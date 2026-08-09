from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any, Callable


SCRIPT = Path(__file__).with_name("countercheck_closure.py")
SPEC = importlib.util.spec_from_file_location("countercheck_closure", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

OWNER_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scholar-discovery"
    / "scripts"
    / "scholar_discovery.py"
)
OWNER_SPEC = importlib.util.spec_from_file_location(
    "countercheck_test_scholar_owner", OWNER_SCRIPT
)
assert OWNER_SPEC and OWNER_SPEC.loader
OWNER = importlib.util.module_from_spec(OWNER_SPEC)
OWNER_SPEC.loader.exec_module(OWNER)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def knowledge_network_fixture() -> dict[str, Any]:
    network = {
        "schema": "KnowledgeNetwork/v1",
        "network_id": "network-1",
        "snapshot_id": "snapshot-frozen",
        "corpus_snapshot": {
            "source": "local",
            "target_ref": "private:local-corpus",
            "captured_at": "2026-08-09T00:00:00Z",
            "inventory_digest": "1" * 64,
            "item_count": 1,
            "item_refs": ["private:item:source-1"],
        },
        "nodes": [
            {
                "node_id": "source:source-1",
                "kind": "source",
                "label": "Synthetic primary source",
                "status": "active",
                "confidence": "high",
                "provenance": [
                    {"source_id": "source:source-1", "locator": "synthetic fixture"}
                ],
            },
            {
                "node_id": "entity:sensitivity-analysis",
                "kind": "entity",
                "label": "Sensitivity analysis",
                "status": "active",
                "confidence": "high",
                "provenance": [
                    {"source_id": "source:source-1", "locator": "synthetic fixture"}
                ],
            },
        ],
        "relations": [
            {
                "relation_id": "relation:source-about-method",
                "from_id": "source:source-1",
                "to_id": "entity:sensitivity-analysis",
                "predicate": "about",
                "status": "supported",
                "confidence": "high",
                "provenance": [
                    {"source_id": "source:source-1", "locator": "synthetic fixture"}
                ],
            }
        ],
        "gap_derivation": {
            "rules": ["missing", "conflict", "low_confidence"],
            "derived_gap_ids": [],
        },
        "gaps": [],
        "change_history": [
            {
                "change_id": "change:fixture",
                "action": "export",
                "object_ids": ["network-1"],
                "basis_refs": ["source:source-1"],
                "recorded_at": "2026-08-09T00:00:00Z",
            }
        ],
        "completion": {
            "status": "passed",
            "open_gap_ids": [],
            "blocking_gap_ids": [],
            "gate_checks": {
                "corpus_snapshotted": True,
                "provenance_complete": True,
                "conflicts_terminal": True,
                "low_confidence_edges_terminal": True,
                "high_priority_explicit_gaps_terminal": True,
                "change_history_recorded": True,
            },
        },
        "sources": [{"source_id": "source-1"}],
        "claims": [],
        "evidence": [],
        "events": [],
        "projection_omissions": [],
        "ledger_digest": "2" * 64,
    }
    network["content_sha256"] = MODULE.canonical_network_content_sha256(network)
    return network


class SyntheticBaseException(BaseException):
    pass


class CountercheckClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.network = knowledge_network_fixture()
        self.network_path = self.write("network.json", self.network)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, value: Any) -> Path:
        path = self.root / name
        path.write_bytes(canonical_bytes(value) + b"\n")
        os.chmod(path, 0o600)
        return path

    def ref(self, path: Path, **extra: Any) -> dict[str, Any]:
        return {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **extra,
        }

    def network_ref(self, path: Path | None = None) -> dict[str, Any]:
        path = path or self.network_path
        value = json.loads(path.read_text(encoding="utf-8"))
        return self.ref(
            path,
            authoritative=True,
            snapshot_id=value["snapshot_id"],
            content_sha256=value["content_sha256"],
        )

    def make_plan(
        self,
        rows: list[tuple[str, str, list[str]]],
        *,
        name: str = "axis-plan.json",
    ) -> Path:
        plan = {
            "schema": "CountercheckAxisPlan/v1",
            "plan_id": "",
            "plan_digest": "",
            "created_at": "2026-08-09T00:00:00Z",
            "network_content_sha256": self.network["content_sha256"],
            "review_status": "approved",
            "axes": [
                {
                    "sequence": index,
                    "round_id": round_id,
                    "dimension": dimension,
                    "provider_families": sorted(providers),
                    "falsifier": (
                        f"Evidence from {round_id} that overturns the proposed no-add boundary"
                    ),
                    "expected_information_gain": (
                        f"Resolve the distinct {dimension} uncertainty tested in {round_id}"
                    ),
                }
                for index, (round_id, dimension, providers) in enumerate(rows, start=1)
            ],
        }
        digest = MODULE.canonical_axis_plan_digest(plan)
        plan["plan_digest"] = digest
        plan["plan_id"] = f"countercheck-axis-plan-{digest[:16]}"
        MODULE.validate_axis_plan(plan)
        return self.write(name, plan)

    def request_set(self, round_id: str, providers: list[str]) -> dict[str, Any]:
        topic_need_set = {
            "schema": "ResearchTopicNeedSet/v1",
            "schema_version": "v1",
            "topic_id": f"topic-{round_id}",
            "question": f"Countercheck the bounded sensitivity-analysis map in {round_id}",
            "as_of": "2026-08-09T00:00:00Z",
            "google_scholar_policy": "disabled",
            "automatic_providers": providers,
            "network_ref": {
                "network_id": "network-1",
                "snapshot_id": f"request-snapshot-{round_id}",
                "sha256": self.network["content_sha256"],
            },
            "needs": [
                {
                    "gap_id": f"gap-{round_id}",
                    "paper_need": (
                        f"Find sensitivity analysis evidence for the {round_id} countercheck"
                    ),
                    "criteria": {
                        "must": ["sensitivity analysis"],
                        "should": ["boundary evidence"],
                        "must_not": ["unrelated clinical sensitivity"],
                    },
                    "query_seeds": [
                        {
                            "objective": "confirm",
                            "query": (
                                f"sensitivity analysis {round_id} confirm boundary evidence"
                            ),
                        },
                        {
                            "objective": "refute",
                            "query": (
                                f"sensitivity analysis {round_id} refute failure limitation"
                            ),
                        },
                    ],
                }
            ],
        }
        request_set = OWNER.compile_topic_need_set(topic_need_set)
        return OWNER.validate_request_set(copy.deepcopy(request_set))

    @staticmethod
    def transport(url: str, timeout_seconds: int) -> bytes:
        del timeout_seconds
        if "api.crossref.org" in url:
            return json.dumps(
                {
                    "message": {
                        "total-results": 1,
                        "items": [
                            {
                                "title": ["Synthetic boundary study"],
                                "author": [{"family": "Tester"}],
                                "issued": {"date-parts": [[2025]]},
                                "container-title": ["Synthetic Methods"],
                                "DOI": "10.1000/synthetic.boundary",
                                "type": "journal-article",
                                "URL": "https://example.org/synthetic-boundary",
                            }
                        ],
                    }
                }
            ).encode("utf-8")
        if "api.semanticscholar.org" in url:
            return json.dumps(
                {
                    "total": 1,
                    "data": [
                        {
                            "paperId": "synthetic-s2-paper",
                            "title": "Synthetic independent replication",
                            "year": 2025,
                            "authors": [{"name": "Test Author"}],
                            "publicationTypes": ["JournalArticle"],
                            "venue": {"name": "Synthetic Methods"},
                            "externalIds": {"DOI": "10.1000/synthetic.replication"},
                            "openAccessPdf": {
                                "url": "https://example.org/synthetic-replication.pdf"
                            },
                            "url": "https://example.org/synthetic-replication",
                        }
                    ],
                }
            ).encode("utf-8")
        raise AssertionError(f"unexpected synthetic provider URL: {url}")

    def make_round(
        self,
        plan_path: Path,
        sequence: int,
        *,
        previous_closure: Path | None = None,
        result_status: str = "complete_bounded",
        review_status: str | None = None,
        round_status: str = "completed",
        after_network: dict[str, Any] | None = None,
    ) -> Path:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        axis = plan["axes"][sequence - 1]
        round_id = axis["round_id"]
        providers = axis["provider_families"]
        request_set = self.request_set(round_id, providers)
        request_path = self.write(f"{round_id}-requests.json", request_set)
        result_set = OWNER.execute_request_set(
            copy.deepcopy(request_set), self.transport, timeout_seconds=30
        )
        if result_status != "complete_bounded":
            result_set["results"][0]["discovery_status"] = result_status
            result_set["results"][0]["stop_reason"] = result_status
        OWNER.validate_result_set(copy.deepcopy(result_set))
        result_path = self.write(f"{round_id}-results.json", result_set)
        result_ref = self.ref(result_path)

        occurrences = sorted(
            [
                {
                    "request_id": result["request_id"],
                    "candidate_id": candidate["candidate_id"],
                }
                for result in result_set["results"]
                for candidate in result["ranked_candidates"]
            ],
            key=lambda row: (row["request_id"], row["candidate_id"]),
        )
        tier_ids: list[str] = []
        occurrence_rows = []
        for index, occurrence in enumerate(occurrences):
            disposition = "tier_a" if review_status and index == 0 else "excluded"
            if disposition == "tier_a":
                tier_ids.append(occurrence["candidate_id"])
            occurrence_rows.append(
                {
                    **occurrence,
                    "disposition": disposition,
                    "reason": "synthetic focused screening decision",
                }
            )
        tier_ids = sorted(set(tier_ids))
        screening = {
            "schema": "CountercheckScreeningSet/v1",
            "round_id": round_id,
            "request_set_id": request_set["request_set_id"],
            "request_set_digest": request_set["request_set_digest"],
            "selected_request_ids": [
                request["request_id"] for request in request_set["requests"]
            ],
            "result_set_ref": {
                "schema": "ScholarDiscoveryResultSet/v1",
                "sha256": result_ref["sha256"],
            },
            "candidate_occurrence_universe_sha256": MODULE.sha256_json(occurrences),
            "candidate_occurrences": occurrence_rows,
            "screening_complete": True,
            "unscreened_occurrence_count": 0,
            "tier_a_candidate_ids": tier_ids,
        }
        screening_path = self.write(f"{round_id}-screening.json", screening)
        reviews = []
        if review_status:
            reviews.append(
                {
                    "candidate_id": tier_ids[0],
                    "status": review_status,
                    "decision_relevant_add": review_status == "accepted_evidence",
                }
            )
        review = {
            "schema": "CountercheckTierAReviewSet/v1",
            "round_id": round_id,
            "request_set_id": request_set["request_set_id"],
            "request_set_digest": request_set["request_set_digest"],
            "tier_a_candidate_ids": tier_ids,
            "review_complete": review_status not in MODULE.PENDING_REVIEW_STATUSES,
            "reviews": reviews,
        }
        review_path = self.write(f"{round_id}-reviews.json", review)
        query_bindings = []
        query_offset = 0
        for request in request_set["requests"]:
            for seed in request["query_seeds"]:
                query_offset += 1
                query_bindings.append(
                    {
                        "query_id": f"query-{round_id}-{query_offset}",
                        "request_id": request["request_id"],
                        "objective": seed["objective"],
                        "normalized_query": seed["query"],
                    }
                )
        before_ref = self.network_ref()
        if after_network is None:
            after_ref = copy.deepcopy(before_ref)
        else:
            after_path = self.root / f"{round_id}-network-after.json"
            after_path.write_text(
                json.dumps(after_network, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.chmod(after_path, 0o600)
            after_ref = self.network_ref(after_path)
        manifest = {
            "schema": "CountercheckRoundClosureInput/v1",
            "round_id": round_id,
            "round_status": round_status,
            "assessed_at": "2026-08-09T00:30:00Z",
            "axis_plan_ref": self.ref(plan_path),
            "axis_sequence": sequence,
            "previous_closure_ref": (
                self.ref(previous_closure) if previous_closure is not None else None
            ),
            "search_axis": {
                "dimension": axis["dimension"],
                "queries": query_bindings,
            },
            "request_set_ref": self.ref(request_path),
            "result_set_ref": result_ref,
            "screening_ref": self.ref(screening_path),
            "tier_a_review_ref": self.ref(review_path),
            "network_before_ref": before_ref,
            "network_after_ref": after_ref,
        }
        return self.write(f"{round_id}-input.json", manifest)

    def close(self, input_path: Path, output_name: str) -> tuple[int, Path]:
        output = self.root / output_name
        code = MODULE.main(
            ["close-round", "--input", str(input_path), "--output", str(output)]
        )
        return code, output

    def assess(self, closures: list[Path], name: str = "streak") -> tuple[int, Path]:
        source = self.write(
            f"{name}-input.json",
            {
                "schema": "CountercheckStreakInput/v1",
                "assessed_at": "2026-08-09T01:00:00Z",
                "closure_refs": [self.ref(path) for path in closures],
            },
        )
        output = self.root / f"{name}-output.json"
        code = MODULE.main(
            ["assess-streak", "--input", str(source), "--output", str(output)]
        )
        return code, output

    def rewrite_referenced_artifact(
        self,
        manifest_path: Path,
        ref_field: str,
        transform: Callable[[dict[str, Any]], None],
    ) -> None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = Path(manifest[ref_field]["path"])
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        transform(artifact)
        self.write(artifact_path.name, artifact)
        manifest[ref_field] = self.ref(artifact_path)
        self.write(manifest_path.name, manifest)

    def test_owner_generated_result_closes_and_replays(self) -> None:
        plan = self.make_plan(
            [
                ("round-06", "failure_boundary", ["crossref"]),
                ("round-07", "independent_replication", ["semantic_scholar"]),
            ]
        )
        manifest = self.make_round(plan, 1)
        code, output = self.close(manifest, "round-06-closure.json")
        self.assertEqual(code, 0)
        closure = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(closure["closure_status"], "qualifying_no_add")
        self.assertTrue(closure["provider_coverage_complete"])
        self.assertEqual(MODULE.main(["validate", "--input", str(output)]), 0)

    def test_rejects_fake_result_shape_and_unknown_discovery_status(self) -> None:
        for label, transform in (
            (
                "fake",
                lambda value: value.update(
                    {
                        "results": [
                            {
                                "request_id": value["results"][0]["request_id"],
                                "status": "complete_bounded",
                            }
                        ]
                    }
                ),
            ),
            (
                "unknown",
                lambda value: value["results"][0].update(
                    {"discovery_status": "completed"}
                ),
            ),
        ):
            with self.subTest(label=label):
                plan = self.make_plan(
                    [
                        (f"round-{label}", "failure_boundary", ["crossref"]),
                        (
                            f"round-{label}-next",
                            "independent_replication",
                            ["semantic_scholar"],
                        ),
                    ],
                    name=f"{label}-plan.json",
                )
                manifest = self.make_round(plan, 1)
                self.rewrite_referenced_artifact(manifest, "result_set_ref", transform)
                code, output = self.close(manifest, f"{label}-must-not-exist.json")
                self.assertEqual(code, 2)
                self.assertFalse(output.exists())

    def test_screening_binds_result_digest_and_complete_occurrence_universe(self) -> None:
        cases = (
            (
                "missing-occurrence",
                lambda value: value["candidate_occurrences"].clear(),
            ),
            (
                "wrong-result-digest",
                lambda value: value["result_set_ref"].update({"sha256": "f" * 64}),
            ),
        )
        for label, transform in cases:
            with self.subTest(label=label):
                plan = self.make_plan(
                    [
                        (f"round-{label}", "counterexample", ["crossref"]),
                        (
                            f"round-{label}-next",
                            "citation_neighborhood",
                            ["semantic_scholar"],
                        ),
                    ],
                    name=f"{label}-plan.json",
                )
                manifest = self.make_round(plan, 1)
                self.rewrite_referenced_artifact(manifest, "screening_ref", transform)
                code, output = self.close(manifest, f"{label}-closure.json")
                self.assertEqual(code, 2)
                self.assertFalse(output.exists())

    def test_owner_partial_result_is_observed_but_not_qualifying(self) -> None:
        plan = self.make_plan(
            [
                ("round-partial", "counterexample", ["crossref"]),
                ("round-partial-next", "citation_neighborhood", ["semantic_scholar"]),
            ]
        )
        manifest = self.make_round(
            plan, 1, result_status="partial_provider", round_status="partial"
        )
        code, output = self.close(manifest, "partial-closure.json")
        self.assertEqual(code, 0)
        closure = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(closure["closure_status"], "partial_provider")
        self.assertTrue(closure["observed_no_add"])
        self.assertFalse(closure["qualifying_no_add"])

    def test_pending_review_and_accepted_evidence_remain_distinct(self) -> None:
        for label, review_status, expected in (
            ("pending", "fulltext_blocked", "review_pending"),
            ("accepted", "accepted_evidence", "evidence_added"),
        ):
            with self.subTest(label=label):
                plan = self.make_plan(
                    [
                        (f"round-{label}", "identity_version_correction", ["crossref"]),
                        (
                            f"round-{label}-next",
                            "independent_replication",
                            ["semantic_scholar"],
                        ),
                    ],
                    name=f"{label}-review-plan.json",
                )
                manifest = self.make_round(plan, 1, review_status=review_status)
                code, output = self.close(manifest, f"{label}-review-closure.json")
                self.assertEqual(code, 0)
                closure = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(closure["closure_status"], expected)

    def test_network_freeze_uses_content_digest_not_file_identity(self) -> None:
        plan = self.make_plan(
            [
                ("round-copy", "failure_boundary", ["crossref"]),
                ("round-copy-next", "citation_neighborhood", ["semantic_scholar"]),
            ]
        )
        variant = copy.deepcopy(self.network)
        manifest = self.make_round(plan, 1, after_network=variant)
        code, output = self.close(manifest, "content-stable-closure.json")
        self.assertEqual(code, 0)
        closure = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(closure["network_digest_unchanged"])

        drift_plan = self.make_plan(
            [
                ("round-content-drift", "counterexample", ["crossref"]),
                (
                    "round-content-drift-next",
                    "independent_replication",
                    ["semantic_scholar"],
                ),
            ],
            name="content-drift-plan.json",
        )
        drift = copy.deepcopy(self.network)
        drift["nodes"][1]["label"] = "Changed sensitivity-analysis meaning"
        drift["content_sha256"] = MODULE.canonical_network_content_sha256(drift)
        manifest = self.make_round(drift_plan, 1, after_network=drift)
        code, output = self.close(manifest, "content-drift-closure.json")
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_network_owner_rejects_tampered_nodes_and_self_digest(self) -> None:
        cases = {}
        duplicate_node = copy.deepcopy(self.network)
        duplicate_node["nodes"][1]["node_id"] = duplicate_node["nodes"][0]["node_id"]
        duplicate_node["content_sha256"] = MODULE.canonical_network_content_sha256(
            duplicate_node
        )
        cases["duplicate-node-with-canonical-digest"] = duplicate_node

        self_digest = copy.deepcopy(self.network)
        self_digest["nodes"][1]["label"] = "Tampered after export"
        self_digest["content_sha256"] = MODULE.sha256_json(self_digest)
        cases["tampered-node-with-self-digest"] = self_digest

        for index, (label, tampered) in enumerate(cases.items()):
            with self.subTest(label=label):
                self.write("network.json", self.network)
                plan = self.make_plan(
                    [
                        (f"round-owner-{index}", "failure_boundary", ["crossref"]),
                        (
                            f"round-owner-{index}-next",
                            "citation_neighborhood",
                            ["semantic_scholar"],
                        ),
                    ],
                    name=f"owner-{index}-plan.json",
                )
                manifest_path = self.make_round(plan, 1)
                self.write("network.json", tampered)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                tampered_ref = self.network_ref(self.network_path)
                manifest["network_before_ref"] = copy.deepcopy(tampered_ref)
                manifest["network_after_ref"] = copy.deepcopy(tampered_ref)
                self.write(manifest_path.name, manifest)
                code, output = self.close(
                    manifest_path, f"owner-{index}-must-not-exist.json"
                )
                self.assertEqual(code, 2)
                self.assertFalse(output.exists())

    def test_axis_plan_pre_review_enforces_all_orthogonality_dimensions(self) -> None:
        plan_path = self.make_plan(
            [
                ("axis-a", "failure_boundary", ["crossref"]),
                ("axis-b", "independent_replication", ["semantic_scholar"]),
            ]
        )
        original = json.loads(plan_path.read_text(encoding="utf-8"))
        mutations = {
            "dimensions": lambda value: value["axes"][1].update(
                {"dimension": value["axes"][0]["dimension"]}
            ),
            "provider-family": lambda value: value["axes"][1].update(
                {"provider_families": value["axes"][0]["provider_families"]}
            ),
            "falsifier": lambda value: value["axes"][1].update(
                {"falsifier": value["axes"][0]["falsifier"]}
            ),
            "information-gain": lambda value: value["axes"][1].update(
                {
                    "expected_information_gain": value["axes"][0][
                        "expected_information_gain"
                    ]
                }
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value = copy.deepcopy(original)
                mutate(value)
                digest = MODULE.canonical_axis_plan_digest(value)
                value["plan_digest"] = digest
                value["plan_id"] = f"countercheck-axis-plan-{digest[:16]}"
                with self.assertRaises(MODULE.ContractError):
                    MODULE.validate_axis_plan(value)

    def test_complete_ordered_plan_supports_only_bounded_saturation(self) -> None:
        plan = self.make_plan(
            [
                ("round-06", "failure_boundary", ["crossref"]),
                ("round-07", "independent_replication", ["semantic_scholar"]),
            ]
        )
        first_manifest = self.make_round(plan, 1)
        code, first = self.close(first_manifest, "closure-06.json")
        self.assertEqual(code, 0)
        second_manifest = self.make_round(plan, 2, previous_closure=first)
        code, second = self.close(second_manifest, "closure-07.json")
        self.assertEqual(code, 0)
        code, output = self.assess([first, second])
        self.assertEqual(code, 0)
        assessment = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(assessment["pragmatic_saturation"])
        self.assertEqual(assessment["claim_scope"], "bounded_countercheck_only")
        self.assertFalse(assessment["domain_completeness"])
        self.assertEqual(MODULE.main(["validate", "--input", str(output)]), 0)

    def test_previous_chain_prevents_omitting_a_reset_round(self) -> None:
        plan = self.make_plan(
            [
                ("round-first", "failure_boundary", ["crossref"]),
                ("round-reset", "identity_version_correction", ["semantic_scholar"]),
                (
                    "round-last",
                    "independent_replication",
                    ["crossref", "semantic_scholar"],
                ),
            ]
        )
        first_manifest = self.make_round(plan, 1)
        _, first = self.close(first_manifest, "closure-first.json")
        reset_manifest = self.make_round(
            plan, 2, previous_closure=first, review_status="accepted_evidence"
        )
        _, reset = self.close(reset_manifest, "closure-reset.json")
        last_manifest = self.make_round(plan, 3, previous_closure=reset)
        _, last = self.close(last_manifest, "closure-last.json")

        code, output = self.assess([first, reset, last], "reset-visible")
        self.assertEqual(code, 0)
        assessment = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(assessment["pragmatic_saturation"])
        self.assertEqual(assessment["latest_qualifying_streak_length"], 1)
        self.assertIn("round-reset", assessment["reset_round_ids"])

        code, output = self.assess([first, last], "reset-omitted")
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_replay_rejects_a_resealed_forged_summary(self) -> None:
        plan = self.make_plan(
            [
                ("round-forged", "counterexample", ["crossref"]),
                ("round-forged-next", "citation_neighborhood", ["semantic_scholar"]),
            ]
        )
        manifest = self.make_round(
            plan, 1, result_status="partial_provider", round_status="partial"
        )
        _, output = self.close(manifest, "partial-real.json")
        forged = json.loads(output.read_text(encoding="utf-8"))
        forged.pop("closure_id")
        forged.pop("closure_digest")
        forged["closure_status"] = "qualifying_no_add"
        forged["qualifying_no_add"] = True
        forged["provider_coverage_complete"] = True
        forged = MODULE._sealed_payload(forged, "countercheck-closure-")
        forged_path = self.write("forged-resealed.json", forged)
        self.assertEqual(MODULE.main(["validate", "--input", str(forged_path)]), 2)

    def test_umask_zero_still_creates_private_atomic_output(self) -> None:
        plan = self.make_plan(
            [
                ("round-mode", "benchmark_null_case", ["crossref"]),
                ("round-mode-next", "citation_neighborhood", ["semantic_scholar"]),
            ]
        )
        manifest = self.make_round(plan, 1)
        output = self.root / "private" / "nested" / "closure.json"
        previous = os.umask(0)
        try:
            code = MODULE.main(
                ["close-round", "--input", str(manifest), "--output", str(output)]
            )
        finally:
            os.umask(previous)
        self.assertEqual(code, 0)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(output.parent.parent.stat().st_mode), 0o700)

    def test_private_writer_cleans_temporary_for_all_base_exceptions(self) -> None:
        exception_types = (KeyboardInterrupt, SystemExit, SyntheticBaseException)
        for index, exception_type in enumerate(exception_types):
            with self.subTest(exception_type=exception_type.__name__):
                target = self.root / f"preserved-{index}.json"
                target.write_bytes(b"preserve-me\n")
                os.chmod(target, 0o600)
                with mock.patch.object(
                    MODULE.os,
                    "replace",
                    side_effect=exception_type("injected interruption"),
                ):
                    with self.assertRaises(exception_type):
                        MODULE.write_json(target, {"new": True})
                self.assertEqual(target.read_bytes(), b"preserve-me\n")
                self.assertEqual(
                    list(self.root.glob(f".preserved-{index}.json.*.tmp")), []
                )
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
