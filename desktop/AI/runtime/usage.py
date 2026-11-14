"""Value-free request sizes and provider-reported usage, including retries."""
from AI.runtime.context_window import json_bytes


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def record_provider_usage(client, request, response, *, family):
    plan = getattr(client, "resource_plan", None)
    if not isinstance(plan, dict):
        return
    usage = response.get("usageMetadata" if family == "gemini" else "usage") or {}
    usage = usage if isinstance(usage, dict) else {}
    if family == "gemini":
        input_tokens = _number(usage.get("promptTokenCount"))
        output_tokens = _number(usage.get("candidatesTokenCount"))
        cached = _number(usage.get("cachedContentTokenCount"))
        reasoning = _number(usage.get("thoughtsTokenCount"))
        if output_tokens is not None:
            output_tokens += reasoning or 0
    elif family == "anthropic":
        input_tokens = _number(usage.get("input_tokens"))
        cached = _number(usage.get("cache_read_input_tokens"))
        created = _number(usage.get("cache_creation_input_tokens"))
        if input_tokens is not None:
            input_tokens += (cached or 0) + (created or 0)
        output_tokens = _number(usage.get("output_tokens"))
        reasoning = None
    else:
        input_tokens = _number(usage.get("prompt_tokens", usage.get("input_tokens")))
        output_tokens = _number(usage.get("completion_tokens", usage.get("output_tokens")))
        prompt_details = usage.get("prompt_tokens_details")
        completion_details = usage.get("completion_tokens_details")
        cached = _number(prompt_details.get("cached_tokens")) if isinstance(prompt_details, dict) else None
        reasoning = _number(completion_details.get("reasoning_tokens")) if isinstance(completion_details, dict) else None
    row = {"provider_family": family, "model": response.get("model") or request.get("model"),
           "input_tokens": input_tokens, "output_tokens": output_tokens, "cached_input_tokens": cached,
           "reasoning_tokens": reasoning, "cost_usd": _number(usage.get("cost")),
           "request_bytes": json_bytes(request), "tool_schema_bytes": json_bytes(request.get("tools", [])),
           "usage_reported": input_tokens is not None or output_tokens is not None}
    totals = dict(plan.get("provider_usage_totals") or {})
    totals["response_count"] = totals.get("response_count", 0) + 1
    totals["responses_with_usage"] = totals.get("responses_with_usage", 0) + int(row["usage_reported"])
    for key in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "cost_usd"):
        if row[key] is not None:
            totals[key] = totals.get(key, 0) + row[key]
    plan["last_provider_usage"] = row
    plan["provider_usage_history"] = [*plan.get("provider_usage_history", []), row][-100:]
    plan["provider_usage_totals"] = totals
