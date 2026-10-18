from __future__ import annotations

import asyncio
import random
import weakref

import httpx

from Feedback.processors.pipeline import Result, map_error_to_message

_REQUEST_CHAOS_ENABLED = False
_REQUEST_CHAOS_MODE = "timeout"
_REQUEST_CHAOS_RATE = 0.0
_REQUEST_CHAOS_RANDOM = random.Random()
_REQUEST_CLIENTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = weakref.WeakKeyDictionary()
_REQUEST_LIMITS = httpx.Limits(max_connections=32, max_keepalive_connections=16, keepalive_expiry=30.0)


def _get_loop_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _REQUEST_CLIENTS.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(limits=_REQUEST_LIMITS)
        _REQUEST_CLIENTS[loop] = client
    return client


async def close_async_request_clients() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    client = _REQUEST_CLIENTS.pop(loop, None)
    if client is None:
        return
    try:
        await client.aclose()
    except Exception:
        pass


def _response_payload(response: httpx.Response | None) -> dict:
    if response is None:
        return {}
    try:
        payload = response.json()
    except Exception:
        payload = None
    return {
        "json": payload,
        "status_code": int(getattr(response, "status_code", 0) or 0),
        "url": str(getattr(response, "url", "") or ""),
    }


def configure_request_chaos(
    *,
    enabled: bool,
    mode: str = "timeout",
    rate: float = 0.30,
    seed: int | None = None,
) -> dict[str, object]:
    global _REQUEST_CHAOS_ENABLED, _REQUEST_CHAOS_MODE, _REQUEST_CHAOS_RATE
    _REQUEST_CHAOS_ENABLED = bool(enabled)
    _REQUEST_CHAOS_MODE = str(mode or "timeout").strip().lower() or "timeout"
    _REQUEST_CHAOS_RATE = max(0.0, min(1.0, float(rate or 0.0)))
    if seed is not None:
        _REQUEST_CHAOS_RANDOM.seed(int(seed))
    return request_chaos_state()


def reset_request_chaos() -> dict[str, object]:
    return configure_request_chaos(enabled=False, mode="timeout", rate=0.0)


def request_chaos_state() -> dict[str, object]:
    return {
        "enabled": bool(_REQUEST_CHAOS_ENABLED),
        "mode": str(_REQUEST_CHAOS_MODE),
        "rate": float(_REQUEST_CHAOS_RATE),
    }


def _maybe_raise_request_chaos(method: str, url: str) -> None:
    if not _REQUEST_CHAOS_ENABLED or _REQUEST_CHAOS_RATE <= 0.0:
        return
    if _REQUEST_CHAOS_RANDOM.random() >= _REQUEST_CHAOS_RATE:
        return

    request = httpx.Request(str(method or "GET"), str(url or ""))
    mode = str(_REQUEST_CHAOS_MODE or "timeout").strip().lower() or "timeout"
    if mode == "429":
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("Injected 429 chaos", request=request, response=response)
    if mode == "network":
        raise httpx.RequestError("Injected network chaos", request=request)
    raise httpx.TimeoutException("Injected timeout chaos")


async def async_make_request(
    method: str,
    url: str,
    headers=None,
    auth=None,
    params=None,
    data=None,
    json=None,
    timeout=15,
) -> Result:
    """Run one async HTTP request and return the shared Result shape."""
    try:
        _maybe_raise_request_chaos(method, url)
        client = _get_loop_client()
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            auth=auth,
            params=params,
            data=data,
            json=json,
            timeout=timeout,
        )
        response.raise_for_status()

        try:
            response_json = response.json()
        except Exception:
            response_json = None

        return Result.ok(
            f"{method} {url} istegi basarili.",
            close_dialog=False,
            data={
                "json": response_json,
                "status_code": response.status_code,
                "url": str(getattr(response, "url", "") or ""),
            },
        )

    except httpx.HTTPStatusError as e:
        msg = map_error_to_message(e)
        return Result.fail(
            f"{method} {url} istegi basarisiz: {msg}",
            error=e,
            close_dialog=False,
            data=_response_payload(getattr(e, "response", None)),
        )
    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(
            f"{method} {url} istegi basarisiz: {msg}",
            error=e,
            close_dialog=False,
        )
