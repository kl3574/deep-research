from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("verify_note_html.py")
MODULE_SPEC = importlib.util.spec_from_file_location("verify_note_html", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
verify = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(verify)


def valid_note(*, depth: str = "evidence") -> str:
    extra = ""
    if depth == "reconstruction":
        extra = """
<h2>完整性与纠错日志</h2>
<p>总页数：10。主文与补充材料：主文 8 页，补充材料 2 页。图表公式盘点：已核查。未解决项：无。</p>
<table><tr><th>初始理解</th><th>源文复核</th><th>修正及影响</th></tr>
<tr><td>初始理解为甲。</td><td>源文复核为乙。</td><td>修正及影响已记录。</td></tr></table>
"""
    return f"""<div data-schema-version="9">
<h1>文献笔记｜Fixture</h1>
<h2>资料与阅读状态</h2>
<p>标题：Fixture；作者：甲；年份：2024；期刊或载体：测试期刊；DOI或稳定标识：10.1000/test；
版本与出版状态：正式版；访问层级：full_text；全文SHA-256：{'a' * 64}；
阅读深度：{depth}；核验时间：2026-07-29。</p>
<h2>为什么重要</h2><p>该来源用于验证方法。</p>
<h2>一句话结论</h2><p>该方法在限定条件下有效。</p>
<h2>心智模型</h2><p>问题到方法再到证据与结论。</p>
<h2>关键主张与证据</h2>
<table><tr><th>Claim ID</th><th>性质</th><th>主张</th><th>证据与精确定位</th><th>条件</th><th>置信度与理由</th></tr>
<tr><td>C1</td><td>source-stated</td><td>该式定义了模型。</td>
<td>正文 p.2 | Eq. (1)</td><td>给定假设成立。</td>
<td>high：原文公式直接支持。</td></tr></table>
<h2>方法或推导</h2><p>输入经过算法得到输出。</p>
<pre class="math">$$x=y$$</pre><p>符号：变量。作用：定义关系。假设：线性。定位：正文 p.2 | Eq. (1)。</p>
<h2>结果</h2><p>实验得到阳性结果。</p>
<h2>假设、失败边界与竞争解释</h2><p>仅在限定数据下成立。</p>
<h2>知识图谱关系</h2><p>支持当前方法分支。</p>
<h2>复用</h2><p>适合相同观测条件。</p>
{extra}
<h2>溯源</h2><p>证据账本：fixture；本地PDF：/tmp/a.pdf；SHA-256：{'a' * 64}；Agent推断：已显式标记。</p>
</div>"""


def valid_metadata_note() -> str:
    return """<div data-schema-version="9" data-access-level="metadata_only">
<h1>文献笔记｜Metadata Fixture</h1>
<h2>资料与阅读状态</h2>
<p>标题：Metadata Fixture；作者：甲；年份：2024；期刊或载体：测试期刊；
DOI或稳定标识：10.1000/test；版本与出版状态：正式版；访问层级：metadata_only；
全文状态：未获取全文；阅读深度：map；核验时间：2026-08-05。</p>
<h2>为什么重要</h2><p>该题录可能与当前问题相关，但尚无全文证据。</p>
<h2>一句话结论</h2><p>未获取全文，不能形成科学结论。</p>
<h2>心智模型</h2><p>当前只保留书目信息，等待合法全文。</p>
<h2>关键主张与证据</h2>
<p>未获取全文，未形成全文证据主张。</p>
<table><tr><th>Claim ID</th><th>性质</th><th>主张</th><th>证据与精确定位</th><th>条件</th><th>置信度与理由</th></tr></table>
<h2>方法或推导</h2><p>未获取全文，方法与推导均未核验。</p>
<h2>结果</h2><p>未获取全文，结果未核验。</p>
<h2>假设、失败边界与竞争解释</h2><p>题录信息不能替代全文证据。</p>
<h2>知识图谱关系</h2><p>仅登记候选来源，不建立证据支持关系。</p>
<h2>复用</h2><p>取得全文后必须重新深读和核验。</p>
<h2>溯源</h2><p>元数据来源：https://doi.org/10.1000/test；元数据核验时间：2026-08-05；Agent推断：未形成全文主张。</p>
</div>"""


class VerifyNoteHTMLTests(unittest.TestCase):
    def test_valid_evidence_note(self) -> None:
        errors, _, summary = verify.validate_note(valid_note())
        self.assertEqual(errors, [])
        self.assertEqual(summary["claim_ids"], ["C1"])
        self.assertEqual(summary["full_text_sha256"], "a" * 64)

    def test_valid_reconstruction_note(self) -> None:
        errors, _, summary = verify.validate_note(valid_note(depth="reconstruction"))
        self.assertEqual(errors, [])
        self.assertEqual(summary["reading_depth"], "reconstruction")

    def test_valid_metadata_only_note_has_no_full_text_sha(self) -> None:
        errors, warnings, summary = verify.validate_note(valid_metadata_note())

        self.assertEqual(errors, [])
        self.assertIsNone(summary["full_text_sha256"])
        self.assertEqual(summary["access_level"], "metadata_only")
        self.assertEqual(summary["root_access_level"], "metadata_only")
        self.assertTrue(warnings)

    def test_metadata_only_rejects_fabricated_hash(self) -> None:
        note = valid_metadata_note().replace(
            "阅读深度：map",
            f"全文SHA-256：{'a' * 64}；阅读深度：map",
        )

        errors, _, _ = verify.validate_note(note)

        self.assertTrue(any("must not contain" in error for error in errors))

    def test_metadata_only_rejects_claim_rows(self) -> None:
        note = valid_metadata_note().replace(
            "</tr></table>",
            "</tr><tr><td>C1</td><td>source-stated</td><td>全文声称该方法有效。</td>"
            "<td>正文 p.2</td><td>给定条件。</td><td>high：原文支持。</td></tr></table>",
            1,
        )

        errors, _, _ = verify.validate_note(note)

        self.assertTrue(any("must not contain claim data rows" in error for error in errors))

    def test_full_text_rejects_missing_hash(self) -> None:
        note = valid_note().replace(f"全文SHA-256：{'a' * 64}；\n", "", 1)

        errors, _, summary = verify.validate_note(note)

        self.assertTrue(any("full-text SHA-256" in error for error in errors))
        self.assertIsNone(summary["full_text_sha256"])

    def test_metadata_marker_rejects_full_text_access_label(self) -> None:
        note = valid_metadata_note().replace(
            "访问层级：metadata_only",
            "访问层级：full_text",
            1,
        )

        errors, _, _ = verify.validate_note(note)

        self.assertTrue(any("metadata-only root marker requires" in error for error in errors))

    def test_accepts_zotero_compacted_metadata_with_br_and_strong(self) -> None:
        digest = "a" * 64
        note = valid_note().replace(
            f"全文SHA-256：{digest}；\n阅读深度：evidence；",
            (
                f"<strong>全文SHA-256：</strong>{digest}<br>"
                "<strong>阅读深度：</strong>evidence；"
            ),
        )
        errors, _, summary = verify.validate_note(note)

        self.assertEqual(errors, [])
        self.assertEqual(summary["reading_depth"], "evidence")

    def test_compacted_br_does_not_hide_trailing_second_root(self) -> None:
        digest = "a" * 64
        note = valid_note().replace(
            f"全文SHA-256：{digest}；\n阅读深度：evidence；",
            (
                f"<strong>全文SHA-256：</strong>{digest}<br>"
                "<strong>阅读深度：</strong>evidence；"
            ),
        )
        note += "<div><script>alert(1)</script></div>"

        errors, _, _ = verify.validate_note(note)

        self.assertTrue(any("exactly one root element" in error for error in errors))
        self.assertTrue(any("forbidden active" in error for error in errors))

    def test_rejects_mismatched_closing_tags(self) -> None:
        note = valid_note().replace(
            "<p>该来源用于验证方法。</p>",
            "<p>该来源用于验证方法。</div>",
            1,
        )

        errors, _, _ = verify.validate_note(note)

        self.assertTrue(any("mismatched closing tag" in error for error in errors))
        self.assertTrue(any("unclosed element stack" in error for error in errors))

    def test_rejects_event_handlers_and_active_urls(self) -> None:
        note = valid_note().replace(
            "<h1>",
            '<a href="javascript:alert(1)" onclick="alert(1)">危险</a><h1>',
            1,
        )

        errors, _, _ = verify.validate_note(note)

        self.assertTrue(any("forbidden active URL" in error for error in errors))
        self.assertTrue(any("forbidden active attribute" in error for error in errors))

    def test_rejects_control_character_obfuscated_active_urls(self) -> None:
        for active_url in (
            "java&#x0A;script:alert(1)",
            "da&#x09;ta:text/html,<script>alert(1)</script>",
            "vb&#x0D;script:alert(1)",
            "java\nscript:alert(1)",
        ):
            with self.subTest(active_url=active_url):
                note = valid_note().replace(
                    "<h1>",
                    f'<a href="{active_url}">危险</a><h1>',
                    1,
                )

                errors, _, _ = verify.validate_note(note)

                self.assertTrue(
                    any("forbidden active URL" in error for error in errors)
                )

    def test_full_text_sha_is_bound_to_its_label(self) -> None:
        note = valid_note().replace(
            "<h1>",
            f"<p>{'a' * 64}</p><h1>",
            1,
        ).replace(
            f"全文SHA-256：{'a' * 64}",
            f"全文SHA-256：{'b' * 63}",
            1,
        )

        errors, _, summary = verify.validate_note(note)

        self.assertTrue(any("full-text SHA-256" in error for error in errors))
        self.assertIsNone(summary["full_text_sha256"])

    def test_duplicate_full_text_sha_labels_are_rejected(self) -> None:
        note = valid_note().replace(
            "阅读深度：evidence",
            f"全文SHA-256：{'a' * 64}；阅读深度：evidence",
            1,
        )

        errors, _, summary = verify.validate_note(note)

        self.assertTrue(any("exactly once" in error for error in errors))
        self.assertIsNone(summary["full_text_sha256"])

    def test_rejects_unicode_math_and_missing_locator(self) -> None:
        note = valid_note().replace("正文 p.2 | Eq. (1)", "没有定位", 1).replace("x=y", "Ẋ=Θ")
        errors, _, _ = verify.validate_note(note)
        self.assertTrue(any("lacks an exact locator" in error for error in errors))
        self.assertTrue(any("forbidden Unicode math" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
