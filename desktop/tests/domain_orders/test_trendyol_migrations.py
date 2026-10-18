from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text
from sqlmodel import SQLModel

from Core.db.migration_runner import run_domain_migrations
from Marketplaces.models.models import Marketplace
from Orders.models.trendyol.migrations import MIGRATIONS

_ = Marketplace


class TestTrendyolOrderMigrations(unittest.TestCase):
    def test_rehomes_legacy_order_tables_into_trendyol_prefixed_tables(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE orderheader (
                        pk INTEGER PRIMARY KEY,
                        orderNumber TEXT NOT NULL,
                        api_account_id INTEGER,
                        is_printed INTEGER DEFAULT 0,
                        is_extracted INTEGER DEFAULT 0,
                        printed_at INTEGER,
                        extracted_at INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE orderdata (
                        pk INTEGER PRIMARY KEY,
                        order_header_id INTEGER,
                        orderNumber TEXT NOT NULL,
                        api_account_id INTEGER,
                        status TEXT,
                        id INTEGER NOT NULL,
                        shipmentPackageId INTEGER,
                        lastModifiedDate INTEGER NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX ix_orderno_lastmod ON orderdata(orderNumber, lastModifiedDate)"))
            conn.execute(
                text(
                    "CREATE INDEX ix_orderno_status_lastmod ON orderdata(orderNumber, status, lastModifiedDate)"
                )
            )
            conn.execute(text("CREATE INDEX ix_orderdata_package_lastmod ON orderdata(id, lastModifiedDate)"))
            conn.execute(
                text(
                    """
                    CREATE TABLE orderitem (
                        pk INTEGER PRIMARY KEY,
                        order_header_id INTEGER,
                        orderNumber TEXT NOT NULL,
                        api_account_id INTEGER,
                        order_data_pk INTEGER,
                        order_data_id INTEGER,
                        snapshotLastModifiedDate INTEGER,
                        quantity INTEGER NOT NULL,
                        productName TEXT,
                        lineId INTEGER
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX ix_orderitem_orderno_productcode ON orderitem(orderNumber, productName)"))
            conn.execute(
                text(
                    "CREATE INDEX ix_orderitem_snapshot_line ON orderitem(order_data_id, snapshotLastModifiedDate, lineId)"
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE returnclaim (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER,
                        order_header_id INTEGER,
                        claimId TEXT NOT NULL,
                        orderNumber TEXT,
                        lastModifiedDate INTEGER NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX ix_returnclaim_claim_lastmod ON returnclaim(claimId, lastModifiedDate)"))
            conn.execute(text("CREATE INDEX ix_returnclaim_orderno_lastmod ON returnclaim(orderNumber, lastModifiedDate)"))
            conn.execute(
                text("CREATE INDEX ix_returnclaim_status_claimdate ON returnclaim(claimId, lastModifiedDate)")
            )
            conn.execute(
                text("INSERT INTO orderheader (pk, orderNumber, api_account_id) VALUES (1, 'ORD-1', NULL)")
            )
            conn.execute(
                text(
                    """
                    INSERT INTO orderdata (
                        pk, order_header_id, orderNumber, api_account_id, status, id, shipmentPackageId, lastModifiedDate
                    ) VALUES (
                        1, NULL, 'ORD-1', NULL, 'Created', 101, 5001, 1700000000000
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO orderitem (
                        pk, order_header_id, orderNumber, api_account_id, order_data_id,
                        snapshotLastModifiedDate, quantity, productName, lineId
                    ) VALUES (
                        1, NULL, 'ORD-1', NULL, 1, 1700000000000, 2, 'Demo Product', 7001
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO returnclaim (pk, api_account_id, claimId, orderNumber, lastModifiedDate)
                    VALUES (1, NULL, 'CLM-1', 'ORD-1', 1700000000001)
                    """
                )
            )

            conn.execute(
                text(
                    """
                    CREATE TABLE orderitemcostsnapshot (
                        pk INTEGER PRIMARY KEY,
                        orderNumber TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_order_item_cost_snapshot (
                        pk INTEGER PRIMARY KEY,
                        orderNumber TEXT NOT NULL
                    )
                    """
                )
            )

            SQLModel.metadata.create_all(bind=conn)
            applied = run_domain_migrations(conn, migrations=MIGRATIONS)

            self.assertIn("orders_trendyol_0001_rehome_order_header", applied)
            self.assertIn("orders_trendyol_0005_rehome_return_claim", applied)

            migrated_header = conn.execute(
                text("SELECT orderNumber FROM trendyol_order_header WHERE pk = 1")
            ).fetchone()
            migrated_data = conn.execute(
                text("SELECT shipmentPackageId, order_header_id FROM trendyol_order_data WHERE pk = 1")
            ).fetchone()
            migrated_item = conn.execute(
                text("SELECT productName, order_data_pk, order_header_id FROM trendyol_order_item WHERE pk = 1")
            ).fetchone()
            migrated_claim = conn.execute(
                text("SELECT claimId, order_header_id FROM trendyol_return_claim WHERE pk = 1")
            ).fetchone()
            migrated_columns = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info('trendyol_order_item')")).fetchall()
            }
            migrated_indexes = {
                row[1]
                for row in conn.execute(text("PRAGMA index_list('trendyol_order_data')")).fetchall()
            }
            old_tables = {
                row[0]
                for row in conn.execute(
                    text(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                          AND name IN (
                              'orderheader',
                              'orderdata',
                              'orderitem',
                              'trendyol_order_item_cost_snapshot',
                              'orderitemcostsnapshot',
                              'returnclaim'
                          )
                        """
                    )
                ).fetchall()
            }

            self.assertEqual(old_tables, set())
            self.assertEqual(str(migrated_header[0]), "ORD-1")
            self.assertEqual(int(migrated_data[0]), 5001)
            self.assertEqual(int(migrated_data[1]), 1)
            self.assertEqual(str(migrated_item[0]), "Demo Product")
            self.assertEqual(int(migrated_item[1]), 1)
            self.assertEqual(int(migrated_item[2]), 1)
            self.assertEqual(str(migrated_claim[0]), "CLM-1")
            self.assertEqual(int(migrated_claim[1]), 1)
            self.assertIn("businessUnit", migrated_columns)
            self.assertIn("laborCost", migrated_columns)
            self.assertIn("ix_trendyol_order_data_account_orderno_lastmod", migrated_indexes)


if __name__ == "__main__":
    unittest.main()
