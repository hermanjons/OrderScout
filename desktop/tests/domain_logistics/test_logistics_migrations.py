from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from Core.db.migration_builders import table_has_foreign_key
from Core.db.migration_runner import run_domain_migrations
from Logistics.models.migrations import MIGRATIONS


class TestLogisticsMigrations(unittest.TestCase):
    def test_cargo_tariff_rebuild_adds_provider_fk_and_backfills_existing_rows(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE marketplace (
                        pk INTEGER PRIMARY KEY,
                        code TEXT NOT NULL,
                        label TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO marketplace (pk, code, label)
                    VALUES (1, 'TRENDYOL', 'Trendyol')
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE logistics_cargo_provider (
                        pk INTEGER PRIMARY KEY,
                        platform_id INTEGER,
                        platformCode TEXT NOT NULL,
                        cargoProviderCode TEXT NOT NULL,
                        cargoProviderName TEXT NOT NULL,
                        logoPath TEXT,
                        note TEXT,
                        createdAt TEXT,
                        updatedAt TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO logistics_cargo_provider (
                        pk,
                        platform_id,
                        platformCode,
                        cargoProviderCode,
                        cargoProviderName,
                        createdAt,
                        updatedAt
                    )
                    VALUES (
                        7,
                        1,
                        'TRENDYOL',
                        'TEXMP',
                        'Trendyol Express Marketplace',
                        '2026-04-10T10:00:00',
                        '2026-04-10T10:00:00'
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE cargo_tariff (
                        pk INTEGER PRIMARY KEY,
                        tariffKey TEXT NOT NULL,
                        name TEXT,
                        description TEXT,
                        platform TEXT,
                        cargoProviderCode TEXT,
                        cargoProviderName TEXT,
                        minDesi REAL,
                        maxDesi REAL,
                        minSalePrice REAL,
                        maxSalePrice REAL,
                        amount REAL,
                        currency TEXT,
                        isVatIncluded BOOLEAN,
                        vatRate REAL,
                        isActive BOOLEAN,
                        isDeleted BOOLEAN,
                        createdAt TEXT,
                        updatedAt TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO cargo_tariff (
                        pk,
                        tariffKey,
                        name,
                        description,
                        platform,
                        cargoProviderCode,
                        cargoProviderName,
                        minDesi,
                        maxDesi,
                        minSalePrice,
                        maxSalePrice,
                        amount,
                        currency,
                        isVatIncluded,
                        vatRate,
                        isActive,
                        isDeleted,
                        createdAt,
                        updatedAt
                    )
                    VALUES (
                        101,
                        'trendyol-express-0-5-desi',
                        'Trendyol Express 0-5 Desi',
                        'Legacy tarif kaydi',
                        'TRENDYOL',
                        'TEXMP',
                        'Trendyol Express Marketplace',
                        0,
                        5,
                        0,
                        300,
                        54.9,
                        'TRY',
                        0,
                        20,
                        1,
                        0,
                        '2026-04-10T10:00:00',
                        '2026-04-10T10:00:00'
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)

            self.assertIn("logistics_0002_add_cargo_tariff_provider_fk", applied)
            self.assertTrue(
                table_has_foreign_key(
                    conn,
                    table_name="cargo_tariff",
                    from_column="cargo_provider_id",
                    target_table="logistics_cargo_provider",
                    target_column="pk",
                )
            )
            row = conn.execute(
                text("SELECT cargo_provider_id FROM cargo_tariff WHERE pk = 101")
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0] or 0), 7)
