from __future__ import annotations

import unittest
from typing import Optional

from sqlalchemy import create_engine, text
from sqlmodel import Field, SQLModel

from Core.db.migration_builders import (
    build_backfill_migration,
    build_copy_columns_migration,
    build_model_rebuild_migration,
    build_rehome_table_migration,
    build_replace_columns_migration,
    make_row_mapper,
    should_run_when_columns_need_replacement,
)
from Core.db.migration_runner import run_domain_migrations
from Core.db.migration_validators import assert_columns_absent, assert_columns_exist


class SampleRebuildModel(SQLModel, table=True):
    __tablename__ = "sample_builder_table"

    id: Optional[int] = Field(default=None, primary_key=True)
    display_name: str
    amount: Optional[int] = None


class SampleRehomeModel(SQLModel, table=True):
    __tablename__ = "sample_rehome_target"

    id: Optional[int] = Field(default=None, primary_key=True)
    display_name: str
    amount: Optional[int] = None


class TestMigrationBuilders(unittest.TestCase):
    def test_rehome_table_builder_moves_legacy_rows_to_new_table_name(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        migration = build_rehome_table_migration(
            migration_id="core_0005_sample_rehome",
            domain="core",
            description="sample rehome",
            old_table_name="sample_rehome_legacy",
            new_table_name=SampleRehomeModel.__table__.name,
            model=SampleRehomeModel,
            source_aliases={"display_name": ("display_name", "legacy_name"), "amount": "legacy_value"},
            required_non_blank=["display_name"],
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sample_rehome_legacy (
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
                    INSERT INTO sample_rehome_legacy (id, legacy_name, legacy_value)
                    VALUES (1, 'demo', 21)
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=[migration])
            row = conn.execute(
                text("SELECT display_name, amount FROM sample_rehome_target WHERE id = 1")
            ).fetchone()
            old_exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='sample_rehome_legacy'")
            ).fetchone()

            self.assertEqual(applied, ["core_0005_sample_rehome"])
            self.assertIsNone(old_exists)
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "demo")
            self.assertEqual(int(row[1]), 21)

    def test_copy_columns_builder_backfills_existing_table_in_place(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        migration = build_copy_columns_migration(
            migration_id="core_0003_sample_copy",
            domain="core",
            description="sample copy",
            table_name="sample_builder_table",
            replacements={"display_name": "legacy_name", "amount": "legacy_value"},
            required_non_blank=["display_name"],
            copy_when_blank=["display_name"],
            column_defs={"display_name": "TEXT", "amount": "INTEGER"},
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sample_builder_table (
                        id INTEGER PRIMARY KEY,
                        legacy_name TEXT NOT NULL,
                        legacy_value INTEGER,
                        display_name TEXT,
                        amount INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sample_builder_table (id, legacy_name, legacy_value, display_name, amount)
                    VALUES (1, 'demo', 11, '', NULL)
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=[migration])
            row = conn.execute(
                text("SELECT display_name, amount FROM sample_builder_table WHERE id = 1")
            ).fetchone()

            self.assertEqual(applied, ["core_0003_sample_copy"])
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "demo")
            self.assertEqual(int(row[1]), 11)

    def test_backfill_builder_runs_sql_and_validates(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        migration = build_backfill_migration(
            migration_id="core_0004_sample_backfill",
            domain="core",
            description="sample backfill",
            should_run=lambda conn: True,
            apply_sql=lambda conn: conn.execute(
                text("UPDATE sample_builder_table SET amount = 15 WHERE id = 1")
            ),
            validators=[
                lambda conn: self.assertEqual(
                    conn.execute(text("SELECT amount FROM sample_builder_table WHERE id = 1")).fetchone()[0],
                    15,
                )
            ],
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sample_builder_table (
                        id INTEGER PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        amount INTEGER
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sample_builder_table (id, display_name, amount)
                    VALUES (1, 'demo', NULL)
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=[migration])
            row = conn.execute(text("SELECT amount FROM sample_builder_table WHERE id = 1")).fetchone()

            self.assertEqual(applied, ["core_0004_sample_backfill"])
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 15)

    def test_replace_columns_builder_creates_declarative_migration(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        migration = build_replace_columns_migration(
            migration_id="core_0002_sample_replace",
            domain="core",
            description="sample replace",
            table_name="sample_builder_table",
            model=SampleRebuildModel,
            replacements={"display_name": ("display_name", "legacy_name")},
            required_non_blank=["display_name"],
            defaults={"amount": lambda row: row.get("legacy_value")},
            old_suffix="__replace_old",
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sample_builder_table (
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
                    INSERT INTO sample_builder_table (id, legacy_name, legacy_value)
                    VALUES (1, 'demo', 9)
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=[migration])
            row = conn.execute(
                text("SELECT display_name, amount FROM sample_builder_table WHERE id = 1")
            ).fetchone()

            self.assertEqual(applied, ["core_0002_sample_replace"])
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "demo")
            self.assertEqual(int(row[1]), 9)

    def test_builder_creates_rebuild_migration_from_model_metadata(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        migration = build_model_rebuild_migration(
            migration_id="core_0001_sample_builder",
            domain="core",
            description="sample",
            table_name="sample_builder_table",
            model=SampleRebuildModel,
            should_run=lambda conn: should_run_when_columns_need_replacement(
                conn,
                table_name="sample_builder_table",
                replacements={"display_name": ("display_name", "legacy_name")},
            ),
            row_mapper=make_row_mapper(
                target_columns=[str(column.name) for column in SampleRebuildModel.__table__.columns],
                source_aliases={"display_name": ("display_name", "legacy_name"), "amount": "legacy_value"},
            ),
            validators=[
                lambda conn: assert_columns_exist(conn, "sample_builder_table", ["display_name", "amount"]),
                lambda conn: assert_columns_absent(conn, "sample_builder_table", ["legacy_name", "legacy_value"]),
            ],
            old_suffix="__builder_old",
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sample_builder_table (
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
                    INSERT INTO sample_builder_table (id, legacy_name, legacy_value)
                    VALUES (1, 'demo', 7)
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=[migration])
            row = conn.execute(
                text("SELECT display_name, amount FROM sample_builder_table WHERE id = 1")
            ).fetchone()

            self.assertEqual(applied, ["core_0001_sample_builder"])
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "demo")
            self.assertEqual(int(row[1]), 7)


if __name__ == "__main__":
    unittest.main()
