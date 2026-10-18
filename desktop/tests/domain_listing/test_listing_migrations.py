from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine, text

from Core.db.migration_runner import run_domain_migrations
from Listing.models.migrations import MIGRATIONS


class TestListingMigrations(unittest.TestCase):
    def test_legacy_listing_tables_are_rehomed_to_snapshot_backed_tables(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE listing_product (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        title TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 3
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE listing_product_item (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        stock_item_id INTEGER NOT NULL,
                        qty REAL,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE listing_product_cost_item (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        cost_key TEXT NOT NULL,
                        calculation_type TEXT,
                        source_type TEXT,
                        source_config TEXT,
                        tariff_key TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE listing_product_cost_snapshot (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        cost_key TEXT NOT NULL,
                        source_type TEXT,
                        source_config TEXT,
                        resolved_amount REAL,
                        resolved_net_amount REAL,
                        resolved_vat_amount REAL,
                        currency TEXT,
                        note TEXT,
                        resolution_meta TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE listing_product_history (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        changes TEXT,
                        created_at TEXT
                    )
                    """
                )
            )

            conn.execute(
                text(
                    """
                    INSERT INTO listing_product (pk, api_account_id, product_id, title, created_at, updated_at, sync_version)
                    VALUES (1, 10, 'P-100', 'Demo Listing', '2026-04-04T10:00:00', '2026-04-04T10:00:00', 3)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO listing_product_item (pk, api_account_id, product_id, stock_item_id, qty, created_at, updated_at)
                    VALUES (2, 10, 'P-100', 77, 2, '2026-04-04T10:00:00', '2026-04-04T10:00:00')
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO listing_product_cost_item (
                    pk, api_account_id, product_id, cost_key, calculation_type, source_type, source_config, tariff_key,
                    created_at, updated_at
                ) VALUES (
                    3, 10, 'P-100', 'cargo', 'manual', 'manual_value', '{"amount":12.5}', NULL,
                    '2026-04-04T10:00:00', '2026-04-04T10:00:00'
                )
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO listing_product_cost_snapshot (
                    pk, api_account_id, product_id, cost_key, source_type, source_config, resolved_amount,
                    resolved_net_amount, resolved_vat_amount, currency, note, resolution_meta, created_at, updated_at
                ) VALUES (
                    4, 10, 'P-100', 'cargo', 'manual_value', '{"amount":12.5}', 12.5,
                    10.42, 2.08, 'TRY', 'demo', '{"matchedTariffKey":"x"}', '2026-04-04T10:00:00', '2026-04-04T10:00:00'
                )
                """
            )
            conn.execute(
                text(
                    """
                    INSERT INTO listing_product_history (pk, api_account_id, product_id, changes, created_at)
                    VALUES (5, 10, 'P-100', '{"title":"old"}', '2026-04-04T10:00:00')
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)

            tables = {
                str(row[0])
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            }

            self.assertIn("listing_trendyol_0001_rehome_listing_product", applied)
            self.assertIn("listing_trendyol_0006_drop_legacy_tables", applied)
            self.assertIn("trendyol_listing_product", tables)
            self.assertIn("stock_item_snapshot", tables)
            self.assertIn("cost_item_snapshot", tables)
            self.assertIn("trendyol_listing_product_history", tables)
            self.assertNotIn("listing_product", tables)
            self.assertNotIn("listing_product_item", tables)
            self.assertNotIn("listing_product_cost_item", tables)
            self.assertNotIn("listing_product_cost_snapshot", tables)
            self.assertNotIn("listing_product_history", tables)
            self.assertNotIn("trendyol_listing_product_cost_item", tables)
            self.assertNotIn("trendyol_listing_product_item", tables)

            listing_row = conn.execute(
                text(
                    """
                    SELECT api_account_id, product_id, title, sync_version
                    FROM trendyol_listing_product
                    WHERE pk = 1
                    """
                )
            ).fetchone()
            stock_snapshot_row = conn.execute(
                text(
                    """
                    SELECT listing_id, stock_item_id, qty, status
                    FROM stock_item_snapshot
                    ORDER BY pk
                    """
                )
            ).fetchone()

            self.assertIsNotNone(listing_row)
            self.assertEqual(int(listing_row[0]), 10)
            self.assertEqual(str(listing_row[1]), "P-100")
            self.assertEqual(str(listing_row[2]), "Demo Listing")
            self.assertEqual(int(listing_row[3]), 3)
            self.assertIsNotNone(stock_snapshot_row)
            self.assertEqual(int(stock_snapshot_row[0]), 1)
            self.assertEqual(int(stock_snapshot_row[1]), 77)
            self.assertAlmostEqual(float(stock_snapshot_row[2] or 0.0), 2.0)
            self.assertEqual(str(stock_snapshot_row[3]), "append")
            snapshot_rows = conn.execute(
                text(
                    """
                    SELECT cost_key, status, source_type, resolved_amount
                    FROM cost_item_snapshot
                    ORDER BY pk
                    """
                )
            ).fetchall()
            self.assertEqual(len(snapshot_rows), 1)
            self.assertEqual(str(snapshot_rows[0][0]), "cargo")
            self.assertEqual(str(snapshot_rows[0][1]), "append")
            self.assertEqual(str(snapshot_rows[0][2]), "manual_value")
            self.assertAlmostEqual(float(snapshot_rows[0][3] or 0.0), 12.5)

    def test_trendyol_listing_product_rebuild_adds_api_account_fk(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE apiaccount (
                        pk INTEGER PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        comp_name TEXT NOT NULL,
                        platform TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        title TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 4
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO apiaccount (pk, account_id, comp_name, platform)
                    VALUES (10, 'seller-10', 'Demo', 'trendyol')
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO trendyol_listing_product (
                        pk, api_account_id, product_id, title, created_at, updated_at, sync_version
                    ) VALUES (
                        1, 10, 'P-200', 'Existing Listing', '2026-04-04T11:00:00', '2026-04-04T11:00:00', 4
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            fk_rows = conn.execute(text("PRAGMA foreign_key_list('trendyol_listing_product')")).fetchall()
            row = conn.execute(
                text(
                    """
                    SELECT api_account_id, product_id, title, sync_version
                    FROM trendyol_listing_product
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertIn("listing_trendyol_0007_add_listing_product_account_fk", applied)
            self.assertTrue(
                any(
                    str(fk[2] or "").lower() == "apiaccount"
                    and str(fk[3] or "").lower() == "api_account_id"
                    and str(fk[4] or "").lower() == "pk"
                    for fk in fk_rows
                )
            )
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 10)
            self.assertEqual(str(row[1]), "P-200")
            self.assertEqual(str(row[2]), "Existing Listing")
            self.assertEqual(int(row[3]), 4)

    def test_trendyol_listing_product_rebuild_adds_stock_item_fk(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE apiaccount (
                        pk INTEGER PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        comp_name TEXT NOT NULL,
                        platform TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO apiaccount (pk, account_id, comp_name, platform) VALUES (10, 'seller-10', 'Demo', 'trendyol')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_item (
                        pk INTEGER PRIMARY KEY,
                        sku TEXT NOT NULL,
                        name TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO stock_item (pk, sku, name) VALUES (77, 'SKU-77', 'Stock 77')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        stock_item_id INTEGER,
                        title TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 5
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO trendyol_listing_product (
                        pk, api_account_id, product_id, stock_item_id, title, created_at, updated_at, sync_version
                    ) VALUES (
                        1, 10, 'P-300', 77, 'Mapped Listing', '2026-04-04T12:00:00', '2026-04-04T12:00:00', 5
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            fk_rows = conn.execute(text("PRAGMA foreign_key_list('trendyol_listing_product')")).fetchall()
            row = conn.execute(
                text(
                    """
                    SELECT stock_item_id, sync_version
                    FROM trendyol_listing_product
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertIn("listing_trendyol_0008_add_listing_product_stock_item_fk", applied)
            self.assertTrue(
                any(
                    str(fk[2] or "").lower() == "stock_item"
                    and str(fk[3] or "").lower() == "stock_item_id"
                    and str(fk[4] or "").lower() == "pk"
                    for fk in fk_rows
                )
            )
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 77)
            self.assertEqual(int(row[1]), 5)

    def test_trendyol_listing_product_item_rows_move_into_stock_item_snapshot(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE apiaccount (
                        pk INTEGER PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        comp_name TEXT NOT NULL,
                        platform TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO apiaccount (pk, account_id, comp_name, platform) VALUES (10, 'seller-10', 'Demo', 'trendyol')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_item (
                        pk INTEGER PRIMARY KEY,
                        sku TEXT NOT NULL,
                        name TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO stock_item (pk, sku, name) VALUES (77, 'SKU-77', 'Stock 77')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        stock_item_id INTEGER,
                        title TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 5
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO trendyol_listing_product (
                        pk, api_account_id, product_id, stock_item_id, title, created_at, updated_at, sync_version
                    ) VALUES (
                        1, 10, 'P-300', 77, 'Mapped Listing', '2026-04-04T12:00:00', '2026-04-04T12:00:00', 5
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product_item (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        stock_item_id INTEGER NOT NULL,
                        qty REAL,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 6
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO trendyol_listing_product_item (
                        pk, api_account_id, product_id, stock_item_id, qty, created_at, updated_at, sync_version
                    ) VALUES (
                        2, 10, 'P-300', 77, 2.5, '2026-04-04T12:00:00', '2026-04-04T12:00:00', 6
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            tables = {
                str(row[0])
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            }
            fk_rows = conn.execute(text("PRAGMA foreign_key_list('stock_item_snapshot')")).fetchall()
            row = conn.execute(
                text(
                    """
                    SELECT listing_id, stock_item_id, qty, status, sync_version
                    FROM stock_item_snapshot
                    ORDER BY pk
                    """
                )
            ).fetchone()

            self.assertIn("listing_trendyol_0018_append_trendyol_listing_product_item_into_stock_snapshots", applied)
            self.assertIn("listing_trendyol_0019_rebuild_stock_item_snapshot_foreign_keys", applied)
            self.assertIn("stock_item_snapshot", tables)
            self.assertNotIn("trendyol_listing_product_item", tables)
            self.assertTrue(
                any(
                    str(fk[2] or "").lower() == "trendyol_listing_product"
                    and str(fk[3] or "").lower() == "listing_id"
                    and str(fk[4] or "").lower() == "pk"
                    for fk in fk_rows
                )
            )
            self.assertTrue(
                any(
                    str(fk[2] or "").lower() == "stock_item"
                    and str(fk[3] or "").lower() == "stock_item_id"
                    and str(fk[4] or "").lower() == "pk"
                    for fk in fk_rows
                )
            )
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 1)
            self.assertEqual(int(row[1]), 77)
            self.assertAlmostEqual(float(row[2] or 0.0), 2.5)
            self.assertEqual(str(row[3]), "append")
            self.assertEqual(int(row[4]), 6)

    def test_trendyol_listing_product_history_rebuild_adds_api_account_fk(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE apiaccount (
                        pk INTEGER PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        comp_name TEXT NOT NULL,
                        platform TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO apiaccount (pk, account_id, comp_name, platform) VALUES (10, 'seller-10', 'Demo', 'trendyol')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product_history (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        changes TEXT,
                        created_at TEXT,
                        sync_version INTEGER DEFAULT 8
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO trendyol_listing_product_history (
                        pk, api_account_id, product_id, changes, created_at, sync_version
                    ) VALUES (
                        5, 10, 'P-500', '{"title":"old"}', '2026-04-04T10:00:00', 8
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            fk_rows = conn.execute(text("PRAGMA foreign_key_list('trendyol_listing_product_history')")).fetchall()
            row = conn.execute(
                text(
                    """
                    SELECT api_account_id, product_id, sync_version
                    FROM trendyol_listing_product_history
                    WHERE pk = 5
                    """
                )
            ).fetchone()

            self.assertIn("listing_trendyol_0020_add_listing_product_history_account_fk", applied)
            self.assertTrue(
                any(
                    str(fk[2] or "").lower() == "apiaccount"
                    and str(fk[3] or "").lower() == "api_account_id"
                    and str(fk[4] or "").lower() == "pk"
                    for fk in fk_rows
                )
            )
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 10)
            self.assertEqual(str(row[1]), "P-500")
            self.assertEqual(int(row[2]), 8)

    def test_cost_item_snapshot_rebuild_moves_matched_tariff_columns_to_resolution_meta(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item_snapshot (
                        pk INTEGER PRIMARY KEY,
                        status TEXT DEFAULT 'append',
                        cost_item_id INTEGER,
                        listing_id INTEGER NOT NULL,
                        cost_key TEXT NOT NULL,
                        source_type TEXT,
                        source_config TEXT,
                        resolved_amount REAL,
                        resolved_net_amount REAL,
                        resolved_vat_amount REAL,
                        currency TEXT,
                        note TEXT,
                        resolution_meta TEXT,
                        matched_tariff_key TEXT,
                        matched_tariff_name TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO cost_item_snapshot (
                        pk, status, cost_item_id, listing_id, cost_key, source_type, source_config,
                        resolved_amount, resolved_net_amount, resolved_vat_amount, currency, note,
                        resolution_meta, matched_tariff_key, matched_tariff_name, created_at, updated_at
                    ) VALUES (
                        1, 'append', NULL, 41, 'kargo', 'builtin_resolver', '{"ruleKey":"cargo_amount_matcher"}',
                        12.5, 10.42, 2.08, 'TRY', 'Aras 0-1',
                        NULL, 'aras-0-1', 'Aras 0-1', '2026-03-12', '2026-03-12'
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            cols = conn.execute(text("PRAGMA table_info(cost_item_snapshot)")).fetchall()
            col_names = {str(row[1]) for row in cols}
            row = conn.execute(
                text("SELECT resolution_meta FROM cost_item_snapshot WHERE pk = 1")
            ).fetchone()

            self.assertIn("listing_trendyol_0021_rebuild_cost_item_snapshot_tariff_meta_shape", applied)
            self.assertNotIn("matched_tariff_key", col_names)
            self.assertNotIn("matched_tariff_name", col_names)
            self.assertIn("resolution_meta", col_names)
            self.assertIsNotNone(row)
            self.assertEqual(
                json.loads(str(row[0])),
                {
                    "matchedTariffKey": "aras-0-1",
                    "matchedTariffName": "Aras 0-1",
                },
            )

    def test_cost_item_snapshot_rebuild_adds_cargo_provider_fk(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE logistics_cargo_provider (
                        pk INTEGER PRIMARY KEY,
                        platformCode TEXT NOT NULL,
                        cargoProviderCode TEXT NOT NULL,
                        cargoProviderName TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO logistics_cargo_provider (pk, platformCode, cargoProviderCode, cargoProviderName)
                    VALUES (41, 'TRENDYOL', 'ARAS', 'Aras Kargo Marketplace')
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item_snapshot (
                        pk INTEGER PRIMARY KEY,
                        status TEXT DEFAULT 'append',
                        cost_item_id INTEGER,
                        listing_id INTEGER NOT NULL,
                        cost_key TEXT NOT NULL,
                        source_type TEXT,
                        source_config TEXT,
                        resolved_amount REAL,
                        resolved_net_amount REAL,
                        resolved_vat_amount REAL,
                        currency TEXT,
                        note TEXT,
                        resolution_meta TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO cost_item_snapshot (
                    pk, status, cost_item_id, listing_id, cost_key, source_type, source_config,
                    resolved_amount, resolved_net_amount, resolved_vat_amount, currency, note,
                    resolution_meta, created_at, updated_at
                ) VALUES (
                    1, 'append', NULL, 41, 'kargo', 'builtin_resolver',
                    '{"ruleKey":"cargo_amount_matcher","cargoProviderId":41,"cargoProviderCode":"ARAS"}',
                    NULL, NULL, NULL, 'TRY', NULL, NULL, '2026-03-12', '2026-03-12'
                )
                """
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            fk_rows = conn.execute(text("PRAGMA foreign_key_list('cost_item_snapshot')")).fetchall()
            cols = conn.execute(text("PRAGMA table_info(cost_item_snapshot)")).fetchall()
            col_names = {str(row[1]) for row in cols}

            self.assertIn("listing_trendyol_0022_add_cost_item_snapshot_cargo_provider_fk", applied)
            self.assertIn("cargo_provider_id", col_names)
            self.assertTrue(
                any(
                    str(fk[2] or "").lower() == "logistics_cargo_provider"
                    and str(fk[3] or "").lower() == "cargo_provider_id"
                    and str(fk[4] or "").lower() == "pk"
                    for fk in fk_rows
                )
            )

    def test_trendyol_cost_snapshot_table_is_rehomed_to_cost_item_snapshot(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE listing_product (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        title TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 1
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO listing_product (pk, api_account_id, product_id, title, created_at, updated_at, sync_version)
                    VALUES (41, 10, 'P-400', 'Demo Listing', '2026-04-04T10:00:00', '2026-04-04T10:00:00', 1)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product_cost_snapshot (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        cost_key TEXT NOT NULL,
                        source_type TEXT,
                        source_config TEXT,
                        resolved_amount REAL,
                        resolved_net_amount REAL,
                        resolved_vat_amount REAL,
                        currency TEXT,
                        note TEXT,
                        resolution_meta TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 6
                    )
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO trendyol_listing_product_cost_snapshot (
                    pk, api_account_id, product_id, cost_key, source_type, source_config,
                    resolved_amount, resolved_net_amount, resolved_vat_amount, currency,
                    note, resolution_meta, created_at, updated_at, sync_version
                ) VALUES (
                    4, 10, 'P-400', 'cargo', 'manual_value', '{"amount":12.5}',
                    12.5, 10.42, 2.08, 'TRY',
                    'demo', '{"matchedTariffKey":"x"}', '2026-04-04T10:00:00', '2026-04-04T10:00:00', 6
                )
                """
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            tables = {
                str(row[0])
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            }
            row = conn.execute(
                text(
                    """
                    SELECT listing_id, cost_key, sync_version
                    FROM cost_item_snapshot
                    WHERE listing_id = 41 AND cost_key = 'cargo'
                    """
                )
            ).fetchone()

            self.assertIn("listing_trendyol_0009_rehome_trendyol_cost_snapshot", applied)
            self.assertIn("cost_item_snapshot", tables)
            self.assertNotIn("trendyol_listing_product_cost_snapshot", tables)
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 41)
            self.assertEqual(str(row[1]), "cargo")
            self.assertEqual(int(row[2]), 6)

    def test_cost_item_snapshot_rebuild_adds_finance_cost_item_fk_and_backfills_match(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item (
                        pk INTEGER PRIMARY KEY,
                        costKey TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO cost_item (pk, costKey) VALUES (91, 'paketleme')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE listing_product (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        title TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 1
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO listing_product (pk, api_account_id, product_id, title, created_at, updated_at, sync_version)
                    VALUES (51, 10, 'P-500', 'Demo Listing', '2026-04-04T10:00:00', '2026-04-04T10:00:00', 1)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item_snapshot (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        cost_key TEXT NOT NULL,
                        source_type TEXT,
                        source_config TEXT,
                        resolved_amount REAL,
                        resolved_net_amount REAL,
                        resolved_vat_amount REAL,
                        currency TEXT,
                        note TEXT,
                        resolution_meta TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        sync_version INTEGER DEFAULT 7
                    )
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO cost_item_snapshot (
                    pk, api_account_id, product_id, cost_key, source_type, source_config,
                    resolved_amount, resolved_net_amount, resolved_vat_amount, currency,
                    note, resolution_meta, created_at, updated_at, sync_version
                ) VALUES (
                    5, 10, 'P-500', 'paketleme', 'manual_value', '{"amount":5}',
                    5, 4.17, 0.83, 'TRY',
                    'demo', '{"matchedTariffKey":"x"}', '2026-04-04T10:00:00', '2026-04-04T10:00:00', 7
                )
                """
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            fk_rows = conn.execute(text("PRAGMA foreign_key_list('cost_item_snapshot')")).fetchall()
            row = conn.execute(
                text(
                    """
                    SELECT cost_item_id, listing_id, sync_version
                    FROM cost_item_snapshot
                    WHERE listing_id = 51 AND cost_key = 'paketleme'
                    """
                )
            ).fetchone()

            self.assertIn("listing_trendyol_0010_add_cost_item_snapshot_cost_item_fk", applied)
            self.assertIn("listing_trendyol_0011_backfill_cost_item_snapshot_cost_item_ids", applied)
            self.assertTrue(
                any(
                    str(fk[2] or "").lower() == "cost_item"
                    and str(fk[3] or "").lower() == "cost_item_id"
                    and str(fk[4] or "").lower() == "pk"
                    for fk in fk_rows
                )
            )
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 91)
            self.assertEqual(int(row[1]), 51)
            self.assertEqual(int(row[2]), 7)

    def test_trendyol_cost_item_table_is_appended_into_snapshots_and_dropped(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO trendyol_listing_product (pk, api_account_id, product_id, created_at, updated_at)
                    VALUES (71, 10, 'P-700', '2026-04-04T10:00:00', '2026-04-04T10:00:00')
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product_cost_item (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        cost_key TEXT NOT NULL,
                        calculation_type TEXT,
                        source_type TEXT,
                        source_config TEXT,
                        tariff_key TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO trendyol_listing_product_cost_item (
                    pk, api_account_id, product_id, cost_key, calculation_type, source_type, source_config,
                    tariff_key, created_at, updated_at
                ) VALUES (
                    8, 10, 'P-700', 'paketleme', 'manual', 'manual_value', '{"amount":9.5}',
                    NULL, '2026-04-04T10:00:00', '2026-04-04T10:00:00'
                )
                """
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            tables = {
                str(row[0])
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            }
            row = conn.execute(
                text(
                    """
                    SELECT listing_id, cost_key, source_type
                    FROM cost_item_snapshot
                    WHERE listing_id = 71 AND cost_key = 'paketleme'
                    """
                )
            ).fetchone()

            self.assertIn("listing_trendyol_0014_append_trendyol_cost_item_rows_into_snapshots", applied)
            self.assertIn("listing_trendyol_0015_drop_deprecated_listing_cost_item_table", applied)
            self.assertNotIn("trendyol_listing_product_cost_item", tables)
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 71)
            self.assertEqual(str(row[1]), "paketleme")
            self.assertEqual(str(row[2]), "manual_value")

    def test_cost_item_snapshot_compaction_migration_collapses_duplicate_history(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE apiaccount (
                        pk INTEGER PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        comp_name TEXT NOT NULL,
                        platform TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO apiaccount (pk, account_id, comp_name, platform) VALUES (10, 'seller-10', 'Demo', 'trendyol')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_item (
                        pk INTEGER PRIMARY KEY,
                        sku TEXT NOT NULL,
                        name TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO stock_item (pk, sku, name) VALUES (77, 'SKU-77', 'Stock 77')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item (
                        pk INTEGER PRIMARY KEY,
                        costKey TEXT NOT NULL UNIQUE,
                        name TEXT,
                        createdAt TEXT,
                        updatedAt TEXT
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO cost_item (pk, costKey, name, createdAt, updatedAt) VALUES (101, 'kargo', 'Kargo', '2026-04-04T10:00:00', '2026-04-04T10:00:00')"))
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_listing_product (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER NOT NULL,
                        product_id TEXT NOT NULL,
                        title TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO trendyol_listing_product (
                        pk, api_account_id, product_id, title, created_at, updated_at
                    ) VALUES (
                        624, 10, 'P-624', 'Demo Listing', '2026-04-04T10:00:00', '2026-04-04T10:00:00'
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item_snapshot (
                        pk INTEGER PRIMARY KEY,
                        cost_item_id INTEGER,
                        listing_id INTEGER NOT NULL,
                        cost_key TEXT NOT NULL,
                        source_type TEXT,
                        source_config TEXT,
                        resolved_amount REAL,
                        resolved_net_amount REAL,
                        resolved_vat_amount REAL,
                        currency TEXT,
                        note TEXT,
                        resolution_meta TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO cost_item_snapshot (
                    pk, cost_item_id, listing_id, cost_key, source_type, source_config,
                    resolved_amount, currency, resolution_meta, created_at, updated_at
                ) VALUES
                    (1, 101, 624, 'kargo', 'manual_value', '{"amount":93.0}', NULL, 'TRY', '{"binding_event":"set"}', '2026-04-07 11:00:00', '2026-04-07 11:00:00'),
                    (2, 101, 624, 'kargo', 'manual_value', '{"amount":93.0}', 93.0, 'TRY', NULL, '2026-04-07 11:00:01', '2026-04-07 11:00:01'),
                    (3, 101, 624, 'kargo', 'manual_value', '{"amount":93.0}', 93.0, 'TRY', NULL, '2026-04-07 11:00:02', '2026-04-07 11:00:02'),
                    (4, 101, 624, 'kargo', NULL, NULL, NULL, 'TRY', '{"removed":true,"binding_event":"remove"}', '2026-04-07 11:00:03', '2026-04-07 11:00:03'),
                    (5, 101, 624, 'kargo', 'manual_value', '{"amount":123.0}', NULL, 'TRY', '{"binding_event":"set"}', '2026-04-07 11:00:04', '2026-04-07 11:00:04'),
                    (6, 101, 624, 'kargo', 'manual_value', '{"amount":123.0}', 123.0, 'TRY', NULL, '2026-04-07 11:00:05', '2026-04-07 11:00:05')
                """
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            self.assertIn("listing_trendyol_0016_add_cost_item_snapshot_status_column", applied)
            self.assertIn("listing_trendyol_0017_compact_cost_item_snapshot_history", applied)

            rows = conn.execute(
                text(
                    """
                    SELECT cost_key, status, source_type, resolved_amount
                    FROM cost_item_snapshot
                    WHERE listing_id = 624
                    ORDER BY pk
                    """
                )
            ).fetchall()

            self.assertEqual(rows, [
                ("kargo", "append", "manual_value", 93.0),
                ("kargo", "remove", "manual_value", 93.0),
                ("kargo", "append", "manual_value", 123.0),
            ])


if __name__ == "__main__":
    unittest.main()
