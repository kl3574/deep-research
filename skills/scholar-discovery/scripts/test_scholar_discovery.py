import copy
import json
import os
import unittest
import urllib.parse
from unittest import mock

from scholar_discovery import (
    ContractError,
    HTTP_USER_AGENT,
    build_preflight,
    build_result,
    compile_topic_need_set,
    compile_understanding_gap_request,
    compile_plan,
    execute_request_set,
    _http_transport,
    _query_url_crossref,
    _query_url_openalex,
    _query_url_semantic_scholar,
    validate_request,
    validate_request_set,
    validate_result_set,
    sha256_json,
    validate_batch,
    validate_plan,
)


def request_fixture():
    return {
        "schema": "ScholarDiscoveryRequest/v1",
        "request_id": "SDR-1",
        "paper_need": "Find primary studies for a proposed relation",
        "intent": "topic_set",
        "effort": "diligent",
        "criteria": {"must": ["relation"], "should": [], "must_not": []},
        "metadata_filters": {
            "years": {"from": 2015, "to": 2026},
            "authors": [],
            "venues": [],
            "languages": ["en"],
            "work_types": ["primary_study"],
            "open_access": None,
        },
        "seeds": {
            "doi": [],
            "arxiv": [],
            "pmid": [],
            "openalex": [],
            "semantic_scholar": [],
            "titles": [],
        },
        "routes": {
            "automatic": ["openalex", "crossref", "semantic_scholar"],
            "google_scholar": "manual_optional",
        },
        "budgets": {
            "max_rounds": 2,
            "max_queries": 12,
            "max_candidates": 20,
            "timeout_seconds": 300,
        },
        "query_seeds": [
            {"objective": "confirm", "query": "alpha beta relation"},
            {"objective": "refute", "query": "alpha beta failure"},
        ],
        "as_of": "2026-08-05T00:00:00Z",
        "gap_ref": {"gap_id": "GAP-1", "network_id": "KN-1"},
    }


UNDERSTANDING_GAP_PROJECTION_BY_TYPE = {
    "missing_input_format": "workflow",
    "missing_data_flow": "workflow",
    "missing_derivation_step": "math",
    "missing_algorithm_detail": "algorithm",
    "missing_applicability_boundary": "applicability",
    "missing_conclusion_scope": "conclusion",
}


def understanding_gap_fixture(gap_type="missing_input_format"):
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
        "projection_type": UNDERSTANDING_GAP_PROJECTION_BY_TYPE[gap_type],
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
                "projection_type": UNDERSTANDING_GAP_PROJECTION_BY_TYPE[gap_type],
                "payload_digest": payload_digest,
            },
            "basis_refs": [
                {
                    "ref_type": "understanding_projection_path",
                    "projection_type": UNDERSTANDING_GAP_PROJECTION_BY_TYPE[gap_type],
                    "source_path": missing_fields[gap_type],
                    "payload_digest": payload_digest,
                }
            ],
        },
        "novelty_claimed": False,
    }
    gap["gap_digest"] = sha256_json(
        {key: value for key, value in gap.items() if key not in {"gap_id", "gap_digest"}}
    )
    gap["gap_id"] = f"understanding-gap-{gap['gap_digest'][:16]}"
    return gap


def request_set_fixture():
    base_request = validate_request(request_fixture())
    request_set = {
        "schema": "ScholarDiscoveryRequestSet/v1",
        "schema_version": "v1",
        "requests": [base_request],
        "network_id": "N-1",
        "network_snapshot_sha256": "a" * 64,
        "network_ref": {"network_id": "N-1", "snapshot_id": "S-1", "sha256": "a" * 64},
        "generated_at": "2026-08-05T00:10:00Z",
    }
    request_set["requests"] = [base_request]
    request_set["request_set_digest"] = request_set["request_set_id"] = ""
    return request_set_digest(request_set)


def request_set_digest(request_set):
    request_set["request_set_digest"] = sha256_json(
        {key: value for key, value in request_set.items() if key not in {"request_set_id", "request_set_digest"}}
    )
    request_set["request_set_id"] = f"request-set-{request_set['request_set_digest'][:16]}"
    return request_set


def candidate(title="A Study", doi="10.1000/ABC", rank=1, authors=None, year=2024):
    return {
        "title": title,
        "authors": authors or ["A. Author"],
        "year": year,
        "venue": "Journal",
        "identifiers": {"doi": doi} if doi else {},
        "work_type": "primary_study",
        "publication_status": "peer_reviewed",
        "access_level": "abstract_only",
        "landing_url": "https://doi.org/10.1000/abc",
        "native_rank": rank,
        "native_score": 99.0,
        "screening": {"decision": "include", "reason": "matches title"},
    }


def batch_fixture(request, query, candidates, status="succeeded"):
    return {
        "schema": "ScholarResultBatch/v1",
        "request_digest": sha256_json(request),
        "query_id": query["query_id"],
        "provider": query["provider"],
        "execution": query["execution"],
        "status": status,
        "accessed_at": "2026-08-05T00:05:00Z",
        "query": query["query"],
        "search_event": {
            "endpoint": query.get("endpoint_hint", query.get("search_url")),
            "redacted_request": {
                "query": query["query"],
                "provider": query["provider"],
                "route": "search",
            },
            "page_or_cursor": "1",
            "expected_total": len(candidates),
            "retrieved": len(candidates),
            "truncated": False,
            "response_sha256": "a" * 64,
            "limitations": [],
        },
        "candidates": candidates,
    }


class ScholarDiscoveryTest(unittest.TestCase):
    def test_compiles_domain_grounded_topic_needs_to_request_set(self):
        topic_needs = {
            "schema": "ResearchTopicNeedSet/v1",
            "schema_version": "v1",
            "topic_id": "doe-surrogate",
            "question": "Which sampling and surrogate routes fit morphology inverse problems?",
            "as_of": "2026-08-05T00:00:00Z",
            "google_scholar_policy": "manual_optional",
            "automatic_providers": ["crossref", "semantic_scholar"],
            "network_ref": {
                "network_id": "KN-DOE",
                "snapshot_id": "KN-DOE-S1",
                "sha256": "a" * 64,
            },
            "needs": [
                {
                    "gap_id": "gap-inverse-doe",
                    "paper_need": "Find adaptive surrogate designs for morphology inverse problems",
                    "criteria": {
                        "must": ["inverse problem", "surrogate"],
                        "should": ["adaptive sampling", "morphology"],
                        "must_not": ["unrelated clinical study"],
                    },
                    "query_seeds": [
                        {
                            "objective": "confirm",
                            "query": "inverse problem surrogate adaptive sampling morphology",
                        },
                        {
                            "objective": "refute",
                            "query": "inverse problem surrogate failure posterior bias limitation",
                        },
                    ],
                }
            ],
        }
        request_set = compile_topic_need_set(topic_needs)
        self.assertEqual(request_set["schema"], "ScholarDiscoveryRequestSet/v1")
        self.assertEqual(len(request_set["requests"]), 1)
        request = request_set["requests"][0]
        self.assertEqual(request["gap_hypothesis_id"], "gap-inverse-doe")
        self.assertNotIn("network dimension", json.dumps(request).lower())
        validate_request_set(request_set)

    def test_topic_compiler_rejects_structural_placeholder_query(self):
        topic_needs = {
            "schema": "ResearchTopicNeedSet/v1",
            "schema_version": "v1",
            "topic_id": "bad-topic",
            "question": "Bad structural topic",
            "as_of": "2026-08-05T00:00:00Z",
            "network_ref": {
                "network_id": "KN-1",
                "snapshot_id": "KN-1-S1",
                "sha256": "a" * 64,
            },
            "needs": [
                {
                    "gap_id": "gap-bad",
                    "paper_need": "Fill a missing field",
                    "criteria": {"must": ["network"], "should": [], "must_not": []},
                    "query_seeds": [
                        {"objective": "confirm", "query": "network dimension validation_target"},
                        {"objective": "refute", "query": "network dimension failure limitation"},
                    ],
                }
            ],
        }
        with self.assertRaisesRegex(ContractError, "structural placeholder"):
            compile_topic_need_set(topic_needs)

    def test_preflight_reports_provider_and_manual_scholar_without_secrets(self):
        request_set = request_set_fixture()
        with mock.patch.dict(
            os.environ,
            {"OPENALEX_API_KEY": "", "SEMANTIC_SCHOLAR_API_KEY": "secret-value"},
            clear=False,
        ):
            preflight = build_preflight(request_set)
        openalex = next(
            row for row in preflight["automatic_providers"] if row["provider"] == "openalex"
        )
        self.assertFalse(openalex["configured"])
        self.assertEqual(preflight["google_scholar"]["automatic"], False)
        self.assertNotIn("secret-value", json.dumps(preflight))

    def test_compiles_all_understanding_gap_types_to_targeted_queries(self):
        query_pairs = set()
        for gap_type in UNDERSTANDING_GAP_PROJECTION_BY_TYPE:
            with self.subTest(gap_type=gap_type):
                gap = understanding_gap_fixture(gap_type)
                request = compile_understanding_gap_request(
                    gap, as_of="2026-08-05T00:00:00Z"
                )
                self.assertEqual(request["understanding_gap"], gap)
                self.assertEqual(request["paper_need"], gap["question"])
                self.assertEqual(request["criteria"], gap["search_terms"])
                self.assertEqual(
                    [item["objective"] for item in request["query_seeds"]],
                    ["confirm", "refute"],
                )
                for item in request["query_seeds"]:
                    self.assertNotIn(gap["missing_field"], item["query"])
                    self.assertNotIn("workflow.graph", item["query"])
                query_pairs.add(
                    tuple(item["query"] for item in request["query_seeds"])
                )
        self.assertEqual(len(query_pairs), len(UNDERSTANDING_GAP_PROJECTION_BY_TYPE))

    def test_understanding_gap_provenance_is_bound_into_request_digest(self):
        first_gap = understanding_gap_fixture("missing_data_flow")
        first = compile_understanding_gap_request(
            first_gap, as_of="2026-08-05T00:00:00Z"
        )
        second_gap = copy.deepcopy(first_gap)
        second_gap["provenance"]["projection_ref"]["projection_digest"] = "e" * 64
        second_gap["provenance"]["projection_ref"]["projection_id"] = (
            "understanding-projection-eeeeeeeeeeeeeeee"
        )
        second_gap["gap_digest"] = sha256_json(
            {
                key: value
                for key, value in second_gap.items()
                if key not in {"gap_id", "gap_digest"}
            }
        )
        second_gap["gap_id"] = f"understanding-gap-{second_gap['gap_digest'][:16]}"
        second = compile_understanding_gap_request(
            second_gap, as_of="2026-08-05T00:00:00Z"
        )
        self.assertNotEqual(sha256_json(first), sha256_json(second))
        self.assertEqual(second["understanding_gap"]["provenance"], second_gap["provenance"])

    def test_understanding_gap_request_cannot_fill_or_rewrite_semantics(self):
        gap = understanding_gap_fixture("missing_algorithm_detail")
        request = compile_understanding_gap_request(
            gap, as_of="2026-08-05T00:00:00Z"
        )
        rewritten = copy.deepcopy(request)
        rewritten["query_seeds"][0]["query"] += " inferred answer"
        with self.assertRaisesRegex(ContractError, "canonical targeted queries"):
            validate_request(rewritten)

        filled = copy.deepcopy(request)
        filled["resolved_value"] = "invented algorithm step"
        with self.assertRaisesRegex(ContractError, "bounded discovery fields"):
            validate_request(filled)

    def test_understanding_gap_compiler_translates_foreign_contract_errors(self):
        invalid = understanding_gap_fixture("missing_conclusion_scope")
        invalid["gap_type"] = "missing_invented_semantics"
        invalid["gap_digest"] = sha256_json(
            {
                key: value
                for key, value in invalid.items()
                if key not in {"gap_id", "gap_digest"}
            }
        )
        invalid["gap_id"] = f"understanding-gap-{invalid['gap_digest'][:16]}"
        with self.assertRaisesRegex(ContractError, "invalid PaperUnderstanding gap"):
            compile_understanding_gap_request(
                invalid, as_of="2026-08-05T00:00:00Z"
            )

    def test_understanding_gap_compiler_rejects_private_query_material(self):
        gap = understanding_gap_fixture("missing_data_flow")
        gap["search_terms"]["must"] = ["/private/user/source.pdf"]
        gap["gap_digest"] = sha256_json(
            {
                key: value
                for key, value in gap.items()
                if key not in {"gap_id", "gap_digest"}
            }
        )
        gap["gap_id"] = f"understanding-gap-{gap['gap_digest'][:16]}"
        with self.assertRaisesRegex(ContractError, "private paths|internal IDs"):
            compile_understanding_gap_request(
                gap, as_of="2026-08-05T00:00:00Z"
            )

    def test_rejects_automatic_google_scholar(self):
        request = request_fixture()
        request["routes"]["automatic"].append("google_scholar")
        with self.assertRaises(ContractError):
            validate_request(request)

    def test_plan_has_api_and_manual_scholar_routes(self):
        plan = compile_plan(request_fixture())
        providers = {row["provider"] for row in plan["queries"]}
        self.assertEqual(
            providers,
            {"openalex", "crossref", "semantic_scholar", "google_scholar"},
        )
        scholar = next(row for row in plan["queries"] if row["provider"] == "google_scholar")
        self.assertEqual(scholar["execution"], "user_manual_export")
        self.assertIn("scholar.google.com/scholar?", scholar["search_url"])

    def test_validate_plan_rejects_query_plan_mutations(self):
        request = request_fixture()
        plan = compile_plan(request)
        changed = copy.deepcopy(plan)
        changed["queries"][0]["query"] = "mutated query"
        with self.assertRaises(ContractError):
            validate_plan(changed, request)

    def test_validate_plan_rejects_noncanonical_endpoint(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        changed = copy.deepcopy(plan)
        changed["queries"][0]["endpoint_hint"] = "https://example.com/works"
        with self.assertRaises(ContractError):
            validate_plan(changed, request)

    def test_google_batch_requires_manual_export_origin(self):
        request = request_fixture()
        plan = compile_plan(request)
        query = next(row for row in plan["queries"] if row["provider"] == "google_scholar")
        batch = batch_fixture(request, query, [], status="blocked")
        with self.assertRaises(ContractError):
            validate_batch(batch, {query["query_id"]: query})
        batch["search_event"]["artifact_origin"] = "not_provided_manual_optional"
        validate_batch(batch, {query["query_id"]: query})
        batch["search_event"]["artifact_origin"] = "user_supplied_manual_export"
        with self.assertRaises(ContractError):
            validate_batch(batch, {query["query_id"]: query})
        batch["search_event"]["artifact_origin"] = "not_provided_manual_required"
        with self.assertRaises(ContractError):
            validate_batch(batch, {query["query_id"]: query})

    def test_plan_normalizes_providers_and_removes_duplicates(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["OpenAlex", "crossref", "openalex", "semantic_scholar"]
        request["routes"]["google_scholar"] = "manual_required"
        validated = validate_request(request)
        self.assertEqual(
            validated["routes"]["automatic"],
            ["openalex", "crossref", "semantic_scholar"],
        )

    def test_arxiv_version_normalization_merges_manifestation(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        q1, q2 = plan["queries"][0], plan["queries"][1]
        arxiv_v1 = candidate(title="V1", doi=None, rank=1)
        arxiv_v2 = candidate(title="V2", doi=None, rank=2)
        arxiv_v1["identifiers"] = {"arxiv": "2101.00001v2"}
        arxiv_v2["identifiers"] = {"arxiv": "2101.00001v3"}
        result = build_result(
            request,
            plan,
            [batch_fixture(request, q1, [arxiv_v1]), batch_fixture(request, q2, [arxiv_v2])],
        )
        self.assertEqual(len(result["ranked_candidates"]), 1)
        self.assertEqual(result["ranked_candidates"][0]["identifiers"].get("arxiv"), "2101.00001")

    def test_doi_and_arxiv_manifestations_do_not_auto_merge_without_strong_id(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        request["routes"]["automatic"] = ["openalex"]
        plan = compile_plan(request)
        q1, q2 = plan["queries"][0], plan["queries"][1]
        doi_item = candidate(doi="10.1000/ABC", title="Shared Work", authors=["Lead", "Co"], year=2024)
        arxiv_item = candidate(
            title="Shared Work",
            doi=None,
            rank=2,
            authors=["Lead", "Co"],
        )
        arxiv_item["identifiers"] = {"arxiv": "2101.00002v2"}
        result = build_result(
            request,
            plan,
            [batch_fixture(request, q1, [doi_item]), batch_fixture(request, q2, [arxiv_item])],
        )
        self.assertEqual(len(result["ranked_candidates"]), 2)
        for item in result["ranked_candidates"]:
            self.assertIn("possible_duplicate", item["quality_flags"])
            self.assertIn("needs_review", item["quality_flags"])
            self.assertEqual(item["work_family_manifestation_count"], 1)

    def test_weak_duplicate_flags_apply_only_to_matching_families(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        request["routes"]["automatic"] = ["openalex"]
        plan = compile_plan(request)
        q1, q2 = plan["queries"][0], plan["queries"][1]

        batch_one = batch_fixture(
            request,
            q1,
            [
                candidate(title="Weak Match Title", doi=None, authors=["Lee"], year=2024),
                candidate(title="Unique A", doi="10.1000/one", authors=["Unique"], year=2021),
            ],
        )
        batch_two = batch_fixture(
            request,
            q2,
            [
                candidate(title="Weak Match Title", doi=None, rank=2, authors=["Lee"], year=2024),
                candidate(title="Unique B", doi="10.1000/two", rank=2, authors=["Diff"], year=2022),
            ],
        )
        result = build_result(request, plan, [batch_one, batch_two])
        flagged = [
            item for item in result["ranked_candidates"] if "possible_duplicate" in item["quality_flags"]
        ]
        self.assertEqual(len(flagged), 2)
        self.assertEqual(
            {item["title"] for item in flagged},
            {"Weak Match Title"},
        )
        unflagged_titles = {
            item["title"] for item in result["ranked_candidates"] if "possible_duplicate" not in item["quality_flags"]
        }
        self.assertEqual(unflagged_titles, {"Unique A", "Unique B"})

    def test_multiple_weak_duplicate_groups_do_not_overmark_non_weak_families(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        request["routes"]["automatic"] = ["openalex"]
        plan = compile_plan(request)
        q1, q2 = plan["queries"][0], plan["queries"][1]

        batch_one = batch_fixture(
            request,
            q1,
            [
                candidate(title="Weak Alpha", doi=None, authors=["Alpha"], year=2024),
                candidate(title="Weak Beta", doi=None, rank=2, authors=["Beta"], year=2023),
                candidate(title="Unique Left", doi="10.1000/left", authors=["Only"], year=2020),
            ],
        )
        batch_two = batch_fixture(
            request,
            q2,
            [
                candidate(title="Weak Alpha", doi=None, rank=2, authors=["Alpha"], year=2024),
                candidate(title="Weak Beta", doi=None, rank=3, authors=["Beta"], year=2023),
                candidate(title="Unique Right", doi="10.1000/right", rank=2, authors=["Only2"], year=2021),
            ],
        )
        result = build_result(request, plan, [batch_one, batch_two])
        flagged = [
            item["title"]
            for item in result["ranked_candidates"]
            if "possible_duplicate" in item["quality_flags"]
        ]
        self.assertEqual(
            sorted(flagged),
            ["Weak Alpha", "Weak Alpha", "Weak Beta", "Weak Beta"],
        )
        unflagged = [
            item["title"]
            for item in result["ranked_candidates"]
            if "possible_duplicate" not in item["quality_flags"]
        ]
        self.assertEqual(sorted(unflagged), ["Unique Left", "Unique Right"])

    def test_retraction_propagates_within_family(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        request["routes"]["automatic"] = ["openalex"]
        plan = compile_plan(request)
        q1, q2 = plan["queries"][0], plan["queries"][1]
        clean = candidate(title="Merged Work", doi="10.1000/clean", authors=["One"], year=2022)
        retracted = candidate(
            title="Merged Work", doi="10.1000/clean", rank=2, authors=["One"], year=2022
        )
        retracted["publication_status"] = "retracted"
        result = build_result(
            request,
            plan,
            [batch_fixture(request, q1, [clean]), batch_fixture(request, q2, [retracted])],
        )
        self.assertEqual(len(result["ranked_candidates"]), 1)
        candidate_item = result["ranked_candidates"][0]
        self.assertEqual(candidate_item["screening"]["decision"], "exclude")
        self.assertIn("retracted_or_withdrawn", candidate_item["quality_flags"])

    def test_manual_optional_is_not_a_partial_provider(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "manual_optional"
        plan = compile_plan(request)
        batches = []
        for query in plan["queries"]:
            if query["provider"] == "google_scholar":
                manual_batch = batch_fixture(request, query, [], status="blocked")
                manual_batch["search_event"]["limitations"] = ["manual_export_not_provided"]
                manual_batch["search_event"]["artifact_origin"] = "not_provided_manual_optional"
                batches.append(manual_batch)
            else:
                batches.append(
                    batch_fixture(
                        request,
                        query,
                        [candidate()],
                    )
                )

        result = build_result(request, plan, batches)
        self.assertEqual(result["discovery_status"], "complete_bounded")
        self.assertEqual(result["unresolved_query_ids"], [])

    def test_validate_result_set_rejects_results_without_gap_hypothesis(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        request["routes"]["automatic"] = ["openalex"]
        plan = compile_plan(request)
        result = build_result(request, plan, [batch_fixture(request, plan["queries"][0], [candidate()])])
        request_set = request_set_fixture()

        result_set = {
            "schema": "ScholarDiscoveryResultSet/v1",
            "schema_version": "v1",
            "request_set_id": request_set["request_set_id"],
            "request_set_digest": request_set["request_set_digest"],
            "network_id": "N-1",
            "network_snapshot_sha256": "a" * 64,
            "network_ref": {"network_id": "N-1", "snapshot_id": "S-1", "sha256": "a" * 64},
            "results": [result],
            "failures": [],
        }
        with self.assertRaises(ContractError):
            validate_result_set(result_set)

    def test_validate_result_set_rejects_results_without_canonical_hypothesis_id(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        request["routes"]["automatic"] = ["openalex"]
        plan = compile_plan(request)
        result = build_result(request, plan, [batch_fixture(request, plan["queries"][0], [candidate()])])
        result["gap_hypothesis_id"] = "GAP-1"
        request_set = request_set_fixture()

        result_set = {
            "schema": "ScholarDiscoveryResultSet/v1",
            "schema_version": "v1",
            "request_set_id": request_set["request_set_id"],
            "request_set_digest": request_set["request_set_digest"],
            "network_id": "N-1",
            "network_snapshot_sha256": "a" * 64,
            "network_ref": {"network_id": "N-1", "snapshot_id": "S-1", "sha256": "a" * 64},
            "results": [result],
            "failures": [],
        }
        with self.assertRaises(ContractError):
            validate_result_set(result_set)

    def test_validate_result_set_rejects_mismatched_result_hypothesis_id(self):
        request_set = request_set_fixture()

        def transport(url: str, timeout: int) -> bytes:
            return b'{"meta":{"count":0},"results":[]}'

        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "unit-test-key"}):
            result_set = execute_request_set(request_set, transport, timeout_seconds=30)
        result_set["results"][0]["hypothesis_id"] = "ANOTHER-HYP"
        with self.assertRaises(ContractError):
            validate_result_set(result_set)

    def test_partial_budget_tracks_query_budget(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "disabled"
        request["budgets"]["max_queries"] = 1
        plan = compile_plan(request)
        self.assertTrue(plan["truncation"]["query_budget_reached"])
        first_query = plan["queries"][0]
        batch = batch_fixture(request, first_query, [], status="empty")
        batch["search_event"]["retrieved"] = 0
        result = build_result(request, plan, [batch])
        self.assertEqual(result["discovery_status"], "partial_budget")
        self.assertTrue(result["limits"]["query_budget_reached"])
        self.assertEqual(len(result["limits"]["missing_query_ids"]), 1)

    def test_partial_budget_tracks_candidate_budget(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "disabled"
        request["budgets"]["max_candidates"] = 1
        plan = compile_plan(request)
        first_query = plan["queries"][0]
        batch = batch_fixture(
            request,
            first_query,
            [candidate(), candidate(doi="10.1000/def", rank=2)],
        )
        result = build_result(request, plan, [batch])
        self.assertEqual(result["discovery_status"], "partial_budget")

    def test_candidate_budget_not_reached_at_exact_limit(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "disabled"
        request["budgets"]["max_candidates"] = 2
        plan = compile_plan(request)
        batch = batch_fixture(
            request,
            plan["queries"][0],
            [candidate(doi="10.1000/one")],
        )
        batch_two = batch_fixture(
            request,
            plan["queries"][1],
            [candidate(doi="10.1000/two", title="Another", rank=1, authors=["Different"])],
        )
        result = build_result(request, plan, [batch, batch_two])
        self.assertEqual(result["discovery_status"], "complete_bounded")
        self.assertFalse(result["limits"]["candidate_budget_reached"])
        self.assertEqual(len(result["ranked_candidates"]), 2)

    def test_partial_provider_from_openalex_truncation(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "disabled"
        request_set = request_set_fixture()
        request_set["requests"] = [validate_request(request)]
        request_set_digest(request_set)

        openalex_payload = {
            "meta": {"count": 3},
            "results": [
                {
                    "title": "OpenAlex Work",
                    "authorships": [{"author": {"display_name": "Alice"}}],
                    "publication_year": 2025,
                    "host_venue": {"display_name": "Open Journal"},
                    "doi": "10.1000/openalex",
                    "ids": {"openalex": "W123"},
                    "type": "article",
                    "is_retracted": False,
                    "abstract_inverted_index": {"a": [1]},
                    "primary_location": {"landing_page_url": "https://example.org/openalex"},
                }
            ],
        }

        def transport(url: str, timeout: int) -> bytes:
            return json.dumps(openalex_payload).encode("utf-8")

        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "unit-test-key"}):
            result_set = execute_request_set(request_set, transport, timeout_seconds=30)
        result = result_set["results"][0]
        self.assertEqual(result["discovery_status"], "partial_provider")
        self.assertEqual(result["provider_failures"][0]["status"], "partial")
        self.assertIn("results_truncated", result["provider_failures"][0]["limitations"])

    def test_batch_rejects_raw_secret_and_fulltext_leaks(self):
        request = request_fixture()
        plan = compile_plan(request)
        query = plan["queries"][0]

        query_batch = batch_fixture(request, query, [])
        with self.assertRaises(ContractError):
            query_batch["search_event"]["redacted_request"]["secret"] = "token"
            validate_batch(query_batch, {query["query_id"]: query})

        query_batch = batch_fixture(request, query, [])
        with self.assertRaises(ContractError):
            query_batch["search_event"]["raw"] = "should be rejected"
            validate_batch(query_batch, {query["query_id"]: query})

        query_batch = batch_fixture(request, query, [])
        with self.assertRaises(ContractError):
            candidate_item = candidate()
            candidate_item["raw"] = {"blob": "raw payload"}
            query_batch["candidates"] = [candidate_item]
            validate_batch(query_batch, {query["query_id"]: query})

    def test_batch_rejects_snippet_body(self):
        request = request_fixture()
        plan = compile_plan(request)
        query = plan["queries"][0]
        item = candidate()
        item["snippet"] = "untrusted search prose"
        batch = batch_fixture(request, query, [item])
        with self.assertRaises(ContractError):
            validate_batch(batch, {query["query_id"]: query})

    def test_batch_rejects_forbidden_search_event_credentials(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        query = plan["queries"][0]

        query_batch = batch_fixture(request, query, [])
        with self.assertRaises(ContractError):
            query_batch["search_event"]["redacted_request"]["query"] = "api_key=abc&query=title"
            validate_batch(query_batch, {query["query_id"]: query})

        query_batch = batch_fixture(request, query, [])
        with self.assertRaises(ContractError):
            query_batch["search_event"]["redacted_request"]["query"] = "password=abc&query=title"
            validate_batch(query_batch, {query["query_id"]: query})

        query_batch = batch_fixture(request, query, [])
        with self.assertRaises(ContractError):
            query_batch["search_event"]["endpoint"] = "https://api.openalex.org/works?token=abc"
            validate_batch(query_batch, {query["query_id"]: query})

    def test_batch_rejects_invalid_doi_identifier(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        query = plan["queries"][0]

        invalid = candidate(doi="s0005109898002234")
        batch = batch_fixture(request, query, [invalid])
        with self.assertRaises(ContractError):
            validate_batch(batch, {query["query_id"]: query})

    def test_same_doi_merges_and_preserves_routes(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        q1, q2 = plan["queries"][0], plan["queries"][1]
        b1 = batch_fixture(request, q1, [candidate(doi="https://doi.org/10.1000/ABC")])
        b2 = batch_fixture(request, q2, [candidate(doi="doi:10.1000/abc", rank=2)])
        result = build_result(request, plan, [b2, b1])
        self.assertEqual(len(result["ranked_candidates"]), 1)
        merged = result["ranked_candidates"][0]
        self.assertEqual(merged["identifiers"]["doi"], "10.1000/abc")
        self.assertEqual(len(merged["discovery_provenance"]), 2)
        self.assertFalse(merged["claim_support_eligible"])

    def test_same_title_different_authors_does_not_merge(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        q1, q2 = plan["queries"]
        b1 = batch_fixture(request, q1, [candidate(doi=None, authors=["Alice"])])
        b2 = batch_fixture(request, q2, [candidate(doi=None, authors=["Bob"])])
        result = build_result(request, plan, [b1, b2])
        self.assertEqual(len(result["ranked_candidates"]), 2)

    def test_retraction_is_visible_and_excluded(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        item = candidate()
        item["publication_status"] = "retracted"
        batch = batch_fixture(request, plan["queries"][0], [item])
        result = build_result(request, plan, [batch])
        self.assertIn(
            "retracted_or_withdrawn", result["ranked_candidates"][0]["quality_flags"]
        )
        self.assertEqual(result["exclusions"][0]["reason"], "retracted_or_withdrawn")

    def test_blocked_route_is_not_empty_proof(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["openalex"]
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        blocked = batch_fixture(request, plan["queries"][0], [], status="blocked")
        result = build_result(request, plan, [blocked])
        self.assertEqual(result["discovery_status"], "blocked_capability")
        self.assertIn(plan["queries"][0]["query_id"], result["unresolved_query_ids"])

    def test_output_is_deterministic_across_batch_order(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        plan = compile_plan(request)
        batches = [
            batch_fixture(request, plan["queries"][0], [candidate()]),
            batch_fixture(request, plan["queries"][1], [candidate(rank=3)]),
        ]
        self.assertEqual(
            build_result(request, plan, batches),
            build_result(
                copy.deepcopy(request),
                copy.deepcopy(plan),
                list(reversed(batches)),
            ),
        )

    def test_query_url_openalex_uses_search_filter_and_per_page(self):
        url = _query_url_openalex(
            "WENDy weak form sparse identification",
            {"years": {"from": 2015, "to": 2022}},
        )
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertIn("search", query)
        self.assertEqual(
            query["search"][0], "WENDy weak form sparse identification"
        )
        self.assertEqual(query["filter"][0], "publication_year:2015-2022")
        self.assertEqual(query["per-page"][0], "10")
        self.assertNotIn("api_key", query)

    def test_query_url_crossref_bibliographic_title_query(self):
        url = _query_url_crossref(
            "WENDy weak form",
            {"years": {"from": 2018, "to": 2024}},
        )
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertIn("query.title", query)
        self.assertNotIn("query", query)
        self.assertEqual(query["query.title"][0], "WENDy weak form")
        self.assertEqual(query["rows"][0], "10")
        self.assertIn("filter", query)
        self.assertIn("from-pub-date:2018-01-01", query["filter"][0])
        self.assertIn("until-pub-date:2024-12-31", query["filter"][0])

    def test_query_url_semantic_scholar_graph_search_route(self):
        url = _query_url_semantic_scholar(
            "WENDy sparse identification",
            {"years": {"from": 2015, "to": 2022}},
        )
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertIn("query", query)
        self.assertEqual(query["query"][0], "WENDy sparse identification")
        self.assertEqual(query["limit"][0], "10")
        self.assertIn("fields", query)

    def test_http_transport_attaches_user_agent(self):
        captured = {}

        class _FakeResponse:
            def __init__(self, payload: bytes = b"{}"):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def read(self):
                return self.payload

        def fake_urlopen(request: object, timeout: int = 30) -> _FakeResponse:
            captured["headers"] = dict(request.header_items())
            captured["url"] = request.full_url
            return _FakeResponse(b'{"ok":true}')

        with mock.patch("scholar_discovery.urllib.request.urlopen", side_effect=fake_urlopen):
            _http_transport("https://api.semanticscholar.org/graph/v1/paper/search?query=test")
        normalized_headers = {key.casefold(): value for key, value in captured["headers"].items()}
        self.assertEqual(normalized_headers.get("user-agent"), HTTP_USER_AGENT)
        self.assertEqual(normalized_headers.get("accept"), "application/json")
        self.assertEqual(captured["url"], "https://api.semanticscholar.org/graph/v1/paper/search?query=test")
        self.assertNotIn("x-api-key", captured["headers"])

        captured = {}
        with mock.patch.dict(os.environ, {"SEMANTIC_SCHOLAR_API_KEY": "test-semantic-key"}):
            with mock.patch("scholar_discovery.urllib.request.urlopen", side_effect=fake_urlopen):
                _http_transport("https://api.semanticscholar.org/graph/v1/paper/search?query=test")
        normalized_headers = {key.casefold(): value for key, value in captured["headers"].items()}
        self.assertEqual(normalized_headers.get("x-api-key"), "test-semantic-key")

    def test_validate_request_set_and_execute_request_set(self):
        request_set = request_set_fixture()

        def transport(url: str, timeout: int) -> bytes:
            if "openalex" in url:
                return b'{"meta":{"count":0},"results":[]}'
            if "crossref" in url:
                return b'{"message":{"total-results":0,"items":[]}}'
            return b"{}"

        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "unit-test-key"}):
            result_set = execute_request_set(request_set, transport, timeout_seconds=30)
        self.assertEqual(result_set["schema"], "ScholarDiscoveryResultSet/v1")
        self.assertEqual(result_set["schema_version"], "v1")
        self.assertTrue(result_set["request_set_id"].startswith("request-set-"))
        self.assertEqual(result_set["request_set_digest"], request_set["request_set_digest"])
        self.assertEqual(result_set["network_ref"], request_set["network_ref"])
        self.assertEqual(len(result_set["results"]), 1)
        self.assertEqual(result_set["results"][0]["request_id"], request_set["requests"][0]["request_id"])
        self.assertEqual(result_set["results"][0]["hypothesis_id"], "GAP-1")
        self.assertEqual(result_set["results"][0]["gap_hypothesis_id"], "GAP-1")
        self.assertEqual(result_set["request_count"], 1)

    def test_validate_request_set_rejects_tampered_digest_or_missing_fields(self):
        request_set = request_set_fixture()
        validate_request_set(request_set)
        bad_digest = request_set_fixture()
        bad_digest["request_set_digest"] = "f" * 64
        with self.assertRaises(ContractError):
            validate_request_set(bad_digest)

        missing_ref = request_set_fixture()
        missing_ref["network_ref"]["network_id"] = "N-2"
        with self.assertRaises(ContractError):
            validate_request_set(missing_ref)

        bad_snapshot = request_set_fixture()
        bad_snapshot["network_snapshot_sha256"] = "f" * 64
        with self.assertRaises(ContractError):
            validate_request_set(bad_snapshot)

        bad_id = request_set_fixture()
        bad_id["request_set_id"] = "request-set-" + "0" * 16
        with self.assertRaises(ContractError):
            validate_request_set(bad_id)

        no_ref = request_set_fixture()
        del no_ref["network_ref"]
        with self.assertRaises(ContractError):
            validate_request_set(no_ref)

    def test_openalex_blocks_execution_without_api_key(self):
        request_set = request_set_fixture()
        request_set["requests"][0]["routes"]["automatic"] = ["openalex"]
        request_set["requests"][0]["routes"]["google_scholar"] = "disabled"
        request_set_digest(request_set)
        called: list[str] = []

        def transport(url: str, timeout: int) -> bytes:
            called.append(url)
            return b'{"meta":{"count":1},"results":[]}'

        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": ""}, clear=False):
            result_set = execute_request_set(request_set, transport, timeout_seconds=30)

        result = result_set["results"][0]
        self.assertEqual(len(called), 0)
        self.assertEqual(len(result["provider_failures"]), 2)
        self.assertEqual(result["provider_failures"][0]["status"], "blocked")
        self.assertIn("blocked_configuration", result["provider_failures"][0]["limitations"])
        self.assertIn("missing_api_key", result["provider_failures"][0]["limitations"])
        self.assertEqual(result["provider_failures"][1]["status"], "blocked")
        self.assertIn("blocked_configuration", result["provider_failures"][1]["limitations"])
        self.assertIn("missing_api_key", result["provider_failures"][1]["limitations"])

    def test_execute_request_set_transports_openalex_and_crossref(self):
        request_set = request_set_fixture()
        request_set["requests"][0]["routes"]["automatic"] = ["openalex", "crossref"]
        request_set["requests"][0]["routes"]["google_scholar"] = "disabled"
        request_set_digest(request_set)
        called_urls: list[str] = []

        openalex_payload = {
            "meta": {"count": 1},
            "results": [
                {
                    "title": "OpenAlex Work",
                    "authorships": [{"author": {"display_name": "Alice"}}],
                    "publication_year": 2025,
                    "host_venue": {"display_name": "Open Journal"},
                    "doi": "10.1000/openalex",
                    "ids": {"openalex": "W123"},
                    "type": "article",
                    "is_retracted": False,
                    "abstract_inverted_index": {"a": [1]},
                    "primary_location": {"landing_page_url": "https://example.org/openalex"},
                }
            ],
        }

        crossref_payload = {
            "message": {
                "total-results": 1,
                "items": [
                    {
                        "title": ["Crossref Work"],
                        "author": [{"family": "Lee"}],
                        "issued": {"date-parts": [[2024]]},
                        "container-title": ["Crossref Journal"],
                        "DOI": "10.1000/crossref",
                        "type": "journal-article",
                        "URL": "https://example.org/crossref",
                    }
                ],
            }
        }

        def transport(url: str, timeout: int) -> bytes:
            called_urls.append(url)
            if "openalex" in url:
                return json.dumps(openalex_payload).encode("utf-8")
            if "crossref" in url:
                return json.dumps(crossref_payload).encode("utf-8")
            return b"{}"

        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "unit-test-key"}):
            result_set = execute_request_set(request_set, transport, timeout_seconds=30)
        self.assertEqual(result_set["results"][0]["discovery_status"], "complete_bounded")
        called = "\n".join(called_urls)
        self.assertIn("api.openalex.org/works", called)
        self.assertIn("api.crossref.org/works", called)
        self.assertEqual(len(called_urls), 4)

    def test_execute_request_set_transports_crossref_with_malformed_identifiers(self):
        request_set = request_set_fixture()
        request_set["requests"][0]["query_seeds"] = [
            {"objective": "confirm", "query": "WENDy weak form sparse identification"}
        ]
        request_set["requests"][0]["routes"]["automatic"] = ["crossref"]
        request_set["requests"][0]["routes"]["google_scholar"] = "disabled"
        request_set["requests"][0]["budgets"] = {
            "max_rounds": 1,
            "max_queries": 6,
            "max_candidates": 20,
            "timeout_seconds": 300,
        }
        request_set_digest(request_set)

        crossref_payload = {
            "message": {
                "total-results": 2,
                "items": [
                    {
                        "title": ["WENDy weak form"],
                        "author": [{"family": "Lee"}],
                        "issued": {"date-parts": [[2024]]},
                        "container-title": ["Crossref Journal"],
                        "DOI": "10.1000/valid",
                        "type": "journal-article",
                        "URL": "https://example.org/crossref-good",
                    },
                    {
                        "title": ["Malformed DOI Work"],
                        "author": [{"family": "Bad"}],
                    "issued": {"date-parts": [[2024]]},
                        "container-title": ["Crossref Journal"],
                        "DOI": "s0005109898002234",
                        "type": "journal-article",
                        "URL": "https://example.org/crossref-bad",
                    },
                ],
            }
        }

        def transport(url: str, timeout: int) -> bytes:
            self.assertIn("api.crossref.org/works", url)
            return json.dumps(crossref_payload).encode("utf-8")

        result_set = execute_request_set(request_set, transport, timeout_seconds=30)
        result = result_set["results"][0]
        self.assertEqual(result["discovery_status"], "complete_bounded")
        self.assertEqual(len(result["search_events"]), 1)
        search_event = result["search_events"][0]
        self.assertEqual(search_event["provider"], "crossref")
        self.assertEqual(search_event["status"], "success")
        self.assertIn("rejected_candidate_records", search_event["search_event"]["limitations"])
        self.assertEqual(search_event["search_event"].get("rejected_candidate_count"), 1)

        titles = [row["title"] for row in result["ranked_candidates"]]
        self.assertIn("WENDy weak form", titles)
        self.assertIn("Malformed DOI Work", titles)
        malformed = next(item for item in result["ranked_candidates"] if item["title"] == "Malformed DOI Work")
        self.assertNotIn("doi", malformed["identifiers"])
        valid = next(item for item in result["ranked_candidates"] if item["title"] == "WENDy weak form")
        self.assertEqual(valid["identifiers"].get("doi"), "10.1000/valid")

    def test_execute_request_set_transports_semantic_scholar(self):
        request_set = request_set_fixture()
        request_set["requests"][0]["routes"]["automatic"] = ["semantic_scholar"]
        request_set["requests"][0]["routes"]["google_scholar"] = "disabled"
        request_set_digest(request_set)
        called_urls: list[str] = []
        payload = {
            "total": 2,
            "data": [
                {
                    "paperId": "s2-12345",
                    "title": "Malformed DOI Work",
                    "year": 2024,
                    "authors": [{"name": "A Author"}],
                    "publicationTypes": ["JournalArticle"],
                    "venue": {"name": "AI Journal"},
                    "externalIds": {"DOI": "10.1000/wendy.001"},
                    "openAccessPdf": {"url": "https://example.org/open.pdf"},
                    "url": "https://www.semanticscholar.org/paper/123",
                },
                {
                    "paperId": "s2-67890",
                    "title": "Malformed DOI Row",
                    "year": 2024,
                    "authors": [{"name": "B Author"}],
                    "publicationTypes": ["JournalArticle"],
                    "venue": {"name": "AI Journal"},
                    "externalIds": {"DOI": "s0005109898002234"},
                    "openAccessPdf": {"url": "https://example.org/open2.pdf"},
                    "url": "https://www.semanticscholar.org/paper/456",
                }
            ],
        }

        def transport(url: str, timeout: int) -> bytes:
            called_urls.append(url)
            return json.dumps(payload).encode("utf-8")

        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "unit-test-key"}):
            result_set = execute_request_set(request_set, transport, timeout_seconds=30)
        result = result_set["results"][0]
        self.assertEqual(result["discovery_status"], "complete_bounded")
        self.assertEqual(len(called_urls), 2)
        self.assertIn("api.semanticscholar.org/graph/v1/paper/search", called_urls[0])
        self.assertEqual(len(result["ranked_candidates"]), 2)
        malformed = next(
            row
            for row in result["ranked_candidates"]
            if row["title"] == "Malformed DOI Row"
        )
        self.assertNotIn("doi", malformed["identifiers"])
        self.assertEqual(
            malformed["identifiers"].get("semantic_scholar"),
            "s2-67890",
        )
        valid = next(
            row for row in result["ranked_candidates"] if row["title"] == "Malformed DOI Work"
        )
        self.assertEqual(valid["identifiers"].get("semantic_scholar"), "s2-12345")
        self.assertEqual(valid["identifiers"].get("doi"), "10.1000/wendy.001")
        self.assertEqual(valid["access_level"], "abstract_only")

    def test_execute_request_set_records_transport_http_429(self):
        request = request_fixture()
        request["query_seeds"] = [{"objective": "confirm", "query": "WENDy weak form"}]
        request["routes"]["automatic"] = ["semantic_scholar"]
        request["routes"]["google_scholar"] = "disabled"
        request = validate_request(request)
        request_set = request_set_fixture()
        request_set["requests"] = [request]
        request_set_digest(request_set)

        def transport(url: str, timeout: int) -> bytes:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)

        result_set = execute_request_set(request_set, transport, timeout_seconds=30)
        result = result_set["results"][0]
        self.assertIn(result["discovery_status"], {"blocked_capability", "partial_provider"})
        self.assertEqual(len(result["provider_failures"]), 1)
        self.assertEqual(result["provider_failures"][0]["limitations"], ["transport_http_429"])

    @unittest.skipUnless(
        os.getenv("SCHOLAR_DISCOVERY_LIVE_SMOKE", "").strip().lower() in {"1", "true", "yes"},
        "set SCHOLAR_DISCOVERY_LIVE_SMOKE=1 to run live smoke",
    )
    def test_live_query_smoke_wendy_candidates(self):
        request = request_fixture()
        request["query_seeds"] = [
            {"objective": "confirm", "query": "WENDy system identification"}
        ]
        request["routes"]["automatic"] = ["crossref"]
        request["routes"]["google_scholar"] = "disabled"
        request_set = request_set_fixture()
        request_set["requests"] = [validate_request(request)]
        request_set_digest(request_set)

        result_set = execute_request_set(request_set, _http_transport, timeout_seconds=60)
        result = result_set["results"][0]
        if result["discovery_status"] == "blocked_capability":
            self.skipTest("live providers currently blocked (rate-limited or offline)")

        statuses = {row["status"] for row in result["search_events"] if row["provider"] == "crossref"}
        self.assertTrue({"success", "partial", "empty"} & statuses)

        titles = [candidate["title"].lower() for candidate in result["ranked_candidates"]]
        self.assertTrue(
            any(
                word in " ".join(titles)
                for word in ["wendy", "weak form", "sparse identification"]
            )
        )

    def test_manual_optional_queries_do_not_consume_autonomous_query_budget(self):
        request = request_fixture()
        request["routes"]["automatic"] = ["crossref"]
        request["routes"]["google_scholar"] = "manual_optional"
        request["budgets"]["max_queries"] = 1

        plan = compile_plan(request)
        automatic = [
            row for row in plan["queries"] if row["execution"] == "documented_api"
        ]
        manual = [
            row for row in plan["queries"] if row["execution"] == "user_manual_export"
        ]
        self.assertEqual(len(automatic), 1)
        self.assertEqual(len(manual), len(request["query_seeds"]))
        self.assertTrue(plan["truncation"]["query_budget_reached"])

if __name__ == "__main__":
    unittest.main()
