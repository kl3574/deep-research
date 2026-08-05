#!/usr/bin/env python3
"""Focused semantic and mutation tests for the understanding evaluator."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest import TestCase

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parents[1]
SOURCE = EVAL_DIR / "fixtures" / "synthetic_wsr_paper.md"
RUBRIC = EVAL_DIR / "understanding_rubric.json"
EXAMPLE = (
    REPO_ROOT
    / "skills"
    / "learn-from-papers"
    / "examples"
    / "paper_understanding.example.json"
)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVALUATOR = _load_module("understanding_evaluator", EVAL_DIR / "understanding_evaluator.py")
PRODUCER = _load_module(
    "paper_understanding_for_semantic_eval",
    REPO_ROOT
    / "skills"
    / "learn-from-papers"
    / "scripts"
    / "paper_understanding.py",
)

SCOPE = {
    "assumptions": ["deterministic latent ODE", "Gaussian measurement noise"],
    "conditions": ["primary experiments at measurement noise through 20%"],
    "units": ["coefficient relative error", "2 s rollout NRMSE"],
    "exclusions": [
        "process noise",
        "hidden states",
        "irregular sampling",
        "noise above 20%",
        "long-time attractors",
    ],
}


def _claim(
    claim_id: str,
    statement: str,
    relation: str,
    status: str,
    locators: list[str],
) -> dict[str, Any]:
    evidence = [
        {
            "evidence_id": f"e-{claim_id}-{index:02d}",
            "summary": statement,
            "locator": locator,
        }
        for index, locator in enumerate(locators)
    ]
    return {
        "claim_id": claim_id,
        "hypothesis_id": f"hyp-{claim_id}",
        "target_id": f"target-{claim_id}",
        "statement": statement,
        "relation": relation,
        "nature": "source-stated",
        "scope": copy.deepcopy(SCOPE),
        "evidence": evidence,
        "evidence_ids": [row["evidence_id"] for row in evidence],
        "verifier_status": "passed",
        "confidence": "low" if status == "terminal" else "medium",
        "confidence_rationale": (
            "The source establishes that this question was not tested."
            if status == "terminal"
            else "The cited source locations directly bound this statement."
        ),
        "status": status,
    }


def _strong_draft() -> dict[str, Any]:
    draft = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    draft.pop("understanding_id", None)
    draft.pop("understanding_digest", None)
    source_text = SOURCE.read_text(encoding="utf-8")
    claims = [
        _claim(
            "c-measurement",
            "Evidence supports deterministic ODE recovery with Gaussian measurement noise only through 20%.",
            "supports",
            "answered",
            ["p. 2, §2.2, para 1", "p. 2, §2.3, para 3", "p. 3, Table 1"],
        ),
        _claim(
            "c-process",
            "Process-noise robustness is refuted by the controlling scope and failed pilot.",
            "refutes",
            "answered",
            ["p. 2, §2.3, para 3", "p. 3, Table 2"],
        ),
        _claim(
            "c-thirty",
            "Reliable recovery at 30% is refuted: correct support occurs in only 1/5 runs.",
            "refutes",
            "answered",
            ["p. 3, Table 1"],
        ),
        _claim(
            "c-long-time",
            "Long-time attractor preservation was not tested and has no evidence beyond two seconds.",
            "not_tested",
            "terminal",
            ["p. 4, §4.2, para 1"],
        ),
        _claim(
            "c-statistical",
            "Statistically indistinguishable seed performance was not tested because uncertainty is absent.",
            "not_tested",
            "terminal",
            ["p. 3, §3.2, para 1"],
        ),
        _claim(
            "c-reproduction",
            "The implementation is not fully reproducible because required settings are omitted.",
            "refutes",
            "answered",
            ["p. 5, §5.1, para 1", "p. 5, Supplement S1"],
        ),
        _claim(
            "c-private-details",
            "Exact values of the five random seeds and unavailable private assets cannot be recovered.",
            "not_tested",
            "terminal",
            ["p. 5, §5.1, para 1", "p. 5, Supplement S1"],
        ),
        _claim(
            "c-method",
            "The source states weak-form integration, least-squares fitting, and coefficient thresholding.",
            "supports",
            "answered",
            ["p. 2, §2, para 1", "Eq. (2)"],
        ),
        _claim(
            "c-covariance",
            "The reported OLS covariance is conditional on selected support and excludes selection uncertainty.",
            "qualifies",
            "answered",
            ["p. 2, §2.1, para 2"],
        ),
        _claim(
            "c-sign",
            "Equation (1)'s positive cubic sign is refuted by the experimental model using -0.5 x^3.",
            "refutes",
            "answered",
            ["Eq. (1)", "p. 5, Table 3", "p. 5, Appendix B"],
        ),
    ]
    claim_ids = [claim["claim_id"] for claim in claims]
    draft["generated_at"] = "2026-08-05T00:00:00Z"
    draft["source_binding"] = {
        "source_id": "synthetic_wsr_paper",
        "canonical_title": "Universal Weak-Form Sparse Recovery under Mixed Noise",
        "authors": ["Synthetic Authors"],
        "year": 2026,
        "venue": "Evaluator fixture",
        "stable_identifier": "local:synthetic_wsr_paper",
        "publication_status": "synthetic",
        "source_artifact_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "source_bundle_id": "paper-source-bundle-synthetic",
        "source_bundle_digest": "a" * 64,
        "reading_dossier_id": "reading-dossier-synthetic",
        "reading_dossier_digest": "b" * 64,
        "paper_card_ref": "PC-SYNTHETIC",
        "evidence_ledger_ref": "EL-SYNTHETIC",
        "agent_inferences_explicit": True,
        "reading_depth": "evidence",
        "access_level": "full_text",
        "verified_at": "2026-08-05T00:00:00Z",
    }
    draft["claims"] = claims
    draft["coverage"] = {
        "understood_claims": [
            {"claim_id": claim["claim_id"], "reason": "source-rooted answer"}
            for claim in claims
            if claim["status"] == "answered"
        ],
        "terminal_claims": [
            {"claim_id": claim["claim_id"], "reason": "source does not report this result"}
            for claim in claims
            if claim["status"] == "terminal"
        ],
    }
    draft["executive_summary"] = {
        "applicability_short": "deterministic measurement-noise recovery through 20%",
        "conclusion_short": "limited support; broader claims unsupported",
        "summary": (
            "Evidence is limited to deterministic dynamics with Gaussian measurement noise through 20%; "
            "mixed-noise, process-noise, 30%, long-time, and statistical claims are unsupported."
        ),
        "claim_ids": claim_ids,
    }
    draft["research_retrieval_title"] = (
        "适用：deterministic measurement-noise recovery through 20%"
        "｜结论：limited support; broader claims unsupported"
    )
    draft["applicability"] = {
        "status": "answered",
        "rationale": "The controlling scope limits primary evidence to deterministic dynamics and measurement noise through 20%.",
        "evidence_ids": ["e-c-measurement-00", "e-c-measurement-01", "e-c-measurement-02"],
        "missing_information": [],
        "primary_use_case": "Sparse recovery for deterministic ODE trajectories with post-integration Gaussian measurement noise.",
        "applies_when": ["Regular sampling and measurement noise no greater than 20%."],
        "does_not_apply_when": [
            "Universal mixed-noise robustness is unsupported.",
            "Process noise is unsupported and the pilot indicates estimator misspecification.",
            "Hidden-state systems and irregular sampling are excluded.",
            "Reliable recovery at 30% is unsupported (1/5 correct support).",
            "Long-time attractors and stochastic dynamics are not tested.",
        ],
        "claim_ids": ["c-measurement", "c-process", "c-thirty", "c-long-time"],
    }
    draft["workflow"] = {
        "status": "answered",
        "rationale": "The source supports a graph from sampled trajectories to a thresholded equation and two-second rollout metrics.",
        "evidence_ids": ["e-c-method-00", "e-c-method-01", "e-c-measurement-00", "e-c-measurement-02"],
        "missing_information": ["Serialization format is not reported; semantic numeric formats are recorded."],
        "inputs": ["observed trajectories", "sample times", "compact test functions", "candidate library"],
        "preconditions": ["deterministic latent ODE", "regular sampling"],
        "steps": [
            {"step_id": "wf-integrate", "action": "Integrate trajectories against compact test functions.", "output": "weak-form targets", "checks": ["test support is compact"]},
            {"step_id": "wf-library", "action": "Evaluate library {1, x, x^2, x^3}.", "output": "design matrix G", "checks": ["column order retained"]},
            {"step_id": "wf-solve", "action": "Solve least-squares coefficients.", "output": "theta", "checks": ["Eq. (2)"]},
            {"step_id": "wf-threshold", "action": "Zero coefficients below lambda.", "output": "thresholded model", "checks": ["support recorded"]},
            {"step_id": "wf-evaluate", "action": "Evaluate two-second rollout NRMSE.", "output": "benchmark metrics", "checks": ["noise level retained"]},
        ],
        "outputs": ["identified equation", "2 s rollout NRMSE table"],
        "data_flow": [
            "trajectories + times + test functions -> weak-form targets",
            "trajectories + library -> design matrix",
            "targets + design matrix -> OLS coefficients",
            "coefficients -> thresholded model",
            "thresholded model -> identified equation",
            "thresholded model -> rollout metrics",
        ],
        "graph": {
            "nodes": [
                {"node_id": "n-trajectories", "kind": "input", "description": "sampled observed trajectories", "semantic_type": "trajectory_samples", "representation": "numeric tensor", "format": "float64 array", "shape": "trajectory[50,time]", "unit": "state x"},
                {"node_id": "n-times", "kind": "input", "description": "regular sample times", "semantic_type": "sample_time", "representation": "numeric vector", "format": "float64 vector", "shape": "time[T]", "unit": "seconds"},
                {"node_id": "n-tests", "kind": "input", "description": "compact polynomial test functions", "semantic_type": "test_functions", "representation": "symbolic set", "format": "polynomial set", "shape": "functions[K]", "unit": "none"},
                {"node_id": "n-library", "kind": "input", "description": "candidate library {1, x, x^2, x^3}", "semantic_type": "feature_library", "representation": "symbolic vector", "format": "symbolic feature vector", "shape": "features[4]", "unit": "mixed"},
                {"node_id": "n-targets", "kind": "intermediate", "description": "weak-form integral targets b", "semantic_type": "weak_form_targets", "representation": "numeric vector", "format": "float64 vector", "shape": "b[K]", "unit": "integrated state"},
                {"node_id": "n-design", "kind": "intermediate", "description": "library design matrix G", "semantic_type": "design_matrix", "representation": "numeric matrix", "format": "float64 matrix", "shape": "G[K,4]", "unit": "mixed"},
                {"node_id": "n-ols", "kind": "intermediate", "description": "least-squares coefficients theta", "semantic_type": "coefficient_vector", "representation": "numeric vector", "format": "float64 vector", "shape": "theta[4]", "unit": "coefficient"},
                {"node_id": "n-thresholded", "kind": "intermediate", "description": "thresholded coefficient support", "semantic_type": "sparse_model", "representation": "sparse vector", "format": "sparse coefficient vector", "shape": "theta[4]", "unit": "coefficient"},
                {"node_id": "n-equation", "kind": "output", "description": "identified governing equation", "semantic_type": "identified_equation", "representation": "coefficient table", "format": "term-coefficient table", "shape": "terms[4]", "unit": "coefficient"},
                {"node_id": "n-metrics", "kind": "output", "description": "two-second rollout NRMSE metrics", "semantic_type": "rollout_metrics", "representation": "numeric table", "format": "noise-metric table", "shape": "noise_levels[4]", "unit": "dimensionless"},
            ],
            "operations": [
                {"operation_id": "op-integrate", "operation": "weak-form integrate", "consumes": ["n-trajectories", "n-times", "n-tests"], "produces": ["n-targets"]},
                {"operation_id": "op-library", "operation": "evaluate library design matrix", "consumes": ["n-trajectories", "n-library"], "produces": ["n-design"]},
                {"operation_id": "op-solve", "operation": "least-squares argmin", "consumes": ["n-targets", "n-design"], "produces": ["n-ols"]},
                {"operation_id": "op-threshold", "operation": "threshold coefficients by lambda", "consumes": ["n-ols"], "produces": ["n-thresholded"]},
                {"operation_id": "op-emit", "operation": "emit identified equation", "consumes": ["n-thresholded"], "produces": ["n-equation"]},
                {"operation_id": "op-evaluate", "operation": "evaluate two-second rollout NRMSE", "consumes": ["n-thresholded"], "produces": ["n-metrics"]},
            ],
        },
    }
    draft["mathematical_principles"] = {
        "status": "answered",
        "rationale": "The weak-form regression and threshold rule are source-stated; covariance limits are retained.",
        "evidence_ids": ["e-c-method-00", "e-c-method-01", "e-c-covariance-00"],
        "missing_information": [],
        "assumptions": [
            "deterministic latent ODE dynamics",
            "Gaussian measurement noise is added after integration",
            "candidate library {1, x, x^2, x^3}",
            "OLS covariance is conditional on the selected support",
            "selection uncertainty is excluded",
        ],
        "derivation_steps": [
            {"step_id": "m-integrate", "statement": "Integrate the deterministic dynamics against compact test functions to obtain weak-form targets.", "depends_on": ["assumption:deterministic latent ODE dynamics", "assumption:Gaussian measurement noise is added after integration"], "origin": "source_stated", "locator": "p. 2, §2, para 1", "evidence_ids": ["e-c-method-00"]},
            {"step_id": "m-design", "statement": "Evaluate the library to form design matrix G and target b.", "depends_on": ["step:m-integrate", "assumption:candidate library {1, x, x^2, x^3}"], "origin": "agent_reconstructed", "locator": "p. 2, §2, para 1", "evidence_ids": ["e-c-method-00"]},
            {"step_id": "m-ols", "statement": "Solve theta = argmin ||G theta - b||_2^2 by least squares.", "depends_on": ["step:m-design"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]},
            {"step_id": "m-threshold", "statement": "Apply lambda thresholding to define the sparse support.", "depends_on": ["step:m-ols"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]},
            {"step_id": "m-covariance", "statement": "Interpret covariance only conditional on selected support, excluding selection uncertainty.", "depends_on": ["step:m-ols", "assumption:OLS covariance is conditional on the selected support", "assumption:selection uncertainty is excluded"], "origin": "source_stated", "locator": "p. 2, §2.1, para 2", "evidence_ids": ["e-c-covariance-00"]},
        ],
        "results": ["weak-form regression system", "thresholded support", "conditional covariance"],
        "principles": [
            {"principle_id": "principle-threshold", "statement": "Least-squares coefficients are thresholded by lambda.", "latex": "\\theta_{k+1}=\\arg\\min_\\theta ||G\\theta-b||_2^2", "symbols": ["G", "b", "theta", "lambda"], "assumptions": ["candidate library {1, x, x^2, x^3}"], "derivation_steps": [{"step_id": "mp-solve", "statement": "Solve least squares, then zero entries below lambda.", "depends_on": ["assumption:candidate library {1, x, x^2, x^3}"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]}], "results": ["thresholded support"], "origin": "source_stated", "claim_ids": ["c-method"], "locator": "Eq. (2)"}
        ],
    }
    missing_details = [
        "Quadrature node count (QUADRATURE_NODES) is unspecified.",
        "Lambda grid (LAMBDA_GRID) is unspecified.",
        "Solver tolerance (SOLVER_TOL) is unspecified.",
        "Five random seeds (SEEDS) are not reported.",
        "Tie-breaking rule is not reported.",
    ]
    top_steps = [
        {"step_id": "a-integrate", "action": "Integrate trajectories against compact test functions for the weak form.", "depends_on": [], "consumes": ["trajectories", "times", "test functions"], "produces": ["b"], "origin": "source_stated", "locator": "p. 2, §2, para 1", "evidence_ids": ["e-c-method-00"]},
        {"step_id": "a-library", "action": "Build library design matrix G from {1, x, x^2, x^3}.", "depends_on": ["a-integrate"], "consumes": ["trajectories", "library"], "produces": ["G"], "origin": "source_stated", "locator": "p. 2, §2, para 1", "evidence_ids": ["e-c-method-00"]},
        {"step_id": "a-solve", "action": "Solve the least-squares argmin for theta.", "depends_on": ["a-library"], "consumes": ["G", "b"], "produces": ["theta"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]},
        {"step_id": "a-threshold", "action": "Threshold coefficients with |theta_j| < lambda.", "depends_on": ["a-solve"], "consumes": ["theta", "lambda"], "produces": ["sparse support"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]},
        {"step_id": "a-evaluate", "action": "Evaluate correct support and two-second rollout NRMSE by measurement-noise level.", "depends_on": ["a-threshold"], "consumes": ["sparse support"], "produces": ["metrics"], "origin": "source_stated", "locator": "p. 3, Table 1", "evidence_ids": ["e-c-measurement-02"]},
    ]
    draft["algorithmic_principles"] = {
        "status": "answered",
        "rationale": "The core order is reported, while stopping, tie-breaking, and reproduction parameters remain unresolved.",
        "evidence_ids": ["e-c-method-00", "e-c-method-01", "e-c-measurement-02", "e-c-reproduction-00", "e-c-reproduction-01"],
        "missing_information": missing_details,
        "objective": "Identify a sparse governing equation without exceeding the paper's supported scope.",
        "state_variables": ["G", "b", "theta", "lambda", "selected support"],
        "ordered_steps": top_steps,
        "invariants": [
            "Library order remains {1, x, x^2, x^3}.",
            "Coefficients satisfying |theta_j| < lambda are zeroed.",
            "Primary claims remain limited to measurement noise through 20%.",
        ],
        "failure_modes": [
            "No errors-in-variables correction.",
            "Process-noise misspecification.",
            "Selection uncertainty is excluded.",
            *missing_details,
        ],
        "algorithms": [
            {"algorithm_id": "uwsr-core", "name": "UWSR weak-form thresholded least squares", "inputs": ["trajectories", "times", "test functions", "library"], "outputs": ["sparse equation"], "initialization": "Use the stated library; numerical initialization is not reported.", "ordered_steps": copy.deepcopy(top_steps[:4]), "update_rule": "Solve least squares and zero theta_j when |theta_j| < lambda.", "stopping_condition": "Threshold-grid termination and tie-breaking stopping conditions are not reported and remain unresolved.", "complexity": "Not reported.", "numerical_risks": ["errors-in-variables bias", "selection uncertainty", "process-noise misspecification"], "claim_ids": ["c-method", "c-measurement", "c-reproduction"], "locator": "p. 2, §2, para 1", "origin": "source_stated"}
        ],
    }
    conclusion_claims = ["c-measurement", "c-process", "c-thirty", "c-long-time", "c-statistical", "c-reproduction", "c-private-details"]
    draft["conclusion"] = {
        "status": "answered",
        "rationale": "The controlling scope, failed process pilot, 1/5 recovery at 30%, and absent long-time/statistical analyses bound the result.",
        "evidence_ids": ["e-c-measurement-01", "e-c-measurement-02", "e-c-process-01", "e-c-long-time-00", "e-c-statistical-00", "e-c-reproduction-00"],
        "missing_information": ["Long-time and statistical evidence is not reported."],
        "statement": "Support is limited to deterministic dynamics with Gaussian measurement noise through 20%; process-noise, 30%, long-time, and statistical claims are unsupported.",
        "confidence": "medium",
        "confidence_rationale": "Direct evidence supports the bounded statement; broader statistically indistinguishable and long-time claims are not tested.",
        "claim_ids": conclusion_claims,
    }
    draft["contributions"] = [
        {"contribution_id": "contribution-bounded-understanding", "statement": "Reconstructs the weak-form algorithm while retaining its evidence-bounded scope and unresolved details.", "claim_ids": ["c-measurement", "c-method", "c-reproduction"], "evidence_ids": ["e-c-measurement-01", "e-c-method-00", "e-c-reproduction-01"], "domain_refs": ["applicability", "workflow", "mathematical_principles", "algorithmic_principles", "conclusion", "wf-solve", "n-design", "principle-threshold", "uwsr-core"]}
    ]
    return draft


def _materialize(draft: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(draft)
    value.pop("understanding_id", None)
    value.pop("understanding_digest", None)
    executive = value["executive_summary"]
    value["research_retrieval_title"] = (
        f"适用：{executive['applicability_short']}"
        f"｜结论：{executive['conclusion_short']}"
    )
    return PRODUCER.create_understanding(value, generated_at="2026-08-05T00:00:00Z")


def _chinese_semantic_variant(candidate: dict[str, Any]) -> dict[str, Any]:
    """Rewrite semantic content in Chinese while preserving source bindings."""
    draft = copy.deepcopy(candidate)
    executive = draft["executive_summary"]
    executive.update(
        {
            "applicability_short": "确定性系统中观测噪声不超过20%的稀疏恢复",
            "conclusion_short": "仅有边界内支持；更广泛主张不支持",
            "summary": (
                "证据仅适用于确定性动力学：积分后加入高斯观测噪声且不超过20%。"
                "混合噪声、过程噪声、30%、长期吸引子及统计学主张不支持。"
            ),
        }
    )
    applicability = draft["applicability"]
    applicability.update(
        {
            "rationale": "控制性范围只覆盖确定性动力学与不超过20%的观测噪声。",
            "primary_use_case": "确定性常微分方程轨迹在积分后加入高斯观测噪声时的稀疏恢复。",
            "applies_when": ["规则采样，且测量噪声不高于20%。"],
            "does_not_apply_when": [
                "混合噪声的普适稳健性不支持。",
                "过程噪声未获支持，小规模试验显示估计器错设。",
                "隐状态系统与不规则采样被排除。",
                "30%噪声下的可靠恢复不支持，仅1/5成功。",
                "长时间吸引子与随机动力学未检验。",
            ],
        }
    )

    workflow = draft["workflow"]
    workflow.update(
        {
            "rationale": "源文支持从采样轨迹到阈值化方程与两秒滚动预测指标的流程图。",
            "missing_information": ["文件序列化规格未报告；此处仅记录语义数值格式。"],
            "inputs": ["观测轨迹", "采样时间", "紧支撑检验函数", "候选函数库"],
            "preconditions": ["确定性潜在常微分方程", "规则采样"],
            "outputs": ["识别方程", "两秒滚动预测NRMSE表"],
            "data_flow": [
                "轨迹+时间+检验函数 -> 弱形式目标",
                "轨迹+函数库 -> 设计矩阵",
                "目标+设计矩阵 -> 最小二乘系数",
                "系数 -> 阈值化模型",
                "阈值化模型 -> 识别方程",
                "阈值化模型 -> 滚动预测指标",
            ],
        }
    )
    workflow["steps"] = [
        {"step_id": "wf-01", "action": "用紧支撑检验函数对轨迹积分。", "output": "弱形式目标", "checks": ["检验函数具有紧支撑"]},
        {"step_id": "wf-02", "action": "计算候选函数库{1,x,x^2,x^3}。", "output": "设计矩阵", "checks": ["保留列顺序"]},
        {"step_id": "wf-03", "action": "求解最小二乘系数。", "output": "系数向量", "checks": ["对应公式(2)"]},
        {"step_id": "wf-04", "action": "将低于λ阈值的系数置零。", "output": "稀疏支撑集", "checks": ["记录支撑集"]},
        {"step_id": "wf-05", "action": "评估两秒滚动预测NRMSE。", "output": "基准指标", "checks": ["保留噪声水平"]},
    ]
    node_ids = {
        old["node_id"]: f"node-{index:02d}"
        for index, old in enumerate(workflow["graph"]["nodes"], start=1)
    }
    node_semantics = [
        ("采样观测轨迹", "轨迹采样", "数值张量", "浮点数组"),
        ("规则采样时间", "采样时间", "数值向量", "浮点向量"),
        ("紧支撑多项式检验函数", "检验函数", "符号集合", "多项式集合"),
        ("候选函数库{1,x,x^2,x^3}", "候选函数库", "符号向量", "特征向量"),
        ("弱形式积分目标", "弱形式目标", "数值向量", "浮点向量"),
        ("函数库设计矩阵", "设计矩阵", "数值矩阵", "浮点矩阵"),
        ("最小二乘系数", "系数向量", "数值向量", "浮点向量"),
        ("阈值化系数支撑集", "稀疏模型", "稀疏向量", "稀疏系数向量"),
        ("识别出的控制方程", "识别方程", "系数表", "项-系数表"),
        ("两秒滚动预测NRMSE指标", "滚动预测指标", "数值表", "噪声-指标表"),
    ]
    for node, (description, semantic_type, representation, format_name) in zip(
        workflow["graph"]["nodes"], node_semantics, strict=True
    ):
        node["node_id"] = node_ids[node["node_id"]]
        node["description"] = description
        node["semantic_type"] = semantic_type
        node["representation"] = representation
        node["format"] = format_name
    operation_names = ["弱形式积分", "计算函数库设计矩阵", "最小二乘最小化", "按λ执行阈值化", "输出识别方程", "评估两秒滚动预测NRMSE"]
    for index, (operation, name) in enumerate(
        zip(workflow["graph"]["operations"], operation_names, strict=True), start=1
    ):
        operation["operation_id"] = f"operation-{index:02d}"
        operation["operation"] = name
        operation["consumes"] = [node_ids[item] for item in operation["consumes"]]
        operation["produces"] = [node_ids[item] for item in operation["produces"]]

    math = draft["mathematical_principles"]
    assumptions = [
        "确定性潜在常微分方程动力学",
        "积分后加入高斯观测噪声",
        "候选函数库{1,x,x^2,x^3}",
        "普通最小二乘协方差以所选支撑集为条件",
        "排除模型选择不确定性",
    ]
    math.update(
        {
            "rationale": "弱形式回归和阈值规则来自原文，并保留协方差的条件性限制。",
            "assumptions": assumptions,
            "results": ["弱形式回归系统", "阈值化支撑集", "条件协方差"],
        }
    )
    math["derivation_steps"] = [
        {"step_id": "math-01", "statement": "用紧支撑检验函数对确定性动力学积分，得到弱形式目标。", "depends_on": [f"assumption:{assumptions[0]}", f"assumption:{assumptions[1]}"], "origin": "source_stated", "locator": "p. 2, §2, para 1", "evidence_ids": ["e-c-method-00"]},
        {"step_id": "math-02", "statement": "计算候选函数库，构造设计矩阵G与目标b。", "depends_on": ["step:math-01", f"assumption:{assumptions[2]}"], "origin": "agent_reconstructed", "locator": "p. 2, §2, para 1", "evidence_ids": ["e-c-method-00"]},
        {"step_id": "math-03", "statement": "求解二范数残差平方的最小二乘最小化问题。", "depends_on": ["step:math-02"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]},
        {"step_id": "math-04", "statement": "按λ阈值将小系数置零，得到稀疏支撑集。", "depends_on": ["step:math-03"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]},
        {"step_id": "math-05", "statement": "协方差只以所选支撑集为条件，不包含选择不确定性。", "depends_on": ["step:math-03", f"assumption:{assumptions[3]}", f"assumption:{assumptions[4]}"], "origin": "source_stated", "locator": "p. 2, §2.1, para 2", "evidence_ids": ["e-c-covariance-00"]},
    ]
    principle = math["principles"][0]
    principle.update(
        {
            "statement": "最小二乘系数按λ执行阈值化。",
            "assumptions": [assumptions[2]],
            "results": ["阈值化支撑集"],
            "derivation_steps": [
                {"step_id": "principle-01", "statement": "先求解最小二乘，再将低于λ的项置零。", "depends_on": [f"assumption:{assumptions[2]}"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]}
            ],
        }
    )

    algorithm = draft["algorithmic_principles"]
    missing = [
        "求积节点数未指定。",
        "λ网格未指定。",
        "求解器容差未指定。",
        "五个随机种子未报告。",
        "平局处理规则未报告。",
    ]
    top_steps = [
        {"step_id": "algorithm-step-01", "action": "用紧支撑检验函数对轨迹做弱形式积分。", "depends_on": [], "consumes": ["轨迹", "时间", "检验函数"], "produces": ["目标向量"], "origin": "source_stated", "locator": "p. 2, §2, para 1", "evidence_ids": ["e-c-method-00"]},
        {"step_id": "algorithm-step-02", "action": "用候选函数库{1,x,x^2,x^3}构造设计矩阵。", "depends_on": ["algorithm-step-01"], "consumes": ["轨迹", "函数库"], "produces": ["设计矩阵"], "origin": "source_stated", "locator": "p. 2, §2, para 1", "evidence_ids": ["e-c-method-00"]},
        {"step_id": "algorithm-step-03", "action": "求解最小二乘最小化问题得到系数。", "depends_on": ["algorithm-step-02"], "consumes": ["设计矩阵", "目标向量"], "produces": ["系数向量"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]},
        {"step_id": "algorithm-step-04", "action": "将绝对值低于λ阈值的系数置零。", "depends_on": ["algorithm-step-03"], "consumes": ["系数向量", "λ"], "produces": ["稀疏支撑集"], "origin": "source_stated", "locator": "Eq. (2)", "evidence_ids": ["e-c-method-01"]},
        {"step_id": "algorithm-step-05", "action": "按观测噪声水平评估正确支撑集与两秒滚动预测NRMSE。", "depends_on": ["algorithm-step-04"], "consumes": ["稀疏支撑集"], "produces": ["指标"], "origin": "source_stated", "locator": "p. 3, Table 1", "evidence_ids": ["e-c-measurement-02"]},
    ]
    algorithm.update(
        {
            "rationale": "核心顺序已报告，但停止、平局处理与复现参数仍未解决。",
            "missing_information": missing,
            "objective": "在不超出论文支持范围的条件下识别稀疏控制方程。",
            "state_variables": ["设计矩阵", "目标向量", "系数", "λ", "所选支撑集"],
            "ordered_steps": top_steps,
            "invariants": [
                "函数库{1,x,x^2,x^3}的顺序保持不变。",
                "低于阈值的系数必须置零。",
                "主要主张始终限于不超过20%的观测噪声。",
            ],
            "failure_modes": ["未做误差变量校正。", "过程噪声下估计器错设。", "排除选择不确定性。", *missing],
        }
    )
    item = algorithm["algorithms"][0]
    item.update(
        {
            "name": "弱形式阈值最小二乘",
            "inputs": ["轨迹", "时间", "检验函数", "函数库"],
            "outputs": ["稀疏方程"],
            "initialization": "使用给定函数库；数值初始化未报告。",
            "ordered_steps": copy.deepcopy(top_steps[:4]),
            "update_rule": "求解最小二乘，并将低于λ阈值的系数置零。",
            "stopping_condition": "阈值网格的停止条件和平局处理未报告，仍未解决。",
            "complexity": "未报告。",
            "numerical_risks": ["误差变量偏差", "选择不确定性", "过程噪声错设"],
        }
    )

    claim_statements = {
        "c-measurement": "证据仅支持确定性常微分方程在不超过20%高斯观测噪声下的恢复。",
        "c-process": "控制性范围与失败的小规模试验否定了过程噪声稳健性。",
        "c-thirty": "30%噪声下的可靠恢复被否定：仅1/5获得正确支撑集。",
        "c-long-time": "长期吸引子保持未检验，两秒以外无证据。",
        "c-statistical": "种子间表现统计上不可区分的主张未检验，因为未报告不确定性。",
        "c-reproduction": "必需设置被省略，所以实现无法完整复现。",
        "c-private-details": "五个随机种子的精确值与不可用的私有资产无法验证。",
        "c-method": "源文说明了弱形式积分、最小二乘拟合和系数阈值化。",
        "c-covariance": "所报告的普通最小二乘协方差以所选支撑集为条件，不包含选择不确定性。",
        "c-sign": "公式(1)的正三次项符号被实验模型中的-0.5x^3否定。",
    }
    for claim in draft["claims"]:
        statement = claim_statements[claim["claim_id"]]
        claim["statement"] = statement
        claim["confidence_rationale"] = (
            "源文明确显示该问题未检验。"
            if claim["status"] == "terminal"
            else "所列源文位置直接限定了该陈述。"
        )
        claim["scope"] = {
            "assumptions": ["确定性潜在常微分方程", "高斯观测噪声"],
            "conditions": ["主要实验中观测噪声不超过20%"],
            "units": ["系数相对误差", "两秒滚动预测NRMSE"],
            "exclusions": ["过程噪声", "隐状态", "不规则采样", "超过20%噪声", "长期吸引子"],
        }
        for evidence in claim["evidence"]:
            evidence["summary"] = statement

    conclusion = draft["conclusion"]
    conclusion.update(
        {
            "rationale": "控制性范围、失败的过程噪声试验、30%时1/5恢复，以及缺失的长期和统计学分析限定了结论。",
            "missing_information": ["长时间与统计学证据未报告。"],
            "statement": "支持范围仅限于确定性动力学中不超过20%的高斯观测噪声；过程噪声、30%、长期和统计学主张不支持。",
            "confidence_rationale": "直接证据支持边界内陈述；统计上不可区分与长期主张未检验。",
        }
    )
    draft["contributions"][0]["statement"] = "在保留证据边界与未解决细节的同时，重建弱形式算法。"
    draft["contributions"][0]["domain_refs"] = [
        "applicability",
        "workflow",
        "mathematical_principles",
        "algorithmic_principles",
        "conclusion",
        "wf-03",
        node_ids["n-design"],
        "principle-threshold",
        "uwsr-core",
    ]
    return _materialize(draft)


class PaperUnderstandingSemanticEvaluationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
        cls.source_text = SOURCE.read_text(encoding="utf-8")
        cls.strong = _materialize(_strong_draft())

    def evaluate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return EVALUATOR.evaluate_understanding(
            candidate,
            self.rubric,
            source_text=self.source_text,
        )

    @staticmethod
    def gate(result: dict[str, Any], name: str) -> dict[str, Any]:
        return next(
            gate
            for gate in result["semantic_evaluation"]["hard_gates"]
            if gate["name"] == name
        )

    @staticmethod
    def dimension_check(
        result: dict[str, Any], dimension: str, name: str
    ) -> dict[str, Any]:
        return next(
            check
            for check in result["semantic_evaluation"]["dimensions"][dimension]["checks"]
            if check["name"] == name
        )

    def test_strong_understanding_passes_schema_and_semantics(self) -> None:
        result = self.evaluate(self.strong)
        self.assertTrue(result["schema_validation"]["passed"])
        self.assertTrue(result["semantic_evaluation"]["passed"])
        self.assertTrue(result["overall"]["passed"])
        self.assertEqual(len(result["semantic_evaluation"]["dimensions"]), 10)

    def test_chinese_semantic_equivalent_passes_without_title_gold_sentence(self) -> None:
        candidate = _chinese_semantic_variant(self.strong)
        result = self.evaluate(candidate)
        self.assertTrue(result["schema_validation"]["passed"])
        self.assertTrue(result["semantic_evaluation"]["passed"])
        self.assertTrue(result["overall"]["passed"])
        self.assertNotIn("limited support", candidate["research_retrieval_title"])

    def test_schema_validity_is_reported_separately_from_semantic_quality(self) -> None:
        candidate = copy.deepcopy(self.strong)
        candidate.pop("understanding_digest")
        result = self.evaluate(candidate)
        self.assertFalse(result["schema_validation"]["passed"])
        self.assertTrue(result["semantic_evaluation"]["passed"])
        self.assertFalse(result["overall"]["passed"])

    def test_each_critical_overclaim_trips_its_named_hard_gate(self) -> None:
        mutations = {
            "mixed_noise_overclaim": "The method is universally robust under mixed noise.",
            "process_noise_overclaim": "The method is robust under process noise.",
            "thirty_percent_overclaim": "Recovery is reliable at 30% noise.",
            "long_time_overclaim": "The method preserves long-time attractors.",
            "statistical_overclaim": "Seed performance is statistically indistinguishable.",
        }
        for gate_name, statement in mutations.items():
            with self.subTest(gate=gate_name):
                draft = copy.deepcopy(self.strong)
                draft["conclusion"]["statement"] = statement
                result = self.evaluate(_materialize(draft))
                self.assertTrue(result["schema_validation"]["passed"])
                self.assertFalse(self.gate(result, gate_name)["passed"])
                self.assertFalse(result["semantic_evaluation"]["passed"])

    def test_placeholder_or_unbound_io_format_fails_hard_gate(self) -> None:
        for format_value in ("unspecified", "未报告"):
            with self.subTest(format=format_value):
                draft = copy.deepcopy(self.strong)
                output = next(
                    node
                    for node in draft["workflow"]["graph"]["nodes"]
                    if node["kind"] == "output"
                )
                output["format"] = format_value
                result = self.evaluate(_materialize(draft))
                self.assertTrue(result["schema_validation"]["passed"])
                self.assertFalse(self.gate(result, "io_format_present")["passed"])

        candidate = copy.deepcopy(self.strong)
        output = next(
            node
            for node in candidate["workflow"]["graph"]["nodes"]
            if node["kind"] == "output"
        )
        output["format"] = ""
        result = self.evaluate(candidate)
        self.assertFalse(self.gate(result, "io_format_present")["passed"])

    def test_explicit_node_bound_unreported_format_is_accepted(self) -> None:
        draft = copy.deepcopy(self.strong)
        output = next(
            node for node in draft["workflow"]["graph"]["nodes"] if node["kind"] == "output"
        )
        output["format"] = "未报告"
        draft["workflow"]["missing_information"].append(
            f"节点 {output['node_id']} 的文件格式未报告。"
        )
        result = self.evaluate(_materialize(draft))
        self.assertTrue(result["schema_validation"]["passed"])
        self.assertTrue(self.gate(result, "io_format_present")["passed"])
        self.assertTrue(result["semantic_evaluation"]["passed"])

    def test_fabricated_unreported_values_fail_hard_gate(self) -> None:
        draft = copy.deepcopy(self.strong)
        draft["algorithmic_principles"]["missing_information"] = [
            "Quadrature node count = 64; lambda grid = [0.01, 0.1]; solver tolerance = 1e-8; "
            "random seeds are [1, 2, 3, 4, 5]; ties are broken by the smallest lambda."
        ]
        result = self.evaluate(_materialize(draft))
        self.assertTrue(result["schema_validation"]["passed"])
        self.assertFalse(
            self.gate(result, "unreported_details_not_fabricated")["passed"]
        )

    def test_solver_tolerance_missing_detail_morphology_equivalents_pass(self) -> None:
        variants = [
            "Solver tolerances are not reported.",
            "ODE solver absolute and relative tolerances are not reported.",
            "求解器绝对容差未报告。",
            "求解器相对容差未说明。",
            "绝对与相对容差未报告。",
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                draft = copy.deepcopy(self.strong)
                algorithm = draft["algorithmic_principles"]
                for field in ("missing_information", "failure_modes"):
                    algorithm[field] = [
                        variant if "Solver tolerance" in item else item
                        for item in algorithm[field]
                    ]
                result = self.evaluate(_materialize(draft))
                self.assertTrue(
                    self.gate(result, "unreported_details_not_fabricated")["passed"]
                )
                self.assertTrue(result["semantic_evaluation"]["passed"])

    def test_semantically_drifting_but_formula_valid_title_fails(self) -> None:
        draft = copy.deepcopy(self.strong)
        draft["executive_summary"]["applicability_short"] = "all mixed-noise systems"
        draft["executive_summary"]["conclusion_short"] = "universal recovery is supported"
        result = self.evaluate(_materialize(draft))
        self.assertTrue(result["schema_validation"]["passed"])
        self.assertFalse(self.gate(result, "pyramid_title_no_drift")["passed"])

    def test_schema_valid_shallow_structure_fails_depth_gate(self) -> None:
        draft = copy.deepcopy(self.strong)
        draft["workflow"]["steps"] = draft["workflow"]["steps"][:1]
        draft["workflow"]["data_flow"] = ["input -> output"]
        draft["workflow"]["graph"] = {
            "nodes": [
                {"node_id": "shallow-in", "kind": "input", "description": "trajectory input", "semantic_type": "input", "representation": "array", "format": "float array", "shape": "samples[N]", "unit": "state"},
                {"node_id": "shallow-out", "kind": "output", "description": "model output", "semantic_type": "output", "representation": "table", "format": "coefficient table", "shape": "terms[4]", "unit": "coefficient"},
            ],
            "operations": [
                {"operation_id": "shallow-op", "operation": "fit", "consumes": ["shallow-in"], "produces": ["shallow-out"]}
            ],
        }
        draft["mathematical_principles"]["derivation_steps"] = draft["mathematical_principles"]["derivation_steps"][:1]
        draft["algorithmic_principles"]["ordered_steps"] = draft["algorithmic_principles"]["ordered_steps"][:1]
        draft["algorithmic_principles"]["algorithms"][0]["ordered_steps"] = draft["algorithmic_principles"]["algorithms"][0]["ordered_steps"][:1]
        draft["contributions"][0]["domain_refs"] = [
            "applicability",
            "workflow",
            "mathematical_principles",
            "algorithmic_principles",
            "conclusion",
        ]
        result = self.evaluate(_materialize(draft))
        self.assertTrue(result["schema_validation"]["passed"])
        self.assertFalse(self.gate(result, "structured_artifact_depth")["passed"])
        self.assertFalse(result["semantic_evaluation"]["passed"])

    def test_four_algorithm_steps_satisfy_depth_when_semantics_are_covered(self) -> None:
        draft = copy.deepcopy(self.strong)
        steps = draft["algorithmic_principles"]["ordered_steps"][:4]
        steps[-1]["action"] += " Then evaluate the rollout NRMSE."
        draft["algorithmic_principles"]["ordered_steps"] = steps
        result = self.evaluate(_materialize(draft))
        self.assertTrue(result["schema_validation"]["passed"])
        self.assertTrue(self.gate(result, "structured_artifact_depth")["passed"])
        self.assertTrue(result["semantic_evaluation"]["passed"])

    def test_title_applicability_markers_may_appear_in_conclusion_short(self) -> None:
        draft = copy.deepcopy(self.strong)
        draft["executive_summary"]["applicability_short"] = "supported experimental regime"
        draft["executive_summary"]["conclusion_short"] = (
            "limited to deterministic measurement-noise experiments through 20%; "
            "broader claims unsupported"
        )
        result = self.evaluate(_materialize(draft))
        self.assertTrue(result["schema_validation"]["passed"])
        self.assertTrue(self.gate(result, "pyramid_title_no_drift")["passed"])
        self.assertTrue(result["semantic_evaluation"]["passed"])

    def test_canonical_title_comes_from_source_binding_and_source_h1(self) -> None:
        rubric = copy.deepcopy(self.rubric)
        rubric["canonical_title"] = "A stale evaluator-side title"
        result = EVALUATOR.evaluate_understanding(
            self.strong,
            rubric,
            source_text=self.source_text,
        )
        check = self.dimension_check(
            result,
            "evidence_locators_and_provenance",
            "source_binding_canonical_title_matches_source",
        )
        self.assertTrue(check["passed"])
        self.assertEqual(
            check["details"]["source_binding"],
            "Universal Weak-Form Sparse Recovery under Mixed Noise",
        )

    def test_any_exact_source_printed_locator_is_valid_beyond_critical_set(self) -> None:
        draft = copy.deepcopy(self.strong)
        claim = next(item for item in draft["claims"] if item["claim_id"] == "c-sign")
        extra = {
            "evidence_id": "e-c-sign-extra",
            "summary": claim["statement"],
            "locator": "p. 4, Figure 1, panels a-b",
        }
        claim["evidence"].append(extra)
        claim["evidence_ids"].append(extra["evidence_id"])
        result = self.evaluate(_materialize(draft))
        locator_check = self.dimension_check(
            result,
            "evidence_locators_and_provenance",
            "all_locators_are_source_printed_tokens",
        )
        required_check = self.dimension_check(
            result,
            "evidence_locators_and_provenance",
            "all_required_locators_present",
        )
        self.assertTrue(locator_check["passed"])
        self.assertTrue(required_check["passed"])
        self.assertTrue(result["semantic_evaluation"]["passed"])

    def test_workflow_may_own_algorithm_setting_and_stopping_gaps(self) -> None:
        draft = copy.deepcopy(self.strong)
        algorithm = draft["algorithmic_principles"]
        setting_gaps = list(algorithm["missing_information"])
        algorithm["missing_information"] = []
        algorithm["failure_modes"] = algorithm["failure_modes"][:3]
        algorithm["algorithms"][0]["stopping_condition"] = "See the workflow gap record."
        draft["workflow"]["missing_information"].extend(
            setting_gaps + ["The algorithm stopping condition is not reported."]
        )
        result = self.evaluate(_materialize(draft))
        stopping = self.dimension_check(
            result,
            "algorithm_ordering_and_limits",
            "unreported_stopping_condition_explicit",
        )
        self.assertTrue(stopping["passed"])
        self.assertTrue(
            self.gate(result, "unreported_details_not_fabricated")["passed"]
        )
        self.assertTrue(result["semantic_evaluation"]["passed"])

    def test_math_root_may_be_dependency_free_but_non_root_needs_prior_step(self) -> None:
        root_draft = copy.deepcopy(self.strong)
        root_draft["mathematical_principles"]["derivation_steps"][0]["depends_on"] = []
        root_result = self.evaluate(_materialize(root_draft))
        root_check = self.dimension_check(
            root_result,
            "math_assumptions_and_derivation",
            "derivation_dependencies_forward_from_root",
        )
        self.assertTrue(root_check["passed"])
        self.assertTrue(root_result["semantic_evaluation"]["passed"])

        detached_draft = copy.deepcopy(self.strong)
        detached_draft["mathematical_principles"]["derivation_steps"][1][
            "depends_on"
        ] = ["assumption:candidate library {1, x, x^2, x^3}"]
        detached_result = self.evaluate(_materialize(detached_draft))
        detached_check = self.dimension_check(
            detached_result,
            "math_assumptions_and_derivation",
            "derivation_dependencies_forward_from_root",
        )
        self.assertFalse(detached_check["passed"])

    def test_hyphenated_least_squares_and_bracketed_library_are_equivalent(self) -> None:
        draft = copy.deepcopy(self.strong)
        draft["algorithmic_principles"]["ordered_steps"][2]["action"] = (
            "Solve the least-squares minimization for theta."
        )
        draft["algorithmic_principles"]["invariants"][0] = (
            "Library order remains [1,x,x^2,x^3]."
        )
        result = self.evaluate(_materialize(draft))
        step_check = self.dimension_check(
            result,
            "algorithm_ordering_and_limits",
            "ordered_step_3",
        )
        invariant_check = self.dimension_check(
            result,
            "algorithm_ordering_and_limits",
            "invariant_1",
        )
        self.assertIn("least-squares", step_check["details"]["matched"])
        self.assertIn("[1,x,x^2,x^3]", invariant_check["details"]["matched"])
        self.assertTrue(result["semantic_evaluation"]["passed"])

    def test_applicability_constraints_are_not_required_as_algorithm_invariants(self) -> None:
        draft = copy.deepcopy(self.strong)
        draft["algorithmic_principles"]["invariants"] = draft[
            "algorithmic_principles"
        ]["invariants"][:2]
        result = self.evaluate(_materialize(draft))
        invariant_checks = [
            check
            for check in result["semantic_evaluation"]["dimensions"][
                "algorithm_ordering_and_limits"
            ]["checks"]
            if check["name"].startswith("invariant_")
        ]
        self.assertEqual(len(invariant_checks), 2)
        self.assertTrue(all(check["passed"] for check in invariant_checks))
        self.assertTrue(result["semantic_evaluation"]["passed"])

    def test_math_markers_may_live_in_derivations_results_and_principles(self) -> None:
        draft = copy.deepcopy(self.strong)
        math = draft["mathematical_principles"]
        replacements = {
            "deterministic latent ODE dynamics": "A1",
            "Gaussian measurement noise is added after integration": "A2",
            "candidate library {1, x, x^2, x^3}": "A3",
            "OLS covariance is conditional on the selected support": "A4",
            "selection uncertainty is excluded": "A5",
        }
        math["assumptions"] = list(replacements.values())
        for step in math["derivation_steps"]:
            step["depends_on"] = [
                f"assumption:{replacements[value.removeprefix('assumption:')]}"
                if value.startswith("assumption:")
                else value
                for value in step["depends_on"]
            ]
        math["derivation_steps"][0]["statement"] += (
            " Gaussian measurement noise is added after integration."
        )
        result = self.evaluate(_materialize(draft))
        marker_checks = [
            check
            for check in result["semantic_evaluation"]["dimensions"][
                "math_assumptions_and_derivation"
            ]["checks"]
            if check["name"].startswith("assumption_")
        ]
        self.assertTrue(all(check["passed"] for check in marker_checks))
        self.assertTrue(result["semantic_evaluation"]["passed"])
