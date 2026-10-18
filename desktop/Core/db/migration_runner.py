from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy import text

from Core.db.migration_ops import add_column_if_missing, table_columns, table_exists


@dataclass(frozen=True)
class DomainMigration:
    migration_id: str
    domain: str
    apply: Callable[[object], None]
    description: str = ""


_DISCOVERED_DOMAIN_MIGRATIONS: tuple[DomainMigration, ...] | None = None


def _desktop_root() -> Path:
    return Path(__file__).resolve().parents[2]


def discover_domain_migrations() -> list[DomainMigration]:
    global _DISCOVERED_DOMAIN_MIGRATIONS

    if _DISCOVERED_DOMAIN_MIGRATIONS is not None:
        return list(_DISCOVERED_DOMAIN_MIGRATIONS)

    migrations: list[DomainMigration] = []
    desktop_root = _desktop_root()

    for domain_dir in sorted(desktop_root.iterdir(), key=lambda item: item.name.lower()):
        if not domain_dir.is_dir():
            continue
        models_dir = domain_dir / "models"
        if not models_dir.exists():
            continue
        for migration_file in sorted(models_dir.rglob("migrations.py")):
            if "__pycache__" in migration_file.parts:
                continue
            module_name = ".".join(migration_file.relative_to(desktop_root).with_suffix("").parts)
            module = importlib.import_module(module_name)
            exported = getattr(module, "MIGRATIONS", ())
            for migration in exported:
                if not isinstance(migration, DomainMigration):
                    raise TypeError(f"{module_name}.MIGRATIONS must contain DomainMigration entries.")
                migrations.append(migration)

    _validate_unique_ids(migrations)
    _DISCOVERED_DOMAIN_MIGRATIONS = tuple(
        sorted(migrations, key=lambda item: (item.domain.lower(), item.migration_id))
    )
    return list(_DISCOVERED_DOMAIN_MIGRATIONS)


def _validate_unique_ids(migrations: Iterable[DomainMigration]) -> None:
    seen: set[str] = set()
    for migration in migrations:
        migration_id = str(migration.migration_id or "").strip()
        if not migration_id:
            raise ValueError("Domain migration id cannot be empty.")
        if migration_id in seen:
            raise ValueError(f"Duplicate domain migration id: {migration_id}")
        seen.add(migration_id)


def _ensure_applied_migrations_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS applied_migrations (
                migration_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                description TEXT,
                applied_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_applied_migrations_domain
            ON applied_migrations(domain, applied_at)
            """
        )
    )
    _ensure_applied_migrations_audit_columns(conn)


def _ensure_applied_migrations_audit_columns(conn) -> None:
    if not table_exists(conn, "applied_migrations"):
        return

    existing = table_columns(conn, "applied_migrations")
    if "created_at" not in existing:
        add_column_if_missing(
            conn,
            table_name="applied_migrations",
            column_name="created_at",
            column_sql="TEXT",
        )
    if "updated_at" not in existing:
        add_column_if_missing(
            conn,
            table_name="applied_migrations",
            column_name="updated_at",
            column_sql="TEXT",
        )

    existing = table_columns(conn, "applied_migrations")
    if "applied_at" not in existing:
        return

    conn.execute(
        text(
            """
            UPDATE applied_migrations
            SET created_at = COALESCE(created_at, applied_at),
                updated_at = COALESCE(updated_at, applied_at, created_at)
            WHERE created_at IS NULL OR updated_at IS NULL
            """
        )
    )


def applied_migration_ids(conn) -> set[str]:
    _ensure_applied_migrations_table(conn)
    rows = conn.execute(text("SELECT migration_id FROM applied_migrations")).fetchall()
    return {str(row[0]) for row in rows}


def pending_domain_migrations(
    conn,
    migrations: Iterable[DomainMigration] | None = None,
) -> list[DomainMigration]:
    planned = list(migrations) if migrations is not None else discover_domain_migrations()
    _validate_unique_ids(planned)
    planned.sort(key=lambda item: (item.domain.lower(), item.migration_id))
    already_applied = applied_migration_ids(conn)
    return [migration for migration in planned if migration.migration_id not in already_applied]


def run_domain_migrations(conn, migrations: Iterable[DomainMigration] | None = None) -> list[str]:
    _ensure_applied_migrations_table(conn)

    planned = pending_domain_migrations(conn, migrations=migrations)
    applied_now: list[str] = []

    for migration in planned:
        now_iso = datetime.now(timezone.utc).isoformat()
        migration.apply(conn)
        conn.execute(
            text(
                """
                INSERT INTO applied_migrations (
                    migration_id,
                    domain,
                    description,
                    applied_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    :migration_id,
                    :domain,
                    :description,
                    :applied_at,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "migration_id": migration.migration_id,
                "domain": migration.domain,
                "description": migration.description,
                "applied_at": now_iso,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
        applied_now.append(migration.migration_id)

    return applied_now
