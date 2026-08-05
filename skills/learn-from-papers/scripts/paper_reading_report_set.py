#!/usr/bin/env python3
"""Produce and validate PaperReadingReportSet/v1 attestation artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SET_SCHEMA = "PaperReadingReportSet/v1"
REPORT_SCHEMA = "PaperReadingReport/v1"
SCHEMA_VERSION = "v1"
PROTOCOL_VERSION = "1.0"
PRODUCER = "learn-from-papers"
REPORT_SET_ID_PREFIX = "reading-report-set-"
REPORT_ID_PREFIX = "reading-report-"
PASSAGE_ID_PREFIX = "passage-"
READ_DEPTH = "full_text"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LOCATOR_TYPES = {"page", "section", "figure", "table", "equation"}
STANCE_VALUES = {"support", "refute", "mixed"}
URL_ONLY_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
DOI_ONLY_RE = re.compile(
    r"(?i)^(?:doi:\s*)?10\.[0-9]{4,9}/\S+$",
)


class ContractError(ValueError):
    """Raised when a report-set contract is invalid."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_report_set_digest(document: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            key: value
            for key, value in document.items()
            if key
            not in {
                "report_set_id",
                "report_set_digest",
                "reading_report_set_id",
                "reading_report_set_digest",
                "network_id",
                "network_snapshot_sha256",
                "source_artifact_sha256",
            }
        }
    )


def canonical_report_digest(document: dict[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in document.items() if key not in {"report_id", "report_digest"}}
    )


def canonical_passage_digest(document: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            key: value
            for key, value in document.items()
            if key not in {"passage_id", "passage_digest"}
        }
    )


def report_set_id(digest: str) -> str:
    return REPORT_SET_ID_PREFIX + digest[:16]


def report_id(digest: str) -> str:
    return REPORT_ID_PREFIX + digest[:16]


def passage_id(digest: str) -> str:
    return PASSAGE_ID_PREFIX + digest[:16]


def timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a list")
    return value


def require_nonempty_string(value: Any, label: str) -> str:
    text = require_string(value, label)
    if not text.strip():
        raise ContractError(f"{label} must not be empty")
    return text


def require_timestamp(value: Any, label: str) -> str:
    text = require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return text


def ensure_sha256(value: Any, label: str) -> str:
    text = require_nonempty_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return text


def require_file_payload(path: Path) -> bytes:
    if path.is_symlink():
        raise ContractError(f"refusing symlink input file: {path}")
    if not path.is_file():
        raise ContractError(f"input file is missing: {path}")
    return path.read_bytes()


def load_json(path: str | Path) -> dict[str, Any]:
    candidate = Path(path).resolve()
    data = json.loads(require_file_payload(candidate).decode("utf-8"))
    if not isinstance(data, dict):
        raise ContractError(f"input JSON object required: {candidate}")
    return data


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path).resolve()
    if target.is_symlink():
        raise ContractError(f"refusing symlink output file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload) + b"\n")
    temporary.replace(target)


def _ensure_reader_depth(value: Any, label: str) -> str:
    text = require_string(value, label)
    if text != READ_DEPTH:
        raise ContractError(f"{label} must be {READ_DEPTH}")
    return text


def _extract_depth(value: dict[str, Any], label: str) -> str:
    read_depth = value.get("read_depth")
    reading_depth = value.get("reading_depth")

    if read_depth is None and reading_depth is None:
        raise ContractError(f"{label} must specify read_depth")

    resolved = _ensure_reader_depth(read_depth, f"{label}.read_depth") if read_depth is not None else _ensure_reader_depth(
        reading_depth, f"{label}.reading_depth"
    )
    if reading_depth is not None and read_depth is not None and reading_depth != read_depth:
        raise ContractError(f"{label}.read_depth and {label}.reading_depth must match")
    return resolved


def _ensure_locator_type(value: Any, label: str) -> str:
    text = require_string(value, label)
    if text not in LOCATOR_TYPES:
        raise ContractError(f"{label} must be one of: {', '.join(sorted(LOCATOR_TYPES))}")
    return text


def _ensure_stance(value: Any, label: str) -> str:
    text = require_string(value, label)
    if text not in STANCE_VALUES:
        raise ContractError(f"{label} must be one of: support, refute, mixed")
    return text


def _validate_exact_locator(value: Any, label: str) -> str:
    text = require_nonempty_string(value, label)
    lowered = text.lower()
    if URL_ONLY_RE.fullmatch(text) or DOI_ONLY_RE.fullmatch(lowered):
        raise ContractError(f"{label} must not be a pure DOI/URL locator")
    return text


def _validate_network_ref(value: Any, label: str) -> dict[str, str]:
    network_ref = require_dict(value, f"{label}")
    network_id = require_string(network_ref.get("network_id"), f"{label}.network_id")
    snapshot_id = require_string(network_ref.get("snapshot_id"), f"{label}.snapshot_id")
    digest = ensure_sha256(network_ref.get("sha256"), f"{label}.sha256")
    return {
        "network_id": network_id,
        "snapshot_id": snapshot_id,
        "sha256": digest,
    }


def _validate_extraction_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _ = require_dict(payload, "extraction")

    if payload.get("schema") == "PaperReadingStructuredExtraction/v1":
        pass
    elif payload.get("schema") is not None:
        raise ContractError("extraction.schema must be PaperReadingStructuredExtraction/v1")

    protocol_version = require_nonempty_string(payload.get("protocol_version"), "extraction.protocol_version")
    if protocol_version != PROTOCOL_VERSION:
        raise ContractError("extraction.protocol_version must be 1.0")

    generated_at = payload.get("generated_at")
    if generated_at is not None:
        require_timestamp(generated_at, "extraction.generated_at")

    if "discovery_metadata" in payload and "reports" not in payload:
        raise ContractError("extraction input must be completed structured extraction, not discovery metadata")

    network_ref = _validate_network_ref(payload.get("network_ref"), "extraction.network_ref")
    review_request_set_id = require_string(
        payload.get("review_request_set_id"), "extraction.review_request_set_id"
    )
    review_request_set_digest = ensure_sha256(
        payload.get("review_request_set_digest"), "extraction.review_request_set_digest"
    )

    reports = require_list(payload.get("reports"), "extraction.reports")
    if not reports:
        raise ContractError("extraction.reports must not be empty")

    validated_reports: list[dict[str, Any]] = []
    for index, report in enumerate(reports):
        validated_reports.append(
            _validate_extraction_report(
                require_dict(report, f"extraction.reports[{index}]"),
            )
        )

    if not validated_reports:
        raise ContractError("extraction.reports must contain at least one report")

    return {
        "protocol_version": protocol_version,
        "generated_at": generated_at,
        "network_ref": network_ref,
        "review_request_set_id": review_request_set_id,
        "review_request_set_digest": review_request_set_digest,
        "reports": validated_reports,
    }


def _validate_extraction_report(report: dict[str, Any]) -> dict[str, Any]:
    review_request_id = require_string(report.get("review_request_id"), "report.review_request_id")
    review_request_digest = ensure_sha256(
        report.get("review_request_digest"),
        "report.review_request_digest",
    )
    source_id = require_string(report.get("source_id"), "report.source_id")
    source_digest = ensure_sha256(report.get("source_digest"), "report.source_digest")
    source_ref = require_string(report.get("source_ref"), "report.source_ref")
    source_artifact_sha256 = ensure_sha256(
        report.get("source_artifact_sha256"),
        "report.source_artifact_sha256",
    )

    _extract_depth(report, "report")

    passages_raw = require_list(report.get("evidence_passages"), "report.evidence_passages")
    if not passages_raw:
        raise ContractError("report.evidence_passages must not be empty")

    validated_passages = [
        _validate_extraction_passage(
            require_dict(passage, "report.evidence_passages"), index
        )
        for index, passage in enumerate(passages_raw)
    ]

    if not validated_passages:
        raise ContractError("report.evidence_passages must not be empty")

    return {
        "review_request_id": review_request_id,
        "review_request_digest": review_request_digest,
        "source_id": source_id,
        "source_digest": source_digest,
        "source_ref": source_ref,
        "source_artifact_sha256": source_artifact_sha256,
        "read_depth": READ_DEPTH,
        "evidence_passages": validated_passages,
    }


def _validate_extraction_passage(
    passage: dict[str, Any], index: int
) -> dict[str, Any]:
    locator_type = _ensure_locator_type(
        passage.get("locator_type"), f"report.evidence_passages[{index}].locator_type"
    )
    exact_locator = _validate_exact_locator(
        passage.get("exact_locator"),
        f"report.evidence_passages[{index}].exact_locator",
    )
    passage_sha256 = ensure_sha256(
        passage.get("passage_sha256"), f"report.evidence_passages[{index}].passage_sha256"
    )
    claim_summary = require_string(
        passage.get("claim_summary"), f"report.evidence_passages[{index}].claim_summary"
    )
    evidence_summary = require_string(
        passage.get("evidence_summary"),
        f"report.evidence_passages[{index}].evidence_summary",
    )
    stance = _ensure_stance(
        passage.get("stance"), f"report.evidence_passages[{index}].stance"
    )
    return {
        "locator_type": locator_type,
        "exact_locator": exact_locator,
        "passage_sha256": passage_sha256,
        "claim_summary": claim_summary,
        "evidence_summary": evidence_summary,
        "stance": stance,
    }


def _validate_report_payload(
    report: dict[str, Any],
    protocol_version: str,
    review_request_set_id: str,
    review_request_set_digest: str,
) -> dict[str, Any]:
    if report.get("schema") != REPORT_SCHEMA:
        raise ContractError(f"paper reading report.schema must equal {REPORT_SCHEMA}")

    producer = report.get("producer")
    if producer is not None:
        producer = require_string(producer, "report.producer")
        if producer != PRODUCER:
            raise ContractError("report.producer must be learn-from-papers")

    protocol = require_nonempty_string(
        report.get("protocol_version", protocol_version),
        "report.protocol_version",
    )
    if protocol != protocol_version:
        raise ContractError("report.protocol_version must match report set protocol_version")

    report_read_depth = _extract_depth(report, "report")
    review_request_id = require_string(report.get("review_request_id"), "report.review_request_id")
    review_request_digest = ensure_sha256(
        report.get("review_request_digest"), "report.review_request_digest"
    )
    source_id = require_string(report.get("source_id"), "report.source_id")
    source_digest = ensure_sha256(report.get("source_digest"), "report.source_digest")
    source_ref = require_string(report.get("source_ref"), "report.source_ref")
    source_artifact_sha256 = ensure_sha256(
        report.get("source_artifact_sha256"), "report.source_artifact_sha256"
    )

    passages = report.get("evidence_passages")
    if passages is None:
        passages = report.get("passages")
    if passages is None:
        raise ContractError("report.evidence_passages must be present")
    passages = require_list(passages, "report.evidence_passages")
    if not passages:
        raise ContractError("report.evidence_passages must not be empty")

    validated_passages: list[dict[str, Any]] = []
    for index, passage in enumerate(passages):
        validated_passages.append(_validate_passage_payload(
            require_dict(
                passage,
                f"report.evidence_passages[{index}]",
            )
        ))

    report_payload = {
        "schema": REPORT_SCHEMA,
        "review_request_id": review_request_id,
        "review_request_digest": review_request_digest,
        "source_id": source_id,
        "source_digest": source_digest,
        "source_ref": source_ref,
        "source_artifact_sha256": source_artifact_sha256,
        "read_depth": report_read_depth,
        "evidence_passages": validated_passages,
    }

    if report.get("review_request_set_id") is not None:
        legacy_set_id = require_string(report.get("review_request_set_id"), "report.review_request_set_id")
        if legacy_set_id != review_request_set_id:
            raise ContractError("report.review_request_set_id does not match report set")
    if report.get("review_request_set_digest") is not None:
        legacy_set_digest = ensure_sha256(
            report.get("review_request_set_digest"), "report.review_request_set_digest"
        )
        if legacy_set_digest != review_request_set_digest:
            raise ContractError("report.review_request_set_digest does not match report set")

    if report.get("reading_depth") is not None:
        reading_depth = require_string(report.get("reading_depth"), "report.reading_depth")
        if reading_depth != READ_DEPTH:
            raise ContractError("report.reading_depth must be full_text")
        if reading_depth != report_read_depth:
            raise ContractError(
                "report.reading_depth and report.read_depth must match"
            )

    expected_digest = canonical_report_digest(report_payload)
    report_digest = require_nonempty_string(
        report.get("report_digest"), "report.report_digest"
    )
    if not SHA256_RE.fullmatch(report_digest):
        raise ContractError("report.report_digest must be 64 lowercase hex characters")
    if expected_digest != report_digest:
        raise ContractError("report.report_digest does not match report payload")
    expected_id = report_id(expected_digest)
    if report.get("report_id") != expected_id:
        raise ContractError("report.report_id does not match report digest")

    return {
        "report_id": report.get("report_id"),
        "report_digest": report_digest,
        "schema": REPORT_SCHEMA,
        "review_request_id": review_request_id,
        "review_request_digest": review_request_digest,
        "source_id": source_id,
        "source_digest": source_digest,
        "source_ref": source_ref,
        "source_artifact_sha256": source_artifact_sha256,
        "read_depth": report_read_depth,
        "evidence_passages": validated_passages,
    }


def _validate_passage_payload(passage: dict[str, Any]) -> dict[str, Any]:
    locator_type = _ensure_locator_type(passage.get("locator_type"), "passage.locator_type")
    exact_locator = _validate_exact_locator(
        passage.get("exact_locator"), "passage.exact_locator"
    )
    passage_sha256 = ensure_sha256(
        passage.get("passage_sha256"), "passage.passage_sha256"
    )
    claim_summary = require_string(passage.get("claim_summary"), "passage.claim_summary")
    evidence_summary = require_string(passage.get("evidence_summary"), "passage.evidence_summary")
    stance = _ensure_stance(passage.get("stance"), "passage.stance")

    provided_passage_id = require_string(passage.get("passage_id"), "passage.passage_id")
    provided_passage_digest = ensure_sha256(
        passage.get("passage_digest"), "passage.passage_digest"
    )
    expected_digest = canonical_passage_digest(
        {key: value for key, value in passage.items() if key not in {"passage_id", "passage_digest"}}
    )
    if expected_digest != provided_passage_digest:
        raise ContractError("passage.passage_digest does not match passage payload")
    expected_id = passage_id(expected_digest)
    if provided_passage_id != expected_id:
        raise ContractError("passage.passage_id does not match passage digest")

    return {
        "passage_id": provided_passage_id,
        "passage_digest": provided_passage_digest,
        "locator_type": locator_type,
        "exact_locator": exact_locator,
        "passage_sha256": passage_sha256,
        "claim_summary": claim_summary,
        "evidence_summary": evidence_summary,
        "stance": stance,
    }


def create_report_set(
    extraction: dict[str, Any], *, generated_at: str | None = None
) -> dict[str, Any]:
    extraction_payload = _validate_extraction_payload(require_dict(extraction, "extraction"))
    protocol_version = extraction_payload["protocol_version"]
    report_set_generated_at = extraction_payload.get("generated_at") or timestamp_now()
    if generated_at is not None:
        report_set_generated_at = require_timestamp(generated_at, "generated_at")

    review_request_set_id = extraction_payload["review_request_set_id"]
    review_request_set_digest = extraction_payload["review_request_set_digest"]
    network_ref = extraction_payload["network_ref"]

    reports: list[dict[str, Any]] = []
    report_ids: set[str] = set()

    for report_index, report in enumerate(extraction_payload["reports"]):
        passages: list[dict[str, Any]] = []
        passage_ids: set[str] = set()
        for passage in report["evidence_passages"]:
            passage_signature = {
                key: value
                for key, value in passage.items()
                if key not in {"passage_id", "passage_digest"}
            }
            digest = canonical_passage_digest(passage_signature)
            identifier = passage_id(digest)
            if identifier in passage_ids:
                raise ContractError(
                    f"duplicate passage_id for generated report at index {report_index}: {identifier}"
                )
            passage_ids.add(identifier)
            passage_with_id = dict(passage_signature)
            passage_with_id["passage_id"] = identifier
            passage_with_id["passage_digest"] = digest
            passages.append(passage_with_id)

        generated_report = {
            "schema": REPORT_SCHEMA,
            "review_request_id": report["review_request_id"],
            "review_request_digest": report["review_request_digest"],
            "source_id": report["source_id"],
            "source_digest": report["source_digest"],
            "source_ref": report["source_ref"],
            "source_artifact_sha256": report["source_artifact_sha256"],
            "read_depth": READ_DEPTH,
            "evidence_passages": passages,
        }
        report_signature = {
            key: value
            for key, value in generated_report.items()
            if key not in {"report_id", "report_digest"}
        }
        report_digest = canonical_report_digest(report_signature)
        report_id_value = report_id(report_digest)
        if report_id_value in report_ids:
            raise ContractError(
                f"duplicate report_id generated for input report at index {report_index}: {report_id_value}"
            )
        report_ids.add(report_id_value)
        generated_report["report_id"] = report_id_value
        generated_report["report_digest"] = report_digest
        reports.append(generated_report)

    report_set_payload = {
        "schema": REPORT_SET_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "protocol_version": protocol_version,
        "generated_at": report_set_generated_at,
        "network_ref": network_ref,
        "review_request_set_id": review_request_set_id,
        "review_request_set_digest": review_request_set_digest,
        "reports": reports,
    }
    report_set_digest = canonical_report_set_digest(report_set_payload)
    report_set_payload["report_set_digest"] = report_set_digest
    report_set_payload["report_set_id"] = report_set_id(report_set_digest)

    return validate_report_set(report_set_payload)


def validate_report_set(document: dict[str, Any]) -> dict[str, Any]:
    document = require_dict(document, "report set")
    if document.get("schema") != REPORT_SET_SCHEMA:
        raise ContractError(f"report set schema must equal {REPORT_SET_SCHEMA}")

    schema_version = require_string(document.get("schema_version"), "report_set.schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ContractError("report_set.schema_version must be v1")

    if document.get("producer") != PRODUCER:
        raise ContractError("report_set.producer must be learn-from-papers")

    protocol_version = require_nonempty_string(
        document.get("protocol_version"), "report_set.protocol_version"
    )
    if protocol_version != PROTOCOL_VERSION:
        raise ContractError("report_set.protocol_version must be 1.0")

    require_timestamp(document.get("generated_at"), "report_set.generated_at")
    network_ref = _validate_network_ref(document.get("network_ref"), "report_set.network_ref")

    network_id = document.get("network_id")
    if network_id is not None:
        network_id = require_string(network_id, "report_set.network_id")
        if network_id != network_ref["network_id"]:
            raise ContractError("report_set.network_id does not match report_set.network_ref")

    network_snapshot_sha256 = document.get("network_snapshot_sha256")
    if network_snapshot_sha256 is not None:
        network_snapshot_sha256 = ensure_sha256(
            network_snapshot_sha256, "report_set.network_snapshot_sha256"
        )
        if network_snapshot_sha256 != network_ref["sha256"]:
            raise ContractError(
                "report_set.network_snapshot_sha256 does not match report_set.network_ref"
            )

    review_request_set_id = require_string(
        document.get("review_request_set_id"), "report_set.review_request_set_id"
    )
    review_request_set_digest = ensure_sha256(
        document.get("review_request_set_digest"), "report_set.review_request_set_digest"
    )
    source_artifact_sha256 = document.get("source_artifact_sha256")
    if source_artifact_sha256 is not None:
        source_artifact_sha256 = ensure_sha256(
            source_artifact_sha256, "report_set.source_artifact_sha256"
        )

    reports = require_list(document.get("reports"), "report_set.reports")
    if not reports:
        raise ContractError("report_set.reports must not be empty")

    validated_reports: list[dict[str, Any]] = []
    report_ids: set[str] = set()
    report_digests: set[str] = set()
    passage_ids: set[str] = set()

    for index, report in enumerate(reports):
        validated = _validate_report_payload(
            require_dict(report, f"report_set.reports[{index}]"),
            protocol_version,
            review_request_set_id,
            review_request_set_digest,
        )
        report_id_value = validated["report_id"]
        report_digest = validated["report_digest"]
        if report_id_value in report_ids:
            raise ContractError(f"duplicate report_id at report_set.reports[{index}]")
        if report_digest in report_digests:
            raise ContractError(f"duplicate report_digest at report_set.reports[{index}]")
        report_ids.add(report_id_value)
        report_digests.add(report_digest)
        for passage in validated["evidence_passages"]:
            if passage["passage_id"] in passage_ids:
                raise ContractError(
                    f"duplicate passage_id across report_set.reports[{index}] passages"
                )
            passage_ids.add(passage["passage_id"])
        if (
            source_artifact_sha256 is not None
            and validated["source_artifact_sha256"] != source_artifact_sha256
        ):
            raise ContractError(
                "report_set.source_artifact_sha256 must match all report source_artifact_sha256"
            )
        validated_reports.append(validated)
    if source_artifact_sha256 is None:
        unique_source_artifacts = {
            report["source_artifact_sha256"] for report in validated_reports
        }
        if len(unique_source_artifacts) == 1:
            source_artifact_sha256 = unique_source_artifacts.pop()

    report_set_digest = require_nonempty_string(
        document.get("report_set_digest"), "report_set.report_set_digest"
    )
    if not SHA256_RE.fullmatch(report_set_digest):
        raise ContractError(
            "report_set.report_set_digest must be 64 lowercase hex characters"
        )
    expected_report_set_digest = canonical_report_set_digest(
        {key: value for key, value in document.items() if key not in {"report_set_id", "report_set_digest"}}
    )
    if report_set_digest != expected_report_set_digest:
        raise ContractError("report_set.report_set_digest does not match report-set payload")

    expected_report_set_id = report_set_id(report_set_digest)
    if document.get("report_set_id") != expected_report_set_id:
        raise ContractError("report_set.report_set_id does not match report-set digest")
    if (
        document.get("reading_report_set_digest") is not None
        and document.get("reading_report_set_digest") != report_set_digest
    ):
        raise ContractError("report_set.reading_report_set_digest does not match report_set_digest")
    if (
        document.get("reading_report_set_id") is not None
        and document.get("reading_report_set_id") != expected_report_set_id
    ):
        raise ContractError("report_set.reading_report_set_id does not match report_set_id")

    report_set = {
        "schema": REPORT_SET_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "protocol_version": protocol_version,
        "generated_at": document["generated_at"],
        "network_ref": network_ref,
        "review_request_set_id": review_request_set_id,
        "review_request_set_digest": review_request_set_digest,
        "report_set_id": expected_report_set_id,
        "report_set_digest": report_set_digest,
        "reports": validated_reports,
    }

    return report_set


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser("create", help="create PaperReadingReportSet/v1")
    create.add_argument("--input", required=True)
    create.add_argument("--output", required=True)
    create.add_argument("--generated-at", help="override generated_at in UTC, ISO-8601")

    validate = subcommands.add_parser("validate", help="validate one PaperReadingReportSet/v1")
    validate.add_argument("--input", required=True)

    return root


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "create":
            extracted = load_json(arguments.input)
            report_set = create_report_set(
                extracted,
                generated_at=arguments.generated_at,
            )
            write_json(arguments.output, report_set)
        else:
            report_set = validate_report_set(load_json(arguments.input))
            print(
                json.dumps(
                    {
                        "valid": True,
                        "schema": report_set["schema"],
                        "report_set_id": report_set["report_set_id"],
                    },
                    sort_keys=True,
                )
            )
        return 0
    except (
        ContractError,
        json.JSONDecodeError,
        OSError,
        ValueError,
        TypeError,
        UnicodeDecodeError,
        re.error,
    ) as exc:
        print(f"paper-reading-report-set failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
