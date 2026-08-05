#!/usr/bin/env python3
"""Validate the schema-9 Zotero projection of a literature knowledge note.

This checks deterministic structure and notation only. It cannot validate that
the claims are entailed by the source or that locators are scientifically
correct.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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

METADATA_ONLY_REQUIRED_METADATA_LABELS = [
    "标题",
    "作者",
    "年份",
    "期刊或载体",
    "DOI或稳定标识",
    "版本与出版状态",
    "访问层级",
    "全文状态",
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
SHA_RE = re.compile(r"\b[0-9A-Fa-f]{64}\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+", re.I)
URL_RE = re.compile(r"\bhttps?://\S+", re.I)
CLAIM_ID_RE = re.compile(r"^C[1-9]\d*$")
VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
DANGEROUS_ELEMENTS = {
    "base",
    "button",
    "embed",
    "form",
    "iframe",
    "input",
    "link",
    "math",
    "meta",
    "object",
    "option",
    "script",
    "select",
    "style",
    "svg",
    "template",
    "textarea",
}
URL_ATTRIBUTES = {"action", "formaction", "href", "poster", "src", "xlink:href"}


def _validate_paper_knowledge_note(
    raw: str,
) -> tuple[list[str], list[str], dict[str, object]]:
    module_path = Path(__file__).with_name("paper_knowledge_note.py")
    spec = importlib.util.spec_from_file_location(
        "paper_knowledge_note_projection_validator",
        module_path,
    )
    if spec is None or spec.loader is None:
        return ["PN-HTML-00: cannot load PaperKnowledgeNote/v2 validator"], [], {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_rendered_html(raw)


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
        self.structural_errors: list[str] = []
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def _handle_start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> None:
        clean = {key: value or "" for key, value in attrs}
        if tag in DANGEROUS_ELEMENTS:
            self.structural_errors.append(
                f"NF-18: forbidden active or embedded element '<{tag}>'"
            )
        for key, value in clean.items():
            normalized_value = value.strip().lower()
            browser_scheme_value = re.sub(
                r"[\x00-\x20\x7f]+",
                "",
                normalized_value,
            )
            if key.startswith("on") or key == "srcdoc":
                self.structural_errors.append(
                    f"NF-18: forbidden active attribute '{key}' on '<{tag}>'"
                )
            elif key in URL_ATTRIBUTES and browser_scheme_value.startswith(
                ("javascript:", "vbscript:", "data:text/html")
            ):
                self.structural_errors.append(
                    f"NF-18: forbidden active URL in '{key}' on '<{tag}>'"
                )
            elif key == "style" and (
                "javascript:" in normalized_value
                or "expression(" in normalized_value
            ):
                self.structural_errors.append(
                    f"NF-18: forbidden active CSS on '<{tag}>'"
                )
        if not self.stack:
            self.root_tags.append((tag, clean))
        if not self_closing and tag not in VOID_ELEMENTS:
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_start(tag, attrs, self_closing=False)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._handle_start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_ELEMENTS:
            self.structural_errors.append(
                f"NF-02: void element '<{tag}>' must not have an end tag"
            )
            return
        if not self.stack:
            self.structural_errors.append(
                f"NF-02: unexpected closing tag '</{tag}>'"
            )
            return
        if self.stack[-1] != tag:
            self.structural_errors.append(
                f"NF-02: mismatched closing tag '</{tag}>'; "
                f"expected '</{self.stack[-1]}>'"
            )
            return
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
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if not self.stack and data.strip():
            self.structural_errors.append(
                "NF-02: non-whitespace text occurs outside the root element"
            )
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
    root_open = re.match(r"\s*<div\b([^>]*)>", raw, flags=re.I | re.S)
    root_access_match = (
        re.search(
            r"\bdata-access-level\s*=\s*[\"']([^\"']+)[\"']",
            root_open.group(1),
            flags=re.I,
        )
        if root_open
        else None
    )
    declared_root_access = (
        root_access_match.group(1).strip().lower() if root_access_match else None
    )
    if re.search(
        r"<div\b[^>]*\bdata-note-contract=[\"']PaperKnowledgeNote/v2[\"']",
        raw,
        flags=re.I,
    ):
        errors, warnings, summary = _validate_paper_knowledge_note(raw)
        if declared_root_access not in (None, "full_text"):
            errors.append(
                "NF-06: PaperKnowledgeNote/v2 is a full-text projection and "
                "cannot declare another data-access-level"
            )
        summary = dict(summary)
        summary.setdefault("access_level", "full_text")
        summary["root_access_level"] = declared_root_access
        return errors, warnings, summary
    errors: list[str] = []
    warnings: list[str] = []
    parser = NoteParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:
        return [f"HTML parse failure: {exc}"], warnings, {}
    errors.extend(parser.structural_errors)
    if parser.stack:
        errors.append(
            "NF-02: unclosed element stack: "
            + " > ".join(f"<{tag}>" for tag in parser.stack)
        )

    root_access_level: str | None = None
    if len(parser.root_tags) != 1:
        errors.append(f"NF-02: expected exactly one root element, found {len(parser.root_tags)}")
    elif parser.root_tags[0][0] != "div":
        errors.append("NF-02: root element must be div")
    elif parser.root_tags[0][1].get("data-schema-version") != "9":
        errors.append("NF-02: root div must have data-schema-version='9'")
    else:
        root_access_level = (
            parser.root_tags[0][1].get("data-access-level", "").strip().lower()
            or None
        )
        if root_access_level not in (None, "full_text", "metadata_only"):
            errors.append(
                "NF-06: root data-access-level must be full_text or metadata_only"
            )

    metadata_only = root_access_level == "metadata_only"

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
    # Zotero may compact source newlines while retaining semantic separators
    # such as <br>, or insert inline wrappers such as <strong>. Replace tags
    # with spaces so adjacent metadata values do not merge into one token.
    status_text = re.sub(r"<[^>]+>", " ", status_html)
    required_metadata_labels = (
        METADATA_ONLY_REQUIRED_METADATA_LABELS
        if metadata_only
        else REQUIRED_METADATA_LABELS
    )
    for label in required_metadata_labels:
        if label not in status_text:
            errors.append(f"NF-06: missing metadata label '{label}'")
    depth_matches = re.findall(r"阅读深度[：:]\s*([a-z]+)", status_text, flags=re.I)
    if not depth_matches or depth_matches[0].lower() not in READING_DEPTHS:
        errors.append("NF-07: reading depth must be map, evidence, or reconstruction")
        reading_depth = None
    else:
        reading_depth = depth_matches[0].lower()
    full_text_sha_labels = re.findall(r"全文SHA-256\s*[：:]", status_text)
    if metadata_only:
        if full_text_sha_labels or SHA_RE.search(raw):
            errors.append(
                "NF-06: metadata-only note must not contain a full-text/PDF "
                "SHA-256 or any 64-hex content hash"
            )
        full_text_sha256 = None
    else:
        full_text_sha_matches = re.findall(
            r"全文SHA-256\s*[：:]\s*([0-9a-f]{64})(?![0-9A-Fa-f])",
            status_text,
        )
        if len(full_text_sha_labels) != 1 or len(full_text_sha_matches) != 1:
            errors.append(
                "NF-06: full-text SHA-256 must occur exactly once as "
                "'全文SHA-256：' followed by 64 lowercase hex characters"
            )
            full_text_sha256 = None
        else:
            full_text_sha256 = full_text_sha_matches[0]
    access_match = re.search(
        r"访问层级[：:]\s*([a-z_]+)",
        status_text,
        flags=re.I,
    )
    access_level = access_match.group(1).lower() if access_match else None
    if metadata_only:
        if access_level != "metadata_only":
            errors.append(
                "NF-06: metadata-only root marker requires "
                "'访问层级：metadata_only'"
            )
        if reading_depth != "map":
            errors.append("NF-07: metadata-only note reading depth must be map")
        if not re.search(r"全文状态\s*[：:]\s*未获取全文", status_text):
            errors.append(
                "NF-06: metadata-only note must visibly state "
                "'全文状态：未获取全文' in 资料与阅读状态"
            )
        if re.search(
            r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
            status_html,
            flags=re.I,
        ):
            errors.append("NF-06: metadata-only full-text disclosure must not be hidden")
    elif access_level != "full_text":
        errors.append("NF-06: full-text note requires '访问层级：full_text'")
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
        if not data_rows and not metadata_only:
            errors.append("NF-08: claim table has no data rows")
        if metadata_only and data_rows:
            errors.append(
                "NF-08: metadata-only note must not contain claim data rows; "
                "full-text evidence was not acquired"
            )
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
    if metadata_only:
        if not re.search(r"元数据来源\s*[：:]\s*\S+", provenance):
            errors.append("NF-17: metadata-only provenance lacks '元数据来源：<value>'")
        if not re.search(
            r"元数据核验时间\s*[：:]\s*\d{4}-\d{2}-\d{2}",
            provenance,
        ):
            errors.append(
                "NF-17: metadata-only provenance lacks a dated "
                "'元数据核验时间：YYYY-MM-DD'"
            )
        for forbidden in ("本地PDF", "全文SHA-256", "PDF SHA-256"):
            if forbidden in provenance:
                errors.append(
                    f"NF-17: metadata-only provenance must not contain '{forbidden}'"
                )
    else:
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
        "access_level": access_level,
        "root_access_level": root_access_level,
        "note_projection": "metadata_only" if metadata_only else "full_text",
        "full_text_sha256": full_text_sha256,
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
