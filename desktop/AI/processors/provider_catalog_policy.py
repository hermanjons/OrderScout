from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


GEMINI_PRICING_SOURCE_URL = "https://ai.google.dev/gemini-api/docs/pricing"
GEMINI_PRICING_REVIEWED_AT = "2026-07-21"
FREE_MODEL_QUALITY_POLICY_SOURCE = "orderscout_user_selected_free_model_policy"
FREE_MODEL_QUALITY_POLICY_REVIEWED_AT = "2026-07-27"

# The Gemini models endpoint does not expose billing-tier metadata.  Keep the
# conservative, reviewed policy in one place: an unknown model must never be
# advertised or selected as free merely because it supports generateContent.
_GEMINI_VERIFIED_FREE_CHAT_MODELS = frozenset(
    {
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite-preview-09-2025",
    }
)

_GEMINI_VERIFIED_NON_FREE_MODELS = frozenset(
    {
        "gemini-omni-flash-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview-customtools",
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-lite-image",
        "gemini-3-pro-image",
        "gemini-2.5-flash-image",
        "gemini-2.5-computer-use-preview-10-2025",
    }
)

# Ordered only as a safe no-catalog fallback pool.  Live acceptance routing is
# still derived from the account's live catalog and measured quality evidence.
_GEMINI_SAFE_FALLBACK_ORDER = (
    "gemini-3.5-flash",
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash-lite-preview-09-2025",
)

# Live provider catalogs expose capability and pricing metadata, not a reliable
# intelligence ranking. Keep the user-selected free-model preference in this
# single provider-policy boundary. Unknown/new models remain eligible but use
# capability/quality evidence inside tier 0 until explicitly measured.
_PROVIDER_FREE_MODEL_QUALITY_TIERS: dict[str, dict[str, int]] = {
    "gemini": {
        "gemini-3.5-flash": 100,
        "gemini-3-flash-preview": 90,
        "gemini-2.5-pro": 85,
        "gemini-3.1-flash-lite": 80,
        "gemini-2.5-flash": 75,
        "gemini-2.5-flash-lite": 65,
        "gemini-2.5-flash-lite-preview-09-2025": 60,
        "gemma-4-31b-it": 50,
        "gemma-4-26b-a4b-it": 45,
    },
    "openrouter": {
        "nvidia/nemotron-3-ultra-550b-a55b:free": 100,
        "nvidia/nemotron-3-super-120b-a12b:free": 90,
        "google/gemma-4-31b-it:free": 80,
        "google/gemma-4-26b-a4b-it:free": 75,
        "openai/gpt-oss-20b:free": 70,
        "nvidia/nemotron-nano-9b-v2:free": 55,
    },
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _pricing_number(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


@dataclass(frozen=True)
class ProviderModelAccess:
    provider_code: str
    model_id: str
    is_free: bool
    free_tier_status: str
    chat_eligible: bool
    pricing_label: str
    policy_source: str = ""
    policy_reviewed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _gemini_chat_eligible(model_id: str) -> bool:
    clean = _text(model_id).casefold().removeprefix("models/")
    if not clean:
        return False
    if clean.startswith("gemma-4-"):
        return True
    disallowed_markers = (
        "-image",
        "-tts",
        "live-translate",
        "flash-live",
        "native-audio",
        "computer-use",
        "robotics",
        "embedding",
        "imagen",
        "veo",
        "lyria",
    )
    return clean.startswith("gemini-") and not any(
        marker in clean for marker in disallowed_markers
    )


def provider_model_access(
    provider_code: str,
    model_id: str,
    *,
    pricing: dict[str, Any] | None = None,
) -> ProviderModelAccess:
    provider = _text(provider_code).casefold()
    clean_model = _text(model_id).removeprefix("models/")
    normalized_model = clean_model.casefold()

    if provider == "gemini":
        if normalized_model in _GEMINI_VERIFIED_FREE_CHAT_MODELS:
            status = "verified_free"
            is_free = True
        elif normalized_model.startswith("gemma-4-"):
            # Google's pricing page classifies the complete Gemma 4 family as
            # free-only in the Developer API.
            status = "verified_free"
            is_free = True
        elif normalized_model in _GEMINI_VERIFIED_NON_FREE_MODELS:
            status = "verified_not_free"
            is_free = False
        else:
            status = "unknown"
            is_free = False
        return ProviderModelAccess(
            provider_code=provider,
            model_id=clean_model,
            is_free=is_free,
            free_tier_status=status,
            chat_eligible=_gemini_chat_eligible(clean_model),
            pricing_label=(
                "verified free tier"
                if is_free
                else "not free"
                if status == "verified_not_free"
                else "pricing unverified"
            ),
            policy_source=GEMINI_PRICING_SOURCE_URL,
            policy_reviewed_at=GEMINI_PRICING_REVIEWED_AT,
        )

    if provider == "openrouter":
        is_free = normalized_model.endswith(":free")
        return ProviderModelAccess(
            provider_code=provider,
            model_id=clean_model,
            is_free=is_free,
            free_tier_status="provider_variant_free" if is_free else "priced",
            chat_eligible=True,
            pricing_label="free" if is_free else "priced",
        )

    clean_pricing = dict(pricing or {})
    charge_keys = (
        "prompt",
        "completion",
        "request",
        "image",
        "web_search",
        "internal_reasoning",
    )
    priced_fields = [key for key in charge_keys if key in clean_pricing]
    is_free = bool(priced_fields) and all(
        _pricing_number(clean_pricing.get(key)) == 0 for key in priced_fields
    )
    prompt = _pricing_number(clean_pricing.get("prompt"))
    completion = _pricing_number(clean_pricing.get("completion"))
    if is_free:
        label = "free"
    elif prompt or completion:
        label = f"prompt {prompt:g} / completion {completion:g}"
    else:
        label = "priced"
    return ProviderModelAccess(
        provider_code=provider,
        model_id=clean_model,
        is_free=is_free,
        free_tier_status="verified_zero_pricing" if is_free else "priced",
        chat_eligible=True,
        pricing_label=label,
    )


def gemini_safe_fallback_models() -> tuple[str, ...]:
    return _GEMINI_SAFE_FALLBACK_ORDER


def gemini_model_is_verified_free_chat(model_id: str) -> bool:
    access = provider_model_access("gemini", model_id)
    return bool(access.is_free and access.chat_eligible)


def provider_free_model_quality_prior(
    provider_code: str,
    model_id: str,
) -> dict[str, Any]:
    provider = _text(provider_code).casefold()
    clean_model = _text(model_id).casefold().removeprefix("models/")
    tier = _PROVIDER_FREE_MODEL_QUALITY_TIERS.get(provider, {}).get(
        clean_model,
        0,
    )
    return {
        "quality_tier": int(tier),
        # A reviewed preference order is not a measured quality score.
        "quality_score": 0.0,
        "quality_source": (
            FREE_MODEL_QUALITY_POLICY_SOURCE if tier > 0 else "unmeasured"
        ),
        "quality_reviewed_at": (
            FREE_MODEL_QUALITY_POLICY_REVIEWED_AT if tier > 0 else ""
        ),
    }
