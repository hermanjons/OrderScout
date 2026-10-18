from __future__ import annotations

import os
import time
from typing import Any

import requests
from PyQt6.QtCore import QThread

from Feedback.processors.pipeline import Result, map_error_to_message


def _thread_sleep(seconds: float) -> None:
    QThread.msleep(max(1, int(float(seconds or 0.0) * 1000)))


def _normalize_release(payload: dict[str, Any]) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    for raw in (payload.get("assets") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        url = str(raw.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        assets.append(
            {
                "name": name,
                "download_url": url,
                "size": int(raw.get("size") or 0),
                "content_type": str(raw.get("content_type") or "").strip(),
                "updated_at": str(raw.get("updated_at") or "").strip(),
                "digest": str(raw.get("digest") or "").strip(),
            }
        )

    return {
        "id": payload.get("id"),
        "tag_name": str(payload.get("tag_name") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "published_at": str(payload.get("published_at") or "").strip(),
        "body": str(payload.get("body") or ""),
        "html_url": str(payload.get("html_url") or "").strip(),
        "prerelease": bool(payload.get("prerelease", False)),
        "draft": bool(payload.get("draft", False)),
        "assets": assets,
    }


def fetch_latest_release(
    *,
    owner: str,
    repo: str,
    include_prerelease: bool = False,
    api_base: str,
    timeout_sec: int,
    retry_count: int = 1,
    retry_backoff_sec: float = 0.0,
) -> Result:
    try:
        owner_name = str(owner or "").strip()
        repo_name = str(repo or "").strip()
        if not owner_name or not repo_name:
            return Result.fail("Update check failed: owner/repo is missing.", close_dialog=False)

        base = str(api_base or "").strip().rstrip("/")
        if not base:
            return Result.fail("Update check failed: api_base is missing.", close_dialog=False)
        try:
            timeout_value = int(timeout_sec)
        except Exception:
            return Result.fail("Update check failed: timeout_sec is invalid.", close_dialog=False)
        if timeout_value <= 0:
            return Result.fail("Update check failed: timeout_sec must be positive.", close_dialog=False)
        try:
            tries = int(retry_count)
        except Exception:
            return Result.fail("Update check failed: retry_count is invalid.", close_dialog=False)
        if tries <= 0:
            return Result.fail("Update check failed: retry_count must be positive.", close_dialog=False)
        try:
            backoff = float(retry_backoff_sec)
        except Exception:
            return Result.fail("Update check failed: retry_backoff_sec is invalid.", close_dialog=False)
        if backoff < 0:
            return Result.fail("Update check failed: retry_backoff_sec cannot be negative.", close_dialog=False)
        url = f"{base}/repos/{owner_name}/{repo_name}/releases"

        token = str(os.environ.get("ORDER_SCOUT_GITHUB_TOKEN") or "").strip()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "OrderScout-Updater",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        for attempt in range(1, tries + 1):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=max(5, timeout_value),
                )
            except Exception:
                if attempt >= tries:
                    raise
                if backoff > 0:
                    delay = min(15.0, backoff * (2 ** (attempt - 1)))
                    _thread_sleep(delay)
                continue

            status = int(response.status_code or 0)
            if status >= 400:
                retriable = status == 429 or status >= 500
                if retriable and attempt < tries:
                    if backoff > 0:
                        delay = min(15.0, backoff * (2 ** (attempt - 1)))
                        _thread_sleep(delay)
                    continue
                try:
                    details = response.json()
                    msg = str(details.get("message") or "").strip()
                except Exception:
                    msg = ""

                remaining_raw = str(response.headers.get("X-RateLimit-Remaining") or "").strip()
                reset_raw = str(response.headers.get("X-RateLimit-Reset") or "").strip()
                retry_after_raw = str(response.headers.get("Retry-After") or "").strip()

                remaining: int | None = None
                reset_epoch: int | None = None
                retry_after_sec: int | None = None
                try:
                    remaining = int(remaining_raw) if remaining_raw else None
                except Exception:
                    remaining = None
                try:
                    reset_epoch = int(reset_raw) if reset_raw else None
                except Exception:
                    reset_epoch = None
                try:
                    retry_after_sec = int(float(retry_after_raw)) if retry_after_raw else None
                except Exception:
                    retry_after_sec = None

                msg_lower = msg.lower()
                rate_limited = bool(
                    status in (403, 429)
                    and (
                        (remaining is not None and remaining <= 0)
                        or ("rate limit" in msg_lower)
                    )
                )
                if rate_limited:
                    now_epoch = int(time.time())
                    wait_candidates: list[int] = []
                    if retry_after_sec is not None and retry_after_sec > 0:
                        wait_candidates.append(retry_after_sec)
                    if reset_epoch is not None and reset_epoch > now_epoch:
                        wait_candidates.append(reset_epoch - now_epoch)
                    wait_sec = max(wait_candidates) if wait_candidates else 60
                    wait_sec = max(1, int(wait_sec))
                    return Result.fail(
                        (
                            "GitHub API hiz limiti asildi. "
                            f"Lutfen yaklasik {wait_sec} sn sonra tekrar dene."
                        ),
                        close_dialog=False,
                        data={
                            "rate_limited": True,
                            "retry_after_sec": wait_sec,
                            "rate_limit_remaining": remaining if remaining is not None else -1,
                            "rate_limit_reset_epoch": reset_epoch or 0,
                        },
                    )

                text = f"GitHub release API error ({status})."
                if msg:
                    text = f"{text} {msg}"
                return Result.fail(text, close_dialog=False)

            payload = response.json()
            if not isinstance(payload, list) or not payload:
                return Result.fail("No release found in update source.", close_dialog=False)

            selected: dict[str, Any] | None = None
            for raw in payload:
                if not isinstance(raw, dict):
                    continue
                if bool(raw.get("draft", False)):
                    continue
                if (not include_prerelease) and bool(raw.get("prerelease", False)):
                    continue
                selected = raw
                break

            if selected is None:
                return Result.fail("No eligible release found.", close_dialog=False)

            release = _normalize_release(selected)
            return Result.ok(
                "Latest release fetched.",
                close_dialog=False,
                data={"release": release},
            )

        return Result.fail("No eligible release found.", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
