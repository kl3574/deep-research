#!/usr/bin/env python3
"""Focused tests for clean Zotero literature-note HTML."""

from __future__ import annotations

import unittest

import clean_literature_note as clean


def note(body: str) -> str:
    return (
        '<div data-schema-version="9"><h1>适用场景与结论</h1>'
        + body
        + "</div>"
    )


class CleanLiteratureNoteTests(unittest.TestCase):
    def assert_invalid(self, raw: str, code: str) -> None:
        errors, _, _ = clean.validate_clean_note_html(raw)
        self.assertTrue(any(error.startswith(code) for error in errors), errors)

    def test_accepts_math_locators_and_natural_language_limitations(self) -> None:
        raw = note(
            '<p>当输入独立时，指标 <span class="math">$S_i=V_i/V$</span> '
            "用于排序。证据定位：p. 12，Eq. (3)。</p>"
            '<pre class="math">$$S_{T_i}=1-V_{\\sim i}/V$$</pre>'
            "<p>局限：该结论仅由摘要支持，尚未核对补充材料。</p>"
        )
        errors, warnings, summary = clean.validate_clean_note_html(raw)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(
            summary["formulas"],
            [
                {"kind": "inline", "payload": "S_i=V_i/V"},
                {
                    "kind": "display",
                    "payload": "S_{T_i}=1-V_{\\sim i}/V",
                },
            ],
        )

    def test_render_helpers_escape_html_once(self) -> None:
        rendered = clean.render_display_math(
            r"\begin{aligned}a&=b\\c&<d\end{aligned}"
        )
        self.assertEqual(
            rendered,
            '<pre class="math">$$\\begin{aligned}a&amp;=b\\\\c&amp;&lt;d'
            '\\end{aligned}$$</pre>',
        )
        with self.assertRaisesRegex(ValueError, "still-escaped"):
            clean.render_inline_math(r"a&amp;=b")

    def test_rejects_plain_dollar_formulas(self) -> None:
        self.assert_invalid(note("<p>错误公式 $x+y$。</p>"), "CN-06")
        self.assert_invalid(note("<p>错误公式 $$x+y$$。</p>"), "CN-06")

    def test_rejects_wrong_math_nodes_attributes_and_nesting(self) -> None:
        cases = [
            (note('<p><em class="math">$x$</em></p>'), "CN-07"),
            (note('<span class="math">$x$</span>'), "CN-07"),
            (note('<p><pre class="math">$$x$$</pre></p>'), "CN-07"),
            (note('<h2><span class="math">$x$</span></h2>'), "CN-07"),
            (note('<p><span class="math" id="eq-1">$x$</span></p>'), "CN-07"),
            (note('<p><span class="math">$$x$$</span></p>'), "CN-08"),
            (note('<pre class="math">$x$</pre>'), "CN-08"),
        ]
        for raw, code in cases:
            with self.subTest(raw=raw):
                self.assert_invalid(raw, code)

    def test_rejects_double_escaping_and_outer_wrapper(self) -> None:
        self.assert_invalid(
            note('<p><span class="math">$a&amp;amp;=b$</span></p>'),
            "CN-09",
        )
        self.assert_invalid(
            note('<p><span class="math">$\\\\frac{a}{b}$</span></p>'),
            "CN-09",
        )
        wrapped = (
            '<div class="zotero-note znv1">'
            + note("<p>正文。</p>")
            + "</div>"
        )
        self.assert_invalid(wrapped, "CN-02")

    def test_rejects_operational_state_but_allows_evidence_dates(self) -> None:
        forbidden = [
            "<p>content_sha256: " + "a" * 64 + "</p>",
            "<p>本地路径：/srv/private/paper.pdf</p>",
            "<p>generated_at: 2026-08-06T10:20:30Z</p>",
            "<p>transaction_id: fixture；readback_status: pending</p>",
            "<h2>资料与阅读状态</h2><p>阅读深度：reconstruction</p>",
        ]
        for body in forbidden:
            with self.subTest(body=body):
                self.assert_invalid(note(body), "CN-10")
        errors, _, _ = clean.validate_clean_note_html(
            note(
                "<p>出版日期：2024-03-01；定位：PDF 页 7，Table 2。"
                "局限：仅由摘要支持。</p>"
            )
        )
        self.assertEqual(errors, [])

    def test_formula_roundtrip_compares_order_and_payload(self) -> None:
        expected = note(
            '<p><span class="math">$a&amp;b$</span></p>'
            '<pre class="math">$$c&lt;d$$</pre>'
        )
        observed = (
            '<div data-schema-version="9">\n<h1>适用场景与结论</h1>\n'
            '<p><span class="math">$a&amp;b$</span></p>\n'
            '<pre class="math">$$c&lt;d$$</pre>\n</div>'
        )
        self.assertEqual(
            clean.compare_formula_roundtrip(expected, observed), []
        )
        swapped = note(
            '<pre class="math">$$c&lt;d$$</pre>'
            '<p><span class="math">$a&amp;b$</span></p>'
        )
        self.assertEqual(
            clean.compare_formula_roundtrip(expected, swapped),
            ["CN-RT-03: formula kind/order/payload changed during roundtrip"],
        )


if __name__ == "__main__":
    unittest.main()
