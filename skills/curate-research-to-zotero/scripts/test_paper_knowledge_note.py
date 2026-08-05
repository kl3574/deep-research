from __future__ import annotations

import copy
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("paper_knowledge_note.py")
MODULE_SPEC = importlib.util.spec_from_file_location("paper_knowledge_note", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
note = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(note)

VERIFY_PATH = Path(__file__).with_name("verify_note_html.py")
VERIFY_SPEC = importlib.util.spec_from_file_location("verify_note_html_projection", VERIFY_PATH)
assert VERIFY_SPEC is not None and VERIFY_SPEC.loader is not None
verify_note_html = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(verify_note_html)


def load_script_module(name: str):
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"test_{name}_projection", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare_note_migration = load_script_module("prepare_note_migration")
update_existing_note = load_script_module("update_existing_note")
render_zotero_desktop_runner = load_script_module("render_zotero_desktop_runner")


def _legacy_valid_input() -> dict[str, object]:
    return {
        "schema": "PaperUnderstandingNoteInput/v1",
        "understanding_binding": {
            "understanding_id": "paper-understanding-0001",
            "understanding_digest": "d" * 64,
            "validation_record_id": "validation-record-0001",
            "validation_record_digest": "e" * 64,
        },
        "executive_summary": {
            "research_retrieval_title": (
                "适用：稀疏、含噪且采样不足的动力系统辨识｜"
                "结论（限定）：满足可辨识性条件时可恢复主导项"
            ),
            "summary": "该方法在明确识别条件下将动力学结构发现化为稀疏回归。",
            "claim_ids": ["C1"],
        },
        "applicability": {
            "primary_use_case": "稀疏、含噪且采样不足的动力系统辨识",
            "applies_when": ["候选库包含真实项", "噪声水平受控"],
            "does_not_apply_when": ["候选库遗漏真实项"],
        },
        "workflow": {
            "inputs": ["观测矩阵", "候选函数库"],
            "preconditions": ["采样覆盖目标时间尺度"],
            "steps": [
                {
                    "step_id": "W1",
                    "action": "构造候选函数矩阵",
                    "output": "设计矩阵",
                    "checks": ["列尺度已归一化"],
                },
                {
                    "step_id": "W2",
                    "action": "求解稀疏回归并复核残差",
                    "output": "候选支撑集",
                    "checks": ["留出集残差未恶化"],
                },
            ],
            "outputs": ["稀疏系数", "诊断记录"],
            "data_flow": ["原始观测到设计矩阵", "设计矩阵到支撑集"],
        },
        "mathematical_principles": {
            "status": "applicable",
            "not_applicable_reason": None,
            "principles": [
                {
                    "principle_id": "M1",
                    "statement": "状态导数由候选函数的稀疏线性组合表示",
                    "latex": r"\dot{X}=\Theta(X)\Xi",
                    "symbols": ["X：状态矩阵", "Xi：稀疏系数矩阵"],
                    "role": "把结构发现转化为稀疏回归",
                    "assumptions": ["候选库包含真实项"],
                    "derivation": ["离散观测估计状态导数", "在候选库上求系数"],
                    "locator": "正文 p.3 | Eq. (2)",
                    "claim_ids": ["C1"],
                }
            ],
        },
        "algorithmic_principles": {
            "status": "applicable",
            "not_applicable_reason": None,
            "principles": [
                {
                    "algorithm_id": "A1",
                    "name": "阈值稀疏回归",
                    "inputs": ["设计矩阵", "状态导数"],
                    "outputs": ["稀疏系数"],
                    "initialization": "最小二乘初始化",
                    "steps": ["求系数", "删除低于阈值的项", "在剩余项上重拟合"],
                    "update_rule": "每轮在当前支撑集上重求最小二乘解",
                    "stopping_condition": "支撑集不再变化",
                    "complexity": "取决于候选列数和迭代次数",
                    "numerical_risks": ["共线性会放大系数误差"],
                    "locator": "正文 p.4 | Algorithm 1",
                    "claim_ids": ["C1"],
                }
            ],
        },
        "conclusion": {
            "statement": "满足可辨识性条件时可恢复主导项",
            "claim_ids": ["C1"],
            "confidence": "high",
            "confidence_rationale": "结果表和方法条件一致",
        },
        "contributions": [
            {
                "contribution_id": "K1",
                "statement": "将候选库与阈值重拟合结合为可检查的结构恢复流程",
                "claim_ids": ["C1"],
            }
        ],
        "source_binding": {
            "source_id": "source-0001",
            "canonical_title": "A verified sparse recovery method",
            "authors": ["甲作者", "乙作者"],
            "year": 2025,
            "venue": "测试期刊",
            "stable_identifier": "10.1000/example",
            "publication_status": "version_of_record",
            "source_artifact_sha256": "a" * 64,
            "source_bundle_id": "paper-source-bundle-0001",
            "source_bundle_digest": "b" * 64,
            "reading_dossier_id": "reading-dossier-0001",
            "reading_dossier_digest": "c" * 64,
            "paper_card_ref": "paper-card-0001",
            "evidence_ledger_ref": "evidence-ledger-0001",
            "agent_inferences_explicit": True,
        },
        "coverage": {
            "access_level": "full_text",
            "reading_depth": "reconstruction",
            "verified_at": "2026-08-05T10:00:00+08:00",
            "claims": [
                {
                    "claim_id": "C1",
                    "hypothesis_id": "H1",
                    "target_id": "T1",
                    "statement": "在限定条件下可恢复主导动力学项",
                    "relation": "qualifies",
                    "nature": "source-stated",
                    "scope": {
                        "assumptions": ["候选库覆盖真实项"],
                        "conditions": ["噪声水平受控"],
                        "units": ["状态量使用原文单位"],
                        "exclusions": ["不覆盖库外动力学"],
                    },
                    "evidence": [
                        {
                            "evidence_id": "E1",
                            "summary": "表格报告限定噪声下的恢复率",
                            "locator": "正文 p.8 | Table 2",
                        }
                    ],
                    "verifier_status": "passed",
                    "confidence": "high",
                    "confidence_rationale": "结果表和方法条件一致",
                }
            ],
            "boundaries": [
                {
                    "boundary_id": "B1",
                    "condition": "候选库遗漏真实项",
                    "effect": "恢复保证不再适用",
                    "locator": "正文 p.10 | Limitations",
                    "claim_ids": ["C1"],
                }
            ],
        },
    }


FINAL_HANDOFF_EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "learn-from-papers"
    / "examples"
    / "paper_understanding_note_input.example.json"
)


def valid_input() -> dict[str, object]:
    return json.loads(FINAL_HANDOFF_EXAMPLE.read_text(encoding="utf-8"))


class PaperKnowledgeNoteTests(unittest.TestCase):
    def test_projection_is_deterministic_and_preserves_scientific_scope(self) -> None:
        normalized_a, html_a, manifest_a = note.build_projection(valid_input())
        normalized_b, html_b, manifest_b = note.build_projection(valid_input())

        self.assertEqual(normalized_a, normalized_b)
        self.assertEqual(html_a, html_b)
        self.assertEqual(manifest_a, manifest_b)
        self.assertIn(
            "结论：在约束条件下该结论成立",
            normalized_a["executive_summary"]["research_retrieval_title"],
        )
        for value in (
            "hyp-001",
            "target-001",
            "supports",
            "p.1 [0:5]",
            "raw_input",
            "text_data",
            "math-step-001",
            "assumption:Lipschitz 条件",
            "source_stated",
            "alg-step-002",
            "buffer、lr",
            "Evidence ID：evidence-001",
            "Domain ref：workflow、conclusion、math-001、alg-001、applicability",
            "Understanding ID",
        ):
            self.assertIn(value, html_a)

    def test_supplied_retrieval_title_is_used_verbatim_after_normalization(self) -> None:
        payload = valid_input()
        supplied = "适用：实验数据的稀疏结构恢复｜结论：可作为条件性方法候选"
        payload["executive_summary"]["research_retrieval_title"] = supplied

        normalized, rendered, _ = note.build_projection(payload)

        self.assertEqual(
            normalized["executive_summary"]["research_retrieval_title"], supplied
        )
        self.assertIn(f"<h1>{supplied}</h1>", rendered)

    def test_write_contract_preserves_bibliographic_title_fields(self) -> None:
        _, html_value, manifest = note.build_projection(valid_input())

        self.assertEqual(manifest["write_contract"]["allowed_mutation_fields"], ["note"])
        self.assertIn("title", manifest["write_contract"]["forbidden_parent_fields"])
        self.assertIn("shortTitle", manifest["write_contract"]["forbidden_parent_fields"])
        self.assertTrue(
            manifest["write_contract"]["parent_bibliographic_fields_preserved"]
        )
        self.assertIn("不得写入父条目 shortTitle", html_value)

    def test_projection_manifest_is_content_addressed_and_binds_understanding(self) -> None:
        _, rendered, manifest = note.build_projection(valid_input())

        self.assertEqual(
            manifest["projection_id"],
            f"{note.PROJECTION_ID_PREFIX}{manifest['projection_digest'][:16]}",
        )
        self.assertEqual(
            manifest["understanding_binding"],
            valid_input()["understanding_binding"],
        )
        self.assertEqual(
            note.validate_projection_manifest(manifest, rendered=rendered), manifest
        )

    def test_projection_manifest_rejects_digest_html_and_parent_field_tampering(self) -> None:
        _, rendered, manifest = note.build_projection(valid_input())

        digest_tamper = copy.deepcopy(manifest)
        digest_tamper["retrieval_title_codepoints"] += 1
        with self.assertRaisesRegex(note.ContractError, "title length"):
            note.validate_projection_manifest(digest_tamper)

        html_tamper = rendered.replace("执行摘要", "篡改摘要", 1)
        with self.assertRaisesRegex(note.ContractError, "HTML hash"):
            note.validate_projection_manifest(manifest, rendered=html_tamper)

        parent_tamper = copy.deepcopy(manifest)
        parent_tamper["write_contract"]["forbidden_parent_fields"].remove(
            "shortTitle"
        )
        parent_tamper["projection_digest"] = note.projection_content_digest(
            parent_tamper
        )
        parent_tamper["projection_id"] = (
            f"{note.PROJECTION_ID_PREFIX}{parent_tamper['projection_digest'][:16]}"
        )
        with self.assertRaisesRegex(note.ContractError, "preserve all parent"):
            note.validate_projection_manifest(parent_tamper)

    def test_projection_manifest_gates_prepare_update_and_desktop_readback(self) -> None:
        _, rendered, manifest = note.build_projection(valid_input())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            source_path = root / "projection.html"
            manifest_path = root / "projection.json"
            source_path.write_text(rendered, encoding="utf-8")
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "upstream provenance"):
                prepare_note_migration.load_projection_manifests([manifest_path])

    def test_rejects_overlong_retrieval_title_instead_of_truncating(self) -> None:
        payload = valid_input()
        payload["executive_summary"]["research_retrieval_title"] = "适用：" + "场景" * 60

        with self.assertRaisesRegex(note.ContractError, "research retrieval title exceeds"):
            note.build_projection(payload)

    def test_rejects_unsafe_retrieval_title_content(self) -> None:
        unsafe_titles = (
            "适用：场景\n注释｜结论：结果",
            "适用：<b>场景</b>｜结论：结果",
            "适用：10.1000/example｜结论：结果",
            f"适用：{'d' * 64}｜结论：结果",
        )
        for unsafe_title in unsafe_titles:
            with self.subTest(unsafe_title=unsafe_title):
                payload = valid_input()
                payload["executive_summary"][
                    "research_retrieval_title"
                ] = unsafe_title
                with self.assertRaises(note.ContractError):
                    note.build_projection(payload)

    def test_rejects_fields_outside_the_frozen_handoff_domains(self) -> None:
        payload = valid_input()
        payload["claims"] = payload["coverage"]["claims"]

        with self.assertRaisesRegex(note.ContractError, "unknown fields"):
            note.build_projection(payload)

    def test_rejects_absolute_local_paths_and_private_key_shapes(self) -> None:
        for unsafe in ("/home/private/paper.pdf", "真实条目 Q7W8E9R0"):
            with self.subTest(unsafe=unsafe):
                payload = valid_input()
                payload["source_binding"]["paper_card_ref"] = unsafe
                with self.assertRaises(note.ContractError):
                    note.build_projection(payload)

    def test_renderer_escapes_input_html_and_validator_rejects_remote_resources(self) -> None:
        payload = valid_input()
        payload["workflow"]["inputs"][0] = '<img src="https://tracker.invalid/pixel">'
        _, rendered, _ = note.build_projection(payload)

        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;img", rendered)
        mutated = rendered.replace(
            "<h2>适用场景与结论</h2>",
            '<img src="https://tracker.invalid/pixel"><h2>适用场景与结论</h2>',
        )
        errors, _, _ = note.validate_rendered_html(mutated)
        self.assertTrue(any("forbidden element" in error for error in errors))
        self.assertTrue(any("remote-capable" in error for error in errors))

    def test_rejects_html_comments_in_input_and_hidden_output(self) -> None:
        payload = valid_input()
        payload["executive_summary"]["summary"] = "摘要 <!-- hidden -->"
        with self.assertRaisesRegex(note.ContractError, "HTML comment"):
            note.build_projection(payload)

        _, rendered, _ = note.build_projection(valid_input())
        hidden = "<!-- /home/private/paper.pdf Q7W8E9R0 -->\n" + rendered
        errors, _, _ = note.validate_rendered_html(hidden)
        self.assertTrue(any("HTML comments are forbidden" in error for error in errors))
        self.assertTrue(any("absolute local path" in error for error in errors))
        self.assertTrue(any("private-key-shaped token" in error for error in errors))
        shared_errors, _, _ = verify_note_html.validate_note(hidden)
        self.assertTrue(
            any("HTML comments are forbidden" in error for error in shared_errors)
        )

    def test_verify_requires_exact_deterministic_projection(self) -> None:
        payload = valid_input()
        _, rendered, manifest = note.build_projection(payload)

        self.assertEqual(note.verify_projection(payload, rendered), manifest)
        with self.assertRaisesRegex(note.ContractError, "not the deterministic projection"):
            note.verify_projection(payload, rendered.replace("raw_input", "tampered", 1))

    def test_shared_note_validator_dispatches_to_v2_contract(self) -> None:
        _, rendered, _ = note.build_projection(valid_input())

        errors, _, summary = verify_note_html.validate_note(rendered)

        self.assertEqual(errors, [])
        self.assertEqual(summary["note_contract"], "PaperKnowledgeNote/v2")
        self.assertTrue(summary["parent_bibliographic_fields_preserved"])

    def test_not_applicable_requires_a_reason(self) -> None:
        payload = valid_input()
        payload["mathematical_principles"] = {
            "status": "not_applicable",
            "rationale": "该来源只描述经验工作流",
            "evidence_ids": ["evidence-001"],
            "missing_information": [],
            "not_applicable_reason": "该来源只描述经验工作流",
            "assumptions": [],
            "derivation_steps": [],
            "results": [],
            "principles": [],
        }
        payload["contributions"][0]["domain_refs"] = [
            "workflow",
            "conclusion",
            "mathematical_principles",
            "alg-001",
            "applicability",
        ]
        _, rendered, _ = note.build_projection(payload)
        self.assertIn("not_applicable", rendered)

        invalid = copy.deepcopy(payload)
        invalid["mathematical_principles"]["not_applicable_reason"] = ""
        with self.assertRaises(note.ContractError):
            note.build_projection(invalid)

    def test_render_command_creates_private_non_overwriting_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.json"
            html_path = root / "note.html"
            manifest_path = root / "projection.json"
            input_path.write_text(
                json.dumps(valid_input(), ensure_ascii=False), encoding="utf-8"
            )
            upstream_paths = {}
            for name in (
                "understanding",
                "validation_record",
                "source_bundle",
                "dossier",
            ):
                path = root / f"{name}.json"
                path.write_text("{}", encoding="utf-8")
                upstream_paths[name] = path
            source_path = root / "source.pdf"
            source_path.write_bytes(b"%PDF-live-source")

            class FakeLearn:
                @staticmethod
                def validate_note_input_projection(*_args, **_kwargs):
                    return valid_input()

            provenance_args = [
                "--understanding",
                str(upstream_paths["understanding"]),
                "--validation-record",
                str(upstream_paths["validation_record"]),
                "--source-bundle",
                str(upstream_paths["source_bundle"]),
                "--source",
                str(source_path),
                "--dossier",
                str(upstream_paths["dossier"]),
            ]

            with mock.patch.object(note, "_load_learn_module", return_value=FakeLearn()):
                stdout = contextlib.redirect_stdout(io.StringIO())
                with stdout:
                    code = note.main(
                        [
                            "render",
                            str(input_path),
                            "--output",
                            str(html_path),
                            "--manifest",
                            str(manifest_path),
                            *provenance_args,
                        ]
                    )
            self.assertEqual(code, 0)
            self.assertEqual(html_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o600)
            with mock.patch.object(note, "_load_learn_module", return_value=FakeLearn()):
                stderr = contextlib.redirect_stderr(io.StringIO())
                with stderr:
                    code = note.main(
                        [
                            "render",
                            str(input_path),
                            "--output",
                            str(html_path),
                            "--manifest",
                            str(manifest_path),
                            *provenance_args,
                        ]
                    )
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
