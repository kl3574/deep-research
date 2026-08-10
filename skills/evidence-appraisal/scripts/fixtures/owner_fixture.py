"""Anonymous, valid learn-from-papers owner artifacts for appraisal tests.

The labels ``fixturea`` and ``fixtureb`` are fixture labels only.  They do not contain
or claim to represent any real paper.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


OWNER_VALIDATORS = {
    "source": "learn_from_papers.source_bundle.verify/v1",
    "dossier": "learn_from_papers.dossier.validate/v1",
    "report": "learn_from_papers.report_set.finalized/v2",
    "attestation": "learn_from_papers.external_attestation.verify/v1",
}
OWNER_STATUSES = {
    "source": "verified",
    "dossier": "finalized",
    "report": "finalized",
    "attestation": "passed",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _modules() -> tuple[Any, Any]:
    scripts = Path(__file__).resolve().parents[3] / "learn-from-papers" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    return importlib.import_module("paper_source_bundle"), importlib.import_module(
        "paper_reading_dossier"
    )


def _draft(
    bundle: dict[str, Any],
    source_path: Path,
    bundle_path: Path,
    phrase: str,
    dossier_module: Any,
    claim_specs: Sequence[Mapping[str, Any]],
    verification_mode: str,
) -> dict[str, Any]:
    source_text = source_path.read_text(encoding="utf-8")
    start = source_text.index(phrase)
    end = start + len(phrase)
    located = dossier_module.locate_span(
        bundle=str(bundle_path), page=1, start_char=start, end_char=end
    )
    claims: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    for spec in claim_specs:
        claim_id = str(spec["claim_id"])
        evidence_ids = [str(value) for value in spec["evidence_ids"]]
        exact_locator = str(spec["exact_locator"])
        claims.append(
            {
                "claim_id": claim_id,
                "hypothesis_id": "hyp-" + claim_id,
                "target_id": "target-" + claim_id,
                "statement": "The anonymous fixture method converges under stated assumptions.",
                "relation": "supports",
                "origin": "source",
                "scope": {
                    "assumptions": ["Lipschitz"],
                    "conditions": ["positive_step"],
                    "units": ["loss"],
                    "exclusions": [],
                },
                "verifier_status": "passed",
                "confidence": "medium",
                "evidence_ids": evidence_ids,
                "subquestion_id": "sq-1",
                "reconstruction_task_ids": [],
                "citation_chain": [],
                "verification": {
                    "mode": verification_mode,
                    "verifier_id": "external-verifier-001",
                },
            }
        )
        for evidence_id in evidence_ids:
            evidence_records.append(
                {
                    "evidence_id": evidence_id,
                    "claim_id": claim_id,
                    "hypothesis_id": "hyp-" + claim_id,
                    "target_id": "target-" + claim_id,
                    "page": 1,
                    "start_char": start,
                    "end_char": end,
                    "relation": "supports",
                    "verifier_status": "passed",
                    "exact_locator": exact_locator,
                    "card_type": "page",
                    "origin": "source",
                    "scope": {
                        "assumptions": ["Lipschitz"],
                        "conditions": ["positive_step"],
                        "units": ["loss"],
                        "exclusions": [],
                    },
                    "document_id": "doc-main",
                    "span_hash": located["span_hash"],
                    "span_id": located["span_id"],
                    "card": {},
                    "reconstruction_task_ids": [],
                    "citation_chain": [],
                }
            )
    return {
        "schema": dossier_module.SCHEMA,
        "schema_version": dossier_module.SCHEMA_VERSION,
        "producer": dossier_module.PRODUCER,
        "protocol_version": dossier_module.PROTOCOL_VERSION,
        "generated_at": "2026-08-10T00:00:00Z",
        "request_question_plan": {
            "request_text": "Validate an anonymous fixture claim.",
            "subquestions": [
                {
                    "subquestion_id": "sq-1",
                    "text": "Can the claim be reconstructed?",
                    "required": True,
                }
            ],
            "abstention_conditions": [],
        },
        "source_bundle": {
            "bundle_id": bundle["bundle_id"],
            "bundle_digest": bundle["bundle_digest"],
            "source_ref": source_path.name,
            "source_artifact_sha256": bundle["source"]["source_sha256"],
        },
        "review_source": {
            "source_id": "anonymous-source",
            "source_digest": "c" * 64,
            "acquisition_locator": "doi:10.0000/anonymous-fixture",
        },
        "network_ref": {
            "network_id": "anonymous-network",
            "snapshot_id": "anonymous-snapshot",
            "sha256": "a" * 64,
        },
        "review_request_set_id": "anonymous-request-set",
        "review_request_set_digest": "b" * 64,
        "review_request_id": "anonymous-request",
        "review_request_digest": "c" * 64,
        "access_level": "full_text",
        "inspection_depth": "evidence",
        "reconstruction_status": "planned",
        "embedded_documents": [
            {"document_id": "doc-main", "instruction": "Keep fixture context isolated."}
        ],
        "component_manifest": [
            {
                "component_id": "component-1",
                "name": "main",
                "artifact": source_path.name,
                "status": "covered",
                "inspected_units": 1,
                "covered_units": 1,
                "terminal_units": 0,
                "document_id": "doc-main",
            }
        ],
        "claims": claims,
        "evidence_records": evidence_records,
        "reconstruction_tasks": [],
        "correction_log": [],
        "unresolved_terminal_states": [],
    }


def _binding(
    role: str,
    artifact_schema: str,
    artifact_id: str,
    raw_path: Path,
    semantic_digest: str,
    lineage_id: str,
    *,
    status: str | None = None,
) -> dict[str, str]:
    return {
        "schema": "OwnerArtifactBinding/v1",
        "artifact_schema": artifact_schema,
        "role": role,
        "lineage_id": lineage_id,
        "id": artifact_id,
        "raw_file_sha256": _raw_sha(raw_path),
        "content_or_semantic_digest": semantic_digest,
        "owner_validator": OWNER_VALIDATORS[role],
        "status": OWNER_STATUSES[role] if status is None else status,
    }


def _receipt(path: Path, binding: dict[str, str]) -> Path:
    receipt_path = path.with_name(path.name + ".receipt.json")
    _write_json(
        receipt_path,
        {
            "schema": "OwnerArtifactValidationReceipt/v1",
            "binding_digest": _digest(binding),
            "raw_file_sha256": binding["raw_file_sha256"],
            "content_or_semantic_digest": binding["content_or_semantic_digest"],
            "owner_validator": binding["owner_validator"],
            "status": "passed",
        },
    )
    return receipt_path


def select_owner_attestation_binding(
    prepared: Mapping[str, Any],
    *,
    lineage_id: str | None = None,
    status: str = "passed",
    attestation_index: int | None = None,
) -> tuple[str, Mapping[str, Any]]:
    """Return one exact external owner-attestation binding for test review assembly."""
    bindings = prepared.get("owner_artifact_bindings")
    if not isinstance(bindings, list):
        raise ValueError("prepared owner_artifact_bindings are unavailable")
    candidates = [
        binding
        for binding in bindings
        if isinstance(binding, Mapping)
        and binding.get("role") == "attestation"
        and binding.get("status") == status
        and (lineage_id is None or binding.get("lineage_id") == lineage_id)
    ]
    if attestation_index is None and len(candidates) != 1:
        raise ValueError("fixture requires exactly one selected owner attestation")
    if attestation_index is not None:
        if type(attestation_index) is not int or not 0 <= attestation_index < len(
            candidates
        ):
            raise ValueError("fixture owner attestation index is unavailable")
        binding = candidates[attestation_index]
    else:
        binding = candidates[0]
    return _digest(binding), binding


def make_anonymous_owner_bundle(
    root: Path,
    label: str,
    *,
    verdict: str = "passed",
    verification_mode: str = "independent_source_check",
    claim_specs: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Create an anonymous final LFP source/dossier/report/attestation universe."""
    if verdict not in {"passed", "not_tested"}:
        raise ValueError("fixture attestation verdict must be passed or not_tested")
    if claim_specs is None:
        claim_specs = [
            {
                "claim_id": "claim-1",
                "evidence_ids": ["evidence-1"],
                "exact_locator": "p. 1",
            }
        ]
    normalized_specs: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    evidence_ids: set[str] = set()
    for index, raw in enumerate(claim_specs):
        if not isinstance(raw, Mapping):
            raise ValueError("fixture claim spec must be an object")
        claim_id = raw.get("claim_id")
        exact_locator = raw.get("exact_locator")
        raw_evidence_ids = raw.get("evidence_ids")
        if (
            not isinstance(claim_id, str)
            or not claim_id
            or not isinstance(exact_locator, str)
            or not exact_locator
            or not isinstance(raw_evidence_ids, Sequence)
            or isinstance(raw_evidence_ids, (str, bytes))
            or not raw_evidence_ids
            or claim_id in claim_ids
        ):
            raise ValueError("fixture claim spec is invalid")
        normalized_evidence_ids: list[str] = []
        for evidence_id in raw_evidence_ids:
            if (
                not isinstance(evidence_id, str)
                or not evidence_id
                or evidence_id in evidence_ids
            ):
                raise ValueError(
                    "fixture evidence IDs must be unique non-empty strings"
                )
            evidence_ids.add(evidence_id)
            normalized_evidence_ids.append(evidence_id)
        claim_ids.add(claim_id)
        normalized_specs.append(
            {
                "claim_id": claim_id,
                "evidence_ids": normalized_evidence_ids,
                "exact_locator": exact_locator,
            }
        )
    source_bundle, dossier_module = _modules()
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / f"{label}-anonymous.txt"
    phrase = "proves it converges"
    source_path.write_text(
        f"0123456789{phrase}. Anonymous fixture {label} supplementary material.",
        encoding="utf-8",
    )
    bundle_path = root / "source-bundle.json"
    manifest = source_bundle.build_bundle(
        source=str(source_path),
        output=str(bundle_path),
        generated_at="2026-08-10T00:00:00Z",
    )
    dossier = dossier_module.create_dossier(
        _draft(
            manifest,
            source_path,
            bundle_path,
            phrase,
            dossier_module,
            normalized_specs,
            verification_mode,
        ),
        bundle=str(bundle_path),
        source=str(source_path),
    )
    dossier_path = root / "reading-dossier.json"
    _write_json(dossier_path, dossier)
    verification_root = root / "verification"
    prepared_path = root / "prepared-report-set.json"
    finalized_path = root / "finalized-report-set.json"

    def run(argv: list[str]) -> None:
        if dossier_module.main(argv) != 0:
            raise RuntimeError(
                "learn-from-papers anonymous owner fixture generation failed"
            )

    run(
        [
            "prepare-attestations",
            "--input",
            str(dossier_path),
            "--output",
            str(prepared_path),
            "--bundle",
            str(bundle_path),
            "--source",
            str(source_path),
            "--producer-context-id",
            "fixture-producer",
            "--verification-root",
            str(verification_root),
            "--generated-at",
            "2026-08-10T00:00:00Z",
        ]
    )
    current_path = prepared_path
    prepared_report_set = json.loads(prepared_path.read_text(encoding="utf-8"))
    for index, report in enumerate(prepared_report_set["reports"]):
        output_path = root / f"attested-report-set-{index}.json"
        run(
            [
                "attest",
                "--input",
                str(current_path),
                "--output",
                str(output_path),
                "--verification-root",
                str(verification_root),
                "--report-id",
                report["report_id"],
                "--mode",
                verification_mode,
                "--verifier-id",
                "external-verifier-001",
                "--verdict",
                verdict,
                "--basis",
                "anonymous fixture review",
                "--verifier-context-id",
                "external-verifier-001",
            ]
        )
        current_path = output_path
    run(
        [
            "finalize-attestations",
            "--input",
            str(current_path),
            "--output",
            str(finalized_path),
            "--verification-root",
            str(verification_root),
        ]
    )
    finalized = json.loads(finalized_path.read_text(encoding="utf-8"))
    attestation_paths = [
        verification_root / report["verification"]["artifact_ref"]
        for report in finalized["reports"]
    ]
    attestations = [
        json.loads(path.read_text(encoding="utf-8")) for path in attestation_paths
    ]
    bindings = [
        _binding(
            "source",
            "PaperSourceBundle/v1",
            manifest["bundle_id"],
            bundle_path,
            manifest["bundle_digest"],
            label,
        ),
        _binding(
            "dossier",
            "PaperReadingDossier/v1",
            dossier["dossier_id"],
            dossier_path,
            dossier["dossier_digest"],
            label,
        ),
        _binding(
            "report",
            "PaperReadingReportSet/v2",
            finalized["report_set_id"],
            finalized_path,
            finalized["report_set_digest"],
            label,
        ),
        *[
            _binding(
                "attestation",
                "VerificationAttestation/v1",
                f"attestation-{_digest(attestation)}",
                attestation_path,
                _digest(attestation),
                label,
                status=verdict,
            )
            for attestation_path, attestation in zip(attestation_paths, attestations)
        ],
    ]
    receipts = [
        _receipt(path, binding)
        for path, binding in zip(
            [bundle_path, dossier_path, finalized_path, *attestation_paths], bindings
        )
    ]
    runtime = {
        "schema": "EvidenceAppraisalOwnerBundle/v1",
        "artifacts": [
            {
                "binding_digest": _digest(bindings[0]),
                "artifact_path": str(bundle_path),
                "verification_receipt_path": str(receipts[0]),
                "source_path": str(source_path),
                "bundle_path": None,
                "verification_root": None,
            },
            {
                "binding_digest": _digest(bindings[1]),
                "artifact_path": str(dossier_path),
                "verification_receipt_path": str(receipts[1]),
                "source_path": str(source_path),
                "bundle_path": str(bundle_path),
                "verification_root": None,
            },
            {
                "binding_digest": _digest(bindings[2]),
                "artifact_path": str(finalized_path),
                "verification_receipt_path": str(receipts[2]),
                "source_path": None,
                "bundle_path": None,
                "verification_root": str(verification_root),
            },
            *[
                {
                    "binding_digest": _digest(binding),
                    "artifact_path": str(attestation_path),
                    "verification_receipt_path": str(receipt),
                    "source_path": None,
                    "bundle_path": None,
                    "verification_root": None,
                }
                for binding, attestation_path, receipt in zip(
                    bindings[3:], attestation_paths, receipts[3:]
                )
            ],
        ],
    }
    return bindings, runtime
