#!/usr/bin/env python3
"""Focused no-op policy tests for reviewed Zotero mutation batches."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import zotero_declarative_bridge as bridge
from test_zotero_declarative_bridge import reviewed_batch_fixture


OLD_CLEAN_NOTE = (
    '<div data-schema-version="9"><h1>既有研究结论</h1>'
    "<p>适用场景：既有笔记基线。局限：仅用于离线测试。</p></div>"
)
PRESERVED_SHORT_TITLE = "高维代理模型分析：应先筛选再校准总效应"
HERE = Path(__file__).resolve().parent


def reseal(batch: dict) -> None:
    for entry in batch["entries"]:
        entry["entry_sha256"] = bridge.sha256_value(
            {key: value for key, value in entry.items() if key != "entry_sha256"}
        )
    batch["manifest_sha256"] = bridge.sha256_value(
        {key: value for key, value in batch.items() if key != "manifest_sha256"}
    )


def preserve_short_title(batch: dict) -> None:
    operation = batch["entries"][0]["operations"][0]
    operation["expected_old_value"] = PRESERVED_SHORT_TITLE
    operation["new_short_title"] = PRESERVED_SHORT_TITLE
    operation["new_short_title_sha256"] = "sha256:" + hashlib.sha256(
        PRESERVED_SHORT_TITLE.encode("utf-8")
    ).hexdigest()
    reseal(batch)


def compile_fixture(
    batch: dict,
    *,
    allow_unchanged_short_titles: bool,
) -> dict:
    parent = batch["entries"][0]["parent"]
    short_operation = batch["entries"][0]["operations"][0]
    note_operation = batch["entries"][0]["operations"][1]
    record = {
        "version": parent["version"],
        "data": {
            "key": parent["key"],
            "version": parent["version"],
            "itemType": "journalArticle",
            "title": parent["title"],
            "shortTitle": short_operation["expected_old_value"],
            "DOI": parent["doi"],
            "collections": ["COLL0001"],
        },
    }
    notes = [
        {
            "key": note_operation["note_key"],
            "version": note_operation["expected_note_version"],
            "html": OLD_CLEAN_NOTE,
        }
    ]
    keyed_path = [
        {"key": "ROOT0001", "name": "Research"},
        {"key": "COLL0001", "name": "Methods"},
    ]
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "reviewed.json"
        source.write_text(json.dumps(batch), encoding="utf-8")
        with mock.patch.object(
            bridge,
            "collection_contract",
            return_value=(keyed_path, {"version": 9, "data": {"version": 9}}),
        ), mock.patch.object(
            bridge, "live_parent", return_value=record
        ), mock.patch.object(
            bridge, "live_child_notes", return_value=notes
        ):
            return bridge.compile_reviewed_batch(
                source,
                transaction_id="reviewed-fixture",
                local_collection_id=40,
                source_hash_contract=bridge.REVIEWED_SOURCE_HASH_CONTRACT,
                short_title_policy=bridge.DECISION_SHORT_TITLE_POLICY,
                short_title_language="zh-CN",
                base_url=bridge.BASE_URL,
                allow_unchanged_short_titles=allow_unchanged_short_titles,
            )


class ReviewedBatchUnchangedShortTitleTests(unittest.TestCase):
    def test_allows_preservation_beside_changing_note_and_keeps_seals(self) -> None:
        batch = reviewed_batch_fixture(OLD_CLEAN_NOTE)
        preserve_short_title(batch)
        compiled = compile_fixture(batch, allow_unchanged_short_titles=True)
        operations = compiled["entries"][0]["operations"]
        self.assertEqual(
            [operation["type"] for operation in operations],
            ["ensure_parent_short_title", "ensure_child_note"],
        )
        self.assertEqual(
            operations[0]["expected_old_value"], operations[0]["new_short_title"]
        )
        self.assertNotEqual(
            operations[1]["expected_old_sha256"], operations[1]["new_sha256"]
        )
        self.assertEqual(
            compiled["manifest_sha256"],
            bridge.sha256_value(
                {
                    key: value
                    for key, value in compiled.items()
                    if key != "manifest_sha256"
                }
            ),
        )
        bridge.validate_manifest(compiled)

    def test_default_rejects_unchanged_short_title(self) -> None:
        batch = reviewed_batch_fixture(OLD_CLEAN_NOTE)
        preserve_short_title(batch)
        with self.assertRaisesRegex(bridge.BridgeError, "shortTitle is unchanged"):
            compile_fixture(batch, allow_unchanged_short_titles=False)

    def test_rejects_entry_when_every_operation_is_noop(self) -> None:
        batch = reviewed_batch_fixture(OLD_CLEAN_NOTE)
        preserve_short_title(batch)
        note_operation = batch["entries"][0]["operations"][1]
        note_operation["new_html"] = OLD_CLEAN_NOTE
        note_operation["new_sha256"] = "sha256:" + hashlib.sha256(
            OLD_CLEAN_NOTE.encode("utf-8")
        ).hexdigest()
        reseal(batch)
        with self.assertRaisesRegex(bridge.BridgeError, "all no-op"):
            compile_fixture(batch, allow_unchanged_short_titles=True)

    def test_cli_exposes_explicit_fail_closed_option(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(HERE / "zotero_declarative_bridge.py"),
                "compile-reviewed-batch",
                "--help",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--allow-unchanged-short-titles", result.stdout)


if __name__ == "__main__":
    unittest.main()
