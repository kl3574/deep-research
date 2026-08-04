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
        if path.endswith("/collections/7V4BEGN4"):
            return {
                "key": "7V4BEGN4",
                "version": 7,
                "data": {
                    "key": "7V4BEGN4",
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
        if path.endswith("/collections/7V4BEGN4/items/top"):
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
                        "path": "/home/private/secret-si.pdf",
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
            self.base_url, 6588343, "7V4BEGN4"
        )
        self.assertEqual("ZoteroCorpusSnapshot/v1", value["schema"])
        self.assertEqual(
            ["PARENT01", "7V4BEGN4"],
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

    def test_private_writer_and_base_url_guards(self) -> None:
        value = snapshotter.build_snapshot(
            self.base_url, 6588343, "7V4BEGN4"
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
        with self.assertRaises(ValueError):
            snapshotter.validate_base_url("https://example.com")


if __name__ == "__main__":
    unittest.main()
