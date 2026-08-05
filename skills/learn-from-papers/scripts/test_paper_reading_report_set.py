#!/usr/bin/env python3
import copy
import importlib.util
import unittest


SCRIPT_PATH = __file__.replace("test_", "")
SPEC = importlib.util.spec_from_file_location("paper_reading_report_set", SCRIPT_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def sample_extraction() -> dict:
    return {
        "schema": "PaperReadingStructuredExtraction/v1",
        "protocol_version": "1.0",
        "generated_at": "2026-08-05T00:00:00Z",
        "network_ref": {
            "network_id": "KN-001",
            "snapshot_id": "KN-001-S001",
            "sha256": "0" * 64,
        },
        "review_request_set_id": "RFS-1",
        "review_request_set_digest": "a" * 64,
        "reports": [
            {
                "review_request_id": "RFX-1",
                "review_request_digest": "b" * 64,
                "source_id": "SRC-1",
                "source_digest": "c" * 64,
                "source_ref": "src-ref-1",
                "source_artifact_sha256": "d" * 64,
                "read_depth": "full_text",
                "evidence_passages": [
                    {
                        "locator_type": "page",
                        "exact_locator": "main p. 1",
                        "passage_sha256": "e" * 64,
                        "claim_summary": "核心主张1",
                        "evidence_summary": "证据文本 1",
                        "stance": "support",
                    },
                    {
                        "locator_type": "figure",
                        "exact_locator": "Fig. 2",
                        "passage_sha256": "f" * 64,
                        "claim_summary": "核心主张2",
                        "evidence_summary": "证据文本 2",
                        "stance": "mixed",
                    },
                ],
            }
        ],
    }


class PaperReadingReportSetTests(unittest.TestCase):
    def test_create_report_set_and_validate_roundtrip(self) -> None:
        report_set = module.create_report_set(sample_extraction())
        validated = module.validate_report_set(report_set)
        self.assertEqual(validated["schema"], module.REPORT_SET_SCHEMA)
        self.assertEqual(validated["schema_version"], module.SCHEMA_VERSION)
        self.assertEqual(validated["producer"], module.PRODUCER)
        self.assertEqual(validated["protocol_version"], "1.0")
        self.assertEqual(
            set(validated.keys()),
            {
                "schema",
                "schema_version",
                "producer",
                "protocol_version",
                "generated_at",
                "network_ref",
                "review_request_set_id",
                "review_request_set_digest",
                "report_set_id",
                "report_set_digest",
                "reports",
            },
        )
        self.assertEqual(
            validated["network_ref"],
            {
                "network_id": "KN-001",
                "snapshot_id": "KN-001-S001",
                "sha256": "0" * 64,
            },
        )
        self.assertEqual(validated["review_request_set_id"], "RFS-1")
        self.assertEqual(validated["review_request_set_digest"], "a" * 64)
        self.assertEqual(len(validated["reports"]), 1)

        expected_set_digest = module.canonical_report_set_digest(
            {
                key: value
                for key, value in validated.items()
                if key not in {"report_set_id", "report_set_digest"}
            }
        )
        self.assertEqual(validated["report_set_digest"], expected_set_digest)
        self.assertEqual(validated["report_set_id"], module.report_set_id(expected_set_digest))

        first_report = validated["reports"][0]
        expected_report_digest = module.canonical_report_digest(
            {
                key: value
                for key, value in first_report.items()
                if key not in {"report_id", "report_digest"}
            }
        )
        self.assertEqual(first_report["schema"], module.REPORT_SCHEMA)
        self.assertEqual(first_report["read_depth"], "full_text")
        self.assertEqual(first_report["source_ref"], "src-ref-1")
        self.assertEqual(
            set(first_report.keys()),
            {
                "schema",
                "report_id",
                "report_digest",
                "review_request_id",
                "review_request_digest",
                "source_id",
                "source_digest",
                "source_ref",
                "source_artifact_sha256",
                "read_depth",
                "evidence_passages",
            },
        )
        self.assertEqual(first_report["report_digest"], expected_report_digest)
        self.assertEqual(first_report["report_id"], module.report_id(expected_report_digest))

        first_passage = first_report["evidence_passages"][0]
        expected_passage_digest = module.canonical_passage_digest(
            {
                key: value
                for key, value in first_passage.items()
                if key not in {"passage_id", "passage_digest"}
            }
        )
        self.assertEqual(first_passage["passage_digest"], expected_passage_digest)
        self.assertEqual(first_passage["passage_id"], module.passage_id(expected_passage_digest))

    def test_legacy_reading_depth_is_supported_for_input_only(self) -> None:
        payload = sample_extraction()
        payload["reports"][0].pop("read_depth")
        payload["reports"][0]["reading_depth"] = "full_text"
        report_set = module.create_report_set(payload)
        report = report_set["reports"][0]
        self.assertEqual(report["read_depth"], "full_text")
        self.assertNotIn("reading_depth", report)

    def test_validate_accepts_legacy_top_level_fields_but_strips_output(self) -> None:
        report_set = module.create_report_set(sample_extraction())
        legacy = {
            **report_set,
            "network_id": "KN-001",
            "network_snapshot_sha256": "0" * 64,
            "source_artifact_sha256": "d" * 64,
            "reading_report_set_id": report_set["report_set_id"],
            "reading_report_set_digest": report_set["report_set_digest"],
        }
        validated = module.validate_report_set(legacy)
        self.assertEqual(
            set(validated.keys()),
            {
                "schema",
                "schema_version",
                "producer",
                "protocol_version",
                "generated_at",
                "network_ref",
                "review_request_set_id",
                "review_request_set_digest",
                "report_set_id",
                "report_set_digest",
                "reports",
            },
        )
        self.assertNotIn("network_id", validated)
        self.assertNotIn("network_snapshot_sha256", validated)
        self.assertNotIn("source_artifact_sha256", validated)
        self.assertNotIn("reading_report_set_id", validated)
        self.assertNotIn("reading_report_set_digest", validated)

    def test_fail_when_source_ref_is_missing(self) -> None:
        payload = sample_extraction()
        del payload["reports"][0]["source_ref"]
        with self.assertRaises(module.ContractError):
            module.create_report_set(payload)

    def test_fail_when_network_ref_is_missing(self) -> None:
        payload = sample_extraction()
        payload.pop("network_ref")
        with self.assertRaises(module.ContractError):
            module.create_report_set(payload)

    def test_fail_when_source_artifact_hash_is_missing(self) -> None:
        payload = sample_extraction()
        del payload["reports"][0]["source_artifact_sha256"]
        with self.assertRaises(module.ContractError):
            module.create_report_set(payload)

    def test_fail_when_discovery_metadata_is_not_a_completed_extraction(self) -> None:
        with self.assertRaises(module.ContractError):
            module.create_report_set(
                {
                    "protocol_version": "1.0",
                    "network_ref": {
                        "network_id": "KN-001",
                        "snapshot_id": "KN-001-S001",
                        "sha256": "0" * 64,
                    },
                    "review_request_set_id": "RFS-1",
                    "review_request_set_digest": "a" * 64,
                    "discovery_metadata": {"query": "x"},
                }
            )

    def test_fail_when_exact_locator_is_url_or_doi(self) -> None:
        payload = sample_extraction()
        payload["reports"][0]["evidence_passages"][0]["exact_locator"] = (
            "https://example.com/paper.pdf"
        )
        with self.assertRaises(module.ContractError):
            module.create_report_set(payload)

        payload = sample_extraction()
        payload["reports"][0]["evidence_passages"][0]["exact_locator"] = "10.1000/abc"
        with self.assertRaises(module.ContractError):
            module.create_report_set(payload)

    def test_fail_on_duplicate_passage_id_after_creation(self) -> None:
        payload = sample_extraction()
        payload["reports"][0]["evidence_passages"].append(
            copy.deepcopy(payload["reports"][0]["evidence_passages"][0])
        )
        with self.assertRaises(module.ContractError):
            module.create_report_set(payload)

    def test_validate_fails_on_digest_tamper(self) -> None:
        report_set = module.create_report_set(sample_extraction())
        invalid = copy.deepcopy(report_set)
        invalid["reports"][0]["report_digest"] = "0" * 64
        with self.assertRaises(module.ContractError):
            module.validate_report_set(invalid)

    def test_validate_fails_on_duplicate_report_id(self) -> None:
        report_set = module.create_report_set(sample_extraction())
        report_set["reports"].append(copy.deepcopy(report_set["reports"][0]))
        with self.assertRaises(module.ContractError):
            module.validate_report_set(report_set)


if __name__ == "__main__":
    unittest.main()
