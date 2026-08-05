import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from understanding_projection import (
    ContractError,
    PROJECTION_SOURCE_PATHS,
    _validate_projection_envelope,
    _validate_upstream_artifacts,
    canonical_payload_digest,
    canonical_projection_digest,
    create_understanding_network_projection,
    sha256_json,
    validate_projection_against_sources,
)

LIVE_PATHS = {
    "source_bundle_path": "/fixture/bundle.json",
    "source_path": "/fixture/paper.txt",
    "dossier_path": "/fixture/dossier.json",
}


def upstream_understanding_fixture():
    understanding = {
        "schema": "PaperUnderstanding/v1",
        "understanding_id": "paper-understanding-aaaaaaaaaaaaaaaa",
        "understanding_digest": "a" * 64,
    }
    for projection_type, source_path in PROJECTION_SOURCE_PATHS.items():
        understanding[source_path] = {
            "status": "answered",
            "upstream_owned": {"arbitrary": [projection_type]},
        }
    return understanding


def validation_record_fixture():
    return {
        "schema": "PaperUnderstandingValidation/v1",
        "understanding_id": "paper-understanding-aaaaaaaaaaaaaaaa",
        "understanding_digest": "a" * 64,
        "status": "passed",
        "source_binding_verified": True,
        "record_id": "paper-understanding-validation-bbbbbbbbbbbbbbbb",
        "record_digest": "b" * 64,
    }


def projection_fixture():
    understanding = upstream_understanding_fixture()
    validation_record = validation_record_fixture()
    with mock.patch(
        "understanding_projection._validate_upstream_artifacts",
        return_value=(understanding, validation_record),
    ):
        return create_understanding_network_projection(
            understanding, validation_record, **LIVE_PATHS
        )


def rehash_projection(projection):
    projection["payload_digest"] = canonical_payload_digest(
        projection["projections"]
    )
    projection["projection_digest"] = canonical_projection_digest(projection)
    projection["projection_id"] = (
        f"understanding-projection-{projection['projection_digest'][:16]}"
    )
    return projection


class UnderstandingProjectionTest(unittest.TestCase):
    def test_create_copies_all_five_typed_payloads_verbatim(self):
        understanding = upstream_understanding_fixture()
        projection = projection_fixture()
        self.assertIs(_validate_projection_envelope(projection), projection)
        self.assertEqual(
            [row["projection_type"] for row in projection["projections"]],
            list(PROJECTION_SOURCE_PATHS),
        )
        for row in projection["projections"]:
            self.assertEqual(row["payload"], understanding[row["source_path"]])

    def test_rejects_missing_or_retyped_projection(self):
        missing = projection_fixture()
        missing["projections"].pop()
        rehash_projection(missing)
        with self.assertRaisesRegex(ContractError, "five projection types"):
            _validate_projection_envelope(missing)

        retyped = projection_fixture()
        retyped["projections"][0]["source_path"] = "workflow"
        rehash_projection(retyped)
        with self.assertRaisesRegex(ContractError, "source_path"):
            _validate_projection_envelope(retyped)

    def test_payload_digest_and_status_bind_each_opaque_payload(self):
        tampered = projection_fixture()
        tampered["projections"][0]["payload"]["upstream_owned"]["arbitrary"].append(
            "tampered"
        )
        tampered["projection_digest"] = canonical_projection_digest(tampered)
        tampered["projection_id"] = (
            f"understanding-projection-{tampered['projection_digest'][:16]}"
        )
        with self.assertRaisesRegex(ContractError, "payload_digest"):
            _validate_projection_envelope(tampered)

        wrong_status = projection_fixture()
        wrong_status["projections"][0]["status"] = "unresolved"
        rehash_projection(wrong_status)
        with self.assertRaisesRegex(ContractError, "upstream payload status"):
            _validate_projection_envelope(wrong_status)

    def test_typed_basis_and_upstream_ids_fail_after_outer_rehash(self):
        arbitrary_basis = projection_fixture()
        arbitrary_basis["projections"][0]["basis_refs"] = [
            {
                "ref_type": "paper_understanding_domain",
                "understanding_id": arbitrary_basis["understanding_binding"][
                    "understanding_id"
                ],
                "understanding_digest": arbitrary_basis["understanding_binding"][
                    "understanding_digest"
                ],
                "source_path": "conclusion.invented",
                "payload_digest": arbitrary_basis["projections"][0][
                    "payload_digest"
                ],
            }
        ]
        rehash_projection(arbitrary_basis)
        with self.assertRaisesRegex(ContractError, "not source-bound"):
            _validate_projection_envelope(arbitrary_basis)

        arbitrary_id = projection_fixture()
        arbitrary_id["understanding_binding"]["understanding_id"] = (
            "paper-understanding-arbitrary"
        )
        for row in arbitrary_id["projections"]:
            row["basis_refs"][0]["understanding_id"] = (
                "paper-understanding-arbitrary"
            )
        rehash_projection(arbitrary_id)
        with self.assertRaisesRegex(ContractError, "not content-derived"):
            _validate_projection_envelope(arbitrary_id)

        arbitrary_record = projection_fixture()
        arbitrary_record["understanding_binding"]["validation_record_id"] = (
            "paper-understanding-validation-arbitrary"
        )
        for row in arbitrary_record["projections"]:
            row["provenance"]["validation_record_id"] = (
                "paper-understanding-validation-arbitrary"
            )
        rehash_projection(arbitrary_record)
        with self.assertRaisesRegex(ContractError, "validation_record_id"):
            _validate_projection_envelope(arbitrary_record)

        arbitrary_projection = projection_fixture()
        arbitrary_projection["projection_id"] = "understanding-projection-arbitrary"
        with self.assertRaisesRegex(ContractError, "projection_id"):
            _validate_projection_envelope(arbitrary_projection)

    def test_source_rebuild_rejects_internally_rehashed_semantic_rewrite(self):
        understanding = upstream_understanding_fixture()
        validation_record = validation_record_fixture()
        rewritten = projection_fixture()
        row = rewritten["projections"][0]
        row["payload"]["upstream_owned"] = {"invented": True}
        row["payload_digest"] = sha256_json(row["payload"])
        row["basis_refs"][0]["payload_digest"] = row["payload_digest"]
        rehash_projection(rewritten)
        _validate_projection_envelope(rewritten)
        with mock.patch(
            "understanding_projection._validate_upstream_artifacts",
            return_value=(understanding, validation_record),
        ):
            with self.assertRaisesRegex(ContractError, "not the verbatim source"):
                validate_projection_against_sources(
                    rewritten, understanding, validation_record, **LIVE_PATHS
                )

    def test_projection_never_authorizes_mutation(self):
        mutating = copy.deepcopy(projection_fixture())
        mutating["mutation_authorized"] = True
        rehash_projection(mutating)
        with self.assertRaisesRegex(ContractError, "mutation_authorized"):
            _validate_projection_envelope(mutating)

    def test_official_validation_record_must_bind_and_verify_source(self):
        understanding = upstream_understanding_fixture()
        validation_record = validation_record_fixture()
        validation_record["source_binding_verified"] = False
        fake_module = mock.Mock()
        fake_module.validate_understanding.return_value = understanding
        fake_module.validate_validation_record.return_value = validation_record
        fake_module.create_validation_record.return_value = validation_record
        with mock.patch(
            "understanding_projection._load_paper_understanding_module",
            return_value=fake_module,
        ):
            with self.assertRaisesRegex(ContractError, "source_binding_verified"):
                _validate_upstream_artifacts(
                    understanding, validation_record, **LIVE_PATHS
                )
        fake_module.validate_validation_record.assert_called_once_with(
            validation_record, understanding=understanding
        )

    def test_content_addressed_true_record_cannot_bypass_live_dossier(self):
        examples = (
            Path(__file__).resolve().parents[2]
            / "learn-from-papers"
            / "examples"
        )
        understanding = json.loads(
            (examples / "paper_understanding.example.json").read_text(encoding="utf-8")
        )
        upstream = __import__("understanding_projection")._load_paper_understanding_module()
        forged_understanding = copy.deepcopy(understanding)
        forged_understanding["claims"][0]["evidence"][0]["summary"] = "fabricated"
        forged_digest = upstream.understanding_digest(forged_understanding)
        forged_understanding["understanding_digest"] = forged_digest
        forged_understanding["understanding_id"] = upstream.understanding_id(
            forged_digest
        )
        forged_record = upstream.create_validation_record(forged_understanding)
        forged_record["source_binding_verified"] = True
        forged_record["checks"][2]["status"] = "passed"
        forged_record["checks"][3]["status"] = "passed"
        record_digest = upstream.validation_record_digest(forged_record)
        forged_record["record_digest"] = record_digest
        forged_record["record_id"] = upstream.validation_record_id(record_digest)
        structurally_valid = upstream.validate_understanding(forged_understanding)
        upstream.validate_validation_record(
            forged_record, understanding=structurally_valid
        )

        with self.assertRaisesRegex(ContractError, "authoritative dossier claim"):
            _validate_upstream_artifacts(
                forged_understanding,
                forged_record,
                source_bundle_path=str(
                    examples / "paper_reading_dossier_fixture" / "bundle.json"
                ),
                source_path=str(
                    examples / "paper_reading_dossier_fixture" / "paper.txt"
                ),
                dossier_path=str(
                    examples / "paper_understanding_dossier.example.json"
                ),
            )


if __name__ == "__main__":
    unittest.main()
