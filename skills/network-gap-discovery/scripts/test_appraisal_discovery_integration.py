import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import network_gap_discovery as discovery


NOW = "2026-08-09T08:00:00Z"
APPRAISAL_SET_REF = {
    "appraisal_set_id": "appraisal-set-SA-001",
    "appraisal_set_digest": "3" * 64,
}


def network_fixture():
    network = {
        "schema": "KnowledgeNetwork/v1",
        "network_id": "KN-TEST",
        "snapshot_id": "KN-TEST-S67",
        "sources": [],
        "nodes": [],
        "relations": [],
        "gaps": [],
        "completion": {"status": "partial"},
    }
    network["content_sha256"] = discovery.sha256_json(network)
    return network


def semantic_fixture(
    target_scope="dependent input sensitivity allocation",
    *,
    comparator="Sobol",
    boundary_variable="dependence",
):
    return {
        "target_scope": target_scope,
        "evidence_class": "independent replication",
        "comparator": comparator,
        "boundary_variable": boundary_variable,
        "independence_requirement": "independent implementation",
    }


def observation_pair_fixture(
    *, confirm_operator="reproduced", refute_operator="not_reproduced"
):
    return {
        "target_metric": "Shapley",
        "comparator": "Sobol",
        "boundary": "dependence",
        "confirm": {
            "operator": confirm_operator,
            "value_or_state": "stable",
            "claim_implication": "supports",
        },
        "refute": {
            "operator": refute_operator,
            "value_or_state": "stable",
            "claim_implication": "challenges",
        },
    }


def seal_challenge(
    *, semantic=None, axis="independent_replication", observation_pair=None
):
    semantic = copy.deepcopy(semantic or semantic_fixture())
    observation_pair = copy.deepcopy(observation_pair or observation_pair_fixture())
    challenge = {
        "schema": discovery.EVIDENCE_CHALLENGE_SCHEMA,
        "challenge_id": "",
        "challenge_digest": "",
        "appraisal_set_ref": copy.deepcopy(APPRAISAL_SET_REF),
        "target": {
            "claim_id": "claim-SA-dependent-inputs",
            "claim_digest": "1" * 64,
            "evidence_id": "evidence-fixturea-fixtureb-fixturec",
            "source_id": "source-SA-aggregate",
            "appraisal_id": "appraisal-SA-001",
            "appraisal_digest": "2" * 64,
        },
        "target_dimension": "independence_overlap",
        "axis": axis,
        "severity": "material",
        "status": "open",
        "problem_statement": "fixture-a, fixture-b, and fixture-c evidence may share estimator assumptions",
        "falsifier": "independent implementation reverses ranking under strong dependence",
        "discriminating_observation": "independent implementation preserves or reverses the ranking",
        "semantic_signature": semantic,
        "adversarial_observation_pair": observation_pair,
        "basis_refs": [
            {
                "kind": "appraisal",
                "record_id": "appraisal-SA-001",
                "record_digest": "2" * 64,
                "locator_id": "claim-check-1",
            }
        ],
        "resolution_route": "targeted_evidence_need",
        "effect_on_overall": "blocks_decisive",
        "supersedes": [],
    }
    challenge["challenge_id"] = (
        "challenge-" + discovery.sha256_json(discovery._challenge_seed(challenge))[:16]
    )
    challenge["challenge_digest"] = discovery._canonical_own_digest(
        challenge, "challenge_digest"
    )
    return challenge


def seal_need(
    challenge,
    *,
    route="scholar_discovery",
    confirm_goal=None,
    refute_goal=None,
    suffix="",
    semantic=None,
    observation_pair=None,
    domain_anchors=None,
):
    semantic = copy.deepcopy(semantic or challenge["semantic_signature"])
    observation_pair = copy.deepcopy(
        observation_pair or challenge["adversarial_observation_pair"]
    )
    if confirm_goal is None:
        confirm_goal = discovery.format_adversarial_observation_goal(
            observation_pair, "confirm"
        )
    if refute_goal is None:
        refute_goal = discovery.format_adversarial_observation_goal(
            observation_pair, "refute"
        )
    if domain_anchors is None:
        domain_anchors = (
            ["shapley sensitivity", "input dependence"]
            if route == "scholar_discovery"
            else []
        )
    need = {
        "need_id": "",
        "need_digest": "",
        "challenge_refs": [
            {
                "challenge_id": challenge["challenge_id"],
                "challenge_digest": challenge["challenge_digest"],
            }
        ],
        "claim_ref": {
            "claim_id": challenge["target"]["claim_id"],
            "claim_digest": challenge["target"]["claim_digest"],
        },
        "appraisal_ref": {
            "appraisal_id": challenge["target"]["appraisal_id"],
            "appraisal_digest": challenge["target"]["appraisal_digest"],
        },
        "route": route,
        "status": "proposed",
        "paper_need": "Test dependent-input sensitivity allocations with an independent implementation",
        "target_scope": semantic["target_scope"],
        "required_evidence_class": semantic["evidence_class"],
        "must_criteria": sorted(["Shapley effects", "dependent inputs"]),
        "should_criteria": ["independent implementation"],
        "must_not_criteria": [],
        "confirm_goal": confirm_goal,
        "refute_goal": refute_goal,
        "falsifier": challenge["falsifier"],
        "semantic_signature": semantic,
        "adversarial_observation_pair": observation_pair,
        "domain_anchors": copy.deepcopy(domain_anchors),
        "acceptance_criterion": "Full text reports an independent implementation and bounded comparison",
        "exclusion_criterion": "Metadata-only mentions without an implemented comparison",
        "decision_impact": "high",
        "mutation_authorized": False,
        "supersedes": [],
    }
    need["need_id"] = "need-" + discovery.sha256_json(discovery._need_seed(need))[:16]
    need["need_digest"] = discovery._canonical_own_digest(need, "need_digest")
    return need


def seal_need_set(needs):
    needs = sorted(copy.deepcopy(needs), key=lambda row: row["need_id"])
    document = {
        "schema": discovery.TARGETED_EVIDENCE_NEED_SET_SCHEMA,
        "need_set_id": "",
        "need_set_digest": "",
        "appraisal_set_ref": copy.deepcopy(APPRAISAL_SET_REF),
        "needs": needs,
    }
    seed = {
        "appraisal_set_ref": copy.deepcopy(document["appraisal_set_ref"]),
        "need_ids": [need["need_id"] for need in needs],
    }
    document["need_set_id"] = "need-set-" + discovery.sha256_json(seed)[:16]
    document["need_set_digest"] = discovery._canonical_own_digest(
        document, "need_set_digest"
    )
    return document


def history_artifact(queries=(), *, round_id="ROUND06-HISTORY"):
    return {
        "schema": "KnowledgeGapHypotheses/v1",
        "round_id": round_id,
        "selection_summary": {"selected_hypothesis_ids": []},
        "hypotheses": [
            {
                "hypothesis_id": f"KGH-HISTORY-{index:02d}",
                "status": "proposed",
                "search_test": {"queries": [{"objective": "confirm", "query": query}]},
            }
            for index, query in enumerate(queries)
        ],
    }


def history_authority_fixture(
    artifacts,
    *,
    execution_authority_contexts=None,
    artifact_file_sha256s=None,
):
    scholar = discovery._scholar_discovery_module()
    candidate = scholar.build_history_authority_candidate(
        artifacts,
        issued_at=NOW,
        execution_authority_contexts=execution_authority_contexts,
        artifact_file_sha256s=artifact_file_sha256s,
    )
    review = scholar.review_history_authority_candidate(
        candidate,
        reviewer_id="reviewer-independent-01",
        reviewer_role="independent history auditor",
        reviewed_at=NOW,
        complete_universe_attested=True,
        independent_reviewer_attested=True,
        execution_authority_contexts=execution_authority_contexts,
    )
    manifest = scholar.finalize_history_authority_manifest(candidate, review)
    return manifest, review


def history_fixture(queries=()):
    scholar = discovery._scholar_discovery_module()
    artifacts = [history_artifact(queries)]
    authority, authority_review = history_authority_fixture(artifacts)
    return (
        scholar.build_search_history_index(
            artifacts, authority, authority_review, generated_at=NOW
        ),
        authority,
        authority_review,
    )


def compile_needs(
    need_set,
    challenges,
    network,
    *,
    round_id,
    history=None,
    execution_authority_contexts=None,
    history_artifact_file_sha256s=None,
):
    if history is None:
        history = history_fixture()
    if len(history) == 3:
        history_index, history_authority, history_authority_review = history
    elif len(history) == 4:
        (
            history_index,
            history_authority,
            history_authority_review,
            history_artifact_file_sha256s,
        ) = history
    else:
        raise ValueError("history fixture must be a (index, authority, review) tuple")
    return discovery.compile_appraisal_needs(
        need_set,
        challenges,
        history_index,
        history_authority,
        history_authority_review,
        network,
        round_id=round_id,
        execution_authority_contexts=execution_authority_contexts,
        artifact_file_sha256s=history_artifact_file_sha256s,
    )


def reviewed_selection(prioritized):
    selected_ids = prioritized["selection_summary"]["selected_hypothesis_ids"]
    return {
        "schema": discovery.REVIEWED_GAP_SELECTION_SCHEMA,
        "input_ref": {
            "schema": discovery.HYPOTHESES_SCHEMA,
            "sha256": discovery.sha256_json(prioritized),
        },
        "network_ref": copy.deepcopy(prioritized["network_ref"]),
        "round_id": prioritized["round_id"],
        "selected_hypothesis_ids": selected_ids,
        "review_status": "approved",
    }


def reseal_request_set(request_set):
    request_set["request_set_digest"] = discovery.canonical_request_set_digest(
        request_set
    )
    request_set["request_set_id"] = (
        discovery.REQUEST_SET_ID_PREFIX + request_set["request_set_digest"][:16]
    )
    return request_set


def compiled_selected_fixture(*, google_scholar_policy="manual_optional"):
    network = network_fixture()
    challenge = seal_challenge()
    scholar_need = seal_need(challenge)
    code_need = seal_need(challenge, route="code_data", suffix="codepath")
    compiled = compile_needs(
        seal_need_set([scholar_need, code_need]),
        [challenge],
        network,
        round_id="ROUND-APPRAISAL-01",
    )
    prioritized = discovery.prioritize(compiled, network)
    selected = discovery.select_hypotheses(
        prioritized, reviewed_selection(prioritized), network
    )
    requests = discovery.emit_search_requests(
        selected,
        network,
        google_scholar_policy=google_scholar_policy,
    )
    return network, challenge, scholar_need, code_need, selected, requests


def request_set_file_sha256(request_set):
    request_set_file, request_set_file_sha256_value = request_set_file_artifact(request_set)
    request_set_file.unlink()
    return request_set_file_sha256_value


def request_set_file_artifact(request_set):
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


def artifact_file_sha256(document):
    raw = (
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    with tempfile.NamedTemporaryFile("wb", delete=False) as temporary:
        temporary.write(raw)
        path = Path(temporary.name)
    path.chmod(0o600)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    finally:
        path.unlink()


def artifact_file(document):
    raw = (
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    with tempfile.NamedTemporaryFile("wb", delete=False) as temporary:
        temporary.write(raw)
        path = Path(temporary.name)
    path.chmod(0o600)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def execute_request_set_with_authority_file(
    scholar,
    request_set,
    transport,
    *,
    execution_authority,
    expected_execution_authority_sha256,
    request_set_file,
    request_set_file_sha256,
    execution_authority_file_sha256=None,
    timeout_seconds=30,
):
    authority_file, authority_file_sha256 = artifact_file(execution_authority)
    if execution_authority_file_sha256 is None:
        execution_authority_file_sha256 = authority_file_sha256
    try:
        return scholar.execute_request_set(
            copy.deepcopy(request_set),
            transport,
            timeout_seconds=timeout_seconds,
            execution_authority=execution_authority,
            expected_execution_authority_sha256=expected_execution_authority_sha256,
            execution_authority_file=authority_file,
            execution_authority_file_sha256=execution_authority_file_sha256,
            request_set_file=request_set_file,
            request_set_file_sha256=request_set_file_sha256,
        )
    finally:
        authority_file.unlink()


def execute_appraisal_request_set_with_authority_file(
    scholar,
    requests,
    transport,
    *,
    execution_authority,
    expected_execution_authority_sha256,
    request_set_file,
    request_set_file_sha256,
    execution_authority_file_sha256=None,
    timeout_seconds=30,
):
    authority_file, authority_file_sha256 = artifact_file(execution_authority)
    if execution_authority_file_sha256 is None:
        execution_authority_file_sha256 = authority_file_sha256
    try:
        return scholar.execute_appraisal_request_set(
            copy.deepcopy(requests),
            transport,
            timeout_seconds=timeout_seconds,
            execution_authority=execution_authority,
            expected_execution_authority_sha256=expected_execution_authority_sha256,
            execution_authority_file=authority_file,
            execution_authority_file_sha256=execution_authority_file_sha256,
            request_set_file=request_set_file,
            request_set_file_sha256=request_set_file_sha256,
        )
    finally:
        authority_file.unlink()


def execute_appraisal_fixture(requests, transport):
    request_set_file, request_set_file_sha = request_set_file_artifact(requests)
    scholar = discovery._scholar_discovery_module()
    try:
        execution_authority = scholar.authorize_request_set(
            copy.deepcopy(requests),
            reviewer_id="reviewer-execution-appraisal-fixture",
            reviewer_role="independent appraisal search execution reviewer",
            reviewed_at=NOW,
            independent_reviewer_attested=True,
            request_set_file=request_set_file,
            request_set_file_sha256=request_set_file_sha,
        )
        authority_file_sha256 = (
            scholar.canonical_search_execution_authorization_file_sha256(
                execution_authority
            )
        )

        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "unit-test-key"}):
            result_set = execute_appraisal_request_set_with_authority_file(
                scholar,
                requests,
                transport,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=authority_file_sha256,
                request_set_file=request_set_file,
                request_set_file_sha256=request_set_file_sha,
            )
    finally:
        request_set_file.unlink()

    contexts = {
        execution_authority["authorization_id"]: {
            "authorization": execution_authority,
            "expected_execution_authority_sha256": authority_file_sha256,
            "execution_authority_file_sha256": authority_file_sha256,
        }
    }
    return (
        result_set,
        contexts,
        request_set_file_sha,
    )


class AppraisalNeedCompilationTests(unittest.TestCase):
    def test_v2_history_replay_requires_context_and_cli_forwards_it(self):
        network, challenge, _, _, _, requests = compiled_selected_fixture(
            google_scholar_policy="disabled"
        )

        def empty_transport(url, timeout):
            del timeout
            if "openalex" in url:
                return b'{"meta":{"count":0},"results":[]}'
            if "crossref" in url:
                return b'{"message":{"total-results":0,"items":[]}}'
            return b'{"total":0,"data":[]}'

        result_set, contexts, request_set_file_sha = execute_appraisal_fixture(
            requests, empty_transport
        )
        scholar = discovery._scholar_discovery_module()
        authority, authority_review = history_authority_fixture(
            [requests, result_set],
            execution_authority_contexts=contexts,
            artifact_file_sha256s=[
                request_set_file_sha,
                artifact_file_sha256(result_set),
            ],
        )
        history_index = scholar.build_search_history_index(
            [requests, result_set],
            authority,
            authority_review,
            generated_at=NOW,
            execution_authority_contexts=contexts,
            artifact_file_sha256s=[
                request_set_file_sha,
                artifact_file_sha256(result_set),
            ],
        )
        history = (
            history_index,
            authority,
            authority_review,
            [
                request_set_file_sha,
                artifact_file_sha256(result_set),
            ],
        )
        code_need = seal_need(
            challenge,
            route="code_data",
            suffix="v2-history-context",
        )
        need_set = seal_need_set([code_need])

        with self.assertRaisesRegex(
            discovery.ContractError, "external execution authorization context"
        ):
            compile_needs(
                need_set,
                [challenge],
                network,
                round_id="ROUND-V2-HISTORY-NO-CONTEXT",
                history=history,
            )

        compiled = compile_needs(
            need_set,
            [challenge],
            network,
            round_id="ROUND-V2-HISTORY-CONTEXT",
            history=history,
            execution_authority_contexts=contexts,
        )
        with self.assertRaisesRegex(
            discovery.ContractError, "external execution authorization context"
        ):
            discovery.validate_hypotheses(
                compiled, network, history_artifact_file_sha256s=history[3]
            )
        discovery.validate_hypotheses(
            compiled,
            network,
            execution_authority_contexts=contexts,
            history_artifact_file_sha256s=history[3],
        )
        with self.assertRaisesRegex(
            discovery.ContractError, "external execution authorization context"
        ):
            discovery.validate_any(
                history_index,
                history_authority=authority,
                history_authority_review=authority_review,
                history_artifact_file_sha256s=history[3],
            )
        discovery.validate_any(
            history_index,
            history_authority=authority,
            history_authority_review=authority_review,
            execution_authority_contexts=contexts,
            history_artifact_file_sha256s=history[3],
        )

        authorization_id = next(iter(contexts))
        authorization = contexts[authorization_id]["authorization"]
        expected_sha256 = contexts[authorization_id][
            "expected_execution_authority_sha256"
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "network": root / "network.json",
                "needs": root / "needs.json",
                "challenge": root / "challenge.json",
                "history": root / "history.json",
                "authority": root / "authority.json",
                "review": root / "review.json",
                "execution": root / "execution.json",
                "compiled": root / "compiled.json",
            }
            for key, value in {
                "network": network,
                "needs": need_set,
                "challenge": challenge,
                "history": {
                    **history_index,
                    "artifact_file_sha256s": history[3],
                },
                "authority": authority,
                "review": authority_review,
                "execution": authorization,
            }.items():
                discovery.write_json(paths[key], value)

            compile_args = [
                "compile-appraisal-needs",
                "--needs",
                str(paths["needs"]),
                "--challenge",
                str(paths["challenge"]),
                "--history-index",
                str(paths["history"]),
                "--history-authority",
                str(paths["authority"]),
                "--history-authority-review",
                str(paths["review"]),
                "--network",
                str(paths["network"]),
                "--round-id",
                "ROUND-V2-HISTORY-CLI",
                "--output",
                str(paths["compiled"]),
            ]
            self.assertEqual(discovery.main(compile_args), 2)
            self.assertFalse(paths["compiled"].exists())
            self.assertEqual(
                discovery.main(
                    compile_args
                    + [
                        "--execution-authority",
                        str(paths["execution"]),
                        "--expected-execution-authority-sha256",
                        expected_sha256,
                    ]
                ),
                0,
            )
            validate_args = [
                "validate",
                "--input",
                str(paths["history"]),
                "--history-authority",
                str(paths["authority"]),
                "--history-authority-review",
                str(paths["review"]),
            ]
            self.assertEqual(discovery.main(validate_args), 2)
            self.assertEqual(
                discovery.main(
                    validate_args
                    + [
                        "--execution-authority",
                        str(paths["execution"]),
                        "--expected-execution-authority-sha256",
                        expected_sha256,
                    ]
                ),
                0,
            )

    def test_only_scholar_route_enters_reviewed_selected_only_chain(self):
        network, _, scholar_need, code_need, selected, requests = (
            compiled_selected_fixture()
        )
        self.assertEqual(len(selected["hypotheses"]), 1)
        self.assertEqual(selected["routed_needs"], [code_need])
        self.assertEqual(len(requests["requests"]), 1)
        self.assertEqual(requests["schema"], discovery.APPRAISAL_REQUEST_SET_SCHEMA)
        self.assertTrue(
            requests["requests"][0]["request_id"].startswith(
                discovery.APPRAISAL_REQUEST_ID_PREFIX
            )
        )
        origin = requests["requests"][0]["appraisal_origin"]
        self.assertEqual(origin["appraisal_set_ref"], APPRAISAL_SET_REF)
        self.assertEqual(origin["need_ref"]["need_id"], scholar_need["need_id"])
        self.assertEqual(origin["need_ref"]["route"], "scholar_discovery")
        self.assertEqual(origin["appraisal_ref"], scholar_need["appraisal_ref"])
        discovery.validate_request_set(requests, network=network)

    def test_network_emitter_validates_and_executes_through_scholar_stub(self):
        _, _, _, _, _, requests = compiled_selected_fixture()
        scholar = discovery._scholar_discovery_module()
        validated = scholar.validate_appraisal_request_set(copy.deepcopy(requests))
        self.assertEqual(validated["requests"], requests["requests"])

        called_urls = []

        def transport(url, timeout):
            called_urls.append(url)
            if "openalex" in url:
                return b'{"meta":{"count":0},"results":[]}'
            if "crossref" in url:
                return b'{"message":{"total-results":0,"items":[]}}'
            return b'{"total":0,"data":[]}'

        request_set_file_path, request_set_file_sha = request_set_file_artifact(requests)
        execution_authority = scholar.authorize_request_set(
            copy.deepcopy(requests),
            reviewer_id="reviewer-execution-appraisal-1",
            reviewer_role="independent appraisal search execution reviewer",
            reviewed_at=NOW,
            independent_reviewer_attested=True,
            request_set_file=request_set_file_path,
            request_set_file_sha256=request_set_file_sha,
        )
        execution_authority_file_sha256 = (
            scholar.canonical_search_execution_authorization_file_sha256(
                execution_authority
            )
        )
        result_set = execute_appraisal_request_set_with_authority_file(
            scholar,
            requests,
            transport,
            execution_authority=execution_authority,
            expected_execution_authority_sha256=(execution_authority_file_sha256),
            request_set_file=request_set_file_path,
            request_set_file_sha256=request_set_file_sha,
            timeout_seconds=30,
        )
        self.assertTrue(called_urls)
        self.assertEqual(result_set["schema"], discovery.RESULT_SET_V2_SCHEMA)
        self.assertEqual(
            result_set["execution_authorization_ref"]["authorization_id"],
            execution_authority["authorization_id"],
        )
        discovery.validate_scholar_discovery_result_set(
            copy.deepcopy(result_set),
            request_set=requests,
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
            request_set_file_sha256=result_set["execution_authorization_ref"][
                "request_set_file_sha256"
            ],
        )
        self.assertEqual(
            result_set["results"][0]["request_id"],
            requests["requests"][0]["request_id"],
        )

    def test_execute_appraisal_request_set_rejects_missing_and_wrong_pins_before_transport(self):
        _, _, _, _, _, requests = compiled_selected_fixture()
        scholar = discovery._scholar_discovery_module()
        called_urls = []

        def forbidden_transport(url, timeout):
            called_urls.append(url)
            return b"{}"

        authority_request_set_file, authority_request_set_file_sha = (
            request_set_file_artifact(requests)
        )
        execution_authority = scholar.authorize_request_set(
            copy.deepcopy(requests),
            reviewer_id="reviewer-execution-appraisal-3",
            reviewer_role="independent appraisal search execution reviewer",
            reviewed_at=NOW,
            independent_reviewer_attested=True,
            request_set_file=authority_request_set_file,
            request_set_file_sha256=authority_request_set_file_sha,
        )
        execution_authority_file_sha256 = (
            scholar.canonical_search_execution_authorization_file_sha256(
                execution_authority
            )
        )

        pretty_request_set_file_sha = hashlib.sha256(
            json.dumps(
                requests,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        ).hexdigest()

        with self.assertRaisesRegex(
            (
                discovery.ContractError,
                discovery._scholar_discovery_module().ContractError,
            ),
            "provider execution requires",
        ):
            scholar.execute_appraisal_request_set(
                copy.deepcopy(requests),
                forbidden_transport,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=authority_request_set_file,
                request_set_file_sha256=authority_request_set_file_sha,
            )
        self.assertEqual(called_urls, [])

        with self.assertRaisesRegex(
            (
                discovery.ContractError,
                discovery._scholar_discovery_module().ContractError,
            ),
            "execution authority file|external trust boundary",
        ):
            execute_appraisal_request_set_with_authority_file(
                scholar,
                requests,
                forbidden_transport,
                timeout_seconds=30,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                execution_authority_file_sha256="f" * 64,
                request_set_file=authority_request_set_file,
                request_set_file_sha256=authority_request_set_file_sha,
            )
        self.assertEqual(called_urls, [])

        with self.assertRaisesRegex(
            (
                discovery.ContractError,
                discovery._scholar_discovery_module().ContractError,
            ),
            "request_set_file_sha256|owner-replayed",
        ):
            execute_appraisal_request_set_with_authority_file(
                scholar,
                requests,
                forbidden_transport,
                timeout_seconds=30,
                execution_authority=execution_authority,
                expected_execution_authority_sha256=execution_authority_file_sha256,
                request_set_file=authority_request_set_file,
                request_set_file_sha256=pretty_request_set_file_sha,
            )
        self.assertEqual(called_urls, [])

    def test_real_evidence_appraisal_producer_package_uses_same_goal_projection(self):
        producer_path = (
            Path(__file__).resolve().parents[2]
            / "evidence-appraisal"
            / "scripts"
            / "evidence_appraisal.py"
        )
        spec = importlib.util.spec_from_file_location(
            "_test_real_evidence_appraisal", producer_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(producer)
        owner_fixture_path = producer_path.with_name("fixtures") / "owner_fixture.py"
        owner_spec = importlib.util.spec_from_file_location(
            "_test_real_evidence_appraisal_owner_fixture", owner_fixture_path
        )
        self.assertIsNotNone(owner_spec)
        self.assertIsNotNone(owner_spec.loader)
        owner_fixture = importlib.util.module_from_spec(owner_spec)
        owner_spec.loader.exec_module(owner_fixture)
        fixtures = producer_path.with_name("fixtures")
        request = json.loads(
            (fixtures / "minimal_request.json").read_text(encoding="utf-8")
        )
        review = json.loads(
            (fixtures / "minimal_independent_review.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            bindings, owner_bundle = owner_fixture.make_anonymous_owner_bundle(
                Path(temporary_directory) / "owner", "anonymous"
            )
            prepared = producer.prepare_appraisal(
                request, owner_artifact_bindings=bindings
            )
            review["prepared_request_digest"] = prepared["request_digest"]
            review["prepared_request_file_sha256"] = prepared[
                "prepared_request_file_sha256"
            ]
            review["owner_artifact_binding_digests"] = copy.deepcopy(
                prepared["owner_artifact_binding_digests"]
            )
            owner_digest, owner_binding = (
                owner_fixture.select_owner_attestation_binding(prepared)
            )
            for relation in review["relation_appraisals"]:
                if (
                    relation["attestation_refs"]
                    and owner_binding["lineage_id"] not in relation["source_lineage"]
                ):
                    relation["source_lineage"].append(owner_binding["lineage_id"])
                for attestation in relation["attestation_refs"]:
                    attestation["owner_attestation_binding_digest"] = owner_digest
                    attestation["binding_digest"] = (
                        producer.compute_attestation_binding_digest(
                            prepared,
                            relation["claim_ref"],
                            relation["evidence_ref"],
                            attestation["locator_ref"],
                            review["reviewer_context"],
                        )
                    )
            materialized_relations = {
                (
                    relation["claim_ref"],
                    relation["evidence_ref"],
                ): producer._materialize_relation(
                    relation,
                    prepared,
                    review["reviewer_context"],
                    f"independent_review.relation_appraisals[{index}]",
                )
                for index, relation in enumerate(review["relation_appraisals"])
            }
            for collection_name in ("challenges", "targeted_evidence_needs"):
                for item in review[collection_name]:
                    legacy_ref = item["relation_ref"]
                    materialized = materialized_relations[
                        (legacy_ref["claim_ref"], legacy_ref["evidence_ref"])
                    ]
                    item["relation_ref"] = {
                        field: materialized[field]
                        for field in (
                            "appraisal_id",
                            "semantic_digest",
                            "claim_ref",
                            "evidence_ref",
                        )
                    }
            review_file_projection = {
                key: value
                for key, value in review.items()
                if key
                not in {
                    "independent_review_file_sha256",
                    "independent_review_digest",
                }
            }
            review["independent_review_file_sha256"] = hashlib.sha256(
                producer.canonical_json_bytes(review_file_projection)
            ).hexdigest()
            review_semantic = {
                key: value
                for key, value in review.items()
                if key != "independent_review_digest"
            }
            review["independent_review_digest"] = hashlib.sha256(
                producer.canonical_json_bytes(review_semantic)
            ).hexdigest()
            appraisal_set = producer.finalize_appraisal(prepared, review, owner_bundle)
            approval = producer.create_reviewed_authority(
                prepared,
                review,
                appraisal_set,
                {
                    "reviewer_ref": "approval-reviewer-1",
                    "review_method": "independent-approval",
                    "reviewed_at": "time-2",
                },
                owner_bundle,
            )
            expected_authority_sha256 = approval["authority_digest"]
            package = producer.build_appraisal_package(
                appraisal_set,
                prepared,
                review,
                approval,
                owner_bundle,
                expected_authority_sha256=expected_authority_sha256,
            )
            with self.assertRaisesRegex(
                discovery.ContractError, "expected_authority_sha256"
            ):
                discovery.validate_evidence_appraisal_package(package)
            validated = discovery.validate_evidence_appraisal_package(
                package,
                approval,
                prepared,
                review,
                owner_bundle,
                expected_authority_sha256=expected_authority_sha256,
            )
            with self.assertRaisesRegex(
                discovery.ContractError, "external trust boundary"
            ):
                discovery.validate_evidence_appraisal_package(
                    package,
                    approval,
                    prepared,
                    review,
                    owner_bundle,
                    expected_authority_sha256="f" * 64,
                )
            need = validated["targeted_evidence_need_set"]["needs"][0]
            self.assertEqual(
                need["confirm_goal"],
                discovery._format_producer_observation_goal(
                    need["adversarial_observation_pair"], "confirm"
                ),
            )
            self.assertNotEqual(need["route"], "scholar_discovery")
            self.assertEqual(need["domain_anchors"], [])
            dispatch = discovery.dispatch_evidence_appraisal_package(
                package,
                approval,
                prepared,
                review,
                owner_bundle,
                expected_authority_sha256=expected_authority_sha256,
            )
            self.assertEqual(
                dispatch["routed_needs"],
                validated["targeted_evidence_need_set"]["needs"],
            )
            self.assertEqual(dispatch["scholar_discovery_needs"], [])
            self.assertFalse(dispatch["mutation_authorized"])

    def test_identical_and_synonym_only_confirm_refute_fail_closed(self):
        network = network_fixture()
        challenge = seal_challenge()
        cases = [
            (
                "independent implementation reproduces stable ranking",
                "independent implementation reproduces stable ranking",
            ),
            (
                "independent code replicated stable ranking",
                "stable ranking reproduced by independent code",
            ),
        ]
        for confirm_goal, refute_goal in cases:
            with self.subTest(refute_goal=refute_goal):
                need = seal_need(
                    challenge,
                    confirm_goal=confirm_goal,
                    refute_goal=refute_goal,
                )
                with self.assertRaises(discovery.ContractError):
                    compile_needs(
                        seal_need_set([need]),
                        [challenge],
                        network,
                        round_id="ROUND-ORTHOGONAL",
                    )

    def test_same_direction_goals_are_not_adversarially_orthogonal(self):
        network = network_fixture()
        challenge = seal_challenge()
        need = seal_need(
            challenge,
            confirm_goal="independent implementation reproduces stable ranking",
            refute_goal="independent implementation does not reverse and preserves stable ranking",
            observation_pair=observation_pair_fixture(refute_operator="reproduced"),
        )
        with self.assertRaisesRegex(
            discovery.ContractError, "ordered complementary pair"
        ):
            compile_needs(
                seal_need_set([need]),
                [challenge],
                network,
                round_id="ROUND-SAME-DIRECTION",
            )

    def test_free_text_negation_cannot_override_a_formally_valid_pair(self):
        network = network_fixture()
        challenge = seal_challenge()
        need = seal_need(
            challenge,
            refute_goal=(
                "independent implementation does not reverse and preserves "
                "stable Shapley ranking"
            ),
        )
        with self.assertRaisesRegex(
            discovery.ContractError,
            "deterministic structured observation projection",
        ):
            compile_needs(
                seal_need_set([need]),
                [challenge],
                network,
                round_id="ROUND-FREE-TEXT-NEGATION",
            )

    def test_long_fixturec_context_preserves_structured_query_core_or_fails_closed(self):
        network = network_fixture()
        semantic = semantic_fixture(
            "Fixture-c style dependent input sensitivity allocation across copula "
            "families sample sizes estimator configurations and convergence regimes"
        )
        semantic["evidence_class"] = (
            "independent numerical replication with allocation diagnostics"
        )
        semantic["independence_requirement"] = (
            "separate implementation data pipeline and numerical configuration"
        )
        challenge = seal_challenge(semantic=semantic)
        need = seal_need(challenge, semantic=semantic)
        need["paper_need"] = (
            "Fixture-c style dependent-input sensitivity allocation comparison across "
            "many copula families estimators implementations diagnostics and regimes"
        )
        need["should_criteria"] = sorted(
            [
                "copula family robustness analysis",
                "independent numerical implementation",
                "multiple sample size regimes",
            ]
        )
        need["need_digest"] = discovery._canonical_own_digest(need, "need_digest")
        compiled = compile_needs(
            seal_need_set([need]),
            [challenge],
            network,
            round_id="ROUND-FIXTUREC-LONG-CONTEXT",
        )
        queries = compiled["hypotheses"][0]["search_test"]["queries"]
        for query in queries:
            objective = query["objective"]
            normalized_terms = set(
                discovery._structured_query_slot_terms(
                    query["query"], f"{objective} test query"
                )
            )
            pair = need["adversarial_observation_pair"]
            observation = pair[objective]
            slot_terms = {
                "target_metric": discovery._structured_query_slot_terms(
                    pair["target_metric"], f"{objective} test target metric"
                ),
                "comparator": discovery._structured_query_slot_terms(
                    pair["comparator"], f"{objective} test comparator"
                ),
                "boundary": discovery._structured_query_slot_terms(
                    pair["boundary"], f"{objective} test boundary"
                ),
                "operator": discovery._structured_query_slot_terms(
                    discovery.OBSERVATION_OPERATOR_QUERY_TEXT[observation["operator"]],
                    f"{objective} test operator",
                ),
                "value_or_state": discovery._structured_query_slot_terms(
                    observation["value_or_state"],
                    f"{objective} test value_or_state",
                ),
            }
            slot_phrases = {
                "target_metric": discovery._structured_query_slot_phrase(
                    pair["target_metric"], f"{objective} structured target_metric"
                ),
                "comparator": discovery._structured_query_slot_phrase(
                    pair["comparator"], f"{objective} structured comparator"
                ),
                "boundary": discovery._structured_query_slot_phrase(
                    pair["boundary"], f"{objective} structured boundary"
                ),
                "operator": discovery._structured_query_slot_phrase(
                    discovery.OBSERVATION_OPERATOR_QUERY_TEXT[observation["operator"]],
                    f"{objective} structured operator",
                ),
                "value_or_state": discovery._structured_query_slot_phrase(
                    observation["value_or_state"],
                    f"{objective} structured value_or_state",
                ),
            }
            self.assertLessEqual(
                len(query["query"].split()), discovery.SEMANTIC_QUERY_MAX_WORDS
            )
            normalized_query_phrase = discovery._normalized_contiguous_phrase(
                query["query"], f"{objective} normalized test query"
            )
            for field in (
                "target_metric",
                "comparator",
                "boundary",
                "operator",
                "value_or_state",
            ):
                self.assertTrue(set(slot_terms[field]).issubset(normalized_terms))
            for field in (
                "target_metric",
                "comparator",
                "boundary",
                "operator",
                "value_or_state",
            ):
                self.assertTrue(
                    discovery._contains_contiguous_phrase(
                        normalized_query_phrase,
                        slot_phrases[field],
                    )
                )
            operator_state_phrase = (
                f"{slot_phrases['operator']} {slot_phrases['value_or_state']}"
            ).strip()
            self.assertTrue(
                discovery._contains_contiguous_phrase(
                    normalized_query_phrase, operator_state_phrase
                )
            )
            for anchor in need["domain_anchors"]:
                self.assertTrue(
                    set(
                        discovery._structured_query_slot_terms(anchor, "test anchor")
                    ).issubset(normalized_terms)
                )
            self.assertTrue(
                discovery.APPRAISAL_QUERY_LABEL_TERMS.isdisjoint(
                    set(query["query"].split())
                )
            )

    def test_regression_preserves_overlapping_slot_and_anchor_tokens(self):
        network = network_fixture()
        observation_pair = observation_pair_fixture()
        observation_pair["comparator"] = "cv"
        observation_pair["boundary"] = "range"
        observation_pair["target_metric"] = "interval replication"
        observation_pair["confirm"]["value_or_state"] = "replication"
        observation_pair["refute"]["value_or_state"] = "replication"
        challenge = seal_challenge(
            semantic=semantic_fixture(
                target_scope="sampling protocol",
                comparator="cv",
                boundary_variable="range",
            ),
            observation_pair=observation_pair,
        )
        need = seal_need(
            challenge,
            observation_pair=observation_pair,
            domain_anchors=["independent replication", "audit"],
            confirm_goal=discovery.format_adversarial_observation_goal(
                observation_pair, "confirm"
            ),
            refute_goal=discovery.format_adversarial_observation_goal(
                observation_pair, "refute"
            ),
        )
        compiled = compile_needs(
            seal_need_set([need]),
            [challenge],
            network,
            round_id="ROUND-REGEN-OPERATOR-STATE-OVERLAP",
        )
        prioritized = discovery.prioritize(compiled, network)
        selected = discovery.select_hypotheses(
            prioritized, reviewed_selection(prioritized), network
        )
        requests = discovery.emit_search_requests(
            selected, network, google_scholar_policy="disabled"
        )
        for query_seed in requests["requests"][0]["query_seeds"]:
            normalized_query = discovery._normalized_contiguous_phrase(
                query_seed["query"], "test regression query"
            )
            self.assertTrue(
                discovery._contains_contiguous_phrase(
                    normalized_query, "interval replication"
                )
            )
            self.assertTrue(
                discovery._contains_contiguous_phrase(
                    normalized_query, "independent replication"
                )
            )
            self.assertGreaterEqual(normalized_query.split().count("replication"), 2)

        oversized_pair = observation_pair_fixture()
        oversized_state = (
            "stable conditional allocation ranking across dependent copula families "
            "sample sizes estimators implementations convergence diagnostics"
        )
        oversized_pair["confirm"]["value_or_state"] = oversized_state
        oversized_pair["refute"]["value_or_state"] = oversized_state
        oversized_challenge = seal_challenge(observation_pair=oversized_pair)
        oversized_need = seal_need(oversized_challenge, observation_pair=oversized_pair)
        with self.assertRaisesRegex(
            discovery.ContractError, "structured observation core exceeds"
        ):
            compile_needs(
                seal_need_set([oversized_need]),
                [oversized_challenge],
                network,
                round_id="ROUND-FIXTUREC-CORE-OVERFLOW",
            )

        anchor_overflow = seal_need(
            challenge,
            domain_anchors=[
                "copula family robustness audit",
                "finite sample convergence diagnostics",
            ],
        )
        with self.assertRaisesRegex(
            discovery.ContractError, "domain-anchor core exceeds"
        ):
            compile_needs(
                seal_need_set([anchor_overflow]),
                [challenge],
                network,
                round_id="ROUND-FIXTUREC-ANCHOR-OVERFLOW",
            )

        three_anchor_challenge = seal_challenge()
        three_anchor_need = seal_need(
            three_anchor_challenge,
            domain_anchors=[
                "shapley sensitivity analysis",
                "input dependence diagnostics",
                "finite sample convergence",
            ],
        )
        with self.assertRaisesRegex(
            discovery.ContractError, "domain-anchor core exceeds"
        ):
            compile_needs(
                seal_need_set([three_anchor_need]),
                [three_anchor_challenge],
                network,
                round_id="ROUND-ALL-ANCHORS-OR-FAIL",
            )

    def test_round06_paraphrase_and_nine_of_ten_history_reuse_are_rejected(self):
        network = network_fixture()
        challenges = []
        needs = []
        for index in range(10):
            semantic = semantic_fixture(
                target_scope=f"dependent input sensitivity allocation case{index}"
            )
            observation_pair = observation_pair_fixture()
            observation_pair["target_metric"] = f"Shapley case{index}"
            challenge = seal_challenge(
                semantic=semantic, observation_pair=observation_pair
            )
            challenges.append(challenge)
            needs.append(
                seal_need(
                    challenge,
                    suffix=f"case{index}",
                    domain_anchors=["shapley ranking", "input dependence"],
                )
            )
        history_queries = [
            " ".join(discovery._objective_terms(need, "confirm")) for need in needs[:9]
        ]
        with self.assertRaisesRegex(discovery.ContractError, "9/10 history reuse"):
            compile_needs(
                seal_need_set(needs),
                challenges,
                network,
                round_id="ROUND06-RETRY",
                history=history_fixture(history_queries),
            )

        challenge = challenges[0]
        need = seal_need(
            challenge,
            domain_anchors=["shapley ranking", "input dependence"],
        )
        paraphrase = " ".join(reversed(discovery._objective_terms(need, "confirm")))
        with self.assertRaisesRegex(discovery.ContractError, "history reuse"):
            compile_needs(
                seal_need_set([need]),
                [challenge],
                network,
                round_id="ROUND06-PARAPHRASE",
                history=history_fixture([paraphrase]),
            )

        replay_tampered, replay_authority, replay_review = history_fixture([paraphrase])
        replay_tampered["entries"] = []
        scholar = discovery._scholar_discovery_module()
        digest = scholar.canonical_search_history_digest(replay_tampered)
        replay_tampered["history_digest"] = digest
        replay_tampered["history_id"] = "search-history-" + digest[:16]
        with self.assertRaisesRegex(discovery.ContractError, "owner-replayed"):
            compile_needs(
                seal_need_set([need]),
                [challenge],
                network,
                round_id="ROUND06-RESEALED-HISTORY",
                history=(replay_tampered, replay_authority, replay_review),
            )

        duplicate_source = history_artifact([paraphrase], round_id="ROUND06-DUPLICATE")
        unrelated_source = history_artifact(
            ["orthogonal calibration benchmark"], round_id="ROUND05-UNRELATED"
        )
        authority, authority_review = history_authority_fixture(
            [duplicate_source, unrelated_source]
        )
        complete = scholar.build_search_history_index(
            [duplicate_source, unrelated_source],
            authority,
            authority_review,
            generated_at=NOW,
        )
        removed_digest = scholar.sha256_json(duplicate_source)
        subset = copy.deepcopy(complete)
        subset["source_artifacts"] = [
            row for row in subset["source_artifacts"] if row["sha256"] != removed_digest
        ]
        subset["artifact_universe"] = [
            row
            for row in subset["artifact_universe"]
            if row["sha256"] != removed_digest
        ]
        subset["entries"] = [
            row
            for row in subset["entries"]
            if row["source_ref"]["sha256"] != removed_digest
        ]
        digest = scholar.canonical_search_history_digest(subset)
        subset["history_digest"] = digest
        subset["history_id"] = "search-history-" + digest[:16]
        with self.assertRaisesRegex(discovery.ContractError, "authority universe"):
            compile_needs(
                seal_need_set([need]),
                [challenge],
                network,
                round_id="ROUND06-WHOLE-SOURCE-DELETION",
                history=(subset, authority, authority_review),
            )

    def test_structural_request_and_non_search_routes_do_not_become_search(self):
        network = network_fixture()
        semantic = semantic_fixture(target_scope="validation_target network dimension")
        challenge = seal_challenge(semantic=semantic)
        need = seal_need(challenge, semantic=semantic)
        with self.assertRaisesRegex(discovery.ContractError, "structural placeholder"):
            compile_needs(
                seal_need_set([need]),
                [challenge],
                network,
                round_id="ROUND-STRUCTURAL",
            )

        ordinary = seal_challenge()
        fulltext = seal_need(ordinary, route="full_text_review", suffix="fulltext")
        code = seal_need(ordinary, route="code_data", suffix="code")
        compiled = compile_needs(
            seal_need_set([fulltext, code]),
            [ordinary],
            network,
            round_id="ROUND-NONSEARCH",
        )
        self.assertEqual(compiled["hypotheses"], [])
        self.assertEqual(
            {need["route"] for need in compiled["routed_needs"]},
            {"full_text_review", "code_data"},
        )

        for bad_need, message in (
            (
                seal_need(ordinary, domain_anchors=["shapley sensitivity"]),
                "2 to 6",
            ),
            (
                seal_need(
                    ordinary,
                    route="code_data",
                    domain_anchors=["shapley sensitivity", "input dependence"],
                ),
                "empty for non-scholar",
            ),
            (
                seal_need(
                    ordinary,
                    domain_anchors=[
                        "five token domain anchor phrase",
                        "input dependence",
                    ],
                ),
                "1 to 4 tokens",
            ),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(discovery.ContractError, message):
                    compile_needs(
                        seal_need_set([bad_need]),
                        [ordinary],
                        network,
                        round_id="ROUND-BAD-DOMAIN-ANCHORS",
                    )

    def test_partial_provider_and_empty_result_leave_appraisal_need_open(self):
        network, _, _, _, selected, requests = compiled_selected_fixture(
            google_scholar_policy="disabled"
        )

        def partial_transport(url, timeout):
            del timeout
            if "openalex" in url:
                return b'{"meta":{"count":3},"results":[]}'
            if "crossref" in url:
                return b'{"message":{"total-results":0,"items":[]}}'
            return b'{"total":0,"data":[]}'

        partial_result, partial_contexts, partial_request_sha = (
            execute_appraisal_fixture(requests, partial_transport)
        )

        partial = discovery.consume_results(
            selected,
            network,
            requests,
            [partial_result],
            execution_authority_contexts=partial_contexts,
            request_set_file_sha256=partial_request_sha,
        )
        self.assertEqual(partial["hypotheses"][0]["status"], "awaiting")
        self.assertFalse(partial["cycle_state"]["saturation"])

        def empty_transport(url, timeout):
            del timeout
            if "openalex" in url:
                return b'{"meta":{"count":0},"results":[]}'
            if "crossref" in url:
                return b'{"message":{"total-results":0,"items":[]}}'
            return b'{"total":0,"data":[]}'

        empty_result, empty_contexts, empty_request_sha = execute_appraisal_fixture(
            requests, empty_transport
        )

        empty = discovery.consume_results(
            selected,
            network,
            requests,
            [empty_result],
            execution_authority_contexts=empty_contexts,
            request_set_file_sha256=empty_request_sha,
        )
        self.assertEqual(empty["hypotheses"][0]["status"], "unresolved")
        self.assertEqual(
            empty["hypotheses"][0]["status_basis"][0]["execution_state"],
            "bounded_no_candidate_not_novelty",
        )
        self.assertFalse(empty["cycle_state"]["saturation"])

        legacy = copy.deepcopy(empty_result)
        legacy["schema"] = discovery.RESULT_SET_SCHEMA
        del legacy["execution_authorization_ref"]
        with self.assertRaisesRegex(discovery.ContractError, "legacy display-only"):
            discovery.consume_results(selected, network, requests, [legacy])

    def test_appraisal_queries_preserve_every_anchor_as_a_contiguous_phrase(self):
        network, _, _, _, selected, requests = compiled_selected_fixture(
            google_scholar_policy="disabled"
        )
        anchors = selected["hypotheses"][0]["domain_anchors"]
        self.assertEqual(len(anchors), 2)
        for request in requests["requests"]:
            for query_seed in request["query_seeds"]:
                normalized_query = discovery._normalized_contiguous_phrase(
                    query_seed["query"], "test query"
                )
                for anchor in anchors:
                    self.assertTrue(
                        discovery._contains_contiguous_phrase(
                            normalized_query,
                            discovery._normalized_contiguous_phrase(
                                anchor, "test anchor"
                            ),
                        )
                    )

        tampered = copy.deepcopy(requests)
        first_anchor = anchors[0]
        reversed_anchor = " ".join(reversed(first_anchor.split()))
        self.assertNotEqual(first_anchor, reversed_anchor)
        first_query = tampered["requests"][0]["query_seeds"][0]
        first_query["query"] = first_query["query"].replace(
            first_anchor, reversed_anchor, 1
        )
        reseal_request_set(tampered)
        with self.assertRaises(discovery.ContractError):
            discovery.validate_request_set(tampered, network=network)

    def test_unrelated_candidates_fail_appraisal_query_precision_gate(self):
        network, _, _, _, selected, requests = compiled_selected_fixture(
            google_scholar_policy="disabled"
        )

        def unrelated_transport(url, timeout):
            del timeout
            if "crossref" in url:
                return json.dumps(
                    {
                        "message": {
                            "total-results": 1,
                            "items": [
                                {
                                    "title": ["Orthogonal clinical treatment trial"],
                                    "author": [{"family": "Unrelated"}],
                                    "issued": {"date-parts": [[2025]]},
                                    "container-title": ["Clinical Journal"],
                                    "DOI": "10.1000/unrelated.precision",
                                    "type": "journal-article",
                                    "URL": "https://example.org/unrelated",
                                }
                            ],
                        }
                    }
                ).encode("utf-8")
            if "openalex" in url:
                return b'{"meta":{"count":0},"results":[]}'
            return b'{"total":0,"data":[]}'

        result_set, contexts, request_sha = execute_appraisal_fixture(
            requests, unrelated_transport
        )
        consumed = discovery.consume_results(
            selected,
            network,
            requests,
            [result_set],
            execution_authority_contexts=contexts,
            request_set_file_sha256=request_sha,
        )
        hypothesis = consumed["hypotheses"][0]
        self.assertEqual(hypothesis["status"], "unresolved")
        self.assertEqual(
            hypothesis["status_basis"][0]["execution_state"],
            "query_precision_failed",
        )
        self.assertNotIn("review_requests", consumed)

        first_anchor = selected["hypotheses"][0]["domain_anchors"][0]

        def one_anchor_transport(url, timeout):
            del timeout
            if "crossref" in url:
                return json.dumps(
                    {
                        "message": {
                            "total-results": 1,
                            "items": [
                                {
                                    "title": [
                                        f"{first_anchor} unrelated clinical trial"
                                    ],
                                    "author": [{"family": "OffTarget"}],
                                    "issued": {"date-parts": [[2025]]},
                                    "container-title": ["Irrelevant Journal"],
                                    "DOI": "10.1000/one.anchor.only",
                                    "type": "journal-article",
                                    "URL": "https://example.org/one-anchor",
                                }
                            ],
                        }
                    }
                ).encode("utf-8")
            if "openalex" in url:
                return b'{"meta":{"count":0},"results":[]}'
            return b'{"total":0,"data":[]}'

        one_anchor_result, one_anchor_contexts, one_anchor_request_sha = (
            execute_appraisal_fixture(requests, one_anchor_transport)
        )
        one_anchor = discovery.consume_results(
            selected,
            network,
            requests,
            [one_anchor_result],
            execution_authority_contexts=one_anchor_contexts,
            request_set_file_sha256=one_anchor_request_sha,
        )
        self.assertEqual(one_anchor["hypotheses"][0]["status"], "unresolved")
        self.assertEqual(
            one_anchor["hypotheses"][0]["status_basis"][0]["execution_state"],
            "query_precision_failed",
        )
        self.assertNotIn("review_requests", one_anchor)

        anchors = selected["hypotheses"][0]["domain_anchors"]

        def reordered_phrase_transport(url, timeout):
            del timeout
            if "crossref" in url:
                return json.dumps(
                    {
                        "message": {
                            "total-results": 1,
                            "items": [
                                {
                                    "title": [
                                        "sensitivity Shapley under input dependence"
                                    ],
                                    "author": [{"family": "OutOfOrder"}],
                                    "issued": {"date-parts": [[2025]]},
                                    "container-title": ["Irrelevant Journal"],
                                    "DOI": "10.1000/reordered.anchor",
                                    "type": "journal-article",
                                    "URL": "https://example.org/reordered-anchor",
                                }
                            ],
                        }
                    }
                ).encode("utf-8")
            if "openalex" in url:
                return b'{"meta":{"count":0},"results":[]}'
            return b'{"total":0,"data":[]}'

        reordered_result, reordered_contexts, reordered_request_sha = (
            execute_appraisal_fixture(requests, reordered_phrase_transport)
        )
        reordered = discovery.consume_results(
            selected,
            network,
            requests,
            [reordered_result],
            execution_authority_contexts=reordered_contexts,
            request_set_file_sha256=reordered_request_sha,
        )
        self.assertEqual(reordered["hypotheses"][0]["status"], "unresolved")
        self.assertEqual(
            reordered["hypotheses"][0]["status_basis"][0]["execution_state"],
            "query_precision_failed",
        )
        self.assertNotIn("review_requests", reordered)

        def mixed_precision_transport(url, timeout):
            del timeout
            if "crossref" in url:
                return json.dumps(
                    {
                        "message": {
                            "total-results": 2,
                            "items": [
                                {
                                    "title": [f"{anchors[0]} under {anchors[1]}"],
                                    "author": [{"family": "OnTarget"}],
                                    "issued": {"date-parts": [[2025]]},
                                    "container-title": ["Target Journal"],
                                    "DOI": "10.1000/all.anchors",
                                    "type": "journal-article",
                                    "URL": "https://example.org/all-anchors",
                                },
                                {
                                    "title": [f"{anchors[0]} unrelated trial"],
                                    "author": [{"family": "OffTarget"}],
                                    "issued": {"date-parts": [[2025]]},
                                    "container-title": ["Irrelevant Journal"],
                                    "DOI": "10.1000/mixed.off-target",
                                    "type": "journal-article",
                                    "URL": "https://example.org/mixed-off-target",
                                },
                            ],
                        }
                    }
                ).encode("utf-8")
            if "openalex" in url:
                return b'{"meta":{"count":0},"results":[]}'
            return b'{"total":0,"data":[]}'

        mixed_result, mixed_contexts, mixed_request_sha = execute_appraisal_fixture(
            requests, mixed_precision_transport
        )
        mixed = discovery.consume_results(
            selected,
            network,
            requests,
            [mixed_result],
            execution_authority_contexts=mixed_contexts,
            request_set_file_sha256=mixed_request_sha,
        )
        self.assertEqual(mixed["hypotheses"][0]["status"], "unresolved")
        self.assertEqual(
            mixed["hypotheses"][0]["status_basis"][0]["execution_state"],
            "query_precision_failed",
        )
        self.assertNotIn("review_requests", mixed)

        missing_ref = copy.deepcopy(result_set)
        del missing_ref["execution_authorization_ref"]
        with self.assertRaises(discovery.ContractError):
            discovery.consume_results(
                selected,
                network,
                requests,
                [missing_ref],
                execution_authority_contexts=contexts,
                request_set_file_sha256=request_sha,
            )

    def test_request_set_replay_rejects_deleted_origin_and_unreviewed_append(self):
        network, _, _, _, selected, requests = compiled_selected_fixture()
        scholar = discovery._scholar_discovery_module()

        deleted_origin = copy.deepcopy(requests)
        del deleted_origin["requests"][0]["appraisal_origin"]
        reseal_request_set(deleted_origin)
        for validator in (
            lambda value: discovery.validate_request_set(value, network=network),
            scholar.validate_request_set,
        ):
            with self.subTest(case="deleted-origin", validator=validator):
                with self.assertRaises(ValueError):
                    validator(copy.deepcopy(deleted_origin))

        downgraded = copy.deepcopy(requests)
        del downgraded["requests"][0]["appraisal_origin"]
        for field in (
            "selected_hypotheses",
            "google_scholar_policy",
            "request_profile",
        ):
            downgraded.pop(field)
        reseal_request_set(downgraded)
        for validator in (
            lambda value: discovery.validate_request_set(value, network=network),
            scholar.validate_request_set,
        ):
            with self.subTest(case="strict-profile-downgrade", validator=validator):
                with self.assertRaisesRegex(
                    ValueError, "complete selected projection|appraisal request ID"
                ):
                    validator(copy.deepcopy(downgraded))

        fully_downgraded = copy.deepcopy(requests)
        for field in (
            "reviewed_selection_ref",
            "selected_hypothesis_ids",
            "selected_hypotheses_sha256",
            "selected_hypotheses",
            "google_scholar_policy",
            "request_profile",
        ):
            fully_downgraded.pop(field)
        del fully_downgraded["requests"][0]["appraisal_origin"]
        fully_downgraded["schema"] = discovery.REQUEST_SET_SCHEMA
        extra = copy.deepcopy(fully_downgraded["requests"][0])
        extra["request_id"] = "SDR-UNREVIEWED-GENERIC"
        extra["gap_hypothesis_id"] = "KGH-UNREVIEWED-GENERIC"
        extra["gap_ref"]["gap_id"] = "KGH-UNREVIEWED-GENERIC"
        fully_downgraded["requests"].append(extra)
        reseal_request_set(fully_downgraded)
        for validator in (
            lambda value: discovery.validate_request_set(value, network=network),
            scholar.validate_request_set,
        ):
            with self.subTest(case="generic-appraisal-id", validator=validator):
                with self.assertRaisesRegex(ValueError, "appraisal request ID"):
                    validator(copy.deepcopy(fully_downgraded))

        transport_calls = []

        def forbidden_transport(url, timeout):
            transport_calls.append(url)
            return b"{}"

        with self.assertRaisesRegex(ValueError, "appraisal request ID"):
            downgraded_request_set_file, downgraded_request_set_file_sha = (
                request_set_file_artifact(fully_downgraded)
            )
            scholar.execute_request_set(
                copy.deepcopy(fully_downgraded),
                forbidden_transport,
                request_set_file=downgraded_request_set_file,
                request_set_file_sha256=downgraded_request_set_file_sha,
            )
        self.assertEqual(transport_calls, [])

        with self.assertRaisesRegex(discovery.ContractError, "execution route"):
            discovery.consume_results(selected, network, fully_downgraded, [])
        with self.assertRaisesRegex(ValueError, "appraisal request ID"):
            scholar.validate_appraisal_request_set(fully_downgraded)

        generic_request_set = copy.deepcopy(fully_downgraded)
        generic_request_set["requests"] = [generic_request_set["requests"][0]]
        generic_request_set["requests"][0]["request_id"] = (
            discovery.GENERIC_REQUEST_ID_PREFIX
            + generic_request_set["requests"][0]["gap_hypothesis_id"]
        )
        reseal_request_set(generic_request_set)
        scholar.validate_request_set(copy.deepcopy(generic_request_set))
        with self.assertRaisesRegex(ValueError, "appraisal execution requires"):
            generic_request_set_file, generic_request_set_file_sha = (
                request_set_file_artifact(generic_request_set)
            )
            scholar.execute_appraisal_request_set(
                copy.deepcopy(generic_request_set),
                forbidden_transport,
                request_set_file=generic_request_set_file,
                request_set_file_sha256=generic_request_set_file_sha,
            )
        self.assertEqual(transport_calls, [])

        requests_file_path, requests_file_sha = request_set_file_artifact(requests)
        appraisal_authority = scholar.authorize_request_set(
            copy.deepcopy(requests),
            reviewer_id="reviewer-execution-appraisal-2",
            reviewer_role="independent appraisal search execution reviewer",
            reviewed_at=NOW,
            independent_reviewer_attested=True,
            request_set_file=requests_file_path,
            request_set_file_sha256=requests_file_sha,
        )
        appraisal_authority_file_sha256 = (
            scholar.canonical_search_execution_authorization_file_sha256(
                appraisal_authority
            )
        )
        with self.assertRaisesRegex(ValueError, "owner-replayed"):
            generic_request_set_file, generic_request_set_file_sha = (
                request_set_file_artifact(generic_request_set)
            )
            execute_request_set_with_authority_file(
                scholar,
                generic_request_set,
                forbidden_transport,
                execution_authority=appraisal_authority,
                expected_execution_authority_sha256=(appraisal_authority_file_sha256),
                request_set_file=generic_request_set_file,
                request_set_file_sha256=generic_request_set_file_sha,
            )
        self.assertEqual(transport_calls, [])

        wrong_prefix = copy.deepcopy(requests)
        wrong_prefix["requests"][0]["request_id"] = (
            discovery.GENERIC_REQUEST_ID_PREFIX
            + wrong_prefix["requests"][0]["gap_hypothesis_id"]
        )
        reseal_request_set(wrong_prefix)
        for validator in (
            lambda value: discovery.validate_request_set(value, network=network),
            scholar.validate_request_set,
        ):
            with self.subTest(case="appraisal-generic-id", validator=validator):
                with self.assertRaisesRegex(ValueError, "ASDR-"):
                    validator(copy.deepcopy(wrong_prefix))

        wrong_route = copy.deepcopy(requests)
        wrong_route["requests"][0]["appraisal_origin"]["need_ref"]["route"] = (
            "full_text_review"
        )
        reseal_request_set(wrong_route)
        for validator in (
            lambda value: discovery.validate_request_set(value, network=network),
            scholar.validate_request_set,
        ):
            with self.subTest(case="appraisal-wrong-route", validator=validator):
                with self.assertRaisesRegex(ValueError, "scholar_discovery"):
                    validator(copy.deepcopy(wrong_route))

        appended = copy.deepcopy(requests)
        extra = copy.deepcopy(appended["requests"][0])
        extra["request_id"] = "SDR-UNREVIEWED-APPEND"
        extra["gap_hypothesis_id"] = "KGH-UNREVIEWED-APPEND"
        extra["gap_ref"]["gap_id"] = "KGH-UNREVIEWED-APPEND"
        appended["requests"].append(extra)
        reseal_request_set(appended)
        for validator in (
            lambda value: discovery.validate_request_set(value, network=network),
            scholar.validate_request_set,
        ):
            with self.subTest(case="unreviewed-append", validator=validator):
                with self.assertRaises(ValueError):
                    validator(copy.deepcopy(appended))


if __name__ == "__main__":
    unittest.main()
