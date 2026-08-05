#!/usr/bin/env python3
"""Probe a research knowledge network without mutating it."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NETWORK_SCHEMA = "KnowledgeNetwork/v1"
PROBE_SCHEMA = "NetworkGapProbe/v1"
HYPOTHESES_SCHEMA = "KnowledgeGapHypotheses/v1"
REQUEST_SET_SCHEMA = "ScholarDiscoveryRequestSet/v1"
LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA = "LearnFromPapersRequestSet/v1"
LEARN_FROM_PAPERS_REQUEST_SCHEMA = "LearnFromPapersRequest/v1"
RESULT_SET_SCHEMA = "ScholarDiscoveryResultSet/v1"
REQUEST_SCHEMA = "ScholarDiscoveryRequest/v1"
RESULT_SCHEMA = "ScholarDiscoveryResult/v1"
REVIEWED_EVIDENCE_SET_SCHEMA = "ReviewedEvidenceSet/v1"
REVIEWED_EVIDENCE_SCHEMA = "ReviewedEvidence/v1"
PAPER_READING_REPORT_SET_SCHEMA = "PaperReadingReportSet/v1"
PAPER_READING_REPORT_SCHEMA = "PaperReadingReport/v1"
PATCH_SCHEMA = "NetworkPatchProposal/v1"

SCHEMA_VERSION = "1.0"
REQUEST_SET_SCHEMA_VERSION = "v1"
PAPER_READING_REPORT_SET_SCHEMA_VERSION = "v1"
REQUEST_SET_ID_PREFIX = "request-set-"
LEARN_REQUEST_SET_ID_PREFIX = "LFR-"
SOURCE_ID_PREFIX = "SRC-"
REPORT_SET_ID_PREFIX = "reading-report-set-"
READING_REPORT_ID_PREFIX = "reading-report-"
PASSAGE_ID_PREFIX = "passage-"
LOCATOR_TYPES = {"page", "section", "figure", "table", "equation"}
READING_REPORT_PROTOCOL = "1.0"
READER_PRODUCER = "learn-from-papers"
READING_DEPTH_ONLY_FULL_TEXT = "full_text"

TARGET_KINDS = {
    "node",
    "relation",
    "evidence",
    "boundary",
    "counterexample",
    "version",
    "benchmark",
    "assumption",
    "mechanism",
    "metric",
    "context",
}
STATUSES = {
    "proposed",
    "testing",
    "awaiting",
    "results",
    "no_signal",
    "content_found",
    "already_covered",
    "supported_gap",
    "contested",
    "refuted",
    "unresolved",
    "blocked",
    "superseded",
}
ACTIVE_STATUSES = {"proposed", "testing", "awaiting", "results", "unresolved", "no_signal"}
DISCOVERY_ACTIVE_STATUSES = {"proposed", "testing", "unresolved", "no_signal", "awaiting"}
SATURATION_BLOCKING_STATUSES = {"proposed", "testing", "unresolved", "awaiting", "results"}
SATURATION_TERMINAL_STATUSES = {
    "no_signal",
    "content_found",
    "already_covered",
    "supported_gap",
    "contested",
    "refuted",
}
DISCOVERY_RESULT_STATUSES = {"results"}
MANUAL_RESULT_STATUSES = {"awaiting"}
CANDIDATE_FOR_REVIEW_STATUSES = {"results"}
LEVELS = {"high", "medium", "low"}
QUERY_OBJECTIVES = {
    "known_item",
    "orientation",
    "confirm",
    "refute",
    "recent_primary",
    "seminal",
    "methods",
    "benchmark",
    "citation_forward",
    "citation_backward",
    "update",
}
AUTOMATIC_PROVIDERS = {
    "openalex",
    "semantic_scholar",
    "crossref",
    "opencitations",
    "pubmed",
    "europepmc",
    "arxiv",
}
DISCOVERY_STATUSES = {
    "complete_bounded",
    "partial_provider",
    "partial_budget",
    "blocked_capability",
    "pending",
}
READ_DEPTHS = {"full_text", "evidence"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INTERNAL_QUERY_BLOCKLIST = {
    "completion.gate_checks.",
    "unmet_declared_gate:",
}
INTERNAL_QUERY_PREFIXES = {
    "gap:",
    "relation:",
    "node:",
    "gap-",
    "rel-",
    "gaph:",
    "kgh-",
    "entity:",
    "completion.gate_checks.",
}
INTERNAL_QUERY_FIELD_NAMES = {"completion", "gate", "status", "entity"}
QUERY_STOP_WORDS = {
    "a",
    "an",
    "at",
    "and",
    "as",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "no",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "via",
    "with",
    "without",
    "around",
    "benchmark",
}
SEMANTIC_QUERY_MAX_WORDS = 12
QUERY_TERM_BLOCKLIST = {"claims_property"}
GAP_REASON_TERM_BLOCKLIST = {
    "an",
    "and",
    "at",
    "benchmark",
    "complete",
    "coverage",
    "gap",
    "identify",
    "for",
    "in",
    "locally",
    "missing",
    "of",
    "open",
    "slot",
    "the",
    "to",
    "unresolved",
    "which",
}

PROBE_FAMILIES = [
    {
        "probe_id": "probe:competency-coverage",
        "family": "competency_coverage",
        "question": "Which promised question, dimension, benchmark, or locally complete slot is unanswered?",
    },
    {
        "probe_id": "probe:taxonomy-contrast",
        "family": "taxonomy_contrast",
        "question": "Which concepts in landmark taxonomies or reviews are absent or only aliases?",
    },
    {
        "probe_id": "probe:perspective-expansion",
        "family": "perspective_expansion",
        "question": "Which object, mechanism, method, evidence, context, boundary, or artifact view is missing?",
    },
    {
        "probe_id": "probe:abc-bridge",
        "family": "abc_bridge",
        "question": "Which context-matched A-B and B-C paths justify a falsifiable A-C search?",
    },
    {
        "probe_id": "probe:citation-frontier",
        "family": "citation_frontier",
        "question": "What relevant cited, citing, related, or unused information is outside the network?",
    },
    {
        "probe_id": "probe:counterevidence-boundary",
        "family": "counterevidence_boundary",
        "question": "Which null, failure, replication, counterexample, or discriminating evidence is absent?",
    },
    {
        "probe_id": "probe:temporal-version",
        "family": "temporal_version",
        "question": "Which update, correction, retraction, superseding version, or time boundary is missing?",
    },
    {
        "probe_id": "probe:relation-context-arity",
        "family": "relation_context_arity",
        "question": "Which pairwise edge hides necessary context, conditions, or an n-ary event?",
    },
]


class ContractError(ValueError):
    """Raised when a gap-discovery contract fails closed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_request_set_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"request_set_id", "request_set_digest"}
    }
    return sha256_json(normalized)


def canonical_evidence_set_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"evidence_set_id", "evidence_set_digest"}
    }
    return sha256_json(normalized)


def canonical_report_set_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key
        not in {
            "report_set_id",
            "report_set_digest",
            "reading_report_set_id",
            "reading_report_set_digest",
            "network_id",
            "network_snapshot_sha256",
            "source_artifact_sha256",
        }
    }
    return sha256_json(normalized)


def canonical_reading_report_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"report_id", "report_digest"}
    }
    return sha256_json(normalized)


def canonical_evidence_passage_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in document.items()
        if key not in {"passage_id", "passage_digest"}
    }
    return sha256_json(normalized)


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def normalize_hypothesis_id(value: str) -> str:
    value = value.strip()
    return value[4:] if value.startswith("gap:") else value


def load_json(path: str | Path) -> Any:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"input must be a regular non-symlink file: {candidate}")
    with candidate.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    if target.is_symlink():
        raise ContractError(f"refusing symlink output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(canonical_bytes(value) + b"\n")
    temporary.replace(target)


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def require_string_list(value: Any, label: str, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ContractError(f"{label} must be a list of non-empty strings")
    if nonempty and not value:
        raise ContractError(f"{label} must not be empty")
    return [item.strip() for item in value]


def require_timestamp(value: Any, label: str) -> str:
    text = require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return text


def timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_sha256(value: Any, label: str) -> str:
    text = require_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return text


def request_digest(request: dict[str, Any]) -> str:
    return sha256_json(request)


def access_to_read_depth(access_level: str) -> str:
    return "full_text" if access_level == "full_text" else "evidence"


def validate_network(value: Any) -> dict[str, Any]:
    network = require_dict(value, "network")
    if network.get("schema") != NETWORK_SCHEMA:
        raise ContractError(f"network.schema must equal {NETWORK_SCHEMA}")
    require_string(network.get("network_id"), "network.network_id")
    require_string(network.get("snapshot_id"), "network.snapshot_id")
    for field in ("nodes", "relations", "gaps"):
        if not isinstance(network.get(field), list):
            raise ContractError(f"network.{field} must be a list")

    network_node_ids = [str(node.get("node_id")) for node in network["nodes"] if node.get("node_id")]
    if len(network_node_ids) != len(set(network_node_ids)):
        raise ContractError("network nodes must have unique node_id")

    network_relation_ids = [
        str(relation.get("relation_id"))
        for relation in network["relations"]
        if relation.get("relation_id") is not None
    ]
    if len(network_relation_ids) != len(set(network_relation_ids)):
        raise ContractError("network relations must have unique relation_id")

    return network


def _dedupe_terms(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def _query_has_internal_marker(value: str) -> bool:
    lower = value.lower()
    if any(marker in lower for marker in INTERNAL_QUERY_BLOCKLIST):
        return True
    if re.search(
        r"\b(?:gap|relation|node|unmet_declared_gate|completion\.)[:_-][A-Za-z0-9_-]+",
        lower,
    ):
        return True
    if re.search(r"\bcompletion\.gate_checks\.[a-z0-9_]+\b", lower):
        return True
    for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9._+-]*", lower):
        if token in INTERNAL_QUERY_FIELD_NAMES:
            return True
        if _query_token_is_internal(token):
            return True
    return False


def _query_token_is_internal(token: str) -> bool:
    lower = token.lower()
    if lower in INTERNAL_QUERY_FIELD_NAMES:
        return True
    if any(lower.startswith(prefix) for prefix in INTERNAL_QUERY_PREFIXES):
        return True
    if re.fullmatch(r"(?:g|rel|kgh|gaph|entity)[-_][a-zA-Z0-9._+-]+", lower):
        return True
    if re.fullmatch(r"[a-z0-9_]+(?:\.[a-z0-9_]+){1,}", lower):
        return True
    return False


def _query_semantic_token_candidates(value: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9._+-]*", value.lower())
    output: list[str] = []
    for token in tokens:
        if token in QUERY_TERM_BLOCKLIST:
            continue
        if token in QUERY_STOP_WORDS:
            continue
        if token.isnumeric():
            continue
        if _query_token_is_internal(token):
            continue
        output.append(token)
    return output


def _query_has_semantic_content(value: str, required_terms: list[str] | None = None) -> bool:
    if _query_has_internal_marker(value):
        return False
    if "no evidence for" in value.lower() and "at this snapshot" in value.lower():
        return False

    if len(value.split()) > SEMANTIC_QUERY_MAX_WORDS:
        return False

    lower = value.lower()
    required = [term.lower() for term in (required_terms or []) if term]
    if required:
        for term in required:
            if term and term in lower:
                return True

    tokens = _query_semantic_token_candidates(value)
    if not tokens:
        return False
    if len(tokens) > SEMANTIC_QUERY_MAX_WORDS:
        return False
    semantic_count = sum(1 for token in tokens if len(token) > 3)
    return semantic_count >= 1


def _normalize_terms(values: list[str]) -> str:
    return " ".join(_dedupe_terms([value.strip() for value in values if isinstance(value, str) and value.strip()]))


def _strip_internal_query_tokens(value: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value)
    return " ".join(
        token for token in tokens if not _query_token_is_internal(token)
    )


def _collect_node_labels(node: dict[str, Any] | None) -> list[str]:
    if node is None:
        return []
    values: list[str] = []
    if isinstance(node.get("label"), str):
        values.append(str(node["label"]))
    aliases = node.get("aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, str):
                values.append(alias)
    return values


def _collect_semantic_terms(values: list[Any]) -> list[str]:
    terms: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                terms.append(text)
                terms.extend(_query_semantic_token_candidates(text))
            continue
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text:
                terms.append(text)
                terms.extend(_query_semantic_token_candidates(text))
    return terms


def _collect_node_terms(node: dict[str, Any] | None) -> list[str]:
    return _collect_semantic_terms(
        [
            node.get("label") if isinstance(node, dict) else None,
            node.get("aliases") if isinstance(node, dict) else None,
            node.get("search_terms") if isinstance(node, dict) else None,
            node.get("taxonomy_terms") if isinstance(node, dict) else None,
            node.get("topics") if isinstance(node, dict) else None,
        ]
    )


def _collect_relation_terms(relation: dict[str, Any] | None) -> list[str]:
    return _collect_semantic_terms(
        [
            relation.get("search_terms") if isinstance(relation, dict) else None,
            relation.get("notes") if isinstance(relation, dict) else None,
        ]
    )


def _collect_research_context_terms(network: dict[str, Any]) -> list[str]:
    context = network.get("research_context") if isinstance(network, dict) else None
    if not isinstance(context, dict):
        return []
    return _collect_semantic_terms(
        [
            context.get("search_terms"),
            context.get("domain_phrases"),
            context.get("research_terms"),
            context.get("topics"),
        ]
    )


def _normalize_search_terms(values: list[str]) -> list[str]:
    tokens = _query_semantic_token_candidates(" ".join(values))
    if not tokens:
        return []
    normalized: list[str] = []
    workflow_terms = {
        "gap",
        "open",
        "explicit",
        "missing",
        "coverage",
        "completion",
        "gate",
        "status",
    }
    for token in tokens:
        lowered = token.lower()
        if lowered in workflow_terms:
            continue
        if lowered in GAP_REASON_TERM_BLOCKLIST:
            continue
        if _query_has_internal_marker(token):
            continue
        normalized.append(token)
    return _dedupe_terms(normalized)


def _need_semantic_enrichment(terms: list[str]) -> bool:
    tokens = _normalize_search_terms(terms)
    if len(tokens) < 2:
        return True
    if all(token in QUERY_STOP_WORDS for token in tokens):
        return True
    return False


def _build_semantic_search_spec(
    signal: dict[str, Any],
    network: dict[str, Any],
) -> tuple[list[str], bool]:
    node_lookup = {str(node.get("node_id")): node for node in network["nodes"] if node.get("node_id")}
    relation_lookup = {
        str(rel.get("relation_id")): rel
        for rel in network["relations"]
        if rel.get("relation_id")
    }
    gap_lookup = {str(gap.get("gap_id")): gap for gap in network["gaps"] if gap.get("gap_id")}

    kind = signal.get("kind")
    ref = str(signal.get("refs", [""])[0])
    terms: list[str] = []
    structural_only = False
    gap_context_terms = _collect_research_context_terms(network)
    terms.extend(gap_context_terms)

    explicit_gap = kind == "explicit_open_gap"

    if explicit_gap:
        gap = gap_lookup.get(ref)
        if gap is not None:
            terms.extend(
                _collect_semantic_terms(
                    [
                        gap.get("title"),
                        gap.get("name"),
                        gap.get("reason"),
                        gap.get("description"),
                        gap.get("next_action"),
                    ]
                )
            )

    elif kind == "unmet_declared_gate":
        structural_only = True

    elif kind == "topological_isolate":
        node = node_lookup.get(ref)
        terms.extend(_collect_node_terms(node))

    elif kind == "low_confidence_relation":
        relation = relation_lookup.get(ref)
        if relation is not None:
            source = node_lookup.get(str(relation.get("from_id")))
            target = node_lookup.get(str(relation.get("to_id")))
            source_labels = _collect_node_terms(source)
            target_labels = _collect_node_terms(target)
            terms.extend(source_labels)
            terms.extend(target_labels)
            terms.extend(_collect_relation_terms(relation))

    else:
        structural_only = True
        if signal.get("reason") and isinstance(signal["reason"], str):
            terms.extend(_collect_semantic_terms([signal["reason"]]))

    terms = _normalize_search_terms(terms)

    if _need_semantic_enrichment(terms):
        structural_only = True

    if kind == "unmet_declared_gate":
        structural_only = True

    return terms, structural_only


def _build_semantic_search_query(
    terms: list[str],
    objective: str,
    fallback: str = "benchmark evidence",
) -> str:
    fragments = _dedupe_terms([term for term in terms if isinstance(term, str) and term.strip()])
    if not fragments:
        fragments = [fallback]

    anchor = next((term for term in fragments if " " in term.strip()), None)
    if anchor is not None:
        fragments = [anchor] + [term for term in fragments if term != anchor]

    refute_modifiers = [
        "limitation",
        "comparison",
        "counterfactual",
        "counterexample",
        "null",
        "scope",
    ]
    if objective == "refute":
        fragments = fragments + refute_modifiers

    query_tokens: list[str] = []
    for fragment in fragments:
        if " " in fragment:
            cleaned_fragment = _strip_internal_query_tokens(fragment)
            if cleaned_fragment:
                cleaned_terms = cleaned_fragment.split()
                if len(cleaned_terms) <= SEMANTIC_QUERY_MAX_WORDS:
                    query_tokens.append(" ".join(cleaned_terms))
                else:
                    query_tokens.extend(cleaned_terms)
            else:
                query_tokens.extend(_query_semantic_token_candidates(fragment))
            continue
        query_tokens.extend(_query_semantic_token_candidates(fragment))
    expanded_query_tokens: list[str] = []
    for token in query_tokens:
        if " " in token:
            expanded_query_tokens.extend(token.split())
        else:
            expanded_query_tokens.append(token)
    query_tokens = _dedupe_terms(expanded_query_tokens)
    if not query_tokens:
        query_tokens = fallback.split()

    if objective == "confirm":
        return " ".join(query_tokens[:SEMANTIC_QUERY_MAX_WORDS])
    if objective == "refute":
        return " ".join(query_tokens[:SEMANTIC_QUERY_MAX_WORDS])
    return " ".join(query_tokens[:SEMANTIC_QUERY_MAX_WORDS])


def network_ref(network: dict[str, Any]) -> dict[str, str]:
    return {
        "network_id": network["network_id"],
        "snapshot_id": network["snapshot_id"],
        "sha256": sha256_json(network),
    }


def network_reference_index(network: dict[str, Any]) -> dict[str, set[str]]:
    nodes = {
        str(node.get("node_id")) for node in network["nodes"] if node.get("node_id") is not None
    }
    relations = {
        str(relation.get("relation_id"))
        for relation in network["relations"]
        if relation.get("relation_id") is not None
    }
    gaps = {
        str(gap.get("gap_id")) for gap in network["gaps"] if gap.get("gap_id") is not None
    }
    completion = require_dict(network.get("completion", {}), "network.completion")
    gate_checks = require_dict(completion.get("gate_checks", {}), "network.completion.gate_checks")
    gate_refs = {f"completion.gate_checks.{gate}" for gate in gate_checks}
    return {
        "network_id": {network["network_id"]},
        "nodes": nodes,
        "relations": relations,
        "gaps": gaps,
        "gate_refs": gate_refs,
    }


def validate_network_ref(
    value: Any, label: str, network: dict[str, Any] | None = None
) -> dict[str, str]:
    ref = require_dict(value, label)
    require_string(ref.get("network_id"), f"{label}.network_id")
    require_string(ref.get("snapshot_id"), f"{label}.snapshot_id")
    digest = require_string(ref.get("sha256"), f"{label}.sha256")
    ensure_sha256(digest, f"{label}.sha256")
    if network is not None and ref != network_ref(validate_network(network)):
        raise ContractError(f"{label} does not match supplied network")
    return ref


def validate_hypothesis_reference(ref_id: str, index: dict[str, set[str]], label: str) -> None:
    if ref_id in {f"network:{network_id}" for network_id in index["network_id"]}:
        return
    if ref_id in index["nodes"] or ref_id in index["relations"] or ref_id in index["gaps"]:
        return
    if ref_id.startswith("node:") and ref_id.split(":", 1)[1] in index["nodes"]:
        return
    if ref_id.startswith("relation:") and ref_id.split(":", 1)[1] in index["relations"]:
        return
    if ref_id.startswith("gap:") and ref_id.split(":", 1)[1] in index["gaps"]:
        return
    if ref_id in index["gate_refs"]:
        return
    raise ContractError(f"{label} must reference current network context")


def connected_components(
    node_ids: set[str], adjacency: dict[str, set[str]]
) -> list[list[str]]:
    unseen = set(node_ids)
    components: list[list[str]] = []
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        queue = deque([start])
        component: list[str] = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    return sorted(components, key=lambda item: (-len(item), item))


def scan_network(value: Any) -> dict[str, Any]:
    network = validate_network(value)
    nodes = {
        str(node.get("node_id")): node
        for node in network["nodes"]
        if node.get("node_id") is not None
    }
    node_ids = set(nodes)
    adjacency = {node_id: set() for node_id in node_ids}
    dangling: list[str] = []
    low_confidence: list[str] = []
    missing_provenance: list[str] = []
    predicate_counts: Counter[str] = Counter()
    for relation in network["relations"]:
        relation_id = str(relation.get("relation_id", "<missing>"))
        source = relation.get("from_id")
        target = relation.get("to_id")
        predicate_counts[str(relation.get("predicate", "<missing>"))] += 1
        if source not in node_ids or target not in node_ids:
            dangling.append(relation_id)
        else:
            adjacency[str(source)].add(str(target))
            adjacency[str(target)].add(str(source))
        if relation.get("confidence") in {"low", "unknown", None} or relation.get(
            "status"
        ) in {"unresolved", "conflicting"}:
            low_confidence.append(relation_id)
        if not relation.get("provenance"):
            missing_provenance.append(relation_id)

    isolates = sorted(
        node_id
        for node_id, neighbors in adjacency.items()
        if not neighbors and nodes[node_id].get("kind") != "source"
    )
    components = connected_components(node_ids, adjacency)
    open_gaps = sorted(
        str(gap.get("gap_id"))
        for gap in network["gaps"]
        if gap.get("status") not in {"resolved", "closed"}
    )
    completion = require_dict(network.get("completion", {}), "network.completion")
    gate_checks = require_dict(
        completion.get("gate_checks", {}), "network.completion.gate_checks"
    )
    unmet_gates = sorted(key for key, passed in gate_checks.items() if passed is not True)

    signals: list[dict[str, Any]] = []
    for gap_id in open_gaps:
        signals.append(
            {
                "signal_id": "signal:gap:" + sha256_json(gap_id)[:12],
                "kind": "explicit_open_gap",
                "refs": [gap_id],
                "classification": "deterministic_structural_signal",
                "reason": "an explicit open gap is present in this snapshot",
            }
        )
    for gate in unmet_gates:
        signals.append(
            {
                "signal_id": "signal:gate:" + sha256_json(gate)[:12],
                "kind": "unmet_declared_gate",
                "refs": [f"completion.gate_checks.{gate}"],
                "classification": "deterministic_structural_signal",
                "reason": "an explicit completion contract is unmet",
            }
        )
    for node_id in isolates:
        signals.append(
            {
                "signal_id": "signal:isolate:" + sha256_json(node_id)[:12],
                "kind": "topological_isolate",
                "refs": [node_id],
                "classification": "implicit_candidate_signal",
                "reason": "topology may reflect aliasing, scope, or missing relations",
            }
        )
    for relation_id in sorted(set(low_confidence)):
        signals.append(
            {
                "signal_id": "signal:low-confidence:" + sha256_json(relation_id)[:12],
                "kind": "low_confidence_relation",
                "refs": [relation_id],
                "classification": "implicit_candidate_signal",
                "reason": "confidence may require independent evidence",
            }
        )
    probe = {
        "schema": PROBE_SCHEMA,
        "network_ref": network_ref(network),
        "open_world_policy": "absence_is_unknown_without_local_completeness_contract",
        "counts": {
            "nodes": len(nodes),
            "relations": len(network["relations"]),
            "gaps": len(network["gaps"]),
            "node_kinds": dict(
                sorted(Counter(node.get("kind", "<missing>") for node in nodes.values()).items())
            ),
            "predicates": dict(sorted(predicate_counts.items())),
        },
        "existing_open_gap_ids": open_gaps,
        "unmet_completion_gates": unmet_gates,
        "topological_isolates": isolates,
        "connected_components": components,
        "dangling_relation_ids": sorted(set(dangling)),
        "low_confidence_relation_ids": sorted(set(low_confidence)),
        "relation_ids_without_provenance": sorted(set(missing_provenance)),
        "candidate_signals": signals,
        "probe_families": PROBE_FAMILIES,
        "novelty_claimed": False,
    }
    return validate_probe(probe)


def validate_probe(value: Any) -> dict[str, Any]:
    probe = require_dict(value, "probe")
    if probe.get("schema") != PROBE_SCHEMA:
        raise ContractError(f"probe.schema must equal {PROBE_SCHEMA}")
    validate_network_ref(probe.get("network_ref"), "probe.network_ref")
    if probe.get("novelty_claimed") is not False:
        raise ContractError("probe.novelty_claimed must be false")
    if not isinstance(probe.get("candidate_signals"), list):
        raise ContractError("probe.candidate_signals must be a list")
    return probe


def signal_hypothesis_signature(signal: dict[str, Any]) -> str:
    kind = signal.get("kind")
    if kind == "explicit_open_gap":
        reason = signal.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
        return "semantic enrichment required"
    if kind == "unmet_declared_gate":
        return "semantic enrichment required"
    if kind == "topological_isolate":
        return "topological isolate"
    if kind == "low_confidence_relation":
        return "low confidence relation"
    return str(signal.get("kind", "candidate"))


def generate_hypotheses_from_probe(
    probe: dict[str, Any], network: dict[str, Any], round_id: str | None = None
) -> dict[str, Any]:
    probe = validate_probe(probe)
    validate_network(network)
    if probe["network_ref"] != network_ref(network):
        raise ContractError("probe network_ref does not match network")
    index = network_reference_index(network)
    hypotheses: list[dict[str, Any]] = []
    for offset, signal in enumerate(sorted(probe["candidate_signals"], key=lambda item: item["signal_id"])):
        signature = signal_hypothesis_signature(signal)
        hypothesis_id = f"KGH-{offset + 1:03d}"
        if signal["kind"] == "topological_isolate":
            target_kind = "node"
            target_signature = signature
            decision_impact = "medium"
            uncertainty = "medium"
        elif signal["kind"] == "low_confidence_relation":
            target_kind = "relation"
            target_signature = signature
            decision_impact = "medium"
            uncertainty = "high"
        elif signal["kind"] == "explicit_open_gap":
            target_kind = "relation"
            target_signature = signature
            decision_impact = "high"
            uncertainty = "medium"
        else:
            target_kind = "assumption"
            target_signature = signature
            decision_impact = "medium"
            uncertainty = "medium"

        search_terms, structural_only = _build_semantic_search_spec(signal, network)
        search_terms = _dedupe_terms(search_terms)
        if not search_terms:
            structural_only = True
        if search_terms:
            target_signature = " ".join(_dedupe_terms(search_terms)[:8])
        elif structural_only:
            target_signature = "semantic enrichment required"
        if not target_signature:
            target_signature = "semantic enrichment required"
        criteria_terms = search_terms[:8]

        if signal["kind"] == "explicit_open_gap":
            grounds_ref = signal["refs"][0]
        else:
            grounds_ref = signal["refs"][0]
        grounds = [{"ref_id": grounds_ref, "statement": signal["reason"]}]
        for ground in grounds:
            validate_hypothesis_reference(ground["ref_id"], index, "hypothesis.grounds")

        hypothesis = {
            "hypothesis_id": hypothesis_id,
            "gap_type": "implicit_candidate",
            "target_kind": target_kind,
            "target_signature": target_signature,
            "scope_and_time_bounds": "snapshot-local explicit contract scope",
            "hypothesis": f"Potential missing evidence gap suggested by probe signal: {signal['reason']}",
            "grounds": grounds,
            "warrant": (
                "This is a deterministic candidate tied to explicit open-structure evidence "
                "from the same snapshot."
            ),
            "backing": [
                {
                    "ref_id": signal["signal_id"],
                    "locator": f"candidate_signal {signal['signal_id']}",
                }
            ],
            "qualifier": "deterministic, bounded, not a novelty claim",
            "defeaters": [
                "alias or existing node captures same meaning",
                "scope mismatch in benchmark definition",
            ],
            "search_test": {
                "queries": [
                    {
                        "objective": "confirm",
                        "query": _build_semantic_search_query(search_terms, "confirm"),
                    },
                    {
                        "objective": "refute",
                        "query": _build_semantic_search_query(search_terms, "refute"),
                    },
                ],
                "route_families": ["openalex", "semantic_scholar", "crossref", "google_scholar"],
                "expected_confirming_observation": (
                    "a primary source with bounded comparison to the same network objects"
                ),
                "expected_disconfirming_observation": "a scope/alias explanation for absence",
                "acceptance_criteria": "multiple bounded routes and grounded fallback",
                "criteria": {
                    "must": criteria_terms,
                    "should": [],
                    "must_not": [],
                },
                "metadata_filters": {},
                "seeds": {
                    "titles": criteria_terms,
                    "arxiv": [],
                },
            },
            "expected_information_gain": "improves bounded completion reasoning",
            "decision_impact": decision_impact,
            "uncertainty": uncertainty,
            "searchability": "medium",
            "cross_branch_blocking": True,
            "dependencies": [],
            "status": "proposed",
            "status_basis": [],
            "novelty_claimed": False,
            "structural_only": structural_only,
            "next_action": "scholar_discovery" if not structural_only else "structural_only",
        }
        validate_hypothesis_reference(grounds_ref, index, "hypothesis.grounds")
        hypothesis["backing"][0]["ref_id"] = f"network:{network['network_id']}"
        hypotheses.append(hypothesis)

    return {
        "schema": HYPOTHESES_SCHEMA,
        "network_ref": network_ref(network),
        "round_id": round_id or timestamp_now(),
        "generated_at": timestamp_now(),
        "method_families": ["competency_coverage", "abc_bridge", "counterevidence_boundary"],
        "hypotheses": hypotheses,
    }


def validate_hypotheses(
    value: Any, network: dict[str, Any] | None = None
) -> dict[str, Any]:
    document = require_dict(value, "hypotheses")
    if document.get("schema") != HYPOTHESES_SCHEMA:
        raise ContractError(f"hypotheses.schema must equal {HYPOTHESES_SCHEMA}")
    validate_network_ref(document.get("network_ref"), "hypotheses.network_ref", network)
    require_string(document.get("round_id"), "hypotheses.round_id")
    require_timestamp(document.get("generated_at"), "hypotheses.generated_at")
    require_string_list(document.get("method_families"), "hypotheses.method_families", True)
    index = network_reference_index(validate_network(network)) if network is not None else None

    hypotheses = document.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ContractError("hypotheses.hypotheses must be a list")
    seen: set[str] = set()
    for index_h, hypothesis in enumerate(hypotheses):
        label = f"hypotheses.hypotheses[{index_h}]"
        item = require_dict(hypothesis, label)
        hypothesis_id = require_string(item.get("hypothesis_id"), f"{label}.hypothesis_id")
        if hypothesis_id in seen:
            raise ContractError(f"duplicate hypothesis_id: {hypothesis_id}")
        seen.add(hypothesis_id)
        if item.get("gap_type") != "implicit_candidate":
            raise ContractError(f"{label}.gap_type must equal implicit_candidate")
        if item.get("target_kind") not in TARGET_KINDS:
            raise ContractError(f"{label}.target_kind is invalid")
        for field in (
            "target_signature",
            "scope_and_time_bounds",
            "hypothesis",
            "warrant",
            "qualifier",
            "expected_information_gain",
            "next_action",
        ):
            require_string(item.get(field), f"{label}.{field}")
        grounds = item.get("grounds")
        if not isinstance(grounds, list) or not grounds:
            raise ContractError(f"{label}.grounds must be non-empty")
        for ground_index, ground in enumerate(grounds):
            entry = require_dict(ground, f"{label}.grounds[{ground_index}]")
            ref_id = require_string(entry.get("ref_id"), f"{label}.grounds[{ground_index}].ref_id")
            require_string(
                entry.get("statement"), f"{label}.grounds[{ground_index}].statement"
            )
            if index is not None:
                validate_hypothesis_reference(ref_id, index, f"{label}.grounds[{ground_index}].ref_id")

        backing = item.get("backing")
        if not isinstance(backing, list) or not backing:
            raise ContractError(f"{label}.backing must be non-empty")
        for backing_index, basis in enumerate(backing):
            entry = require_dict(basis, f"{label}.backing[{backing_index}]")
            ref_id = require_string(
                entry.get("ref_id"), f"{label}.backing[{backing_index}].ref_id"
            )
            require_string(entry.get("locator"), f"{label}.backing[{backing_index}].locator")
            if index is not None:
                validate_hypothesis_reference(
                    ref_id, index, f"{label}.backing[{backing_index}].ref_id"
                )

        require_string_list(item.get("defeaters"), f"{label}.defeaters", True)
        require_string_list(item.get("dependencies"), f"{label}.dependencies")
        if item.get("novelty_claimed") is not False:
            raise ContractError(f"{label}.novelty_claimed must be false")
        structural_only = item.get("structural_only")
        if structural_only is not None and structural_only not in {True, False}:
            raise ContractError(f"{label}.structural_only must be boolean if present")
        needs_semantic_enrichment = item.get("needs_semantic_enrichment")
        if (
            needs_semantic_enrichment is not None
            and needs_semantic_enrichment not in {True, False}
        ):
            raise ContractError(
                f"{label}.needs_semantic_enrichment must be boolean if present"
            )
        skip_semantic_validation = bool(structural_only) or bool(needs_semantic_enrichment)
        for field in ("decision_impact", "uncertainty", "searchability"):
            if item.get(field) not in LEVELS:
                raise ContractError(f"{label}.{field} is invalid")
        if not isinstance(item.get("cross_branch_blocking"), bool):
            raise ContractError(f"{label}.cross_branch_blocking must be boolean")
        if item.get("status") not in STATUSES:
            raise ContractError(f"{label}.status is invalid")
        if not isinstance(item.get("status_basis"), list):
            raise ContractError(f"{label}.status_basis must be a list")

        search_test = require_dict(item.get("search_test"), f"{label}.search_test")
        queries = search_test.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ContractError(f"{label}.search_test needs at least one query")
        if (not skip_semantic_validation) and len(queries) < 2:
            raise ContractError(f"{label}.search_test needs confirm and refute queries")
        objectives: set[str] = set()
        criteria = require_dict(search_test.get("criteria"), f"{label}.search_test.criteria")
        required_terms = criteria.get("must", [])
        for query_index, query in enumerate(queries):
            entry = require_dict(query, f"{label}.search_test.queries[{query_index}]")
            objective = entry.get("objective")
            if objective not in QUERY_OBJECTIVES:
                raise ContractError(f"{label}.search_test query objective is invalid")
            objectives.add(objective)
            query_text = require_string(
                entry.get("query"), f"{label}.search_test.queries[{query_index}].query"
            )
            if not skip_semantic_validation and not _query_has_semantic_content(
                query_text, required_terms=required_terms
            ):
                raise ContractError(
                    f"{label}.search_test query lacks semantic content or contains internal markers"
                )
        if (not skip_semantic_validation) and not {"confirm", "refute"}.issubset(
            objectives
        ):
            raise ContractError(f"{label}.search_test requires confirm and refute")
        routes = require_string_list(
            search_test.get("route_families"),
            f"{label}.search_test.route_families",
            True,
        )
        if len(set(routes)) < 2:
            raise ContractError(f"{label}.search_test needs two route families")
        for field in (
            "expected_confirming_observation",
            "expected_disconfirming_observation",
            "acceptance_criteria",
        ):
            require_string(search_test.get(field), f"{label}.search_test.{field}")

        if item["status"] in {
            "content_found",
            "supported_gap",
            "contested",
            "refuted",
            "already_covered",
        }:
            if not item["status_basis"]:
                raise ContractError(f"{label}.status_basis required for evidence states")
            groups = set()
            has_full_text = False
            for basis_index, basis in enumerate(item["status_basis"]):
                entry = require_dict(basis, f"{label}.status_basis[{basis_index}]")
                require_string(
                    entry.get("hypothesis_id"),
                    f"{label}.status_basis[{basis_index}].hypothesis_id",
                )
                require_string(
                    entry.get("review_request_id"),
                    f"{label}.status_basis[{basis_index}].review_request_id",
                )
                require_string(
                    entry.get("review_request_digest"),
                    f"{label}.status_basis[{basis_index}].review_request_digest",
                )
                if entry.get("claim_support_eligible") not in {True, False}:
                    raise ContractError(
                        f"{label}.status_basis[{basis_index}].claim_support_eligible must be boolean"
                    )
                require_string(
                    entry.get("source_ref"),
                    f"{label}.status_basis[{basis_index}].source_ref",
                )
                require_string(
                    entry.get("locator"), f"{label}.status_basis[{basis_index}].locator"
                )
                read_depth = require_string(
                    entry.get("read_depth"),
                    f"{label}.status_basis[{basis_index}].read_depth",
                )
                if read_depth not in READ_DEPTHS:
                    raise ContractError(
                        f"{label}.status_basis[{basis_index}].read_depth invalid"
                    )
                has_full_text = has_full_text or read_depth == "full_text"
                groups.add(entry.get("independence_group") or entry.get("source_ref"))
            if item["status"] in {"content_found", "supported_gap", "contested"} and (
                item["decision_impact"] == "high"
                and (len(groups) < 2 or not has_full_text)
            ):
                raise ContractError(
                    f"{label} high-impact evidence states need two groups and full text"
                )
    return document


def priority_components(hypothesis: dict[str, Any]) -> dict[str, int]:
    return {
        "decision_impact": {"high": 8, "medium": 4, "low": 1}[
            hypothesis["decision_impact"]
        ],
        "uncertainty": {"high": 3, "medium": 2, "low": 1}[hypothesis["uncertainty"]],
        "searchability": {"high": 2, "medium": 1, "low": 0}[
            hypothesis["searchability"]
        ],
        "cross_branch_blocking": 3 if hypothesis["cross_branch_blocking"] else 0,
        "terminal_status_penalty": -100 if hypothesis["status"] not in ACTIVE_STATUSES else 0,
    }


def prioritize(value: Any, network: dict[str, Any] | None = None) -> dict[str, Any]:
    document = validate_hypotheses(value, network)
    output = json.loads(json.dumps(document))
    for hypothesis in output["hypotheses"]:
        components = priority_components(hypothesis)
        hypothesis["priority_components"] = components
        hypothesis["priority_score"] = sum(components.values())
    output["hypotheses"].sort(
        key=lambda item: (-item["priority_score"], item["hypothesis_id"])
    )
    output["priority_order"] = [item["hypothesis_id"] for item in output["hypotheses"]]
    return output


def optional_list(value: Any) -> list[str]:
    return [] if value is None else require_string_list(value, "optional list")


def validate_scholar_discovery_request(value: Any) -> dict[str, Any]:
    request = require_dict(value, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ContractError(f"request.schema must equal {REQUEST_SCHEMA}")
    require_string(request.get("request_id"), "request.request_id")
    require_string(request.get("paper_need"), "request.paper_need")
    intent = request.get("intent")
    if intent not in {"auto", "known_item", "topic_set", "author", "citation_graph", "update"}:
        raise ContractError("request.intent is invalid")
    if request.get("effort") not in {"fast", "diligent"}:
        raise ContractError("request.effort must be one of fast or diligent")

    criteria = require_dict(request.get("criteria"), "request.criteria")
    for key in ("must", "should", "must_not"):
        require_string_list(criteria.get(key), f"request.criteria.{key}")
    filters = require_dict(request.get("metadata_filters"), "request.metadata_filters")
    years = require_dict(filters.get("years", {}), "request.metadata_filters.years")
    year_from = years.get("from")
    year_to = years.get("to")
    for key, year in (("from", year_from), ("to", year_to)):
        if year is not None and (
            isinstance(year, bool)
            or not isinstance(year, int)
            or year < 1000
            or year > 3000
        ):
            raise ContractError(f"request.metadata_filters.years.{key} is invalid")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ContractError("request.metadata_filters.years.from exceeds years.to")
    for key in ("authors", "venues", "languages", "work_types"):
        require_string_list(filters.get(key, []), f"request.metadata_filters.{key}")
    if filters.get("open_access") not in {None, True, False}:
        raise ContractError("request.metadata_filters.open_access must be true, false, or null")

    seeds = require_dict(request.get("seeds"), "request.seeds")
    for key in ("doi", "arxiv", "pmid", "openalex", "semantic_scholar", "titles"):
        require_string_list(seeds.get(key, []), f"request.seeds.{key}")

    routes = require_dict(request.get("routes"), "request.routes")
    automatic = require_string_list(routes.get("automatic"), "request.routes.automatic")
    unknown = set(automatic) - AUTOMATIC_PROVIDERS
    if unknown:
        raise ContractError(f"unsupported automatic providers: {sorted(unknown)}")
    if "google_scholar" in automatic:
        raise ContractError("Google Scholar must never be an automatic provider")
    if routes.get("google_scholar") not in {"disabled", "manual_optional", "manual_required"}:
        raise ContractError("request.routes.google_scholar must be valid policy")

    budgets = require_dict(request.get("budgets"), "request.budgets")
    for key in ("max_rounds", "max_queries", "max_candidates", "timeout_seconds"):
        value = budgets.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ContractError(f"request.budgets.{key} must be a positive integer")

    query_seeds = request.get("query_seeds")
    if not isinstance(query_seeds, list) or not query_seeds:
        raise ContractError("request.query_seeds must be a non-empty list")
    objectives: set[str] = set()
    for query_index, seed in enumerate(query_seeds):
        query = require_dict(seed, f"request.query_seeds[{query_index}]")
        objective = query.get("objective")
        if objective not in QUERY_OBJECTIVES:
            raise ContractError("request.query_seeds objective is invalid")
        objectives.add(objective)
        require_string(query.get("query"), f"request.query_seeds[{query_index}].query")
    if not {"confirm", "refute"}.issubset(objectives):
        raise ContractError("request.query_seeds must include confirm and refute")

    return request


def emit_search_requests(
    value: Any,
    network: dict[str, Any] | None = None,
    *,
    google_scholar_policy: str = "manual_optional",
) -> dict[str, Any]:
    if google_scholar_policy not in {"disabled", "manual_optional", "manual_required"}:
        raise ContractError(
            "google_scholar_policy must be disabled, manual_optional, or manual_required"
        )
    document = prioritize(value, network)
    network_ref_value = document["network_ref"]

    requests: list[dict[str, Any]] = []
    seen_request_ids: set[str] = set()
    for hypothesis in document["hypotheses"]:
        if hypothesis["status"] not in ACTIVE_STATUSES:
            continue
        if hypothesis.get("structural_only") or hypothesis.get("needs_semantic_enrichment"):
            hypothesis["next_action"] = "structural_only"
            continue

        search_test = hypothesis["search_test"]
        criteria = search_test.get("criteria", {})
        filters = search_test.get("metadata_filters", {})
        seeds = search_test.get("seeds", {})
        route_families = list(dict.fromkeys(search_test["route_families"]))
        automatic = [route for route in route_families if route in AUTOMATIC_PROVIDERS]
        if not automatic:
            automatic = ["openalex", "semantic_scholar", "crossref"]
        years = filters.get("years", {}) if isinstance(filters, dict) else {}
        request_id = "SDR-" + hypothesis["hypothesis_id"]
        if request_id in seen_request_ids:
            raise ContractError(f"duplicate request_id {request_id}")
        seen_request_ids.add(request_id)
        google_scholar_route = (
            google_scholar_policy
            if "google_scholar" in route_families
            else "disabled"
        )

        request = {
            "schema": REQUEST_SCHEMA,
            "request_id": request_id,
            "paper_need": hypothesis["hypothesis"],
            "intent": "topic_set",
            "effort": "diligent" if hypothesis["decision_impact"] == "high" else "fast",
            "criteria": {
                "must": optional_list(criteria.get("must")),
                "should": optional_list(criteria.get("should")),
                "must_not": optional_list(criteria.get("must_not")),
            },
            "metadata_filters": {
                "years": {"from": years.get("from"), "to": years.get("to")},
                "authors": optional_list(filters.get("authors")),
                "venues": optional_list(filters.get("venues")),
                "languages": optional_list(filters.get("languages")),
                "work_types": optional_list(filters.get("work_types")),
                "open_access": filters.get("open_access"),
            },
            "seeds": {
                key: optional_list(seeds.get(key))
                for key in ("doi", "arxiv", "pmid", "openalex", "semantic_scholar", "titles")
            },
            "routes": {
                "automatic": automatic,
                "google_scholar": google_scholar_route,
            },
            "budgets": {
                "max_rounds": 3,
                "max_queries": min(
                    30, max(6, len(search_test["queries"]) * (len(automatic) + 1))
                ),
                "max_candidates": 100,
                "timeout_seconds": 900,
            },
            "query_seeds": search_test["queries"],
            "as_of": document["generated_at"],
            "gap_ref": {
                "gap_id": hypothesis["hypothesis_id"],
                "network_id": network_ref_value["network_id"],
            },
            "gap_hypothesis_id": hypothesis["hypothesis_id"],
        }
        validate_scholar_discovery_request(request)
        requests.append(request)

    set_payload: dict[str, Any] = {
        "schema_version": REQUEST_SET_SCHEMA_VERSION,
        "network_id": network_ref_value["network_id"],
        "network_snapshot_sha256": network_ref_value["sha256"],
        "generated_at": document["generated_at"],
        "schema": REQUEST_SET_SCHEMA,
        "network_ref": network_ref_value,
        "requests": requests,
    }
    set_payload["request_set_digest"] = canonical_request_set_digest(set_payload)
    set_payload["request_set_id"] = (
        REQUEST_SET_ID_PREFIX + set_payload["request_set_digest"][:16]
    )
    validate_request_set(set_payload)
    return set_payload


def validate_request_set(value: Any, *, network: dict[str, Any] | None = None) -> dict[str, Any]:
    document = require_dict(value, "request set")
    if document.get("schema") != REQUEST_SET_SCHEMA:
        raise ContractError(f"request set schema must equal {REQUEST_SET_SCHEMA}")
    require_string(
        document.get("schema_version"), "request set.schema_version"
    )
    if document["schema_version"] != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("request set.schema_version must be v1")
    require_string(document.get("network_id"), "request set.network_id")
    require_string(document.get("request_set_id"), "request set.request_set_id")
    require_string(document.get("request_set_digest"), "request set.request_set_digest")
    ensure_sha256(document.get("request_set_digest"), "request set.request_set_digest")
    ensure_sha256(
        document.get("network_snapshot_sha256"),
        "request set.network_snapshot_sha256",
    )
    network_ref_value = validate_network_ref(
        document.get("network_ref"), "request set.network_ref"
    )
    if network_ref_value["network_id"] != document["network_id"]:
        raise ContractError("request set network_id does not match request set network_ref")
    if network_ref_value["sha256"] != document["network_snapshot_sha256"]:
        raise ContractError(
            "request set snapshot digest does not match request set network_ref"
        )
    requests = document.get("requests")
    if not isinstance(requests, list):
        raise ContractError("request set.requests must be a list")

    request_ids = set()
    for index_r, request in enumerate(requests):
        request = validate_scholar_discovery_request(request)
        request_id = request["request_id"]
        if request_id in request_ids:
            raise ContractError("request_set duplicate request_id")
        request_ids.add(request_id)
    request_set_digest = document["request_set_digest"]
    expected_digest = canonical_request_set_digest(document)
    if request_set_digest != expected_digest:
        raise ContractError("request set.request_set_digest does not match request set content")
    expected_id = REQUEST_SET_ID_PREFIX + request_set_digest[:16]
    if document.get("request_set_id") != expected_id:
        raise ContractError("request set.request_set_id must match request set digest")
    if network is not None:
        if document.get("network_id") != network["network_id"]:
            raise ContractError("request set network_id does not match supplied network")
        if document.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError("request set snapshot digest mismatch")
        if network_ref_value["snapshot_id"] != network_ref(network)["snapshot_id"]:
            raise ContractError("request set network_ref snapshot_id does not match network")
    return document


def validate_scholar_discovery_result(value: Any) -> dict[str, Any]:
    result = require_dict(value, "result")
    if result.get("schema") != RESULT_SCHEMA:
        raise ContractError(f"result.schema must equal {RESULT_SCHEMA}")
    require_string(result.get("request_id"), "result.request_id")
    require_string(result.get("hypothesis_id"), "result.hypothesis_id")
    ensure_sha256(result.get("request_digest"), "result.request_digest")
    require_timestamp(result.get("as_of"), "result.as_of")
    if result.get("discovery_status") not in DISCOVERY_STATUSES:
        raise ContractError("result.discovery_status is invalid")
    candidates = result.get("ranked_candidates")
    if not isinstance(candidates, list):
        raise ContractError("result.ranked_candidates must be a list")
    for candidate_index, candidate in enumerate(candidates):
        item = require_dict(candidate, f"result.ranked_candidates[{candidate_index}]")
        require_string(item.get("candidate_id"), f"result.ranked_candidates[{candidate_index}].candidate_id")
        for optional_field in ("url", "doi", "exact_locator"):
            if item.get(optional_field) is not None:
                require_string(
                    item.get(optional_field),
                    f"result.ranked_candidates[{candidate_index}].{optional_field}",
                )
        screening = require_dict(item.get("screening"), "result.screening")
        if screening.get("decision") not in {"include", "exclude", "maybe", "unscreened"}:
            raise ContractError("result.ranked_candidates[].screening.decision is invalid")
        require_string(item.get("access_level"), f"result.ranked_candidates[{candidate_index}].access_level")
    provider_failures = result.get("provider_failures")
    if provider_failures is not None and not isinstance(provider_failures, list):
        raise ContractError("result.provider_failures must be a list")
    unresolved_query_ids = result.get("unresolved_query_ids")
    if unresolved_query_ids is not None and (
        not isinstance(unresolved_query_ids, list)
        or not all(
            isinstance(item, str)
            or (
                isinstance(item, dict)
                and isinstance(item.get("provider"), str)
            )
            for item in unresolved_query_ids
        )
    ):
        raise ContractError(
            "result.unresolved_query_ids must be a list of strings or provider maps"
        )
    return result


def validate_scholar_discovery_result_set(
    value: Any,
    *,
    request_set: dict[str, Any] | None = None,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "result set")
    if document.get("schema") != RESULT_SET_SCHEMA:
        raise ContractError(
            f"result set schema must equal {RESULT_SET_SCHEMA}"
    )
    request_set_id = require_string(document.get("request_set_id"), "result_set.request_set_id")
    request_set_digest = require_string(
        document.get("request_set_digest"), "result_set.request_set_digest"
    )
    ensure_sha256(document.get("request_set_digest"), "result_set.request_set_digest")
    if request_set is not None:
        expected = require_string(request_set.get("request_set_id"), "request set.request_set_id")
        if request_set_id != expected:
            raise ContractError("result_set.request_set_id does not match request set")
        expected_digest = require_string(
            request_set.get("request_set_digest"), "request set.request_set_digest"
        )
        if request_set_digest != expected_digest:
            raise ContractError("result_set.request_set_digest does not match request set")
    require_string(document.get("network_id"), "result_set.network_id")
    network_ref_value = validate_network_ref(document.get("network_ref"), "result_set.network_ref")
    if network_ref_value["network_id"] != document.get("network_id"):
        raise ContractError("result_set.network_id does not match result_set.network_ref")
    if network_ref_value["sha256"] != document.get("network_snapshot_sha256"):
        raise ContractError(
            "result_set.network_snapshot_sha256 does not match result_set.network_ref"
        )
    ensure_sha256(
        document.get("network_snapshot_sha256"),
        "result_set.network_snapshot_sha256",
    )
    require_timestamp(document.get("generated_at"), "result_set.generated_at")
    if network is not None:
        if document.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError("result_set.network_id does not match supplied network")
        if document.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError(
                "result_set.network_snapshot_sha256 does not match supplied network"
            )
    results = document.get("results")
    if not isinstance(results, list):
        raise ContractError("result_set.results must be a list")
    normalized_results = [validate_scholar_discovery_result(item) for item in results]
    if request_set is not None:
        request_ids = {request["request_id"] for request in request_set.get("requests", [])}
        request_by_id = {request["request_id"]: request for request in request_set.get("requests", [])}
        for result in normalized_results:
            if result["request_id"] not in request_ids:
                raise ContractError("result_set includes unknown request_id")
            request = request_by_id[result["request_id"]]
            expected = request_digest(request)
            if result["request_digest"] != expected:
                raise ContractError(
                    f"result.request_digest mismatch for request_id {result['request_id']}"
                )
            if normalize_hypothesis_id(result["hypothesis_id"]) != normalize_hypothesis_id(
                request.get("gap_hypothesis_id", "")
            ):
                raise ContractError("result.hypothesis_id does not match request gap hypothesis")
    validated = dict(document)
    validated["results"] = normalized_results
    return validated


def normalize_result_set(
    value: Any,
    *,
    request_set: dict[str, Any] | None = None,
    network: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # Result-set normalizer for consume-results.
    payload = require_dict(value, "result input")
    if payload.get("schema") == RESULT_SCHEMA:
        raise ContractError(
            "consume-results expects ScholarDiscoveryResultSet/v1 payloads only"
        )
    if payload.get("schema") != RESULT_SET_SCHEMA:
        raise ContractError(f"unsupported result schema: {payload.get('schema')!r}")

    request_set_id = require_string(payload.get("request_set_id"), "result_set.request_set_id")
    request_set_digest = require_string(
        payload.get("request_set_digest"), "result_set.request_set_digest"
    )
    ensure_sha256(payload.get("request_set_digest"), "result_set.request_set_digest")
    if request_set is not None:
        expected = require_string(request_set.get("request_set_id"), "request set.request_set_id")
        if request_set_id != expected:
            raise ContractError("result_set.request_set_id does not match request set")
        expected_digest = require_string(
            request_set.get("request_set_digest"), "request set.request_set_digest"
        )
        if request_set_digest != expected_digest:
            raise ContractError("result_set.request_set_digest does not match request set")
    require_string(payload.get("network_id"), "result_set.network_id")
    network_ref_value = validate_network_ref(payload.get("network_ref"), "result_set.network_ref")
    if network_ref_value["network_id"] != payload.get("network_id"):
        raise ContractError("result_set.network_id does not match result_set.network_ref")
    if network_ref_value["sha256"] != payload.get("network_snapshot_sha256"):
        raise ContractError(
            "result_set.network_snapshot_sha256 does not match result_set.network_ref"
        )
    ensure_sha256(payload.get("network_snapshot_sha256"), "result_set.network_snapshot_sha256")
    require_timestamp(payload.get("generated_at"), "result_set.generated_at")
    if network is not None:
        if payload.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError("result_set.network_id does not match supplied network")
        if payload.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError(
                "result_set.network_snapshot_sha256 does not match supplied network"
            )

    results = payload.get("results")
    if not isinstance(results, list):
        raise ContractError("result_set.results must be a list")
    normalized = [
        validate_scholar_discovery_result(item)
        for item in results
    ]
    if request_set is not None:
        request_by_id = {request["request_id"]: request for request in request_set.get("requests", [])}
        for item in normalized:
            request = request_by_id.get(item["request_id"])
            if request is None:
                raise ContractError("result_set includes unknown request_id")
            if normalize_hypothesis_id(item["hypothesis_id"]) != normalize_hypothesis_id(
                request.get("gap_hypothesis_id", "")
            ):
                raise ContractError("result.hypothesis_id does not match request gap hypothesis")
    return normalized


def validate_learn_from_papers_request(value: Any) -> dict[str, Any]:
    request = require_dict(value, "review request")
    if request.get("schema") != LEARN_FROM_PAPERS_REQUEST_SCHEMA:
        raise ContractError(
            f"review request.schema must equal {LEARN_FROM_PAPERS_REQUEST_SCHEMA}"
        )
    require_string(request.get("request_id"), "review request.request_id")
    require_string(request.get("source_request_id"), "review request.source_request_id")
    require_string(request.get("hypothesis_id"), "review request.hypothesis_id")
    sources = request.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ContractError("review request.sources must be a non-empty list")
    for index, source in enumerate(sources):
        entry = require_dict(source, f"review request.sources[{index}]")
        require_string(
            entry.get("source_id"), f"review request.sources[{index}].source_id"
        )
        ensure_sha256(entry.get("source_digest"), f"review request.sources[{index}].source_digest")
        if not entry.get("source_id").startswith(SOURCE_ID_PREFIX):
            raise ContractError("review request source_id must use SRC- prefix")
        require_string(
            entry.get("source_ref"), f"review request.sources[{index}].source_ref"
        )
        require_string(
            entry.get("exact_locator"),
            f"review request.sources[{index}].exact_locator",
        )
        read_depth = require_string(
            entry.get("read_depth"), f"review request.sources[{index}].read_depth"
        )
        if read_depth not in READ_DEPTHS:
            raise ContractError(
                f"review request.sources[{index}].read_depth invalid"
            )
        required_read_depth = require_string(
            entry.get("required_read_depth"),
            f"review request.sources[{index}].required_read_depth",
        )
        if required_read_depth not in READ_DEPTHS:
            raise ContractError(
                f"review request.sources[{index}].required_read_depth invalid"
            )
        if required_read_depth != read_depth:
            raise ContractError(
                f"review request.sources[{index}].required_read_depth must match read_depth"
            )
        if entry.get("discovery_only") is not True:
            raise ContractError(
                f"review request.sources[{index}].discovery_only must be true"
            )
        if entry.get("claim_support_eligible") is not False:
            raise ContractError(
                f"review request.sources[{index}].claim_support_eligible must be false"
            )
        if not any((entry.get(field)) for field in ("url", "doi")):
            raise ContractError(
                f"review request.sources[{index}] must include url or doi"
            )
    return request


def validate_learn_from_papers_request_set(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "review request set")
    if document.get("schema") != LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA:
        raise ContractError(
            f"review request set schema must equal {LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA}"
        )
    require_string(document.get("request_set_id"), "review request set.request_set_id")
    require_string(document.get("request_set_digest"), "review request set.request_set_digest")
    ensure_sha256(document.get("request_set_digest"), "review request set.request_set_digest")
    expected_digest = canonical_request_set_digest(document)
    if document.get("request_set_digest") != expected_digest:
        raise ContractError(
            "review request set.request_set_digest does not match request set content"
        )
    expected_id = LEARN_REQUEST_SET_ID_PREFIX + expected_digest[:16]
    if document.get("request_set_id") != expected_id:
        raise ContractError("review request set.request_set_id must match request set digest")
    require_string(document.get("network_id"), "review request set.network_id")
    validate_network_ref(document.get("network_ref"), "review request set.network_ref")
    ensure_sha256(
        document.get("network_snapshot_sha256"),
        "review request set.network_snapshot_sha256",
    )
    network_ref_value = document.get("network_ref")
    if network_ref_value.get("network_id") != document.get("network_id"):
        raise ContractError(
            "review request set network_id does not match review request set network_ref"
        )
    if network_ref_value.get("sha256") != document.get("network_snapshot_sha256"):
        raise ContractError(
            "review request set snapshot digest does not match review request set network_ref"
        )
    require_timestamp(document.get("generated_at"), "review request set.generated_at")

    requests = document.get("requests")
    if not isinstance(requests, list):
        raise ContractError("review request set.requests must be a list")
    request_ids = set()
    for request in requests:
        item = validate_learn_from_papers_request(request)
        if item["request_id"] in request_ids:
            raise ContractError("review request set duplicate request_id")
        request_ids.add(item["request_id"])

    if network is not None:
        if document.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError(
                "review request set network_id does not match supplied network"
            )
        if document.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError(
                "review request set network_snapshot_sha256 does not match supplied network"
            )
        if network_ref_value.get("snapshot_id") != network_ref(network)["snapshot_id"]:
            raise ContractError(
                "review request set network_ref snapshot_id does not match supplied network"
            )
    return document


def _is_unacceptable_locator(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("http://") or lowered.startswith("https://") or bool(
        re.fullmatch(r"10\.[0-9]+/.+", value)
    )


def validate_evidence_passage(value: Any, *, report_id: str | None = None) -> dict[str, Any]:
    passage = require_dict(value, "paper reading report passage")
    if report_id is not None:
        pass_label = f"paper reading report {report_id} passage"
    else:
        pass_label = "paper reading report passage"
    require_string(passage.get("passage_id"), f"{pass_label}.passage_id")
    ensure_sha256(passage.get("passage_digest"), f"{pass_label}.passage_digest")
    locator_type = require_string(
        passage.get("locator_type"), f"{pass_label}.locator_type"
    )
    if locator_type not in LOCATOR_TYPES:
        raise ContractError(f"{pass_label}.locator_type invalid")
    exact_locator = require_string(
        passage.get("exact_locator"), f"{pass_label}.exact_locator"
    )
    if _is_unacceptable_locator(exact_locator):
        raise ContractError(f"{pass_label}.exact_locator must not be DOI/URL")
    require_string(passage.get("claim_summary"), f"{pass_label}.claim_summary")
    require_string(passage.get("evidence_summary"), f"{pass_label}.evidence_summary")
    if _is_unacceptable_locator(passage.get("passage_sha256", "")):
        raise ContractError(f"{pass_label}.passage_sha256 cannot be DOI/URL")
    ensure_sha256(passage.get("passage_sha256"), f"{pass_label}.passage_sha256")

    expected_digest = canonical_evidence_passage_digest(passage)
    if passage.get("passage_digest") != expected_digest:
        raise ContractError(
            f"{pass_label}.passage_digest does not match passage content"
        )
    expected_id = PASSAGE_ID_PREFIX + expected_digest[:16]
    if passage.get("passage_id") != expected_id:
        raise ContractError(f"{pass_label}.passage_id must match passage digest")
    return passage


def validate_paper_reading_report(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = require_dict(value, "paper reading report")
    if report.get("schema") != PAPER_READING_REPORT_SCHEMA:
        raise ContractError(
            f"paper reading report.schema must equal {PAPER_READING_REPORT_SCHEMA}"
        )
    if report.get("review_request_set_id") is not None:
        require_string(
            report.get("review_request_set_id"),
            "paper reading report.review_request_set_id",
        )
    if report.get("review_request_set_digest") is not None:
        ensure_sha256(
            report.get("review_request_set_digest"),
            "paper reading report.review_request_set_digest",
        )
    require_string(report.get("report_id"), "paper reading report.report_id")
    require_string(report.get("report_digest"), "paper reading report.report_digest")
    ensure_sha256(report.get("report_digest"), "paper reading report.report_digest")
    require_string(report.get("review_request_id"), "paper reading report.review_request_id")
    require_string(report.get("review_request_digest"), "paper reading report.review_request_digest")
    ensure_sha256(
        report.get("review_request_digest"), "paper reading report.review_request_digest"
    )
    require_string(report.get("source_id"), "paper reading report.source_id")
    require_string(report.get("source_digest"), "paper reading report.source_digest")
    ensure_sha256(report.get("source_digest"), "paper reading report.source_digest")
    require_string(report.get("source_ref"), "paper reading report.source_ref")
    if report.get("exact_locator") is not None:
        require_string(report.get("exact_locator"), "paper reading report.exact_locator")
    read_depth = require_string(report.get("read_depth"), "paper reading report.read_depth")
    if read_depth != READING_DEPTH_ONLY_FULL_TEXT:
        raise ContractError("paper reading report.read_depth must be full_text")
    if report.get("producer") is not None and report.get("producer") != READER_PRODUCER:
        raise ContractError("paper reading report.producer must be learn-from-papers")
    if report.get("protocol_version") is not None:
        protocol_version = require_string(
            report.get("protocol_version"), "paper reading report.protocol_version"
        )
        if protocol_version != READING_REPORT_PROTOCOL:
            raise ContractError("paper reading report.protocol_version must be 1.0")
    ensure_sha256(report.get("source_artifact_sha256"), "paper reading report.source_artifact_sha256")
    if "passages" in report:
        raise ContractError("paper reading report.passages is deprecated")
    passages = report.get("evidence_passages")
    if not isinstance(passages, list) or not passages:
        raise ContractError("paper reading report.evidence_passages must be a non-empty list")
    source_artifact = report.get("source_artifact_sha256")
    for index, passage in enumerate(passages):
        valid_passage = validate_evidence_passage(passage, report_id=report.get("report_id", ""))
        if source_artifact is None:
            raise ContractError("paper reading report.source_artifact_sha256 is required")
        if source_artifact != report.get("source_artifact_sha256"):
            raise ContractError("paper reading report source_artifact_sha256 mismatch")
        passages[index] = valid_passage

    expected_digest = canonical_reading_report_digest(report)
    if report.get("report_digest") != expected_digest:
        raise ContractError("paper reading report.report_digest does not match report content")
    expected_id = READING_REPORT_ID_PREFIX + expected_digest[:16]
    if report.get("report_id") != expected_id:
        raise ContractError("paper reading report.report_id must match report digest")
    if network is not None:
        if not isinstance(network, dict):
            raise ContractError("network must be an object")
    return report


def validate_paper_reading_report_set(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "paper reading report set")
    if document.get("schema") != PAPER_READING_REPORT_SET_SCHEMA:
        raise ContractError(
            f"paper reading report set schema must equal {PAPER_READING_REPORT_SET_SCHEMA}"
        )
    require_string(document.get("schema_version"), "paper reading report set.schema_version")
    if document["schema_version"] != PAPER_READING_REPORT_SET_SCHEMA_VERSION:
        raise ContractError(
            "paper reading report set.schema_version must be v1"
        )
    require_string(
        document.get("review_request_set_id"),
        "paper reading report set.review_request_set_id",
    )
    require_string(
        document.get("review_request_set_digest"),
        "paper reading report set.review_request_set_digest",
    )
    ensure_sha256(
        document.get("review_request_set_digest"),
        "paper reading report set.review_request_set_digest",
    )
    require_string(document.get("report_set_id"), "paper reading report set.report_set_id")
    require_string(
        document.get("report_set_digest"), "paper reading report set.report_set_digest"
    )
    ensure_sha256(
        document.get("report_set_digest"), "paper reading report set.report_set_digest"
    )
    if document.get("source_artifact_sha256") is not None:
        ensure_sha256(
            document.get("source_artifact_sha256"),
            "paper reading report set.source_artifact_sha256",
        )
    require_string(document.get("producer"), "paper reading report set.producer")
    if document.get("producer") != READER_PRODUCER:
        raise ContractError("paper reading report set.producer must be learn-from-papers")
    require_string(document.get("protocol_version"), "paper reading report set.protocol_version")
    require_timestamp(document.get("generated_at"), "paper reading report set.generated_at")
    validate_network_ref(document.get("network_ref"), "paper reading report set.network_ref")
    network_ref_value = document.get("network_ref")
    if not isinstance(network_ref_value, dict):
        raise ContractError("paper reading report set.network_ref must be an object")
    if document.get("network_id") is not None and network_ref_value.get("network_id") != document.get("network_id"):
        raise ContractError(
            "paper reading report set network_id does not match network_ref"
        )
    if document.get("network_snapshot_sha256") is not None and network_ref_value.get("sha256") != document.get("network_snapshot_sha256"):
        raise ContractError(
            "paper reading report set snapshot digest does not match network_ref"
        )

    reports = document.get("reports")
    if not isinstance(reports, list) or not reports:
        raise ContractError("paper reading report set.reports must be a non-empty list")
    report_ids: set[str] = set()
    for index, report in enumerate(reports):
        valid_report = validate_paper_reading_report(
            report,
            network=network,
        )
        reports[index] = valid_report
        if valid_report.get("review_request_set_id") is not None and valid_report["review_request_set_id"] != document["review_request_set_id"]:
            raise ContractError(
                "paper reading report set.review_request_set_id mismatch"
            )
        if valid_report.get("review_request_set_digest") is not None and valid_report["review_request_set_digest"] != document["review_request_set_digest"]:
            raise ContractError(
                "paper reading report set.review_request_set_digest mismatch"
            )
        if document.get("source_artifact_sha256") is not None and valid_report["source_artifact_sha256"] != document.get("source_artifact_sha256"):
            raise ContractError("paper reading report set.source_artifact_sha256 mismatch")
        if valid_report["report_id"] in report_ids:
            raise ContractError("paper reading report set duplicate report_id")
        report_ids.add(valid_report["report_id"])

    expected_digest = canonical_report_set_digest(document)
    if document.get("report_set_digest") != expected_digest:
        raise ContractError("paper reading report set report_set_digest mismatch")
    expected_id = REPORT_SET_ID_PREFIX + expected_digest[:16]
    if document.get("report_set_id") != expected_id:
        raise ContractError("paper reading report set.report_set_id mismatch")

    if network is not None:
        if network_ref_value.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError("paper reading report set network_id mismatch")
        if network_ref_value.get("sha256") != network_ref(network)["sha256"]:
            raise ContractError(
                "paper reading report set snapshot digest mismatch"
            )
    return document


def validate_reviewed_evidence(value: Any) -> dict[str, Any]:
    item = require_dict(value, "reviewed evidence")
    if item.get("schema") != REVIEWED_EVIDENCE_SCHEMA:
        raise ContractError(f"reviewed evidence.schema must equal {REVIEWED_EVIDENCE_SCHEMA}")
    require_string(item.get("request_set_id"), "reviewed evidence.request_set_id")
    require_string(item.get("reading_report_id"), "reviewed evidence.reading_report_id")
    if not item["reading_report_id"].startswith(READING_REPORT_ID_PREFIX):
        raise ContractError(
            "reviewed evidence.reading_report_id must start with reading-report-"
        )
    require_string(item.get("reading_report_digest"), "reviewed evidence.reading_report_digest")
    ensure_sha256(item.get("reading_report_digest"), "reviewed evidence.reading_report_digest")
    require_string(item.get("passage_id"), "reviewed evidence.passage_id")
    if not item["passage_id"].startswith(PASSAGE_ID_PREFIX):
        raise ContractError("reviewed evidence.passage_id must start with passage-")
    require_string(item.get("passage_digest"), "reviewed evidence.passage_digest")
    ensure_sha256(item.get("passage_digest"), "reviewed evidence.passage_digest")
    require_string(item.get("review_request_id"), "reviewed evidence.review_request_id")
    require_string(item.get("review_request_digest"), "reviewed evidence.review_request_digest")
    require_string(item.get("source_id"), "reviewed evidence.source_id")
    ensure_sha256(item.get("review_request_digest"), "reviewed evidence.review_request_digest")
    ensure_sha256(item.get("source_digest"), "reviewed evidence.source_digest")
    require_string(item.get("request_id"), "reviewed evidence.request_id")
    require_string(item.get("hypothesis_id"), "reviewed evidence.hypothesis_id")
    require_string(item.get("source_ref"), "reviewed evidence.source_ref")
    require_string(item.get("exact_locator"), "reviewed evidence.exact_locator")
    if not any((item.get(field)) for field in ("doi", "url")):
        raise ContractError("reviewed evidence must include doi or url")
    read_depth = require_string(item.get("read_depth"), "reviewed evidence.read_depth")
    if read_depth not in READ_DEPTHS:
        raise ContractError("reviewed evidence.read_depth must be full_text or evidence")
    if item.get("review_completed") is not True:
        raise ContractError("reviewed evidence.review_completed must be true")

    if item.get("claim_support_eligible") is not True:
        raise ContractError("reviewed evidence.claim_support_eligible must be true")
    if item.get("discovery_only") is not False:
        raise ContractError("reviewed evidence.discovery_only must be false")
    outcome = item.get("outcome")
    if outcome not in {"supports", "contradicts", "already_covered", "unknown"}:
        raise ContractError(
            "reviewed evidence outcome must be supports, contradicts, already_covered, or unknown"
        )
    return item


def validate_reviewed_evidence_set(
    value: Any,
    *,
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = require_dict(value, "reviewed evidence set")
    if document.get("schema") != REVIEWED_EVIDENCE_SET_SCHEMA:
        raise ContractError(
            f"reviewed evidence set schema must equal {REVIEWED_EVIDENCE_SET_SCHEMA}"
        )
    require_string(document.get("schema_version"), "reviewed evidence set.schema_version")
    require_string(document.get("request_set_id"), "reviewed evidence set.request_set_id")
    require_string(document.get("request_set_digest"), "reviewed evidence set.request_set_digest")
    ensure_sha256(document.get("request_set_digest"), "reviewed evidence set.request_set_digest")
    require_string(document.get("evidence_set_digest"), "reviewed evidence set.evidence_set_digest")
    ensure_sha256(document.get("evidence_set_digest"), "reviewed evidence set.evidence_set_digest")
    expected_evidence_set_digest = canonical_evidence_set_digest(document)
    if document["evidence_set_digest"] != expected_evidence_set_digest:
        raise ContractError(
            "reviewed evidence set.evidence_set_digest does not match reviewed evidence set content"
        )
    require_string(document.get("network_id"), "reviewed evidence set.network_id")
    validate_network_ref(document.get("network_ref"), "reviewed evidence set.network_ref")
    ensure_sha256(
        document.get("network_snapshot_sha256"),
        "reviewed evidence set.network_snapshot_sha256",
    )
    network_ref_value = document.get("network_ref")
    if network_ref_value.get("network_id") != document.get("network_id"):
        raise ContractError(
            "reviewed evidence set network_id does not match reviewed evidence set network_ref"
        )
    if network_ref_value.get("sha256") != document.get("network_snapshot_sha256"):
        raise ContractError(
            "reviewed evidence set snapshot digest does not match reviewed evidence set network_ref"
        )
    require_timestamp(document.get("generated_at"), "reviewed evidence set.generated_at")

    evidence_items = document.get("evidence")
    if not isinstance(evidence_items, list):
        raise ContractError("reviewed evidence set.evidence must be a list")
    for item in evidence_items:
        item = validate_reviewed_evidence(item)
        if item["request_set_id"] != document["request_set_id"]:
            raise ContractError("reviewed evidence item request_set_id does not match set")

    if network is not None:
        if document.get("network_id") != network_ref(network)["network_id"]:
            raise ContractError(
                "reviewed evidence set network_id does not match supplied network"
            )
        if document.get("network_snapshot_sha256") != network_ref(network)["sha256"]:
            raise ContractError(
                "reviewed evidence set network_snapshot_sha256 does not match supplied network"
            )
        if network_ref(document["network_ref"])["snapshot_id"] != network_ref(network)["snapshot_id"]:
            raise ContractError(
                "reviewed evidence set network_ref snapshot_id does not match supplied network"
            )
    return document


def _collect_candidate_sources(
    request_id: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def _as_str(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    def _collect_manifestation_url(candidate: dict[str, Any]) -> str | None:
        manifestations = candidate.get("manifestations")
        if not isinstance(manifestations, list):
            return None
        for item in manifestations:
            if not isinstance(item, dict):
                continue
            url = _as_str(item.get("landing_url"))
            if url:
                return url
        return None

    sources: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:3]):
        exact_locator = _as_str(candidate.get("exact_locator"))
        if exact_locator is None:
            exact_locator = _as_str(candidate.get("doi"))
        doi = _as_str(candidate.get("doi"))
        if doi is None and isinstance(candidate.get("identifiers"), dict):
            identifiers = candidate["identifiers"]
            doi = _as_str(identifiers.get("doi"))
            if doi:
                exact_locator = doi
            else:
                exact_locator = (
                    exact_locator
                    or _as_str(identifiers.get("arxiv"))
                    or _as_str(identifiers.get("pmid"))
                    or _as_str(identifiers.get("openalex"))
                )
        if exact_locator is None:
            exact_locator = _as_str(candidate.get("url"))
        if exact_locator is None:
            exact_locator = _collect_manifestation_url(candidate)
        if not exact_locator:
            continue
        exact_locator_text = str(exact_locator)
        access_level = candidate.get("access_level", "evidence")
        read_depth = access_to_read_depth(access_level)
        source_ref = f"{request_id}-candidate-{index}"
        source_payload: dict[str, Any] = {
            "request_id": request_id,
            "source_ref": source_ref,
            "candidate_id": candidate.get("candidate_id", source_ref),
            "exact_locator": exact_locator_text,
            "read_depth": read_depth,
            "required_read_depth": read_depth,
            "screening_decision": candidate.get("screening", {}).get("decision"),
            "access_level": access_level,
            "query_seed_position": index,
            "title": candidate.get("title"),
        }
        source_digest = sha256_json(source_payload)
        item: dict[str, Any] = {
            "source_id": SOURCE_ID_PREFIX + source_digest[:16],
            "source_digest": source_digest,
            "source_ref": source_ref,
            "exact_locator": exact_locator_text,
            "read_depth": read_depth,
            "required_read_depth": read_depth,
            "discovery_only": True,
            "claim_support_eligible": False,
            "query_seed_position": index,
        }
        if candidate.get("doi"):
            item["doi"] = candidate["doi"]
        elif doi:
            item["doi"] = doi
        elif candidate.get("url"):
            item["url"] = candidate["url"]
        elif "://" in exact_locator_text:
            item["url"] = exact_locator_text
        else:
            item["doi"] = exact_locator_text
        manifest_url = _collect_manifestation_url(candidate)
        if manifest_url and "url" not in item:
            item["url"] = manifest_url
        screening_decision = candidate.get("screening", {}).get("decision")
        if screening_decision:
            item["screening_decision"] = screening_decision
        item["source_ref"] = source_ref
        sources.append(item)
    return sources


def _result_is_pending(
    result: dict[str, Any],
) -> bool:
    unresolved_query_ids = result.get("unresolved_query_ids") or []
    if unresolved_query_ids:
        return True
    provider_failures = result.get("provider_failures") or []
    if provider_failures:
        return True
    if result.get("discovery_status") in {
        "partial_provider",
        "partial_budget",
        "blocked_capability",
        "pending",
    }:
        return True
    return False


def _result_provider_from_entry(entry: Any) -> str | None:
    if isinstance(entry, dict):
        provider = entry.get("provider")
        return provider.strip() if isinstance(provider, str) else None
    if not isinstance(entry, str):
        return None
    if entry.startswith("provider:"):
        provider = entry.split(":", 1)[1]
        return provider.strip() or None
    if entry.startswith("provider="):
        provider = entry.split("=", 1)[1]
        return provider.strip() or None
    if entry.startswith("google_scholar:"):
        return "google_scholar"
    return None


def _has_provider_marker(value: Any, provider: str) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        item_provider = _result_provider_from_entry(item)
        if item_provider and item_provider == provider:
            return True
    return False


def _review_evidence_identity(item: dict[str, Any]) -> tuple[str, str]:
    evidence_digest = sha256_json(item)
    return "EV-" + evidence_digest[:16], evidence_digest


def _derive_reviewed_hypothesis_status(
    evidence_items: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    supports = [item for item in evidence_items if item["outcome"] == "supports"]
    contradicted = [
        item
        for item in evidence_items
        if item["outcome"] in {"contradicts", "already_covered"}
    ]
    unknown = [item for item in evidence_items if item["outcome"] == "unknown"]

    if supports and contradicted:
        return "contested", supports + contradicted
    if supports:
        status = "content_found"
        if not any(item.get("read_depth") == "full_text" for item in supports):
            status = "supported_gap"
        return status, supports
    if any(item["outcome"] == "already_covered" for item in contradicted):
        return "already_covered", contradicted
    if contradicted:
        return "refuted", contradicted
    if unknown:
        return "unresolved", []
    return "results", []


def _execution_state_entry(
    request_id: str,
    execution_state: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "source_ref": request_id,
        "locator": "discovery result pending or captured",
        "read_depth": "evidence",
        "execution_state": execution_state,
    }
    if details:
        entry.update(details)
    return entry


def consume_results(
    hypotheses_value: Any,
    network: dict[str, Any],
    request_set_value: Any,
    result_values: list[Any],
    *,
    round_id: str | None = None,
) -> dict[str, Any]:
    hypotheses_doc = validate_hypotheses(hypotheses_value, network)
    request_set = validate_request_set(request_set_value, network=network)
    request_map: dict[str, dict[str, Any]] = {}
    for request in request_set["requests"]:
        request_map[request["request_id"]] = request
        gap_ref = request.get("gap_hypothesis_id")
        if gap_ref:
            request_map["SDR-" + gap_ref] = request

    request_ids = set(request_map)
    result_map: dict[str, dict[str, Any]] = {}
    for result in result_values:
        parsed = normalize_result_set(result, request_set=request_set, network=network)
        for item in parsed:
            request_id = item["request_id"]
            if request_id not in request_ids:
                raise ContractError(f"result.request_id {request_id} not in request set")
            expected = request_digest(request_map[request_id])
            if item["request_digest"] != expected:
                raise ContractError(
                    f"result.request_digest mismatch for request_id {request_id}"
                )
            if normalize_hypothesis_id(item["hypothesis_id"]) != normalize_hypothesis_id(
                request_map[request_id].get("gap_hypothesis_id", "")
            ):
                raise ContractError(
                    "result.hypothesis_id does not match request gap hypothesis"
                )
            if request_id in result_map:
                raise ContractError(f"duplicate result for request_id {request_id}")
            result_map[request_id] = item

    previous_cycle = hypotheses_doc.get("cycle_state", {})
    previous_round = previous_cycle.get("discovery_round", 0)
    if not isinstance(previous_round, int):
        previous_round = 0
    previous_no_progress = previous_cycle.get("consecutive_no_progress_rounds", 0)
    if not isinstance(previous_no_progress, int):
        previous_no_progress = 0

    max_rounds = max(
        (
            request.get("budgets", {}).get("max_rounds", 1)
            for request in request_set.get("requests", [])
        ),
        default=1,
    )

    cycle_state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "round_id": round_id or hypotheses_doc.get("round_id", timestamp_now()),
        "generated_at": timestamp_now(),
        "network_snapshot_sha256": network_ref(network)["sha256"],
        "network_id": network_ref(network)["network_id"],
        "request_set_id": request_set.get("request_set_id"),
        "request_set_digest": request_set.get("request_set_digest"),
        "discovery_round": previous_round + 1 if result_values else previous_round,
        "results_consumed": 0,
        "awaiting_results": 0,
        "status_counts": {status: 0 for status in sorted(STATUSES)},
        "consecutive_no_progress_rounds": previous_no_progress,
        "max_rounds": max_rounds,
        "next_actions": [],
        "phase": "idle",
        "stop_reason": "",
        "pending_reason": "",
        "saturation": False,
    }

    review_requests: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    has_progress = False
    provider_pending = False
    manual_pending = False

    for hypothesis in hypotheses_doc["hypotheses"]:
        hypothesis = json.loads(json.dumps(hypothesis))
        hypothesis_id = hypothesis["hypothesis_id"]
        request_id = f"SDR-{hypothesis_id}"
        request = request_map.get(request_id)
        result = result_map.get(request_id)
        previous_status = hypothesis["status"]
        if hypothesis.get("structural_only"):
            hypothesis["next_action"] = "structural_only"
            if previous_status in DISCOVERY_ACTIVE_STATUSES:
                if previous_status != "no_signal":
                    hypothesis["status"] = "no_signal"
                    if previous_status != "no_signal":
                        has_progress = True
                else:
                    hypothesis["status"] = "no_signal"
            hypothesis["status_basis"] = []
            cycle_state["status_counts"][hypothesis["status"]] += 1
            updated.append(hypothesis)
            continue

        if previous_status not in DISCOVERY_ACTIVE_STATUSES:
            cycle_state["status_counts"][previous_status] += 1
            updated.append(hypothesis)
            continue

        if result is None:
            if request and request.get("routes", {}).get("google_scholar") == "manual_required":
                hypothesis["status"] = "awaiting"
                manual_pending = True
                cycle_state["awaiting_results"] += 1
                hypothesis["status_basis"] = [
                    _execution_state_entry(
                        request_id,
                        "pending_execution",
                        {
                            "discovery_status": "manual_capture_required",
                            "google_scholar_route": "manual_required",
                        },
                    )
                ]
                hypothesis["next_action"] = "consume-reviewed-evidence"
            else:
                hypothesis["status"] = "awaiting"
                provider_pending = True
                cycle_state["awaiting_results"] += 1
                hypothesis["status_basis"] = [
                    _execution_state_entry(request_id, "not_executed")
                ]
                hypothesis["next_action"] = "scholar_discovery"
        elif _result_is_pending(result):
            ranked_candidates = result.get("ranked_candidates") or []
            has_ranked_candidates = bool(ranked_candidates)
            if has_ranked_candidates:
                sources = _collect_candidate_sources(request_id, ranked_candidates)
                if sources:
                    hypothesis["status"] = "results"
                    hypothesis["status_basis"] = [
                        _execution_state_entry(
                            request_id,
                            "retry_or_route_pending",
                            {
                                "discovery_status": result["discovery_status"],
                            },
                        )
                    ]
                    hypothesis["next_action"] = "learn_from_papers"
                    review_requests.append(
                        {
                            "schema": LEARN_FROM_PAPERS_REQUEST_SCHEMA,
                            "request_id": f"LFR-{request_id}",
                            "source_request_id": request_id,
                            "hypothesis_id": hypothesis_id,
                            "sources": sources,
                        }
                    )
                    provider_pending = True
                else:
                    has_ranked_candidates = False
            if not has_ranked_candidates:
                is_manual_required = False
                google_scholar_route = request.get("routes", {}).get("google_scholar")
                has_google_scholar_provider = _has_provider_marker(
                    result.get("unresolved_query_ids"),
                    "google_scholar",
                ) or _has_provider_marker(result.get("provider_failures"), "google_scholar")
                if google_scholar_route == "manual_required" and has_google_scholar_provider:
                    is_manual_required = True
                    manual_pending = True
                hypothesis["status"] = "awaiting"
                status_basis = {
                    "discovery_status": result["discovery_status"],
                }
                if result.get("unresolved_query_ids"):
                    status_basis["unresolved_query_ids"] = result["unresolved_query_ids"]
                if result.get("provider_failures"):
                    status_basis["provider_failures"] = result["provider_failures"]
                hypothesis["status_basis"] = [
                    _execution_state_entry(
                        request_id,
                        "retry_or_route_pending",
                        status_basis,
                    )
                ]
                if is_manual_required:
                    if google_scholar_route == "manual_required":
                        hypothesis["status_basis"][0]["google_scholar_route"] = "manual_required"
                    hypothesis["next_action"] = "manual_scholar_export"
                else:
                    provider_pending = True
                    hypothesis["next_action"] = "scholar_discovery"
                cycle_state["awaiting_results"] += 1
        elif not result.get("ranked_candidates"):
            hypothesis["status"] = "no_signal"
            hypothesis["status_basis"] = []
            hypothesis["next_action"] = "scholar_discovery"
        else:
            sources = _collect_candidate_sources(request_id, result.get("ranked_candidates", []))
            if sources:
                hypothesis["status"] = "results"
                hypothesis["status_basis"] = []
                hypothesis["next_action"] = "learn_from_papers"
                review_requests.append(
                    {
                        "schema": LEARN_FROM_PAPERS_REQUEST_SCHEMA,
                        "request_id": f"LFR-{request_id}",
                        "source_request_id": request_id,
                        "hypothesis_id": hypothesis_id,
                        "sources": sources,
                    }
                )
            else:
                hypothesis["status"] = "no_signal"
                hypothesis["status_basis"] = []
                hypothesis["next_action"] = "scholar_discovery"

        if hypothesis["status"] != previous_status:
            has_progress = True

        if hypothesis["status"] in {"content_found", "supported_gap", "contested", "refuted", "already_covered"}:
            validate_hypotheses({**hypotheses_doc, "hypotheses": [hypothesis]})

        if hypothesis["status"] == "results":
            cycle_state["results_consumed"] += 1

        cycle_state["status_counts"][hypothesis["status"]] += 1
        updated.append(hypothesis)

    awaiting_review = any(
        item["status"] in CANDIDATE_FOR_REVIEW_STATUSES for item in updated
    )
    active = any(item["status"] in DISCOVERY_ACTIVE_STATUSES for item in updated)

    if awaiting_review:
        cycle_state["phase"] = "review_and_retry" if provider_pending else "review"
        cycle_state["next_actions"] = ["consume-reviewed-evidence"]
    elif active:
        cycle_state["phase"] = "discover"
        cycle_state["next_actions"] = ["discover"]
    else:
        cycle_state["phase"] = "idle"
        cycle_state["next_actions"] = []

    if manual_pending:
        cycle_state["stop_reason"] = "manual_required"
    elif awaiting_review:
        cycle_state["stop_reason"] = "review_pending"
    elif provider_pending:
        cycle_state["stop_reason"] = "provider_pending"
    elif active:
        cycle_state["stop_reason"] = "provider_pending"
    else:
        cycle_state["stop_reason"] = "provider_pending"
    if manual_pending:
        cycle_state["pending_reason"] = "manual_required"
    elif awaiting_review:
        cycle_state["pending_reason"] = (
            "provider_pending" if provider_pending else "review_pending"
        )
    elif provider_pending or active:
        cycle_state["pending_reason"] = "provider_pending"
    else:
        cycle_state["pending_reason"] = "provider_pending"

    if result_values:
        if has_progress:
            cycle_state["consecutive_no_progress_rounds"] = 0
        else:
            cycle_state["consecutive_no_progress_rounds"] = previous_no_progress + 1

    budget_exhausted = result_values and cycle_state["discovery_round"] >= max_rounds
    if budget_exhausted:
        cycle_state["stop_reason"] = "budget_exhausted"
    elif manual_pending:
        cycle_state["stop_reason"] = "manual_required"

    terminal_round = (
        result_values
        and not manual_pending
        and not awaiting_review
        and all(
            item["status"] in SATURATION_TERMINAL_STATUSES
            for item in updated
        )
    )

    if (
        result_values
        and not manual_pending
        and not awaiting_review
        and terminal_round
        and cycle_state["consecutive_no_progress_rounds"] >= 2
        and not budget_exhausted
    ):
        cycle_state["saturation"] = True
        cycle_state["stop_reason"] = "saturated"

    review_request_set: dict[str, Any] | None = None
    if review_requests:
        review_request_set = {
            "schema": LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "network_id": network_ref(network)["network_id"],
            "network_snapshot_sha256": network_ref(network)["sha256"],
            "network_ref": network_ref(network),
            "generated_at": timestamp_now(),
            "source_discovery_set_id": request_set.get("request_set_id"),
            "source_discovery_set_digest": request_set.get("request_set_digest"),
            "requests": review_requests,
        }
        review_request_set["request_set_digest"] = canonical_request_set_digest(
            review_request_set
        )
        review_request_set["request_set_id"] = (
            LEARN_REQUEST_SET_ID_PREFIX + review_request_set["request_set_digest"][:16]
        )
        validate_learn_from_papers_request_set(review_request_set, network=network)
        cycle_state["review_request_set_id"] = review_request_set["request_set_id"]
        cycle_state["review_request_set_digest"] = review_request_set[
            "request_set_digest"
        ]

    output = {
        "schema": HYPOTHESES_SCHEMA,
        "network_ref": network_ref(network),
        "round_id": cycle_state["round_id"],
        "generated_at": timestamp_now(),
        "method_families": hypotheses_doc["method_families"],
        "hypotheses": updated,
        "cycle_state": cycle_state,
    }
    if review_request_set is not None:
        output["review_requests"] = review_request_set
    return output


def consume_reviewed_evidence(
    hypotheses_value: Any,
    network: dict[str, Any],
    review_requests_value: Any,
    evidence_set_value: Any,
    reading_reports_value: Any,
    *,
    round_id: str | None = None,
) -> dict[str, Any]:
    hypotheses_doc = validate_hypotheses(hypotheses_value, network)
    review_requests = validate_learn_from_papers_request_set(
        review_requests_value, network=network
    )
    evidence_set = validate_reviewed_evidence_set(evidence_set_value, network=network)
    reading_report_set = validate_paper_reading_report_set(
        reading_reports_value, network=network
    )
    expected_review_set = hypotheses_doc.get("cycle_state", {}).get("review_request_set_id")
    expected_review_set_digest = hypotheses_doc.get("cycle_state", {}).get(
        "review_request_set_digest"
    )
    expected_evidence_set_digest = hypotheses_doc.get("cycle_state", {}).get(
        "reviewed_evidence_set_digest"
    )
    expected_report_set = hypotheses_doc.get("cycle_state", {}).get(
        "report_set_id"
    )
    expected_report_set_digest = hypotheses_doc.get("cycle_state", {}).get(
        "report_set_digest"
    )
    review_set_id = review_requests["request_set_id"]
    review_set_digest = review_requests["request_set_digest"]
    if evidence_set["request_set_id"] != review_set_id:
        raise ContractError("reviewed evidence set id does not match review request set")
    if evidence_set["request_set_digest"] != review_set_digest:
        raise ContractError(
            "reviewed evidence set digest does not match review request set"
        )
    if expected_review_set and review_set_id != expected_review_set:
        raise ContractError("review request set id does not match cycle review request set")
    if (
        expected_review_set_digest
        and review_set_digest != expected_review_set_digest
    ):
        raise ContractError(
            "review request set digest does not match cycle review request set digest"
        )
    if (
        expected_evidence_set_digest
        and evidence_set["evidence_set_digest"] != expected_evidence_set_digest
    ):
        raise ContractError(
            "reviewed evidence set digest does not match cycle reviewed evidence set digest"
        )
    if expected_report_set and reading_report_set["report_set_id"] != expected_report_set:
        raise ContractError(
            "reading report set id does not match cycle report set"
        )
    if (
        expected_report_set_digest
        and expected_report_set_digest != reading_report_set["report_set_digest"]
    ):
        raise ContractError(
            "reading report set digest does not match cycle report set digest"
        )
    if review_requests["network_id"] != evidence_set["network_id"]:
        raise ContractError(
            "reviewed evidence set network_id does not match review request set"
        )
    if review_requests["network_snapshot_sha256"] != evidence_set["network_snapshot_sha256"]:
        raise ContractError(
            "reviewed evidence set snapshot does not match review request set"
        )
    if review_requests["network_ref"] != evidence_set["network_ref"]:
        raise ContractError(
            "reviewed evidence set network_ref does not match review request set"
        )
    if review_requests["network_id"] != reading_report_set["network_ref"]["network_id"]:
        raise ContractError(
            "reading report set network_id does not match review request set"
        )
    if review_requests["request_set_id"] != reading_report_set["review_request_set_id"]:
        raise ContractError(
            "reading report set review_request_set_id does not match review request set"
        )
    if review_requests["request_set_digest"] != reading_report_set["review_request_set_digest"]:
        raise ContractError(
            "reading report set review_request_set_digest does not match review request set"
        )
    if review_requests["network_snapshot_sha256"] != reading_report_set["network_ref"]["sha256"]:
        raise ContractError(
            "reading report set snapshot does not match review request set"
        )
    if review_requests["network_ref"] != reading_report_set["network_ref"]:
        raise ContractError(
            "reading report set network_ref does not match review request set"
        )

    review_request_lookup = {
        request["request_id"]: request for request in review_requests["requests"]
    }
    review_request_digests = {
        request["request_id"]: sha256_json(request) for request in review_requests["requests"]
    }
    review_request_sources: dict[str, dict[str, dict[str, Any]]] = {}
    for request_id, request in review_request_lookup.items():
        source_map: dict[str, dict[str, Any]] = {}
        for source in request["sources"]:
            source_map[source["source_id"]] = source
        review_request_sources[request_id] = source_map

    reading_report_lookup: dict[str, dict[str, Any]] = {}
    reading_report_passage_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for report in reading_report_set["reports"]:
        report_request_id = report["review_request_id"]
        if report_request_id not in review_request_lookup:
            raise ContractError(
                "reading report set includes report for unknown review request"
            )
        if report["review_request_digest"] != review_request_digests[report_request_id]:
            raise ContractError(
                "reading report set review_request_digest mismatch"
            )
        if report["source_id"] not in review_request_sources[report_request_id]:
            raise ContractError(
                "reading report set source_id does not match selected review source"
            )
        report_source = review_request_sources[report_request_id][report["source_id"]]
        if report["source_digest"] != report_source["source_digest"]:
            raise ContractError(
                "reading report set source_digest does not match selected source"
            )
        if report["source_ref"] != report_source["source_ref"]:
            raise ContractError(
                "reading report set source_ref does not match selected source"
            )
        reading_report_lookup[report["report_id"]] = report
        passages = report.get("evidence_passages")
        if not isinstance(passages, list) or not passages:
            raise ContractError("reading report set passages must be a non-empty list")
        for passage in passages:
            passage_id = passage.get("passage_id")
            if not isinstance(passage_id, str):
                raise ContractError(
                    "reading report set passages must include passage_id"
                )
            reading_report_passage_lookup[(report["report_id"], passage_id)] = passage

    previous_cycle = hypotheses_doc.get("cycle_state", {})
    previous_round = previous_cycle.get("discovery_round", 0)
    if not isinstance(previous_round, int):
        previous_round = 0
    previous_no_progress = previous_cycle.get("consecutive_no_progress_rounds", 0)
    if not isinstance(previous_no_progress, int):
        previous_no_progress = 0
    max_rounds = previous_cycle.get("max_rounds", 1)
    if not isinstance(max_rounds, int):
        max_rounds = 1

    manual_pending = any(
        item["status"] == "awaiting" and item.get("next_action") == "consume-reviewed-evidence"
        for item in hypotheses_doc["hypotheses"]
    )

    hypothesis_by_id = {
        hypothesis["hypothesis_id"]: hypothesis for hypothesis in hypotheses_doc["hypotheses"]
    }

    evidence_by_hypothesis: dict[str, list[dict[str, Any]]] = {}
    for item in evidence_set["evidence"]:
        request_id = item["request_id"]
        review_request = review_request_lookup.get(request_id)
        if review_request is None:
            raise ContractError("reviewed evidence refers to unknown review request")
        if item["review_request_id"] != request_id:
            raise ContractError("reviewed evidence request_id mismatch review_request_id")
        if item["hypothesis_id"] != review_request["hypothesis_id"]:
            raise ContractError("reviewed evidence hypothesis_id does not match review request")
        if item["review_request_digest"] != review_request_digests[item["request_id"]]:
            raise ContractError("reviewed evidence review request digest mismatch")
        reading_report_id = item["reading_report_id"]
        reading_report_digest = item["reading_report_digest"]
        passage_id = item["passage_id"]
        passage_digest = item["passage_digest"]
        report = reading_report_lookup.get(reading_report_id)
        if report is None:
            raise ContractError("reviewed evidence reading_report_id not found in reading report set")
        if report["review_request_id"] != request_id:
            raise ContractError("reviewed evidence reading_report_id mismatch review_request_id")
        if report["review_request_digest"] != item["review_request_digest"]:
            raise ContractError("reviewed evidence reading_report_digest mismatch")
        if report["report_digest"] != reading_report_digest:
            raise ContractError(
                "reviewed evidence reading_report_digest does not match report digest"
            )
        passage = reading_report_passage_lookup.get((reading_report_id, passage_id))
        if passage is None:
            raise ContractError("reviewed evidence passage_id not found in report")
        if passage["passage_digest"] != passage_digest:
            raise ContractError("reviewed evidence passage_digest does not match passage digest")
        source_id = item["source_id"]
        source_digest = item["source_digest"]
        source_lookup = review_request_sources.get(request_id, {})
        source = source_lookup.get(source_id)
        if source is None:
            raise ContractError(
                "reviewed evidence source_id does not match any source in review request"
            )
        if source["source_digest"] != source_digest:
            raise ContractError("reviewed evidence source digest mismatch")
        if item["source_ref"] != source["source_ref"]:
            raise ContractError("reviewed evidence source_ref mismatch")
        if item["exact_locator"] != source["exact_locator"]:
            raise ContractError("reviewed evidence exact_locator mismatch")
        if item["read_depth"] != source["read_depth"]:
            raise ContractError("reviewed evidence read_depth mismatch")
        if item["read_depth"] != source.get("required_read_depth"):
            raise ContractError(
                "reviewed evidence read_depth mismatch required source read depth"
            )
        if item["source_id"] != report.get("source_id"):
            raise ContractError("reviewed evidence source_id does not match reading report")
        if item["source_digest"] != report.get("source_digest"):
            raise ContractError(
                "reviewed evidence source_digest does not match reading report"
            )
        if item.get("review_completed") is not True:
            raise ContractError("reviewed evidence.review_completed must be true")
        if source.get("url") and item.get("url") != source["url"]:
            raise ContractError("reviewed evidence URL mismatch")
        if source.get("doi") and item.get("doi") != source["doi"]:
            raise ContractError("reviewed evidence DOI mismatch")
        if item.get("discovery_only") is not False:
            raise ContractError("reviewed evidence must not be discovery-only")
        if item["hypothesis_id"] not in hypothesis_by_id:
            raise ContractError("reviewed evidence refers to unknown hypothesis")
        evidence_by_hypothesis.setdefault(item["hypothesis_id"], []).append(item)

    updated: list[dict[str, Any]] = []
    has_progress = False
    cycle_state = {
        "schema_version": SCHEMA_VERSION,
        "round_id": round_id or hypotheses_doc.get("round_id", timestamp_now()),
        "generated_at": timestamp_now(),
        "network_snapshot_sha256": network_ref(network)["sha256"],
        "network_id": network_ref(network)["network_id"],
        "discovery_round": previous_round + (1 if evidence_set["evidence"] else 0),
        "results_consumed": 0,
        "awaiting_results": 0,
        "status_counts": {status: 0 for status in sorted(STATUSES)},
        "consecutive_no_progress_rounds": previous_no_progress,
        "max_rounds": max_rounds,
        "phase": "review",
        "next_actions": ["discover"],
        "stop_reason": "in_progress",
        "pending_reason": "provider_pending",
        "saturation": False,
        "review_request_set_id": review_set_id,
        "review_request_set_digest": review_set_digest,
        "reviewed_evidence_set_id": evidence_set["request_set_id"],
        "reviewed_evidence_set_digest": evidence_set["evidence_set_digest"],
        "report_set_id": reading_report_set["report_set_id"],
        "report_set_digest": reading_report_set["report_set_digest"],
        "request_set_id": previous_cycle.get("request_set_id", review_set_id),
        "request_set_digest": previous_cycle.get("request_set_digest", review_set_digest),
    }

    for hypothesis in hypotheses_doc["hypotheses"]:
        hypothesis = json.loads(json.dumps(hypothesis))
        if hypothesis["status"] != "results":
            cycle_state["status_counts"][hypothesis["status"]] += 1
            updated.append(hypothesis)
            continue

        evidence_items = [
            item
            for item in evidence_by_hypothesis.get(hypothesis["hypothesis_id"], [])
            if not item.get("discovery_only")
        ]
        if not evidence_items:
            cycle_state["status_counts"][hypothesis["status"]] += 1
            cycle_state["awaiting_results"] += 1
            hypothesis["next_action"] = "discover"
            updated.append(hypothesis)
            continue

        derived_status, basis_items = _derive_reviewed_hypothesis_status(evidence_items)
        hypothesis["status"] = derived_status

        if hypothesis["status"] in {
            "content_found",
            "supported_gap",
            "contested",
            "refuted",
            "already_covered",
        }:
            if not any(item["outcome"] in {"supports", "contradicts", "already_covered"} for item in evidence_items):
                raise ContractError("reviewed evidence requires decisive outcomes")
        else:
            basis_items = []

        basis: list[dict[str, Any]] = []
        for item in basis_items:
            entry: dict[str, Any] = {
                "hypothesis_id": hypothesis["hypothesis_id"],
                "source_ref": item["source_ref"],
                "locator": item["exact_locator"],
                "read_depth": item["read_depth"],
                "source_id": item["source_id"],
                "source_digest": item["source_digest"],
                "review_request_id": item["review_request_id"],
                "review_request_digest": item["review_request_digest"],
                "claim_support_eligible": item["claim_support_eligible"],
                "reading_report_id": item["reading_report_id"],
                "reading_report_digest": item["reading_report_digest"],
                "passage_id": item["passage_id"],
                "passage_digest": item["passage_digest"],
            }
            if item.get("url"):
                entry["url"] = item["url"]
            if item.get("doi"):
                entry["doi"] = item["doi"]
            if item.get("url") is None and item.get("doi") is None:
                entry["source_ref"] = item["source_ref"]
            evidence_id, evidence_digest = _review_evidence_identity(item)
            entry["evidence_id"] = evidence_id
            entry["evidence_digest"] = evidence_digest
            basis.append(entry)

        if hypothesis["status"] in {
            "content_found",
            "supported_gap",
            "contested",
            "refuted",
            "already_covered",
        }:
            if not basis:
                raise ContractError("reviewed evidence requires status basis entries")
            has_progress = True
            cycle_state["results_consumed"] += 1
        else:
            cycle_state["awaiting_results"] += 1

        hypothesis["status_basis"] = basis
        hypothesis["next_action"] = "discover"
        cycle_state["status_counts"][hypothesis["status"]] += 1
        updated.append(hypothesis)

    active = any(item["status"] in DISCOVERY_ACTIVE_STATUSES for item in updated)
    awaiting_review = any(item["status"] in CANDIDATE_FOR_REVIEW_STATUSES for item in updated)

    if awaiting_review:
        cycle_state["phase"] = "review"
        cycle_state["next_actions"] = ["consume-reviewed-evidence"]
        cycle_state["stop_reason"] = "review_pending"
        cycle_state["pending_reason"] = "review_pending"
    elif active:
        cycle_state["phase"] = "discover"
        cycle_state["next_actions"] = ["discover"]
        cycle_state["stop_reason"] = "provider_pending"
        cycle_state["pending_reason"] = "provider_pending"
    else:
        cycle_state["phase"] = "idle"
        cycle_state["next_actions"] = []
        cycle_state["stop_reason"] = "provider_pending"
        cycle_state["pending_reason"] = "provider_pending"

    if manual_pending:
        cycle_state["stop_reason"] = "manual_required"
        cycle_state["pending_reason"] = "manual_required"

    if evidence_set["evidence"]:
        if has_progress:
            cycle_state["consecutive_no_progress_rounds"] = 0
        else:
            cycle_state["consecutive_no_progress_rounds"] = previous_no_progress + 1

    terminal_round = (
        evidence_set["evidence"]
        and not manual_pending
        and not awaiting_review
        and all(
            item["status"] in SATURATION_TERMINAL_STATUSES for item in updated
        )
    )

    if (
        terminal_round
        and cycle_state["consecutive_no_progress_rounds"] >= 2
        and not any(
            item["status"] in SATURATION_BLOCKING_STATUSES for item in updated
        )
    ):
        cycle_state["saturation"] = True
        cycle_state["stop_reason"] = "saturated"

    if evidence_set["evidence"] and cycle_state["discovery_round"] >= max_rounds:
        cycle_state["stop_reason"] = "budget_exhausted"

    return {
        "schema": HYPOTHESES_SCHEMA,
        "network_ref": network_ref(network),
        "round_id": cycle_state["round_id"],
        "generated_at": timestamp_now(),
        "method_families": hypotheses_doc["method_families"],
        "hypotheses": updated,
        "cycle_state": cycle_state,
    }



def propose_patch(
    document: Any,
    network: dict[str, Any],
    reviewed_evidence_set_value: Any,
    review_requests_value: Any,
    reading_reports_value: Any,
) -> dict[str, Any]:
    document = validate_hypotheses(document, network)
    review_requests = validate_learn_from_papers_request_set(
        review_requests_value, network=network
    )
    reviewed_evidence_set = validate_reviewed_evidence_set(
        reviewed_evidence_set_value, network=network
    )
    reading_report_set = validate_paper_reading_report_set(
        reading_reports_value, network=network
    )

    review_set_id = review_requests["request_set_id"]
    review_set_digest = review_requests["request_set_digest"]
    if reviewed_evidence_set["request_set_id"] != review_set_id:
        raise ContractError("reviewed evidence set id does not match review request set")
    if reviewed_evidence_set["request_set_digest"] != review_set_digest:
        raise ContractError(
            "reviewed evidence set digest does not match review request set"
        )
    if review_requests["network_id"] != reviewed_evidence_set["network_id"]:
        raise ContractError(
            "reviewed evidence set network_id does not match review request set"
        )
    if review_requests["network_snapshot_sha256"] != reviewed_evidence_set[
        "network_snapshot_sha256"
    ]:
        raise ContractError(
            "reviewed evidence set network_ref and snapshot do not match review request set"
        )
    if review_requests["network_ref"] != reviewed_evidence_set["network_ref"]:
        raise ContractError(
            "reviewed evidence set network_ref does not match review request set"
        )

    cycle_state = require_dict(document.get("cycle_state"), "hypotheses.cycle_state")
    expected_review_set = require_string(
        cycle_state.get("review_request_set_id"),
        "hypotheses.cycle_state.review_request_set_id",
    )
    expected_review_set_digest = require_string(
        cycle_state.get("review_request_set_digest"),
        "hypotheses.cycle_state.review_request_set_digest",
    )
    expected_evidence_set_id = require_string(
        cycle_state.get("reviewed_evidence_set_id"),
        "hypotheses.cycle_state.reviewed_evidence_set_id",
    )
    expected_evidence_set_digest = require_string(
        cycle_state.get("reviewed_evidence_set_digest"),
        "hypotheses.cycle_state.reviewed_evidence_set_digest",
    )
    expected_report_set_id = require_string(
        cycle_state.get("report_set_id"),
        "hypotheses.cycle_state.report_set_id",
    )
    expected_report_set_digest = require_string(
        cycle_state.get("report_set_digest"),
        "hypotheses.cycle_state.report_set_digest",
    )
    accepted = [
        hypothesis
        for hypothesis in document["hypotheses"]
        if hypothesis["status"] in {"content_found", "supported_gap"}
    ]
    if review_set_id != expected_review_set:
        raise ContractError("review request set id does not match cycle review request set")
    if review_set_digest != expected_review_set_digest:
        raise ContractError(
            "review request set digest does not match cycle review request set digest"
        )
    if reviewed_evidence_set["request_set_id"] != expected_evidence_set_id:
        raise ContractError(
            "reviewed evidence set id does not match cycle reviewed evidence set id"
        )
    if reviewed_evidence_set["evidence_set_digest"] != expected_evidence_set_digest:
        raise ContractError(
            "reviewed evidence set digest does not match cycle reviewed evidence set digest"
        )
    if reading_report_set["report_set_id"] != expected_report_set_id:
        raise ContractError(
            "reading report set id does not match cycle reading report set id"
        )
    if reading_report_set["report_set_digest"] != expected_report_set_digest:
        raise ContractError(
            "reading report set digest does not match cycle reading report set digest"
        )
    if review_requests["request_set_id"] != reading_report_set["review_request_set_id"]:
        raise ContractError(
            "reading report set review_request_set_id does not match review request set"
        )
    if review_requests["request_set_digest"] != reading_report_set["review_request_set_digest"]:
        raise ContractError(
            "reading report set review_request_set_digest does not match review request set"
        )
    if review_requests["network_id"] != reading_report_set["network_ref"]["network_id"]:
        raise ContractError("reading report set network_id does not match review request set")
    if review_requests["network_snapshot_sha256"] != reading_report_set["network_ref"]["sha256"]:
        raise ContractError(
            "reading report set network_ref and snapshot do not match review request set"
        )
    if review_requests["network_ref"] != reading_report_set["network_ref"]:
        raise ContractError("reading report set network_ref does not match review request set")

    review_request_lookup = {
        request["request_id"]: request for request in review_requests["requests"]
    }
    review_request_digests = {
        request["request_id"]: sha256_json(request) for request in review_requests["requests"]
    }
    review_request_sources: dict[str, dict[str, dict[str, Any]]] = {}
    for request in review_requests["requests"]:
        source_map: dict[str, dict[str, Any]] = {}
        for source in request["sources"]:
            source_map[source["source_id"]] = source
        review_request_sources[request["request_id"]] = source_map

    reading_report_lookup: dict[str, dict[str, Any]] = {}
    reading_report_passage_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for report in reading_report_set["reports"]:
        reading_report_lookup[report["report_id"]] = report
        passages = report.get("evidence_passages")
        if not isinstance(passages, list) or not passages:
            raise ContractError("reading report passages must be a non-empty list")
        for passage in passages:
            passage_id = passage.get("passage_id")
            if not isinstance(passage_id, str) or not passage_id:
                raise ContractError("reading report passage_id must be present")
            reading_report_passage_lookup[(report["report_id"], passage_id)] = passage

    reviewed_evidence_by_hypothesis: dict[str, list[dict[str, Any]]] = {}
    for item in reviewed_evidence_set["evidence"]:
        reviewed_evidence_by_hypothesis.setdefault(item["hypothesis_id"], []).append(
            item
        )

    reviewed_evidence_lookup: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for item in reviewed_evidence_set["evidence"]:
        reviewed_evidence_lookup[(
            item["request_id"],
            item["source_id"],
            item["source_digest"],
            item["reading_report_id"],
            item["passage_id"],
        )] = item

    basis_gap_ids = [hypothesis["hypothesis_id"] for hypothesis in accepted]

    nodes = []
    relations = []
    evidence = []

    for hypothesis in accepted:
        basis = hypothesis["status_basis"]
        if not basis:
            raise ContractError(
                "proposal basis required for accepted hypothesis statuses"
            )
        evidence_items = [
            item
            for item in reviewed_evidence_by_hypothesis.get(
                hypothesis["hypothesis_id"], []
            )
            if not item.get("discovery_only")
        ]
        derived_status, _ = _derive_reviewed_hypothesis_status(evidence_items)
        if hypothesis["status"] != derived_status:
            raise ContractError(
                "proposed patch hypothesis status must match reviewed-evidence-derived status"
            )
        validated_basis: list[dict[str, Any]] = []
        for index, entry in enumerate(basis):
            basis_entry = require_dict(entry, f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}]")
            require_string(
                basis_entry.get("hypothesis_id"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].hypothesis_id",
            )
            if basis_entry["hypothesis_id"] != hypothesis["hypothesis_id"]:
                raise ContractError(
                    "status basis hypothesis_id does not match accepted hypothesis"
                )
            require_string(
                basis_entry.get("review_request_id"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].review_request_id",
            )
            review_request_id = basis_entry["review_request_id"]
            if review_request_id not in review_request_lookup:
                raise ContractError(
                    "proposed patch review_request_id does not exist in review requests"
                )
            request = review_request_lookup[review_request_id]
            if request["hypothesis_id"] != hypothesis["hypothesis_id"]:
                raise ContractError(
                    "proposed patch review request does not match hypothesis"
                )
            if basis_entry.get("review_request_digest") != review_request_digests[review_request_id]:
                raise ContractError("proposed patch review request digest mismatch")
            if basis_entry.get("claim_support_eligible") is not True:
                raise ContractError(
                    "proposed patch status basis claim_support_eligible must be true"
                )
            reading_report_id = require_string(
                basis_entry.get("reading_report_id"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].reading_report_id",
            )
            if not reading_report_id.startswith(READING_REPORT_ID_PREFIX):
                raise ContractError(
                    "hypothesis status_basis reading_report_id must start with reading-report-"
                )
            reading_report_digest = require_string(
                basis_entry.get("reading_report_digest"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].reading_report_digest",
            )
            ensure_sha256(
                reading_report_digest,
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].reading_report_digest",
            )
            passage_id = require_string(
                basis_entry.get("passage_id"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].passage_id",
            )
            if not passage_id.startswith(PASSAGE_ID_PREFIX):
                raise ContractError(
                    "hypothesis status_basis passage_id must start with passage-"
                )
            passage_digest = require_string(
                basis_entry.get("passage_digest"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].passage_digest",
            )
            ensure_sha256(
                passage_digest,
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].passage_digest",
            )
            source_id = require_string(
                basis_entry.get("source_id"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].source_id",
            )
            source_digest = require_string(
                basis_entry.get("source_digest"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].source_digest",
            )
            ensure_sha256(
                source_digest,
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].source_digest",
            )
            report = reading_report_lookup.get(reading_report_id)
            if report is None:
                raise ContractError(
                    "proposed patch reading_report_id does not exist in reading report set"
                )
            if report["review_request_id"] != review_request_id:
                raise ContractError(
                    "proposed patch reading report does not match review request"
                )
            if report["review_request_digest"] != basis_entry["review_request_digest"]:
                raise ContractError(
                    "proposed patch reading report request digest mismatch"
                )
            if report["source_id"] != source_id:
                raise ContractError("proposed patch reading report source_id mismatch")
            if report["source_digest"] != source_digest:
                raise ContractError(
                    "proposed patch reading report source digest mismatch"
                )
            if report["report_digest"] != reading_report_digest:
                raise ContractError(
                    "proposed patch reading_report_digest does not match reading report"
                )
            passage = reading_report_passage_lookup.get((reading_report_id, passage_id))
            if passage is None:
                raise ContractError(
                    "proposed patch passage_id does not exist in referenced report"
                )
            if passage["passage_digest"] != passage_digest:
                raise ContractError(
                    "proposed patch passage_digest does not match passage"
                )
            evidence_id = require_string(
                basis_entry.get("evidence_id"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].evidence_id",
            )
            evidence_digest = require_string(
                basis_entry.get("evidence_digest"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].evidence_digest",
            )
            ensure_sha256(
                evidence_digest,
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].evidence_digest",
            )
            request = review_request_lookup[review_request_id]
            request_source = review_request_sources.get(review_request_id, {}).get(source_id)
            if request_source is None:
                raise ContractError(
                    "proposed patch status basis source_id does not exist in review request"
                )
            if request_source["source_digest"] != source_digest:
                raise ContractError(
                    "proposed patch status basis source digest mismatch"
                )
            if basis_entry.get("source_ref") != request_source["source_ref"]:
                raise ContractError(
                    "proposed patch status basis source_ref mismatch"
                )
            if basis_entry.get("locator") != request_source["exact_locator"]:
                raise ContractError(
                    "proposed patch status basis locator mismatch"
                )
            if (
                request_source.get("url") is not None
                and basis_entry.get("url") != request_source["url"]
            ):
                raise ContractError("proposed patch status basis URL mismatch")
            if (
                request_source.get("doi") is not None
                and basis_entry.get("doi") != request_source["doi"]
            ):
                raise ContractError("proposed patch status basis DOI mismatch")

            evidence_key = (
                review_request_id,
                source_id,
                source_digest,
                reading_report_id,
                passage_id,
            )
            basis_evidence = reviewed_evidence_lookup.get(evidence_key)
            if basis_evidence is None:
                raise ContractError(
                    "proposed patch basis must match non-discovery-only reviewed evidence"
                )
            basis_evidence_id, basis_evidence_digest = _review_evidence_identity(
                basis_evidence
            )
            if basis_evidence["review_request_id"] != review_request_id:
                raise ContractError(
                    "proposed patch basis evidence review_request_id mismatch"
                )
            if basis_evidence["request_id"] != review_request_id:
                raise ContractError(
                    "proposed patch basis evidence request_id mismatch"
                )
            if evidence_id != basis_evidence_id:
                raise ContractError(
                    "proposed patch basis evidence_id does not match evidence record"
                )
            if evidence_digest != basis_evidence_digest:
                raise ContractError(
                    "proposed patch basis evidence_digest does not match evidence record"
                )
            if basis_evidence["hypothesis_id"] != hypothesis["hypothesis_id"]:
                raise ContractError("proposed patch basis hypothesis mismatch with evidence")
            if basis_evidence["outcome"] != "supports":
                raise ContractError(
                    "proposed patch accepted hypotheses must be based on supports evidence"
                )
            if basis_evidence["claim_support_eligible"] is not True:
                raise ContractError(
                    "proposed patch evidence must come from claim-support-eligible review"
                )
            if basis_evidence.get("review_completed") is not True:
                raise ContractError(
                    "proposed patch basis evidence review_completed must be true"
                )
            require_string(
                basis_entry.get("source_ref"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].source_ref",
            )
            require_string(
                basis_entry.get("locator"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].locator",
            )
            read_depth = require_string(
                basis_entry.get("read_depth"),
                f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].read_depth",
            )
            if read_depth not in READ_DEPTHS:
                raise ContractError(
                    f"hypothesis {hypothesis['hypothesis_id']} status_basis[{index}].read_depth invalid"
                )
            if read_depth != request_source.get("required_read_depth"):
                raise ContractError(
                    "proposed patch status basis read_depth mismatch required source read depth"
                )
            if read_depth != basis_evidence["read_depth"]:
                raise ContractError(
                    "proposed patch status basis read depth does not match evidence"
                )
            if reading_report_digest != basis_evidence["reading_report_digest"]:
                raise ContractError(
                    "proposed patch status basis reading report digest mismatch"
                )
            if passage_digest != basis_evidence["passage_digest"]:
                raise ContractError(
                    "proposed patch status basis passage digest mismatch"
                )

            validated_basis.append(
                {
                    "source_ref": basis_entry["source_ref"],
                    "source_id": source_id,
                    "source_digest": source_digest,
                    "locator": basis_entry["locator"],
                    "read_depth": basis_entry["read_depth"],
                    "review_request_id": review_request_id,
                    "review_request_digest": basis_entry["review_request_digest"],
                    "claim_support_eligible": basis_entry["claim_support_eligible"],
                    "evidence_id": basis_entry["evidence_id"],
                    "evidence_digest": basis_entry["evidence_digest"],
                    "reading_report_id": reading_report_id,
                    "reading_report_digest": reading_report_digest,
                    "passage_id": passage_id,
                    "passage_digest": passage_digest,
                }
            )

        if not validated_basis:
            raise ContractError(
                "proposal requires at least one validated reviewed evidence entry"
            )
        provenance = [
            {
                "source_ref": entry["source_ref"],
                "locator": entry["locator"],
                "read_depth": entry["read_depth"],
            }
            for entry in validated_basis
        ]
        row = {
            "hypothesis_id": hypothesis["hypothesis_id"],
            "status": hypothesis["status"],
            "target_signature": hypothesis["target_signature"],
            "hypothesis": hypothesis["hypothesis"],
            "provenance": provenance,
        }
        if hypothesis["target_kind"] == "node":
            nodes.append(row)
        elif hypothesis["target_kind"] == "relation":
            relations.append(row)
        else:
            evidence.append(row)

    patch = {
        "schema": PATCH_SCHEMA,
        "proposal_id": "NPP-" + sha256_json(
            {
                "network": network_ref(network),
                "basis": basis_gap_ids,
                "status": "supported",
            }
        )[:12],
        "network_ref": network_ref(network),
        "generated_at": timestamp_now(),
        "basis_gap_ids": basis_gap_ids,
        "proposal_only": True,
        "novelty_claimed": False,
        "nodes": nodes,
        "relations": relations,
        "evidence": evidence,
        "review_gate": "pending_research_knowledge_network_validation",
    }
    return validate_patch(patch, network)


def validate_patch(
    value: Any, network: dict[str, Any] | None = None
) -> dict[str, Any]:
    patch = require_dict(value, "patch")
    if patch.get("schema") != PATCH_SCHEMA:
        raise ContractError(f"patch.schema must equal {PATCH_SCHEMA}")
    require_string(patch.get("proposal_id"), "patch.proposal_id")
    if network is not None:
        validate_network_ref(patch.get("network_ref"), "patch.network_ref", network)
    require_timestamp(patch.get("generated_at"), "patch.generated_at")
    require_string_list(patch.get("basis_gap_ids"), "patch.basis_gap_ids", True)
    if patch.get("proposal_only") is not True:
        raise ContractError("patch.proposal_only must be true")
    if patch.get("novelty_claimed") is not False:
        raise ContractError("patch.novelty_claimed must be false")
    if patch.get("review_gate") != "pending_research_knowledge_network_validation":
        raise ContractError("patch.review_gate must remain pending")
    for forbidden in ("apply", "auto_merge", "write_authorized"):
        if patch.get(forbidden):
            raise ContractError(f"patch must not authorize {forbidden}")
    for collection in ("nodes", "relations", "evidence"):
        rows = patch.get(collection)
        if not isinstance(rows, list):
            raise ContractError(f"patch.{collection} must be a list")
        for index, row in enumerate(rows):
            item = require_dict(row, f"patch.{collection}[{index}]")
            provenance = item.get("provenance")
            if not isinstance(provenance, list) or not provenance:
                raise ContractError(f"patch.{collection}[{index}].provenance is required")
            for source in provenance:
                entry = require_dict(source, "patch provenance")
                require_string(entry.get("source_ref"), "patch provenance source_ref")
                require_string(entry.get("locator"), "patch provenance locator")
                if "source_id" in entry:
                    require_string(
                        entry.get("source_id"), "patch provenance source_id"
                    )
                if "source_digest" in entry:
                    ensure_sha256(
                        entry.get("source_digest"), "patch provenance source_digest"
                    )
                read_depth = require_string(
                    entry.get("read_depth"), "patch provenance read_depth"
                )
                if read_depth not in READ_DEPTHS:
                    raise ContractError("patch provenance needs full_text or evidence depth")
    return patch


def validate_any(value: Any, network: dict[str, Any] | None = None) -> dict[str, Any]:
    schema = value.get("schema") if isinstance(value, dict) else None
    if schema == NETWORK_SCHEMA:
        return validate_network(value)
    if schema == PROBE_SCHEMA:
        return validate_probe(value)
    if schema == HYPOTHESES_SCHEMA:
        return validate_hypotheses(value, network)
    if schema == PATCH_SCHEMA:
        return validate_patch(value, network)
    if schema == REQUEST_SET_SCHEMA:
        return validate_request_set(value, network=network)
    if schema == REQUEST_SCHEMA:
        return validate_scholar_discovery_request(value)
    if schema == RESULT_SCHEMA:
        return validate_scholar_discovery_result(value)
    if schema == RESULT_SET_SCHEMA:
        return validate_scholar_discovery_result_set(value, network=network)
    if schema == LEARN_FROM_PAPERS_REQUEST_SCHEMA:
        return validate_learn_from_papers_request(value)
    if schema == LEARN_FROM_PAPERS_REQUEST_SET_SCHEMA:
        return validate_learn_from_papers_request_set(value, network=network)
    if schema == REVIEWED_EVIDENCE_SCHEMA:
        return validate_reviewed_evidence(value)
    if schema == REVIEWED_EVIDENCE_SET_SCHEMA:
        return validate_reviewed_evidence_set(value, network=network)
    if schema == PAPER_READING_REPORT_SCHEMA:
        return validate_paper_reading_report(value, network=network)
    if schema == PAPER_READING_REPORT_SET_SCHEMA:
        return validate_paper_reading_report_set(value, network=network)
    raise ContractError(f"unsupported schema: {schema!r}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    scan = subcommands.add_parser("scan", help="scan a KnowledgeNetwork/v1")
    scan.add_argument("--network", required=True)
    scan.add_argument("--output", required=True)

    generate = subcommands.add_parser(
        "generate-hypotheses", help="emit deterministic gap hypotheses from network scan"
    )
    generate.add_argument("--network", required=True)
    generate.add_argument("--round-id")
    generate.add_argument("--output", required=True)

    rank = subcommands.add_parser("prioritize", help="rank gap hypotheses")
    rank.add_argument("--input", required=True)
    rank.add_argument("--network")
    rank.add_argument("--output", required=True)

    emit = subcommands.add_parser(
        "emit-search-requests", help="emit scholar-discovery requests"
    )
    emit.add_argument("--input", required=True)
    emit.add_argument("--network", required=True)
    emit.add_argument("--output", required=True)
    emit.add_argument(
        "--google-scholar-policy",
        choices=["manual_optional", "manual_required", "disabled"],
        default="manual_optional",
    )

    consume = subcommands.add_parser(
        "consume-results", help="consume result set and transition hypothesis status"
    )
    consume.add_argument("--hypotheses", required=True)
    consume.add_argument("--network", required=True)
    consume.add_argument("--requests", required=True)
    consume.add_argument("--result", action="append", default=[], required=True)
    consume.add_argument("--output", required=True)
    consume.add_argument("--round-id")

    consume_review = subcommands.add_parser(
        "consume-reviewed-evidence", help="consume reviewed evidence and transition hypothesis status"
    )
    consume_review.add_argument("--hypotheses", required=True)
    consume_review.add_argument("--network", required=True)
    consume_review.add_argument("--review-requests", required=True)
    consume_review.add_argument("--evidence", required=True)
    consume_review.add_argument("--reading-reports", required=True)
    consume_review.add_argument("--output", required=True)
    consume_review.add_argument("--round-id")

    propose = subcommands.add_parser(
        "propose-patch", help="emit proposal-only NetworkPatchProposal/v1"
    )
    propose.add_argument("--input", required=True)
    propose.add_argument("--network", required=True)
    propose.add_argument("--reviewed-evidence-set", required=True)
    propose.add_argument("--review-requests", required=True)
    propose.add_argument("--reading-reports", required=True)
    propose.add_argument("--output", required=True)

    validate = subcommands.add_parser("validate", help="validate one contract")
    validate.add_argument("--input", required=True)
    validate.add_argument("--network")

    cycle = subcommands.add_parser("cycle", help="run bounded discovery cycle")
    cycle.add_argument("--network", required=True)
    cycle.add_argument("--hypotheses-output", required=True)
    cycle.add_argument("--requests-output", required=True)
    cycle.add_argument(
        "--google-scholar-policy",
        choices=["manual_optional", "manual_required", "disabled"],
        default="manual_optional",
    )

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "scan":
            write_json(args.output, scan_network(load_json(args.network)))

        elif args.command == "generate-hypotheses":
            network = load_json(args.network)
            validate_network(network)
            probe = scan_network(network)
            write_json(
                args.output,
                generate_hypotheses_from_probe(
                    probe,
                    network,
                    round_id=args.round_id,
                ),
            )

        elif args.command == "prioritize":
            network = load_json(args.network) if args.network else None
            write_json(args.output, prioritize(load_json(args.input), network))

        elif args.command == "emit-search-requests":
            network = load_json(args.network)
            validate_network(network)
            write_json(
                args.output,
                emit_search_requests(
                    load_json(args.input),
                    network,
                    google_scholar_policy=args.google_scholar_policy,
                ),
            )

        elif args.command == "consume-results":
            network = load_json(args.network)
            validate_network(network)
            hypotheses = load_json(args.hypotheses)
            request_set = load_json(args.requests)
            result_inputs = [load_json(path) for path in args.result]
            output = consume_results(
                hypotheses,
                network,
                request_set,
                result_inputs,
                round_id=args.round_id,
            )
            write_json(args.output, output)

        elif args.command == "consume-reviewed-evidence":
            network = load_json(args.network)
            validate_network(network)
            output = consume_reviewed_evidence(
                load_json(args.hypotheses),
                network,
                load_json(args.review_requests),
                load_json(args.evidence),
                load_json(args.reading_reports),
                round_id=args.round_id,
            )
            write_json(args.output, output)

        elif args.command == "propose-patch":
            network = load_json(args.network)
            validate_network(network)
            write_json(
                args.output,
                propose_patch(
                    load_json(args.input),
                    network,
                    load_json(args.reviewed_evidence_set),
                    load_json(args.review_requests),
                    load_json(args.reading_reports),
                ),
            )

        elif args.command == "cycle":
            network = load_json(args.network)
            validate_network(network)
            probe = scan_network(network)
            hypotheses = generate_hypotheses_from_probe(probe, network)
            prioritized = prioritize(hypotheses, network)
            request_set = emit_search_requests(
                prioritized,
                network,
                google_scholar_policy=args.google_scholar_policy,
            )
            write_json(args.hypotheses_output, prioritized)
            write_json(args.requests_output, request_set)

        else:
            network = load_json(args.network) if args.network else None
            output = validate_any(load_json(args.input), network)
            print(json.dumps({"valid": True, "schema": output["schema"]}, sort_keys=True))
        return 0

    except (ContractError, json.JSONDecodeError, OSError, ValueError, TypeError, re.error) as exc:
        print(f"network-gap-discovery validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
