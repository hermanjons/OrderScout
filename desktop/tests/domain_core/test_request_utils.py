from __future__ import annotations

import asyncio
import unittest

from Core.utils import request_utils


class TestRequestUtils(unittest.TestCase):
    def tearDown(self) -> None:
        request_utils.reset_request_chaos()

    def test_async_make_request_can_inject_429_chaos(self) -> None:
        request_utils.configure_request_chaos(enabled=True, mode="429", rate=1.0, seed=42)

        result = asyncio.run(request_utils.async_make_request("GET", "https://example.com/test"))

        self.assertFalse(result.success)
        self.assertEqual(int((result.data or {}).get("status_code") or 0), 429)
        self.assertIn("429", str(result.message or ""))

    def test_configure_request_chaos_clamps_rate_and_normalizes_mode(self) -> None:
        state = request_utils.configure_request_chaos(enabled=True, mode=" NETWORK ", rate=9.0, seed=1)
        self.assertTrue(bool(state.get("enabled")))
        self.assertEqual(state.get("mode"), "network")
        self.assertEqual(float(state.get("rate") or 0.0), 1.0)

    def test_reset_request_chaos_disables_and_zeroes_rate(self) -> None:
        request_utils.configure_request_chaos(enabled=True, mode="timeout", rate=1.0)
        state = request_utils.reset_request_chaos()
        self.assertFalse(bool(state.get("enabled")))
        self.assertEqual(state.get("mode"), "timeout")
        self.assertEqual(float(state.get("rate")), 0.0)

    def test_async_make_request_can_inject_network_chaos(self) -> None:
        request_utils.configure_request_chaos(enabled=True, mode="network", rate=1.0, seed=42)
        result = asyncio.run(request_utils.async_make_request("POST", "https://example.com/test"))
        self.assertFalse(result.success)
        self.assertIn("baglanti", str(result.message or "").casefold())


if __name__ == "__main__":
    unittest.main()
