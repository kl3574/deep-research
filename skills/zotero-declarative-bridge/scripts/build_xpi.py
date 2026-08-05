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
PLUGIN_VERSION = "0.1.1"


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
    if app.get("strict_min_version") != "9.0" or app.get("strict_max_version") != "9.0.*":
        raise ValueError("plugin compatibility must remain pinned to Zotero 9.0.*")
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
    return hashlib.sha256(output.read_bytes()).hexdigest()


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
