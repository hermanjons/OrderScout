"""Pure argument validation and exact completed-source binding primitives.

This module has no intent, business plan, provider, UI or domain executor.
"""
from __future__ import annotations
from copy import deepcopy
import re
from typing import Any
from AI.processors.session_state import AgentTaskStep

_STEP_OUTPUT_BINDING_KEYS = frozenset({"$from_step", "path"})
_STEP_OUTPUT_PATH_PATTERN = re.compile(r"tool_result(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*")

def _compact_text(value):
    return str(value or "").strip()


def _is_step_output_binding(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and set(value) == _STEP_OUTPUT_BINDING_KEYS
        and _compact_text(value.get("$from_step"))
        and _compact_text(value.get("path"))
    )


def _argument_binding_problems(
    value: Any,
    *,
    allowed_source_steps: set[str],
    path: str = "arguments",
) -> list[str]:
    problems: list[str] = []
    if isinstance(value, dict):
        if "$from_step" in value or (
            "path" in value and set(value).issubset(_STEP_OUTPUT_BINDING_KEYS)
        ):
            if not _is_step_output_binding(value):
                return [f"{path}:invalid_step_output_binding"]
            source_step = _compact_text(value.get("$from_step"))
            source_path = _compact_text(value.get("path"))
            if source_step not in allowed_source_steps:
                problems.append(f"{path}:binding_source_not_dependency")
            if _STEP_OUTPUT_PATH_PATTERN.fullmatch(source_path) is None:
                problems.append(f"{path}:binding_path_not_allowed")
            return problems
        for name, child in value.items():
            problems.extend(
                _argument_binding_problems(
                    child,
                    allowed_source_steps=allowed_source_steps,
                    path=f"{path}.{name}",
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems.extend(
                _argument_binding_problems(
                    child,
                    allowed_source_steps=allowed_source_steps,
                    path=f"{path}[{index}]",
                )
            )
    elif isinstance(value, str) and value.strip().startswith("$from_step"):
        problems.append(f"{path}:step_output_binding_must_be_typed_object")
    return problems


def _schema_value_problems(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str,
    allow_step_bindings: bool = False,
) -> list[str]:
    """Small strict JSON-schema subset used at the direct operation boundary."""

    if allow_step_bindings and _is_step_output_binding(value):
        return []
    problems: list[str] = []
    schema_type = schema.get("type")
    allowed_types = (
        set(schema_type)
        if isinstance(schema_type, list)
        else {schema_type}
        if isinstance(schema_type, str)
        else set()
    )
    if value is None and "null" in allowed_types:
        return []
    type_ok = True
    if allowed_types:
        type_ok = any(
            (
                kind == "object" and isinstance(value, dict)
                or kind == "array" and isinstance(value, list)
                or kind == "string" and isinstance(value, str)
                or kind == "integer" and isinstance(value, int) and not isinstance(value, bool)
                or kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool)
                or kind == "boolean" and isinstance(value, bool)
                or kind == "null" and value is None
            )
            for kind in allowed_types
        )
    if not type_ok:
        return [f"{path}:type"]
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        problems.append(f"{path}:enum")
    if isinstance(value, dict):
        properties = (
            dict(schema.get("properties") or {})
            if isinstance(schema.get("properties"), dict)
            else {}
        )
        required = {
            _compact_text(name)
            for name in list(schema.get("required") or [])
            if _compact_text(name)
        }
        for name in sorted(required):
            if name not in value:
                problems.append(f"{path}.{name}:required")
        additional = schema.get("additionalProperties", True)
        for name, child in value.items():
            child_schema = properties.get(name)
            if isinstance(child_schema, dict):
                problems.extend(
                    _schema_value_problems(
                        child,
                        child_schema,
                        path=f"{path}.{name}",
                        allow_step_bindings=allow_step_bindings,
                    )
                )
            elif additional is False:
                problems.append(f"{path}.{name}:unknown")
            elif isinstance(additional, dict):
                problems.extend(
                    _schema_value_problems(
                        child,
                        additional,
                        path=f"{path}.{name}",
                        allow_step_bindings=allow_step_bindings,
                    )
                )
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value):
            problems.extend(
                _schema_value_problems(
                    child,
                    dict(schema.get("items") or {}),
                    path=f"{path}[{index}]",
                    allow_step_bindings=allow_step_bindings,
                )
            )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            problems.append(f"{path}:minimum")
        if isinstance(maximum, (int, float)) and value > maximum:
            problems.append(f"{path}:maximum")
    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            problems.append(f"{path}:minLength")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            problems.append(f"{path}:maxLength")
    return problems


def _tool_argument_problems(
    tool: Any,
    arguments: Any,
    *,
    allow_step_bindings: bool = False,
    allowed_source_steps: set[str] | None = None,
    dependency_output_fields: set[str] | None = None,
) -> list[str]:
    if not isinstance(arguments, dict):
        return ["arguments:type"]
    schema = tool.parameters if isinstance(tool.parameters, dict) else {}
    problems = _schema_value_problems(
        arguments,
        schema,
        path="arguments",
        allow_step_bindings=allow_step_bindings,
    )
    if allow_step_bindings:
        problems.extend(
            _argument_binding_problems(
                arguments,
                allowed_source_steps=set(allowed_source_steps or set()),
            )
        )
        produced_fields = set(dependency_output_fields or set())
        problems = [
            problem
            for problem in problems
            if not (
                problem.startswith("arguments.")
                and problem.endswith(":required")
                and problem[len("arguments.") : -len(":required")]
                in produced_fields
            )
        ]
    return list(dict.fromkeys(problems))


def _source_bound_operation_argument_problems(
    operation_id: str,
    arguments: dict[str, Any],
    dependency_ids: set[str],
    *,
    source_operations: dict[str, str] | None = None,
) -> list[str]:
    """Reject model-authored data at generic computation/artifact boundaries."""
    problems: list[str] = []
    if operation_id in {"reports.build_snapshot", "analysis.calculate", "analysis.table"}:
        if not isinstance(arguments.get("sources", []), list):
            return ["arguments.sources:type"]
        for index, raw_source in enumerate(list(arguments.get("sources") or [])):
            source = raw_source if isinstance(raw_source, dict) else {}
            source_id = _compact_text(source.get("source_step_id"))
            binding = source.get("result")
            prefix = f"arguments.sources[{index}].result"
            if not (
                source_id in dependency_ids
                and _is_step_output_binding(binding)
                and _compact_text(binding.get("$from_step")) == source_id
                and binding.get("path") == "tool_result"
            ):
                problems.append(f"{prefix}:binding_requires_exact_source_result")
            actual_operation = (source_operations or {}).get(source_id)
            if actual_operation and source.get("operation_id") != actual_operation:
                problems.append(f"{prefix}:binding_source_operation_mismatch")
    elif operation_id == "web.research_report":
        if not isinstance(arguments.get("web_observations", []), list):
            return ["arguments.web_observations:type"]
        for index, binding in enumerate(list(arguments.get("web_observations") or [])):
            source_id = _compact_text(binding.get("$from_step")) if _is_step_output_binding(binding) else ""
            producer = (source_operations or {}).get(source_id)
            expected_path = ("tool_result.result.web_observation" if producer == "artifacts.read"
                             else "tool_result.web_observation")
            if (source_id not in dependency_ids or producer not in {
                    "web.open", "web.document.read", "web.follow", "artifacts.read"}
                    or not _is_step_output_binding(binding) or binding.get("path") != expected_path):
                problems.append(f"arguments.web_observations[{index}]:binding_requires_opened_observation")
    elif operation_id in {"reports.xlsx.prepare", "web.research_report_xlsx.prepare"}:
        binding = arguments.get("report_snapshot")
        source_id = _compact_text(binding.get("$from_step")) if isinstance(binding, dict) else ""
        if not (
            source_id in dependency_ids
            and _is_step_output_binding(binding)
            and binding.get("path") == "tool_result.report_snapshot"
        ):
            problems.append("arguments.report_snapshot:binding_requires_builder_snapshot")
        actual_operation = (source_operations or {}).get(source_id)
        expected_operation = "reports.build_snapshot" if operation_id == "reports.xlsx.prepare" else "web.research_report"
        if actual_operation and actual_operation != expected_operation:
            problems.append("arguments.report_snapshot:binding_source_operation_mismatch")
    return problems


def _resolve_step_output_path(
    source: AgentTaskStep,
    source_path: str,
) -> tuple[bool, Any]:
    normalized_path = _compact_text(source_path)
    if _STEP_OUTPUT_PATH_PATTERN.fullmatch(normalized_path) is None:
        return False, None
    parts = re.findall(
        r"[A-Za-z_][A-Za-z0-9_]*|\[\d+\]",
        normalized_path,
    )
    if not parts or parts[0] != "tool_result":
        return False, None
    current: Any = source.result_data
    for part in parts:
        if part.startswith("["):
            if not isinstance(current, (list, tuple)):
                return False, None
            index = int(part[1:-1])
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            if not isinstance(current, dict) or part not in current:
                return False, None
            current = current[part]
    return True, deepcopy(current)


def _resolve_argument_value(
    value: Any,
    *,
    dependencies: dict[str, AgentTaskStep],
    path: str,
    problems: list[str],
    bindings: dict[str, str],
) -> Any:
    if isinstance(value, dict):
        if "$from_step" in value or (
            "path" in value and set(value).issubset(_STEP_OUTPUT_BINDING_KEYS)
        ):
            if not _is_step_output_binding(value):
                problems.append(f"{path}:invalid_step_output_binding")
                return None
            source_id = _compact_text(value.get("$from_step"))
            source_path = _compact_text(value.get("path"))
            source = dependencies.get(source_id)
            if source is None:
                problems.append(f"{path}:binding_source_not_completed_dependency")
                return None
            found, resolved = _resolve_step_output_path(source, source_path)
            if not found:
                problems.append(f"{path}:binding_value_missing")
                return None
            binding_path = (
                path[len("arguments.") :]
                if path.startswith("arguments.")
                else path
            )
            bindings[binding_path] = f"{source_id}:{source_path}"
            return resolved
        return {
            name: _resolve_argument_value(
                child,
                dependencies=dependencies,
                path=f"{path}.{name}",
                problems=problems,
                bindings=bindings,
            )
            for name, child in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_argument_value(
                child,
                dependencies=dependencies,
                path=f"{path}[{index}]",
                problems=problems,
                bindings=bindings,
            )
            for index, child in enumerate(value)
        ]
    return deepcopy(value)
