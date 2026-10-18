from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from Core.db.migration_runner import run_domain_migrations
from Stock.models.migrations import MIGRATIONS


class TestStockMigrations(unittest.TestCase):
    def test_stock_item_custom_tag_is_renamed_to_custom_label(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_item (
                        pk INTEGER PRIMARY KEY,
                        sku TEXT NOT NULL,
                        name TEXT NOT NULL,
                        barcode TEXT,
                        item_type TEXT DEFAULT 'physical',
                        unit TEXT DEFAULT 'adet',
                        brand TEXT,
                        category TEXT,
                        sub_category TEXT,
                        model_code TEXT,
                        manufacturer TEXT,
                        gtip_code TEXT,
                        custom_tag TEXT,
                        location_code TEXT,
                        image_path TEXT,
                        description TEXT,
                        note TEXT,
                        is_active INTEGER DEFAULT 1,
                        min_stock REAL,
                        max_stock REAL,
                        safety_stock REAL,
                        reorder_point REAL,
                        reorder_qty REAL,
                        lead_time_days INTEGER,
                        shelf_life_days INTEGER,
                        serial_tracking INTEGER DEFAULT 0,
                        lot_tracking INTEGER DEFAULT 0,
                        allow_negative_stock INTEGER DEFAULT 0,
                        vat_rate REAL,
                        weight_kg REAL,
                        length_cm REAL,
                        width_cm REAL,
                        height_cm REAL,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_uuid TEXT,
                        sync_version INTEGER DEFAULT 1,
                        sync_updated_at TEXT,
                        sync_deleted_at TEXT,
                        sync_source_device TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO stock_item (
                        pk, sku, name, custom_tag, item_type, unit, is_active, created_at, updated_at, sync_version
                    ) VALUES (
                        1, 'SKU-1', 'Demo Stok', 'etiket-1', 'physical', 'adet', 1,
                        '2026-04-02T10:00:00', '2026-04-02T10:00:00', 3
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            cols = conn.execute(text("PRAGMA table_info(stock_item)")).fetchall()
            col_names = {str(row[1]) for row in cols}
            row = conn.execute(
                text(
                    """
                    SELECT custom_label
                    FROM stock_item
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertIn("stock_0001_stock_item_custom_label", applied)
            self.assertIn("custom_label", col_names)
            self.assertIn("custom_tag", col_names)
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "etiket-1")

    def test_stock_hot_path_indexes_are_created_for_existing_tables(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE warehouse (
                        pk INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        code TEXT,
                        is_active INTEGER DEFAULT 1,
                        created_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_tx (
                        pk INTEGER PRIMARY KEY,
                        item_id INTEGER NOT NULL,
                        warehouse_id INTEGER NOT NULL,
                        direction TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        qty REAL NOT NULL,
                        occurred_at TEXT,
                        created_at TEXT,
                        reference_type TEXT,
                        reference_id TEXT
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)

            warehouse_indexes = {
                str(row[1]) for row in conn.execute(text("PRAGMA index_list('warehouse')")).fetchall()
            }
            stock_tx_indexes = {
                str(row[1]) for row in conn.execute(text("PRAGMA index_list('stock_tx')")).fetchall()
            }

            self.assertIn("stock_0002_create_hot_path_indexes", applied)
            self.assertIn("ix_warehouse_code", warehouse_indexes)
            self.assertIn("ix_stock_tx_item_time", stock_tx_indexes)
            self.assertIn("ix_stock_tx_warehouse_time", stock_tx_indexes)

    def test_stock_tx_rebuild_adds_order_header_fk(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_order_header (
                        pk INTEGER PRIMARY KEY,
                        orderNumber TEXT NOT NULL,
                        api_account_id INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO trendyol_order_header (pk, orderNumber, api_account_id)
                    VALUES (11, 'ORD-1', 1)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_tx (
                        pk INTEGER PRIMARY KEY,
                        item_id INTEGER NOT NULL,
                        warehouse_id INTEGER NOT NULL,
                        direction TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        qty REAL NOT NULL,
                        occurred_at TEXT,
                        created_at TEXT,
                        reference_type TEXT,
                        reference_id TEXT,
                        order_ref TEXT,
                        listing_id TEXT,
                        order_header_id INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO stock_tx (
                        pk, item_id, warehouse_id, direction, reason, qty, occurred_at, created_at,
                        reference_type, reference_id, order_ref, listing_id, order_header_id
                    ) VALUES (
                        1, 7, 2, 'OUT', 'order_out', 3, '2026-04-07T10:00:00', '2026-04-07T10:00:00',
                        'order', 'ref-1', 'ORD-1', 'P-1', 11
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            row = conn.execute(
                text(
                    """
                    SELECT order_header_id, order_ref
                    FROM stock_tx
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertIn("stock_0003_add_stock_tx_order_header_fk", applied)
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 11)
            self.assertEqual(str(row[1]), "ORD-1")

    def test_stock_item_rebuild_backfills_brand_foreign_key_from_name(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE brand (
                        pk INTEGER PRIMARY KEY,
                        name TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO brand (pk, name) VALUES (7, 'ACME')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_item (
                        pk INTEGER PRIMARY KEY,
                        sku TEXT NOT NULL,
                        name TEXT NOT NULL,
                        item_type TEXT NOT NULL DEFAULT 'physical',
                        unit TEXT NOT NULL DEFAULT 'adet',
                        brand TEXT,
                        is_active INTEGER DEFAULT 1,
                        serial_tracking INTEGER NOT NULL DEFAULT 0,
                        lot_tracking INTEGER NOT NULL DEFAULT 0,
                        allow_negative_stock INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO stock_item (
                        pk, sku, name, item_type, unit, brand, is_active,
                        serial_tracking, lot_tracking, allow_negative_stock, created_at, updated_at
                    )
                    VALUES (
                        1, 'SKU-1', 'Demo Item', 'physical', 'adet', 'ACME', 1,
                        0, 0, 0, '2026-04-09T10:00:00', '2026-04-09T10:00:00'
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            col_names = {str(row[1]) for row in conn.execute(text("PRAGMA table_info(stock_item)")).fetchall()}
            row = conn.execute(
                text(
                    """
                    SELECT brand_id, brand
                    FROM stock_item
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertTrue(
                "stock_0004_add_stock_item_brand_fk" in applied
                or "stock_0006_backfill_stock_item_brand_ids" in applied
            )
            self.assertIn("brand_id", col_names)
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 7)
            self.assertEqual(str(row[1]), "ACME")

    def test_stock_tx_rebuild_backfills_company_foreign_key_from_counterparty(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE company (
                        pk INTEGER PRIMARY KEY,
                        name TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO company (pk, name) VALUES (5, 'Demo Muhatap')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_tx (
                        pk INTEGER PRIMARY KEY,
                        item_id INTEGER NOT NULL,
                        warehouse_id INTEGER NOT NULL,
                        direction TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        qty REAL NOT NULL,
                        reference_type TEXT NOT NULL DEFAULT 'none',
                        occurred_at TEXT,
                        created_at TEXT,
                        counterparty TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO stock_tx (
                        pk, item_id, warehouse_id, direction, reason, qty, reference_type, occurred_at, created_at, counterparty
                    ) VALUES (
                        1, 7, 2, 'IN', 'manual_in', 3, 'none', '2026-04-09T10:00:00', '2026-04-09T10:00:00', 'Demo Muhatap'
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            col_names = {str(row[1]) for row in conn.execute(text("PRAGMA table_info(stock_tx)")).fetchall()}
            row = conn.execute(
                text(
                    """
                    SELECT company_id, counterparty
                    FROM stock_tx
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertTrue(
                "stock_0005_add_stock_tx_company_fk" in applied
                or "stock_0007_backfill_stock_tx_company_ids" in applied
            )
            self.assertIn("company_id", col_names)
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 5)
            self.assertEqual(str(row[1]), "Demo Muhatap")

    def test_stock_tx_backfill_marks_legacy_cost_rows_as_net(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_item (
                        pk INTEGER PRIMARY KEY,
                        vat_rate REAL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO stock_item (pk, vat_rate) VALUES (1, 20)"))
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_tx (
                        pk INTEGER PRIMARY KEY,
                        item_id INTEGER,
                        warehouse_id INTEGER,
                        direction TEXT,
                        reason TEXT,
                        qty REAL,
                        occurred_at TEXT,
                        created_at TEXT,
                        unit_cost REAL,
                        currency TEXT,
                        unit_cost_input_mode TEXT,
                        unit_cost_vat_rate REAL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO stock_tx (
                        pk, item_id, warehouse_id, direction, reason, qty, occurred_at, created_at,
                        unit_cost, currency, unit_cost_input_mode, unit_cost_vat_rate
                    )
                    VALUES (
                        1, 1, 1, 'IN', 'manual_in', 1, '2026-03-11 10:00:00', '2026-03-11 10:00:00',
                        20, 'TRY', NULL, NULL
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            row = conn.execute(
                text("SELECT unit_cost_input_mode, unit_cost_vat_rate FROM stock_tx WHERE pk = 1")
            ).fetchone()

            self.assertIn("stock_0008_backfill_stock_tx_legacy_cost_defaults", applied)
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "net")
            self.assertAlmostEqual(float(row[1] or 0.0), 20.0)


if __name__ == "__main__":
    unittest.main()
