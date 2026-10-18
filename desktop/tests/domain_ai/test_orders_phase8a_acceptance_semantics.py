from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from AI.processors.acceptance_manifest import validate_turn_model_provenance
from AI.processors.orders_source_ui_human_recheck_cli import (
    _runtime_source_evidence,
    validate_source_ui_acceptance_artifact,
)


MODEL = "gemini-3-flash-preview"
ORDER_NUMBERS = ["ORD-P8A-001", "ORD-P8A-002", "ORD-P8A-003"]
SOURCE_SNAPSHOT_HASH = "phase8a-source-snapshot"
SOURCE_REVISION = "1785000000000"
COUNT_FINGERPRINT = "phase8a-count-fingerprint"


def _model_runtime() -> dict[str, Any]:
    return {
        "model_invoked": True,
        "model_invocation_attempted": True,
        "model_response_count": 1,
        "any_model_response_received": True,
        "final_model_response_received": True,
        "requested_model": MODEL,
        "actual_model": MODEL,
        "final_actual_model": MODEL,
        "fallback_used": False,
        "any_model_fallback_used": False,
        "accepted_semantic_output": True,
        "final_response_source": "verified_model_candidate",
        "invocation_error_reason": "",
        "invocation_contract_history": ["structured_output"],
        "invocation_outcome_history": [
            {
                "contract": "structured_output",
                "requested_model": MODEL,
                "actual_model": MODEL,
                "response_received": True,
                "error_reason": "",
                "fallback_used": False,
            }
        ],
    }


def _deterministic_runtime(*, pending_read: bool = False) -> dict[str, Any]:
    return {
        "model_invoked": False,
        "model_invocation_attempted": False,
        "model_response_count": 0,
        "any_model_response_received": False,
        "final_model_response_received": False,
        "requested_model": MODEL,
        "actual_model": "",
        "final_actual_model": "",
        "fallback_used": False,
        "any_model_fallback_used": False,
        "accepted_semantic_output": False,
        "final_response_source": (
            "typed_pending_state_projection" if pending_read else "runtime_projection"
        ),
        "decision_path": (
            "pending_action_scope_read_guard" if pending_read else "typed_runtime"
        ),
        "invocation_error_reason": "",
        "invocation_contract_history": [],
        "invocation_outcome_history": [],
    }


def _label_action(
    action_id: str,
    order_numbers: list[str],
    *,
    model_code: str = "TANEX_2610",
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "action_type": "labels.action_create_labels_from_selected_orders",
        "status": "pending_approval",
        "approval_required": True,
        "risk_level": "medium",
        "summary": f"{len(order_numbers)} siparis icin etiket hazirlaniyor.",
        "arguments": {
            "payload": {
                "order_numbers": list(order_numbers),
                "brand_code": "TANEX",
                "model_code": model_code,
            },
            "source_selection_id": "phase8a-selection",
            "validation_source_snapshot_hash": SOURCE_SNAPSHOT_HASH,
            "source_snapshot_hash": SOURCE_SNAPSHOT_HASH,
            "source_query_fingerprint": COUNT_FINGERPRINT,
        },
        "rows": [
            {"operation": "create_label", "order_number": order_number}
            for order_number in order_numbers
        ],
    }


def _review(turn: int) -> dict[str, Any]:
    return {
        "turn": turn,
        "assessment": "pass",
        "read_confirmed": True,
        "review_seconds": 60.0,
    }


def _base_turn(
    number: int,
    *,
    prompt: str,
    answer: str,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "turn": number,
        "prompt": prompt,
        "answer": answer,
        "success": True,
        "turn_outcome": "completed",
        "selection_reason": "Onceki authoritative sonucu ilerletmek icin secildi.",
        "runtime": runtime,
        "tool_call": {},
        "tool_calls": [],
        "tool_result": {},
        "approval_required": False,
        "pending_action": {},
        "superseded_actions": [],
        "execute": {"success": None, "data": {}},
    }
    if number > 1:
        row["review_previous"] = _review(number - 1)
    return row


def _count_turn() -> dict[str, Any]:
    row = _base_turn(
        1,
        prompt="başkan kaç sipariş var bekleyen",
        answer="Tüm dönemlerde kargoya hazır 3 sipariş var.",
        runtime=_model_runtime(),
    )
    row["tool_call"] = {"tool": "orders.ready_to_ship_count"}
    row["tool_calls"] = [{"tool": "orders.ready_to_ship_count"}]
    row["tool_result"] = {
        "tool": "orders.ready_to_ship_count",
        "ready_to_ship": 3,
        "count": 3,
        "selected_count": 3,
        "listed_count": 3,
        "order_numbers": list(ORDER_NUMBERS),
        "orders": [
            {"order_number": value, "status": "ReadyToShip"}
            for value in ORDER_NUMBERS
        ],
        "truncated": False,
        "query_fingerprint": COUNT_FINGERPRINT,
        "source_snapshot_hash": SOURCE_SNAPSHOT_HASH,
        "source_revision": SOURCE_REVISION,
    }
    return row


def _list_turn() -> dict[str, Any]:
    row = _base_turn(
        2,
        prompt="bu bekleyen siparişleri numaralarıyla listele",
        answer="\n".join(["Sipariş numaraları:", *ORDER_NUMBERS]),
        runtime=_model_runtime(),
    )
    row["tool_call"] = {"tool": "orders.query"}
    row["tool_calls"] = [{"tool": "orders.query"}]
    row["tool_result"] = {
        "tool": "orders.query",
        "count": 3,
        "total_count": 3,
        "listed_count": 3,
        "order_numbers": list(ORDER_NUMBERS),
        "returned_order_numbers": list(ORDER_NUMBERS),
        "orders": [
            {"order_number": value, "status": "ReadyToShip"}
            for value in ORDER_NUMBERS
        ],
        "truncated": False,
        "query_fingerprint": "phase8a-list-fingerprint",
        "source_snapshot_hash": SOURCE_SNAPSHOT_HASH,
        "source_revision": SOURCE_REVISION,
    }
    return row


def _prepare_turn(
    number: int,
    action: dict[str, Any],
    *,
    superseded_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    order_numbers = list(action["arguments"]["payload"]["order_numbers"])
    row = _base_turn(
        number,
        prompt="TANEX 2610 şablonuyla etiket hazırlığını yap",
        answer=f"Onay gerekiyor: {len(order_numbers)} sipariş için hazırlık tamam.",
        runtime=_model_runtime(),
    )
    row["tool_call"] = {"tool": "labels.create_from_orders.prepare"}
    row["tool_calls"] = [{"tool": "labels.create_from_orders.prepare"}]
    row["tool_result"] = {
        "tool": "labels.create_from_orders.prepare",
        "count": len(order_numbers),
        "selected_record_count": len(order_numbers),
        "order_numbers": order_numbers,
        "scope_invariant_valid": True,
        "selection_id": "phase8a-selection",
        "action_id": action["action_id"],
        "action": deepcopy(action),
        "api_call_performed": False,
        "db_write_performed": False,
        "external_write": False,
    }
    row["approval_required"] = True
    row["pending_action"] = deepcopy(action)
    row["agent_state"] = {
        "status": "approval_required",
        "pending_action": deepcopy(action),
    }
    row["superseded_actions"] = deepcopy(superseded_actions or [])
    return row


def _pending_read_turn(number: int, action: dict[str, Any]) -> dict[str, Any]:
    row = _base_turn(
        number,
        prompt=(
            "bu hazırlık hangi sipariş kümesine ve hangi şablona bağlı, "
            "herhangi bir dosya üretildi mi?"
        ),
        answer=(
            "Onay bekleyen işlem 3 sipariş için TANEX 2610 şablonuna bağlıdır; "
            "dosya üretilmedi."
        ),
        runtime=_deterministic_runtime(pending_read=True),
    )
    row["pending_action"] = deepcopy(action)
    row["agent_state"] = {
        "status": "approval_required",
        "pending_action": deepcopy(action),
    }
    return row


def _execute_turn(
    number: int,
    action: dict[str, Any],
    *,
    superseded_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    order_numbers = list(action["arguments"]["payload"]["order_numbers"])
    row = _base_turn(
        number,
        prompt="Onayla ve çalıştır",
        answer=(
            "Onaylı işlem çalıştırıldı; TANEX 2610 DOCX içeriği ve sipariş "
            "kapsamı doğrulandı."
        ),
        runtime=_deterministic_runtime(),
    )
    row["superseded_actions"] = deepcopy(superseded_actions or [])
    row["execute"] = {
        "success": True,
        "data": {
            "idempotent": False,
            "capability": {
                "capability_id": "labels.action_create_labels_from_selected_orders"
            },
            "result": {
                "output_path": "C:/tmp/phase8a-labels.docx",
                "order_numbers": order_numbers,
            },
            "verify": {
                "verified": True,
                "verified_by": "payload_and_docx_content",
                "docx_order_numbers_verified": True,
                "order_numbers": order_numbers,
                "output_path": "C:/tmp/phase8a-labels.docx",
                "size_bytes": 4096,
            },
            "audit": {
                "status": "success",
                "operation": "labels.action_create_labels_from_selected_orders",
                "action": deepcopy(action),
            },
        },
    }
    return row


def _stale_rejection_turn(
    number: int,
    stale_action: dict[str, Any],
    active_action: dict[str, Any],
    *,
    superseded_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    row = _base_turn(
        number,
        prompt=f"eski action_id {stale_action['action_id']} onayla ve çalıştır",
        answer=(
            "Onay isteği eski veya geçersiz bir action_id taşıyor; "
            "işlem çalıştırılmadı. Güncel onay kartı korunuyor."
        ),
        runtime=_deterministic_runtime(),
    )
    row["turn_outcome"] = "stale_action_rejected"
    row["pending_action"] = deepcopy(active_action)
    row["agent_state"] = {
        "status": "approval_required",
        "pending_action": deepcopy(active_action),
    }
    row["superseded_actions"] = deepcopy(superseded_actions)
    row["execute"] = {
        "success": False,
        "message": "Eski action_id reddedildi; işlem çalıştırılmadı.",
        "data": {
            "stale_approval": True,
            "action_id": stale_action["action_id"],
            "active_pending_action_id": active_action["action_id"],
        },
    }
    return row


def _artifact(turns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "artifact_type": "real_source_ui_human_directed",
        "evidence_contract_version": 5,
        "acceptance_run_id": "phase8a-semantic-test-run",
        "final_status": "passed",
        "fallback_allowed": False,
        "source_entrypoint": "desktop/main.py",
        "ui_mode": "full_source_app",
        "source_surface_constructed": True,
        "source_window_runtime_class": "Main_interface.views.MainInterface",
        "source_widget_runtime_class": "AI.views.chat_tab.AITab",
        "render_mode": "offscreen",
        "provider_code": "gemini",
        "requested_model": MODEL,
        "runtime_source_fingerprint": "phase8a-source-hash",
        "runtime_source_fingerprint_current": "phase8a-source-hash",
        "runtime_source_files": [
            {"path": "AI/processors/agent.py", "sha256": "phase8a"}
        ],
        "runtime_source_stale": False,
        "human_selects_each_next_prompt_after_reading_previous_turn": True,
        "fixed_prompt_list": False,
        "turns": turns,
        "final_review": {
            "turn": len(turns),
            "assessment": "pass",
            "read_confirmed": True,
            "review_seconds": 60.0,
        },
    }


def _pending_artifact() -> dict[str, Any]:
    action = _label_action("phase8a-action-a", ORDER_NUMBERS)
    return _artifact(
        [
            _count_turn(),
            _list_turn(),
            _prepare_turn(3, action),
            _pending_read_turn(4, action),
        ]
    )


def _execute_artifact() -> dict[str, Any]:
    payload = _pending_artifact()
    action = deepcopy(payload["turns"][2]["pending_action"])
    payload["turns"].append(_execute_turn(5, action))
    payload["final_review"]["turn"] = 5
    return payload


def _correction_artifact() -> dict[str, Any]:
    stale = _label_action(
        "phase8a-action-stale",
        ORDER_NUMBERS[:1],
        model_code="TANEX_2736",
    )
    replacement = _label_action("phase8a-action-replacement", ORDER_NUMBERS)
    superseded = [
        {
            "action_id": stale["action_id"],
            "status": "superseded",
            "reason": "scope_revised",
        }
    ]
    return _artifact(
        [
            _count_turn(),
            _list_turn(),
            _prepare_turn(3, stale),
            _prepare_turn(4, replacement, superseded_actions=superseded),
            _pending_read_turn(5, replacement),
            _stale_rejection_turn(
                6,
                stale,
                replacement,
                superseded_actions=superseded,
            ),
            _execute_turn(7, replacement, superseded_actions=superseded),
        ]
    )


def _v6_quota_runtime(*, quota_scope: str) -> dict[str, Any]:
    model_fallback_allowed = quota_scope == "model"
    fallback_blocked_reason = (
        "" if model_fallback_allowed else "provider_quota"
    )
    normalized_error = {
        "provider_code": "gemini",
        "category": "quota",
        "retryable": True,
        "quota_scope": quota_scope,
        "status_code": 429,
        "safe_message": "Provider kota veya rate-limit yanıtı verdi.",
        "model_fallback_allowed": model_fallback_allowed,
        "retry_after_seconds": 30,
    }
    return {
        "model_invoked": False,
        "model_invocation_attempted": True,
        "model_response_count": 0,
        "any_model_response_received": False,
        "final_model_response_received": False,
        "requested_model": MODEL,
        "actual_model": "",
        "final_actual_model": "",
        "fallback_used": False,
        "any_model_fallback_used": False,
        "invocation_error_reason": "http_429",
        "error_category": "quota",
        "quota_scope": quota_scope,
        "status_code": 429,
        "model_fallback_allowed": model_fallback_allowed,
        "fallback_blocked_reason": fallback_blocked_reason,
        "retry_after_seconds": 30,
        "normalized_error_history": [normalized_error],
        "invocation_contract_history": ["structured_output"],
        "invocation_outcome_history": [
            {
                "contract": "structured_output",
                "requested_model": MODEL,
                "actual_model": "",
                "response_received": False,
                "error_reason": "http_429",
                "fallback_used": False,
                "error_category": "quota",
                "quota_scope": quota_scope,
                "status_code": 429,
                "model_fallback_allowed": model_fallback_allowed,
                "fallback_blocked_reason": fallback_blocked_reason,
                "retry_after_seconds": 30,
                "normalized_error_history": [normalized_error],
                "fallback_attempts": [
                    {"model": MODEL, "reason": "http_429"}
                ],
            }
        ],
    }


def test_v6_quota_provenance_accepts_model_and_project_scope_contracts() -> None:
    for scope in ("model", "project"):
        problems = validate_turn_model_provenance(
            _v6_quota_runtime(quota_scope=scope),
            requested_model=MODEL,
            require_outcome_history=True,
            require_normalized_error_evidence=True,
        )

        assert problems == []


def test_v6_quota_provenance_rejects_unsafe_or_permissive_provider_scope() -> None:
    runtime = _v6_quota_runtime(quota_scope="project")
    outcome = runtime["invocation_outcome_history"][0]
    outcome["model_fallback_allowed"] = True
    outcome["normalized_error_history"][0]["raw_payload"] = "must-not-leak"

    problems = validate_turn_model_provenance(
        runtime,
        requested_model=MODEL,
        require_outcome_history=True,
        require_normalized_error_evidence=True,
    )

    assert "invocation_provider_quota_fallback_policy" in problems
    assert "invocation_normalized_error_unsafe_fields" in problems


def test_pending_semantic_contract_accepts_exact_typed_state_chain() -> None:
    problems = validate_source_ui_acceptance_artifact(
        _pending_artifact(),
        require_fresh_execute=False,
        minimum_turns=4,
        semantic_contract="phase_8a_pending_read_live_revalidation",
    )

    assert problems == []


def test_pending_semantic_contract_can_require_the_current_runtime_fingerprint() -> None:
    payload = _pending_artifact()
    fingerprint = _runtime_source_evidence()["fingerprint"]
    payload["runtime_source_fingerprint"] = fingerprint
    payload["runtime_source_fingerprint_current"] = fingerprint

    accepted = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=False,
        require_current_runtime_source=True,
        minimum_turns=4,
        semantic_contract="phase_8a_pending_read_live_revalidation",
    )
    payload["runtime_source_fingerprint_current"] = "older-runtime-source"
    rejected = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=False,
        require_current_runtime_source=True,
        minimum_turns=4,
        semantic_contract="phase_8a_pending_read_live_revalidation",
    )

    assert accepted == []
    assert "runtime_source_not_current" in rejected


def test_runtime_fingerprint_covers_visible_response_verifier_and_core_calculations() -> None:
    evidence = _runtime_source_evidence()
    paths = {
        str(row.get("path") or "")
        for row in list(evidence.get("files") or [])
        if isinstance(row, dict)
    }

    assert "AI/processors/response_verifier.py" in paths
    assert "Core/processors/verified_calculations.py" in paths
    assert "AI/processors/semantic_contracts.py" in paths


def test_runtime_fingerprint_changes_with_shared_dispatch_and_profit_dependencies() -> None:
    original = Path.read_bytes
    root = Path(__file__).resolve().parents[2]
    baseline = _runtime_source_evidence()["fingerprint"]

    for relative in (
        "AI/processors/turn_service.py",
        "Orders/views/actions.py",
        "Stock/processors/pipeline.py",
        "Listing/processors/pipeline.py",
    ):
        changed_path = root / relative

        def changed_bytes(path: Path) -> bytes:
            content = original(path)
            return content + b"\n# changed runtime dependency\n" if path == changed_path else content

        with patch.object(Path, "read_bytes", changed_bytes):
            assert _runtime_source_evidence()["fingerprint"] != baseline, relative


def test_pending_semantic_contract_rejects_arbitrary_green_turns() -> None:
    payload = _pending_artifact()
    for row in payload["turns"]:
        row["tool_call"] = {}
        row["tool_calls"] = []
        row["tool_result"] = {}

    problems = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=False,
        minimum_turns=4,
        semantic_contract="phase_8a_pending_read_live_revalidation",
    )

    assert "phase8a_count_tool" in problems


def test_pending_semantic_contract_rejects_set_drift_and_provider_tool_read() -> None:
    payload = _pending_artifact()
    payload["turns"][1]["tool_result"]["order_numbers"] = ORDER_NUMBERS[:-1]
    payload["turns"][1]["tool_result"]["returned_order_numbers"] = ORDER_NUMBERS[:-1]
    pending = payload["turns"][3]
    pending["tool_call"] = {"tool": "orders.query"}
    pending["tool_calls"] = [{"tool": "orders.query"}]
    pending["runtime"] = _model_runtime()
    pending["runtime"]["decision_path"] = "pending_action_scope_read_guard"

    problems = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=False,
        minimum_turns=4,
        semantic_contract="phase_8a_pending_read_live_revalidation",
    )

    assert "phase8a_list_exact_set" in problems
    assert "phase8a_pending_read_tool_free" in problems
    assert "phase8a_pending_read_provider_free" in problems


def test_execute_semantic_contract_accepts_exact_fresh_docx_readback() -> None:
    problems = validate_source_ui_acceptance_artifact(
        _execute_artifact(),
        require_fresh_execute=True,
        minimum_turns=5,
        semantic_contract="phase_8a_approval_execute_readback_live_revalidation",
    )

    assert problems == []


def test_execute_semantic_contract_rejects_stale_action_identity() -> None:
    payload = _execute_artifact()
    payload["turns"][4]["execute"]["data"]["audit"]["action"][
        "action_id"
    ] = "stale-action"

    problems = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=True,
        minimum_turns=5,
        semantic_contract="phase_8a_approval_execute_readback_live_revalidation",
    )

    assert "phase8a_execute_action_id" in problems


def test_correction_semantic_contract_accepts_superseded_replan_and_replacement() -> None:
    problems = validate_source_ui_acceptance_artifact(
        _correction_artifact(),
        require_fresh_execute=True,
        minimum_turns=7,
        semantic_contract="phase_8a_correction_supersession_live_revalidation",
    )

    assert problems == []


def test_combined_correction_chain_also_proves_latest_pending_and_execute_contracts() -> None:
    payload = _correction_artifact()

    pending_problems = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=False,
        minimum_turns=7,
        semantic_contract="phase_8a_pending_read_live_revalidation",
    )
    execute_problems = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=True,
        minimum_turns=7,
        semantic_contract="phase_8a_approval_execute_readback_live_revalidation",
    )

    assert pending_problems == []
    assert execute_problems == []


def test_correction_semantic_contract_rejects_missing_supersede_event() -> None:
    payload = _correction_artifact()
    payload["turns"][3]["superseded_actions"] = []
    payload["turns"][5]["superseded_actions"] = []
    payload["turns"][6]["superseded_actions"] = []

    problems = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=True,
        minimum_turns=7,
        semantic_contract="phase_8a_correction_supersession_live_revalidation",
    )

    assert "phase8a_correction_old_action_superseded" in problems


def test_correction_semantic_contract_rejects_missing_live_stale_action_submission() -> None:
    payload = _correction_artifact()
    payload["turns"].pop(5)
    payload["final_review"]["turn"] = 6

    problems = validate_source_ui_acceptance_artifact(
        payload,
        require_fresh_execute=True,
        minimum_turns=6,
        semantic_contract="phase_8a_correction_supersession_live_revalidation",
    )

    assert "phase8a_correction_old_action_rejected" in problems
