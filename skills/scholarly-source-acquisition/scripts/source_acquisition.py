#!/usr/bin/env python3
"""Safely acquire one explicit public scholarly PDF with an auditable result."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import queue
import re
import socket
import ssl
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit
from urllib.request import (
    HTTPHandler,
    HTTPSHandler,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)


RESULT_SCHEMA = "AcquisitionResult/v1"
CANDIDATE_SCHEMA = "AcquisitionCandidate/v1"
PRODUCER = "scholarly-source-acquisition"
PROTOCOL_VERSION = "1.0"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
HARD_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0
HARD_MAX_TIMEOUT = 120.0
DEFAULT_REDIRECT_LIMIT = 3
HARD_MAX_REDIRECT_LIMIT = 5
DEFAULT_CLEANUP_GRACE_SECONDS = 0.25
CHUNK_SIZE = 64 * 1024
PDF_MAGIC = b"%PDF-"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
IDENTIFIER_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
MIME_RE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

SOURCE_ACCESS_PAIRS = {
    "open_repository": "declared_open_access",
    "institutional_repository": "institutional_public_copy",
    "author_copy": "author_provided",
    "preprint_server": "preprint_public_copy",
    "publisher_open": "publisher_open_access",
}
DISCOVERY_SCHEMAS = {
    "ScholarDiscoveryResult/v1",
    "ScholarDiscoveryResultSet/v1",
    "ManualScholarExport/v1",
}
SENSITIVE_QUERY_FRAGMENTS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "cookie",
    "credential",
    "jwt",
    "key",
    "passwd",
    "password",
    "session",
    "sig",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
    "x-goog-credential",
    "x-goog-signature",
}
CHECK_NAMES = [
    "candidate_contract",
    "url_policy",
    "transport_policy",
    "destination_exclusive",
    "public_dns",
    "http_response",
    "content_type",
    "pdf_magic",
    "size_limit",
    "sha256",
    "artifact_publish",
]
CANDIDATE_KEYS = {
    "schema",
    "candidate_id",
    "title",
    "authors",
    "year",
    "rank",
    "identifiers",
    "discovery_ref",
    "locator",
}
LOCATOR_KEYS = {"url", "source_type", "access_basis"}
DISCOVERY_REF_KEYS = {"schema", "artifact_sha256", "candidate_id"}
RESULT_KEYS = {
    "schema",
    "schema_version",
    "producer",
    "protocol_version",
    "operation",
    "status",
    "generated_at",
    "candidate",
    "candidate_digest",
    "request",
    "http",
    "checks",
    "artifact",
    "handoff",
    "failures",
    "result_id",
    "result_digest",
}
REQUEST_KEYS = {
    "requested_url",
    "query_removed",
    "source_type",
    "access_basis",
    "destination",
    "request_profile",
    "transport_profile",
    "proxy_url",
    "max_bytes",
    "timeout_seconds",
    "redirect_limit",
}
HTTP_KEYS = {
    "attempted",
    "status_code",
    "content_type",
    "final_url",
    "redirects",
    "bytes_received",
}
CHECK_KEYS = {"name", "status", "detail"}
ARTIFACT_KEYS = {
    "path",
    "media_type",
    "size_bytes",
    "sha256",
    "pdf_magic_verified",
    "content_type_verified",
}
HANDOFF_KEYS = {
    "target_schema",
    "source_path",
    "source_sha256",
    "builder_contract",
    "recommended_argv",
}
FAILURE_KEYS = {"code", "stage", "message", "retryable"}


class ContractError(ValueError):
    """A closed-contract validation failure."""


class AcquisitionError(RuntimeError):
    """A controlled acquisition failure safe to persist in a manifest."""

    def __init__(self, code: str, stage: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.safe_message = message
        self.retryable = retryable


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _remaining_seconds(deadline: float, clock: Any, stage: str) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise AcquisitionError(
            "fetch_deadline_exceeded",
            stage,
            "The total scholarly PDF fetch deadline was exceeded",
            True,
        )
    return remaining


def _run_with_deadline(
    action: Any,
    *,
    deadline: float,
    clock: Any,
    stage: str,
    late_cleanup: Any = None,
) -> Any:
    """Run one blocking platform call without letting it exceed the fetch budget."""
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
    abandoned = threading.Event()

    def worker() -> None:
        try:
            item = (True, action())
        except Exception as error:
            item = (False, error)
        if abandoned.is_set():
            if item[0] and late_cleanup is not None:
                try:
                    late_cleanup(item[1])
                except Exception:
                    pass
            return
        try:
            result_queue.put_nowait(item)
        except queue.Full:
            if item[0] and late_cleanup is not None:
                try:
                    late_cleanup(item[1])
                except Exception:
                    pass

    _remaining_seconds(deadline, clock, stage)
    thread = threading.Thread(target=worker, name="scholarly-acquisition-blocking-call", daemon=True)
    thread.start()
    try:
        item = result_queue.get(timeout=_remaining_seconds(deadline, clock, stage))
    except queue.Empty as error:
        abandoned.set()
        try:
            late_item = result_queue.get_nowait()
        except queue.Empty:
            late_item = None
        if late_item is not None and late_item[0] and late_cleanup is not None:
            try:
                late_cleanup(late_item[1])
            except Exception:
                pass
        raise AcquisitionError(
            "fetch_deadline_exceeded",
            stage,
            "The total scholarly PDF fetch deadline was exceeded",
            True,
        ) from error
    try:
        _remaining_seconds(deadline, clock, stage)
    except AcquisitionError:
        abandoned.set()
        if item[0] and late_cleanup is not None:
            try:
                late_cleanup(item[1])
            except Exception:
                pass
        raise
    if not item[0]:
        raise item[1]
    return item[1]


def _abort_response_io(response: Any, *, grace_seconds: float = DEFAULT_CLEANUP_GRACE_SECONDS) -> None:
    """Best-effort non-blocking cancellation for an HTTP response being read elsewhere."""
    frontier = [response]
    visited: set[int] = set()
    sockets: list[socket.socket] = []
    for _depth in range(6):
        next_frontier: list[Any] = []
        for value in frontier:
            if value is None or id(value) in visited:
                continue
            visited.add(id(value))
            if isinstance(value, socket.socket):
                sockets.append(value)
                continue
            for attribute in ("fp", "raw", "_sock", "sock", "socket", "_connection"):
                try:
                    child = getattr(value, attribute, None)
                except Exception:
                    child = None
                if child is not None:
                    next_frontier.append(child)
        frontier = next_frontier

    for network_socket in sockets:
        try:
            network_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            network_socket.close()
        except OSError:
            pass

    close_finished = threading.Event()

    def close_response() -> None:
        try:
            response.close()
        except Exception:
            pass
        finally:
            close_finished.set()

    closer = threading.Thread(
        target=close_response, name="scholarly-acquisition-response-close", daemon=True
    )
    closer.start()
    close_finished.wait(timeout=max(0.0, grace_seconds))


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown or missing:
        raise ContractError(f"{label} keys mismatch; missing={missing}, unknown={unknown}")


def require_string(value: Any, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ContractError(f"{label} must be a non-empty string up to {maximum} characters")
    if any(ord(character) < 32 for character in value):
        raise ContractError(f"{label} cannot contain control characters")
    return value.strip()


def validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ContractError("generated_at must be canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ContractError("generated_at is not a valid UTC timestamp") from error
    return value


def _sensitive_query_key(key: str) -> bool:
    normalized = key.casefold().replace(".", "_").replace("-", "_")
    return any(
        normalized == fragment.replace("-", "_")
        or normalized.startswith(fragment.replace("-", "_") + "_")
        for fragment in SENSITIVE_QUERY_FRAGMENTS
    )


def _url_parts(url: Any) -> tuple[Any, str]:
    text = require_string(url, "locator.url", maximum=4096)
    if any(character.isspace() for character in text):
        raise AcquisitionError("invalid_url", "url_policy", "URL whitespace is not allowed")
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as error:
        raise AcquisitionError("invalid_url", "url_policy", "URL syntax is invalid") from error
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise AcquisitionError("invalid_url", "url_policy", "Only HTTP(S) URLs are accepted")
    if parsed.username is not None or parsed.password is not None:
        raise AcquisitionError("authorization_data_rejected", "url_policy", "URL authorization data is not accepted")
    if parsed.fragment:
        raise AcquisitionError("invalid_url", "url_policy", "URL fragments are not accepted")
    host = (parsed.hostname or "").casefold().rstrip(".")
    if not host or "." not in host:
        raise AcquisitionError("invalid_url", "url_policy", "A public fully qualified host is required")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise AcquisitionError("ip_literal_rejected", "url_policy", "IP-literal URLs are not accepted")
    expected_port = 80 if scheme == "http" else 443
    if port not in {None, expected_port}:
        raise AcquisitionError("non_default_port_rejected", "url_policy", "Only the default HTTP(S) port is accepted")
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if _sensitive_query_key(key):
            raise AcquisitionError("authorization_data_rejected", "url_policy", "Credential-like URL query data is not accepted")
    netloc = host
    path = parsed.path or "/"
    sanitized = urlunsplit((scheme, netloc, path, "", ""))
    return parsed, sanitized


def sanitize_url(url: Any) -> str:
    _parsed, sanitized = _url_parts(url)
    return sanitized


def normalize_transport(transport_profile: Any, proxy_url: Any) -> tuple[str, str | None]:
    if transport_profile not in {"direct", "loopback-proxy"}:
        raise AcquisitionError(
            "transport_profile_rejected",
            "transport_policy",
            "Transport profile must be direct or loopback-proxy",
        )
    if transport_profile == "direct":
        if proxy_url is not None:
            raise AcquisitionError(
                "proxy_not_allowed",
                "transport_policy",
                "Direct transport does not accept a proxy URL",
            )
        return "direct", None
    if not isinstance(proxy_url, str) or not proxy_url or len(proxy_url) > 512:
        raise AcquisitionError(
            "proxy_url_required",
            "transport_policy",
            "Loopback proxy transport requires an explicit HTTP proxy URL",
        )
    if any(character.isspace() or ord(character) < 32 for character in proxy_url):
        raise AcquisitionError(
            "proxy_url_rejected", "transport_policy", "Proxy URL syntax is invalid"
        )
    try:
        parsed = urlsplit(proxy_url)
        port = parsed.port
    except ValueError as error:
        raise AcquisitionError(
            "proxy_url_rejected", "transport_policy", "Proxy URL syntax is invalid"
        ) from error
    if parsed.scheme.casefold() != "http":
        raise AcquisitionError(
            "proxy_url_rejected", "transport_policy", "Only an HTTP loopback proxy is accepted"
        )
    if parsed.username is not None or parsed.password is not None:
        raise AcquisitionError(
            "proxy_authorization_rejected",
            "transport_policy",
            "Proxy authorization data is not accepted",
        )
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise AcquisitionError(
            "proxy_url_rejected",
            "transport_policy",
            "Proxy URL cannot contain query, fragment, or a non-root path",
        )
    host = parsed.hostname
    if host is None or port is None or port < 1:
        raise AcquisitionError(
            "proxy_url_rejected",
            "transport_policy",
            "Proxy URL requires a loopback IP literal and explicit port",
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise AcquisitionError(
            "proxy_host_rejected",
            "transport_policy",
            "Proxy host must be a loopback IP literal",
        ) from error
    if not address.is_loopback:
        raise AcquisitionError(
            "proxy_host_rejected", "transport_policy", "Proxy host must be loopback"
        )
    canonical_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return "loopback-proxy", f"http://{canonical_host}:{port}"


class _LoopbackProxyHandler(ProxyHandler):
    """Explicit proxy handler that never consults environment NO_PROXY rules."""

    def proxy_open(self, req: Request, proxy: str, request_type: str) -> Any:
        parsed = urlsplit(proxy)
        proxy_type = parsed.scheme
        host_port = parsed.netloc
        original_type = req.type
        req.set_proxy(host_port, proxy_type)
        if original_type == proxy_type:
            return None
        return self.parent.open(req, timeout=req.timeout)


def _proxy_handler(transport_profile: str, proxy_url: str | None) -> ProxyHandler:
    profile, canonical_proxy = normalize_transport(transport_profile, proxy_url)
    if profile == "direct":
        return ProxyHandler({})
    return _LoopbackProxyHandler({"http": canonical_proxy, "https": canonical_proxy})


def _assert_public_hostname(url: str, *, deadline: float, clock: Any) -> None:
    parsed, _sanitized = _url_parts(url)
    host = parsed.hostname
    try:
        answers = _run_with_deadline(
            lambda: socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM),
            deadline=deadline,
            clock=clock,
            stage="public_dns",
        )
    except OSError as error:
        raise AcquisitionError(
            "dns_resolution_failed", "public_dns", "The scholarly host could not be resolved", True
        ) from error
    _remaining_seconds(deadline, clock, "public_dns")
    addresses = {answer[4][0] for answer in answers if answer[4]}
    if not addresses:
        raise AcquisitionError(
            "dns_resolution_failed", "public_dns", "The scholarly host returned no addresses", True
        )
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as error:
            raise AcquisitionError("dns_policy_rejected", "public_dns", "The host returned an invalid address") from error
        if not parsed_address.is_global:
            raise AcquisitionError(
                "dns_policy_rejected", "public_dns", "The scholarly host must resolve only to public addresses"
            )


def normalize_candidate(raw: Any, *, preserve_request_url: bool = True) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ContractError("candidate must be a JSON object")
    unknown = sorted(set(raw) - CANDIDATE_KEYS)
    required = {"schema", "candidate_id", "title", "locator"}
    missing = sorted(required - set(raw))
    if unknown or missing:
        raise ContractError(f"candidate keys mismatch; missing={missing}, unknown={unknown}")
    if raw.get("schema") != CANDIDATE_SCHEMA:
        raise ContractError(f"candidate.schema must be {CANDIDATE_SCHEMA}")
    candidate_id = require_string(raw.get("candidate_id"), "candidate.candidate_id", maximum=128)
    if not ID_RE.fullmatch(candidate_id):
        raise ContractError("candidate.candidate_id has invalid format")
    title = require_string(raw.get("title"), "candidate.title", maximum=1000)

    authors = raw.get("authors", [])
    if not isinstance(authors, list) or len(authors) > 100:
        raise ContractError("candidate.authors must be a list of at most 100 strings")
    normalized_authors = [
        require_string(author, f"candidate.authors[{index}]", maximum=300)
        for index, author in enumerate(authors)
    ]
    year = raw.get("year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool) or not 1000 <= year <= 3000):
        raise ContractError("candidate.year must be null or an integer from 1000 through 3000")
    rank = raw.get("rank")
    if rank is not None and (not isinstance(rank, int) or isinstance(rank, bool) or rank < 1):
        raise ContractError("candidate.rank must be null or a positive integer")

    identifiers = raw.get("identifiers", {})
    if not isinstance(identifiers, dict) or len(identifiers) > 32:
        raise ContractError("candidate.identifiers must be an object with at most 32 entries")
    normalized_identifiers: dict[str, str] = {}
    for key, value in sorted(identifiers.items()):
        if not isinstance(key, str) or not IDENTIFIER_KEY_RE.fullmatch(key):
            raise ContractError("candidate identifier keys have invalid format")
        if _sensitive_query_key(key):
            raise ContractError("candidate identifiers cannot contain authorization material")
        normalized_identifiers[key.casefold()] = require_string(
            value, f"candidate.identifiers.{key}", maximum=1024
        )

    discovery_ref = raw.get("discovery_ref")
    normalized_discovery_ref = None
    if discovery_ref is not None:
        if not isinstance(discovery_ref, dict):
            raise ContractError("candidate.discovery_ref must be null or an object")
        require_exact_keys(discovery_ref, DISCOVERY_REF_KEYS, "candidate.discovery_ref")
        if discovery_ref.get("schema") not in DISCOVERY_SCHEMAS:
            raise ContractError("candidate.discovery_ref.schema is unsupported")
        digest = discovery_ref.get("artifact_sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ContractError("candidate.discovery_ref.artifact_sha256 must be lowercase SHA-256")
        if discovery_ref.get("candidate_id") != candidate_id:
            raise ContractError("candidate.discovery_ref.candidate_id must match candidate_id")
        normalized_discovery_ref = {
            "schema": discovery_ref["schema"],
            "artifact_sha256": digest,
            "candidate_id": candidate_id,
        }

    locator = raw.get("locator")
    if not isinstance(locator, dict):
        raise ContractError("candidate.locator must be an object")
    require_exact_keys(locator, LOCATOR_KEYS, "candidate.locator")
    source_type = locator.get("source_type")
    access_basis = locator.get("access_basis")
    if source_type not in SOURCE_ACCESS_PAIRS:
        raise ContractError("candidate.locator.source_type is unsupported")
    if access_basis != SOURCE_ACCESS_PAIRS[source_type]:
        raise ContractError("candidate locator source_type/access_basis pair is inconsistent")
    parsed, sanitized = _url_parts(locator.get("url"))
    request_url = parsed.geturl() if preserve_request_url else sanitized

    return {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": candidate_id,
        "title": title,
        "authors": normalized_authors,
        "year": year,
        "rank": rank,
        "identifiers": normalized_identifiers,
        "discovery_ref": normalized_discovery_ref,
        "locator": {
            "url": request_url,
            "source_type": source_type,
            "access_basis": access_basis,
        },
    }


def candidate_for_manifest(candidate: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(candidate))
    result["locator"]["url"] = sanitize_url(candidate["locator"]["url"])
    return result


def _absolute_path(path: str) -> Path:
    return Path(path).expanduser().absolute()


def _assert_non_symlink_components(path: Path, label: str) -> None:
    absolute = _absolute_path(str(path))
    chain = list(reversed(absolute.parents)) + [absolute]
    for component in chain:
        if os.path.lexists(component) and component.is_symlink():
            raise AcquisitionError("unsafe_path", "destination_exclusive", f"{label} cannot contain symlink components")


def _preflight_destination(destination: str, *, result_path: str | None = None) -> Path:
    path = _absolute_path(destination)
    if result_path is not None and path == _absolute_path(result_path):
        raise AcquisitionError("path_collision", "destination_exclusive", "Destination and result paths must differ")
    _assert_non_symlink_components(path.parent, "Destination parent")
    if not path.parent.is_dir():
        raise AcquisitionError("unsafe_path", "destination_exclusive", "Destination parent must already exist")
    if os.path.lexists(path):
        raise AcquisitionError("destination_exists", "destination_exclusive", "Destination already exists")
    return path


def _validate_limits(max_bytes: int, timeout_seconds: float, redirect_limit: int) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= HARD_MAX_BYTES:
        raise ContractError(f"max_bytes must be an integer from 1 through {HARD_MAX_BYTES}")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= HARD_MAX_TIMEOUT:
        raise ContractError(f"timeout_seconds must be greater than zero and at most {HARD_MAX_TIMEOUT}")
    if isinstance(redirect_limit, bool) or not isinstance(redirect_limit, int) or not 0 <= redirect_limit <= HARD_MAX_REDIRECT_LIMIT:
        raise ContractError(f"redirect_limit must be an integer from 0 through {HARD_MAX_REDIRECT_LIMIT}")


def _base_checks() -> list[dict[str, Any]]:
    return [{"name": name, "status": "not_run", "detail": None} for name in CHECK_NAMES]


def _set_check(checks: list[dict[str, Any]], name: str, status: str, detail: str | None = None) -> None:
    for check in checks:
        if check["name"] == name:
            check["status"] = status
            check["detail"] = detail
            return
    raise AssertionError(f"unknown check: {name}")


def _http_record() -> dict[str, Any]:
    return {
        "attempted": False,
        "status_code": None,
        "content_type": None,
        "final_url": None,
        "redirects": [],
        "bytes_received": 0,
    }


def _request_record(
    candidate: dict[str, Any],
    destination: Path,
    max_bytes: int,
    timeout_seconds: float,
    redirect_limit: int,
    transport_profile: str,
    proxy_url: str | None,
) -> dict[str, Any]:
    raw_url = candidate["locator"]["url"]
    parsed, sanitized = _url_parts(raw_url)
    return {
        "requested_url": sanitized,
        "query_removed": bool(parsed.query),
        "source_type": candidate["locator"]["source_type"],
        "access_basis": candidate["locator"]["access_basis"],
        "destination": str(destination),
        "request_profile": "anonymous-pdf",
        "transport_profile": transport_profile,
        "proxy_url": proxy_url,
        "max_bytes": max_bytes,
        "timeout_seconds": float(timeout_seconds),
        "redirect_limit": redirect_limit,
    }


def _failure(error: AcquisitionError) -> dict[str, Any]:
    return {
        "code": error.code,
        "stage": error.stage,
        "message": error.safe_message,
        "retryable": error.retryable,
    }


def _finish_result(payload: dict[str, Any]) -> dict[str, Any]:
    digest_payload = dict(payload)
    digest = sha256_json(digest_payload)
    result = dict(payload)
    result["result_id"] = f"acquisition-result-{digest[:16]}"
    result["result_digest"] = digest
    validate_result(result, verify_artifact=False)
    return result


def _result_payload(
    *,
    operation: str,
    status: str,
    generated_at: str,
    candidate: dict[str, Any] | None,
    request: dict[str, Any] | None,
    http: dict[str, Any],
    checks: list[dict[str, Any]],
    artifact: dict[str, Any] | None,
    handoff: dict[str, Any] | None,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest_candidate = candidate_for_manifest(candidate) if candidate is not None else None
    return {
        "schema": RESULT_SCHEMA,
        "schema_version": "v1",
        "producer": PRODUCER,
        "protocol_version": PROTOCOL_VERSION,
        "operation": operation,
        "status": status,
        "generated_at": validate_timestamp(generated_at),
        "candidate": manifest_candidate,
        "candidate_digest": sha256_json(manifest_candidate) if manifest_candidate is not None else None,
        "request": request,
        "http": http,
        "checks": checks,
        "artifact": artifact,
        "handoff": handoff,
        "failures": failures,
    }


def _input_failure_result(operation: str, generated_at: str, message: str) -> dict[str, Any]:
    checks = _base_checks()
    _set_check(checks, "candidate_contract", "failed", "Candidate input is invalid")
    error = AcquisitionError("invalid_candidate", "candidate_contract", message)
    return _finish_result(
        _result_payload(
            operation=operation,
            status="failed",
            generated_at=generated_at,
            candidate=None,
            request=None,
            http=_http_record(),
            checks=checks,
            artifact=None,
            handoff=None,
            failures=[_failure(error)],
        )
    )


def plan_candidate(
    raw_candidate: Any,
    destination: str,
    *,
    generated_at: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    redirect_limit: int = DEFAULT_REDIRECT_LIMIT,
    transport_profile: str = "direct",
    proxy_url: str | None = None,
    result_path: str | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or utc_now()
    validate_timestamp(timestamp)
    checks = _base_checks()
    http = _http_record()
    try:
        _validate_limits(max_bytes, timeout_seconds, redirect_limit)
        candidate = normalize_candidate(raw_candidate)
        _set_check(checks, "candidate_contract", "passed")
        _set_check(checks, "url_policy", "passed")
        normalized_profile, normalized_proxy = normalize_transport(transport_profile, proxy_url)
        _set_check(checks, "transport_policy", "passed")
        destination_path = _absolute_path(destination)
        request = _request_record(
            candidate,
            destination_path,
            max_bytes,
            timeout_seconds,
            redirect_limit,
            normalized_profile,
            normalized_proxy,
        )
        destination_path = _preflight_destination(destination, result_path=result_path)
        _set_check(checks, "destination_exclusive", "passed")
    except ContractError:
        return _input_failure_result("plan", timestamp, "Candidate input or limits are invalid")
    except AcquisitionError as error:
        _set_check(checks, error.stage, "failed", error.safe_message)
        candidate_value = locals().get("candidate")
        request_value = locals().get("request")
        return _finish_result(
            _result_payload(
                operation="plan",
                status="failed",
                generated_at=timestamp,
                candidate=candidate_value,
                request=request_value,
                http=http,
                checks=checks,
                artifact=None,
                handoff=None,
                failures=[_failure(error)],
            )
        )
    return _finish_result(
        _result_payload(
            operation="plan",
            status="planned",
            generated_at=timestamp,
            candidate=candidate,
            request=request,
            http=http,
            checks=checks,
            artifact=None,
            handoff=None,
            failures=[],
        )
    )


class _BoundedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, limit: int, deadline: float, clock: Any):
        super().__init__()
        self.limit = limit
        self.deadline = deadline
        self.clock = clock
        self.redirects: list[str] = []

    def redirect_request(self, req: Request, fp: BinaryIO, code: int, msg: str, headers: Any, newurl: str) -> Request | None:
        _remaining_seconds(self.deadline, self.clock, "http_response")
        if len(self.redirects) >= self.limit:
            raise AcquisitionError("redirect_limit_exceeded", "http_response", "The redirect limit was exceeded")
        absolute_url = urljoin(req.full_url, newurl)
        _assert_public_hostname(absolute_url, deadline=self.deadline, clock=self.clock)
        _remaining_seconds(self.deadline, self.clock, "http_response")
        self.redirects.append(sanitize_url(absolute_url))
        redirected = super().redirect_request(req, fp, code, msg, headers, absolute_url)
        if redirected is not None:
            redirected.headers.clear()
            redirected.add_header("User-Agent", "scholarly-source-acquisition/1.0")
            redirected.add_header("Accept", "application/pdf")
            redirected.add_header("Accept-Encoding", "identity")
        _remaining_seconds(self.deadline, self.clock, "http_response")
        return redirected


def _open_http_stream(
    url: str,
    deadline: float,
    redirect_limit: int,
    *,
    clock: Any,
    transport_profile: str,
    proxy_url: str | None,
) -> tuple[Any, list[str]]:
    _assert_public_hostname(url, deadline=deadline, clock=clock)
    redirect_handler = _BoundedRedirectHandler(redirect_limit, deadline, clock)
    context = ssl.create_default_context()
    opener = build_opener(
        _proxy_handler(transport_profile, proxy_url),
        HTTPHandler(),
        HTTPSHandler(context=context),
        redirect_handler,
    )
    request = Request(
        url,
        headers={
            "User-Agent": "scholarly-source-acquisition/1.0",
            "Accept": "application/pdf",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    remaining = _remaining_seconds(deadline, clock, "http_response")
    response = _run_with_deadline(
        lambda: opener.open(request, timeout=remaining),
        deadline=deadline,
        clock=clock,
        stage="http_response",
        late_cleanup=lambda opened: _abort_response_io(opened),
    )
    try:
        _assert_public_hostname(response.geturl(), deadline=deadline, clock=clock)
        _remaining_seconds(deadline, clock, "http_response")
    except Exception:
        _abort_response_io(response)
        raise
    return response, redirect_handler.redirects


def _normalized_content_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    media_type = value.split(";", 1)[0].strip().casefold()
    return media_type if MIME_RE.fullmatch(media_type) else None


def _parse_content_length(value: Any, max_bytes: int) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.isdigit():
        raise AcquisitionError("invalid_content_length", "size_limit", "Content-Length is invalid")
    length = int(value)
    if length > max_bytes:
        raise AcquisitionError("size_limit_exceeded", "size_limit", "The declared PDF size exceeds the limit")
    return length


def _stream_pdf_to_temp(
    response: Any,
    parent: Path,
    max_bytes: int,
    declared_length: int | None,
    *,
    deadline: float,
    clock: Any,
) -> tuple[Path, int, str]:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".source-acquisition-", suffix=".part", dir=parent)
    temporary = Path(temporary_name)
    descriptor_open = True
    completed = False
    digest = hashlib.sha256()
    total = 0
    prefix = b""
    chunk_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=2)
    stop_reader = threading.Event()

    def reader() -> None:
        try:
            while not stop_reader.is_set():
                _remaining_seconds(deadline, clock, "http_response")
                chunk = response.read(CHUNK_SIZE)
                _remaining_seconds(deadline, clock, "http_response")
                if not isinstance(chunk, bytes):
                    raise AcquisitionError("invalid_response_body", "pdf_magic", "The response body is not bytes")
                while not stop_reader.is_set():
                    try:
                        chunk_queue.put(
                            ("chunk", chunk),
                            timeout=_remaining_seconds(deadline, clock, "http_response"),
                        )
                        break
                    except queue.Full:
                        continue
                if not chunk:
                    return
        except AcquisitionError as error:
            try:
                chunk_queue.put_nowait(("error", error))
            except queue.Full:
                pass
        except (TimeoutError, socket.timeout):
            error = AcquisitionError(
                "fetch_deadline_exceeded",
                "http_response",
                "The total scholarly PDF fetch deadline was exceeded",
                True,
            )
            try:
                chunk_queue.put_nowait(("error", error))
            except queue.Full:
                pass
        except Exception:
            error = AcquisitionError(
                "network_error", "http_response", "The scholarly PDF response read failed", True
            )
            try:
                chunk_queue.put_nowait(("error", error))
            except queue.Full:
                pass

    try:
        reader_thread = threading.Thread(
            target=reader, name="scholarly-acquisition-reader", daemon=True
        )
        reader_thread.start()
        target_stream = os.fdopen(descriptor, "wb")
        descriptor_open = False
        with target_stream as target:
            while True:
                _remaining_seconds(deadline, clock, "http_response")
                try:
                    kind, payload = chunk_queue.get(
                        timeout=_remaining_seconds(deadline, clock, "http_response")
                    )
                except queue.Empty as error:
                    raise AcquisitionError(
                        "fetch_deadline_exceeded",
                        "http_response",
                        "The total scholarly PDF fetch deadline was exceeded",
                        True,
                    ) from error
                _remaining_seconds(deadline, clock, "http_response")
                if kind == "error":
                    raise payload
                chunk = payload
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise AcquisitionError("size_limit_exceeded", "size_limit", "The downloaded PDF exceeds the limit")
                if len(prefix) < len(PDF_MAGIC):
                    prefix += chunk[: len(PDF_MAGIC) - len(prefix)]
                    if len(prefix) == len(PDF_MAGIC) and prefix != PDF_MAGIC:
                        raise AcquisitionError("pdf_magic_mismatch", "pdf_magic", "The response is not a PDF byte stream")
                target.write(chunk)
                digest.update(chunk)
                _remaining_seconds(deadline, clock, "http_response")
            target.flush()
            os.fsync(target.fileno())
        _remaining_seconds(deadline, clock, "http_response")
        if prefix != PDF_MAGIC:
            raise AcquisitionError("pdf_magic_mismatch", "pdf_magic", "The response is not a complete PDF byte stream")
        if declared_length is not None and total != declared_length:
            raise AcquisitionError("content_length_mismatch", "size_limit", "Content-Length does not match downloaded bytes")
        completed = True
        return temporary, total, digest.hexdigest()
    finally:
        stop_reader.set()
        if descriptor_open:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if not completed:
            temporary.unlink(missing_ok=True)


def _publish_exclusive(temporary: Path, destination: Path, *, deadline: float, clock: Any) -> None:
    published = False
    try:
        _remaining_seconds(deadline, clock, "artifact_publish")
        os.link(temporary, destination)
        published = True
        _remaining_seconds(deadline, clock, "artifact_publish")
    except FileExistsError as error:
        raise AcquisitionError("destination_exists", "artifact_publish", "Destination appeared during acquisition") from error
    except AcquisitionError:
        if published:
            try:
                if os.path.samefile(temporary, destination):
                    destination.unlink()
            except OSError:
                pass
        raise
    except OSError as error:
        raise AcquisitionError("publish_failed", "artifact_publish", "Verified bytes could not be published") from error
    finally:
        temporary.unlink(missing_ok=True)


def fetch_candidate(
    raw_candidate: Any,
    destination: str,
    *,
    generated_at: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    redirect_limit: int = DEFAULT_REDIRECT_LIMIT,
    transport_profile: str = "direct",
    proxy_url: str | None = None,
    result_path: str | None = None,
    _clock: Any = time.monotonic,
    _cleanup_grace_seconds: float = DEFAULT_CLEANUP_GRACE_SECONDS,
) -> dict[str, Any]:
    timestamp = generated_at or utc_now()
    validate_timestamp(timestamp)
    checks = _base_checks()
    http = _http_record()
    candidate = None
    request = None
    temporary: Path | None = None
    response = None
    try:
        _validate_limits(max_bytes, timeout_seconds, redirect_limit)
        candidate = normalize_candidate(raw_candidate)
        _set_check(checks, "candidate_contract", "passed")
        _set_check(checks, "url_policy", "passed")
        normalized_profile, normalized_proxy = normalize_transport(transport_profile, proxy_url)
        _set_check(checks, "transport_policy", "passed")
        destination_path = _absolute_path(destination)
        request = _request_record(
            candidate,
            destination_path,
            max_bytes,
            timeout_seconds,
            redirect_limit,
            normalized_profile,
            normalized_proxy,
        )
        destination_path = _preflight_destination(destination, result_path=result_path)
        _set_check(checks, "destination_exclusive", "passed")

        deadline = _clock() + timeout_seconds
        http["attempted"] = True
        response, redirects = _open_http_stream(
            candidate["locator"]["url"],
            deadline,
            redirect_limit,
            clock=_clock,
            transport_profile=normalized_profile,
            proxy_url=normalized_proxy,
        )
        http["redirects"] = redirects
        _set_check(checks, "public_dns", "passed")
        status_code = getattr(response, "status", None) or response.getcode()
        http["status_code"] = status_code
        http["final_url"] = sanitize_url(response.geturl())
        if status_code != 200:
            raise AcquisitionError("http_status_rejected", "http_response", "The server did not return HTTP 200", True)
        _set_check(checks, "http_response", "passed")

        content_type = _normalized_content_type(response.headers.get("Content-Type"))
        http["content_type"] = content_type
        if content_type != "application/pdf":
            raise AcquisitionError("content_type_mismatch", "content_type", "The response Content-Type is not application/pdf")
        content_encoding = response.headers.get("Content-Encoding")
        if isinstance(content_encoding, str) and content_encoding.strip().casefold() not in {"", "identity"}:
            raise AcquisitionError("content_encoding_rejected", "content_type", "Encoded response bodies are not accepted")
        _set_check(checks, "content_type", "passed")

        declared_length = _parse_content_length(response.headers.get("Content-Length"), max_bytes)
        temporary, size_bytes, source_sha256 = _stream_pdf_to_temp(
            response,
            destination_path.parent,
            max_bytes,
            declared_length,
            deadline=deadline,
            clock=_clock,
        )
        http["bytes_received"] = size_bytes
        _set_check(checks, "pdf_magic", "passed")
        _set_check(checks, "size_limit", "passed")
        _set_check(checks, "sha256", "passed")
        _publish_exclusive(temporary, destination_path, deadline=deadline, clock=_clock)
        temporary = None
        _set_check(checks, "artifact_publish", "passed")
    except ContractError:
        return _input_failure_result("fetch", timestamp, "Candidate input or limits are invalid")
    except HTTPError as error:
        http["attempted"] = True
        http["status_code"] = error.code
        controlled = AcquisitionError("http_status_rejected", "http_response", "The server rejected the anonymous PDF request", error.code >= 500)
        _set_check(checks, "http_response", "failed", controlled.safe_message)
        failure = controlled
    except (TimeoutError, socket.timeout):
        failure = AcquisitionError("network_timeout", "http_response", "The anonymous PDF request timed out", True)
        _set_check(checks, "http_response", "failed", failure.safe_message)
    except URLError:
        failure = AcquisitionError("network_error", "http_response", "The anonymous PDF request failed", True)
        _set_check(checks, "http_response", "failed", failure.safe_message)
    except AcquisitionError as error:
        failure = error
        _set_check(checks, error.stage, "failed", error.safe_message)
    except OSError:
        failure = AcquisitionError("io_error", "artifact_publish", "Local acquisition I/O failed")
        _set_check(checks, "artifact_publish", "failed", failure.safe_message)
    finally:
        if response is not None:
            _abort_response_io(response, grace_seconds=_cleanup_grace_seconds)
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    if "failure" in locals():
        return _finish_result(
            _result_payload(
                operation="fetch",
                status="failed",
                generated_at=timestamp,
                candidate=candidate,
                request=request,
                http=http,
                checks=checks,
                artifact=None,
                handoff=None,
                failures=[_failure(failure)],
            )
        )

    artifact = {
        "path": str(destination_path),
        "media_type": "application/pdf",
        "size_bytes": size_bytes,
        "sha256": source_sha256,
        "pdf_magic_verified": True,
        "content_type_verified": True,
    }
    handoff = {
        "target_schema": "PaperSourceBundle/v1",
        "source_path": str(destination_path),
        "source_sha256": source_sha256,
        "builder_contract": "skills/learn-from-papers/scripts/paper_source_bundle.py",
        "recommended_argv": [
            "build",
            "--source",
            str(destination_path),
            "--output",
            "<bundle-json-path>",
        ],
    }
    return _finish_result(
        _result_payload(
            operation="fetch",
            status="acquired",
            generated_at=timestamp,
            candidate=candidate,
            request=request,
            http=http,
            checks=checks,
            artifact=artifact,
            handoff=handoff,
            failures=[],
        )
    )


def _validate_manifest_candidate(value: Any) -> dict[str, Any]:
    candidate = normalize_candidate(value, preserve_request_url=False)
    if candidate["locator"]["url"] != value["locator"]["url"]:
        raise ContractError("result candidate URL must be sanitized")
    return candidate


def _validate_request(value: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("result.request must be an object")
    require_exact_keys(value, REQUEST_KEYS, "result.request")
    requested_url = sanitize_url(value.get("requested_url"))
    if requested_url != value.get("requested_url"):
        raise ContractError("result.request.requested_url must not contain a query")
    if requested_url != candidate["locator"]["url"]:
        raise ContractError("result request URL must match candidate URL")
    if not isinstance(value.get("query_removed"), bool):
        raise ContractError("result.request.query_removed must be boolean")
    if value.get("source_type") != candidate["locator"]["source_type"] or value.get("access_basis") != candidate["locator"]["access_basis"]:
        raise ContractError("result request source/access must match candidate")
    destination = require_string(value.get("destination"), "result.request.destination")
    if not Path(destination).is_absolute():
        raise ContractError("result.request.destination must be absolute")
    if value.get("request_profile") != "anonymous-pdf":
        raise ContractError("result.request.request_profile must be anonymous-pdf")
    try:
        profile, canonical_proxy = normalize_transport(
            value.get("transport_profile"), value.get("proxy_url")
        )
    except AcquisitionError as error:
        raise ContractError(error.safe_message) from error
    if profile != value.get("transport_profile") or canonical_proxy != value.get("proxy_url"):
        raise ContractError("result request transport fields are not canonical")
    _validate_limits(value.get("max_bytes"), value.get("timeout_seconds"), value.get("redirect_limit"))
    return value


def _validate_http(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("result.http must be an object")
    require_exact_keys(value, HTTP_KEYS, "result.http")
    if not isinstance(value.get("attempted"), bool):
        raise ContractError("result.http.attempted must be boolean")
    status_code = value.get("status_code")
    if status_code is not None and (not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599):
        raise ContractError("result.http.status_code must be null or a valid HTTP status")
    content_type = value.get("content_type")
    if content_type is not None and (not isinstance(content_type, str) or not MIME_RE.fullmatch(content_type)):
        raise ContractError("result.http.content_type must be null or a normalized media type")
    for label in ("final_url",):
        url = value.get(label)
        if url is not None and sanitize_url(url) != url:
            raise ContractError(f"result.http.{label} must be a sanitized HTTP(S) URL")
    redirects = value.get("redirects")
    if not isinstance(redirects, list):
        raise ContractError("result.http.redirects must be a list")
    for index, url in enumerate(redirects):
        if sanitize_url(url) != url:
            raise ContractError(f"result.http.redirects[{index}] must be sanitized")
    bytes_received = value.get("bytes_received")
    if not isinstance(bytes_received, int) or isinstance(bytes_received, bool) or bytes_received < 0:
        raise ContractError("result.http.bytes_received must be a non-negative integer")
    return value


def _validate_checks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(CHECK_NAMES):
        raise ContractError("result.checks must contain the complete ordered check set")
    for index, (check, expected_name) in enumerate(zip(value, CHECK_NAMES)):
        if not isinstance(check, dict):
            raise ContractError(f"result.checks[{index}] must be an object")
        require_exact_keys(check, CHECK_KEYS, f"result.checks[{index}]")
        if check.get("name") != expected_name:
            raise ContractError("result.checks order or name is invalid")
        if check.get("status") not in {"passed", "failed", "not_run"}:
            raise ContractError("result check status is invalid")
        if check.get("detail") is not None:
            require_string(check["detail"], "result check detail", maximum=300)
    return value


def _validate_failures(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError("result.failures must be a list")
    for index, failure in enumerate(value):
        if not isinstance(failure, dict):
            raise ContractError(f"result.failures[{index}] must be an object")
        require_exact_keys(failure, FAILURE_KEYS, f"result.failures[{index}]")
        require_string(failure.get("code"), "failure.code", maximum=80)
        if failure.get("stage") not in CHECK_NAMES:
            raise ContractError("failure.stage must name a defined check")
        require_string(failure.get("message"), "failure.message", maximum=300)
        if not isinstance(failure.get("retryable"), bool):
            raise ContractError("failure.retryable must be boolean")
    return value


def _validate_artifact(value: Any, request: dict[str, Any], *, verify_artifact: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("result.artifact must be an object")
    require_exact_keys(value, ARTIFACT_KEYS, "result.artifact")
    path_text = require_string(value.get("path"), "result.artifact.path")
    if path_text != request["destination"] or not Path(path_text).is_absolute():
        raise ContractError("artifact path must equal the absolute request destination")
    if value.get("media_type") != "application/pdf":
        raise ContractError("artifact media_type must be application/pdf")
    size = value.get("size_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < len(PDF_MAGIC):
        raise ContractError("artifact size_bytes is invalid")
    digest = value.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ContractError("artifact sha256 must be lowercase SHA-256")
    if value.get("pdf_magic_verified") is not True or value.get("content_type_verified") is not True:
        raise ContractError("artifact verification flags must be true")
    if verify_artifact:
        path = Path(path_text)
        try:
            _assert_non_symlink_components(path, "Acquired artifact")
        except AcquisitionError as error:
            raise ContractError(error.safe_message) from error
        if not path.is_file():
            raise ContractError("acquired artifact is missing")
        if path.stat().st_size != size:
            raise ContractError("acquired artifact size mismatch")
        with path.open("rb") as stream:
            if stream.read(len(PDF_MAGIC)) != PDF_MAGIC:
                raise ContractError("acquired artifact PDF magic mismatch")
        if sha256_file(path) != digest:
            raise ContractError("acquired artifact SHA-256 mismatch")
    return value


def _validate_handoff(value: Any, artifact: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("result.handoff must be an object")
    require_exact_keys(value, HANDOFF_KEYS, "result.handoff")
    if value.get("target_schema") != "PaperSourceBundle/v1":
        raise ContractError("handoff.target_schema must be PaperSourceBundle/v1")
    if value.get("source_path") != artifact["path"] or value.get("source_sha256") != artifact["sha256"]:
        raise ContractError("handoff source must match the acquired artifact")
    if value.get("builder_contract") != "skills/learn-from-papers/scripts/paper_source_bundle.py":
        raise ContractError("handoff.builder_contract is invalid")
    expected_argv = [
        "build",
        "--source",
        artifact["path"],
        "--output",
        "<bundle-json-path>",
    ]
    if value.get("recommended_argv") != expected_argv:
        raise ContractError("handoff.recommended_argv is invalid")
    return value


def validate_result(document: Any, *, verify_artifact: bool = True) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ContractError("result must be a JSON object")
    require_exact_keys(document, RESULT_KEYS, "result")
    if document.get("schema") != RESULT_SCHEMA or document.get("schema_version") != "v1":
        raise ContractError("result schema/version is invalid")
    if document.get("producer") != PRODUCER or document.get("protocol_version") != PROTOCOL_VERSION:
        raise ContractError("result producer/protocol is invalid")
    operation = document.get("operation")
    status = document.get("status")
    if operation not in {"plan", "fetch"} or status not in {"planned", "acquired", "failed"}:
        raise ContractError("result operation/status is invalid")
    validate_timestamp(document.get("generated_at"))

    candidate_value = document.get("candidate")
    request_value = document.get("request")
    if candidate_value is None:
        if document.get("candidate_digest") is not None or request_value is not None or status != "failed":
            raise ContractError("only a failed input result may omit candidate and request")
        candidate = None
        request = None
    else:
        candidate = _validate_manifest_candidate(candidate_value)
        if document.get("candidate_digest") != sha256_json(candidate_value):
            raise ContractError("result candidate_digest mismatch")
        if request_value is None:
            if status != "failed":
                raise ContractError("only a failed result may omit request")
            request = None
        else:
            request = _validate_request(request_value, candidate)

    http = _validate_http(document.get("http"))
    checks = _validate_checks(document.get("checks"))
    failures = _validate_failures(document.get("failures"))
    artifact_value = document.get("artifact")
    handoff_value = document.get("handoff")

    if status == "planned":
        if operation != "plan" or failures or artifact_value is not None or handoff_value is not None or http["attempted"]:
            raise ContractError("planned result state is inconsistent")
        if candidate is None or request is None:
            raise ContractError("planned result requires candidate and request")
        if [check["status"] for check in checks[:4]] != ["passed", "passed", "passed", "passed"] or any(
            check["status"] != "not_run" for check in checks[4:]
        ):
            raise ContractError("planned result checks are inconsistent")
    elif status == "failed":
        if not failures or artifact_value is not None or handoff_value is not None:
            raise ContractError("failed result state is inconsistent")
        failed_names = {check["name"] for check in checks if check["status"] == "failed"}
        if not failed_names or any(failure["stage"] not in failed_names for failure in failures):
            raise ContractError("failed result must bind failures to failed checks")
    else:
        if operation != "fetch" or failures or candidate is None or request is None:
            raise ContractError("acquired result state is inconsistent")
        if any(check["status"] != "passed" for check in checks):
            raise ContractError("acquired result requires all checks to pass")
        if not http["attempted"] or http["status_code"] != 200 or http["content_type"] != "application/pdf":
            raise ContractError("acquired result HTTP state is inconsistent")
        artifact = _validate_artifact(artifact_value, request, verify_artifact=verify_artifact)
        _validate_handoff(handoff_value, artifact)
        if http["bytes_received"] != artifact["size_bytes"]:
            raise ContractError("acquired HTTP byte count must match artifact size")

    payload = {key: value for key, value in document.items() if key not in {"result_id", "result_digest"}}
    digest = sha256_json(payload)
    if document.get("result_digest") != digest or document.get("result_id") != f"acquisition-result-{digest[:16]}":
        raise ContractError("result content address mismatch")
    return document


def _load_json(path: str) -> Any:
    input_path = Path(path)
    if input_path.is_symlink():
        raise ContractError("input JSON cannot be a symlink")
    with input_path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_json_atomic(path: str, document: dict[str, Any]) -> None:
    output = _absolute_path(path)
    _assert_non_symlink_components(output.parent, "Result parent")
    if not output.parent.is_dir():
        raise ContractError("result parent must already exist")
    if output.is_symlink() or output.is_dir():
        raise ContractError("result path cannot be a symlink or directory")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".acquisition-result-", suffix=".json", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _read_candidate_or_failure(path: str, operation: str, generated_at: str) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        return _load_json(path), None
    except (OSError, json.JSONDecodeError, ContractError):
        return None, _input_failure_result(operation, generated_at, "Candidate JSON could not be read or parsed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "fetch"):
        command = commands.add_parser(name, help=f"{name.capitalize()} one explicit scholarly PDF acquisition")
        command.add_argument("--candidate", required=True, help="AcquisitionCandidate/v1 JSON")
        command.add_argument("--destination", required=True, help="New PDF path; never overwritten")
        command.add_argument("--output", required=True, help="AcquisitionResult/v1 JSON")
        command.add_argument("--generated-at", help="Canonical UTC timestamp for reproducible fixtures")
        command.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
        command.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT)
        command.add_argument("--redirect-limit", type=int, default=DEFAULT_REDIRECT_LIMIT)
        command.add_argument(
            "--transport-profile",
            choices=("direct", "loopback-proxy"),
            default="direct",
        )
        command.add_argument(
            "--proxy-url",
            help="Explicit unauthenticated http://<loopback-IP>:<port>; loopback-proxy only",
        )
    validate = commands.add_parser("validate", help="Validate an AcquisitionResult/v1 and live acquired artifact")
    validate.add_argument("--input", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        try:
            result = _load_json(args.input)
            validate_result(result, verify_artifact=True)
        except (OSError, json.JSONDecodeError, ContractError) as error:
            print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
            return 1
        print(json.dumps({"valid": True, "result_id": result["result_id"], "status": result["status"]}, sort_keys=True))
        return 0

    timestamp = args.generated_at or utc_now()
    try:
        validate_timestamp(timestamp)
    except ContractError as error:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2

    candidate_path = _absolute_path(args.candidate)
    output_path = _absolute_path(args.output)
    if candidate_path == output_path:
        print(json.dumps({"valid": False, "error": "candidate and output paths must differ"}, sort_keys=True), file=sys.stderr)
        return 2
    raw_candidate, failure_result = _read_candidate_or_failure(args.candidate, args.command, timestamp)
    if failure_result is not None:
        result = failure_result
    else:
        function = plan_candidate if args.command == "plan" else fetch_candidate
        result = function(
            raw_candidate,
            args.destination,
            generated_at=timestamp,
            max_bytes=args.max_bytes,
            timeout_seconds=args.timeout_seconds,
            redirect_limit=args.redirect_limit,
            transport_profile=args.transport_profile,
            proxy_url=args.proxy_url,
            result_path=args.output,
        )
    try:
        _write_json_atomic(args.output, result)
    except (OSError, ContractError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"result_id": result["result_id"], "status": result["status"]}, sort_keys=True))
    return 0 if result["status"] in {"planned", "acquired"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
