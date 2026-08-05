from __future__ import annotations

import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
import tempfile
import threading
import sys
from pathlib import Path
import unittest
import urllib.parse

SCRIPT_PATH = Path(__file__).with_name("knowledge_network.py")
SPEC = importlib.util.spec_from_file_location("knowledge_network", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["knowledge_network"] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


def load_deep_validator():
    candidates = (
        SCRIPT_PATH.parents[2]
        / "deep-research"
        / "scripts"
        / "validate_research_handoff.py",
        Path.home()
        / ".codex"
        / "skills"
        / "deep-research"
        / "scripts"
        / "validate_research_handoff.py",
    )
    validator_path = next((path for path in candidates if path.is_file()), None)
    if validator_path is None:
        raise RuntimeError("deep-research validator is unavailable")
    spec = importlib.util.spec_from_file_location(
        "deep_research_handoff_validator", validator_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["deep_research_handoff_validator"] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


def load_snapshot_producer():
    producer_path = (
        SCRIPT_PATH.parents[2]
        / "curate-research-to-zotero"
        / "scripts"
        / "snapshot_zotero_collection.py"
    )
    spec = importlib.util.spec_from_file_location(
        "zotero_snapshot_producer", producer_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["zotero_snapshot_producer"] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


def load_deep_research_run():
    validator = load_deep_validator()
    sys.modules["validate_research_handoff"] = validator
    run_path = (
        SCRIPT_PATH.parents[2]
        / "deep-research"
        / "scripts"
        / "research_run.py"
    )
    spec = importlib.util.spec_from_file_location("deep_research_run", run_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["deep_research_run"] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


def invoke(root: Path, network_id: str, arguments: list[str]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    all_args = ["--root", str(root), "--network-id", network_id, *arguments]
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = MODULE.main(all_args)
    return code, stdout.getvalue(), stderr.getvalue()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest_json(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


class KnowledgeNetworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.network_id = "network-01"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def init_network(
        self,
        network_id: str = "network-01",
        required_dimension: list[str] | None = None,
        required_benchmark: list[str] | None = None,
    ) -> tuple[str, Path, str]:
        snapshot = self.root / f"snapshot-{network_id}.json"
        snapshot.write_text('{"papers": []}', encoding="utf-8")
        digest = sha256(snapshot)
        args = [
            "init",
            "--question", "How to build the local knowledge network?",
            "--scope", "local-reviewed-only",
            "--snapshot-path", str(snapshot),
            "--snapshot-digest", digest,
        ]
        for item in required_dimension or []:
            args.extend(["--required-dimension", item])
        for item in required_benchmark or []:
            args.extend(["--required-benchmark-profile", item])
        code, _, error = invoke(self.root, network_id, args)
        self.assertEqual(code, 0, error)
        return network_id, snapshot, digest

    def make_zotero_snapshot(
        self,
        network_id: str,
        parents: list[dict[str, object]],
        collection_version: int = 1,
    ) -> tuple[Path, str]:
        snapshot_path = self.root / f"{network_id}-zotero-snapshot.json"
        collection = {
            "collection_version": collection_version,
            "group_id": 123456,
            "collection_key": "TESTCOLL",
            "collection_path": [
                {"key": "ROOT", "name": "root", "version": 1},
                {
                    "key": "COLL",
                    "name": "sub",
                    "version": collection_version,
                },
            ],
        }
        snapshot = {
            "schema": MODULE.ZOTERO_SNAPSHOT_SCHEMA,
            "retrieved_at": "2026-01-01T00:00:00Z",
            "collection": collection,
            "parents": parents,
        }
        identity_sha256 = MODULE._sha256_json(
            {
                "group_id": collection["group_id"],
                "collection_key": collection["collection_key"],
                "collection_path": [
                    {"key": item["key"], "name": item["name"]}
                    for item in collection["collection_path"]
                ],
            }
        )
        snapshot["identity_sha256"] = identity_sha256
        snapshot["state_sha256"] = MODULE._sha256_json(
            {
                "identity_sha256": identity_sha256,
                "collection_version": collection_version,
                "parents": parents,
            }
        )
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return snapshot_path, snapshot["state_sha256"]

    def init_network_with_snapshot(
        self, network_id: str, snapshot_path: Path, digest: str
    ) -> tuple[str, Path, str]:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if snapshot.get("schema") == MODULE.ZOTERO_SNAPSHOT_SCHEMA:
            digest = str(snapshot["state_sha256"])
        args = [
            "init",
            "--question", "How to build the local knowledge network?",
            "--scope", "local-reviewed-only",
            "--snapshot-path", str(snapshot_path),
            "--snapshot-digest", digest,
        ]
        code, _, error = invoke(self.root, network_id, args)
        self.assertEqual(code, 0, error)
        return network_id, snapshot_path, digest

    def add_source(
        self,
        network_id: str,
        source_id: str = "source-01",
        version_hash: str | None = None,
    ):
        digest = version_hash or (f"sha256:{'f' * 64}")
        code, _, error = invoke(
            self.root,
            network_id,
            [
                "add-source",
                "--source-id", source_id,
                "--canonical-identity", f"Canonical {source_id}",
                "--canonical-version", "v1",
                "--read-version", "read-v1",
                "--read-depth", "full",
                "--version-hash", digest,
                "--role", "source",
            ],
        )
        self.assertEqual(code, 0, error)
        return digest

    def add_entity(self, network_id: str, entity_id: str = "entity-01"):
        code, _, error = invoke(
            self.root,
            network_id,
            [
                "add-entity",
                "--entity-id", entity_id,
                "--entity-type", "method",
                "--name", f"{entity_id} name",
                "--description", f"{entity_id} desc",
            ],
        )
        self.assertEqual(code, 0, error)

    def add_claim(
        self,
        network_id: str,
        claim_id: str,
        impact: str = "high",
        entity_id: str | None = None,
        dimensions: list[str] | None = None,
        profiles: list[str] | None = None,
    ):
        args = [
            "add-claim",
            "--claim-id", claim_id,
            "--claim-text", f"Claim body for {claim_id}",
            "--impact", impact,
        ]
        if entity_id is not None:
            args.extend(["--entity-id", entity_id])
        for item in dimensions or []:
            args.extend(["--coverage-dimension", item])
        for item in profiles or []:
            args.extend(["--benchmark-profile", item])
        code, _, error = invoke(self.root, network_id, args)
        self.assertEqual(code, 0, error)

    def add_evidence(
        self,
        network_id: str,
        claim_id: str,
        source_id: str,
        polarity: str = "supports",
        evidence_id: str = "evidence-01",
        locator: str = "Figure 2",
    ):
        return invoke(
            self.root,
            network_id,
            [
                "add-evidence",
                "--evidence-id", evidence_id,
                "--claim-id", claim_id,
                "--source-id", source_id,
                "--polarity", polarity,
                "--exact-locator", locator,
                "--independence-group", "group-a",
                "--summary", f"{claim_id} via {source_id}",
            ],
        )

    def parse_status(self, network_id: str):
        code, output, error = invoke(self.root, network_id, ["status"])
        self.assertEqual(code, 0, error)
        return json.loads(output)

    def test_ingest_zotero_snapshot_happy_path_metadata_only(self):
        parents = [
            {
                "key": "BBBBBBBB",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Fallback Parent Two",
                "date": "2025",
                "DOI": "",
                "ISBN": "",
                "creators": [{"creatorType": "author"}],
            },
            {
                "key": "AAAAAAA1",
                "version": 2,
                "item_type": "journalArticle",
                "title": "Parent One",
                "date": "2026",
                "DOI": "10.1000/example-1",
                "ISBN": "",
                "creators": [],
                "children": [
                    {
                        "key": "NOTEAA",
                        "version": 1,
                        "item_type": "note",
                        "availability": "present",
                        "schema_version": "9",
                    },
                    {
                        "key": "PDFAA",
                        "version": 2,
                        "item_type": "attachment",
                        "availability": "local_reference",
                        "content_type": "application/pdf",
                        "artifact_role": "main_text_candidate",
                    },
                ],
            },
        ]
        snapshot_path, state_sha = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=7
        )
        snapshot_digest = sha256(snapshot_path)
        self.init_network_with_snapshot(self.network_id, snapshot_path, snapshot_digest)
        code, output, error = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(code, 0, error)
        payload = json.loads(output)
        self.assertEqual(payload["added"], 2)
        self.assertEqual(payload["existing"], 0)
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["snapshot_state"]["state_sha256"], state_sha)
        self.assertEqual(payload["snapshot_state"]["path"], str(snapshot_path))
        sources = self.load_ledger(self.network_id, "sources")
        expected_ids = [
            MODULE._parent_source_id(
                parent, MODULE._snapshot_parent_identity_hash(parent)
            )
            for parent in MODULE._snapshot_parents_sorted(parents)
        ]
        self.assertEqual([row["source_id"] for row in sources], expected_ids)
        for row in sources:
            self.assertEqual(row["read_depth"], "metadata")
            self.assertEqual(row["role"], "zotero_corpus")
            self.assertEqual(row["canonical_version"], row["read_version"])
            self.assertEqual(
                row["snapshot_state"]["state_sha256"],
                state_sha,
            )
            self.assertNotIn("exact_locator", row)
        self.assertEqual(sources[0]["canonical_identity"], "doi:10.1000/example-1")
        self.assertTrue(sources[1]["canonical_identity"].startswith("title-date:"))
        self.assertEqual(len(self.load_ledger(self.network_id, "claims")), 0)
        self.assertEqual(len(self.load_ledger(self.network_id, "evidence")), 0)

    def test_external_absolute_snapshot_init_and_ingest(self):
        parents = [
            {
                "key": "EXTERNAL1",
                "version": 3,
                "item_type": "journalArticle",
                "title": "External Snapshot Parent",
                "date": "2026",
                "DOI": "10.1000/external-snapshot",
                "ISBN": "",
                "creators": [],
            }
        ]
        local_snapshot, _ = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=4
        )
        with tempfile.TemporaryDirectory() as external_directory:
            external_snapshot = Path(external_directory) / "corpus.json"
            local_snapshot.replace(external_snapshot)
            file_digest = sha256(external_snapshot)
            digest = json.loads(
                external_snapshot.read_text(encoding="utf-8")
            )["state_sha256"]
            initialized = invoke(
                self.root,
                self.network_id,
                [
                    "init",
                    "--question", "Can an external snapshot remain external?",
                    "--scope", "external-private-snapshot",
                    "--snapshot-path", str(external_snapshot),
                    "--snapshot-digest", digest,
                ],
            )
            self.assertEqual(initialized[0], 0, initialized[2])
            ingested = invoke(
                self.root,
                self.network_id,
                ["ingest-zotero-snapshot", "--snapshot", str(external_snapshot)],
            )
            self.assertEqual(ingested[0], 0, ingested[2])
            state = json.loads(
                (self.root / "networks" / self.network_id / "network.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(state["corpus_snapshot_path"], str(external_snapshot))
            self.assertEqual(state["corpus_snapshot_digest"], digest)
            self.assertEqual(state["corpus_snapshot_file_sha256"], file_digest)
            self.assertFalse(
                (self.root / "networks" / self.network_id / "corpus.json").exists()
            )

            escaped_output = Path(external_directory) / "escaped-export.json"
            rejected_output = invoke(
                self.root,
                self.network_id,
                ["export", "--output", str(escaped_output)],
            )
            self.assertEqual(rejected_output[0], 1, rejected_output[2])
            self.assertFalse(escaped_output.exists())

    def test_real_producer_snapshot_contract_and_tamper_rejection(self):
        producer = load_snapshot_producer()
        group_id = 123456
        collection_key = "TESTCOLL"
        responses = {
            f"/api/groups/{group_id}/collections/{collection_key}": {
                "key": collection_key,
                "version": 9,
                "data": {
                    "key": collection_key,
                    "name": "Calibration Corpus",
                    "version": 9,
                    "parentCollection": "ROOTCOLL",
                },
            },
            f"/api/groups/{group_id}/collections/ROOTCOLL": {
                "key": "ROOTCOLL",
                "version": 4,
                "data": {
                    "key": "ROOTCOLL",
                    "name": "Inverse Problems",
                    "version": 4,
                    "parentCollection": False,
                },
            },
            f"/api/groups/{group_id}/collections/{collection_key}/items/top": [
                {
                    "key": "PARENT01",
                    "version": 2,
                    "data": {
                        "key": "PARENT01",
                        "version": 2,
                        "itemType": "journalArticle",
                        "title": "WENDy: Weak-form estimation of nonlinear dynamics",
                        "date": "2023",
                        "DOI": "10.1000/wendy",
                        "ISBN": "",
                        "creators": [
                            {
                                "creatorType": "author",
                                "firstName": "A",
                                "lastName": "Researcher",
                            }
                        ],
                    },
                },
                {
                    "key": "PARENT02",
                    "version": 1,
                    "data": {
                        "key": "PARENT02",
                        "version": 1,
                        "itemType": "journalArticle",
                        "title": "Sparse dynamics benchmark",
                        "date": "2026",
                        "DOI": "",
                        "ISBN": "",
                        "creators": [],
                    },
                },
            ],
            f"/api/groups/{group_id}/items/PARENT01/children": [
                {
                    "key": "NOTE0001",
                    "version": 1,
                    "data": {
                        "key": "NOTE0001",
                        "version": 1,
                        "itemType": "note",
                        "note": '<div data-schema-version="1">reviewed</div>',
                    },
                }
            ],
            f"/api/groups/{group_id}/items/PARENT02/children": [
                {
                    "key": "PDF00001",
                    "version": 1,
                    "data": {
                        "key": "PDF00001",
                        "version": 1,
                        "itemType": "attachment",
                        "title": "Main text",
                        "contentType": "application/pdf",
                        "path": "storage:paper.pdf",
                        "linkMode": "imported_file",
                    },
                }
            ],
        }

        class FakeZoteroHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                payload = responses.get(path)
                if payload is None:
                    self.send_error(404)
                    return
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeZoteroHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as external_directory:
                producer_output = Path(external_directory) / "producer.json"
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                    stderr
                ):
                    producer_code = producer.main(
                        [
                            "--base-url", f"http://127.0.0.1:{server.server_port}",
                            "--group-id", str(group_id),
                            "--collection-key", collection_key,
                            "--output", str(producer_output),
                        ]
                    )
                self.assertEqual(producer_code, 0, stderr.getvalue())
                producer_result = json.loads(stdout.getvalue())
                producer_state = producer_result["state_sha256"]
                producer_payload = json.loads(
                    producer_output.read_text(encoding="utf-8")
                )
                self.assertEqual(producer_result["parents"], 2)

                network_id = "network-producer-integration"
                initialized = invoke(
                    self.root,
                    network_id,
                    [
                        "init",
                        "--question", "Can producer output be consumed directly?",
                        "--scope", "producer-consumer-contract",
                        "--snapshot-path", str(producer_output),
                        "--snapshot-digest", producer_state,
                    ],
                )
                self.assertEqual(initialized[0], 0, initialized[2])
                ingested = invoke(
                    self.root,
                    network_id,
                    [
                        "ingest-zotero-snapshot",
                        "--snapshot", str(producer_output),
                    ],
                )
                self.assertEqual(ingested[0], 0, ingested[2])
                self.assertEqual(len(self.load_ledger(network_id, "sources")), 2)
                state = json.loads(
                    (self.root / "networks" / network_id / "network.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(state["corpus_snapshot_digest"], producer_state)
                self.assertEqual(
                    state["corpus_snapshot_state_sha256"], producer_state
                )
                self.assertEqual(
                    state["corpus_snapshot_identity_sha256"],
                    producer_payload["identity_sha256"],
                )
                self.assertEqual(
                    state["corpus_snapshot_file_sha256"], sha256(producer_output)
                )

                responses[
                    f"/api/groups/{group_id}/collections/{collection_key}"
                ]["version"] = 10
                responses[
                    f"/api/groups/{group_id}/collections/{collection_key}"
                ]["data"]["version"] = 10
                responses[
                    f"/api/groups/{group_id}/collections/{collection_key}/items/top"
                ][0]["version"] = 3
                responses[
                    f"/api/groups/{group_id}/collections/{collection_key}/items/top"
                ][0]["data"]["version"] = 3
                producer_output_v2 = Path(external_directory) / "producer-v2.json"
                v2_stdout = io.StringIO()
                v2_stderr = io.StringIO()
                with contextlib.redirect_stdout(
                    v2_stdout
                ), contextlib.redirect_stderr(v2_stderr):
                    producer_v2_code = producer.main(
                        [
                            "--base-url", f"http://127.0.0.1:{server.server_port}",
                            "--group-id", str(group_id),
                            "--collection-key", collection_key,
                            "--output", str(producer_output_v2),
                        ]
                    )
                self.assertEqual(producer_v2_code, 0, v2_stderr.getvalue())
                producer_v2_result = json.loads(v2_stdout.getvalue())
                self.assertNotEqual(
                    producer_v2_result["state_sha256"], producer_state
                )
                refreshed = invoke(
                    self.root,
                    network_id,
                    [
                        "ingest-zotero-snapshot",
                        "--snapshot", str(producer_output_v2),
                        "--allow-refresh",
                    ],
                )
                self.assertEqual(refreshed[0], 0, refreshed[2])
                refresh_payload = json.loads(refreshed[1])
                self.assertEqual(refresh_payload["added"], 0)
                self.assertEqual(refresh_payload["changed"], 1)
                self.assertEqual(refresh_payload["existing"], 1)
                self.assertEqual(refresh_payload["removed"], 0)
                self.assertEqual(refresh_payload["total"], 2)
                self.assertEqual(len(self.load_ledger(network_id, "sources")), 3)
                refreshed_state = json.loads(
                    (self.root / "networks" / network_id / "network.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    refreshed_state["corpus_snapshot_path"], str(producer_output_v2)
                )
                self.assertEqual(
                    refreshed_state["corpus_snapshot_state_sha256"],
                    producer_v2_result["state_sha256"],
                )
                refresh_events = [
                    event
                    for event in self.load_ledger(network_id, "events")
                    if event.get("event_type") == "snapshot_refreshed"
                ]
                self.assertEqual(len(refresh_events), 1)
                self.assertEqual(
                    refresh_events[0]["previous_snapshot_path"],
                    str(producer_output),
                )
                self.assertEqual(
                    refresh_events[0]["snapshot_path"], str(producer_output_v2)
                )
                self.assertEqual(refresh_events[0]["added"], 0)
                self.assertEqual(refresh_events[0]["changed"], 1)
                self.assertEqual(refresh_events[0]["removed"], 0)
                self.assertEqual(refresh_events[0]["current"], 2)

                file_tamper = Path(external_directory) / "file-tamper.json"
                file_tamper.write_text(
                    producer_output.read_text(encoding="utf-8"), encoding="utf-8"
                )
                file_network = "network-producer-file-tamper"
                file_init = invoke(
                    self.root,
                    file_network,
                    [
                        "init",
                        "--question", "file tamper",
                        "--scope", "tamper",
                        "--snapshot-path", str(file_tamper),
                        "--snapshot-digest", producer_state,
                    ],
                )
                self.assertEqual(file_init[0], 0, file_init[2])
                with file_tamper.open("a", encoding="utf-8") as handle:
                    handle.write("\n")
                file_ingest = invoke(
                    self.root,
                    file_network,
                    ["ingest-zotero-snapshot", "--snapshot", str(file_tamper)],
                )
                self.assertEqual(file_ingest[0], 1, file_ingest[2])
                self.assertIn("file digest mismatch", file_ingest[2])
                self.assertEqual(self.load_ledger(file_network, "sources"), [])

                state_tamper = Path(external_directory) / "state-tamper.json"
                bad_state = json.loads(json.dumps(producer_payload))
                bad_state["state_sha256"] = f"sha256:{'0' * 64}"
                state_tamper.write_text(
                    json.dumps(bad_state, ensure_ascii=False), encoding="utf-8"
                )
                state_init = invoke(
                    self.root,
                    "network-producer-state-tamper",
                    [
                        "init",
                        "--question", "state tamper",
                        "--scope", "tamper",
                        "--snapshot-path", str(state_tamper),
                        "--snapshot-digest", bad_state["state_sha256"],
                    ],
                )
                self.assertEqual(state_init[0], 1, state_init[2])
                self.assertIn("state_sha256 mismatch", state_init[2])

                identity_tamper = Path(external_directory) / "identity-tamper.json"
                bad_identity = json.loads(json.dumps(producer_payload))
                bad_identity["identity_sha256"] = f"sha256:{'1' * 64}"
                bad_identity["state_sha256"] = producer.digest_value(
                    {
                        "identity_sha256": bad_identity["identity_sha256"],
                        "collection_version": bad_identity["collection"][
                            "collection_version"
                        ],
                        "parents": bad_identity["parents"],
                    }
                )
                identity_tamper.write_text(
                    json.dumps(bad_identity, ensure_ascii=False), encoding="utf-8"
                )
                identity_init = invoke(
                    self.root,
                    "network-producer-identity-tamper",
                    [
                        "init",
                        "--question", "identity tamper",
                        "--scope", "tamper",
                        "--snapshot-path", str(identity_tamper),
                        "--snapshot-digest", bad_identity["state_sha256"],
                    ],
                )
                self.assertEqual(identity_init[0], 1, identity_init[2])
                self.assertIn("identity_sha256 mismatch", identity_init[2])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_init_rejects_relative_symlink_and_fifo_snapshot_paths(self):
        target = self.root / "snapshot-input-target.json"
        target.write_text('{"papers": []}', encoding="utf-8")
        relative = invoke(
            self.root,
            "network-relative-input",
            [
                "init",
                "--question", "relative",
                "--scope", "local",
                "--snapshot-path", target.name,
                "--snapshot-digest", sha256(target),
            ],
        )
        self.assertEqual(relative[0], 1, relative[2])
        self.assertIn("must be absolute", relative[2])

        symlink = self.root / "snapshot-input-link.json"
        symlink.symlink_to(target)
        symlink_result = invoke(
            self.root,
            "network-symlink-input",
            [
                "init",
                "--question", "symlink",
                "--scope", "local",
                "--snapshot-path", str(symlink),
                "--snapshot-digest", sha256(target),
            ],
        )
        self.assertEqual(symlink_result[0], 1, symlink_result[2])
        self.assertIn("regular non-symlink", symlink_result[2])

        fifo = self.root / "snapshot-input.fifo"
        os.mkfifo(fifo)
        fifo_result = invoke(
            self.root,
            "network-fifo-input",
            [
                "init",
                "--question", "fifo",
                "--scope", "local",
                "--snapshot-path", str(fifo),
                "--snapshot-digest", f"sha256:{'0' * 64}",
            ],
        )
        self.assertEqual(fifo_result[0], 1, fifo_result[2])
        self.assertIn("regular non-symlink", fifo_result[2])

    def test_init_rejects_snapshot_changed_during_read(self):
        snapshot = self.root / "snapshot-drift.json"
        snapshot.write_text('{"papers": []}', encoding="utf-8")
        original_fingerprint = MODULE._snapshot_file_fingerprint
        calls = 0

        def drifting_fingerprint(metadata):
            nonlocal calls
            calls += 1
            fingerprint = original_fingerprint(metadata)
            if calls == 3:
                return (*fingerprint[:-1], fingerprint[-1] + 1)
            return fingerprint

        MODULE._snapshot_file_fingerprint = drifting_fingerprint
        try:
            result = invoke(
                self.root,
                "network-drifting-input",
                [
                    "init",
                    "--question", "drift",
                    "--scope", "local",
                    "--snapshot-path", str(snapshot),
                    "--snapshot-digest", sha256(snapshot),
                ],
            )
        finally:
            MODULE._snapshot_file_fingerprint = original_fingerprint
        self.assertEqual(result[0], 1, result[2])
        self.assertIn("changed during read", result[2])
        self.assertFalse(
            (self.root / "networks" / "network-drifting-input").exists()
        )

    def test_ingest_zotero_snapshot_idempotent(self):
        parents = [
            {
                "key": "CCCCC111",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Stable Parent",
                "date": "2026",
                "DOI": "10.1000/idempotent",
                "ISBN": "",
                "creators": [],
            },
            {
                "key": "CCCCC112",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Stable Parent B",
                "date": "2024",
                "DOI": "",
                "ISBN": "",
                "creators": [],
            },
        ]
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=1
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        first = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(first[0], 0, first[2])
        second = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(second[0], 0, second[2])
        payload = json.loads(second[1])
        self.assertEqual(payload["added"], 0)
        self.assertEqual(payload["existing"], 2)
        self.assertEqual(len(self.load_ledger(self.network_id, "sources")), 2)

    def test_ingest_zotero_snapshot_refreshes_changed_and_new_parent(self):
        parents_v1 = [
            {
                "key": "REFRESH01",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Versioned Parent",
                "date": "2026",
                "DOI": "10.1000/refreshable",
                "ISBN": "",
                "creators": [],
            },
            {
                "key": "REFRESH00",
                "version": 4,
                "item_type": "journalArticle",
                "title": "Unchanged Parent",
                "date": "2024",
                "DOI": "10.1000/unchanged-parent",
                "ISBN": "",
                "creators": [],
            },
        ]
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, parents_v1, collection_version=1
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        first = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(first[0], 0, first[2])

        parents_v2 = [
            {
                "key": "REFRESH01",
                "version": 2,
                "item_type": "journalArticle",
                "title": "Versioned Parent",
                "date": "2026",
                "DOI": "10.1000/refreshable",
                "ISBN": "",
                "creators": [],
            },
            {
                "key": "REFRESH00",
                "version": 4,
                "item_type": "journalArticle",
                "title": "Unchanged Parent",
                "date": "2024",
                "DOI": "10.1000/unchanged-parent",
                "ISBN": "",
                "creators": [],
            },
            {
                "key": "REFRESH02",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Added Parent",
                "date": "2025",
                "DOI": "10.1000/added-parent",
                "ISBN": "",
                "creators": [],
            },
        ]
        snapshot_path, refreshed_state_digest = self.make_zotero_snapshot(
            self.network_id, parents_v2, collection_version=2
        )
        file_digest = sha256(snapshot_path)
        refresh = invoke(
            self.root,
            self.network_id,
            [
                "ingest-zotero-snapshot",
                "--snapshot",
                str(snapshot_path),
                "--allow-refresh",
            ],
        )
        self.assertEqual(refresh[0], 0, refresh[2])
        payload = json.loads(refresh[1])
        self.assertEqual(payload["added"], 1)
        self.assertEqual(payload["changed"], 1)
        self.assertEqual(payload["existing"], 1)
        self.assertEqual(payload["total"], 3)
        self.assertEqual(
            payload["snapshot_state"]["digest"], refreshed_state_digest
        )
        self.assertEqual(payload["snapshot_state"]["file_sha256"], file_digest)
        sources = self.load_ledger(self.network_id, "sources")
        self.assertEqual(len(sources), 4)

        grouped = {}
        for source in sources:
            grouped.setdefault(source["canonical_identity"], []).append(source)
        parent_identity = "doi:10.1000/refreshable"
        versions = grouped[parent_identity]
        self.assertEqual(len(versions), 2)
        versions = sorted(versions, key=lambda row: row["sequence"])
        self.assertEqual(versions[1]["supersedes"], versions[0]["source_id"])

        expected_current_ids = [
            MODULE._parent_source_id(
                parent, MODULE._snapshot_parent_identity_hash(parent)
            )
            for parent in MODULE._snapshot_parents_sorted(parents_v2)
        ]
        state = json.loads(
            (self.root / "networks" / self.network_id / "network.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            state["corpus_snapshot_current_source_ids"], expected_current_ids
        )
        events = self.load_ledger(self.network_id, "events")
        self.assertEqual(
            sorted(
                {
                    row["event_type"]
                    for row in events
                    if row.get("event_type") is not None
                }
            ),
            ["init", "snapshot_refreshed"],
        )

    def test_ingest_zotero_snapshot_allow_refresh_requires_matching_identity(self):
        parents = [
            {
                "key": "MISMATCH01",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Identity Snapshot",
                "date": "2026",
                "DOI": "10.1000/mismatch",
                "ISBN": "",
                "creators": [],
            }
        ]
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=1
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )

        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=2
        )
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        payload["collection"]["group_id"] = 999999
        payload["identity_sha256"] = MODULE._sha256_json(
            {
                "group_id": payload["collection"]["group_id"],
                "collection_key": payload["collection"]["collection_key"],
                "collection_path": payload["collection"]["collection_path"],
            }
        )
        payload["state_sha256"] = MODULE._sha256_json(
            {
                "identity_sha256": payload["identity_sha256"],
                "collection_version": payload["collection"]["collection_version"],
                "parents": payload["parents"],
            }
        )
        snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        mismatch = invoke(
            self.root,
            self.network_id,
            [
                "ingest-zotero-snapshot",
                "--snapshot",
                str(snapshot_path),
                "--allow-refresh",
            ],
        )
        self.assertEqual(mismatch[0], 1, mismatch[2])
        self.assertIn("identity_sha256 mismatch", mismatch[2])

    def test_ingest_zotero_snapshot_allow_refresh_removals_preserve_ledger(self):
        parents = [
            {
                "key": "REMOVE01",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Keep Parent",
                "date": "2026",
                "DOI": "10.1000/keep-parent",
                "ISBN": "",
                "creators": [],
            },
            {
                "key": "REMOVE02",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Remove Parent",
                "date": "2025",
                "DOI": "10.1000/remove-parent",
                "ISBN": "",
                "creators": [],
            },
        ]
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=1
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(len(self.load_ledger(self.network_id, "sources")), 2)

        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, [parents[0]], collection_version=2
        )
        refresh = invoke(
            self.root,
            self.network_id,
            [
                "ingest-zotero-snapshot",
                "--snapshot",
                str(snapshot_path),
                "--allow-refresh",
            ],
        )
        self.assertEqual(refresh[0], 0, refresh[2])
        payload = json.loads(refresh[1])
        self.assertEqual(payload["added"], 0)
        self.assertEqual(payload["existing"], 1)
        self.assertEqual(payload["removed"], 1)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(self.load_ledger(self.network_id, "sources")), 2)
        status = self.parse_status(self.network_id)
        self.assertEqual(status["snapshot"]["current_count"], 1)
        self.assertEqual(len(status["snapshot"]["current_sources"]), 1)
        current_source_ids = status["snapshot"]["current_sources"]
        removed_id = MODULE._parent_source_id(
            parents[1], MODULE._snapshot_parent_identity_hash(parents[1])
        )
        self.assertNotIn(removed_id, current_source_ids)

    def test_ingest_zotero_snapshot_rejects_digest_or_path(self):
        parents = [
            {
                "key": "PATH0001",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Path Test Parent",
                "date": "2026",
                "DOI": "10.1000/path-test",
                "ISBN": "",
                "creators": [],
            }
        ]
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=1
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        snapshot_path.write_text(
            snapshot_path.read_text(encoding="utf-8").replace("PATH0001", "PATH0002"),
            encoding="utf-8",
        )
        digest_mismatch = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(digest_mismatch[0], 1, digest_mismatch[2])
        self.assertEqual(len(self.load_ledger(self.network_id, "sources")), 0)

        copy_path = self.root / "copied-snapshot.json"
        copy_path.write_text(
            snapshot_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        path_mismatch = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(copy_path)],
        )
        self.assertEqual(path_mismatch[0], 1, path_mismatch[2])
        self.assertEqual(len(self.load_ledger(self.network_id, "sources")), 0)

    def test_ingest_zotero_snapshot_rejects_schema(self):
        snapshot_path = self.root / "schema-wrong.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "schema": "not-supported",
                    "retrieved_at": "2026-01-01T00:00:00Z",
                    "collection": {"collection_version": 1},
                    "identity_sha256": "sha256:" + "0" * 64,
                    "state_sha256": "sha256:" + "0" * 64,
                    "parents": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        path_digest = sha256(snapshot_path)
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, path_digest
        )
        code, _, error = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(code, 1, error)
        self.assertEqual(len(self.load_ledger(self.network_id, "sources")), 0)

    def test_ingest_zotero_snapshot_rejects_declared_identity_or_state_digest(self):
        parent = {
            "key": "DIGEST01",
            "version": 1,
            "item_type": "journalArticle",
            "title": "Digest Parent",
            "date": "2026",
            "DOI": "10.1000/digest-parent",
            "ISBN": "",
            "creators": [],
        }
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, [parent], collection_version=1
        )
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        payload["identity_sha256"] = f"sha256:{'a' * 64}"
        snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        identity = invoke(
            self.root,
            self.network_id,
            [
                "init",
                "--question", "identity digest tamper",
                "--scope", "tamper",
                "--snapshot-path", str(snapshot_path),
                "--snapshot-digest", payload["state_sha256"],
            ],
        )
        self.assertEqual(identity[0], 1, identity[2])
        self.assertIn("identity_sha256 mismatch", identity[2])
        self.assertFalse((self.root / "networks" / self.network_id).exists())

        state_network = "network-state-digest"
        snapshot_path, _ = self.make_zotero_snapshot(
            state_network, [parent], collection_version=1
        )
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        payload["state_sha256"] = f"sha256:{'b' * 64}"
        snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        state_result = invoke(
            self.root,
            state_network,
            [
                "init",
                "--question", "state digest tamper",
                "--scope", "tamper",
                "--snapshot-path", str(snapshot_path),
                "--snapshot-digest", payload["state_sha256"],
            ],
        )
        self.assertEqual(state_result[0], 1, state_result[2])
        self.assertIn("state_sha256 mismatch", state_result[2])

    def test_ingest_zotero_snapshot_rejects_relative_path_and_parent_shape(self):
        parent = {
            "key": "SHAPE001",
            "version": 1,
            "item_type": "journalArticle",
            "title": "Shape Parent",
            "date": "2026",
            "DOI": "10.1000/shape-parent",
            "ISBN": "",
            "creators": [],
        }
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, [parent], collection_version=1
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        relative = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", snapshot_path.name],
        )
        self.assertEqual(relative[0], 1, relative[2])
        self.assertIn("absolute path", relative[2])

        malformed_network = "network-parent-shape"
        snapshot_path, _ = self.make_zotero_snapshot(
            malformed_network, [parent], collection_version=1
        )
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        payload["parents"][0]["version"] = "one"
        payload["state_sha256"] = MODULE._sha256_json(
            {
                "identity_sha256": payload["identity_sha256"],
                "collection_version": payload["collection"]["collection_version"],
                "parents": payload["parents"],
            }
        )
        snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        malformed = invoke(
            self.root,
            malformed_network,
            [
                "init",
                "--question", "parent shape tamper",
                "--scope", "tamper",
                "--snapshot-path", str(snapshot_path),
                "--snapshot-digest", payload["state_sha256"],
            ],
        )
        self.assertEqual(malformed[0], 1, malformed[2])
        self.assertIn("version missing or invalid", malformed[2])

    def test_ingest_zotero_snapshot_rejects_corrupt(self):
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id,
            [
                {
                    "key": "CORRUPT1",
                    "version": 1,
                    "item_type": "journalArticle",
                    "title": "Corrupt Parent",
                    "date": "2026",
                    "DOI": "10.1000/corrupt",
                    "ISBN": "",
                    "creators": [],
                }
            ],
            collection_version=1,
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        snapshot_path.write_text(
            '{"schema": "ZoteroCorpusSnapshot/v1"', encoding="utf-8"
        )
        code, _, error = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(code, 1, error)
        self.assertEqual(len(self.load_ledger(self.network_id, "sources")), 0)

    def test_ingest_zotero_snapshot_rejects_symlink(self):
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id,
            [
                {
                    "key": "SYM00111",
                    "version": 1,
                    "item_type": "journalArticle",
                    "title": "Symlink Parent",
                    "date": "2026",
                    "DOI": "10.1000/symlink",
                    "ISBN": "",
                    "creators": [],
                }
            ],
            collection_version=1,
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        symlink = self.root / "symlink-snapshot.json"
        symlink.symlink_to(snapshot_path)
        code, _, error = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(symlink)],
        )
        self.assertEqual(code, 1, error)
        self.assertEqual(len(self.load_ledger(self.network_id, "sources")), 0)

    def test_ingest_zotero_snapshot_rollback_on_batch_conflict(self):
        parents = [
            {
                "key": "ROLLBACK1",
                "version": 2,
                "item_type": "journalArticle",
                "title": "Rollback Parent",
                "date": "2026",
                "DOI": "10.1000/rollback",
                "ISBN": "",
                "creators": [],
            },
            {
                "key": "ROLLBACK2",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Rollback Parent B",
                "date": "2026",
                "DOI": "10.1000/rollback-b",
                "ISBN": "",
                "creators": [],
            },
        ]
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=1
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        conflict_parent = parents[0]
        conflict_source_id = MODULE._parent_source_id(
            conflict_parent, MODULE._snapshot_parent_identity_hash(conflict_parent)
        )
        conflict = invoke(
            self.root,
            self.network_id,
            [
                "add-source",
                "--source-id", conflict_source_id,
                "--canonical-identity", "conflict",
                "--canonical-version", "v-conflict",
                "--read-version", "read-conflict",
                "--read-depth", "metadata",
                "--version-hash", f"sha256:{'0' * 64}",
                "--role", "source",
            ],
        )
        self.assertEqual(conflict[0], 0, conflict[2])
        ingest = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(ingest[0], 1, ingest[2])
        sources = self.load_ledger(self.network_id, "sources")
        self.assertEqual(len(sources), 1)

    def test_validate_rejects_tampered_current_snapshot_membership(self):
        parents = [
            {
                "key": "MEMBER01",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Membership Parent A",
                "date": "2026",
                "DOI": "10.1000/member-a",
                "ISBN": "",
                "creators": [],
            },
            {
                "key": "MEMBER02",
                "version": 1,
                "item_type": "journalArticle",
                "title": "Membership Parent B",
                "date": "2026",
                "DOI": "10.1000/member-b",
                "ISBN": "",
                "creators": [],
            },
        ]
        snapshot_path, _ = self.make_zotero_snapshot(
            self.network_id, parents, collection_version=1
        )
        self.init_network_with_snapshot(
            self.network_id, snapshot_path, sha256(snapshot_path)
        )
        ingested = invoke(
            self.root,
            self.network_id,
            ["ingest-zotero-snapshot", "--snapshot", str(snapshot_path)],
        )
        self.assertEqual(ingested[0], 0, ingested[2])
        state_path = self.root / "networks" / self.network_id / "network.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["corpus_snapshot_current_source_ids"] = state[
            "corpus_snapshot_current_source_ids"
        ][:-1]
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        validated = invoke(self.root, self.network_id, ["validate"])
        self.assertEqual(validated[0], 1, validated[2])
        self.assertIn("current membership mismatch", validated[1])

    def test_residual_transaction_journal_blocks_validation(self):
        self.init_network(self.network_id)
        journal = (
            self.root
            / "networks"
            / self.network_id
            / ".transaction.json"
        )
        journal.write_text(
            json.dumps(
                {
                    "schema": "KnowledgeNetworkTransaction/v1",
                    "status": "prepared",
                    "targets": [],
                }
            ),
            encoding="utf-8",
        )
        validated = invoke(self.root, self.network_id, ["validate"])
        self.assertEqual(validated[0], 1, validated[2])
        self.assertIn("transaction journal", validated[2])

    def load_ledger(self, network_id: str, name: str) -> list[dict[str, object]]:
        path = self.root / "networks" / network_id / f"{name}.jsonl"
        rows: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def test_happy_path_and_validate(self):
        self.init_network(self.network_id)
        self.add_source(self.network_id, "source-01")
        self.add_entity(self.network_id)
        self.add_claim(self.network_id, "claim-01", impact="medium")
        code, _, error = self.add_evidence(
            self.network_id, "claim-01", "source-01", evidence_id="evidence-01"
        )
        self.assertEqual(code, 0, error)
        relation = invoke(
            self.root,
            self.network_id,
            [
                "add-relation",
                "--relation-id", "relation-01",
                "--relation-type", "supports",
                "--from-ref", "claim:claim-01",
                "--to-ref", "evidence:evidence-01",
            ],
        )
        self.assertEqual(relation[0], 0, relation[2])
        gap = invoke(
            self.root,
            self.network_id,
            ["derive-gaps"],
        )
        self.assertEqual(gap[0], 0, gap[2])
        status = self.parse_status(self.network_id)
        self.assertFalse(status["open_conflicts"])
        self.assertEqual(status["validation_errors"], [])
        validate = invoke(self.root, self.network_id, ["validate"])
        self.assertEqual(validate[0], 0)

    def test_locator_missing_rejected(self):
        self.init_network(self.network_id, required_dimension=[], required_benchmark=[])
        self.add_source(self.network_id, "source-01")
        self.add_entity(self.network_id)
        self.add_claim(self.network_id, "claim-locator")
        code, _, _ = invoke(
            self.root,
            self.network_id,
            [
                "add-evidence",
                "--evidence-id", "evidence-locator",
                "--claim-id", "claim-locator",
                "--source-id", "source-01",
                "--polarity", "supports",
                "--independence-group", "g1",
                "--summary", "locator missing by test",
            ],
        )
        self.assertEqual(code, 2)

    def test_source_hash_version_mismatch(self):
        self.init_network(self.network_id)
        first = f"sha256:{'1' * 64}"
        self.add_source(self.network_id, "source-bad", version_hash=first)
        code, _, error = invoke(
            self.root,
            self.network_id,
            [
                "add-source",
                "--source-id", "source-bad",
                "--canonical-identity", "Canonical source-bad",
                "--canonical-version", "v1",
                "--read-version", "read-v1",
                "--read-depth", "full",
                "--version-hash", f"sha256:{'2' * 64}",
                "--role", "source",
            ],
        )
        self.assertEqual(code, 1, error)

    def test_conflict_and_single_source_gaps(self):
        self.init_network(self.network_id)
        self.add_source(self.network_id, "source-a", version_hash=f"sha256:{'a' * 64}")
        self.add_source(self.network_id, "source-b", version_hash=f"sha256:{'b' * 64}")
        self.add_entity(self.network_id)
        self.add_claim(self.network_id, "claim-conflict", impact="high")
        code, _, error = self.add_evidence(
            self.network_id,
            "claim-conflict",
            "source-a",
            polarity="supports",
            evidence_id="ev-a",
            locator="Fig A",
        )
        self.assertEqual(code, 0, error)
        code, _, error = self.add_evidence(
            self.network_id,
            "claim-conflict",
            "source-b",
            polarity="contradicts",
            evidence_id="ev-b",
            locator="Fig B",
        )
        self.assertEqual(code, 0, error)
        derive = invoke(self.root, self.network_id, ["derive-gaps"])
        self.assertEqual(derive[0], 0, derive[2])
        status = self.parse_status(self.network_id)
        self.assertIn("claim-conflict", status["open_conflicts"])

        # single-source gap is not created when two independent groups exist
        self.add_claim(self.network_id, "claim-single", impact="medium")
        code, _, error = self.add_evidence(
            self.network_id,
            "claim-single",
            "source-a",
            polarity="supports",
            evidence_id="ev-single",
            locator="Fig C",
        )
        self.assertEqual(code, 0, error)
        derive_single = invoke(self.root, self.network_id, ["derive-gaps"])
        self.assertEqual(derive_single[0], 0, derive_single[2])
        status = self.parse_status(self.network_id)
        self.assertIn("derived:single-source:claim-single", status["open_gaps"])

    def test_implicit_candidate_tabi_fields_and_novelty_guard(self):
        self.init_network(self.network_id)
        self.add_entity(self.network_id)
        self.add_claim(self.network_id, "claim-isolate", impact="low")
        derive = invoke(self.root, self.network_id, ["derive-gaps"])
        self.assertEqual(derive[0], 0, derive[2])
        status = self.parse_status(self.network_id)
        self.assertIn("derived:isolated:claim-isolate", status["open_gaps"])

        # explicit novelty claim on implicit candidate must be rejected
        reject = invoke(
            self.root,
            self.network_id,
            [
                "record-gap",
                "--gap-id", "gap-novelty",
                "--gap-type", "implicit_candidate",
                "--claim-id", "claim-isolate",
                "--impact", "medium",
                "--status", "open",
                "--description", "novelty check",
                "--grounds", "isolated",
                "--warrant", "needs evidence",
                "--backing", "none",
                "--qualifier", "candidate only",
                "--defeaters", "none",
                "--search-test", "search route",
                "--novelty-claimed",
            ],
        )
        self.assertEqual(reject[0], 1, reject[2])

    def test_explicit_gap_records_novelty_flag(self):
        self.init_network(self.network_id)
        self.add_source(self.network_id, "source-01")
        self.add_entity(self.network_id)
        self.add_claim(self.network_id, "claim-novelty", impact="low")
        accept = invoke(
            self.root,
            self.network_id,
            [
                "record-gap",
                "--gap-id",
                "gap-novelty-explicit",
                "--gap-type",
                "explicit",
                "--claim-id",
                "claim-novelty",
                "--impact",
                "medium",
                "--status",
                "open",
                "--description",
                "explicitly marked novelty",
                "--source",
                "researcher-review",
                "--novelty-claimed",
            ],
        )
        self.assertEqual(accept[0], 0, accept[2])
        status = self.parse_status(self.network_id)
        self.assertIn("gap-novelty-explicit", status["open_gaps"])

    def test_gap_transition_resolve_and_reopen_is_append_only(self):
        self.init_network(self.network_id)
        self.add_source(self.network_id, "source-transition")
        self.add_claim(self.network_id, "claim-transition", impact="medium")
        evidence = self.add_evidence(
            self.network_id,
            "claim-transition",
            "source-transition",
            evidence_id="evidence-transition",
            locator="Table 2",
        )
        self.assertEqual(evidence[0], 0, evidence[2])
        gap = invoke(
            self.root,
            self.network_id,
            [
                "record-gap",
                "--gap-id", "gap-transition",
                "--gap-type", "explicit",
                "--claim-id", "claim-transition",
                "--impact", "medium",
                "--status", "open",
                "--description", "Targeted search required",
                "--source", "reviewer",
            ],
        )
        self.assertEqual(gap[0], 0, gap[2])
        initial_record_id = self.load_ledger(self.network_id, "gaps")[-1]["record_id"]
        self.assertRegex(initial_record_id, MODULE.ID_RE)
        self.assertNotIn(":", initial_record_id)
        resolved = invoke(
            self.root,
            self.network_id,
            [
                "transition-gap",
                "--gap-id", "gap-transition",
                "--from-record-id", initial_record_id,
                "--status", "resolved",
                "--reason", "Targeted evidence now covers the missing route",
                "--evidence-ref", "evidence-transition",
            ],
        )
        self.assertEqual(resolved[0], 0, resolved[2])
        resolved_payload = json.loads(resolved[1])
        status = self.parse_status(self.network_id)
        self.assertNotIn("gap-transition", status["open_gaps"])

        stale = invoke(
            self.root,
            self.network_id,
            [
                "transition-gap",
                "--gap-id", "gap-transition",
                "--from-record-id", initial_record_id,
                "--status", "open",
                "--reason", "Stale transition attempt",
            ],
        )
        self.assertEqual(stale[0], 1, stale[2])

        reopened = invoke(
            self.root,
            self.network_id,
            [
                "transition-gap",
                "--gap-id", "gap-transition",
                "--from-record-id", resolved_payload["record_id"],
                "--status", "open",
                "--reason", "New contradictory result requires another search",
            ],
        )
        self.assertEqual(reopened[0], 0, reopened[2])
        rows = self.load_ledger(self.network_id, "gaps")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["status"], "open")
        self.assertEqual(rows[1]["status"], "resolved")
        self.assertEqual(rows[2]["status"], "open")
        self.assertEqual(rows[2]["supersedes"], rows[1]["record_id"])
        self.assertIn("gap-transition", self.parse_status(self.network_id)["open_gaps"])
        self.assertEqual(invoke(self.root, self.network_id, ["validate"])[0], 0)

    def test_gap_resolution_requires_known_evidence(self):
        self.init_network(self.network_id)
        gap = invoke(
            self.root,
            self.network_id,
            [
                "record-gap",
                "--gap-id", "gap-needs-evidence",
                "--gap-type", "explicit",
                "--impact", "high",
                "--status", "open",
                "--description", "Evidence is still absent",
                "--source", "reviewer",
            ],
        )
        self.assertEqual(gap[0], 0, gap[2])
        gap_ledger = self.root / "networks" / self.network_id / "gaps.jsonl"
        initial_record_id = self.load_ledger(self.network_id, "gaps")[-1]["record_id"]
        before = gap_ledger.read_bytes()
        rejected = invoke(
            self.root,
            self.network_id,
            [
                "transition-gap",
                "--gap-id", "gap-needs-evidence",
                "--from-record-id", initial_record_id,
                "--status", "resolved",
                "--reason", "Unsupported closure",
            ],
        )
        self.assertEqual(rejected[0], 1, rejected[2])
        self.assertIn("requires evidence references", rejected[2])
        self.assertEqual(gap_ledger.read_bytes(), before)
        self.assertEqual(len(self.load_ledger(self.network_id, "gaps")), 1)

    def test_gap_resolution_rejects_unrelated_evidence_before_append(self):
        self.init_network(self.network_id)
        self.add_source(self.network_id, "source-gap-a")
        self.add_source(
            self.network_id,
            "source-gap-b",
            version_hash=f"sha256:{'b' * 64}",
        )
        self.add_claim(self.network_id, "claim-gap-a", impact="medium")
        self.add_claim(self.network_id, "claim-gap-b", impact="medium")
        evidence = self.add_evidence(
            self.network_id,
            "claim-gap-b",
            "source-gap-b",
            evidence_id="evidence-gap-b",
        )
        self.assertEqual(evidence[0], 0, evidence[2])
        recorded = invoke(
            self.root,
            self.network_id,
            [
                "record-gap",
                "--gap-id", "gap-claim-a",
                "--gap-type", "explicit",
                "--claim-id", "claim-gap-a",
                "--impact", "medium",
                "--status", "open",
                "--source", "reviewer",
                "--description", "claim A still lacks evidence",
            ],
        )
        self.assertEqual(recorded[0], 0, recorded[2])
        ledger = self.root / "networks" / self.network_id / "gaps.jsonl"
        initial_record_id = self.load_ledger(self.network_id, "gaps")[-1]["record_id"]
        before = ledger.read_bytes()
        rejected = invoke(
            self.root,
            self.network_id,
            [
                "transition-gap",
                "--gap-id", "gap-claim-a",
                "--from-record-id", initial_record_id,
                "--status", "resolved",
                "--reason", "wrong claim evidence",
                "--evidence-ref", "evidence-gap-b",
            ],
        )
        self.assertEqual(rejected[0], 1, rejected[2])
        self.assertIn("must reference the gap claim", rejected[2])
        self.assertEqual(ledger.read_bytes(), before)

    def test_initial_resolved_gap_requires_evidence_before_append(self):
        self.init_network(self.network_id)
        ledger = self.root / "networks" / self.network_id / "gaps.jsonl"
        before = ledger.read_bytes()
        rejected = invoke(
            self.root,
            self.network_id,
            [
                "record-gap",
                "--gap-id", "gap-invalid-resolution",
                "--gap-type", "explicit",
                "--impact", "medium",
                "--status", "resolved",
                "--source", "reviewer",
                "--description", "unsupported initial resolution",
            ],
        )
        self.assertEqual(rejected[0], 1, rejected[2])
        self.assertIn("requires evidence references", rejected[2])
        self.assertEqual(ledger.read_bytes(), before)

    def test_coverage_unmet_blocks_completion(self):
        self.init_network(self.network_id, ["coverage-dim"], ["profile-x"])
        self.add_source(self.network_id, "source-01")
        self.add_entity(self.network_id)
        self.add_claim(self.network_id, "claim-coverage", impact="high")
        invoke(self.root, self.network_id, ["derive-gaps"])
        status = self.parse_status(self.network_id)
        self.assertIn("unmet_coverage", status["completion"]["blockers"])
        self.assertFalse(status["completion"]["can_complete"])
        self.assertEqual(status["coverage"]["missing_dimensions"], ["coverage-dim"])
        self.assertEqual(
            status["coverage"]["missing_benchmark_profiles"], ["profile-x"]
        )

    def test_coverage_check_uses_evidence_backed_network_union(self):
        self.init_network(self.network_id, ["required-a", "required-b"], [])
        self.add_source(self.network_id, "source-01")
        self.add_entity(self.network_id)
        self.add_claim(
            self.network_id,
            "claim-covered",
            impact="high",
            dimensions=["required-a", "required-b", "extra-dim"],
        )
        self.add_claim(
            self.network_id,
            "claim-missing",
            impact="medium",
            dimensions=["required-a"],
        )
        evidence = self.add_evidence(
            self.network_id,
            "claim-covered",
            "source-01",
            evidence_id="evidence-covered",
        )
        self.assertEqual(evidence[0], 0, evidence[2])
        invoke(self.root, self.network_id, ["derive-gaps"])
        status = self.parse_status(self.network_id)
        self.assertEqual(status["coverage"]["missing_dimensions"], [])
        self.assertEqual(
            status["coverage"]["evidence_backed_active_claim_ids"],
            ["claim-covered"],
        )
        self.assertEqual(
            status["coverage"]["decisive_evidence_polarities"], ["supports"]
        )

    def test_non_support_evidence_does_not_satisfy_decisive_coverage(self):
        for polarity in ("qualifies", "contradicts", "not_tested"):
            with self.subTest(polarity=polarity):
                network_id = f"coverage-{polarity}"
                self.init_network(network_id, ["doe-route"], [])
                self.add_source(network_id, "source-01")
                self.add_entity(network_id)
                self.add_claim(
                    network_id,
                    "claim-doe",
                    impact="high",
                    dimensions=["doe-route"],
                )
                evidence = self.add_evidence(
                    network_id,
                    "claim-doe",
                    "source-01",
                    evidence_id="evidence-doe",
                    polarity=polarity,
                )
                self.assertEqual(evidence[0], 0, evidence[2])
                status = self.parse_status(network_id)
                self.assertEqual(status["coverage"]["covered_dimensions"], [])
                self.assertEqual(
                    status["coverage"]["evidence_backed_active_claim_ids"], []
                )
                self.assertEqual(
                    status["high_impact_claims_with_no_decisive_evidence"], 1
                )
                self.assertIn("unmet_coverage", status["completion"]["blockers"])

    def test_claimless_high_priority_explicit_gap_blocks_completion(self):
        cases = (
            ("p0", ["--priority", "P0"], "low"),
            ("p1", ["--priority", "P1"], "low"),
            (
                "decision",
                ["--priority", "P2", "--decision-impact", "high"],
                "low",
            ),
            ("legacy", [], "medium"),
        )
        for suffix, extra, impact in cases:
            with self.subTest(case=suffix):
                network_id = f"blocking-gap-{suffix}"
                gap_id = f"gap-{suffix}"
                self.init_network(network_id, [], [])
                result = invoke(
                    self.root,
                    network_id,
                    [
                        "record-gap",
                        "--gap-id",
                        gap_id,
                        "--gap-type",
                        "explicit",
                        "--impact",
                        impact,
                        "--status",
                        "open",
                        "--source",
                        "doe-real-fixture",
                        "--description",
                        "Decision-relevant DoE gap",
                        *extra,
                    ],
                )
                self.assertEqual(result[0], 0, result[2])
                status = self.parse_status(network_id)
                self.assertFalse(status["completion"]["can_complete"])
                self.assertIn(
                    "open_high_priority_explicit_gap",
                    status["completion"]["blockers"],
                )
                self.assertEqual(
                    status["open_high_priority_explicit_gap_ids"], [gap_id]
                )

    def test_claimless_p2_low_explicit_gap_does_not_block_status_completion(self):
        self.init_network(self.network_id, [], [])
        result = invoke(
            self.root,
            self.network_id,
            [
                "record-gap",
                "--gap-id",
                "gap-p2-low",
                "--gap-type",
                "explicit",
                "--impact",
                "low",
                "--priority",
                "P2",
                "--status",
                "open",
                "--source",
                "doe-real-fixture",
                "--description",
                "Non-blocking follow-up",
            ],
        )
        self.assertEqual(result[0], 0, result[2])
        status = self.parse_status(self.network_id)
        self.assertTrue(status["completion"]["can_complete"])
        self.assertEqual(status["open_high_priority_explicit_gap_ids"], [])

    def test_collective_coverage_derives_two_aggregate_gaps_not_cartesian(self):
        dimensions = [
            "direct_calibration",
            "noise_robustness",
            "partial_observation",
            "cross_method_model_discovery",
        ]
        profiles = [
            "linear_oscillator",
            "lotka_volterra",
            "reaction_network",
            "lorenz",
            "hidden_dynamics",
        ]
        self.init_network(self.network_id, dimensions, profiles)
        claim_coverage = [
            (["direct_calibration"], ["linear_oscillator"]),
            (["noise_robustness"], ["lotka_volterra"]),
            (["partial_observation"], ["reaction_network"]),
            ([], ["lorenz"]),
            (["direct_calibration"], []),
            (["noise_robustness"], []),
            ([], ["linear_oscillator"]),
        ]
        for index, (claim_dimensions, claim_profiles) in enumerate(claim_coverage):
            source_id = f"source-{index}"
            claim_id = f"claim-{index}"
            self.add_source(
                self.network_id,
                source_id,
                version_hash=f"sha256:{str(index + 1) * 64}",
            )
            self.add_claim(
                self.network_id,
                claim_id,
                impact="medium",
                dimensions=claim_dimensions,
                profiles=claim_profiles,
            )
            evidence = self.add_evidence(
                self.network_id,
                claim_id,
                source_id,
                evidence_id=f"evidence-{index}",
            )
            self.assertEqual(evidence[0], 0, evidence[2])

        first = invoke(self.root, self.network_id, ["derive-gaps"])
        self.assertEqual(first[0], 0, first[2])
        first_payload = json.loads(first[1])
        aggregate_ids = {
            "derived:missing-dimension:cross_method_model_discovery",
            "derived:missing-profile:hidden_dynamics",
        }
        local_ids = {f"derived:single-source:claim-{index}" for index in range(7)}
        self.assertEqual(set(first_payload["appended_gap_ids"]), aggregate_ids | local_ids)
        self.assertEqual(len(first_payload["appended_gap_ids"]), 9)
        status = self.parse_status(self.network_id)
        self.assertEqual(
            status["coverage"]["missing_dimensions"],
            ["cross_method_model_discovery"],
        )
        self.assertEqual(
            status["coverage"]["missing_benchmark_profiles"],
            ["hidden_dynamics"],
        )

        network_dir = self.root / "networks" / self.network_id
        gaps_before = (network_dir / "gaps.jsonl").read_bytes()
        events_before = (network_dir / "events.jsonl").read_bytes()
        second = invoke(self.root, self.network_id, ["derive-gaps"])
        self.assertEqual(second[0], 0, second[2])
        self.assertEqual(json.loads(second[1])["appended_gap_ids"], [])
        self.assertEqual((network_dir / "gaps.jsonl").read_bytes(), gaps_before)
        self.assertEqual((network_dir / "events.jsonl").read_bytes(), events_before)

    def test_colon_gap_id_validate_export_and_explicit_reopen(self):
        self.init_network(self.network_id, ["cross_method_model_discovery"], [])
        self.add_source(self.network_id, "source-colon")
        self.add_claim(self.network_id, "claim-colon", impact="medium")
        evidence = self.add_evidence(
            self.network_id,
            "claim-colon",
            "source-colon",
            evidence_id="evidence-colon",
        )
        self.assertEqual(evidence[0], 0, evidence[2])
        derived = invoke(self.root, self.network_id, ["derive-gaps"])
        self.assertEqual(derived[0], 0, derived[2])
        gap_id = "derived:missing-dimension:cross_method_model_discovery"
        row = next(
            row
            for row in self.load_ledger(self.network_id, "gaps")
            if row["gap_id"] == gap_id
        )
        self.assertRegex(row["record_id"], MODULE.ID_RE)
        resolved = invoke(
            self.root,
            self.network_id,
            [
                "transition-gap",
                "--gap-id", gap_id,
                "--from-record-id", row["record_id"],
                "--status", "resolved",
                "--reason", "Coverage route reviewed",
                "--evidence-ref", "evidence-colon",
                "--resolution-source", "manual coverage audit",
            ],
        )
        self.assertEqual(resolved[0], 0, resolved[2])
        resolved_row = json.loads(resolved[1])
        gaps_before = len(self.load_ledger(self.network_id, "gaps"))
        rerun = invoke(self.root, self.network_id, ["derive-gaps"])
        self.assertEqual(rerun[0], 0, rerun[2])
        self.assertIn(gap_id, json.loads(rerun[1])["reopen_required_gap_ids"])
        self.assertEqual(len(self.load_ledger(self.network_id, "gaps")), gaps_before)
        reopened = invoke(
            self.root,
            self.network_id,
            [
                "transition-gap",
                "--gap-id", gap_id,
                "--from-record-id", resolved_row["record_id"],
                "--status", "open",
                "--reason", "Coverage requirement remains unmet",
            ],
        )
        self.assertEqual(reopened[0], 0, reopened[2])
        self.assertEqual(invoke(self.root, self.network_id, ["validate"])[0], 0)
        output = self.root / "colon-gap-export.json"
        exported = invoke(
            self.root,
            self.network_id,
            ["export", "--output", str(output)],
        )
        self.assertEqual(exported[0], 0, exported[2])
        export_payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertIn(gap_id, {gap["gap_id"] for gap in export_payload["gaps"]})

    def test_derive_invalid_candidate_is_zero_write(self):
        self.init_network(self.network_id)
        network_dir = self.root / "networks" / self.network_id
        gaps_before = (network_dir / "gaps.jsonl").read_bytes()
        events_before = (network_dir / "events.jsonl").read_bytes()
        original = MODULE._build_derived_gap_payloads
        MODULE._build_derived_gap_payloads = lambda _state, _records: [
            {
                "gap_id": "invalid gap id",
                "gap_type": "deterministic_structural",
                "claim_id": None,
                "impact": "medium",
                "status": "open",
                "description": "Injected invalid candidate",
            }
        ]
        try:
            rejected = invoke(self.root, self.network_id, ["derive-gaps"])
        finally:
            MODULE._build_derived_gap_payloads = original
        self.assertEqual(rejected[0], 1, rejected[2])
        self.assertIn("derive candidate invalid", rejected[2])
        self.assertEqual((network_dir / "gaps.jsonl").read_bytes(), gaps_before)
        self.assertEqual((network_dir / "events.jsonl").read_bytes(), events_before)

    def test_idempotency_and_collision(self):
        self.init_network(self.network_id)
        self.add_source(
            self.network_id, "source-dup", version_hash=f"sha256:{'1' * 64}"
        )
        first = invoke(
            self.root,
            self.network_id,
            [
                "add-source",
                "--source-id", "source-dup",
                "--canonical-identity", "Canonical source-dup",
                "--canonical-version", "v1",
                "--read-version", "read-v1",
                "--read-depth", "full",
                "--version-hash", f"sha256:{'1' * 64}",
                "--role", "source",
            ],
        )
        self.assertEqual(first[0], 0)
        second = invoke(
            self.root,
            self.network_id,
            [
                "add-source",
                "--source-id", "source-dup",
                "--canonical-identity", "Canonical source-dup",
                "--canonical-version", "v1",
                "--read-version", "read-v1",
                "--read-depth", "full",
                "--version-hash", f"sha256:{'2' * 64}",
                "--role", "source",
            ],
        )
        self.assertEqual(second[0], 1)
        state = json.loads(
            (
                self.root / "networks" / self.network_id / "network.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("network_id", state)

    def test_corrupt_ledger_fails_validation(self):
        self.init_network(self.network_id)
        self.add_source(self.network_id, "source-01")
        sources_ledger = self.root / "networks" / self.network_id / "sources.jsonl"
        with sources_ledger.open("a", encoding="utf-8") as handle:
            handle.write("{\"truncated\":")
        code, _, error = invoke(self.root, self.network_id, ["validate"])
        self.assertEqual(code, 1, error)

    def test_snapshot_digest_binding_and_deterministic_export(self):
        self.init_network(self.network_id)
        network_dir = self.root / "networks" / self.network_id
        snapshot = network_dir / "network.json"
        state = json.loads(snapshot.read_text(encoding="utf-8"))
        wrong = {
            "network_id": self.network_id,
            "question": "q",
            "scope": "s",
            "corpus_snapshot_path": state["corpus_snapshot_path"],
            "corpus_snapshot_digest": "sha256:" + "0" * 64,
        }
        snapshot.write_text(json.dumps(wrong), encoding="utf-8")
        # must fail because digest binding changed and schema_version missing
        self.assertEqual(invoke(self.root, self.network_id, ["validate"])[0], 1)

        # build a stable network for deterministic export
        self.init_network("network-deterministic")
        self.add_source(
            "network-deterministic", "s1", version_hash=f"sha256:{'f' * 64}"
        )
        self.add_entity("network-deterministic", "e1")
        self.add_claim("network-deterministic", "claim-export", impact="low")
        code, _, error = self.add_evidence(
            "network-deterministic",
            "claim-export",
            "s1",
            evidence_id="evid-export",
            locator="A1",
        )
        self.assertEqual(code, 0, error)
        out_a = self.root / "export-a.json"
        out_b = self.root / "export-b.json"
        self.assertEqual(
            invoke(
                self.root,
                "network-deterministic",
                ["export", "--output", str(out_a)],
            )[0],
            0,
        )
        self.assertEqual(
            invoke(
                self.root,
                "network-deterministic",
                ["export", "--output", str(out_b)],
            )[0],
            0,
        )
        self.assertEqual(
            out_a.read_text(encoding="utf-8"), out_b.read_text(encoding="utf-8")
        )

    def test_export_satisfies_deep_knowledge_network_contract(self):
        self.init_network(self.network_id, required_dimension=[], required_benchmark=[])
        self.add_source(self.network_id, "source-contract")
        self.add_entity(self.network_id, "entity-contract")
        self.add_claim(
            self.network_id,
            "claim-contract",
            impact="medium",
            entity_id="entity-contract",
        )
        evidence = self.add_evidence(
            self.network_id,
            "claim-contract",
            "source-contract",
            evidence_id="evidence-contract",
            locator="PDF p.4 | Eq. (7)",
        )
        self.assertEqual(evidence[0], 0, evidence[2])
        self.add_claim(self.network_id, "claim-contract-low", impact="low")
        low_evidence = self.add_evidence(
            self.network_id,
            "claim-contract-low",
            "source-contract",
            evidence_id="evidence-contract-low",
            locator="Appendix A",
        )
        self.assertEqual(low_evidence[0], 0, low_evidence[2])
        implicit_gap = invoke(
            self.root,
            self.network_id,
            [
                "record-gap",
                "--gap-id", "gap-contract-implicit-low",
                "--gap-type", "implicit_candidate",
                "--claim-id", "claim-contract-low",
                "--impact", "low",
                "--status", "open",
                "--description", "Candidate benchmark coverage gap",
                "--grounds", "Only one benchmark family is represented",
                "--warrant", "Route robustness may not transfer",
                "--backing", "The reviewed evidence covers one family",
                "--qualifier", "candidate only",
                "--defeaters", "A broader hidden benchmark set may exist",
                "--search-test", "Search for an independent benchmark suite",
            ],
        )
        self.assertEqual(implicit_gap[0], 0, implicit_gap[2])
        derive = invoke(self.root, self.network_id, ["derive-gaps"])
        self.assertEqual(derive[0], 0, derive[2])

        output_path = self.root / "knowledge-network-v1.json"
        exported = invoke(
            self.root,
            self.network_id,
            ["export", "--output", str(output_path)],
        )
        self.assertEqual(exported[0], 0, exported[2])
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "KnowledgeNetwork/v1")
        for ledger in ("sources", "claims", "evidence", "relations", "gaps", "events"):
            self.assertIn(ledger, payload)

        validator = load_deep_validator()
        self.assertEqual(validator.validate_knowledge_network(payload), [])
        priorities = {gap["priority"] for gap in payload["gaps"]}
        self.assertIn("medium", priorities)
        self.assertIn("low", priorities)
        deep_run = load_deep_research_run()
        file_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        loaded, reference = deep_run._load_knowledge_network(
            output_path, file_sha256
        )
        self.assertEqual(loaded["snapshot_id"], payload["snapshot_id"])
        self.assertEqual(reference["sha256"], file_sha256)
        next_actions = deep_run._build_next_actions_from_network(
            loaded, {}, set()
        )
        implicit_action = next(
            action
            for action in next_actions
            if action["gap_id"] == "gap-contract-implicit-low"
        )
        self.assertEqual(implicit_action["action_type"], "search_test")
        self.assertEqual(
            implicit_action["search_test"],
            "Search for an independent benchmark suite",
        )
        self.assertFalse(implicit_action["novelty_claimed"])

        invalid_priority = json.loads(json.dumps(payload))
        invalid_priority["gaps"][0]["priority"] = "important"
        invalid_path = self.root / "knowledge-network-invalid-priority.json"
        invalid_path.write_text(
            json.dumps(invalid_priority, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        invalid_sha256 = hashlib.sha256(invalid_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "priority must be"):
            deep_run._load_knowledge_network(invalid_path, invalid_sha256)
        corrupt_schema = dict(payload)
        corrupt_schema["schema"] = "KnowledgeNetwork/v0"
        self.assertTrue(validator.validate_knowledge_network(corrupt_schema))

        digest_errors: list[str] = []
        validator._validate_file_digest(
            str(output_path), "0" * 64, "knowledge_network_ref", digest_errors
        )
        self.assertTrue(
            any("sha256 mismatch" in error for error in digest_errors),
            digest_errors,
        )

    def test_export_omits_unsupported_claim_and_reports_incomplete_provenance(self):
        self.init_network(self.network_id, required_dimension=[], required_benchmark=[])
        self.add_source(self.network_id, "source-projection")
        self.add_entity(self.network_id, "entity-unsupported")
        self.add_claim(
            self.network_id,
            "claim-unsupported",
            impact="high",
            entity_id="entity-unsupported",
        )
        output_path = self.root / "unsupported-projection.json"
        exported = invoke(
            self.root,
            self.network_id,
            ["export", "--output", str(output_path)],
        )
        self.assertEqual(exported[0], 0, exported[2])
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        node_ids = {node["node_id"] for node in payload["nodes"]}
        self.assertNotIn("claim:claim-unsupported", node_ids)
        self.assertNotIn("entity:entity-unsupported", node_ids)
        self.assertIn(
            "claim:claim-unsupported:missing-evidence",
            payload["projection_omissions"],
        )
        self.assertFalse(
            payload["completion"]["gate_checks"]["provenance_complete"]
        )
        self.assertEqual(payload["completion"]["status"], "partial")
        validator = load_deep_validator()
        self.assertEqual(validator.validate_knowledge_network(payload), [])

    def test_snapshot_binding_rejects_wrong_digest(self):
        snapshot = self.root / "external-snapshot.json"
        snapshot.write_text("{\"items\": []}", encoding="utf-8")
        code, _, error = invoke(
            self.root,
            self.network_id,
            [
                "init",
                "--question", "bad digest",
                "--scope", "local",
                "--snapshot-path", str(snapshot),
                "--snapshot-digest", "sha256:" + "0" * 64,
            ],
        )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
