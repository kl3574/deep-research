#!/usr/bin/env python3
"""Classify scholarly PDFs and build or adopt traceable OCR derivatives."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


QUALITY_SCHEMA = "ScholarlyDocumentQuality/v1"
NORMALIZATION_SCHEMA = "ScholarlyDocumentNormalization/v1"
FAILURE_SCHEMA = "ScholarlyDocumentNormalizationFailure/v1"
SCHEMA_VERSION = "v1"
PRODUCER = "scholarly-document-normalization"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_+.-]+$")
VERSION_RE = re.compile(r"\d+(?:\.\d+)+")

THRESHOLDS = {
    "blank_non_whitespace_max": 20,
    "blank_scan_page_fraction_min": 0.8,
    "column_gap_spaces_min": 4,
    "column_gap_line_fraction_min": 0.2,
    "column_risk_page_fraction_min": 0.25,
    "column_risk_nonempty_lines_min": 8,
    "pathological_control_fraction_max": 0.01,
    "pathological_long_line_chars_min": 1000,
    "pathological_max_line_chars_max": 20000,
    "pathological_mean_page_chars_max": 100000,
    "pathological_page_chars_max": 200000,
    "pathological_page_fraction_min": 0.5,
    "pathological_replacement_fraction_max": 0.02,
    "pathological_single_page_chars_max": 1000000,
    "pathological_token_repetition_max": 0.95,
}

QUALITY_TOP_KEYS = {
    "schema",
    "schema_version",
    "producer",
    "generated_at",
    "source",
    "tools",
    "thresholds",
    "pages",
    "summary",
    "quality_id",
    "quality_digest",
}
SOURCE_KEYS = {
    "path",
    "name",
    "sha256",
    "size_bytes",
    "magic",
    "page_count",
    "source_kind",
    "source_bundle_ref",
}
BUNDLE_REF_KEYS = {
    "path",
    "sha256",
    "bundle_id",
    "bundle_digest",
    "source_sha256",
}
TOOL_KEYS = {"path", "resolved_path", "version", "version_argv"}
PAGE_KEYS = {
    "page_index",
    "extracted_chars",
    "non_whitespace_chars",
    "alphanumeric_chars",
    "replacement_chars",
    "control_chars",
    "line_count",
    "nonempty_line_count",
    "max_line_chars",
    "mean_line_chars",
    "empty_line_fraction",
    "long_line_fraction",
    "column_gap_line_fraction",
    "max_token_repetition",
    "page_kind",
}
SUMMARY_KEYS = {
    "classification",
    "reasons",
    "review_required",
    "review_reasons",
    "normalization_recommended",
    "total_extracted_chars",
    "total_non_whitespace_chars",
    "blank_page_fraction",
    "pathological_page_fraction",
    "column_risk_page_fraction",
}
IDENTITY_KEYS = {"path", "sha256", "size_bytes", "magic", "page_count"}
QUALITY_INPUT_KEYS = {"path", "sha256", "quality_id", "quality_digest"}
NORMALIZATION_TOP_KEYS = {
    "schema",
    "schema_version",
    "producer",
    "generated_at",
    "method",
    "quality_input",
    "original",
    "derivative",
    "tools",
    "argv",
    "settings",
    "quality_before",
    "quality_after",
    "review_required",
    "review_reasons",
    "accuracy_claim",
    "lineage_id",
    "lineage_digest",
}
ADOPTED_NORMALIZATION_TOP_KEYS = NORMALIZATION_TOP_KEYS | {
    "adoption_mode",
    "provenance",
    "validation_tools",
}
PROVENANCE_KEYS = {
    "status",
    "statement",
    "creation_method",
    "tools_role",
    "argv_role",
}


class ContractError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "contract_error",
        missing_tools: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.missing_tools = missing_tools or []


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strict_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ContractError(f"{label} keys mismatch; missing={missing}, unknown={unknown}")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value


def require_timestamp(value: Any, label: str) -> str:
    text = require_string(value, label)
    if not text.endswith("Z"):
        raise ContractError(f"{label} must be canonical UTC ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError(f"{label} must be ISO-8601") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ContractError(f"{label} must be UTC")
    return text


def require_argv_list(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ContractError(f"{label} must be a non-empty string list")
    return list(value)


def parse_argv_json(value: str | None, label: str) -> list[str] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ContractError(f"{label} must be a JSON string list") from exc
    return require_argv_list(parsed, label)


def absolute_path(path_value: str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ContractError(f"{label} must be absolute")
    return path


def regular_file(path_value: str, label: str) -> Path:
    path = absolute_path(path_value, label)
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label} must be a regular non-symlink file: {path}")
    return path


def output_path(path_value: str, label: str) -> Path:
    path = absolute_path(path_value, label)
    if path.exists() or path.is_symlink():
        raise ContractError(f"refusing to overwrite existing {label}: {path}", code="exists")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ContractError(f"{label} parent must be an existing regular directory")
    return path


def tool_path(path_value: str, label: str) -> tuple[Path, Path]:
    path = absolute_path(path_value, label)
    if not path.exists() or not path.is_file() or not os.access(path, os.X_OK):
        raise ContractError(
            f"required tool is missing or not executable: {label}",
            code="missing_tool",
            missing_tools=[label],
        )
    return path, path.resolve(strict=True)


def run_tool(argv: list[str], label: str, *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"{label} could not run", code="tool_failed") from exc
    if result.returncode != 0:
        raise ContractError(
            f"{label} failed with exit code {result.returncode}", code="tool_failed"
        )
    return result


def probe_tool(path_value: str, label: str) -> dict[str, Any]:
    path, resolved = tool_path(path_value, label)
    probes = ["--version", "-v"] if label == "tesseract" else ["-v", "--version"]
    for flag in probes:
        try:
            result = subprocess.run(
                [str(path), flag],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                timeout=20,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        banner = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        first = banner.splitlines()[0][:300] if banner else ""
        if result.returncode == 0 and VERSION_RE.search(first):
            return {
                "path": str(path),
                "resolved_path": str(resolved),
                "version": first,
                "version_argv": [str(path), flag],
            }
    raise ContractError(
        f"cannot obtain a recognizable version from {label}", code="tool_version_failed"
    )


def pdf_identity(path: Path, *, recorded_path: Path | None = None) -> dict[str, Any]:
    with path.open("rb") as handle:
        magic = handle.read(5)
    if magic != b"%PDF-":
        raise ContractError(f"file does not have PDF magic: {path}", code="invalid_pdf")
    return {
        "path": str(recorded_path or path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "magic": "%PDF-",
    }


def pdf_page_count(path: Path, pdfinfo: str) -> int:
    result = run_tool([pdfinfo, str(path)], "pdfinfo")
    match = re.search(r"(?mi)^Pages:\s*(\d+)\s*$", result.stdout + "\n" + result.stderr)
    if match is None or int(match.group(1)) <= 0:
        raise ContractError("pdfinfo did not report a positive page count", code="page_count")
    return int(match.group(1))


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON: {path}") from exc


def bundle_ref(path_value: str | None, source_sha256: str) -> dict[str, Any] | None:
    if path_value is None:
        return None
    path = regular_file(path_value, "source_bundle")
    bundle = load_json(path)
    if not isinstance(bundle, dict) or bundle.get("schema") != "PaperSourceBundle/v1":
        raise ContractError("source bundle schema must be PaperSourceBundle/v1")
    source = bundle.get("source")
    if not isinstance(source, dict) or source.get("source_sha256") != source_sha256:
        raise ContractError("source bundle does not bind the inspected PDF SHA-256")
    digest = require_string(bundle.get("bundle_digest"), "bundle.bundle_digest")
    bundle_id = require_string(bundle.get("bundle_id"), "bundle.bundle_id")
    if not SHA256_RE.fullmatch(digest):
        raise ContractError("bundle.bundle_digest is invalid")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "bundle_id": bundle_id,
        "bundle_digest": digest,
        "source_sha256": source_sha256,
    }


def extract_pages(path: Path, pdftotext: str, page_count: int, work: Path) -> list[str]:
    output = work / "layout.txt"
    run_tool(
        [pdftotext, "-layout", "-enc", "UTF-8", str(path), str(output)],
        "pdftotext",
    )
    try:
        text = output.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ContractError("pdftotext did not create readable UTF-8 output") from exc
    pages = text.split("\f")
    while len(pages) > page_count and not pages[-1].strip():
        pages.pop()
    if len(pages) < page_count:
        pages.extend([""] * (page_count - len(pages)))
    if len(pages) != page_count:
        raise ContractError(
            f"text page split mismatch: expected {page_count}, got {len(pages)}",
            code="page_split",
        )
    return pages


def rounded(value: float) -> float:
    return round(value, 6)


def page_metrics(page: str, page_index: int) -> dict[str, Any]:
    lines = page.splitlines()
    nonempty = [line for line in lines if line.strip()]
    lengths = [len(line) for line in lines]
    tokens = re.findall(r"\w+", page.casefold(), flags=re.UNICODE)
    repeated = max(Counter(tokens).values()) / len(tokens) if tokens else 0.0
    extracted = len(page)
    non_whitespace = sum(not char.isspace() for char in page)
    replacement = page.count("\ufffd")
    control = sum(
        ord(char) < 32 and char not in "\n\r\t\f" for char in page
    )
    long_lines = sum(
        len(line) >= THRESHOLDS["pathological_long_line_chars_min"] for line in lines
    )
    column_gap = " " * THRESHOLDS["column_gap_spaces_min"]

    def has_column_gap(line: str) -> bool:
        offset = line.find(column_gap)
        return (
            offset >= 3
            and bool(line[:offset].strip())
            and bool(line[offset + len(column_gap) :].strip())
        )

    column_lines = sum(has_column_gap(line) for line in nonempty)
    denom_chars = max(extracted, 1)
    denom_lines = max(len(lines), 1)
    denom_nonempty = max(len(nonempty), 1)
    replacement_fraction = replacement / denom_chars
    control_fraction = control / denom_chars
    column_fraction = column_lines / denom_nonempty
    pathological = (
        extracted >= THRESHOLDS["pathological_page_chars_max"]
        or (max(lengths, default=0) >= THRESHOLDS["pathological_max_line_chars_max"])
        or replacement_fraction > THRESHOLDS["pathological_replacement_fraction_max"]
        or control_fraction > THRESHOLDS["pathological_control_fraction_max"]
        or (len(tokens) >= 100 and repeated > THRESHOLDS["pathological_token_repetition_max"])
    )
    column_risk = (
        len(nonempty) >= THRESHOLDS["column_risk_nonempty_lines_min"]
        and column_fraction >= THRESHOLDS["column_gap_line_fraction_min"]
    )
    if non_whitespace <= THRESHOLDS["blank_non_whitespace_max"]:
        kind = "blank"
    elif pathological:
        kind = "pathological"
    elif column_risk:
        kind = "column_risk"
    else:
        kind = "native"
    return {
        "page_index": page_index,
        "extracted_chars": extracted,
        "non_whitespace_chars": non_whitespace,
        "alphanumeric_chars": sum(char.isalnum() for char in page),
        "replacement_chars": replacement,
        "control_chars": control,
        "line_count": len(lines),
        "nonempty_line_count": len(nonempty),
        "max_line_chars": max(lengths, default=0),
        "mean_line_chars": rounded(sum(lengths) / denom_lines),
        "empty_line_fraction": rounded((len(lines) - len(nonempty)) / denom_lines),
        "long_line_fraction": rounded(long_lines / denom_lines),
        "column_gap_line_fraction": rounded(column_fraction),
        "max_token_repetition": rounded(repeated),
        "page_kind": kind,
    }


def quality_summary(pages: list[dict[str, Any]], source_kind: str) -> dict[str, Any]:
    count = len(pages)
    kinds = Counter(page["page_kind"] for page in pages)
    blank_fraction = kinds["blank"] / count
    pathological_fraction = kinds["pathological"] / count
    column_fraction = kinds["column_risk"] / count
    if blank_fraction >= THRESHOLDS["blank_scan_page_fraction_min"]:
        classification = "blank_scan"
        reasons = ["blank page fraction meets blank_scan threshold"]
    elif (
        pathological_fraction >= THRESHOLDS["pathological_page_fraction_min"]
        or max(page["extracted_chars"] for page in pages)
        >= THRESHOLDS["pathological_single_page_chars_max"]
        or sum(page["extracted_chars"] for page in pages) / count
        >= THRESHOLDS["pathological_mean_page_chars_max"]
    ):
        classification = "pathological_text"
        reasons = ["pathological extraction metrics exceed supported threshold"]
    elif (kinds["blank"] or kinds["pathological"]) and (
        kinds["native"] or kinds["column_risk"]
    ):
        classification = "mixed"
        reasons = ["usable and blank/pathological page classes coexist"]
    elif kinds["blank"] or kinds["pathological"]:
        classification = "mixed"
        reasons = ["a minority of abnormal pages requires review"]
    elif column_fraction >= THRESHOLDS["column_risk_page_fraction_min"]:
        classification = "column_risk"
        reasons = ["layout extraction indicates possible multi-column reading order"]
    else:
        classification = "native_ok"
        reasons = ["all supported extraction-quality gates pass"]
    review_required = classification != "native_ok"
    review_reasons = [] if not review_required else list(reasons)
    if classification == "column_risk":
        review_reasons.append("OCR does not establish semantic column order")
    if source_kind == "ocr_derivative":
        review_required = True
        review_reasons.append(
            "caller-declared OCR derivative requires transcription review"
        )
    return {
        "classification": classification,
        "reasons": reasons,
        "review_required": review_required,
        "review_reasons": review_reasons,
        "normalization_recommended": classification
        in {"blank_scan", "pathological_text", "mixed"},
        "total_extracted_chars": sum(page["extracted_chars"] for page in pages),
        "total_non_whitespace_chars": sum(
            page["non_whitespace_chars"] for page in pages
        ),
        "blank_page_fraction": rounded(blank_fraction),
        "pathological_page_fraction": rounded(pathological_fraction),
        "column_risk_page_fraction": rounded(column_fraction),
    }


def quality_digest(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key not in {"quality_id", "quality_digest"}}
    return sha256_json(payload)


def inspect_document(
    *,
    source_path: str,
    pdfinfo_path: str,
    pdftotext_path: str,
    generated_at: str,
    source_bundle_path: str | None = None,
    recorded_path: Path | None = None,
    source_kind: str = "raw",
) -> dict[str, Any]:
    timestamp = require_timestamp(generated_at, "generated_at")
    if source_kind not in {"raw", "ocr_derivative"}:
        raise ContractError("source_kind must be raw or ocr_derivative")
    source = regular_file(source_path, "source")
    info_tool = probe_tool(pdfinfo_path, "pdfinfo")
    text_tool = probe_tool(pdftotext_path, "pdftotext")
    identity = pdf_identity(source, recorded_path=recorded_path)
    page_count = pdf_page_count(source, info_tool["path"])
    identity["page_count"] = page_count
    identity["name"] = (recorded_path or source).name
    identity["source_kind"] = source_kind
    identity["source_bundle_ref"] = bundle_ref(
        source_bundle_path, identity["sha256"]
    )
    with tempfile.TemporaryDirectory(prefix="scholarly-quality-") as temp:
        pages = extract_pages(source, text_tool["path"], page_count, Path(temp))
    metrics = [page_metrics(page, index + 1) for index, page in enumerate(pages)]
    record = {
        "schema": QUALITY_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "generated_at": timestamp,
        "source": identity,
        "tools": {"pdfinfo": info_tool, "pdftotext": text_tool},
        "thresholds": copy.deepcopy(THRESHOLDS),
        "pages": metrics,
        "summary": quality_summary(metrics, source_kind),
        "quality_id": "",
        "quality_digest": "",
    }
    digest = quality_digest(record)
    record["quality_digest"] = digest
    record["quality_id"] = f"scholarly-document-quality-{digest[:16]}"
    return validate_quality_shape(record)


def validate_tool_shape(value: Any, label: str) -> None:
    tool = strict_keys(value, TOOL_KEYS, label)
    for key in ("path", "resolved_path", "version"):
        require_string(tool.get(key), f"{label}.{key}")
    argv = tool.get("version_argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) for item in argv):
        raise ContractError(f"{label}.version_argv must be a non-empty string list")


def validate_quality_shape(value: Any) -> dict[str, Any]:
    record = strict_keys(copy.deepcopy(value), QUALITY_TOP_KEYS, "quality")
    if record.get("schema") != QUALITY_SCHEMA or record.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported quality schema/version")
    if record.get("producer") != PRODUCER:
        raise ContractError("quality.producer is invalid")
    require_timestamp(record.get("generated_at"), "quality.generated_at")
    source = strict_keys(record.get("source"), SOURCE_KEYS, "quality.source")
    require_string(source.get("path"), "quality.source.path")
    require_string(source.get("name"), "quality.source.name")
    if source.get("magic") != "%PDF-" or not SHA256_RE.fullmatch(str(source.get("sha256"))):
        raise ContractError("quality source identity is invalid")
    if not isinstance(source.get("size_bytes"), int) or source["size_bytes"] <= 5:
        raise ContractError("quality.source.size_bytes is invalid")
    if not isinstance(source.get("page_count"), int) or source["page_count"] <= 0:
        raise ContractError("quality.source.page_count is invalid")
    if source.get("source_kind") not in {"raw", "ocr_derivative"}:
        raise ContractError("quality.source.source_kind is invalid")
    if source.get("source_bundle_ref") is not None:
        ref = strict_keys(source["source_bundle_ref"], BUNDLE_REF_KEYS, "source_bundle_ref")
        for key in ("sha256", "bundle_digest", "source_sha256"):
            if not SHA256_RE.fullmatch(str(ref.get(key))):
                raise ContractError(f"source_bundle_ref.{key} is invalid")
        if ref["source_sha256"] != source["sha256"]:
            raise ContractError("source bundle/source SHA mismatch")
    tools = strict_keys(record.get("tools"), {"pdfinfo", "pdftotext"}, "quality.tools")
    for name, tool in tools.items():
        validate_tool_shape(tool, f"quality.tools.{name}")
    if record.get("thresholds") != THRESHOLDS:
        raise ContractError("quality.thresholds are unsupported")
    pages = record.get("pages")
    if not isinstance(pages, list) or len(pages) != source["page_count"]:
        raise ContractError("quality.pages must match source page_count")
    for index, raw_page in enumerate(pages, start=1):
        page = strict_keys(raw_page, PAGE_KEYS, f"quality.pages[{index - 1}]")
        if page.get("page_index") != index:
            raise ContractError("quality page indexes must be contiguous")
        if page.get("page_kind") not in {"blank", "pathological", "column_risk", "native"}:
            raise ContractError("quality page_kind is invalid")
    summary = strict_keys(record.get("summary"), SUMMARY_KEYS, "quality.summary")
    if summary.get("classification") not in {
        "native_ok",
        "blank_scan",
        "pathological_text",
        "mixed",
        "column_risk",
    }:
        raise ContractError("quality classification is invalid")
    if not isinstance(summary.get("review_required"), bool) or not isinstance(
        summary.get("normalization_recommended"), bool
    ):
        raise ContractError("quality summary booleans are invalid")
    digest = quality_digest(record)
    if record.get("quality_digest") != digest:
        raise ContractError("quality_digest mismatch")
    if record.get("quality_id") != f"scholarly-document-quality-{digest[:16]}":
        raise ContractError("quality_id mismatch")
    return record


def validate_quality_record(
    record: Any,
    *,
    source_path: str,
    pdfinfo_path: str,
    pdftotext_path: str,
    source_bundle_path: str | None,
) -> dict[str, Any]:
    expected = validate_quality_shape(record)
    if expected["source"]["path"] != source_path:
        raise ContractError("quality source path does not match live source")
    regenerated = inspect_document(
        source_path=source_path,
        pdfinfo_path=pdfinfo_path,
        pdftotext_path=pdftotext_path,
        generated_at=expected["generated_at"],
        source_bundle_path=source_bundle_path,
        source_kind=expected["source"]["source_kind"],
    )
    if regenerated != expected:
        raise ContractError("quality record does not match deterministic live regeneration")
    return regenerated


def identity_with_pages(path: Path, pdfinfo: str, *, recorded_path: Path | None = None) -> dict[str, Any]:
    identity = pdf_identity(path, recorded_path=recorded_path)
    identity["page_count"] = pdf_page_count(path, pdfinfo)
    return identity


def lineage_digest(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key not in {"lineage_id", "lineage_digest"}}
    return sha256_json(payload)


def validate_identity_shape(value: Any, label: str) -> None:
    identity = strict_keys(value, IDENTITY_KEYS, label)
    require_string(identity.get("path"), f"{label}.path")
    if identity.get("magic") != "%PDF-" or not SHA256_RE.fullmatch(str(identity.get("sha256"))):
        raise ContractError(f"{label} identity is invalid")
    if not isinstance(identity.get("size_bytes"), int) or identity["size_bytes"] <= 5:
        raise ContractError(f"{label}.size_bytes is invalid")
    if not isinstance(identity.get("page_count"), int) or identity["page_count"] <= 0:
        raise ContractError(f"{label}.page_count is invalid")


def validate_normalization_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("method") == "adopt-existing":
        return validate_adopted_normalization_shape(value)
    record = strict_keys(copy.deepcopy(value), NORMALIZATION_TOP_KEYS, "normalization")
    if record.get("schema") != NORMALIZATION_SCHEMA or record.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported normalization schema/version")
    if record.get("producer") != PRODUCER:
        raise ContractError("normalization.producer is invalid")
    require_timestamp(record.get("generated_at"), "normalization.generated_at")
    if record.get("method") != "pdftoppm+tesseract+pdfunite":
        raise ContractError("normalization.method is invalid")
    quality_input = strict_keys(record.get("quality_input"), QUALITY_INPUT_KEYS, "quality_input")
    for key in ("sha256", "quality_digest"):
        if not SHA256_RE.fullmatch(str(quality_input.get(key))):
            raise ContractError(f"quality_input.{key} is invalid")
    validate_identity_shape(record.get("original"), "normalization.original")
    validate_identity_shape(record.get("derivative"), "normalization.derivative")
    if record["original"]["page_count"] != record["derivative"]["page_count"]:
        raise ContractError("normalization page counts differ")
    tools = strict_keys(
        record.get("tools"),
        {"pdfinfo", "pdftotext", "pdftoppm", "tesseract", "pdfunite"},
        "normalization.tools",
    )
    for name, tool in tools.items():
        validate_tool_shape(tool, f"normalization.tools.{name}")
    argv = strict_keys(record.get("argv"), {"render", "ocr", "assemble"}, "normalization.argv")
    for name, items in argv.items():
        require_argv_list(items, f"normalization.argv.{name}")
    settings = strict_keys(record.get("settings"), {"dpi", "languages"}, "normalization.settings")
    if not isinstance(settings.get("dpi"), int) or not 72 <= settings["dpi"] <= 600:
        raise ContractError("normalization.settings.dpi is invalid")
    if not LANGUAGE_RE.fullmatch(str(settings.get("languages"))):
        raise ContractError("normalization.settings.languages is invalid")
    before = validate_quality_shape(record.get("quality_before"))
    after = validate_quality_shape(record.get("quality_after"))
    if before["source"]["sha256"] != record["original"]["sha256"]:
        raise ContractError("before quality does not bind original")
    if after["source"]["sha256"] != record["derivative"]["sha256"]:
        raise ContractError("after quality does not bind derivative")
    if record.get("review_required") is not True:
        raise ContractError("OCR normalization must remain review_required")
    reasons = record.get("review_reasons")
    if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) or not item for item in reasons):
        raise ContractError("normalization.review_reasons must be non-empty")
    if record.get("accuracy_claim") != "not_assessed":
        raise ContractError("OCR accuracy must remain not_assessed")
    digest = lineage_digest(record)
    if record.get("lineage_digest") != digest:
        raise ContractError("lineage_digest mismatch")
    if record.get("lineage_id") != f"scholarly-document-normalization-{digest[:16]}":
        raise ContractError("lineage_id mismatch")
    return record


def validate_adopted_normalization_shape(value: Any) -> dict[str, Any]:
    record = strict_keys(
        copy.deepcopy(value), ADOPTED_NORMALIZATION_TOP_KEYS, "normalization"
    )
    if record.get("schema") != NORMALIZATION_SCHEMA or record.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported adopted normalization schema/version")
    if record.get("producer") != PRODUCER:
        raise ContractError("normalization.producer is invalid")
    require_timestamp(record.get("generated_at"), "normalization.generated_at")
    if record.get("method") != "adopt-existing":
        raise ContractError("adopted normalization.method is invalid")
    if record.get("adoption_mode") != "existing_derivative_no_ocr_execution":
        raise ContractError("normalization.adoption_mode is invalid")
    quality_input = strict_keys(
        record.get("quality_input"), QUALITY_INPUT_KEYS, "quality_input"
    )
    for key in ("sha256", "quality_digest"):
        if not SHA256_RE.fullmatch(str(quality_input.get(key))):
            raise ContractError(f"quality_input.{key} is invalid")
    validate_identity_shape(record.get("original"), "normalization.original")
    validate_identity_shape(record.get("derivative"), "normalization.derivative")
    if record["original"]["sha256"] == record["derivative"]["sha256"]:
        raise ContractError("adopted derivative must differ from original")
    if record["original"]["page_count"] != record["derivative"]["page_count"]:
        raise ContractError("normalization page counts differ")
    tools = strict_keys(
        record.get("tools"),
        {"pdfinfo", "pdftotext", "pdftoppm", "tesseract", "pdfunite"},
        "normalization.tools",
    )
    for name, tool in tools.items():
        validate_tool_shape(tool, f"normalization.tools.{name}")
    validation_tools = strict_keys(
        record.get("validation_tools"),
        {"pdfinfo", "pdftotext"},
        "normalization.validation_tools",
    )
    for name, tool in validation_tools.items():
        validate_tool_shape(tool, f"normalization.validation_tools.{name}")
        if tool != tools[name]:
            raise ContractError(f"validation tool {name} must match probed tool identity")
    argv = strict_keys(
        record.get("argv"), {"render", "ocr", "assemble"}, "normalization.argv"
    )
    for name, items in argv.items():
        require_argv_list(items, f"normalization.argv.{name}")
    settings = strict_keys(
        record.get("settings"), {"dpi", "languages"}, "normalization.settings"
    )
    if not isinstance(settings.get("dpi"), int) or not 72 <= settings["dpi"] <= 600:
        raise ContractError("normalization.settings.dpi is invalid")
    if not LANGUAGE_RE.fullmatch(str(settings.get("languages"))):
        raise ContractError("normalization.settings.languages is invalid")
    provenance = strict_keys(
        record.get("provenance"), PROVENANCE_KEYS, "normalization.provenance"
    )
    if provenance.get("status") not in {"recorded", "reconstructed"}:
        raise ContractError("normalization.provenance.status is invalid")
    require_string(provenance.get("statement"), "normalization.provenance.statement")
    if provenance.get("creation_method") != "pdftoppm+tesseract+pdfunite":
        raise ContractError("normalization.provenance.creation_method is invalid")
    require_string(provenance.get("tools_role"), "normalization.provenance.tools_role")
    require_string(provenance.get("argv_role"), "normalization.provenance.argv_role")
    before = validate_quality_shape(record.get("quality_before"))
    after = validate_quality_shape(record.get("quality_after"))
    if before["source"]["source_kind"] != "raw":
        raise ContractError("before quality must describe the raw original")
    if after["source"]["source_kind"] != "ocr_derivative":
        raise ContractError("after quality must declare an OCR derivative")
    if before["source"]["sha256"] != record["original"]["sha256"]:
        raise ContractError("before quality does not bind original")
    if after["source"]["sha256"] != record["derivative"]["sha256"]:
        raise ContractError("after quality does not bind derivative")
    if after["summary"]["classification"] in {
        "blank_scan",
        "pathological_text",
        "mixed",
    }:
        raise ContractError("adopted derivative fails extraction quality gates")
    if record.get("review_required") is not True:
        raise ContractError("adopted OCR must remain review_required")
    reasons = record.get("review_reasons")
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not item for item in reasons)
    ):
        raise ContractError("normalization.review_reasons must be non-empty")
    if record.get("accuracy_claim") != "not_assessed":
        raise ContractError("OCR accuracy must remain not_assessed")
    digest = lineage_digest(record)
    if record.get("lineage_digest") != digest:
        raise ContractError("lineage_digest mismatch")
    if record.get("lineage_id") != f"scholarly-document-normalization-{digest[:16]}":
        raise ContractError("lineage_id mismatch")
    return record


def numeric_page_key(path: Path) -> tuple[int, str]:
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    return (int(match.group(1)) if match else math.inf, path.name)


def publish_pair(files: list[tuple[Path, Path]]) -> None:
    published: list[Path] = []
    try:
        for source, destination in files:
            with source.open("rb") as reader, destination.open("xb") as writer:
                published.append(destination)
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
            destination.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        for path in published:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise


def normalize_document(
    *,
    source_path: str,
    quality_path: str,
    output_pdf_path: str,
    output_record_path: str,
    pdfinfo_path: str,
    pdftotext_path: str,
    pdftoppm_path: str,
    tesseract_path: str,
    pdfunite_path: str,
    generated_at: str,
    source_bundle_path: str | None,
    dpi: int,
    languages: str,
) -> dict[str, Any]:
    timestamp = require_timestamp(generated_at, "generated_at")
    source = regular_file(source_path, "source")
    quality_file = regular_file(quality_path, "quality")
    output_pdf = output_path(output_pdf_path, "output_pdf")
    output_record = output_path(output_record_path, "output_record")
    if not 72 <= dpi <= 600:
        raise ContractError("dpi must be between 72 and 600")
    if not LANGUAGE_RE.fullmatch(languages):
        raise ContractError("languages has unsupported characters")
    before = validate_quality_record(
        load_json(quality_file),
        source_path=source_path,
        pdfinfo_path=pdfinfo_path,
        pdftotext_path=pdftotext_path,
        source_bundle_path=source_bundle_path,
    )
    classification = before["summary"]["classification"]
    if classification == "native_ok":
        raise ContractError("native_ok source must use an explicit skip artifact", code="not_required")
    if classification == "column_risk":
        raise ContractError(
            "column_risk requires layout review; OCR is not a reading-order repair",
            code="manual_review_required",
        )
    if before["source"]["source_kind"] != "raw":
        raise ContractError("normalization quality input must describe the raw source")
    tools = {
        "pdfinfo": before["tools"]["pdfinfo"],
        "pdftotext": before["tools"]["pdftotext"],
        "pdftoppm": probe_tool(pdftoppm_path, "pdftoppm"),
        "tesseract": probe_tool(tesseract_path, "tesseract"),
        "pdfunite": probe_tool(pdfunite_path, "pdfunite"),
    }
    original = identity_with_pages(source, tools["pdfinfo"]["path"])
    with tempfile.TemporaryDirectory(
        prefix=".scholarly-normalization-", dir=output_pdf.parent
    ) as temp:
        work = Path(temp)
        prefix = work / "page"
        run_tool(
            [
                tools["pdftoppm"]["path"],
                "-r",
                str(dpi),
                "-png",
                str(source),
                str(prefix),
            ],
            "pdftoppm",
        )
        images = sorted(work.glob("page-*.png"), key=numeric_page_key)
        if len(images) != original["page_count"]:
            raise ContractError(
                f"pdftoppm page count mismatch: {len(images)}",
                code="render_page_count",
            )
        page_pdfs: list[Path] = []
        for index, image in enumerate(images, start=1):
            base = work / f"ocr-{index:06d}"
            run_tool(
                [
                    tools["tesseract"]["path"],
                    str(image),
                    str(base),
                    "-l",
                    languages,
                    "pdf",
                ],
                "tesseract",
            )
            page_pdf = base.with_suffix(".pdf")
            if not page_pdf.is_file() or page_pdf.is_symlink():
                raise ContractError("tesseract did not create a page PDF", code="ocr_output")
            page_pdfs.append(page_pdf)
        staged_pdf = work / "normalized.pdf"
        run_tool(
            [tools["pdfunite"]["path"], *map(str, page_pdfs), str(staged_pdf)],
            "pdfunite",
        )
        derivative = identity_with_pages(
            staged_pdf, tools["pdfinfo"]["path"], recorded_path=output_pdf
        )
        if derivative["page_count"] != original["page_count"]:
            raise ContractError("derivative page count differs from original", code="page_count")
        after = inspect_document(
            source_path=str(staged_pdf),
            pdfinfo_path=pdfinfo_path,
            pdftotext_path=pdftotext_path,
            generated_at=timestamp,
            recorded_path=output_pdf,
            source_kind="ocr_derivative",
        )
        if after["summary"]["classification"] in {
            "blank_scan",
            "pathological_text",
            "mixed",
        }:
            raise ContractError(
                "normalized derivative still fails extraction quality gates",
                code="ineffective_normalization",
            )
        record = {
            "schema": NORMALIZATION_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "producer": PRODUCER,
            "generated_at": timestamp,
            "method": "pdftoppm+tesseract+pdfunite",
            "quality_input": {
                "path": str(quality_file),
                "sha256": sha256_file(quality_file),
                "quality_id": before["quality_id"],
                "quality_digest": before["quality_digest"],
            },
            "original": original,
            "derivative": derivative,
            "tools": tools,
            "argv": {
                "render": [
                    tools["pdftoppm"]["path"],
                    "-r",
                    str(dpi),
                    "-png",
                    "{original_pdf}",
                    "{workdir}/page",
                ],
                "ocr": [
                    tools["tesseract"]["path"],
                    "{page_image}",
                    "{page_output_base}",
                    "-l",
                    languages,
                    "pdf",
                ],
                "assemble": [
                    tools["pdfunite"]["path"],
                    "{page_pdfs...}",
                    "{derivative_pdf}",
                ],
            },
            "settings": {"dpi": dpi, "languages": languages},
            "quality_before": before,
            "quality_after": after,
            "review_required": True,
            "review_reasons": [
                "OCR extractability does not establish transcription accuracy",
                "equations, figures, tables, and semantic reading order require source review",
            ],
            "accuracy_claim": "not_assessed",
            "lineage_id": "",
            "lineage_digest": "",
        }
        digest = lineage_digest(record)
        record["lineage_digest"] = digest
        record["lineage_id"] = f"scholarly-document-normalization-{digest[:16]}"
        record = validate_normalization_shape(record)
        staged_record = work / "normalization.json"
        staged_record.write_bytes(canonical_bytes(record) + b"\n")
        publish_pair([(staged_pdf, output_pdf), (staged_record, output_record)])
    return record


def adoption_argv(
    *,
    tools: dict[str, dict[str, Any]],
    dpi: int,
    languages: str,
    provenance_status: str,
    render_argv: list[str] | None,
    ocr_argv: list[str] | None,
    assemble_argv: list[str] | None,
) -> dict[str, list[str]]:
    provided = {
        "render": render_argv,
        "ocr": ocr_argv,
        "assemble": assemble_argv,
    }
    if provenance_status == "recorded" and any(value is None for value in provided.values()):
        raise ContractError(
            "recorded provenance requires explicit render, OCR, and assemble argv"
        )
    defaults = {
        "render": [
            tools["pdftoppm"]["path"],
            "-r",
            str(dpi),
            "-png",
            "{original_pdf}",
            "{workdir}/page",
        ],
        "ocr": [
            tools["tesseract"]["path"],
            "{page_image}",
            "{page_output_base}",
            "-l",
            languages,
            "pdf",
        ],
        "assemble": [
            tools["pdfunite"]["path"],
            "{page_pdfs...}",
            "{derivative_pdf}",
        ],
    }
    return {
        name: require_argv_list(
            defaults[name] if value is None else value,
            f"normalization.argv.{name}",
        )
        for name, value in provided.items()
    }


def adopt_existing_document(
    *,
    source_path: str,
    derivative_path: str,
    quality_path: str,
    output_record_path: str,
    pdfinfo_path: str,
    pdftotext_path: str,
    pdftoppm_path: str,
    tesseract_path: str,
    pdfunite_path: str,
    generated_at: str,
    source_bundle_path: str | None,
    dpi: int,
    languages: str,
    provenance_status: str,
    provenance_statement: str,
    render_argv: list[str] | None = None,
    ocr_argv: list[str] | None = None,
    assemble_argv: list[str] | None = None,
) -> dict[str, Any]:
    timestamp = require_timestamp(generated_at, "generated_at")
    source = regular_file(source_path, "source")
    derivative = regular_file(derivative_path, "derivative")
    quality_file = regular_file(quality_path, "quality")
    output_record = output_path(output_record_path, "output_record")
    if os.path.samefile(source, derivative):
        raise ContractError("adopted derivative must be a distinct file")
    if not 72 <= dpi <= 600:
        raise ContractError("dpi must be between 72 and 600")
    if not LANGUAGE_RE.fullmatch(languages):
        raise ContractError("languages has unsupported characters")
    if provenance_status not in {"recorded", "reconstructed"}:
        raise ContractError("provenance_status must be recorded or reconstructed")
    statement = require_string(provenance_statement, "provenance_statement")
    before = validate_quality_record(
        load_json(quality_file),
        source_path=source_path,
        pdfinfo_path=pdfinfo_path,
        pdftotext_path=pdftotext_path,
        source_bundle_path=source_bundle_path,
    )
    classification = before["summary"]["classification"]
    if classification == "native_ok":
        raise ContractError("native_ok source does not require OCR adoption", code="not_required")
    if classification == "column_risk":
        raise ContractError(
            "column_risk requires layout review; OCR is not a reading-order repair",
            code="manual_review_required",
        )
    if before["source"]["source_kind"] != "raw":
        raise ContractError("adoption quality input must describe the raw source")
    tools = {
        "pdfinfo": probe_tool(pdfinfo_path, "pdfinfo"),
        "pdftotext": probe_tool(pdftotext_path, "pdftotext"),
        "pdftoppm": probe_tool(pdftoppm_path, "pdftoppm"),
        "tesseract": probe_tool(tesseract_path, "tesseract"),
        "pdfunite": probe_tool(pdfunite_path, "pdfunite"),
    }
    original = identity_with_pages(source, tools["pdfinfo"]["path"])
    adopted = identity_with_pages(derivative, tools["pdfinfo"]["path"])
    if original["sha256"] == adopted["sha256"]:
        raise ContractError("adopted derivative must differ from original")
    if original["page_count"] != adopted["page_count"]:
        raise ContractError("adopted derivative page count differs from original")
    after = inspect_document(
        source_path=derivative_path,
        pdfinfo_path=pdfinfo_path,
        pdftotext_path=pdftotext_path,
        generated_at=timestamp,
        source_kind="ocr_derivative",
    )
    if after["summary"]["classification"] in {
        "blank_scan",
        "pathological_text",
        "mixed",
    }:
        raise ContractError(
            "adopted derivative still fails extraction quality gates",
            code="ineffective_normalization",
        )
    argv = adoption_argv(
        tools=tools,
        dpi=dpi,
        languages=languages,
        provenance_status=provenance_status,
        render_argv=render_argv,
        ocr_argv=ocr_argv,
        assemble_argv=assemble_argv,
    )
    provenance = {
        "status": provenance_status,
        "statement": statement,
        "creation_method": "pdftoppm+tesseract+pdfunite",
        "tools_role": (
            "live-probed executable identities supplied at adoption; not proof of the "
            "historical execution environment"
        ),
        "argv_role": (
            "caller-recorded historical argv"
            if provenance_status == "recorded"
            else "caller-declared reconstruction templates; not historical execution proof"
        ),
    }
    record = {
        "schema": NORMALIZATION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "generated_at": timestamp,
        "method": "adopt-existing",
        "adoption_mode": "existing_derivative_no_ocr_execution",
        "quality_input": {
            "path": str(quality_file),
            "sha256": sha256_file(quality_file),
            "quality_id": before["quality_id"],
            "quality_digest": before["quality_digest"],
        },
        "original": original,
        "derivative": adopted,
        "tools": tools,
        "validation_tools": {
            "pdfinfo": tools["pdfinfo"],
            "pdftotext": tools["pdftotext"],
        },
        "argv": argv,
        "settings": {"dpi": dpi, "languages": languages},
        "provenance": provenance,
        "quality_before": before,
        "quality_after": after,
        "review_required": True,
        "review_reasons": [
            "The existing derivative was adopted without rerunning OCR",
            "OCR extractability does not establish transcription accuracy",
            "equations, figures, tables, and semantic reading order require source review",
            f"OCR execution provenance is {provenance_status}",
        ],
        "accuracy_claim": "not_assessed",
        "lineage_id": "",
        "lineage_digest": "",
    }
    digest = lineage_digest(record)
    record["lineage_digest"] = digest
    record["lineage_id"] = f"scholarly-document-normalization-{digest[:16]}"
    record = validate_normalization_shape(record)
    if (
        identity_with_pages(source, tools["pdfinfo"]["path"]) != original
        or identity_with_pages(derivative, tools["pdfinfo"]["path"]) != adopted
    ):
        raise ContractError("adoption inputs changed during inspection", code="input_changed")
    write_json_exclusive(str(output_record), record)
    return record


def validate_normalization_record(
    record: Any,
    *,
    source_path: str,
    derivative_path: str,
    quality_path: str,
    pdfinfo_path: str,
    pdftotext_path: str,
    source_bundle_path: str | None,
) -> dict[str, Any]:
    expected = validate_normalization_shape(record)
    source = regular_file(source_path, "source")
    derivative = regular_file(derivative_path, "derivative")
    quality_file = regular_file(quality_path, "quality")
    if expected["original"]["path"] != source_path:
        raise ContractError("normalization original path mismatch")
    if expected["derivative"]["path"] != derivative_path:
        raise ContractError("normalization derivative path mismatch")
    if expected["quality_input"]["path"] != quality_path:
        raise ContractError("normalization quality path mismatch")
    if expected["quality_input"]["sha256"] != sha256_file(quality_file):
        raise ContractError("normalization quality artifact SHA mismatch")
    if expected["tools"]["pdfinfo"]["path"] != pdfinfo_path:
        raise ContractError("normalization pdfinfo path mismatch")
    if expected["tools"]["pdftotext"]["path"] != pdftotext_path:
        raise ContractError("normalization pdftotext path mismatch")
    if expected["method"] == "adopt-existing":
        if expected["validation_tools"] != {
            "pdfinfo": expected["tools"]["pdfinfo"],
            "pdftotext": expected["tools"]["pdftotext"],
        }:
            raise ContractError("adoption validation tool identity mismatch")
        for name, recorded_tool in expected["tools"].items():
            if probe_tool(recorded_tool["path"], name) != recorded_tool:
                raise ContractError(f"adoption tool identity changed: {name}")
    live_original = identity_with_pages(source, pdfinfo_path)
    live_derivative = identity_with_pages(derivative, pdfinfo_path)
    if live_original != expected["original"] or live_derivative != expected["derivative"]:
        raise ContractError("normalization live PDF identity mismatch")
    before = validate_quality_record(
        load_json(quality_file),
        source_path=source_path,
        pdfinfo_path=pdfinfo_path,
        pdftotext_path=pdftotext_path,
        source_bundle_path=source_bundle_path,
    )
    after = inspect_document(
        source_path=derivative_path,
        pdfinfo_path=pdfinfo_path,
        pdftotext_path=pdftotext_path,
        generated_at=expected["quality_after"]["generated_at"],
        source_kind="ocr_derivative",
    )
    if before != expected["quality_before"] or after != expected["quality_after"]:
        raise ContractError("normalization quality lineage mismatch")
    return expected


def write_json_exclusive(path_value: str, value: Any) -> None:
    path = output_path(path_value, "output")
    try:
        with path.open("xb") as handle:
            handle.write(canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--source", required=True)
    inspect.add_argument("--source-bundle")
    inspect.add_argument(
        "--source-kind", choices=("raw", "ocr_derivative"), default="raw"
    )
    inspect.add_argument("--pdfinfo", required=True)
    inspect.add_argument("--pdftotext", required=True)
    inspect.add_argument("--generated-at", required=True)
    inspect.add_argument("--output", required=True)

    normalize = commands.add_parser("normalize")
    normalize.add_argument("--source", required=True)
    normalize.add_argument("--source-bundle")
    normalize.add_argument("--quality", required=True)
    normalize.add_argument("--pdfinfo", required=True)
    normalize.add_argument("--pdftotext", required=True)
    normalize.add_argument("--pdftoppm", required=True)
    normalize.add_argument("--tesseract", required=True)
    normalize.add_argument("--pdfunite", required=True)
    normalize.add_argument("--dpi", type=int, default=300)
    normalize.add_argument("--languages", default="eng")
    normalize.add_argument("--generated-at", required=True)
    normalize.add_argument("--output-pdf", required=True)
    normalize.add_argument("--output-record", required=True)

    adopt = commands.add_parser("adopt-existing")
    adopt.add_argument("--source", required=True)
    adopt.add_argument("--derivative", required=True)
    adopt.add_argument("--quality", required=True)
    adopt.add_argument("--source-bundle")
    adopt.add_argument("--pdfinfo", required=True)
    adopt.add_argument("--pdftotext", required=True)
    adopt.add_argument("--pdftoppm", required=True)
    adopt.add_argument("--tesseract", required=True)
    adopt.add_argument("--pdfunite", required=True)
    adopt.add_argument("--dpi", type=int, default=300)
    adopt.add_argument("--languages", default="eng")
    adopt.add_argument(
        "--provenance-status", choices=("recorded", "reconstructed"), required=True
    )
    adopt.add_argument("--provenance-statement", required=True)
    adopt.add_argument("--render-argv-json")
    adopt.add_argument("--ocr-argv-json")
    adopt.add_argument("--assemble-argv-json")
    adopt.add_argument("--generated-at", required=True)
    adopt.add_argument("--output-record", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--input", required=True)
    validate.add_argument("--source", required=True)
    validate.add_argument("--derivative")
    validate.add_argument("--quality")
    validate.add_argument("--source-bundle")
    validate.add_argument("--pdfinfo", required=True)
    validate.add_argument("--pdftotext", required=True)
    return root


def failure(command: str, exc: Exception) -> dict[str, Any]:
    return {
        "schema": FAILURE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "code": getattr(exc, "code", "runtime_error"),
        "message": str(exc),
        "missing_tools": getattr(exc, "missing_tools", []),
        "temporary_artifacts_cleaned": True,
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "inspect":
            record = inspect_document(
                source_path=args.source,
                source_bundle_path=args.source_bundle,
                pdfinfo_path=args.pdfinfo,
                pdftotext_path=args.pdftotext,
                generated_at=args.generated_at,
                source_kind=args.source_kind,
            )
            write_json_exclusive(args.output, record)
            result = {
                "schema": record["schema"],
                "quality_id": record["quality_id"],
                "quality_digest": record["quality_digest"],
                "classification": record["summary"]["classification"],
                "review_required": record["summary"]["review_required"],
            }
        elif args.command == "normalize":
            record = normalize_document(
                source_path=args.source,
                source_bundle_path=args.source_bundle,
                quality_path=args.quality,
                output_pdf_path=args.output_pdf,
                output_record_path=args.output_record,
                pdfinfo_path=args.pdfinfo,
                pdftotext_path=args.pdftotext,
                pdftoppm_path=args.pdftoppm,
                tesseract_path=args.tesseract,
                pdfunite_path=args.pdfunite,
                generated_at=args.generated_at,
                dpi=args.dpi,
                languages=args.languages,
            )
            result = {
                "schema": record["schema"],
                "lineage_id": record["lineage_id"],
                "lineage_digest": record["lineage_digest"],
                "derivative_sha256": record["derivative"]["sha256"],
                "review_required": record["review_required"],
                "accuracy_claim": record["accuracy_claim"],
            }
        elif args.command == "adopt-existing":
            record = adopt_existing_document(
                source_path=args.source,
                derivative_path=args.derivative,
                quality_path=args.quality,
                output_record_path=args.output_record,
                source_bundle_path=args.source_bundle,
                pdfinfo_path=args.pdfinfo,
                pdftotext_path=args.pdftotext,
                pdftoppm_path=args.pdftoppm,
                tesseract_path=args.tesseract,
                pdfunite_path=args.pdfunite,
                dpi=args.dpi,
                languages=args.languages,
                provenance_status=args.provenance_status,
                provenance_statement=args.provenance_statement,
                render_argv=parse_argv_json(args.render_argv_json, "render_argv_json"),
                ocr_argv=parse_argv_json(args.ocr_argv_json, "ocr_argv_json"),
                assemble_argv=parse_argv_json(
                    args.assemble_argv_json, "assemble_argv_json"
                ),
                generated_at=args.generated_at,
            )
            result = {
                "schema": record["schema"],
                "lineage_id": record["lineage_id"],
                "lineage_digest": record["lineage_digest"],
                "derivative_sha256": record["derivative"]["sha256"],
                "adoption_mode": record["adoption_mode"],
                "review_required": record["review_required"],
                "accuracy_claim": record["accuracy_claim"],
            }
        else:
            input_path = regular_file(args.input, "input")
            value = load_json(input_path)
            schema = value.get("schema") if isinstance(value, dict) else None
            if schema == QUALITY_SCHEMA:
                record = validate_quality_record(
                    value,
                    source_path=args.source,
                    source_bundle_path=args.source_bundle,
                    pdfinfo_path=args.pdfinfo,
                    pdftotext_path=args.pdftotext,
                )
                result = {
                    "valid": True,
                    "schema": QUALITY_SCHEMA,
                    "quality_digest": record["quality_digest"],
                    "classification": record["summary"]["classification"],
                }
            elif schema == NORMALIZATION_SCHEMA:
                if not args.derivative or not args.quality:
                    raise ContractError(
                        "normalization validation requires --derivative and --quality"
                    )
                record = validate_normalization_record(
                    value,
                    source_path=args.source,
                    derivative_path=args.derivative,
                    quality_path=args.quality,
                    source_bundle_path=args.source_bundle,
                    pdfinfo_path=args.pdfinfo,
                    pdftotext_path=args.pdftotext,
                )
                result = {
                    "valid": True,
                    "schema": NORMALIZATION_SCHEMA,
                    "lineage_digest": record["lineage_digest"],
                    "review_required": record["review_required"],
                    "accuracy_claim": record["accuracy_claim"],
                }
            else:
                raise ContractError(f"unsupported input schema: {schema!r}")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ContractError, OSError) as exc:
        print(
            json.dumps(failure(args.command, exc), ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
