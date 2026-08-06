import unittest
from datetime import datetime, timezone
from unittest import mock

import scholar_discovery as discovery


class OperationalTimestampTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 6, 0, 0, 0, tzinfo=timezone.utc)

    def test_rejects_timestamp_beyond_future_skew(self):
        with mock.patch.object(discovery, "utc_now", return_value=self.now):
            with self.assertRaisesRegex(discovery.ContractError, "in the future"):
                discovery.require_timestamp(
                    "2026-08-06T00:05:01Z", "request.as_of"
                )

    def test_accepts_timestamp_at_future_skew_boundary(self):
        with mock.patch.object(discovery, "utc_now", return_value=self.now):
            self.assertEqual(
                discovery.require_timestamp(
                    "2026-08-06T00:05:00Z", "request.as_of"
                ),
                "2026-08-06T00:05:00Z",
            )

    def test_compares_non_utc_offset_in_utc(self):
        with mock.patch.object(discovery, "utc_now", return_value=self.now):
            self.assertEqual(
                discovery.require_timestamp(
                    "2026-08-06T08:05:00+08:00", "batch.accessed_at"
                ),
                "2026-08-06T08:05:00+08:00",
            )


if __name__ == "__main__":
    unittest.main()
