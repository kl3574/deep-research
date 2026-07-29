#!/usr/bin/env python3

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import update_existing_note as module


class UpdateExistingNoteTests(unittest.TestCase):
    def test_probe_local_write_uses_server_id_without_options_request(self) -> None:
        with patch.object(
            module,
            "request",
            return_value=(
                200,
                {"zOtErO-SeRvEr-Id": "instance-123"},
                b"Nothing to see here.",
            ),
        ) as request_mock:
            result = module.probe_local_write()

        self.assertTrue(result["supported"])
        self.assertEqual(result["server_id"], "instance-123")
        self.assertEqual(result["authorization_probe"], "deferred_until_apply")
        request_mock.assert_called_once_with(f"{module.LOCAL_BASE}/api/")

    def test_probe_local_write_rejects_runtime_without_server_id(self) -> None:
        with patch.object(
            module,
            "request",
            return_value=(200, {"Zotero-API-Version": "3"}, b""),
        ):
            result = module.probe_local_write()

        self.assertFalse(result["supported"])
        self.assertIsNone(result["server_id"])

    def test_choose_route_prefers_supported_local_then_web(self) -> None:
        self.assertEqual(
            module.choose_route(
                "auto",
                local_supported=True,
                web_key_present=True,
            ),
            "local",
        )
        self.assertEqual(
            module.choose_route(
                "auto",
                local_supported=False,
                web_key_present=True,
            ),
            "web",
        )
        self.assertIsNone(
            module.choose_route(
                "local",
                local_supported=False,
                web_key_present=True,
            )
        )
        self.assertIsNone(
            module.choose_route(
                "web",
                local_supported=True,
                web_key_present=False,
            )
        )

    def test_unavailable_route_message_matches_explicit_request(self) -> None:
        self.assertIn(
            "local write route unavailable",
            module.unavailable_route_message("local", "ZOTERO_API_KEY"),
        )
        web_message = module.unavailable_route_message("web", "CUSTOM_ZOTERO_KEY")
        self.assertIn("Web API write route unavailable", web_message)
        self.assertIn("CUSTOM_ZOTERO_KEY is unset", web_message)
        auto_message = module.unavailable_route_message("auto", "ZOTERO_API_KEY")
        self.assertIn("local write authorization", auto_message)
        self.assertIn("ZOTERO_API_KEY is unset", auto_message)

    def test_authorize_local_parses_key_without_logging_it(self) -> None:
        body = json.dumps(
            {"key": "local-secret-for-test", "remember": True}
        ).encode("utf-8")
        with patch.object(
            module,
            "request",
            return_value=(200, {}, body),
        ) as request_mock:
            result = module.authorize_local("instance-123", "test app")

        self.assertEqual(result["api_key"], "local-secret-for-test")
        self.assertTrue(result["remember"])
        _, kwargs = request_mock.call_args
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(
            kwargs["headers"]["Zotero-Server-ID"],
            "instance-123",
        )
        self.assertEqual(kwargs["payload"], {"appName": "test app"})
        self.assertEqual(kwargs["timeout"], 55)

    def test_authorize_local_reports_rate_limit_without_response_body(self) -> None:
        with patch.object(
            module,
            "request",
            return_value=(
                429,
                {"Retry-After": "37"},
                b'{"key":"must-not-appear"}',
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "rate-limited; retry after 37 seconds",
            ) as raised:
                module.authorize_local("instance-123", "test app")

        self.assertNotIn("must-not-appear", str(raised.exception))

    def test_patch_local_note_uses_version_guard_and_reads_back(self) -> None:
        new_html = '<div data-schema-version="9"><p>中文</p></div>'
        local = {
            "note_key": "NOTE1234",
            "parent_key": "PARENT12",
            "local_version": 123,
            "new_html": new_html,
            "new_sha256": module.sha256_text(new_html),
        }
        with (
            patch.object(
                module,
                "request",
                return_value=(204, {}, b""),
            ) as request_mock,
            patch.object(
                module,
                "get_json",
                return_value=(
                    {},
                    {
                        "version": 124,
                        "data": {
                            "parentItem": "PARENT12",
                            "note": new_html,
                        },
                    },
                ),
            ),
        ):
            result = module.patch_local_note(
                1234567,
                local,
                "local-secret-for-test",
                "instance-123",
            )

        self.assertTrue(result["local_verified"])
        self.assertEqual(result["local_version"], 124)
        _, kwargs = request_mock.call_args
        self.assertEqual(kwargs["method"], "PATCH")
        self.assertEqual(
            kwargs["headers"]["If-Unmodified-Since-Version"],
            "123",
        )
        self.assertEqual(
            kwargs["headers"]["Zotero-Server-ID"],
            "instance-123",
        )
        self.assertEqual(
            kwargs["headers"]["Zotero-API-Key"],
            "local-secret-for-test",
        )
        self.assertEqual(kwargs["payload"], {"note": new_html})


if __name__ == "__main__":
    unittest.main()
