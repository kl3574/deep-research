from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import evidence_appraisal as ea
from fixtures.owner_fixture import (
    make_anonymous_owner_bundle,
    select_owner_attestation_binding,
)


FIXTURES = Path(__file__).parents[1] / "scripts" / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def refresh_review(
    prepared: dict,
    review: dict,
    *,
    lineage_id: str | None = None,
    status: str = "passed",
    attestation_index: int | None = None,
) -> dict:
    review["prepared_request_digest"] = prepared["request_digest"]
    review["prepared_request_file_sha256"] = prepared["prepared_request_file_sha256"]
    review["owner_artifact_binding_digests"] = prepared[
        "owner_artifact_binding_digests"
    ]
    owner_digest, owner_binding = select_owner_attestation_binding(
        prepared,
        lineage_id=lineage_id,
        status=status,
        attestation_index=attestation_index,
    )
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
        identity = (
            draft["relation_ref"]["claim_ref"],
            draft["relation_ref"]["evidence_ref"],
        )
        draft["relation_ref"] = targets[identity]
    return rehash_review(review)


def rehash_review(review: dict) -> dict:
    review["independent_review_file_sha256"] = ea._digest(
        ea._review_file_projection(review)
    )
    review["independent_review_digest"] = ea._digest(ea._review_semantic(review))
    return review


def baseline(tmp_path: Path, label: str = "fixturea") -> tuple[dict, dict, dict, dict]:
    bindings, owner_bundle = make_anonymous_owner_bundle(tmp_path / label, label)
    prepared = ea.prepare_appraisal(
        load("minimal_request.json"), owner_artifact_bindings=bindings
    )
    review = refresh_review(prepared, load("minimal_independent_review.json"))
    return (
        prepared,
        review,
        ea.finalize_appraisal(prepared, review, owner_bundle),
        owner_bundle,
    )


def subject_matched_request_review(
    claim_ref: str,
    evidence_ref: str,
    locator: str = "pages/page-0001.txt#char=10-29",
) -> tuple[dict, dict]:
    request = load("minimal_request.json")
    request["relation_keys"] = [{"claim_ref": claim_ref, "evidence_ref": evidence_ref}]
    review = load("minimal_independent_review.json")
    relation = review["relation_appraisals"][0]
    relation["claim_ref"] = claim_ref
    relation["evidence_ref"] = evidence_ref
    locator_ref = {"source_ref": "source-1", "locator": locator}
    relation["locator_refs"] = [locator_ref]
    relation["attestation_refs"][0]["locator_ref"] = copy.deepcopy(locator_ref)
    for item in review["challenges"] + review["targeted_evidence_needs"]:
        item["relation_ref"]["claim_ref"] = claim_ref
        item["relation_ref"]["evidence_ref"] = evidence_ref
    return request, review


def approved_package(tmp_path: Path) -> tuple[dict, dict, dict, dict, dict, dict]:
    prepared, review, appraisal_set, owner_bundle = baseline(tmp_path)
    authority = ea.create_reviewed_authority(
        prepared,
        review,
        appraisal_set,
        {
            "reviewer_ref": "authority-1",
            "review_method": "independent-check",
            "reviewed_at": "time-a",
        },
        owner_bundle,
    )
    package = ea.build_appraisal_package(
        appraisal_set,
        prepared,
        review,
        authority,
        owner_bundle,
        expected_authority_sha256=authority["authority_digest"],
    )
    return prepared, review, appraisal_set, owner_bundle, authority, package


def merge_owner_bundles(*bundles: dict) -> dict:
    return {
        "schema": "EvidenceAppraisalOwnerBundle/v1",
        "artifacts": [item for bundle in bundles for item in bundle["artifacts"]],
    }


def test_authority_package_replays_and_self_seal_does_not(tmp_path: Path) -> None:
    prepared, review, _, owner_bundle, authority, package = approved_package(tmp_path)
    assert (
        ea.validate_appraisal_package(
            package,
            authority,
            prepared,
            review,
            owner_bundle,
            expected_authority_sha256=authority["authority_digest"],
        )
        == package
    )
    with pytest.raises(ea.ContractError, match="actual approval"):
        ea.validate_appraisal_package(
            package,
            None,
            prepared,
            review,
            owner_bundle,
            expected_authority_sha256=authority["authority_digest"],
        )
    with pytest.raises(ea.ContractError, match="external trust boundary"):
        ea.validate_appraisal_package(
            package,
            authority,
            prepared,
            review,
            owner_bundle,
            expected_authority_sha256="0" * 64,
        )


def test_package_tamper_cannot_reuse_original_approval(tmp_path: Path) -> None:
    prepared, review, _, owner_bundle, authority, package = approved_package(tmp_path)
    tampered = copy.deepcopy(package)
    tampered["challenges"][0]["statement"] = "tampered"
    tampered["package_digest"] = ea._digest(ea._package_core(tampered))
    tampered["seal"]["digest"] = tampered["package_digest"]
    with pytest.raises(ea.ContractError, match="does not replay|candidate"):
        ea.validate_appraisal_package(
            tampered,
            authority,
            prepared,
            review,
            owner_bundle,
            expected_authority_sha256=authority["authority_digest"],
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda review: review["relation_appraisals"][0].__setitem__(
                "attestation_refs", []
            ),
            "passed decisive",
        ),
        (
            lambda review: review["relation_appraisals"][0]["attestation_refs"][
                0
            ].__setitem__("binding_digest", "0" * 64),
            "opaque or unrelated",
        ),
        (
            lambda review: review["relation_appraisals"][0][
                "domain_verdicts"
            ].__setitem__("analysis", "defeated"),
            "defeated domain",
        ),
        (
            lambda review: review["relation_appraisals"][0][
                "domain_verdicts"
            ].__setitem__("analysis", "unresolved"),
            "key domain",
        ),
    ],
)
def test_decisive_adversarial_cases_fail_closed(
    tmp_path: Path, mutate, message: str
) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(
        tmp_path / "fixturea", "fixturea"
    )
    prepared = ea.prepare_appraisal(
        load("minimal_request.json"), owner_artifact_bindings=bindings
    )
    review = refresh_review(prepared, load("minimal_independent_review.json"))
    mutate(review)
    if message == "opaque or unrelated":
        rehash_review(review)
    else:
        refresh_review(prepared, review)
    with pytest.raises(ea.ContractError, match=message):
        ea.finalize_appraisal(prepared, review, owner_bundle)


def test_failed_attestation_requires_same_atom_bound_pass(tmp_path: Path) -> None:
    prepared, review, _, owner_bundle = baseline(tmp_path)
    relation = review["relation_appraisals"][0]
    failed = copy.deepcopy(relation["attestation_refs"][0])
    failed.update(
        {
            "attestation_id": "attestation-failed",
            "state": "failed",
            "decisive": False,
            "supersedes_ref": None,
        }
    )
    passed = copy.deepcopy(relation["attestation_refs"][0])
    passed.update(
        {"attestation_id": "attestation-pass", "supersedes_ref": "attestation-failed"}
    )
    passed["locator_ref"] = {"source_ref": "source-1", "locator": "p. 2"}
    relation["locator_refs"].append(copy.deepcopy(passed["locator_ref"]))
    relation["attestation_refs"] = [failed, passed]
    refresh_review(prepared, review)
    with pytest.raises(ea.ContractError, match="exact same atom"):
        ea.finalize_appraisal(prepared, review, owner_bundle)


@pytest.mark.parametrize(
    "locator",
    [
        "p.1/p.2",
        "pages/page-0001.txt #char=10-80",
        "pages/page-0001.txt#char=10-80&line=1",
        "p. 1 and p. 2",
        "lines 1-3",
        "row 1–3",
        "section 1-3",
    ],
)
def test_locator_counterexamples_fail_closed(tmp_path: Path, locator: str) -> None:
    prepared, review, _, owner_bundle = baseline(tmp_path)
    review["relation_appraisals"][0]["locator_refs"][0]["locator"] = locator
    rehash_review(review)
    with pytest.raises(ea.ContractError, match="locator"):
        ea.finalize_appraisal(prepared, review, owner_bundle)


def test_safe_path_fragment_locator_is_one_valid_atom_and_pair_is_exact(
    tmp_path: Path,
) -> None:
    prepared, review, _, owner_bundle = baseline(tmp_path)
    relation = review["relation_appraisals"][0]
    locator = "pages/page-0001.txt#char=10-29"
    relation["locator_refs"][0]["locator"] = locator
    relation["attestation_refs"][0]["locator_ref"]["locator"] = locator
    refresh_review(prepared, review)
    assert (
        ea.finalize_appraisal(prepared, review, owner_bundle)["relation_appraisals"][0][
            "locator_refs"
        ][0]["locator"]
        == locator
    )
    review = refresh_review(prepared, load("minimal_independent_review.json"))
    review["targeted_evidence_needs"][0]["adversarial_observation_pair"]["refute"][
        "value_or_state"
    ] = "999"
    refresh_review(prepared, review)
    with pytest.raises(ea.ContractError, match="one exact value_or_state"):
        ea.finalize_appraisal(prepared, review, owner_bundle)


def test_scholar_need_requires_semantically_sealed_domain_anchors(
    tmp_path: Path,
) -> None:
    prepared, review, _, owner_bundle = baseline(tmp_path)
    need = review["targeted_evidence_needs"][0]
    need["route"] = "scholar_discovery"
    need["domain_anchors"] = ["randomized controlled trial", "calibrated endpoint"]
    refresh_review(prepared, review)
    result = ea.finalize_appraisal(prepared, review, owner_bundle)
    assert result["targeted_evidence_need_semantic_digests"]
    need["domain_anchors"] = ["only one"]
    refresh_review(prepared, review)
    with pytest.raises(ea.ContractError, match="domain anchors"):
        ea.finalize_appraisal(prepared, review, owner_bundle)


@pytest.mark.parametrize("label", ["fixturea", "fixtureb"])
def test_anonymous_valid_owner_universes_replay_through_lfp(
    tmp_path: Path, label: str
) -> None:
    prepared, review, appraisal_set, owner_bundle = baseline(tmp_path, label)
    assert ea.finalize_appraisal(prepared, review, owner_bundle) == appraisal_set


def test_multilineage_owner_bundle_replays_all_lines_and_allows_unused_terminal(
    tmp_path: Path,
) -> None:
    fixturec_bindings, fixturec_bundle = make_anonymous_owner_bundle(
        tmp_path / "fixturec", "fixturec"
    )
    fixturea_bindings, fixturea_bundle = make_anonymous_owner_bundle(
        tmp_path / "fixturea", "fixturea", verdict="not_tested"
    )
    bindings = fixturec_bindings + fixturea_bindings
    owner_bundle = merge_owner_bundles(fixturec_bundle, fixturea_bundle)
    prepared = ea.prepare_appraisal(
        load("minimal_request.json"), owner_artifact_bindings=bindings
    )
    review = refresh_review(
        prepared, load("minimal_independent_review.json"), lineage_id="fixturec"
    )
    appraisal_set = ea.finalize_appraisal(prepared, review, owner_bundle)
    authority = ea.create_reviewed_authority(
        prepared,
        review,
        appraisal_set,
        {
            "reviewer_ref": "authority-multilineage",
            "review_method": "complete-owner-replay",
            "reviewed_at": "time-multilineage",
        },
        owner_bundle,
    )
    package = ea.build_appraisal_package(
        appraisal_set,
        prepared,
        review,
        authority,
        owner_bundle,
        expected_authority_sha256=authority["authority_digest"],
    )
    assert (
        ea.validate_appraisal_package(
            package,
            authority,
            prepared,
            review,
            owner_bundle,
            expected_authority_sha256=authority["authority_digest"],
        )
        == package
    )
    fixturea_attestations = {
        ea._digest(binding)
        for binding in fixturea_bindings
        if binding["role"] == "attestation"
    }
    missing = copy.deepcopy(owner_bundle)
    missing["artifacts"] = [
        item
        for item in missing["artifacts"]
        if item["binding_digest"] not in fixturea_attestations
    ]
    with pytest.raises(ea.ContractError, match="missing|exact owner"):
        ea.finalize_appraisal(prepared, review, missing)


def test_owner_attestation_cannot_cross_lineage_or_select_terminal_not_tested(
    tmp_path: Path,
) -> None:
    fixturec_bindings, fixturec_bundle = make_anonymous_owner_bundle(
        tmp_path / "fixturec", "fixturec"
    )
    fixturea_bindings, fixturea_bundle = make_anonymous_owner_bundle(
        tmp_path / "fixturea", "fixturea"
    )
    prepared = ea.prepare_appraisal(
        load("minimal_request.json"),
        owner_artifact_bindings=fixturec_bindings + fixturea_bindings,
    )
    review = refresh_review(
        prepared, load("minimal_independent_review.json"), lineage_id="fixturec"
    )
    fixturea_digest, _ = select_owner_attestation_binding(
        prepared, lineage_id="fixturea"
    )
    review["relation_appraisals"][0]["attestation_refs"][0][
        "owner_attestation_binding_digest"
    ] = fixturea_digest
    rehash_review(review)
    with pytest.raises(ea.ContractError, match="source_lineage"):
        ea.finalize_appraisal(
            prepared, review, merge_owner_bundles(fixturec_bundle, fixturea_bundle)
        )

    terminal_bindings, terminal_bundle = make_anonymous_owner_bundle(
        tmp_path / "terminal", "terminal", verdict="not_tested"
    )
    terminal_prepared = ea.prepare_appraisal(
        load("minimal_request.json"), owner_artifact_bindings=terminal_bindings
    )
    terminal_review = refresh_review(
        terminal_prepared,
        load("minimal_independent_review.json"),
        lineage_id="terminal",
        status="not_tested",
    )
    with pytest.raises(ea.ContractError, match="external passed"):
        ea.finalize_appraisal(terminal_prepared, terminal_review, terminal_bundle)


def test_selected_owner_attestation_rejects_unrelated_passed_subject_same_lineage(
    tmp_path: Path,
) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(
        tmp_path / "same-lineage",
        "same-lineage",
        claim_specs=[
            {
                "claim_id": "claim-1",
                "evidence_ids": ["evidence-1"],
                "exact_locator": "p. 1",
            },
            {
                "claim_id": "unrelated-claim",
                "evidence_ids": ["unrelated-evidence"],
                "exact_locator": "p. 1",
            },
        ],
    )
    prepared = ea.prepare_appraisal(
        load("minimal_request.json"), owner_artifact_bindings=bindings
    )
    review = refresh_review(
        prepared,
        load("minimal_independent_review.json"),
        attestation_index=1,
    )
    with pytest.raises(ea.ContractError, match="owner subject"):
        ea.finalize_appraisal(prepared, review, owner_bundle)


def test_noneligible_passed_owner_cannot_authorize_qualified_relation(
    tmp_path: Path,
) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(
        tmp_path / "noneligible",
        "noneligible",
        verification_mode="same_context_diagnostic",
    )
    prepared = ea.prepare_appraisal(
        load("minimal_request.json"), owner_artifact_bindings=bindings
    )
    review = load("minimal_independent_review.json")
    relation = review["relation_appraisals"][0]
    relation["overall"] = "qualified_only"
    relation["domain_verdicts"]["design"] = "concern"
    relation["attestation_refs"][0]["decisive"] = False
    refresh_review(prepared, review)
    with pytest.raises(ea.ContractError, match="owner-eligible"):
        ea.finalize_appraisal(prepared, review, owner_bundle)


def test_decisive_flag_cannot_self_upgrade_noneligible_owner(
    tmp_path: Path,
) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(
        tmp_path / "self-upgrade",
        "self-upgrade",
        verification_mode="same_context_diagnostic",
    )
    prepared = ea.prepare_appraisal(
        load("minimal_request.json"), owner_artifact_bindings=bindings
    )
    review = refresh_review(prepared, load("minimal_independent_review.json"))
    with pytest.raises(ea.ContractError, match="owner-eligible"):
        ea.finalize_appraisal(prepared, review, owner_bundle)


@pytest.mark.parametrize(
    ("label", "claim_ref", "evidence_ref"),
    [
        ("fixturea", "fixturea-c02", "fixturea-evidence-c02"),
        ("fixtureb", "fixtureb-c03", "fixtureb-evidence-c03"),
        ("fixturec", "fixturec-c08", "fixturec-evidence-c08"),
    ],
)
def test_owner_subject_coverage_accepts_published_case_shapes(
    tmp_path: Path, label: str, claim_ref: str, evidence_ref: str
) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(
        tmp_path / label,
        label,
        claim_specs=[
            {
                "claim_id": claim_ref,
                "evidence_ids": [evidence_ref],
                "exact_locator": "p. 1",
            }
        ],
    )
    request, review = subject_matched_request_review(claim_ref, evidence_ref)
    prepared = ea.prepare_appraisal(request, owner_artifact_bindings=bindings)
    if label == "fixtureb":
        relation = review["relation_appraisals"][0]
        failed = copy.deepcopy(relation["attestation_refs"][0])
        failed.update(
            {
                "attestation_id": "fixtureb-c03-failed",
                "state": "failed",
                "decisive": False,
                "supersedes_ref": None,
            }
        )
        passed = copy.deepcopy(relation["attestation_refs"][0])
        passed.update(
            {
                "attestation_id": "fixtureb-c03-passed",
                "supersedes_ref": "fixtureb-c03-failed",
            }
        )
        relation["attestation_refs"] = [failed, passed]
    refresh_review(prepared, review)
    assert ea.finalize_appraisal(prepared, review, owner_bundle)["relation_appraisals"]


def test_fixturec_unfinalized_report_cannot_pass_complete_scope(tmp_path: Path) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(
        tmp_path / "fixturec", "fixturec"
    )
    bad_bindings = copy.deepcopy(bindings)
    report_entry = owner_bundle["artifacts"][2]
    prepared_report_path = Path(report_entry["artifact_path"]).with_name(
        "prepared-report-set.json"
    )
    prepared_report = json.loads(prepared_report_path.read_text(encoding="utf-8"))
    bad_bindings[2]["id"] = prepared_report["report_set_id"]
    bad_bindings[2]["raw_file_sha256"] = hashlib.sha256(
        prepared_report_path.read_bytes()
    ).hexdigest()
    bad_bindings[2]["content_or_semantic_digest"] = prepared_report["report_set_digest"]
    receipt = {
        "schema": "OwnerArtifactValidationReceipt/v1",
        "binding_digest": ea._digest(bad_bindings[2]),
        "raw_file_sha256": bad_bindings[2]["raw_file_sha256"],
        "content_or_semantic_digest": bad_bindings[2]["content_or_semantic_digest"],
        "owner_validator": bad_bindings[2]["owner_validator"],
        "status": "passed",
    }
    bad_receipt = prepared_report_path.with_name("fixturec-invalid-report.receipt.json")
    bad_receipt.write_bytes(ea.canonical_json_bytes(receipt) + b"\n")
    owner_bundle["artifacts"][2]["binding_digest"] = ea._digest(bad_bindings[2])
    owner_bundle["artifacts"][2]["artifact_path"] = str(prepared_report_path)
    owner_bundle["artifacts"][2]["verification_receipt_path"] = str(bad_receipt)
    prepared = ea.prepare_appraisal(
        load("minimal_request.json"), owner_artifact_bindings=bad_bindings
    )
    review = refresh_review(prepared, load("minimal_independent_review.json"))
    with pytest.raises(ea.ContractError, match="owner report validator rejected"):
        ea.finalize_appraisal(prepared, review, owner_bundle)


def test_owner_delete_swap_reseal_and_raw_newline_all_fail(tmp_path: Path) -> None:
    prepared, review, _, owner_bundle, authority, package = approved_package(tmp_path)
    missing = copy.deepcopy(owner_bundle)
    missing["artifacts"].pop()
    with pytest.raises(ea.ContractError, match="missing|exact owner"):
        ea.validate_appraisal_package(
            package,
            authority,
            prepared,
            review,
            missing,
            expected_authority_sha256=authority["authority_digest"],
        )
    resealed = copy.deepcopy(package)
    resealed["owner_artifact_binding_digests"][0] = "0" * 64
    resealed["package_digest"] = ea._digest(ea._package_core(resealed))
    resealed["seal"]["digest"] = resealed["package_digest"]
    with pytest.raises(ea.ContractError, match="owner artifact universe"):
        ea.validate_appraisal_package(
            resealed,
            authority,
            prepared,
            review,
            owner_bundle,
            expected_authority_sha256=authority["authority_digest"],
        )
    swapped = copy.deepcopy(owner_bundle)
    report_path = Path(swapped["artifacts"][2]["artifact_path"])
    report_path.write_bytes(report_path.read_bytes() + b"\n")
    with pytest.raises(ea.ContractError, match="raw_file_sha256"):
        ea.validate_appraisal_package(
            package,
            authority,
            prepared,
            review,
            swapped,
            expected_authority_sha256=authority["authority_digest"],
        )


def test_reconcile_supersedes_latest_and_preserves_owner_lineage(
    tmp_path: Path,
) -> None:
    prepared, review, prior, owner_bundle = baseline(tmp_path / "prior")
    return_set = load("minimal_return_set.json")
    return_set["prior_cycle_ref"] = {
        "appraisal_set_id": prior["appraisal_set_id"],
        "appraisal_set_digest": prior["appraisal_set_digest"],
        "cycle": prior["cycle"],
    }
    next_bindings, next_owner = make_anonymous_owner_bundle(
        tmp_path / "next", "fixtureb"
    )
    next_request = {
        "schema": "EvidenceAppraisalRequest/v1",
        "appraisal_set_id": prior["appraisal_set_id"],
        "cycle": 1,
        "prior_cycle_ref": return_set["prior_cycle_ref"],
        "relation_keys": return_set["relation_keys"],
    }
    next_prepared = ea.prepare_appraisal(
        next_request, owner_artifact_bindings=next_bindings
    )
    next_review = load("minimal_return_review.json")
    next_review["relation_appraisals"][0]["supersedes_prior_appraisal_ref"] = {
        "appraisal_set_id": prior["appraisal_set_id"],
        "appraisal_set_digest": prior["appraisal_set_digest"],
        "cycle": prior["cycle"],
        "appraisal_id": prior["relation_appraisals"][0]["appraisal_id"],
        "semantic_digest": prior["relation_appraisals"][0]["semantic_digest"],
    }
    next_review = refresh_review(next_prepared, next_review)
    result = ea.reconcile_appraisal(
        prior, next_prepared, return_set, next_review, next_owner
    )
    all_owner = merge_owner_bundles(owner_bundle, next_owner)
    authority = ea.create_reviewed_authority(
        next_prepared,
        next_review,
        result,
        {
            "reviewer_ref": "authority-2",
            "review_method": "lineage-check",
            "reviewed_at": "time-b",
        },
        all_owner,
        lineage=[prior],
    )
    package = ea.build_appraisal_package(
        result,
        next_prepared,
        next_review,
        authority,
        all_owner,
        expected_authority_sha256=authority["authority_digest"],
        lineage=[prior],
    )
    assert (
        ea.validate_appraisal_package(
            package,
            authority,
            next_prepared,
            next_review,
            all_owner,
            expected_authority_sha256=authority["authority_digest"],
            lineage=[prior],
        )
        == package
    )


def test_atomic_writer_propagates_chmod_failure_and_cleans_baseexception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, appraisal_set, _ = baseline(tmp_path / "owner")
    monkeypatch.setattr(
        ea.os, "chmod", lambda *_: (_ for _ in ()).throw(PermissionError("no chmod"))
    )
    with pytest.raises(PermissionError):
        ea.write_appraisal_atomically(tmp_path / "out.json", appraisal_set)
    assert not list(tmp_path.glob(".evidence-appraisal-*"))


def test_atomic_writer_cleans_temporary_file_on_baseexception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, appraisal_set, _ = baseline(tmp_path / "owner")

    def interrupt(*_args: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(ea.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        ea.write_appraisal_atomically(tmp_path / "out.json", appraisal_set)
    assert not list(tmp_path.glob(".evidence-appraisal-*"))


def test_cli_exposes_real_subcommands_and_owner_inputs() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts" / "evidence_appraisal.py"),
            "--help",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for command in ("prepare", "finalize", "reconcile", "validate"):
        assert command in completed.stdout
    prepared_help = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts" / "evidence_appraisal.py"),
            "prepare",
            "--help",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--owner-artifact" in prepared_help.stdout
    assert "--owner-receipt" in prepared_help.stdout


def test_cli_replays_anonymous_owner_bundle_end_to_end(tmp_path: Path) -> None:
    bindings, owner_bundle = make_anonymous_owner_bundle(
        tmp_path / "fixturea", "fixturea"
    )
    request_path = tmp_path / "request.json"
    prepared_path = tmp_path / "prepared.json"
    review_path = tmp_path / "review.json"
    set_path = tmp_path / "set.json"
    authority_path = tmp_path / "authority.json"
    package_path = tmp_path / "package.json"
    owner_bundle_path = tmp_path / "owner-runtime.json"
    request_path.write_bytes(
        ea.canonical_json_bytes(load("minimal_request.json")) + b"\n"
    )
    owner_bundle_path.write_bytes(ea.canonical_json_bytes(owner_bundle) + b"\n")
    binding_paths: list[Path] = []
    for index, binding in enumerate(bindings):
        binding_path = tmp_path / f"binding-{index}.json"
        binding_path.write_bytes(ea.canonical_json_bytes(binding) + b"\n")
        binding_paths.append(binding_path)
    cli = [
        sys.executable,
        str(Path(__file__).parents[1] / "scripts" / "evidence_appraisal.py"),
    ]
    subprocess.run(
        [
            *cli,
            "prepare",
            str(request_path),
            str(prepared_path),
            *sum((["--owner-binding", str(path)] for path in binding_paths), []),
            "--owner-bundle",
            str(owner_bundle_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    review_path.write_bytes(
        ea.canonical_json_bytes(
            refresh_review(prepared, load("minimal_independent_review.json"))
        )
        + b"\n"
    )
    subprocess.run(
        [
            *cli,
            "finalize",
            str(prepared_path),
            str(review_path),
            str(set_path),
            "--owner-bundle",
            str(owner_bundle_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            *cli,
            "authority",
            str(prepared_path),
            str(review_path),
            str(set_path),
            str(authority_path),
            "--reviewer-ref",
            "cli-authority",
            "--review-method",
            "independent-check",
            "--reviewed-at",
            "cli-time",
            "--owner-bundle",
            str(owner_bundle_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    subprocess.run(
        [
            *cli,
            "package",
            str(set_path),
            str(prepared_path),
            str(review_path),
            str(authority_path),
            str(package_path),
            "--expected-authority-sha256",
            authority["authority_digest"],
            "--owner-bundle",
            str(owner_bundle_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    completed = subprocess.run(
        [
            *cli,
            "validate",
            str(package_path),
            "--approval",
            str(authority_path),
            "--prepared",
            str(prepared_path),
            "--review",
            str(review_path),
            "--expected-authority-sha256",
            authority["authority_digest"],
            "--owner-bundle",
            str(owner_bundle_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "valid reviewed EvidenceAppraisalPackage/v1" in completed.stdout
    assert str(tmp_path) not in package_path.read_text(encoding="utf-8")


def test_owner_binding_rejects_unsupported_schema(tmp_path: Path) -> None:
    bindings, _ = make_anonymous_owner_bundle(tmp_path / "unsupported", "fixturea")
    bindings[0]["artifact_schema"] = "UnsupportedOwner/v1"
    with pytest.raises(ea.ContractError, match="allowlisted"):
        ea.prepare_appraisal(
            load("minimal_request.json"), owner_artifact_bindings=bindings
        )
