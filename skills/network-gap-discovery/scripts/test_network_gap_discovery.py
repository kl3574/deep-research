import copy
import importlib.util
import json
import unittest
from pathlib import Path

from network_gap_discovery import (
    ContractError,
    consume_reviewed_evidence,
    consume_results,
    emit_search_requests,
    generate_hypotheses_from_probe,
    propose_patch,
    sha256_json,
    network_ref,
    prioritize,
    scan_network,
    validate_hypotheses,
    validate_paper_reading_report_set,
    validate_patch,
    validate_request_set,
)


def network_fixture():
    return {
        "schema": "KnowledgeNetwork/v1",
        "network_id": "KN-1",
        "snapshot_id": "KN-1-S1",
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
        "gaps": [
            {"gap_id": "GAP-EXPLICIT", "status": "open", "reason": "benchmark"}
        ],
        "completion": {
            "status": "partial",
            "open_gap_ids": ["GAP-EXPLICIT"],
            "gate_checks": {"corpus_snapshotted": True, "conflicts_terminal": False},
        },
    }


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
        {"gap_id": "GAP-WENDY", "status": "open", "reason": "wendy benchmark scope update"},
    ]
    return network


def hypotheses_fixture(network=None):
    network = network or network_fixture()
    return {
        "schema": "KnowledgeGapHypotheses/v1",
        "network_ref": network_ref(network),
        "round_id": "ROUND-1",
        "generated_at": "2026-08-05T00:00:00Z",
        "method_families": ["abc_bridge", "counterevidence_boundary"],
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
                "status": "proposed",
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
    result = make_result(
        request["request_id"],
        ranked_candidates,
        request_digest=request_digest,
        hypothesis_id=hypothesis_id,
    )
    result["discovery_status"] = discovery_status
    return {
        "schema": "ScholarDiscoveryResultSet/v1",
        "request_set_id": request_set["request_set_id"],
        "request_set_digest": request_set["request_set_digest"],
        "network_id": request_set["network_id"],
        "network_snapshot_sha256": request_set["network_snapshot_sha256"],
        "network_ref": request_set["network_ref"],
        "generated_at": "2026-08-05T01:00:00Z",
        "results": [result],
    }


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


def make_reading_report_set(
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


def attach_reading_report_identity(evidence_items, report_set):
    report = report_set["reports"][0]
    passages = report["evidence_passages"]
    passage = passages[0]
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
    reading_report_set = make_reading_report_set(
        review_request,
        network,
        review_set["request_set_id"],
        review_set["request_set_digest"],
    )
    attach_reading_report_identity(evidence_items, reading_report_set)
    attach_reviewed_evidence_set_digest(evidence_set)
    reviewed_hypotheses = consume_reviewed_evidence(
        results,
        network,
        review_set,
        evidence_set,
        reading_report_set,
    )
    return results, review_set, evidence_set, reading_report_set, reviewed_hypotheses


class NetworkGapDiscoveryTest(unittest.TestCase):
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

    def test_scan_marks_isolate_as_candidate_not_negative(self):
        probe = scan_network(network_fixture())
        self.assertEqual(probe["topological_isolates"], ["entity:C"]
        )
        signal = next(
            item for item in probe["candidate_signals"] if item["kind"] == "topological_isolate"
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

    def test_structural_only_hypothesis_is_not_subject_to_confirm_refute_requirements(self):
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

    def test_needs_semantic_enrichment_hypothesis_is_not_subject_to_semantic_content_requirements(self):
        document = hypotheses_fixture()
        hypothesis = document["hypotheses"][0]
        hypothesis["needs_semantic_enrichment"] = True
        hypothesis["search_test"]["queries"][0]["query"] = (
            "completion gate remains structurally unmet"
        )
        validate_hypotheses(document)
        request_set = emit_search_requests(document, network_fixture())
        self.assertEqual(request_set["requests"], [])

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
        self.assertIn(
            "decision_impact", first["hypotheses"][0]["priority_components"]
        )

    def test_emit_search_requests_is_bounded_to_network_snapshot(self):
        network = network_fixture()
        hypotheses = generate_hypotheses_from_probe(scan_network(network), network)
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
            "hypotheses": structural_only,
        }
        request_set = emit_search_requests(structural_doc, network)
        self.assertEqual(request_set["requests"], [])

        output = consume_results(
            structural_doc,
            network,
            request_set,
            [],
        )
        self.assertEqual(output["hypotheses"][0]["next_action"], "structural_only")
        self.assertEqual(output["hypotheses"][0]["status"], "no_signal")

    def test_generated_semantic_queries_are_id_free_and_topic_grounded(self):
        network = semantic_gap_network_fixture()
        hypotheses = generate_hypotheses_from_probe(scan_network(network), network)
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
            query["query"]
            for query in explicit_gap["search_test"]["queries"]
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
            self.assertLessEqual(
                len(query.split()), 12, f"query too long: {query}"
            )
            self.assertNotIn(
                "Which promised benchmark or locally complete slot is unresolved?",
                query,
            )
            self.assertNotIn("claims_property", query)
        self.assertNotRegex(all_query_text, r"\bno evidence for\b.*\bat this snapshot\b")
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
        self.assertTrue(
            "sparse" in explicit_payload or "benchmark" in explicit_payload
        )
        for workflow_token in (" gap ", " open ", " explicit ", " missing ", " coverage "):
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

    def test_make_reading_report_set_uses_report_set_namespace(self):
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
                            "candidate_id": "RRP",
                            "screening": {"decision": "include"},
                            "access_level": "full_text",
                            "url": "https://example.org/review-paper-rp",
                        }
                    ],
                    request_digest=request_digest,
                )
            ],
        )
        review_request = output["review_requests"]["requests"][0]
        report_set = make_reading_report_set(
            review_request,
            network,
            output["review_requests"]["request_set_id"],
            output["review_requests"]["request_set_digest"],
        )
        self.assertEqual(report_set["schema"], "PaperReadingReportSet/v1")
        self.assertTrue(report_set["report_set_id"].startswith("reading-report-set-"))
        self.assertEqual(
            report_set["report_set_id"],
            "reading-report-set-" + report_set["report_set_digest"][:16],
        )
        self.assertEqual(report_set["schema_version"], "v1")
        self.assertIn("review_request_set_id", report_set)
        self.assertIn("review_request_set_digest", report_set)
        self.assertNotIn("review_request_set_id", report_set["reports"][0])
        self.assertNotIn("review_request_set_digest", report_set["reports"][0])

    def test_reviewed_evidence_rejects_non_learning_review_source_flags(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        reviewed_hypotheses, review_set, evidence_set, reading_report_set, _ = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RFL1",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-fl1",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-fl1",
                    "url": "https://example.org/paper-fl1",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )

        with self.assertRaises(ContractError):
            invalid_discovery_source = copy.deepcopy(review_set)
            invalid_discovery_source["requests"][0]["sources"][0]["discovery_only"] = False
            consume_reviewed_evidence(
                reviewed_hypotheses,
                network,
                invalid_discovery_source,
                evidence_set,
                reading_report_set,
            )

        with self.assertRaises(ContractError):
            invalid_claim_support_source = copy.deepcopy(review_set)
            invalid_claim_support_source["requests"][0]["sources"][0]["claim_support_eligible"] = True
            consume_reviewed_evidence(
                reviewed_hypotheses,
                network,
                invalid_claim_support_source,
                evidence_set,
                reading_report_set,
            )

    def test_consume_reviewed_evidence_rejects_reading_report_source_mismatch(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        reviewed_hypotheses, review_set, evidence_set, reading_report_set, _ = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RFL2",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-fl2",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-fl2",
                    "url": "https://example.org/paper-fl2",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        report = reading_report_set["reports"][0]
        report["source_id"] = "SRC-ALT-1"
        report["report_digest"] = _sha_without(report, {"report_id", "report_digest"})
        report["report_id"] = "reading-report-" + report["report_digest"][:16]
        reading_report_set["source_artifact_sha256"] = report["source_digest"]
        reading_report_set["report_set_digest"] = _sha_without(
            reading_report_set, {"report_set_id", "report_set_digest"}
        )
        reading_report_set["report_set_id"] = (
            "reading-report-set-" + reading_report_set["report_set_digest"][:16]
        )
        reviewed_hypotheses["cycle_state"]["report_set_id"] = reading_report_set[
            "report_set_id"
        ]
        reviewed_hypotheses["cycle_state"]["report_set_digest"] = reading_report_set[
            "report_set_digest"
        ]
        with self.assertRaises(ContractError):
            consume_reviewed_evidence(
                reviewed_hypotheses,
                network,
                review_set,
                evidence_set,
                reading_report_set,
            )

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
        awaiting_requests = emit_search_requests(awaiting_hypotheses, awaiting_network)
        awaiting_requests["requests"][0]["routes"]["google_scholar"] = "manual_required"
        attach_request_set_digest(awaiting_requests)
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

    def test_consume_results_marks_awaiting_for_provider_failure_and_unresolved_queries(self):
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
        )
        provider_failure["results"][0]["provider_failures"] = ["provider timeout"]
        awaiting_provider = consume_results(hypotheses, network, request_set, [provider_failure])
        self.assertEqual(awaiting_provider["hypotheses"][0]["status"], "awaiting")
        self.assertEqual(
            awaiting_provider["hypotheses"][0]["next_action"], "scholar_discovery"
        )
        provider_failure_google = make_result_set(
            request_set_manual_required,
            request_manual_required,
            [],
            request_digest=request_manual_required_digest,
        )
        provider_failure_google["results"][0]["provider_failures"] = [
            {"provider": "google_scholar", "error": "requires_manual_capture"},
        ]
        awaiting_provider_google = consume_results(
            hypotheses,
            network,
            request_set_manual_required,
            [provider_failure_google],
        )
        self.assertEqual(awaiting_provider_google["hypotheses"][0]["status"], "awaiting")
        self.assertEqual(
            awaiting_provider_google["hypotheses"][0]["next_action"],
            "manual_scholar_export",
        )

        unresolved = make_result_set(
            request_set_manual_required,
            request_manual_required,
            [],
            request_digest=request_manual_required_digest,
        )
        unresolved["results"][0]["unresolved_query_ids"] = [
            {"query": "q1", "provider": "google_scholar"},
            {"query": "q2", "provider": "google_scholar"},
        ]
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

        unresolved_without_manual = copy.deepcopy(request_set)
        unresolved_without_manual["requests"][0]["routes"]["google_scholar"] = "manual_required"
        attach_request_set_digest(unresolved_without_manual)
        unresolved_without_manual_request = unresolved_without_manual["requests"][0]
        unresolved_without_manual_request_digest = sha256_json(unresolved_without_manual_request)
        unresolved_without_manual_result_set = make_result_set(
            unresolved_without_manual,
            unresolved_without_manual_request,
            [],
            request_digest=unresolved_without_manual_request_digest,
        )
        unresolved_without_manual_result_set["results"][0]["unresolved_query_ids"] = ["q1", "q2"]
        awaiting_unresolved_non_manual = consume_results(
            hypotheses,
            network,
            unresolved_without_manual,
            [unresolved_without_manual_result_set],
        )
        self.assertEqual(awaiting_unresolved_non_manual["hypotheses"][0]["status"], "awaiting")
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
            partial_request_set = request_set_manual_required if is_blocked_capability else request_set
            partial_request = request_manual_required if is_blocked_capability else request
            partial_request_digest = (
                request_manual_required_digest if is_blocked_capability else request_digest
            )
            partial = make_result_set(
                partial_request_set,
                partial_request,
                [],
                request_digest=partial_request_digest,
                discovery_status=discovery_status,
            )
            if discovery_status == "blocked_capability":
                partial["results"][0]["unresolved_query_ids"] = [
                    {"query": "q-blocked", "provider": "google_scholar"}
                ]
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
                self.assertEqual(awaiter["cycle_state"]["pending_reason"], "manual_required")
            else:
                self.assertEqual(
                    awaiter["hypotheses"][0]["next_action"],
                    "scholar_discovery",
                )

    def test_partial_provider_with_ranked_candidates_still_generates_review_request(self):
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
            )
            result["results"][0]["provider_failures"] = ["provider timeout"]
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
    def test_consume_reviewed_evidence_transitions(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        request_digest = sha256_json(request)

        def reviewed_output(candidate_candidates: list[dict], evidence: list[dict]) -> dict:
            results = consume_results(
                hypotheses,
                network,
                request_set,
                [make_result_set(request_set, request, candidate_candidates, request_digest)],
            )
            review_set = results["review_requests"]
            review_request = review_set["requests"][0]
            review_request_digest = sha256_json(review_request)
            reading_report_set = make_reading_report_set(
                review_request,
                network,
                review_set["request_set_id"],
                review_set["request_set_digest"],
            )
            evidence_set = {
                "schema": "ReviewedEvidenceSet/v1",
                "schema_version": "1.0",
                "request_set_id": review_set["request_set_id"],
                "request_set_digest": review_set["request_set_digest"],
                "network_id": network_ref(network)["network_id"],
                "network_snapshot_sha256": network_ref(network)["sha256"],
                "network_ref": network_ref(network),
                "generated_at": "2026-08-05T02:00:00Z",
                "evidence": evidence,
            }
            attach_review_source_identity(
                review_set,
                evidence,
                review_request,
            )
            for item in evidence:
                item["request_set_id"] = review_set["request_set_id"]
                item["request_id"] = review_request["request_id"]
                item["review_request_id"] = review_request["request_id"]
                item["review_request_digest"] = review_request_digest
            attach_reading_report_identity(evidence, reading_report_set)
            attach_reviewed_evidence_set_digest(evidence_set)
            return consume_reviewed_evidence(
                results,
                network,
                review_set,
                evidence_set,
                reading_report_set,
            )

        output_support = reviewed_output(
            [
                {
                    "candidate_id": "R1",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "exact_locator": "https://example.org/review-paper-1",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "study-1",
                    "exact_locator": "paper-1",
                    "url": "https://example.org/paper-1",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        self.assertEqual(output_support["hypotheses"][0]["status"], "content_found")
        self.assertEqual(output_support["hypotheses"][0]["next_action"], "discover")

        output_contested = reviewed_output(
            [
                {
                    "candidate_id": "R2",
                    "screening": {"decision": "include"},
                    "access_level": "abstract",
                    "exact_locator": "https://example.org/review-paper-2",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "study-2",
                    "exact_locator": "paper-2",
                    "url": "https://example.org/paper-2",
                    "read_depth": "evidence",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                },
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "study-3",
                    "exact_locator": "paper-3",
                    "url": "https://example.org/paper-3",
                    "read_depth": "evidence",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "contradicts",
                    "hypothesis_id": "KGH-1",
                },
            ],
        )
        self.assertEqual(output_contested["hypotheses"][0]["status"], "contested")

        output_unknown = reviewed_output(
            [
                {
                    "candidate_id": "R3",
                    "screening": {"decision": "include"},
                    "access_level": "abstract",
                    "exact_locator": "https://example.org/review-paper-3",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "study-4",
                    "exact_locator": "paper-4",
                    "url": "https://example.org/paper-4",
                    "read_depth": "evidence",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "unknown",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        self.assertEqual(output_unknown["hypotheses"][0]["status"], "unresolved")

    def test_discovery_only_review_evidence_is_rejected(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        request = request_set["requests"][0]
        request_digest = sha256_json(request)

        results = consume_results(
            hypotheses,
            network,
            request_set,
            [
                make_result_set(
                    request_set,
                    request,
                    [
                        {
                            "candidate_id": "RDO",
                            "screening": {"decision": "include"},
                            "access_level": "full_text",
                            "url": "https://example.org/review-paper-do",
                        }
                    ],
                    request_digest=request_digest,
                )
            ],
        )
        review_set = results["review_requests"]
        evidence_set = {
            "schema": "ReviewedEvidenceSet/v1",
            "schema_version": "1.0",
            "request_set_id": review_set["request_set_id"],
            "request_set_digest": review_set["request_set_digest"],
            "network_id": network_ref(network)["network_id"],
            "network_snapshot_sha256": network_ref(network)["sha256"],
            "network_ref": network_ref(network),
            "generated_at": "2026-08-05T03:00:00Z",
            "evidence": [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "study-do-not-upgrade",
                    "exact_locator": "paper-dou",
                    "url": "https://example.org/paper-dou",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "outcome": "supports",
                    "discovery_only": True,
                    "hypothesis_id": "KGH-1",
                    "request_set_id": review_set["request_set_id"],
                }
            ],
        }
        attach_reviewed_evidence_set_digest(evidence_set)
        review_request = review_set["requests"][0]
        review_request_digest = sha256_json(review_request)
        attach_review_source_identity(review_set, evidence_set["evidence"], review_request)
        for item in evidence_set["evidence"]:
            item["request_id"] = review_request["request_id"]
            item["review_request_id"] = review_request["request_id"]
            item["review_request_digest"] = review_request_digest
        reading_report_set = make_reading_report_set(
            review_request,
            network,
            review_set["request_set_id"],
            review_set["request_set_digest"],
        )
        attach_reading_report_identity(evidence_set["evidence"], reading_report_set)

        with self.assertRaises(ContractError):
            consume_reviewed_evidence(
                results, network, review_set, evidence_set, reading_report_set
            )

    def test_direct_copy_of_review_source_without_completion_is_rejected(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        reviewed_hypotheses, review_set, evidence_set, reading_report_set, _ = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RCC",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-cc",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-cc",
                    "url": "https://example.org/paper-cc",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        evidence_set["evidence"][0]["review_completed"] = False
        with self.assertRaises(ContractError):
            consume_reviewed_evidence(
                reviewed_hypotheses,
                network,
                review_set,
                evidence_set,
                reading_report_set,
            )

    def test_consume_reviewed_evidence_requires_matching_review_sets(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        reviewed_hypotheses, review_set, evidence_set, reading_report_set, _ = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RB1",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-verify",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-ver",
                    "url": "https://example.org/paper-ver",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )

        with self.assertRaises(ContractError):
            consume_reviewed_evidence(
                reviewed_hypotheses,
                network,
                review_set,
                {
                    **evidence_set,
                    "request_set_id": "WRONG-REQUEST-SET",
                },
                reading_report_set,
            )

        wrong_request_set = {
            **review_set,
            "request_set_id": "WRONG-REQUEST-SET",
        }
        with self.assertRaises(ContractError):
            consume_reviewed_evidence(
                reviewed_hypotheses,
                network,
                wrong_request_set,
                evidence_set,
                reading_report_set,
            )
        reviewed_hypotheses["cycle_state"]["review_request_set_id"] = "WRONG-CYCLE-SET"
        with self.assertRaises(ContractError):
            consume_reviewed_evidence(
                reviewed_hypotheses,
                network,
                review_set,
                evidence_set,
                reading_report_set,
            )

    def test_consume_reviewed_evidence_rejects_source_identity_mismatch(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RBM1",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-mismatch",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-rbm1",
                    "url": "https://example.org/paper-rbm1",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        evidence_set["evidence"][0]["source_id"] = "SRC-BAD"
        evidence_set["evidence"][0]["source_digest"] = "0" * 64

        with self.assertRaises(ContractError):
            consume_reviewed_evidence(
                reviewed_hypotheses,
                network,
                review_set,
                evidence_set,
                reading_report_set,
            )

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

    def test_propose_patch_rejects_missing_cycle_evidence_set_reference(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RZM",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-zm",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-zm",
                    "url": "https://example.org/paper-zm",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        with self.assertRaises(ContractError):
            corrupted = copy.deepcopy(reviewed_hypotheses)
            del corrupted["cycle_state"]["reviewed_evidence_set_id"]
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

        with self.assertRaises(ContractError):
            corrupted = copy.deepcopy(reviewed_hypotheses)
            del corrupted["cycle_state"]["reviewed_evidence_set_digest"]
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

        with self.assertRaises(ContractError):
            corrupted = copy.deepcopy(reviewed_hypotheses)
            corrupted["cycle_state"]["reviewed_evidence_set_id"] = "WRONG-EVIDENCE-SET"
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

        with self.assertRaises(ContractError):
            corrupted = copy.deepcopy(reviewed_hypotheses)
            del corrupted["cycle_state"]["report_set_id"]
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

        with self.assertRaises(ContractError):
            corrupted = copy.deepcopy(reviewed_hypotheses)
            del corrupted["cycle_state"]["report_set_digest"]
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

        with self.assertRaises(ContractError):
            corrupted = copy.deepcopy(reviewed_hypotheses)
            corrupted["cycle_state"]["report_set_id"] = "WRONG-REPORT-SET"
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

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
        request_set = emit_search_requests(hypotheses, network)
        request_set["requests"][0]["routes"]["google_scholar"] = "manual_required"
        attach_request_set_digest(request_set)

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

    def test_propose_patch_accepts_valid_reviewed_basis(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RZ1",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-z1",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-z1",
                    "url": "https://example.org/paper-z1",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        patch = propose_patch(
            reviewed_hypotheses,
            network,
            evidence_set,
            review_set,
            reading_report_set,
        )
        self.assertEqual(patch["schema"], "NetworkPatchProposal/v1")
        self.assertEqual(patch["basis_gap_ids"], ["KGH-1"])
        self.assertEqual(len(patch["relations"]), 1)
        self.assertEqual(patch["relations"][0]["status"], "content_found")

    def test_propose_patch_rejects_tampered_hypothesis_status(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RZ1A",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-z1a",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-z1a",
                    "url": "https://example.org/paper-z1a",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        corrupted = copy.deepcopy(reviewed_hypotheses)
        corrupted["hypotheses"][0]["status"] = "supported_gap"
        with self.assertRaises(ContractError):
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

    def test_propose_patch_rejects_broken_evidence_identity_in_status_basis(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RZ1B",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-z1b",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-z1b",
                    "url": "https://example.org/paper-z1b",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        corrupted = copy.deepcopy(reviewed_hypotheses)
        corrupted["hypotheses"][0]["status_basis"][0]["evidence_digest"] = "0" * 64
        with self.assertRaises(ContractError):
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

    def test_propose_patch_rejects_missing_review_request_id_in_status_basis(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RZ2",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-z2",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-z2",
                    "url": "https://example.org/paper-z2",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        corrupted = copy.deepcopy(reviewed_hypotheses)
        del corrupted["hypotheses"][0]["status_basis"][0]["review_request_id"]
        with self.assertRaises(ContractError):
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

    def test_propose_patch_rejects_review_request_digest_mismatch(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RZ3",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-z3",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-z3",
                    "url": "https://example.org/paper-z3",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        corrupted = copy.deepcopy(reviewed_hypotheses)
        corrupted["hypotheses"][0]["status_basis"][0]["review_request_digest"] = "0" * 64
        with self.assertRaises(ContractError):
            propose_patch(
                corrupted,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

    def test_propose_patch_rejects_cycle_review_request_set_mismatch(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RZ4",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-z4",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-z4",
                    "url": "https://example.org/paper-z4",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        reviewed_hypotheses["cycle_state"]["review_request_set_id"] = "WRONG-CYCLE-SET"
        with self.assertRaises(ContractError):
            propose_patch(
                reviewed_hypotheses,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )

    def test_propose_patch_rejects_cycle_review_request_set_digest_mismatch(self):
        network = network_fixture()
        hypotheses = hypotheses_fixture(network)
        hypotheses["hypotheses"][0]["decision_impact"] = "medium"
        request_set = emit_search_requests(hypotheses, network)
        _, review_set, evidence_set, reading_report_set, reviewed_hypotheses = build_reviewed_inputs(
            hypotheses,
            network,
            request_set,
            [
                {
                    "candidate_id": "RZ5",
                    "screening": {"decision": "include"},
                    "access_level": "full_text",
                    "url": "https://example.org/review-paper-z5",
                }
            ],
            [
                {
                    "schema": "ReviewedEvidence/v1",
                    "source_ref": "review-source",
                    "exact_locator": "paper-z5",
                    "url": "https://example.org/paper-z5",
                    "read_depth": "full_text",
                    "claim_support_eligible": True,
                    "discovery_only": False,
                    "outcome": "supports",
                    "hypothesis_id": "KGH-1",
                }
            ],
        )
        reviewed_hypotheses["cycle_state"]["review_request_set_digest"] = "0" * 64
        with self.assertRaises(ContractError):
            propose_patch(
                reviewed_hypotheses,
                network,
                evidence_set,
                review_set,
                reading_report_set,
            )


if __name__ == "__main__":
    unittest.main()
