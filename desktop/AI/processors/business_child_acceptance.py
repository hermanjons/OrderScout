"""Independent child stock campaign checks over durable execution and native cells."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from AI.processors.business_acceptance_evidence import completed_observation_receipts, receipt_hash, validate_general_report_sources


def _number(value, expected):
    return type(value) in (int, float) and value == expected


def validate_child_stock_cells(report: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    rows = [row for sheet in report.get("sheets") or [] for row in sheet.get("rows") or [] if isinstance(row, list)]
    problems = []
    for currency, amount in fixture["stock"]["stock_value_by_currency"].items():
        if not any(currency in row and any(_number(value, amount) for value in row) for row in rows):
            problems.append("child_report_native_currency_amount_missing:" + currency)
    for sku, balance in fixture["stock"]["balance_by_sku"].items():
        if not any(sku in row and "adet" in row and any(_number(value, balance) for value in row) for row in rows):
            problems.append("child_report_native_quantity_unit_missing:" + sku)
    return {"passed": not problems, "problems": problems, "reader": "native report rows independently compared to seeded SQLite fixture"}


def _has_plan(value, operation, depth=0):
    if depth > 6:
        return False
    if isinstance(value, str):
        try:
            return _has_plan(json.loads(value), operation, depth + 1)
        except (ValueError, TypeError):
            return False
    if not isinstance(value, dict):
        return False
    if any(isinstance(row, dict) and row.get("operation_id") == operation for row in value.get("steps") or []):
        return True
    return any(_has_plan(value.get(key), operation, depth + 1) for key in ("data", "payload", "parsed", "response", "content", "text"))


def validate_child_stock_report(turn: dict[str, Any], fixture: dict[str, Any], *, isolation_root: str | Path,
                                task_store_root: str | Path | None = None, expected_model: str | None = None) -> dict[str, Any]:
    from AI.processors.task_store import TASK_STORE_DIR, load_agent_task_state

    raw = turn.get("raw_turn_data") or {}
    parent = raw.get("state") or raw.get("session_state") or {}
    receipts = completed_observation_receipts(turn)
    delegates = [row for row in receipts if row["operation_id"] == "agent.delegate"]
    problems, proof = [], []
    if len(delegates) != 1:
        return {"passed": False, "problems": ["exact_completed_child_delegation_missing"], "proof": []}
    delegated = delegates[0]
    receipt = delegated["result"]
    reservation = (parent.get("active_entities") or {}).get("child_task_reservations", {}).get(delegated["source_step_id"]) or {}
    if (receipt.get("child_status") != "complete" or receipt.get("depth") != 1 or receipt.get("read_only") is not True
            or receipt.get("effect_authority") is not False or receipt.get("business_observations_in_receipt") is not False
            or receipt.get("requires_artifact_read") is not True):
        problems.append("child_receipt_cannot_certify_business_completion")
    if (reservation.get("status") != "complete" or reservation.get("child_task_id") != receipt.get("child_task_id")
            or reservation.get("reservation_id") != receipt.get("reservation_id")
            or reservation.get("max_steps") != receipt.get("reserved_steps")
            or reservation.get("max_replans") != receipt.get("reserved_replans")):
        problems.append("child_reservation_not_exact_receipt")
    budget = (parent.get("active_entities") or {}).get("execution_budget") or {}
    reservations = list(((parent.get("active_entities") or {}).get("child_task_reservations") or {}).values())
    reserved_steps = sum(int(row.get("max_steps") or 0) for row in reservations)
    reserved_replans = sum(int(row.get("max_replans") or 0) for row in reservations)
    if (budget.get("started_steps") != len(parent.get("completed_steps") or []) + reserved_steps
            or budget.get("reserved_child_replans", 0) != reserved_replans
            or int(budget.get("started_steps") or 0) > int(budget.get("max_steps") or 0)):
        problems.append("child_parent_budget_reservation_not_exact")
    try:
        root = Path(task_store_root or TASK_STORE_DIR).resolve()
        root.relative_to(Path(isolation_root).resolve())
        child = load_agent_task_state(receipt["child_task_id"], root=root)
    except (KeyError, ValueError, OSError, TypeError):
        return {"passed": False, "problems": [*problems, "isolated_durable_child_unavailable"], "proof": []}
    policy = child.active_entities.get("child_delegation_policy") or {}
    if (child.status != "complete" or child.remaining_steps or child.pending_actions or child.active_pending_action_id
            or child.session_id == parent.get("session_id") or policy.get("schema_version") != 1
            or policy.get("depth") != 1 or policy.get("effects_allowed") is not False
            or policy.get("parent_task_id") != parent.get("session_id")):
        problems.append("durable_child_read_authority_or_completion_invalid")
    if reservation.get("scope_policy") != policy:
        problems.append("durable_child_policy_not_reserved_scope")
    child_budget = child.active_entities.get("execution_budget") or {}
    if (child_budget.get("max_steps") != reservation.get("max_steps") or child_budget.get("max_replans") != reservation.get("max_replans")
            or child_budget.get("started_steps") != receipt.get("child_started_steps")
            or int(child_budget.get("started_steps") or 0) > int(child_budget.get("max_steps") or 0)):
        problems.append("durable_child_budget_not_reserved_budget")
    from AI.processors.child_task_runtime import child_read_context
    from AI.processors.tools import available_tools
    try:
        with child_read_context(policy):
            registry = available_tools()
    except (ValueError, TypeError):
        registry = {}
    for step in child.completed_steps:
        if (step.status != "completed" or step.verification_status != "observed" or len(step.tool_names) != 1
                or step.tool_names[0] not in registry):
            problems.append("durable_child_operation_outside_successful_R0")
    sources = completed_observation_receipts({"raw_turn_data": {"state": child.to_dict()}})
    stock = [row for row in sources if row["operation_id"] == "stock.inventory_overview"]
    if len(stock) != 1:
        problems.append("exact_durable_child_canonical_stock_read_missing")
    else:
        source = stock[0]
        result = source["result"]
        value_rows = result.get("stock_value_by_currency") or []
        quantity_rows = result.get("top_balances") or []
        values = {row.get("currency"): row.get("amount") for row in value_rows}
        quantities = {row.get("sku"): row.get("balance") for row in quantity_rows}
        if (len(values) != len(value_rows) or len(quantities) != len(quantity_rows)
                or set(values) != set(fixture["stock"]["stock_value_by_currency"])
                or set(quantities) != set(fixture["stock"]["balance_by_sku"])
                or any(not _number(values[key], amount) for key, amount in fixture["stock"]["stock_value_by_currency"].items() if key in values)
                or any(not _number(quantities[key], amount) for key, amount in fixture["stock"]["balance_by_sku"].items() if key in quantities)
                or any(row.get("unit") != "adet" for row in quantity_rows)):
            problems.append("durable_child_stock_not_independent_fixture")
        imported = []
        for row in receipts:
            if row["operation_id"] != "artifacts.read":
                continue
            actual = row["result"]
            artifact = actual.get("artifact") or {}
            origin = artifact.get("origin") or {}
            if (origin.get("task_id") == child.session_id and origin.get("step_id") == source["source_step_id"]
                    and origin.get("operation_id") == source["operation_id"] and artifact.get("result_hash") == source["source_result_hash"]
                    and receipt_hash(actual.get("result")) == source["source_result_hash"]
                    and actual.get("historical_observation") is True and actual.get("fresh_read") is False
                    and actual.get("verified") is True
                    and any(ref.get("artifact_id") == artifact.get("artifact_id") and ref.get("origin") == origin
                            and ref.get("result_hash") == source["source_result_hash"] for ref in receipt.get("artifact_refs") or [])):
                imported.append(row)
        if not imported:
            problems.append("parent_exact_historical_child_artifact_read_missing")
        reports = validate_general_report_sources(turn, required_domains=("artifacts",), required_source_operations=("artifacts.read",))
        problems.extend(reports["problems"])
        imported_ids = {row["source_step_id"] for row in imported}
        if not any(any(row["source_step_id"] in imported_ids for row in build["bound_sources"]) for build in reports["proof"]):
            problems.append("report_not_bound_to_exact_child_artifact_wrapper")
        proof.append({"child_task_id": child.session_id, "stock_step_id": source["source_step_id"],
                      "stock_result_hash": source["source_result_hash"], "parent_import_steps": sorted(imported_ids),
                      "reservation_id": receipt.get("reservation_id"), "reserved_steps": reserved_steps, "reserved_replans": reserved_replans})
    if any(row["operation_id"].startswith("stock.") for row in receipts):
        problems.append("parent_replaced_delegated_observation_with_fresh_stock_read")
    ledger = [row for row in turn.get("model_responses") or [] if (row.get("delegated_child") or {}).get("task_id") == child.session_id]
    expected_model = str(expected_model or (turn.get("runtime") or {}).get("requested_model") or "").casefold()
    if (not ledger or not any(row.get("response_received") is True and _has_plan(row.get("response"), "stock.inventory_overview") for row in ledger)
            or any((row.get("delegated_child") or {}).get("parent_task_id") != parent.get("session_id")
                   or (row.get("delegated_child") or {}).get("effect_authority") is not False for row in ledger)):
        problems.append("same_client_independent_child_plan_ledger_missing")
    if (not expected_model or any(str(row.get("requested_model") or "").casefold() != expected_model
                                 or str(row.get("actual_model") or "").casefold() != expected_model
                                 or row.get("fallback_used") for row in ledger)):
        problems.append("same_client_exact_child_model_identity_missing")
    pending = turn.get("pending_action") or turn.get("action_proposal") or {}
    snapshot = (((pending.get("arguments") or {}).get("payload") or pending.get("safe_payload") or {}).get("report_snapshot") or {})
    problems.extend(validate_child_stock_cells(snapshot, fixture)["problems"])
    return {"passed": not problems, "problems": list(dict.fromkeys(problems)), "proof": proof,
            "boundary": "Reopened isolated durable child, actual parent artifact wrapper, shared model ledger, exact report provenance and native fixture cells; visible answer still needs review."}
