from __future__ import annotations

from copy import deepcopy
from typing import Any

from AI.processors.orders_source_ui_human_recheck_cli import (
    _validate_phase8b_orders_organic_semantics,
)


MODEL = "gemini-3.1-flash-lite"


def _runtime(*, invoked: bool = True) -> dict[str, Any]:
    return {
        "model_invoked": invoked,
        "model_invocation_attempted": invoked,
        "accepted_semantic_output": invoked,
        "requested_model": MODEL if invoked else "",
        "actual_model": MODEL if invoked else "",
        "fallback_used": False,
        "any_model_fallback_used": False,
        "final_response_source": (
            "verified_model_candidate" if invoked else "typed_pending_state_projection"
        ),
    }


def _turn(
    phase: str,
    *,
    tools: list[str] | None = None,
    result: dict[str, Any] | None = None,
    answer: str = "Doğrulanmış görünür cevap.",
    invoked: bool = True,
    approval_required: bool = False,
    pending_action: dict[str, Any] | None = None,
    execute: dict[str, Any] | None = None,
) -> dict[str, Any]:
    names = list(tools or [])
    row: dict[str, Any] = {
        "selection_reason": f"phase8b:{phase}|adaptive test phase",
        "answer": answer,
        "success": True,
        "tool_call": {"tool": names[0]} if names else {},
        "tool_calls": [{"tool": name} for name in names],
        "tool_result": dict(result or {}),
        "runtime": _runtime(invoked=invoked),
        "approval_required": approval_required,
        "pending_action": dict(pending_action or {}),
        "execute": dict(execute or {"success": None, "data": {}}),
    }
    if phase == "orders_capabilities":
        row["runtime"]["decision_path"] = "typed_capability_catalog_grounded"
    return row


def _valid_turns() -> list[dict[str, Any]]:
    sales_snapshot = {
        "snapshot_id": "rpt-phase8b-sales",
        "content_hash": "sales-content-hash",
        "source_domain": "orders",
        "report_type": "orders.item_sales",
    }
    sales_action = {
        "action_id": "action-phase8b-xlsx",
        "status": "pending_approval",
        "action_type": "orders.action_export_report_snapshot_xlsx",
        "arguments": {
            "payload": {
                "report_snapshot": sales_snapshot,
                "output_path": "phase8b-sales.xlsx",
            }
        },
    }
    identity_result = {
        "public_product_identities": [
            {"product_name": "Public Product", "barcode": "8691234567891"}
        ]
    }
    identity_state = {
        "completed_steps": [
            {
                "tool_names": ["orders.product_public_identities"],
                "result_data": {"tool_result": identity_result},
            }
        ]
    }
    return [
        _turn("greeting", answer="İyiyim başkan, buradayım."),
        _turn("emotional_chat", answer="Canının sıkkın olmasına üzüldüm; dinliyorum."),
        _turn(
            "orders_capabilities",
            tools=["operations.capability_catalog"],
            answer=(
                "Sipariş durum ve ciro özetlerini, kargo risklerini, iade claim'lerini, "
                "etiketleri, rapor ve Excel çıktılarını ve public ürün için web araştırmasını "
                "yönetebilirim; etkili işleri açık onay olmadan execute etmem."
            ),
        ),
        _turn(
            "orders_summary",
            tools=[
                "orders.status_counts",
                "orders.ready_to_ship_count",
                "orders.revenue_total",
            ],
            result={
                "state": {
                    "completed_steps": [
                        {
                            "tool_names": ["orders.status_counts"],
                            "result_data": {
                                "tool_result": {
                                    "status_counts": {
                                        "Delivered": 8,
                                        "Cancelled": 2,
                                    }
                                }
                            },
                        },
                        {
                            "tool_names": ["orders.ready_to_ship_count"],
                            "result_data": {
                                "tool_result": {"ready_to_ship": 3}
                            },
                        },
                        {
                            "tool_names": ["orders.revenue_total"],
                            "result_data": {
                                "tool_result": {"total_revenue": 1250.0}
                            },
                        },
                    ]
                }
            },
        ),
        _turn(
            "recent_orders",
            tools=["orders.recent"],
            result={"order_numbers": ["ORD-1", "ORD-2"]},
        ),
        _turn(
            "order_detail",
            tools=["orders.full_context"],
            result={"order_numbers": ["ORD-1"]},
        ),
        _turn(
            "long_context_return",
            tools=["orders.full_context"],
            result={"order_numbers": ["ORD-1"]},
        ),
        _turn(
            "ready_count",
            tools=["orders.ready_to_ship_count"],
            result={"ready_to_ship": 2},
        ),
        _turn(
            "ready_list",
            tools=["orders.ready_to_ship"],
            result={"order_numbers": ["ORD-1", "ORD-2"]},
        ),
        _turn("fulfillment_risk", tools=["orders.fulfillment_risk"]),
        _turn(
            "cargo_prepare",
            tools=["orders.change_cargo_provider_bulk.prepare"],
            approval_required=True,
            pending_action={
                "action_id": "action-cargo",
                "action_type": "orders.change_orders_cargo_provider_bulk",
                "status": "pending_approval",
            },
        ),
        _turn("cargo_cancel", invoked=False, answer="İşlem iptal edildi; hiçbir istek gönderilmedi."),
        _turn(
            "item_sales_list",
            tools=["orders.item_sales_report"],
            result={
                "snapshot_id": sales_snapshot["snapshot_id"],
                "report_snapshot": sales_snapshot,
            },
        ),
        _turn(
            "item_sales_excel_prepare",
            tools=["orders.item_sales_report_xlsx.prepare"],
            approval_required=True,
            pending_action=sales_action,
        ),
        _turn(
            "item_sales_excel_pending",
            invoked=False,
            answer="Onay bekliyor; henüz dosya üretilmedi.",
            pending_action=sales_action,
        ),
        _turn(
            "item_sales_excel_execute",
            invoked=False,
            execute={
                "success": True,
                "data": {
                    "capability": {
                        "capability_id": "orders.action_export_report_snapshot_xlsx"
                    },
                    "verify": {
                        "verified": True,
                        "verified_by": "xlsx_exact_snapshot_readback",
                        "snapshot_id": sales_snapshot["snapshot_id"],
                        "output_path": "phase8b-sales.xlsx",
                    },
                },
            },
        ),
        _turn(
            "public_product_identity",
            tools=["orders.product_public_identities"],
            result={"state": identity_state},
        ),
        _turn(
            "public_web_research",
            tools=["web.search", "web.open", "web.compare_sources"],
            answer="Açılan iki kaynağa göre bulgular doğrulandı: https://example.com/a",
        ),
        _turn(
            "private_orders_web_boundary",
            answer="Özel sipariş numarası ve kişisel veriyi web'e göndermem; yalnız public ürün bilgisiyle araştırma yapabilirim.",
        ),
        _turn("cancellations", tools=["orders.cancellations"]),
        _turn("waiting_returns", tools=["returns.waiting.list"]),
        _turn("closing_chat", answer="Siparişleri inceledik, riskleri gördük ve doğrulanmış Excel hazırladık."),
    ]


def test_phase8b_organic_contract_accepts_composed_orders_web_xlsx_chain() -> None:
    assert _validate_phase8b_orders_organic_semantics(_valid_turns()) == []


def test_phase8b_organic_contract_accepts_canonical_orders_query_for_recent_list() -> None:
    turns = deepcopy(_valid_turns())
    recent_turn = next(
        row
        for row in turns
        if str(row.get("selection_reason") or "").startswith(
            "phase8b:recent_orders"
        )
    )
    recent_turn["tool_call"] = {"tool": "orders.query"}
    recent_turn["tool_calls"] = [{"tool": "orders.query"}]

    assert _validate_phase8b_orders_organic_semantics(turns) == []


def test_phase8b_summary_accepts_multi_metric_canonical_result_not_tool_name_count() -> None:
    turns = deepcopy(_valid_turns())
    summary_turn = next(
        row
        for row in turns
        if str(row.get("selection_reason") or "").startswith(
            "phase8b:orders_summary"
        )
    )
    summary_turn["tool_call"] = {"tool": "orders.count"}
    summary_turn["tool_calls"] = [
        {"tool": "orders.count"},
        {"tool": "orders.summary"},
        {"tool": "orders.item_sales_summary"},
    ]
    summary_turn["tool_result"] = {
        "state": {
            "completed_steps": [
                {
                    "tool_names": ["orders.count"],
                    "result_data": {"tool_result": {"count": 3112}},
                },
                {
                    "tool_names": ["orders.summary"],
                    "result_data": {
                        "tool_result": {
                            "total_orders": 3112,
                            "status_counts": {
                                "Delivered": 2950,
                                "Cancelled": 110,
                                "Shipped": 7,
                                "UnDelivered": 1,
                                "UnDeliveredAndReturned": 44,
                            },
                            "estimated_revenue": 502518.01,
                        }
                    },
                },
                {
                    "tool_names": ["orders.item_sales_summary"],
                    "result_data": {
                        "tool_result": {
                            "rows": [{"product_name": "Public Product"}],
                            "product_count": 1,
                        }
                    },
                },
            ]
        }
    }

    assert _validate_phase8b_orders_organic_semantics(turns) == []


def test_phase8b_summary_rejects_multiple_tool_names_without_metric_evidence() -> None:
    turns = deepcopy(_valid_turns())
    summary_turn = next(
        row
        for row in turns
        if str(row.get("selection_reason") or "").startswith(
            "phase8b:orders_summary"
        )
    )
    summary_turn["tool_result"] = {
        "state": {
            "completed_steps": [
                {
                    "tool_names": ["orders.count"],
                    "result_data": {"tool_result": {}},
                },
                {
                    "tool_names": ["orders.revenue_total"],
                    "result_data": {"tool_result": {}},
                },
            ]
        }
    }

    problems = _validate_phase8b_orders_organic_semantics(turns)

    assert "phase8b_orders_summary_multi_signal" in problems


def test_phase8b_organic_contract_rejects_private_order_web_egress() -> None:
    turns = deepcopy(_valid_turns())
    private_turn = next(
        row
        for row in turns
        if str(row.get("selection_reason") or "").startswith(
            "phase8b:private_orders_web_boundary"
        )
    )
    private_turn["tool_call"] = {"tool": "web.search"}
    private_turn["tool_calls"] = [{"tool": "web.search"}]

    problems = _validate_phase8b_orders_organic_semantics(turns)

    assert "phase8b_private_orders_web_fail_closed" in problems


def test_phase8b_organic_contract_rejects_xlsx_snapshot_drift() -> None:
    turns = deepcopy(_valid_turns())
    execute_turn = next(
        row
        for row in turns
        if str(row.get("selection_reason") or "").startswith(
            "phase8b:item_sales_excel_execute"
        )
    )
    execute_turn["execute"]["data"]["verify"]["snapshot_id"] = "wrong-snapshot"

    problems = _validate_phase8b_orders_organic_semantics(turns)

    assert "phase8b_item_sales_xlsx_execute_readback" in problems
