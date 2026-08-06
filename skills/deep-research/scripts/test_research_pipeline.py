import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from research_pipeline import (
    ContractError,
    MigrationRequired,
    compile_topic_requests,
    execution_digest,
    initialize_execution,
    main,
    migrate_legacy_execution,
    pipeline_status,
    record_stage,
    sha256_json,
    validate_execution,
    validate_scenario,
)


def scenario_fixture():
    return {
        "schema": "ResearchScenario/v1",
        "schema_version": "v1",
        "scenario_id": "doe-surrogate",
        "question": "Which DoE and surrogate routes fit morphology inverse problems?",
        "decision_or_use": "Select an evidence-backed simulator sampling workflow",
        "scope": "Expensive deterministic and noisy morphology simulators",
        "exclusions": ["unverified tutorials"],
        "currentness": "Sources checked through 2026-08-05",
        "risk": "Poor sampling wastes expensive simulations",
        "zotero_target": {
            "group_id": 1234567,
            "library_name": "Example Research Library",
            "collection_key": "COLL0001",
            "collection_path": ["Example", "Research", "DoE"],
        },
        "knowledge_dimensions": [
            "initial_design",
            "surrogate_family",
            "inverse_profile",
        ],
        "google_scholar_policy": "manual_optional",
        "automatic_providers": ["crossref", "semantic_scholar"],
        "topic_needs": [
            {
                "gap_id": "gap-inverse-surrogate",
                "paper_need": "Find adaptive surrogate methods for morphology inverse problems",
                "criteria": {
                    "must": ["inverse problem", "surrogate"],
                    "should": ["adaptive sampling", "morphology"],
                    "must_not": [],
                },
                "query_seeds": [
                    {
                        "objective": "confirm",
                        "query": "inverse problem surrogate adaptive sampling morphology",
                    },
                    {
                        "objective": "refute",
                        "query": "inverse problem surrogate posterior bias failure limitation",
                    },
                ],
            }
        ],
    }


def network_fixture():
    network = {
        "schema": "KnowledgeNetwork/v1",
        "network_id": "doe-surrogate",
        "snapshot_id": "doe-surrogate-s1",
        "sources": [],
        "nodes": [],
        "relations": [],
        "gaps": [],
        "completion": {"status": "partial"},
    }
    network["content_sha256"] = sha256_json(network)
    return network


def discovery_result_set_fixture(discovery_status="complete_bounded"):
    return {
        "schema": "ScholarDiscoveryResultSet/v1",
        "schema_version": "v1",
        "request_set_id": "request-set-" + "a" * 16,
        "request_set_digest": "a" * 64,
        "network_id": "doe-surrogate",
        "network_snapshot_sha256": "b" * 64,
        "network_ref": {
            "network_id": "doe-surrogate",
            "snapshot_id": "doe-surrogate-s1",
            "sha256": "b" * 64,
        },
        "generated_at": "2026-08-05T00:00:00Z",
        "results": [
            {
                "schema": "ScholarDiscoveryResult/v1",
                "request_id": "SDR-GAP-001",
                "request_digest": "c" * 64,
                "plan_digest": "d" * 64,
                "discovery_status": discovery_status,
                "ranked_candidates": [],
                "hypothesis_id": "gap-inverse-surrogate",
                "gap_hypothesis_id": "gap-inverse-surrogate",
            }
        ],
        "failures": [],
        "request_count": 1,
    }


def legacy_execution_fixture(artifact_path):
    execution = initialize_execution(
        scenario_fixture(), as_of="2026-08-05T00:00:00Z"
    )
    for stage_id in (
        "zotero_baseline",
        "network_seed",
        "topic_discovery",
        "source_acquisition",
    ):
        selected_artifact = artifact_path
        if stage_id == "topic_discovery":
            selected_artifact = artifact_path.with_name("topic-discovery.json")
            selected_artifact.write_text(
                json.dumps(discovery_result_set_fixture()), encoding="utf-8"
            )
        execution = record_stage(
            execution,
            stage_id=stage_id,
            status="completed",
            artifact_paths=[str(selected_artifact)],
            reason=f"{stage_id} complete",
            as_of="2026-08-05T00:01:00Z",
        )
    legacy = copy.deepcopy(execution)
    legacy["stages"] = [
        stage
        for stage in legacy["stages"]
        if stage["stage_id"] != "source_normalization"
    ]
    next(
        stage
        for stage in legacy["stages"]
        if stage["stage_id"] == "paper_understanding"
    )["dependencies"] = ["source_acquisition"]
    legacy.pop("migration_provenance")
    legacy["state_digest"] = execution_digest(legacy)
    return legacy


class ResearchPipelineTests(unittest.TestCase):
    def test_initializes_ordered_resumable_stages(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        status = pipeline_status(execution)
        self.assertEqual(status["ready_stages"], ["zotero_baseline"])
        self.assertEqual(status["completed_stage_count"], 0)
        self.assertFalse(status["can_publish"])

    def test_compile_topic_uses_domain_terms_not_structural_field_names(self):
        request_set = compile_topic_requests(
            scenario_fixture(),
            network_fixture(),
            as_of="2026-08-05T00:00:00Z",
        )
        self.assertEqual(request_set["schema"], "ScholarDiscoveryRequestSet/v1")
        payload = json.dumps(request_set).lower()
        self.assertIn("inverse problem", payload)
        self.assertIn("surrogate", payload)
        self.assertNotIn("network dimension", payload)
        self.assertNotIn("validation_target", payload)

    def test_stage_completion_binds_artifact_and_enforces_dependencies(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "snapshot.json"
            artifact.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "incomplete dependencies"):
                record_stage(
                    execution,
                    stage_id="network_seed",
                    status="completed",
                    artifact_paths=[str(artifact)],
                    reason=None,
                    as_of="2026-08-05T00:01:00Z",
                )
            updated = record_stage(
                execution,
                stage_id="zotero_baseline",
                status="completed",
                artifact_paths=[str(artifact)],
                reason="exact target read back",
                as_of="2026-08-05T00:01:00Z",
            )
        status = pipeline_status(updated)
        self.assertIn("network_seed", status["ready_stages"])
        bound = updated["stages"][0]["artifacts"][0]
        self.assertEqual(bound["size"], 2)
        self.assertEqual(len(bound["sha256"]), 64)

    def test_understanding_waits_for_acquisition_and_normalization_state(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "stage.json"
            artifact.write_text("{}", encoding="utf-8")
            discovery_artifact = Path(tmp) / "topic-discovery.json"
            discovery_artifact.write_text(
                json.dumps(discovery_result_set_fixture()), encoding="utf-8"
            )
            timestamp = "2026-08-05T00:01:00Z"
            for stage_id in (
                "zotero_baseline",
                "network_seed",
                "topic_discovery",
                "source_acquisition",
            ):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=[
                        str(discovery_artifact)
                        if stage_id == "topic_discovery"
                        else str(artifact)
                    ],
                    reason="fixture completed",
                    as_of=timestamp,
                )
            self.assertEqual(
                pipeline_status(execution)["ready_stages"], ["source_normalization"]
            )
            with self.assertRaisesRegex(ContractError, "source_normalization"):
                record_stage(
                    execution,
                    stage_id="paper_understanding",
                    status="completed",
                    artifact_paths=[str(artifact)],
                    reason=None,
                    as_of=timestamp,
                )
            skip = Path(tmp) / "source-normalization-skip.json"
            skip.write_text(
                json.dumps(
                    {
                        "schema": "ScholarlyDocumentQuality/v1",
                        "classification": "native_ok",
                        "normalization_recommended": False,
                    }
                ),
                encoding="utf-8",
            )
            execution = record_stage(
                execution,
                stage_id="source_normalization",
                status="completed",
                artifact_paths=[str(skip)],
                reason="all raw sources classified native_ok; explicit skip",
                as_of=timestamp,
            )
        self.assertIn("paper_understanding", pipeline_status(execution)["ready_stages"])

    def test_partial_discovery_is_terminal_but_does_not_claim_full_coverage(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            generic_artifact = Path(tmp) / "stage.json"
            generic_artifact.write_text("{}", encoding="utf-8")
            partial_artifact = Path(tmp) / "topic-discovery-partial.json"
            partial_artifact.write_text(
                json.dumps(discovery_result_set_fixture("partial_provider")),
                encoding="utf-8",
            )
            timestamp = "2026-08-05T00:01:00Z"
            for stage_id in ("zotero_baseline", "network_seed"):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=[str(generic_artifact)],
                    reason="fixture completed",
                    as_of=timestamp,
                )
            with self.assertRaisesRegex(
                ContractError, "record --status partial.*partial_provider"
            ):
                record_stage(
                    execution,
                    stage_id="topic_discovery",
                    status="completed",
                    artifact_paths=[str(partial_artifact)],
                    reason="all provider actions terminated",
                    as_of=timestamp,
                )
            execution = record_stage(
                execution,
                stage_id="topic_discovery",
                status="partial",
                artifact_paths=[str(partial_artifact)],
                reason="one provider route remained truncated",
                as_of=timestamp,
            )
            for stage_id in (
                "source_acquisition",
                "source_normalization",
                "paper_understanding",
                "zotero_curation",
                "network_merge",
                "gap_cycle",
                "network_publish",
            ):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=[str(generic_artifact)],
                    reason="bounded downstream work completed",
                    as_of=timestamp,
                )

        status = pipeline_status(execution)
        self.assertEqual(status["partial_stages"], ["topic_discovery"])
        self.assertEqual(status["terminal_stage_count"], len(execution["stages"]))
        self.assertTrue(status["stage_actions_terminal"])
        self.assertFalse(status["coverage_complete"])
        self.assertFalse(status["can_finalize_complete"])
        self.assertTrue(status["can_finalize_partial"])
        self.assertEqual(status["outcome"], "partial")
        self.assertFalse(status["complete"])

    def test_scenario_rejects_credential_fields_and_structural_gap_ids(self):
        secret = scenario_fixture()
        secret["api_key"] = "must-not-enter-state"
        with self.assertRaisesRegex(ContractError, "forbidden credential"):
            validate_scenario(secret)

        structural = copy.deepcopy(scenario_fixture())
        structural["topic_needs"][0]["gap_id"] = (
            "derived:missing-dimension:validation_target"
        )
        with self.assertRaisesRegex(ContractError, "semantic topic"):
            validate_scenario(structural)

    def test_legacy_validate_returns_machine_readable_migration_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.json"
            artifact.write_text("{}", encoding="utf-8")
            legacy = legacy_execution_fixture(artifact)
            legacy_path = Path(tmp) / "legacy.json"
            legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = main(["validate", "--input", str(legacy_path)])
        diagnostic = json.loads(stderr.getvalue())
        self.assertEqual(status, 2)
        self.assertEqual(diagnostic["code"], "migration_required")
        self.assertEqual(diagnostic["legacy_state_digest"], legacy["state_digest"])

    def test_migrates_four_completed_legacy_without_changing_stage_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.json"
            artifact.write_text("{}", encoding="utf-8")
            legacy = legacy_execution_fixture(artifact)
            migrated = migrate_legacy_execution(
                legacy, as_of="2026-08-05T00:02:00Z"
            )
        by_id = {stage["stage_id"]: stage for stage in migrated["stages"]}
        for old_stage in legacy["stages"]:
            current = by_id[old_stage["stage_id"]]
            self.assertEqual(current["status"], old_stage["status"])
            self.assertEqual(current["artifacts"], old_stage["artifacts"])
        normalization = by_id["source_normalization"]
        self.assertEqual(normalization["status"], "pending")
        self.assertEqual(normalization["reason"], "normalization evidence required")
        self.assertEqual(
            by_id["paper_understanding"]["dependencies"],
            ["source_acquisition", "source_normalization"],
        )
        provenance = migrated["migration_provenance"][0]
        self.assertEqual(provenance["source_state_digest"], legacy["state_digest"])
        self.assertEqual(len(provenance["verified_artifacts"]), 4)
        self.assertEqual(pipeline_status(migrated)["ready_stages"], ["source_normalization"])
        self.assertEqual(validate_execution(migrated), migrated)

    def test_migration_rejects_unknown_or_out_of_order_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.json"
            artifact.write_text("{}", encoding="utf-8")
            legacy = legacy_execution_fixture(artifact)
            for mutation in ("unknown", "out_of_order"):
                invalid = copy.deepcopy(legacy)
                if mutation == "unknown":
                    invalid["stages"][0]["stage_id"] = "unknown_stage"
                else:
                    invalid["stages"][0], invalid["stages"][1] = (
                        invalid["stages"][1],
                        invalid["stages"][0],
                    )
                invalid["state_digest"] = execution_digest(invalid)
                with self.subTest(mutation=mutation):
                    with self.assertRaisesRegex(ContractError, "exact pre-normalization"):
                        migrate_legacy_execution(
                            invalid, as_of="2026-08-05T00:02:00Z"
                        )

    def test_record_stage_never_silently_migrates_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.json"
            artifact.write_text("{}", encoding="utf-8")
            legacy = legacy_execution_fixture(artifact)
            with self.assertRaises(MigrationRequired):
                record_stage(
                    legacy,
                    stage_id="paper_understanding",
                    status="blocked",
                    artifact_paths=[],
                    reason="must migrate first",
                    as_of="2026-08-05T00:02:00Z",
                )


if __name__ == "__main__":
    unittest.main()
