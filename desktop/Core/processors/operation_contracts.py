from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


OPERATION_EFFECT_CLASSES = frozenset({"read", "local_effect", "external_mutation"})
OPERATION_RISK_LEVELS = frozenset({"R0", "R1", "R2", "R3"})
OPERATION_APPROVAL_POLICIES = frozenset(
    {"none", "prepare_then_confirm", "supervised_only"}
)


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_text_tuple(values: Any) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            _compact_text(value)
            for value in list(values or [])
            if _compact_text(value)
        )
    )


@dataclass(frozen=True)
class OperationMetadata:
    """Provider/UI bağımsız, discoverable operation catalog sözleşmesi."""

    name: str
    version: str
    owner_domain: str
    effect_class: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    record_ref_types: tuple[str, ...] = ()
    environment_scope: tuple[str, ...] = ()
    account_scope: str = "none"
    risk_level: str = "R0"
    approval_policy: str = "none"
    idempotency: str = "safe"
    retry_behavior: str = "safe"
    supports_prepare: bool = False
    supports_execute: bool = True
    supports_verify: bool = False
    timeout_seconds: int = 30
    supports_cancellation: bool = False
    supports_progress: bool = False
    sensitive_fields: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _compact_text(self.name):
            raise ValueError("Operation name is required.")
        if not _compact_text(self.version):
            raise ValueError("Operation version is required.")
        if not _compact_text(self.owner_domain):
            raise ValueError("Operation owner_domain is required.")
        if self.effect_class not in OPERATION_EFFECT_CLASSES:
            raise ValueError(f"Unsupported operation effect_class: {self.effect_class}")
        if self.risk_level not in OPERATION_RISK_LEVELS:
            raise ValueError(f"Unsupported operation risk_level: {self.risk_level}")
        if self.approval_policy not in OPERATION_APPROVAL_POLICIES:
            raise ValueError(
                f"Unsupported operation approval_policy: {self.approval_policy}"
            )
        if self.effect_class == "read" and self.risk_level != "R0":
            raise ValueError("Read operations must use risk level R0.")
        if self.effect_class != "read" and self.approval_policy == "none":
            raise ValueError("Effectful operations require an approval policy.")
        if int(self.timeout_seconds) <= 0:
            raise ValueError("Operation timeout_seconds must be positive.")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "record_ref_types",
            "environment_scope",
            "sensitive_fields",
            "required_capabilities",
        ):
            payload[key] = list(payload[key])
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OperationMetadata":
        values = dict(payload or {})
        for key in (
            "record_ref_types",
            "environment_scope",
            "sensitive_fields",
            "required_capabilities",
        ):
            values[key] = _clean_text_tuple(values.get(key))
        return cls(**values)


@dataclass(frozen=True)
class OperationResultEnvelope:
    """Domain Result nesnelerinin agent/runtime sınırındaki ortak görünümü."""

    operation_name: str
    operation_version: str
    success: bool
    status: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    record_refs: tuple[dict[str, Any], ...] = ()
    scope: dict[str, Any] = field(default_factory=dict)
    selected_record_count: int | None = None
    preview_item_count: int | None = None
    execute_input_count: int | None = None
    retryable: bool = False
    verification: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""

    def invariant_problems(self) -> list[str]:
        problems: list[str] = []
        counts = {
            "selected_record_count": self.selected_record_count,
            "preview_item_count": self.preview_item_count,
            "execute_input_count": self.execute_input_count,
        }
        present = {key: value for key, value in counts.items() if value is not None}
        if present and len(set(present.values())) != 1:
            problems.append("selection_preview_execute_count_mismatch")
        if self.selected_record_count is not None and self.record_refs:
            if int(self.selected_record_count) != len(self.record_refs):
                problems.append("selected_record_count_record_refs_mismatch")
        return problems

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["record_refs"] = [dict(row) for row in self.record_refs]
        payload["invariant_problems"] = self.invariant_problems()
        return payload
