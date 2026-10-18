from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text

from Core.db import bootstrap
from Core.db.models import build_source_id
import Core.db.migrator as migrator


class TestBootstrapModelMigrations(unittest.TestCase):
    def setUp(self) -> None:
        migrator.clear_registered_tables()

    def tearDown(self) -> None:
        migrator.clear_registered_tables()

    def test_model_column_registration_adds_missing_trendyol_order_data_columns(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE trendyol_order_data (
                        pk INTEGER PRIMARY KEY,
                        orderNumber TEXT,
                        api_account_id INTEGER,
                        lastModifiedDate INTEGER
                    )
                    """
                )
            )

            bootstrap._register_model_column_migrations()
            migrator.run_auto_migrations(conn)

            cols = conn.execute(text("PRAGMA table_info(trendyol_order_data)")).fetchall()
            col_names = {str(row[1]) for row in cols}

            self.assertIn("identityNumber", col_names)
            self.assertIn("packageHistories", col_names)
            self.assertIn("shipmentPackageStatus", col_names)

    def test_auto_migrations_do_not_register_deprecated_listing_cost_item_table(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            bootstrap._register_auto_migrations()
            migrator.run_auto_migrations(conn)

            tables = {
                str(row[0])
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            }
            self.assertNotIn("trendyol_listing_product_cost_item", tables)

    def test_model_column_registration_adds_stock_tx_vat_mode_columns(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE stock_tx (
                        id INTEGER PRIMARY KEY,
                        item_id INTEGER,
                        warehouse_id INTEGER,
                        direction TEXT,
                        reason TEXT,
                        qty REAL,
                        occurred_at TEXT,
                        created_at TEXT,
                        unit_cost REAL,
                        currency TEXT
                    )
                    """
                )
            )

            bootstrap._register_model_column_migrations()
            migrator.run_auto_migrations(conn)

            cols = conn.execute(text("PRAGMA table_info(stock_tx)")).fetchall()
            col_names = {str(row[1]) for row in cols}

            self.assertIn("unit_cost_input_mode", col_names)
            self.assertIn("unit_cost_vat_rate", col_names)

    def test_source_identity_registration_adds_marketplace_identity_indexes(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE marketplace (
                        pk INTEGER PRIMARY KEY,
                        code TEXT,
                        label TEXT,
                        isActive INTEGER DEFAULT 1
                    )
                    """
                )
            )

            bootstrap._register_auto_migrations()
            migrator.run_auto_migrations(conn)

            cols = conn.execute(text("PRAGMA table_info(marketplace)")).fetchall()
            col_names = {str(row[1]) for row in cols}
            index_rows = conn.execute(text("PRAGMA index_list(marketplace)")).fetchall()
            index_names = {str(row[1]) for row in index_rows}

            self.assertIn("sourceType", col_names)
            self.assertIn("sourceId", col_names)
            self.assertIn("ix_marketplace_sourceType", index_names)
            self.assertIn("ix_marketplace_sourceId", index_names)
            self.assertIn("uq_marketplace_source_identity", index_names)

    def test_reconcile_builtin_source_identity_updates_builtin_backed_rows(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE marketplace (
                        pk INTEGER PRIMARY KEY,
                        code TEXT,
                        label TEXT,
                        sourceType TEXT,
                        sourceId INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE logistics_cargo_provider (
                        pk INTEGER PRIMARY KEY,
                        platformCode TEXT,
                        cargoProviderCode TEXT,
                        cargoProviderName TEXT,
                        sourceType TEXT,
                        sourceId INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item (
                        pk INTEGER PRIMARY KEY,
                        costKey TEXT,
                        sourceType TEXT,
                        sourceId INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE cargo_tariff (
                        pk INTEGER PRIMARY KEY,
                        tariffKey TEXT,
                        sourceType TEXT,
                        sourceId INTEGER
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO marketplace (pk, code, label, sourceType, sourceId) VALUES (1, 'TRENDYOL', 'Trendyol', 'user', 11)"))
            conn.execute(text("INSERT INTO logistics_cargo_provider (pk, platformCode, cargoProviderCode, cargoProviderName, sourceType, sourceId) VALUES (2, 'TRENDYOL', 'ARASMP', 'Aras', 'user', 22)"))
            conn.execute(text("INSERT INTO cost_item (pk, costKey, sourceType, sourceId) VALUES (3, 'komisyon', 'user', 33)"))
            conn.execute(text("INSERT INTO cargo_tariff (pk, tariffKey, sourceType, sourceId) VALUES (4, 'trendyol-express-0-5-desi', 'user', 44)"))

            marketplace_source_id = build_source_id("marketplace", {"code": "TRENDYOL"}, source_type="builtin")
            provider_source_id = build_source_id(
                "logistics_cargo_provider",
                {"platformCode": "TRENDYOL", "cargoProviderCode": "ARASMP"},
                source_type="builtin",
            )
            cost_item_source_id = build_source_id("cost_item", {"costKey": "komisyon"}, source_type="builtin")
            cargo_tariff_source_id = build_source_id(
                "cargo_tariff",
                {"platform": "TRENDYOL", "tariffKey": "trendyol-express-0-5-desi"},
                source_type="builtin",
            )

            with patch("Marketplaces.constants.catalog_constants.load_default_marketplaces", return_value=[{"code": "TRENDYOL", "sourceId": marketplace_source_id}]), patch(
                "Logistics.constants.catalog_constants.builtin_cargo_provider_records",
                return_value=[{"platformCode": "TRENDYOL", "cargoProviderCode": "ARASMP", "sourceId": provider_source_id}],
            ), patch(
                "Finance.constants.domain_constants.FINANCE_BUILTIN_COST_ITEM_RECORDS",
                [{"costKey": "komisyon", "sourceId": cost_item_source_id}],
            ), patch(
                "Logistics.constants.catalog_constants.default_cargo_tariff_records",
                return_value=[{"tariffKey": "trendyol-express-0-5-desi", "source_id": cargo_tariff_source_id}],
            ):
                bootstrap._reconcile_builtin_source_identity(conn)

            marketplace_row = conn.execute(text("SELECT sourceType, sourceId FROM marketplace WHERE pk = 1")).fetchone()
            provider_row = conn.execute(text("SELECT sourceType, sourceId FROM logistics_cargo_provider WHERE pk = 2")).fetchone()
            cost_item_row = conn.execute(text("SELECT sourceType, sourceId FROM cost_item WHERE pk = 3")).fetchone()
            cargo_tariff_row = conn.execute(text("SELECT sourceType, sourceId FROM cargo_tariff WHERE pk = 4")).fetchone()

            self.assertEqual(tuple(marketplace_row), ("builtin", marketplace_source_id))
            self.assertEqual(tuple(provider_row), ("builtin", provider_source_id))
            self.assertEqual(tuple(cost_item_row), ("builtin", cost_item_source_id))
            self.assertEqual(tuple(cargo_tariff_row), ("builtin", cargo_tariff_source_id))

    def test_reconcile_builtin_source_identity_updates_builtin_content_and_syncs_links(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE marketplace (
                    pk INTEGER PRIMARY KEY,
                    code TEXT,
                    label TEXT,
                    description TEXT,
                    logoPath TEXT,
                    isActive INTEGER,
                    updatedAt TEXT,
                    sourceType TEXT,
                    sourceId INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE logistics_cargo_provider (
                    pk INTEGER PRIMARY KEY,
                    platform_id INTEGER,
                    platformCode TEXT,
                    cargoProviderCode TEXT,
                    cargoProviderName TEXT,
                    logoPath TEXT,
                    note TEXT,
                    updatedAt TEXT,
                    sourceType TEXT,
                    sourceId INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE cost_item (
                    pk INTEGER PRIMARY KEY,
                    costKey TEXT,
                    name TEXT,
                    description TEXT,
                    valueType TEXT,
                    defaultMatchMode TEXT,
                    defaultAmount REAL,
                    currency TEXT,
                    isVatIncluded INTEGER,
                    vatRate REAL,
                    supportedPlatformsJson TEXT,
                    supportedPlatformSourceIdsJson TEXT,
                    supportedSourceTypesJson TEXT,
                    defaultSourceType TEXT,
                    defaultSourceConfigJson TEXT,
                    isActive INTEGER,
                    updatedAt TEXT,
                    sourceType TEXT,
                    sourceId INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE cost_item_marketplace_link (
                    pk INTEGER PRIMARY KEY,
                    cost_item_id INTEGER,
                    marketplace_id INTEGER,
                    createdAt TEXT,
                    updatedAt TEXT,
                    sourceType TEXT,
                    sourceId INTEGER
                )
            """))
            conn.execute(text("""
                CREATE TABLE cargo_tariff (
                    pk INTEGER PRIMARY KEY,
                    tariffKey TEXT,
                    name TEXT,
                    description TEXT,
                    cargo_provider_id INTEGER,
                    cargoProviderCode TEXT,
                    cargoProviderName TEXT,
                    amount REAL,
                    currency TEXT,
                    isVatIncluded INTEGER,
                    vatRate REAL,
                    isActive INTEGER,
                    updatedAt TEXT,
                    sourceType TEXT,
                    sourceId INTEGER
                )
            """))

            conn.execute(text("INSERT INTO marketplace VALUES (1, 'TRENDYOL', 'Eski Trendyol', 'eski', NULL, 1, '2026-04-01T00:00:00', 'user', 11)"))
            conn.execute(text("INSERT INTO logistics_cargo_provider VALUES (2, 1, 'TRENDYOL', 'ARASMP', 'Eski Aras', NULL, NULL, '2026-04-01T00:00:00', 'user', 22)"))
            conn.execute(text("""INSERT INTO cost_item VALUES (
                3, 'komisyon', 'Eski Komisyon', 'eski', 'percentage', 'manual', 10, 'TRY', 1, 20,
                '[]', '[]', '["manual_value"]', 'manual_value', NULL, 1, '2026-04-01T00:00:00', 'user', 33
            )"""))
            conn.execute(text("""INSERT INTO cargo_tariff VALUES (
                4, 'trendyol-express-0-5-desi', 'Eski Tarife', 'eski', 2, 'ARASMP', 'Eski Aras', 10, 'TRY', 1, 20, 1, '2026-04-01T00:00:00', 'user', 44
            )"""))

            with patch(
                "Marketplaces.constants.catalog_constants.load_default_marketplaces",
                return_value=[{"code": "TRENDYOL", "label": "Trendyol Yeni", "description": "guncel", "sourceId": 1, "isActive": True}],
            ), patch(
                "Logistics.constants.catalog_constants.builtin_cargo_provider_records",
                return_value=[{"platformCode": "TRENDYOL", "platformSourceId": 1, "cargoProviderCode": "ARASMP", "cargoProviderName": "Aras Yeni", "sourceId": 2}],
            ), patch(
                "Finance.constants.domain_constants.FINANCE_BUILTIN_COST_ITEM_RECORDS",
                [{
                    "costKey": "komisyon",
                    "name": "Komisyon Yeni",
                    "description": "guncel",
                    "valueType": "percentage",
                    "defaultMatchMode": "manual",
                    "defaultAmount": 12,
                    "currency": "TRY",
                    "isVatIncluded": True,
                    "vatRate": 20,
                    "supportedPlatformSourceIds": [1],
                    "supportedSourceTypes": ["manual_value"],
                    "defaultSourceType": "manual_value",
                    "defaultSourceConfig": None,
                    "isActive": True,
                    "sourceId": 3,
                }],
            ), patch(
                "Logistics.constants.catalog_constants.default_cargo_tariff_records",
                return_value=[
                    {
                        "tariffKey": "trendyol-express-0-5-desi",
                        "name": "Tarife Yeni",
                        "description": "guncel",
                        "cargoProviderCode": "ARASMP",
                        "cargoProviderName": "Aras Yeni",
                        "cargo_provider_source_id": 2,
                        "amount": 99.5,
                        "currency": "TRY",
                        "isVatIncluded": False,
                        "vatRate": 20,
                        "isActive": True,
                        "source_id": 4,
                    }
                ],
            ):
                bootstrap._reconcile_builtin_source_identity(conn)

            marketplace_row = conn.execute(text("SELECT label, sourceType, sourceId FROM marketplace WHERE pk = 1")).fetchone()
            provider_row = conn.execute(text("SELECT cargoProviderName, sourceType, sourceId FROM logistics_cargo_provider WHERE pk = 2")).fetchone()
            cost_item_row = conn.execute(text("SELECT name, supportedPlatformSourceIdsJson, sourceType, sourceId FROM cost_item WHERE pk = 3")).fetchone()
            link_row = conn.execute(text("SELECT cost_item_id, marketplace_id, sourceType, sourceId FROM cost_item_marketplace_link")).fetchone()
            cargo_tariff_row = conn.execute(text("SELECT name, amount, sourceType, sourceId FROM cargo_tariff WHERE pk = 4")).fetchone()

            self.assertEqual(tuple(marketplace_row), ("Trendyol Yeni", "builtin", 1))
            self.assertEqual(tuple(provider_row), ("Aras Yeni", "builtin", 2))
            self.assertEqual(tuple(cost_item_row), ("Komisyon Yeni", "[1]", "builtin", 3))
            self.assertEqual(tuple(link_row[:3]), (3, 1, "builtin"))
            self.assertGreater(int(link_row[3] or 0), 0)
            self.assertEqual(tuple(cargo_tariff_row), ("Tarife Yeni", 99.5, "builtin", 4))

    def test_reconcile_builtin_source_identity_deactivates_removed_builtin_records(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE marketplace (pk INTEGER PRIMARY KEY, code TEXT, isActive INTEGER, updatedAt TEXT, sourceType TEXT, sourceId INTEGER)"))
            conn.execute(text("CREATE TABLE logistics_cargo_provider (pk INTEGER PRIMARY KEY, platformCode TEXT, cargoProviderCode TEXT, updatedAt TEXT, sourceType TEXT, sourceId INTEGER)"))
            conn.execute(text("CREATE TABLE cost_item (pk INTEGER PRIMARY KEY, costKey TEXT, isActive INTEGER, updatedAt TEXT, sourceType TEXT, sourceId INTEGER)"))
            conn.execute(text("CREATE TABLE cargo_tariff (pk INTEGER PRIMARY KEY, tariffKey TEXT, isActive INTEGER, updatedAt TEXT, sourceType TEXT, sourceId INTEGER)"))
            conn.execute(text("INSERT INTO marketplace VALUES (1, 'TRENDYOL', 1, '2026-04-01T00:00:00', 'builtin', 1)"))
            conn.execute(text("INSERT INTO logistics_cargo_provider VALUES (2, 'TRENDYOL', 'ARASMP', '2026-04-01T00:00:00', 'builtin', 2)"))
            conn.execute(text("INSERT INTO cost_item VALUES (3, 'komisyon', 1, '2026-04-01T00:00:00', 'builtin', 3)"))
            conn.execute(text("INSERT INTO cargo_tariff VALUES (4, 'tarife', 1, '2026-04-01T00:00:00', 'builtin', 4)"))

            with patch("Marketplaces.constants.catalog_constants.load_default_marketplaces", return_value=[]), patch(
                "Logistics.constants.catalog_constants.builtin_cargo_provider_records", return_value=[]
            ), patch(
                "Finance.constants.domain_constants.FINANCE_BUILTIN_COST_ITEM_RECORDS", []
            ), patch(
                "Logistics.constants.catalog_constants.default_cargo_tariff_records", return_value=[]
            ):
                bootstrap._reconcile_builtin_source_identity(conn)

            self.assertEqual(tuple(conn.execute(text("SELECT sourceType, isActive FROM marketplace WHERE pk = 1")).fetchone()), ("builtin", 0))
            self.assertEqual(tuple(conn.execute(text("SELECT sourceType FROM logistics_cargo_provider WHERE pk = 2")).fetchone()), ("builtin",))
            self.assertEqual(tuple(conn.execute(text("SELECT sourceType, isActive FROM cost_item WHERE pk = 3")).fetchone()), ("builtin", 0))
            self.assertEqual(tuple(conn.execute(text("SELECT sourceType, isActive FROM cargo_tariff WHERE pk = 4")).fetchone()), ("builtin", 0))

    def test_source_identity_registration_renames_legacy_license_primary_keys(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE license_state (
                        id INTEGER PRIMARY KEY,
                        provider TEXT NOT NULL,
                        license_key TEXT NOT NULL,
                        device_id TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE license_action_log (
                        id INTEGER PRIMARY KEY,
                        action TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        device_id TEXT NOT NULL
                    )
                    """
                )
            )

            bootstrap._register_auto_migrations()
            migrator.run_auto_migrations(conn)

            for table_name in ("license_state", "license_action_log"):
                cols = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                col_names = {str(row[1]) for row in cols}
                self.assertIn("pk", col_names, table_name)
                self.assertNotIn("id", col_names, table_name)

    def test_sync_tables_gain_audit_columns_and_backfill_values(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sync_outbox (
                        pk INTEGER PRIMARY KEY AUTOINCREMENT,
                        table_name TEXT NOT NULL,
                        record_sync_uuid TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        payload_json TEXT,
                        created_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE sync_state (
                        pk INTEGER PRIMARY KEY AUTOINCREMENT,
                        state_key TEXT NOT NULL UNIQUE,
                        state_value TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE sync_change_log (
                        pk INTEGER PRIMARY KEY AUTOINCREMENT,
                        table_name TEXT NOT NULL,
                        record_sync_uuid TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        payload_json TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sync_outbox (
                        table_name, record_sync_uuid, operation, payload_json, created_at, status, retry_count, last_error
                    ) VALUES (
                        'apiaccount', 'sync-1', 'upsert', '{}', '2026-04-01T10:00:00', 'pending', 0, NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sync_state (
                        state_key, state_value, updated_at
                    ) VALUES (
                        'order', 'ready', '2026-04-01T11:00:00'
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sync_change_log (
                        table_name, record_sync_uuid, operation, payload_json, created_at
                    ) VALUES (
                        'apiaccount', 'sync-2', 'upsert', '{}', '2026-04-01T12:00:00'
                    )
                    """
                )
            )

            bootstrap._register_auto_migrations()
            migrator.run_auto_migrations(conn)
            bootstrap._backfill_system_audit_timestamps(conn)

            for table_name in ("sync_outbox", "sync_state", "sync_change_log"):
                cols = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                col_names = {str(row[1]) for row in cols}
                self.assertIn("created_at", col_names, table_name)
                self.assertIn("updated_at", col_names, table_name)

            outbox_row = conn.execute(
                text(
                    """
                    SELECT created_at, updated_at
                    FROM sync_outbox
                    WHERE record_sync_uuid = 'sync-1'
                    """
                )
            ).fetchone()
            state_row = conn.execute(
                text(
                    """
                    SELECT created_at, updated_at
                    FROM sync_state
                    WHERE state_key = 'order'
                    """
                )
            ).fetchone()
            change_row = conn.execute(
                text(
                    """
                    SELECT created_at, updated_at
                    FROM sync_change_log
                    WHERE record_sync_uuid = 'sync-2'
                    """
                )
            ).fetchone()

            self.assertEqual(str(outbox_row[0]), "2026-04-01T10:00:00")
            self.assertEqual(str(outbox_row[1]), "2026-04-01T10:00:00")
            self.assertEqual(str(state_row[0]), "2026-04-01T11:00:00")
            self.assertEqual(str(state_row[1]), "2026-04-01T11:00:00")
            self.assertEqual(str(change_row[0]), "2026-04-01T12:00:00")
            self.assertEqual(str(change_row[1]), "2026-04-01T12:00:00")

if __name__ == "__main__":
    unittest.main()
