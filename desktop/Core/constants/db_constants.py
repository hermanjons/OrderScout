from __future__ import annotations


DEFAULT_SQLITE_SAFE_MAX_VARIABLES = 900

SOURCE_TYPE_BUILTIN = "builtin"
SOURCE_TYPE_USER = "user"
SOURCE_TYPE_API = "api"
SOURCE_TYPES = {
    SOURCE_TYPE_BUILTIN,
    SOURCE_TYPE_USER,
    SOURCE_TYPE_API,
}

SOURCE_IDENTITY_TABLES: tuple[str, ...] = (
    "apiaccount",
    "ai_model_artifact",
    "ai_provider_account",
    "brand",
    "cargo_tariff",
    "company",
    "cost_item",
    "cost_item_marketplace_link",
    "finance_invoice_document",
    "finance_manual_transaction",
    "logistics_cargo_provider",
    "marketplace",
    "stock_item",
    "stock_item_snapshot",
    "stock_tx",
    "trendyol_finance_cargo_invoice_item",
    "trendyol_finance_transaction",
    "trendyol_listing_product",
    "trendyol_listing_product_history",
    "trendyol_order_data",
    "trendyol_order_header",
    "trendyol_order_item",
    "trendyol_return_claim",
    "warehouse",
    "cost_item_snapshot",
)

SOURCE_IDENTITY_PK_COLUMNS: dict[str, str] = {
    table_name: "pk"
    for table_name in SOURCE_IDENTITY_TABLES
}

SOURCE_IDENTITY_COLUMNS = {
    "sourceType": "TEXT",
    "sourceId": "INTEGER",
}

SOURCE_IDENTITY_BACKFILL_KEYS: dict[str, tuple[str, ...]] = {
    "apiaccount": ("platform", "account_id", "seller_id"),
    "ai_model_artifact": ("repo_id", "filename"),
    "ai_provider_account": ("provider_code", "label"),
    "brand": ("code", "name"),
    "cargo_tariff": ("platform", "tariffKey"),
    "company": ("tax_no", "name"),
    "cost_item": ("costKey",),
    "cost_item_marketplace_link": ("cost_item_id", "marketplace_id"),
    "finance_invoice_document": ("invoiceNumber", "filePath"),
    "finance_manual_transaction": ("transactionDate", "direction", "categoryKey", "amount", "referenceNo"),
    "license_action_log": ("provider", "device_id", "action", "created_at"),
    "license_state": ("provider", "device_id"),
    "logistics_cargo_provider": ("platformCode", "cargoProviderCode"),
    "marketplace": ("code",),
    "stock_item": ("sku",),
    "stock_item_snapshot": ("listing_id", "stock_item_id", "created_at"),
    "stock_tx": ("reference_type", "reference_id", "item_id", "warehouse_id", "occurred_at", "created_at"),
    "trendyol_finance_cargo_invoice_item": (
        "api_account_id",
        "invoiceSerialNumber",
        "parcelUniqueId",
        "shipmentPackageType",
    ),
    "trendyol_finance_transaction": ("api_account_id", "serviceKey", "recordId", "transactionDate"),
    "trendyol_listing_product": ("api_account_id", "product_id"),
    "trendyol_listing_product_history": ("api_account_id", "product_id", "created_at"),
    "trendyol_order_data": ("api_account_id", "id", "lastModifiedDate"),
    "trendyol_order_header": ("api_account_id", "orderNumber"),
    "trendyol_order_item": ("api_account_id", "order_data_id", "order_data_pk", "snapshotLastModifiedDate", "lineId"),
    "trendyol_return_claim": ("api_account_id", "claimId", "lastModifiedDate"),
    "warehouse": ("code", "name"),
    "cost_item_snapshot": ("listing_id", "cost_key", "created_at"),
}

# Includes retired tables solely for compatibility with existing databases.
SOURCE_IDENTITY_PK_RENAME_TABLES = (
    "ai_model_artifact",
    "ai_provider_account",
    "brand",
    "company",
    "cost_item_snapshot",
    "finance_invoice_document",
    "finance_manual_transaction",
    "license_action_log",
    "license_state",
    "stock_item",
    "stock_item_snapshot",
    "stock_tx",
    "trendyol_listing_product",
    "trendyol_listing_product_history",
    "warehouse",
)

SYNC_READY_EXTRA_COLUMNS: dict[str, str] = {}

__all__ = [
    "DEFAULT_SQLITE_SAFE_MAX_VARIABLES",
    "SOURCE_IDENTITY_BACKFILL_KEYS",
    "SOURCE_IDENTITY_COLUMNS",
    "SOURCE_IDENTITY_PK_COLUMNS",
    "SOURCE_IDENTITY_PK_RENAME_TABLES",
    "SOURCE_IDENTITY_TABLES",
    "SOURCE_TYPE_API",
    "SOURCE_TYPE_BUILTIN",
    "SOURCE_TYPE_USER",
    "SOURCE_TYPES",
    "SYNC_READY_EXTRA_COLUMNS",
]
