from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from Core.processors.operation_contracts import OperationMetadata, OperationResultEnvelope
from AI.processors.session_state import PendingActionSnapshot
from Feedback.processors.pipeline import Result


ACTION_STATUS_PENDING_APPROVAL = "pending_approval"
ACTION_STATUS_EXECUTED = "executed"
ACTION_TYPE_PREPARE_WRITE = "prepare_write"
ACTION_TYPE_EXECUTE_WRITE = "execute_write"


@dataclass(frozen=True)
class AgentOperationPolicy:
    domain: str
    tool: str
    action_type: str
    risk_level: str = "medium"
    requires_approval: bool = True
    destructive: bool = False
    external_write: bool = False

    def operation_metadata(self) -> OperationMetadata:
        risk_level = "R2" if self.external_write else "R1"
        return OperationMetadata(
            name=self.action_type or self.tool,
            version="1.0",
            owner_domain=self.domain,
            effect_class="external_mutation" if self.external_write else "local_effect",
            input_schema={"type": "object", "additionalProperties": True},
            output_schema={"type": "object", "additionalProperties": True},
            environment_scope=("production", "stage") if self.external_write else ("local",),
            account_scope="runtime_resolved",
            risk_level=risk_level,
            approval_policy="prepare_then_confirm",
            idempotency="key_required" if self.external_write else "operation_defined",
            retry_behavior="never_without_idempotency" if self.external_write else "operation_defined",
            supports_prepare=True,
            supports_execute=True,
            supports_verify=True,
            supports_cancellation=True,
            supports_progress=True,
            sensitive_fields=("credentials", "api_key", "api_secret", "token", "password"),
        )


def compact_text(value: Any) -> str:
    return str(value or "").strip()


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for key, new_value in dict(after or {}).items():
        old_value = dict(before or {}).get(key)
        if old_value != new_value:
            changes[str(key)] = {"before": old_value, "after": new_value}
    return changes


def build_approval_action(
    *,
    policy: AgentOperationPolicy,
    title: str,
    summary: str,
    arguments: dict[str, Any],
    rows: list[dict[str, Any]],
    warnings: list[str] | None = None,
    execute_enabled: bool = False,
    selection_id: str = "",
) -> dict[str, Any]:
    operation = policy.operation_metadata()
    action = {
        "approval_required": bool(policy.requires_approval),
        "status": ACTION_STATUS_PENDING_APPROVAL,
        "domain": policy.domain,
        "action_type": policy.action_type,
        "title": title,
        "summary": summary,
        "risk_level": policy.risk_level,
        "tool": policy.tool,
        "operation_metadata": operation.to_dict(),
        "arguments": dict(arguments or {}),
        "rows": list(rows or []),
        "warnings": list(warnings or []),
        "execute_enabled": bool(execute_enabled),
        "api_call_performed": False,
        "db_write_performed": False,
        "external_write": bool(policy.external_write),
        "destructive": bool(policy.destructive),
        "next_step": "Kullanici onayi olmadan gercek API istegi veya DB yazimi yapilmaz.",
    }
    if compact_text(selection_id):
        action["selection_id"] = compact_text(selection_id)
    return PendingActionSnapshot.from_action(action).to_action(action)


def prepare_result(
    *,
    policy: AgentOperationPolicy,
    message: str,
    action: dict[str, Any],
    data: dict[str, Any] | None = None,
) -> Result:
    operation = policy.operation_metadata()
    envelope = OperationResultEnvelope(
        operation_name=operation.name,
        operation_version=operation.version,
        success=True,
        status=ACTION_STATUS_PENDING_APPROVAL,
        message=message,
        data={"approval_required": bool(policy.requires_approval)},
        scope={
            "domain": policy.domain,
            "environment_scope": list(operation.environment_scope),
            "account_scope": operation.account_scope,
        },
        retryable=False,
    )
    payload = {
        "approval_required": bool(policy.requires_approval),
        "api_call_performed": False,
        "db_write_performed": False,
        "tool": policy.tool,
        "action": dict(action or {}),
        "operation_result": envelope.to_dict(),
    }
    payload.update(dict(data or {}))
    return Result.ok(message, close_dialog=False, data=payload)
