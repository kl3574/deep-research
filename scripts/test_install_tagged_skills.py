#!/usr/bin/env python3
"""Unit tests for the tagged-skill installer with fault-injection coverage."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
import sys

import importlib.util


SCRIPT_PATH = Path(__file__).with_name("install_tagged_skills.py")
SPEC = importlib.util.spec_from_file_location("install_tagged_skills", SCRIPT_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["install_tagged_skills"] = module
SPEC.loader.exec_module(module)

GIT_AUTHOR = {
    "GIT_AUTHOR_NAME": "Installer Test",
    "GIT_AUTHOR_EMAIL": "installer@test.local",
}

SELECTED_RESEARCH_SKILLS = (
    "deep-research",
    "scholar-discovery",
    "learn-from-papers",
)


def _git(*cmd: str, cwd: Path, check: bool = True) -> str:
    env = dict(**GIT_AUTHOR, **dict(_ for _ in []))
    proc = subprocess.run(
        ["git", *cmd],
        cwd=str(cwd),
        check=False,
        text=True,
        capture_output=True,
        env={**dict(__import__("os").environ), **env},
    )
    if proc.returncode != 0 and check:
        raise AssertionError(proc.stderr)
    return proc.stdout.strip()


def _create_repo_with_tag(
    root: Path,
    tag: str,
    *,
    light_tag: bool = False,
    second_commit: bool = False,
    tag_at_head: bool = True,
    add_pycache_ignore: bool = False,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=root)
    _git("config", "user.name", GIT_AUTHOR["GIT_AUTHOR_NAME"], cwd=root)
    _git("config", "user.email", GIT_AUTHOR["GIT_AUTHOR_EMAIL"], cwd=root)
    (root / "README.md").write_text("v", encoding="utf-8")
    if add_pycache_ignore:
        (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (root / "skills").mkdir(exist_ok=True)
    for name in module.DEFAULT_SKILLS:
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"name: {name}\n", encoding="utf-8")
        (skill_dir / "payload.txt").write_text("v1\n", encoding="utf-8")

    commit_files = ["README.md", "skills"]
    if add_pycache_ignore:
        commit_files.append(".gitignore")
    _git("add", *commit_files, cwd=root)
    _git("commit", "-q", "-m", "base", cwd=root)

    if not second_commit:
        if light_tag:
            _git("tag", tag, cwd=root)
        else:
            _git("tag", "-a", tag, "-m", f"{tag} test", cwd=root)

    if second_commit and not tag_at_head:
        if light_tag:
            _git("tag", tag, cwd=root)
        else:
            _git("tag", "-a", tag, "-m", f"{tag} test", cwd=root)

    if second_commit:
        (root / "README.md").write_text("v2", encoding="utf-8")
        _git("add", "README.md", cwd=root)
        _git("commit", "-q", "-m", "second", cwd=root)

    if second_commit and tag_at_head:
        if light_tag:
            _git("tag", tag, cwd=root)
        else:
            _git("tag", "-a", tag, "-m", f"{tag} test", cwd=root)

    bare = root.with_name(f"{root.name}-remote.git")
    _git("init", "--bare", "-q", str(bare), cwd=root.parent)
    _git("remote", "add", "origin", str(bare), cwd=root)
    _git("push", "-q", "origin", "HEAD", "--tags", cwd=root)
    return root, bare


def _make_fake_codex_runner(
    *,
    skills_root: Path,
    required_skills: tuple[str, ...] = module.DEFAULT_SKILLS,
    missing_locator: bool = False,
    doctor_exit_code: int = 0,
    nested_content: bool = False,
    debug_stdout_bytes: bool = False,
    debug_stdout_none: bool = False,
    extra_locators: tuple[str, ...] = (),
    debug_payload_override: str | bytes | None = None,
    doctor_payload: dict[str, object] | None = None,
    debug_stderr: object = "",
    doctor_stderr: object = "",
    validate_env: object | None = None,
    record_calls: list[tuple[list[str], dict[str, object]]] | None = None,
) -> Mock:
    prompt_lines = [
        f"confirm (file: {skills_root / name / 'SKILL.md'})"
        for name in required_skills
        if not (missing_locator and name == required_skills[0])
    ]
    prompt_lines.extend(extra_locators)
    prompt_text_joined = "\n".join(prompt_lines)
    if nested_content:
        content: object = [{"type": "input_text", "text": prompt_text_joined}]
    else:
        content = {"input_text": prompt_text_joined}
    prompt_text = json.dumps([{"content": content}])

    if debug_payload_override is not None:
        debug_stdout = debug_payload_override
    elif debug_stdout_none:
        debug_stdout: object = None
    elif debug_stdout_bytes:
        debug_stdout = prompt_text.encode("utf-8")
    else:
        debug_stdout = prompt_text

    if doctor_payload is None:
        doctor_payload = {
            "schemaVersion": 1,
            "overallStatus": "ok",
            "checks": {
                "loader": {
                    "id": "loader",
                    "status": "ok",
                }
            },
        }

    def _run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if record_calls is not None:
            record_calls.append((cmd, dict(_)))
        if validate_env is not None:
            assert callable(validate_env)
            validate_env(dict(_).get("env"))
        if cmd[:3] == ["codex", "debug", "prompt-input"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=debug_stdout,
                stderr=debug_stderr,
            )
        if cmd[:2] == ["codex", "doctor"]:
            return subprocess.CompletedProcess(
                cmd,
                doctor_exit_code,
                stdout=json.dumps(doctor_payload),
                stderr=(
                    doctor_stderr
                    if doctor_stderr
                    else ("" if doctor_exit_code == 0 else "doctor failed")
                ),
            )
        raise AssertionError(f"unexpected command: {cmd}")

    return Mock(side_effect=_run)


def _single_transaction_root(backup_parent: Path) -> Path:
    candidates = list(backup_parent.glob("v0.8.1-*"))
    if len(candidates) != 1:
        raise AssertionError(f"expected one transaction root, got {candidates}")
    return candidates[0]


def _exchange_slot(backup_parent: Path) -> Path:
    return _single_transaction_root(backup_parent) / "skills-before-install"


def _root_alias_text(skills_root: Path) -> str:
    return "\n".join(
        (
            "## Skills",
            "### Skill roots",
            f"- `r0` = `{skills_root}`",
            "### Available skills",
            *(
                f"- {name}: Test skill. (file: r0/{name}/SKILL.md)"
                for name in SELECTED_RESEARCH_SKILLS
            ),
        )
    )


def _developer_text_payload(*blocks: str) -> str:
    return json.dumps(
        [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": block} for block in blocks],
            }
        ]
    )


class InstallTaggedSkillsTests(unittest.TestCase):
    def test_selected_install_accepts_developer_root_alias_locators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")
            unselected_name = next(
                name
                for name in module.DEFAULT_SKILLS
                if name not in SELECTED_RESEARCH_SKILLS
            )
            unselected_file = active_root / unselected_name / "local-only.txt"
            unselected_file.write_bytes(b"unselected local changes\x00\xff")
            unrelated = active_root / "unrelated-skill" / "SKILL.md"
            unrelated.parent.mkdir()
            unrelated.write_text("KEEP\n", encoding="utf-8")

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                required_skills=SELECTED_RESEARCH_SKILLS,
                codex_runner=_make_fake_codex_runner(
                    skills_root=active_root,
                    required_skills=SELECTED_RESEARCH_SKILLS,
                    debug_payload_override=_developer_text_payload(
                        _root_alias_text(active_root)
                    ),
                ),
            )

            for name in SELECTED_RESEARCH_SKILLS:
                self.assertEqual(
                    (active_root / name / "SKILL.md").read_text(encoding="utf-8"),
                    f"name: {name}\n",
                )
            self.assertEqual(
                unselected_file.read_bytes(), b"unselected local changes\x00\xff"
            )
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "KEEP\n")
            loaders = json.loads(
                (result["backup_root"] / "codex-loaders.json").read_text(
                    encoding="utf-8"
                )
            )
            expected = sorted(
                str(active_root / name / "SKILL.md")
                for name in SELECTED_RESEARCH_SKILLS
            )
            self.assertEqual(loaders["loader"]["skill_count"], 3)
            self.assertEqual(
                loaders["loader"]["locator_set_sha256"],
                hashlib.sha256(
                    json.dumps(expected, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            )

    def test_selected_install_preserves_unselected_skills_and_limits_receipts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")
                (skill_dir / "local-only.txt").write_text(
                    f"local {name}\n", encoding="utf-8"
                )
            unrelated = active_root / "extra-skill"
            unrelated.mkdir()
            (unrelated / "SKILL.md").write_text("KEEP\n", encoding="utf-8")
            (unrelated / "payload.bin").write_bytes(b"\x00\xfflocal")
            preserved_files = {
                path.relative_to(active_root): path.read_bytes()
                for path in active_root.rglob("*")
                if path.is_file()
                and path.relative_to(active_root).parts[0]
                not in SELECTED_RESEARCH_SKILLS
            }

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                required_skills=SELECTED_RESEARCH_SKILLS,
                codex_runner=_make_fake_codex_runner(
                    skills_root=active_root,
                    required_skills=SELECTED_RESEARCH_SKILLS,
                ),
            )

            for name in SELECTED_RESEARCH_SKILLS:
                self.assertEqual(
                    (active_root / name / "SKILL.md").read_text(encoding="utf-8"),
                    f"name: {name}\n",
                )
                self.assertEqual(
                    (active_root / name / "payload.txt").read_text(encoding="utf-8"),
                    "v1\n",
                )
                self.assertFalse((active_root / name / "local-only.txt").exists())
            self.assertEqual(
                {
                    path.relative_to(active_root): path.read_bytes()
                    for path in active_root.rglob("*")
                    if path.is_file()
                    and path.relative_to(active_root).parts[0]
                    not in SELECTED_RESEARCH_SKILLS
                },
                preserved_files,
            )

            expected_entries = {
                f"{name}/{suffix}"
                for name in SELECTED_RESEARCH_SKILLS
                for suffix in ("", "SKILL.md", "payload.txt")
            }
            backup = result["backup_root"]
            source_manifest = json.loads(
                (backup / "source-manifest.json").read_text(encoding="utf-8")
            )
            installed_manifest = json.loads(
                (backup / "installed-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(set(source_manifest), expected_entries)
            self.assertEqual(installed_manifest, source_manifest)
            self.assertEqual(result["installed_manifest"], source_manifest)
            self.assertEqual(
                set((backup / "tag-snapshot" / "skills").iterdir()),
                {
                    backup / "tag-snapshot" / "skills" / name
                    for name in SELECTED_RESEARCH_SKILLS
                },
            )
            verification = json.loads(
                (backup / "tag-verification.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                verification["required_skills"], list(SELECTED_RESEARCH_SKILLS)
            )
            loaders = json.loads(
                (backup / "codex-loaders.json").read_text(encoding="utf-8")
            )
            self.assertEqual(loaders["loader"]["skill_count"], 3)
            self.assertEqual(
                loaders["loader"]["skill_names"], sorted(SELECTED_RESEARCH_SKILLS)
            )
            expected_locators = sorted(
                str(active_root / name / "SKILL.md")
                for name in SELECTED_RESEARCH_SKILLS
            )
            self.assertEqual(
                loaders["loader"]["locator_set_sha256"],
                hashlib.sha256(
                    json.dumps(expected_locators, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            )

    def test_clean_install_replaces_only_target_skills_and_preserves_extras(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("old\n", encoding="utf-8")
            # unrelated skill should be preserved
            (active_root / "extra-skill").mkdir(parents=True)
            (active_root / "extra-skill" / "SKILL.md").write_text(
                "keep\n", encoding="utf-8"
            )

            backup_root = tmp_path / "backup_root"
            codex_runner = _make_fake_codex_runner(skills_root=active_root)

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=backup_root,
                codex_runner=codex_runner,
            )
            self.assertEqual(result["tag"], "v0.8.1")

            self.assertEqual(
                list(
                    active_root.parent.glob(
                        f".{active_root.name}.deep-research-stage-*"
                    )
                ),
                [],
            )
            self.assertTrue((active_root / "extra-skill" / "SKILL.md").is_file())
            self.assertEqual(
                (active_root / "extra-skill" / "SKILL.md").read_text(encoding="utf-8"),
                "keep\n",
            )
            self.assertIn(
                f"{module.DEFAULT_SKILLS[0]}/SKILL.md",
                result["installed_manifest"],
            )
            self.assertTrue(codex_runner.call_count >= 2)
            self.assertTrue((result["backup_root"] / "skills-before-install").exists())
            self.assertEqual(
                (
                    result["backup_root"]
                    / "skills-before-install"
                    / module.DEFAULT_SKILLS[0]
                    / "SKILL.md"
                ).read_text(encoding="utf-8"),
                "old\n",
            )
            self.assertTrue((result["backup_root"] / "tag-snapshot").is_dir())
            self.assertEqual(
                (result["backup_root"] / "source-manifest.json").read_bytes(),
                (result["backup_root"] / "installed-manifest.json").read_bytes(),
            )
            loaders = json.loads(
                (result["backup_root"] / "codex-loaders.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(set(loaders), {"loader", "doctor"})
            self.assertEqual(loaders["loader"]["status"], "ok")
            self.assertEqual(
                loaders["loader"]["skill_count"], len(module.DEFAULT_SKILLS)
            )
            self.assertEqual(
                loaders["loader"]["skill_names"], sorted(module.DEFAULT_SKILLS)
            )
            self.assertRegex(loaders["loader"]["locator_set_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(loaders["doctor"]["schemaVersion"], 1)
            self.assertEqual(loaders["doctor"]["overallStatus"], "ok")
            self.assertEqual(loaders["doctor"]["status_counts"], {"ok": 1})
            self.assertEqual(loaders["doctor"]["check_count"], 1)
            self.assertRegex(loaders["doctor"]["check_ids_sha256"], r"^[0-9a-f]{64}$")
            self.assertFalse((result["backup_root"] / "prompt-debug-raw.json").exists())
            self.assertFalse((result["backup_root"] / "doctor-raw.json").exists())

    def test_unrelated_skill_named_skills_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")
            unrelated = active_root / "skills"
            unrelated.mkdir()
            (unrelated / "SKILL.md").write_text("KEEP\n", encoding="utf-8")

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                codex_runner=_make_fake_codex_runner(skills_root=active_root),
            )

            self.assertEqual(
                (active_root / "skills" / "SKILL.md").read_text(encoding="utf-8"),
                "KEEP\n",
            )
            self.assertEqual(
                (
                    result["backup_root"]
                    / "skills-before-install"
                    / "skills"
                    / "SKILL.md"
                ).read_text(encoding="utf-8"),
                "KEEP\n",
            )

    def test_success_archive_and_failed_rollback_preserve_prior_root_mode(self) -> None:
        for missing_locator in (False, True):
            with self.subTest(missing_locator=missing_locator):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
                    active_root = tmp_path / "active_skills"
                    for name in module.DEFAULT_SKILLS:
                        skill_dir = active_root / name
                        skill_dir.mkdir(parents=True)
                        (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")
                    os.chmod(active_root, 0o775)

                    kwargs = {
                        "tag": "v0.8.1",
                        "repo_root": source_repo,
                        "skills_root": active_root,
                        "backup_root": tmp_path / "backup_root",
                        "codex_runner": _make_fake_codex_runner(
                            skills_root=active_root,
                            missing_locator=missing_locator,
                        ),
                    }
                    if missing_locator:
                        with self.assertRaises(module.InstallerError):
                            module.install_tagged_skills(**kwargs)
                        prior_root = active_root
                    else:
                        result = module.install_tagged_skills(**kwargs)
                        prior_root = result["backup_root"] / "skills-before-install"
                        self.assertEqual(
                            stat.S_IMODE(active_root.stat().st_mode),
                            0o775,
                        )

                    self.assertEqual(
                        stat.S_IMODE(prior_root.stat().st_mode),
                        0o775,
                    )
                    self.assertEqual(
                        (prior_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                            encoding="utf-8"
                        ),
                        "OLD\n",
                    )

    def test_preserve_unrelated_symlink_when_copying_stage_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("old\n", encoding="utf-8")
            anchor_target = tmp_path / "anchor.txt"
            anchor_target.write_text("anchor", encoding="utf-8")
            (active_root / "extra-link").symlink_to(anchor_target)

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                codex_runner=_make_fake_codex_runner(skills_root=active_root),
            )
            self.assertIn("tag", result)
            self.assertTrue((active_root / "extra-link").is_symlink())
            self.assertEqual((active_root / "extra-link").resolve(), anchor_target)

    def test_reject_lightweight_or_missing_annotated_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(
                tmp_path / "repo",
                "v0.8.1-light",
                light_tag=True,
            )
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")
            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1-light",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_reject_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            dirty_file = source_repo / "dirty.txt"
            dirty_file.write_text("dirty", encoding="utf-8")
            _git("add", "dirty.txt", cwd=source_repo)
            # dirty in worktree intentionally by not committing
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_reject_head_not_matching_tag_peeled_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(
                tmp_path / "repo",
                "v0.8.1",
                second_commit=True,
                tag_at_head=False,
            )
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")
            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_reject_remote_tag_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            (source_repo / "README.md").write_text("v2", encoding="utf-8")
            _git("add", "README.md", cwd=source_repo)
            _git("commit", "-q", "-m", "second", cwd=source_repo)
            _git("tag", "-d", "v0.8.1", cwd=source_repo)
            _git("tag", "-a", "v0.8.1", "-m", "retag", cwd=source_repo)

            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_installed_bytes_come_from_tag_objects_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            first_source = (
                source_repo / "skills" / module.DEFAULT_SKILLS[0] / "SKILL.md"
            )
            original = first_source.read_text(encoding="utf-8")
            real_runner = subprocess.run

            def racing_runner(
                cmd: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                result = real_runner(cmd, **kwargs)
                if cmd[:3] == ["git", "ls-remote", "--tags"]:
                    first_source.write_text(
                        "TAMPERED-AFTER-PREFLIGHT\n", encoding="utf-8"
                    )
                return result

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                command_runner=racing_runner,
                codex_runner=_make_fake_codex_runner(skills_root=active_root),
            )
            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                original,
            )
            self.assertEqual(
                result["tag_commit"], _git("rev-parse", "HEAD", cwd=source_repo)
            )

    def test_failed_rollback_preserves_old_root_at_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            exchange_calls = 0

            def second_exchange_fails(path_a: Path, path_b: Path) -> None:
                nonlocal exchange_calls
                exchange_calls += 1
                if exchange_calls == 2:
                    raise module.InstallerError("injected rollback exchange failure")
                module._exchange_atomically(path_a, path_b)

            with self.assertRaisesRegex(
                module.InstallerError, "rollback failed"
            ) as raised:
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=active_root,
                        missing_locator=True,
                    ),
                    exchange=second_exchange_fails,
                )

            preserved_old = _exchange_slot(tmp_path / "backup_root")
            self.assertEqual(raised.exception.recovery_root, preserved_old)
            self.assertIn(f"recovery_root={preserved_old}", str(raised.exception))
            self.assertEqual(
                (preserved_old / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_nonblocking_active_root_lock_rejects_concurrent_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            with module._active_root_lock(active_root) as lock_path:
                with self.assertRaisesRegex(module.InstallerError, "lock is busy"):
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    )
                self.assertTrue(lock_path.is_file())

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertEqual(list((tmp_path / "backup_root").glob("v0.8.1-*")), [])

    def test_lock_and_signal_guard_cover_stage_archive_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            original_sigterm = module.signal.getsignal(module.signal.SIGTERM)
            observations: dict[str, bool] = {}
            exchange_count = 0

            def lock_is_busy() -> bool:
                try:
                    with module._active_root_lock(active_root):
                        return False
                except module.InstallerError:
                    return True

            def hook(step: str) -> None:
                if step == "stage":
                    observations["stage_signal"] = (
                        module.signal.getsignal(module.signal.SIGTERM)
                        != original_sigterm
                    )
                    observations["stage_lock"] = lock_is_busy()

            def exchange_then_fail_rollback(path_a: Path, path_b: Path) -> None:
                nonlocal exchange_count
                exchange_count += 1
                if exchange_count == 2:
                    observations["rollback_signal"] = (
                        module.signal.getsignal(module.signal.SIGTERM)
                        != original_sigterm
                    )
                    observations["rollback_lock"] = lock_is_busy()
                    raise module.InstallerError("injected rollback failure")
                module._exchange_atomically(path_a, path_b)

            def archive_checks_guard(stage_root: Path, backup_root: Path) -> Path:
                observations["archive_signal"] = (
                    module.signal.getsignal(module.signal.SIGTERM) != original_sigterm
                )
                observations["archive_lock"] = lock_is_busy()
                raise module.InstallerError("injected archive failure")

            with self.assertRaisesRegex(module.InstallerError, "rollback failed"):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    exchange=exchange_then_fail_rollback,
                    archive=archive_checks_guard,
                    phase_hook=hook,
                )

            self.assertEqual(
                observations,
                {
                    "stage_signal": True,
                    "stage_lock": True,
                    "archive_signal": True,
                    "archive_lock": True,
                    "rollback_signal": True,
                    "rollback_lock": True,
                },
            )

    def test_exchange_that_swaps_then_raises_is_detected_and_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            exchange_count = 0

            def exchange_then_raise(path_a: Path, path_b: Path) -> None:
                nonlocal exchange_count
                exchange_count += 1
                module._exchange_atomically(path_a, path_b)
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    exchange=exchange_then_raise,
                )

            self.assertEqual(exchange_count, 2)
            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertEqual(
                list(
                    active_root.parent.glob(
                        f".{active_root.name}.deep-research-stage-*"
                    )
                ),
                [],
            )

    def test_reject_parent_symlink_for_skills_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            real_parent = tmp_path / "real_skills_parent"
            real_parent.mkdir(parents=True)
            linked_parent = tmp_path / "linked_parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            active_root = linked_parent / "active_skills"

            # create required targets under the real target path, but expose alias via symlink
            for name in module.DEFAULT_SKILLS:
                skill_dir = real_parent / "active_skills" / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("old\n", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=real_parent / "active_skills"
                    ),
                )

    def test_reject_broken_ancestor_symlink_for_skills_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            broken_parent = tmp_path / "missing-parent"
            alias_parent = tmp_path / "alias-parent"
            alias_parent.symlink_to(broken_parent, target_is_directory=True)
            active_root = alias_parent / "active_skills"
            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=tmp_path / "real"),
                )

    def test_reject_parent_symlink_for_backup_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("old\n", encoding="utf-8")

            real_backup_parent = tmp_path / "real-backup-root"
            real_backup_parent.mkdir()
            backup_parent = tmp_path / "backup-parent-link"
            backup_parent.symlink_to(real_backup_parent, target_is_directory=True)
            backup_root = backup_parent / "skill-backups"

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=backup_root,
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_foreign_prebuilt_transaction_root_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            tag_commit = _git("rev-parse", "HEAD", cwd=source_repo)
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            foreign_root = (
                tmp_path
                / "backup_root"
                / f"v0.8.1-{tag_commit[:12]}-12345-collision-token"
            )
            foreign_root.mkdir(parents=True)
            sentinel = foreign_root / "sentinel"
            sentinel.write_text("KEEP", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                with patch.object(module.time, "time", return_value=12345):
                    with patch.object(
                        module.secrets,
                        "token_hex",
                        return_value="collision-token",
                    ):
                        module.install_tagged_skills(
                            tag="v0.8.1",
                            repo_root=source_repo,
                            skills_root=active_root,
                            backup_root=tmp_path / "backup_root",
                            codex_runner=_make_fake_codex_runner(
                                skills_root=active_root
                            ),
                        )

            self.assertTrue(foreign_root.is_dir())
            self.assertTrue(sentinel.exists())

    def test_identity_drift_before_skill_replace_does_not_mutate_foreign_stage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            foreign_stage: Path | None = None

            def drift_stage_identity(step: str) -> None:
                nonlocal foreign_stage
                if step == "skills_replace":
                    stage_root = _exchange_slot(tmp_path / "backup_root")
                    stage_root.rename(tmp_path / "displaced-owned-stage")
                    stage_root.mkdir()
                    (stage_root / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                    foreign_stage = stage_root
                elif step == "before_exchange":
                    raise module.InstallerError("stop after replace")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    phase_hook=drift_stage_identity,
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                (foreign_stage / "FOREIGN").read_text(encoding="utf-8"), "KEEP\n"
            )
            self.assertFalse((foreign_stage / module.DEFAULT_SKILLS[0]).exists())

    def test_identity_drift_before_exchange_preserves_active_and_foreign_roots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            foreign_stage: Path | None = None

            def drift_stage_identity(step: str) -> None:
                nonlocal foreign_stage
                if step != "before_exchange":
                    return
                stage_root = _exchange_slot(tmp_path / "backup_root")
                stage_root.rename(tmp_path / "displaced-ready-stage")
                stage_root.mkdir()
                (stage_root / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                foreign_stage = stage_root

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    phase_hook=drift_stage_identity,
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                (foreign_stage / "FOREIGN").read_text(encoding="utf-8"), "KEEP\n"
            )

    def test_postcheck_race_before_replace_never_mutates_foreign_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            real_classifier = module._classify_transaction_paths
            raced = False
            foreign_stage: Path | None = None

            def race_after_prepared_check(**kwargs: object) -> str:
                nonlocal raced, foreign_stage
                state = real_classifier(**kwargs)
                if state == "prepared" and not raced:
                    raced = True
                    stage_root = Path(kwargs["stage_root"])
                    stage_root.rename(tmp_path / "displaced-owned-stage-after-check")
                    stage_root.mkdir()
                    (stage_root / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                    foreign_stage = stage_root
                return state

            with patch.object(
                module,
                "_classify_transaction_paths",
                side_effect=race_after_prepared_check,
            ):
                with self.assertRaises(module.InstallerError):
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    )

            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                (foreign_stage / "FOREIGN").read_text(encoding="utf-8"), "KEEP\n"
            )
            self.assertFalse((foreign_stage / module.DEFAULT_SKILLS[0]).exists())
            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_postcheck_race_before_exchange_restores_original_active_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            real_classifier = module._classify_transaction_paths
            prepared_count = 0
            foreign_stage: Path | None = None

            def race_after_exchange_precheck(**kwargs: object) -> str:
                nonlocal prepared_count, foreign_stage
                state = real_classifier(**kwargs)
                if state == "prepared":
                    prepared_count += 1
                    if prepared_count == 2:
                        stage_root = Path(kwargs["stage_root"])
                        stage_root.rename(tmp_path / "displaced-ready-after-check")
                        stage_root.mkdir()
                        (stage_root / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                        foreign_stage = stage_root
                return state

            with patch.object(
                module,
                "_classify_transaction_paths",
                side_effect=race_after_exchange_precheck,
            ):
                with self.assertRaises(module.InstallerError):
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                (foreign_stage / "FOREIGN").read_text(encoding="utf-8"), "KEEP\n"
            )

    def test_postcheck_race_before_rollback_preserves_original_active_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            real_classifier = module._classify_transaction_paths
            raced = False
            displaced_old: Path | None = None
            foreign_stage: Path | None = None

            def race_after_rollback_precheck(**kwargs: object) -> str:
                nonlocal raced, displaced_old, foreign_stage
                state = real_classifier(**kwargs)
                if state == "exchanged" and not raced:
                    raced = True
                    stage_root = Path(kwargs["stage_root"])
                    displaced_old = tmp_path / "displaced-old-before-rollback"
                    stage_root.rename(displaced_old)
                    stage_root.mkdir()
                    (stage_root / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                    foreign_stage = stage_root
                return state

            with patch.object(
                module,
                "_classify_transaction_paths",
                side_effect=race_after_rollback_precheck,
            ):
                with self.assertRaises(module.InstallerError) as raised:
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(
                            skills_root=active_root,
                            missing_locator=True,
                        ),
                    )

            self.assertIsNotNone(displaced_old)
            assert displaced_old is not None
            self.assertEqual(
                (displaced_old / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                (foreign_stage / "FOREIGN").read_text(encoding="utf-8"), "KEEP\n"
            )
            self.assertFalse((active_root / "FOREIGN").exists())
            self.assertIsNotNone(raised.exception.recovery_root)
            recovery_root = Path(raised.exception.recovery_root)
            self.assertEqual(
                (recovery_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_reject_empty_skill_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")

            empty_skill = source_repo / "skills" / module.DEFAULT_SKILLS[0]
            for file_name in ("SKILL.md", "payload.txt"):
                (empty_skill / file_name).unlink()
            _git("add", "skills", cwd=source_repo)
            _git("commit", "-q", "-m", "empty skill", cwd=source_repo)
            _git("tag", "-d", "v0.8.1", cwd=source_repo)
            _git("tag", "-a", "v0.8.1", "-m", "v0.8.1", cwd=source_repo)
            _git("push", "-q", "--force", "origin", "HEAD", "--tags", cwd=source_repo)

            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("old\n", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_archive_window_failure_triggers_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            def archive_fails(stage_root: Path, backup_root: Path) -> Path:
                raise module.InstallerError("injected archive failure")

            backup_root = tmp_path / "backup_root"
            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=backup_root,
                    archive=archive_fails,
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            stage_candidates = list(
                active_root.parent.glob(f".{active_root.name}.deep-research-stage-*")
            )
            self.assertEqual(stage_candidates, [])
            self.assertEqual(len(list(backup_root.glob("v0.8.1-*"))), 1)

    def test_archive_confirmation_does_not_rename_or_delete_exchange_slot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            backup_root = Path(tmp_dir) / "transaction"
            slot = backup_root / "skills-before-install"
            slot.mkdir(parents=True)
            marker = slot / "OLD"
            marker.write_text("KEEP\n", encoding="utf-8")
            identity = module._path_identity(slot)

            with patch.object(
                module.os,
                "rename",
                side_effect=AssertionError("archive must not rename"),
            ):
                returned = module._archive_stage_root(slot, backup_root)

            self.assertEqual(returned, slot)
            self.assertEqual(module._path_identity(slot), identity)
            self.assertEqual(marker.read_text(encoding="utf-8"), "KEEP\n")

    def test_precommit_archive_hook_failure_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            def archive_then_raise(stage_root: Path, backup_root: Path) -> Path:
                module._archive_stage_root(stage_root, backup_root)
                raise KeyboardInterrupt

            backup_parent = tmp_path / "backup_root"
            with self.assertRaises(KeyboardInterrupt):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=backup_parent,
                    archive=archive_then_raise,
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            backup_candidates = list(backup_parent.glob("v0.8.1-*"))
            self.assertEqual(len(backup_candidates), 1)
            failed_new = backup_candidates[0] / "skills-before-install"
            self.assertNotEqual(
                (failed_new / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertEqual(
                list(
                    active_root.parent.glob(
                        f".{active_root.name}.deep-research-stage-*"
                    )
                ),
                [],
            )

    def test_source_snapshot_is_retained_in_transaction_root(self) -> None:
        for fail_during_stage in (False, True):
            with self.subTest(fail_during_stage=fail_during_stage):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
                    active_root = tmp_path / "active_skills"
                    for name in module.DEFAULT_SKILLS:
                        skill_dir = active_root / name
                        skill_dir.mkdir(parents=True)
                        (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

                    def hook(step: str) -> None:
                        if fail_during_stage and step == "stage":
                            raise module.InstallerError("injected staging failure")

                    if fail_during_stage:
                        with self.assertRaisesRegex(
                            module.InstallerError, "injected staging failure"
                        ):
                            module.install_tagged_skills(
                                tag="v0.8.1",
                                repo_root=source_repo,
                                skills_root=active_root,
                                backup_root=tmp_path / "backup_root",
                                codex_runner=_make_fake_codex_runner(
                                    skills_root=active_root
                                ),
                                phase_hook=hook,
                            )
                    else:
                        module.install_tagged_skills(
                            tag="v0.8.1",
                            repo_root=source_repo,
                            skills_root=active_root,
                            backup_root=tmp_path / "backup_root",
                            codex_runner=_make_fake_codex_runner(
                                skills_root=active_root
                            ),
                            phase_hook=hook,
                        )

                    self.assertEqual(
                        list(source_repo.glob("deep-research-skill-snapshot-*")),
                        [],
                    )
                    snapshot_root = (
                        _single_transaction_root(tmp_path / "backup_root")
                        / "tag-snapshot"
                    )
                    self.assertTrue(snapshot_root.is_dir())
                    self.assertTrue(
                        (
                            snapshot_root
                            / "skills"
                            / module.DEFAULT_SKILLS[0]
                            / "SKILL.md"
                        ).is_file()
                    )

    def test_archive_identity_drift_does_not_move_foreign_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            foreign_stage: Path | None = None
            displaced_old = tmp_path / "displaced-old-root"

            def drift_stage_identity(step: str) -> None:
                nonlocal foreign_stage
                if step != "before_archive":
                    return
                stage_root = _exchange_slot(tmp_path / "backup_root")
                stage_root.rename(displaced_old)
                stage_root.mkdir()
                (stage_root / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                foreign_stage = stage_root

            with self.assertRaises(module.InstallerError) as raised:
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    phase_hook=drift_stage_identity,
                )

            self.assertIsNotNone(raised.exception.recovery_root)
            self.assertTrue(displaced_old.is_dir())
            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                (foreign_stage / "FOREIGN").read_text(encoding="utf-8"),
                "KEEP\n",
            )

    def test_postcheck_archive_drift_does_not_move_foreign_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            real_identity = module._path_identity
            armed = False
            raced = False
            displaced_old = tmp_path / "postcheck-displaced-old"
            foreign_stage: Path | None = None

            def hook(step: str) -> None:
                nonlocal armed
                if step == "before_archive":
                    armed = True

            def identity_then_drift(path: Path) -> object:
                nonlocal raced, foreign_stage
                result = real_identity(path)
                slot = _exchange_slot(tmp_path / "backup_root")
                if armed and not raced and path == slot:
                    raced = True
                    slot.rename(displaced_old)
                    slot.mkdir()
                    (slot / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                    foreign_stage = slot
                return result

            with patch.object(
                module, "_path_identity", side_effect=identity_then_drift
            ):
                with self.assertRaises(module.InstallerError) as raised:
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                        phase_hook=hook,
                    )

            self.assertTrue(displaced_old.is_dir())
            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                (foreign_stage / "FOREIGN").read_text(encoding="utf-8"),
                "KEEP\n",
            )
            self.assertIsNotNone(raised.exception.recovery_root)
            self.assertEqual(
                (
                    Path(raised.exception.recovery_root)
                    / module.DEFAULT_SKILLS[0]
                    / "SKILL.md"
                ).read_text(encoding="utf-8"),
                "OLD\n",
            )

    def test_success_retains_tag_snapshot_without_recursive_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            real_rmtree = module.shutil.rmtree

            def reject_snapshot_cleanup(
                path: object, *args: object, **kwargs: object
            ) -> None:
                if "tag-snapshot" in Path(path).parts:
                    raise AssertionError("tag snapshot must not be recursively removed")
                real_rmtree(path, *args, **kwargs)

            with patch.object(
                module.shutil, "rmtree", side_effect=reject_snapshot_cleanup
            ):
                result = module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

            self.assertTrue((result["backup_root"] / "tag-snapshot").is_dir())

    def test_pre_stage_snapshot_substitution_cannot_install_non_tag_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            displaced_snapshot = tmp_path / "displaced-tag-snapshot"
            foreign_snapshot: Path | None = None

            def substitute_snapshot(step: str) -> None:
                nonlocal foreign_snapshot
                if step != "pre_stage":
                    return
                snapshot_root = (
                    _single_transaction_root(tmp_path / "backup_root") / "tag-snapshot"
                )
                snapshot_root.rename(displaced_snapshot)
                snapshot_root.mkdir()
                foreign_snapshot = snapshot_root
                for name in module.DEFAULT_SKILLS:
                    skill_dir = snapshot_root / "skills" / name
                    skill_dir.mkdir(parents=True)
                    (skill_dir / "SKILL.md").write_text(
                        "NON_TAG_BYTES\n", encoding="utf-8"
                    )

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    phase_hook=substitute_snapshot,
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertTrue(displaced_snapshot.is_dir())
            self.assertIsNotNone(foreign_snapshot)
            assert foreign_snapshot is not None
            self.assertEqual(
                (
                    foreign_snapshot / "skills" / module.DEFAULT_SKILLS[0] / "SKILL.md"
                ).read_text(encoding="utf-8"),
                "NON_TAG_BYTES\n",
            )

    def test_snapshot_mkdir_open_race_does_not_modify_foreign_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            real_os_open = module.os.open
            displaced_snapshot = tmp_path / "displaced-created-snapshot"
            foreign_snapshot: Path | None = None

            def substitute_before_open(
                path: object, flags: int, mode: int = 0o777
            ) -> int:
                nonlocal foreign_snapshot
                target = Path(path)
                if target.name == "tag-snapshot" and foreign_snapshot is None:
                    target.rename(displaced_snapshot)
                    target.mkdir()
                    (target / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                    foreign_snapshot = target
                return real_os_open(path, flags, mode)

            with patch.object(module.os, "open", side_effect=substitute_before_open):
                with self.assertRaises(module.InstallerError):
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    )

            self.assertIsNotNone(foreign_snapshot)
            assert foreign_snapshot is not None
            self.assertEqual(
                sorted(
                    path.relative_to(foreign_snapshot).as_posix()
                    for path in foreign_snapshot.rglob("*")
                ),
                ["FOREIGN"],
            )
            self.assertEqual(
                (foreign_snapshot / "FOREIGN").read_text(encoding="utf-8"),
                "KEEP\n",
            )
            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_stage_mkdir_bind_race_does_not_modify_foreign_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            real_path_identity = module._path_identity
            displaced_stage = tmp_path / "displaced-created-stage"
            foreign_stage: Path | None = None

            def substitute_before_bind(path: Path) -> module.PathIdentity | None:
                nonlocal foreign_stage
                if path.name == "skills-before-install" and foreign_stage is None:
                    path.rename(displaced_stage)
                    path.mkdir()
                    (path / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                    foreign_stage = path
                return real_path_identity(path)

            with patch.object(
                module, "_path_identity", side_effect=substitute_before_bind
            ):
                with self.assertRaises(module.InstallerError):
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    )

            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                sorted(
                    path.relative_to(foreign_stage).as_posix()
                    for path in foreign_stage.rglob("*")
                ),
                ["FOREIGN"],
            )
            self.assertEqual(
                (foreign_stage / "FOREIGN").read_text(encoding="utf-8"),
                "KEEP\n",
            )
            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_stage_open_substitution_preserves_foreign_target_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            active_root.mkdir()
            (active_root / "unrelated").mkdir()
            (active_root / "unrelated" / "SKILL.md").write_text(
                "OLD\n", encoding="utf-8"
            )

            real_os_open = module.os.open
            displaced_stage = tmp_path / "displaced-empty-stage"
            foreign_stage: Path | None = None

            def substitute_before_open(
                path: object, flags: int, mode: int = 0o777
            ) -> int:
                nonlocal foreign_stage
                target = Path(path)
                if target.name == "skills-before-install" and foreign_stage is None:
                    target.rename(displaced_stage)
                    precious = target / module.DEFAULT_SKILLS[0]
                    precious.mkdir(parents=True)
                    (precious / "PRECIOUS").write_text("KEEP\n", encoding="utf-8")
                    foreign_stage = target
                return real_os_open(path, flags, mode)

            with patch.object(module.os, "open", side_effect=substitute_before_open):
                with self.assertRaises(module.InstallerError):
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    )

            self.assertIsNotNone(foreign_stage)
            assert foreign_stage is not None
            self.assertEqual(
                (foreign_stage / module.DEFAULT_SKILLS[0] / "PRECIOUS").read_text(
                    encoding="utf-8"
                ),
                "KEEP\n",
            )
            self.assertEqual(
                (active_root / "unrelated" / "SKILL.md").read_text(encoding="utf-8"),
                "OLD\n",
            )

    def test_active_root_substitution_during_stage_copy_never_becomes_backup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            displaced_active = tmp_path / "displaced-active"
            foreign_active: Path | None = None
            real_copy = module._copy_loader_root

            def substitute_before_copy(
                source_root: Path, stage_root: Path
            ) -> tuple[int, module.PathIdentity]:
                nonlocal foreign_active
                active_root.rename(displaced_active)
                active_root.mkdir()
                (active_root / "FOREIGN").write_text("KEEP\n", encoding="utf-8")
                foreign_active = active_root
                return real_copy(source_root, stage_root)

            with patch.object(
                module, "_copy_loader_root", side_effect=substitute_before_copy
            ):
                with self.assertRaises(module.InstallerError):
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    )

            self.assertIsNotNone(foreign_active)
            assert foreign_active is not None
            self.assertEqual(
                (foreign_active / "FOREIGN").read_text(encoding="utf-8"),
                "KEEP\n",
            )
            self.assertEqual(
                (displaced_active / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_pre_stage_in_place_snapshot_mutation_cannot_be_blessed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            def mutate_snapshot(step: str) -> None:
                if step != "pre_stage":
                    return
                snapshot_root = (
                    _single_transaction_root(tmp_path / "backup_root") / "tag-snapshot"
                )
                for name in module.DEFAULT_SKILLS:
                    (snapshot_root / "skills" / name / "SKILL.md").write_text(
                        "IN_PLACE_NON_TAG_BYTES\n", encoding="utf-8"
                    )

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    phase_hook=mutate_snapshot,
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_pre_stage_empty_directory_injection_cannot_be_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            def inject_empty_directory(step: str) -> None:
                if step != "pre_stage":
                    return
                snapshot_root = (
                    _single_transaction_root(tmp_path / "backup_root") / "tag-snapshot"
                )
                (
                    snapshot_root
                    / "skills"
                    / module.DEFAULT_SKILLS[0]
                    / "UNTRACKED_EMPTY"
                ).mkdir()

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    phase_hook=inject_empty_directory,
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertFalse(
                (active_root / module.DEFAULT_SKILLS[0] / "UNTRACKED_EMPTY").exists()
            )

    def test_extraction_manifest_is_derived_before_mutable_snapshot_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            real_compute_manifest = module._compute_manifest
            mutated = False

            def mutate_before_first_snapshot_scan(
                root: Path, skills: object
            ) -> dict[str, module.ManifestEntry]:
                nonlocal mutated
                is_snapshot_scan = (
                    not mutated
                    and root.name == "skills"
                    and root.parent.name.isdigit()
                    and Path("/proc/self/fd") in root.parents
                )
                if is_snapshot_scan:
                    mutated = True
                    for name in module.DEFAULT_SKILLS:
                        (root / name / "SKILL.md").write_text(
                            "BLESSED_NON_TAG\n", encoding="utf-8"
                        )
                return real_compute_manifest(root, skills)

            with patch.object(
                module,
                "_compute_manifest",
                side_effect=mutate_before_first_snapshot_scan,
            ):
                with self.assertRaises(module.InstallerError):
                    module.install_tagged_skills(
                        tag="v0.8.1",
                        repo_root=source_repo,
                        skills_root=active_root,
                        backup_root=tmp_path / "backup_root",
                        codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    )

            self.assertTrue(mutated)
            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_snapshot_mutation_after_initial_manifest_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            def mutate_snapshot(step: str) -> None:
                if step != "skills_replace":
                    return
                snapshot_root = (
                    _single_transaction_root(tmp_path / "backup_root") / "tag-snapshot"
                )
                for name in module.DEFAULT_SKILLS:
                    (snapshot_root / "skills" / name / "SKILL.md").write_text(
                        "LATE_NON_TAG_BYTES\n", encoding="utf-8"
                    )

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    phase_hook=mutate_snapshot,
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_installed_tree_mutation_before_commit_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            def mutate_installed(step: str) -> None:
                if step != "before_archive":
                    return
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").write_text(
                    "POSTCHECK_MUTATION\n", encoding="utf-8"
                )

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                    phase_hook=mutate_installed,
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_reject_ignored_source_file_not_in_tag_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(
                tmp_path / "repo",
                "v0.8.1",
                add_pycache_ignore=True,
            )
            cached_file = (
                source_repo
                / "skills"
                / module.DEFAULT_SKILLS[0]
                / "__pycache__"
                / "ignored.py"
            )
            cached_file.parent.mkdir(parents=True, exist_ok=True)
            cached_file.write_text("cache\n", encoding="utf-8")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")
            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_reject_symlink_in_source_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            linked_target = (
                source_repo / "skills" / module.DEFAULT_SKILLS[0] / "SKILL.md"
            )
            link_path = source_repo / "skills" / module.DEFAULT_SKILLS[0] / "link"
            link_path.symlink_to(linked_target)
            _git("add", "skills", cwd=source_repo)
            _git("commit", "-q", "-m", "add symlink", cwd=source_repo)
            _git("tag", "-d", "v0.8.1", cwd=source_repo)
            _git("push", "-q", "--delete", "origin", "v0.8.1", cwd=source_repo)
            _git("tag", "-a", "v0.8.1", "-m", "v0.8.1", cwd=source_repo)
            _git("push", "-q", "--force", "origin", "HEAD", "--tags", cwd=source_repo)

            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")
            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_locator_shape_nested_content_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                codex_runner=_make_fake_codex_runner(
                    skills_root=active_root,
                    nested_content=True,
                ),
            )
            self.assertEqual(result["tag"], "v0.8.1")

    def test_locator_shape_allows_unrelated_locators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                codex_runner=_make_fake_codex_runner(
                    skills_root=active_root,
                    nested_content=True,
                    extra_locators=(
                        "/tmp/unrelated/file.txt",
                        "confirm (file: /tmp/unrelated/other.txt)",
                    ),
                ),
            )
            self.assertEqual(result["tag"], "v0.8.1")

    def test_locator_shape_rejects_duplicate_skill_name_from_unrelated_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")
            alias_root = tmp_path / "skills-alias"
            alias_root.symlink_to(active_root, target_is_directory=True)

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=active_root,
                        nested_content=True,
                        extra_locators=(
                            f"confirm (file: {alias_root / module.DEFAULT_SKILLS[0] / 'SKILL.md'})",
                        ),
                    ),
                )

    def test_locator_shape_rejects_non_list_debug_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            payload = json.dumps(
                {
                    "content": {
                        "input_text": "\n".join(
                            str(active_root / name / "SKILL.md")
                            for name in module.DEFAULT_SKILLS
                        )
                    }
                }
            )
            with self.assertRaises(module.InstallerError):
                module._parse_locator_output(
                    payload, active_root, module.DEFAULT_SKILLS
                )

    def test_locator_shape_rejects_content_list_block_without_type_or_text(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            active_root = Path(tmp_dir) / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            payload = json.dumps(
                [
                    {
                        "content": [
                            {"type": "input_text", "text": "ok"},
                            {"text": "missing type"},
                        ]
                    }
                ]
            )
            with self.assertRaises(module.InstallerError):
                module._parse_locator_output(
                    payload, active_root, module.DEFAULT_SKILLS
                )

    def test_locator_shape_rejects_content_list_block_without_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            active_root = Path(tmp_dir) / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            payload = json.dumps(
                [
                    {
                        "content": [
                            {"type": "input_text", "text": "ok"},
                            {"type": "input_text"},
                        ]
                    }
                ]
            )
            with self.assertRaises(module.InstallerError):
                module._parse_locator_output(
                    payload, active_root, module.DEFAULT_SKILLS
                )

    def test_locator_shape_rejects_disallowed_locator_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            base_locator_lines = [
                f"confirm (file: {active_root / name / 'SKILL.md'})"
                for name in module.DEFAULT_SKILLS
            ]
            bad_variants = [
                "../outside/SKILL.md",
                "/tmp//bad/SKILL.md",
                "/tmp/../outside/SKILL.md",
                f"{active_root / module.DEFAULT_SKILLS[0] / 'SKILL.md'}\x00",
                "/tmp/bad\npath/SKILL.md",
            ]

            for variant in bad_variants:
                lines = list(base_locator_lines)
                lines[0] = f"confirm (file: {variant})"
                payload = json.dumps(
                    [
                        {
                            "content": {
                                "input_text": "\n".join(lines),
                            }
                        }
                    ]
                )
                with self.assertRaises(module.InstallerError):
                    module._parse_locator_output(
                        payload, active_root, module.DEFAULT_SKILLS
                    )

    def test_locator_shape_rejects_nonexact_lexical_and_renamed_alias_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            exact_lines = [
                f"confirm (file: {active_root / name / 'SKILL.md'})"
                for name in module.DEFAULT_SKILLS
            ]
            renamed_alias = tmp_path / "renamed-locator"
            renamed_alias.symlink_to(
                active_root / module.DEFAULT_SKILLS[0], target_is_directory=True
            )
            hardlink_alias = tmp_path / "renamed-hardlink" / "SKILL.md"
            hardlink_alias.parent.mkdir()
            os.link(active_root / module.DEFAULT_SKILLS[0] / "SKILL.md", hardlink_alias)
            variants = {
                "trailing-whitespace": [
                    exact_lines[0][:-1] + " )",
                    *exact_lines[1:],
                ],
                "leading-double-slash-extra": [
                    *exact_lines,
                    "confirm (file: //tmp/unrelated/SKILL.md)",
                ],
                "renamed-symlink-alias-extra": [
                    *exact_lines,
                    f"confirm (file: {renamed_alias / 'SKILL.md'})",
                ],
                "renamed-hardlink-alias-extra": [
                    *exact_lines,
                    f"confirm (file: {hardlink_alias})",
                ],
            }

            for label, lines in variants.items():
                with self.subTest(label=label):
                    payload = json.dumps(
                        [{"content": {"input_text": "\n".join(lines)}}]
                    )
                    with self.assertRaises(module.InstallerError):
                        module._parse_locator_output(
                            payload, active_root, module.DEFAULT_SKILLS
                        )

    def test_locator_shape_rejects_non_object_content_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            active_root = Path(tmp_dir) / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            payload = json.dumps([{"content": ["oops"]}])
            with self.assertRaises(module.InstallerError):
                module._parse_locator_output(
                    payload, active_root, module.DEFAULT_SKILLS
                )

    def test_locator_shape_accepts_nested_content_list_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            active_root = Path(tmp_dir) / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            payload = json.dumps(
                [
                    {
                        "content": [
                            {"type": "input_text", "text": "ignore"},
                            {
                                "type": "input_text",
                                "text": "\n".join(
                                    f"confirm (file: {active_root / name / 'SKILL.md'})"
                                    for name in module.DEFAULT_SKILLS
                                ),
                            },
                        ]
                    }
                ]
            )
            result = module._parse_locator_output(
                payload,
                active_root,
                module.DEFAULT_SKILLS,
            )
            self.assertEqual(
                result,
                sorted(
                    str((active_root / name / "SKILL.md").absolute())
                    for name in module.DEFAULT_SKILLS
                ),
            )

    def test_rollback_on_fake_doctor_bad_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=active_root,
                        doctor_payload={"status": "ok"},
                        doctor_exit_code=0,
                        nested_content=True,
                    ),
                )

    def test_accepts_fake_doctor_schema_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                codex_runner=_make_fake_codex_runner(
                    skills_root=active_root,
                    doctor_payload={
                        "schemaVersion": 1,
                        "overallStatus": "ok",
                        "checks": {
                            "loader": {
                                "id": "loader",
                                "status": "ok",
                            }
                        },
                    },
                ),
            )
            self.assertEqual(result["tag"], "v0.8.1")

    def test_loader_receipt_never_persists_dynamic_doctor_identifiers(self) -> None:
        secret = "SENTINEL_DOCTOR_SECRET_42"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                codex_runner=_make_fake_codex_runner(
                    skills_root=active_root,
                    doctor_payload={
                        "schemaVersion": 1,
                        "overallStatus": "ok",
                        "checks": {
                            secret: {
                                "id": secret,
                                "status": "ok",
                                "details": secret,
                            }
                        },
                    },
                    doctor_stderr=secret,
                ),
            )

            for path in Path(result["backup_root"]).rglob("*"):
                if path.is_file():
                    self.assertNotIn(secret.encode(), path.read_bytes())

    def test_invalid_loader_json_does_not_retain_secret_exception_context(self) -> None:
        secret = "SENTINEL_JSON_SECRET_73"
        with tempfile.TemporaryDirectory() as tmp_dir:
            active_root = Path(tmp_dir) / "active_skills"
            with self.assertRaises(module.InstallerError) as raised:
                module._parse_locator_output(
                    "{" + secret,
                    active_root,
                    module.DEFAULT_SKILLS,
                )
            self.assertNotIn(secret, str(raised.exception))
            self.assertIsNone(raised.exception.__context__)
            tb = raised.exception.__traceback__
            while tb is not None:
                if Path(tb.tb_frame.f_code.co_filename) == SCRIPT_PATH:
                    self.assertNotIn(secret, repr(tb.tb_frame.f_locals))
                tb = tb.tb_next

    def test_invalid_doctor_json_does_not_retain_secret_exception_context(self) -> None:
        secret = "SENTINEL_DOCTOR_JSON_SECRET_91"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")
            prompt_text = json.dumps(
                [
                    {
                        "content": [
                            {
                                "type": "input_text",
                                "text": "\n".join(
                                    f"confirm (file: {active_root / name / 'SKILL.md'})"
                                    for name in module.DEFAULT_SKILLS
                                ),
                            }
                        ]
                    }
                ]
            )

            def invalid_doctor_runner(
                cmd: list[str], **_kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                if cmd[:3] == ["codex", "debug", "prompt-input"]:
                    return subprocess.CompletedProcess(cmd, 0, prompt_text, "")
                return subprocess.CompletedProcess(cmd, 0, "{" + secret, "")

            with self.assertRaises(module.InstallerError) as raised:
                module._verify_codex_loader(
                    active_root,
                    module.DEFAULT_SKILLS,
                    invalid_doctor_runner,
                    tmp_path / "codex-home",
                )
            self.assertNotIn(secret, str(raised.exception))
            self.assertIsNone(raised.exception.__context__)
            tb = raised.exception.__traceback__
            while tb is not None:
                if Path(tb.tb_frame.f_code.co_filename) == SCRIPT_PATH:
                    self.assertNotIn(secret, repr(tb.tb_frame.f_locals))
                tb = tb.tb_next

    def test_rejects_non_integer_doctor_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            for label, schema_version in (("boolean", True), ("float", 1.0)):
                with self.subTest(label=label):
                    with self.assertRaises(module.InstallerError):
                        module.install_tagged_skills(
                            tag="v0.8.1",
                            repo_root=source_repo,
                            skills_root=active_root,
                            backup_root=tmp_path / f"backup-{label}",
                            codex_runner=_make_fake_codex_runner(
                                skills_root=active_root,
                                doctor_payload={
                                    "schemaVersion": schema_version,
                                    "overallStatus": "ok",
                                    "checks": {
                                        "loader": {
                                            "id": "loader",
                                            "status": "ok",
                                        }
                                    },
                                },
                            ),
                        )

    def test_rejects_fake_doctor_non_ok_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=active_root,
                        doctor_payload={
                            "schemaVersion": 1,
                            "overallStatus": "fail",
                            "checks": {
                                "loader": {
                                    "id": "loader",
                                    "status": "fail",
                                }
                            },
                        },
                    ),
                )

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root_warn",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=active_root,
                        doctor_payload={
                            "schemaVersion": 1,
                            "overallStatus": "ok",
                            "checks": {
                                "loader": {
                                    "id": "loader",
                                    "status": "warn",
                                }
                            },
                        },
                    ),
                )

    def test_reject_missing_skills_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=active_root),
                )

    def test_locator_bytes_payload_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            result = module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                codex_runner=_make_fake_codex_runner(
                    skills_root=active_root,
                    nested_content=True,
                    debug_stdout_bytes=True,
                ),
            )
            self.assertEqual(result["tag"], "v0.8.1")

    def test_locator_and_doctor_stdout_bound_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=active_root,
                        nested_content=False,
                        debug_payload_override="x" * (module.MAX_STDOUT_BYTES + 1),
                    ),
                )

    def test_locator_and_doctor_stderr_bound_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=active_root,
                        debug_stderr="y" * (module.MAX_STDOUT_BYTES + 1),
                    ),
                )

    def test_real_subprocess_enforces_combined_streaming_output_bound(self) -> None:
        chunk_size = module.MAX_STDOUT_BYTES // 2 + 1024
        command = [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.stdout.write('x' * {chunk_size}); sys.stdout.flush(); "
                f"sys.stderr.write('y' * {chunk_size}); sys.stderr.flush()"
            ),
        ]
        with self.assertRaisesRegex(module.InstallerError, "combined"):
            module._run_with_capture(
                command,
                runner=subprocess.run,
                max_stdout_bytes=module.MAX_STDOUT_BYTES,
            )

    def test_output_bound_exception_frames_do_not_retain_payload(self) -> None:
        secret = "SENTINEL_BOUND_SECRET_58"

        def oversized_runner(
            cmd: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                secret * module.MAX_STDOUT_BYTES,
                "",
            )

        try:
            module._run_with_capture(
                ["fake"],
                runner=oversized_runner,
                max_stdout_bytes=module.MAX_STDOUT_BYTES,
            )
        except module.InstallerError as exc:
            tb = exc.__traceback__
            while tb is not None:
                if Path(tb.tb_frame.f_code.co_filename) == SCRIPT_PATH:
                    self.assertNotIn(secret, repr(tb.tb_frame.f_locals))
                tb = tb.tb_next
        else:
            self.fail("oversized output was accepted")

    def test_real_subprocess_timeout_kills_descendant_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sentinel = Path(tmp_dir) / "grandchild-survived"
            command = [
                sys.executable,
                "-c",
                (
                    "import os, pathlib, time; "
                    "pid=os.fork(); "
                    f"sentinel={str(sentinel)!r}; "
                    "(time.sleep(0.6), pathlib.Path(sentinel).write_text('alive')) "
                    "if pid == 0 else time.sleep(30)"
                ),
            ]
            with patch.object(module, "MAX_COMMAND_SECONDS", 0.15):
                with self.assertRaisesRegex(module.InstallerError, "time limit"):
                    module._run_with_capture(
                        command,
                        runner=subprocess.run,
                        max_stdout_bytes=module.MAX_STDOUT_BYTES,
                    )
            time.sleep(0.75)
            self.assertFalse(sentinel.exists())

    def test_codex_child_env_is_minimal_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            calls: list[tuple[list[str], dict[str, object]]] = []
            env_calls: list[dict[str, object]] = []

            original_path = os.environ.get("PATH", "")
            env_path = os.pathsep.join(["/custom/bin", original_path])

            def validate_env(env: object) -> None:
                assert isinstance(env, dict)
                unexpected = [
                    key
                    for key in env
                    if key != "CODEX_HOME" and key not in module.ALLOWED_ENV_KEYS
                ]
                self.assertEqual(unexpected, [])
                self.assertIn("/custom/bin", str(env.get("PATH")))
                self.assertEqual(env.get("HOME"), "/tmp/unused-home")
                self.assertNotIn("SECRET_TOKEN", env)
                self.assertNotIn("LC_SECRET_TOKEN", env)
                self.assertEqual(env.get("CODEX_HOME"), str(tmp_path / "codex-home"))
                env_calls.append(env)

            with patch.dict(
                os.environ,
                {
                    "SECRET_TOKEN": "top-secret",
                    "PATH": env_path,
                    "HOME": "/tmp/unused-home",
                    "LANG": "C",
                    "TERM": "xterm-256color",
                    "LC_ALL": "C.UTF-8",
                    "LC_SECRET_TOKEN": "locale-shaped-secret",
                },
            ):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_home=tmp_path / "codex-home",
                    codex_runner=_make_fake_codex_runner(
                        skills_root=active_root,
                        nested_content=True,
                        record_calls=calls,
                        validate_env=validate_env,
                    ),
                )
            self.assertGreaterEqual(len(calls), 2)
            self.assertGreaterEqual(len(env_calls), 2)

    def test_codex_child_env_preserves_nonsecret_terminal_identity(self) -> None:
        filtered = module._filter_env(
            {
                "HOME": "/tmp/home",
                "CODEX_HOME": "/tmp/home/.codex",
                "PATH": "/usr/bin:/bin",
                "VTE_VERSION": "8000",
                "OPENAI_API_KEY": "must-not-pass",
            }
        )
        self.assertEqual(filtered["VTE_VERSION"], "8000")
        self.assertNotIn("OPENAI_API_KEY", filtered)

    def test_rollback_on_doctor_failure(self) -> None:
        for required_skills in (module.DEFAULT_SKILLS, SELECTED_RESEARCH_SKILLS):
            with self.subTest(required_skills=required_skills):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
                    active_root = tmp_path / "active_skills"
                    for name in module.DEFAULT_SKILLS:
                        skill_dir = active_root / name
                        skill_dir.mkdir(parents=True, exist_ok=True)
                        (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")
                        (skill_dir / "local-only.txt").write_text(
                            f"local {name}\n", encoding="utf-8"
                        )
                    (active_root / "anchor.bin").write_bytes(b"\x00\xffKEEP")
                    os.chmod(active_root, 0o775)
                    old_root = active_root.stat()
                    old_files = {
                        path.relative_to(active_root): path.read_bytes()
                        for path in active_root.rglob("*")
                        if path.is_file()
                    }

                    backup_root = tmp_path / "backup_root"
                    codex_runner = _make_fake_codex_runner(
                        skills_root=active_root,
                        required_skills=required_skills,
                        doctor_exit_code=1,
                    )
                    with self.assertRaisesRegex(
                        module.InstallerError, "codex doctor --json failed"
                    ):
                        module.install_tagged_skills(
                            tag="v0.8.1",
                            repo_root=source_repo,
                            skills_root=active_root,
                            backup_root=backup_root,
                            required_skills=required_skills,
                            codex_runner=codex_runner,
                        )

                    self.assertEqual(codex_runner.call_count, 2)
                    candidates = list(backup_root.glob("v0.8.1-*"))
                    self.assertEqual(len(candidates), 1)
                    self.assertTrue((candidates[0] / "tag-verification.json").is_file())
                    self.assertFalse((candidates[0] / "prompt-debug-raw.json").exists())
                    self.assertFalse((candidates[0] / "doctor-raw.json").exists())
                    self.assertEqual(
                        {
                            path.relative_to(active_root): path.read_bytes()
                            for path in active_root.rglob("*")
                            if path.is_file()
                        },
                        old_files,
                    )
                    restored_root = active_root.stat()
                    self.assertEqual(
                        (restored_root.st_dev, restored_root.st_ino),
                        (old_root.st_dev, old_root.st_ino),
                    )
                    self.assertEqual(stat.S_IMODE(restored_root.st_mode), 0o775)

    def test_rollback_on_missing_locator_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")
            (active_root / "anchor.txt").write_text("keep", encoding="utf-8")

            backup_root = tmp_path / "backup_root"
            coderunner = _make_fake_codex_runner(
                skills_root=active_root,
                missing_locator=True,
            )
            with self.assertRaises(module.InstallerError):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=backup_root,
                    codex_runner=coderunner,
                )

            # failure must keep original content; backup receipts should still exist
            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )
            self.assertTrue((active_root / "anchor.txt").is_file())
            candidates = list(backup_root.glob("v0.8.1-*"))
            self.assertEqual(len(candidates), 1)
            self.assertTrue((candidates[0] / "tag-verification.json").is_file())
            self.assertFalse((candidates[0] / "prompt-debug-raw.json").exists())
            self.assertFalse((candidates[0] / "doctor-raw.json").exists())

    def test_rollback_on_keyboard_interrupt_after_exchange(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                skill_dir = active_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("OLD\n", encoding="utf-8")

            def interrupted_runner(
                _cmd: list[str], **_kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=active_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=interrupted_runner,
                )

            self.assertEqual(
                (active_root / module.DEFAULT_SKILLS[0] / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
                "OLD\n",
            )

    def test_reject_symlinked_skills_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            real_root = tmp_path / "real_skills"
            real_root.mkdir()
            alias_root = tmp_path / "skills_alias"
            alias_root.symlink_to(real_root, target_is_directory=True)

            with self.assertRaisesRegex(module.InstallerError, "symlink"):
                module.install_tagged_skills(
                    tag="v0.8.1",
                    repo_root=source_repo,
                    skills_root=alias_root,
                    backup_root=tmp_path / "backup_root",
                    codex_runner=_make_fake_codex_runner(skills_root=real_root),
                )

    def test_write_atomic_text_unlinks_temp_on_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "receipt.txt"

            class _FailingHandle:
                def __init__(self, fd: int) -> None:
                    self._fd = fd

                def __enter__(self) -> "_FailingHandle":
                    return self

                def __exit__(
                    self, _exc_type: object, _exc_value: object, _tb: object
                ) -> None:
                    os.close(self._fd)

                def write(self, _value: str) -> None:
                    raise OSError("injected write failure")

                def flush(self) -> None:
                    return None

                def close(self) -> None:
                    if self._fd >= 0:
                        os.close(self._fd)
                        self._fd = -1

            with patch.object(module.secrets, "token_hex", return_value="deadbeef"):
                with patch.object(
                    module.os,
                    "fdopen",
                    side_effect=lambda fd, *args, **kwargs: _FailingHandle(fd),
                ):
                    with self.assertRaises(OSError):
                        module._write_atomic_text(path, "payload")
            self.assertFalse((path.parent / ".receipt.txt.deadbeef.tmp").exists())

    def test_codex_home_is_passed_to_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_repo, _ = _create_repo_with_tag(tmp_path / "repo", "v0.8.1")
            active_root = tmp_path / "active_skills"
            for name in module.DEFAULT_SKILLS:
                (active_root / name / "SKILL.md").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (active_root / name / "SKILL.md").write_text("old\n", encoding="utf-8")

            calls: list[tuple[list[str], dict[str, object]]] = []
            custom_home = tmp_path / "custom-codex-home"
            module.install_tagged_skills(
                tag="v0.8.1",
                repo_root=source_repo,
                skills_root=active_root,
                backup_root=tmp_path / "backup_root",
                codex_home=custom_home,
                codex_runner=_make_fake_codex_runner(
                    skills_root=active_root,
                    nested_content=True,
                    record_calls=calls,
                ),
            )
            self.assertEqual(len(calls), 2)
            for _, kwargs in calls:
                env = kwargs.get("env")
                assert isinstance(env, dict)
                self.assertEqual(env.get("CODEX_HOME"), str(custom_home))

    def test_cli_defaults_follow_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            custom_home = Path(tmp_dir) / "codex-home"
            with patch.dict(os.environ, {"CODEX_HOME": str(custom_home)}):
                with patch.object(
                    sys,
                    "argv",
                    ["install_tagged_skills.py", "--tag", "v0.8.1"],
                ):
                    args = module.parse_args()
            self.assertEqual(Path(args.skills_root), custom_home / "skills")
            self.assertEqual(Path(args.backup_root), custom_home / "skill-backups")


class RootAliasLocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp_path = Path(self.temp_dir.name)
        self.skills_root = self.tmp_path / "active_skills"
        for name in SELECTED_RESEARCH_SKILLS:
            skill_file = self.skills_root / name / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text(f"name: {name}\n", encoding="utf-8")
        self.text = _root_alias_text(self.skills_root)

    def _parse(self, *blocks: str) -> list[str]:
        return module._parse_locator_output(
            _developer_text_payload(*blocks),
            self.skills_root,
            SELECTED_RESEARCH_SKILLS,
        )

    def _reject(self, *blocks: str) -> None:
        with self.assertRaises(module.InstallerError):
            self._parse(*blocks)

    def test_root_alias_accepts_multiple_roots_and_unrelated_skills(self) -> None:
        unrelated_root = self.tmp_path / "other_skills"
        text = self.text.replace(
            "### Available skills",
            f"\n- `r1` = `{unrelated_root}`\n\n### Available skills",
        )
        text += "\n- other: Unrelated. (file: r1/other/SKILL.md)"
        self.assertEqual(
            self._parse(text),
            sorted(
                str(self.skills_root / name / "SKILL.md")
                for name in SELECTED_RESEARCH_SKILLS
            ),
        )

    def test_root_alias_rejects_unknown_alias(self) -> None:
        self._reject(self.text.replace("r0/deep-research", "r7/deep-research"))
        self._reject(self.text + "\n- other: Unknown. (file: r7/other/SKILL.md)")

    def test_root_alias_rejects_duplicate_root_definition(self) -> None:
        self._reject(
            self.text.replace(
                "### Available skills",
                f"- `r0` = `{self.skills_root}`\n### Available skills",
            )
        )

    def test_root_alias_rejects_noncanonical_root_paths(self) -> None:
        variants = (
            f"{self.tmp_path}/../{self.tmp_path.name}/active_skills",
            f"{self.tmp_path}//active_skills",
            f"//{str(self.skills_root).lstrip('/')}",
            f"{self.tmp_path}/./active_skills",
            "relative/active_skills",
            f" {self.skills_root}",
            f"{self.skills_root} ",
            f"{self.skills_root}/",
        )
        for root in variants:
            with self.subTest(root=root):
                self._reject(self.text.replace(f"`{self.skills_root}`", f"`{root}`"))

    def test_root_alias_rejects_noncanonical_suffix_paths(self) -> None:
        variants = (
            "r0//deep-research/SKILL.md",
            "r0/../active_skills/deep-research/SKILL.md",
            "r0/./deep-research/SKILL.md",
            "r0/deep-research/../deep-research/SKILL.md",
            "r0/deep-research//SKILL.md",
            " r0/deep-research/SKILL.md",
            "r0/deep-research/SKILL.md ",
        )
        for location in variants:
            with self.subTest(location=location):
                self._reject(self.text.replace("r0/deep-research/SKILL.md", location))

    def test_root_alias_rejects_control_characters_in_roots_and_suffixes(self) -> None:
        for character in ("\t", "\x00", "\x1f", "\x7f"):
            with self.subTest(character=repr(character), field="root"):
                root = f"{self.tmp_path}/active{character}_skills"
                self._reject(self.text.replace(f"`{self.skills_root}`", f"`{root}`"))
            with self.subTest(character=repr(character), field="suffix"):
                self._reject(
                    self.text.replace(
                        "r0/deep-research/SKILL.md",
                        f"r0/deep{character}-research/SKILL.md",
                    )
                )

    def test_root_alias_rejects_mixed_absolute_and_short_duplicate(self) -> None:
        exact = self.skills_root / "deep-research" / "SKILL.md"
        self._reject(self.text + f"\n- repeated: Duplicate. (file: {exact})")

    def test_root_alias_rejects_target_outside_exact_path(self) -> None:
        other_root = self.tmp_path / "other_skills"
        outside_file = other_root / "deep-research" / "SKILL.md"
        outside_file.parent.mkdir(parents=True)
        outside_file.write_text("different source\n", encoding="utf-8")
        text = self.text.replace(
            "### Available skills",
            f"- `r1` = `{other_root}`\n### Available skills",
        )
        self._reject(
            text + "\n- repeated: Other source. (file: r1/deep-research/SKILL.md)"
        )

    def test_root_alias_rejects_renamed_symlink_and_hardlink_aliases(self) -> None:
        target = self.skills_root / "deep-research" / "SKILL.md"
        symlink_root = self.tmp_path / "renamed-symlink"
        symlink_root.symlink_to(target.parent, target_is_directory=True)
        hardlink_root = self.tmp_path / "renamed-hardlink"
        hardlink_root.mkdir()
        os.link(target, hardlink_root / "SKILL.md")
        for alias_root in (symlink_root, hardlink_root):
            with self.subTest(alias_root=alias_root.name):
                text = self.text.replace(
                    "### Available skills",
                    f"- `r1` = `{alias_root}`\n### Available skills",
                )
                self._reject(text + "\n- renamed: Alias. (file: r1/SKILL.md)")

    def test_root_alias_does_not_share_bindings_between_content_blocks(self) -> None:
        definitions, entries = self.text.split("### Available skills", 1)
        self._reject(definitions + "### Available skills", entries)

    def test_root_alias_does_not_share_bindings_between_messages(self) -> None:
        definitions, entries = self.text.split("### Available skills", 1)
        payload = json.dumps(
            [
                {
                    "role": "developer",
                    "content": {"input_text": definitions + "### Available skills"},
                },
                {"role": "developer", "content": {"input_text": entries}},
            ]
        )
        with self.assertRaises(module.InstallerError):
            module._parse_locator_output(
                payload, self.skills_root, SELECTED_RESEARCH_SKILLS
            )

    def test_root_alias_rejects_tables_in_untrusted_message_roles(self) -> None:
        for role in ("user", "assistant", None):
            with self.subTest(role=role):
                message = {"content": [{"type": "input_text", "text": self.text}]}
                if role is not None:
                    message["role"] = role
                with self.assertRaises(module.InstallerError):
                    module._parse_locator_output(
                        json.dumps([message]),
                        self.skills_root,
                        SELECTED_RESEARCH_SKILLS,
                    )

    def test_root_alias_rejects_definitions_outside_roots_table(self) -> None:
        self._reject(self.text.replace("### Skill roots", "### Other configuration"))
        self._reject(self.text.replace("### Skill roots\n", ""))

    def test_root_alias_rejects_malformed_roots_table(self) -> None:
        malformed = {
            "missing-available-header": self.text.replace("### Available skills", ""),
            "unexpected-table-line": self.text.replace(
                "### Available skills", "read this root\n### Available skills"
            ),
            "missing-path-backticks": self.text.replace(
                f"`{self.skills_root}`", str(self.skills_root)
            ),
            "invalid-alias-name": self.text.replace("`r0`", "`root0`"),
            "duplicate-section": self.text.replace(
                "### Available skills",
                f"### Skill roots\n- `r1` = `{self.tmp_path}`\n### Available skills",
            ),
        }
        for label, text in malformed.items():
            with self.subTest(label=label):
                self._reject(text)


if __name__ == "__main__":
    unittest.main()
