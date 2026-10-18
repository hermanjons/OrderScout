from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

import Core.db.migrator as migrator


class TestMigrator(unittest.TestCase):
    def setUp(self) -> None:
        migrator.clear_registered_tables()

    def tearDown(self) -> None:
        migrator.clear_registered_tables()

    def test_run_auto_migrations_can_rename_and_add_columns(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE sample (id INTEGER PRIMARY KEY, old_name TEXT)"))

            migrator.register_table(
                migrator.TableSpec(
                    name="sample",
                    rename_columns={"old_name": "new_name"},
                    columns={"extra_col": "INTEGER DEFAULT 0"},
                    indexes_sql=["CREATE INDEX IF NOT EXISTS ix_sample_new_name ON sample(new_name)"],
                )
            )
            migrator.run_auto_migrations(conn)

            cols = conn.execute(text("PRAGMA table_info(sample)")).fetchall()
            col_names = {str(row[1]) for row in cols}
            self.assertIn("new_name", col_names)
            self.assertIn("extra_col", col_names)
            self.assertNotIn("old_name", col_names)

            idx_rows = conn.execute(text("PRAGMA index_list(sample)")).fetchall()
            idx_names = {str(row[1]) for row in idx_rows}
            self.assertIn("ix_sample_new_name", idx_names)


if __name__ == "__main__":
    unittest.main()
