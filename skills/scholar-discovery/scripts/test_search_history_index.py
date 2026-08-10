import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import scholar_discovery as discovery


NOW = "2026-08-09T08:00:00Z"


def write_temp_json_artifact(
    directory: str, filename: str, value: object, pretty: bool = False
) -> tuple[str, str]:
    path = Path(directory) / filename
    text = json.dumps(
        value,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def request_set_file_sha256(request_set) -> str:
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
        request_set_path = temporary.name
    Path(request_set_path).chmod(0o600)
    try:
        return hashlib.sha256(Path(request_set_path).read_bytes()).hexdigest()
    finally:
        Path(request_set_path).unlink()


def execution_authority_file_artifact(execution_authority: dict) -> tuple[str, str]:
    raw = (
        json.dumps(
            execution_authority,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    with tempfile.NamedTemporaryFile("wb", delete=False) as temporary:
        temporary.write(raw)
        authority_file_path = Path(temporary.name)
    authority_file_path.chmod(0o600)
    return str(authority_file_path), hashlib.sha256(raw).hexdigest()


def execute_request_set_with_authority_file(
    request_set,
    transport,
    *,
    execution_authority,
    expected_execution_authority_sha256,
    request_set_file,
    request_set_file_sha256,
    execution_authority_file_sha256: str | None = None,
    timeout_seconds: int | None = None,
):
    authority_file_path, authority_file_sha256 = execution_authority_file_artifact(
        execution_authority
    )
    if execution_authority_file_sha256 is None:
        execution_authority_file_sha256 = authority_file_sha256
    try:
        return discovery.execute_request_set(
            request_set,
            transport,
            timeout_seconds=timeout_seconds,
            execution_authority=execution_authority,
            expected_execution_authority_sha256=expected_execution_authority_sha256,
            execution_authority_file=authority_file_path,
            execution_authority_file_sha256=execution_authority_file_sha256,
            request_set_file=request_set_file,
            request_set_file_sha256=request_set_file_sha256,
        )
    finally:
        Path(authority_file_path).unlink()


def transport_no_results(url: str, timeout_seconds: int | None = None) -> bytes:
    del timeout_seconds
    if "crossref" in url:
        return b'{"message":{"total-results":0,"items":[]}}'
    return b'{"total":0,"data":[]}'


def authority_manifest(
    *artifacts,
    execution_authority_contexts=None,
    artifact_file_sha256s=None,
):
    candidate = discovery.build_history_authority_candidate(
        list(artifacts),
        issued_at=NOW,
        execution_authority_contexts=execution_authority_contexts,
        artifact_file_sha256s=artifact_file_sha256s,
    )
    review = discovery.review_history_authority_candidate(
        candidate,
        reviewer_id="reviewer-independent-01",
        reviewer_role="independent history auditor",
        reviewed_at=NOW,
        complete_universe_attested=True,
        independent_reviewer_attested=True,
        execution_authority_contexts=execution_authority_contexts,
    )
    return (
        discovery.finalize_history_authority_manifest(candidate, review),
        review,
        candidate,
    )


def request_fixture():
    return {
        "schema": discovery.REQUEST_SCHEMA,
        "request_id": "SDR-ROUND06-FIXTURE",
        "paper_need": "Test dependent-input sensitivity allocations independently",
        "intent": "topic_set",
        "effort": "diligent",
        "criteria": {
            "must": ["dependent inputs", "Shapley effects"],
            "should": [],
            "must_not": [],
        },
        "metadata_filters": {
            "years": {"from": None, "to": None},
            "authors": [],
            "venues": [],
            "languages": [],
            "work_types": [],
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
            "automatic": ["crossref", "semantic_scholar"],
            "google_scholar": "manual_optional",
        },
        "budgets": {
            "max_rounds": 2,
            "max_queries": 12,
            "max_candidates": 100,
            "timeout_seconds": 900,
        },
        "query_seeds": [
            {
                "objective": "confirm",
                "query": "stable Shapley sensitivity allocation independently replicated for correlated variables",
            },
            {
                "objective": "refute",
                "query": "Shapley sensitivity ranking reverses for dependent inputs",
            },
        ],
        "as_of": NOW,
        "gap_ref": {"gap_id": "KGH-FIXTURE", "network_id": "KN-TEST"},
        "gap_hypothesis_id": "KGH-FIXTURE",
    }


def request_set_fixture(request):
    request_set = {
        "schema": discovery.REQUEST_SET_SCHEMA,
        "schema_version": "v1",
        "request_set_id": "",
        "request_set_digest": "",
        "network_id": "KN-TEST",
        "network_snapshot_sha256": "b" * 64,
        "network_ref": {
            "network_id": "KN-TEST",
            "snapshot_id": "KN-TEST-S1",
            "sha256": "b" * 64,
        },
        "generated_at": NOW,
        "requests": [request],
    }
    digest = discovery.canonical_request_set_digest(request_set)
    request_set["request_set_digest"] = digest
    request_set["request_set_id"] = f"request-set-{digest[:16]}"
    return request_set


def failure_result_set(request_set):
    return {
        "schema": discovery.RESULT_SET_SCHEMA,
        "schema_version": "v1",
        "request_set_id": request_set["request_set_id"],
        "request_set_digest": request_set["request_set_digest"],
        "network_id": "KN-TEST",
        "network_snapshot_sha256": "b" * 64,
        "network_ref": {
            "network_id": "KN-TEST",
            "snapshot_id": "KN-TEST-S1",
            "sha256": "b" * 64,
        },
        "generated_at": NOW,
        "results": [],
        "failures": [
            {
                "request_id": request_set["requests"][0]["request_id"],
                "error": "provider timeout",
            }
        ],
        "request_count": 1,
    }


def partial_result_fixture(request):
    plan = discovery.compile_plan(request)
    return {
        "schema": discovery.RESULT_SCHEMA,
        "request_id": request["request_id"],
        "request_digest": discovery.sha256_json(request),
        "plan_digest": discovery.sha256_json(plan),
        "discovery_status": "partial_provider",
        "query_plan": copy.deepcopy(plan["queries"]),
        "search_events": [
            {
                "query_id": row["query_id"],
                "status": "partial",
                "query": row["query"],
            }
            for row in plan["queries"]
        ],
        "ranked_candidates": [
            {
                "candidate_id": "candidate-fixturec",
                "title": "Fixture-c sensitivity analysis with dependent inputs",
                "discovery_only": True,
                "claim_support_eligible": False,
            }
        ],
        "provider_failures": [],
        "unresolved_query_ids": [],
    }


class SearchHistoryIndexTests(unittest.TestCase):
    def test_indexes_v2_result_only_with_external_execution_authority_context(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256 = write_temp_json_artifact(
                directory, "request_set.json", request_set
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )

            def transport(url, timeout):
                del timeout
                if "crossref" in url:
                    return b'{"message":{"total-results":0,"items":[]}}'
                return b'{"total":0,"data":[]}'

            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=authority_file_sha256,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            result_set_loaded = discovery.load_json(result_set_path)
            request_set_and_result_hashes = [
                request_set_file_sha256,
                result_set_file_sha256,
            ]
            contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": authority_file_sha256,
                    "execution_authority_file_sha256": authority_file_sha256,
                }
            }
            with self.assertRaisesRegex(
                discovery.ContractError, "external execution authorization context"
            ):
                discovery.build_history_authority_candidate(
                    [request_set_loaded, result_set_loaded],
                    issued_at=NOW,
                    artifact_file_sha256s=request_set_and_result_hashes,
                )
            candidate = discovery.build_history_authority_candidate(
                [request_set_loaded, result_set_loaded],
                issued_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=request_set_and_result_hashes,
            )
            approval = discovery.review_history_authority_candidate(
                candidate,
                reviewer_id="history-reviewer-v2",
                reviewer_role="independent history auditor",
                reviewed_at=NOW,
                complete_universe_attested=True,
                independent_reviewer_attested=True,
                execution_authority_contexts=contexts,
            )
            manifest = discovery.finalize_history_authority_manifest(candidate, approval)
            history = discovery.build_search_history_index(
                [request_set_loaded, result_set_loaded],
                manifest,
                approval,
                generated_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=request_set_and_result_hashes,
            )
            discovery.validate_search_history_index(
                history,
                manifest,
                approval,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=request_set_and_result_hashes,
            )
            self.assertIn(
                discovery.RESULT_SET_V2_SCHEMA,
                {row["schema"] for row in history["source_artifacts"]},
            )
            self.assertEqual(
                history["schema"], discovery.SEARCH_HISTORY_INDEX_V2_SCHEMA
            )
            self.assertTrue(
                all(
                    {"request_occurrence_id", "local_request_id", "request_scope_ref"}
                    <= set(row)
                    for row in history["entries"]
                )
            )

            downgraded = copy.deepcopy(result_set_loaded)
        downgraded["schema"] = discovery.RESULT_SET_SCHEMA
        del downgraded["execution_authorization_ref"]
        legacy_candidate = discovery.build_history_authority_candidate(
            [request_set_loaded, downgraded], issued_at=NOW
        )
        legacy_approval = discovery.review_history_authority_candidate(
            legacy_candidate,
            reviewer_id="history-reviewer-legacy",
            reviewer_role="independent history auditor",
            reviewed_at=NOW,
            complete_universe_attested=True,
            independent_reviewer_attested=True,
        )
        legacy_manifest = discovery.finalize_history_authority_manifest(
            legacy_candidate, legacy_approval
        )
        legacy_history = discovery.build_search_history_index(
            [request_set, downgraded],
            legacy_manifest,
            legacy_approval,
            generated_at=NOW,
        )
        self.assertFalse(
            [
                row
                for row in legacy_history["entries"]
                if row["source_ref"]["schema"] == discovery.RESULT_SET_SCHEMA
            ]
        )

    def test_v2_result_set_uses_raw_request_set_file_sha256_for_validation(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256 = write_temp_json_artifact(
                directory, "request_set.json", request_set, pretty=True
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            _, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": (
                        execution_authority_file_sha256
                    ),
                    "execution_authority_file_sha256": (
                        execution_authority_file_sha256
                    ),
                }
            }
            artifact_file_sha256s = [
                request_set_file_sha256,
                result_set_file_sha256,
            ]
            candidate = discovery.build_history_authority_candidate(
                [
                    discovery.load_json(request_set_path),
                    discovery.load_json(result_set_path),
                ],
                issued_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=artifact_file_sha256s,
            )
            approval = discovery.review_history_authority_candidate(
                candidate,
                reviewer_id="history-reviewer-v2",
                reviewer_role="independent history auditor",
                reviewed_at=NOW,
                complete_universe_attested=True,
                independent_reviewer_attested=True,
                execution_authority_contexts=contexts,
            )
            manifest = discovery.finalize_history_authority_manifest(
                candidate, approval
            )
            history = discovery.build_search_history_index(
                [
                    discovery.load_json(request_set_path),
                    discovery.load_json(result_set_path),
                ],
                manifest,
                approval,
                generated_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=artifact_file_sha256s,
            )
            discovery.validate_search_history_index(
                history,
                manifest,
                approval,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=artifact_file_sha256s,
            )
            self.assertIn(
                discovery.RESULT_SET_V2_SCHEMA,
                {row["schema"] for row in history["source_artifacts"]},
            )

    def test_v2_index_replays_sorted_artifact_file_shas(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256_value = write_temp_json_artifact(
                directory, "request_set.json", request_set
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256_value,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256_value,
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": (
                        execution_authority_file_sha256
                    ),
                    "execution_authority_file_sha256": (
                        execution_authority_file_sha256
                    ),
                }
            }
            unsorted_artifacts = [
                discovery.load_json(result_set_path),
                discovery.load_json(request_set_path),
            ]
            unsorted_file_shas = [
                result_set_file_sha256,
                request_set_file_sha256_value,
            ]
            artifact_rows = sorted(
                [
                    (artifact, file_sha)
                    for artifact, file_sha in zip(
                        unsorted_artifacts, unsorted_file_shas
                    )
                ],
                key=lambda row: (row[0]["schema"], discovery.sha256_json(row[0])),
            )
            expected_source_artifacts = [
                {
                    "schema": row[0]["schema"],
                    "sha256": discovery.sha256_json(row[0]),
                }
                for row in artifact_rows
            ]
            authority, approval, _ = authority_manifest(
                *unsorted_artifacts,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=unsorted_file_shas,
            )
            history = discovery.build_search_history_index(
                unsorted_artifacts,
                authority,
                approval,
                generated_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=unsorted_file_shas,
            )
            reversed_history = discovery.build_search_history_index(
                list(reversed(unsorted_artifacts)),
                authority,
                approval,
                generated_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=list(reversed(unsorted_file_shas)),
            )
            self.assertEqual(history["source_artifacts"], expected_source_artifacts)
            self.assertEqual(
                history["history_digest"], reversed_history["history_digest"]
            )
            self.assertIn(
                discovery.RESULT_SET_V2_SCHEMA,
                {row["schema"] for row in history["source_artifacts"]},
            )

    def test_v2_index_rejects_pretty_request_set_file_sha_mismatch(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            pretty_request_set_path, pretty_request_set_file_sha256 = (
                write_temp_json_artifact(
                    directory, "request_set.json", request_set, pretty=True
                )
            )
            request_set_loaded = discovery.load_json(pretty_request_set_path)
            canonical_request_set_file_sha = request_set_file_sha256(request_set)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=pretty_request_set_path,
                request_set_file_sha256=pretty_request_set_file_sha256,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=pretty_request_set_path,
                request_set_file_sha256=pretty_request_set_file_sha256,
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            authority, approval, _ = authority_manifest(
                request_set_loaded,
                discovery.load_json(result_set_path),
                execution_authority_contexts={
                    execution_authority["authorization_id"]: {
                        "authorization": execution_authority,
                        "expected_execution_authority_sha256": (
                            execution_authority_file_sha256
                        ),
                        "execution_authority_file_sha256": (
                            execution_authority_file_sha256
                        ),
                    }
                },
                artifact_file_sha256s=[
                    pretty_request_set_file_sha256,
                    result_set_file_sha256,
                ],
            )
            with self.assertRaisesRegex(
                discovery.ContractError,
                "search execution authorization is not the owner-replayed exact "
                "request-set binding|result_set.execution_authorization_ref is not the "
                "owner-replayed authorization projection",
            ):
                discovery.build_search_history_index(
                    [request_set_loaded, discovery.load_json(result_set_path)],
                    authority,
                    approval,
                    generated_at=NOW,
                    execution_authority_contexts={
                        execution_authority["authorization_id"]: {
                            "authorization": execution_authority,
                            "expected_execution_authority_sha256": (
                                execution_authority_file_sha256
                            ),
                            "execution_authority_file_sha256": (
                                execution_authority_file_sha256
                            ),
                        }
                    },
                    artifact_file_sha256s=[
                        canonical_request_set_file_sha,
                        result_set_file_sha256,
                    ],
                )

    def test_v2_index_rejects_mismatched_execution_authority_pin(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256_value = write_temp_json_artifact(
                directory, "request_set.json", request_set
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256_value,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256_value,
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            valid_contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": (
                        execution_authority_file_sha256
                    ),
                    "execution_authority_file_sha256": (
                        execution_authority_file_sha256
                    ),
                }
            }
            authority, approval, _ = authority_manifest(
                request_set_loaded,
                discovery.load_json(result_set_path),
                execution_authority_contexts=valid_contexts,
                artifact_file_sha256s=[
                    request_set_file_sha256_value,
                    result_set_file_sha256,
                ],
            )
            with self.assertRaisesRegex(
                discovery.ContractError,
                "actual search execution authorization file SHA-256 is outside the "
                "caller-provided external trust boundary",
            ):
                discovery.build_search_history_index(
                    [
                        request_set_loaded,
                        discovery.load_json(result_set_path),
                    ],
                    authority,
                    approval,
                    generated_at=NOW,
                    execution_authority_contexts={
                        execution_authority["authorization_id"]: {
                            "authorization": execution_authority,
                            "expected_execution_authority_sha256": "a" * 64,
                            "execution_authority_file_sha256": (
                                execution_authority_file_sha256
                            ),
                        }
                    },
                    artifact_file_sha256s=[
                        request_set_file_sha256_value,
                        result_set_file_sha256,
                    ],
                )

    def test_many_sources_index_build_keeps_shape_for_52_sources(self):
        artifacts = []
        artifact_file_sha256s = []
        base_request = request_fixture()
        for index in range(52):
            request = copy.deepcopy(base_request)
            request["request_id"] = f"SDR-ROUND06-{index:03d}"
            request["gap_ref"]["gap_id"] = f"KGH-{index:03d}"
            request["gap_hypothesis_id"] = f"KGH-{index:03d}"
            request["query_seeds"][0]["query"] = (
                f"Permutation case {index} for history index order"
            )
            artifacts.append(request)
            artifact_file_sha256s.append(f"{index:064x}")
        authority, approval, _ = authority_manifest(*artifacts)
        history = discovery.build_search_history_index(
            artifacts,
            authority,
            approval,
            generated_at=NOW,
            artifact_file_sha256s=artifact_file_sha256s,
        )
        reverse_history = discovery.build_search_history_index(
            list(reversed(artifacts)),
            authority,
            approval,
            generated_at=NOW,
            artifact_file_sha256s=list(reversed(artifact_file_sha256s)),
        )
        self.assertEqual(len(history["source_artifacts"]), 52)
        self.assertEqual(len(history["artifact_universe"]), 52)
        self.assertEqual(
            history["history_digest"], reverse_history["history_digest"]
        )
        self.assertEqual(history["schema"], discovery.SEARCH_HISTORY_INDEX_V2_SCHEMA)

    def test_v2_candidate_replays_sorted_artifact_file_shas(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256 = write_temp_json_artifact(
                directory, "request_set.json", request_set, pretty=True
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": (
                        execution_authority_file_sha256
                    ),
                    "execution_authority_file_sha256": (
                        execution_authority_file_sha256
                    ),
                }
            }
            result_set_loaded = discovery.load_json(result_set_path)
            unsorted_artifacts = [
                result_set_loaded,
                request_set_loaded,
            ]
            unsorted_file_shas = [
                result_set_file_sha256,
                request_set_file_sha256,
            ]
            artifact_rows = sorted(
                [
                    (artifact, file_sha256)
                    for artifact, file_sha256 in zip(
                        unsorted_artifacts, unsorted_file_shas
                    )
                ],
                key=lambda row: (row[0]["schema"], discovery.sha256_json(row[0])),
            )
            expected_file_shas = [row[1] for row in artifact_rows]
            expected_refs = [
                {
                    "schema": row[0]["schema"],
                    "sha256": discovery.sha256_json(row[0]),
                }
                for row in artifact_rows
            ]

            candidate = discovery.build_history_authority_candidate(
                unsorted_artifacts,
                issued_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=unsorted_file_shas,
            )
            self.assertEqual(candidate["artifact_file_sha256s"], expected_file_shas)
            self.assertEqual(candidate["artifact_refs"], expected_refs)

            approval = discovery.review_history_authority_candidate(
                candidate,
                reviewer_id="history-reviewer-v2",
                reviewer_role="independent history auditor",
                reviewed_at=NOW,
                complete_universe_attested=True,
                independent_reviewer_attested=True,
                execution_authority_contexts=contexts,
            )
            manifest = discovery.finalize_history_authority_manifest(
                candidate, approval
            )
            history = discovery.build_search_history_index(
                [request_set_loaded, result_set_loaded],
                manifest,
                approval,
                generated_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=[
                    request_set_file_sha256,
                    result_set_file_sha256,
                ],
            )
            discovery.validate_search_history_index(
                history,
                manifest,
                approval,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=[
                    request_set_file_sha256,
                    result_set_file_sha256,
                ],
            )
            self.assertIn(
                discovery.RESULT_SET_V2_SCHEMA,
                {row["schema"] for row in history["source_artifacts"]},
            )

    def test_v2_candidate_rejects_mismatched_request_set_file_sha(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256 = write_temp_json_artifact(
                directory, "request_set.json", request_set, pretty=True
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            result_set_loaded = discovery.load_json(result_set_path)
            with self.assertRaisesRegex(
                discovery.ContractError,
                "search execution authorization is not the owner-replayed exact "
                "request-set binding|result_set.execution_authorization_ref is not the "
                "owner-replayed authorization projection",
            ):
                discovery.build_history_authority_candidate(
                    [request_set_loaded, result_set_loaded],
                    issued_at=NOW,
                    execution_authority_contexts={
                        execution_authority["authorization_id"]: {
                            "authorization": execution_authority,
                            "expected_execution_authority_sha256": (
                                execution_authority_file_sha256
                            ),
                            "execution_authority_file_sha256": (
                                execution_authority_file_sha256
                            ),
                        }
                    },
                    artifact_file_sha256s=[
                        "f" * 64,
                        result_set_file_sha256,
                    ],
                )

    def test_v2_candidate_rejects_mismatched_execution_authority_pin(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256 = write_temp_json_artifact(
                directory, "request_set.json", request_set, pretty=True
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            result_set_loaded = discovery.load_json(result_set_path)
            with self.assertRaisesRegex(
                discovery.ContractError,
                "actual search execution authorization file SHA-256",
            ):
                discovery.build_history_authority_candidate(
                    [request_set_loaded, result_set_loaded],
                    issued_at=NOW,
                    execution_authority_contexts={
                        execution_authority["authorization_id"]: {
                            "authorization": execution_authority,
                            "expected_execution_authority_sha256": "a" * 64,
                            "execution_authority_file_sha256": (
                                execution_authority_file_sha256
                            ),
                        }
                    },
                    artifact_file_sha256s=[
                        request_set_file_sha256,
                        result_set_file_sha256,
                    ],
                )

    def test_v2_result_set_rejects_pretty_request_set_file_sha_mismatch(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            pretty_request_set_path, pretty_request_set_file_sha256 = (
                write_temp_json_artifact(
                    directory, "request_set.json", request_set, pretty=True
                )
            )
            request_set_loaded = discovery.load_json(pretty_request_set_path)
            canonical_request_set_file_sha = request_set_file_sha256(request_set)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=pretty_request_set_path,
                request_set_file_sha256=pretty_request_set_file_sha256,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=pretty_request_set_path,
                request_set_file_sha256=pretty_request_set_file_sha256,
            )
            result_set_path, result_set_file_sha256 = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": (
                        execution_authority_file_sha256
                    ),
                    "execution_authority_file_sha256": (
                        execution_authority_file_sha256
                    ),
                }
            }
            with self.assertRaisesRegex(
                discovery.ContractError,
                "search execution authorization is not the owner-replayed exact request-set binding|"
                "result_set.execution_authorization_ref is not the owner-replayed "
                "authorization projection",
            ):
                discovery.build_history_authority_candidate(
                    [
                        discovery.load_json(pretty_request_set_path),
                        discovery.load_json(result_set_path),
                    ],
                    issued_at=NOW,
                    execution_authority_contexts=contexts,
                    artifact_file_sha256s=[
                        canonical_request_set_file_sha,
                        result_set_file_sha256,
                    ],
                )

    def test_indexes_failed_request_independent_of_artifact_order(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        failure = failure_result_set(request_set)
        authority, authority_review, _ = authority_manifest(failure, request_set)
        history = discovery.build_search_history_index(
            [failure, request_set],
            authority,
            authority_review,
            generated_at=NOW,
        )
        discovery.validate_search_history_index(history, authority, authority_review)
        states = {row["state"] for row in history["entries"]}
        self.assertIn("requested", states)
        self.assertNotIn("failed", states)
        self.assertFalse(
            [
                row
                for row in history["entries"]
                if row["source_ref"]["schema"] == discovery.RESULT_SET_SCHEMA
            ]
        )
        self.assertEqual(
            history["history_id"],
            "search-history-" + history["history_digest"][:16],
        )

    def test_v1_result_set_artifacts_are_display_only_even_without_bound_request_set(
        self,
    ):
        request = request_fixture()
        request_set = request_set_fixture(request)
        failure = failure_result_set(request_set)
        authority, authority_review, _ = authority_manifest(failure)
        history = discovery.build_search_history_index(
            [failure], authority, authority_review, generated_at=NOW
        )
        discovery.validate_search_history_index(history, authority, authority_review)
        self.assertEqual(history["schema"], discovery.SEARCH_HISTORY_INDEX_V2_SCHEMA)
        self.assertEqual(
            [row["schema"] for row in history["source_artifacts"]],
            [discovery.RESULT_SET_SCHEMA],
        )
        self.assertEqual(history["entries"], [])

    def test_v1_result_artifact_with_malformed_state_is_display_only(self):
        request = request_fixture()
        result = partial_result_fixture(request)
        result["schema"] = discovery.RESULT_SCHEMA
        result["discovery_status"] = "unsupported-state-token"
        authority, authority_review, _ = authority_manifest(result)
        history = discovery.build_search_history_index(
            [result], authority, authority_review, generated_at=NOW
        )
        discovery.validate_search_history_index(history, authority, authority_review)
        self.assertEqual(history["schema"], discovery.SEARCH_HISTORY_INDEX_V2_SCHEMA)
        self.assertEqual(history["entries"], [])

    def test_indexes_selection_leak_partial_and_candidate_semantics(self):
        hypotheses = {
            "schema": "KnowledgeGapHypotheses/v1",
            "round_id": "ROUND06",
            "selection_summary": {"selected_hypothesis_ids": ["KGH-FIXTURE"]},
            "hypotheses": [
                {
                    "hypothesis_id": "KGH-FIXTURE",
                    "status": "selected",
                    "search_test": {"queries": request_fixture()["query_seeds"]},
                },
                {
                    "hypothesis_id": "KGH-FIXTURE-LEAK",
                    "status": "proposed",
                    "search_test": {
                        "queries": [
                            {
                                "objective": "confirm",
                                "query": "fixture-b dependent input Shapley estimator benchmark",
                            }
                        ]
                    },
                },
            ],
        }
        request = request_fixture()
        result = partial_result_fixture(request)
        authority, authority_review, _ = authority_manifest(hypotheses, request, result)
        history = discovery.build_search_history_index(
            [hypotheses, request, result],
            authority,
            authority_review,
            generated_at=NOW,
        )
        states = {row["state"] for row in history["entries"]}
        self.assertIn("selection_leak", states)
        self.assertNotIn("partial", states)
        self.assertNotIn("candidate", states)
        leaked = [row for row in history["entries"] if row["selection_leak"]]
        self.assertEqual(
            {row["local_request_id"] for row in leaked}, {"SDR-KGH-FIXTURE-LEAK"}
        )

    def test_semantic_signature_collapses_round06_paraphrase(self):
        left = discovery.semantic_signature(
            "Fixture-a Shapley allocation for correlated variables"
        )[0]
        right = discovery.semantic_signature(
            "Shapley attribution with dependent inputs Fixture-a"
        )[0]
        self.assertEqual(left, right)

    def test_history_digest_and_entry_terms_fail_closed(self):
        request = request_fixture()
        authority, authority_review, _ = authority_manifest(request)
        history = discovery.build_search_history_index(
            [request], authority, authority_review, generated_at=NOW
        )
        tampered = copy.deepcopy(history)
        tampered["entries"] = []
        digest = discovery.canonical_search_history_digest(tampered)
        tampered["history_digest"] = digest
        tampered["history_id"] = "search-history-" + digest[:16]
        with self.assertRaisesRegex(discovery.ContractError, "owner-replayed"):
            discovery.validate_search_history_index(
                tampered, authority, authority_review
            )

        self_reported = copy.deepcopy(history)
        self_reported["source_artifacts"][0]["sha256"] = "d" * 64
        digest = discovery.canonical_search_history_digest(self_reported)
        self_reported["history_digest"] = digest
        self_reported["history_id"] = "search-history-" + digest[:16]
        with self.assertRaisesRegex(discovery.ContractError, "authority universe"):
            discovery.validate_search_history_index(
                self_reported, authority, authority_review
            )

    def test_v2_index_replay_rejects_tampered_entries(self):
        request = request_fixture()
        request_set = request_set_fixture(request)
        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256 = write_temp_json_artifact(
                directory, "request_set.json", request_set
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            execution_authority_file_sha = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            result_set_path, result_set_file_sha = write_temp_json_artifact(
                directory, "result_set.json", result_set
            )
            contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": (
                        execution_authority_file_sha
                    ),
                    "execution_authority_file_sha256": (
                        execution_authority_file_sha
                    ),
                }
            }
            authority, approval, _ = authority_manifest(
                request_set_loaded,
                discovery.load_json(result_set_path),
                execution_authority_contexts=contexts,
                artifact_file_sha256s=[request_set_file_sha256, result_set_file_sha],
            )
            history = discovery.build_search_history_index(
                [
                    request_set_loaded,
                    discovery.load_json(result_set_path),
                ],
                authority,
                approval,
                generated_at=NOW,
                execution_authority_contexts=contexts,
                artifact_file_sha256s=[request_set_file_sha256, result_set_file_sha],
            )
            self.assertEqual(history["schema"], discovery.SEARCH_HISTORY_INDEX_V2_SCHEMA)
            tampered = copy.deepcopy(history)
            tampered["entries"][0]["objective"] = "tampered objective"
            tampered["entries"].sort(
                key=lambda row: (
                    row["semantic_signature"],
                    row["objective"],
                    row["state"],
                    row["request_occurrence_id"],
                    row["source_ref"]["sha256"],
                    row["source_ref"]["locator"],
                )
            )
            tampered["history_digest"] = discovery.canonical_search_history_digest(tampered)
            tampered["history_id"] = "search-history-" + tampered["history_digest"][:16]
            with self.assertRaisesRegex(
                discovery.ContractError,
                "owner-replayed",
            ):
                discovery.validate_search_history_index(
                    tampered,
                    authority,
                    approval,
                    execution_authority_contexts=contexts,
                    artifact_file_sha256s=[request_set_file_sha256, result_set_file_sha],
                )

    def test_whole_source_deletion_cannot_redefine_authority_universe(self):
        first = request_fixture()
        second = copy.deepcopy(first)
        second["request_id"] = "SDR-ROUND05-UNRELATED"
        second["gap_hypothesis_id"] = "KGH-ROUND05-UNRELATED"
        second["gap_ref"]["gap_id"] = "KGH-ROUND05-UNRELATED"
        second["query_seeds"][0]["query"] = "orthogonal calibration benchmark"
        authority, authority_review, _ = authority_manifest(first, second)
        history = discovery.build_search_history_index(
            [first, second], authority, authority_review, generated_at=NOW
        )
        removed_digest = discovery.sha256_json(first)
        tampered = copy.deepcopy(history)
        tampered["source_artifacts"] = [
            row
            for row in tampered["source_artifacts"]
            if row["sha256"] != removed_digest
        ]
        tampered["artifact_universe"] = [
            row
            for row in tampered["artifact_universe"]
            if row["sha256"] != removed_digest
        ]
        tampered["entries"] = [
            row
            for row in tampered["entries"]
            if row["source_ref"]["sha256"] != removed_digest
        ]
        digest = discovery.canonical_search_history_digest(tampered)
        tampered["history_digest"] = digest
        tampered["history_id"] = "search-history-" + digest[:16]
        with self.assertRaisesRegex(discovery.ContractError, "authority universe"):
            discovery.validate_search_history_index(
                tampered, authority, authority_review
            )

        subset_candidate = discovery.build_history_authority_candidate(
            [second], issued_at=NOW
        )
        with self.assertRaisesRegex(
            discovery.ContractError, "does not bind candidate file"
        ):
            discovery.finalize_history_authority_manifest(
                subset_candidate, authority_review
            )

    def test_partial_result_requires_complete_planned_query_coverage(self):
        request = request_fixture()
        result = partial_result_fixture(request)
        result["search_events"] = []
        authority, authority_review, _ = authority_manifest(request, result)
        history = discovery.build_search_history_index(
            [request, result],
            authority,
            authority_review,
            generated_at=NOW,
        )
        discovery.validate_search_history_index(history, authority, authority_review)
        request_rows = [
            row
            for row in history["entries"]
            if row.get("request_id", row.get("local_request_id"))
            == request["request_id"]
            and row["state"] == "requested"
        ]
        self.assertEqual(len(request_rows), len(request["query_seeds"]))

    def test_v2_history_rejects_query_budget_pseudo_complete_replayed_result(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        request["budgets"]["max_queries"] = 1
        request_set = request_set_fixture(request)

        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256 = write_temp_json_artifact(
                directory, "request_set.json", request_set
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            result_set = execute_request_set_with_authority_file(
                request_set_loaded,
                transport_no_results,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )

            result = result_set["results"][0]
            self.assertEqual(result["discovery_status"], "partial_budget")
            self.assertTrue(result["limits"]["query_budget_reached"])
            self.assertTrue(result["limits"]["missing_query_ids"])

            tampered = copy.deepcopy(result_set)
            tampered_result = tampered["results"][0]
            tampered_result["discovery_status"] = "complete_bounded"
            tampered_result["stop_reason"] = "complete_bounded"
            tampered_result["limits"]["query_budget_reached"] = False
            tampered_result["limits"]["missing_query_ids"] = []

            _, tampered_result_set_file_sha256 = write_temp_json_artifact(
                directory, "tampered_result_set.json", tampered
            )

            contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": execution_authority_file_sha256,
                    "execution_authority_file_sha256": execution_authority_file_sha256,
                }
            }
            with self.assertRaisesRegex(
                discovery.ContractError,
                "does not match request budget replay|query_budget_reached|complete_bounded",
            ):
                authority_manifest(
                    request_set_loaded,
                    tampered,
                    execution_authority_contexts=contexts,
                    artifact_file_sha256s=[
                        request_set_file_sha256,
                        tampered_result_set_file_sha256,
                    ],
                )

    def test_v2_history_rejects_pre_truncation_candidate_count_requirements(self):
        request = request_fixture()
        request["routes"]["google_scholar"] = "disabled"
        request["routes"]["automatic"] = ["openalex"]
        request["budgets"]["max_candidates"] = 1
        request_set = request_set_fixture(request)

        payload = {
            "meta": {"count": 2},
            "results": [
                {
                    "title": "OpenAlex Work A",
                    "authorships": [{"author": {"display_name": "Alice"}}],
                    "publication_year": 2025,
                    "host_venue": {"display_name": "Open Journal"},
                    "doi": "10.1000/openalex-a",
                    "ids": {"openalex": "W123"},
                    "type": "article",
                    "is_retracted": False,
                    "abstract_inverted_index": {"a": [1]},
                    "primary_location": {"landing_page_url": "https://example.org/openalex-a"},
                },
                {
                    "title": "OpenAlex Work B",
                    "authorships": [{"author": {"display_name": "Bob"}}],
                    "publication_year": 2025,
                    "host_venue": {"display_name": "Open Journal"},
                    "doi": "10.1000/openalex-b",
                    "ids": {"openalex": "W124"},
                    "type": "article",
                    "is_retracted": False,
                    "abstract_inverted_index": {"b": [1]},
                    "primary_location": {"landing_page_url": "https://example.org/openalex-b"},
                },
            ],
        }

        def transport(url: str, timeout_seconds: int | None = None) -> bytes:
            del timeout_seconds
            if "crossref" in url:
                return b'{"message":{"total-results":0,"items":[]}}'
            if "openalex" in url:
                return json.dumps(payload).encode("utf-8")
            return b'{"total":0,"data":[]}'

        with tempfile.TemporaryDirectory() as directory:
            request_set_path, request_set_file_sha256 = write_temp_json_artifact(
                directory, "request_set.json", request_set
            )
            request_set_loaded = discovery.load_json(request_set_path)
            execution_authority = discovery.authorize_request_set(
                copy.deepcopy(request_set_loaded),
                reviewer_id="history-execution-reviewer",
                reviewer_role="independent search execution reviewer",
                reviewed_at=NOW,
                independent_reviewer_attested=True,
                request_set_file=request_set_path,
                request_set_file_sha256=request_set_file_sha256,
            )
            execution_authority_file_sha256 = (
                discovery.canonical_search_execution_authorization_file_sha256(
                    execution_authority
                )
            )
            with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "unit-test-key"}):
                result_set = execute_request_set_with_authority_file(
                    request_set_loaded,
                    transport,
                    execution_authority=execution_authority,
                    expected_execution_authority_sha256=execution_authority_file_sha256,
                    request_set_file=request_set_path,
                    request_set_file_sha256=request_set_file_sha256,
                )

            _, tampered_result_set_file_sha256 = write_temp_json_artifact(
                directory, "tampered_result_set.json", result_set
            )

            contexts = {
                execution_authority["authorization_id"]: {
                    "authorization": execution_authority,
                    "expected_execution_authority_sha256": execution_authority_file_sha256,
                    "execution_authority_file_sha256": execution_authority_file_sha256,
                }
            }

            tampered_missing = copy.deepcopy(result_set)
            del tampered_missing["results"][0]["limits"]["pre_truncation_candidate_count"]
            _, tampered_missing_result_set_file_sha256 = write_temp_json_artifact(
                directory, "tampered_missing.json", tampered_missing
            )
            with self.assertRaisesRegex(
                discovery.ContractError,
                "pre_truncation_candidate_count is required for request replay",
            ):
                authority_manifest(
                    request_set_loaded,
                    tampered_missing,
                    execution_authority_contexts=contexts,
                    artifact_file_sha256s=[
                        request_set_file_sha256,
                        tampered_missing_result_set_file_sha256,
                    ],
                )

            tampered_zeroed = copy.deepcopy(result_set)
            for event in tampered_zeroed["results"][0]["search_events"]:
                event["candidate_count"] = 0
            tampered_zeroed["results"][0]["limits"]["pre_truncation_candidate_count"] = 0
            _, tampered_zeroed_result_set_file_sha256 = write_temp_json_artifact(
                directory, "tampered_zeroed.json", tampered_zeroed
            )
            with self.assertRaisesRegex(
                discovery.ContractError,
                "must be at least the number of ranked candidates",
            ):
                authority_manifest(
                    request_set_loaded,
                    tampered_zeroed,
                    execution_authority_contexts=contexts,
                    artifact_file_sha256s=[
                        request_set_file_sha256,
                        tampered_zeroed_result_set_file_sha256,
                    ],
                )

            tampered_inconsistent = copy.deepcopy(result_set)
            tampered_inconsistent["results"][0]["limits"]["pre_truncation_candidate_count"] = 1
            _, tampered_inconsistent_result_set_file_sha256 = write_temp_json_artifact(
                directory, "tampered_inconsistent.json", tampered_inconsistent
            )
            with self.assertRaisesRegex(
                discovery.ContractError,
                "does not match the sum of search_event candidate_count",
            ):
                authority_manifest(
                    request_set_loaded,
                    tampered_inconsistent,
                    execution_authority_contexts=contexts,
                    artifact_file_sha256s=[
                        request_set_file_sha256,
                        tampered_inconsistent_result_set_file_sha256,
                    ],
                )

    def test_v2_occurrences_scope_reused_local_request_ids_to_request_set_artifacts(
        self,
    ):
        first_request = request_fixture()
        first_request_set = request_set_fixture(first_request)
        second_request = copy.deepcopy(first_request)
        second_request["paper_need"] = (
            "Independently test a second bounded input-dependence claim"
        )
        second_request_set = request_set_fixture(second_request)

        authority, approval, _ = authority_manifest(
            first_request_set, second_request_set
        )
        history = discovery.build_search_history_index(
            [first_request_set, second_request_set],
            authority,
            approval,
            generated_at=NOW,
        )

        self.assertEqual(history["schema"], discovery.SEARCH_HISTORY_INDEX_V2_SCHEMA)
        local_id = first_request["request_id"]
        rows = [
            row for row in history["entries"] if row["local_request_id"] == local_id
        ]
        self.assertEqual(len({row["request_occurrence_id"] for row in rows}), 2)
        self.assertEqual(len({row["request_scope_ref"]["sha256"] for row in rows}), 2)
        discovery.validate_search_history_index(history, authority, approval)

    def test_request_set_rejects_duplicate_local_request_ids(self):
        request_set = request_set_fixture(request_fixture())
        duplicate = copy.deepcopy(request_set)
        duplicate["requests"].append(copy.deepcopy(duplicate["requests"][0]))
        duplicate["request_set_digest"] = discovery.canonical_request_set_digest(
            duplicate
        )
        duplicate["request_set_id"] = (
            "request-set-" + duplicate["request_set_digest"][:16]
        )

        with self.assertRaisesRegex(discovery.ContractError, "unique request_id"):
            discovery.build_history_authority_candidate([duplicate], issued_at=NOW)

    def test_many_sources_candidate_build_keeps_file_sha_shape_for_52_sources(self):
        artifacts = []
        artifact_file_sha256s = []
        base_request = request_fixture()
        for index in range(52):
            request = copy.deepcopy(base_request)
            request["request_id"] = f"SDR-ROUND06-{index:03d}"
            request["gap_ref"]["gap_id"] = f"KGH-{index:03d}"
            request["gap_hypothesis_id"] = f"KGH-{index:03d}"
            request["query_seeds"][0]["query"] = (
                f"Permutation case {index} under correlated inputs"
            )
            artifacts.append(request)
            artifact_file_sha256s.append(f"{index:064x}")
        candidate = discovery.build_history_authority_candidate(
            artifacts,
            issued_at=NOW,
            artifact_file_sha256s=artifact_file_sha256s,
        )
        self.assertEqual(len(candidate["artifact_refs"]), 52)
        self.assertEqual(len(candidate["artifact_universe"]), 52)
        self.assertEqual(len(candidate["artifact_file_sha256s"]), 52)
        expected_rows = sorted(
            [
                (artifact, artifact_file_sha256)
                for artifact, artifact_file_sha256 in zip(
                    artifacts, artifact_file_sha256s
                )
            ],
            key=lambda row: (row[0]["schema"], discovery.sha256_json(row[0])),
        )
        self.assertEqual(
            candidate["artifact_file_sha256s"],
            [row[1] for row in expected_rows],
        )

    def test_candidate_approval_replays_embedded_exact_artifact_universe(self):
        request = request_fixture()
        candidate = discovery.build_history_authority_candidate(
            [request], issued_at=NOW
        )
        self.assertIn("artifact_universe", candidate)

        ref_only = copy.deepcopy(candidate)
        del ref_only["artifact_universe"]
        with self.assertRaisesRegex(
            discovery.ContractError, "constructible artifact_universe"
        ):
            discovery.review_history_authority_candidate(
                ref_only,
                reviewer_id="history-reviewer-ref-only",
                reviewer_role="independent history auditor",
                reviewed_at=NOW,
                complete_universe_attested=True,
                independent_reviewer_attested=True,
            )

        tampered = copy.deepcopy(candidate)
        tampered["artifact_universe"][0]["artifact"]["paper_need"] = "tampered"
        with self.assertRaisesRegex(discovery.ContractError, "does not bind"):
            discovery.review_history_authority_candidate(
                tampered,
                reviewer_id="history-reviewer-tampered",
                reviewer_role="independent history auditor",
                reviewed_at=NOW,
                complete_universe_attested=True,
                independent_reviewer_attested=True,
            )

        approval = discovery.review_history_authority_candidate(
            candidate,
            reviewer_id="history-reviewer-replay",
            reviewer_role="independent history auditor",
            reviewed_at=NOW,
            complete_universe_attested=True,
            independent_reviewer_attested=True,
        )
        manifest = discovery.finalize_history_authority_manifest(candidate, approval)
        history = discovery.build_search_history_index(
            [request], manifest, approval, generated_at=NOW
        )
        discovery.validate_search_history_index(history, manifest, approval)


if __name__ == "__main__":
    unittest.main()
