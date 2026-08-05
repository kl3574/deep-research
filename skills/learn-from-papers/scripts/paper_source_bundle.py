#!/usr/bin/env python3
"""Build and verify PaperSourceBundle/v1 source artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import errno
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "PaperSourceBundle/v1"
SCHEMA_VERSION = "v1"
PROTOCOL_VERSION = "1.0"
PRODUCER = "learn-from-papers"
BUNDLE_PREFIX = "paper-source-bundle-"
BACKUP_PREFIX = ".paper-source-bundle-backup-"
SPAN_PREFIX = "source-passages-span-"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BACKUP_JOURNAL = "paper-source-bundle-journal.json"
TOP_LEVEL_KEYS = {
    "schema",
    "schema_version",
    "producer",
    "protocol_version",
    "generated_at",
    "source",
    "page_count",
    "tools",
    "pages",
    "bundle_digest",
    "bundle_id",
    "rendered_pages",
}
SOURCE_KEYS = {"name", "format", "size_bytes", "source_sha256"}
TOOL_KEYS = {"command", "available", "status", "version"}
PAGE_KEYS = {"page_index", "artifact_path", "artifact_sha256", "byte_count", "char_count"}
RENDERED_PAGE_KEYS = {"page_index", "artifact_path", "artifact_sha256", "byte_count"}


class ContractError(ValueError):
    """Raised when an invariant is broken for bundle construction or verification."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_hex(value: str | bytes) -> str:
    hasher = hashlib.sha256()
    if isinstance(value, str):
        value = value.encode("utf-8")
    hasher.update(value)
    return hasher.hexdigest()


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty UTC ISO timestamp")
    if not value.endswith("Z"):
        raise ContractError(f"{label} must end with Z for UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be a UTC ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include UTC offset")
    if parsed.tzinfo != timezone.utc:
        raise ContractError(f"{label} must be UTC (Z)")
    return value


def _validate_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_sha256(value: Any, label: str) -> str:
    value = _validate_non_empty_string(value, label)
    if not SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return value


def _safe_parent(path: Path) -> None:
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise ContractError(f"refusing symlink path element: {current}")
        current = current.parent


def _write_atomic(path: Path, payload: bytes) -> None:
    _safe_parent(path)
    _safe_parent(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd = -1
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        temp_path = Path(temp_name)
        _safe_parent(temp_path)
        _safe_parent(path)
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        fd = -1

        _safe_parent(path)
        if path.exists() and path.is_symlink():
            raise ContractError(f"refusing symlink output path during publish: {path}")
        if path.parent.is_symlink():
            raise ContractError(f"refusing symlink output directory during publish: {path.parent}")

        os.replace(temp_path, path)
        _safe_parent(path.parent)
    finally:
        if fd != -1:
            os.close(fd)
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _safe_replace(src: Path, dst: Path) -> None:
    _safe_parent(dst)
    if dst.is_symlink():
        raise ContractError(f"refusing replacement onto symlink destination: {dst}")
    if src.is_symlink():
        raise ContractError(f"refusing replacement from symlink source: {src}")
    if dst.exists():
        if dst.is_dir():
            if not src.is_dir():
                raise ContractError(f"cannot replace directory with non-directory: {dst}")
            shutil.rmtree(dst)
        else:
            if src.is_dir():
                raise ContractError(f"cannot replace file with directory: {dst}")
            dst.unlink()
    os.replace(src, dst)


def _real_rmtree(path: Path, *, ignore_errors: bool = True) -> None:
    __import__("shutil").rmtree(path, ignore_errors=ignore_errors)


def _safe_replace_directory(src: Path, dst: Path) -> None:
    _safe_parent(dst)
    if dst.is_symlink():
        raise ContractError(f"refusing replacement onto symlink destination: {dst}")
    if src.is_symlink():
        raise ContractError(f"refusing replacement from symlink source: {src}")
    if not src.is_dir():
        raise ContractError(f"directory replace requires source directory: {src}")

    if dst.exists():
        if not dst.is_dir():
            raise ContractError(f"cannot replace directory with non-directory: {dst}")
        _real_rmtree(dst)

    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno == errno.ENOTEMPTY:
            # Filesystems may report ENOTEMPTY for directory renames with
            # implementation-specific constraints, so fall back to a safe
            # copy-and-replace path for recovery.
            if dst.exists():
                _real_rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
            _real_rmtree(src, ignore_errors=True)
            return
        raise


def _rollback_commit(
    *,
    moved_staged_to_live: list[tuple[Path, Path]],
    moved_live_to_backup: list[tuple[Path, Path]],
) -> None:
    for staged_path, live_path in reversed(moved_staged_to_live):
        if live_path.exists():
            _safe_replace(live_path, staged_path)
    for backup_path, live_path in reversed(moved_live_to_backup):
        if backup_path.exists():
            _safe_replace(backup_path, live_path)


def _backup_journal_path(backup_root: Path) -> Path:
    return backup_root / BACKUP_JOURNAL


def _write_backup_journal(backup_root: Path, output_path: Path) -> None:
    payload = {
        "output_path": str(output_path.resolve()),
        "created_at": _timestamp_now(),
    }
    _backup_journal_path(backup_root).write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _read_backup_journal(backup_root: Path) -> dict[str, Any] | None:
    journal_path = _backup_journal_path(backup_root)
    if not journal_path.exists():
        return None
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _iter_recoverable_backups(output_path: Path) -> list[Path]:
    output_key = str(output_path.resolve())
    parent = output_path.parent
    backups: list[Path] = []
    if not parent.exists():
        return backups
    for backup_root in sorted(parent.glob(f"{BACKUP_PREFIX}*")):
        if not backup_root.is_dir():
            continue
        journal = _read_backup_journal(backup_root)
        if journal is not None and journal.get("output_path") == output_key:
            if not (
                (backup_root / output_path.name).exists()
                or (backup_root / "pages").exists()
                or (backup_root / "page_renders").exists()
            ):
                _real_rmtree(backup_root, ignore_errors=True)
                continue
            backups.append(backup_root)
    return backups


def _recover_from_backup(output_path: Path, backup_root: Path) -> None:
    live_bundle = output_path
    live_pages_root = output_path.parent / "pages"
    live_render_root = output_path.parent / "page_renders"
    backup_bundle = backup_root / output_path.name
    backup_pages_root = backup_root / "pages"
    backup_render_root = backup_root / "page_renders"

    journal = _read_backup_journal(backup_root)
    if journal is None or journal.get("output_path") != str(output_path.resolve()):
        raise ContractError(f"backup is not for output path: {backup_root}")

    recovered_any = False
    if backup_bundle.exists():
        _safe_replace(backup_bundle, live_bundle)
        recovered_any = True
    if backup_pages_root.exists():
        _safe_replace_directory(backup_pages_root, live_pages_root)
        recovered_any = True
    if backup_render_root.exists():
        _safe_replace_directory(backup_render_root, live_render_root)
        recovered_any = True
    if not recovered_any:
        raise ContractError(f"backup has no recoverable content: {backup_root}")


def _cleanup_stale_staging(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for stale in sorted(output_dir.glob(".paper-source-bundle-staging-*")):
        if stale.is_dir():
            _real_rmtree(stale, ignore_errors=True)


def recover_bundle(*, output: str, backup: str | None = None) -> str:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    backup_root = Path(backup) if backup else None
    if backup_root is None:
        candidates = _iter_recoverable_backups(output_path)
        if not candidates:
            raise ContractError(f"no recoverable backup found for output: {output_path}")
        backup_root = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    if not backup_root.exists() or not backup_root.is_dir():
        raise ContractError(f"backup root missing: {backup_root}")

    _recover_from_backup(output_path=output_path, backup_root=backup_root)
    _real_rmtree(backup_root, ignore_errors=True)
    return str(backup_root)


def _recover_pending_bundle(output_path: Path) -> None:
    candidates = _iter_recoverable_backups(output_path)
    if not candidates:
        return
    backup_root = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    _recover_from_backup(output_path=output_path, backup_root=backup_root)
    _real_rmtree(backup_root, ignore_errors=True)


def _commit_staging(output_path: Path, staging_root: Path) -> None:
    staged_bundle = staging_root / output_path.name
    staged_pages_root = staging_root / "pages"
    staged_render_root = staging_root / "page_renders"
    live_bundle = output_path
    live_pages_root = output_path.parent / "pages"
    live_render_root = output_path.parent / "page_renders"

    if not staged_bundle.exists():
        raise ContractError("staged bundle is missing")
    if not staged_pages_root.is_dir():
        raise ContractError("staged pages root is missing")

    backup_root = Path(tempfile.mkdtemp(prefix=BACKUP_PREFIX, dir=str(output_path.parent)))
    _write_backup_journal(backup_root, output_path)
    moved_staged_to_live: list[tuple[Path, Path]] = []
    moved_live_to_backup: list[tuple[Path, Path]] = []

    try:
        if live_bundle.exists():
            if live_bundle.is_symlink():
                raise ContractError(f"refusing symlink live bundle path: {live_bundle}")
            live_backup = backup_root / output_path.name
            _safe_replace(live_bundle, live_backup)
            moved_live_to_backup.append((live_backup, live_bundle))

        if live_pages_root.exists():
            if live_pages_root.is_symlink():
                raise ContractError(f"refusing symlink pages root: {live_pages_root}")
            if not live_pages_root.is_dir():
                raise ContractError(f"live pages root must be directory: {live_pages_root}")
            live_backup = backup_root / "pages"
            _safe_replace(live_pages_root, live_backup)
            moved_live_to_backup.append((live_backup, live_pages_root))

        if live_render_root.exists():
            if live_render_root.is_symlink():
                raise ContractError(f"refusing symlink render root: {live_render_root}")
            if not live_render_root.is_dir():
                raise ContractError(f"live render root must be directory: {live_render_root}")
            live_backup = backup_root / "page_renders"
            _safe_replace(live_render_root, live_backup)
            moved_live_to_backup.append((live_backup, live_render_root))

        _safe_replace(staged_pages_root, live_pages_root)
        moved_staged_to_live.append((staged_pages_root, live_pages_root))

        if staged_render_root.exists():
            _safe_replace(staged_render_root, live_render_root)
            moved_staged_to_live.append((staged_render_root, live_render_root))

        _safe_replace(staged_bundle, live_bundle)
        moved_staged_to_live.append((staged_bundle, live_bundle))
    except Exception as exc:
        try:
            _rollback_commit(
                moved_staged_to_live=moved_staged_to_live,
                moved_live_to_backup=moved_live_to_backup,
            )
        except Exception as rollback_exc:
            raise ContractError(
                f"build commit failed and rollback failed; recoverable backup at {backup_root}"
            ) from rollback_exc
        finally:
            if not backup_root.exists():
                return
        raise ContractError(f"build commit failed: {exc}") from exc
    if backup_root.exists():
        _real_rmtree(backup_root, ignore_errors=True)

    if backup_root.exists():
        _real_rmtree(backup_root, ignore_errors=True)


def _ensure_file_input(path: Path, label: str) -> None:
    if not path.is_file():
        raise ContractError(f"{label} must be an existing file: {path}")
    if path.is_symlink():
        raise ContractError(f"{label} must not be a symlink: {path}")
    _safe_parent(path)


def _read_file_bytes(path: Path) -> bytes:
    _ensure_file_input(path, "source")
    return path.read_bytes()


def _sha256_file(path: Path) -> str:
    return sha256_hex(_read_file_bytes(path))


def canonical_bundle_digest(document: dict[str, Any]) -> str:
    return sha256_hex(
        canonical_json_bytes(
            {key: value for key, value in document.items() if key not in {"bundle_id", "bundle_digest"}}
        )
    )


def bundle_id(digest: str) -> str:
    return f"{BUNDLE_PREFIX}{digest[:16]}"


def span_id(digest: str) -> str:
    return f"{SPAN_PREFIX}{digest[:16]}"


def _run_tool_version(command: str, *, required: bool = False) -> dict[str, Any]:
    executable = shutil.which(command)
    if executable is None:
        status = "missing"
        if required:
            raise ContractError(f"required tool is missing: {command}")
        return {
            "command": command,
            "available": False,
            "status": status,
            "version": None,
        }

    try:
        completed = subprocess.run(
            [executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        status = "failed"
        if required:
            raise ContractError(f"required tool failed to run: {command}") from exc
        return {
            "command": command,
            "available": False,
            "status": status,
            "version": None,
        }

    payload = (completed.stdout or completed.stderr or "").strip().splitlines()
    version = payload[0].strip() if payload else None
    status = "ok" if completed.returncode == 0 else "failed"
    if required and status != "ok":
        raise ContractError(f"required tool is unavailable: {command}")
    if status != "ok" and not required and completed.returncode != 0:
        return {
            "command": command,
            "available": False,
            "status": "failed",
            "version": version,
        }
    return {
        "command": command,
        "available": True,
        "status": "ok",
        "version": version,
    }


def _ensure_source_type(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "pdf"
    try:
        if _read_file_bytes(path).startswith(b"%PDF-"):
            return "pdf"
    except OSError:
        return "text"
    return "text"


def _split_text_pages(source_bytes: bytes) -> list[str]:
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("source is not valid UTF-8") from exc
    # FF is explicit page break in legacy plain-text exports.
    return text.split("\x0c") or [""]

def _extract_pdf_page_count(source: Path, pdfinfo: str) -> int:
    completed = subprocess.run(
        [pdfinfo, str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise ContractError(f"pdfinfo failed: {completed.stderr.strip() or completed.stdout.strip()}")
    for line in completed.stdout.splitlines():
        if not line.lower().startswith("pages:"):
            continue
        value = line.split(":", 1)[1].strip().split()[0]
        return int(value)
    raise ContractError("pdfinfo output did not contain page count")


def _extract_pdf_page_text(source: Path, pdftotext: str, page: int) -> str:
    completed = subprocess.run(
        [pdftotext, "-layout", "-f", str(page), "-l", str(page), "-enc", "UTF-8", str(source), "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise ContractError(
            f"pdftotext failed for page {page}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout


def _render_pdf_page_image(source: Path, pdftoppm: str, page: int, destination: Path) -> str:
    completed = subprocess.run(
        [pdftoppm, "-png", "-singlefile", "-f", str(page), "-l", str(page), str(source), str(destination)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise ContractError(
            f"pdftoppm failed for page {page}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    candidates = sorted(destination.parent.glob(f"{destination.name}*.png"))
    if not candidates:
        raise ContractError(f"pdftoppm output file missing for page {page}")
    return candidates[0].name


def _ensure_artifact_path(root: Path, artifact_path: str) -> Path:
    if not isinstance(artifact_path, str):
        raise ContractError("artifact_path must be a string")
    if artifact_path.startswith(("/", "\\")):
        raise ContractError(f"artifact_path must be relative: {artifact_path}")
    normalized = Path(artifact_path.replace("\\", "/"))
    if ".." in normalized.parts or any(part in {"", "."} for part in normalized.parts):
        raise ContractError(f"artifact_path is not normalized: {artifact_path}")
    candidate = root / normalized
    cursor = root
    for part in normalized.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ContractError(f"artifact_path contains symlink component: {artifact_path}")
    candidate = candidate.resolve(strict=False)
    root_resolved = root.resolve()
    if not str(candidate).startswith(str(root_resolved) + os.sep):
        raise ContractError(f"artifact_path escapes bundle root: {artifact_path}")
    if candidate.is_symlink():
        raise ContractError(f"artifact file is symlink: {artifact_path}")
    return candidate


def _validate_artifact_reference(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    if value.startswith(("/", "\\")):
        raise ContractError(f"{label} must be relative: {value}")
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {"", "."} for part in parts) or ".." in parts:
        raise ContractError(f"{label} contains invalid path elements: {value}")
    return normalized


def _reject_unknown_fields(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = set(payload) - allowed
    if extra:
        raise ContractError(f"{label} contains unknown keys: {', '.join(sorted(extra))}")


def _to_tool_map() -> dict[str, dict[str, Any]]:
    return {
        "pdfinfo": _run_tool_version("pdfinfo", required=True),
        "pdftotext": _run_tool_version("pdftotext", required=True),
    }


def build_bundle(
    *,
    source: str,
    output: str,
    generated_at: str | None = None,
    render_pages: bool = False,
) -> dict[str, Any]:
    source_path = Path(source)
    output_path = Path(output)
    if output_path.exists() and output_path.is_symlink():
        raise ContractError(f"refusing symlink output path: {output_path}")
    _safe_parent(source_path)
    _safe_parent(output_path)
    _ensure_file_input(source_path, "source")

    source_type = _ensure_source_type(source_path)
    source_bytes = _read_file_bytes(source_path)
    source_size = len(source_bytes)
    source_hash = sha256_hex(source_bytes)

    generated_time = _validate_timestamp(generated_at, "generated_at") if generated_at else _timestamp_now()
    _cleanup_stale_staging(output_path.parent)
    _recover_pending_bundle(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_root: Path | None = None
    try:
        staging_root = Path(
            tempfile.mkdtemp(prefix=".paper-source-bundle-staging-", dir=str(output_path.parent))
        )
        pages_root = staging_root / "pages"
        rendered_root = staging_root / "page_renders"
        staged_bundle_path = staging_root / output_path.name
        tool_map: dict[str, dict[str, Any]]

        pages_root.mkdir(parents=True, exist_ok=True)
        if render_pages:
            rendered_root.mkdir(parents=True, exist_ok=True)

        pages: list[dict[str, Any]] = []
        rendered_pages: list[dict[str, Any]] = []
        if source_type == "pdf":
            tool_map = _to_tool_map()
            pdfinfo_path = shutil.which("pdfinfo")
            pdftotext_path = shutil.which("pdftotext")
            if pdfinfo_path is None or pdftotext_path is None:
                tool_map["pdfinfo"] = _run_tool_version("pdfinfo", required=False)
                tool_map["pdftotext"] = _run_tool_version("pdftotext", required=False)
                raise ContractError("pdfinfo/pdftotext missing from PATH")

            tool_map["pdfinfo"] = _run_tool_version("pdfinfo", required=True)
            tool_map["pdftotext"] = _run_tool_version("pdftotext", required=True)
            page_count = _extract_pdf_page_count(source_path, pdfinfo_path)
            render_cmd = None
            if render_pages:
                pdftoppm_path = shutil.which("pdftoppm")
                if pdftoppm_path is None:
                    tool_map["pdftoppm"] = _run_tool_version("pdftoppm", required=False)
                    raise ContractError("pdftoppm unavailable while render requested")
                tool_map["pdftoppm"] = _run_tool_version("pdftoppm", required=True)
                render_cmd = pdftoppm_path
            else:
                tool_map["pdftoppm"] = {
                    "command": "pdftoppm",
                    "available": False,
                    "status": "disabled",
                    "version": None,
                }

            for page_index in range(1, page_count + 1):
                raw_text = _extract_pdf_page_text(source_path, pdftotext_path, page_index)
                page_bytes = raw_text.encode("utf-8")
                artifact_name = f"page-{page_index:04d}.txt"
                artifact_rel = Path("pages") / artifact_name
                artifact_path = pages_root / artifact_name
                artifact_path.write_bytes(page_bytes)
                pages.append(
                    {
                        "page_index": page_index,
                        "artifact_path": artifact_rel.as_posix(),
                        "artifact_sha256": sha256_hex(page_bytes),
                        "byte_count": len(page_bytes),
                        "char_count": len(raw_text),
                    }
                )
                if render_cmd is not None:
                    render_prefix = rendered_root / f"page-{page_index:04d}"
                    rendered_name = _render_pdf_page_image(
                        source_path, render_cmd, page_index, render_prefix
                    )
                    rendered_rel = Path("page_renders") / rendered_name
                    rendered_path = rendered_root / rendered_name
                    if rendered_path.is_file():
                        rendered_bytes = rendered_path.read_bytes()
                        rendered_pages.append(
                            {
                                "page_index": page_index,
                                "artifact_path": rendered_rel.as_posix(),
                                "artifact_sha256": sha256_hex(rendered_bytes),
                                "byte_count": len(rendered_bytes),
                            }
                        )
                    else:
                        raise ContractError(f"render artifact missing for page {page_index}")
        else:
            tool_map = {
                "pdfinfo": {
                    "command": "pdfinfo",
                    "available": False,
                    "status": "not_needed",
                    "version": None,
                },
                "pdftotext": {
                    "command": "pdftotext",
                    "available": False,
                    "status": "not_needed",
                    "version": None,
                },
                "pdftoppm": {
                    "command": "pdftoppm",
                    "available": False,
                    "status": "not_needed",
                    "version": None,
                },
            }
            texts = _split_text_pages(source_bytes)
            for page_index, page_text in enumerate(texts, start=1):
                page_bytes = page_text.encode("utf-8")
                artifact_name = f"page-{page_index:04d}.txt"
                artifact_rel = Path("pages") / artifact_name
                artifact_path = pages_root / artifact_name
                artifact_path.write_bytes(page_bytes)
                pages.append(
                    {
                        "page_index": page_index,
                        "artifact_path": artifact_rel.as_posix(),
                        "artifact_sha256": sha256_hex(page_bytes),
                        "byte_count": len(page_bytes),
                        "char_count": len(page_text),
                    }
                )

        manifest_payload: dict[str, Any] = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "producer": PRODUCER,
            "protocol_version": PROTOCOL_VERSION,
            "generated_at": generated_time,
            "source": {
                "name": source_path.name,
                "format": source_type,
                "size_bytes": source_size,
                "source_sha256": source_hash,
            },
            "page_count": len(pages),
            "tools": tool_map,
            "pages": pages,
        }
        if render_pages:
            manifest_payload["rendered_pages"] = rendered_pages
        manifest_payload["bundle_digest"] = canonical_bundle_digest(manifest_payload)
        manifest_payload["bundle_id"] = bundle_id(manifest_payload["bundle_digest"])

        _write_atomic(staged_bundle_path, canonical_json_bytes(manifest_payload) + b"\n")
        verify_bundle(bundle=str(staged_bundle_path), source=str(source_path))
        _commit_staging(output_path=output_path, staging_root=staging_root)
        return validate_bundle(manifest_payload)
    finally:
        if staging_root is not None and staging_root.exists():
            _real_rmtree(staging_root, ignore_errors=True)


def validate_bundle(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ContractError("bundle must be a JSON object")
    payload = dict(document)
    _reject_unknown_fields(
        payload,
        TOP_LEVEL_KEYS,
        "bundle",
    )
    if payload.get("schema") != SCHEMA:
        raise ContractError(f"bundle.schema must be {SCHEMA}")
    if _validate_non_empty_string(payload.get("schema_version"), "schema_version") != SCHEMA_VERSION:
        raise ContractError("bundle.schema_version must be v1")
    if _validate_non_empty_string(payload.get("producer"), "producer") != PRODUCER:
        raise ContractError("bundle.producer must be learn-from-papers")
    if _validate_non_empty_string(payload.get("protocol_version"), "protocol_version") != PROTOCOL_VERSION:
        raise ContractError("bundle.protocol_version must be 1.0")
    generated = _validate_timestamp(payload.get("generated_at"), "generated_at")

    source = payload.get("source")
    if not isinstance(source, dict):
        raise ContractError("bundle.source must be an object")
    _reject_unknown_fields(source, SOURCE_KEYS, "bundle.source")
    source_name = _validate_non_empty_string(source.get("name"), "source.name")
    source_format = _validate_non_empty_string(source.get("format"), "source.format")
    if source_format not in {"text", "pdf"}:
        raise ContractError("source.format must be text or pdf")
    source_size = source.get("size_bytes")
    if not isinstance(source_size, int) or source_size < 0:
        raise ContractError("source.size_bytes must be >= 0")
    source_sha256 = _validate_sha256(source.get("source_sha256"), "source.source_sha256")
    page_count = payload.get("page_count")
    if not isinstance(page_count, int) or page_count < 1:
        raise ContractError("page_count must be positive")

    tools = payload.get("tools")
    if not isinstance(tools, dict):
        raise ContractError("tools must be an object")
    _reject_unknown_fields(tools, {"pdfinfo", "pdftotext", "pdftoppm"}, "bundle.tools")
    for key in ["pdfinfo", "pdftotext"]:
        _validate_tool_block(tools.get(key), key)
    if "pdftoppm" in tools:
        _validate_tool_block(tools["pdftoppm"], "pdftoppm", allow_missing=True)

    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ContractError("pages must be a non-empty list")

    seen_indexes: set[int] = set()
    normalized_pages: list[dict[str, Any]] = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ContractError(f"pages[{index}] must be an object")
        _reject_unknown_fields(page, PAGE_KEYS, f"pages[{index}]")
        artifact_path = _validate_artifact_reference(
            page.get("artifact_path"),
            f"pages[{index}].artifact_path",
        )
        page_index = page.get("page_index")
        if not isinstance(page_index, int) or page_index < 1:
            raise ContractError(f"pages[{index}].page_index must be positive int")
        if page_index in seen_indexes:
            raise ContractError(f"duplicate page_index: {page_index}")
        seen_indexes.add(page_index)
        _validate_sha256(page.get("artifact_sha256"), f"pages[{index}].artifact_sha256")
        byte_count = page.get("byte_count")
        char_count = page.get("char_count")
        if not isinstance(byte_count, int) or byte_count < 0:
            raise ContractError(f"pages[{index}].byte_count must be >= 0")
        if char_count is not None and (not isinstance(char_count, int) or char_count < 0):
            raise ContractError(f"pages[{index}].char_count must be >= 0")
        normalized_pages.append(
            {
                "page_index": page_index,
                "artifact_path": artifact_path,
                "artifact_sha256": page["artifact_sha256"],
                "byte_count": byte_count,
                "char_count": char_count,
            }
        )
    if page_count != len(normalized_pages):
        raise ContractError("page_count must match number of pages")

    rendered_pages = document.get("rendered_pages")
    normalized_rendered_pages: list[dict[str, Any]] = []
    if rendered_pages is not None:
        if not isinstance(rendered_pages, list):
            raise ContractError("rendered_pages must be a list if present")
        for index, item in enumerate(rendered_pages):
            if not isinstance(item, dict):
                raise ContractError(f"rendered_pages[{index}] must be an object")
            _reject_unknown_fields(item, RENDERED_PAGE_KEYS, f"rendered_pages[{index}]")
            artifact_path = _validate_artifact_reference(
                item.get("artifact_path"),
                f"rendered_pages[{index}].artifact_path",
            )
            _validate_non_empty_string(item.get("artifact_sha256"), f"rendered_pages[{index}].artifact_sha256")
            _validate_sha256(item.get("artifact_sha256"), f"rendered_pages[{index}].artifact_sha256")
            if not isinstance(item.get("byte_count"), int) or item.get("byte_count", -1) < 0:
                raise ContractError(f"rendered_pages[{index}].byte_count must be >= 0")
            if not isinstance(item.get("page_index"), int) or item.get("page_index") < 1:
                raise ContractError(f"rendered_pages[{index}].page_index must be positive")
            normalized_rendered_pages.append(
                {
                    "page_index": item["page_index"],
                    "artifact_path": artifact_path,
                    "artifact_sha256": item["artifact_sha256"],
                    "byte_count": item["byte_count"],
                }
            )

    manifest_digest = _validate_non_empty_string(payload.get("bundle_digest"), "bundle_digest")
    if not SHA256_RE.fullmatch(manifest_digest):
        raise ContractError("bundle_digest must be hex sha256")
    bundle_id_value = _validate_non_empty_string(payload.get("bundle_id"), "bundle_id")
    if not bundle_id_value.startswith(BUNDLE_PREFIX):
        raise ContractError("bundle_id invalid prefix")
    expected_bundle_id = bundle_id(manifest_digest)
    if bundle_id_value != expected_bundle_id:
        raise ContractError("bundle_id does not match bundle_digest")

    normalized_payload = dict(payload)
    normalized_payload["pages"] = normalized_pages
    if rendered_pages is not None:
        normalized_payload["rendered_pages"] = normalized_rendered_pages
    manifest_source = normalized_payload.get("source")
    assert isinstance(manifest_source, dict)
    normalized_payload["source"] = {
        "name": source_name,
        "format": source_format,
        "size_bytes": source_size,
        "source_sha256": source_sha256,
    }
    expected = canonical_bundle_digest(normalized_payload)
    if expected != manifest_digest:
        raise ContractError("bundle_digest does not match manifest payload")

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": generated,
        "source": {
            "name": source_name,
            "format": source_format,
            "size_bytes": source_size,
            "source_sha256": source_sha256,
        },
        "page_count": page_count,
        "tools": tools,
        "pages": normalized_pages,
        **({"rendered_pages": normalized_rendered_pages} if rendered_pages is not None else {}),
        "bundle_digest": manifest_digest,
        "bundle_id": bundle_id_value,
    }


def _validate_tool_block(value: Any, name: str, *, allow_missing: bool = False) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"tools.{name} must be an object")
    _reject_unknown_fields(value, TOOL_KEYS, f"tools.{name}")
    command = _validate_non_empty_string(value.get("command"), f"tools.{name}.command")
    if command != name:
        raise ContractError(f"tools.{name}.command must be {name}")
    status = _validate_non_empty_string(value.get("status"), f"tools.{name}.status")
    if status not in {"ok", "missing", "failed", "not_needed", "disabled"}:
        raise ContractError(f"tools.{name}.status invalid: {status}")
    available = value.get("available")
    if not isinstance(available, bool):
        raise ContractError(f"tools.{name}.available must be bool")
    if not allow_missing and not available and status in {"missing", "failed"}:
        raise ContractError(f"tools.{name}.missing required tool for bundle")
    if "version" in value and value.get("version") is not None:
        _validate_non_empty_string(value.get("version"), f"tools.{name}.version")


def verify_bundle(*, bundle: str, source: str) -> dict[str, Any]:
    bundle_path = Path(bundle)
    source_path = Path(source)
    _ensure_file_input(bundle_path, "bundle")
    _ensure_file_input(source_path, "source")
    _safe_parent(bundle_path)
    raw = json.loads(bundle_path.read_text(encoding="utf-8"))
    normalized = validate_bundle(raw)
    manifest_dir = bundle_path.parent
    if manifest_dir.is_symlink():
        raise ContractError("bundle-root directory must not be a symlink")
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != normalized["source"]["size_bytes"]:
        raise ContractError("source size mismatch")
    if sha256_hex(source_bytes) != normalized["source"]["source_sha256"]:
        raise ContractError("source sha256 mismatch")

    if normalized["source"]["name"] != source_path.name:
        raise ContractError("source name mismatch")

    by_page = {page["page_index"]: page for page in normalized["pages"]}
    source_format = normalized["source"]["format"]

    if source_format == "text":
        source_pages = _split_text_pages(source_bytes)
        if len(source_pages) != normalized["page_count"]:
            raise ContractError("page_count mismatch against source data")
        for index, source_page in enumerate(source_pages, start=1):
            page = by_page.get(index)
            if page is None:
                raise ContractError("missing page artifact for source-derived page index")
            expected_bytes = source_page.encode("utf-8")
            if page["byte_count"] != len(expected_bytes):
                raise ContractError("page artifact byte_count does not match source-derived text")
            if page["artifact_sha256"] != sha256_hex(expected_bytes):
                raise ContractError("page artifact hash does not match source-derived text")
            if page["char_count"] is not None and page["char_count"] != len(source_page):
                raise ContractError("page char_count does not match source-derived text")

            page_root = _ensure_artifact_path(manifest_dir, page["artifact_path"])
            if not page_root.is_file():
                raise ContractError(f"pages[{index}] artifact missing: {page['artifact_path']}")
            if page_root.is_symlink():
                raise ContractError(f"pages[{index}] artifact is symlink: {page['artifact_path']}")
            page_bytes = page_root.read_bytes()
            if page_bytes != expected_bytes:
                raise ContractError(f"pages[{index}] artifact does not match source-derived text")
            if page_root.stat().st_size != page["byte_count"]:
                raise ContractError(f"pages[{index}] artifact size mismatch")
    elif source_format == "pdf":
        tools = normalized["tools"]
        current_pdfinfo = _run_tool_version("pdfinfo", required=True)
        current_pdftotext = _run_tool_version("pdftotext", required=True)

        if tools["pdfinfo"]["version"] != current_pdfinfo["version"]:
            raise ContractError("tools.pdfinfo.version mismatch with current environment")
        if tools["pdftotext"]["version"] != current_pdftotext["version"]:
            raise ContractError("tools.pdftotext.version mismatch with current environment")

        pdfinfo_path = shutil.which("pdfinfo")
        pdftotext_path = shutil.which("pdftotext")
        if pdfinfo_path is None or pdftotext_path is None:
            raise ContractError("required PDF tools are unavailable")

        page_count = _extract_pdf_page_count(source_path, pdfinfo_path)
        if page_count != normalized["page_count"]:
            raise ContractError("page_count mismatch against re-extracted PDF data")

        for index in range(1, page_count + 1):
            page = by_page.get(index)
            if page is None:
                raise ContractError("missing page artifact for source-derived page index")
            page_text = _extract_pdf_page_text(source_path, pdftotext_path, index)
            expected_bytes = page_text.encode("utf-8")
            if page["byte_count"] != len(expected_bytes):
                raise ContractError("page artifact byte_count does not match extracted PDF text")
            if page["artifact_sha256"] != sha256_hex(expected_bytes):
                raise ContractError("page artifact hash does not match extracted PDF text")
            if page["char_count"] is not None and page["char_count"] != len(page_text):
                raise ContractError("page char_count does not match extracted PDF text")

            page_root = _ensure_artifact_path(manifest_dir, page["artifact_path"])
            if not page_root.is_file():
                raise ContractError(f"pages[{index}] artifact missing: {page['artifact_path']}")
            if page_root.is_symlink():
                raise ContractError(f"pages[{index}] artifact is symlink: {page['artifact_path']}")
            page_bytes = page_root.read_bytes()
            if page_bytes != expected_bytes:
                raise ContractError(f"pages[{index}] artifact does not match extracted PDF text")
            if page_root.stat().st_size != page["byte_count"]:
                raise ContractError(f"pages[{index}] artifact size mismatch")
    else:
        raise ContractError(f"unsupported source format: {source_format}")

    for rendered in normalized.get("rendered_pages", []):
        artifact = _ensure_artifact_path(manifest_dir, rendered["artifact_path"])
        if not artifact.is_file():
            raise ContractError(f"rendered page artifact missing: {rendered['artifact_path']}")
        if artifact.is_symlink():
            raise ContractError(f"rendered page artifact is symlink: {rendered['artifact_path']}")
        rendered_bytes = artifact.read_bytes()
        if sha256_hex(rendered_bytes) != rendered["artifact_sha256"]:
            raise ContractError(f"rendered page hash mismatch: {rendered['artifact_path']}")
        if len(rendered_bytes) != rendered["byte_count"]:
            raise ContractError(f"rendered page size mismatch: {rendered['artifact_path']}")

    return normalized


def _find_char_offsets(page_bytes: bytes, start: int, end: int, page_index: int) -> tuple[int, int]:
    if start < 0 or end < 0:
        raise ContractError("offsets must be >= 0")
    if end < start:
        raise ContractError("end_offset must be >= start_offset")

    text = page_bytes.decode("utf-8")
    if end > len(text):
        raise ContractError("end_offset beyond page text length")
    start_bytes = text[:start].encode("utf-8")
    end_bytes = text[:end].encode("utf-8")
    return len(start_bytes), len(end_bytes)


def locate_span(*, bundle: str, page: int, start_char: int, end_char: int) -> dict[str, Any]:
    if page < 1:
        raise ContractError("page must be >= 1")
    bundle_path = Path(bundle)
    _ensure_file_input(bundle_path, "bundle")
    bundle_data = validate_bundle(json.loads(bundle_path.read_text(encoding="utf-8")))
    manifest_dir = bundle_path.parent

    target = next((item for item in bundle_data["pages"] if item["page_index"] == page), None)
    if target is None:
        raise ContractError(f"page {page} not found in bundle")
    page_path = _ensure_artifact_path(manifest_dir, target["artifact_path"])
    if not page_path.is_file():
        raise ContractError(f"artifact missing for page {page}")
    if page_path.is_symlink():
        raise ContractError(f"page artifact is symlink: {target['artifact_path']}")

    page_bytes = page_path.read_bytes()
    if len(page_bytes) != target["byte_count"]:
        raise ContractError("pages[...].artifact size mismatch for locate")
    if sha256_hex(page_bytes) != target["artifact_sha256"]:
        raise ContractError("pages[...].artifact digest mismatch for locate")
    if target["char_count"] is not None:
        try:
            if len(page_bytes.decode("utf-8")) != target["char_count"]:
                raise ContractError("pages[...].char_count mismatch for locate")
        except UnicodeDecodeError as exc:
            raise ContractError("pages[...].artifact must decode as UTF-8 for locate") from exc

    start_byte, end_byte = _find_char_offsets(page_bytes, start_char, end_char, page)
    fragment = page_bytes[start_byte:end_byte]
    span_context = {
        "schema": "PaperSourceBundleSpan/v1",
        "bundle_id": bundle_data["bundle_id"],
        "page": page,
        "start_char": start_char,
        "end_char": end_char,
    }
    span_context_bytes = canonical_json_bytes(span_context)
    span_hash = sha256_hex(span_context_bytes + b"|" + fragment)

    return {
        "bundle_id": bundle_data["bundle_id"],
        "page": page,
        "start_char": start_char,
        "end_char": end_char,
        "exact_locator": f"p.{page} [{start_char}:{end_char}]",
        "span_hash": span_hash,
        "span_id": span_id(span_hash),
        "artifact_path": target["artifact_path"],
    }


def _parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    build = subcommands.add_parser("build", help="Build PaperSourceBundle/v1 from source")
    build.add_argument("--source", required=True)
    build.add_argument("--output", required=True, help="Bundle JSON path")
    build.add_argument("--generated-at")
    build.add_argument("--render-pages", action="store_true")

    verify = subcommands.add_parser("verify", help="Verify a PaperSourceBundle/v1")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--source", required=True)

    recover = subcommands.add_parser("recover", help="Recover a PaperSourceBundle/v1 from backup")
    recover.add_argument("--output", required=True, help="Bundle JSON path")
    recover.add_argument("--backup", help="Backup directory path")

    locate = subcommands.add_parser("locate", help="Locate a span by page char offsets")
    locate.add_argument("--bundle", required=True)
    locate.add_argument("--page", required=True, type=int)
    locate.add_argument("--start-char", required=True, type=int)
    locate.add_argument("--end-char", required=True, type=int)
    return root


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            manifest = build_bundle(
                source=args.source,
                output=args.output,
                generated_at=args.generated_at,
                render_pages=args.render_pages,
            )
            print(manifest["bundle_id"])
        elif args.command == "verify":
            verify_bundle(bundle=args.bundle, source=args.source)
            print("verify: true")
        elif args.command == "recover":
            backup = recover_bundle(output=args.output, backup=args.backup)
            print(f"recovered: {backup}")
        else:
            result = locate_span(
                bundle=args.bundle,
                page=args.page,
                start_char=args.start_char,
                end_char=args.end_char,
            )
            print(json.dumps(result, sort_keys=True))
        return 0
    except (ContractError, OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
        print(f"paper-source-bundle failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
