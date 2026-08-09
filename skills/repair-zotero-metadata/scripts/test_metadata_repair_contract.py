#!/usr/bin/env python3
"""Contract tests for reviewed existing-parent metadata repairs."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import metadata_repair_contract as contract


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
BUILD_REVIEWED_SOURCE = contract.build_reviewed_source


def synthetic_sidecar() -> dict:
    sidecar = {
        "schema": "ZoteroParentMetadataRepairLiveSidecar/v1",
        "captured_at": "2026-01-02T03:03:00Z",
        "mode": "read_only",
        "private": True,
        "evidence_state": {"parent_version": 3, "duplicate_candidates": []},
        "safety": {"zotero_writes": 0},
    }
    sidecar["content_sha256"] = contract.sha256_value(sidecar)
    return sidecar


def synthetic_sidecar_bytes() -> bytes:
    return (
        json.dumps(synthetic_sidecar(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    ).encode("utf-8")


def synthetic_sidecar_ref() -> dict:
    payload = synthetic_sidecar_bytes()
    sidecar = json.loads(payload)
    return {
        "schema": sidecar["schema"],
        "file_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "content_sha256": sidecar["content_sha256"],
    }


def synthetic_draft() -> dict:
    return {
        "schema": "ZoteroParentMetadataRepairDraft/v1",
        "status": "reviewed",
        "created_at": "2026-01-02T03:04:05Z",
        "private": True,
        "source_evidence_sidecar_ref": synthetic_sidecar_ref(),
        "source": {
            "hash_contract": "canonical-json-v1",
            "evidence_artifacts": [
                {
                    "id": "pdf-evidence",
                    "kind": "verified_pdf",
                    "locator": "artifact:synthetic-pdf",
                    "retrieved_at": "2026-01-02T03:00:00Z",
                    "sha256": SHA_C,
                },
                {
                    "id": "publisher-evidence",
                    "kind": "publisher_metadata",
                    "locator": "https://example.invalid/synthetic-record",
                    "retrieved_at": "2026-01-02T03:01:00Z",
                    "sha256": SHA_B,
                },
            ],
            "field_evidence": {
                "DOI": ["pdf-evidence", "publisher-evidence"],
                "creators": ["pdf-evidence", "publisher-evidence"],
                "issue": ["publisher-evidence"],
                "pages": ["publisher-evidence"],
                "publicationTitle": ["publisher-evidence"],
                "volume": ["publisher-evidence"],
            },
        },
        "target": {
            "group_id": 999999,
            "library_type": "group",
            "library_type_id": 999999,
            "local_library_id": 99,
            "library_name": "Synthetic Research Library",
            "collection_key": "COLL0001",
            "collection_version": 7,
            "collection_path": ["Research", "Methods"],
            "internal_collection_id": None,
        },
        "entry": {
            "parent": {
                "key": "PARENT01",
                "version": 3,
                "item_type": "journalArticle",
                "title": "Synthetic sensitivity study",
                "short_title": "Synthetic setting: reviewed conclusion",
                "expected_target_membership": True,
            },
            "children": [
                {
                    "key": "NOTE0001",
                    "version": 2,
                    "item_type": "note",
                    "content_sha256": SHA_B,
                },
                {
                    "key": "PDF00001",
                    "version": 5,
                    "item_type": "attachment",
                    "content_type": "application/pdf",
                    "link_mode": "imported_file",
                    "size_bytes": 1234,
                    "content_sha256": SHA_C,
                    "direct_collection_count": 0,
                },
            ],
            "evidence_pdf_key": "PDF00001",
            "duplicate_preconditions": {
                "scope": "full_library",
                "desired_doi_other_parent_keys": [],
                "title_year_creator_other_parent_keys": [],
            },
            "repair": {
                "profile": "journal_article_core_v1",
                "transition_policy": "fill_or_evidence_bound_replace_v1",
                "expected_profile": {
                    "DOI": "10.0000/synthetic.old",
                    "creators": [],
                    "publicationTitle": "",
                    "volume": "",
                    "issue": "",
                    "pages": "",
                    "date": "2026",
                },
                "desired_profile": {
                    "DOI": "10.0000/synthetic.new",
                    "creators": [
                        {
                            "creatorType": "author",
                            "firstName": "Alex",
                            "lastName": "Example",
                        },
                        {
                            "creatorType": "author",
                            "firstName": "Blair",
                            "lastName": "Sample",
                        },
                    ],
                    "publicationTitle": "Synthetic Journal",
                    "volume": "7",
                    "issue": "2",
                    "pages": "10-20",
                    "date": "2026",
                },
            },
        },
        "summary": {
            "decision": "repair",
            "review_scope": "synthetic contract test",
        },
    }


def synthetic_v2_state(*, post_commit: bool = False) -> tuple[dict, list[dict]]:
    note_html = '<div data-schema-version="9"><p>Synthetic note</p></div>'
    parent = {
        "key": "PARENT01",
        "version": 9 if post_commit else 3,
        "itemType": "journalArticle",
        "title": "Synthetic sensitivity study",
        "shortTitle": "Synthetic setting: reviewed conclusion",
        "abstractNote": "Bound non-profile metadata",
        "DOI": "10.0000/synthetic.new" if post_commit else "10.0000/synthetic.old",
        "creators": (
            [
                {"creatorType": "author", "firstName": "Alex", "lastName": "Example"},
                {"creatorType": "author", "firstName": "Blair", "lastName": "Sample"},
            ]
            if post_commit
            else []
        ),
        "publicationTitle": "Synthetic Journal" if post_commit else "",
        "volume": "7" if post_commit else "",
        "issue": "2" if post_commit else "",
        "pages": "10-20" if post_commit else "",
        "date": "2026",
        "url": "https://example.invalid/parent",
        "tags": ([{"tag": "method"}, {"tag": "reviewed"}] if post_commit else [{"tag": "reviewed"}, {"tag": "method"}]),
        "collections": (["OTHER001", "COLL0001"] if post_commit else ["COLL0001", "OTHER001"]),
        "dateAdded": "2026-01-01T00:00:00Z",
        "dateModified": "2026-01-03T00:00:00Z" if post_commit else "2026-01-01T00:00:00Z",
        "relations": {},
    }
    note = {
        "key": "NOTE0001",
        "version": 2,
        "itemType": "note",
        "parentItem": "PARENT01",
        "note": note_html,
        "tags": [],
        "relations": {},
    }
    attachment = {
        "key": "PDF00001",
        "version": 9 if post_commit else 5,
        "itemType": "attachment",
        "parentItem": "PARENT01",
        "title": "Synthetic sensitivity study - full text",
        "url": "https://example.invalid/paper.pdf",
        "contentType": "application/pdf",
        "linkMode": "imported_file",
        "md5": "0123456789abcdef0123456789abcdef",
        "mtime": 1_700_000_000_000,
        "filename": (
            "Example and Sample - 2026 - Synthetic sensitivity study.pdf"
            if post_commit
            else "2026 - Synthetic sensitivity study.pdf"
        ),
        "collections": [],
        "tags": [],
        "relations": {},
        "dateAdded": "2026-01-01T00:00:00Z",
        "dateModified": "2026-01-01T00:00:00Z",
    }
    storage_path = (
        "/synthetic/storage/PDF00001/Example and Sample - 2026 - Synthetic sensitivity study.pdf"
        if post_commit
        else "/synthetic/storage/PDF00001/2026 - Synthetic sensitivity study.pdf"
    )
    return parent, [
        {"data": note},
        {
            "data": attachment,
            "storage_path": storage_path,
            "content_sha256": SHA_C,
            "size_bytes": 1234,
        },
    ]


def synthetic_v2_draft() -> dict:
    draft = synthetic_draft()
    draft["schema"] = contract.DRAFT_SCHEMA_V2
    parent_data, child_records = synthetic_v2_state()
    note_html = child_records[0]["data"]["note"]
    draft["entry"]["children"][0]["content_sha256"] = (
        "sha256:" + hashlib.sha256(note_html.encode("utf-8")).hexdigest()
    )
    draft["entry"]["serializer_guard"] = contract.serializer_guard_from_records(
        parent_data, child_records
    )
    return draft


def build_reviewed(draft: dict | None = None, sidecar: Path | bytes | None = None) -> dict:
    return BUILD_REVIEWED_SOURCE(
        draft or synthetic_draft(),
        source_evidence_sidecar=sidecar or synthetic_sidecar_bytes(),
    )


class MetadataRepairContractTests(unittest.TestCase):
    def test_cross_serializer_fixture_has_exact_diagnosis_and_one_canonical_projection(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parents[2]
            / "zotero-declarative-bridge"
            / "scripts"
            / "fixtures"
            / "metadata_cross_serializer_attachment_v1.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["diagnosis"]["local_api_only_fields"],
            ["md5", "mtime"],
        )
        projections = {}
        for phase in ("pre", "post"):
            local_api = fixture[phase]["local_api"]
            item_to_json = fixture[phase]["item_to_json"]
            self.assertEqual(
                sorted(set(local_api) - set(item_to_json)),
                fixture["diagnosis"]["local_api_only_fields"],
            )
            local_projection = contract.serializer_attachment_projection(
                local_api,
                content_md5=fixture["content_md5"],
            )
            runtime_projection = contract.serializer_attachment_projection(
                item_to_json,
                content_md5=fixture["content_md5"],
            )
            self.assertEqual(local_projection, fixture[phase]["expected_projection"])
            self.assertEqual(runtime_projection, fixture[phase]["expected_projection"])
            projections[phase] = contract.serializer_attachment_stable_data(
                item_to_json,
                content_md5=fixture["content_md5"],
            )
        self.assertEqual(projections["pre"], projections["post"])

    def test_projection_contract_is_explicit_and_defaults_parent_and_note_fields(self) -> None:
        self.assertEqual(
            contract.SERIALIZER_PROJECTION_CONTRACT["schema"],
            contract.SERIALIZER_PROJECTION_SCHEMA,
        )
        parent, children = synthetic_v2_state()
        projected_parent = contract.serializer_parent_projection(parent)
        projected_note = contract.serializer_note_projection(children[0]["data"])
        self.assertEqual(projected_parent["fields"]["PMID"], "")
        self.assertEqual(projected_parent["fields"]["citationKey"], "")
        self.assertEqual(projected_note["date_added"], "")
        with self.assertRaisesRegex(contract.ContractError, "unknown fields"):
            contract.serializer_parent_projection({**parent, "futureField": "unsafe"})

    def test_builds_and_validates_sealed_fixed_profile_source(self) -> None:
        reviewed = build_reviewed(synthetic_draft())
        validated = contract.validate_reviewed_source(reviewed)
        self.assertEqual(validated["schema"], contract.REVIEWED_SCHEMA)
        self.assertFalse(validated["executable"])
        self.assertEqual(
            set(validated["entry"]["repair"]["desired_profile"]),
            set(contract.PROFILE_FIELDS),
        )
        self.assertEqual(
            validated["entry"]["repair"]["changed_fields"],
            ["DOI", "creators", "issue", "pages", "publicationTitle", "volume"],
        )
        self.assertEqual(
            validated["manifest_sha256"],
            contract.sha256_value(
                {key: value for key, value in validated.items() if key != "manifest_sha256"}
            ),
        )

    def test_title_and_short_title_are_not_writable_profile_fields(self) -> None:
        draft = synthetic_draft()
        draft["entry"]["repair"]["desired_profile"]["title"] = "Injected title"
        with self.assertRaisesRegex(contract.ContractError, "profile keys differ"):
            build_reviewed(draft)

    def test_v2_binds_hash_only_zotero_serializer_guard_without_changing_v1(self) -> None:
        reviewed_v1 = build_reviewed(synthetic_draft())
        reviewed_v2 = build_reviewed(synthetic_v2_draft())
        self.assertEqual(reviewed_v1["schema"], contract.REVIEWED_SCHEMA)
        self.assertNotIn("serializer_guard", reviewed_v1["entry"])
        self.assertEqual(reviewed_v2["schema"], contract.REVIEWED_SCHEMA_V2)
        self.assertEqual(
            reviewed_v2["entry"]["serializer_guard"]["profile"],
            contract.SERIALIZER_GUARD_PROFILE,
        )

    def test_v2_allows_only_managed_attachment_rename_and_set_order_after_commit(self) -> None:
        expected_parent, expected_children = synthetic_v2_state()
        observed_parent, observed_children = synthetic_v2_state(post_commit=True)
        expected = contract.serializer_guard_from_records(expected_parent, expected_children)
        observed = contract.serializer_guard_from_records(observed_parent, observed_children)
        self.assertEqual(
            contract.classify_serializer_guard(
                expected, observed, allow_equivalent=True
            ),
            "zotero_managed_attachment_rename_and_set_order_equivalent",
        )
        with self.assertRaisesRegex(contract.ContractError, "serializer content drift"):
            contract.classify_serializer_guard(
                expected, observed, allow_equivalent=False
            )

    def test_v2_equivalence_rejects_attachment_note_and_tag_member_drift(self) -> None:
        expected_parent, expected_children = synthetic_v2_state()
        expected = contract.serializer_guard_from_records(expected_parent, expected_children)

        for field, value in (
            ("title", "Changed attachment title"),
            ("url", "https://example.invalid/other.pdf"),
            ("linkMode", "imported_url"),
            ("contentType", "text/html"),
            ("md5", "f" * 32),
        ):
            with self.subTest(attachment_field=field):
                parent, children = synthetic_v2_state(post_commit=True)
                children[1]["data"][field] = value
                observed = contract.serializer_guard_from_records(parent, children)
                with self.assertRaisesRegex(contract.ContractError, "stable_data_sha256"):
                    contract.classify_serializer_guard(
                        expected, observed, allow_equivalent=True
                    )

        for field in ("tags", "collections"):
            with self.subTest(attachment_member_field=field):
                parent, children = synthetic_v2_state(post_commit=True)
                value = {"tag": "new-member"} if field == "tags" else "EXTRA001"
                children[1]["data"][field].append(value)
                observed = contract.serializer_guard_from_records(parent, children)
                with self.assertRaisesRegex(contract.ContractError, "stable_data_sha256"):
                    contract.classify_serializer_guard(
                        expected, observed, allow_equivalent=True
                    )

        parent, children = synthetic_v2_state(post_commit=True)
        children[1]["content_sha256"] = SHA_A
        with self.assertRaisesRegex(contract.ContractError, "content_sha256"):
            contract.classify_serializer_guard(
                expected,
                contract.serializer_guard_from_records(parent, children),
                allow_equivalent=True,
            )

        parent, children = synthetic_v2_state(post_commit=True)
        children[0]["data"]["note"] = "Changed note"
        with self.assertRaisesRegex(contract.ContractError, "note content"):
            contract.classify_serializer_guard(
                expected,
                contract.serializer_guard_from_records(parent, children),
                allow_equivalent=True,
            )

        parent, children = synthetic_v2_state(post_commit=True)
        parent["tags"].append({"tag": "new-member"})
        with self.assertRaisesRegex(contract.ContractError, "tags member drift"):
            contract.classify_serializer_guard(
                expected,
                contract.serializer_guard_from_records(parent, children),
                allow_equivalent=True,
            )

        parent, children = synthetic_v2_state(post_commit=True)
        parent["collections"].append("EXTRA001")
        with self.assertRaisesRegex(contract.ContractError, "collections member drift"):
            contract.classify_serializer_guard(
                expected,
                contract.serializer_guard_from_records(parent, children),
                allow_equivalent=True,
            )

    def test_rejects_nonempty_creator_replacement_in_v1(self) -> None:
        draft = synthetic_draft()
        draft["entry"]["repair"]["expected_profile"]["creators"] = [
            {
                "creatorType": "author",
                "firstName": "Existing",
                "lastName": "Author",
            }
        ]
        with self.assertRaisesRegex(contract.ContractError, "creators may only be filled"):
            build_reviewed(draft)

    def test_rejects_doi_replacement_without_two_evidence_artifacts(self) -> None:
        draft = synthetic_draft()
        draft["source"]["field_evidence"]["DOI"] = ["publisher-evidence"]
        with self.assertRaisesRegex(contract.ContractError, "DOI replacement requires two"):
            build_reviewed(draft)

    def test_rejects_verified_pdf_hash_not_bound_to_pdf_child(self) -> None:
        draft = synthetic_draft()
        draft["source"]["evidence_artifacts"][0]["sha256"] = SHA_A
        with self.assertRaisesRegex(contract.ContractError, "bound PDF child"):
            build_reviewed(draft)

    def test_date_replacement_requires_bound_verified_pdf_reference(self) -> None:
        draft = synthetic_draft()
        draft["entry"]["repair"]["expected_profile"]["date"] = "2025"
        draft["source"]["evidence_artifacts"].append(
            {
                "id": "registry-evidence",
                "kind": "doi_registry",
                "locator": "https://example.invalid/synthetic-registry",
                "retrieved_at": "2026-01-02T03:02:00Z",
                "sha256": SHA_B,
            }
        )
        draft["source"]["field_evidence"]["date"] = [
            "publisher-evidence",
            "registry-evidence",
        ]
        with self.assertRaisesRegex(contract.ContractError, "verified PDF"):
            build_reviewed(draft)
        draft["source"]["field_evidence"]["date"] = [
            "pdf-evidence",
            "publisher-evidence",
        ]
        build_reviewed(draft)

    def test_duplicate_title_year_distinguishes_exact_and_long_prefix_creators(self) -> None:
        draft = synthetic_draft()
        desired = draft["entry"]["repair"]["desired_profile"]
        title = draft["entry"]["parent"]["title"]

        def record(key: str, creators: list[dict], record_title: str = title) -> dict:
            return {
                "data": {
                    "key": key,
                    "itemType": "journalArticle",
                    "title": record_title,
                    "date": "2026",
                    "DOI": "",
                    "creators": creators,
                }
            }

        candidates = contract.find_duplicate_candidates(
            [
                record(
                    "PARTIAL1",
                    [{"creatorType": "author", "lastName": "Example"}],
                ),
                record("MISSING1", []),
                record(
                    "EXTRA001",
                    [
                        {"creatorType": "author", "lastName": "Example"},
                        {"creatorType": "editor", "lastName": "Editor"},
                    ],
                ),
                record(
                    "OTHER001",
                    [{"creatorType": "author", "lastName": "Unrelated"}],
                ),
                record(
                    "PREFIX01",
                    [{"creatorType": "author", "lastName": "Example"}],
                    "Synthetic sensitivity",
                ),
                record("PREFMISS", [], "Synthetic sensitivity"),
                record(
                    "PREFOTHR",
                    [{"creatorType": "author", "lastName": "Unrelated"}],
                    "Synthetic sensitivity",
                ),
                record(
                    "SHORT001",
                    [{"creatorType": "author", "lastName": "Example"}],
                    "Synthetic",
                ),
            ],
            current_key="PARENT01",
            title=title,
            desired_profile=desired,
        )
        self.assertEqual(
            candidates["title_year_creator_other_parent_keys"],
            ["EXTRA001", "MISSING1", "PARTIAL1", "PREFIX01"],
        )

    def test_rejects_any_reviewed_duplicate_candidate(self) -> None:
        draft = synthetic_draft()
        draft["entry"]["duplicate_preconditions"][
            "desired_doi_other_parent_keys"
        ] = ["OTHER001"]
        with self.assertRaisesRegex(contract.ContractError, "duplicate candidates"):
            build_reviewed(draft)

    def test_validation_detects_nested_hash_drift(self) -> None:
        reviewed = build_reviewed(synthetic_draft())
        reviewed["entry"]["repair"]["desired_profile"]["volume"] = "8"
        with self.assertRaisesRegex(contract.ContractError, "desired_profile_sha256"):
            contract.validate_reviewed_source(reviewed)

    def test_cli_writes_private_source_and_validate_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft_path = root / "draft.json"
            sidecar_path = root / "sidecar.json"
            source_path = root / "reviewed.json"
            draft_path.write_text(json.dumps(synthetic_draft()), encoding="utf-8")
            sidecar_path.write_bytes(synthetic_sidecar_bytes())
            sidecar_path.chmod(0o600)
            self.assertEqual(
                contract.main(
                    [
                        "build-reviewed-source",
                        str(draft_path),
                        str(source_path),
                        "--source-evidence-sidecar",
                        str(sidecar_path),
                    ]
                ),
                0,
            )
            self.assertEqual(source_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                contract.main(["validate-reviewed-source", str(source_path)]),
                0,
            )

    def test_duplicate_normalization_matches_shared_cross_language_fixtures(self) -> None:
        fixture = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "references"
                / "duplicate-normalization-fixtures.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            fixture["schema"], "MetadataDuplicateNormalizationFixtures/v1"
        )
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    contract._duplicate_text(case["input"]), case["expected"]
                )

    def test_rejects_missing_source_evidence_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-sidecar.json"
            with self.assertRaisesRegex(
                contract.ContractError, "cannot read source evidence sidecar"
            ):
                build_reviewed(synthetic_draft(), missing)

    def test_rejects_mutated_source_evidence_sidecar_content(self) -> None:
        mutated = synthetic_sidecar()
        mutated["captured_at"] = "2026-01-02T03:03:01Z"
        payload = (
            json.dumps(mutated, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        draft = synthetic_draft()
        draft["source_evidence_sidecar_ref"]["file_sha256"] = (
            "sha256:" + hashlib.sha256(payload).hexdigest()
        )
        with self.assertRaisesRegex(contract.ContractError, "content_sha256"):
            build_reviewed(draft, payload)

    def test_rejects_source_evidence_sidecar_reference_mismatch(self) -> None:
        draft = synthetic_draft()
        draft["source_evidence_sidecar_ref"]["file_sha256"] = SHA_A
        with self.assertRaisesRegex(contract.ContractError, "file_sha256"):
            build_reviewed(draft, synthetic_sidecar_bytes())


if __name__ == "__main__":
    unittest.main()
