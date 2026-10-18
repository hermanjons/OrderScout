from __future__ import annotations

import subprocess
import sys
import zlib
import random
import os
import shlex
import shutil
import tempfile
import base64
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Callable

from Feedback.processors.pipeline import Result, map_error_to_message
from settings import DB_NAME

from Account.processors.pipeline import get_all_companies
from Core.utils.request_utils import configure_request_chaos, request_chaos_state, reset_request_chaos
from Finance.processors.rule_loader import resolve_finance_rule
from Labels.processors.pipeline import create_order_label_from_orders, export_labels_to_word
from Listing.processors.pipeline import get_listings_from_db, save_listings_to_db
from Logistics.views.actions import load_logistics_cargo_tariffs
from Orders.models.trendyol.models import OrderItem
from Orders.processors.trendyol.pipeline import get_nonfinal_order_numbers, save_orders_to_db
from Stock.processors.pipeline import list_brands, list_item_balances, list_items, list_warehouses, manual_out

from Listing.signals.signals import listing_signals
from Orders.signals.signals import order_signals
from Core.utils.model_utils import get_engine
from sqlmodel import Session, select

BuildProgressCallback = Optional[Callable[[int, str], None]]
BuildLogCallback = Optional[Callable[[str], None]]

ORDER_STATUS_PRESETS: dict[str, tuple[str, str]] = {
    "created": ("Picking", "ReadyToShip"),
    "shipped": ("Shipped", "Shipped"),
    "delivered": ("Delivered", "Delivered"),
    "cancelled": ("Cancelled", "Cancelled"),
}

ORDER_LIFECYCLE_PRESETS: dict[str, tuple[tuple[str, str], ...]] = {
    "single": (ORDER_STATUS_PRESETS["created"],),
    "created": (ORDER_STATUS_PRESETS["created"],),
    "shipped": (ORDER_STATUS_PRESETS["shipped"],),
    "delivered": (ORDER_STATUS_PRESETS["delivered"],),
    "cancelled": (ORDER_STATUS_PRESETS["cancelled"],),
    "created_to_shipped": (
        ORDER_STATUS_PRESETS["created"],
        ORDER_STATUS_PRESETS["shipped"],
    ),
    "created_to_delivered": (
        ORDER_STATUS_PRESETS["created"],
        ORDER_STATUS_PRESETS["shipped"],
        ORDER_STATUS_PRESETS["delivered"],
    ),
    "created_to_cancelled": (
        ORDER_STATUS_PRESETS["created"],
        ORDER_STATUS_PRESETS["cancelled"],
    ),
}


@dataclass(frozen=True)
class _ListingSource:
    product_id: str
    title: str
    stock_code: str
    barcode: str
    base_product_code: int
    unit_price: float


def _resolve_status_pair(
    *,
    preset_key: str | None = None,
    order_status: str | None = None,
    shipment_status: str | None = None,
) -> tuple[str, str]:
    preset = ORDER_STATUS_PRESETS.get(str(preset_key or "").strip().lower())
    if preset is not None:
        return preset
    return (
        str(order_status or "Picking").strip() or "Picking",
        str(shipment_status or "ReadyToShip").strip() or "ReadyToShip",
    )


def _resolve_lifecycle_stages(
    *,
    lifecycle_key: str | None = None,
    order_status: str | None = None,
    shipment_status: str | None = None,
) -> tuple[tuple[str, str], ...]:
    key = str(lifecycle_key or "single").strip().lower() or "single"
    preset = ORDER_LIFECYCLE_PRESETS.get(key)
    if preset is not None:
        return preset
    return (_resolve_status_pair(order_status=order_status, shipment_status=shipment_status),)


def _utc_ms_now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _simulated_line_id(seed: int, line_index: int) -> int:
    try:
        return int(seed) * 100 + int(line_index) + 1
    except Exception:
        return int(line_index) + 1


def _pick_company_pk(explicit_pk: Optional[int], companies: list[dict]) -> Optional[int]:
    if explicit_pk is not None:
        return _safe_int(explicit_pk, 0) or None
    if not companies:
        return None
    return _safe_int(companies[0].get("pk"), 0) or None


def _source_base_code(product_id: str, product_code_raw: Any) -> int:
    code = _safe_int(product_code_raw, 0)
    if code > 0:
        return code
    checksum = zlib.crc32(str(product_id).encode("utf-8"))
    return int(checksum % 900_000) + 100_000


def _normalize_listing_sources(listing_items: Iterable[dict]) -> list[_ListingSource]:
    sources: list[_ListingSource] = []
    seen: set[str] = set()

    for it in listing_items or []:
        if not isinstance(it, dict):
            continue

        product_id = str(
            it.get("product_id")
            or it.get("productId")
            or it.get("id")
            or ""
        ).strip()
        if not product_id or product_id in seen:
            continue

        seen.add(product_id)
        title = str(it.get("title") or it.get("name") or product_id).strip()
        stock_code = str(it.get("stock_code") or it.get("stockCode") or product_id).strip()
        barcode = str(it.get("barcode") or "").strip()
        base_product_code = _source_base_code(product_id, it.get("product_code") or it.get("productCode"))
        sale_price = _safe_float(it.get("sale_price") or it.get("salePrice"), 0.0)
        list_price = _safe_float(it.get("list_price") or it.get("listPrice"), 0.0)
        unit_price = sale_price if sale_price > 0 else max(list_price, 0.0)

        sources.append(
            _ListingSource(
                product_id=product_id,
                title=title,
                stock_code=stock_code,
                barcode=barcode,
                base_product_code=base_product_code,
                unit_price=unit_price,
            )
        )

    return sources


def _save_orders_payload(
    *,
    order_data_list: list[dict[str, Any]],
    order_item_list: list[dict[str, Any]],
    db_name: str | None = None,
) -> Result:
    kwargs = {}
    if db_name:
        kwargs["db_name"] = str(db_name)

    return save_orders_to_db(
        Result.ok(
            "Simulated orders",
            close_dialog=False,
            data={
                "order_data_list": order_data_list,
                "order_item_list": order_item_list,
            },
        ),
        **kwargs,
    )


def _emit_orders_persisted_if_new(
    *,
    source: str,
    order_data_list: list[dict[str, Any]],
    order_item_list: list[dict[str, Any]],
    db_result: dict[str, Any],
) -> None:
    try:
        counts = (db_result or {}).get("counts") or {}
        inserted_items = int(counts.get("items_inserted", 0) or 0)
    except Exception:
        inserted_items = 0

    if inserted_items <= 0:
        return

    payload = {
        "source": str(source or "").strip() or "testing",
        "order_item_list": order_item_list or [],
        "order_data_list": order_data_list or [],
        "db_result": db_result or {},
    }
    try:
        order_signals.orders_persisted.emit(payload)
    except Exception:
        pass


def list_companies_for_testing() -> Result:
    try:
        res = get_all_companies()
        if not res.success:
            return res

        records = (res.data or {}).get("records", []) or []
        companies = []
        for r in records:
            pk = getattr(r, "pk", None)
            if pk is None:
                continue
            companies.append(
                {
                    "pk": int(pk),
                    "comp_name": str(getattr(r, "comp_name", "") or ""),
                    "platform": str(getattr(r, "platform", "") or ""),
                    "account_id": str(getattr(r, "account_id", "") or ""),
                    "is_active": bool(getattr(r, "is_active", False)),
                }
            )

        return Result.ok(
            "Test companies loaded.",
            close_dialog=False,
            data={"companies": companies},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def list_company_listings_for_testing(
    *,
    api_account_id: int,
    search: str | None = None,
    limit: int = 300,
    db_name: str | None = None,
) -> Result:
    try:
        kwargs: dict[str, Any] = {
            "api_account_ids": [int(api_account_id)],
            "search": (search or "").strip() or None,
        }
        if db_name:
            kwargs["db_name"] = str(db_name)

        res = get_listings_from_db(**kwargs)
        if not res.success:
            return res

        raw_items = (res.data or {}).get("items", []) or []
        normalized: list[dict[str, Any]] = []

        for it in raw_items:
            product_id = str(it.get("productId") or it.get("product_id") or "").strip()
            if not product_id:
                continue

            sale_price = _safe_float(it.get("salePrice") or it.get("sale_price"), 0.0)
            list_price = _safe_float(it.get("listPrice") or it.get("list_price"), 0.0)
            stock_items = list(it.get("stock_items") or []) if isinstance(it.get("stock_items"), list) else []
            linked_stock_ids: list[int] = []
            for stock_row in stock_items:
                if not isinstance(stock_row, dict):
                    continue
                try:
                    stock_item_id = int(stock_row.get("stock_item_id"))
                except Exception:
                    continue
                if stock_item_id > 0:
                    linked_stock_ids.append(stock_item_id)
            normalized.append(
                {
                    "product_id": product_id,
                    "title": str(it.get("title") or it.get("name") or product_id).strip(),
                    "stock_code": str(it.get("stockCode") or it.get("stock_code") or "").strip(),
                    "barcode": str(it.get("barcode") or "").strip(),
                    "brand": str(it.get("brand") or "").strip(),
                    "quantity": it.get("quantity"),
                    "product_code": it.get("productCode") or it.get("product_code"),
                    "sale_price": sale_price if sale_price > 0 else None,
                    "list_price": list_price if list_price > 0 else None,
                    "stock_linked": bool(linked_stock_ids),
                    "stock_item_ids": linked_stock_ids,
                    "stock_items": stock_items,
                }
            )

        normalized.sort(key=lambda x: ((x.get("title") or "").lower(), x.get("product_id") or ""))

        total = len(normalized)
        limit = max(1, min(int(limit), 2000)) if int(limit) > 0 else 2000
        shown = normalized[:limit]

        return Result.ok(
            f"{len(shown)} listing row ready.",
            close_dialog=False,
            data={"items": shown, "total": total, "shown": len(shown)},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def simulate_order_arrival(
    *,
    api_account_id: int,
    order_count: int = 1,
    lines_per_order: int = 2,
    shipment_status: str = "ReadyToShip",
    order_status: str = "Picking",
    status_preset: str | None = None,
    lifecycle_key: str | None = None,
    prefix: str = "SIM",
    db_name: str | None = None,
) -> Result:
    """
    Simulates incoming orders without external API.
    """
    try:
        if int(order_count) <= 0:
            return Result.fail("order_count must be greater than 0.", close_dialog=False)
        if int(lines_per_order) <= 0:
            return Result.fail("lines_per_order must be greater than 0.", close_dialog=False)

        order_count = min(int(order_count), 300)
        lines_per_order = min(int(lines_per_order), 30)
        api_account_id = int(api_account_id)
        lifecycle_stages = _resolve_lifecycle_stages(
            lifecycle_key=lifecycle_key,
            order_status=order_status,
            shipment_status=shipment_status,
        )
        if status_preset and lifecycle_key in (None, "", "single"):
            lifecycle_stages = (
                _resolve_status_pair(
                    preset_key=status_preset,
                    order_status=order_status,
                    shipment_status=shipment_status,
                ),
            )

        now_ms = _utc_ms_now()
        order_data_list: list[dict[str, Any]] = []
        order_item_list: list[dict[str, Any]] = []
        order_numbers: list[str] = []

        for oidx in range(order_count):
            seed = now_ms + (oidx * 10)
            order_number = f"{prefix}-{api_account_id}-{seed}-{oidx + 1}"
            order_numbers.append(order_number)
            package_histories: list[dict[str, Any]] = []
            for stage_idx, (stage_order_status, stage_shipment_status) in enumerate(lifecycle_stages):
                snapshot_id = int(seed + stage_idx + 1)
                last_modified = int(seed + ((stage_idx + 1) * 100))
                package_histories.append({"status": str(stage_order_status), "createdDate": last_modified})
                order_data_list.append(
                    {
                        "id": snapshot_id,
                        "orderNumber": order_number,
                        "api_account_id": api_account_id,
                        "lastModifiedDate": last_modified,
                        "orderDate": int(seed),
                        "status": str(stage_order_status),
                        "shipmentPackageStatus": str(stage_shipment_status),
                        "cargoTrackingNumber": f"SIMTRK{seed}",
                        "cargoProviderName": "Simulated Cargo",
                        "customerFirstName": "Sim",
                        "customerLastName": "Customer",
                        "totalPrice": float(oidx + 1) * 100.0,
                        "packageHistories": list(package_histories),
                        "shipmentAddress": {
                            "fullAddress": "Simulated Test Address",
                            "city": "Istanbul",
                        },
                    }
                )

                for lidx in range(lines_per_order):
                    line_id = _simulated_line_id(seed, lidx)
                    order_item_list.append(
                        {
                            "orderNumber": order_number,
                            "api_account_id": api_account_id,
                            "order_data_id": snapshot_id,
                            "snapshotLastModifiedDate": last_modified,
                            "lineId": line_id,
                            "id": line_id,
                            "quantity": int((lidx % 3) + 1),
                            "productName": f"Sim Product {lidx + 1}",
                            "merchantSku": f"SIM-SKU-{oidx + 1}-{lidx + 1}",
                            "sku": f"SIMSKU{oidx + 1}{lidx + 1}",
                            "barcode": f"869{(seed + lidx) % 1000000000:09d}",
                            "productCode": int((seed % 900_000) * 100 + lidx + 1),
                            "orderLineItemStatusName": str(stage_order_status),
                            "shipmentPackageStatus": str(stage_shipment_status),
                            "status": str(stage_shipment_status),
                            "taskDate": last_modified,
                        }
                    )

        save_res = _save_orders_payload(
            order_data_list=order_data_list,
            order_item_list=order_item_list,
            db_name=db_name,
        )
        if not save_res.success:
            return save_res

        _emit_orders_persisted_if_new(
            source="testing.quick_order_sim",
            order_data_list=order_data_list,
            order_item_list=order_item_list,
            db_result=save_res.data or {},
        )

        if bool((save_res.data or {}).get("changed")):
            try:
                order_signals.orders_changed.emit()
            except Exception:
                pass

        return Result.ok(
            f"{len(order_numbers)} simulated orders processed.",
            close_dialog=False,
            data={
                "order_numbers": order_numbers,
                "snapshot_count": len(order_data_list),
                "save": save_res.data or {},
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def simulate_order_arrival_from_listings(
    *,
    api_account_id: int,
    listing_items: list[dict],
    order_count: int = 1,
    shipment_status: str = "ReadyToShip",
    order_status: str = "Picking",
    status_preset: str | None = None,
    lifecycle_key: str | None = None,
    prefix: str = "SIM-LST",
    db_name: str | None = None,
) -> Result:
    """
    Simulates order arrivals by using selected listing products as sources.
    """
    try:
        if int(order_count) <= 0:
            return Result.fail("order_count must be greater than 0.", close_dialog=False)

        sources = _normalize_listing_sources(listing_items)
        if not sources:
            return Result.fail("No valid listing sources selected.", close_dialog=False)

        order_count = min(int(order_count), 300)
        api_account_id = int(api_account_id)
        lifecycle_stages = _resolve_lifecycle_stages(
            lifecycle_key=lifecycle_key,
            order_status=order_status,
            shipment_status=shipment_status,
        )
        if status_preset:
            lifecycle_stages = _resolve_lifecycle_stages(lifecycle_key=lifecycle_key or "single")
            if lifecycle_key in (None, "", "single"):
                lifecycle_stages = (
                    _resolve_status_pair(
                        preset_key=status_preset,
                        order_status=order_status,
                        shipment_status=shipment_status,
                    ),
                )

        now_ms = _utc_ms_now()
        rng = random.Random(now_ms + api_account_id)
        order_data_list: list[dict[str, Any]] = []
        order_item_list: list[dict[str, Any]] = []
        order_numbers: list[str] = []

        for oidx in range(order_count):
            base_seed = now_ms + (oidx * 1_000)
            order_number = f"{prefix}-{api_account_id}-{base_seed}-{oidx + 1}"
            order_numbers.append(order_number)

            if order_count == 1 and len(sources) > 1:
                picked_sources = list(sources)
            elif len(sources) == 1:
                picked_sources = [sources[0]]
            else:
                picked_count = rng.randint(1, len(sources))
                picked_sources = rng.sample(sources, picked_count)

            prepared_lines: list[dict[str, Any]] = []
            order_total = 0.0
            for lidx, src in enumerate(picked_sources):
                qty = int(rng.randint(1, 3))
                unit_price = float(src.unit_price or 0.0)
                amount = round(unit_price * qty, 4) if unit_price > 0 else 0.0
                order_total += amount
                prepared_lines.append(
                    {
                        "source": src,
                        "qty": qty,
                        "unit_price": unit_price,
                        "amount": amount,
                        "line_id": _simulated_line_id(base_seed, lidx),
                        "product_code": int(src.base_product_code * 100 + (lidx + 1)),
                    }
                )

            package_histories: list[dict[str, Any]] = []
            for stage_idx, (stage_order_status, stage_shipment_status) in enumerate(lifecycle_stages):
                snapshot_id = int(base_seed + stage_idx + 1)
                last_modified = int(base_seed + ((stage_idx + 1) * 100))
                package_histories.append(
                    {
                        "status": str(stage_order_status),
                        "createdDate": last_modified,
                    }
                )
                order_data_list.append(
                    {
                        "id": snapshot_id,
                        "orderNumber": order_number,
                        "api_account_id": api_account_id,
                        "lastModifiedDate": last_modified,
                        "orderDate": int(base_seed),
                        "status": str(stage_order_status),
                        "shipmentPackageStatus": str(stage_shipment_status),
                        "cargoTrackingNumber": f"SIMLST{base_seed}",
                        "cargoProviderName": "Simulated Listing Cargo",
                        "customerFirstName": "Listing",
                        "customerLastName": "Customer",
                        "totalPrice": round(order_total, 4),
                        "packageHistories": list(package_histories),
                        "shipmentAddress": {
                            "fullAddress": "Listing Driven Test Address",
                            "city": "Istanbul",
                        },
                    }
                )

                for line in prepared_lines:
                    src = line["source"]
                    item_payload = {
                        "orderNumber": order_number,
                        "api_account_id": api_account_id,
                        "order_data_id": snapshot_id,
                        "snapshotLastModifiedDate": last_modified,
                        "lineId": int(line["line_id"]),
                        "id": int(line["line_id"]),
                        "quantity": int(line["qty"]),
                        "productName": src.title,
                        "merchantSku": src.stock_code or src.product_id,
                        "sku": src.stock_code or src.product_id,
                        "barcode": src.barcode or f"869{(base_seed + int(line['line_id'])) % 1000000000:09d}",
                        "productCode": int(line["product_code"]),
                        "orderLineItemStatusName": str(stage_order_status),
                        "shipmentPackageStatus": str(stage_shipment_status),
                        "status": str(stage_shipment_status),
                        "taskDate": last_modified,
                    }
                    if float(line["unit_price"] or 0.0) > 0:
                        item_payload["price"] = round(float(line["unit_price"]), 4)
                        item_payload["amount"] = float(line["amount"])
                    order_item_list.append(item_payload)

        save_res = _save_orders_payload(
            order_data_list=order_data_list,
            order_item_list=order_item_list,
            db_name=db_name,
        )
        if not save_res.success:
            return save_res

        _emit_orders_persisted_if_new(
            source="testing.listing_order_sim",
            order_data_list=order_data_list,
            order_item_list=order_item_list,
            db_result=save_res.data or {},
        )

        if bool((save_res.data or {}).get("changed")):
            try:
                order_signals.orders_changed.emit()
            except Exception:
                pass

        return Result.ok(
            f"{len(order_numbers)} listing-driven orders processed.",
            close_dialog=False,
            data={
                "order_numbers": order_numbers,
                "source_count": len(sources),
                "sources": [
                    {
                        "product_id": s.product_id,
                        "title": s.title,
                        "stock_code": s.stock_code,
                    }
                    for s in sources
                ],
                "lifecycle_key": str(lifecycle_key or "single").strip() or "single",
                "snapshot_count": len(order_data_list),
                "save": save_res.data or {},
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def verify_listing_order_simulation(
    *,
    api_account_id: int,
    listing_items: list[dict] | None = None,
    order_count: int = 1,
    lifecycle_key: str | None = "created",
    db_name: str | None = None,
) -> Result:
    """
    UI smoke check for the listing -> order path.
    It creates a listing-driven test order and verifies that the latest order
    items can be read back with fields copied from the listing source.
    """
    try:
        api_account_id = int(api_account_id)
        selected_items = list(listing_items or [])

        if not selected_items:
            listings_res = list_company_listings_for_testing(
                api_account_id=api_account_id,
                limit=20,
                db_name=db_name,
            )
            if not listings_res.success:
                return listings_res
            selected_items = list((listings_res.data or {}).get("items", []) or [])

        if not selected_items:
            listing_sim = simulate_listing_arrival(
                api_account_id=api_account_id,
                item_count=3,
                prefix="SMOKE-L",
                db_name=db_name,
            )
            if not listing_sim.success:
                return listing_sim
            listings_res = list_company_listings_for_testing(
                api_account_id=api_account_id,
                limit=20,
                db_name=db_name,
            )
            if not listings_res.success:
                return listings_res
            selected_items = list((listings_res.data or {}).get("items", []) or [])

        selected_items = selected_items[:3]
        sources = _normalize_listing_sources(selected_items)
        if not sources:
            return Result.fail("Smoke için geçerli listing kaynağı bulunamadı.", close_dialog=False)

        order_res = simulate_order_arrival_from_listings(
            api_account_id=api_account_id,
            listing_items=selected_items,
            order_count=max(1, min(int(order_count or 1), 10)),
            lifecycle_key=str(lifecycle_key or "created").strip() or "created",
            prefix="SMOKE-O",
            db_name=db_name,
        )
        if not order_res.success:
            return order_res

        order_numbers = list((order_res.data or {}).get("order_numbers") or [])
        if not order_numbers:
            return Result.fail("Smoke sipariş numarası üretilemedi.", close_dialog=False, data=order_res.data or {})

        with Session(get_engine(db_name or DB_NAME)) as session:
            rows = session.exec(
                select(OrderItem)
                .where(OrderItem.orderNumber.in_(order_numbers))
                .where(OrderItem.api_account_id == api_account_id)
            ).all() or []

        if not rows:
            return Result.fail(
                "Smoke sipariş kaydedildi ama OrderItem geri okunamadı.",
                close_dialog=False,
                data={"order_numbers": order_numbers, "simulation": order_res.data or {}},
            )

        expected_titles = {str(src.title or "").strip() for src in sources if str(src.title or "").strip()}
        expected_skus = {str(src.stock_code or src.product_id or "").strip() for src in sources}
        matched_rows = [
            row for row in rows
            if str(getattr(row, "productName", "") or "").strip() in expected_titles
            or str(getattr(row, "merchantSku", "") or "").strip() in expected_skus
            or str(getattr(row, "sku", "") or "").strip() in expected_skus
        ]
        if not matched_rows:
            return Result.fail(
                "Smoke sipariş satırları listing kaynaklarıyla eşleşmedi.",
                close_dialog=False,
                data={
                    "order_numbers": order_numbers,
                    "item_count": len(rows),
                    "expected_titles": sorted(expected_titles),
                    "expected_skus": sorted(expected_skus),
                },
            )

        return Result.ok(
            "Listing -> sipariş smoke doğrulandı.",
            close_dialog=False,
            data={
                "order_numbers": order_numbers,
                "source_count": len(sources),
                "item_count": len(rows),
                "matched_item_count": len(matched_rows),
                "snapshot_count": int((order_res.data or {}).get("snapshot_count") or 0),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def simulate_listing_arrival(
    *,
    api_account_id: int,
    item_count: int = 10,
    prefix: str = "SIM-L",
    db_name: str | None = None,
) -> Result:
    """
    Simulates listing arrivals without external API.
    """
    try:
        if int(item_count) <= 0:
            return Result.fail("item_count must be greater than 0.", close_dialog=False)

        item_count = min(int(item_count), 1000)
        api_account_id = int(api_account_id)
        now_ms = _utc_ms_now()

        items: list[dict[str, Any]] = []
        for idx in range(item_count):
            seed = now_ms + idx
            product_id = f"{prefix}-{api_account_id}-{seed}-{idx + 1}"
            items.append(
                {
                    "api_account_id": api_account_id,
                    "productId": product_id,
                    "title": f"Sim Listing Product {idx + 1}",
                    "barcode": f"869{seed % 1000000000:09d}",
                    "stockCode": f"SIM-STOCK-{idx + 1}",
                    "brand": "SIM-BRAND",
                    "quantity": float((idx % 5) + 1),
                    "approved": True,
                    "archived": False,
                    "onSale": True,
                    "listPrice": float((idx % 7) + 100),
                    "salePrice": float((idx % 7) + 90),
                    "images": [],
                    "attributes": [],
                }
            )

        save_kwargs = {}
        if db_name:
            save_kwargs["db_name"] = str(db_name)

        save_res = save_listings_to_db(items, **save_kwargs)
        if not save_res.success:
            return save_res

        counts = (save_res.data or {}).get("counts", {}) or {}
        history_count = int(counts.get("history", 0) or 0)
        inserted = int(counts.get("inserted", 0) or 0)
        delta = history_count if history_count > 0 else inserted

        if delta > 0:
            try:
                listing_signals.badge_changed.emit(delta)
            except Exception:
                pass

        return Result.ok(
            f"{item_count} simulated listings processed.",
            close_dialog=False,
            data={"save": save_res.data or {}},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def run_cargo_tariff_sandbox(
    *,
    platform_code: str,
    sale_price: float,
    dimensional_weight: float,
    cargo_provider_code: str = "",
    cargo_provider_name: str = "",
    cargo_provider_id: int | None = None,
    db_name: str | None = None,
) -> Result:
    try:
        tariffs_res = load_logistics_cargo_tariffs(source_state="all", db_name=db_name)
        if not tariffs_res.success:
            return tariffs_res
        tariffs = list((tariffs_res.data or {}).get("records") or [])
        match = resolve_finance_rule(
            "cargo_amount_matcher",
            {
                "cargoProviderId": cargo_provider_id,
                "cargoProviderCode": str(cargo_provider_code or "").strip().upper(),
                "cargoProviderName": str(cargo_provider_name or "").strip(),
            },
            {
                "platform_code": str(platform_code or "").strip(),
                "sale_price": float(sale_price),
                "effective_dimensional_weight": float(dimensional_weight),
                "cargo_tariffs": tariffs,
            },
        )
        if match.get("missing_reason"):
            return Result.fail(str(match.get("missing_reason") or "Uygun kargo tarifesi bulunamadı."), close_dialog=False, data=match)
        meta = dict(match.get("meta") or {})
        matched_tariff = dict(meta.get("matchedTariff") or {})
        match["tariff_label"] = str(meta.get("matchedTariffName") or match.get("note") or "")
        match["matched_tariff_label"] = str(meta.get("matchedTariffName") or match.get("note") or "")
        match["matched_tariff_key"] = str(meta.get("matchedTariffKey") or matched_tariff.get("tariffKey") or "")
        return Result.ok(
            "Kargo sandbox eşleşmesi hazırlandı.",
            close_dialog=False,
            data=match,
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def simulate_stock_depletion(
    *,
    item_limit: int = 500,
) -> Result:
    try:
        warehouses_res = list_warehouses(only_active=False)
        if not warehouses_res.success:
            return warehouses_res
        warehouse_rows = list((warehouses_res.data or {}).get("records") or [])
        if not warehouse_rows:
            return Result.fail("Stok tüketimi için depo bulunamadı.", close_dialog=False)
        warehouse_id = int(getattr(warehouse_rows[0], "id", 0) or 0)
        if warehouse_id <= 0:
            return Result.fail("Geçerli depo bulunamadı.", close_dialog=False)

        balances_res = list_item_balances(only_active=False)
        if not balances_res.success:
            return balances_res
        records = list((balances_res.data or {}).get("records") or [])
        limit = max(1, min(int(item_limit or 1), 1000))

        processed = 0
        depleted = 0
        errors: list[str] = []
        for row in records[:limit]:
            processed += 1
            item = row.get("item")
            item_id = int(getattr(item, "id", 0) or 0)
            on_hand = float(row.get("on_hand") or 0.0)
            if item_id <= 0 or on_hand <= 0:
                continue
            out_res = manual_out(
                item_id=item_id,
                warehouse_id=warehouse_id,
                qty=on_hand,
                allow_negative=True,
                created_by="testing.stock_depletion",
                note="TestLab stock depletion simulator",
            )
            if out_res.success:
                depleted += 1
            else:
                errors.append(f"{item_id}:{out_res.message}")

        if depleted <= 0 and errors:
            return Result.fail("Stok tüketimi başarısız oldu.", close_dialog=False, data={"processed": processed, "errors": errors})

        return Result.ok(
            "Stok tüketimi simülasyonu tamamlandı.",
            close_dialog=False,
            data={"processed": processed, "depleted": depleted, "errors": errors},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def run_label_stress_test(
    *,
    api_account_id: int,
    order_count: int = 1000,
    db_name: str | None = None,
) -> Result:
    try:
        simulated = simulate_order_arrival(
            api_account_id=int(api_account_id),
            order_count=max(1, min(int(order_count or 1), 1000)),
            lines_per_order=1,
            lifecycle_key="created",
            prefix="LBL-STRESS",
            db_name=db_name,
        )
        if not simulated.success:
            return simulated

        order_numbers = list((simulated.data or {}).get("order_numbers") or [])
        labels_res = create_order_label_from_orders(order_numbers)
        if not labels_res.success:
            return labels_res

        payload = dict((labels_res.data or {}).get("label_payload") or {})
        if not payload:
            return Result.fail("Etiket payload üretilemedi.", close_dialog=False)

        with tempfile.TemporaryDirectory(prefix="orderscout_label_stress_") as temp_root:
            output_path = Path(temp_root) / "stress_labels.docx"
            export_res = export_labels_to_word(
                payload,
                brand_code=str(payload.get("brand_code") or ""),
                model_code=str(payload.get("model_code") or ""),
                output_path=str(output_path),
            )
            if not export_res.success:
                return export_res

        return Result.ok(
            "Etiket stres testi tamamlandı.",
            close_dialog=False,
            data={
                "order_count": len(order_numbers),
                "snapshot_count": int((simulated.data or {}).get("snapshot_count") or 0),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def configure_test_chaos_mode(
    *,
    enabled: bool,
    mode: str = "timeout",
    rate: float = 0.30,
    seed: int | None = None,
) -> Result:
    try:
        state = (
            configure_request_chaos(enabled=enabled, mode=mode, rate=rate, seed=seed)
            if enabled
            else reset_request_chaos()
        )
        return Result.ok("Chaos modu güncellendi.", close_dialog=False, data={"state": state})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def run_domain_healthcheck(
    *,
    api_account_id: int | None = None,
    db_name: str | None = None,
) -> Result:
    """
    Runs a quick end-to-end healthcheck across core domains.
    """
    try:
        steps: list[dict[str, Any]] = []

        companies_res = list_companies_for_testing()
        steps.append(
            {
                "step": "account.list_companies",
                "success": companies_res.success,
                "detail": companies_res.message,
            }
        )
        if not companies_res.success:
            return Result.fail(companies_res.message, close_dialog=False, data={"steps": steps})

        companies = (companies_res.data or {}).get("companies", []) or []
        company_pk = _pick_company_pk(api_account_id, companies)
        if company_pk is None:
            return Result.fail("No company found for healthcheck.", close_dialog=False, data={"steps": steps})

        listing_sim = simulate_listing_arrival(
            api_account_id=company_pk,
            item_count=2,
            prefix="HLTH-L",
            db_name=db_name,
        )
        steps.append(
            {
                "step": "listing.simulate_arrival",
                "success": listing_sim.success,
                "detail": listing_sim.message,
            }
        )
        if not listing_sim.success:
            return Result.fail(listing_sim.message, close_dialog=False, data={"steps": steps})

        listings_res = list_company_listings_for_testing(
            api_account_id=company_pk,
            limit=20,
            db_name=db_name,
        )
        steps.append(
            {
                "step": "listing.read_company_items",
                "success": listings_res.success,
                "detail": listings_res.message,
            }
        )
        if not listings_res.success:
            return Result.fail(listings_res.message, close_dialog=False, data={"steps": steps})

        listing_sources = (listings_res.data or {}).get("items", []) or []
        if not listing_sources:
            return Result.fail("No listing sources available for order simulation.", close_dialog=False, data={"steps": steps})

        order_sim = simulate_order_arrival_from_listings(
            api_account_id=company_pk,
            listing_items=listing_sources[:3],
            order_count=1,
            prefix="HLTH-O",
            db_name=db_name,
        )
        steps.append(
            {
                "step": "orders.simulate_from_listings",
                "success": order_sim.success,
                "detail": order_sim.message,
            }
        )
        if not order_sim.success:
            return Result.fail(order_sim.message, close_dialog=False, data={"steps": steps})

        simulated_order_numbers = (order_sim.data or {}).get("order_numbers", []) or []
        if db_name:
            steps.append(
                {
                    "step": "labels.create_payload",
                    "success": True,
                    "detail": "Skipped in isolated-db mode.",
                }
            )
        elif simulated_order_numbers:
            labels_res = create_order_label_from_orders(simulated_order_numbers[:1])
            steps.append(
                {
                    "step": "labels.create_payload",
                    "success": labels_res.success,
                    "detail": labels_res.message,
                }
            )
            if not labels_res.success:
                return Result.fail(labels_res.message, close_dialog=False, data={"steps": steps})

        if db_name:
            steps.append(
                {
                    "step": "orders.nonfinal_query",
                    "success": True,
                    "detail": "Skipped in isolated-db mode.",
                }
            )
            steps.append(
                {
                    "step": "stock.reads",
                    "success": True,
                    "detail": "Skipped in isolated-db mode.",
                }
            )
        else:
            nonfinal_res = get_nonfinal_order_numbers()
            steps.append(
                {
                    "step": "orders.nonfinal_query",
                    "success": nonfinal_res.success,
                    "detail": nonfinal_res.message,
                }
            )
            if not nonfinal_res.success:
                return Result.fail(nonfinal_res.message, close_dialog=False, data={"steps": steps})

            stock_items_res = list_items(only_active=False)
            stock_warehouses_res = list_warehouses(only_active=False)
            stock_brands_res = list_brands(only_active=False)

            stock_ok = all([stock_items_res.success, stock_warehouses_res.success, stock_brands_res.success])
            steps.append(
                {
                    "step": "stock.reads",
                    "success": stock_ok,
                    "detail": (
                        f"items={stock_items_res.success}, "
                        f"warehouses={stock_warehouses_res.success}, "
                        f"brands={stock_brands_res.success}"
                    ),
                }
            )
            if not stock_ok:
                return Result.fail("Stock healthcheck step failed.", close_dialog=False, data={"steps": steps})

        return Result.ok(
            "Domain healthcheck completed successfully.",
            close_dialog=False,
            data={
                "company_pk": company_pk,
                "steps": steps,
                "simulated_order_numbers": simulated_order_numbers,
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def run_local_unittest_suite(
    *,
    pattern: str = "test_*.py",
    timeout_sec: int = 240,
) -> Result:
    """
    Runs local unittest discovery and returns compact execution output.
    """
    try:
        project_root = Path(__file__).resolve().parents[2]
        tests_dir = project_root / "tests"

        if not tests_dir.exists():
            return Result.fail("tests directory was not found.", close_dialog=False)

        timeout_sec = max(30, min(int(timeout_sec), 1800))
        pattern = (pattern or "test_*.py").strip() or "test_*.py"

        cmd = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            pattern,
            "-q",
        ]

        completed = subprocess.run(
            cmd,
            cwd=str(project_root),
            text=True,
            capture_output=True,
            timeout=timeout_sec,
        )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        output = "\n".join(part for part in [stdout, stderr] if part)

        if completed.returncode == 0:
            return Result.ok(
                "Local unittest suite passed.",
                close_dialog=False,
                data={
                    "returncode": completed.returncode,
                    "output": output,
                    "command": " ".join(cmd),
                },
            )

        return Result.fail(
            "Local unittest suite failed.",
            close_dialog=False,
            data={
                "returncode": completed.returncode,
                "output": output,
                "command": " ".join(cmd),
            },
        )

    except subprocess.TimeoutExpired as e:
        return Result.fail(
            f"Local unittest suite timed out after {timeout_sec} sec.",
            error=e,
            close_dialog=False,
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _emit_build_log(callback: BuildLogCallback, line: str) -> None:
    if callback is None:
        return
    try:
        callback(str(line or ""))
    except Exception:
        pass


def _emit_build_progress(callback: BuildProgressCallback, percent: int, stage: str) -> None:
    if callback is None:
        return
    try:
        callback(max(0, min(100, int(percent))), str(stage or "").strip())
    except Exception:
        pass


def _sanitize_version_token(version: str) -> str:
    raw = str(version or "").strip()
    if not raw:
        return "0.0.0"
    token = "".join(ch if (ch.isalnum() or ch in "._-") else "-" for ch in raw)
    token = token.strip("-. _")
    return token or "0.0.0"


def _select_packaging_python(project_root: Path) -> Path:
    candidates = [
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root.parent / ".venv" / "Scripts" / "python.exe",
        project_root.parent / "venv" / "Scripts" / "python.exe",
        Path(sys.executable).resolve(),
    ]
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return Path(sys.executable).resolve()


def _detect_iscc_path() -> Optional[Path]:
    env_path = str(os.environ.get("INNO_SETUP_COMPILER") or "").strip()
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    which_path = shutil.which("iscc")
    if which_path:
        candidates.append(Path(which_path))
    candidates.extend(
        [
            Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
            Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        ]
    )
    reg_paths = [
        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
    ]
    for reg_path in reg_paths:
        try:
            probe = subprocess.run(
                ["reg", "query", reg_path, "/v", "InstallLocation"],
                text=True,
                capture_output=True,
            )
            if int(probe.returncode if probe.returncode is not None else 1) != 0:
                continue
            for line in str(probe.stdout or "").splitlines():
                if "InstallLocation" not in line:
                    continue
                raw = line.split("REG_SZ", 1)[-1].strip()
                if not raw:
                    continue
                candidates.append(Path(raw) / "ISCC.exe")
        except Exception:
            continue
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return None


def _run_stream_command(
    *,
    command: list[str],
    cwd: Path,
    log_callback: BuildLogCallback = None,
    on_line: Optional[Callable[[str], None]] = None,
    env: Optional[dict[str, str]] = None,
) -> tuple[int, str]:
    cmd_text = shlex.join([str(x) for x in command])
    _emit_build_log(log_callback, f"$ {cmd_text}")
    proc = subprocess.Popen(
        [str(x) for x in command],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    collected: list[str] = []
    try:
        if proc.stdout is not None:
            for raw in proc.stdout:
                line = str(raw or "").rstrip()
                if not line:
                    continue
                collected.append(line)
                if len(collected) > 1500:
                    collected = collected[-1500:]
                _emit_build_log(log_callback, line)
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:
                        pass
        return_code = int(proc.wait())
    finally:
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass
    output_tail = "\n".join(collected[-300:])
    return return_code, output_tail


def _pyinstaller_progress_from_line(line: str, current: int) -> int:
    text = str(line or "").strip().lower()
    value = int(current)
    checkpoints = [
        ("wrote", 8),
        ("appending 'datas'", 12),
        ("running analysis", 20),
        ("analyzing modules", 30),
        ("analyzing", 35),
        ("building pyz", 52),
        ("building pkg", 66),
        ("building exe", 80),
        ("building collect", 92),
        ("build complete", 100),
    ]
    for token, mark in checkpoints:
        if token in text:
            value = max(value, mark)
    return max(0, min(100, value))


def _iscc_progress_from_line(line: str, current: int) -> int:
    text = str(line or "").strip().lower()
    value = int(current)
    checkpoints = [
        ("inno setup", 8),
        ("preprocessing", 16),
        ("parsing [setup]", 28),
        ("creating setup files", 62),
        ("updating version info", 86),
        ("successful compile", 100),
    ]
    for token, mark in checkpoints:
        if token in text:
            value = max(value, mark)
    return max(0, min(100, value))


def _inno_quote_path(path: Path) -> str:
    return str(path.resolve()).replace('"', '""')


def _iter_project_package_modules(project_root: Path, package_name: str) -> Iterable[str]:
    package_dir = project_root / str(package_name or "").replace(".", os.sep)
    if not package_dir.exists() or not package_dir.is_dir():
        return []

    modules: set[str] = set()
    for path in package_dir.rglob("*.py"):
        if any(part == "__pycache__" for part in path.parts):
            continue
        rel = path.relative_to(project_root).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        modules.add(".".join(parts))
    return sorted(modules)


def build_portable_exe_release(
    *,
    version: str,
    output_root: str,
    progress_callback: BuildProgressCallback = None,
    log_callback: BuildLogCallback = None,
) -> Result:
    try:
        project_root = Path(__file__).resolve().parents[2]
        main_py = project_root / "main.py"
        if not main_py.exists():
            return Result.fail("main.py bulunamadi.", close_dialog=False)

        raw_output = str(output_root or "").strip()
        if not raw_output:
            return Result.fail("Cikti klasoru zorunlu.", close_dialog=False)
        output_dir = Path(raw_output).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        python_exe = _select_packaging_python(project_root)
        _emit_build_log(log_callback, f"Python runtime: {python_exe}")

        check_cmd = [str(python_exe), "-m", "PyInstaller", "--version"]
        check = subprocess.run(
            check_cmd,
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )
        if int(check.returncode if check.returncode is not None else 1) != 0:
            return Result.fail(
                "PyInstaller bulunamadi. Venv veya ortam kurulumunu kontrol et.",
                close_dialog=False,
            )

        exe_root = output_dir / "exe"
        dist_path = exe_root / "dist"
        work_path = exe_root / "build"
        spec_path = exe_root / "spec"
        for p in [dist_path, work_path, spec_path]:
            p.mkdir(parents=True, exist_ok=True)

        icon_path = project_root / "images" / "orderscout-logo.ico"
        add_data_pairs = [
            (project_root / "images", "images"),
            (project_root / "Labels" / "assets", "Labels\\assets"),
            (project_root / "AI" / "constants" / "files", "AI\\constants\\files"),
            (project_root / "Account" / "constants" / "files", "Account\\constants\\files"),
            (project_root / "Core" / "constants" / "files", "Core\\constants\\files"),
            (project_root / "Finance" / "constants" / "files", "Finance\\constants\\files"),
            (project_root / "Listing" / "constants" / "trendyol" / "files", "Listing\\constants\\trendyol\\files"),
            (project_root / "Logistics" / "constants" / "files", "Logistics\\constants\\files"),
            (project_root / "Marketplaces" / "constants" / "files", "Marketplaces\\constants\\files"),
            (project_root / "Orders" / "constants" / "trendyol" / "files", "Orders\\constants\\trendyol\\files"),
            (project_root / "Stock" / "constants" / "files", "Stock\\constants\\files"),
            (project_root / "Update" / "constants" / "files", "Update\\constants\\files"),
        ]
        try:
            import docxcompose  # type: ignore

            docx_templates = Path(docxcompose.__file__).resolve().parent / "templates"
            if docx_templates.exists():
                add_data_pairs.append((docx_templates, "docxcompose\\templates"))
        except Exception:
            pass

        cmd = [
            str(python_exe),
            "-u",
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--name",
            "OrderScout",
            "--distpath",
            str(dist_path),
            "--workpath",
            str(work_path),
            "--specpath",
            str(spec_path),
            "--collect-data",
            "docxcompose",
        ]
        app_packages = [
            "Account",
            "AI",
            "Core",
            "Feedback",
            "Finance",
            "Labels",
            "Support",
            "Listing",
            "Logistics",
            "Main_interface",
            "Marketplaces",
            "Orders",
            "Stock",
            "Testing",
            "Update",
        ]
        for package_name in app_packages:
            cmd.extend(["--collect-submodules", package_name])
            for module_name in _iter_project_package_modules(project_root, package_name):
                cmd.extend(["--hidden-import", module_name])

        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])

        for src, dst in add_data_pairs:
            if src.exists():
                cmd.extend(["--add-data", f"{src};{dst}"])

        cmd.append(str(main_py))

        _emit_build_progress(progress_callback, 2, "PyInstaller hazırlık")
        current_progress = 2
        line_count = 0

        def _on_line(line: str) -> None:
            nonlocal current_progress
            nonlocal line_count
            line_count += 1
            lower = str(line or "").strip().lower()

            next_progress = _pyinstaller_progress_from_line(line, current_progress)
            # Long-running steps (especially analysis) should still show movement.
            if next_progress == current_progress and line_count % 25 == 0 and current_progress < 94:
                next_progress = min(94, current_progress + 1)
            current_progress = next_progress

            stage = "EXE derleniyor"
            if "running analysis" in lower or "analyzing modules" in lower:
                stage = "EXE analiz ediliyor"
            elif "building pyz" in lower:
                stage = "Python arşivi oluşturuluyor"
            elif "building pkg" in lower:
                stage = "Paket arşivi oluşturuluyor"
            elif "building exe" in lower:
                stage = "EXE üretiliyor"
            elif "building collect" in lower:
                stage = "Dosyalar toplanıyor"
            elif "build complete" in lower:
                stage = "EXE tamamlandı"

            _emit_build_progress(progress_callback, current_progress, stage)

        code, tail = _run_stream_command(
            command=cmd,
            cwd=project_root,
            log_callback=log_callback,
            on_line=_on_line,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        if int(code) != 0:
            return Result.fail(
                "PyInstaller işlemi başarısız.",
                close_dialog=False,
                data={"output_tail": tail},
            )

        exe_dir = dist_path / "OrderScout"
        exe_path = exe_dir / "OrderScout.exe"
        if not exe_path.exists():
            return Result.fail("EXE çıktı dosyası oluşmadı.", close_dialog=False)

        _emit_build_progress(progress_callback, 100, "EXE tamamlandı")
        _emit_build_log(log_callback, f"EXE: {exe_path}")
        return Result.ok(
            "EXE build tamamlandı.",
            close_dialog=False,
            data={
                "version": str(version or "").strip(),
                "output_root": str(output_dir),
                "exe_root": str(exe_root),
                "dist_dir": str(exe_dir),
                "exe_path": str(exe_path),
                "spec_path": str(spec_path / "OrderScout.spec"),
                "python_exe": str(python_exe),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def build_setup_from_exe_dist(
    *,
    version: str,
    output_root: str,
    dist_dir: str,
    progress_callback: BuildProgressCallback = None,
    log_callback: BuildLogCallback = None,
) -> Result:
    try:
        project_root = Path(__file__).resolve().parents[2]
        raw_output = str(output_root or "").strip()
        if not raw_output:
            return Result.fail("Cikti klasoru zorunlu.", close_dialog=False)
        output_dir = Path(raw_output).expanduser()
        dist_path = Path(str(dist_dir or "").strip()).expanduser()
        if not dist_path.exists():
            return Result.fail("Setup için dist klasörü bulunamadı.", close_dialog=False)
        if not (dist_path / "OrderScout.exe").exists():
            return Result.fail("Dist klasöründe OrderScout.exe bulunamadı.", close_dialog=False)

        iscc_path = _detect_iscc_path()
        if iscc_path is None:
            return Result.fail(
                "Inno Setup compiler (ISCC.exe) bulunamadi. INNO_SETUP_COMPILER ortam degiskenini ayarla.",
                close_dialog=False,
            )

        setup_root = output_dir / "setup"
        setup_root.mkdir(parents=True, exist_ok=True)
        script_path = setup_root / "OrderScout_auto_build.iss"
        # Keep a stable installer filename for website/download links and updater URLs.
        base_name = "OrderScout_Setup_x64"
        icon_path = project_root / "images" / "orderscout-logo.ico"
        icon_line = (
            f'SetupIconFile={_inno_quote_path(icon_path)}\n'
            if icon_path.exists()
            else ""
        )

        script_text = (
            '; Auto-generated by Test Lab build tab\n'
            '#define MyAppName "OrderScout"\n'
            f'#define MyAppVersion "{str(version or "").strip()}"\n'
            '#define MyAppPublisher "OrderScout"\n'
            '#define MyAppExeName "OrderScout.exe"\n'
            "\n"
            "[Setup]\n"
            "AppId={{6A52E4F6-EA38-4AF9-9F73-76D9B02B89B1}\n"
            "AppName={#MyAppName}\n"
            "AppVersion={#MyAppVersion}\n"
            "AppPublisher={#MyAppPublisher}\n"
            "DefaultDirName={autopf}\\OrderScout\n"
            "DefaultGroupName=OrderScout\n"
            "DisableDirPage=no\n"
            "DisableProgramGroupPage=yes\n"
            f"OutputDir={_inno_quote_path(setup_root)}\n"
            f"OutputBaseFilename={base_name}\n"
            "Compression=lzma\n"
            "SolidCompression=yes\n"
            "WizardStyle=modern\n"
            "ArchitecturesAllowed=x64compatible\n"
            "ArchitecturesInstallIn64BitMode=x64compatible\n"
            "PrivilegesRequired=admin\n"
            "CloseApplications=yes\n"
            "RestartApplications=no\n"
            f"{icon_line}"
            "\n"
            "[Languages]\n"
            'Name: "turkish"; MessagesFile: "compiler:Languages\\Turkish.isl"\n'
            'Name: "english"; MessagesFile: "compiler:Default.isl"\n'
            "\n"
            "[Tasks]\n"
            'Name: "desktopicon"; Description: "Masaüstü kısayolu oluştur"; GroupDescription: "Ek kısayollar:"; Flags: unchecked\n'
            "\n"
            "[Files]\n"
            f'Source: "{_inno_quote_path(dist_path)}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs\n'
            "\n"
            "[Icons]\n"
            'Name: "{autoprograms}\\OrderScout"; Filename: "{app}\\OrderScout.exe"\n'
            'Name: "{autodesktop}\\OrderScout"; Filename: "{app}\\OrderScout.exe"; Tasks: desktopicon\n'
            "\n"
            "[Run]\n"
            'Filename: "{app}\\OrderScout.exe"; Description: "OrderScout aç"; Flags: nowait postinstall skipifsilent\n'
        )
        script_path.write_text(script_text, encoding="utf-8-sig")
        _emit_build_log(log_callback, f"ISS script: {script_path}")

        _emit_build_progress(progress_callback, 3, "Inno Setup hazırlık")
        current_progress = 3
        total_files = 0
        try:
            total_files = sum(1 for p in dist_path.rglob("*") if p.is_file())
        except Exception:
            total_files = 0
        compressed_files = 0
        line_count = 0

        def _on_line(line: str) -> None:
            nonlocal current_progress
            nonlocal compressed_files
            nonlocal line_count
            line_count += 1
            raw = str(line or "").strip()
            lower = raw.lower()

            next_progress = _iscc_progress_from_line(raw, current_progress)
            stage = "Setup paketleniyor"

            if lower.startswith("compressing:") or " compressing:" in lower:
                if "setup program executable" in lower:
                    next_progress = max(next_progress, 96)
                    stage = "Kurulum dosyası sonlandırılıyor"
                else:
                    compressed_files += 1
                    if total_files > 0:
                        ratio = min(1.0, compressed_files / float(total_files))
                        dynamic = 35 + int(ratio * 58)  # 35..93
                        next_progress = max(next_progress, dynamic)
                    stage = "Setup dosyaları sıkıştırılıyor"
            elif "creating setup files" in lower:
                stage = "Setup dosyaları hazırlanıyor"
            elif "updating version info" in lower:
                stage = "Sürüm bilgisi güncelleniyor"
            elif "successful compile" in lower:
                stage = "Setup tamamlandı"

            if next_progress == current_progress and line_count % 40 == 0 and current_progress < 98:
                next_progress = min(98, current_progress + 1)

            current_progress = max(current_progress, next_progress)
            _emit_build_progress(progress_callback, current_progress, stage)

        code, tail = _run_stream_command(
            command=[str(iscc_path), str(script_path)],
            cwd=project_root,
            log_callback=log_callback,
            on_line=_on_line,
        )
        if int(code) != 0:
            return Result.fail(
                "Inno Setup derlemesi başarısız.",
                close_dialog=False,
                data={"output_tail": tail},
            )

        setup_path = setup_root / f"{base_name}.exe"
        if not setup_path.exists():
            return Result.fail("Setup dosyası oluşmadı.", close_dialog=False)

        _emit_build_progress(progress_callback, 100, "Setup tamamlandı")
        _emit_build_log(log_callback, f"SETUP: {setup_path}")
        return Result.ok(
            "Setup build tamamlandı.",
            close_dialog=False,
            data={
                "version": str(version or "").strip(),
                "output_root": str(output_dir),
                "setup_root": str(setup_root),
                "setup_path": str(setup_path),
                "iss_script": str(script_path),
                "iscc_path": str(iscc_path),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def build_exe_and_setup_release(
    *,
    version: str,
    output_root: str,
    progress_callback: BuildProgressCallback = None,
    log_callback: BuildLogCallback = None,
) -> Result:
    try:
        release_version = str(version or "").strip()
        if not release_version:
            return Result.fail("Sürüm boş olamaz.", close_dialog=False)
        raw_output = str(output_root or "").strip()
        if not raw_output:
            return Result.fail("Çıktı klasörü seçilmelidir.", close_dialog=False)
        output_dir = Path(raw_output).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        _emit_build_log(log_callback, f"Release build başladı (version={release_version})")
        _emit_build_log(log_callback, f"Çıktı kök klasörü: {output_dir}")

        def _phase1_progress(percent: int, stage: str) -> None:
            mapped = int(5 + (max(0, min(100, int(percent))) * 0.70))
            _emit_build_progress(progress_callback, mapped, stage or "EXE derleniyor")

        exe_res = build_portable_exe_release(
            version=release_version,
            output_root=str(output_dir),
            progress_callback=_phase1_progress,
            log_callback=log_callback,
        )
        if not exe_res.success:
            return exe_res

        exe_data = exe_res.data or {}
        dist_dir = str(exe_data.get("dist_dir") or "").strip()
        if not dist_dir:
            return Result.fail("EXE dist klasörü belirlenemedi.", close_dialog=False)

        def _phase2_progress(percent: int, stage: str) -> None:
            mapped = int(75 + (max(0, min(100, int(percent))) * 0.25))
            _emit_build_progress(progress_callback, mapped, stage or "Setup paketleniyor")

        setup_res = build_setup_from_exe_dist(
            version=release_version,
            output_root=str(output_dir),
            dist_dir=dist_dir,
            progress_callback=_phase2_progress,
            log_callback=log_callback,
        )
        if not setup_res.success:
            return setup_res

        setup_data = setup_res.data or {}
        _emit_build_progress(progress_callback, 100, "Release build tamamlandı")
        _emit_build_log(log_callback, "Tüm build adımları başarıyla tamamlandı.")
        return Result.ok(
            "EXE + Setup build tamamlandı.",
            close_dialog=False,
            data={
                "version": release_version,
                "output_root": str(output_dir),
                "exe_path": str(exe_data.get("exe_path") or ""),
                "dist_dir": str(exe_data.get("dist_dir") or ""),
                "setup_path": str(setup_data.get("setup_path") or ""),
                "iss_script": str(setup_data.get("iss_script") or ""),
                "iscc_path": str(setup_data.get("iscc_path") or ""),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _desktop_release_output_root() -> Path:
    return Path.home() / "Desktop" / "os-release"


def _desktop_release_repo_path() -> Path:
    return Path.home() / "Desktop" / "OrderScout-releases"


def _clean_release_output_dir(path: Path) -> None:
    target = path.expanduser().resolve()
    if target.name.casefold() != "os-release":
        raise RuntimeError(f"Release output klasoru beklenen isimde degil: {target}")
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _run_release_command(
    *,
    command: list[str],
    cwd: Path,
    log_callback: BuildLogCallback = None,
    allow_failure: bool = False,
) -> tuple[int, str]:
    code, tail = _run_stream_command(
        command=[str(part) for part in command],
        cwd=cwd,
        log_callback=log_callback,
    )
    if int(code) != 0 and not allow_failure:
        raise RuntimeError(f"Komut basarisiz: {shlex.join([str(x) for x in command])}\n{tail}")
    return int(code), str(tail or "")


def _ensure_release_repo(
    *,
    release_repo_path: Path,
    log_callback: BuildLogCallback = None,
) -> Path:
    repo_path = release_repo_path.expanduser().resolve()
    remote_url = "https://github.com/hermanjons/OrderScout-releases.git"
    if not repo_path.exists():
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        _run_release_command(
            command=["git", "clone", remote_url, str(repo_path)],
            cwd=repo_path.parent,
            log_callback=log_callback,
        )
    if not (repo_path / ".git").exists():
        raise RuntimeError(f"Release repo gecersiz: {repo_path}")
    _run_release_command(command=["git", "-C", str(repo_path), "fetch", "origin", "main"], cwd=repo_path, log_callback=log_callback)
    _run_release_command(command=["git", "-C", str(repo_path), "checkout", "main"], cwd=repo_path, log_callback=log_callback)
    _run_release_command(command=["git", "-C", str(repo_path), "pull", "--ff-only", "origin", "main"], cwd=repo_path, log_callback=log_callback)
    return repo_path


def _mirror_release_runtime_payload(
    *,
    dist_dir: Path,
    release_repo_path: Path,
    log_callback: BuildLogCallback = None,
) -> None:
    dist_path = dist_dir.expanduser().resolve()
    repo_path = release_repo_path.expanduser().resolve()
    internal_src = dist_path / "_internal"
    exe_src = dist_path / "OrderScout.exe"
    internal_dst = repo_path / "_internal"
    exe_dst = repo_path / "OrderScout.exe"
    if not internal_src.exists() or not internal_src.is_dir():
        raise RuntimeError(f"Runtime _internal bulunamadi: {internal_src}")
    if not exe_src.exists():
        raise RuntimeError(f"Runtime EXE bulunamadi: {exe_src}")
    if internal_dst.exists():
        shutil.rmtree(internal_dst)
    shutil.copytree(internal_src, internal_dst)
    shutil.copy2(exe_src, exe_dst)
    _emit_build_log(log_callback, f"Runtime payload mirrored: {repo_path}")


def _git_status_short(repo_path: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--short"],
        text=True,
        capture_output=True,
    )
    if int(completed.returncode if completed.returncode is not None else 1) != 0:
        raise RuntimeError(str(completed.stderr or completed.stdout or "git status failed").strip())
    return str(completed.stdout or "").strip()


def _commit_and_push_release_repo(
    *,
    release_repo_path: Path,
    version: str,
    log_callback: BuildLogCallback = None,
) -> str:
    repo_path = release_repo_path.expanduser().resolve()
    status = _git_status_short(repo_path)
    if status:
        _emit_build_log(log_callback, status)
        _run_release_command(command=["git", "-C", str(repo_path), "add", "-A"], cwd=repo_path, log_callback=log_callback)
        _run_release_command(
            command=["git", "-C", str(repo_path), "commit", "-m", f"Release artifacts v{version}"],
            cwd=repo_path,
            log_callback=log_callback,
        )
    else:
        _emit_build_log(log_callback, "Release repo runtime degisikligi yok; mevcut HEAD kullaniliyor.")
    _run_release_command(command=["git", "-C", str(repo_path), "push", "origin", "main"], cwd=repo_path, log_callback=log_callback)
    completed = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    if int(completed.returncode if completed.returncode is not None else 1) != 0:
        raise RuntimeError("Release repo HEAD okunamadi.")
    head = str(completed.stdout or "").strip()
    _emit_build_log(log_callback, f"Release repo HEAD: {head}")
    return head


def _git_credential_for_github(repo_slug: str) -> tuple[str, str]:
    cred_input = f"protocol=https\nhost=github.com\npath={repo_slug}\n\n"
    completed = subprocess.run(
        ["git", "credential", "fill"],
        input=cred_input,
        text=True,
        capture_output=True,
    )
    if int(completed.returncode if completed.returncode is not None else 1) != 0:
        raise RuntimeError("GitHub credential okunamadi.")
    username = ""
    password = ""
    for line in str(completed.stdout or "").splitlines():
        if line.startswith("username="):
            username = line.split("=", 1)[1].strip()
        elif line.startswith("password="):
            password = line.split("=", 1)[1].strip()
    if not username or not password:
        raise RuntimeError("GitHub credential eksik.")
    return username, password


def _github_headers(repo_slug: str, *, content_type: str = "application/json") -> dict[str, str]:
    username, password = _git_credential_for_github(repo_slug)
    token = base64.b64encode(f"{username}:{password}".encode("ascii")).decode("ascii")
    headers = {
        "Authorization": f"Basic {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "OrderScout-Release-Agent",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _github_request(
    *,
    url: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            if not raw:
                return int(response.status), None
            return int(response.status), json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        detail = ""
        try:
            detail = raw.decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"GitHub API {method} {url} failed: {exc.code} {detail}") from exc


def _github_request_allow_404(
    *,
    url: str,
    method: str,
    headers: dict[str, str],
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            if not raw:
                return int(response.status), None
            return int(response.status), json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if int(exc.code) == 404:
            return 404, None
        raw = exc.read()
        raise RuntimeError(f"GitHub API {method} {url} failed: {exc.code} {raw.decode('utf-8', errors='replace')}") from exc


def _replace_release_tag(
    *,
    release_repo_path: Path,
    repo_slug: str,
    tag: str,
    log_callback: BuildLogCallback = None,
) -> None:
    headers = _github_headers(repo_slug)
    release_url = f"https://api.github.com/repos/{repo_slug}/releases/tags/{urllib.parse.quote(tag)}"
    status, release = _github_request_allow_404(url=release_url, method="GET", headers=headers)
    if status != 404 and isinstance(release, dict):
        release_id = release.get("id")
        if release_id:
            _emit_build_log(log_callback, f"Existing GitHub release deleted: {tag}")
            _github_request(
                url=f"https://api.github.com/repos/{repo_slug}/releases/{release_id}",
                method="DELETE",
                headers=headers,
            )

    repo_path = release_repo_path.expanduser().resolve()
    _run_release_command(
        command=["git", "-C", str(repo_path), "push", "origin", f":refs/tags/{tag}"],
        cwd=repo_path,
        log_callback=log_callback,
        allow_failure=True,
    )
    _run_release_command(
        command=["git", "-C", str(repo_path), "tag", "-d", tag],
        cwd=repo_path,
        log_callback=log_callback,
        allow_failure=True,
    )
    _run_release_command(
        command=["git", "-C", str(repo_path), "tag", "-a", tag, "HEAD", "-m", f"OrderScout {tag}"],
        cwd=repo_path,
        log_callback=log_callback,
    )
    _run_release_command(
        command=["git", "-C", str(repo_path), "push", "origin", f"refs/tags/{tag}"],
        cwd=repo_path,
        log_callback=log_callback,
    )


def _create_github_release_and_upload_setup(
    *,
    repo_slug: str,
    tag: str,
    version: str,
    setup_path: Path,
    log_callback: BuildLogCallback = None,
) -> dict[str, Any]:
    headers = _github_headers(repo_slug)
    body = json.dumps(
        {
            "tag_name": tag,
            "target_commitish": "main",
            "name": f"OrderScout v{version} - Stable Release",
            "body": f"Automated release for OrderScout v{version}.\n\nAssets:\n- OrderScout_Setup_x64.exe",
            "draft": False,
            "prerelease": False,
        }
    ).encode("utf-8")
    _status, release = _github_request(
        url=f"https://api.github.com/repos/{repo_slug}/releases",
        method="POST",
        headers=headers,
        body=body,
    )
    if not isinstance(release, dict):
        raise RuntimeError("GitHub release yaniti gecersiz.")
    upload_base = str(release.get("upload_url") or "").split("{", 1)[0]
    if not upload_base:
        raise RuntimeError("GitHub upload_url bulunamadi.")
    upload_url = f"{upload_base}?name=OrderScout_Setup_x64.exe"
    asset_headers = _github_headers(repo_slug, content_type="application/octet-stream")
    setup_bytes = setup_path.read_bytes()
    _asset_status, asset = _github_request(
        url=upload_url,
        method="POST",
        headers=asset_headers,
        body=setup_bytes,
    )
    if not isinstance(asset, dict):
        raise RuntimeError("GitHub asset yaniti gecersiz.")
    local_sha = hashlib.sha256(setup_bytes).hexdigest()
    digest = str(asset.get("digest") or "")
    _emit_build_log(log_callback, f"GitHub release: {release.get('html_url')}")
    _emit_build_log(log_callback, f"Setup SHA256: {local_sha}")
    if digest:
        _emit_build_log(log_callback, f"GitHub asset digest: {digest}")
    return {
        "release_url": str(release.get("html_url") or ""),
        "asset_url": str(asset.get("browser_download_url") or ""),
        "asset_size": int(asset.get("size") or 0),
        "asset_digest": digest,
        "setup_sha256": local_sha,
    }


def publish_desktop_release(
    *,
    version: str,
    output_root: str = "",
    release_repo_path: str = "",
    release_repo_slug: str = "hermanjons/OrderScout-releases",
    progress_callback: BuildProgressCallback = None,
    log_callback: BuildLogCallback = None,
) -> Result:
    try:
        release_version = str(version or "").strip()
        if not release_version:
            return Result.fail("Surum bos olamaz.", close_dialog=False)
        repo_slug = str(release_repo_slug or "hermanjons/OrderScout-releases").strip()
        output_dir = Path(output_root).expanduser() if str(output_root or "").strip() else _desktop_release_output_root()
        release_repo = Path(release_repo_path).expanduser() if str(release_repo_path or "").strip() else _desktop_release_repo_path()
        tag = f"v.{release_version}"

        _emit_build_progress(progress_callback, 1, "Release klasoru temizleniyor")
        _emit_build_log(log_callback, f"One-click release basladi: {tag}")
        _emit_build_log(log_callback, f"Output root: {output_dir}")
        _emit_build_log(log_callback, f"Release repo: {release_repo}")
        _clean_release_output_dir(output_dir)

        def _build_progress(percent: int, stage: str) -> None:
            mapped = int(4 + (max(0, min(100, int(percent))) * 0.66))
            _emit_build_progress(progress_callback, mapped, stage or "Build")

        build_res = build_exe_and_setup_release(
            version=release_version,
            output_root=str(output_dir),
            progress_callback=_build_progress,
            log_callback=log_callback,
        )
        if not build_res.success:
            return build_res
        build_data = build_res.data or {}
        dist_dir = Path(str(build_data.get("dist_dir") or ""))
        setup_path = Path(str(build_data.get("setup_path") or ""))
        if not dist_dir.exists() or not setup_path.exists():
            return Result.fail("Build ciktilari eksik.", close_dialog=False, data=build_data)

        _emit_build_progress(progress_callback, 72, "Release repo hazirlaniyor")
        repo_path = _ensure_release_repo(release_repo_path=release_repo, log_callback=log_callback)
        _emit_build_progress(progress_callback, 76, "Runtime payload aynalaniyor")
        _mirror_release_runtime_payload(dist_dir=dist_dir, release_repo_path=repo_path, log_callback=log_callback)
        _emit_build_progress(progress_callback, 82, "Release repo push")
        release_commit = _commit_and_push_release_repo(
            release_repo_path=repo_path,
            version=release_version,
            log_callback=log_callback,
        )
        _emit_build_progress(progress_callback, 88, "Tag yenileniyor")
        _replace_release_tag(
            release_repo_path=repo_path,
            repo_slug=repo_slug,
            tag=tag,
            log_callback=log_callback,
        )
        _emit_build_progress(progress_callback, 94, "GitHub release yayinlaniyor")
        github_data = _create_github_release_and_upload_setup(
            repo_slug=repo_slug,
            tag=tag,
            version=release_version,
            setup_path=setup_path,
            log_callback=log_callback,
        )
        _emit_build_progress(progress_callback, 100, "Release tamamlandi")
        _emit_build_log(log_callback, "One-click release tamamlandi.")
        return Result.ok(
            "Desktop release yayinlandi.",
            close_dialog=False,
            data={
                **build_data,
                **github_data,
                "tag": tag,
                "release_commit": release_commit,
                "release_repo": str(repo_path),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
