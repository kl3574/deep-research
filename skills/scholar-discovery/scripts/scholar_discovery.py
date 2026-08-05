#!/usr/bin/env python3
"""Compose auditable scholarly-discovery contracts and execute legal API routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REQUEST_SCHEMA = "ScholarDiscoveryRequest/v1"
REQUEST_SET_SCHEMA = "ScholarDiscoveryRequestSet/v1"
PLAN_SCHEMA = "ScholarQueryPlan/v1"
BATCH_SCHEMA = "ScholarResultBatch/v1"
RESULT_SCHEMA = "ScholarDiscoveryResult/v1"
RESULT_SET_SCHEMA = "ScholarDiscoveryResultSet/v1"
REQUEST_SET_SCHEMA_VERSION = "v1"

INTENTS = {"auto", "known_item", "topic_set", "author", "citation_graph", "update"}
EFFORTS = {"fast", "diligent"}
AUTOMATIC_PROVIDERS = {
    "openalex",
    "semantic_scholar",
    "crossref",
    "opencitations",
    "pubmed",
    "europepmc",
    "arxiv",
}
EXECUTABLE_PROVIDERS = {"openalex", "crossref", "semantic_scholar"}
GOOGLE_PROVIDER = "google_scholar"
GOOGLE_POLICIES = {"disabled", "manual_optional", "manual_required"}
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
BATCH_STATUSES = {
    "success",
    "partial",
    "empty",
    "blocked",
    "failed",
    "budget_exhausted",
    "succeeded",
}
BATCH_SUCCESS_STATUSES = {"success", "succeeded"}
SEARCH_SUCCESS_STATUSES = {"success", "succeeded", "empty"}
BATCH_INCOMPLETE_STATUSES = {"partial", "blocked", "failed", "budget_exhausted"}
BATCH_TERMINAL_STATUSES = {"success", "succeeded", "partial", "empty", "blocked", "failed", "budget_exhausted"}
ACCESS_LEVELS = {"metadata_only", "abstract_only", "snippet_only", "full_text"}
OPENALEX_API_KEY_ENV = "OPENALEX_API_KEY"
SEMANTIC_SCHOLAR_API_KEY_ENV = "SEMANTIC_SCHOLAR_API_KEY"
OPENALEX_RESULTS_PER_PAGE = 10
SEMANTIC_SCHOLAR_RESULTS_LIMIT = 10
HTTP_USER_AGENT = "scholar-discovery/1.0 (+https://github.com/kl3574/deep-research)"
SEMANTIC_SCHOLAR_FIELDS = ",".join(
    [
        "title",
        "year",
        "venue",
        "publicationTypes",
        "externalIds",
        "authors",
        "isOpenAccess",
        "openAccessPdf",
        "url",
    ]
)
PUBLICATION_STATUSES = {
    "peer_reviewed",
    "preprint",
    "corrected",
    "retracted",
    "withdrawn",
    "unknown",
}
SCREENING_DECISIONS = {"include", "exclude", "maybe", "unscreened"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^([0-9A-Za-z_\-.:/]+)$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

ENDPOINT_HINTS = {
    "openalex": "https://api.openalex.org/works",
    "crossref": "https://api.crossref.org/works",
    "semantic_scholar": "https://api.semanticscholar.org/graph/v1/paper/search",
    "opencitations": "https://api.opencitations.net/index/v2",
    "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
    "europepmc": "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
    "arxiv": "https://export.arxiv.org/api/query",
}

SEARCH_EVENT_REQUIRED_FIELDS = {
    "endpoint",
    "redacted_request",
    "page_or_cursor",
    "expected_total",
    "retrieved",
    "truncated",
    "response_sha256",
    "limitations",
}
SEARCH_EVENT_OPTIONAL_FIELDS = {
    "artifact_origin",
    "rejected_candidate_count",
}
SEARCH_EVENT_FORBIDDEN_FIELDS = {
    "secret",
    "raw",
    "raw_query",
    "raw_request",
    "raw_response",
    "raw_payload",
    "raw_body",
    "full_text",
    "fulltext",
    "abstract",
    "snippet",
    "html",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "authorization",
    "cookie",
    "session",
}
GOOGLE_NOT_PROVIDED_ORIGINS = {
    "not_provided_manual_optional",
    "not_provided_manual_required",
}
GOOGLE_USER_SUPPLIED_ORIGIN = "user_supplied_manual_export"

SCHOLAR_EXECUTION = "user_manual_export"
DOCUMENTED_EXECUTION = "documented_api"
GOOGLE_LIMITATION_MANUAL_EXPORT = "manual_export_not_provided"
ARXIV_V2_SUFFIX_RE = re.compile(r"v(\d+)$", flags=re.IGNORECASE)
ENDPOINT_WHITELIST = {
    "openalex": "https://api.openalex.org/works",
    "crossref": "https://api.crossref.org/works",
    "semantic_scholar": "https://api.semanticscholar.org/graph/v1/paper/search",
    "opencitations": "https://api.opencitations.net/index/v2",
    "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
    "europepmc": "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
    "arxiv": "https://export.arxiv.org/api/query",
    "google_scholar": "https://scholar.google.com/scholar",
}

Transport = Callable[[str, int], bytes]


class ContractError(ValueError):
    """Raised when a discovery contract fails closed."""



def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def now_iso_utc() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


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


def require_positive_int(value: Any, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise ContractError(f"{label} must be an integer in [1, {maximum}]")
    return value


def require_timestamp(value: Any, label: str) -> str:
    text = require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return text


def ensure_sha256(value: Any, label: str) -> str:
    text = require_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return text


def canonical_request_set_digest(document: dict[str, Any]) -> str:
    normalized = {
        key: value for key, value in document.items() if key not in {"request_set_id", "request_set_digest"}
    }
    return sha256_json(normalized)


def validate_network_ref(
    value: Any,
    label: str,
    network_id: str | None = None,
    network_snapshot_sha256: str | None = None,
) -> dict[str, str]:
    ref = require_dict(value, label)
    network_id_in_ref = require_string(ref.get("network_id"), f"{label}.network_id")
    require_string(ref.get("snapshot_id"), f"{label}.snapshot_id")
    sha256 = ensure_sha256(ref.get("sha256"), f"{label}.sha256")
    ref["sha256"] = sha256
    if network_id is not None and network_id_in_ref != network_id:
        raise ContractError(f"{label}.network_id is inconsistent with parent network_id")
    if network_snapshot_sha256 is not None and sha256 != network_snapshot_sha256:
        raise ContractError(f"{label}.sha256 is inconsistent with parent network_snapshot_sha256")
    return ref


def require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ContractError(f"{label} must be a list of non-empty strings")
    return [item.strip() for item in value]


def normalize_provider(value: Any, label: str) -> str:
    provider = require_string(value, label).lower()
    if provider in AUTOMATIC_PROVIDERS | {GOOGLE_PROVIDER}:
        return provider
    raise ContractError(f"{label} is unknown: {provider}")


def validate_request(value: Any) -> dict[str, Any]:
    request = require_dict(value, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ContractError(f"request.schema must equal {REQUEST_SCHEMA}")

    require_string(request.get("request_id"), "request.request_id")
    require_string(request.get("paper_need"), "request.paper_need")
    if request.get("intent") not in INTENTS:
        raise ContractError(f"request.intent must be one of {sorted(INTENTS)}")
    if request.get("effort") not in EFFORTS:
        raise ContractError(f"request.effort must be one of {sorted(EFFORTS)}")

    criteria = require_dict(request.get("criteria"), "request.criteria")
    for key in ("must", "should", "must_not"):
        require_string_list(criteria.get(key), f"request.criteria.{key}")

    filters = require_dict(request.get("metadata_filters"), "request.metadata_filters")
    years = require_dict(filters.get("years", {}), "request.metadata_filters.years")
    year_from = years.get("from")
    year_to = years.get("to")
    for key, year in (("from", year_from), ("to", year_to)):
        if year is not None and (isinstance(year, bool) or not isinstance(year, int) or year < 1000 or year > 3000):
            raise ContractError(f"request.metadata_filters.years.{key} is invalid")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ContractError("request.metadata_filters.years.from exceeds years.to")

    for key in ("authors", "venues", "languages", "work_types"):
        require_string_list(filters.get(key, []), f"request.metadata_filters.{key}")
    if filters.get("open_access") not in {None, True, False}:
        raise ContractError("request.metadata_filters.open_access must be true, false, or null")

    seeds = require_dict(request.get("seeds"), "request.seeds")
    for key in ("doi", "arxiv", "pmid", "openalex", "semantic_scholar", "titles"):
        require_string_list(seeds.get(key), f"request.seeds.{key}")

    routes = require_dict(request.get("routes"), "request.routes")
    raw_automatic = require_string_list(routes.get("automatic"), "request.routes.automatic")
    automatic = [normalize_provider(provider, f"request.routes.automatic[{index}]") for index, provider in enumerate(raw_automatic)]
    request["routes"]["automatic"] = list(dict.fromkeys(automatic))
    if GOOGLE_PROVIDER in request["routes"]["automatic"]:
        raise ContractError("Google Scholar must never be an automatic provider")

    raw_google = require_string(routes.get("google_scholar"), "request.routes.google_scholar").lower()
    if raw_google not in GOOGLE_POLICIES:
        raise ContractError(f"request.routes.google_scholar must be one of {sorted(GOOGLE_POLICIES)}")
    request["routes"]["google_scholar"] = raw_google

    budgets = require_dict(request.get("budgets"), "request.budgets")
    require_positive_int(budgets.get("max_rounds"), "request.budgets.max_rounds", 20)
    require_positive_int(budgets.get("max_queries"), "request.budgets.max_queries", 100)
    require_positive_int(budgets.get("max_candidates"), "request.budgets.max_candidates", 5000)
    require_positive_int(budgets.get("timeout_seconds"), "request.budgets.timeout_seconds", 86400)

    query_seeds = request.get("query_seeds")
    if not isinstance(query_seeds, list) or not query_seeds:
        raise ContractError("request.query_seeds must be a non-empty list")
    for index, seed in enumerate(query_seeds):
        item = require_dict(seed, f"request.query_seeds[{index}]")
        if item.get("objective") not in QUERY_OBJECTIVES:
            raise ContractError(f"request.query_seeds[{index}].objective must be supported")
        require_string(item.get("query"), f"request.query_seeds[{index}].query")

    require_timestamp(request.get("as_of"), "request.as_of")

    if "gap_ref" in request and "gap_hypothesis_id" not in request:
        gap_ref = require_dict(request["gap_ref"], "request.gap_ref")
        request["gap_hypothesis_id"] = require_string(
            gap_ref.get("gap_id"), "request.gap_ref.gap_id"
        )
    else:
        require_string(request.get("gap_hypothesis_id"), "request.gap_hypothesis_id")

    # keep backward-compat for non-network fields if present
    if "schema_version" in request:
        if request["schema_version"] != REQUEST_SET_SCHEMA_VERSION:
            raise ContractError("request.schema_version is unsupported")
    return request


def validate_request_set(value: Any) -> dict[str, Any]:
    request_set = require_dict(value, "request_set")
    if request_set.get("schema") != REQUEST_SET_SCHEMA:
        raise ContractError(f"request_set.schema must equal {REQUEST_SET_SCHEMA}")

    if "schema_version" not in request_set:
        request_set["schema_version"] = REQUEST_SET_SCHEMA_VERSION
    if request_set["schema_version"] != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("request_set.schema_version is unsupported")

    requests = request_set.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ContractError("request_set.requests must be a non-empty list")

    validated_requests = [validate_request(item) for item in requests]
    request_set["requests"] = validated_requests

    request_set["request_set_id"] = require_string(
        request_set.get("request_set_id"), "request_set.request_set_id"
    )
    request_set["request_set_digest"] = ensure_sha256(
        request_set.get("request_set_digest"), "request_set.request_set_digest"
    )
    request_set["network_ref"] = validate_network_ref(
        request_set.get("network_ref"),
        "request_set.network_ref",
        request_set.get("network_id"),
        request_set.get("network_snapshot_sha256"),
    )
    request_set_id = request_set["request_set_id"]
    request_set_digest = request_set["request_set_digest"]
    expected_request_set_id = f"request-set-{request_set_digest[:16]}"
    if request_set_id != expected_request_set_id:
        raise ContractError("request_set.request_set_id is invalid")

    if request_set_digest != canonical_request_set_digest(request_set):
        raise ContractError("request_set.request_set_digest is invalid")

    if "network_id" in request_set:
        require_string(request_set.get("network_id"), "request_set.network_id")
    if "network_snapshot_sha256" in request_set:
        ensure_sha256(request_set["network_snapshot_sha256"], "request_set.network_snapshot_sha256")
    if "generated_at" in request_set:
        require_timestamp(request_set.get("generated_at"), "request_set.generated_at")
    return request_set


def scholar_url(query: str, filters: dict[str, Any]) -> str:
    params: dict[str, Any] = {"q": query}
    years = filters.get("years", {})
    if years.get("from") is not None:
        params["as_ylo"] = years["from"]
    if years.get("to") is not None:
        params["as_yhi"] = years["to"]
    return "https://scholar.google.com/scholar?" + urllib.parse.urlencode(params)


def _normalize_endpoint(url: Any, label: str) -> str:
    text = require_string(url, label)
    parsed = urllib.parse.urlsplit(text)
    if not parsed.scheme or not parsed.netloc:
        raise ContractError(f"{label} must be a valid absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ContractError(f"{label} must not contain credentials")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "", "", ""))


def _validate_endpoint_for_provider(endpoint: str, provider: str, label: str) -> str:
    normalized = _normalize_endpoint(endpoint, label)
    allowed = ENDPOINT_WHITELIST.get(provider, normalized)
    if provider == GOOGLE_PROVIDER:
        allowed = ENDPOINT_WHITELIST["google_scholar"]
    if normalized != allowed and not normalized.startswith(f"{allowed}/"):
        raise ContractError(f"{label} is not permitted for provider {provider}")
    return normalized


def _scan_forbidden_keys(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{label} keys must be strings")
            if key.strip().lower() in SEARCH_EVENT_FORBIDDEN_FIELDS:
                raise ContractError(f"{label} contains forbidden key '{key}'")
            _scan_forbidden_keys(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{label}[{index}]")


def _contains_credential_parameter(keys: list[str]) -> None:
    credential_keys = {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "session",
    }
    for key in keys:
        if key.strip().lower() in credential_keys:
            raise ContractError(f"{key!r} is a credential-bearing parameter")


def _scan_search_event_credentials(label: str, provider: str, endpoint: str, redacted_request: dict[str, Any]) -> None:
    parsed = urllib.parse.urlsplit(endpoint)

    credential_query_keys = [name.lower() for name in urllib.parse.parse_qs(parsed.query).keys()]
    _contains_credential_parameter(credential_query_keys)

    redacted_query = redacted_request.get("query")
    if isinstance(redacted_query, str):
        redacted_query_keys = set(urllib.parse.parse_qs(redacted_query).keys())
        _contains_credential_parameter(list(redacted_query_keys))


def _expected_query_ids(request: dict[str, Any], max_queries: int | None = None) -> set[str]:
    request_digest = sha256_json(request)
    routes = request["routes"]
    provider_order = request["routes"]["automatic"]
    query_ids: set[str] = set()

    for seed_index, seed in enumerate(request["query_seeds"], start=1):
        route_specs = [(provider, DOCUMENTED_EXECUTION) for provider in provider_order]
        if routes["google_scholar"] != "disabled":
            route_specs.append((GOOGLE_PROVIDER, SCHOLAR_EXECUTION))
        for provider, _ in route_specs:
            if max_queries is not None and len(query_ids) >= max_queries:
                break
            identity = {
                "request_digest": request_digest,
                "seed_index": seed_index,
                "objective": seed["objective"],
                "provider": provider,
                "query": seed["query"],
            }
            query_ids.add("query-" + sha256_json(identity)[:16])

        if max_queries is not None and len(query_ids) >= max_queries:
            break

    return query_ids


def _build_plan(request: dict[str, Any]) -> dict[str, Any]:
    request_digest = sha256_json(request)
    routes = request["routes"]
    provider_order = request["routes"]["automatic"]
    max_queries = request["budgets"]["max_queries"]
    queries: list[dict[str, Any]] = []

    for seed_index, seed in enumerate(request["query_seeds"], start=1):
        route_specs = [(provider, DOCUMENTED_EXECUTION) for provider in provider_order]
        if routes["google_scholar"] != "disabled":
            route_specs.append((GOOGLE_PROVIDER, SCHOLAR_EXECUTION))

        for provider, execution in route_specs:
            if len(queries) >= max_queries:
                break
            identity = {
                "request_digest": request_digest,
                "seed_index": seed_index,
                "objective": seed["objective"],
                "provider": provider,
                "query": seed["query"],
            }
            row: dict[str, Any] = {
                "query_id": "query-" + sha256_json(identity)[:16],
                "seed_index": seed_index,
                "objective": seed["objective"],
                "provider": provider,
                "execution": execution,
                "query": seed["query"],
                "filters": request["metadata_filters"],
            }
            if provider == GOOGLE_PROVIDER:
                row["search_url"] = scholar_url(seed["query"], request["metadata_filters"])
                row["policy"] = routes["google_scholar"]
            else:
                row["endpoint_hint"] = ENDPOINT_HINTS[provider]
            queries.append(row)

        if len(queries) >= max_queries:
            break

    covered = {query["seed_index"] for query in queries}
    return {
        "schema": PLAN_SCHEMA,
        "request_id": request["request_id"],
        "request_digest": request_digest,
        "coverage_promise": "bounded_targeted_discovery",
        "compiled_as_of": request["as_of"],
        "google_scholar_policy": routes["google_scholar"],
        "queries": queries,
        "truncation": {
            "max_queries": max_queries,
            "query_budget_reached": bool(
                set(range(1, len(request["query_seeds"]) + 1)) - covered
            ),
            "unplanned_seed_indices": sorted(
                set(range(1, len(request["query_seeds"]) + 1)) - covered
            ),
        },
    }


def compile_plan(request_value: Any) -> dict[str, Any]:
    request = validate_request(request_value)
    return validate_plan(_build_plan(request), request)


def validate_plan(value: Any, request: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = require_dict(value, "plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ContractError(f"plan.schema must equal {PLAN_SCHEMA}")

    request_id = require_string(plan.get("request_id"), "plan.request_id")
    digest = require_string(plan.get("request_digest"), "plan.request_digest")
    if not SHA256_RE.fullmatch(digest):
        raise ContractError("plan.request_digest must be 64 lowercase hex characters")

    if request is not None:
        canonical_request = validate_request(request)
        expected_plan = _build_plan(canonical_request)
        expected_digest = expected_plan["request_digest"]
        if request_id != canonical_request["request_id"]:
            raise ContractError("plan.request_id does not match validated request")
        if digest != expected_digest:
            raise ContractError("plan.request_digest does not match validated request")
        if canonical_bytes(plan) != canonical_bytes(expected_plan):
            raise ContractError(
                "plan fields (queries/filters/provider/policy) do not match canonical rebuild"
            )
        plan = expected_plan

    if plan.get("google_scholar_policy") not in GOOGLE_POLICIES:
        raise ContractError("plan.google_scholar_policy is invalid")

    queries = plan.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ContractError("plan.queries must be a non-empty list")

    seen: set[str] = set()
    for index, query in enumerate(queries):
        item = require_dict(query, f"plan.queries[{index}]")
        query_id = require_string(item.get("query_id"), f"plan.queries[{index}].query_id")
        if query_id in seen:
            raise ContractError(f"duplicate query_id: {query_id}")
        seen.add(query_id)

        provider = normalize_provider(item.get("provider"), f"plan.queries[{index}].provider")
        execution = require_string(item.get("execution"), f"plan.queries[{index}].execution")
        if provider == GOOGLE_PROVIDER:
            if execution != SCHOLAR_EXECUTION:
                raise ContractError("Google Scholar plan entries must be user_manual_export")
            if item.get("policy") not in GOOGLE_POLICIES:
                raise ContractError("Google Scholar plan entries must include a valid policy")
        else:
            if execution != DOCUMENTED_EXECUTION:
                raise ContractError("automatic provider plan entries must be documented_api")
            if provider not in ENDPOINT_HINTS:
                raise ContractError("plan provider is unsupported")
            endpoint_hint = _validate_endpoint_for_provider(
                require_string(item.get("endpoint_hint"), f"plan.queries[{index}].endpoint_hint"),
                provider,
                f"plan.queries[{index}].endpoint_hint",
            )
            item["endpoint_hint"] = endpoint_hint

        require_string(item.get("query"), f"plan.queries[{index}].query")
    return plan


def validate_candidate(value: Any, label: str) -> dict[str, Any]:
    candidate = require_dict(value, label)
    _scan_forbidden_keys(candidate, label)

    require_string(candidate.get("title"), f"{label}.title")
    require_string_list(candidate.get("authors", []), f"{label}.authors")

    year = candidate.get("year")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or year < 1000 or year > 3000):
        raise ContractError(f"{label}.year is invalid")

    if candidate.get("venue") is not None and not isinstance(candidate.get("venue"), str):
        raise ContractError(f"{label}.venue must be a string or null")

    identifiers = require_dict(candidate.get("identifiers", {}), f"{label}.identifiers")
    for key, identifier in identifiers.items():
        require_string(key, f"{label}.identifiers key")
        require_string(identifier, f"{label}.identifiers.{key}")
        if key.casefold() == "doi":
            normalized = normalize_identifier(key, identifier)
            if not DOI_RE.fullmatch(normalized):
                raise ContractError(f"{label}.identifiers.{key} has invalid format")
            identifiers[key] = normalized
        elif not IDENTIFIER_RE.fullmatch(identifier):
            raise ContractError(f"{label}.identifiers.{key} has invalid format")

    relations = candidate.get("relations")
    if relations is not None:
        if not isinstance(relations, list):
            raise ContractError(f"{label}.relations must be a list")
        normalized_relations: list[str] = []
        for relation_index, relation in enumerate(relations):
            if isinstance(relation, str):
                rel = relation.strip()
                if not rel:
                    raise ContractError(f"{label}.relations[{relation_index}] must be non-empty")
                normalized_relations.append(rel.lower())
                continue
            if not isinstance(relation, dict):
                raise ContractError(f"{label}.relations[{relation_index}] must be string or object")
            rel_id = relation.get("id")
            if not isinstance(rel_id, str) or not rel_id.strip():
                raise ContractError(
                    f"{label}.relations[{relation_index}].id must be a non-empty string"
                )
            rel_kind = relation.get("kind", "relation")
            if not isinstance(rel_kind, str) or not rel_kind.strip():
                raise ContractError(
                    f"{label}.relations[{relation_index}].kind must be a non-empty string"
                )
            normalized_relations.append(f"{rel_kind.lower()}:{rel_id.strip()}")
        candidate["relations"] = sorted(set(normalized_relations))

    if "work_family_hint" in candidate and candidate["work_family_hint"] is not None:
        if not isinstance(candidate["work_family_hint"], str):
            raise ContractError("candidate.work_family_hint must be a string")
        candidate["work_family_hint"] = candidate["work_family_hint"].strip()
        if not candidate["work_family_hint"]:
            raise ContractError("candidate.work_family_hint must be non-empty")

    if "manifestation_id" in candidate and candidate["manifestation_id"] is not None:
        if not isinstance(candidate["manifestation_id"], str) or not candidate["manifestation_id"].strip():
            raise ContractError("candidate.manifestation_id must be a non-empty string")

    require_string(candidate.get("work_type"), f"{label}.work_type")
    if candidate.get("publication_status") not in PUBLICATION_STATUSES:
        raise ContractError(f"{label}.publication_status is invalid")

    if candidate.get("access_level") not in ACCESS_LEVELS:
        raise ContractError(f"{label}.access_level is invalid")

    rank = candidate.get("native_rank")
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise ContractError(f"{label}.native_rank must be positive")

    score = candidate.get("native_score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
        raise ContractError(f"{label}.native_score must be numeric or null")

    screening = require_dict(candidate.get("screening"), f"{label}.screening")
    if screening.get("decision") not in SCREENING_DECISIONS:
        raise ContractError(f"{label}.screening.decision is invalid")
    require_string(screening.get("reason"), f"{label}.screening.reason")
    return candidate


def validate_search_event(
    event: dict[str, Any], label: str, provider: str | None = None
) -> dict[str, Any]:
    event = require_dict(event, label)
    _scan_forbidden_keys(event, label)
    redacted = event.get("redacted_request")
    if not isinstance(redacted, dict):
        raise ContractError(f"{label}.redacted_request must be an object")
    if not redacted:
        raise ContractError(f"{label}.redacted_request must be a non-empty object")

    _scan_forbidden_keys(redacted, f"{label}.redacted_request")

    unexpected = set(event.keys()) - (SEARCH_EVENT_REQUIRED_FIELDS | SEARCH_EVENT_OPTIONAL_FIELDS)
    if unexpected:
        raise ContractError(f"{label} has unsupported keys: {sorted(unexpected)}")

    for field in SEARCH_EVENT_REQUIRED_FIELDS:
        if field not in event:
            raise ContractError(f"{label}.{field} is required")

    raw_endpoint = require_string(event.get("endpoint"), f"{label}.endpoint")
    event["endpoint"] = _validate_endpoint_for_provider(
        raw_endpoint,
        provider or "",
        f"{label}.endpoint",
    )
    redacted_query = redacted.get("query")
    if not isinstance(redacted_query, str) or not redacted_query.strip():
        raise ContractError(f"{label}.redacted_request.query must be non-empty")

    if not isinstance(event.get("limitations"), list):
        raise ContractError(f"{label}.limitations must be a list")
    if not isinstance(event.get("page_or_cursor"), str):
        raise ContractError(f"{label}.page_or_cursor must be a string")
    for field_name in ("expected_total", "retrieved"):
        value = event.get(field_name)
        if not isinstance(value, int) or value < 0:
            raise ContractError(f"{label}.{field_name} must be a non-negative integer")
    if not isinstance(event.get("truncated"), bool):
        raise ContractError(f"{label}.truncated must be boolean")
    if not isinstance(event.get("response_sha256"), str) or not SHA256_RE.fullmatch(
        event["response_sha256"]
    ):
        raise ContractError(f"{label}.response_sha256 must be 64 lowercase hex chars")
    rejected_candidate_count = event.get("rejected_candidate_count", 0)
    if not isinstance(rejected_candidate_count, int) or rejected_candidate_count < 0:
        raise ContractError(f"{label}.rejected_candidate_count must be a non-negative integer")
    if provider in {GOOGLE_PROVIDER} and event.get("page_or_cursor") not in {"manual", "*", "1"}:
        raise ContractError(f"{label}.page_or_cursor is invalid for Google Scholar")

    if not isinstance(event.get("limitations"), list):
        raise ContractError(f"{label}.limitations must be a list")

    redacted_provider = redacted.get("provider")
    if redacted_provider is not None and not isinstance(redacted_provider, str):
        raise ContractError(f"{label}.redacted_request.provider must be a string")

    redacted_query = redacted.get("query")
    if not isinstance(redacted_query, str):
        raise ContractError(f"{label}.redacted_request.query must be a string")
    if not redacted_query.strip():
        raise ContractError(f"{label}.redacted_request.query must be non-empty")

    if provider:
        _scan_search_event_credentials(label, provider, raw_endpoint, redacted)
    return event


def validate_batch(
    value: Any, plan_queries: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    batch = require_dict(value, "batch")
    if batch.get("schema") != BATCH_SCHEMA:
        raise ContractError(f"batch.schema must equal {BATCH_SCHEMA}")

    digest = require_string(batch.get("request_digest"), "batch.request_digest")
    if not SHA256_RE.fullmatch(digest):
        raise ContractError("batch.request_digest must be 64 lowercase hex")

    query_id = require_string(batch.get("query_id"), "batch.query_id")
    provider = normalize_provider(batch.get("provider"), "batch.provider")
    execution = require_string(batch.get("execution"), "batch.execution")
    status = require_string(batch.get("status"), "batch.status")
    if status == "succeeded":
        status = "success"
    if status not in BATCH_STATUSES:
        raise ContractError(f"batch.status must be one of {sorted(BATCH_STATUSES)}")
    batch["status"] = status
    if execution not in {DOCUMENTED_EXECUTION, SCHOLAR_EXECUTION}:
        raise ContractError("batch.execution must be documented_api or user_manual_export")

    require_timestamp(batch.get("accessed_at"), "batch.accessed_at")
    require_string(batch.get("query"), "batch.query")

    event = validate_search_event(
        require_dict(batch.get("search_event"), "batch.search_event"),
        "batch.search_event",
        provider,
    )
    if provider != GOOGLE_PROVIDER:
        if event.get("endpoint") != _validate_endpoint_for_provider(
            event["endpoint"], provider, "batch.search_event.endpoint"
        ):
            event["endpoint"] = _validate_endpoint_for_provider(
                event["endpoint"], provider, "batch.search_event.endpoint"
            )
    else:
        _validate_endpoint_for_provider(
            event["endpoint"], GOOGLE_PROVIDER, "batch.search_event.endpoint"
        )

    if provider == GOOGLE_PROVIDER:
        if execution != SCHOLAR_EXECUTION:
            raise ContractError("Google Scholar batches must be user_manual_export")
        artifact_origin = event.get("artifact_origin")
        if batch["status"] == "blocked":
            if artifact_origin not in GOOGLE_NOT_PROVIDED_ORIGINS:
                raise ContractError(
                    "Google manual search events must carry not_provided_manual_* origin"
                )
            if artifact_origin == "not_provided_manual_optional":
                if plan_queries is not None:
                    policy = plan_queries.get(query_id, {}).get("policy")
                    if policy != "manual_optional":
                        raise ContractError(
                            "not_provided_manual_optional only allowed for manual_optional policy"
                        )
            elif artifact_origin == "not_provided_manual_required":
                if plan_queries is not None:
                    policy = plan_queries.get(query_id, {}).get("policy")
                    if policy != "manual_required":
                        raise ContractError(
                            "not_provided_manual_required only allowed for manual_required policy"
                        )
        elif artifact_origin in GOOGLE_NOT_PROVIDED_ORIGINS:
            raise ContractError("Google Scholar placeholder origin is blocked-only")
        elif artifact_origin is not None and artifact_origin != GOOGLE_USER_SUPPLIED_ORIGIN:
            raise ContractError(
                f"Google manual search events support only '{GOOGLE_USER_SUPPLIED_ORIGIN}' when not blocked"
            )
    elif execution != DOCUMENTED_EXECUTION:
        raise ContractError("automatic provider batches must be documented_api")

    if provider == GOOGLE_PROVIDER:
        batch["provider"] = GOOGLE_PROVIDER
    if plan_queries is not None:
        planned = plan_queries.get(query_id)
        if planned is None:
            raise ContractError(f"batch query_id was not planned: {query_id}")
        for field in ("provider", "execution", "query"):
            if batch.get(field) != planned.get(field):
                raise ContractError(f"batch.{field} does not match plan")

    candidates = batch.get("candidates")
    if not isinstance(candidates, list):
        raise ContractError("batch.candidates must be a list")
    for index, candidate in enumerate(candidates):
        validate_candidate(candidate, f"batch.candidates[{index}]")

    return batch


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _normalize_arxiv_identifier(value: str, keep_version: bool = True) -> str:
    text = value.strip()
    text = re.sub(r"^(?:arxiv:|https?://arxiv\.org/abs/)", "", text, flags=re.I)
    if not keep_version:
        text = ARXIV_V2_SUFFIX_RE.sub("", text)
    return text.casefold()


def normalize_identifier(kind: str, value: str) -> str:
    text = value.strip()
    if kind.casefold() == "doi":
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
        text = re.sub(r"^doi:\s*", "", text, flags=re.I)
    if kind.casefold() == "arxiv":
        text = _normalize_arxiv_identifier(text, keep_version=True)
    return text.casefold()


def _first_author_key(candidates: list[str]) -> str:
    return normalize_text(candidates[0]) if candidates else ""


def _collect_identifier_value(
    identifiers: dict[str, str],
    kind: str,
    value: Any,
) -> bool:
    if not isinstance(value, str):
        return False

    normalized = (
        _normalize_arxiv_identifier(value, keep_version=True)
        if kind == "arxiv"
        else normalize_identifier(kind, value)
    )
    if kind == "doi":
        if not DOI_RE.fullmatch(normalized):
            return True
    elif not IDENTIFIER_RE.fullmatch(normalized):
        return True

    identifiers[kind] = normalized
    return False


def _family_weak_signature(candidate: dict[str, Any], fallback: str) -> str:
    title = normalize_text(candidate["title"])
    authors = candidate.get("authors", [])
    year = candidate.get("year")
    first_author = _first_author_key(authors) if isinstance(authors, list) else ""
    if title and first_author and year:
        return f"weak:{sha256_json([title, first_author, year])}"
    return f"weak:{sha256_json([fallback])}"


def family_signatures(candidate: dict[str, Any], fallback: str) -> tuple[list[str], str]:
    identifiers = candidate.get("identifiers", {})
    signatures: set[str] = set()

    for kind in ("doi", "pmid", "semantic_scholar", "openalex"):
        identifier = identifiers.get(kind)
        if identifier:
            signatures.add(f"{kind}:{normalize_identifier(kind, identifier)}")

    arxiv_identifier = identifiers.get("arxiv")
    if arxiv_identifier:
        signatures.add(f"arxiv:{_normalize_arxiv_identifier(arxiv_identifier, keep_version=False)}")

    for relation in normalize_relation_ids(candidate):
        signatures.add(f"relation:{relation}")

    signatures.add(_family_weak_signature(candidate, fallback))

    if candidate.get("work_family_hint"):
        signatures.add(f"hint:{normalize_text(candidate['work_family_hint'])}")

    sorted_signatures = sorted(signatures)
    confidence = "low"
    if any(
        signature.startswith(("doi:", "pmid:", "semantic_scholar:", "openalex:", "arxiv:"))
        for signature in sorted_signatures
    ):
        confidence = "high"
    return sorted_signatures, confidence


def _collect_identifiers_from_value(value: Any, identifiers: dict[str, str]) -> bool:
    rejected = False
    if isinstance(value, str):
        lowered = value.lower()
        if "arxiv.org/abs/" in lowered:
            rejected = rejected or _collect_identifier_value(identifiers, "arxiv", value)
            return rejected
        if "doi.org/" in lowered:
            rejected = rejected or _collect_identifier_value(identifiers, "doi", value)
            return rejected
        if "openalex.org/" in lowered:
            rejected = rejected or _collect_identifier_value(identifiers, "openalex", value)
            return rejected
    if isinstance(value, dict):
        for val in value.values():
            if _collect_identifiers_from_value(val, identifiers):
                rejected = True
    elif isinstance(value, list):
        for item in value:
            if _collect_identifiers_from_value(item, identifiers):
                rejected = True
    return rejected


def _extract_openalex_identifiers(item: dict[str, Any]) -> tuple[dict[str, str], int]:
    identifiers: dict[str, str] = {}
    rejected_candidates = 0

    def _mark_rejected() -> None:
        nonlocal rejected_candidates
        rejected_candidates += 1

    def add_from_mapping(mapping: Any, kind_hints: dict[str, str] | None = None) -> None:
        if not isinstance(mapping, dict):
            return
        for key, value in mapping.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            normalized_key = key.strip().lower()
            normalized_value = value.strip()
            if not normalized_value:
                continue
            if kind_hints and normalized_key in kind_hints:
                if _collect_identifier_value(identifiers, kind_hints[normalized_key], normalized_value):
                    _mark_rejected()
                continue
            if "doi" in normalized_key:
                if _collect_identifier_value(identifiers, "doi", normalized_value):
                    _mark_rejected()
            elif "pmid" in normalized_key:
                if _collect_identifier_value(identifiers, "pmid", normalized_value):
                    _mark_rejected()
            elif "openalex" in normalized_key:
                if _collect_identifier_value(identifiers, "openalex", normalized_value):
                    _mark_rejected()
            elif "arxiv" in normalized_key:
                if _collect_identifier_value(identifiers, "arxiv", normalized_value):
                    _mark_rejected()
            elif normalized_key in {"semantic_scholar", "semantic scholar", "semanticscholar", "s2"}:
                if _collect_identifier_value(identifiers, "semantic_scholar", normalized_value):
                    _mark_rejected()

            if _collect_identifiers_from_value(normalized_value, identifiers):
                _mark_rejected()

    add_from_mapping(item.get("ids"), {"doi": "doi", "pmid": "pmid", "openalex": "openalex", "openalexid": "openalex"})
    add_from_mapping(item.get("primary_location"), {"source_id": "openalex", "id": "openalex"})
    for location in item.get("locations") or []:
        if isinstance(location, dict):
            add_from_mapping(location.get("source"), {"source_id": "openalex", "id": "openalex"})
            add_from_mapping(location, {"landing_page_url": "openalex"})
            add_from_mapping(location.get("source", {}).get("ids") if isinstance(location.get("source"), dict) else None)
    for venue in item.get("alternative_host_venues") or []:
        if isinstance(venue, dict):
            add_from_mapping(venue.get("ids"), {"openalex": "openalex"})
            if _collect_identifiers_from_value(venue.get("id"), identifiers):
                _mark_rejected()
    relations = item.get("relation")
    if isinstance(relations, dict):
        for related in relations.values():
            if _collect_identifiers_from_value(related, identifiers):
                _mark_rejected()
    for rel in item.get("link", []) if isinstance(item.get("link"), list) else []:
        if _collect_identifiers_from_value(rel, identifiers):
            _mark_rejected()

    return identifiers, min(rejected_candidates, 1)


def _extract_crossref_identifiers(item: dict[str, Any]) -> tuple[dict[str, str], int]:
    identifiers: dict[str, str] = {}
    rejected_candidates = 0
    direct = item.get("DOI")
    if isinstance(direct, str):
        if _collect_identifier_value(identifiers, "doi", direct):
            rejected_candidates += 1

    for relation in (item.get("relation") or {}).values() if isinstance(item.get("relation"), dict) else []:
        if isinstance(relation, dict):
            relation = [relation]
        if isinstance(relation, list):
            for related in relation:
                if _collect_identifiers_from_value(related, identifiers):
                    rejected_candidates += 1

    for relation in item.get("relation", {}).values():
        if _collect_identifiers_from_value(relation, identifiers):
            rejected_candidates += 1

    for link in item.get("link", []) if isinstance(item.get("link"), list) else []:
        if _collect_identifiers_from_value(link, identifiers):
            rejected_candidates += 1

    for alternative in item.get("alternative-id", []) if isinstance(item.get("alternative-id"), list) else []:
        if isinstance(alternative, str) and alternative:
            if _collect_identifier_value(identifiers, "doi", alternative):
                rejected_candidates += 1

    if item.get("URL") and isinstance(item["URL"], str):
        if _collect_identifiers_from_value(item["URL"], identifiers):
            rejected_candidates += 1

    if item.get("id") and isinstance(item["id"], str):
        if _collect_identifiers_from_value(item["id"], identifiers):
            rejected_candidates += 1

    return identifiers, min(rejected_candidates, 1)


def _extract_semantic_scholar_identifiers(item: dict[str, Any]) -> tuple[dict[str, str], int]:
    identifiers: dict[str, str] = {}
    rejected_candidates = 0

    direct = item.get("paperId")
    if isinstance(direct, str):
        if _collect_identifier_value(identifiers, "semantic_scholar", direct):
            rejected_candidates += 1

    external_ids = item.get("externalIds")
    if isinstance(external_ids, dict):
        if doi := external_ids.get("DOI"):
            if isinstance(doi, str):
                if _collect_identifier_value(identifiers, "doi", doi):
                    rejected_candidates += 1
        if pmid := external_ids.get("PMID"):
            if isinstance(pmid, str):
                if _collect_identifier_value(identifiers, "pmid", pmid):
                    rejected_candidates += 1
        if arxiv := external_ids.get("ArXiv"):
            if isinstance(arxiv, str):
                if _collect_identifier_value(identifiers, "arxiv", arxiv):
                    rejected_candidates += 1

    for key in ("url", "publicationVenue"):
        if _collect_identifiers_from_value(item.get(key), identifiers):
            rejected_candidates += 1

    return identifiers, min(rejected_candidates, 1)


def normalize_relation_ids(candidate: dict[str, Any]) -> list[str]:
    relations = candidate.get("relations") or []
    normalized: list[str] = []
    for relation in relations:
        relation_value = relation if isinstance(relation, str) else relation
        if isinstance(relation_value, str):
            normalized.append(normalize_text(relation_value))
    return sorted(set(normalized))


def choose_field(values: list[Any]) -> Any:
    encoded = [json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values]
    winner, _ = sorted(Counter(encoded).items(), key=lambda item: (-item[1], item[0]))[0]
    return json.loads(winner)


def compute_manifestation_id(candidate: dict[str, Any], fallback: str) -> str:
    if "manifestation_id" in candidate and candidate.get("manifestation_id"):
        return "man-" + str(candidate["manifestation_id"]).strip()

    identifiers = candidate.get("identifiers", {})
    for kind in ("doi", "pmid", "arxiv", "semantic_scholar", "openalex"):
        identifier = identifiers.get(kind)
        if identifier:
            if kind == "arxiv":
                return f"man-arxiv:{normalize_identifier('arxiv', identifier)}"
            return f"man-{kind}:{normalize_identifier(kind, identifier)}"

    return f"man-{fallback[:16]}"


def compute_family_key(candidate: dict[str, Any], fallback: str) -> tuple[str, str]:
    work_family_hint = candidate.get("work_family_hint")
    if work_family_hint:
        return f"hint:{normalize_text(work_family_hint)}", "high"

    relation_ids = normalize_relation_ids(candidate)
    if relation_ids:
        return f"relation:{sha256_json(relation_ids)}", "high"

    identifiers = candidate.get("identifiers", {})
    for kind in ("doi", "pmid", "semantic_scholar", "openalex"):
        identifier = identifiers.get(kind)
        if identifier:
            return f"{kind}:{normalize_identifier(kind, identifier)}", "high"
    arxiv_identifier = identifiers.get("arxiv")
    if arxiv_identifier:
        return f"arxiv:{_normalize_arxiv_identifier(arxiv_identifier, keep_version=False)}", "high"

    signatures, confidence = family_signatures(candidate, fallback)
    return signatures[0], confidence


def _is_manual_export_blocking_failure(batch: dict[str, Any], plan: dict[str, Any]) -> bool:
    if batch["provider"] != GOOGLE_PROVIDER:
        return batch["status"] in {"blocked", "failed", "partial", "budget_exhausted"}

    if batch["status"] != "blocked":
        return False

    artifact_origin = batch["search_event"].get("artifact_origin")
    if artifact_origin == "not_provided_manual_optional":
        return False
    if artifact_origin == "not_provided_manual_required":
        return True
    return plan.get("google_scholar_policy") == "manual_required"


def build_result(
    request_value: Any, plan_value: Any, batch_values: list[Any]
) -> dict[str, Any]:
    request = validate_request(request_value)
    plan = validate_plan(plan_value, request)
    plan_queries = {query["query_id"]: query for query in plan["queries"]}
    request_digest = sha256_json(request)

    batches: list[dict[str, Any]] = []
    seen_query_ids: set[str] = set()
    for value in batch_values:
        batch = validate_batch(value, plan_queries)
        if batch["request_digest"] != request_digest:
            raise ContractError("batch is not bound to request")
        if batch["query_id"] in seen_query_ids:
            raise ContractError(f"duplicate batch for {batch['query_id']}")
        seen_query_ids.add(batch["query_id"])
        batches.append(batch)

    order = {query["query_id"]: index for index, query in enumerate(plan["queries"])}
    batches.sort(key=lambda batch: order[batch["query_id"]])

    manifestation_clusters: dict[str, list[dict[str, Any]]] = {}
    for batch in batches:
        ranked_candidates = sorted(batch["candidates"], key=lambda item: item["native_rank"])
        for candidate in ranked_candidates:
            fallback = f"{batch['query_id']}:{candidate['native_rank']}"
            manifestation_id = compute_manifestation_id(candidate, sha256_json(fallback))
            family_key, _ = compute_family_key(candidate, sha256_json(fallback))
            signature_set, signature_confidence = family_signatures(
                candidate, sha256_json(fallback)
            )
            observation = {
                "batch": batch,
                "candidate": candidate,
                "manifestation_id": manifestation_id,
                "family_key": family_key,
                "family_confidence": signature_confidence,
                "family_signatures": signature_set,
            }
            manifestation_clusters.setdefault(manifestation_id, []).append(observation)

    family_map: dict[str, set[str]] = {}
    class _UnionFind:
        def __init__(self) -> None:
            self.parent: dict[str, str] = {}
            self.size: dict[str, int] = {}

        def add(self, node: str) -> None:
            self.parent.setdefault(node, node)
            self.size.setdefault(node, 1)

        def find(self, node: str) -> str:
            while self.parent[node] != node:
                self.parent[node] = self.parent[self.parent[node]]
                node = self.parent[node]
            return node

        def union(self, left: str, right: str) -> None:
            left_root = self.find(left)
            right_root = self.find(right)
            if left_root == right_root:
                return
            if self.size[left_root] < self.size[right_root]:
                left_root, right_root = right_root, left_root
            self.parent[right_root] = left_root
            self.size[left_root] += self.size[right_root]

    union_find = _UnionFind()
    for manifestation_id in manifestation_clusters:
        union_find.add(manifestation_id)

    signature_to_members: dict[str, list[str]] = {}
    weak_signature_to_members: dict[str, list[str]] = {}
    for manifestation_id, observations in manifestation_clusters.items():
        for observation in observations:
            for signature in observation["family_signatures"]:
                if signature.startswith("weak:"):
                    weak_signature_to_members.setdefault(signature, []).append(manifestation_id)
                else:
                    signature_to_members.setdefault(signature, []).append(manifestation_id)

    for signature, members in signature_to_members.items():
        if len(members) < 2:
            continue
        first_member = members[0]
        for member in members[1:]:
            union_find.union(first_member, member)

    weak_duplicate_families: set[str] = set()
    for members in weak_signature_to_members.values():
        if len(members) < 2:
            continue
        roots = {union_find.find(member) for member in members}
        if len(roots) > 1:
            weak_duplicate_families.update(roots)

    for manifestation_id in manifestation_clusters:
        family_map.setdefault(union_find.find(manifestation_id), set()).add(manifestation_id)

    root_to_family_id: dict[str, str] = {
        root: "family-" + sha256_json(sorted(manifestation_ids))[:16]
        for root, manifestation_ids in family_map.items()
    }

    weak_duplicate_family_ids = {
        root_to_family_id.get(root)
        for root in weak_duplicate_families
        if root_to_family_id.get(root) is not None
    }

    for root, manifestation_ids in list(family_map.items()):
        family_id = root_to_family_id[root]
        for manifestation_id in manifestation_ids:
            for observation in manifestation_clusters[manifestation_id]:
                observation["family_id"] = family_id

    ranked: list[dict[str, Any]] = []
    for root, manifestation_ids in list(family_map.items()):
        family_id = root_to_family_id[root]
        observations = [obs for manifestation_id in sorted(manifestation_ids) for obs in manifestation_clusters[manifestation_id]]
        fields = ("title", "authors", "year", "venue", "work_type", "publication_status")
        canonical = {
            field: choose_field([obs["candidate"][field] for obs in observations])
            for field in fields
        }
        conflicts: dict[str, list[Any]] = {}
        for field in fields:
            distinct = sorted(
                {
                    json.dumps(obs["candidate"][field], ensure_ascii=False, sort_keys=True)
                    for obs in observations
                }
            )
            if len(distinct) > 1:
                conflicts[field] = [json.loads(item) for item in distinct]

        identifiers: dict[str, str] = {}
        for obs in observations:
            for kind, identifier in obs["candidate"].get("identifiers", {}).items():
                if kind == "arxiv":
                    normalized = _normalize_arxiv_identifier(identifier, keep_version=False)
                else:
                    normalized = normalize_identifier(kind, identifier)
                previous = identifiers.get(kind)
                if previous is not None and previous != normalized:
                    conflicts[f"identifier:{kind}"] = sorted({previous, normalized})
                else:
                    identifiers[kind] = normalized

        provenance = [
            {
                "query_id": obs["batch"]["query_id"],
                "provider": obs["batch"]["provider"],
                "execution": obs["batch"]["execution"],
                "accessed_at": obs["batch"]["accessed_at"],
                "native_rank": obs["candidate"]["native_rank"],
                "native_score": obs["candidate"].get("native_score"),
            }
            for obs in observations
        ]
        unique_ranks = {(row["query_id"], row["native_rank"]) for row in provenance}
        rrf = round(sum(1.0 / (60 + rank) for _, rank in unique_ranks), 12)

        access_level = max(
            (obs["candidate"]["access_level"] for obs in observations),
            key={"snippet_only": 0, "metadata_only": 1, "abstract_only": 2, "full_text": 3}.get,
        )

        screenings = [obs["candidate"]["screening"] for obs in observations]
        has_retracted = any(
            obs["candidate"].get("publication_status") in {"retracted", "withdrawn"}
            for obs in observations
        )
        if has_retracted:
            decision = "exclude"
        else:
            decision = max(
                (screening["decision"] for screening in screenings),
                key={"exclude": 0, "unscreened": 1, "maybe": 2, "include": 3}.get,
            )

        flags: list[str] = []
        if has_retracted or canonical["publication_status"] in {
            "retracted",
            "withdrawn",
        }:
            flags.append("retracted_or_withdrawn")
        if canonical["publication_status"] == "preprint":
            flags.append("preprint")
        if access_level in {"metadata_only", "snippet_only"}:
            flags.append("insufficient_for_claim_evidence")
        if len({row["provider"] for row in provenance}) == 1:
            flags.append("single_provider")
        if family_id in weak_duplicate_family_ids:
            flags.append("possible_duplicate")
            flags.append("needs_review")
        if not identifiers:
            flags.append("no_stable_identifier")
        if conflicts:
            flags.append("identity_or_metadata_conflict")

        manifestation_ids = sorted({obs["manifestation_id"] for obs in observations})
        candidate_id = "candidate-" + sha256_json(family_id)[:16]
        quality_flags = sorted(set(flags))

        ranked.append(
            {
                "candidate_id": candidate_id,
                "manifestation_key": family_id,
                "manifestation_ids": manifestation_ids,
                "work_family_id": family_id,
                "work_family_manifestation_count": len(manifestation_ids),
                **canonical,
                "identifiers": identifiers,
                "access_level": access_level,
                "screening": {
                    "decision": decision,
                    "observations": screenings,
                },
                "field_conflicts": conflicts,
                "discovery_provenance": provenance,
                "rrf_score": rrf,
                "quality_flags": quality_flags,
                "discovery_only": True,
                "claim_support_eligible": False,
                "manifestation_count": len(manifestation_ids),
            }
        )

    decision_order = {"include": 0, "maybe": 1, "unscreened": 2, "exclude": 3}
    ranked.sort(
        key=lambda item: (
            decision_order[item["screening"]["decision"]],
            "retracted_or_withdrawn" in item["quality_flags"],
            -item["rrf_score"],
            normalize_text(item["title"]),
            item["candidate_id"],
        )
    )
    max_candidates = request["budgets"]["max_candidates"]
    pre_truncation_count = len(ranked)
    candidate_budget_reached = pre_truncation_count > max_candidates
    ranked = ranked[:max_candidates]
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index

    expected_query_ids = _expected_query_ids(request)
    planned_query_ids = {query["query_id"] for query in plan["queries"]}
    missing = sorted(expected_query_ids - seen_query_ids)

    def batch_incomplete(batch_item: dict[str, Any]) -> bool:
        if batch_item["provider"] == GOOGLE_PROVIDER:
            return _is_manual_export_blocking_failure(batch_item, plan)
        return batch_item["status"] in BATCH_INCOMPLETE_STATUSES

    failures = [
        {
            "query_id": batch["query_id"],
            "provider": batch["provider"],
            "status": batch["status"],
            "limitations": batch["search_event"].get("limitations", []),
        }
        for batch in batches
        if batch_incomplete(batch)
    ]

    query_budget_reached = bool(expected_query_ids - planned_query_ids)
    unresolved = sorted(
        set(missing) | {batch["query_id"] for batch in batches if batch_incomplete(batch)}
    )

    any_signal = any(
        (
            batch["status"] in {"success", "partial", "empty", "budget_exhausted"}
            if batch["provider"] != GOOGLE_PROVIDER
            else (
                batch["status"] == "success"
                or (
                    batch["status"] == "blocked"
                    and batch["search_event"].get("artifact_origin")
                    == "not_provided_manual_optional"
                )
            )
        )
        for batch in batches
    )

    if not batches or not any_signal:
        status = "blocked_capability"
    elif query_budget_reached or candidate_budget_reached:
        status = "partial_budget"
    elif failures or unresolved:
        status = "partial_provider"
    else:
        status = "complete_bounded"

    result = {
        "schema": RESULT_SCHEMA,
        "request_id": request["request_id"],
        "request_digest": request_digest,
        "plan_digest": sha256_json(plan),
        "discovery_status": status,
        "coverage_promise": "bounded_targeted_discovery_not_systematic_completeness",
        "as_of": max([batch["accessed_at"] for batch in batches] + [request["as_of"]]),
        "query_plan": plan["queries"],
        "search_events": [
            {
                "query_id": batch["query_id"],
                "provider": batch["provider"],
                "execution": batch["execution"],
                "status": batch["status"],
                "accessed_at": batch["accessed_at"],
                "query": batch["query"],
                "search_event": batch["search_event"],
                "candidate_count": len(batch["candidates"]),
            }
            for batch in batches
        ],
        "paper_clusters": [
            {
                "work_family_id": item["work_family_id"],
                "manifestation_ids": item["manifestation_ids"],
                "candidate_id": item["candidate_id"],
            }
            for item in ranked
        ],
        "ranked_candidates": ranked,
        "exclusions": [
            {
                "candidate_id": item["candidate_id"],
                "reason": (
                    "retracted_or_withdrawn"
                    if "retracted_or_withdrawn" in item["quality_flags"]
                    else "screening_excluded"
                ),
            }
            for item in ranked
            if item["screening"]["decision"] == "exclude"
            or "retracted_or_withdrawn" in item["quality_flags"]
        ],
        "provider_failures": failures,
        "unresolved_query_ids": unresolved,
        "stop_reason": status,
        "limits": {
            "query_budget_reached": query_budget_reached,
            "candidate_budget_reached": candidate_budget_reached,
            "missing_query_ids": missing,
            "google_scholar_manual_only": True,
        },
    }
    return validate_result(result)


def validate_result(value: Any) -> dict[str, Any]:
    result = require_dict(value, "result")
    if result.get("schema") != RESULT_SCHEMA:
        raise ContractError(f"result.schema must equal {RESULT_SCHEMA}")
    require_string(result.get("request_id"), "result.request_id")
    for field in ("request_digest", "plan_digest"):
        digest = require_string(result.get(field), f"result.{field}")
        if not SHA256_RE.fullmatch(digest):
            raise ContractError(f"result.{field} must be 64 lowercase hex")

    if result.get("discovery_status") not in {
        "complete_bounded",
        "partial_provider",
        "partial_budget",
        "blocked_capability",
    }:
        raise ContractError("result.discovery_status is invalid")

    candidates = result.get("ranked_candidates")
    if not isinstance(candidates, list):
        raise ContractError("result.ranked_candidates must be a list")

    for index, candidate in enumerate(candidates):
        item = require_dict(candidate, f"result.ranked_candidates[{index}]")
        if item.get("discovery_only") is not True:
            raise ContractError("result candidates must remain discovery_only")
        if item.get("claim_support_eligible") is not False:
            raise ContractError("discovery candidates cannot be claim evidence")
        require_string(item.get("candidate_id"), f"result.ranked_candidates[{index}].candidate_id")
    return result


def validate_result_set(value: Any) -> dict[str, Any]:
    result_set = require_dict(value, "result_set")
    if result_set.get("schema") != RESULT_SET_SCHEMA:
        raise ContractError(f"result_set.schema must equal {RESULT_SET_SCHEMA}")
    if result_set.get("schema_version") != REQUEST_SET_SCHEMA_VERSION:
        raise ContractError("result_set.schema_version is unsupported")
    request_set_id = require_string(result_set.get("request_set_id"), "result_set.request_set_id")
    request_set_digest = ensure_sha256(result_set.get("request_set_digest"), "result_set.request_set_digest")
    if request_set_id != f"request-set-{request_set_digest[:16]}":
        raise ContractError("result_set.request_set_id is invalid")

    if "generated_at" in result_set:
        require_timestamp(result_set.get("generated_at"), "result_set.generated_at")
    if "network_ref" not in result_set:
        raise ContractError("result_set.network_ref is required")
    result_set["network_ref"] = validate_network_ref(
        result_set.get("network_ref"),
        "result_set.network_ref",
        result_set.get("network_id"),
        result_set.get("network_snapshot_sha256"),
    )
    if "network_id" in result_set:
        require_string(result_set.get("network_id"), "result_set.network_id")
    if "network_snapshot_sha256" in result_set:
        ensure_sha256(result_set["network_snapshot_sha256"], "result_set.network_snapshot_sha256")

    results = result_set.get("results")
    if not isinstance(results, list):
        raise ContractError("result_set.results must be a list")
    request_ids = set()
    for index, result in enumerate(results):
        validate_result(result)
        request_id = require_string(result.get("request_id"), f"result_set.results[{index}].request_id")
        if request_id in request_ids:
            raise ContractError("result_set.results must contain unique request_id values")
        request_ids.add(request_id)
        require_string(result.get("hypothesis_id"), f"result_set.results[{index}].hypothesis_id")
        gap_hypothesis_id = require_string(result.get("gap_hypothesis_id"), f"result_set.results[{index}].gap_hypothesis_id")
        if gap_hypothesis_id != result["hypothesis_id"]:
            raise ContractError(f"result_set.results[{index}].hypothesis_id must match gap_hypothesis_id")

    failures = result_set.get("failures", [])
    if not isinstance(failures, list):
        raise ContractError("result_set.failures must be a list")
    for index, failure in enumerate(failures):
        item = require_dict(failure, f"result_set.failures[{index}]")
        if item.get("request_set_id") not in {None, request_set_id}:
            raise ContractError(f"result_set.failures[{index}].request_set_id is invalid")
        if "request_id" in item:
            require_string(item.get("request_id"), f"result_set.failures[{index}].request_id")

    return result_set


def _http_transport(url: str, timeout_seconds: int = 30) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    headers = {
        "User-Agent": HTTP_USER_AGENT,
        "Accept": "application/json",
    }
    if parsed.netloc == "api.semanticscholar.org":
        semantic_key = os.getenv(SEMANTIC_SCHOLAR_API_KEY_ENV, "").strip()
        if semantic_key:
            headers["x-api-key"] = semantic_key

    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _query_url_openalex(query: str, filters: dict[str, Any]) -> str:
    api_key = os.getenv(OPENALEX_API_KEY_ENV, "").strip()
    filter_values = []
    years = filters.get("years", {})
    if years.get("from") is not None or years.get("to") is not None:
        year_from = years.get("from", "")
        year_to = years.get("to", "")
        if year_from and year_to:
            filter_values.append(f"publication_year:{year_from}-{year_to}")
        elif year_from:
            filter_values.append(f"publication_year:>={year_from}")
        elif year_to:
            filter_values.append(f"publication_year:<={year_to}")

    params = {"search": query, "per-page": OPENALEX_RESULTS_PER_PAGE}
    if api_key:
        params["api_key"] = api_key
    if filter_values:
        params["filter"] = ",".join(filter_values)
    return ENDPOINT_HINTS["openalex"] + "?" + urllib.parse.urlencode(params)


def _query_url_crossref(query: str, filters: dict[str, Any]) -> str:
    years = filters.get("years", {})
    params: dict[str, Any] = {
        "query.title": query,
        "rows": 10,
    }
    if years.get("from") is not None:
        params["filter"] = f"from-pub-date:{years['from']}-01-01"
    if years.get("to") is not None:
        existing = params.get("filter", "")
        params["filter"] = (
            f"{existing},until-pub-date:{years['to']}-12-31" if existing else f"until-pub-date:{years['to']}-12-31"
        )
    return ENDPOINT_HINTS["crossref"] + "?" + urllib.parse.urlencode(params)


def _query_url_semantic_scholar(query: str, filters: dict[str, Any]) -> str:
    params: dict[str, Any] = {
        "query": query,
        "limit": SEMANTIC_SCHOLAR_RESULTS_LIMIT,
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }
    return ENDPOINT_HINTS["semantic_scholar"] + "?" + urllib.parse.urlencode(params)


def _parse_openalex_candidates(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    results = []
    rejected_candidate_count = 0
    for rank, item in enumerate(payload.get("results", []), start=1):
        authors = [
            author.get("author", {}).get("display_name")
            for author in item.get("authorships", [])
            if isinstance(author, dict)
            and isinstance(author.get("author"), dict)
            and author["author"].get("display_name")
        ]
        venue = None
        if item.get("host_venue", {}).get("display_name"):
            venue = item["host_venue"]["display_name"]
        if venue is None and item.get("primary_location", {}).get("source", {}).get("display_name"):
            venue = item["primary_location"]["source"]["display_name"]

        identifiers, rejected_candidate = _extract_openalex_identifiers(item)
        rejected_candidate_count += rejected_candidate

        publication_status = "peer_reviewed"
        if item.get("is_retracted"):
            publication_status = "retracted"
        elif item.get("raw_type") == "preprint":
            publication_status = "preprint"

        results.append(
            {
                "title": item.get("title", "") or item.get("display_name", ""),
                "authors": authors or ["Unknown"],
                "year": item.get("publication_year"),
                "venue": venue,
                "identifiers": identifiers,
                "work_type": item.get("type", "primary_study"),
                "publication_status": publication_status,
                "access_level": "abstract_only" if item.get("abstract_inverted_index") else "metadata_only",
                "landing_url": item.get("primary_location", {}).get("landing_page_url")
                or item.get("id"),
                "native_rank": rank,
                "native_score": item.get("relevance_score"),
                "screening": {"decision": "include", "reason": "openalex auto-match"},
            }
        )
    return results, rejected_candidate_count


def _parse_crossref_candidates(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    results = []
    rejected_candidate_count = 0
    items = payload.get("message", {}).get("items", [])
    for rank, item in enumerate(items, start=1):
        authors = []
        for author in item.get("author", []):
            family = author.get("family")
            given = author.get("given")
            if given and family:
                authors.append(f"{given} {family}")
            elif family:
                authors.append(family)
        year_parts = item.get("issued", {}).get("date-parts", [[]])[0]
        year = year_parts[0] if year_parts else None
        venue = None
        containers = item.get("container-title", [])
        if isinstance(containers, list) and containers:
            venue = containers[0]

        publication_status = "peer_reviewed"
        raw_type = (item.get("type") or "").lower()
        if "preprint" in raw_type:
            publication_status = "preprint"

        identifiers, rejected_candidate = _extract_crossref_identifiers(item)
        rejected_candidate_count += rejected_candidate

        results.append(
            {
                "title": item.get("title", [""])[0],
                "authors": authors or ["Unknown"],
                "year": year,
                "venue": venue,
                "identifiers": identifiers,
                "work_type": item.get("type", "primary_study"),
                "publication_status": publication_status,
                "access_level": "metadata_only",
                "landing_url": item.get("URL"),
                "native_rank": rank,
                "native_score": None,
                "screening": {"decision": "include", "reason": "crossref auto-match"},
            }
        )
    return results, rejected_candidate_count


def _parse_semantic_scholar_candidates(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    items = payload.get("data", [])
    results = []
    rejected_candidate_count = 0
    for rank, item in enumerate(items, start=1):
        authors = []
        for author in item.get("authors", []):
            name = author.get("name") if isinstance(author, dict) else None
            if isinstance(name, str) and name:
                authors.append(name)

        year = item.get("year")
        venue = item.get("venue")
        if isinstance(venue, dict):
            venue = venue.get("name")

        publication_status = "peer_reviewed"
        raw_types = item.get("publicationTypes")
        if isinstance(raw_types, list):
            lowered = ",".join(value.lower() for value in raw_types if isinstance(value, str))
            if "preprint" in lowered:
                publication_status = "preprint"

        identifiers, rejected_candidate = _extract_semantic_scholar_identifiers(item)
        rejected_candidate_count += rejected_candidate

        results.append(
            {
                "title": item.get("title", ""),
                "authors": authors or ["Unknown"],
                "year": year,
                "venue": venue,
                "identifiers": identifiers,
                "work_type": item.get("type", "primary_study"),
                "publication_status": publication_status,
                "access_level": "abstract_only" if item.get("openAccessPdf") else "metadata_only",
                "landing_url": item.get("url"),
                "native_rank": rank,
                "native_score": item.get("score"),
                "screening": {"decision": "include", "reason": "semantic_scholar auto-match"},
            }
        )
    return results, rejected_candidate_count


def _build_search_event(
    provider: str,
    query: str,
    url: str,
    payload: bytes,
    candidates: list[dict[str, Any]],
    expected_total: int,
    limitations: list[str],
    status: str,
    rejected_candidate_count: int = 0,
) -> dict[str, Any]:
    redacted_request = {"query": query, "provider": provider, "route": "search"}
    if provider in EXECUTABLE_PROVIDERS:
        redacted_request["filters"] = {"provider": provider}
    response_sha = hashlib.sha256(payload or b"{}").hexdigest() if status not in {"blocked"} else "0" * 64

    return {
        "endpoint": _normalize_endpoint(url, "batch.search_event.endpoint"),
        "redacted_request": redacted_request,
        "page_or_cursor": "1",
        "expected_total": int(expected_total),
        "retrieved": len(candidates),
        "truncated": len(candidates) < expected_total if expected_total else False,
        "response_sha256": response_sha,
        "limitations": limitations,
        **(
            {"rejected_candidate_count": int(rejected_candidate_count)}
            if rejected_candidate_count
            else {}
        ),
    }


def _build_manual_google_batch(
    request_digest: str,
    query: dict[str, Any],
    access_time: str,
    policy: str,
) -> dict[str, Any]:
    if policy == "manual_required":
        origin = "not_provided_manual_required"
    else:
        origin = "not_provided_manual_optional"
    return {
        "schema": BATCH_SCHEMA,
        "request_digest": request_digest,
        "query_id": query["query_id"],
        "provider": GOOGLE_PROVIDER,
        "execution": SCHOLAR_EXECUTION,
        "status": "blocked",
        "accessed_at": access_time,
        "query": query["query"],
        "search_event": {
            "endpoint": "https://scholar.google.com/scholar",
            "redacted_request": {
                "query": query["query"],
                "provider": GOOGLE_PROVIDER,
                "policy": policy,
                "route": "manual_export",
            },
            "page_or_cursor": "manual",
            "expected_total": 0,
            "retrieved": 0,
            "truncated": False,
            "response_sha256": "0" * 64,
            "artifact_origin": origin,
            "limitations": [GOOGLE_LIMITATION_MANUAL_EXPORT],
        },
        "candidates": [],
    }


def _execute_provider_query(
    provider: str,
    query: dict[str, Any],
    request_digest: str,
    transport: Transport,
    timeout_seconds: int,
) -> dict[str, Any]:
    access_time = now_iso_utc()
    provider_accessed = now_iso_utc()
    if provider == GOOGLE_PROVIDER:
        raise ContractError("Google Scholar must never be automatically executed")

    if provider == "openalex":
        if not os.getenv(OPENALEX_API_KEY_ENV, "").strip():
            return {
                "schema": BATCH_SCHEMA,
                "request_digest": request_digest,
                "query_id": query["query_id"],
                "provider": provider,
                "execution": DOCUMENTED_EXECUTION,
                "status": "blocked",
                "accessed_at": access_time,
                "query": query["query"],
                "search_event": {
                    "endpoint": ENDPOINT_HINTS["openalex"],
                    "redacted_request": {
                        "query": query["query"],
                        "provider": provider,
                        "route": "search",
                    },
                    "page_or_cursor": "1",
                    "expected_total": 0,
                    "retrieved": 0,
                    "truncated": False,
                    "response_sha256": "0" * 64,
                    "limitations": ["blocked_configuration", "missing_api_key"],
                },
                "candidates": [],
            }
        url = _query_url_openalex(query["query"], query["filters"])
        parser = _parse_openalex_candidates
    elif provider == "crossref":
        url = _query_url_crossref(query["query"], query["filters"])
        parser = _parse_crossref_candidates
    elif provider == "semantic_scholar":
        url = _query_url_semantic_scholar(query["query"], query["filters"])
        parser = _parse_semantic_scholar_candidates
    else:
        return {
            "schema": BATCH_SCHEMA,
            "request_digest": request_digest,
            "query_id": query["query_id"],
            "provider": provider,
            "execution": DOCUMENTED_EXECUTION,
            "status": "failed",
            "accessed_at": access_time,
            "query": query["query"],
            "search_event": {
                "endpoint": ENDPOINT_HINTS.get(provider, ""),
                "redacted_request": {"query": query["query"], "provider": provider, "route": "search"},
                "page_or_cursor": "1",
                "expected_total": 0,
                "retrieved": 0,
                "truncated": False,
                "response_sha256": "0" * 64,
                "limitations": ["provider_not_implemented"],
            },
            "candidates": [],
        }

    try:
        payload = transport(url, timeout_seconds)
        payload_obj = json.loads(payload.decode("utf-8"))
        candidates, rejected_candidate_count = parser(payload_obj)
        status = "success" if candidates else "empty"
        limitations: list[str] = []
        if rejected_candidate_count:
            limitations.append("rejected_candidate_records")
        if provider == "openalex":
            expected_total = payload_obj.get("meta", {}).get("count", len(candidates))
        elif provider == "crossref":
            expected_total = payload_obj.get("message", {}).get("total-results", len(candidates))
        else:
            expected_total = payload_obj.get("total", len(candidates))
        if expected_total and len(candidates) < expected_total:
            limitations.append("results_truncated")
            status = "partial"

        query_params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        for key in ("per-page", "rows", "limit"):
            limit_values = query_params.get(key)
            if not limit_values:
                continue
            try:
                limit = int(limit_values[0])
            except (TypeError, ValueError):
                limit = None
            if limit and len(candidates) >= limit and expected_total and len(candidates) < expected_total:
                limitations.append("one_page_truncation")
                break

        search_event = _build_search_event(
            provider,
            query["query"],
            url,
            payload,
            candidates,
            int(expected_total or 0),
            limitations,
            status,
            rejected_candidate_count,
        )
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        status = "failed"
        if isinstance(exc, urllib.error.HTTPError):
            limitations = [f"transport_http_{exc.code}"]
        else:
            limitations = [f"transport_error:{exc.__class__.__name__}"]
        candidates = []
        search_event = {
            "endpoint": _normalize_endpoint(url, "batch.search_event.endpoint"),
            "redacted_request": {"query": query["query"], "provider": provider, "route": "search"},
            "page_or_cursor": "1",
            "expected_total": 0,
            "retrieved": 0,
            "truncated": False,
            "response_sha256": "0" * 64,
            "limitations": limitations,
        }
    return {
        "schema": BATCH_SCHEMA,
        "request_digest": request_digest,
        "query_id": query["query_id"],
        "provider": provider,
        "execution": DOCUMENTED_EXECUTION,
        "status": status,
        "accessed_at": provider_accessed,
        "query": query["query"],
        "search_event": search_event,
        "candidates": candidates,
    }


def execute_plan(
    request_value: Any,
    plan_value: Any,
    transport: Transport,
    timeout_seconds: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    request = validate_request(request_value)
    plan = validate_plan(plan_value, request)
    request_digest = sha256_json(request)

    batches: list[dict[str, Any]] = []
    if timeout_seconds is None:
        timeout_seconds = request["budgets"]["timeout_seconds"]

    for query in plan["queries"]:
        if query["provider"] == GOOGLE_PROVIDER:
            batches.append(
                _build_manual_google_batch(
                    request_digest,
                    query,
                    now_iso_utc(),
                    query.get("policy", request["routes"]["google_scholar"]),
                )
            )
            continue

        if query["provider"] not in EXECUTABLE_PROVIDERS:
            batch = {
                "schema": BATCH_SCHEMA,
                "request_digest": request_digest,
                "query_id": query["query_id"],
                "provider": query["provider"],
                "execution": DOCUMENTED_EXECUTION,
                "status": "failed",
                "accessed_at": now_iso_utc(),
                "query": query["query"],
                "search_event": {
                    "endpoint": _normalize_endpoint(
                        query.get("endpoint_hint", ""), "batch.search_event.endpoint"
                    ),
                    "redacted_request": {
                        "query": query["query"],
                        "provider": query["provider"],
                        "route": "search",
                    },
                    "page_or_cursor": "1",
                    "expected_total": 0,
                    "retrieved": 0,
                    "truncated": False,
                    "response_sha256": "0" * 64,
                    "limitations": ["provider_not_implemented"],
                },
                "candidates": [],
            }
        else:
            batch = _execute_provider_query(
                query["provider"], query, request_digest, transport, timeout_seconds
            )

        batches.append(batch)

    discovery = build_result(request, plan, batches)
    return discovery, batches


def execute_request_set(
    request_set_value: Any,
    transport: Transport,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    request_set = validate_request_set(request_set_value)

    request_set_id = request_set.get("request_set_id")
    request_set_digest = request_set.get("request_set_digest")
    network_id = request_set.get("network_id")
    network_snapshot_sha256 = request_set.get("network_snapshot_sha256")
    network_ref = request_set.get("network_ref")

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for request in request_set["requests"]:
        try:
            request_copy = validate_request(dict(request))
            plan = compile_plan(request_copy)
            discovery, _ = execute_plan(request_copy, plan, transport, timeout_seconds)
            discovery["hypothesis_id"] = request_copy.get("gap_hypothesis_id")
            discovery["gap_hypothesis_id"] = request_copy.get("gap_hypothesis_id")
            results.append(discovery)
        except ContractError as exc:
            failures.append(
                {
                    "request_id": request.get("request_id"),
                    "request_set_id": request_set_id,
                    "gap_hypothesis_id": request.get("gap_hypothesis_id"),
                    "error": str(exc),
                }
            )

    result_set = {
        "schema": RESULT_SET_SCHEMA,
        "schema_version": REQUEST_SET_SCHEMA_VERSION,
        "request_set_id": request_set_id,
        "request_set_digest": request_set_digest,
        "network_id": network_id,
        "network_snapshot_sha256": network_snapshot_sha256,
        "network_ref": network_ref,
        "generated_at": request_set.get("generated_at", now_iso_utc()),
        "results": results,
        "failures": failures,
        "request_count": len(results),
    }
    return validate_result_set(result_set)


def validate_any(value: Any) -> dict[str, Any]:
    schema = value.get("schema") if isinstance(value, dict) else None
    if schema == REQUEST_SCHEMA:
        return validate_request(value)
    if schema == REQUEST_SET_SCHEMA:
        return validate_request_set(value)
    if schema == PLAN_SCHEMA:
        return validate_plan(value)
    if schema == BATCH_SCHEMA:
        return validate_batch(value)
    if schema == RESULT_SCHEMA:
        return validate_result(value)
    if schema == RESULT_SET_SCHEMA:
        return validate_result_set(value)
    raise ContractError(f"unsupported schema: {schema!r}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    plan = subcommands.add_parser("plan", help="compile a bounded query plan")
    plan.add_argument("--request", required=True)
    plan.add_argument("--output", required=True)

    handoff = subcommands.add_parser("handoff", help="merge normalized batches")
    handoff.add_argument("--request", required=True)
    handoff.add_argument("--plan", required=True)
    handoff.add_argument("--batch", action="append", default=[], required=True)
    handoff.add_argument("--output", required=True)

    execute = subcommands.add_parser("execute", help="execute request-set batches")
    execute.add_argument("--request-set", required=True)
    execute.add_argument("--output", required=True)

    validate = subcommands.add_parser("validate", help="validate one contract")
    validate.add_argument("--input", required=True)

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "plan":
            write_json(args.output, compile_plan(load_json(args.request)))
        elif args.command == "handoff":
            write_json(
                args.output,
                build_result(
                    load_json(args.request),
                    load_json(args.plan),
                    [load_json(path) for path in args.batch],
                ),
            )
        elif args.command == "execute":
            write_json(
                args.output,
                execute_request_set(load_json(args.request_set), _http_transport),
            )
        else:
            validated = validate_any(load_json(args.input))
            print(json.dumps({"valid": True, "schema": validated["schema"]}, sort_keys=True))
        return 0
    except (ContractError, json.JSONDecodeError, OSError) as exc:
        print(f"scholar-discovery validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
