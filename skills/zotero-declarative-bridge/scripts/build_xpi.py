#!/usr/bin/env python3
"""Build a deterministic Zotero declarative bridge XPI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path


FILES = ("manifest.json", "bridge_core.js", "bootstrap.js")
PLUGIN_ID = "zotero-declarative-bridge@deep-research.local"
PLUGIN_VERSION = "0.1.8"
REPOSITORY_RELEASE_VERSION = "0.6.9"
RELEASE_TAG = f"v{REPOSITORY_RELEASE_VERSION}"
XPI_FILENAME = f"zotero-declarative-bridge-{PLUGIN_VERSION}.xpi"
XPI_SHA256 = "7010a524994caf115d8deb208ac529989789e804017bd18c2613fce710b8d79c"
PLUGIN_UPDATE_URL = (
    "https://raw.githubusercontent.com/kl3574/deep-research/main/skills/"
    "zotero-declarative-bridge/assets/zotero-plugin/updates.json"
)
EXPECTED_UPDATE_LINK = (
    f"https://github.com/kl3574/deep-research/releases/download/{RELEASE_TAG}/"
    f"{XPI_FILENAME}"
)
EXPECTED_UPDATE_HASH = f"sha256:{XPI_SHA256}"


def validate_update_manifest(plugin_root: Path, manifest: dict[str, object]) -> str:
    update_path = plugin_root / "updates.json"
    try:
        update_manifest = json.loads(update_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid external update manifest: {exc}") from exc
    if not isinstance(update_manifest, dict) or set(update_manifest) != {"addons"}:
        raise ValueError("external update manifest must contain only an addons object")
    addons = update_manifest["addons"]
    if not isinstance(addons, dict) or set(addons) != {PLUGIN_ID}:
        raise ValueError("external update manifest must contain only the reviewed plugin ID")
    addon = addons[PLUGIN_ID]
    if not isinstance(addon, dict) or set(addon) != {"updates"}:
        raise ValueError("external update manifest plugin entry must contain only updates")
    updates = addon["updates"]
    if not isinstance(updates, list):
        raise ValueError("external update manifest updates must be a list")
    if any(not isinstance(entry, dict) for entry in updates):
        raise ValueError("external update manifest update entries must be objects")
    matches = [entry for entry in updates if entry.get("version") == PLUGIN_VERSION]
    if len(matches) != 1:
        raise ValueError("external update manifest must contain one current version")
    entry = matches[0]
    app = manifest["applications"]["zotero"]
    expected = {
        "version": PLUGIN_VERSION,
        "update_link": EXPECTED_UPDATE_LINK,
        "update_hash": EXPECTED_UPDATE_HASH,
        "applications": {
            "zotero": {
                "strict_min_version": app["strict_min_version"],
                "strict_max_version": app["strict_max_version"],
            }
        },
    }
    if set(entry) != set(expected):
        raise ValueError("external update manifest current entry fields do not match the release contract")
    if entry["update_link"] != EXPECTED_UPDATE_LINK:
        raise ValueError("external update manifest release tag and asset do not match the release contract")
    if entry["update_hash"] != EXPECTED_UPDATE_HASH:
        raise ValueError("external update manifest XPI hash does not match the release contract")
    if entry["applications"] != expected["applications"]:
        raise ValueError("external update manifest compatibility does not match the plugin manifest")
    return entry["update_hash"]


def build(output: Path, plugin_root: Path) -> str:
    output = output.expanduser().resolve()
    plugin_root = plugin_root.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise ValueError(f"refusing to overwrite {output}")
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))
    app = manifest.get("applications", {}).get("zotero", {})
    if manifest.get("manifest_version") != 2:
        raise ValueError("Zotero 9 plugin manifest_version must be 2")
    if manifest.get("version") != PLUGIN_VERSION:
        raise ValueError(f"plugin version must be {PLUGIN_VERSION}")
    if app.get("id") != PLUGIN_ID:
        raise ValueError("plugin ID mismatch")
    if app.get("update_url") != PLUGIN_UPDATE_URL:
        raise ValueError("plugin update URL must match the reviewed public HTTPS manifest")
    if app.get("strict_min_version") != "9.0" or app.get("strict_max_version") != "9.0.*":
        raise ValueError("plugin compatibility must remain pinned to Zotero 9.0.*")
    expected_hash = validate_update_manifest(plugin_root, manifest)
    bootstrap = (plugin_root / "bootstrap.js").read_text(encoding="utf-8")
    for hook in ("function startup(", "function shutdown(", "function install(", "function uninstall("):
        if hook not in bootstrap:
            raise ValueError(f"missing Zotero bootstrap lifecycle hook: {hook}")
    if "unsupported Zotero runtime" not in bootstrap or "Zotero.logError(error)" not in bootstrap:
        raise ValueError("bootstrap must retain the runtime guard and startup error logging")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in FILES:
            data = (plugin_root / name).read_bytes()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, data)
    os.chmod(output, 0o600)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    if f"sha256:{digest}" != expected_hash:
        output.unlink()
        raise ValueError("built XPI hash does not match the external update manifest")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets" / "zotero-plugin",
    )
    args = parser.parse_args()
    digest = build(args.output, args.plugin_root)
    print(json.dumps({"status": "built", "output": str(args.output.resolve()), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
