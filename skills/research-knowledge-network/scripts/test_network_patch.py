from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock


SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import network_patch as PATCH  # noqa: E402

KN = PATCH.kn


def invoke(module, argv: list[str]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = module.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def attach(value: dict, id_field: str, digest_field: str, prefix: str) -> dict:
    subject = {
        key: item
        for key, item in value.items()
        if key not in {id_field, digest_field}
    }
    digest = PATCH.digest_json(subject)
    value[digest_field] = digest
    value[id_field] = prefix + digest[:16]
    return value


class NetworkPatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.network_id = "patch-network"
        self._active_proposal = None
        self.gap_stub = mock.Mock()
        self.gap_stub.propose_patch.side_effect = (
            lambda *args, **kwargs: self._active_proposal
        )
        self.gap_patcher = mock.patch.object(
            PATCH, "load_gap_module", return_value=self.gap_stub
        )
        self.gap_patcher.start()
        snapshot = self.root / "corpus.json"
        snapshot.write_text('{"papers": []}', encoding="utf-8")
        code, _, error = self.kn(
            [
                "init",
                "--question",
                "Should a reviewed relation enter the network?",
                "--scope",
                "reviewed-only",
                "--snapshot-path",
                str(snapshot),
                "--snapshot-digest",
                KN._sha256_file(snapshot),
            ]
        )
        self.assertEqual(code, 0, error)
        code, _, error = self.kn(
            [
                "add-source",
                "--source-id",
                "source-01",
                "--canonical-identity",
                "doi:10.1000/example",
                "--canonical-version",
                "v1",
                "--read-version",
                "reviewed-v1",
                "--read-depth",
                "full",
                "--version-hash",
                "sha256:" + "a" * 64,
                "--role",
                "source",
            ]
        )
        self.assertEqual(code, 0, error)
        code, _, error = self.kn(
            [
                "add-claim",
                "--claim-id",
                "claim-01",
                "--claim-text",
                "Calibrated sparse dynamics recover the benchmark.",
                "--impact",
                "high",
            ]
        )
        self.assertEqual(code, 0, error)

    def tearDown(self):
        self.gap_patcher.stop()
        self.temp.cleanup()

    def kn(self, arguments: list[str]):
        return invoke(
            KN,
            ["--root", str(self.root), "--network-id", self.network_id, *arguments],
        )

    def patch(self, arguments: list[str]):
        return invoke(
            PATCH,
            ["--root", str(self.root), "--network-id", self.network_id, *arguments],
        )

    def current_ref(self) -> dict[str, str]:
        paths = KN._safe_paths(str(self.root), self.network_id)
        state, records = KN._load_state(paths)
        return PATCH.current_network_ref(paths, state, records)

    def basis(self, suffix: str) -> dict:
        value = {
            "review_request_id": f"review-request-{suffix}",
            "review_request_digest": "1" * 64,
            "report_set_id": "report-set-01",
            "report_set_digest": "2" * 64,
            "dossier_id": f"dossier-{suffix}",
            "dossier_digest": "3" * 64,
            "reading_report_id": f"reading-report-{suffix}",
            "reading_report_digest": "4" * 64,
            "source_bundle_id": f"source-bundle-{suffix}",
            "source_bundle_digest": "5" * 64,
            "source_artifact_sha256": "a" * 64,
            "source_id": "source-01",
            "source_digest": "6" * 64,
            "claim_id": "claim-01",
            "claim_digest": "7" * 64,
            "evidence_id": f"paper-evidence-{suffix}",
            "evidence_digest": "8" * 64,
            "span_id": f"span-{suffix}",
            "span_hash": "9" * 64,
            "source_ref": "paper.txt",
            "acquisition_locator": "https://doi.org/10.1000/example",
            "evidence_locator": "pages/page-0001.txt#char=12-48",
            "relation": "supports",
            "access_level": "full_text",
            "inspection_depth": "evidence",
            "claim_support_eligible": True,
            "projection_status": "decisive",
            "verification": {
                "mode": "independent_source_check",
                "verifier_id": "reviewer-02",
                "artifact_sha256": "b" * 64,
            },
        }
        return attach(value, "basis_id", "basis_digest", "network-patch-basis-")

    def action(self, action_type: str, hypothesis_id: str, suffix: str) -> dict:
        kind = action_type.removeprefix("propose_")
        signature = {
            "relation": "entity:A ? entity:C",
            "evidence": f"paper-evidence-{suffix}",
            "node": f"claim-node-{suffix}",
        }[kind]
        reviewed_evidence = [self.basis(suffix)]
        target_signature = {
            "target_kind": kind,
            "signature": signature,
        }
        value = {
            "action_type": action_type,
            "action_status": "blocked" if kind == "node" else "proposed",
            "hypothesis_id": hypothesis_id,
            "target_signature": target_signature,
            "hypothesis": f"Reviewed hypothesis {suffix}",
            "reviewed_evidence": reviewed_evidence,
        }
        if kind == "relation":
            basis = reviewed_evidence[0]
            scope = {
                "scope_statement": f"Reviewed report scope {suffix}",
                "assumptions": ["sparse governing dynamics"],
                "conditions": ["noise-controlled observations"],
                "units": ["dimensionless benchmark units"],
                "exclusions": ["fully observed dense systems"],
                "defeaters": ["non-identifiable reaction sets"],
                "coverage_dimensions": ["structural-identifiability"],
                "benchmark_profiles": ["sparse-dynamics-toy-model"],
            }
            target_claim = {
                "schema": "NetworkPatchTargetClaim/v1",
                "schema_version": "1.0",
                "claim_text": f"Reviewed scientific relation {suffix}",
                "entity_id": None,
                "impact": "high",
                "coverage_dimensions": scope["coverage_dimensions"],
                "benchmark_profiles": scope["benchmark_profiles"],
                "supersedes": None,
                "epistemic_status": {
                    "projection_status": basis["projection_status"],
                    "claim_support_eligible": basis["claim_support_eligible"],
                    "inspection_depth": basis["inspection_depth"],
                    "relation": basis["relation"],
                },
                "gap_hypothesis_id": hypothesis_id,
                "target_signature": target_signature,
                "report_claim_id": basis["claim_id"],
                "report_claim_digest": basis["claim_digest"],
                "scope": scope,
                "scope_digest": PATCH.digest_json(scope),
            }
            target_claim["target_claim_digest"] = PATCH.digest_json(target_claim)
            target_claim["claim_id"] = (
                "claim-target-" + target_claim["target_claim_digest"][:16]
            )
            value["target_claim"] = target_claim
        return attach(
            value, "action_id", "action_digest", "network-patch-action-"
        )

    def proposal(self) -> dict:
        value = {
            "schema": "NetworkPatchProposal/v2",
            "schema_version": "2.0",
            "network_ref": self.current_ref(),
            "request_ref": {
                "request_set_id": "request-set-01",
                "request_set_digest": "c" * 64,
                "review_request_set_id": "review-request-set-01",
                "review_request_set_digest": "d" * 64,
            },
            "generated_at": "2026-08-05T01:00:00Z",
            "proposal_only": True,
            "novelty_claimed": False,
            "review_gate": "pending_research_knowledge_network_acceptance",
            "actions": [
                self.action("propose_relation", "gap-relation", "1"),
                self.action("propose_node", "gap-node", "2"),
                self.action("propose_evidence", "gap-evidence", "3"),
            ],
        }
        return attach(
            value,
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )

    def operation(
        self, operation_type: str, payload: dict, basis_rows: list[dict]
    ) -> dict:
        return attach(
            {
                "operation_type": operation_type,
                "basis_refs": [
                    {
                        "basis_id": item["basis_id"],
                        "basis_digest": item["basis_digest"],
                    }
                    for item in basis_rows
                ],
                "payload": payload,
            },
            "operation_id",
            "operation_digest",
            "network-operation-",
        )

    def authority(self) -> dict:
        authority_artifact = self.root / "acceptance-review.json"
        authority_artifact.write_text(
            '{"decision":"approved-by-scientific-curator"}\n',
            encoding="utf-8",
        )
        value = {
            "basis_type": "expert_review",
            "source_ref": "acceptance-review.json",
            "locator": "decision:relation-1",
            "artifact_sha256": hashlib.sha256(
                authority_artifact.read_bytes()
            ).hexdigest(),
        }
        value["basis_id"] = (
            "patch-authority-basis-" + PATCH.digest_json(value)[:16]
        )
        return value

    def acceptance(self, proposal: dict, plan: dict) -> dict:
        authority = self.authority()
        action = proposal["actions"][0]
        relation_basis = action["reviewed_evidence"]
        target_claim = self.operation(
            "add-claim",
            {
                field: action["target_claim"][field]
                for field in (
                    "claim_id",
                    "claim_text",
                    "entity_id",
                    "impact",
                    "coverage_dimensions",
                    "benchmark_profiles",
                    "supersedes",
                )
            }
            | {
                "scope_statement": action["target_claim"]["scope"][
                    "scope_statement"
                ],
                **{
                    field: action["target_claim"]["scope"][field]
                    for field in (
                        "assumptions",
                        "conditions",
                        "units",
                        "exclusions",
                        "defeaters",
                    )
                },
            },
            relation_basis,
        )
        evidence = self.operation(
            "add-evidence",
            {
                "evidence_id": "paper-evidence-1",
                "claim_id": PATCH.target_claim_id(action),
                "source_id": "source-01",
                "polarity": "supports",
                "exact_locator": "pages/page-0001.txt#char=12-48",
                "independence_group": "source-01",
                "summary": action["hypothesis"],
                "notes": "accepted from NetworkPatchProposal/v2",
                "supersedes": None,
            },
            relation_basis,
        )
        relation = self.operation(
            "add-relation",
            {
                "relation_id": PATCH.relation_operation_id(
                    action, relation_basis[0]
                ),
                "relation_type": "supports",
                "from_ref": "claim:" + PATCH.target_claim_id(action),
                "to_ref": "evidence:paper-evidence-1",
                "notes": "network-patch-action:" + action["action_digest"],
                "supersedes": None,
            },
            relation_basis,
        )
        decisions = [
            {
                "action_id": proposal["actions"][0]["action_id"],
                "action_digest": proposal["actions"][0]["action_digest"],
                "decision": "accept",
                "rationale": "Independent evidence and typed mapping passed review.",
                "authority_basis_ids": [authority["basis_id"]],
                "operations": [target_claim, evidence, relation],
            },
            {
                "action_id": proposal["actions"][1]["action_id"],
                "action_digest": proposal["actions"][1]["action_digest"],
                "decision": "reject",
                "rationale": "The node duplicates an existing construct.",
                "authority_basis_ids": [authority["basis_id"]],
                "operations": [],
            },
            {
                "action_id": proposal["actions"][2]["action_id"],
                "action_digest": proposal["actions"][2]["action_digest"],
                "decision": "defer",
                "rationale": "A second independent source is still required.",
                "authority_basis_ids": [authority["basis_id"]],
                "operations": [],
            },
        ]
        value = {
            "schema": "NetworkPatchAcceptance/v1",
            "schema_version": "1.0",
            "network_ref": proposal["network_ref"],
            "proposal_ref": {
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal["proposal_digest"],
            },
            "plan_ref": {
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
            },
            "decided_at": "2026-08-05T02:00:00Z",
            "operator": {
                "operator_id": "review-board-01",
                "operator_role": "scientific-curator",
                "authority_basis": [authority],
            },
            "decisions": decisions,
        }
        return attach(
            value,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )

    def write(self, name: str, value: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return path

    def evidence_pack(self, proposal: dict) -> dict:
        artifact_root = self.root / "runtime-artifacts"
        artifact_root.mkdir(exist_ok=True)
        verification_root = self.root / "verification-root"
        verification_root.mkdir(exist_ok=True)
        attestation = verification_root / "independent.json"
        attestation.write_text('{"fixture": true}\n', encoding="utf-8")
        artifacts = {}
        for role in sorted(PATCH.EVIDENCE_PACK_FILE_ROLES):
            suffix = ".txt" if role == "source_artifact" else ".json"
            path = artifact_root / f"{role}{suffix}"
            content = "fixture source" if suffix == ".txt" else "{}"
            path.write_text(content, encoding="utf-8")
            artifacts[role] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        _, tree_digest = PATCH._verification_tree_digest(str(verification_root))
        value = {
            "schema": "NetworkPatchEvidencePack/v1",
            "schema_version": "1.0",
            "proposal_ref": {
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal.get("proposal_digest")
                or PATCH.digest_json(proposal),
            },
            "network_ref": proposal["network_ref"],
            "artifacts": artifacts,
            "verification_root": {
                "path": str(verification_root),
                "tree_sha256": tree_digest,
            },
        }
        self._active_proposal = proposal
        return attach(
            value,
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )

    def evidence_pack_from_artifacts(
        self,
        proposal: dict,
        artifact_paths: dict[str, Path],
        verification_root: Path,
    ) -> dict:
        artifacts = {
            role: {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for role, path in sorted(artifact_paths.items())
        }
        _, tree_digest = PATCH._verification_tree_digest(str(verification_root))
        return attach(
            {
                "schema": "NetworkPatchEvidencePack/v1",
                "schema_version": "1.0",
                "proposal_ref": {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                },
                "network_ref": proposal["network_ref"],
                "artifacts": artifacts,
                "verification_root": {
                    "path": str(verification_root.resolve()),
                    "tree_sha256": tree_digest,
                },
            },
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )

    def contracts(self):
        proposal = self.proposal()
        plan = PATCH.create_plan(
            proposal,
            proposal["network_ref"],
            prepared_at="2026-08-05T01:30:00Z",
        )
        return proposal, plan, self.acceptance(proposal, plan)

    def test_real_relation_apply_is_dry_runnable_atomic_and_audited(self):
        proposal, plan, acceptance = self.contracts()
        evidence_pack = self.evidence_pack(proposal)
        proposal_path = self.write("proposal.json", proposal)
        plan_path = self.write("plan.json", plan)
        acceptance_path = self.write("acceptance.json", acceptance)
        pack_path = self.write("evidence-pack.json", evidence_pack)
        before = self.current_ref()
        network_dir = self.root / KN.NETWORK_ROOT / self.network_id
        live_before = {
            path.name: (path.stat().st_ino, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in [network_dir / "network.json"]
            + [network_dir / f"{name}.jsonl" for name in KN.LEDGER_NAMES]
        }

        validated = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(validated[0], 0, validated[2])
        self.assertTrue(json.loads(validated[1])["apply_eligible"])

        prepared_path = self.root / "patch-plans" / "prepared-plan.json"
        prepared = self.patch(
            [
                "prepare-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--output",
                str(prepared_path),
            ]
        )
        self.assertEqual(prepared[0], 0, prepared[2])
        self.assertEqual(json.loads(prepared[1])["proposal_ref"], plan["proposal_ref"])

        dry = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
                "--dry-run",
            ]
        )
        self.assertEqual(dry[0], 0, dry[2])
        self.assertEqual(self.current_ref(), before)
        live_after_dry = {
            path.name: (path.stat().st_ino, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in [network_dir / "network.json"]
            + [network_dir / f"{name}.jsonl" for name in KN.LEDGER_NAMES]
        }
        self.assertEqual(live_after_dry, live_before)
        self.assertGreaterEqual(self.gap_stub.propose_patch.call_count, 3)

        applied = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        result = json.loads(applied[1])
        self.assertEqual(
            result["decision_counts"], {"accept": 1, "defer": 1, "reject": 1}
        )
        self.assertNotEqual(self.current_ref(), before)
        paths = KN._safe_paths(str(self.root), self.network_id)
        _, records = KN._load_state(paths)
        self.assertEqual(
            [item["evidence_id"] for item in records["evidence"]],
            ["paper-evidence-1"],
        )
        self.assertEqual(
            [item["relation_id"] for item in records["relations"]],
            [
                PATCH.relation_operation_id(
                    proposal["actions"][0],
                    proposal["actions"][0]["reviewed_evidence"][0],
                )
            ],
        )
        events = [
            item for item in records["events"] if item.get("event_type") == "patch_decision"
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(
            [item["decision"] for item in events[0]["decisions"]],
            ["accept", "reject", "defer"],
        )
        exported = self.kn(["export"])
        self.assertEqual(exported[0], 0, exported[2])
        patch_changes = [
            item
            for item in json.loads(exported[1])["change_history"]
            if item["action"] == "patch-decision"
        ]
        self.assertEqual(len(patch_changes), 1)
        self.assertTrue(
            all(item.startswith("authority:sha256:") for item in patch_changes[0]["basis_refs"])
        )
        self.assertNotIn("source:source-01", patch_changes[0]["basis_refs"])
        self.assertIn(proposal["actions"][0]["action_id"], patch_changes[0]["object_ids"])

        duplicate = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(duplicate[0], 1)
        self.assertIn("stale", duplicate[2])

    def test_tampering_noneligibility_unmapped_and_stale_fail_closed(self):
        proposal, plan, acceptance = self.contracts()
        evidence_pack = self.evidence_pack(proposal)
        tampered = json.loads(json.dumps(proposal))
        tampered["actions"][0]["hypothesis"] = "forged"
        with self.assertRaises(ValueError):
            PATCH.validate_proposal_v2(tampered, self.current_ref())

        noneligible = json.loads(json.dumps(proposal))
        basis = noneligible["actions"][0]["reviewed_evidence"][0]
        basis["verification"]["mode"] = "same_context_diagnostic"
        attach(basis, "basis_id", "basis_digest", "network-patch-basis-")
        attach(
            noneligible["actions"][0],
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        attach(
            noneligible,
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaises(ValueError):
            PATCH.validate_proposal_v2(noneligible, self.current_ref())

        unmapped = json.loads(json.dumps(acceptance))
        unmapped["decisions"][0]["operations"] = []
        attach(
            unmapped,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaises(ValueError):
            PATCH.validate_acceptance(unmapped, proposal, plan, self.current_ref())

        proposal_path = self.write("stale-proposal.json", proposal)
        plan_path = self.write("stale-plan.json", plan)
        acceptance_path = self.write("stale-acceptance.json", acceptance)
        pack_path = self.write("stale-pack.json", evidence_pack)
        changed = self.kn(
            [
                "add-entity",
                "--entity-id",
                "later-entity",
                "--entity-type",
                "method",
                "--name",
                "Later entity",
                "--description",
                "Makes the proposal snapshot stale",
            ]
        )
        self.assertEqual(changed[0], 0, changed[2])
        stale = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(stale[0], 1)
        self.assertIn("stale", stale[2])

    def test_evidence_pack_reopens_artifacts_and_rejects_missing_or_forged_chain(self):
        proposal, _, _ = self.contracts()
        forged = json.loads(json.dumps(proposal))
        basis = forged["actions"][0]["reviewed_evidence"][0]
        basis["source_id"] = "forged-source-not-in-network"
        basis["claim_id"] = "forged-claim-not-in-network"
        basis["verification"] = {
            "mode": "independent_source_check",
            "verifier_id": "proposal-self",
            "artifact_sha256": "f" * 64,
        }
        attach(basis, "basis_id", "basis_digest", "network-patch-basis-")
        attach(
            forged["actions"][0],
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        attach(
            forged,
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        pack = self.evidence_pack(forged)
        proposal_path = self.write("forged-proposal.json", forged)
        pack_path = self.write("forged-pack.json", pack)

        self.gap_patcher.stop()
        try:
            rejected = self.patch(
                [
                    "validate-patch",
                    "--proposal",
                    str(proposal_path),
                    "--evidence-pack",
                    str(pack_path),
                ]
            )
        finally:
            self.gap_patcher.start()
        self.assertEqual(rejected[0], 1)
        self.assertRegex(
            rejected[2],
            "strict upstream evidence reopening failed|does not bind a reviewed report claim",
        )

        missing = json.loads(json.dumps(pack))
        missing["artifacts"]["source_artifact"] = {
            "path": str(self.root / "does-not-exist.txt"),
            "sha256": "0" * 64,
        }
        attach(
            missing,
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )
        missing_path = self.write("missing-pack.json", missing)
        rejected_missing = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(missing_path),
            ]
        )
        self.assertEqual(rejected_missing[0], 1)
        self.assertRegex(
            rejected_missing[2],
            "unavailable|does not bind a reviewed report claim",
        )

    def test_evidence_pack_upstream_uses_private_stable_snapshot(self):
        proposal, _, _ = self.contracts()
        pack = self.evidence_pack(proposal)
        original_source = Path(pack["artifacts"]["source_artifact"]["path"])
        declared = pack["artifacts"]["source_artifact"]["sha256"]
        proposal_path = self.write("snapshot-proposal.json", proposal)
        pack_path = self.write("snapshot-pack.json", pack)
        observed_stage_paths = []

        def drift_original_then_return(*args, **kwargs):
            observed_stage_paths.append(Path(kwargs["source_artifact_path"]))
            original_source.write_text("concurrent drift", encoding="utf-8")
            return proposal

        self.gap_stub.propose_patch.side_effect = drift_original_then_return
        validated = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(validated[0], 1)
        self.assertIn("drifted during regeneration", validated[2])
        self.assertEqual(len(observed_stage_paths), 1)
        self.assertNotEqual(observed_stage_paths[0], original_source)
        self.assertNotEqual(
            hashlib.sha256(original_source.read_bytes()).hexdigest(), declared
        )
        self.gap_stub.propose_patch.side_effect = (
            lambda *args, **kwargs: self._active_proposal
        )

    def test_operation_smuggling_and_cross_basis_identity_are_rejected(self):
        proposal, plan, acceptance = self.contracts()
        basis = proposal["actions"][0]["reviewed_evidence"]
        smuggled = json.loads(json.dumps(acceptance))
        smuggled["decisions"][0]["operations"].append(
            self.operation(
                "add-claim",
                {
                    "claim_id": "unrelated-injected-claim",
                    "claim_text": "unrelated",
                    "entity_id": None,
                    "impact": "low",
                    "coverage_dimensions": [],
                    "benchmark_profiles": [],
                    "supersedes": None,
                },
                basis,
            )
        )
        attach(
            smuggled,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(
            ValueError,
            "does not match its basis|relation operation sequence|canonical semantic mapping|payload fields invalid",
        ):
            PATCH.validate_acceptance(
                smuggled, proposal, plan, self.current_ref()
            )

        crossed = json.loads(json.dumps(acceptance))
        evidence = crossed["decisions"][0]["operations"][0]
        evidence["payload"]["source_id"] = "source-foreign"
        attach(
            evidence,
            "operation_id",
            "operation_digest",
            "network-operation-",
        )
        attach(
            crossed,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(
            ValueError, "does not match its basis|payload fields invalid"
        ):
            PATCH.validate_acceptance(
                crossed, proposal, plan, self.current_ref()
            )

    def test_prepare_output_is_exclusive_confined_and_cannot_clobber_live_state(self):
        proposal, _, _ = self.contracts()
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("output-proposal.json", proposal)
        pack_path = self.write("output-pack.json", pack)
        network_state = (
            self.root / KN.NETWORK_ROOT / self.network_id / "network.json"
        )
        before = (
            network_state.stat().st_ino,
            hashlib.sha256(network_state.read_bytes()).hexdigest(),
        )
        common = [
            "prepare-patch",
            "--proposal",
            str(proposal_path),
            "--evidence-pack",
            str(pack_path),
            "--output",
        ]
        clobber = self.patch([*common, str(network_state)])
        self.assertEqual(clobber[0], 1)

        plan_root = self.root / "patch-plans"
        symlink = plan_root / "state-link.json"
        symlink.symlink_to(network_state)
        self.assertEqual(self.patch([*common, str(symlink)])[0], 1)
        hardlink = plan_root / "state-hardlink.json"
        os.link(network_state, hardlink)
        self.assertEqual(self.patch([*common, str(hardlink)])[0], 1)

        output = plan_root / "exclusive-plan.json"
        created = self.patch([*common, str(output)])
        self.assertEqual(created[0], 0, created[2])
        self.assertEqual(self.patch([*common, str(output)])[0], 1)
        after = (
            network_state.stat().st_ino,
            hashlib.sha256(network_state.read_bytes()).hexdigest(),
        )
        self.assertEqual(after, before)

    def test_reject_defer_only_advances_audit_snapshot_and_requires_rebase(self):
        proposal, plan, acceptance = self.contracts()
        acceptance["decisions"][0]["decision"] = "defer"
        acceptance["decisions"][0]["rationale"] = "Await another review."
        acceptance["decisions"][0]["operations"] = []
        attach(
            acceptance,
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("defer-proposal.json", proposal)
        plan_path = self.write("defer-plan.json", plan)
        acceptance_path = self.write("defer-acceptance.json", acceptance)
        pack_path = self.write("defer-pack.json", pack)
        paths = KN._safe_paths(str(self.root), self.network_id)
        _, before_records = KN._load_state(paths)
        scientific_before = {
            name: json.loads(json.dumps(before_records[name]))
            for name in ("sources", "entities", "claims", "evidence", "relations", "gaps")
        }
        before_ref = self.current_ref()
        applied = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        _, after_records = KN._load_state(paths)
        for name, rows in scientific_before.items():
            self.assertEqual(after_records[name], rows)
        self.assertNotEqual(self.current_ref(), before_ref)
        stale = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(stale[0], 1)
        self.assertIn("stale", stale[2])

    def test_patch_decision_event_is_closed_and_content_addressed(self):
        proposal, plan, acceptance = self.contracts()
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("event-proposal.json", proposal)
        plan_path = self.write("event-plan.json", plan)
        acceptance_path = self.write("event-acceptance.json", acceptance)
        pack_path = self.write("event-pack.json", pack)
        applied = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        events_path = (
            self.root / KN.NETWORK_ROOT / self.network_id / "events.jsonl"
        )
        original = events_path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in original.splitlines() if line]
        patch_event = next(
            item for item in rows if item.get("event_type") == "patch_decision"
        )
        patch_event["unknown_bypass"] = True
        events_path.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
            encoding="utf-8",
        )
        malformed = self.kn(["validate"])
        self.assertEqual(malformed[0], 1)
        self.assertIn("patch_decision fields invalid", malformed[1])

        rows = [json.loads(line) for line in original.splitlines() if line]
        patch_event = next(
            item for item in rows if item.get("event_type") == "patch_decision"
        )
        patch_event["decisions"][0]["action_digest"] = "0" * 64
        events_path.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
            encoding="utf-8",
        )
        tampered = self.kn(["validate"])
        self.assertEqual(tampered[0], 1)
        self.assertIn("event_digest mismatch", tampered[1])
        self.assertIn("action ID/digest mismatch", tampered[1])

    def test_apply_replace_failure_rolls_back_every_live_file(self):
        proposal, plan, acceptance = self.contracts()
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("rollback-proposal.json", proposal)
        plan_path = self.write("rollback-plan.json", plan)
        acceptance_path = self.write("rollback-acceptance.json", acceptance)
        pack_path = self.write("rollback-pack.json", pack)
        network_dir = self.root / KN.NETWORK_ROOT / self.network_id
        live_files = [network_dir / "network.json"] + [
            network_dir / f"{name}.jsonl" for name in KN.LEDGER_NAMES
        ]
        before = {path.name: path.read_bytes() for path in live_files}
        original_replace = os.replace
        call_count = 0

        def fail_after_first_live_replace(source, target):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise OSError("injected transaction replace failure")
            return original_replace(source, target)

        with mock.patch.object(
            KN.os, "replace", side_effect=fail_after_first_live_replace
        ):
            failed = self.patch(
                [
                    "apply-patch",
                    "--proposal",
                    str(proposal_path),
                    "--evidence-pack",
                    str(pack_path),
                    "--plan",
                    str(plan_path),
                    "--acceptance",
                    str(acceptance_path),
                ]
            )
        self.assertEqual(failed[0], 1)
        self.assertIn("injected transaction replace failure", failed[2])
        self.assertGreaterEqual(call_count, 4)
        after = {path.name: path.read_bytes() for path in live_files}
        self.assertEqual(after, before)
        self.assertFalse((network_dir / ".transaction.json").exists())
        validated = self.kn(["validate"])
        self.assertEqual(validated[0], 0, validated[2])

    def test_v1_is_audit_only_and_cannot_directly_apply(self):
        proposal = {
            "schema": "NetworkPatchProposal/v1",
            "proposal_id": "NPP-audit-only",
            "network_ref": self.current_ref(),
            "generated_at": "2026-08-05T00:30:00Z",
            "basis_gap_ids": [],
            "proposal_only": True,
            "novelty_claimed": False,
            "nodes": [],
            "relations": [],
            "evidence": [],
            "review_gate": "pending_research_knowledge_network_validation",
        }
        evidence_pack = self.evidence_pack(proposal)
        path = self.write("v1.json", proposal)
        pack_path = self.write("v1-pack.json", evidence_pack)
        validated = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(validated[0], 0, validated[2])
        self.assertFalse(json.loads(validated[1])["apply_eligible"])
        prepared = self.patch(
            [
                "prepare-patch",
                "--proposal",
                str(path),
                "--evidence-pack",
                str(pack_path),
                "--output",
                str(self.root / "patch-plans" / "v1-plan.json"),
            ]
        )
        self.assertEqual(prepared[0], 1)
        direct = self.patch(["apply-patch", "--proposal", str(path)])
        self.assertEqual(direct[0], 2)

    def test_relation_requires_lossless_target_claim_and_never_defaults_impact(self):
        proposal = self.proposal()
        relation = proposal["actions"][0]
        self.assertEqual(relation["target_claim"]["impact"], "high")
        self.assertNotEqual(
            relation["target_claim"]["claim_text"],
            relation["target_signature"]["signature"],
        )
        relation = PATCH.without(relation, "action_id", "action_digest")
        relation.pop("target_claim")
        proposal["actions"][0] = attach(
            relation, "action_id", "action_digest", "network-patch-action-"
        )
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        with self.assertRaisesRegex(ValueError, "target_claim"):
            PATCH.validate_proposal_v2(proposal, self.current_ref())

    def test_unmocked_real_producer_to_atomic_rkn_apply(self):
        self.gap_patcher.stop()
        real_gap = PATCH.load_gap_module()
        gap_test_path = (
            SCRIPT_DIR.parent.parent
            / "network-gap-discovery"
            / "scripts"
            / "test_network_gap_discovery.py"
        )
        sys.path.insert(0, str(gap_test_path.parent))
        spec = importlib.util.spec_from_file_location(
            "rkn_real_gap_test_support", gap_test_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        gap_support = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = gap_support
        spec.loader.exec_module(gap_support)

        source_text = (
            "The primary result proves it converges under the stated assumptions."
        )
        source_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        onboarded = self.kn(
            [
                "add-source",
                "--source-id",
                "SRC-1",
                "--canonical-identity",
                "url:https://example.org/fixture-paper",
                "--canonical-version",
                "reviewed-v1",
                "--read-version",
                "full-text-v1",
                "--read-depth",
                "full",
                "--version-hash",
                "sha256:" + source_sha,
                "--role",
                "source",
            ]
        )
        self.assertEqual(onboarded[0], 0, onboarded[2])
        for entity_id in ("entity-a", "entity-b", "entity-c"):
            created = self.kn(
                [
                    "add-entity",
                    "--entity-id",
                    entity_id,
                    "--entity-type",
                    "benchmark-construct",
                    "--name",
                    entity_id,
                    "--description",
                    f"Benchmark entity {entity_id}",
                ]
            )
            self.assertEqual(created[0], 0, created[2])
        ground_evidence = self.kn(
            [
                "add-evidence",
                "--evidence-id",
                "ground-evidence",
                "--claim-id",
                "claim-01",
                "--source-id",
                "source-01",
                "--polarity",
                "supports",
                "--exact-locator",
                "page=1",
                "--independence-group",
                "source-01",
                "--summary",
                "Reviewed grounding evidence",
            ]
        )
        self.assertEqual(ground_evidence[0], 0, ground_evidence[2])
        grounded = self.kn(
            [
                "add-relation",
                "--relation-id",
                "rel-ab",
                "--relation-type",
                "supports",
                "--from-ref",
                "claim:claim-01",
                "--to-ref",
                "evidence:ground-evidence",
                "--notes",
                "Reviewed A-B grounding relation",
            ]
        )
        self.assertEqual(grounded[0], 0, grounded[2])
        exported = self.kn(["export"])
        self.assertEqual(exported[0], 0, exported[2])
        live_network = json.loads(exported[1])

        hypotheses = gap_support.hypotheses_fixture(live_network)
        hypotheses["hypotheses"][0]["decision_impact"] = "low"
        hypotheses["hypotheses"][0]["grounds"][0]["ref_id"] = (
            "evidence:ground-evidence"
        )
        hypotheses["hypotheses"][0]["backing"][0]["locator"] = (
            "evidence:ground-evidence"
        )
        hypotheses["hypotheses"][0]["backing"][0]["ref_id"] = (
            "evidence:ground-evidence"
        )
        request_set = real_gap.emit_search_requests(hypotheses, live_network)
        request = request_set["requests"][0]
        discovered = real_gap.consume_results(
            hypotheses,
            live_network,
            request_set,
            [
                gap_support.make_result_set(
                    request_set,
                    request,
                    [gap_support.reviewed_candidate_fixture()],
                    request_digest=real_gap.sha256_json(request),
                )
            ],
        )
        review_set = discovered["review_requests"]
        review_request = review_set["requests"][0]
        artifact_root = self.root / "real-producer-chain"
        artifact_root.mkdir()
        verification_root = artifact_root / "verification"
        verification_root.mkdir()
        report_set, dossier, bundle_raw, source_raw = (
            gap_support.real_producer_projection(
                artifact_root,
                review_set,
                review_request,
                live_network,
                verification_root=verification_root,
            )
        )
        bundle_path = Path(bundle_raw)
        source_path = Path(source_raw)
        self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), source_sha)
        reviewed = real_gap.consume_reviewed_evidence(
            discovered,
            live_network,
            review_set,
            report_set,
            dossier,
            source_bundle_path=bundle_path,
            source_artifact_path=source_path,
            verification_root=verification_root,
        )
        proposal = real_gap.propose_patch(
            reviewed,
            live_network,
            review_set,
            report_set,
            dossier,
            source_bundle_path=bundle_path,
            source_artifact_path=source_path,
            verification_root=verification_root,
        )
        self.assertEqual(proposal["schema"], "NetworkPatchProposal/v2")
        self.assertEqual(len(proposal["actions"]), 1)
        mixed_proposal = json.loads(json.dumps(proposal))
        for kind in ("assumption", "boundary"):
            blocked_action = json.loads(json.dumps(proposal["actions"][0]))
            blocked_action.pop("target_claim")
            blocked_action.update(
                {
                    "action_type": "propose_evidence",
                    "action_status": "blocked",
                    "hypothesis_id": f"KGH-BLOCKED-{kind}",
                    "target_signature": {
                        "target_kind": kind,
                        "signature": f"{kind}:reviewed-boundary",
                    },
                    "hypothesis": f"Reviewed {kind} requires a future typed adapter.",
                }
            )
            mixed_proposal["actions"].append(blocked_action)
        gap_support.rehash_patch_v2(mixed_proposal)
        real_gap.validate_patch_v2(mixed_proposal, live_network)
        PATCH.validate_proposal_v2(mixed_proposal, self.current_ref())
        mixed_plan = PATCH.create_plan(
            mixed_proposal,
            self.current_ref(),
            prepared_at="2026-08-05T03:30:00Z",
        )
        self.assertEqual(
            [item["action_status"] for item in mixed_plan["actions"]],
            ["pending_acceptance", "blocked", "blocked"],
        )
        self.assertEqual(mixed_plan["actions"][1]["allowed_operation_types"], [])
        self.assertEqual(mixed_plan["actions"][2]["allowed_operation_types"], [])

        artifact_paths = {
            "hypotheses": self.write("real-reviewed-hypotheses.json", reviewed),
            "review_requests": self.write("real-review-requests.json", review_set),
            "reading_reports": self.write("real-reading-reports.json", report_set),
            "dossier": self.write("real-dossier.json", dossier),
            "source_bundle": bundle_path,
            "source_artifact": source_path,
        }
        evidence_pack = self.evidence_pack_from_artifacts(
            proposal, artifact_paths, verification_root
        )
        proposal_path = self.write("real-proposal.json", proposal)
        pack_path = self.write("real-evidence-pack.json", evidence_pack)

        validated = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(validated[0], 0, validated[2])

        tampered_path = artifact_paths["hypotheses"]
        original_reviewed = tampered_path.read_bytes()
        tampered_path.write_text('{"tampered":true}', encoding="utf-8")
        tampered = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
            ]
        )
        self.assertEqual(tampered[0], 1)
        self.assertIn("sha256 mismatch", tampered[2])
        tampered_path.write_bytes(original_reviewed)

        unonboarded_proposal = json.loads(json.dumps(proposal))
        unonboarded_proposal["actions"][0]["reviewed_evidence"][0][
            "source_id"
        ] = "SRC-NOT-ONBOARDED"
        gap_support.rehash_patch_v2(unonboarded_proposal)
        unonboarded_pack = json.loads(json.dumps(evidence_pack))
        unonboarded_pack["proposal_ref"] = {
            "proposal_id": unonboarded_proposal["proposal_id"],
            "proposal_digest": unonboarded_proposal["proposal_digest"],
        }
        unonboarded_pack = attach(
            PATCH.without(unonboarded_pack, "pack_id", "pack_digest"),
            "pack_id",
            "pack_digest",
            "network-patch-evidence-pack-",
        )
        unonboarded_proposal_path = self.write(
            "real-unonboarded-proposal.json", unonboarded_proposal
        )
        unonboarded_pack_path = self.write(
            "real-unonboarded-pack.json", unonboarded_pack
        )
        unonboarded = self.patch(
            [
                "validate-patch",
                "--proposal",
                str(unonboarded_proposal_path),
                "--evidence-pack",
                str(unonboarded_pack_path),
            ]
        )
        self.assertEqual(unonboarded[0], 1)
        self.assertIn("source onboarding required", unonboarded[2])

        plan_path = self.root / "patch-plans" / "real-plan.json"
        prepared = self.patch(
            [
                "prepare-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--output",
                str(plan_path),
            ]
        )
        self.assertEqual(prepared[0], 0, prepared[2])
        plan = json.loads(prepared[1])
        action = proposal["actions"][0]
        basis_rows = action["reviewed_evidence"]
        basis = basis_rows[0]
        target = action["target_claim"]
        claim_operation = self.operation(
            "add-claim",
            {
                field: target[field]
                for field in (
                    "claim_id",
                    "claim_text",
                    "entity_id",
                    "impact",
                    "coverage_dimensions",
                    "benchmark_profiles",
                    "supersedes",
                )
            }
            | {
                "scope_statement": target["scope"]["scope_statement"],
                **{
                    field: target["scope"][field]
                    for field in (
                        "assumptions",
                        "conditions",
                        "units",
                        "exclusions",
                        "defeaters",
                    )
                },
            },
            basis_rows,
        )
        evidence_operation = self.operation(
            "add-evidence",
            {
                "evidence_id": basis["evidence_id"],
                "claim_id": target["claim_id"],
                "source_id": basis["source_id"],
                "polarity": "supports",
                "exact_locator": basis["evidence_locator"],
                "independence_group": basis["source_id"],
                "summary": action["hypothesis"],
                "notes": "accepted from NetworkPatchProposal/v2",
                "supersedes": None,
            },
            basis_rows,
        )
        relation_id = PATCH.relation_operation_id(action, basis)
        relation_operation = self.operation(
            "add-relation",
            {
                "relation_id": relation_id,
                "relation_type": "supports",
                "from_ref": "claim:" + target["claim_id"],
                "to_ref": "evidence:" + basis["evidence_id"],
                "notes": "network-patch-action:" + action["action_digest"],
                "supersedes": None,
            },
            basis_rows,
        )
        authority = self.authority()
        mixed_acceptance = attach(
            {
                "schema": "NetworkPatchAcceptance/v1",
                "schema_version": "1.0",
                "network_ref": mixed_proposal["network_ref"],
                "proposal_ref": {
                    "proposal_id": mixed_proposal["proposal_id"],
                    "proposal_digest": mixed_proposal["proposal_digest"],
                },
                "plan_ref": {
                    "plan_id": mixed_plan["plan_id"],
                    "plan_digest": mixed_plan["plan_digest"],
                },
                "decided_at": "2026-08-05T03:45:00Z",
                "operator": {
                    "operator_id": "external-governance-board",
                    "operator_role": "scientific-curator",
                    "authority_basis": [authority],
                },
                "decisions": [
                    {
                        "action_id": mixed_proposal["actions"][0]["action_id"],
                        "action_digest": mixed_proposal["actions"][0][
                            "action_digest"
                        ],
                        "decision": "accept",
                        "rationale": "Accept only the lossless relation mapping.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": [
                            claim_operation,
                            evidence_operation,
                            relation_operation,
                        ],
                    },
                    {
                        "action_id": mixed_proposal["actions"][1]["action_id"],
                        "action_digest": mixed_proposal["actions"][1][
                            "action_digest"
                        ],
                        "decision": "reject",
                        "rationale": "No lossless assumption adapter exists.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": [],
                    },
                    {
                        "action_id": mixed_proposal["actions"][2]["action_id"],
                        "action_digest": mixed_proposal["actions"][2][
                            "action_digest"
                        ],
                        "decision": "defer",
                        "rationale": "Boundary materialization remains blocked.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": [],
                    },
                ],
            },
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        PATCH.validate_acceptance(
            mixed_acceptance, mixed_proposal, mixed_plan, self.current_ref()
        )
        blocked_acceptance = json.loads(json.dumps(mixed_acceptance))
        blocked_acceptance["decisions"][1].update(
            {
                "decision": "accept",
                "rationale": "Attempt to bypass the blocked operation gate.",
                "operations": [evidence_operation],
            }
        )
        blocked_acceptance = attach(
            PATCH.without(
                blocked_acceptance, "acceptance_id", "acceptance_digest"
            ),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(ValueError, "blocked action cannot be accepted"):
            PATCH.validate_acceptance(
                blocked_acceptance,
                mixed_proposal,
                mixed_plan,
                self.current_ref(),
            )
        acceptance = attach(
            {
                "schema": "NetworkPatchAcceptance/v1",
                "schema_version": "1.0",
                "network_ref": proposal["network_ref"],
                "proposal_ref": {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                },
                "plan_ref": {
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                },
                "decided_at": "2026-08-05T04:00:00Z",
                "operator": {
                    "operator_id": "external-governance-board",
                    "operator_role": "scientific-curator",
                    "authority_basis": [authority],
                },
                "decisions": [
                    {
                        "action_id": action["action_id"],
                        "action_digest": action["action_digest"],
                        "decision": "accept",
                        "rationale": "External review accepted the exact typed projection.",
                        "authority_basis_ids": [authority["basis_id"]],
                        "operations": [
                            claim_operation,
                            evidence_operation,
                            relation_operation,
                        ],
                    }
                ],
            },
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        acceptance_path = self.write("real-acceptance.json", acceptance)
        before_apply = self.current_ref()
        dry_run = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
                "--dry-run",
            ]
        )
        self.assertEqual(dry_run[0], 0, dry_run[2])
        self.assertEqual(self.current_ref(), before_apply)
        applied = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(applied[0], 0, applied[2])
        core_valid = self.kn(["validate"])
        self.assertEqual(core_valid[0], 0, core_valid[2])

        paths = KN._safe_paths(str(self.root), self.network_id)
        _, records = KN._load_state(paths)
        claim = next(
            item for item in records["claims"] if item["claim_id"] == target["claim_id"]
        )
        for field in (
            "claim_text",
            "entity_id",
            "impact",
            "coverage_dimensions",
            "benchmark_profiles",
            "supersedes",
        ):
            self.assertEqual(claim[field], target[field])
        self.assertEqual(claim["scope_statement"], target["scope"]["scope_statement"])
        for field in (
            "assumptions",
            "conditions",
            "units",
            "exclusions",
            "defeaters",
        ):
            self.assertEqual(claim[field], target["scope"][field])
        post_apply_export = self.kn(["export"])
        self.assertEqual(post_apply_export[0], 0, post_apply_export[2])
        exported_claim = next(
            item
            for item in json.loads(post_apply_export[1])["claims"]
            if item["claim_id"] == target["claim_id"]
        )
        for field in (
            "scope_statement",
            "assumptions",
            "conditions",
            "units",
            "exclusions",
            "defeaters",
        ):
            self.assertEqual(exported_claim[field], claim[field])
        evidence = next(
            item
            for item in records["evidence"]
            if item["evidence_id"] == basis["evidence_id"]
        )
        self.assertEqual(evidence["claim_id"], target["claim_id"])
        self.assertEqual(evidence["source_id"], basis["source_id"])
        self.assertEqual(evidence["exact_locator"], basis["evidence_locator"])
        self.assertEqual(evidence["polarity"], "supports")
        self.assertEqual(evidence["supersedes"], None)
        relation = next(
            item for item in records["relations"] if item["relation_id"] == relation_id
        )
        self.assertEqual(relation["relation_type"], "supports")
        self.assertEqual(relation["from"], "claim:" + target["claim_id"])
        self.assertEqual(relation["to"], "evidence:" + basis["evidence_id"])

        stale = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(stale[0], 1)
        self.assertIn("stale", stale[2])

    def test_evidence_projection_cannot_supersede_active_evidence_on_real_apply(self):
        seeded = self.kn(
            [
                "add-evidence",
                "--evidence-id",
                "old-evidence",
                "--claim-id",
                "claim-01",
                "--source-id",
                "source-01",
                "--polarity",
                "supports",
                "--exact-locator",
                "page=1",
                "--independence-group",
                "source-01",
                "--summary",
                "Previously reviewed evidence",
            ]
        )
        self.assertEqual(seeded[0], 0, seeded[2])
        before = self.current_ref()
        proposal, plan, acceptance = self.contracts()
        action = proposal["actions"][0]
        evidence_operation = acceptance["decisions"][0]["operations"][1]
        malicious_payload = dict(evidence_operation["payload"])
        malicious_payload["supersedes"] = "evidence:old-evidence"
        acceptance["decisions"][0]["operations"][1] = self.operation(
            "add-evidence", malicious_payload, action["reviewed_evidence"]
        )
        acceptance = attach(
            PATCH.without(acceptance, "acceptance_id", "acceptance_digest"),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        pack = self.evidence_pack(proposal)
        proposal_path = self.write("supersede-proposal.json", proposal)
        plan_path = self.write("supersede-plan.json", plan)
        acceptance_path = self.write("supersede-acceptance.json", acceptance)
        pack_path = self.write("supersede-pack.json", pack)

        rejected = self.patch(
            [
                "apply-patch",
                "--proposal",
                str(proposal_path),
                "--evidence-pack",
                str(pack_path),
                "--plan",
                str(plan_path),
                "--acceptance",
                str(acceptance_path),
            ]
        )
        self.assertEqual(rejected[0], 1)
        self.assertIn("supersedes must be null", rejected[2])
        self.assertEqual(self.current_ref(), before)
        exported = self.kn(["export"])
        self.assertEqual(exported[0], 0, exported[2])
        self.assertEqual(
            [item["evidence_id"] for item in json.loads(exported[1])["evidence"]],
            ["old-evidence"],
        )

    def test_evidence_projection_rejects_any_noncanonical_closed_field(self):
        proposal, plan, acceptance = self.contracts()
        action = proposal["actions"][0]
        canonical = acceptance["decisions"][0]["operations"][1]
        mutations = {
            "polarity": "qualifies",
            "notes": "operator supplied note",
            "summary": "different scientific statement",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                candidate = json.loads(json.dumps(acceptance))
                payload = dict(canonical["payload"])
                payload[field] = value
                candidate["decisions"][0]["operations"][1] = self.operation(
                    "add-evidence", payload, action["reviewed_evidence"]
                )
                candidate = attach(
                    PATCH.without(candidate, "acceptance_id", "acceptance_digest"),
                    "acceptance_id",
                    "acceptance_digest",
                    "network-patch-acceptance-",
                )
                with self.assertRaisesRegex(ValueError, "exact reviewed projection"):
                    PATCH.validate_acceptance(
                        candidate, proposal, plan, self.current_ref()
                    )

    def test_propose_node_acceptance_is_fail_closed_without_target_node(self):
        proposal, plan, acceptance = self.contracts()
        self.assertEqual(plan["actions"][1]["allowed_operation_types"], [])
        node_action = proposal["actions"][1]
        malicious_claim = self.operation(
            "add-claim",
            {
                "claim_id": node_action["target_signature"]["signature"],
                "claim_text": node_action["hypothesis"],
                "entity_id": "entity:injected",
                "impact": "high",
                "coverage_dimensions": ["injected-dimension"],
                "benchmark_profiles": ["injected-profile"],
                "supersedes": "claim:claim-01",
            },
            node_action["reviewed_evidence"],
        )
        acceptance["decisions"][1].update(
            {
                "decision": "accept",
                "rationale": "Attempt an unconstrained node projection.",
                "operations": [malicious_claim],
            }
        )
        acceptance = attach(
            PATCH.without(acceptance, "acceptance_id", "acceptance_digest"),
            "acceptance_id",
            "acceptance_digest",
            "network-patch-acceptance-",
        )
        with self.assertRaisesRegex(ValueError, "blocked action cannot be accepted"):
            PATCH.validate_acceptance(
                acceptance, proposal, plan, self.current_ref()
            )

    def test_every_evidence_pack_artifact_and_verification_tree_rejects_drift(self):
        proposal, _, _ = self.contracts()
        pack = self.evidence_pack(proposal)
        paths = KN._safe_paths(self.root, self.network_id)
        state, records, network_ref = PATCH.validate_live_network(paths)
        live_network = KN._knowledge_network_export(paths, state, records)

        for role, reference in sorted(pack["artifacts"].items()):
            with self.subTest(role=role):
                artifact = Path(reference["path"])
                original = artifact.read_bytes()
                artifact.write_bytes(
                    original + b"\nconcurrent-drift"
                    if role == "source_artifact"
                    else b'{"concurrent_drift":true}'
                )
                try:
                    with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                        PATCH.validate_evidence_pack(
                            pack,
                            proposal,
                            network_ref,
                            live_network=live_network,
                        )
                finally:
                    artifact.write_bytes(original)

        verification_root = Path(pack["verification_root"]["path"])
        verification_artifact = next(
            path for path in verification_root.rglob("*") if path.is_file()
        )
        original = verification_artifact.read_bytes()
        verification_artifact.write_bytes(original + b"\nconcurrent-drift")
        try:
            with self.assertRaisesRegex(ValueError, "tree digest mismatch"):
                PATCH.validate_evidence_pack(
                    pack,
                    proposal,
                    network_ref,
                    live_network=live_network,
                )
        finally:
            verification_artifact.write_bytes(original)

    def test_source_independence_is_lineage_not_verifier_identity(self):
        first = self.basis("source-a")
        same_source_second_verifier = self.basis("source-b")
        same_source_second_verifier["source_id"] = first["source_id"]
        same_source_second_verifier["verification"]["verifier_id"] = "reviewer-99"
        self.assertEqual(
            PATCH.source_independence_group(first),
            PATCH.source_independence_group(same_source_second_verifier),
        )

        second_source_same_verifier = self.basis("source-c")
        second_source_same_verifier["source_id"] = "source-02"
        second_source_same_verifier["verification"]["verifier_id"] = first[
            "verification"
        ]["verifier_id"]
        self.assertNotEqual(
            PATCH.source_independence_group(first),
            PATCH.source_independence_group(second_source_same_verifier),
        )

    def test_unonboarded_basis_source_fails_before_patch_preparation(self):
        proposal = self.proposal()
        relation = proposal["actions"][0]
        basis = PATCH.without(
            relation["reviewed_evidence"][0], "basis_id", "basis_digest"
        )
        basis["source_id"] = "source-not-onboarded"
        basis = attach(
            basis, "basis_id", "basis_digest", "network-patch-basis-"
        )
        relation["reviewed_evidence"] = [basis]
        relation = attach(
            PATCH.without(relation, "action_id", "action_digest"),
            "action_id",
            "action_digest",
            "network-patch-action-",
        )
        proposal["actions"][0] = relation
        proposal = attach(
            PATCH.without(proposal, "proposal_id", "proposal_digest"),
            "proposal_id",
            "proposal_digest",
            "network-patch-proposal-",
        )
        proposal = PATCH.validate_proposal_v2(proposal, self.current_ref())
        paths = KN._safe_paths(self.root, self.network_id)
        state, records, _ = PATCH.validate_live_network(paths)
        live_network = KN._knowledge_network_export(paths, state, records)
        with self.assertRaisesRegex(ValueError, "source onboarding required"):
            PATCH.require_onboarded_sources(proposal, live_network)


if __name__ == "__main__":
    unittest.main()
