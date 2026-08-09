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

    def test_rejects_operational_metadata_and_template_declarations(self) -> None:
        polluted_fragments = [
            "<p>ShortTitleReview/v4.2-rc1</p>",
            "<p>applicability: selected-note-only</p>",
            "<p><strong>decision</strong>: apply</p>",
            "<p>predicate = exact_collection_match</p>",
            "<p>old_note_or_explicit_missing_disclosure</p>",
            "<p>preserved_old_locator_or_nonfull_disclosure</p>",
            "<p>bounded_classification_boilerplate</p>",
            "<p>hash: sha256:0123456789abcdef</p>",
            "<p>manifest: reviewed-items.json</p>",
            "<p>transaction: replace-child-note</p>",
            "<p>sync: pending</p>",
            "<p>audit: passed</p>",
            "<p>validator: clean-note-v2</p>",
            "<p>status: ready</p>",
            '<p data-status="ready">A result paragraph.</p>',
            '<p>{"manifest": "reviewed-items.json"}</p>',
            "<h2>Sync status</h2><p>ready</p>",
        ]
        for fragment in polluted_fragments:
            with self.subTest(fragment=fragment):
                errors, _, _ = clean.validate_clean_note_html(note(fragment))
                self.assertTrue(
                    any("operational metadata" in error for error in errors),
                    errors,
                )

    def test_allows_scientific_uses_of_metadata_vocabulary(self) -> None:
        scientific_prose = (
            "<p>The classification of regimes follows the measured Damkohler "
            "number.</p>"
            "<p>The stability status of the fixed point changes at the "
            "bifurcation.</p>"
            "<p>A locality-sensitive hash algorithm clusters related state "
            "vectors.</p>"
            "<p>The predicate is evaluated inside the theorem, while the "
            "validator function denotes a mathematical map.</p>"
            "<p>The transaction rate and synchronization error are reported as "
            "physical observables.</p>"
        )
        errors, _, _ = clean.validate_clean_note_html(note(scientific_prose))
        self.assertEqual(errors, [])

    def test_rejects_structured_curation_target_fields(self) -> None:
        polluted_fragments = [
            "<p>目标集合：示例文库 / 研究主题 / 子主题</p>",
            "<p>目标文库: 示例团队文库</p>",
            "<p>集合路径：研究主题 / 子主题</p>",
            "<p>collection: example-corpus</p>",
            "<p>library = example-team</p>",
            "<p>target: example-subcollection</p>",
            "<p>path: example / branch</p>",
            '<p>{"collection_path": "example / branch"}</p>',
            '<p data-library="example-team">研究结论。</p>',
            "<h2>Target collection</h2><p>example-corpus</p>",
        ]
        for fragment in polluted_fragments:
            with self.subTest(fragment=fragment):
                self.assert_invalid(note(fragment), "CN-10")

    def test_allows_scientific_prose_using_curation_words(self) -> None:
        scientific_prose = (
            "<p>The specimen collection spans three process regimes, and the "
            "software library implements a path-sampling algorithm.</p>"
            "<p>The target response is surface roughness. The inferred path "
            "through parameter space is compared with the reference curve.</p>"
            "<p>本文分析轨迹集合，并把路径采样用于稀有事件估计；这些词是论文内容。"
            "</p>"
        )
        errors, _, _ = clean.validate_clean_note_html(note(scientific_prose))
        self.assertEqual(errors, [])

    def test_rejects_every_custom_data_attribute_outside_root_schema(self) -> None:
        attributes = [
            "data-curation-path",
            "data-zotero-collection",
            "data-run-id",
            "data-local-path",
            "data-workflow",
            "data-private-state",
        ]
        for attribute in attributes:
            with self.subTest(attribute=attribute):
                self.assert_invalid(
                    note(f'<p {attribute}="synthetic">研究结论。</p>'),
                    "CN-04",
                )
        for attribute in ("data-schema-version", "data-citation-items"):
            with self.subTest(descendant_attribute=attribute):
                self.assert_invalid(
                    note(f'<p {attribute}="synthetic">研究结论。</p>'),
                    "CN-04",
                )

    def test_allows_only_root_schema_data_attributes_and_ordinary_attributes(
        self,
    ) -> None:
        raw = (
            '<div data-schema-version="9" data-citation-items="[]">'
            "<h1>研究结论</h1>"
            '<p class="finding" title="paper statement">'
            '<em lang="en">The target response follows a path.</em>'
            "</p></div>"
        )
        errors, warnings, _ = clean.validate_clean_note_html(raw)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_rejects_prose_dominated_math_payloads(self) -> None:
        invalid_payloads = [
            "输入变量必须相互独立，否则结果不成立。",
            "This estimator requires independent inputs and enough samples.",
            r"\text{输入变量必须相互独立，否则结果不成立}",
            "global sensitivity analysis method",
        ]
        for payload in invalid_payloads:
            raw = note(f'<pre class="math">$${payload}$$</pre>')
            with self.subTest(payload=payload):
                errors, _, _ = clean.validate_clean_note_html(raw)
                self.assertTrue(
                    any("prose-dominated" in error for error in errors),
                    errors,
                )

    def test_accepts_aligned_entities_operators_and_short_text_labels(self) -> None:
        aligned = (
            r"\begin{aligned}"
            r"S_i &="
            r" \frac{\operatorname{Var}(\mathbb{E}[Y\mid X_i])}"
            r"{\operatorname{Var}(Y)}\\ "
            r"S_{T_i} &= 1-\frac{V_{\sim i}}{V}"
            r"\end{aligned}"
        )
        cases = [
            aligned,
            r"\begin{gathered}A=B\\ C=D\end{gathered}",
            (
                r"f(x)=\begin{cases}1,&\text{if }x>0\\"
                r"0,&\text{otherwise}\end{cases}"
            ),
            r"\operatorname{Var}(Y)",
        ]
        for payload in cases:
            rendered = clean.render_display_math(payload)
            raw = note(rendered)
            with self.subTest(payload=payload):
                errors, _, summary = clean.validate_clean_note_html(raw)
                self.assertEqual(errors, [])
                self.assertEqual(summary["formulas"][0]["payload"], payload)
        self.assertIn("&amp;", clean.render_display_math(aligned))

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
