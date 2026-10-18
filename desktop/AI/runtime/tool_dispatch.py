"""Trusted tool execution boundary, independent of business intent and prose."""
from __future__ import annotations
from copy import deepcopy
import inspect
from Feedback.processors.pipeline import Result
from AI.runtime.arguments import _resolve_argument_value, _source_bound_operation_argument_problems
from AI.runtime.schema import validate_tool_arguments


def execute_tool_call(state, step, tool, *, db_name, client, persist, root, progress_callback, task_control, registry, checkpoint):
    from AI.processors.observation_projection import source_projection_hash
    from AI.processors.source_policy import source_operation_problems
    completed = {row.step_id: row for row in state.completed_steps
                 if row.status == "completed" and row.verification_status in {"observed", "verified"}}
    dependencies = {key: completed[key] for key in step.depends_on if key in completed}
    errors = source_operation_problems(tool.name, state=state)
    if tool.requires_approval and state.active_entities.get("model_loop", {}).get("failed_effect_continuation"):
        errors.append("failed_effect_requires_new_user_instruction_before_prepare")
    for requirement in tool.input_source_requirements:
        if "[" in requirement.argument_path or "." in requirement.argument_path:
            continue  # Repeated source arguments have the native receipt check below.
        bound = step.arguments.get(requirement.argument_path)
        producer = dependencies.get(bound.get("$from_step")) if isinstance(bound, dict) else None
        if requirement.required and (producer is None or bound.get("path") != requirement.result_path
                or requirement.producer_operation_ids and producer.tool_names[0] not in requirement.producer_operation_ids):
            errors.append(f"{requirement.argument_path}:exact_declared_producer_required")
    errors.extend(_source_bound_operation_argument_problems(tool.name, step.arguments, set(dependencies),
        source_operations={key: row.tool_names[0] for key, row in dependencies.items() if len(row.tool_names) == 1}))
    bindings = {}
    arguments = _resolve_argument_value(deepcopy(step.arguments), dependencies=dependencies,
        path="arguments", problems=errors, bindings=bindings)
    # Child binding copies only model arguments. Trusted state/callbacks must
    # retain their real identity and are injected after this copying boundary.
    from AI.processors.child_task_runtime import bind_child_read_arguments, child_observation_problems
    arguments, child_errors = bind_child_read_arguments(tool, arguments)
    errors.extend(child_errors)
    if tool.name in {"files.read", "files.list"}:
        workspace = state.active_entities.get("file_workspace") or {}
        if not workspace.get("session_id"):
            errors.append("file_workspace_not_imported")
        else:
            arguments["session_id"] = workspace["session_id"]
            authorized = {row.get("attachment_id") for row in workspace.get("attachments", []) if isinstance(row, dict)}
            if tool.name == "files.read" and arguments.get("attachment_id") not in authorized:
                errors.append("attachment_not_authorized")
    errors.extend(validate_tool_arguments(tool, arguments))
    if errors:
        return Result.fail("Araç girdileri doğrulanamadı.", close_dialog=False,
                           data={"tool": tool.name, "argument_problems": errors})
    if tool.name in {"reports.build_snapshot", "analysis.calculate", "analysis.table"}:
        for index, source in enumerate(arguments.get("sources") or []):
            observed = dependencies.get(source.get("source_step_id"))
            producer = registry.get(source.get("operation_id"))
            if (observed is None or producer is None or producer.requires_approval or not producer.read_only
                    or observed.tool_names != [producer.name]
                    or source_projection_hash(source.get("result")) != source_projection_hash(observed.result_data.get("tool_result"))):
                errors.append(f"sources[{index}]:exact_observed_read_required")
    if errors:
        return Result.fail("Araç girdileri doğrulanamadı.", close_dialog=False,
                           data={"tool": tool.name, "argument_problems": errors})
    if tool.requires_approval:
        from AI.processors.semantic_verifier import _configuration_schemas, verify_plan_step_semantics
        if _configuration_schemas(arguments):
            checked = verify_plan_step_semantics(state, step, tool, verifier_client=client)
            if not checked.success:
                return checked
    invocation = deepcopy(arguments)
    if "db_name" in inspect.signature(tool.handler).parameters:
        invocation["db_name"] = db_name
    if tool.name == "artifacts.read":
        invocation["session_id"] = state.session_id
        invocation["authorized_capabilities"] = [deepcopy(row) for row in
            (state.active_entities.get("observation_artifacts") or {}).get("capabilities", [])
            if row.get("artifact_id") == arguments.get("artifact_id")]
    if tool.name == "agent.delegate":
        invocation["runtime_context"] = {"parent_state": state, "step_id": step.step_id,
            "planner_client": client, "chat_client": client, "db_name": db_name, "persist": persist,
            "task_store_root": root, "progress_callback": progress_callback, "task_control": task_control,
            "checkpoint": checkpoint}
    if tool.name == "approvals.cancel":
        invocation["runtime_context"] = {"state": state}
    result = tool.handler(**invocation)
    if not isinstance(result, Result):
        raise TypeError("canonical_tool_did_not_return_Result")
    payload = dict(result.data or {})
    child_errors = child_observation_problems(tool, payload)
    if child_errors:
        return Result.fail("Araç sonucu alt çalışma kapsamıyla uyuşmuyor.", close_dialog=False,
                           data={"argument_problems": child_errors})
    return Result(success=result.success, message=result.message, error=result.error, close_dialog=False,
        data={"tool_result": payload, "tool_call": {"tool": tool.name, "arguments": arguments},
              "dependency_bindings": bindings, "conversation_context": payload.get("conversation_context") or {}})

