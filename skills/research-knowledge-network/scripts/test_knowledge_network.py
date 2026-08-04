from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import sys
from pathlib import Path
import unittest

SCRIPT_PATH = Path(__file__).with_name("knowledge_network.py")
SPEC = importlib.util.spec_from_file_location("knowledge_network", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["knowledge_network"] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


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

    def add_source(self, network_id: str, source_id: str = "source-01", version_hash: str | None = None):
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

    def test_happy_path_and_validate(self):
        self.init_network(self.network_id)
        self.add_source(self.network_id, "source-01")
        self.add_entity(self.network_id)
        self.add_claim(self.network_id, "claim-01", impact="medium")
        code, _, error = self.add_evidence(self.network_id, "claim-01", "source-01", evidence_id="evidence-01")
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

    def test_coverage_unmet_blocks_completion(self):
        self.init_network(self.network_id, ["coverage-dim"], ["profile-x"])
        self.add_source(self.network_id, "source-01")
        self.add_entity(self.network_id)
        self.add_claim(self.network_id, "claim-coverage", impact="high")
        invoke(self.root, self.network_id, ["derive-gaps"])
        status = self.parse_status(self.network_id)
        self.assertIn("unmet_coverage", status["completion"]["blockers"])
        self.assertFalse(status["completion"]["can_complete"])
        self.assertIn("claim-coverage", status["coverage"]["missing_dimension_claim_ids"])
        self.assertIn("claim-coverage", status["coverage"]["missing_profile_claim_ids"])

    def test_coverage_check_recognizes_subset_dimensions(self):
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
        invoke(self.root, self.network_id, ["derive-gaps"])
        status = self.parse_status(self.network_id)
        self.assertIn("claim-missing", status["coverage"]["missing_dimension_claim_ids"])
        self.assertNotIn(
            "claim-covered",
            status["coverage"]["missing_dimension_claim_ids"],
        )

    def test_idempotency_and_collision(self):
        self.init_network(self.network_id)
        self.add_source(self.network_id, "source-dup", version_hash=f"sha256:{'1' * 64}")
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
        state = json.loads((self.root / "networks" / self.network_id / "network.json").read_text(encoding="utf-8"))
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
        self.add_source("network-deterministic", "s1", version_hash=f"sha256:{'f' * 64}")
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
        self.assertEqual(invoke(self.root, "network-deterministic", ["export", "--output", str(out_a)])[0], 0)
        self.assertEqual(invoke(self.root, "network-deterministic", ["export", "--output", str(out_b)])[0], 0)
        self.assertEqual(out_a.read_text(encoding="utf-8"), out_b.read_text(encoding="utf-8"))

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
