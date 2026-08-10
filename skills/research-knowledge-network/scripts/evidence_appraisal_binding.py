#!/usr/bin/env python3
"""Owner-derived appraisal bindings and reviewed exact-operation projections."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BINDING_SCHEMA = "EvidenceAppraisalBinding/v1"
PROJECTION_SCHEMA = "EvidenceAppraisalNetworkProjection/v1"
PROJECTION_REVIEW_SCHEMA = "EvidenceAppraisalProjectionReview/v1"
SCHEMA_VERSION = "1.0"
HEX64_RE = re.compile(r"[0-9a-f]{64}")
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
LEDGER_NAMES = (
    "sources",
    "entities",
    "claims",
    "evidence",
    "relations",
    "gaps",
    "events",
)
NETWORK_SCOPE_FIELDS = (
    "scope_statement",
    "assumptions",
    "conditions",
    "units",
    "exclusions",
    "defeaters",
    "coverage_dimensions",
    "benchmark_profiles",
)
PROJECTION_DECISIONS = {"authorize", "reject", "defer"}
SCOPE_ALIGNMENTS = {"match", "mismatch", "unresolved"}
PROJECTED_RELATIONS = {"supports", "contradicts", "qualifies", "context"}
GAP_STATUS_TRANSITIONS = {
    "open": {"resolved", "blocked"},
    "resolved": {"open"},
    "blocked": {"open", "resolved"},
}
GAP_TRANSITION_FIELDS = {
    "gap_id",
    "from_record_id",
    "from_status",
    "to_status",
    "reason",
    "evidence_refs",
    "resolution_source",
    "basis_appraisal_refs",
    "basis_need_refs",
}


class BindingError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def without(value: dict[str, Any], *fields: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in fields}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BindingError(f"{label} must be an object")
    return value


def _keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise BindingError(
            f"{label} fields mismatch; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BindingError(f"{label} must be a non-empty string")
    return value.strip()


def _digest(value: Any, label: str) -> str:
    text = _string(value, label)
    if not HEX64_RE.fullmatch(text):
        raise BindingError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _timestamp(value: Any, label: str) -> str:
    text = _string(value, label)
    if not UTC_RE.fullmatch(text):
        raise BindingError(f"{label} must be second-precision UTC")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise BindingError(f"{label} is not a valid timestamp") from exc
    return text


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise BindingError(f"{label} contains duplicates")


def _attach(
    value: dict[str, Any], id_field: str, digest_field: str, prefix: str
) -> dict[str, Any]:
    result = copy.deepcopy(value)
    digest = digest_json(without(result, id_field, digest_field))
    result[digest_field] = digest
    result[id_field] = prefix + digest[:16]
    return result


def load_appraisal_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "evidence-appraisal"
        / "scripts"
        / "evidence_appraisal.py"
    )
    name = "rkn_evidence_appraisal_owner"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BindingError(f"evidence-appraisal owner unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "validate_appraisal_package", None)):
        raise BindingError("evidence-appraisal package owner API is unavailable")
    return module


def load_json_stable(path_value: str, label: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise BindingError(f"{label} must be a regular non-symlink file")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    fingerprint = lambda stat: (  # noqa: E731
        stat.st_dev,
        stat.st_ino,
        stat.st_mode,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )
    if fingerprint(before) != fingerprint(after):
        raise BindingError(f"{label} changed while it was read")
    try:
        return _object(json.loads(raw), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError(f"{label} is not valid UTF-8 JSON") from exc


def validate_network_ref(value: Any, label: str = "network_ref") -> dict[str, str]:
    ref = _object(value, label)
    _keys(ref, {"network_id", "snapshot_id", "sha256"}, label)
    return {
        "network_id": _string(ref["network_id"], f"{label}.network_id"),
        "snapshot_id": _string(ref["snapshot_id"], f"{label}.snapshot_id"),
        "sha256": _digest(ref["sha256"], f"{label}.sha256"),
    }


def validate_prefix_guard(value: Any) -> dict[str, Any]:
    guard = _object(value, "binding.network_guard")
    _keys(guard, {"state", "ledgers"}, "binding.network_guard")
    state = _object(guard["state"], "binding.network_guard.state")
    _keys(state, {"size", "sha256"}, "binding.network_guard.state")
    if type(state["size"]) is not int or state["size"] < 0:
        raise BindingError("binding.network_guard.state.size is invalid")
    _digest(state["sha256"], "binding.network_guard.state.sha256")
    ledgers = _object(guard["ledgers"], "binding.network_guard.ledgers")
    _keys(ledgers, set(LEDGER_NAMES), "binding.network_guard.ledgers")
    for name in LEDGER_NAMES:
        item = _object(ledgers[name], f"binding.network_guard.ledgers.{name}")
        _keys(
            item,
            {"record_count", "byte_size", "sha256"},
            f"binding.network_guard.ledgers.{name}",
        )
        if type(item["record_count"]) is not int or item["record_count"] < 0:
            raise BindingError(
                f"binding.network_guard.ledgers.{name}.record_count invalid"
            )
        if type(item["byte_size"]) is not int or item["byte_size"] < 0:
            raise BindingError(
                f"binding.network_guard.ledgers.{name}.byte_size invalid"
            )
        _digest(item["sha256"], f"binding.network_guard.ledgers.{name}.sha256")
    return copy.deepcopy(guard)


def validate_proposal_integrity(value: Any) -> dict[str, Any]:
    proposal = _object(value, "proposal")
    _keys(
        proposal,
        {
            "schema",
            "schema_version",
            "proposal_id",
            "proposal_digest",
            "network_ref",
            "request_ref",
            "generated_at",
            "proposal_only",
            "novelty_claimed",
            "review_gate",
            "actions",
        },
        "proposal",
    )
    if (
        proposal["schema"] != "NetworkPatchProposal/v2"
        or proposal["schema_version"] != "2.0"
    ):
        raise BindingError("appraisal binding requires NetworkPatchProposal/v2")
    validate_network_ref(proposal["network_ref"], "proposal.network_ref")
    actions = proposal["actions"]
    if not isinstance(actions, list):
        raise BindingError("proposal.actions must be a list")
    action_ids: list[str] = []
    for action_index, action_value in enumerate(actions):
        label = f"proposal.actions[{action_index}]"
        action = _object(action_value, label)
        action_digest = _digest(action.get("action_digest"), f"{label}.action_digest")
        if action.get("action_id") != "network-patch-action-" + action_digest[:16]:
            raise BindingError(f"{label}.action_id mismatch")
        if digest_json(without(action, "action_id", "action_digest")) != action_digest:
            raise BindingError(f"{label}.action_digest mismatch")
        bases = action.get("reviewed_evidence")
        if not isinstance(bases, list) or not bases:
            raise BindingError(f"{label}.reviewed_evidence must be non-empty")
        for basis_index, basis_value in enumerate(bases):
            basis_label = f"{label}.reviewed_evidence[{basis_index}]"
            basis = _object(basis_value, basis_label)
            basis_digest = _digest(
                basis.get("basis_digest"), f"{basis_label}.basis_digest"
            )
            if basis.get("basis_id") != "network-patch-basis-" + basis_digest[:16]:
                raise BindingError(f"{basis_label}.basis_id mismatch")
            if digest_json(without(basis, "basis_id", "basis_digest")) != basis_digest:
                raise BindingError(f"{basis_label}.basis_digest mismatch")
        if action.get("action_type") == "propose_relation":
            target = _object(action.get("target_claim"), f"{label}.target_claim")
            scope = _object(target.get("scope"), f"{label}.target_claim.scope")
            if target.get("scope_digest") != digest_json(scope):
                raise BindingError(f"{label}.target_claim.scope_digest mismatch")
        action_ids.append(str(action["action_id"]))
    _unique(action_ids, "proposal action IDs")
    proposal_digest = _digest(proposal["proposal_digest"], "proposal.proposal_digest")
    if (
        digest_json(without(proposal, "proposal_id", "proposal_digest"))
        != proposal_digest
    ):
        raise BindingError("proposal.proposal_digest mismatch")
    if proposal["proposal_id"] != "network-patch-proposal-" + proposal_digest[:16]:
        raise BindingError("proposal.proposal_id mismatch")
    return proposal


def _validated_appraisal_package(
    package_value: Any,
    approval_value: Any,
    prepared_value: Any,
    independent_review_value: Any,
    owner_bundle_value: Any,
    lineage_values: list[Any],
    expected_authority_sha256: str,
) -> dict[str, Any]:
    module = load_appraisal_module()
    try:
        return module.validate_appraisal_package(
            package_value,
            approval_value,
            prepared_value,
            independent_review_value,
            owner_bundle_value,
            expected_authority_sha256=_digest(
                expected_authority_sha256, "expected_authority_sha256"
            ),
            lineage=lineage_values,
        )
    except module.ContractError as exc:
        raise BindingError(
            f"EvidenceAppraisalPackage/v1 owner replay failed: {exc}"
        ) from exc


def _allowed_relation(appraisal: dict[str, Any]) -> str | None:
    verdict = appraisal["relation_verdict"]
    overall = appraisal["overall"]
    domains = appraisal["domain_verdicts"]
    if any(state == "defeated" for state in domains.values()):
        return None
    if verdict in {"not_tested", "unresolved"}:
        return None
    if overall == "decisive_within_scope":
        if not any(
            item.get("state") == "passed" and item.get("decisive") is True
            for item in appraisal["attestation_refs"]
        ):
            return None
        return verdict if verdict in {"supports", "contradicts"} else None
    if overall == "qualified_only":
        return (
            "qualifies" if verdict in {"supports", "qualifies", "contradicts"} else None
        )
    if overall == "context_only":
        return "context"
    return None


def _trusted_owner_attestation_lineages(
    appraisal_set: dict[str, Any],
    lineage_values: list[Any],
    expected_owner_digests: list[str],
) -> tuple[dict[str, str], set[str]]:
    """Rebuild the sealed owner-attestation to lineage projection.

    The owner package validator has already replayed this universe.  Rebuilding it
    here keeps RKN's independence grouping tied to the sealed owner bindings,
    rather than to an arbitrary value supplied in ``source_lineage``.
    """
    sets = [appraisal_set]
    for index, raw in enumerate(lineage_values):
        sets.append(_object(raw, f"lineage[{index}]"))

    bindings_by_digest: dict[str, dict[str, Any]] = {}
    for set_index, appraisal in enumerate(sets):
        raw_bindings = appraisal.get("owner_artifact_bindings")
        if not isinstance(raw_bindings, list) or not raw_bindings:
            raise BindingError(
                f"sealed appraisal set {set_index} lacks owner artifact bindings"
            )
        for binding_index, raw in enumerate(raw_bindings):
            binding = _object(
                raw,
                f"sealed appraisal set {set_index}.owner_artifact_bindings["
                f"{binding_index}]",
            )
            binding_digest = digest_json(binding)
            existing = bindings_by_digest.get(binding_digest)
            if existing is not None:
                if existing != binding:
                    raise BindingError("sealed owner binding digest collision")
                continue
            bindings_by_digest[binding_digest] = binding

    if set(bindings_by_digest) != set(expected_owner_digests):
        raise BindingError(
            "sealed appraisals do not expose the exact package owner binding universe"
        )

    passed_attestation_lineages: dict[str, str] = {}
    owner_lineage_ids: set[str] = set()
    for binding_digest, binding in bindings_by_digest.items():
        lineage_id = _string(
            binding.get("lineage_id"),
            f"owner binding {binding_digest}.lineage_id",
        )
        owner_lineage_ids.add(lineage_id)
        role = _string(binding.get("role"), f"owner binding {binding_digest}.role")
        if role != "attestation":
            continue
        status = _string(
            binding.get("status"), f"owner binding {binding_digest}.status"
        )
        if status == "passed":
            passed_attestation_lineages[binding_digest] = lineage_id
        elif status != "not_tested":
            raise BindingError(
                f"owner attestation {binding_digest} has a non-terminal status"
            )
    if not passed_attestation_lineages:
        raise BindingError("sealed owner universe has no passed external attestations")
    return passed_attestation_lineages, owner_lineage_ids


def _trusted_owner_lineage_for_appraisal(
    appraisal: dict[str, Any],
    passed_attestation_lineages: dict[str, str],
    owner_lineage_ids: set[str],
) -> str:
    refs = appraisal.get("attestation_refs")
    if not isinstance(refs, list) or not refs:
        raise BindingError("appraisal lacks owner-attested lineage evidence")

    selected_digests: list[str] = []
    selected_lineages: set[str] = set()
    for index, raw in enumerate(refs):
        ref = _object(raw, f"appraisal.attestation_refs[{index}]")
        digest = _digest(
            ref.get("owner_attestation_binding_digest"),
            f"appraisal.attestation_refs[{index}].owner_attestation_binding_digest",
        )
        lineage_id = passed_attestation_lineages.get(digest)
        if lineage_id is None:
            raise BindingError(
                "appraisal attestation reference must bind a passed owner attestation"
            )
        selected_digests.append(digest)
        selected_lineages.add(lineage_id)
    if len(selected_digests) != len(set(selected_digests)):
        raise BindingError("appraisal repeats an owner attestation binding")
    if len(selected_lineages) != 1:
        raise BindingError("appraisal attestation references cross owner lineages")
    owner_lineage_id = next(iter(selected_lineages))

    source_lineage = appraisal.get("source_lineage")
    if not isinstance(source_lineage, list) or not source_lineage:
        raise BindingError("appraisal.source_lineage must be a non-empty list")
    declared_owner_lineages = {
        _string(item, f"appraisal.source_lineage[{index}]")
        for index, item in enumerate(source_lineage)
        if isinstance(item, str) and item.strip() in owner_lineage_ids
    }
    if declared_owner_lineages != {owner_lineage_id}:
        raise BindingError(
            "appraisal.source_lineage must select exactly its passed owner lineage"
        )
    return owner_lineage_id


def _network_scope(
    action: dict[str, Any],
    basis: dict[str, Any],
    claim_scopes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if action.get("action_type") == "propose_relation":
        scope = action["target_claim"]["scope"]
    else:
        scope = claim_scopes.get(str(basis.get("claim_id")))
        if scope is None:
            raise BindingError(
                f"current claim scope unavailable for {basis.get('claim_id')!r}"
            )
    scope = _object(scope, "network claim scope")
    _keys(scope, set(NETWORK_SCOPE_FIELDS), "network claim scope")
    return copy.deepcopy(scope)


def mutation_subject_digest(operation_type: str, payload: dict[str, Any]) -> str:
    return digest_json({"operation_type": operation_type, "payload": payload})


def _authorization_digest(operation_type: str, subject_digest: str) -> str:
    return digest_json(
        {"operation_type": operation_type, "mutation_subject_digest": subject_digest}
    )


def _relation_id(action: dict[str, Any], basis: dict[str, Any], relation: str) -> str:
    return (
        "relation-"
        + digest_json(
            {
                "target_signature": action["target_signature"],
                "target_claim_id": action["target_claim"]["claim_id"],
                "basis_id": basis["basis_id"],
                "basis_digest": basis["basis_digest"],
                "evidence_id": basis["evidence_id"],
                "relation_type": relation,
            }
        )[:16]
    )


def _route(
    operation_type: str,
    payload: dict[str, Any],
    row_ids: list[str],
    target_refs: dict[str, str | None],
) -> dict[str, Any]:
    subject_digest = mutation_subject_digest(operation_type, payload)
    return {
        "operation_type": operation_type,
        "authorization_digest": _authorization_digest(operation_type, subject_digest),
        "mutation_subject_digest": subject_digest,
        "binding_row_ids": row_ids,
        "target_refs": target_refs,
    }


def _transition_basis(package: dict[str, Any]) -> dict[str, Any]:
    appraisal_set = package["appraisal_set"]
    return {
        "cycle": appraisal_set["cycle"],
        "prior_cycle_ref": copy.deepcopy(appraisal_set["prior_cycle_ref"]),
        "appraisals": [
            {
                "appraisal_ref": {
                    "appraisal_id": item["appraisal_id"],
                    "semantic_digest": item["semantic_digest"],
                },
                "claim_ref": item["claim_ref"],
                "evidence_ref": item["evidence_ref"],
                "relation_verdict": item["relation_verdict"],
                "overall": item["overall"],
                "supersedes_prior_appraisal_ref": copy.deepcopy(
                    item["supersedes_prior_appraisal_ref"]
                ),
            }
            for item in appraisal_set["relation_appraisals"]
        ],
        "unresolved_needs": [
            {
                "need_ref": {
                    "need_id": item["need_id"],
                    "semantic_digest": item["semantic_digest"],
                },
                "route": item["route"],
                "relation_ref": copy.deepcopy(item["relation_ref"]),
            }
            for item in package["targeted_evidence_need_set"]["needs"]
        ],
        "challenges": [
            {
                "challenge_ref": {
                    "challenge_id": item["challenge_id"],
                    "semantic_digest": item["semantic_digest"],
                },
                "axis": item["axis"],
                "route": item["route"],
                "status": item["status"],
                "relation_ref": copy.deepcopy(item["relation_ref"]),
            }
            for item in package["challenges"]
        ],
    }


def _sorted_digest_refs(
    value: Any,
    id_field: str,
    digest_field: str,
    label: str,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise BindingError(f"{label} must be a list")
    refs: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        item = _object(raw, item_label)
        _keys(item, {id_field, digest_field}, item_label)
        refs.append(
            {
                id_field: _string(item[id_field], f"{item_label}.{id_field}"),
                digest_field: _digest(
                    item[digest_field], f"{item_label}.{digest_field}"
                ),
            }
        )
    expected = sorted(refs, key=lambda item: (item[id_field], item[digest_field]))
    if refs != expected:
        raise BindingError(f"{label} must be sorted")
    _unique(
        [f"{item[id_field]}:{item[digest_field]}" for item in refs],
        label,
    )
    return refs


def _validate_gap_transition_review(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    transition = _object(value, label)
    _keys(transition, GAP_TRANSITION_FIELDS, label)
    for field in ("gap_id", "from_record_id", "from_status", "to_status", "reason"):
        _string(transition[field], f"{label}.{field}")
    if transition["to_status"] not in GAP_STATUS_TRANSITIONS.get(
        transition["from_status"], set()
    ):
        raise BindingError(f"{label} has an invalid status transition")
    evidence_refs = transition["evidence_refs"]
    if not isinstance(evidence_refs, list) or not all(
        isinstance(item, str) and item.strip() for item in evidence_refs
    ):
        raise BindingError(f"{label}.evidence_refs must be non-empty strings")
    if evidence_refs != sorted(set(evidence_refs)):
        raise BindingError(f"{label}.evidence_refs must be sorted and unique")
    if (
        not isinstance(transition["resolution_source"], str)
        or transition["resolution_source"] != transition["resolution_source"].strip()
    ):
        raise BindingError(f"{label}.resolution_source must be a canonical string")
    _sorted_digest_refs(
        transition["basis_appraisal_refs"],
        "appraisal_id",
        "semantic_digest",
        f"{label}.basis_appraisal_refs",
    )
    _sorted_digest_refs(
        transition["basis_need_refs"],
        "need_id",
        "semantic_digest",
        f"{label}.basis_need_refs",
    )
    return copy.deepcopy(transition)


def _transition_subject(transition: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_type": "transition-gap",
        **{
            key: copy.deepcopy(transition[key])
            for key in (
                "gap_id",
                "from_record_id",
                "from_status",
                "to_status",
                "reason",
                "evidence_refs",
                "resolution_source",
            )
        },
    }


def _transition_route(
    transition: dict[str, Any],
    action: dict[str, Any],
    action_binding: dict[str, Any],
    rows: dict[str, dict[str, Any]],
    relation_reviews: list[dict[str, Any]],
    transition_basis: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    if transition["gap_id"] != action["hypothesis_id"]:
        raise BindingError(f"{label} gap transition targets another action")
    action_rows = [rows[row_id] for row_id in action_binding["binding_row_ids"]]
    rows_by_appraisal = {
        (
            row["appraisal_ref"]["appraisal_id"],
            row["appraisal_ref"]["semantic_digest"],
        ): row
        for row in action_rows
    }
    appraisal_refs = transition["basis_appraisal_refs"]
    selected_rows: list[dict[str, Any]] = []
    for ref in appraisal_refs:
        row = rows_by_appraisal.get((ref["appraisal_id"], ref["semantic_digest"]))
        if row is None:
            raise BindingError(f"{label} appraisal basis crosses proposal actions")
        selected_rows.append(row)

    needs_by_ref = {
        (item["need_ref"]["need_id"], item["need_ref"]["semantic_digest"]): item
        for item in transition_basis["unresolved_needs"]
    }
    selected_needs: list[dict[str, Any]] = []
    need_rows: list[dict[str, Any]] = []
    for ref in transition["basis_need_refs"]:
        need = needs_by_ref.get((ref["need_id"], ref["semantic_digest"]))
        if need is None:
            raise BindingError(
                f"{label} need basis is not active in this appraisal set"
            )
        relation_ref = need["relation_ref"]
        row = rows_by_appraisal.get(
            (relation_ref["appraisal_id"], relation_ref["semantic_digest"])
        )
        if row is None or (row["upstream_claim_ref"], row["evidence_ref"]) != (
            relation_ref["claim_ref"],
            relation_ref["evidence_ref"],
        ):
            raise BindingError(f"{label} need basis crosses proposal actions")
        selected_needs.append(need)
        need_rows.append(row)

    to_status = transition["to_status"]
    bound_rows: list[dict[str, Any]]
    if to_status == "resolved":
        if transition["basis_need_refs"] or not selected_rows:
            raise BindingError(
                f"{label} resolved transition requires appraisal bases only"
            )
        if any(
            row["overall"] not in {"decisive_within_scope", "qualified_only"}
            or not row["mutation_eligible"]
            for row in selected_rows
        ):
            raise BindingError(
                f"{label} resolved transition requires admissible in-scope appraisal bases"
            )
        reviews_by_row = {item["binding_row_id"]: item for item in relation_reviews}
        if any(
            reviews_by_row.get(row["binding_row_id"]) is None
            or reviews_by_row[row["binding_row_id"]]["scope_alignment"] != "match"
            or reviews_by_row[row["binding_row_id"]]["projected_relation"]
            != row["allowed_relation"]
            for row in selected_rows
        ):
            raise BindingError(
                f"{label} resolved transition requires scope-matched relation projections"
            )
        expected_evidence = sorted({row["evidence_ref"] for row in selected_rows})
        if not expected_evidence or transition["evidence_refs"] != expected_evidence:
            raise BindingError(
                f"{label} resolved transition evidence must exactly match appraisal bases"
            )
        bound_rows = selected_rows
    elif to_status == "blocked":
        if (
            selected_rows
            or not selected_needs
            or transition["evidence_refs"]
            or transition["resolution_source"]
        ):
            raise BindingError(
                f"{label} blocked transition requires unresolved need bases only"
            )
        bound_rows = need_rows
    else:
        if (
            transition["basis_need_refs"]
            or not selected_rows
            or transition["evidence_refs"]
            or transition["resolution_source"]
            or transition_basis["cycle"] <= 0
        ):
            raise BindingError(
                f"{label} reopen requires new-cycle superseding appraisal bases"
            )
        appraisal_meta = {
            (
                item["appraisal_ref"]["appraisal_id"],
                item["appraisal_ref"]["semantic_digest"],
            ): item
            for item in transition_basis["appraisals"]
        }
        challenges = transition_basis["challenges"]
        for ref in appraisal_refs:
            identity = (ref["appraisal_id"], ref["semantic_digest"])
            item = appraisal_meta.get(identity)
            if item is None or item["supersedes_prior_appraisal_ref"] is None:
                raise BindingError(
                    f"{label} reopen appraisal does not supersede the prior cycle"
                )
            if not any(
                challenge["status"] in {"open", "not_tested"}
                and (
                    challenge["relation_ref"]["appraisal_id"],
                    challenge["relation_ref"]["semantic_digest"],
                )
                == identity
                for challenge in challenges
            ):
                raise BindingError(
                    f"{label} reopen appraisal lacks a current open challenge"
                )
        bound_rows = selected_rows

    subject = _transition_subject(transition)
    return {
        "operation_type": "transition-gap",
        "authorization_digest": digest_json(subject),
        "mutation_subject_digest": None,
        "binding_row_ids": [row["binding_row_id"] for row in bound_rows],
        "target_refs": {
            "claim_id": bound_rows[0]["network_claim_ref"],
            "evidence_id": None,
            "source_id": None,
            "gap_id": transition["gap_id"],
        },
        "basis_appraisal_refs": copy.deepcopy(transition["basis_appraisal_refs"]),
        "basis_need_refs": copy.deepcopy(transition["basis_need_refs"]),
    }


def _build_rows_and_actions(
    appraisal_set: dict[str, Any],
    proposal: dict[str, Any],
    claim_scopes: dict[str, dict[str, Any]],
    passed_attestation_lineages: dict[str, str],
    owner_lineage_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    appraisals: dict[tuple[str, str], dict[str, Any]] = {}
    for appraisal in appraisal_set["relation_appraisals"]:
        identity = (appraisal["claim_ref"], appraisal["evidence_ref"])
        # Owner validation proves that repeated identities form an exact
        # immutable supersession chain. The final row is the current verdict.
        appraisals[identity] = appraisal

    rows: list[dict[str, Any]] = []
    action_bindings: list[dict[str, Any]] = []
    for action in proposal["actions"]:
        action_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for basis in action["reviewed_evidence"]:
            appraisal = appraisals.get((basis["claim_id"], basis["evidence_id"]))
            if appraisal is None:
                raise BindingError(
                    f"finalized appraisal set does not cover basis {basis['basis_id']}"
                )
            locator_match = any(
                locator["locator"] == basis["evidence_locator"]
                and locator["source_ref"] in {basis["source_id"], basis["source_ref"]}
                for locator in appraisal["locator_refs"]
            )
            if not locator_match:
                raise BindingError("appraisal lacks the proposal basis exact locator")
            owner_lineage_id = _trusted_owner_lineage_for_appraisal(
                appraisal,
                passed_attestation_lineages,
                owner_lineage_ids,
            )
            lineage_digest = digest_json({"owner_lineage_id": owner_lineage_id})
            relation = _allowed_relation(appraisal)
            network_claim_ref = (
                action["target_claim"]["claim_id"]
                if action["action_type"] == "propose_relation"
                else basis["claim_id"]
            )
            row = _attach(
                {
                    "schema": "EvidenceAppraisalBindingRow/v1",
                    "binding_row_id": "",
                    "binding_row_digest": "",
                    "action_id": action["action_id"],
                    "action_digest": action["action_digest"],
                    "basis_id": basis["basis_id"],
                    "basis_digest": basis["basis_digest"],
                    "appraisal_ref": {
                        "appraisal_id": appraisal["appraisal_id"],
                        "semantic_digest": appraisal["semantic_digest"],
                    },
                    "upstream_claim_ref": basis["claim_id"],
                    "network_claim_ref": network_claim_ref,
                    "evidence_ref": basis["evidence_id"],
                    "source_ref": basis["source_id"],
                    "relation_verdict": appraisal["relation_verdict"],
                    "overall": appraisal["overall"],
                    "appraisal_scope_digest": digest_json(appraisal["scope"]),
                    "network_scope_digest": digest_json(
                        _network_scope(action, basis, claim_scopes)
                    ),
                    "owner_lineage_id": owner_lineage_id,
                    "source_lineage_digest": lineage_digest,
                    "independence_group": "owner-lineage-" + lineage_digest[:16],
                    "allowed_relation": relation,
                    "mutation_eligible": relation
                    in {
                        "supports",
                        "contradicts",
                        "qualifies",
                    },
                },
                "binding_row_id",
                "binding_row_digest",
                "appraisal-binding-row-",
            )
            rows.append(row)
            action_rows.append((row, basis))

        eligible = all(row["mutation_eligible"] for row, _ in action_rows)
        routes: list[dict[str, Any]] = []
        if eligible and action["action_type"] == "propose_relation":
            target = action["target_claim"]
            claim_payload = {
                "claim_id": target["claim_id"],
                "claim_text": target["claim_text"],
                "entity_id": target["entity_id"],
                "impact": target["impact"],
                "is_factual": False,
                "scope_statement": target["scope"]["scope_statement"],
                "assumptions": target["scope"]["assumptions"],
                "conditions": target["scope"]["conditions"],
                "units": target["scope"]["units"],
                "exclusions": target["scope"]["exclusions"],
                "defeaters": target["scope"]["defeaters"],
                "coverage_dimensions": target["coverage_dimensions"],
                "benchmark_profiles": target["benchmark_profiles"],
                "supersedes": target["supersedes"],
            }
            routes.append(
                _route(
                    "add-claim",
                    claim_payload,
                    [row["binding_row_id"] for row, _ in action_rows],
                    {
                        "claim_id": target["claim_id"],
                        "evidence_id": None,
                        "source_id": None,
                        "gap_id": None,
                    },
                )
            )
        if eligible:
            for row, basis in action_rows:
                relation = row["allowed_relation"]
                evidence_payload = {
                    "evidence_id": basis["evidence_id"],
                    "claim_id": row["network_claim_ref"],
                    "source_id": basis["source_id"],
                    "polarity": relation,
                    "exact_locator": basis["evidence_locator"],
                    "independence_group": row["independence_group"],
                    "summary": action["hypothesis"],
                    "notes": "accepted from NetworkPatchProposal/v2",
                    "supersedes": None,
                }
                routes.append(
                    _route(
                        "add-evidence",
                        evidence_payload,
                        [row["binding_row_id"]],
                        {
                            "claim_id": row["network_claim_ref"],
                            "evidence_id": basis["evidence_id"],
                            "source_id": basis["source_id"],
                            "gap_id": None,
                        },
                    )
                )
                if action["action_type"] == "propose_relation":
                    relation_payload = {
                        "relation_id": _relation_id(action, basis, relation),
                        "relation_type": relation,
                        "from": "claim:" + row["network_claim_ref"],
                        "to": "evidence:" + basis["evidence_id"],
                        "notes": "network-patch-action:" + action["action_digest"],
                        "supersedes": None,
                    }
                    routes.append(
                        _route(
                            "add-relation",
                            relation_payload,
                            [row["binding_row_id"]],
                            {
                                "claim_id": row["network_claim_ref"],
                                "evidence_id": basis["evidence_id"],
                                "source_id": basis["source_id"],
                                "gap_id": None,
                            },
                        )
                    )
        action_bindings.append(
            _attach(
                {
                    "action_binding_id": "",
                    "action_binding_digest": "",
                    "action_id": action["action_id"],
                    "action_digest": action["action_digest"],
                    "binding_row_ids": [
                        row["binding_row_id"] for row, _ in action_rows
                    ],
                    "mutation_routes": routes,
                },
                "action_binding_id",
                "action_binding_digest",
                "appraisal-action-binding-",
            )
        )
    return rows, action_bindings


def create_binding(
    package_value: Any,
    approval_value: Any,
    prepared_value: Any,
    independent_review_value: Any,
    owner_bundle_value: Any,
    lineage_values: list[Any],
    expected_authority_sha256: str,
    proposal_value: Any,
    network_ref_value: Any,
    network_guard_value: Any,
    claim_scopes: dict[str, dict[str, Any]],
    *,
    bound_at: str,
) -> dict[str, Any]:
    package = _validated_appraisal_package(
        package_value,
        approval_value,
        prepared_value,
        independent_review_value,
        owner_bundle_value,
        lineage_values,
        expected_authority_sha256,
    )
    appraisal = package["appraisal_set"]
    prepared = _object(prepared_value, "prepared")
    independent_review = _object(independent_review_value, "independent review")
    owner_digests = package.get("owner_artifact_binding_digests")
    if (
        not isinstance(owner_digests, list)
        or not owner_digests
        or any(
            not isinstance(item, str) or not HEX64_RE.fullmatch(item)
            for item in owner_digests
        )
        or len(owner_digests) != len(set(owner_digests))
    ):
        raise BindingError(
            "validated appraisal package owner binding digests are invalid"
        )
    proposal = validate_proposal_integrity(proposal_value)
    network_ref = validate_network_ref(network_ref_value)
    if proposal["network_ref"] != network_ref:
        raise BindingError("proposal network_ref does not match current network")
    passed_attestation_lineages, owner_lineage_ids = (
        _trusted_owner_attestation_lineages(
            appraisal,
            lineage_values,
            owner_digests,
        )
    )
    rows, actions = _build_rows_and_actions(
        appraisal,
        proposal,
        claim_scopes,
        passed_attestation_lineages,
        owner_lineage_ids,
    )
    value = {
        "schema": BINDING_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "binding_id": "",
        "binding_digest": "",
        "network_ref": network_ref,
        "network_guard": validate_prefix_guard(network_guard_value),
        "proposal_ref": {
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
        },
        "appraisal_package_ref": {
            "package_digest": package["package_digest"],
        },
        "appraisal_set_ref": {
            "appraisal_set_id": appraisal["appraisal_set_id"],
            "appraisal_set_digest": appraisal["appraisal_set_digest"],
        },
        "approval_ref": copy.deepcopy(package["approval_ref"]),
        "owner_artifact_binding_digests": copy.deepcopy(owner_digests),
        "expected_authority_sha256": _digest(
            expected_authority_sha256, "expected_authority_sha256"
        ),
        "prepared_ref": {
            "request_digest": prepared["request_digest"],
            "prepared_request_file_sha256": prepared["prepared_request_file_sha256"],
        },
        "independent_review_ref": {
            "independent_review_digest": independent_review[
                "independent_review_digest"
            ],
            "independent_review_file_sha256": independent_review[
                "independent_review_file_sha256"
            ],
        },
        "lineage_refs": [
            {
                "appraisal_set_id": item["appraisal_set_id"],
                "appraisal_set_digest": item["appraisal_set_digest"],
                "cycle": item["cycle"],
            }
            for item in lineage_values
        ],
        "bound_at": _timestamp(bound_at, "bound_at"),
        "mutation_authorized": False,
        "relation_bindings": rows,
        "action_bindings": actions,
        "transition_basis": _transition_basis(package),
    }
    return _attach(value, "binding_id", "binding_digest", "evidence-appraisal-binding-")


def validate_binding(
    value: Any,
    package_value: Any,
    approval_value: Any,
    prepared_value: Any,
    independent_review_value: Any,
    owner_bundle_value: Any,
    lineage_values: list[Any],
    expected_authority_sha256: str,
    proposal_value: Any,
    network_ref_value: Any,
    claim_scopes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    binding = _object(value, "binding")
    _keys(
        binding,
        {
            "schema",
            "schema_version",
            "binding_id",
            "binding_digest",
            "network_ref",
            "network_guard",
            "proposal_ref",
            "appraisal_package_ref",
            "appraisal_set_ref",
            "approval_ref",
            "owner_artifact_binding_digests",
            "expected_authority_sha256",
            "prepared_ref",
            "independent_review_ref",
            "lineage_refs",
            "bound_at",
            "mutation_authorized",
            "relation_bindings",
            "action_bindings",
            "transition_basis",
        },
        "binding",
    )
    if (
        binding["schema"] != BINDING_SCHEMA
        or binding["schema_version"] != SCHEMA_VERSION
    ):
        raise BindingError("binding schema/version invalid")
    expected = create_binding(
        package_value,
        approval_value,
        prepared_value,
        independent_review_value,
        owner_bundle_value,
        lineage_values,
        expected_authority_sha256,
        proposal_value,
        network_ref_value,
        binding["network_guard"],
        claim_scopes,
        bound_at=binding["bound_at"],
    )
    if binding != expected:
        raise BindingError("binding is not the owner-derived appraisal projection")
    return binding


def _review_from_projection(projection: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": PROJECTION_REVIEW_SCHEMA,
        "binding_ref": projection["binding_ref"],
        "proposal_ref": projection["proposal_ref"],
        "reviewer": projection["reviewer"],
        "decisions": [
            {
                key: copy.deepcopy(decision[key])
                for key in (
                    "action_id",
                    "action_digest",
                    "decision",
                    "rationale",
                    "relation_reviews",
                    "gap_transition",
                )
            }
            for decision in projection["decisions"]
        ],
    }


def create_reviewed_projection(
    binding_value: Any,
    proposal_value: Any,
    review_value: Any,
    *,
    reviewed_at: str,
) -> dict[str, Any]:
    binding = _object(binding_value, "binding")
    proposal = validate_proposal_integrity(proposal_value)
    review = _object(review_value, "projection review")
    _keys(
        review,
        {"schema", "binding_ref", "proposal_ref", "reviewer", "decisions"},
        "projection review",
    )
    if review["schema"] != PROJECTION_REVIEW_SCHEMA:
        raise BindingError("projection review schema invalid")
    binding_ref = {
        "binding_id": binding["binding_id"],
        "binding_digest": binding["binding_digest"],
    }
    proposal_ref = {
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal["proposal_digest"],
    }
    if review["binding_ref"] != binding_ref or review["proposal_ref"] != proposal_ref:
        raise BindingError("projection review binding mismatch")
    reviewer = _object(review["reviewer"], "projection review reviewer")
    _keys(reviewer, {"reviewer_id", "reviewer_role"}, "projection review reviewer")
    _string(reviewer["reviewer_id"], "projection reviewer_id")
    _string(reviewer["reviewer_role"], "projection reviewer_role")
    if not isinstance(review["decisions"], list) or len(review["decisions"]) != len(
        proposal["actions"]
    ):
        raise BindingError("projection review must decide every proposal action")
    rows = {row["binding_row_id"]: row for row in binding["relation_bindings"]}
    action_bindings = {row["action_id"]: row for row in binding["action_bindings"]}
    decisions: list[dict[str, Any]] = []
    authorization_digests: list[str] = []
    for index, (raw, action) in enumerate(
        zip(review["decisions"], proposal["actions"])
    ):
        label = f"projection review decisions[{index}]"
        decision = _object(raw, label)
        _keys(
            decision,
            {
                "action_id",
                "action_digest",
                "decision",
                "rationale",
                "relation_reviews",
                "gap_transition",
            },
            label,
        )
        if (decision["action_id"], decision["action_digest"]) != (
            action["action_id"],
            action["action_digest"],
        ):
            raise BindingError(f"{label} action mismatch")
        if decision["decision"] not in PROJECTION_DECISIONS:
            raise BindingError(f"{label}.decision invalid")
        _string(decision["rationale"], f"{label}.rationale")
        action_binding = action_bindings[action["action_id"]]
        gap_transition = _validate_gap_transition_review(
            decision["gap_transition"], f"{label}.gap_transition"
        )
        relation_reviews = decision["relation_reviews"]
        if not isinstance(relation_reviews, list):
            raise BindingError(f"{label}.relation_reviews must be a list")
        normalized: list[dict[str, Any]] = []
        for row_index, raw_review in enumerate(relation_reviews):
            row_label = f"{label}.relation_reviews[{row_index}]"
            row_review = _object(raw_review, row_label)
            _keys(
                row_review,
                {
                    "binding_row_id",
                    "binding_row_digest",
                    "scope_alignment",
                    "projected_relation",
                },
                row_label,
            )
            binding_row = rows.get(str(row_review["binding_row_id"]))
            if (
                binding_row is None
                or row_review["binding_row_digest"] != binding_row["binding_row_digest"]
            ):
                raise BindingError(f"{row_label} binding mismatch")
            if binding_row["action_id"] != action["action_id"]:
                raise BindingError(f"{row_label} crosses actions")
            if row_review["scope_alignment"] not in SCOPE_ALIGNMENTS:
                raise BindingError(f"{row_label}.scope_alignment invalid")
            if (
                row_review["projected_relation"] is not None
                and row_review["projected_relation"] not in PROJECTED_RELATIONS
            ):
                raise BindingError(f"{row_label}.projected_relation invalid")
            normalized.append(copy.deepcopy(row_review))
        if [row["binding_row_id"] for row in normalized] != action_binding[
            "binding_row_ids"
        ]:
            raise BindingError(f"{label} must review every binding row in order")
        authorized: list[dict[str, Any]] = []
        relation_projection_requested = any(
            row["projected_relation"] is not None for row in normalized
        )
        if decision["decision"] == "authorize":
            if relation_projection_requested:
                for row_review in normalized:
                    binding_row = rows[row_review["binding_row_id"]]
                    if (
                        not binding_row["mutation_eligible"]
                        or binding_row["allowed_relation"] == "context"
                        or row_review["scope_alignment"] != "match"
                        or row_review["projected_relation"]
                        != binding_row["allowed_relation"]
                    ):
                        raise BindingError(
                            f"{label} cannot authorize ineligible, context-only, "
                            "scope-mismatched, or relation-mismatched evidence"
                        )
                authorized.extend(copy.deepcopy(action_binding["mutation_routes"]))
            if gap_transition is not None:
                authorized.append(
                    _transition_route(
                        gap_transition,
                        action,
                        action_binding,
                        rows,
                        normalized,
                        binding["transition_basis"],
                        label,
                    )
                )
            if not authorized:
                raise BindingError(f"{label} has no safe mutation route")
            authorization_digests.extend(
                row["authorization_digest"] for row in authorized
            )
        elif relation_projection_requested or gap_transition is not None:
            raise BindingError(
                f"{label} reject/defer cannot project a relation or gap transition"
            )
        decisions.append(
            {**copy.deepcopy(decision), "authorized_mutations": authorized}
        )
    _unique(authorization_digests, "projection authorization digests")
    value = {
        "schema": PROJECTION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "projection_id": "",
        "projection_digest": "",
        "network_ref": copy.deepcopy(binding["network_ref"]),
        "proposal_ref": proposal_ref,
        "binding_ref": binding_ref,
        "appraisal_package_ref": copy.deepcopy(binding["appraisal_package_ref"]),
        "appraisal_set_ref": copy.deepcopy(binding["appraisal_set_ref"]),
        "approval_ref": copy.deepcopy(binding["approval_ref"]),
        "expected_authority_sha256": binding["expected_authority_sha256"],
        "reviewed_at": _timestamp(reviewed_at, "reviewed_at"),
        "reviewer": copy.deepcopy(reviewer),
        "review_status": "approved",
        "mutation_authorized": True,
        "decisions": decisions,
    }
    return _attach(
        value,
        "projection_id",
        "projection_digest",
        "evidence-appraisal-projection-",
    )


def validate_reviewed_projection(
    value: Any, binding_value: Any, proposal_value: Any
) -> dict[str, Any]:
    projection = _object(value, "projection")
    _keys(
        projection,
        {
            "schema",
            "schema_version",
            "projection_id",
            "projection_digest",
            "network_ref",
            "proposal_ref",
            "binding_ref",
            "appraisal_package_ref",
            "appraisal_set_ref",
            "approval_ref",
            "expected_authority_sha256",
            "reviewed_at",
            "reviewer",
            "review_status",
            "mutation_authorized",
            "decisions",
        },
        "projection",
    )
    if (
        projection["schema"] != PROJECTION_SCHEMA
        or projection["schema_version"] != SCHEMA_VERSION
    ):
        raise BindingError("projection schema/version invalid")
    if (
        projection["review_status"] != "approved"
        or projection["mutation_authorized"] is not True
    ):
        raise BindingError("projection is not explicitly reviewed and authorizing")
    expected = create_reviewed_projection(
        binding_value,
        proposal_value,
        _review_from_projection(projection),
        reviewed_at=projection["reviewed_at"],
    )
    if projection != expected:
        raise BindingError("projection is not canonical")
    return projection


def gate_refs(binding: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "reviewed_appraisal",
        "appraisal_package_ref": copy.deepcopy(binding["appraisal_package_ref"]),
        "appraisal_set_ref": copy.deepcopy(binding["appraisal_set_ref"]),
        "approval_ref": copy.deepcopy(binding["approval_ref"]),
        "owner_artifact_binding_digests": copy.deepcopy(
            binding["owner_artifact_binding_digests"]
        ),
        "expected_authority_sha256": binding["expected_authority_sha256"],
        "binding_ref": {
            "binding_id": binding["binding_id"],
            "binding_digest": binding["binding_digest"],
        },
        "projection_ref": {
            "projection_id": projection["projection_id"],
            "projection_digest": projection["projection_digest"],
        },
    }


def validate_gate(
    package_value: Any,
    approval_value: Any,
    prepared_value: Any,
    independent_review_value: Any,
    owner_bundle_value: Any,
    lineage_values: list[Any],
    expected_authority_sha256: str,
    proposal_value: Any,
    binding_value: Any,
    projection_value: Any,
    network_ref_value: Any,
    claim_scopes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    proposal = validate_proposal_integrity(proposal_value)
    binding = validate_binding(
        binding_value,
        package_value,
        approval_value,
        prepared_value,
        independent_review_value,
        owner_bundle_value,
        lineage_values,
        expected_authority_sha256,
        proposal,
        network_ref_value,
        claim_scopes,
    )
    projection = validate_reviewed_projection(projection_value, binding, proposal)
    package = copy.deepcopy(_object(package_value, "appraisal package"))
    return {
        "package": package,
        "appraisal": package["appraisal_set"],
        "proposal": proposal,
        "binding": binding,
        "projection": projection,
        "refs": gate_refs(binding, projection),
    }


def authorize_mutation(
    gate: dict[str, Any],
    operation_type: str,
    payload: dict[str, Any],
    *,
    authorization_subject: dict[str, Any] | None = None,
    consumed_authorization_digests: set[str] | None = None,
) -> dict[str, Any]:
    subject_digest = mutation_subject_digest(operation_type, payload)
    authorization_digest = (
        digest_json(authorization_subject)
        if authorization_subject is not None
        else _authorization_digest(operation_type, subject_digest)
    )
    matches = [
        mutation
        for decision in gate["projection"]["decisions"]
        if decision["decision"] == "authorize"
        for mutation in decision["authorized_mutations"]
        if mutation["operation_type"] == operation_type
        and mutation["authorization_digest"] == authorization_digest
        and (
            mutation["mutation_subject_digest"] is None
            or mutation["mutation_subject_digest"] == subject_digest
        )
    ]
    if len(matches) != 1:
        raise BindingError(
            "reviewed appraisal projection does not authorize this exact scientific mutation"
        )
    if authorization_digest in (consumed_authorization_digests or set()):
        raise BindingError("reviewed appraisal authorization was already consumed")
    return {
        "authorization_digest": authorization_digest,
        "mutation_subject_digest": subject_digest,
        "mutation_route": matches[0],
        "refs": copy.deepcopy(gate["refs"]),
    }
