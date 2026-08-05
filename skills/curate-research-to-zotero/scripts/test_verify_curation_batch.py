#!/usr/bin/env python3

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import verify_curation_batch as verify


PAPER_NOTE_PATH = Path(__file__).with_name("paper_knowledge_note.py")
PAPER_NOTE_SPEC = importlib.util.spec_from_file_location(
    "paper_knowledge_note_for_batch_test",
    PAPER_NOTE_PATH,
)
assert PAPER_NOTE_SPEC is not None and PAPER_NOTE_SPEC.loader is not None
paper_note = importlib.util.module_from_spec(PAPER_NOTE_SPEC)
PAPER_NOTE_SPEC.loader.exec_module(paper_note)

FINAL_HANDOFF_EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "learn-from-papers"
    / "examples"
    / "paper_understanding_note_input.example.json"
)


def metadata_note() -> str:
    return """<div data-schema-version="9" data-access-level="metadata_only">
<h1>文献笔记｜Metadata Fixture</h1>
<h2>资料与阅读状态</h2><p>标题：Metadata Fixture；作者：甲；年份：2024；期刊或载体：测试期刊；DOI或稳定标识：10.1000/test；版本与出版状态：正式版；访问层级：metadata_only；全文状态：未获取全文；阅读深度：map；核验时间：2026-08-05。</p>
<h2>为什么重要</h2><p>该题录可能相关，但尚无全文证据。</p>
<h2>一句话结论</h2><p>未获取全文，不能形成科学结论。</p>
<h2>心智模型</h2><p>当前只保留书目信息，等待合法全文。</p>
<h2>关键主张与证据</h2><p>未获取全文，未形成全文证据主张。</p><table><tr><th>Claim ID</th><th>性质</th><th>主张</th><th>证据与精确定位</th><th>条件</th><th>置信度与理由</th></tr></table>
<h2>方法或推导</h2><p>未获取全文，方法与推导均未核验。</p>
<h2>结果</h2><p>未获取全文，结果未核验。</p>
<h2>假设、失败边界与竞争解释</h2><p>题录信息不能替代全文证据。</p>
<h2>知识图谱关系</h2><p>仅登记候选来源，不建立证据支持关系。</p>
<h2>复用</h2><p>取得全文后必须重新深读和核验。</p>
<h2>溯源</h2><p>元数据来源：https://doi.org/10.1000/test；元数据核验时间：2026-08-05；Agent推断：未形成全文主张。</p>
</div>"""


def paper_knowledge_note() -> str:
    payload = json.loads(FINAL_HANDOFF_EXAMPLE.read_text(encoding="utf-8"))
    _, rendered, _ = paper_note.build_projection(payload)
    return rendered


class CurationBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle.json"
        self.bundle.write_text('{"native_bundle":true}\n', encoding="utf-8")
        self.pdf = self.root / "paper.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\nfixture\n")
        self.note = self.root / "note.html"
        headings = "".join(
            f"<h2>{heading}</h2><p>x</p>" for heading in verify.NOTE_SECTIONS
        )
        self.note.write_text(
            f'<div data-schema-version="9">{headings}</div>',
            encoding="utf-8",
        )
        self.target = {
            "group_id": 1234567,
            "library_id": 2,
            "library_name": "Example Research Library",
            "collection_key": "COLL0001",
            "collection_path": ["Research", "Inverse Problems", "Calibration"],
        }
        identity = verify.compute_identity_fingerprint(self.target)
        self.fingerprint = {
            "identity_sha256": identity,
            "state_sha256": verify.compute_state_fingerprint(
                identity, 12, ["ABCDEFGH"]
            ),
            "captured_at": "2026-08-04T00:00:00+08:00",
            "collection_version": 12,
            "top_level_parent_keys": ["ABCDEFGH"],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def entry(self, entry_id: str = "paper-1") -> dict[str, object]:
        return {
            "entry_id": entry_id,
            "canonical_identity": {
                "type": "doi",
                "value": "10.1000/example",
            },
            "decision": "create_parent",
            "handler": "import_zotero_bundle",
            "gate_status": "golden",
            "fulltext_status": "fulltext_verified",
            "expected_effect": {
                "new_parent_count": 1,
                "target_membership": True,
                "note_action": "create",
                "attachment_action": "create",
            },
            "bundle_path": str(self.bundle),
            "bundle_sha256": verify.sha256_file(self.bundle),
            "note_artifact": {
                "path": str(self.note),
                "sha256": verify.sha256_file(self.note),
                "schema_version": "9",
            },
            "pdf_artifacts": [
                {
                    "path": str(self.pdf),
                    "sha256": verify.sha256_file(self.pdf),
                    "artifact_role": "version_of_record",
                    "counts_as_fulltext": True,
                }
            ],
        }

    def batch(self) -> dict[str, object]:
        return {
            "schema": "CurationBatch/v1",
            "batch_id": "test-batch",
            "created_at": "2026-08-04T00:00:00+08:00",
            "target": copy.deepcopy(self.target),
            "target_fingerprint": copy.deepcopy(self.fingerprint),
            "entries": [self.entry()],
        }

    def blocked_entry(self, entry_id: str, decision: str) -> dict[str, object]:
        entry = self.entry(entry_id)
        entry["canonical_identity"] = {
            "type": "doi",
            "value": f"10.1000/{entry_id}",
        }
        for key in ("bundle_path", "bundle_sha256", "note_artifact"):
            entry.pop(key)
        entry["pdf_artifacts"] = []
        entry.update(
            {
                "decision": decision,
                "handler": "none",
                "gate_status": "blocked",
                "fulltext_status": "metadata_only",
                "expected_effect": {
                    "new_parent_count": 0,
                    "target_membership": False,
                    "note_action": "no_op",
                    "attachment_action": "no_op",
                },
            }
        )
        if decision == "blocked_unsupported_operation":
            entry["existing_parent"] = {
                "key": "ZXCVBNMA",
                "version": 4,
                "in_target": False,
            }
        return entry

    def mixed_batch(self) -> dict[str, object]:
        batch = self.batch()
        golden = []
        for index in range(1, 15):
            entry = self.entry(f"golden-{index:02d}")
            entry["canonical_identity"] = {
                "type": "doi",
                "value": f"10.1000/golden-{index:02d}",
            }
            golden.append(entry)
        batch["entries"] = golden + [
            self.blocked_entry("blocked-duplicate", "blocked_duplicate_conflict"),
            self.blocked_entry("blocked-version", "blocked_version_conflict"),
            self.blocked_entry("blocked-operation", "blocked_unsupported_operation"),
        ]
        return batch

    def success_execution(
        self, batch: dict[str, object]
    ) -> dict[str, object]:
        events = []
        digest = verify.digest_value(batch)
        for index, state in enumerate(verify.SUCCESS_STATES):
            event: dict[str, object] = {
                "sequence": index + 1,
                "state": state,
                "recorded_at": "2026-08-04T00:00:00+08:00",
            }
            if state == "write_authorized":
                event["evidence"] = {"approved_batch_digest": digest}
            events.append(event)
        return {
            "schema": "CurationExecution/v1",
            "batch_digest": digest,
            "target_identity_sha256": batch["target_fingerprint"][
                "identity_sha256"
            ],
            "initial_state_sha256": batch["target_fingerprint"][
                "state_sha256"
            ],
            "events": events,
            "results": [
                {
                    "entry_id": entry["entry_id"],
                    "status": (
                        "blocked"
                        if entry["decision"] in verify.BLOCKED_DECISIONS
                        else "readback_verified"
                    ),
                    "observed_effect": copy.deepcopy(entry["expected_effect"]),
                }
                for entry in batch["entries"]
            ],
        }

    def test_golden_happy_path(self) -> None:
        batch = self.batch()
        self.assertEqual([], verify.validate_batch(batch))
        observed = {
            "schema": "ObservedTarget/v1",
            "target": copy.deepcopy(batch["target"]),
            "target_fingerprint": copy.deepcopy(
                batch["target_fingerprint"]
            ),
        }
        self.assertEqual(
            [], verify.validate_observed_target(observed, batch)
        )
        self.assertEqual(
            [], verify.validate_execution(self.success_execution(batch), batch)
        )

    def test_mixed_batch_14_golden_3_blocked_readback_passes(self) -> None:
        batch = self.mixed_batch()
        frozen_batch = copy.deepcopy(batch)
        digest = verify.digest_value(batch)
        execution = self.success_execution(batch)

        self.assertEqual([], verify.validate_batch(batch))
        self.assertEqual(digest, execution["batch_digest"])
        self.assertEqual([], verify.validate_execution(execution, batch))
        self.assertEqual(frozen_batch, batch)
        statuses = {
            result["entry_id"]: result["status"] for result in execution["results"]
        }
        self.assertEqual(
            14, sum(value == "readback_verified" for value in statuses.values())
        )
        self.assertEqual(3, sum(value == "blocked" for value in statuses.values()))

    def test_mixed_batch_blocked_results_fail_closed(self) -> None:
        batch = self.mixed_batch()
        base = self.success_execution(batch)
        cases: dict[str, tuple[dict[str, object], str]] = {}

        missing = copy.deepcopy(base)
        missing["results"] = [
            result
            for result in missing["results"]
            if result["entry_id"] != "blocked-duplicate"
        ]
        cases["missing"] = (missing, "lacks blocked result")

        wrong_status = copy.deepcopy(base)
        next(
            result
            for result in wrong_status["results"]
            if result["entry_id"] == "blocked-version"
        )["status"] = "readback_verified"
        cases["wrong_status"] = (wrong_status, "status must be blocked")

        mismatch = copy.deepcopy(base)
        next(
            result
            for result in mismatch["results"]
            if result["entry_id"] == "blocked-operation"
        )["observed_effect"]["target_membership"] = True
        cases["mismatch"] = (mismatch, "effect mismatch")

        mutated = copy.deepcopy(base)
        next(
            result
            for result in mutated["results"]
            if result["entry_id"] == "blocked-duplicate"
        )["observed_effect"] = {
            "new_parent_count": 1,
            "target_membership": True,
            "note_action": "create",
            "attachment_action": "create",
        }
        cases["mutated"] = (mutated, "reports mutation")

        for name, (execution, expected_error) in cases.items():
            with self.subTest(name=name):
                errors = verify.validate_execution(execution, batch)
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_mixed_batch_does_not_allow_blocked_status_for_golden_entry(self) -> None:
        batch = self.mixed_batch()
        execution = self.success_execution(batch)
        execution["results"][0]["status"] = "blocked"

        errors = verify.validate_execution(execution, batch)

        self.assertTrue(any("lacks readback result" in error for error in errors))

    def test_paper_knowledge_note_v2_five_section_branch(self) -> None:
        self.note.write_text(paper_knowledge_note(), encoding="utf-8")
        batch = self.batch()
        batch["entries"][0]["note_artifact"]["sha256"] = verify.sha256_file(
            self.note
        )

        self.assertEqual([], verify.validate_batch(batch))

    def test_metadata_only_marker_branch(self) -> None:
        self.note.write_text(metadata_note(), encoding="utf-8")
        batch = self.batch()
        entry = batch["entries"][0]
        entry["decision"] = "metadata_only_create"
        entry["fulltext_status"] = "metadata_only"
        entry["pdf_artifacts"] = []
        entry["expected_effect"]["attachment_action"] = "no_op"
        entry["note_artifact"]["sha256"] = verify.sha256_file(self.note)

        self.assertEqual([], verify.validate_batch(batch))

    def test_note_contract_marker_and_section_mixes_are_rejected(self) -> None:
        cases = {
            "pkn_with_metadata_marker": paper_knowledge_note().replace(
                'data-note-contract="PaperKnowledgeNote/v2"',
                'data-note-contract="PaperKnowledgeNote/v2" data-access-level="metadata_only"',
                1,
            ),
            "legacy_with_pkn_contract": self.note.read_text(encoding="utf-8").replace(
                'data-schema-version="9"',
                'data-schema-version="9" data-note-contract="PaperKnowledgeNote/v2"',
                1,
            ),
            "pkn_sections_with_metadata_marker": paper_knowledge_note()
            .replace(' data-note-contract="PaperKnowledgeNote/v2"', "", 1)
            .replace(
                'data-schema-version="9"',
                'data-schema-version="9" data-access-level="metadata_only"',
                1,
            ),
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                self.note.write_text(content, encoding="utf-8")
                batch = self.batch()
                batch["entries"][0]["note_artifact"][
                    "sha256"
                ] = verify.sha256_file(self.note)
                self.assertTrue(verify.validate_batch(batch))

    def test_target_drift_and_schema_mismatch(self) -> None:
        batch = self.batch()
        invalid = copy.deepcopy(batch)
        invalid["schema"] = "CurationBatch/v2"
        self.assertTrue(
            any("schema_mismatch" in value for value in verify.validate_batch(invalid))
        )
        observed = {
            "schema": "ObservedTarget/v1",
            "target": copy.deepcopy(batch["target"]),
            "target_fingerprint": copy.deepcopy(
                batch["target_fingerprint"]
            ),
        }
        observed["target_fingerprint"]["collection_version"] = 13
        observed["target_fingerprint"][
            "state_sha256"
        ] = verify.compute_state_fingerprint(
            observed["target_fingerprint"]["identity_sha256"],
            13,
            ["ABCDEFGH"],
        )
        self.assertTrue(
            any(
                "target_drift" in value
                for value in verify.validate_observed_target(observed, batch)
            )
        )

    def test_si_only_and_duplicate_identity_are_rejected(self) -> None:
        batch = self.batch()
        batch["entries"][0]["pdf_artifacts"][0][
            "artifact_role"
        ] = "supporting_information"
        errors = verify.validate_batch(batch)
        self.assertTrue(
            any("cannot count as full text" in value for value in errors)
        )
        self.assertTrue(
            any("requires a verified main-text" in value for value in errors)
        )
        batch = self.batch()
        duplicate = self.entry("paper-2")
        batch["entries"].append(duplicate)
        self.assertTrue(
            any(
                "duplicate canonical identity" in value
                for value in verify.validate_batch(batch)
            )
        )

    def test_existing_outside_target_is_blocked_not_duplicated(self) -> None:
        batch = self.batch()
        batch["entries"][0]["existing_parent"] = {
            "key": "ZXCVBNMA",
            "version": 4,
            "in_target": False,
        }
        errors = verify.validate_batch(batch)
        self.assertTrue(
            any("must never be handled by a create" in value for value in errors)
        )
        blocked = self.entry()
        for key in ("bundle_path", "bundle_sha256", "note_artifact"):
            blocked.pop(key)
        blocked["pdf_artifacts"] = []
        blocked.update(
            {
                "decision": "blocked_unsupported_operation",
                "handler": "none",
                "gate_status": "blocked",
                "fulltext_status": "metadata_only",
                "existing_parent": {
                    "key": "ZXCVBNMA",
                    "version": 4,
                    "in_target": False,
                },
                "expected_effect": {
                    "new_parent_count": 0,
                    "target_membership": False,
                    "note_action": "no_op",
                    "attachment_action": "no_op",
                },
            }
        )
        batch["entries"] = [blocked]
        self.assertEqual([], verify.validate_batch(batch))

    def test_partial_commit_and_readback_mismatch(self) -> None:
        batch = self.batch()
        second = self.entry("paper-2")
        second["canonical_identity"] = {
            "type": "doi",
            "value": "10.1000/example-2",
        }
        batch["entries"].append(second)
        digest = verify.digest_value(batch)
        events = []
        for index, state in enumerate(verify.SUCCESS_STATES[:6]):
            event: dict[str, object] = {
                "sequence": index + 1,
                "state": state,
                "recorded_at": "2026-08-04T00:00:00+08:00",
            }
            if state == "write_authorized":
                event["evidence"] = {"approved_batch_digest": digest}
            events.append(event)
        base = {
            "schema": "CurationExecution/v1",
            "batch_digest": digest,
            "target_identity_sha256": batch["target_fingerprint"][
                "identity_sha256"
            ],
            "initial_state_sha256": batch["target_fingerprint"][
                "state_sha256"
            ],
        }
        partial = {
            **base,
            "events": events
            + [
                {
                    "sequence": 7,
                    "state": "partial_commit",
                    "recorded_at": "2026-08-04T00:00:00+08:00",
                    "detail": "one committed",
                }
            ],
            "results": [
                {"entry_id": "paper-1", "status": "imported"},
                {"entry_id": "paper-2", "status": "pending"},
            ],
        }
        self.assertEqual([], verify.validate_execution(partial, batch))
        mismatch = {
            **base,
            "events": events
            + [
                {
                    "sequence": 7,
                    "state": "imported",
                    "recorded_at": "2026-08-04T00:00:00+08:00",
                },
                {
                    "sequence": 8,
                    "state": "readback_mismatch",
                    "recorded_at": "2026-08-04T00:00:00+08:00",
                    "detail": "hash differs",
                },
            ],
            "results": [
                {
                    "entry_id": "paper-1",
                    "status": "readback_mismatch",
                    "observed_effect": {"new_parent_count": 0},
                },
                {"entry_id": "paper-2", "status": "pending"},
            ],
        }
        self.assertEqual([], verify.validate_execution(mismatch, batch))


if __name__ == "__main__":
    unittest.main()
