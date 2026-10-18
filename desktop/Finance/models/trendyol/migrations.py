from __future__ import annotations

from Core.db.migration_builders import (
    build_drop_table_migration,
    build_promote_table_migration,
)
from Finance.models.trendyol.models import FinanceCargoInvoiceItem, FinanceCostItem, FinanceTransaction


MIGRATIONS = [
    build_promote_table_migration(
        migration_id="finance_trendyol_0001_rehome_cost_item",
        domain="finance",
        description="Promote legacy financecostitem table to cost_item.",
        old_table_name="financecostitem",
        new_table_name=FinanceCostItem.__table__.name,
        indexes_sql=[
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_cost_item_costkey ON cost_item(costKey)",
            "CREATE INDEX IF NOT EXISTS ix_cost_item_active_updated ON cost_item(isActive, updatedAt)",
            "CREATE INDEX IF NOT EXISTS ix_cost_item_deleted_updated ON cost_item(isDeleted, updatedAt)",
        ],
    ),
    build_drop_table_migration(
        migration_id="finance_trendyol_0002_drop_legacy_finance_profit_method_table",
        domain="finance",
        description="Drop deprecated financeprofitmethod table.",
        table_name="financeprofitmethod",
    ),
    build_drop_table_migration(
        migration_id="finance_trendyol_0003_drop_cost_item_platform_links",
        domain="finance",
        description="Drop deprecated cost_item_platform_link table. supportedPlatformsJson is the source of truth.",
        table_name="cost_item_platform_link",
    ),
    build_promote_table_migration(
        migration_id="finance_trendyol_0004_rehome_finance_transaction",
        domain="finance",
        description="Promote legacy financetransaction table to trendyol_finance_transaction.",
        old_table_name="financetransaction",
        new_table_name=FinanceTransaction.__table__.name,
        indexes_sql=[
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_financetransaction_service_account_record_date ON trendyol_finance_transaction(serviceKey, api_account_id, recordId, transactionDate)",
            "CREATE INDEX IF NOT EXISTS ix_financetransaction_orderno_date ON trendyol_finance_transaction(orderNumber, transactionDate)",
            "CREATE INDEX IF NOT EXISTS ix_financetransaction_serial_date ON trendyol_finance_transaction(commissionInvoiceSerialNumber, transactionDate)",
            "CREATE INDEX IF NOT EXISTS ix_financetransaction_service_type_date ON trendyol_finance_transaction(serviceKey, transactionType, transactionDate)",
        ],
    ),
    build_promote_table_migration(
        migration_id="finance_trendyol_0005_rehome_finance_cargo_invoice_item",
        domain="finance",
        description="Promote legacy financecargoinvoiceitem table to trendyol_finance_cargo_invoice_item.",
        old_table_name="financecargoinvoiceitem",
        new_table_name=FinanceCargoInvoiceItem.__table__.name,
        indexes_sql=[
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_financecargoitem_account_invoice_parcel_type ON trendyol_finance_cargo_invoice_item(api_account_id, invoiceSerialNumber, parcelUniqueId, shipmentPackageType)",
            "CREATE INDEX IF NOT EXISTS ix_financecargoitem_invoice_orderno ON trendyol_finance_cargo_invoice_item(invoiceSerialNumber, orderNumber)",
        ],
    ),
]
