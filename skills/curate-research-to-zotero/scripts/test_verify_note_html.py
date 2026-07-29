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
<tr><td>C1</td><td>source-stated</td><td>该式定义了模型。</td><td>正文 p.2 | Eq. (1)</td><td>给定假设成立。</td><td>high：原文公式直接支持。</td></tr></table>
<h2>方法或推导</h2><p>输入经过算法得到输出。</p>
<pre class="math">$$x=y$$</pre><p>符号：变量。作用：定义关系。假设：线性。定位：正文 p.2 | Eq. (1)。</p>
<h2>结果</h2><p>实验得到阳性结果。</p>
<h2>假设、失败边界与竞争解释</h2><p>仅在限定数据下成立。</p>
<h2>知识图谱关系</h2><p>支持当前方法分支。</p>
<h2>复用</h2><p>适合相同观测条件。</p>
{extra}
<h2>溯源</h2><p>证据账本：fixture；本地PDF：/tmp/a.pdf；SHA-256：{'a' * 64}；Agent推断：已显式标记。</p>
</div>"""


class VerifyNoteHTMLTests(unittest.TestCase):
    def test_valid_evidence_note(self) -> None:
        errors, _, summary = verify.validate_note(valid_note())
        self.assertEqual(errors, [])
        self.assertEqual(summary["claim_ids"], ["C1"])

    def test_valid_reconstruction_note(self) -> None:
        errors, _, summary = verify.validate_note(valid_note(depth="reconstruction"))
        self.assertEqual(errors, [])
        self.assertEqual(summary["reading_depth"], "reconstruction")

    def test_rejects_unicode_math_and_missing_locator(self) -> None:
        note = valid_note().replace("正文 p.2 | Eq. (1)", "没有定位", 1).replace("x=y", "Ẋ=Θ")
        errors, _, _ = verify.validate_note(note)
        self.assertTrue(any("lacks an exact locator" in error for error in errors))
        self.assertTrue(any("forbidden Unicode math" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
