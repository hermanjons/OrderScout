from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Optional

from sqlmodel import Field

from Core.constants.db_constants import (
    SOURCE_IDENTITY_PK_COLUMNS,
    SOURCE_IDENTITY_TABLES,
    SOURCE_TYPE_API,
    SOURCE_TYPE_BUILTIN,
    SOURCE_TYPE_USER,
    SOURCE_TYPES,
)

_BUILTIN_SOURCE_IDENTITY_TABLES = {"marketplace"}
_API_SOURCE_IDENTITY_TABLES = {
    "trendyol_finance_cargo_invoice_item",
    "trendyol_finance_transaction",
    "trendyol_listing_product",
    "trendyol_listing_product_history",
    "trendyol_order_data",
    "trendyol_order_header",
    "trendyol_order_item",
    "trendyol_return_claim",
}
_USER_SOURCE_IDENTITY_TABLES = {
    "apiaccount",
    "ai_model_artifact",
    "ai_provider_account",
    "brand",
    "company",
    "finance_invoice_document",
    "finance_manual_transaction",
    "license_action_log",
    "license_state",
    "stock_item",
    "stock_item_snapshot",
    "stock_tx",
    "warehouse",
    "cost_item_snapshot",
}
_SOURCE_ID_BUILDERS = {
    "apiaccount": lambda payload: f"api-account|{_row_value(payload, 'platform')}|{_row_value(payload, 'account_id', 'seller_id')}",
    "ai_model_artifact": lambda payload: f"ai-model|{_row_value(payload, 'repo_id')}|{_row_value(payload, 'filename')}",
    "ai_provider_account": lambda payload: f"ai-provider|{_row_value(payload, 'provider_code')}|{_row_value(payload, 'label')}",
    "brand": lambda payload: f"brand|{_row_value(payload, 'code', 'name')}",
    "cargo_tariff": lambda payload: f"cargo-tariff|{_row_value(payload, 'platform')}|{_row_value(payload, 'tariffKey')}",
    "company": lambda payload: f"company|{_row_value(payload, 'tax_no', 'name')}",
    "cost_item": lambda payload: f"cost-item|{_row_value(payload, 'costKey')}",
    "cost_item_marketplace_link": lambda payload: (
        f"cost-item-marketplace-link|{_row_value(payload, 'cost_item_id')}|{_row_value(payload, 'marketplace_id')}"
    ),
    "finance_invoice_document": lambda payload: (
        f"finance-invoice-document|{_row_value(payload, 'invoiceNumber')}|{_row_value(payload, 'filePath')}"
    ),
    "finance_manual_transaction": lambda payload: (
        f"finance-manual-transaction|{_row_value(payload, 'transactionDate')}|"
        f"{_row_value(payload, 'direction')}|{_row_value(payload, 'categoryKey')}|"
        f"{_row_value(payload, 'amount')}|{_row_value(payload, 'referenceNo', 'sync_uuid')}"
    ),
    "license_action_log": lambda payload: (
        f"license-action|{_row_value(payload, 'provider')}|{_row_value(payload, 'device_id')}|"
        f"{_row_value(payload, 'action')}|{_row_value(payload, 'created_at')}"
    ),
    "license_state": lambda payload: f"license-state|{_row_value(payload, 'provider')}|{_row_value(payload, 'device_id')}",
    "logistics_cargo_provider": lambda payload: (
        f"cargo-provider|{_row_value(payload, 'platformCode')}|{_row_value(payload, 'cargoProviderCode')}"
    ),
    "marketplace": lambda payload: f"marketplace|{_row_value(payload, 'code')}",
    "stock_item": lambda payload: f"stock-item|{_row_value(payload, 'sku')}",
    "stock_item_snapshot": lambda payload: (
        f"listing-stock-snapshot|{_row_value(payload, 'listing_id')}|"
        f"{_row_value(payload, 'stock_item_id')}|{_row_value(payload, 'created_at')}"
    ),
    "stock_tx": lambda payload: (
        f"stock-tx|{_row_value(payload, 'reference_type')}|{_row_value(payload, 'reference_id')}|"
        f"{_row_value(payload, 'item_id')}|{_row_value(payload, 'warehouse_id')}|"
        f"{_row_value(payload, 'occurred_at', 'created_at')}"
    ),
    "trendyol_finance_cargo_invoice_item": lambda payload: (
        f"finance-cargo-item|{_row_value(payload, 'api_account_id')}|{_row_value(payload, 'invoiceSerialNumber')}|"
        f"{_row_value(payload, 'parcelUniqueId')}|{_row_value(payload, 'shipmentPackageType')}"
    ),
    "trendyol_finance_transaction": lambda payload: (
        f"finance-transaction|{_row_value(payload, 'api_account_id')}|{_row_value(payload, 'serviceKey')}|"
        f"{_row_value(payload, 'recordId')}|{_row_value(payload, 'transactionDate')}"
    ),
    "trendyol_listing_product": lambda payload: (
        f"listing-product|{_row_value(payload, 'api_account_id')}|{_row_value(payload, 'product_id')}"
    ),
    "trendyol_listing_product_history": lambda payload: (
        f"listing-product-history|{_row_value(payload, 'api_account_id')}|{_row_value(payload, 'product_id')}|"
        f"{_row_value(payload, 'created_at', 'pk')}"
    ),
    "trendyol_order_data": lambda payload: (
        f"order-data|{_row_value(payload, 'api_account_id')}|{_row_value(payload, 'id')}|"
        f"{_row_value(payload, 'lastModifiedDate')}"
    ),
    "trendyol_order_header": lambda payload: (
        f"order-header|{_row_value(payload, 'api_account_id')}|{_row_value(payload, 'orderNumber')}"
    ),
    "trendyol_order_item": lambda payload: (
        f"order-item|{_row_value(payload, 'api_account_id')}|{_row_value(payload, 'order_data_id', 'order_data_pk')}|"
        f"{_row_value(payload, 'snapshotLastModifiedDate')}|{_row_value(payload, 'lineId')}"
    ),
    "trendyol_return_claim": lambda payload: (
        f"return-claim|{_row_value(payload, 'api_account_id')}|{_row_value(payload, 'claimId')}|"
        f"{_row_value(payload, 'lastModifiedDate')}"
    ),
    "warehouse": lambda payload: f"warehouse|{_row_value(payload, 'code', 'name')}",
    "cost_item_snapshot": lambda payload: (
        f"listing-cost-snapshot|{_row_value(payload, 'listing_id')}|{_row_value(payload, 'cost_key')}|"
        f"{_row_value(payload, 'created_at', 'pk')}"
    ),
}
_SOURCE_IDENTITY_MODEL_META: dict[Any, tuple[str, frozenset[str], bool, bool, str, Any]] = {}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed


def coerce_source_id(value: Any) -> int | None:
    parsed = _safe_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _stable_positive_int(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    raw = int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF
    return raw or 1


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _hash_payload(row: dict[str, Any]) -> int:
    encoded = json.dumps(dict(row or {}), ensure_ascii=False, sort_keys=True, default=str)
    return _stable_positive_int(encoded)


def _fallback_source_id(table_name: str, row: dict[str, Any]) -> int:
    explicit_sync_uuid = _compact_text(_row_value(row, "sync_uuid"))
    if explicit_sync_uuid:
        return _stable_positive_int(f"{table_name}:sync:{explicit_sync_uuid}")
    pk_name = SOURCE_IDENTITY_PK_COLUMNS.get(table_name)
    if pk_name:
        pk_value = coerce_source_id(_row_value(row, pk_name))
        if pk_value is not None:
            return pk_value
    return _stable_positive_int(f"{table_name}:row:{_hash_payload(row)}")


def _default_source_type_for_table(table_name: str) -> str:
    if table_name in _BUILTIN_SOURCE_IDENTITY_TABLES:
        return SOURCE_TYPE_BUILTIN
    if table_name in _API_SOURCE_IDENTITY_TABLES:
        return SOURCE_TYPE_API
    if table_name in _USER_SOURCE_IDENTITY_TABLES:
        return SOURCE_TYPE_USER
    return SOURCE_TYPE_USER


def infer_source_type(table_name: str, row: dict[str, Any]) -> str:
    explicit = _compact_text(_row_value(row, "sourceType", "source_type")).lower()
    if explicit in SOURCE_TYPES:
        return explicit
    if bool(_row_value(row, "isBuiltin")):
        return SOURCE_TYPE_BUILTIN
    return _default_source_type_for_table(table_name)


def _infer_source_type_from_default(default_source_type: str, row: dict[str, Any]) -> str:
    explicit = str(row.get("sourceType") or row.get("source_type") or "").strip().lower()
    if explicit in SOURCE_TYPES:
        return explicit
    if bool(row.get("isBuiltin")):
        return SOURCE_TYPE_BUILTIN
    return default_source_type


def build_source_id(table_name: str, row: dict[str, Any], *, source_type: str) -> int:
    explicit_source_id = coerce_source_id(_row_value(row, "sourceId", "source_id"))
    if explicit_source_id is not None:
        return explicit_source_id

    builder = _SOURCE_ID_BUILDERS.get(table_name)
    return _build_generated_source_id(table_name, row, source_type=source_type, builder=builder)


def _build_generated_source_id(
    table_name: str,
    row: dict[str, Any],
    *,
    source_type: str,
    builder: Any = None,
) -> int:
    if table_name == "brand":
        seed = f"brand|{_row_value(row, 'code', 'name')}"
    else:
        builder = builder if builder is not None else _SOURCE_ID_BUILDERS.get(table_name)
        seed = builder(row or {}) if builder is not None else ""
    seed = _compact_text(seed)
    if seed:
        return _stable_positive_int(seed)
    if source_type == SOURCE_TYPE_USER:
        return _fallback_source_id(table_name, row)
    return _fallback_source_id(table_name, row)


def _source_identity_model_meta(model: Any) -> tuple[str, frozenset[str], bool, bool, str, Any]:
    cached = _SOURCE_IDENTITY_MODEL_META.get(model)
    if cached is not None:
        return cached
    table = getattr(model, "__table__", None)
    table_name = str(getattr(table, "name", "") or "").strip()
    column_names = frozenset(str(column.name) for column in getattr(table, "columns", ()))
    cached = (
        table_name,
        column_names,
        "sourceType" in column_names,
        "sourceId" in column_names,
        _default_source_type_for_table(table_name) if table_name else SOURCE_TYPE_USER,
        _SOURCE_ID_BUILDERS.get(table_name),
    )
    _SOURCE_IDENTITY_MODEL_META[model] = cached
    return cached


def ensure_source_identity_inplace(model: Any, row: dict[str, Any]) -> dict[str, Any]:
    payload = row if isinstance(row, dict) else dict(row or {})
    table_name, column_names, has_source_type, has_source_id, default_source_type, source_id_builder = _source_identity_model_meta(model)
    if not table_name:
        return payload
    if not has_source_type:
        return payload

    source_type = _infer_source_type_from_default(default_source_type, payload)
    payload["sourceType"] = source_type
    if has_source_id and coerce_source_id(payload.get("sourceId")) is None:
        payload["sourceId"] = _build_generated_source_id(
            table_name,
            payload,
            source_type=source_type,
            builder=source_id_builder,
        )
    return payload


def ensure_source_identity(model: Any, row: dict[str, Any]) -> dict[str, Any]:
    return ensure_source_identity_inplace(model, dict(row or {}))


def backfill_source_identity_row(table_name: str, row: dict[str, Any]) -> tuple[str, int]:
    normalized_table = str(table_name or "").strip()
    payload = dict(row or {})
    source_type = infer_source_type(normalized_table, payload)
    source_id = coerce_source_id(_row_value(payload, "sourceId", "source_id"))
    if source_id is None:
        source_id = build_source_id(normalized_table, payload, source_type=source_type)
    return source_type, source_id


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditMixin:
    created_at: datetime = Field(default_factory=_utcnow_naive)
    updated_at: datetime = Field(default_factory=_utcnow_naive)


class SyncStateMixin:
    sync_uuid: Optional[str] = Field(default=None, index=True, max_length=64)
    sync_version: int = Field(default=1)
    sync_updated_at: Optional[str] = Field(default=None, index=True, max_length=64)
    sync_deleted_at: Optional[str] = Field(default=None, max_length=64)
    sync_source_device: Optional[str] = Field(default=None, max_length=128)


class SourceIdentityMixin(AuditMixin, SyncStateMixin):
    sourceType: Optional[str] = Field(default=None, index=True, nullable=False, max_length=32)
    sourceId: Optional[int] = Field(default=None, index=True, nullable=False)

    @property
    def source_id(self) -> Optional[int]:
        return getattr(self, "sourceId", None)

    @source_id.setter
    def source_id(self, value: Optional[int]) -> None:
        object.__setattr__(self, "sourceId", coerce_source_id(value))

    def __getattr__(self, name: str) -> Any:
        if name == "source_type":
            return getattr(self, "sourceType", None)
        raise AttributeError(name)

    def model_post_init(self, __context: Any) -> None:
        try:
            table = getattr(self, "__table__", None)
            columns = tuple(getattr(table, "columns", ()) or ())
            payload = {str(column.name): getattr(self, str(column.name), None) for column in columns}
            fixed = ensure_source_identity(self.__class__, payload)
            for key in ("sourceType", "sourceId"):
                if key in fixed and getattr(self, key, None) != fixed.get(key):
                    object.__setattr__(self, key, fixed.get(key))
        except Exception:
            return
