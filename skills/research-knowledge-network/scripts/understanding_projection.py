#!/usr/bin/env python3
"""Create and verify a content-addressed PaperUnderstanding network projection."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECTION_SCHEMA = "UnderstandingNetworkProjection/v1"
PAPER_UNDERSTANDING_SCHEMA = "PaperUnderstanding/v1"
VALIDATION_SCHEMA = "PaperUnderstandingValidation/v1"
SCHEMA_VERSION = "1.0"
CONSUMER = "research-knowledge-network"
PROJECTION_PRODUCER = "research-knowledge-network.understanding-projection"
PROJECTION_SOURCE_PATHS = {
    "applicability": "applicability",
    "workflow": "workflow",
    "math": "mathematical_principles",
    "algorithm": "algorithmic_principles",
    "conclusion": "conclusion",
}
PROJECTION_STATUSES = {"answered", "not_applicable", "unresolved"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when a projection or its upstream binding fails closed."""


_PAPER_UNDERSTANDING_MODULE: Any | None = None


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_projection_digest(document: dict[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in document.items()
            if key not in {"projection_id", "projection_digest"}
        }
    )


def canonical_payload_digest(rows: list[dict[str, Any]]) -> str:
    return sha256_json(
        [
            {
                "projection_type": row["projection_type"],
                "source_path": row["source_path"],
                "status": row["status"],
                "payload_digest": row["payload_digest"],
            }
            for row in rows
        ]
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


def _load_paper_understanding_module() -> Any:
    global _PAPER_UNDERSTANDING_MODULE
    if _PAPER_UNDERSTANDING_MODULE is not None:
        return _PAPER_UNDERSTANDING_MODULE
    path = (
        Path(__file__).resolve().parents[2]
        / "learn-from-papers"
        / "scripts"
        / "paper_understanding.py"
    )
    if not path.is_file() or path.is_symlink():
        raise ContractError("learn-from-papers paper_understanding.py is required")
    spec = importlib.util.spec_from_file_location("rkn_paper_understanding", path)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot load PaperUnderstanding validator from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for function_name in (
        "validate_understanding",
        "validate_validation_record",
        "create_validation_record",
    ):
        if not hasattr(module, function_name):
            raise ContractError(
                f"learn-from-papers lacks required {function_name} producer contract"
            )
    _PAPER_UNDERSTANDING_MODULE = module
    return module


def _validate_upstream_artifacts(
    understanding: Any,
    validation_record: Any,
    *,
    source_bundle_path: str,
    source_path: str,
    dossier_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    live_paths = (source_bundle_path, source_path, dossier_path)
    if not all(isinstance(path, str) and path.strip() for path in live_paths):
        raise ContractError(
            "source bundle, source, and dossier paths are required for live validation"
        )
    module = _load_paper_understanding_module()
    try:
        validated_understanding = module.validate_understanding(
            understanding,
            require_identity=True,
            source_bundle_path=source_bundle_path,
            source_path=source_path,
            dossier_path=dossier_path,
        )
        validated_record = module.validate_validation_record(
            validation_record, understanding=validated_understanding
        )
        regenerated_record = module.create_validation_record(
            validated_understanding,
            source_bundle=source_bundle_path,
            source=source_path,
            dossier=dossier_path,
        )
    except ValueError as exc:
        raise ContractError(f"upstream PaperUnderstanding validation failed: {exc}") from exc
    if validated_understanding.get("schema") != PAPER_UNDERSTANDING_SCHEMA:
        raise ContractError("upstream understanding schema mismatch")
    if validated_record.get("schema") != VALIDATION_SCHEMA:
        raise ContractError("upstream validation record schema mismatch")
    for field in ("understanding_id", "understanding_digest"):
        if validated_record.get(field) != validated_understanding.get(field):
            raise ContractError(f"validation record {field} does not bind understanding")
    if validated_record.get("status") != "passed":
        raise ContractError("validation record status must be passed")
    if validated_record.get("source_binding_verified") is not True:
        raise ContractError("validation record must have source_binding_verified=true")
    if validated_record != regenerated_record:
        raise ContractError(
            "validation record does not exactly match deterministic live regeneration"
        )
    return validated_understanding, validated_record


def _understanding_binding(
    understanding: dict[str, Any], validation_record: dict[str, Any]
) -> dict[str, str]:
    return {
        "understanding_id": understanding["understanding_id"],
        "understanding_digest": understanding["understanding_digest"],
        "validation_record_id": validation_record["record_id"],
        "validation_record_digest": validation_record["record_digest"],
    }


def create_understanding_network_projection(
    understanding: Any,
    validation_record: Any,
    *,
    source_bundle_path: str,
    source_path: str,
    dossier_path: str,
) -> dict[str, Any]:
    validated_understanding, validated_record = _validate_upstream_artifacts(
        understanding,
        validation_record,
        source_bundle_path=source_bundle_path,
        source_path=source_path,
        dossier_path=dossier_path,
    )
    binding = _understanding_binding(validated_understanding, validated_record)
    rows: list[dict[str, Any]] = []
    for projection_type, source_path in PROJECTION_SOURCE_PATHS.items():
        payload = copy.deepcopy(validated_understanding[source_path])
        payload_digest = sha256_json(payload)
        rows.append(
            {
                "projection_type": projection_type,
                "source_path": source_path,
                "status": payload["status"],
                "payload": payload,
                "payload_digest": payload_digest,
                "basis_refs": [
                    {
                        "ref_type": "paper_understanding_domain",
                        "understanding_id": binding["understanding_id"],
                        "understanding_digest": binding["understanding_digest"],
                        "source_path": source_path,
                        "payload_digest": payload_digest,
                    }
                ],
                "provenance": {
                    "producer": PROJECTION_PRODUCER,
                    "copy_mode": "verbatim",
                    "validation_record_id": binding["validation_record_id"],
                    "validation_record_digest": binding[
                        "validation_record_digest"
                    ],
                },
            }
        )
    projection = {
        "schema": PROJECTION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "projection_id": "",
        "projection_digest": "",
        "payload_digest": canonical_payload_digest(rows),
        "understanding_binding": binding,
        "projections": rows,
        "consumer": CONSUMER,
        "mutation_authorized": False,
    }
    projection["projection_digest"] = canonical_projection_digest(projection)
    projection["projection_id"] = (
        f"understanding-projection-{projection['projection_digest'][:16]}"
    )
    return _validate_projection_envelope(projection)


def _validate_projection_envelope(value: Any) -> dict[str, Any]:
    projection = _object(value, "understanding projection")
    expected_keys = {
        "schema",
        "schema_version",
        "projection_id",
        "projection_digest",
        "payload_digest",
        "understanding_binding",
        "projections",
        "consumer",
        "mutation_authorized",
    }
    if set(projection) != expected_keys:
        raise ContractError(
            f"understanding projection must contain exactly {sorted(expected_keys)}"
        )
    if projection.get("schema") != PROJECTION_SCHEMA:
        raise ContractError(f"schema must equal {PROJECTION_SCHEMA}")
    if projection.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"schema_version must equal {SCHEMA_VERSION}")
    if projection.get("consumer") != CONSUMER:
        raise ContractError(f"consumer must equal {CONSUMER}")
    if projection.get("mutation_authorized") is not False:
        raise ContractError("mutation_authorized must be false")

    binding = _object(projection.get("understanding_binding"), "understanding_binding")
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
        raise ContractError("understanding_binding.understanding_id is not content-derived")
    validation_record_digest = _digest(
        binding.get("validation_record_digest"),
        "understanding_binding.validation_record_digest",
    )
    if binding.get("validation_record_id") != (
        f"paper-understanding-validation-{validation_record_digest[:16]}"
    ):
        raise ContractError(
            "understanding_binding.validation_record_id is not content-derived"
        )

    rows = projection.get("projections")
    if not isinstance(rows, list) or len(rows) != len(PROJECTION_SOURCE_PATHS):
        raise ContractError("projections must contain each of the five projection types")
    observed_order: list[str] = []
    for index, raw_row in enumerate(rows):
        row = _object(raw_row, f"projections[{index}]")
        if set(row) != {
            "projection_type",
            "source_path",
            "status",
            "payload",
            "payload_digest",
            "basis_refs",
            "provenance",
        }:
            raise ContractError(f"projections[{index}] has an unsupported field set")
        projection_type = _text(
            row.get("projection_type"), f"projections[{index}].projection_type"
        )
        if projection_type not in PROJECTION_SOURCE_PATHS:
            raise ContractError(f"projections[{index}].projection_type is unsupported")
        observed_order.append(projection_type)
        source_path = PROJECTION_SOURCE_PATHS[projection_type]
        if row.get("source_path") != source_path:
            raise ContractError(
                f"projections[{index}].source_path does not match projection_type"
            )
        payload = _object(row.get("payload"), f"projections[{index}].payload")
        status = row.get("status")
        if status not in PROJECTION_STATUSES or payload.get("status") != status:
            raise ContractError(
                f"projections[{index}].status must equal the upstream payload status"
            )
        payload_digest = _digest(
            row.get("payload_digest"), f"projections[{index}].payload_digest"
        )
        if payload_digest != sha256_json(payload):
            raise ContractError(f"projections[{index}].payload_digest is invalid")

        basis_refs = row.get("basis_refs")
        if not isinstance(basis_refs, list) or len(basis_refs) != 1:
            raise ContractError(f"projections[{index}].basis_refs must have one typed ref")
        basis = _object(basis_refs[0], f"projections[{index}].basis_refs[0]")
        expected_basis = {
            "ref_type": "paper_understanding_domain",
            "understanding_id": binding["understanding_id"],
            "understanding_digest": binding["understanding_digest"],
            "source_path": source_path,
            "payload_digest": payload_digest,
        }
        if basis != expected_basis:
            raise ContractError(f"projections[{index}].basis_refs are not source-bound")

        provenance = _object(row.get("provenance"), f"projections[{index}].provenance")
        expected_provenance = {
            "producer": PROJECTION_PRODUCER,
            "copy_mode": "verbatim",
            "validation_record_id": binding["validation_record_id"],
            "validation_record_digest": binding["validation_record_digest"],
        }
        if provenance != expected_provenance:
            raise ContractError(f"projections[{index}].provenance is not validation-bound")

    if observed_order != list(PROJECTION_SOURCE_PATHS):
        raise ContractError("projection types must appear exactly once in canonical order")
    payload_digest = _digest(projection.get("payload_digest"), "payload_digest")
    if payload_digest != canonical_payload_digest(rows):
        raise ContractError("payload_digest is invalid")
    projection_digest = _digest(
        projection.get("projection_digest"), "projection_digest"
    )
    if projection_digest != canonical_projection_digest(projection):
        raise ContractError("projection_digest is invalid")
    if projection.get("projection_id") != (
        f"understanding-projection-{projection_digest[:16]}"
    ):
        raise ContractError("projection_id is invalid")
    return projection


def validate_projection_against_sources(
    value: Any,
    understanding: Any,
    validation_record: Any,
    *,
    source_bundle_path: str,
    source_path: str,
    dossier_path: str,
) -> dict[str, Any]:
    projection = _validate_projection_envelope(value)
    expected = create_understanding_network_projection(
        understanding,
        validation_record,
        source_bundle_path=source_bundle_path,
        source_path=source_path,
        dossier_path=dossier_path,
    )
    if projection != expected:
        raise ContractError(
            "projection is internally valid but is not the verbatim source projection"
        )
    return projection


def validate_understanding_network_projection(
    value: Any,
    understanding: Any,
    validation_record: Any,
    *,
    source_bundle_path: str,
    source_path: str,
    dossier_path: str,
) -> dict[str, Any]:
    """Public validation always reprojects from authoritative upstream artifacts."""
    return validate_projection_against_sources(
        value,
        understanding,
        validation_record,
        source_bundle_path=source_bundle_path,
        source_path=source_path,
        dossier_path=dossier_path,
    )


def _load_json(path: str | Path) -> Any:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(f"input must be a regular non-symlink file: {candidate}")
    with candidate.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    if target.is_symlink():
        raise ContractError(f"refusing symlink output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(canonical_bytes(value) + b"\n")
    temporary.replace(target)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create-projection", help="create a projection from validated upstream files"
    )
    create.add_argument("--understanding", required=True)
    create.add_argument("--validation-record", required=True)
    create.add_argument("--source-bundle", required=True)
    create.add_argument("--source", required=True)
    create.add_argument("--dossier", required=True)
    create.add_argument("--output", required=True)
    validate = commands.add_parser(
        "validate", help="rebuild and compare a projection against upstream files"
    )
    validate.add_argument("--input", required=True)
    validate.add_argument("--understanding", required=True)
    validate.add_argument("--validation-record", required=True)
    validate.add_argument("--source-bundle", required=True)
    validate.add_argument("--source", required=True)
    validate.add_argument("--dossier", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        understanding = _load_json(args.understanding)
        validation_record = _load_json(args.validation_record)
        if args.command == "create-projection":
            projection = create_understanding_network_projection(
                understanding,
                validation_record,
                source_bundle_path=args.source_bundle,
                source_path=args.source,
                dossier_path=args.dossier,
            )
            _write_json(args.output, projection)
        else:
            projection = validate_projection_against_sources(
                _load_json(args.input),
                understanding,
                validation_record,
                source_bundle_path=args.source_bundle,
                source_path=args.source,
                dossier_path=args.dossier,
            )
            print(
                json.dumps(
                    {"valid": True, "schema": projection["schema"]}, sort_keys=True
                )
            )
        return 0
    except (ContractError, json.JSONDecodeError, OSError) as exc:
        print(f"understanding projection validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
