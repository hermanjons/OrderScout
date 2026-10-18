from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable


DEGRADATION_NATIVE_TOOLS = "native_tools"
DEGRADATION_STRUCTURED_PLAN = "structured_plan"
DEGRADATION_TEXT_GUARDED = "text_guarded"
DEGRADATION_CHAT_ONLY = "chat_only"

_STRUCTURED_CONTRACT_HEALTH_TTL_SECONDS = 30 * 60
_STRUCTURED_CONTRACT_HEALTH_MAX_ENTRIES = 256
_STRUCTURED_CONTRACT_DEGRADATIONS: dict[str, dict[str, Any]] = {}
_STRUCTURED_CONTRACT_HEALTH_CACHE_VERSION = 1


def _text(value: Any) -> str:
    return str(value or "").strip()


def _structured_contract_health_key(
    planner_client: Callable[[str], str] | None,
) -> str:
    plan = getattr(planner_client, "resource_plan", {})
    if not isinstance(plan, dict):
        return ""
    return _text(plan.get("contract_health_key"))


def _structured_contract_health_cache_path() -> Path:
    override = _text(os.environ.get("ORDERSCOUT_PROVIDER_HEALTH_CACHE_PATH"))
    if override:
        return Path(override)
    local_app_data = _text(os.environ.get("LOCALAPPDATA"))
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "OrderScout" / "cache" / "ai_provider_contract_health.json"


def _persistent_structured_reason(reason: str) -> str:
    """Return a value-free reason code safe to persist across processes."""

    clean = _text(reason).casefold()
    safe_exact = {
        "empty_response",
        "empty_structured_response",
        "structured_request_timeout",
        "structured_no_response",
        "structured_contract_validation_failed",
    }
    if clean in safe_exact or re.fullmatch(r"http_(?:400|422)", clean):
        return clean
    return "structured_contract_validation_failed"


def _read_persistent_structured_contract_degradations() -> dict[str, dict[str, Any]]:
    path = _structured_contract_health_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != (
        _STRUCTURED_CONTRACT_HEALTH_CACHE_VERSION
    ):
        return {}
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, dict):
        return {}
    now = time.time()
    entries: dict[str, dict[str, Any]] = {}
    for key, raw_row in raw_entries.items():
        if not re.fullmatch(r"[a-f0-9]{64}", _text(key).casefold()):
            continue
        if not isinstance(raw_row, dict):
            continue
        try:
            observed_epoch = float(raw_row.get("observed_epoch") or 0.0)
        except (TypeError, ValueError):
            continue
        age = now - observed_epoch
        if age < 0 or age > _STRUCTURED_CONTRACT_HEALTH_TTL_SECONDS:
            continue
        entries[_text(key).casefold()] = {
            "reason": _persistent_structured_reason(raw_row.get("reason")),
            "observed_epoch": observed_epoch,
        }
    return entries


def _write_persistent_structured_contract_degradations(
    entries: dict[str, dict[str, Any]],
) -> None:
    path = _structured_contract_health_cache_path()
    bounded = sorted(
        (
            (key, dict(row))
            for key, row in entries.items()
            if re.fullmatch(r"[a-f0-9]{64}", _text(key).casefold())
            and isinstance(row, dict)
        ),
        key=lambda item: float(item[1].get("observed_epoch") or 0.0),
        reverse=True,
    )[:_STRUCTURED_CONTRACT_HEALTH_MAX_ENTRIES]
    payload = {
        "version": _STRUCTURED_CONTRACT_HEALTH_CACHE_VERSION,
        "entries": {
            _text(key).casefold(): {
                "reason": _persistent_structured_reason(row.get("reason")),
                "observed_epoch": float(row.get("observed_epoch") or 0.0),
            }
            for key, row in bounded
        },
    }
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _remember_structured_contract_degradation(
    planner_client: Callable[[str], str] | None,
    reason: str,
) -> None:
    key = _structured_contract_health_key(planner_client)
    clean_reason = _text(reason)[:240]
    if not key or not clean_reason:
        return
    now = time.monotonic()
    _STRUCTURED_CONTRACT_DEGRADATIONS[key] = {
        "reason": clean_reason,
        "observed_monotonic": now,
    }
    expired = [
        cache_key
        for cache_key, row in _STRUCTURED_CONTRACT_DEGRADATIONS.items()
        if now - float(row.get("observed_monotonic") or 0.0)
        > _STRUCTURED_CONTRACT_HEALTH_TTL_SECONDS
    ]
    for cache_key in expired:
        _STRUCTURED_CONTRACT_DEGRADATIONS.pop(cache_key, None)
    if len(_STRUCTURED_CONTRACT_DEGRADATIONS) > _STRUCTURED_CONTRACT_HEALTH_MAX_ENTRIES:
        oldest = sorted(
            _STRUCTURED_CONTRACT_DEGRADATIONS,
            key=lambda cache_key: float(
                _STRUCTURED_CONTRACT_DEGRADATIONS[cache_key].get(
                    "observed_monotonic"
                )
                or 0.0
            ),
        )
        for cache_key in oldest[
            : len(_STRUCTURED_CONTRACT_DEGRADATIONS)
            - _STRUCTURED_CONTRACT_HEALTH_MAX_ENTRIES
        ]:
            _STRUCTURED_CONTRACT_DEGRADATIONS.pop(cache_key, None)
    persistent_entries = _read_persistent_structured_contract_degradations()
    persistent_entries[key.casefold()] = {
        "reason": _persistent_structured_reason(clean_reason),
        "observed_epoch": time.time(),
    }
    _write_persistent_structured_contract_degradations(persistent_entries)


def _cached_structured_contract_degradation(
    planner_client: Callable[[str], str] | None,
) -> str:
    key = _structured_contract_health_key(planner_client)
    row = _STRUCTURED_CONTRACT_DEGRADATIONS.get(key) if key else None
    if isinstance(row, dict):
        age = time.monotonic() - float(row.get("observed_monotonic") or 0.0)
        if age <= _STRUCTURED_CONTRACT_HEALTH_TTL_SECONDS:
            return _text(row.get("reason"))
        _STRUCTURED_CONTRACT_DEGRADATIONS.pop(key, None)
    if not key:
        return ""
    persistent_row = _read_persistent_structured_contract_degradations().get(
        key.casefold()
    )
    if not isinstance(persistent_row, dict):
        return ""
    reason = _text(persistent_row.get("reason"))
    if not reason:
        return ""
    _STRUCTURED_CONTRACT_DEGRADATIONS[key] = {
        "reason": reason,
        "observed_monotonic": time.monotonic(),
    }
    return reason


@dataclass(frozen=True)
class ModelCapabilityProfile:
    provider_code: str
    model_id: str
    chat: bool = True
    streaming: bool = False
    native_tool_calling_available: bool = False
    native_tool_runtime_enabled: bool = False
    structured_output_available: bool = False
    structured_output_runtime_enabled: bool = False
    context_tokens: int | None = None
    output_tokens: int | None = None
    reasoning: dict[str, Any] = field(default_factory=dict)
    multimodal_inputs: tuple[str, ...] = ()
    usage_reporting: bool = False
    quota_reporting: bool = False
    pricing: dict[str, Any] = field(default_factory=dict)
    degradation_mode: str = DEGRADATION_TEXT_GUARDED
    prepare_write_allowed: bool = True
    external_write_planning_allowed: bool = False
    source: str = "inferred"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["multimodal_inputs"] = list(self.multimodal_inputs)
        return payload


@dataclass(frozen=True)
class ModelCapabilityGate:
    allowed: bool
    enforced: bool
    code: str = "allowed"
    message: str = ""
    degradation_mode: str = ""
    prepare_write: bool = False
    external_write: bool = False
    decision_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedProviderError:
    provider_code: str
    category: str
    retryable: bool
    quota_scope: str = ""
    status_code: int | None = None
    safe_message: str = ""
    model_fallback_allowed: bool = False
    retry_after_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _provider_error_text(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    payload: Any = None
    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
    parts = [_text(exc)]
    if payload not in (None, "", {}, []):
        try:
            parts.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        except Exception:
            parts.append(_text(payload))
    return " ".join(part for part in parts if part).casefold()


def _provider_error_metadata(exc: Exception) -> dict[str, Any]:
    response = getattr(exc, "response", None)
    try:
        payload = response.json() if response is not None else {}
        error = payload.get("error") if isinstance(payload, dict) else None
        metadata = error.get("metadata") if isinstance(error, dict) else None
        return metadata if isinstance(metadata, dict) else {}
    except Exception:
        return {}


def _provider_retry_after_seconds(exc: Exception, text: str) -> int | None:
    """Return only a bounded retry delay; never copy provider headers/payloads."""

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    header_value: Any = None
    if headers is not None:
        try:
            header_value = headers.get("Retry-After")
        except Exception:
            header_value = None
    candidates = [_text(header_value)]
    retry_match = re.search(
        r"(?:retry[_\s-]*(?:after|delay)|retrydelay)[^0-9]{0,80}"
        r"([0-9]+(?:\.[0-9]+)?)\s*s",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    if retry_match:
        candidates.append(retry_match.group(1))
    for value in candidates:
        if not value:
            continue
        try:
            seconds = int(float(value))
        except (TypeError, ValueError):
            continue
        if seconds >= 0:
            return min(seconds, 86_400)
    return None


def normalize_provider_error(
    provider_code: str,
    exc: Exception,
) -> NormalizedProviderError:
    """Normalize provider failures without exposing raw provider payloads.

    A 429 is not automatically a model-level failure. Explicit project/account/provider
    quota signals pause the provider route; explicit model/upstream signals may advance
    to the next capability-compatible model. Unknown 429 responses fail closed and never
    start a sibling-model roulette.
    """

    provider = _text(provider_code).casefold()
    response = getattr(exc, "response", None)
    status = int(getattr(response, "status_code", 0) or 0) or None
    text = _provider_error_text(exc)
    compact_error = re.sub(r"[^a-z0-9]+", "", text)
    retry_after_seconds = _provider_retry_after_seconds(exc, text)
    metadata = _provider_error_metadata(exc)
    limit_source = _text(metadata.get("limit_source")).casefold()
    openrouter_spending_limit = provider == "openrouter" and status == 403 and (
        limit_source in {
            "openrouter_key_limit", "openrouter_workspace_budget",
            "openrouter_guardrail_budget",
        }
        or not limit_source and "key limit exceeded (total limit)" in text
    )
    turn_deadline = bool(getattr(exc, "turn_deadline_exceeded", False))
    exception_module = str(type(exc).__module__ or "").casefold()
    http_client_transport_without_response = bool(
        status is None
        and exception_module.startswith(
            ("requests", "urllib3", "httpx", "httpcore")
        )
    )
    transport = (
        isinstance(exc, (TimeoutError, ConnectionError))
        or http_client_transport_without_response
        or any(
            token in text
            for token in ("connection", "timed out", "timeout")
        )
    )
    openrouter_upstream_auth_failure = (
        provider == "openrouter"
        and status in {400, 401, 403}
        and (
            "api_key_invalid" in text
            or "api key not valid" in text
            or "invalid api key" in text
        )
        and (
            '"is_byok": false' in text
            or "provider returned error" in text
        )
    )

    quota_scope = ""
    category = "provider_error"
    retryable = False
    model_fallback_allowed = False
    if turn_deadline:
        category = "turn_deadline"
        quota_scope = "runtime"
    elif openrouter_spending_limit:
        category = "billing"
        quota_scope = "key_limit" if limit_source in {"", "openrouter_key_limit"} else "account"
        # A different model cannot restore this shared spending allowance.
        retry_after_seconds = None
    elif openrouter_upstream_auth_failure:
        # OpenRouter may return an HTTP 400 when the selected upstream route
        # cannot authenticate with its own provider credential.  This is not
        # the user's OpenRouter credential and must not pause the whole account
        # route.  Treat it as an unavailable model route so an explicitly
        # enabled model fallback may advance while exact-model evaluations fail
        # closed and report that the requested model never answered.
        category = "model_unavailable"
        retryable = True
        quota_scope = "model"
        model_fallback_allowed = True
    elif (
        status == 402
        or "insufficient_quota" in text
        or "insufficient credit" in text
        or "credit balance" in text
        or (
            "billing account" in text
            and any(
                token in text
                for token in (
                    "disabled",
                    "inactive",
                    "not enabled",
                    "payment required",
                )
            )
        )
    ):
        category = "billing"
        quota_scope = "billing"
    elif (
        "policy violation" in text
        or "blocked by policy" in text
        or "permission denied" in text
        or "not allowed for this project" in text
    ):
        category = "policy"
        quota_scope = "policy"
    elif status in {401, 403} or any(
        token in text
        for token in (
            "invalid api key",
            "api key not valid",
            "unauthorized",
            "authentication failed",
            "invalid token",
        )
    ):
        category = "auth"
        quota_scope = "auth"
    elif status == 429 or "quota" in text or "rate limit" in text:
        category = "quota"
        retryable = True
        combined_model_scope_tokens = (
            "perprojectpermodel",
            "peraccountpermodel",
            "perproviderpermodel",
            "quotadimensionsmodel",
        )
        model_scope_tokens = (
            "permodel",
            "modellevel",
            "modelquota",
            "modelratelimit",
            "upstreamratelimit",
            "upstreamproviderreturned",
        )
        project_scope_tokens = (
            "perproject",
            "projectlevel",
            "projectquota",
        )
        free_tier_scope_tokens = (
            "freemodelsperday",
            "freemodelsperminute",
            "dailyfreelimit",
            "freemodelratelimit",
        )
        account_scope_tokens = (
            "peraccount",
            "accountlevel",
            "accountquota",
        )
        provider_scope_tokens = (
            "providerwide",
            "providerquota",
        )
        if any(
            token in compact_error for token in combined_model_scope_tokens
        ):
            # Gemini quota IDs such as
            # GenerateRequestsPerDayPerProjectPerModel-FreeTier are backed by
            # a different quota bucket for each model. Switching models is
            # therefore a model-scope transition, not a project-wide retry.
            quota_scope = "model"
            model_fallback_allowed = True
        elif any(token in compact_error for token in model_scope_tokens):
            quota_scope = "model"
            model_fallback_allowed = True
        elif any(token in compact_error for token in project_scope_tokens):
            quota_scope = "project"
        elif any(token in compact_error for token in free_tier_scope_tokens):
            # OpenRouter's :free variants share a free-model request bucket.
            # Exhausting that bucket does not prove that paid models or the
            # API key's dollar budget are exhausted.  Do not try another free
            # sibling, but also do not pause explicitly authorized paid routes.
            quota_scope = "free_tier"
            model_fallback_allowed = False
        elif any(token in compact_error for token in account_scope_tokens):
            quota_scope = "account"
        elif any(token in compact_error for token in provider_scope_tokens):
            quota_scope = "provider"
        else:
            quota_scope = "unknown"
            model_fallback_allowed = False
    elif transport:
        category = "transport"
        retryable = True
        model_fallback_allowed = True
    elif status == 404:
        category = "model_unavailable"
        retryable = True
        quota_scope = "model"
        model_fallback_allowed = True
    elif status in {500, 502, 503, 504}:
        category = "provider_error"
        retryable = True
        model_fallback_allowed = True

    safe_message = {
        "quota": "Provider kota veya rate-limit yanıtı verdi.",
        "transport": "Provider bağlantısı zaman aşımına uğradı veya kurulamadı.",
        "model_unavailable": "İstenen model provider üzerinde bulunamadı.",
        "billing": "Provider hesabının ödeme veya kredi erişimi isteği engelledi.",
        "auth": "Provider kimlik doğrulaması başarısız oldu.",
        "policy": "Provider erişim politikası isteği engelledi.",
        "turn_deadline": "Cloud sohbet turunun süre bütçesi doldu.",
        "provider_error": "Provider isteği başarısız oldu.",
    }.get(category, "Provider isteği başarısız oldu.")
    if openrouter_spending_limit:
        safe_message = (
            "API anahtarının harcama sınırı doldu."
            if quota_scope == "key_limit"
            else "Provider hesabının harcama sınırı doldu."
        )
    return NormalizedProviderError(
        provider_code=provider,
        category=category,
        retryable=retryable,
        quota_scope=quota_scope,
        status_code=status,
        safe_message=safe_message,
        model_fallback_allowed=model_fallback_allowed,
        retry_after_seconds=retry_after_seconds,
    )


def capability_profile_from_record(
    record: dict[str, Any],
    *,
    reasoning: dict[str, Any] | None = None,
    native_tool_runtime_enabled: bool = False,
    structured_output_runtime_enabled: bool = False,
) -> ModelCapabilityProfile:
    provider = _text(record.get("provider_code")).casefold()
    model_id = _text(record.get("default_model") or record.get("model_id") or record.get("id")).removeprefix("models/")
    metadata = dict(record.get("model_metadata") or {}) if isinstance(record.get("model_metadata"), dict) else {}
    supported_parameters = {
        _text(value).casefold()
        for value in list(metadata.get("supported_parameters") or record.get("supported_parameters") or [])
        if _text(value)
    }
    generation_methods = {
        _text(value)
        for value in list(metadata.get("supported_generation_methods") or record.get("supported_generation_methods") or [])
        if _text(value)
    }
    gemini_function_model = provider == "gemini" and model_id.casefold().startswith(
        "gemini-"
    )
    native_available = bool(
        "tools" in supported_parameters
        or "tool_choice" in supported_parameters
        or "function_calling" in supported_parameters
        or provider in {"anthropic", "openai"}
        or gemini_function_model
    )
    structured_available = bool(
        supported_parameters.intersection(
            {"response_format", "structured_outputs", "json_schema", "response_schema"}
        )
        or provider == "anthropic"
        or gemini_function_model
    )
    runtime_native = bool(native_available and native_tool_runtime_enabled)
    runtime_structured = bool(structured_available and structured_output_runtime_enabled)
    if runtime_native and runtime_structured:
        degradation = DEGRADATION_NATIVE_TOOLS
    elif runtime_structured:
        degradation = DEGRADATION_STRUCTURED_PLAN
    elif bool(record.get("chat", True)):
        degradation = DEGRADATION_TEXT_GUARDED
    else:
        degradation = DEGRADATION_CHAT_ONLY

    def optional_int(*values: Any) -> int | None:
        for value in values:
            try:
                parsed = int(value)
            except Exception:
                continue
            if parsed > 0:
                return parsed
        return None

    modalities = metadata.get("input_modalities") or record.get("input_modalities") or []
    if not modalities and provider == "gemini":
        modalities = ["text", "image"]
    return ModelCapabilityProfile(
        provider_code=provider,
        model_id=model_id,
        chat=bool(record.get("chat", True) and (not generation_methods or "generateContent" in generation_methods)),
        streaming=bool(metadata.get("streaming") or record.get("streaming")),
        native_tool_calling_available=native_available,
        native_tool_runtime_enabled=runtime_native,
        structured_output_available=structured_available,
        structured_output_runtime_enabled=runtime_structured,
        context_tokens=optional_int(
            metadata.get("context_length"),
            metadata.get("input_token_limit"),
            record.get("context_length"),
            record.get("input_token_limit"),
        ),
        output_tokens=optional_int(
            metadata.get("max_output_tokens"),
            metadata.get("output_token_limit"),
            record.get("max_output_tokens"),
            record.get("output_token_limit"),
        ),
        reasoning=dict(reasoning or {}),
        multimodal_inputs=tuple(_text(value).casefold() for value in modalities if _text(value)),
        usage_reporting=bool(metadata.get("usage_reporting", provider in {"openai", "openrouter", "anthropic"})),
        quota_reporting=bool(metadata.get("quota_reporting")),
        pricing=dict(metadata.get("pricing") or record.get("pricing") or {}),
        degradation_mode=degradation,
        prepare_write_allowed=degradation in {
            DEGRADATION_NATIVE_TOOLS,
            DEGRADATION_STRUCTURED_PLAN,
            DEGRADATION_TEXT_GUARDED,
        },
        external_write_planning_allowed=degradation in {
            DEGRADATION_NATIVE_TOOLS,
            DEGRADATION_STRUCTURED_PLAN,
        },
        source="provider_metadata" if metadata else "provider_family_inference",
    )


def runtime_capability_profile(
    planner_client: Callable[[str], str] | None = None,
    model_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the selected runtime's effective profile without trusting UI labels.

    Built clients expose the adapter-produced profile through ``resource_plan``.
    Record metadata is only a fallback for deterministic/rule paths where a model
    process was intentionally not started.
    """

    plan = getattr(planner_client, "resource_plan", {}) if planner_client is not None else {}
    if isinstance(plan, dict) and isinstance(plan.get("capability_profile"), dict):
        profile = dict(plan.get("capability_profile") or {})
        if profile:
            return profile

    record = dict(model_record or {}) if isinstance(model_record, dict) else {}
    explicit = (
        dict(record.get("capability_profile") or {})
        if isinstance(record.get("capability_profile"), dict)
        else {}
    )
    provider = _text(record.get("provider_code")).casefold()
    if not provider and any(
        _text(record.get(key))
        for key in ("local_path", "model_path", "gguf_path", "filename", "repo_id")
    ):
        provider = "local"
    if not provider and not explicit:
        return {}

    inferred_record = dict(record)
    inferred_record["provider_code"] = provider
    inferred_record.setdefault(
        "default_model",
        _text(
            record.get("filename")
            or record.get("repo_id")
            or record.get("local_path")
            or record.get("model_path")
        ),
    )
    inferred = capability_profile_from_record(
        inferred_record,
        reasoning=(
            dict(record.get("reasoning_capabilities") or {})
            if isinstance(record.get("reasoning_capabilities"), dict)
            else {}
        ),
        native_tool_runtime_enabled=bool(
            record.get("native_tool_runtime_enabled", False)
            and planner_client is not None
            and callable(getattr(planner_client, "invoke_tools", None))
        ),
        structured_output_runtime_enabled=bool(
            record.get("structured_output_runtime_enabled", False)
            and planner_client is not None
            and callable(getattr(planner_client, "invoke_structured", None))
        ),
    ).to_dict()
    inferred.update(explicit)
    native_preference = bool(record.get("native_tool_runtime_enabled", True))
    structured_preference = bool(
        record.get("structured_output_runtime_enabled", True)
    )
    wired_native = bool(
        planner_client is not None
        and callable(getattr(planner_client, "invoke_tools", None))
        and inferred.get("native_tool_calling_available") is True
        and native_preference
    )
    wired_structured = bool(
        planner_client is not None
        and callable(getattr(planner_client, "invoke_structured", None))
        and inferred.get("structured_output_available") is True
        and structured_preference
    )
    inferred["native_tool_runtime_enabled"] = wired_native
    inferred["structured_output_runtime_enabled"] = wired_structured
    degradation = _text(inferred.get("degradation_mode")).casefold()
    if wired_native and wired_structured:
        degradation = DEGRADATION_NATIVE_TOOLS
    elif wired_structured:
        degradation = DEGRADATION_STRUCTURED_PLAN
    elif degradation in {DEGRADATION_NATIVE_TOOLS, DEGRADATION_STRUCTURED_PLAN}:
        degradation = DEGRADATION_TEXT_GUARDED if inferred.get("chat", True) else DEGRADATION_CHAT_ONLY
    inferred["degradation_mode"] = degradation
    if degradation == DEGRADATION_CHAT_ONLY:
        inferred["prepare_write_allowed"] = False
        inferred["external_write_planning_allowed"] = False
    elif degradation == DEGRADATION_TEXT_GUARDED:
        inferred["prepare_write_allowed"] = True
        inferred["external_write_planning_allowed"] = False
    else:
        inferred["prepare_write_allowed"] = True
        inferred["external_write_planning_allowed"] = True
    return inferred


def record_provider_structured_contract_validation_failure(
    planner_client: Callable[[str], str] | None,
    reason: str,
) -> bool:
    """Remember a schema-invalid structured response for this exact client.

    Transport success alone is not proof that the structured contract worked.
    The owning parser calls this only after the returned body fails JSON/top-level
    schema validation.  It records no response content and does not change model,
    provider, fallback, business intent, or operation selection.
    """

    if planner_client is None:
        return False
    plan = getattr(planner_client, "resource_plan", {})
    if not isinstance(plan, dict):
        return False
    if _text(plan.get("last_invocation_contract")).casefold() != "structured_output":
        return False
    clean_reason = _text(reason)[:240] or "structured_contract_validation_failed"
    plan["structured_output_validation_failure"] = {
        "reason": clean_reason,
        "requested_model": _text(plan.get("requested_model")),
    }
    setattr(planner_client, "resource_plan", plan)
    _remember_structured_contract_degradation(
        planner_client,
        clean_reason,
    )
    return True


def guarded_json_prompt(prompt: str, schema: dict[str, Any] | None) -> str:
    """Preserve the response contract on every text recovery transport."""
    if not schema:
        return prompt
    suffix = "\n\n" + "\n".join([
        "GUARDED JSON RESPONSE CONTRACT (authoritative):",
        "Return exactly one JSON object, without markdown or prose, that conforms to every type, enum, required field and additionalProperties rule in this schema:",
        json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    ])
    return prompt if prompt.endswith(suffix) else prompt.rstrip() + suffix


def invoke_provider_planner(
    planner_client: Callable[[str], str],
    prompt: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    response_schema: dict[str, Any] | None = None,
    prefer_guarded_json: bool = False,
) -> str:
    """Invoke the strongest *actually wired* planner contract for this client.

    Capability metadata alone never selects a native path. The built client must
    expose the corresponding callable and its effective runtime profile must say
    that the path is enabled. Otherwise planning stays on the guarded text path.
    """

    profile = runtime_capability_profile(planner_client, None)
    native_method = getattr(planner_client, "invoke_tools", None)
    if (
        tools
        and profile.get("native_tool_runtime_enabled") is True
        and callable(native_method)
    ):
        return str(native_method(prompt, tools=list(tools)) or "")

    guarded_json_method = getattr(planner_client, "invoke_json_text", None)

    def structured_contract_degraded_reason() -> str:
        """Return a same-client structured-contract failure already recovered.

        A provider can advertise JSON schema support while the selected route
        repeatedly returns an empty structured body.  Once that exact model
        has recovered through the verified guarded-JSON channel, re-entering
        the failed wire contract for every later planner phase only burns the
        shared turn deadline.  This is transport health, not a business or
        model decision, so the same provider-independent planner may remember
        it for the lifetime of the client.
        """

        plan = getattr(planner_client, "resource_plan", {})
        if not isinstance(plan, dict):
            return ""
        cached_reason = _cached_structured_contract_degradation(
            planner_client
        )
        if cached_reason:
            plan["structured_output_health_cache_hit"] = True
            plan["structured_output_health_cache_reason"] = cached_reason
            setattr(planner_client, "resource_plan", plan)
            return cached_reason
        validation_failure = plan.get("structured_output_validation_failure")
        if isinstance(validation_failure, dict):
            failed_model = _text(
                validation_failure.get("requested_model")
            ).casefold()
            current_model = _text(plan.get("requested_model")).casefold()
            if not failed_model or not current_model or failed_model == current_model:
                return (
                    _text(validation_failure.get("reason"))
                    or "structured_contract_validation_failed"
                )
        outcomes = [
            dict(row)
            for row in list(plan.get("invocation_outcome_history") or [])
            if isinstance(row, dict)
        ]
        for index in range(len(outcomes) - 1, -1, -1):
            row = outcomes[index]
            if _text(row.get("contract")).casefold() != "structured_output":
                continue
            if row.get("response_received") is True:
                return ""
            requested_model = _text(row.get("requested_model")).casefold()
            recovered = next(
                (
                    later
                    for later in outcomes[index + 1 :]
                    if _text(later.get("contract")).casefold()
                    in {"json_text_guarded", "text"}
                    and later.get("response_received") is True
                    and not later.get("fallback_used")
                    and (
                        not requested_model
                        or _text(later.get("requested_model")).casefold()
                        == requested_model
                    )
                ),
                None,
            )
            if recovered is not None:
                return _text(row.get("error_reason")) or "structured_no_response"
            fallback_reason = _text(
                plan.get("structured_output_fallback_reason")
            )
            if fallback_reason:
                # Entering the guarded path proves that the native structured
                # wire contract already failed. The guarded request can then
                # hit the overall turn deadline independently; requiring it
                # to succeed before remembering native health makes every
                # fresh process burn the same known-bad first request again.
                return fallback_reason
            return ""
        return ""

    def invoke_guarded_json() -> str:
        guarded_prompt = guarded_json_prompt(prompt, response_schema)
        return str(
            guarded_json_method(
                guarded_prompt,
                schema=dict(response_schema or {}),
            )
            or ""
        )

    # A bounded repair follows an already-failed structured response from the
    # same exact model. Re-entering the same structured channel can spend a
    # second full request timeout before its built-in guarded degradation and
    # starve the actual GoalPlan call. The caller may therefore request the
    # already-wired guarded JSON contract directly; model/provider identity,
    # schema authority and fallback policy remain unchanged.
    if (
        prefer_guarded_json
        and response_schema
        and callable(guarded_json_method)
    ):
        return invoke_guarded_json()

    degraded_reason = structured_contract_degraded_reason()
    if response_schema and callable(guarded_json_method) and degraded_reason:
        plan = getattr(planner_client, "resource_plan", {})
        if isinstance(plan, dict):
            plan["structured_output_bypassed"] = True
            plan["structured_output_bypass_reason"] = degraded_reason
            plan["structured_output_bypass_contract"] = (
                "same_exact_model_json_text_guarded"
            )
            setattr(planner_client, "resource_plan", plan)
        return invoke_guarded_json()

    structured_method = getattr(planner_client, "invoke_structured", None)
    if (
        profile.get("structured_output_runtime_enabled") is True
        and callable(structured_method)
    ):
        try:
            answer = str(
                structured_method(
                    prompt,
                    schema=dict(response_schema or {}),
                )
                or ""
            )
        except Exception:
            failed_reason = structured_contract_degraded_reason()
            if failed_reason:
                _remember_structured_contract_degradation(
                    planner_client,
                    failed_reason,
                )
            raise
        recovered_reason = structured_contract_degraded_reason()
        if recovered_reason:
            _remember_structured_contract_degradation(
                planner_client,
                recovered_reason,
            )
        return answer
    if response_schema and callable(guarded_json_method):
        return invoke_guarded_json()
    return str(planner_client(prompt) or "")


def evaluate_model_capability_gate(
    profile: dict[str, Any] | ModelCapabilityProfile | None,
    *,
    prepare_write: bool,
    external_write: bool,
    decision_source: str,
) -> ModelCapabilityGate:
    """Apply controlled degradation before a model-originated operation executes.

    ``external_write_planning_allowed`` governs plans authored by the model. A
    text-guarded model may still use the deterministic parser/validator path when
    ``prepare_write_allowed`` is true; it never receives implicit execute authority.
    """

    if isinstance(profile, ModelCapabilityProfile):
        payload = profile.to_dict()
    else:
        payload = dict(profile or {}) if isinstance(profile, dict) else {}
    source = _text(decision_source).casefold()
    degradation = _text(payload.get("degradation_mode")).casefold()
    if not prepare_write:
        return ModelCapabilityGate(
            allowed=True,
            enforced=bool(payload),
            degradation_mode=degradation,
            decision_source=source,
        )
    if not payload:
        return ModelCapabilityGate(
            allowed=True,
            enforced=False,
            prepare_write=True,
            external_write=bool(external_write),
            decision_source=source,
        )
    if payload.get("prepare_write_allowed") is not True:
        return ModelCapabilityGate(
            allowed=False,
            enforced=True,
            code="prepare_write_disabled",
            message=(
                "Seçili modelin güvenli capability profili bu işlem için prepare "
                "oluşturmaya izin vermiyor. Bu modelle yalnızca read ve sohbet "
                "işlemleri kullanılabilir."
            ),
            degradation_mode=degradation,
            prepare_write=True,
            external_write=bool(external_write),
            decision_source=source,
        )
    if (
        external_write
        and source in {"llm", "model", "model_plan"}
        and payload.get("external_write_planning_allowed") is not True
    ):
        return ModelCapabilityGate(
            allowed=False,
            enforced=True,
            code="external_write_model_plan_disabled",
            message=(
                "Seçili model dış etkili bir işlemi doğrudan planlayacak güvenlik "
                "yeteneğine sahip değil. İstek ancak deterministik parser/validator "
                "yoluyla yeniden hazırlanabilir."
            ),
            degradation_mode=degradation,
            prepare_write=True,
            external_write=True,
            decision_source=source,
        )
    return ModelCapabilityGate(
        allowed=True,
        enforced=True,
        degradation_mode=degradation,
        prepare_write=True,
        external_write=bool(external_write),
        decision_source=source,
    )


class ProviderAdapter(ABC):
    code: str
    family: str

    @abstractmethod
    def build_chat_client(self, record: dict[str, Any], *, timeout: float) -> Callable[[str], str] | None:
        raise NotImplementedError

    @abstractmethod
    def capability_profile(self, record: dict[str, Any]) -> ModelCapabilityProfile:
        raise NotImplementedError

    def normalize_error(self, exc: Exception) -> NormalizedProviderError:
        return normalize_provider_error(self.code, exc)


@dataclass(frozen=True)
class CallableProviderAdapter(ProviderAdapter):
    code: str
    family: str
    client_factory: Callable[[dict[str, Any], float], Callable[[str], str] | None]
    capability_factory: Callable[[dict[str, Any]], ModelCapabilityProfile]

    def build_chat_client(self, record: dict[str, Any], *, timeout: float) -> Callable[[str], str] | None:
        return self.client_factory(dict(record or {}), float(timeout))

    def capability_profile(self, record: dict[str, Any]) -> ModelCapabilityProfile:
        return self.capability_factory(dict(record or {}))


class ProviderAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter, *aliases: str) -> None:
        for code in (adapter.code, *aliases):
            clean = _text(code).casefold()
            if clean:
                self._adapters[clean] = adapter

    def get(self, provider_code: str) -> ProviderAdapter | None:
        return self._adapters.get(_text(provider_code).casefold())

    def require(self, provider_code: str) -> ProviderAdapter:
        adapter = self.get(provider_code)
        if adapter is None:
            raise ValueError(f"Provider adapter is not registered: {provider_code}")
        return adapter

    def codes(self) -> list[str]:
        return sorted(self._adapters)
