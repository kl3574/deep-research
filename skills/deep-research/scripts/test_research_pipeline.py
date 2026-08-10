import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import sys
from pathlib import Path
from typing import Any

from research_pipeline import (
    ContractError,
    MigrationRequired,
    _binding_digest_universe,
    _owner_bundle_matches_binding_universe,
    compile_topic_requests,
    execution_digest,
    initialize_execution,
    load_appraisal_module,
    load_scholar_module,
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


def write_current_discovery_artifacts(
    directory: Path, discovery_status="complete_bounded"
) -> list[str]:
    scholar = load_scholar_module()

    def write(name: str, value: dict) -> tuple[Path, str]:
        path = directory / name
        raw = (
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    request_set = compile_topic_requests(
        scenario_fixture(), network_fixture(), as_of="2026-08-05T00:00:00Z"
    )
    request_path, request_sha256 = write("topic-request-set.json", request_set)
    authorization = scholar.authorize_request_set(
        request_set,
        reviewer_id="pipeline-execution-reviewer",
        reviewer_role="independent search execution reviewer",
        reviewed_at="2026-08-05T00:01:00Z",
        independent_reviewer_attested=True,
        request_set_file=request_path,
        request_set_file_sha256=request_sha256,
    )
    authorization_path, authorization_sha256 = write(
        "topic-execution-authorization.json", authorization
    )

    def transport(url, timeout):
        del timeout
        if "crossref" in url:
            return b'{"message":{"total-results":0,"items":[]}}'
        return b'{"total":0,"data":[]}'

    result_set = scholar.execute_request_set(
        request_set,
        transport,
        execution_authority=authorization,
        expected_execution_authority_sha256=authorization_sha256,
        execution_authority_file=authorization_path,
        execution_authority_file_sha256=authorization_sha256,
        request_set_file=request_path,
        request_set_file_sha256=request_sha256,
    )
    if discovery_status != "complete_bounded":
        for result in result_set["results"]:
            _set_discovery_result_status(result, discovery_status)
    result_path, _ = write("topic-result-set.json", result_set)
    return [str(request_path), str(authorization_path), str(result_path)]


def load_research_network_publish_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "research-network-publish"
        / "scripts"
        / "render_network_html.py"
    )
    name = "pipeline_research_network_publish_test"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load research-network-publish owner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _seal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    copy_payload = copy.deepcopy(payload)
    copy_payload.pop("content_sha256", None)
    payload_bytes = (
        json.dumps(copy_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    copy_payload["content_sha256"] = hashlib.sha256(payload_bytes).hexdigest()
    return copy_payload


def write_discovery_attempt_artifact(
    directory: Path,
    base_result_set: dict[str, Any],
    *,
    attempt: int,
    supersedes_attempt: int | None,
    discovery_status: str,
) -> Path:
    result_set = copy.deepcopy(base_result_set)
    for result in result_set["results"]:
        _set_discovery_result_status(result, discovery_status)
    attempt_payload = {
        "schema": "ScholarDiscoveryResultSetAttempt/v1",
        "schema_version": "v1",
        "request_set_id": result_set["request_set_id"],
        "request_set_digest": result_set["request_set_digest"],
        "attempt": attempt,
        "result_set": result_set,
    }
    if supersedes_attempt is not None:
        attempt_payload["supersedes_attempt"] = supersedes_attempt
    path = directory / f"topic-attempt-{attempt}.json"
    path.write_text(
        json.dumps(attempt_payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def _set_discovery_result_status(result: dict[str, Any], status: str) -> None:
    result["discovery_status"] = status
    result["stop_reason"] = status
    if status == "complete_bounded":
        return
    events = result.get("search_events", [])
    if status == "partial_budget":
        result["limits"]["candidate_budget_reached"] = True
        return
    if not events:
        raise AssertionError("partial discovery fixture requires a search event")
    event = events[0]
    event["status"] = "blocked" if status == "blocked_capability" else "partial"
    event["search_event"]["truncated"] = status != "blocked_capability"
    event["search_event"]["limitations"] = ["fixture_incomplete_provider"]
    result["provider_failures"] = []
    result["unresolved_query_ids"] = []


def publish_network_fixture() -> dict[str, Any]:
    return _seal_payload(
        {
            "schema": "KnowledgeNetwork/v1",
            "network_id": "doe-surrogate-private",
            "snapshot_id": "doe-surrogate-private-snapshot",
            "sources": [],
            "nodes": [
                {
                    "node_id": "node-001",
                    "kind": "claim",
                    "label": "A synthetic privacy-safe claim",
                    "status": "active",
                    "confidence": "high",
                }
            ],
            "relations": [],
            "gaps": [
                {
                    "gap_id": "gap-001",
                    "reason": "open hypothesis",
                    "priority": "decision_critical",
                    "status": "open",
                    "next_action": "Acquire an authoritative test result.",
                }
            ],
            "completion": {
                "status": "partial",
                "open_gap_ids": ["gap-001"],
            },
        }
    )


def publish_research_map_fixture(snapshot_id: str) -> dict[str, Any]:
    return _seal_payload(
        {
            "schema": "ResearchMap/v1",
            "network_snapshot_id": snapshot_id,
            "title": "Deterministic private publication test map",
            "summary": "Projection summary for publication-owner replay tests.",
            "field_map": [],
            "competency_questions": [],
            "routes": [],
            "recommendations": [],
        }
    )


def write_network_publish_evidence_artifacts(
    directory: Path, *, include_research_map: bool = True
) -> Path:
    publisher = load_research_network_publish_module()
    network = publish_network_fixture()
    network_bytes = (
        json.dumps(network, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    network_path = directory / "publish-network.json"
    network_path.write_bytes(network_bytes)
    network_ref = {
        "path": str(network_path),
        "sha256": hashlib.sha256(network_bytes).hexdigest(),
        "size": len(network_bytes),
        "content_sha256": network["content_sha256"],
        "network_id": network["network_id"],
        "snapshot_id": network["snapshot_id"],
    }

    research_map = publish_research_map_fixture(network["snapshot_id"]) if include_research_map else None
    if research_map is not None:
        research_map_bytes = (
            json.dumps(research_map, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        research_map_path = directory / "publish-map.json"
        research_map_path.write_bytes(research_map_bytes)
        research_map_ref = {
            "path": str(research_map_path),
            "sha256": hashlib.sha256(research_map_bytes).hexdigest(),
            "size": len(research_map_bytes),
            "content_sha256": research_map["content_sha256"],
            "network_snapshot_id": research_map["network_snapshot_id"],
        }
    else:
        research_map_ref = None

    projection = publisher.build_projection(
        network,
        research_map,
        publisher.PUBLIC_MODE,
    )
    rendered = publisher.render_document(projection)
    publisher.assert_output_privacy(rendered, publisher.PUBLIC_MODE)
    publication_bytes = rendered.encode("utf-8")
    publication_path = directory / "publish-publication.html"
    publication_path.write_bytes(publication_bytes)
    publication_ref = {
        "path": str(publication_path),
        "sha256": hashlib.sha256(publication_bytes).hexdigest(),
        "size": len(publication_bytes),
        "rendered_document_sha256": hashlib.sha256(publication_bytes).hexdigest(),
    }
    evidence: dict[str, Any] = {
        "schema": "ResearchNetworkPublishEvidence/v1",
        "schema_version": "v1",
        "mode": publisher.PUBLIC_MODE,
        "generated_at": "2026-08-05T00:00:00Z",
        "network": network_ref,
        "publication_html": publication_ref,
    }
    if research_map_ref is not None:
        evidence["research_map"] = research_map_ref
    evidence_path = directory / "publish-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return evidence_path


def approved_appraisal_artifacts(directory: Path):
    owner = load_appraisal_module()
    fixtures = (
        Path(__file__).resolve().parents[2]
        / "evidence-appraisal"
        / "scripts"
        / "fixtures"
    )
    request = json.loads(
        (fixtures / "minimal_request.json").read_text(encoding="utf-8")
    )
    review = json.loads(
        (fixtures / "minimal_independent_review.json").read_text(encoding="utf-8")
    )
    owner_fixture_path = fixtures / "owner_fixture.py"
    spec = importlib.util.spec_from_file_location(
        "_pipeline_evidence_appraisal_owner_fixture", owner_fixture_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load evidence-appraisal owner fixture")
    owner_fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner_fixture)
    bindings, owner_bundle = owner_fixture.make_anonymous_owner_bundle(
        directory / "appraisal-owner", "pipeline"
    )
    prepared = owner.prepare_appraisal(request, owner_artifact_bindings=bindings)
    review["prepared_request_digest"] = prepared["request_digest"]
    review["prepared_request_file_sha256"] = prepared["prepared_request_file_sha256"]
    review["owner_artifact_binding_digests"] = copy.deepcopy(
        prepared["owner_artifact_binding_digests"]
    )
    passed_owner_attestations = [
        binding
        for binding in bindings
        if binding.get("role") == "attestation" and binding.get("status") == "passed"
    ]
    if not passed_owner_attestations:
        raise RuntimeError("fixture requires a passed owner attestation")
    for relation in review["relation_appraisals"]:
        matching_owner_attestations = [
            binding
            for binding in passed_owner_attestations
            if binding["lineage_id"] in relation["source_lineage"]
        ]
        if not matching_owner_attestations and len(passed_owner_attestations) == 1:
            matching_owner_attestations = passed_owner_attestations
            relation["source_lineage"].append(
                passed_owner_attestations[0]["lineage_id"]
            )
        if len(matching_owner_attestations) != 1:
            raise RuntimeError(
                "fixture relation must select exactly one passed owner attestation lineage"
            )
        owner_attestation_binding = matching_owner_attestations[0]
        for attestation in relation["attestation_refs"]:
            attestation["owner_attestation_binding_digest"] = owner._digest(
                owner_attestation_binding
            )
            attestation["binding_digest"] = owner.compute_attestation_binding_digest(
                prepared,
                relation["claim_ref"],
                relation["evidence_ref"],
                attestation["locator_ref"],
                review["reviewer_context"],
            )
    materialized_relation_refs = {}
    for index, relation in enumerate(review["relation_appraisals"]):
        materialized = owner._materialize_relation(
            relation,
            prepared,
            review["reviewer_context"],
            f"fixture.relation_appraisals[{index}]",
        )
        materialized_relation_refs[
            (materialized["claim_ref"], materialized["evidence_ref"])
        ] = {
            "claim_ref": materialized["claim_ref"],
            "evidence_ref": materialized["evidence_ref"],
            "appraisal_id": materialized["appraisal_id"],
            "semantic_digest": materialized["semantic_digest"],
        }
    for collection_name in ("challenges", "targeted_evidence_needs"):
        for item in review[collection_name]:
            key = (
                item["relation_ref"]["claim_ref"],
                item["relation_ref"]["evidence_ref"],
            )
            item["relation_ref"] = copy.deepcopy(materialized_relation_refs[key])
    review["independent_review_file_sha256"] = owner._digest(
        owner._review_file_projection(review)
    )
    review["independent_review_digest"] = owner._digest(owner._review_semantic(review))
    appraisal_set = owner.finalize_appraisal(prepared, review, owner_bundle)
    approval = owner.create_reviewed_authority(
        prepared,
        review,
        appraisal_set,
        {
            "reviewer_ref": "pipeline-authority",
            "review_method": "independent-approval",
            "reviewed_at": "time-authority",
        },
        owner_bundle,
    )
    package = owner.build_appraisal_package(
        appraisal_set,
        prepared,
        review,
        approval,
        owner_bundle,
        expected_authority_sha256=approval["authority_digest"],
    )
    return [
        package,
        approval,
        prepared,
        review,
        owner_bundle,
        {
            "schema": "EvidenceAppraisalAuthorityExpectation/v1",
            "expected_authority_sha256": approval["authority_digest"],
        },
    ]


def write_appraisal_artifacts(directory: Path) -> list[str]:
    paths = []
    for index, value in enumerate(approved_appraisal_artifacts(directory)):
        path = directory / f"appraisal-{index}.json"
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        paths.append(str(path))
    return paths


class OwnerBundleBindingUniverseTests(unittest.TestCase):
    @staticmethod
    def _bundle(digests: list[str]) -> dict:
        return {
            "schema": "EvidenceAppraisalOwnerBundle/v1",
            "artifacts": [{"binding_digest": digest} for digest in digests],
        }

    def test_reordered_aggregate_owner_bundle_matches_exact_universe(self):
        fixturec = [character * 64 for character in "0123"]
        fixturea = [character * 64 for character in "4567"]
        expected = _binding_digest_universe(fixturec + fixturea)

        self.assertTrue(
            _owner_bundle_matches_binding_universe(
                self._bundle(list(reversed(fixturea)) + list(reversed(fixturec))),
                expected,
            )
        )

    def test_secondary_lineage_missing_or_tampered_never_matches(self):
        fixturec = [character * 64 for character in "0123"]
        fixturea = [character * 64 for character in "4567"]
        expected = _binding_digest_universe(fixturec + fixturea)

        self.assertFalse(
            _owner_bundle_matches_binding_universe(
                self._bundle(fixturec + fixturea[:-1]), expected
            )
        )
        self.assertFalse(
            _owner_bundle_matches_binding_universe(
                self._bundle(fixturec + fixturea[:-1] + ["f" * 64]), expected
            )
        )


def completed_execution_before_publish(directory: Path):
    execution = initialize_execution(scenario_fixture(), as_of="2026-08-05T00:00:00Z")
    generic = directory / "stage.json"
    generic.write_text("{}", encoding="utf-8")
    discovery_artifacts = write_current_discovery_artifacts(directory)
    appraisal_artifacts = write_appraisal_artifacts(directory)
    for stage_id in (
        "zotero_baseline",
        "network_seed",
        "topic_discovery",
        "source_acquisition",
        "source_normalization",
        "paper_understanding",
        "evidence_appraisal",
        "zotero_curation",
        "network_merge",
        "gap_cycle",
    ):
        execution = record_stage(
            execution,
            stage_id=stage_id,
            status="completed",
            artifact_paths=(
                discovery_artifacts
                if stage_id == "topic_discovery"
                else appraisal_artifacts
                if stage_id == "evidence_appraisal"
                else [str(generic)]
            ),
            reason="fixture completed",
            as_of="2026-08-05T00:01:00Z",
        )
    return execution, generic, [Path(path) for path in discovery_artifacts]


def execution_with_topic_discovery_and_source_dependencies(
    directory: Path,
) -> tuple[dict[str, Any], Path, list[Path]]:
    execution = initialize_execution(scenario_fixture(), as_of="2026-08-05T00:00:00Z")
    generic = directory / "topic-generic.json"
    generic.write_text("{}", encoding="utf-8")
    discovery_artifacts = [Path(path) for path in write_current_discovery_artifacts(directory)]
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
            artifact_paths=(
                discovery_artifacts
                if stage_id == "topic_discovery"
                else [str(generic)]
            ),
            reason="topic discovery fixture",
            as_of="2026-08-05T00:01:00Z",
        )
    return execution, generic, discovery_artifacts


def execution_with_evidence_ready_for_gap_cycle(
    directory: Path,
) -> tuple[dict[str, Any], Path, list[str]]:
    execution = initialize_execution(scenario_fixture(), as_of="2026-08-05T00:00:00Z")
    generic = directory / "evidence-generic.json"
    generic.write_text("{}", encoding="utf-8")
    discovery_artifacts = [Path(path) for path in write_current_discovery_artifacts(directory)]
    appraisal_artifacts = write_appraisal_artifacts(directory)
    for stage_id in (
        "zotero_baseline",
        "network_seed",
        "topic_discovery",
        "source_acquisition",
        "source_normalization",
        "paper_understanding",
        "evidence_appraisal",
        "zotero_curation",
        "network_merge",
    ):
        execution = record_stage(
            execution,
            stage_id=stage_id,
            status="completed",
            artifact_paths=(
                discovery_artifacts
                if stage_id == "topic_discovery"
                else appraisal_artifacts
                if stage_id == "evidence_appraisal"
                else [str(generic)]
            ),
            reason="evidence fixture",
            as_of="2026-08-05T00:01:00Z",
        )
    return execution, generic, appraisal_artifacts


def rebind_execution_artifact(execution, path: Path):
    resolved = str(path.resolve())
    raw = path.read_bytes()
    for stage in execution["stages"]:
        for artifact in stage["artifacts"]:
            if artifact["path"] == resolved:
                artifact["sha256"] = hashlib.sha256(raw).hexdigest()
                artifact["size"] = len(raw)
                execution["state_digest"] = execution_digest(execution)
                return
    raise AssertionError(f"missing bound test artifact: {resolved}")


def legacy_execution_fixture(artifact_path):
    execution = initialize_execution(scenario_fixture(), as_of="2026-08-05T00:00:00Z")
    discovery_artifacts = write_current_discovery_artifacts(artifact_path.parent)
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
            artifact_paths=(
                discovery_artifacts
                if stage_id == "topic_discovery"
                else [str(artifact_path)]
            ),
            reason=f"{stage_id} complete",
            as_of="2026-08-05T00:01:00Z",
        )
    legacy = copy.deepcopy(execution)
    legacy["stages"] = [
        stage
        for stage in legacy["stages"]
        if stage["stage_id"] not in {"source_normalization", "evidence_appraisal"}
    ]
    next(
        stage
        for stage in legacy["stages"]
        if stage["stage_id"] == "paper_understanding"
    )["dependencies"] = ["source_acquisition"]
    next(stage for stage in legacy["stages"] if stage["stage_id"] == "network_merge")[
        "dependencies"
    ] = ["paper_understanding"]
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

    def test_topic_discovery_rejects_display_only_v1_result_set(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            generic = directory / "stage.json"
            generic.write_text("{}", encoding="utf-8")
            legacy = directory / "legacy-result.json"
            legacy.write_text(
                json.dumps(discovery_result_set_fixture()), encoding="utf-8"
            )
            for stage_id in ("zotero_baseline", "network_seed"):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=[str(generic)],
                    reason="fixture completed",
                    as_of="2026-08-05T00:01:00Z",
                )
            with self.assertRaisesRegex(ContractError, "ScholarDiscoveryResultSet/v2"):
                record_stage(
                    execution,
                    stage_id="topic_discovery",
                    status="completed",
                    artifact_paths=[str(legacy)],
                    reason="display-only legacy result",
                    as_of="2026-08-05T00:01:00Z",
                )

    def test_topic_discovery_rejects_duplicate_plain_result_set_without_attempt_chain(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            generic = directory / "stage.json"
            generic.write_text("{}", encoding="utf-8")
            discovery_artifacts = [Path(path) for path in write_current_discovery_artifacts(directory)]
            duplicate = directory / "topic-result-set-duplicate.json"
            duplicate.write_text(
                discovery_artifacts[-1].read_text(encoding="utf-8"), encoding="utf-8"
            )
            for stage_id in ("zotero_baseline", "network_seed"):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=[str(generic)],
                    reason="fixture completed",
                    as_of="2026-08-05T00:01:00Z",
                )
            with self.assertRaisesRegex(
                ContractError,
                "multiple result sets for one request_set_id require an explicit "
                "ScholarDiscoveryResultSetAttempt/v1 supersession contract",
            ):
                record_stage(
                    execution,
                    stage_id="topic_discovery",
                    status="completed",
                    artifact_paths=[
                        str(discovery_artifacts[0]),
                        str(discovery_artifacts[1]),
                        str(discovery_artifacts[2]),
                        str(duplicate),
                    ],
                    reason="duplicate plain result set",
                    as_of="2026-08-05T00:01:00Z",
                )

    def test_topic_discovery_rejects_duplicate_attempt_id(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            generic = directory / "stage.json"
            generic.write_text("{}", encoding="utf-8")
            discovery_artifacts = [Path(path) for path in write_current_discovery_artifacts(directory)]
            base_result_set = json.loads(
                discovery_artifacts[-1].read_text(encoding="utf-8")
            )
            attempt_one = write_discovery_attempt_artifact(
                directory,
                base_result_set,
                attempt=1,
                supersedes_attempt=None,
                discovery_status="complete_bounded",
            )
            attempt_duplicate = directory / "topic-attempt-1-duplicate.json"
            attempt_duplicate.write_text(
                attempt_one.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            for stage_id in ("zotero_baseline", "network_seed"):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=[str(generic)],
                    reason="fixture completed",
                    as_of="2026-08-05T00:01:00Z",
                )
            with self.assertRaisesRegex(
                ContractError,
                "ScholarDiscoveryResultSetAttempt/v1 duplicate attempt",
            ):
                record_stage(
                    execution,
                    stage_id="topic_discovery",
                    status="completed",
                    artifact_paths=[
                        str(discovery_artifacts[0]),
                        str(discovery_artifacts[1]),
                        str(attempt_one),
                        str(attempt_duplicate),
                    ],
                    reason="duplicate attempt",
                    as_of="2026-08-05T00:01:00Z",
                )

    def test_topic_discovery_partial_attempts_are_order_invariant(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            generic = directory / "stage.json"
            generic.write_text("{}", encoding="utf-8")
            discovery_artifacts = [Path(path) for path in write_current_discovery_artifacts(directory)]
            base_result_set = json.loads(
                discovery_artifacts[-1].read_text(encoding="utf-8")
            )
            attempt_one = write_discovery_attempt_artifact(
                directory,
                base_result_set,
                attempt=1,
                supersedes_attempt=None,
                discovery_status="complete_bounded",
            )
            attempt_two = write_discovery_attempt_artifact(
                directory,
                base_result_set,
                attempt=2,
                supersedes_attempt=1,
                discovery_status="partial_provider",
            )
            for stage_id in ("zotero_baseline", "network_seed"):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=[str(generic)],
                    reason="fixture completed",
                    as_of="2026-08-05T00:01:00Z",
                )
            for order, paths in {
                "complete_then_partial": (attempt_one, attempt_two),
                "partial_then_complete": (attempt_two, attempt_one),
            }.items():
                with self.subTest(order=order):
                    with self.assertRaisesRegex(
                        ContractError, "record --status partial.*partial_provider"
                    ):
                        record_stage(
                            execution,
                            stage_id="topic_discovery",
                            status="completed",
                            artifact_paths=[
                                str(discovery_artifacts[0]),
                                str(discovery_artifacts[1]),
                                str(paths[0]),
                                str(paths[1]),
                            ],
                            reason="attempt order invariance",
                            as_of="2026-08-05T00:01:00Z",
                        )
                    status = pipeline_status(
                        record_stage(
                            execution,
                            stage_id="topic_discovery",
                            status="partial",
                            artifact_paths=[
                                str(discovery_artifacts[0]),
                                str(discovery_artifacts[1]),
                                str(paths[0]),
                                str(paths[1]),
                            ],
                            reason="attempt order invariance",
                            as_of="2026-08-05T00:01:00Z",
                        )
                    )
                    self.assertEqual(status["partial_stages"], ["topic_discovery"])

    def test_understanding_waits_for_acquisition_and_normalization_state(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "stage.json"
            artifact.write_text("{}", encoding="utf-8")
            discovery_artifacts = write_current_discovery_artifacts(Path(tmp))
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
                    artifact_paths=(
                        discovery_artifacts
                        if stage_id == "topic_discovery"
                        else [str(artifact)]
                    ),
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
            partial_artifacts = write_current_discovery_artifacts(
                Path(tmp), "partial_provider"
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
                    artifact_paths=partial_artifacts,
                    reason="all provider actions terminated",
                    as_of=timestamp,
                )
            execution = record_stage(
                execution,
                stage_id="topic_discovery",
                status="partial",
                artifact_paths=partial_artifacts,
                reason="one provider route remained truncated",
                as_of=timestamp,
            )
            appraisal_artifacts = write_appraisal_artifacts(Path(tmp))
            network_publish_evidence = write_network_publish_evidence_artifacts(
                Path(tmp), include_research_map=True
            )
            for stage_id in (
                "source_acquisition",
                "source_normalization",
                "paper_understanding",
                "evidence_appraisal",
                "zotero_curation",
                "network_merge",
                "gap_cycle",
                "network_publish",
            ):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=(
                        appraisal_artifacts
                        if stage_id == "evidence_appraisal"
                        else [str(network_publish_evidence)]
                        if stage_id == "network_publish"
                        else [str(generic_artifact)]
                    ),
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

    def test_topic_discovery_partial_can_be_reclassified_to_blocked(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            generic = Path(tmp) / "topic-generic.json"
            generic.write_text("{}", encoding="utf-8")
            partial_discovery_artifacts = [
                Path(path)
                for path in write_current_discovery_artifacts(Path(tmp), "partial_provider")
            ]
            for stage_id in ("zotero_baseline", "network_seed"):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=(
                        [str(path) for path in partial_discovery_artifacts]
                        if stage_id == "topic_discovery"
                        else [str(generic)]
                    ),
                    reason="partial discovery fixture",
                    as_of="2026-08-05T00:01:00Z",
                )
            execution = record_stage(
                execution,
                stage_id="topic_discovery",
                status="partial",
                artifact_paths=[str(path) for path in partial_discovery_artifacts],
                reason="partial results after bounded run",
                as_of="2026-08-05T00:02:00Z",
            )
            execution = record_stage(
                execution,
                stage_id="topic_discovery",
                status="blocked",
                artifact_paths=[],
                reason="provider capability limits in this attempt",
                as_of="2026-08-05T00:03:00Z",
            )
            status = pipeline_status(execution)
            self.assertIn("topic_discovery", status["blocked_stages"])
            self.assertNotIn("topic_discovery", status["partial_stages"])

    def test_topic_discovery_partial_artifact_drift_rejected_when_blocking(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            generic = Path(tmp) / "topic-generic.json"
            generic.write_text("{}", encoding="utf-8")
            partial_discovery_artifacts = [
                Path(path)
                for path in write_current_discovery_artifacts(Path(tmp), "partial_provider")
            ]
            for stage_id in ("zotero_baseline", "network_seed"):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=(
                        [str(path) for path in partial_discovery_artifacts]
                        if stage_id == "topic_discovery"
                        else [str(generic)]
                    ),
                    reason="partial discovery fixture",
                    as_of="2026-08-05T00:01:00Z",
                )
            execution = record_stage(
                execution,
                stage_id="topic_discovery",
                status="partial",
                artifact_paths=[str(path) for path in partial_discovery_artifacts],
                reason="partial results after bounded run",
                as_of="2026-08-05T00:02:00Z",
            )
            partial_discovery_artifacts[0].write_text(
                partial_discovery_artifacts[0].read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContractError):
                record_stage(
                    execution,
                    stage_id="topic_discovery",
                    status="blocked",
                    artifact_paths=[],
                    reason="provider capability limits in this attempt",
                    as_of="2026-08-05T00:03:00Z",
                )

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
            migrated = migrate_legacy_execution(legacy, as_of="2026-08-05T00:02:00Z")
            self.assertEqual(
                pipeline_status(migrated)["ready_stages"], ["source_normalization"]
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
        self.assertEqual(len(provenance["verified_artifacts"]), 6)

        self.assertEqual(validate_execution(migrated), migrated)

    def test_migrates_pre_appraisal_execution_without_fabricating_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.json"
            artifact.write_text("{}", encoding="utf-8")
            legacy = legacy_execution_fixture(artifact)
            pre_appraisal = migrate_legacy_execution(
                legacy, as_of="2026-08-05T00:02:00Z"
            )
            migrated = migrate_legacy_execution(
                pre_appraisal, as_of="2026-08-05T00:03:00Z"
            )
            self.assertFalse(pipeline_status(pre_appraisal)["can_publish"])
        by_id = {stage["stage_id"]: stage for stage in migrated["stages"]}
        self.assertEqual(by_id["evidence_appraisal"]["status"], "pending")
        self.assertEqual(by_id["network_merge"]["dependencies"], ["evidence_appraisal"])
        self.assertEqual(
            migrated["migration_provenance"][-1]["schema"],
            "ResearchPipelineMigration/v2",
        )

    def test_terminal_appraisal_rejects_candidate_set_without_authority_replay(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            generic = directory / "generic.json"
            generic.write_text("{}", encoding="utf-8")
            discovery_artifacts = write_current_discovery_artifacts(directory)
            for stage_id in (
                "zotero_baseline",
                "network_seed",
                "topic_discovery",
                "source_acquisition",
                "source_normalization",
                "paper_understanding",
            ):
                execution = record_stage(
                    execution,
                    stage_id=stage_id,
                    status="completed",
                    artifact_paths=(
                        discovery_artifacts
                        if stage_id == "topic_discovery"
                        else [str(generic)]
                    ),
                    reason="fixture completed",
                    as_of="2026-08-05T00:01:00Z",
                )
            candidate = approved_appraisal_artifacts(directory)[0]["appraisal_set"]
            candidate_path = directory / "candidate.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "candidate set alone"):
                record_stage(
                    execution,
                    stage_id="evidence_appraisal",
                    status="completed",
                    artifact_paths=[str(candidate_path)],
                    reason="candidate is not authority",
                    as_of="2026-08-05T00:02:00Z",
                )

    def test_record_stage_replays_completed_topic_discovery_for_any_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            execution, generic, discovery_artifacts = (
                execution_with_topic_discovery_and_source_dependencies(Path(tmp))
            )
            discovery_artifacts[0].write_text(
                discovery_artifacts[0].read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "bound artifact content drifted"):
                record_stage(
                    execution,
                    stage_id="source_normalization",
                    status="completed",
                    artifact_paths=[str(generic)],
                    reason="source normalization depends on topic discovery",
                    as_of="2026-08-05T00:02:00Z",
                )

    def test_record_stage_replays_completed_evidence_appraisal_for_any_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            execution, generic, appraisal_artifacts = (
                execution_with_evidence_ready_for_gap_cycle(Path(tmp))
            )
            output_path = Path(tmp) / "next.json"
            execution_path = Path(tmp) / "execution.json"
            execution_path.write_text(
                json.dumps(execution), encoding="utf-8"
            )
            Path(appraisal_artifacts[0]).write_text(
                Path(appraisal_artifacts[0]).read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = main(
                    [
                        "record-stage",
                        "--execution",
                        str(execution_path),
                        "--stage",
                        "gap_cycle",
                        "--status",
                        "completed",
                        "--artifact",
                        str(generic),
                        "--reason",
                        "gap coverage depends on evidence appraisal",
                        "--as-of",
                        "2026-08-05T00:02:00Z",
                        "--output",
                        str(output_path),
                    ]
                )
            self.assertEqual(status, 2)
            self.assertFalse(output_path.exists())
            self.assertIn(
                "bound artifact content drifted",
                stderr.getvalue(),
            )
            self.assertEqual(
                json.loads(execution_path.read_text(encoding="utf-8")),
                execution,
            )

    def test_record_stage_rejects_duplicate_key_topic_discovery_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            execution = initialize_execution(
                scenario_fixture(), as_of="2026-08-05T00:00:00Z"
            )
            generic = Path(tmp) / "generic.json"
            generic.write_text("{}", encoding="utf-8")
            discovery_artifacts = write_current_discovery_artifacts(Path(tmp))
            execution = record_stage(
                execution,
                stage_id="zotero_baseline",
                status="completed",
                artifact_paths=[str(generic)],
                reason="fixture completed",
                as_of="2026-08-05T00:01:00Z",
            )
            execution = record_stage(
                execution,
                stage_id="network_seed",
                status="completed",
                artifact_paths=[str(generic)],
                reason="fixture completed",
                as_of="2026-08-05T00:01:00Z",
            )
            duplicate_request_set = Path(discovery_artifacts[0])
            duplicate_request_set.write_text(
                """{"schema":"ScholarDiscoveryRequestSet/v1","schema":"ScholarDiscoveryRequestSet/v1","request_set_id":"req-dup"}""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "duplicate JSON key"):
                record_stage(
                    execution,
                    stage_id="topic_discovery",
                    status="completed",
                    artifact_paths=[
                        str(duplicate_request_set),
                        discovery_artifacts[1],
                        discovery_artifacts[2],
                    ],
                    reason="duplicate key in request set",
                    as_of="2026-08-05T00:01:00Z",
                )

    def test_network_publish_rejects_arbitrary_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            execution, generic, discovery_artifacts = (
                completed_execution_before_publish(Path(tmp))
            )
            invalid = Path(tmp) / "invalid.json"
            invalid.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "terminal network_publish requires a validated "
                "ResearchNetworkPublishEvidence/v1 artifact",
            ):
                record_stage(
                    execution,
                    stage_id="network_publish",
                    status="completed",
                    artifact_paths=[str(invalid)],
                    reason="publish with arbitrary JSON",
                    as_of="2026-08-05T00:02:00Z",
                )

    def test_network_publish_rejects_post_record_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            execution, generic, discovery_artifacts = (
                completed_execution_before_publish(Path(tmp))
            )
            evidence_path = write_network_publish_evidence_artifacts(
                Path(tmp), include_research_map=True
            )
            execution = record_stage(
                execution,
                stage_id="network_publish",
                status="completed",
                artifact_paths=[str(evidence_path)],
                reason="publish with owned evidence",
                as_of="2026-08-05T00:02:00Z",
            )
            evidence_path.write_text(
                evidence_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ContractError, "bound artifact content drifted"):
                pipeline_status(execution)

    def test_network_publish_records_valid_owner_replay_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            execution, generic, discovery_artifacts = (
                completed_execution_before_publish(Path(tmp))
            )
            evidence_path = write_network_publish_evidence_artifacts(
                Path(tmp), include_research_map=True
            )
            execution = record_stage(
                execution,
                stage_id="network_publish",
                status="completed",
                artifact_paths=[str(evidence_path)],
                reason="publish owned evidence",
                as_of="2026-08-05T00:02:00Z",
            )
            status = pipeline_status(execution)
            self.assertTrue(status["coverage_complete"])
            self.assertTrue(status["can_finalize_complete"])

    def test_network_publish_status_and_validate_reject_drift(self):
        for target in ("evidence", "network", "html"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                execution, _, discovery_artifacts = (
                    completed_execution_before_publish(Path(tmp))
                )
                evidence_path = write_network_publish_evidence_artifacts(
                    Path(tmp), include_research_map=True
                )
                execution = record_stage(
                    execution,
                    stage_id="network_publish",
                    status="completed",
                    artifact_paths=[str(evidence_path)],
                    reason="publish with owned evidence",
                    as_of="2026-08-05T00:02:00Z",
                )
                evidence = json.loads(
                    evidence_path.read_text(encoding="utf-8")
                )
                network_path = Path(evidence["network"]["path"])
                publication_path = Path(evidence["publication_html"]["path"])
                target_path = (
                    evidence_path
                    if target == "evidence"
                    else network_path
                    if target == "network"
                    else publication_path
                )
                target_path.write_text(
                    target_path.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(ContractError):
                    pipeline_status(execution)
                execution_path = Path(tmp) / "execution.json"
                execution_path.write_text(
                    json.dumps(execution), encoding="utf-8"
                )
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    status = main(["validate", "--input", str(execution_path)])
                self.assertEqual(status, 2)
                self.assertIn("research-pipeline validation failed", stderr.getvalue())

    def test_partial_network_publish_artifact_drift_detected_when_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            execution, _, _ = completed_execution_before_publish(Path(tmp))
            evidence_path = write_network_publish_evidence_artifacts(
                Path(tmp), include_research_map=True
            )
            execution = record_stage(
                execution,
                stage_id="network_publish",
                status="partial",
                artifact_paths=[str(evidence_path)],
                reason="publication attempt completed but provider incomplete",
                as_of="2026-08-05T00:02:00Z",
            )
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            publication_path = Path(evidence["publication_html"]["path"])
            publication_path.write_text(
                publication_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaises(ContractError):
                record_stage(
                    execution,
                    stage_id="network_publish",
                    status="blocked",
                    artifact_paths=[],
                    reason="publication attempt reclassified as blocked",
                    as_of="2026-08-05T00:03:00Z",
                )
            with self.assertRaises(ContractError):
                pipeline_status(execution)
            execution_path = Path(tmp) / "execution.json"
            execution_path.write_text(json.dumps(execution), encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = main(["validate", "--input", str(execution_path)])
            self.assertEqual(status, 2)
            self.assertIn("research-pipeline validation failed", stderr.getvalue())

    def test_blocked_terminal_stage_without_coverage_artifacts_is_not_replayed(self):
        execution = initialize_execution(
            scenario_fixture(), as_of="2026-08-05T00:00:00Z"
        )
        execution = record_stage(
            execution,
            stage_id="network_publish",
            status="blocked",
            artifact_paths=[],
            reason="publish was unavailable in this attempt",
            as_of="2026-08-05T00:01:00Z",
        )
        status = pipeline_status(execution)
        self.assertIn("network_publish", status["blocked_stages"])
        self.assertEqual(status["coverage_complete"], False)
        self.assertFalse(status["complete"])

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
                    with self.assertRaisesRegex(
                        ContractError, "exact pre-normalization"
                    ):
                        migrate_legacy_execution(invalid, as_of="2026-08-05T00:02:00Z")

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
