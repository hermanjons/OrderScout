"""Exact local listing/stock binding reads and single-link previews.

The manual editor owns a complete replacement list. A single-link preview
merges one explicit stock card into the observed bindings before using that
same replacement operation; it never chooses a listing or a stock card.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Listing.models import ListingProduct
from Stock.models import StockItem
from settings import DB_NAME


def _positive_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("positive_integer_id_required")
    return value


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _listing_identity(row: ListingProduct) -> dict[str, Any]:
    return {"listing_id": row.pk, "api_account_id": row.api_account_id,
            "product_id": row.product_id, "title": row.title, "barcode": row.barcode,
            "stock_code": row.stock_code, "archived": row.archived}


def _stock_identity(row: StockItem) -> dict[str, Any]:
    return {"stock_item_id": row.pk, "sku": row.sku, "name": row.name,
            "barcode": row.barcode, "unit": row.unit, "is_active": row.is_active}


def _binding_state(row: ListingProduct, latest_rows: dict) -> str:
    snapshots = [{"stock_item_id": int(stock_id), "snapshot_id": snapshot.pk,
                  "status": snapshot.status, "qty": float(snapshot.qty)}
                 for (listing_id, stock_id), snapshot in sorted(latest_rows.items())
                 if listing_id == row.pk]
    return _digest({"listing": _listing_identity(row), "identity": row.sync_uuid,
                    "primary_stock_item_id": row.stock_item_id, "snapshots": snapshots})


def _stock_state(rows: list[StockItem]) -> str:
    return _digest([{**_stock_identity(row), "identity": row.sync_uuid}
                    for row in sorted(rows, key=lambda item: int(item.pk))])


def _exact_listing(session: Session, *, listing_id: int, api_account_id: int,
                   product_id: str) -> ListingProduct | None:
    _positive_id(listing_id)
    _positive_id(api_account_id)
    if not isinstance(product_id, str) or not product_id or product_id != product_id.strip():
        raise ValueError("exact_product_id_required")
    return session.exec(select(ListingProduct).where(
        ListingProduct.pk == listing_id, ListingProduct.api_account_id == api_account_id,
        ListingProduct.product_id == product_id)).first()


def effective_listing_stock_bindings(listing: ListingProduct, snapshot_rows) -> list[dict]:
    """Project latest history rows, retaining a primary-only legacy binding.

    Snapshot history is authoritative, including removals. The old primary
    pointer means one stock unit only when this listing has no history at all.
    Do not validate away a dangling legacy pointer here: preparation must see
    the missing stock card and fail rather than silently replace its binding.
    """
    from Listing.processors.pipeline import _snapshot_removed, _stock_binding_payload_from_snapshot
    history = list(snapshot_rows)
    bindings = []
    for row in history:
        if _snapshot_removed(row):
            continue
        payload = _stock_binding_payload_from_snapshot(row)
        if payload is not None:
            bindings.append(payload)
    if not history and listing.stock_item_id is not None:
        bindings.append({"stock_item_id": int(listing.stock_item_id), "qty": 1.0})
    bindings.sort(key=lambda item: (item["stock_item_id"] != listing.stock_item_id, item["stock_item_id"]))
    return bindings


def _read_bindings(session: Session, listing: ListingProduct) -> tuple[list[dict], dict]:
    from Listing.processors.pipeline import _latest_stock_snapshot_rows_by_listing
    latest = _latest_stock_snapshot_rows_by_listing(session, listing_ids=[int(listing.pk)])
    return effective_listing_stock_bindings(listing, latest.values()), latest


def read_listing_stock_links(*, listing_id: int, api_account_id: int, product_id: str,
                             db_name: str = DB_NAME) -> Result:
    """Read one exact account-owned listing's current local binding rows."""
    try:
        with Session(get_engine(db_name)) as session:
            listing = _exact_listing(session, listing_id=listing_id,
                api_account_id=api_account_id, product_id=product_id)
            if listing is None:
                return Result.fail("İlan kimliği ve hesap/ürün anahtarı eşleşmiyor.", close_dialog=False,
                                   data={"reason": "listing_identity_mismatch", "complete": False})
            bindings, latest = _read_bindings(session, listing)
            return Result.ok(data={"listing": _listing_identity(listing), "stock_items": bindings,
                "binding_state": _binding_state(listing, latest), "complete": True,
                "quantity_basis": "stock_units_per_listing_unit", "scope": "local"})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False,
                           data={"complete": False})


def preview_listing_stock_link(*, listing_id: int, api_account_id: int, product_id: str,
                               stock_item_id: int, qty: float = 1, db_name: str = DB_NAME) -> Result:
    """Validate and prepare one selected link while retaining every other link."""
    try:
        _positive_id(stock_item_id)
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or not math.isfinite(qty) or qty <= 0:
            raise ValueError("finite_positive_quantity_required")
        with Session(get_engine(db_name)) as session:
            listing = _exact_listing(session, listing_id=listing_id,
                api_account_id=api_account_id, product_id=product_id)
            if listing is None:
                return Result.fail("İlan kimliği ve hesap/ürün anahtarı eşleşmiyor.", close_dialog=False,
                                   data={"reason": "listing_identity_mismatch", "complete": False})
            stock = session.get(StockItem, stock_item_id)
            if stock is None or not stock.is_active:
                return Result.fail("Seçilen etkin stok kartı bulunamadı.", close_dialog=False,
                                   data={"reason": "active_stock_item_required", "complete": False})
            current, latest = _read_bindings(session, listing)
            desired = {row["stock_item_id"]: dict(row) for row in current}
            desired[stock_item_id] = {"stock_item_id": stock_item_id, "qty": float(qty)}
            desired_items = list(desired.values())
            stock_rows = list(session.exec(select(StockItem).where(StockItem.pk.in_(list(desired)))).all())
            if len(stock_rows) != len(desired):
                return Result.fail("Mevcut eşleştirmede eksik stok kartı var.", close_dialog=False,
                                   data={"reason": "missing_existing_stock_item", "complete": False})
            payload = {"listing_id": listing_id, "api_account_id": api_account_id, "product_id": product_id,
                       "stock_items": desired_items, "expected_binding_state": _binding_state(listing, latest),
                       "expected_stock_state": _stock_state(stock_rows), "db_name": db_name}
            return Result.ok(data={"listing": _listing_identity(listing), "stock_item": _stock_identity(stock),
                "qty": float(qty), "current_stock_items": current, "desired_stock_items": desired_items,
                "changed": current != desired_items, "payload": payload, "complete": True,
                "quantity_basis": "stock_units_per_listing_unit", "scope": "local"})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False,
                           data={"complete": False})
