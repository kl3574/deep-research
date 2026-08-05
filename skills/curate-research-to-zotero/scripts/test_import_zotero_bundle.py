from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("import_zotero_bundle.py")
SPEC = importlib.util.spec_from_file_location("import_zotero_bundle", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def metadata_note() -> str:
    return """<div data-schema-version="9" data-access-level="metadata_only">
<h1>文献笔记｜Metadata Fixture</h1>
<h2>资料与阅读状态</h2><p>标题：Metadata Fixture；作者：甲；年份：2024；期刊或载体：测试期刊；DOI或稳定标识：10.1000/test；版本与出版状态：正式版；访问层级：metadata_only；全文状态：未获取全文；阅读深度：map；核验时间：2026-08-05。</p>
<h2>为什么重要</h2><p>该题录可能相关，但尚无全文证据。</p>
<h2>一句话结论</h2><p>未获取全文，不能形成科学结论。</p>
<h2>心智模型</h2><p>当前只保留书目信息，等待合法全文。</p>
<h2>关键主张与证据</h2><p>未获取全文，未形成全文证据主张。</p><table><tr><th>Claim ID</th><th>性质</th><th>主张</th><th>证据与精确定位</th><th>条件</th><th>置信度与理由</th></tr></table>
<h2>方法或推导</h2><p>未获取全文，方法与推导均未核验。</p>
<h2>结果</h2><p>未获取全文，结果未核验。</p>
<h2>假设、失败边界与竞争解释</h2><p>题录信息不能替代全文证据。</p>
<h2>知识图谱关系</h2><p>仅登记候选来源，不建立证据支持关系。</p>
<h2>复用</h2><p>取得全文后必须重新深读和核验。</p>
<h2>溯源</h2><p>元数据来源：https://doi.org/10.1000/test；元数据核验时间：2026-08-05；Agent推断：未形成全文主张。</p>
</div>"""


class MetadataOnlyImportTests(unittest.TestCase):
    def make_bundle(
        self,
        root: Path,
        *,
        pdf: object = None,
        note_html: str | None = None,
    ) -> tuple[Path, Path]:
        note = root / "note.html"
        note.write_text(note_html or metadata_note(), encoding="utf-8")
        bundle = {
            "source_id": "source-1",
            "access_level": "metadata_only",
            "metadata_only_reason": "No lawful full text was acquired.",
            "target": {"group_id": 1},
            "item": {"title": "A paper", "DOI": "10.1/example"},
            "pdf": pdf,
            "note": {
                "html_path": str(note),
                "sha256": hashlib.sha256(note.read_bytes()).hexdigest(),
            },
        }
        path = root / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        return path, note

    def test_metadata_only_bundle_validates_without_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle_path, note_path = self.make_bundle(Path(temp))
            bundle, pdf_path, actual_note, pdf_hash = module.load_and_validate(bundle_path)
            self.assertEqual(bundle["access_level"], "metadata_only")
            self.assertIsNone(pdf_path)
            self.assertIsNone(pdf_hash)
            self.assertEqual(actual_note, note_path)

    def test_metadata_only_bundle_refuses_declared_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle_path, _ = self.make_bundle(Path(temp), pdf={"local_path": "/tmp/x.pdf"})
            with self.assertRaisesRegex(module.BundleError, "must not declare a PDF"):
                module.load_and_validate(bundle_path)

    def test_metadata_only_bundle_refuses_full_text_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            note_html = metadata_note().replace(
                'data-access-level="metadata_only"',
                'data-access-level="full_text"',
                1,
            )
            bundle_path, _ = self.make_bundle(Path(temp), note_html=note_html)
            with patch.object(
                module,
                "validate_note",
                return_value=(
                    [],
                    [],
                    {
                        "access_level": "full_text",
                        "root_access_level": "full_text",
                        "note_projection": "full_text",
                    },
                ),
            ):
                with self.assertRaisesRegex(module.BundleError, "does not match"):
                    module.load_and_validate(bundle_path)

    def test_full_text_bundle_refuses_metadata_only_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle_path, _ = self.make_bundle(root)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["access_level"] = "full_text"
            bundle["pdf"] = {
                "local_path": str(pdf),
                "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            }
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

            with self.assertRaisesRegex(module.BundleError, "conflicts with"):
                module.load_and_validate(bundle_path)

    def test_metadata_only_import_creates_no_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle_path, note_path = self.make_bundle(Path(temp))
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            note_html = note_path.read_text(encoding="utf-8")
            calls: list[str] = []

            def request_json(path: str, **_: object) -> tuple[int, object]:
                calls.append(path)
                return 201, {}

            children = [{"key": "NOTEKEY", "data": {"itemType": "note", "note": note_html}}]
            with (
                patch.object(module, "request_json", side_effect=request_json),
                patch.object(
                    module,
                    "poll_new_parent",
                    return_value={"key": "PARENT", "data": {"collections": ["COLL"]}},
                ),
                patch.object(module, "api_get", return_value=children),
            ):
                result = module.import_bundle(
                    bundle,
                    None,
                    None,
                    group_id=1,
                    collection_key="COLL",
                    storage_root=Path("/unused"),
                )

            self.assertEqual(calls, ["/connector/saveItems"])
            self.assertEqual(result["access_level"], "metadata_only")
            self.assertIsNone(result["attachment_key"])
            self.assertIsNone(result["source_pdf_sha256"])


if __name__ == "__main__":
    unittest.main()
