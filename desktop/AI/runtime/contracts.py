"""Tool contracts are shared by providers, runtime and business adapters."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from Feedback.processors.pipeline import Result


@dataclass(frozen=True)
class OperationInputSource:
    """Trusted registry contract for an input produced by completed operations.

    Explicit producer IDs require their contracts to accompany this operation
    in the planner catalog. An empty tuple permits any completed operation of
    the declared effect class; it does not require every read tool to be shown.
    """

    argument_path: str
    producer_operation_ids: tuple[str, ...] = ()
    result_path: str = "tool_result"
    required: bool = True
    producer_effect_class: str = "read"

    def to_dict(self) -> dict[str, Any]:
        return {
            "argument_path": self.argument_path,
            "producer_operation_ids": list(self.producer_operation_ids),
            "result_path": self.result_path,
            "required": self.required,
            "producer_effect_class": self.producer_effect_class,
            "binding_kind": "completed_step_output",
        }


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Result]
    domain: str = "general"
    read_only: bool = True
    destructive: bool = False
    risk_level: str = "low"
    requires_approval: bool = False
    action_type: str = "read"
    result_schema: dict[str, Any] | None = None
    canonical_callable: str = ""
    input_source_requirements: tuple[OperationInputSource, ...] = ()
