#!/usr/bin/env python3
"""Deterministic statement-to-citation audit sealing and replay."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "ReportCitationAudit/v1"
SCHEMA_VERSION = "1"
REPORT_SCHEMA = "ResearchReport/v1"
EVIDENCE_SCHEMA = "ReportCitationSet/v1"

PRIVATE_FILE_MODE = 0o600
AT_EMPTY_PATH = 0x1000
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
}
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|password|passwd|secret|token)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
PRIVATE_PATH_PATTERNS = (
    re.compile(
        r"(?:^|[\s'\"(])/(?!/)[A-Za-z0-9._-]+(?:/[A-Za-z0-9._~ -]+)+"
    ),
    re.compile(r"(?:^|[\s'\"(])~/(?:[^\s/]+/)*[^\s]+"),
    re.compile(r"\b[A-Za-z]:[\\/][^\s]+"),
    re.compile(r"(?:^|[\s'\"(])(?:\.\.[\\/])+(?:[^\s'\"()]+)"),
    re.compile(r"(?:^|[\s'\"(])\\\\[^\\\s]+\\[^\s]+"),
    re.compile(r"(?:^|[\s'\"(])//[^/\s]+/[^\s]+"),
    re.compile(r"\bfile://", re.IGNORECASE),
)

STATEMENT_STATUSES = {"decisive", "qualified"}
DECISION_IMPACTS = {"high", "medium", "low"}
SOURCE_ACCESS = {"full_text", "abstract_only", "metadata_only"}
RELATIONS = {"supports", "contradicts", "qualifies", "not_tested"}
ENTAILMENTS = {"entailed", "partial", "not_entailed", "unknown"}
SOURCE_ROLES = {"primary", "secondary"}
COUNTEREVIDENCE_STATUSES = {"represented", "missing", "not_required"}
REPORT_FIELDS = {
    "schema",
    "schema_version",
    "report_id",
    "report_text",
    "statement_rows",
}
STATEMENT_FIELDS = {
    "statement_id",
    "statement_text",
    "start_char",
    "end_char",
    "decision_impact",
    "status",
}
EVIDENCE_FIELDS = {
    "schema",
    "schema_version",
    "citations",
}
CITATION_FIELDS = {
    "citation_id",
    "statement_id",
    "source_id",
    "source_version",
    "source_access",
    "locator",
    "relation",
    "entailment",
    "missing_qualifier",
    "source_role",
    "counterevidence_status",
    "evidence_path",
    "evidence_raw_sha256",
}
AUDIT_FIELDS = {
    "schema",
    "schema_version",
    "report_id",
    "projection",
    "projection_digest",
    "overall_status",
    "metrics",
    "private",
    "audit_id",
    "audit_digest",
}
AUDIT_PRIVATE_FIELDS = {
    "final_report",
    "draft_report",
    "evidence_manifest",
    "evidence_files",
}
REPORT_BINDING_FIELDS = {"path", "raw_sha256"}


class ContractError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_hex(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _reject_duplicate_json_key_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ContractError(f"duplicate JSON key: {key!r}")
        output[key] = value
    return output


def _load_json_bytes(payload: bytes, path: Path, *, label: str) -> dict[str, Any]:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_key_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is invalid JSON: {path}") from exc


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a list")
    return value


def _require_string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    value = value.strip()
    if nonempty and not value:
        raise ContractError(f"{label} must be non-empty")
    return value


def _require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{label} must be an integer")
    return value


def _require_hex(value: Any, label: str) -> str:
    text = _require_string(value, label, nonempty=True)
    if not HEX_RE.fullmatch(text):
        raise ContractError(f"{label} must be lowercase 64-hex")
    return text


def _stat_fingerprint(state: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        state.st_dev,
        state.st_ino,
        state.st_size,
        state.st_mtime_ns,
        state.st_ctime_ns,
    )


def _scan_forbidden_keys(value: Any, label: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{label} keys must be strings")
            if key.casefold() in FORBIDDEN_KEYS:
                raise ContractError(f"{label} contains forbidden key {key!r}")
            _scan_forbidden_keys(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{label}[{index}]")
    elif isinstance(value, str) and any(
        pattern.search(value) for pattern in FORBIDDEN_VALUE_PATTERNS
    ):
        raise ContractError(f"{label} contains credential-shaped value")


def _scan_private_path_leaks(value: Any, label: str = "projection") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _scan_private_path_leaks(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_private_path_leaks(item, f"{label}[{index}]")
    elif isinstance(value, str) and any(
        pattern.search(value) for pattern in PRIVATE_PATH_PATTERNS
    ):
        raise ContractError(f"{label} contains a private path-shaped value")


def _check_required_keys(value: dict[str, Any], label: str, required: set[str]) -> None:
    missing = sorted(required - value.keys())
    if missing:
        raise ContractError(f"{label} missing required keys: {', '.join(missing)}")


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError as exc:
        raise ContractError(f"cannot compare file identities: {left}, {right}") from exc


def _link_unnamed_file(
    descriptor: int, directory_descriptor: int, output_name: bytes
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    linkat = libc.linkat
    linkat.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    linkat.restype = ctypes.c_int
    if linkat(
        descriptor,
        ctypes.c_char_p(b""),
        directory_descriptor,
        ctypes.c_char_p(output_name),
        AT_EMPTY_PATH,
    ) != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(os.fsdecode(output_name))
        raise OSError(
            error_number,
            os.strerror(error_number),
            os.fsdecode(output_name),
        )


def _to_absolute_non_symlink_file(path_value: str, *, label: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise ContractError(f"{label} must be absolute: {path}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"{label} is unavailable: {path}") from exc
    if resolved != path:
        raise ContractError(
            f"{label} must be a regular non-symlink path without symlink ancestors: {path}"
        )
    try:
        pre_stat = path.lstat()
    except OSError as exc:
        raise ContractError(f"{label} is unavailable: {path}") from exc
    if stat.S_ISLNK(pre_stat.st_mode):
        raise ContractError(f"{label} must be a regular non-symlink file: {path}")
    if not stat.S_ISREG(pre_stat.st_mode):
        raise ContractError(f"{label} must be a regular file: {path}")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ContractError("platform lacks O_NOFOLLOW")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
    try:
        descriptor_stat = os.fstat(descriptor)
        if _stat_fingerprint(pre_stat) != _stat_fingerprint(descriptor_stat):
            raise ContractError(f"{label} changed between stat and open: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        contents = b"".join(chunks)
        after_stat = os.fstat(descriptor)
        if _stat_fingerprint(descriptor_stat) != _stat_fingerprint(after_stat):
            raise ContractError(f"{label} changed during read: {path}")
        if after_stat.st_size != len(contents):
            raise ContractError(f"{label} length changed during read: {path}")
    finally:
        os.close(descriptor)
    return path, contents


def _write_private_json(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        raise ContractError(f"refusing to overwrite output: {path}")
    if not path.parent.is_dir():
        raise ContractError(f"output parent must already be a directory: {path.parent}")
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"output parent is unavailable: {path.parent}") from exc
    if resolved_parent != path.parent:
        raise ContractError(f"output parent must not traverse symbolic links: {path.parent}")
    payload = canonical_json_bytes(value) + b"\n"
    directory_descriptor = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    descriptor = -1
    temporary: Path | None = None
    try:
        if hasattr(os, "O_TMPFILE"):
            try:
                descriptor = os.open(
                    path.parent,
                    os.O_TMPFILE | os.O_WRONLY | os.O_CLOEXEC,
                    PRIVATE_FILE_MODE,
                )
            except OSError as exc:
                unsupported = {
                    errno.EINVAL,
                    errno.EISDIR,
                    getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
                    errno.EOPNOTSUPP,
                }
                if exc.errno not in unsupported:
                    raise
        if descriptor < 0:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", dir=path.parent
            )
            temporary = Path(temporary_name)
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        published_stat = os.fstat(descriptor)
        try:
            if temporary is None:
                _link_unnamed_file(
                    descriptor, directory_descriptor, os.fsencode(path.name)
                )
            else:
                os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise ContractError(f"refusing to overwrite output: {path}") from exc
        linked_stat = os.stat(
            path.name, dir_fd=directory_descriptor, follow_symlinks=False
        )
        if not stat.S_ISREG(linked_stat.st_mode) or (
            linked_stat.st_dev,
            linked_stat.st_ino,
            linked_stat.st_size,
        ) != (
            published_stat.st_dev,
            published_stat.st_ino,
            published_stat.st_size,
        ):
            raise ContractError(
                f"published output identity changed before verification: {path}"
            )
        if temporary is not None:
            temporary_stat = temporary.lstat()
            if (
                temporary_stat.st_dev,
                temporary_stat.st_ino,
            ) == (published_stat.st_dev, published_stat.st_ino):
                temporary.unlink()
                temporary = None
        os.fsync(directory_descriptor)
    finally:
        if descriptor >= 0:
            published_stat = os.fstat(descriptor)
            if temporary is not None and temporary.exists():
                temporary_stat = temporary.lstat()
                if (
                    temporary_stat.st_dev,
                    temporary_stat.st_ino,
                ) == (published_stat.st_dev, published_stat.st_ino):
                    temporary.unlink()
            os.close(descriptor)
        os.close(directory_descriptor)


def _validate_report(report: dict[str, Any]) -> dict[str, Any]:
    _check_required_keys(report, "report", REPORT_FIELDS)
    if set(report.keys()) != REPORT_FIELDS:
        raise ContractError("report must contain exact required keys")
    if report.get("schema") != REPORT_SCHEMA:
        raise ContractError(f"report.schema must be {REPORT_SCHEMA}")
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("report.schema_version must be 1")

    report_text = _require_string(report.get("report_text"), "report.report_text")
    report_id = _require_string(report.get("report_id"), "report.report_id")
    raw_rows = _require_list(report.get("statement_rows"), "report.statement_rows")
    if not raw_rows:
        raise ContractError("report.statement_rows must not be empty")

    rows: list[dict[str, Any]] = []
    seen_statement_ids: set[str] = set()
    for index, row_raw in enumerate(raw_rows):
        label = f"statement_rows[{index}]"
        row = _require_dict(row_raw, label)
        _check_required_keys(row, f"{label}", STATEMENT_FIELDS)
        if set(row.keys()) != STATEMENT_FIELDS:
            raise ContractError(f"{label} must contain exactly: {', '.join(sorted(STATEMENT_FIELDS))}")
        statement_id = _require_string(row.get("statement_id"), f"{label}.statement_id")
        if statement_id in seen_statement_ids:
            raise ContractError(f"duplicate statement_id: {statement_id}")
        seen_statement_ids.add(statement_id)

        statement_text = _require_string(
            row.get("statement_text"), f"{label}.statement_text"
        )
        start_char = _require_int(row.get("start_char"), f"{label}.start_char")
        end_char = _require_int(row.get("end_char"), f"{label}.end_char")
        if start_char < 0 or end_char < 0 or end_char < start_char:
            raise ContractError(f"{label}.{statement_id} span is invalid")
        if end_char > len(report_text):
            raise ContractError(f"{label}.{statement_id} span exceeds report text")
        if report_text[start_char:end_char] != statement_text:
            raise ContractError(
                f"{label}.{statement_id} statement_text does not match report text slice"
            )

        decision_impact = _require_string(
            row.get("decision_impact"), f"{label}.{statement_id}.decision_impact"
        )
        if decision_impact not in DECISION_IMPACTS:
            raise ContractError(
                f"{label}.{statement_id}.decision_impact must be one of {sorted(DECISION_IMPACTS)}"
            )
        status = _require_string(
            row.get("status"), f"{label}.{statement_id}.status"
        ).lower()
        if status not in STATEMENT_STATUSES:
            raise ContractError(
                f"{label}.{statement_id}.status must be one of {sorted(STATEMENT_STATUSES)}"
            )

        rows.append(
            {
                "statement_id": statement_id,
                "statement_text": statement_text,
                "start_char": start_char,
                "end_char": end_char,
                "decision_impact": decision_impact,
                "status": status,
            }
        )

    rows = sorted(rows, key=lambda item: (item["start_char"], item["statement_id"]))
    for index in range(1, len(rows)):
        if rows[index]["start_char"] < rows[index - 1]["end_char"]:
            raise ContractError(
                "statement span overlap between "
                f"{rows[index - 1]['statement_id']} and {rows[index]['statement_id']}"
            )

    return {
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "report_text": report_text,
        "statement_rows": rows,
    }


def _validate_evidence(
    evidence: dict[str, Any],
    statement_ids: set[str],
    *,
    final_report_path: Path,
    draft_report_path: Path,
    audit_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    _check_required_keys(evidence, "evidence", EVIDENCE_FIELDS)
    if set(evidence.keys()) != EVIDENCE_FIELDS:
        raise ContractError("evidence must contain exact required keys")
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        raise ContractError(f"evidence.schema must be {EVIDENCE_SCHEMA}")
    if evidence.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("evidence.schema_version must be 1")

    rows_raw = _require_list(evidence.get("citations"), "evidence.citations")
    if not rows_raw:
        raise ContractError("evidence.citations must not be empty")

    statements: set[str] = set()
    output_rows: list[dict[str, Any]] = []
    evidence_files: dict[str, dict[str, str]] = {}
    for index, row_raw in enumerate(rows_raw):
        label = f"evidence.citations[{index}]"
        row = _require_dict(row_raw, label)
        _check_required_keys(row, label, CITATION_FIELDS)
        if set(row.keys()) != CITATION_FIELDS:
            raise ContractError(
                f"{label} must contain exactly: {', '.join(sorted(CITATION_FIELDS))}"
            )

        citation_id = _require_string(row.get("citation_id"), f"{label}.citation_id")
        if citation_id in statements:
            raise ContractError(f"duplicate citation_id: {citation_id}")
        statements.add(citation_id)

        statement_id = _require_string(row.get("statement_id"), f"{label}.statement_id")
        if statement_id not in statement_ids:
            raise ContractError(f"{label}.statement_id does not exist in report rows")

        source_access = _require_string(row.get("source_access"), f"{label}.source_access")
        if source_access not in SOURCE_ACCESS:
            raise ContractError(
                f"{label}.source_access must be one of {sorted(SOURCE_ACCESS)}"
            )

        relation = _require_string(row.get("relation"), f"{label}.relation")
        if relation not in RELATIONS:
            raise ContractError(f"{label}.relation must be one of {sorted(RELATIONS)}")

        entailment = _require_string(row.get("entailment"), f"{label}.entailment")
        if entailment not in ENTAILMENTS:
            raise ContractError(f"{label}.entailment must be one of {sorted(ENTAILMENTS)}")

        source_role = _require_string(row.get("source_role"), f"{label}.source_role")
        if source_role not in SOURCE_ROLES:
            raise ContractError(f"{label}.source_role must be one of {sorted(SOURCE_ROLES)}")

        counterevidence_status = _require_string(
            row.get("counterevidence_status"), f"{label}.counterevidence_status"
        )
        if counterevidence_status not in COUNTEREVIDENCE_STATUSES:
            raise ContractError(
                f"{label}.counterevidence_status must be one of {sorted(COUNTEREVIDENCE_STATUSES)}"
            )

        evidence_path = _to_absolute_non_symlink_file(
            _require_string(row.get("evidence_path"), f"{label}.evidence_path"),
            label=f"{label}.evidence_path",
        )[0]
        if _same_file(evidence_path, final_report_path) or _same_file(
            evidence_path, draft_report_path
        ):
            raise ContractError("evidence_path cannot point to report inputs")
        if audit_path is not None and _same_file(evidence_path, audit_path):
            raise ContractError("evidence file cannot be the audit artifact")

        evidence_raw_sha256 = _require_hex(
            row.get("evidence_raw_sha256"), f"{label}.evidence_raw_sha256"
        )
        evidence_raw = _to_absolute_non_symlink_file(
            str(evidence_path), label=f"{label}.evidence_path"
        )[1]
        if evidence_raw_sha256 != sha256_hex(evidence_raw):
            raise ContractError(f"{label} evidence_raw_sha256 mismatch")

        output_rows.append(
            {
                "citation_id": citation_id,
                "statement_id": statement_id,
                "source_id": _require_string(row.get("source_id"), f"{label}.source_id"),
                "source_version": _require_string(
                    row.get("source_version"), f"{label}.source_version"
                ),
                "source_access": source_access,
                "locator": _require_string(row.get("locator"), f"{label}.locator"),
                "relation": relation,
                "entailment": entailment,
                "missing_qualifier": _require_string(
                    row.get("missing_qualifier"),
                    f"{label}.missing_qualifier",
                    nonempty=False,
                ),
                "source_role": source_role,
                "counterevidence_status": counterevidence_status,
            }
        )
        evidence_files[citation_id] = {
            "path": str(evidence_path),
            "sha256": evidence_raw_sha256,
        }

    return output_rows, evidence_files


def _statement_outcome(
    statement: dict[str, Any],
    citations: list[dict[str, Any]],
) -> tuple[str, bool]:
    if any(
        citation["source_access"] == "abstract_only"
        and citation["relation"] in {"supports", "contradicts", "qualifies"}
        for citation in citations
    ):
        raise ContractError(
            f"decisive statement {statement['statement_id']} uses abstract_only evidence"
        )

    if not citations:
        return "partial", False

    if any(
        citation["relation"] == "contradicts"
        and citation["entailment"] in {"entailed", "partial"}
        for citation in citations
    ):
        return "failed", False

    support = [
        citation
        for citation in citations
        if citation["relation"] in {"supports", "qualifies"}
    ]
    if not support:
        return "partial", False
    if any(citation["entailment"] != "entailed" for citation in support):
        return "partial", False
    if any(citation["missing_qualifier"] for citation in support):
        return "partial", False

    closure_support = [
        citation
        for citation in support
        if citation["source_access"] == "full_text"
        and citation["source_role"] == "primary"
    ]
    if not closure_support:
        return "partial", False

    if any(
        citation["counterevidence_status"] == "missing"
        for citation in support
    ):
        return "partial", True

    return statement["status"], False


def _compute_outcomes(
    statement_rows: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, bool], str]:
    by_statement: dict[str, list[dict[str, Any]]] = {
        row["statement_id"]: [] for row in statement_rows
    }
    for citation in citations:
        by_statement[citation["statement_id"]].append(citation)

    outcomes: dict[str, str] = {}
    blocked: dict[str, bool] = {}
    for row in statement_rows:
        outcome, is_blocked = _statement_outcome(row, by_statement[row["statement_id"]])
        outcomes[row["statement_id"]] = outcome
        blocked[row["statement_id"]] = is_blocked

    if any(value == "failed" for value in outcomes.values()):
        overall = "failed"
    elif any(value == "partial" for value in outcomes.values()):
        overall = "partial"
    else:
        overall = "complete"
    return outcomes, blocked, overall


def _build_projection(
    statement_rows: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    outcomes: dict[str, str],
) -> list[dict[str, Any]]:
    by_statement: dict[str, list[dict[str, Any]]] = {
        row["statement_id"]: [] for row in statement_rows
    }
    for citation in citations:
        by_statement[citation["statement_id"]].append(citation)

    projection: list[dict[str, Any]] = []
    for row in statement_rows:
        statement_id = row["statement_id"]
        related = sorted(by_statement[statement_id], key=lambda item: item["citation_id"])
        projection.append(
            {
                "statement_id": statement_id,
                "statement_text": row["statement_text"],
                "span": {
                    "start_char": row["start_char"],
                    "end_char": row["end_char"],
                },
                "decision_impact": row["decision_impact"],
                "status": row["status"],
                "outcome": outcomes[statement_id],
                "citations": [
                    {
                        "citation_id": citation["citation_id"],
                        "source_id": citation["source_id"],
                        "source_version": citation["source_version"],
                        "source_access": citation["source_access"],
                        "locator": citation["locator"],
                        "relation": citation["relation"],
                        "entailment": citation["entailment"],
                        "missing_qualifier": citation["missing_qualifier"],
                        "source_role": citation["source_role"],
                        "counterevidence_status": citation["counterevidence_status"],
                    }
                    for citation in related
                ],
            }
        )
    return projection


def _metrics(
    statement_rows: list[dict[str, Any]],
    outcomes: dict[str, str],
    citations: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "statement_count": len(statement_rows),
        "citation_count": len(citations),
        "decisive_statement_count": sum(
            1 for state in outcomes.values() if state == "decisive"
        ),
        "qualified_statement_count": sum(
            1 for state in outcomes.values() if state == "qualified"
        ),
        "partial_statement_count": sum(
            1 for state in outcomes.values() if state == "partial"
        ),
        "failed_statement_count": sum(
            1 for state in outcomes.values() if state == "failed"
        ),
        "primary_citation_count": sum(
            1 for citation in citations if citation["source_role"] == "primary"
        ),
        "secondary_citation_count": sum(
            1 for citation in citations if citation["source_role"] == "secondary"
        ),
        "counterevidence_missing_count": sum(
            1
            for citation in citations
            if citation["counterevidence_status"] == "missing"
        ),
        "high_impact_decisive_count": sum(
            1
            for row in statement_rows
            if row["decision_impact"] == "high" and outcomes[row["statement_id"]] == "decisive"
        ),
    }


def _projection_digest(projection: list[dict[str, Any]]) -> str:
    return sha256_hex(canonical_json_bytes(projection))


def _seal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop("audit_id", None)
    unsigned.pop("audit_digest", None)
    digest = sha256_hex(canonical_json_bytes(unsigned))
    payload = dict(payload)
    payload["audit_id"] = f"report-citation-audit-{digest[:16]}"
    payload["audit_digest"] = digest
    return payload


def _validate_audit(value: dict[str, Any], *, audit_path: Path) -> dict[str, Any]:
    _check_required_keys(value, "audit", AUDIT_FIELDS)
    if set(value.keys()) != AUDIT_FIELDS:
        raise ContractError("audit must contain exact required keys")
    if value.get("schema") != SCHEMA:
        raise ContractError(f"audit.schema must be {SCHEMA}")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("audit.schema_version must be 1")

    private = _require_dict(value.get("private"), "audit.private")
    if set(private.keys()) != AUDIT_PRIVATE_FIELDS:
        raise ContractError("audit.private must contain exact required fields")
    for key in ("final_report", "draft_report", "evidence_manifest"):
        _check_required_keys(
            _require_dict(private.get(key), f"audit.private.{key}"),
            f"audit.private.{key}",
            REPORT_BINDING_FIELDS,
        )
    for source, binding in private["evidence_files"].items():
        if not isinstance(source, str) or not source.strip():
            raise ContractError("audit.private.evidence_files keys must be non-empty strings")
        _check_required_keys(
            _require_dict(binding, f"audit.private.evidence_files[{source}]"),
            f"audit.private.evidence_files[{source}]",
            {"path", "sha256"},
        )
        _require_string(binding["path"], f"audit.private.evidence_files[{source}].path")
        _require_hex(binding["sha256"], f"audit.private.evidence_files[{source}].sha256")
        if Path(binding["path"]).resolve() == audit_path:
            raise ContractError("audit private evidence path cannot be audit artifact")
        if not Path(binding["path"]).is_absolute():
            raise ContractError("audit.private.evidence_files paths must be absolute")

    _check_required_keys(
        _require_dict(private.get("evidence_manifest"), "audit.private.evidence_manifest"),
        "audit.private.evidence_manifest",
        REPORT_BINDING_FIELDS,
    )
    for item_key in ("final_report", "draft_report"):
        report_binding = _require_dict(private[item_key], f"audit.private.{item_key}")
        if report_binding.get("path") == str(audit_path):
            raise ContractError("audit path cannot be reused as report binding")
        _require_string(report_binding.get("path"), f"audit.private.{item_key}.path")
        _require_hex(report_binding.get("raw_sha256"), f"audit.private.{item_key}.raw_sha256")

    manifest_binding = private["evidence_manifest"]
    _require_string(manifest_binding.get("path"), "audit.private.evidence_manifest.path")
    _require_hex(manifest_binding.get("raw_sha256"), "audit.private.evidence_manifest.raw_sha256")

    digest_payload = dict(value)
    digest_payload.pop("audit_id", None)
    digest_payload.pop("audit_digest", None)
    if value.get("audit_digest") != sha256_hex(canonical_json_bytes(digest_payload)):
        raise ContractError("audit_digest mismatch")
    if value.get("audit_id") != f"report-citation-audit-{value['audit_digest'][:16]}":
        raise ContractError("audit_id mismatch")
    return value


def _read_and_validate_report(path: Path, raw_pin: str) -> tuple[dict[str, Any], str]:
    report_path, report_raw = _to_absolute_non_symlink_file(str(path), label=f"report {path}")
    if sha256_hex(report_raw) != raw_pin:
        raise ContractError("report raw pin mismatch")
    report = _load_json_bytes(report_raw, report_path, label="report")
    _scan_forbidden_keys(report)
    return _validate_report(report), sha256_hex(report_raw)


def _read_and_validate_evidence(
    path: str,
    pin: str,
    statement_ids: set[str],
    *,
    final_report_path: Path,
    draft_report_path: Path,
    audit_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], str]:
    evidence_path, evidence_raw = _to_absolute_non_symlink_file(
        path, label="evidence manifest"
    )
    actual_pin = sha256_hex(evidence_raw)
    if actual_pin != pin:
        raise ContractError("evidence manifest raw pin mismatch")
    evidence = _load_json_bytes(evidence_raw, evidence_path, label="evidence manifest")
    _scan_forbidden_keys(evidence)
    citations, bindings = _validate_evidence(
        evidence,
        statement_ids,
        final_report_path=final_report_path,
        draft_report_path=draft_report_path,
        audit_path=audit_path,
    )
    return citations, bindings, actual_pin


def _run_seal(
    *,
    final_report: Path,
    draft_report: Path,
    evidence_manifest: Path,
    final_report_raw_sha256: str,
    draft_report_raw_sha256: str,
    evidence_raw_sha256: str,
    output: Path,
) -> None:
    final_report_payload, final_pin = _read_and_validate_report(
        final_report, _require_hex(final_report_raw_sha256, "final-report-raw-sha256")
    )
    draft_report_payload, draft_pin = _read_and_validate_report(
        draft_report, _require_hex(draft_report_raw_sha256, "draft-report-raw-sha256")
    )
    if final_report_payload["report_id"] != draft_report_payload["report_id"]:
        raise ContractError("final and draft report ids differ")

    if _same_file(final_report, draft_report):
        raise ContractError("final and draft reports must be distinct files")

    if _same_file(evidence_manifest, final_report) or _same_file(
        evidence_manifest, draft_report
    ):
        raise ContractError("evidence manifest must be distinct from report inputs")

    citations, evidence_files, evidence_manifest_pin = _read_and_validate_evidence(
        str(evidence_manifest),
        _require_hex(evidence_raw_sha256, "evidence-raw-sha256"),
        {row["statement_id"] for row in final_report_payload["statement_rows"]},
        final_report_path=final_report,
        draft_report_path=draft_report,
    )
    evidence_path = Path(evidence_manifest).expanduser().absolute()

    outcomes, blocked, overall_status = _compute_outcomes(
        final_report_payload["statement_rows"], citations
    )
    projection = _build_projection(
        final_report_payload["statement_rows"], citations, outcomes
    )
    _scan_private_path_leaks(projection)
    projection_digest = _projection_digest(projection)
    metric_payload = _metrics(final_report_payload["statement_rows"], outcomes, citations)

    del blocked
    payload = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "report_id": final_report_payload["report_id"],
        "projection": projection,
        "projection_digest": projection_digest,
        "overall_status": overall_status,
        "metrics": metric_payload,
        "private": {
            "final_report": {
                "path": str(final_report),
                "raw_sha256": final_pin,
            },
            "draft_report": {
                "path": str(draft_report),
                "raw_sha256": draft_pin,
            },
            "evidence_manifest": {
                "path": str(evidence_path),
                "raw_sha256": evidence_manifest_pin,
            },
            "evidence_files": evidence_files,
        },
    }
    _scan_forbidden_keys(payload)
    payload = _seal_payload(payload)
    _write_private_json(output, payload)


def _run_validate(
    *,
    audit: Path,
    final_report: Path,
    draft_report: Path,
    final_report_raw_sha256: str,
    draft_report_raw_sha256: str,
    evidence_raw_sha256: str,
    audit_raw_sha256: str,
) -> dict[str, Any]:
    audit_path, audit_raw = _to_absolute_non_symlink_file(str(audit), label="audit")
    if sha256_hex(audit_raw) != _require_hex(audit_raw_sha256, "audit-raw-sha256"):
        raise ContractError("audit raw pin mismatch")
    audit_json = _load_json_bytes(audit_raw, audit_path, label="audit")
    _scan_forbidden_keys(audit_json)
    audit = _validate_audit(audit_json, audit_path=audit_path)

    if _same_file(audit_path, final_report) or _same_file(audit_path, draft_report):
        raise ContractError("audit must be distinct from report inputs")
    if _same_file(final_report, draft_report):
        raise ContractError("final and draft reports must be distinct files")

    private = _require_dict(audit["private"], "audit.private")
    final_binding = _require_dict(private["final_report"], "audit.private.final_report")
    draft_binding = _require_dict(private["draft_report"], "audit.private.draft_report")
    manifest_binding = _require_dict(
        private["evidence_manifest"], "audit.private.evidence_manifest"
    )
    evidence_bindings = _require_dict(
        private["evidence_files"], "audit.private.evidence_files"
    )

    if final_binding["path"] != str(final_report):
        raise ContractError("final report path does not match audit binding")
    if draft_binding["path"] != str(draft_report):
        raise ContractError("draft report path does not match audit binding")

    final_report_payload, final_pin = _read_and_validate_report(
        final_report, _require_hex(final_report_raw_sha256, "final-report-raw-sha256")
    )
    if final_pin != final_binding["raw_sha256"]:
        raise ContractError("final report raw sha mismatch")
    draft_report_payload, draft_pin = _read_and_validate_report(
        draft_report, _require_hex(draft_report_raw_sha256, "draft-report-raw-sha256")
    )
    if draft_pin != draft_binding["raw_sha256"]:
        raise ContractError("draft report raw sha mismatch")
    if final_report_payload["report_id"] != draft_report_payload["report_id"]:
        raise ContractError("final and draft reports describe different report ids")
    if final_report_payload["report_id"] != audit["report_id"]:
        raise ContractError("audit report id does not match final report")
    if final_report != Path(final_binding["path"]) or draft_report != Path(draft_binding["path"]):
        raise ContractError("final/draft report inputs do not match audit binding")

    evidence_raw_sha256 = _require_hex(evidence_raw_sha256, "evidence-raw-sha256")
    if evidence_raw_sha256 != manifest_binding["raw_sha256"]:
        raise ContractError("evidence manifest raw pin mismatch")
    citations, evidence_files, manifest_pin = _read_and_validate_evidence(
        manifest_binding["path"],
        evidence_raw_sha256,
        {row["statement_id"] for row in final_report_payload["statement_rows"]},
        final_report_path=final_report,
        draft_report_path=draft_report,
        audit_path=audit_path,
    )
    if manifest_pin != manifest_binding["raw_sha256"]:
        raise ContractError("evidence manifest raw pin mismatch")
    if sorted(evidence_files.keys()) != sorted(evidence_bindings.keys()):
        raise ContractError("evidence file binding keys mismatch")
    for citation_id, bind in evidence_bindings.items():
        if Path(bind["path"]) == audit_path:
            raise ContractError("evidence file cannot point to audit artifact")
        if bind["path"] != evidence_files[citation_id]["path"]:
            raise ContractError(f"evidence binding path changed for {citation_id}")
        if bind["sha256"] != evidence_files[citation_id]["sha256"]:
            raise ContractError(f"evidence binding changed for {citation_id}")

    outcomes, blocked, overall_status = _compute_outcomes(
        final_report_payload["statement_rows"], citations
    )
    projection = _build_projection(
        final_report_payload["statement_rows"], citations, outcomes
    )
    _scan_private_path_leaks(projection)
    projection_digest = _projection_digest(projection)
    if projection_digest != audit["projection_digest"]:
        raise ContractError("projection digest mismatch")
    if projection != audit["projection"]:
        raise ContractError("projection mismatch")
    if overall_status != audit["overall_status"]:
        raise ContractError("overall_status mismatch")
    metric_payload = _metrics(final_report_payload["statement_rows"], outcomes, citations)
    if metric_payload != audit["metrics"]:
        raise ContractError("metrics mismatch")

    return {
        "valid": True,
        "audit_id": audit["audit_id"],
        "report_id": audit["report_id"],
        "overall_status": overall_status,
        "statement_status": outcomes,
        "counterevidence_blocked": blocked,
        "projection_digest": projection_digest,
        "metrics": metric_payload,
    }


def validate_audit_binding(
    *,
    audit: Path,
    final_report: Path,
    draft_report: Path,
    final_report_raw_sha256: str,
    draft_report_raw_sha256: str,
    evidence_raw_sha256: str,
    audit_raw_sha256: str,
) -> dict[str, Any]:
    """Replay one externally pinned citation audit through its public owner seam."""

    return _run_validate(
        audit=audit,
        final_report=final_report,
        draft_report=draft_report,
        final_report_raw_sha256=final_report_raw_sha256,
        draft_report_raw_sha256=draft_report_raw_sha256,
        evidence_raw_sha256=evidence_raw_sha256,
        audit_raw_sha256=audit_raw_sha256,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal = subparsers.add_parser("seal")
    seal.add_argument("--final-report", required=True)
    seal.add_argument("--draft-report", required=True)
    seal.add_argument("--evidence", required=True)
    seal.add_argument("--evidence-raw-sha256", required=True)
    seal.add_argument("--final-report-raw-sha256", required=True)
    seal.add_argument("--draft-report-raw-sha256", required=True)
    seal.add_argument("--output", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--audit", required=True)
    validate.add_argument("--final-report", required=True)
    validate.add_argument("--draft-report", required=True)
    validate.add_argument("--final-report-raw-sha256", required=True)
    validate.add_argument("--draft-report-raw-sha256", required=True)
    validate.add_argument("--evidence-raw-sha256", required=True)
    validate.add_argument("--audit-raw-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "seal":
            _run_seal(
                final_report=Path(args.final_report).expanduser().absolute(),
                draft_report=Path(args.draft_report).expanduser().absolute(),
                evidence_manifest=Path(args.evidence).expanduser().absolute(),
                final_report_raw_sha256=args.final_report_raw_sha256,
                draft_report_raw_sha256=args.draft_report_raw_sha256,
                evidence_raw_sha256=args.evidence_raw_sha256,
                output=Path(args.output).expanduser().absolute(),
            )
            return 0

        report = _run_validate(
            audit=Path(args.audit).expanduser().absolute(),
            final_report=Path(args.final_report).expanduser().absolute(),
            draft_report=Path(args.draft_report).expanduser().absolute(),
            final_report_raw_sha256=args.final_report_raw_sha256,
            draft_report_raw_sha256=args.draft_report_raw_sha256,
            evidence_raw_sha256=args.evidence_raw_sha256,
            audit_raw_sha256=args.audit_raw_sha256,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (ContractError, OSError, json.JSONDecodeError):
        print(f"report-citation-audit failed: {sys.exc_info()[1]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
