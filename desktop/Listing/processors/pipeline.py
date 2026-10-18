# Listing/processors/pipeline.py
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from typing import Any, Optional

from sqlmodel import Session, select
from sqlalchemy import delete, func, or_

from settings import DB_NAME
from Feedback.processors.pipeline import Result, map_error_to_message
from Core.utils.model_utils import create_records, get_engine, update_records
from Finance.constants.domain_constants import FINANCE_COST_SOURCE_DEFINITIONS
from Finance.processors.rule_loader import resolve_finance_rule
from Finance.processors.pipeline import (
    cost_source_type_label,
    default_source_binding_for_cost_card,
    normalize_cost_source_config,
    normalize_cost_source_type,
    source_type_to_legacy_match_mode,
)
from Logistics.processors.cargo_amount_matcher import match_cargo_amount
from Listing.constants.platform_constants import canonical_platform_code
from Listing.models import (
    ListingProduct,
    ListingProductStockSnapshot,
    ListingProductCostSnapshot,
    ListingProductHistory,
)
from Listing.signals.signals import listing_signals
from Account.models.models import ApiAccount
from Logistics.models.models import LogisticsCargoProvider
from Finance.models.trendyol.models import FinanceCostItem
from Stock.models import StockItem

_ENGINE_CACHE: dict[str, Any] = {}


def _engine(db_name: str = DB_NAME):
    key = str(db_name or DB_NAME)
    engine = _ENGINE_CACHE.get(key)
    if engine is None:
        engine = get_engine(key)
        _ENGINE_CACHE[key] = engine
    return engine


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _product_id_from_item(item: dict) -> str:
    return str(
        item.get("productId")
        or item.get("variantId")
        or item.get("contentId")
        or item.get("platformListingId")
        or item.get("product_id")
        or item.get("id")
        or item.get("barcode")
        or item.get("stockCode")
        or ""
    ).strip()


def _safe_int_id(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _cargo_provider_id_from_source_config(source_config: Any) -> Optional[int]:
    if not isinstance(source_config, dict):
        return None
    return _safe_int_id(
        source_config.get("cargoProviderId")
        if "cargoProviderId" in source_config
        else source_config.get("cargo_provider_id")
    )


def _cargo_provider_code_from_source_config(source_config: Any) -> str:
    if not isinstance(source_config, dict):
        return ""
    return str(
        source_config.get("cargoProviderCode")
        if "cargoProviderCode" in source_config
        else source_config.get("cargo_provider_code")
        or ""
    ).strip().upper()


def _binding_requires_cargo_provider(
    *,
    cost_key: Any,
    source_type: Any = None,
    source_config: Any = None,
) -> bool:
    normalized_key = str(cost_key or "").strip().casefold()
    if normalized_key == "kargo":
        return True
    normalized_source_type = str(source_type or "").strip().casefold()
    if normalized_source_type != "builtin_resolver":
        return False
    if not isinstance(source_config, dict):
        return False
    resolver_key = str(
        source_config.get("ruleKey")
        or source_config.get("resolverKey")
        or source_config.get("resolver_key")
        or ""
    ).strip().casefold()
    return resolver_key == "cargo_amount_matcher"


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _lookup_path_value(value: Any, path: str) -> Any:
    current = value
    for raw_part in [part for part in str(path).split(".") if str(part).strip()]:
        part = str(raw_part).strip()
        if isinstance(current, dict):
            current = current.get(part)
            continue
        if isinstance(current, (list, tuple)) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(current):
                current = current[idx]
                continue
        return None
    return current


def normalize_listing_cost_binding(
    row: dict[str, Any] | None,
    *,
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(row or {})
    cost_key = _compact_text(payload.get("cost_key") or payload.get("costKey"))
    default_source_type, default_source_config = default_source_binding_for_cost_card(card, cost_key=cost_key)

    source_type = normalize_cost_source_type(
        payload.get("source_type") or payload.get("sourceType") or payload.get("calculation_type") or payload.get("calculationType"),
        fallback=default_source_type,
    )
    source_config = normalize_cost_source_config(
        source_type,
        payload.get("source_config") or payload.get("sourceConfig"),
        cost_key=cost_key,
        card=card,
    )
    if source_config is None and source_type == default_source_type:
        source_config = deepcopy(default_source_config)

    amount = None
    if source_type == "manual_value":
        if isinstance(source_config, dict):
            amount = _optional_float(source_config.get("amount"))
        if amount is None:
            amount = _optional_float(payload.get("amount"))
            if amount is not None:
                source_config = {"amount": amount}
        if amount is None:
            source_config = None

    return {
        "cost_key": cost_key,
        "calculation_type": source_type_to_legacy_match_mode(source_type),
        "source_type": source_type,
        "source_config": deepcopy(source_config) if isinstance(source_config, dict) else None,
        "amount": amount,
        "quantity": None,
        "tariff_key": _compact_text(payload.get("tariff_key") or payload.get("tariffKey")) or None,
    }


def resolve_listing_cost_source(
    *,
    binding: dict[str, Any],
    card: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = normalize_listing_cost_binding(binding, card=card)
    source_type = normalized.get("source_type") or "manual_value"
    source_config = dict(normalized.get("source_config") or {})
    context_payload = context or {}
    value_type = _compact_text((card or {}).get("valueType") or (card or {}).get("calculationType")).casefold() or "numeric"

    if not bool((FINANCE_COST_SOURCE_DEFINITIONS.get(source_type) or {}).get("enabled", False)):
        return {
            "success": False,
            "source_type": source_type,
            "missing_reason": f"Kaynak tipi henüz etkin değil: {cost_source_type_label(source_type)}",
            "trace": {
                "sourceType": source_type,
                "sourceConfig": deepcopy(source_config),
            },
        }

    if source_type == "manual_value":
        raw_amount = _optional_float(normalized.get("amount"))
        if raw_amount is None:
            return {
                "success": False,
                "source_type": source_type,
                "missing_reason": f"Maliyet değeri eksik: {_compact_text((card or {}).get('name')) or _compact_text(binding.get('cost_key'))}",
                "trace": {
                    "sourceType": source_type,
                    "sourceConfig": deepcopy(source_config),
                },
            }
        if value_type == "percentage":
            sale_price = _optional_float(context_payload.get("sale_price"))
            if sale_price is None:
                return {
                    "success": False,
                    "source_type": source_type,
                    "missing_reason": "Satış fiyatı olmadan yüzdesel maliyet hesaplanamaz.",
                    "trace": {
                        "sourceType": source_type,
                        "rawAmount": raw_amount,
                    },
                }
            computed_amount = sale_price * (raw_amount / 100.0)
            return {
                "success": True,
                "source_type": source_type,
                "amount": computed_amount,
                "raw_amount": raw_amount,
                "amount_is_gross": False,
                "note": f"%{raw_amount:.2f}",
                "trace": {
                    "sourceType": source_type,
                    "rawAmount": raw_amount,
                    "salePrice": sale_price,
                },
            }
        return {
            "success": True,
            "source_type": source_type,
            "amount": raw_amount,
            "raw_amount": raw_amount,
            "amount_is_gross": False,
            "note": "",
            "trace": {
                "sourceType": source_type,
                "rawAmount": raw_amount,
            },
        }

    if source_type == "db_field":
        field_path = _compact_text(source_config.get("fieldPath"))
        field_label = _compact_text(source_config.get("label")) or field_path
        item_payload = dict(context_payload.get("item") or {})
        raw_value = _lookup_path_value(item_payload, field_path) if field_path else None
        numeric_value = _optional_float(raw_value)
        if numeric_value is None:
            field_label = _compact_text(source_config.get("label")) or field_path
            return {
                "success": False,
                "source_type": source_type,
                "missing_reason": f"Veri alanı değeri bulunamadı: {field_label or 'alan'}",
                "trace": {
                    "sourceType": source_type,
                    "sourceConfig": deepcopy(source_config),
                    "rawValue": raw_value,
                },
            }
        if value_type == "percentage":
            sale_price = _optional_float(context_payload.get("sale_price"))
            if sale_price is None:
                return {
                    "success": False,
                    "source_type": source_type,
                    "missing_reason": "Satış fiyatı olmadan yüzdesel maliyet hesaplanamaz.",
                    "trace": {
                        "sourceType": source_type,
                        "rawValue": raw_value,
                    },
                }
            computed_amount = sale_price * (numeric_value / 100.0)
            return {
                "success": True,
                "source_type": source_type,
                "amount": computed_amount,
                "raw_amount": numeric_value,
                "amount_is_gross": False,
                "note": field_label or f"%{numeric_value:.2f}",
                "trace": {
                    "sourceType": source_type,
                    "rawValue": raw_value,
                    "salePrice": sale_price,
                },
            }
        return {
            "success": True,
            "source_type": source_type,
            "amount": numeric_value,
            "raw_amount": numeric_value,
            "amount_is_gross": False,
            "note": field_label,
            "trace": {
                "sourceType": source_type,
                "rawValue": raw_value,
            },
        }

    if source_type == "builtin_resolver":
        resolver_key = str(source_config.get("ruleKey") or "").strip() or str(source_config.get("resolverKey") or "").strip()
        if not resolver_key:
            return {
                "success": False,
                "source_type": source_type,
                "missing_reason": "Kural anahtarı bulunamadı.",
                "trace": {
                    "sourceType": source_type,
                    "sourceConfig": deepcopy(source_config),
                },
            }
        try:
            resolved = resolve_finance_rule(resolver_key, source_config, context_payload)
        except Exception:
            return {
                "success": False,
                "source_type": source_type,
                "missing_reason": f"Kural çözücüsü bulunamadı: {resolver_key or 'builtin'}",
                "trace": {
                    "sourceType": source_type,
                    "sourceConfig": deepcopy(source_config),
                },
            }
        amount = _optional_float(resolved.get("amount"))
        if amount is None:
            return {
                "success": False,
                "source_type": source_type,
                "missing_reason": _compact_text(resolved.get("missing_reason")) or "Otomatik maliyet çözümlenemedi.",
                "trace": {
                    "sourceType": source_type,
                    "sourceConfig": deepcopy(source_config),
                    "resolverPayload": deepcopy(resolved),
                },
            }
        return {
            "success": True,
            "source_type": source_type,
            "amount": amount,
            "raw_amount": _optional_float(resolved.get("raw_amount")) if resolved.get("raw_amount") not in (None, "") else amount,
            "amount_is_gross": bool(resolved.get("amount_is_gross", False)),
            "note": _compact_text(resolved.get("note")),
            "trace": {
                "sourceType": source_type,
                "sourceConfig": deepcopy(source_config),
                "resolverPayload": deepcopy(resolved),
            },
            "meta": deepcopy(dict(resolved.get("meta") or {})),
        }

    return {
        "success": True,
        "source_type": source_type,
        "amount": None,
        "raw_amount": None,
        "amount_is_gross": False,
        "note": "",
        "trace": {
            "sourceType": source_type,
            "sourceConfig": deepcopy(source_config),
        },
    }


def _normalize_listing_item(item: dict) -> Optional[dict]:
    if not isinstance(item, dict):
        return None

    product_id = _product_id_from_item(item)
    api_account_id = item.get("api_account_id")
    if not product_id or api_account_id is None:
        return None

    def _first_non_none(*vals):
        for v in vals:
            if v is not None:
                return v
        return None

    def _to_float(val):
        if val is None or val == "":
            return None
        try:
            return float(val)
        except Exception:
            return None

    def _nested_name(val):
        if isinstance(val, dict):
            return val.get("name")
        return val

    def _nested_id(val):
        if isinstance(val, dict):
            return val.get("id")
        return None

    title = item.get("title") or item.get("name") or item.get("productName")
    barcode = item.get("barcode")
    stock_code = item.get("stockCode") or item.get("stock_code")
    brand = _nested_name(item.get("brand") or item.get("brandName"))
    quantity = _first_non_none(item.get("quantity"), item.get("stockQuantity"), item.get("stock"))
    approved = item.get("approved")
    archived = item.get("archived")
    on_sale = item.get("onsale")
    if on_sale is None:
        on_sale = item.get("onSale")
    category_name = _nested_name(item.get("category") or item.get("categoryName"))
    images = item.get("images")
    if images is None:
        images = item.get("media")
    delivery_option = item.get("deliveryOption")
    if delivery_option is None:
        delivery_option = item.get("deliveryOptions")
    if isinstance(quantity, dict):
        quantity = _first_non_none(quantity.get("quantity"), quantity.get("stockQuantity"))
    price_block = item.get("price") if isinstance(item.get("price"), dict) else {}

    return {
        "api_account_id": int(api_account_id),
        "product_id": str(product_id),
        "product_code": str(item.get("productCode") or "") or None,
        "batch_request_id": item.get("batchRequestId"),
        "supplier_id": item.get("supplierId"),
        "create_datetime": item.get("createDateTime") or item.get("creationDate") or item.get("sellerCreatedDate"),
        "last_update_date": item.get("lastUpdateDate") or item.get("lastModifiedDate") or item.get("sellerModifiedDate"),
        "gender": item.get("gender"),
        "category_name": category_name,
        "product_main_id": item.get("productMainId"),
        "description": item.get("description"),
        "stock_unit_type": item.get("stockUnitType"),

        "title": title,
        "barcode": barcode,
        "stock_code": stock_code,
        "brand": brand,
        "quantity": _to_float(quantity),
        "approved": approved,
        "archived": archived,
        "on_sale": on_sale,

        "list_price": _to_float(item.get("listPrice") or price_block.get("listPrice")),
        "sale_price": _to_float(item.get("salePrice") or price_block.get("salePrice")),
        "vat_rate": _to_float(item.get("vatRate")),
        "dimensional_weight": _to_float(item.get("dimensionalWeight")),
        "location_based_delivery": item.get("locationBasedDelivery"),
        "lot_number": item.get("lotNumber"),
        "special_consumption_tax": _to_float(item.get("specialConsumptionTax")),
        "delivery_option": delivery_option,
        "images": images,
        "attributes": item.get("attributes"),
        "platform_listing_id": item.get("platformListingId") or item.get("contentId"),
        "stock_id": item.get("stockId"),
        "has_active_campaign": item.get("hasActiveCampaign"),
        "locked": item.get("locked"),
        "product_content_id": item.get("productContentId") or item.get("contentId"),
        "pim_category_id": item.get("pimCategoryId"),
        "brand_id": item.get("brandId") or _nested_id(item.get("brand")),
        "version": item.get("version"),
        "color": item.get("color"),
        "size": item.get("size"),
        "locked_by_unsupplied_reason": item.get("lockedByUnSuppliedReason"),
        "product_url": item.get("productUrl"),
        "raw": item,
    }


def _normalize_stock_items(items: list[dict]) -> list[dict]:
    merged: dict[int, float] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        stock_id = it.get("stock_item_id") or it.get("id")
        if stock_id is None:
            continue
        try:
            stock_id = int(stock_id)
        except Exception:
            continue

        qty_raw = it.get("qty") if "qty" in it else it.get("quantity")
        try:
            qty_val = float(qty_raw)
        except Exception:
            qty_val = 0.0
        if qty_val <= 0:
            continue
        merged[stock_id] = merged.get(stock_id, 0.0) + qty_val

    return [{"stock_item_id": k, "qty": v} for k, v in merged.items()]


LISTING_CHANGE_FIELDS: set[str] = {
    "product_code",
    "supplier_id",
    "gender",
    "category_name",
    "product_main_id",
    "description",
    "stock_unit_type",
    "title",
    "barcode",
    "stock_code",
    "brand",
    "quantity",
    "approved",
    "archived",
    "on_sale",
    "list_price",
    "sale_price",
    "vat_rate",
    "dimensional_weight",
    "location_based_delivery",
    "lot_number",
    "special_consumption_tax",
    "delivery_option",
    "images",
    "attributes",
    "platform_listing_id",
    "stock_id",
    "has_active_campaign",
    "locked",
    "product_content_id",
    "pim_category_id",
    "brand_id",
    "color",
    "size",
    "locked_by_unsupplied_reason",
    "product_url",
}

_LISTING_JSON_LIKE_FIELDS: set[str] = {"delivery_option", "images", "attributes"}


def _canonical_listing_compare_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_listing_compare_value(val)
            for key, val in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        normalized = [_canonical_listing_compare_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, str):
        return value.strip()
    return value


def _listing_field_values_equal(field_name: str, left: Any, right: Any) -> bool:
    if field_name in _LISTING_JSON_LIKE_FIELDS:
        return _canonical_listing_compare_value(left) == _canonical_listing_compare_value(right)
    if isinstance(left, float) or isinstance(right, float):
        try:
            left_num = float(left)
            right_num = float(right)
        except Exception:
            return left == right
        return math.isclose(left_num, right_num, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(left, str) or isinstance(right, str):
        return str(left or "").strip() == str(right or "").strip()
    return left == right


def _emit_listing_signal(signal_name: str, payload: Optional[dict[str, Any]] = None) -> None:
    try:
        signal = getattr(listing_signals, signal_name, None)
        if signal is not None:
            signal.emit(dict(payload or {}))
    except Exception:
        pass


def _snapshot_meta_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


SNAPSHOT_STATUS_APPEND = "append"
SNAPSHOT_STATUS_SET = "set"
SNAPSHOT_STATUS_REMOVE = "remove"
SNAPSHOT_STATUS_VALUES = {
    SNAPSHOT_STATUS_APPEND,
    SNAPSHOT_STATUS_SET,
    SNAPSHOT_STATUS_REMOVE,
}


def _normalize_snapshot_status(value: Any, *, fallback: str = SNAPSHOT_STATUS_SET) -> str:
    raw = str(value or "").strip().casefold()
    if raw in SNAPSHOT_STATUS_VALUES:
        return raw
    return fallback


def _snapshot_status(value: Any) -> str:
    raw_status = ""
    resolution_meta: Any = None
    if isinstance(value, dict):
        raw_status = str(value.get("status") or "").strip()
        resolution_meta = value.get("resolution_meta")
    else:
        raw_status = str(getattr(value, "status", "") or "").strip()
        resolution_meta = getattr(value, "resolution_meta", None)

    normalized = _normalize_snapshot_status(raw_status, fallback="")
    if normalized:
        return normalized

    meta = _snapshot_meta_dict(resolution_meta)
    if bool(meta.get("removed")):
        return SNAPSHOT_STATUS_REMOVE
    binding_event = _normalize_snapshot_status(meta.get("binding_event"), fallback="")
    if binding_event:
        return binding_event
    return SNAPSHOT_STATUS_SET


def _snapshot_removed(value: Any) -> bool:
    return _snapshot_status(value) == SNAPSHOT_STATUS_REMOVE


def _clean_snapshot_resolution_meta(value: Any) -> dict[str, Any] | None:
    meta = _snapshot_meta_dict(value)
    if not meta:
        return None
    cleaned = {
        str(key): val
        for key, val in meta.items()
        if str(key) not in {"binding_event", "removed", "status"}
    }
    return cleaned or None


def _canonical_snapshot_compare_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_snapshot_compare_value(val)
            for key, val in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        normalized = [_canonical_snapshot_compare_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, str):
        return value.strip()
    return value


def _snapshot_payload_signature(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_item_id": _safe_int_id(payload.get("cost_item_id")),
        "cargo_provider_id": _safe_int_id(payload.get("cargo_provider_id")),
        "cost_key": str(payload.get("cost_key") or "").strip().casefold(),
        "source_type": str(payload.get("source_type") or "").strip() or None,
        "source_config": _canonical_snapshot_compare_value(dict(payload.get("source_config") or {}) or None),
        "resolved_amount": _optional_float(payload.get("resolved_amount")),
        "resolved_net_amount": _optional_float(payload.get("resolved_net_amount")),
        "resolved_vat_amount": _optional_float(payload.get("resolved_vat_amount")),
        "currency": str(payload.get("currency") or "TRY").strip().upper() or "TRY",
        "note": str(payload.get("note") or "").strip() or None,
        "resolution_meta": _canonical_snapshot_compare_value(_clean_snapshot_resolution_meta(payload.get("resolution_meta"))),
    }


def _snapshot_row_signature(row: ListingProductCostSnapshot) -> dict[str, Any]:
    return {
        "cost_item_id": _safe_int_id(getattr(row, "cost_item_id", None)),
        "cargo_provider_id": _safe_int_id(getattr(row, "cargo_provider_id", None)),
        "cost_key": str(getattr(row, "cost_key", "") or "").strip().casefold(),
        "source_type": str(getattr(row, "source_type", "") or "").strip() or None,
        "source_config": _canonical_snapshot_compare_value(dict(getattr(row, "source_config", None) or {}) or None),
        "resolved_amount": _optional_float(getattr(row, "resolved_amount", None)),
        "resolved_net_amount": _optional_float(getattr(row, "resolved_net_amount", None)),
        "resolved_vat_amount": _optional_float(getattr(row, "resolved_vat_amount", None)),
        "currency": str(getattr(row, "currency", "") or "TRY").strip().upper() or "TRY",
        "note": str(getattr(row, "note", "") or "").strip() or None,
        "resolution_meta": _canonical_snapshot_compare_value(_clean_snapshot_resolution_meta(getattr(row, "resolution_meta", None))),
    }


def _snapshot_row_matches_payload(row: ListingProductCostSnapshot, payload: dict[str, Any]) -> bool:
    return _snapshot_row_signature(row) == _snapshot_payload_signature(payload)


def _snapshot_binding_signature(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_item_id": _safe_int_id(payload.get("cost_item_id")),
        "cargo_provider_id": _safe_int_id(payload.get("cargo_provider_id")),
        "cost_key": str(payload.get("cost_key") or "").strip().casefold(),
        "source_type": str(payload.get("source_type") or "").strip() or None,
        "source_config": _canonical_snapshot_compare_value(dict(payload.get("source_config") or {}) or None),
    }


def _snapshot_row_binding_matches_payload(row: ListingProductCostSnapshot, payload: dict[str, Any]) -> bool:
    return {
        "cost_item_id": _safe_int_id(getattr(row, "cost_item_id", None)),
        "cargo_provider_id": _safe_int_id(getattr(row, "cargo_provider_id", None)),
        "cost_key": str(getattr(row, "cost_key", "") or "").strip().casefold(),
        "source_type": str(getattr(row, "source_type", "") or "").strip() or None,
        "source_config": _canonical_snapshot_compare_value(dict(getattr(row, "source_config", None) or {}) or None),
    } == _snapshot_binding_signature(payload)


def _snapshot_has_resolved_payload(row: ListingProductCostSnapshot) -> bool:
    if _optional_float(getattr(row, "resolved_amount", None)) is not None:
        return True
    if _optional_float(getattr(row, "resolved_net_amount", None)) is not None:
        return True
    if _optional_float(getattr(row, "resolved_vat_amount", None)) is not None:
        return True
    if str(getattr(row, "note", "") or "").strip():
        return True
    return bool(_clean_snapshot_resolution_meta(getattr(row, "resolution_meta", None)))


def _resolve_cost_item_ids(
    session: Session,
    *,
    normalized_cost_keys: set[str],
) -> dict[str, int]:
    if not normalized_cost_keys:
        return {}
    rows = session.exec(
        select(FinanceCostItem).where(func.lower(FinanceCostItem.costKey).in_(list(normalized_cost_keys)))
    ).all() or []
    cost_item_id_map: dict[str, int] = {}
    for cost_item in rows:
        cost_item_pk = getattr(cost_item, "pk", None)
        if cost_item_pk is None:
            continue
        normalized_key = str(getattr(cost_item, "costKey", "") or "").strip().casefold()
        if normalized_key:
            cost_item_id_map[normalized_key] = int(cost_item_pk)
    return cost_item_id_map


def _latest_snapshot_rows_by_listing(
    session: Session,
    *,
    listing_ids: list[int],
) -> dict[tuple[int, str], ListingProductCostSnapshot]:
    if not listing_ids:
        return {}

    row_number = func.row_number().over(
        partition_by=(
            ListingProductCostSnapshot.listing_id,
            func.lower(ListingProductCostSnapshot.cost_key),
        ),
        order_by=(
            ListingProductCostSnapshot.created_at.desc(),
            ListingProductCostSnapshot.pk.desc(),
        ),
    ).label("row_number")
    latest_subq = (
        select(ListingProductCostSnapshot.pk.label("snapshot_pk"), row_number)
        .where(ListingProductCostSnapshot.listing_id.in_(list(listing_ids)))
        .subquery()
    )
    stmt = (
        select(ListingProductCostSnapshot)
        .join(latest_subq, ListingProductCostSnapshot.pk == latest_subq.c.snapshot_pk)
        .where(latest_subq.c.row_number == 1)
    )
    latest_rows: dict[tuple[int, str], ListingProductCostSnapshot] = {}
    for row in session.exec(stmt).all() or []:
        listing_id = _safe_int_id(getattr(row, "listing_id", None))
        cost_key = str(getattr(row, "cost_key", "") or "").strip()
        if listing_id is None or not cost_key:
            continue
        key = (listing_id, cost_key.casefold())
        if key not in latest_rows:
            latest_rows[key] = row
    return latest_rows


def _binding_payload_from_snapshot(row: ListingProductCostSnapshot) -> Optional[dict[str, Any]]:
    cost_key = str(getattr(row, "cost_key", "") or "").strip()
    if not cost_key:
        return None

    source_config = dict(getattr(row, "source_config", None) or {}) or None
    cargo_provider_id = _safe_int_id(getattr(row, "cargo_provider_id", None))
    if cargo_provider_id is not None:
        source_config = dict(source_config or {})
        source_config.setdefault("cargoProviderId", cargo_provider_id)

    normalized_binding = normalize_listing_cost_binding(
        {
            "cost_key": cost_key,
            "source_type": getattr(row, "source_type", None),
            "source_config": source_config,
        }
    )
    return {
        "cost_key": cost_key,
        "costKey": cost_key,
        "calculation_type": normalized_binding.get("calculation_type") or None,
        "calculationType": normalized_binding.get("calculation_type") or None,
        "matchMode": normalized_binding.get("calculation_type") or None,
        "source_type": normalized_binding.get("source_type") or None,
        "sourceType": normalized_binding.get("source_type") or None,
        "source_config": dict(normalized_binding.get("source_config") or {}) or None,
        "sourceConfig": dict(normalized_binding.get("source_config") or {}) or None,
        "cargo_provider_id": cargo_provider_id,
        "amount": normalized_binding.get("amount"),
        "quantity": normalized_binding.get("quantity"),
        "tariff_key": normalized_binding.get("tariff_key"),
        "tariffKey": normalized_binding.get("tariff_key"),
        "resolved_amount": _optional_float(getattr(row, "resolved_amount", None)),
        "resolved_net_amount": _optional_float(getattr(row, "resolved_net_amount", None)),
        "resolved_vat_amount": _optional_float(getattr(row, "resolved_vat_amount", None)),
        "currency": str(getattr(row, "currency", "") or "").strip() or None,
        "note": str(getattr(row, "note", "") or "").strip() or None,
        "cost_item_id": _safe_int_id(getattr(row, "cost_item_id", None)),
    }


def _latest_stock_snapshot_rows_by_listing(
    session: Session,
    *,
    listing_ids: list[int],
) -> dict[tuple[int, int], ListingProductStockSnapshot]:
    if not listing_ids:
        return {}

    multi_snapshot_exists = bool(
        session.exec(
            select(ListingProductStockSnapshot.listing_id)
            .where(ListingProductStockSnapshot.listing_id.in_(list(listing_ids)))
            .group_by(
                ListingProductStockSnapshot.listing_id,
                ListingProductStockSnapshot.stock_item_id,
            )
            .having(func.count(ListingProductStockSnapshot.pk) > 1)
            .limit(1)
        ).first()
    )
    if not multi_snapshot_exists:
        stmt = select(ListingProductStockSnapshot).where(
            ListingProductStockSnapshot.listing_id.in_(list(listing_ids))
        )
        latest_rows: dict[tuple[int, int], ListingProductStockSnapshot] = {}
        for row in session.exec(stmt).all() or []:
            listing_id = _safe_int_id(getattr(row, "listing_id", None))
            stock_item_id = _safe_int_id(getattr(row, "stock_item_id", None))
            if listing_id is None or stock_item_id is None:
                continue
            latest_rows[(listing_id, stock_item_id)] = row
        return latest_rows

    row_number = func.row_number().over(
        partition_by=(
            ListingProductStockSnapshot.listing_id,
            ListingProductStockSnapshot.stock_item_id,
        ),
        order_by=(
            ListingProductStockSnapshot.created_at.desc(),
            ListingProductStockSnapshot.pk.desc(),
        ),
    ).label("row_number")
    latest_subq = (
        select(ListingProductStockSnapshot.pk.label("snapshot_pk"), row_number)
        .where(ListingProductStockSnapshot.listing_id.in_(list(listing_ids)))
        .subquery()
    )
    stmt = (
        select(ListingProductStockSnapshot)
        .join(latest_subq, ListingProductStockSnapshot.pk == latest_subq.c.snapshot_pk)
        .where(latest_subq.c.row_number == 1)
    )
    latest_rows: dict[tuple[int, int], ListingProductStockSnapshot] = {}
    for row in session.exec(stmt).all() or []:
        listing_id = _safe_int_id(getattr(row, "listing_id", None))
        stock_item_id = _safe_int_id(getattr(row, "stock_item_id", None))
        if listing_id is None or stock_item_id is None:
            continue
        key = (listing_id, stock_item_id)
        if key not in latest_rows:
            latest_rows[key] = row
    return latest_rows


def _stock_snapshot_row_matches_payload(
    row: ListingProductStockSnapshot,
    payload: dict[str, Any],
) -> bool:
    return (
        _safe_int_id(getattr(row, "stock_item_id", None)) == _safe_int_id(payload.get("stock_item_id"))
        and math.isclose(
            float(getattr(row, "qty", 0.0) or 0.0),
            float(payload.get("qty", 0.0) or 0.0),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    )


def _stock_binding_payload_from_snapshot(row: ListingProductStockSnapshot) -> Optional[dict[str, Any]]:
    stock_item_id = _safe_int_id(getattr(row, "stock_item_id", None))
    if stock_item_id is None:
        return None
    qty = float(getattr(row, "qty", 0.0) or 0.0)
    if qty <= 0:
        return None
    return {"stock_item_id": stock_item_id, "qty": qty}


def _normalize_cost_items(items: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}

    for it in items or []:
        if not isinstance(it, dict):
            continue
        normalized = normalize_listing_cost_binding(it)
        cost_key = str(normalized.get("cost_key") or "").strip()
        if not cost_key:
            continue
        if normalized.get("source_type") == "manual_value" and normalized.get("amount") is None:
            continue

        merged[cost_key] = {
            "cost_key": cost_key,
            "calculation_type": normalized.get("calculation_type") or None,
            "source_type": normalized.get("source_type") or None,
            "source_config": dict(normalized.get("source_config") or {}) or None,
            "tariff_key": normalized.get("tariff_key"),
        }
    return list(merged.values())


def _optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_cost_match_mode(value: Any, *, fallback: str = "manual") -> str:
    raw = str(value or "").strip().casefold()
    if raw in {"manual", "fixed", "per_order", "percentage", "per_unit", "per_package", "per_minute"}:
        return "manual"
    if raw in {"automatic", "tariff_lookup"}:
        return "automatic"
    if raw == "semi_automatic":
        return "semi_automatic"
    return str(fallback or "").strip().casefold() or "manual"


DEFAULT_SERVICE_VAT_RATE = 20.0
DEFAULT_DESI_DIVISOR = 3000.0


def _resolved_vat_rate(vat_rate: Any, *, fallback: Any = None) -> Optional[float]:
    direct = _optional_float(vat_rate)
    if direct is not None and direct >= 0:
        return direct
    default_val = _optional_float(fallback)
    if default_val is not None and default_val >= 0:
        return default_val
    return None


def _gross_amount(
    amount: Any,
    *,
    is_vat_included: bool = True,
    vat_rate: Any = None,
    default_vat_rate: Any = None,
) -> Optional[float]:
    amount_val = _optional_float(amount)
    if amount_val is None:
        return None
    if bool(is_vat_included):
        return amount_val
    vat_val = _resolved_vat_rate(vat_rate, fallback=default_vat_rate)
    if vat_val is None or vat_val < 0:
        return amount_val
    return amount_val * (1.0 + (vat_val / 100.0))


def _vat_amount_from_gross(
    amount: Any,
    *,
    vat_rate: Any = None,
    default_vat_rate: Any = None,
) -> Optional[float]:
    amount_val = _optional_float(amount)
    if amount_val is None:
        return None
    resolved_rate = _resolved_vat_rate(vat_rate, fallback=default_vat_rate)
    if resolved_rate is None or resolved_rate < 0:
        return None
    if resolved_rate == 0:
        return 0.0
    return amount_val * (resolved_rate / (100.0 + resolved_rate))


def _net_amount_from_gross(
    amount: Any,
    *,
    vat_rate: Any = None,
    default_vat_rate: Any = None,
) -> Optional[float]:
    amount_val = _optional_float(amount)
    if amount_val is None:
        return None
    vat_amount = _vat_amount_from_gross(amount_val, vat_rate=vat_rate, default_vat_rate=default_vat_rate)
    if vat_amount is None:
        return amount_val
    return amount_val - vat_amount


def _stock_unit_desi(metrics: dict[str, Any] | None) -> Optional[float]:
    if not isinstance(metrics, dict):
        return None

    weight_val = _optional_float(metrics.get("weight_kg"))
    candidates: list[float] = []
    if weight_val is not None and weight_val > 0:
        candidates.append(weight_val)

    length_val = _optional_float(metrics.get("length_cm"))
    width_val = _optional_float(metrics.get("width_cm"))
    height_val = _optional_float(metrics.get("height_cm"))
    if (
        length_val is not None and length_val > 0
        and width_val is not None and width_val > 0
        and height_val is not None and height_val > 0
    ):
        volumetric_desi = (length_val * width_val * height_val) / DEFAULT_DESI_DIVISOR
        if volumetric_desi > 0:
            candidates.append(volumetric_desi)

    if not candidates:
        return None
    return max(candidates)


def _stock_items_total_desi(
    stock_items: list[dict] | None,
    stock_dimension_map: dict[int, dict[str, Any]] | None,
) -> dict[str, Any]:
    total_desi = 0.0
    has_any = False
    missing_stock_ids: list[int] = []

    for row in stock_items or ():
        if not isinstance(row, dict):
            continue
        try:
            stock_item_id = int(row.get("stock_item_id"))
        except Exception:
            continue
        qty_val = _optional_float(row.get("qty"))
        if qty_val is None or qty_val <= 0:
            continue

        unit_desi = _stock_unit_desi((stock_dimension_map or {}).get(stock_item_id))
        if unit_desi is None:
            missing_stock_ids.append(stock_item_id)
            continue

        total_desi += unit_desi * qty_val
        has_any = True

    return {
        "total_desi": total_desi if has_any else None,
        "missing_stock_ids": list(dict.fromkeys(missing_stock_ids)),
        "is_partial": bool(has_any and missing_stock_ids),
    }


def _stock_cost_input_mode_note(mode: Any, *, vat_rate: Any = None) -> str:
    raw = str(mode or "").strip().casefold()
    rate = _optional_float(vat_rate)
    rate_text = f" (%{rate:.0f})" if rate is not None else ""
    if raw == "gross":
        return "Maliyet girişi KDV dahil kaydedildi."
    if raw == "net":
        return f"Maliyet girişi KDV hariç kaydedildi; stokta brüte çevrildi{rate_text}."
    if raw == "mixed_explicit":
        return "Aktif stok maliyeti KDV dahil ve hariç girişlerin birleşiminden oluşuyor."
    if raw == "legacy":
        return "Eski stok kayıtlarında KDV modu tutulmadığı için brüt varsayımı kullanıldı."
    return "Stok maliyeti ayrışımı stok kartı KDV oranına göre yapıldı."


def _range_matches(value: Any, minimum: Any, maximum: Any) -> bool:
    min_val = _optional_float(minimum)
    max_val = _optional_float(maximum)
    probe = _optional_float(value)
    if probe is None:
        return min_val is None and max_val is None
    if min_val is not None and probe < min_val:
        return False
    if max_val is not None and probe > max_val:
        return False
    return True


def _range_span(minimum: Any, maximum: Any) -> float:
    min_val = _optional_float(minimum)
    max_val = _optional_float(maximum)
    if min_val is None or max_val is None:
        return 999999999.0
    return max(0.0, max_val - min_val)


def match_cargo_tariff_for_listing(
    *,
    sale_price: Any,
    dimensional_weight: Any,
    platform_code: Any,
    cargo_tariffs: list[dict] | None,
    cargo_provider_id: Any = None,
    cargo_provider_code: Any = None,
    cargo_provider_name: Any = None,
) -> Optional[dict]:
    return match_cargo_amount(
        sale_price=sale_price,
        dimensional_weight=dimensional_weight,
        platform_code=platform_code,
        cargo_tariffs=cargo_tariffs,
        cargo_provider_id=cargo_provider_id,
        cargo_provider_code=cargo_provider_code,
        cargo_provider_name=cargo_provider_name,
    )


def estimate_listing_profit(
    *,
    item: dict,
    stock_cost_map: dict[int, float] | None,
    cost_card_map: dict[str, dict] | None,
    cargo_tariffs: list[dict] | None,
    platform_code: Any,
    stock_vat_rate_map: dict[int, float] | None = None,
    stock_cost_meta_map: dict[int, dict[str, Any]] | None = None,
    stock_dimension_map: dict[int, dict[str, Any]] | None = None,
    sale_quantity: Any = 1,
) -> dict[str, Any]:
    def _first_present(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return None

    def _amount_text(value: Optional[float], *, signed: bool = False) -> str:
        if value is None:
            return "-"
        if signed:
            return f"-{value:.2f} TL"
        return f"{value:.2f} TL"

    def _delta_text(value: Optional[float]) -> str:
        if value is None:
            return "-"
        if value > 0:
            return f"-{value:.2f} TL"
        if value < 0:
            return f"+{abs(value):.2f} TL"
        return "0.00 TL"

    def _vat_status_note(value: Optional[float]) -> str:
        if value is None:
            return ""
        if value > 0:
            return "Devlete borç"
        if value < 0:
            return "KDV alacağı"
        return ""

    def _component_payload(
        *,
        key: str,
        label: str,
        total: float,
        vat: float,
        kind: str,
        note: str = "",
        source_type: str = "",
        source_trace: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "kind": kind,
            "gross": total,
            "vat": vat,
            "net": (total - vat),
            "gross_text": _amount_text(total),
            "vat_text": _amount_text(vat),
            "net_text": _amount_text(total - vat),
            "note": note,
            "source_type": source_type or None,
            "source_trace": dict(source_trace or {}) or None,
        }

    unit_sale_price = _optional_float(
        _first_present(
            item.get("salePrice"),
            item.get("sale_price"),
            item.get("listPrice"),
            item.get("list_price"),
        )
    )
    sale_quantity_value = _optional_float(sale_quantity)
    if sale_quantity_value is None or sale_quantity_value <= 0:
        sale_quantity_value = 1.0
    sale_quantity_text = (
        str(int(sale_quantity_value))
        if float(sale_quantity_value).is_integer()
        else f"{sale_quantity_value:.2f}".rstrip("0").rstrip(".")
    )
    sale_price = None if unit_sale_price is None else (unit_sale_price * sale_quantity_value)
    sale_vat_rate = _optional_float(_first_present(item.get("vatRate"), item.get("vat_rate")))
    dimensional_weight = _first_present(item.get("dimensionalWeight"), item.get("dimensional_weight"))
    stock_items: list[dict[str, Any]] = []
    for row in (item.get("stock_items") or []):
        if not isinstance(row, dict):
            continue
        scaled_row = dict(row)
        qty_val = _optional_float(scaled_row.get("qty"))
        if qty_val is not None:
            scaled_row["qty"] = qty_val * sale_quantity_value
        stock_items.append(scaled_row)
    cost_items = item.get("cost_items") or ()
    stock_cost_map = stock_cost_map or {}
    stock_vat_rate_map = stock_vat_rate_map or {}
    stock_cost_meta_map = stock_cost_meta_map or {}
    stock_dimension_map = stock_dimension_map or {}
    cost_card_map = cost_card_map or {}

    listing_desi = _optional_float(dimensional_weight)
    if listing_desi is not None:
        listing_desi *= sale_quantity_value
    stock_desi_info = _stock_items_total_desi(stock_items, stock_dimension_map)
    stock_total_desi = _optional_float(stock_desi_info.get("total_desi"))
    effective_dimensional_weight = listing_desi
    dimensional_weight_source = "ilan"
    if effective_dimensional_weight is None:
        effective_dimensional_weight = stock_total_desi
        if effective_dimensional_weight is not None:
            dimensional_weight_source = "stock"
        else:
            dimensional_weight_source = "unknown"

    complete = sale_price is not None
    stock_cost_total = 0.0
    commission_total = 0.0
    cargo_total = 0.0
    other_cost_total = 0.0
    purchase_vat_total = 0.0
    commission_vat_total = 0.0
    cargo_vat_total = 0.0
    other_cost_vat_total = 0.0
    sale_vat = 0.0
    net_vat = 0.0
    matched_cargo_tariff_key = None
    matched_cargo_tariff_name = None
    missing_reasons: list[str] = []
    applied_costs: list[dict[str, Any]] = []
    stock_cost_notes: list[str] = []

    if not stock_items:
        complete = False
        missing_reasons.append("Eşleşmiş ürün bulunamadı.")

    for row in stock_items:
        if not isinstance(row, dict):
            continue
        try:
            stock_item_id = int(row.get("stock_item_id"))
        except Exception:
            complete = False
            missing_reasons.append("Stok kartı eşleşmesinde geçersiz kayıt var.")
            continue
        qty_val = _optional_float(row.get("qty"))
        if qty_val is None or qty_val <= 0:
            continue
        unit_cost = _optional_float(stock_cost_map.get(stock_item_id))
        if unit_cost is None:
            complete = False
            missing_reasons.append(f"Stok kartı maliyeti eksik: #{stock_item_id}")
            continue
        line_cost = unit_cost * qty_val
        stock_cost_total += line_cost
        stock_vat_rate = _optional_float(stock_vat_rate_map.get(stock_item_id))
        stock_cost_meta = stock_cost_meta_map.get(stock_item_id) or {}
        mode_note = _stock_cost_input_mode_note(
            stock_cost_meta.get("input_mode"),
            vat_rate=stock_vat_rate,
        )
        if mode_note:
            stock_cost_notes.append(mode_note)
        if stock_vat_rate is None and line_cost > 0:
            complete = False
            missing_reasons.append(f"Stok kartı KDV oranı eksik: #{stock_item_id}")
            continue
        purchase_vat = _vat_amount_from_gross(line_cost, vat_rate=stock_vat_rate)
        if purchase_vat is not None:
            purchase_vat_total += purchase_vat

    if stock_cost_total > 0:
        stock_note_parts: list[str] = []
        linked_stock_label = str(item.get("linked_stock_label") or "").strip()
        if linked_stock_label:
            stock_note_parts.append(linked_stock_label)
        if stock_cost_notes:
            stock_note_parts.extend(list(dict.fromkeys(stock_cost_notes)))
        applied_costs.append(
            _component_payload(
                key="stock",
                label="Stok Maliyeti",
                total=stock_cost_total,
                vat=purchase_vat_total,
                kind="stock",
                note="\n".join(part for part in stock_note_parts if part),
            )
        )

    for row in cost_items:
        if not isinstance(row, dict):
            continue
        cost_key = str(row.get("cost_key") or row.get("costKey") or "").strip().casefold()
        if not cost_key:
            continue
        card = cost_card_map.get(cost_key) or {}
        if not card:
            complete = False
            missing_reasons.append(f"Maliyet kartı bulunamadı: {cost_key}")
            continue
        card_label = str(card.get("name") or card.get("label") or cost_key).strip() or cost_key

        value_type = str(card.get("valueType") or card.get("calculationType") or "").strip().casefold() or "numeric"
        is_vat_included = bool(card.get("isVatIncluded", True))
        vat_rate = card.get("vatRate")
        normalized_binding = normalize_listing_cost_binding(row, card=card)
        resolution = resolve_listing_cost_source(
            binding=normalized_binding,
            card=card,
            context={
                "item": item,
                "sale_price": sale_price,
                "effective_dimensional_weight": effective_dimensional_weight,
                "platform_code": platform_code,
                "cargo_tariffs": cargo_tariffs,
            },
        )
        if not bool(resolution.get("success")):
            complete = False
            missing_reasons.append(str(resolution.get("missing_reason") or f"Maliyet hesabı başarısız: {card_label}"))
            continue

        resolved_amount = _optional_float(resolution.get("amount"))
        if resolved_amount is None:
            complete = False
            missing_reasons.append(f"Maliyet hesabı başarısız: {card.get('name') or cost_key}")
            continue

        gross_amount = (
            resolved_amount
            if bool(resolution.get("amount_is_gross", False))
            else _gross_amount(
                resolved_amount,
                is_vat_included=is_vat_included,
                vat_rate=vat_rate,
                default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
            )
        )
        if gross_amount is None:
            complete = False
            missing_reasons.append(f"Maliyet hesabı başarısız: {card.get('name') or cost_key}")
            continue

        resolution_meta = dict(resolution.get("meta") or {})
        matched_tariff = dict(resolution_meta.get("matchedTariff") or {})
        source_config = dict(normalized_binding.get("source_config") or {})
        selected_provider_name = str(
            resolution_meta.get("selectedCargoProviderName")
            or resolution_meta.get("cargoProviderName")
            or source_config.get("cargoProviderName")
            or ""
        ).strip()
        resolved_note = str(resolution.get("note") or "").strip()
        note_parts: list[str] = []
        if resolved_note:
            note_parts.append(resolved_note)
        if selected_provider_name and selected_provider_name not in note_parts:
            note_parts.append(selected_provider_name)

        if cost_key == "kargo":
            cargo_total += gross_amount
            cargo_vat = _vat_amount_from_gross(
                gross_amount,
                vat_rate=matched_tariff.get("vatRate") if matched_tariff else vat_rate,
                default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
            ) or 0.0
            cargo_vat_total += cargo_vat
            matched_cargo_tariff_key = matched_tariff.get("tariffKey") or resolution_meta.get("matchedTariffKey")
            matched_cargo_tariff_name = (
                matched_tariff.get("name")
                or matched_tariff.get("label")
                or resolution_meta.get("matchedTariffName")
            )
            tariff_note = str(matched_cargo_tariff_name or matched_cargo_tariff_key or "").strip()
            if tariff_note and tariff_note not in note_parts:
                note_parts.insert(0, tariff_note)
            applied_costs.append(
                _component_payload(
                    key=cost_key,
                    label=card_label,
                    total=gross_amount,
                    vat=cargo_vat,
                    kind="cargo",
                    note=" | ".join(part for part in note_parts if part),
                    source_type=str(resolution.get("source_type") or ""),
                    source_trace=dict(resolution.get("trace") or {}),
                )
            )
        elif value_type == "percentage":
            commission_total += gross_amount
            commission_vat = _vat_amount_from_gross(
                gross_amount,
                vat_rate=vat_rate,
                default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
            ) or 0.0
            commission_vat_total += commission_vat
            raw_amount = _optional_float(resolution.get("raw_amount"))
            if raw_amount is not None and not note_parts:
                note_parts.append(f"%{raw_amount:.2f}")
            applied_costs.append(
                _component_payload(
                    key=cost_key,
                    label=card_label,
                    total=gross_amount,
                    vat=commission_vat,
                    kind="commission",
                    note=" | ".join(part for part in note_parts if part),
                    source_type=str(resolution.get("source_type") or ""),
                    source_trace=dict(resolution.get("trace") or {}),
                )
            )
        else:
            other_cost_total += gross_amount
            other_cost_vat = _vat_amount_from_gross(
                gross_amount,
                vat_rate=vat_rate,
                default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
            ) or 0.0
            other_cost_vat_total += other_cost_vat
            applied_costs.append(
                _component_payload(
                    key=cost_key,
                    label=card_label,
                    total=gross_amount,
                    vat=other_cost_vat,
                    kind="other",
                    note=" | ".join(part for part in note_parts if part),
                    source_type=str(resolution.get("source_type") or ""),
                    source_trace=dict(resolution.get("trace") or {}),
                )
            )

    estimated_profit = None
    estimated_profit_text = "-"
    breakdown: list[dict[str, Any]] = []
    detail_payload: dict[str, Any] = {}
    if sale_price is not None:
        if sale_vat_rate is None:
            complete = False
            missing_reasons.append("İlan satış KDV oranı eksik.")
        sale_vat = _vat_amount_from_gross(sale_price, vat_rate=sale_vat_rate) or 0.0
        input_vat_total = purchase_vat_total + commission_vat_total + cargo_vat_total + other_cost_vat_total
        total_costs = stock_cost_total + commission_total + cargo_total + other_cost_total
        payout_total = sale_price - commission_total - cargo_total
        sale_net_total = _net_amount_from_gross(sale_price, vat_rate=sale_vat_rate) or sale_price
        net_vat = sale_vat - input_vat_total
        estimated_profit = (
            sale_price
            - total_costs
            - net_vat
        )
        if complete:
            estimated_profit_text = f"{estimated_profit:.2f} TL"
        breakdown = [
            {
                "label": "Satış Fiyatı",
                "value": sale_price,
                "value_text": _amount_text(sale_price),
                "kind": "income",
            }
        ]
        for component in applied_costs:
            breakdown.append(
                {
                    "label": component.get("label"),
                    "value": component.get("gross"),
                    "value_text": _amount_text(component.get("gross"), signed=True),
                    "kind": component.get("kind") or "cost",
                    "note": component.get("note") or "",
                }
            )
        if purchase_vat_total > 0:
            breakdown.append(
                {
                    "label": "Alıştan KDV",
                    "value": purchase_vat_total,
                    "value_text": _amount_text(purchase_vat_total),
                    "kind": "vat",
                }
            )
        if commission_vat_total > 0:
            breakdown.append(
                {
                    "label": "Komisyondan KDV",
                    "value": commission_vat_total,
                    "value_text": _amount_text(commission_vat_total),
                    "kind": "vat",
                }
            )
        if cargo_vat_total > 0:
            breakdown.append(
                {
                    "label": "Kargodan KDV",
                    "value": cargo_vat_total,
                    "value_text": _amount_text(cargo_vat_total),
                    "kind": "vat",
                }
            )
        if other_cost_vat_total > 0:
            breakdown.append(
                {
                    "label": "Diğer Maliyet KDV",
                    "value": other_cost_vat_total,
                    "value_text": _amount_text(other_cost_vat_total),
                    "kind": "vat",
                }
            )
        breakdown.extend(
            [
                {
                    "label": "Satıştan KDV",
                    "value": sale_vat,
                    "value_text": _amount_text(sale_vat),
                    "kind": "vat",
                },
                {
                    "label": "Nihai KDV",
                    "value": net_vat,
                    "value_text": _delta_text(net_vat),
                    "kind": "vat_balance",
                    "note": _vat_status_note(net_vat),
                },
                {
                    "label": "Tahmini Kar",
                    "value": estimated_profit,
                    "value_text": _amount_text(estimated_profit),
                    "kind": "profit",
                },
            ]
        )
        detail_payload = {
            "summary": {
                "unit_sale_price": unit_sale_price,
                "unit_sale_price_text": _amount_text(unit_sale_price),
                "sale_quantity": sale_quantity_value,
                "sale_quantity_text": sale_quantity_text,
                "sale_price": sale_price,
                "sale_price_text": _amount_text(sale_price),
                "sale_net": sale_net_total,
                "sale_net_text": _amount_text(sale_net_total),
                "sale_vat_rate": sale_vat_rate,
                "sale_vat_rate_text": f"%{sale_vat_rate:.2f}" if sale_vat_rate is not None else "-",
                "sale_vat": sale_vat,
                "sale_vat_text": _amount_text(sale_vat),
                "dimensional_weight": effective_dimensional_weight,
                "dimensional_weight_text": "-" if effective_dimensional_weight is None else f"{effective_dimensional_weight:.2f}",
                "dimensional_weight_source": dimensional_weight_source,
                "dimensional_weight_source_text": (
                    "İlan desisi"
                    if dimensional_weight_source == "ilan"
                    else "Stok kartı toplam desisi"
                    if dimensional_weight_source == "stock"
                    else "Desi verisi yok"
                ),
                "stock_total_desi": stock_total_desi,
                "stock_total_desi_text": "-" if stock_total_desi is None else f"{stock_total_desi:.2f}",
                "stock_desi_is_partial": bool(stock_desi_info.get("is_partial")),
                "stock_desi_missing_stock_ids": list(stock_desi_info.get("missing_stock_ids") or []),
                "cargo_tariff_name": matched_cargo_tariff_name or matched_cargo_tariff_key or "-",
                "linked_stock_label": str(item.get("linked_stock_label") or "").strip(),
            },
            "applied_costs": applied_costs,
            "results": {
                "payout_total": payout_total,
                "payout_total_text": _amount_text(payout_total),
                "total_costs": total_costs,
                "total_costs_text": _amount_text(total_costs),
                "input_vat_total": input_vat_total,
                "input_vat_total_text": _amount_text(input_vat_total),
                "sale_vat": sale_vat,
                "sale_vat_text": _amount_text(sale_vat),
                "net_vat": net_vat,
                "net_vat_text": _delta_text(net_vat),
                "net_vat_note": _vat_status_note(net_vat),
                "estimated_profit": estimated_profit,
                "estimated_profit_text": _amount_text(estimated_profit),
            },
        }
    elif sale_price is None:
        missing_reasons.append("İlan satış fiyatı bulunamadı.")

    return {
        "sale_quantity": sale_quantity_value,
        "estimated_profit": estimated_profit,
        "estimated_profit_text": estimated_profit_text,
        "estimated_profit_ready": bool(complete and estimated_profit is not None),
        "stock_cost_total": stock_cost_total,
        "commission_cost": commission_total,
        "cargo_cost": cargo_total,
        "other_cost_total": other_cost_total,
        "sale_vat_rate": sale_vat_rate,
        "sale_vat": sale_vat,
        "purchase_vat": purchase_vat_total,
        "commission_vat": commission_vat_total,
        "cargo_vat": cargo_vat_total,
        "other_cost_vat": other_cost_vat_total,
        "net_vat": net_vat,
        "matched_cargo_tariff_key": matched_cargo_tariff_key,
        "matched_cargo_tariff_name": matched_cargo_tariff_name,
        "estimated_profit_breakdown": breakdown,
        "estimated_profit_detail": detail_payload,
        "estimated_profit_missing_reasons": list(dict.fromkeys(missing_reasons)),
    }

def _estimate_listing_profit_resolver_v1(
    *,
    item: dict,
    stock_cost_map: dict[int, float] | None,
    cost_card_map: dict[str, dict] | None,
    cargo_tariffs: list[dict] | None,
    platform_code: Any,
    stock_vat_rate_map: dict[int, float] | None = None,
    stock_cost_meta_map: dict[int, dict[str, Any]] | None = None,
    stock_dimension_map: dict[int, dict[str, Any]] | None = None,
    sale_quantity: Any = 1,
) -> dict[str, Any]:
    def _first_present(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return None

    def _amount_text(value: Optional[float], *, signed: bool = False) -> str:
        if value is None:
            return "-"
        if signed:
            return f"-{value:.2f} TL"
        return f"{value:.2f} TL"

    def _delta_text(value: Optional[float]) -> str:
        if value is None:
            return "-"
        if value > 0:
            return f"-{value:.2f} TL"
        if value < 0:
            return f"+{abs(value):.2f} TL"
        return "0.00 TL"

    def _vat_status_note(value: Optional[float]) -> str:
        if value is None:
            return ""
        if value > 0:
            return "Devlete borc"
        if value < 0:
            return "KDV alacagi"
        return ""

    def _component_payload(
        *,
        key: str,
        label: str,
        total: float,
        vat: float,
        kind: str,
        note: str = "",
        source_type: str = "",
        source_trace: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
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

    unit_sale_price = _optional_float(
        _first_present(
            item.get("salePrice"),
            item.get("sale_price"),
            item.get("listPrice"),
            item.get("list_price"),
        )
    )
    sale_quantity_value = _optional_float(sale_quantity)
    if sale_quantity_value is None or sale_quantity_value <= 0:
        sale_quantity_value = 1.0
    sale_quantity_text = (
        str(int(sale_quantity_value))
        if float(sale_quantity_value).is_integer()
        else f"{sale_quantity_value:.2f}".rstrip("0").rstrip(".")
    )
    sale_price = None if unit_sale_price is None else unit_sale_price * sale_quantity_value
    sale_vat_rate = _optional_float(_first_present(item.get("vatRate"), item.get("vat_rate")))
    dimensional_weight = _first_present(item.get("dimensionalWeight"), item.get("dimensional_weight"))

    stock_items: list[dict[str, Any]] = []
    for row in item.get("stock_items") or ():
        if not isinstance(row, dict):
            continue
        scaled_row = dict(row)
        qty_val = _optional_float(scaled_row.get("qty"))
        if qty_val is not None:
            scaled_row["qty"] = qty_val * sale_quantity_value
        stock_items.append(scaled_row)

    cost_items = item.get("cost_items") or ()
    stock_cost_map = stock_cost_map or {}
    stock_vat_rate_map = stock_vat_rate_map or {}
    stock_cost_meta_map = stock_cost_meta_map or {}
    stock_dimension_map = stock_dimension_map or {}
    cost_card_map = cost_card_map or {}

    listing_desi = _optional_float(dimensional_weight)
    if listing_desi is not None:
        listing_desi *= sale_quantity_value
    stock_desi_info = _stock_items_total_desi(stock_items, stock_dimension_map)
    stock_total_desi = _optional_float(stock_desi_info.get("total_desi"))
    effective_dimensional_weight = listing_desi
    dimensional_weight_source = "ilan"
    if effective_dimensional_weight is None:
        effective_dimensional_weight = stock_total_desi
        if effective_dimensional_weight is not None:
            dimensional_weight_source = "stock"
        else:
            dimensional_weight_source = "unknown"

    complete = sale_price is not None
    stock_cost_total = 0.0
    commission_total = 0.0
    cargo_total = 0.0
    other_cost_total = 0.0
    purchase_vat_total = 0.0
    commission_vat_total = 0.0
    cargo_vat_total = 0.0
    other_cost_vat_total = 0.0
    sale_vat = 0.0
    net_vat = 0.0
    matched_cargo_tariff_key = None
    matched_cargo_tariff_name = None
    missing_reasons: list[str] = []
    applied_costs: list[dict[str, Any]] = []
    stock_cost_notes: list[str] = []

    if not stock_items:
        complete = False
        missing_reasons.append("Eslesmis urun bulunamadi.")

    for row in stock_items:
        if not isinstance(row, dict):
            continue
        try:
            stock_item_id = int(row.get("stock_item_id"))
        except Exception:
            complete = False
            missing_reasons.append("Stok kartı eşleşmesinde geçersiz kayıt var.")
            continue

        qty_val = _optional_float(row.get("qty"))
        if qty_val is None or qty_val <= 0:
            continue

        unit_cost = _optional_float(stock_cost_map.get(stock_item_id))
        if unit_cost is None:
            complete = False
            missing_reasons.append(f"Stok karti maliyeti eksik: #{stock_item_id}")
            continue

        line_cost = unit_cost * qty_val
        stock_cost_total += line_cost
        stock_vat_rate = _optional_float(stock_vat_rate_map.get(stock_item_id))
        stock_cost_meta = stock_cost_meta_map.get(stock_item_id) or {}
        mode_note = _stock_cost_input_mode_note(stock_cost_meta.get("input_mode"), vat_rate=stock_vat_rate)
        if mode_note:
            stock_cost_notes.append(mode_note)
        if stock_vat_rate is None and line_cost > 0:
            complete = False
            missing_reasons.append(f"Stok karti KDV orani eksik: #{stock_item_id}")
            continue

        purchase_vat = _vat_amount_from_gross(line_cost, vat_rate=stock_vat_rate)
        if purchase_vat is not None:
            purchase_vat_total += purchase_vat

    if stock_cost_total > 0:
        stock_note_parts: list[str] = []
        linked_stock_label = str(item.get("linked_stock_label") or "").strip()
        if linked_stock_label:
            stock_note_parts.append(linked_stock_label)
        if stock_cost_notes:
            stock_note_parts.extend(list(dict.fromkeys(stock_cost_notes)))
        applied_costs.append(
            _component_payload(
                key="stock",
                label="Stok Maliyeti",
                total=stock_cost_total,
                vat=purchase_vat_total,
                kind="stock",
                note="\n".join(part for part in stock_note_parts if part),
            )
        )

    for row in cost_items:
        if not isinstance(row, dict):
            continue
        cost_key = str(row.get("cost_key") or row.get("costKey") or "").strip().casefold()
        if not cost_key:
            continue

        card = cost_card_map.get(cost_key) or {}
        if not card:
            complete = False
            missing_reasons.append(f"Maliyet karti bulunamadi: {cost_key}")
            continue

        card_label = str(card.get("name") or card.get("label") or cost_key).strip() or cost_key
        value_type = str(card.get("valueType") or card.get("calculationType") or "").strip().casefold() or "numeric"
        is_vat_included = bool(card.get("isVatIncluded", True))
        vat_rate = card.get("vatRate")
        normalized_binding = normalize_listing_cost_binding(row, card=card)
        resolution = resolve_listing_cost_source(
            binding=normalized_binding,
            card=card,
            context={
                "item": item,
                "sale_price": sale_price,
                "effective_dimensional_weight": effective_dimensional_weight,
                "platform_code": platform_code,
                "cargo_tariffs": cargo_tariffs,
            },
        )
        if not bool(resolution.get("success")):
            complete = False
            missing_reasons.append(str(resolution.get("missing_reason") or f"Maliyet hesabı başarısız: {card_label}"))
            continue

        resolved_amount = _optional_float(resolution.get("amount"))
        gross_amount = resolved_amount if bool(resolution.get("amount_is_gross", False)) else _gross_amount(
            resolved_amount,
            is_vat_included=is_vat_included,
            vat_rate=vat_rate,
            default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
        )
        if gross_amount is None:
            complete = False
            missing_reasons.append(f"Maliyet hesabı başarısız: {card_label}")
            continue

        source_trace = dict(resolution.get("trace") or {})
        resolution_meta = dict(resolution.get("meta") or {})
        kind_override = str(resolution_meta.get("kind") or "").strip().casefold()
        source_config = dict(normalized_binding.get("source_config") or {})
        selected_provider_name = str(
            resolution_meta.get("selectedCargoProviderName")
            or resolution_meta.get("cargoProviderName")
            or source_config.get("cargoProviderName")
            or ""
        ).strip()
        note_text = str(resolution.get("note") or "").strip()

        if kind_override == "cargo":
            cargo_total += gross_amount
            matched_cargo_tariff_key = resolution_meta.get("matchedTariffKey")
            matched_cargo_tariff_name = resolution_meta.get("matchedTariffName")
            matched_tariff = dict(resolution_meta.get("matchedTariff") or {})
            cargo_vat = _vat_amount_from_gross(
                gross_amount,
                vat_rate=matched_tariff.get("vatRate") if matched_tariff else vat_rate,
                default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
            ) or 0.0
            cargo_vat_total += cargo_vat
            note_parts: list[str] = []
            if note_text:
                note_parts.append(note_text)
            if selected_provider_name and selected_provider_name not in note_parts:
                note_parts.append(selected_provider_name)
            applied_costs.append(
                _component_payload(
                    key=cost_key,
                    label=card_label,
                    total=gross_amount,
                    vat=cargo_vat,
                    kind="cargo",
                    note=" | ".join(part for part in note_parts if part)
                    or str(matched_cargo_tariff_name or matched_cargo_tariff_key or "").strip(),
                    source_type=str(resolution.get("source_type") or ""),
                    source_trace=source_trace,
                )
            )
            continue

        if value_type == "percentage":
            commission_total += gross_amount
            commission_vat = _vat_amount_from_gross(
                gross_amount,
                vat_rate=vat_rate,
                default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
            ) or 0.0
            commission_vat_total += commission_vat
            applied_costs.append(
                _component_payload(
                    key=cost_key,
                    label=card_label,
                    total=gross_amount,
                    vat=commission_vat,
                    kind="commission",
                    note=note_text,
                    source_type=str(resolution.get("source_type") or ""),
                    source_trace=source_trace,
                )
            )
            continue

        other_cost_total += gross_amount
        other_cost_vat = _vat_amount_from_gross(
            gross_amount,
            vat_rate=vat_rate,
            default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
        ) or 0.0
        other_cost_vat_total += other_cost_vat
        applied_costs.append(
            _component_payload(
                key=cost_key,
                label=card_label,
                total=gross_amount,
                vat=other_cost_vat,
                kind="other",
                note=note_text,
                source_type=str(resolution.get("source_type") or ""),
                source_trace=source_trace,
            )
        )

    estimated_profit = None
    estimated_profit_text = "-"
    breakdown: list[dict[str, Any]] = []
    detail_payload: dict[str, Any] = {}
    if sale_price is not None:
        if sale_vat_rate is None:
            complete = False
            missing_reasons.append("Ilan satis KDV orani eksik.")
        sale_vat = _vat_amount_from_gross(sale_price, vat_rate=sale_vat_rate) or 0.0
        input_vat_total = purchase_vat_total + commission_vat_total + cargo_vat_total + other_cost_vat_total
        total_costs = stock_cost_total + commission_total + cargo_total + other_cost_total
        payout_total = sale_price - commission_total - cargo_total
        sale_net_total = _net_amount_from_gross(sale_price, vat_rate=sale_vat_rate) or sale_price
        net_vat = sale_vat - input_vat_total
        estimated_profit = sale_price - total_costs - net_vat
        if complete:
            estimated_profit_text = f"{estimated_profit:.2f} TL"

        breakdown = [
            {
                "label": "Satış Fiyatı",
                "value": sale_price,
                "value_text": _amount_text(sale_price),
                "kind": "income",
            }
        ]
        for component in applied_costs:
            breakdown.append(
                {
                    "label": component.get("label"),
                    "value": component.get("gross"),
                    "value_text": _amount_text(component.get("gross"), signed=True),
                    "kind": component.get("kind") or "cost",
                    "note": component.get("note") or "",
                }
            )
        if purchase_vat_total > 0:
            breakdown.append(
                {
                    "label": "Alıştan KDV",
                    "value": purchase_vat_total,
                    "value_text": _amount_text(purchase_vat_total),
                    "kind": "vat",
                }
            )
        if commission_vat_total > 0:
            breakdown.append(
                {
                    "label": "Komisyondan KDV",
                    "value": commission_vat_total,
                    "value_text": _amount_text(commission_vat_total),
                    "kind": "vat",
                }
            )
        if cargo_vat_total > 0:
            breakdown.append(
                {
                    "label": "Kargodan KDV",
                    "value": cargo_vat_total,
                    "value_text": _amount_text(cargo_vat_total),
                    "kind": "vat",
                }
            )
        if other_cost_vat_total > 0:
            breakdown.append(
                {
                    "label": "Diğer Maliyet KDV",
                    "value": other_cost_vat_total,
                    "value_text": _amount_text(other_cost_vat_total),
                    "kind": "vat",
                }
            )
        breakdown.extend(
            [
                {
                    "label": "Satıştan KDV",
                    "value": sale_vat,
                    "value_text": _amount_text(sale_vat),
                    "kind": "vat",
                },
                {
                    "label": "Nihai KDV",
                    "value": net_vat,
                    "value_text": _delta_text(net_vat),
                    "kind": "vat_balance",
                    "note": _vat_status_note(net_vat),
                },
                {
                    "label": "Tahmini Kar",
                    "value": estimated_profit,
                    "value_text": _amount_text(estimated_profit),
                    "kind": "profit",
                },
            ]
        )

        detail_payload = {
            "summary": {
                "unit_sale_price": unit_sale_price,
                "unit_sale_price_text": _amount_text(unit_sale_price),
                "sale_quantity": sale_quantity_value,
                "sale_quantity_text": sale_quantity_text,
                "sale_price": sale_price,
                "sale_price_text": _amount_text(sale_price),
                "sale_net": sale_net_total,
                "sale_net_text": _amount_text(sale_net_total),
                "sale_vat_rate": sale_vat_rate,
                "sale_vat_rate_text": f"%{sale_vat_rate:.2f}" if sale_vat_rate is not None else "-",
                "sale_vat": sale_vat,
                "sale_vat_text": _amount_text(sale_vat),
                "dimensional_weight": effective_dimensional_weight,
                "dimensional_weight_text": "-" if effective_dimensional_weight is None else f"{effective_dimensional_weight:.2f}",
                "dimensional_weight_source": dimensional_weight_source,
                "dimensional_weight_source_text": (
                    "Ilan desisi"
                    if dimensional_weight_source == "ilan"
                    else "Stok karti toplam desisi"
                    if dimensional_weight_source == "stock"
                    else "Desi verisi yok"
                ),
                "stock_total_desi": stock_total_desi,
                "stock_total_desi_text": "-" if stock_total_desi is None else f"{stock_total_desi:.2f}",
                "stock_desi_is_partial": bool(stock_desi_info.get("is_partial")),
                "stock_desi_missing_stock_ids": list(stock_desi_info.get("missing_stock_ids") or []),
                "cargo_tariff_name": matched_cargo_tariff_name or matched_cargo_tariff_key or "-",
                "linked_stock_label": str(item.get("linked_stock_label") or "").strip(),
            },
            "applied_costs": applied_costs,
            "results": {
                "payout_total": payout_total,
                "payout_total_text": _amount_text(payout_total),
                "total_costs": total_costs,
                "total_costs_text": _amount_text(total_costs),
                "input_vat_total": input_vat_total,
                "input_vat_total_text": _amount_text(input_vat_total),
                "sale_vat": sale_vat,
                "sale_vat_text": _amount_text(sale_vat),
                "net_vat": net_vat,
                "net_vat_text": _delta_text(net_vat),
                "net_vat_note": _vat_status_note(net_vat),
                "estimated_profit": estimated_profit,
                "estimated_profit_text": _amount_text(estimated_profit),
            },
        }
    else:
        missing_reasons.append("Ilan satis fiyati bulunamadi.")

    return {
        "sale_quantity": sale_quantity_value,
        "estimated_profit": estimated_profit,
        "estimated_profit_text": estimated_profit_text,
        "estimated_profit_ready": bool(complete and estimated_profit is not None),
        "stock_cost_total": stock_cost_total,
        "commission_cost": commission_total,
        "cargo_cost": cargo_total,
        "other_cost_total": other_cost_total,
        "sale_vat_rate": sale_vat_rate,
        "sale_vat": sale_vat,
        "purchase_vat": purchase_vat_total,
        "commission_vat": commission_vat_total,
        "cargo_vat": cargo_vat_total,
        "other_cost_vat": other_cost_vat_total,
        "net_vat": net_vat,
        "matched_cargo_tariff_key": matched_cargo_tariff_key,
        "matched_cargo_tariff_name": matched_cargo_tariff_name,
        "estimated_profit_breakdown": breakdown,
        "estimated_profit_detail": detail_payload,
        "estimated_profit_missing_reasons": list(dict.fromkeys(missing_reasons)),
    }


estimate_listing_profit = _estimate_listing_profit_resolver_v1


def _build_listing_cost_snapshot_rows(
    *,
    item: dict[str, Any],
    estimation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    binding_map: dict[str, dict[str, Any]] = {}
    for binding_row in list(item.get("cost_items") or []):
        if not isinstance(binding_row, dict):
            continue
        normalized_binding = normalize_listing_cost_binding(binding_row)
        cost_key = str(normalized_binding.get("cost_key") or "").strip()
        if not cost_key:
            continue
        binding_map[cost_key.casefold()] = {
            "cost_key": cost_key,
            "source_type": str(normalized_binding.get("source_type") or "").strip() or None,
            "source_config": dict(normalized_binding.get("source_config") or {}) or None,
            "cargo_provider_id": _cargo_provider_id_from_source_config(normalized_binding.get("source_config")),
        }

    detail = dict((estimation or {}).get("estimated_profit_detail") or {})
    applied_costs = list(detail.get("applied_costs") or [])
    resolved_map: dict[str, dict[str, Any]] = {}
    for cost_row in applied_costs:
        if not isinstance(cost_row, dict):
            continue
        cost_key = str(cost_row.get("key") or "").strip()
        if not cost_key or cost_key == "stock":
            continue
        source_trace = dict(cost_row.get("source_trace") or {})
        resolver_payload = dict(source_trace.get("resolverPayload") or {})
        resolver_meta = dict(resolver_payload.get("meta") or {})
        resolved_map[cost_key.casefold()] = {
            "cost_key": cost_key,
            "source_type": str(cost_row.get("source_type") or "").strip() or None,
            "source_config": dict(source_trace.get("sourceConfig") or {}) or None,
            "cargo_provider_id": _cargo_provider_id_from_source_config(source_trace.get("sourceConfig")),
            "resolved_amount": _optional_float(cost_row.get("gross")),
            "resolved_net_amount": _optional_float(cost_row.get("net")),
            "resolved_vat_amount": _optional_float(cost_row.get("vat")),
            "currency": "TRY",
            "note": str(cost_row.get("note") or "").strip() or None,
            "resolution_meta": resolver_meta or None,
            "updated_at": _utcnow_naive(),
        }
    rows: list[dict[str, Any]] = []
    for normalized_key in sorted(set(binding_map.keys()) | set(resolved_map.keys())):
        binding_payload = dict(binding_map.get(normalized_key) or {})
        resolved_payload = dict(resolved_map.get(normalized_key) or {})
        cost_key = str(
            binding_payload.get("cost_key")
            or resolved_payload.get("cost_key")
            or normalized_key
        ).strip()
        if not cost_key:
            continue
        rows.append(
            {
                "cost_key": cost_key,
                "source_type": (
                    str(binding_payload.get("source_type") or "").strip()
                    or str(resolved_payload.get("source_type") or "").strip()
                    or None
                ),
                "cargo_provider_id": (
                    _safe_int_id(binding_payload.get("cargo_provider_id"))
                    if binding_payload.get("cargo_provider_id") is not None
                    else _safe_int_id(resolved_payload.get("cargo_provider_id"))
                ),
                "source_config": (
                    dict(binding_payload.get("source_config") or {}) or None
                    if binding_payload.get("source_config") is not None
                    else dict(resolved_payload.get("source_config") or {}) or None
                ),
                "resolved_amount": _optional_float(resolved_payload.get("resolved_amount")),
                "resolved_net_amount": _optional_float(resolved_payload.get("resolved_net_amount")),
                "resolved_vat_amount": _optional_float(resolved_payload.get("resolved_vat_amount")),
                "currency": str(resolved_payload.get("currency") or "TRY").strip() or "TRY",
                "note": str(resolved_payload.get("note") or "").strip() or None,
                "resolution_meta": _clean_snapshot_resolution_meta(resolved_payload.get("resolution_meta")),
                "updated_at": resolved_payload.get("updated_at") or _utcnow_naive(),
            }
        )
    return rows


def _resolve_listing_primary_id(
    session: Session,
    *,
    listing_id: Any = None,
    api_account_id: Any = None,
    product_id: Any = None,
) -> Optional[int]:
    resolved_listing_id = _safe_int_id(listing_id)
    if resolved_listing_id is not None:
        return resolved_listing_id

    try:
        resolved_api_account_id = int(api_account_id)
    except Exception:
        return None
    resolved_product_id = str(product_id or "").strip()
    if not resolved_product_id:
        return None

    row = session.exec(
        select(ListingProduct.pk)
        .where(ListingProduct.api_account_id == resolved_api_account_id)
        .where(ListingProduct.product_id == resolved_product_id)
    ).first()
    return _safe_int_id(row)


def set_listing_cost_snapshots(
    *,
    listing_id: Optional[int] = None,
    api_account_id: Optional[int] = None,
    product_id: Optional[str] = None,
    snapshot_rows: list[dict[str, Any]],
    db_name: str = DB_NAME,
) -> Result:
    try:
        engine = _engine(db_name)
        with Session(engine) as session:
            with session.begin():
                batch_now = _utcnow_naive()
                resolved_listing_id = _resolve_listing_primary_id(
                    session,
                    listing_id=listing_id,
                    api_account_id=api_account_id,
                    product_id=product_id,
                )
                if resolved_listing_id is None:
                    return Result.fail("Snapshot icin ilan kaydi bulunamadi.", close_dialog=False)
                requested_cost_keys = {
                    str(row.get("cost_key") or "").strip().casefold()
                    for row in list(snapshot_rows or [])
                    if isinstance(row, dict) and str(row.get("cost_key") or "").strip()
                }
                cost_item_id_map = _resolve_cost_item_ids(
                    session,
                    normalized_cost_keys=requested_cost_keys,
                )
                for row in list(snapshot_rows or []):
                    if not isinstance(row, dict):
                        continue
                    cost_key = str(row.get("cost_key") or "").strip()
                    if not cost_key:
                        continue
                    session.add(
                        ListingProductCostSnapshot(
                            status=_normalize_snapshot_status(row.get("status"), fallback=SNAPSHOT_STATUS_SET),
                            cost_item_id=cost_item_id_map.get(cost_key.casefold()),
                            cargo_provider_id=_safe_int_id(row.get("cargo_provider_id"))
                            or _cargo_provider_id_from_source_config(row.get("source_config")),
                            listing_id=int(resolved_listing_id),
                            cost_key=cost_key,
                            source_type=str(row.get("source_type") or "").strip() or None,
                            source_config=dict(row.get("source_config") or {}) or None,
                            resolved_amount=_optional_float(row.get("resolved_amount")),
                            resolved_net_amount=_optional_float(row.get("resolved_net_amount")),
                            resolved_vat_amount=_optional_float(row.get("resolved_vat_amount")),
                            currency=str(row.get("currency") or "TRY").strip() or "TRY",
                            note=str(row.get("note") or "").strip() or None,
                            resolution_meta=_clean_snapshot_resolution_meta(row.get("resolution_meta")),
                            created_at=row.get("created_at") or batch_now,
                            updated_at=row.get("updated_at") or batch_now,
                        )
                    )
        _emit_listing_signal(
            "cost_snapshots_synced",
            {
                "listing_id": int(resolved_listing_id),
                "api_account_id": _safe_int_id(api_account_id),
                "product_id": str(product_id or "").strip() or None,
                "snapshot_count": len(list(snapshot_rows or [])),
            },
        )
        return Result.ok("Maliyet snapshotları güncellendi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def sync_listing_cost_snapshots_for_item(
    *,
    item: dict[str, Any],
    estimation: dict[str, Any] | None,
    db_name: str = DB_NAME,
) -> Result:
    listing_id = item.get("listing_id")
    if listing_id in (None, ""):
        listing_id = item.get("listingId")
    api_account_id = item.get("api_account_id")
    product_id = _product_id_from_item(item)
    if listing_id in (None, "") and (api_account_id in (None, "") or not product_id):
        return Result.ok("Maliyet snapshotı için ürün anahtarı bulunamadı.", close_dialog=False)
    try:
        engine = _engine(db_name)
        with Session(engine) as session:
            with session.begin():
                batch_now = _utcnow_naive()
                resolved_listing_id = _resolve_listing_primary_id(
                    session,
                    listing_id=_safe_int_id(listing_id),
                    api_account_id=_safe_int_id(api_account_id),
                    product_id=str(product_id),
                )
                if resolved_listing_id is None:
                    return Result.fail("Snapshot için ilan kaydı bulunamadı.", close_dialog=False)

                item_with_listing = dict(item)
                item_with_listing["listing_id"] = int(resolved_listing_id)
                desired_rows = _build_listing_cost_snapshot_rows(item=item_with_listing, estimation=estimation)
                desired_by_key = {
                    str(row.get("cost_key") or "").strip().casefold(): dict(row)
                    for row in desired_rows
                    if str(row.get("cost_key") or "").strip()
                }
                cost_item_id_map = _resolve_cost_item_ids(
                    session,
                    normalized_cost_keys=set(desired_by_key.keys()),
                )
                latest_snapshot_rows = _latest_snapshot_rows_by_listing(
                    session,
                    listing_ids=[int(resolved_listing_id)],
                )
                current_snapshot_by_key: dict[str, ListingProductCostSnapshot] = {}
                for (listing_key, normalized_key), snapshot_row in latest_snapshot_rows.items():
                    if listing_key == int(resolved_listing_id):
                        current_snapshot_by_key[normalized_key] = snapshot_row

                inserted_count = 0
                updated_count = 0

                for normalized_key, desired_row in desired_by_key.items():
                    desired_payload = dict(desired_row)
                    desired_payload["cost_item_id"] = cost_item_id_map.get(normalized_key)
                    desired_payload["cargo_provider_id"] = (
                        _safe_int_id(desired_payload.get("cargo_provider_id"))
                        or _cargo_provider_id_from_source_config(desired_payload.get("source_config"))
                    )
                    desired_payload["currency"] = str(desired_payload.get("currency") or "TRY").strip() or "TRY"
                    desired_payload["resolution_meta"] = _clean_snapshot_resolution_meta(desired_payload.get("resolution_meta"))
                    desired_payload["updated_at"] = desired_payload.get("updated_at") or batch_now
                    desired_payload["created_at"] = desired_payload.get("created_at") or batch_now

                    current_row = current_snapshot_by_key.get(normalized_key)
                    if current_row is None or _snapshot_removed(current_row):
                        session.add(
                            ListingProductCostSnapshot(
                                status=SNAPSHOT_STATUS_APPEND,
                                cost_item_id=desired_payload.get("cost_item_id"),
                                cargo_provider_id=desired_payload.get("cargo_provider_id"),
                                listing_id=int(resolved_listing_id),
                                cost_key=str(desired_payload.get("cost_key") or "").strip(),
                                source_type=desired_payload.get("source_type"),
                                source_config=desired_payload.get("source_config"),
                                resolved_amount=desired_payload.get("resolved_amount"),
                                resolved_net_amount=desired_payload.get("resolved_net_amount"),
                                resolved_vat_amount=desired_payload.get("resolved_vat_amount"),
                                currency=desired_payload.get("currency"),
                                note=desired_payload.get("note"),
                                resolution_meta=desired_payload.get("resolution_meta"),
                                created_at=desired_payload.get("created_at"),
                                updated_at=desired_payload.get("updated_at"),
                            )
                        )
                        inserted_count += 1
                        continue

                    if _snapshot_row_matches_payload(current_row, desired_payload):
                        continue

                    if (
                        _snapshot_row_binding_matches_payload(current_row, desired_payload)
                        and not _snapshot_has_resolved_payload(current_row)
                    ):
                        current_row.cost_item_id = desired_payload.get("cost_item_id")
                        current_row.cargo_provider_id = desired_payload.get("cargo_provider_id")
                        current_row.source_type = desired_payload.get("source_type")
                        current_row.source_config = desired_payload.get("source_config")
                        current_row.resolved_amount = desired_payload.get("resolved_amount")
                        current_row.resolved_net_amount = desired_payload.get("resolved_net_amount")
                        current_row.resolved_vat_amount = desired_payload.get("resolved_vat_amount")
                        current_row.currency = desired_payload.get("currency")
                        current_row.note = desired_payload.get("note")
                        current_row.resolution_meta = desired_payload.get("resolution_meta")
                        current_row.updated_at = desired_payload.get("updated_at")
                        current_row.status = _normalize_snapshot_status(getattr(current_row, "status", None), fallback=SNAPSHOT_STATUS_APPEND)
                        updated_count += 1
                        continue

                    session.add(
                        ListingProductCostSnapshot(
                            status=SNAPSHOT_STATUS_SET,
                            cost_item_id=desired_payload.get("cost_item_id"),
                            cargo_provider_id=desired_payload.get("cargo_provider_id"),
                            listing_id=int(resolved_listing_id),
                            cost_key=str(desired_payload.get("cost_key") or "").strip(),
                            source_type=desired_payload.get("source_type"),
                            source_config=desired_payload.get("source_config"),
                            resolved_amount=desired_payload.get("resolved_amount"),
                            resolved_net_amount=desired_payload.get("resolved_net_amount"),
                            resolved_vat_amount=desired_payload.get("resolved_vat_amount"),
                            currency=desired_payload.get("currency"),
                            note=desired_payload.get("note"),
                            resolution_meta=desired_payload.get("resolution_meta"),
                            created_at=batch_now,
                            updated_at=desired_payload.get("updated_at") or batch_now,
                        )
                    )
                    inserted_count += 1

                desired_keys = set(desired_by_key.keys())
                for normalized_key, current_row in current_snapshot_by_key.items():
                    if normalized_key in desired_keys or _snapshot_removed(current_row):
                        continue
                    session.add(
                        ListingProductCostSnapshot(
                            status=SNAPSHOT_STATUS_REMOVE,
                            cost_item_id=_safe_int_id(getattr(current_row, "cost_item_id", None)),
                            cargo_provider_id=_safe_int_id(getattr(current_row, "cargo_provider_id", None)),
                            listing_id=int(resolved_listing_id),
                            cost_key=str(getattr(current_row, "cost_key", "") or "").strip(),
                            source_type=str(getattr(current_row, "source_type", "") or "").strip() or None,
                            source_config=dict(getattr(current_row, "source_config", None) or {}) or None,
                            resolved_amount=_optional_float(getattr(current_row, "resolved_amount", None)),
                            resolved_net_amount=_optional_float(getattr(current_row, "resolved_net_amount", None)),
                            resolved_vat_amount=_optional_float(getattr(current_row, "resolved_vat_amount", None)),
                            currency=str(getattr(current_row, "currency", "") or "TRY").strip() or "TRY",
                            note=str(getattr(current_row, "note", "") or "").strip() or None,
                            resolution_meta=_clean_snapshot_resolution_meta(getattr(current_row, "resolution_meta", None)),
                            created_at=batch_now,
                            updated_at=batch_now,
                        )
                    )
                    inserted_count += 1

        _emit_listing_signal(
            "cost_snapshots_synced",
            {
                "listing_id": int(_safe_int_id(listing_id) or resolved_listing_id),
                "api_account_id": _safe_int_id(api_account_id),
                "product_id": str(product_id or "").strip() or None,
                "snapshot_count": inserted_count,
                "updated_count": updated_count,
            },
        )
        return Result.ok("Maliyet snapshotları güncellendi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def save_listings_to_db(
    items: list[dict],
    *,
    db_name: str = DB_NAME,
    sync_api_account_ids: Optional[list[int]] = None,
    prune_missing: bool = False,
) -> Result:
    """
    Upsert listings. Preserves existing stock_item_id (mapping) if present.
    """
    try:
        now = _utcnow_naive()
        cleaned: list[dict] = []
        keys: list[tuple[int, str]] = []
        sync_ids = {
            int(value)
            for value in (sync_api_account_ids or [])
            if value is not None and str(value).strip()
        }
        incoming_ids_by_account: dict[int, set[str]] = {}

        for it in items or []:
            rec = _normalize_listing_item(it)
            if not rec:
                continue
            key = (rec["api_account_id"], rec["product_id"])
            keys.append(key)
            cleaned.append(rec)
            incoming_ids_by_account.setdefault(int(rec["api_account_id"]), set()).add(str(rec["product_id"]))

        if not cleaned and not sync_ids:
            return Result.ok(
                "Kaydedilecek ürün yok.",
                close_dialog=False,
                data={
                    "attempted": 0,
                    "changed": False,
                    "counts": {"inserted": 0, "updated": 0, "history": 0, "deleted": 0},
                },
            )

        # existing mappings (preserve stock_item_id + created_at)
        engine = _engine(db_name)
        existing_map: dict[tuple[int, str], ListingProduct] = {}
        if keys:
            acc_ids = list({k[0] for k in keys})
            prod_ids = list({k[1] for k in keys})
            with Session(engine) as session:
                stmt = (
                    select(ListingProduct)
                    .where(ListingProduct.api_account_id.in_(acc_ids))
                    .where(ListingProduct.product_id.in_(prod_ids))
                )
                rows = session.exec(stmt).all() or []
                for row in rows:
                    existing_map[(row.api_account_id, row.product_id)] = row

        tracked_fields = {"quantity", "list_price", "sale_price", "on_sale", "archived", "title"}

        def _is_changed(existing_row: ListingProduct, rec: dict) -> bool:
            for k in LISTING_CHANGE_FIELDS:
                v = rec.get(k)
                try:
                    existing_val = getattr(existing_row, k)
                except Exception:
                    existing_val = None
                if not _listing_field_values_equal(k, existing_val, v):
                    return True
            return False

        def _build_changes(existing_row: ListingProduct, rec: dict) -> dict:
            changes: dict = {}
            for field in tracked_fields:
                old_val = getattr(existing_row, field, None)
                new_val = rec.get(field)
                # Skip history when old value is None (baseline) or new value is None
                if old_val is None or new_val is None:
                    continue
                if old_val != new_val:
                    changes[field] = {"old": old_val, "new": new_val}
            return changes

        new_records: list[dict] = []
        changed_records: list[dict] = []
        history_records: list[dict] = []
        deleted_count = 0

        for rec in cleaned:
            key = (rec["api_account_id"], rec["product_id"])
            existing = existing_map.get(key)
            if existing is not None:
                rec["stock_item_id"] = existing.stock_item_id
                rec["created_at"] = existing.created_at
                if _is_changed(existing, rec):
                    rec["updated_at"] = now
                    changed_records.append(rec)
                    changes = _build_changes(existing, rec)
                    if changes:
                        history_records.append(
                            {
                                "api_account_id": rec["api_account_id"],
                                "product_id": rec["product_id"],
                                "changes": changes,
                                "created_at": now,
                            }
                        )
            else:
                rec["created_at"] = now
                rec["updated_at"] = now
                new_records.append(rec)

        if prune_missing and sync_ids:
            with Session(engine) as session:
                stale_rows = session.exec(
                    select(ListingProduct).where(ListingProduct.api_account_id.in_(list(sync_ids)))
                ).all() or []
                stale_pairs = {
                    (int(row.api_account_id), str(row.product_id))
                    for row in stale_rows
                    if str(row.product_id) not in incoming_ids_by_account.get(int(row.api_account_id), set())
                }
                if stale_pairs:
                    stale_listing_ids = [
                        int(row.pk)
                        for row in stale_rows
                        if row.pk is not None and (int(row.api_account_id), str(row.product_id)) in stale_pairs
                    ]
                    if stale_listing_ids:
                        session.exec(
                            delete(ListingProductCostSnapshot).where(
                                ListingProductCostSnapshot.listing_id.in_(stale_listing_ids)
                            )
                        )
                        session.exec(delete(ListingProduct).where(ListingProduct.pk.in_(stale_listing_ids)))
                        deleted_count += len(stale_listing_ids)

                    if stale_listing_ids:
                        session.exec(
                            delete(ListingProductStockSnapshot).where(
                                ListingProductStockSnapshot.listing_id.in_(stale_listing_ids)
                            )
                        )

                    session.commit()

        payload = new_records + changed_records
        if payload:
            res = create_records(
                model=ListingProduct,
                data_list=payload,
                db_name=db_name,
                conflict_keys=["api_account_id", "product_id"],
                mode="update",
            )
            if not res.success:
                return res

            if history_records:
                create_records(
                    model=ListingProductHistory,
                    data_list=history_records,
                    db_name=db_name,
                    conflict_keys=None,
                    mode="plain",
                )

        if not new_records and not changed_records and deleted_count == 0:
            return Result.ok(
                "Ürünler güncel, yazılacak değişiklik yok.",
                close_dialog=False,
                data={
                    "attempted": len(cleaned),
                    "changed": False,
                    "counts": {"inserted": 0, "updated": 0, "history": 0, "deleted": 0},
                },
            )

        return Result.ok(
            "Ürünler veritabanına kaydedildi.",
            close_dialog=False,
            data={
                "attempted": len(cleaned),
                "changed": bool(new_records or changed_records or deleted_count),
                "counts": {
                    "inserted": len(new_records),
                    "updated": len(changed_records),
                    "history": len(history_records),
                    "deleted": deleted_count,
                },
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_listings_from_db(
    *,
    api_account_ids: Optional[list[int]] = None,
    listing_status: Optional[str] = None,
    active_listings: Optional[bool] = None,
    approved: Optional[bool] = None,
    barcode: Optional[str] = None,
    stock_code: Optional[str] = None,
    brand: Optional[str | list[str]] = None,
    product_id: Optional[str] = None,
    search: Optional[str] = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        engine = _engine(db_name)
        with Session(engine) as session:
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
                    brands = [str(b) for b in brand if str(b)]
                    if brands:
                        stmt = stmt.where(ListingProduct.brand.in_(brands))
                else:
                    stmt = stmt.where(ListingProduct.brand.like(f"%{brand}%"))
            if product_id:
                stmt = stmt.where(ListingProduct.product_id.like(f"%{product_id}%"))
            if search:
                q = f"%{search}%"
                stmt = stmt.where(
                    or_(
                        ListingProduct.title.like(q),
                        ListingProduct.barcode.like(q),
                        ListingProduct.stock_code.like(q),
                        ListingProduct.brand.like(q),
                        ListingProduct.product_id.like(q),
                    )
                )

            status = (listing_status or "").strip().lower() if listing_status else None
            if status is None and active_listings is True:
                status = "active"

            if status == "active":
                stmt = stmt.where(ListingProduct.on_sale.is_(True))
                stmt = stmt.where(or_(ListingProduct.archived.is_(None), ListingProduct.archived.is_(False)))
            elif status == "archived":
                stmt = stmt.where(ListingProduct.archived.is_(True))
            elif status == "out_of_stock":
                stmt = stmt.where(or_(ListingProduct.quantity.is_(None), ListingProduct.quantity <= 0))
                stmt = stmt.where(or_(ListingProduct.archived.is_(None), ListingProduct.archived.is_(False)))

            stmt = stmt.order_by(ListingProduct.updated_at.desc())
            rows = session.exec(stmt).all() or []

            latest_stock_snapshot_rows: dict[tuple[int, int], ListingProductStockSnapshot] = {}
            latest_cost_snapshot_rows: dict[tuple[int, str], ListingProductCostSnapshot] = {}
            if rows:
                listing_ids = [int(r.pk) for r in rows if r.pk is not None]
                latest_stock_snapshot_rows = _latest_stock_snapshot_rows_by_listing(session, listing_ids=listing_ids)
                latest_cost_snapshot_rows = _latest_snapshot_rows_by_listing(session, listing_ids=listing_ids)

        items_map: dict[int, list[dict]] = {}
        for (listing_id, _stock_item_id), snapshot_row in latest_stock_snapshot_rows.items():
            if _snapshot_removed(snapshot_row):
                continue
            binding_payload = _stock_binding_payload_from_snapshot(snapshot_row)
            if binding_payload is None:
                continue
            items_map.setdefault(listing_id, []).append(binding_payload)

        provider_rows_by_id: dict[int, LogisticsCargoProvider] = {}
        requested_provider_ids = {
            _safe_int_id(getattr(snapshot_row, "cargo_provider_id", None))
            for snapshot_row in latest_cost_snapshot_rows.values()
        }
        requested_provider_ids.discard(None)
        if requested_provider_ids:
            with Session(engine) as enrich_session:
                for provider_row in enrich_session.exec(
                    select(LogisticsCargoProvider).where(
                        LogisticsCargoProvider.pk.in_(sorted(int(value) for value in requested_provider_ids))
                    )
                ).all() or []:
                    provider_pk = _safe_int_id(getattr(provider_row, "pk", None))
                    if provider_pk is not None:
                        provider_rows_by_id[provider_pk] = provider_row

        cost_items_map: dict[int, list[dict]] = {}
        for (listing_id, _cost_key), snapshot_row in latest_cost_snapshot_rows.items():
            if _snapshot_removed(snapshot_row):
                continue
            binding_payload = _binding_payload_from_snapshot(snapshot_row)
            if binding_payload is None:
                continue
            provider_id = _safe_int_id(binding_payload.get("cargo_provider_id"))
            if provider_id is not None:
                provider_row = provider_rows_by_id.get(provider_id)
                if provider_row is not None:
                    source_config = dict(binding_payload.get("source_config") or {}) or {}
                    source_config.setdefault("cargoProviderId", provider_id)
                    source_config.setdefault(
                        "cargoProviderCode",
                        str(getattr(provider_row, "cargoProviderCode", "") or "").strip().upper() or None,
                    )
                    source_config.setdefault(
                        "cargoProviderName",
                        str(getattr(provider_row, "cargoProviderName", "") or "").strip() or None,
                    )
                    binding_payload["source_config"] = source_config
                    binding_payload["sourceConfig"] = dict(source_config)
            cost_items_map.setdefault(listing_id, []).append(binding_payload)

        items: list[dict] = []
        for row in rows:
            raw = row.raw if isinstance(row.raw, dict) else {}
            listing_pk = int(row.pk) if row.pk is not None else None
            item = dict(raw)
            item.update(
                {
                    "api_account_id": row.api_account_id,
                    "productId": row.product_id,
                    "title": row.title,
                    "barcode": row.barcode,
                    "stockCode": row.stock_code,
                    "brand": row.brand,
                    "quantity": row.quantity,
                    "approved": row.approved,
                    "archived": row.archived,
                    "on_sale": row.on_sale,
                    "productCode": row.product_code,
                    "batchRequestId": row.batch_request_id,
                    "supplierId": row.supplier_id,
                    "createDateTime": row.create_datetime,
                    "lastUpdateDate": row.last_update_date,
                    "gender": row.gender,
                    "categoryName": row.category_name,
                    "productMainId": row.product_main_id,
                    "description": row.description,
                    "stockUnitType": row.stock_unit_type,
                    "listPrice": row.list_price,
                    "salePrice": row.sale_price,
                    "vatRate": row.vat_rate,
                    "dimensionalWeight": row.dimensional_weight,
                    "locationBasedDelivery": row.location_based_delivery,
                    "lotNumber": row.lot_number,
                    "specialConsumptionTax": row.special_consumption_tax,
                    "deliveryOption": row.delivery_option,
                    "images": row.images,
                    "attributes": row.attributes,
                    "platformListingId": row.platform_listing_id,
                    "stockId": row.stock_id,
                    "hasActiveCampaign": row.has_active_campaign,
                    "locked": row.locked,
                    "productContentId": row.product_content_id,
                    "pimCategoryId": row.pim_category_id,
                    "brandId": row.brand_id,
                    "version": row.version,
                    "color": row.color,
                    "size": row.size,
                    "lockedByUnSuppliedReason": row.locked_by_unsupplied_reason,
                    "productUrl": row.product_url,
                    "listing_id": listing_pk,
                    "listingId": listing_pk,
                    "stock_item_id": row.stock_item_id,
                    "stock_items": items_map.get(listing_pk, []) if listing_pk is not None else [],
                    "cost_items": cost_items_map.get(listing_pk, []) if listing_pk is not None else [],
                }
            )
            items.append(item)

        return Result.ok(
            f"{len(items)} ürün cache'den alındı.",
            close_dialog=False,
            data={"items": items},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_listing_brands_from_db(
    *,
    api_account_ids: Optional[list[int]] = None,
    listing_status: Optional[str] = None,
    active_listings: Optional[bool] = None,
    approved: Optional[bool] = None,
    barcode: Optional[str] = None,
    stock_code: Optional[str] = None,
    product_id: Optional[str] = None,
    search: Optional[str] = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        engine = _engine(db_name)
        with Session(engine) as session:
            stmt = select(ListingProduct.brand)
            if api_account_ids:
                stmt = stmt.where(ListingProduct.api_account_id.in_(api_account_ids))
            if approved is not None:
                stmt = stmt.where(ListingProduct.approved == bool(approved))
            if barcode:
                stmt = stmt.where(ListingProduct.barcode.like(f"%{barcode}%"))
            if stock_code:
                stmt = stmt.where(ListingProduct.stock_code.like(f"%{stock_code}%"))
            if product_id:
                stmt = stmt.where(ListingProduct.product_id.like(f"%{product_id}%"))
            if search:
                q = f"%{search}%"
                stmt = stmt.where(
                    or_(
                        ListingProduct.title.like(q),
                        ListingProduct.barcode.like(q),
                        ListingProduct.stock_code.like(q),
                        ListingProduct.brand.like(q),
                        ListingProduct.product_id.like(q),
                    )
                )

            status = (listing_status or "").strip().lower() if listing_status else None
            if status is None and active_listings is True:
                status = "active"

            if status == "active":
                stmt = stmt.where(ListingProduct.on_sale.is_(True))
                stmt = stmt.where(or_(ListingProduct.archived.is_(None), ListingProduct.archived.is_(False)))
            elif status == "archived":
                stmt = stmt.where(ListingProduct.archived.is_(True))
            elif status == "out_of_stock":
                stmt = stmt.where(or_(ListingProduct.quantity.is_(None), ListingProduct.quantity <= 0))
                stmt = stmt.where(or_(ListingProduct.archived.is_(None), ListingProduct.archived.is_(False)))

            stmt = stmt.where(ListingProduct.brand.is_not(None))
            stmt = stmt.where(func.trim(ListingProduct.brand) != "")
            stmt = stmt.distinct().order_by(func.lower(ListingProduct.brand), ListingProduct.brand)
            brands = [
                str(value or "").strip()
                for value in (session.exec(stmt).all() or [])
                if str(value or "").strip()
            ]
        return Result.ok(data={"brands": brands})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def update_listing_stock_item(
    *,
    api_account_id: int,
    product_id: str,
    stock_item_id: Optional[int],
    db_name: str = DB_NAME,
) -> Result:
    try:
        return set_listing_stock_items(
            api_account_id=api_account_id,
            product_id=product_id,
            stock_items=[{"stock_item_id": stock_item_id, "qty": 1}] if stock_item_id else [],
            db_name=db_name,
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def set_listing_stock_items(
    *,
    api_account_id: int,
    product_id: str,
    stock_items: list[dict],
    db_name: str = DB_NAME,
) -> Result:
    try:
        normalized = _normalize_stock_items(stock_items)
        engine = _engine(db_name)
        normalized_valid = list(normalized or [])
        invalid_ids: list[int] = []
        if normalized_valid:
            with Session(engine) as session:
                has_any_stock_cards = session.exec(select(StockItem.pk).limit(1)).first() is not None
                if has_any_stock_cards:
                    requested_ids = sorted(
                        {
                            int(it.get("stock_item_id"))
                            for it in normalized_valid
                            if it.get("stock_item_id") is not None
                        }
                    )
                    valid_ids: set[int] = set()
                    if requested_ids:
                        stock_stmt = select(StockItem.pk).where(StockItem.pk.in_(requested_ids))
                        for stock_id_row in (session.exec(stock_stmt).all() or []):
                            try:
                                valid_ids.add(int(stock_id_row))
                            except Exception:
                                continue
                    invalid_ids = [sid for sid in requested_ids if sid not in valid_ids]
                    normalized_valid = [
                        it for it in normalized_valid
                        if int(it.get("stock_item_id")) in valid_ids
                    ]
        with Session(engine) as session:
            with session.begin():
                batch_now = _utcnow_naive()
                resolved_listing_id = _resolve_listing_primary_id(
                    session,
                    api_account_id=int(api_account_id),
                    product_id=str(product_id),
                )
                if resolved_listing_id is None:
                    return Result.fail("Urun eslesmesi icin ilan kaydi bulunamadi.", close_dialog=False)

                latest_stock_snapshot_rows = _latest_stock_snapshot_rows_by_listing(
                    session,
                    listing_ids=[int(resolved_listing_id)],
                )
                current_snapshot_by_stock_id: dict[int, ListingProductStockSnapshot] = {}
                for (listing_key, stock_item_key), snapshot_row in latest_stock_snapshot_rows.items():
                    if listing_key == int(resolved_listing_id):
                        current_snapshot_by_stock_id[stock_item_key] = snapshot_row

                desired_by_stock_id = {
                    int(it["stock_item_id"]): {"stock_item_id": int(it["stock_item_id"]), "qty": float(it["qty"])}
                    for it in normalized_valid
                    if it.get("stock_item_id") is not None
                }

                changed = False
                for stock_item_key, desired_payload in desired_by_stock_id.items():
                    current_row = current_snapshot_by_stock_id.get(stock_item_key)
                    if current_row is None or _snapshot_removed(current_row):
                        session.add(
                            ListingProductStockSnapshot(
                                status=SNAPSHOT_STATUS_APPEND,
                                listing_id=int(resolved_listing_id),
                                stock_item_id=int(stock_item_key),
                                qty=float(desired_payload["qty"]),
                                created_at=batch_now,
                                updated_at=batch_now,
                            )
                        )
                        changed = True
                        continue
                    if _stock_snapshot_row_matches_payload(current_row, desired_payload):
                        continue
                    session.add(
                        ListingProductStockSnapshot(
                            status=SNAPSHOT_STATUS_SET,
                            listing_id=int(resolved_listing_id),
                            stock_item_id=int(stock_item_key),
                            qty=float(desired_payload["qty"]),
                            created_at=batch_now,
                            updated_at=batch_now,
                        )
                    )
                    changed = True

                for stock_item_key, current_row in current_snapshot_by_stock_id.items():
                    if stock_item_key in desired_by_stock_id or _snapshot_removed(current_row):
                        continue
                    session.add(
                        ListingProductStockSnapshot(
                            status=SNAPSHOT_STATUS_REMOVE,
                            listing_id=int(resolved_listing_id),
                            stock_item_id=int(stock_item_key),
                            qty=float(getattr(current_row, "qty", 0.0) or 0.0),
                            created_at=batch_now,
                            updated_at=batch_now,
                        )
                    )
                    changed = True

        if not changed and not invalid_ids:
            return Result.ok("Urun eslesmesi zaten guncel.", close_dialog=False)

        primary_stock_item_id: Optional[int] = None
        if normalized_valid:
            try:
                primary_stock_item_id = int(normalized_valid[0].get("stock_item_id"))
            except Exception:
                primary_stock_item_id = None

        update_records(
            ListingProduct,
            filters={"api_account_id": int(api_account_id), "product_id": str(product_id)},
            update_data={"updated_at": _utcnow_naive(), "stock_item_id": primary_stock_item_id},
            db_name=db_name,
        )
        _emit_listing_signal(
            "stock_matches_changed",
            {
                "api_account_id": int(api_account_id),
                "product_id": str(product_id),
                "match_count": len(normalized_valid),
                "stock_item_ids": [
                    int(it["stock_item_id"])
                    for it in normalized_valid
                    if it.get("stock_item_id") is not None
                ],
                "invalid_stock_item_ids": list(invalid_ids),
            },
        )

        if invalid_ids:
            return Result.ok(
                f"Urun eslesmesi guncellendi. Gecersiz stok kartlari atlandi: {', '.join(str(v) for v in invalid_ids)}",
                close_dialog=False,
            )

        return Result.ok("Ürün eşleşmesi güncellendi.", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def set_listing_cost_items(
    *,
    api_account_id: int,
    product_id: str,
    cost_items: list[dict],
    db_name: str = DB_NAME,
) -> Result:
    try:
        normalized = _normalize_cost_items(cost_items)
        engine = _engine(db_name)
        changed = False
        with Session(engine) as session:
            with session.begin():
                batch_now = _utcnow_naive()
                resolved_listing_id = _resolve_listing_primary_id(
                    session,
                    api_account_id=api_account_id,
                    product_id=product_id,
                )
                if resolved_listing_id is None:
                    return Result.fail("Maliyet eslesmesi icin ilan kaydi bulunamadi.", close_dialog=False)
                latest_snapshot_rows = _latest_snapshot_rows_by_listing(
                    session,
                    listing_ids=[int(resolved_listing_id)],
                )
                current_snapshot_by_key: dict[str, ListingProductCostSnapshot] = {}
                for (listing_key, normalized_key), snapshot_row in latest_snapshot_rows.items():
                    if listing_key != int(resolved_listing_id):
                        continue
                    current_snapshot_by_key[normalized_key] = snapshot_row

                requested_cost_keys = {
                    str(it.get("cost_key") or "").strip().casefold()
                    for it in normalized
                    if str(it.get("cost_key") or "").strip()
                }
                cost_item_id_map = _resolve_cost_item_ids(
                    session,
                    normalized_cost_keys=requested_cost_keys,
                )
                account_platform = str(
                    session.exec(
                        select(ApiAccount.platform).where(ApiAccount.pk == int(api_account_id))
                    ).first()
                    or ""
                ).strip().upper()

                requested_provider_ids = {
                    _cargo_provider_id_from_source_config(it.get("source_config"))
                    for it in normalized
                    if _binding_requires_cargo_provider(
                        cost_key=it.get("cost_key"),
                        source_type=it.get("source_type"),
                        source_config=it.get("source_config"),
                    )
                }
                requested_provider_ids.discard(None)
                provider_rows_by_id: dict[int, LogisticsCargoProvider] = {}
                if requested_provider_ids:
                    for provider_row in session.exec(
                        select(LogisticsCargoProvider).where(
                            LogisticsCargoProvider.pk.in_(sorted(int(value) for value in requested_provider_ids))
                        )
                    ).all() or []:
                        provider_pk = _safe_int_id(getattr(provider_row, "pk", None))
                        if provider_pk is not None:
                            provider_rows_by_id[provider_pk] = provider_row

                for it in normalized:
                    cost_key = str(it.get("cost_key") or "").strip()
                    if not cost_key:
                        continue
                    normalized_key = cost_key.casefold()
                    source_config = dict(it.get("source_config") or {}) or None
                    cargo_provider_id = _cargo_provider_id_from_source_config(source_config)
                    if _binding_requires_cargo_provider(
                        cost_key=cost_key,
                        source_type=it.get("source_type"),
                        source_config=source_config,
                    ):
                        if cargo_provider_id is None:
                            return Result.fail(
                                "Kargo maliyeti için bir kargo firması seçilmelidir.",
                                close_dialog=False,
                            )
                        provider_row = provider_rows_by_id.get(cargo_provider_id)
                        if provider_row is None:
                            return Result.fail(
                                "Seçilen kargo firması veritabanında bulunamadı.",
                                close_dialog=False,
                            )
                        provider_platform = str(getattr(provider_row, "platformCode", "") or "").strip().upper()
                        if account_platform and provider_platform and provider_platform != account_platform:
                            return Result.fail(
                                "Seçilen kargo firması bu ilana ait platformla uyuşmuyor.",
                                close_dialog=False,
                            )
                    desired_payload = {
                        "cost_item_id": cost_item_id_map.get(normalized_key),
                        "cargo_provider_id": cargo_provider_id,
                        "cost_key": cost_key,
                        "source_type": str(it.get("source_type") or "").strip() or None,
                        "source_config": source_config,
                        "resolved_amount": None,
                        "resolved_net_amount": None,
                        "resolved_vat_amount": None,
                        "currency": "TRY",
                        "note": None,
                        "resolution_meta": None,
                    }
                    current_row = current_snapshot_by_key.get(normalized_key)
                    if current_row is not None and not _snapshot_removed(current_row) and _snapshot_row_binding_matches_payload(current_row, desired_payload):
                        continue
                    session.add(
                        ListingProductCostSnapshot(
                            status=SNAPSHOT_STATUS_APPEND if current_row is None or _snapshot_removed(current_row) else SNAPSHOT_STATUS_SET,
                            cost_item_id=cost_item_id_map.get(normalized_key),
                            cargo_provider_id=cargo_provider_id,
                            listing_id=int(resolved_listing_id),
                            cost_key=cost_key,
                            source_type=str(it.get("source_type") or "") or None,
                            source_config=source_config,
                            created_at=batch_now,
                            updated_at=batch_now,
                        )
                    )
                    changed = True
                removed_cost_keys = set(current_snapshot_by_key.keys()) - requested_cost_keys
                for normalized_key in sorted(removed_cost_keys):
                    snapshot_row = current_snapshot_by_key.get(normalized_key)
                    if snapshot_row is None:
                        continue
                    if _snapshot_removed(snapshot_row):
                        continue
                    cost_key = str(getattr(snapshot_row, "cost_key", "") or "").strip()
                    if not cost_key:
                        continue
                    session.add(
                        ListingProductCostSnapshot(
                            status=SNAPSHOT_STATUS_REMOVE,
                            cost_item_id=_safe_int_id(getattr(snapshot_row, "cost_item_id", None)),
                            cargo_provider_id=_safe_int_id(getattr(snapshot_row, "cargo_provider_id", None)),
                            listing_id=int(resolved_listing_id),
                            cost_key=cost_key,
                            source_type=str(getattr(snapshot_row, "source_type", "") or "").strip() or None,
                            source_config=dict(getattr(snapshot_row, "source_config", None) or {}) or None,
                            resolved_amount=_optional_float(getattr(snapshot_row, "resolved_amount", None)),
                            resolved_net_amount=_optional_float(getattr(snapshot_row, "resolved_net_amount", None)),
                            resolved_vat_amount=_optional_float(getattr(snapshot_row, "resolved_vat_amount", None)),
                            currency=str(getattr(snapshot_row, "currency", "") or "TRY").strip() or "TRY",
                            note=str(getattr(snapshot_row, "note", "") or "").strip() or None,
                            resolution_meta=_clean_snapshot_resolution_meta(getattr(snapshot_row, "resolution_meta", None)),
                            created_at=batch_now,
                            updated_at=batch_now,
                        )
                    )
                    changed = True

        if changed:
            update_records(
                ListingProduct,
                filters={"api_account_id": int(api_account_id), "product_id": str(product_id)},
                update_data={"updated_at": _utcnow_naive()},
                db_name=db_name,
            )
            _emit_listing_signal(
                "cost_matches_changed",
                {
                    "api_account_id": int(api_account_id),
                    "product_id": str(product_id),
                    "match_count": len(normalized),
                    "cost_keys": [str(it.get("cost_key") or "") for it in normalized if str(it.get("cost_key") or "")],
                },
            )
            return Result.ok("Maliyet eşleşmesi güncellendi.", close_dialog=False)
        return Result.ok("Maliyet eşleşmesi zaten güncel.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def update_listing_price_inventory_cache(
    *,
    api_account_id: int,
    product_id: str,
    quantity: Optional[float],
    list_price: Optional[float],
    sale_price: Optional[float],
    db_name: str = DB_NAME,
) -> Result:
    try:
        update_records(
            ListingProduct,
            filters={"api_account_id": int(api_account_id), "product_id": str(product_id)},
            update_data={
                "quantity": quantity,
                "list_price": list_price,
                "sale_price": sale_price,
                "updated_at": _utcnow_naive(),
            },
            db_name=db_name,
        )
        _emit_listing_signal(
            "listing_cache_updated",
            {
                "api_account_id": int(api_account_id),
                "product_id": str(product_id),
                "quantity": quantity,
                "list_price": list_price,
                "sale_price": sale_price,
            },
        )
        return Result.ok("Cache güncellendi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
