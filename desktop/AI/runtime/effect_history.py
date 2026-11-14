"""Compact views of actual approved executions, separate from prepared inputs.

These are evidence projections, not business decisions or answer templates.
Prepared action fields can identify the approved target, but never establish an
execution result. Keep the actual outcome/readback ahead of bulky proposal data.
"""
from __future__ import annotations

from copy import deepcopy

from AI.runtime.context_window import bounded_preview, json_bytes


def _mapping(value):
    return value if isinstance(value, dict) else {}


def approved_effect_receipts(state, sanitize, *, max_receipts=6, max_bytes=12000):
    """Read only host execution envelopes; pending/prepare data is not evidence.

    The three durable stores overlap. Join matching outcomes by actual action
    identity and success, retaining their real source positions and readback.
    Never traverse action arguments or audit payloads for purported outcomes.
    """
    receipts = []

    def add(*, source, index=None, action=None, operation="", success=None,
            message="", verify=None, result=None, timestamp="", action_id="", extra=None):
        if not isinstance(success, bool):
            return
        action = _mapping(action)
        action_id = action_id or action.get("action_id") or ""
        operation = operation or action.get("action_type") or ""
        if not operation:
            return
        verification = sanitize(_mapping(verify))
        match = next((row for row in reversed(receipts)
                      if action_id and row.get("action_id") == action_id and row["operation"] == operation
                      and row["success"] == success
                      and (not row.get("verify") or not verification or row["verify"] == verification)), None)
        if match is None:
            match = {"action_id": action_id, "operation": operation, "phase": "execute",
                     "success": success, "status": "executed" if success else "failed", "sources": []}
            receipts.append(match)
        provenance = {"collection": source}
        if index is not None:
            provenance["index"] = index
        match["sources"].append(provenance)
        if message:
            match["message"] = bounded_preview(sanitize(message), max_bytes=700)
        if verification:
            # This is the operation's readback, not preparation verification.
            match["verify"] = bounded_preview(verification, max_bytes=2800)
        if verification or "business_completion_verified" not in match:
            match["business_completion_verified"] = bool(success and verification.get("verified") is True)
        if isinstance(result, dict):
            match["result"] = bounded_preview(sanitize(result), max_bytes=1600)
        if timestamp:
            match["timestamp"] = timestamp
        if action.get("record_refs"):
            match["approved_record_refs"] = bounded_preview(sanitize(action["record_refs"]), max_bytes=1200)
        prepared_step = _mapping(action.get("semantic_verification")).get("step_id")
        if prepared_step:
            match["preparation_step_id"] = prepared_step
        if extra:
            match.update(extra)

    for index, event in enumerate(getattr(state, "action_history", [])):
        event = _mapping(event)
        if event.get("phase") != "execute" or event.get("status") not in {"executed", "failed"}:
            continue
        add(source="action_history", index=index, action=event.get("action"),
            operation=event.get("action_type", ""), success=event.get("success"),
            message=event.get("result_message", ""), verify=event.get("verify"))

    for index, stored in enumerate(getattr(state, "last_tool_results", [])):
        stored = _mapping(stored)
        # Only this host-owned approval result envelope is an execution receipt.
        if stored.get("step") != "approval" or stored.get("tool_names") != ["execute_approved_operation"]:
            continue
        data = _mapping(stored.get("data"))
        audit = _mapping(data.get("audit"))
        add(source="last_tool_results", index=index, action=audit.get("action"),
            operation=audit.get("operation", ""), success=audit.get("execute_success"),
            message=audit.get("result_message", ""), verify=data.get("verify", audit.get("verify")),
            result=data.get("result"), timestamp=audit.get("timestamp", ""))

    last = _mapping(_mapping(getattr(state, "active_entities", {}).get("model_loop")).get("last_execution"))
    if last.get("action_id") and last.get("operation"):
        add(source="model_loop.last_execution", action_id=last["action_id"], operation=last["operation"],
            success=last.get("success"), message=last.get("message", ""), verify=last.get("verify"),
            result=last.get("result"))

    # Reserve the newest outcomes first. Whole receipt objects stay intact; a
    # generic nested preview must not push execution/readback behind proposals.
    selected, used = [], 0
    for row in reversed(receipts[-max_receipts:]):
        size = json_bytes(row)
        if used + size <= max_bytes:
            selected.append(row)
            used += size
    return list(reversed(selected))


def observation_effect_timing(state, receipts):
    """Label exact recorded pre-execution observations without erasing them.

    No wall time is invented. The ordered host result ledger establishes the
    relation; a recorded preparation step is a safe fallback for older states.
    This temporal relation alone does not imply matching entity/account scope.
    """
    ledger = getattr(state, "last_tool_results", [])
    timing = {}
    for receipt in receipts:
        before_indices = set()
        for source in receipt["sources"]:
            if source["collection"] == "last_tool_results":
                before_indices.update(row.get("step") for row in ledger[:source["index"]]
                                      if isinstance(row, dict) and isinstance(row.get("step"), int))
        prepared = next((step for step in state.completed_steps
                         if step.step_id == receipt.get("preparation_step_id")), None)
        for step in state.completed_steps:
            if step.index in before_indices or prepared is not None and step.index <= prepared.index:
                row = timing.setdefault(step.step_id, {"historical_before_approved_execution": []})
                identity = {key: deepcopy(receipt[key]) for key in ("action_id", "operation")}
                if identity not in row["historical_before_approved_execution"]:
                    row["historical_before_approved_execution"].append(identity)
    return timing
