from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from AI.processors.acceptance_manifest import validate_turn_model_provenance
from AI.processors.cloud_runtime import provider_invocation_provenance
from AI.processors.live_evidence import LiveEvidenceRedactor
from AI.processors.task_runtime import model_authored_projection_acceptance


_RUNTIME_SOURCE_FILES = (
    "main.py",
    "settings.py",
    "Main_interface/views/views.py",
    "AI/processors/acceptance_manifest.py",
    "AI/processors/agent.py",
    "AI/processors/analysis_grounding.py",
    "AI/processors/cloud_runtime.py",
    "AI/processors/conversation_runtime.py",
    "AI/processors/live_evidence.py",
    "AI/processors/model_routing.py",
    "AI/processors/model_loop.py",
    "AI/runtime/__init__.py",
    "AI/runtime/contracts.py",
    "AI/runtime/arguments.py",
    "AI/runtime/schema.py",
    "AI/runtime/catalog.py",
    "AI/runtime/tool_dispatch.py",
    "AI/processors/conversation_controls.py",
    "AI/processors/operation_catalog.py",
    "AI/processors/operation_policy.py",
    "AI/processors/source_policy.py",
    "AI/processors/operation_runtime.py",
    "AI/processors/orders_source_ui_human_recheck_cli.py",
    "AI/processors/provider_adapters.py",
    "AI/processors/provider_catalog_policy.py",
    "AI/processors/response_layout.py",
    "AI/processors/grouped_projection.py",
    "AI/processors/response_verifier.py",
    "AI/processors/semantic_contracts.py",
    "AI/processors/semantic_verifier.py",
    "AI/processors/session_state.py",
    "AI/processors/task_runtime.py",
    "AI/processors/task_store.py",
    "AI/processors/tools.py",
    "AI/processors/turn_evidence.py",
    "AI/processors/turn_service.py",
    "AI/views/chat_tab.py",
    "Core/processors/verified_calculations.py",
    "Account/models/models.py",
    "Account/processors/pipeline.py",
    "Account/processors/local_health.py",
    "Account/views/actions.py",
    "Finance/processors/pipeline.py",
    "Finance/views/actions.py",
    "Listing/processors/pipeline.py",
    "Logistics/processors/catalog.py",
    "Logistics/processors/pipeline.py",
    "Orders/models/trendyol/models.py",
    "Orders/processors/agentic_metrics.py",
    "Orders/processors/agentic_repository.py",
    "Orders/processors/data_freshness.py",
    "Orders/processors/trendyol/pipeline.py",
    "Orders/views/actions.py",
    "Stock/processors/pipeline.py",
    "Stock/processors/inventory_summary.py",
    "Stock/views/actions.py",
    "Labels/assets/TANEX_2610.docx",
    "Labels/constants/template_constants.py",
    "Labels/processors/pipeline.py",
)


def _configure_interactive_utf8_stdio() -> None:
    """Keep adaptive JSONL prompts lossless across Windows pipe boundaries."""

    for stream_name, stream in (
        ("stdin", sys.stdin),
        ("stdout", sys.stdout),
        ("stderr", sys.stderr),
    ):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        reconfigure(
            encoding="utf-8",
            errors="strict" if stream_name == "stdin" else "backslashreplace",
        )


def _parse_jsonl_command(raw_line: str) -> dict[str, Any]:
    """Parse one Windows-safe JSONL command without weakening JSON strictness."""

    # Windows PowerShell 5 can prefix the first native-pipeline record with a
    # UTF-8 BOM even when stdout was configured as UTF-8 without a preamble.
    # The BOM is a transport marker, not part of the JSON document.
    line = str(raw_line or "").strip().lstrip("\ufeff")
    command = json.loads(line)
    if not isinstance(command, dict):
        raise ValueError("JSON object gerekir.")
    return command


def _runtime_source_evidence() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    aggregate = hashlib.sha256()
    files: list[dict[str, Any]] = []
    for relative_path in _RUNTIME_SOURCE_FILES:
        path = root / relative_path
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        stat = path.stat()
        aggregate.update(relative_path.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\0")
        files.append(
            {
                "path": relative_path,
                "sha256": digest,
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    return {"fingerprint": aggregate.hexdigest(), "files": files}


def _compact(value: Any) -> str:
    return str(value or "").strip()


def _normalized_model(value: Any) -> str:
    return _compact(value).casefold().removeprefix("models/")


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _minimum_human_review_seconds(answer: Any) -> float:
    """Return a conservative lower bound for a claimed human read/review."""
    length = len(_compact(answer))
    return round(max(1.5, min(45.0, length / 220.0)), 2)


def _review_allows_next_turn(review: dict[str, Any]) -> bool:
    assessment = _compact(review.get("assessment")).casefold()
    if assessment == "pass":
        return True
    return assessment == "fail" and review.get("correction_requested") is True


def _intentional_cancel_completed(prompt: Any, answer: Any) -> bool:
    prompt_text = _compact(prompt).casefold()
    answer_text = _compact(answer).casefold()
    cancel_requested = any(
        token in prompt_text
        for token in ("vazgeç", "vazgec", "iptal", "yapma", "çekme", "cekme", "durdur")
    )
    cancel_confirmed = any(
        token in answer_text
        for token in (
            "iptal edildi",
            "iptal edildi.",
            "vazgeçildi",
            "vazgecildi",
            "agent gorevi iptal edildi",
        )
    )
    no_effect_confirmed = (
        "api isteği veya db yazımı yapılmadı" in answer_text
        or "api istegi veya db yazimi yapilmadi" in answer_text
        or (
            "api istegi" in answer_text
            and "db yazimi" in answer_text
            and "calismadi" in answer_text
        )
    )
    return cancel_requested and cancel_confirmed and no_effect_confirmed


def _turn_tool(row: dict[str, Any]) -> str:
    call = dict(row.get("tool_call") or {}) if isinstance(row.get("tool_call"), dict) else {}
    return _compact(call.get("tool"))


def _turn_tool_result(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("tool_result") or {}) if isinstance(row.get("tool_result"), dict) else {}


def _turn_execute_data(row: dict[str, Any]) -> dict[str, Any]:
    execute = dict(row.get("execute") or {}) if isinstance(row.get("execute"), dict) else {}
    return dict(execute.get("data") or {}) if isinstance(execute.get("data"), dict) else {}


def _fold_text(value: Any) -> str:
    text = _compact(value).casefold().replace("ı", "i")
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def _turn_tool_names(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    direct = _turn_tool(row)
    if direct:
        values.append(direct)
    for call in list(row.get("tool_calls") or []):
        if not isinstance(call, dict):
            continue
        tool_name = _compact(call.get("tool") or call.get("tool_name"))
        if tool_name and tool_name not in values:
            values.append(tool_name)
    return values


def _turn_task_state(row: dict[str, Any]) -> dict[str, Any]:
    direct = _turn_tool_result(row)
    if isinstance(direct.get("state"), dict):
        return dict(direct.get("state") or {})
    agent_state = (
        dict(row.get("agent_state") or {})
        if isinstance(row.get("agent_state"), dict)
        else {}
    )
    for key in ("session_state", "state"):
        if isinstance(agent_state.get(key), dict):
            return dict(agent_state.get(key) or {})
    return {}


def _turn_canonical_tool_result(row: dict[str, Any]) -> dict[str, Any]:
    """Return the domain operation result hidden inside a task-runtime envelope."""

    direct = _turn_tool_result(row)
    state = _turn_task_state(row)
    completed_steps = [
        dict(item)
        for item in list(state.get("completed_steps") or [])
        if isinstance(item, dict)
    ]
    expected_tool = _turn_tool(row)
    for step in reversed(completed_steps):
        step_tools = {
            _compact(value)
            for value in list(step.get("tool_names") or [])
            if _compact(value)
        }
        if expected_tool and step_tools and expected_tool not in step_tools:
            continue
        result_data = (
            dict(step.get("result_data") or {})
            if isinstance(step.get("result_data"), dict)
            else {}
        )
        nested = result_data.get("tool_result")
        if isinstance(nested, dict):
            return dict(nested)
    return direct


def _order_numbers(value: Any) -> list[str]:
    if isinstance(value, dict):
        for key in (
            "order_numbers",
            "returned_order_numbers",
            "selected_order_numbers",
            "orders",
        ):
            if key not in value:
                continue
            rows = value.get(key)
            if isinstance(rows, list) and rows and all(
                isinstance(item, dict) for item in rows
            ):
                return [
                    _compact(
                        item.get("order_number")
                        or item.get("orderNumber")
                        or item.get("record_id")
                    )
                    for item in rows
                    if _compact(
                        item.get("order_number")
                        or item.get("orderNumber")
                        or item.get("record_id")
                    )
                ]
            return [
                _compact(item)
                for item in list(rows or [])
                if _compact(item)
            ]
    return []


def _action_payload(action: dict[str, Any]) -> dict[str, Any]:
    arguments = (
        dict(action.get("arguments") or {})
        if isinstance(action.get("arguments"), dict)
        else {}
    )
    payload = (
        dict(arguments.get("payload") or {})
        if isinstance(arguments.get("payload"), dict)
        else {}
    )
    return payload or arguments


def _label_action_from_turn(row: dict[str, Any]) -> dict[str, Any]:
    canonical_result = _turn_canonical_tool_result(row)
    for candidate in (
        canonical_result.get("action"),
        row.get("pending_action"),
        row.get("action_proposal"),
        (row.get("agent_state") or {}).get("pending_action")
        if isinstance(row.get("agent_state"), dict)
        else None,
    ):
        if not isinstance(candidate, dict):
            continue
        action = dict(candidate)
        if (
            _compact(action.get("action_type"))
            == "labels.action_create_labels_from_selected_orders"
        ):
            return action
    return {}


def _label_action_order_numbers(action: dict[str, Any]) -> list[str]:
    payload = _action_payload(action)
    values = _order_numbers(payload)
    if values:
        return values
    values = _order_numbers(action)
    if values:
        return values
    return [
        _compact(row.get("order_number") or row.get("orderNumber"))
        for row in list(action.get("rows") or [])
        if isinstance(row, dict)
        and _compact(row.get("order_number") or row.get("orderNumber"))
    ]


def _effective_execute_data(row: dict[str, Any]) -> dict[str, Any]:
    data = _turn_execute_data(row)
    nested = data.get("execute")
    if isinstance(nested, dict):
        merged = dict(data)
        merged.update(dict(nested))
        return merged
    return data


def _phase8a_truth_chain(
    turns: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Extract and verify count -> exact list source truth without fixed cardinality."""

    problems: list[str] = []
    count_index = next(
        (
            index
            for index, row in enumerate(turns)
            if _turn_tool(row) == "orders.ready_to_ship_count"
        ),
        -1,
    )
    if count_index < 0:
        return {}, ["phase8a_count_tool"]
    count_row = turns[count_index]
    count_result = _turn_canonical_tool_result(count_row)
    try:
        count = int(
            count_result.get("ready_to_ship")
            or count_result.get("count")
            or count_result.get("selected_count")
            or 0
        )
    except (TypeError, ValueError):
        count = 0
    count_orders = _order_numbers(count_result)
    if count <= 0:
        problems.append("phase8a_count_positive")
    if len(count_orders) != count or len(set(count_orders)) != count:
        problems.append("phase8a_count_exact_set")
    if count_result.get("truncated") is True:
        problems.append("phase8a_count_truncated")
    count_fingerprint = _compact(count_result.get("query_fingerprint"))
    source_snapshot_hash = _compact(count_result.get("source_snapshot_hash"))
    source_revision = _compact(count_result.get("source_revision"))
    if not count_fingerprint:
        problems.append("phase8a_count_query_fingerprint")
    if not source_snapshot_hash:
        problems.append("phase8a_count_source_snapshot_hash")
    if not source_revision:
        problems.append("phase8a_count_source_revision")

    list_index = next(
        (
            index
            for index, row in enumerate(turns)
            if index > count_index
            and _turn_tool(row) in {"orders.query", "orders.ready_to_ship"}
        ),
        -1,
    )
    if list_index < 0:
        problems.append("phase8a_exact_list_tool")
        return {
            "count_index": count_index,
            "count": count,
            "order_numbers": count_orders,
            "count_fingerprint": count_fingerprint,
            "source_snapshot_hash": source_snapshot_hash,
            "source_revision": source_revision,
        }, problems
    list_row = turns[list_index]
    list_result = _turn_canonical_tool_result(list_row)
    list_orders = _order_numbers(list_result)
    try:
        listed_count = int(
            list_result.get("listed_count")
            or list_result.get("count")
            or list_result.get("total_count")
            or 0
        )
    except (TypeError, ValueError):
        listed_count = 0
    if (
        listed_count != count
        or len(list_orders) != count
        or len(set(list_orders)) != count
        or set(list_orders) != set(count_orders)
    ):
        problems.append("phase8a_list_exact_set")
    if list_result.get("truncated") is True:
        problems.append("phase8a_list_truncated")
    if _compact(list_result.get("source_snapshot_hash")) != source_snapshot_hash:
        problems.append("phase8a_list_source_snapshot")
    listed_rows = [
        dict(item)
        for item in list(list_result.get("orders") or [])
        if isinstance(item, dict)
    ]
    if listed_rows and any(
        _fold_text(item.get("status")) not in {"readytoship", "ready_to_ship"}
        for item in listed_rows
    ):
        problems.append("phase8a_list_status_scope")

    for label, row in (("count", count_row), ("list", list_row)):
        runtime = (
            dict(row.get("runtime") or {})
            if isinstance(row.get("runtime"), dict)
            else {}
        )
        if (
            runtime.get("model_invoked") is not True
            or runtime.get("accepted_semantic_output") is not True
            or _normalized_model(runtime.get("actual_model"))
            != _normalized_model(runtime.get("requested_model"))
        ):
            problems.append(f"phase8a_{label}_model_authored")
    if str(count) not in _compact(count_row.get("answer")):
        problems.append("phase8a_count_visible_answer")
    if any(value not in _compact(list_row.get("answer")) for value in list_orders):
        problems.append("phase8a_list_visible_answer")
    return {
        "count_index": count_index,
        "list_index": list_index,
        "count": count,
        "order_numbers": count_orders,
        "count_fingerprint": count_fingerprint,
        "source_snapshot_hash": source_snapshot_hash,
        "source_revision": source_revision,
    }, problems


def _phase8a_label_prepare(
    turns: list[dict[str, Any]],
    *,
    after_index: int,
    expected_order_numbers: list[str],
    expected_source_snapshot_hash: str,
    before_index: int | None = None,
    prefer_latest: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    prepare_indexes = [
        index
        for index, row in enumerate(turns)
        if index > after_index
        and (before_index is None or index < before_index)
        and _turn_tool(row) == "labels.create_from_orders.prepare"
    ]
    prepare_index = (
        prepare_indexes[-1]
        if prepare_indexes and prefer_latest
        else prepare_indexes[0]
        if prepare_indexes
        else -1
    )
    if prepare_index < 0:
        return {}, ["phase8a_label_prepare_tool"]
    row = turns[prepare_index]
    result = _turn_canonical_tool_result(row)
    action = _label_action_from_turn(row)
    action_orders = _label_action_order_numbers(action)
    expected_set = set(expected_order_numbers)
    result_orders = _order_numbers(result)
    if (
        set(action_orders) != expected_set
        or len(action_orders) != len(expected_order_numbers)
        or (
            result_orders
            and (
                set(result_orders) != expected_set
                or len(result_orders) != len(expected_order_numbers)
            )
        )
    ):
        problems.append("phase8a_prepare_exact_set")
    try:
        selected_count = int(
            result.get("selected_record_count")
            or result.get("count")
            or len(result_orders)
        )
    except (TypeError, ValueError):
        selected_count = 0
    if selected_count != len(expected_order_numbers):
        problems.append("phase8a_prepare_count")
    payload = _action_payload(action)
    if _fold_text(payload.get("brand_code")) != "tanex":
        problems.append("phase8a_prepare_brand")
    if _fold_text(payload.get("model_code")).replace(" ", "_") != "tanex_2610":
        problems.append("phase8a_prepare_model")
    if result.get("scope_invariant_valid") is not True:
        problems.append("phase8a_prepare_scope_invariant")
    if row.get("approval_required") is not True:
        problems.append("phase8a_prepare_approval")
    if (
        result.get("api_call_performed") is True
        or result.get("db_write_performed") is True
        or result.get("external_write") is True
        or (row.get("execute") or {}).get("success") is True
    ):
        problems.append("phase8a_prepare_side_effect")
    action_id = _compact(action.get("action_id") or result.get("action_id"))
    action_arguments = (
        dict(action.get("arguments") or {})
        if isinstance(action.get("arguments"), dict)
        else {}
    )
    selection_id = _compact(
        result.get("selection_id") or action_arguments.get("source_selection_id")
    )
    action_snapshot_hash = _compact(
        action_arguments.get("validation_source_snapshot_hash")
        or action_arguments.get("source_snapshot_hash")
    )
    if not action_id:
        problems.append("phase8a_prepare_action_id")
    if not selection_id:
        problems.append("phase8a_prepare_selection_id")
    if action_snapshot_hash != expected_source_snapshot_hash:
        problems.append("phase8a_prepare_source_snapshot")
    runtime = (
        dict(row.get("runtime") or {})
        if isinstance(row.get("runtime"), dict)
        else {}
    )
    if (
        runtime.get("model_invoked") is not True
        or runtime.get("accepted_semantic_output") is not True
        or _normalized_model(runtime.get("actual_model"))
        != _normalized_model(runtime.get("requested_model"))
    ):
        problems.append("phase8a_prepare_model_authored")
    if "onay" not in _fold_text(row.get("answer")):
        problems.append("phase8a_prepare_visible_approval")
    return {
        "prepare_index": prepare_index,
        "row": row,
        "result": result,
        "action": action,
        "action_id": action_id,
        "selection_id": selection_id,
        "order_numbers": action_orders,
    }, problems


def _validate_phase8a_pending_read_semantics(
    turns: list[dict[str, Any]],
) -> list[str]:
    truth, problems = _phase8a_truth_chain(turns)
    if not truth or "list_index" not in truth:
        return list(dict.fromkeys(problems))
    pending_index = next(
        (
            index
            for index, row in enumerate(turns)
            if index > int(truth["list_index"])
            and _compact((row.get("runtime") or {}).get("decision_path"))
            == "pending_action_scope_read_guard"
        ),
        -1,
    )
    if pending_index < 0:
        problems.append("phase8a_pending_read_guard")
        return list(dict.fromkeys(problems))
    prepare, prepare_problems = _phase8a_label_prepare(
        turns,
        after_index=int(truth["list_index"]),
        before_index=pending_index,
        prefer_latest=True,
        expected_order_numbers=list(truth["order_numbers"]),
        expected_source_snapshot_hash=_compact(truth["source_snapshot_hash"]),
    )
    problems.extend(prepare_problems)
    if not prepare:
        return list(dict.fromkeys(problems))
    row = turns[pending_index]
    runtime = (
        dict(row.get("runtime") or {})
        if isinstance(row.get("runtime"), dict)
        else {}
    )
    if _turn_tool_names(row):
        problems.append("phase8a_pending_read_tool_free")
    if (
        runtime.get("model_invocation_attempted") is not False
        or runtime.get("model_invoked") is not False
        or runtime.get("any_model_response_received") is True
        or int(runtime.get("model_response_count") or 0) != 0
        or list(runtime.get("invocation_outcome_history") or [])
    ):
        problems.append("phase8a_pending_read_provider_free")
    if _compact(runtime.get("final_response_source")) != "typed_pending_state_projection":
        problems.append("phase8a_pending_read_projection")
    pending_action = _label_action_from_turn(row)
    if (
        _compact(pending_action.get("action_id")) != _compact(prepare["action_id"])
        or set(_label_action_order_numbers(pending_action))
        != set(truth["order_numbers"])
        or _compact(pending_action.get("status")) != "pending_approval"
    ):
        problems.append("phase8a_pending_read_action_preserved")
    if any(
        _compact(item.get("action_id")) == _compact(prepare["action_id"])
        and _compact(item.get("status")) == "superseded"
        for item in list(row.get("superseded_actions") or [])
        if isinstance(item, dict)
    ):
        problems.append("phase8a_pending_read_not_superseded")
    if (row.get("execute") or {}).get("success") is True:
        problems.append("phase8a_pending_read_no_execute")
    answer = _fold_text(row.get("answer"))
    negative_file = (
        "dosya uretilmedi" in answer
        or "dosya olusturulmadi" in answer
        or ("dosya" in answer and "hayir" in answer)
        or ("dosya" in answer and "yapilmadi" in answer)
    )
    if (
        str(int(truth["count"])) not in answer
        or "tanex 2610" not in answer
        or not negative_file
        or "onay" not in answer
    ):
        problems.append("phase8a_pending_read_visible_answer")
    return list(dict.fromkeys(problems))


def _label_execute_contract(
    turns: list[dict[str, Any]],
    *,
    after_index: int,
    expected_action_id: str,
    expected_order_numbers: list[str],
) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    expected_set = set(expected_order_numbers)
    for index, row in enumerate(turns):
        if index <= after_index:
            continue
        execute = (
            dict(row.get("execute") or {})
            if isinstance(row.get("execute"), dict)
            else {}
        )
        if execute.get("success") is not True:
            continue
        data = _effective_execute_data(row)
        verify = (
            dict(data.get("verify") or {})
            if isinstance(data.get("verify"), dict)
            else {}
        )
        capability = (
            dict(data.get("capability") or {})
            if isinstance(data.get("capability"), dict)
            else {}
        )
        audit = (
            dict(data.get("audit") or {})
            if isinstance(data.get("audit"), dict)
            else {}
        )
        action = (
            dict(audit.get("action") or {})
            if isinstance(audit.get("action"), dict)
            else {}
        )
        action_id = _compact(action.get("action_id"))
        action_orders = _label_action_order_numbers(action)
        verify_orders = _order_numbers(verify)
        if (
            _compact(capability.get("capability_id"))
            != "labels.action_create_labels_from_selected_orders"
            or _compact(audit.get("operation"))
            != "labels.action_create_labels_from_selected_orders"
        ):
            problems.append("phase8a_execute_action_type")
        if expected_action_id and action_id != expected_action_id:
            problems.append("phase8a_execute_action_id")
        if (
            set(action_orders) != expected_set
            or len(action_orders) != len(expected_order_numbers)
            or set(verify_orders) != expected_set
            or len(verify_orders) != len(expected_order_numbers)
        ):
            problems.append("phase8a_execute_exact_set")
        result_payload = (
            dict(data.get("result") or {})
            if isinstance(data.get("result"), dict)
            else {}
        )
        output_path = _compact(
            verify.get("output_path") or result_payload.get("output_path")
        )
        if (
            verify.get("verified") is not True
            or _compact(verify.get("verified_by")) != "payload_and_docx_content"
            or verify.get("docx_order_numbers_verified") is not True
            or not output_path.casefold().endswith(".docx")
            or int(verify.get("size_bytes") or 0) <= 0
            or _compact(audit.get("status")) != "success"
            or data.get("idempotent") is True
        ):
            problems.append("phase8a_execute_verified_docx")
        return {"execute_index": index, "row": row, "data": data}, problems
    return {}, ["phase8a_fresh_label_execute"]


def _validate_phase8a_execute_readback_semantics(
    turns: list[dict[str, Any]],
) -> list[str]:
    problems = _validate_phase8a_pending_read_semantics(turns)
    truth, truth_problems = _phase8a_truth_chain(turns)
    problems.extend(truth_problems)
    if not truth or "list_index" not in truth:
        return list(dict.fromkeys(problems))
    prepare, prepare_problems = _phase8a_label_prepare(
        turns,
        after_index=int(truth["list_index"]),
        prefer_latest=True,
        expected_order_numbers=list(truth["order_numbers"]),
        expected_source_snapshot_hash=_compact(truth["source_snapshot_hash"]),
    )
    problems.extend(prepare_problems)
    if prepare:
        _execute, execute_problems = _label_execute_contract(
            turns,
            after_index=int(prepare["prepare_index"]),
            expected_action_id=_compact(prepare["action_id"]),
            expected_order_numbers=list(truth["order_numbers"]),
        )
        problems.extend(execute_problems)
    return list(dict.fromkeys(problems))


def _validate_phase8a_correction_supersession_semantics(
    turns: list[dict[str, Any]],
) -> list[str]:
    truth, problems = _phase8a_truth_chain(turns)
    problems.extend(_validate_phase8a_pending_read_semantics(turns))
    if not truth or "list_index" not in truth:
        return list(dict.fromkeys(problems))
    prepare_rows = [
        (index, row, _label_action_from_turn(row))
        for index, row in enumerate(turns)
        if index > int(truth["list_index"])
        and _turn_tool(row) == "labels.create_from_orders.prepare"
    ]
    prepare_rows = [item for item in prepare_rows if item[2]]
    if len(prepare_rows) < 2:
        problems.append("phase8a_correction_two_prepares")
        return list(dict.fromkeys(problems))
    first_index, _first_row, first_action = prepare_rows[0]
    second_index, second_row, second_action = prepare_rows[1]
    first_id = _compact(first_action.get("action_id"))
    second_id = _compact(second_action.get("action_id"))
    if not first_id or not second_id or first_id == second_id:
        problems.append("phase8a_correction_new_action_id")
    second_orders = _label_action_order_numbers(second_action)
    if (
        set(second_orders) != set(truth["order_numbers"])
        or len(second_orders) != len(truth["order_numbers"])
    ):
        problems.append("phase8a_correction_exact_replacement")
    first_payload = _action_payload(first_action)
    second_payload = _action_payload(second_action)
    if (
        set(_label_action_order_numbers(first_action)) == set(second_orders)
        and _fold_text(first_payload.get("model_code"))
        == _fold_text(second_payload.get("model_code"))
    ):
        problems.append("phase8a_correction_no_material_revision")
    superseded_rows = [
        dict(item)
        for row in turns[second_index:]
        for item in list(row.get("superseded_actions") or [])
        if isinstance(item, dict)
    ]
    if not any(
        _compact(item.get("action_id")) == first_id
        and _compact(item.get("status")) == "superseded"
        for item in superseded_rows
    ):
        problems.append("phase8a_correction_old_action_superseded")
    runtime = (
        dict(second_row.get("runtime") or {})
        if isinstance(second_row.get("runtime"), dict)
        else {}
    )
    if (
        runtime.get("model_invoked") is not True
        or runtime.get("accepted_semantic_output") is not True
    ):
        problems.append("phase8a_correction_model_replan")
    for row in turns[first_index + 1 : second_index]:
        data = _effective_execute_data(row)
        audit = data.get("audit") if isinstance(data.get("audit"), dict) else {}
        action = audit.get("action") if isinstance(audit.get("action"), dict) else {}
        if (
            (row.get("execute") or {}).get("success") is True
            and _compact(action.get("action_id")) == first_id
        ):
            problems.append("phase8a_correction_stale_action_executed")
    stale_rejection_rows = [
        row
        for row in turns[second_index + 1 :]
        if row.get("turn_outcome") == "stale_action_rejected"
        and isinstance((row.get("execute") or {}).get("data"), dict)
        and (row.get("execute") or {}).get("data", {}).get("stale_approval")
        is True
    ]
    if not any(
        _compact((row.get("execute") or {}).get("data", {}).get("action_id"))
        == first_id
        and _compact(
            (row.get("execute") or {}).get("data", {}).get(
                "active_pending_action_id"
            )
        )
        == second_id
        and (row.get("execute") or {}).get("success") is False
        and _compact((row.get("pending_action") or {}).get("action_id"))
        == second_id
        for row in stale_rejection_rows
    ):
        problems.append("phase8a_correction_old_action_rejected")
    _execute, execute_problems = _label_execute_contract(
        turns,
        after_index=second_index,
        expected_action_id=second_id,
        expected_order_numbers=list(truth["order_numbers"]),
    )
    problems.extend(execute_problems)
    return list(dict.fromkeys(problems))


def _phase8b_turn(
    turns: list[dict[str, Any]],
    phase: str,
) -> tuple[int, dict[str, Any]]:
    marker = f"phase8b:{_compact(phase).casefold()}"
    for index, row in enumerate(turns):
        reason = _compact(row.get("selection_reason")).casefold()
        if reason == marker or reason.startswith(f"{marker}|"):
            return index, row
    return -1, {}


def _phase8b_action_from_turn(row: dict[str, Any]) -> dict[str, Any]:
    canonical_result = _turn_canonical_tool_result(row)
    agent_state = (
        dict(row.get("agent_state") or {})
        if isinstance(row.get("agent_state"), dict)
        else {}
    )
    for candidate in (
        canonical_result.get("action"),
        row.get("pending_action"),
        row.get("action_proposal"),
        agent_state.get("pending_action"),
    ):
        if isinstance(candidate, dict) and _compact(
            candidate.get("action_type") or candidate.get("operation")
        ):
            return dict(candidate)
    return {}


def _phase8b_completed_tool_results(
    row: dict[str, Any],
    tool_name: str,
) -> list[dict[str, Any]]:
    state = _turn_task_state(row)
    values: list[dict[str, Any]] = []
    for step in list(state.get("completed_steps") or []):
        if not isinstance(step, dict) or tool_name not in {
            _compact(value) for value in list(step.get("tool_names") or [])
        }:
            continue
        result_data = (
            dict(step.get("result_data") or {})
            if isinstance(step.get("result_data"), dict)
            else {}
        )
        result = result_data.get("tool_result")
        if isinstance(result, dict):
            values.append(dict(result))
    return values


def _phase8b_summary_signals(row: dict[str, Any]) -> set[str]:
    """Derive summary coverage from canonical result fields, not tool-name count."""

    state = _turn_task_state(row)
    step_rows = [
        dict(step)
        for step in list(state.get("completed_steps") or [])
        if isinstance(step, dict)
    ]
    evidence_rows: list[tuple[set[str], dict[str, Any]]] = []
    for step in step_rows:
        result_data = (
            dict(step.get("result_data") or {})
            if isinstance(step.get("result_data"), dict)
            else {}
        )
        result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        evidence_rows.append(
            (
                {
                    _compact(value)
                    for value in list(step.get("tool_names") or [])
                    if _compact(value)
                },
                result,
            )
        )
    if not evidence_rows:
        evidence_rows.append(
            (set(_turn_tool_names(row)), _turn_canonical_tool_result(row))
        )

    signals: set[str] = set()
    for tools, result in evidence_rows:
        if (
            any(
                key in result
                for key in ("total_orders", "total_count")
            )
            or (
                "orders.count" in tools
                and isinstance(result.get("count"), (int, float))
            )
        ):
            signals.add("total_count")
        if isinstance(result.get("status_counts"), dict):
            signals.add("status_distribution")
        if any(
            isinstance(result.get(key), (int, float))
            for key in ("estimated_revenue", "total_revenue", "revenue")
        ):
            signals.add("revenue")
        if any(
            isinstance(result.get(key), (int, float))
            for key in ("risk_count", "overdue_count")
        ):
            signals.add("fulfillment_risk")
        if tools.intersection(
            {"orders.ready_to_ship", "orders.ready_to_ship_count"}
        ) and any(
            isinstance(result.get(key), (int, float))
            for key in ("ready_to_ship", "selected_count", "count")
        ):
            signals.add("ready_to_ship")
        if tools.intersection(
            {"returns.waiting.list", "returns.waiting_action_count"}
        ) and any(
            isinstance(result.get(key), (int, float))
            for key in ("count", "waiting_count", "actionable_count")
        ):
            signals.add("waiting_returns")
        if tools.intersection(
            {"orders.item_sales_summary", "orders.item_sales_report"}
        ) and (
            isinstance(result.get("rows"), list)
            or isinstance(result.get("product_count"), (int, float))
        ):
            signals.add("item_sales")
    return signals


def _phase8b_runtime_is_exact_model_authored(row: dict[str, Any]) -> bool:
    runtime = (
        dict(row.get("runtime") or {})
        if isinstance(row.get("runtime"), dict)
        else {}
    )
    return bool(
        runtime.get("model_invoked") is True
        and runtime.get("accepted_semantic_output") is True
        and _normalized_model(runtime.get("actual_model"))
        == _normalized_model(runtime.get("requested_model"))
        and runtime.get("fallback_used") is not True
        and runtime.get("any_model_fallback_used") is not True
    )


def _phase8b_has_mojibake(value: Any) -> bool:
    text = _compact(value)
    return any(
        token in text
        for token in ("\ufffd", "Ã", "Ä", "Å", "â€", "ï¿¼", "ðŸ")
    )


def _validate_phase8b_orders_organic_semantics(
    turns: list[dict[str, Any]],
) -> list[str]:
    """Validate the adaptive Orders capability-reopening conversation.

    Phase labels are navigation metadata only. Every accepted phase is also checked
    against runtime, tool, typed-state, effect and read-back evidence so a label cannot
    turn an unrelated green response into acceptance.
    """

    problems: list[str] = []
    required_phases = (
        "greeting",
        "emotional_chat",
        "orders_capabilities",
        "orders_summary",
        "recent_orders",
        "order_detail",
        "long_context_return",
        "ready_count",
        "ready_list",
        "fulfillment_risk",
        "cargo_prepare",
        "cargo_cancel",
        "item_sales_list",
        "item_sales_excel_prepare",
        "item_sales_excel_pending",
        "item_sales_excel_execute",
        "public_product_identity",
        "public_web_research",
        "private_orders_web_boundary",
        "cancellations",
        "waiting_returns",
        "closing_chat",
    )
    phase_rows: dict[str, tuple[int, dict[str, Any]]] = {
        phase: _phase8b_turn(turns, phase) for phase in required_phases
    }
    for phase, (index, _row) in phase_rows.items():
        if index < 0:
            problems.append(f"phase8b_missing:{phase}")

    if any(_phase8b_has_mojibake(row.get("answer")) for row in turns):
        problems.append("phase8b_visible_answer_mojibake")

    free_chat_phases = (
        "greeting",
        "emotional_chat",
        "closing_chat",
    )
    for phase in free_chat_phases:
        _index, row = phase_rows.get(phase, (-1, {}))
        if not row:
            continue
        if _turn_tool_names(row) or (row.get("execute") or {}).get("success") is True:
            problems.append(f"phase8b_free_chat_effect:{phase}")
        if not _phase8b_runtime_is_exact_model_authored(row):
            problems.append(f"phase8b_free_chat_model:{phase}")

    _capability_index, capability_row = phase_rows.get(
        "orders_capabilities", (-1, {})
    )
    if capability_row:
        capability_answer = _fold_text(capability_row.get("answer"))
        capability_groups = (
            ("etiket",),
            ("iade", "claim"),
            ("kargo",),
            ("excel", "rapor"),
            ("web", "arastir"),
            ("onay", "execute"),
            ("ciro", "durum", "risk"),
        )
        covered_groups = sum(
            1
            for group in capability_groups
            if any(token in capability_answer for token in group)
        )
        if (
            _turn_tool_names(capability_row)
            != ["operations.capability_catalog"]
            or covered_groups < 6
            or _compact(
                (capability_row.get("runtime") or {}).get("decision_path")
            )
            != "typed_capability_catalog_grounded"
            or not _phase8b_runtime_is_exact_model_authored(capability_row)
            or (capability_row.get("execute") or {}).get("success") is True
        ):
            problems.append("phase8b_orders_capability_catalog_grounded")

    _summary_index, summary = phase_rows.get("orders_summary", (-1, {}))
    if summary:
        if len(_phase8b_summary_signals(summary)) < 2:
            problems.append("phase8b_orders_summary_multi_signal")
        if not _phase8b_runtime_is_exact_model_authored(summary):
            problems.append("phase8b_orders_summary_model")

    _recent_index, recent = phase_rows.get("recent_orders", (-1, {}))
    recent_orders = _order_numbers(_turn_canonical_tool_result(recent)) if recent else []
    if recent and (
        not set(_turn_tool_names(recent)).intersection(
            {"orders.recent", "orders.query"}
        )
        or not recent_orders
    ):
        problems.append("phase8b_recent_orders")

    _detail_index, detail = phase_rows.get("order_detail", (-1, {}))
    detail_orders = _order_numbers(_turn_canonical_tool_result(detail)) if detail else []
    if detail and (
        "orders.full_context" not in _turn_tool_names(detail)
        or len(set(detail_orders)) != 1
        or (recent_orders and not set(detail_orders).issubset(set(recent_orders)))
    ):
        problems.append("phase8b_order_detail_exact")

    _long_index, long_return = phase_rows.get("long_context_return", (-1, {}))
    long_orders = (
        _order_numbers(_turn_canonical_tool_result(long_return))
        if long_return
        else []
    )
    if long_return and (
        "orders.full_context" not in _turn_tool_names(long_return)
        or not detail_orders
        or set(long_orders) != set(detail_orders)
    ):
        problems.append("phase8b_long_context_exact_record")

    count_index, count_row = phase_rows.get("ready_count", (-1, {}))
    count_result = _turn_canonical_tool_result(count_row) if count_row else {}
    try:
        ready_count = int(
            count_result.get("ready_to_ship")
            or count_result.get("count")
            or count_result.get("selected_count")
            or 0
        )
    except (TypeError, ValueError):
        ready_count = 0
    if count_row and (
        "orders.ready_to_ship_count" not in _turn_tool_names(count_row)
        or ready_count < 0
    ):
        problems.append("phase8b_ready_count")

    list_index, list_row = phase_rows.get("ready_list", (-1, {}))
    ready_orders = _order_numbers(_turn_canonical_tool_result(list_row)) if list_row else []
    if list_row and (
        not set(_turn_tool_names(list_row)).intersection(
            {"orders.ready_to_ship", "orders.query"}
        )
        or len(ready_orders) != ready_count
        or bool(ready_count) != bool(ready_orders)
        or list_index <= count_index
    ):
        problems.append("phase8b_ready_list_exact_count")

    _risk_index, risk_row = phase_rows.get("fulfillment_risk", (-1, {}))
    if risk_row and not set(_turn_tool_names(risk_row)).intersection(
        {
            "orders.fulfillment_risk",
            "orders.fulfillment_risk_count",
            "orders.shipping_deadline_analysis",
        }
    ):
        problems.append("phase8b_fulfillment_risk")

    cargo_index, cargo_row = phase_rows.get("cargo_prepare", (-1, {}))
    if cargo_row:
        cargo_tools = set(_turn_tool_names(cargo_row))
        if (
            not cargo_tools.intersection(
                {
                    "orders.change_cargo_provider.prepare",
                    "orders.change_cargo_provider_bulk.prepare",
                }
            )
            or cargo_row.get("approval_required") is not True
            or not _phase8b_action_from_turn(cargo_row)
            or (cargo_row.get("execute") or {}).get("success") is True
        ):
            problems.append("phase8b_cargo_prepare_safe")
    cancel_index, cargo_cancel = phase_rows.get("cargo_cancel", (-1, {}))
    if cargo_cancel and (
        cancel_index <= cargo_index
        or (cargo_cancel.get("execute") or {}).get("success") is True
        or cargo_cancel.get("approval_required") is True
    ):
        problems.append("phase8b_cargo_cancel_effect_free")

    sales_index, sales_row = phase_rows.get("item_sales_list", (-1, {}))
    sales_result = _turn_canonical_tool_result(sales_row) if sales_row else {}
    sales_snapshot = (
        dict(sales_result.get("report_snapshot") or {})
        if isinstance(sales_result.get("report_snapshot"), dict)
        else {}
    )
    if sales_row and (
        "orders.item_sales_report" not in _turn_tool_names(sales_row)
        or not _compact(
            sales_snapshot.get("snapshot_id") or sales_result.get("snapshot_id")
        )
        or sales_row.get("approval_required") is True
        or (sales_row.get("execute") or {}).get("success") is True
    ):
        problems.append("phase8b_item_sales_list_snapshot_no_file")

    prepare_index, sales_prepare = phase_rows.get(
        "item_sales_excel_prepare", (-1, {})
    )
    sales_action = _phase8b_action_from_turn(sales_prepare) if sales_prepare else {}
    sales_payload = _action_payload(sales_action) if sales_action else {}
    prepared_snapshot = (
        dict(sales_payload.get("report_snapshot") or {})
        if isinstance(sales_payload.get("report_snapshot"), dict)
        else {}
    )
    sales_snapshot_id = _compact(
        sales_snapshot.get("snapshot_id") or sales_result.get("snapshot_id")
    )
    if sales_prepare and (
        "orders.item_sales_report_xlsx.prepare"
        not in _turn_tool_names(sales_prepare)
        or sales_prepare.get("approval_required") is not True
        or _compact(sales_action.get("action_type"))
        != "orders.action_export_report_snapshot_xlsx"
        or _compact(prepared_snapshot.get("snapshot_id")) != sales_snapshot_id
        or (sales_prepare.get("execute") or {}).get("success") is True
        or prepare_index <= sales_index
    ):
        problems.append("phase8b_item_sales_xlsx_prepare")

    pending_index, sales_pending = phase_rows.get(
        "item_sales_excel_pending", (-1, {})
    )
    if sales_pending:
        pending_runtime = (
            dict(sales_pending.get("runtime") or {})
            if isinstance(sales_pending.get("runtime"), dict)
            else {}
        )
        if (
            _turn_tool_names(sales_pending)
            or pending_runtime.get("model_invoked") is not False
            or pending_runtime.get("model_invocation_attempted") is not False
            or _compact(pending_runtime.get("final_response_source"))
            != "typed_pending_state_projection"
            or _compact(
                (sales_pending.get("pending_action") or {}).get("action_id")
            )
            != _compact(sales_action.get("action_id"))
            or pending_index <= prepare_index
        ):
            problems.append("phase8b_item_sales_pending_projection")

    execute_index, sales_execute = phase_rows.get(
        "item_sales_excel_execute", (-1, {})
    )
    execute_data = _effective_execute_data(sales_execute) if sales_execute else {}
    execute_verify = (
        dict(execute_data.get("verify") or {})
        if isinstance(execute_data.get("verify"), dict)
        else {}
    )
    execute_capability = (
        dict(execute_data.get("capability") or {})
        if isinstance(execute_data.get("capability"), dict)
        else {}
    )
    if sales_execute and (
        (sales_execute.get("execute") or {}).get("success") is not True
        or _compact(execute_capability.get("capability_id"))
        != "orders.action_export_report_snapshot_xlsx"
        or execute_verify.get("verified") is not True
        or _compact(execute_verify.get("verified_by"))
        != "xlsx_exact_snapshot_readback"
        or _compact(execute_verify.get("snapshot_id")) != sales_snapshot_id
        or not _compact(execute_verify.get("output_path")).casefold().endswith(
            ".xlsx"
        )
        or execute_index <= pending_index
    ):
        problems.append("phase8b_item_sales_xlsx_execute_readback")

    _identity_index, identity_row = phase_rows.get(
        "public_product_identity", (-1, {})
    )
    if identity_row and (
        "orders.product_public_identities" not in _turn_tool_names(identity_row)
        or not _phase8b_completed_tool_results(
            identity_row, "orders.product_public_identities"
        )
    ):
        problems.append("phase8b_public_product_identity")

    _web_index, web_row = phase_rows.get("public_web_research", (-1, {}))
    if web_row:
        web_tools = set(_turn_tool_names(web_row))
        opened = bool(
            web_tools.intersection({"web.open", "web.document.read"})
        )
        if (
            "web.search" not in web_tools
            or not opened
            or (web_row.get("execute") or {}).get("success") is True
        ):
            problems.append("phase8b_public_web_search_open")

    _private_index, private_row = phase_rows.get(
        "private_orders_web_boundary", (-1, {})
    )
    if private_row:
        private_tools = set(_turn_tool_names(private_row))
        private_answer = _fold_text(private_row.get("answer"))
        if (
            any(name.startswith("web.") for name in private_tools)
            or (private_row.get("execute") or {}).get("success") is True
            or not any(
                token in private_answer
                for token in (
                    "ozel",
                    "gizli",
                    "kisisel",
                    "siparis numarasi",
                    "urun bilgisi",
                    "public urun",
                )
            )
        ):
            problems.append("phase8b_private_orders_web_fail_closed")

    _cancel_index, cancellations = phase_rows.get("cancellations", (-1, {}))
    if cancellations and not set(_turn_tool_names(cancellations)).intersection(
        {"orders.cancellations", "orders.cancelled_count"}
    ):
        problems.append("phase8b_cancellations_read")

    _returns_index, waiting_returns = phase_rows.get(
        "waiting_returns", (-1, {})
    )
    if waiting_returns and not set(_turn_tool_names(waiting_returns)).intersection(
        {"returns.waiting.list", "returns.query", "returns.count"}
    ):
        problems.append("phase8b_waiting_returns_read")

    return list(dict.fromkeys(problems))


def _validate_real_conversation_semantics(turns: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    ready_rows = [row for row in turns if _turn_tool(row) == "orders.ready_to_ship"]
    exact_selection_rows = [
        row
        for row in ready_rows
        if int(_turn_tool_result(row).get("listed_count") or 0) == 21
        and len(list(_turn_tool_result(row).get("order_numbers") or [])) == 21
        and _turn_tool_result(row).get("truncated") is not True
    ]
    if not exact_selection_rows:
        problems.append("semantic_exact_21_order_selection")

    prepare_rows = [
        row
        for row in turns
        if _turn_tool(row) == "labels.create_from_orders.prepare"
        and int(_turn_tool_result(row).get("selected_record_count") or _turn_tool_result(row).get("count") or 0) == 21
        and len(list(_turn_tool_result(row).get("order_numbers") or [])) == 21
        and row.get("approval_required") is True
        and _turn_tool_result(row).get("scope_invariant_valid") is True
    ]
    if not prepare_rows:
        problems.append("semantic_exact_21_label_prepare")

    superseded = [
        item
        for row in turns
        for item in list(row.get("superseded_actions") or [])
        if isinstance(item, dict)
    ]
    if not superseded:
        problems.append("semantic_superseded_stale_approval")

    label_execute_rows: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(turns):
        execute = dict(row.get("execute") or {}) if isinstance(row.get("execute"), dict) else {}
        data = _turn_execute_data(row)
        verify = dict(data.get("verify") or {}) if isinstance(data.get("verify"), dict) else {}
        capability = dict(data.get("capability") or {}) if isinstance(data.get("capability"), dict) else {}
        action_type = _compact(capability.get("capability_id") or data.get("action_type"))
        order_numbers = list(verify.get("order_numbers") or verify.get("orders") or [])
        output_path = _compact(verify.get("output_path") or verify.get("path"))
        if (
            execute.get("success") is True
            and data.get("idempotent") is not True
            and verify.get("verified") is True
            and action_type == "labels.action_create_labels_from_selected_orders"
            and len(order_numbers) == 21
            and output_path.casefold().endswith(".docx")
            and _compact(verify.get("verified_by")) == "payload_and_docx_content"
        ):
            label_execute_rows.append((index, row))
    if not label_execute_rows:
        problems.append("semantic_fresh_21_label_docx_execute_verify")
    else:
        execute_index = label_execute_rows[0][0]
        if len(turns[execute_index + 1 :]) < 3:
            problems.append("semantic_post_operation_conversation")

    correction_rows = [
        row
        for row in turns[1:]
        if isinstance(row.get("review_previous"), dict)
        and _compact((row.get("review_previous") or {}).get("assessment")).casefold() in {"pass", "fail"}
        and (row.get("review_previous") or {}).get("correction_requested") is True
        and row.get("success") is True
    ]
    if not correction_rows:
        problems.append("semantic_direct_correction_recovery")
    return problems


def _validate_full_history_semantics(turns: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    deadline_indexes = [
        index
        for index, row in enumerate(turns)
        if _turn_tool(row) == "orders.shipping_deadline_analysis"
        and int(_turn_tool_result(row).get("requested_count") or 0) == 21
        and int(_turn_tool_result(row).get("matched_count") or 0) == 21
        and _turn_tool_result(row).get("truncated") is not True
    ]
    if not deadline_indexes:
        problems.append("semantic_selected_21_deadline_analysis")

    newest_ten_rows = [
        row
        for row in turns
        if _turn_tool(row) == "returns.query"
        and int((_turn_tool_result(row).get("pagination") or {}).get("returned") or 0) == 10
        and _compact(_turn_tool_result(row).get("sort")) == "claim_date_desc"
        and row.get("approval_required") is not True
    ]
    if not newest_ten_rows:
        problems.append("semantic_no_write_newest_10_returns")

    reason_indexes: list[int] = []
    full_reason_rows: list[dict[str, Any]] = []
    for index, row in enumerate(turns):
        if _turn_tool(row) != "returns.reason_summary":
            continue
        result = _turn_tool_result(row)
        reason_indexes.append(index)
        if (
            _compact(result.get("period")) == "all"
            and int(result.get("total_claims") or 0) > 100
            and result.get("reason_counting_rule")
            and result.get("multi_reason_claims") is not None
            and result.get("claims_without_reason") is not None
        ):
            full_reason_rows.append(row)
    if not full_reason_rows:
        problems.append("semantic_complete_full_history_reason_denominator")
    if len(reason_indexes) < 3:
        problems.append("semantic_reason_analysis_context_continuity")
    if deadline_indexes and reason_indexes and not any(index > min(reason_indexes) for index in deadline_indexes):
        problems.append("semantic_deadline_context_restore_after_returns")

    advice_rows = [
        row
        for index, row in enumerate(turns)
        if reason_indexes
        and index > min(reason_indexes)
        and not _turn_tool(row)
        and row.get("approval_required") is not True
        and any(token in _compact(row.get("prompt")).casefold() for token in ("tavsiye", "iyilestir", "işlem yapma", "islem yapma"))
    ]
    if not advice_rows:
        problems.append("semantic_post_analysis_advice_no_task")

    correction_rows = [
        row
        for row in turns[1:]
        if isinstance(row.get("review_previous"), dict)
        and _compact((row.get("review_previous") or {}).get("assessment")).casefold() in {"pass", "fail"}
        and (row.get("review_previous") or {}).get("correction_requested") is True
        and _turn_tool(row) == "returns.reason_summary"
    ]
    if not correction_rows:
        problems.append("semantic_return_analysis_natural_correction")
    return problems


def validate_source_ui_acceptance_artifact(
    payload: dict[str, Any],
    *,
    require_full_source_app: bool = True,
    require_fresh_execute: bool = True,
    require_current_runtime_source: bool = False,
    minimum_turns: int = 20,
    semantic_contract: str = "",
) -> list[str]:
    """Validate claims that used to be trusted as operator-authored metadata."""
    problems: list[str] = []
    if _compact(payload.get("artifact_type")) != "real_source_ui_human_directed":
        problems.append("artifact_type")
    try:
        evidence_contract_version = int(payload.get("evidence_contract_version") or 0)
    except (TypeError, ValueError):
        evidence_contract_version = 0
    if evidence_contract_version < 3:
        problems.append("evidence_contract_version")
    if evidence_contract_version >= 4:
        startup_fingerprint = _compact(payload.get("runtime_source_fingerprint"))
        current_fingerprint = _compact(
            payload.get("runtime_source_fingerprint_current")
        )
        source_files = list(payload.get("runtime_source_files") or [])
        if not startup_fingerprint or not current_fingerprint or not source_files:
            problems.append("runtime_source_fingerprint")
        if payload.get("runtime_source_stale") is not False:
            problems.append("runtime_source_stale")
        if (
            startup_fingerprint
            and current_fingerprint
            and startup_fingerprint != current_fingerprint
        ):
            problems.append("runtime_source_changed")
        if require_current_runtime_source:
            live_fingerprint = _compact(_runtime_source_evidence().get("fingerprint"))
            if not live_fingerprint or current_fingerprint != live_fingerprint:
                problems.append("runtime_source_not_current")
    if _compact(payload.get("final_status")).casefold() != "passed":
        problems.append("final_status")
    if bool(payload.get("fallback_allowed")):
        problems.append("fallback_allowed")
    if require_full_source_app:
        if _compact(payload.get("source_entrypoint")).replace("\\", "/").casefold() != "desktop/main.py":
            problems.append("source_entrypoint")
        if _compact(payload.get("ui_mode")).casefold() != "full_source_app":
            problems.append("ui_mode")
        if payload.get("source_surface_constructed") is not True:
            problems.append("source_surface_constructed")
        if not _compact(payload.get("source_window_runtime_class")).endswith(".MainInterface"):
            problems.append("source_window_runtime_class")
        if not _compact(payload.get("source_widget_runtime_class")).endswith(".AITab"):
            problems.append("source_widget_runtime_class")
        if _compact(payload.get("render_mode")).casefold() not in {"offscreen", "interactive"}:
            problems.append("render_mode")
        if not _compact(payload.get("acceptance_run_id")):
            problems.append("acceptance_run_id")

    turns = [dict(row) for row in list(payload.get("turns") or []) if isinstance(row, dict)]
    if len(turns) < max(1, int(minimum_turns or 20)):
        problems.append("minimum_turn_count")
    if turns and not all(bool(row.get("success")) for row in turns):
        problems.append("turn_failure")
    if turns and not all(_compact(row.get("selection_reason")) for row in turns):
        problems.append("selection_reason")

    human_review_ok = bool(turns)
    for index, row in enumerate(turns[1:], start=1):
        previous = turns[index - 1]
        review = dict(row.get("review_previous") or {}) if isinstance(row.get("review_previous"), dict) else {}
        required_seconds = _minimum_human_review_seconds(previous.get("answer"))
        if (
            int(review.get("turn") or 0) != int(previous.get("turn") or index)
            or not _review_allows_next_turn(review)
            or review.get("read_confirmed") is not True
            or _safe_float(review.get("review_seconds")) < required_seconds
        ):
            human_review_ok = False
            break
    final_review = dict(payload.get("final_review") or {}) if isinstance(payload.get("final_review"), dict) else {}
    if turns:
        last = turns[-1]
        if (
            int(final_review.get("turn") or 0) != int(last.get("turn") or len(turns))
            or _compact(final_review.get("assessment")).casefold() != "pass"
            or final_review.get("read_confirmed") is not True
            or _safe_float(final_review.get("review_seconds"))
            < _minimum_human_review_seconds(last.get("answer"))
        ):
            human_review_ok = False
    if not human_review_ok:
        problems.append("human_review")
    if payload.get("human_selects_each_next_prompt_after_reading_previous_turn") is not True:
        problems.append("adaptive_human_selection")
    if payload.get("fixed_prompt_list") is not False:
        problems.append("fixed_prompt_list")

    requested_model = _normalized_model(payload.get("requested_model"))
    invoked_turns = [
        row
        for row in turns
        if isinstance(row.get("runtime"), dict)
        and (row.get("runtime") or {}).get("model_invoked") is True
    ]
    if not invoked_turns:
        problems.append("model_not_proven_invoked")
    exact_model_turns = [
        row
        for row in invoked_turns
        if _normalized_model((row.get("runtime") or {}).get("actual_model")) == requested_model
    ]
    if requested_model and not exact_model_turns:
        problems.append("exact_model_not_proven")
    if evidence_contract_version >= 5:
        for row in turns:
            runtime = (
                dict(row.get("runtime") or {})
                if isinstance(row.get("runtime"), dict)
                else {}
            )
            for problem in validate_turn_model_provenance(
                runtime,
                requested_model=requested_model,
                require_outcome_history=True,
                require_normalized_error_evidence=(
                    evidence_contract_version >= 6
                ),
            ):
                problems.append(
                    f"turn_model_provenance:{int(row.get('turn') or 0)}:{problem}"
                )
        if invoked_turns and not any(
            (row.get("runtime") or {}).get("accepted_semantic_output") is True
            for row in invoked_turns
        ):
            problems.append("model_semantic_output_not_proven")
    if any(
        (row.get("runtime") or {}).get("fallback_used") is True
        or (row.get("runtime") or {}).get("any_model_fallback_used") is True
        for row in turns
    ):
        problems.append("fallback_used")

    if require_fresh_execute:
        fresh_verified_execute = False
        for row in turns:
            execute = dict(row.get("execute") or {}) if isinstance(row.get("execute"), dict) else {}
            execute_data = dict(execute.get("data") or {}) if isinstance(execute.get("data"), dict) else {}
            nested_execute = (
                dict(execute_data.get("execute") or {})
                if isinstance(execute_data.get("execute"), dict)
                else {}
            )
            verify_value = execute_data.get("verify") or nested_execute.get("verify")
            verify = dict(verify_value or {}) if isinstance(verify_value, dict) else {}
            idempotent = (
                execute_data.get("idempotent")
                if "idempotent" in execute_data
                else nested_execute.get("idempotent")
            )
            if (
                execute.get("success") is True
                and idempotent is not True
                and verify.get("verified") is True
            ):
                fresh_verified_execute = True
                break
        if not fresh_verified_execute:
            problems.append("fresh_verified_execute")

    contract = _compact(semantic_contract)
    if contract == "source_ui_real_conversation_reproduction":
        problems.extend(_validate_real_conversation_semantics(turns))
    elif contract == "source_ui_full_history_analysis_reproduction":
        problems.extend(_validate_full_history_semantics(turns))
    elif contract == "phase_8a_pending_read_live_revalidation":
        problems.extend(_validate_phase8a_pending_read_semantics(turns))
    elif contract == "phase_8a_approval_execute_readback_live_revalidation":
        problems.extend(_validate_phase8a_execute_readback_semantics(turns))
    elif contract == "phase_8a_correction_supersession_live_revalidation":
        problems.extend(_validate_phase8a_correction_supersession_semantics(turns))
    elif contract == "phase_8b_orders_organic_capability_revalidation":
        problems.extend(_validate_phase8b_orders_organic_semantics(turns))

    return list(dict.fromkeys(problems))


def _write_artifact(path: Path, payload: dict[str, Any]) -> None:
    redactor = LiveEvidenceRedactor()
    redactor.collect_public_urls(payload)
    redactor.collect(payload)
    sanitized = redactor.redact(payload)
    sanitized["privacy_redaction"] = redactor.metadata()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(sanitized, ensure_ascii=False, indent=2)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    last_error: OSError | None = None
    for _attempt in range(5):
        try:
            tmp_path.write_text(body, encoding="utf-8")
            os.replace(tmp_path, path)
            return
        except OSError as exc:
            last_error = exc
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


def _wait_for_workers(tab: Any, app: Any, *, timeout: float) -> None:
    deadline = time.monotonic() + max(5.0, float(timeout))
    while True:
        app.processEvents()
        chat_worker = getattr(tab, "_chat_worker", None)
        action_worker = getattr(tab, "_action_worker", None)
        chat_running = bool(
            chat_worker is not None
            and getattr(chat_worker, "isRunning", lambda: False)()
        )
        action_running = bool(
            action_worker is not None
            and getattr(action_worker, "isRunning", lambda: False)()
        )
        if (
            not chat_running
            and not action_running
            and chat_worker is None
            and action_worker is None
        ):
            app.processEvents()
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Source UI turn zaman asimina ugradi.")
        time.sleep(0.02)


def _ensure_provider_selection(
    tab: Any,
    *,
    provider_id: int,
    provider_label: str,
    provider_code: str,
    model: str,
    model_metadata: dict[str, Any] | None = None,
    free_model_test_route: dict[str, Any] | None = None,
) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidgetItem

    from AI.constants.ui_constants import AI_CHAT_SOURCE_CLOUD_VALUE

    cloud_index = tab.source_combo.findData(AI_CHAT_SOURCE_CLOUD_VALUE)
    tab.source_combo.blockSignals(True)
    tab.source_combo.setCurrentIndex(cloud_index)
    tab.source_combo.blockSignals(False)
    tab.model_list.clear()
    payload = {
        "id": int(provider_id),
        "label": provider_label,
        "provider_code": provider_code,
        "default_model": model,
        "reasoning_effort": "auto",
        "allow_model_fallback": False,
        "is_enabled": True,
        "model_metadata": dict(model_metadata or {}),
        "free_model_test_route": dict(free_model_test_route or {}),
        "_source_kind": "cloud_model",
        "_explicit_runtime_override": True,
    }
    item = QListWidgetItem(f"{provider_label} / {model}")
    item.setData(Qt.ItemDataRole.UserRole, payload)
    tab.model_list.addItem(item)
    tab.model_list.setCurrentRow(0)
    tab._update_chat_controls()


def _resolve_provider_model_selection(
    *,
    provider_id: int,
    provider_code: str,
    model: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the same live model metadata that the real Chat model list carries.

    The acceptance driver creates its list row programmatically.  Without this
    lookup, OpenRouter models lose their ``supported_parameters`` and are tested
    on the guarded-text path even though a normal UI selection enables native
    tools.  Fail closed rather than recording a false capability result.
    """

    from AI.processors.pipeline import get_provider_account, list_provider_models

    account = get_provider_account(int(provider_id))
    if not account.success:
        raise RuntimeError(account.message)
    provider = dict((account.data or {}).get("record") or {})
    catalog = list_provider_models(
        provider_code=provider_code,
        endpoint_url=_compact(provider.get("endpoint_url")),
        api_key=_compact(provider.get("api_key")),
        free_only=False,
        limit=500,
    )
    if not catalog.success:
        raise RuntimeError(catalog.message)
    data = dict(catalog.data or {})
    requested = _normalized_model(model)
    metadata = next(
        (
            dict(row)
            for row in list(data.get("records") or [])
            if isinstance(row, dict)
            and _normalized_model(row.get("id") or row.get("model_id")) == requested
        ),
        {},
    )
    if not metadata:
        raise RuntimeError(f"Secilen model canli provider katalogunda bulunamadi: {model}")
    return metadata, dict(data.get("free_model_test_route") or {})


def _capture_turn(
    tab: Any,
    *,
    prompt: str,
    review_previous: dict[str, Any],
    capture: dict[str, Any],
    started_at: str,
    completed_at: str,
    duration_seconds: float,
) -> dict[str, Any]:
    result = capture.pop("turn_result", None)
    execute_result = capture.pop("execute_result", None)
    data = dict(getattr(result, "data", None) or {})
    action = (
        dict(data.get("action_proposal") or {})
        if isinstance(data.get("action_proposal"), dict)
        else {}
    )
    context = (
        dict(data.get("conversation_context") or {})
        if isinstance(data.get("conversation_context"), dict)
        else {}
    )
    turn_interpretation = (
        dict(data.get("turn_interpretation") or {})
        if isinstance(data.get("turn_interpretation"), dict)
        else {}
    )
    runtime = (
        dict(data.get("runtime") or {})
        if isinstance(data.get("runtime"), dict)
        else {}
    )
    resource_plan = (
        dict(runtime.get("resource_plan") or {})
        if isinstance(runtime.get("resource_plan"), dict)
        else {}
    )
    provider_provenance = provider_invocation_provenance(resource_plan)
    capability_profile = (
        dict(resource_plan.get("capability_profile") or {})
        if isinstance(resource_plan.get("capability_profile"), dict)
        else {}
    )
    nested_tool_result = (
        dict(data.get("tool_result") or {})
        if isinstance(data.get("tool_result"), dict)
        else {}
    )
    task_state = (
        dict(data.get("state") or {})
        if isinstance(data.get("state"), dict)
        else (
            dict(nested_tool_result.get("state") or {})
            if isinstance(nested_tool_result.get("state"), dict)
            else {}
        )
    )
    active_entities = dict(task_state.get("active_entities") or {})
    task_plan = (
        dict(active_entities.get("task_plan") or {})
        if isinstance(active_entities.get("task_plan"), dict)
        else {}
    )
    serialized_tool_calls: list[dict[str, Any]] = []
    seen_tool_calls: set[str] = set()
    for row in list(data.get("tool_calls") or []) + list(
        data.get("direct_tool_calls") or []
    ):
        if not isinstance(row, dict):
            continue
        clean_row = dict(row)
        fingerprint = json.dumps(
            clean_row,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if fingerprint in seen_tool_calls:
            continue
        seen_tool_calls.add(fingerprint)
        serialized_tool_calls.append(clean_row)
    serialized_tool_results = [
        dict(row)
        for row in list(data.get("direct_tool_results") or [])
        if isinstance(row, dict)
    ]
    selected_tool = _compact(
        (
            dict(data.get("tool_call") or {}).get("tool")
            if isinstance(data.get("tool_call"), dict)
            else ""
        )
        or next(
            (
                dict(row).get("tool")
                for row in serialized_tool_calls
                if isinstance(row, dict) and _compact(row.get("tool"))
            ),
            "",
        )
    )
    response_synthesis = (
        dict(active_entities.get("response_synthesis") or {})
        if isinstance(active_entities.get("response_synthesis"), dict)
        else {}
    )
    if (
        not response_synthesis
        and isinstance(data.get("response_synthesis"), dict)
    ):
        response_synthesis = dict(data.get("response_synthesis") or {})
    final_response_source = _compact(
        data.get("final_response_source")
        or runtime.get("final_response_source")
        or response_synthesis.get("final_source")
    )
    decision_path = _compact(
        data.get("decision_path") or runtime.get("decision_path")
    )
    final_model_response_received = bool(
        runtime.get("final_model_response_received")
        if "final_model_response_received" in runtime
        else provider_provenance.get("final_model_response_received")
    )
    projection_acceptance = model_authored_projection_acceptance(
        task_state,
        selected_operation_ids=[selected_tool] if selected_tool else [],
        final_model_response_received=final_model_response_received,
    )
    model_authored_plan_accepted = bool(
        projection_acceptance.get("model_authored_plan_accepted")
        and provider_provenance.get("any_model_response_received") is True
    )
    verified_business_projection = bool(
        projection_acceptance.get("verified_business_projection")
        and provider_provenance.get("any_model_response_received") is True
    )
    accepted_semantic_output = bool(
        data.get("accepted_semantic_output")
        or runtime.get("accepted_semantic_output")
        or final_response_source
        in {"verified_model_candidate", "verified_model_repair"}
        or (
            final_response_source
            == "deterministic_verified_uncertainty"
            and final_model_response_received
        )
        or (
            final_response_source
            == "deterministic_verified_non_business_fallback"
            and final_model_response_received
        )
        or (
            decision_path == "typed_model_non_business_turn"
            and final_model_response_received
        )
        or verified_business_projection
    )
    assistant_rows = [
        dict(row)
        for row in list(getattr(tab, "_chat_history", []) or [])
        if isinstance(row, dict) and row.get("role") == "assistant"
    ]
    result_failed_message = _compact(
        getattr(result, "message", "")
        if result is not None and not bool(getattr(result, "success", False))
        else ""
    )
    visible_answer = _compact(
        data.get("answer")
        or result_failed_message
        or (assistant_rows[-1].get("content") if assistant_rows else "")
        or getattr(result, "message", "")
    )
    execute_data = dict(getattr(execute_result, "data", None) or {})
    stale_action_rejected = bool(
        execute_result is not None
        and not bool(getattr(execute_result, "success", False))
        and execute_data.get("stale_approval") is True
    )
    raw_success = (
        bool(getattr(result, "success", False))
        if result is not None
        else bool(getattr(execute_result, "success", False))
    )
    provider_unavailable = bool(data.get("provider_unavailable"))
    intentional_cancel = not raw_success and _intentional_cancel_completed(prompt, visible_answer)
    state = (
        dict(getattr(tab, "_agent_state", {}) or {})
        if isinstance(getattr(tab, "_agent_state", {}), dict)
        else {}
    )
    pending = (
        dict(state.get("pending_action") or {})
        if isinstance(state.get("pending_action"), dict)
        else {}
    )
    return {
        "turn": len(
            [
                row
                for row in list(getattr(tab, "_chat_history", []) or [])
                if isinstance(row, dict) and row.get("role") == "user"
            ]
        ),
        "prompt": prompt,
        "review_previous": dict(review_previous or {}),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(max(0.0, float(duration_seconds or 0.0)), 3),
        "success": (
            (raw_success and not provider_unavailable)
            or intentional_cancel
            or stale_action_rejected
        ),
        "turn_outcome": (
            "provider_unavailable"
            if provider_unavailable
            else "stale_action_rejected"
            if stale_action_rejected
            else "cancelled"
            if intentional_cancel
            else "completed"
            if raw_success
            else "failed"
        ),
        "answer": visible_answer,
        "mode": _compact(data.get("mode")),
        "tool_call": dict(data.get("tool_call") or {})
        if isinstance(data.get("tool_call"), dict)
        else {},
        # Direct canonical operations (for example the capability catalog) are
        # part of the product turn just like task-runtime tool calls. Preserve
        # both in one evidence stream so acceptance cannot pass on prose alone.
        "tool_calls": serialized_tool_calls,
        "direct_tool_results": serialized_tool_results,
        "tool_result": dict(data.get("tool_result") or {})
        if isinstance(data.get("tool_result"), dict)
        else {},
        "conversation_context": context,
        "turn_interpretation": turn_interpretation,
        "approval_required": bool(data.get("approval_required")),
        "action_proposal": action,
        "agent_state": state,
        "pending_action": pending,
        "superseded_actions": [
            dict(row)
            for row in list(getattr(tab, "_superseded_actions", []) or [])
            if isinstance(row, dict)
        ],
        "runtime": {
            "source": _compact(runtime.get("source")),
            "runtime_name": _compact(runtime.get("runtime_name")),
            "model_name": _compact(runtime.get("model_name")),
            "model_invoked": bool(runtime.get("model_invoked")),
            "decision_path": decision_path,
            "accepted_semantic_output": accepted_semantic_output,
            "accepted_semantic_output_source": (
                "model_loop_v1"
                if decision_path == "model_loop_v1" and accepted_semantic_output
                else "model_authored_verified_projection"
                if verified_business_projection
                else "llm_direct_task_plan"
                if model_authored_plan_accepted
                else "deterministic_verified_uncertainty"
                if (
                    accepted_semantic_output
                    and final_response_source
                    == "deterministic_verified_uncertainty"
                )
                else "deterministic_verified_non_business_fallback"
                if (
                    accepted_semantic_output
                    and final_response_source
                    == "deterministic_verified_non_business_fallback"
                )
                else "verified_model_response"
                if accepted_semantic_output
                else ""
            ),
            "final_response_source": final_response_source,
            "requested_model": _compact(
                provider_provenance.get("requested_model")
            ),
            "actual_model": _compact(
                provider_provenance.get("last_successful_actual_model")
            ),
            "final_actual_model": _compact(
                provider_provenance.get("final_actual_model")
            ),
            "model_response_count": int(
                provider_provenance.get("model_response_count") or 0
            ),
            "any_model_response_received": bool(
                provider_provenance.get("any_model_response_received")
            ),
            "final_model_response_received": bool(
                provider_provenance.get("final_model_response_received")
            ),
            "any_model_fallback_used": bool(
                provider_provenance.get("any_model_fallback_used")
            ),
            "fallback_allowed": resource_plan.get("fallback_allowed"),
            "fallback_used": provider_provenance.get("final_fallback_used"),
            "model_invocation_attempted": bool(
                resource_plan.get("model_invocation_attempted") is True
                or provider_provenance.get("invocation_outcome_history")
            ),
            "invocation_error_reason": _compact(
                provider_provenance.get("final_invocation_error_reason")
            ),
            "error_category": _compact(
                provider_provenance.get("final_error_category")
            ),
            "quota_scope": _compact(
                provider_provenance.get("final_quota_scope")
            ),
            "status_code": provider_provenance.get("final_status_code"),
            "model_fallback_allowed": provider_provenance.get(
                "final_model_fallback_allowed"
            ),
            "fallback_blocked_reason": _compact(
                provider_provenance.get(
                    "final_fallback_blocked_reason"
                )
            ),
            "retry_after_seconds": provider_provenance.get(
                "final_retry_after_seconds"
            ),
            "normalized_error_history": [
                dict(value)
                for value in list(
                    provider_provenance.get("normalized_error_history")
                    or []
                )
                if isinstance(value, dict)
            ],
            "same_model_retry_events": [
                {
                    "model": _compact(value.get("model")),
                    "attempt": int(value.get("attempt") or 0),
                    "reason": _compact(value.get("reason")),
                }
                for value in list(
                    resource_plan.get("same_model_retry_events") or []
                )
                if isinstance(value, dict)
            ],
            "request_prompt_hashes": [
                {
                    "model": _compact(value.get("model")),
                    "prompt_sha256": _compact(value.get("prompt_sha256")),
                    "attempt": int(value.get("attempt") or 0),
                }
                for value in list(
                    resource_plan.get("request_prompt_hashes") or []
                )
                if isinstance(value, dict)
            ],
            "last_invocation_contract": _compact(
                resource_plan.get("last_invocation_contract")
            ),
            "invocation_contract_history": [
                _compact(value)
                for value in list(
                    resource_plan.get("invocation_contract_history") or []
                )
                if _compact(value)
            ],
            "invocation_outcome_history": [
                dict(value)
                for value in list(
                    provider_provenance.get("invocation_outcome_history") or []
                )
                if isinstance(value, dict)
            ],
            "structured_output_request_timeout_seconds": _safe_float(
                resource_plan.get(
                    "structured_output_request_timeout_seconds"
                )
            ),
            "structured_output_recovery_reserve_seconds": _safe_float(
                resource_plan.get(
                    "structured_output_recovery_reserve_seconds"
                )
            ),
            "structured_output_health_cache_hit": (
                resource_plan.get("structured_output_health_cache_hit")
                is True
            ),
            "structured_output_bypassed": (
                resource_plan.get("structured_output_bypassed") is True
            ),
            "structured_output_bypass_reason": _compact(
                resource_plan.get("structured_output_bypass_reason")
            ),
            "guarded_json_max_tokens": int(
                resource_plan.get("guarded_json_max_tokens") or 0
            ),
            "degradation_mode": _compact(resource_plan.get("degradation_mode")),
            "capability_profile": {
                "native_tool_calling_available": capability_profile.get(
                    "native_tool_calling_available"
                )
                is True,
                "native_tool_runtime_enabled": capability_profile.get(
                    "native_tool_runtime_enabled"
                )
                is True,
                "structured_output_available": capability_profile.get(
                    "structured_output_available"
                )
                is True,
                "structured_output_runtime_enabled": capability_profile.get(
                    "structured_output_runtime_enabled"
                )
                is True,
            },
            "fallback_attempts": [
                dict(row)
                for row in list(resource_plan.get("fallback_attempts") or [])
                if isinstance(row, dict)
            ],
        },
        "response_synthesis": response_synthesis,
        "execute": {
            "success": bool(getattr(execute_result, "success", False))
            if execute_result is not None
            else None,
            "message": _compact(getattr(execute_result, "message", "")),
            "data": execute_data,
        },
        "transcript_text": _compact(tab.transcript.toPlainText()),
    }


def _capture_timeout_turn(
    tab: Any,
    *,
    prompt: str,
    review_previous: dict[str, Any],
    requested_model: str,
    provider_code: str,
    started_at: str,
    completed_at: str,
    duration_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Build explicit failure evidence without reusing a stale assistant response.

    The worker can still be blocked in provider or runtime code when the source-UI
    acceptance deadline expires.  Therefore this record deliberately does not claim
    whether a model, tool, or side effect ran; it records only what the driver knows:
    no completed turn result was observed before the deadline.
    """

    user_turn_count = len(
        [
            row
            for row in list(getattr(tab, "_chat_history", []) or [])
            if isinstance(row, dict) and row.get("role") == "user"
        ]
    )
    transcript = getattr(tab, "transcript", None)
    transcript_text = (
        _compact(transcript.toPlainText())
        if transcript is not None and hasattr(transcript, "toPlainText")
        else ""
    )
    return {
        "turn": user_turn_count,
        "prompt": prompt,
        "review_previous": dict(review_previous or {}),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(max(0.0, float(duration_seconds or 0.0)), 3),
        "timeout_seconds": round(max(0.0, float(timeout_seconds or 0.0)), 3),
        "success": False,
        "turn_outcome": "source_ui_timeout",
        "answer": (
            "Source UI turu zaman aşımına uğradı; tamamlanmış bir sonuç alınamadı. "
            "Bu koşu kabul kanıtı değildir ve fresh process ile yeniden başlatılmalıdır."
        ),
        "mode": "",
        "tool_call": {},
        "tool_calls": [],
        "direct_tool_results": [],
        "tool_result": {},
        "conversation_context": {},
        "turn_interpretation": {},
        "approval_required": False,
        "action_proposal": {},
        "agent_state": {},
        "pending_action": {},
        "superseded_actions": [],
        "runtime": {
            "source": "source_ui_acceptance_driver",
            "runtime_name": "source_ui_timeout",
            "model_name": "",
            "model_invoked": None,
            "decision_path": "acceptance_driver_timeout",
            "accepted_semantic_output": False,
            "accepted_semantic_output_source": "",
            "final_response_source": "",
            "requested_model": _compact(requested_model),
            "actual_model": "",
            "final_actual_model": "",
            "model_response_count": 0,
            "any_model_response_received": False,
            "final_model_response_received": False,
            "any_model_fallback_used": False,
            "fallback_allowed": False,
            "fallback_used": False,
            "model_invocation_attempted": None,
            "model_observation_state": "unknown_due_to_timeout",
            "tool_observation_state": "unknown_due_to_timeout",
            "effect_observation_state": "unknown_due_to_timeout",
            "invocation_error_reason": "source_ui_turn_timeout",
            "error_category": "acceptance_driver_timeout",
            "quota_scope": "",
            "status_code": None,
            "model_fallback_allowed": False,
            "fallback_blocked_reason": "source_ui_timeout_requires_fresh_process",
            "retry_after_seconds": None,
            "normalized_error_history": [],
            "same_model_retry_events": [],
            "request_prompt_hashes": [],
            "last_invocation_contract": "",
            "invocation_contract_history": [],
            "invocation_outcome_history": [],
            "degradation_mode": "",
            "capability_profile": {},
            "fallback_attempts": [],
            "provider_code": _compact(provider_code),
        },
        "response_synthesis": {
            "final_projection_verified": False,
            "failure_reason": "source_ui_turn_timeout",
        },
        "execute": {
            "success": None,
            "message": "",
            "data": {},
        },
        "transcript_text": transcript_text,
    }


def _close_artifact_after_timeout(
    artifact: dict[str, Any],
    *,
    turn: dict[str, Any],
    timeout_seconds: float,
    minimum_turns: int,
) -> None:
    """Close a timed-out acceptance process as explicit non-acceptance evidence."""

    artifact.setdefault("turns", []).append(dict(turn))
    artifact["final_status"] = "failed"
    artifact["terminal_reason"] = "source_ui_turn_timeout"
    artifact["restart_required"] = True
    artifact["timeout_seconds"] = round(
        max(0.0, float(timeout_seconds or 0.0)),
        3,
    )
    artifact["human_selects_each_next_prompt_after_reading_previous_turn"] = False
    artifact["fixed_prompt_list"] = False
    artifact["final_review"] = {
        "turn": int(turn.get("turn") or len(artifact.get("turns") or [])),
        "assessment": "fail",
        "notes": "source_ui_turn_timeout",
        "read_confirmed": False,
        "review_seconds": 0.0,
    }
    artifact["updated_at"] = datetime.now(timezone.utc).isoformat()
    validation_problems = validate_source_ui_acceptance_artifact(
        artifact,
        require_full_source_app=True,
        require_fresh_execute=False,
        minimum_turns=max(1, int(minimum_turns or 20)),
    )
    problems = ["source_ui_turn_timeout"]
    problems.extend(
        problem for problem in validation_problems if problem not in problems
    )
    artifact["acceptance_validation"] = {
        "requested_status": "failed",
        "accepted": False,
        "problems": problems,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    _configure_interactive_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=(
            "Keep the real AITab widget alive while a human chooses each next "
            "source-UI acceptance turn. Read one JSON command per line."
        )
    )
    parser.add_argument("--provider-id", type=int, required=True)
    parser.add_argument("--provider-label", required=True)
    parser.add_argument("--provider-code", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument(
        "--minimum-turns",
        type=int,
        default=20,
        help="Focused source-UI regressions may declare a smaller auditable turn contract.",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from AI.views import chat_tab as chat_module
    from main import build_source_app_ai_acceptance_surface

    app = QApplication.instance() or QApplication([])
    source_window, tab = build_source_app_ai_acceptance_surface(app)
    app.processEvents()
    startup_source_evidence = _runtime_source_evidence()
    model_metadata, free_model_test_route = _resolve_provider_model_selection(
        provider_id=args.provider_id,
        provider_code=args.provider_code,
        model=args.model,
    )
    _ensure_provider_selection(
        tab,
        provider_id=args.provider_id,
        provider_label=args.provider_label,
        provider_code=args.provider_code,
        model=args.model,
        model_metadata=model_metadata,
        free_model_test_route=free_model_test_route,
    )

    capture: dict[str, Any] = {}
    acceptance_run_id = uuid.uuid4().hex
    original_turn_runner = chat_module._run_chat_turn_with_runtime
    original_execute_runner = chat_module._run_approved_chat_action

    def capture_turn_runner(*runner_args: Any, **runner_kwargs: Any) -> Any:
        result = original_turn_runner(*runner_args, **runner_kwargs)
        capture["turn_result"] = result
        return result

    def capture_execute_runner(*runner_args: Any, **runner_kwargs: Any) -> Any:
        positional = list(runner_args)
        keyword = dict(runner_kwargs)
        if positional and isinstance(positional[0], dict):
            action = dict(positional[0])
            action["_source_ui_acceptance_run_id"] = acceptance_run_id
            positional[0] = action
        elif isinstance(keyword.get("action"), dict):
            action = dict(keyword.get("action") or {})
            action["_source_ui_acceptance_run_id"] = acceptance_run_id
            keyword["action"] = action
        result = original_execute_runner(*positional, **keyword)
        capture["execute_result"] = result
        return result

    chat_module._run_chat_turn_with_runtime = capture_turn_runner
    chat_module._run_approved_chat_action = capture_execute_runner

    artifact_path = Path(args.artifact_path)
    artifact: dict[str, Any] = {
        "name": "orders-source-ui-human-recheck",
        "artifact_type": "real_source_ui_human_directed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider_code": args.provider_code,
        "provider_id": int(args.provider_id),
        "requested_model": args.model,
        "fallback_allowed": False,
        "evidence_contract_version": 6,
        "acceptance_run_id": acceptance_run_id,
        "runtime_process_id": int(os.getpid()),
        "runtime_source_fingerprint": startup_source_evidence["fingerprint"],
        "runtime_source_fingerprint_current": startup_source_evidence["fingerprint"],
        "runtime_source_files": list(startup_source_evidence["files"]),
        "runtime_source_stale": False,
        "source_entrypoint": "desktop/main.py",
        "ui_mode": "full_source_app",
        "source_shell": "Main_interface.views.MainInterface",
        "source_widget": "AI.views.chat_tab.AITab",
        "source_surface_constructed": True,
        "source_window_runtime_class": f"{type(source_window).__module__}.{type(source_window).__name__}",
        "source_widget_runtime_class": f"{type(tab).__module__}.{type(tab).__name__}",
        "render_mode": _compact(os.environ.get("QT_QPA_PLATFORM")) or "interactive",
        "source_send_path": "AITab._send_message",
        "human_selects_each_next_prompt_after_reading_previous_turn": False,
        "fixed_prompt_list": True,
        "minimum_turn_contract": max(1, int(args.minimum_turns or 20)),
        "turns": [],
        "final_status": "open",
    }
    _write_artifact(artifact_path, artifact)
    print(
        json.dumps(
            {
                "ready": True,
                "provider": args.provider_code,
                "model": args.model,
                "commands": ["turn", "finalize", "quit"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    last_turn_completed_monotonic: float | None = None
    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            command = _parse_jsonl_command(line)
            action = _compact(command.get("action")).casefold() or "turn"
            if action == "quit":
                print(json.dumps({"success": True, "closed": True}), flush=True)
                return 0
            current_source_evidence = _runtime_source_evidence()
            artifact["runtime_source_fingerprint_current"] = current_source_evidence[
                "fingerprint"
            ]
            artifact["runtime_source_stale"] = bool(
                current_source_evidence["fingerprint"]
                != startup_source_evidence["fingerprint"]
            )
            if artifact["runtime_source_stale"]:
                artifact["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_artifact(artifact_path, artifact)
                print(
                    json.dumps(
                        {
                            "success": False,
                            "error": "runtime_source_changed_restart_required",
                            "message": (
                                "Acceptance source files changed after process start; "
                                "restart the offscreen source-app process before continuing."
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue
            if action == "finalize":
                requested_status = _compact(command.get("status")).casefold() or "open"
                require_fresh_execute = command.get("require_fresh_execute") is not False
                last_review_input = (
                    dict(command.get("review_last") or {})
                    if isinstance(command.get("review_last"), dict)
                    else {}
                )
                last_turn = (artifact.get("turns") or [])[-1] if artifact.get("turns") else {}
                artifact["final_review"] = {
                    "turn": int(last_turn.get("turn") or 0),
                    "assessment": _compact(last_review_input.get("assessment")).casefold(),
                    "notes": _compact(last_review_input.get("notes")),
                    "read_confirmed": last_review_input.get("read_confirmed") is True,
                    "review_seconds": round(
                        max(0.0, time.monotonic() - last_turn_completed_monotonic)
                        if last_turn_completed_monotonic is not None
                        else 0.0,
                        3,
                    ),
                }
                turns = list(artifact.get("turns") or [])
                adaptive = bool(turns) and all(
                    isinstance(row.get("review_previous"), dict)
                    and (row.get("review_previous") or {}).get("read_confirmed") is True
                    and _review_allows_next_turn(dict(row.get("review_previous") or {}))
                    and _compact(row.get("selection_reason"))
                    for row in turns[1:]
                )
                adaptive = bool(
                    adaptive
                    and artifact["final_review"].get("read_confirmed") is True
                    and artifact["final_review"].get("assessment") == "pass"
                )
                artifact["human_selects_each_next_prompt_after_reading_previous_turn"] = adaptive
                artifact["fixed_prompt_list"] = not adaptive
                artifact["final_status"] = "passed" if requested_status == "passed" else requested_status
                artifact["fresh_execute_required"] = require_fresh_execute
                artifact["final_notes"] = _compact(command.get("notes"))
                artifact["updated_at"] = datetime.now(timezone.utc).isoformat()
                validation_problems = validate_source_ui_acceptance_artifact(
                    artifact,
                    require_full_source_app=True,
                    require_fresh_execute=require_fresh_execute,
                    minimum_turns=max(1, int(args.minimum_turns or 20)),
                )
                if requested_status == "passed" and validation_problems:
                    artifact["final_status"] = "open"
                artifact["acceptance_validation"] = {
                    "requested_status": requested_status,
                    "accepted": requested_status == "passed" and not validation_problems,
                    "problems": validation_problems,
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                }
                _write_artifact(artifact_path, artifact)
                print(
                    json.dumps(
                        {
                            "success": True,
                            "final_status": artifact["final_status"],
                            "turn_count": len(artifact["turns"]),
                            "acceptance_validation": artifact["acceptance_validation"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue
            prompt = _compact(command.get("prompt"))
            if not prompt:
                raise ValueError("turn komutu prompt gerektirir.")
            review_previous_input = (
                dict(command.get("review_previous") or {})
                if isinstance(command.get("review_previous"), dict)
                else {}
            )
            previous_turn = (artifact.get("turns") or [])[-1] if artifact.get("turns") else {}
            review_previous = {}
            if previous_turn:
                review_previous = {
                    "turn": int(previous_turn.get("turn") or 0),
                    "assessment": _compact(review_previous_input.get("assessment")).casefold(),
                    "notes": _compact(review_previous_input.get("notes")),
                    "read_confirmed": review_previous_input.get("read_confirmed") is True,
                    "correction_requested": review_previous_input.get("correction_requested") is True,
                    "review_seconds": round(
                        max(0.0, time.monotonic() - last_turn_completed_monotonic)
                        if last_turn_completed_monotonic is not None
                        else 0.0,
                        3,
                    ),
                }
            _ensure_provider_selection(
                tab,
                provider_id=args.provider_id,
                provider_label=args.provider_label,
                provider_code=args.provider_code,
                model=args.model,
                model_metadata=model_metadata,
                free_model_test_route=free_model_test_route,
            )
            turn_started_monotonic = time.monotonic()
            turn_started_at = datetime.now(timezone.utc).isoformat()
            tab.composer.setPlainText(prompt)
            tab._send_message()
            try:
                _wait_for_workers(tab, app, timeout=args.timeout)
            except TimeoutError:
                turn_completed_monotonic = time.monotonic()
                turn_completed_at = datetime.now(timezone.utc).isoformat()
                turn = _capture_timeout_turn(
                    tab,
                    prompt=prompt,
                    review_previous=review_previous,
                    requested_model=args.model,
                    provider_code=args.provider_code,
                    started_at=turn_started_at,
                    completed_at=turn_completed_at,
                    duration_seconds=(
                        turn_completed_monotonic - turn_started_monotonic
                    ),
                    timeout_seconds=args.timeout,
                )
                turn["selection_reason"] = _compact(command.get("reason"))
                _close_artifact_after_timeout(
                    artifact,
                    turn=turn,
                    timeout_seconds=args.timeout,
                    minimum_turns=max(1, int(args.minimum_turns or 20)),
                )
                _write_artifact(artifact_path, artifact)
                print(
                    json.dumps(
                        {
                            "success": False,
                            "terminal": True,
                            "restart_required": True,
                            "error": "source_ui_turn_timeout",
                            "turn": turn.get("turn"),
                            "turn_outcome": turn.get("turn_outcome"),
                            "requested_model": args.model,
                            "answer_preview": turn.get("answer"),
                            "final_status": artifact.get("final_status"),
                            "acceptance_validation": artifact.get(
                                "acceptance_validation"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                # The timed-out QThread can be blocked inside provider/network code and
                # AITab.closeEvent() waits for it indefinitely.  This CLI is an isolated
                # acceptance subprocess, so terminate the whole process only after the
                # failure artifact and terminal JSON response are durably written.
                os._exit(124)
            turn_completed_monotonic = time.monotonic()
            turn_completed_at = datetime.now(timezone.utc).isoformat()
            turn = _capture_turn(
                tab,
                prompt=prompt,
                review_previous=review_previous,
                capture=capture,
                started_at=turn_started_at,
                completed_at=turn_completed_at,
                duration_seconds=turn_completed_monotonic - turn_started_monotonic,
            )
            turn["selection_reason"] = _compact(command.get("reason"))
            artifact["turns"].append(turn)
            last_turn_completed_monotonic = turn_completed_monotonic
            artifact["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_artifact(artifact_path, artifact)
            redactor = LiveEvidenceRedactor()
            redactor.collect(turn)
            redacted_turn = redactor.redact(turn)
            tool_call = (
                dict(redacted_turn.get("tool_call") or {})
                if isinstance(redacted_turn.get("tool_call"), dict)
                else {}
            )
            pending = (
                dict(redacted_turn.get("pending_action") or {})
                if isinstance(redacted_turn.get("pending_action"), dict)
                else {}
            )
            print(
                json.dumps(
                    {
                        "turn": redacted_turn.get("turn"),
                        "success": redacted_turn.get("success"),
                        "tool": tool_call.get("tool"),
                        "approval_required": redacted_turn.get("approval_required"),
                        "pending_summary": pending.get("summary"),
                        "superseded_count": len(
                            list(redacted_turn.get("superseded_actions") or [])
                        ),
                        "runtime": redacted_turn.get("runtime"),
                        "answer_preview": _compact(
                            str(redacted_turn.get("answer") or "")[:500]
                        ),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        chat_module._run_chat_turn_with_runtime = original_turn_runner
        chat_module._run_approved_chat_action = original_execute_runner
        tab.close()
        tab.deleteLater()
        source_window.close()
        source_window.deleteLater()
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
