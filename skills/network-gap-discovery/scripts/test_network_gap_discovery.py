import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

import network_gap_discovery as discovery
from network_gap_discovery import (
    ACTION_FOR_TARGET_KIND,
    ContractError,
    PAPER_UNDERSTANDING_GAP_TO_PROJECTION,
    REVIEWED_GAP_SELECTION_SCHEMA,
    REVIEWED_GAP_SELECTION_V2_SCHEMA,
    TARGET_KINDS,
    canonical_paper_understanding_gap_digest,
    consume_reviewed_evidence,
    consume_reviewed_evidence_collection,
    consume_results as _consume_results,
    emit_search_requests as _emit_search_requests,
    generate_hypotheses_from_probe,
    sha256_json,
    network_ref,
    prioritize,
    propose_patch,
    propose_patch_v3,
    propose_patch_v4,
    scan_network,
    select_hypotheses,
    selected_hypotheses_for_emission,
    validate_hypotheses,
    validate_paper_reading_report_set,
    validate_paper_reading_report_set_v2,
    validate_paper_understanding_gap,
    validate_patch_v1 as validate_patch,
    validate_patch_v2,
    validate_patch_v3,
    validate_patch_v4,
    validate_request_set,
)


LEARN_SCRIPTS = Path(__file__).resolve().parents[2] / "learn-from-papers" / "scripts"


def _load_learn_module(name):
    path = LEARN_SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"network_test_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE_BUNDLE_MODULE = _load_learn_module("paper_source_bundle")
READING_DOSSIER_MODULE = _load_learn_module("paper_reading_dossier")
READING_COLLECTION_MODULE = _load_learn_module("paper_reading_evidence_collection")


def emit_search_requests(value, network=None, **kwargs):
    """Migrate legacy producer fixtures through the reviewed selection gate."""
    if value.get("reviewed_selection_ref") is not None:
        return _emit_search_requests(value, network, **kwargs)
    try:
        selected = selected_hypotheses_for_emission(value)
    except ContractError:
        return _emit_search_requests(value, network, **kwargs)

    unscheduled = copy.deepcopy(value)
    unscheduled.pop("priority_order", None)
    unscheduled.pop("selection_summary", None)
    for hypothesis in unscheduled["hypotheses"]:
        hypothesis["status"] = "proposed"
    prioritized = prioritize(unscheduled, network)
    selected_ids = [hypothesis["hypothesis_id"] for hypothesis in selected]
    selection = {
        "schema": REVIEWED_GAP_SELECTION_SCHEMA,
        "input_ref": {
            "schema": "KnowledgeGapHypotheses/v1",
            "sha256": sha256_json(prioritized),
        },
        "network_ref": copy.deepcopy(prioritized["network_ref"]),
        "round_id": prioritized["round_id"],
        "selected_hypothesis_ids": selected_ids,
        "review_status": "approved",
    }
    selected_document = select_hypotheses(prioritized, selection, network)
    value.clear()
    value.update(selected_document)
    return _emit_search_requests(value, network, **kwargs)


def _artifact_file_sha256(value):
    artifact_path, artifact_sha256 = _artifact_file(value)
    artifact_path.unlink()
    return artifact_sha256


def _artifact_file(value):
    raw = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    with tempfile.NamedTemporaryFile("wb", delete=False) as temporary:
        temporary.write(raw)
        artifact_path = Path(temporary.name)
    artifact_path.chmod(0o600)
    return artifact_path, hashlib.sha256(artifact_path.read_bytes()).hexdigest()


def _write_named_artifact(root, name, value):
    path = root / name
    raw = discovery.canonical_bytes(value) + b"\n"
    path.write_bytes(raw)
    path.chmod(0o600)
    return path, hashlib.sha256(raw).hexdigest()


def _consumable_hypothesis_projection(hypothesis):
    subject = hypothesis["claim_subject"]
    return {
        "hypothesis_id": hypothesis["hypothesis_id"],
        "input_status": hypothesis["status"],
        "epistemic_task_sha256": sha256_json(
            discovery._epistemic_task_from_hypothesis(hypothesis)
        ),
        "subject_ref": {
            "subject_id": subject["subject_id"],
            "subject_digest": subject["subject_digest"],
        },
        "origin_gap_refs": copy.deepcopy(subject["origin_gap_refs"]),
    }


def _review_request_projection(review_set):
    return [
        {
            "request_id": request["request_id"],
            "request_content_sha256": sha256_json(request),
            "hypothesis_id": request["hypothesis_id"],
            "epistemic_task_sha256": sha256_json(request["epistemic_task"]),
            "sources": [
                {
                    "source_id": source["source_id"],
                    "source_digest": source["source_digest"],
                    "source_content_sha256": sha256_json(source),
                }
                for source in request["sources"]
            ],
        }
        for request in review_set["requests"]
    ]


def _collection_group_authority_projection(collection):
    return [
        {
            "reading_group_id": group["reading_group_id"],
            "reading_group_digest": group["reading_group_digest"],
            "source_id": group["source_ref"]["source_id"],
            "source_digest": group["source_ref"]["source_digest"],
            "source_artifact_sha256": group["refs"]["source_artifact"]["sha256"],
            "report_set_id": group["report_set_ref"]["report_set_id"],
            "report_set_digest": group["report_set_ref"]["report_set_digest"],
        }
        for group in collection["reading_groups"]
    ]


def _collection_reviewer_context():
    return {
        "reviewer_id": "collection-consumption-reviewer-1",
        "reviewer_role": "independent collection-consumption reviewer",
        "reviewer_context_id": "independent-collection-review-context-1",
        "reviewed_at": "2026-08-05T00:25:00Z",
        "independent_from_bound_artifact_producers": True,
    }


def reviewed_collection_consumption_artifacts(root, fixture):
    preconsumption = fixture["selected"]
    hypotheses_path, hypotheses_raw_sha = _write_named_artifact(
        root, "preconsumption-hypotheses.json", preconsumption
    )
    review_requests_path, review_requests_raw_sha = _write_named_artifact(
        root, "learn-from-papers-request-set.json", fixture["review_set"]
    )
    collection_path, collection_raw_sha = _write_named_artifact(
        root, "reading-collection.json", fixture["collection"]
    )
    expected_hypotheses_binding = {
        "schema": "KnowledgeGapHypotheses/v1",
        "raw_file_sha256": hypotheses_raw_sha,
        "canonical_sha256": sha256_json(preconsumption),
        "consumable_hypotheses": [
            _consumable_hypothesis_projection(hypothesis)
            for hypothesis in preconsumption["hypotheses"]
            if hypothesis["status"] == "selected"
        ],
        "selection_summary": copy.deepcopy(preconsumption["selection_summary"]),
        "reviewed_selection_ref": copy.deepcopy(
            preconsumption["reviewed_selection_ref"]
        ),
    }
    authority = discovery.create_reviewed_collection_consumption_authority(
        hypotheses_path,
        fixture["network"],
        review_requests_path,
        collection_path,
        consumed_at="2026-08-05T00:30:00Z",
        reviewer_context=_collection_reviewer_context(),
    )
    self_binding = authority["hypotheses_binding"]
    if self_binding != expected_hypotheses_binding:
        raise AssertionError("authority hypotheses binding changed the reviewed input")
    expected_request_binding = {
        "schema": "LearnFromPapersRequestSet/v1",
        "raw_file_sha256": review_requests_raw_sha,
        "canonical_sha256": sha256_json(fixture["review_set"]),
        "request_set_id": fixture["review_set"]["request_set_id"],
        "request_set_digest": fixture["review_set"]["request_set_digest"],
        "requests": _review_request_projection(fixture["review_set"]),
    }
    if "source_discovery_set_id" in fixture["review_set"]:
        raise AssertionError("direct fixture must not invent a discovery-set anchor")
    if "source_discovery_ref" in authority["review_request_set_binding"]:
        raise AssertionError("direct authority must not invent source_discovery_ref")
    if authority["review_request_set_binding"] != expected_request_binding:
        raise AssertionError("authority request binding changed the exact LFR set")
    expected_collection_binding = {
        "schema": "PaperReadingEvidenceCollection/v1",
        "raw_file_sha256": collection_raw_sha,
        "canonical_sha256": sha256_json(fixture["collection"]),
        "collection_id": fixture["collection"]["collection_id"],
        "collection_digest": fixture["collection"]["collection_digest"],
        "reading_groups": _collection_group_authority_projection(fixture["collection"]),
    }
    if authority["reading_collection_binding"] != expected_collection_binding:
        raise AssertionError("authority collection binding changed the exact groups")
    if authority["route"] != "direct_reviewed_selection":
        raise AssertionError("authority route must remain direct_reviewed_selection")
    if authority["network_ref"] != network_ref(fixture["network"]):
        raise AssertionError("authority network ref changed")
    if authority["consumed_at"] != "2026-08-05T00:30:00Z":
        raise AssertionError("authority consumed_at changed")
    if authority["round_id"] != preconsumption["round_id"]:
        raise AssertionError("authority round_id changed")
    if authority["expected_consumed_hypotheses_sha256"] == sha256_json(preconsumption):
        raise AssertionError("authority expected output must not equal selected input")
    if not authority["producer_context_ids"]:
        raise AssertionError("fixture authority must bind live producer contexts")
    if (
        authority["reviewer_context"]["reviewer_context_id"]
        in authority["producer_context_ids"]
    ):
        raise AssertionError("fixture reviewer context collides with a producer")
    authority_path, authority_raw_sha = _write_named_artifact(
        root, "collection-consumption-authority.json", authority
    )
    return {
        "preconsumption": preconsumption,
        "hypotheses_path": hypotheses_path,
        "review_requests_path": review_requests_path,
        "collection_path": collection_path,
        "authority": authority,
        "authority_path": authority_path,
        "authority_raw_sha": authority_raw_sha,
    }


def _request_set_file_sha256(request_set):
    request_set_file, request_set_file_sha256 = _request_set_file_artifact(request_set)
    request_set_file.unlink()
    return request_set_file_sha256


def _request_set_file_artifact(request_set):
    raw = (
        json.dumps(
            request_set,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    with tempfile.NamedTemporaryFile("wb", delete=False) as temporary:
        temporary.write(raw)
        request_set_path = Path(temporary.name)
    request_set_path.chmod(0o600)
    return request_set_path, hashlib.sha256(request_set_path.read_bytes()).hexdigest()


def attach_network_content_sha256(network):
    network["content_sha256"] = sha256_json(
        {key: value for key, value in network.items() if key != "content_sha256"}
    )
    return network


def paper_understanding_gap_fixture(gap_type="missing_input_format"):
    missing_fields = {
        "missing_input_format": "workflow.graph.nodes[0].format",
        "missing_data_flow": "workflow.data_flow[0]",
        "missing_derivation_step": "mathematical_principles.derivation_steps[0]",
        "missing_algorithm_detail": "algorithmic_principles.ordered_steps[0]",
        "missing_applicability_boundary": "applicability.does_not_apply_when[0]",
        "missing_conclusion_scope": "conclusion.statement",
    }
    payload_digest = "d" * 64
    gap = {
        "schema": "PaperUnderstandingGap/v1",
        "gap_id": "",
        "gap_digest": "",
        "gap_type": gap_type,
        "projection_type": PAPER_UNDERSTANDING_GAP_TO_PROJECTION[gap_type],
        "missing_field": missing_fields[gap_type],
        "question": f"Which source passage resolves {gap_type}?",
        "search_terms": {
            "must": ["system identification"],
            "should": ["primary source"],
            "must_not": ["unrelated acronym"],
        },
        "provenance": {
            "understanding_binding": {
                "understanding_id": "paper-understanding-aaaaaaaaaaaaaaaa",
                "understanding_digest": "a" * 64,
                "validation_record_id": "paper-understanding-validation-bbbbbbbbbbbbbbbb",
                "validation_record_digest": "b" * 64,
            },
            "projection_ref": {
                "schema": "UnderstandingNetworkProjection/v1",
                "projection_id": "understanding-projection-cccccccccccccccc",
                "projection_digest": "c" * 64,
                "projection_type": PAPER_UNDERSTANDING_GAP_TO_PROJECTION[gap_type],
                "payload_digest": payload_digest,
            },
            "basis_refs": [
                {
                    "ref_type": "understanding_projection_path",
                    "projection_type": PAPER_UNDERSTANDING_GAP_TO_PROJECTION[gap_type],
                    "source_path": missing_fields[gap_type],
                    "payload_digest": payload_digest,
                }
            ],
        },
        "novelty_claimed": False,
    }
    gap["gap_digest"] = canonical_paper_understanding_gap_digest(gap)
    gap["gap_id"] = f"understanding-gap-{gap['gap_digest'][:16]}"
    return gap


def network_fixture():
    network = {
        "schema": "KnowledgeNetwork/v1",
        "network_id": "KN-1",
        "snapshot_id": "KN-1-S1",
        "sources": [{"source_id": "SRC-1"}],
        "nodes": [
            {"node_id": "entity:A", "kind": "entity", "label": "A"},
            {"node_id": "entity:B", "kind": "entity", "label": "B"},
            {"node_id": "entity:C", "kind": "entity", "label": "C"},
        ],
        "relations": [
            {
                "relation_id": "REL-AB",
                "from_id": "entity:A",
                "to_id": "entity:B",
                "predicate": "associated_with",
                "status": "supported",
                "confidence": "high",
                "provenance": [{"source_id": "source:1", "locator": "p.1"}],
            }
        ],
        "gaps": [{"gap_id": "GAP-EXPLICIT", "status": "open", "reason": "benchmark"}],
        "completion": {
            "status": "partial",
            "open_gap_ids": ["GAP-EXPLICIT"],
            "gate_checks": {"corpus_snapshotted": True, "conflicts_terminal": False},
        },
    }
    return attach_network_content_sha256(network)


def semantic_gap_network_fixture():
    network = network_fixture()
    network["nodes"].append(
        {
            "node_id": "entity:Wendy",
            "kind": "entity",
            "label": "Wendy benchmark object",
        }
    )
    network["gaps"] = [
        {
            "gap_id": "GAP-SPARSE",
            "status": "open",
            "reason": "Sparse coverage on cross-benchmark evidence in sparse graphs",
        },
        {
            "gap_id": "GAP-WENDY",
            "status": "open",
            "reason": "wendy benchmark scope update",
        },
    ]
    return attach_network_content_sha256(network)


def doe_surrogate_noise_network_fixture(single_source_count=96, isolate_count=24):
    nodes = [{"node_id": "source:DOE", "kind": "source", "label": "DoE corpus"}]
    relations = []
    gaps = [
        {
            "gap_id": "gap:morphology_specific_benchmark",
            "gap_type": "explicit",
            "status": "open",
            "impact": "high",
            "declared_priority": "P0",
            "description": "Cross-route morphology benchmark under one simulator budget",
        },
        {
            "gap_id": "gap:stopping_and_calibration",
            "gap_type": "explicit",
            "status": "open",
            "impact": "high",
            "declared_priority": "P0",
            "description": "Executable stopping and uncertainty calibration certificate",
        },
        {
            "gap_id": "gap:batch_pending_failures",
            "gap_type": "explicit",
            "status": "open",
            "impact": "medium",
            "declared_priority": "P1",
            "description": "Batch pending and simulator failure handling",
        },
    ]
    for index in range(single_source_count):
        claim_id = f"DOE-{index:03d}"
        node_id = f"claim:{claim_id}"
        nodes.append(
            {
                "node_id": node_id,
                "kind": "claim",
                "label": f"DoE reviewed claim {index:03d}",
            }
        )
        relations.append(
            {
                "relation_id": f"REL-DOE-{index:03d}",
                "from_id": node_id,
                "to_id": "source:DOE",
                "predicate": "supports",
                "status": "supported",
                "confidence": "high",
                "provenance": [{"source_id": "SRC-DOE", "locator": f"p.{index + 1}"}],
            }
        )
        gaps.append(
            {
                "gap_id": f"derived:single-source:{claim_id}",
                "gap_type": "deterministic_structural",
                "status": "open",
                "impact": "medium",
                "claim_id": claim_id,
                "derivation_rule": "single_independent_source",
                "description": f"Claim {claim_id} has one independent source stream",
            }
        )
    for index in range(isolate_count):
        nodes.append(
            {
                "node_id": f"claim:ISOLATE-{index:03d}",
                "kind": "claim",
                "label": f"Unconnected DoE boundary {index:03d}",
            }
        )
    network = {
        "schema": "KnowledgeNetwork/v1",
        "network_id": "DOE-NOISE",
        "snapshot_id": "DOE-NOISE-S1",
        "sources": [{"source_id": "SRC-DOE"}],
        "nodes": nodes,
        "relations": relations,
        "gaps": gaps,
        "completion": {
            "status": "partial",
            "open_gap_ids": [gap["gap_id"] for gap in gaps],
            "gate_checks": {"corpus_snapshotted": True},
        },
    }
    return attach_network_content_sha256(network)


def hypotheses_fixture(network=None):
    network = network or network_fixture()
    return {
        "schema": "KnowledgeGapHypotheses/v1",
        "network_ref": network_ref(network),
        "round_id": "ROUND-1",
        "generated_at": "2026-08-05T00:00:00Z",
        "method_families": ["abc_bridge", "counterevidence_boundary"],
        "selection_summary": {
            "selected_count": 1,
            "selected_hypothesis_ids": ["KGH-1"],
            "unselected_proposed_hypothesis_ids": [],
        },
        "hypotheses": [
            {
                "hypothesis_id": "KGH-1",
                "gap_type": "implicit_candidate",
                "target_kind": "relation",
                "target_signature": "entity:A ? entity:C",
                "scope_and_time_bounds": "test scope through 2026",
                "hypothesis": "A relation between A and C may be missing",
                "grounds": [{"ref_id": "REL-AB", "statement": "A-B is reviewed"}],
                "warrant": "A compatible B-C path motivates an A-C test",
                "backing": [{"ref_id": "network:KN-1", "locator": "REL-AB"}],
                "qualifier": "possible only",
                "defeaters": ["C is an alias", "direct A-C study exists"],
                "search_test": {
                    "queries": [
                        {"objective": "confirm", "query": "A C relation"},
                        {"objective": "refute", "query": "A C null failure"},
                    ],
                    "route_families": [
                        "openalex",
                        "semantic_scholar",
                        "google_scholar",
                    ],
                    "expected_confirming_observation": "direct primary study",
                    "expected_disconfirming_observation": "direct null or covered node",
                    "acceptance_criteria": "independent full-text evidence",
                    "criteria": {"must": ["A", "C"], "should": [], "must_not": []},
                    "metadata_filters": {"languages": ["en"]},
                    "seeds": {},
                },
                "expected_information_gain": "changes route selection",
                "decision_impact": "high",
                "uncertainty": "high",
                "searchability": "medium",
                "cross_branch_blocking": True,
                "dependencies": [],
                "status": "selected",
                "status_basis": [],
                "novelty_claimed": False,
                "next_action": "scholar_discovery",
            }
        ],
    }


def make_result(
    request_id: str,
    ranked_candidates,
    request_digest: str = "f" * 64,
    hypothesis_id: str = "KGH-1",
):
    return {
        "schema": "ScholarDiscoveryResult/v1",
        "request_id": request_id,
        "request_digest": request_digest,
        "hypothesis_id": hypothesis_id,
        "as_of": "2026-08-05T01:00:00Z",
        "discovery_status": "complete_bounded",
        "ranked_candidates": ranked_candidates,
    }


def make_result_set(
    request_set,
    request,
    ranked_candidates,
    request_digest: str = "f" * 64,
    hypothesis_id: str = "KGH-1",
    discovery_status: str = "complete_bounded",
):
    scholar = discovery._scholar_discovery_module()
    try:
        request_set_file, request_set_file_sha = _request_set_file_artifact(request_set)
        try:
            authorization = scholar.authorize_request_set(
                request_set,
                reviewer_id="network-test-execution-reviewer",
                reviewer_role="independent execution reviewer",
                reviewed_at="2026-08-05T00:30:00Z",
                independent_reviewer_attested=True,
                request_set_file=request_set_file,
                request_set_file_sha256=request_set_file_sha,
            )
            authorization_file_path, authorization_file_sha256 = _artifact_file(
                authorization
            )

            def transport(url, timeout):
                del timeout
                if "crossref" in url:
                    return b'{"message":{"total-results":0,"items":[]}}'
                if "openalex" in url:
                    return b'{"meta":{"count":0},"results":[]}'
                return b'{"total":0,"data":[]}'

            try:
                result_set = scholar.execute_request_set(
                    request_set,
                    transport,
                    execution_authority=authorization,
                    expected_execution_authority_sha256=authorization_file_sha256,
                    execution_authority_file=authorization_file_path,
                    execution_authority_file_sha256=authorization_file_sha256,
                    request_set_file=request_set_file,
                    request_set_file_sha256=request_set_file_sha,
                )
            finally:
                authorization_file_path.unlink()
        finally:
            request_set_file.unlink()
    except ValueError:
        # Mismatch tests need a shape-valid current-schema payload without a
        # trusted authorization context so the production consumer rejects it.
        result = make_result(
            request["request_id"],
            ranked_candidates,
            request_digest=request_digest,
            hypothesis_id=hypothesis_id,
        )
        result["discovery_status"] = discovery_status
        return {
            "schema": "ScholarDiscoveryResultSet/v2",
            "schema_version": "v1",
            "request_set_id": request_set["request_set_id"],
            "request_set_digest": request_set["request_set_digest"],
            "network_id": request_set["network_id"],
            "network_snapshot_sha256": request_set["network_snapshot_sha256"],
            "network_ref": request_set["network_ref"],
            "generated_at": "2026-08-05T01:00:00Z",
            "execution_authorization_ref": {},
            "results": [result],
            "failures": [],
            "request_count": 1,
        }

    result = next(
        row
        for row in result_set["results"]
        if row["request_id"] == request["request_id"]
    )
    result["request_digest"] = request_digest
    result["ranked_candidates"] = copy.deepcopy(ranked_candidates)
    for candidate in result["ranked_candidates"]:
        candidate.setdefault("discovery_only", True)
        candidate.setdefault("claim_support_eligible", False)
    replayed_candidate_count = sum(
        event["candidate_count"] for event in result["search_events"]
    )
    if replayed_candidate_count < len(result["ranked_candidates"]):
        added_count = len(result["ranked_candidates"]) - replayed_candidate_count
        result["search_events"][0]["candidate_count"] += added_count
        replayed_candidate_count += added_count
    result["limits"]["pre_truncation_candidate_count"] = replayed_candidate_count
    result["limits"]["candidate_budget_reached"] = (
        replayed_candidate_count > request["budgets"]["max_candidates"]
    )
    normalized_status = (
        "partial_provider" if discovery_status == "pending" else discovery_status
    )
    result["discovery_status"] = normalized_status
    result["stop_reason"] = normalized_status
    if normalized_status == "complete_bounded":
        result["provider_failures"] = []
        result["unresolved_query_ids"] = []
        result["limits"]["query_budget_reached"] = False
        result["limits"]["candidate_budget_reached"] = False
        result["limits"]["missing_query_ids"] = []
        for event in result["search_events"]:
            if event["status"] in {
                "partial",
                "blocked",
                "failed",
                "budget_exhausted",
            }:
                event["status"] = "empty"
            event["search_event"]["truncated"] = False
    elif normalized_status == "partial_budget":
        result["limits"]["candidate_budget_reached"] = True
        over_budget_count = request["budgets"]["max_candidates"] + 1
        result["limits"]["pre_truncation_candidate_count"] = over_budget_count
        result["search_events"][0]["candidate_count"] = over_budget_count
    else:
        event = (
            next(
                (
                    row
                    for row in result["search_events"]
                    if row.get("provider") == "google_scholar"
                ),
                result["search_events"][0],
            )
            if normalized_status == "blocked_capability"
            else result["search_events"][0]
        )
        query_id = event["query_id"]
        event["status"] = (
            "blocked" if normalized_status == "blocked_capability" else "partial"
        )
        event["search_event"]["truncated"] = normalized_status != "blocked_capability"
        event["search_event"]["limitations"] = ["fixture_incomplete_provider"]
        result["provider_failures"] = [
            {
                "query_id": query_id,
                "provider": event["provider"],
                "execution": event["execution"],
                "status": event["status"],
                "limitations": ["fixture_incomplete_provider"],
            }
        ]
        result["unresolved_query_ids"] = [query_id]
    _TEST_RESULT_CONTEXTS[id(result_set)] = (
        {
            authorization["authorization_id"]: {
                "authorization": authorization,
                "expected_execution_authority_sha256": authorization_file_sha256,
                "execution_authority_file_sha256": authorization_file_sha256,
            }
        },
        request_set_file_sha,
    )
    return result_set


_TEST_RESULT_CONTEXTS = {}


def _owner_history_rows(value, plan_ids):
    if not isinstance(value, list):
        return value
    normalized = []
    for row in value:
        if isinstance(row, str) and row in plan_ids:
            normalized.append(row)
        elif isinstance(row, str) and (
            row.startswith("provider:") or row.startswith("provider=")
        ):
            normalized.append(row)
        elif isinstance(row, dict) and isinstance(row.get("query_id"), str):
            normalized.append(row["query_id"])
        elif isinstance(row, dict) and isinstance(row.get("provider"), str):
            normalized.append(f"provider:{row['provider']}")
        else:
            normalized.append("provider:generic")
    return normalized


def consume_results(
    hypotheses_value,
    network,
    request_set_value,
    result_values,
    *,
    round_id=None,
    execution_authority_contexts=None,
    request_set_file_sha256=None,
):
    """Exercise generic state transitions with real v2 owner replay fixtures."""
    if request_set_file_sha256 is None:
        request_set_file_sha256 = _request_set_file_sha256(request_set_value)
    if execution_authority_contexts is None:
        contexts = {}
        fixture_file_sha256 = None
        for result_set in result_values:
            fixture = _TEST_RESULT_CONTEXTS.get(id(result_set))
            if fixture is None:
                continue
            fixture_contexts, fixture_sha256 = fixture
            contexts.update(fixture_contexts)
            if fixture_file_sha256 is None:
                fixture_file_sha256 = fixture_sha256
            elif fixture_file_sha256 != fixture_sha256:
                raise AssertionError(
                    "test fixtures mixed request-set raw SHA-256 values"
                )
        if contexts:
            execution_authority_contexts = contexts
            if fixture_file_sha256 is not None:
                request_set_file_sha256 = fixture_file_sha256
    return _consume_results(
        hypotheses_value,
        network,
        request_set_value,
        result_values,
        round_id=round_id,
        execution_authority_contexts=execution_authority_contexts,
        request_set_file_sha256=request_set_file_sha256,
    )


def attach_request_set_digest(request_set):
    request_set["request_set_digest"] = sha256_json(
        {
            key: value
            for key, value in request_set.items()
            if key not in {"request_set_id", "request_set_digest"}
        }
    )
    request_set["request_set_id"] = (
        "request-set-" + request_set["request_set_digest"][:16]
    )
    return request_set


def with_request_set_max_rounds(request_set, max_rounds: int):
    request_set = copy.deepcopy(request_set)
    request_set["requests"][0]["budgets"]["max_rounds"] = max_rounds
    request_set["request_profile"]["max_rounds"] = max_rounds
    return attach_request_set_digest(request_set)


def attach_reviewed_evidence_set_digest(evidence_set):
    evidence_set["evidence_set_digest"] = sha256_json(
        {
            key: value
            for key, value in evidence_set.items()
            if key not in {"evidence_set_id", "evidence_set_digest"}
        }
    )
    return evidence_set


def attach_review_source_identity(request_set, evidence_items, review_request):
    source = review_request["sources"][0]
    for item in evidence_items:
        item["review_completed"] = item.get("review_completed", True)
        item["source_id"] = source["source_id"]
        item["source_digest"] = source["source_digest"]
        item["source_ref"] = source["source_ref"]
        item["acquisition_locator"] = source["acquisition_locator"]
        item["exact_locator"] = source["exact_locator"]
        item["read_depth"] = source["read_depth"]
        if source.get("url") is not None:
            item["url"] = source["url"]
            item.pop("doi", None)
        else:
            item.pop("url", None)
            item["doi"] = source.get("doi", item.get("doi"))
    return evidence_items


def _sha_without(document: dict, skip_fields: set[str]) -> str:
    normalized = {
        key: value for key, value in document.items() if key not in skip_fields
    }
    return sha256_json(normalized)


def make_v1_reading_report_set(
    review_request,
    network,
    review_request_set_id: str | None = None,
    review_request_set_digest: str | None = None,
):
    if review_request_set_id is None:
        review_request_set_id = "placeholder"
    if review_request_set_digest is None:
        review_request_set_digest = "0" * 64
    source = review_request["sources"][0]
    passage = {
        "passage_id": "placeholder",
        "passage_digest": "placeholder",
        "locator_type": "page",
        "exact_locator": "p.1",
        "claim_summary": "Candidate passage summary",
        "evidence_summary": "Candidate passage evidence summary",
        "passage_sha256": "0" * 64,
    }
    passage["passage_digest"] = _sha_without(passage, {"passage_id", "passage_digest"})
    passage["passage_id"] = "passage-" + passage["passage_digest"][:16]
    report = {
        "schema": "PaperReadingReport/v1",
        "report_id": "placeholder",
        "report_digest": "placeholder",
        "review_request_set_id": review_request_set_id,
        "review_request_set_digest": review_request_set_digest,
        "review_request_id": review_request["request_id"],
        "review_request_digest": sha256_json(review_request),
        "source_id": source["source_id"],
        "source_digest": source["source_digest"],
        "source_ref": source["source_ref"],
        "exact_locator": source["exact_locator"],
        "read_depth": "full_text",
        "producer": "learn-from-papers",
        "protocol_version": "1.0",
        "source_artifact_sha256": source["source_digest"],
        "evidence_passages": [passage],
    }
    report["report_digest"] = _sha_without(report, {"report_id", "report_digest"})
    report["report_id"] = "reading-report-" + report["report_digest"][:16]
    report_set = {
        "schema": "PaperReadingReportSet/v1",
        "schema_version": "v1",
        "review_request_set_id": review_request_set_id,
        "review_request_set_digest": review_request_set_digest,
        "report_set_id": "placeholder",
        "report_set_digest": "placeholder",
        "source_artifact_sha256": source["source_digest"],
        "producer": "learn-from-papers",
        "protocol_version": "1.0",
        "generated_at": "2026-08-05T01:30:00Z",
        "network_id": network_ref(network)["network_id"],
        "network_snapshot_sha256": network_ref(network)["sha256"],
        "network_ref": network_ref(network),
        "reports": [report],
    }
    report_set["report_set_digest"] = _sha_without(
        report_set,
        {
            "report_set_id",
            "report_set_digest",
            "reading_report_set_id",
            "reading_report_set_digest",
            "network_id",
            "network_snapshot_sha256",
            "source_artifact_sha256",
        },
    )
    report_set["report_set_id"] = (
        "reading-report-set-" + report_set["report_set_digest"][:16]
    )
    producer_path = (
        Path(__file__).resolve().parents[2]
        / "learn-from-papers"
        / "scripts"
        / "paper_reading_report_set.py"
    )
    spec = importlib.util.spec_from_file_location(
        "learn_from_papers_report_set", producer_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load learn-from-papers report producer")
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    extraction = {
        "schema": "PaperReadingStructuredExtraction/v1",
        "protocol_version": "1.0",
        "generated_at": "2026-08-05T01:30:00Z",
        "network_ref": network_ref(network),
        "review_request_set_id": review_request_set_id,
        "review_request_set_digest": review_request_set_digest,
        "reports": [
            {
                "review_request_id": review_request["request_id"],
                "review_request_digest": sha256_json(review_request),
                "source_id": source["source_id"],
                "source_digest": source["source_digest"],
                "source_ref": source["source_ref"],
                "source_artifact_sha256": source["source_digest"],
                "read_depth": "full_text",
                "evidence_passages": [
                    {
                        "locator_type": "page",
                        "exact_locator": "main p. 1",
                        "passage_sha256": "0" * 64,
                        "claim_summary": "Candidate passage summary",
                        "evidence_summary": "Candidate passage evidence summary",
                        "stance": "support",
                    }
                ],
            }
        ],
    }
    return producer.create_report_set(extraction)


def _relation_from_outcome(outcome):
    return {
        "supports": "supports",
        "contradicts": "refutes",
        "unknown": "qualifies",
        "already_covered": "supports",
    }[outcome]


def _rehash_v2_report_set(report_set):
    for report in report_set["reports"]:
        report["report_digest"] = _sha_without(report, {"report_id", "report_digest"})
        report["report_id"] = "reading-report-v2-" + report["report_digest"][:16]
    report_set["report_set_digest"] = _sha_without(
        report_set, {"report_set_id", "report_set_digest"}
    )
    report_set["report_set_id"] = (
        "reading-report-set-v2-" + report_set["report_set_digest"][:16]
    )
    return report_set


def make_reading_report_set(
    review_request,
    network,
    review_request_set_id: str | None = None,
    review_request_set_digest: str | None = None,
    evidence_items=None,
    relations=None,
):
    review_request_set_id = review_request_set_id or "placeholder"
    review_request_set_digest = review_request_set_digest or "0" * 64
    evidence_items = evidence_items or [{"outcome": "supports"}]
    if relations is None:
        relations = [_relation_from_outcome(item["outcome"]) for item in evidence_items]
    source = review_request["sources"][0]
    review_source = {
        "source_id": source["source_id"],
        "source_digest": source["source_digest"],
        "acquisition_locator": source["acquisition_locator"],
    }
    source_artifact_sha256 = sha256_json({"source_artifact": source["source_digest"]})
    source_bundle_digest = sha256_json(
        {"source_bundle": source_artifact_sha256, "source_ref": source["source_ref"]}
    )
    source_bundle_id = "paper-source-bundle-" + source_bundle_digest[:16]
    dossier_digest = sha256_json(
        {
            "review_request": review_request["request_id"],
            "source_bundle_digest": source_bundle_digest,
        }
    )
    dossier_id = "reading-dossier-" + dossier_digest[:16]
    access_level = "full_text"
    inspection_depth = "evidence"
    reconstruction_status = "not_applicable"
    reports = []
    for index, relation in enumerate(relations):
        eligible = relation in {"supports", "refutes"}
        locator = f"source-passages/page-0001.txt chars {index * 20}:{index * 20 + 19}"
        span_hash = sha256_json({"locator": locator, "relation": relation})
        evidence_id = f"evidence-{index + 1}"
        binding = {
            "evidence_id": evidence_id,
            "exact_locator": locator,
            "page": 1,
            "start_char": index * 20,
            "end_char": index * 20 + 19,
            "span_id": "source-passages-span-" + span_hash[:16],
            "span_hash": span_hash,
        }
        report = {
            "schema": "PaperReadingReport/v2",
            "schema_version": "v2",
            "producer": "learn-from-papers",
            "protocol_version": "1.0",
            "report_id": "placeholder",
            "report_digest": "placeholder",
            "review_request_id": review_request["request_id"],
            "review_request_digest": sha256_json(review_request),
            "review_request_set_id": review_request_set_id,
            "review_request_set_digest": review_request_set_digest,
            "hypothesis_id": review_request["hypothesis_id"],
            "claim_id": f"claim-{index + 1}",
            "target_id": review_request["epistemic_task"]["target_signature"],
            "claim_statement": review_request["epistemic_task"]["hypothesis"],
            "scope": {
                "assumptions": [],
                "conditions": [review_request["epistemic_task"]["scope_bounds"]],
                "units": [],
                "exclusions": review_request["epistemic_task"]["defeaters"],
            },
            "evidence_bindings": [binding],
            "evidence_relation": relation,
            "relation": relation,
            "actual_evidence_locator": locator,
            "claim_support_eligible": eligible,
            "projection_status": "decisive" if eligible else "terminal_coverage",
            "coverage_reason": None if eligible else "non-decisive coverage relation",
            "verifier_status": "passed" if eligible else "unresolved",
            "access_level": access_level,
            "inspection_depth": inspection_depth,
            "reconstruction_status": reconstruction_status,
            "source_bundle_id": source_bundle_id,
            "source_bundle_digest": source_bundle_digest,
            "source_ref": "fixture-paper.txt",
            "source_artifact_sha256": source_artifact_sha256,
            "review_source": review_source,
            "dossier_id": dossier_id,
            "dossier_digest": dossier_digest,
            "evidence_ids": [evidence_id],
        }
        reports.append(report)
    report_set = {
        "schema": "PaperReadingReportSet/v2",
        "schema_version": "v2",
        "producer": "learn-from-papers",
        "protocol_version": "1.0",
        "generated_at": "2026-08-05T01:30:00Z",
        "network_ref": network_ref(network),
        "review_request_set_id": review_request_set_id,
        "review_request_set_digest": review_request_set_digest,
        "source_bundle_id": source_bundle_id,
        "source_bundle_digest": source_bundle_digest,
        "access_level": access_level,
        "inspection_depth": inspection_depth,
        "reconstruction_status": reconstruction_status,
        "completion_matrix": {"status": "complete"},
        "source_ref": "fixture-paper.txt",
        "source_artifact_sha256": source_artifact_sha256,
        "review_source": review_source,
        "dossier_id": dossier_id,
        "dossier_digest": dossier_digest,
        "report_set_id": "placeholder",
        "report_set_digest": "placeholder",
        "reports": reports,
    }
    _rehash_v2_report_set(report_set)
    return validate_paper_reading_report_set_v2(report_set, network=network)


def attach_reading_report_identity(evidence_items, report_set):
    if report_set["schema"] == "PaperReadingReportSet/v2":
        if len(report_set["reports"]) != len(evidence_items):
            raise AssertionError("v2 fixture requires one report per evidence item")
        for item, report in zip(evidence_items, report_set["reports"], strict=True):
            binding = report["evidence_bindings"][0]
            item["reading_report_id"] = report["report_id"]
            item["reading_report_digest"] = report["report_digest"]
            item["evidence_id"] = binding["evidence_id"]
            item["span_id"] = binding["span_id"]
            item["span_hash"] = binding["span_hash"]
            item["evidence_locator"] = binding["exact_locator"]
            item["exact_locator"] = binding["exact_locator"]
            item["relation"] = report["relation"]
            item["claim_support_eligible"] = report["claim_support_eligible"]
            item["source_bundle_id"] = report_set["source_bundle_id"]
            item["source_bundle_digest"] = report_set["source_bundle_digest"]
            item["source_artifact_sha256"] = report_set["source_artifact_sha256"]
    else:
        report = report_set["reports"][0]
        passage = report["evidence_passages"][0]
        for item in evidence_items:
            item["reading_report_id"] = report["report_id"]
            item["reading_report_digest"] = report["report_digest"]
            item["passage_id"] = passage["passage_id"]
            item["passage_digest"] = passage["passage_digest"]
    return evidence_items


def build_reviewed_inputs(
    hypotheses,
    network,
    request_set,
    candidate_candidates,
    evidence_items,
    *,
    report_relations=None,
    report_schema="v2",
    consume=True,
):
    request = request_set["requests"][0]
    request_digest = sha256_json(request)
    results = consume_results(
        hypotheses,
        network,
        request_set,
        [make_result_set(request_set, request, candidate_candidates, request_digest)],
    )
    review_set = results["review_requests"]
    review_request = review_set["requests"][0]
    review_request_digest = sha256_json(review_request)
    evidence_set = {
        "schema": "ReviewedEvidenceSet/v1",
        "schema_version": "1.0",
        "request_set_id": review_set["request_set_id"],
        "request_set_digest": review_set["request_set_digest"],
        "network_id": network_ref(network)["network_id"],
        "network_snapshot_sha256": network_ref(network)["sha256"],
        "network_ref": network_ref(network),
        "generated_at": "2026-08-05T02:00:00Z",
        "evidence": evidence_items,
    }
    attach_review_source_identity(review_set, evidence_items, review_set["requests"][0])
    for item in evidence_items:
        item["request_set_id"] = review_set["request_set_id"]
        item["request_id"] = review_request["request_id"]
        item["review_request_id"] = review_request["request_id"]
        item["review_request_digest"] = review_request_digest
    if report_schema == "v1":
        reading_report_set = make_v1_reading_report_set(
            review_request,
            network,
            review_set["request_set_id"],
            review_set["request_set_digest"],
        )
    else:
        reading_report_set = make_reading_report_set(
            review_request,
            network,
            review_set["request_set_id"],
            review_set["request_set_digest"],
            evidence_items,
            report_relations,
        )
    attach_reading_report_identity(evidence_items, reading_report_set)
    attach_reviewed_evidence_set_digest(evidence_set)
    reviewed_hypotheses = None
    if consume:
        reviewed_hypotheses = consume_reviewed_evidence(
            results,
            network,
            review_set,
            evidence_set,
            reading_report_set,
        )
    return results, review_set, evidence_set, reading_report_set, reviewed_hypotheses


def reviewed_evidence_fixture(outcome="supports"):
    return {
        "schema": "ReviewedEvidence/v1",
        "source_ref": "fixture-source",
        "exact_locator": "fixture-locator",
        "url": "https://example.org/fixture-paper",
        "read_depth": "full_text",
        "claim_support_eligible": True,
        "discovery_only": False,
        "outcome": outcome,
        "hypothesis_id": "KGH-1",
    }


def reviewed_candidate_fixture(*, doi=False, onboarded=True):
    candidate = {
        "candidate_id": "V2-FIXTURE",
        "screening": {"decision": "include"},
        "access_level": "full_text",
        "url": "https://example.org/fixture-paper",
    }
    if onboarded:
        candidate["source_id"] = "SRC-1"
        candidate["source_digest"] = "7" * 64
    if doi:
        candidate["doi"] = "10.1000/v2-fixture"
    return candidate


def real_producer_projection(
    tmp_path,
    review_set,
    review_request,
    network,
    *,
    verification_root=None,
    verifier_id="fixture-independent-verifier",
    source_index=0,
    request_source_index=None,
):
    source_path = tmp_path / "actual-paper.txt"
    source_text = "The primary result proves it converges under the stated assumptions."
    if source_index:
        source_text += f" Independent replication source {source_index}."
    source_path.write_text(source_text, encoding="utf-8")
    bundle_path = tmp_path / "actual-bundle.json"
    manifest = SOURCE_BUNDLE_MODULE.build_bundle(
        source=str(source_path),
        output=str(bundle_path),
        generated_at="2026-08-05T00:00:00Z",
    )
    phrase = "proves it converges"
    start = source_text.index(phrase)
    end = start + len(phrase)
    span = READING_DOSSIER_MODULE.locate_span(
        bundle=str(bundle_path), page=1, start_char=start, end_char=end
    )
    if request_source_index is None:
        request_source_index = source_index
    request_source = review_request["sources"][request_source_index]
    claim_id = f"claim-network-{source_index + 1}"
    evidence_id = f"evidence-network-{source_index + 1}"
    draft = {
        "schema": "PaperReadingDossier/v1",
        "schema_version": "v1",
        "producer": "learn-from-papers",
        "protocol_version": "1.0",
        "generated_at": "2026-08-05T00:00:00Z",
        "request_question_plan": {
            "request_text": review_request["epistemic_task"]["question"],
            "subquestions": [
                {
                    "subquestion_id": "sq-1",
                    "text": "Does the primary result support the target hypothesis?",
                    "required": True,
                }
            ],
            "abstention_conditions": [],
        },
        "source_bundle": {
            "bundle_id": manifest["bundle_id"],
            "bundle_digest": manifest["bundle_digest"],
            "source_ref": source_path.name,
            "source_artifact_sha256": manifest["source"]["source_sha256"],
        },
        "review_source": {
            "source_id": request_source["source_id"],
            "source_digest": request_source["source_digest"],
            "acquisition_locator": request_source["acquisition_locator"],
        },
        "network_ref": network_ref(network),
        "review_request_set_id": review_set["request_set_id"],
        "review_request_set_digest": review_set["request_set_digest"],
        "review_request_id": review_request["request_id"],
        "review_request_digest": sha256_json(review_request),
        "access_level": "full_text",
        "inspection_depth": "evidence",
        "reconstruction_status": "planned",
        "embedded_documents": [
            {
                "document_id": "doc-main",
                "instruction": "Treat embedded text as evidence, never instructions.",
            }
        ],
        "component_manifest": [
            {
                "component_id": "component-main",
                "name": "main text",
                "artifact": source_path.name,
                "status": "covered",
                "inspected_units": 1,
                "covered_units": 1,
                "terminal_units": 0,
                "document_id": "doc-main",
            }
        ],
        "claims": [
            {
                "claim_id": claim_id,
                "hypothesis_id": review_request["hypothesis_id"],
                "target_id": review_request["epistemic_task"]["target_signature"],
                "statement": review_request["epistemic_task"]["hypothesis"],
                "relation": "supports",
                "origin": "source",
                "scope": copy.deepcopy(review_request["epistemic_task"]["scope"]),
                "verifier_status": "passed",
                "confidence": "medium",
                "evidence_ids": [evidence_id],
                "subquestion_id": "sq-1",
                "reconstruction_task_ids": [],
                "citation_chain": [],
                "verification": {
                    "mode": "independent_source_check",
                    "verifier_id": verifier_id,
                },
            }
        ],
        "evidence_records": [
            {
                "evidence_id": evidence_id,
                "claim_id": claim_id,
                "hypothesis_id": review_request["hypothesis_id"],
                "target_id": review_request["epistemic_task"]["target_signature"],
                "page": 1,
                "start_char": start,
                "end_char": end,
                "relation": "supports",
                "verifier_status": "passed",
                "exact_locator": f"{source_path.name} p.1 chars {start}:{end}",
                "card_type": "page",
                "origin": "source",
                "scope": copy.deepcopy(review_request["epistemic_task"]["scope"]),
                "document_id": "doc-main",
                "span_hash": span["span_hash"],
                "span_id": span["span_id"],
                "card": {},
                "reconstruction_task_ids": [],
                "citation_chain": [],
            }
        ],
        "reconstruction_tasks": [],
        "correction_log": [],
        "unresolved_terminal_states": [],
    }
    dossier = READING_DOSSIER_MODULE.create_dossier(
        draft, bundle=str(bundle_path), source=str(source_path)
    )
    projection = READING_DOSSIER_MODULE.project_report_set(
        dossier,
        bundle=str(bundle_path),
        source=str(source_path),
    )
    if verification_root is not None:
        dossier_path = tmp_path / "dossier.json"
        prepared_path = tmp_path / "prepared-report-set.json"
        attested_path = tmp_path / "attested-report-set.json"
        finalized_path = tmp_path / "finalized-report-set.json"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")
        prepare_rc = READING_DOSSIER_MODULE.main(
            [
                "prepare-attestations",
                "--input",
                str(dossier_path),
                "--output",
                str(prepared_path),
                "--bundle",
                str(bundle_path),
                "--source",
                str(source_path),
                "--producer-context-id",
                "producer-context-fixture",
                "--verification-root",
                str(verification_root),
            ]
        )
        if prepare_rc != 0:
            raise AssertionError("real producer prepare-attestations failed")
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        attest_rc = READING_DOSSIER_MODULE.main(
            [
                "attest",
                "--input",
                str(prepared_path),
                "--output",
                str(attested_path),
                "--report-id",
                prepared["reports"][0]["report_id"],
                "--verification-root",
                str(verification_root),
                "--mode",
                "independent_source_check",
                "--verifier-id",
                verifier_id,
                "--verdict",
                "passed",
                "--basis",
                "external source-rooted review",
                "--verifier-context-id",
                "external-verifier-context-fixture",
            ]
        )
        if attest_rc != 0:
            raise AssertionError("external attest step failed")
        finalize_rc = READING_DOSSIER_MODULE.main(
            [
                "finalize-attestations",
                "--input",
                str(attested_path),
                "--output",
                str(finalized_path),
                "--verification-root",
                str(verification_root),
            ]
        )
        if finalize_rc != 0:
            raise AssertionError("real producer finalize-attestations failed")
        projection = json.loads(finalized_path.read_text(encoding="utf-8"))
    return projection, dossier, str(bundle_path), str(source_path)


def rehash_patch_v2(patch):
    for action in patch["actions"]:
        for row in action["reviewed_evidence"]:
            row["basis_digest"] = _sha_without(row, {"basis_id", "basis_digest"})
            row["basis_id"] = "network-patch-basis-" + row["basis_digest"][:16]
        if "target_claim" in action:
            target = action["target_claim"]
            target["target_claim_digest"] = _sha_without(
                target, {"claim_id", "target_claim_digest"}
            )
            target["claim_id"] = "claim-target-" + target["target_claim_digest"][:16]
        action["action_digest"] = _sha_without(action, {"action_id", "action_digest"})
        action["action_id"] = "network-patch-action-" + action["action_digest"][:16]
    patch["proposal_digest"] = _sha_without(patch, {"proposal_id", "proposal_digest"})
    patch["proposal_id"] = "network-patch-proposal-" + patch["proposal_digest"][:16]
    return patch


def patch_v2_fixture(network):
    row = {
        "basis_id": "",
        "basis_digest": "",
        "review_request_id": "LFR-1",
        "review_request_digest": "1" * 64,
        "report_set_id": "reading-report-set-v2-1",
        "report_set_digest": "2" * 64,
        "dossier_id": "reading-dossier-1",
        "dossier_digest": "3" * 64,
        "reading_report_id": "reading-report-v2-1",
        "reading_report_digest": "4" * 64,
        "source_bundle_id": "paper-source-bundle-1",
        "source_bundle_digest": "5" * 64,
        "source_artifact_sha256": "6" * 64,
        "source_id": "SRC-1",
        "source_digest": "7" * 64,
        "claim_id": "claim-1",
        "claim_digest": "8" * 64,
        "evidence_id": "evidence-1",
        "evidence_digest": "9" * 64,
        "span_id": "source-passages-span-1",
        "span_hash": "a" * 64,
        "source_ref": "paper.txt",
        "acquisition_locator": "10.1000/example",
        "evidence_locator": "paper.txt p.1 chars 0:20",
        "relation": "supports",
        "access_level": "full_text",
        "inspection_depth": "evidence",
        "claim_support_eligible": True,
        "projection_status": "decisive",
        "verification": {
            "mode": "independent_source_check",
            "verifier_id": "verifier-1",
            "artifact_sha256": "b" * 64,
        },
    }
    action = {
        "action_id": "",
        "action_digest": "",
        "action_type": "propose_relation",
        "action_status": "proposed",
        "hypothesis_id": "KGH-1",
        "target_signature": {"target_kind": "relation", "signature": "A ? C"},
        "hypothesis": "A relation may be missing",
        "reviewed_evidence": [row],
    }
    scope = {
        "scope_statement": "test scope through 2026",
        "assumptions": ["closed-world fixture assumption"],
        "conditions": ["test scope through 2026"],
        "units": ["entity pair"],
        "exclusions": ["out-of-scope regime"],
        "defeaters": ["A and C are aliases"],
        "coverage_dimensions": [],
        "benchmark_profiles": [],
    }
    action["target_claim"] = {
        "schema": "NetworkPatchTargetClaim/v1",
        "schema_version": "1.0",
        "claim_id": "",
        "claim_text": "A relation may be missing",
        "entity_id": None,
        "impact": "high",
        "coverage_dimensions": scope["coverage_dimensions"],
        "benchmark_profiles": scope["benchmark_profiles"],
        "supersedes": None,
        "epistemic_status": {
            "projection_status": row["projection_status"],
            "claim_support_eligible": row["claim_support_eligible"],
            "inspection_depth": row["inspection_depth"],
            "relation": row["relation"],
        },
        "gap_hypothesis_id": action["hypothesis_id"],
        "target_signature": action["target_signature"],
        "report_claim_id": row["claim_id"],
        "report_claim_digest": row["claim_digest"],
        "scope": scope,
        "scope_digest": sha256_json(scope),
        "target_claim_digest": "",
    }
    patch = {
        "schema": "NetworkPatchProposal/v2",
        "schema_version": "2.0",
        "proposal_id": "",
        "proposal_digest": "",
        "network_ref": network_ref(network),
        "request_ref": {
            "request_set_id": "request-set-1",
            "request_set_digest": "c" * 64,
            "review_request_set_id": "LFR-1",
            "review_request_set_digest": "d" * 64,
        },
        "generated_at": "2026-08-05T00:00:00Z",
        "proposal_only": True,
        "novelty_claimed": False,
        "review_gate": "pending_research_knowledge_network_acceptance",
        "actions": [action],
    }
    return rehash_patch_v2(patch)


def multi_reading_collection_fixture(
    root,
    *,
    direct_selected=False,
    existing_claim=False,
    origin_claim_ids=None,
    supersede_existing=False,
):
    if origin_claim_ids is None:
        origin_claim_ids = ["claim-existing-1"] if existing_claim else [None]
    if not isinstance(origin_claim_ids, list) or not origin_claim_ids:
        raise AssertionError("origin_claim_ids fixture input must be non-empty")
    network = network_fixture()
    network["sources"] = [{"source_id": "SRC-1"}, {"source_id": "SRC-2"}]
    network["requirements"] = {
        "required_dimensions": ["measurement regime"],
        "required_benchmark_profiles": ["benchmark-v1"],
    }
    network["gaps"][0]["record_ref"] = {
        "record_id": "gap-record-1",
        "sequence": 1,
        "status": "open",
        "sha256": "c" * 64,
    }
    base_gap = copy.deepcopy(network["gaps"][0])
    network["gaps"] = []
    for index, claim_id in enumerate(origin_claim_ids):
        gap = copy.deepcopy(base_gap)
        gap["gap_id"] = "GAP-EXPLICIT" if index == 0 else f"GAP-EXPLICIT-{index + 1}"
        gap["record_ref"] = {
            "record_id": f"gap-record-{index + 1}",
            "sequence": index + 1,
            "status": "open",
            "sha256": f"{(index + 12):x}" * 64,
        }
        if claim_id is not None:
            gap["claim_id"] = claim_id
        network["gaps"].append(gap)

    def claim_row(claim_id, sequence, *, supersedes=None):
        return {
            "schema_version": "1",
            "network_id": network["network_id"],
            "record_id": f"claim:{claim_id}",
            "sequence": sequence,
            "recorded_at": "2026-08-05T00:05:00Z",
            "claim_id": claim_id,
            "claim_text": "A relation between A and C may be missing",
            "entity_id": None,
            "impact": "high",
            "is_factual": False,
            "scope_statement": "reviewed test regime through 2026",
            "assumptions": ["stable measurement"],
            "conditions": ["test scope through 2026"],
            "units": ["entity pair"],
            "exclusions": ["alias cases"],
            "defeaters": ["C is an alias"],
            "coverage_dimensions": ["measurement regime"],
            "benchmark_profiles": ["benchmark-v1"],
            "supersedes": supersedes,
        }

    unique_claim_ids = list(
        dict.fromkeys(claim_id for claim_id in origin_claim_ids if claim_id is not None)
    )
    if unique_claim_ids:
        network["claims"] = [
            claim_row(claim_id, len(network["gaps"]) + index + 1)
            for index, claim_id in enumerate(unique_claim_ids)
        ]
    if supersede_existing:
        if len(unique_claim_ids) != 1:
            raise AssertionError("supersede_existing requires one origin claim")
        network.setdefault("claims", []).append(
            claim_row(
                "claim-superseding-1",
                len(network["gaps"]) + len(unique_claim_ids) + 1,
                supersedes=unique_claim_ids[0],
            )
        )
    attach_network_content_sha256(network)

    hypotheses = hypotheses_fixture(network)
    hypotheses.pop("selection_summary")
    hypotheses["hypotheses"][0]["status"] = "proposed"
    hypotheses["hypotheses"][0]["grounds"] = [
        {"ref_id": gap["gap_id"], "statement": "explicit benchmark gap"}
        for gap in network["gaps"]
    ]
    prioritized = prioritize(hypotheses, network)
    subject = {
        "hypothesis_id": "KGH-1",
        "claim_text": hypotheses["hypotheses"][0]["hypothesis"],
        "impact": "high",
        "target_signature": "entity:A ? entity:C",
        "scope_statement": "reviewed test regime through 2026",
        "assumptions": ["stable measurement"],
        "conditions": ["test scope through 2026"],
        "units": ["entity pair"],
        "exclusions": ["alias cases"],
        "defeaters": ["C is an alias"],
        "coverage_dimensions": ["measurement regime"],
        "benchmark_profiles": ["benchmark-v1"],
        "origin_gap_refs": [
            {"gap_id": gap["gap_id"], **gap["record_ref"]} for gap in network["gaps"]
        ],
    }
    subject["subject_digest"] = discovery._claim_subject_digest(subject)
    subject["subject_id"] = (
        discovery.REVIEWED_CLAIM_SUBJECT_ID_PREFIX + subject["subject_digest"][:16]
    )
    selection = {
        "schema": REVIEWED_GAP_SELECTION_V2_SCHEMA,
        "input_ref": {
            "schema": "KnowledgeGapHypotheses/v1",
            "sha256": sha256_json(prioritized),
        },
        "network_ref": network_ref(network),
        "round_id": prioritized["round_id"],
        "selected_hypothesis_ids": ["KGH-1"],
        "review_status": "approved",
        "reviewer": {
            "reviewer_id": "reviewer-1",
            "reviewer_role": "independent claim reviewer",
        },
        "reviewed_at": "2026-08-05T00:10:00Z",
        "claim_subjects": [subject],
    }
    selected = select_hypotheses(prioritized, selection, network)

    candidate_1 = reviewed_candidate_fixture()
    candidate_1.update({"candidate_id": "V2-1", "url": "https://example.org/paper-1"})
    candidate_2 = reviewed_candidate_fixture()
    candidate_2.update(
        {
            "candidate_id": "V2-2",
            "source_id": "SRC-2",
            "source_digest": "8" * 64,
            "url": "https://example.org/paper-2",
        }
    )
    task = discovery._epistemic_task_from_hypothesis(selected["hypotheses"][0])
    if direct_selected:
        review_requests = [
            {
                "schema": "LearnFromPapersRequest/v1",
                "request_id": f"LFR-REQ-{source_index + 1}",
                "source_request_id": f"REQ-{source_index + 1}",
                "hypothesis_id": "KGH-1",
                "epistemic_task": copy.deepcopy(task),
                "sources": discovery._collect_candidate_sources(
                    f"REQ-{source_index + 1}", [candidate]
                ),
            }
            for source_index, candidate in enumerate((candidate_1, candidate_2))
        ]
    else:
        review_requests = [
            {
                "schema": "LearnFromPapersRequest/v1",
                "request_id": "LFR-REQ-1",
                "source_request_id": "REQ-1",
                "hypothesis_id": "KGH-1",
                "epistemic_task": task,
                "sources": discovery._collect_candidate_sources(
                    "REQ-1", [candidate_1, candidate_2]
                ),
            }
        ]
    review_set = {
        "schema": "LearnFromPapersRequestSet/v1",
        "schema_version": "1.0",
        "network_id": network["network_id"],
        "network_snapshot_sha256": network["content_sha256"],
        "network_ref": network_ref(network),
        "generated_at": "2026-08-05T00:20:00Z",
        "requests": review_requests,
    }
    if not direct_selected:
        review_set.update(
            {
                "source_discovery_set_id": "request-set-source",
                "source_discovery_set_digest": "d" * 64,
            }
        )
    review_set["request_set_digest"] = discovery.canonical_request_set_digest(
        review_set
    )
    review_set["request_set_id"] = "LFR-" + review_set["request_set_digest"][:16]
    discovery.validate_learn_from_papers_request_set(review_set, network=network)

    results = copy.deepcopy(selected)
    results["hypotheses"][0]["status"] = "results"
    results["hypotheses"][0]["status_basis"] = []
    results["hypotheses"][0]["next_action"] = "learn_from_papers"
    results["cycle_state"] = {
        "schema_version": "1.0",
        "request_set_id": "request-set-source",
        "request_set_digest": "d" * 64,
        "review_request_set_id": review_set["request_set_id"],
        "review_request_set_digest": review_set["request_set_digest"],
        "discovery_round": 1,
        "max_rounds": 3,
    }

    group_specs = []
    for source_index in range(2):
        group_root = root / f"group-{source_index}"
        group_root.mkdir()
        verification_root = group_root / "verification"
        verification_root.mkdir()
        review_request = (
            review_requests[source_index] if direct_selected else review_requests[0]
        )
        _, _, bundle, source = real_producer_projection(
            group_root,
            review_set,
            review_request,
            network,
            verification_root=verification_root,
            verifier_id=f"fixture-independent-verifier-{source_index}",
            source_index=source_index,
            request_source_index=0 if direct_selected else source_index,
        )
        group_specs.append(
            {
                "reading_reports": str(group_root / "finalized-report-set.json"),
                "dossier": str(group_root / "dossier.json"),
                "source_bundle": bundle,
                "source_artifact": source,
                "verification_root": str(verification_root),
            }
        )
    collection = READING_COLLECTION_MODULE.build_collection(list(reversed(group_specs)))
    return {
        "network": network,
        "prioritized": prioritized,
        "selection": selection,
        "selected": selected,
        "subject": subject,
        "results": results,
        "review_set": review_set,
        "collection": collection,
    }


def rehash_patch_v3(patch):
    for action in patch["actions"]:
        for row in action["reviewed_evidence"]:
            row["basis_digest"] = _sha_without(row, {"basis_id", "basis_digest"})
            row["basis_id"] = "network-patch-basis-" + row["basis_digest"][:16]
        target = action.get("target_claim")
        if target is not None:
            target["report_claim_refs"] = []
            for row in action["reviewed_evidence"]:
                matching_groups = [
                    group_ref
                    for group_ref in action["reading_group_refs"]
                    if group_ref["source_id"] == row["source_id"]
                    and group_ref["report_set_id"] == row["report_set_id"]
                    and group_ref["report_set_digest"] == row["report_set_digest"]
                ]
                reading_group_id = (
                    matching_groups[0]["reading_group_id"]
                    if len(matching_groups) == 1
                    else action["reading_group_refs"][0]["reading_group_id"]
                )
                target["report_claim_refs"].append(
                    {
                        "basis_id": row["basis_id"],
                        "basis_digest": row["basis_digest"],
                        "reading_group_id": reading_group_id,
                        "claim_id": row["claim_id"],
                        "claim_digest": row["claim_digest"],
                        "reading_report_id": row["reading_report_id"],
                        "reading_report_digest": row["reading_report_digest"],
                    }
                )
            target["scope_digest"] = sha256_json(target["scope"])
            target["target_claim_digest"] = _sha_without(
                target, {"claim_id", "target_claim_digest"}
            )
            target["claim_id"] = "claim-target-" + target["target_claim_digest"][:16]
        action["action_digest"] = _sha_without(action, {"action_id", "action_digest"})
        action["action_id"] = "network-patch-action-" + action["action_digest"][:16]
    patch["proposal_digest"] = _sha_without(patch, {"proposal_id", "proposal_digest"})
    patch["proposal_id"] = "network-patch-proposal-" + patch["proposal_digest"][:16]
    return patch


def rehash_patch_v4_identity(patch):
    for action in patch["actions"]:
        action["action_digest"] = _sha_without(action, {"action_id", "action_digest"})
        action["action_id"] = "network-patch-action-" + action["action_digest"][:16]
    patch["proposal_digest"] = _sha_without(patch, {"proposal_id", "proposal_digest"})
    patch["proposal_id"] = "network-patch-proposal-" + patch["proposal_digest"][:16]
    return patch


class NetworkGapDiscoveryTest(unittest.TestCase):
    def test_paper_understanding_gap_accepts_exact_six_gap_types(self):
        for gap_type in PAPER_UNDERSTANDING_GAP_TO_PROJECTION:
            with self.subTest(gap_type=gap_type):
                gap = paper_understanding_gap_fixture(gap_type)
                self.assertIs(validate_paper_understanding_gap(gap), gap)

    def test_paper_understanding_gap_rejects_wrong_projection_and_tampering(self):
        mismatch = paper_understanding_gap_fixture("missing_input_format")
        mismatch["projection_type"] = "math"
        mismatch["gap_digest"] = canonical_paper_understanding_gap_digest(mismatch)
        mismatch["gap_id"] = f"understanding-gap-{mismatch['gap_digest'][:16]}"
        with self.assertRaisesRegex(ContractError, "incompatible"):
            validate_paper_understanding_gap(mismatch)

        tampered = paper_understanding_gap_fixture("missing_derivation_step")
        tampered["question"] = "A different unresolved question"
        with self.assertRaisesRegex(ContractError, "gap_digest"):
            validate_paper_understanding_gap(tampered)

    def test_paper_understanding_gap_rejects_cross_domain_fields_and_unbound_basis(
        self,
    ):
        cross_domain = paper_understanding_gap_fixture("missing_data_flow")
        cross_domain["missing_field"] = "conclusion.invented"
        cross_domain["provenance"]["basis_refs"][0]["source_path"] = (
            "conclusion.invented"
        )
        cross_domain["gap_digest"] = canonical_paper_understanding_gap_digest(
            cross_domain
        )
        cross_domain["gap_id"] = f"understanding-gap-{cross_domain['gap_digest'][:16]}"
        with self.assertRaisesRegex(ContractError, "field prefix"):
            validate_paper_understanding_gap(cross_domain)

        unbound = paper_understanding_gap_fixture("missing_derivation_step")
        unbound["provenance"]["basis_refs"][0]["source_path"] = (
            "mathematical_principles.principles[0].derivation_steps[0]"
        )
        unbound["gap_digest"] = canonical_paper_understanding_gap_digest(unbound)
        unbound["gap_id"] = f"understanding-gap-{unbound['gap_digest'][:16]}"
        with self.assertRaisesRegex(ContractError, "bind missing_field"):
            validate_paper_understanding_gap(unbound)

    def test_paper_understanding_gap_rejects_private_query_material(self):
        for unsafe in (
            "/private/user/paper.pdf",
            "Zotero key ABCD1234",
            "github_pat_secretvalue",
            "gap:INTERNAL-1",
        ):
            with self.subTest(unsafe=unsafe):
                gap = paper_understanding_gap_fixture("missing_conclusion_scope")
                gap["search_terms"]["must"] = [unsafe]
                gap["gap_digest"] = canonical_paper_understanding_gap_digest(gap)
                gap["gap_id"] = f"understanding-gap-{gap['gap_digest'][:16]}"
                with self.assertRaisesRegex(
                    ContractError, "secrets, private paths, or keys|internal IDs"
                ):
                    validate_paper_understanding_gap(gap)

    def test_paper_understanding_gap_requires_validated_opaque_provenance(self):
        invalid = paper_understanding_gap_fixture("missing_conclusion_scope")
        invalid["provenance"]["understanding_binding"].pop("validation_record_digest")
        invalid["gap_digest"] = canonical_paper_understanding_gap_digest(invalid)
        invalid["gap_id"] = f"understanding-gap-{invalid['gap_digest'][:16]}"
        with self.assertRaisesRegex(ContractError, "validation_record_digest"):
            validate_paper_understanding_gap(invalid)

        novelty = paper_understanding_gap_fixture("missing_algorithm_detail")
        novelty["novelty_claimed"] = True
        novelty["gap_digest"] = canonical_paper_understanding_gap_digest(novelty)
        novelty["gap_id"] = f"understanding-gap-{novelty['gap_digest'][:16]}"
        with self.assertRaisesRegex(ContractError, "novelty_claimed"):
            validate_paper_understanding_gap(novelty)

    def test_paper_understanding_gap_rejects_rehashed_arbitrary_upstream_ids(self):
        mutations = (
            (
                ("understanding_binding", "understanding_id"),
                "paper-understanding-arbitrary",
                "understanding_id does not match",
            ),
            (
                ("understanding_binding", "validation_record_id"),
                "paper-understanding-validation-arbitrary",
                "validation_record_id does not match",
            ),
            (
                ("projection_ref", "projection_id"),
                "understanding-projection-arbitrary",
                "projection_id does not match",
            ),
        )
        for (container, field), value, message in mutations:
            with self.subTest(field=field):
                gap = paper_understanding_gap_fixture("missing_data_flow")
                gap["provenance"][container][field] = value
                gap["gap_digest"] = canonical_paper_understanding_gap_digest(gap)
                gap["gap_id"] = f"understanding-gap-{gap['gap_digest'][:16]}"
                with self.assertRaisesRegex(ContractError, message):
                    validate_paper_understanding_gap(gap)

    def test_accepts_canonical_learn_from_papers_report_set_example(self):
        example = (
            Path(__file__).resolve().parents[2]
            / "learn-from-papers"
            / "examples"
            / "paper_reading_report_set.example.json"
        )
        value = json.loads(example.read_text(encoding="utf-8"))
        validated = validate_paper_reading_report_set(value)
        self.assertEqual(validated["schema"], "PaperReadingReportSet/v1")
        self.assertEqual(validated["producer"], "learn-from-papers")

    def test_network_ref_uses_export_content_sha256_without_self_reference(self):
        network = network_fixture()
        reference = network_ref(network)
        self.assertEqual(reference["sha256"], network["content_sha256"])
        self.assertNotEqual(reference["sha256"], sha256_json(network))

        tampered = copy.deepcopy(network)
        tampered["gaps"].append(
            {"gap_id": "GAP-TAMPERED", "status": "open", "reason": "tampered"}
        )
        with self.assertRaisesRegex(ContractError, "content_sha256"):
            scan_network(tampered)

    def test_scan_marks_isolate_as_candidate_not_negative(self):
        probe = scan_network(network_fixture())
        self.assertEqual(probe["topological_isolates"], ["entity:C"])
        signal = next(
            item
            for item in probe["candidate_signals"]
            if item["kind"] == "topological_isolate"
        )
        self.assertEqual(signal["classification"], "implicit_candidate_signal")
        self.assertFalse(probe["novelty_claimed"])

    def test_scan_preserves_declared_gap_and_unmet_gate(self):
        probe = scan_network(network_fixture())
        self.assertEqual(probe["existing_open_gap_ids"], ["GAP-EXPLICIT"])
        self.assertEqual(probe["unmet_completion_gates"], ["conflicts_terminal"])

    def test_generate_hypotheses_deterministic(self):
        network = network_fixture()
        probe = scan_network(network)
        first = generate_hypotheses_from_probe(probe, network)
        second = generate_hypotheses_from_probe(probe, network)
        self.assertEqual(first["hypotheses"], second["hypotheses"])
        self.assertEqual(first["hypotheses"][0]["hypothesis_id"], "KGH-001")

    def test_doe_noise_fixture_is_bounded_deduplicated_and_explicit_first(self):
        network = doe_surrogate_noise_network_fixture()
        probe = scan_network(network)
        policy = probe["candidate_signal_policy"]
        summary = probe["candidate_signal_summary"]
        self.assertLessEqual(len(probe["candidate_signals"]), policy["max_total"])
        self.assertGreater(summary["suppressed_count"], 0)
        self.assertLessEqual(
            summary["selected_by_tier"].get("single_source", 0),
            policy["tier_budgets"]["single_source"],
        )
        self.assertLessEqual(
            summary["selected_by_tier"].get("isolate", 0),
            policy["tier_budgets"]["isolate"],
        )
        dedupe_keys = [item["dedupe_key"] for item in probe["candidate_signals"]]
        self.assertEqual(len(dedupe_keys), len(set(dedupe_keys)))

        hypotheses = generate_hypotheses_from_probe(probe, network, "DOE-ROUND")
        self.assertLessEqual(
            len(hypotheses["hypotheses"]), hypotheses["candidate_budget"]["max_total"]
        )
        prioritized = prioritize(hypotheses, network)
        explicit = prioritized["hypotheses"][:3]
        self.assertTrue(
            all(
                item["source_signal_tier"] == "explicit_high_impact"
                for item in explicit
            )
        )
        self.assertEqual(
            {item["grounds"][0]["ref_id"] for item in explicit},
            {
                "gap:morphology_specific_benchmark",
                "gap:stopping_and_calibration",
                "gap:batch_pending_failures",
            },
        )
        first_single_source = next(
            item
            for item in prioritized["hypotheses"]
            if item["source_signal_tier"] == "single_source"
        )
        self.assertTrue(
            all(
                item["priority_score"] > first_single_source["priority_score"]
                for item in explicit
            )
        )

    def test_claim_gap_uses_claim_node_text_instead_of_internal_id(self):
        network = doe_surrogate_noise_network_fixture(
            single_source_count=1, isolate_count=0
        )
        claim_id = "DOE-000"
        claim_node = next(
            node for node in network["nodes"] if node["node_id"] == f"claim:{claim_id}"
        )
        claim_node["label"] = (
            "Adaptive maximin sampling reduces surrogate error only for smooth "
            "deterministic responses"
        )
        claim_gap = next(
            gap for gap in network["gaps"] if gap.get("claim_id") == claim_id
        )
        previous_gap_id = claim_gap["gap_id"]
        claim_gap.update(
            {
                "gap_id": f"derived:unsupported-high-impact:{claim_id}",
                "gap_type": "explicit",
                "derivation_rule": "unsupported_high_impact",
                "impact": "high",
                "description": f"No decisive evidence for high-impact claim {claim_id}",
            }
        )
        network["completion"]["open_gap_ids"] = [
            claim_gap["gap_id"] if gap_id == previous_gap_id else gap_id
            for gap_id in network["completion"]["open_gap_ids"]
        ]
        attach_network_content_sha256(network)

        hypotheses = generate_hypotheses_from_probe(scan_network(network), network)
        prioritized = prioritize(hypotheses, network)
        hypothesis = next(
            item
            for item in prioritized["hypotheses"]
            if item["grounds"][0]["ref_id"] == claim_gap["gap_id"]
        )
        self.assertEqual(hypothesis["status"], "selected")
        self.assertEqual(hypothesis["source_signal_tier"], "explicit_high_impact")
        self.assertEqual(hypothesis["decision_impact"], "high")
        self.assertEqual(hypothesis["semantic_label"], claim_node["label"])
        human_search = json.dumps(
            {
                "semantic_label": hypothesis["semantic_label"],
                "hypothesis": hypothesis["hypothesis"],
                "target_signature": hypothesis["target_signature"],
                "search_test": hypothesis["search_test"],
            }
        ).lower()
        self.assertNotIn(claim_id.lower(), human_search)
        self.assertNotIn("decisive high-impact claim", human_search)
        self.assertIn("adaptive", human_search)
        self.assertIn("surrogate", human_search)

        request_set = emit_search_requests(prioritized, network)
        request = next(
            item
            for item in request_set["requests"]
            if item["gap_hypothesis_id"] == hypothesis["hypothesis_id"]
        )
        request_search = json.dumps(
            {
                "paper_need": request["paper_need"],
                "criteria": request["criteria"],
                "query_seeds": request["query_seeds"],
            }
        ).lower()
        self.assertNotIn(claim_id.lower(), request_search)
        self.assertIn("adaptive", request_search)

    def test_same_claim_gap_dedup_preserves_every_origin_as_ordered_ground(self):
        network = doe_surrogate_noise_network_fixture(
            single_source_count=1, isolate_count=0
        )
        single_source_gap = next(
            gap for gap in network["gaps"] if gap.get("claim_id") == "DOE-000"
        )
        unsupported_gap = {
            "gap_id": "derived:unsupported-high-impact:DOE-000",
            "gap_type": "explicit",
            "status": "open",
            "impact": "high",
            "claim_id": "DOE-000",
            "derivation_rule": "unsupported_high_impact",
            "description": "Claim DOE-000 lacks required decisive coverage",
        }
        network["gaps"].append(unsupported_gap)
        network["completion"]["open_gap_ids"].append(unsupported_gap["gap_id"])
        attach_network_content_sha256(network)

        probe = scan_network(network)
        claim_signals = [
            signal
            for signal in probe["candidate_signals"]
            if signal.get("dedupe_key") == "claim:DOE-000"
        ]
        self.assertEqual(len(claim_signals), 1)
        self.assertEqual(
            claim_signals[0]["refs"],
            [single_source_gap["gap_id"], unsupported_gap["gap_id"]],
        )
        self.assertEqual(claim_signals[0]["tier"], "explicit_high_impact")

        hypotheses = generate_hypotheses_from_probe(probe, network, "DUAL-GAP")
        hypothesis = next(
            item
            for item in hypotheses["hypotheses"]
            if item["source_signal_tier"] == "explicit_high_impact"
            and item["semantic_label"] == "DoE reviewed claim 000"
        )
        self.assertEqual(
            [ground["ref_id"] for ground in hypothesis["grounds"]],
            [single_source_gap["gap_id"], unsupported_gap["gap_id"]],
        )
        self.assertFalse(hypothesis["structural_only"])
        self.assertEqual(hypothesis["next_action"], "scholar_discovery")
        self.assertEqual(hypothesis["decision_impact"], "high")

        mixed_subject_probe = copy.deepcopy(probe)
        mixed_signal = next(
            signal
            for signal in mixed_subject_probe["candidate_signals"]
            if signal.get("dedupe_key") == "claim:DOE-000"
        )
        mixed_signal["refs"].append("gap:morphology_specific_benchmark")
        with self.assertRaisesRegex(ContractError, "share one semantic subject"):
            generate_hypotheses_from_probe(mixed_subject_probe, network, "MIXED-GAP")

    def test_cross_family_dedup_does_not_inject_isolate_ref_into_gap_grounds(self):
        network = doe_surrogate_noise_network_fixture(
            single_source_count=0, isolate_count=1
        )
        unsupported_gap = {
            "gap_id": "derived:unsupported-high-impact:ISOLATE-000",
            "gap_type": "explicit",
            "status": "open",
            "impact": "high",
            "claim_id": "ISOLATE-000",
            "derivation_rule": "unsupported_high_impact",
            "description": "Claim ISOLATE-000 lacks required decisive coverage",
        }
        network["gaps"].append(unsupported_gap)
        network["completion"]["open_gap_ids"].append(unsupported_gap["gap_id"])
        attach_network_content_sha256(network)

        probe = scan_network(network)
        claim_signals = [
            signal
            for signal in probe["candidate_signals"]
            if signal.get("dedupe_key") == "claim:ISOLATE-000"
        ]
        self.assertEqual(len(claim_signals), 1)
        self.assertEqual(claim_signals[0]["kind"], "explicit_open_gap")
        self.assertEqual(claim_signals[0]["refs"], [unsupported_gap["gap_id"]])

        hypotheses = generate_hypotheses_from_probe(probe, network, "CROSS-FAMILY-GAP")
        hypothesis = next(
            item
            for item in hypotheses["hypotheses"]
            if item["semantic_label"] == "Unconnected DoE boundary 000"
        )
        self.assertEqual(
            [ground["ref_id"] for ground in hypothesis["grounds"]],
            [unsupported_gap["gap_id"]],
        )
        self.assertEqual(hypothesis["source_signal_tier"], "explicit_high_impact")
        self.assertFalse(hypothesis["structural_only"])

    def test_gap_signal_tier_rejects_conflicting_derived_family_markers(self):
        cases = [
            (
                "rule-only unsupported high impact",
                {
                    "gap_id": "GAP-CLAIM",
                    "derivation_rule": "unsupported_high_impact",
                    "gap_type": "explicit",
                    "claim_id": "CLAIM-1",
                },
                "explicit_high_impact",
            ),
            (
                "prefix-only unsupported high impact",
                {
                    "gap_id": "derived:unsupported-high-impact:CLAIM-1",
                    "gap_type": "explicit",
                    "claim_id": "CLAIM-1",
                },
                "explicit_high_impact",
            ),
            (
                "ordinary claim-backed explicit",
                {
                    "gap_id": "GAP-CLAIM",
                    "gap_type": "explicit",
                    "claim_id": "CLAIM-1",
                },
                "explicit",
            ),
            (
                "ordinary single source",
                {
                    "gap_id": "derived:single-source:CLAIM-1",
                    "derivation_rule": "single_independent_source",
                    "gap_type": "deterministic_structural",
                    "claim_id": "CLAIM-1",
                },
                "single_source",
            ),
        ]
        for label, gap, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(discovery._gap_signal_tier(gap), expected)

        conflict = {
            "gap_id": "derived:unsupported-high-impact:CLAIM-1",
            "derivation_rule": "single_independent_source",
            "gap_type": "explicit",
            "claim_id": "CLAIM-1",
        }
        with self.assertRaisesRegex(ContractError, "derived-family"):
            discovery._gap_signal_tier(conflict)

    def test_rejects_non_implicit_hypothesis(self):
        document = hypotheses_fixture()
        document["hypotheses"][0]["gap_type"] = "deterministic_structural"
        with self.assertRaises(ContractError):
            validate_hypotheses(document)

    def test_rejects_novelty_claim(self):
        document = hypotheses_fixture()
        document["hypotheses"][0]["novelty_claimed"] = True
        with self.assertRaises(ContractError):
            validate_hypotheses(document)

    def test_requires_confirm_and_refute(self):
        document = hypotheses_fixture()
        document["hypotheses"][0]["search_test"]["queries"][1]["objective"] = "confirm"
        with self.assertRaises(ContractError):
            validate_hypotheses(document)

    def test_long_semantic_query_preserves_gap_specific_refute_terms(self):
        terms = [
            "recursive estimation static deterministic parameter requires source-backed "
            "batch equivalence persistent excitation information growth initialization "
            "forgetting-factor consistency asymptotic efficiency divergence boundaries"
        ]

        confirm = discovery._build_semantic_search_query(terms, "confirm")
        refute = discovery._build_semantic_search_query(terms, "refute")

        self.assertLessEqual(len(confirm.split()), discovery.SEMANTIC_QUERY_MAX_WORDS)
        self.assertLessEqual(len(refute.split()), discovery.SEMANTIC_QUERY_MAX_WORDS)
        self.assertNotEqual(confirm, refute)
        for term in ("persistent", "excitation", "forgetting-factor", "divergence"):
            self.assertIn(term, refute.split())
        for generic_modifier in ("limitation", "counterexample", "null"):
            self.assertNotIn(generic_modifier, refute.split())

    def test_generated_topic_hypotheses_do_not_invent_title_seeds(self):
        network = semantic_gap_network_fixture()
        hypotheses = generate_hypotheses_from_probe(scan_network(network), network)

        searchable = [
            hypothesis
            for hypothesis in hypotheses["hypotheses"]
            if not hypothesis["structural_only"]
        ]

        self.assertTrue(searchable)
        self.assertTrue(
            all(
                hypothesis["search_test"]["seeds"]["titles"] == []
                for hypothesis in searchable
            )
        )
        for hypothesis in searchable:
            search_test = hypothesis["search_test"]
            refute_query = next(
                query["query"]
                for query in search_test["queries"]
                if query["objective"] == "refute"
            )
            self.assertIn(
                refute_query, search_test["expected_disconfirming_observation"]
            )
            self.assertTrue(
                set(search_test["criteria"]["must"]).isdisjoint(
                    discovery.GENERIC_QUERY_BOILERPLATE
                )
            )

    def test_long_semantic_label_is_preserved_as_paper_need(self):
        label = (
            "Recursive estimation of a static deterministic parameter requires "
            "persistent excitation, information growth, initialization, and "
            "explicit divergence boundaries."
        )

        self.assertEqual(
            discovery._semantic_paper_need(label, ["recursive", "estimation"]),
            label,
        )

    def test_rejects_internal_id_query_text(self):
        document = hypotheses_fixture()
        document["hypotheses"][0]["search_test"]["queries"][0]["query"] = (
            "relation:REL-AB evidence context"
        )
        with self.assertRaises(ContractError):
            validate_hypotheses(document)

    def test_rejects_snapshot_only_evidence_query(self):
        document = hypotheses_fixture()
        document["hypotheses"][0]["search_test"]["queries"][0]["query"] = (
            "No evidence for GAP-EXPLICIT at this snapshot"
        )
        with self.assertRaises(ContractError):
            validate_hypotheses(document)

    def test_structural_only_hypothesis_is_not_subject_to_confirm_refute_requirements(
        self,
    ):
        network = network_fixture()
        document = generate_hypotheses_from_probe(scan_network(network), network)
        structural_hypothesis = copy.deepcopy(
            next(item for item in document["hypotheses"] if item["structural_only"])
        )
        structural_hypothesis["search_test"]["queries"] = [
            {
                "objective": "confirm",
                "query": "completion gate remains structurally unmet",
            }
        ]
        document["hypotheses"] = [structural_hypothesis]
        validate_hypotheses(document, network)

    def test_needs_semantic_enrichment_hypothesis_is_not_subject_to_semantic_content_requirements(
        self,
    ):
        document = hypotheses_fixture()
        hypothesis = document["hypotheses"][0]
        hypothesis["status"] = "proposed"
        hypothesis["needs_semantic_enrichment"] = True
        hypothesis["search_test"]["queries"][0]["query"] = (
            "completion gate remains structurally unmet"
        )
        document["selection_summary"] = {
            "selected_count": 0,
            "selected_hypothesis_ids": [],
            "unselected_proposed_hypothesis_ids": [hypothesis["hypothesis_id"]],
        }
        validate_hypotheses(document)
        with self.assertRaisesRegex(ContractError, "zero selected hypotheses"):
            emit_search_requests(document, network_fixture())

    def test_rejects_unknown_reference(self):
        document = hypotheses_fixture(network_fixture())
        document["hypotheses"][0]["grounds"][0]["ref_id"] = "node:missing"
        with self.assertRaises(ContractError):
            validate_hypotheses(document, network_fixture())

    def test_high_impact_content_requires_independent_full_text(self):
        document = hypotheses_fixture()
        hypothesis = document["hypotheses"][0]
        hypothesis["status"] = "content_found"
        hypothesis["status_basis"] = [
            {
                "source_ref": "study-1",
                "locator": "paper-1",
                "hypothesis_id": "KGH-1",
                "independence_group": "study-1",
                "review_request_id": "RR-1",
                "review_request_digest": "f" * 64,
                "claim_support_eligible": True,
                "read_depth": "abstract",
            }
        ]
        with self.assertRaises(ContractError):
            validate_hypotheses(document)
        hypothesis["status_basis"] = [
            {
                "source_ref": "study-1",
                "locator": "paper-1",
                "hypothesis_id": "KGH-1",
                "independence_group": "study-1",
                "review_request_id": "RR-1",
                "review_request_digest": "f" * 64,
                "claim_support_eligible": True,
                "read_depth": "full_text",
            },
            {
                "source_ref": "study-2",
                "locator": "paper-2",
                "hypothesis_id": "KGH-1",
                "independence_group": "study-2",
                "review_request_id": "RR-2",
                "review_request_digest": "f" * 64,
                "claim_support_eligible": True,
                "read_depth": "evidence",
            },
        ]
        validate_hypotheses(document)

    def test_priority_is_transparent_and_deterministic(self):
        document = hypotheses_fixture()
        second = copy.deepcopy(document["hypotheses"][0])
        second["hypothesis_id"] = "KGH-2"
        second["decision_impact"] = "low"
        document["hypotheses"].append(second)
        first = prioritize(document)
        second_run = prioritize(copy.deepcopy(document))
        self.assertEqual(first, second_run)
        self.assertEqual(first["priority_order"], ["KGH-1", "KGH-2"])
        self.assertIn("decision_impact", first["hypotheses"][0]["priority_components"])

    def test_prioritize_status_matches_emitted_request_selection(self):
        network = network_fixture()
        document = hypotheses_fixture(network)
        structural = copy.deepcopy(document["hypotheses"][0])
        structural["hypothesis_id"] = "KGH-STRUCTURAL"
        structural["status"] = "proposed"
        structural["structural_only"] = True
        structural["next_action"] = "structural_only"
        document["hypotheses"].append(structural)

        prioritized = prioritize(document, network)
        request_set = emit_search_requests(prioritized, network)
        selected_ids = {
            item["hypothesis_id"]
            for item in prioritized["hypotheses"]
            if item["status"] == "selected"
        }
        emitted_ids = {item["gap_hypothesis_id"] for item in request_set["requests"]}
        self.assertEqual(selected_ids, emitted_ids)
        self.assertEqual(
            prioritized["selection_summary"]["selected_hypothesis_ids"],
            ["KGH-1"],
        )
        self.assertEqual(
            next(
                item
                for item in prioritized["hypotheses"]
                if item["hypothesis_id"] == "KGH-STRUCTURAL"
            )["status"],
            "proposed",
        )

    def test_emit_search_requests_emits_only_four_selected_from_twenty(self):
        network = network_fixture()
        document = hypotheses_fixture(network)
        template = document["hypotheses"][0]
        hypotheses = []
        selected_ids = []
        proposed_ids = []
        for index in range(20):
            hypothesis = copy.deepcopy(template)
            hypothesis_id = f"KGH-{index + 1:02d}"
            hypothesis["hypothesis_id"] = hypothesis_id
            hypothesis["status"] = "selected" if index < 4 else "proposed"
            if index == 19:
                hypothesis["structural_only"] = True
                hypothesis["next_action"] = "structural_only"
            hypotheses.append(hypothesis)
            (selected_ids if index < 4 else proposed_ids).append(hypothesis_id)
        document["hypotheses"] = hypotheses
        document["selection_summary"] = {
            "selected_count": 4,
            "selected_hypothesis_ids": selected_ids,
            "unselected_proposed_hypothesis_ids": proposed_ids,
        }

        request_set = emit_search_requests(document, network)

        self.assertEqual(
            [request["gap_hypothesis_id"] for request in request_set["requests"]],
            selected_ids,
        )

    def test_emit_search_requests_all_proposed_emits_empty_set(self):
        network = network_fixture()
        document = hypotheses_fixture(network)
        hypothesis = document["hypotheses"][0]
        hypothesis["status"] = "proposed"
        document["selection_summary"] = {
            "selected_count": 0,
            "selected_hypothesis_ids": [],
            "unselected_proposed_hypothesis_ids": [hypothesis["hypothesis_id"]],
        }

        with self.assertRaisesRegex(ContractError, "zero selected hypotheses"):
            emit_search_requests(document, network)

    def test_emit_search_requests_rejects_selection_summary_mismatch(self):
        network = network_fixture()
        for field, value, message in (
            ("selected_count", 0, "selected_count"),
            ("selected_hypothesis_ids", ["KGH-MISSING"], "selected_hypothesis_ids"),
            (
                "unselected_proposed_hypothesis_ids",
                ["KGH-1"],
                "unselected_proposed_hypothesis_ids",
            ),
        ):
            with self.subTest(field=field):
                document = hypotheses_fixture(network)
                document["selection_summary"][field] = value
                with self.assertRaisesRegex(ContractError, message):
                    emit_search_requests(document, network)

        missing = hypotheses_fixture(network)
        missing.pop("selection_summary")
        with self.assertRaisesRegex(ContractError, "selection_summary"):
            emit_search_requests(missing, network)

    def test_emit_search_requests_rejects_selected_structural_hypothesis(self):
        network = network_fixture()
        document = hypotheses_fixture(network)
        document["hypotheses"][0]["structural_only"] = True
        document["hypotheses"][0]["next_action"] = "structural_only"
        with self.assertRaisesRegex(ContractError, "non-structural"):
            emit_search_requests(document, network)

    def test_emit_search_requests_is_bounded_to_network_snapshot(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        request_set = emit_search_requests(hypotheses, network)
        self.assertEqual(request_set["schema"], "ScholarDiscoveryRequestSet/v1")
        self.assertEqual(request_set["schema_version"], "v1")
        self.assertEqual(request_set["network_id"], network_ref(network)["network_id"])
        self.assertEqual(
            request_set["network_snapshot_sha256"], network_ref(network)["sha256"]
        )
        stale_network = copy.deepcopy(network)
        stale_network["relations"].append(
            {
                "relation_id": "REL-STALE",
                "from_id": "entity:A",
                "to_id": "entity:B",
                "predicate": "contrasts_with",
                "status": "supported",
                "confidence": "high",
                "provenance": [{"source_id": "source:1", "locator": "p.2"}],
            }
        )
        attach_network_content_sha256(stale_network)
        with self.assertRaises(ContractError):
            emit_search_requests(hypotheses, stale_network)

    def test_request_set_rejects_duplicate_request_ids(self):
        network = network_fixture()
        request_set = emit_search_requests(hypotheses_fixture(network), network)
        duplicate_set = copy.deepcopy(request_set)
        duplicate_set["requests"] = [
            request_set["requests"][0],
            request_set["requests"][0],
        ]
        attach_request_set_digest(duplicate_set)
        with self.assertRaises(ContractError):
            validate_request_set(duplicate_set)

    def test_request_set_rejects_stale_snapshot(self):
        network = network_fixture()
        request_set = emit_search_requests(hypotheses_fixture(network), network)
        request_set["network_snapshot_sha256"] = "0" * 64
        with self.assertRaises(ContractError):
            validate_request_set(request_set, network=network)

    def test_request_set_rejects_missing_schema_version(self):
        network = network_fixture()
        request_set = emit_search_requests(hypotheses_fixture(network), network)
        del request_set["schema_version"]
        with self.assertRaises(ContractError):
            validate_request_set(request_set, network=network)

    def test_emits_scholar_request_without_automatic_google(self):
        request_set = emit_search_requests(hypotheses_fixture(), network_fixture())
        self.assertEqual(request_set["schema"], "ScholarDiscoveryRequestSet/v1")
        request = request_set["requests"][0]
        self.assertEqual(request["schema"], "ScholarDiscoveryRequest/v1")
        self.assertEqual(request["routes"]["google_scholar"], "manual_optional")
        self.assertNotIn("google_scholar", request["routes"]["automatic"])
        self.assertEqual(
            {item["objective"] for item in request["query_seeds"]},
            {"confirm", "refute"},
        )

    def test_emit_search_requests_respects_google_scholar_policy(self):
        network = network_fixture()
        request_set_default = emit_search_requests(hypotheses_fixture(network), network)
        request_set_required = emit_search_requests(
            hypotheses_fixture(network),
            network,
            google_scholar_policy="manual_required",
        )
        request_set_disabled = emit_search_requests(
            hypotheses_fixture(network),
            network,
            google_scholar_policy="disabled",
        )
        self.assertEqual(
            request_set_default["requests"][0]["routes"]["google_scholar"],
            "manual_optional",
        )
        self.assertEqual(
            request_set_required["requests"][0]["routes"]["google_scholar"],
            "manual_required",
        )
        self.assertEqual(
            request_set_disabled["requests"][0]["routes"]["google_scholar"],
            "disabled",
        )

    def test_structural_only_hypotheses_skip_search_requests_and_mark_no_signal(self):
        network = network_fixture()
        document = generate_hypotheses_from_probe(scan_network(network), network)
        structural_only = [
            hypothesis
            for hypothesis in document["hypotheses"]
            if hypothesis["structural_only"]
        ]
        self.assertTrue(structural_only)
        structural_doc = {
            "schema": document["schema"],
            "network_ref": document["network_ref"],
            "round_id": document["round_id"],
            "generated_at": document["generated_at"],
            "method_families": document["method_families"],
            "selection_summary": {
                "selected_count": 0,
                "selected_hypothesis_ids": [],
                "unselected_proposed_hypothesis_ids": [
                    hypothesis["hypothesis_id"] for hypothesis in structural_only
                ],
            },
            "hypotheses": structural_only,
        }
        with self.assertRaisesRegex(ContractError, "zero selected hypotheses"):
            emit_search_requests(structural_doc, network)
        self.assertEqual(
            structural_doc["hypotheses"][0]["next_action"], "structural_only"
        )
        self.assertEqual(structural_doc["hypotheses"][0]["status"], "proposed")

    def test_derived_missing_dimension_is_not_compiled_as_scholar_query(self):
        network = network_fixture()
        gap_id = "derived:missing-dimension:validation_target"
        network["gaps"] = [
            {
                "gap_id": gap_id,
                "gap_type": "deterministic_structural",
                "status": "open",
                "reason": "network dimension validation_target.",
            }
        ]
        network["completion"]["open_gap_ids"] = [gap_id]
        attach_network_content_sha256(network)

        document = generate_hypotheses_from_probe(scan_network(network), network)
        matching = [
            hypothesis
            for hypothesis in document["hypotheses"]
            if any(ground["ref_id"] == gap_id for ground in hypothesis["grounds"])
        ]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]["structural_only"])
        self.assertEqual(matching[0]["next_action"], "structural_only")

        structural_doc = {
            "schema": document["schema"],
            "network_ref": document["network_ref"],
            "round_id": document["round_id"],
            "generated_at": document["generated_at"],
            "method_families": document["method_families"],
            "selection_summary": {
                "selected_count": 0,
                "selected_hypothesis_ids": [],
                "unselected_proposed_hypothesis_ids": [
                    hypothesis["hypothesis_id"] for hypothesis in matching
                ],
            },
            "hypotheses": matching,
        }
        with self.assertRaisesRegex(ContractError, "zero selected hypotheses"):
            emit_search_requests(structural_doc, network)

    def test_generated_semantic_queries_are_id_free_and_topic_grounded(self):
        network = semantic_gap_network_fixture()
        hypotheses = prioritize(
            generate_hypotheses_from_probe(scan_network(network), network), network
        )
        non_wendy_scope = [
            hypothesis
            for hypothesis in hypotheses["hypotheses"]
            if "wendy" not in hypothesis["target_signature"].lower()
        ]
        explicit_gap_candidates = [
            hypothesis
            for hypothesis in hypotheses["hypotheses"]
            if "wendy" not in hypothesis["target_signature"].lower()
            and any(
                "sparse" in query["query"].lower()
                or "benchmark" in query["query"].lower()
                for query in hypothesis["search_test"]["queries"]
            )
        ]
        self.assertTrue(
            explicit_gap_candidates,
            "expected a non-WENDy relation/node hypothesis aligned with an explicit sparse gap",
        )
        explicit_gap = explicit_gap_candidates[0]
        wendy_scope = [
            hypothesis
            for hypothesis in hypotheses["hypotheses"]
            if hypothesis["target_kind"] in {"relation", "node"}
            and "wendy" in hypothesis["target_signature"].lower()
        ]
        all_query_text = " ".join(
            query["query"].lower()
            for hypothesis in hypotheses["hypotheses"]
            for query in hypothesis["search_test"]["queries"]
        )
        raw_queries = [
            query["query"]
            for hypothesis in hypotheses["hypotheses"]
            for query in hypothesis["search_test"]["queries"]
        ]
        explicit_queries = [
            query["query"] for query in explicit_gap["search_test"]["queries"]
        ]
        wendy_confirm_queries = [
            query["query"]
            for hypothesis in wendy_scope
            for query in hypothesis["search_test"]["queries"]
            if query["objective"] == "confirm"
        ]
        wendy_refute_queries = [
            query["query"]
            for hypothesis in wendy_scope
            for query in hypothesis["search_test"]["queries"]
            if query["objective"] == "refute"
        ]
        wendy_queries = [
            query["query"]
            for hypothesis in wendy_scope
            for query in hypothesis["search_test"]["queries"]
        ]
        non_wendy_queries = [
            query["query"]
            for hypothesis in non_wendy_scope
            for query in hypothesis["search_test"]["queries"]
        ]
        forbidden = [
            "gap:",
            "relation:",
            "node:",
            "unmet_declared_gate:",
            "completion.gate_checks.",
            "gap-",
            "rel-",
            "gaph-",
            "kgh-",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, all_query_text)
        for query in raw_queries:
            self.assertLessEqual(len(query.split()), 12, f"query too long: {query}")
            self.assertNotIn(
                "Which promised benchmark or locally complete slot is unresolved?",
                query,
            )
            self.assertNotIn("claims_property", query)
        self.assertNotRegex(
            all_query_text, r"\bno evidence for\b.*\bat this snapshot\b"
        )
        self.assertIn("sparse", all_query_text)
        self.assertIn("benchmark", all_query_text)
        self.assertTrue(
            wendy_scope,
            "expected at least one node/relation hypothesis to include WENDy scope",
        )
        self.assertTrue(
            all("wendy" in query.lower() for query in wendy_queries),
            "wendy-scoped hypotheses must keep wendy anchor",
        )
        self.assertTrue(wendy_confirm_queries, "expected WENDy scoped confirm query")
        self.assertTrue(wendy_refute_queries, "expected WENDy scoped refute query")
        self.assertTrue(
            all(
                "sindy" not in query.lower() and "lorenz" not in query.lower()
                for query in wendy_queries
            ),
            "WENDy scoped queries should not include unrelated SINDy/Lorenz terms",
        )
        self.assertTrue(
            all("WENDy" not in query for query in non_wendy_queries),
            "non-WENDy node/relation scopes should not inject WENDy",
        )
        explicit_payload = " ".join(explicit_queries).lower()
        explicit_ref = explicit_gap["grounds"][0]["ref_id"].lower()
        self.assertNotIn(explicit_ref, explicit_payload)
        self.assertNotIn("gap:" + explicit_ref, explicit_payload)
        self.assertTrue("sparse" in explicit_payload or "benchmark" in explicit_payload)
        for workflow_token in (
            " gap ",
            " open ",
            " explicit ",
            " missing ",
            " coverage ",
        ):
            self.assertNotIn(workflow_token, f" {explicit_payload} ")

    def test_generated_queries_and_target_signatures_avoid_signal_ids(self):
        network = {
            "schema": "KnowledgeNetwork/v1",
            "network_id": "KN-SEM",
            "snapshot_id": "KN-SEM-S1",
            "nodes": [],
            "relations": [],
            "gaps": [{"gap_id": "GAP-ID-SEM", "status": "open", "reason": ""}],
            "completion": {
                "status": "partial",
                "gate_checks": {"scope_complete": False},
            },
        }
        attach_network_content_sha256(network)
        hypotheses = generate_hypotheses_from_probe(scan_network(network), network)

        forbidden = (
            "gap:",
            "relation:",
            "node:",
            "unmet_declared_gate:",
            "completion.gate_checks.",
            "gap-",
            "rel-",
            "gaph-",
            "kgh-",
        )
        all_query_text = " ".join(
            query["query"].lower()
            for hypothesis in hypotheses["hypotheses"]
            for query in hypothesis["search_test"]["queries"]
        )
        all_signatures = " ".join(
            hypothesis["target_signature"].lower()
            for hypothesis in hypotheses["hypotheses"]
        )
        for marker in forbidden:
            self.assertNotIn(marker, all_query_text)
            self.assertNotIn(marker, all_signatures)
        for workflow_marker in ("explicit", "gap", "completion", "gate"):
            self.assertNotIn(workflow_marker, all_signatures)
        self.assertNotRegex(
            all_query_text,
            r"\b(?:gap|relation|node)-[a-z0-9][a-z0-9_-]*\b",
        )

    def test_unrelated_domain_query_does_not_inject_sparse_dynamics_terms(self):
        network = {
            "schema": "KnowledgeNetwork/v1",
            "network_id": "KN-MATERIALS",
            "snapshot_id": "KN-MATERIALS-S1",
            "research_context": {
                "domain_phrases": ["grain boundary mobility"],
                "search_terms": ["phase field microscopy"],
            },
            "nodes": [
                {
                    "node_id": "material:grain-boundary",
                    "label": "grain boundary mobility",
                    "search_terms": ["phase field microscopy"],
                }
            ],
            "relations": [],
            "gaps": [
                {
                    "gap_id": "ZXCV-9911-ABC",
                    "status": "open",
                    "reason": "uncertain mobility under thermal cycling",
                    "next_action": "find experimental validation",
                }
            ],
            "completion": {"status": "partial", "gate_checks": {}},
        }
        attach_network_content_sha256(network)
        hypotheses = generate_hypotheses_from_probe(scan_network(network), network)
        query_text = " ".join(
            query["query"].lower()
            for hypothesis in hypotheses["hypotheses"]
            for query in hypothesis["search_test"]["queries"]
        )
        self.assertNotIn("zxcv-9911-abc", query_text)
        for forbidden in ("wendy", "sindy", "lorenz", "sparse", "toy model"):
            self.assertNotIn(forbidden, query_text)
        self.assertIn("grain", query_text)
        self.assertIn("mobility", query_text)

    def test_single_request_compatibility_and_result_consumption(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        request_digest = sha256_json(request)

        output = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [
                        {
                            "candidate_id": "C1",
                            "screening": {"decision": "include"},
                            "access_level": "full_text",
                            "url": "https://example.org/candidate-1",
                        }
                    ],
                    request_digest=request_digest,
                )
            ],
        )
        self.assertEqual(output["hypotheses"][0]["status"], "results")
        self.assertEqual(output["hypotheses"][0]["status_basis"], [])
        self.assertEqual(output["hypotheses"][0]["next_action"], "learn_from_papers")

        self.assertIn("review_requests", output)
        review_set = output["review_requests"]
        self.assertTrue(review_set["requests"])
        self.assertEqual(len(review_set["requests"][0]["sources"]), 1)
        source = review_set["requests"][0]["sources"][0]
        self.assertTrue(source["discovery_only"])
        self.assertFalse(source["claim_support_eligible"])

    def test_generic_consume_rejects_display_only_v1_result_set(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        current = make_result_set(
            request_set,
            request,
            [
                {
                    "candidate_id": "V1-CANDIDATE",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/v1-display-only",
                }
            ],
            request_digest=sha256_json(request),
        )
        legacy = copy.deepcopy(current)
        legacy["schema"] = "ScholarDiscoveryResultSet/v1"
        del legacy["execution_authorization_ref"]

        with self.assertRaisesRegex(ContractError, "legacy display-only"):
            _consume_results(hypotheses, network, request_set, [legacy])
        self.assertEqual(hypotheses["hypotheses"][0]["status"], "selected")

    def test_consume_results_status_transitions(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        request_digest = sha256_json(request)

        output_no_signal = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [],
                    request_digest=request_digest,
                )
            ],
        )
        self.assertEqual(output_no_signal["hypotheses"][0]["status"], "no_signal")

        output_results = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [
                        {
                            "candidate_id": "M1",
                            "screening": {"decision": "maybe"},
                            "access_level": "evidence",
                            "url": "https://example.org/m1",
                        }
                    ],
                    request_digest=request_digest,
                )
            ],
        )
        self.assertEqual(output_results["hypotheses"][0]["status"], "results")

        output_content = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [
                        {
                            "candidate_id": "I1",
                            "screening": {"decision": "include"},
                            "access_level": "full_text",
                            "url": "https://example.org/i1",
                        }
                    ],
                    request_digest=request_digest,
                )
            ],
        )
        self.assertEqual(output_content["hypotheses"][0]["status"], "results")

        output_supported = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [
                        {
                            "candidate_id": "S1",
                            "screening": {"decision": "include"},
                            "access_level": "abstract",
                            "discovery_provenance": [{"provider": "openalex"}],
                            "url": "https://example.org/s1",
                        }
                    ],
                    request_digest=request_digest,
                )
            ],
        )
        self.assertEqual(output_supported["hypotheses"][0]["status"], "results")

        output_contested = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [
                        {
                            "candidate_id": "I1",
                            "screening": {"decision": "include"},
                            "access_level": "abstract",
                            "url": "https://example.org/i1b",
                        },
                        {
                            "candidate_id": "E1",
                            "screening": {"decision": "exclude"},
                            "access_level": "abstract",
                            "url": "https://example.org/e1",
                        },
                    ],
                    request_digest=request_digest,
                )
            ],
        )
        self.assertEqual(output_contested["hypotheses"][0]["status"], "results")

        awaiting_network = network_fixture()
        awaiting_hypotheses = hypotheses_fixture(awaiting_network)
        awaiting_hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        awaiting_requests = emit_search_requests(
            awaiting_hypotheses,
            awaiting_network,
            google_scholar_policy="manual_required",
        )
        output_awaiting = consume_results(
            awaiting_hypotheses,
            awaiting_network,
            awaiting_requests,
            [],
        )
        self.assertEqual(output_awaiting["hypotheses"][0]["status"], "awaiting")

        with self.assertRaises(ContractError):
            consume_results(
                hypotheses,
                network,
                request_set,
                [
                    make_result_set(
                        request_set,
                        request,
                        [
                            {
                                "candidate_id": "BAD",
                                "screening": {"decision": "include"},
                                "access_level": "full_text",
                                "url": "https://example.org/bad",
                            }
                        ],
                        request_digest="0" * 64,
                    )
                ],
            )

    def test_result_set_binding_to_request_set_and_network(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        request_digest = sha256_json(request)

        with self.assertRaises(ContractError):
            mismatched_set = {
                **request_set,
                "request_set_id": "request-set-WRONG",
            }
            consume_results(
                hypotheses,
                network,
                request_set,
                [
                    make_result_set(
                        mismatched_set,
                        request,
                        [],
                        request_digest=request_digest,
                    )
                ],
            )

        with self.assertRaises(ContractError):
            mismatched_set = {
                **request_set,
                "network_id": "0" * 16,
            }
            consume_results(
                hypotheses,
                network,
                request_set,
                [
                    make_result_set(
                        mismatched_set,
                        request,
                        [],
                        request_digest=request_digest,
                    )
                ],
            )

        with self.assertRaises(ContractError):
            mismatched_set = {
                **request_set,
                "network_snapshot_sha256": "0" * 64,
            }
            consume_results(
                hypotheses,
                network,
                request_set,
                [
                    make_result_set(
                        mismatched_set,
                        request,
                        [],
                        request_digest=request_digest,
                    )
                ],
            )

    def test_consume_results_marks_awaiting_for_provider_failure_and_unresolved_queries(
        self,
    ):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request_set_manual_required = emit_search_requests(
            hypotheses,
            network,
            google_scholar_policy="manual_required",
        )
        request = request_set["requests"][0]
        request_digest = sha256_json(request)
        request_manual_required = request_set_manual_required["requests"][0]
        request_manual_required_digest = sha256_json(request_manual_required)

        provider_failure = make_result_set(
            request_set,
            request,
            [],
            request_digest=request_digest,
            discovery_status="partial_provider",
        )
        awaiting_provider = consume_results(
            hypotheses, network, request_set, [provider_failure]
        )
        self.assertEqual(awaiting_provider["hypotheses"][0]["status"], "awaiting")
        self.assertEqual(
            awaiting_provider["hypotheses"][0]["next_action"], "scholar_discovery"
        )
        provider_failure_google = make_result_set(
            request_set_manual_required,
            request_manual_required,
            [],
            request_digest=request_manual_required_digest,
            discovery_status="blocked_capability",
        )
        awaiting_provider_google = consume_results(
            hypotheses,
            network,
            request_set_manual_required,
            [provider_failure_google],
        )
        self.assertEqual(
            awaiting_provider_google["hypotheses"][0]["status"], "awaiting"
        )
        self.assertEqual(
            awaiting_provider_google["hypotheses"][0]["next_action"],
            "manual_scholar_export",
        )

        unresolved = make_result_set(
            request_set_manual_required,
            request_manual_required,
            [],
            request_digest=request_manual_required_digest,
            discovery_status="blocked_capability",
        )
        awaiting_unresolved = consume_results(
            hypotheses,
            network,
            request_set_manual_required,
            [unresolved],
        )
        self.assertEqual(awaiting_unresolved["hypotheses"][0]["status"], "awaiting")
        self.assertEqual(
            awaiting_unresolved["hypotheses"][0]["next_action"], "manual_scholar_export"
        )
        self.assertEqual(
            awaiting_unresolved["cycle_state"]["pending_reason"], "manual_required"
        )
        self.assertEqual(
            awaiting_unresolved["cycle_state"]["stop_reason"], "manual_required"
        )

        unresolved_without_manual = emit_search_requests(
            hypotheses,
            network,
            google_scholar_policy="manual_required",
        )
        unresolved_without_manual_request = unresolved_without_manual["requests"][0]
        unresolved_without_manual_request_digest = sha256_json(
            unresolved_without_manual_request
        )
        unresolved_without_manual_result_set = make_result_set(
            unresolved_without_manual,
            unresolved_without_manual_request,
            [],
            request_digest=unresolved_without_manual_request_digest,
            discovery_status="partial_provider",
        )
        awaiting_unresolved_non_manual = consume_results(
            hypotheses,
            network,
            unresolved_without_manual,
            [unresolved_without_manual_result_set],
        )
        self.assertEqual(
            awaiting_unresolved_non_manual["hypotheses"][0]["status"], "awaiting"
        )
        self.assertEqual(
            awaiting_unresolved_non_manual["hypotheses"][0]["next_action"],
            "scholar_discovery",
        )
        self.assertEqual(
            awaiting_unresolved_non_manual["cycle_state"]["pending_reason"],
            "provider_pending",
        )

        for discovery_status in (
            "partial_provider",
            "partial_budget",
            "blocked_capability",
            "pending",
        ):
            is_blocked_capability = discovery_status == "blocked_capability"
            partial_request_set = (
                request_set_manual_required if is_blocked_capability else request_set
            )
            partial_request = (
                request_manual_required if is_blocked_capability else request
            )
            partial_request_digest = (
                request_manual_required_digest
                if is_blocked_capability
                else request_digest
            )
            partial = make_result_set(
                partial_request_set,
                partial_request,
                [],
                request_digest=partial_request_digest,
                discovery_status=discovery_status,
            )
            awaiter = consume_results(
                hypotheses,
                network,
                partial_request_set,
                [partial],
            )
            self.assertEqual(awaiter["hypotheses"][0]["status"], "awaiting")
            if discovery_status == "blocked_capability":
                self.assertEqual(
                    awaiter["hypotheses"][0]["next_action"],
                    "manual_scholar_export",
                )
                self.assertEqual(
                    awaiter["cycle_state"]["pending_reason"], "manual_required"
                )
            else:
                self.assertEqual(
                    awaiter["hypotheses"][0]["next_action"],
                    "scholar_discovery",
                )

    def test_partial_provider_with_ranked_candidates_still_generates_review_request(
        self,
    ):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        request_digest = sha256_json(request)
        partial_with_candidates = make_result_set(
            request_set,
            request,
            [
                {
                    "candidate_id": "C1",
                    "screening": {"decision": "include"},
                    "access_level": "evidence",
                    "url": "https://example.org/partial-provider",
                }
            ],
            request_digest=request_digest,
            discovery_status="partial_provider",
        )
        output = consume_results(
            hypotheses,
            network,
            request_set,
            [partial_with_candidates],
        )
        self.assertEqual(output["hypotheses"][0]["status"], "results")
        self.assertEqual(output["hypotheses"][0]["next_action"], "learn_from_papers")
        self.assertIn("review_requests", output)
        self.assertEqual(len(output["review_requests"]["requests"]), 1)
        self.assertEqual(output["cycle_state"]["phase"], "review_and_retry")
        self.assertEqual(output["cycle_state"]["pending_reason"], "provider_pending")

    def test_consume_results_no_saturation_when_pending(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        request_digest = sha256_json(request)

        def build_awaiting_result() -> dict:
            result = make_result_set(
                request_set,
                request,
                [],
                request_digest=request_digest,
                discovery_status="partial_provider",
            )
            return result

        first = consume_results(
            hypotheses,
            network,
            request_set,
            [build_awaiting_result()],
        )
        second = consume_results(
            first,
            network,
            request_set,
            [build_awaiting_result()],
        )
        third = consume_results(
            second,
            network,
            request_set,
            [build_awaiting_result()],
        )
        self.assertFalse(third["cycle_state"]["saturation"])
        self.assertNotEqual(third["cycle_state"]["stop_reason"], "saturated")

    def test_consume_results_collects_sources_from_nested_scholar_result_fields(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        request_digest = sha256_json(request)

        result = make_result_set(
            request_set,
            request,
            [
                {
                    "candidate_id": "S1",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "identifiers": {
                        "doi": "10.1000/example-doi",
                        "arxiv": "arXiv:2501.01010",
                        "pmid": "987654321",
                        "openalex": "W123456789",
                    },
                    "manifestations": [
                        {"landing_url": "https://example.org/landing/s1"},
                    ],
                    "title": "Nested Scholar Source",
                },
                {
                    "candidate_id": "S2",
                    "screening": {"decision": "include"},
                    "access_level": "evidence",
                    "identifiers": {"openalex": "W987654321"},
                    "manifestations": [
                        {"landing_url": "https://example.org/landing/s2"},
                    ],
                    "title": "Fallback to OpenAlex",
                },
            ],
            request_digest=request_digest,
        )
        output = consume_results(
            hypotheses,
            network,
            request_set,
            [result],
        )
        review_set = output["review_requests"]
        self.assertEqual(len(review_set["requests"][0]["sources"]), 2)
        first_source = review_set["requests"][0]["sources"][0]
        second_source = review_set["requests"][0]["sources"][1]

        self.assertEqual(first_source["exact_locator"], "10.1000/example-doi")
        self.assertEqual(first_source["doi"], "10.1000/example-doi")
        self.assertEqual(first_source["url"], "https://example.org/landing/s1")
        self.assertEqual(first_source["query_seed_position"], 0)
        self.assertTrue(first_source["discovery_only"])

        self.assertEqual(second_source["exact_locator"], "W987654321")
        self.assertEqual(second_source["url"], "https://example.org/landing/s2")
        self.assertEqual(second_source["query_seed_position"], 1)

    def test_consume_results_saturates_after_two_no_progress_rounds(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = with_request_set_max_rounds(
            emit_search_requests(hypotheses, network), 5
        )
        request = request_set["requests"][0]
        request_digest = sha256_json(request_set["requests"][0])

        first = consume_results(
            hypotheses,
            network,
            request_set,
            [make_result_set(request_set, request, [], request_digest=request_digest)],
        )
        self.assertFalse(first["cycle_state"]["saturation"])

        second = consume_results(
            first,
            network,
            request_set,
            [make_result_set(request_set, request, [], request_digest=request_digest)],
        )
        self.assertFalse(second["cycle_state"]["saturation"])
        self.assertEqual(second["cycle_state"]["consecutive_no_progress_rounds"], 1)

        third = consume_results(
            second,
            network,
            request_set,
            [make_result_set(request_set, request, [], request_digest=request_digest)],
        )
        self.assertTrue(third["cycle_state"]["saturation"])
        self.assertEqual(third["cycle_state"]["consecutive_no_progress_rounds"], 2)
        self.assertEqual(third["cycle_state"]["stop_reason"], "saturated")

    def test_consume_results_stops_when_budget_exhausted(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = with_request_set_max_rounds(
            emit_search_requests(hypotheses, network), 2
        )
        request = request_set["requests"][0]
        request_digest = sha256_json(request_set["requests"][0])

        first = consume_results(
            hypotheses,
            network,
            request_set,
            [make_result_set(request_set, request, [], request_digest=request_digest)],
        )
        self.assertFalse(first["cycle_state"]["saturation"])

        second = consume_results(
            first,
            network,
            request_set,
            [make_result_set(request_set, request, [], request_digest=request_digest)],
        )
        self.assertFalse(second["cycle_state"]["saturation"])
        self.assertEqual(second["cycle_state"]["stop_reason"], "budget_exhausted")

    def test_saturation_skips_manual_pending(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(
            hypotheses,
            network,
            google_scholar_policy="manual_required",
        )

        awaiting = consume_results(
            hypotheses,
            network,
            request_set,
            [],
        )
        self.assertFalse(awaiting["cycle_state"]["saturation"])
        self.assertEqual(awaiting["hypotheses"][0]["status"], "awaiting")

        awaiting = consume_results(
            awaiting,
            network,
            request_set,
            [],
        )
        self.assertFalse(awaiting["cycle_state"]["saturation"])
        self.assertEqual(awaiting["hypotheses"][0]["status"], "awaiting")

    def test_patch_cannot_authorize_merge(self):
        network = network_fixture()
        patch = {
            "schema": "NetworkPatchProposal/v1",
            "proposal_id": "NPP-1",
            "network_ref": network_ref(network),
            "generated_at": "2026-08-05T00:30:00Z",
            "basis_gap_ids": ["KGH-1"],
            "proposal_only": True,
            "novelty_claimed": False,
            "nodes": [],
            "relations": [],
            "evidence": [],
            "review_gate": "pending_research_knowledge_network_validation",
            "auto_merge": True,
        }
        with self.assertRaises(ContractError):
            validate_patch(patch, network)
        patch["auto_merge"] = False
        validate_patch(patch, network)

    def test_current_producer_is_rejected_without_reopenable_attestation(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        results = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [reviewed_candidate_fixture()],
                    request_digest=sha256_json(request),
                )
            ],
        )
        review_set = results["review_requests"]
        review_request = review_set["requests"][0]
        with tempfile.TemporaryDirectory() as directory:
            report_set, dossier, bundle, source = real_producer_projection(
                Path(directory), review_set, review_request, network
            )
            self.assertEqual(report_set["source_ref"], "actual-paper.txt")
            self.assertNotEqual(
                report_set["source_ref"], review_request["sources"][0]["source_ref"]
            )
            with self.assertRaisesRegex(ContractError, "external attestation"):
                consume_reviewed_evidence(
                    results,
                    network,
                    review_set,
                    report_set,
                    dossier,
                    source_bundle_path=bundle,
                    source_artifact_path=source,
                    verification_root=directory,
                )

    def test_prepare_attestations_cannot_self_certify_independent_review(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        results = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [reviewed_candidate_fixture()],
                    request_digest=sha256_json(request),
                )
            ],
        )
        review_set = results["review_requests"]
        review_request = review_set["requests"][0]
        for verifier_id in ("producer_self", "generated", "learn-from-papers"):
            with self.subTest(verifier_id=verifier_id):
                with tempfile.TemporaryDirectory() as directory:
                    report_set, dossier, bundle, source = real_producer_projection(
                        Path(directory),
                        review_set,
                        review_request,
                        network,
                        verification_root=directory,
                        verifier_id=verifier_id,
                    )
                    with self.assertRaisesRegex(ContractError, "not independent"):
                        consume_reviewed_evidence(
                            results,
                            network,
                            review_set,
                            report_set,
                            dossier,
                            source_bundle_path=bundle,
                            source_artifact_path=source,
                            verification_root=directory,
                        )

    def test_self_consistent_forged_report_fails_dossier_reprojection(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        results = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [reviewed_candidate_fixture()],
                    request_digest=sha256_json(request),
                )
            ],
        )
        review_set = results["review_requests"]
        review_request = review_set["requests"][0]
        with tempfile.TemporaryDirectory() as directory:
            report_set, dossier, bundle, source = real_producer_projection(
                Path(directory),
                review_set,
                review_request,
                network,
                verification_root=directory,
            )
            forged = copy.deepcopy(report_set)
            forged["reports"][0]["claim_statement"] = "forged semantic claim"
            _rehash_v2_report_set(forged)
            with self.assertRaisesRegex(ContractError, "subject_digest"):
                consume_reviewed_evidence(
                    results,
                    network,
                    review_set,
                    forged,
                    dossier,
                    source_bundle_path=bundle,
                    source_artifact_path=source,
                    verification_root=directory,
                )

    def test_real_three_stage_producer_to_target_claim_patch_v2(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "low"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        results = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [reviewed_candidate_fixture()],
                    request_digest=sha256_json(request),
                )
            ],
        )
        review_set = results["review_requests"]
        review_request = review_set["requests"][0]
        with tempfile.TemporaryDirectory() as directory:
            report_set, dossier, bundle, source = real_producer_projection(
                Path(directory),
                review_set,
                review_request,
                network,
                verification_root=directory,
            )
            self.assertNotEqual(
                Path(source).name, review_request["sources"][0]["source_ref"]
            )
            consumed = consume_reviewed_evidence(
                results,
                network,
                review_set,
                report_set,
                dossier,
                source_bundle_path=bundle,
                source_artifact_path=source,
                verification_root=directory,
            )
            target_kind_patches = {}
            for target_kind in sorted(TARGET_KINDS):
                with self.subTest(target_kind=target_kind):
                    variant = copy.deepcopy(consumed)
                    variant["hypotheses"][0]["target_kind"] = target_kind
                    generated = propose_patch(
                        variant,
                        network,
                        review_set,
                        report_set,
                        dossier,
                        source_bundle_path=bundle,
                        source_artifact_path=source,
                        verification_root=directory,
                    )
                    validate_patch_v2(generated, network)
                    target_kind_patches[target_kind] = generated

        patch = target_kind_patches["relation"]

        action = patch["actions"][0]
        basis = action["reviewed_evidence"][0]
        target = action["target_claim"]
        request_scope = review_request["epistemic_task"]["scope"]
        self.assertEqual(
            target["claim_text"], report_set["reports"][0]["claim_statement"]
        )
        self.assertEqual(target["impact"], "low")
        self.assertEqual(
            target["scope"]["scope_statement"],
            review_request["epistemic_task"]["scope_bounds"],
        )
        self.assertEqual(target["coverage_dimensions"], [])
        self.assertEqual(target["benchmark_profiles"], [])
        self.assertEqual(target["scope"]["assumptions"], request_scope["assumptions"])
        self.assertEqual(target["scope"]["conditions"], request_scope["conditions"])
        self.assertEqual(target["scope"]["units"], request_scope["units"])
        self.assertEqual(target["scope"]["exclusions"], request_scope["exclusions"])
        self.assertEqual(
            target["scope"]["defeaters"],
            review_request["epistemic_task"]["defeaters"],
        )
        self.assertNotEqual(target["scope"]["exclusions"], target["scope"]["defeaters"])
        self.assertEqual(target["report_claim_id"], basis["claim_id"])
        self.assertEqual(target["report_claim_digest"], basis["claim_digest"])
        self.assertIn(
            basis["source_id"], {source["source_id"] for source in network["sources"]}
        )
        validate_patch_v2(patch, network)
        for target_kind, generated in target_kind_patches.items():
            with self.subTest(validated_target_kind=target_kind):
                generated_action = generated["actions"][0]
                self.assertEqual(
                    generated_action["action_type"],
                    ACTION_FOR_TARGET_KIND[target_kind],
                )
                self.assertEqual(
                    generated_action["action_status"],
                    "proposed" if target_kind == "relation" else "blocked",
                )
                self.assertEqual(
                    "target_claim" in generated_action,
                    target_kind == "relation",
                )
        assumption_action = target_kind_patches["assumption"]["actions"][0]
        self.assertEqual(assumption_action["action_type"], "propose_evidence")
        self.assertEqual(assumption_action["action_status"], "blocked")

        invalid_assumption = copy.deepcopy(target_kind_patches["assumption"])
        invalid_assumption["actions"][0]["action_status"] = "proposed"
        rehash_patch_v2(invalid_assumption)
        with self.assertRaisesRegex(ContractError, "materialization eligibility"):
            validate_patch_v2(invalid_assumption, network)

    def test_unonboarded_source_is_terminal_onboarding_required(self):
        network = network_fixture()
        network["sources"] = []
        attach_network_content_sha256(network)
        hypotheses = hypotheses_fixture(network)
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        results = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [reviewed_candidate_fixture()],
                    request_digest=sha256_json(request),
                )
            ],
        )
        review_set = results["review_requests"]
        review_request = review_set["requests"][0]
        with tempfile.TemporaryDirectory() as directory:
            report_set, dossier, bundle, source = real_producer_projection(
                Path(directory),
                review_set,
                review_request,
                network,
                verification_root=directory,
            )
            consumed = consume_reviewed_evidence(
                results,
                network,
                review_set,
                report_set,
                dossier,
                source_bundle_path=bundle,
                source_artifact_path=source,
                verification_root=directory,
            )
            self.assertEqual(consumed["hypotheses"][0]["status"], "blocked")
            self.assertEqual(
                consumed["hypotheses"][0]["next_action"], "onboarding_required"
            )
            self.assertEqual(
                consumed["cycle_state"]["stop_reason"], "onboarding_required"
            )
            with self.assertRaisesRegex(ContractError, "onboarding_required"):
                propose_patch(
                    consumed,
                    network,
                    review_set,
                    report_set,
                    dossier,
                    source_bundle_path=bundle,
                    source_artifact_path=source,
                    verification_root=directory,
                )

    def test_action_map_is_closed_for_every_target_kind(self):
        self.assertEqual(
            ACTION_FOR_TARGET_KIND,
            {
                "node": "propose_node",
                "relation": "propose_relation",
                "evidence": "propose_evidence",
                "boundary": "propose_evidence",
                "counterexample": "propose_evidence",
                "version": "propose_evidence",
                "benchmark": "propose_evidence",
                "benchmark_profile": "propose_evidence",
                "assumption": "propose_evidence",
                "mechanism": "propose_evidence",
                "metric": "propose_evidence",
                "measurement": "propose_evidence",
                "estimator": "propose_evidence",
                "failure_mode": "propose_evidence",
                "context": "propose_evidence",
            },
        )
        self.assertEqual(TARGET_KINDS, set(ACTION_FOR_TARGET_KIND))

    def test_network_patch_v2_exact_evidence_target_is_apply_eligible(self):
        network = network_fixture()
        valid = patch_v2_fixture(network)
        exact_evidence = copy.deepcopy(valid)
        exact_evidence_action = exact_evidence["actions"][0]
        exact_evidence_action.pop("target_claim")
        exact_evidence_action["action_type"] = "propose_evidence"
        exact_evidence_action["target_signature"] = {
            "target_kind": "evidence",
            "signature": exact_evidence_action["reviewed_evidence"][0]["evidence_id"],
        }
        exact_evidence_action["action_status"] = "proposed"
        rehash_patch_v2(exact_evidence)
        validate_patch_v2(exact_evidence, network)

    def test_network_patch_v2_contract_and_ineligible_mutations(self):
        network = network_fixture()
        valid = patch_v2_fixture(network)
        self.assertEqual(
            validate_patch_v2(copy.deepcopy(valid), network)["schema"],
            "NetworkPatchProposal/v2",
        )
        mutations = (
            ("access_level", "abstract_only"),
            ("inspection_depth", "map"),
            ("relation", "qualifies"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                invalid = copy.deepcopy(valid)
                invalid["actions"][0]["reviewed_evidence"][0][field] = value
                rehash_patch_v2(invalid)
                with self.assertRaisesRegex(ContractError, "not graph eligible"):
                    validate_patch_v2(invalid, network)
        same_context = copy.deepcopy(valid)
        same_context["actions"][0]["reviewed_evidence"][0]["verification"]["mode"] = (
            "same_context_diagnostic"
        )
        rehash_patch_v2(same_context)
        with self.assertRaisesRegex(ContractError, "verification mode"):
            validate_patch_v2(same_context, network)

        missing_target = copy.deepcopy(valid)
        missing_target["actions"][0].pop("target_claim")
        rehash_patch_v2(missing_target)
        with self.assertRaisesRegex(ContractError, "action field set"):
            validate_patch_v2(missing_target, network)

        invented_profile = copy.deepcopy(valid)
        target = invented_profile["actions"][0]["target_claim"]
        target["benchmark_profiles"] = ["out-of-scope regime"]
        target["scope"]["benchmark_profiles"] = ["out-of-scope regime"]
        target["scope_digest"] = sha256_json(target["scope"])
        rehash_patch_v2(invented_profile)
        with self.assertRaisesRegex(ContractError, "explicit same-named"):
            validate_patch_v2(invented_profile, network)

        unonboarded = copy.deepcopy(valid)
        unonboarded["actions"][0]["reviewed_evidence"][0]["source_id"] = "SRC-MISSING"
        rehash_patch_v2(unonboarded)
        with self.assertRaisesRegex(ContractError, "onboarding_required"):
            validate_patch_v2(unonboarded, network)

    def test_real_gap_queries_preserve_semantic_label_and_drop_internal_template_terms(
        self,
    ):
        network = doe_surrogate_noise_network_fixture(
            single_source_count=0, isolate_count=0
        )
        semantic_label = "expensive simulator adaptive sampling and surrogate uncertainty calibration"
        network["gaps"][0]["description"] = semantic_label
        network["gaps"][0]["reason"] = (
            "Targeted evidence needed for claim:rank_correlation_fulltext"
        )
        attach_network_content_sha256(network)

        hypotheses = prioritize(
            generate_hypotheses_from_probe(scan_network(network), network), network
        )
        hypothesis = next(
            row
            for row in hypotheses["hypotheses"]
            if row["grounds"][0]["ref_id"] == "gap:morphology_specific_benchmark"
        )
        self.assertEqual(hypothesis["semantic_label"], semantic_label)

        request_set = emit_search_requests(hypotheses, network)
        request = next(
            row
            for row in request_set["requests"]
            if row["gap_hypothesis_id"] == hypothesis["hypothesis_id"]
        )
        self.assertEqual(request["paper_need"], semantic_label)
        provider_queries = " ".join(
            seed["query"] for seed in request["query_seeds"]
        ).lower()
        self.assertIn("expensive simulator", provider_queries)
        for forbidden in (
            "claim:",
            "rank_correlation_fulltext",
            "targeted",
            "needed",
            "probe",
            "signal",
        ):
            self.assertNotIn(forbidden, provider_queries)
        self.assertNotEqual(
            request["query_seeds"][0]["query"],
            request["query_seeds"][1]["query"],
        )

    def test_generated_acceptance_criteria_is_semantic_not_route_boilerplate(self):
        network = doe_surrogate_noise_network_fixture(
            single_source_count=0, isolate_count=0
        )
        semantic_label = "expensive simulator adaptive sampling with surrogate uncertainty calibration"
        network["gaps"][0]["description"] = semantic_label
        attach_network_content_sha256(network)

        hypotheses = generate_hypotheses_from_probe(scan_network(network), network)
        hypothesis = next(
            row
            for row in hypotheses["hypotheses"]
            if row["grounds"][0]["ref_id"] == "gap:morphology_specific_benchmark"
        )
        acceptance = hypothesis["search_test"]["acceptance_criteria"].lower()
        self.assertNotEqual(acceptance, "multiple bounded routes and grounded fallback")
        self.assertIn("expensive simulator", acceptance)
        self.assertIn("primary full-text evidence", acceptance)
        self.assertGreaterEqual(
            len(set(hypothesis["search_test"]["route_families"])), 2
        )

    def test_low_confidence_relation_emits_semantic_paper_need(self):
        network = network_fixture()
        network["nodes"][0]["label"] = (
            "spatial Sobol maps from Gaussian-process surrogates"
        )
        network["nodes"][1]["label"] = "hyperparameter and basis-selection uncertainty"
        network["relations"][0].update(
            {
                "confidence": "low",
                "status": "unresolved",
                "notes": "uncertainty propagation remains unverified",
            }
        )
        network["gaps"] = []
        network["completion"] = {
            "status": "partial",
            "open_gap_ids": [],
            "gate_checks": {"corpus_snapshotted": True, "conflicts_terminal": True},
        }
        attach_network_content_sha256(network)

        hypotheses = prioritize(
            generate_hypotheses_from_probe(scan_network(network), network), network
        )
        hypothesis = next(
            row
            for row in hypotheses["hypotheses"]
            if row["source_signal_kind"] == "low_confidence_relation"
        )
        request_set = emit_search_requests(hypotheses, network)
        request = next(
            row
            for row in request_set["requests"]
            if row["gap_hypothesis_id"] == hypothesis["hypothesis_id"]
        )

        self.assertEqual(hypothesis["status"], "selected")
        self.assertNotEqual(
            request["paper_need"].lower(),
            "confidence may require independent evidence",
        )
        self.assertIn("spatial", request["paper_need"].lower())
        self.assertIn("uncertainty", request["paper_need"].lower())
        self.assertEqual(
            {
                row["hypothesis_id"]
                for row in hypotheses["hypotheses"]
                if row["status"] == "selected"
            },
            {row["gap_hypothesis_id"] for row in request_set["requests"]},
        )

    def test_reviewed_gap_selection_v2_replays_subject_and_current_gap_record(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = multi_reading_collection_fixture(Path(directory))
            selected = fixture["selected"]
            subject = fixture["subject"]
            network = fixture["network"]

            replayed_ref = discovery.reviewed_selection_ref_for_emission(
                selected, ["KGH-1"], network
            )
            self.assertEqual(replayed_ref, selected["reviewed_selection_ref"])
            self.assertEqual(
                discovery.reviewed_selection_ref_for_emission(
                    selected, ["KGH-1"], None
                ),
                replayed_ref,
            )
            request_set = emit_search_requests(selected, network)
            discovery._scholar_discovery_module().validate_request_set(request_set)
            with self.assertRaisesRegex(ContractError, "requires the bound network"):
                select_hypotheses(fixture["prioritized"], fixture["selection"], None)
            task = discovery._epistemic_task_from_hypothesis(selected["hypotheses"][0])
            self.assertEqual(task["hypothesis"], subject["claim_text"])
            self.assertEqual(task["target_signature"], subject["target_signature"])
            self.assertEqual(task["scope_bounds"], subject["scope_statement"])
            self.assertEqual(
                task["scope"],
                {
                    field: subject[field]
                    for field in ("assumptions", "conditions", "units", "exclusions")
                },
            )

            stale = copy.deepcopy(fixture["selection"])
            stale_subject = stale["claim_subjects"][0]
            stale_subject["origin_gap_refs"][0]["sequence"] = 2
            stale_subject["subject_digest"] = discovery._claim_subject_digest(
                stale_subject
            )
            stale_subject["subject_id"] = (
                discovery.REVIEWED_CLAIM_SUBJECT_ID_PREFIX
                + stale_subject["subject_digest"][:16]
            )
            with self.assertRaisesRegex(ContractError, "current export record_ref"):
                select_hypotheses(fixture["prioritized"], stale, fixture["network"])

            kgh = copy.deepcopy(fixture["selection"])
            kgh_subject = kgh["claim_subjects"][0]
            kgh_subject["origin_gap_refs"][0]["gap_id"] = "KGH-FORGED"
            kgh_subject["subject_digest"] = discovery._claim_subject_digest(kgh_subject)
            kgh_subject["subject_id"] = (
                discovery.REVIEWED_CLAIM_SUBJECT_ID_PREFIX
                + kgh_subject["subject_digest"][:16]
            )
            with self.assertRaisesRegex(ContractError, "not KGH"):
                select_hypotheses(fixture["prioritized"], kgh, fixture["network"])

            injected = copy.deepcopy(fixture["selection"])
            injected_subject = injected["claim_subjects"][0]
            injected_subject["coverage_dimensions"].append("unrequired dimension")
            injected_subject["subject_digest"] = discovery._claim_subject_digest(
                injected_subject
            )
            injected_subject["subject_id"] = (
                discovery.REVIEWED_CLAIM_SUBJECT_ID_PREFIX
                + injected_subject["subject_digest"][:16]
            )
            with self.assertRaisesRegex(ContractError, "unrequired coverage"):
                select_hypotheses(fixture["prioritized"], injected, fixture["network"])

            substituted = copy.deepcopy(fixture["selection"])
            substituted_subject = substituted["claim_subjects"][0]
            substituted_subject["claim_text"] = "An unrelated treatment cures cancer."
            substituted_subject["subject_digest"] = discovery._claim_subject_digest(
                substituted_subject
            )
            substituted_subject["subject_id"] = (
                discovery.REVIEWED_CLAIM_SUBJECT_ID_PREFIX
                + substituted_subject["subject_digest"][:16]
            )
            with self.assertRaisesRegex(ContractError, "claim_text must match"):
                select_hypotheses(
                    fixture["prioritized"], substituted, fixture["network"]
                )

    def test_multi_reading_collection_consumes_and_proposes_v3_in_collection_order(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            fixture = multi_reading_collection_fixture(
                Path(directory), direct_selected=True
            )
            artifacts = reviewed_collection_consumption_artifacts(
                Path(directory), fixture
            )
            consumed = consume_reviewed_evidence_collection(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )
            replayed_consumed = consume_reviewed_evidence_collection(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )
            self.assertEqual(
                discovery.canonical_bytes(consumed),
                discovery.canonical_bytes(replayed_consumed),
            )
            hypothesis = consumed["hypotheses"][0]
            self.assertEqual(hypothesis["status"], "content_found")
            self.assertEqual(
                [row["independence_group"] for row in hypothesis["status_basis"]],
                [row["source_id"] for row in hypothesis["status_basis"]],
            )
            self.assertEqual(
                consumed["cycle_state"]["reading_collection_id"],
                fixture["collection"]["collection_id"],
            )
            self.assertEqual(
                consumed["cycle_state"]["reading_collection_digest"],
                fixture["collection"]["collection_digest"],
            )

            patch = propose_patch_v3(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )
            replayed_patch = propose_patch_v3(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )
            self.assertEqual(
                discovery.canonical_bytes(patch),
                discovery.canonical_bytes(replayed_patch),
            )
            validate_patch_v3(patch, fixture["network"])
            self.assertEqual(
                patch["consumption_ref"],
                consumed["cycle_state"]["consumption_ref"],
            )
            action = patch["actions"][0]
            self.assertEqual(
                action["reading_group_refs"],
                [
                    discovery._reading_group_ref(group)
                    for group in fixture["collection"]["reading_groups"]
                ],
            )
            self.assertEqual(action["hypothesis"], fixture["subject"]["claim_text"])
            self.assertEqual(
                action["origin_gap_refs"], fixture["subject"]["origin_gap_refs"]
            )
            target = action["target_claim"]
            self.assertEqual(
                target["coverage_dimensions"],
                fixture["subject"]["coverage_dimensions"],
            )
            self.assertEqual(
                target["benchmark_profiles"], fixture["subject"]["benchmark_profiles"]
            )
            self.assertEqual(
                len(target["report_claim_refs"]), len(action["reviewed_evidence"])
            )

    def test_multi_reading_claimless_origins_propose_v4_new_claim_without_changing_v3(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(root, direct_selected=True)
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)

            v3 = propose_patch_v3(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )
            v4 = propose_patch_v4(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )

            self.assertEqual(v4["schema"], "NetworkPatchProposal/v4")
            self.assertEqual(v4["schema_version"], "4.0")
            self.assertEqual(v4["actions"][0]["action_type"], "propose_relation")
            self.assertIn("target_claim", v4["actions"][0])
            self.assertNotIn("existing_claim_ref", v4["actions"][0])
            self.assertEqual(
                {
                    key: value
                    for key, value in v4["actions"][0].items()
                    if key not in {"action_id", "action_digest"}
                },
                {
                    key: value
                    for key, value in v3["actions"][0].items()
                    if key not in {"action_id", "action_digest"}
                },
            )
            self.assertIs(validate_patch_v4(v4, fixture["network"]), v4)
            self.assertIs(validate_patch_v3(v3, fixture["network"]), v3)

    def test_multi_reading_claim_backed_origins_propose_v4_evidence_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(
                root, direct_selected=True, existing_claim=True
            )
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)

            patch = propose_patch_v4(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )

            action = patch["actions"][0]
            self.assertEqual(action["action_type"], "propose_evidence_extension")
            self.assertNotIn("target_claim", action)
            existing = action["existing_claim_ref"]
            claim = fixture["network"]["claims"][0]
            self.assertEqual(
                set(existing),
                {
                    "schema",
                    "schema_version",
                    "claim_id",
                    "claim_record_ref",
                    "claim_semantics",
                    "scope_digest",
                    "claim_semantic_digest",
                },
            )
            self.assertEqual(existing["schema"], "NetworkPatchExistingClaimRef/v1")
            self.assertEqual(
                set(existing["claim_semantics"]),
                {
                    "claim_text",
                    "entity_id",
                    "impact",
                    "is_factual",
                    "scope_statement",
                    "assumptions",
                    "conditions",
                    "units",
                    "exclusions",
                    "defeaters",
                    "coverage_dimensions",
                    "benchmark_profiles",
                    "supersedes",
                },
            )
            self.assertEqual(
                existing["claim_record_ref"],
                {
                    "record_id": claim["record_id"],
                    "sequence": claim["sequence"],
                    "sha256": sha256_json(claim),
                },
            )
            self.assertEqual(
                existing["claim_semantic_digest"],
                sha256_json(existing["claim_semantics"]),
            )
            self.assertEqual(
                existing["scope_digest"],
                sha256_json(
                    {
                        key: existing["claim_semantics"][key]
                        for key in (
                            "scope_statement",
                            "assumptions",
                            "conditions",
                            "units",
                            "exclusions",
                            "defeaters",
                            "coverage_dimensions",
                            "benchmark_profiles",
                        )
                    }
                ),
            )
            self.assertEqual(
                action["subject_ref"],
                {
                    "subject_id": fixture["subject"]["subject_id"],
                    "subject_digest": fixture["subject"]["subject_digest"],
                },
            )
            self.assertEqual(
                action["origin_gap_refs"], fixture["subject"]["origin_gap_refs"]
            )
            self.assertIs(validate_patch_v4(patch, fixture["network"]), patch)
            with mock.patch.object(
                discovery,
                "validate_patch_v3",
                side_effect=AssertionError("v4 validation must remain native"),
            ):
                self.assertIs(validate_patch_v4(patch, fixture["network"]), patch)

            unknown_top_level = copy.deepcopy(patch)
            unknown_top_level["unexpected_top_level"] = "self-sealed injection"
            discovery._rehash_patch_proposal_identity(unknown_top_level)
            with self.assertRaisesRegex(ContractError, "top-level contract"):
                validate_patch_v4(unknown_top_level, fixture["network"])

    def test_propose_patch_v4_cli_replays_the_authorized_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(
                root, direct_selected=True, existing_claim=True
            )
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)
            network_path, _ = _write_named_artifact(
                root, "network.json", fixture["network"]
            )
            output_path = root / "patch-v4.json"

            result = discovery.main(
                [
                    "propose-patch-v4",
                    "--input",
                    str(artifacts["hypotheses_path"]),
                    "--network",
                    str(network_path),
                    "--review-requests",
                    str(artifacts["review_requests_path"]),
                    "--reading-collection",
                    str(artifacts["collection_path"]),
                    "--consumption-authority",
                    str(artifacts["authority_path"]),
                    "--expected-authority-file-sha256",
                    artifacts["authority_raw_sha"],
                    "--output",
                    str(output_path),
                ]
            )
            self.assertEqual(result, 0)
            emitted = discovery.load_json(output_path)
            self.assertEqual(
                discovery.canonical_bytes(emitted),
                discovery.canonical_bytes(
                    propose_patch_v4(
                        artifacts["hypotheses_path"],
                        fixture["network"],
                        artifacts["review_requests_path"],
                        artifacts["collection_path"],
                        artifacts["authority_path"],
                        expected_authority_file_sha256=artifacts["authority_raw_sha"],
                    )
                ),
            )
            self.assertEqual(
                discovery.main(
                    [
                        "validate",
                        "--input",
                        str(output_path),
                        "--network",
                        str(network_path),
                    ]
                ),
                0,
            )

    def test_propose_patch_v4_rejects_mixed_multiple_and_superseded_origin_claims(self):
        cases = (
            (["claim-existing-1", None], False, "cannot mix"),
            (
                ["claim-existing-1", "claim-existing-2"],
                False,
                "multiple existing claims",
            ),
            (["claim-existing-1"], True, "has been superseded"),
        )
        for origin_claim_ids, superseded, error in cases:
            with (
                self.subTest(origin_claim_ids=origin_claim_ids, superseded=superseded),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                fixture = multi_reading_collection_fixture(
                    root,
                    direct_selected=True,
                    origin_claim_ids=origin_claim_ids,
                    supersede_existing=superseded,
                )
                artifacts = reviewed_collection_consumption_artifacts(root, fixture)
                with self.assertRaisesRegex(ContractError, error):
                    propose_patch_v4(
                        artifacts["hypotheses_path"],
                        fixture["network"],
                        artifacts["review_requests_path"],
                        artifacts["collection_path"],
                        artifacts["authority_path"],
                        expected_authority_file_sha256=artifacts["authority_raw_sha"],
                    )

    def test_validate_patch_v4_rejects_subject_drift_stale_claim_row_and_union_ambiguity(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(
                root, direct_selected=True, existing_claim=True
            )
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)
            valid = propose_patch_v4(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )

            subject_drift = copy.deepcopy(valid)
            existing = subject_drift["actions"][0]["existing_claim_ref"]
            existing["claim_semantics"]["conditions"] = ["a different condition"]
            existing["scope_digest"] = sha256_json(
                {
                    key: existing["claim_semantics"][key]
                    for key in (
                        "scope_statement",
                        "assumptions",
                        "conditions",
                        "units",
                        "exclusions",
                        "defeaters",
                        "coverage_dimensions",
                        "benchmark_profiles",
                    )
                }
            )
            existing["claim_semantic_digest"] = sha256_json(existing["claim_semantics"])
            rehash_patch_v4_identity(subject_drift)
            with self.assertRaisesRegex(ContractError, "subject.*live claim scope"):
                validate_patch_v4(subject_drift, fixture["network"])

            stale_network = copy.deepcopy(fixture["network"])
            stale_network["claims"][0]["recorded_at"] = "2026-08-05T00:06:00Z"
            attach_network_content_sha256(stale_network)
            with self.assertRaisesRegex(ContractError, "current claim ledger row"):
                validate_patch_v4(valid, stale_network)

            ambiguous = copy.deepcopy(valid)
            ambiguous_action = ambiguous["actions"][0]
            ambiguous_action["target_claim"] = {"schema": "NetworkPatchTargetClaim/v2"}
            rehash_patch_v4_identity(ambiguous)
            with self.assertRaisesRegex(ContractError, "field set invalid for route"):
                validate_patch_v4(ambiguous, fixture["network"])

    def test_collection_consumption_rejects_results_flip_self_sealed_lfr_and_source_substitution(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(root, direct_selected=True)
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)

            with self.assertRaisesRegex(ContractError, "absolute artifact path"):
                consume_reviewed_evidence_collection(
                    fixture["selected"],
                    fixture["network"],
                    fixture["review_set"],
                    fixture["collection"],
                    artifacts["authority"],
                    expected_authority_file_sha256=artifacts["authority_raw_sha"],
                )

            forged_results = copy.deepcopy(fixture["selected"])
            forged_results["hypotheses"][0]["status"] = "results"
            forged_results_path, _ = _write_named_artifact(
                root, "forged-results.json", forged_results
            )
            with self.assertRaisesRegex(
                ContractError,
                "hypotheses raw.*binding mismatch|direct_reviewed_selection",
            ):
                consume_reviewed_evidence_collection(
                    forged_results_path,
                    fixture["network"],
                    artifacts["review_requests_path"],
                    artifacts["collection_path"],
                    artifacts["authority_path"],
                    expected_authority_file_sha256=artifacts["authority_raw_sha"],
                )

            with self.assertRaisesRegex(
                ContractError,
                "ReviewedEvidenceCollectionConsumptionAuthority/v1",
            ):
                consume_reviewed_evidence_collection(
                    artifacts["hypotheses_path"],
                    fixture["network"],
                    artifacts["review_requests_path"],
                    artifacts["collection_path"],
                    artifacts["review_requests_path"],
                    expected_authority_file_sha256=hashlib.sha256(
                        artifacts["review_requests_path"].read_bytes()
                    ).hexdigest(),
                )

            substituted = copy.deepcopy(fixture["review_set"])
            substituted["requests"][0]["sources"][0]["url"] = (
                "https://example.org/substituted-source"
            )
            substituted["request_set_digest"] = discovery.canonical_request_set_digest(
                substituted
            )
            substituted["request_set_id"] = (
                "LFR-" + substituted["request_set_digest"][:16]
            )
            substituted_path, _ = _write_named_artifact(
                root, "substituted-request-set.json", substituted
            )
            with self.assertRaisesRegex(
                ContractError, "review request set raw.*binding mismatch"
            ):
                consume_reviewed_evidence_collection(
                    artifacts["hypotheses_path"],
                    fixture["network"],
                    substituted_path,
                    artifacts["collection_path"],
                    artifacts["authority_path"],
                    expected_authority_file_sha256=artifacts["authority_raw_sha"],
                )

    def test_collection_authority_rejects_v1_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(root, direct_selected=True)
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)

            v1_selection = {
                "schema": REVIEWED_GAP_SELECTION_SCHEMA,
                "input_ref": copy.deepcopy(fixture["selection"]["input_ref"]),
                "network_ref": copy.deepcopy(fixture["selection"]["network_ref"]),
                "round_id": fixture["selection"]["round_id"],
                "selected_hypothesis_ids": ["KGH-1"],
                "review_status": "approved",
            }
            selected_v1 = select_hypotheses(
                fixture["prioritized"], v1_selection, fixture["network"]
            )
            selected_v1_path, _ = _write_named_artifact(
                root, "selected-v1.json", selected_v1
            )
            with self.assertRaisesRegex(ContractError, "ReviewedGapSelection/v2"):
                discovery.create_reviewed_collection_consumption_authority(
                    selected_v1_path,
                    fixture["network"],
                    artifacts["review_requests_path"],
                    artifacts["collection_path"],
                    consumed_at="2026-08-05T00:30:00Z",
                    reviewer_context=_collection_reviewer_context(),
                )

    def test_collection_authority_rejects_pin_independence_task_mismatch_and_partial_collection(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(root, direct_selected=True)
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)

            with self.assertRaisesRegex(ContractError, "raw file SHA-256 mismatch"):
                consume_reviewed_evidence_collection(
                    artifacts["hypotheses_path"],
                    fixture["network"],
                    artifacts["review_requests_path"],
                    artifacts["collection_path"],
                    artifacts["authority_path"],
                    expected_authority_file_sha256="0" * 64,
                )

            collided = copy.deepcopy(artifacts["authority"])
            collided["reviewer_context"]["reviewer_context_id"] = collided[
                "producer_context_ids"
            ][0]
            collided["authority_digest"] = _sha_without(
                collided, {"authority_id", "authority_digest", "seal"}
            )
            collided["authority_id"] = (
                "reviewed-collection-consumption-authority-"
                + collided["authority_digest"][:16]
            )
            collided["seal"]["digest"] = collided["authority_digest"]
            collided_path, collided_raw_sha = _write_named_artifact(
                root, "collided-authority.json", collided
            )
            with self.assertRaisesRegex(
                ContractError, "reviewer_context_id must differ"
            ):
                consume_reviewed_evidence_collection(
                    artifacts["hypotheses_path"],
                    fixture["network"],
                    artifacts["review_requests_path"],
                    artifacts["collection_path"],
                    collided_path,
                    expected_authority_file_sha256=collided_raw_sha,
                )

            unattested = copy.deepcopy(artifacts["authority"])
            unattested["reviewer_context"][
                "independent_from_bound_artifact_producers"
            ] = False
            unattested["authority_digest"] = _sha_without(
                unattested, {"authority_id", "authority_digest", "seal"}
            )
            unattested["authority_id"] = (
                "reviewed-collection-consumption-authority-"
                + unattested["authority_digest"][:16]
            )
            unattested["seal"]["digest"] = unattested["authority_digest"]
            unattested_path, unattested_raw_sha = _write_named_artifact(
                root, "unattested-authority.json", unattested
            )
            with self.assertRaisesRegex(
                ContractError, "explicitly attest independence"
            ):
                consume_reviewed_evidence_collection(
                    artifacts["hypotheses_path"],
                    fixture["network"],
                    artifacts["review_requests_path"],
                    artifacts["collection_path"],
                    unattested_path,
                    expected_authority_file_sha256=unattested_raw_sha,
                )

            mismatched = copy.deepcopy(fixture["review_set"])
            mismatched["requests"][0]["epistemic_task"]["acceptance_criteria"] = (
                "A substituted task"
            )
            mismatched["request_set_digest"] = discovery.canonical_request_set_digest(
                mismatched
            )
            mismatched["request_set_id"] = (
                "LFR-" + mismatched["request_set_digest"][:16]
            )
            mismatched_path, _ = _write_named_artifact(
                root, "task-mismatch.json", mismatched
            )
            with self.assertRaisesRegex(ContractError, "epistemic_task mismatch"):
                discovery.create_reviewed_collection_consumption_authority(
                    artifacts["hypotheses_path"],
                    fixture["network"],
                    mismatched_path,
                    artifacts["collection_path"],
                    consumed_at="2026-08-05T00:30:00Z",
                    reviewer_context=_collection_reviewer_context(),
                )

            partial = copy.deepcopy(fixture["collection"])
            partial["reading_groups"] = partial["reading_groups"][:1]
            partial["collection_digest"] = (
                READING_COLLECTION_MODULE.canonical_collection_digest(partial)
            )
            partial["collection_id"] = (
                "paper-reading-evidence-collection-" + partial["collection_digest"][:16]
            )
            partial_path, _ = _write_named_artifact(
                root, "partial-collection.json", partial
            )
            with self.assertRaisesRegex(ContractError, "at least two groups"):
                discovery.create_reviewed_collection_consumption_authority(
                    artifacts["hypotheses_path"],
                    fixture["network"],
                    artifacts["review_requests_path"],
                    partial_path,
                    consumed_at="2026-08-05T00:30:00Z",
                    reviewer_context=_collection_reviewer_context(),
                )

    def test_collection_consume_rejects_parent_directory_symlink_swap_during_replay(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(root, direct_selected=True)
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)

            hypotheses_parent = root / "isolated-hypotheses"
            hypotheses_parent.mkdir()
            hypotheses_path = hypotheses_parent / "selected.json"
            hypotheses_path.write_bytes(artifacts["hypotheses_path"].read_bytes())
            hypotheses_path.chmod(0o600)
            moved_parent = root / "moved-hypotheses"

            trigger_path = Path(
                fixture["collection"]["reading_groups"][0]["refs"]["source_artifact"][
                    "path"
                ]
            )
            trigger_metadata = os.stat(trigger_path, follow_symlinks=False)
            sentinel_atime_ns = 1_000_000_000
            os.utime(
                trigger_path,
                ns=(sentinel_atime_ns, trigger_metadata.st_mtime_ns),
                follow_symlinks=False,
            )
            swapped = threading.Event()
            swap_errors = []

            def swap_parent_after_live_replay_starts():
                deadline = time.monotonic() + 5
                try:
                    while time.monotonic() < deadline:
                        if (
                            os.stat(trigger_path, follow_symlinks=False).st_atime_ns
                            != sentinel_atime_ns
                        ):
                            hypotheses_parent.rename(moved_parent)
                            os.symlink(
                                moved_parent,
                                hypotheses_parent,
                                target_is_directory=True,
                            )
                            swapped.set()
                            return
                        time.sleep(0.0005)
                    swap_errors.append("live replay did not read the trigger artifact")
                except Exception as exc:  # pragma: no cover - surfaced below
                    swap_errors.append(repr(exc))

            worker = threading.Thread(
                target=swap_parent_after_live_replay_starts,
                daemon=True,
            )
            worker.start()
            try:
                with self.assertRaisesRegex(
                    ContractError, "must not traverse a symlink"
                ):
                    consume_reviewed_evidence_collection(
                        hypotheses_path,
                        fixture["network"],
                        artifacts["review_requests_path"],
                        artifacts["collection_path"],
                        artifacts["authority_path"],
                        expected_authority_file_sha256=artifacts["authority_raw_sha"],
                    )
            finally:
                worker.join(timeout=6)
            self.assertTrue(swapped.is_set(), swap_errors)
            self.assertEqual(swap_errors, [])

    def test_proposal_rejects_authority_file_change_after_second_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = multi_reading_collection_fixture(root, direct_selected=True)
            artifacts = reviewed_collection_consumption_artifacts(root, fixture)
            original_replay = discovery._propose_patch_v3_from_consumed_values

            def mutate_authority_after_real_replay(*args, **kwargs):
                proposal = original_replay(*args, **kwargs)
                artifacts["authority_path"].write_bytes(
                    artifacts["authority_path"].read_bytes() + b" "
                )
                return proposal

            with mock.patch.object(
                discovery,
                "_propose_patch_v3_from_consumed_values",
                side_effect=mutate_authority_after_real_replay,
            ):
                with self.assertRaisesRegex(
                    ContractError,
                    "collection consumption authority changed during",
                ):
                    propose_patch_v3(
                        artifacts["hypotheses_path"],
                        fixture["network"],
                        artifacts["review_requests_path"],
                        artifacts["collection_path"],
                        artifacts["authority_path"],
                        expected_authority_file_sha256=artifacts["authority_raw_sha"],
                    )

    def test_patch_v3_rejects_reorder_duplicate_source_injection_and_single_source(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            fixture = multi_reading_collection_fixture(
                Path(directory), direct_selected=True
            )
            artifacts = reviewed_collection_consumption_artifacts(
                Path(directory), fixture
            )
            valid = propose_patch_v3(
                artifacts["hypotheses_path"],
                fixture["network"],
                artifacts["review_requests_path"],
                artifacts["collection_path"],
                artifacts["authority_path"],
                expected_authority_file_sha256=artifacts["authority_raw_sha"],
            )

            reordered = copy.deepcopy(valid)
            reordered_action = reordered["actions"][0]
            reordered_action["reading_group_refs"].reverse()
            reordered_action["reviewed_evidence"].reverse()
            rehash_patch_v3(reordered)
            with self.assertRaisesRegex(ContractError, "collection canonical order"):
                validate_patch_v3(reordered, fixture["network"])

            duplicate_source = copy.deepcopy(valid)
            duplicate_refs = duplicate_source["actions"][0]["reading_group_refs"]
            duplicate_refs[1]["source_id"] = duplicate_refs[0]["source_id"]
            rehash_patch_v3(duplicate_source)
            with self.assertRaisesRegex(ContractError, "unique source_id"):
                validate_patch_v3(duplicate_source, fixture["network"])

            injected_coverage = copy.deepcopy(valid)
            injected_target = injected_coverage["actions"][0]["target_claim"]
            injected_target["coverage_dimensions"].append("unreviewed dimension")
            injected_target["scope"]["coverage_dimensions"].append(
                "unreviewed dimension"
            )
            rehash_patch_v3(injected_coverage)
            with self.assertRaisesRegex(ContractError, "unrequired coverage"):
                validate_patch_v3(injected_coverage, fixture["network"])

            stale_origin = copy.deepcopy(valid)
            stale_action = stale_origin["actions"][0]
            stale_action["origin_gap_refs"][0]["sequence"] = 99
            stale_action["target_claim"]["origin_gap_refs"][0]["sequence"] = 99
            rehash_patch_v3(stale_origin)
            with self.assertRaisesRegex(ContractError, "current export record_ref"):
                validate_patch_v3(stale_origin, fixture["network"])

            kgh_origin = copy.deepcopy(valid)
            kgh_action = kgh_origin["actions"][0]
            kgh_action["origin_gap_refs"][0]["gap_id"] = "KGH-FORGED"
            kgh_action["target_claim"]["origin_gap_refs"][0]["gap_id"] = "KGH-FORGED"
            rehash_patch_v3(kgh_origin)
            with self.assertRaisesRegex(ContractError, "not KGH"):
                validate_patch_v3(kgh_origin, fixture["network"])

            single_source = copy.deepcopy(valid)
            single_action = single_source["actions"][0]
            single_action["reading_group_refs"] = single_action["reading_group_refs"][
                :1
            ]
            single_action["reviewed_evidence"] = single_action["reviewed_evidence"][:1]
            rehash_patch_v3(single_source)
            with self.assertRaisesRegex(ContractError, "at least two reading"):
                validate_patch_v3(single_source, fixture["network"])

    def test_collection_subject_projection_rejects_mixed_reference_and_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = multi_reading_collection_fixture(Path(directory))
            for field, value in (
                (
                    "network_ref",
                    {**fixture["collection"]["network_ref"], "snapshot_id": "OTHER"},
                ),
                (
                    "review_request_set_ref",
                    {
                        **fixture["collection"]["review_request_set_ref"],
                        "review_request_set_digest": "e" * 64,
                    },
                ),
            ):
                with self.subTest(mixed_collection_ref=field):
                    mixed_collection = copy.deepcopy(fixture["collection"])
                    mixed_collection[field] = value
                    mixed_collection["collection_digest"] = (
                        READING_COLLECTION_MODULE.canonical_collection_digest(
                            mixed_collection
                        )
                    )
                    mixed_collection["collection_id"] = (
                        "paper-reading-evidence-collection-"
                        + mixed_collection["collection_digest"][:16]
                    )
                    with self.assertRaisesRegex(ContractError, field):
                        discovery.validate_reading_evidence_collection(
                            mixed_collection,
                            network=fixture["network"],
                            review_requests=fixture["review_set"],
                        )

            hypothesis = fixture["results"]["hypotheses"][0]
            subject = fixture["subject"]
            task = discovery._epistemic_task_from_hypothesis(hypothesis)
            record = {
                "report": {
                    "hypothesis_id": subject["hypothesis_id"],
                    "target_id": subject["target_signature"],
                    "claim_statement": subject["claim_text"],
                    "scope": copy.deepcopy(task["scope"]),
                },
                "request": {"epistemic_task": copy.deepcopy(task)},
            }
            discovery._validate_record_subject_projection(record, hypothesis, subject)

            mixed_scope = copy.deepcopy(record)
            mixed_scope["report"]["scope"]["conditions"] = ["other regime"]
            with self.assertRaisesRegex(ContractError, "scope does not match"):
                discovery._validate_record_subject_projection(
                    mixed_scope, hypothesis, subject
                )

            mixed_ref = copy.deepcopy(record)
            mixed_ref["request"]["epistemic_task"]["target_signature"] = (
                "entity:OTHER ? entity:C"
            )
            with self.assertRaisesRegex(ContractError, "epistemic_task"):
                discovery._validate_record_subject_projection(
                    mixed_ref, hypothesis, subject
                )

    def test_patch_v2_contract_remains_compatible_with_v3_addition(self):
        network = network_fixture()
        patch = patch_v2_fixture(network)
        before = discovery.canonical_bytes(patch)
        self.assertIs(validate_patch_v2(patch, network), patch)
        self.assertEqual(discovery.canonical_bytes(patch), before)


if __name__ == "__main__":
    unittest.main()
