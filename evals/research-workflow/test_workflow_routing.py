from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location(
    "workflow_routing_under_test", HERE / "workflow_routing.py"
)
assert SPEC is not None and SPEC.loader is not None
WORKFLOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW)


class WorkflowRoutingEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(
            (HERE / "fixtures/release_cases.json").read_text(encoding="utf-8")
        )

    def plan(self, case_id: str) -> dict:
        case = next(item for item in self.fixture["cases"] if item["case_id"] == case_id)
        return copy.deepcopy(case["plan"])

    def step(self, plan: dict, step_id: str) -> dict:
        return next(item for item in plan["steps"] if item["step_id"] == step_id)

    def test_release_cases_pass_and_cover_all_six_skills(self) -> None:
        first = WORKFLOW.evaluate_case_set(copy.deepcopy(self.fixture))
        second = WORKFLOW.evaluate_case_set(copy.deepcopy(self.fixture))
        self.assertEqual(first, second)
        self.assertTrue(first["passed"])
        self.assertEqual(first["case_count"], 7)
        self.assertEqual(set(first["skill_coverage"]), set(WORKFLOW.SKILL_OPERATIONS))

    def test_field_only_rejects_invented_network_state(self) -> None:
        plan = self.plan("field-only-no-network")
        plan["steps"].append(
            {
                "step_id": "invent-network",
                "skill": "research-knowledge-network",
                "operation": "snapshot",
                "execution": "local_readonly",
                "consumes": ["KnowledgeNetwork/v1#invented"],
                "produces": ["NetworkSnapshotRef/v1#invented"],
            }
        )
        with self.assertRaisesRegex(WORKFLOW.ContractError, "must not invent"):
            WORKFLOW.validate_plan(plan)

    def test_existing_corpus_rejects_learning_after_network_ingest(self) -> None:
        plan = self.plan("existing-zotero-corpus")
        learning = plan["steps"].pop(2)
        plan["steps"].insert(4, learning)
        with self.assertRaisesRegex(WORKFLOW.ContractError, "preserve order"):
            WORKFLOW.validate_plan(plan)

    def test_open_world_gap_requires_request_set_handoff(self) -> None:
        plan = self.plan("open-world-gap-to-scholar")
        self.step(plan, "discover-official")["consumes"] = [
            "ScholarDiscoveryRequestSet/v1#wrong-snapshot"
        ]
        with self.assertRaisesRegex(WORKFLOW.ContractError, "must consume"):
            WORKFLOW.validate_plan(plan)

    def test_google_scholar_automatic_execution_is_rejected(self) -> None:
        plan = self.plan("google-scholar-manual-only")
        step = self.step(plan, "manual-scholar-export")
        step["operation"] = "automatic_discovery"
        step["execution"] = "documented_api"
        with self.assertRaisesRegex(WORKFLOW.ContractError, "cannot use an automatic"):
            WORKFLOW.validate_plan(plan)

    def test_new_source_requires_onboarding_and_fresh_snapshot(self) -> None:
        missing = self.plan("new-source-fresh-snapshot")
        missing["steps"] = [
            step for step in missing["steps"] if step["step_id"] != "network-onboard-source"
        ]
        with self.assertRaisesRegex(WORKFLOW.ContractError, "onboard_source"):
            WORKFLOW.validate_plan(missing)

        stale = self.plan("new-source-fresh-snapshot")
        proposal = self.step(stale, "propose-from-new-source")
        proposal["network_ref"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(WORKFLOW.ContractError, "post-onboarding"):
            WORKFLOW.validate_plan(stale)

    def test_decisive_evidence_requires_external_finalization(self) -> None:
        missing_finalize = self.plan("decisive-external-attestation")
        missing_finalize["steps"] = [
            step
            for step in missing_finalize["steps"]
            if step["step_id"] != "finalize-attestations"
        ]
        with self.assertRaisesRegex(WORKFLOW.ContractError, "finalize_attestations"):
            WORKFLOW.validate_plan(missing_finalize)

        same_context = self.plan("decisive-external-attestation")
        attestation = self.step(same_context, "external-attestation")["attestation"]
        attestation["verifier_context_id"] = attestation["producer_context_id"]
        with self.assertRaisesRegex(WORKFLOW.ContractError, "contexts must differ"):
            WORKFLOW.validate_plan(same_context)

    def test_patch_v2_requires_explicit_governance_acceptance(self) -> None:
        plan = self.plan("patch-v2-governance")
        self.step(plan, "apply-governed-patch").pop("governance")
        with self.assertRaisesRegex(WORKFLOW.ContractError, "must be an object"):
            WORKFLOW.validate_plan(plan)

    def test_real_public_contract_probes_pass(self) -> None:
        probes = WORKFLOW.run_public_contract_probes(REPO_ROOT)
        self.assertTrue(all(probes.values()), probes)

    def test_cli_writes_deterministic_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            result = WORKFLOW.main(
                [
                    "evaluate",
                    "--input",
                    str(HERE / "fixtures/release_cases.json"),
                    "--output",
                    str(output),
                    "--repo-root",
                    str(REPO_ROOT),
                ]
            )
            self.assertEqual(result, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertTrue(all(report["public_contract_probes"].values()))


if __name__ == "__main__":
    unittest.main()
