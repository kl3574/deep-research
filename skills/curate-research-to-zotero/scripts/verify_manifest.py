#!/usr/bin/env python3
"""Lightweight verifier for curate-research-to-zotero manifests.

Usage:
  python verify_manifest.py MANIFEST.json \
    --root . \
    --source-registry source_registry.json \
    --pdf-manifest pdf_manifest.json \
    --references-bib references.bib \
    --require-pdf \
    --json

Exit codes:
  0 success
  1 validation error (schema or signature failure)
  2 IO/parse error
  3 alignment error (id mismatch with related files)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path


EXIT_SUCCESS = 0
EXIT_VALIDATION = 1
EXIT_IO = 2
EXIT_ALIGNMENT = 3


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def has_pdf_signature(path: Path) -> bool:
    with path.open("rb") as f:
        return b"%PDF-" in f.read(1024)


def collect_bib_ids(path: Path) -> set[str]:
    ids = set()
    if not path.exists():
        raise FileNotFoundError(f"references.bib not found: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        m = re.match(r"\s*@[^{}]+\{\s*([^,\s]+)\s*,", line)
        if m:
            ids.add(m.group(1))
    return ids


def load_id_set(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        candidates = []
        for row in rows:
            candidates.append(row)
        ids = set()
        for item in candidates:
            item_id = item.get("id") or item.get("source_id") or item.get("item_id")
            if item_id:
                ids.add(str(item_id))
        return ids
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict) and "entries" in payload:
        payload = payload["entries"]
    if not isinstance(payload, list):
        raise ValueError(f"unsupported structure in {path}")
    ids = set()
    for item in payload:
        item_id = None
        if isinstance(item, dict):
            item_id = item.get("id") or item.get("source_id") or item.get("item_id")
        if item_id:
            ids.add(str(item_id))
    return ids


def report_issues(errors: list[str], warnings: list[str], *, as_json: bool = False) -> int:
    status = EXIT_SUCCESS
    for msg in warnings:
        print(f"WARN: {msg}", file=sys.stderr)
    for msg in errors:
        print(f"ERROR: {msg}", file=sys.stderr)
        status = max(status, EXIT_VALIDATION)
    if as_json:
        print(
            json.dumps(
                {
                    "status": "ok" if status == EXIT_SUCCESS else "fail",
                    "exit_code": status,
                    "errors": errors,
                    "warnings": warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return status


def validate_manifest(
    data: object, root: Path, require_pdf: bool
) -> tuple[int, list[str], list[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    ids: set[str] = set()

    if not isinstance(data, dict):
        errors.append("manifest root must be an object")
        return EXIT_VALIDATION, errors, warnings, ids

    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("'entries' must be an array")
        return EXIT_VALIDATION, errors, warnings, ids
    if not entries:
        warnings.append("Manifest has zero entries")

    for idx, entry in enumerate(entries, start=1):
        prefix = f"entry[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: must be object")
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            errors.append(f"{prefix}: id must be non-empty string")
            continue
        entry_id = entry_id.strip()
        if entry_id in ids:
            errors.append(f"{prefix}: duplicate id '{entry_id}'")
        ids.add(entry_id)

        title = entry.get("title")
        year = entry.get("year")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{prefix}: title must be non-empty string")
        if not isinstance(year, int) or year < 1000 or year > 2500:
            errors.append(f"{prefix}: year must be int in [1000,2500]")

        source = entry.get("source")
        if not isinstance(source, dict):
            errors.append(f"{prefix}: source must be object with doi or canonical_url")
        else:
            doi = (source.get("doi") or "").strip() if isinstance(source.get("doi"), str) else ""
            canonical = (source.get("canonical_url") or "").strip() if isinstance(source.get("canonical_url"), str) else ""
            if not (doi or canonical or (isinstance(title, str) and title.strip() and isinstance(year, int))):
                errors.append(f"{prefix}: source must include doi, canonical_url, or (title + year)")

        pdf = entry.get("pdf")
        source_access = source.get("access_level") if isinstance(source, dict) else None
        if source_access is not None and source_access not in {
            "full_text",
            "partial_text",
            "abstract_only",
            "metadata_only",
        }:
            errors.append(f"{prefix}: source.access_level has unsupported value '{source_access}'")

        if require_pdf and (
            not isinstance(pdf, dict) or pdf.get("status") != "verified"
        ):
            errors.append(f"{prefix}: --require-pdf requires pdf.status='verified'")
            continue

        if isinstance(pdf, dict):
            pdf_status = pdf.get("status")
            raw_path = pdf.get("local_path")
            if pdf_status == "verified" and (
                not isinstance(raw_path, str) or not raw_path.strip()
            ):
                errors.append(f"{prefix}: verified pdf requires a non-empty local_path")
            if isinstance(raw_path, str) and raw_path.strip():
                pdf_path = (root / raw_path).expanduser().resolve()
                if not pdf_path.exists():
                    errors.append(f"{prefix}: pdf.local_path does not exist: {pdf_path}")
                elif not pdf_path.is_file():
                    errors.append(f"{prefix}: pdf.local_path is not file: {pdf_path}")
                elif not has_pdf_signature(pdf_path):
                    errors.append(f"{prefix}: no %PDF- signature in first 1024 bytes")
                else:
                    digest = sha256sum(pdf_path)
                    expected = pdf.get("expected_sha256")
                    declared = pdf.get("sha256")
                    if pdf_status == "verified" and not (
                        isinstance(declared, str)
                        and re.fullmatch(r"[0-9a-fA-F]{64}", declared)
                    ):
                        errors.append(f"{prefix}: verified pdf requires a 64-hex sha256")
                    elif isinstance(declared, str) and declared.lower() != digest.lower():
                        errors.append(f"{prefix}: pdf.sha256 mismatch: manifest={declared} actual={digest}")
                    if expected is not None:
                        if not isinstance(expected, str) or not re.fullmatch(
                            r"[0-9a-fA-F]{64}", expected
                        ):
                            errors.append(f"{prefix}: pdf.expected_sha256 must be 64-hex")
                        elif expected.lower() != digest.lower():
                            errors.append(
                                f"{prefix}: pdf.expected_sha256 mismatch: "
                                f"expected={expected} actual={digest}"
                            )
                    declared_size = pdf.get("size_bytes")
                    if pdf_status == "verified" and not isinstance(declared_size, int):
                        errors.append(f"{prefix}: verified pdf requires integer size_bytes")
                    elif isinstance(declared_size, int) and declared_size != pdf_path.stat().st_size:
                        errors.append(
                            f"{prefix}: pdf.size_bytes mismatch: "
                            f"manifest={declared_size} actual={pdf_path.stat().st_size}"
                        )
                    declared_mime = pdf.get("declared_mime") or pdf.get("mime")
                    if declared_mime and declared_mime not in {
                        "application/pdf",
                        "application/x-pdf",
                    }:
                        warnings.append(
                            f"{prefix}: declared MIME is '{declared_mime}', content signature is PDF"
                        )
            elif pdf_status == "verified":
                # The missing-path error above is sufficient.
                pass
            elif pdf_status:
                warnings.append(f"{prefix}: pdf status is '{pdf_status}', file not verified")
        else:
            if source_access == "metadata_only":
                warnings.append(f"{prefix}: metadata_only without pdf")
            elif "pdf" in entry:
                errors.append(f"{prefix}: pdf must be object when present")

        note = entry.get("note")
        if isinstance(note, dict):
            note_status = note.get("status")
            note_path_raw = note.get("local_path")
            if note_status == "verified" and (
                not isinstance(note_path_raw, str) or not note_path_raw.strip()
            ):
                errors.append(f"{prefix}: verified note requires a non-empty local_path")
            if isinstance(note_path_raw, str) and note_path_raw.strip():
                note_path = (root / note_path_raw).expanduser().resolve()
                if not note_path.is_file():
                    errors.append(f"{prefix}: note.local_path is not a file: {note_path}")
                else:
                    try:
                        note_text = note_path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        errors.append(f"{prefix}: note must be valid UTF-8")
                    else:
                        if note_status == "verified" and not note_text.strip():
                            errors.append(f"{prefix}: verified note must not be empty")
                    note_digest = sha256sum(note_path)
                    note_declared = note.get("sha256")
                    if note_status == "verified" and not (
                        isinstance(note_declared, str)
                        and re.fullmatch(r"[0-9a-fA-F]{64}", note_declared)
                    ):
                        errors.append(f"{prefix}: verified note requires a 64-hex sha256")
                    elif (
                        isinstance(note_declared, str)
                        and note_declared.lower() != note_digest.lower()
                    ):
                        errors.append(
                            f"{prefix}: note.sha256 mismatch: "
                            f"manifest={note_declared} actual={note_digest}"
                        )
        elif note is not None:
            errors.append(f"{prefix}: note must be object when present")

    return (EXIT_SUCCESS if not errors else EXIT_VALIDATION), errors, warnings, ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a curate-research-to-zotero provenance manifest.")
    parser.add_argument("manifest", type=Path, help="Path to manifest JSON file.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Base path for relative pdf paths.")
    parser.add_argument("--require-pdf", action="store_true", help="Require pdf object and file for every entry.")
    parser.add_argument("--source-registry", type=Path, default=None, help="Optional source_registry file to align ids.")
    parser.add_argument("--pdf-manifest", type=Path, default=None, help="Optional pdf_manifest file to align ids.")
    parser.add_argument("--references-bib", type=Path, default=None, help="Optional references.bib file to align entry ids.")
    parser.add_argument("--json", action="store_true", help="Output report in JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        with args.manifest.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        print(f"manifest file missing: {args.manifest}", file=sys.stderr)
        return EXIT_IO
    except json.JSONDecodeError as e:
        print(f"manifest JSON parse error: {e}", file=sys.stderr)
        return EXIT_IO
    except OSError as e:
        print(f"manifest read error: {e}", file=sys.stderr)
        return EXIT_IO

    root = args.root.expanduser().resolve()

    status, errors, warnings, manifest_ids = validate_manifest(payload, root, args.require_pdf)
    if status != EXIT_SUCCESS:
        return report_issues(errors, warnings, as_json=args.json)

    alignment_errors: list[str] = []
    alignment_code = EXIT_SUCCESS

    if args.source_registry:
        try:
            source_ids = load_id_set(args.source_registry)
        except Exception as e:
            print(f"source registry read error: {e}", file=sys.stderr)
            return EXIT_IO
        if not manifest_ids.issubset(source_ids):
            diff = sorted(manifest_ids - source_ids)
            alignment_errors.append(f"manifest ids missing in source registry: {diff}")

    if args.pdf_manifest:
        try:
            pdf_ids = load_id_set(args.pdf_manifest)
        except Exception as e:
            print(f"pdf manifest read error: {e}", file=sys.stderr)
            return EXIT_IO
        pdf_required_ids = {
            str(entry.get("id"))
            for entry in payload.get("entries", [])
            if isinstance(entry, dict)
            and isinstance(entry.get("pdf"), dict)
            and entry["pdf"].get("status") == "verified"
        }
        if not pdf_required_ids.issubset(pdf_ids):
            diff = sorted(pdf_required_ids - pdf_ids)
            alignment_errors.append(f"verified pdf ids missing in pdf manifest: {diff}")

    if args.references_bib:
        try:
            bib_ids = collect_bib_ids(args.references_bib)
        except Exception as e:
            print(f"references.bib read error: {e}", file=sys.stderr)
            return EXIT_IO
        bib_required_ids = {
            str(entry.get("id"))
            for entry in payload.get("entries", [])
            if isinstance(entry, dict)
            and isinstance(entry.get("ingestion"), dict)
            and entry["ingestion"].get("decision") in {"add", "metadata_only"}
        }
        if not bib_required_ids:
            bib_required_ids = set(manifest_ids)
        if not bib_required_ids.issubset(bib_ids):
            diff = sorted(bib_required_ids - bib_ids)
            alignment_errors.append(f"manifest ids missing in references.bib: {diff}")

    if alignment_errors:
        alignment_code = EXIT_ALIGNMENT
        for msg in alignment_errors:
            print(f"ALIGNMENT ERROR: {msg}", file=sys.stderr)
        if args.json:
            print(
                json.dumps(
                    {
                        "status": "alignment_error",
                        "exit_code": alignment_code,
                        "alignment_errors": alignment_errors,
                        "warning_count": len(warnings),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return alignment_code

    if args.json:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "exit_code": EXIT_SUCCESS,
                    "entries": len(payload.get("entries", [])) if isinstance(payload, dict) else 0,
                    "warnings": warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            "manifest ok: entries="
            f"{len(payload.get('entries', [])) if isinstance(payload, dict) else 0}"
        )
        for line in warnings:
            print(f"WARN: {line}")

    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
