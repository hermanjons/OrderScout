from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
from time import perf_counter as _invocation_clock
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from AI.processors.provider_adapters import (
    CallableProviderAdapter,
    ModelCapabilityProfile,
    NormalizedProviderError,
    ProviderAdapter,
    ProviderAdapterRegistry,
    capability_profile_from_record,
    guarded_json_prompt,
    normalize_provider_error,
)
from AI.processors.provider_catalog_policy import (
    gemini_model_is_verified_free_chat,
    gemini_safe_fallback_models,
)

ChatClient = Callable[[str], str]

DEFAULT_CLOUD_MAX_TOKENS = 2048
DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS = 8192
DEFAULT_FINAL_TEXT_MAX_TOKENS = DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS
# Guarded JSON remains the provider-independent recovery path for the same
# typed planning contract.  Reasoning-capable routes may spend part of the
# output envelope on hidden reasoning, so it must retain the structured-output
# budget; otherwise a valid exact-model plan can be truncated before the JSON
# closes and spuriously degrade into repair/fallback behavior.
DEFAULT_GUARDED_JSON_MAX_TOKENS = DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS
DEFAULT_CLOUD_TEMPERATURE = 0
DEFAULT_CLOUD_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_CLOUD_TURN_TIMEOUT_SECONDS = 180.0
MAX_CLOUD_TASK_TIMEOUT_SECONDS = 900.0
MAX_EXACT_MODEL_RATE_LIMIT_WAIT_SECONDS = 60
GEMINI_FALLBACK_MODELS = gemini_safe_fallback_models()
GEMINI_VALIDATED_FREE_MODEL = GEMINI_FALLBACK_MODELS[0]
GEMINI_MODEL_CATALOG_LIMIT = 24
OPENROUTER_VALIDATED_FREE_MODEL = "openai/gpt-oss-20b:free"

OPENAI_COMPATIBLE_PROVIDERS = {
    "openai",
    "openrouter",
    "groq",
    "together",
    "mistral",
    "custom",
}

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "mistral": "https://api.mistral.ai/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}

OPENROUTER_FALLBACK_MODELS = (
    OPENROUTER_VALIDATED_FREE_MODEL,
    "openai/gpt-oss-120b:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
)

_GEMINI_MODEL_PRIORITY = GEMINI_FALLBACK_MODELS


class CloudTurnDeadlineExceeded(requests.Timeout):
    """The shared turn budget ended; this is not a provider/model failure."""

    turn_deadline_exceeded = True


def _post_with_hard_wall_clock_timeout(
    url: str,
    *,
    timeout: float,
    turn_deadline_limited: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """Run one provider POST behind a true wall-clock deadline.

    ``requests`` applies its timeout to socket connect/read inactivity, not to
    the total response lifetime. A provider that keeps delivering partial
    bytes can therefore outlive the shared agent-turn deadline and leave the
    source UI worker blocked. The transport call runs in a daemon thread so
    the caller can fail closed at the exact wall-clock boundary. Provider
    retries and fallback policy remain in the owning invocation loop.
    """

    bounded_timeout = max(0.05, float(timeout or 0.0))
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def run_request() -> None:
        try:
            response = requests.post(
                url,
                timeout=bounded_timeout,
                **kwargs,
            )
        except Exception as exc:  # transported back to the owning thread
            result_queue.put((False, exc))
            return
        result_queue.put((True, response))

    worker = threading.Thread(
        target=run_request,
        name="orderscout-provider-post",
        daemon=True,
    )
    worker.start()
    worker.join(bounded_timeout)
    if worker.is_alive():
        if turn_deadline_limited:
            raise CloudTurnDeadlineExceeded(
                "Cloud provider request exceeded the shared wall-clock budget."
            )
        raise requests.Timeout(
            "Cloud provider request exceeded its phase wall-clock budget."
        )
    try:
        succeeded, value = result_queue.get_nowait()
    except queue.Empty as exc:
        raise CloudTurnDeadlineExceeded(
            "Cloud provider request ended without a transport result."
        ) from exc
    if not succeeded:
        raise value
    return value


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def begin_provider_chat_turn(
    client: ChatClient | None,
    *,
    timeout: float = DEFAULT_CLOUD_TURN_TIMEOUT_SECONDS,
) -> ChatClient | None:
    """Start one shared wall-clock budget for all provider calls in a turn."""

    if client is None:
        return None
    turn_timeout = max(1.0, float(timeout or 0.0))
    setattr(client, "turn_timeout_seconds", turn_timeout)
    started = time.monotonic()
    setattr(client, "turn_started_monotonic", started)
    setattr(
        client,
        "turn_deadline_monotonic",
        started + turn_timeout,
    )
    resource_plan = dict(getattr(client, "resource_plan", {}) or {})
    resource_plan["turn_timeout_seconds"] = turn_timeout
    resource_plan["turn_deadline_active"] = True
    resource_plan["task_budget_reserved"] = False
    resource_plan["task_deadline_active"] = False
    resource_plan.pop("task_timeout_seconds", None)
    resource_plan.pop("task_step_budget", None)
    setattr(client, "resource_plan", resource_plan)
    return client


def reserve_provider_task_budget(client: ChatClient, *, max_steps: int) -> None:
    """Reserve one bounded task deadline without resetting it during replans."""
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 64:
        raise ValueError("task_step_budget_invalid")
    plan = dict(getattr(client, "resource_plan", {}) or {})
    if plan.get("task_budget_reserved") is True:
        return
    if not hasattr(client, "turn_started_monotonic"):
        begin_provider_chat_turn(client)
        plan = dict(getattr(client, "resource_plan", {}) or {})
    started = float(getattr(client, "turn_started_monotonic"))
    base = float(getattr(client, "turn_timeout_seconds", DEFAULT_CLOUD_TURN_TIMEOUT_SECONDS))
    # An agent task has several provider calls, unlike an ordinary chat reply.
    # The step/replan counters remain independent limits and request timeouts
    # remain bounded. Reserving again cannot extend the same task indefinitely.
    seconds = min(MAX_CLOUD_TASK_TIMEOUT_SECONDS,
                  max(base, DEFAULT_CLOUD_REQUEST_TIMEOUT_SECONDS * (max_steps + 2)))
    setattr(client, "turn_deadline_monotonic", started + seconds)
    plan.update({"task_budget_reserved": True, "task_timeout_seconds": seconds,
                 "task_step_budget": max_steps, "task_deadline_active": True})
    setattr(client, "resource_plan", plan)


def _effective_provider_request_timeout(
    client: ChatClient,
    configured_timeout: float,
    *,
    invocation_contract: str = "",
) -> float:
    request_timeout = max(0.05, float(configured_timeout or 0.0))
    try:
        deadline = float(getattr(client, "turn_deadline_monotonic"))
    except (AttributeError, TypeError, ValueError):
        plan = getattr(client, "resource_plan", {})
        if isinstance(plan, dict):
            plan["request_timeout_seconds"] = request_timeout
            plan["request_timeout_turn_limited"] = False
            setattr(client, "resource_plan", plan)
        return request_timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0.05:
        raise CloudTurnDeadlineExceeded(
            "Cloud turn deadline exceeded before provider request."
        )
    effective = min(request_timeout, remaining)
    plan = getattr(client, "resource_plan", {})
    guarded_recovery_available = bool(
        isinstance(plan, dict)
        and plan.get("guarded_json_recovery_available") is True
    )
    if (
        _compact_text(invocation_contract).casefold()
        == "structured_output"
        and guarded_recovery_available
    ):
        # Native schema transport is an optimization, not permission to consume
        # the entire multi-phase agent turn.  Reserve five sixths of the current
        # wall-clock budget for the same-model guarded contract, GoalPlan repair,
        # final synthesis and verification.  A healthy structured route still
        # gets a bounded request; a slow/broken one can degrade without starving
        # the user-visible answer.
        structured_ceiling = max(5.0, remaining / 6.0)
        effective = min(effective, structured_ceiling)
        if isinstance(plan, dict):
            plan["structured_output_request_timeout_seconds"] = effective
            plan["structured_output_recovery_reserve_seconds"] = max(
                0.0,
                remaining - effective,
            )
            setattr(client, "resource_plan", plan)
    if isinstance(plan, dict):
        plan["request_timeout_seconds"] = effective
        plan["request_timeout_turn_limited"] = bool(
            effective >= max(0.05, remaining - 0.05)
        )
        setattr(client, "resource_plan", plan)
    return effective


def _last_request_timeout_turn_limited(client: ChatClient) -> bool:
    plan = getattr(client, "resource_plan", {})
    return bool(
        isinstance(plan, dict)
        and plan.get("request_timeout_turn_limited") is True
    )


def _safe_optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _normalized_error_evidence(
    value: NormalizedProviderError | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Whitelist the only provider-error fields allowed in runtime evidence."""

    if isinstance(value, NormalizedProviderError):
        payload = value.to_dict()
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        return {}
    category = _compact_text(payload.get("category")).casefold()
    if not category:
        return {}
    retry_after_seconds = _safe_optional_int(payload.get("retry_after_seconds"))
    if retry_after_seconds is not None:
        retry_after_seconds = min(max(0, retry_after_seconds), 86_400)
    return {
        "provider_code": _compact_text(payload.get("provider_code")).casefold(),
        "category": category,
        "retryable": bool(payload.get("retryable")),
        "quota_scope": _compact_text(payload.get("quota_scope")).casefold(),
        "status_code": _safe_optional_int(payload.get("status_code")),
        "safe_message": _compact_text(payload.get("safe_message")),
        "model_fallback_allowed": bool(payload.get("model_fallback_allowed")),
        "retry_after_seconds": retry_after_seconds,
    }


def _fallback_blocked_reason_for(
    normalized_error: NormalizedProviderError | Mapping[str, Any] | None,
) -> str:
    row = _normalized_error_evidence(normalized_error)
    if not row or row.get("model_fallback_allowed") is True:
        return ""
    category = _compact_text(row.get("category")).casefold()
    if category == "quota":
        if _compact_text(row.get("quota_scope")).casefold() == "free_tier":
            return "free_tier_quota"
        return "provider_quota"
    if category in {"billing", "auth", "policy"}:
        return f"provider_{category}"
    if category == "turn_deadline":
        return "turn_deadline_exceeded"
    return "model_fallback_disallowed"


def _structured_output_rejected(exc: Exception) -> bool:
    """Return true only for errors that explicitly reject structured output.

    OpenRouter also uses HTTP 400 for broken upstream routes (for example an
    upstream provider credential failure).  Retrying those errors with the
    same model and a different response contract only duplicates a request and
    obscures the actual route failure.
    """

    response = getattr(exc, "response", None)
    payload: Any = None
    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
    try:
        error_text = json.dumps(payload, ensure_ascii=False).casefold()
    except Exception:
        error_text = _compact_text(payload).casefold()
    if not error_text:
        error_text = _compact_text(exc).casefold()
    contract_tokens = (
        "response_format",
        "response format",
        "json_schema",
        "json schema",
        "structured output",
        "structured_outputs",
    )
    rejection_tokens = (
        "reject",
        "unsupported",
        "not supported",
        "invalid",
        "not available",
        "unrecognized",
    )
    return any(token in error_text for token in contract_tokens) and any(
        token in error_text for token in rejection_tokens
    )


_CHAT_TEMPLATE_EDGE_TOKENS = (
    "</|turn>",
    "<|end_of_turn|>",
    "<end_of_turn>",
    "<|eot_id|>",
    "<|im_end|>",
    "<|endoftext|>",
    "</s>",
)


def _strip_chat_template_edge_tokens(value: Any) -> str:
    """Remove model-template sentinels only when they leak at response edges."""

    text = _compact_text(value)
    changed = True
    while text and changed:
        changed = False
        for token in _CHAT_TEMPLATE_EDGE_TOKENS:
            if text.startswith(token):
                text = text[len(token) :].strip()
                changed = True
            if text.endswith(token):
                text = text[: -len(token)].strip()
                changed = True
    return text


SENSITIVE_QUERY_KEYS = {"key", "api_key", "apikey", "token", "access_token"}


def _redact_url_secrets(url: Any) -> str:
    text = str(url or "")
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            clean_key = key.casefold()
            query.append((key, "***" if clean_key in SENSITIVE_QUERY_KEYS else value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        redacted = text
        for key in SENSITIVE_QUERY_KEYS:
            redacted = _redact_query_secret(redacted, key)
        return redacted


def _redact_query_secret(text: str, key: str) -> str:
    import re

    return re.sub(rf"([?&]{re.escape(key)}=)[^&\s]+", rf"\1***", text, flags=re.IGNORECASE)


def raise_for_status_safely(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        safe_url = _redact_url_secrets(getattr(response, "url", ""))
        status = getattr(response, "status_code", "")
        reason = _compact_text(getattr(response, "reason", ""))
        prefix = ""
        if int(status or 0) == 429:
            retry_after = _compact_text(getattr(response, "headers", {}).get("Retry-After") if hasattr(response, "headers") else "")
            prefix = "Cloud LLM rate limit/quota siniri asildi"
            if retry_after:
                prefix = f"{prefix}; retry-after={retry_after}"
        if safe_url and status:
            label = f"{status} Client Error"
            if reason:
                label = f"{label}: {reason}"
            message = f"{label} for url: {safe_url}"
        else:
            message = str(exc)
            for key in SENSITIVE_QUERY_KEYS:
                message = _redact_query_secret(message, key)
        if prefix:
            message = f"{prefix}. {message}"
        raise requests.HTTPError(message, response=response) from exc


def _json(response: requests.Response) -> dict[str, Any]:
    raise_for_status_safely(response)
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _join_endpoint(base_url: str, suffix: str) -> str:
    base = _compact_text(base_url).rstrip("/")
    if not base:
        return suffix
    if base.endswith(suffix):
        return base
    return f"{base}/{suffix.lstrip('/')}"


def _append_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in params.items():
        if value and key not in query:
            query[key] = value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _extract_openai_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return _strip_chat_template_edge_tokens(content)
    if isinstance(content, list):
        parts = [
            _compact_text(part.get("text") if isinstance(part, dict) else part)
            for part in content
        ]
        return _strip_chat_template_edge_tokens(
            "\n".join(part for part in parts if part)
        )
    return _strip_chat_template_edge_tokens(first.get("text"))


def _wire_tool_name(value: Any, *, used: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "_", _compact_text(value)).strip("_")[:64]
    if not base:
        base = "orderscout_tool"
    candidate = base
    suffix = 2
    while candidate in used:
        marker = f"_{suffix}"
        candidate = f"{base[: max(1, 64 - len(marker))]}{marker}"
        suffix += 1
    used.add(candidate)
    return candidate


def _provider_tool_definitions(
    tools: list[dict[str, Any]],
    *,
    family: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    definitions: list[dict[str, Any]] = []
    wire_to_source: dict[str, str] = {}
    used: set[str] = set()
    if len(tools or []) > 128:
        raise ValueError("Tool catalog exceeds the transport window; discover and load a bounded menu first")
    for row in list(tools or []):
        if not isinstance(row, dict):
            continue
        source_name = _compact_text(row.get("name"))
        if not source_name:
            continue
        wire_name = _wire_tool_name(source_name, used=used)
        wire_to_source[wire_name] = source_name
        parameters = (
            dict(row.get("parameters") or {})
            if isinstance(row.get("parameters"), dict)
            else {"type": "object", "properties": {}, "additionalProperties": False}
        )
        description = _compact_text(row.get("description"))
        if family == "anthropic":
            definitions.append(
                {
                    "name": wire_name,
                    "description": description,
                    "input_schema": parameters,
                }
            )
        elif family == "gemini":
            definitions.append(
                {
                    "name": wire_name,
                    "description": description,
                    "parameters": parameters,
                }
            )
        else:
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": wire_name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
    return definitions, wire_to_source


def _normalized_tool_decision(calls: list[dict[str, Any]]) -> str:
    clean_calls = [row for row in calls if isinstance(row, dict) and _compact_text(row.get("tool"))]
    if not clean_calls:
        return ""
    if len(clean_calls) == 1:
        row = clean_calls[0]
        return json.dumps(
            {
                "mode": "tool",
                "tool": row.get("tool"),
                "arguments": dict(row.get("arguments") or {}),
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"mode": "tools", "calls": clean_calls},
        ensure_ascii=False,
    )


def _record_invocation_contract(client: ChatClient, contract: str) -> None:
    clean_contract = _compact_text(contract) or "text"
    plan = getattr(client, "resource_plan", {})
    if not isinstance(plan, dict):
        return
    history = [
        _compact_text(value)
        for value in list(plan.get("invocation_contract_history") or [])
        if _compact_text(value)
    ]
    history.append(clean_contract)
    plan["last_invocation_contract"] = clean_contract
    plan["invocation_contract_history"] = history
    setattr(client, "_invocation_started_at", _invocation_clock())
    setattr(client, "resource_plan", plan)


def _record_invocation_outcome(
    client: ChatClient,
    *,
    contract: str,
    requested_model: str,
    actual_model: str = "",
    response_received: bool,
    error_reason: str = "",
    fallback_used: bool = False,
    normalized_error: NormalizedProviderError | Mapping[str, Any] | None = None,
    normalized_error_history: list[
        NormalizedProviderError | Mapping[str, Any]
    ]
    | None = None,
    fallback_blocked_reason: str = "",
    fallback_attempts: list[Mapping[str, Any]] | None = None,
) -> None:
    """Keep append-only per-call provenance across a multi-invocation turn."""

    plan = getattr(client, "resource_plan", {})
    if not isinstance(plan, dict):
        return
    safe_error_history = [
        safe
        for value in list(normalized_error_history or [])
        if (safe := _normalized_error_evidence(value))
    ]
    safe_final_error = _normalized_error_evidence(normalized_error)
    if (
        safe_final_error
        and (
            not safe_error_history
            or safe_error_history[-1] != safe_final_error
        )
    ):
        safe_error_history.append(safe_final_error)
    if response_received:
        safe_final_error = {}
    elif not safe_final_error and safe_error_history:
        safe_final_error = dict(safe_error_history[-1])
    safe_attempts = [
        {
            "model": _compact_text(value.get("model")),
            "reason": _compact_text(value.get("reason")),
        }
        for value in list(fallback_attempts or [])
        if isinstance(value, Mapping)
        and (
            _compact_text(value.get("model"))
            or _compact_text(value.get("reason"))
        )
    ]
    row = {
        "contract": _compact_text(contract) or "text",
        "requested_model": _compact_text(requested_model),
        "actual_model": _compact_text(actual_model),
        "response_received": bool(response_received),
        "error_reason": _compact_text(error_reason),
        "fallback_used": bool(fallback_used),
        "error_category": _compact_text(safe_final_error.get("category")),
        "quota_scope": _compact_text(safe_final_error.get("quota_scope")),
        "status_code": safe_final_error.get("status_code"),
        "model_fallback_allowed": (
            bool(safe_final_error.get("model_fallback_allowed"))
            if safe_final_error
            else None
        ),
        "fallback_blocked_reason": _compact_text(fallback_blocked_reason),
        "retry_after_seconds": safe_final_error.get("retry_after_seconds"),
        "normalized_error_history": safe_error_history,
        "fallback_attempts": safe_attempts,
    }
    started_at = getattr(client, "_invocation_started_at", None)
    if isinstance(started_at, (int, float)):
        row["duration_seconds"] = round(max(0.0, _invocation_clock() - started_at), 6)
        setattr(client, "_invocation_started_at", None)
    history = [
        dict(value)
        for value in list(plan.get("invocation_outcome_history") or [])
        if isinstance(value, dict)
    ]
    history.append(row)
    successful_models: list[str] = []
    for value in history:
        model = _compact_text(value.get("actual_model"))
        if bool(value.get("response_received")) and model and model not in successful_models:
            successful_models.append(model)
    plan["invocation_outcome_history"] = history
    plan["model_response_count"] = sum(
        1 for value in history if bool(value.get("response_received"))
    )
    plan["any_model_response_received"] = bool(plan["model_response_count"])
    plan["any_model_fallback_used"] = any(
        bool(value.get("fallback_used")) for value in history
    )
    plan["successful_actual_models"] = successful_models
    plan["last_successful_actual_model"] = (
        successful_models[-1] if successful_models else ""
    )
    plan["final_model_response_received"] = bool(row["response_received"])
    plan["final_invocation_error_reason"] = row["error_reason"]
    plan["final_error_category"] = row["error_category"]
    plan["final_quota_scope"] = row["quota_scope"]
    plan["final_status_code"] = row["status_code"]
    plan["final_model_fallback_allowed"] = row["model_fallback_allowed"]
    plan["final_fallback_blocked_reason"] = row[
        "fallback_blocked_reason"
    ]
    plan["final_retry_after_seconds"] = row["retry_after_seconds"]
    setattr(client, "resource_plan", plan)


def provider_invocation_provenance(
    resource_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project one authoritative view of a multi-invocation provider turn.

    ``actual_model`` and ``invocation_error_reason`` describe only the latest
    invocation.  A task turn can contain interpretation, planning and response
    synthesis calls, so consumers must not use those last-write fields as the
    history aggregate.  This projection keeps legacy single-call plans
    readable while making append-only outcome history authoritative whenever
    it exists.
    """

    plan = dict(resource_plan or {})
    history = [
        {
            "contract": _compact_text(row.get("contract")) or "text",
            **({"duration_seconds": row["duration_seconds"]}
               if isinstance(row.get("duration_seconds"), (int, float))
               and not isinstance(row.get("duration_seconds"), bool)
               and row["duration_seconds"] >= 0 else {}),
            "requested_model": _compact_text(row.get("requested_model")),
            "actual_model": _compact_text(row.get("actual_model")),
            "response_received": bool(row.get("response_received")),
            "error_reason": _compact_text(row.get("error_reason")),
            "fallback_used": bool(row.get("fallback_used")),
            "error_category": _compact_text(
                row.get("error_category")
            ).casefold(),
            "quota_scope": _compact_text(row.get("quota_scope")).casefold(),
            "status_code": _safe_optional_int(row.get("status_code")),
            "model_fallback_allowed": (
                bool(row.get("model_fallback_allowed"))
                if row.get("model_fallback_allowed") is not None
                else None
            ),
            "fallback_blocked_reason": _compact_text(
                row.get("fallback_blocked_reason")
            ),
            "retry_after_seconds": _safe_optional_int(
                row.get("retry_after_seconds")
            ),
            "normalized_error_history": [
                safe
                for value in list(
                    row.get("normalized_error_history") or []
                )
                if (safe := _normalized_error_evidence(value))
            ],
            "fallback_attempts": [
                {
                    "model": _compact_text(value.get("model")),
                    "reason": _compact_text(value.get("reason")),
                }
                for value in list(row.get("fallback_attempts") or [])
                if isinstance(value, Mapping)
                and (
                    _compact_text(value.get("model"))
                    or _compact_text(value.get("reason"))
                )
            ],
        }
        for row in list(plan.get("invocation_outcome_history") or [])
        if isinstance(row, dict)
    ]
    if history:
        response_rows = [row for row in history if row["response_received"]]
        successful_models = list(
            dict.fromkeys(
                row["actual_model"]
                for row in response_rows
                if row["actual_model"]
            )
        )
        final_row = history[-1]
        model_response_count = len(response_rows)
        final_model_response_received = bool(final_row["response_received"])
        final_actual_model = (
            final_row["actual_model"]
            if final_model_response_received
            else ""
        )
        final_error_reason = final_row["error_reason"]
        final_fallback_used = bool(final_row["fallback_used"])
        final_error_category = final_row["error_category"]
        final_quota_scope = final_row["quota_scope"]
        final_status_code = final_row["status_code"]
        final_model_fallback_allowed = final_row[
            "model_fallback_allowed"
        ]
        final_fallback_blocked_reason = final_row[
            "fallback_blocked_reason"
        ]
        final_retry_after_seconds = final_row["retry_after_seconds"]
        requested_model = _compact_text(
            plan.get("requested_model")
            or final_row["requested_model"]
        )
    else:
        legacy_actual_model = _compact_text(plan.get("actual_model"))
        explicit_any_response = plan.get("any_model_response_received")
        explicit_final_response = plan.get("final_model_response_received")
        if explicit_final_response is not None:
            final_model_response_received = bool(explicit_final_response)
        elif explicit_any_response is not None:
            final_model_response_received = bool(
                explicit_any_response
                and legacy_actual_model
                and not _compact_text(plan.get("invocation_error_reason"))
            )
        else:
            final_model_response_received = bool(
                legacy_actual_model
                and not _compact_text(plan.get("invocation_error_reason"))
            )
        any_model_response_received = bool(
            explicit_any_response
            if explicit_any_response is not None
            else final_model_response_received
        )
        try:
            model_response_count = int(
                plan.get("model_response_count")
                or (1 if any_model_response_received else 0)
            )
        except (TypeError, ValueError):
            model_response_count = 1 if any_model_response_received else 0
        model_response_count = max(0, model_response_count)
        last_successful = _compact_text(
            plan.get("last_successful_actual_model")
            or (legacy_actual_model if any_model_response_received else "")
        )
        successful_models = [
            _compact_text(value)
            for value in list(plan.get("successful_actual_models") or [])
            if _compact_text(value)
        ]
        if last_successful and last_successful not in successful_models:
            successful_models.append(last_successful)
        final_actual_model = (
            legacy_actual_model if final_model_response_received else ""
        )
        final_error_reason = _compact_text(
            plan.get("final_invocation_error_reason")
            or plan.get("invocation_error_reason")
        )
        final_fallback_used = bool(plan.get("fallback_used"))
        legacy_errors = [
            safe
            for value in list(plan.get("normalized_error_history") or [])
            if (safe := _normalized_error_evidence(value))
        ]
        final_error = legacy_errors[-1] if legacy_errors else {}
        final_error_category = _compact_text(
            plan.get("final_error_category")
            or final_error.get("category")
        ).casefold()
        final_quota_scope = _compact_text(
            plan.get("final_quota_scope")
            or final_error.get("quota_scope")
            or plan.get("quota_scope")
        ).casefold()
        final_status_code = _safe_optional_int(
            plan.get("final_status_code")
            if plan.get("final_status_code") is not None
            else final_error.get("status_code")
        )
        final_model_fallback_allowed = (
            bool(plan.get("final_model_fallback_allowed"))
            if plan.get("final_model_fallback_allowed") is not None
            else (
                bool(final_error.get("model_fallback_allowed"))
                if final_error
                else None
            )
        )
        final_fallback_blocked_reason = _compact_text(
            plan.get("final_fallback_blocked_reason")
            or plan.get("fallback_blocked_reason")
        )
        final_retry_after_seconds = _safe_optional_int(
            plan.get("final_retry_after_seconds")
            if plan.get("final_retry_after_seconds") is not None
            else final_error.get("retry_after_seconds")
        )
        requested_model = _compact_text(plan.get("requested_model"))

    any_model_response_received = bool(model_response_count)
    last_successful_actual_model = (
        successful_models[-1] if successful_models else ""
    )
    any_model_fallback_used = (
        any(bool(row["fallback_used"]) for row in history)
        if history
        else bool(plan.get("any_model_fallback_used") or final_fallback_used)
    )
    normalized_error_history = [
        dict(error)
        for row in history
        for error in list(row.get("normalized_error_history") or [])
        if isinstance(error, dict)
    ]
    if not history:
        normalized_error_history = [
            safe
            for value in list(plan.get("normalized_error_history") or [])
            if (safe := _normalized_error_evidence(value))
        ]
    return {
        "requested_model": requested_model,
        "actual_model": last_successful_actual_model,
        "last_successful_actual_model": last_successful_actual_model,
        "final_actual_model": final_actual_model,
        "model_response_count": model_response_count,
        "any_model_response_received": any_model_response_received,
        "final_model_response_received": final_model_response_received,
        "successful_actual_models": successful_models,
        "any_model_fallback_used": any_model_fallback_used,
        "final_fallback_used": final_fallback_used,
        "final_invocation_error_reason": final_error_reason,
        "final_error_category": final_error_category,
        "final_quota_scope": final_quota_scope,
        "final_status_code": final_status_code,
        "final_model_fallback_allowed": final_model_fallback_allowed,
        "final_fallback_blocked_reason": final_fallback_blocked_reason,
        "final_retry_after_seconds": final_retry_after_seconds,
        "normalized_error_history": normalized_error_history,
        "invocation_outcome_history": history,
    }


def provider_invocation_turn_plan(
    resource_plan: Mapping[str, Any] | None,
    *,
    outcome_start: int = 0,
    contract_start: int = 0,
) -> dict[str, Any]:
    """Return a resource-plan copy scoped to invocations after turn start."""

    plan = dict(resource_plan or {})
    all_outcomes = [
        dict(row)
        for row in list(plan.get("invocation_outcome_history") or [])
        if isinstance(row, dict)
    ]
    all_contracts = [
        _compact_text(value)
        for value in list(plan.get("invocation_contract_history") or [])
        if _compact_text(value)
    ]
    try:
        outcome_index = max(0, int(outcome_start or 0))
    except (TypeError, ValueError):
        outcome_index = 0
    try:
        contract_index = max(0, int(contract_start or 0))
    except (TypeError, ValueError):
        contract_index = 0
    turn_outcomes = all_outcomes[outcome_index:]
    turn_contracts = all_contracts[contract_index:]
    if turn_outcomes:
        # Outcome contracts are the authoritative per-call ledger.  Keep the
        # independently recorded contract list only when it matches that
        # ledger; otherwise expose the mismatch for the acceptance validator.
        plan["invocation_outcome_history"] = turn_outcomes
        plan["invocation_contract_history"] = turn_contracts
        provenance = provider_invocation_provenance(plan)
        plan.update(
            {
                "requested_model": provenance["requested_model"],
                "actual_model": provenance["final_actual_model"],
                "last_successful_actual_model": provenance[
                    "last_successful_actual_model"
                ],
                "successful_actual_models": provenance[
                    "successful_actual_models"
                ],
                "model_response_count": provenance["model_response_count"],
                "any_model_response_received": provenance[
                    "any_model_response_received"
                ],
                "final_model_response_received": provenance[
                    "final_model_response_received"
                ],
                "any_model_fallback_used": provenance[
                    "any_model_fallback_used"
                ],
                "fallback_used": provenance["final_fallback_used"],
                "invocation_error_reason": provenance[
                    "final_invocation_error_reason"
                ],
                "final_invocation_error_reason": provenance[
                    "final_invocation_error_reason"
                ],
                "final_error_category": provenance[
                    "final_error_category"
                ],
                "quota_scope": provenance["final_quota_scope"],
                "final_quota_scope": provenance["final_quota_scope"],
                "final_status_code": provenance["final_status_code"],
                "final_model_fallback_allowed": provenance[
                    "final_model_fallback_allowed"
                ],
                "fallback_blocked_reason": provenance[
                    "final_fallback_blocked_reason"
                ],
                "final_fallback_blocked_reason": provenance[
                    "final_fallback_blocked_reason"
                ],
                "final_retry_after_seconds": provenance[
                    "final_retry_after_seconds"
                ],
                "normalized_error_history": provenance[
                    "normalized_error_history"
                ],
                "model_invocation_attempted": True,
            }
        )
        return plan

    if all_outcomes:
        # The shared client has older calls, but this turn made none.  Do not
        # let their successful model or failure status leak into this turn.
        plan.update(
            {
                "actual_model": "",
                "last_successful_actual_model": "",
                "successful_actual_models": [],
                "model_response_count": 0,
                "any_model_response_received": False,
                "final_model_response_received": False,
                "any_model_fallback_used": False,
                "fallback_used": False,
                "invocation_error_reason": "",
                "final_invocation_error_reason": "",
                "final_error_category": "",
                "quota_scope": "",
                "final_quota_scope": "",
                "final_status_code": None,
                "final_model_fallback_allowed": None,
                "fallback_blocked_reason": "",
                "final_fallback_blocked_reason": "",
                "final_retry_after_seconds": None,
                "normalized_error_history": [],
                "model_invocation_attempted": False,
                "invocation_outcome_history": [],
                "invocation_contract_history": turn_contracts,
            }
        )
    return plan


def _extract_openai_tool_decision(
    payload: dict[str, Any],
    *,
    wire_to_source: dict[str, str],
) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    raw_calls = message.get("tool_calls")
    calls: list[dict[str, Any]] = []
    if isinstance(raw_calls, list):
        for row in raw_calls:
            function = row.get("function") if isinstance(row, dict) else None
            if not isinstance(function, dict):
                continue
            wire_name = _compact_text(function.get("name"))
            source_name = wire_to_source.get(wire_name, "")
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except Exception:
                    arguments = {}
            calls.append(
                {
                    "tool": source_name,
                    "arguments": dict(arguments or {}) if isinstance(arguments, dict) else {},
                }
            )
    normalized = _normalized_tool_decision(calls)
    return normalized or _extract_openai_text(payload)


def _extract_anthropic_tool_decision(
    payload: dict[str, Any],
    *,
    wire_to_source: dict[str, str],
) -> str:
    content = payload.get("content")
    calls: list[dict[str, Any]] = []
    if isinstance(content, list):
        for part in content[:16]:
            if not isinstance(part, dict) or _compact_text(part.get("type")) != "tool_use":
                continue
            wire_name = _compact_text(part.get("name"))
            calls.append(
                {
                    "tool": wire_to_source.get(wire_name, ""),
                    "arguments": (
                        dict(part.get("input") or {})
                        if isinstance(part.get("input"), dict)
                        else {}
                    ),
                }
            )
    return _normalized_tool_decision(calls) or _extract_anthropic_text(payload)


def _extract_anthropic_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, list):
        return _strip_chat_template_edge_tokens(
            "\n".join(
                _compact_text(part.get("text"))
                for part in content
                if isinstance(part, dict) and _compact_text(part.get("text"))
            )
        )
    return _strip_chat_template_edge_tokens(payload.get("completion"))


def _extract_anthropic_structured_output(
    payload: dict[str, Any],
    *,
    tool_name: str,
) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    for part in content:
        if (
            isinstance(part, dict)
            and _compact_text(part.get("type")) == "tool_use"
            and _compact_text(part.get("name")) == tool_name
            and isinstance(part.get("input"), dict)
        ):
            return json.dumps(part.get("input"), ensure_ascii=False)
    return ""


def _openai_response_format(schema: dict[str, Any] | None) -> dict[str, Any]:
    clean_schema = dict(schema or {})
    if not clean_schema:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "orderscout_planner_output",
            "strict": True,
            "schema": clean_schema,
        },
    }


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else {}
    parts = content.get("parts") if isinstance(content, dict) else []
    if not isinstance(parts, list):
        return ""
    return _strip_chat_template_edge_tokens(
        "\n".join(
            _compact_text(part.get("text"))
            for part in parts
            if (
                isinstance(part, dict)
                and not bool(part.get("thought"))
                and _compact_text(part.get("text"))
            )
        )
    )


def _gemini_response_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates")
    candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
    content = candidate.get("content") if isinstance(candidate, dict) else {}
    parts = content.get("parts") if isinstance(content, dict) else []
    clean_parts = [part for part in parts if isinstance(part, dict)] if isinstance(parts, list) else []
    usage = payload.get("usageMetadata") if isinstance(payload.get("usageMetadata"), dict) else {}
    return {
        "finish_reason": _compact_text(candidate.get("finishReason")) if isinstance(candidate, dict) else "",
        "part_count": len(clean_parts),
        "thought_part_count": sum(bool(part.get("thought")) for part in clean_parts),
        "text_part_count": sum(bool(_compact_text(part.get("text"))) for part in clean_parts),
        "prompt_token_count": int(usage.get("promptTokenCount") or 0),
        "candidate_token_count": int(usage.get("candidatesTokenCount") or 0),
        "thought_token_count": int(usage.get("thoughtsTokenCount") or 0),
        "total_token_count": int(usage.get("totalTokenCount") or 0),
    }


def _extract_gemini_tool_decision(
    payload: dict[str, Any],
    *,
    wire_to_source: dict[str, str],
) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else {}
    parts = content.get("parts") if isinstance(content, dict) else []
    calls: list[dict[str, Any]] = []
    if isinstance(parts, list):
        for part in parts[:16]:
            function_call = part.get("functionCall") if isinstance(part, dict) else None
            if not isinstance(function_call, dict):
                continue
            wire_name = _compact_text(function_call.get("name"))
            arguments = function_call.get("args")
            calls.append(
                {
                    "tool": wire_to_source.get(wire_name, ""),
                    "arguments": dict(arguments or {}) if isinstance(arguments, dict) else {},
                }
            )
    return _normalized_tool_decision(calls) or _extract_gemini_text(payload)


def _gemini_structured_generation_config(
    model: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Return the generateContent schema dialect supported by the model family.

    Gemini 3 uses the current responseFormat envelope. Gemini 2.x and older
    aliases keep the previous responseMimeType/responseSchema contract.
    """

    normalized_model = _compact_text(model).casefold().removeprefix("models/")
    if re.match(r"^gemini-3(?:[.-]|$)", normalized_model):
        return {
            "responseFormat": {
                "text": {
                    # responseFormat uses the v1beta enum, unlike the legacy
                    # responseMimeType string field used by Gemini 2.x.
                    "mimeType": "APPLICATION_JSON",
                    "schema": dict(schema),
                }
            }
        }

    def _legacy_schema(value: Any) -> Any:
        """Translate strict JSON Schema into Gemini 2.x's supported subset.

        The legacy ``responseSchema`` protobuf rejects ``additionalProperties``
        as an unknown field, including when it appears in nested objects. The
        application still parses and validates the returned object against the
        original strict schema, so removing only the unsupported wire keyword
        does not weaken the authoritative contract boundary.
        """

        if isinstance(value, dict):
            return {
                key: _legacy_schema(item)
                for key, item in value.items()
                if key != "additionalProperties"
            }
        if isinstance(value, list):
            return [_legacy_schema(item) for item in value]
        return value

    return {
        "responseMimeType": "application/json",
        "responseSchema": _legacy_schema(dict(schema)),
    }


def _extract_gemini_catalog_model_ids(payload: dict[str, Any]) -> list[str]:
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        return []
    model_ids: list[str] = []
    for row in raw_models:
        if not isinstance(row, dict):
            continue
        methods = row.get("supportedGenerationMethods")
        if isinstance(methods, list) and "generateContent" not in [str(item) for item in methods]:
            continue
        model_id = _compact_text(row.get("name")).removeprefix("models/")
        if (
            model_id
            and gemini_model_is_verified_free_chat(model_id)
            and model_id not in model_ids
        ):
            model_ids.append(model_id)
    return sorted(
        model_ids,
        key=lambda model_id: (
            _GEMINI_MODEL_PRIORITY.index(model_id)
            if model_id in _GEMINI_MODEL_PRIORITY
            else len(_GEMINI_MODEL_PRIORITY),
            model_id,
        ),
    )


def _fetch_gemini_catalog_model_ids(*, base_url: str, api_key: str, timeout: float) -> list[str]:
    clean_key = _compact_text(api_key)
    if not clean_key:
        return []
    endpoint = _append_query(_join_endpoint(base_url or DEFAULT_BASE_URLS["gemini"], "models"), key=clean_key)
    try:
        response = _json(requests.get(endpoint, headers={"Accept": "application/json"}, timeout=min(float(timeout or 45), 45.0)))
    except Exception:
        return []
    return _extract_gemini_catalog_model_ids(response)[:GEMINI_MODEL_CATALOG_LIMIT]


def _bounded_int(value: Any, *, default: int, minimum: int = 64, maximum: int = 8192) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _bounded_float(value: Any, *, default: float, minimum: float = 0.0, maximum: float = 2.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def provider_reasoning_capabilities(
    provider_code: str,
    model: str,
    *,
    model_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = _compact_text(provider_code).casefold()
    model_id = _compact_text(model).casefold().removeprefix("models/")
    metadata = dict(model_metadata or {})
    if provider == "gemini":
        if model_id.startswith("gemini-3") or model_id in {
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
        }:
            return {
                "supported": True,
                "control": "thinking_level",
                "efforts": ["auto", "low", "medium", "high"],
                "off_supported": False,
                "mandatory": True,
            }
        if model_id.startswith("gemini-2.5"):
            off_supported = "pro" not in model_id
            return {
                "supported": True,
                "control": "thinking_budget",
                "efforts": ["auto", *(["off"] if off_supported else []), "low", "medium", "high"],
                "off_supported": off_supported,
                "mandatory": not off_supported,
            }
        return {"supported": False, "control": "", "efforts": ["auto"], "off_supported": False, "mandatory": False}

    if provider == "openrouter":
        supported_parameters = {
            _compact_text(value).casefold()
            for value in list(metadata.get("supported_parameters") or [])
            if _compact_text(value)
        }
        reasoning_meta = dict(metadata.get("reasoning") or {}) if isinstance(metadata.get("reasoning"), dict) else {}
        inferred = any(
            token in model_id
            for token in ("gpt-oss", "reason", "deepseek-r1", "qwen-r1", "nemotron")
        )
        supported = bool("reasoning" in supported_parameters or reasoning_meta or inferred)
        supported_efforts = [
            _compact_text(value).casefold()
            for value in list(reasoning_meta.get("supported_efforts") or [])
            if _compact_text(value)
        ]
        efforts = ["auto"]
        mandatory = bool(reasoning_meta.get("mandatory"))
        if supported and not mandatory:
            efforts.append("off")
        for effort in ("low", "medium", "high"):
            if not supported_efforts or effort in supported_efforts:
                efforts.append(effort)
        return {
            "supported": supported,
            "control": "reasoning_effort" if supported else "",
            "efforts": efforts if supported else ["auto"],
            "off_supported": supported and not mandatory,
            "mandatory": mandatory,
            "default_effort": _compact_text(reasoning_meta.get("default_effort")).casefold() or "auto",
        }

    return {"supported": False, "control": "", "efforts": ["auto"], "off_supported": False, "mandatory": False}


def _normalized_reasoning_effort(value: Any, capabilities: dict[str, Any]) -> str:
    effort = _compact_text(value).casefold() or "auto"
    allowed = list(capabilities.get("efforts") or ["auto"])
    return effort if effort in allowed else "auto"


def _gemini_thinking_config(model: str, effort: str) -> dict[str, Any]:
    capabilities = provider_reasoning_capabilities("gemini", model)
    effort = _normalized_reasoning_effort(effort, capabilities)
    if not capabilities.get("supported") or effort == "auto":
        return {}
    if capabilities.get("control") == "thinking_level":
        return {"thinkingLevel": effort}
    budgets = {"off": 0, "low": 512, "medium": 2048, "high": 8192}
    return {"thinkingBudget": budgets.get(effort, -1)}


def build_openai_compatible_client(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 600.0,
    extra_headers: dict[str, str] | None = None,
    request_options: dict[str, Any] | None = None,
    fallback_models: tuple[str, ...] | list[str] | None = None,
    provider_code: str = "openai",
    model_metadata: dict[str, Any] | None = None,
    fallback_model_metadata: dict[str, dict[str, Any]] | None = None,
    native_tool_runtime_enabled: bool = False,
    structured_output_runtime_enabled: bool = False,
) -> ChatClient | None:
    clean_model = _compact_text(model)
    clean_base = _compact_text(base_url)
    if not clean_model or not clean_base:
        return None
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    clean_key = _compact_text(api_key)
    if clean_key:
        headers["Authorization"] = f"Bearer {clean_key}"
    headers.update(dict(extra_headers or {}))
    endpoint = _join_endpoint(clean_base, "chat/completions")
    options = dict(request_options or {})
    metadata_by_model = {
        _compact_text(key).removeprefix("models/"): dict(value)
        for key, value in dict(fallback_model_metadata or {}).items()
        if _compact_text(key) and isinstance(value, dict)
    }
    metadata_by_model[clean_model.removeprefix("models/")] = dict(model_metadata or {})

    def _metadata_for(candidate: str) -> dict[str, Any]:
        return dict(metadata_by_model.get(candidate.removeprefix("models/")) or {})

    def _supported_parameters(candidate: str) -> set[str]:
        return {
            _compact_text(value).casefold()
            for value in list(_metadata_for(candidate).get("supported_parameters") or [])
            if _compact_text(value)
        }
    max_tokens = _bounded_int(
        options.pop("max_tokens", options.pop("max_output_tokens", DEFAULT_CLOUD_MAX_TOKENS)),
        default=DEFAULT_CLOUD_MAX_TOKENS,
    )
    temperature = _bounded_float(options.pop("temperature", DEFAULT_CLOUD_TEMPERATURE), default=DEFAULT_CLOUD_TEMPERATURE)
    model_candidates: list[str] = []
    for candidate in (clean_model, *(fallback_models or ())):
        clean_candidate = _compact_text(candidate)
        if clean_candidate and clean_candidate not in model_candidates:
            model_candidates.append(clean_candidate)

    def _invoke(
        prompt: str,
        *,
        payload_overrides: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None,
        response_extractor: Callable[[dict[str, Any]], str] = _extract_openai_text,
        invocation_contract: str = "text",
        required_capability: str = "",
    ) -> str:
        last_error: Exception | None = None
        fallback_attempts: list[dict[str, Any]] = []
        normalized_error_history: list[dict[str, Any]] = []
        request_prompt_hashes: list[dict[str, str]] = []
        same_model_empty_retries: list[dict[str, Any]] = []
        same_model_retry_events: list[dict[str, Any]] = []
        prompt_hash = hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()
        initial_plan = getattr(_client, "resource_plan", {})
        prior_same_model_empty_retry_history = (
            [
                dict(row)
                for row in list(
                    initial_plan.get(
                        "same_model_empty_retry_history"
                    )
                    or []
                )
                if isinstance(row, dict)
            ]
            if isinstance(initial_plan, dict)
            else []
        )
        if isinstance(initial_plan, dict):
            initial_plan.update(
                {
                    "requested_model": clean_model,
                    "actual_model": "",
                    "fallback_used": False,
                    "model_invocation_attempted": True,
                    "invocation_error_reason": "",
                    "same_model_empty_retries": [],
                    "same_model_retry_events": [],
                }
            )
            setattr(_client, "resource_plan", initial_plan)
        _record_invocation_contract(_client, invocation_contract)
        for candidate in model_candidates:
            candidate_metadata = _metadata_for(candidate)
            candidate_profile = capability_profile_from_record(
                {
                    "provider_code": provider_code,
                    "default_model": candidate,
                    "model_metadata": candidate_metadata,
                },
                reasoning=provider_reasoning_capabilities(
                    provider_code,
                    candidate,
                    model_metadata=candidate_metadata,
                ),
            )
            capability_compatible = (
                required_capability != "native_tools"
                or candidate_profile.native_tool_calling_available
            ) and (
                required_capability != "structured_output"
                or candidate_profile.structured_output_available
            )
            if not capability_compatible:
                reason = f"capability_incompatible:{required_capability}"
                fallback_attempts.append({"model": candidate, "reason": reason})
                last_error = RuntimeError(
                    f"Cloud model gerekli yetenegi desteklemiyor: {candidate} ({required_capability})"
                )
                plan = getattr(_client, "resource_plan", {})
                if isinstance(plan, dict):
                    plan["invocation_error_reason"] = reason
                    plan["fallback_attempts"] = list(fallback_attempts)
                    setattr(_client, "resource_plan", plan)
                continue
            payload = {
                "model": candidate,
                "messages": [{"role": "user", "content": str(prompt or "")}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            payload.update(options)
            resolved_overrides = (
                payload_overrides(candidate)
                if callable(payload_overrides)
                else dict(payload_overrides or {})
            )
            payload.update(dict(resolved_overrides or {}))
            try:
                answer = ""
                exact_model_empty_retry_limit = (
                    0
                    if invocation_contract == "structured_output"
                    else 1
                    if len(model_candidates) == 1
                    and candidate == clean_model
                    else 0
                )
                exact_model_request_attempt_limit = (
                    1
                    if invocation_contract == "structured_output"
                    else 3
                    if len(model_candidates) == 1
                    and candidate == clean_model
                    else 1
                )
                empty_retry_count = 0
                for request_attempt in range(exact_model_request_attempt_limit):
                    request_prompt_record: dict[str, Any] = {
                        "model": candidate,
                        "prompt_sha256": prompt_hash,
                    }
                    if exact_model_request_attempt_limit > 1:
                        request_prompt_record["attempt"] = request_attempt + 1
                    request_prompt_hashes.append(request_prompt_record)
                    try:
                        request_timeout = _effective_provider_request_timeout(
                            _client,
                            timeout,
                            invocation_contract=invocation_contract,
                        )
                        response_payload = _json(
                            _post_with_hard_wall_clock_timeout(
                                endpoint,
                                headers=headers,
                                json=payload,
                                timeout=request_timeout,
                                turn_deadline_limited=(
                                    _last_request_timeout_turn_limited(_client)
                                ),
                            )
                        )
                    except requests.RequestException as retry_exc:
                        retry_error = normalize_provider_error(
                            provider_code,
                            retry_exc,
                        )
                        same_model_retry_allowed = bool(
                            request_attempt + 1
                            < exact_model_request_attempt_limit
                            and retry_error.retryable
                            and (
                                retry_error.category == "transport"
                                or retry_error.status_code
                                in {500, 502, 503, 504}
                            )
                            # Unknown/project/model rate-limit scopes require
                            # their own bounded wait/fallback policy.  A blind
                            # immediate 429 retry would only burn the turn.
                            and retry_error.status_code != 429
                        )
                        if not same_model_retry_allowed:
                            raise
                        normalized_error_history.append(
                            retry_error.to_dict()
                        )
                        same_model_retry_events.append(
                            {
                                "model": candidate,
                                "attempt": request_attempt + 1,
                                "reason": (
                                    f"http_{retry_error.status_code}"
                                    if retry_error.status_code
                                    else retry_error.category
                                ),
                                "invocation_contract": invocation_contract,
                                "prompt_sha256": prompt_hash,
                            }
                        )
                        continue
                    answer = response_extractor(response_payload)
                    if _compact_text(answer):
                        break
                    if empty_retry_count < exact_model_empty_retry_limit:
                        empty_retry_count += 1
                        same_model_empty_retries.append(
                            {
                                "model": candidate,
                                "reason": "empty_response",
                                "attempt": request_attempt + 1,
                                "invocation_contract": invocation_contract,
                                "prompt_sha256": prompt_hash,
                            }
                        )
                        continue
                    break
            except requests.RequestException as exc:
                last_error = exc
                status = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
                normalized_error = normalize_provider_error(provider_code, exc)
                normalized_error_history.append(normalized_error.to_dict())
                error_reason = (
                    "turn_deadline_exceeded"
                    if normalized_error.category == "turn_deadline"
                    else "transport_error" if not status else f"http_{status}"
                )
                fallback_attempts.append(
                    {
                        "model": candidate,
                        "reason": error_reason,
                    }
                )
                plan = getattr(_client, "resource_plan", {})
                if isinstance(plan, dict):
                    plan["invocation_error_reason"] = fallback_attempts[-1]["reason"]
                    plan["fallback_attempts"] = list(fallback_attempts)
                    plan["normalized_error_history"] = list(normalized_error_history)
                    plan["quota_scope"] = normalized_error.quota_scope
                    plan["fallback_blocked_reason"] = (
                        _fallback_blocked_reason_for(normalized_error)
                    )
                    plan["request_prompt_hashes"] = list(request_prompt_hashes)
                    plan["same_model_empty_retries"] = list(
                        same_model_empty_retries
                    )
                    plan["same_model_retry_events"] = list(
                        same_model_retry_events
                    )
                    plan["same_model_empty_retry_history"] = [
                        *prior_same_model_empty_retry_history,
                        *same_model_empty_retries,
                    ][-100:]
                    setattr(_client, "resource_plan", plan)
                if (
                    not normalized_error.model_fallback_allowed
                    or candidate == model_candidates[-1]
                ):
                    _record_invocation_outcome(
                        _client,
                        contract=invocation_contract,
                        requested_model=clean_model,
                        response_received=False,
                        error_reason=fallback_attempts[-1]["reason"],
                        fallback_used=candidate != clean_model,
                        normalized_error=normalized_error,
                        normalized_error_history=normalized_error_history,
                        fallback_blocked_reason=(
                            _fallback_blocked_reason_for(normalized_error)
                        ),
                        fallback_attempts=fallback_attempts,
                    )
                    raise
                continue
            if not _compact_text(answer):
                last_error = RuntimeError(f"Cloud model bos cevap dondurdu: {candidate}")
                fallback_attempts.append({"model": candidate, "reason": "empty_response"})
                plan = getattr(_client, "resource_plan", {})
                if isinstance(plan, dict):
                    plan["invocation_error_reason"] = "empty_response"
                    plan["fallback_attempts"] = list(
                        fallback_attempts
                    )
                    plan["request_prompt_hashes"] = list(
                        request_prompt_hashes
                    )
                    plan["same_model_empty_retries"] = list(
                        same_model_empty_retries
                    )
                    plan["same_model_retry_events"] = list(
                        same_model_retry_events
                    )
                    plan["same_model_empty_retry_history"] = [
                        *prior_same_model_empty_retry_history,
                        *same_model_empty_retries,
                    ][-100:]
                    setattr(_client, "resource_plan", plan)
                if candidate == model_candidates[-1]:
                    _record_invocation_outcome(
                        _client,
                        contract=invocation_contract,
                        requested_model=clean_model,
                        response_received=False,
                        error_reason="empty_response",
                        fallback_used=candidate != clean_model,
                        fallback_attempts=fallback_attempts,
                    )
                    raise last_error
                continue
            setattr(_client, "model_name", candidate)
            plan = getattr(_client, "resource_plan", {})
            if isinstance(plan, dict):
                actual_reasoning = provider_reasoning_capabilities(
                    provider_code,
                    candidate,
                    model_metadata=candidate_metadata,
                )
                actual_profile = capability_profile_from_record(
                    {
                        "provider_code": provider_code,
                        "default_model": candidate,
                        "model_metadata": candidate_metadata,
                    },
                    reasoning=actual_reasoning,
                    native_tool_runtime_enabled=native_tool_runtime_enabled,
                    structured_output_runtime_enabled=structured_output_runtime_enabled,
                )
                plan["requested_model"] = clean_model
                plan["actual_model"] = candidate
                plan["fallback_used"] = candidate != clean_model
                plan["fallback_attempts"] = list(fallback_attempts)
                plan["normalized_error_history"] = list(normalized_error_history)
                plan["request_prompt_hashes"] = list(request_prompt_hashes)
                plan["same_model_empty_retries"] = list(
                    same_model_empty_retries
                )
                plan["same_model_retry_events"] = list(
                    same_model_retry_events
                )
                plan["same_model_empty_retry_history"] = [
                    *prior_same_model_empty_retry_history,
                    *same_model_empty_retries,
                ][-100:]
                plan["quota_scope"] = ""
                plan["fallback_blocked_reason"] = ""
                plan["invocation_error_reason"] = ""
                plan["reasoning_capabilities"] = actual_reasoning
                plan["capability_profile"] = actual_profile.to_dict()
                plan["degradation_mode"] = actual_profile.degradation_mode
                setattr(_client, "resource_plan", plan)
            _record_invocation_outcome(
                _client,
                contract=invocation_contract,
                requested_model=clean_model,
                actual_model=candidate,
                response_received=True,
                fallback_used=candidate != clean_model,
                normalized_error_history=normalized_error_history,
                fallback_attempts=fallback_attempts,
            )
            return answer
        if last_error is not None:
            _record_invocation_outcome(
                _client,
                contract=invocation_contract,
                requested_model=clean_model,
                response_received=False,
                error_reason=_compact_text(
                    dict(getattr(_client, "resource_plan", {}) or {}).get(
                        "invocation_error_reason"
                    )
                ),
                normalized_error_history=[
                    dict(row)
                    for row in list(
                        dict(
                            getattr(_client, "resource_plan", {}) or {}
                        ).get("normalized_error_history")
                        or []
                    )
                    if isinstance(row, dict)
                ],
                fallback_blocked_reason=_compact_text(
                    dict(
                        getattr(_client, "resource_plan", {}) or {}
                    ).get("fallback_blocked_reason")
                ),
                fallback_attempts=fallback_attempts,
            )
            raise last_error
        return ""

    def _client(prompt: str) -> str:
        return _invoke(prompt)

    def _invoke_structured(prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        def guarded_json_fallback(reason: str) -> str:
            plan = getattr(_client, "resource_plan", {})
            if isinstance(plan, dict):
                plan["structured_output_fallback_reason"] = reason
                plan["structured_output_fallback_contract"] = (
                    "same_exact_model_json_text_guarded"
                )
                setattr(_client, "resource_plan", plan)
            answer = _invoke_json_text(prompt, schema=schema)
            return answer

        try:
            answer = _invoke(
                prompt,
                payload_overrides=lambda candidate: {
                    "max_tokens": max(max_tokens, DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS),
                    "response_format": _openai_response_format(
                        schema
                        if _supported_parameters(candidate).intersection(
                            {"json_schema", "structured_outputs"}
                        )
                        else None
                    )
                },
                invocation_contract="structured_output",
                required_capability="structured_output",
            )
            if schema:
                try:
                    json.loads(answer)
                except (ValueError, TypeError):
                    return guarded_json_fallback("invalid_structured_json")
            return answer
        except requests.RequestException as exc:
            status = int(
                getattr(getattr(exc, "response", None), "status_code", 0)
                or 0
            )
            if (
                isinstance(exc, requests.Timeout)
                and not isinstance(exc, CloudTurnDeadlineExceeded)
            ):
                return guarded_json_fallback(
                    "structured_request_timeout"
                )
            if (
                provider_code != "openrouter"
                or status not in {400, 422}
                or not _structured_output_rejected(exc)
            ):
                raise
            # OpenRouter's live model metadata may advertise structured output
            # while a concrete free route rejects response_format/json_schema.
            # Retry once on the same exact model through guarded JSON text;
            # application-side schema parsing/validation remains mandatory.
            return guarded_json_fallback(f"http_{status}")
        except RuntimeError:
            plan = getattr(_client, "resource_plan", {})
            if (
                provider_code != "openrouter"
                or not isinstance(plan, dict)
                or _compact_text(plan.get("invocation_error_reason"))
                != "empty_response"
            ):
                raise
            # A route may accept response_format yet return no visible content.
            # Repeating the identical structured contract can consume the
            # complete shared turn deadline without adding evidence. Keep the
            # exact selected model and immediately use guarded JSON text;
            # downstream JSON/schema/operation validation remains authoritative.
            return guarded_json_fallback("empty_structured_response")

    def _invoke_json_text(prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        prompt = guarded_json_prompt(prompt, schema)
        guarded_max_tokens = max(
            max_tokens,
            DEFAULT_GUARDED_JSON_MAX_TOKENS,
        )
        plan = getattr(_client, "resource_plan", {})
        if isinstance(plan, dict):
            plan["guarded_json_max_tokens"] = guarded_max_tokens
            setattr(_client, "resource_plan", plan)

        def guarded_overrides(candidate: str) -> dict[str, Any]:
            overrides: dict[str, Any] = {
                "max_tokens": guarded_max_tokens,
            }
            if provider_code == "openrouter":
                reasoning = provider_reasoning_capabilities(
                    provider_code,
                    candidate,
                    model_metadata=_metadata_for(candidate),
                )
                if reasoning.get("supported"):
                    overrides["reasoning"] = {
                        "effort": (
                            "none"
                            if reasoning.get("off_supported")
                            and not reasoning.get("mandatory")
                            else "low"
                        ),
                        "exclude": True,
                    }
            return overrides

        return _invoke(
            prompt,
            payload_overrides=guarded_overrides,
            invocation_contract="json_text_guarded",
        )

    def _invoke_final_text(prompt: str) -> str:
        """Render a verified final projection without hidden-reasoning starvation.

        Reasoning-capable OpenRouter models may spend the ordinary 2K text
        envelope entirely on excluded reasoning and return an empty visible
        message.  Final synthesis is already grounded in typed authoritative
        observations and independently verified, so it needs output headroom,
        not another expensive planning pass.
        """

        final_max_tokens = max(max_tokens, DEFAULT_FINAL_TEXT_MAX_TOKENS)
        plan = getattr(_client, "resource_plan", {})
        if isinstance(plan, dict):
            plan["final_text_max_tokens"] = final_max_tokens
            setattr(_client, "resource_plan", plan)

        def final_overrides(candidate: str) -> dict[str, Any]:
            overrides: dict[str, Any] = {"max_tokens": final_max_tokens}
            if provider_code != "openrouter":
                return overrides
            reasoning = provider_reasoning_capabilities(
                provider_code,
                candidate,
                model_metadata=_metadata_for(candidate),
            )
            if not reasoning.get("supported"):
                return overrides
            if reasoning.get("off_supported") and not reasoning.get("mandatory"):
                effort = "none"
            else:
                supported_efforts = list(reasoning.get("efforts") or [])
                effort = next(
                    (
                        value
                        for value in ("low", "medium", "high")
                        if value in supported_efforts
                    ),
                    "high",
                )
            overrides["reasoning"] = {
                "effort": effort,
                "exclude": True,
            }
            current_plan = getattr(_client, "resource_plan", {})
            if isinstance(current_plan, dict):
                current_plan["final_text_reasoning_effort"] = effort
                current_plan["final_text_reasoning_disabled"] = effort == "none"
                setattr(_client, "resource_plan", current_plan)
            return overrides

        return _invoke(
            prompt,
            payload_overrides=final_overrides,
            invocation_contract="final_text",
        )

    def _invoke_tools(prompt: str, *, tools: list[dict[str, Any]]) -> str:
        definitions, wire_to_source = _provider_tool_definitions(
            tools,
            family="openai",
        )
        if not definitions:
            return _invoke(prompt)
        return _invoke(
            prompt,
            payload_overrides={
                "tools": definitions,
                "tool_choice": "auto",
            },
            response_extractor=lambda payload: _extract_openai_tool_decision(
                payload,
                wire_to_source=wire_to_source,
            ),
            invocation_contract="native_tools",
            required_capability="native_tools",
        )

    setattr(_client, "invoke_structured", _invoke_structured)
    setattr(_client, "invoke_json_text", _invoke_json_text)
    setattr(_client, "invoke_final_text", _invoke_final_text)
    setattr(_client, "invoke_tools", _invoke_tools)

    return _client


def _build_anthropic_client(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float,
    request_options: dict[str, Any] | None = None,
) -> ChatClient | None:
    clean_model = _compact_text(model)
    clean_key = _compact_text(api_key)
    if not clean_model or not clean_key:
        return None
    endpoint = _join_endpoint(base_url or DEFAULT_BASE_URLS["anthropic"], "messages")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": clean_key,
        "anthropic-version": "2023-06-01",
    }
    options = dict(request_options or {})
    max_tokens = _bounded_int(
        options.pop("max_tokens", options.pop("max_output_tokens", DEFAULT_CLOUD_MAX_TOKENS)),
        default=DEFAULT_CLOUD_MAX_TOKENS,
    )
    temperature = _bounded_float(options.pop("temperature", DEFAULT_CLOUD_TEMPERATURE), default=DEFAULT_CLOUD_TEMPERATURE)

    def _invoke(
        prompt: str,
        *,
        payload_overrides: dict[str, Any] | None = None,
        response_extractor: Callable[[dict[str, Any]], str] = _extract_anthropic_text,
        invocation_contract: str = "text",
    ) -> str:
        plan = getattr(_client, "resource_plan", {})
        if isinstance(plan, dict):
            plan.update(
                {
                    "requested_model": clean_model,
                    "actual_model": "",
                    "fallback_used": False,
                    "model_invocation_attempted": True,
                    "invocation_error_reason": "",
                    "request_prompt_hashes": [
                        {
                            "model": clean_model,
                            "prompt_sha256": hashlib.sha256(
                                str(prompt or "").encode("utf-8")
                            ).hexdigest(),
                        }
                    ],
                }
            )
            setattr(_client, "resource_plan", plan)
        _record_invocation_contract(_client, invocation_contract)
        payload = {
            "model": clean_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": str(prompt or "")}],
        }
        payload.update(options)
        payload.update(dict(payload_overrides or {}))
        try:
            request_timeout = _effective_provider_request_timeout(
                _client,
                timeout,
                invocation_contract=invocation_contract,
            )
            response = _json(
                _post_with_hard_wall_clock_timeout(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=request_timeout,
                    turn_deadline_limited=(
                        _last_request_timeout_turn_limited(_client)
                    ),
                )
            )
            answer = response_extractor(response)
        except requests.RequestException as exc:
            normalized_error = normalize_provider_error("anthropic", exc)
            plan = getattr(_client, "resource_plan", {})
            if isinstance(plan, dict):
                plan["invocation_error_reason"] = (
                    f"http_{normalized_error.status_code}"
                    if normalized_error.status_code
                    else normalized_error.category
                )
                plan["normalized_error_history"] = [normalized_error.to_dict()]
                plan["quota_scope"] = normalized_error.quota_scope
                plan["fallback_blocked_reason"] = (
                    _fallback_blocked_reason_for(normalized_error)
                )
                setattr(_client, "resource_plan", plan)
            _record_invocation_outcome(
                _client,
                contract=invocation_contract,
                requested_model=clean_model,
                response_received=False,
                error_reason=(
                    f"http_{normalized_error.status_code}"
                    if normalized_error.status_code
                    else normalized_error.category
                ),
                normalized_error=normalized_error,
                normalized_error_history=[normalized_error],
                fallback_blocked_reason=(
                    _fallback_blocked_reason_for(normalized_error)
                ),
            )
            raise
        plan = getattr(_client, "resource_plan", {})
        if isinstance(plan, dict):
            plan["actual_model"] = clean_model
            plan["fallback_used"] = False
            plan["invocation_error_reason"] = ""
            plan["normalized_error_history"] = []
            plan["quota_scope"] = ""
            plan["fallback_blocked_reason"] = ""
            setattr(_client, "resource_plan", plan)
        _record_invocation_outcome(
            _client,
            contract=invocation_contract,
            requested_model=clean_model,
            actual_model=clean_model,
            response_received=bool(_compact_text(answer)),
            error_reason="" if _compact_text(answer) else "empty_response",
        )
        return answer

    def _client(prompt: str) -> str:
        return _invoke(prompt)

    def _invoke_structured(prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        tool_name = "orderscout_structured_output"
        clean_schema = dict(schema or {}) or {
            "type": "object",
            "additionalProperties": True,
        }
        return _invoke(
            prompt,
            payload_overrides={
                "tools": [
                    {
                        "name": tool_name,
                        "description": "Return the validated OrderScout planner output.",
                        "input_schema": clean_schema,
                    }
                ],
                "tool_choice": {"type": "tool", "name": tool_name},
            },
            response_extractor=lambda payload: _extract_anthropic_structured_output(
                payload,
                tool_name=tool_name,
            ),
            invocation_contract="structured_output",
        )

    def _invoke_tools(prompt: str, *, tools: list[dict[str, Any]]) -> str:
        definitions, wire_to_source = _provider_tool_definitions(
            tools,
            family="anthropic",
        )
        if not definitions:
            return _invoke(prompt)
        return _invoke(
            prompt,
            payload_overrides={
                "tools": definitions,
                "tool_choice": {"type": "auto"},
            },
            response_extractor=lambda payload: _extract_anthropic_tool_decision(
                payload,
                wire_to_source=wire_to_source,
            ),
            invocation_contract="native_tools",
        )

    setattr(_client, "invoke_structured", _invoke_structured)
    setattr(_client, "invoke_tools", _invoke_tools)

    return _client


def _build_gemini_client(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float,
    request_options: dict[str, Any] | None = None,
    fallback_models: tuple[str, ...] | list[str] | None = None,
    native_tool_runtime_enabled: bool = False,
    structured_output_runtime_enabled: bool = False,
) -> ChatClient | None:
    clean_model = _compact_text(model)
    clean_key = _compact_text(api_key)
    if not clean_model or not clean_key:
        return None
    base = _compact_text(base_url) or DEFAULT_BASE_URLS["gemini"]
    options = dict(request_options or {})
    allow_fallback = bool(options.pop("allow_fallback", True))
    try:
        max_rate_limit_wait_seconds = int(
            options.pop(
                "max_exact_model_rate_limit_wait_seconds",
                MAX_EXACT_MODEL_RATE_LIMIT_WAIT_SECONDS,
            )
        )
    except (TypeError, ValueError):
        max_rate_limit_wait_seconds = MAX_EXACT_MODEL_RATE_LIMIT_WAIT_SECONDS
    max_rate_limit_wait_seconds = max(
        0,
        min(
            MAX_EXACT_MODEL_RATE_LIMIT_WAIT_SECONDS,
            max_rate_limit_wait_seconds,
        ),
    )
    reasoning_effort = _compact_text(options.pop("reasoning_effort", "auto")).casefold() or "auto"
    generation_config = dict(options.pop("generationConfig", {}) or {})
    generation_config.setdefault(
        "maxOutputTokens",
        _bounded_int(
            options.pop("maxOutputTokens", options.pop("max_tokens", options.pop("max_output_tokens", DEFAULT_CLOUD_MAX_TOKENS))),
            default=DEFAULT_CLOUD_MAX_TOKENS,
        ),
    )
    generation_config.setdefault(
        "temperature",
        _bounded_float(options.pop("temperature", DEFAULT_CLOUD_TEMPERATURE), default=DEFAULT_CLOUD_TEMPERATURE),
    )
    static_model_candidates: list[str] = []
    configured_candidates = (
        (clean_model, *(fallback_models or GEMINI_FALLBACK_MODELS))
        if allow_fallback
        else (clean_model,)
    )
    for candidate in configured_candidates:
        clean_candidate = _compact_text(candidate).removeprefix("models/")
        if clean_candidate and clean_candidate not in static_model_candidates:
            static_model_candidates.append(clean_candidate)
    catalog_model_candidates: list[str] | None = None

    def _model_candidates() -> list[str]:
        nonlocal catalog_model_candidates
        if not allow_fallback:
            return list(static_model_candidates)
        if catalog_model_candidates is None:
            catalog_model_candidates = _fetch_gemini_catalog_model_ids(base_url=base, api_key=clean_key, timeout=timeout)
        candidates = list(static_model_candidates)
        if allow_fallback:
            for candidate in catalog_model_candidates:
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _invoke(
        prompt: str,
        *,
        generation_config_overrides: dict[str, Any] | None = None,
        generation_config_factory: Callable[[str], dict[str, Any]] | None = None,
        payload_overrides: dict[str, Any] | None = None,
        response_extractor: Callable[[dict[str, Any]], str] = _extract_gemini_text,
        invocation_contract: str = "text",
    ) -> str:
        last_error: requests.RequestException | None = None
        fallback_attempts: list[dict[str, Any]] = []
        same_model_retry_events: list[dict[str, Any]] = []
        normalized_error_history: list[dict[str, Any]] = []
        request_prompt_hashes: list[dict[str, str]] = []
        prompt_hash = hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()
        model_candidates = _model_candidates()
        if invocation_contract in {"structured_output", "native_tools"}:
            model_candidates = [
                candidate
                for candidate in model_candidates
                if candidate.casefold().startswith("gemini-")
            ]
        if not model_candidates:
            raise RuntimeError(
                f"Gemini model bu planner sozlesmesini desteklemiyor: {clean_model}"
            )
        initial_plan = getattr(_client, "resource_plan", {})
        if isinstance(initial_plan, dict):
            initial_plan.update(
                {
                    "requested_model": clean_model,
                    "actual_model": "",
                    "fallback_used": False,
                    "model_invocation_attempted": True,
                    "invocation_error_reason": "",
                }
            )
            setattr(_client, "resource_plan", initial_plan)
        _record_invocation_contract(_client, invocation_contract)
        for endpoint_model in model_candidates:
            candidate_generation_config = dict(generation_config)
            thinking_config = _gemini_thinking_config(endpoint_model, reasoning_effort)
            if thinking_config:
                candidate_generation_config["thinkingConfig"] = thinking_config
            candidate_generation_config.update(
                dict(generation_config_overrides or {})
            )
            if generation_config_factory is not None:
                candidate_generation_config.update(
                    dict(generation_config_factory(endpoint_model) or {})
                )
            payload = {
                "contents": [{"role": "user", "parts": [{"text": str(prompt or "")}]}],
                "generationConfig": candidate_generation_config,
            }
            payload.update(options)
            payload.update(dict(payload_overrides or {}))
            if ":generateContent" in base:
                endpoint = base
            else:
                endpoint = _join_endpoint(base, f"models/{endpoint_model}:generateContent")
            endpoint = _append_query(endpoint, key=clean_key)
            try:
                max_same_model_attempts = (
                    1
                    if invocation_contract == "structured_output"
                    else 3
                    if not allow_fallback
                    else 1
                )
                answer = ""
                for attempt_index in range(max_same_model_attempts):
                    request_prompt_hashes.append(
                        {
                            "model": endpoint_model,
                            "prompt_sha256": prompt_hash,
                            "attempt": attempt_index + 1,
                        }
                    )
                    try:
                        request_timeout = _effective_provider_request_timeout(
                            _client,
                            timeout,
                            invocation_contract=invocation_contract,
                        )
                        response = _json(
                            _post_with_hard_wall_clock_timeout(
                                endpoint,
                                headers={"Content-Type": "application/json"},
                                json=payload,
                                timeout=request_timeout,
                                turn_deadline_limited=(
                                    _last_request_timeout_turn_limited(_client)
                                ),
                            )
                        )
                        answer = response_extractor(response)
                        if _compact_text(answer):
                            break
                        if attempt_index + 1 < max_same_model_attempts:
                            same_model_retry_events.append(
                                {
                                    "model": endpoint_model,
                                    "attempt": attempt_index + 1,
                                    "reason": "empty_response",
                                }
                            )
                    except requests.RequestException as retry_exc:
                        retry_error = normalize_provider_error("gemini", retry_exc)
                        retry_wait_seconds: int | None = None
                        if (
                            retry_error.status_code == 429
                            and retry_error.quota_scope == "model"
                            and retry_error.retry_after_seconds is not None
                        ):
                            provider_wait = max(
                                0,
                                int(retry_error.retry_after_seconds),
                            )
                            if (
                                max_rate_limit_wait_seconds > 0
                                and
                                provider_wait
                                <= max_rate_limit_wait_seconds
                            ):
                                retry_wait_seconds = min(
                                    max_rate_limit_wait_seconds,
                                    max(1, provider_wait + 1),
                                )
                        same_model_retry_allowed = bool(
                            attempt_index + 1 < max_same_model_attempts
                            and retry_error.retryable
                            and (
                                retry_error.status_code != 429
                                or retry_wait_seconds is not None
                            )
                        )
                        if not same_model_retry_allowed:
                            raise
                        retry_event = {
                            "model": endpoint_model,
                            "attempt": attempt_index + 1,
                            "reason": (
                                f"http_{retry_error.status_code}"
                                if retry_error.status_code
                                else retry_error.category
                            ),
                        }
                        if retry_wait_seconds is not None:
                            retry_event.update(
                                {
                                    "quota_scope": retry_error.quota_scope,
                                    "wait_seconds": retry_wait_seconds,
                                }
                            )
                            time.sleep(retry_wait_seconds)
                        same_model_retry_events.append(retry_event)
                if not _compact_text(answer):
                    fallback_attempts.append(
                        {"model": endpoint_model, "reason": "empty_response"}
                    )
                    plan = getattr(_client, "resource_plan", {})
                    if isinstance(plan, dict):
                        plan["actual_model"] = endpoint_model
                        plan["requested_model"] = clean_model
                        plan["fallback_used"] = (
                            endpoint_model != clean_model.removeprefix("models/")
                        )
                        plan["invocation_error_reason"] = "empty_response"
                        plan["fallback_attempts"] = list(fallback_attempts)
                        plan["request_prompt_hashes"] = list(request_prompt_hashes)
                        plan["same_model_retry_events"] = list(
                            same_model_retry_events
                        )
                        setattr(_client, "resource_plan", plan)
                    if (
                        endpoint_model == model_candidates[-1]
                        or ":generateContent" in base
                        or not allow_fallback
                    ):
                        _record_invocation_outcome(
                            _client,
                            contract=invocation_contract,
                            requested_model=clean_model,
                            actual_model=endpoint_model,
                            response_received=False,
                            error_reason="empty_response",
                            fallback_used=(
                                endpoint_model
                                != clean_model.removeprefix("models/")
                            ),
                            normalized_error_history=normalized_error_history,
                            fallback_attempts=fallback_attempts,
                        )
                        return ""
                    continue
                setattr(_client, "model_name", endpoint_model)
                plan = getattr(_client, "resource_plan", {})
                if isinstance(plan, dict):
                    actual_capabilities = provider_reasoning_capabilities(
                        "gemini",
                        endpoint_model,
                    )
                    plan["actual_model"] = endpoint_model
                    plan["requested_model"] = clean_model
                    plan["fallback_used"] = endpoint_model != clean_model.removeprefix("models/")
                    plan["fallback_attempts"] = list(fallback_attempts)
                    plan["normalized_error_history"] = list(normalized_error_history)
                    plan["request_prompt_hashes"] = list(request_prompt_hashes)
                    plan["same_model_retry_events"] = list(same_model_retry_events)
                    plan["quota_scope"] = ""
                    plan["fallback_blocked_reason"] = ""
                    plan["invocation_error_reason"] = ""
                    plan["reasoning_capabilities"] = actual_capabilities
                    plan["reasoning_effort"] = _normalized_reasoning_effort(
                        reasoning_effort,
                        actual_capabilities,
                    )
                    actual_profile = capability_profile_from_record(
                        {
                            "provider_code": "gemini",
                            "default_model": endpoint_model,
                        },
                        reasoning=actual_capabilities,
                        native_tool_runtime_enabled=native_tool_runtime_enabled,
                        structured_output_runtime_enabled=structured_output_runtime_enabled,
                    )
                    plan["capability_profile"] = actual_profile.to_dict()
                    plan["degradation_mode"] = actual_profile.degradation_mode
                    response_metadata = _gemini_response_metadata(response)
                    response_metadata.update(
                        {
                            "model": endpoint_model,
                            "invocation_contract": invocation_contract,
                            "max_output_tokens": int(
                                candidate_generation_config.get("maxOutputTokens") or 0
                            ),
                        }
                    )
                    metadata_history = [
                        dict(row)
                        for row in list(plan.get("response_metadata_history") or [])[-31:]
                        if isinstance(row, dict)
                    ]
                    metadata_history.append(response_metadata)
                    plan["last_response_metadata"] = response_metadata
                    plan["response_metadata_history"] = metadata_history
                    setattr(_client, "resource_plan", plan)
                break
            except requests.RequestException as exc:
                last_error = exc
                normalized_error = normalize_provider_error("gemini", exc)
                normalized_error_history.append(normalized_error.to_dict())
                status = normalized_error.status_code
                reason = (
                    "turn_deadline_exceeded"
                    if normalized_error.category == "turn_deadline"
                    else "transport_error"
                    if normalized_error.category == "transport"
                    else f"http_{int(status or 0)}"
                )
                fallback_attempts.append(
                    {"model": endpoint_model, "reason": reason}
                )
                plan = getattr(_client, "resource_plan", {})
                if isinstance(plan, dict):
                    plan["invocation_error_reason"] = reason
                    plan["fallback_attempts"] = list(fallback_attempts)
                    plan["normalized_error_history"] = list(normalized_error_history)
                    plan["request_prompt_hashes"] = list(request_prompt_hashes)
                    plan["same_model_retry_events"] = list(same_model_retry_events)
                    plan["quota_scope"] = normalized_error.quota_scope
                    plan["fallback_blocked_reason"] = (
                        _fallback_blocked_reason_for(normalized_error)
                    )
                    setattr(_client, "resource_plan", plan)
                if (
                    not normalized_error.model_fallback_allowed
                    or endpoint_model == model_candidates[-1]
                    or ":generateContent" in base
                ):
                    _record_invocation_outcome(
                        _client,
                        contract=invocation_contract,
                        requested_model=clean_model,
                        response_received=False,
                        error_reason=reason,
                        fallback_used=(
                            endpoint_model != clean_model.removeprefix("models/")
                        ),
                        normalized_error=normalized_error,
                        normalized_error_history=normalized_error_history,
                        fallback_blocked_reason=(
                            _fallback_blocked_reason_for(normalized_error)
                        ),
                        fallback_attempts=fallback_attempts,
                    )
                    raise
        else:
            if last_error is not None:
                raise last_error
            return ""

        _record_invocation_outcome(
            _client,
            contract=invocation_contract,
            requested_model=clean_model,
            actual_model=_compact_text(
                dict(getattr(_client, "resource_plan", {}) or {}).get(
                    "actual_model"
                )
            ),
            response_received=bool(_compact_text(answer)),
            error_reason="" if _compact_text(answer) else "empty_response",
            fallback_used=bool(
                dict(getattr(_client, "resource_plan", {}) or {}).get(
                    "fallback_used"
                )
            ),
            normalized_error_history=normalized_error_history,
            fallback_attempts=fallback_attempts,
        )
        return answer

    def _client(prompt: str) -> str:
        return _invoke(prompt)

    def _invoke_structured(
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
    ) -> str:
        clean_schema = dict(schema or {}) or {
            "type": "object",
            "additionalProperties": True,
        }

        def _structured_generation_config(endpoint_model: str) -> dict[str, Any]:
            config = _gemini_structured_generation_config(
                endpoint_model,
                clean_schema,
            )
            # Thinking tokens count against Gemini's output budget. A short
            # ordinary-chat budget can therefore cut a valid JSON plan before
            # its closing braces. Structured planning gets a bounded contract
            # budget while the user's normal chat setting remains unchanged.
            config["maxOutputTokens"] = max(
                int(generation_config.get("maxOutputTokens") or 0),
                DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS,
            )
            return config

        def guarded_text_fallback(reason: str) -> str:
            plan = getattr(_client, "resource_plan", {})
            if isinstance(plan, dict):
                plan["structured_output_fallback_reason"] = reason
                plan["structured_output_fallback_contract"] = (
                    "same_exact_model_json_text_guarded"
                )
                setattr(_client, "resource_plan", plan)
            answer = _invoke(
                guarded_json_prompt(prompt, schema),
                generation_config_overrides={
                    "maxOutputTokens": max(
                        int(generation_config.get("maxOutputTokens") or 0),
                        DEFAULT_GUARDED_JSON_MAX_TOKENS,
                    )
                },
                invocation_contract="text",
            )
            return answer

        try:
            answer = _invoke(
                prompt,
                generation_config_factory=_structured_generation_config,
                invocation_contract="structured_output",
            )
            if _compact_text(answer):
                return answer
            plan = getattr(_client, "resource_plan", {})
            if (
                isinstance(plan, dict)
                and _compact_text(plan.get("invocation_error_reason"))
                == "empty_response"
            ):
                return guarded_text_fallback(
                    "empty_structured_response"
                )
            return answer
        except requests.RequestException as exc:
            if (
                isinstance(exc, requests.Timeout)
                and not isinstance(exc, CloudTurnDeadlineExceeded)
            ):
                return guarded_text_fallback(
                    "structured_request_timeout"
                )
            status = int(
                getattr(getattr(exc, "response", None), "status_code", 0)
                or 0
            )
            if status not in {400, 422}:
                raise
            # Some generateContent model/API combinations advertise structured
            # output but reject the schema envelope. Keep the exact selected
            # model and retry the same guarded planning prompt as plain text;
            # downstream parsing and step allow-lists remain authoritative.
            # The retry is still a structured-planner call in application
            # semantics. Gemini thinking tokens share the output budget, so
            # falling back to the ordinary chat budget can truncate the JSON
            # before its closing brace even though the exact model answered.
            return guarded_text_fallback(f"http_{status}")

    def _invoke_json_text(
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
    ) -> str:
        # Gemini-hosted text models such as Gemma intentionally do not inherit
        # Gemini native tool or response-schema authority.  They can still
        # author the same typed plan through the provider-independent guarded
        # JSON-text contract; downstream JSON/schema/operation verification
        # remains authoritative.
        prompt = guarded_json_prompt(prompt, schema)
        guarded_max_tokens = max(
            int(generation_config.get("maxOutputTokens") or 0),
            DEFAULT_GUARDED_JSON_MAX_TOKENS,
        )
        plan = getattr(_client, "resource_plan", {})
        if isinstance(plan, dict):
            plan["guarded_json_max_tokens"] = guarded_max_tokens
            setattr(_client, "resource_plan", plan)
        return _invoke(
            prompt,
            generation_config_overrides={
                "maxOutputTokens": guarded_max_tokens,
            },
            invocation_contract="json_text_guarded",
        )

    def _invoke_tools(prompt: str, *, tools: list[dict[str, Any]]) -> str:
        definitions, wire_to_source = _provider_tool_definitions(
            tools,
            family="gemini",
        )
        if not definitions:
            return _invoke(prompt)
        return _invoke(
            prompt,
            payload_overrides={
                "tools": [{"functionDeclarations": definitions}],
                "toolConfig": {
                    "functionCallingConfig": {
                        "mode": "AUTO",
                    }
                },
            },
            response_extractor=lambda payload: _extract_gemini_tool_decision(
                payload,
                wire_to_source=wire_to_source,
            ),
            invocation_contract="native_tools",
        )

    setattr(_client, "invoke_structured", _invoke_structured)
    setattr(_client, "invoke_json_text", _invoke_json_text)
    setattr(_client, "invoke_tools", _invoke_tools)

    return _client


def _base_request_options(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "max_tokens",
            "max_output_tokens",
            "maxOutputTokens",
            "temperature",
            "max_exact_model_rate_limit_wait_seconds",
        )
        if record.get(key) not in (None, "")
    }


def _configured_fallback_models(record: dict[str, Any]) -> list[str]:
    rows = record.get("free_model_test_route") or record.get("fallback_models") or []
    if isinstance(rows, dict):
        rows = rows.get("model_ids") or rows.get("models") or []
    models: list[str] = []
    for row in list(rows or []):
        value = _compact_text(
            row.get("model_id") or row.get("id")
            if isinstance(row, dict)
            else row
        ).removeprefix("models/")
        if value and value not in models:
            models.append(value)
    return models


def _configured_fallback_model_metadata(
    record: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    route = record.get("free_model_test_route")
    rows = route.get("models") if isinstance(route, dict) else []
    result: dict[str, dict[str, Any]] = {}
    for row in list(rows or []):
        if not isinstance(row, dict):
            continue
        model_id = _compact_text(row.get("model_id") or row.get("id")).removeprefix(
            "models/"
        )
        if not model_id:
            continue
        metadata = (
            dict(row.get("metadata") or {})
            if isinstance(row.get("metadata"), dict)
            else {}
        )
        supported_parameters = [
            _compact_text(value)
            for value in list(metadata.get("supported_parameters") or [])
            if _compact_text(value)
        ]
        if not supported_parameters:
            if row.get("native_tool_calling") is True:
                supported_parameters.extend(["tools", "tool_choice"])
            if row.get("structured_output") is True:
                supported_parameters.append("response_format")
        metadata["supported_parameters"] = list(dict.fromkeys(supported_parameters))
        metadata.setdefault("context_length", row.get("context_tokens"))
        metadata.setdefault("output_token_limit", row.get("output_tokens"))
        if row.get("reasoning") is not None and not isinstance(
            metadata.get("reasoning"), dict
        ):
            metadata["reasoning"] = {"supported": bool(row.get("reasoning"))}
        result[model_id] = metadata
    return result


def _adapter_capability_profile(record: dict[str, Any]) -> ModelCapabilityProfile:
    provider_code = _compact_text(record.get("provider_code")).casefold()
    model = _compact_text(record.get("default_model"))
    metadata = dict(record.get("model_metadata") or {}) if isinstance(record.get("model_metadata"), dict) else {}
    reasoning = provider_reasoning_capabilities(provider_code, model, model_metadata=metadata)
    return capability_profile_from_record(
        record,
        reasoning=reasoning,
        native_tool_runtime_enabled=False,
        structured_output_runtime_enabled=False,
    )


def _runtime_feature_preference(
    record: dict[str, Any],
    key: str,
    *,
    available: bool,
) -> bool:
    """Auto-enable a wired capability unless the user explicitly disables it."""

    if key in record:
        return bool(record.get(key))
    return bool(available)


def _openai_compatible_adapter_client(record: dict[str, Any], timeout: float) -> ChatClient | None:
    provider_code = _compact_text(record.get("provider_code")).casefold()
    model = _compact_text(record.get("default_model"))
    metadata = dict(record.get("model_metadata") or {}) if isinstance(record.get("model_metadata"), dict) else {}
    reasoning = provider_reasoning_capabilities(provider_code, model, model_metadata=metadata)
    effort = _normalized_reasoning_effort(record.get("reasoning_effort"), reasoning)
    options = _base_request_options(record)
    if provider_code == "openrouter":
        configured_reasoning = record.get("reasoning")
        if isinstance(configured_reasoning, dict):
            options["reasoning"] = dict(configured_reasoning)
        elif reasoning.get("supported"):
            if effort == "auto":
                options["reasoning"] = {"enabled": True, "exclude": True}
            elif effort == "off":
                options["reasoning"] = {"effort": "none", "exclude": True}
            else:
                options["reasoning"] = {"effort": effort, "exclude": True}
    allow_fallback = bool(record.get("allow_model_fallback", True))
    configured_route = _configured_fallback_models(record)
    fallback_models: list[str] | tuple[str, ...] | None = None
    if allow_fallback and provider_code == "openrouter":
        fallback_models = configured_route or OPENROUTER_FALLBACK_MODELS
    advertised = _adapter_capability_profile(record)
    return build_openai_compatible_client(
        base_url=_compact_text(record.get("endpoint_url")) or DEFAULT_BASE_URLS.get(provider_code, ""),
        api_key=_compact_text(record.get("api_key")),
        model=model,
        timeout=timeout,
        request_options=options,
        fallback_models=fallback_models,
        provider_code=provider_code or "custom",
        model_metadata=metadata,
        fallback_model_metadata=_configured_fallback_model_metadata(record),
        native_tool_runtime_enabled=_runtime_feature_preference(
            record,
            "native_tool_runtime_enabled",
            available=advertised.native_tool_calling_available,
        ),
        structured_output_runtime_enabled=_runtime_feature_preference(
            record,
            "structured_output_runtime_enabled",
            available=advertised.structured_output_available,
        ),
    )


def _anthropic_adapter_client(record: dict[str, Any], timeout: float) -> ChatClient | None:
    return _build_anthropic_client(
        base_url=_compact_text(record.get("endpoint_url")) or DEFAULT_BASE_URLS["anthropic"],
        api_key=_compact_text(record.get("api_key")),
        model=_compact_text(record.get("default_model")),
        timeout=timeout,
        request_options=_base_request_options(record),
    )


def _gemini_adapter_client(record: dict[str, Any], timeout: float) -> ChatClient | None:
    model = _compact_text(record.get("default_model"))
    metadata = dict(record.get("model_metadata") or {}) if isinstance(record.get("model_metadata"), dict) else {}
    reasoning = provider_reasoning_capabilities("gemini", model, model_metadata=metadata)
    options = _base_request_options(record)
    options["reasoning_effort"] = _normalized_reasoning_effort(record.get("reasoning_effort"), reasoning)
    options["allow_fallback"] = bool(record.get("allow_model_fallback", True))
    advertised = _adapter_capability_profile(record)
    return _build_gemini_client(
        base_url=_compact_text(record.get("endpoint_url")) or DEFAULT_BASE_URLS["gemini"],
        api_key=_compact_text(record.get("api_key")),
        model=model,
        timeout=timeout,
        request_options=options,
        fallback_models=_configured_fallback_models(record) or None,
        native_tool_runtime_enabled=_runtime_feature_preference(
            record,
            "native_tool_runtime_enabled",
            available=advertised.native_tool_calling_available,
        ),
        structured_output_runtime_enabled=_runtime_feature_preference(
            record,
            "structured_output_runtime_enabled",
            available=advertised.structured_output_available,
        ),
    )


def _local_adapter_client(record: dict[str, Any], timeout: float) -> ChatClient | None:
    # Lazy import keeps llama.cpp discovery out of cloud-only startup paths.
    from AI.processors.local_runtime import build_local_planner_client

    local_record = dict(record or {})
    local_record.setdefault("timeout", timeout)
    return build_local_planner_client(local_record)


def _local_capability_profile(record: dict[str, Any]) -> ModelCapabilityProfile:
    local_record = dict(record or {})
    local_record["provider_code"] = "local"
    local_record["default_model"] = _compact_text(
        local_record.get("default_model")
        or local_record.get("filename")
        or local_record.get("repo_id")
        or local_record.get("local_path")
    )
    return capability_profile_from_record(
        local_record,
        reasoning=dict(local_record.get("reasoning_capabilities") or {}),
        native_tool_runtime_enabled=False,
        structured_output_runtime_enabled=False,
    )


_ADAPTER_REGISTRY: ProviderAdapterRegistry | None = None


def provider_adapter_registry() -> ProviderAdapterRegistry:
    global _ADAPTER_REGISTRY
    if _ADAPTER_REGISTRY is not None:
        return _ADAPTER_REGISTRY
    registry = ProviderAdapterRegistry()
    for code in sorted(OPENAI_COMPATIBLE_PROVIDERS):
        registry.register(
            CallableProviderAdapter(
                code=code,
                family="openai_compatible",
                client_factory=_openai_compatible_adapter_client,
                capability_factory=_adapter_capability_profile,
            )
        )
    registry.register(
        CallableProviderAdapter(
            code="anthropic",
            family="anthropic_messages",
            client_factory=_anthropic_adapter_client,
            capability_factory=_adapter_capability_profile,
        )
    )
    registry.register(
        CallableProviderAdapter(
            code="gemini",
            family="google_generate_content",
            client_factory=_gemini_adapter_client,
            capability_factory=_adapter_capability_profile,
        )
    )
    registry.register(
        CallableProviderAdapter(
            code="local",
            family="llama_cpp",
            client_factory=_local_adapter_client,
            capability_factory=_local_capability_profile,
        ),
        "llama_cpp",
    )
    _ADAPTER_REGISTRY = registry
    return registry


def provider_adapter_for_record(record: dict[str, Any] | None) -> ProviderAdapter | None:
    if not isinstance(record, dict):
        return None
    provider_code = _compact_text(record.get("provider_code")).casefold()
    adapter = provider_adapter_registry().get(provider_code)
    if adapter is None and _compact_text(record.get("endpoint_url")):
        adapter = provider_adapter_registry().get("custom")
    return adapter


def build_provider_chat_client(
    record: dict[str, Any] | None,
    *,
    timeout: float = DEFAULT_CLOUD_REQUEST_TIMEOUT_SECONDS,
) -> ChatClient | None:
    if not isinstance(record, dict) or not bool(record.get("is_enabled", True)):
        return None
    provider_code = _compact_text(record.get("provider_code")).casefold()
    model = _compact_text(record.get("default_model"))
    adapter = provider_adapter_for_record(record)
    if adapter is None:
        return None
    client = adapter.build_chat_client(record, timeout=timeout)
    if client is None:
        return None
    advertised_profile = adapter.capability_profile(record)
    native_runtime_enabled = bool(
        _runtime_feature_preference(
            record,
            "native_tool_runtime_enabled",
            available=advertised_profile.native_tool_calling_available,
        )
        and callable(getattr(client, "invoke_tools", None))
    )
    structured_runtime_enabled = bool(
        _runtime_feature_preference(
            record,
            "structured_output_runtime_enabled",
            available=advertised_profile.structured_output_available,
        )
        and callable(getattr(client, "invoke_structured", None))
    )
    profile = capability_profile_from_record(
        record,
        reasoning=dict(advertised_profile.reasoning or {}),
        native_tool_runtime_enabled=native_runtime_enabled,
        structured_output_runtime_enabled=structured_runtime_enabled,
    )
    reasoning = dict(profile.reasoning or {})
    effort = _normalized_reasoning_effort(record.get("reasoning_effort"), reasoning)
    if not _compact_text(getattr(client, "runtime_name", "")):
        setattr(client, "runtime_name", f"{provider_code or 'cloud'}_chat")
    if model or not _compact_text(getattr(client, "model_name", "")):
        setattr(client, "model_name", model or "selected")
    resource_plan = dict(getattr(client, "resource_plan", {}) or {})
    resource_plan.update(
        {
            "profile": "local_provider" if provider_code == "local" else "cloud_provider",
            "provider_code": provider_code,
            "provider_family": adapter.family,
            "requested_model": model,
            "reasoning_effort": effort,
            "reasoning_capabilities": reasoning,
            "capability_profile": profile.to_dict(),
            "degradation_mode": profile.degradation_mode,
            "fallback_allowed": bool(record.get("allow_model_fallback", True)),
            "request_timeout_seconds": float(timeout),
            "guarded_json_recovery_available": callable(
                getattr(client, "invoke_json_text", None)
            ),
            "contract_health_key": hashlib.sha256(
                json.dumps(
                    {
                        "provider_code": provider_code,
                        "provider_family": adapter.family,
                        "provider_account_id": _compact_text(record.get("id")),
                        "model": model,
                        "endpoint": _compact_text(record.get("endpoint_url"))
                        or DEFAULT_BASE_URLS.get(provider_code, ""),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
    )
    setattr(client, "resource_plan", resource_plan)
    # Wrappers delegate this method to the actual client whose request closure
    # owns the deadline; writing a wrapper attribute would leave it unchanged.
    setattr(client, "reserve_task_budget", lambda *, max_steps: reserve_provider_task_budget(client, max_steps=max_steps))
    return client
