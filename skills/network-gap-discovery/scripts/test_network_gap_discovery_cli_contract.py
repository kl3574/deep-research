import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from network_gap_discovery import (
    ContractError,
    load_exported_knowledge_network,
    parser,
    sha256_json,
)


def exported_network_fixture():
    network = {
        "schema": "KnowledgeNetwork/v1",
        "network_id": "KN-CLI",
        "snapshot_id": "KN-CLI-S1",
        "sources": [],
        "nodes": [],
        "relations": [],
        "gaps": [],
        "completion": {"status": "partial"},
    }
    network["content_sha256"] = sha256_json(network)
    return network


class NetworkCliContractTests(unittest.TestCase):
    def test_network_help_names_exported_contract(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            parser().parse_args(["scan", "--help"])
        rendered = " ".join(output.getvalue().split())
        self.assertIn("exported KnowledgeNetwork/v1", rendered)
        self.assertIn("do not pass networks/<id>/network.json", rendered)

    def test_storage_manifest_gets_actionable_export_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "network.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "v1",
                        "network_id": "KN-STORAGE",
                        "corpus_snapshot": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ContractError, "research-knowledge-network export"
            ):
                load_exported_knowledge_network(path)

    def test_exported_network_still_loads(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "knowledge-network.export.json"
            path.write_text(json.dumps(exported_network_fixture()), encoding="utf-8")
            loaded = load_exported_knowledge_network(path)
            self.assertEqual(loaded["schema"], "KnowledgeNetwork/v1")


if __name__ == "__main__":
    unittest.main()
