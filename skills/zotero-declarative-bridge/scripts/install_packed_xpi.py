#!/usr/bin/env python3
"""Atomically stage a reviewed packed XPI in the active Zotero profile."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import shutil
import socket
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PLUGIN_ID = "zotero-declarative-bridge@deep-research.local"
PLUGIN_VERSION = "0.1.1"
FILES = ("manifest.json", "bridge_core.js", "bootstrap.js")
ZOTERO_PORT = 23119


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_xpi(path: Path) -> tuple[dict, str]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError("XPI must be a regular non-symlink file")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if names != list(FILES) or len(set(names)) != len(names):
            raise ValueError(f"XPI root entries must be exactly {list(FILES)} in build order")
        manifest = json.loads(archive.read("manifest.json"))
    app = manifest.get("applications", {}).get("zotero", {})
    expected = {
        "manifest_version": 2,
        "version": PLUGIN_VERSION,
        "id": PLUGIN_ID,
        "strict_min_version": "9.0",
        "strict_max_version": "9.0.*",
    }
    observed = {
        "manifest_version": manifest.get("manifest_version"),
        "version": manifest.get("version"),
        "id": app.get("id"),
        "strict_min_version": app.get("strict_min_version"),
        "strict_max_version": app.get("strict_max_version"),
    }
    if observed != expected:
        raise ValueError(f"XPI manifest mismatch: {observed}")
    return manifest, sha256_file(path)


def active_default_profile(profile: Path) -> tuple[Path, str]:
    profile = profile.expanduser().resolve()
    profiles_ini = profile.parent / "profiles.ini"
    parser = configparser.ConfigParser()
    if not parser.read(profiles_ini, encoding="utf-8"):
        raise ValueError(f"profiles.ini unavailable: {profiles_ini}")
    defaults = []
    for section in parser.sections():
        if not section.startswith("Profile") or parser.get(section, "Default", fallback="0") != "1":
            continue
        raw = parser.get(section, "Path")
        candidate = (profiles_ini.parent / raw).resolve() if parser.get(section, "IsRelative", fallback="1") == "1" else Path(raw).expanduser().resolve()
        defaults.append(candidate)
    if defaults != [profile]:
        raise ValueError(f"explicit profile is not the unique default profile: {defaults}")
    compatibility = configparser.ConfigParser()
    compatibility_path = profile / "compatibility.ini"
    if not compatibility.read(compatibility_path, encoding="utf-8"):
        raise ValueError(f"compatibility.ini unavailable: {compatibility_path}")
    last_version = compatibility.get("Compatibility", "LastVersion").split("_", 1)[0]
    if not last_version.startswith("9.0."):
        raise ValueError(f"active profile runtime is outside reviewed Zotero 9.0.*: {last_version}")
    return profiles_ini, last_version


def zotero_is_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", ZOTERO_PORT), timeout=0.25):
            return True
    except OSError:
        return False


def write_private_json(path: Path, value: dict) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to overwrite receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install_packed_xpi(
    xpi: Path,
    profile: Path,
    receipt: Path,
    backup_dir: Path | None = None,
) -> dict:
    xpi = xpi.expanduser().resolve()
    profile = profile.expanduser().resolve()
    receipt = receipt.expanduser().resolve()
    manifest, digest = inspect_xpi(xpi)
    profiles_ini, runtime_version = active_default_profile(profile)
    if zotero_is_running():
        raise ValueError("Zotero is listening on 127.0.0.1:23119; close it before staging an XPI")

    extensions = profile / "extensions"
    extensions.mkdir(mode=0o700, parents=True, exist_ok=True)
    bare_id = extensions / PLUGIN_ID
    destination = extensions / f"{PLUGIN_ID}.xpi"
    if bare_id.exists() or bare_id.is_symlink():
        raise ValueError("ambiguous bare-ID entry exists; it must be reviewed as a developer proxy, not overwritten")
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError("existing packed-XPI destination is not a regular file")

    previous = None
    if destination.exists():
        if backup_dir is None:
            raise ValueError("existing XPI requires --backup-dir")
        backup_dir = backup_dir.expanduser().resolve()
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup = backup_dir / f"{PLUGIN_ID}.xpi"
        if backup.exists() or backup.is_symlink():
            raise ValueError(f"refusing to overwrite backup: {backup}")
        shutil.copyfile(destination, backup)
        os.chmod(backup, 0o600)
        previous = {"path": str(destination), "sha256": sha256_file(destination), "backup": str(backup)}

    descriptor, temporary = tempfile.mkstemp(prefix=f".{PLUGIN_ID}.", suffix=".xpi", dir=extensions)
    os.close(descriptor)
    try:
        shutil.copyfile(xpi, temporary)
        os.chmod(temporary, 0o600)
        if sha256_file(Path(temporary)) != digest:
            raise ValueError("staged XPI hash mismatch")
        os.replace(temporary, destination)
        directory_fd = os.open(extensions, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    result = {
        "schema": "zotero-declarative-bridge-packed-install/v1",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "plugin_id": PLUGIN_ID,
        "plugin_version": manifest["version"],
        "runtime_version": runtime_version,
        "profile": str(profile),
        "profiles_ini": str(profiles_ini),
        "source_xpi": str(xpi),
        "source_xpi_sha256": digest,
        "destination": str(destination),
        "destination_sha256": sha256_file(destination),
        "previous": previous,
        "install_shape": "profile/extensions/<plugin-id>.xpi",
        "extensions_json_edited": False,
        "sqlite_edited": False,
    }
    write_private_json(receipt, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xpi", type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    result = install_packed_xpi(args.xpi, args.profile, args.receipt, args.backup_dir)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
