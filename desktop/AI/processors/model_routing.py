from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def stable_state_hash(payload: dict[str, Any] | None) -> str:
    encoded = json.dumps(
        dict(payload or {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest()


@dataclass(frozen=True)
class FreeModelCandidate:
    provider_code: str
    model_id: str
    accessible: bool
    is_free: bool
    chat: bool
    native_tool_calling: bool
    structured_output: bool
    context_tokens: int
    output_tokens: int
    reasoning: bool
    quality_tier: int = 0
    quality_score: float = 0.0
    reliability_score: float = 0.0
    latency_ms: float | None = None
    quota_scope: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return bool(
            self.accessible
            and self.is_free
            and self.chat
            and self.context_tokens >= 8_192
            and self.output_tokens >= 512
        )

    @property
    def score(self) -> float:
        if not self.eligible:
            return -1_000_000.0
        capability_score = (
            (35.0 if self.native_tool_calling else 0.0)
            + (30.0 if self.structured_output else 0.0)
            + (12.0 if self.reasoning else 0.0)
        )
        context_score = min(20.0, self.context_tokens / 16_384.0)
        output_score = min(8.0, self.output_tokens / 1_024.0)
        latency_penalty = min(15.0, float(self.latency_ms or 0.0) / 2_000.0)
        return round(
            capability_score
            + context_score
            + output_score
            + float(self.quality_score) * 25.0
            + float(self.reliability_score) * 20.0
            - latency_penalty,
            6,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update({"eligible": self.eligible, "score": self.score})
        return payload


@dataclass(frozen=True)
class FreeModelTestRoute:
    provider_code: str
    candidates: tuple[FreeModelCandidate, ...]
    state_hash: str
    generated_from_live_catalog: bool

    @property
    def model_ids(self) -> tuple[str, ...]:
        return tuple(row.model_id for row in self.candidates if row.eligible)

    def transition_after_failure(
        self,
        *,
        current_model: str,
        quota_scope: str,
        reason: str,
        message_index: int,
        state_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current_state_hash = stable_state_hash(state_payload)
        if current_state_hash != self.state_hash:
            return {
                "status": "blocked_state_changed",
                "provider_code": self.provider_code,
                "requested_model": current_model,
                "next_model": "",
                "quota_scope": quota_scope or "unknown",
                "reason": reason,
                "message_index": int(message_index),
                "state_hash": current_state_hash,
                "expected_state_hash": self.state_hash,
            }
        scope = _text(quota_scope).casefold() or "unknown"
        if scope != "model":
            return {
                "status": "provider_paused",
                "provider_code": self.provider_code,
                "requested_model": current_model,
                "next_model": "",
                "quota_scope": scope,
                "reason": reason,
                "message_index": int(message_index),
                "state_hash": self.state_hash,
            }
        models = list(self.model_ids)
        clean_current = _text(current_model).removeprefix("models/")
        try:
            current_index = models.index(clean_current)
        except ValueError:
            current_index = -1
        next_model = models[current_index + 1] if current_index + 1 < len(models) else ""
        return {
            "status": "fallback_selected" if next_model else "route_exhausted",
            "provider_code": self.provider_code,
            "requested_model": clean_current,
            "next_model": next_model,
            "quota_scope": scope,
            "reason": reason,
            "message_index": int(message_index),
            "state_hash": self.state_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_code": self.provider_code,
            "generated_from_live_catalog": self.generated_from_live_catalog,
            "state_hash": self.state_hash,
            "models": [row.to_dict() for row in self.candidates],
            "model_ids": list(self.model_ids),
        }


def build_free_model_test_route(
    provider_code: str,
    records: list[dict[str, Any]],
    *,
    state_payload: dict[str, Any] | None = None,
    accessibility: dict[str, dict[str, Any]] | None = None,
    quality: dict[str, dict[str, Any]] | None = None,
    generated_from_live_catalog: bool = True,
) -> FreeModelTestRoute:
    provider = _text(provider_code).casefold()
    access = dict(accessibility or {})
    quality_rows = dict(quality or {})
    candidates: list[FreeModelCandidate] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        model_id = _text(record.get("id") or record.get("model_id")).removeprefix("models/")
        if not model_id:
            continue
        capability = dict(record.get("capability_profile") or {})
        access_row = dict(access.get(model_id) or {})
        quality_row = dict(quality_rows.get(model_id) or {})
        candidates.append(
            FreeModelCandidate(
                provider_code=provider,
                model_id=model_id,
                accessible=bool(access_row.get("accessible", record.get("accessible", True))),
                is_free=bool(record.get("is_free")),
                chat=bool(capability.get("chat", True)),
                native_tool_calling=bool(capability.get("native_tool_calling_available")),
                structured_output=bool(capability.get("structured_output_available")),
                context_tokens=int(capability.get("context_tokens") or record.get("context_length") or 0),
                output_tokens=int(capability.get("output_tokens") or record.get("output_token_limit") or 2_048),
                reasoning=bool((capability.get("reasoning") or {}).get("supported")),
                quality_tier=int(quality_row.get("quality_tier") or 0),
                quality_score=float(quality_row.get("quality_score") or 0.0),
                reliability_score=float(quality_row.get("reliability_score") or access_row.get("reliability_score") or 0.0),
                latency_ms=(
                    float(access_row.get("latency_ms"))
                    if access_row.get("latency_ms") not in (None, "")
                    else None
                ),
                quota_scope=_text(access_row.get("quota_scope")),
                metadata={
                    "pricing_label": record.get("pricing_label"),
                    "free_tier_status": record.get("free_tier_status"),
                    "pricing_policy_source": record.get("pricing_policy_source"),
                    "pricing_policy_reviewed_at": record.get("pricing_policy_reviewed_at"),
                    "supported_parameters": [
                        _text(value)
                        for value in list(record.get("supported_parameters") or [])
                        if _text(value)
                    ],
                    "supported_generation_methods": [
                        _text(value)
                        for value in list(record.get("supported_generation_methods") or [])
                        if _text(value)
                    ],
                    "input_modalities": [
                        _text(value)
                        for value in list(record.get("input_modalities") or [])
                        if _text(value)
                    ],
                    "reasoning": (
                        dict(record.get("reasoning") or {})
                        if isinstance(record.get("reasoning"), dict)
                        else {}
                    ),
                    "quality_source": _text(quality_row.get("quality_source")),
                    "quality_reviewed_at": _text(
                        quality_row.get("quality_reviewed_at")
                    ),
                },
            )
        )
    candidates.sort(
        key=lambda row: (
            not row.eligible,
            -int(row.quality_tier),
            -row.score,
            row.model_id.casefold(),
        )
    )
    return FreeModelTestRoute(
        provider_code=provider,
        candidates=tuple(candidates),
        state_hash=stable_state_hash(state_payload),
        generated_from_live_catalog=bool(generated_from_live_catalog),
    )
