#!/usr/bin/env python3
"""Focused tests for PaperUnderstanding and its note projection."""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
import stat
import tempfile
from io import StringIO
from pathlib import Path
from typing import Any
from unittest import TestCase

SCRIPT_DIR = Path(__file__).resolve().parent
EXAMPLES = SCRIPT_DIR.parent / "examples"
FIXTURE = EXAMPLES / "paper_reading_dossier_fixture"
DOSSIER_PATH = EXAMPLES / "paper_understanding_dossier.example.json"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


module = _load_module("paper_understanding", SCRIPT_DIR / "paper_understanding.py")
source_bundle_module = _load_module(
    "paper_source_bundle",
    SCRIPT_DIR / "paper_source_bundle.py",
)
dossier_module = _load_module(
    "paper_reading_dossier_for_understanding",
    SCRIPT_DIR / "paper_reading_dossier.py",
)
paper_knowledge_note = _load_module(
    "paper_knowledge_note",
    SCRIPT_DIR.parent.parent
    / "curate-research-to-zotero"
    / "scripts"
    / "paper_knowledge_note.py",
)


def _verified_inputs() -> tuple[dict[str, Any], dict[str, Any], str, str, str]:
    source = str(FIXTURE / "paper.txt")
    bundle = str(FIXTURE / "bundle.json")
    dossier_path = str(DOSSIER_PATH)
    manifest = source_bundle_module.verify_bundle(bundle=bundle, source=source)
    dossier = dossier_module.validate_dossier(
        json.loads(DOSSIER_PATH.read_text(encoding="utf-8")),
        bundle=bundle,
        source=source,
    )
    return manifest, dossier, source, bundle, dossier_path


def _base_understanding(
    manifest: dict[str, Any],
    dossier: dict[str, Any],
) -> dict[str, Any]:
    authoritative_claim = dossier["claims"][0]
    authoritative_evidence = dossier["evidence_records"][0]
    locator = authoritative_evidence["exact_locator"]
    return {
        "schema": module.SCHEMA,
        "schema_version": module.SCHEMA_VERSION,
        "producer": module.PRODUCER,
        "protocol_version": module.PROTOCOL_VERSION,
        "generated_at": "2026-08-05T00:00:00Z",
        "research_retrieval_title": "适用：模型是否能稳定训练｜结论：在约束条件下该结论成立",
        "source_binding": {
            "source_id": dossier["review_source"]["source_id"],
            "canonical_title": "Stability Note: an Example",
            "authors": ["A. Author", "B. Author"],
            "year": 2024,
            "venue": "Journal of Examples",
            "stable_identifier": "10.9999/example",
            "publication_status": "preprint",
            "source_artifact_sha256": manifest["source"]["source_sha256"],
            "source_bundle_id": manifest["bundle_id"],
            "source_bundle_digest": manifest["bundle_digest"],
            "reading_dossier_id": dossier["dossier_id"],
            "reading_dossier_digest": dossier["dossier_digest"],
            "paper_card_ref": "PC-001",
            "evidence_ledger_ref": "EL-001",
            "agent_inferences_explicit": True,
            "reading_depth": dossier["inspection_depth"],
            "access_level": dossier["access_level"],
            "verified_at": "2026-08-05T00:00:00Z",
        },
        "executive_summary": {
            "applicability_short": "模型是否能稳定训练",
            "conclusion_short": "在约束条件下该结论成立",
            "summary": "该论文支持稳定训练的一个充分条件。",
            "claim_ids": ["claim-001"],
        },
        "applicability": {
            "status": "answered",
            "rationale": "方法给出了可复核的边界条件",
            "evidence_ids": ["evidence-001"],
            "missing_information": [],
            "primary_use_case": "参数训练稳定性评估",
            "applies_when": ["观测噪声受限"],
            "does_not_apply_when": ["过度外推任务"],
            "claim_ids": ["claim-001"],
        },
        "workflow": {
            "status": "answered",
            "rationale": "从方法、假设到结论可追溯",
            "evidence_ids": ["evidence-001"],
            "missing_information": [],
            "inputs": ["训练日志", "超参数"],
            "preconditions": ["输入数据已标准化"],
            "steps": [
                {
                    "step_id": "step-01",
                    "action": "复核关键假设",
                    "output": "假设清单",
                    "checks": ["符号定义一致"],
                },
                {
                    "step_id": "step-02",
                    "action": "提取关键不等式",
                    "output": "边界式",
                    "checks": ["逐行校验"],
                },
            ],
            "outputs": ["支持结论"],
            "data_flow": ["node-in -> node-mid", "node-mid -> node-out"],
            "graph": {
                "nodes": [
                    {
                        "node_id": "node-in",
                        "kind": "input",
                        "description": "输入日志",
                        "semantic_type": "raw_input",
                        "representation": "text_data",
                        "format": "text/plain",
                        "shape": "records[N]",
                        "unit": "none",
                    },
                    {
                        "node_id": "node-mid",
                        "kind": "intermediate",
                        "description": "约束集合",
                        "semantic_type": "constraint_set",
                        "representation": "symbolic_set",
                        "format": "math/latex",
                        "shape": "constraints[K]",
                        "unit": "none",
                    },
                    {
                        "node_id": "node-out",
                        "kind": "output",
                        "description": "输出边界结论",
                        "semantic_type": "final_statement",
                        "representation": "text_data",
                        "format": "text/plain",
                        "shape": "scalar",
                        "unit": "none",
                    },
                ],
                "operations": [
                    {
                        "operation_id": "op-01",
                        "operation": "extract constraints",
                        "consumes": ["node-in"],
                        "produces": ["node-mid"],
                    },
                    {
                        "operation_id": "op-02",
                        "operation": "derive bound",
                        "consumes": ["node-mid"],
                        "produces": ["node-out"],
                    },
                ],
            },
        },
        "mathematical_principles": {
            "status": "answered",
            "rationale": "定理链条可逐步展开",
            "evidence_ids": ["evidence-001"],
            "missing_information": [],
            "assumptions": ["Lipschitz 条件"],
            "derivation_steps": [
                {
                    "step_id": "math-step-001",
                    "statement": "从 Lipschitz 条件得到界限估计。",
                    "depends_on": ["assumption:Lipschitz 条件"],
                    "origin": "source_stated",
                    "locator": locator,
                    "evidence_ids": ["evidence-001"],
                },
                {
                    "step_id": "math-step-002",
                    "statement": "由前一步推出稳定性边界。",
                    "depends_on": ["step:math-step-001"],
                    "origin": "agent_reconstructed",
                    "locator": locator,
                    "evidence_ids": ["evidence-001"],
                },
            ],
            "results": ["稳定性边界成立"],
            "principles": [
                {
                    "principle_id": "math-001",
                    "statement": "若满足假设 H，则有 L2 收敛",
                    "latex": r"\dot V(t) \le -\alpha V(t)",
                    "symbols": ["V", r"\alpha"],
                    "assumptions": ["正则性"],
                    "derivation_steps": [
                        {
                            "step_id": "math-prin-001",
                            "statement": "从正则性与边界直接推出。",
                            "depends_on": ["assumption:正则性"],
                            "origin": "source_stated",
                            "locator": locator,
                            "evidence_ids": ["evidence-001"],
                        }
                    ],
                    "results": ["V(t) 收敛"],
                    "origin": "source_stated",
                    "claim_ids": ["claim-001"],
                    "locator": locator,
                }
            ],
        },
        "algorithmic_principles": {
            "status": "answered",
            "rationale": "步骤与目标函数一致",
            "evidence_ids": ["evidence-001"],
            "missing_information": [],
            "objective": "稳定性验证",
            "state_variables": ["x_t", "learning_rate"],
            "ordered_steps": [
                {
                    "step_id": "alg-step-001",
                    "action": "初始化缓冲区",
                    "depends_on": [],
                    "consumes": ["x_t"],
                    "produces": ["buffer"],
                    "origin": "source_stated",
                    "locator": locator,
                    "evidence_ids": ["evidence-001"],
                },
                {
                    "step_id": "alg-step-002",
                    "action": "执行稳定性裁剪更新",
                    "depends_on": ["alg-step-001"],
                    "consumes": ["buffer", "learning_rate"],
                    "produces": ["x_next"],
                    "origin": "source_stated",
                    "locator": locator,
                    "evidence_ids": ["evidence-001"],
                },
            ],
            "invariants": ["范数有界"],
            "failure_modes": ["梯度爆炸"],
            "algorithms": [
                {
                    "algorithm_id": "alg-001",
                    "name": "稳定性裁剪更新",
                    "inputs": ["x_t", "lr"],
                    "outputs": ["x_next"],
                    "initialization": "x_0=0",
                    "ordered_steps": [
                        {
                            "step_id": "alg-001-1",
                            "action": "x_next = x_t + lr * grad",
                            "depends_on": [],
                            "consumes": ["x_t", "lr"],
                            "produces": ["x_next"],
                            "origin": "source_stated",
                            "locator": locator,
                            "evidence_ids": ["evidence-001"],
                        }
                    ],
                    "update_rule": "梯度方向收缩",
                    "stopping_condition": "|grad| < eps",
                    "complexity": "O(Td)",
                    "numerical_risks": ["步长敏感"],
                    "claim_ids": ["claim-001"],
                    "locator": locator,
                    "origin": "source_stated",
                }
            ],
        },
        "conclusion": {
            "status": "answered",
            "rationale": "已匹配主文假设与证据",
            "evidence_ids": ["evidence-001"],
            "missing_information": [],
            "statement": "训练在上述条件下稳定",
            "confidence": "medium",
            "confidence_rationale": "结论由主文证据直接支持",
            "claim_ids": ["claim-001"],
        },
        "contributions": [
            {
                "contribution_id": "contrib-001",
                "statement": "明确了稳定性验证的先决条件",
                "claim_ids": ["claim-001"],
                "evidence_ids": ["evidence-001"],
                "domain_refs": [
                    "step-01",
                    "node-mid",
                    "math-001",
                    "alg-001",
                    "applicability",
                    "conclusion",
                ],
            }
        ],
        "coverage": {
            "understood_claims": [
                {"claim_id": "claim-001", "reason": "源文献给出直接证据"}
            ],
            "terminal_claims": [],
        },
        "claims": [
            {
                "claim_id": "claim-001",
                "hypothesis_id": "hyp-001",
                "target_id": "target-001",
                "statement": authoritative_claim["statement"],
                "relation": "supports",
                "nature": "source-stated",
                "scope": authoritative_claim["scope"],
                "evidence": [
                    {
                        "evidence_id": "evidence-001",
                        "summary": authoritative_claim["statement"],
                        "locator": locator,
                    }
                ],
                "evidence_ids": ["evidence-001"],
                "verifier_status": "passed",
                "confidence": "high",
                "confidence_rationale": "来源清晰且可复核",
                "status": "answered",
            }
        ],
    }


def _create_verified() -> tuple[dict[str, Any], dict[str, Any], str, str, str]:
    manifest, dossier, source, bundle, dossier_path = _verified_inputs()
    created = module.create_understanding(
        _base_understanding(manifest, dossier),
        source_bundle=bundle,
        source=source,
        dossier=dossier_path,
    )
    record = module.create_validation_record(
        created,
        source_bundle=bundle,
        source=source,
        dossier=dossier_path,
    )
    return created, record, source, bundle, dossier_path


class PaperUnderstandingTests(TestCase):
    def test_create_validate_and_validation_record_roundtrip(self) -> None:
        created, record, source, bundle, dossier = _create_verified()
        validated = module.validate_understanding(
            created,
            source_bundle_path=bundle,
            source_path=source,
            dossier_path=dossier,
        )
        self.assertEqual(validated["understanding_id"], created["understanding_id"])
        self.assertTrue(record["source_binding_verified"])
        self.assertEqual(
            module.validate_validation_record(record, understanding=validated),
            record,
        )

    def test_validate_cli_emits_and_writes_content_addressed_record(self) -> None:
        created, _, source, bundle, dossier = _create_verified()
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            input_path = workspace / "understanding.json"
            output_path = workspace / "validation.json"
            input_path.write_text(json.dumps(created), encoding="utf-8")
            stdout = StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "validate",
                        "--input",
                        str(input_path),
                        "--bundle",
                        bundle,
                        "--source",
                        source,
                        "--dossier",
                        dossier,
                        "--output",
                        str(output_path),
                    ]
                )
            self.assertEqual(code, 0)
            emitted = json.loads(stdout.getvalue())
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(emitted, written)
            self.assertEqual(written["schema"], module.VALIDATION_SCHEMA)
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)

    def test_required_mutations_fail_closed(self) -> None:
        manifest, dossier, _, _, _ = _verified_inputs()
        base = _base_understanding(manifest, dossier)
        mutations: list[tuple[str, Any]] = []

        missing_format = copy.deepcopy(base)
        del missing_format["workflow"]["graph"]["nodes"][0]["format"]
        mutations.append(("missing format", missing_format))

        dangling_flow = copy.deepcopy(base)
        dangling_flow["workflow"]["graph"]["operations"][0]["consumes"] = [
            "node-missing"
        ]
        mutations.append(("dangling flow", dangling_flow))

        bad_derivation = copy.deepcopy(base)
        bad_derivation["mathematical_principles"]["derivation_steps"][0][
            "depends_on"
        ] = ["step:math-step-002"]
        mutations.append(("bad derivation", bad_derivation))

        bad_algorithm = copy.deepcopy(base)
        bad_algorithm["algorithmic_principles"]["ordered_steps"][0][
            "depends_on"
        ] = ["alg-step-002"]
        mutations.append(("bad algorithm", bad_algorithm))

        title_drift = copy.deepcopy(base)
        title_drift["executive_summary"]["conclusion_short"] = "漂移标题"
        mutations.append(("title drift", title_drift))

        for label, payload in mutations:
            with self.subTest(label=label), self.assertRaises(module.ContractError):
                module.create_understanding(payload)

    def test_graph_requires_role_correct_participation(self) -> None:
        manifest, dossier, _, _, _ = _verified_inputs()
        payload = _base_understanding(manifest, dossier)
        module.create_understanding(payload)
        payload["workflow"]["graph"]["operations"][1]["consumes"] = ["node-in"]
        with self.assertRaises(module.ContractError):
            module.create_understanding(payload)

    def test_source_bundle_source_and_dossier_are_all_or_none(self) -> None:
        manifest, dossier, source, bundle, dossier_path = _verified_inputs()
        payload = _base_understanding(manifest, dossier)
        with self.assertRaises(module.ContractError):
            module.create_understanding(payload, source_bundle=bundle)
        payload["source_binding"]["reading_dossier_digest"] = "0" * 64
        with self.assertRaises(module.ContractError):
            module.create_understanding(
                payload,
                source_bundle=bundle,
                source=source,
                dossier=dossier_path,
            )

    def test_live_registry_rejects_fabricated_provenance(self) -> None:
        manifest, dossier_data, source, bundle, dossier = _verified_inputs()
        base = _base_understanding(manifest, dossier_data)

        fabricated_id = copy.deepcopy(base)
        def replace_evidence_id(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "evidence_id" and item == "evidence-001":
                        value[key] = "evidence-fabricated"
                    elif key == "evidence_ids" and isinstance(item, list):
                        value[key] = [
                            "evidence-fabricated" if entry == "evidence-001" else entry
                            for entry in item
                        ]
                    else:
                        replace_evidence_id(item)
            elif isinstance(value, list):
                for item in value:
                    replace_evidence_id(item)
        replace_evidence_id(fabricated_id)

        fabricated_summary = copy.deepcopy(base)
        fabricated_summary["claims"][0]["evidence"][0]["summary"] = "fabricated"
        fabricated_locator = copy.deepcopy(base)
        fabricated_locator["claims"][0]["evidence"][0]["locator"] = "p.99 [0:1]"
        fabricated_domain_ref = copy.deepcopy(base)
        fabricated_domain_ref["contributions"][0]["domain_refs"][0] = "domain-fabricated"

        for label, payload in (
            ("evidence id", fabricated_id),
            ("summary", fabricated_summary),
            ("locator", fabricated_locator),
            ("domain ref", fabricated_domain_ref),
        ):
            with self.subTest(label=label), self.assertRaises(module.ContractError):
                module.create_understanding(
                    payload,
                    source_bundle=bundle,
                    source=source,
                    dossier=dossier,
                )

    def test_timestamp_offset_is_converted_to_utc_instant(self) -> None:
        manifest, dossier, _, _, _ = _verified_inputs()
        payload = _base_understanding(manifest, dossier)
        payload["generated_at"] = "2026-08-05T08:00:00+08:00"
        created = module.create_understanding(
            payload,
            generated_at=payload["generated_at"],
        )
        self.assertEqual(created["generated_at"], "2026-08-05T00:00:00Z")

    def test_genuine_math_not_applicable_example_validates_and_projects(self) -> None:
        _, _, source, bundle, dossier = _verified_inputs()
        example = json.loads(
            (EXAMPLES / "paper_understanding_math_not_applicable.example.json").read_text(
                encoding="utf-8"
            )
        )
        validated = module.validate_understanding(
            example,
            source_bundle_path=bundle,
            source_path=source,
            dossier_path=dossier,
        )
        self.assertEqual(validated["mathematical_principles"]["principles"], [])
        record = module.create_validation_record(
            validated,
            source_bundle=bundle,
            source=source,
            dossier=dossier,
        )
        projection = module.validate_note_input_projection(
            validated,
            record,
            source_bundle_path=bundle,
            source_path=source,
            dossier_path=dossier,
        )
        self.assertEqual(projection["mathematical_principles"]["status"], "not_applicable")
        paper_knowledge_note.validate_input(projection)

    def test_checked_examples_validate_and_map_remains_unprojectable(self) -> None:
        _, _, source, bundle, dossier = _verified_inputs()
        example = json.loads(
            (EXAMPLES / "paper_understanding.example.json").read_text(encoding="utf-8")
        )
        validated = module.validate_understanding(
            example,
            source_bundle_path=bundle,
            source_path=source,
            dossier_path=dossier,
        )
        record = module.create_validation_record(
            validated,
            source_bundle=bundle,
            source=source,
            dossier=dossier,
        )
        projection = module.validate_note_input_projection(
            validated,
            record,
            source_bundle_path=bundle,
            source_path=source,
            dossier_path=dossier,
        )
        normalized = paper_knowledge_note.validate_input(projection)
        self.assertEqual(normalized["understanding_binding"], projection["understanding_binding"])
        self.assertEqual(
            projection["workflow"]["graph"]["nodes"][0]["semantic_type"],
            "raw_input",
        )
        self.assertEqual(
            projection["mathematical_principles"]["derivation_steps"][1]["depends_on"],
            ["step:math-step-001"],
        )
        self.assertEqual(
            projection["algorithmic_principles"]["ordered_steps"][1]["depends_on"],
            ["alg-step-001"],
        )
        self.assertIn("workflow", projection["contributions"][0]["domain_refs"])

        map_example = json.loads(
            (EXAMPLES / "paper_understanding_invalid_projection.example.json").read_text(
                encoding="utf-8"
            )
        )
        structurally_valid = module.validate_understanding(map_example)
        with self.assertRaises(TypeError):
            module.validate_note_input_projection(structurally_valid, record)

    def test_projection_rejects_unverified_or_forged_validation_record(self) -> None:
        created, record, source, bundle, dossier = _create_verified()
        unverified = module.create_validation_record(created)
        self.assertFalse(unverified["source_binding_verified"])
        with self.assertRaises(module.ContractError):
            module.validate_note_input_projection(
                created,
                unverified,
                source_bundle_path=bundle,
                source_path=source,
                dossier_path=dossier,
            )

        forged_id = copy.deepcopy(record)
        forged_id["record_id"] = module.VALIDATION_PREFIX + "0" * 16
        with self.assertRaises(module.ContractError):
            module.validate_note_input_projection(
                created,
                forged_id,
                source_bundle_path=bundle,
                source_path=source,
                dossier_path=dossier,
            )

        forged_digest = copy.deepcopy(record)
        forged_digest["record_digest"] = "0" * 64
        with self.assertRaises(module.ContractError):
            module.validate_note_input_projection(
                created,
                forged_digest,
                source_bundle_path=bundle,
                source_path=source,
                dossier_path=dossier,
            )

    def test_projection_preconditions_and_unresolved_status_fail_closed(self) -> None:
        manifest, dossier_data, source, bundle, dossier = _verified_inputs()
        mutations: list[dict[str, Any]] = []
        empty_boundary = _base_understanding(manifest, dossier_data)
        empty_boundary["applicability"]["does_not_apply_when"] = []
        mutations.append(empty_boundary)
        empty_preconditions = _base_understanding(manifest, dossier_data)
        empty_preconditions["workflow"]["preconditions"] = []
        mutations.append(empty_preconditions)
        empty_checks = _base_understanding(manifest, dossier_data)
        empty_checks["workflow"]["steps"][0]["checks"] = []
        mutations.append(empty_checks)
        empty_flow = _base_understanding(manifest, dossier_data)
        empty_flow["workflow"]["data_flow"] = []
        mutations.append(empty_flow)
        unresolved_math = _base_understanding(manifest, dossier_data)
        unresolved_math["mathematical_principles"]["status"] = "unresolved"
        unresolved_math["mathematical_principles"]["evidence_ids"] = []
        unresolved_math["mathematical_principles"]["missing_information"] = [
            "缺少附录"
        ]
        mutations.append(unresolved_math)

        for payload in mutations:
            created = module.create_understanding(
                payload,
                source_bundle=bundle,
                source=source,
                dossier=dossier,
            )
            record = module.create_validation_record(
                created,
                source_bundle=bundle,
                source=source,
                dossier=dossier,
            )
            with self.assertRaises(module.ContractError):
                module.validate_note_input_projection(
                    created,
                    record,
                    source_bundle_path=bundle,
                    source_path=source,
                    dossier_path=dossier,
                )

    def test_project_command_is_opt_in_and_private(self) -> None:
        created, record, source, bundle, dossier = _create_verified()
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            input_path = workspace / "understanding.json"
            output_path = workspace / "projection.json"
            validation_path = workspace / "validation.json"
            input_path.write_text(json.dumps(created), encoding="utf-8")
            validation_path.write_text(json.dumps(record), encoding="utf-8")
            stdout = StringIO()
            with contextlib.redirect_stdout(stdout):
                code = module.main(
                    [
                        "project-note-input",
                        "--understanding",
                        str(input_path),
                        "--output",
                        str(output_path),
                        "--source-bundle",
                        bundle,
                        "--source",
                        source,
                        "--dossier",
                        dossier,
                        "--validation-record",
                        str(validation_path),
                    ]
                )
            self.assertEqual(code, 0)
            manifest = json.loads(stdout.getvalue())
            self.assertIsNone(manifest["shadow_path"])
            self.assertIsNone(manifest["audit_path"])
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)

    def test_project_command_preflight_prevents_partial_outputs(self) -> None:
        created, record, source, bundle, dossier = _create_verified()
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            input_path = workspace / "understanding.json"
            output_path = workspace / "projection.json"
            shadow_root = workspace / "shadow"
            audit_root = workspace / "audit"
            audit_root.mkdir()
            existing_audit = audit_root / output_path.name
            existing_audit.write_text("keep", encoding="utf-8")
            input_path.write_text(json.dumps(created), encoding="utf-8")
            validation_path = workspace / "validation.json"
            validation_path.write_text(json.dumps(record), encoding="utf-8")
            stderr = StringIO()
            with contextlib.redirect_stderr(stderr):
                code = module.main(
                    [
                        "project-note-input",
                        "--understanding",
                        str(input_path),
                        "--output",
                        str(output_path),
                        "--source-bundle",
                        bundle,
                        "--source",
                        source,
                        "--dossier",
                        dossier,
                        "--validation-record",
                        str(validation_path),
                        "--shadow-root",
                        str(shadow_root),
                        "--audit-root",
                        str(audit_root),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertFalse(output_path.exists())
            self.assertFalse((shadow_root / output_path.name).exists())
            self.assertEqual(existing_audit.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    from unittest import main

    main()
