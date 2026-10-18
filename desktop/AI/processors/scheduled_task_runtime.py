"""Submit a leased workflow through the shared conversation and task runtime."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from AI.processors.conversation_runtime import run_contextual_conversation_turn
from AI.processors.session_state import AgentSessionState
from AI.processors.workflow_scheduler import RunLease, WorkflowScheduler
from Feedback.processors.pipeline import Result


def run_scheduled_task(lease: RunLease, *, scheduler: WorkflowScheduler, client: Callable[..., Any],
                       provider_code: str, model_name: str, db_name: str,
                       current_session: AgentSessionState | Mapping[str, Any] | None = None,
                       allowed_scope_bindings: Mapping[str, Any] | None = None,
                       runtime_context: dict[str, Any] | None = None,
                       task_store_root: str | None = None, progress_callback: Callable[..., None] | None = None,
                       task_control: Any = None) -> Result:
    """A schedule never supplies a plan, old results or an approval token."""
    def shared_runner(goal: str, **options: Any) -> Result:
        def task_created(state: AgentSessionState) -> None:
            scheduler.attach_task_session(lease, state.session_id)
        turn = run_contextual_conversation_turn(
            goal, client=options["planner_client"] or options["chat_client"],
            provider_code=provider_code, model_name=model_name, db_name=db_name, history=[],
            session_state=options["session_state"], persist=True, task_store_root=task_store_root,
            max_steps=options["max_steps"], max_replans=options["max_replans"],
            progress_callback=options.get("progress_callback"), task_created_callback=task_created,
            runtime_context=runtime_context, task_control=task_control, allow_approval_execute=False,
        )
        return Result(success=turn["success"], message=turn["answer"], close_dialog=False,
                      data={"state": turn["session_state"], "session_state": turn["session_state"],
                            "answer": turn["answer"], "approval_required": turn["approval_required"],
                            "action_proposal": turn["action_proposal"], "provider_provenance": turn["provider_provenance"],
                            "tool_calls": turn["tool_arguments"], "tool_results": turn["tool_results"],
                            "final_response_source": "shared_scheduled_conversation", "mode": turn["mode"]})
    options: dict[str, Any] = {"domain": "general", "db_name": db_name, "persist": True}
    if progress_callback is not None:
        options["progress_callback"] = progress_callback
    if task_store_root is not None:
        options["task_store_root"] = task_store_root
    return scheduler.execute_lease(
        lease, runner=shared_runner, planner_client=client, chat_client=client,
        current_session=current_session, allowed_scope_bindings=allowed_scope_bindings, runner_options=options,
    )
