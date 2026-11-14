"""Stock catalog queries over the same balances used by the manual screens."""
from __future__ import annotations

import unicodedata
from typing import Any

from sqlalchemy import case, func
from sqlmodel import Session, select

from Feedback.processors.pipeline import Result, map_error_to_message
from Stock.models.models import StockItem
from Stock.processors import pipeline
from Stock.processors.item_updates import THRESHOLD_FIELDS

_TURKISH_SEARCH_TRANSLATION = str.maketrans("ığüşöç", "igusoc")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _search_text(value: Any) -> str:
    text = _text(value).casefold()
    if text.isascii():
        return text
    text = text.translate(_TURKISH_SEARCH_TRANSLATION)
    return "".join(char for char in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(char))


def _match_score(item: Any, query: str, terms: list[str]) -> int:
    if not query:
        return 0
    values = [_search_text(getattr(item, field, "")) for field in (
        "sku", "name", "barcode", "brand", "category", "sub_category", "model_code", "location_code",
    )]
    haystack = " ".join(values)
    return (100 if query in (values[0], values[2]) else 0) + (30 if query in haystack else 0) + sum(
        4 for term in terms if term in haystack
    )


def _item_projection(balance_row: dict[str, Any]) -> dict[str, Any]:
    item = balance_row["item"]
    # Quantities are domain quantities, not money. Keep sub-cent quantities and
    # an unset threshold distinct from an explicit zero threshold.
    return {
        "item_id": int(item.pk),
        **{key: _text(getattr(item, key, "")) for key in (
            "sku", "name", "barcode", "brand", "category", "location_code",
        )},
        "balance": float(balance_row["on_hand"]),
        "unit": _text(getattr(item, "unit", "")) or "adet",
        **{name: balance_row.get(name) if name == "min_stock" else getattr(item, name, None)
           for name in THRESHOLD_FIELDS},
    }


def query_items_with_balances(*, db_name: str | None = None, query: str = "", limit: int = 20,
                             offset: int = 0, only_active: bool = True,
                             warehouse_id: int | None = None) -> Result:
    """Find and page stock cards; exact SKU/barcode matches rank before text matches.

    Turkish letters and diacritics are normalized. Text terms use OR matching.
    Balances always come from the canonical inventory pipeline, optionally scoped
    to one warehouse. The total counts all matches before pagination.
    """
    try:
        limit = max(1, min(100, int(limit)))
        offset = max(0, int(offset))
        source = pipeline.list_item_balances(
            warehouse_id=warehouse_id, only_active=only_active, db_name=db_name,
        )
        if not source.success:
            return source
        normalized = _search_text(query)
        terms = [part for part in normalized.replace("-", " ").replace("_", " ").split() if len(part) >= 2]
        scored = []
        for row in source.data.get("records") or []:
            score = _match_score(row["item"], normalized, terms)
            if not normalized or score > 0:
                scored.append((score, row))
        scored.sort(key=lambda pair: (-pair[0], _text(pair[1]["item"].name).casefold(), int(pair[1]["item"].pk)))
        items = [_item_projection(row) for _, row in scored[offset:offset + limit]]
        return Result.ok(f"{len(scored)} stok kaydı bulundu.", close_dialog=False, data={
            "query": query, "total": len(scored), "count": len(items), "offset": offset,
            "has_more": offset + len(items) < len(scored), "items": items,
        })
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def read_item_counts(*, db_name: str | None = None) -> Result:
    """Count catalog cards without loading movements or computing valuation."""
    try:
        stmt = select(
            func.count(),
            func.count(case((StockItem.is_active != 0, 1))),
        ).select_from(StockItem)
        with Session(pipeline._engine(db_name)) as session:
            total, active = session.exec(stmt).one()
        return Result.ok(f"{active} aktif stok kartı var.", close_dialog=False,
                         data={"total": total, "active": active, "count": active})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
