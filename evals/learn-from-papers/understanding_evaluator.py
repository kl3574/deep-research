#!/usr/bin/env python3
"""Semantic evaluator for PaperUnderstanding/v1 over the synthetic WSR paper.

Schema validation and semantic scoring are intentionally reported separately:
the producer validator proves structural closure, while this evaluator checks
whether the closed artifact actually understands the source.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

RUBRIC_SCHEMA = "PaperUnderstandingSemanticRubric/v1"
EVALUATION_SCHEMA = "PaperUnderstandingSemanticEvaluation/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER_PATH = (
    REPO_ROOT / "skills" / "learn-from-papers" / "scripts" / "paper_understanding.py"
)
_PRODUCER: ModuleType | None = None


def _load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a top-level object")
    return value


def _load_producer() -> ModuleType:
    global _PRODUCER
    if _PRODUCER is not None:
        return _PRODUCER
    spec = importlib.util.spec_from_file_location(
        "learn_from_papers_understanding_evaluator_producer", PRODUCER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load PaperUnderstanding validator: {PRODUCER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _PRODUCER = module
    return module


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for nested in value.values():
            result.extend(_strings(nested))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result = []
        for nested in value:
            result.extend(_strings(nested))
        return result
    return []


def _text(value: Any) -> str:
    return "\n".join(_strings(value))


def _normalize(value: Any) -> str:
    text = str(value).casefold()
    text = re.sub(r"[\u2010-\u2015_/]+", "-", text)
    return " ".join(text.split())


def _normalize_locator(value: Any) -> str:
    text = " ".join(str(value).split())
    text = re.sub(r"\bEq\.\s*\(", "Eq. (", text)
    return text


def _source_canonical_title(source_text: str) -> str:
    for line in source_text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return ""


def _source_locator_tokens(source_text: str) -> set[str]:
    """Extract the locator tokens printed by the source rather than a gold list."""
    tokens: set[str] = set()
    for line in source_text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading:
            heading_text = heading.group(1).strip()
            tokens.add(_normalize_locator(heading_text))
            prefix = heading_text.split("[", 1)[0].strip()
            if prefix:
                tokens.add(_normalize_locator(prefix))
        for bracketed in re.findall(r"\[([^\]\n]+)\]", line):
            tokens.add(_normalize_locator(bracketed))
        for equation in re.findall(r"\bEq\.\s*\(\d+\)", line):
            tokens.add(_normalize_locator(equation))
    return tokens


def _contains(text: str, marker: Any) -> bool:
    return _normalize(marker) in _normalize(text)


def _group_hits(text: str, groups: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for raw_group in _list(groups):
        alternatives = [str(item) for item in _list(raw_group)]
        hits = [marker for marker in alternatives if _contains(text, marker)]
        results.append(
            {
                "alternatives": alternatives,
                "passed": bool(hits),
                "matched": hits,
            }
        )
    return results


def _check(name: str, passed: bool, details: Any = None) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "details": details}


def _dimension(name: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for check in checks if check["passed"])
    score = passed / len(checks) if checks else 0.0
    return {
        "name": name,
        "score": round(score, 3),
        "checks_passed": passed,
        "checks_total": len(checks),
        "checks": checks,
    }


def _marker_checks(prefix: str, text: str, groups: Any) -> list[dict[str, Any]]:
    return [
        _check(f"{prefix}_{index + 1}", row["passed"], row)
        for index, row in enumerate(_group_hits(text, groups))
    ]


def _section(candidate: Mapping[str, Any], name: str) -> dict[str, Any]:
    return _object(candidate.get(name))


def _schema_validation(candidate: Mapping[str, Any]) -> dict[str, Any]:
    try:
        validated = _load_producer().validate_understanding(dict(candidate))
    except Exception as exc:  # ContractError belongs to the loaded producer version.
        return {
            "passed": False,
            "validator": "learn-from-papers.paper-understanding",
            "details": f"{type(exc).__name__}: {exc}",
        }
    return {
        "passed": True,
        "validator": "learn-from-papers.paper-understanding",
        "details": f"validated {validated['schema']}",
    }


def _applicability_dimension(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any]
) -> dict[str, Any]:
    section = _section(candidate, "applicability")
    applies_text = _text(
        [section.get("primary_use_case"), section.get("applies_when"), section.get("rationale")]
    )
    excludes_text = _text(
        [
            section.get("does_not_apply_when"),
            section.get("missing_information"),
            section.get("rationale"),
        ]
    )
    checks = [_check("status_answered", section.get("status") == "answered")]
    checks.extend(
        _marker_checks("applies", applies_text, rubric.get("applies_marker_groups"))
    )
    checks.extend(
        _marker_checks(
            "excludes", excludes_text, rubric.get("exclusion_marker_groups")
        )
    )
    checks.append(
        _check(
            "claim_and_evidence_bindings_present",
            bool(_list(section.get("claim_ids")))
            and bool(_list(section.get("evidence_ids"))),
        )
    )
    return _dimension("applicability", checks)


def _graph(candidate: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    workflow = _section(candidate, "workflow")
    graph = _object(workflow.get("graph"))
    nodes = [_object(item) for item in _list(graph.get("nodes"))]
    operations = [_object(item) for item in _list(graph.get("operations"))]
    return nodes, operations


def _io_format_gaps(
    workflow: Mapping[str, Any],
    nodes: list[dict[str, Any]],
    rubric: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify placeholder I/O formats, allowing only source-bound gaps."""
    placeholders = {
        _normalize(item) for item in _list(rubric.get("format_placeholders"))
    }
    bound_gap_values = {
        _normalize(item) for item in _list(rubric.get("format_bound_gap_values"))
    }
    gap_markers = [str(item) for item in _list(rubric.get("format_gap_markers"))]
    gap_statements = _strings(workflow.get("missing_information"))
    generic_tokens = {"input", "output", "node", "data", "输入", "输出", "节点", "数据"}
    failures: list[dict[str, Any]] = []
    accepted_gaps: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("kind") not in {"input", "output"}:
            continue
        node_id = str(node.get("node_id", "<missing>"))
        format_value = str(node.get("format", ""))
        normalized_format = _normalize(format_value)
        if normalized_format not in placeholders:
            continue
        binding_tokens = [
            str(node.get(key, "")).strip()
            for key in ("node_id", "description", "semantic_type")
        ]
        binding_tokens = [
            token
            for token in binding_tokens
            if token and _normalize(token) not in generic_tokens
        ]
        bound_statement = next(
            (
                statement
                for statement in gap_statements
                if any(_contains(statement, marker) for marker in gap_markers)
                and any(_contains(statement, marker) for marker in bound_gap_values)
                and any(_contains(statement, token) for token in binding_tokens)
            ),
            None,
        )
        row = {
            "node_id": node_id,
            "format": format_value,
            "bound_missing_information": bound_statement,
        }
        if normalized_format in bound_gap_values and bound_statement is not None:
            accepted_gaps.append(row)
        else:
            failures.append(row)
    return failures, accepted_gaps


def _workflow_dimensions(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    workflow = _section(candidate, "workflow")
    nodes, operations = _graph(candidate)
    node_text = _text(nodes)
    operation_text = _text(operations)
    kinds = {str(node.get("kind", "")) for node in nodes}

    node_checks = [
        _check(
            "minimum_nodes",
            len(nodes) >= int(rubric.get("minimum_nodes", 1)),
            {"provided": len(nodes), "required": rubric.get("minimum_nodes")},
        ),
        _check("input_intermediate_output_present", {"input", "intermediate", "output"} <= kinds),
        _check("workflow_steps_present", len(_list(workflow.get("steps"))) >= 4),
    ]
    node_checks.extend(
        _marker_checks("node_semantics", node_text, rubric.get("node_marker_groups"))
    )

    placeholders = {_normalize(item) for item in _list(rubric.get("format_placeholders"))}
    io_nodes = [node for node in nodes if node.get("kind") in {"input", "output"}]
    format_failures, accepted_format_gaps = _io_format_gaps(workflow, nodes, rubric)
    shape_failures = [
        str(node.get("node_id", "<missing>"))
        for node in io_nodes
        if _normalize(node.get("shape", "")) in placeholders
    ]
    format_checks = [
        _check("input_and_output_nodes_present", bool(io_nodes) and {"input", "output"} <= kinds),
        _check(
            "all_io_formats_specific_or_bound_gap",
            not format_failures,
            {"failures": format_failures, "accepted_gaps": accepted_format_gaps},
        ),
        _check("all_io_shapes_specific", not shape_failures, shape_failures),
        _check(
            "multiple_io_contracts",
            len(io_nodes) >= 4,
            {"provided": len(io_nodes), "required": 4},
        ),
    ]

    reachable = {
        str(node.get("node_id")) for node in nodes if node.get("kind") == "input"
    }
    changed = True
    while changed:
        changed = False
        for operation in operations:
            consumes = {str(item) for item in _list(operation.get("consumes"))}
            produces = {str(item) for item in _list(operation.get("produces"))}
            if consumes and consumes <= reachable and not produces <= reachable:
                reachable.update(produces)
                changed = True
    output_ids = {
        str(node.get("node_id")) for node in nodes if node.get("kind") == "output"
    }
    flow_checks = [
        _check(
            "minimum_operations",
            len(operations) >= int(rubric.get("minimum_operations", 1)),
            {"provided": len(operations), "required": rubric.get("minimum_operations")},
        ),
        _check("all_outputs_reachable_from_inputs", bool(output_ids) and output_ids <= reachable),
        _check("narrative_data_flow_present", len(_list(workflow.get("data_flow"))) >= 4),
    ]
    flow_checks.extend(
        _marker_checks(
            "operation_semantics", operation_text, rubric.get("operation_marker_groups")
        )
    )
    return {
        "workflow_nodes": _dimension("workflow_nodes", node_checks),
        "io_formats": _dimension("io_formats", format_checks),
        "data_flow_edges": _dimension("data_flow_edges", flow_checks),
    }


def _mathematics_dimension(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any]
) -> dict[str, Any]:
    section = _section(candidate, "mathematical_principles")
    assumptions = _list(section.get("assumptions"))
    steps = [_object(item) for item in _list(section.get("derivation_steps"))]
    principles = [_object(item) for item in _list(section.get("principles"))]
    provenance_ok = bool(steps) and all(
        step.get("origin") in {"source_stated", "agent_reconstructed"}
        and bool(str(step.get("locator", "")).strip())
        and bool(_list(step.get("evidence_ids")))
        for step in steps
    )
    prior_step_ids: set[str] = set()
    dependency_rows: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        dependencies = [str(item) for item in _list(step.get("depends_on"))]
        step_refs = {
            dependency.removeprefix("step:")
            for dependency in dependencies
            if not dependency.startswith(("assumption:", "result:"))
        }
        is_root = index == 0
        passed = (
            not step_refs
            if is_root
            else bool(dependencies) and bool(step_refs) and step_refs <= prior_step_ids
        )
        dependency_rows.append(
            {
                "step_id": step.get("step_id"),
                "is_root": is_root,
                "dependencies": dependencies,
                "passed": passed,
            }
        )
        prior_step_ids.add(str(step.get("step_id", "")))
    dependencies_ok = bool(dependency_rows) and all(
        row["passed"] for row in dependency_rows
    )
    structured_math_text = _text(
        [
            assumptions,
            steps,
            section.get("results"),
            principles,
            section.get("rationale"),
            section.get("missing_information"),
        ]
    )
    checks = [
        _check("status_answered", section.get("status") == "answered"),
        _check(
            "minimum_assumptions",
            len(assumptions) >= int(rubric.get("minimum_assumptions", 1)),
            {"provided": len(assumptions), "required": rubric.get("minimum_assumptions")},
        ),
        _check(
            "minimum_derivation_steps",
            len(steps) >= int(rubric.get("minimum_derivation_steps", 1)),
            {"provided": len(steps), "required": rubric.get("minimum_derivation_steps")},
        ),
        _check("derivation_dependencies_forward_from_root", dependencies_ok, dependency_rows),
        _check("derivation_provenance_explicit", provenance_ok),
        _check("principle_with_latex_and_derivation", any(
            str(item.get("latex", "")).strip() and _list(item.get("derivation_steps"))
            for item in principles
        )),
    ]
    checks.extend(
        _marker_checks(
            "assumption", structured_math_text, rubric.get("assumption_marker_groups")
        )
    )
    checks.extend(
        _marker_checks(
            "derivation", _text(steps), rubric.get("derivation_marker_groups")
        )
    )
    return _dimension("math_assumptions_and_derivation", checks)


def _algorithm_gap_statements(candidate: Mapping[str, Any]) -> list[str]:
    workflow = _section(candidate, "workflow")
    algorithm = _section(candidate, "algorithmic_principles")
    algorithms = [_object(item) for item in _list(algorithm.get("algorithms"))]
    return _strings(
        [
            workflow.get("missing_information"),
            algorithm.get("missing_information"),
            algorithm.get("failure_modes"),
            [item.get("stopping_condition") for item in algorithms],
        ]
    )


def _algorithm_dimension(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any]
) -> dict[str, Any]:
    section = _section(candidate, "algorithmic_principles")
    steps = [_object(item) for item in _list(section.get("ordered_steps"))]
    algorithms = [_object(item) for item in _list(section.get("algorithms"))]
    item_steps = sum(len(_list(item.get("ordered_steps"))) for item in algorithms)
    gap_statements = _algorithm_gap_statements(candidate)
    missing_text = _text(gap_statements)
    dependencies_ok = len(steps) > 1 and all(
        bool(_list(step.get("depends_on"))) for step in steps[1:]
    )
    stopping_markers = [str(item) for item in _list(rubric.get("stopping_unknown_markers"))]
    stopping_concepts = [str(item) for item in _list(rubric.get("stopping_concept_markers"))]
    stopping_ok = any(
        any(_contains(statement, marker) for marker in stopping_markers)
        and any(_contains(statement, concept) for concept in stopping_concepts)
        for statement in gap_statements
    )
    checks = [
        _check("status_answered", section.get("status") == "answered"),
        _check(
            "minimum_ordered_steps",
            len(steps) >= int(rubric.get("minimum_ordered_steps", 1)),
            {"provided": len(steps), "required": rubric.get("minimum_ordered_steps")},
        ),
        _check(
            "minimum_algorithm_item_steps",
            item_steps >= int(rubric.get("minimum_algorithm_steps", 1)),
            {"provided": item_steps, "required": rubric.get("minimum_algorithm_steps")},
        ),
        _check("ordering_dependencies_explicit", dependencies_ok),
        _check("unreported_stopping_condition_explicit", stopping_ok, gap_statements),
        _check("algorithm_has_update_rule", bool(algorithms) and all(
            str(item.get("update_rule", "")).strip() for item in algorithms
        )),
    ]
    checks.extend(
        _marker_checks("ordered_step", _text(steps), rubric.get("step_marker_groups"))
    )
    checks.extend(
        _marker_checks(
            "invariant", _text(section.get("invariants")), rubric.get("invariant_marker_groups")
        )
    )
    checks.extend(
        _marker_checks("missing_detail", missing_text, rubric.get("missing_detail_groups"))
    )
    return _dimension("algorithm_ordering_and_limits", checks)


def _conclusion_dimension(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any]
) -> dict[str, Any]:
    section = _section(candidate, "conclusion")
    text = _text(
        [
            section.get("statement"),
            section.get("rationale"),
            section.get("confidence_rationale"),
            section.get("missing_information"),
        ]
    )
    checks = [
        _check("status_answered", section.get("status") == "answered"),
        _check("calibrated_confidence", _normalize(section.get("confidence")) in {"low", "medium"}),
        _check("claim_and_evidence_bindings_present", bool(_list(section.get("claim_ids"))) and bool(_list(section.get("evidence_ids")))),
    ]
    checks.extend(
        _marker_checks("supported_scope", text, rubric.get("supported_marker_groups"))
    )
    checks.extend(
        _marker_checks("limitation", text, rubric.get("limitation_marker_groups"))
    )
    return _dimension("conclusion_scope", checks)


def _title_dimension(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any]
) -> dict[str, Any]:
    executive = _section(candidate, "executive_summary")
    applicability = str(executive.get("applicability_short", ""))
    conclusion = str(executive.get("conclusion_short", ""))
    expected = f"适用：{applicability}｜结论：{conclusion}"
    provided = str(candidate.get("research_retrieval_title", ""))
    checks = [_check("exact_pyramid_formula", provided == expected, {"expected": expected})]
    checks.extend(
        _marker_checks(
            "title_applicability", provided, rubric.get("applicability_marker_groups")
        )
    )
    checks.extend(
        _marker_checks("title_conclusion", conclusion, rubric.get("conclusion_marker_groups"))
    )
    return _dimension("pyramid_title_consistency", checks)


def _claim_evidence(candidate: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    registry: dict[str, dict[str, Any]] = {}
    locators: set[str] = set()
    for raw_claim in _list(candidate.get("claims")):
        claim = _object(raw_claim)
        for raw_evidence in _list(claim.get("evidence")):
            evidence = _object(raw_evidence)
            evidence_id = str(evidence.get("evidence_id", ""))
            locator = str(evidence.get("locator", ""))
            if evidence_id:
                registry[evidence_id] = evidence
            if locator:
                locators.add(locator)
    return registry, locators


def _structured_rows(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    math = _section(candidate, "mathematical_principles")
    algorithm = _section(candidate, "algorithmic_principles")
    rows = [_object(item) for item in _list(math.get("derivation_steps"))]
    for principle_raw in _list(math.get("principles")):
        principle = _object(principle_raw)
        rows.append(principle)
        rows.extend(_object(item) for item in _list(principle.get("derivation_steps")))
    rows.extend(_object(item) for item in _list(algorithm.get("ordered_steps")))
    for item_raw in _list(algorithm.get("algorithms")):
        item = _object(item_raw)
        rows.append(item)
        rows.extend(_object(step) for step in _list(item.get("ordered_steps")))
    return rows


def _all_evidence_refs(candidate: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for name in (
        "applicability",
        "workflow",
        "mathematical_principles",
        "algorithmic_principles",
        "conclusion",
    ):
        refs.extend(str(item) for item in _list(_section(candidate, name).get("evidence_ids")))
    for row in _structured_rows(candidate):
        refs.extend(str(item) for item in _list(row.get("evidence_ids")))
    for raw in _list(candidate.get("contributions")):
        refs.extend(str(item) for item in _list(_object(raw).get("evidence_ids")))
    return refs


def _evidence_dimension(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any], source_text: str
) -> dict[str, Any]:
    source_binding = _section(candidate, "source_binding")
    registry, evidence_locators = _claim_evidence(candidate)
    rows = _structured_rows(candidate)
    structured_locators = {
        str(row.get("locator")) for row in rows if str(row.get("locator", "")).strip()
    }
    all_locators = evidence_locators | structured_locators
    normalized_evidence_locators = {
        _normalize_locator(locator) for locator in evidence_locators
    }
    normalized_all_locators = {_normalize_locator(locator) for locator in all_locators}
    required = {
        _normalize_locator(item) for item in _list(rubric.get("required_locators"))
    }
    source_locator_tokens = _source_locator_tokens(source_text)
    source_title = _source_canonical_title(source_text)
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    refs = _all_evidence_refs(candidate)
    source_rows = [row for row in rows if row.get("origin") == "source_stated"]
    checks = [
        _check("source_artifact_digest_matches", source_binding.get("source_artifact_sha256") == source_hash),
        _check(
            "source_binding_canonical_title_matches_source",
            bool(source_title) and source_binding.get("canonical_title") == source_title,
            {
                "source_binding": source_binding.get("canonical_title"),
                "source_title": source_title,
            },
        ),
        _check(
            "all_required_locators_present",
            required <= normalized_evidence_locators,
            sorted(required - normalized_evidence_locators),
        ),
        _check(
            "all_locators_are_source_printed_tokens",
            bool(normalized_all_locators)
            and normalized_all_locators <= source_locator_tokens,
            sorted(normalized_all_locators - source_locator_tokens),
        ),
        _check("all_evidence_references_resolve", bool(refs) and all(ref in registry for ref in refs)),
        _check("source_stated_rows_have_provenance", bool(source_rows) and all(
            str(row.get("locator", "")) in evidence_locators
            and ("evidence_ids" not in row or bool(_list(row.get("evidence_ids"))))
            for row in source_rows
        )),
    ]
    return _dimension("evidence_locators_and_provenance", checks)


def _abstention_dimension(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any]
) -> dict[str, Any]:
    claims = [_object(item) for item in _list(candidate.get("claims"))]
    terminal_ids = {
        str(_object(item).get("claim_id"))
        for item in _list(_section(candidate, "coverage").get("terminal_claims"))
    }
    not_tested = [
        claim
        for claim in claims
        if claim.get("relation") == "not_tested" and claim.get("status") == "terminal"
    ]
    checks = _marker_checks(
        "terminal_not_tested", _text(not_tested), rubric.get("not_tested_marker_groups")
    )
    checks.extend(
        [
            _check("terminal_claims_present", bool(not_tested)),
            _check(
                "terminal_coverage_closed",
                bool(not_tested)
                and all(str(claim.get("claim_id")) in terminal_ids for claim in not_tested),
            ),
            _check(
                "core_sections_not_misclassified_not_applicable",
                all(
                    _section(candidate, name).get("status") != "not_applicable"
                    for name in (
                        "applicability",
                        "workflow",
                        "mathematical_principles",
                        "algorithmic_principles",
                        "conclusion",
                    )
                ),
            ),
        ]
    )
    return _dimension("abstention_and_not_applicable", checks)


def _claim_bearing_units(candidate: Mapping[str, Any]) -> list[str]:
    executive = _section(candidate, "executive_summary")
    applicability = _section(candidate, "applicability")
    conclusion = _section(candidate, "conclusion")
    units = _strings(
        [
            candidate.get("research_retrieval_title"),
            executive,
            applicability.get("primary_use_case"),
            applicability.get("applies_when"),
            conclusion.get("statement"),
            conclusion.get("rationale"),
            conclusion.get("confidence_rationale"),
            [_object(item).get("statement") for item in _list(candidate.get("contributions"))],
        ]
    )
    for raw_claim in _list(candidate.get("claims")):
        claim = _object(raw_claim)
        if claim.get("relation") in {"supports", "qualifies"} and claim.get("status") == "answered":
            units.extend(_strings([claim.get("statement"), claim.get("confidence_rationale")]))
    return units


def _limitation_text(candidate: Mapping[str, Any]) -> str:
    applicability = _section(candidate, "applicability")
    conclusion = _section(candidate, "conclusion")
    algorithm = _section(candidate, "algorithmic_principles")
    boundary_claims = [
        _object(item)
        for item in _list(candidate.get("claims"))
        if _object(item).get("relation") in {"refutes", "not_tested"}
    ]
    return _text(
        [
            applicability.get("does_not_apply_when"),
            applicability.get("rationale"),
            applicability.get("missing_information"),
            conclusion,
            algorithm.get("failure_modes"),
            algorithm.get("missing_information"),
            boundary_claims,
            _section(candidate, "coverage").get("terminal_claims"),
        ]
    )


def _unnegated_pattern_hits(
    units: list[str], patterns: Any, negation_markers: list[str]
) -> list[str]:
    compiled = [re.compile(str(pattern), re.IGNORECASE) for pattern in _list(patterns)]
    hits: list[str] = []
    for unit in units:
        if any(_contains(unit, marker) for marker in negation_markers):
            continue
        if any(pattern.search(unit) for pattern in compiled):
            hits.append(unit)
    return hits


def _hard_gates(
    candidate: Mapping[str, Any], rubric: Mapping[str, Any], dimensions: Mapping[str, Any]
) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    negations = [str(item) for item in _list(rubric.get("negation_markers"))]
    claim_units = _claim_bearing_units(candidate)
    limitation_text = _limitation_text(candidate)
    for raw in _list(rubric.get("overclaims")):
        policy = _object(raw)
        hits = _unnegated_pattern_hits(claim_units, policy.get("patterns"), negations)
        limitation_rows = _group_hits(
            limitation_text, policy.get("limitation_marker_groups")
        )
        limitations_ok = bool(limitation_rows) and all(row["passed"] for row in limitation_rows)
        gates.append(
            {
                "name": str(policy.get("name", "overclaim")),
                "passed": not hits and limitations_ok,
                "severity": "hard",
                "details": {
                    "unnegated_assertions": hits,
                    "limitation_checks": limitation_rows,
                },
            }
        )

    workflow_policy = _object(rubric.get("workflow"))
    nodes, operations = _graph(candidate)
    workflow = _section(candidate, "workflow")
    format_failures, accepted_format_gaps = _io_format_gaps(
        workflow, nodes, workflow_policy
    )
    gates.append(
        {
            "name": "io_format_present",
            "passed": bool(nodes) and not format_failures,
            "severity": "hard",
            "details": {
                "nodes_with_unbound_missing_or_placeholder_format": format_failures,
                "accepted_bound_format_gaps": accepted_format_gaps,
            },
        }
    )

    fabrication_negations = negations + ["unresolved", "unspecified", "omits", "missing"]
    fabricated = _unnegated_pattern_hits(
        _strings(candidate), rubric.get("fabricated_value_patterns"), fabrication_negations
    )
    missing_detail_rows = _group_hits(
        _text(_algorithm_gap_statements(candidate)),
        _object(rubric.get("algorithm")).get("missing_detail_groups"),
    )
    gates.append(
        {
            "name": "unreported_details_not_fabricated",
            "passed": not fabricated
            and bool(missing_detail_rows)
            and all(row["passed"] for row in missing_detail_rows),
            "severity": "hard",
            "details": {
                "fabricated_value_assertions": fabricated,
                "missing_detail_checks": missing_detail_rows,
            },
        }
    )

    title_dimension = dimensions["pyramid_title_consistency"]
    gates.append(
        {
            "name": "pyramid_title_no_drift",
            "passed": title_dimension["score"] == 1.0,
            "severity": "hard",
            "details": title_dimension["checks"],
        }
    )

    depth = _object(rubric.get("depth"))
    math = _section(candidate, "mathematical_principles")
    algorithms = _section(candidate, "algorithmic_principles")
    algorithm_items = [_object(item) for item in _list(algorithms.get("algorithms"))]
    _, evidence_locators = _claim_evidence(candidate)
    depth_checks = [
        _check("nodes", len(nodes) >= int(depth.get("minimum_nodes", 1)), len(nodes)),
        _check("operations", len(operations) >= int(depth.get("minimum_operations", 1)), len(operations)),
        _check("math_derivation_steps", len(_list(math.get("derivation_steps"))) >= int(depth.get("minimum_math_derivation_steps", 1)), len(_list(math.get("derivation_steps")))),
        _check("algorithm_ordered_steps", len(_list(algorithms.get("ordered_steps"))) >= int(depth.get("minimum_algorithm_ordered_steps", 1)), len(_list(algorithms.get("ordered_steps")))),
        _check("algorithm_item_steps", sum(len(_list(item.get("ordered_steps"))) for item in algorithm_items) >= int(depth.get("minimum_algorithm_item_steps", 1)), sum(len(_list(item.get("ordered_steps"))) for item in algorithm_items)),
        _check("claims", len(_list(candidate.get("claims"))) >= int(depth.get("minimum_claims", 1)), len(_list(candidate.get("claims")))),
        _check("unique_locators", len(evidence_locators) >= int(depth.get("minimum_unique_locators", 1)), len(evidence_locators)),
    ]
    gates.append(
        {
            "name": "structured_artifact_depth",
            "passed": all(check["passed"] for check in depth_checks),
            "severity": "hard",
            "details": depth_checks,
        }
    )
    return gates


def evaluate_understanding(
    candidate: Mapping[str, Any],
    rubric: Mapping[str, Any],
    *,
    source_text: str,
) -> dict[str, Any]:
    if rubric.get("schema") != RUBRIC_SCHEMA:
        raise ValueError(f"rubric schema must be {RUBRIC_SCHEMA}")
    if not source_text.strip():
        raise ValueError("source_text must not be empty")

    dimensions: dict[str, dict[str, Any]] = {
        "applicability": _applicability_dimension(candidate, _object(rubric.get("applicability"))),
        **_workflow_dimensions(candidate, _object(rubric.get("workflow"))),
        "math_assumptions_and_derivation": _mathematics_dimension(candidate, _object(rubric.get("mathematics"))),
        "algorithm_ordering_and_limits": _algorithm_dimension(candidate, _object(rubric.get("algorithm"))),
        "conclusion_scope": _conclusion_dimension(candidate, _object(rubric.get("conclusion"))),
        "pyramid_title_consistency": _title_dimension(candidate, _object(rubric.get("title"))),
        "evidence_locators_and_provenance": _evidence_dimension(candidate, _object(rubric.get("evidence")), source_text),
        "abstention_and_not_applicable": _abstention_dimension(candidate, _object(rubric.get("abstention"))),
    }
    gates = _hard_gates(candidate, _object(rubric.get("hard_gates")) | {
        "workflow": _object(rubric.get("workflow")),
        "algorithm": _object(rubric.get("algorithm")),
    }, dimensions)
    thresholds = _object(rubric.get("thresholds"))
    minimum_dimension = float(thresholds.get("minimum_dimension_score", 0.0))
    minimum_semantic = float(thresholds.get("minimum_semantic_score", 0.0))
    semantic_score = round(
        sum(item["score"] for item in dimensions.values()) / len(dimensions), 3
    )
    semantic_passed = (
        semantic_score >= minimum_semantic
        and all(item["score"] >= minimum_dimension for item in dimensions.values())
        and all(gate["passed"] for gate in gates)
    )
    schema_validation = _schema_validation(candidate)
    return {
        "schema": EVALUATION_SCHEMA,
        "candidate_schema": candidate.get("schema"),
        "rubric_schema": rubric.get("schema"),
        "schema_validation": schema_validation,
        "semantic_evaluation": {
            "passed": semantic_passed,
            "score": semantic_score,
            "minimum_score": minimum_semantic,
            "minimum_dimension_score": minimum_dimension,
            "dimensions": dimensions,
            "hard_gates": gates,
        },
        "overall": {
            "passed": bool(schema_validation["passed"] and semantic_passed),
            "requires": ["schema_validation.passed", "semantic_evaluation.passed"],
        },
    }


def evaluate_paths(
    candidate_path: str | Path,
    rubric_path: str | Path,
    *,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    rubric = _load_json(rubric_path)
    resolved_source = (
        Path(source_path)
        if source_path is not None
        else REPO_ROOT / str(rubric.get("paper_path", ""))
    )
    return evaluate_understanding(
        _load_json(candidate_path),
        rubric,
        source_text=resolved_source.read_text(encoding="utf-8"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--rubric", required=True)
    parser.add_argument("--source")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)
    result = evaluate_paths(
        args.candidate,
        args.rubric,
        source_path=args.source,
    )
    print(json.dumps(result, ensure_ascii=False, indent=args.indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
