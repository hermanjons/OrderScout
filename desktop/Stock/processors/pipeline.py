# Stock/processors/pipeline.py
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from contextvars import ContextVar
import json
import hashlib
import secrets
import time
import unicodedata
from typing import Any, Dict, Optional, Iterable
from types import SimpleNamespace

from sqlmodel import Session, select
from sqlalchemy import String, cast, func, or_, case, update as sa_update
from sqlalchemy.exc import IntegrityError

from settings import DB_NAME
from Feedback.processors.pipeline import Result, map_error_to_message

from Core.utils.model_utils import (
    get_engine,
    create_records,
    update_records,
    delete_records,
    get_records,
    make_normalizer,
)

from Finance.models.trendyol.models import Brand, Company
from Stock.models import StockItem, Warehouse, StockTx
from Stock.signals.signals import stock_signals
from Stock.constants.domain_constants import (
    StockError,
    StockItemType,
    StockTxDirection,
    StockTxReason,
    StockReferenceType,
    ALLOW_NEGATIVE_STOCK_DEFAULT,
    UNIT_COST_INPUT_MODE_GROSS,
    UNIT_COST_INPUT_MODE_NET,
    UNIT_COST_INPUT_MODE_MIXED,
    UNIT_COST_INPUT_MODE_LEGACY,
)
from Stock.constants.catalog_constants import (
    next_user_sub_group_id,
    next_user_upper_group_id,
    save_user_sub_group_map,
    save_user_upper_group_rows,
    sub_group_map,
    upper_group_names,
    upper_group_rows,
    user_sub_group_map,
    user_upper_group_rows,
)

_STOCK_SIGNAL_DEBOUNCE_SECONDS = 0.03
_last_refresh_emit_at = 0.0
_last_quick_access_emit: dict[str, tuple[int, float]] = {}
_ENGINE_DB_NAME: str | None = None
_ENGINE = None
_pd = None
_NAMED_RECORD_ID_CACHE: dict[tuple[str, ...], Optional[int]] = {}
_DATABASE_SCOPE = ContextVar("orderscout_stock_database", default=None)


def _database_name(db_name=None):
    return str(db_name or _DATABASE_SCOPE.get() or DB_NAME)


@contextmanager
def database_scope(db_name):
    """Bind manual and agent operations without changing process-wide settings."""
    token = _DATABASE_SCOPE.set(_database_name(db_name))
    try:
        yield
    finally:
        _DATABASE_SCOPE.reset(token)

# -------------------------------------------------
# Normalizers (match your models.py)
# -------------------------------------------------
item_normalizer = make_normalizer(
    coalesce_none={
        "barcode": None,
        "brand_id": None,
        "brand": None,
        "category": None,
        "sub_category": None,
        "model_code": None,
        "manufacturer": None,
        "gtip_code": None,
        "custom_label": None,
        "location_code": None,
        "image_path": None,
        "description": None,
        "note": None,
        "min_stock": None,
        "max_stock": None,
        "safety_stock": None,
        "reorder_point": None,
        "reorder_qty": None,
        "lead_time_days": None,
        "shelf_life_days": None,
        "vat_rate": None,
        "weight_kg": None,
        "length_cm": None,
        "width_cm": None,
        "height_cm": None,
        "default_cost": None,
        "default_currency": "TRY",
        "unit": "adet",
        "item_type": StockItemType.physical.value,
        "is_active": True,
        "serial_tracking": False,
        "lot_tracking": False,
        "allow_negative_stock": False,
    },
    strip_strings=True,
)

warehouse_normalizer = make_normalizer(
    coalesce_none={
        "name": None,
        "code": None,
        "manager_name": None,
        "phone": None,
        "email": None,
        "address": None,
        "city": None,
        "country": None,
        "capacity_m3": None,
        "layout_json": None,
        "note": None,
        "is_active": True,
    },
    strip_strings=True,
)

tx_normalizer = make_normalizer(
    coalesce_none={
        "unit_cost": None,
        "unit_cost_input_mode": None,
        "unit_cost_vat_rate": None,
        "currency": "TRY",
        "valuation_method": "moving_avg",
        "valuation_calc_version": 1,
        "valuation_cost_source": None,
        "valuation_qty_before": None,
        "valuation_qty_after": None,
        "valuation_stock_value_before": None,
        "valuation_stock_value_after": None,
        "valuation_avg_before": None,
        "valuation_avg_after": None,
        "reference_type": StockReferenceType.none,
        "reference_id": None,
        "order_header_id": None,
        "order_ref": None,
        "listing_id": None,
        "map_qty": None,
        "note": None,
        "created_by": None,
        "company_id": None,
        "counterparty": None,
        "attachments": None,
    },
    strip_strings=True,
)

brand_normalizer = make_normalizer(strip_strings=True)
company_normalizer = make_normalizer(strip_strings=True)

def _engine(db_name: str | None = None):
    return get_engine(_database_name(db_name))


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _pandas():
    global _pd
    if _pd is None:
        import pandas as pd

        _pd = pd
    return _pd


def _safe_int_id(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _stock_tx_count(*, item_id: Optional[int] = None, warehouse_id: Optional[int] = None) -> int:
    stmt = select(func.count()).select_from(StockTx)
    if item_id is not None:
        stmt = stmt.where(StockTx.item_id == int(item_id))
    if warehouse_id is not None:
        stmt = stmt.where(StockTx.warehouse_id == int(warehouse_id))
    with Session(_engine()) as session:
        result = session.exec(stmt).one()
    try:
        return int(result or 0)
    except Exception:
        return 0


def _stock_item_brand_count(brand_id: int) -> int:
    stmt = select(func.count()).select_from(StockItem).where(StockItem.brand_id == int(brand_id))
    with Session(_engine()) as session:
        result = session.exec(stmt).one()
    try:
        return int(result or 0)
    except Exception:
        return 0


def _stock_tx_company_count(company_id: int) -> int:
    stmt = select(func.count()).select_from(StockTx).where(StockTx.company_id == int(company_id))
    with Session(_engine()) as session:
        result = session.exec(stmt).one()
    try:
        return int(result or 0)
    except Exception:
        return 0


def _list_stock_items(*, only_active: bool = True, db_name: str | None = None) -> list[StockItem]:
    stmt = select(StockItem)
    if only_active:
        stmt = stmt.where(StockItem.is_active.is_(True))
    stmt = stmt.order_by(StockItem.name, StockItem.sku, StockItem.pk)
    with Session(_engine(db_name)) as session:
        return list(session.exec(stmt).all() or [])


def _list_named_records(model: Any, *, only_active: bool = True) -> list[Any]:
    stmt = select(model)
    is_active_column = getattr(model, "is_active", None)
    if only_active and is_active_column is not None:
        stmt = stmt.where(is_active_column.is_(True))

    order_columns = [column for column in (getattr(model, "name", None), getattr(model, "pk", None)) if column is not None]
    if order_columns:
        stmt = stmt.order_by(*order_columns)

    with Session(_engine()) as session:
        return list(session.exec(stmt).all() or [])


def _get_record(model: Any, pk: Any) -> Any:
    try:
        record_id = int(pk)
    except Exception:
        return None
    if record_id <= 0:
        return None
    with Session(_engine()) as session:
        return session.get(model, record_id)


def _resolve_named_record_id(model: Any, name: Any, *, id_attr: str = "pk", name_attr: str = "name") -> Optional[int]:
    text = str(name or "").strip()
    if not text:
        return None
    cache_key = (
        _database_name(),
        str(getattr(model, "__tablename__", getattr(model, "__name__", model))),
        str(id_attr),
        str(name_attr),
        text.casefold(),
    )
    if cache_key in _NAMED_RECORD_ID_CACHE:
        return _NAMED_RECORD_ID_CACHE[cache_key]
    with Session(_engine()) as session:
        stmt = (
            select(getattr(model, id_attr))
            .where(func.lower(getattr(model, name_attr)) == text.casefold())
            .limit(1)
        )
        row = session.exec(stmt).first()
    result = _safe_int_id(row)
    _NAMED_RECORD_ID_CACHE[cache_key] = result
    return result


def _resolve_brand_id(brand_name: Any) -> Optional[int]:
    return _resolve_named_record_id(Brand, brand_name)


def _resolve_company_id(company_name: Any) -> Optional[int]:
    return _resolve_named_record_id(Company, company_name)


def _sync_stock_item_brand_labels(*, brand_id: int, brand_name: str) -> None:
    normalized_name = str(brand_name or "").strip() or None
    with Session(_engine()) as session:
        session.exec(
            sa_update(StockItem)
            .where(StockItem.brand_id == int(brand_id))
            .values(brand=normalized_name, updated_at=_utcnow_naive())
        )
        session.commit()


def _sync_stock_tx_company_labels(*, company_id: int, company_name: str) -> None:
    normalized_name = str(company_name or "").strip() or None
    with Session(_engine()) as session:
        session.exec(
            sa_update(StockTx)
            .where(StockTx.company_id == int(company_id))
            .values(counterparty=normalized_name)
        )
        session.commit()


def _list_txs_query(
    *,
    item_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> list[StockTx]:
    stmt = select(StockTx)
    if item_id is not None:
        stmt = stmt.where(StockTx.item_id == int(item_id))
    if warehouse_id is not None:
        stmt = stmt.where(StockTx.warehouse_id == int(warehouse_id))
    stmt = stmt.order_by(
        StockTx.occurred_at.desc(),
        StockTx.created_at.desc(),
        StockTx.pk.desc(),
    )
    if limit is not None:
        stmt = stmt.limit(max(1, int(limit)))
    with Session(_engine()) as session:
        return list(session.exec(stmt).all() or [])


def _normalize_update_payload(update_data: Dict[str, Any], *, normalizer=None) -> Dict[str, Any]:
    payload = dict(update_data or {})
    if not payload or normalizer is None:
        return payload
    try:
        normalized = normalizer(payload)
    except Exception:
        return payload
    normalized_dict = dict(normalized or payload)
    return {key: normalized_dict.get(key, payload.get(key)) for key in payload.keys()}


def _comparable_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _prepare_update_payload(
    model: Any,
    pk: int,
    update_data: Dict[str, Any],
    *,
    normalizer=None,
    stamp_updated_at: bool = True,
) -> tuple[Optional[Dict[str, Any]], Optional[Result]]:
    current = _get_record(model, pk)
    if current is None:
        return None, Result.fail("Kayıt bulunamadı.", close_dialog=False)

    normalized = _normalize_update_payload(update_data, normalizer=normalizer)
    changed: Dict[str, Any] = {}
    for key, value in normalized.items():
        current_value = getattr(current, key, None)
        if _comparable_value(current_value) != _comparable_value(value):
            changed[key] = value

    if not changed:
        return None, _ok("Değişiklik yok.", noop=True)

    if stamp_updated_at and hasattr(current, "updated_at"):
        changed["updated_at"] = _utcnow_naive()
    return changed, None


def _aggregate_on_hand_by_item(
    item_ids: list[int],
    *,
    warehouse_id: Optional[int] = None,
    session: Session | None = None,
    db_name: str | None = None,
) -> Dict[int, float]:
    if not item_ids:
        return {}

    qty_delta = case(
        (StockTx.direction == StockTxDirection.IN_, StockTx.qty),
        else_=-StockTx.qty,
    )
    stmt = (
        select(
            StockTx.item_id,
            func.coalesce(func.sum(qty_delta), 0.0),
        )
        .where(StockTx.item_id.in_(item_ids))
        .group_by(StockTx.item_id)
    )
    if warehouse_id is not None:
        stmt = stmt.where(StockTx.warehouse_id == int(warehouse_id))

    totals: Dict[int, float] = {}
    if session is None:
        with Session(_engine(db_name)) as owned_session:
            rows = owned_session.exec(stmt).all() or []
    else:
        rows = session.exec(stmt).all() or []
    for item_id, on_hand in rows:
        try:
            totals[int(item_id)] = float(on_hand or 0.0)
        except Exception:
            continue
    return totals


def _list_balance_txs(
    item_ids: list[int],
    *,
    warehouse_id: Optional[int] = None,
    db_name: str | None = None,
) -> list[Any]:
    if not item_ids:
        return []
    stmt = select(
        StockTx.pk,
        StockTx.item_id,
        StockTx.warehouse_id,
        StockTx.direction,
        StockTx.qty,
        StockTx.occurred_at,
        StockTx.created_at,
        StockTx.unit_cost,
        StockTx.currency,
        StockTx.unit_cost_input_mode,
    ).where(StockTx.item_id.in_(item_ids))
    if warehouse_id is not None:
        stmt = stmt.where(StockTx.warehouse_id == int(warehouse_id))
    stmt = stmt.order_by(
        StockTx.item_id,
        StockTx.warehouse_id,
        StockTx.occurred_at,
        StockTx.created_at,
        StockTx.pk,
    )
    with Session(_engine(db_name)) as session:
        return list(session.exec(stmt).all() or [])


def _balance_maps_from_latest_valuations(
    item_ids: list[int],
    *,
    warehouse_id: Optional[int] = None,
    db_name: str | None = None,
) -> Optional[tuple]:
    if not item_ids:
        return {}, {}, {}, {}, {}, {}

    row_number = func.row_number().over(
        partition_by=(StockTx.item_id, StockTx.warehouse_id),
        order_by=(
            StockTx.occurred_at.desc(),
            StockTx.created_at.desc(),
            StockTx.pk.desc(),
        ),
    ).label("row_number")
    latest_base = select(StockTx.pk.label("tx_pk"), row_number).where(StockTx.item_id.in_(item_ids))
    if warehouse_id is not None:
        latest_base = latest_base.where(StockTx.warehouse_id == int(warehouse_id))
    latest_subq = latest_base.subquery()
    stmt = (
        select(
            StockTx.item_id,
            StockTx.warehouse_id,
            StockTx.valuation_qty_after,
            StockTx.valuation_avg_after,
            StockTx.currency,
            StockTx.unit_cost_input_mode,
        )
        .join(latest_subq, StockTx.pk == latest_subq.c.tx_pk)
        .where(latest_subq.c.row_number == 1)
    )

    on_hand_by_item: Dict[int, float] = {}
    valuation_rows = []

    with Session(_engine(db_name)) as session:
        rows = session.exec(stmt).all() or []

    for row in rows:
        item_id = _safe_int_id(getattr(row, "item_id", None))
        if item_id is None:
            continue

        qty_raw = getattr(row, "valuation_qty_after", None)
        if qty_raw is None:
            return None
        on_hand = _safe_float(qty_raw, 0.0)
        on_hand_by_item[item_id] = on_hand_by_item.get(item_id, 0.0) + on_hand

        valuation_rows.append((
            item_id, on_hand, getattr(row, "valuation_avg_after", None),
            getattr(row, "currency", None), getattr(row, "unit_cost_input_mode", None),
        ))

    return on_hand_by_item, *_summarize_item_valuation_rows(valuation_rows)

def _emit_refresh():
    global _last_refresh_emit_at
    _NAMED_RECORD_ID_CACHE.clear()
    now = time.monotonic()
    if (now - _last_refresh_emit_at) < _STOCK_SIGNAL_DEBOUNCE_SECONDS:
        return
    _last_refresh_emit_at = now
    try:
        stock_signals.refreshed.emit()
    except Exception:
        pass


def _emit_tx_created(tx_id: int) -> None:
    try:
        target_id = int(tx_id or 0)
    except Exception:
        target_id = 0
    if target_id <= 0:
        return
    try:
        stock_signals.tx_created.emit(target_id)
    except Exception:
        pass


def _emit_quick_access_change(section: str, delta: int = 1):
    normalized_section = str(section or "").strip().lower()
    normalized_delta = int(delta or 1)
    now = time.monotonic()
    last_state = _last_quick_access_emit.get(normalized_section)
    if last_state is not None and last_state[0] == normalized_delta and (now - last_state[1]) < _STOCK_SIGNAL_DEBOUNCE_SECONDS:
        return
    _last_quick_access_emit[normalized_section] = (normalized_delta, now)
    try:
        stock_signals.quick_access_changed.emit(normalized_section, normalized_delta)
    except Exception:
        pass

def _fail(code: StockError, error: Exception, detail: str = "", **extra) -> Result:
    return Result.fail(
        map_error_to_message(error),
        error=error,
        close_dialog=False,
        data={"code": str(code), "detail": detail, **extra},
    )

def _ok(msg: str, **data) -> Result:
    return Result.ok(msg, close_dialog=False, data=data)


def _text_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).casefold()


def _ean13_check_digit(base12: str) -> str:
    total = 0
    for idx, ch in enumerate(base12):
        n = int(ch)
        total += n if (idx % 2 == 0) else (n * 3)
    return str((10 - (total % 10)) % 10)


def _random_ean13(prefix: str = "869") -> str:
    p = "".join(ch for ch in str(prefix or "") if ch.isdigit()) or "869"
    p = p[:12]
    missing = 12 - len(p)
    core = p + "".join(str(secrets.randbelow(10)) for _ in range(missing))
    return core + _ean13_check_digit(core)


def _is_barcode_taken(barcode: Optional[str], exclude_id: Optional[int] = None) -> bool:
    code = (barcode or "").strip()
    if not code:
        return False
    stmt = select(StockItem.pk).where(StockItem.barcode == code)
    if exclude_id is not None:
        stmt = stmt.where(StockItem.pk != int(exclude_id))
    stmt = stmt.limit(1)
    with Session(_engine()) as session:
        return session.exec(stmt).first() is not None


def generate_unique_barcode(prefix: str = "869", max_attempts: int = 200) -> Result:
    try:
        attempts = max(1, int(max_attempts))
        for _ in range(attempts):
            candidate = _random_ean13(prefix=prefix)
            if not _is_barcode_taken(candidate):
                return _ok("Benzersiz barkod üretildi.", barcode=candidate)
        return Result.fail(
            "Benzersiz barkod üretilemedi. Lütfen tekrar dene.",
            close_dialog=False,
            data={"attempts": attempts},
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Benzersiz barkod üretilemedi.")

# -------------------------------------------------
# ITEM
# -------------------------------------------------
def create_item(
    sku: str,
    name: str,
    unit: str = "adet",
    item_type: str = StockItemType.physical.value,
    barcode: Optional[str] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
    sub_category: Optional[str] = None,
    model_code: Optional[str] = None,
    manufacturer: Optional[str] = None,
    gtip_code: Optional[str] = None,
    custom_label: Optional[str] = None,
    location_code: Optional[str] = None,
    image_path: Optional[str] = None,
    description: Optional[str] = None,
    note: Optional[str] = None,
    is_active: bool = True,
    min_stock: Optional[float] = None,
    max_stock: Optional[float] = None,
    safety_stock: Optional[float] = None,
    reorder_point: Optional[float] = None,
    reorder_qty: Optional[float] = None,
    lead_time_days: Optional[int] = None,
    shelf_life_days: Optional[int] = None,
    serial_tracking: bool = False,
    lot_tracking: bool = False,
    allow_negative_stock: bool = False,
    vat_rate: Optional[float] = None,
    weight_kg: Optional[float] = None,
    length_cm: Optional[float] = None,
    width_cm: Optional[float] = None,
    height_cm: Optional[float] = None,
) -> Result:
    try:
        barcode = (barcode or "").strip() or None
        brand_name = str(brand or "").strip() or None
        brand_id = _resolve_brand_id(brand_name)
        if barcode and _is_barcode_taken(barcode):
            return Result.fail("Bu barkod zaten başka bir kartta kullanılıyor.", close_dialog=False)

        payload = {
            "sku": sku,
            "name": name,
            "barcode": barcode,
            "item_type": item_type,
            "unit": unit,
            "brand_id": brand_id,
            "brand": brand_name,
            "category": category,
            "sub_category": sub_category,
            "model_code": model_code,
            "manufacturer": manufacturer,
            "gtip_code": gtip_code,
            "custom_label": custom_label,
            "location_code": location_code,
            "image_path": image_path,
            "description": description,
            "note": note,
            "is_active": bool(is_active),
            "min_stock": min_stock,
            "max_stock": max_stock,
            "safety_stock": safety_stock,
            "reorder_point": reorder_point,
            "reorder_qty": reorder_qty,
            "lead_time_days": lead_time_days,
            "shelf_life_days": shelf_life_days,
            "serial_tracking": bool(serial_tracking),
            "lot_tracking": bool(lot_tracking),
            "allow_negative_stock": bool(allow_negative_stock),
            "vat_rate": vat_rate,
            "weight_kg": weight_kg,
            "length_cm": length_cm,
            "width_cm": width_cm,
            "height_cm": height_cm,
            "updated_at": _utcnow_naive(),
            "created_at": _utcnow_naive(),
        }

        res = create_records(
            model=StockItem,
            mode="plain",
            data_list=[payload],
            db_name=_database_name(),
            conflict_keys=["sku"],
            normalizer=item_normalizer,
        )
        if not res.success:
            return res

        _emit_quick_access_change("items", 1)
        _emit_refresh()
        return _ok("Stok kartı başarıyla kaydedildi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Stok kartı oluşturulamadı.")

def update_item(pk: int, update_data: Dict[str, Any]) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)

        update_data = dict(update_data or {})
        if "barcode" in update_data:
            incoming_barcode = update_data.get("barcode")
            incoming_barcode = str(incoming_barcode).strip() if incoming_barcode is not None else ""
            incoming_barcode = incoming_barcode or None
            update_data["barcode"] = incoming_barcode
            if incoming_barcode and _is_barcode_taken(incoming_barcode, exclude_id=int(pk)):
                return Result.fail("Bu barkod zaten başka bir kartta kullanılıyor.", close_dialog=False)
        if "brand" in update_data:
            brand_name = str(update_data.get("brand") or "").strip() or None
            update_data["brand"] = brand_name
            update_data["brand_id"] = _resolve_brand_id(brand_name)
        update_payload, early_result = _prepare_update_payload(
            StockItem,
            pk,
            update_data,
            normalizer=item_normalizer,
        )
        if early_result is not None:
            return early_result

        res = update_records(
            model=StockItem,
            filters={"pk": pk},
            update_data=update_payload,
            db_name=_database_name(),
        )
        if res.success:
            _emit_quick_access_change("items", 1)
            _emit_refresh()
        return res
    except Exception as e:
        return _fail(StockError.db_error, e, "Stok kartı güncellenemedi.")

def delete_item(pk: int, cascade: bool = False) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        tx_count = _stock_tx_count(item_id=int(pk))
        if tx_count > 0:
            if not cascade:
                return Result.fail(
                    "Bu stok kartına bağlı hareketler var. Önce hareketleri silmelisin.",
                    close_dialog=False,
                    data={"tx_count": tx_count, "can_cascade": True},
                )
            delete_records(model=StockTx, filters={"item_id": pk}, db_name=_database_name())

        # Listing domain baglantilarini temizle (orphan eslesme kalmasin).
        try:
            from Listing.models import ListingProduct, ListingProductStockSnapshot  # pylint: disable=import-outside-toplevel

            rel_del = delete_records(model=ListingProductStockSnapshot, filters={"stock_item_id": pk}, db_name=_database_name())
            if not rel_del.success:
                return rel_del

            rel_upd = update_records(
                model=ListingProduct,
                filters={"stock_item_id": pk},
                update_data={"stock_item_id": None, "updated_at": _utcnow_naive()},
                db_name=_database_name(),
            )
            if not rel_upd.success:
                return rel_upd
        except Exception as rel_err:
            return _fail(StockError.db_error, rel_err, "Listing eslesmeleri temizlenemedi.")
        res = delete_records(
            model=StockItem,
            filters={"pk": pk},
            db_name=_database_name(),
        )
        if res.success:
            _emit_quick_access_change("items", 1)
            if cascade and tx_count > 0:
                _emit_quick_access_change("tx", tx_count)
            _emit_refresh()
        return res
    except IntegrityError as e:
        # FK kısıtı: stok hareketi vb. bağlantılı kayıtlar var
        return Result.fail(
            "Bu stok kartına bağlı kayıtlar var. Önce ilişkili hareketleri/siparişleri temizlemelisin.",
            error=e,
            close_dialog=False,
            data={"code": str(StockError.db_error), "detail": "foreign_key"},
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Stok kartı silinemedi.")


def list_items(only_active: bool = True, *, db_name: str | None = None) -> Result:
    try:
        records = _list_stock_items(only_active=only_active, db_name=db_name)

        return _ok(
            f"{len(records)} stok kartı çekildi." if records else "Stok kartı bulunmuyor.",
            records=records,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Stok kartları okunamadı.")

# -------------------------------------------------
# WAREHOUSE
# -------------------------------------------------
def create_warehouse(
    name: str,
    code: Optional[str] = None,
    manager_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    capacity_m3: Optional[float] = None,
    layout_json: Optional[str] = None,
    note: Optional[str] = None,
) -> Result:
    try:
        payload = {
            "name": name,
            "code": code,
            "manager_name": manager_name,
            "phone": phone,
            "email": email,
            "address": address,
            "city": city,
            "country": country,
            "capacity_m3": capacity_m3,
            "layout_json": layout_json,
            "note": note,
            "is_active": True,
            "created_at": _utcnow_naive(),
        }
        res = create_records(
            model=Warehouse,
            mode="plain",
            data_list=[payload],
            db_name=_database_name(),
            conflict_keys=["name"],
            normalizer=warehouse_normalizer,
        )
        if not res.success:
            return res
        _emit_quick_access_change("warehouses", 1)
        _emit_refresh()
        return _ok("Depo başarıyla kaydedildi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Depo oluşturulamadı.")

def update_warehouse(pk: int, update_data: Dict[str, Any]) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        update_payload, early_result = _prepare_update_payload(
            Warehouse,
            pk,
            update_data,
            normalizer=warehouse_normalizer,
        )
        if early_result is not None:
            return early_result
        res = update_records(
            model=Warehouse,
            filters={"pk": pk},
            update_data=update_payload,
            db_name=_database_name(),
        )
        if res.success:
            _emit_quick_access_change("warehouses", 1)
            _emit_refresh()
        return res
    except Exception as e:
        return _fail(StockError.db_error, e, "Depo güncellenemedi.")


def delete_warehouse(pk: int) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        tx_count = _stock_tx_count(warehouse_id=int(pk))
        if tx_count > 0:
            return Result.fail(
                "Bu depoya bağlı stok hareketleri var. Önce ilişkili hareketleri temizlemelisin.",
                close_dialog=False,
                data={"tx_count": tx_count},
            )

        res = delete_records(
            model=Warehouse,
            filters={"pk": pk},
            db_name=_database_name(),
        )
        if res.success:
            _emit_quick_access_change("warehouses", 1)
            _emit_refresh()
        return res
    except IntegrityError as e:
        return Result.fail(
            "Bu depoya bağlı kayıtlar var. Önce ilişkili hareketleri/siparişleri temizlemelisin.",
            error=e,
            close_dialog=False,
            data={"code": str(StockError.db_error), "detail": "foreign_key"},
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Depo silinemedi.")


def list_warehouses(only_active: bool = True) -> Result:
    try:
        records = _list_named_records(Warehouse, only_active=only_active)

        return _ok(
            f"{len(records)} depo çekildi." if records else "Depo bulunmuyor.",
            records=records,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Depolar okunamadı.")

# -------------------------------------------------
# BRAND
# -------------------------------------------------
def create_brand(
    name: str,
    code: Optional[str] = None,
    registration_no: Optional[str] = None,
    country: Optional[str] = None,
    website: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    address: Optional[str] = None,
    note: Optional[str] = None,
) -> Result:
    try:
        payload = {
            "name": (name or "").strip(),
            "code": (code or "").strip() or None,
            "registration_no": (registration_no or "").strip() or None,
            "country": (country or "").strip() or None,
            "website": (website or "").strip() or None,
            "contact_email": (contact_email or "").strip() or None,
            "contact_phone": (contact_phone or "").strip() or None,
            "address": (address or "").strip() or None,
            "note": (note or "").strip() or None,
            "is_active": True,
            "created_at": _utcnow_naive(),
        }
        if not payload["name"]:
            return Result.fail("Marka adı boş olamaz.", close_dialog=False)

        res = create_records(
            model=Brand,
            mode="plain",
            data_list=[payload],
            db_name=_database_name(),
            conflict_keys=["name"],
            normalizer=make_normalizer(strip_strings=True),
        )
        if not res.success:
            return res
        _emit_quick_access_change("brands", 1)
        _emit_refresh()
        return _ok("Marka başarıyla kaydedildi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Marka oluşturulamadı.")


def update_brand(pk: int, update_data: Dict[str, Any]) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        update_payload, early_result = _prepare_update_payload(
            Brand,
            pk,
            update_data,
            normalizer=brand_normalizer,
        )
        if early_result is not None:
            return early_result
        res = update_records(model=Brand, filters={"pk": pk}, update_data=update_payload, db_name=_database_name())
        if res.success:
            refreshed = _get_record(Brand, pk)
            if refreshed is not None:
                _sync_stock_item_brand_labels(
                    brand_id=int(pk),
                    brand_name=str(getattr(refreshed, "name", "") or ""),
                )
            _emit_quick_access_change("brands", 1)
            _emit_refresh()
        return res
    except Exception as e:
        return _fail(StockError.db_error, e, "Marka güncellenemedi.")


def delete_brand(pk: int) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        linked_items = _stock_item_brand_count(int(pk))
        if linked_items > 0:
            return Result.fail(
                "Bu markaya bağlı stok kartları var. Önce ilişkili stok kartlarını güncellemelisin.",
                close_dialog=False,
                data={"item_count": linked_items},
            )
        res = delete_records(model=Brand, filters={"pk": pk}, db_name=_database_name())
        if res.success:
            _emit_quick_access_change("brands", 1)
            _emit_refresh()
        return res
    except Exception as e:
        return _fail(StockError.db_error, e, "Marka silinemedi.")


def list_brands(only_active: bool = True) -> Result:
    try:
        records = _list_named_records(Brand, only_active=only_active)

        return _ok(
            f"{len(records)} marka çekildi." if records else "Marka bulunmuyor.",
            records=records,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Markalar okunamadı.")


# -------------------------------------------------
# SUB GROUP (CATEGORY CHILDREN)
# -------------------------------------------------
def list_upper_groups() -> Result:
    try:
        groups = upper_group_names()
        return _ok(
            f"{len(groups)} üst grup çekildi." if groups else "Üst grup bulunmuyor.",
            records=groups,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Üst gruplar okunamadı.")


def list_upper_group_records() -> Result:
    try:
        rows = upper_group_rows()
        records = [
            SimpleNamespace(
                pk=int((row or {}).get("id") or 0),
                name=str((row or {}).get("name") or ""),
                created_at=str((row or {}).get("created_at") or ""),
                source=str((row or {}).get("source") or "default"),
            )
            for row in rows
        ]
        return _ok(
            f"{len(records)} üst grup çekildi." if records else "Üst grup bulunmuyor.",
            records=records,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Üst grup kayıtları okunamadı.")


def create_upper_group(name: str) -> Result:
    try:
        name = str(name or "").strip()
        if not name:
            return Result.fail("Kategori adı boş olamaz.", close_dialog=False)
        merged = upper_group_names()
        if any(_text_key(existing) == _text_key(name) for existing in merged):
            return Result.fail("Bu kategori zaten var.", close_dialog=False)
        user_rows = user_upper_group_rows()
        user_rows.append(
            {
                "id": next_user_upper_group_id(user_rows),
                "name": name,
                "created_at": _utcnow_naive().isoformat(),
                "source": "user",
            }
        )
        save_user_upper_group_rows(user_rows)
        _emit_refresh()
        return _ok("Kategori başarıyla kaydedildi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Kategori oluşturulamadı.")


def update_upper_group(pk: int, update_data: Dict[str, Any]) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        if int(pk) <= 0:
            return Result.fail("Varsayılan kategori düzenlenemez.", close_dialog=False)
        new_name = str((update_data or {}).get("name") or "").strip()
        if not new_name:
            return Result.fail("Kategori adı boş olamaz.", close_dialog=False)

        user_rows = user_upper_group_rows()
        current_row = None
        current_index = None
        for idx, row in enumerate(user_rows):
            try:
                rid = int((row or {}).get("id"))
            except Exception:
                rid = -1
            if rid == int(pk):
                current_row = dict(row)
                current_index = idx
                break
        if current_row is None or current_index is None:
            return Result.fail("Kayıt bulunamadı.", close_dialog=False)

        old_name = str(current_row.get("name") or "").strip()
        for row in upper_group_rows():
            try:
                rid = int((row or {}).get("id"))
            except Exception:
                rid = -1
            row_name = str((row or {}).get("name") or "").strip()
            if rid != int(pk) and _text_key(row_name) == _text_key(new_name):
                return Result.fail("Bu kategori zaten var.", close_dialog=False)

        current_row["name"] = new_name
        user_rows[current_index] = current_row
        save_user_upper_group_rows(user_rows)

        user_sub_groups = user_sub_group_map()
        if old_name and _text_key(old_name) != _text_key(new_name) and old_name in user_sub_groups:
            moved = user_sub_groups.pop(old_name, [])
            existing = user_sub_groups.get(new_name, [])
            user_sub_groups[new_name] = [*existing, *moved]
            save_user_sub_group_map(user_sub_groups)

        _emit_refresh()
        return _ok("Kategori güncellendi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Kategori güncellenemedi.")


def delete_upper_group(pk: int) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        if int(pk) <= 0:
            return Result.fail("Varsayılan kategori silinemez.", close_dialog=False)

        user_rows = user_upper_group_rows()
        target_row = None
        remaining_rows: list[dict[str, Any]] = []
        for row in user_rows:
            try:
                rid = int((row or {}).get("id"))
            except Exception:
                rid = -1
            if rid == int(pk):
                target_row = dict(row)
                continue
            remaining_rows.append(dict(row))
        if target_row is None:
            return Result.fail("Kayıt bulunamadı.", close_dialog=False)

        category_name = str(target_row.get("name") or "").strip()
        merged_sub_groups = sub_group_map().get(category_name, [])
        if merged_sub_groups:
            return Result.fail("Bu kategoriye bağlı alt gruplar varken silinemez.", close_dialog=False)

        save_user_upper_group_rows(remaining_rows)
        _emit_refresh()
        return _ok("Kategori silindi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Kategori silinemedi.")


def create_sub_group(category: str, name: str, is_active: bool = True) -> Result:
    try:
        category = (category or "").strip()
        name = (name or "").strip()
        if not category:
            return Result.fail("Üst grup boş olamaz.", close_dialog=False)
        if not name:
            return Result.fail("Alt grup adı boş olamaz.", close_dialog=False)

        upper_groups = upper_group_names()
        matched_category = next((g for g in upper_groups if _text_key(g) == _text_key(category)), None)
        if not matched_category:
            return Result.fail("Geçersiz üst grup seçimi.", close_dialog=False)

        data = sub_group_map()
        rows = data.get(matched_category, [])
        for row in rows:
            if _text_key(row.get("name", "")) == _text_key(name):
                return Result.fail("Bu alt grup zaten var.", close_dialog=False)

        user_data = user_sub_group_map()
        user_rows = user_data.get(matched_category, [])
        user_rows.append(
            {
                "id": next_user_sub_group_id(user_data),
                "name": name,
                "is_active": bool(is_active),
                "created_at": _utcnow_naive().isoformat(),
                "source": "user",
            }
        )
        user_data[matched_category] = user_rows
        save_user_sub_group_map(user_data)

        _emit_refresh()
        return _ok("Alt grup başarıyla kaydedildi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Alt grup oluşturulamadı.")


def update_sub_group(pk: int, update_data: Dict[str, Any]) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        if int(pk) <= 0:
            return Result.fail("Varsayılan alt grup düzenlenemez.", close_dialog=False)

        new_category = str((update_data or {}).get("category") or "").strip()
        new_name = str((update_data or {}).get("name") or "").strip()
        if not new_category:
            return Result.fail("Üst grup boş olamaz.", close_dialog=False)
        if not new_name:
            return Result.fail("Alt grup adı boş olamaz.", close_dialog=False)

        user_data = user_sub_group_map()

        found_category = None
        found_idx = None
        found_row = None
        for cat, rows in user_data.items():
            for idx, row in enumerate(rows or []):
                try:
                    rid = int(row.get("id"))
                except Exception:
                    rid = -1
                if rid == int(pk):
                    found_category = cat
                    found_idx = idx
                    found_row = dict(row)
                    break
            if found_row is not None:
                break

        if found_row is None or found_category is None or found_idx is None:
            return Result.fail("Kayıt bulunamadı.", close_dialog=False)

        upper_groups = upper_group_names()
        matched_category = next((g for g in upper_groups if _text_key(g) == _text_key(new_category)), None)
        if not matched_category:
            return Result.fail("Geçersiz üst grup seçimi.", close_dialog=False)

        merged = sub_group_map()
        target_rows = merged.get(matched_category, [])
        for row in target_rows:
            try:
                rid = int(row.get("id"))
            except Exception:
                rid = -1
            if rid != int(pk) and _text_key(row.get("name", "")) == _text_key(new_name):
                return Result.fail("Bu alt grup zaten var.", close_dialog=False)

        user_data[found_category].pop(found_idx)
        if not user_data[found_category]:
            user_data.pop(found_category, None)

        found_row["name"] = new_name
        found_row["is_active"] = bool((update_data or {}).get("is_active", found_row.get("is_active", True)))
        found_row["source"] = "user"
        user_data.setdefault(matched_category, []).append(found_row)
        save_user_sub_group_map(user_data)

        _emit_refresh()
        return _ok("Alt grup güncellendi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Alt grup güncellenemedi.")


def delete_sub_group(pk: int) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        if int(pk) <= 0:
            return Result.fail("Varsayılan alt grup silinemez.", close_dialog=False)

        user_data = user_sub_group_map()
        removed = False
        for cat in list(user_data.keys()):
            rows = user_data.get(cat, [])
            new_rows = []
            for row in rows:
                try:
                    rid = int(row.get("id"))
                except Exception:
                    rid = -1
                if rid == int(pk):
                    removed = True
                    continue
                new_rows.append(row)
            if new_rows:
                user_data[cat] = new_rows
            else:
                user_data.pop(cat, None)
        if not removed:
            return Result.fail("Kayıt bulunamadı.", close_dialog=False)
        save_user_sub_group_map(user_data)
        _emit_refresh()
        return _ok("Alt grup silindi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Alt grup silinemedi.")


def list_sub_groups(category: Optional[str] = None, only_active: bool = True) -> Result:
    try:
        cat = (category or "").strip()
        data = sub_group_map()
        records = []
        categories = list(data.keys())
        if cat:
            matched = next((name for name in categories if _text_key(name) == _text_key(cat)), None)
            categories = [matched] if matched else []
        for c in categories:
            rows = data.get(c, [])
            for row in rows:
                is_active = bool(row.get("is_active", True))
                if only_active and not is_active:
                    continue
                records.append(
                    SimpleNamespace(
                        pk=int(row.get("id")),
                        category=c,
                        name=str(row.get("name") or ""),
                        is_active=is_active,
                        created_at=str(row.get("created_at") or ""),
                        source=str(row.get("source") or "user"),
                    )
                )

        records = sorted(records, key=lambda x: (_text_key(x.category), _text_key(x.name)))

        return _ok(
            f"{len(records)} alt grup çekildi." if records else "Alt grup bulunmuyor.",
            records=records,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Alt gruplar okunamadı.")


# -------------------------------------------------
# COMPANY / COUNTERPARTY
# -------------------------------------------------
def create_company(name: str, **kwargs) -> Result:
    try:
        payload = {
            "name": (name or "").strip(),
            "tax_no": (kwargs.get("tax_no") or "").strip() or None,
            "phone": (kwargs.get("phone") or "").strip() or None,
            "email": (kwargs.get("email") or "").strip() or None,
            "address": (kwargs.get("address") or "").strip() or None,
            "note": (kwargs.get("note") or "").strip() or None,
            "is_active": True,
            "created_at": _utcnow_naive(),
        }
        if not payload["name"]:
            return Result.fail("Şirket adı boş olamaz.", close_dialog=False)

        res = create_records(
            model=Company,
            mode="plain",
            data_list=[payload],
            db_name=_database_name(),
            conflict_keys=["name"],
            normalizer=make_normalizer(strip_strings=True),
        )
        if not res.success:
            return res
        _emit_quick_access_change("companies", 1)
        _emit_refresh()
        return _ok("Şirket başarıyla kaydedildi.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Şirket oluşturulamadı.")


def update_company(pk: int, update_data: Dict[str, Any]) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        update_payload, early_result = _prepare_update_payload(
            Company,
            pk,
            update_data,
            normalizer=company_normalizer,
        )
        if early_result is not None:
            return early_result
        res = update_records(model=Company, filters={"pk": pk}, update_data=update_payload, db_name=_database_name())
        if res.success:
            refreshed = _get_record(Company, pk)
            if refreshed is not None:
                _sync_stock_tx_company_labels(
                    company_id=int(pk),
                    company_name=str(getattr(refreshed, "name", "") or ""),
                )
            _emit_quick_access_change("companies", 1)
            _emit_refresh()
        return res
    except Exception as e:
        return _fail(StockError.db_error, e, "Şirket güncellenemedi.")


def delete_company(pk: int) -> Result:
    try:
        if not pk:
            return Result.fail("Geçersiz id.", close_dialog=False)
        linked_txs = _stock_tx_company_count(int(pk))
        if linked_txs > 0:
            return Result.fail(
                "Bu muhataba bağlı stok hareketleri var. Önce ilişkili hareketleri güncellemelisin.",
                close_dialog=False,
                data={"tx_count": linked_txs},
            )
        res = delete_records(model=Company, filters={"pk": pk}, db_name=_database_name())
        if res.success:
            _emit_quick_access_change("companies", 1)
            _emit_refresh()
        return res
    except Exception as e:
        return _fail(StockError.db_error, e, "Şirket silinemedi.")


def list_companies(only_active: bool = True) -> Result:
    try:
        records = _list_named_records(Company, only_active=only_active)

        return _ok(
            f"{len(records)} şirket çekildi." if records else "Şirket bulunmuyor.",
            records=records,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Şirketler okunamadı.")

# -------------------------------------------------
# ON HAND
# -------------------------------------------------
def get_on_hand(item_id: int, warehouse_id: Optional[int] = None) -> Result:
    try:
        stmt = select(
            func.coalesce(
                func.sum(
                    case((StockTx.direction == StockTxDirection.IN_, StockTx.qty), else_=0.0)
                ),
                0.0,
            ),
            func.coalesce(
                func.sum(
                    case((StockTx.direction == StockTxDirection.OUT, StockTx.qty), else_=0.0)
                ),
                0.0,
            ),
        ).where(StockTx.item_id == int(item_id))
        if warehouse_id is not None:
            stmt = stmt.where(StockTx.warehouse_id == int(warehouse_id))

        with Session(_engine()) as session:
            row = session.exec(stmt).one()
        total_in = float((row[0] if row else 0.0) or 0.0)
        total_out = float((row[1] if row else 0.0) or 0.0)
        on_hand = total_in - total_out
        return _ok("Stok hesaplandı.", on_hand=on_hand, total_in=total_in, total_out=total_out)
    except Exception as e:
        return _fail(StockError.db_error, e, "Stok hesaplanamadı.")

# -------------------------------------------------
# TX
# -------------------------------------------------
def _is_duplicate_ref(reference_type: StockReferenceType, reference_id: Optional[str], item_id: int) -> bool:
    if reference_type == StockReferenceType.none or not reference_id:
        return False
    res = get_records(
        model=StockTx,
        db_engine=_engine(),
        filters={"reference_type": reference_type, "reference_id": reference_id, "item_id": item_id},
    )
    if not res.success:
        return False
    return bool(res.data.get("records", []) or [])


def _tx_time_sort_key(tx: StockTx) -> tuple[datetime, datetime, int]:
    occurred = getattr(tx, "occurred_at", None) or datetime.min
    created = getattr(tx, "created_at", None) or datetime.min
    try:
        tx_id = int(getattr(tx, "pk", 0) or 0)
    except Exception:
        tx_id = 0
    return occurred, created, tx_id


def _coerce_direction(value: Any) -> StockTxDirection:
    if value == StockTxDirection.IN_:
        return StockTxDirection.IN_
    if value == StockTxDirection.OUT:
        return StockTxDirection.OUT
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().upper()
    if text == "OUT" or text.endswith(".OUT") or text.endswith("OUT"):
        return StockTxDirection.OUT
    if (
        text in {"IN", "IN_"}
        or text.endswith(".IN_")
        or text.endswith("IN_")
        or text.endswith("IN")
    ):
        return StockTxDirection.IN_
    return StockTxDirection.IN_


def _parse_direction_filter(value: Any) -> Optional[StockTxDirection]:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().upper()
    if not text:
        return None
    if text == "OUT" or text.endswith(".OUT") or text.endswith("OUT"):
        return StockTxDirection.OUT
    if text in {"IN", "IN_"} or text.endswith(".IN_") or text.endswith("IN_"):
        return StockTxDirection.IN_
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_currency(value: Any, default: str = "TRY") -> str:
    cur = str(value or "").strip().upper()
    return cur or default


def _normalize_unit_cost_input_mode(value: Any) -> Optional[str]:
    raw = str(value or "").strip().casefold()
    if not raw:
        return None
    if raw in {"gross", "vat_included", "included", "kdv_dahil", "kdv dahil"}:
        return UNIT_COST_INPUT_MODE_GROSS
    if raw in {"net", "vat_excluded", "excluded", "kdv_haric", "kdv haric", "kdv hariç"}:
        return UNIT_COST_INPUT_MODE_NET
    if raw in {"mixed", "mixed_explicit"}:
        return UNIT_COST_INPUT_MODE_MIXED
    if raw in {"legacy", "unknown"}:
        return UNIT_COST_INPUT_MODE_LEGACY
    return None


def _merge_unit_cost_input_modes(current_mode: Optional[str], incoming_mode: Optional[str]) -> Optional[str]:
    current = _normalize_unit_cost_input_mode(current_mode)
    incoming = _normalize_unit_cost_input_mode(incoming_mode)
    if current is None:
        return incoming or UNIT_COST_INPUT_MODE_LEGACY
    if incoming is None:
        return UNIT_COST_INPUT_MODE_LEGACY
    if current == incoming:
        return current
    if UNIT_COST_INPUT_MODE_LEGACY in {current, incoming}:
        return UNIT_COST_INPUT_MODE_LEGACY
    return UNIT_COST_INPUT_MODE_MIXED


def _resolve_item_vat_rate(item_id: Any) -> Optional[float]:
    try:
        item_key = int(item_id)
    except Exception:
        return None
    if item_key <= 0:
        return None

    item_res = get_records(model=StockItem, db_engine=_engine(), filters={"pk": item_key})
    if not item_res.success:
        return None
    rows = (item_res.data or {}).get("records", []) or []
    if not rows:
        return None
    vat_rate = getattr(rows[0], "vat_rate", None)
    vat_value = _safe_float(vat_rate, -1.0) if vat_rate is not None else -1.0
    return vat_value if vat_value >= 0 else None


def _gross_amount_from_unit_cost(
    amount: Any,
    *,
    input_mode: Optional[str],
    vat_rate: Optional[float],
) -> Optional[float]:
    amount_val = _safe_float(amount, -1.0) if amount is not None else -1.0
    if amount_val <= 0:
        return None

    normalized_mode = _normalize_unit_cost_input_mode(input_mode) or UNIT_COST_INPUT_MODE_GROSS
    if normalized_mode != UNIT_COST_INPUT_MODE_NET:
        return amount_val

    vat_value = _safe_float(vat_rate, -1.0) if vat_rate is not None else -1.0
    if vat_value < 0:
        return None
    return amount_val * (1.0 + (vat_value / 100.0))


def _local_now_naive() -> datetime:
    # Uygulama UI'da lokal saat gösteriyor; DB kaydini da lokal-naive tutuyoruz.
    return datetime.now()


def _to_local_naive(value: Optional[datetime]) -> datetime:
    if not isinstance(value, datetime):
        return _local_now_naive()
    if value.tzinfo is not None:
        try:
            return value.astimezone().replace(tzinfo=None)
        except Exception:
            return value.replace(tzinfo=None)
    return value


def _replay_moving_average_state(
    txs: Iterable[StockTx],
    *,
    warehouse_id: Optional[int] = None,
) -> Dict[tuple[int, int], dict[str, Any]]:
    """
    Perpetual (hareketli) ortalama maliyet replay.
    state payload:
      {
        "on_hand": float,
        "avg_unit_cost": Optional[float],
        "currency": str,
        "unit_cost_input_mode": Optional[str],
      }
    """
    states: Dict[tuple[int, int], dict[str, Any]] = {}
    ordered = sorted(list(txs or []), key=_tx_time_sort_key)

    for tx in ordered:
        try:
            item_id = int(getattr(tx, "item_id", 0) or 0)
            wh_id = int(getattr(tx, "warehouse_id", 0) or 0)
        except Exception:
            continue
        if item_id <= 0 or wh_id <= 0:
            continue
        if warehouse_id is not None and wh_id != int(warehouse_id):
            continue

        qty = _safe_float(getattr(tx, "qty", 0), 0.0)
        if qty <= 0:
            continue

        key = (item_id, wh_id)
        state = states.setdefault(
            key,
            {
                "on_hand": 0.0,
                "avg_unit_cost": None,
                "currency": "TRY",
                "unit_cost_input_mode": None,
            },
        )
        on_hand = _safe_float(state.get("on_hand", 0.0), 0.0)
        avg_unit_cost_raw = state.get("avg_unit_cost")
        avg_unit_cost = _safe_float(avg_unit_cost_raw, -1.0) if avg_unit_cost_raw is not None else None
        if avg_unit_cost is not None and avg_unit_cost <= 0:
            avg_unit_cost = None
        state_currency = _normalize_currency(state.get("currency"), "TRY")
        state_input_mode = _normalize_unit_cost_input_mode(state.get("unit_cost_input_mode"))

        direction = _coerce_direction(getattr(tx, "direction", None))
        tx_cost_raw = getattr(tx, "unit_cost", None)
        tx_cost = _safe_float(tx_cost_raw, -1.0) if tx_cost_raw is not None else -1.0
        tx_cost = tx_cost if tx_cost > 0 else None
        tx_currency = _normalize_currency(getattr(tx, "currency", None), state_currency)
        tx_input_mode = _normalize_unit_cost_input_mode(getattr(tx, "unit_cost_input_mode", None))

        if direction == StockTxDirection.IN_:
            remaining_in = qty

            # Once inventory is negative, incoming quantity first closes negative balance.
            if on_hand < -1e-9 and remaining_in > 1e-9:
                cover_qty = min(remaining_in, abs(on_hand))
                on_hand += cover_qty
                remaining_in -= cover_qty
                if on_hand <= 1e-9:
                    avg_unit_cost = None
                    state_input_mode = None

            # Remaining IN creates/updates active moving-average layer only when stock is positive.
            if remaining_in > 1e-9:
                if on_hand <= 1e-9:
                    on_hand += remaining_in
                    if tx_cost is not None:
                        avg_unit_cost = tx_cost
                        state_currency = tx_currency
                        state_input_mode = tx_input_mode or UNIT_COST_INPUT_MODE_LEGACY
                    else:
                        avg_unit_cost = None
                        state_input_mode = None
                else:
                    if tx_cost is None:
                        on_hand += remaining_in
                    else:
                        if avg_unit_cost is None:
                            avg_unit_cost = tx_cost
                            state_currency = tx_currency
                            state_input_mode = tx_input_mode or UNIT_COST_INPUT_MODE_LEGACY
                            on_hand += remaining_in
                        else:
                            new_on_hand = on_hand + remaining_in
                            if new_on_hand > 1e-9:
                                avg_unit_cost = ((on_hand * avg_unit_cost) + (remaining_in * tx_cost)) / new_on_hand
                                state_input_mode = _merge_unit_cost_input_modes(state_input_mode, tx_input_mode)
                            on_hand = new_on_hand
        else:
            on_hand -= qty
            if on_hand <= 1e-9:
                if abs(on_hand) <= 1e-9:
                    on_hand = 0.0
                avg_unit_cost = None
                state_input_mode = None

        state["on_hand"] = on_hand
        state["avg_unit_cost"] = avg_unit_cost if (avg_unit_cost is not None and avg_unit_cost > 0) else None
        state["currency"] = state_currency
        state["unit_cost_input_mode"] = state_input_mode

    return states


def _build_active_stock_state_map(
    txs: Iterable[StockTx],
    *,
    warehouse_id: Optional[int] = None,
) -> Dict[tuple[int, int], dict[str, Any]]:
    return _replay_moving_average_state(txs, warehouse_id=warehouse_id)


def _state_numeric_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    qty_before = _safe_float(state.get("on_hand"), 0.0)
    avg_before_raw = state.get("avg_unit_cost")
    avg_before = _safe_float(avg_before_raw, -1.0) if avg_before_raw is not None else -1.0
    if avg_before <= 0:
        avg_before = None
    currency = _normalize_currency(state.get("currency"), "TRY")
    if avg_before is not None and qty_before > 0:
        stock_value_before = qty_before * avg_before
    else:
        stock_value_before = 0.0
    return {
        "qty_before": qty_before,
        "avg_before": avg_before,
        "stock_value_before": stock_value_before,
        "currency": currency,
        "unit_cost_input_mode": _normalize_unit_cost_input_mode(state.get("unit_cost_input_mode")),
    }


def _get_item_wh_moving_average_state(*, item_id: int, warehouse_id: int) -> Result:
    try:
        tx_rows = _list_txs_query(item_id=int(item_id), warehouse_id=int(warehouse_id))
    except Exception as e:
        return _fail(StockError.db_error, e, "Hareketli ortalama durum snapshot hazırlanamadı.")
    states = _build_active_stock_state_map(tx_rows, warehouse_id=int(warehouse_id))
    state = states.get((int(item_id), int(warehouse_id)), {})
    snap = _state_numeric_snapshot(state)
    return _ok(
        "Hareketli ortalama durum snapshot hazır.",
        **snap,
    )


def _plan_moving_average_out_context(item_id: int, warehouse_id: int, qty: float) -> Result:
    qty_val = _safe_float(qty, 0.0)
    if qty_val <= 0:
        return _ok(
            "Maliyet bağlamı gerekmiyor.",
            allocated_qty=0.0,
            unallocated_qty=0.0,
            moving_avg_unit_cost=None,
            currency="TRY",
            unit_cost_input_mode=None,
            on_hand=0.0,
            qty_before=0.0,
            qty_after=0.0,
            avg_before=None,
            avg_after=None,
            stock_value_before=0.0,
            stock_value_after=0.0,
            cost_source="moving_avg_auto",
        )

    state_res = _get_item_wh_moving_average_state(item_id=int(item_id), warehouse_id=int(warehouse_id))
    if not state_res.success:
        return state_res
    state_data = state_res.data or {}
    on_hand = _safe_float(state_data.get("qty_before"), 0.0)
    available_qty = max(0.0, on_hand)
    allocated_qty = min(qty_val, available_qty)
    unallocated_qty = max(0.0, qty_val - allocated_qty)
    moving_avg_unit_cost = state_data.get("avg_before")
    currency = _normalize_currency(state_data.get("currency"), "TRY")

    qty_after = on_hand - qty_val
    if qty_after > 1e-9 and moving_avg_unit_cost is not None:
        avg_after = moving_avg_unit_cost
        stock_value_after = qty_after * avg_after
    else:
        avg_after = None
        stock_value_after = 0.0

    return _ok(
        "Hareketli ortalama maliyet bağlamı hazırlandı.",
        allocated_qty=allocated_qty,
        unallocated_qty=unallocated_qty,
        moving_avg_unit_cost=moving_avg_unit_cost,
        currency=currency,
        unit_cost_input_mode=_normalize_unit_cost_input_mode(state_data.get("unit_cost_input_mode")),
        on_hand=on_hand,
        qty_before=on_hand,
        qty_after=qty_after,
        avg_before=moving_avg_unit_cost,
        avg_after=avg_after,
        stock_value_before=_safe_float(state_data.get("stock_value_before"), 0.0),
        stock_value_after=stock_value_after,
        cost_source="moving_avg_auto",
    )


def _plan_moving_average_in_context(
    *,
    item_id: int,
    warehouse_id: int,
    qty: float,
    tx_unit_cost: Optional[float],
    tx_currency: Optional[str],
) -> Result:
    qty_val = _safe_float(qty, 0.0)
    if qty_val <= 0:
        return _ok(
            "Maliyet bağlamı gerekmiyor.",
            qty_before=0.0,
            qty_after=0.0,
            avg_before=None,
            avg_after=None,
            stock_value_before=0.0,
            stock_value_after=0.0,
            currency=_normalize_currency(tx_currency, "TRY"),
            cost_source="manual_in",
        )

    state_res = _get_item_wh_moving_average_state(item_id=int(item_id), warehouse_id=int(warehouse_id))
    if not state_res.success:
        return state_res
    state_data = state_res.data or {}
    qty_before = _safe_float(state_data.get("qty_before"), 0.0)
    avg_before_raw = state_data.get("avg_before")
    avg_before = _safe_float(avg_before_raw, -1.0) if avg_before_raw is not None else -1.0
    if avg_before <= 0:
        avg_before = None
    currency_before = _normalize_currency(state_data.get("currency"), "TRY")

    in_cost = _safe_float(tx_unit_cost, -1.0) if tx_unit_cost is not None else -1.0
    in_cost = in_cost if in_cost > 0 else None
    in_currency = _normalize_currency(tx_currency, currency_before)

    qty_after = qty_before + qty_val
    avg_after: Optional[float] = None
    currency_after = currency_before

    # Negative/zero stock has no active moving-average layer.
    if qty_after <= 1e-9:
        avg_after = None
        currency_after = currency_before
    elif qty_before <= 1e-9:
        # Incoming first closes negative/zero balance; only positive remainder starts avg layer.
        if in_cost is not None:
            avg_after = in_cost
            currency_after = in_currency
        else:
            avg_after = None
            currency_after = currency_before
    else:
        if in_cost is None:
            avg_after = avg_before
            currency_after = currency_before
        elif avg_before is None:
            avg_after = in_cost
            currency_after = in_currency
        elif qty_after > 1e-9:
            avg_after = ((qty_before * avg_before) + (qty_val * in_cost)) / qty_after
            currency_after = in_currency

    stock_value_before = _safe_float(state_data.get("stock_value_before"), 0.0)
    if avg_after is not None and qty_after > 0:
        stock_value_after = qty_after * avg_after
    else:
        stock_value_after = 0.0

    return _ok(
        "Hareketli ortalama giriş maliyet bağlamı hazırlandı.",
        qty_before=qty_before,
        qty_after=qty_after,
        avg_before=avg_before,
        avg_after=avg_after,
        stock_value_before=stock_value_before,
        stock_value_after=stock_value_after,
        currency=currency_after,
        cost_source="manual_in",
    )


def _is_missing_unit_cost(value: Any) -> bool:
    if value is None:
        return True
    try:
        return float(value) <= 0
    except Exception:
        return True


def _build_backfill_note(note: Optional[str]) -> str:
    base = str(note or "").strip()
    marker = "negatif stok bakiyesi"
    if not base:
        return marker
    if marker in base.casefold():
        return base
    return f"{base} | {marker}"


def _backfill_missing_out_costs(
    *,
    session: Session,
    item_id: int,
    warehouse_id: int,
    incoming_qty: float,
    incoming_unit_cost: Optional[float],
    incoming_currency: Optional[str],
) -> dict[str, Any]:
    """
    Fills unit_cost for historical OUT rows that were created while stock was negative
    (i.e. cost could not be determined at that moment).
    Backfill is FIFO on OUT occurred_at/id order.
    """
    qty_budget = _safe_float(incoming_qty, 0.0)
    unit_cost_val = _safe_float(incoming_unit_cost, -1.0) if incoming_unit_cost is not None else -1.0
    if qty_budget <= 1e-9 or unit_cost_val <= 0:
        return {
            "backfilled_qty": 0.0,
            "backfilled_tx_count": 0,
            "split_rows": 0,
        }

    cur = _normalize_currency(incoming_currency, "TRY")
    stmt = (
        select(StockTx)
        .where(StockTx.item_id == int(item_id))
        .where(StockTx.warehouse_id == int(warehouse_id))
        .where(StockTx.direction == StockTxDirection.OUT)
        .where(or_(StockTx.unit_cost == None, StockTx.unit_cost <= 0))  # noqa: E711
        .order_by(StockTx.occurred_at, StockTx.created_at, StockTx.pk)
    )
    rows = list(session.exec(stmt).all() or [])

    remaining = qty_budget
    backfilled_qty = 0.0
    backfilled_tx_count = 0
    split_rows = 0

    for tx in rows:
        if remaining <= 1e-9:
            break
        tx_qty = _safe_float(getattr(tx, "qty", 0), 0.0)
        if tx_qty <= 1e-9:
            continue

        fill_qty = min(tx_qty, remaining)
        if fill_qty <= 1e-9:
            continue

        if fill_qty >= tx_qty - 1e-9:
            tx.unit_cost = unit_cost_val
            tx.currency = cur
            tx.valuation_cost_source = "negative_backfill"
            backfilled_qty += tx_qty
            backfilled_tx_count += 1
            remaining -= tx_qty
            continue

        # Partial coverage: split row into priced+unpriced OUT rows.
        original_note = getattr(tx, "note", None)
        leftover_qty = max(0.0, tx_qty - fill_qty)

        tx.qty = fill_qty
        tx.unit_cost = unit_cost_val
        tx.currency = cur
        tx.valuation_cost_source = "negative_backfill_split"
        backfilled_qty += fill_qty
        backfilled_tx_count += 1
        remaining = 0.0

        if leftover_qty > 1e-9:
            residual_payload = {
                "item_id": int(getattr(tx, "item_id", item_id) or item_id),
                "warehouse_id": int(getattr(tx, "warehouse_id", warehouse_id) or warehouse_id),
                "direction": _coerce_direction(getattr(tx, "direction", StockTxDirection.OUT)),
                "reason": getattr(tx, "reason", StockTxReason.manual_out),
                "qty": leftover_qty,
                "occurred_at": _to_local_naive(getattr(tx, "occurred_at", None)),
                "created_at": _to_local_naive(getattr(tx, "created_at", None)),
                "unit_cost": None,
                "currency": cur,
                "valuation_method": getattr(tx, "valuation_method", "moving_avg"),
                "valuation_calc_version": getattr(tx, "valuation_calc_version", 1),
                "valuation_cost_source": "negative_pending",
                "valuation_qty_before": getattr(tx, "valuation_qty_before", None),
                "valuation_qty_after": getattr(tx, "valuation_qty_after", None),
                "valuation_stock_value_before": getattr(tx, "valuation_stock_value_before", None),
                "valuation_stock_value_after": getattr(tx, "valuation_stock_value_after", None),
                "valuation_avg_before": getattr(tx, "valuation_avg_before", None),
                "valuation_avg_after": getattr(tx, "valuation_avg_after", None),
                # Keep duplicate-safe, this row is internal residual.
                "reference_type": StockReferenceType.none,
                "reference_id": None,
                "note": _build_backfill_note(original_note),
                "created_by": getattr(tx, "created_by", None),
                "counterparty": getattr(tx, "counterparty", None),
                "attachments": getattr(tx, "attachments", None),
            }
            residual_payload = tx_normalizer(residual_payload)
            session.add(StockTx(**residual_payload))
            split_rows += 1
        break

    return {
        "backfilled_qty": backfilled_qty,
        "backfilled_tx_count": backfilled_tx_count,
        "split_rows": split_rows,
    }


def _order_item_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _build_order_ref_id(
    *,
    api_account_id: int,
    order_number: str,
    product_code: str,
    barcode: str,
    stock_code: str,
) -> str:
    source = "|".join(
        [
            str(api_account_id),
            str(order_number or "").strip(),
            str(product_code or "").strip(),
            str(barcode or "").strip(),
            str(stock_code or "").strip(),
        ]
    )
    digest = hashlib.sha1(source.encode("utf-8", errors="ignore"), usedforsecurity=False).hexdigest()[:32]
    return f"ordauto:{digest}"


def _is_created_order_status(*values: Any) -> bool:
    normalized_values = {
        str(value or "").strip().casefold().replace(" ", "")
        for value in values
        if str(value or "").strip()
    }
    if not normalized_values:
        return False
    return any(value in {"created", "readytoship"} for value in normalized_values)


def auto_deduct_order_items(order_item_list: list[dict], *, created_by: Optional[str] = "orders:auto") -> Result:
    """
    Order item listesinden listing eslesmesi yapar ve stock item'lar icin otomatik order_out tx olusturur.
    - Idempotency: reference_type=order + deterministic reference_id
    - Unit cost: aktif havuz hareketli ortalama maliyet
    """
    try:
        raw_items = list(order_item_list or [])
        if not raw_items:
            return _ok(
                "Order item bulunamadi, stok dusumu atlandi.",
                processed_lines=0,
                matched_lines=0,
                tx_created=0,
                tx_duplicate=0,
                tx_failed=0,
                unmatched_lines=0,
            )

        # Late import to keep domain coupling narrow at import-time.
        from Listing.models import ListingProduct, ListingProductStockSnapshot  # pylint: disable=import-outside-toplevel

        normalized: Dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in raw_items:
            order_number = str(_order_item_get(row, "orderNumber", "") or "").strip()
            if not order_number:
                continue

            try:
                api_account_id = int(_order_item_get(row, "api_account_id"))
            except Exception:
                continue
            if api_account_id <= 0:
                continue

            qty = _safe_float(_order_item_get(row, "quantity", 0), 0.0)
            if qty <= 0:
                continue

            if not _is_created_order_status(
                _order_item_get(row, "orderLineItemStatusName", None),
                _order_item_get(row, "shipmentPackageStatus", None),
                _order_item_get(row, "status", None),
            ):
                continue

            product_code = str(_order_item_get(row, "productCode", "") or "").strip()
            if product_code == "0":
                product_code = ""
            barcode = str(_order_item_get(row, "barcode", "") or "").strip()
            stock_code = str(_order_item_get(row, "merchantSku", "") or _order_item_get(row, "sku", "") or "").strip()
            platform_name = str(_order_item_get(row, "platform", "") or "").strip()

            key = (
                api_account_id,
                order_number,
                _text_key(product_code),
                _text_key(barcode),
                _text_key(stock_code),
            )
            bucket = normalized.get(key)
            if bucket is None:
                bucket = {
                    "api_account_id": api_account_id,
                    "order_number": order_number,
                    "product_code": product_code,
                    "barcode": barcode,
                    "stock_code": stock_code,
                    "platform": platform_name,
                    "qty": 0.0,
                }
                normalized[key] = bucket
            bucket["qty"] = _safe_float(bucket.get("qty", 0.0), 0.0) + qty

        lines = list(normalized.values())
        if not lines:
            return _ok(
                "Created durumunda ge?erli order item bulunamad?, stok d???m? atland?.",
                processed_lines=0,
                matched_lines=0,
                tx_created=0,
                tx_duplicate=0,
                tx_failed=0,
                unmatched_lines=0,
            )

        account_ids = sorted({int(line["api_account_id"]) for line in lines})
        order_numbers_by_acc: Dict[int, set[str]] = {}
        for line in lines:
            acc_id = int(line["api_account_id"])
            order_numbers_by_acc.setdefault(acc_id, set()).add(str(line["order_number"]))

        # api_account -> platform map (muhatap alanina yazmak icin)
        platform_by_acc: Dict[int, str] = {}
        try:
            from Account.models.models import ApiAccount  # pylint: disable=import-outside-toplevel

            with Session(_engine()) as session:
                stmt = select(ApiAccount.pk, ApiAccount.platform).where(ApiAccount.pk.in_(account_ids))
                for row in list(session.exec(stmt).all() or []):
                    try:
                        acc_id = int(row[0] or 0)
                    except Exception:
                        continue
                    if acc_id <= 0:
                        continue
                    platform = str(row[1] or "").strip()
                    if platform:
                        platform_by_acc[acc_id] = platform
        except Exception:
            platform_by_acc = {}

        order_header_pk_by_key: Dict[tuple[int, str], int] = {}
        try:
            from Orders.models.trendyol.models import OrderHeader  # pylint: disable=import-outside-toplevel

            with Session(_engine()) as session:
                for acc_id, order_numbers in order_numbers_by_acc.items():
                    normalized_order_numbers = sorted({str(value).strip() for value in order_numbers if str(value).strip()})
                    if not normalized_order_numbers:
                        continue
                    stmt = (
                        select(OrderHeader.pk, OrderHeader.orderNumber)
                        .where(OrderHeader.api_account_id == acc_id)
                        .where(OrderHeader.orderNumber.in_(normalized_order_numbers))
                    )
                    for row in list(session.exec(stmt).all() or []):
                        try:
                            order_header_pk = int(row[0] or 0)
                        except Exception:
                            continue
                        order_number = str(row[1] or "").strip()
                        if order_header_pk > 0 and order_number:
                            order_header_pk_by_key[(acc_id, order_number)] = order_header_pk
        except Exception:
            order_header_pk_by_key = {}

        product_codes_by_acc: Dict[int, set[str]] = {}
        barcodes_by_acc: Dict[int, set[str]] = {}
        stock_codes_by_acc: Dict[int, set[str]] = {}
        for line in lines:
            acc_id = int(line["api_account_id"])
            if line["product_code"]:
                product_codes_by_acc.setdefault(acc_id, set()).add(str(line["product_code"]))
            if line["barcode"]:
                barcodes_by_acc.setdefault(acc_id, set()).add(str(line["barcode"]))
            if line["stock_code"]:
                stock_codes_by_acc.setdefault(acc_id, set()).add(str(line["stock_code"]))

        listing_rows: list[ListingProduct] = []
        with Session(_engine()) as session:
            for acc_id in account_ids:
                conds = []
                prod_codes = sorted(product_codes_by_acc.get(acc_id, set()))
                barcodes = sorted(barcodes_by_acc.get(acc_id, set()))
                stock_codes = sorted(stock_codes_by_acc.get(acc_id, set()))

                if prod_codes:
                    conds.append(ListingProduct.product_code.in_(prod_codes))
                if barcodes:
                    conds.append(ListingProduct.barcode.in_(barcodes))
                if stock_codes:
                    conds.append(ListingProduct.stock_code.in_(stock_codes))
                if not conds:
                    continue

                stmt = (
                    select(ListingProduct)
                    .where(ListingProduct.api_account_id == acc_id)
                    .where(or_(*conds))
                    .order_by(ListingProduct.updated_at.desc(), ListingProduct.pk.desc())
                )
                listing_rows.extend(list(session.exec(stmt).all()))

        by_product_code: Dict[tuple[int, str], Any] = {}
        by_barcode: Dict[tuple[int, str], Any] = {}
        by_stock_code: Dict[tuple[int, str], Any] = {}
        for lp in listing_rows:
            try:
                acc_id = int(getattr(lp, "api_account_id", 0) or 0)
            except Exception:
                continue
            if acc_id <= 0:
                continue

            pc_key = _text_key(getattr(lp, "product_code", None))
            bc_key = _text_key(getattr(lp, "barcode", None))
            sc_key = _text_key(getattr(lp, "stock_code", None))
            if pc_key and (acc_id, pc_key) not in by_product_code:
                by_product_code[(acc_id, pc_key)] = lp
            if bc_key and (acc_id, bc_key) not in by_barcode:
                by_barcode[(acc_id, bc_key)] = lp
            if sc_key and (acc_id, sc_key) not in by_stock_code:
                by_stock_code[(acc_id, sc_key)] = lp

        resolved_lines: list[dict[str, Any]] = []
        unmatched_lines: list[dict[str, Any]] = []
        for line in lines:
            acc_id = int(line["api_account_id"])
            lp = None
            pc_key = _text_key(line.get("product_code"))
            bc_key = _text_key(line.get("barcode"))
            sc_key = _text_key(line.get("stock_code"))

            if pc_key:
                lp = by_product_code.get((acc_id, pc_key))
            if lp is None and bc_key:
                lp = by_barcode.get((acc_id, bc_key))
            if lp is None and sc_key:
                lp = by_stock_code.get((acc_id, sc_key))

            if lp is None:
                unmatched_lines.append(line)
                continue

            line["listing"] = lp
            resolved_lines.append(line)

        if not resolved_lines:
            return _ok(
                "Order item bulundu ancak listing eslesmesi yok.",
                processed_lines=len(lines),
                matched_lines=0,
                tx_created=0,
                tx_duplicate=0,
                tx_failed=0,
                unmatched_lines=len(unmatched_lines),
            )

        product_ids_by_acc: Dict[int, set[str]] = {}
        for line in resolved_lines:
            lp = line["listing"]
            try:
                acc_id = int(getattr(lp, "api_account_id", 0) or 0)
            except Exception:
                continue
            product_id = str(getattr(lp, "product_id", "") or "").strip()
            if acc_id > 0 and product_id:
                product_ids_by_acc.setdefault(acc_id, set()).add(product_id)

        latest_stock_snapshot_rows: dict[tuple[int, int], ListingProductStockSnapshot] = {}
        with Session(_engine()) as session:
            listing_ids = sorted(
                {
                    int(getattr(line["listing"], "pk", 0) or 0)
                    for line in resolved_lines
                    if getattr(line.get("listing"), "pk", None) is not None
                }
            )
            if listing_ids:
                stmt = (
                    select(ListingProductStockSnapshot)
                    .where(ListingProductStockSnapshot.listing_id.in_(listing_ids))
                    .order_by(
                        ListingProductStockSnapshot.listing_id.asc(),
                        ListingProductStockSnapshot.stock_item_id.asc(),
                        ListingProductStockSnapshot.created_at.desc(),
                        ListingProductStockSnapshot.pk.desc(),
                    )
                )
                for row in list(session.exec(stmt).all() or []):
                    try:
                        listing_id = int(getattr(row, "listing_id", 0) or 0)
                        stock_item_id = int(getattr(row, "stock_item_id", 0) or 0)
                    except Exception:
                        continue
                    if listing_id <= 0 or stock_item_id <= 0:
                        continue
                    key = (listing_id, stock_item_id)
                    if key not in latest_stock_snapshot_rows:
                        latest_stock_snapshot_rows[key] = row

        map_items_by_key: Dict[int, list[dict[str, float]]] = {}
        for (listing_id, stock_item_id), row in latest_stock_snapshot_rows.items():
            status = str(getattr(row, "status", "") or "").strip().casefold()
            if status == "remove":
                continue
            qty = _safe_float(getattr(row, "qty", 1), 1.0)
            if qty <= 0:
                qty = 1.0
            map_items_by_key.setdefault(listing_id, []).append(
                {"stock_item_id": stock_item_id, "qty": qty}
            )

        operations: list[dict[str, Any]] = []
        for line in resolved_lines:
            lp = line["listing"]
            acc_id = int(getattr(lp, "api_account_id", 0) or 0)
            product_id = str(getattr(lp, "product_id", "") or "").strip()
            if acc_id <= 0 or not product_id:
                unmatched_lines.append(line)
                continue

            listing_pk = _safe_int_id(getattr(lp, "pk", None))
            mapped_items = list(map_items_by_key.get(int(listing_pk or 0), []) or []) if listing_pk else []
            if not mapped_items:
                stock_item_id = getattr(lp, "stock_item_id", None)
                try:
                    stock_item_id = int(stock_item_id) if stock_item_id is not None else 0
                except Exception:
                    stock_item_id = 0
                if stock_item_id > 0:
                    mapped_items = [{"stock_item_id": stock_item_id, "qty": 1.0}]

            if not mapped_items:
                unmatched_lines.append(line)
                continue

            base_qty = _safe_float(line.get("qty", 0), 0.0)
            if base_qty <= 0:
                continue

            for mapped in mapped_items:
                stock_item_id = int(mapped["stock_item_id"])
                map_qty = _safe_float(mapped.get("qty", 1.0), 1.0)
                if map_qty <= 0:
                    map_qty = 1.0
                total_out_qty = base_qty * map_qty
                if total_out_qty <= 0:
                    continue

                ref_id = _build_order_ref_id(
                    api_account_id=acc_id,
                    order_number=str(line.get("order_number", "") or ""),
                    product_code=str(line.get("product_code", "") or ""),
                    barcode=str(line.get("barcode", "") or ""),
                    stock_code=str(line.get("stock_code", "") or ""),
                )

                order_ref = str(line.get("order_number", "") or "").strip() or None
                listing_ref = str(product_id or "").strip() or None

                operations.append(
                    {
                        "item_id": stock_item_id,
                        "qty": total_out_qty,
                        "order_header_id": order_header_pk_by_key.get((acc_id, str(line.get("order_number", "") or "").strip())),
                        "reference_id": ref_id,
                        "order_ref": order_ref,
                        "listing_id": listing_ref,
                        "map_qty": map_qty,
                        "note": "Otomatik sipariş çıkışı",
                        "counterparty": (
                            str(platform_by_acc.get(acc_id, "") or "").strip()
                            or str(line.get("platform", "") or "").strip()
                            or None
                        ),
                    }
                )

        if not operations:
            return _ok(
                "Eslesen listing bulundu ancak stok karti eslesmesi yok.",
                processed_lines=len(lines),
                matched_lines=len(resolved_lines),
                tx_created=0,
                tx_duplicate=0,
                tx_failed=0,
                unmatched_lines=len(unmatched_lines),
            )

        involved_item_ids = sorted({int(op["item_id"]) for op in operations})
        if not involved_item_ids:
            return _ok(
                "Stok islemine uygun urun bulunamadi.",
                processed_lines=len(lines),
                matched_lines=len(resolved_lines),
                tx_created=0,
                tx_duplicate=0,
                tx_failed=0,
                unmatched_lines=len(unmatched_lines),
            )

        item_allow_negative_map: Dict[int, bool] = {}
        items_res = get_records(model=StockItem, db_engine=_engine(), filters={"pk": involved_item_ids})
        if items_res.success:
            for item in (items_res.data or {}).get("records", []) or []:
                try:
                    item_id = int(getattr(item, "pk", 0) or 0)
                except Exception:
                    continue
                if item_id > 0:
                    item_allow_negative_map[item_id] = bool(
                        getattr(item, "allow_negative_stock", ALLOW_NEGATIVE_STOCK_DEFAULT)
                    )

        warehouse_map: Dict[int, int] = {}
        for item_id in involved_item_ids:
            wh_res = _resolve_adjustment_warehouse_id(item_id=item_id)
            if wh_res.success:
                try:
                    wh_id = int((wh_res.data or {}).get("warehouse_id", 0) or 0)
                except Exception:
                    wh_id = 0
                if wh_id > 0:
                    warehouse_map[item_id] = wh_id

        if not warehouse_map:
            return Result.fail(
                "Siparis stok dusumu icin uygun depo bulunamadi.",
                close_dialog=False,
            )

        created = 0
        duplicate = 0
        failed = 0
        failures: list[dict[str, Any]] = []
        created_records: list[dict[str, Any]] = []

        for op in operations:
            item_id = int(op["item_id"])
            wh_id = int(warehouse_map.get(item_id, 0) or 0)
            if wh_id <= 0:
                failed += 1
                failures.append(
                    {"item_id": item_id, "reason": "warehouse_not_found", "message": "Depo bulunamadi."}
                )
                continue

            tx_create_res = create_tx(
                item_id=item_id,
                warehouse_id=wh_id,
                direction=StockTxDirection.OUT,
                qty=_safe_float(op.get("qty", 0), 0.0),
                reason=StockTxReason.order_out,
                note=op.get("note"),
                created_by=created_by,
                unit_cost=None,
                currency="TRY",
                counterparty=str(op.get("counterparty", "") or "").strip() or None,
                reference_type=StockReferenceType.order,
                reference_id=str(op.get("reference_id", "") or ""),
                order_header_id=_safe_int_id(op.get("order_header_id")),
                order_ref=str(op.get("order_ref", "") or "").strip() or None,
                listing_id=str(op.get("listing_id", "") or "").strip() or None,
                map_qty=_safe_float(op.get("map_qty", 0), 0.0) or None,
                allow_negative=item_allow_negative_map.get(item_id, ALLOW_NEGATIVE_STOCK_DEFAULT),
            )

            if tx_create_res.success:
                created += 1
                tx_data = tx_create_res.data or {}
                created_records.append(
                    {
                        "item_id": item_id,
                        "warehouse_id": wh_id,
                        "reference_id": op.get("reference_id"),
                        "order_header_id": op.get("order_header_id"),
                        "order_ref": op.get("order_ref"),
                        "listing_id": op.get("listing_id"),
                        "map_qty": op.get("map_qty"),
                        "tx_id": int(tx_data.get("tx_id", 0) or 0),
                        "qty": _safe_float(op.get("qty", 0), 0.0),
                        "unit_cost": tx_data.get("resolved_unit_cost"),
                        "currency": _normalize_currency(tx_data.get("resolved_currency"), "TRY"),
                        "allocated_qty": _safe_float(tx_data.get("allocated_qty"), 0.0),
                        "unallocated_qty": _safe_float(tx_data.get("unallocated_qty"), 0.0),
                    }
                )
                continue

            message = str(getattr(tx_create_res, "message", "") or "").casefold()
            if "referans" in message:
                duplicate += 1
                continue

            failed += 1
            failures.append(
                {
                    "item_id": item_id,
                    "reference_id": op.get("reference_id"),
                    "order_header_id": op.get("order_header_id"),
                    "message": getattr(tx_create_res, "message", "Bilinmeyen hata"),
                }
            )

        return _ok(
            "Siparis stok dusumu tamamlandi.",
            processed_lines=len(lines),
            matched_lines=len(resolved_lines),
            tx_created=created,
            tx_duplicate=duplicate,
            tx_failed=failed,
            unmatched_lines=len(unmatched_lines),
            created_records=created_records,
            failures=failures,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Siparis stok dusumu yapilamadi.")

def create_tx(
    item_id: int,
    warehouse_id: int,
    direction: StockTxDirection,
    qty: float,
    reason: StockTxReason,
    *,
    occurred_at: Optional[datetime] = None,
    unit_cost: Optional[float] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
    currency: str = "TRY",
    counterparty: Optional[str] = None,
    attachments: Optional[str] = None,
    reference_type: StockReferenceType = StockReferenceType.none,
    reference_id: Optional[str] = None,
    order_header_id: Optional[int] = None,
    order_ref: Optional[str] = None,
    listing_id: Optional[str] = None,
    map_qty: Optional[float] = None,
    note: Optional[str] = None,
    created_by: Optional[str] = None,
    allow_negative: Optional[bool] = None,
) -> Result:
    try:
        if _get_record(StockItem, item_id) is None:
            return Result.fail("Stok karti bulunamadi.", close_dialog=False)

        if _get_record(Warehouse, warehouse_id) is None:
            return Result.fail("Depo bulunamadi.", close_dialog=False)

        qty_val = _safe_float(qty, -1.0)
        if qty_val <= 0:
            return Result.fail("Miktar 0'dan büyük olmalı.", close_dialog=False)

        ref_type_val = (
            reference_type
            if isinstance(reference_type, StockReferenceType)
            else StockReferenceType(str(reference_type))
        )
        ref_id_val = str(reference_id or "").strip() or None
        order_header_id_val = _safe_int_id(order_header_id)
        order_ref_val = str(order_ref or "").strip() or None
        listing_id_val = str(listing_id or "").strip() or None
        counterparty_name = str(counterparty or "").strip() or None
        company_id_val = _resolve_company_id(counterparty_name)
        map_qty_val: Optional[float] = None
        if map_qty is not None:
            parsed_map_qty = _safe_float(map_qty, -1.0)
            if parsed_map_qty <= 0:
                return Result.fail("Map qty 0'dan buyuk olmali.", close_dialog=False)
            map_qty_val = parsed_map_qty

        if _is_duplicate_ref(ref_type_val, ref_id_val, item_id):
            return Result.fail("Aynı referans daha önce işlendi.", close_dialog=False)

        direction_val = _coerce_direction(direction)
        reason_val = reason if isinstance(reason, StockTxReason) else StockTxReason(str(reason))
        resolved_currency = _normalize_currency(currency, "TRY")
        resolved_unit_cost: Optional[float] = None
        resolved_unit_cost_input_mode = _normalize_unit_cost_input_mode(unit_cost_input_mode)
        resolved_unit_cost_vat_rate = _safe_float(unit_cost_vat_rate, -1.0) if unit_cost_vat_rate is not None else -1.0
        if resolved_unit_cost_vat_rate < 0:
            resolved_unit_cost_vat_rate = -1.0
        manual_cost_override = False
        if unit_cost is not None:
            parsed_cost = _safe_float(unit_cost, -1.0)
            if parsed_cost > 0:
                effective_vat_rate = (
                    resolved_unit_cost_vat_rate
                    if resolved_unit_cost_vat_rate >= 0
                    else _resolve_item_vat_rate(item_id)
                )
                vat_rate_for_calc = effective_vat_rate if effective_vat_rate not in (None, "") else None
                gross_unit_cost = _gross_amount_from_unit_cost(
                    parsed_cost,
                    input_mode=resolved_unit_cost_input_mode,
                    vat_rate=vat_rate_for_calc,
                )
                if gross_unit_cost is None:
                    if resolved_unit_cost_input_mode == UNIT_COST_INPUT_MODE_NET:
                        return Result.fail(
                            "KDV hariç maliyet için stok kartında geçerli KDV oranı zorunlu.",
                            close_dialog=False,
                        )
                    return Result.fail("Birim maliyet çözümlenemedi.", close_dialog=False)
                resolved_unit_cost = gross_unit_cost
                if resolved_unit_cost_input_mode is None:
                    resolved_unit_cost_input_mode = UNIT_COST_INPUT_MODE_GROSS
                if vat_rate_for_calc is not None:
                    resolved_unit_cost_vat_rate = effective_vat_rate
                manual_cost_override = True

        requested_allow_negative = (
            ALLOW_NEGATIVE_STOCK_DEFAULT if allow_negative is None else bool(allow_negative)
        )
        # Negatif stok sadece siparis kaynakli cikislarda anlamlidir.
        # Manuel cikis / duzeltme kaynakli cikislarda her zaman engellenir.
        allow_negative_effective = bool(
            requested_allow_negative
            and direction_val == StockTxDirection.OUT
            and reason_val == StockTxReason.order_out
            and ref_type_val == StockReferenceType.order
            and bool(ref_id_val)
        )
        if direction_val == StockTxDirection.OUT and not allow_negative_effective:
            bal = get_on_hand(item_id=item_id, warehouse_id=warehouse_id)
            if not bal.success:
                return bal
            on_hand = float(bal.data.get("on_hand", 0) or 0)
            if on_hand < qty_val:
                return Result.fail(
                    f"Yetersiz stok. Mevcut: {on_hand}, istenen: {qty_val}",
                    close_dialog=False,
                    data={"on_hand": on_hand, "requested": qty_val},
                )

        allocated_qty = 0.0
        unallocated_qty = 0.0
        valuation_method = "moving_avg"
        valuation_calc_version = 1
        valuation_cost_source = "moving_avg_auto"
        valuation_qty_before: Optional[float] = None
        valuation_qty_after: Optional[float] = None
        valuation_stock_value_before: Optional[float] = None
        valuation_stock_value_after: Optional[float] = None
        valuation_avg_before: Optional[float] = None
        valuation_avg_after: Optional[float] = None

        if direction_val == StockTxDirection.OUT:
            alloc_res = _plan_moving_average_out_context(
                item_id=int(item_id),
                warehouse_id=int(warehouse_id),
                qty=qty_val,
            )
            if not alloc_res.success:
                return alloc_res

            alloc_data = alloc_res.data or {}
            allocated_qty = _safe_float(alloc_data.get("allocated_qty"), 0.0)
            unallocated_qty = _safe_float(alloc_data.get("unallocated_qty"), 0.0)
            valuation_qty_before = _safe_float(alloc_data.get("qty_before"), 0.0)
            valuation_qty_after = _safe_float(alloc_data.get("qty_after"), valuation_qty_before - qty_val)
            valuation_stock_value_before = _safe_float(alloc_data.get("stock_value_before"), 0.0)
            valuation_stock_value_after = _safe_float(alloc_data.get("stock_value_after"), 0.0)
            avg_before_raw = alloc_data.get("avg_before")
            avg_after_raw = alloc_data.get("avg_after")
            valuation_avg_before = _safe_float(avg_before_raw, -1.0) if avg_before_raw is not None else None
            valuation_avg_after = _safe_float(avg_after_raw, -1.0) if avg_after_raw is not None else None
            if valuation_avg_before is not None and valuation_avg_before <= 0:
                valuation_avg_before = None
            if valuation_avg_after is not None and valuation_avg_after <= 0:
                valuation_avg_after = None

            if not allow_negative_effective and unallocated_qty > 1e-9:
                on_hand_val = _safe_float(alloc_data.get("on_hand"), 0.0)
                return Result.fail(
                    f"Yetersiz stok. Mevcut: {on_hand_val}, istenen: {qty_val}",
                    close_dialog=False,
                    data={"on_hand": on_hand_val, "requested": qty_val},
                )

            if resolved_unit_cost is None:
                auto_cost = alloc_data.get("moving_avg_unit_cost")
                auto_currency = alloc_data.get("currency")
                auto_input_mode = _normalize_unit_cost_input_mode(alloc_data.get("unit_cost_input_mode"))
                auto_cost_val = _safe_float(auto_cost, -1.0) if auto_cost is not None else -1.0
                if auto_cost_val > 0:
                    resolved_unit_cost = auto_cost_val
                    resolved_currency = _normalize_currency(auto_currency, resolved_currency)
                    if resolved_unit_cost_input_mode is None:
                        resolved_unit_cost_input_mode = auto_input_mode
                    if resolved_unit_cost_vat_rate < 0:
                        effective_vat_rate = _resolve_item_vat_rate(item_id)
                        if effective_vat_rate is not None:
                            resolved_unit_cost_vat_rate = effective_vat_rate
            valuation_cost_source = "manual_override" if manual_cost_override else "moving_avg_auto"
        else:
            in_ctx_res = _plan_moving_average_in_context(
                item_id=int(item_id),
                warehouse_id=int(warehouse_id),
                qty=qty_val,
                tx_unit_cost=resolved_unit_cost,
                tx_currency=resolved_currency,
            )
            if not in_ctx_res.success:
                return in_ctx_res
            in_ctx = in_ctx_res.data or {}
            valuation_qty_before = _safe_float(in_ctx.get("qty_before"), 0.0)
            valuation_qty_after = _safe_float(in_ctx.get("qty_after"), valuation_qty_before + qty_val)
            valuation_stock_value_before = _safe_float(in_ctx.get("stock_value_before"), 0.0)
            valuation_stock_value_after = _safe_float(in_ctx.get("stock_value_after"), 0.0)
            avg_before_raw = in_ctx.get("avg_before")
            avg_after_raw = in_ctx.get("avg_after")
            valuation_avg_before = _safe_float(avg_before_raw, -1.0) if avg_before_raw is not None else None
            valuation_avg_after = _safe_float(avg_after_raw, -1.0) if avg_after_raw is not None else None
            if valuation_avg_before is not None and valuation_avg_before <= 0:
                valuation_avg_before = None
            if valuation_avg_after is not None and valuation_avg_after <= 0:
                valuation_avg_after = None
            valuation_cost_source = "manual_in"

        occurred_at_val = _to_local_naive(occurred_at)
        created_at_val = _local_now_naive()

        payload = {
            "item_id": item_id,
            "warehouse_id": warehouse_id,
            "direction": direction_val,
            "reason": reason_val,
            "qty": qty_val,
            "occurred_at": occurred_at_val,
            "created_at": created_at_val,
            "unit_cost": resolved_unit_cost,
            "unit_cost_input_mode": resolved_unit_cost_input_mode,
            "unit_cost_vat_rate": resolved_unit_cost_vat_rate if resolved_unit_cost_vat_rate >= 0 else None,
            "currency": resolved_currency,
            "valuation_method": valuation_method,
            "valuation_calc_version": valuation_calc_version,
            "valuation_cost_source": valuation_cost_source,
            "valuation_qty_before": valuation_qty_before,
            "valuation_qty_after": valuation_qty_after,
            "valuation_stock_value_before": valuation_stock_value_before,
            "valuation_stock_value_after": valuation_stock_value_after,
            "valuation_avg_before": valuation_avg_before,
            "valuation_avg_after": valuation_avg_after,
            "reference_type": ref_type_val,
            "reference_id": ref_id_val,
            "order_header_id": order_header_id_val,
            "order_ref": order_ref_val,
            "listing_id": listing_id_val,
            "map_qty": map_qty_val,
            "note": note,
            "created_by": created_by,
            "company_id": company_id_val,
            "counterparty": counterparty_name,
            "attachments": attachments,
        }
        payload = tx_normalizer(payload)

        tx_id = 0
        backfilled_qty = 0.0
        backfilled_tx_count = 0
        backfill_split_rows = 0
        with Session(_engine()) as session:
            if (
                direction_val == StockTxDirection.IN_
                and resolved_unit_cost is not None
                and resolved_unit_cost > 0
                and qty_val > 0
            ):
                backfill_info = _backfill_missing_out_costs(
                    session=session,
                    item_id=int(item_id),
                    warehouse_id=int(warehouse_id),
                    incoming_qty=qty_val,
                    incoming_unit_cost=resolved_unit_cost,
                    incoming_currency=resolved_currency,
                )
                backfilled_qty = _safe_float(backfill_info.get("backfilled_qty"), 0.0)
                backfilled_tx_count = int(backfill_info.get("backfilled_tx_count", 0) or 0)
                backfill_split_rows = int(backfill_info.get("split_rows", 0) or 0)

            tx_row = StockTx(**payload)
            session.add(tx_row)
            session.flush()
            tx_id = int(getattr(tx_row, "pk", 0) or 0)

            session.commit()

        _emit_tx_created(tx_id)
        _emit_quick_access_change("tx", 1)
        _emit_refresh()
        return _ok(
            "Stok hareketi işlendi.",
            tx_id=tx_id,
            allocated_qty=allocated_qty,
            unallocated_qty=unallocated_qty,
            resolved_unit_cost=resolved_unit_cost,
            resolved_currency=resolved_currency,
            backfilled_qty=backfilled_qty,
            backfilled_tx_count=backfilled_tx_count,
            backfill_split_rows=backfill_split_rows,
        )
    except IntegrityError as e:
        raw = str(e).lower()
        if "ix_stock_tx_ref_unique" in raw or "stock_tx.reference_type" in raw:
            return Result.fail("Aynı referans daha önce işlendi.", close_dialog=False)
        return _fail(StockError.integrity, e, "Stok hareketi bütünlük kontrolünde hata oluştu.")
    except Exception as e:
        return _fail(StockError.db_error, e, "Stok hareketi oluşturulamadı.")

def manual_in(
    item_id: int,
    warehouse_id: int,
    qty: float,
    note: Optional[str] = None,
    created_by: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    unit_cost: Optional[float] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
    currency: str = "TRY",
    counterparty: Optional[str] = None,
    attachments: Optional[str] = None,
    reason: Optional[str] = None,
) -> Result:
    return create_tx(
        item_id=item_id,
        warehouse_id=warehouse_id,
        direction=StockTxDirection.IN_,
        qty=qty,
        reason=StockTxReason(reason) if reason else StockTxReason.manual_in,
        note=note,
        created_by=created_by,
        occurred_at=occurred_at,
        unit_cost=unit_cost,
        unit_cost_input_mode=unit_cost_input_mode,
        unit_cost_vat_rate=unit_cost_vat_rate,
        currency=currency,
        counterparty=counterparty,
        attachments=attachments,
    )

def manual_out(
    item_id: int,
    warehouse_id: int,
    qty: float,
    note: Optional[str] = None,
    created_by: Optional[str] = None,
    allow_negative: bool = False,
    occurred_at: Optional[datetime] = None,
    unit_cost: Optional[float] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
    currency: str = "TRY",
    counterparty: Optional[str] = None,
    attachments: Optional[str] = None,
    reason: Optional[str] = None,
    reference_type: StockReferenceType = StockReferenceType.none,
    reference_id: Optional[str] = None,
    order_ref: Optional[str] = None,
    listing_id: Optional[str] = None,
    map_qty: Optional[float] = None,
) -> Result:
    return create_tx(
        item_id=item_id,
        warehouse_id=warehouse_id,
        direction=StockTxDirection.OUT,
        qty=qty,
        reason=StockTxReason(reason) if reason else StockTxReason.manual_out,
        note=note,
        created_by=created_by,
        allow_negative=allow_negative,
        occurred_at=occurred_at,
        unit_cost=unit_cost,
        unit_cost_input_mode=unit_cost_input_mode,
        unit_cost_vat_rate=unit_cost_vat_rate,
        currency=currency,
        counterparty=counterparty,
        attachments=attachments,
        reference_type=reference_type,
        reference_id=reference_id,
        order_ref=order_ref,
        listing_id=listing_id,
        map_qty=map_qty,
    )


def update_tx_attachments(
    *,
    tx_id: int,
    attachments: Optional[str] = None,
) -> Result:
    return update_tx_edit_fields(tx_id=tx_id, attachments=attachments)


def update_tx_edit_fields(
    *,
    tx_id: int,
    attachments: Optional[str] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
) -> Result:
    try:
        target_id = int(tx_id or 0)
    except Exception:
        target_id = 0
    if target_id <= 0:
        return Result.fail("Geçersiz hareket numarası.", close_dialog=False)

    normalized = tx_normalizer({"attachments": attachments})
    normalized_attachments = normalized.get("attachments")
    if normalized_attachments is not None and len(str(normalized_attachments)) > 2000:
        return Result.fail("Belge bilgisi çok uzun (max 2000 karakter).", close_dialog=False)

    normalized_mode = _normalize_unit_cost_input_mode(unit_cost_input_mode)
    normalized_vat_rate = _safe_float(unit_cost_vat_rate, -1.0) if unit_cost_vat_rate is not None else -1.0
    if normalized_vat_rate < 0:
        normalized_vat_rate = -1.0

    try:
        with Session(_engine()) as session:
            row = session.get(StockTx, target_id)
            if row is None:
                return Result.fail("Stok hareketi bulunamadı.", close_dialog=False)

            row_unit_cost = _safe_float(getattr(row, "unit_cost", None), -1.0)
            has_cost_value = row_unit_cost > 0
            resolved_mode = (
                normalized_mode
                or _normalize_unit_cost_input_mode(getattr(row, "unit_cost_input_mode", None))
                or UNIT_COST_INPUT_MODE_NET
            )
            if normalized_vat_rate >= 0:
                resolved_vat_rate: Optional[float] = normalized_vat_rate
            else:
                existing_vat_rate = _safe_float(getattr(row, "unit_cost_vat_rate", None), -1.0)
                if existing_vat_rate >= 0:
                    resolved_vat_rate = existing_vat_rate
                else:
                    resolved_vat_rate = _resolve_item_vat_rate(getattr(row, "item_id", None))

            if has_cost_value and resolved_mode == UNIT_COST_INPUT_MODE_NET and resolved_vat_rate is None:
                return Result.fail(
                    "KDV hariç maliyet için stok kartında geçerli KDV oranı zorunlu.",
                    close_dialog=False,
                )

            row.attachments = normalized_attachments
            row.unit_cost_input_mode = resolved_mode
            row.unit_cost_vat_rate = resolved_vat_rate
            session.add(row)
            session.commit()

        _emit_refresh()
        return _ok(
            "Hareket düzenleme alanları güncellendi.",
            tx_id=target_id,
            attachments=normalized_attachments,
            unit_cost_input_mode=resolved_mode,
            unit_cost_vat_rate=resolved_vat_rate,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Hareket düzenleme alanları güncellenemedi.")


def _resolve_adjustment_warehouse_id(
    *,
    item_id: int,
    warehouse_id: Optional[int] = None,
) -> Result:
    try:
        if warehouse_id is not None:
            return _ok("Depo bulundu.", warehouse_id=int(warehouse_id))

        stmt = (
            select(StockTx.warehouse_id)
            .where(StockTx.item_id == int(item_id))
            .order_by(StockTx.occurred_at.desc(), StockTx.created_at.desc(), StockTx.pk.desc())
            .limit(1)
        )
        with Session(_engine()) as session:
            latest_warehouse_id = session.exec(stmt).first()
        try:
            resolved_warehouse_id = int(latest_warehouse_id or 0)
        except Exception:
            resolved_warehouse_id = 0
        if resolved_warehouse_id > 0:
            return _ok("Depo bulundu.", warehouse_id=resolved_warehouse_id)

        wh_res = get_records(model=Warehouse, db_engine=_engine())
        if not wh_res.success:
            return wh_res

        warehouses = wh_res.data.get("records", []) or []
        active_warehouses = [w for w in warehouses if bool(getattr(w, "is_active", False))]
        pool = active_warehouses or warehouses
        if not pool:
            return Result.fail(
                "Stok düzeltmesi için depo bulunamadı. Önce bir depo eklemelisin.",
                close_dialog=False,
            )

        chosen = pool[0]
        chosen_id = int(getattr(chosen, "pk", 0) or 0)
        if chosen_id <= 0:
            return Result.fail(
                "Stok düzeltmesi için geçerli depo bulunamadı.",
                close_dialog=False,
            )
        return _ok("Depo bulundu.", warehouse_id=chosen_id)
    except Exception as e:
        return _fail(StockError.db_error, e, "Stok düzeltmesi için depo çözümlenemedi.")


def adjust_item_stock_to(
    *,
    item_id: int,
    target_qty: float,
    warehouse_id: Optional[int] = None,
    note: Optional[str] = None,
    created_by: Optional[str] = None,
    allow_negative: Optional[bool] = None,
    unit_cost: Optional[float] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
    currency: str = "TRY",
) -> Result:
    """
    Stok kartındaki hedef bakiyeye göre otomatik düzeltme hareketi üretir.
    - target > mevcut: adjustment IN
    - target < mevcut: adjustment OUT
    """
    try:
        item_id = int(item_id)
        target = float(target_qty)
    except Exception:
        return Result.fail("Geçersiz ürün veya hedef stok değeri.", close_dialog=False)

    if target < 0:
        return Result.fail("Hedef stok 0 veya daha büyük olmalı.", close_dialog=False)

    item_res = get_records(model=StockItem, db_engine=_engine(), filters={"pk": item_id})
    if not item_res.success:
        return item_res
    item_rows = item_res.data.get("records", []) or []
    if not item_rows:
        return Result.fail("Stok kartı bulunamadı.", close_dialog=False)
    item = item_rows[0]

    effective_allow_negative = (
        bool(allow_negative)
        if allow_negative is not None
        else bool(getattr(item, "allow_negative_stock", ALLOW_NEGATIVE_STOCK_DEFAULT))
    )

    wh_res = _resolve_adjustment_warehouse_id(item_id=item_id, warehouse_id=warehouse_id)
    if not wh_res.success:
        return wh_res
    resolved_wh_id = int(wh_res.data.get("warehouse_id", 0) or 0)
    if resolved_wh_id <= 0:
        return Result.fail("Stok düzeltmesi için depo bulunamadı.", close_dialog=False)

    bal_res = get_on_hand(item_id=item_id, warehouse_id=resolved_wh_id)
    if not bal_res.success:
        return bal_res
    current = float(bal_res.data.get("on_hand", 0) or 0)
    delta = float(target - current)
    if abs(delta) < 1e-9:
        return _ok(
            "Stok zaten hedef değerle aynı.",
            changed=False,
            previous_on_hand=current,
            target_on_hand=target,
            warehouse_id=resolved_wh_id,
        )

    qty = abs(delta)
    currency_val = str(currency or "TRY").strip().upper() or "TRY"
    unit_cost_val: Optional[float] = None
    if unit_cost is not None:
        try:
            unit_cost_val = float(unit_cost)
        except Exception:
            return Result.fail("Birim maliyet sayısal olmalı.", close_dialog=False)
        if unit_cost_val <= 0:
            return Result.fail("Birim maliyet 0'dan büyük olmalı.", close_dialog=False)
    auto_note = (
        (note or "").strip()
        or f"Otomatik düzeltme: {current:g} -> {target:g}"
    )

    if delta > 0:
        if unit_cost_val is None:
            return Result.fail(
                "Stok giriş düzeltmesinde birim maliyet zorunludur.",
                close_dialog=False,
            )
        tx_res = create_tx(
            item_id=item_id,
            warehouse_id=resolved_wh_id,
            direction=StockTxDirection.IN_,
            qty=qty,
            reason=StockTxReason.adjustment,
            note=auto_note,
            created_by=created_by,
            unit_cost=unit_cost_val,
            unit_cost_input_mode=unit_cost_input_mode,
            unit_cost_vat_rate=unit_cost_vat_rate,
            currency=currency_val,
            counterparty=None,
            attachments=None,
            allow_negative=effective_allow_negative,
        )
        movement = "in"
    else:
        tx_res = create_tx(
            item_id=item_id,
            warehouse_id=resolved_wh_id,
            direction=StockTxDirection.OUT,
            qty=qty,
            reason=StockTxReason.adjustment,
            note=auto_note,
            created_by=created_by,
            unit_cost=None,
            currency=currency_val,
            counterparty=None,
            attachments=None,
            allow_negative=effective_allow_negative,
        )
        movement = "out"

    if not tx_res.success:
        return tx_res

    return _ok(
        "Stok düzeltme hareketi işlendi.",
        changed=True,
        movement=movement,
        delta_qty=qty,
        previous_on_hand=current,
        target_on_hand=target,
        warehouse_id=resolved_wh_id,
    )

def list_txs(item_id: Optional[int] = None, warehouse_id: Optional[int] = None, limit: int = 200) -> Result:
    try:
        try:
            max_limit = max(1, int(limit))
        except Exception:
            max_limit = 200

        txs = _list_txs_query(item_id=item_id, warehouse_id=warehouse_id, limit=max_limit)

        return _ok(
            f"{len(txs)} hareket çekildi." if txs else "Hareket bulunmuyor.",
            records=txs,
        )
    except Exception as e:
        return _fail(StockError.db_error, e, "Hareketler okunamadı.")


def list_txs_by_ids(tx_ids: list[int]) -> Result:
    """
    Verilen hareket ID listesini doğrudan getirir (limit uygulamaz).
    """
    try:
        normalized_ids: list[int] = []
        for raw in (tx_ids or []):
            try:
                tx_id = int(raw or 0)
            except Exception:
                continue
            if tx_id > 0 and tx_id not in normalized_ids:
                normalized_ids.append(tx_id)

        if not normalized_ids:
            return _ok("Hareket bulunamadı.", records=[])

        res = get_records(model=StockTx, db_engine=_engine(), filters={"pk": normalized_ids})
        if not res.success:
            return res

        rows = (res.data or {}).get("records", []) or []
        rows = sorted(rows, key=lambda x: getattr(x, "occurred_at", None) or datetime.min, reverse=True)
        return _ok(f"{len(rows)} hareket bulundu.", records=rows)
    except Exception as e:
        return _fail(StockError.db_error, e, "Hareketler okunamadı.")


def get_tx_cost_detail(*, tx_id: int) -> Result:
    try:
        target_id = int(tx_id or 0)
    except Exception:
        target_id = 0
    if target_id <= 0:
        return Result.fail("Geçersiz hareket numarası.", close_dialog=False)

    try:
        tx_res = get_records(model=StockTx, db_engine=_engine(), filters={"pk": target_id})
        if not tx_res.success:
            return tx_res
        target_rows = (tx_res.data or {}).get("records", []) or []
        if not target_rows:
            return Result.fail("Hareket bulunamadı.", close_dialog=False)
        target_tx = target_rows[0]

        try:
            item_id = int(getattr(target_tx, "item_id", 0) or 0)
            warehouse_id = int(getattr(target_tx, "warehouse_id", 0) or 0)
        except Exception:
            item_id = 0
            warehouse_id = 0
        if item_id <= 0 or warehouse_id <= 0:
            return Result.fail("Hareket için ürün/depo bilgisi geçersiz.", close_dialog=False)

        snapshot_qty_before_raw = getattr(target_tx, "valuation_qty_before", None)
        snapshot_qty_after_raw = getattr(target_tx, "valuation_qty_after", None)
        snapshot_avg_before_raw = getattr(target_tx, "valuation_avg_before", None)
        snapshot_avg_after_raw = getattr(target_tx, "valuation_avg_after", None)
        snapshot_value_before_raw = getattr(target_tx, "valuation_stock_value_before", None)
        snapshot_value_after_raw = getattr(target_tx, "valuation_stock_value_after", None)
        has_snapshot = any(
            v is not None
            for v in (
                snapshot_qty_before_raw,
                snapshot_qty_after_raw,
                snapshot_avg_before_raw,
                snapshot_avg_after_raw,
                snapshot_value_before_raw,
                snapshot_value_after_raw,
            )
        )

        if has_snapshot:
            direction = _coerce_direction(getattr(target_tx, "direction", None))
            direction_text = "Giriş" if direction == StockTxDirection.IN_ else "Çıkış"
            qty = _safe_float(getattr(target_tx, "qty", 0), 0.0)
            row_cost_raw = getattr(target_tx, "unit_cost", None)
            row_cost = _safe_float(row_cost_raw, -1.0) if row_cost_raw is not None else -1.0
            row_cost = row_cost if row_cost > 0 else None
            row_currency = _normalize_currency(getattr(target_tx, "currency", None), "TRY")

            qty_before = _safe_float(snapshot_qty_before_raw, 0.0)
            qty_after = _safe_float(snapshot_qty_after_raw, qty_before)
            avg_before = _safe_float(snapshot_avg_before_raw, -1.0) if snapshot_avg_before_raw is not None else None
            avg_after = _safe_float(snapshot_avg_after_raw, -1.0) if snapshot_avg_after_raw is not None else None
            if avg_before is not None and avg_before <= 0:
                avg_before = None
            if avg_after is not None and avg_after <= 0:
                avg_after = None
            stock_value_before = _safe_float(snapshot_value_before_raw, 0.0)
            stock_value_after = _safe_float(snapshot_value_after_raw, 0.0)
            cost_source = str(getattr(target_tx, "valuation_cost_source", "") or "").strip() or (
                "manual_in" if direction == StockTxDirection.IN_ else "moving_avg_auto"
            )
            calc_version = int(getattr(target_tx, "valuation_calc_version", 1) or 1)

            formula_lines: list[str] = [
                f"Hareket: {direction_text} #{target_id}",
                f"Yöntem: Hareketli Ortalama (Perpetual) • Versiyon: {calc_version}",
                f"Ürün ID: {item_id} • Depo ID: {warehouse_id}",
                f"Miktar (işlem): {qty}",
                f"Birim maliyet (kayıt): {row_cost if row_cost is not None else '-'} {row_currency}",
                f"Stok önce: {qty_before}",
                f"Ortalama önce: {avg_before if avg_before is not None else '-'} {row_currency}",
                f"Stok değeri önce: {stock_value_before}",
                f"Stok sonra: {qty_after}",
                f"Ortalama sonra: {avg_after if avg_after is not None else '-'} {row_currency}",
                f"Stok değeri sonra: {stock_value_after}",
            ]
            if direction == StockTxDirection.IN_:
                formula_lines.append("Formül: yeni_ortalama = ((eski_stok * eski_ortalama) + (giriş_miktarı * giriş_maliyeti)) / yeni_stok")
            else:
                formula_lines.append("Formül: çıkış_birim_maliyeti = o anki hareketli ortalama")
                formula_lines.append("Not: Çıkış işlemi ortalamayı değiştirmez; stok 0/altına düşerse ortalama sıfırlanır.")

            return _ok(
                "Maliyet detayı hazır.",
                tx_id=target_id,
                direction=str(getattr(target_tx, "direction", "") or ""),
                cost_source=cost_source,
                qty=qty,
                unit_cost=row_cost,
                currency=row_currency,
                qty_before=qty_before,
                qty_after=qty_after,
                avg_before=avg_before,
                avg_after=avg_after,
                stock_value_before=stock_value_before,
                stock_value_after=stock_value_after,
                formula_lines=formula_lines,
            )

        wh_rows_res = get_records(
            model=StockTx,
            db_engine=_engine(),
            filters={"item_id": item_id, "warehouse_id": warehouse_id},
        )
        if not wh_rows_res.success:
            return wh_rows_res
        rows = sorted((wh_rows_res.data or {}).get("records", []) or [], key=_tx_time_sort_key)

        on_hand = 0.0
        avg_unit_cost: Optional[float] = None
        state_currency = "TRY"
        detail_data: Optional[dict[str, Any]] = None

        for row in rows:
            try:
                rid = int(getattr(row, "pk", 0) or 0)
            except Exception:
                continue
            qty = _safe_float(getattr(row, "qty", 0), 0.0)
            if qty <= 0:
                continue

            direction = _coerce_direction(getattr(row, "direction", None))
            row_cost_raw = getattr(row, "unit_cost", None)
            row_cost = _safe_float(row_cost_raw, -1.0) if row_cost_raw is not None else -1.0
            row_cost = row_cost if row_cost > 0 else None
            row_currency = _normalize_currency(getattr(row, "currency", None), state_currency)

            qty_before = on_hand
            avg_before = avg_unit_cost
            currency_before = state_currency
            stock_value_before = (qty_before * avg_before) if (avg_before is not None and qty_before > 0) else 0.0

            qty_after = qty_before
            avg_after = avg_before
            currency_after = currency_before

            if direction == StockTxDirection.IN_:
                if qty_before <= 1e-9:
                    qty_after = qty
                    if row_cost is not None:
                        avg_after = row_cost
                        currency_after = row_currency
                    elif avg_after is None:
                        avg_after = None
                else:
                    if row_cost is None:
                        qty_after = qty_before + qty
                    else:
                        if avg_before is None:
                            avg_after = row_cost
                            currency_after = row_currency
                            qty_after = qty_before + qty
                        else:
                            qty_after = qty_before + qty
                            if qty_after > 1e-9:
                                avg_after = ((qty_before * avg_before) + (qty * row_cost)) / qty_after
            else:
                qty_after = qty_before - qty
                if qty_after <= 1e-9:
                    if abs(qty_after) <= 1e-9:
                        qty_after = 0.0
                    avg_after = None

            stock_value_after = (qty_after * avg_after) if (avg_after is not None and qty_after > 0) else 0.0

            if rid == target_id:
                direction_text = "Giriş" if direction == StockTxDirection.IN_ else "Çıkış"
                cost_source = str(getattr(row, "valuation_cost_source", "") or "").strip()
                if not cost_source:
                    if direction == StockTxDirection.OUT:
                        if row_cost is not None and avg_before is not None and abs(row_cost - avg_before) > 1e-9:
                            cost_source = "manual_override"
                        else:
                            cost_source = "moving_avg_auto"
                    else:
                        cost_source = "manual_in" if row_cost is not None else "costless_in"

                formula_lines: list[str] = [
                    f"Hareket: {direction_text} #{rid}",
                    f"Yöntem: Hareketli Ortalama (Perpetual) • Versiyon: {int(getattr(row, 'valuation_calc_version', 1) or 1)}",
                    f"Ürün ID: {item_id} • Depo ID: {warehouse_id}",
                    f"Miktar (işlem): {qty}",
                    f"Birim maliyet (kayıt): {row_cost if row_cost is not None else '-'} {row_currency}",
                    f"Stok önce: {qty_before}",
                    f"Ortalama önce: {avg_before if avg_before is not None else '-'} {currency_before}",
                    f"Stok değeri önce: {stock_value_before}",
                    f"Stok sonra: {qty_after}",
                    f"Ortalama sonra: {avg_after if avg_after is not None else '-'} {currency_after}",
                    f"Stok değeri sonra: {stock_value_after}",
                ]
                if direction == StockTxDirection.IN_:
                    formula_lines.append("Formül: yeni_ortalama = ((eski_stok * eski_ortalama) + (giriş_miktarı * giriş_maliyeti)) / yeni_stok")
                else:
                    formula_lines.append("Formül: çıkış_birim_maliyeti = o anki hareketli ortalama")
                    formula_lines.append("Not: Çıkış işlemi ortalamayı değiştirmez; stok 0/altına düşerse ortalama sıfırlanır.")

                detail_data = {
                    "tx_id": rid,
                    "direction": str(getattr(row, "direction", "") or ""),
                    "cost_source": cost_source,
                    "qty": qty,
                    "unit_cost": row_cost,
                    "currency": row_currency,
                    "qty_before": qty_before,
                    "qty_after": qty_after,
                    "avg_before": avg_before,
                    "avg_after": avg_after,
                    "stock_value_before": stock_value_before,
                    "stock_value_after": stock_value_after,
                    "formula_lines": formula_lines,
                }
                break

            on_hand = qty_after
            avg_unit_cost = avg_after if (avg_after is not None and avg_after > 0) else None
            state_currency = currency_after

        if detail_data is None:
            return Result.fail("Maliyet detayı hesaplanamadı.", close_dialog=False)
        return _ok("Maliyet detayı hazır.", **detail_data)
    except Exception as e:
        return _fail(StockError.db_error, e, "Maliyet detayı hazırlanamadı.")


# -------------------------------------------------
# SUMMARY / FILTER / EXPORT
# -------------------------------------------------
def _calc_on_hand_map(
    txs: Iterable[StockTx],
    *,
    warehouse_id: Optional[int] = None,
) -> Dict[int, float]:
    """
    item_id -> on_hand (IN - OUT)
    """
    totals: Dict[int, float] = {}
    for tx in txs:
        try:
            if warehouse_id is not None and getattr(tx, "warehouse_id", None) != warehouse_id:
                continue
            item_id = int(getattr(tx, "item_id", 0) or 0)
            if not item_id:
                continue
            qty = float(getattr(tx, "qty", 0) or 0)
            direction = getattr(tx, "direction", None)
            delta = qty if direction == StockTxDirection.IN_ else -qty
            totals[item_id] = totals.get(item_id, 0.0) + delta
        except Exception:
            continue
    return totals


def _summarize_item_valuation_rows(
    rows: Iterable[tuple[int, float, Any, Any, Any]],
) -> tuple[Dict[int, float], Dict[int, str], Dict[int, Optional[str]], Dict[int, Dict[str, float]], Dict[int, float]]:
    """Preserve currency and missing cost across warehouse valuation layers."""
    quantity_by_currency: Dict[int, Dict[str, float]] = {}
    value_by_currency: Dict[int, Dict[str, float]] = {}
    missing_quantity: Dict[int, float] = {}
    mode_by_item: Dict[int, Optional[str]] = {}
    for item_id, raw_qty, raw_cost, raw_currency, raw_mode in rows:
        qty = _safe_float(raw_qty, 0.0)
        if qty <= 0:
            continue
        cost = _safe_float(raw_cost, -1.0) if raw_cost is not None else -1.0
        if cost < 0:
            missing_quantity[item_id] = missing_quantity.get(item_id, 0.0) + qty
            continue
        currency = _normalize_currency(raw_currency, "TRY")
        quantities = quantity_by_currency.setdefault(item_id, {})
        values = value_by_currency.setdefault(item_id, {})
        quantities[currency] = quantities.get(currency, 0.0) + qty
        values[currency] = values.get(currency, 0.0) + qty * cost
        mode_by_item[item_id] = _merge_unit_cost_input_modes(
            mode_by_item.get(item_id), raw_mode,
        )

    avg_by_item: Dict[int, float] = {}
    currency_by_item: Dict[int, str] = {}
    for item_id, values in value_by_currency.items():
        if len(values) != 1 or missing_quantity.get(item_id, 0.0) > 0:
            continue
        currency, value = next(iter(values.items()))
        qty = quantity_by_currency[item_id][currency]
        if qty > 0:
            avg_by_item[item_id] = value / qty
            currency_by_item[item_id] = currency
    return avg_by_item, currency_by_item, mode_by_item, value_by_currency, missing_quantity


def _calc_avg_unit_cost_map(
    txs: Iterable[StockTx],
    *,
    warehouse_id: Optional[int] = None,
) -> tuple[Dict[int, float], Dict[int, str], Dict[int, Optional[str]], Dict[int, Dict[str, float]], Dict[int, float]]:
    """
    item_id -> avg_unit_cost, item_id -> currency, item_id -> unit_cost_input_mode.
    Uses the same active-stock valuation logic as order auto-deduction:
    - Cost layer resets when on_hand <= 0.
    - For warehouse scoped query, cost is taken directly from that warehouse state.
    - For all warehouses, average is available only with one currency and no missing cost.
    """
    active_states = _build_active_stock_state_map(txs, warehouse_id=warehouse_id)

    valuation_rows = []
    for (item_id, _wh_id), state in active_states.items():
        try:
            item_key = int(item_id)
        except Exception:
            continue
        if item_key <= 0:
            continue

        on_hand = _safe_float(state.get("on_hand", 0.0), 0.0)
        valuation_rows.append((
            item_key, on_hand, state.get("avg_unit_cost"),
            state.get("currency"), state.get("unit_cost_input_mode"),
        ))

    return _summarize_item_valuation_rows(valuation_rows)


def list_item_balances(
    *,
    warehouse_id: Optional[int] = None,
    only_active: bool = True,
    db_name: str | None = None,
) -> Result:
    """
    Tüm stok kartları için bakiye döner.
    data: records=[{item, on_hand, min_stock, is_low, avg_unit_cost, avg_cost_currency, avg_cost_input_mode}]
    """
    try:
        items = _list_stock_items(only_active=only_active, db_name=db_name)
        item_ids: list[int] = []
        for item in items:
            try:
                item_id = int(getattr(item, "pk", 0) or 0)
            except Exception:
                item_id = 0
            if item_id > 0:
                item_ids.append(item_id)

        balance_maps = _balance_maps_from_latest_valuations(
            item_ids,
            warehouse_id=warehouse_id,
            db_name=db_name,
        )
        if balance_maps is None:
            on_hand_map = _aggregate_on_hand_by_item(
                item_ids,
                warehouse_id=warehouse_id,
                db_name=db_name,
            )
            txs = _list_balance_txs(
                item_ids,
                warehouse_id=warehouse_id,
                db_name=db_name,
            )
            avg_cost_map, avg_cost_currency_map, avg_cost_input_mode_map, value_map, missing_cost_map = _calc_avg_unit_cost_map(
                txs,
                warehouse_id=warehouse_id,
            )
        else:
            on_hand_map, avg_cost_map, avg_cost_currency_map, avg_cost_input_mode_map, value_map, missing_cost_map = balance_maps

        records = []
        for it in items:
            item_id = getattr(it, "pk", None)
            if item_id is None:
                continue
            on_hand = float(on_hand_map.get(int(item_id), 0.0))
            min_stock = getattr(it, "min_stock", None)
            try:
                min_stock_val = float(min_stock) if min_stock is not None else None
            except Exception:
                min_stock_val = None

            is_low = False
            if min_stock_val is not None:
                is_low = on_hand <= float(min_stock_val)

            records.append({
                "item": it,
                "on_hand": on_hand,
                "min_stock": min_stock_val,
                "is_low": is_low,
                "avg_unit_cost": avg_cost_map.get(int(item_id)),
                "avg_cost_currency": avg_cost_currency_map.get(int(item_id), ""),
                "avg_cost_input_mode": avg_cost_input_mode_map.get(int(item_id)),
                "stock_value_by_currency": dict(value_map.get(int(item_id), {})),
                "valuation_missing_quantity": missing_cost_map.get(int(item_id), 0.0),
            })

        # düşük stoklar öne gelsin
        records.sort(key=lambda r: (not r["is_low"], (r["item"].name or "")))

        return _ok("Stok bakiyeleri hazırlandı.", records=records)
    except Exception as e:
        return _fail(StockError.db_error, e, "Stok bakiyeleri alınamadı.")


def list_txs_filtered(
    *,
    item_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    direction: Optional[str] = None,
    reason: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
    limit: int = 500,
) -> Result:
    try:
        try:
            max_limit = max(1, int(limit))
        except Exception:
            max_limit = 500

        stmt = select(StockTx)

        if item_id is not None:
            try:
                stmt = stmt.where(StockTx.item_id == int(item_id))
            except Exception:
                return _ok("0 hareket bulundu.", records=[])

        if warehouse_id is not None:
            try:
                stmt = stmt.where(StockTx.warehouse_id == int(warehouse_id))
            except Exception:
                return _ok("0 hareket bulundu.", records=[])

        if direction:
            direction_enum = _parse_direction_filter(direction)
            if direction_enum is None:
                return _ok("0 hareket bulundu.", records=[])
            stmt = stmt.where(StockTx.direction == direction_enum)

        if reason:
            reason_raw = getattr(reason, "value", reason)
            reason_text = str(reason_raw or "").strip()
            if reason_text:
                try:
                    reason_enum = StockTxReason(reason_text)
                except Exception:
                    return _ok("0 hareket bulundu.", records=[])
                stmt = stmt.where(StockTx.reason == reason_enum)

        if date_from is not None:
            stmt = stmt.where(StockTx.occurred_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(StockTx.occurred_at <= date_to)

        search_text = str(search or "").strip().lower()
        if search_text:
            pattern = f"%{search_text}%"
            stmt = stmt.where(
                or_(
                    func.lower(func.coalesce(StockTx.note, "")).like(pattern),
                    func.lower(func.coalesce(StockTx.reference_id, "")).like(pattern),
                    func.lower(func.coalesce(StockTx.order_ref, "")).like(pattern),
                    func.lower(func.coalesce(StockTx.listing_id, "")).like(pattern),
                    func.lower(func.coalesce(StockTx.created_by, "")).like(pattern),
                    func.lower(func.coalesce(cast(StockTx.map_qty, String), "")).like(pattern),
                )
            )

        stmt = (
            stmt.order_by(
                StockTx.occurred_at.desc(),
                StockTx.created_at.desc(),
                StockTx.pk.desc(),
            )
            .limit(max_limit)
        )

        with Session(_engine()) as session:
            rows = session.exec(stmt).all()

        return _ok(f"{len(rows)} hareket bulundu.", records=rows)
    except Exception as e:
        return _fail(StockError.db_error, e, "Filtrelenmiş hareketler okunamadı.")


def export_txs_excel(*, txs: list, output_path: str) -> Result:
    """
    Excel export (xlsx).
    """
    try:
        pd = _pandas()
        rows = []
        for tx in (txs or []):
            rows.append({
                "occurred_at": getattr(tx, "occurred_at", ""),
                "direction": getattr(tx, "direction", ""),
                "qty": getattr(tx, "qty", ""),
                "unit_cost": getattr(tx, "unit_cost", ""),
                "currency": getattr(tx, "currency", ""),
                "reason": getattr(tx, "reason", ""),
                "counterparty": getattr(tx, "counterparty", ""),
                "note": getattr(tx, "note", ""),
                "reference_id": getattr(tx, "reference_id", ""),
                "order_ref": getattr(tx, "order_ref", ""),
                "listing_id": getattr(tx, "listing_id", ""),
                "map_qty": getattr(tx, "map_qty", ""),
            })
        df = pd.DataFrame(rows)
        df.to_excel(output_path, index=False)
        return _ok("Excel export tamamlandı.", output_path=output_path)
    except Exception as e:
        return _fail(StockError.db_error, e, "Excel export yapılamadı.")




