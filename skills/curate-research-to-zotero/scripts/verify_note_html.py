#!/usr/bin/env python3
"""Validate the schema-9 Zotero projection of a literature knowledge note.

This checks deterministic structure and notation only. It cannot validate that
the claims are entailed by the source or that locators are scientifically
correct.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_IO = 2

REQUIRED_SECTIONS = [
    "资料与阅读状态",
    "为什么重要",
    "一句话结论",
    "心智模型",
    "关键主张与证据",
    "方法或推导",
    "结果",
    "假设、失败边界与竞争解释",
    "知识图谱关系",
    "复用",
    "溯源",
]

REQUIRED_METADATA_LABELS = [
    "标题",
    "作者",
    "年份",
    "期刊或载体",
    "DOI或稳定标识",
    "版本与出版状态",
    "访问层级",
    "全文SHA-256",
    "阅读深度",
    "核验时间",
]

CLAIM_HEADERS = [
    "Claim ID",
    "性质",
    "主张",
    "证据与精确定位",
    "条件",
    "置信度与理由",
]

CLAIM_NATURES = {
    "source-stated",
    "agent-inferred",
    "externally-supported",
    "unresolved",
}

CONFIDENCE_LEVELS = {"high", "medium", "low"}
READING_DEPTHS = {"map", "evidence", "reconstruction"}
FORBIDDEN_MATH_GLYPHS = ("Ẋ", "Θ", "Ξ", "²", "³", "‖")
CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
SHA_RE = re.compile(r"\b[0-9a-f]{64}\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+", re.I)
URL_RE = re.compile(r"\bhttps?://\S+", re.I)
CLAIM_ID_RE = re.compile(r"^C[1-9]\d*$")


class NoteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.root_tags: list[tuple[str, dict[str, str]]] = []
        self.h1: list[str] = []
        self.h2: list[str] = []
        self.rows: list[list[str]] = []
        self.math_blocks: list[str] = []
        self.paragraphs: list[str] = []
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        clean = {key: value or "" for key, value in attrs}
        if not self.stack:
            self.root_tags.append((tag, clean))
        self.stack.append(tag)
        if tag in {"h1", "h2", "p"}:
            self._capture = tag
            self._buffer = []
        elif tag == "pre" and "math" in clean.get("class", "").split():
            self._capture = "math"
            self._buffer = []
        elif tag == "tr":
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        text = " ".join("".join(self._buffer).split())
        if tag == "h1" and self._capture == "h1":
            self.h1.append(text)
            self._capture = None
        elif tag == "h2" and self._capture == "h2":
            self.h2.append(text)
            self._capture = None
        elif tag == "p" and self._capture == "p":
            self.paragraphs.append(text)
            self._capture = None
        elif tag == "pre" and self._capture == "math":
            self.math_blocks.append("".join(self._buffer).strip())
            self._capture = None
        elif tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buffer.append(data)
        if self._cell is not None:
            self._cell.append(data)


def sha256sum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section_text(raw: str, heading: str) -> str:
    match = re.search(
        rf"<h2\b[^>]*>\s*{re.escape(heading)}\s*</h2>(.*?)(?=<h2\b|</div>\s*$)",
        raw,
        flags=re.I | re.S,
    )
    return match.group(1) if match else ""


def validate_note(raw: str) -> tuple[list[str], list[str], dict[str, object]]:
    errors: list[str] = []
    warnings: list[str] = []
    parser = NoteParser()
    try:
        parser.feed(raw)
    except Exception as exc:
        return [f"HTML parse failure: {exc}"], warnings, {}

    if len(parser.root_tags) != 1:
        errors.append(f"NF-02: expected exactly one root element, found {len(parser.root_tags)}")
    elif parser.root_tags[0][0] != "div":
        errors.append("NF-02: root element must be div")
    elif parser.root_tags[0][1].get("data-schema-version") != "9":
        errors.append("NF-02: root div must have data-schema-version='9'")

    if len(parser.h1) != 1 or not parser.h1[0]:
        errors.append(f"NF-02: expected one non-empty h1, found {len(parser.h1)}")

    positions: list[int] = []
    for section in REQUIRED_SECTIONS:
        if section not in parser.h2:
            errors.append(f"NF-03: missing section '{section}'")
        else:
            positions.append(parser.h2.index(section))
            text = re.sub(r"<[^>]+>", " ", section_text(raw, section))
            if not CHINESE_RE.search(text):
                errors.append(f"NF-05: section '{section}' contains no Chinese explanatory text")
    if positions and positions != sorted(positions):
        errors.append("NF-03: required sections are not in contract order")

    status_html = section_text(raw, "资料与阅读状态")
    status_text = re.sub(r"<[^>]+>", "", status_html)
    for label in REQUIRED_METADATA_LABELS:
        if label not in status_text:
            errors.append(f"NF-06: missing metadata label '{label}'")
    depth_matches = re.findall(r"阅读深度[：:]\s*([a-z]+)", status_text, flags=re.I)
    if not depth_matches or depth_matches[0].lower() not in READING_DEPTHS:
        errors.append("NF-07: reading depth must be map, evidence, or reconstruction")
        reading_depth = None
    else:
        reading_depth = depth_matches[0].lower()
    if "全文SHA-256" in status_text and not SHA_RE.search(status_text.lower()):
        errors.append("NF-06: full-text SHA-256 must be 64 lowercase hex characters")
    if "DOI或稳定标识" in status_text and not (
        DOI_RE.search(status_text) or URL_RE.search(status_text) or "unresolved" in status_text
    ):
        errors.append("NF-06: DOI/stable identifier is missing or malformed")

    claim_parser = NoteParser()
    claim_parser.feed(section_text(raw, "关键主张与证据"))
    claim_rows = [row for row in claim_parser.rows if row]
    header_index = next(
        (idx for idx, row in enumerate(claim_rows) if row == CLAIM_HEADERS),
        None,
    )
    if header_index is None:
        errors.append("NF-08: exact claim-table header is missing")
        data_rows: list[list[str]] = []
    else:
        data_rows = claim_rows[header_index + 1 :]
        if not data_rows:
            errors.append("NF-08: claim table has no data rows")
    seen_claim_ids: set[str] = set()
    for idx, row in enumerate(data_rows, start=1):
        if len(row) != len(CLAIM_HEADERS):
            errors.append(f"NF-08: claim row {idx} must contain six cells")
            continue
        claim_id, nature, claim, locator, conditions, confidence = row
        if not CLAIM_ID_RE.fullmatch(claim_id):
            errors.append(f"NF-08: invalid Claim ID '{claim_id}'")
        elif claim_id in seen_claim_ids:
            errors.append(f"NF-08: duplicate Claim ID '{claim_id}'")
        seen_claim_ids.add(claim_id)
        if nature not in CLAIM_NATURES:
            errors.append(f"NF-09: unsupported claim nature '{nature}'")
        if not claim or not CHINESE_RE.search(claim):
            errors.append(f"NF-08: {claim_id or idx} claim must contain Chinese text")
        if not locator or not re.search(
            r"(p\.?\s*\d+|页\s*\d+|PDF\s*(?:实体)?页\s*\d+|Eq\.|Fig\.|Table|§|unresolved)",
            locator,
            flags=re.I,
        ):
            errors.append(f"NF-08: {claim_id or idx} lacks an exact locator")
        if not conditions:
            errors.append(f"NF-08: {claim_id or idx} lacks conditions")
        level_match = re.match(r"^(high|medium|low)\s*[：:—-]\s*(.+)$", confidence, flags=re.I)
        if not level_match or level_match.group(1).lower() not in CONFIDENCE_LEVELS:
            errors.append(f"NF-10: {claim_id or idx} confidence needs level and rationale")
        elif not CHINESE_RE.search(level_match.group(2)):
            errors.append(f"NF-10: {claim_id or idx} confidence rationale must be explanatory")

    for glyph in FORBIDDEN_MATH_GLYPHS:
        if glyph in raw:
            errors.append(f"NF-13: forbidden Unicode math substitute '{glyph}'")
    raw_math_matches = list(
        re.finditer(
            r"<pre\b[^>]*class=[\"'][^\"']*\bmath\b[^\"']*[\"'][^>]*>.*?</pre>",
            raw,
            flags=re.I | re.S,
        )
    )
    for idx, math in enumerate(parser.math_blocks, start=1):
        if not (math.startswith("$$") and math.endswith("$$")):
            errors.append(f"NF-12: math block {idx} must be wrapped in $$...$$")
        if idx <= len(raw_math_matches):
            start = raw_math_matches[idx - 1].end()
            later = raw[start:]
            end_match = re.search(r"<pre\b|<h2\b", later, flags=re.I)
            following_raw = later[: end_match.start()] if end_match else later
        else:
            following_raw = ""
        following = re.sub(r"<[^>]+>", " ", following_raw)
        for label in ("符号", "作用", "假设", "定位"):
            if label not in following:
                errors.append(f"NF-14: math block {idx} lacks following '{label}'")

    if reading_depth == "reconstruction":
        if "完整性与纠错日志" not in parser.h2:
            errors.append("NF-04: reconstruction note needs '完整性与纠错日志'")
        completeness = section_text(raw, "完整性与纠错日志")
        completeness_text = re.sub(r"<[^>]+>", " ", completeness)
        for required in (
            "总页数",
            "主文与补充材料",
            "图表公式盘点",
            "初始理解",
            "源文复核",
            "修正及影响",
            "未解决项",
        ):
            if required not in completeness_text:
                errors.append(f"NF-15/16: reconstruction log lacks '{required}'")

    provenance = re.sub(r"<[^>]+>", " ", section_text(raw, "溯源"))
    for required in ("证据账本", "本地PDF", "SHA-256", "Agent推断"):
        if required not in provenance:
            errors.append(f"NF-17: provenance lacks '{required}'")

    summary = {
        "schema_version": "9" if not parser.root_tags else parser.root_tags[0][1].get("data-schema-version"),
        "title": parser.h1[0] if parser.h1 else None,
        "sections": parser.h2,
        "claim_ids": sorted(seen_claim_ids),
        "math_block_count": len(parser.math_blocks),
        "reading_depth": reading_depth,
    }
    if not parser.math_blocks:
        warnings.append("No display-math block present; acceptable only when the source note needs no display equation")
    return errors, warnings, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("note", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        raw = args.note.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"note read error: {exc}", file=sys.stderr)
        return EXIT_IO
    if not raw.strip():
        print("note is empty", file=sys.stderr)
        return EXIT_VALIDATION

    digest = sha256sum(args.note)
    errors, warnings, summary = validate_note(raw)
    if args.expected_sha256 and digest.lower() != args.expected_sha256.lower():
        errors.append(
            f"NF-01: SHA-256 mismatch expected={args.expected_sha256.lower()} actual={digest}"
        )

    payload = {
        "status": "ok" if not errors else "fail",
        "sha256": digest,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for warning in warnings:
            print(f"WARN: {warning}", file=sys.stderr)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"{payload['status']}: {args.note} sha256={digest}")
    return EXIT_OK if not errors else EXIT_VALIDATION


if __name__ == "__main__":
    raise SystemExit(main())
