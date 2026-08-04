#!/usr/bin/env python3
"""Validate private ResearchHandoff/v1 artifacts using only the standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


HASH_RE = re.compile(r"^[0-9a-f]{64}$")
TASK_MODES = {"research", "acquisition", "zotero"}
RESEARCH_STATES = {"complete", "partial", "blocked"}
DELIVERY_STATES = {
    "not_requested",
    "preflight",
    "ready",
    "partial",
    "complete",
    "blocked_capability",
    "blocked_authorization",
    "failed",
}
ROW_STATES = {
    "complete",
    "partial",
    "blocked_capability",
    "blocked_authorization",
    "failed",
    "not_applicable",
}
PATH_STATES = {"available", "failed", "unavailable", "unknown"}
CAPABILITY_STATES = {
    "available",
    "unknown",
    "not_required",
    "blocked_capability",
}
ATTACHMENT_PAIRS = {
    "main_text": "version_of_record_main",
    "accepted_manuscript": "accepted_manuscript_main",
    "preprint": "preprint_main",
    "supplement": "supplementary_information",
    "metadata_only": "metadata_only",
}
EXTERNAL_PREFIXES = ("acquire_", "zotero_")
NETWORK_NODE_KINDS = {"source", "claim", "entity"}
CONFIDENCE = {"high", "medium", "low", "unknown"}


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_keys(
    value: Any, keys: tuple[str, ...], label: str, errors: list[str]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    for key in keys:
        if key not in value:
            errors.append(f"{label}.{key} is required")
    return value


def _require_nonempty(
    value: dict[str, Any], keys: tuple[str, ...], label: str, errors: list[str]
) -> None:
    for key in keys:
        if key in value and not _present(value.get(key)):
            errors.append(f"{label}.{key} must be non-empty")


def _validate_file_digest(
    path_value: Any, digest_value: Any, label: str, errors: list[str]
) -> Path | None:
    if not isinstance(path_value, str) or not path_value:
        errors.append(f"{label}.path is required")
        return None
    path = Path(path_value)
    if not path.is_absolute():
        errors.append(f"{label}.path must be absolute")
        return None
    if not HASH_RE.fullmatch(str(digest_value or "")):
        errors.append(f"{label}.sha256 must be 64 lowercase hex characters")
        return None
    if not path.is_file():
        errors.append(f"{label}.path does not exist: {path}")
        return None
    actual = _sha256(path)
    if actual != digest_value:
        errors.append(f"{label}.sha256 mismatch: expected {digest_value}, got {actual}")
        return None
    return path


def _validate_provenance(
    provenance: Any, label: str, errors: list[str]
) -> None:
    if not isinstance(provenance, list) or not provenance:
        errors.append(f"{label}.provenance must be a non-empty list")
        return
    for index, entry in enumerate(provenance):
        _require_keys(
            entry,
            ("source_id", "locator"),
            f"{label}.provenance[{index}]",
            errors,
        )


def validate_knowledge_network(
    network: Any, *, zotero_required: bool = False
) -> list[str]:
    errors: list[str] = []
    network = _require_keys(
        network,
        (
            "schema",
            "network_id",
            "snapshot_id",
            "corpus_snapshot",
            "nodes",
            "relations",
            "gap_derivation",
            "gaps",
            "change_history",
            "completion",
        ),
        "knowledge_network",
        errors,
    )
    if network.get("schema") != "KnowledgeNetwork/v1":
        errors.append("knowledge_network.schema must equal KnowledgeNetwork/v1")
    _require_nonempty(
        network, ("network_id", "snapshot_id"), "knowledge_network", errors
    )

    corpus = _require_keys(
        network.get("corpus_snapshot"),
        ("source", "captured_at", "inventory_digest", "item_count", "item_refs"),
        "knowledge_network.corpus_snapshot",
        errors,
    )
    if zotero_required:
        if corpus.get("source") != "zotero":
            errors.append(
                "knowledge_network.corpus_snapshot.source must be zotero "
                "when Zotero is in task_modes"
            )
        if not _present(corpus.get("target_ref")):
            errors.append(
                "knowledge_network.corpus_snapshot.target_ref is required "
                "for Zotero work"
            )
    _require_nonempty(
        corpus,
        ("source", "captured_at"),
        "knowledge_network.corpus_snapshot",
        errors,
    )
    if not HASH_RE.fullmatch(str(corpus.get("inventory_digest") or "")):
        errors.append(
            "knowledge_network.corpus_snapshot.inventory_digest must be "
            "64 lowercase hex characters"
        )
    if not isinstance(corpus.get("item_count"), int) or corpus.get("item_count") < 0:
        errors.append(
            "knowledge_network.corpus_snapshot.item_count must be a non-negative integer"
        )
    if not isinstance(corpus.get("item_refs"), list):
        errors.append("knowledge_network.corpus_snapshot.item_refs must be a list")
    elif isinstance(corpus.get("item_count"), int) and corpus.get(
        "item_count"
    ) != len(corpus.get("item_refs")):
        errors.append(
            "knowledge_network.corpus_snapshot.item_count must match item_refs"
        )

    nodes = network.get("nodes")
    node_ids: set[str] = set()
    if not isinstance(nodes, list) or not nodes:
        errors.append("knowledge_network.nodes must be a non-empty list")
        nodes = []
    for index, node in enumerate(nodes):
        label = f"knowledge_network.nodes[{index}]"
        node = _require_keys(
            node,
            ("node_id", "kind", "label", "status", "confidence", "provenance"),
            label,
            errors,
        )
        _require_nonempty(node, ("node_id", "label", "status"), label, errors)
        node_id = node.get("node_id")
        if node_id in node_ids:
            errors.append(f"{label}.node_id is duplicated: {node_id}")
        elif isinstance(node_id, str):
            node_ids.add(node_id)
        if node.get("kind") not in NETWORK_NODE_KINDS:
            errors.append(f"{label}.kind must be source, claim, or entity")
        if node.get("status") not in {"active", "unresolved", "deprecated"}:
            errors.append(f"{label}.status is invalid")
        if node.get("confidence") not in CONFIDENCE:
            errors.append(f"{label}.confidence is invalid")
        _validate_provenance(node.get("provenance"), label, errors)

    relations = network.get("relations")
    relation_ids: set[str] = set()
    if not isinstance(relations, list) or not relations:
        errors.append("knowledge_network.relations must be a non-empty list")
        relations = []
    for index, relation in enumerate(relations):
        label = f"knowledge_network.relations[{index}]"
        relation = _require_keys(
            relation,
            (
                "relation_id",
                "from_id",
                "to_id",
                "predicate",
                "status",
                "confidence",
                "provenance",
            ),
            label,
            errors,
        )
        _require_nonempty(
            relation,
            ("relation_id", "from_id", "to_id", "predicate"),
            label,
            errors,
        )
        relation_id = relation.get("relation_id")
        if relation_id in relation_ids:
            errors.append(f"{label}.relation_id is duplicated: {relation_id}")
        elif isinstance(relation_id, str):
            relation_ids.add(relation_id)
        if relation.get("from_id") not in node_ids:
            errors.append(f"{label}.from_id must reference a node")
        if relation.get("to_id") not in node_ids:
            errors.append(f"{label}.to_id must reference a node")
        if relation.get("confidence") not in CONFIDENCE:
            errors.append(f"{label}.confidence is invalid")
        if relation.get("status") not in {
            "supported",
            "contradicted",
            "qualified",
            "unresolved",
        }:
            errors.append(f"{label}.status is invalid")
        _validate_provenance(relation.get("provenance"), label, errors)

    derivation = _require_keys(
        network.get("gap_derivation"),
        ("rules", "derived_gap_ids"),
        "knowledge_network.gap_derivation",
        errors,
    )
    rules = derivation.get("rules")
    if not isinstance(rules, list) or not {
        "missing",
        "conflict",
        "low_confidence",
    }.issubset(set(rules)):
        errors.append(
            "knowledge_network.gap_derivation.rules must include "
            "missing, conflict, and low_confidence"
        )

    gaps = network.get("gaps")
    gap_ids: set[str] = set()
    open_gap_ids: set[str] = set()
    if not isinstance(gaps, list):
        errors.append("knowledge_network.gaps must be a list")
        gaps = []
    known_objects = node_ids | relation_ids
    for index, gap in enumerate(gaps):
        label = f"knowledge_network.gaps[{index}]"
        gap = _require_keys(
            gap,
            ("gap_id", "derived_from", "reason", "priority", "status", "next_action"),
            label,
            errors,
        )
        _require_nonempty(
            gap, ("gap_id", "priority", "next_action"), label, errors
        )
        gap_id = gap.get("gap_id")
        if gap_id in gap_ids:
            errors.append(f"{label}.gap_id is duplicated: {gap_id}")
        elif isinstance(gap_id, str):
            gap_ids.add(gap_id)
        if gap.get("reason") not in {"missing", "conflict", "low_confidence"}:
            errors.append(f"{label}.reason is invalid")
        if gap.get("status") not in {"open", "resolved", "unresolved"}:
            errors.append(f"{label}.status is invalid")
        if gap.get("status") == "open" and isinstance(gap_id, str):
            open_gap_ids.add(gap_id)
        derived_from = gap.get("derived_from")
        if not isinstance(derived_from, list) or not derived_from:
            errors.append(f"{label}.derived_from must be a non-empty list")
        else:
            for object_id in derived_from:
                if object_id not in known_objects:
                    errors.append(
                        f"{label}.derived_from references unknown object {object_id}"
                    )

    derived_gap_ids = derivation.get("derived_gap_ids")
    if not isinstance(derived_gap_ids, list) or set(derived_gap_ids) != gap_ids:
        errors.append(
            "knowledge_network.gap_derivation.derived_gap_ids must exactly "
            "match gaps"
        )

    history = network.get("change_history")
    if not isinstance(history, list) or not history:
        errors.append("knowledge_network.change_history must be a non-empty list")
    else:
        for index, change in enumerate(history):
            change = _require_keys(
                change,
                ("change_id", "action", "object_ids", "basis_refs", "recorded_at"),
                f"knowledge_network.change_history[{index}]",
                errors,
            )
            _require_nonempty(
                change,
                ("change_id", "action", "object_ids", "basis_refs", "recorded_at"),
                f"knowledge_network.change_history[{index}]",
                errors,
            )

    completion = _require_keys(
        network.get("completion"),
        ("status", "open_gap_ids", "gate_checks"),
        "knowledge_network.completion",
        errors,
    )
    if completion.get("status") not in {"passed", "partial", "blocked"}:
        errors.append("knowledge_network.completion.status is invalid")
    if set(completion.get("open_gap_ids") or []) != open_gap_ids:
        errors.append(
            "knowledge_network.completion.open_gap_ids must match open gaps"
        )
    checks = completion.get("gate_checks")
    required_checks = {
        "corpus_snapshotted",
        "provenance_complete",
        "conflicts_terminal",
        "low_confidence_edges_terminal",
        "change_history_recorded",
    }
    if not isinstance(checks, dict) or not required_checks.issubset(checks):
        errors.append(
            "knowledge_network.completion.gate_checks is missing required checks"
        )
    if completion.get("status") == "passed":
        if open_gap_ids:
            errors.append("a passed knowledge network cannot have open gaps")
        if not isinstance(checks, dict) or not all(
            checks.get(key) is True for key in required_checks
        ):
            errors.append(
                "a passed knowledge network requires all completion gate checks"
            )
    return errors


def _validate_benchmark(card: Any, index: int, errors: list[str]) -> str | None:
    label = f"benchmarks[{index}]"
    card = _require_keys(
        card,
        (
            "schema",
            "benchmark_id",
            "name",
            "task_modes",
            "model",
            "observation_protocol",
            "evaluation",
            "failure_boundaries",
            "evidence",
        ),
        label,
        errors,
    )
    if card.get("schema") != "BenchmarkProfile/v1":
        errors.append(f"{label}.schema must equal BenchmarkProfile/v1")
    _require_nonempty(card, ("benchmark_id", "name"), label, errors)
    model = _require_keys(
        card.get("model"),
        (
            "equations_or_model_ref",
            "candidate_library",
            "ground_truth",
            "parameters",
            "initial_conditions",
            "inputs_or_perturbations",
        ),
        f"{label}.model",
        errors,
    )
    _require_nonempty(
        model,
        (
            "equations_or_model_ref",
            "candidate_library",
            "ground_truth",
            "parameters",
            "initial_conditions",
            "inputs_or_perturbations",
        ),
        f"{label}.model",
        errors,
    )
    observation = _require_keys(
        card.get("observation_protocol"),
        (
            "observed_states",
            "inputs_or_perturbations",
            "noise",
            "sampling",
            "trajectories",
        ),
        f"{label}.observation_protocol",
        errors,
    )
    _require_nonempty(
        observation,
        (
            "observed_states",
            "inputs_or_perturbations",
            "noise",
            "sampling",
            "trajectories",
        ),
        f"{label}.observation_protocol",
        errors,
    )
    evaluation = _require_keys(
        card.get("evaluation"),
        ("split", "metrics", "equivalence_rule"),
        f"{label}.evaluation",
        errors,
    )
    _require_nonempty(
        evaluation,
        ("split", "equivalence_rule"),
        f"{label}.evaluation",
        errors,
    )
    if not isinstance(evaluation.get("metrics"), list) or not evaluation.get("metrics"):
        errors.append(f"{label}.evaluation.metrics must be a non-empty list")
    if not isinstance(card.get("failure_boundaries"), list) or not card.get(
        "failure_boundaries"
    ):
        errors.append(f"{label}.failure_boundaries must be a non-empty list")
    evidence = _require_keys(
        card.get("evidence"),
        ("source_claim_refs", "exact_locators"),
        f"{label}.evidence",
        errors,
    )
    for field in ("source_claim_refs", "exact_locators"):
        if not isinstance(evidence.get(field), list) or not evidence.get(field):
            errors.append(f"{label}.evidence.{field} must be a non-empty list")
    if not isinstance(card.get("task_modes"), list) or not card.get("task_modes"):
        errors.append(f"{label}.task_modes must be a non-empty list")
    benchmark_id = card.get("benchmark_id")
    return benchmark_id if isinstance(benchmark_id, str) else None


def validate_handoff(document: Any) -> list[str]:
    errors: list[str] = []
    document = _require_keys(
        document,
        (
            "schema",
            "run_id",
            "task_modes",
            "privacy",
            "research",
            "knowledge_network",
            "preflight",
            "items",
            "request",
            "delivery",
        ),
        "handoff",
        errors,
    )
    if document.get("schema") != "ResearchHandoff/v1":
        errors.append("handoff.schema must equal ResearchHandoff/v1")
    _require_nonempty(document, ("run_id",), "handoff", errors)

    task_modes = document.get("task_modes")
    if not isinstance(task_modes, list) or not task_modes:
        errors.append("handoff.task_modes must be a non-empty list")
        modes: set[str] = set()
    else:
        modes = set(task_modes)
        if len(modes) != len(task_modes):
            errors.append("handoff.task_modes must not contain duplicates")
        if not modes.issubset(TASK_MODES) or "research" not in modes:
            errors.append(
                "handoff.task_modes must contain research and only supported modes"
            )

    privacy = _require_keys(
        document.get("privacy"),
        ("classification", "public_export"),
        "privacy",
        errors,
    )
    if privacy.get("classification") != "private":
        errors.append("privacy.classification must be private")
    if privacy.get("public_export") != "redacted_only":
        errors.append("privacy.public_export must be redacted_only")

    research = _require_keys(
        document.get("research"),
        ("status", "contract_ref", "coverage_audit_ref"),
        "research",
        errors,
    )
    if research.get("status") not in RESEARCH_STATES:
        errors.append("research.status is invalid")
    _require_nonempty(
        research,
        ("contract_ref", "coverage_audit_ref"),
        "research",
        errors,
    )

    network_ref = _require_keys(
        document.get("knowledge_network"),
        ("schema", "snapshot_id", "path", "sha256"),
        "knowledge_network_ref",
        errors,
    )
    if network_ref.get("schema") != "KnowledgeNetwork/v1":
        errors.append("knowledge_network_ref.schema must equal KnowledgeNetwork/v1")
    _require_nonempty(
        network_ref, ("snapshot_id",), "knowledge_network_ref", errors
    )
    network_path = _validate_file_digest(
        network_ref.get("path"),
        network_ref.get("sha256"),
        "knowledge_network_ref",
        errors,
    )
    network: dict[str, Any] | None = None
    if network_path is not None:
        try:
            network = json.loads(network_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"knowledge_network_ref.path is not valid UTF-8 JSON: {exc}")
        if network is not None:
            errors.extend(
                validate_knowledge_network(
                    network, zotero_required="zotero" in modes
                )
            )
            if network_ref.get("snapshot_id") != network.get("snapshot_id"):
                errors.append(
                    "knowledge_network_ref.snapshot_id does not match snapshot"
                )
            if (
                research.get("status") == "complete"
                and (network.get("completion") or {}).get("status") != "passed"
            ):
                errors.append(
                    "complete research requires a passed knowledge-network gate"
                )

    compound = bool(modes & {"acquisition", "zotero"})
    preflight = _require_keys(
        document.get("preflight"),
        ("completed", "golden_bundle"),
        "preflight",
        errors,
    )
    if compound and preflight.get("completed") is not True:
        errors.append("compound work requires completed preflight")
    if "zotero" in modes and preflight.get("zotero_corpus_first") is not True:
        errors.append("Zotero work requires zotero_corpus_first=true")
    golden = _require_keys(
        preflight.get("golden_bundle"),
        ("item_id", "status", "bundle_ref", "validation_ref"),
        "preflight.golden_bundle",
        errors,
    )
    _require_nonempty(
        golden,
        ("item_id", "bundle_ref", "validation_ref"),
        "preflight.golden_bundle",
        errors,
    )
    if compound and golden.get("status") != "passed":
        errors.append("compound work requires a passed golden bundle")

    items = document.get("items")
    item_ids: set[str] = set()
    benchmark_references: set[str] = set()
    if not isinstance(items, list) or not items:
        errors.append("items must be a non-empty list")
        items = []
    for index, item in enumerate(items):
        label = f"items[{index}]"
        item = _require_keys(
            item,
            (
                "item_id",
                "source_id",
                "evidence_role",
                "reading_tier",
                "attachments",
            ),
            label,
            errors,
        )
        _require_nonempty(item, ("item_id", "source_id"), label, errors)
        item_id = item.get("item_id")
        if item_id in item_ids:
            errors.append(f"{label}.item_id is duplicated: {item_id}")
        elif isinstance(item_id, str):
            item_ids.add(item_id)
        role = item.get("evidence_role")
        tier = item.get("reading_tier")
        if role not in {"decisive", "supporting", "orientation"}:
            errors.append(f"{label}.evidence_role is invalid")
        if tier not in {"A", "B", "C"}:
            errors.append(f"{label}.reading_tier is invalid")
        if role == "decisive" and tier != "A":
            errors.append(f"{label}: decisive evidence must be Tier A")
        if tier == "A":
            if role != "decisive":
                errors.append(f"{label}: Tier A is reserved for decisive evidence")
            lfp = _require_keys(
                item.get("learn_from_papers"),
                (
                    "paper_card_ref",
                    "evidence_ledger_ref",
                    "locator_audit_ref",
                    "locator_audit_status",
                ),
                f"{label}.learn_from_papers",
                errors,
            )
            _require_nonempty(
                lfp,
                ("paper_card_ref", "evidence_ledger_ref", "locator_audit_ref"),
                f"{label}.learn_from_papers",
                errors,
            )
            if lfp.get("locator_audit_status") != "passed":
                errors.append(f"{label}: Tier A locator audit must be passed")

        attachments = item.get("attachments")
        if not isinstance(attachments, list):
            errors.append(f"{label}.attachments must be a list")
            attachments = []
        for attachment_index, attachment in enumerate(attachments):
            attachment_label = f"{label}.attachments[{attachment_index}]"
            attachment = _require_keys(
                attachment,
                ("attachment_id", "role", "source_kind"),
                attachment_label,
                errors,
            )
            _require_nonempty(
                attachment, ("attachment_id",), attachment_label, errors
            )
            attachment_role = attachment.get("role")
            source_kind = attachment.get("source_kind")
            expected_kind = ATTACHMENT_PAIRS.get(attachment_role)
            if expected_kind is None:
                errors.append(f"{attachment_label}.role is invalid")
            elif source_kind != expected_kind:
                errors.append(
                    f"{attachment_label}: role {attachment_role} requires "
                    f"source_kind {expected_kind}; supplementary information "
                    "cannot be main_text"
                )
            if attachment_role != "metadata_only":
                if not _present(attachment.get("path")):
                    errors.append(f"{attachment_label}.path is required")
                if not HASH_RE.fullmatch(str(attachment.get("sha256") or "")):
                    errors.append(
                        f"{attachment_label}.sha256 must be 64 lowercase hex characters"
                    )

        if item.get("benchmark_use") is True:
            benchmark_ids = item.get("benchmark_ids")
            if not isinstance(benchmark_ids, list) or not benchmark_ids:
                errors.append(
                    f"{label}.benchmark_ids is required when benchmark_use=true"
                )
            else:
                benchmark_references.update(benchmark_ids)

    if golden.get("item_id") not in item_ids:
        errors.append("preflight.golden_bundle.item_id must reference an item")

    benchmarks = document.get("benchmarks", [])
    benchmark_ids: set[str] = set()
    if not isinstance(benchmarks, list):
        errors.append("benchmarks must be a list")
        benchmarks = []
    for index, benchmark in enumerate(benchmarks):
        benchmark_id = _validate_benchmark(benchmark, index, errors)
        if benchmark_id in benchmark_ids:
            errors.append(f"benchmark_id is duplicated: {benchmark_id}")
        elif benchmark_id is not None:
            benchmark_ids.add(benchmark_id)
    if document.get("benchmark_profile_required") is True and not benchmarks:
        errors.append(
            "benchmark_profile_required=true requires at least one benchmark card"
        )
    missing_benchmarks = benchmark_references - benchmark_ids
    if missing_benchmarks:
        errors.append(
            "items reference missing benchmark cards: "
            + ", ".join(sorted(missing_benchmarks))
        )

    request = _require_keys(
        document.get("request"), ("requirements",), "request", errors
    )
    requirements = request.get("requirements")
    expected_rows: set[tuple[str, str, str]] = set()
    external_operations: set[str] = set()
    if not isinstance(requirements, list) or not requirements:
        errors.append("request.requirements must be a non-empty list")
        requirements = []
    requirement_ids: set[str] = set()
    for index, requirement in enumerate(requirements):
        label = f"request.requirements[{index}]"
        requirement = _require_keys(
            requirement,
            ("requirement_id", "required", "item_ids", "operations"),
            label,
            errors,
        )
        _require_nonempty(requirement, ("requirement_id",), label, errors)
        if not isinstance(requirement.get("required"), bool):
            errors.append(f"{label}.required must be boolean")
        requirement_id = requirement.get("requirement_id")
        if requirement_id in requirement_ids:
            errors.append(f"{label}.requirement_id is duplicated: {requirement_id}")
        elif isinstance(requirement_id, str):
            requirement_ids.add(requirement_id)
        requirement_items = requirement.get("item_ids")
        operations = requirement.get("operations")
        if not isinstance(requirement_items, list) or not requirement_items:
            errors.append(f"{label}.item_ids must be a non-empty list")
            requirement_items = []
        if not isinstance(operations, list) or not operations:
            errors.append(f"{label}.operations must be a non-empty list")
            operations = []
        for item_id in requirement_items:
            if item_id not in item_ids:
                errors.append(f"{label}.item_ids references unknown item {item_id}")
        if requirement.get("required") is True and isinstance(requirement_id, str):
            for item_id in requirement_items:
                for operation in operations:
                    expected_rows.add((requirement_id, item_id, operation))
                    if isinstance(operation, str) and operation.startswith(
                        EXTERNAL_PREFIXES
                    ):
                        external_operations.add(operation)

    delivery = _require_keys(
        document.get("delivery"),
        (
            "status",
            "authorization",
            "capability_matrix",
            "curation_batches",
            "completion_matrix",
        ),
        "delivery",
        errors,
    )
    delivery_status = delivery.get("status")
    if delivery_status not in DELIVERY_STATES:
        errors.append("delivery.status is invalid")
    authorization = _require_keys(
        delivery.get("authorization"),
        ("target_approved", "batch_approved", "approval_ref", "target_ref"),
        "delivery.authorization",
        errors,
    )
    if delivery_status == "complete" and (
        authorization.get("target_approved") is not True
        or authorization.get("batch_approved") is not True
    ):
        errors.append("complete delivery requires target and batch approval")
    if delivery_status == "complete":
        _require_nonempty(
            authorization,
            ("approval_ref", "target_ref"),
            "delivery.authorization",
            errors,
        )

    capabilities = delivery.get("capability_matrix")
    if not isinstance(capabilities, list):
        errors.append("delivery.capability_matrix must be a list")
        capabilities = []
    capability_operations: set[str] = set()
    blocked_required_operations: set[str] = set()
    for index, capability in enumerate(capabilities):
        label = f"delivery.capability_matrix[{index}]"
        capability = _require_keys(
            capability,
            ("operation", "required", "status", "paths"),
            label,
            errors,
        )
        _require_nonempty(capability, ("operation",), label, errors)
        if not isinstance(capability.get("required"), bool):
            errors.append(f"{label}.required must be boolean")
        operation = capability.get("operation")
        if operation in capability_operations:
            errors.append(f"{label}.operation is duplicated: {operation}")
        elif isinstance(operation, str):
            capability_operations.add(operation)
        if capability.get("status") not in CAPABILITY_STATES:
            errors.append(f"{label}.status is invalid")
        paths = capability.get("paths")
        if not isinstance(paths, list) or not paths:
            errors.append(f"{label}.paths must be a non-empty list")
            paths = []
        path_ids: set[str] = set()
        failed_paths = 0
        available_paths = 0
        for path_index, path_record in enumerate(paths):
            path_label = f"{label}.paths[{path_index}]"
            path_record = _require_keys(
                path_record,
                ("path_id", "status", "evidence_ref"),
                path_label,
                errors,
            )
            _require_nonempty(
                path_record, ("path_id", "evidence_ref"), path_label, errors
            )
            path_id = path_record.get("path_id")
            if path_id in path_ids:
                errors.append(f"{path_label}.path_id is duplicated: {path_id}")
            elif isinstance(path_id, str):
                path_ids.add(path_id)
            path_status = path_record.get("status")
            if path_status not in PATH_STATES:
                errors.append(f"{path_label}.status is invalid")
            if path_status in {"failed", "unavailable"}:
                failed_paths += 1
            if path_status == "available":
                available_paths += 1
        should_block = failed_paths >= 2 and available_paths == 0
        if should_block and capability.get("status") != "blocked_capability":
            errors.append(
                f"{label}: two failed/unavailable paths with no available path "
                "require blocked_capability"
            )
        if capability.get("status") == "blocked_capability":
            if not should_block:
                errors.append(
                    f"{label}: blocked_capability requires at least two failed "
                    "or unavailable paths and no available path"
                )
            elif capability.get("required") is True and isinstance(operation, str):
                blocked_required_operations.add(operation)
        if available_paths and capability.get("status") == "blocked_capability":
            errors.append(
                f"{label}: an available path is incompatible with blocked_capability"
            )

    missing_capabilities = external_operations - capability_operations
    if missing_capabilities:
        errors.append(
            "required external operations lack capability records: "
            + ", ".join(sorted(missing_capabilities))
        )
    if blocked_required_operations and delivery_status != "blocked_capability":
        errors.append(
            "a blocked required capability requires delivery.status "
            "blocked_capability"
        )
    if (
        delivery_status == "blocked_capability"
        and not blocked_required_operations
    ):
        errors.append(
            "delivery.status blocked_capability requires a blocked required operation"
        )

    batches = delivery.get("curation_batches")
    if not isinstance(batches, list):
        errors.append("delivery.curation_batches must be a list")
        batches = []
    batch_ids: set[str] = set()
    for index, batch in enumerate(batches):
        label = f"delivery.curation_batches[{index}]"
        batch = _require_keys(
            batch,
            ("batch_id", "manifest_path", "sha256", "visibility", "target_ref"),
            label,
            errors,
        )
        _require_nonempty(batch, ("batch_id", "target_ref"), label, errors)
        batch_id = batch.get("batch_id")
        if batch_id in batch_ids:
            errors.append(f"{label}.batch_id is duplicated: {batch_id}")
        elif isinstance(batch_id, str):
            batch_ids.add(batch_id)
        if batch.get("visibility") != "private":
            errors.append(f"{label}.visibility must be private")
        _validate_file_digest(
            batch.get("manifest_path"),
            batch.get("sha256"),
            label.replace("curation_batches", "curation_batch").replace(
                ".manifest_path", ""
            ),
            errors,
        )
    if "zotero" in modes and delivery_status in {"ready", "partial", "complete"}:
        if not batches:
            errors.append(
                "ready, partial, or complete Zotero delivery requires "
                "a CurationBatch reference"
            )

    rows = delivery.get("completion_matrix")
    actual_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not isinstance(rows, list):
        errors.append("delivery.completion_matrix must be a list")
        rows = []
    for index, row in enumerate(rows):
        label = f"delivery.completion_matrix[{index}]"
        row = _require_keys(
            row,
            ("requirement_id", "item_id", "operation", "status", "evidence_refs"),
            label,
            errors,
        )
        _require_nonempty(
            row, ("requirement_id", "item_id", "operation"), label, errors
        )
        key = (row.get("requirement_id"), row.get("item_id"), row.get("operation"))
        if key in actual_rows:
            errors.append(f"{label} duplicates completion row {key}")
        else:
            actual_rows[key] = row
        if row.get("status") not in ROW_STATES:
            errors.append(f"{label}.status is invalid")
        if not isinstance(row.get("evidence_refs"), list):
            errors.append(f"{label}.evidence_refs must be a list")
        elif row.get("status") == "complete" and not row.get("evidence_refs"):
            errors.append(
                f"{label}.evidence_refs must be non-empty for complete rows"
            )
        if row.get("status") != "complete" and not _present(row.get("blocker")):
            errors.append(f"{label}.blocker is required for incomplete rows")

    missing_rows = expected_rows - set(actual_rows)
    if missing_rows:
        formatted = ", ".join(
            "/".join(row) for row in sorted(missing_rows)
        )
        errors.append(f"completion_matrix is missing required rows: {formatted}")
    if delivery_status == "complete":
        incomplete = [
            key
            for key in expected_rows
            if actual_rows.get(key, {}).get("status") != "complete"
        ]
        if incomplete:
            errors.append(
                "complete delivery requires all required completion rows complete"
            )
    if delivery_status == "partial" and expected_rows and all(
        actual_rows.get(key, {}).get("status") == "complete" for key in expected_rows
    ):
        errors.append("partial delivery must retain at least one incomplete row")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a private ResearchHandoff/v1 JSON document."
    )
    parser.add_argument("handoff", type=Path)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.handoff.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"valid": False, "errors": [str(exc)]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    errors = validate_handoff(document)
    print(
        json.dumps(
            {"valid": not errors, "errors": errors},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
