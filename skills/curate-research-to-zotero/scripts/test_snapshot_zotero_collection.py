#!/usr/bin/env python3

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.parse
from unittest import mock

import snapshot_zotero_collection as snapshotter


class FakeZoteroHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        body = json.dumps(self.payload(path)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def payload(path: str) -> object:
        if not path.startswith("/api/groups/"):
            raise AssertionError(path)
        if path.endswith("/collections/COLL0001"):
            return {
                "key": "COLL0001",
                "version": 7,
                "data": {
                    "key": "COLL0001",
                    "name": "Target",
                    "parentCollection": "PARENT01",
                    "version": 7,
                },
            }
        if path.endswith("/collections/PARENT01"):
            return {
                "key": "PARENT01",
                "version": 3,
                "data": {
                    "key": "PARENT01",
                    "name": "Root",
                    "parentCollection": False,
                    "version": 3,
                },
            }
        if path.endswith("/collections/COLL0001/items/top"):
            return [
                {
                    "key": "ABCDEFGH",
                    "version": 11,
                    "data": {
                        "key": "ABCDEFGH",
                        "itemType": "journalArticle",
                        "title": "Sparse dynamics",
                        "date": "2026",
                        "DOI": "10.1000/example",
                        "abstractNote": "FULL ABSTRACT MUST NOT LEAK",
                        "creators": [
                            {
                                "creatorType": "author",
                                "firstName": "A",
                                "lastName": "Researcher",
                            }
                        ],
                    },
                }
            ]
        if path.endswith("/items/ABCDEFGH/children"):
            return [
                {
                    "key": "NOTENOTE",
                    "version": 2,
                    "data": {
                        "itemType": "note",
                        "note": '<div data-schema-version="9">PRIVATE NOTE BODY</div>',
                    },
                },
                {
                    "key": "PDFPDF01",
                    "version": 5,
                    "data": {
                        "itemType": "attachment",
                        "title": "Supporting Information",
                        "filename": "secret-si.pdf",
                        "contentType": "application/pdf",
                        "linkMode": "imported_file",
                        "path": "/home/tester/secret-si.pdf",
                        "url": "https://secret.example/token",
                    },
                },
            ]
        raise AssertionError(path)


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), FakeZoteroHandler
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.base_url = (
            f"http://127.0.0.1:{self.server.server_port}"
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_snapshot_omits_private_content_and_hashes_state(self) -> None:
        value = snapshotter.build_snapshot(
            self.base_url, 1234567, "COLL0001"
        )
        self.assertEqual("ZoteroCorpusSnapshot/v1", value["schema"])
        self.assertEqual(
            ["PARENT01", "COLL0001"],
            [
                item["key"]
                for item in value["collection"]["collection_path"]
            ],
        )
        self.assertEqual(["ABCDEFGH"], [item["key"] for item in value["parents"]])
        children = value["parents"][0]["children"]
        self.assertEqual(
            ["NOTENOTE", "PDFPDF01"], [item["key"] for item in children]
        )
        self.assertEqual(
            "supporting_information", children[1]["artifact_role"]
        )
        serialized = json.dumps(value, ensure_ascii=False)
        for forbidden in (
            "FULL ABSTRACT",
            "PRIVATE NOTE BODY",
            "/home/private",
            "secret.example",
            "secret-si.pdf",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertTrue(value["identity_sha256"].startswith("sha256:"))
        self.assertTrue(value["state_sha256"].startswith("sha256:"))

    def test_origin_and_api_base_urls_are_equivalent(self) -> None:
        origin = snapshotter.build_snapshot(
            self.base_url, 1234567, "COLL0001"
        )
        api = snapshotter.build_snapshot(
            self.base_url + "/api", 1234567, "COLL0001"
        )
        api_slash = snapshotter.build_snapshot(
            self.base_url + "/api/", 1234567, "COLL0001"
        )
        self.assertEqual(
            self.base_url,
            snapshotter.validate_base_url(self.base_url + "/api"),
        )
        self.assertEqual(origin["collection"], api["collection"])
        self.assertEqual(origin["parents"], api["parents"])
        self.assertEqual(origin["state_sha256"], api["state_sha256"])
        self.assertEqual(api["collection"], api_slash["collection"])
        self.assertEqual(api["parents"], api_slash["parents"])
        self.assertEqual(api["state_sha256"], api_slash["state_sha256"])

    def test_get_all_paginates_101_top_parents_and_children_without_loss(self) -> None:
        top_path = "/api/groups/1234567/collections/COLL0001/items/top"
        child_path = "/api/groups/1234567/items/P0000000/children"
        datasets = {
            top_path: [
                {"key": f"P{index:07d}", "data": {}}
                for index in range(101)
            ],
            child_path: [
                {"key": f"C{index:07d}", "data": {}}
                for index in range(101)
            ],
        }
        starts = {top_path: [], child_path: []}

        def fake_api_get(
            _base_url: str, path: str, params: dict[str, object] | None = None
        ) -> object:
            self.assertIsNotNone(params)
            assert params is not None
            start = int(params["start"])
            limit = int(params["limit"])
            starts[path].append(start)
            return datasets[path][start : start + limit]

        with mock.patch.object(snapshotter, "api_get", side_effect=fake_api_get):
            top = snapshotter.get_all(self.base_url, top_path)
            children = snapshotter.get_all(self.base_url, child_path)

        for path, observed in ((top_path, top), (child_path, children)):
            expected_keys = [item["key"] for item in datasets[path]]
            observed_keys = [item["key"] for item in observed]
            self.assertEqual(expected_keys, observed_keys)
            self.assertEqual(101, len(set(observed_keys)))
            self.assertEqual([0, 100], starts[path])

    def test_get_all_rejects_a_repeated_full_page(self) -> None:
        path = "/api/groups/1234567/collections/COLL0001/items/top"
        full_page = [
            {"key": f"R{index:07d}", "data": {}}
            for index in range(100)
        ]
        starts: list[int] = []

        def fake_api_get(
            _base_url: str, _path: str, params: dict[str, object] | None = None
        ) -> object:
            self.assertIsNotNone(params)
            assert params is not None
            starts.append(int(params["start"]))
            if len(starts) > 2:
                raise AssertionError("pagination loop guard did not stop repeated page")
            return full_page

        with mock.patch.object(snapshotter, "api_get", side_effect=fake_api_get):
            with self.assertRaisesRegex(ValueError, "repeated full page"):
                snapshotter.get_all(self.base_url, path)
        self.assertEqual([0, 100], starts)

    def test_private_writer_and_base_url_guards(self) -> None:
        value = snapshotter.build_snapshot(
            self.base_url, 1234567, "COLL0001"
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "snapshot.json"
            snapshotter.write_private_snapshot(output, value)
            self.assertEqual(0o600, os.stat(output).st_mode & 0o777)
            with self.assertRaises(FileExistsError):
                snapshotter.write_private_snapshot(output, value)
        with self.assertRaises(ValueError):
            snapshotter.validate_base_url(
                "http://user:secret@127.0.0.1:23119"
            )
        for invalid in (
            self.base_url + "/foo",
            self.base_url + "/api/v1",
            self.base_url + "?key=value",
            self.base_url + "/api?key=value",
            self.base_url + "#fragment",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    snapshotter.validate_base_url(invalid)
        with self.assertRaises(ValueError):
            snapshotter.validate_base_url("https://example.com")


if __name__ == "__main__":
    unittest.main()
