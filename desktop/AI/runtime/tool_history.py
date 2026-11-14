"""Bounded replay of actual current-turn model calls, never invented plans."""
import hashlib
import json

from AI.runtime.context_window import bounded_preview, json_bytes


def arguments_hash(arguments):
    return hashlib.sha256(json.dumps(arguments, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def current_tool_exchanges(state, sanitize, *, max_pairs=8, max_bytes=14000):
    loop = state.active_entities.get("model_loop", {})
    start = loop.get("turn_started_step_count", len(state.completed_steps))
    authored = {row.get("step_id"): row for row in loop.get("authored_calls", []) if isinstance(row, dict)}
    exchanges, used = [], 0
    for step in reversed(state.completed_steps[max(0, int(start)):]):
        if len(exchanges) >= max_pairs:
            break
        receipt = authored.get(step.step_id, {})
        wire_name = receipt.get("wire_tool_name")
        if (step.status not in {"completed", "failed"} or len(step.tool_names) != 1
                or receipt.get("arguments_hash_version") != 2
                or receipt.get("operation_id") != step.tool_names[0]
                or receipt.get("arguments_sha256") != arguments_hash(step.arguments)
                or not isinstance(wire_name, str) or not wire_name):
            continue
        # Do not rewrite a model's call arguments into a different alleged call.
        # Private/oversized arguments stay in host state, outside this replay.
        if sanitize(step.arguments) != step.arguments or json_bytes(step.arguments) > 4000:
            continue
        call_id = "call_" + hashlib.sha256((state.session_id + ":" + step.step_id).encode()).hexdigest()[:32]
        result = {"step_id": step.step_id, "operation": step.tool_names[0], "success": step.status == "completed",
                  "message": step.result_message[:240], "full_result_stored": True,
                  "result": bounded_preview(sanitize(step.result_data.get("tool_result", {})), max_bytes=2600)}
        row = {"step_id": step.step_id, "id_origin": "host_replay_identity", "messages": [
            {"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function",
                "function": {"name": wire_name, "arguments": json.dumps(step.arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}}]},
            {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}]}
        size = json_bytes(row)
        if used + size > max_bytes:
            break
        exchanges.append(row)
        used += size
    return list(reversed(exchanges))
