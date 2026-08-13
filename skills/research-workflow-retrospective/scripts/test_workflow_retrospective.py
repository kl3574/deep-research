from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "workflow_retrospective_under_test", HERE / "workflow_retrospective.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WorkflowRetrospectiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run = self.root / "run.json"
        self.audit_a = self.root / "binding-error.json"
        self.audit_b = self.root / "browser-error.json"
        self.run.write_text('{"schema":"SyntheticRun/v1"}\n', encoding="utf-8")
        self.audit_a.write_text(
            '{"error":"locator source mismatch","stage":"binding"}\n',
            encoding="utf-8",
        )
        self.audit_b.write_text(
            '{"error":"favicon 404","stage":"browser_review"}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ref(self, path: Path) -> dict[str, str]:
        return {"path": str(path), "sha256": sha(path)}

    def incident(
        self,
        *,
        key: str = "locator-source-alignment",
        owner: str = "evidence-appraisal",
        classification: str = "contract_seam",
        detected: str = "binding",
        earliest: str = "appraisal_prepare",
        evidence: Path | None = None,
        seam: str = "EvidenceLocatorRef/v1",
        one_off: bool = False,
        reproducibility: str = "reproduced",
        acceptance_tests: list[str] | None = None,
        negative_tests: list[str] | None = None,
    ) -> dict:
        return {
            "incident_key": key,
            "title": "Cross-owner locator alignment failed",
            "observation": "The binder rejected the appraisal locator source reference.",
            "impact": "high",
            "recurrence": "repeated",
            "classification": classification,
            "owner_skill": owner,
            "detected_stage": detected,
            "earliest_detectable_stage": earliest,
            "reproducibility": reproducibility,
            "one_off": one_off,
            "evidence_refs": [self.ref(evidence or self.audit_a)],
            "proposed_change": {
                "kind": "shared_contract",
                "target": "Cross-owner exact locator identity",
                "seam": seam,
                "acceptance_tests": acceptance_tests
                if acceptance_tests is not None
                else ["Owner output crosses the seam unchanged"],
                "negative_tests": negative_tests
                if negative_tests is not None
                else ["Same basename with another hash is rejected"],
                "non_goals": ["Do not weaken owner replay"],
            },
        }

    def bundle(self) -> dict:
        return {
            "schema": "ResearchWorkflowEvidenceBundle/v1",
            "run_id": "run-01",
            "as_of": "2026-08-13T12:00:00Z",
            "scope": "Review representation escapes in one completed run.",
            "stage_order": [
                "alignment",
                "appraisal_prepare",
                "binding",
                "publication",
                "browser_review",
            ],
            "run_ref": self.ref(self.run),
            "incidents": [self.incident()],
            "external_design_refs": [
                {
                    "title": "Multi-agent research system",
                    "url": "https://www.anthropic.com/engineering/multi-agent-research-system",
                    "retrieved_at": "2026-08-13",
                    "evidence_level": "official_engineering",
                    "claim": "Parallel workers help independent breadth-first branches.",
                    "use": "Require an explicit parallelism decision instead of agent count.",
                }
            ],
        }

    def write_bundle(self, value: dict | None = None, name: str = "bundle.json") -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(value or self.bundle(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def build(self, bundle: Path | None = None) -> dict:
        bundle = bundle or self.write_bundle()
        return MODULE.review_bundle(bundle, sha(bundle))

    def write_review(self, review: dict, name: str = "review.json") -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(review, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_build_is_deterministic_and_compartments_private_paths(self) -> None:
        bundle = self.write_bundle()
        first = MODULE.review_bundle(bundle, sha(bundle))
        second = MODULE.review_bundle(bundle, sha(bundle))
        self.assertEqual(first, second)
        self.assertEqual(first["summary"]["finding_count"], 1)
        self.assertEqual(first["findings"][0]["priority"], "P0")
        self.assertEqual(first["findings"][0]["implementation_readiness"], "ready")
        public_projection = {key: value for key, value in first.items() if key != "private"}
        self.assertNotIn(str(self.root), json.dumps(public_projection, ensure_ascii=False))
        self.assertEqual(first["private"]["bundle_ref"]["path"], str(bundle))
        self.assertEqual(first["private"]["run_ref"]["path"], str(self.run))
        self.assertEqual(
            first["private"]["evidence_refs"]["locator-source-alignment"][0]["path"],
            str(self.audit_a),
        )

    def test_validate_replays_bundle_and_review_with_external_pins(self) -> None:
        bundle = self.write_bundle()
        review_path = self.write_review(MODULE.review_bundle(bundle, sha(bundle)))
        validated = MODULE.validate_review(
            review_path, bundle, sha(bundle), sha(review_path)
        )
        self.assertEqual(validated["schema"], "ResearchWorkflowReview/v1")

    def test_bundle_external_pin_is_required(self) -> None:
        bundle = self.write_bundle()
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "external pin"):
            MODULE.review_bundle(bundle, "f" * 64)

    def test_review_external_pin_and_replay_are_required(self) -> None:
        bundle = self.write_bundle()
        review_path = self.write_review(MODULE.review_bundle(bundle, sha(bundle)))
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "external pin"):
            MODULE.validate_review(review_path, bundle, sha(bundle), "f" * 64)

        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["scope"] = "Self-resealed drift"
        body = copy.deepcopy(review)
        body.pop("review_id")
        body.pop("review_digest")
        digest = hashlib.sha256(MODULE._canonical_bytes(body)).hexdigest()
        review["review_id"] = f"research-workflow-review-{digest[:16]}"
        review["review_digest"] = digest
        drift_path = self.write_review(review, "drift.json")
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "replayed bundle"):
            MODULE.validate_review(drift_path, bundle, sha(bundle), sha(drift_path))

    def test_evidence_drift_fails_closed(self) -> None:
        bundle = self.write_bundle()
        self.audit_a.write_text('{"error":"changed"}\n', encoding="utf-8")
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "raw SHA-256 mismatch"):
            MODULE.review_bundle(bundle, sha(bundle))

    def test_moved_bundle_requires_fresh_review(self) -> None:
        bundle = self.write_bundle()
        review_path = self.write_review(MODULE.review_bundle(bundle, sha(bundle)))
        moved = self.root / "moved-bundle.json"
        moved.write_bytes(bundle.read_bytes())
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "replayed bundle"):
            MODULE.validate_review(
                review_path, moved, sha(moved), sha(review_path)
            )

    def test_moved_evidence_requires_fresh_review(self) -> None:
        bundle = self.write_bundle()
        review_path = self.write_review(MODULE.review_bundle(bundle, sha(bundle)))
        moved = self.root / "moved-evidence.json"
        moved.write_bytes(self.audit_a.read_bytes())
        value = json.loads(bundle.read_text(encoding="utf-8"))
        value["incidents"][0]["evidence_refs"][0]["path"] = str(moved)
        moved_bundle = self.write_bundle(value, "bundle-moved-evidence.json")
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "replayed bundle"):
            MODULE.validate_review(
                review_path,
                moved_bundle,
                sha(moved_bundle),
                sha(review_path),
            )

    def test_stage_order_rejects_impossible_earliest_detection(self) -> None:
        value = self.bundle()
        value["incidents"][0]["earliest_detectable_stage"] = "publication"
        bundle = self.write_bundle(value)
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "must not follow"):
            MODULE.review_bundle(bundle, sha(bundle))

    def test_duplicate_seam_is_rejected(self) -> None:
        value = self.bundle()
        second = copy.deepcopy(value["incidents"][0])
        second["incident_key"] = "same-seam-second-symptom"
        second["evidence_refs"] = [self.ref(self.audit_b)]
        value["incidents"].append(second)
        bundle = self.write_bundle(value)
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "duplicate owner"):
            MODULE.review_bundle(bundle, sha(bundle))

    def test_evidence_identity_is_path_and_hash_not_hash_alone(self) -> None:
        replay = self.root / "binding-error-replay.json"
        replay.write_bytes(self.audit_a.read_bytes())
        value = self.bundle()
        value["incidents"][0]["evidence_refs"] = [
            self.ref(self.audit_a),
            self.ref(replay),
        ]
        bundle = self.write_bundle(value)
        finding = self.build(bundle)["findings"][0]
        self.assertEqual(finding["evidence_sha256"], [sha(self.audit_a)] * 2)

        value["incidents"][0]["evidence_refs"].append(self.ref(replay))
        duplicate_bundle = self.write_bundle(value, "duplicate-evidence.json")
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "duplicates"):
            MODULE.review_bundle(duplicate_bundle, sha(duplicate_bundle))

    def test_no_change_readiness_is_explicit(self) -> None:
        value = self.bundle()
        value["incidents"][0]["proposed_change"]["kind"] = "no_change"
        bundle = self.write_bundle(value)
        self.assertEqual(
            self.build(bundle)["findings"][0]["implementation_readiness"],
            "no_change",
        )

    def test_one_off_and_missing_tests_are_not_implementation_ready(self) -> None:
        value = self.bundle()
        value["incidents"] = [
            self.incident(
                key="browser-disconnected",
                owner="research-presentation-audit",
                classification="one_off_environment",
                detected="browser_review",
                earliest="browser_review",
                evidence=self.audit_b,
                seam="browser-capability-probe",
                one_off=True,
            ),
            self.incident(
                key="unreproduced-resume",
                owner="deep-research",
                classification="workflow_state",
                detected="publication",
                earliest="alignment",
                seam="ResearchResume/v1",
                reproducibility="not_reproduced",
            ),
        ]
        bundle = self.write_bundle(value)
        findings = {item["incident_key"]: item for item in self.build(bundle)["findings"]}
        self.assertEqual(
            findings["browser-disconnected"]["implementation_readiness"],
            "one_off_local",
        )
        self.assertEqual(
            findings["unreproduced-resume"]["implementation_readiness"],
            "needs_reproduction",
        )

    def test_unknown_keys_and_credentials_are_rejected(self) -> None:
        unknown = self.bundle()
        unknown["unexpected"] = True
        bundle = self.write_bundle(unknown)
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "keys differ"):
            MODULE.review_bundle(bundle, sha(bundle))

        credential = self.bundle()
        credential["external_design_refs"][0]["claim"] = "Bearer abcdefghijklmnop"
        bundle = self.write_bundle(credential, "credential.json")
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "credential-shaped"):
            MODULE.review_bundle(bundle, sha(bundle))

        for index, secret_text in enumerate(
            (
                "api_key=not-a-real-secret-value",
                "password: not-a-real-password",
                "https://example-user:not-a-real-password@example.invalid/path",
            )
        ):
            credential = self.bundle()
            credential["external_design_refs"][0]["claim"] = secret_text
            bundle = self.write_bundle(credential, f"credential-value-{index}.json")
            with self.assertRaisesRegex(
                MODULE.RetrospectiveError, "credential-shaped"
            ):
                MODULE.review_bundle(bundle, sha(bundle))

    def test_symlink_evidence_is_rejected(self) -> None:
        link = self.root / "audit-link.json"
        link.symlink_to(self.audit_a)
        value = self.bundle()
        value["incidents"][0]["evidence_refs"] = [
            {"path": str(link), "sha256": sha(self.audit_a)}
        ]
        bundle = self.write_bundle(value)
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "symlink"):
            MODULE.review_bundle(bundle, sha(bundle))

    def test_symlinked_ancestor_is_rejected(self) -> None:
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        value = self.bundle()
        value["incidents"][0]["evidence_refs"] = [
            {
                "path": str(alias / self.audit_a.name),
                "sha256": sha(self.audit_a),
            }
        ]
        bundle = self.write_bundle(value)
        with self.assertRaisesRegex(MODULE.RetrospectiveError, "symlink"):
            MODULE.review_bundle(bundle, sha(bundle))

    def test_cli_build_does_not_overwrite_and_validate_passes(self) -> None:
        bundle = self.write_bundle()
        output = self.root / "cli-review.json"
        self.assertEqual(
            MODULE.main(
                [
                    "build",
                    "--bundle",
                    str(bundle),
                    "--expected-bundle-sha256",
                    sha(bundle),
                    "--output",
                    str(output),
                ]
            ),
            0,
        )
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            MODULE.main(
                [
                    "validate",
                    "--bundle",
                    str(bundle),
                    "--review",
                    str(output),
                    "--expected-bundle-sha256",
                    sha(bundle),
                    "--expected-review-sha256",
                    sha(output),
                ]
            ),
            0,
        )
        self.assertEqual(
            MODULE.main(
                [
                    "build",
                    "--bundle",
                    str(bundle),
                    "--expected-bundle-sha256",
                    sha(bundle),
                    "--output",
                    str(output),
                ]
            ),
            1,
        )

    def test_atomic_writer_rejects_symlink_swap_without_chmod_victim(self) -> None:
        output = self.root / "swap-review.json"
        victim = self.root / "victim.txt"
        victim.write_text("victim", encoding="utf-8")
        victim.chmod(0o644)

        def symlink_swap(
            _descriptor: int, _directory_descriptor: int, _output_name: bytes
        ) -> None:
            output.symlink_to(victim)

        with mock.patch.object(
            MODULE, "_link_unnamed_file", side_effect=symlink_swap
        ):
            with self.assertRaisesRegex(
                MODULE.RetrospectiveError, "published output identity changed"
            ):
                MODULE._atomic_write_json(output, {"safe": True})
        self.assertTrue(output.is_symlink())
        self.assertEqual(victim.stat().st_mode & 0o777, 0o644)
        self.assertEqual(victim.read_text(encoding="utf-8"), "victim")

    def test_atomic_writer_portable_named_temp_fallback(self) -> None:
        output = self.root / "fallback-review.json"
        real_open = MODULE.os.open

        def no_tmpfile(path, flags, mode=0o777, *, dir_fd=None):
            if hasattr(MODULE.os, "O_TMPFILE") and (
                flags & MODULE.os.O_TMPFILE
            ) == MODULE.os.O_TMPFILE:
                raise OSError(MODULE.errno.EOPNOTSUPP, "unsupported")
            if dir_fd is None:
                return real_open(path, flags, mode)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(MODULE.os, "open", side_effect=no_tmpfile):
            MODULE._atomic_write_json(output, {"safe": True})
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8")), {"safe": True}
        )
        self.assertEqual(list(self.root.glob(f".{output.name}.*")), [])


if __name__ == "__main__":
    unittest.main()
