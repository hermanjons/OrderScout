"""Shared stock-card policy previews and validation; no agent or UI dependency."""
from __future__ import annotations

import math
from typing import Any

from sqlmodel import Session

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Stock.models.models import StockItem
from Stock.processors.policy_rules import THRESHOLD_FIELDS, low_stock_policy_metadata


def normalize_threshold_updates(values: dict[str, Any]) -> dict[str, float | None]:
    """Omission preserves a field; explicit None clears it and zero is a value."""
    normalized = {}
    for name in THRESHOLD_FIELDS:
        if name not in values:
            continue
        value = values[name]
        if value is None:
            normalized[name] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(f"{name}: sıfır veya pozitif sonlu bir miktar gerekir.")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"{name}: geçerli bir miktar gerekir.") from error
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{name}: sıfır veya pozitif sonlu bir miktar gerekir.")
        normalized[name] = number
    return normalized


def item_update_snapshot(item: Any) -> dict[str, Any]:
    return {"id": int(getattr(item, "pk", 0) or 0),
        **{name: str(getattr(item, name, "") or "").strip() for name in
           ("sku", "name", "barcode", "brand", "category", "sub_category")},
        "unit": str(getattr(item, "unit", "") or "adet").strip(),
        "is_active": bool(getattr(item, "is_active", True)),
        **{name: getattr(item, name, None) for name in THRESHOLD_FIELDS}}


def read_item_update_snapshot(*, item_id: int, db_name: str | None = None) -> Result:
    from Stock.processors.pipeline import _database_name
    try:
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
            return Result.fail("Geçerli tam sayı stok kartı kimliği gerekir.", close_dialog=False,
                               data={"reason": "invalid_stock_item_id"})
        with Session(get_engine(_database_name(db_name))) as session:
            item = session.get(StockItem, int(item_id))
            if item is None:
                return Result.fail("Stok kartı bulunamadı.", close_dialog=False,
                                   data={"reason": "stock_item_missing", "item_id": item_id})
            record = item_update_snapshot(item)
            comparison = {name: getattr(item, name) for name in ("sku", "name", "unit", "is_active", *THRESHOLD_FIELDS)}
        return Result.ok("Stok kartının güncel alanları okundu.", close_dialog=False,
                         data={"record": record, "expected_values": comparison})
    except Exception as error:
        return Result.fail(map_error_to_message(error), error=error, close_dialog=False)


def preview_item_threshold_update(*, item_id: int, updates: dict[str, Any], db_name: str | None = None) -> Result:
    """Read a single exact card and describe a policy patch without writing."""
    try:
        if not isinstance(updates, dict) or not updates or set(updates) - set(THRESHOLD_FIELDS):
            raise ValueError("En az bir geçerli stok eşiği alanı gerekir.")
        requested = normalize_threshold_updates(updates)
        source = read_item_update_snapshot(item_id=item_id, db_name=db_name)
        if not source.success:
            return source
        before = source.data["record"]
        after = {**before, **requested}
        changes = {name: {"before": before[name], "after": value}
                   for name, value in requested.items() if before[name] != value}
        # Bind identity/unit and the policy state the user will approve. Other
        # card annotations may change independently without authorizing a patch.
        expected = source.data["expected_values"]
        return Result.ok("Stok eşik değişikliği hazırlandı." if changes else "İstenen stok eşikleri zaten kayıtlı.",
            close_dialog=False, data={"item_id": item_id, "record": before, "requested": requested,
                "zero_minimum_disables_all_alerts": False, "low_stock_policy": low_stock_policy_metadata(),
                "write_required": bool(changes), "row": {"operation": "update", "id": before["id"],
                    "sku": before["sku"], "before": before, "after": after,
                    "changes": changes, "expected_values": expected}, "db_write_performed": False})
    except (TypeError, ValueError, OverflowError) as error:
        return Result.fail(str(error), error=error, close_dialog=False,
                           data={"reason": "invalid_stock_thresholds", "db_write_performed": False})
