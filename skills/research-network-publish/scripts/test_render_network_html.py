#!/usr/bin/env python3
"""Contract and privacy tests for render_network_html.py."""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import render_network_html as renderer


def seal(payload: dict) -> dict:
    result = copy.deepcopy(payload)
    result.pop("content_sha256", None)
    encoded = json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    result["content_sha256"] = hashlib.sha256(encoded).hexdigest()
    return result


def network_fixture() -> dict:
    return seal(
        {
            "schema": "KnowledgeNetwork/v1",
            "network_id": "KN-PRIVATE-001",
            "snapshot_id": "KN-PRIVATE-001-S001",
            "corpus_snapshot": {
                "target_ref": "/home/alice/Zotero/storage/AB12CD34",
                "inventory_digest": "a" * 64,
            },
            "sources": [
                {
                    "source_id": "source:SRC-PRIVATE",
                    "title": "A verified source",
                    "authors": ["Ada Example"],
                    "year": 2024,
                    "doi": "10.1000/example",
                    "item_key": "AB12CD34",
                    "note_body": "DO NOT PUBLISH THIS NOTE BODY",
                    "fulltext": "DO NOT PUBLISH THIS FULL TEXT",
                }
            ],
            "nodes": [
                {
                    "node_id": "source:SRC-PRIVATE",
                    "kind": "source",
                    "label": "A verified source",
                    "status": "active",
                    "confidence": "high",
                },
                {
                    "node_id": "claim:C1",
                    "kind": "claim",
                    "label": "Sampling improves coverage",
                    "status": "active",
                    "confidence": "high",
                },
                {
                    "node_id": "entity:M1",
                    "kind": "method",
                    "label": "Sequential design",
                    "status": "active",
                    "confidence": "high",
                },
            ],
            "relations": [
                {
                    "relation_id": "REL-PRIVATE-001",
                    "from_id": "claim:C1",
                    "to_id": "entity:M1",
                    "predicate": "supports",
                    "status": "supported",
                    "confidence": "high",
                    "provenance": [
                        {
                            "source_id": "source:SRC-PRIVATE",
                            "locator": "/home/alice/papers/source.pdf p. 4; Zotero item: AB12CD34",
                        }
                    ],
                },
                {
                    "relation_id": "REL-PRIVATE-002",
                    "from_id": "claim:C1",
                    "to_id": "entity:M1",
                    "predicate": "contradicts",
                    "status": "conflict",
                    "confidence": "medium",
                    "provenance": [],
                },
            ],
            "gaps": [
                {
                    "gap_id": "GAP-PRIVATE-001",
                    "reason": "conflict",
                    "priority": "decision_critical",
                    "status": "open",
                    "next_action": "Compare the conflicting assumptions.",
                }
            ],
            "completion": {
                "status": "partial",
                "open_gap_ids": ["GAP-PRIVATE-001"],
                "gate_checks": {
                    "corpus_snapshotted": True,
                    "conflicts_terminal": False,
                },
            },
        }
    )


def map_fixture(snapshot_id: str = "KN-PRIVATE-001-S001") -> dict:
    return seal(
        {
            "schema": "ResearchMap/v1",
            "network_snapshot_id": snapshot_id,
            "title": "Sampling and surrogate models",
            "summary": "A field map grounded in reviewed relations.",
            "field_map": [
                {
                    "field_id": "FIELD-SAMPLING",
                    "label": "Sampling",
                    "summary": "Sequential and space-filling designs.",
                    "node_ids": ["entity:M1"],
                }
            ],
            "competency_questions": [
                {
                    "question_id": "CQ-1",
                    "question": "When does sequential design improve coverage?",
                    "status": "partially_answered",
                    "answer": "Only under the reviewed assumptions.",
                    "relation_ids": ["REL-PRIVATE-001"],
                    "gap_ids": ["GAP-PRIVATE-001"],
                }
            ],
            "routes": [
                {
                    "route_id": "ROUTE-1",
                    "label": "Sequential route",
                    "summary": "Adapt sampling to current uncertainty.",
                    "relation_ids": ["REL-PRIVATE-001"],
                }
            ],
            "recommendations": [
                {
                    "recommendation_id": "REC-1",
                    "title": "Resolve the assumption conflict",
                    "rationale": "The conflict is decision-critical.",
                    "priority": "high",
                    "evidence_refs": ["REL-PRIVATE-001", "GAP-PRIVATE-001"],
                }
            ],
        }
    )


class RenderNetworkHtmlTests(unittest.TestCase):
    def test_rejects_wrong_network_schema(self) -> None:
        network = network_fixture()
        network["schema"] = "KnowledgeNetwork/v2"
        network = seal(network)
        with self.assertRaisesRegex(renderer.ContractError, "KnowledgeNetwork/v1"):
            renderer.validate_inputs(network)

    def test_rejects_wrong_content_digest(self) -> None:
        network = network_fixture()
        network["nodes"][0]["label"] = "Changed after sealing"
        with self.assertRaisesRegex(renderer.ContractError, "canonical content"):
            renderer.validate_inputs(network)

    def test_rejects_research_map_bound_to_another_snapshot(self) -> None:
        with self.assertRaisesRegex(renderer.ContractError, "does not match"):
            renderer.validate_inputs(network_fixture(), map_fixture("OTHER-SNAPSHOT"))

    def test_public_projection_removes_privacy_redlines(self) -> None:
        network = network_fixture()
        projection = renderer.build_projection(network, map_fixture(), renderer.PUBLIC_MODE)
        document = renderer.render_document(projection)
        renderer.assert_output_privacy(document, renderer.PUBLIC_MODE)
        self.assertNotIn("/home/alice", document)
        self.assertNotIn("AB12CD34", document)
        self.assertNotIn(network["content_sha256"], document)
        self.assertNotIn("DO NOT PUBLISH THIS NOTE BODY", document)
        self.assertNotIn("DO NOT PUBLISH THIS FULL TEXT", document)
        self.assertNotIn("REL-PRIVATE-001", document)
        self.assertIn("[redacted path]", document)

    def test_private_mode_rejects_credentials(self) -> None:
        network = network_fixture()
        network["sources"][0]["api_token"] = "not-a-real-token-value"
        network = seal(network)
        with self.assertRaisesRegex(renderer.ContractError, "credential-shaped key"):
            renderer.build_projection(network, None, renderer.PRIVATE_MODE)

    def test_render_is_deterministic(self) -> None:
        network = network_fixture()
        research_map = map_fixture()
        first = renderer.render_document(
            renderer.build_projection(network, research_map, renderer.PUBLIC_MODE)
        )
        second = renderer.render_document(
            renderer.build_projection(copy.deepcopy(network), copy.deepcopy(research_map), renderer.PUBLIC_MODE)
        )
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))

    def test_html_contains_required_sections_and_mobile_contract(self) -> None:
        document = renderer.render_document(
            renderer.build_projection(network_fixture(), map_fixture(), renderer.PUBLIC_MODE)
        )
        for section_id in (
            "field-map",
            "competency-questions",
            "routes-relations",
            "sources",
            "coverage-gaps-conflicts",
            "recommendations",
            "provenance",
        ):
            self.assertIn(f'id="{section_id}"', document)
        self.assertIn('name="viewport"', document)
        self.assertIn("@media (max-width:700px)", document)
        self.assertIn("<svg", document)
        self.assertIn("<script>", document)
        self.assertNotIn("cdn.", document.lower())

    def test_render_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "network.html"
            target.write_text("existing", encoding="utf-8")
            with mock.patch.object(renderer.os, "replace") as replace:
                with self.assertRaisesRegex(renderer.ContractError, "refusing to overwrite"):
                    renderer.write_exclusive(target, "replacement")
            replace.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "existing")

    def test_atomic_publication_uses_target_directory_not_system_temp(self) -> None:
        with (
            tempfile.TemporaryDirectory() as system_temp,
            tempfile.TemporaryDirectory() as target_dir,
        ):
            target = Path(target_dir) / "network.html"
            real_replace = os.replace
            replace_calls: list[tuple[Path, Path]] = []

            def simulated_cross_device_replace(source: str, destination: str) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                replace_calls.append((source_path, destination_path))
                source_device = 1 if source_path.parent == Path(system_temp) else 2
                destination_device = 2 if destination_path.parent == Path(target_dir) else 1
                if source_device != destination_device:
                    raise OSError(errno.EXDEV, "simulated cross-device link")
                real_replace(source, destination)

            with (
                mock.patch.object(renderer.tempfile, "tempdir", system_temp),
                mock.patch.object(
                    renderer.os,
                    "replace",
                    side_effect=simulated_cross_device_replace,
                ),
            ):
                renderer.write_exclusive(target, "published")

            self.assertEqual(target.read_text(encoding="utf-8"), "published")
            self.assertEqual(len(replace_calls), 1)
            source, destination = replace_calls[0]
            self.assertEqual(source.parent, target.parent)
            self.assertEqual(destination, target)
            self.assertNotEqual(source.parent, Path(system_temp))

    def test_replace_failure_cleans_temp_and_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as target_dir:
            target = Path(target_dir) / "network.html"
            with mock.patch.object(
                renderer.os,
                "replace",
                side_effect=OSError(errno.EXDEV, "simulated cross-device link"),
            ):
                with self.assertRaisesRegex(OSError, "cross-device"):
                    renderer.write_exclusive(target, "not committed")

            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_directory_fsync_failure_reports_committed_target(self) -> None:
        with tempfile.TemporaryDirectory() as target_dir:
            target = Path(target_dir) / "network.html"
            fsync_calls = 0
            real_fsync = os.fsync

            def fail_directory_fsync(descriptor: int) -> None:
                nonlocal fsync_calls
                fsync_calls += 1
                if fsync_calls == 2:
                    raise OSError("simulated directory fsync failure")
                real_fsync(descriptor)

            with mock.patch.object(
                renderer.os,
                "fsync",
                side_effect=fail_directory_fsync,
            ):
                with self.assertRaisesRegex(
                    renderer.ContractError,
                    "atomically committed but directory fsync failed",
                ):
                    renderer.write_exclusive(target, "committed")

            self.assertEqual(target.read_text(encoding="utf-8"), "committed")
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_research_map_rejects_unknown_relation_reference(self) -> None:
        research_map = map_fixture()
        research_map["routes"][0]["relation_ids"] = ["REL-UNKNOWN"]
        research_map = seal(research_map)
        with self.assertRaisesRegex(renderer.ContractError, "unknown IDs"):
            renderer.validate_inputs(network_fixture(), research_map)

    def test_recommendation_rejects_unknown_evidence_reference(self) -> None:
        research_map = map_fixture()
        research_map["recommendations"][0]["evidence_refs"] = ["SOURCE-UNKNOWN"]
        research_map = seal(research_map)
        with self.assertRaisesRegex(renderer.ContractError, "unknown IDs"):
            renderer.validate_inputs(network_fixture(), research_map)


if __name__ == "__main__":
    unittest.main()
