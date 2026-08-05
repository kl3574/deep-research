#!/usr/bin/env python3
"""Refuse unsupported packed-XPI profile copying.

Packed XPIs are installation artifacts for Zotero's visible Plugins UI. This
compatibility guard exists so an old automation command cannot claim that a
filesystem copy registered or activated an add-on.
"""

from __future__ import annotations

import argparse
import sys


OFFICIAL_INSTALL_URL = "https://www.zotero.org/support/plugins"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xpi")
    parser.add_argument("--profile")
    parser.add_argument("--receipt")
    parser.add_argument("--backup-dir")
    return parser.parse_args()


def main() -> int:
    parse_args()
    print(
        "refusing direct profile copy: install the reviewed XPI through "
        f"Zotero Tools -> Plugins ({OFFICIAL_INSTALL_URL}); the stable skill "
        "does not modify profile discovery preferences",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
