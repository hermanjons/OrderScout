from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import Update.api.github_release_api as update_api


class _FakeResponse:
    def __init__(self, status_code: int, payload, headers: dict | None = None):
        self.status_code = int(status_code)
        self._payload = payload
        self.headers = dict(headers or {})

    def json(self):
        return self._payload


class TestUpdateApi(unittest.TestCase):
    def _release_payload(self, *, prerelease: bool = False) -> dict:
        return {
            "id": 101,
            "tag_name": "v0.2.0",
            "name": "OrderScout v0.2.0",
            "published_at": "2026-01-01T10:00:00Z",
            "body": "notes",
            "html_url": "https://example.test/release",
            "prerelease": prerelease,
            "draft": False,
            "assets": [
                {
                    "name": "OrderScout_Setup_x64.exe",
                    "browser_download_url": "https://example.test/OrderScout_Setup_x64.exe",
                    "size": 123,
                    "content_type": "application/x-msdownload",
                    "updated_at": "2026-01-01T10:00:00Z",
                    "digest": "sha256:" + ("a" * 64),
                }
            ],
        }

    def test_fetch_latest_release_retries_after_503(self) -> None:
        responses = [
            _FakeResponse(503, {"message": "temporary"}),
            _FakeResponse(200, [self._release_payload()]),
        ]
        with patch.object(update_api.requests, "get", side_effect=responses) as mocked_get, patch.object(
            update_api, "_thread_sleep"
        ) as mocked_sleep:
            res = update_api.fetch_latest_release(
                owner="x",
                repo="y",
                include_prerelease=False,
                api_base="https://api.github.com",
                timeout_sec=10,
                retry_count=2,
                retry_backoff_sec=0.01,
            )

        self.assertTrue(res.success, res.message)
        self.assertEqual(mocked_get.call_count, 2)
        mocked_sleep.assert_called_once()

    def test_fetch_latest_release_normalizes_asset_digest(self) -> None:
        with patch.object(
            update_api.requests,
            "get",
            return_value=_FakeResponse(200, [self._release_payload()]),
        ):
            res = update_api.fetch_latest_release(
                owner="x",
                repo="y",
                include_prerelease=False,
                api_base="https://api.github.com",
                timeout_sec=10,
            )

        self.assertTrue(res.success, res.message)
        release = (res.data or {}).get("release") or {}
        assets = release.get("assets") or []
        self.assertEqual(len(assets), 1)
        self.assertEqual(str(assets[0].get("digest")), "sha256:" + ("a" * 64))

    def test_fetch_latest_release_marks_rate_limit_with_retry_after(self) -> None:
        reset_epoch = int(time.time()) + 120
        payload = {"message": "API rate limit exceeded"}
        response = _FakeResponse(
            403,
            payload,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_epoch),
            },
        )
        with patch.object(update_api.requests, "get", return_value=response):
            res = update_api.fetch_latest_release(
                owner="x",
                repo="y",
                include_prerelease=False,
                api_base="https://api.github.com",
                timeout_sec=10,
            )

        self.assertFalse(res.success)
        data = res.data or {}
        self.assertTrue(bool(data.get("rate_limited")))
        retry_after = int(data.get("retry_after_sec") or 0)
        self.assertGreater(retry_after, 0)
        self.assertIn("hiz limiti", str(res.message).lower())

    def test_fetch_latest_release_sends_auth_header_when_env_token_exists(self) -> None:
        with patch.dict(update_api.os.environ, {"ORDER_SCOUT_GITHUB_TOKEN": "abc123"}, clear=False), patch.object(
            update_api.requests,
            "get",
            return_value=_FakeResponse(200, [self._release_payload()]),
        ) as mocked_get:
            res = update_api.fetch_latest_release(
                owner="x",
                repo="y",
                include_prerelease=False,
                api_base="https://api.github.com",
                timeout_sec=10,
            )

        self.assertTrue(res.success, res.message)
        self.assertIsNotNone(mocked_get.call_args)
        headers = mocked_get.call_args.kwargs.get("headers") or {}
        self.assertEqual(str(headers.get("Authorization") or ""), "Bearer abc123")


if __name__ == "__main__":
    unittest.main()
