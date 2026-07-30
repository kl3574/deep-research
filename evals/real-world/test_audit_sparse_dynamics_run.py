#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import hashlib
import http.server
import importlib.util
import json
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("audit_sparse_dynamics_run.py")
SPEC = importlib.util.spec_from_file_location("audit_sparse_dynamics_run", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules["audit_sparse_dynamics_run"] = AUDIT
SPEC.loader.exec_module(AUDIT)


def make_pdf(path: Path, marker: str = "A") -> None:
    payload = (
        b"%PDF-1.7\n"
        b"1 0 obj << /Type /Catalog >>\n"
        b"endobj\n"
        + marker.encode("utf-8")
        + b"\n%%EOF\n"
    )
    path.write_bytes(payload)


def make_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def make_md5(path: Path) -> str:
    digest = hashlib.md5()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def make_note_html(path: Path, source_id: str, source_sha: str) -> None:
    content = f"""
<div data-schema-version=\"9\">
  <h1>研究文献 {source_id}</h1>
  <h2>资料与阅读状态</h2>
  <p>标题：{source_id}</p>
  <p>作者：测试作者</p>
  <p>年份：2026</p>
  <p>期刊或载体：测试期刊</p>
  <p>DOI或稳定标识：10.1234/{source_id}</p>
  <p>版本与出版状态：v1</p>
  <p>访问层级：full_text</p>
  <p>全文SHA-256：{source_sha}</p>
  <p>阅读深度：evidence</p>
  <p>核验时间：2026-07-30</p>
  <h2>为什么重要</h2>
  <p>用于构建深度调研流程的一致性样例。</p>
  <h2>一句话结论</h2>
  <p>该文献支持当前识别与校准研究方向。</p>
  <h2>心智模型</h2>
  <pre class=\"math\">$$x_t = f(x_{{t-1}}) + u_t$$</pre>
  <p>符号：x_t, f, u_t。</p>
  <p>作用：描述离散动态演化。</p>
  <p>假设：系统可辨识。</p>
  <p>定位：p.1</p>
  <h2>关键主张与证据</h2>
  <table>
    <tr><th>Claim ID</th><th>性质</th><th>主张</th><th>证据与精确定位</th><th>条件</th><th>置信度与理由</th></tr>
    <tr><td>C1</td><td>source-stated</td><td>本文给出可复现的关键步骤。</td><td>p.2</td><td>已知边界条件</td><td>high: 条款完整且可核验。</td></tr>
  </table>
  <h2>方法或推导</h2>
  <p>采用分段建模与参数约束。</p>
  <h2>结果</h2>
  <p>结果符合实验设计。</p>
  <h2>假设、失败边界与竞争解释</h2>
  <p>噪声过大时会影响稳定性。</p>
  <h2>知识图谱关系</h2>
  <p>与稀疏动力学识别存在映射关系。</p>
  <h2>复用</h2>
  <p>可用于多源动力学的先验设计。</p>
  <h2>溯源</h2>
  <p>证据账本：本地文件与手工核验记录。</p>
  <p>本地PDF：{path}</p>
  <p>SHA-256：{source_sha}</p>
  <p>Agent推断：基于结构证据链。</p>
</div>
"""
    path.write_text(content.strip() + "\n", encoding="utf-8")


def make_bundle(
    path: Path,
    source_id: str,
    pdf_path: Path,
    note_path: Path,
    *,
    group_id: int = 123456,
    library_name: str = "PRIVATE_ZOTERO_TARGET",
    library_id: int = 2,
    collection_key: str = "TESTCOL1",
    collection_path: str = "PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET",
    doi: str = "10.1234/undefined",
) -> None:
    payload = {
        "source_id": source_id,
        "target": {
            "library_name": library_name,
            "library_id": library_id,
            "group_id": group_id,
            "collection_key": collection_key,
            "collection_path": collection_path,
        },
        "item": {
            "title": source_id,
            "itemType": "journalArticle",
            "source": {"doi": doi},
            "DOI": doi,
        },
        "pdf": {
            "local_path": str(pdf_path),
            "size_bytes": pdf_path.stat().st_size,
            "sha256": make_sha256(pdf_path),
            "pages": 10,
            "encrypted": False,
            "pdftotext": {"readable": True, "text_bytes": 120},
        },
        "note": {
            "local_path": str(note_path),
            "sha256": make_sha256(note_path),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _api_payload(
    group_id: int,
    parent_key: str,
    note_key: str,
    attachment_key: str,
    collection_key: str,
    parent_title: str,
    parent_doi: str | None,
    parent_year: str | None,
    note_html: str,
    pdf_path: str,
    pdf_sha: str,
    pdf_md5: str,
) -> dict[str, dict[str, dict[str, object]]]:
    parent_data: dict[str, object] = {
        "key": parent_key,
        "itemType": "journalArticle",
        "collections": [collection_key],
        "parentItem": None,
        "title": parent_title,
    }
    if parent_doi is not None:
        parent_data["DOI"] = parent_doi
    if parent_year is not None:
        parent_data["date"] = parent_year

    return {
        parent_key: {
            "library": {"id": group_id},
            "data": parent_data,
        },
        note_key: {
            "library": {"id": group_id},
            "data": {
                "key": note_key,
                "itemType": "note",
                "parentItem": parent_key,
                "note": note_html,
            },
        },
        attachment_key: {
            "library": {"id": group_id},
            "data": {
                "key": attachment_key,
                "itemType": "attachment",
                "parentItem": parent_key,
                "path": pdf_path,
                "storedPath": pdf_path,
                "sha256": pdf_sha,
                "md5": pdf_md5,
            },
        },
    }


def _set_readback_status(manifest_path: Path, source_id: str, status: str) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in payload.get("entries", []):
        if str(entry.get("id") or entry.get("source_id") or "").strip() == source_id:
            readback = entry.setdefault("readback", {})
            if isinstance(readback, dict):
                readback["status"] = status
            break
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@contextlib.contextmanager
def _serve_api(
    route_map: dict[tuple[str, str], dict[str, object]],
    file_view_url_map: dict[tuple[str, str], str],
):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            parts = parsed.path.split("/")
            if (
                len(parts) == 6
                and parts[1] == "api"
                and parts[2] == "groups"
                and parts[4] == "items"
            ):
                group_id = parts[3]
                key = urllib.parse.unquote(parts[5])
                payload = route_map.get((group_id, key))
                if payload is None:
                    self.send_error(404, "not found")
                    return
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if (
                len(parts) == 9
                and parts[1] == "api"
                and parts[2] == "groups"
                and parts[4] == "items"
                and parts[6] == "file"
                and parts[7] == "view"
                and parts[8] == "url"
            ):
                group_id = parts[3]
                key = urllib.parse.unquote(parts[5])
                file_url = file_view_url_map.get((group_id, key))
                if file_url is None:
                    self.send_error(404, "not found")
                    return
                body = file_url.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404, "route not found")

        def log_message(
            self, format: str, *args: object
        ) -> None:  # pragma: no cover - test log suppressor
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


class AuditSparseDynamicsRunTests(unittest.TestCase):
    def _strip_pdf_metadata_fields(
        self,
        root: Path,
        source_ids: list[str],
        *,
        drop_fields: tuple[str, ...] = ("pages", "encrypted", "pdftotext"),
    ) -> None:
        target_ids = set(source_ids)

        ingestion_path = root / "ingestion_manifest.json"
        ingestion_payload = json.loads(ingestion_path.read_text(encoding="utf-8"))
        for entry in ingestion_payload.get("entries", []):
            entry_id = str(entry.get("id") or entry.get("source_id") or "").strip()
            if entry_id not in target_ids:
                continue
            pdf = entry.get("pdf")
            if isinstance(pdf, dict):
                for field in drop_fields:
                    pdf.pop(field, None)
        ingestion_path.write_text(
            json.dumps(ingestion_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        for path in sorted((root / "bundles").glob("*.json")):
            bundle_payload = json.loads(path.read_text(encoding="utf-8"))
            source_id = str(
                bundle_payload.get("source_id") or bundle_payload.get("id") or ""
            ).strip()
            if source_id not in target_ids:
                continue
            pdf = bundle_payload.get("pdf")
            if isinstance(pdf, dict):
                for field in drop_fields:
                    pdf.pop(field, None)
            path.write_text(
                json.dumps(bundle_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _create_run_root(
        self, root: Path, *, count: int = 3, group_id: int = 123456
    ) -> tuple[list[str], list[tuple[str, str, str, str]]]:
        run_root = root
        pdf_dir = run_root / "pdfs"
        bundle_dir = run_root / "bundles"
        notes_dir = run_root / "notes"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        notes_dir.mkdir(parents=True, exist_ok=True)

        ids: list[str] = []
        files: list[dict[str, object]] = []
        entries: list[dict[str, object]] = []
        readback_keys: list[tuple[str, str, str, str]] = []
        default_target = {
            "library_name": "PRIVATE_ZOTERO_TARGET",
            "library_id": 2,
            "group_id": group_id,
            "collection_key": "TESTCOL1",
            "collection_path": "PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET",
        }

        for idx in range(1, count + 1):
            source_id = f"deep-research-test-{idx:02d}"
            ids.append(source_id)
            pdf_path = pdf_dir / f"{source_id}.pdf"
            make_pdf(pdf_path, marker=chr(64 + idx))
            note_path = notes_dir / f"{source_id}.html"
            make_note_html(note_path, source_id, make_sha256(pdf_path))
            sha = make_sha256(note_path)
            entry_doi = f"10.1234/{source_id}"

            files.append(
                {
                    "id": source_id,
                    "local_path": str(pdf_path),
                    "size_bytes": pdf_path.stat().st_size,
                    "sha256": make_sha256(pdf_path),
                    "pages": 10 + idx,
                    "encrypted": False,
                    "pdftotext": {"readable": True, "text_bytes": 120},
                    "title": source_id,
                }
            )

            bundle_path = bundle_dir / f"{source_id}.json"
            make_bundle(
                bundle_path,
                source_id,
                pdf_path,
                note_path,
                group_id=group_id,
                doi=entry_doi,
            )

            parent_key = f"PARENT-{idx:02d}"
            note_key = f"NOTE-{idx:02d}"
            attachment_key = f"ATTACH-{idx:02d}"
            readback_keys.append((source_id, parent_key, note_key, attachment_key))

            entries.append(
                {
                    "id": source_id,
                    "title": source_id,
                    "target": dict(default_target),
                    "doi": entry_doi,
                    "source": {"doi": entry_doi, "title": source_id},
                    "pdf": {
                        "local_path": str(pdf_path),
                        "size_bytes": pdf_path.stat().st_size,
                        "sha256": make_sha256(pdf_path),
                        "pages": 10 + idx,
                        "encrypted": False,
                        "pdftotext": {"readable": True, "text_bytes": 120},
                    },
                    "note": {
                        "local_path": str(note_path),
                        "sha256": sha,
                    },
                    "readback": {
                        "status": "verified",
                        "zotero_item_key": parent_key,
                        "zotero_note_key": note_key,
                        "zotero_attachment_key": attachment_key,
                        "stored_path": str(pdf_path),
                        "stored_sha256": make_sha256(pdf_path),
                    },
                }
            )

        manifest_payload = {"files": files}
        (run_root / "manifest.json").write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        (run_root / "ingestion_manifest.json").write_text(
            json.dumps(
                {
                    "manifest_version": "2",
                    "entries": entries,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        standalone_pdf = pdf_dir / "deep-research-test-01.pdf"
        standalone_pdf_sha = make_sha256(standalone_pdf)
        extra_note = notes_dir / "extra_sindy.html"
        make_note_html(extra_note, "extra", standalone_pdf_sha)
        standalone_manifest = [
            {
                "id": "extra_sindy",
                "note_path": str(extra_note),
                "note_sha256": make_sha256(extra_note),
                "pdf_path": str(standalone_pdf),
                "pdf_sha256": standalone_pdf_sha,
                "pdf_pages": 11,
                "title": "研究文献 extra",
                "doi": "10.1234/extra",
                "note_full_text_sha256": standalone_pdf_sha,
            }
        ]
        (run_root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME).write_text(
            json.dumps(standalone_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return ids, readback_keys

    @staticmethod
    def _synthetic_pdf_tool_output(path: Path) -> tuple[int | None, bool | None, str | None]:
        name = path.name
        for idx in range(1, 9):
            marker = f"deep-research-test-{idx:02d}"
            if marker in name:
                return (10 + idx, False, None)
        return (None, None, "pdf tool output unavailable")

    @contextlib.contextmanager
    def _mock_pdf_tool_output(self):
        original = AUDIT._validate_pdf_tool_output
        try:
            AUDIT._validate_pdf_tool_output = self._synthetic_pdf_tool_output
            yield
        finally:
            AUDIT._validate_pdf_tool_output = original

    def _build_api_routes(
        self, root: Path, ids: list[str], readback_keys: list[tuple[str, str, str, str]]
    ) -> tuple[dict[tuple[str, str], dict[str, object]], dict[tuple[str, str], str]]:
        payloads: dict[tuple[str, str], dict[str, object]] = {}
        file_urls: dict[tuple[str, str], str] = {}
        collection_key = "TESTCOL1"
        group_id = 123456
        notes_dir = root / "notes"
        pdf_dir = root / "pdfs"

        ingestion_path = root / "ingestion_manifest.json"
        try:
            ingestion_payload = json.loads(ingestion_path.read_text(encoding="utf-8"))
            ingest_entries = ingestion_payload.get("entries", []) if isinstance(ingestion_payload, dict) else []
        except (OSError, json.JSONDecodeError):
            ingest_entries = []

        def _resolve_entry_metadata(source_id: str) -> tuple[str, str | None, str | None]:
            def _extract_year(value: object) -> str | None:
                if not isinstance(value, str):
                    return None
                text = value.strip()
                if not text:
                    return None
                for token in text.replace("/", " ").replace("-", " ").replace("_", " ").split():
                    if len(token) == 4 and token.isdigit() and token[0:2] in {"19", "20"}:
                        return token
                return None

            def _extract_year_from_record(record: dict[str, object]) -> str | None:
                for field in (
                    "year",
                    "publication_year",
                    "publicationYear",
                    "year_published",
                    "yearPublished",
                    "date",
                    "datePublished",
                    "date_published",
                    "publicationDate",
                    "issued",
                ):
                    extracted = _extract_year(record.get(field))
                    if extracted is not None:
                        return extracted
                source = record.get("source")
                if isinstance(source, dict):
                    return _extract_year_from_record(source)
                return None

            def _text(value: object) -> str | None:
                if not isinstance(value, str):
                    return None
                cleaned = value.strip()
                return cleaned or None

            def _maybe_doi(value: object) -> str | None:
                text = _text(value)
                if text is None:
                    return None
                return text.lower() if text.lower().startswith("10.") else None

            parent_title = source_id
            parent_doi = f"10.1234/{source_id}"
            parent_year = None

            for entry in ingest_entries if isinstance(ingest_entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                entry_id = str(entry.get("id") or entry.get("source_id") or "").strip()
                if entry_id != source_id:
                    continue
                entry_title = _text(entry.get("title"))
                if entry_title:
                    parent_title = entry_title
                if not parent_title and isinstance(entry.get("source"), dict):
                    source_title = _text(entry["source"].get("title"))
                    if source_title:
                        parent_title = source_title
                entry_doi = _maybe_doi(entry.get("doi"))
                if entry_doi is None and isinstance(entry.get("source"), dict):
                    entry_doi = _maybe_doi(entry["source"].get("doi"))
                if entry_doi is not None:
                    parent_doi = entry_doi
                parent_year = _extract_year_from_record(entry)
                break

            bundle_path = root / "bundles" / f"{source_id}.json"
            if bundle_path.exists():
                try:
                    bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    bundle_payload = None
                if isinstance(bundle_payload, dict):
                    bundle_item = bundle_payload.get("item")
                    if isinstance(bundle_item, dict):
                        bundle_title = _text(bundle_item.get("title"))
                        if bundle_title:
                            parent_title = bundle_title
                        if "source" in bundle_item and isinstance(
                            bundle_item.get("source"), dict
                        ):
                            bundle_doi = _maybe_doi(bundle_item["source"].get("doi"))
                            if bundle_doi is not None:
                                parent_doi = bundle_doi
                    if isinstance(bundle_item, dict) and not parent_year:
                        parent_year = _extract_year_from_record(bundle_item)
            return parent_title, parent_doi, parent_year

        for idx, entry in enumerate(readback_keys, start=1):
            source_id = ids[idx - 1]
            note_path = notes_dir / f"{source_id}.html"
            pdf_path = pdf_dir / f"{source_id}.pdf"
            assert note_path.exists()
            assert pdf_path.exists()
            parent_title, parent_doi, parent_year = _resolve_entry_metadata(source_id)

            _, parent_key, note_key, attachment_key = entry
            route_payloads = _api_payload(
                group_id,
                parent_key,
                note_key,
                attachment_key,
                collection_key,
                parent_title,
                parent_doi,
                parent_year,
                note_path.read_text(encoding="utf-8"),
                str(pdf_path),
                make_sha256(pdf_path),
                make_md5(pdf_path),
            )
            for key, payload in route_payloads.items():
                payloads[(str(group_id), key)] = payload
            file_urls[(str(group_id), attachment_key)] = f"file://{pdf_path}"
        return payloads, file_urls

    def _run_audit(
        self,
        root: Path,
        *,
        expected_pdfs: int,
        expected_bundles: int,
        expected_notes: int,
        ingest_path: Path | None = None,
        zotero_base_url: str | None = None,
        skip_pdf_tools: bool = True,
    ) -> tuple[int, dict]:
        args = argparse.Namespace(
            run_root=root,
            corpus_manifest=root / "manifest.json",
            ingestion_manifest=ingest_path or (root / "ingestion_manifest.json"),
            bundle_dir=root / "bundles",
            notes_dir=root / "notes",
            sindy_note=root / "notes" / "extra_sindy.html",
            zotero_base_url=zotero_base_url,
            expected_pdfs=expected_pdfs,
            expected_bundles=expected_bundles,
            expected_notes=expected_notes,
            skip_pdf_tools=skip_pdf_tools,
            output=None,
            generated_at="2026-07-30T00:00:00+00:00",
        )
        return AUDIT.run_audit(args)

    def _run_main(self, argv: list[str]) -> tuple[int, dict | None, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = AUDIT.main(argv)
        raw = output.getvalue().strip()
        report: dict | None = None
        if raw:
            try:
                report = json.loads(raw)
            except json.JSONDecodeError:
                report = None
        return code, report, raw

    def _set_bundle_source_id(self, root: Path, source_id: str, new_bundle_source_id: str) -> None:
        bundle_path = root / "bundles" / f"{source_id}.json"
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
        payload["source_id"] = new_bundle_source_id
        payload["id"] = new_bundle_source_id
        bundle_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _set_entry_target(self, root: Path, source_id: str, *, target: dict[str, object]) -> None:
        payload = json.loads((root / "ingestion_manifest.json").read_text(encoding="utf-8"))
        entries = payload.get("entries", [])
        for entry in entries:
            if (
                isinstance(entry, dict)
                and str(entry.get("id") or entry.get("source_id") or "").strip() == source_id
            ):
                entry["target"] = target
                break
        else:
            raise AssertionError(f"entry not found for {source_id}")
        (root / "ingestion_manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _set_entry_identity(self, root: Path, source_id: str, *, title: str | None, doi: str | None) -> None:
        payload = json.loads((root / "ingestion_manifest.json").read_text(encoding="utf-8"))
        entries = payload.get("entries", [])
        for entry in entries:
            if (
                isinstance(entry, dict)
                and str(entry.get("id") or entry.get("source_id") or "").strip() == source_id
            ):
                if title is not None:
                    entry["title"] = title
                else:
                    entry.pop("title", None)
                if doi is not None:
                    entry["doi"] = doi
                else:
                    entry.pop("doi", None)
                break
        else:
            raise AssertionError(f"entry not found for {source_id}")
        (root / "ingestion_manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _set_bundle_identity(self, root: Path, source_id: str, *, doi: str | None) -> None:
        bundle_path = root / "bundles" / f"{source_id}.json"
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
        item = payload.get("item")
        if not isinstance(item, dict):
            raise AssertionError("bundle item missing")
        if doi is not None:
            item["source"] = {"doi": doi}
        else:
            item.pop("source", None)
        bundle_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_audit_passes_without_api_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_SUCCESS)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "pass")
            self.assertEqual(report["checks"]["notes"]["status"], "pass")
            self.assertEqual(report["checks"]["corpus_files"]["status"], "pass")
            standalone_manifest = root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME
            self.assertEqual(
                report["inputs"]["standalone_manifest"],
                {
                    "path": str(standalone_manifest),
                    "sha256": make_sha256(standalone_manifest),
                },
            )
            standalone_item = next(
                item
                for item in report["checks"]["notes"]["payload"]["items"]
                if item.get("id") == "extra_sindy"
            )
            self.assertEqual(
                standalone_item["expected_identity"]["doi"],
                "10.1234/extra",
            )
            self.assertEqual(
                standalone_item["expected_identity"]["note_sha256"],
                make_sha256(root / "notes" / "extra_sindy.html"),
            )

    def test_audit_fails_without_standalone_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            manifest_path = root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME
            manifest_path.unlink()
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["notes"]["status"], "fail")
            self.assertTrue(
                any(
                    "standalone note manifest missing" in issue
                    for issue in report["checks"]["notes"]["issues"]
                ),
                report["checks"]["notes"]["issues"],
            )

    def test_audit_fails_without_standalone_note_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            manifest_path = root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload[0].pop("note_sha256")
            manifest_path.write_text(
                json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["notes"]["status"], "fail")
            self.assertTrue(
                any(
                    "missing note sha256 declaration" in issue
                    for item in report["checks"]["notes"]["payload"]["items"]
                    if item["index"] == 4
                    for issue in item.get("issues", [])
                ),
                report["checks"]["notes"]["payload"]["items"][3].get("issues", []),
            )

    def test_audit_enforces_standalone_note_title_doi_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            manifest_path = root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_payload[0]["title"] = "wrong title"
            manifest_payload[0]["doi"] = "10.9999/wrong-doi"
            manifest_path.write_text(
                json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["notes"]["status"], "fail")
            item4 = report["checks"]["notes"]["payload"]["items"][3]
            self.assertTrue(
                any(
                    "standalone note title mismatch" in issue
                    for issue in item4.get("issues", [])
                ),
                item4["issues"],
            )
            self.assertTrue(
                any(
                    "standalone note doi mismatch" in issue
                    for issue in item4.get("issues", [])
                ),
                item4["issues"],
            )

    def test_audit_main_blocks_output_to_input_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            output = root / "ingestion_manifest.json"
            output_original = output.read_bytes()
            code, report, _ = self._run_main(
                [
                    "--run-root",
                    str(root),
                    "--sindy-note",
                    str(root / "notes" / "extra_sindy.html"),
                    "--expected-pdfs",
                    "3",
                    "--expected-bundles",
                    "3",
                    "--expected-notes",
                    "4",
                    "--skip-pdf-tools",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, AUDIT.EXIT_ERROR)
            self.assertIsNotNone(report)
            if isinstance(report, dict):
                self.assertEqual(report.get("status"), "error")
                self.assertIn(
                    "refuse to write audit report to input artifact path",
                    str(report.get("error", "")),
                )
            self.assertEqual(output.read_bytes(), output_original)

    def test_audit_main_blocks_output_to_default_bundle_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            output = root / "bundles" / "deep-research-test-01.json"
            output_original = output.read_bytes()
            code, report, _ = self._run_main(
                [
                    "--run-root",
                    str(root),
                    "--sindy-note",
                    str(root / "notes" / "extra_sindy.html"),
                    "--expected-pdfs",
                    "3",
                    "--expected-bundles",
                    "3",
                    "--expected-notes",
                    "4",
                    "--skip-pdf-tools",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, AUDIT.EXIT_ERROR)
            self.assertIsNotNone(report)
            self.assertEqual(output.read_bytes(), output_original)

    def test_audit_main_blocks_output_to_standalone_note_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            unique_pdf = root / "pdfs" / "standalone-unique.pdf"
            make_pdf(unique_pdf, marker="U")
            manifest_payload = json.loads(
                (root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            extra_note_path = root / "notes" / "extra_sindy.html"
            extra_note_pdf_hash = make_sha256(unique_pdf)
            make_note_html(extra_note_path, "extra", extra_note_pdf_hash)
            manifest_payload[0]["pdf_path"] = str(unique_pdf)
            manifest_payload[0]["pdf_sha256"] = extra_note_pdf_hash
            manifest_payload[0]["pdf_pages"] = 11
            manifest_payload[0]["note_sha256"] = make_sha256(extra_note_path)
            manifest_payload[0]["note_full_text_sha256"] = extra_note_pdf_hash
            (root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME).write_text(
                json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output = unique_pdf
            output_original = output.read_bytes()
            code, report, _ = self._run_main(
                [
                    "--run-root",
                    str(root),
                    "--sindy-note",
                    str(root / "notes" / "extra_sindy.html"),
                    "--expected-pdfs",
                    "3",
                    "--expected-bundles",
                    "3",
                    "--expected-notes",
                    "4",
                    "--skip-pdf-tools",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, AUDIT.EXIT_ERROR)
            self.assertIsNotNone(report)
            self.assertEqual(output.read_bytes(), output_original)

    def test_audit_main_blocks_output_to_standalone_note_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            manifest_payload = json.loads(
                (root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            outside_note = root / "outside_standalone_note.html"
            outside_note_pdf_hash = make_sha256(root / "pdfs" / "deep-research-test-01.pdf")
            make_note_html(
                outside_note,
                "outside",
                outside_note_pdf_hash,
            )
            manifest_payload[0]["note_path"] = str(outside_note)
            manifest_payload[0]["note_sha256"] = make_sha256(outside_note)
            manifest_payload[0]["note_full_text_sha256"] = outside_note_pdf_hash
            (root / AUDIT.STANDALONE_NOTE_MANIFEST_FILENAME).write_text(
                json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output = outside_note
            output_original = output.read_bytes()
            code, report, _ = self._run_main(
                [
                    "--run-root",
                    str(root),
                    "--sindy-note",
                    str(root / "notes" / "extra_sindy.html"),
                    "--expected-pdfs",
                    "3",
                    "--expected-bundles",
                    "3",
                    "--expected-notes",
                    "4",
                    "--skip-pdf-tools",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, AUDIT.EXIT_ERROR)
            self.assertIsNotNone(report)
            if isinstance(report, dict):
                self.assertEqual(report.get("status"), "error")
                self.assertIn(
                    "refuse to write audit report to input artifact path",
                    str(report.get("error", "")),
                )
            self.assertEqual(output.read_bytes(), output_original)

    def test_audit_main_allows_safe_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            output = root / "audit-report.json"
            code, report, _ = self._run_main(
                [
                    "--run-root",
                    str(root),
                    "--sindy-note",
                    str(root / "notes" / "extra_sindy.html"),
                    "--expected-pdfs",
                    "3",
                    "--expected-bundles",
                    "3",
                    "--expected-notes",
                    "4",
                    "--skip-pdf-tools",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, AUDIT.EXIT_SUCCESS)
            self.assertIsNotNone(report)
            if isinstance(report, dict):
                self.assertEqual(report.get("status"), "pass")
            self.assertTrue(output.exists())

    def test_audit_accepts_matching_entry_bundle_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, _ = self._create_run_root(root)
            doi = "10.1234/example.2026.01"
            self._set_entry_target(
                root,
                ids[0],
                target={
                    "library_name": "PRIVATE_ZOTERO_TARGET",
                    "library_id": 2,
                    "group_id": 123456,
                    "collection_key": "TESTCOL1",
                    "collection_path": "PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET",
                    "name": "sparse_dynamics",
                },
            )
            self._set_entry_identity(
                root,
                ids[0],
                title=ids[0],
                doi=doi,
            )
            self._set_bundle_identity(root, ids[0], doi=doi)
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_SUCCESS)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "pass")

    def test_audit_rejects_bundle_source_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, _ = self._create_run_root(root)
            self._set_bundle_source_id(root, ids[0], "deep-research-test-01-renamed")
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            first_item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertEqual(first_item["status"], "fail")
            self.assertTrue(
                any("bundle source_id mismatch" in issue for issue in first_item["issues"]),
                first_item["issues"],
            )

    def test_audit_rejects_entry_target_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, _ = self._create_run_root(root)
            self._set_entry_target(
                root,
                ids[0],
                target={
                    "library_name": "PRIVATE_ZOTERO_TARGET",
                    "library_id": 2,
                    "group_id": 999999,
                    "collection_key": "BADKEY",
                    "collection_path": "PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET",
                },
            )
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            first_item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertEqual(first_item["status"], "fail")
            self.assertTrue(
                any("target.group_id mismatch" in issue for issue in first_item["issues"]),
                first_item["issues"],
            )

    def test_audit_rejects_entry_title_and_doi_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, _ = self._create_run_root(root)
            self._set_entry_identity(
                root,
                ids[0],
                title="wrong title",
                doi=None,
            )
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            first_item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertEqual(first_item["status"], "fail")
            self.assertTrue(
                any("bundle and entry title mismatch" in issue for issue in first_item["issues"]),
                first_item["issues"],
            )

            self._set_entry_identity(
                root,
                ids[0],
                title=ids[0],
                doi="10.4321/wrong.doi",
            )
            self._set_bundle_identity(root, ids[0], doi="10.1234/good.doi")
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            first_item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertEqual(first_item["status"], "fail")
            self.assertTrue(
                any("bundle and entry DOI mismatch" in issue for issue in first_item["issues"]),
                first_item["issues"],
            )

    def test_audit_detects_stale_bundle_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            stale_bundle = root / "bundles" / "stale.json"
            stale_bundle.write_text(
                json.dumps(
                    {
                        "source_id": "stale",
                        "id": "stale",
                        "target": {
                            "library_name": "PRIVATE_ZOTERO_TARGET",
                            "library_id": 2,
                            "group_id": 123456,
                            "collection_key": "TESTCOL1",
                            "collection_path": "PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            self.assertTrue(
                any(
                    "orphan bundle files detected" in issue
                    for issue in report["checks"]["bundle_records"].get("issues", [])
                ),
                report["checks"]["bundle_records"].get("issues", []),
            )

    def test_audit_augments_pdf_metadata_from_verified_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, _ = self._create_run_root(root)
            self._strip_pdf_metadata_fields(root, ids)
            with self._mock_pdf_tool_output():
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    skip_pdf_tools=False,
                )
            self.assertEqual(code, AUDIT.EXIT_SUCCESS)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "pass")
            self.assertTrue(
                any(
                    "legacy_pdf_metadata_augmented_from_verified_corpus"
                    in item
                    for item in report["limitations"]
                )
            )
            for item in report["checks"]["bundle_records"]["payload"]["items"]:
                self.assertEqual(item["status"], "pass")
                self.assertFalse(
                    any(
                        "no matching verified corpus entry" in issue
                        for issue in item.get("issues", [])
                    ),
                    item["issues"],
                )

    def test_audit_rejects_pdf_metadata_without_verified_corpus_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, _ = self._create_run_root(root)
            self._strip_pdf_metadata_fields(root, [ids[0]])

            ingestion_path = root / "ingestion_manifest.json"
            ingestion_payload = json.loads(ingestion_path.read_text(encoding="utf-8"))
            assert "entries" in ingestion_payload
            assert len(ingestion_payload["entries"]) >= 2

            entry = ingestion_payload["entries"][0]
            tamper_entry_pdf = ingestion_payload["entries"][1].get("pdf")
            if not isinstance(entry.get("pdf"), dict):
                raise AssertionError("entry pdf missing")
            if not isinstance(tamper_entry_pdf, dict):
                raise AssertionError("tamper entry pdf missing")
            entry_pdf = entry["pdf"]
            entry_pdf["local_path"] = tamper_entry_pdf["local_path"]
            entry_pdf["size_bytes"] = tamper_entry_pdf["size_bytes"]
            ingestion_path.write_text(
                json.dumps(ingestion_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            first_bundle = sorted((root / "bundles").glob("*.json"))[0]
            bundle_payload = json.loads(first_bundle.read_text(encoding="utf-8"))
            bundle_pdf = bundle_payload.get("pdf")
            if not isinstance(bundle_pdf, dict):
                raise AssertionError("bundle pdf missing")
            bundle_pdf["local_path"] = entry_pdf["local_path"]
            bundle_pdf["size_bytes"] = entry_pdf["size_bytes"]
            bundle_pdf["sha256"] = entry_pdf["sha256"]
            first_bundle.write_text(
                json.dumps(bundle_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with self._mock_pdf_tool_output():
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    skip_pdf_tools=False,
                )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            first_item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertTrue(
                any(
                    "no matching verified corpus entry" in issue
                    for issue in first_item.get("issues", [])
                )
                or any("path mismatch" in issue for issue in first_item.get("issues", [])),
                first_item["issues"],
            )

    def test_audit_rejects_pdf_metadata_augmentation_if_corpus_verification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, _ = self._create_run_root(root)
            self._strip_pdf_metadata_fields(root, ids)

            corpus_path = root / "manifest.json"
            corpus_payload = json.loads(corpus_path.read_text(encoding="utf-8"))
            assert "files" in corpus_payload and len(corpus_payload["files"]) >= 1
            corpus_payload["files"][0].pop("pdftotext", None)
            corpus_path.write_text(
                json.dumps(corpus_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with self._mock_pdf_tool_output():
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    skip_pdf_tools=False,
                )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["checks"]["corpus_files"]["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")

    def test_audit_rejects_pdf_and_note_bundle_entry_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, _ = self._create_run_root(root)
            ingestion_path = root / "ingestion_manifest.json"
            payload = json.loads(ingestion_path.read_text(encoding="utf-8"))
            entries = payload.get("entries", [])
            if not isinstance(entries, list) or len(entries) < 2:
                raise AssertionError("insufficient entries for mismatch fixture")

            target = entries[0]
            donor = entries[1]
            target_pdf = target.get("pdf")
            donor_pdf = donor.get("pdf")
            target_note = target.get("note")
            donor_note = donor.get("note")
            if (
                not isinstance(target_pdf, dict)
                or not isinstance(donor_pdf, dict)
                or not isinstance(target_note, dict)
                or not isinstance(donor_note, dict)
            ):
                raise AssertionError("entry payload missing pdf/note block")

            target_pdf["local_path"] = donor_pdf["local_path"]
            target_pdf["sha256"] = donor_pdf["sha256"]
            target_note["local_path"] = donor_note["local_path"]
            target_note["sha256"] = donor_note["sha256"]
            payload["entries"][0] = target
            ingestion_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            first_item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertEqual(first_item["status"], "fail")
            self.assertTrue(
                any(
                    "bundle and entry pdf local_path mismatch" in issue
                    for issue in first_item["issues"]
                ),
                first_item["issues"],
            )
            self.assertTrue(
                any(
                    "bundle and entry note local_path mismatch" in issue
                    for issue in first_item["issues"]
                ),
                first_item["issues"],
            )

    def test_audit_readback_with_local_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, readback_keys = self._create_run_root(root)
            routes, file_view_urls = self._build_api_routes(
                root, ids, readback_keys
            )
            with _serve_api(routes, file_view_urls) as base_url:
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    zotero_base_url=base_url,
                )
            self.assertEqual(code, AUDIT.EXIT_SUCCESS)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "pass")
            self.assertEqual(
                report["checks"]["bundle_records"]["payload"]["items"][0]["readback"][
                    "status"
                ],
                "pass",
            )

    def test_audit_detects_readback_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, readback_keys = self._create_run_root(root)
            routes, file_view_urls = self._build_api_routes(root, ids, readback_keys)
            drift_payload = copy.deepcopy(routes)
            drift_file_view_urls = copy.deepcopy(file_view_urls)
            parent_key = "PARENT-01"
            note_key = "NOTE-01"
            attachment_key = "ATTACH-01"
            group_id = "123456"
            drift_payload[(group_id, parent_key)]["data"]["collections"] = ["wrong-collection"]
            drift_payload[(group_id, note_key)]["data"]["parentItem"] = "PARENT-XX"
            drift_payload[(group_id, attachment_key)]["data"]["md5"] = "0" * 32

            bad_pdf_path = root / "pdfs" / "drifted-attach.pdf"
            make_pdf(bad_pdf_path, marker="Z")
            drift_file_view_urls[(group_id, attachment_key)] = f"file://{bad_pdf_path}"

            with _serve_api(drift_payload, drift_file_view_urls) as base_url:
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    zotero_base_url=base_url,
                )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            item = report["checks"]["bundle_records"]["payload"]["items"][0]
            issues = item["readback"]["issues"]
            self.assertTrue(
                any("note parentItem mismatch" in issue for issue in issues)
                or any(
                    "expected collection key" in issue or "does not contain expected collection key" in issue
                    for issue in issues
                )
            )
            self.assertTrue(
                any("stored_path mismatch" in issue for issue in issues),
                issues,
            )
            self.assertTrue(
                any("attachment md5 mismatch with downloaded file" in issue for issue in issues),
                issues,
            )
            self.assertTrue(
                any("stored sha256 mismatch" in issue for issue in issues),
                issues,
            )

    def test_audit_detects_readback_parent_title_and_doi_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, readback_keys = self._create_run_root(root)
            routes, file_view_urls = self._build_api_routes(root, ids, readback_keys)
            parent_key = "PARENT-01"
            drift_payload = copy.deepcopy(routes)
            drift_payload[(str(123456), parent_key)]["data"]["title"] = "Drifted Title"
            drift_payload[(str(123456), parent_key)]["data"]["DOI"] = "10.9999/drifted-doi"

            with _serve_api(drift_payload, file_view_urls) as base_url:
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    zotero_base_url=base_url,
                )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            item = report["checks"]["bundle_records"]["payload"]["items"][0]
            issues = item["readback"]["issues"]
            self.assertTrue(
                any("parent title mismatch" in issue for issue in issues),
                issues,
            )
            self.assertTrue(
                any("parent DOI mismatch" in issue for issue in issues),
                issues,
            )

    def test_audit_detects_readback_parent_year_drift_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, readback_keys = self._create_run_root(root)
            ingest_path = root / "ingestion_manifest.json"
            ingest_payload = json.loads(ingest_path.read_text(encoding="utf-8"))
            ingest_payload["entries"][0]["source"]["year"] = "2026"
            ingest_path.write_text(
                json.dumps(ingest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            bundle_path = root / "bundles" / f"{ids[0]}.json"
            bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            if isinstance(bundle_payload.get("item"), dict):
                bundle_payload["item"]["date"] = "2026"
            bundle_path.write_text(
                json.dumps(bundle_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            routes, file_view_urls = self._build_api_routes(root, ids, readback_keys)
            parent_key = "PARENT-01"
            drift_payload = copy.deepcopy(routes)
            drift_payload[(str(123456), parent_key)]["data"]["date"] = "2025-01-01"

            with _serve_api(drift_payload, file_view_urls) as base_url:
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    zotero_base_url=base_url,
                )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            item = report["checks"]["bundle_records"]["payload"]["items"][0]
            issues = item["readback"]["issues"]
            self.assertTrue(
                any("parent publication year mismatch" in issue for issue in issues),
                issues,
            )

    def test_audit_verified_readback_without_api_is_historical_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_SUCCESS)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "pass")
            self.assertIn(
                "readback verified without live API; verification is historical only",
                report["limitations"],
            )
            first_item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertEqual(first_item["readback"]["status"], "not_run")
            self.assertEqual(first_item["readback"]["payload"]["manifest_status"], "verified")

    def test_audit_rejects_non_verified_readback_status_without_api(self) -> None:
        for status in (
            "pending_note_update",
            "failed",
            "conflict",
            "unknown",
            "weird-status",
        ):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    self._create_run_root(root)
                    _set_readback_status(
                        root / "ingestion_manifest.json",
                        "deep-research-test-01",
                        status,
                    )
                    code, report = self._run_audit(
                        root,
                        expected_pdfs=3,
                        expected_bundles=3,
                        expected_notes=4,
                    )
                    self.assertEqual(code, AUDIT.EXIT_FAIL)
                    self.assertEqual(report["status"], "fail")
                    self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
                    item = report["checks"]["bundle_records"]["payload"]["items"][0]
                    self.assertEqual(item["status"], "fail")
                    self.assertEqual(item["readback"]["status"], "fail")
                    if status in {"weird-status"}:
                        self.assertTrue(
                            any("invalid" in issue for issue in item["issues"]),
                            item["issues"],
                        )
                    else:
                        self.assertTrue(
                            any("must be verified" in issue for issue in item["issues"]),
                            item["issues"],
                        )

    def test_audit_rejects_missing_readback_status_without_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            payload_path = root / "ingestion_manifest.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            first_entry = payload["entries"][0]
            readback = first_entry.get("readback")
            if isinstance(readback, dict):
                readback.pop("status", None)
            payload_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertEqual(item["status"], "fail")
            self.assertEqual(item["readback"]["status"], "fail")
            self.assertTrue(
                any("readback.status" in issue for issue in item["issues"]),
                item["issues"],
            )

    def test_audit_rejects_non_verified_readback_status_with_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, readback_keys = self._create_run_root(root)
            _set_readback_status(
                root / "ingestion_manifest.json",
                "deep-research-test-01",
                "pending_note_update",
            )
            routes, file_view_urls = self._build_api_routes(root, ids, readback_keys)
            with _serve_api(routes, file_view_urls) as base_url:
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    zotero_base_url=base_url,
                )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            item = report["checks"]["bundle_records"]["payload"]["items"][0]
            self.assertEqual(item["status"], "fail")
            self.assertEqual(item["readback"]["status"], "fail")
            self.assertTrue(
                any("must be verified" in issue for issue in item["issues"]),
                item["issues"],
            )

    def test_audit_fails_when_required_pdf_field_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            manifest_path = root / "manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            del payload["files"][0]["pdftotext"]
            manifest_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(
                any(
                    "missing required pdf field: pdftotext" in issue
                    for item in report["checks"]["corpus_files"]["payload"]["items"]
                    for issue in item.get("issues", [])
                )
            )

    def test_audit_fails_when_pdf_tools_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            original = AUDIT._validate_pdf_tool_output
            try:
                AUDIT._validate_pdf_tool_output = lambda path: (None, None, "pdfinfo unavailable")
                code, report = self._run_audit(
                    root,
                    expected_pdfs=3,
                    expected_bundles=3,
                    expected_notes=4,
                    skip_pdf_tools=False,
                )
            finally:
                AUDIT._validate_pdf_tool_output = original
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(
                any(
                    "pdf tool check failed: pdfinfo unavailable" in issue
                    for item in report["checks"]["corpus_files"]["payload"]["items"]
                    for issue in item.get("issues", [])
                )
            )

    def test_audit_fails_when_counts_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._create_run_root(root)
            code, report = self._run_audit(
                root,
                expected_pdfs=4,
                expected_bundles=4,
                expected_notes=4,
            )
            self.assertEqual(code, AUDIT.EXIT_FAIL)
            self.assertEqual(report["checks"]["corpus_files"]["status"], "fail")
            self.assertEqual(report["checks"]["bundle_records"]["status"], "fail")
            self.assertEqual(report["status"], "fail")

    def test_legacy_items_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids, readback_keys = self._create_run_root(root)
            legacy_payload = {"manifest_version": "1", "items": []}
            for idx, source_id in enumerate(ids, start=1):
                parent_key = readback_keys[idx - 1][1]
                note_key = readback_keys[idx - 1][2]
                attachment_key = readback_keys[idx - 1][3]
                entry = {
                    "source_id": source_id,
                    "title": source_id,
                    "target": {
                        "library_name": "PRIVATE_ZOTERO_TARGET",
                        "library_id": 2,
                        "group_id": 123456,
                        "collection_key": "TESTCOL1",
                        "collection_path": "PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET/PRIVATE_ZOTERO_TARGET",
                    },
                    "doi": f"10.1234/{source_id}",
                    "source": {"doi": f"10.1234/{source_id}", "title": source_id},
                    "pdf": {
                        "local_path": str(root / "pdfs" / f"{source_id}.pdf"),
                        "size_bytes": (root / "pdfs" / f"{source_id}.pdf").stat().st_size,
                        "sha256": make_sha256(root / "pdfs" / f"{source_id}.pdf"),
                        "pages": 10 + idx,
                        "encrypted": False,
                        "pdftotext": {"readable": True, "text_bytes": 120},
                    },
                    "note": {
                        "local_path": str(root / "notes" / f"{source_id}.html"),
                        "sha256": make_sha256(root / "notes" / f"{source_id}.html"),
                    },
                    "readback": {
                        "status": "verified",
                        "zotero_item_key": parent_key,
                        "zotero_note_key": note_key,
                        "zotero_attachment_key": attachment_key,
                        "stored_path": str(root / "pdfs" / f"{source_id}.pdf"),
                        "stored_sha256": make_sha256(root / "pdfs" / f"{source_id}.pdf"),
                    },
                }
                legacy_payload["items"].append(entry)
            legacy_path = root / "ingestion_manifest.legacy.json"
            legacy_path.write_text(
                json.dumps(legacy_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            code, report = self._run_audit(
                root,
                expected_pdfs=3,
                expected_bundles=3,
                expected_notes=4,
                ingest_path=legacy_path,
            )
            self.assertEqual(code, AUDIT.EXIT_SUCCESS)
            self.assertEqual(report["checks"]["bundle_records"]["status"], "pass")
            self.assertTrue(
                any(
                    "legacy ingestion key 'items' used for compatibility"
                    in item
                    for item in report["limitations"]
                )
            )


if __name__ == "__main__":
    unittest.main()
