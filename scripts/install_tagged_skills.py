#!/usr/bin/env python3
"""Install an annotated-tag skill set with whole-root atomic swap and loader checks."""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import io
import json
import os
import re
import selectors
import shutil
import signal
import stat
import tarfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

import subprocess

import secrets

MAX_STDOUT_BYTES = 1024 * 1024
MAX_COMMAND_SECONDS = 60.0
OUTPUT_READ_CHUNK_BYTES = 64 * 1024
DIRECTORY_MANIFEST_SHA256 = hashlib.sha256(b"directory\0").hexdigest()
ALLOWED_ENV_KEYS = {
    "PATH",
    "HOME",
    "CODEX_HOME",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "COLORTERM",
    "NO_COLOR",
    "VTE_VERSION",
    "XDG_RUNTIME_DIR",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
}
ALLOWED_DOCTOR_STATUSES = {"ok"}

DEFAULT_SKILLS = (
    "curate-research-to-zotero",
    "deep-research",
    "evidence-appraisal",
    "learn-from-papers",
    "network-gap-discovery",
    "research-knowledge-network",
    "research-network-publish",
    "research-workflow-retrospective",
    "repair-zotero-metadata",
    "scholar-discovery",
    "scholarly-document-normalization",
    "scholarly-source-acquisition",
)

DEFAULT_PROMPT = (
    "Use $deep-research and only confirm the following 12 SKILL.md locators appear "
    "exactly once."
)

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class InstallerError(RuntimeError):
    """Raised when install preconditions or post checks fail."""

    def __init__(self, message: str, *, recovery_root: Path | None = None) -> None:
        super().__init__(message)
        self.recovery_root = recovery_root


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    mode: str
    sha256: str


PathIdentity = tuple[int, int]


def _run_with_capture(
    cmd: list[str],
    *,
    runner: CommandRunner,
    cwd: Path | None = None,
    extra_args: dict[str, object] | None = None,
    max_stdout_bytes: int | None = None,
) -> subprocess.CompletedProcess[str]:
    opts: dict[str, object] = {
        "text": True,
        "capture_output": True,
    }
    if cwd is not None:
        opts["cwd"] = str(cwd)
    if extra_args:
        if "env" in extra_args and isinstance(extra_args["env"], dict):
            extra = dict(extra_args)
            extra["env"] = _filter_env(extra["env"])
            opts.update(extra)
        else:
            opts.update(extra_args)
    if max_stdout_bytes is not None and runner is subprocess.run:
        return _run_bounded_subprocess(
            cmd,
            cwd=Path(str(opts["cwd"])) if "cwd" in opts else None,
            env=opts.get("env") if isinstance(opts.get("env"), dict) else None,
            max_bytes=max_stdout_bytes,
        )
    try:
        result = runner(cmd, **opts)
    except TypeError:
        try:
            opts.pop("cwd")
            result = runner(cmd, **opts)
        except TypeError:
            result = runner(cmd)
    if max_stdout_bytes is not None:
        try:
            stdout = _bounded_payload(result.stdout, max_stdout_bytes, stream="stdout")
            stderr = _bounded_payload(
                getattr(result, "stderr", ""), max_stdout_bytes, stream="stderr"
            )
            if len(stdout) + len(stderr) > max_stdout_bytes:
                stdout = b""
                stderr = b""
                result.stdout = ""
                result.stderr = ""
                raise InstallerError(
                    "combined subprocess output exceeded the byte limit"
                )
        except InstallerError:
            result.stdout = ""
            result.stderr = ""
            raise
    return result


def _run_bounded_subprocess(
    cmd: list[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str] | None,
    max_bytes: int,
) -> subprocess.CompletedProcess[str]:
    """Capture stdout and stderr while enforcing one combined in-flight limit."""

    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise InstallerError("subprocess capture streams were unavailable")

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    total_bytes = 0
    chunk = b""
    deadline = time.monotonic() + MAX_COMMAND_SECONDS
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InstallerError("subprocess exceeded the time limit")
            events = selector.select(min(remaining, 0.25))
            for key, _mask in events:
                chunk = os.read(key.fd, OUTPUT_READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise InstallerError(
                        "combined subprocess output exceeded the byte limit"
                    )
                buffers[str(key.data)].extend(chunk)
        return_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        chunk = b""
        buffers["stdout"].clear()
        buffers["stderr"].clear()
        raise
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            if not stream.closed:
                stream.close()

    return subprocess.CompletedProcess(
        cmd,
        return_code,
        stdout=bytes(buffers["stdout"]).decode("utf-8", errors="replace"),
        stderr=bytes(buffers["stderr"]).decode("utf-8", errors="replace"),
    )


def _bounded_payload(
    payload: object | None, max_bytes: int, stream: str = "stdout"
) -> bytes:
    if not isinstance(payload, bytes):
        payload = _as_text(payload).encode("utf-8", errors="replace")
    if len(payload) > max_bytes:
        payload = b""
        raise InstallerError(f"{stream} exceeded max bytes ({max_bytes})")
    return payload


def _filter_env(env: Mapping[str, object]) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(key, str):
            continue
        if key == "CODEX_HOME" or key in ALLOWED_ENV_KEYS:
            allowed[key] = str(value)
    return allowed


def _absolute_canonical_path(value: str) -> str:
    if value != value.strip():
        raise InstallerError("locator path contains surrounding whitespace")
    if not value.startswith("/"):
        raise InstallerError("locator path must be absolute")
    if value.startswith("//"):
        raise InstallerError("locator path contains a doubled leading separator")
    if "\x00" in value:
        raise InstallerError("locator path contains a NUL byte")
    if "\n" in value or "\r" in value:
        raise InstallerError("locator path contains a newline")
    if "//" in value[1:]:
        raise InstallerError("locator path contains a doubled separator")
    if any(part in (".", "..") for part in value.split("/")):
        raise InstallerError("locator path contains a relative segment")
    return value


def _validate_doctor_payload_impl(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise InstallerError("codex doctor output is not an object")

    schema_version = payload.get("schemaVersion")
    if type(schema_version) is not int or schema_version != 1:
        raise InstallerError("codex doctor schemaVersion must be integer 1")

    overall_status = payload.get("overallStatus")
    if overall_status != "ok":
        raise InstallerError("codex doctor overallStatus is not ok")

    checks = payload.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise InstallerError("codex doctor checks must be a non-empty object")

    observed_status_counts: dict[str, int] = {}
    check_ids: list[str] = []
    for check_id, check_data in checks.items():
        if not isinstance(check_id, str):
            raise InstallerError("codex doctor check id is not a string")
        if not isinstance(check_data, Mapping):
            raise InstallerError("codex doctor check is not an object")
        check_ids.append(check_id)
        check_status = check_data.get("status")
        if check_status not in ALLOWED_DOCTOR_STATUSES:
            raise InstallerError("codex doctor check status is not ok")
        recorded_id = check_data.get("id")
        if recorded_id != check_id:
            raise InstallerError("codex doctor check id does not match its key")
        observed_status_counts[check_status] = (
            observed_status_counts.get(check_status, 0) + 1
        )
    normalized_status_counts = {}
    for status, count in observed_status_counts.items():
        normalized_status_counts[status] = count

    return {
        "schemaVersion": 1,
        "overallStatus": "ok",
        "status_counts": normalized_status_counts,
        "check_count": len(check_ids),
        "check_ids_sha256": hashlib.sha256(
            json.dumps(sorted(check_ids), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _try_validate_doctor_payload(
    payload: object,
) -> tuple[dict[str, object] | None, bool]:
    try:
        if not isinstance(payload, Mapping):
            return None, False
        return _validate_doctor_payload_impl(payload), True
    except InstallerError:
        return None, False


def _validate_doctor_payload(payload: Mapping[str, object]) -> dict[str, object]:
    summary, valid = _try_validate_doctor_payload(payload)
    payload = {}
    if not valid or summary is None:
        raise InstallerError("codex doctor output failed strict schema validation")
    return summary


def _run_command(
    cmd: list[str],
    cwd: Path,
    *,
    runner: CommandRunner,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = _run_with_capture(cmd, cwd=cwd, runner=runner)
    if check and result.returncode != 0:
        raise InstallerError(
            f"command failed with exit code {result.returncode}: {' '.join(cmd)}"
        )
    return result


def _as_text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _hex_mode(path: Path) -> str:
    return f"{os.stat(path).st_mode & 0o777:03o}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_payload(manifest: dict[str, ManifestEntry]) -> str:
    return (
        json.dumps(
            {path: entry.__dict__ for path, entry in manifest.items()},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _manifest_to_bytes(manifest: dict[str, ManifestEntry]) -> bytes:
    return _manifest_payload(manifest).encode("utf-8")


def _existing_symlink_ancestor_check(path: Path) -> None:
    allow = {Path("/"), Path("/home")}
    check_path = path if path.is_absolute() else (Path.cwd() / path)
    for ancestor in (check_path, *check_path.parents):
        if ancestor in allow:
            continue
        try:
            mode = os.lstat(ancestor).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise InstallerError(f"path ancestor is symlink: {ancestor}")


def _validate_existing_ancestor_no_symlink(path: Path) -> None:
    _existing_symlink_ancestor_check(path)


def _compute_manifest(root: Path, skills: Iterable[str]) -> dict[str, ManifestEntry]:
    manifest: dict[str, ManifestEntry] = {}
    base = root.resolve()
    for skill in skills:
        skill_path = base / skill
        if skill_path.is_symlink():
            raise InstallerError(f"required skill path is symlink: {skill_path}")
        skill_root = skill_path.resolve()
        if not skill_root.exists():
            raise InstallerError(f"missing skill directory: {skill_root}")
        if not skill_root.is_dir():
            raise InstallerError(
                f"required skill path is not a directory: {skill_root}"
            )
        root_key = f"{skill}/"
        manifest[root_key] = ManifestEntry(
            path=root_key,
            mode=_hex_mode(skill_root),
            sha256=DIRECTORY_MANIFEST_SHA256,
        )
        for path in skill_root.rglob("*"):
            if path.is_symlink():
                raise InstallerError(f"source contains disallowed symlink: {path}")
            relpath = path.relative_to(base).as_posix()
            if path.is_dir():
                directory_key = f"{relpath}/"
                manifest[directory_key] = ManifestEntry(
                    path=directory_key,
                    mode=_hex_mode(path),
                    sha256=DIRECTORY_MANIFEST_SHA256,
                )
                continue
            if not path.is_file():
                raise InstallerError(f"source contains non-regular path: {relpath}")
            manifest[relpath] = ManifestEntry(
                path=relpath,
                mode=_hex_mode(path),
                sha256=_sha256_file(path),
            )
    return manifest


def _write_atomic_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{int(time.time())}-{hash(payload) & 0xFFFFFF:x}.tmp"
    )
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    handle: object | None = None
    try:
        handle = os.fdopen(fd, "w", encoding="utf-8")
        with handle:
            handle.write(payload)
            handle.flush()
    except BaseException:
        if handle is None:
            os.close(fd)
        if tmp.exists():
            os.unlink(tmp)
        raise
    os.replace(tmp, path)


def _write_json(path: Path, payload: object) -> None:
    _write_atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_manifest(path: Path, manifest: dict[str, ManifestEntry]) -> None:
    _write_atomic_text(path, _manifest_payload(manifest))


def _ensure_clean_repo(repo_root: Path, runner: CommandRunner) -> None:
    status = _run_command(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        repo_root,
        runner=runner,
    ).stdout.strip()
    if status:
        raise InstallerError(
            "repository is not clean; commit and clean working tree first"
        )


def _tracked_skill_paths(
    repo_root: Path, skills: Iterable[str], runner: CommandRunner
) -> set[str]:
    skill_paths = [f"skills/{skill}" for skill in skills]
    tree = _run_command(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", *skill_paths],
        repo_root,
        runner=runner,
    ).stdout.splitlines()
    tracked = {line.strip() for line in tree if line.strip()}
    if not tracked:
        raise InstallerError("no tracked files found for required skills")
    return tracked


def _verify_clean_tag_tree(
    repo_root: Path,
    required_skills: Iterable[str],
    runner: CommandRunner,
) -> None:
    skill_paths = [f"skills/{skill}" for skill in required_skills]
    tracked = _tracked_skill_paths(repo_root, required_skills, runner)

    observed: set[str] = set()
    for skill in required_skills:
        skill_root = repo_root / "skills" / skill
        for path in skill_root.rglob("*"):
            if path.is_symlink():
                relpath = path.relative_to(repo_root)
                raise InstallerError(f"source contains disallowed symlink: {relpath}")
            if path.is_dir():
                continue
            if not path.is_file():
                relpath = path.relative_to(repo_root)
                raise InstallerError(f"source contains non-regular path: {relpath}")
            relpath = path.relative_to(repo_root)
            key = relpath.as_posix()
            if key not in tracked:
                raise InstallerError(
                    f"source contains untracked or ignored file: {relpath}"
                )
            observed.add(key)

    missing = sorted(tracked - observed)
    if missing:
        raise InstallerError(f"tag tree missing tracked files: {missing}")

    dirty = _run_command(
        ["git", "diff", "--name-only", "--"] + skill_paths,
        repo_root,
        runner=runner,
        check=False,
    ).stdout.strip()
    if dirty:
        raise InstallerError("tracked target-skill files are modified in working tree")

    staged = _run_command(
        ["git", "diff", "--name-only", "--cached", "--"] + skill_paths,
        repo_root,
        runner=runner,
        check=False,
    ).stdout.strip()
    if staged:
        raise InstallerError("tracked target-skill files are staged/dirty")


def _verify_annotated_tag(
    repo_root: Path,
    tag: str,
    runner: CommandRunner,
) -> tuple[str, str]:
    tag_ref = f"refs/tags/{tag}"
    tag_object = _run_command(
        ["git", "rev-parse", tag_ref], repo_root, runner=runner
    ).stdout.strip()
    tag_type = _run_command(
        ["git", "cat-file", "-t", tag_ref], repo_root, runner=runner
    ).stdout.strip()
    if tag_type != "tag":
        raise InstallerError(f"{tag} is not annotated (type={tag_type})")
    tag_commit = _run_command(
        ["git", "rev-parse", f"{tag_ref}^{{}}"],
        repo_root,
        runner=runner,
    ).stdout.strip()
    head = _run_command(
        ["git", "rev-parse", "HEAD"], repo_root, runner=runner
    ).stdout.strip()
    if head != tag_commit:
        raise InstallerError(
            f"checked out commit is not the tagged commit ({head} != {tag_commit})"
        )
    return tag_object, tag_commit


def _verify_remote_refs(
    repo_root: Path,
    tag: str,
    local_tag_object: str,
    local_tag_commit: str,
    runner: CommandRunner,
) -> None:
    output = (
        _run_command(
            [
                "git",
                "ls-remote",
                "--tags",
                "origin",
                f"refs/tags/{tag}",
                f"refs/tags/{tag}^{{}}",
            ],
            repo_root,
            runner=runner,
        )
        .stdout.strip()
        .splitlines()
    )
    remote: dict[str, str] = {}
    for line in output:
        if "\t" not in line:
            continue
        value, ref = line.split("\t", 1)
        remote[ref.strip()] = value.strip()

    expected_tag_ref = f"refs/tags/{tag}"
    expected_p_ref = f"refs/tags/{tag}^{{}}"
    if expected_tag_ref not in remote or expected_p_ref not in remote:
        raise InstallerError(f"origin does not expose both tag refs for {tag}")
    if remote[expected_tag_ref] != local_tag_object:
        raise InstallerError("tag object in origin does not match local tag object")
    if remote[expected_p_ref] != local_tag_commit:
        raise InstallerError("peeled tag commit in origin does not match local commit")


def _validate_archive_name(path_name: str) -> str:
    if not path_name:
        return ""
    if path_name.startswith("/"):
        raise InstallerError(f"archive path is absolute: {path_name}")
    normalized = Path(path_name)
    if any(part == ".." for part in normalized.parts):
        raise InstallerError(f"archive path contains traversal: {path_name}")
    if path_name.startswith("./"):
        raise InstallerError(f"archive path is unsafe: {path_name}")
    return path_name


def _materialize_skill_snapshot(
    repo_root: Path,
    commit: str,
    skills: Iterable[str],
    runner: CommandRunner,
    snapshot_root: Path,
) -> tuple[Path, int, PathIdentity, dict[str, ManifestEntry]]:
    skill_names = tuple(skills)
    allowed_skills = set(skill_names)
    skill_paths = [f"skills/{skill}" for skill in skill_names]
    archive_result = _run_with_capture(
        [
            "git",
            "archive",
            "--format=tar",
            commit,
            "--",
            *skill_paths,
        ],
        cwd=repo_root,
        runner=runner,
        extra_args={"text": False},
    )
    if archive_result.returncode != 0:
        raise InstallerError(f"git archive failed: {archive_result.stderr}")
    raw = archive_result.stdout
    if isinstance(raw, str):
        raw = raw.encode("utf-8")

    if snapshot_root.exists():
        raise InstallerError(f"tag snapshot path already exists: {snapshot_root}")
    os.mkdir(snapshot_root, 0o700)
    snapshot_fd = os.open(
        snapshot_root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    )
    snapshot_stat = os.fstat(snapshot_fd)
    snapshot_identity = (snapshot_stat.st_dev, snapshot_stat.st_ino)
    snapshot_entries = list(_stable_directory_path(snapshot_fd).iterdir())
    if snapshot_entries or _path_identity(snapshot_root) != snapshot_identity:
        os.close(snapshot_fd)
        raise InstallerError(
            "tag snapshot changed or was populated before stable binding"
        )
    stable_snapshot_root = _stable_directory_path(snapshot_fd)
    seen_skills: set[str] = set()
    expected_manifest: dict[str, ManifestEntry] = {}

    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r|*") as tar:
            while True:
                member = tar.next()
                if member is None:
                    break
                name = _validate_archive_name(member.name)
                if not name:
                    continue

                parts = Path(name).parts
                if not parts or parts[0] != "skills":
                    raise InstallerError(f"archive entry is outside skills/: {name}")
                if len(parts) > 1 and parts[1] not in allowed_skills:
                    raise InstallerError(
                        f"archive contains an unrequested skill entry: {name}"
                    )

                if member.issym() or member.islnk():
                    raise InstallerError(f"archive contains symlink entry: {name}")
                if member.isdir():
                    target = stable_snapshot_root / name
                    target.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        os.chmod(target, stat.S_IMODE(member.mode))
                    if len(parts) > 1:
                        seen_skills.add(parts[1])
                        directory_key = f"{Path(*parts[1:]).as_posix().rstrip('/')}/"
                        if directory_key in expected_manifest:
                            raise InstallerError(
                                f"archive contains duplicate entry: {name}"
                            )
                        expected_manifest[directory_key] = ManifestEntry(
                            path=directory_key,
                            mode=f"{stat.S_IMODE(member.mode):03o}",
                            sha256=DIRECTORY_MANIFEST_SHA256,
                        )
                    continue

                if (
                    member.isdev()
                    or member.isblk()
                    or member.ischr()
                    or member.isfifo()
                ):
                    raise InstallerError(f"archive contains special entry: {name}")
                if not member.isfile():
                    raise InstallerError(f"unsupported archive entry type: {name}")

                source = tar.extractfile(member)
                if source is None:
                    raise InstallerError(f"could not read archive entry: {name}")
                payload = source.read()
                if len(payload) != member.size:
                    raise InstallerError(f"archive entry was truncated: {name}")
                if len(parts) < 3:
                    raise InstallerError(f"archive file path is incomplete: {name}")
                relpath = Path(*parts[1:]).as_posix()
                if relpath in expected_manifest:
                    raise InstallerError(f"archive contains duplicate entry: {name}")
                expected_manifest[relpath] = ManifestEntry(
                    path=relpath,
                    mode=f"{stat.S_IMODE(member.mode):03o}",
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
                target = stable_snapshot_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as out:
                    out.write(payload)
                os.chmod(target, stat.S_IMODE(member.mode))
                seen_skills.add(parts[1])

        for skill in skill_names:
            skill_root = stable_snapshot_root / "skills" / skill
            if not skill_root.is_dir():
                raise InstallerError(
                    f"required skill path missing in tag snapshot: {skill}"
                )
            if not any(path.is_file() for path in skill_root.rglob("*")):
                raise InstallerError(f"required skill is empty: {skill}")

        observed = {
            entry.name
            for entry in stable_snapshot_root.iterdir()
            if entry.name == "skills"
        }
        if not observed:
            raise InstallerError("tag snapshot missing skills/ directory")
        if _path_identity(snapshot_root) != snapshot_identity:
            raise InstallerError("tag snapshot pathname identity changed")
        if seen_skills != allowed_skills:
            raise InstallerError(
                "tag snapshot skill set does not match requested skills"
            )
        extracted_manifest = _compute_manifest(
            stable_snapshot_root / "skills", skill_names
        )
        if _manifest_to_bytes(extracted_manifest) != _manifest_to_bytes(
            expected_manifest
        ):
            raise InstallerError(
                "tag snapshot bytes do not match the git archive manifest"
            )
    except BaseException:
        os.close(snapshot_fd)
        raise

    return snapshot_root, snapshot_fd, snapshot_identity, expected_manifest


def _copy_loader_root(source_root: Path, stage_root: Path) -> tuple[int, PathIdentity]:
    stage_root.parent.mkdir(parents=True, exist_ok=True)
    if stage_root.exists():
        raise InstallerError(f"stage root already exists: {stage_root}")
    os.mkdir(stage_root, 0o700)
    stage_fd = os.open(
        stage_root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    )
    stage_stat = os.fstat(stage_fd)
    created_identity = (stage_stat.st_dev, stage_stat.st_ino)
    stable_stage_root = _stable_directory_path(stage_fd)
    stage_entries = list(stable_stage_root.iterdir())
    if stage_entries or _path_identity(stage_root) != created_identity:
        os.close(stage_fd)
        raise InstallerError(
            "stage root changed or was populated before stable binding"
        )
    if not source_root.exists():
        return stage_fd, created_identity
    if not source_root.is_dir():
        os.close(stage_fd)
        raise InstallerError(f"source root is not a directory: {source_root}")
    try:
        for source_child in source_root.iterdir():
            stage_child = stable_stage_root / source_child.name
            if source_child.is_symlink():
                target = os.readlink(source_child)
                os.symlink(target, stage_child)
                continue
            if source_child.is_dir():
                shutil.copytree(
                    source_child,
                    stage_child,
                    symlinks=True,
                    copy_function=shutil.copy2,
                )
                continue
            if source_child.is_file():
                shutil.copy2(source_child, stage_child)
                continue
            raise InstallerError(
                f"source root contains non-regular child entry: {source_child}"
            )
    except BaseException:
        os.close(stage_fd)
        raise
    return stage_fd, created_identity


def _replace_target_skills(
    source_root: Path, stage_root: Path, skills: Iterable[str]
) -> None:
    source_root = source_root / "skills"
    for skill in skills:
        source_skill = source_root / skill
        target_skill = stage_root / skill
        if target_skill.is_symlink():
            raise InstallerError(f"destination skill path is symlink: {target_skill}")
        if target_skill.is_dir():
            shutil.rmtree(target_skill)
        elif target_skill.exists():
            target_skill.unlink()
        if target_skill.exists():
            raise InstallerError(
                f"destination skill path did not clear: {target_skill}"
            )

        shutil.copytree(
            source_skill,
            target_skill,
            symlinks=False,
            copy_function=shutil.copy2,
        )


def _parse_locator_output_impl(
    output: str, skills_root: Path, skills: Iterable[str]
) -> list[str]:
    expected_by_skill = {
        skill: _absolute_canonical_path(str(skills_root / skill / "SKILL.md"))
        for skill in skills
    }
    expected = set(expected_by_skill.values())
    expected_count = len(expected)
    candidates: list[str] = []

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = None
    if payload is None:
        raise InstallerError("codex debug prompt-input output is not valid JSON")

    if not isinstance(payload, list):
        raise InstallerError("codex debug prompt-input output must be a JSON list")

    values: list[str] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise InstallerError(
                "codex debug prompt-input output contains non-object item"
            )
        content = item.get("content")
        if isinstance(content, Mapping):
            input_text = content.get("input_text")
            if isinstance(input_text, str):
                values.append(input_text)
                continue
            raise InstallerError(
                "codex debug prompt-input output content mapping missing input_text string"
            )
        if isinstance(content, list):
            if not content:
                raise InstallerError(
                    "codex debug prompt-input output content list is empty"
                )
            for block in content:
                if not isinstance(block, Mapping):
                    raise InstallerError(
                        "codex debug prompt-input output content list item is not an object"
                    )
                block_type = block.get("type")
                block_text = block.get("text")
                if not isinstance(block_type, str):
                    raise InstallerError(
                        "codex debug prompt-input output content block missing type"
                    )
                if not isinstance(block_text, str):
                    raise InstallerError(
                        "codex debug prompt-input output content block missing text"
                    )
                if block_type == "input_text":
                    values.append(block_text)
            continue
        raise InstallerError(
            "codex debug prompt-input output content must be an object or list"
        )

    if not values:
        raise InstallerError("codex debug prompt-input output contains no locator text")

    file_pattern = re.compile(r"\(file: ([^\)\r\n]+)\)")
    for value in values:
        for match in file_pattern.finditer(value):
            location = match.group(1)
            if location.endswith("SKILL.md"):
                candidates.append(_absolute_canonical_path(location))

    counts: dict[str, int] = {}
    for path in candidates:
        counts[path] = counts.get(path, 0) + 1

    for skill, expected_path in expected_by_skill.items():
        if counts.get(expected_path, 0) != 1:
            raise InstallerError(
                f"locator occurrence mismatch for required skill {skill}"
            )

    duplicate_names: set[str] = set()
    for candidate in candidates:
        candidate_path = Path(candidate)
        if candidate_path.name != "SKILL.md":
            continue
        parent_name = candidate_path.parent.name
        if (
            parent_name in expected_by_skill
            and candidate != expected_by_skill[parent_name]
        ):
            duplicate_names.add(parent_name)

    if duplicate_names:
        raise InstallerError("target skill locator appears outside its exact path")

    expected_resolved = {Path(path).resolve(strict=True) for path in expected}
    expected_identities = {
        (metadata.st_dev, metadata.st_ino)
        for path in expected
        for metadata in (os.stat(path, follow_symlinks=False),)
    }
    for candidate in candidates:
        if candidate in expected:
            continue
        try:
            resolved_candidate = Path(candidate).resolve(strict=True)
            candidate_metadata = os.stat(candidate, follow_symlinks=False)
        except (FileNotFoundError, OSError):
            continue
        if resolved_candidate in expected_resolved:
            raise InstallerError("target skill locator appears through an alias path")
        if (
            candidate_metadata.st_dev,
            candidate_metadata.st_ino,
        ) in expected_identities:
            raise InstallerError("target skill locator appears through an alias path")

    if len(candidates) < expected_count:
        raise InstallerError(
            f"locator count mismatch from codex debug: {len(candidates)}"
        )

    return sorted(expected_by_skill.values())


def _try_parse_locator_output(
    output: str, skills_root: Path, skills: Iterable[str]
) -> tuple[list[str] | None, bool]:
    try:
        return _parse_locator_output_impl(output, skills_root, skills), True
    except (InstallerError, json.JSONDecodeError, OSError, ValueError):
        return None, False


def _parse_locator_output(
    output: str, skills_root: Path, skills: Iterable[str]
) -> list[str]:
    locator_paths, valid = _try_parse_locator_output(output, skills_root, skills)
    output = ""
    if not valid or locator_paths is None:
        raise InstallerError(
            "codex debug prompt-input failed strict locator validation"
        )
    return locator_paths


def _try_parse_doctor_output(
    output: str,
) -> tuple[dict[str, object] | None, bool]:
    try:
        payload = json.loads(output or "{}")
    except json.JSONDecodeError:
        return None, False
    return _try_validate_doctor_payload(payload)


def _verify_codex_loader(
    skills_root: Path,
    skills: Iterable[str],
    runner: CommandRunner,
    codex_home: Path,
) -> tuple[list[str], Mapping[str, object]]:
    env = {**os.environ, "CODEX_HOME": str(codex_home)}
    debug_result = _run_with_capture(
        ["codex", "debug", "prompt-input", DEFAULT_PROMPT],
        runner=runner,
        extra_args={"env": env},
        max_stdout_bytes=MAX_STDOUT_BYTES,
    )
    if debug_result.returncode != 0:
        debug_result.stdout = ""
        debug_result.stderr = ""
        raise InstallerError("codex debug prompt-input failed")
    debug_payload = _as_text(getattr(debug_result, "stdout", ""))
    locator_paths, locator_valid = _try_parse_locator_output(
        debug_payload, skills_root, skills
    )
    debug_payload = ""
    debug_result.stdout = ""
    debug_result.stderr = ""
    if not locator_valid or locator_paths is None:
        raise InstallerError(
            "codex debug prompt-input failed strict locator validation"
        )

    doctor_result = _run_with_capture(
        ["codex", "doctor", "--json"],
        runner=runner,
        extra_args={"env": env},
        max_stdout_bytes=MAX_STDOUT_BYTES,
    )
    doctor_payload = _as_text(getattr(doctor_result, "stdout", ""))
    if doctor_result.returncode != 0:
        doctor_payload = ""
        doctor_result.stdout = ""
        doctor_result.stderr = ""
        raise InstallerError("codex doctor --json failed")
    doctor_summary, doctor_valid = _try_parse_doctor_output(doctor_payload)
    doctor_payload = ""
    doctor_result.stdout = ""
    doctor_result.stderr = ""
    if not doctor_valid or doctor_summary is None:
        raise InstallerError("codex doctor output failed strict schema validation")
    return locator_paths, doctor_summary


def _exchange_atomically(path_a: Path, path_b: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise InstallerError("renameat2 unavailable in libc")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    AT_FDCWD = -100
    RENAME_EXCHANGE = 2
    ret = renameat2(
        AT_FDCWD,
        os.fsencode(str(path_a)),
        AT_FDCWD,
        os.fsencode(str(path_b)),
        ctypes.c_uint(RENAME_EXCHANGE),
    )
    if ret != 0:
        raise InstallerError(
            f"renameat2 RENAME_EXCHANGE failed: {os.strerror(ctypes.get_errno())}"
        )


def _exchange_verified_identities(
    path_a: Path,
    path_b: Path,
    *,
    identity_a: PathIdentity,
    identity_b: PathIdentity,
    exchange: Callable[[Path, Path], None],
) -> str:
    """Exchange exact path identities, reversing one wrong-object swap immediately."""

    if _path_identity(path_a) != identity_a or _path_identity(path_b) != identity_b:
        return "identity_changed"
    exchange(path_a, path_b)
    if _path_identity(path_a) == identity_b and _path_identity(path_b) == identity_a:
        return "exchanged"

    reverse_error: BaseException | None = None
    if _path_identity(path_b) == identity_a:
        try:
            exchange(path_a, path_b)
        except BaseException as exc:
            reverse_error = exc
    if _path_identity(path_a) == identity_a:
        return "identity_changed"
    recovery_root = _identity_locator(identity_a, (path_a, path_b))
    message = "atomic exchange used a changed path identity"
    if recovery_root is not None:
        message += f"; recovery_root={recovery_root}"
    raise InstallerError(message, recovery_root=recovery_root) from reverse_error


def _make_backup_root(
    parent: Path,
    tag: str,
    commit: str,
    *,
    skills_parent: Path,
) -> Path:
    parent = parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    if os.stat(parent).st_dev != os.stat(skills_parent).st_dev:
        raise InstallerError("backup root must be on same device as skills root parent")
    candidate = (
        parent / f"{tag}-{commit[:12]}-{int(time.time())}-{secrets.token_hex(3)}"
    )
    try:
        os.makedirs(candidate, mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        raise InstallerError(f"transaction backup collision: {candidate}") from exc
    return candidate


def _archive_stage_root(stage_root: Path, backup_root: Path) -> Path:
    """Confirm the exchange slot is already the final prior-root archive.

    The slot is created at this final pathname before the exchange.  A
    successful exchange therefore places the old loader root here atomically;
    no pathname rename is needed after post-install checks.
    """

    archived = backup_root / "skills-before-install"
    if stage_root != archived:
        raise InstallerError("exchange slot is not the final archive path")
    if not archived.is_dir() or archived.is_symlink():
        raise InstallerError("final archive path is not an ordinary directory")
    return archived


def _path_identity(path: Path) -> PathIdentity | None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return None
    return metadata.st_dev, metadata.st_ino


def _open_directory_identity(path: Path) -> tuple[int, PathIdentity]:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise InstallerError("opened staged root is not a directory")
        return fd, (metadata.st_dev, metadata.st_ino)
    except BaseException:
        os.close(fd)
        raise


def _stable_directory_path(fd: int) -> Path:
    path = Path("/proc/self/fd") / str(fd)
    if not path.exists():
        raise InstallerError("stable staged-root descriptor path is unavailable")
    return path


def _classify_transaction_paths(
    *,
    skills_root: Path,
    stage_root: Path,
    archived_root: Path,
    old_identity: PathIdentity,
    new_identity: PathIdentity,
) -> str:
    active = _path_identity(skills_root)
    staged = _path_identity(stage_root)
    if stage_root == archived_root:
        if active == old_identity and staged == new_identity:
            return "prepared"
        if active == new_identity and staged == old_identity:
            return "exchanged"
        return "ambiguous"
    archived = _path_identity(archived_root)
    if active == old_identity and staged == new_identity and archived is None:
        return "prepared"
    if active == new_identity and staged == old_identity and archived is None:
        return "exchanged"
    if active == new_identity and staged is None and archived == old_identity:
        return "committed"
    return "ambiguous"


def _identity_locator(
    identity: PathIdentity,
    candidates: Iterable[Path],
) -> Path | None:
    for candidate in candidates:
        if _path_identity(candidate) == identity:
            return candidate
    return None


def _recovery_locator_or_copy(
    identity: PathIdentity,
    candidates: Iterable[Path],
    *,
    directory_fd: int,
    backup_root: Path,
) -> Path:
    locator = _identity_locator(identity, candidates)
    if locator is not None:
        return locator
    recovery_copy = backup_root / "skills-recovery-copy"
    if recovery_copy.exists():
        raise InstallerError("recovery copy path already exists")
    shutil.copytree(
        _stable_directory_path(directory_fd),
        recovery_copy,
        symlinks=True,
        copy_function=shutil.copy2,
    )
    os.chmod(recovery_copy, 0o700)
    return recovery_copy


def _lock_path_for_active_root(skills_root: Path) -> Path:
    return skills_root.parent / f".{skills_root.name}.deep-research-install.lock"


@contextmanager
def _active_root_lock(skills_root: Path) -> Iterable[Path]:
    """Hold a stable sibling lock while the active-root pathname is exchanged."""

    lock_path = _lock_path_for_active_root(skills_root)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise InstallerError(
            f"could not open installer lock {lock_path}: {exc}"
        ) from exc

    acquired = False
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise InstallerError(f"installer lock is not a regular file: {lock_path}")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                raise InstallerError(f"installer lock is busy: {lock_path}") from exc
            raise InstallerError(
                f"could not acquire installer lock {lock_path}: {exc}"
            ) from exc
        acquired = True
        yield lock_path
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def _signal_guard() -> Iterable[None]:
    handlers: dict[int, object] = {}

    def _on_signal(signum: int, _frame: object) -> None:
        raise InstallerError(f"interrupted by signal {signum}")

    for sig in (signal.SIGINT, signal.SIGTERM):
        handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, _on_signal)
    try:
        yield
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def _validate_backups_and_roots(skills_root: Path, backup_root: Path) -> None:
    if backup_root.resolve().is_relative_to(skills_root.resolve()):
        raise InstallerError(f"backup must be outside skills root: {backup_root}")
    if backup_root.exists() and backup_root.is_symlink():
        raise InstallerError(f"backup root is symlink: {backup_root}")


def install_tagged_skills(
    *,
    tag: str,
    repo_root: Path,
    skills_root: Path,
    backup_root: Path,
    required_skills: tuple[str, ...] = DEFAULT_SKILLS,
    command_runner: CommandRunner = subprocess.run,
    codex_runner: CommandRunner = subprocess.run,
    codex_home: Path | None = None,
    exchange: Callable[[Path, Path], None] = _exchange_atomically,
    archive: Callable[[Path, Path], Path] = _archive_stage_root,
    phase_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    phase_hook = phase_hook or (lambda _step: None)

    _validate_existing_ancestor_no_symlink(repo_root)
    _validate_existing_ancestor_no_symlink(skills_root)
    _validate_existing_ancestor_no_symlink(backup_root)

    repo_root = repo_root.resolve()
    skills_root = skills_root.resolve()
    backup_root = backup_root.resolve()

    if not repo_root.joinpath(".git").is_dir():
        raise InstallerError(f"repo_root is not a git repository: {repo_root}")

    if not skills_root.exists():
        raise InstallerError(f"skills root does not exist: {skills_root}")
    if not skills_root.is_dir():
        raise InstallerError(f"skills root is not a directory: {skills_root}")
    if skills_root.is_symlink():
        raise InstallerError(f"skills root is symlink: {skills_root}")

    _validate_backups_and_roots(skills_root, backup_root)
    codex_home = (codex_home or skills_root.parent).resolve()

    # The sibling lock pathname does not move when the active root and the
    # transaction backup's final exchange slot are swapped. Hold it across
    # every preflight, staging, validation, commit decision, and rollback.
    with _active_root_lock(skills_root), _signal_guard():
        skills_source_root = repo_root / "skills"
        if not skills_source_root.is_dir():
            raise InstallerError(f"repo missing skills directory: {skills_source_root}")

        for skill in required_skills:
            source_skill = skills_source_root / skill
            if not source_skill.exists():
                raise InstallerError(
                    f"required skill missing in source tree: {source_skill}"
                )
            if source_skill.is_symlink():
                raise InstallerError(
                    f"required skill is symlink in source: {source_skill}"
                )

        _ensure_clean_repo(repo_root, command_runner)
        _verify_clean_tag_tree(repo_root, required_skills, command_runner)
        tag_object, tag_commit = _verify_annotated_tag(repo_root, tag, command_runner)
        _verify_remote_refs(repo_root, tag, tag_object, tag_commit, command_runner)

        transaction_backup_root = _make_backup_root(
            backup_root,
            tag,
            tag_commit,
            skills_parent=skills_root.parent,
        )
        os.chmod(transaction_backup_root, 0o700)
        stage_root = transaction_backup_root / "skills-before-install"
        archived_root = stage_root
        source_snapshot_root = transaction_backup_root / "tag-snapshot"
        source_snapshot_fd: int | None = None
        source_snapshot_identity: PathIdentity | None = None
        old_identity: PathIdentity | None = None
        new_identity: PathIdentity | None = None
        source_manifest: dict[str, ManifestEntry] = {}
        installed_manifest: dict[str, ManifestEntry] = {}
        stage_root_identity: PathIdentity | None = None
        stage_root_fd: int | None = None
        old_root_fd: int | None = None
        commit_decided = False
        result: dict[str, object] | None = None

        try:
            (
                source_snapshot_root,
                source_snapshot_fd,
                source_snapshot_identity,
                expected_source_manifest,
            ) = _materialize_skill_snapshot(
                repo_root,
                tag_commit,
                required_skills,
                command_runner,
                source_snapshot_root,
            )
            stable_source_snapshot = _stable_directory_path(source_snapshot_fd)
            phase_hook("pre_stage")
            source_manifest = _compute_manifest(
                stable_source_snapshot / "skills", required_skills
            )
            if _manifest_to_bytes(source_manifest) != _manifest_to_bytes(
                expected_source_manifest
            ):
                raise InstallerError("tag snapshot manifest changed after extraction")
            phase_hook("stage")
            old_root_fd, old_identity = _open_directory_identity(skills_root)
            stage_root_fd, stage_root_identity = _copy_loader_root(
                _stable_directory_path(old_root_fd), stage_root
            )
            old_root_metadata = os.fstat(old_root_fd)
            os.fchmod(stage_root_fd, stat.S_IMODE(old_root_metadata.st_mode))
            new_identity = stage_root_identity
            if old_identity is None or new_identity is None:
                raise InstallerError(
                    "could not record active and staged root identities"
                )
            if old_identity == new_identity:
                raise InstallerError(
                    "active and staged roots unexpectedly share an identity"
                )
            if _path_identity(skills_root) != old_identity:
                raise InstallerError(
                    "active root pathname changed while preparing the staged copy"
                )

            phase_hook("skills_replace")
            state = _classify_transaction_paths(
                skills_root=skills_root,
                stage_root=stage_root,
                archived_root=archived_root,
                old_identity=old_identity,
                new_identity=new_identity,
            )
            if state != "prepared":
                raise InstallerError(
                    "transaction paths changed before staged skill replacement"
                )
            _replace_target_skills(
                stable_source_snapshot,
                _stable_directory_path(stage_root_fd),
                required_skills,
            )
            _write_json(
                transaction_backup_root / "tag-verification.json",
                {
                    "tag": tag,
                    "tag_object": tag_object,
                    "tag_commit": tag_commit,
                    "required_skills": list(required_skills),
                },
            )

            phase_hook("before_exchange")
            state = _classify_transaction_paths(
                skills_root=skills_root,
                stage_root=stage_root,
                archived_root=archived_root,
                old_identity=old_identity,
                new_identity=new_identity,
            )
            if state != "prepared":
                raise InstallerError("transaction paths changed before atomic exchange")
            exchange_result = _exchange_verified_identities(
                skills_root,
                stage_root,
                identity_a=old_identity,
                identity_b=new_identity,
                exchange=exchange,
            )
            if exchange_result != "exchanged":
                raise InstallerError("transaction paths changed before atomic exchange")
            state = _classify_transaction_paths(
                skills_root=skills_root,
                stage_root=stage_root,
                archived_root=archived_root,
                old_identity=old_identity,
                new_identity=new_identity,
            )
            if state != "exchanged":
                raise InstallerError(
                    f"atomic exchange returned in unexpected state: {state}"
                )
            phase_hook("after_exchange")

            installed_manifest = _compute_manifest(skills_root, required_skills)
            if _manifest_to_bytes(installed_manifest) != _manifest_to_bytes(
                source_manifest
            ):
                raise InstallerError(
                    "installed manifest does not match source manifest"
                )

            locator_paths, doctor_payload = _verify_codex_loader(
                skills_root,
                required_skills,
                runner=codex_runner,
                codex_home=codex_home,
            )

            _write_manifest(
                transaction_backup_root / "source-manifest.json", source_manifest
            )
            _write_manifest(
                transaction_backup_root / "installed-manifest.json", installed_manifest
            )
            _write_json(
                transaction_backup_root / "codex-loaders.json",
                {
                    "loader": {
                        "status": "ok",
                        "skill_count": len(required_skills),
                        "skill_names": sorted(required_skills),
                        "locator_set_sha256": hashlib.sha256(
                            json.dumps(locator_paths, separators=(",", ":")).encode(
                                "utf-8"
                            )
                        ).hexdigest(),
                    },
                    "doctor": doctor_payload,
                },
            )

            phase_hook("before_archive")
            if _path_identity(stage_root) != old_identity:
                raise InstallerError("staged old-root identity changed before archive")
            returned_archive_root = archive(stage_root, transaction_backup_root)
            state = _classify_transaction_paths(
                skills_root=skills_root,
                stage_root=stage_root,
                archived_root=archived_root,
                old_identity=old_identity,
                new_identity=new_identity,
            )
            if state != "exchanged":
                raise InstallerError(f"archive returned in unexpected state: {state}")
            if Path(returned_archive_root) != archived_root:
                raise InstallerError(
                    f"archive returned unexpected recovery locator: {returned_archive_root}"
                )
            if _path_identity(archived_root) != old_identity:
                raise InstallerError("archived old-root identity changed after archive")
            if (
                source_snapshot_identity is None
                or _path_identity(source_snapshot_root) != source_snapshot_identity
            ):
                raise InstallerError("tag snapshot pathname identity changed")
            if _manifest_to_bytes(
                _compute_manifest(stable_source_snapshot / "skills", required_skills)
            ) != _manifest_to_bytes(expected_source_manifest):
                raise InstallerError("tag snapshot manifest changed before commit")
            if _manifest_to_bytes(
                _compute_manifest(skills_root, required_skills)
            ) != _manifest_to_bytes(expected_source_manifest):
                raise InstallerError("installed manifest changed before commit")
            _write_json(
                transaction_backup_root / "archive-status.json",
                {"archived_root": str(archived_root)},
            )

            commit_decided = True

            result = {
                "tag": tag,
                "tag_object": tag_object,
                "tag_commit": tag_commit,
                "installed_manifest": {
                    k: v.__dict__ for k, v in installed_manifest.items()
                },
                "backup_root": transaction_backup_root,
            }
        except BaseException as install_error:
            if (
                transaction_backup_root is not None
                and old_identity is not None
                and new_identity is not None
            ):
                archived_root = transaction_backup_root / "skills-before-install"
                if commit_decided:
                    message = (
                        "install committed but finalization failed; "
                        f"recovery_root={archived_root}"
                    )
                    raise InstallerError(
                        message, recovery_root=archived_root
                    ) from install_error
                state = _classify_transaction_paths(
                    skills_root=skills_root,
                    stage_root=stage_root,
                    archived_root=archived_root,
                    old_identity=old_identity,
                    new_identity=new_identity,
                )

                if state == "exchanged":
                    rollback_error: BaseException | None = None
                    try:
                        rollback_result = _exchange_verified_identities(
                            skills_root,
                            stage_root,
                            identity_a=new_identity,
                            identity_b=old_identity,
                            exchange=exchange,
                        )
                        if rollback_result != "exchanged":
                            rollback_error = InstallerError(
                                "rollback path identities changed"
                            )
                    except BaseException as exc:
                        rollback_error = exc
                    state = _classify_transaction_paths(
                        skills_root=skills_root,
                        stage_root=stage_root,
                        archived_root=archived_root,
                        old_identity=old_identity,
                        new_identity=new_identity,
                    )
                    if state == "exchanged":
                        recovery_root = _recovery_locator_or_copy(
                            old_identity,
                            (stage_root, archived_root),
                            directory_fd=old_root_fd,
                            backup_root=transaction_backup_root,
                        )
                        message = "install failed and rollback failed"
                        if recovery_root is not None:
                            message += f"; recovery_root={recovery_root}"
                        raise InstallerError(
                            message, recovery_root=recovery_root
                        ) from (rollback_error or install_error)
                    if state != "prepared":
                        recovery_root = _recovery_locator_or_copy(
                            old_identity,
                            (stage_root, archived_root, skills_root),
                            directory_fd=old_root_fd,
                            backup_root=transaction_backup_root,
                        )
                        message = f"install rollback left ambiguous state: {state}"
                        if recovery_root is not None:
                            message += f"; recovery_root={recovery_root}"
                        raise InstallerError(
                            message, recovery_root=recovery_root
                        ) from (rollback_error or install_error)

                if state == "prepared":
                    # The failed new tree stays in the unique transaction
                    # backup. Avoid any post-check/delete race against a
                    # replacement pathname.
                    raise

                if state == "ambiguous" and _path_identity(stage_root) == old_identity:
                    rollback_error: BaseException | None = None
                    try:
                        rollback_result = _exchange_verified_identities(
                            skills_root,
                            stage_root,
                            identity_a=new_identity,
                            identity_b=old_identity,
                            exchange=exchange,
                        )
                        if rollback_result != "exchanged":
                            rollback_error = InstallerError(
                                "rollback path identities changed"
                            )
                    except BaseException as exc:
                        rollback_error = exc
                    if _path_identity(skills_root) == old_identity:
                        raise InstallerError(
                            "atomic exchange rejected a changed staged-root identity"
                        ) from install_error
                    recovery_root = _recovery_locator_or_copy(
                        old_identity,
                        (stage_root, archived_root, skills_root),
                        directory_fd=old_root_fd,
                        backup_root=transaction_backup_root,
                    )
                    message = "changed-stage exchange could not restore original root"
                    if recovery_root is not None:
                        message += f"; recovery_root={recovery_root}"
                    raise InstallerError(message, recovery_root=recovery_root) from (
                        rollback_error or install_error
                    )

                recovery_root = _recovery_locator_or_copy(
                    old_identity,
                    (stage_root, archived_root, skills_root),
                    directory_fd=old_root_fd,
                    backup_root=transaction_backup_root,
                )
                message = f"install failed with ambiguous transaction state: {state}"
                if recovery_root is not None:
                    message += f"; recovery_root={recovery_root}"
                raise InstallerError(
                    message, recovery_root=recovery_root
                ) from install_error

                # Failure before identity capture or after a successful
                # rollback leaves all transaction artifacts in the unique
                # mode-0700 backup. No pathname is recursively deleted.
            raise
        finally:
            if source_snapshot_fd is not None:
                os.close(source_snapshot_fd)
                source_snapshot_fd = None
            if stage_root_fd is not None:
                os.close(stage_root_fd)
                stage_root_fd = None
            if old_root_fd is not None:
                os.close(old_root_fd)
                old_root_fd = None

        if result is None:
            raise RuntimeError("installer did not complete")
        return result


def parse_args() -> argparse.Namespace:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser = argparse.ArgumentParser(
        description="Install an annotated-tag skill set using atomic root exchange."
    )
    parser.add_argument("--tag", required=True, help="annotated git tag to install")
    parser.add_argument(
        "--repo",
        default=str(Path(__file__).resolve().parent.parent),
        help="repository path",
    )
    parser.add_argument(
        "--skills-root",
        default=str(codex_home / "skills"),
        help="local loader root",
    )
    parser.add_argument(
        "--backup-root",
        default=str(codex_home / "skill-backups"),
        help="backup parent directory outside loader root",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = install_tagged_skills(
        tag=args.tag,
        repo_root=Path(args.repo),
        skills_root=Path(args.skills_root),
        backup_root=Path(args.backup_root),
    )
    print(
        json.dumps(
            {
                "tag": result["tag"],
                "tag_object": result["tag_object"],
                "backup_root": str(result["backup_root"]),
                "installed_entry_count": len(result["installed_manifest"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
