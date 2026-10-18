from __future__ import annotations

from Account.models.models import ApiAccount  # noqa: F401
from Finance.models.trendyol.models import FinanceCostItem  # noqa: F401
from Logistics.models.models import LogisticsCargoProvider  # noqa: F401
from Stock.models.models import StockItem  # noqa: F401
from Core.db.migration_builders import (
    SYNC_READY_EXTRA_COLUMNS,
    build_append_rows_migration,
    build_create_table_with_extra_columns_sql,
    build_backfill_migration,
    build_listing_cost_snapshot_tariff_meta_migration,
    build_listing_cost_snapshot_compaction_migration,
    build_model_rebuild_migration,
    build_rehome_table_migration,
    build_target_columns,
    make_listing_cost_binding_snapshot_row_mapper,
    make_listing_stock_binding_snapshot_row_mapper,
    make_listing_snapshot_row_mapper,
    make_foreign_key_validator,
    make_row_mapper,
    table_has_foreign_key,
    table_has_index,
)
from Core.db.migration_ops import drop_table_if_exists, table_columns, table_exists
from Listing.models.models import (
    ListingProduct,
    ListingProductCostSnapshot,
    ListingProductHistory,
    ListingProductStockSnapshot,
)


MIGRATIONS = [
    build_rehome_table_migration(
        migration_id="listing_trendyol_0001_rehome_listing_product",
        domain="listing",
        description="Move legacy listing_product rows into trendyol_listing_product.",
        old_table_name="listing_product",
        new_table_name=ListingProduct.__table__.name,
        model=ListingProduct,
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["product_id"],
        drop_old=False,
        defaults={
            "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
        },
    ),
    build_append_rows_migration(
        migration_id="listing_trendyol_0002_rehome_listing_product_item",
        domain="listing",
        description="Move legacy listing_product_item rows into stock_item_snapshot.",
        old_table_name="listing_product_item",
        new_table_name=ListingProductStockSnapshot.__table__.name,
        model=ListingProductStockSnapshot,
        row_mapper_factory=lambda conn: make_listing_stock_binding_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductStockSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=[],
    ),
    build_append_rows_migration(
        migration_id="listing_trendyol_0003_append_listing_product_cost_item_into_snapshots",
        domain="listing",
        description="Move legacy listing_product_cost_item rows into cost_item_snapshot.",
        old_table_name="listing_product_cost_item",
        new_table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        row_mapper_factory=lambda conn: make_listing_cost_binding_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["cost_key"],
    ),
    build_append_rows_migration(
        migration_id="listing_trendyol_0004_rehome_listing_product_cost_snapshot",
        domain="listing",
        description="Move legacy listing_product_cost_snapshot rows into cost_item_snapshot.",
        old_table_name="listing_product_cost_snapshot",
        new_table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        row_mapper_factory=lambda conn: make_listing_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["cost_key"],
        drop_old=False,
    ),
    build_rehome_table_migration(
        migration_id="listing_trendyol_0005_rehome_listing_product_history",
        domain="listing",
        description="Move legacy listing_product_history rows into trendyol_listing_product_history.",
        old_table_name="listing_product_history",
        new_table_name=ListingProductHistory.__table__.name,
        model=ListingProductHistory,
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["product_id"],
        drop_old=False,
        defaults={
            "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
        },
    ),
    build_backfill_migration(
        migration_id="listing_trendyol_0006_drop_legacy_tables",
        domain="listing",
        description="Drop legacy generic listing tables after Trendyol rehome completes.",
        should_run=lambda conn: any(
            table_exists(conn, table_name)
            for table_name in (
                "listing_product",
                "listing_product_item",
                "listing_product_cost_snapshot",
                "listing_product_history",
            )
        ),
        apply_sql=lambda conn: [
            drop_table_if_exists(conn, table_name)
            for table_name in (
                "listing_product",
                "listing_product_item",
                "listing_product_cost_snapshot",
                "listing_product_history",
            )
        ],
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0007_add_listing_product_account_fk",
        domain="listing",
        description="Rebuild trendyol_listing_product to enforce apiaccount foreign key.",
        table_name=ListingProduct.__table__.name,
        model=ListingProduct,
        should_run=lambda conn: table_exists(conn, ListingProduct.__table__.name)
        and not table_has_foreign_key(
            conn,
            table_name=ListingProduct.__table__.name,
            from_column="api_account_id",
            target_table="apiaccount",
            target_column="pk",
        ),
        row_mapper=make_row_mapper(
            target_columns=build_target_columns(model=ListingProduct, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProduct,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
            excluded_foreign_keys=[("stock_item_id", "stock_item", "pk")],
        ),
        target_columns=build_target_columns(model=ListingProduct, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProduct.__table__.name,
                from_column="api_account_id",
                target_table="apiaccount",
                target_column="pk",
            )
        ],
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0008_add_listing_product_stock_item_fk",
        domain="listing",
        description="Rebuild trendyol_listing_product to enforce stock_item foreign key.",
        table_name=ListingProduct.__table__.name,
        model=ListingProduct,
        should_run=lambda conn: table_exists(conn, ListingProduct.__table__.name)
        and not table_has_foreign_key(
            conn,
            table_name=ListingProduct.__table__.name,
            from_column="stock_item_id",
            target_table="stock_item",
            target_column="pk",
        ),
        row_mapper=make_row_mapper(
            target_columns=build_target_columns(model=ListingProduct, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProduct,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
        ),
        target_columns=build_target_columns(model=ListingProduct, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProduct.__table__.name,
                from_column="stock_item_id",
                target_table="stock_item",
                target_column="pk",
            )
        ],
    ),
    build_append_rows_migration(
        migration_id="listing_trendyol_0009_rehome_trendyol_cost_snapshot",
        domain="listing",
        description="Move trendyol_listing_product_cost_snapshot rows into cost_item_snapshot.",
        old_table_name="trendyol_listing_product_cost_snapshot",
        new_table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        row_mapper_factory=lambda conn: make_listing_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["cost_key"],
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0010_add_cost_item_snapshot_cost_item_fk",
        domain="listing",
        description="Rebuild cost_item_snapshot to enforce cost_item foreign key.",
        table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        should_run=lambda conn: table_exists(conn, ListingProductCostSnapshot.__table__.name)
        and (
            "listing_id" not in table_columns(conn, ListingProductCostSnapshot.__table__.name)
            or "api_account_id" in table_columns(conn, ListingProductCostSnapshot.__table__.name)
            or "product_id" in table_columns(conn, ListingProductCostSnapshot.__table__.name)
            or not table_has_foreign_key(
                conn,
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cost_item_id",
                target_table="cost_item",
                target_column="pk",
            )
        ),
        row_mapper=make_row_mapper(target_columns=[]),
        row_mapper_factory=lambda conn: make_listing_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProductCostSnapshot,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
        ),
        target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cost_item_id",
                target_table="cost_item",
                target_column="pk",
            ),
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            ),
        ],
    ),
    build_backfill_migration(
        migration_id="listing_trendyol_0011_backfill_cost_item_snapshot_cost_item_ids",
        domain="listing",
        description="Backfill cost_item_snapshot.cost_item_id from cost_item.costKey matches.",
        should_run=lambda conn: table_exists(conn, ListingProductCostSnapshot.__table__.name)
        and table_exists(conn, FinanceCostItem.__table__.name),
        apply_sql=lambda conn: conn.exec_driver_sql(
            """
            UPDATE cost_item_snapshot
            SET cost_item_id = (
                SELECT cost_item.pk
                FROM cost_item
                WHERE lower(trim(cost_item.costKey)) = lower(trim(cost_item_snapshot.cost_key))
                LIMIT 1
            )
            WHERE cost_item_id IS NULL
            """
        ),
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0012_rebuild_cost_item_snapshot_listing_root",
        domain="listing",
        description="Rebuild cost_item_snapshot to use listing_id instead of api_account_id/product_id.",
        table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        should_run=lambda conn: table_exists(conn, ListingProductCostSnapshot.__table__.name)
        and (
            "listing_id" not in table_columns(conn, ListingProductCostSnapshot.__table__.name)
            or "api_account_id" in table_columns(conn, ListingProductCostSnapshot.__table__.name)
            or "product_id" in table_columns(conn, ListingProductCostSnapshot.__table__.name)
            or not table_has_foreign_key(
                conn,
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            )
        ),
        row_mapper=make_row_mapper(target_columns=[]),
        row_mapper_factory=lambda conn: make_listing_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProductCostSnapshot,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
        ),
        target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            ),
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cost_item_id",
                target_table="cost_item",
                target_column="pk",
            ),
        ],
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0013_rebuild_cost_item_snapshot_history_shape",
        domain="listing",
        description="Rebuild cost_item_snapshot without unique listing/cost_key constraint to keep history rows.",
        table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        should_run=lambda conn: table_exists(conn, ListingProductCostSnapshot.__table__.name)
        and (
            table_has_index(
                conn,
                ListingProductCostSnapshot.__table__.name,
                "sqlite_autoindex_cost_item_snapshot_1",
            )
            or table_has_index(
                conn,
                ListingProductCostSnapshot.__table__.name,
                "uq_cost_item_snapshot_key",
            )
        ),
        row_mapper=make_row_mapper(
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProductCostSnapshot,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
        ),
        target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            ),
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cost_item_id",
                target_table="cost_item",
                target_column="pk",
            ),
        ],
    ),
    build_append_rows_migration(
        migration_id="listing_trendyol_0014_append_trendyol_cost_item_rows_into_snapshots",
        domain="listing",
        description="Move trendyol listing cost bindings into cost_item_snapshot history rows.",
        old_table_name="trendyol_listing_product_cost_item",
        new_table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        row_mapper_factory=lambda conn: make_listing_cost_binding_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["cost_key"],
    ),
    build_backfill_migration(
        migration_id="listing_trendyol_0015_drop_deprecated_listing_cost_item_table",
        domain="listing",
        description="Drop deprecated trendyol_listing_product_cost_item table after snapshot migration.",
        should_run=lambda conn: table_exists(conn, "trendyol_listing_product_cost_item"),
        apply_sql=lambda conn: drop_table_if_exists(conn, "trendyol_listing_product_cost_item"),
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0016_add_cost_item_snapshot_status_column",
        domain="listing",
        description="Rebuild cost_item_snapshot to add append/set/remove status column.",
        table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        should_run=lambda conn: table_exists(conn, ListingProductCostSnapshot.__table__.name)
        and "status" not in table_columns(conn, ListingProductCostSnapshot.__table__.name),
        row_mapper=make_row_mapper(target_columns=[]),
        row_mapper_factory=lambda conn: make_listing_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProductCostSnapshot,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
        ),
        target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            ),
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cost_item_id",
                target_table="cost_item",
                target_column="pk",
            ),
        ],
    ),
    build_listing_cost_snapshot_compaction_migration(
        migration_id="listing_trendyol_0017_compact_cost_item_snapshot_history",
        domain="listing",
        description="Compact legacy duplicate cost item snapshot rows into append/set/remove history entries.",
        table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        validators=[
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            ),
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cost_item_id",
                target_table="cost_item",
                target_column="pk",
            ),
        ],
    ),
    build_append_rows_migration(
        migration_id="listing_trendyol_0018_append_trendyol_listing_product_item_into_stock_snapshots",
        domain="listing",
        description="Move trendyol listing stock bindings into stock_item_snapshot history rows.",
        old_table_name="trendyol_listing_product_item",
        new_table_name=ListingProductStockSnapshot.__table__.name,
        model=ListingProductStockSnapshot,
        row_mapper_factory=lambda conn: make_listing_stock_binding_snapshot_row_mapper(
            conn,
            target_columns=build_target_columns(model=ListingProductStockSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0019_rebuild_stock_item_snapshot_foreign_keys",
        domain="listing",
        description="Rebuild stock_item_snapshot to enforce listing and stock item foreign keys.",
        table_name=ListingProductStockSnapshot.__table__.name,
        model=ListingProductStockSnapshot,
        should_run=lambda conn: table_exists(conn, ListingProductStockSnapshot.__table__.name)
        and (
            not table_has_foreign_key(
                conn,
                table_name=ListingProductStockSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            )
            or not table_has_foreign_key(
                conn,
                table_name=ListingProductStockSnapshot.__table__.name,
                from_column="stock_item_id",
                target_table="stock_item",
                target_column="pk",
            )
        ),
        row_mapper=make_row_mapper(
            target_columns=build_target_columns(model=ListingProductStockSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProductStockSnapshot,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
        ),
        target_columns=build_target_columns(model=ListingProductStockSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProductStockSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            ),
            make_foreign_key_validator(
                table_name=ListingProductStockSnapshot.__table__.name,
                from_column="stock_item_id",
                target_table="stock_item",
                target_column="pk",
            ),
        ],
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0020_add_listing_product_history_account_fk",
        domain="listing",
        description="Rebuild trendyol_listing_product_history to enforce apiaccount foreign key.",
        table_name=ListingProductHistory.__table__.name,
        model=ListingProductHistory,
        should_run=lambda conn: table_exists(conn, ListingProductHistory.__table__.name)
        and not table_has_foreign_key(
            conn,
            table_name=ListingProductHistory.__table__.name,
            from_column="api_account_id",
            target_table="apiaccount",
            target_column="pk",
        ),
        row_mapper=make_row_mapper(
            target_columns=build_target_columns(model=ListingProductHistory, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProductHistory,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
        ),
        target_columns=build_target_columns(model=ListingProductHistory, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProductHistory.__table__.name,
                from_column="api_account_id",
                target_table="apiaccount",
                target_column="pk",
            )
        ],
    ),
    build_listing_cost_snapshot_tariff_meta_migration(
        migration_id="listing_trendyol_0021_rebuild_cost_item_snapshot_tariff_meta_shape",
        domain="listing",
        description="Rebuild cost_item_snapshot to fold legacy matched tariff columns into resolution_meta.",
        table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
    ),
    build_model_rebuild_migration(
        migration_id="listing_trendyol_0022_add_cost_item_snapshot_cargo_provider_fk",
        domain="listing",
        description="Rebuild cost_item_snapshot to enforce logistics cargo provider foreign key.",
        table_name=ListingProductCostSnapshot.__table__.name,
        model=ListingProductCostSnapshot,
        should_run=lambda conn: table_exists(conn, ListingProductCostSnapshot.__table__.name)
        and (
            "cargo_provider_id" not in table_columns(conn, ListingProductCostSnapshot.__table__.name)
            or not table_has_foreign_key(
                conn,
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cargo_provider_id",
                target_table=LogisticsCargoProvider.__table__.name,
                target_column="pk",
            )
        ),
        row_mapper=make_row_mapper(
            target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
            defaults={
                "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
            },
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=ListingProductCostSnapshot,
            extra_columns=SYNC_READY_EXTRA_COLUMNS,
        ),
        target_columns=build_target_columns(model=ListingProductCostSnapshot, extra_columns=SYNC_READY_EXTRA_COLUMNS),
        validators=[
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="listing_id",
                target_table=ListingProduct.__table__.name,
                target_column="pk",
            ),
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cost_item_id",
                target_table="cost_item",
                target_column="pk",
            ),
            make_foreign_key_validator(
                table_name=ListingProductCostSnapshot.__table__.name,
                from_column="cargo_provider_id",
                target_table=LogisticsCargoProvider.__table__.name,
                target_column="pk",
            ),
        ],
    ),
    build_backfill_migration(
        migration_id="listing_trendyol_0023_create_filter_hot_path_indexes",
        domain="listing",
        description="Create indexes used by large listing filters and updated-at ordering.",
        should_run=lambda conn: table_exists(conn, ListingProduct.__table__.name),
        apply_sql=lambda conn: [
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_listing_product_account_updated "
                "ON trendyol_listing_product(api_account_id, updated_at)"
            ),
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_listing_product_account_status_updated "
                "ON trendyol_listing_product(api_account_id, archived, on_sale, updated_at)"
            ),
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_listing_product_account_qty_updated "
                "ON trendyol_listing_product(api_account_id, archived, quantity, updated_at)"
            ),
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_listing_product_account_brand_updated "
                "ON trendyol_listing_product(api_account_id, brand, updated_at)"
            ),
        ],
    ),
]

