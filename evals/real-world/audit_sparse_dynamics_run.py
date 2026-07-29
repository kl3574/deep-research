#!/usr/bin/env python3
"""Read-only audit script for sparse-dynamics deep-research artifacts.

The auditor validates:
- local corpus PDFs and bundle bindings
- readback manifest integrity and optional Zotero local read-only verification
- schema-9 notes (Chinese + LaTeX + integrity checks)
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXIT_SUCCESS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

DEFAULT_RUN_ROOT = Path("~/.local/share/deep-research/sparse-dynamics-2026-07-29").expanduser()
DEFAULT_EXPECTED_PDFS = 10
DEFAULT_EXPECTED_BUNDLE_ITEMS = 3
DEFAULT_EXPECTED_NOTES = 4
STANDALONE_NOTE_MANIFEST_FILENAME = "sindy_standalone_notes.json"
PDF_MAGIC = b"%PDF-"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
MD5_RE = re.compile(r"^[0-9a-f]{32}$", re.I)
READBACK_STATUS_VERIFIED = "verified"
READBACK_STATUS_PENDING_NOTE_UPDATE = "pending_note_update"
READBACK_STATUS_FAILED = "failed"
READBACK_STATUS_CONFLICT = "conflict"
READBACK_STATUS_UNKNOWN = "unknown"
READBACK_STATUS_ALLOWED: set[str] = {
    READBACK_STATUS_VERIFIED,
    READBACK_STATUS_PENDING_NOTE_UPDATE,
    READBACK_STATUS_FAILED,
    READBACK_STATUS_CONFLICT,
    READBACK_STATUS_UNKNOWN,
}


def _run_command(cmd: list[str], *, timeout: int = 20) -> tuple[int, str]:
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, (completed.stdout or "").strip()


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _script_sha256(script_path: Path) -> str:
    return _sha256(script_path)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _norm_path(value: Any) -> Path | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _norm_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _pick_text(value: Any, *fields: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for field_name in fields:
        candidate = _norm_text(value.get(field_name))
        if candidate is not None:
            return candidate
    return None


def _normalize_collection_path(value: Any) -> str | None:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                chunk = item.strip()
                if chunk:
                    parts.append(chunk)
            elif isinstance(item, dict):
                for field in ("name", "title", "path", "value"):
                    raw = item.get(field) if isinstance(item, dict) else None
                    if isinstance(raw, str):
                        chunk = raw.strip()
                        if chunk:
                            parts.append(chunk)
                            break
        return "/".join(parts) if parts else None

    if not isinstance(value, str):
        return None

    raw = value.replace("\\", "/").strip()
    if not raw:
        return None
    return "/".join(segment.strip() for segment in raw.split("/") if segment.strip())


def _normalize_collection_path_for_compare(value: Any) -> str | None:
    if isinstance(value, list):
        pieces: list[str] = []
        for item in value:
            if isinstance(item, str):
                piece = item.strip()
            elif isinstance(item, dict):
                piece = None
                for field in ("name", "title", "path", "value"):
                    raw = item.get(field) if isinstance(item, dict) else None
                    if isinstance(raw, str):
                        candidate = raw.strip()
                        if candidate:
                            piece = candidate
                            break
            else:
                piece = None
            if piece:
                pieces.append(piece)
        return "/".join(pieces) if pieces else None
    return _normalize_collection_path(value)


def _normalize_doi(value: Any) -> str | None:
    candidate = _norm_text(value)
    if candidate is None:
        return None
    return candidate.strip().lower()


def _normalize_target_scalar(value: Any) -> str | None:
    if isinstance(value, int):
        return str(value)
    candidate = _norm_text(value)
    if candidate is None:
        return None
    return candidate.strip().lower()


def _normalize_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _extract_year(value: Any) -> str | None:
    text = _norm_text(value)
    if text is None:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if match is None:
        return None
    return match.group(1)


def _extract_year_from_metadata(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    for candidate_field in (
        "year",
        "publication_year",
        "publicationYear",
        "year_published",
        "yearPublished",
        "date",
        "datePublished",
        "date_published",
        "publicationDate",
        "issued",
    ):
        value = record.get(candidate_field)
        extracted = _extract_year(value)
        if extracted is not None:
            return extracted
    source = record.get("source")
    if isinstance(source, dict):
        return _extract_year_from_metadata(source)
    return None

def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "1", "yes", "y"}:
            return True
        if value in {"false", "0", "no", "n"}:
            return False
    return None


def _extract_doi(raw: str) -> str | None:
    match = re.search(r"DOI或稳定标识\s*[:：]\s*([^\n\r<]+)", raw)
    if match is not None:
        value = match.group(1).strip()
        if value:
            doi = _extract_doi_from_value(value)
            if doi is not None:
                return doi

    normalized = html.unescape(raw)
    normalized = re.sub(r"<[^>]+>", " ", normalized)
    normalized = re.sub(r"[\r\n\t]+", " ", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    match = re.search(r"DOI或稳定标识\s*[:：]\s*([^\n\r]+)", normalized)
    if match is not None:
        value = match.group(1).strip()
        if value:
            doi = _extract_doi_from_value(value)
            if doi is not None:
                return doi

    return _extract_doi_from_value(normalized)


def _extract_doi_from_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if match := re.search(r"10\.[0-9A-Za-z][^\s<>\"]+", value):
        return match.group(0).strip().rstrip(".,;:)])}")
    return None


def _normalize_note_html(raw: str) -> str:
    decoded = html.unescape(raw)
    decoded = re.sub(r"[\r\n\t]+", " ", decoded)
    decoded = re.sub(r">\s+<", "><", decoded)
    decoded = re.sub(r"\s{2,}", " ", decoded).strip()
    return decoded


def _extract_tool_pages_and_encrypted(out: str) -> tuple[int | None, bool | None]:
    pages: int | None = None
    encrypted: bool | None = None
    for line in out.splitlines():
        lower = line.lower()
        if lower.startswith("pages:"):
            value = line.split(":", 1)[1].strip().split()[0]
            if value.isdigit():
                pages = int(value)
        if lower.startswith("encrypted:"):
            encrypted = lower.split(":", 1)[1].strip() in {
                "yes",
                "true",
                "y",
                "on",
            }
    return pages, encrypted


def _validate_pdf_tool_output(path: Path) -> tuple[int | None, bool | None, str | None]:
    if not _has_tool("pdfinfo"):
        return None, None, "pdfinfo unavailable"
    code, out = _run_command(["pdfinfo", str(path)])
    if code != 0:
        return None, None, f"pdfinfo failed (code={code})"

    tool_pages, tool_encrypted = _extract_tool_pages_and_encrypted(out)
    if tool_pages is None:
        return None, None, "pdfinfo output missing page count"

    if not _has_tool("pdftotext"):
        return tool_pages, tool_encrypted, "pdftotext unavailable"
    code, text = _run_command(["pdftotext", "-layout", str(path), "-"])
    if code != 0:
        return tool_pages, tool_encrypted, f"pdftotext failed (code={code})"
    if not text.strip():
        return tool_pages, tool_encrypted, "pdftotext output empty"

    return tool_pages, tool_encrypted, None


def _collect_collection_keys(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    keys: list[str] = []
    for item in value:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                keys.append(cleaned)
            continue
        if isinstance(item, dict):
            for field in ("key", "collection_key", "collectionKey"):
                candidate = item.get(field) if isinstance(item, dict) else None
                if isinstance(candidate, str):
                    cleaned = candidate.strip()
                    if cleaned:
                        keys.append(cleaned)
                        break
    return keys


def _extract_doi_from_item(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for field_name in (
        "DOI",
        "doi",
        "Doi",
        "doi_url",
        "DOIUrl",
        "stable_identifier",
        "canonical_url",
        "url",
    ):
        value = item.get(field_name)
        candidate = _extract_doi_from_value(value)
        if candidate is not None:
            return candidate
    return None


def _library_id(payload: dict[str, Any]) -> int | None:
    library = payload.get("library")
    if isinstance(library, dict):
        return _to_int(library.get("id")) or _to_int(library.get("libraryID"))
    return None


def _extract_zotero_item(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if "item" in payload and isinstance(payload["item"], dict):
        return payload["item"]
    if {"key", "data", "links"} <= set(payload.keys()):
        return payload
    return payload


def _api_fetch_item(base_url: str, group_id: int, item_key: str, *, timeout: int = 20) -> tuple[dict[str, Any], str | None]:
    encoded_key = urllib.parse.quote(item_key, safe="")
    url = f"{base_url.rstrip('/')}/api/groups/{group_id}/items/{encoded_key}"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            item = json.loads(raw)
            return _extract_zotero_item(item), None
    except urllib.error.HTTPError as exc:
        return {}, f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return {}, f"request failed: {exc.reason}"
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON from API: {exc}"


def _api_fetch_attachment_file_url(
    base_url: str, group_id: int, attachment_key: str, *, timeout: int = 20
) -> tuple[str | None, str | None]:
    encoded_key = urllib.parse.quote(attachment_key, safe="")
    url = f"{base_url.rstrip('/')}/api/groups/{group_id}/items/{encoded_key}/file/view/url"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "text/plain")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8").strip()
            if not raw:
                return None, "attachment file view url response is empty"
            return raw, None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return None, f"request failed: {exc.reason}"


def _resolve_file_url(file_url: str) -> Path | None:
    parsed = urllib.parse.urlparse(file_url)
    if parsed.scheme != "file":
        return None
    raw_path = parsed.path or ""
    if not raw_path:
        return None
    return Path(urllib.parse.unquote(raw_path)).resolve()


def _load_note_validator():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "curate-research-to-zotero"
        / "scripts"
        / "verify_note_html.py"
    )
    spec = importlib.util.spec_from_file_location("verify_note_html", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load verify_note_html.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collect_input_artifact_paths(
    args: argparse.Namespace,
    *,
    script_path: Path,
    corpus_manifest: Path,
    ingestion_manifest: Path,
    note_candidates: list[Path],
) -> set[Path]:
    paths: set[Path] = set()
    resolved_bundle_dir = (
        args.bundle_dir
        if args.bundle_dir is not None
        else Path(args.run_root).expanduser() / "bundles"
    )
    resolved_notes_dir = (
        args.notes_dir
        if args.notes_dir is not None
        else Path(args.run_root).expanduser() / "notes"
    )
    for candidate in (
        script_path,
        args.run_root,
        corpus_manifest,
        ingestion_manifest,
        resolved_bundle_dir,
        resolved_notes_dir,
    ):
        try:
            paths.add(candidate.resolve())
        except Exception:
            paths.add(candidate)
    if args.sindy_note is not None:
        try:
            paths.add(args.sindy_note.expanduser().resolve())
        except Exception:
            paths.add(args.sindy_note.expanduser())

    paths.add((args.run_root / STANDALONE_NOTE_MANIFEST_FILENAME).resolve())
    standalone_manifest_path = args.run_root / STANDALONE_NOTE_MANIFEST_FILENAME
    try:
        standalone_payload = _read_json(standalone_manifest_path)
    except (OSError, json.JSONDecodeError):
        standalone_payload = None
    if isinstance(standalone_payload, list):
        for record in standalone_payload:
            if not isinstance(record, dict):
                continue
            for field in (
                "note_path",
                "note_html_path",
                "html_path",
                "pdf_path",
                "path",
            ):
                candidate = _norm_path(record.get(field))
                if candidate is not None:
                    paths.add(candidate)

            for field in ("note",):
                candidate = _norm_path(record.get(field))
                if candidate is not None:
                    paths.add(candidate)

            for section in ("pdf", "note"):
                section_payload = record.get(section)
                if isinstance(section_payload, dict):
                    for field in (
                        "local_path",
                        "pdf_path",
                        "note_path",
                        "note_html_path",
                        "path",
                    ):
                        candidate = _norm_path(section_payload.get(field))
                        if candidate is not None:
                            paths.add(candidate)

    for path in note_candidates:
        try:
            paths.add(path.resolve())
        except Exception:
            paths.add(path)

    if resolved_bundle_dir.exists():
        for path in sorted(resolved_bundle_dir.glob("*.json")):
            try:
                paths.add(path.resolve())
            except Exception:
                paths.add(path)
            try:
                bundle_payload = _read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(bundle_payload, dict):
                continue
            for field in ("local_path", "pdf_path", "note_path", "note_html_path", "path"):
                for section in ("pdf", "note"):
                    section_payload = bundle_payload.get(section)
                    if isinstance(section_payload, dict):
                        candidate = section_payload.get(field)
                        resolved = _norm_path(candidate)
                        if resolved is not None:
                            paths.add(resolved)

    for manifest_path in (corpus_manifest, ingestion_manifest):
        if not manifest_path.exists():
            continue
        try:
            manifest_payload = _read_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(manifest_payload, list):
            for record in manifest_payload:
                if not isinstance(record, dict):
                    continue
                for field in ("note_path", "note_html_path", "html_path", "pdf_path", "path"):
                    candidate = _norm_path(record.get(field))
                    if candidate is not None:
                        paths.add(candidate)
                candidate = _norm_path(record.get("note"))
                if candidate is not None:
                    paths.add(candidate)
                for section in ("pdf", "note"):
                    section_payload = record.get(section)
                    if isinstance(section_payload, dict):
                        for field in (
                            "local_path",
                            "pdf_path",
                            "note_path",
                            "note_html_path",
                            "path",
                        ):
                            candidate = _norm_path(section_payload.get(field))
                            if candidate is not None:
                                paths.add(candidate)
            continue

        if not isinstance(manifest_payload, dict):
            continue
        for record in manifest_payload.get("files", []) or []:
            if isinstance(record, dict):
                for field in ("local_path", "pdf_path", "path"):
                    candidate = _norm_path(record.get(field))
                    if candidate is not None:
                        paths.add(candidate)
        for collection_name in ("entries", "items"):
            collection = manifest_payload.get(collection_name)
            if not isinstance(collection, list):
                continue
            for entry in collection:
                if not isinstance(entry, dict):
                    continue
                for section in ("pdf", "note"):
                    section_payload = entry.get(section)
                    if isinstance(section_payload, dict):
                        for field in ("local_path", "pdf_path", "note_path", "note_html_path", "path"):
                            candidate = _norm_path(section_payload.get(field))
                            if candidate is not None:
                                paths.add(candidate)
                for field in ("readback",):
                    readback = entry.get(field)
                    if isinstance(readback, dict):
                        for rb_field in ("stored_path",):
                            candidate = _norm_path(readback.get(rb_field))
                            if candidate is not None:
                                paths.add(candidate)
                for field in ("title", "path", "pdf_path"):
                    candidate = _norm_path(entry.get(field))
                    if candidate is not None:
                        paths.add(candidate)

    return paths


def _is_output_path_risky(output: Path, protected: set[Path]) -> bool:
    try:
        return output.resolve() in protected
    except Exception:
        return output in protected


def _git_commit(path: Path) -> str | None:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        )
        candidate = output.strip()
        if candidate:
            return candidate
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _safe_unwrapped(value: str) -> str:
    return value.strip().replace("\n", "").replace("\r", "")


def _pdf_lookup_key(local_path: Path, sha256: str) -> tuple[str, str]:
    return (str(local_path.resolve()), sha256.lower())


def _validated_pdf_lookup_from_corpus_result(
    item: dict[str, Any],
) -> dict[str, Any] | None:
    path = item.get("path")
    if not isinstance(path, str):
        return None
    sha = item.get("declared_sha256")
    pages = item.get("declared_pages")
    encrypted = item.get("declared_encrypted")
    pdftotext = item.get("declared_pdftotext")
    if (
        not isinstance(sha, str)
        or not SHA256_RE.fullmatch(sha)
        or not isinstance(pages, int)
        or pages <= 0
        or not isinstance(encrypted, bool)
    ):
        return None
    if not isinstance(pdftotext, dict):
        return None
    if not isinstance(pdftotext.get("readable"), bool):
        return None
    text_bytes = pdftotext.get("text_bytes")
    if not isinstance(text_bytes, int) or text_bytes <= 0:
        return None
    return {
        "pages": pages,
        "encrypted": encrypted,
        "pdftotext": pdftotext,
        "path": path,
        "sha256": sha.lower(),
    }


@dataclass
class Check:
    name: str
    status: str = "pass"
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.status = "fail"
        self.issues.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "issues": self.issues,
            "warnings": self.warnings,
            "payload": self.payload,
        }


def _entry_id(entry: dict[str, Any]) -> str:
    return (
        str(entry.get("id") or entry.get("source_id") or "").strip() or "<unknown>"
    )


def _find_bundle_by_source_id(bundle_dir: Path, source_id: str) -> tuple[Path | None, list[str]]:
    direct = bundle_dir / f"{source_id}.json"
    matches: list[Path] = []
    if direct.exists():
        matches.append(direct)
    for candidate in sorted(bundle_dir.glob("*.json")):
        try:
            if candidate == direct:
                continue
            payload = _read_json(candidate)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        candidate_id = str(payload.get("source_id") or payload.get("id") or "").strip()
        if candidate_id and candidate_id == source_id:
            matches.append(candidate)
    if len(matches) > 1:
        return (
            None,
            [
                f"bundle source_id ambiguous: {source_id} "
                f"matched {len(matches)} files"
            ],
        )
    if len(matches) == 1:
        return matches[0], []
    return None, []


def _normalize_entries(payload: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]], bool]:
    if not isinstance(payload, dict):
        return "invalid ingestion manifest payload", [], False

    if isinstance(payload.get("entries"), list):
        errors: list[str] = []
        seen_ids: set[str] = set()
        entries: list[dict[str, Any]] = []
        for index, entry in enumerate(payload["entries"], start=1):
            if not isinstance(entry, dict):
                errors.append(f"entries[{index}] is not an object")
                continue
            entry_id = _entry_id(entry)
            if entry_id == "<unknown>":
                errors.append(f"entries[{index}] missing id/source_id")
                continue
            if entry_id in seen_ids:
                errors.append(f"entries contains duplicate id: {entry_id}")
                continue
            seen_ids.add(entry_id)
            entries.append(entry)
        if errors:
            return "; ".join(errors), [], False
        return None, entries, False

    if isinstance(payload.get("items"), list):
        errors: list[str] = []
        seen_ids: set[str] = set()
        items: list[dict[str, Any]] = []
        for index, entry in enumerate(payload["items"], start=1):
            if not isinstance(entry, dict):
                errors.append(f"items[{index}] is not an object")
                continue
            item_id = _entry_id(entry)
            if item_id == "<unknown>":
                errors.append(f"items[{index}] missing source_id")
                continue
            if item_id in seen_ids:
                errors.append(f"items contains duplicate source_id: {item_id}")
                continue
            seen_ids.add(item_id)
            items.append(entry)
        if errors:
            return "; ".join(errors), [], True
        return None, items, True

    return "missing entries/items array", [], False


def _validate_pdf_file(
    idx: int,
    entry_id: str,
    payload: dict[str, Any],
    *,
    skip_pdf_tools: bool,
    limitations: list[str],
) -> dict[str, Any]:
    check = Check(name=f"pdf[{idx}]")
    result: dict[str, Any] = {
        "index": idx,
        "id": entry_id,
        "status": "pass",
        "issues": [],
        "warnings": [],
    }

    required = ("local_path", "size_bytes", "sha256", "pages", "encrypted", "pdftotext")
    for required_field in required:
        if required_field not in payload:
            check.fail(f"missing required pdf field: {required_field}")

    path = _norm_path(payload.get("local_path"))
    result["path"] = str(path) if path is not None else None
    if path is None:
        check.fail("pdf.local_path is missing or invalid")
    elif not path.exists():
        check.fail(f"pdf file not found: {path}")
    elif not path.is_file():
        check.fail(f"pdf path is not file: {path}")
    else:
        with path.open("rb") as stream:
            if not stream.read(len(PDF_MAGIC)).startswith(PDF_MAGIC):
                check.fail("pdf magic header check failed")

    declared_size = _to_int(payload.get("size_bytes"))
    if path is not None and path.exists() and declared_size is not None:
        observed_size = path.stat().st_size
        if observed_size != declared_size:
            check.fail(f"size mismatch: expected={declared_size} observed={observed_size}")
    elif declared_size is None:
        check.fail("invalid or missing pdf size_bytes")

    declared_sha = payload.get("sha256")
    if declared_sha is not None:
        if not isinstance(declared_sha, str) or not SHA256_RE.fullmatch(declared_sha):
            check.fail("invalid pdf sha256 format")
        elif path is not None and path.exists():
            observed_sha = _sha256(path)
            if observed_sha != declared_sha.lower():
                check.fail(f"sha mismatch: expected={declared_sha.lower()} observed={observed_sha}")
    else:
        check.fail("missing pdf sha256")

    declared_pages = _to_int(payload.get("pages"))
    if declared_pages is None:
        check.fail("missing or invalid pdf pages")
    elif declared_pages <= 0:
        check.fail(f"invalid pdf pages: {declared_pages}")

    encrypted = _to_bool(payload.get("encrypted"))
    if encrypted is None:
        check.fail("missing or invalid pdf encrypted flag")
    elif encrypted:
        check.fail("manifest marks pdf as encrypted")

    pdftotext = payload.get("pdftotext")
    if not isinstance(pdftotext, dict):
        check.fail("pdftotext block missing")
    else:
        if pdftotext.get("readable") is not True:
            check.fail("pdftotext.readable must be true")
        text_bytes = _to_int(pdftotext.get("text_bytes"))
        if text_bytes is None or text_bytes <= 0:
            check.fail("pdftotext.text_bytes must be positive")

    if skip_pdf_tools:
        if "skip_pdf_tools" not in limitations:
            limitations.append("pdf tool verification skipped via --skip-pdf-tools")
    else:
        tool_pages, tool_encrypted, tool_issue = _validate_pdf_tool_output(path) if path else (None, None, "pdf path unresolved")
        if tool_issue is not None:
            check.fail(f"pdf tool check failed: {tool_issue}")
        else:
            if tool_pages != declared_pages:
                check.fail(f"pdfinfo pages mismatch: tool={tool_pages} manifest={declared_pages}")
            if tool_encrypted:
                check.fail("pdfinfo reports pdf is encrypted")

    result["status"] = check.status
    result["issues"] = check.issues
    result["warnings"] = check.warnings
    result["declared_sha256"] = declared_sha.lower() if isinstance(declared_sha, str) else None
    result["declared_pages"] = declared_pages
    result["declared_encrypted"] = encrypted
    result["declared_pdftotext"] = pdftotext
    if path is not None and path.exists():
        result["observed_sha256"] = _sha256(path)
        result["observed_size"] = path.stat().st_size
    else:
        result["observed_sha256"] = None
        result["observed_size"] = None
    return result


def _validate_note_record(
    idx: int,
    entry_id: str,
    note_path: Path,
    validator: Any,
    *,
    expected_declared_hash: str | None,
    expected_pdf_sha256: str | None,
    strict_binding: bool = False,
) -> tuple[dict[str, Any], str | None]:
    result: dict[str, Any] = {
        "index": idx,
        "id": entry_id,
        "path": str(note_path),
        "status": "pass",
        "issues": [],
        "warnings": [],
    }

    if not note_path.exists():
        result["status"] = "fail"
        result["issues"].append("note file not found")
        return result, None
    if not note_path.is_file():
        result["status"] = "fail"
        result["issues"].append("note path is not file")
        return result, None

    raw = note_path.read_text(encoding="utf-8")
    if not raw.strip():
        result["status"] = "fail"
        result["issues"].append("note is empty")
        return result, None

    actual_sha = _sha256(note_path)
    declared = expected_declared_hash.lower() if isinstance(expected_declared_hash, str) else None
    if strict_binding:
        if declared is None:
            result["issues"].append("missing note sha256 declaration")
        elif not SHA256_RE.fullmatch(declared):
            result["issues"].append("note sha256 declaration malformed")
        elif declared != actual_sha:
            result["issues"].append(
                f"note sha mismatch: expected={declared} actual={actual_sha}"
            )

    errors, warnings, summary = validator.validate_note(raw)
    result["summary"] = summary
    result["warnings"].extend(warnings)
    if summary.get("schema_version") != "9":
        result["issues"].append("schema_version is not 9")
    if (summary.get("math_block_count") or 0) < 1:
        result["issues"].append("no LaTeX display math block found")

    if errors:
        result["issues"].extend(errors)

    full_text_sha = summary.get("full_text_sha256")
    if strict_binding:
        if expected_pdf_sha256 is None:
            result["issues"].append("missing expected PDF hash for note binding")
        elif full_text_sha is None:
            result["issues"].append("note missing full_text sha256 field")
        elif not SHA256_RE.fullmatch(str(full_text_sha)):
            result["issues"].append("note full_text sha256 malformed")
        elif str(full_text_sha).lower() != expected_pdf_sha256.lower():
            result["issues"].append(
                "note full_text sha256 mismatch: "
                f"expected={expected_pdf_sha256.lower()} observed={str(full_text_sha).lower()}"
            )

    if result["issues"]:
        result["status"] = "fail"

    return result, full_text_sha


def _validate_readback(
    entry_id: str,
    readback: dict[str, Any],
    target: dict[str, Any],
    expected_pdf_sha256: str | None,
    note_path: Path | None,
    validator: Any,
    zotero_base_url: str,
    expected_title: str | None = None,
    expected_doi: str | None = None,
    expected_year: str | None = None,
    readback_status: str | None = None,
) -> dict[str, Any]:
    check = Check(name=f"readback[{entry_id}]")
    result: dict[str, Any] = {
        "status": "pass",
        "issues": [],
        "warnings": [],
        "payload": {
            "manifest_status": readback_status,
            "group": None,
            "parent_key": None,
            "note_key": None,
            "attachment_key": None,
            "parent": {},
            "note": {},
            "attachment": {},
        },
    }

    if not readback:
        check.fail("readback section missing")
        result["status"] = check.status
        result["issues"] = check.issues
        return result

    required = (
        "zotero_item_key",
        "zotero_note_key",
        "zotero_attachment_key",
        "stored_path",
        "stored_sha256",
    )
    for required_field in required:
        if required_field not in readback:
            check.fail(f"readback missing required field: {required_field}")

    group_id = _to_int(target.get("group_id")) or _to_int(readback.get("group_id"))
    if group_id is None:
        check.fail("unable to determine expected group id for readback check")
    expected_collection = target.get("collection_key")
    if not isinstance(expected_collection, str) or not expected_collection.strip():
        check.fail("bundle.target.collection_key required for readback collection check")
    if note_path is None:
        check.fail("bundle note path missing for readback comparison")

    local_note = note_path.read_text(encoding="utf-8") if note_path and note_path.exists() else ""
    if not local_note:
        check.fail("note content missing for readback comparison")

    if check.status == "fail":
        result["status"] = "fail"
        result["issues"] = check.issues
        return result

    parent_key = str(readback.get("zotero_item_key")).strip()
    note_key = str(readback.get("zotero_note_key")).strip()
    attachment_key = str(readback.get("zotero_attachment_key")).strip()
    result["payload"]["parent_key"] = parent_key
    result["payload"]["note_key"] = note_key
    result["payload"]["attachment_key"] = attachment_key
    result["payload"]["group"] = group_id

    parent_item, err = _api_fetch_item(zotero_base_url, group_id, parent_key)
    if err is not None:
        check.fail(f"fetch parent failed: {err}")
    else:
        parent_library_id = _library_id(parent_item)
        if parent_library_id != group_id:
            check.fail(
                f"parent parentItem group mismatch: expected={group_id} observed={parent_library_id}"
            )

        parent_data = parent_item.get("data", {})
        expected_title_normalized = _normalize_title(expected_title)
        observed_parent_title = _normalize_title(parent_data.get("title"))
        if not isinstance(parent_data, dict):
            check.fail("parent item data missing")
        else:
            observed_parent_title = _normalize_title(parent_data.get("title"))
            if parent_data.get("itemType") in {"attachment", "note"}:
                check.fail("parent itemType must not be attachment/note")
            if parent_data.get("key") and parent_data["key"] != parent_key:
                check.fail("parent key mismatch in payload")
            if expected_title_normalized is not None:
                if observed_parent_title is None:
                    check.fail(
                        "parent title missing from readback API payload"
                    )
                elif observed_parent_title != expected_title_normalized:
                    check.fail(
                        "parent title mismatch: "
                        f"expected={expected_title_normalized} observed={observed_parent_title}"
                    )
            parent_collections = _collect_collection_keys(parent_data.get("collections"))
            if expected_collection and expected_collection not in parent_collections:
                check.fail(
                    "parent does not contain expected collection key "
                    f"{expected_collection}"
                )
            expected_doi_normalized = _normalize_doi(expected_doi)
            observed_doi = _extract_doi_from_item(parent_data)
            if expected_doi_normalized is not None:
                if observed_doi is None:
                    check.fail(
                        f"parent DOI missing from readback API payload: expected={expected_doi_normalized}"
                    )
                elif _normalize_doi(observed_doi) != expected_doi_normalized:
                    check.fail(
                        "parent DOI mismatch: "
                        f"expected={expected_doi_normalized} observed={_normalize_doi(observed_doi)}"
                    )
            expected_year_normalized = _normalize_target_scalar(expected_year)
            observed_year = _extract_year_from_metadata(parent_data)
            if expected_year_normalized is not None:
                if observed_year is None:
                    check.fail(
                        "parent publication year missing from readback API payload"
                    )
                elif observed_year != expected_year_normalized:
                    check.fail(
                        "parent publication year mismatch: "
                        f"expected={expected_year_normalized} observed={observed_year}"
                    )
        result["payload"]["parent"] = parent_item

    note_item, err = _api_fetch_item(zotero_base_url, group_id, note_key)
    if err is not None:
        check.fail(f"fetch note failed: {err}")
    else:
        note_data = note_item.get("data", {})
        if not isinstance(note_data, dict):
            check.fail("note item data missing")
        else:
            if note_data.get("itemType") != "note":
                check.fail("note itemType is not note")
            if note_data.get("parentItem") != parent_key:
                check.fail(
                    "note parentItem mismatch: "
                    f"expected={parent_key} observed={note_data.get('parentItem')}"
                )
            remote_note = str(note_data.get("note", ""))
            remote_errors, _, remote_summary = validator.validate_note(remote_note)
            if remote_summary.get("schema_version") != "9":
                check.fail("remote note schema_version is not 9")
            if remote_errors:
                check.fail(
                    "remote note validation failed: "
                    + ", ".join(_safe_unwrapped(err) for err in remote_errors)
                )
            if _normalize_note_html(remote_note) != _normalize_note_html(local_note):
                check.fail("remote note content is not normalized-equivalent to local note")
            remote_full_text_sha = remote_summary.get("full_text_sha256")
            if expected_pdf_sha256 is None:
                check.fail("expected pdf hash unavailable for remote note check")
            elif remote_full_text_sha is None:
                check.fail("remote note missing full_text sha256")
            elif str(remote_full_text_sha).lower() != expected_pdf_sha256.lower():
                check.fail(
                    "remote note full_text sha256 mismatch: "
                    f"expected={expected_pdf_sha256.lower()} observed={str(remote_full_text_sha).lower()}"
                )
        result["payload"]["note"] = note_item

    attachment_item, err = _api_fetch_item(zotero_base_url, group_id, attachment_key)
    if err is not None:
        check.fail(f"fetch attachment failed: {err}")
    else:
        attachment_data = attachment_item.get("data", {})
        if not isinstance(attachment_data, dict):
            check.fail("attachment item data missing")
        else:
            if attachment_data.get("itemType") not in {"attachment", "document"}:
                check.fail("attachment itemType is not attachment")
            if attachment_data.get("parentItem") != parent_key:
                check.fail(
                    "attachment parentItem mismatch: "
                    f"expected={parent_key} observed={attachment_data.get('parentItem')}"
                )
            attachment_file_url, file_url_err = _api_fetch_attachment_file_url(
                zotero_base_url, group_id, attachment_key
            )
            if file_url_err is not None:
                check.fail(f"fetch attachment file url failed: {file_url_err}")
            else:
                attached_file = _resolve_file_url(attachment_file_url)
                if attached_file is None:
                    check.fail(
                        f"invalid attachment file url (not file://): {attachment_file_url}"
                    )
                elif not attached_file.exists():
                    check.fail(f"attachment file url points to missing file: {attachment_file_url}")
                else:
                    expected_stored_path = readback.get("stored_path")
                    if not isinstance(expected_stored_path, str) or not expected_stored_path.strip():
                        check.fail("readback.stored_path missing or invalid")
                    else:
                        expected_path = Path(expected_stored_path).resolve()
                        if str(attached_file) != str(expected_path):
                            check.fail(
                                "attachment stored_path mismatch between API file/url and readback manifest"
                            )

                    observed_attachment_sha256 = _sha256(attached_file)
                    observed_attachment_md5 = _md5(attached_file)
                    if str(readback.get("stored_sha256") or "").strip().lower() != (
                        observed_attachment_sha256
                    ):
                        check.fail(
                            "attachment stored sha256 mismatch: "
                            f"expected={readback.get('stored_sha256')} observed={observed_attachment_sha256}"
                        )
                    if (
                        expected_pdf_sha256 is not None
                        and observed_attachment_sha256.lower() != expected_pdf_sha256.lower()
                    ):
                        check.fail(
                            "attachment hash does not match source pdf hash: "
                            f"expected={expected_pdf_sha256.lower()} observed={observed_attachment_sha256}"
                        )

                    attachment_md5 = attachment_data.get("md5")
                    if attachment_md5 is None:
                        check.fail("attachment md5 missing in API payload")
                    elif not MD5_RE.fullmatch(str(attachment_md5)):
                        check.fail("attachment md5 format invalid")
                    elif str(attachment_md5).lower() != observed_attachment_md5:
                        check.fail(
                            "attachment md5 mismatch with downloaded file: "
                            f"expected={observed_attachment_md5} observed={str(attachment_md5).lower()}"
                        )
        result["payload"]["attachment"] = attachment_item

    result["status"] = check.status
    result["issues"] = check.issues
    result["warnings"] = check.warnings
    return result


def _validate_bundle_records(
    entries: list[dict[str, Any]],
    bundle_dir: Path,
    *,
    expected_count: int,
    skip_pdf_tools: bool,
    expected_zotero_base_url: str | None,
    verified_corpus_lookup: dict[tuple[str, str], dict[str, Any]],
    limitations: list[str],
    validator: Any,
) -> tuple[dict[str, Any], list[str]]:
    check = Check(name="bundle_records")
    discovered_bundle_paths: set[Path] = set()
    if bundle_dir.exists():
        for bundle_file in sorted(bundle_dir.glob("*.json")):
            discovered_bundle_paths.add(bundle_file.resolve())
    payload: dict[str, Any] = {
        "expected_count": expected_count,
        "actual_count": len(entries),
        "items": [],
    }
    matched_bundle_paths: set[Path] = set()

    if not bundle_dir.exists():
        check.fail(f"bundle directory not found: {bundle_dir}")
        check.payload = payload
        payload["items"] = []
        return check.to_dict(), limitations

    for idx, entry in enumerate(entries, start=1):
        item_id = _entry_id(entry)
        item_result: dict[str, Any] = {
            "index": idx,
            "id": item_id,
            "status": "pass",
            "issues": [],
            "warnings": [],
            "pdf": None,
            "note": None,
            "readback": None,
            "bundle_path": None,
        }

        if item_id == "<unknown>":
            item_result["status"] = "fail"
            item_result["issues"].append("missing id/source_id")
            check.status = "fail"
            payload["items"].append(item_result)
            continue

        bundle_path, bundle_lookup_issues = _find_bundle_by_source_id(bundle_dir, item_id)
        if bundle_lookup_issues:
            item_result["status"] = "fail"
            item_result["issues"].extend(bundle_lookup_issues)
            check.status = "fail"
        if bundle_path is None:
            item_result["status"] = "fail"
            item_result["issues"].append("bundle file not found by source id")
            check.status = "fail"
            payload["items"].append(item_result)
            continue

        item_result["bundle_path"] = str(bundle_path)
        matched_bundle_paths.add(bundle_path.resolve())
        try:
            bundle_payload = _read_json(bundle_path)
        except (OSError, json.JSONDecodeError) as exc:
            item_result["status"] = "fail"
            item_result["issues"].append(f"bundle payload load failure: {exc}")
            check.status = "fail"
            payload["items"].append(item_result)
            continue
        if not isinstance(bundle_payload, dict):
            item_result["status"] = "fail"
            item_result["issues"].append("bundle payload is not object")
            check.status = "fail"
            payload["items"].append(item_result)
            continue

        bundle_source = str(bundle_payload.get("source_id") or bundle_payload.get("id") or "").strip()
        if bundle_source != item_id:
            item_result["issues"].append(
                f"bundle source_id mismatch: expected={item_id} payload={bundle_source}"
            )
            item_result["status"] = "fail"
            check.status = "fail"

        target = bundle_payload.get("target")
        if not isinstance(target, dict):
            item_result["issues"].append("bundle.target is missing")
            item_result["status"] = "fail"
            check.status = "fail"
            target = {}

        entry_target = entry.get("target")
        entry_target_source = "entry.target"
        if entry_target is None and isinstance(entry.get("ingestion"), dict):
            entry_target = entry["ingestion"].get("target")
            entry_target_source = "entry.ingestion.target"
        if isinstance(entry_target, dict):
            required_target_fields = (
                "library_name",
                "library_id",
                "group_id",
                "collection_key",
                "collection_path",
            )
            for required_field in required_target_fields:
                if required_field in ("library_id", "group_id"):
                    expected_raw = _normalize_target_scalar(target.get(required_field))
                    observed_raw = _normalize_target_scalar(entry_target.get(required_field))
                elif required_field == "collection_path":
                    expected_raw = _normalize_collection_path_for_compare(
                        target.get(required_field)
                    )
                    observed_raw = _normalize_collection_path_for_compare(
                        entry_target.get(required_field)
                    )
                else:
                    expected_raw = _norm_text(target.get(required_field))
                    observed_raw = _norm_text(entry_target.get(required_field))

                if expected_raw is None:
                    item_result["issues"].append(
                        f"bundle.target.{required_field} is required"
                    )
                    item_result["status"] = "fail"
                    check.status = "fail"
                if observed_raw is None:
                    item_result["issues"].append(
                        f"{entry_target_source}.{required_field} is required"
                    )
                    item_result["status"] = "fail"
                    check.status = "fail"
                if (
                    expected_raw is not None
                    and observed_raw is not None
                    and expected_raw != observed_raw
                ):
                    item_result["issues"].append(
                        f"target.{required_field} mismatch: expected={expected_raw} observed={observed_raw}"
                    )
                    item_result["status"] = "fail"
                    check.status = "fail"
        elif "target" in entry or "ingestion" in entry:
            item_result["issues"].append(
                "entry target is present but not object; expected object"
            )
            item_result["status"] = "fail"
            check.status = "fail"
        else:
            item_result["issues"].append("entry.target is required")
            item_result["status"] = "fail"
            check.status = "fail"

        item_data = bundle_payload.get("item")
        if isinstance(item_data, dict):
            if not isinstance(item_data.get("title"), str) or not item_data["title"].strip():
                item_result["issues"].append("bundle.item.title is missing")
                item_result["status"] = "fail"
                check.status = "fail"

            entry_title = _norm_text(entry.get("title"))
            if entry_title is None and isinstance(entry.get("source"), dict):
                entry_title = _norm_text(entry["source"].get("title"))
            bundle_title = _norm_text(item_data.get("title"))
            if entry_title is None:
                item_result["issues"].append("entry.title is required for binding check")
                item_result["status"] = "fail"
                check.status = "fail"
            if bundle_title is None:
                item_result["issues"].append("bundle.item.title is required")
                item_result["status"] = "fail"
                check.status = "fail"
            if (
                entry_title is not None
                and bundle_title is not None
                and entry_title != bundle_title
            ):
                item_result["issues"].append(
                    f"bundle and entry title mismatch: expected={bundle_title} observed={entry_title}"
                )
                item_result["status"] = "fail"
                check.status = "fail"

            entry_doi = _extract_doi_from_item(entry)
            if entry_doi is None and isinstance(entry.get("source"), dict):
                entry_doi = _extract_doi_from_item(entry["source"])
            bundle_source = item_data.get("source")
            bundle_doi = _normalize_doi(
                _extract_doi_from_item(bundle_source)
                if isinstance(bundle_source, dict)
                else _extract_doi_from_item(item_data)
            )
            if entry_doi is not None:
                entry_doi = _normalize_doi(entry_doi)
            if entry_doi is None:
                item_result["issues"].append("entry.doi is required")
                item_result["status"] = "fail"
                check.status = "fail"
            if bundle_doi is None:
                item_result["issues"].append("bundle.item.doi is required")
                item_result["status"] = "fail"
                check.status = "fail"
            if entry_doi is not None and bundle_doi is not None and entry_doi != bundle_doi:
                item_result["issues"].append(
                    f"bundle and entry DOI mismatch: expected={bundle_doi} observed={entry_doi}"
                )
                item_result["status"] = "fail"
                check.status = "fail"
        else:
            item_result["issues"].append("bundle.item is missing")
            item_result["status"] = "fail"
            check.status = "fail"

        entry_pdf = entry.get("pdf")
        bundle_pdf = bundle_payload.get("pdf")
        if not isinstance(entry_pdf, dict):
            item_result["issues"].append("entry.pdf is missing or not object")
            item_result["status"] = "fail"
            check.status = "fail"
            entry_pdf = {}
        if not isinstance(bundle_pdf, dict):
            item_result["issues"].append("bundle.pdf is missing or not object")
            item_result["status"] = "fail"
            check.status = "fail"
            bundle_pdf = {}

        entry_pdf_path = _pick_text(entry_pdf, "local_path", "pdf_path")
        bundle_pdf_path = _pick_text(bundle_pdf, "local_path", "pdf_path")
        entry_pdf_sha = _pick_text(entry_pdf, "sha256", "pdf_sha256")
        bundle_pdf_sha = _pick_text(bundle_pdf, "sha256", "pdf_sha256")
        for field_name, entry_value, bundle_value in (
            ("local_path", entry_pdf_path, bundle_pdf_path),
            ("sha256", entry_pdf_sha, bundle_pdf_sha),
        ):
            if entry_value is None:
                item_result["issues"].append(f"entry.pdf {field_name} missing")
                item_result["status"] = "fail"
                check.status = "fail"
            if bundle_value is None:
                item_result["issues"].append(f"bundle.pdf {field_name} missing")
                item_result["status"] = "fail"
                check.status = "fail"
            if (
                entry_value is not None
                and bundle_value is not None
                and entry_value != bundle_value
            ):
                item_result["issues"].append(f"bundle and entry pdf {field_name} mismatch")
                item_result["status"] = "fail"
                check.status = "fail"
        note_payload_entry = entry.get("note")
        note_payload_bundle = bundle_payload.get("note")
        if not isinstance(note_payload_entry, dict):
            item_result["issues"].append("entry.note is missing or not object")
            item_result["status"] = "fail"
            check.status = "fail"
            note_payload_entry = {}
        if not isinstance(note_payload_bundle, dict):
            item_result["issues"].append("bundle.note is missing or not object")
            item_result["status"] = "fail"
            check.status = "fail"
            note_payload_bundle = {}

        entry_note_path = _pick_text(
            note_payload_entry, "local_path", "note_path", "note_html_path", "html_path", "path"
        )
        bundle_note_path = _pick_text(
            note_payload_bundle, "local_path", "note_path", "note_html_path", "html_path", "path"
        )
        entry_note_sha = _pick_text(
            note_payload_entry, "sha256", "note_sha256", "hash", "note_hash"
        )
        bundle_note_sha = _pick_text(
            note_payload_bundle, "sha256", "note_sha256", "hash", "note_hash"
        )
        for field_name, entry_value, bundle_value in (
            ("local_path", entry_note_path, bundle_note_path),
            ("sha256", entry_note_sha, bundle_note_sha),
        ):
            if entry_value is None:
                item_result["issues"].append(f"entry.note {field_name} missing")
                item_result["status"] = "fail"
                check.status = "fail"
            if bundle_value is None:
                item_result["issues"].append(f"bundle.note {field_name} missing")
                item_result["status"] = "fail"
                check.status = "fail"
            if (
                entry_value is not None
                and bundle_value is not None
                and entry_value != bundle_value
            ):
                item_result["issues"].append(
                    f"bundle and entry note {field_name} mismatch"
                )
                item_result["status"] = "fail"
                check.status = "fail"
        note_payload: dict[str, Any] = {}
        if isinstance(note_payload_bundle, dict):
            note_payload.update(note_payload_bundle)
            if entry_note_path is not None:
                note_payload["local_path"] = entry_note_path
            if entry_note_sha is not None:
                note_payload["sha256"] = entry_note_sha
        if isinstance(note_payload_entry, dict):
            note_payload.update(note_payload_entry)
            if bundle_note_path is not None:
                note_payload["local_path"] = bundle_note_path
            if bundle_note_sha is not None:
                note_payload["sha256"] = bundle_note_sha

        pdf_payload: dict[str, Any] = {}
        if isinstance(bundle_pdf, dict):
            pdf_payload.update(bundle_pdf)
        if isinstance(entry_pdf, dict):
            pdf_payload.update(entry_pdf)
        if entry_pdf_path is not None:
            pdf_payload["local_path"] = entry_pdf_path
        if entry_pdf_sha is not None:
            pdf_payload["sha256"] = entry_pdf_sha

        pdf_path = _norm_path(pdf_payload.get("local_path"))
        if not pdf_path:
            item_result["issues"].append("bundle/pdf local_path missing")
            item_result["status"] = "fail"
            check.status = "fail"

        if (
            "pages" not in pdf_payload
            or "encrypted" not in pdf_payload
            or "pdftotext" not in pdf_payload
        ):
            if pdf_path is None:
                item_result["issues"].append(
                    "bundle/pdf missing required metadata and cannot match verified corpus "
                    "(local_path or sha256 missing)"
                )
            else:
                payload_sha = pdf_payload.get("sha256")
                if not isinstance(payload_sha, str):
                    item_result["issues"].append(
                        "bundle/pdf missing required metadata and cannot match verified corpus "
                        "(local_path or sha256 missing)"
                    )
                else:
                    lookup_key = _pdf_lookup_key(pdf_path, payload_sha)
                    corpus_pdf = verified_corpus_lookup.get(lookup_key)
                    if corpus_pdf is None:
                        item_result["issues"].append(
                            "bundle/pdf missing immutable metadata and no matching verified "
                            "corpus entry for strict augmentation (path+sha256 mismatch)"
                        )
                    else:
                        for field in ("pages", "encrypted", "pdftotext"):
                            if field not in pdf_payload:
                                pdf_payload[field] = corpus_pdf[field]
                        if "legacy_pdf_metadata_augmented_from_verified_corpus" not in limitations:
                            limitations.append(
                                "legacy_pdf_metadata_augmented_from_verified_corpus"
                            )

        pdf_result = _validate_pdf_file(
            idx,
            item_id,
            pdf_payload,
            skip_pdf_tools=skip_pdf_tools,
            limitations=limitations,
        )
        item_result["pdf"] = pdf_result
        if pdf_result["status"] != "pass":
            item_result["status"] = "fail"
            check.status = "fail"

        expected_pdf_sha = pdf_result.get("declared_sha256")
        note_path = _norm_path(note_payload.get("local_path"))
        note_result, _ = _validate_note_record(
            idx,
            item_id,
            note_path or Path(),
            validator,
            expected_declared_hash=note_payload.get("sha256"),
            expected_pdf_sha256=expected_pdf_sha,
            strict_binding=True,
        )
        item_result["note"] = note_result
        if note_result["status"] != "pass":
            item_result["status"] = "fail"
            check.status = "fail"

        if isinstance(note_payload.get("local_path"), str) and note_path is None:
            item_result["issues"].append("bundle/note local_path is invalid")
            item_result["status"] = "fail"
            check.status = "fail"

        expected_parent_title = _normalize_title(
            _pick_text(item_data if isinstance(item_data, dict) else {}, "title")
        )
        if expected_parent_title is None and isinstance(entry, dict):
            expected_parent_title = _normalize_title(entry.get("title"))
            if expected_parent_title is None and isinstance(entry.get("source"), dict):
                expected_parent_title = _normalize_title(entry["source"].get("title"))
        expected_parent_doi = (
            _extract_doi_from_item(item_data) if isinstance(item_data, dict) else None
        )
        if expected_parent_doi is None and isinstance(entry, dict):
            expected_parent_doi = _extract_doi_from_item(entry)
            if expected_parent_doi is None and isinstance(entry.get("source"), dict):
                expected_parent_doi = _extract_doi_from_item(entry["source"])
        expected_parent_year = (
            _extract_year_from_metadata(item_data)
            if isinstance(item_data, dict)
            else None
        )
        if expected_parent_year is None and isinstance(entry, dict):
            expected_parent_year = _extract_year_from_metadata(entry)

        readback = entry.get("readback")
        readback_status: str | None = None
        if not isinstance(readback, dict):
            item_result["issues"].append("entry.readback missing")
            item_result["status"] = "fail"
            check.status = "fail"
            item_result["readback"] = {
                "status": "fail",
                "issues": ["entry.readback missing"],
                "warnings": [],
                "payload": {"configured": False, "manifest_status": None},
            }
        else:
            if not readback:
                item_result["issues"].append("entry.readback is empty")
                item_result["status"] = "fail"
                check.status = "fail"
                item_result["readback"] = {
                    "status": "fail",
                    "issues": ["entry.readback is empty"],
                    "warnings": [],
                    "payload": {"configured": False, "manifest_status": None},
                }
            else:
                raw_status = readback.get("status")
                if not isinstance(raw_status, str) or not raw_status.strip():
                    item_result["issues"].append("readback.status missing or invalid")
                    item_result["status"] = "fail"
                    check.status = "fail"
                    item_result["readback"] = {
                        "status": "fail",
                        "issues": ["readback.status missing or invalid"],
                        "warnings": [],
                        "payload": {"configured": False, "manifest_status": readback_status},
                    }
                else:
                    readback_status = raw_status.strip().lower()
                    if readback_status not in READBACK_STATUS_ALLOWED:
                        item_result["issues"].append(
                            f"readback.status is invalid: {raw_status}"
                        )
                        item_result["status"] = "fail"
                        check.status = "fail"
                        item_result["readback"] = {
                            "status": "fail",
                            "issues": [f"readback.status is invalid: {raw_status}"],
                            "warnings": [],
                            "payload": {
                                "configured": expected_zotero_base_url is not None,
                                "manifest_status": readback_status,
                            },
                        }
                    elif readback_status != READBACK_STATUS_VERIFIED:
                        item_result["issues"].append(
                            f"readback.status must be {READBACK_STATUS_VERIFIED} for this audit, observed={readback_status}"
                        )
                        item_result["status"] = "fail"
                        check.status = "fail"
                        item_result["readback"] = {
                            "status": "fail",
                            "issues": [
                                f"readback.status must be {READBACK_STATUS_VERIFIED} for this audit, observed={readback_status}"
                            ],
                            "warnings": [],
                            "payload": {
                                "configured": expected_zotero_base_url is not None,
                                "manifest_status": readback_status,
                            },
                        }
                    else:
                        if expected_pdf_sha is None:
                            item_result["issues"].append(
                                "source pdf sha unavailable for readback binding"
                            )
                            item_result["status"] = "fail"
                            check.status = "fail"
                        else:
                            if isinstance(expected_pdf_sha, str) and not isinstance(
                                readback.get("stored_sha256"), str
                            ):
                                item_result["issues"].append(
                                    "readback.stored_sha256 missing"
                                )
                                item_result["status"] = "fail"
                                check.status = "fail"
                            elif isinstance(readback.get("stored_sha256"), str):
                                if (
                                    str(readback.get("stored_sha256")).lower()
                                    != expected_pdf_sha.lower()
                                ):
                                    item_result["issues"].append(
                                        "readback stored sha256 mismatch with source pdf hash"
                                    )
                                    item_result["status"] = "fail"
                                    check.status = "fail"

                        if item_result["status"] == "pass":
                            if expected_zotero_base_url is not None:
                                readback_result = _validate_readback(
                                    item_id,
                                    readback,
                                    target,
                                    expected_pdf_sha,
                                    note_path,
                                    validator,
                                    expected_zotero_base_url,
                                    expected_title=expected_parent_title,
                                    expected_doi=expected_parent_doi,
                                    expected_year=expected_parent_year,
                                    readback_status=readback_status,
                                )
                                item_result["readback"] = readback_result
                                if readback_result["status"] != "pass":
                                    item_result["status"] = "fail"
                                    check.status = "fail"
                            else:
                                if "readback verified without live API" not in limitations:
                                    limitations.append(
                                        "readback verified without live API; verification is historical only"
                                    )
                                item_result["readback"] = {
                                    "status": "not_run",
                                    "issues": [],
                                    "warnings": [
                                        "enable --zotero-base-url to perform API readback verification"
                                    ],
                                    "payload": {
                                        "configured": False,
                                        "manifest_status": readback_status,
                                    },
                                }

        if item_result["status"] == "fail":
            check.status = "fail"
            if pdf_result.get("issues"):
                item_result["issues"].extend(pdf_result["issues"])
            if note_result.get("issues"):
                item_result["issues"].extend(note_result["issues"])

        if item_result["readback"] is None:
            item_result["readback"] = {
                "status": "fail",
                "issues": ["readback not evaluated due earlier validation failures"],
                "warnings": [],
                "payload": {
                    "configured": expected_zotero_base_url is not None,
                    "manifest_status": readback_status,
                },
            }
        payload["items"].append(item_result)

    orphan_bundle_paths = sorted(
        discovered_bundle_paths.difference(matched_bundle_paths),
        key=lambda path: str(path),
    )
    if orphan_bundle_paths:
        check.fail(
            "orphan bundle files detected: "
            + ", ".join(path.name for path in orphan_bundle_paths)
        )

    if len(entries) != expected_count:
        check.fail(f"bundle count mismatch: expected {expected_count}, actual {len(entries)}")

    check.payload = payload
    return check.to_dict(), limitations


def _validate_corpus_files(
    manifest_path: Path,
    *,
    expected_count: int,
    skip_pdf_tools: bool,
    limitations: list[str],
) -> tuple[dict[str, Any], list[str], dict[tuple[str, str], dict[str, Any]]]:
    check = Check(name="corpus_files")
    payload: dict[str, Any] = {
        "manifest": str(manifest_path),
        "expected_count": expected_count,
        "items": [],
    }
    verified_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    sha_entries: dict[str, list[tuple[int, str, str | None]]] = {}

    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        check.fail(f"manifest read failure: {exc}")
        check.payload = payload
        return check.to_dict(), limitations, {}

    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        check.fail("manifest.files is missing or not a list")
        check.payload = payload
        return check.to_dict(), limitations, {}

    if len(files) != expected_count:
        check.fail(f"corpus file count mismatch: expected {expected_count}, actual {len(files)}")

    for idx, entry in enumerate(files, start=1):
        if not isinstance(entry, dict):
            item = {
                "index": idx,
                "status": "fail",
                "issues": ["corpus file entry is not object"],
            }
            payload["items"].append(item)
            check.status = "fail"
            continue
        entry_id = _entry_id(entry)
        normalized_entry_id = (
            entry_id if entry_id != "<unknown>" else f"index:{idx}"
        )
        resolved_path = _norm_path(entry.get("local_path"))
        resolved_path_key = str(resolved_path) if resolved_path is not None else None

        file_result = _validate_pdf_file(
            idx,
            str(_entry_id(entry) or idx),
            entry,
            skip_pdf_tools=skip_pdf_tools,
            limitations=limitations,
        )
        if entry_id != "<unknown>":
            if normalized_entry_id in seen_ids:
                file_result["issues"].append(f"duplicate corpus file id: {entry_id}")
                file_result["status"] = "fail"
            else:
                seen_ids.add(normalized_entry_id)
        if resolved_path_key is not None:
            if resolved_path_key in seen_paths:
                file_result["issues"].append(
                    f"duplicate corpus local_path for distinct file entry: {resolved_path_key}"
                )
                file_result["status"] = "fail"
            else:
                seen_paths.add(resolved_path_key)

        declared_sha = _norm_text(file_result.get("declared_sha256"))
        if declared_sha is not None:
            declared_sha = declared_sha.lower()
            for prior_index, prior_entry_id, prior_path in sha_entries.get(declared_sha, []):
                if prior_entry_id != normalized_entry_id or prior_path != resolved_path_key:
                    conflict_issue = (
                        f"duplicate sha256 across distinct corpus records: sha256={declared_sha} "
                        f"entries='{prior_entry_id}' and '{normalized_entry_id}'"
                    )
                    file_result["issues"].append(conflict_issue)
                    file_result["status"] = "fail"
                    prior_item = payload["items"][prior_index - 1]
                    if conflict_issue not in prior_item.get("issues", []):
                        prior_item["issues"].append(conflict_issue)
                    prior_item["status"] = "fail"
                    check.status = "fail"
            sha_entries.setdefault(declared_sha, []).append(
                (idx, normalized_entry_id, resolved_path_key)
            )
        payload["items"].append(file_result)
        if file_result["status"] != "pass":
            check.status = "fail"
        elif not skip_pdf_tools:
            verified = _validated_pdf_lookup_from_corpus_result(file_result)
            if verified is not None:
                verified_lookup[_pdf_lookup_key(Path(file_result["path"]), file_result["declared_sha256"])] = verified

    payload["pass_count"] = sum(
        1 for item in payload["items"] if item.get("status") == "pass"
    )
    check.payload = payload
    return check.to_dict(), limitations, verified_lookup


def _validate_notes(
    notes: list[Path],
    expected_count: int,
    validator: Any,
    *,
    standalone_expectations: list[dict[str, Any]] | None = None,
    standalone_manifest_issues: list[str] | None = None,
    limitations: list[str] | None = None,
    skip_pdf_tools: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    check = Check(name="notes")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in notes:
        resolved = path.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(resolved)

    standalone: dict[str, dict[str, Any]] = {}
    if standalone_expectations is None:
        standalone_expectations = []
    if limitations is None:
        limitations = []
    for item in standalone_expectations:
        note_path = _norm_path(
            item.get("note_path")
            or item.get("note_html_path")
            or item.get("html_path")
            or item.get("path")
            or item.get("note")
        )
        if note_path is not None:
            standalone[note_path.resolve().as_posix()] = item

    matched_standalone: set[str] = set()

    for idx, path in enumerate(deduped, start=1):
        if not path.exists():
            item = {
                "index": idx,
                "path": str(path),
                "status": "fail",
                "issues": ["note file not found"],
                "warnings": [],
            }
            items.append(item)
            check.status = "fail"
            continue

        spec = standalone.get(path.as_posix())
        if spec is not None:
            matched_standalone.add(path.as_posix())
            item, _ = _validate_standalone_note(
                idx,
                path,
                validator,
                spec,
                limitations=limitations,
                skip_pdf_tools=skip_pdf_tools,
            )
            item["index"] = idx
            item["path"] = str(path)
            items.append(item)
            if item["status"] != "pass":
                check.status = "fail"
            continue

        if not path.exists():
            item = {
                "index": idx,
                "path": str(path),
                "status": "fail",
                "issues": ["note file not found"],
                "warnings": [],
            }
            items.append(item)
            check.status = "fail"
            continue
        note_result, _ = _validate_note_record(
            idx,
            path.stem,
            path,
            validator,
            expected_declared_hash=None,
            expected_pdf_sha256=None,
        )
        note_result["path"] = str(path)
        note_result["index"] = idx
        items.append(note_result)
        if note_result["status"] != "pass":
            check.status = "fail"

    for spec in standalone_expectations:
        note_path = _norm_path(
            spec.get("note_path")
            or spec.get("note_html_path")
            or spec.get("html_path")
            or spec.get("path")
            or spec.get("note")
        )
        if note_path is None or note_path.resolve().as_posix() not in {
            path.as_posix() for path in deduped
        }:
            check.fail(f"standalone note path missing from candidates: {spec.get('note_path')}")
        elif note_path.resolve().as_posix() not in matched_standalone:
            check.fail(f"standalone note binding not validated: {spec.get('note_path')}")

    for issue in standalone_manifest_issues or []:
        check.fail(issue)

    check.payload = {
        "expected_count": expected_count,
        "actual_count": len(deduped),
        "items": items,
    }
    if len(deduped) != expected_count:
        check.fail(f"note count mismatch: expected {expected_count}, actual {len(deduped)}")
    check.payload["pass_count"] = sum(1 for item in items if item.get("status") == "pass")
    return check.to_dict(), limitations


def _validate_standalone_note(
    idx: int,
    path: Path,
    validator: Any,
    spec: dict[str, Any],
    *,
    limitations: list[str],
    skip_pdf_tools: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    result: dict[str, Any] = {
        "index": idx,
        "path": str(path),
        "status": "pass",
        "issues": [],
        "warnings": [],
    }
    if not path.exists():
        result["status"] = "fail"
        result["issues"].append("standalone note path not found")
        return result, result["issues"]

    note_sha = _norm_text(spec.get("note_sha256"))
    if note_sha is not None:
        note_sha = note_sha.lower()
    expected_pdf_path = _norm_path(spec.get("pdf_path"))
    expected_pdf_sha = _norm_text(spec.get("pdf_sha256"))
    if expected_pdf_sha is not None:
        expected_pdf_sha = expected_pdf_sha.lower()
    expected_pdf_pages = _to_int(spec.get("pdf_pages"))
    expected_title = _norm_text(spec.get("title"))
    expected_doi = (
        _norm_text(spec.get("doi"))
        or _norm_text(spec.get("DOI"))
        or _norm_text(spec.get("doi_url"))
    )
    expected_full_text_sha = _norm_text(spec.get("note_full_text_sha256"))
    expected_id = _norm_text(spec.get("id")) or path.stem
    result["expected_identity"] = {
        "id": expected_id,
        "title": expected_title,
        "doi": _normalize_doi(expected_doi),
        "note_sha256": note_sha,
        "note_full_text_sha256": (
            expected_full_text_sha.lower()
            if isinstance(expected_full_text_sha, str)
            else None
        ),
        "pdf_path": str(expected_pdf_path) if expected_pdf_path is not None else None,
        "pdf_sha256": expected_pdf_sha,
        "pdf_pages": expected_pdf_pages,
    }

    if note_sha is None:
        result["issues"].append("standalone note manifest missing note_sha256")
        result["status"] = "fail"
    if expected_pdf_path is None:
        result["issues"].append("standalone note manifest missing pdf_path")
        result["status"] = "fail"
    if expected_pdf_sha is None or not SHA256_RE.fullmatch(expected_pdf_sha):
        result["issues"].append("standalone note manifest missing valid pdf_sha256")
        result["status"] = "fail"
    if expected_pdf_pages is None or expected_pdf_pages <= 0:
        result["issues"].append("standalone note manifest missing valid pdf_pages")
        result["status"] = "fail"
    if expected_title is None:
        result["issues"].append("standalone note manifest missing title")
        result["status"] = "fail"
    if expected_doi is None:
        result["issues"].append("standalone note manifest missing doi")
        result["status"] = "fail"
    if expected_full_text_sha is None or not SHA256_RE.fullmatch(expected_full_text_sha):
        result["issues"].append("standalone note manifest missing valid note_full_text_sha256")
        result["status"] = "fail"

    note_text = path.read_text(encoding="utf-8")
    note_result, full_text_sha = _validate_note_record(
        idx,
        expected_id,
        path,
        validator,
        expected_declared_hash=note_sha,
        expected_pdf_sha256=expected_pdf_sha,
        strict_binding=True,
    )
    result.update(note_result)
    if note_result["status"] == "fail":
        result["status"] = "fail"
    if expected_title is not None and note_result.get("summary", {}).get("title") != expected_title:
        result["issues"].append(
            f"standalone note title mismatch: expected={expected_title} observed={note_result.get('summary', {}).get('title')}"
        )
        result["status"] = "fail"
    observed_doi = _extract_doi(note_text)
    if expected_doi is not None and observed_doi != expected_doi:
        result["issues"].append(
            f"standalone note doi mismatch: expected={expected_doi} observed={observed_doi}"
        )
        result["status"] = "fail"
    if (
        expected_full_text_sha is not None
        and isinstance(full_text_sha, str)
        and full_text_sha.lower() != expected_full_text_sha.lower()
    ):
        result["issues"].append(
            "standalone note full_text_sha256 mismatch: "
            f"expected={expected_full_text_sha.lower()} observed={full_text_sha.lower()}"
        )
        result["status"] = "fail"

    if expected_pdf_path is not None and expected_pdf_sha is not None:
        if not expected_pdf_path.exists():
            result["issues"].append(f"standalone note referenced pdf does not exist: {expected_pdf_path}")
            result["status"] = "fail"
        else:
            observed_size = expected_pdf_path.stat().st_size
            observed_sha = _sha256(expected_pdf_path)
            issues: list[str] = []
            with expected_pdf_path.open("rb") as stream:
                if not stream.read(len(PDF_MAGIC)).startswith(PDF_MAGIC):
                    issues.append("standalone note referenced file is not a PDF")
            declared_path = _norm_path(str(expected_pdf_path))
            if declared_path is None or not declared_path.exists():
                issues.append(f"standalone note referenced pdf path invalid: {expected_pdf_path}")
            if observed_size <= 0:
                issues.append("standalone note referenced pdf size must be > 0")
            if observed_sha.lower() != expected_pdf_sha.lower():
                issues.append(
                    "standalone note referenced pdf sha256 mismatch: "
                    f"expected={expected_pdf_sha.lower()} observed={observed_sha}"
                )
            tool_pages: int | None = None
            tool_encrypted: bool | None = None
            if skip_pdf_tools:
                if "standalone note pdf tool checks skipped via --skip-pdf-tools" not in limitations:
                    limitations.append(
                        "standalone note pdf tool checks skipped via --skip-pdf-tools"
                    )
            else:
                tool_pages, tool_encrypted, tool_issue = _validate_pdf_tool_output(
                    expected_pdf_path
                )
                if tool_issue is not None:
                    issues.append(
                        f"standalone note referenced pdf tool check failed: {tool_issue}"
                    )
                elif not isinstance(expected_pdf_pages, int):
                    issues.append("standalone note manifest missing valid pdf_pages")
                elif tool_pages != expected_pdf_pages:
                    issues.append(
                        "standalone note referenced pdf page mismatch: "
                        f"expected={expected_pdf_pages} observed={tool_pages}"
                    )
                if tool_encrypted:
                    issues.append("standalone note referenced pdf is encrypted")

            pdf_result = {
                "index": idx,
                "id": expected_id,
                "path": str(expected_pdf_path),
                "status": "pass" if not issues else "fail",
                "issues": issues,
                "warnings": [],
                "declared_sha256": expected_pdf_sha.lower(),
                "declared_pages": expected_pdf_pages,
                "declared_encrypted": tool_encrypted,
                "declared_pdftotext": None,
                "observed_sha256": observed_sha,
                "observed_size": observed_size,
            }
            if pdf_result["status"] != "pass":
                result["issues"].extend(pdf_result["issues"])
                result["status"] = "fail"
            result["pdf"] = pdf_result

    result["warnings"] = result.get("warnings", [])
    return result, result["issues"]


def _collect_note_candidates(notes_dir: Path, extra: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if notes_dir.exists():
        for path in sorted(notes_dir.glob("*.html")):
            candidates.append(path.resolve())
    if extra is not None:
        candidates.append(extra.resolve())
    return candidates


def _load_standalone_notes_manifest(run_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    manifest_path = run_root / STANDALONE_NOTE_MANIFEST_FILENAME
    if not manifest_path.exists():
        return [], [f"standalone note manifest missing: {manifest_path}"]
    try:
        payload = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"standalone note manifest parse error: {exc}"]
    if not isinstance(payload, list):
        return [], ["standalone note manifest must be a list"]
    if not payload:
        return [], ["standalone note manifest is empty"]
    seen_paths: set[str] = set()
    records: list[dict[str, Any]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            return (
                [],
                [f"standalone note manifest entry[{index}] is not an object"],
            )
        note_path = _norm_path(
            item.get("note_path")
            or item.get("note_html_path")
            or item.get("html_path")
            or item.get("path")
            or item.get("note")
        )
        if note_path is None:
            return [], [f"standalone note manifest entry[{index}] missing note_path"]
        normalized = note_path.resolve().as_posix()
        if normalized in seen_paths:
            return [], [f"duplicate standalone note path: {normalized}"]
        seen_paths.add(normalized)
        records.append(item)
    return records, []


def _resolve_sindy_note_path(
    explicit_note: Path | None = None
) -> Path | None:
    if explicit_note is not None:
        return explicit_note.expanduser()

    env_path = os.environ.get("DEEP_RESEARCH_SINDY_NOTE_PATH")
    if env_path is not None:
        explicit_path = _norm_path(env_path)
        if explicit_path is not None and explicit_path.exists():
            return explicit_path

    fallback = (
        Path("~/.local/share/deep-research").expanduser()
        / "zotero-private-staging"
        / "overrides"
        / "TEST0001.html"
    )
    if fallback.exists():
        return fallback

    migration_candidates = sorted(
        Path("~/.local/share/deep-research").expanduser().glob("zotero-note-migration-*")
    )
    for candidate in migration_candidates:
        maybe = candidate / "overrides" / "TEST0001.html"
        if maybe.exists():
            return maybe
    return None


def _collect_input_output_guard_paths(
    args: argparse.Namespace,
    run_root: Path,
    corpus_manifest: Path,
    ingestion_manifest: Path,
) -> set[Path]:
    notes_dir = args.notes_dir if args.notes_dir is not None else run_root / "notes"
    explicit_sindy_note = _resolve_sindy_note_path(args.sindy_note)
    if explicit_sindy_note is not None:
        explicit_sindy_note = explicit_sindy_note.expanduser().resolve()
    note_candidates = _collect_note_candidates(notes_dir, explicit_sindy_note)
    return _collect_input_artifact_paths(
        args=args,
        script_path=Path(__file__).resolve(),
        corpus_manifest=corpus_manifest,
        ingestion_manifest=ingestion_manifest,
        note_candidates=note_candidates,
    )


def _ensure_output_not_input(
    args: argparse.Namespace,
    run_root: Path,
    output: Path,
    corpus_manifest: Path,
    ingestion_manifest: Path,
) -> None:
    safe_output = output.expanduser().resolve()
    protected = _collect_input_output_guard_paths(
        args=args,
        run_root=run_root,
        corpus_manifest=corpus_manifest,
        ingestion_manifest=ingestion_manifest,
    )
    if _is_output_path_risky(safe_output, protected):
        raise RuntimeError(
            "refuse to write audit report to input artifact path: "
            f"{safe_output}"
        )


def run_audit(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    script_path = Path(__file__).resolve()
    run_root = args.run_root.expanduser().resolve()
    generated_at = (
        args.generated_at
        if args.generated_at is not None
        else datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )

    limitations: list[str] = []
    report: dict[str, Any] = {
        "status": "pass",
        "generated_at": generated_at,
        "metadata": {},
        "limitations": [],
        "inputs": {},
        "checks": {},
        "summary": {},
    }

    if args.generated_at is None:
        report["metadata"]["generated_at_mode"] = "runtime"
    else:
        report["metadata"]["generated_at_mode"] = "fixed"

    repo_root = script_path.parent.parent.parent
    report["metadata"]["repo"] = {
        "root": str(repo_root),
        "commit": _git_commit(repo_root),
    }
    report["metadata"]["python"] = {
        "version": sys.version.split(" ", maxsplit=1)[0],
    }
    report["metadata"]["script"] = {
        "path": str(script_path),
        "sha256": _script_sha256(script_path),
    }

    if args.corpus_manifest is None:
        corpus_manifest = run_root / "manifest.json"
    else:
        corpus_manifest = args.corpus_manifest.expanduser().resolve()
    if args.ingestion_manifest is None:
        ingestion_manifest = run_root / "ingestion_manifest.json"
    else:
        ingestion_manifest = args.ingestion_manifest.expanduser().resolve()

    legacy_path = run_root / "ingestion_manifest.legacy.json"
    if not ingestion_manifest.exists() and legacy_path.exists():
        ingestion_manifest = legacy_path
        limitations.append("ingestion manifest auto-fallback to ingestion_manifest.legacy.json")

    if args.bundle_dir is None:
        bundle_dir = run_root / "bundles"
    else:
        bundle_dir = args.bundle_dir.expanduser().resolve()

    if args.notes_dir is None:
        notes_dir = run_root / "notes"
    else:
        notes_dir = args.notes_dir.expanduser().resolve()

    explicit_note = args.sindy_note
    if explicit_note is None:
        explicit_note = _resolve_sindy_note_path(explicit_note)
    if explicit_note is not None:
        explicit_note = explicit_note.resolve()
    standalone_manifest = run_root / STANDALONE_NOTE_MANIFEST_FILENAME

    report["inputs"] = {
        "run_root": str(run_root),
        "corpus_manifest": {
            "path": str(corpus_manifest),
            "sha256": _sha256(corpus_manifest) if corpus_manifest.exists() else None,
        },
        "ingestion_manifest": {
            "path": str(ingestion_manifest),
            "sha256": _sha256(ingestion_manifest) if ingestion_manifest.exists() else None,
        },
        "standalone_manifest": {
            "path": str(standalone_manifest),
            "sha256": (
                _sha256(standalone_manifest)
                if standalone_manifest.exists()
                else None
            ),
        },
        "bundle_dir": str(bundle_dir),
        "notes_dir": str(notes_dir),
        "sindy_note": str(explicit_note) if explicit_note is not None else None,
        "zotero_base_url": args.zotero_base_url,
    }

    note_candidates = _collect_note_candidates(
        notes_dir,
        explicit_note if isinstance(explicit_note, Path) else None,
    )
    report["inputs"]["note_hashes"] = [
        {"path": str(path), "sha256": _sha256(path) if path.exists() else None}
        for path in sorted(set(note_candidates))
    ]
    standalone_note_records, manifest_issues = _load_standalone_notes_manifest(run_root)
    if manifest_issues:
        report["status"] = "fail"
        limitations.append("standalone note manifest invalid")
        standalone_note_records = []

    validator = _load_note_validator()

    if not corpus_manifest.exists():
        report["status"] = "fail"
        report["checks"]["corpus_files"] = {
            "name": "corpus_files",
            "status": "fail",
            "issues": [f"corpus manifest not found: {corpus_manifest}"],
            "warnings": [],
            "payload": {"path": str(corpus_manifest)},
        }
        corpus_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    else:
        corpus_check, limitations, corpus_lookup = _validate_corpus_files(
            corpus_manifest,
            expected_count=args.expected_pdfs,
            skip_pdf_tools=args.skip_pdf_tools,
            limitations=limitations,
        )
        report["checks"]["corpus_files"] = corpus_check
        if corpus_check["status"] == "fail":
            report["status"] = "fail"

    if not ingestion_manifest.exists():
        report["status"] = "fail"
        report["checks"]["bundle_records"] = {
            "name": "bundle_records",
            "status": "fail",
            "issues": [f"ingestion manifest not found: {ingestion_manifest}"],
            "warnings": [],
            "payload": {"path": str(ingestion_manifest)},
        }
    else:
        payload = _read_json(ingestion_manifest)
        normalize_err, entries, used_legacy = _normalize_entries(payload)
        if normalize_err is not None:
            report["status"] = "fail"
            report["checks"]["bundle_records"] = {
                "name": "bundle_records",
                "status": "fail",
                "issues": [normalize_err],
                "warnings": [],
                "payload": {"path": str(ingestion_manifest)},
            }
        else:
            if used_legacy:
                limitations.append("legacy ingestion key 'items' used for compatibility")
            bundle_check, limitations = _validate_bundle_records(
                entries,
                bundle_dir,
                expected_count=args.expected_bundles,
                skip_pdf_tools=args.skip_pdf_tools,
                expected_zotero_base_url=args.zotero_base_url,
                verified_corpus_lookup=corpus_lookup,
                limitations=limitations,
                validator=validator,
            )
            report["checks"]["bundle_records"] = bundle_check
            if bundle_check["status"] == "fail":
                report["status"] = "fail"

    notes_check, _ = _validate_notes(
        note_candidates,
        expected_count=args.expected_notes,
        validator=validator,
        standalone_expectations=standalone_note_records,
        standalone_manifest_issues=manifest_issues,
        limitations=limitations,
        skip_pdf_tools=args.skip_pdf_tools,
    )
    report["checks"]["notes"] = notes_check
    if notes_check["status"] == "fail":
        report["status"] = "fail"

    report["limitations"] = sorted(set(limitations))
    report["summary"] = {
        "corpus_files_checked": len(report["checks"]["corpus_files"]["payload"].get("items", []))
        if "corpus_files" in report["checks"] and isinstance(report["checks"]["corpus_files"].get("payload"), dict)
        else 0,
        "bundle_items_checked": len(report["checks"]["bundle_records"]["payload"].get("items", []))
        if "bundle_records" in report["checks"] and isinstance(report["checks"]["bundle_records"].get("payload"), dict)
        else 0,
        "notes_checked": len(report["checks"]["notes"]["payload"].get("items", [])),
        "pass": report["status"] == "pass",
    }

    report["status"] = "pass" if report["status"] == "pass" else "fail"
    return (EXIT_SUCCESS if report["status"] == "pass" else EXIT_FAIL, report)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Produce a deterministic read-only audit report for sparse-dynamics.",
    )
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--corpus-manifest", type=Path, default=None)
    parser.add_argument("--ingestion-manifest", type=Path, default=None)
    parser.add_argument("--bundle-dir", type=Path, default=None)
    parser.add_argument("--notes-dir", type=Path, default=None)
    parser.add_argument("--sindy-note", type=Path, default=None)
    parser.add_argument("--zotero-base-url", type=str, default=None)
    parser.add_argument("--generated-at", type=str, default=None)
    parser.add_argument("--expected-pdfs", type=int, default=DEFAULT_EXPECTED_PDFS)
    parser.add_argument("--expected-bundles", type=int, default=DEFAULT_EXPECTED_BUNDLE_ITEMS)
    parser.add_argument("--expected-notes", type=int, default=DEFAULT_EXPECTED_NOTES)
    parser.add_argument("--skip-pdf-tools", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.output is not None:
            output = args.output.expanduser().resolve()
            run_root = args.run_root.expanduser().resolve()
            corpus_manifest = (
                args.corpus_manifest.expanduser().resolve()
                if args.corpus_manifest is not None
                else run_root / "manifest.json"
            )
            ingestion_manifest = (
                args.ingestion_manifest.expanduser().resolve()
                if args.ingestion_manifest is not None
                else run_root / "ingestion_manifest.json"
            )
            legacy_ingestion_manifest = run_root / "ingestion_manifest.legacy.json"
            if not ingestion_manifest.exists() and legacy_ingestion_manifest.exists():
                ingestion_manifest = legacy_ingestion_manifest
            _ensure_output_not_input(
                args=args,
                run_root=run_root,
                output=output,
                corpus_manifest=corpus_manifest,
                ingestion_manifest=ingestion_manifest,
            )
        code, report = run_audit(args)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if args.output is not None:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return code
    except Exception as exc:
        payload = {
            "status": "error",
            "generated_at": (
                args.generated_at
                if getattr(args, "generated_at", None) is not None
                else datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            ),
            "error": str(exc),
            "python": {"version": sys.version.split(" ", maxsplit=1)[0]},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
