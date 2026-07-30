#!/usr/bin/env python3
"""Reject private Zotero artifacts and identifiers from the public Git tree."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable


ZOTERO_KEY_RE = re.compile(r"[A-Z0-9]{8}")
ZOTERO_KEY_TOKEN_RE = re.compile(r"(?<![A-Z0-9])[A-Z0-9]{8}(?![A-Z0-9])")
DATED_STAGING_RE = re.compile(
    r"zotero-(?:all-notes|note-migration)-\d{4}-\d{2}-\d{2}"
)
PRIVATE_NOTE_PATH_RE = re.compile(
    r"(?:overrides|originals|updated)/[A-Z0-9]{8}(?:\.create)?\.html"
)
PRIVATE_HOME_RE = re.compile(r"/(?:home|Users)/(?!user(?:name)?/|test(?:er)?/)[^/\s]+/")
GROUP_ID_RE = re.compile(
    r"(?:group[_-]?id|groupID|--group-id)[^0-9]{0,20}([1-9][0-9]{5,})",
    re.IGNORECASE,
)
KEY_ENTITY = r"(?:collection|note|parent|attachment|item|pdf(?:[_-]?attachment)?)"
KEY_FIELD = rf"{KEY_ENTITY}(?:[_-]?keys?)"
KEY_ASSIGNMENT_RE = re.compile(
    rf"\b(?i:{KEY_FIELD})\b(?:\s*:\s*[^=\n]{{1,40}})?"
    r"\s*=\s*[\"']([A-Z0-9]{8})[\"'](?![A-Z0-9])",
)
KEY_COLON_RE = re.compile(
    rf"(?<![A-Za-z0-9_])[\"']?(?i:{KEY_FIELD})[\"']?\s*:\s*"
    r"[\"']?([A-Z0-9]{8})[\"']?(?![A-Z0-9])",
)
KEY_ARRAY_RE = re.compile(
    rf"(?<![A-Za-z0-9_])[\"']?(?i:{KEY_ENTITY}(?:[_-]?keys))[\"']?"
    r"\s*(?::|=)\s*\[([^\]]{0,20000})\]",
    re.DOTALL,
)

SYNTHETIC_GROUP_IDS = {"123456", "1234567", "999999"}
SYNTHETIC_KEY_PREFIXES = (
    "TEST",
    "NOTE",
    "PARENT",
    "PDFATT",
    "ATT",
    "COLL",
    "LEAF",
    "ROOT",
    "OTHER",
    "NEWNOTE",
    "NOOP",
    "STAGE",
    "CREATED",
    "UPDATE",
    "FINAL",
    "TYPO",
    "ITEM",
    "CHILD",
)
SYNTHETIC_KEY_EXACT = {"ABCDEFGH", "HGFEDCBA", "C1234567"}
PRIVATE_TEXT_FIELDS = {"libraryname", "collectionname", "collectionpath"}

BANNED_SUFFIXES = {".pdf", ".bib", ".bibtex", ".ris", ".enw", ".html"}
BANNED_BASENAME_PATTERNS = (
    re.compile(r"migration_manifest.*\.json"),
    re.compile(r"zotero_desktop_.*_report\.json"),
    re.compile(r"parent-note-map.*\.json"),
    re.compile(r"pdf-attachment-map.*\.json"),
)
BANNED_DIRECTORY_PREFIXES = ("zotero-all-notes-", "zotero-note-migration-")


def tracked_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [
        Path(value.decode("utf-8"))
        for value in result.stdout.split(b"\0")
        if value
    ]


def _is_synthetic_key(value: str) -> bool:
    return value in SYNTHETIC_KEY_EXACT or value.startswith(
        SYNTHETIC_KEY_PREFIXES
    )


def _path_issue(path: Path) -> str | None:
    if path.suffix.lower() in BANNED_SUFFIXES:
        return f"tracked private-artifact extension: {path.suffix.lower()}"
    if any(pattern.fullmatch(path.name) for pattern in BANNED_BASENAME_PATTERNS):
        return "tracked Zotero migration artifact"
    if any(
        part.startswith(prefix)
        for part in path.parts
        for prefix in BANNED_DIRECTORY_PREFIXES
    ):
        return "tracked private Zotero staging directory"
    return None


def _collect_private_tokens(value: object, key_hint: str = "") -> set[str]:
    tokens: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            tokens.update(_collect_private_tokens(child, str(key)))
    elif isinstance(value, list):
        for child in value:
            tokens.update(_collect_private_tokens(child, key_hint))
    elif isinstance(value, str):
        if ZOTERO_KEY_RE.fullmatch(value):
            tokens.add(value)
        if "group" in key_hint.lower() and "id" in key_hint.lower():
            if value.isdigit() and len(value) >= 6:
                tokens.add(value)
        normalized_hint = re.sub(r"[^a-z0-9]", "", key_hint.lower())
        if normalized_hint in PRIVATE_TEXT_FIELDS and value.strip():
            tokens.add(value.strip())
    elif isinstance(value, int):
        if "group" in key_hint.lower() and "id" in key_hint.lower():
            tokens.add(str(value))
    return tokens


def private_tokens_from_json(paths: Iterable[Path]) -> set[str]:
    tokens: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        tokens.update(_collect_private_tokens(payload))
    return tokens


def _text_issues(text: str, private_tokens: set[str]) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    lines = text.splitlines()
    for line_number, line in enumerate(lines, 1):
        if PRIVATE_HOME_RE.search(line):
            issues.append((line_number, "private absolute home path"))
        if DATED_STAGING_RE.search(line):
            issues.append((line_number, "dated private Zotero staging path"))
        if PRIVATE_NOTE_PATH_RE.search(line):
            issues.append((line_number, "private-style Zotero note filename"))
        for match in GROUP_ID_RE.finditer(line):
            if match.group(1) not in SYNTHETIC_GROUP_IDS:
                issues.append((line_number, "non-synthetic Zotero group ID"))
        for pattern in (KEY_ASSIGNMENT_RE, KEY_COLON_RE):
            for match in pattern.finditer(line):
                if not _is_synthetic_key(match.group(1).upper()):
                    issues.append((line_number, "non-synthetic Zotero item key"))

    for array_match in KEY_ARRAY_RE.finditer(text):
        array_body = array_match.group(1)
        for key_match in ZOTERO_KEY_TOKEN_RE.finditer(array_body):
            key = key_match.group(0)
            if _is_synthetic_key(key.upper()):
                continue
            offset = array_match.start(1) + key_match.start()
            line_number = text.count("\n", 0, offset) + 1
            issues.append((line_number, "non-synthetic Zotero item key"))

    for token in private_tokens:
        offset = text.find(token)
        if offset >= 0:
            line_number = text.count("\n", 0, offset) + 1
            issues.append((line_number, "identifier found in private JSON input"))
    return sorted(set(issues))


def scan_tracked_tree(
    root: Path,
    paths: Iterable[Path],
    private_tokens: set[str] | None = None,
) -> list[str]:
    private_tokens = private_tokens or set()
    findings: list[str] = []
    for relative_path in paths:
        path_issue = _path_issue(relative_path)
        if path_issue:
            findings.append(f"{relative_path}: {path_issue}")
            continue

        absolute_path = root / relative_path
        try:
            text = absolute_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, issue in _text_issues(text, private_tokens):
            findings.append(f"{relative_path}:{line_number}: {issue}")
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the tracked public tree for private Zotero artifacts."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--private-json",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional private manifest/report used only to derive an in-memory "
            "denylist; may be repeated."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    private_json_paths = list(args.private_json)
    private_json_paths.extend(
        Path(value)
        for value in os.environ.get(
            "DEEP_RESEARCH_PRIVATE_JSONS", ""
        ).split(os.pathsep)
        if value
    )
    private_tokens = private_tokens_from_json(private_json_paths)
    findings = scan_tracked_tree(root, tracked_paths(root), private_tokens)
    if findings:
        print("Public-tree privacy check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "Public-tree privacy check passed "
        f"({len(private_tokens)} private identifiers checked in memory)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
