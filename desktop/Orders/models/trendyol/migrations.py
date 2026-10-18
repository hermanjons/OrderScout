from __future__ import annotations

from Core.db.migration_builders import (
    SYNC_READY_EXTRA_COLUMNS,
    build_backfill_migration,
    build_rehome_table_migration,
)
from Core.db.migration_ops import add_column_if_missing, drop_table_if_exists, table_exists
from Orders.models.trendyol.models import (
    OrderData,
    OrderHeader,
    OrderItem,
    ReturnClaim,
)


MIGRATIONS = [
    build_rehome_table_migration(
        migration_id="orders_trendyol_0001_rehome_order_header",
        domain="orders",
        description="Move legacy orderheader rows into trendyol_order_header.",
        old_table_name="orderheader",
        new_table_name=OrderHeader.__table__.name,
        model=OrderHeader,
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["orderNumber"],
        drop_old=False,
        defaults={
            "is_printed": lambda row: row.get("is_printed") if row.get("is_printed") is not None else 0,
            "is_extracted": lambda row: row.get("is_extracted") if row.get("is_extracted") is not None else 0,
            "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
        },
    ),
    build_rehome_table_migration(
        migration_id="orders_trendyol_0002_rehome_order_data",
        domain="orders",
        description="Move legacy orderdata rows into trendyol_order_data.",
        old_table_name="orderdata",
        new_table_name=OrderData.__table__.name,
        model=OrderData,
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["orderNumber"],
        drop_old=False,
        defaults={
            "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
        },
    ),
    build_rehome_table_migration(
        migration_id="orders_trendyol_0003_rehome_order_item",
        domain="orders",
        description="Move legacy orderitem rows into trendyol_order_item.",
        old_table_name="orderitem",
        new_table_name=OrderItem.__table__.name,
        model=OrderItem,
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["orderNumber"],
        drop_old=False,
        defaults={
            "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
        },
    ),
    build_rehome_table_migration(
        migration_id="orders_trendyol_0005_rehome_return_claim",
        domain="orders",
        description="Move legacy returnclaim rows into trendyol_return_claim.",
        old_table_name="returnclaim",
        new_table_name=ReturnClaim.__table__.name,
        model=ReturnClaim,
        extra_columns=SYNC_READY_EXTRA_COLUMNS,
        required_non_blank=["claimId"],
        drop_old=False,
        defaults={
            "sync_version": lambda row: row.get("sync_version") if row.get("sync_version") is not None else 1,
        },
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0006_drop_legacy_tables",
        domain="orders",
        description="Drop legacy Trendyol order tables after rehome completes.",
        should_run=lambda conn: any(
            table_exists(conn, table_name)
            for table_name in (
                "orderitem",
                "orderdata",
                "orderheader",
                "returnclaim",
            )
        ),
        apply_sql=lambda conn: [
            drop_table_if_exists(conn, table_name)
            for table_name in (
                "orderitem",
                "orderdata",
                "orderheader",
                "returnclaim",
            )
        ],
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0007_drop_cost_snapshot_tables",
        domain="orders",
        description="Drop unused Trendyol order cost snapshot tables.",
        should_run=lambda conn: any(
            table_exists(conn, table_name)
            for table_name in (
                "orderitemcostsnapshot",
                "trendyol_order_item_cost_snapshot",
            )
        ),
        apply_sql=lambda conn: [
            drop_table_if_exists(conn, table_name)
            for table_name in (
                "orderitemcostsnapshot",
                "trendyol_order_item_cost_snapshot",
            )
        ],
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0008_backfill_order_item_order_data_pk",
        domain="orders",
        description="Backfill trendyol_order_item.order_data_pk from order snapshots.",
        should_run=lambda conn: table_exists(conn, "trendyol_order_item") and table_exists(conn, "trendyol_order_data"),
        apply_sql=lambda conn: [
            add_column_if_missing(conn, table_name="trendyol_order_item", column_name="order_data_pk", column_sql="INTEGER"),
            conn.exec_driver_sql(
                """
                UPDATE trendyol_order_item
                SET order_data_pk = (
                    SELECT od.pk
                    FROM trendyol_order_data od
                    WHERE od.id = trendyol_order_item.order_data_id
                      AND od.lastModifiedDate = trendyol_order_item.snapshotLastModifiedDate
                      AND COALESCE(od.api_account_id, -1) = COALESCE(trendyol_order_item.api_account_id, -1)
                    LIMIT 1
                )
                WHERE order_data_pk IS NULL
                  AND order_data_id IS NOT NULL
                  AND snapshotLastModifiedDate IS NOT NULL
                """
            ),
            conn.exec_driver_sql(
                """
                UPDATE trendyol_order_item
                SET order_data_pk = (
                    SELECT od.pk
                    FROM trendyol_order_data od
                    WHERE od.pk = trendyol_order_item.order_data_id
                      AND od.lastModifiedDate = trendyol_order_item.snapshotLastModifiedDate
                      AND COALESCE(od.api_account_id, -1) = COALESCE(trendyol_order_item.api_account_id, -1)
                    LIMIT 1
                )
                WHERE order_data_pk IS NULL
                  AND order_data_id IS NOT NULL
                  AND snapshotLastModifiedDate IS NOT NULL
                """
            ),
            conn.exec_driver_sql(
                """
                UPDATE trendyol_order_item
                SET order_header_id = (
                    SELECT od.order_header_id
                    FROM trendyol_order_data od
                    WHERE od.pk = trendyol_order_item.order_data_pk
                    LIMIT 1
                )
                WHERE order_header_id IS NULL
                  AND order_data_pk IS NOT NULL
                """
            ),
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_order_item_order_data_pk ON trendyol_order_item(order_data_pk)"
            ),
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_order_item_orderdatapk_line ON trendyol_order_item(order_data_pk, lineId)"
            ),
        ],
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0009_backfill_return_claim_order_header",
        domain="orders",
        description="Backfill trendyol_return_claim.order_header_id from order headers.",
        should_run=lambda conn: table_exists(conn, "trendyol_return_claim") and table_exists(conn, "trendyol_order_header"),
        apply_sql=lambda conn: [
            add_column_if_missing(conn, table_name="trendyol_return_claim", column_name="order_header_id", column_sql="INTEGER"),
            conn.exec_driver_sql(
                """
                UPDATE trendyol_return_claim
                SET order_header_id = (
                    SELECT oh.pk
                    FROM trendyol_order_header oh
                    WHERE oh.orderNumber = trendyol_return_claim.orderNumber
                      AND COALESCE(oh.api_account_id, -1) = COALESCE(trendyol_return_claim.api_account_id, -1)
                    LIMIT 1
                )
                WHERE order_header_id IS NULL
                  AND TRIM(COALESCE(orderNumber, '')) <> ''
                """
            ),
            conn.exec_driver_sql(
                """
                UPDATE trendyol_return_claim
                SET order_header_id = (
                    SELECT od.order_header_id
                    FROM trendyol_order_data od
                    WHERE od.shipmentPackageId = trendyol_return_claim.orderShipmentPackageId
                      AND COALESCE(od.api_account_id, -1) = COALESCE(trendyol_return_claim.api_account_id, -1)
                    ORDER BY od.lastModifiedDate DESC
                    LIMIT 1
                )
                WHERE order_header_id IS NULL
                  AND orderShipmentPackageId IS NOT NULL
                """
            ),
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_return_claim_order_header_id ON trendyol_return_claim(order_header_id)"
            ),
        ],
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0010_add_order_item_future_fields",
        domain="orders",
        description="Ensure Trendyol order item stores newly added API fields.",
        should_run=lambda conn: table_exists(conn, "trendyol_order_item"),
        apply_sql=lambda conn: [
            add_column_if_missing(conn, table_name="trendyol_order_item", column_name="businessUnit", column_sql="TEXT"),
            add_column_if_missing(conn, table_name="trendyol_order_item", column_name="laborCost", column_sql="REAL"),
        ],
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0011_create_hot_path_indexes",
        domain="orders",
        description="Create composite indexes for latest-order and latest-claim queries.",
        should_run=lambda conn: any(
            table_exists(conn, table_name)
            for table_name in (
                "trendyol_order_data",
                "trendyol_return_claim",
            )
        ),
        apply_sql=lambda conn: [
            (
                conn.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_trendyol_order_data_account_orderno_lastmod ON trendyol_order_data(api_account_id, orderNumber, lastModifiedDate)"
                )
                if table_exists(conn, "trendyol_order_data")
                else None
            ),
            (
                conn.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_trendyol_order_data_header_lastmod ON trendyol_order_data(order_header_id, lastModifiedDate)"
                )
                if table_exists(conn, "trendyol_order_data")
                else None
            ),
            (
                conn.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_trendyol_return_claim_account_claim_lastmod ON trendyol_return_claim(api_account_id, claimId, lastModifiedDate)"
                )
                if table_exists(conn, "trendyol_return_claim")
                else None
            ),
        ],
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0012_backfill_order_data_headers",
        domain="orders",
        description="Backfill trendyol_order_data.order_header_id from order headers.",
        should_run=lambda conn: table_exists(conn, "trendyol_order_data") and table_exists(conn, "trendyol_order_header"),
        apply_sql=lambda conn: [
            conn.exec_driver_sql(
                """
                UPDATE trendyol_order_data
                SET order_header_id = (
                    SELECT oh.pk
                    FROM trendyol_order_header oh
                    WHERE oh.orderNumber = trendyol_order_data.orderNumber
                      AND COALESCE(oh.api_account_id, -1) = COALESCE(trendyol_order_data.api_account_id, -1)
                    LIMIT 1
                )
                WHERE order_header_id IS NULL
                  AND TRIM(COALESCE(orderNumber, '')) <> ''
                """
            ),
        ],
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0013_backfill_order_item_headers",
        domain="orders",
        description="Backfill trendyol_order_item.order_header_id from order headers when still missing.",
        should_run=lambda conn: table_exists(conn, "trendyol_order_item") and table_exists(conn, "trendyol_order_header"),
        apply_sql=lambda conn: [
            conn.exec_driver_sql(
                """
                UPDATE trendyol_order_item
                SET order_header_id = (
                    SELECT oh.pk
                    FROM trendyol_order_header oh
                    WHERE oh.orderNumber = trendyol_order_item.orderNumber
                      AND COALESCE(oh.api_account_id, -1) = COALESCE(trendyol_order_item.api_account_id, -1)
                    LIMIT 1
                )
                WHERE order_header_id IS NULL
                  AND TRIM(COALESCE(orderNumber, '')) <> ''
                """
            ),
        ],
    ),
    build_backfill_migration(
        migration_id="orders_trendyol_0014_create_filter_hot_path_indexes",
        domain="orders",
        description="Create indexes used by large order filter and latest snapshot queries.",
        should_run=lambda conn: table_exists(conn, "trendyol_order_data"),
        apply_sql=lambda conn: [
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_order_data_shipmentPackageStatus ON trendyol_order_data(shipmentPackageStatus)"
            ),
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_order_data_shipment_orderdate ON trendyol_order_data(shipmentPackageStatus, orderDate)"
            ),
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trendyol_order_data_account_status_orderdate_lastmod ON trendyol_order_data(api_account_id, shipmentPackageStatus, orderDate, lastModifiedDate)"
            ),
        ],
    ),
]
