#!/usr/bin/env python3
"""Offline tests for scholarly source acquisition."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import source_acquisition as acquisition


FIXED_TIME = "2026-08-05T00:00:00Z"


def candidate(url: str = "https://repository.example.edu/paper.pdf?download=1") -> dict:
    return {
        "schema": "AcquisitionCandidate/v1",
        "candidate_id": "candidate-0123456789abcdef",
        "title": "A bounded scholarly source",
        "authors": ["A. Author"],
        "year": 2024,
        "rank": 1,
        "identifiers": {"doi": "10.1234/example"},
        "discovery_ref": {
            "schema": "ScholarDiscoveryResult/v1",
            "artifact_sha256": "a" * 64,
            "candidate_id": "candidate-0123456789abcdef",
        },
        "locator": {
            "url": url,
            "source_type": "institutional_repository",
            "access_basis": "institutional_public_copy",
        },
    }


class FakeHeaders(dict):
    def get(self, key: str, default=None):
        return super().get(key, default)


class FakeResponse:
    def __init__(self, body: bytes, *, content_type: str = "application/pdf", declared_length: int | None = None):
        self._stream = io.BytesIO(body)
        self.status = 200
        self.headers = FakeHeaders({"Content-Type": content_type})
        if declared_length is not None:
            self.headers["Content-Length"] = str(declared_length)
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return "https://cdn.example.edu/final.pdf?download=1"

    def close(self) -> None:
        self.closed = True


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class TricklingResponse(FakeResponse):
    def __init__(self, chunks: list[bytes], clock: FakeClock, seconds_per_chunk: float):
        super().__init__(b"")
        self._chunks = list(chunks)
        self._clock = clock
        self._seconds_per_chunk = seconds_per_chunk

    def read(self, size: int = -1) -> bytes:
        self._clock.advance(self._seconds_per_chunk)
        return self._chunks.pop(0) if self._chunks else b""


class BlockingCloseTricklingResponse(TricklingResponse):
    def __init__(self, chunks: list[bytes], clock: FakeClock, seconds_per_chunk: float):
        super().__init__(chunks, clock, seconds_per_chunk)
        self.release_close = threading.Event()

    def close(self) -> None:
        self.release_close.wait(timeout=5.0)
        self.closed = True


class SourceAcquisitionTests(unittest.TestCase):
    def test_cli_reports_limit_error_without_mislabeling_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path = root / "candidate.json"
            output_path = root / "result.json"
            destination = root / "paper.pdf"
            candidate_path.write_text(json.dumps(candidate()), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                status = acquisition.main(
                    [
                        "plan",
                        "--candidate",
                        str(candidate_path),
                        "--destination",
                        str(destination),
                        "--output",
                        str(output_path),
                        "--generated-at",
                        FIXED_TIME,
                        "--redirect-limit",
                        str(acquisition.HARD_MAX_REDIRECT_LIMIT + 1),
                    ]
                )
            result = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(1, status)
        self.assertEqual("failed", result["status"])
        self.assertIsNone(result["candidate"])
        self.assertIn("Acquisition limits are invalid", result["checks"][0]["detail"])
        self.assertIn("redirect", result["checks"][0]["detail"].lower())
        self.assertEqual("invalid_limits", result["failures"][0]["code"])

    def test_plan_is_offline_and_query_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            acquisition.socket, "getaddrinfo", side_effect=AssertionError("network called")
        ) as resolver:
            destination = Path(directory) / "paper.pdf"
            result = acquisition.plan_candidate(
                candidate(), str(destination), generated_at=FIXED_TIME
            )
        self.assertEqual(result["status"], "planned")
        self.assertFalse(result["http"]["attempted"])
        self.assertTrue(result["request"]["query_removed"])
        self.assertNotIn("?", result["request"]["requested_url"])
        self.assertNotIn("?", result["candidate"]["locator"]["url"])
        resolver.assert_not_called()
        acquisition.validate_result(result, verify_artifact=False)

    def test_direct_proxy_handler_ignores_environment(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://remote.example.com:8080",
                "HTTPS_PROXY": "http://remote.example.com:8080",
                "ALL_PROXY": "http://remote.example.com:8080",
            },
        ):
            handler = acquisition._proxy_handler("direct", None)
        self.assertEqual(handler.proxies, {})

    def test_loopback_proxy_handler_is_explicit_for_both_schemes(self) -> None:
        handler = acquisition._proxy_handler(
            "loopback-proxy", "http://127.0.0.1:10808"
        )
        self.assertEqual(
            handler.proxies,
            {
                "http": "http://127.0.0.1:10808",
                "https": "http://127.0.0.1:10808",
            },
        )

    def test_loopback_proxy_ignores_environment_no_proxy(self) -> None:
        class FakeParent:
            def __init__(self) -> None:
                self.calls = 0

            def open(self, request, timeout=None):
                self.calls += 1
                return "proxied"

        handler = acquisition._proxy_handler(
            "loopback-proxy", "http://127.0.0.1:10808"
        )
        parent = FakeParent()
        handler.add_parent(parent)
        request = acquisition.Request("https://example.edu/paper.pdf")
        request.timeout = 3.0
        with mock.patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"}):
            result = handler.https_open(request)
        self.assertEqual(result, "proxied")
        self.assertEqual(parent.calls, 1)
        self.assertEqual(request._tunnel_host, "example.edu")
        self.assertEqual(
            handler.proxies,
            {
                "http": "http://127.0.0.1:10808",
                "https": "http://127.0.0.1:10808",
            },
        )

    def test_proxy_policy_rejects_remote_and_authorization(self) -> None:
        rejected = [
            "http://192.0.2.10:8080",
            "http://proxy.example.com:8080",
            "http://user:secret@127.0.0.1:10808",
            "http://127.0.0.1:10808?token=secret",
            "https://127.0.0.1:10808",
            "http://127.0.0.1:0",
        ]
        for proxy_url in rejected:
            with self.subTest(proxy_url=proxy_url), self.assertRaises(
                acquisition.AcquisitionError
            ):
                acquisition.normalize_transport("loopback-proxy", proxy_url)

    def test_rejected_proxy_is_structured_and_does_not_persist_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = acquisition.plan_candidate(
                candidate(),
                str(Path(directory) / "paper.pdf"),
                generated_at=FIXED_TIME,
                transport_profile="loopback-proxy",
                proxy_url="http://user:secret@127.0.0.1:10808",
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failures"][0]["stage"], "transport_policy")
        self.assertIsNone(result["request"])
        self.assertNotIn(b"secret", acquisition.canonical_json_bytes(result))
        acquisition.validate_result(result, verify_artifact=False)

    def test_url_rejects_authorization_material(self) -> None:
        with self.assertRaises(acquisition.AcquisitionError):
            acquisition.normalize_candidate(
                candidate("https://repository.example.edu/paper.pdf?access_token=secret")
            )
        with self.assertRaises(acquisition.AcquisitionError):
            acquisition.normalize_candidate(
                candidate("https://user:secret@repository.example.edu/paper.pdf")
            )

    def test_existing_destination_fails_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "paper.pdf"
            destination.write_bytes(b"existing")
            with mock.patch.object(
                acquisition, "_open_http_stream", side_effect=AssertionError("network called")
            ) as opener:
                result = acquisition.fetch_candidate(
                    candidate(), str(destination), generated_at=FIXED_TIME
                )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failures"][0]["code"], "destination_exists")
            self.assertEqual(destination.read_bytes(), b"existing")
            opener.assert_not_called()
            acquisition.validate_result(result, verify_artifact=False)

    def test_plan_existing_destination_is_a_valid_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "paper.pdf"
            destination.write_bytes(b"existing")
            result = acquisition.plan_candidate(
                candidate(), str(destination), generated_at=FIXED_TIME
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["request"]["destination"], str(destination))
            self.assertEqual(result["failures"][0]["code"], "destination_exists")
            acquisition.validate_result(result, verify_artifact=False)

    def test_fetch_acquires_verified_pdf_and_handoff(self) -> None:
        body = b"%PDF-1.7\nfixture\n%%EOF\n"
        response = FakeResponse(body, declared_length=len(body))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            acquisition,
            "_open_http_stream",
            return_value=(response, ["https://cdn.example.edu/final.pdf"]),
        ):
            destination = Path(directory) / "paper.pdf"
            result = acquisition.fetch_candidate(
                candidate(), str(destination), generated_at=FIXED_TIME
            )
            self.assertEqual(result["status"], "acquired")
            self.assertEqual(destination.read_bytes(), body)
            self.assertEqual(result["artifact"]["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(result["handoff"]["source_sha256"], result["artifact"]["sha256"])
            self.assertNotIn("?", result["http"]["final_url"])
            acquisition.validate_result(result, verify_artifact=True)
        self.assertTrue(response.closed)

    def test_html_pseudo_pdf_is_rejected_and_removed(self) -> None:
        response = FakeResponse(b"<html>not a paper</html>")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            acquisition, "_open_http_stream", return_value=(response, [])
        ):
            destination = Path(directory) / "paper.pdf"
            result = acquisition.fetch_candidate(
                candidate(), str(destination), generated_at=FIXED_TIME
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failures"][0]["code"], "pdf_magic_mismatch")
            self.assertFalse(destination.exists())
            self.assertFalse(list(Path(directory).glob(".source-acquisition-*.part")))
            acquisition.validate_result(result, verify_artifact=False)

    def test_trickling_multichunk_response_exceeds_total_deadline(self) -> None:
        clock = FakeClock()
        response = TricklingResponse(
            [b"%PDF-", b"1.7\nfirst", b"second", b"%%EOF", b""],
            clock,
            seconds_per_chunk=0.4,
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            acquisition, "_open_http_stream", return_value=(response, [])
        ):
            destination = Path(directory) / "paper.pdf"
            result = acquisition.fetch_candidate(
                candidate(),
                str(destination),
                generated_at=FIXED_TIME,
                timeout_seconds=1.0,
                _clock=clock,
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failures"][0]["code"], "fetch_deadline_exceeded")
            self.assertEqual(result["failures"][0]["stage"], "http_response")
            self.assertFalse(destination.exists())
            self.assertFalse(list(Path(directory).glob(".source-acquisition-*.part")))
            self.assertTrue(response.closed)
            acquisition.validate_result(result, verify_artifact=False)

    def test_deadline_does_not_wait_for_blocking_response_close(self) -> None:
        clock = FakeClock()
        response = BlockingCloseTricklingResponse(
            [b"%PDF-", b"1.7\nfirst", b"second", b"%%EOF", b""],
            clock,
            seconds_per_chunk=0.4,
        )
        try:
            with tempfile.TemporaryDirectory() as directory, mock.patch.object(
                acquisition, "_open_http_stream", return_value=(response, [])
            ):
                destination = Path(directory) / "paper.pdf"
                started = time.monotonic()
                result = acquisition.fetch_candidate(
                    candidate(),
                    str(destination),
                    generated_at=FIXED_TIME,
                    timeout_seconds=1.0,
                    _clock=clock,
                    _cleanup_grace_seconds=0.01,
                    transport_profile="loopback-proxy",
                    proxy_url="http://127.0.0.1:10808",
                )
                elapsed = time.monotonic() - started
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["failures"][0]["code"], "fetch_deadline_exceeded")
                self.assertLess(elapsed, 0.5)
                self.assertFalse(destination.exists())
                self.assertFalse(list(Path(directory).glob(".source-acquisition-*.part")))
        finally:
            response.release_close.set()

    def test_content_type_rejected_before_publish(self) -> None:
        response = FakeResponse(b"%PDF-1.7\nfixture", content_type="text/html")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            acquisition, "_open_http_stream", return_value=(response, [])
        ):
            destination = Path(directory) / "paper.pdf"
            result = acquisition.fetch_candidate(
                candidate(), str(destination), generated_at=FIXED_TIME
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failures"][0]["code"], "content_type_mismatch")
            self.assertFalse(destination.exists())

    def test_validate_detects_artifact_tampering(self) -> None:
        body = b"%PDF-1.7\nfixture\n%%EOF\n"
        response = FakeResponse(body)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            acquisition, "_open_http_stream", return_value=(response, [])
        ):
            destination = Path(directory) / "paper.pdf"
            result = acquisition.fetch_candidate(
                candidate(), str(destination), generated_at=FIXED_TIME
            )
            destination.write_bytes(b"%PDF-tampered")
            with self.assertRaises(acquisition.ContractError):
                acquisition.validate_result(result, verify_artifact=True)

    def test_validate_cli_rejects_symlink_without_traceback(self) -> None:
        body = b"%PDF-1.7\nfixture\n%%EOF\n"
        response = FakeResponse(body)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            acquisition, "_open_http_stream", return_value=(response, [])
        ):
            root = Path(directory)
            destination = root / "paper.pdf"
            result_path = root / "acquisition.json"
            result = acquisition.fetch_candidate(
                candidate(), str(destination), generated_at=FIXED_TIME
            )
            acquisition._write_json_atomic(str(result_path), result)
            target = root / "target.pdf"
            destination.replace(target)
            destination.symlink_to(target)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                return_code = acquisition.main(["validate", "--input", str(result_path)])
            self.assertEqual(return_code, 1)
            self.assertIn('"valid": false', stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_validate_rejects_unknown_field_and_stale_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = acquisition.plan_candidate(
                candidate(), str(Path(directory) / "paper.pdf"), generated_at=FIXED_TIME
            )
        tampered = copy.deepcopy(result)
        tampered["unexpected"] = True
        with self.assertRaises(acquisition.ContractError):
            acquisition.validate_result(tampered, verify_artifact=False)
        tampered = copy.deepcopy(result)
        tampered["request"]["max_bytes"] -= 1
        with self.assertRaises(acquisition.ContractError):
            acquisition.validate_result(tampered, verify_artifact=False)


if __name__ == "__main__":
    unittest.main()
