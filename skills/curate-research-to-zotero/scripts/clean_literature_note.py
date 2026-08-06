#!/usr/bin/env python3
"""Render and validate clean schema-9 Zotero literature-note HTML."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


CONTRACT = "ZoteroCleanLiteratureNote/v1"
EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_IO = 2
FORMULA_TAGS = {"span": "inline", "pre": "display"}
DANGEROUS_TAGS = {
    "base", "embed", "form", "iframe", "input", "link", "math", "meta",
    "object", "script", "style", "svg", "template",
}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "source", "track", "wbr",
}
ROOT_ATTRIBUTES = {"data-schema-version", "data-citation-items"}
ENTITY_LITERAL_RE = re.compile(
    r"&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-f]+);", re.I
)
DOUBLE_COMMAND_RE = re.compile(
    r"\\\\(?:begin|end|frac|sqrt|sum|prod|operatorname|mathrm|mathbf|mathbb|"
    r"mathcal|text|tag|left|right|partial|nabla|dot|bar|hat|mid|le|ge)\b"
)
PLAIN_DISPLAY_RE = re.compile(r"(?<!\\)\$\$[^$]+\$\$")
PLAIN_INLINE_RE = re.compile(r"(?<![\\$])\$(?!\$)[^$\n]+(?<!\\)\$(?!\$)")
SHA256_RE = re.compile(r"\b(?:sha256:)?[0-9a-f]{64}\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?:file://|(?<![\w.-])/(?:home|Users|private|tmp)/|"
    r"(?<![\w.-])[A-Za-z]:[\\/]|\\\\[^\\\s]+[\\/])"
)
TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
    r"(?:Z|[+-]\d{2}:\d{2})\b"
)
OPERATIONAL_RE = re.compile(
    r"(?:\b(?:run|transaction|draft|review|apply|readback|workflow)[ _-]?"
    r"(?:id|status)\b|\b(?:content|source|manifest|projection)[ _-]?sha256\b|"
    r"\b(?:generated|updated|reviewed|applied)[ _-]?at\b|\btool[ _-]?version\b|"
    r"运行ID|事务ID|草稿状态|审核状态|写入状态|回读状态|工作流状态|"
    r"生成时间|核验时间|工具版本|本地路径|全文SHA-?256|资料与阅读状态|"
    r"阅读深度[：:]|访问层级[：:]|全文状态[：:])",
    re.I,
)


def _attrs_dict(
    attrs: list[tuple[str, str | None]],
) -> tuple[dict[str, str], bool]:
    result: dict[str, str] = {}
    duplicate = False
    for key, value in attrs:
        key = key.lower()
        duplicate = duplicate or key in result
        result[key] = value or ""
    return result, duplicate


class CleanNoteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.roots: list[tuple[str, dict[str, str]]] = []
        self.errors: list[str] = []
        self.formulas: list[dict[str, str]] = []
        self._math: dict[str, Any] | None = None
        self.outside_text: list[str] = []
        self.h1_depth = 0
        self.h1_text: list[str] = []
        self.h1_count = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        clean, duplicate = _attrs_dict(attrs)
        if duplicate:
            self.errors.append(f"CN-02: duplicate attribute on <{tag}>")
        if tag in DANGEROUS_TAGS:
            self.errors.append(f"CN-03: forbidden element <{tag}>")
        for key, value in clean.items():
            normalized = re.sub(r"[\x00-\x20\x7f]+", "", value.lower())
            if key.startswith("on") or key == "srcdoc":
                self.errors.append(f"CN-03: forbidden active attribute {key}")
            if normalized.startswith(
                ("javascript:", "vbscript:", "data:text/html")
            ):
                self.errors.append(
                    f"CN-03: forbidden active attribute value in {key}"
                )
        if not self.stack:
            self.roots.append((tag, clean))
        if tag == "div" and "zotero-note" in clean.get("class", "").split():
            self.errors.append(
                "CN-02: omit Zotero's outer zotero-note wrapper"
            )

        math_class = "math" in clean.get("class", "").split()
        if self._math is not None:
            self.errors.append("CN-07: math nodes must contain text only")
        if math_class:
            if tag not in FORMULA_TAGS:
                self.errors.append(
                    "CN-07: class=math is allowed only on span or pre"
                )
            else:
                if set(clean) != {"class"} or clean["class"].split() != ["math"]:
                    self.errors.append(
                        "CN-07: math nodes cannot carry IDs or extra attributes"
                    )
                kind = FORMULA_TAGS[tag]
                if kind == "inline" and (
                    not self.stack or self.stack[-1] != "p"
                ):
                    self.errors.append(
                        "CN-07: inline math must be a direct child of p"
                    )
                headings = {"p", "h1", "h2", "h3", "h4", "h5", "h6"}
                if kind == "display" and any(
                    ancestor in headings for ancestor in self.stack
                ):
                    self.errors.append(
                        "CN-07: display math cannot be nested in prose or headings"
                    )
                self._math = {"tag": tag, "kind": kind, "parts": []}
        if tag == "h1":
            self.h1_count += 1
            self.h1_depth = len(self.stack) + 1
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            self.errors.append(f"CN-02: void element </{tag}> cannot close")
            return
        if not self.stack or self.stack[-1] != tag:
            expected = self.stack[-1] if self.stack else "none"
            self.errors.append(
                f"CN-02: mismatched </{tag}>; expected </{expected}>"
            )
            return
        if self._math is not None and self._math["tag"] == tag:
            self.formulas.append(
                {
                    "kind": self._math["kind"],
                    "text": "".join(self._math["parts"]),
                }
            )
            self._math = None
        self.stack.pop()
        if tag == "h1":
            self.h1_depth = 0

    def handle_data(self, data: str) -> None:
        if self._math is not None:
            self._math["parts"].append(data)
        else:
            self.outside_text.append(data)
        if self.h1_depth:
            self.h1_text.append(data)
        if not self.stack and data.strip():
            self.errors.append("CN-02: text occurs outside the root element")


def _latex_payload_error(payload: str) -> str | None:
    if not payload or payload != payload.strip():
        return "formula payload must be non-empty and storage-trimmed"
    if ENTITY_LITERAL_RE.search(payload):
        return "formula payload contains a still-escaped HTML entity"
    if DOUBLE_COMMAND_RE.search(payload):
        return "formula payload contains a double-escaped LaTeX command"
    return None


def _parse_formulas(raw: str) -> tuple[CleanNoteParser, list[str]]:
    parser = CleanNoteParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:  # pragma: no cover
        parser.errors.append(f"CN-02: HTML parse failure: {exc}")
    if parser.stack:
        parser.errors.append(
            "CN-02: unclosed elements: " + " > ".join(parser.stack)
        )
    if parser._math is not None:
        parser.errors.append("CN-07: unclosed math node")

    payload_errors: list[str] = []
    for index, formula in enumerate(parser.formulas, start=1):
        text = formula["text"]
        if formula["kind"] == "inline":
            if not (
                text.startswith("$")
                and text.endswith("$")
                and not text.startswith("$$")
                and not text.endswith("$$")
            ):
                payload_errors.append(
                    f"CN-08: inline formula {index} must have exactly one "
                    "$ delimiter pair"
                )
                continue
            payload = text[1:-1]
        else:
            if not (text.startswith("$$") and text.endswith("$$")):
                payload_errors.append(
                    f"CN-08: display formula {index} must have a $$ delimiter pair"
                )
                continue
            payload = text[2:-2]
        error = _latex_payload_error(payload)
        if error:
            payload_errors.append(f"CN-09: formula {index} {error}")
        formula["payload"] = unicodedata.normalize("NFC", payload)
    return parser, payload_errors


def extract_formula_sequence(raw: str) -> list[dict[str, str]]:
    """Return ordered formula kind/payload pairs or raise on malformed math."""
    parser, payload_errors = _parse_formulas(raw)
    math_errors = [
        error for error in parser.errors if error.startswith("CN-07")
    ]
    errors = math_errors + payload_errors
    if errors:
        raise ValueError("; ".join(errors))
    return [
        {"kind": formula["kind"], "payload": formula["payload"]}
        for formula in parser.formulas
        if "payload" in formula
    ]


def validate_clean_note_html(
    raw: str,
) -> tuple[list[str], list[str], dict[str, object]]:
    """Validate content hygiene, not scientific entailment."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw, str) or not raw:
        return ["CN-01: note HTML must be a non-empty string"], warnings, {}
    if raw != raw.strip():
        errors.append("CN-01: note HTML must be storage-trimmed")

    parser, payload_errors = _parse_formulas(raw)
    errors.extend(parser.errors)
    errors.extend(payload_errors)
    if len(parser.roots) != 1:
        errors.append(
            f"CN-02: expected one root element, found {len(parser.roots)}"
        )
    else:
        tag, attrs = parser.roots[0]
        if tag != "div":
            errors.append("CN-02: root element must be div")
        if attrs.get("data-schema-version") != "9":
            errors.append(
                "CN-02: clean math-capable note requires data-schema-version=9"
            )
        unknown = sorted(set(attrs) - ROOT_ATTRIBUTES)
        if unknown:
            errors.append(
                f"CN-04: root has unsupported attributes: {unknown}"
            )
    if parser.h1_count != 1 or not "".join(parser.h1_text).strip():
        errors.append("CN-05: expected exactly one non-empty h1")

    for part in parser.outside_text:
        if PLAIN_DISPLAY_RE.search(part) or PLAIN_INLINE_RE.search(part):
            errors.append(
                "CN-06: plain-dollar formula occurs outside a Zotero math node"
            )
            break

    visible = "\n".join(parser.outside_text)
    checks = (
        (SHA256_RE, "CN-10: hash must live outside literature HTML"),
        (LOCAL_PATH_RE, "CN-10: local path must live outside literature HTML"),
        (TIMESTAMP_RE, "CN-10: timestamp must live outside literature HTML"),
        (OPERATIONAL_RE, "CN-10: workflow state must live outside literature HTML"),
    )
    for pattern, message in checks:
        if pattern.search(visible):
            errors.append(message)

    formulas = [
        {"kind": formula["kind"], "payload": formula.get("payload")}
        for formula in parser.formulas
    ]
    return errors, warnings, {
        "contract": CONTRACT,
        "schema_version": "9",
        "formula_count": len(formulas),
        "formulas": formulas,
    }


def compare_formula_roundtrip(
    expected_html: str, observed_html: str
) -> list[str]:
    """Compare ordered, decoded, NFC-normalized math payloads."""
    try:
        expected = extract_formula_sequence(expected_html)
    except ValueError as exc:
        return [f"CN-RT-01: expected HTML has invalid math: {exc}"]
    try:
        observed = extract_formula_sequence(observed_html)
    except ValueError as exc:
        return [f"CN-RT-02: observed HTML has invalid math: {exc}"]
    if expected != observed:
        return [
            "CN-RT-03: formula kind/order/payload changed during roundtrip"
        ]
    return []


def _render_math(latex: str, *, display: bool) -> str:
    if not isinstance(latex, str):
        raise TypeError("latex must be a string")
    error = _latex_payload_error(latex)
    if error:
        raise ValueError(error)
    if re.search(r"(?<!\\)\$", latex):
        raise ValueError("pass raw LaTeX without math delimiters")
    escaped = html.escape(latex, quote=False)
    if display:
        return f'<pre class="math">$${escaped}$$</pre>'
    return f'<span class="math">${escaped}$</span>'


def render_inline_math(latex: str) -> str:
    return _render_math(latex, display=False)


def render_display_math(latex: str) -> str:
    return _render_math(latex, display=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("html", type=Path)
    roundtrip = subparsers.add_parser("roundtrip")
    roundtrip.add_argument("expected", type=Path)
    roundtrip.add_argument("observed", type=Path)
    for command in ("inline", "display"):
        render = subparsers.add_parser(command)
        render.add_argument("latex")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            errors, warnings, summary = validate_clean_note_html(
                args.html.read_text(encoding="utf-8")
            )
        elif args.command == "roundtrip":
            errors = compare_formula_roundtrip(
                args.expected.read_text(encoding="utf-8"),
                args.observed.read_text(encoding="utf-8"),
            )
            warnings, summary = [], {"contract": CONTRACT}
        else:
            renderer = (
                render_inline_math
                if args.command == "inline"
                else render_display_math
            )
            print(renderer(args.latex))
            return EXIT_OK
    except (OSError, UnicodeError) as exc:
        print(json.dumps({"status": "io_error", "error": str(exc)}))
        return EXIT_IO
    print(
        json.dumps(
            {
                "status": "valid" if not errors else "invalid",
                "errors": errors,
                "warnings": warnings,
                "summary": summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return EXIT_OK if not errors else EXIT_VALIDATION


if __name__ == "__main__":
    sys.exit(main())
