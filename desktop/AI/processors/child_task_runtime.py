"""Bounded child research using the same model, deadline and real task runtime.

Delegation grants read authority only. A private context restricts discovery,
planning and execution; completed child observations return as existing runtime
artifact capabilities, never as parent business observations or approvals.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, Mapping
from uuid import uuid4

from AI.processors.session_state import AgentSessionState
from Feedback.processors.pipeline import Result


_POLICY = ContextVar("orderscout_child_read_policy", default=None)
_EXECUTION_ID = ContextVar("orderscout_child_execution_id", default="")
_PROTECTED = {"orders", "returns", "finance", "listing", "marketplaces", "account", "accounts"}
_CONTROLLED_OPERATIONS = {"operations.discover"}
_RECORD_FIELDS = {"order": ("order_numbers", "order_number"), "return": ("claim_ids", "claim_id"),
                  "stock_item": ("item_ids", "item_id"), "listing": ("listing_ids", "listing_id")}


def current_child_policy() -> dict[str, Any] | None:
    value = _POLICY.get()
    return deepcopy(value) if isinstance(value, dict) else None


def current_child_execution_id() -> str:
    return _EXECUTION_ID.get() if _POLICY.get() is not None else ""


def bind_child_execution_identity(state: AgentSessionState) -> None:
    policy = _POLICY.get()
    if policy is not None:
        if state.active_entities.get("child_delegation_policy") != policy:
            raise ValueError("Child execution identity requires the exact saved read policy.")
        _EXECUTION_ID.set(state.session_id)


@contextmanager
def child_read_context(policy: Mapping[str, Any]):
    value = deepcopy(dict(policy))
    if value.get("schema_version") != 1 or value.get("depth") != 1 or value.get("effects_allowed") is not False:
        raise ValueError("Invalid child read policy.")
    if _POLICY.get() is not None:
        raise ValueError("Nested delegation is unavailable.")
    token = _POLICY.set(value)
    identity_token = _EXECUTION_ID.set("")
    try:
        yield
    finally:
        _EXECUTION_ID.reset(identity_token)
        _POLICY.reset(token)


def _scope_policy(parent: AgentSessionState) -> dict[str, Any]:
    accounts, environments, companies, filters, records = {}, {}, {}, {}, {}
    for domain, scope in parent.active_scopes.items():
        accounts[domain] = list(scope.account_ids)
        environments[domain] = [value for value in scope.environments if value != "unknown"]
        companies[domain] = list(scope.company_ids)
        filters[domain] = deepcopy(scope.filters)
    for domain in parent.active_selection_ids:
        selected = parent.active_selection(domain)
        if selected is None:
            continue
        for ref in selected.refs:
            shape = _RECORD_FIELDS.get(ref.record_type)
            if shape:
                records.setdefault(domain, {}).setdefault(shape[0], []).append(ref.record_id)
    return {"schema_version": 1, "depth": 1, "effects_allowed": False,
            "parent_task_id": parent.session_id, "account_ids": accounts, "environments": environments,
            "company_ids": companies, "filters": filters, "records": records}


def _scope_values(policy, field, domain):
    # Account/company IDs from another canonical owner are not an identity
    # bridge. A missing binding cannot authorize the union of unrelated scopes.
    return list((policy.get(field) or {}).get(domain) or [])


def _properties(tool):
    return dict((getattr(tool, "parameters", None) or {}).get("properties") or {})


def restrict_tool_registry(registry: Mapping[str, Any]) -> dict[str, Any]:
    """A new dictionary; shared tool instances and the parent registry stay intact."""
    policy = _POLICY.get()
    if policy is None:
        return dict(registry)
    allowed = {}
    for name, tool in registry.items():
        if (name == "agent.delegate" or (name.startswith("operations.") and name not in _CONTROLLED_OPERATIONS)
                or not getattr(tool, "read_only", False) or getattr(tool, "requires_approval", False)
                or getattr(tool, "destructive", False) or getattr(tool, "action_type", "read") != "read"):
            continue
        domain = getattr(tool, "domain", "general")
        properties = _properties(tool)
        if domain in _PROTECTED and any((policy.get("account_ids") or {}).values()):
            if not _scope_values(policy, "account_ids", domain):
                continue
        if domain in _PROTECTED and any((policy.get("environments") or {}).values()):
            if not _scope_values(policy, "environments", domain):
                continue
        if domain in _PROTECTED and _scope_values(policy, "account_ids", domain):
            if not {"api_account_ids", "api_account_id"}.intersection(properties):
                continue
        if (policy.get("records") or {}).get(domain):
            if not set(policy["records"][domain]).issubset(properties):
                continue
        allowed[name] = tool
    return allowed


def bind_child_read_arguments(tool, arguments: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    policy = _POLICY.get()
    values = deepcopy(dict(arguments))
    if policy is None:
        return values, []
    name, domain = getattr(tool, "name", ""), getattr(tool, "domain", "general")
    if name not in restrict_tool_registry({name: tool}):
        return values, ["child_operation_outside_read_scope"]
    problems, properties = [], _properties(tool)
    if name == "operations.discover" and values.get("include_manual") is True:
        problems.append("child_manual_catalog_not_authorized")
    if name == "operations.discover":
        values["include_manual"] = False

    def constrain(field, permitted, *, scalar=False, integers=False):
        if not permitted:
            return
        if field not in properties:
            problems.append("child_scope_unbindable:" + field)
            return
        canonical = [int(value) for value in permitted] if integers else list(permitted)
        actual = values.get(field)
        supplied = [actual] if scalar and actual not in (None, "") else actual
        if supplied is None or supplied == [] or supplied == "":
            if scalar and len(canonical) != 1:
                problems.append("child_scalar_scope_ambiguous:" + field)
            else:
                values[field] = canonical[0] if scalar else canonical
        elif not isinstance(supplied, list) or not {str(value) for value in supplied}.issubset({str(value) for value in canonical}):
            problems.append("child_scope_widening:" + field)

    accounts = _scope_values(policy, "account_ids", domain) if domain in _PROTECTED else []
    if accounts:
        field = "api_account_ids" if "api_account_ids" in properties else "api_account_id"
        constrain(field, accounts, scalar=field == "api_account_id", integers=True)
    environments = _scope_values(policy, "environments", domain)
    if environments and "environment" in properties:
        constrain("environment", environments, scalar=True)
    if environments and "environments" in properties:
        constrain("environments", environments)
    companies = _scope_values(policy, "company_ids", domain)
    if domain in {"finance", "stock"} and companies:
        field = "company_ids" if "company_ids" in properties else "company_id"
        constrain(field, companies, scalar=field == "company_id", integers=True)
    for field, permitted in (policy.get("records", {}).get(domain) or {}).items():
        constrain(field, permitted)
    for field, expected in (policy.get("filters", {}).get(domain) or {}).items():
        if expected in (None, "", [], {}) or field in {"api_account_ids", "api_account_id"}:
            continue
        if field not in properties:
            problems.append("child_scope_filter_unbindable:" + field)
        elif field in values and values[field] != expected:
            problems.append("child_scope_filter_changed:" + field)
        else:
            values[field] = deepcopy(expected)
    return values, problems


def child_observation_problems(tool, result: Mapping[str, Any]) -> list[str]:
    policy = _POLICY.get()
    if policy is None:
        return []
    domain = getattr(tool, "domain", "general")
    if getattr(tool, "name", "") == "artifacts.read":
        artifact = result.get("artifact") or {}
        domain = str((artifact.get("scope") or {}).get("domain") or domain)
        source_operation = str((artifact.get("origin") or {}).get("operation_id") or "")
        from AI.processors.tools import available_tools
        if source_operation not in available_tools():
            return ["child_artifact_source_outside_read_scope"]
    accounts = _scope_values(policy, "account_ids", domain) if domain in _PROTECTED else []
    environments = _scope_values(policy, "environments", domain) if domain in _PROTECTED else []
    problems = []

    def inspect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "api_account_id" and accounts and item is not None and str(item) not in {str(account) for account in accounts}:
                    problems.append("child_observed_account_scope_widening")
                if key == "requested_api_account_ids" and accounts and isinstance(item, list) and not {str(account) for account in item}.issubset({str(account) for account in accounts}):
                    problems.append("child_observed_account_scope_widening")
                if key == "environment" and environments and item not in environments:
                    problems.append("child_observed_environment_scope_changed")
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)
    inspect(result)
    return list(dict.fromkeys(problems))


def delegate_read_task(*, objective: str, max_steps: int = 2, max_replans: int = 1,
                       runtime_context: Mapping[str, Any] | None = None) -> Result:
    """Runtime binds all authority; the model supplies only a goal and budgets."""
    if not isinstance(runtime_context, dict) or type(runtime_context.get("parent_state")) is not AgentSessionState:
        return Result.fail("Alt çalışma yalnız mevcut görevin güvenli çalışma ortamından başlatılabilir.", close_dialog=False)
    parent = runtime_context["parent_state"]
    if _POLICY.get() is not None or parent.active_entities.get("child_delegation_policy"):
        return Result.fail("Alt çalışmanın yeniden alt çalışma başlatmasına izin verilmez.", close_dialog=False)
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 4000:
        return Result.fail("Alt çalışmanın hedefi geçersiz.", close_dialog=False)
    if type(max_steps) is not int or not 1 <= max_steps <= 8 or type(max_replans) is not int or not 0 <= max_replans <= 4:
        return Result.fail("Alt çalışma bütçesi geçersiz.", close_dialog=False)
    client = runtime_context.get("planner_client")
    if client is None:
        return Result.fail("Alt çalışma mevcut seçili model olmadan başlatılamaz.", close_dialog=False)
    budget = parent.active_entities.get("execution_budget") or {}
    reservations = parent.active_entities.setdefault("child_task_reservations", {})
    policy = _scope_policy(parent)
    step_id = runtime_context.get("step_id")
    existing = reservations.get(step_id)
    checkpoint = runtime_context.get("checkpoint")
    if not callable(checkpoint):
        return Result.fail("Alt çalışma rezervasyonu güvenli biçimde kaydedilemedi.", close_dialog=False,
                           data={"delegation_started": False})
    resuming = False
    if existing:
        if existing.get("scope_policy") != policy:
            return Result.fail("Alt çalışmanın kaydedilmiş kapsamı değiştiği için aynı çalışma sürdürülmedi.", close_dialog=False,
                               data={"child_task_id": existing.get("child_task_id"), "child_status": existing.get("status"),
                                     "recovery_required": True, "child_scope_changed": True})
        same_request = (existing.get("objective") == objective and existing.get("max_steps") == max_steps
                        and existing.get("max_replans") == max_replans)
        if same_request and existing.get("status") == "complete":
            return Result.ok("Tamamlanmış alt çalışmanın gerçek gözlem kaynakları korundu.", close_dialog=False,
                             data=deepcopy(existing["receipt"]))
        resuming = (same_request and existing.get("status") in {"paused", "interrupted", "running"}
                    and bool(existing.get("child_task_id")) and bool(runtime_context.get("persist")))
        if not resuming:
            return Result.fail("Önceki alt çalışma yeniden başlatılmadı; kaydedilmiş çalışma sonucu incelenmeli.", close_dialog=False,
                               data={"child_task_id": existing.get("child_task_id"), "child_status": existing.get("status"), "recovery_required": True})
    if not resuming and (int(budget.get("max_steps", 0)) - int(budget.get("started_steps", 0)) < max_steps
            or int(budget.get("max_replans", 0)) - int(budget.get("applied_replans", 0)) < max_replans):
        return Result.fail("Alt çalışma için ana görevin kalan bütçesi yeterli değil.", close_dialog=False,
                           data={"delegation_started": False, "parent_budget_exhausted": True})
    reservation = existing if resuming else {"reservation_id": "child_" + uuid4().hex, "objective": objective,
                                            "max_steps": max_steps, "max_replans": max_replans,
                                            "status": "reserved", "child_task_id": "", "scope_policy": deepcopy(policy)}
    reservation_id = reservation["reservation_id"]
    if not resuming:
        reservations[step_id] = reservation
        budget["started_steps"] = int(budget.get("started_steps", 0)) + max_steps
        budget["reserved_child_replans"] = int(budget.get("reserved_child_replans", 0)) + max_replans
        budget["applied_replans"] = int(budget.get("applied_replans", 0)) + max_replans
        parent.active_entities["execution_budget"] = budget
    try:
        checkpoint("child_resume_reserved" if resuming else "child_budget_reserved")
        from AI.processors import observation_artifacts, task_runtime
        if not resuming:
            fresh = AgentSessionState(goal=objective, active_domain="general")
            fresh.active_scopes = deepcopy(parent.active_scopes)
            fresh.selection_snapshots = deepcopy(parent.selection_snapshots)
            fresh.active_selection_ids = deepcopy(parent.active_selection_ids)
            workspace = parent.active_entities.get("file_workspace")
            if isinstance(workspace, dict):
                fresh.active_entities["file_workspace"] = deepcopy(workspace)
            if parent.active_entities.get("file_workspace_session_id"):
                fresh.active_entities["file_workspace_session_id"] = parent.active_entities["file_workspace_session_id"]
            observation_artifacts.transfer_observation_capabilities(parent, fresh)

        def created(child):
            reservation["child_task_id"] = child.session_id
            reservation["status"] = "running"
            checkpoint("child_task_attached")

        if resuming:
            from AI.processors.task_store import load_agent_task_state
            restored = load_agent_task_state(reservation["child_task_id"], root=runtime_context.get("task_store_root"))
            child_budget = restored.active_entities.get("execution_budget") or {}
            if (restored.active_entities.get("child_delegation_policy") != policy or restored.goal != objective
                    or child_budget.get("max_steps") != max_steps or child_budget.get("max_replans") != max_replans):
                raise ValueError("Child durable scope or budget changed.")
            with child_read_context(policy):
                result = (Result.ok("Kaydedilmiş alt araştırmanın gerçek sonucu korundu.", close_dialog=False,
                                    data={"state": restored.to_dict()})
                          if restored.status == "complete" and not restored.remaining_steps and not restored.pending_actions
                          else task_runtime.resume_read_task(
                    restored, planner_client=client, chat_client=runtime_context.get("chat_client"),
                    db_name=runtime_context.get("db_name"), persist=True,
                    task_store_root=runtime_context.get("task_store_root"), task_control=runtime_context.get("task_control"),
                    progress_callback=runtime_context.get("progress_callback")))
        else:
            with child_read_context(policy):
                from AI.processors.model_loop import is_model_loop, run_model_loop
                if is_model_loop(parent):
                    result = run_model_loop(objective, client=client, session_state=fresh,
                        db_name=runtime_context.get("db_name"), max_steps=max_steps, max_replans=max_replans,
                        task_created_callback=created, persist=bool(runtime_context.get("persist")),
                        task_store_root=runtime_context.get("task_store_root"), task_control=runtime_context.get("task_control"),
                        progress_callback=runtime_context.get("progress_callback"))
                else:
                    result = task_runtime.run_agent_task(
                    objective, domain="general", session_state=fresh, planner_client=client,
                    chat_client=runtime_context.get("chat_client"), db_name=runtime_context.get("db_name"),
                    max_steps=max_steps, max_replans=max_replans, task_created_callback=created,
                    persist=bool(runtime_context.get("persist")), task_store_root=runtime_context.get("task_store_root"),
                    task_control=runtime_context.get("task_control"), progress_callback=runtime_context.get("progress_callback"),
                    turn_interpretation={"mode": "inspect", "domain": "general", "intent_kind": "data_read", "valid": True,
                                         "objective": objective, "requested_fields": [], "requires_clarification": False})
        payload = dict(result.data or {})
        actual_state = payload.get("state")
        if not isinstance(actual_state, dict) or actual_state.get("session_id") != reservation.get("child_task_id"):
            raise ValueError("Child runtime did not return its actual attached execution state.")
        child = AgentSessionState.from_dict(actual_state)
        complete = result.success and child.status == "complete" and not child.pending_actions and not child.remaining_steps
        refs = []
        if complete:
            refs = [row for row in observation_artifacts.observation_artifact_refs(child)
                    if row.get("origin", {}).get("task_id") == child.session_id]
            if not refs:
                complete = False
            else:
                observation_artifacts.transfer_observation_capabilities(child, parent, artifact_ids=[row["artifact_id"] for row in refs])
        receipt = {"tool": "agent.delegate", "child_task_id": child.session_id, "child_status": child.status,
                   "objective": objective, "depth": 1, "read_only": True, "effect_authority": False,
                   "reservation_id": reservation_id, "reserved_steps": max_steps, "reserved_replans": max_replans,
                   "child_started_steps": int((child.active_entities.get("execution_budget") or {}).get("started_steps", 0)),
                   "artifact_refs": refs, "business_observations_in_receipt": False, "requires_artifact_read": True}
        if not complete:
            receipt["child_failure_reason"] = str((child.active_entities.get("task_plan") or {}).get("planner_error")
                                                  or (child.active_entities.get("goal_progress") or {}).get("reason")
                                                  or "child_incomplete")
        reservation.update(status="complete" if complete else child.status, receipt=deepcopy(receipt))
        checkpoint("child_task_observed")
        if not complete:
            return Result.fail("Alt araştırma tamamlanmadı; ana hedef tamamlanmış sayılmadı.", close_dialog=False, data=receipt)
        return Result.ok("Alt araştırma tamamlandı; gerçek gözlemleri yetkili kaynaklarından okuyarak devam edebilirsin.",
                         close_dialog=False, data=receipt)
    except Exception as exc:
        reservation["status"] = "failed"
        reservation["error_type"] = type(exc).__name__
        try:
            checkpoint("child_task_failed")
        except Exception:
            pass
        return Result.fail("Alt çalışma tamamlanamadı; ayrılan bütçe ve çalışma kaydı korunuyor.", error=exc,
                           close_dialog=False, data={"child_task_id": reservation.get("child_task_id"),
                                                     "child_status": "failed", "reservation_id": reservation_id})
