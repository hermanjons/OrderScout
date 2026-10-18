from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from Core.db.migration_ops import rebuild_table, table_columns


class TestMigrationOps(unittest.TestCase):
    def test_rebuild_table_copies_rows_and_recreates_indexes(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sample (
                        id INTEGER PRIMARY KEY,
                        legacy_name TEXT NOT NULL,
                        legacy_value INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sample (id, legacy_name, legacy_value)
                    VALUES (1, 'demo', 5)
                    """
                )
            )

            rebuild_table(
                conn,
                table_name="sample",
                old_suffix="__legacy",
                create_sql="""
                CREATE TABLE sample (
                    id INTEGER PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    amount INTEGER
                )
                """,
                insert_sql="""
                INSERT INTO sample (id, display_name, amount)
                VALUES (:id, :display_name, :amount)
                """,
                row_mapper=lambda row: {
                    "id": row.get("id"),
                    "display_name": row.get("legacy_name"),
                    "amount": row.get("legacy_value"),
                },
                indexes_sql=[
                    "CREATE INDEX IF NOT EXISTS ix_sample_display_name ON sample(display_name)"
                ],
            )

            cols = table_columns(conn, "sample")
            row = conn.execute(text("SELECT display_name, amount FROM sample WHERE id = 1")).fetchone()
            indexes = conn.execute(text("PRAGMA index_list(sample)")).fetchall()
            index_names = {str(item[1]) for item in indexes}

            self.assertIn("display_name", cols)
            self.assertIn("amount", cols)
            self.assertNotIn("legacy_name", cols)
            self.assertNotIn("legacy_value", cols)
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "demo")
            self.assertEqual(int(row[1]), 5)
            self.assertIn("ix_sample_display_name", index_names)


if __name__ == "__main__":
    unittest.main()
