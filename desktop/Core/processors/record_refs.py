from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class RecordRef:
    """Domain kayıtlarını sıra numarası veya görünen metinden bağımsız tanımlar."""

    domain: str
    record_type: str
    record_id: str
    source: str
    account: str
    environment: str
    identifiers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _compact_text(self.domain):
            raise ValueError("RecordRef domain is required.")
        if not _compact_text(self.record_type):
            raise ValueError("RecordRef record_type is required.")
        if not _compact_text(self.record_id):
            raise ValueError("RecordRef record_id is required.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "source": self.source,
            "account": self.account,
            "environment": self.environment,
            "identifiers": dict(self.identifiers or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RecordRef":
        return cls(
            domain=_compact_text(payload.get("domain")),
            record_type=_compact_text(payload.get("record_type")),
            record_id=_compact_text(payload.get("record_id")),
            source=_compact_text(payload.get("source")) or "unknown",
            account=_compact_text(payload.get("account")) or "unknown",
            environment=_compact_text(payload.get("environment")) or "unknown",
            identifiers={
                _compact_text(key): _compact_text(value)
                for key, value in dict(payload.get("identifiers") or {}).items()
                if _compact_text(key) and _compact_text(value)
            },
        )
