#!/usr/bin/env python3
"""Validate bounded, cross-skill research workflow routes.

This evaluator checks orchestration and authority boundaries. It never performs
network requests, writes Zotero, or mutates a knowledge network.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


PLAN_SCHEMA = "WorkflowRoutePlan/v1"
CASE_SET_SCHEMA = "WorkflowRoutingCaseSet/v1"
REPORT_SCHEMA = "WorkflowRoutingEvaluation/v1"

DEEP = "deep-research"
CURATE = "curate-research-to-zotero"
LEARN = "learn-from-papers"
RKN = "research-knowledge-network"
GAP = "network-gap-discovery"
SCHOLAR = "scholar-discovery"

SKILL_OPERATIONS = {
    DEEP: {"field_map", "orchestrate"},
    CURATE: {
        "inventory_existing_corpus",
        "read_existing_source",
        "onboard_new_source",
    },
    LEARN: {
        "deep_read",
        "prepare_attestations",
        "external_attest",
        "finalize_attestations",
    },
    RKN: {
        "ingest_existing_corpus",
        "onboard_source",
        "snapshot",
        "ingest_decisive_evidence",
        "prepare_patch",
        "apply_patch",
    },
    GAP: {
        "audit_snapshot",
        "emit_search_requests",
        "consume_reviewed_evidence",
        "propose_patch_v2",
    },
    SCHOLAR: {"automatic_discovery", "manual_google_scholar_export"},
}

REQUIRED_REQUEST_CLASSES = {
    "field_only",
    "existing_zotero_corpus",
    "open_world_gap",
    "google_scholar_manual",
    "new_source_patch",
    "decisive_evidence",
    "network_patch_v2",
}


class ContractError(ValueError):
    """Raised when a workflow route violates an orchestration contract."""


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _exact_keys(
    value: dict[str, Any],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise ContractError(f"{label} missing fields: {sorted(missing)}")
    if unknown:
        raise ContractError(f"{label} has unknown fields: {sorted(unknown)}")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    result = [_text(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ContractError(f"{label} must not contain duplicates")
    return result


def _network_ref(value: Any, label: str) -> dict[str, str]:
    ref = _mapping(value, label)
    _exact_keys(ref, {"network_id", "snapshot_id", "sha256"}, set(), label)
    result = {
        "network_id": _text(ref["network_id"], f"{label}.network_id"),
        "snapshot_id": _text(ref["snapshot_id"], f"{label}.snapshot_id"),
        "sha256": _text(ref["sha256"], f"{label}.sha256"),
    }
    digest = result["sha256"]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ContractError(f"{label}.sha256 must be 64 lowercase hex characters")
    return result


def _step_key(step: dict[str, Any]) -> tuple[str, str]:
    return step["skill"], step["operation"]


def _step(plan: dict[str, Any], skill: str, operation: str) -> dict[str, Any]:
    matches = [item for item in plan["steps"] if _step_key(item) == (skill, operation)]
    if len(matches) != 1:
        raise ContractError(
            f"route requires exactly one {skill}.{operation} step; found {len(matches)}"
        )
    return matches[0]


def _ordered(plan: dict[str, Any], expected: list[tuple[str, str]]) -> None:
    positions: list[int] = []
    for key in expected:
        matches = [
            index for index, item in enumerate(plan["steps"]) if _step_key(item) == key
        ]
        if len(matches) != 1:
            raise ContractError(
                f"route requires exactly one {key[0]}.{key[1]} step; "
                f"found {len(matches)}"
            )
        positions.append(matches[0])
    if positions != sorted(positions):
        rendered = " -> ".join(f"{skill}.{operation}" for skill, operation in expected)
        raise ContractError(f"route must preserve order: {rendered}")


def _artifact(step: dict[str, Any], field: str, prefix: str) -> str:
    matches = [item for item in step[field] if item.startswith(prefix)]
    if len(matches) != 1:
        raise ContractError(
            f"{step['step_id']}.{field} requires exactly one {prefix} artifact"
        )
    return matches[0]


def _require_consumes(step: dict[str, Any], artifact: str) -> None:
    if artifact not in step["consumes"]:
        raise ContractError(f"{step['step_id']} must consume {artifact}")


def _validate_step(value: Any, index: int) -> dict[str, Any]:
    label = f"steps[{index}]"
    step = _mapping(value, label)
    _exact_keys(
        step,
        {"step_id", "skill", "operation", "execution", "consumes", "produces"},
        {"provider", "network_ref", "attestation", "governance"},
        label,
    )
    normalized = {
        "step_id": _text(step["step_id"], f"{label}.step_id"),
        "skill": _text(step["skill"], f"{label}.skill"),
        "operation": _text(step["operation"], f"{label}.operation"),
        "execution": _text(step["execution"], f"{label}.execution"),
        "consumes": _string_list(step["consumes"], f"{label}.consumes"),
        "produces": _string_list(step["produces"], f"{label}.produces"),
    }
    if normalized["skill"] not in SKILL_OPERATIONS:
        raise ContractError(f"{label}.skill is unknown")
    if normalized["operation"] not in SKILL_OPERATIONS[normalized["skill"]]:
        raise ContractError(
            f"{label}.operation is not owned by {normalized['skill']}"
        )
    for key in ("provider", "attestation", "governance"):
        if key in step:
            normalized[key] = copy.deepcopy(step[key])
    if "network_ref" in step:
        normalized["network_ref"] = _network_ref(
            step["network_ref"], f"{label}.network_ref"
        )
    return normalized


def _validate_google_policy(plan: dict[str, Any]) -> None:
    for step in plan["steps"]:
        provider = step.get("provider")
        if provider != "google_scholar":
            continue
        if step["skill"] != SCHOLAR:
            raise ContractError("Google Scholar operations are owned by scholar-discovery")
        if step["operation"] != "manual_google_scholar_export":
            raise ContractError("Google Scholar cannot use an automatic operation")
        if step["execution"] != "user_manual_export":
            raise ContractError("Google Scholar execution must be user_manual_export")
    for step in plan["steps"]:
        if (
            step["skill"] == SCHOLAR
            and step["operation"] == "automatic_discovery"
            and step.get("provider") == "google_scholar"
        ):
            raise ContractError("automatic discovery must reject Google Scholar")


def _validate_field_only(plan: dict[str, Any]) -> None:
    if any(step["skill"] != DEEP for step in plan["steps"]):
        raise ContractError("field_only routes must not invent downstream state")
    if not any(step["operation"] == "field_map" for step in plan["steps"]):
        raise ContractError("field_only route requires deep-research.field_map")
    forbidden = ("KnowledgeNetwork/", "NetworkSnapshotRef/", "ZoteroCorpusSnapshot/")
    for step in plan["steps"]:
        if "network_ref" in step:
            raise ContractError("field_only routes must not invent a network_ref")
        if any(item.startswith(forbidden) for item in step["consumes"] + step["produces"]):
            raise ContractError("field_only routes must not invent network or corpus artifacts")


def _validate_existing_corpus(plan: dict[str, Any]) -> None:
    expected = [
        (CURATE, "inventory_existing_corpus"),
        (CURATE, "read_existing_source"),
        (LEARN, "deep_read"),
        (RKN, "ingest_existing_corpus"),
        (RKN, "snapshot"),
    ]
    _ordered(plan, expected)
    inventory = _step(plan, CURATE, "inventory_existing_corpus")
    reading = _step(plan, CURATE, "read_existing_source")
    learning = _step(plan, LEARN, "deep_read")
    ingest = _step(plan, RKN, "ingest_existing_corpus")
    snapshot = _step(plan, RKN, "snapshot")
    corpus = _artifact(inventory, "produces", "ZoteroCorpusSnapshot/v1#")
    source = _artifact(reading, "produces", "PaperSourceBundle/v1#")
    dossier = _artifact(learning, "produces", "PaperReadingDossier/v1#")
    network = _artifact(ingest, "produces", "KnowledgeNetwork/v1#")
    _require_consumes(reading, corpus)
    _require_consumes(learning, source)
    _require_consumes(ingest, corpus)
    _require_consumes(ingest, dossier)
    _require_consumes(snapshot, network)


def _validate_open_world_gap(plan: dict[str, Any]) -> None:
    expected = [
        (RKN, "snapshot"),
        (GAP, "audit_snapshot"),
        (GAP, "emit_search_requests"),
        (SCHOLAR, "automatic_discovery"),
    ]
    _ordered(plan, expected)
    snapshot = _step(plan, RKN, "snapshot")
    audit = _step(plan, GAP, "audit_snapshot")
    emit = _step(plan, GAP, "emit_search_requests")
    discover = _step(plan, SCHOLAR, "automatic_discovery")
    snapshot_artifact = _artifact(snapshot, "produces", "NetworkSnapshotRef/v1#")
    hypotheses = _artifact(audit, "produces", "GapHypothesisSet/v1#")
    requests = _artifact(emit, "produces", "ScholarDiscoveryRequestSet/v1#")
    _require_consumes(audit, snapshot_artifact)
    _require_consumes(emit, snapshot_artifact)
    _require_consumes(emit, hypotheses)
    _require_consumes(discover, requests)
    refs = [snapshot.get("network_ref"), audit.get("network_ref"), emit.get("network_ref")]
    if any(ref is None for ref in refs) or refs[1:] != refs[:-1]:
        raise ContractError("open_world_gap steps must bind one exact network snapshot")


def _validate_google_manual(plan: dict[str, Any]) -> None:
    manual = _step(plan, SCHOLAR, "manual_google_scholar_export")
    if manual.get("provider") != "google_scholar":
        raise ContractError("manual Scholar route must name provider google_scholar")
    if manual["execution"] != "user_manual_export":
        raise ContractError("manual Scholar route must use user_manual_export")


def _validate_new_source(plan: dict[str, Any]) -> None:
    expected = [
        (CURATE, "onboard_new_source"),
        (RKN, "onboard_source"),
        (RKN, "snapshot"),
        (GAP, "propose_patch_v2"),
    ]
    _ordered(plan, expected)
    curate = _step(plan, CURATE, "onboard_new_source")
    onboard = _step(plan, RKN, "onboard_source")
    snapshot = _step(plan, RKN, "snapshot")
    proposal = _step(plan, GAP, "propose_patch_v2")
    curated = _artifact(curate, "produces", "CuratedSource/v1#")
    onboarded = _artifact(onboard, "produces", "OnboardedSourceRef/v1#")
    fresh_snapshot = _artifact(snapshot, "produces", "NetworkSnapshotRef/v1#")
    _require_consumes(onboard, curated)
    _require_consumes(snapshot, onboarded)
    _require_consumes(proposal, fresh_snapshot)
    if snapshot.get("network_ref") is None or proposal.get("network_ref") is None:
        raise ContractError("new-source proposal requires an explicit fresh network_ref")
    if snapshot["network_ref"] != proposal["network_ref"]:
        raise ContractError("proposal must bind the post-onboarding network snapshot")
    _artifact(proposal, "produces", "NetworkPatchProposal/v2#")


def _validate_decisive(plan: dict[str, Any]) -> None:
    expected = [
        (LEARN, "deep_read"),
        (LEARN, "prepare_attestations"),
        (LEARN, "external_attest"),
        (LEARN, "finalize_attestations"),
        (GAP, "consume_reviewed_evidence"),
    ]
    _ordered(plan, expected)
    prepare = _step(plan, LEARN, "prepare_attestations")
    attest = _step(plan, LEARN, "external_attest")
    finalize = _step(plan, LEARN, "finalize_attestations")
    consume = _step(plan, GAP, "consume_reviewed_evidence")
    request = _artifact(prepare, "produces", "VerificationRequestSet/v1#")
    attestation_artifact = _artifact(
        attest, "produces", "VerificationAttestation/v1#"
    )
    finalized = _artifact(
        finalize, "produces", "PaperReadingReportSet/v2#finalized-"
    )
    _require_consumes(attest, request)
    _require_consumes(finalize, request)
    _require_consumes(finalize, attestation_artifact)
    _require_consumes(consume, finalized)
    attestation = _mapping(attest.get("attestation"), "external_attest.attestation")
    _exact_keys(
        attestation,
        {
            "schema",
            "origin",
            "mode",
            "verdict",
            "producer_context_id",
            "verifier_context_id",
        },
        set(),
        "external_attest.attestation",
    )
    if attestation["schema"] != "VerificationAttestation/v1":
        raise ContractError("decisive evidence requires VerificationAttestation/v1")
    if attestation["origin"] != "external_verifier":
        raise ContractError("decisive attestation origin must be external_verifier")
    if attestation["mode"] not in {"independent_source_check", "expert_review"}:
        raise ContractError("decisive attestation mode must be independent or expert")
    if attestation["verdict"] != "passed":
        raise ContractError("decisive attestation verdict must be passed")
    if attestation["producer_context_id"] == attestation["verifier_context_id"]:
        raise ContractError("producer and verifier contexts must differ")


def _validate_patch_governance(plan: dict[str, Any]) -> None:
    expected = [
        (GAP, "propose_patch_v2"),
        (RKN, "prepare_patch"),
        (RKN, "apply_patch"),
    ]
    _ordered(plan, expected)
    proposal = _step(plan, GAP, "propose_patch_v2")
    prepare = _step(plan, RKN, "prepare_patch")
    apply = _step(plan, RKN, "apply_patch")
    proposal_artifact = _artifact(
        proposal, "produces", "NetworkPatchProposal/v2#"
    )
    plan_artifact = _artifact(prepare, "produces", "NetworkPatchPlan/v1#")
    acceptance_artifact = _artifact(
        apply, "consumes", "NetworkPatchAcceptance/v1#"
    )
    _require_consumes(prepare, proposal_artifact)
    _require_consumes(apply, proposal_artifact)
    _require_consumes(apply, plan_artifact)
    governance = _mapping(apply.get("governance"), "apply_patch.governance")
    _exact_keys(
        governance,
        {
            "schema",
            "decision",
            "authorized",
            "operator_scope",
            "operator_id",
            "authority_basis_ids",
            "acceptance_artifact",
        },
        set(),
        "apply_patch.governance",
    )
    if governance["schema"] != "NetworkPatchAcceptance/v1":
        raise ContractError("apply_patch requires NetworkPatchAcceptance/v1")
    if governance["decision"] != "accept" or governance["authorized"] is not True:
        raise ContractError("apply_patch requires an explicit accept authorization")
    if governance["operator_scope"] != "external_governance":
        raise ContractError("patch proposal cannot self-authorize governance")
    _text(governance["operator_id"], "apply_patch.governance.operator_id")
    authority = _string_list(
        governance["authority_basis_ids"],
        "apply_patch.governance.authority_basis_ids",
    )
    if not authority:
        raise ContractError("governance acceptance requires authority_basis_ids")
    if governance["acceptance_artifact"] != acceptance_artifact:
        raise ContractError("governance metadata must bind the consumed acceptance")


PROFILE_VALIDATORS = {
    "field_only": _validate_field_only,
    "existing_zotero_corpus": _validate_existing_corpus,
    "open_world_gap": _validate_open_world_gap,
    "google_scholar_manual": _validate_google_manual,
    "new_source_patch": _validate_new_source,
    "decisive_evidence": _validate_decisive,
    "network_patch_v2": _validate_patch_governance,
}


def validate_plan(value: Any) -> dict[str, Any]:
    plan = _mapping(value, "plan")
    _exact_keys(
        plan,
        {"schema", "route_id", "request_class", "objective", "steps"},
        set(),
        "plan",
    )
    if plan["schema"] != PLAN_SCHEMA:
        raise ContractError(f"plan.schema must be {PLAN_SCHEMA}")
    request_class = _text(plan["request_class"], "plan.request_class")
    if request_class not in PROFILE_VALIDATORS:
        raise ContractError(f"unsupported request_class: {request_class}")
    raw_steps = plan["steps"]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ContractError("plan.steps must be a non-empty array")
    normalized = {
        "schema": PLAN_SCHEMA,
        "route_id": _text(plan["route_id"], "plan.route_id"),
        "request_class": request_class,
        "objective": _text(plan["objective"], "plan.objective"),
        "steps": [_validate_step(step, index) for index, step in enumerate(raw_steps)],
    }
    step_ids = [step["step_id"] for step in normalized["steps"]]
    if len(step_ids) != len(set(step_ids)):
        raise ContractError("step_id values must be unique")
    _validate_google_policy(normalized)
    PROFILE_VALIDATORS[request_class](normalized)
    return normalized


def evaluate_case_set(value: Any) -> dict[str, Any]:
    case_set = _mapping(value, "case_set")
    _exact_keys(case_set, {"schema", "cases"}, set(), "case_set")
    if case_set["schema"] != CASE_SET_SCHEMA:
        raise ContractError(f"case_set.schema must be {CASE_SET_SCHEMA}")
    cases = case_set["cases"]
    if not isinstance(cases, list) or not cases:
        raise ContractError("case_set.cases must be a non-empty array")
    results: list[dict[str, Any]] = []
    case_ids: list[str] = []
    request_classes: set[str] = set()
    skills: set[str] = set()
    for index, raw_case in enumerate(cases):
        case = _mapping(raw_case, f"cases[{index}]")
        _exact_keys(case, {"case_id", "description", "plan"}, set(), f"cases[{index}]")
        case_id = _text(case["case_id"], f"cases[{index}].case_id")
        _text(case["description"], f"cases[{index}].description")
        plan = validate_plan(case["plan"])
        case_ids.append(case_id)
        request_classes.add(plan["request_class"])
        skills.update(step["skill"] for step in plan["steps"])
        results.append(
            {
                "case_id": case_id,
                "request_class": plan["request_class"],
                "passed": True,
                "step_count": len(plan["steps"]),
            }
        )
    if len(case_ids) != len(set(case_ids)):
        raise ContractError("case_id values must be unique")
    if request_classes != REQUIRED_REQUEST_CLASSES:
        missing = sorted(REQUIRED_REQUEST_CLASSES - request_classes)
        extra = sorted(request_classes - REQUIRED_REQUEST_CLASSES)
        raise ContractError(f"release cases have profile mismatch; missing={missing}, extra={extra}")
    if skills != set(SKILL_OPERATIONS):
        missing = sorted(set(SKILL_OPERATIONS) - skills)
        raise ContractError(f"release cases do not cover all six skills: {missing}")
    return {
        "schema": REPORT_SCHEMA,
        "passed": True,
        "case_count": len(results),
        "request_classes": sorted(request_classes),
        "skill_coverage": sorted(skills),
        "results": results,
        "limits": [
            "no_live_network_requests",
            "no_zotero_mutation",
            "no_knowledge_network_mutation",
            "semantic_quality_is_evaluated_elsewhere",
        ],
    }


def _canonical_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_module(name: str, path: Path, import_dir: Path | None = None) -> Any:
    if import_dir is not None:
        sys.path.insert(0, str(import_dir))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ContractError(f"cannot load production module: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if import_dir is not None:
            sys.path.remove(str(import_dir))


def _scholar_request() -> dict[str, Any]:
    return {
        "schema": "ScholarDiscoveryRequest/v1",
        "request_id": "SDR-GAP-001",
        "paper_need": "Find primary studies that test a proposed missing relation",
        "intent": "topic_set",
        "effort": "diligent",
        "criteria": {
            "must": ["target relation"],
            "should": [],
            "must_not": [],
        },
        "metadata_filters": {
            "years": {"from": 2015, "to": 2026},
            "authors": [],
            "venues": [],
            "languages": ["en"],
            "work_types": ["primary_study"],
            "open_access": None,
        },
        "seeds": {
            "doi": [],
            "arxiv": [],
            "pmid": [],
            "openalex": [],
            "semantic_scholar": [],
            "titles": [],
        },
        "routes": {
            "automatic": ["openalex", "semantic_scholar", "crossref"],
            "google_scholar": "manual_optional",
        },
        "budgets": {
            "max_rounds": 3,
            "max_queries": 18,
            "max_candidates": 100,
            "timeout_seconds": 900,
        },
        "query_seeds": [
            {"objective": "confirm", "query": "exact concepts and relation"},
            {
                "objective": "refute",
                "query": "exact concepts failure OR limitation",
            },
        ],
        "as_of": "2026-08-05T00:00:00Z",
        "gap_ref": {"gap_id": "GAP-001", "network_id": "KN-001"},
        "hypothesis_id": "GAP-001",
    }


def _required_subcommand_fields(parser: argparse.ArgumentParser, name: str) -> set[str]:
    subparsers = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if len(subparsers) != 1 or name not in subparsers[0].choices:
        raise ContractError(f"production CLI is missing subcommand {name}")
    return {
        action.dest
        for action in subparsers[0].choices[name]._actions
        if getattr(action, "required", False)
    }


def run_public_contract_probes(repo_root: Path) -> dict[str, bool]:
    """Exercise stable production validators and public CLI gate definitions."""

    scholar_path = repo_root / "skills/scholar-discovery/scripts/scholar_discovery.py"
    gap_path = repo_root / "skills/network-gap-discovery/scripts/network_gap_discovery.py"
    dossier_path = repo_root / "skills/learn-from-papers/scripts/paper_reading_dossier.py"
    patch_path = repo_root / "skills/research-knowledge-network/scripts/network_patch.py"
    scholar = _load_module("workflow_eval_scholar", scholar_path)
    gap = _load_module("workflow_eval_gap", gap_path)
    dossier = _load_module("workflow_eval_dossier", dossier_path)
    patch = _load_module(
        "workflow_eval_patch", patch_path, patch_path.parent
    )

    request = scholar.validate_request(_scholar_request())
    request_set: dict[str, Any] = {
        "schema": "ScholarDiscoveryRequestSet/v1",
        "schema_version": "v1",
        "network_id": "KN-001",
        "network_snapshot_sha256": "a" * 64,
        "network_ref": {
            "network_id": "KN-001",
            "snapshot_id": "snapshot-001",
            "sha256": "a" * 64,
        },
        "generated_at": "2026-08-05T00:10:00Z",
        "requests": [request],
    }
    digest = _canonical_digest(request_set)
    request_set["request_set_digest"] = digest
    request_set["request_set_id"] = "request-set-" + digest[:16]
    scholar.validate_request_set(request_set)
    gap.validate_request_set(request_set)

    query_plan = scholar.compile_plan(request)
    google_queries = [
        item for item in query_plan["queries"] if item["provider"] == "google_scholar"
    ]
    if not google_queries or any(
        item["execution"] != "user_manual_export" for item in google_queries
    ):
        raise ContractError("production Scholar plan lost the manual-export boundary")
    tampered_plan = copy.deepcopy(query_plan)
    next(
        item
        for item in tampered_plan["queries"]
        if item["provider"] == "google_scholar"
    )["execution"] = "documented_api"
    try:
        scholar.validate_plan(tampered_plan, request)
    except Exception:
        scholar_rejected_automation = True
    else:
        raise ContractError("production Scholar validator accepted automatic Scholar")

    dossier_required = _required_subcommand_fields(
        dossier._parser(), "finalize-attestations"
    )
    patch_required = _required_subcommand_fields(patch.build_parser(), "apply-patch")
    if "verification_root" not in dossier_required:
        raise ContractError("finalize-attestations no longer requires verification_root")
    if "acceptance" not in patch_required:
        raise ContractError("apply-patch no longer requires explicit acceptance")

    return {
        "shared_scholar_request_set_validated": True,
        "google_scholar_compiled_as_manual_export": True,
        "google_scholar_automatic_plan_rejected": scholar_rejected_automation,
        "finalize_attestations_requires_verification_root": True,
        "apply_patch_requires_acceptance": True,
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path | None, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(rendered)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-plan")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--input", type=Path, required=True)
    evaluate.add_argument("--output", type=Path)
    evaluate.add_argument("--repo-root", type=Path)
    evaluate.add_argument("--skip-public-probes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-plan":
            result = validate_plan(_read_json(args.input))
        else:
            result = evaluate_case_set(_read_json(args.input))
            if not args.skip_public_probes:
                repo_root = args.repo_root or Path(__file__).resolve().parents[2]
                result["public_contract_probes"] = run_public_contract_probes(repo_root)
        _write_json(args.output, result)
        return 0
    except (ContractError, OSError, json.JSONDecodeError) as error:
        print(f"workflow routing validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
