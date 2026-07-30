#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import tempfile
import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

import update_existing_note as module
from test_verify_note_html import valid_note


class UpdateExistingNoteTests(unittest.TestCase):
    def _default_schema9_note(self, note_key: str, pdf_sha256: str) -> str:
        return f"""<div data-schema-version="9">
<h1>文献笔记｜{note_key}</h1>
<h2>资料与阅读状态</h2>
<p><strong>标题：</strong>文献笔记｜{note_key}<br>
<strong>作者：</strong>测试作者<br>
<strong>年份：</strong>2026<br>
<strong>期刊或载体：</strong>测试期刊<br>
<strong>DOI或稳定标识：</strong>10.1000/test<br>
<strong>版本与出版状态：</strong>正式版<br>
<strong>访问层级：</strong>full_text<br>
<strong>全文SHA-256：</strong>{pdf_sha256}<br>
<strong>阅读深度：</strong>evidence<br>
<strong>核验时间：</strong>2026-07-29。</p>
<h2>为什么重要</h2><p>用于迁移前后行为比对与断言。</p>
<h2>一句话结论</h2><p>该条目可安全继续复用。</p>
<h2>心智模型</h2><p>输入到处理逻辑，再到结论，闭环可复核。</p>
<h2>关键主张与证据</h2>
<table><tr><th>Claim ID</th><th>性质</th><th>主张</th><th>证据与精确定位</th><th>条件</th><th>置信度与理由</th></tr>
<tr><td>C1</td><td>source-stated</td><td>本条目提供了可复现的来源说明。</td>
<td>正文 p.1 | Eq. (1)</td><td>给定默认条件成立。</td>
<td>high：文献与迁移上下文一致。</td></tr></table>
<h2>方法或推导</h2>
<pre class="math">$$x=y$$</pre><p>符号：变量定义。作用：建立一一对应。假设：结构在默认上下文下成立。定位：正文 p.1 | Eq. (1)。</p>
<h2>结果</h2><p>该注释通过当前迁移约束。</p>
<h2>假设、失败边界与竞争解释</h2><p>结论受源条件约束，需结合上下文核验。</p>
<h2>知识图谱关系</h2><p>该注释服务于当前知识图谱边界校验。</p>
<h2>复用</h2><p>适用于重复出现的相同结构场景。</p>
<h2>溯源</h2><p>证据账本：已核验；本地PDF：/tmp/{note_key}.pdf；SHA-256：{pdf_sha256}；Agent推断：已显式记录。</p>
</div>"""

    def _staged_entry(
        self,
        tmpdir: Path,
        *,
        note_key: str,
        parent_key: str,
        note_version: int = 1,
        old_html: str | None = None,
        new_html: str | None = None,
        child_note_inventory: list[str] | None = None,
        child_attachment_inventory: list[str] | None = None,
        expected_parent_key: str | None = None,
        pdf_content: bytes = b"%PDF-1.4\n%EOF\n",
        pdf_attachment_key: str | None = None,
        pdf_attachment_link_mode: str = "linked_file",
        validation_summary: dict[str, object] | None = None,
        validation_errors: list[str] | None = None,
    ) -> dict[str, object]:
        old_path = tmpdir / f"{note_key}.old.html"
        new_path = tmpdir / f"{note_key}.new.html"
        pdf_path = tmpdir / f"{note_key}.pdf"
        pdf_path.write_bytes(pdf_content)
        pdf_sha = module.sha256_bytes(pdf_content)
        default_html = self._default_schema9_note(note_key=note_key, pdf_sha256=pdf_sha)
        if old_html is None:
            old_html = "<p>旧笔记</p>"
        if new_html is None:
            new_html = default_html
        old_path.write_text(old_html, encoding="utf-8")
        new_path.write_text(new_html, encoding="utf-8")

        if child_attachment_inventory is None:
            pdf_attachment_key = pdf_attachment_key or "ATT00001"
            child_attachment_inventory = [pdf_attachment_key]
        elif pdf_attachment_key is None:
            pdf_attachment_key = str(child_attachment_inventory[0])
        return {
            "status": "staged_verified",
            "note_key": note_key,
            "parent_key": parent_key,
            "expected_parent_key": expected_parent_key or parent_key,
            "note_version": note_version,
            "old_path": str(old_path.resolve()),
            "new_path": str(new_path.resolve()),
            "old_sha256": module.sha256_text(old_html),
            "new_sha256": module.sha256_text(new_html),
            "pdf_path": str(pdf_path.resolve()),
            "pdf_sha256": pdf_sha,
            "child_note_inventory": child_note_inventory
            if child_note_inventory is not None
            else [note_key],
            "child_attachment_inventory": child_attachment_inventory
            if child_attachment_inventory is not None
            else [],
            "pdf_attachment_key": pdf_attachment_key,
            "pdf_attachment_link_mode": pdf_attachment_link_mode,
            "validation_summary": validation_summary
            or {
                "schema_version": "9",
                "full_text_sha256": pdf_sha,
            },
            "validation_errors": validation_errors or [],
        }

    def test_probe_local_write_uses_server_id_without_options_request(self) -> None:
        with patch.object(
            module,
            "request",
            return_value=(
                200,
                {"zOtErO-SeRvEr-Id": "instance-123"},
                b"Nothing to see here.",
            ),
        ) as request_mock:
            result = module.probe_local_write()

        self.assertTrue(result["supported"])
        self.assertEqual(result["server_id"], "instance-123")
        self.assertEqual(result["authorization_probe"], "deferred_until_apply")
        request_mock.assert_called_once_with(f"{module.LOCAL_BASE}/api/")

    def test_probe_local_write_rejects_runtime_without_server_id(self) -> None:
        with patch.object(
            module,
            "request",
            return_value=(200, {"Zotero-API-Version": "3"}, b""),
        ):
            result = module.probe_local_write()

        self.assertFalse(result["supported"])
        self.assertIsNone(result["server_id"])

    def test_choose_route_prefers_supported_local_then_web(self) -> None:
        self.assertEqual(
            module.choose_route(
                "auto",
                local_supported=True,
                web_key_present=True,
            ),
            "local",
        )
        self.assertEqual(
            module.choose_route(
                "auto",
                local_supported=False,
                web_key_present=True,
            ),
            "web",
        )
        self.assertIsNone(
            module.choose_route(
                "local",
                local_supported=False,
                web_key_present=True,
            )
        )
        self.assertIsNone(
            module.choose_route(
                "web",
                local_supported=True,
                web_key_present=False,
            )
        )

    def test_unavailable_route_message_matches_explicit_request(self) -> None:
        self.assertIn(
            "local write route unavailable",
            module.unavailable_route_message("local", "ZOTERO_API_KEY"),
        )
        web_message = module.unavailable_route_message("web", "CUSTOM_ZOTERO_KEY")
        self.assertIn("Web API write route unavailable", web_message)
        self.assertIn("CUSTOM_ZOTERO_KEY is unset", web_message)
        auto_message = module.unavailable_route_message("auto", "ZOTERO_API_KEY")
        self.assertIn("local write authorization", auto_message)
        self.assertIn("ZOTERO_API_KEY is unset", auto_message)

    def test_authorize_local_parses_key_without_logging_it(self) -> None:
        body = json.dumps(
            {"key": "local-secret-for-test", "remember": True}
        ).encode("utf-8")
        with patch.object(
            module,
            "request",
            return_value=(200, {}, body),
        ) as request_mock:
            result = module.authorize_local("instance-123", "test app")

        self.assertEqual(result["api_key"], "local-secret-for-test")
        self.assertTrue(result["remember"])
        _, kwargs = request_mock.call_args
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(
            kwargs["headers"]["Zotero-Server-ID"],
            "instance-123",
        )
        self.assertEqual(kwargs["payload"], {"appName": "test app"})
        self.assertEqual(kwargs["timeout"], 55)

    def test_authorize_local_reports_rate_limit_without_response_body(self) -> None:
        with patch.object(
            module,
            "request",
            return_value=(
                429,
                {"Retry-After": "37"},
                b'{"key":"must-not-appear"}',
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "rate-limited; retry after 37 seconds",
            ) as raised:
                module.authorize_local("instance-123", "test app")

        self.assertNotIn("must-not-appear", str(raised.exception))

    def test_verify_web_key_access_accepts_exact_group_write(self) -> None:
        key_obj = {
            "userID": 123,
            "access": {
                "groups": {
                    "1234567": {
                        "library": True,
                        "write": True,
                    }
                }
            },
        }
        with patch.object(
            module,
            "get_json",
            return_value=({}, key_obj),
        ) as get_json_mock:
            result = module.verify_web_key_access("web-secret-for-test", 1234567)

        self.assertEqual(
            result,
            {
                "group_id": 1234567,
                "library": True,
                "write": True,
            },
        )
        get_json_mock.assert_called_once_with(
            f"{module.WEB_BASE}/keys/current",
            headers=module.web_headers("web-secret-for-test"),
        )

    def test_verify_web_key_access_rejects_read_only_group(self) -> None:
        key_obj = {
            "access": {
                "groups": {
                    "all": {
                        "library": True,
                        "write": False,
                    }
                }
            },
        }
        with patch.object(
            module,
            "get_json",
            return_value=({}, key_obj),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "cannot write group 1234567",
            ):
                module.verify_web_key_access("web-secret-for-test", 1234567)

    def test_load_entries_rejects_duplicate_staged_note_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": [
                            "PARENT01",
                            "PARENT02",
                        ],
                        "entries": [
                            self._staged_entry(
                                tmp_path,
                                note_key="NOTE000A",
                                parent_key="PARENT01",
                            ),
                            self._staged_entry(
                                tmp_path,
                                note_key="NOTE000A",
                                parent_key="PARENT02",
                            ),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError, "duplicate note_key in staged entries: NOTE000A"
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_missing_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "entries": [
                            {
                                "status": "staged_verified",
                                "note_key": "NOTE000A",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "migration manifest version must be '2'"
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_written_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": True,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "entries": [
                            {
                                "status": "staged_verified",
                                "note_key": "NOTE000A",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "migration manifest must have write_performed set to False",
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_inventory_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01", "PARENT02"],
                        "entries": [
                            {
                                "status": "staged_verified",
                                "note_key": "NOTE000A",
                                "parent_key": "PARENT01",
                                "expected_parent_key": "PARENT01",
                                "child_note_inventory": ["NOTE000A"],
                                "child_attachment_inventory": [],
                                "note_version": 1,
                                "old_path": f"{tmpdir}/old.html",
                                "new_path": f"{tmpdir}/new.html",
                                "old_sha256": module.sha256_text("<p>old</p>"),
                                "new_sha256": module.sha256_text("<p>new</p>"),
                                "pdf_path": f"{tmpdir}/a.pdf",
                                "pdf_sha256": module.sha256_bytes(
                                    b"%PDF-1.4\n%EOF"
                                ),
                                "validation_summary": {
                                    "schema_version": "9",
                                    "full_text_sha256": module.sha256_bytes(
                                        b"%PDF-1.4\n%EOF"
                                    ),
                                },
                                "validation_errors": [],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "entries do not exactly cover collection inventory",
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_non_pdf_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [
                            self._staged_entry(
                                tmp_path,
                                note_key="NOTE000A",
                                parent_key="PARENT01",
                                pdf_content=b"NOT_A_PDF",
                            ),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "does not point to a PDF file",
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_validation_summary_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [
                            self._staged_entry(
                                tmp_path,
                                note_key="NOTE000A",
                                parent_key="PARENT01",
                                validation_summary={
                                    "schema_version": "9",
                                    "full_text_sha256": "0" * 64,
                                },
                            ),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "full_text_sha256 does not match pdf_sha256",
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_strip_noop_new_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            entry = self._staged_entry(
                tmp_path,
                note_key="NOTE000A",
                parent_key="PARENT01",
            )
            old_html = "<p>旧笔记</p>"
            new_html = "<p>旧笔记</p>\n"
            Path(str(entry["old_path"])).write_text(old_html, encoding="utf-8")
            Path(str(entry["new_path"])).write_text(new_html, encoding="utf-8")
            entry["old_sha256"] = module.sha256_text(old_html)
            entry["new_sha256"] = module.sha256_text(new_html)
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [entry],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "staged note normalizes to the existing note",
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_accepts_unchanged_verified_without_noop_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            entry = self._staged_entry(
                tmp_path,
                note_key="NOTE000A",
                parent_key="PARENT01",
            )
            unchanged_note = valid_note().replace(
                "a" * 64,
                entry["pdf_sha256"],
            )
            entry["status"] = "unchanged_verified"
            Path(str(entry["old_path"])).write_text(unchanged_note, encoding="utf-8")
            Path(str(entry["new_path"])).write_text(unchanged_note, encoding="utf-8")
            entry["old_sha256"] = module.sha256_text(unchanged_note)
            entry["new_sha256"] = module.sha256_text(unchanged_note)
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [entry],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            target, entries = module.load_entries(manifest_path, set())

        self.assertEqual(target["collection_item_inventory"], ["PARENT01"])
        self.assertEqual(entries[0]["status"], "unchanged_verified")

    def test_load_entries_rejects_unchanged_verified_with_hash_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            entry = self._staged_entry(
                tmp_path,
                note_key="NOTE000A",
                parent_key="PARENT01",
            )
            unchanged = valid_note().replace(
                "a" * 64,
                entry["pdf_sha256"],
            )
            entry["status"] = "unchanged_verified"
            Path(str(entry["old_path"])).write_text(unchanged, encoding="utf-8")
            Path(str(entry["new_path"])).write_text(
                f"{unchanged}\nwith divergence",
                encoding="utf-8",
            )
            entry["old_sha256"] = module.sha256_text(unchanged)
            entry["new_sha256"] = module.sha256_text(
                f"{unchanged}\nwith divergence"
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [entry],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "unchanged note hashes are inconsistent",
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_unexpected_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "1",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [
                            {
                                "status": "staged_verified",
                                "note_key": "NOTE000A",
                                "parent_key": "PARENT01",
                                "expected_parent_key": "PARENT01",
                                "child_note_inventory": ["NOTE000A"],
                                "child_attachment_inventory": [],
                                "note_version": 1,
                                "old_path": f"{tmpdir}/old.html",
                                "new_path": f"{tmpdir}/new.html",
                                "old_sha256": module.sha256_text("<p>old</p>"),
                                "new_sha256": module.sha256_text("<p>new</p>"),
                                "pdf_path": f"{tmpdir}/a.pdf",
                                "pdf_sha256": "0" * 64,
                                "validation_summary": {
                                    "schema_version": "9",
                                    "full_text_sha256": "0" * 64,
                                },
                                "validation_errors": [],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "migration manifest version must be '2'"
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_invalid_or_ambiguous_batch_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01", "PARENT02"],
                        "entries": [
                            self._staged_entry(
                                tmp_path,
                                note_key="NOTE000A",
                                parent_key="PARENT01",
                            ),
                            {
                                "status": "blocked_multiple_notes",
                                "parent_key": "PARENT02",
                                "expected_parent_key": "PARENT02",
                                "note_key": "NOTEXIST",
                                "child_note_inventory": ["NOTE000B"],
                                "child_attachment_inventory": ["ATT00002"],
                                "note_version": 1,
                                "old_path": str(tmp_path / "old.html"),
                                "new_path": str(tmp_path / "new.html"),
                                "old_sha256": module.sha256_text("<old/>"),
                                "new_sha256": module.sha256_text("<new/>"),
                                "pdf_path": str(tmp_path / "paper.pdf"),
                                "pdf_sha256": module.sha256_bytes(b"%PDF-1.4\n%EOF"),
                                "validation_summary": {
                                    "schema_version": "9",
                                    "full_text_sha256": module.sha256_bytes(
                                        b"%PDF-1.4\n%EOF"
                                    ),
                                },
                                "validation_errors": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "invalid or ambiguous"):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_staged_child_inventory_not_matching_note_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [
                            self._staged_entry(
                                tmp_path,
                                note_key="NOTE000A",
                                parent_key="PARENT01",
                                child_note_inventory=["NOTE9999"],
                            ),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "staged child_note_inventory must be exactly the note key",
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_expected_parent_key_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [
                            self._staged_entry(
                                tmp_path,
                                note_key="NOTE000A",
                                parent_key="PARENT01",
                                expected_parent_key="PARENT02",
                            ),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "expected_parent_key does not match parent_key",
            ):
                module.load_entries(manifest_path, set())

    def test_load_entries_rejects_unsorted_child_note_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "2",
                        "write_performed": False,
                        "target": {
                            "group_id": 1234567,
                            "library_id": 1234567,
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "local_collection_id": "C1",
                            "collection_path": ["col"],
                            "collection_key": "COLL",
                        },
                        "collection_item_inventory": ["PARENT01"],
                        "entries": [
                            self._staged_entry(
                                tmp_path,
                                note_key="NOTE000A",
                                parent_key="PARENT01",
                                child_attachment_inventory=["ATT00002", "ATT00001"],
                            ),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "must be sorted in ascending order",
            ):
                module.load_entries(manifest_path, set())

    def test_resolve_target_contract_rejects_legacy_manifest(self) -> None:
        target = {
            "group_id": 1234567,
            "collection_key": "COLL",
            "collection_name": "集合",
        }
        with self.assertRaisesRegex(
            ValueError,
            "manifest target is missing required exact contract fields",
        ):
            module.resolve_target_contract(target)

    def test_verify_target_contract_accepts_strict_tree_view_collection_id(self) -> None:
        target = {
            "group_id": 1234567,
            "library_id": 2,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C27",
            "collection_path": ["foo", "target"],
            "collection_key": "COLL",
        }
        resolved = module.resolve_target_contract(target)

        selected = {
            "libraryID": "2",
            "libraryName": "PRIVATE_ZOTERO_TARGET",
            "name": "target",
            "editable": True,
            "filesEditable": True,
            "id": "27",
            "collectionPath": ["foo", "target"],
        }
        module.verify_target_match(selected, resolved)
        self.assertEqual(resolved["group_id"], 1234567)
        self.assertEqual(resolved["library_id"], 2)

    def test_verify_explicit_api_collection_contract_binds_group_key_and_path(
        self,
    ) -> None:
        target = {
            "group_id": 1234567,
            "library_id": 2,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "27",
            "collection_key": "LEAFKEY1",
            "collection_name": "Leaf",
            "collection_path": ["Root", "Leaf"],
        }
        with patch.object(
            module,
            "get_json",
            side_effect=[
                (
                    {},
                    {
                        "key": "LEAFKEY1",
                        "library": {
                            "type": "group",
                            "id": 1234567,
                            "name": "PRIVATE_ZOTERO_TARGET",
                        },
                        "data": {
                            "key": "LEAFKEY1",
                            "name": "Leaf",
                            "parentCollection": "ROOTKEY1",
                        },
                    },
                ),
                (
                    {},
                    {
                        "key": "ROOTKEY1",
                        "library": {
                            "type": "group",
                            "id": 1234567,
                            "name": "PRIVATE_ZOTERO_TARGET",
                        },
                        "data": {
                            "key": "ROOTKEY1",
                            "name": "Root",
                            "parentCollection": False,
                        },
                    },
                ),
            ],
        ):
            result = module.verify_explicit_api_collection_contract(target)

        self.assertTrue(result["verified"])
        self.assertEqual(result["collection_key"], "LEAFKEY1")
        self.assertEqual(result["collection_path"], ["Root", "Leaf"])

    def test_selected_target_reconstructs_exact_collection_path(self) -> None:
        payload = {
            "libraryID": 2,
            "libraryName": "PRIVATE_ZOTERO_TARGET",
            "id": 27,
            "name": "PRIVATE_ZOTERO_TARGET",
            "editable": True,
            "filesEditable": True,
            "targets": [
                {"id": "L1", "name": "我的文库", "level": 0},
                {"id": "C1", "name": "无关集合", "level": 1},
                {"id": "L2", "name": "PRIVATE_ZOTERO_TARGET", "level": 0},
                {"id": "C9", "name": "PRIVATE_ZOTERO_TARGET", "level": 1},
                {"id": "C20", "name": "PRIVATE_ZOTERO_TARGET", "level": 2},
                {
                    "id": "C27",
                    "name": "PRIVATE_ZOTERO_TARGET",
                    "level": 3,
                },
            ],
        }
        with patch.object(
            module,
            "request",
            return_value=(200, {}, json.dumps(payload).encode("utf-8")),
        ):
            selected = module.selected_target()

        self.assertEqual(
            selected["collectionPath"],
            ["PRIVATE_ZOTERO_TARGET", "PRIVATE_ZOTERO_TARGET", "PRIVATE_ZOTERO_TARGET"],
        )

    def test_preflight_web_route_checks_key_then_every_entry(self) -> None:
        locals_verified = [
            {"note_key": "NOTE000A"},
            {"note_key": "NOTE000B"},
        ]
        with (
            patch.object(
                module,
                "verify_web_key_access",
                return_value={
                    "group_id": 1234567,
                    "library": True,
                    "write": True,
                },
            ) as access_mock,
            patch.object(
                module,
                "verify_remote_entry",
                side_effect=[
                    {"version": 10, "old_html": "one", "old_sha256": "a" * 64},
                    {"version": 11, "old_html": "two", "old_sha256": "b" * 64},
                ],
            ) as entry_mock,
        ):
            access, remotes = module.preflight_web_route(
                1234567,
                "TESTCOL1",
                locals_verified,
                "web-secret-for-test",
            )

        access_mock.assert_called_once_with("web-secret-for-test", 1234567)
        self.assertEqual(entry_mock.call_count, 2)
        self.assertEqual(set(remotes), {"NOTE000A", "NOTE000B"})
        self.assertTrue(access["write"])

    def test_verify_remote_entry_checks_type_parent_collection_and_version(self) -> None:
        old_html = "<p>旧笔记</p>"
        local = {
            "note_key": "NOTE000A",
            "parent_key": "PARENT01",
            "old_sha256": module.sha256_text(old_html),
        }
        note_obj = {
            "data": {
                "itemType": "note",
                "parentItem": "PARENT01",
                "note": old_html,
            }
        }
        parent_obj = {
            "data": {
                "itemType": "journalArticle",
                "collections": ["TESTCOL1"],
            }
        }
        with patch.object(
            module,
            "get_json",
            side_effect=[
                ({"Last-Modified-Version": "77"}, note_obj),
                ({}, parent_obj),
            ],
        ) as get_json_mock:
            result = module.verify_remote_entry(
                1234567,
                "TESTCOL1",
                local,
                "web-secret-for-test",
            )

        self.assertEqual(result["version"], 77)
        self.assertEqual(result["old_sha256"], local["old_sha256"])
        self.assertEqual(get_json_mock.call_count, 2)

    def test_verify_remote_entry_rejects_bool_version(self) -> None:
        local = {
            "note_key": "NOTE000A",
            "parent_key": "PARENT01",
            "old_sha256": module.sha256_text("<p>旧笔记</p>"),
        }
        note_obj = {
            "version": True,
            "data": {
                "itemType": "note",
                "parentItem": "PARENT01",
                "note": "<p>旧笔记</p>",
            }
        }
        parent_obj = {
            "data": {
                "itemType": "journalArticle",
                "collections": ["TESTCOL1"],
            }
        }
        with patch.object(
            module,
            "get_json",
            side_effect=[
                ({"Last-Modified-Version": "77"}, note_obj),
                ({}, parent_obj),
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "version has invalid type bool"):
                module.verify_remote_entry(
                    1234567,
                    "TESTCOL1",
                    local,
                    "web-secret-for-test",
                )

    def test_verify_remote_entry_rejects_version_mismatch_with_header(self) -> None:
        local = {
            "note_key": "NOTE000A",
            "parent_key": "PARENT01",
            "old_sha256": module.sha256_text("<p>旧笔记</p>"),
        }
        note_obj = {
            "version": 12,
            "data": {
                "itemType": "note",
                "parentItem": "PARENT01",
                "note": "<p>旧笔记</p>",
            }
        }
        parent_obj = {
            "data": {
                "itemType": "journalArticle",
                "collections": ["TESTCOL1"],
            }
        }
        with patch.object(
            module,
            "get_json",
            side_effect=[
                ({"Last-Modified-Version": "77"}, note_obj),
                ({}, parent_obj),
            ],
        ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "version mismatch: body=12, header=77",
                ):
                    module.verify_remote_entry(
                        1234567,
                        "TESTCOL1",
                        local,
                        "web-secret-for-test",
                    )

    def test_verify_local_source_contract_rejects_modified_pdf_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            local = self._staged_entry(
                tmp_path,
                note_key="NOTE1234",
                parent_key="PARENT12",
            )
            local["group_id"] = 1234567
            local["pdf_attachment_key"] = "ATT00001"
            pdf_path = Path(str(local["pdf_path"]))
            pdf_path.write_bytes(b"%PDF-1.4\nmodified body\n%%EOF\n")
            with self.assertRaisesRegex(
                RuntimeError,
                "live approved PDF hash changed",
            ):
                module.verify_local_source_contract(local)

    def test_verify_local_source_contract_rejects_when_attachment_file_view_url_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            local = self._staged_entry(
                tmp_path,
                note_key="NOTE1234",
                parent_key="PARENT12",
            )
            local["group_id"] = 1234567
            local["pdf_attachment_key"] = "ATT00001"
            wrong_pdf = tmp_path / "other.pdf"
            wrong_pdf.write_bytes(b"%PDF-1.4\ndifferent body\n%%EOF\n")
            wrong_url = f"file://{wrong_pdf.resolve()}"
            with (
                patch.object(
                    module,
                    "request",
                    return_value=(200, {}, wrong_url.encode("utf-8")),
                ) as request_mock,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "live attachment file path changed",
                ):
                    module.verify_local_source_contract(local)
                request_mock.assert_called_once()
                request_url = request_mock.call_args.args[0]
                self.assertIn(
                    "/api/groups/1234567/items/ATT00001/file/view/url",
                    request_url,
                )

    def test_verify_local_source_contract_rejects_unsynced_local_note_edit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            local = self._staged_entry(
                tmp_path,
                note_key="NOTE1234",
                parent_key="PARENT12",
            )
            local.update(
                {
                    "group_id": 1234567,
                    "pdf_attachment_key": "ATT00001",
                    "local_version": 12,
                    "old_sha256": module.sha256_text("<p>旧笔记</p>"),
                }
            )
            pdf_url = f"file://{Path(str(local['pdf_path'])).resolve()}"
            edited_note = {
                "version": 13,
                "data": {
                    "itemType": "note",
                    "parentItem": "PARENT12",
                    "deleted": False,
                    "version": 13,
                    "note": "<p>未同步的本地编辑</p>",
                },
            }
            with (
                patch.object(
                    module,
                    "request",
                    return_value=(200, {}, pdf_url.encode("utf-8")),
                ),
                patch.object(
                    module,
                    "get_json",
                    return_value=({}, edited_note),
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "live local note version changed",
                ):
                    module.verify_local_source_contract(local)

    def test_patch_remote_note_treats_http_500_with_successful_readback_as_success(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        readback = (
            {"Last-Modified-Version": "10"},
            {
                "version": 10,
                "data": {
                    "itemType": "note",
                    "parentItem": "PARENT12",
                    "deleted": False,
                    "note": new_html,
                },
            },
        )
        parent = (
            {},
            {
                "data": {
                    "deleted": False,
                    "collections": ["COLL"],
                },
            },
        )
        with patch.object(
            module,
            "request",
            return_value=(500, {}, b"server error"),
        ), patch.object(
            module,
            "get_json",
            side_effect=[readback, parent],
        ):
            result = module.patch_remote_note(
                1234567,
                local,
                {"version": 9},
                "web-secret-for-test",
                "COLL",
            )

        self.assertTrue(result["remote_verified"])
        self.assertEqual(result["remote_version"], 10)

    def test_patch_remote_note_rechecks_local_source_after_inventory_guard(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        events: list[str] = []

        def inventory_guard(_: dict[str, object]) -> None:
            events.append("inventory")

        def source_guard() -> None:
            events.append("local-source")

        def patch_request(*_: object, **__: object) -> tuple[int, dict[str, str], bytes]:
            events.append("patch")
            return 204, {}, b""

        with (
            patch.object(module, "request", side_effect=patch_request),
            patch.object(
                module,
                "get_json",
                side_effect=[
                    (
                        {"Last-Modified-Version": "10"},
                        {
                            "version": 10,
                            "data": {
                                "itemType": "note",
                                "parentItem": "PARENT12",
                                "deleted": False,
                                "note": new_html,
                            },
                        },
                    ),
                    (
                        {},
                        {
                            "data": {
                                "deleted": False,
                                "collections": ["COLL"],
                            }
                        },
                    ),
                ],
            ),
        ):
            module.patch_remote_note(
                1234567,
                local,
                {"version": 9},
                "web-secret-for-test",
                "COLL",
                target_contract={"group_id": 1234567},
                pre_patch_contract_check=inventory_guard,
                source_contract_check=source_guard,
            )

        self.assertEqual(events[:3], ["inventory", "local-source", "patch"])

    def test_patch_remote_note_treats_http_500_with_readback_failure_as_outcome_unknown(
        self,
    ) -> None:
        new_html = "<p>中文</p>"
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with patch.object(
            module,
            "request",
            return_value=(500, {}, b"server error"),
        ), patch.object(
            module,
            "get_json",
            side_effect=RuntimeError("readback GET failed"),
        ):
            with self.assertRaisesRegex(
                module.MutationOutcomeUnknown,
                "mutation outcome unknown",
            ):
                module.patch_remote_note(
                    1234567,
                    local,
                    {"version": 9},
                    "web-secret-for-test",
                    "COLL",
                )

    def test_patch_remote_note_reads_back_and_validates_type_parent_collection_and_new_version(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with (
            patch.object(
                module,
                "request",
                return_value=(204, {}, b""),
            ),
            patch.object(
                module,
                "get_json",
                side_effect=[
                    (
                        {"Last-Modified-Version": "10"},
                        {
                            "version": "10",
                            "data": {
                                "itemType": "note",
                                "parentItem": "PARENT12",
                                "deleted": False,
                                "note": new_html,
                            },
                        },
                    ),
                    (
                        {},
                        {
                            "data": {
                                "deleted": False,
                                "collections": ["COLL"],
                            }
                        },
                    ),
                ],
            ),
        ):
            result = module.patch_remote_note(
                1234567,
                local,
                {"version": 9},
                "web-secret-for-test",
                "COLL",
            )

        self.assertTrue(result["remote_verified"])
        self.assertEqual(result["remote_version"], 10)

    def test_patch_remote_note_raises_mutation_accepted_when_readback_fails(self) -> None:
        new_html = "<p>中文</p>"
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with (
            patch.object(
                module,
                "request",
                return_value=(204, {}, b""),
            ),
            patch.object(
                module,
                "get_json",
                side_effect=RuntimeError("readback GET failed"),
            ),
        ):
            with self.assertRaisesRegex(
                module.MutationAcceptedButUnverified,
                "mutation accepted but unverified",
            ):
                module.patch_remote_note(
                    1234567,
                    local,
                    {"version": 9},
                    "web-secret-for-test",
                    "COLL",
                )

    def test_patch_remote_note_raises_outcome_unknown_when_transport_error_and_readback_is_inconclusive(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with (
            patch.object(
                module,
                "request",
                side_effect=module.urllib.error.URLError("temporary network failure"),
            ),
            patch.object(
                module,
                "get_json",
                side_effect=RuntimeError("readback GET failed"),
            ),
        ):
            with self.assertRaisesRegex(
                module.MutationOutcomeUnknown,
                "mutation outcome unknown",
            ):
                module.patch_remote_note(
                    1234567,
                    local,
                    {"version": 9},
                    "web-secret-for-test",
                    "COLL",
                )

    def test_patch_remote_note_treats_transport_error_with_successful_readback_as_success(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        readback = (
            {"Last-Modified-Version": "10"},
            {
                "version": 10,
                "data": {
                    "itemType": "note",
                    "parentItem": "PARENT12",
                    "deleted": False,
                    "note": new_html,
                },
            },
        )
        parent = (
            {},
            {
                "data": {
                    "deleted": False,
                    "collections": ["COLL"],
                },
            },
        )
        with patch.object(
            module,
            "request",
            side_effect=module.urllib.error.URLError("temporary network failure"),
        ), patch.object(
            module,
            "get_json",
            side_effect=[readback, parent],
        ):
            result = module.patch_remote_note(
                1234567,
                local,
                {"version": 9},
                "web-secret-for-test",
                "COLL",
            )

        self.assertTrue(result["remote_verified"])
        self.assertEqual(result["remote_version"], 10)

    def test_patch_remote_note_treats_transport_error_with_readback_as_unverified_when_post_contract_fails(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        readback = (
            {"Last-Modified-Version": "10"},
            {
                "version": 10,
                "data": {
                    "itemType": "note",
                    "parentItem": "PARENT12",
                    "deleted": False,
                    "note": new_html,
                },
            },
        )
        parent = (
            {},
            {
                "data": {
                    "deleted": False,
                    "collections": ["COLL"],
                },
            },
        )

        def _fail_contract(_: dict[str, object]) -> None:
            raise RuntimeError("contract changed after patch")

        with patch.object(
            module,
            "request",
            side_effect=module.urllib.error.URLError("temporary network failure"),
        ), patch.object(
            module,
            "get_json",
            side_effect=[readback, parent],
        ):
            with self.assertRaisesRegex(
                module.MutationAcceptedButUnverified,
                "post-patch contract changed",
            ):
                module.patch_remote_note(
                    1234567,
                    local,
                    {"version": 9},
                    "web-secret-for-test",
                    "COLL",
                    target_contract={"group_id": 1234567},
                    post_patch_contract_check=_fail_contract,
                )
    def test_main_dry_run_has_no_backups_or_patches(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_item_inventory": ["PARENT01"],
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE1234",
                "expected_parent_key": "PARENT12",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
        ]
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(
                module,
                "verify_local_entry",
                return_value={
                    "note_key": "NOTE1234",
                    "parent_key": "PARENT12",
                    "local_version": 1,
                    "old_sha256": module.sha256_text("<p>old</p>"),
                    "new_sha256": module.sha256_text("<p>new</p>"),
                    "old_html": "<p>old</p>",
                    "new_html": "<p>new</p>",
                    "new_path": "/tmp/new.html",
                },
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(module, "backup_note") as backup_note_mock,
            patch.object(module, "patch_local_note") as patch_local_mock,
            patch.object(module.sys, "argv", ["update_existing_note.py", "manifest.json"]),
        ):
            result = module.main()

        self.assertEqual(result, module.EXIT_OK)
        backup_note_mock.assert_not_called()
        patch_local_mock.assert_not_called()

    def test_main_apply_requires_explicit_group_key_confirmation(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 2,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 1,
            "old_sha256": module.sha256_text("<p>old</p>"),
            "new_sha256": module.sha256_text("<p>new</p>"),
            "old_html": "<p>old</p>",
            "new_html": "<p>new</p>",
        }
        stderr = io.StringIO()
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, [{"status": "staged_verified"}]),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "2",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={
                    "group_id": 1234567,
                    "collection_key": "COLL",
                    "verified": True,
                },
            ),
            patch.object(module, "verify_local_entry", return_value=local),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(module, "backup_note") as backup_note_mock,
            patch.object(module, "patch_local_note") as patch_local_mock,
            patch.object(
                module.sys,
                "argv",
                ["update_existing_note.py", "--yes", "manifest.json"],
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main()

        report = stderr.getvalue()
        self.assertEqual(result, module.EXIT_CAPABILITY)
        self.assertIn("capability_blocked", report)
        parsed = json.loads(report)
        self.assertFalse(parsed["write_performed"])
        backup_note_mock.assert_not_called()
        patch_local_mock.assert_not_called()

    def test_main_apply_rejects_second_child_note_during_local_preflight(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_item_inventory": ["PARENT01", "PARENT02"],
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE000A",
                "expected_parent_key": "PARENT01",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
            {
                "status": "staged_verified",
                "note_key": "NOTE000B",
                "expected_parent_key": "PARENT02",
                "note_version": 2,
                "new_path": "/tmp/new2.html",
                "new_sha256": module.sha256_text("<p>new2</p>"),
                "old_sha256": module.sha256_text("<p>old2</p>"),
            },
        ]
        stderr = io.StringIO()
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"group_id": 1234567, "verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(
                module,
                "verify_local_entry",
                side_effect=[
                    {
                        "note_key": "NOTE000A",
                        "parent_key": "PARENT01",
                        "local_version": 1,
                        "old_sha256": module.sha256_text("<p>old</p>"),
                        "new_sha256": module.sha256_text("<p>new</p>"),
                        "old_html": "<p>old</p>",
                        "new_html": "<p>new</p>",
                    },
                    RuntimeError("second child note rejected"),
                ],
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(module, "authorize_local") as authorize_local_mock,
            patch.object(module, "backup_note") as backup_note_mock,
            patch.object(module, "patch_local_note") as patch_local_mock,
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main()

        report = stderr.getvalue()
        self.assertEqual(result, module.EXIT_CONFLICT)
        authorize_local_mock.assert_not_called()
        backup_note_mock.assert_not_called()
        patch_local_mock.assert_not_called()
        self.assertIn("preflight failed", report)

    def test_main_yes_rejects_unchanged_note_key(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "unchanged_verified",
                "note_key": "NOTE000A",
                "expected_parent_key": "PARENT01",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
                "parent_key": "PARENT01",
            },
        ]
        stderr = io.StringIO()
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(
                module,
                "verify_local_entry",
                return_value={
                    "note_key": "NOTE000A",
                    "parent_key": "PARENT01",
                    "local_version": 1,
                    "old_sha256": module.sha256_text("<p>old</p>"),
                    "new_sha256": module.sha256_text("<p>new</p>"),
                    "old_html": "<p>old</p>",
                    "new_html": "<p>new</p>",
                },
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(module, "backup_note") as backup_note_mock,
            patch.object(module, "patch_local_note") as patch_local_mock,
            patch.object(module.sys, "argv", [
                "update_existing_note.py",
                "--yes",
                "--note-key",
                "NOTE000A",
                "manifest.json",
            ]),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main()

        self.assertEqual(result, module.EXIT_CONFLICT)
        self.assertIn("requested note keys are not mutable", stderr.getvalue())
        backup_note_mock.assert_not_called()
        patch_local_mock.assert_not_called()

    def test_main_yes_rejects_apply_if_local_source_contract_fails_for_verified_unchanged_entry(
        self,
    ) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
            "collection_item_inventory": ["PARENT01", "PARENT02"],
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE000A",
                "expected_parent_key": "PARENT01",
                "note_version": 1,
                "parent_key": "PARENT01",
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
            {
                "status": "unchanged_verified",
                "note_key": "NOTE000B",
                "expected_parent_key": "PARENT02",
                "note_version": 2,
                "parent_key": "PARENT02",
                "new_path": "/tmp/new2.html",
                "new_sha256": module.sha256_text("<p>new2</p>"),
                "old_sha256": module.sha256_text("<p>old2</p>"),
            },
        ]
        stderr = io.StringIO()
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(
                module,
                "verify_local_entry",
                side_effect=[
                    {
                        "note_key": "NOTE000A",
                        "parent_key": "PARENT01",
                        "local_version": 1,
                        "old_sha256": module.sha256_text("<p>old</p>"),
                        "new_sha256": module.sha256_text("<p>new</p>"),
                        "old_html": "<p>old</p>",
                        "new_html": "<p>new</p>",
                    },
                    {
                        "note_key": "NOTE000B",
                        "parent_key": "PARENT02",
                        "local_version": 2,
                        "old_sha256": module.sha256_text("<p>old2</p>"),
                        "new_sha256": module.sha256_text("<p>new2</p>"),
                        "old_html": "<p>old2</p>",
                        "new_html": "<p>new2</p>",
                    },
                ],
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(
                module,
                "verify_local_source_contract",
                side_effect=[None, RuntimeError("unchanged note drifted")],
            ) as verify_source_mock,
            patch.object(module, "authorize_local") as authorize_local_mock,
            patch.object(module, "backup_note") as backup_note_mock,
            patch.object(module, "patch_local_note") as patch_local_mock,
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main()

        report = json.loads(stderr.getvalue())
        self.assertEqual(result, module.EXIT_CONFLICT)
        self.assertEqual(report["status"], "preflight_failed")
        self.assertEqual(report["selected_route"], "local")
        self.assertIn("preflight failed", report.get("error", ""))
        verify_calls = [call.args[0] for call in verify_source_mock.call_args_list]
        self.assertEqual(
            [item["note_key"] for item in verify_calls],
            ["NOTE000A", "NOTE000B"],
        )
        authorize_local_mock.assert_not_called()
        backup_note_mock.assert_not_called()
        patch_local_mock.assert_not_called()

    def test_main_yes_applies_only_staged_and_skips_unchanged_inventory(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
            "collection_item_inventory": ["PARENT01", "PARENT02"],
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE000A",
                "expected_parent_key": "PARENT01",
                "note_version": 1,
                "parent_key": "PARENT01",
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
            {
                "status": "unchanged_verified",
                "note_key": "NOTE000B",
                "expected_parent_key": "PARENT02",
                "note_version": 2,
                "parent_key": "PARENT02",
                "new_path": "/tmp/new2.html",
                "new_sha256": module.sha256_text("<p>new2</p>"),
                "old_sha256": module.sha256_text("<p>old2</p>"),
            },
        ]
        events: list[str] = []

        def record_backup(
            backup_dir: Path,
            note_key: str,
            version: int,
            _old_html: str,
        ) -> str:
            events.append(f"backup:{note_key}")
            return str(backup_dir / f"{note_key}.html")

        def record_patch(
            group_id: int,
            local: dict[str, object],
            *_args: object,
            **_kwargs: object,
        ) -> dict[str, object]:
            events.append(f"patch:{local['note_key']}")
            return {"local_version": 2, "local_verified": True}

        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(module, "verify_local_source_contract", return_value=None),
            patch.object(
                module,
                "verify_local_entry",
                side_effect=[
                    {
                        "note_key": "NOTE000A",
                        "parent_key": "PARENT01",
                        "local_version": 1,
                        "old_sha256": module.sha256_text("<p>old</p>"),
                        "new_sha256": module.sha256_text("<p>new</p>"),
                        "old_html": "<p>old</p>",
                        "new_html": "<p>new</p>",
                        "group_id": 1234567,
                        "pdf_attachment_key": "PDFATTA1",
                        "pdf_sha256": "a" * 64,
                        "pdf_path": "/tmp/NOTE000A.pdf",
                    },
                    {
                        "note_key": "NOTE000B",
                        "parent_key": "PARENT02",
                        "local_version": 2,
                        "old_sha256": module.sha256_text("<p>old2</p>"),
                        "new_sha256": module.sha256_text("<p>new2</p>"),
                        "old_html": "<p>old2</p>",
                        "new_html": "<p>new2</p>",
                        "group_id": 1234567,
                        "pdf_attachment_key": "PDFATTB1",
                        "pdf_sha256": "b" * 64,
                        "pdf_path": "/tmp/NOTE000B.pdf",
                    },
                ],
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(
                module,
                "authorize_local",
                return_value={"api_key": "local-key", "remember": True},
            ),
            patch.object(module, "backup_note", side_effect=record_backup),
            patch.object(module, "patch_local_note", side_effect=record_patch),
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
        ):
            result = module.main()

        self.assertEqual(result, module.EXIT_OK)
        self.assertEqual(events, ["backup:NOTE000A", "patch:NOTE000A"])

    def test_main_yes_no_staged_entries_skips_all_backup_and_patch(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_item_inventory": ["PARENT01", "PARENT02"],
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "unchanged_verified",
                "note_key": "NOTE000A",
                "expected_parent_key": "PARENT01",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
                "parent_key": "PARENT01",
            },
            {
                "status": "unchanged_verified",
                "note_key": "NOTE000B",
                "expected_parent_key": "PARENT02",
                "note_version": 2,
                "new_path": "/tmp/new2.html",
                "new_sha256": module.sha256_text("<p>new2</p>"),
                "old_sha256": module.sha256_text("<p>old2</p>"),
                "parent_key": "PARENT02",
            },
        ]
        stdout = io.StringIO()
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(
                module,
                "verify_local_entry",
                side_effect=[
                    {
                        "note_key": "NOTE000A",
                        "parent_key": "PARENT01",
                        "local_version": 1,
                        "old_sha256": module.sha256_text("<p>old</p>"),
                        "new_sha256": module.sha256_text("<p>new</p>"),
                        "old_html": "<p>old</p>",
                        "new_html": "<p>new</p>",
                    },
                    {
                        "note_key": "NOTE000B",
                        "parent_key": "PARENT02",
                        "local_version": 2,
                        "old_sha256": module.sha256_text("<p>old2</p>"),
                        "new_sha256": module.sha256_text("<p>new2</p>"),
                        "old_html": "<p>old2</p>",
                        "new_html": "<p>new2</p>",
                    },
                ],
            ),
            patch.object(
                module,
                "choose_route",
                return_value="local",
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(module, "backup_note") as backup_note_mock,
            patch.object(module, "patch_local_note") as patch_local_mock,
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "manifest.json",
                ],
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = module.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(result, module.EXIT_OK)
        self.assertEqual(report["status"], "no_changes")
        self.assertEqual(report["mutation_count"], 0)
        self.assertFalse(report["write_performed"])
        backup_note_mock.assert_not_called()
        patch_local_mock.assert_not_called()

    def test_main_web_apply_rejects_second_child_note_during_remote_preflight(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE000A",
                "expected_parent_key": "PARENT01",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
            {
                "status": "staged_verified",
                "note_key": "NOTE000B",
                "expected_parent_key": "PARENT02",
                "note_version": 2,
                "new_path": "/tmp/new2.html",
                "new_sha256": module.sha256_text("<p>new2</p>"),
                "old_sha256": module.sha256_text("<p>old2</p>"),
            },
        ]
        stderr = io.StringIO()
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"group_id": 1234567, "verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(
                module,
                "verify_web_key_access",
                return_value={"group_id": 1234567, "library": True, "write": True},
            ),
            patch.object(
                module,
                "verify_remote_entry",
                side_effect=[
                    {
                        "version": 12,
                        "old_html": "<p>old</p>",
                        "old_sha256": module.sha256_text("<p>old</p>"),
                    },
                    RuntimeError("second child note rejected"),
                ],
            ),
            patch.object(
                module,
                "verify_local_entry",
                side_effect=[
                    {
                        "note_key": "NOTE000A",
                        "parent_key": "PARENT01",
                        "local_version": 1,
                        "old_sha256": module.sha256_text("<p>old</p>"),
                        "new_sha256": module.sha256_text("<p>new</p>"),
                        "old_html": "<p>old</p>",
                        "new_html": "<p>new</p>",
                    },
                    {
                        "note_key": "NOTE000B",
                        "parent_key": "PARENT02",
                        "local_version": 2,
                        "old_sha256": module.sha256_text("<p>old2</p>"),
                        "new_sha256": module.sha256_text("<p>new2</p>"),
                        "old_html": "<p>old2</p>",
                        "new_html": "<p>new2</p>",
                    },
                ],
            ),
            patch.object(module, "probe_local_write", return_value={"supported": False}),
            patch.object(module, "backup_note") as backup_note_mock,
            patch.object(module, "patch_remote_note") as patch_remote_mock,
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
            patch.dict(os.environ, {"ZOTERO_API_KEY": "web-secret"}),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main()

        self.assertEqual(result, module.EXIT_CONFLICT)
        backup_note_mock.assert_not_called()
        patch_remote_mock.assert_not_called()
        self.assertIn("preflight_failed", stderr.getvalue())

    def test_main_stops_without_patching_when_web_preflight_fails(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE1234",
                "expected_parent_key": "PARENT12",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
        ]
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(
                module,
                "verify_local_entry",
                return_value={
                    "note_key": "NOTE1234",
                    "parent_key": "PARENT12",
                    "local_version": 1,
                    "old_sha256": module.sha256_text("<p>old</p>"),
                    "new_sha256": module.sha256_text("<p>new</p>"),
                    "old_html": "<p>old</p>",
                    "new_html": "<p>new</p>",
                    "new_path": "/tmp/new.html",
                },
            ),
            patch.object(module, "probe_local_write", return_value={"supported": False}),
            patch.object(
                module,
                "preflight_web_route",
                side_effect=RuntimeError("remote preflight failed"),
            ),
            patch.object(module, "backup_note") as backup_note_mock,
            patch.object(module, "patch_remote_note") as patch_remote_mock,
            patch.object(module, "patch_local_note") as patch_local_mock,
            patch.object(module.sys, "argv", ["update_existing_note.py", "--yes", "manifest.json"]),
            patch.dict(os.environ, {"ZOTERO_API_KEY": "web-secret"}),
        ):
            result = module.main()

        self.assertEqual(result, module.EXIT_CONFLICT)
        backup_note_mock.assert_not_called()
        patch_remote_mock.assert_not_called()
        patch_local_mock.assert_not_called()

    def test_main_web_inventory_checks_use_non_api_group_route(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE000A",
                "expected_parent_key": "PARENT01",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
        ]
        local = {
            "note_key": "NOTE000A",
            "parent_key": "PARENT01",
            "local_version": 1,
            "old_sha256": module.sha256_text("<p>old</p>"),
            "new_sha256": module.sha256_text("<p>new</p>"),
            "old_html": "<p>old</p>",
            "new_html": "<p>new</p>",
            "group_id": 1234567,
            "pdf_attachment_key": "PDFATTA1",
            "pdf_sha256": "a" * 64,
            "pdf_path": "/tmp/NOTE000A.pdf",
        }
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={
                    "group_id": 1234567,
                    "collection_key": "COLL",
                    "verified": True,
                },
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ) as verify_inventory_mock,
            patch.object(module, "verify_local_entry", return_value=local),
            patch.object(module, "verify_local_source_contract", return_value=None),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": False},
            ),
            patch.object(
                module,
                "preflight_web_route",
                return_value=(
                    {
                        "group_id": 1234567,
                        "library": True,
                        "write": True,
                    },
                    {
                        "NOTE000A": {
                            "version": 10,
                            "old_html": "<p>old</p>",
                            "old_sha256": module.sha256_text("<p>old</p>"),
                        },
                    },
                ),
            ),
            patch.object(
                module,
                "backup_note",
                return_value="/tmp/NOTE000A.html",
            ) as backup_mock,
            patch.object(
                module,
                "patch_remote_note",
                return_value={"remote_version": 11, "remote_verified": True},
            ) as patch_remote_mock,
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
            patch.dict(os.environ, {"ZOTERO_API_KEY": "web-secret"}),
        ):
            result = module.main()

        self.assertEqual(result, module.EXIT_OK)
        self.assertEqual(backup_mock.call_count, 1)
        self.assertEqual(patch_remote_mock.call_count, 1)
        verify_inventory_mock.assert_any_call(
            base_api=module.LOCAL_BASE,
            group_id=1234567,
            collection_key="COLL",
            entries=entries,
            headers=None,
            group_route="/api/groups",
        )
        verify_inventory_mock.assert_any_call(
            base_api=module.WEB_BASE,
            group_id=1234567,
            collection_key="COLL",
            entries=entries,
            headers=module.web_headers("web-secret"),
            group_route="/groups",
        )

    def test_main_reports_partial_failure_when_mutation_accepted_but_unverified(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE1234",
                "expected_parent_key": "PARENT12",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
            {
                "status": "staged_verified",
                "note_key": "NOTE5678",
                "expected_parent_key": "PARENT56",
                "note_version": 2,
                "new_path": "/tmp/new2.html",
                "new_sha256": module.sha256_text("<p>new2</p>"),
                "old_sha256": module.sha256_text("<p>old2</p>"),
            },
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(module, "verify_local_source_contract", return_value=None),
            patch.object(
                module,
                "verify_local_entry",
                side_effect=[
                    {
                        "note_key": "NOTE1234",
                        "parent_key": "PARENT12",
                        "local_version": 1,
                        "old_sha256": module.sha256_text("<p>old</p>"),
                        "new_sha256": module.sha256_text("<p>new</p>"),
                        "old_html": "<p>old</p>",
                        "new_html": "<p>new</p>",
                        "group_id": 1234567,
                        "pdf_attachment_key": "PDFATTA1",
                        "pdf_sha256": "a" * 64,
                        "pdf_path": "/tmp/NOTE1234.pdf",
                    },
                    {
                        "note_key": "NOTE5678",
                        "parent_key": "PARENT56",
                        "local_version": 2,
                        "old_sha256": module.sha256_text("<p>old2</p>"),
                        "new_sha256": module.sha256_text("<p>new2</p>"),
                        "old_html": "<p>old2</p>",
                        "new_html": "<p>new2</p>",
                        "group_id": 1234567,
                        "pdf_attachment_key": "PDFATTB1",
                        "pdf_sha256": "b" * 64,
                        "pdf_path": "/tmp/NOTE5678.pdf",
                    },
                ],
            ),
            patch.object(module, "probe_local_write", return_value={"supported": True, "server_id": "server-1"}),
            patch.object(module, "authorize_local", return_value={"api_key": "local", "remember": True}),
            patch.object(
                module,
                "backup_note",
                side_effect=[
                    "/tmp/NOTE1234.html",
                    "/tmp/NOTE5678.html",
                ],
            ),
            patch.object(
                module,
                "patch_local_note",
                side_effect=[
                    module.MutationAcceptedButUnverified(
                        "NOTE1234",
                        "PARENT12",
                        "GET failed",
                    ),
                    {
                        "local_version": 99,
                        "local_verified": True,
                    },
                ],
            ),
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main()

        report = json.loads(stderr.getvalue())
        self.assertEqual(result, module.EXIT_CONFLICT)
        self.assertEqual(report["status"], "partial_failure")
        self.assertTrue(report["write_performed"])
        self.assertEqual(
            report["accepted_but_unverified"],
            {
                "note_key": "NOTE1234",
                "parent_key": "PARENT12",
                "backup": "/tmp/NOTE1234.html",
            },
        )
        self.assertEqual(report["completed"], [])

    def test_main_reports_partial_failure_when_mutation_outcome_unknown(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE1234",
                "expected_parent_key": "PARENT12",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
        ]
        stderr = io.StringIO()
        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(module, "verify_local_source_contract", return_value=None),
            patch.object(
                module,
                "verify_local_entry",
                return_value={
                    "note_key": "NOTE1234",
                    "parent_key": "PARENT12",
                    "local_version": 1,
                    "old_sha256": module.sha256_text("<p>old</p>"),
                    "new_sha256": module.sha256_text("<p>new</p>"),
                    "old_html": "<p>old</p>",
                    "new_html": "<p>new</p>",
                    "new_path": "/tmp/new.html",
                    "group_id": 1234567,
                    "pdf_attachment_key": "PDFATTA1",
                    "pdf_sha256": "a" * 64,
                    "pdf_path": "/tmp/NOTE1234.pdf",
                },
            ),
            patch.object(module, "probe_local_write", return_value={"supported": True, "server_id": "server-1"}),
            patch.object(module, "authorize_local", return_value={"api_key": "local", "remember": True}),
            patch.object(module, "backup_note", return_value="/tmp/NOTE1234.html"),
            patch.object(
                module,
                "patch_local_note",
                side_effect=module.MutationOutcomeUnknown(
                    "NOTE1234",
                    "PARENT12",
                    "transport error with inconclusive readback",
                ),
            ),
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main()

        report = json.loads(stderr.getvalue())
        self.assertEqual(result, module.EXIT_CONFLICT)
        self.assertEqual(report["status"], "partial_failure")
        self.assertIsNone(report["write_performed"])
        self.assertEqual(
            report["outcome_unknown"],
            {
                "note_key": "NOTE1234",
                "parent_key": "PARENT12",
                "backup": "/tmp/NOTE1234.html",
            },
        )
        self.assertEqual(report["completed"], [])

    def test_main_no_patch_when_first_backup_fails(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE1234",
                "expected_parent_key": "PARENT12",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
            {
                "status": "staged_verified",
                "note_key": "NOTE5678",
                "expected_parent_key": "PARENT56",
                "note_version": 2,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new2</p>"),
                "old_sha256": module.sha256_text("<p>old2</p>"),
            },
        ]

        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(module, "verify_local_source_contract", return_value=None),
            patch.object(
                module,
                "verify_local_entry",
                side_effect=[
                    {
                        "note_key": "NOTE1234",
                        "parent_key": "PARENT12",
                        "local_version": 1,
                        "old_sha256": module.sha256_text("<p>old</p>"),
                        "new_sha256": module.sha256_text("<p>new</p>"),
                        "old_html": "<p>old</p>",
                        "new_html": "<p>new</p>",
                        "group_id": 1234567,
                        "pdf_attachment_key": "PDFATTA1",
                        "pdf_sha256": "a" * 64,
                        "pdf_path": "/tmp/NOTE1234.pdf",
                    },
                    {
                        "note_key": "NOTE5678",
                        "parent_key": "PARENT56",
                        "local_version": 2,
                        "old_sha256": module.sha256_text("<p>old2</p>"),
                        "new_sha256": module.sha256_text("<p>new2</p>"),
                        "old_html": "<p>old2</p>",
                        "new_html": "<p>new2</p>",
                        "group_id": 1234567,
                        "pdf_attachment_key": "PDFATTB1",
                        "pdf_sha256": "b" * 64,
                        "pdf_path": "/tmp/NOTE5678.pdf",
                    },
                ],
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(
                module,
                "authorize_local",
                return_value={"api_key": "local", "remember": True},
            ),
            patch.object(
                module,
                "backup_note",
                side_effect=RuntimeError("backup failed"),
            ) as backup_note_mock,
            patch.object(module, "patch_local_note") as patch_local_mock,
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
        ):
            result = module.main()

        self.assertEqual(result, module.EXIT_CONFLICT)
        self.assertEqual(backup_note_mock.call_count, 1)
        patch_local_mock.assert_not_called()

    def test_main_backups_are_created_before_any_patch(self) -> None:
        manifest = {
            "group_id": 1234567,
            "library_id": 1234567,
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "local_collection_id": "C1",
            "collection_path": ["集合"],
            "collection_key": "COLL",
        }
        entries = [
            {
                "status": "staged_verified",
                "note_key": "NOTE1234",
                "expected_parent_key": "PARENT12",
                "note_version": 1,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new</p>"),
                "old_sha256": module.sha256_text("<p>old</p>"),
            },
            {
                "status": "staged_verified",
                "note_key": "NOTE5678",
                "expected_parent_key": "PARENT56",
                "note_version": 2,
                "new_path": "/tmp/new.html",
                "new_sha256": module.sha256_text("<p>new2</p>"),
                "old_sha256": module.sha256_text("<p>old2</p>"),
            },
        ]
        events: list[str] = []

        def record_backup(*args: object) -> str:
            events.append(f"backup:{args[1]}")
            return f"/tmp/{args[1]}.html"

        def record_patch(*args: object, **_: object) -> dict[str, object]:
            local = args[1]
            events.append(f"patch:{local['note_key']}")
            return {"local_version": 99, "local_verified": True}

        with (
            patch.object(
                module,
                "load_entries",
                return_value=(manifest, entries),
            ),
            patch.object(
                module,
                "selected_target",
                return_value={
                    "libraryID": "1234567",
                    "libraryName": "PRIVATE_ZOTERO_TARGET",
                    "name": "集合",
                    "id": "C1",
                    "collectionPath": ["集合"],
                    "editable": True,
                    "filesEditable": True,
                },
            ),
            patch.object(
                module,
                "verify_explicit_api_collection_contract",
                return_value={"verified": True},
            ),
            patch.object(
                module,
                "verify_inventory_contract",
                return_value=None,
            ),
            patch.object(module, "verify_local_source_contract", return_value=None),
            patch.object(
                module,
                "verify_local_entry",
                side_effect=[
                    {
                        "note_key": "NOTE1234",
                        "parent_key": "PARENT12",
                        "local_version": 1,
                        "old_sha256": module.sha256_text("<p>old</p>"),
                        "new_sha256": module.sha256_text("<p>new</p>"),
                        "old_html": "<p>old</p>",
                        "new_html": "<p>new</p>",
                        "group_id": 1234567,
                        "pdf_attachment_key": "PDFATTA1",
                        "pdf_sha256": "a" * 64,
                        "pdf_path": "/tmp/NOTE1234.pdf",
                    },
                    {
                        "note_key": "NOTE5678",
                        "parent_key": "PARENT56",
                        "local_version": 2,
                        "old_sha256": module.sha256_text("<p>old2</p>"),
                        "new_sha256": module.sha256_text("<p>new2</p>"),
                        "old_html": "<p>old2</p>",
                        "new_html": "<p>new2</p>",
                        "group_id": 1234567,
                        "pdf_attachment_key": "PDFATTB1",
                        "pdf_sha256": "b" * 64,
                        "pdf_path": "/tmp/NOTE5678.pdf",
                    },
                ],
            ),
            patch.object(
                module,
                "probe_local_write",
                return_value={"supported": True, "server_id": "server-1"},
            ),
            patch.object(
                module,
                "authorize_local",
                return_value={"api_key": "local", "remember": True},
            ),
            patch.object(module, "backup_note", side_effect=record_backup),
            patch.object(module, "patch_local_note", side_effect=record_patch),
            patch.object(
                module.sys,
                "argv",
                [
                    "update_existing_note.py",
                    "--yes",
                    "--confirm-explicit-api-target",
                    "manifest.json",
                ],
            ),
        ):
            result = module.main()

        self.assertEqual(result, module.EXIT_OK)
        self.assertEqual(
            events,
            [
                "backup:NOTE1234",
                "backup:NOTE5678",
                "patch:NOTE1234",
                "patch:NOTE5678",
            ],
        )

    def test_patch_local_note_uses_version_guard_and_reads_back(self) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 123,
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with (
            patch.object(
                module,
                "request",
                return_value=(204, {}, b""),
            ) as request_mock,
            patch.object(
                module,
                "get_json",
                side_effect=[
                    (
                        {},
                        {
                            "version": 124,
                            "data": {
                                "itemType": "note",
                                "parentItem": "PARENT12",
                                "note": new_html,
                                "version": 124,
                            },
                        },
                    ),
                    (
                        {},
                        {
                            "data": {
                                "deleted": False,
                                "collections": ["COLL"],
                            }
                        },
                    ),
                ],
            ),
        ):
            result = module.patch_local_note(
                1234567,
                local,
                "local-secret-for-test",
                "instance-123",
                "COLL",
            )

        self.assertTrue(result["local_verified"])
        self.assertEqual(result["local_version"], 124)
        _, kwargs = request_mock.call_args
        self.assertEqual(kwargs["method"], "PATCH")
        self.assertEqual(
            kwargs["headers"]["If-Unmodified-Since-Version"],
            "123",
        )
        self.assertEqual(
            kwargs["headers"]["Zotero-Server-ID"],
            "instance-123",
        )
        self.assertEqual(
            kwargs["headers"]["Zotero-API-Key"],
            "local-secret-for-test",
        )
        self.assertEqual(kwargs["payload"], {"note": new_html})

    def test_patch_local_note_raises_mutation_accepted_when_readback_fails(self) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 123,
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with (
            patch.object(
                module,
                "request",
                return_value=(204, {}, b""),
            ),
            patch.object(
                module,
                "get_json",
                side_effect=RuntimeError("local readback GET failed"),
            ),
        ):
            with self.assertRaisesRegex(
                module.MutationAcceptedButUnverified,
                "mutation accepted but unverified",
            ):
                module.patch_local_note(
                    1234567,
                    local,
                    "local-secret-for-test",
                    "instance-123",
                    "COLL",
                )

    def test_patch_local_note_raises_outcome_unknown_when_transport_error_and_readback_is_inconclusive(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 123,
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with (
            patch.object(
                module,
                "request",
                side_effect=module.urllib.error.URLError("temporary network failure"),
            ),
            patch.object(
                module,
                "get_json",
                side_effect=RuntimeError("local readback GET failed"),
            ),
        ):
            with self.assertRaisesRegex(
                module.MutationOutcomeUnknown,
                "mutation outcome unknown",
            ):
                module.patch_local_note(
                    1234567,
                    local,
                    "local-secret-for-test",
                    "instance-123",
                    "COLL",
                )

    def test_patch_local_note_treats_http_500_with_successful_readback_as_success(self) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 123,
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        readback = (
            {},
            {
                "version": 124,
                "data": {
                    "itemType": "note",
                    "parentItem": "PARENT12",
                    "note": new_html,
                    "version": 124,
                    "deleted": False,
                },
            },
        )
        parent = (
            {},
            {
                "data": {
                    "deleted": False,
                    "collections": ["COLL"],
                },
            },
        )
        with patch.object(
            module,
            "request",
            return_value=(500, {}, b"server error"),
        ), patch.object(
            module,
            "get_json",
            side_effect=[readback, parent],
        ):
            result = module.patch_local_note(
                1234567,
                local,
                "local-secret-for-test",
                "instance-123",
                "COLL",
            )

        self.assertTrue(result["local_verified"])
        self.assertEqual(result["local_version"], 124)

    def test_patch_local_note_treats_http_500_with_readback_failure_as_outcome_unknown(self) -> None:
        new_html = "<p>中文</p>"
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 123,
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with patch.object(
            module,
            "request",
            return_value=(500, {}, b"server error"),
        ), patch.object(
            module,
            "get_json",
            side_effect=RuntimeError("local readback GET failed"),
        ):
            with self.assertRaisesRegex(
                module.MutationOutcomeUnknown,
                "mutation outcome unknown",
            ):
                module.patch_local_note(
                    1234567,
                    local,
                    "local-secret-for-test",
                    "instance-123",
                    "COLL",
                )

    def test_patch_local_note_treats_transport_error_with_successful_readback_as_success(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 123,
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        readback = (
            {},
            {
                "version": 124,
                "data": {
                    "itemType": "note",
                    "parentItem": "PARENT12",
                    "note": new_html,
                    "version": 124,
                    "deleted": False,
                },
            },
        )
        parent = (
            {},
            {
                "data": {
                    "deleted": False,
                    "collections": ["COLL"],
                },
            },
        )
        with patch.object(
            module,
            "request",
            side_effect=module.urllib.error.URLError("temporary network failure"),
        ), patch.object(
            module,
            "get_json",
            side_effect=[readback, parent],
        ):
            result = module.patch_local_note(
                1234567,
                local,
                "local-secret-for-test",
                "instance-123",
                "COLL",
            )

        self.assertTrue(result["local_verified"])
        self.assertEqual(result["local_version"], 124)

    def test_patch_local_note_treats_transport_error_with_readback_as_unverified_when_post_contract_fails(
        self,
    ) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 123,
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        readback = (
            {},
            {
                "version": 124,
                "data": {
                    "itemType": "note",
                    "parentItem": "PARENT12",
                    "note": new_html,
                    "version": 124,
                    "deleted": False,
                },
            },
        )
        parent = (
            {},
            {
                "data": {
                    "deleted": False,
                    "collections": ["COLL"],
                },
            },
        )

        def _fail_contract(_: dict[str, object]) -> None:
            raise RuntimeError("contract changed after patch")

        with patch.object(
            module,
            "request",
            side_effect=module.urllib.error.URLError("temporary network failure"),
        ), patch.object(
            module,
            "get_json",
            side_effect=[readback, parent],
        ):
            with self.assertRaisesRegex(
                module.MutationAcceptedButUnverified,
                "post-patch contract changed",
            ):
                module.patch_local_note(
                    1234567,
                    local,
                    "local-secret-for-test",
                    "instance-123",
                    "COLL",
                    target_contract={"group_id": 1234567},
                    post_patch_contract_check=_fail_contract,
                )


if __name__ == "__main__":
    unittest.main()
