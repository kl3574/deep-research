import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_document_normalization import (
    ContractError,
    adopt_existing_document,
    inspect_document,
    main,
    normalize_document,
    validate_normalization_record,
    validate_quality_record,
    validate_quality_shape,
    write_json_exclusive,
)


FAKE_TOOL = r'''#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
log = os.environ.get("FAKE_TOOL_LOG")
if log:
    with Path(log).open("a", encoding="utf-8") as handle:
        handle.write(name + " " + " ".join(sys.argv[1:]) + "\n")
if len(sys.argv) == 2 and sys.argv[1] in {"-v", "--version"}:
    print(f"{name} version 1.2.3")
    raise SystemExit(0)

def content(path):
    return Path(path).read_text(encoding="utf-8", errors="ignore")

def pages(path):
    match = re.search(r"PAGES=(\d+)", content(path))
    return int(match.group(1)) if match else 1

if name == "pdfinfo":
    print(f"Pages: {pages(sys.argv[-1])}")
elif name == "pdftotext":
    source, output = sys.argv[-2:]
    marker = content(source)
    count = pages(source)
    if "BLANK" in marker:
        body = [""] * count
    elif "PATHOLOGICAL" in marker:
        body = [("X" * 210001)] * count
    elif "COLUMN" in marker:
        body = ["\n".join(["left content        right content"] * 12)] * count
    elif "MIXED" in marker:
        body = ["", "ordinary searchable prose\n" * 12][:count]
        body.extend(["ordinary searchable prose\n" * 12] * (count - len(body)))
    else:
        body = ["ordinary searchable prose with several words\n" * 12] * count
    Path(output).write_text("\f".join(body) + "\f", encoding="utf-8")
elif name == "pdftoppm":
    source, prefix = sys.argv[-2:]
    for index in range(1, pages(source) + 1):
        Path(f"{prefix}-{index}.png").write_bytes(b"FAKEPNG")
elif name == "tesseract":
    if os.environ.get("FAKE_TESSERACT_FAIL") == "1":
        raise SystemExit(9)
    Path(sys.argv[2] + ".pdf").write_text(
        "%PDF-FAKE\nPAGES=1\nOCR_PAGE\n", encoding="utf-8"
    )
elif name == "pdfunite":
    inputs, output = sys.argv[1:-1], sys.argv[-1]
    Path(output).write_text(
        f"%PDF-FAKE\nPAGES={len(inputs)}\nOCR_NATIVE\n", encoding="utf-8"
    )
else:
    raise SystemExit(3)
'''


class ScholarlyDocumentNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tools = {}
        for name in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract", "pdfunite"):
            path = self.root / name
            path.write_text(FAKE_TOOL, encoding="utf-8")
            path.chmod(0o755)
            self.tools[name] = str(path)

    def tearDown(self):
        self.temp.cleanup()

    def source(self, marker, pages=3):
        path = self.root / f"{marker.lower()}.pdf"
        path.write_text(f"%PDF-FAKE\nPAGES={pages}\n{marker}\n", encoding="utf-8")
        return path

    def inspect(self, marker, pages=3):
        source = self.source(marker, pages)
        record = inspect_document(
            source_path=str(source),
            pdfinfo_path=self.tools["pdfinfo"],
            pdftotext_path=self.tools["pdftotext"],
            generated_at="2026-08-05T00:00:00Z",
        )
        quality = self.root / f"{marker.lower()}-quality.json"
        write_json_exclusive(str(quality), record)
        return source, quality, record

    def normalize(self, marker="BLANK"):
        source, quality, before = self.inspect(marker)
        derivative = self.root / f"{marker.lower()}-searchable.pdf"
        result = self.root / f"{marker.lower()}-normalization.json"
        record = normalize_document(
            source_path=str(source),
            quality_path=str(quality),
            output_pdf_path=str(derivative),
            output_record_path=str(result),
            pdfinfo_path=self.tools["pdfinfo"],
            pdftotext_path=self.tools["pdftotext"],
            pdftoppm_path=self.tools["pdftoppm"],
            tesseract_path=self.tools["tesseract"],
            pdfunite_path=self.tools["pdfunite"],
            generated_at="2026-08-05T00:01:00Z",
            source_bundle_path=None,
            dpi=300,
            languages="eng",
        )
        return source, quality, derivative, result, before, record

    def adopt(self, provenance_status="reconstructed", **kwargs):
        source, quality, before = self.inspect("BLANK")
        derivative = self.root / "existing-searchable.pdf"
        derivative.write_text(
            "%PDF-FAKE\nPAGES=3\nOCR_NATIVE\n", encoding="utf-8"
        )
        derivative_before = derivative.read_bytes()
        result = self.root / "adopted-normalization.json"
        log = self.root / "tool-calls.log"
        with mock.patch.dict(os.environ, {"FAKE_TOOL_LOG": str(log)}):
            record = adopt_existing_document(
                source_path=str(source),
                derivative_path=str(derivative),
                quality_path=str(quality),
                output_record_path=str(result),
                pdfinfo_path=self.tools["pdfinfo"],
                pdftotext_path=self.tools["pdftotext"],
                pdftoppm_path=self.tools["pdftoppm"],
                tesseract_path=self.tools["tesseract"],
                pdfunite_path=self.tools["pdfunite"],
                generated_at="2026-08-05T00:02:00Z",
                source_bundle_path=None,
                dpi=300,
                languages="eng",
                provenance_status=provenance_status,
                provenance_statement="Retained OCR outputs and operator record.",
                **kwargs,
            )
        self.assertEqual(derivative.read_bytes(), derivative_before)
        return source, quality, derivative, result, before, record, log

    def test_inspect_classifies_blank_pathological_and_column_risk(self):
        cases = {
            "BLANK": "blank_scan",
            "PATHOLOGICAL": "pathological_text",
            "MIXED": "mixed",
            "COLUMN": "column_risk",
        }
        for marker, expected in cases.items():
            with self.subTest(marker=marker):
                _, _, record = self.inspect(marker)
                self.assertEqual(record["summary"]["classification"], expected)
                self.assertTrue(record["summary"]["review_required"])
                self.assertEqual(len(record["pages"]), 3)

    def test_quality_output_is_closed_and_live_reproducible(self):
        source, _, record = self.inspect("NATIVE")
        validated = validate_quality_record(
            record,
            source_path=str(source),
            pdfinfo_path=self.tools["pdfinfo"],
            pdftotext_path=self.tools["pdftotext"],
            source_bundle_path=None,
        )
        self.assertEqual(validated, record)
        invalid = dict(record, surprise=True)
        with self.assertRaisesRegex(ContractError, "unknown"):
            validate_quality_shape(invalid)

    def test_normalize_and_validate_binds_lineage_and_requires_review(self):
        source, quality, derivative, _, _, record = self.normalize()
        validated = validate_normalization_record(
            record,
            source_path=str(source),
            derivative_path=str(derivative),
            quality_path=str(quality),
            pdfinfo_path=self.tools["pdfinfo"],
            pdftotext_path=self.tools["pdftotext"],
            source_bundle_path=None,
        )
        self.assertEqual(validated["quality_before"]["summary"]["classification"], "blank_scan")
        self.assertEqual(validated["quality_after"]["summary"]["classification"], "native_ok")
        self.assertTrue(validated["quality_after"]["summary"]["review_required"])
        self.assertTrue(validated["review_required"])
        self.assertEqual(validated["accuracy_claim"], "not_assessed")
        self.assertEqual(validated["original"]["page_count"], validated["derivative"]["page_count"])

    def test_adopt_existing_emits_v1_per_page_lineage_without_rerunning_ocr(self):
        source, quality, derivative, result, _, record, log = self.adopt()
        self.assertEqual(record["schema"], "ScholarlyDocumentNormalization/v1")
        self.assertEqual(record["method"], "adopt-existing")
        self.assertEqual(record["adoption_mode"], "existing_derivative_no_ocr_execution")
        self.assertEqual(record["provenance"]["status"], "reconstructed")
        self.assertEqual(len(record["quality_before"]["pages"]), 3)
        self.assertEqual(len(record["quality_after"]["pages"]), 3)
        self.assertEqual(record["quality_after"]["summary"]["classification"], "native_ok")
        self.assertTrue(record["quality_after"]["summary"]["review_required"])
        self.assertTrue(record["review_required"])
        self.assertEqual(record["accuracy_claim"], "not_assessed")
        self.assertEqual(result.stat().st_mode & 0o777, 0o600)
        calls = log.read_text(encoding="utf-8").splitlines()
        operational_ocr = [
            line
            for line in calls
            if line.startswith(("pdftoppm ", "tesseract ", "pdfunite "))
            and not line.endswith((" --version", " -v"))
        ]
        self.assertEqual(operational_ocr, [])
        validated = validate_normalization_record(
            record,
            source_path=str(source),
            derivative_path=str(derivative),
            quality_path=str(quality),
            pdfinfo_path=self.tools["pdfinfo"],
            pdftotext_path=self.tools["pdftotext"],
            source_bundle_path=None,
        )
        self.assertEqual(validated, record)

    def test_adopt_existing_detects_page_mismatch_without_output(self):
        source, quality, _ = self.inspect("BLANK")
        derivative = self.source("OCR_NATIVE", pages=2)
        output = self.root / "page-mismatch.json"
        with self.assertRaisesRegex(ContractError, "page count"):
            adopt_existing_document(
                source_path=str(source),
                derivative_path=str(derivative),
                quality_path=str(quality),
                output_record_path=str(output),
                pdfinfo_path=self.tools["pdfinfo"],
                pdftotext_path=self.tools["pdftotext"],
                pdftoppm_path=self.tools["pdftoppm"],
                tesseract_path=self.tools["tesseract"],
                pdfunite_path=self.tools["pdfunite"],
                generated_at="2026-08-05T00:02:00Z",
                source_bundle_path=None,
                dpi=300,
                languages="eng",
                provenance_status="reconstructed",
                provenance_statement="Retained OCR outputs.",
            )
        self.assertFalse(output.exists())

    def test_adopt_existing_recorded_provenance_requires_explicit_argv(self):
        with self.assertRaisesRegex(ContractError, "requires explicit"):
            self.adopt(provenance_status="recorded")

    def test_adopted_lineage_validation_detects_derivative_tampering(self):
        source, quality, derivative, _, _, record, _ = self.adopt()
        with derivative.open("ab") as handle:
            handle.write(b"tamper")
        with self.assertRaisesRegex(ContractError, "identity mismatch"):
            validate_normalization_record(
                record,
                source_path=str(source),
                derivative_path=str(derivative),
                quality_path=str(quality),
                pdfinfo_path=self.tools["pdfinfo"],
                pdftotext_path=self.tools["pdftotext"],
                source_bundle_path=None,
            )

    def test_lineage_validation_detects_derivative_tampering(self):
        source, quality, derivative, _, _, record = self.normalize()
        with derivative.open("ab") as handle:
            handle.write(b"tamper")
        with self.assertRaisesRegex(ContractError, "identity mismatch"):
            validate_normalization_record(
                record,
                source_path=str(source),
                derivative_path=str(derivative),
                quality_path=str(quality),
                pdfinfo_path=self.tools["pdfinfo"],
                pdftotext_path=self.tools["pdftotext"],
                source_bundle_path=None,
            )

    def test_normalize_refuses_existing_outputs(self):
        source, quality, _ = self.inspect("BLANK")
        derivative = self.root / "exists.pdf"
        derivative.write_bytes(b"occupied")
        with self.assertRaisesRegex(ContractError, "overwrite"):
            normalize_document(
                source_path=str(source),
                quality_path=str(quality),
                output_pdf_path=str(derivative),
                output_record_path=str(self.root / "record.json"),
                pdfinfo_path=self.tools["pdfinfo"],
                pdftotext_path=self.tools["pdftotext"],
                pdftoppm_path=self.tools["pdftoppm"],
                tesseract_path=self.tools["tesseract"],
                pdfunite_path=self.tools["pdfunite"],
                generated_at="2026-08-05T00:01:00Z",
                source_bundle_path=None,
                dpi=300,
                languages="eng",
            )

    def test_tool_failure_cleans_temporary_and_published_outputs(self):
        source, quality, _ = self.inspect("BLANK")
        derivative = self.root / "failed.pdf"
        result = self.root / "failed.json"
        with mock.patch.dict(os.environ, {"FAKE_TESSERACT_FAIL": "1"}):
            with self.assertRaisesRegex(ContractError, "tesseract failed"):
                normalize_document(
                    source_path=str(source),
                    quality_path=str(quality),
                    output_pdf_path=str(derivative),
                    output_record_path=str(result),
                    pdfinfo_path=self.tools["pdfinfo"],
                    pdftotext_path=self.tools["pdftotext"],
                    pdftoppm_path=self.tools["pdftoppm"],
                    tesseract_path=self.tools["tesseract"],
                    pdfunite_path=self.tools["pdfunite"],
                    generated_at="2026-08-05T00:01:00Z",
                    source_bundle_path=None,
                    dpi=300,
                    languages="eng",
                )
        self.assertFalse(derivative.exists())
        self.assertFalse(result.exists())
        self.assertEqual(list(self.root.glob(".scholarly-normalization-*")), [])

    def test_missing_tool_is_structured_failure_without_outputs(self):
        source, quality, _ = self.inspect("BLANK")
        derivative = self.root / "missing.pdf"
        result = self.root / "missing.json"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            status = main(
                [
                    "normalize",
                    "--source",
                    str(source),
                    "--quality",
                    str(quality),
                    "--pdfinfo",
                    self.tools["pdfinfo"],
                    "--pdftotext",
                    self.tools["pdftotext"],
                    "--pdftoppm",
                    str(self.root / "not-installed"),
                    "--tesseract",
                    self.tools["tesseract"],
                    "--pdfunite",
                    self.tools["pdfunite"],
                    "--generated-at",
                    "2026-08-05T00:01:00Z",
                    "--output-pdf",
                    str(derivative),
                    "--output-record",
                    str(result),
                ]
            )
        failure = json.loads(stderr.getvalue())
        self.assertEqual(status, 2)
        self.assertEqual(failure["schema"], "ScholarlyDocumentNormalizationFailure/v1")
        self.assertEqual(failure["code"], "missing_tool")
        self.assertEqual(failure["missing_tools"], ["pdftoppm"])
        self.assertTrue(failure["temporary_artifacts_cleaned"])
        self.assertFalse(derivative.exists())
        self.assertFalse(result.exists())

    def test_native_and_column_sources_are_not_forced_through_ocr(self):
        for marker, message in (("NATIVE", "native_ok"), ("COLUMN", "column_risk")):
            with self.subTest(marker=marker):
                source, quality, _ = self.inspect(marker)
                with self.assertRaisesRegex(ContractError, message):
                    normalize_document(
                        source_path=str(source),
                        quality_path=str(quality),
                        output_pdf_path=str(self.root / f"{marker}.out.pdf"),
                        output_record_path=str(self.root / f"{marker}.out.json"),
                        pdfinfo_path=self.tools["pdfinfo"],
                        pdftotext_path=self.tools["pdftotext"],
                        pdftoppm_path=self.tools["pdftoppm"],
                        tesseract_path=self.tools["tesseract"],
                        pdfunite_path=self.tools["pdfunite"],
                        generated_at="2026-08-05T00:01:00Z",
                        source_bundle_path=None,
                        dpi=300,
                        languages="eng",
                    )


if __name__ == "__main__":
    unittest.main()
