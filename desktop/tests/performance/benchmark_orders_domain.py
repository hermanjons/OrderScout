from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


DESKTOP_ROOT = Path(__file__).resolve().parents[2]
if str(DESKTOP_ROOT) not in sys.path:
    sys.path.insert(0, str(DESKTOP_ROOT))


def _summary(values: list[float], *, size: int | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "runs": [round(value, 6) for value in values],
        "median": round(float(statistics.median(values)), 6) if values else 0.0,
        "mean": round(float(statistics.mean(values)), 6) if values else 0.0,
        "min": round(min(values), 6) if values else 0.0,
        "max": round(max(values), 6) if values else 0.0,
    }
    if size is not None:
        payload["size"] = int(size)
    return payload


def _payload_size(result, *keys: str) -> int:
    data = getattr(result, "data", None) or {}
    if not isinstance(data, dict):
        return 0
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _bench_sync(name: str, fn, repeats: int, *, size_keys: tuple[str, ...]) -> tuple[str, dict[str, object], object]:
    values: list[float] = []
    last_result = None
    last_size = 0
    for _ in range(repeats):
        started_at = time.perf_counter()
        last_result = fn()
        values.append(time.perf_counter() - started_at)
        last_size = _payload_size(last_result, *size_keys)
        if hasattr(last_result, "success") and not last_result.success:
            raise RuntimeError(f"{name} failed: {getattr(last_result, 'message', '')}")
    return name, _summary(values, size=last_size), last_result


async def _run_active_return_claim_id_verify_once():
    from Feedback.processors.pipeline import Result
    import Orders.views.actions as orders_actions

    account = SimpleNamespace(pk=1)
    claim = SimpleNamespace(claimId="BENCH-ACTIVE-CLAIM", api_account_id=1)
    calls: list[dict] = []

    async def fake_fetch(_accounts, **kwargs):
        calls.append(dict(kwargs))
        return Result.ok(
            "ok",
            close_dialog=False,
            data={
                "return_claim_list": [
                    {
                        "api_account_id": 1,
                        "claimId": "BENCH-ACTIVE-CLAIM",
                        "claimNumber": "BENCH-ACTIVE-CLAIM",
                        "orderNumber": "BENCH-ORDER",
                        "claimItemStatus": "WaitingInAction",
                        "lastModifiedDate": 1_700_000_000_000,
                    }
                ],
                "errors": [],
            },
        )

    with patch.object(
        orders_actions,
        "get_latest_return_claims_filtered",
        return_value=Result.ok("local", close_dialog=False, data={"claims": [claim]}),
    ), patch.object(
        orders_actions,
        "_fetch_returns_from_active_companies_async",
        side_effect=fake_fetch,
    ), patch.object(
        orders_actions,
        "save_return_claims_to_db",
        return_value=Result.ok(
            "saved",
            close_dialog=False,
            data={"changed": False, "counts": {"claims_inserted": 0, "claims_restored": 0}},
        ),
    ):
        result = await orders_actions._refresh_active_return_claims_from_api_async([account])

    if not result.success:
        raise RuntimeError(result.message)
    return result, len(calls)


def _bench_active_return_claim_id_verify(repeats: int) -> tuple[str, dict[str, object]]:
    values: list[float] = []
    calls = 0
    for _ in range(repeats):
        started_at = time.perf_counter()
        _result, calls = asyncio.run(_run_active_return_claim_id_verify_once())
        values.append(time.perf_counter() - started_at)
    payload = _summary(values, size=calls)
    payload["api_call_count"] = calls
    return "active_return_claim_id_verify_fake", payload


def _bench_qt_page_build(repeats: int, orders: list) -> tuple[str, dict[str, object]]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from Orders.views.orders_manager_window import OrdersListModel

    app = QApplication.instance() or QApplication([])
    page_orders = list(orders[:20])
    values: list[float] = []
    for _ in range(repeats):
        model = OrdersListModel([])
        started_at = time.perf_counter()
        model.set_orders(page_orders)
        app.processEvents()
        values.append(time.perf_counter() - started_at)
    return "orders_qt_model_set_page_20", _summary(values, size=len(page_orders))


def run(repeats: int) -> dict[str, object]:
    from Orders.processors.trendyol.pipeline import (
        RETURN_ACTIVE_STATUS_CODES,
        filter_order_records_in_memory,
        get_latest_orders,
        get_latest_ready_to_ship_orders,
        get_latest_return_claims,
        get_nonfinal_order_numbers,
    )
    import Orders.views.actions as orders_actions

    results: dict[str, object] = {}

    name, payload, latest_orders_result = _bench_sync(
        "db_get_latest_orders_all",
        get_latest_orders,
        repeats,
        size_keys=("orders",),
    )
    results[name] = payload
    orders = (latest_orders_result.data or {}).get("orders", []) or []

    for name, fn, keys in (
        ("db_get_latest_ready_to_ship", get_latest_ready_to_ship_orders, ("orders",)),
        ("db_get_latest_return_claims_all", get_latest_return_claims, ("claims",)),
        (
            "db_get_latest_return_claims_active",
            lambda: get_latest_return_claims(claim_statuses=RETURN_ACTIVE_STATUS_CODES),
            ("claims",),
        ),
        ("db_get_nonfinal_order_numbers", get_nonfinal_order_numbers, ("order_numbers",)),
        ("view_load_ready_to_ship_orders", orders_actions.load_ready_to_ship_orders, ("records",)),
        (
            "view_load_returns_waiting_action",
            lambda: orders_actions.load_returns_for_source_filters(shipment_status_code="WaitingInAction"),
            ("records",),
        ),
    ):
        bench_name, bench_payload, _ = _bench_sync(name, fn, repeats, size_keys=keys)
        results[bench_name] = bench_payload

    for name, filters in (
        ("filter_status_ready_to_ship", {"shipment_status_code": "ReadyToShip", "date_enabled": False}),
        ("filter_global_delivered", {"global": "delivered", "date_enabled": False}),
        ("filter_global_no_match", {"global": "__unlikely_orderscout_match__", "date_enabled": False}),
    ):
        bench_name, bench_payload, _ = _bench_sync(
            name,
            lambda filters=filters: filter_order_records_in_memory(orders, filters),
            repeats,
            size_keys=("filtered",),
        )
        results[bench_name] = bench_payload

    active_name, active_payload = _bench_active_return_claim_id_verify(repeats)
    results[active_name] = active_payload

    try:
        qt_name, qt_payload = _bench_qt_page_build(repeats, orders)
        results[qt_name] = qt_payload
    except Exception as exc:
        results["orders_qt_model_set_page_20"] = {"skipped": str(exc)}

    return {
        "repeats": repeats,
        "benchmarks": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Orders domain hot paths.")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    repeats = max(1, int(args.repeats or 5))
    print(json.dumps(run(repeats), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
