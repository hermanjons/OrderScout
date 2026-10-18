from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from Core.db.migration_runner import run_domain_migrations
from Finance.models.trendyol.migrations import MIGRATIONS


class TestFinanceMigrations(unittest.TestCase):
    def test_legacy_finance_cost_item_table_is_rehomed_to_cost_item(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item (
                        pk INTEGER PRIMARY KEY,
                        costKey TEXT NOT NULL,
                        name TEXT,
                        description TEXT,
                        valueType TEXT,
                        defaultMatchMode TEXT,
                        defaultAmount REAL,
                        currency TEXT,
                        isVatIncluded INTEGER,
                        vatRate REAL,
                        supportedSourceTypesJson TEXT,
                        supportedPlatformsJson TEXT,
                        defaultSourceType TEXT,
                        defaultSourceConfigJson TEXT,
                        isActive INTEGER,
                        isDeleted INTEGER,
                        createdAt TEXT,
                        updatedAt TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE financecostitem (
                        pk INTEGER PRIMARY KEY,
                        costKey TEXT NOT NULL,
                        name TEXT,
                        description TEXT,
                        valueType TEXT,
                        defaultMatchMode TEXT,
                        defaultAmount REAL,
                        currency TEXT,
                        isVatIncluded INTEGER,
                        vatRate REAL,
                        supportedSourceTypesJson TEXT,
                        supportedPlatformsJson TEXT,
                        defaultSourceType TEXT,
                        defaultSourceConfigJson TEXT,
                        isActive INTEGER,
                        isDeleted INTEGER,
                        createdAt TEXT,
                        updatedAt TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item_snapshot (
                        id INTEGER PRIMARY KEY,
                        cost_item_id INTEGER,
                        FOREIGN KEY(cost_item_id) REFERENCES financecostitem(pk)
                    )
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO financecostitem (
                    pk, costKey, name, description, valueType, defaultMatchMode, defaultAmount,
                    currency, isVatIncluded, vatRate, supportedSourceTypesJson, supportedPlatformsJson,
                    defaultSourceType, defaultSourceConfigJson, isActive, isDeleted, createdAt, updatedAt
                ) VALUES (
                    1, 'paketleme', 'Paketleme', 'Demo', 'numeric', 'manual', 12.5,
                    'TRY', 1, 20, '[]', '[]',
                    'manual_value', NULL, 1, 0, '2026-04-04T10:00:00', '2026-04-04T10:00:00'
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
                    SELECT pk, costKey, name, currency
                    FROM cost_item
                    WHERE pk = 1
                    """
                )
            ).fetchone()
            fk_rows = conn.execute(text("PRAGMA foreign_key_list('cost_item_snapshot')")).fetchall()

            self.assertIn("finance_trendyol_0001_rehome_cost_item", applied)
            self.assertIn("cost_item", tables)
            self.assertNotIn("financecostitem", tables)
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 1)
            self.assertEqual(str(row[1]), "paketleme")
            self.assertEqual(str(row[2]), "Paketleme")
            self.assertEqual(str(row[3]), "TRY")
            self.assertTrue(
                any(
                    str(fk[2] or "").lower() == "cost_item"
                    and str(fk[3] or "").lower() == "cost_item_id"
                    and str(fk[4] or "").lower() == "pk"
                    for fk in fk_rows
                )
            )

    def test_legacy_finance_profit_method_table_is_dropped(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE financeprofitmethod (
                        pk INTEGER PRIMARY KEY,
                        name TEXT
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            tables = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='financeprofitmethod'")
            ).fetchall()

            self.assertIn("finance_trendyol_0002_drop_legacy_finance_profit_method_table", applied)
            self.assertEqual(tables, [])

    def test_deprecated_cost_item_platform_link_table_is_dropped(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item (
                        pk INTEGER PRIMARY KEY,
                        costKey TEXT NOT NULL,
                        name TEXT,
                        description TEXT,
                        valueType TEXT,
                        defaultMatchMode TEXT,
                        defaultAmount REAL,
                        currency TEXT,
                        isVatIncluded INTEGER,
                        vatRate REAL,
                        supportedSourceTypesJson TEXT,
                        supportedPlatformsJson TEXT,
                        defaultSourceType TEXT,
                        defaultSourceConfigJson TEXT,
                        isActive INTEGER,
                        isDeleted INTEGER,
                        createdAt TEXT,
                        updatedAt TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE cost_item_platform_link (
                        pk INTEGER PRIMARY KEY,
                        cost_item_id INTEGER,
                        marketplace_id INTEGER
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)
            tables = {
                str(row[0])
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            }
            self.assertIn("finance_trendyol_0003_drop_cost_item_platform_links", applied)
            self.assertNotIn("cost_item_platform_link", tables)

    def test_legacy_finance_transaction_table_is_rehomed_to_trendyol_finance_transaction(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE financetransaction (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER,
                        serviceKey TEXT NOT NULL,
                        sellerId INTEGER,
                        recordId TEXT NOT NULL,
                        transactionType TEXT,
                        description TEXT,
                        transactionDate INTEGER,
                        orderDate INTEGER,
                        paymentDate INTEGER,
                        orderNumber TEXT,
                        shipmentPackageId INTEGER,
                        barcode TEXT,
                        receiptId INTEGER,
                        paymentOrderId TEXT,
                        paymentPeriod INTEGER,
                        currency TEXT,
                        country TEXT,
                        affiliate TEXT,
                        debt REAL,
                        credit REAL,
                        netAmount REAL,
                        sellerRevenue REAL,
                        commissionRate REAL,
                        commissionAmount REAL,
                        commissionInvoiceSerialNumber TEXT,
                        storeId INTEGER,
                        storeName TEXT,
                        storeAddress TEXT
                    )
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO financetransaction (
                    pk, api_account_id, serviceKey, recordId, transactionDate, orderNumber, currency
                ) VALUES (
                    1, 10, 'settlements', 'R-1', 1710000000000, 'ORD-1', 'TRY'
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
                    SELECT pk, api_account_id, serviceKey, recordId, orderNumber, currency
                    FROM trendyol_finance_transaction
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertIn("finance_trendyol_0004_rehome_finance_transaction", applied)
            self.assertIn("trendyol_finance_transaction", tables)
            self.assertNotIn("financetransaction", tables)
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 1)
            self.assertEqual(int(row[1]), 10)
            self.assertEqual(str(row[2]), "settlements")
            self.assertEqual(str(row[3]), "R-1")
            self.assertEqual(str(row[4]), "ORD-1")
            self.assertEqual(str(row[5]), "TRY")

    def test_legacy_finance_cargo_invoice_item_table_is_rehomed_to_trendyol_finance_cargo_invoice_item(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE financecargoinvoiceitem (
                        pk INTEGER PRIMARY KEY,
                        api_account_id INTEGER,
                        sellerId INTEGER,
                        invoiceSerialNumber TEXT NOT NULL,
                        parcelUniqueId INTEGER,
                        orderNumber TEXT,
                        shipmentPackageType TEXT,
                        amount REAL,
                        desi REAL
                    )
                    """
                )
            )
            conn.exec_driver_sql(
                """
                INSERT INTO financecargoinvoiceitem (
                    pk, api_account_id, invoiceSerialNumber, parcelUniqueId, orderNumber, shipmentPackageType, amount, desi
                ) VALUES (
                    1, 10, 'INV-1', 1001, 'ORD-1', 'BOX', 45.5, 2.0
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
                    SELECT pk, api_account_id, invoiceSerialNumber, parcelUniqueId, orderNumber, shipmentPackageType, amount, desi
                    FROM trendyol_finance_cargo_invoice_item
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertIn("finance_trendyol_0005_rehome_finance_cargo_invoice_item", applied)
            self.assertIn("trendyol_finance_cargo_invoice_item", tables)
            self.assertNotIn("financecargoinvoiceitem", tables)
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 1)
            self.assertEqual(int(row[1]), 10)
            self.assertEqual(str(row[2]), "INV-1")
            self.assertEqual(int(row[3]), 1001)
            self.assertEqual(str(row[4]), "ORD-1")
            self.assertEqual(str(row[5]), "BOX")
            self.assertEqual(float(row[6]), 45.5)
            self.assertEqual(float(row[7]), 2.0)


if __name__ == "__main__":
    unittest.main()
