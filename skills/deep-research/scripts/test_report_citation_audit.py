from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("report_citation_audit.py")
SPEC = importlib.util.spec_from_file_location("report_citation_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ReportCitationAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_json(self, name: str, value: Any) -> Path:
        path = self.root / name
        path.write_bytes(_canonical_bytes(value) + b"\n")
        os.chmod(path, 0o600)
        return path

    def write_text(self, name: str, value: str) -> Path:
        path = self.root / name
        path.write_text(value, encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    def run_main(self, args: list[str]):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = MODULE.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def statement_row(
        self,
        *,
        report_text: str,
        statement_text: str,
        statement_id: str,
        decision_impact: str = "high",
        status: str = "decisive",
    ) -> dict[str, Any]:
        start = report_text.index(statement_text)
        return {
            "statement_id": statement_id,
            "statement_text": statement_text,
            "start_char": start,
            "end_char": start + len(statement_text),
            "decision_impact": decision_impact,
            "status": status,
        }

    def citation_row(
        self,
        *,
        citation_id: str,
        statement_id: str,
        source_id: str,
        source_version: str,
        source_access: str,
        locator: str,
        relation: str,
        entailment: str,
        missing_qualifier: str,
        source_role: str,
        counterevidence_status: str,
        evidence_text: str,
    ) -> dict[str, Any]:
        evidence_path = self.write_text(f"{citation_id}.txt", evidence_text)
        return {
            "citation_id": citation_id,
            "statement_id": statement_id,
            "source_id": source_id,
            "source_version": source_version,
            "source_access": source_access,
            "locator": locator,
            "relation": relation,
            "entailment": entailment,
            "missing_qualifier": missing_qualifier,
            "source_role": source_role,
            "counterevidence_status": counterevidence_status,
            "evidence_path": str(evidence_path),
            "evidence_raw_sha256": _sha256(evidence_path.read_bytes()),
        }

    def build_bundle(
        self,
        *,
        report_text: str,
        statements: list[dict[str, Any]],
        citations: list[dict[str, Any]],
    ) -> tuple[Path, Path, Path, str, str, str]:
        final_report = {
            "schema": "ResearchReport/v1",
            "schema_version": "1",
            "report_id": "report-audit-1",
            "report_text": report_text,
            "statement_rows": statements,
        }
        draft_report = dict(final_report)
        final_path = self.write_json("final-report.json", final_report)
        draft_path = self.write_json("draft-report.json", draft_report)
        evidence_path = self.write_json(
            "evidence-set.json",
            {"schema": "ReportCitationSet/v1", "schema_version": "1", "citations": citations},
        )
        return (
            final_path,
            draft_path,
            evidence_path,
            _sha256(final_path.read_bytes()),
            _sha256(draft_path.read_bytes()),
            _sha256(evidence_path.read_bytes()),
        )

    def seal(
        self,
        final_path: Path,
        draft_path: Path,
        evidence_path: Path,
        final_pin: str,
        draft_pin: str,
        evidence_pin: str,
        output_path: Path,
    ) -> tuple[int, str, str]:
        return self.run_main(
            [
                "seal",
                "--final-report",
                str(final_path),
                "--draft-report",
                str(draft_path),
                "--evidence",
                str(evidence_path),
                "--evidence-raw-sha256",
                evidence_pin,
                "--final-report-raw-sha256",
                final_pin,
                "--draft-report-raw-sha256",
                draft_pin,
                "--output",
                str(output_path),
            ]
        )

    def validate(
        self,
        audit_path: Path,
        final_path: Path,
        draft_path: Path,
        final_pin: str,
        draft_pin: str,
        evidence_pin: str,
        audit_pin: str,
    ) -> tuple[int, dict[str, Any], str]:
        code, out, err = self.run_main(
            [
                "validate",
                "--audit",
                str(audit_path),
                "--final-report",
                str(final_path),
                "--draft-report",
                str(draft_path),
                "--final-report-raw-sha256",
                final_pin,
                "--draft-report-raw-sha256",
                draft_pin,
                "--evidence-raw-sha256",
                evidence_pin,
                "--audit-raw-sha256",
                audit_pin,
            ]
        )
        payload = None
        if out.strip():
            payload = json.loads(out)
        return code, payload, err

    def _audit_pin(self, audit_path: Path) -> str:
        return _sha256(audit_path.read_bytes())

    def test_report_word_drift_invalidates(self):
        report_text = "Claim alpha establishes baseline. Another sentence follows."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Claim alpha establishes baseline",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="snippet support",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, _ = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            audit_path,
        )
        self.assertEqual(code, 0)

        final_path.write_text(
            "Claim alpha establishes baseline and an extra clause. Another sentence follows.",
            encoding="utf-8",
        )
        os.chmod(final_path, 0o600)
        code, _, err = self.validate(
            audit_path,
            final_path,
            draft_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self._audit_pin(audit_path),
        )
        self.assertNotEqual(code, 0)
        self.assertIn("report raw pin mismatch", err)

    def test_half_supported_compound_statement_partial(self):
        report_text = "A compound report statement has partial evidence support."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="A compound report statement",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="e1",
            ),
            self.citation_row(
                citation_id="citation:2",
                statement_id="statement:1",
                source_id="source:2",
                source_version="v1",
                source_access="full_text",
                locator="doc p2",
                relation="supports",
                entailment="partial",
                missing_qualifier="missing boundary conditions",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="e2",
            ),
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, _ = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            audit_path,
        )
        self.assertEqual(code, 0)
        code, payload, _ = self.validate(
            audit_path,
            final_path,
            draft_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self._audit_pin(audit_path),
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["overall_status"], "partial")
        self.assertEqual(payload["statement_status"]["statement:1"], "partial")

    def test_missing_qualifier_alone_prevents_closure(self):
        report_text = "The bounded result requires an unstated condition."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="The bounded result requires an unstated condition",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="missing model boundary",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="exact full-text support with a missing boundary",
            )
        ]
        bundle = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, error = self.seal(*bundle, audit_path)
        self.assertEqual(code, 0, error)
        code, payload, error = self.validate(
            audit_path,
            bundle[0],
            bundle[1],
            bundle[3],
            bundle[4],
            bundle[5],
            self._audit_pin(audit_path),
        )
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["overall_status"], "partial")
        self.assertEqual(payload["statement_status"]["statement:1"], "partial")

    def test_abstract_only_decisive_rejected(self):
        report_text = "Abstract-only source cannot close a decisive statement."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Abstract-only source cannot close",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="abstract_only",
                locator="doc abstract",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="not_required",
                evidence_text="a",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        code, _, err = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self.root / "audit.json",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("abstract_only", err)

    def test_metadata_only_cannot_close_decisive_statement(self):
        report_text = "Metadata can orient but cannot close a decisive statement."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Metadata can orient",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="metadata_only",
                locator="catalog record",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="secondary",
                counterevidence_status="not_required",
                evidence_text="metadata record",
            )
        ]
        bundle = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, error = self.seal(*bundle, audit_path)
        self.assertEqual(code, 0, error)
        code, payload, error = self.validate(
            audit_path,
            bundle[0],
            bundle[1],
            bundle[3],
            bundle[4],
            bundle[5],
            self._audit_pin(audit_path),
        )
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["overall_status"], "partial")
        self.assertEqual(payload["statement_status"]["statement:1"], "partial")

    def test_fully_entailed_qualified_statement_can_complete(self):
        report_text = "The bounded result holds only under the stated assumptions."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="The bounded result holds only under the stated assumptions",
                statement_id="statement:1",
                status="qualified",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="p. 2",
                relation="qualifies",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="bounded full-text evidence",
            )
        ]
        bundle = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, error = self.seal(*bundle, audit_path)
        self.assertEqual(code, 0, error)
        code, payload, error = self.validate(
            audit_path,
            bundle[0],
            bundle[1],
            bundle[3],
            bundle[4],
            bundle[5],
            self._audit_pin(audit_path),
        )
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["overall_status"], "complete")
        self.assertEqual(payload["statement_status"]["statement:1"], "qualified")

    def test_missing_counterevidence_blocks_complete(self):
        report_text = "Counterevidence is tracked to avoid false completion."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Counterevidence is tracked",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p10",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="missing",
                evidence_text="support evidence",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, _ = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            audit_path,
        )
        self.assertEqual(code, 0)
        code, payload, _ = self.validate(
            audit_path,
            final_path,
            draft_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self._audit_pin(audit_path),
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["overall_status"], "partial")
        self.assertEqual(payload["statement_status"]["statement:1"], "partial")

    def test_evidence_hash_drift(self):
        report_text = "Evidence drift breaks replay."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Evidence drift breaks",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p3",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="evidence baseline",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, _ = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            audit_path,
        )
        self.assertEqual(code, 0)

        evidence_file = Path(citations[0]["evidence_path"])
        evidence_file.write_text("tampered", encoding="utf-8")
        os.chmod(evidence_file, 0o600)
        code, _, err = self.validate(
            audit_path,
            final_path,
            draft_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self._audit_pin(audit_path),
        )
        self.assertNotEqual(code, 0)
        self.assertIn("evidence_raw_sha256", err)

    def test_self_sealed_audit_rejected(self):
        report_text = "Self-reference should be rejected at validation time."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Self-reference should be rejected",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p12",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="support note",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, _ = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            audit_path,
        )
        self.assertEqual(code, 0)

        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        payload["private"]["evidence_files"]["citation:1"]["path"] = str(audit_path)
        payload["private"]["evidence_files"]["citation:1"]["sha256"] = _sha256(audit_path.read_bytes())
        payload = MODULE._seal_payload(payload)
        audit_path.write_bytes(MODULE.canonical_json_bytes(payload))
        os.chmod(audit_path, 0o600)

        code, _, err = self.validate(
            audit_path,
            final_path,
            draft_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self._audit_pin(audit_path),
        )
        self.assertNotEqual(code, 0)
        self.assertIn("audit artifact", err)

    def test_symlink_path_rejected(self):
        report_text = "Symlink report paths must be rejected."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Symlink report paths",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p15",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="support path",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        symlink_path = self.root / "final-symlink.json"
        symlink_path.symlink_to(final_path)
        code, _, err = self.seal(
            symlink_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self.root / "audit.json",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("symlink", err)

    def test_ancestor_symlink_path_rejected(self):
        report_text = "Ancestor symlink paths must be rejected."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Ancestor symlink paths",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="support path",
            )
        ]
        bundle = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        code, _, error = self.seal(
            alias / bundle[0].name,
            bundle[1],
            bundle[2],
            bundle[3],
            bundle[4],
            bundle[5],
            self.root / "audit.json",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("symlink", error)

    def test_hard_link_alias_cannot_reuse_report_as_evidence(self):
        report_text = "Hard-link aliases cannot substitute evidence."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Hard-link aliases cannot substitute evidence",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="replace this evidence",
            )
        ]
        bundle = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        manifest = json.loads(bundle[2].read_text(encoding="utf-8"))
        evidence_path = Path(manifest["citations"][0]["evidence_path"])
        evidence_path.unlink()
        os.link(bundle[0], evidence_path)
        manifest["citations"][0]["evidence_raw_sha256"] = _sha256(
            evidence_path.read_bytes()
        )
        bundle[2].write_bytes(_canonical_bytes(manifest) + b"\n")
        evidence_pin = _sha256(bundle[2].read_bytes())
        code, _, error = self.seal(
            bundle[0],
            bundle[1],
            bundle[2],
            bundle[3],
            bundle[4],
            evidence_pin,
            self.root / "audit.json",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("report inputs", error)

    def test_private_path_in_public_projection_rejected(self):
        report_text = "Public projection must not leak local paths."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Public projection must not leak local paths",
                statement_id="statement:1",
            )
        ]
        for index, locator in enumerate(
            (
                "/home/user/private/source.pdf",
                "../../private/source.pdf",
                r"\\server\share\source.pdf",
                "//server/share/source.pdf",
            )
        ):
            citations = [
                self.citation_row(
                    citation_id="citation:1",
                    statement_id="statement:1",
                    source_id="source:1",
                    source_version="v1",
                    source_access="full_text",
                    locator=locator,
                    relation="supports",
                    entailment="entailed",
                    missing_qualifier="",
                    source_role="primary",
                    counterevidence_status="represented",
                    evidence_text="ordinary evidence",
                )
            ]
            bundle = self.build_bundle(
                report_text=report_text,
                statements=statements,
                citations=citations,
            )
            code, _, error = self.seal(
                *bundle, self.root / f"audit-private-path-{index}.json"
            )
            self.assertNotEqual(code, 0)
            self.assertIn("private path-shaped", error)

    def test_duplicate_and_overlap_rejected(self):
        report_text = "first statement overlaps with second statement"
        statements = [
            {
                "statement_id": "statement:1",
                "statement_text": "first",
                "start_char": 0,
                "end_char": 5,
                "decision_impact": "high",
                "status": "decisive",
            },
            {
                "statement_id": "statement:2",
                "statement_text": "st statement o",
                "start_char": 3,
                "end_char": 17,
                "decision_impact": "high",
                "status": "decisive",
            },
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="e1",
            ),
            self.citation_row(
                citation_id="citation:2",
                statement_id="statement:2",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p2",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="e2",
            ),
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        code, _, err = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self.root / "audit.json",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("span overlap", err)

    def test_deterministic_two_builds(self):
        report_text = "Deterministic behavior requires identical digests."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Deterministic behavior",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="det",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        output_a = self.root / "audit-a.json"
        output_b = self.root / "audit-b.json"
        self.assertEqual(
            self.seal(
                final_path,
                draft_path,
                evidence_path,
                final_pin,
                draft_pin,
                evidence_pin,
                output_a,
            )[0],
            0,
        )
        self.assertEqual(
            self.seal(
                final_path,
                draft_path,
                evidence_path,
                final_pin,
                draft_pin,
                evidence_pin,
                output_b,
            )[0],
            0,
        )
        audit_a = json.loads(output_a.read_text(encoding="utf-8"))
        audit_b = json.loads(output_b.read_text(encoding="utf-8"))
        self.assertEqual(audit_a["audit_digest"], audit_b["audit_digest"])
        self.assertEqual(audit_a["projection_digest"], audit_b["projection_digest"])
        self.assertEqual(audit_a["projection"], audit_b["projection"])

    def test_cli_atomic(self):
        report_text = "Atomic outputs must not overwrite existing files."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Atomic outputs",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="atomic",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        output_path = self.root / "audit.json"
        code, _, _ = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            output_path,
        )
        self.assertEqual(code, 0)
        self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)

        code, _, err = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            output_path,
        )
        self.assertNotEqual(code, 0)
        self.assertIn("refusing to overwrite output", err)

    def test_atomic_writer_never_removes_a_concurrent_winner(self):
        output_path = self.root / "race-audit.json"
        winner = b"concurrent winner\n"

        def concurrent_link(
            _descriptor: int, _directory_descriptor: int, _output_name: bytes
        ) -> None:
            output_path.write_bytes(winner)
            os.chmod(output_path, 0o600)
            raise FileExistsError(str(output_path))

        with mock.patch.object(
            MODULE, "_link_unnamed_file", side_effect=concurrent_link
        ):
            with self.assertRaisesRegex(MODULE.ContractError, "refusing to overwrite"):
                MODULE._write_private_json(output_path, {"safe": True})
        self.assertEqual(output_path.read_bytes(), winner)
        self.assertEqual(list(self.root.glob(f".{output_path.name}.*")), [])

    def test_atomic_writer_rejects_symlink_swap_without_chmod_victim(self):
        output_path = self.root / "swap-audit.json"
        victim = self.root / "victim.txt"
        victim.write_text("victim", encoding="utf-8")
        victim.chmod(0o644)

        def symlink_swap(
            _descriptor: int, _directory_descriptor: int, _output_name: bytes
        ) -> None:
            output_path.symlink_to(victim)

        with mock.patch.object(
            MODULE, "_link_unnamed_file", side_effect=symlink_swap
        ):
            with self.assertRaisesRegex(
                MODULE.ContractError, "published output identity changed"
            ):
                MODULE._write_private_json(output_path, {"safe": True})
        self.assertTrue(output_path.is_symlink())
        self.assertEqual(victim.stat().st_mode & 0o777, 0o644)
        self.assertEqual(victim.read_text(encoding="utf-8"), "victim")

    def test_atomic_writer_portable_named_temp_fallback(self):
        output_path = self.root / "fallback-audit.json"
        real_open = MODULE.os.open

        def no_tmpfile(path, flags, mode=0o777, *, dir_fd=None):
            if hasattr(MODULE.os, "O_TMPFILE") and (
                flags & MODULE.os.O_TMPFILE
            ) == MODULE.os.O_TMPFILE:
                raise OSError(MODULE.errno.EOPNOTSUPP, "unsupported")
            if dir_fd is None:
                return real_open(path, flags, mode)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(MODULE.os, "open", side_effect=no_tmpfile):
            MODULE._write_private_json(output_path, {"safe": True})
        self.assertEqual(output_path.read_bytes(), b'{"safe":true}\n')
        self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob(f".{output_path.name}.*")), [])

    def test_atomic_writer_cleans_temporary_after_fsync_failure(self):
        output_path = self.root / "failed-audit.json"
        with mock.patch.object(MODULE.os, "fsync", side_effect=OSError("injected")):
            with self.assertRaisesRegex(OSError, "injected"):
                MODULE._write_private_json(output_path, {"safe": True})
        self.assertFalse(output_path.exists())
        self.assertEqual(list(self.root.glob(f".{output_path.name}.*")), [])

    def test_directory_fsync_failure_reports_published_output_without_retry_cleanup(self):
        output_path = self.root / "published-not-durable-audit.json"
        calls = 0
        real_fsync = MODULE.os.fsync

        def fail_second_fsync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected directory fsync failure")
            real_fsync(descriptor)

        with mock.patch.object(MODULE.os, "fsync", side_effect=fail_second_fsync):
            with self.assertRaisesRegex(OSError, "directory fsync failure"):
                MODULE._write_private_json(output_path, {"safe": True})
        self.assertTrue(output_path.is_file())
        self.assertFalse(output_path.is_symlink())
        self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(output_path.read_bytes(), b'{"safe":true}\n')

    def test_credential_shaped_values_are_rejected(self):
        for index, statement_text in enumerate(
            (
                "api_key=not-a-real-secret-value",
                "password: not-a-real-password",
                "https://example-user:not-a-real-password@example.invalid/path",
            )
        ):
            report_text = f"The report accidentally contains {statement_text}."
            statements = [
                self.statement_row(
                    report_text=report_text,
                    statement_text=statement_text,
                    statement_id="statement:1",
                )
            ]
            citations = [
                self.citation_row(
                    citation_id=f"citation:{index}",
                    statement_id="statement:1",
                    source_id="source:1",
                    source_version="v1",
                    source_access="full_text",
                    locator="p. 1",
                    relation="supports",
                    entailment="entailed",
                    missing_qualifier="",
                    source_role="primary",
                    counterevidence_status="represented",
                    evidence_text="ordinary evidence",
                )
            ]
            bundle = self.build_bundle(
                report_text=report_text,
                statements=statements,
                citations=citations,
            )
            code, _, error = self.seal(*bundle, self.root / f"secret-audit-{index}.json")
            self.assertNotEqual(code, 0)
            self.assertIn("credential-shaped value", error)

    def test_wrong_evidence_pin_rejected(self):
        report_text = "Incorrect evidence pin should be rejected."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Incorrect evidence pin",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="baseline",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        code, _, err = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            "0" * 64,
            self.root / "audit.json",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("evidence manifest raw pin mismatch", err)

    def test_wrong_audit_pin_rejected(self):
        report_text = "Wrong external audit pin should fail for self-sealed artifact."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Wrong external audit pin",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="audit baseline",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        audit_path = self.root / "audit.json"
        code, _, _ = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            audit_path,
        )
        self.assertEqual(code, 0)

        code, _, err = self.validate(
            audit_path,
            final_path,
            draft_path,
            final_pin,
            draft_pin,
            evidence_pin,
            "0" * 64,
        )
        self.assertNotEqual(code, 0)
        self.assertIn("audit raw pin mismatch", err)

    def test_unknown_top_level_report_keys_rejected(self):
        report_text = "Unknown top-level keys should be rejected."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Unknown top-level keys",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="evidence one",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )

        final_report = json.loads(final_path.read_text(encoding="utf-8"))
        final_report["unexpected_field"] = "x"
        final_path.write_bytes(_canonical_bytes(final_report) + b"\n")
        final_pin = _sha256(final_path.read_bytes())
        code, _, err = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self.root / "audit-report.json",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("exact required keys", err)

    def test_unknown_top_level_evidence_keys_rejected(self):
        report_text = "Evidence unknown top-level keys should be rejected."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Evidence unknown top-level keys",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="evidence one",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["unexpected_field"] = "x"
        evidence_path.write_bytes(_canonical_bytes(evidence) + b"\n")
        evidence_pin = _sha256(evidence_path.read_bytes())
        code, _, err = self.seal(
            final_path,
            draft_path,
            evidence_path,
            final_pin,
            draft_pin,
            evidence_pin,
            self.root / "audit-evidence.json",
        )
        self.assertNotEqual(code, 0)
        self.assertIn("exact required keys", err)

    def test_stable_read_detects_change(self):
        report_text = "Stable-read detection should fail on mutation."
        statements = [
            self.statement_row(
                report_text=report_text,
                statement_text="Stable-read detection",
                statement_id="statement:1",
            )
        ]
        citations = [
            self.citation_row(
                citation_id="citation:1",
                statement_id="statement:1",
                source_id="source:1",
                source_version="v1",
                source_access="full_text",
                locator="doc p1",
                relation="supports",
                entailment="entailed",
                missing_qualifier="",
                source_role="primary",
                counterevidence_status="represented",
                evidence_text="evidence",
            )
        ]
        final_path, draft_path, evidence_path, final_pin, draft_pin, evidence_pin = self.build_bundle(
            report_text=report_text,
            statements=statements,
            citations=citations,
        )

        original_fstat = MODULE.os.fstat
        calls: dict[str, int] = {"count": 0}

        def unstable_fstat(descriptor: int):
            calls["count"] += 1
            result = original_fstat(descriptor)
            if calls["count"] == 2:
                values = list(result)
                values[8] = result.st_mtime + 1
                return os.stat_result(values)
            return result

        with mock.patch.object(MODULE.os, "fstat", side_effect=unstable_fstat):
            code, _, err = self.seal(
                final_path,
                draft_path,
                evidence_path,
                final_pin,
                draft_pin,
                evidence_pin,
                self.root / "audit-stable.json",
            )
            self.assertNotEqual(code, 0)
            self.assertIn("changed during read", err)

if __name__ == "__main__":
    unittest.main()
