from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidence_appraisal import (
    ContractError,
    _validate_locator_atom,
    finalize_appraisal,
    prepare_appraisal,
    reconcile_appraisal,
    validate_appraisal_set,
)
from fixtures.owner_fixture import (
    make_anonymous_owner_bundle,
    select_owner_attestation_binding,
)


FIXTURES = Path(__file__).with_name("fixtures")


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def refresh_review(prepared: dict, review: dict) -> dict:
    import evidence_appraisal as ea

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
            attestation["binding_digest"] = ea.compute_attestation_binding_digest(
                prepared,
                relation["claim_ref"],
                relation["evidence_ref"],
                attestation["locator_ref"],
                review["reviewer_context"],
            )
    targets = {}
    for relation in review["relation_appraisals"]:
        digest = ea._digest(ea._relation_semantic(relation))
        targets[(relation["claim_ref"], relation["evidence_ref"])] = {
            "claim_ref": relation["claim_ref"],
            "evidence_ref": relation["evidence_ref"],
            "appraisal_id": f"appraisal-{digest}",
            "semantic_digest": digest,
        }
    for draft in review["challenges"] + review["targeted_evidence_needs"]:
        draft["relation_ref"] = targets[
            (draft["relation_ref"]["claim_ref"], draft["relation_ref"]["evidence_ref"])
        ]
    review["independent_review_file_sha256"] = ea._digest(
        ea._review_file_projection(review)
    )
    review["independent_review_digest"] = ea._digest(ea._review_semantic(review))
    return review


def test_public_seam_prepares_and_finalizes_claim_evidence_relations(
    tmp_path: Path,
) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(tmp_path / "fixturea", "fixturea")
    prepared = prepare_appraisal(
        load_fixture("minimal_request.json"), owner_artifact_bindings=bindings
    )
    result = finalize_appraisal(
        prepared,
        refresh_review(prepared, load_fixture("minimal_independent_review.json")),
        owner_bundle,
    )

    assert result["schema"] == "EvidenceAppraisalSet/v1"
    assert len(result["relation_appraisals"]) == 1
    assert result["relation_appraisals"][0]["schema"] == "EvidenceAppraisal/v1"
    assert validate_appraisal_set(result) == result


def test_public_seam_fails_closed() -> None:
    with pytest.raises(ContractError):
        prepare_appraisal({"schema": "EvidenceAppraisalRequest/v1"})


def test_locator_accepts_exact_lfp_page_character_span() -> None:
    locator = {
        "source_ref": "paper-source-bundle-example",
        "locator": "p.4 [1767:1937]",
    }
    assert _validate_locator_atom(locator, "locator") == (
        "paper-source-bundle-example",
        "p.4 [1767:1937]",
    )


@pytest.mark.parametrize(
    "locator",
    [
        "p.4 [1937:1767]",
        "p.4 [1767:1767]",
        "p.4 [1767:1937]; p.5 [286:618]",
        "p.4 [1767:1937] and p.5 [286:618]",
        "p.4 [1767:1937]/p.5 [286:618]",
    ],
)
def test_locator_rejects_invalid_or_compound_lfp_page_character_span(
    locator: str,
) -> None:
    with pytest.raises(ContractError):
        _validate_locator_atom(
            {"source_ref": "paper-source-bundle-example", "locator": locator},
            "locator",
        )


def test_public_seam_reconciles_by_supersession_not_mutation(tmp_path: Path) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(tmp_path / "fixturea", "fixturea")
    prepared = prepare_appraisal(
        load_fixture("minimal_request.json"), owner_artifact_bindings=bindings
    )
    prior = finalize_appraisal(
        prepared,
        refresh_review(prepared, load_fixture("minimal_independent_review.json")),
        owner_bundle,
    )
    next_bindings, next_owner_bundle = make_anonymous_owner_bundle(
        tmp_path / "fixtureb", "fixtureb"
    )
    return_set = load_fixture("minimal_return_set.json")
    return_set["prior_cycle_ref"] = {
        "appraisal_set_id": prior["appraisal_set_id"],
        "appraisal_set_digest": prior["appraisal_set_digest"],
        "cycle": prior["cycle"],
    }
    next_request = {
        "schema": "EvidenceAppraisalRequest/v1",
        "appraisal_set_id": prior["appraisal_set_id"],
        "cycle": prior["cycle"] + 1,
        "prior_cycle_ref": return_set["prior_cycle_ref"],
        "relation_keys": return_set["relation_keys"],
    }
    next_prepared = prepare_appraisal(
        next_request, owner_artifact_bindings=next_bindings
    )
    next_review = load_fixture("minimal_return_review.json")
    next_review["relation_appraisals"][0]["supersedes_prior_appraisal_ref"] = {
        "appraisal_set_id": prior["appraisal_set_id"],
        "appraisal_set_digest": prior["appraisal_set_digest"],
        "cycle": prior["cycle"],
        "appraisal_id": prior["relation_appraisals"][0]["appraisal_id"],
        "semantic_digest": prior["relation_appraisals"][0]["semantic_digest"],
    }
    result = reconcile_appraisal(
        prior,
        next_prepared,
        return_set,
        refresh_review(next_prepared, next_review),
        next_owner_bundle,
    )

    assert result["cycle"] == prior["cycle"] + 1
    assert (
        result["prior_cycle_ref"]["appraisal_set_digest"]
        == prior["appraisal_set_digest"]
    )
    assert (
        result["relation_appraisals"][: len(prior["relation_appraisals"])]
        == prior["relation_appraisals"]
    )
