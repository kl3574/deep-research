"""Small deterministic health check for the owner-bound appraisal contract."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from evidence_appraisal import (
    _digest,
    _relation_semantic,
    _review_file_projection,
    _review_semantic,
    build_appraisal_package,
    compute_attestation_binding_digest,
    create_reviewed_authority,
    finalize_appraisal,
    prepare_appraisal,
    validate_appraisal_package,
    validate_appraisal_set,
)
from fixtures.owner_fixture import (
    make_anonymous_owner_bundle,
    select_owner_attestation_binding,
)


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"


def _refresh_review(prepared: dict, review: dict) -> dict:
    review["prepared_request_digest"] = prepared["request_digest"]
    review["prepared_request_file_sha256"] = prepared["prepared_request_file_sha256"]
    review["owner_artifact_binding_digests"] = prepared[
        "owner_artifact_binding_digests"
    ]
    owner_digest, owner_binding = select_owner_attestation_binding(prepared)
    for relation in review["relation_appraisals"]:
        if (
            relation["attestation_refs"]
            and owner_binding["lineage_id"] not in relation["source_lineage"]
        ):
            relation["source_lineage"].append(owner_binding["lineage_id"])
        for attestation in relation["attestation_refs"]:
            attestation["owner_attestation_binding_digest"] = owner_digest
            attestation["binding_digest"] = compute_attestation_binding_digest(
                prepared,
                relation["claim_ref"],
                relation["evidence_ref"],
                attestation["locator_ref"],
                review["reviewer_context"],
            )
    targets = {}
    for relation in review["relation_appraisals"]:
        digest = _digest(_relation_semantic(relation))
        targets[(relation["claim_ref"], relation["evidence_ref"])] = {
            "claim_ref": relation["claim_ref"],
            "evidence_ref": relation["evidence_ref"],
            "appraisal_id": f"appraisal-{digest}",
            "semantic_digest": digest,
        }
    for item in review["challenges"] + review["targeted_evidence_needs"]:
        item["relation_ref"] = targets[
            (item["relation_ref"]["claim_ref"], item["relation_ref"]["evidence_ref"])
        ]
    review["independent_review_file_sha256"] = _digest(_review_file_projection(review))
    review["independent_review_digest"] = _digest(_review_semantic(review))
    return review


def main() -> int:
    request = json.loads(
        (FIXTURES / "minimal_request.json").read_text(encoding="utf-8")
    )
    review = json.loads(
        (FIXTURES / "minimal_independent_review.json").read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory(prefix="evidence-appraisal-quick-") as temporary:
        relation_key = request["relation_keys"][0]
        owner_locator = review["relation_appraisals"][0]["locator_refs"][0]["locator"]
        bindings, owner_bundle = make_anonymous_owner_bundle(
            Path(temporary),
            "fixturea",
            claim_specs=[
                {
                    "claim_id": relation_key["claim_ref"],
                    "evidence_ids": [relation_key["evidence_ref"]],
                    "exact_locator": owner_locator,
                }
            ],
        )
        prepared = prepare_appraisal(request, owner_artifact_bindings=bindings)
        review = _refresh_review(prepared, review)
        result = finalize_appraisal(prepared, review, owner_bundle)
        validate_appraisal_set(result)
        authority = create_reviewed_authority(
            prepared,
            review,
            result,
            {
                "reviewer_ref": "quick-authority",
                "review_method": "independent-check",
                "reviewed_at": "quick-time",
            },
            owner_bundle,
        )
        package = build_appraisal_package(
            result,
            prepared,
            review,
            authority,
            owner_bundle,
            expected_authority_sha256=authority["authority_digest"],
        )
        validate_appraisal_package(
            package,
            authority,
            prepared,
            review,
            owner_bundle,
            expected_authority_sha256=authority["authority_digest"],
        )
    print("Evidence appraisal approved-package quick validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
