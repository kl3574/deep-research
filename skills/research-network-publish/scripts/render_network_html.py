#!/usr/bin/env python3
"""Validate and render research-network exports as deterministic HTML."""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence


RENDERER_VERSION = "research-network-publish/1"
PUBLIC_MODE = "public-redacted"
PRIVATE_MODE = "private"
MODES = (PUBLIC_MODE, PRIVATE_MODE)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_DIGEST_RE = re.compile(r"\b[0-9a-fA-F]{32,128}\b")
_PUBLIC_POSIX_PATH_RE = re.compile(
    r"(?<![:/A-Za-z0-9])/(?:[^/\s<>\"']+/)+[^/\s<>\"']+"
)
_PUBLIC_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s<>\"']+\\)+[^\\\s<>\"']+")
_PUBLIC_ZOTERO_URI_RE = re.compile(r"\bzotero:(?://)?\S+", re.IGNORECASE)
_PUBLIC_ITEM_CONTEXT_RE = re.compile(
    r"\b(?:zotero\s+)?(?:item(?:\s+key)?|key)\s*[:=#/]\s*[A-Z0-9]{8}\b",
    re.IGNORECASE,
)
_PUBLIC_ITEM_KEY_RE = re.compile(r"\b[A-Z0-9]{8}\b")
_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)"
        r"\s*[:=]\s*[^\s,;]{6,}",
        re.IGNORECASE,
    ),
)
_CREDENTIAL_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "authorization",
    "cookie",
    "privatekey",
    "credential",
    "accesskey",
)


class ContractError(ValueError):
    """Raised when an input or publication contract is violated."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_file(path_value: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(path_value)
    if path.is_symlink():
        raise ContractError(f"input must not be a symlink: {path}")
    if not path.is_file():
        raise ContractError(f"input is not an ordinary file: {path}")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicates,
        )
    except UnicodeDecodeError as exc:
        raise ContractError(f"input is not UTF-8 JSON: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"top-level JSON value must be an object: {path}")
    return payload


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    unsigned = copy.deepcopy(dict(payload))
    unsigned.pop("content_sha256", None)
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_digest(payload: Mapping[str, Any], label: str) -> None:
    supplied = payload.get("content_sha256")
    if not isinstance(supplied, str) or not _DIGEST_RE.fullmatch(supplied):
        raise ContractError(f"{label}.content_sha256 must be 64 lowercase hex characters")
    actual = hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()
    if supplied != actual:
        raise ContractError(f"{label}.content_sha256 does not match canonical content")


def _require_text(record: Mapping[str, Any], key: str, label: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label}.{key} must be a non-empty string")
    return value


def _require_list(record: Mapping[str, Any], key: str, label: str) -> list[Any]:
    value = record.get(key)
    if not isinstance(value, list):
        raise ContractError(f"{label}.{key} must be an array")
    return value


def _validate_unique_records(
    rows: Sequence[Any], id_key: str, label: str, required_keys: Sequence[str]
) -> set[str]:
    seen: set[str] = set()
    for index, row in enumerate(rows):
        row_label = f"{label}[{index}]"
        if not isinstance(row, dict):
            raise ContractError(f"{row_label} must be an object")
        identifier = _require_text(row, id_key, row_label)
        if identifier in seen:
            raise ContractError(f"duplicate {label} identifier: {identifier}")
        seen.add(identifier)
        for key in required_keys:
            _require_text(row, key, row_label)
    return seen


def _credential_key(key: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(part in compact for part in _CREDENTIAL_KEY_PARTS)


def _scan_credentials(value: Any, location: str = "input") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _credential_key(str(key)):
                raise ContractError(f"credential-shaped key is forbidden at {location}.{key}")
            _scan_credentials(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_credentials(child, f"{location}[{index}]")
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in _CREDENTIAL_VALUE_PATTERNS):
            raise ContractError(f"credential-shaped value is forbidden at {location}")


def validate_network(network: Mapping[str, Any]) -> None:
    if network.get("schema") != "KnowledgeNetwork/v1":
        raise ContractError("network.schema must equal KnowledgeNetwork/v1")
    _require_text(network, "network_id", "network")
    _require_text(network, "snapshot_id", "network")
    nodes = _require_list(network, "nodes", "network")
    relations = _require_list(network, "relations", "network")
    gaps = _require_list(network, "gaps", "network")
    node_ids = _validate_unique_records(nodes, "node_id", "nodes", ("kind", "label"))
    _validate_unique_records(
        relations,
        "relation_id",
        "relations",
        ("from_id", "to_id", "predicate"),
    )
    _validate_unique_records(gaps, "gap_id", "gaps", ("reason", "status"))
    for index, relation in enumerate(relations):
        assert isinstance(relation, dict)
        for endpoint in ("from_id", "to_id"):
            if relation[endpoint] not in node_ids:
                raise ContractError(
                    f"relations[{index}].{endpoint} references unknown node {relation[endpoint]}"
                )
        provenance = relation.get("provenance", [])
        if not isinstance(provenance, list):
            raise ContractError(f"relations[{index}].provenance must be an array")
        for p_index, record in enumerate(provenance):
            if not isinstance(record, dict):
                raise ContractError(
                    f"relations[{index}].provenance[{p_index}] must be an object"
                )
    completion = network.get("completion")
    if not isinstance(completion, dict):
        raise ContractError("network.completion must be an object")
    _require_text(completion, "status", "network.completion")
    open_gap_ids = completion.get("open_gap_ids", [])
    if not isinstance(open_gap_ids, list) or not all(isinstance(item, str) for item in open_gap_ids):
        raise ContractError("network.completion.open_gap_ids must be an array of strings")
    sources = network.get("sources", [])
    if not isinstance(sources, list):
        raise ContractError("network.sources must be an array when present")
    if sources:
        _validate_unique_records(sources, "source_id", "sources", ())
    _validate_digest(network, "network")
    _scan_credentials(network, "network")


def _validate_reference_list(
    row: Mapping[str, Any], key: str, allowed: set[str], label: str
) -> None:
    refs = row.get(key, [])
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise ContractError(f"{label}.{key} must be an array of strings")
    unknown = sorted(set(refs) - allowed)
    if unknown:
        raise ContractError(f"{label}.{key} references unknown IDs: {', '.join(unknown)}")


def validate_research_map(research_map: Mapping[str, Any], network: Mapping[str, Any]) -> None:
    if research_map.get("schema") != "ResearchMap/v1":
        raise ContractError("research_map.schema must equal ResearchMap/v1")
    _require_text(research_map, "title", "research_map")
    snapshot_id = _require_text(research_map, "network_snapshot_id", "research_map")
    if snapshot_id != network["snapshot_id"]:
        raise ContractError("research_map.network_snapshot_id does not match network.snapshot_id")
    node_ids = {str(row["node_id"]) for row in network["nodes"]}
    relation_ids = {str(row["relation_id"]) for row in network["relations"]}
    gap_ids = {str(row["gap_id"]) for row in network["gaps"]}
    source_ids = {str(row["source_id"]) for row in network.get("sources", [])}
    evidence_ids = node_ids | relation_ids | gap_ids | source_ids
    specs = (
        ("field_map", "field_id", ("label",)),
        ("competency_questions", "question_id", ("question", "status")),
        ("routes", "route_id", ("label",)),
        ("recommendations", "recommendation_id", ("title",)),
    )
    arrays: dict[str, list[Any]] = {}
    for array_key, id_key, required in specs:
        rows = _require_list(research_map, array_key, "research_map")
        _validate_unique_records(rows, id_key, f"research_map.{array_key}", required)
        arrays[array_key] = rows
    for index, row in enumerate(arrays["field_map"]):
        _validate_reference_list(row, "node_ids", node_ids, f"field_map[{index}]")
    for index, row in enumerate(arrays["competency_questions"]):
        _validate_reference_list(
            row, "relation_ids", relation_ids, f"competency_questions[{index}]"
        )
        _validate_reference_list(row, "gap_ids", gap_ids, f"competency_questions[{index}]")
    for index, row in enumerate(arrays["routes"]):
        _validate_reference_list(row, "relation_ids", relation_ids, f"routes[{index}]")
    for index, row in enumerate(arrays["recommendations"]):
        _validate_reference_list(
            row, "evidence_refs", evidence_ids, f"recommendations[{index}]"
        )
    _validate_digest(research_map, "research_map")
    _scan_credentials(research_map, "research_map")


def validate_inputs(
    network: Mapping[str, Any], research_map: Mapping[str, Any] | None = None
) -> None:
    validate_network(network)
    if research_map is not None:
        validate_research_map(research_map, network)


def _redact_public_text(value: Any) -> str:
    text = str(value) if value is not None else ""
    text = _PUBLIC_ZOTERO_URI_RE.sub("[redacted Zotero reference]", text)
    text = _PUBLIC_ITEM_CONTEXT_RE.sub("[redacted Zotero item]", text)
    text = _PUBLIC_POSIX_PATH_RE.sub("[redacted path]", text)
    text = _PUBLIC_WINDOWS_PATH_RE.sub("[redacted path]", text)
    text = _PUBLIC_DIGEST_RE.sub("[redacted digest]", text)
    text = _PUBLIC_ITEM_KEY_RE.sub("[redacted item key]", text)
    return text


def _text(value: Any, mode: str) -> str:
    raw = str(value) if value is not None else ""
    return _redact_public_text(raw) if mode == PUBLIC_MODE else raw


def _display_value(value: Any, mode: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return _text(value, mode)
    if isinstance(value, list):
        return ", ".join(part for part in (_display_value(item, mode) for item in value) if part)
    if isinstance(value, dict):
        if "name" in value:
            return _display_value(value["name"], mode)
        names = [value.get("given"), value.get("family")]
        return " ".join(_text(item, mode) for item in names if item)
    return ""


def _ordinal_map(values: Iterable[str], prefix: str) -> dict[str, str]:
    return {value: f"{prefix}{index:03d}" for index, value in enumerate(sorted(set(values)), 1)}


def _counts(rows: Iterable[Mapping[str, Any]], key: str, mode: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        label = _text(row.get(key, "unspecified"), mode) or "unspecified"
        counts[label] = counts.get(label, 0) + 1
    return [{"label": label, "count": counts[label]} for label in sorted(counts)]


def _first_value(row: Mapping[str, Any], keys: Sequence[str], mode: str) -> str:
    for key in keys:
        if key in row:
            value = _display_value(row[key], mode)
            if value:
                return value
    return ""


def build_projection(
    network: Mapping[str, Any],
    research_map: Mapping[str, Any] | None = None,
    mode: str = PUBLIC_MODE,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ContractError(f"unknown privacy mode: {mode}")
    validate_inputs(network, research_map)
    raw_nodes = sorted(network["nodes"], key=lambda row: str(row["node_id"]))
    raw_relations = sorted(network["relations"], key=lambda row: str(row["relation_id"]))
    raw_gaps = sorted(network["gaps"], key=lambda row: str(row["gap_id"]))
    raw_sources = sorted(network.get("sources", []), key=lambda row: str(row["source_id"]))
    node_map = _ordinal_map((str(row["node_id"]) for row in raw_nodes), "N")
    relation_map = _ordinal_map((str(row["relation_id"]) for row in raw_relations), "R")
    gap_map = _ordinal_map((str(row["gap_id"]) for row in raw_gaps), "G")
    source_map = _ordinal_map((str(row["source_id"]) for row in raw_sources), "S")

    def visible(raw: str, mapping: Mapping[str, str]) -> str:
        return mapping.get(raw, "External") if mode == PUBLIC_MODE else _text(raw, mode)

    nodes = []
    for row in raw_nodes:
        raw_id = str(row["node_id"])
        nodes.append(
            {
                "id": visible(raw_id, node_map),
                "kind": _text(row.get("kind", "unspecified"), mode),
                "label": _text(row.get("label", "Unnamed node"), mode),
                "status": _text(row.get("status", "unspecified"), mode),
                "confidence": _text(row.get("confidence", "unspecified"), mode),
            }
        )

    def provenance_text(records: Any) -> str:
        if not isinstance(records, list):
            return ""
        parts = []
        for record in records:
            if not isinstance(record, dict):
                continue
            raw_source = str(record.get("source_id", ""))
            if mode == PUBLIC_MODE:
                source = source_map.get(raw_source) or node_map.get(raw_source) or "Source"
            else:
                source = _text(raw_source, mode)
            locator = _text(record.get("locator", ""), mode)
            parts.append(f"{source}: {locator}" if locator else source)
        return "; ".join(part for part in parts if part)

    relations = []
    for row in raw_relations:
        raw_id = str(row["relation_id"])
        relations.append(
            {
                "id": visible(raw_id, relation_map),
                "from": visible(str(row["from_id"]), node_map),
                "to": visible(str(row["to_id"]), node_map),
                "predicate": _text(row.get("predicate", "related_to"), mode),
                "status": _text(row.get("status", "unspecified"), mode),
                "confidence": _text(row.get("confidence", "unspecified"), mode),
                "provenance": provenance_text(row.get("provenance", [])),
            }
        )

    gaps = []
    for row in raw_gaps:
        raw_id = str(row["gap_id"])
        gaps.append(
            {
                "id": visible(raw_id, gap_map),
                "reason": _text(row.get("reason", "unspecified"), mode),
                "priority": _text(row.get("priority", "unspecified"), mode),
                "status": _text(row.get("status", "unspecified"), mode),
                "next_action": _text(row.get("next_action", ""), mode),
            }
        )

    sources = []
    for index, row in enumerate(raw_sources, 1):
        raw_id = str(row["source_id"])
        title = _first_value(row, ("title", "canonical_title", "label", "citation"), mode)
        metadata = []
        for key in ("authors", "year", "venue", "doi", "url", "tier"):
            value = _display_value(row.get(key), mode)
            if value:
                metadata.append(f"{key}: {value}")
        sources.append(
            {
                "id": visible(raw_id, source_map),
                "title": title or f"Source {index}",
                "metadata": " | ".join(metadata),
            }
        )
    if not sources:
        for node in nodes:
            if node["kind"].lower() == "source":
                sources.append({"id": node["id"], "title": node["label"], "metadata": ""})

    field_map = []
    if research_map is not None:
        field_ids = _ordinal_map(
            (str(row["field_id"]) for row in research_map["field_map"]), "F"
        )
        for row in sorted(research_map["field_map"], key=lambda item: str(item["field_id"])):
            raw_id = str(row["field_id"])
            field_map.append(
                {
                    "id": visible(raw_id, field_ids),
                    "label": _text(row["label"], mode),
                    "summary": _text(row.get("summary", ""), mode),
                    "nodes": [visible(str(item), node_map) for item in sorted(row.get("node_ids", []))],
                }
            )
    else:
        groups: dict[str, list[str]] = {}
        for node in nodes:
            groups.setdefault(node["kind"], []).append(node["id"])
        for index, kind in enumerate(sorted(groups), 1):
            field_map.append(
                {
                    "id": f"F{index:03d}",
                    "label": kind,
                    "summary": f"Derived node-kind group ({len(groups[kind])} nodes).",
                    "nodes": groups[kind],
                }
            )

    questions = []
    if research_map is not None:
        question_ids = _ordinal_map(
            (str(row["question_id"]) for row in research_map["competency_questions"]), "Q"
        )
        for row in sorted(
            research_map["competency_questions"], key=lambda item: str(item["question_id"])
        ):
            raw_id = str(row["question_id"])
            questions.append(
                {
                    "id": visible(raw_id, question_ids),
                    "question": _text(row["question"], mode),
                    "status": _text(row["status"], mode),
                    "answer": _text(row.get("answer", ""), mode),
                    "relations": [
                        visible(str(item), relation_map)
                        for item in sorted(row.get("relation_ids", []))
                    ],
                    "gaps": [visible(str(item), gap_map) for item in sorted(row.get("gap_ids", []))],
                }
            )

    routes = []
    if research_map is not None:
        route_ids = _ordinal_map((str(row["route_id"]) for row in research_map["routes"]), "T")
        for row in sorted(research_map["routes"], key=lambda item: str(item["route_id"])):
            raw_id = str(row["route_id"])
            routes.append(
                {
                    "id": visible(raw_id, route_ids),
                    "label": _text(row["label"], mode),
                    "summary": _text(row.get("summary", ""), mode),
                    "relations": [
                        visible(str(item), relation_map)
                        for item in sorted(row.get("relation_ids", []))
                    ],
                }
            )
    else:
        predicates: dict[str, list[str]] = {}
        for relation in relations:
            predicates.setdefault(relation["predicate"], []).append(relation["id"])
        for index, predicate in enumerate(sorted(predicates), 1):
            routes.append(
                {
                    "id": f"T{index:03d}",
                    "label": predicate,
                    "summary": f"Derived relation route ({len(predicates[predicate])} relations).",
                    "relations": predicates[predicate],
                }
            )

    recommendations = []
    if research_map is not None:
        recommendation_ids = _ordinal_map(
            (str(row["recommendation_id"]) for row in research_map["recommendations"]), "A"
        )
        for row in sorted(
            research_map["recommendations"], key=lambda item: str(item["recommendation_id"])
        ):
            raw_id = str(row["recommendation_id"])
            raw_refs = sorted(str(item) for item in row.get("evidence_refs", []))
            rendered_refs = []
            for ref in raw_refs:
                if ref in relation_map:
                    rendered_refs.append(visible(ref, relation_map))
                elif ref in gap_map:
                    rendered_refs.append(visible(ref, gap_map))
                elif ref in source_map:
                    rendered_refs.append(visible(ref, source_map))
                elif ref in node_map:
                    rendered_refs.append(visible(ref, node_map))
                else:
                    raise ContractError(f"recommendation evidence reference is unknown: {ref}")
            recommendations.append(
                {
                    "id": visible(raw_id, recommendation_ids),
                    "title": _text(row["title"], mode),
                    "rationale": _text(row.get("rationale", ""), mode),
                    "priority": _text(row.get("priority", "unspecified"), mode),
                    "evidence": rendered_refs,
                }
            )
    else:
        open_gaps = [gap for gap in gaps if gap["status"].lower() not in {"resolved", "closed"}]
        for index, gap in enumerate(open_gaps, 1):
            recommendations.append(
                {
                    "id": f"A{index:03d}",
                    "title": f"Resolve {gap['id']}",
                    "rationale": gap["next_action"] or gap["reason"],
                    "priority": gap["priority"],
                    "evidence": [gap["id"]],
                }
            )

    conflict_terms = ("conflict", "contradict", "disput", "inconsisten")
    conflicts = [
        relation
        for relation in relations
        if any(
            term in f"{relation['status']} {relation['predicate']}".lower()
            for term in conflict_terms
        )
    ]
    completion = network["completion"]
    gates = completion.get("gate_checks", {})
    if not isinstance(gates, dict):
        gates = {}
    title = (
        _text(research_map["title"], mode)
        if research_map is not None
        else _text(network.get("title", "Research knowledge network"), mode)
    )
    summary = (
        _text(research_map.get("summary", ""), mode)
        if research_map is not None
        else "A deterministic projection of reviewed evidence, relations, and open gaps."
    )
    provenance = {
        "renderer": RENDERER_VERSION,
        "mode": mode,
        "network_schema": "KnowledgeNetwork/v1",
        "research_map_schema": "ResearchMap/v1" if research_map is not None else "not supplied",
        "network_ref": "withheld in public projection"
        if mode == PUBLIC_MODE
        else _text(network["network_id"], mode),
        "snapshot_ref": "withheld in public projection"
        if mode == PUBLIC_MODE
        else _text(network["snapshot_id"], mode),
        "completion_status": _text(completion["status"], mode),
        "source_count": len(sources),
        "privacy_note": "Internal identifiers and sensitive corpus metadata are withheld."
        if mode == PUBLIC_MODE
        else "Exact stable IDs and locators retained; credentials and note/full-text fields omitted.",
    }
    return {
        "title": title,
        "summary": summary,
        "mode": mode,
        "nodes": nodes,
        "relations": relations,
        "field_map": field_map,
        "questions": questions,
        "routes": routes,
        "sources": sources,
        "gaps": gaps,
        "conflicts": conflicts,
        "recommendations": recommendations,
        "coverage": {
            "node_kinds": _counts(raw_nodes, "kind", mode),
            "relation_statuses": _counts(raw_relations, "status", mode),
            "relation_confidence": _counts(raw_relations, "confidence", mode),
            "completion_status": _text(completion["status"], mode),
            "gates": [
                {"label": _text(key, mode), "value": bool(gates[key])}
                for key in sorted(gates)
            ],
        },
        "provenance": provenance,
    }


def _h(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _search_text(*values: Any) -> str:
    flattened: list[str] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(str(item) for item in value)
        else:
            flattened.append(str(value))
    return _h(" ".join(flattened).lower())


def _cards(rows: Sequence[Mapping[str, Any]], fields: Sequence[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="empty">No reviewed entries are available for this section.</p>'
    cards = []
    for row in rows:
        searchable = _search_text(*(row.get(key, "") for key, _ in fields))
        lines = []
        for key, label in fields:
            value = row.get(key, "")
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            if value != "":
                lines.append(f'<p><strong>{_h(label)}:</strong> {_h(value)}</p>')
        cards.append(f'<article class="card searchable" data-search="{searchable}">{"".join(lines)}</article>')
    return "".join(cards)


def _graph_svg(nodes: Sequence[Mapping[str, Any]], relations: Sequence[Mapping[str, Any]]) -> str:
    if not nodes:
        return '<p class="empty">The network contains no nodes.</p>'
    columns = 3
    card_width = 260
    card_height = 78
    x_step = 300
    y_step = 112
    width = 900
    rows = (len(nodes) + columns - 1) // columns
    height = max(160, rows * y_step + 36)
    positions: dict[str, tuple[int, int]] = {}
    node_parts = []
    for index, node in enumerate(nodes):
        x = 20 + (index % columns) * x_step
        y = 24 + (index // columns) * y_step
        positions[str(node["id"])] = (x + card_width // 2, y + card_height // 2)
        label = str(node["label"])
        short = label if len(label) <= 34 else label[:31] + "..."
        search = _search_text(node["id"], node["kind"], label, node["status"])
        node_parts.append(
            f'<g class="graph-node searchable" data-search="{search}">'
            f'<title>{_h(label)}</title><rect x="{x}" y="{y}" width="{card_width}" '
            f'height="{card_height}" rx="12" />'
            f'<text x="{x + 14}" y="{y + 25}" class="node-id">{_h(node["id"])} | {_h(node["kind"])}</text>'
            f'<text x="{x + 14}" y="{y + 52}" class="node-label">{_h(short)}</text></g>'
        )
    edge_parts = []
    for relation in relations:
        start = positions.get(str(relation["from"]))
        end = positions.get(str(relation["to"]))
        if not start or not end:
            continue
        edge_parts.append(
            f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" '
            f'class="edge"><title>{_h(relation["id"])}: {_h(relation["predicate"])}</title></line>'
        )
    return (
        '<div class="graph-wrap"><svg class="network-graph" role="img" '
        'aria-label="Knowledge network node and relation view" '
        f'viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker></defs>'
        + "".join(edge_parts)
        + "".join(node_parts)
        + "</svg></div>"
    )


def _relation_table(relations: Sequence[Mapping[str, Any]]) -> str:
    if not relations:
        return '<p class="empty">No relations are present.</p>'
    body = []
    for row in relations:
        search = _search_text(*row.values())
        body.append(
            f'<tr class="searchable" data-search="{search}"><td>{_h(row["id"])}</td>'
            f'<td>{_h(row["from"])}</td><td>{_h(row["predicate"])}</td>'
            f'<td>{_h(row["to"])}</td><td>{_h(row["status"])}</td>'
            f'<td>{_h(row["confidence"])}</td><td>{_h(row["provenance"])}</td></tr>'
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>ID</th><th>From</th><th>Predicate</th>'
        '<th>To</th><th>Status</th><th>Confidence</th><th>Provenance</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def render_document(projection: Mapping[str, Any]) -> str:
    stats = (
        f'<span>{len(projection["nodes"])} nodes</span>'
        f'<span>{len(projection["relations"])} relations</span>'
        f'<span>{len(projection["sources"])} sources</span>'
        f'<span>{len(projection["gaps"])} gaps</span>'
    )
    coverage = projection["coverage"]
    coverage_cards = []
    for label, rows in (
        ("Node kinds", coverage["node_kinds"]),
        ("Relation status", coverage["relation_statuses"]),
        ("Relation confidence", coverage["relation_confidence"]),
    ):
        detail = ", ".join(f'{row["label"]}: {row["count"]}' for row in rows) or "none"
        coverage_cards.append({"label": label, "detail": detail})
    for gate in coverage["gates"]:
        coverage_cards.append(
            {"label": f'Gate: {gate["label"]}', "detail": "passed" if gate["value"] else "not passed"}
        )
    provenance_rows = [
        {"label": key.replace("_", " ").title(), "value": value}
        for key, value in sorted(projection["provenance"].items())
    ]
    style = """
:root { --ink:#17221d; --muted:#5d6d64; --paper:#f5f0e4; --panel:#fffdf7;
  --accent:#b44728; --forest:#245845; --line:#d8cfbd; --sun:#e9bd55; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; color:var(--ink); background:
  radial-gradient(circle at 12% 0%, #f5dca4 0, transparent 28rem),
  linear-gradient(135deg, #eee6d4, var(--paper) 48%, #e5eee7);
  font-family:Georgia, 'Times New Roman', serif; line-height:1.55; }
header { padding:clamp(2.2rem,7vw,5.8rem) clamp(1rem,6vw,5rem) 2.2rem;
  border-bottom:1px solid var(--line); }
.kicker { font:700 .75rem/1.2 ui-monospace,monospace; letter-spacing:.18em;
  text-transform:uppercase; color:var(--accent); }
h1 { max-width:18ch; margin:.35rem 0 1rem; font-size:clamp(2.5rem,7vw,6.2rem);
  line-height:.94; letter-spacing:-.045em; }
h2 { margin:0 0 1rem; font-size:clamp(1.7rem,4vw,3.2rem); line-height:1; }
h3 { font-size:1.05rem; }
.lede { max-width:68ch; color:var(--muted); font-size:clamp(1rem,2vw,1.25rem); }
.stats { display:flex; flex-wrap:wrap; gap:.6rem; margin-top:1.4rem; }
.stats span,.pill { border:1px solid var(--line); background:#fff8; border-radius:999px;
  padding:.35rem .75rem; font:700 .75rem/1.2 ui-monospace,monospace; }
.toolbar { position:sticky; top:0; z-index:10; padding:.8rem clamp(1rem,6vw,5rem);
  background:#f5f0e4ef; backdrop-filter:blur(9px); border-bottom:1px solid var(--line); }
.toolbar label { display:block; max-width:58rem; margin:auto; font:700 .8rem/1.2 ui-monospace,monospace; }
input[type=search] { width:100%; margin-top:.35rem; padding:.8rem 1rem; border:1px solid var(--forest);
  border-radius:0; background:var(--panel); color:var(--ink); font:inherit; }
main { width:min(1200px,calc(100% - 2rem)); margin:auto; }
section { padding:clamp(2.8rem,7vw,6rem) 0; border-bottom:1px solid var(--line); }
.section-intro { max-width:70ch; color:var(--muted); }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,245px),1fr)); gap:1rem; }
.card { min-width:0; padding:1rem; border:1px solid var(--line); background:var(--panel);
  box-shadow:5px 5px 0 #d7cdb6; overflow-wrap:anywhere; }
.card p { margin:.35rem 0; }
.empty { padding:1rem; border-left:4px solid var(--sun); background:#fff8; color:var(--muted); }
.graph-wrap,.table-wrap { overflow:auto; border:1px solid var(--line); background:var(--panel); }
.network-graph { display:block; width:100%; min-width:780px; height:auto; }
.edge { stroke:#8e9c93; stroke-width:1.3; opacity:.65; marker-end:url(#arrow); }
marker path { fill:#8e9c93; }
.graph-node rect { fill:#fffaf0; stroke:var(--forest); stroke-width:1.5; }
.graph-node:hover rect { fill:#f4dda6; }
.node-id { font:700 11px ui-monospace,monospace; fill:var(--accent); }
.node-label { font:15px Georgia,serif; fill:var(--ink); }
table { width:100%; min-width:860px; border-collapse:collapse; font-size:.9rem; }
th,td { padding:.7rem; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }
th { position:sticky; top:0; background:#ece2cc; font:700 .72rem ui-monospace,monospace;
  text-transform:uppercase; letter-spacing:.05em; }
footer { padding:2rem 1rem 4rem; text-align:center; color:var(--muted); }
[hidden] { display:none !important; }
@media (max-width:700px) {
  header { padding-top:3rem; } main { width:min(100% - 1rem,1200px); }
  section { padding:3rem 0; } .card { box-shadow:3px 3px 0 #d7cdb6; }
  .toolbar { padding:.65rem .5rem; } .network-graph { min-width:680px; }
}
@media (prefers-reduced-motion:reduce) { html { scroll-behavior:auto; } }
"""
    script = """
(() => {
  const input = document.getElementById('network-search');
  const count = document.getElementById('match-count');
  const records = Array.from(document.querySelectorAll('.searchable'));
  const apply = () => {
    const query = input.value.trim().toLocaleLowerCase();
    let visible = 0;
    records.forEach((record) => {
      const match = !query || (record.dataset.search || '').includes(query);
      record.hidden = !match;
      if (match) visible += 1;
    });
    count.textContent = query ? `${visible} matching records` : `${records.length} searchable records`;
  };
  input.addEventListener('input', apply);
  apply();
})();
"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="{_h(RENDERER_VERSION)}">
<title>{_h(projection['title'])}</title>
<style>{style}</style>
</head>
<body>
<header>
  <div class="kicker">Verified research network / {_h(projection['mode'])}</div>
  <h1>{_h(projection['title'])}</h1>
  <p class="lede">{_h(projection['summary'])}</p>
  <div class="stats">{stats}</div>
</header>
<div class="toolbar"><label for="network-search">Search the published network
  <input id="network-search" type="search" placeholder="Method, claim, source, gap..." autocomplete="off">
  <span id="match-count" aria-live="polite"></span></label></div>
<main>
<section id="field-map"><h2>Field map</h2><p class="section-intro">Reviewed domains and their linked network nodes.</p>
  <div class="grid">{_cards(projection['field_map'], (('id','ID'),('label','Field'),('summary','Scope'),('nodes','Nodes')))}</div>
</section>
<section id="competency-questions"><h2>Competency questions</h2><p class="section-intro">Questions the evidence network is expected to answer without extrapolation.</p>
  <div class="grid">{_cards(projection['questions'], (('id','ID'),('question','Question'),('status','Status'),('answer','Answer'),('relations','Relations'),('gaps','Gaps')))}</div>
</section>
<section id="routes-relations"><h2>Routes and relations</h2><p class="section-intro">Method routes first, followed by the auditable relation graph and provenance table.</p>
  <div class="grid">{_cards(projection['routes'], (('id','ID'),('label','Route'),('summary','Scope'),('relations','Relations')))}</div>
  <h3>Network view</h3>{_graph_svg(projection['nodes'], projection['relations'])}
  <h3>Relation ledger</h3>{_relation_table(projection['relations'])}
</section>
<section id="sources"><h2>Sources</h2><p class="section-intro">Presentation-safe source identities used by the rendered evidence relations.</p>
  <div class="grid">{_cards(projection['sources'], (('id','ID'),('title','Source'),('metadata','Bibliography')))}</div>
</section>
<section id="coverage-gaps-conflicts"><h2>Coverage, gaps, and conflicts</h2>
  <h3>Coverage</h3><div class="grid">{_cards(coverage_cards, (('label','Measure'),('detail','Value')))}</div>
  <h3>Open and terminal gaps</h3><div class="grid">{_cards(projection['gaps'], (('id','ID'),('reason','Reason'),('priority','Priority'),('status','Status'),('next_action','Next action')))}</div>
  <h3>Conflict relations</h3><div class="grid">{_cards(projection['conflicts'], (('id','ID'),('from','From'),('predicate','Predicate'),('to','To'),('status','Status'),('provenance','Provenance')))}</div>
</section>
<section id="recommendations"><h2>Recommendations</h2><p class="section-intro">Reviewed recommendations, or deterministic next actions derived only from explicit open gaps.</p>
  <div class="grid">{_cards(projection['recommendations'], (('id','ID'),('title','Recommendation'),('rationale','Rationale'),('priority','Priority'),('evidence','Evidence refs')))}</div>
</section>
<section id="provenance"><h2>Provenance</h2><p class="section-intro">Deterministic publication metadata. No wall-clock value or host path is included.</p>
  <div class="grid">{_cards(provenance_rows, (('label','Field'),('value','Value')))}</div>
</section>
</main>
<footer>Self-contained evidence publication generated from immutable validated inputs.</footer>
<script>{script}</script>
</body>
</html>
"""


def assert_output_privacy(document: str, mode: str) -> None:
    if any(pattern.search(document) for pattern in _CREDENTIAL_VALUE_PATTERNS):
        raise ContractError("rendered HTML contains a credential-shaped value")
    if mode == PUBLIC_MODE:
        checks = (
            (_PUBLIC_POSIX_PATH_RE, "absolute POSIX path"),
            (_PUBLIC_WINDOWS_PATH_RE, "absolute Windows path"),
            (_PUBLIC_ZOTERO_URI_RE, "Zotero URI"),
            (_PUBLIC_ITEM_CONTEXT_RE, "Zotero item key"),
            (_PUBLIC_DIGEST_RE, "content hash"),
        )
        for pattern, label in checks:
            if pattern.search(document):
                raise ContractError(f"public HTML contains forbidden {label}")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _cleanup_temporary_output(path: Path | None) -> OSError | None:
    if path is None:
        return None
    try:
        path.unlink()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return exc
    return None


def write_exclusive(path_value: str | os.PathLike[str], document: str) -> None:
    path = Path(path_value)
    if path.suffix.lower() not in {".html", ".htm"}:
        raise ContractError("output path must end in .html or .htm")
    if not path.parent.is_dir():
        raise ContractError(f"output parent directory does not exist: {path.parent}")
    if os.path.lexists(path):
        raise ContractError(f"refusing to overwrite existing output: {path}")

    temporary_path: Path | None = None
    committed = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())

        if os.path.lexists(path):
            raise ContractError(f"refusing to overwrite existing output: {path}")
        os.replace(temporary_path, path)
        committed = True
        _fsync_directory(path.parent)
    except BaseException as exc:
        if committed:
            raise ContractError(
                f"output was atomically committed but directory fsync failed: {path}"
            ) from exc
        cleanup_error = _cleanup_temporary_output(temporary_path)
        if cleanup_error is not None:
            raise ContractError(
                "atomic publication failed before commit and temporary output "
                f"was retained because cleanup failed: {temporary_path}: {cleanup_error}"
            ) from exc
        raise


def _load_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any] | None]:
    network = load_json_file(args.network)
    research_map = load_json_file(args.research_map) if args.research_map else None
    return network, research_map


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and publish immutable research networks as self-contained HTML."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "render"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--network", required=True, help="KnowledgeNetwork/v1 JSON file")
        subparser.add_argument("--research-map", help="Optional ResearchMap/v1 JSON file")
        subparser.add_argument("--mode", choices=MODES, default=PUBLIC_MODE)
        if command == "render":
            subparser.add_argument("--output", required=True, help="New .html output path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        network, research_map = _load_inputs(args)
        projection = build_projection(network, research_map, args.mode)
        document = render_document(projection)
        assert_output_privacy(document, args.mode)
        if args.command == "validate":
            print(
                f"valid: KnowledgeNetwork/v1"
                f"{', ResearchMap/v1' if research_map is not None else ''}; mode={args.mode}"
            )
            return 0
        write_exclusive(args.output, document)
        print(f"rendered: {args.output}")
        return 0
    except (ContractError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
