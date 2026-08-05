#!/usr/bin/env python3
"""Validate orchestration-only routing for a verified PaperUnderstanding artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROUTE_SCHEMA = "PaperUnderstandingRoute/v1"
PROJECTION_SCHEMA = "UnderstandingNetworkProjection/v1"
VALIDATION_BINDING_SCHEMA = "PaperUnderstandingRouteValidationBinding/v1"
SCHEMA_VERSION = "1.0"
DESTINATIONS = {"research-knowledge-network", "network-gap-discovery"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when an orchestration route fails closed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_route_digest(document: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in document.items()
            if key not in {"route_id", "route_digest"}
        }
    )


def canonical_validation_binding_digest(document: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in document.items()
            if key not in {"binding_id", "binding_digest"}
        }
    )


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def _digest(value: Any, label: str) -> str:
    text = _text(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ContractError(f"{label} must be 64 lowercase hex characters")
    return text


def _validate_understanding_binding(value: Any) -> dict[str, str]:
    binding = _object(value, "understanding_binding")
    if set(binding) != {
        "understanding_id",
        "understanding_digest",
        "validation_record_id",
        "validation_record_digest",
    }:
        raise ContractError("understanding_binding has an unsupported field set")
    understanding_digest = _digest(
        binding.get("understanding_digest"), "understanding_binding.understanding_digest"
    )
    if binding.get("understanding_id") != (
        f"paper-understanding-{understanding_digest[:16]}"
    ):
        raise ContractError(
            "understanding_binding.understanding_id does not match understanding_digest"
        )
    validation_record_digest = _digest(
        binding.get("validation_record_digest"),
        "understanding_binding.validation_record_digest",
    )
    if binding.get("validation_record_id") != (
        f"paper-understanding-validation-{validation_record_digest[:16]}"
    ):
        raise ContractError(
            "understanding_binding.validation_record_id does not match "
            "validation_record_digest"
        )
    return binding


def _validate_projection_ref(value: Any) -> dict[str, str]:
    projection_ref = _object(value, "projection_ref")
    if set(projection_ref) != {"schema", "projection_id", "projection_digest"}:
        raise ContractError(
            "projection_ref must contain exactly schema, projection_id, and "
            "projection_digest"
        )
    if projection_ref.get("schema") != PROJECTION_SCHEMA:
        raise ContractError(f"projection_ref.schema must equal {PROJECTION_SCHEMA}")
    projection_digest = _digest(
        projection_ref.get("projection_digest"), "projection_ref.projection_digest"
    )
    if projection_ref.get("projection_id") != (
        f"understanding-projection-{projection_digest[:16]}"
    ):
        raise ContractError("projection_ref.projection_id does not match projection_digest")
    return projection_ref


def build_validation_binding(
    understanding_binding: dict[str, str], projection_ref: dict[str, str]
) -> dict[str, str]:
    binding = {
        "schema": VALIDATION_BINDING_SCHEMA,
        "binding_id": "",
        "binding_digest": "",
        "understanding_id": understanding_binding["understanding_id"],
        "understanding_digest": understanding_binding["understanding_digest"],
        "validation_record_id": understanding_binding["validation_record_id"],
        "validation_record_digest": understanding_binding[
            "validation_record_digest"
        ],
        "projection_id": projection_ref["projection_id"],
        "projection_digest": projection_ref["projection_digest"],
    }
    binding["binding_digest"] = canonical_validation_binding_digest(binding)
    binding["binding_id"] = (
        f"understanding-route-validation-{binding['binding_digest'][:16]}"
    )
    return binding


def _validate_validation_binding(
    value: Any,
    understanding_binding: dict[str, str],
    projection_ref: dict[str, str],
) -> dict[str, str]:
    binding = _object(value, "validation_binding")
    expected = build_validation_binding(understanding_binding, projection_ref)
    if binding != expected:
        raise ContractError(
            "validation_binding must content-bind validation record, understanding, "
            "and projection identities"
        )
    return binding


def validate_paper_understanding_route(value: Any) -> dict[str, Any]:
    route = _object(value, "paper understanding route")
    expected_keys = {
        "schema",
        "schema_version",
        "route_id",
        "route_digest",
        "understanding_binding",
        "projection_ref",
        "validation_binding",
        "destinations",
        "orchestration_only",
        "semantic_rewrite_allowed",
    }
    if set(route) != expected_keys:
        raise ContractError(
            f"paper understanding route must contain exactly {sorted(expected_keys)}"
        )
    if route.get("schema") != ROUTE_SCHEMA:
        raise ContractError(f"schema must equal {ROUTE_SCHEMA}")
    if route.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"schema_version must equal {SCHEMA_VERSION}")
    if route.get("orchestration_only") is not True:
        raise ContractError("orchestration_only must be true")
    if route.get("semantic_rewrite_allowed") is not False:
        raise ContractError("semantic_rewrite_allowed must be false")

    understanding_binding = _validate_understanding_binding(
        route.get("understanding_binding")
    )
    projection_ref = _validate_projection_ref(route.get("projection_ref"))
    _validate_validation_binding(
        route.get("validation_binding"), understanding_binding, projection_ref
    )

    destinations = route.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        raise ContractError("destinations must be a non-empty list")
    if any(destination not in DESTINATIONS for destination in destinations):
        raise ContractError(f"destinations must be drawn from {sorted(DESTINATIONS)}")
    if len(destinations) != len(set(destinations)):
        raise ContractError("destinations must be unique")

    route_digest = _digest(route.get("route_digest"), "route_digest")
    if route_digest != canonical_route_digest(route):
        raise ContractError("route_digest is invalid")
    if route.get("route_id") != f"understanding-route-{route_digest[:16]}":
        raise ContractError("route_id is invalid")
    return route


def _load_json(path: str | Path) -> Any:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"input must be a regular non-symlink file: {candidate}")
    with candidate.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--input", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        validated = validate_paper_understanding_route(_load_json(args.input))
        print(json.dumps({"valid": True, "schema": validated["schema"]}, sort_keys=True))
        return 0
    except (ContractError, json.JSONDecodeError, OSError) as exc:
        print(f"paper understanding route validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
