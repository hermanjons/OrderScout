"""Local listing catalog reads shared by manual screens and other callers.

The raw reader owns the manual catalog's account/status/filter semantics. Query
operations use that complete source, then rank and page before projection; they
never infer a total from the first page. No marketplace request is performed.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from sqlalchemy import func, or_
from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Listing.models.models import ListingProduct
from settings import DB_NAME


def _filter_number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError, OverflowError):
        return None


def _within_bounds(value: float | None, bounds: tuple[float | None, float | None]) -> bool:
    minimum, maximum = bounds
    return (value is not None
            and not (minimum is not None and value < minimum)
            and not (maximum is not None and value > maximum))


def _restrict_numeric_range(stmt, column, bounds):
    minimum, maximum = bounds
    stmt = stmt.where(column.is_not(None))
    # Legacy SQLite rows may carry non-numeric storage types. Pass them through
    # to the Python conversion, including the fallback from sale to list price.
    legacy = func.typeof(column).not_in(("integer", "real"))
    if minimum is not None and math.isfinite(minimum):
        stmt = stmt.where(or_(legacy, column >= minimum))
    if maximum is not None and math.isfinite(maximum):
        stmt = stmt.where(or_(legacy, column <= maximum))
    return stmt


def read_listing_products(
    *, db_name: str = DB_NAME, api_account_ids: list[int] | None = None,
    listing_status: str | None = None, active_listings: bool | None = None,
    approved: bool | None = None, barcode: str | None = None,
    stock_code: str | None = None, brand: str | list[str] | None = None,
    product_id: str | None = None, search: str | None = None,
    quantity_bounds: tuple[float | None, float | None] | None = None,
    price_bounds: tuple[float | None, float | None] | None = None,
) -> Result:
    """Read the complete manual catalog selection without snapshot enrichment.

    As in the existing manual reader, an absent/empty account list means all
    accounts. ``active`` means on sale and not archived; it is narrower than the
    non-archived scope used by catalog search and summary.
    """
    try:
        stmt = select(ListingProduct)
        if api_account_ids:
            stmt = stmt.where(ListingProduct.api_account_id.in_(api_account_ids))
        if approved is not None:
            stmt = stmt.where(ListingProduct.approved == bool(approved))
        if barcode:
            stmt = stmt.where(ListingProduct.barcode.like(f"%{barcode}%"))
        if stock_code:
            stmt = stmt.where(ListingProduct.stock_code.like(f"%{stock_code}%"))
        if brand:
            if isinstance(brand, (list, tuple, set)):
                brands = [str(value) for value in brand if str(value)]
                if brands:
                    stmt = stmt.where(ListingProduct.brand.in_(brands))
            else:
                stmt = stmt.where(ListingProduct.brand.like(f"%{brand}%"))
        if product_id:
            stmt = stmt.where(ListingProduct.product_id.like(f"%{product_id}%"))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(
                ListingProduct.title.like(pattern), ListingProduct.barcode.like(pattern),
                ListingProduct.stock_code.like(pattern), ListingProduct.brand.like(pattern),
                ListingProduct.product_id.like(pattern),
            ))

        status = listing_status.strip().lower() if listing_status else None
        if status is None and active_listings is True:
            status = "active"
        not_archived = or_(ListingProduct.archived.is_(None), ListingProduct.archived.is_(False))
        if status == "active":
            stmt = stmt.where(ListingProduct.on_sale.is_(True), not_archived)
        elif status == "archived":
            stmt = stmt.where(ListingProduct.archived.is_(True))
        elif status == "out_of_stock":
            stmt = stmt.where(or_(ListingProduct.quantity.is_(None), ListingProduct.quantity <= 0), not_archived)

        if quantity_bounds:
            stmt = _restrict_numeric_range(stmt, ListingProduct.quantity, quantity_bounds)
        if price_bounds:
            stmt = _restrict_numeric_range(stmt, func.coalesce(ListingProduct.sale_price, ListingProduct.list_price),
                                           price_bounds)

        with Session(get_engine(db_name or DB_NAME)) as session:
            rows = list(session.exec(stmt.order_by(ListingProduct.updated_at.desc(), ListingProduct.pk)).all())
        if quantity_bounds:
            rows = [row for row in rows if _within_bounds(_filter_number(row.quantity), quantity_bounds)]
        if price_bounds:
            filtered = []
            for row in rows:
                price = _filter_number(row.sale_price)
                if price is None:
                    price = _filter_number(row.list_price)
                if _within_bounds(price, price_bounds):
                    filtered.append(row)
            rows = filtered
        return Result.ok("Ilan katalog kayitlari getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _search_text(value: Any) -> str:
    text = _text(value).casefold().translate(str.maketrans("ığüşöç", "igusoc"))
    return "".join(char for char in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(char))


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    parsed = float(str(value).strip().replace(",", "."))
    return parsed if math.isfinite(parsed) else None


def _price(row: Any) -> float | None:
    price = _number(getattr(row, "sale_price", None))
    return price if price is not None else _number(getattr(row, "list_price", None))


def _money(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def listing_currency_code(row: Any) -> str:
    """Use the manual listing editor's raw currency precedence and TRY default."""
    raw = getattr(row, "raw", None)
    if isinstance(raw, dict):
        for key in ("currencyCode", "currency_code", "currency", "currencyType", "priceCurrency"):
            code = _text(raw.get(key))
            if code:
                return code.upper()
    return "TRY"


def listing_product_detail(row: Any) -> dict[str, Any]:
    """Project one catalog record without rounding quantities or guessing prices."""
    return {
        "listing_id": getattr(row, "pk", None),
        "api_account_id": getattr(row, "api_account_id", None),
        **{key: _text(getattr(row, key, "")) for key in (
            "title", "barcode", "stock_code", "product_id", "product_code", "brand", "category_name",
        )},
        "quantity": _number(getattr(row, "quantity", None)),
        "sale_price": _money(_price(row)),
        "list_price": _money(_number(getattr(row, "list_price", None))),
        "currency": listing_currency_code(row),
        "approved": getattr(row, "approved", None),
        **{key: bool(getattr(row, key, False)) for key in ("archived", "on_sale", "locked", "has_active_campaign")},
        "product_url": _text(getattr(row, "product_url", "")),
        "stock_item_id": getattr(row, "stock_item_id", None),
    }


def _match_score(row: Any, query: str) -> int | None:
    if not query:
        return 0
    values = [_search_text(getattr(row, key, "")) for key in (
        "title", "barcode", "stock_code", "product_id", "product_code",
    )]
    haystack = " ".join(values)
    words = set(haystack.replace("-", " ").replace("_", " ").split())
    terms = [part for part in query.replace("-", " ").replace("_", " ").split() if len(part) >= 2]
    identifiers = values[1:]
    identifier_match = query in identifiers
    score = 100 if identifier_match else 0
    for identifier in identifiers:
        # A one-character product ID inside another word must not match every
        # sentence containing that letter. Preserve embedded identifier lookup
        # when the complete identifier is surrounded by word boundaries.
        if identifier and (identifier in terms or re.search(r"(?<!\w)" + re.escape(identifier) + r"(?!\w)", query)):
            score += 90
            identifier_match = True
    phrase_match = query in haystack
    if phrase_match:
        score += 30
    matched_terms = [term for term in terms if (term in haystack if len(term) >= 3 else term in words)]
    if len(terms) > 1 and not identifier_match and not phrase_match and len(matched_terms) < len(terms):
        return None
    score += sum(5 if len(term) >= 3 else 4 for term in matched_terms)
    return score if score > 0 else None


def query_listing_products(
    *, db_name: str = DB_NAME, query: str = "", limit: int = 10, offset: int = 0,
    api_account_ids: list[int] | None = None,
) -> Result:
    """Rank non-archived catalog records, retaining owner IDs and a full total.

    Exact identifiers precede text matches. Multiple free text terms must all
    match unless an identifier or the complete phrase matched. Empty queries
    sort by title. Limit is clamped to 1..50; count is the returned page length.
    """
    try:
        limit = max(1, min(50, int(limit or 10)))
        offset = max(0, int(offset))
        source = read_listing_products(db_name=db_name, api_account_ids=api_account_ids)
        if not source.success:
            return source
        clean_query = _search_text(query)
        scored = []
        for row in source.data.get("records") or []:
            if bool(row.archived):
                continue
            score = _match_score(row, clean_query)
            if score is not None:
                scored.append((score, row))
        if clean_query:
            scored.sort(key=lambda pair: (-pair[0], -(_number(pair[1].quantity) or 0), int(pair[1].pk)))
        else:
            scored.sort(key=lambda pair: (_text(pair[1].title).casefold(), int(pair[1].pk)))
        records = [row for _score, row in scored[offset:offset + limit]]
        return Result.ok(f"{len(scored)} ilan bulundu.", close_dialog=False, data={
            "query": query, "total": len(scored), "count": len(records), "offset": offset,
            "has_more": offset + len(records) < len(scored), "records": records,
        })
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def read_listing_search(
    *, db_name: str = DB_NAME, query: str = "", limit: int = 10, offset: int = 0,
    api_account_ids: list[int] | None = None,
) -> Result:
    """Serializable catalog search over the same ranked records used by lookups."""
    source = query_listing_products(db_name=db_name, query=query, limit=limit, offset=offset,
                                    api_account_ids=api_account_ids)
    if not source.success:
        return source
    try:
        data = dict(source.data)
        data["results"] = [listing_product_detail(row) for row in data.pop("records")]
        return Result.ok(source.message, close_dialog=False, data=data)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _sample(row: Any) -> dict[str, Any]:
    detail = listing_product_detail(row)
    return {key: detail[key] for key in (
        "listing_id", "api_account_id", "product_id", "title", "barcode", "stock_code",
        "quantity", "sale_price", "currency", "on_sale", "approved",
    )}


def read_listing_summary(*, db_name: str = DB_NAME, limit: int = 8,
                         api_account_ids: list[int] | None = None) -> Result:
    """Summarize all selected records; active counts mean non-archived here.

    ``needs_attention`` preserves the existing waiting-for-approval/locked count.
    ``read_listing_attention`` additionally includes stock and sale-state issues.
    Null approval is neither approved nor explicitly unapproved. Missing quantity
    belongs to the manual out-of-stock scope but remains null in returned rows.
    """
    try:
        limit = max(1, min(30, int(limit or 8)))
        source = read_listing_products(db_name=db_name, api_account_ids=api_account_ids)
        if not source.success:
            return source
        rows = source.data.get("records") or []
        active = [row for row in rows if not bool(row.archived)]
        samples = sorted(active, key=lambda row: (
            _price(row) is None, _price(row) if _price(row) is not None else 0, int(row.pk),
        ))[:limit]
        return Result.ok(f"Lokal kayda gore {len(rows)} ilan/urun kaydi var.", close_dialog=False, data={
            "total_listings": len(rows), "active_listings": len(active), "archived": len(rows) - len(active),
            "on_sale": sum(bool(row.on_sale) for row in active),
            "not_on_sale": sum(not bool(row.on_sale) for row in active),
            "approved": sum(bool(row.approved) for row in active),
            "unapproved": sum(row.approved is False for row in active),
            "locked": sum(bool(row.locked) for row in active),
            "needs_attention": sum(row.approved is False or bool(row.locked) for row in active),
            "out_of_stock": sum((_number(row.quantity) or 0) <= 0 for row in active),
            "sample_listings": [_sample(row) for row in samples],
        })
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def read_listing_attention(*, db_name: str = DB_NAME, limit: int = 12, offset: int = 0,
                           api_account_ids: list[int] | None = None) -> Result:
    """Count and page non-archived records needing stock/status attention."""
    try:
        limit = max(1, min(50, int(limit or 12)))
        offset = max(0, int(offset))
        source = read_listing_products(db_name=db_name, api_account_ids=api_account_ids)
        if not source.success:
            return source
        rows = source.data.get("records") or []
        active = [row for row in rows if not bool(row.archived)]
        attention = []
        reason_counts: dict[str, int] = {}
        for row in active:
            reasons = []
            if (_number(row.quantity) or 0) <= 0:
                reasons.append("out_of_stock")
            if row.approved is False:
                reasons.append("not_approved")
            locked = bool(row.locked) or bool(row.locked_by_unsupplied_reason)
            if locked:
                reasons.append("locked")
            if not bool(row.on_sale):
                reasons.append("not_on_sale")
            if not reasons:
                continue
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            attention.append({**_sample(row), "approved": row.approved, "locked": locked,
                              "archived": bool(row.archived), "reasons": reasons})
        attention.sort(key=lambda row: (-len(row["reasons"]), row["quantity"] or 0, row["listing_id"]))
        page = attention[offset:offset + limit]
        return Result.ok(f"{len(attention)} ilan dikkat istiyor.", close_dialog=False, data={
            "total_listings": len(rows), "active_listings": len(active), "attention_count": len(attention),
            "reason_counts": reason_counts, "listings": page, "count": len(page), "offset": offset,
            "has_more": offset + len(page) < len(attention),
        })
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
