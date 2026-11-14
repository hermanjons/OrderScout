"""Orders profit calculation, catalog and item reads shared with manual actions.

Optional readers at the public boundaries preserve explicit application test
seams. All default readers and calculations are owned by processors.
"""
from __future__ import annotations

from typing import Any
from Feedback.processors.pipeline import Result, map_error_to_message
from Marketplaces.constants.catalog_constants import canonical_platform_code
from settings import DB_NAME
from Account.processors.pipeline import get_active_companies
from Listing.processors.pipeline import estimate_listing_profit, get_listings_from_db, normalize_listing_cost_binding, resolve_listing_cost_source
from Finance.processors.catalog_reads import load_finance_cost_items, load_finance_cargo_tariffs as load_logistics_cargo_tariffs
from Stock.processors.pipeline import list_items as action_list_items, list_item_balances as action_list_item_balances
from Orders.processors.trendyol.pipeline import get_latest_order_items_by_numbers

ORDER_LEVEL_COST_KEYS = {"kargo", "platform-hizmet-bedeli"}
DEFAULT_SERVICE_VAT_RATE = 20.0


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _optional_float(value: Any) -> float | None:
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _record_pk(row: Any) -> int | None:
    if isinstance(row, dict):
        candidates = (row.get("pk"), row.get("id"))
    else:
        candidates = (getattr(row, "pk", None), getattr(row, "id", None))
    for value in candidates:
        try:
            key = int(value)
        except Exception:
            continue
        if key > 0:
            return key
    return None


def _amount_text(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f} TL"


def _delta_text(value: float | None) -> str:
    if value is None:
        return "-"
    if value > 0:
        return f"-{value:.2f} TL"
    if value < 0:
        return f"+{abs(value):.2f} TL"
    return "0.00 TL"


def _gross_amount(amount: Any, *, is_vat_included: bool=True, vat_rate: Any=None, default_vat_rate: Any=None) -> float | None:
    amount_val = _optional_float(amount)
    if amount_val is None:
        return None
    if is_vat_included:
        return amount_val
    rate = _optional_float(vat_rate)
    if rate is None:
        rate = _optional_float(default_vat_rate)
    if rate is None or rate < 0:
        return amount_val
    return amount_val * (1.0 + (rate / 100.0))


def _vat_amount_from_gross(amount: Any, *, vat_rate: Any=None, default_vat_rate: Any=None) -> float | None:
    amount_val = _optional_float(amount)
    if amount_val is None:
        return None
    rate = _optional_float(vat_rate)
    if rate is None:
        rate = _optional_float(default_vat_rate)
    if rate is None or rate < 0:
        return None
    if rate == 0:
        return 0.0
    return amount_val * (rate / (100.0 + rate))


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _safe_str(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _compose_linked_stock_label(stock_items: Any, *, stock_item_label_map: dict[int, str] | None, sale_quantity: float=1.0, fallback: str='') -> str:
    label_map = dict(stock_item_label_map or {})
    labels: list[str] = []
    for stock_item in list(stock_items or []):
        if not isinstance(stock_item, dict):
            continue
        try:
            stock_item_id = int(stock_item.get("stock_item_id"))
        except Exception:
            continue
        label = _safe_str(label_map.get(stock_item_id))
        if not label:
            continue
        try:
            qty_value = float(stock_item.get("qty") or 0) * float(sale_quantity)
        except Exception:
            qty_value = 0.0
        if qty_value > 0:
            labels.append(f"{label} x{qty_value:.1f}")
        else:
            labels.append(label)
    return ", ".join(labels) or _safe_str(fallback)


def _cost_items_for_platform(cost_items_cache: list[dict[str, Any]] | None, platform_code: Any) -> list[dict[str, Any]]:
    normalized_platform = canonical_platform_code(platform_code)
    if not normalized_platform:
        return [dict(row) for row in (cost_items_cache or []) if isinstance(row, dict)]
    out: list[dict[str, Any]] = []
    for row in (cost_items_cache or []):
        if not isinstance(row, dict):
            continue
        supported = [
            canonical_platform_code(value)
            for value in list(row.get("supportedPlatforms") or [])
            if canonical_platform_code(value)
        ]
        if supported and normalized_platform not in supported:
            continue
        out.append(dict(row))
    return out


def _build_cost_card_map(cost_items_cache: list[dict[str, Any]] | None, *, platform_code: Any=None) -> dict[str, dict]:
    return {
        _safe_str(row.get("costKey")).casefold(): dict(row)
        for row in _cost_items_for_platform(cost_items_cache, platform_code)
        if _safe_str(row.get("costKey"))
    }


def _cost_key(value: Any) -> str:
    return _safe_str(value).casefold()


def _is_order_level_cost(row: dict[str, Any]) -> bool:
    return _cost_key(row.get("cost_key") or row.get("costKey")) in ORDER_LEVEL_COST_KEYS


def _lookup_value_variants(value: Any) -> list[str]:
    text = _safe_str(value)
    if not text or text == "-":
        return []
    variants = [text.casefold()]
    compact = text.replace(" ", "").casefold()
    if compact and compact not in variants:
        variants.append(compact)
    return variants


def _append_listing_lookup(index_map: dict[tuple[int, str], dict], api_account_id: int, value: Any, listing: dict) -> None:
    for variant in _lookup_value_variants(value):
        index_map.setdefault((int(api_account_id), variant), listing)


def _build_listing_lookup_indexes(listings: list[dict[str, Any]]) -> dict[str, dict[tuple[int, str], dict]]:
    by_product_code: dict[tuple[int, str], dict] = {}
    by_barcode: dict[tuple[int, str], dict] = {}
    by_stock_code: dict[tuple[int, str], dict] = {}
    for listing in listings or []:
        if not isinstance(listing, dict):
            continue
        try:
            api_account_id = int(listing.get("api_account_id") or 0)
        except Exception:
            api_account_id = 0
        if api_account_id <= 0:
            continue
        _append_listing_lookup(
            by_product_code,
            api_account_id,
            listing.get("productCode") or listing.get("product_code") or listing.get("productId") or listing.get("product_id"),
            listing,
        )
        _append_listing_lookup(by_barcode, api_account_id, listing.get("barcode"), listing)
        _append_listing_lookup(
            by_stock_code,
            api_account_id,
            listing.get("stockCode") or listing.get("stock_code"),
            listing,
        )
    return {
        "by_product_code": by_product_code,
        "by_barcode": by_barcode,
        "by_stock_code": by_stock_code,
    }


def _match_listing_for_order_item(*, order_item: dict[str, Any], api_account_id: int, lookup: dict[str, dict[tuple[int, str], dict]]) -> dict[str, Any] | None:
    if api_account_id <= 0:
        return None

    def _find(index_name: str, value: Any) -> dict[str, Any] | None:
        bucket = lookup.get(index_name) or {}
        for variant in _lookup_value_variants(value):
            matched = bucket.get((int(api_account_id), variant))
            if matched is not None:
                return matched
        return None

    matched = _find("by_product_code", order_item.get("productCode") or order_item.get("product_code"))
    if matched is not None:
        return matched
    matched = _find("by_barcode", order_item.get("barcode"))
    if matched is not None:
        return matched
    return _find(
        "by_stock_code",
        order_item.get("stockCode") or order_item.get("stock_code") or order_item.get("merchantSku") or order_item.get("sku"),
    )


def _component_payload(*, key: str, label: str, total: float, vat: float, kind: str, note: str='', source_type: str='', source_trace: dict[str, Any] | None=None) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "gross": total,
        "vat": vat,
        "net": total - vat,
        "gross_text": _amount_text(total),
        "vat_text": _amount_text(vat),
        "net_text": _amount_text(total - vat),
        "note": note,
        "source_type": source_type or None,
        "source_trace": dict(source_trace or {}) or None,
    }


def _resolve_order_level_costs(*, bindings_by_key: dict[str, dict[str, Any]], cost_card_map: dict[str, dict[str, Any]], sale_price: float, order_desi: float | None, platform_code: str, cargo_tariffs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], dict[str, float], bool]:
    applied: list[dict[str, Any]] = []
    missing: list[str] = []
    totals = {"cargo_total": 0.0, "other_total": 0.0, "cargo_vat": 0.0, "other_vat": 0.0}
    complete = True

    for key in sorted(bindings_by_key.keys(), key=lambda value: 0 if value == "kargo" else 1):
        binding = dict(bindings_by_key.get(key) or {})
        card = dict(cost_card_map.get(key) or {})
        if not card:
            complete = False
            missing.append(f"Maliyet karti bulunamadi: {key}")
            continue
        label = _safe_str(card.get("name") or card.get("label") or key) or key
        normalized = normalize_listing_cost_binding(binding, card=card)
        card_currency = _safe_str(card.get("currency")).upper()
        value_type = _safe_str(card.get("valueType") or card.get("calculationType")).casefold()
        tariff_binding = key == "kargo" and normalized.get("source_type") == "builtin_resolver"
        if value_type != "percentage" and not tariff_binding and card_currency not in {"", "TRY"}:
            complete = False
            missing.append(
                f"Maliyet kartı {label} {card_currency}; doğrulanmış kur dönüşümü "
                "olmadan TRY kârı hesaplanamaz."
            )
            continue
        resolution = resolve_listing_cost_source(
            binding=normalized,
            card=card,
            context={
                "item": {"salePrice": sale_price, "dimensionalWeight": order_desi},
                "sale_price": sale_price,
                "effective_dimensional_weight": order_desi,
                "platform_code": platform_code,
                "cargo_tariffs": cargo_tariffs,
            },
        )
        if not bool(resolution.get("success")):
            complete = False
            missing.append(_safe_str(resolution.get("missing_reason")) or f"Maliyet hesabi basarisiz: {label}")
            continue
        resolved_amount = _optional_float(resolution.get("amount"))
        if resolved_amount is None:
            complete = False
            missing.append(f"Maliyet hesabi basarisiz: {label}")
            continue
        meta = dict(resolution.get("meta") or {})
        matched_tariff = dict(meta.get("matchedTariff") or {})
        tariff_currency = _safe_str(matched_tariff.get("currency")).upper()
        if tariff_currency not in {"", "TRY"}:
            complete = False
            missing.append(
                f"Kargo tarifesi {tariff_currency}; doğrulanmış kur dönüşümü "
                "olmadan TRY kârı hesaplanamaz."
            )
            continue
        gross_amount = (
            resolved_amount
            if bool(resolution.get("amount_is_gross", False))
            else _gross_amount(
                resolved_amount,
                is_vat_included=bool(card.get("isVatIncluded", True)),
                vat_rate=card.get("vatRate"),
                default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
            )
        )
        if gross_amount is None:
            complete = False
            missing.append(f"Maliyet hesabi basarisiz: {label}")
            continue

        vat_rate = matched_tariff.get("vatRate") if key == "kargo" and matched_tariff else card.get("vatRate")
        vat_amount = _vat_amount_from_gross(
            gross_amount,
            vat_rate=vat_rate,
            default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
        ) or 0.0
        note_parts: list[str] = []
        tariff_name = _safe_str(matched_tariff.get("name") or matched_tariff.get("label") or meta.get("matchedTariffName"))
        if tariff_name:
            note_parts.append(tariff_name)
        note = _safe_str(resolution.get("note"))
        if note and note not in note_parts:
            note_parts.append(note)

        if key == "kargo":
            provider = _safe_str(meta.get("selectedCargoProviderName") or meta.get("cargoProviderName"))
            if provider and provider not in note_parts:
                note_parts.append(provider)
            totals["cargo_total"] += gross_amount
            totals["cargo_vat"] += vat_amount
            kind = "cargo"
        else:
            totals["other_total"] += gross_amount
            totals["other_vat"] += vat_amount
            kind = "other"

        applied.append(
            _component_payload(
                key=key,
                label=label,
                total=gross_amount,
                vat=vat_amount,
                kind=kind,
                note=" | ".join(note_parts),
                source_type=_safe_str(resolution.get("source_type")),
                source_trace=dict(resolution.get("trace") or {}),
            )
        )

    return applied, missing, totals, complete


def _extract_item_image(item) -> str:
    candidate_keys = (
        "imageUrl",
        "imageURL",
        "productImageUrl",
        "productImageURL",
        "image",
        "image_path",
        "thumbnail",
        "pictureUrl",
    )
    for key in candidate_keys:
        value = getattr(item, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("url") or value.get("imageUrl")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def _resolve_item_total_amount(item) -> Any:
    try:
        quantity = int(getattr(item, "quantity", 0) or 0)
    except Exception:
        quantity = 0

    def _coerce(raw: Any) -> float | None:
        try:
            if raw in (None, ""):
                return None
            return float(raw)
        except Exception:
            return None

    def _same(a: float | None, b: float | None) -> bool:
        return a is not None and b is not None and abs(a - b) < 0.0001

    unit_price = _coerce(getattr(item, "lineUnitPrice", None))
    if unit_price is None:
        unit_price = _coerce(getattr(item, "price", None))
    line_gross = _coerce(getattr(item, "lineGrossAmount", None))
    amount = _coerce(getattr(item, "amount", None))

    if unit_price is not None and quantity > 0:
        return unit_price * quantity

    if line_gross is not None:
        return line_gross * quantity if quantity > 1 else line_gross
    if amount is not None:
        return amount * quantity if quantity > 1 else amount
    return None


def _resolve_item_unit_price(item) -> float | None:
    def _coerce(raw: Any) -> float | None:
        try:
            if raw in (None, ""):
                return None
            return float(raw)
        except Exception:
            return None

    for key in ("lineUnitPrice", "price"):
        value = _coerce(getattr(item, key, None))
        if value is not None:
            return value

    total_amount = _coerce(_resolve_item_total_amount(item))
    try:
        quantity = int(getattr(item, "quantity", 0) or 0)
    except Exception:
        quantity = 0
    if total_amount is not None and quantity > 0:
        return total_amount / quantity
    return None


def _normalize_order_item_account_key(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _order_item_group_key(order_number: Any, api_account_id: Any=None) -> tuple[int | None, str]:
    return (
        _normalize_order_item_account_key(api_account_id),
        str(order_number or "").strip(),
    )


def _order_item_to_view_row(item) -> dict:
    name = str(getattr(item, "productName", "") or "").strip() or "-"
    merchant_sku = str(getattr(item, "merchantSku", "") or "").strip()
    sku = merchant_sku or str(getattr(item, "sku", "") or "").strip() or "-"
    barcode = str(getattr(item, "barcode", "") or "").strip() or "-"
    qty = int(getattr(item, "quantity", 0) or 0)
    unit_price = _resolve_item_unit_price(item)
    amount = _resolve_item_total_amount(item)
    image_url = _extract_item_image(item)
    return {
        "orderNumber": str(getattr(item, "orderNumber", "") or "").strip(),
        "name": name,
        "sku": sku,
        "merchantSku": merchant_sku or sku,
        "stockCode": str(getattr(item, "stockCode", "") or "").strip() or merchant_sku or sku,
        "barcode": barcode,
        "qty": qty,
        "unit_price": unit_price,
        "amount": amount,
        "currencyCode": getattr(item, "currencyCode", None),
        "image": image_url,
        "productCode": getattr(item, "productCode", None),
        "vatRate": getattr(item, "vatRate", None),
        "api_account_id": getattr(item, "api_account_id", None),
        "lineId": getattr(item, "lineId", None),
    }


def load_order_items_for_order_numbers(order_numbers: list[str] | tuple[str, ...], *, api_account_ids: list[int] | tuple[int, ...] | None=None, db_name: str | None=None, items_reader=None) -> Result:
    items_reader = items_reader or get_latest_order_items_by_numbers
    try:
        normalized_numbers = [
            str(number or "").strip()
            for number in (order_numbers or [])
            if str(number or "").strip()
        ]
        normalized_numbers = list(dict.fromkeys(normalized_numbers))
        if not normalized_numbers:
            return Result.ok(
                "Sipariş numarası boş.",
                close_dialog=False,
                data={"items": [], "items_by_order": {}},
            )

        normalized_account_ids = [
            int(value)
            for value in (api_account_ids or [])
            if _normalize_order_item_account_key(value) is not None
        ]
        normalized_account_ids = list(dict.fromkeys(normalized_account_ids))

        res = items_reader(
            normalized_numbers,
            api_account_ids=normalized_account_ids or None,
            db_name=db_name,
        )
        if not res.success:
            return res

        item_rows = (res.data or {}).get("items", []) or []
        grouped: dict[tuple[int | None, str], list[dict]] = {}
        flat_rows: list[dict] = []
        for item in item_rows:
            view_row = _order_item_to_view_row(item)
            flat_rows.append(view_row)
            key = _order_item_group_key(
                getattr(item, "orderNumber", None),
                getattr(item, "api_account_id", None),
            )
            grouped.setdefault(key, []).append(view_row)

        return Result.ok(
            f"Sipariş ürünleri yüklendi. ({len(flat_rows)})",
            close_dialog=False,
            data={"items": flat_rows, "items_by_order": grouped},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def load_order_profit_catalog(*, api_account_ids: list[int] | None=None, db_name: str=DB_NAME, account_reader=None, listing_reader=None, stock_reader=None, balance_reader=None, cost_reader=None, tariff_reader=None) -> Result:
    account_reader = account_reader or get_active_companies
    listing_reader = listing_reader or get_listings_from_db
    stock_reader = stock_reader or action_list_items
    balance_reader = balance_reader or action_list_item_balances
    cost_reader = cost_reader or load_finance_cost_items
    tariff_reader = tariff_reader or load_logistics_cargo_tariffs
    try:
        normalized_account_ids = sorted(
            {
                int(value)
                for value in (api_account_ids or [])
                if value is not None
            }
        )

        account_platform_map: dict[int, str] = {}
        accounts_res = account_reader(db_name=db_name)
        if accounts_res.success:
            for row in (accounts_res.data or {}).get("records", []) or []:
                try:
                    account_id = int(getattr(row, "pk", None))
                except Exception:
                    continue
                if normalized_account_ids and account_id not in normalized_account_ids:
                    continue
                account_platform_map[account_id] = canonical_platform_code(getattr(row, "platform", "") or "")

        listings_res = listing_reader(
            api_account_ids=normalized_account_ids or None,
            db_name=db_name,
        )
        if not listings_res.success:
            return listings_res
        listings = [
            dict(row)
            for row in ((listings_res.data or {}).get("items", []) or [])
            if isinstance(row, dict)
        ]

        stock_item_label_map: dict[int, str] = {}
        stock_cost_map: dict[int, float] = {}
        stock_cost_meta_map: dict[int, dict[str, Any]] = {}
        stock_vat_rate_map: dict[int, float | None] = {}
        stock_dimension_map: dict[int, dict[str, float | None]] = {}

        stock_res = stock_reader(only_active=True, db_name=db_name)
        if stock_res.success:
            for row in (stock_res.data or {}).get("records", []) or []:
                item_id = _record_pk(row)
                if item_id is None:
                    continue
                stock_item_label_map[item_id] = f"{getattr(row, 'sku', '')} - {getattr(row, 'name', '')}"
                vat_rate = getattr(row, "vat_rate", None)
                try:
                    stock_vat_rate_map[item_id] = float(vat_rate) if vat_rate not in (None, "") else None
                except Exception:
                    stock_vat_rate_map[item_id] = None
                stock_dimension_map[item_id] = {
                    "weight_kg": getattr(row, "weight_kg", None),
                    "length_cm": getattr(row, "length_cm", None),
                    "width_cm": getattr(row, "width_cm", None),
                    "height_cm": getattr(row, "height_cm", None),
                }

        balances_res = balance_reader(only_active=True, db_name=db_name)
        if balances_res.success:
            for row in (balances_res.data or {}).get("records", []) or []:
                try:
                    item = row.get("item")
                    item_id = _record_pk(item)
                    if item_id is None:
                        continue
                    avg_cost = float(row.get("avg_unit_cost"))
                except Exception:
                    continue
                stock_cost_map[item_id] = avg_cost
                stock_cost_meta_map[item_id] = {
                    "input_mode": row.get("avg_cost_input_mode"),
                    "currency": _safe_str(row.get("avg_cost_currency")).upper() or None,
                }

        cost_items_cache: list[dict[str, Any]] = []
        cost_res = cost_reader(active_state="Aktif", db_name=db_name)
        if cost_res.success:
            cost_items_cache = [
                {
                    "costKey": _safe_str(row.get("costKey")),
                    "name": _safe_str(row.get("name")),
                    "label": _safe_str(row.get("name")),
                    "valueType": _safe_str(row.get("valueType") or row.get("calculationType")),
                    "defaultMatchMode": _safe_str(row.get("defaultMatchMode")) or "manual",
                    "supportedSourceTypes": list(row.get("supportedSourceTypes") or []),
                    "defaultSourceType": _safe_str(row.get("defaultSourceType")),
                    "defaultSourceConfig": dict(row.get("defaultSourceConfig") or {}) or None,
                    "defaultAmount": row.get("defaultAmount"),
                    "currency": _safe_str(row.get("currency")) or "TRY",
                    "isVatIncluded": bool(row.get("isVatIncluded", True)),
                    "vatRate": row.get("vatRate"),
                    "supportedPlatforms": list(row.get("supportedPlatforms") or []),
                }
                for row in ((cost_res.data or {}).get("records", []) or [])
                if isinstance(row, dict)
                and _safe_str(row.get("costKey"))
                and (not bool(row.get("isBuiltin")) or bool(row.get("isBuiltinAccepted")))
            ]

        cargo_tariffs_cache: list[dict[str, Any]] = []
        tariff_res = tariff_reader(active_state="Aktif", db_name=db_name)
        if tariff_res.success:
            cargo_tariffs_cache = [
                {
                    "tariffKey": _safe_str(row.get("tariffKey")),
                    "name": _safe_str(row.get("name")),
                    "label": _safe_str(row.get("name") or row.get("cargoProviderName")),
                    "cargo_provider_id": int(row.get("cargo_provider_id") or 0) or None,
                    "platformCode": _safe_str(row.get("platformCode") or row.get("platform")),
                    "platform": _safe_str(row.get("platform")),
                    "cargoProviderCode": _safe_str(row.get("cargoProviderCode")),
                    "cargoProviderName": _safe_str(row.get("cargoProviderName")),
                    "minDesi": row.get("minDesi"),
                    "maxDesi": row.get("maxDesi"),
                    "minSalePrice": row.get("minSalePrice"),
                    "maxSalePrice": row.get("maxSalePrice"),
                    "amount": row.get("amount"),
                    "currency": _safe_str(row.get("currency")),
                    "isVatIncluded": bool(row.get("isVatIncluded", True)),
                    "vatRate": row.get("vatRate"),
                    "isActive": bool(row.get("isActive", True)),
                }
                for row in ((tariff_res.data or {}).get("records", []) or [])
                if isinstance(row, dict)
                and _safe_str(row.get("tariffKey"))
                and (not bool(row.get("isBuiltin")) or bool(row.get("isBuiltinAccepted")))
            ]

        return Result.ok(
            "Siparis kar katalogu hazirlandi.",
            close_dialog=False,
            data={
                "api_account_ids": normalized_account_ids,
                "account_platform_map": account_platform_map,
                "stock_item_label_map": stock_item_label_map,
                "stock_cost_map": stock_cost_map,
                "stock_cost_meta_map": stock_cost_meta_map,
                "stock_vat_rate_map": stock_vat_rate_map,
                "stock_dimension_map": stock_dimension_map,
                "cost_items_cache": cost_items_cache,
                "cargo_tariffs_cache": cargo_tariffs_cache,
                "listings": listings,
                "listing_lookup": _build_listing_lookup_indexes(listings),
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def estimate_order_profit(*, order, order_items: list[dict[str, Any]] | None, catalog: dict[str, Any] | None, listing_estimator=None) -> dict[str, Any]:
    listing_estimator = listing_estimator or estimate_listing_profit
    order_items = [row for row in (order_items or []) if isinstance(row, dict)]
    catalog = catalog if isinstance(catalog, dict) else {}
    stock_item_label_map = catalog.get("stock_item_label_map") or {}
    stock_cost_map = catalog.get("stock_cost_map") or {}
    stock_cost_meta_map = catalog.get("stock_cost_meta_map") or {}
    stock_vat_rate_map = catalog.get("stock_vat_rate_map") or {}
    stock_dimension_map = catalog.get("stock_dimension_map") or {}
    cost_items_cache = catalog.get("cost_items_cache") or []
    cargo_tariffs_cache = catalog.get("cargo_tariffs_cache") or []
    account_platform_map = catalog.get("account_platform_map") or {}
    lookup = catalog.get("listing_lookup") or {}
    cost_card_map_cache = catalog.get("_cost_card_map_cache")
    if not isinstance(cost_card_map_cache, dict):
        cost_card_map_cache = {}
        catalog["_cost_card_map_cache"] = cost_card_map_cache

    def _cost_card_map_for(platform_code: Any) -> dict[str, dict]:
        cache_key = canonical_platform_code(platform_code)
        if cache_key not in cost_card_map_cache:
            cost_card_map_cache[cache_key] = _build_cost_card_map(
                cost_items_cache,
                platform_code=cache_key,
            )
        return cost_card_map_cache[cache_key]

    order_number = _safe_str(getattr(order, "orderNumber", ""))
    try:
        api_account_id = int(getattr(order, "api_account_id", None) or 0)
    except Exception:
        api_account_id = 0
    order_platform_code = canonical_platform_code(account_platform_map.get(api_account_id) or "")

    # The existing profit engine calculates TRY amounts and has no FX conversion
    # contract. Keep unlabelled stock costs and explicitly foreign monetary
    # inputs out of that calculation. Legacy sales/cost cards without a currency
    # retain their existing TRY behavior; stock balances now provide currency.
    currency_missing_reasons: list[str] = []
    order_currency = _safe_str(getattr(order, "currencyCode", None)).upper()
    if order_currency not in {"", "TRY"}:
        currency_missing_reasons.append(
            f"Sipariş satış para birimi {order_currency}; doğrulanmış kur dönüşümü "
            "olmadan TRY kârı hesaplanamaz."
        )
    for item in order_items:
        item_currency = _safe_str(item.get("currencyCode")).upper()
        if item_currency not in {"", "TRY"}:
            currency_missing_reasons.append(
                f"Sipariş kalemi satış para birimi {item_currency}; doğrulanmış kur "
                "dönüşümü olmadan TRY kârı hesaplanamaz."
            )
        listing = _match_listing_for_order_item(
            order_item=item, api_account_id=api_account_id, lookup=lookup,
        )
        if listing is None:
            continue
        if _optional_float(item.get("unit_price")) is None:
            listing_currency = _safe_str(listing.get("currencyCode") or listing.get("currency")).upper()
            if listing_currency not in {"", "TRY"}:
                currency_missing_reasons.append(
                    f"İlan satış para birimi {listing_currency}; doğrulanmış kur "
                    "dönüşümü olmadan TRY kârı hesaplanamaz."
                )
        listing_platform = canonical_platform_code(account_platform_map.get(listing.get("api_account_id")) or "")
        cards = _cost_card_map_for(listing_platform)
        for binding in listing.get("cost_items") or []:
            if not isinstance(binding, dict):
                continue
            key = _cost_key(binding.get("cost_key") or binding.get("costKey"))
            card = cards.get(key) or {}
            value_type = _safe_str(card.get("valueType") or card.get("calculationType")).casefold()
            normalized_binding = normalize_listing_cost_binding(binding, card=card)
            tariff_binding = key == "kargo" and normalized_binding.get("source_type") == "builtin_resolver"
            card_currency = _safe_str(card.get("currency")).upper()
            if value_type != "percentage" and not tariff_binding and card_currency not in {"", "TRY"}:
                label = _safe_str(card.get("name") or card.get("label") or key)
                currency_missing_reasons.append(
                    f"Maliyet kartı {label} {card_currency}; doğrulanmış kur dönüşümü "
                    "olmadan TRY kârı hesaplanamaz."
                )
        for stock_row in listing.get("stock_items") or []:
            if not isinstance(stock_row, dict):
                continue
            try:
                stock_item_id = int(stock_row.get("stock_item_id"))
            except (TypeError, ValueError):
                continue
            if (_optional_float(stock_row.get("qty")) or 0.0) <= 0:
                continue
            if _optional_float(stock_cost_map.get(stock_item_id)) is None:
                continue  # The existing estimator reports missing cost itself.
            cost_currency = _safe_str(
                (stock_cost_meta_map.get(stock_item_id) or {}).get("currency")
            ).upper()
            if not cost_currency:
                currency_missing_reasons.append(
                    f"Stok kartı maliyet para birimi eksik: #{stock_item_id}."
                )
            elif cost_currency != "TRY":
                currency_missing_reasons.append(
                    f"Stok kartı maliyeti {cost_currency}: #{stock_item_id}; "
                    "doğrulanmış kur dönüşümü olmadan TRY kârı hesaplanamaz."
                )
    if currency_missing_reasons:
        return {
            "estimated_profit": None,
            "estimated_profit_text": "-",
            "estimated_profit_ready": False,
            "estimated_profit_breakdown": [],
            "estimated_profit_detail": {
                "summary": {"order_number": order_number, "line_count": len(order_items),
                            "line_count_text": str(len(order_items))},
                "results": {},
                "lines": [],
            },
            "estimated_profit_missing_reasons": _dedupe_preserve_order(currency_missing_reasons),
        }

    if not order_items:
        return {
            "estimated_profit": None,
            "estimated_profit_text": "-",
            "estimated_profit_ready": False,
            "estimated_profit_breakdown": [],
            "estimated_profit_detail": {
                "summary": {"order_number": order_number, "line_count": 0, "line_count_text": "0"},
                "results": {},
                "lines": [],
            },
            "estimated_profit_missing_reasons": ["Siparis urunleri bulunamadi."],
        }

    line_entries: list[dict[str, Any]] = []
    combined_applied_costs: list[dict[str, Any]] = []
    order_level_bindings: dict[str, dict[str, Any]] = {}
    missing_reasons: list[str] = []
    complete = True
    matched_line_count = 0
    total_quantity = 0.0
    order_desi_total = 0.0
    has_order_desi = False
    totals = {
        "sale_price": 0.0,
        "payout_total": 0.0,
        "total_costs": 0.0,
        "input_vat_total": 0.0,
        "sale_vat": 0.0,
        "net_vat": 0.0,
        "estimated_profit": 0.0,
    }

    for item in order_items:
        qty_value = _optional_float(item.get("qty")) or 0.0
        if qty_value <= 0:
            qty_value = 1.0
        total_quantity += qty_value
        item_title = _safe_str(item.get("name")) or _safe_str(item.get("sku")) or _safe_str(item.get("barcode")) or "Urun"
        unit_sale_price = _optional_float(item.get("unit_price"))
        line_amount = (
            (unit_sale_price * qty_value)
            if unit_sale_price is not None
            else _optional_float(item.get("amount"))
        )
        matched_listing = _match_listing_for_order_item(order_item=item, api_account_id=api_account_id, lookup=lookup)
        if matched_listing is None:
            complete = False
            missing_reasons.append(f"Ilan eslesmesi bulunamadi: {item_title}")
            line_entries.append(
                {
                    "title": item_title,
                    "qty": qty_value,
                    "qty_text": f"{qty_value:.0f}" if float(qty_value).is_integer() else f"{qty_value:.2f}",
                    "unit_price": unit_sale_price,
                    "unit_price_text": _amount_text(unit_sale_price),
                    "amount": line_amount,
                    "amount_text": _amount_text(line_amount),
                    "listing_title": "",
                    "matched": False,
                    "estimated_profit": None,
                    "estimated_profit_text": "-",
                    "estimated_profit_ready": False,
                    "missing_reasons": ["Ilan eslesmesi bulunamadi."],
                }
            )
            continue

        matched_line_count += 1
        listing = dict(matched_listing)
        if unit_sale_price is not None:
            listing["salePrice"] = unit_sale_price
        order_vat_rate = _optional_float(item.get("vatRate"))
        if order_vat_rate is not None:
            listing["vatRate"] = order_vat_rate
        listing["linked_stock_label"] = _compose_linked_stock_label(
            listing.get("stock_items"),
            stock_item_label_map=stock_item_label_map,
            sale_quantity=qty_value,
            fallback=_safe_str(listing.get("linked_stock_label")),
        )
        listing_cost_items = [row for row in list(listing.get("cost_items") or []) if isinstance(row, dict)]
        for row in listing_cost_items:
            key = _cost_key(row.get("cost_key") or row.get("costKey"))
            if key in ORDER_LEVEL_COST_KEYS and key not in order_level_bindings:
                order_level_bindings[key] = dict(row)
        listing["cost_items"] = [row for row in listing_cost_items if not _is_order_level_cost(row)]

        listing_platform = canonical_platform_code(account_platform_map.get(listing.get("api_account_id")) or "")
        estimation = listing_estimator(
            item=listing,
            stock_cost_map=stock_cost_map,
            stock_vat_rate_map=stock_vat_rate_map,
            stock_cost_meta_map=stock_cost_meta_map,
            stock_dimension_map=stock_dimension_map,
            cost_card_map=_cost_card_map_for(listing_platform),
            cargo_tariffs=cargo_tariffs_cache,
            platform_code=listing_platform,
            sale_quantity=qty_value,
        )

        line_ready = bool(estimation.get("estimated_profit_ready"))
        if not line_ready:
            complete = False
        for reason in list(estimation.get("estimated_profit_missing_reasons") or []):
            missing_reasons.append(f"{item_title}: {reason}")

        detail = dict(estimation.get("estimated_profit_detail") or {})
        results = dict(detail.get("results") or {})
        summary = dict(detail.get("summary") or {})
        for component in list(detail.get("applied_costs") or []):
            if not isinstance(component, dict):
                continue
            component_row = dict(component)
            note = _safe_str(component_row.get("note"))
            component_row["note"] = f"{item_title} | {note}" if note else item_title
            combined_applied_costs.append(component_row)
        line_desi = _optional_float(summary.get("stock_total_desi"))
        if line_desi is None:
            line_desi = _optional_float(summary.get("dimensional_weight"))
        if line_desi is not None and line_desi > 0:
            order_desi_total += line_desi
            has_order_desi = True
        sale_price_total = _optional_float(summary.get("sale_price"))
        if sale_price_total is None:
            sale_price_total = line_amount

        totals["sale_price"] += float(sale_price_total or 0.0)
        totals["payout_total"] += float(_optional_float(results.get("payout_total")) or 0.0)
        totals["total_costs"] += float(_optional_float(results.get("total_costs")) or 0.0)
        totals["input_vat_total"] += float(_optional_float(results.get("input_vat_total")) or 0.0)
        totals["sale_vat"] += float(_optional_float(results.get("sale_vat")) or 0.0)
        totals["net_vat"] += float(_optional_float(results.get("net_vat")) or 0.0)
        totals["estimated_profit"] += float(_optional_float(estimation.get("estimated_profit")) or 0.0)

        line_entries.append(
            {
                "title": item_title,
                "qty": qty_value,
                "qty_text": f"{qty_value:.0f}" if float(qty_value).is_integer() else f"{qty_value:.2f}",
                "unit_price": unit_sale_price,
                "unit_price_text": _amount_text(unit_sale_price),
                "amount": line_amount,
                "amount_text": _amount_text(line_amount),
                "listing_title": _safe_str(listing.get("title")) or item_title,
                "matched": True,
                "estimated_profit": estimation.get("estimated_profit"),
                "estimated_profit_text": _safe_str(estimation.get("estimated_profit_text")) or "-",
                "estimated_profit_ready": line_ready,
                "missing_reasons": list(estimation.get("estimated_profit_missing_reasons") or []),
                "detail": detail,
                "breakdown": list(estimation.get("estimated_profit_breakdown") or []),
            }
        )

    order_level_cost_map = _cost_card_map_for(order_platform_code)
    order_level_applied, order_level_missing, order_level_totals, order_level_complete = _resolve_order_level_costs(
        bindings_by_key=order_level_bindings,
        cost_card_map=order_level_cost_map,
        sale_price=totals["sale_price"],
        order_desi=order_desi_total if has_order_desi else None,
        platform_code=order_platform_code,
        cargo_tariffs=cargo_tariffs_cache,
    )
    combined_applied_costs.extend(order_level_applied)
    missing_reasons.extend(order_level_missing)
    if not order_level_complete:
        complete = False
    totals["total_costs"] += order_level_totals["cargo_total"] + order_level_totals["other_total"]
    totals["input_vat_total"] += order_level_totals["cargo_vat"] + order_level_totals["other_vat"]
    totals["payout_total"] -= order_level_totals["cargo_total"]
    totals["net_vat"] = totals["sale_vat"] - totals["input_vat_total"]
    totals["estimated_profit"] = totals["sale_price"] - totals["total_costs"] - totals["net_vat"]

    estimated_profit_value = totals["estimated_profit"] if line_entries and complete else None
    marketplace_deductions = totals["sale_price"] - totals["payout_total"]
    return {
        "estimated_profit": estimated_profit_value,
        "estimated_profit_text": _amount_text(estimated_profit_value) if complete and estimated_profit_value is not None else "-",
        "estimated_profit_ready": bool(complete and estimated_profit_value is not None),
        "estimated_profit_breakdown": [],
        "estimated_profit_detail": {
            "summary": {
                "order_number": order_number,
                "line_count": len(line_entries),
                "line_count_text": str(len(line_entries)),
                "matched_line_count": matched_line_count,
                "matched_line_count_text": str(matched_line_count),
                "item_quantity_total": total_quantity,
                "item_quantity_total_text": f"{total_quantity:.0f}" if float(total_quantity).is_integer() else f"{total_quantity:.2f}",
                "sale_price": totals["sale_price"],
                "sale_price_text": _amount_text(totals["sale_price"]),
            },
            "applied_costs": combined_applied_costs,
            "results": {
                "payout_total": totals["payout_total"],
                "payout_total_text": _amount_text(totals["payout_total"]),
                "marketplace_deductions": marketplace_deductions,
                "marketplace_deductions_text": _amount_text(marketplace_deductions),
                "total_costs": totals["total_costs"],
                "total_costs_text": _amount_text(totals["total_costs"]),
                "input_vat_total": totals["input_vat_total"],
                "input_vat_total_text": _amount_text(totals["input_vat_total"]),
                "sale_vat": totals["sale_vat"],
                "sale_vat_text": _amount_text(totals["sale_vat"]),
                "net_vat": totals["net_vat"],
                "net_vat_text": _delta_text(totals["net_vat"]),
                "estimated_profit": estimated_profit_value,
                "estimated_profit_text": _amount_text(estimated_profit_value),
            },
            "lines": line_entries,
        },
        "estimated_profit_missing_reasons": _dedupe_preserve_order(missing_reasons),
    }

def _normalize_profit_account_ids(api_account_ids: list[int] | None) -> list[int] | None:
    if api_account_ids is None:
        return None
    if (not isinstance(api_account_ids, (list, tuple)) or not api_account_ids
            or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                   for value in api_account_ids)):
        raise ValueError("api_account_ids must contain positive account IDs.")
    return sorted(set(api_account_ids))


def estimate_orders_profit_summary(
    *,
    orders: list[Any] | tuple[Any, ...],
    db_name: str = DB_NAME,
    api_account_ids: list[int] | None = None,
    catalog_reader=None, items_reader=None, order_estimator=None,
) -> Result:
    """Aggregate account-scoped estimates using the same engine as manual orders."""
    catalog_reader = catalog_reader or load_order_profit_catalog
    items_reader = items_reader or load_order_items_for_order_numbers
    order_estimator = order_estimator or estimate_order_profit
    try:
        account_filter = _normalize_profit_account_ids(api_account_ids)
        scoped_orders = [
            order
            for order in list(orders or [])
            if _safe_str(getattr(order, "orderNumber", ""))
            and (account_filter is None or getattr(order, "api_account_id", None) in account_filter)
        ]
        # Order numbers are only unique within an account; keep its latest snapshot.
        latest_orders = {}
        for order in scoped_orders:
            key = (getattr(order, "api_account_id", None), _safe_str(getattr(order, "orderNumber", "")))
            current = latest_orders.get(key)
            rank = lambda row: (int(getattr(row, "lastModifiedDate", 0) or 0), int(getattr(row, "pk", 0) or 0))
            if current is None or rank(order) >= rank(current):
                latest_orders[key] = order
        scoped_orders = list(latest_orders.values())
        if not scoped_orders:
            return Result.ok(
                "Siparis olmadigi icin tahmini kar 0 TRY.",
                close_dialog=False,
                data={
                    "estimated_profit": 0.0,
                    "partial_estimated_profit": 0.0,
                    "estimated_profit_ready": True,
                    "revenue": 0.0,
                    "order_count": 0,
                    "complete_order_count": 0,
                    "incomplete_order_count": 0,
                    "missing_reasons": [],
                    "rows": [],
                    "requested_api_account_ids": account_filter or [],
                    "api_account_ids": [],
                },
            )

        account_id_set: set[int] = set()
        for order in scoped_orders:
            account_id = _normalize_order_item_account_key(
                getattr(order, "api_account_id", None)
            )
            if isinstance(account_id, int) and account_id > 0:
                account_id_set.add(account_id)
        account_ids = sorted(account_id_set)
        catalog_res = catalog_reader(
            api_account_ids=account_ids or None,
            db_name=db_name,
        )
        if not catalog_res.success:
            return catalog_res
        catalog = dict(catalog_res.data or {})

        order_numbers = [
            _safe_str(getattr(order, "orderNumber", ""))
            for order in scoped_orders
        ]
        items_res = items_reader(
            order_numbers,
            api_account_ids=account_ids or None,
            db_name=db_name,
        )
        if not items_res.success:
            return items_res
        items_by_order = dict((items_res.data or {}).get("items_by_order") or {})

        complete_count = 0
        partial_profit = 0.0
        revenue = 0.0
        missing_reasons: list[str] = []
        rows: list[dict[str, Any]] = []
        for order in scoped_orders:
            order_number = _safe_str(getattr(order, "orderNumber", ""))
            account_id = _normalize_order_item_account_key(getattr(order, "api_account_id", None))
            items = list(items_by_order.get((account_id, order_number), []) or [])
            estimation = order_estimator(
                order=order,
                order_items=items,
                catalog=catalog,
            )
            ready = bool(estimation.get("estimated_profit_ready"))
            value = _optional_float(estimation.get("estimated_profit"))
            if ready and value is not None:
                complete_count += 1
                partial_profit += value
            for reason in list(estimation.get("estimated_profit_missing_reasons") or []):
                clean_reason = _safe_str(reason)
                if clean_reason:
                    missing_reasons.append(f"{order_number}: {clean_reason}")
            order_revenue = _optional_float(
                getattr(order, "packageTotalPrice", None)
                or getattr(order, "totalPrice", None)
            )
            revenue += float(order_revenue or 0.0)
            rows.append(
                {
                    "order_number": order_number,
                    "api_account_id": account_id,
                    "estimated_profit_ready": ready,
                    "estimated_profit": value if ready else None,
                    "missing_reasons": list(estimation.get("estimated_profit_missing_reasons") or []),
                }
            )

        total_count = len(scoped_orders)
        incomplete_count = total_count - complete_count
        ready = incomplete_count == 0
        estimated_profit = partial_profit if ready else None
        deduped_reasons = _dedupe_preserve_order(missing_reasons)
        if ready:
            message = f"{total_count} siparis icin tahmini kar {estimated_profit:.2f} TRY."
        else:
            message = (
                f"Tahmini kar hesaplanamadi: {incomplete_count}/{total_count} sipariste "
                "maliyet, para birimi veya ilan esleme verisi eksik ya da uyumsuz."
            )
        return Result.ok(
            message,
            close_dialog=False,
            data={
                "estimated_profit": estimated_profit,
                "partial_estimated_profit": partial_profit if complete_count else None,
                "estimated_profit_ready": ready,
                "revenue": revenue,
                "order_count": total_count,
                "complete_order_count": complete_count,
                "incomplete_order_count": incomplete_count,
                "missing_reasons": deduped_reasons[:50],
                "rows": rows,
                "requested_api_account_ids": account_filter or [],
                "api_account_ids": account_ids,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
