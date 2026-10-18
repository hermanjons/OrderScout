from __future__ import annotations

from Core.db.migration_builders import (
    build_backfill_migration,
    build_copy_columns_migration,
    build_stock_tx_legacy_cost_defaults_migration,
)
from Core.db.migration_ops import add_column_if_missing, table_columns, table_exists
from Orders.models.trendyol.models import OrderHeader  # noqa: F401
from Stock.models.models import StockItem
def _create_stock_tx_hot_path_indexes(conn) -> None:
    if table_exists(conn, "warehouse"):
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_warehouse_code ON warehouse(code)"
        )
    if not table_exists(conn, "stock_tx"):
        return

    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_stock_tx_item_time ON stock_tx(item_id, occurred_at, created_at, pk)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_stock_tx_warehouse_time ON stock_tx(warehouse_id, occurred_at, created_at, pk)"
    )


def _backfill_stock_item_brand_ids(conn) -> None:
    conn.exec_driver_sql(
        """
        UPDATE stock_item
           SET brand_id = (
               SELECT brand.pk
                 FROM brand
                WHERE lower(trim(brand.name)) = lower(trim(stock_item.brand))
                LIMIT 1
           )
         WHERE brand_id IS NULL
           AND trim(COALESCE(brand, '')) <> ''
           AND EXISTS (
               SELECT 1
                 FROM brand
                WHERE lower(trim(brand.name)) = lower(trim(stock_item.brand))
           )
        """
    )


def _backfill_stock_tx_company_ids(conn) -> None:
    conn.exec_driver_sql(
        """
        UPDATE stock_tx
           SET company_id = (
               SELECT company.pk
                 FROM company
                WHERE lower(trim(company.name)) = lower(trim(stock_tx.counterparty))
                LIMIT 1
           )
         WHERE company_id IS NULL
           AND trim(COALESCE(counterparty, '')) <> ''
           AND EXISTS (
               SELECT 1
                 FROM company
                WHERE lower(trim(company.name)) = lower(trim(stock_tx.counterparty))
           )
        """
    )


MIGRATIONS = [
    build_copy_columns_migration(
        migration_id="stock_0001_stock_item_custom_label",
        domain="stock",
        description="Copy stock_item.custom_tag values into custom_label.",
        table_name=StockItem.__table__.name,
        replacements={
            "custom_label": ("custom_label", "custom_tag"),
        },
        column_defs={
            "custom_label": "TEXT",
        },
        copy_when_blank=["custom_label"],
    ),
    build_backfill_migration(
        migration_id="stock_0002_create_hot_path_indexes",
        domain="stock",
        description="Create composite indexes for stock journal hot paths.",
        should_run=lambda conn: any(
            table_exists(conn, table_name)
            for table_name in (
                "warehouse",
                "stock_tx",
            )
        ),
        apply_sql=_create_stock_tx_hot_path_indexes,
    ),
    build_backfill_migration(
        migration_id="stock_0003_add_stock_tx_order_header_fk",
        domain="stock",
        description="Rebuild stock_tx to add optional order header foreign key.",
        should_run=lambda conn: table_exists(conn, "stock_tx")
        and (
            "order_header_id" not in table_columns(conn, "stock_tx")
        ),
        apply_sql=lambda conn: add_column_if_missing(
            conn,
            table_name="stock_tx",
            column_name="order_header_id",
            column_sql="INTEGER",
        ),
    ),
    build_backfill_migration(
        migration_id="stock_0004_add_stock_item_brand_fk",
        domain="stock",
        description="Add stock_item.brand_id column for brand relation.",
        should_run=lambda conn: table_exists(conn, StockItem.__table__.name)
        and "brand_id" not in table_columns(conn, StockItem.__table__.name),
        apply_sql=lambda conn: add_column_if_missing(
            conn,
            table_name=StockItem.__table__.name,
            column_name="brand_id",
            column_sql="INTEGER",
        ),
    ),
    build_backfill_migration(
        migration_id="stock_0005_add_stock_tx_company_fk",
        domain="stock",
        description="Add stock_tx.company_id column for company relation.",
        should_run=lambda conn: table_exists(conn, "stock_tx")
        and "company_id" not in table_columns(conn, "stock_tx"),
        apply_sql=lambda conn: add_column_if_missing(
            conn,
            table_name="stock_tx",
            column_name="company_id",
            column_sql="INTEGER",
        ),
    ),
    build_backfill_migration(
        migration_id="stock_0006_backfill_stock_item_brand_ids",
        domain="stock",
        description="Backfill stock_item.brand_id from legacy brand names.",
        should_run=lambda conn: (
            table_exists(conn, "stock_item")
            and table_exists(conn, "brand")
            and "brand_id" in table_columns(conn, "stock_item")
            and "brand" in table_columns(conn, "stock_item")
            and bool(
                conn.exec_driver_sql(
                    """
                    SELECT 1
                    FROM stock_item
                    WHERE brand_id IS NULL
                      AND trim(COALESCE(brand, '')) <> ''
                    LIMIT 1
                    """
                ).fetchone()
            )
        ),
        apply_sql=_backfill_stock_item_brand_ids,
    ),
    build_backfill_migration(
        migration_id="stock_0007_backfill_stock_tx_company_ids",
        domain="stock",
        description="Backfill stock_tx.company_id from legacy counterparty names.",
        should_run=lambda conn: (
            table_exists(conn, "stock_tx")
            and table_exists(conn, "company")
            and "company_id" in table_columns(conn, "stock_tx")
            and "counterparty" in table_columns(conn, "stock_tx")
            and bool(
                conn.exec_driver_sql(
                    """
                    SELECT 1
                    FROM stock_tx
                    WHERE company_id IS NULL
                      AND trim(COALESCE(counterparty, '')) <> ''
                    LIMIT 1
                    """
                ).fetchone()
            )
        ),
        apply_sql=_backfill_stock_tx_company_ids,
    ),
    build_stock_tx_legacy_cost_defaults_migration(
        migration_id="stock_0008_backfill_stock_tx_legacy_cost_defaults",
        domain="stock",
        description="Backfill legacy stock_tx cost mode and VAT defaults.",
    ),
]

