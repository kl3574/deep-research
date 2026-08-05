#!/usr/bin/env python3
"""Tests for PaperSourceBundle/v1 source rooting."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
from unittest import TestCase, main
from subprocess import CompletedProcess
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).with_name("paper_source_bundle.py")
SPEC = importlib.util.spec_from_file_location("paper_source_bundle", SCRIPT_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
EXAMPLE_PATH = SCRIPT_PATH.parent.parent / "examples" / "paper_source_bundle.example.json"


class PaperSourceBundleTests(TestCase):
    def setUp(self) -> None:
        self.generated_at = "2026-08-05T00:00:00Z"

    def _build_text_bundle(self, tmp_path: Path, content: str) -> tuple[dict, str]:
        tmp_path.mkdir(parents=True, exist_ok=True)
        source = tmp_path / "paper.txt"
        source.write_text(content, encoding="utf-8")
        bundle_path = tmp_path / "bundle.json"
        manifest = module.build_bundle(
            source=str(source),
            output=str(bundle_path),
            generated_at=self.generated_at,
        )
        return manifest, str(source)

    def test_deterministic_build_is_stable(self) -> None:
        content = "alpha\n\fbeta\n\fgamma"
        with self.subTest("first"):
            pass
        first, _ = self._build_text_bundle(Path("/tmp/paper_bundle_1"), content)
        second, _ = self._build_text_bundle(Path("/tmp/paper_bundle_2"), content)
        self.assertEqual(first["bundle_digest"], second["bundle_digest"])
        self.assertEqual(first["bundle_id"], second["bundle_id"])

    def test_source_and_page_tamper_failures(self) -> None:
        source = Path("/tmp/paper_source_tamper/paper.txt")
        manifest, source_path = self._build_text_bundle(source.parent, "page-one\n\fpage-two")
        self.assertEqual(manifest["source"]["name"], "paper.txt")
        source.write_text("tampered", encoding="utf-8")
        with self.assertRaises(module.ContractError):
            module.verify_bundle(bundle=str(source.parent / "bundle.json"), source=str(source))
        page_path = source.parent / manifest["pages"][0]["artifact_path"]
        page_path.write_text(page_path.read_text(encoding="utf-8") + "x", encoding="utf-8")
        with self.assertRaises(module.ContractError):
            module.verify_bundle(bundle=str(source.parent / "bundle.json"), source=str(source))

    def test_locate_rejects_bad_offsets(self) -> None:
        manifest, source_path = self._build_text_bundle(Path("/tmp/paper_bundle_offsets"), "a\n\fbcd")
        page_one = manifest["pages"][0]
        path = Path(source_path).parent
        with self.assertRaises(module.ContractError):
            module.locate_span(
                bundle=str(path / "bundle.json"),
                page=1,
                start_char=0,
                end_char=page_one["char_count"] + 1,
            )
        with self.assertRaises(module.ContractError):
            module.locate_span(
                bundle=str(path / "bundle.json"),
                page=1,
                start_char=5,
                end_char=3,
            )

    def test_locate_rejects_mutated_page_artifact(self) -> None:
        manifest, source_path = self._build_text_bundle(Path("/tmp/paper_bundle_locate_mutation"), "abc\fdef")
        path = Path(source_path).parent
        page_path = path / manifest["pages"][0]["artifact_path"]
        page_path.write_text(page_path.read_text(encoding="utf-8") + "X", encoding="utf-8")
        with self.assertRaises(module.ContractError):
            module.locate_span(
                bundle=str(path / "bundle.json"),
                page=1,
                start_char=0,
                end_char=1,
            )

    def test_symlink_source_and_path_escape_fail(self) -> None:
        workspace = Path("/tmp/paper_bundle_symlink")
        source = workspace / "real.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("abc\fdef", encoding="utf-8")
        linked = workspace / "link.txt"
        if linked.exists():
            linked.unlink()
        os.symlink(str(source), str(linked))
        with self.assertRaises(module.ContractError):
            module.build_bundle(source=str(linked), output=str(workspace / "bundle.json"))

        manifest, source_path = self._build_text_bundle(workspace, "abc\fdef")
        bad = copy.deepcopy(manifest)
        bad["pages"][0]["artifact_path"] = "../evil.txt"
        bundle_path = workspace / "bundle_tamper.json"
        bundle_path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(module.ContractError):
            module.verify_bundle(bundle=str(bundle_path), source=source_path)

    def test_verify_rejects_symlink_artifact_component(self) -> None:
        workspace = Path("/tmp/paper_bundle_artifact_component")
        manifest, source_path = self._build_text_bundle(workspace, "abc\fdef")
        alias = workspace / "alias_pages"
        if alias.exists():
            if alias.is_symlink() or alias.is_file():
                alias.unlink()
        os.symlink("pages", str(alias))
        mutated = copy.deepcopy(manifest)
        mutated["pages"][0]["artifact_path"] = "alias_pages/page-0001.txt"
        bundle_path = workspace / "bundle_artifact_component.json"
        bundle_path.write_text(json.dumps(mutated), encoding="utf-8")
        with self.assertRaises(module.ContractError):
            module.verify_bundle(bundle=str(bundle_path), source=source_path)

    def test_verify_rejects_payload_rewrite_without_source_change(self) -> None:
        workspace = Path("/tmp/paper_bundle_rewrite_payload")
        manifest, source_path = self._build_text_bundle(workspace, "abc\fdef")
        workspace_path = Path(source_path).parent
        tampered = copy.deepcopy(manifest)

        tampered_path = workspace_path / tampered["pages"][0]["artifact_path"]
        tampered_payload = "tampered"
        tampered_bytes = tampered_payload.encode("utf-8")
        tampered_path.write_bytes(tampered_bytes)
        tampered["pages"][0]["artifact_sha256"] = module.sha256_hex(tampered_bytes)
        tampered["pages"][0]["byte_count"] = len(tampered_bytes)
        tampered["pages"][0]["char_count"] = len(tampered_payload)
        tampered["bundle_digest"] = module.canonical_bundle_digest(tampered)
        tampered["bundle_id"] = module.bundle_id(tampered["bundle_digest"])

        bundle_path = workspace_path / "bundle_rewritten.json"
        bundle_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(module.ContractError):
            module.verify_bundle(bundle=str(bundle_path), source=source_path)

    def test_verify_idempotent(self) -> None:
        manifest, source_path = self._build_text_bundle(Path("/tmp/paper_bundle_verify"), "one\fsecond")
        bundle_path = Path(source_path).parent / "bundle.json"
        result_one = module.verify_bundle(bundle=str(bundle_path), source=source_path)
        result_two = module.verify_bundle(bundle=str(bundle_path), source=source_path)
        self.assertEqual(result_one["bundle_id"], result_two["bundle_id"])
        self.assertEqual(result_one["bundle_digest"], result_two["bundle_digest"])

    def test_text_multipage_form_feed(self) -> None:
        manifest, source_path = self._build_text_bundle(Path("/tmp/paper_bundle_form_feed"), "p1\fp2\fp3")
        self.assertEqual(manifest["page_count"], 3)
        page_texts = [int(item["char_count"]) for item in manifest["pages"]]
        self.assertEqual(page_texts, [2, 2, 2])
        path = Path(source_path).parent
        locate = module.locate_span(bundle=str(path / "bundle.json"), page=2, start_char=0, end_char=1)
        self.assertEqual(locate["page"], 2)
        self.assertTrue(locate["span_hash"])

    def test_missing_poppler_tools_are_honest(self) -> None:
        fake_pdf = Path("/tmp/paper_bundle_missing_poppler/paper.pdf")
        fake_pdf.parent.mkdir(parents=True, exist_ok=True)
        fake_pdf.write_text("%PDF-1.7 fake", encoding="utf-8")

        with patch.object(module.shutil, "which") as which:
            which.side_effect = lambda name: None
            with self.assertRaises(module.ContractError):
                module.build_bundle(source=str(fake_pdf), output=str(fake_pdf.with_suffix(".json")))

    def test_example_manifest_roundtrip(self) -> None:
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        fixture_source = "alpha\fbeta"
        fixture_pages = ["alpha", "beta"]

        self.assertEqual(example["source"]["name"], "paper.txt")
        self.assertEqual(example["source"]["size_bytes"], len(fixture_source.encode("utf-8")))
        self.assertEqual(example["source"]["source_sha256"], module.sha256_hex(fixture_source.encode("utf-8")))
        self.assertEqual(example["page_count"], len(fixture_pages))
        for index, text in enumerate(fixture_pages, start=1):
            page_key = f"page-{index:04d}"
            artifact_path = f"pages/{page_key}.txt"
            self.assertEqual(example["pages"][index - 1]["artifact_path"], artifact_path)
            self.assertEqual(example["pages"][index - 1]["byte_count"], len(text.encode("utf-8")))
            self.assertEqual(example["pages"][index - 1]["char_count"], len(text))
            self.assertEqual(
                example["pages"][index - 1]["artifact_sha256"],
                module.sha256_hex(text.encode("utf-8")),
            )

        workspace = Path("/tmp/paper_source_bundle_example_verify")
        source_path = workspace / example["source"]["name"]
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(fixture_source, encoding="utf-8")
        for index, page in enumerate(fixture_pages, start=1):
            page_path = workspace / f"pages/page-{index:04d}.txt"
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(page, encoding="utf-8")
        bundle_path = workspace / "bundle.json"
        bundle_path.write_text(json.dumps(example), encoding="utf-8")
        result = module.verify_bundle(bundle=str(bundle_path), source=str(source_path))
        self.assertEqual(result["bundle_id"], example["bundle_id"])

    def test_pdf_build_with_mocked_poppler(self) -> None:
        pdf_path = Path("/tmp/paper_bundle_pdf/paper.pdf")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text("%PDF-1.7 fake", encoding="utf-8")
        workspace = pdf_path.parent
        bundle_path = workspace / "bundle.json"

        fake_tools = {
            "pdfinfo": "/tmp/fake_pdfinfo",
            "pdftotext": "/tmp/fake_pdftotext",
            "pdftoppm": "/tmp/fake_pdftoppm",
        }

        def fake_which(name: str) -> str:
            return fake_tools[name]

        def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            command = str(cmd[0])
            if "--version" in cmd:
                return CompletedProcess(cmd, 0, stdout=f"{Path(command).name} version 1.0")
            if command == fake_tools["pdfinfo"]:
                if cmd[1:] == [str(pdf_path)]:
                    return CompletedProcess(cmd, 0, stdout="Pages: 2")
                return CompletedProcess(cmd, 0, stdout="")
            if command == fake_tools["pdftotext"]:
                page = int(cmd[cmd.index("-f") + 1])
                return CompletedProcess(cmd, 0, stdout=f"page {page} text")
            if command == fake_tools["pdftoppm"]:
                destination = Path(cmd[-1])
                destination.with_suffix(".png").write_bytes(b"PNG")
                return CompletedProcess(cmd, 0, stdout="")
            raise AssertionError(f"unexpected command: {cmd}")

        with patch.object(module, "shutil") as fake_shutil, patch.object(
            module.subprocess, "run"
        ) as run:
            fake_shutil.which.side_effect = fake_which
            run.side_effect = fake_run
            manifest = module.build_bundle(
                source=str(pdf_path),
                output=str(bundle_path),
                generated_at=self.generated_at,
                render_pages=True,
            )

        self.assertEqual(manifest["source"]["format"], "pdf")
        self.assertEqual(manifest["page_count"], 2)
        self.assertEqual(len(manifest["rendered_pages"]), 2)

    def test_verify_pdf_rejects_mutated_page_payload(self) -> None:
        pdf_path = Path("/tmp/paper_bundle_verify_pdf_mutation/paper.pdf")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text("%PDF-1.7 fake", encoding="utf-8")
        workspace = pdf_path.parent
        bundle_path = workspace / "bundle.json"

        fake_tools = {
            "pdfinfo": "/tmp/fake_pdfinfo_verify",
            "pdftotext": "/tmp/fake_pdftotext_verify",
            "pdftoppm": "/tmp/fake_pdftoppm_verify",
        }

        def fake_which(name: str) -> str:
            return fake_tools[name]

        def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            command = str(cmd[0])
            if "--version" in cmd:
                return CompletedProcess(cmd, 0, stdout=f"{Path(command).name} version 1.0")
            if command == fake_tools["pdfinfo"]:
                if cmd[1:] == [str(pdf_path)]:
                    return CompletedProcess(cmd, 0, stdout="Pages: 2")
                return CompletedProcess(cmd, 0, stdout="")
            if command == fake_tools["pdftotext"]:
                page = int(cmd[cmd.index("-f") + 1])
                return CompletedProcess(cmd, 0, stdout=f"page {page} text")
            if command == fake_tools["pdftoppm"]:
                destination = Path(cmd[-1])
                destination.with_suffix(".png").write_bytes(b"PNG")
                return CompletedProcess(cmd, 0, stdout="")
            raise AssertionError(f"unexpected command: {cmd}")

        with patch.object(module, "shutil") as fake_shutil, patch.object(
            module.subprocess, "run"
        ) as run:
            fake_shutil.which.side_effect = fake_which
            run.side_effect = fake_run
            manifest = module.build_bundle(
                source=str(pdf_path),
                output=str(bundle_path),
                generated_at=self.generated_at,
            )

        tampered = copy.deepcopy(manifest)
        page_path = workspace / tampered["pages"][0]["artifact_path"]
        tampered_payload = "tampered"
        page_path.write_text(tampered_payload, encoding="utf-8")
        tampered_bytes = tampered_payload.encode("utf-8")
        tampered["pages"][0]["artifact_sha256"] = module.sha256_hex(tampered_bytes)
        tampered["pages"][0]["byte_count"] = len(tampered_bytes)
        tampered["pages"][0]["char_count"] = len(tampered_payload)
        tampered["bundle_digest"] = module.canonical_bundle_digest(tampered)
        tampered["bundle_id"] = module.bundle_id(tampered["bundle_digest"])
        tampered_bundle = workspace / "bundle_tampered.json"
        tampered_bundle.write_text(json.dumps(tampered), encoding="utf-8")

        with patch.object(module, "shutil") as fake_shutil, patch.object(
            module.subprocess, "run"
        ) as run:
            fake_shutil.which.side_effect = fake_which
            run.side_effect = fake_run
            with self.assertRaises(module.ContractError):
                module.verify_bundle(bundle=str(tampered_bundle), source=str(pdf_path))

    def test_verify_rejects_mutated_rendered_page_same_length(self) -> None:
        pdf_path = Path("/tmp/paper_bundle_verify_rendered_mutation/paper.pdf")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text("%PDF-1.7 fake", encoding="utf-8")
        workspace = pdf_path.parent
        bundle_path = workspace / "bundle.json"
        fake_tools = {
            "pdfinfo": "/tmp/fake_pdfinfo_render",
            "pdftotext": "/tmp/fake_pdftotext_render",
            "pdftoppm": "/tmp/fake_pdftoppm_render",
        }

        def fake_which(name: str) -> str:
            return fake_tools[name]

        def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            command = str(cmd[0])
            if "--version" in cmd:
                return CompletedProcess(cmd, 0, stdout=f"{Path(command).name} version 1.0")
            if command == fake_tools["pdfinfo"]:
                if cmd[1:] == [str(pdf_path)]:
                    return CompletedProcess(cmd, 0, stdout="Pages: 2")
                return CompletedProcess(cmd, 0, stdout="")
            if command == fake_tools["pdftotext"]:
                page = int(cmd[cmd.index("-f") + 1])
                return CompletedProcess(cmd, 0, stdout=f"page {page} text")
            if command == fake_tools["pdftoppm"]:
                destination = Path(cmd[-1])
                destination.with_suffix(".png").write_bytes(b"AAAA")
                return CompletedProcess(cmd, 0, stdout="")
            raise AssertionError(f"unexpected command: {cmd}")

        with patch.object(module, "shutil") as fake_shutil, patch.object(
            module.subprocess, "run"
        ) as run:
            fake_shutil.which.side_effect = fake_which
            run.side_effect = fake_run
            manifest = module.build_bundle(
                source=str(pdf_path),
                output=str(bundle_path),
                generated_at=self.generated_at,
                render_pages=True,
            )

        rendered_path = workspace / manifest["rendered_pages"][0]["artifact_path"]
        rendered_path.write_bytes(b"BBBB")
        with self.assertRaises(module.ContractError):
            module.verify_bundle(bundle=str(bundle_path), source=str(pdf_path))

    def test_build_preserves_existing_bundle_on_invalid_utf8(self) -> None:
        workspace = Path("/tmp/paper_bundle_preserve_invalid_utf8")
        source = workspace / "paper.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("valid", encoding="utf-8")
        bundle_path = workspace / "bundle.json"
        module.build_bundle(source=str(source), output=str(bundle_path), generated_at=self.generated_at)
        before_path = bundle_path.read_text(encoding="utf-8")
        source.write_bytes(b"\xff\xfe")
        with self.assertRaises(module.ContractError):
            module.build_bundle(source=str(source), output=str(bundle_path), generated_at=self.generated_at)
        self.assertEqual(bundle_path.read_text(encoding="utf-8"), before_path)
        self.assertEqual(json.loads(bundle_path.read_text(encoding="utf-8")), json.loads(before_path))

    def test_build_preserves_existing_bundle_on_pdf_extract_failure(self) -> None:
        workspace = Path("/tmp/paper_bundle_preserve_pdf_extract")
        source = workspace / "paper.pdf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("%PDF-1.7 fake", encoding="utf-8")
        bundle_path = workspace / "bundle.json"

        fake_tools = {
            "pdfinfo": "/tmp/fake_pdfinfo_extract",
            "pdftotext": "/tmp/fake_pdftotext_extract",
        }

        def fake_which(name: str) -> str:
            if name in fake_tools:
                return fake_tools[name]
            return None

        def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            command = str(cmd[0])
            if "--version" in cmd:
                return CompletedProcess(cmd, 0, stdout=f"{Path(command).name} version 1.0")
            if command == fake_tools["pdfinfo"]:
                return CompletedProcess(cmd, 0, stdout="Pages: 1")
            if command == fake_tools["pdftotext"]:
                return CompletedProcess(cmd, 0, stdout="page 1 text")
            raise AssertionError(f"unexpected command: {cmd}")

        def fake_fail_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            command = str(cmd[0])
            if "--version" in cmd:
                return CompletedProcess(cmd, 0, stdout=f"{Path(command).name} version 1.0")
            if command == fake_tools["pdfinfo"]:
                return CompletedProcess(cmd, 0, stdout="Pages: 1")
            if command == fake_tools["pdftotext"]:
                return CompletedProcess(cmd, 1, stdout="", stderr="pdftotext fail")
            raise AssertionError(f"unexpected command: {cmd}")

        with patch.object(module, "shutil") as fake_shutil, patch.object(
            module.subprocess, "run"
        ) as run:
            fake_shutil.which.side_effect = fake_which
            run.side_effect = fake_run
            module.build_bundle(
                source=str(source),
                output=str(bundle_path),
                generated_at=self.generated_at,
                render_pages=False,
            )

        before_bundle_text = bundle_path.read_text(encoding="utf-8")
        with patch.object(module, "shutil") as fake_shutil, patch.object(
            module.subprocess, "run"
        ) as run:
            fake_shutil.which.side_effect = fake_which
            run.side_effect = fake_fail_run
            with self.assertRaises(module.ContractError):
                module.build_bundle(source=str(source), output=str(bundle_path), generated_at=self.generated_at)
        self.assertEqual(bundle_path.read_text(encoding="utf-8"), before_bundle_text)

    def test_build_preserves_existing_bundle_on_replace_failure(self) -> None:
        workspace = Path("/tmp/paper_bundle_replace_failure")
        source = workspace / "paper.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("preserve", encoding="utf-8")
        bundle_path = workspace / "bundle.json"
        module.build_bundle(
            source=str(source),
            output=str(bundle_path),
            generated_at=self.generated_at,
        )
        before_bytes = bundle_path.read_text(encoding="utf-8")
        source.write_text("preserve-v2", encoding="utf-8")

        original_replace = module.os.replace
        def failing_replace(src: Path, dst: Path) -> None:
            if "paper-source-bundle-staging-" in str(src) and str(dst) == str(bundle_path):
                raise OSError("forced replace failure")
            return original_replace(src, dst)

        with patch.object(module.os, "replace", side_effect=failing_replace):
            with self.assertRaises(module.ContractError):
                module.build_bundle(source=str(source), output=str(bundle_path), generated_at=self.generated_at)
        self.assertEqual(bundle_path.read_text(encoding="utf-8"), before_bytes)

    def test_build_cleans_staging_after_partial_pdf_extract_failure(self) -> None:
        workspace = Path("/tmp/paper_bundle_pdf_partial_extract")
        pdf_path = workspace / "paper.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text("%PDF-1.7 fake", encoding="utf-8")
        bundle_path = workspace / "bundle.json"

        fake_tools = {
            "pdfinfo": "/tmp/fake_pdfinfo_partial_extract",
            "pdftotext": "/tmp/fake_pdftotext_partial_extract",
        }

        def fake_which(name: str) -> str:
            return fake_tools[name]

        def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            command = str(cmd[0])
            if "--version" in cmd:
                return CompletedProcess(cmd, 0, stdout=f"{Path(command).name} version 1.0")
            if command == fake_tools["pdfinfo"]:
                return CompletedProcess(cmd, 0, stdout="Pages: 2")
            if command == fake_tools["pdftotext"]:
                page = int(cmd[cmd.index("-f") + 1])
                if page == 1:
                    return CompletedProcess(cmd, 0, stdout=f"page {page} text")
                return CompletedProcess(cmd, 1, stdout="", stderr="pdftotext failed for page")
            raise AssertionError(f"unexpected command: {cmd}")

        with patch.object(module, "shutil") as fake_shutil, patch.object(
            module.subprocess, "run"
        ) as run:
            fake_shutil.which.side_effect = fake_which
            run.side_effect = fake_run
            with self.assertRaises(module.ContractError):
                module.build_bundle(
                    source=str(pdf_path),
                    output=str(bundle_path),
                    generated_at=self.generated_at,
                    render_pages=False,
                )

        self.assertFalse(bundle_path.exists())
        self.assertFalse(any(workspace.glob(".paper-source-bundle-staging-*")))
        self.assertFalse((workspace / "pages").exists())

    def test_build_recoverable_backup_on_publish_and_restore_failure(self) -> None:
        workspace = Path("/tmp/paper_bundle_recoverable_backup")
        source = workspace / "paper.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("preserve", encoding="utf-8")
        bundle_path = workspace / "bundle.json"
        module.build_bundle(source=str(source), output=str(bundle_path), generated_at=self.generated_at)
        before_bytes = bundle_path.read_text(encoding="utf-8")
        source.write_text("preserve-v2", encoding="utf-8")

        original_replace = module.os.replace

        def failing_replace(src: Path, dst: Path) -> None:
            src_path = str(src)
            dst_path = str(dst)
            if dst_path == str(bundle_path) and ".paper-source-bundle-staging-" in src_path:
                raise OSError("forced publish failure")
            if dst_path == str(bundle_path) and ".paper-source-bundle-backup-" in src_path:
                raise OSError("forced restore failure")
            return original_replace(src, dst)

        with patch.object(module.os, "replace", side_effect=failing_replace):
            with self.assertRaises(module.ContractError) as context:
                module.build_bundle(source=str(source), output=str(bundle_path), generated_at=self.generated_at)
        message = str(context.exception)
        self.assertIn("recoverable backup at ", message)
        backup_path = Path(message.split("recoverable backup at ", 1)[1].strip())
        self.assertTrue(backup_path.exists())

        recovered_backup = module.recover_bundle(output=str(bundle_path), backup=str(backup_path))
        self.assertEqual(bundle_path.read_text(encoding="utf-8"), before_bytes)
        self.assertIn(recovered_backup, str(backup_path))
        self.assertFalse(any(workspace.glob(".paper-source-bundle-backup-*")))

    def test_verify_rejects_dangling_temp_artifact(self) -> None:
        manifest, source_path = self._build_text_bundle(
            Path("/tmp/paper_bundle_verify_dangling_artifact"),
            "one\ftwo",
        )
        workspace_path = Path(source_path).parent
        tampered = copy.deepcopy(manifest)
        tampered["pages"][0]["artifact_path"] = "pages/page-9999.txt"
        tampered["bundle_digest"] = module.canonical_bundle_digest(tampered)
        tampered["bundle_id"] = module.bundle_id(tampered["bundle_digest"])

        bundle_path = workspace_path / "bundle_dangling.json"
        bundle_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(module.ContractError):
            module.verify_bundle(bundle=str(bundle_path), source=source_path)

    def test_build_rejects_symlink_parent(self) -> None:
        workspace = Path("/tmp/paper_bundle_symlink_parent")
        real_parent = workspace / "real"
        link_parent = workspace / "linked-output"
        source_path = real_parent / "paper.txt"
        real_parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("safe", encoding="utf-8")
        if link_parent.exists():
            link_parent.unlink()
        os.symlink(str(real_parent), str(link_parent))
        with self.assertRaises(module.ContractError):
            module.build_bundle(source=str(source_path), output=str(link_parent / "bundle.json"))

    def test_reject_unknown_manifest_fields(self) -> None:
        manifest, source_path = self._build_text_bundle(Path("/tmp/paper_bundle_unknown_field"), "abc")
        tampered = {**manifest, "unexpected": "value"}
        with self.assertRaises(module.ContractError):
            module.validate_bundle(tampered)

        tampered_bundle_path = Path(source_path).parent / "bundle_unknown.json"
        tampered_bundle_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(module.ContractError):
            module.verify_bundle(bundle=str(tampered_bundle_path), source=source_path)

    def test_validate_roundtrip_is_idempotent(self) -> None:
        manifest, _ = self._build_text_bundle(Path("/tmp/paper_bundle_validate_roundtrip"), "abc\fbde")
        validated_once = module.validate_bundle(manifest)
        validated_twice = module.validate_bundle(validated_once)
        self.assertEqual(validated_once, validated_twice)

    def test_stale_artifacts_are_replaced(self) -> None:
        workspace = Path("/tmp/paper_bundle_stale")
        source = workspace / "paper.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("page-one", encoding="utf-8")
        stale = workspace / "pages" / "page-0009.txt"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("stale", encoding="utf-8")
        manifest, source_path = self._build_text_bundle(workspace, "fresh")
        self.assertFalse((workspace / "pages" / "page-0009.txt").exists())

if __name__ == "__main__":
    main()
