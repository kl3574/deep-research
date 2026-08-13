#!/usr/bin/env python3
"""Build and replay deterministic evidence-bound research workflow reviews."""

from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


BUNDLE_SCHEMA = "ResearchWorkflowEvidenceBundle/v1"
REVIEW_SCHEMA = "ResearchWorkflowReview/v1"
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
IMPACTS = {"high": 3, "medium": 2, "low": 1}
RECURRENCES = {"repeated": 2, "potential": 1, "once": 0}
REPRODUCIBILITY = {"reproduced": 2, "not_applicable": 1, "not_reproduced": 0}
CLASSIFICATIONS = {
    "contract_seam",
    "implementation_bug",
    "workflow_state",
    "coordination",
    "presentation",
    "operational_delivery",
    "one_off_environment",
}
CHANGE_KINDS = {
    "owner_contract",
    "shared_contract",
    "orchestration_contract",
    "new_skill",
    "tests_only",
    "docs_only",
    "local_repair",
    "no_change",
}
EVIDENCE_LEVELS = {
    "official_documentation",
    "official_engineering",
    "primary_research",
    "owner_repository",
}
AT_EMPTY_PATH = 0x1000
_CREDENTIAL_KEYS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "authorization",
    "cookie",
    "privatekey",
    "credential",
    "accesskey",
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"\b(?:api[_-]?key|password|passwd|secret|token)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE),
)


class RetrospectiveError(ValueError):
    """Raised when a retrospective contract fails closed."""


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


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise RetrospectiveError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RetrospectiveError("artifact is not canonical JSON data") from exc


def _raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX_RE.fullmatch(value):
        raise RetrospectiveError(f"{label} must be 64 lowercase hex characters")
    return value


def _check_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrospectiveError(f"{label} must be a non-empty string")
    return value


def _check_id(value: Any, label: str) -> str:
    text = _check_text(value, label)
    if not ID_RE.fullmatch(text):
        raise RetrospectiveError(f"{label} must be a safe stable identifier")
    return text


def _check_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise RetrospectiveError(
            f"{label} keys differ; missing={missing}, unknown={unknown}"
        )


def _scan_credentials(value: Any, location: str = "bundle") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            compact = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(part in compact for part in _CREDENTIAL_KEYS):
                raise RetrospectiveError(
                    f"credential-shaped key is forbidden at {location}.{key}"
                )
            _scan_credentials(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_credentials(child, f"{location}[{index}]")
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in _CREDENTIAL_PATTERNS):
            raise RetrospectiveError(
                f"credential-shaped value is forbidden at {location}"
            )


def _ordinary_bytes(path_value: Any, label: str) -> tuple[Path, bytes]:
    if isinstance(path_value, os.PathLike):
        path_text = os.fspath(path_value)
    else:
        path_text = _check_text(path_value, f"{label}.path")
    path = Path(path_text)
    if not path.is_absolute():
        raise RetrospectiveError(f"{label}.path must be absolute")
    try:
        resolved = path.resolve(strict=True)
        before = path.lstat()
    except OSError as exc:
        raise RetrospectiveError(f"{label}.path is unavailable") from exc
    if resolved != path:
        raise RetrospectiveError(
            f"{label}.path must not traverse a symlink or path alias"
        )
    if not stat.S_ISREG(before.st_mode):
        raise RetrospectiveError(f"{label}.path must be an ordinary non-symlink file")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RetrospectiveError("platform lacks O_NOFOLLOW")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
    try:
        opened = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(
            getattr(before, field) != getattr(opened, field)
            for field in stable_fields
        ):
            raise RetrospectiveError(f"{label}.path changed between stat and open")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if any(
            getattr(opened, field) != getattr(after, field)
            for field in stable_fields
        ):
            raise RetrospectiveError(f"{label}.path changed while it was read")
        if after.st_size != len(data):
            raise RetrospectiveError(f"{label}.path size changed while it was read")
    finally:
        os.close(descriptor)
    return path, data


def _load_json_file(path_value: Any, label: str) -> tuple[Path, bytes, dict[str, Any]]:
    path, data = _ordinary_bytes(path_value, label)
    try:
        value = json.loads(
            data.decode("utf-8"), object_pairs_hook=_object_without_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetrospectiveError(f"{label}.path must contain UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RetrospectiveError(f"{label}.path top level must be an object")
    return path, data, value


def _validate_ref(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RetrospectiveError(f"{label} must be an object")
    _check_exact_keys(value, {"path", "sha256"}, label)
    _, data = _ordinary_bytes(value.get("path"), label)
    expected = _check_sha(value.get("sha256"), f"{label}.sha256")
    actual = _raw_sha256(data)
    if actual != expected:
        raise RetrospectiveError(f"{label} raw SHA-256 mismatch")
    return {"path": str(value["path"]), "sha256": expected}


def _text_array(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "an array" if allow_empty else "a non-empty array"
        raise RetrospectiveError(f"{label} must be {qualifier}")
    result = [_check_text(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise RetrospectiveError(f"{label} must not contain duplicates")
    return result


def _validate_change(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RetrospectiveError(f"{label} must be an object")
    _check_exact_keys(
        value,
        {"kind", "target", "seam", "acceptance_tests", "negative_tests", "non_goals"},
        label,
    )
    kind = _check_text(value.get("kind"), f"{label}.kind")
    if kind not in CHANGE_KINDS:
        raise RetrospectiveError(f"{label}.kind is invalid")
    return {
        "kind": kind,
        "target": _check_text(value.get("target"), f"{label}.target"),
        "seam": _check_text(value.get("seam"), f"{label}.seam"),
        "acceptance_tests": _text_array(
            value.get("acceptance_tests"), f"{label}.acceptance_tests", allow_empty=True
        ),
        "negative_tests": _text_array(
            value.get("negative_tests"), f"{label}.negative_tests", allow_empty=True
        ),
        "non_goals": _text_array(
            value.get("non_goals"), f"{label}.non_goals", allow_empty=True
        ),
    }


def _priority(
    impact: str,
    recurrence: str,
    reproducibility: str,
    escape_distance: int,
    one_off: bool,
) -> tuple[int, str]:
    score = (
        IMPACTS[impact]
        + RECURRENCES[recurrence]
        + REPRODUCIBILITY[reproducibility]
        + min(escape_distance, 3)
        - (3 if one_off else 0)
    )
    level = "P0" if score >= 8 else "P1" if score >= 5 else "P2"
    return score, level


def _readiness(
    one_off: bool, reproducibility: str, change: Mapping[str, Any]
) -> str:
    if change["kind"] == "no_change":
        return "no_change"
    if one_off:
        return "one_off_local"
    if reproducibility == "not_reproduced":
        return "needs_reproduction"
    if not change["acceptance_tests"] or not change["negative_tests"]:
        return "needs_tests"
    return "ready"


def _validate_incident(
    value: Any, index: int, stage_index: Mapping[str, int]
) -> dict[str, Any]:
    label = f"incidents[{index}]"
    if not isinstance(value, dict):
        raise RetrospectiveError(f"{label} must be an object")
    _check_exact_keys(
        value,
        {
            "incident_key",
            "title",
            "observation",
            "impact",
            "recurrence",
            "classification",
            "owner_skill",
            "detected_stage",
            "earliest_detectable_stage",
            "reproducibility",
            "one_off",
            "evidence_refs",
            "proposed_change",
        },
        label,
    )
    incident_key = _check_id(value.get("incident_key"), f"{label}.incident_key")
    impact = _check_text(value.get("impact"), f"{label}.impact")
    recurrence = _check_text(value.get("recurrence"), f"{label}.recurrence")
    classification = _check_text(
        value.get("classification"), f"{label}.classification"
    )
    reproducibility = _check_text(
        value.get("reproducibility"), f"{label}.reproducibility"
    )
    if impact not in IMPACTS:
        raise RetrospectiveError(f"{label}.impact is invalid")
    if recurrence not in RECURRENCES:
        raise RetrospectiveError(f"{label}.recurrence is invalid")
    if classification not in CLASSIFICATIONS:
        raise RetrospectiveError(f"{label}.classification is invalid")
    if reproducibility not in REPRODUCIBILITY:
        raise RetrospectiveError(f"{label}.reproducibility is invalid")
    owner = _check_id(value.get("owner_skill"), f"{label}.owner_skill")
    detected = _check_id(value.get("detected_stage"), f"{label}.detected_stage")
    earliest = _check_id(
        value.get("earliest_detectable_stage"),
        f"{label}.earliest_detectable_stage",
    )
    if detected not in stage_index or earliest not in stage_index:
        raise RetrospectiveError(f"{label} stages must occur in stage_order")
    if stage_index[earliest] > stage_index[detected]:
        raise RetrospectiveError(
            f"{label}.earliest_detectable_stage must not follow detected_stage"
        )
    one_off = value.get("one_off")
    if not isinstance(one_off, bool):
        raise RetrospectiveError(f"{label}.one_off must be boolean")
    refs_value = value.get("evidence_refs")
    if not isinstance(refs_value, list) or not refs_value:
        raise RetrospectiveError(f"{label}.evidence_refs must be a non-empty array")
    refs = [
        _validate_ref(ref, f"{label}.evidence_refs[{ref_index}]")
        for ref_index, ref in enumerate(refs_value)
    ]
    refs = sorted(refs, key=lambda item: (item["path"], item["sha256"]))
    ref_keys = [(ref["path"], ref["sha256"]) for ref in refs]
    if len(ref_keys) != len(set(ref_keys)):
        raise RetrospectiveError(f"{label}.evidence_refs must not contain duplicates")
    ref_hashes = sorted(ref["sha256"] for ref in refs)
    change = _validate_change(value.get("proposed_change"), f"{label}.proposed_change")
    escape_distance = stage_index[detected] - stage_index[earliest]
    score, priority = _priority(
        impact, recurrence, reproducibility, escape_distance, one_off
    )
    return {
        "incident_key": incident_key,
        "title": _check_text(value.get("title"), f"{label}.title"),
        "observation": _check_text(value.get("observation"), f"{label}.observation"),
        "impact": impact,
        "recurrence": recurrence,
        "classification": classification,
        "owner_skill": owner,
        "detected_stage": detected,
        "earliest_detectable_stage": earliest,
        "escape_distance": escape_distance,
        "reproducibility": reproducibility,
        "one_off": one_off,
        "evidence_sha256": ref_hashes,
        "_private_evidence_refs": refs,
        "proposed_change": change,
        "priority_score": score,
        "priority": priority,
        "implementation_readiness": _readiness(one_off, reproducibility, change),
    }


def _validate_design_ref(value: Any, index: int) -> dict[str, str]:
    label = f"external_design_refs[{index}]"
    if not isinstance(value, dict):
        raise RetrospectiveError(f"{label} must be an object")
    _check_exact_keys(
        value,
        {"title", "url", "retrieved_at", "evidence_level", "claim", "use"},
        label,
    )
    url = _check_text(value.get("url"), f"{label}.url")
    if not url.startswith("https://"):
        raise RetrospectiveError(f"{label}.url must use https")
    level = _check_text(value.get("evidence_level"), f"{label}.evidence_level")
    if level not in EVIDENCE_LEVELS:
        raise RetrospectiveError(f"{label}.evidence_level is invalid")
    return {
        "title": _check_text(value.get("title"), f"{label}.title"),
        "url": url,
        "retrieved_at": _check_text(value.get("retrieved_at"), f"{label}.retrieved_at"),
        "evidence_level": level,
        "claim": _check_text(value.get("claim"), f"{label}.claim"),
        "use": _check_text(value.get("use"), f"{label}.use"),
    }


def _load_bundle(
    bundle_path: str | os.PathLike[str], expected_bundle_sha256: str
) -> tuple[Path, dict[str, Any], str]:
    path, raw, bundle = _load_json_file(bundle_path, "bundle")
    expected = _check_sha(expected_bundle_sha256, "expected_bundle_sha256")
    actual = _raw_sha256(raw)
    if actual != expected:
        raise RetrospectiveError("bundle raw SHA-256 does not match external pin")
    _check_exact_keys(
        bundle,
        {
            "schema",
            "run_id",
            "as_of",
            "scope",
            "stage_order",
            "run_ref",
            "incidents",
            "external_design_refs",
        },
        "bundle",
    )
    if bundle.get("schema") != BUNDLE_SCHEMA:
        raise RetrospectiveError(f"bundle.schema must equal {BUNDLE_SCHEMA}")
    _scan_credentials(bundle)
    return path, bundle, actual


def review_bundle(
    bundle_path: str | os.PathLike[str], expected_bundle_sha256: str
) -> dict[str, Any]:
    """Reopen a pinned bundle and project a deterministic retrospective review."""

    bound_bundle_path, bundle, bundle_sha = _load_bundle(
        bundle_path, expected_bundle_sha256
    )
    run_id = _check_id(bundle.get("run_id"), "bundle.run_id")
    stage_order = _text_array(bundle.get("stage_order"), "bundle.stage_order")
    for index, stage in enumerate(stage_order):
        _check_id(stage, f"bundle.stage_order[{index}]")
    stage_index = {stage: index for index, stage in enumerate(stage_order)}
    run_ref = _validate_ref(bundle.get("run_ref"), "bundle.run_ref")
    incident_values = bundle.get("incidents")
    if not isinstance(incident_values, list) or not incident_values:
        raise RetrospectiveError("bundle.incidents must be a non-empty array")
    findings = [
        _validate_incident(value, index, stage_index)
        for index, value in enumerate(incident_values)
    ]
    private_evidence_refs = {
        finding["incident_key"]: finding.pop("_private_evidence_refs")
        for finding in findings
    }
    incident_keys = [finding["incident_key"] for finding in findings]
    if len(incident_keys) != len(set(incident_keys)):
        raise RetrospectiveError("bundle.incidents contains duplicate incident_key")
    seam_keys = [
        (
            finding["owner_skill"],
            finding["classification"],
            finding["proposed_change"]["seam"],
        )
        for finding in findings
    ]
    if len(seam_keys) != len(set(seam_keys)):
        raise RetrospectiveError(
            "bundle.incidents contains duplicate owner/classification/seam findings"
        )
    findings.sort(key=lambda item: (-item["priority_score"], item["incident_key"]))

    design_values = bundle.get("external_design_refs")
    if not isinstance(design_values, list):
        raise RetrospectiveError("bundle.external_design_refs must be an array")
    design_refs = [
        _validate_design_ref(value, index)
        for index, value in enumerate(design_values)
    ]
    design_refs.sort(key=lambda item: (item["url"], item["claim"]))
    urls = [item["url"] for item in design_refs]
    if len(urls) != len(set(urls)):
        raise RetrospectiveError("bundle.external_design_refs contains duplicate url")

    def counts(field: str) -> dict[str, int]:
        values: dict[str, int] = {}
        for finding in findings:
            key = str(finding[field])
            values[key] = values.get(key, 0) + 1
        return {key: values[key] for key in sorted(values)}

    review: dict[str, Any] = {
        "schema": REVIEW_SCHEMA,
        "run_id": run_id,
        "as_of": _check_text(bundle.get("as_of"), "bundle.as_of"),
        "scope": _check_text(bundle.get("scope"), "bundle.scope"),
        "bundle_ref": {"raw_sha256": bundle_sha},
        "run_ref": {"raw_sha256": run_ref["sha256"]},
        "stage_order": stage_order,
        "findings": findings,
        "external_design_refs": design_refs,
        "summary": {
            "finding_count": len(findings),
            "by_priority": counts("priority"),
            "by_owner": counts("owner_skill"),
            "by_classification": counts("classification"),
            "by_readiness": counts("implementation_readiness"),
            "scope": "pinned_incident_set_only",
        },
        "limits": [
            "no_live_provider_execution",
            "no_research_interpretation",
            "no_zotero_mutation",
            "no_knowledge_network_mutation",
            "no_governance_authorization",
            "does_not_establish_absence_outside_pinned_scope",
        ],
        "private": {
            "bundle_ref": {
                "path": str(bound_bundle_path),
                "raw_sha256": bundle_sha,
            },
            "run_ref": run_ref,
            "evidence_refs": private_evidence_refs,
        },
    }
    digest = _raw_sha256(_canonical_bytes(review))
    review["review_id"] = f"research-workflow-review-{digest[:16]}"
    review["review_digest"] = digest
    return review


def _validate_review_shape(review: Mapping[str, Any]) -> None:
    _check_exact_keys(
        review,
        {
            "schema",
            "run_id",
            "as_of",
            "scope",
            "bundle_ref",
            "run_ref",
            "stage_order",
            "findings",
            "external_design_refs",
            "summary",
            "limits",
            "private",
            "review_id",
            "review_digest",
        },
        "review",
    )
    if review.get("schema") != REVIEW_SCHEMA:
        raise RetrospectiveError(f"review.schema must equal {REVIEW_SCHEMA}")
    supplied = _check_sha(review.get("review_digest"), "review.review_digest")
    body = copy.deepcopy(dict(review))
    body.pop("review_id", None)
    body.pop("review_digest", None)
    actual = _raw_sha256(_canonical_bytes(body))
    if actual != supplied:
        raise RetrospectiveError("review.review_digest does not match canonical content")
    if review.get("review_id") != f"research-workflow-review-{actual[:16]}":
        raise RetrospectiveError("review.review_id does not match review_digest")


def validate_review(
    review_path: str | os.PathLike[str],
    bundle_path: str | os.PathLike[str],
    expected_bundle_sha256: str,
    expected_review_sha256: str,
) -> dict[str, Any]:
    """Replay a review from its pinned bundle and require exact equality."""

    _, raw, review = _load_json_file(review_path, "review")
    expected_review = _check_sha(expected_review_sha256, "expected_review_sha256")
    if _raw_sha256(raw) != expected_review:
        raise RetrospectiveError("review raw SHA-256 does not match external pin")
    _validate_review_shape(review)
    rebuilt = review_bundle(bundle_path, expected_bundle_sha256)
    if review != rebuilt:
        raise RetrospectiveError("review does not equal replayed bundle projection")
    return review


def _atomic_write_json(path_value: str | os.PathLike[str], value: Mapping[str, Any]) -> None:
    path = Path(path_value)
    parent = path.parent
    if not path.is_absolute():
        raise RetrospectiveError("output must be an absolute path")
    if path.exists() or path.is_symlink():
        raise RetrospectiveError(f"output already exists: {path}")
    if parent.is_symlink() or not parent.is_dir():
        raise RetrospectiveError(f"output parent must be an existing ordinary directory: {parent}")
    if parent.resolve(strict=True) != parent:
        raise RetrospectiveError("output parent must not traverse a symlink or path alias")
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"
    directory_descriptor = os.open(
        parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    descriptor = -1
    temporary: Path | None = None
    try:
        if hasattr(os, "O_TMPFILE"):
            try:
                descriptor = os.open(
                    parent, os.O_TMPFILE | os.O_WRONLY | os.O_CLOEXEC, 0o600
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
                prefix=f".{path.name}.", dir=parent
            )
            temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
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
            raise RetrospectiveError(f"output already exists: {path}") from exc
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
            raise RetrospectiveError(
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or replay an evidence-bound research workflow retrospective"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build a deterministic review")
    build.add_argument("--bundle", required=True)
    build.add_argument("--expected-bundle-sha256", required=True)
    build.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate", help="Replay and validate a review")
    validate.add_argument("--bundle", required=True)
    validate.add_argument("--review", required=True)
    validate.add_argument("--expected-bundle-sha256", required=True)
    validate.add_argument("--expected-review-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "build":
            review = review_bundle(args.bundle, args.expected_bundle_sha256)
            _atomic_write_json(args.output, review)
            print(
                json.dumps(
                    {
                        "schema": review["schema"],
                        "review_id": review["review_id"],
                        "review_digest": review["review_digest"],
                        "finding_count": review["summary"]["finding_count"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        review = validate_review(
            args.review,
            args.bundle,
            args.expected_bundle_sha256,
            args.expected_review_sha256,
        )
        print(
            json.dumps(
                {
                    "schema": review["schema"],
                    "valid": True,
                    "review_id": review["review_id"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, RetrospectiveError) as exc:
        print(f"workflow-retrospective failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
