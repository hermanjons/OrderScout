from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from Core.db.migration_runner import (
    DomainMigration,
    applied_migration_ids,
    discover_domain_migrations,
    pending_domain_migrations,
    run_domain_migrations,
)


class TestDomainMigrationRunner(unittest.TestCase):
    def test_discovery_finds_account_domain_migrations(self) -> None:
        migration_ids = {migration.migration_id for migration in discover_domain_migrations()}
        self.assertIn("account_0001_apiaccount_identity_columns", migration_ids)
        self.assertIn("orders_trendyol_0001_rehome_order_header", migration_ids)
        self.assertIn("stock_0001_stock_item_custom_label", migration_ids)

    def test_runner_applies_each_migration_once(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        call_counter = {"count": 0}

        def _apply(conn) -> None:
            call_counter["count"] += 1
            conn.execute(text("CREATE TABLE IF NOT EXISTS migration_probe (id INTEGER PRIMARY KEY)"))

        migration = DomainMigration(
            migration_id="account_9999_probe",
            domain="account",
            description="probe",
            apply=_apply,
        )

        with engine.begin() as conn:
            first_run = run_domain_migrations(conn, migrations=[migration])
            second_run = run_domain_migrations(conn, migrations=[migration])

            self.assertEqual(first_run, ["account_9999_probe"])
            self.assertEqual(second_run, [])
            self.assertEqual(call_counter["count"], 1)
            self.assertIn("account_9999_probe", applied_migration_ids(conn))

    def test_runner_persists_audit_columns_on_applied_migrations(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        migration = DomainMigration(
            migration_id="account_9998_audit_probe",
            domain="account",
            description="audit probe",
            apply=lambda conn: None,
        )

        with engine.begin() as conn:
            run_domain_migrations(conn, migrations=[migration])

            cols = conn.execute(text("PRAGMA table_info(applied_migrations)")).fetchall()
            col_names = {str(row[1]) for row in cols}
            row = conn.execute(
                text(
                    """
                    SELECT applied_at, created_at, updated_at
                    FROM applied_migrations
                    WHERE migration_id = :migration_id
                    """
                ),
                {"migration_id": migration.migration_id},
            ).fetchone()

        self.assertIn("created_at", col_names)
        self.assertIn("updated_at", col_names)
        self.assertIsNotNone(row)
        self.assertEqual(str(row[0]), str(row[1]))
        self.assertEqual(str(row[0]), str(row[2]))

    def test_pending_domain_migrations_excludes_applied_entries(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        migration = DomainMigration(
            migration_id="account_9998_pending_probe",
            domain="account",
            description="probe",
            apply=lambda conn: None,
        )

        with engine.begin() as conn:
            self.assertEqual(
                [item.migration_id for item in pending_domain_migrations(conn, migrations=[migration])],
                ["account_9998_pending_probe"],
            )
            run_domain_migrations(conn, migrations=[migration])
            self.assertEqual(pending_domain_migrations(conn, migrations=[migration]), [])


if __name__ == "__main__":
    unittest.main()
