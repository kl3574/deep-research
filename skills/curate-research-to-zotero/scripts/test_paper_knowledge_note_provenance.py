from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
NOTE_INPUT_EXAMPLE = (
    SCRIPT_DIR.parents[1]
    / "learn-from-papers"
    / "examples"
    / "paper_understanding_note_input.example.json"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


note = load_module("paper_knowledge_note", SCRIPT_DIR / "paper_knowledge_note.py")
prepare = load_module(
    "provenance_prepare_note_migration",
    SCRIPT_DIR / "prepare_note_migration.py",
)
update = load_module(
    "provenance_update_existing_note",
    SCRIPT_DIR / "update_existing_note.py",
)
desktop = load_module(
    "provenance_render_zotero_desktop_runner",
    SCRIPT_DIR / "render_zotero_desktop_runner.py",
)


class FakeLearn:
    def __init__(self, expected: dict[str, object]) -> None:
        self.expected = expected

    def validate_note_input_projection(
        self,
        understanding: dict[str, object],
        validation_record: dict[str, object],
        **paths: str,
    ) -> dict[str, object]:
        if validation_record.get("source_binding_verified") is not True:
            raise ValueError("source binding was not live verified")
        if set(paths) != {
            "source_bundle_path",
            "source_path",
            "dossier_path",
        }:
            raise ValueError("live source paths are incomplete")
        regenerated = copy.deepcopy(self.expected)
        regenerated["understanding_binding"] = {
            "understanding_id": understanding["understanding_id"],
            "understanding_digest": understanding["understanding_digest"],
            "validation_record_id": validation_record["record_id"],
            "validation_record_digest": validation_record["record_digest"],
        }
        return regenerated


class ProvenanceGateTests(unittest.TestCase):
    def _context(self, root: Path) -> tuple[dict[str, Path], FakeLearn]:
        root.mkdir(parents=True, exist_ok=True)
        expected = json.loads(NOTE_INPUT_EXAMPLE.read_text(encoding="utf-8"))
        binding = expected["understanding_binding"]
        understanding = {
            "schema": "PaperUnderstanding/v1",
            "understanding_id": binding["understanding_id"],
            "understanding_digest": binding["understanding_digest"],
        }
        validation = {
            "schema": "PaperUnderstandingValidation/v1",
            "record_id": binding["validation_record_id"],
            "record_digest": binding["validation_record_digest"],
            "source_binding_verified": True,
        }
        paths = {
            "note_input": root / "note-input.json",
            "understanding": root / "understanding.json",
            "validation_record": root / "validation.json",
            "source_bundle": root / "bundle.json",
            "source": root / "source.pdf",
            "dossier": root / "dossier.json",
        }
        paths["note_input"].write_text(
            json.dumps(expected, ensure_ascii=False),
            encoding="utf-8",
        )
        paths["understanding"].write_text(
            json.dumps(understanding),
            encoding="utf-8",
        )
        paths["validation_record"].write_text(
            json.dumps(validation),
            encoding="utf-8",
        )
        paths["source_bundle"].write_text(
            json.dumps({"schema": "PaperSourceBundle/v1"}),
            encoding="utf-8",
        )
        paths["source"].write_bytes(b"%PDF-bound-source")
        paths["dossier"].write_text(
            json.dumps({"schema": "PaperReadingDossier/v1"}),
            encoding="utf-8",
        )
        return paths, FakeLearn(expected)

    @staticmethod
    def _build(paths: dict[str, Path]):
        return note.build_live_projection(
            note_input_path=paths["note_input"],
            understanding_path=paths["understanding"],
            validation_record_path=paths["validation_record"],
            source_bundle_path=paths["source_bundle"],
            source_path=paths["source"],
            dossier_path=paths["dossier"],
        )

    def test_live_projection_derives_ids_and_keeps_paths_out_of_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths, fake = self._context(Path(temp).resolve())
            with mock.patch.object(note, "_load_learn_module", return_value=fake):
                normalized, rendered, manifest = self._build(paths)
            self.assertEqual(
                manifest["understanding_binding"],
                normalized["understanding_binding"],
            )
            self.assertEqual(
                set(manifest["upstream_provenance"]),
                note.UPSTREAM_PROVENANCE_KEYS,
            )
            for path in paths.values():
                self.assertNotIn(str(path), rendered)

    def test_arbitrary_ids_and_forged_verified_flag_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            paths, fake = self._context(root)
            supplied = json.loads(paths["note_input"].read_text(encoding="utf-8"))
            supplied["understanding_binding"]["understanding_id"] = (
                "paper-understanding-attacker"
            )
            paths["note_input"].write_text(json.dumps(supplied), encoding="utf-8")
            with mock.patch.object(note, "_load_learn_module", return_value=fake):
                with self.assertRaisesRegex(note.ContractError, "exactly match"):
                    self._build(paths)

            paths, fake = self._context(root / "forged")
            forged = json.loads(
                paths["validation_record"].read_text(encoding="utf-8")
            )
            forged["source_binding_verified"] = False
            paths["validation_record"].write_text(
                json.dumps(forged),
                encoding="utf-8",
            )
            with mock.patch.object(note, "_load_learn_module", return_value=fake):
                with self.assertRaisesRegex(note.ContractError, "live validation failed"):
                    self._build(paths)

    def test_each_bound_artifact_is_reopened_and_hash_checked(self) -> None:
        for artifact in note.UPSTREAM_ARTIFACT_NAMES:
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as temp:
                paths, fake = self._context(Path(temp).resolve())
                with mock.patch.object(note, "_load_learn_module", return_value=fake):
                    _, rendered, manifest = self._build(paths)
                    paths[artifact].write_bytes(paths[artifact].read_bytes() + b" ")
                    with self.assertRaisesRegex(note.ContractError, "hash changed"):
                        note.validate_projection_manifest(
                            manifest,
                            rendered=rendered,
                            require_upstream_provenance=True,
                            verify_upstream_provenance=True,
                        )

    def test_prepare_update_and_desktop_repeat_live_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            paths, fake = self._context(root)
            with mock.patch.object(note, "_load_learn_module", return_value=fake):
                _, rendered, manifest = self._build(paths)
                html_path = root / "note.html"
                manifest_path = root / "projection.json"
                html_path.write_text(rendered, encoding="utf-8")
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                manifests = prepare.load_projection_manifests([manifest_path])
                used: set[str] = set()
                entry = {
                    "note_key": "ABCD1234",
                    **prepare.projection_binding_for_html(
                        rendered,
                        html_path,
                        manifests,
                        used,
                    ),
                }
                update.verify_projection_gate_entry(
                    entry,
                    staged_html=rendered,
                    status="create_verified",
                    note_key="ABCD1234",
                )
                desktop.verify_projection_gate_entry(
                    entry,
                    staged_html=rendered,
                    status="create_verified",
                    label="ABCD1234",
                )

                disk = json.loads(manifest_path.read_text(encoding="utf-8"))
                disk["upstream_provenance"]["source_sha256"] = "0" * 64
                manifest_path.write_text(json.dumps(disk), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "differs from staged binding"):
                    update.verify_projection_gate_entry(
                        entry,
                        staged_html=rendered,
                        status="create_verified",
                        note_key="ABCD1234",
                    )


if __name__ == "__main__":
    unittest.main()
