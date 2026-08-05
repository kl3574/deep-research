#!/usr/bin/env python3
"""Audit a completed Zotero bridge research-delivery run from frozen artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA = "ZoteroBridgeRunEvidencePack/v1"
SUMMARY_SCHEMA = "ZoteroBridgeRunAudit/v1"
ARTIFACT_KEYS = {
    "probe",
    "canary_apply",
    "canary_readback",
    "metadata_apply",
    "metadata_readback",
    "attachment_summary",
    "negative_membership_readback",
    "final_acceptance",
    "network",
    "research_map",
    "html_primary",
    "html_repeat",
}
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REMOTE_RESOURCE_RE = re.compile(
    r"<(?:script|link|img|iframe|object|embed)\b[^>]*\b(?:src|href|data)\s*=\s*"
    r"[\"'](?:https?:)?//",
    re.IGNORECASE,
)


class AuditFailure(RuntimeError):
    """A frozen artifact is valid JSON but does not satisfy the run contract."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditFailure("JSON artifact must be an object")
    return value


def exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise AuditFailure(f"{label} keys differ")


def validate_pack(pack: dict[str, Any]) -> dict[str, Any]:
    exact_keys(pack, {"schema", "expected", "artifacts", "evidence_pack_sha256"}, "pack")
    if pack["schema"] != SCHEMA:
        raise AuditFailure("evidence-pack schema mismatch")
    digest = pack["evidence_pack_sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise AuditFailure("invalid evidence-pack digest")
    unsigned = {key: value for key, value in pack.items() if key != "evidence_pack_sha256"}
    if "sha256:" + hashlib.sha256(canonical_bytes(unsigned)).hexdigest() != digest:
        raise AuditFailure("evidence-pack digest mismatch")
    expected = pack["expected"]
    if not isinstance(expected, dict):
        raise AuditFailure("expected must be an object")
    required_expected = {
        "plugin_version",
        "zotero_version",
        "target_parent_count",
        "short_title_count",
        "note_count",
        "local_readable_pdf_parent_count",
        "attachment_batch_import_count",
        "attachment_total_import_count",
        "current_source_count",
        "current_source_doi_count",
    }
    exact_keys(expected, required_expected, "expected")
    artifacts = pack["artifacts"]
    if not isinstance(artifacts, dict):
        raise AuditFailure("artifacts must be an object")
    exact_keys(artifacts, ARTIFACT_KEYS, "artifacts")
    return expected


def load_artifacts(pack: dict[str, Any]) -> dict[str, tuple[Path, bytes, dict[str, Any] | None]]:
    loaded: dict[str, tuple[Path, bytes, dict[str, Any] | None]] = {}
    for name, ref in pack["artifacts"].items():
        if not isinstance(ref, dict):
            raise AuditFailure(f"artifact {name} reference must be an object")
        exact_keys(ref, {"path", "sha256"}, f"artifact {name}")
        path = Path(ref["path"]).expanduser().resolve()
        if not path.is_file() or path.is_symlink():
            raise AuditFailure(f"artifact {name} is not a regular file")
        if not isinstance(ref["sha256"], str) or not SHA256_RE.fullmatch(ref["sha256"]):
            raise AuditFailure(f"artifact {name} has invalid digest")
        raw = path.read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise AuditFailure(f"artifact {name} digest mismatch")
        parsed = None if name.startswith("html_") else json.loads(raw.decode("utf-8"))
        if parsed is not None and not isinstance(parsed, dict):
            raise AuditFailure(f"artifact {name} must contain a JSON object")
        loaded[name] = (path, raw, parsed)
    return loaded


def result(receipt: dict[str, Any], *, status: str, action: str) -> dict[str, Any]:
    if receipt.get("status") != status or receipt.get("action") != action:
        raise AuditFailure(f"{action} receipt status mismatch")
    value = receipt.get("result")
    if not isinstance(value, dict):
        raise AuditFailure(f"{action} receipt result missing")
    return value


def audit(pack: dict[str, Any]) -> dict[str, Any]:
    expected = validate_pack(pack)
    loaded = load_artifacts(pack)

    probe = loaded["probe"][2]
    assert probe is not None
    probe_result = result(probe, status="available", action="probe")
    if probe_result.get("plugin_version") != expected["plugin_version"]:
        raise AuditFailure("plugin version mismatch")
    if probe_result.get("zotero_version") != expected["zotero_version"]:
        raise AuditFailure("Zotero version mismatch")
    profiles = probe_result.get("execution_profiles") or {}
    if set(profiles) != {"db_atomic", "single_attachment_import"}:
        raise AuditFailure("execution profiles mismatch")
    if probe_result.get("mixed_operations") is not False or probe_result.get("attachment_batch") is not False:
        raise AuditFailure("unsafe bridge capability advertised")

    for prefix, profile in (("canary", "single_attachment_import"), ("metadata", "db_atomic")):
        apply_receipt = loaded[f"{prefix}_apply"][2]
        readback_receipt = loaded[f"{prefix}_readback"][2]
        assert apply_receipt is not None and readback_receipt is not None
        apply_result = result(apply_receipt, status="completed", action="apply")
        if apply_result.get("commit_state") != "committed" or apply_result.get("execution_profile") != profile:
            raise AuditFailure(f"{prefix} apply did not commit with {profile}")
        readback_result = result(readback_receipt, status="verified", action="readback")
        if readback_result.get("all_satisfied") is not True:
            raise AuditFailure(f"{prefix} readback is not satisfied")

    attachment_summary = loaded["attachment_summary"][2]
    assert attachment_summary is not None
    rows = attachment_summary.get("results")
    if attachment_summary.get("status") != "completed" or not isinstance(rows, list):
        raise AuditFailure("attachment summary did not complete")
    if len(rows) != expected["attachment_batch_import_count"]:
        raise AuditFailure("attachment batch import count mismatch")
    if any(row.get("status") != "verified" for row in rows if isinstance(row, dict)) or any(
        not isinstance(row, dict) for row in rows
    ):
        raise AuditFailure("an attachment import is not verified")

    negative_membership = loaded["negative_membership_readback"][2]
    assert negative_membership is not None
    negative_result = result(
        negative_membership, status="not_applied", action="readback"
    )
    negative_state = negative_result.get("state") or {}
    negative_entries = negative_state.get("entries") or []
    if negative_result.get("all_satisfied") is not False or len(negative_entries) != 1:
        raise AuditFailure("negative membership readback did not reject the manifest")
    negative_entry = negative_entries[0]
    negative_operations = negative_entry.get("operations") or []
    if negative_entry.get("target_membership") is not False or not any(
        operation.get("decision") == "needs_write"
        for operation in negative_operations
        if isinstance(operation, dict)
    ):
        raise AuditFailure("negative membership readback did not enforce target membership")

    acceptance = loaded["final_acceptance"][2]
    assert acceptance is not None
    if acceptance.get("status") != "completed_local_zotero":
        raise AuditFailure("local Zotero acceptance did not complete")
    accepted = acceptance.get("acceptance") or {}
    acceptance_expectations = {
        "target_parent_count": expected["target_parent_count"],
        "nonempty_short_title_count": expected["short_title_count"],
        "exactly_one_note_parent_count": expected["note_count"],
        "nonempty_note_parent_count": expected["note_count"],
        "local_readable_pdf_parent_count": expected["local_readable_pdf_parent_count"],
    }
    for field, wanted in acceptance_expectations.items():
        if accepted.get(field) != wanted:
            raise AuditFailure(f"acceptance field {field} mismatch")
    if accepted.get("attachment_batch_verified_count") != expected["attachment_batch_import_count"]:
        raise AuditFailure("acceptance attachment batch count mismatch")
    operations = acceptance.get("operations") or {}
    if operations.get("ensure_pdf_attachment") != expected["attachment_total_import_count"]:
        raise AuditFailure("acceptance total attachment import count mismatch")
    limits = acceptance.get("delivery_limits") or {}
    if limits.get("local_zotero_verified") is not True:
        raise AuditFailure("local Zotero verification is absent")
    if limits.get("pdf_cloud_sync_verified") is not False:
        raise AuditFailure("cloud PDF sync must remain an explicit non-claim")

    network = loaded["network"][2]
    research_map = loaded["research_map"][2]
    assert network is not None and research_map is not None
    if network.get("schema") != "KnowledgeNetwork/v1" or research_map.get("schema") != "ResearchMap/v1":
        raise AuditFailure("network or research-map schema mismatch")
    if research_map.get("network_snapshot_id") != network.get("snapshot_id"):
        raise AuditFailure("research-map snapshot binding mismatch")
    corpus = network.get("corpus_snapshot") or {}
    item_refs = corpus.get("item_refs") or []
    if (
        corpus.get("source") != "zotero"
        or corpus.get("item_count") != expected["current_source_count"]
        or len(item_refs) != expected["current_source_count"]
        or len(set(item_refs)) != len(item_refs)
        or any(not isinstance(ref, str) or not ref for ref in item_refs)
    ):
        raise AuditFailure("current corpus source count mismatch")
    sources = network.get("sources") or []
    current_rows = [
        source
        for source in sources
        if isinstance(source, dict)
        and source.get("role") == "zotero_corpus"
        and source.get("corpus_membership") == "current"
    ]
    if len(current_rows) != expected["current_source_count"]:
        raise AuditFailure("current bibliographic source projection mismatch")
    if sum(bool(source.get("title")) for source in current_rows) != expected["current_source_count"]:
        raise AuditFailure("current source title coverage mismatch")
    if sum(bool(source.get("doi")) for source in current_rows) != expected["current_source_doi_count"]:
        raise AuditFailure("current source DOI coverage mismatch")

    html_primary = loaded["html_primary"][1]
    html_repeat = loaded["html_repeat"][1]
    if html_primary != html_repeat:
        raise AuditFailure("HTML renders are not byte-identical")
    text = html_primary.decode("utf-8")
    if REMOTE_RESOURCE_RE.search(text):
        raise AuditFailure("HTML contains a remote executable or visual resource")
    if "<!doctype html>" not in text.lower():
        raise AuditFailure("HTML document type missing")

    return {
        "schema": SUMMARY_SCHEMA,
        "status": "passed",
        "plugin_version": expected["plugin_version"],
        "zotero_version": expected["zotero_version"],
        "target_parent_count": expected["target_parent_count"],
        "note_count": expected["note_count"],
        "short_title_count": expected["short_title_count"],
        "local_readable_pdf_parent_count": expected["local_readable_pdf_parent_count"],
        "attachment_batch_import_count": expected["attachment_batch_import_count"],
        "attachment_total_import_count": expected["attachment_total_import_count"],
        "current_source_count": expected["current_source_count"],
        "current_source_doi_count": expected["current_source_doi_count"],
        "html_deterministic": True,
        "html_self_contained": True,
        "cloud_sync_claimed": False,
    }


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-pack", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        summary = audit(read_json(args.evidence_pack))
        if args.output:
            write_exclusive(args.output, summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except AuditFailure as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        print(f"audit error: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
