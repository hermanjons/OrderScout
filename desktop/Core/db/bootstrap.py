# Core/db/bootstrap.py
import datetime
import json
from typing import Iterable, Optional

from sqlmodel import SQLModel
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from Core.utils.model_utils import clear_engine_cache, get_engine
from Core.constants.db_constants import (
    SOURCE_IDENTITY_BACKFILL_KEYS,
    SOURCE_IDENTITY_COLUMNS,
    SOURCE_IDENTITY_PK_COLUMNS,
    SOURCE_IDENTITY_PK_RENAME_TABLES,
    SOURCE_IDENTITY_TABLES,
)
from Core.db.models import (
    backfill_source_identity_row,
    build_source_id,
    coerce_source_id,
)
from settings import DB_NAME
from Core.db.migrator import TableSpec, register_table, run_auto_migrations
from Core.db.migration_runner import DomainMigration, pending_domain_migrations, run_domain_migrations

def _format_default_sql(value) -> Optional[str]:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _now_utc_naive() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _compile_sqlite_column_type(column) -> str:
    try:
        return str(column.type.compile(dialect=sqlite_dialect())).strip() or "TEXT"
    except Exception:
        return "TEXT"


def _register_model_column_migrations() -> None:
    """
    Register additive column migrations from SQLModel metadata.
    This keeps existing user DBs schema-compatible when new model fields are added.
    """
    from Core.db import model_registry  # noqa: F401

    for table in SQLModel.metadata.sorted_tables:
        columns: dict[str, str] = {}
        for column in table.columns:
            if bool(getattr(column, "primary_key", False)):
                continue

            col_type = _compile_sqlite_column_type(column)
            col_def = col_type

            default_clause = None
            default_obj = getattr(column, "default", None)
            if default_obj is not None and bool(getattr(default_obj, "is_scalar", False)):
                default_clause = _format_default_sql(getattr(default_obj, "arg", None))
            elif getattr(column, "server_default", None) is not None:
                server_arg = getattr(column.server_default, "arg", None)
                server_sql = str(server_arg).strip() if server_arg is not None else ""
                if server_sql:
                    default_clause = server_sql

            if default_clause is not None:
                col_def = f"{col_type} DEFAULT {default_clause}"

            columns[column.name] = col_def

        if columns:
            register_table(TableSpec(name=table.name, columns=columns))


def _register_auto_migrations() -> None:
    _register_model_column_migrations()
    _register_source_identity_migrations()
    _register_sync_ready_migrations()


def _register_source_identity_migrations() -> None:
    for table_name in SOURCE_IDENTITY_TABLES:
        register_table(
            TableSpec(
                name=table_name,
                columns=SOURCE_IDENTITY_COLUMNS,
                indexes_sql=[
                    f"CREATE INDEX IF NOT EXISTS ix_{table_name}_sourceType ON {table_name}(sourceType);",
                    f"CREATE INDEX IF NOT EXISTS ix_{table_name}_sourceId ON {table_name}(sourceId);",
                    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table_name}_source_identity ON {table_name}(sourceType, sourceId);",
                ],
            )
        )

    for table_name in SOURCE_IDENTITY_PK_RENAME_TABLES:
        register_table(
            TableSpec(
                name=table_name,
                rename_columns={"id": "pk"},
            )
        )


def _register_sync_ready_migrations() -> None:
    register_table(TableSpec(
        name="sync_outbox",
        create_sql="""
            CREATE TABLE IF NOT EXISTS sync_outbox (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                table_name TEXT NOT NULL,
                record_sync_uuid TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );
        """,
        columns={
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
        indexes_sql=[
            "CREATE INDEX IF NOT EXISTS ix_sync_outbox_status_created ON sync_outbox(status, created_at);",
            "CREATE INDEX IF NOT EXISTS ix_sync_outbox_record ON sync_outbox(table_name, record_sync_uuid);",
        ],
    ))

    register_table(TableSpec(
        name="sync_state",
        create_sql="""
            CREATE TABLE IF NOT EXISTS sync_state (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                state_key TEXT NOT NULL UNIQUE,
                state_value TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """,
        columns={
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
        indexes_sql=[
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_sync_state_key ON sync_state(state_key);",
        ],
    ))

    register_table(TableSpec(
        name="sync_change_log",
        create_sql="""
            CREATE TABLE IF NOT EXISTS sync_change_log (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                table_name TEXT NOT NULL,
                record_sync_uuid TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """,
        columns={
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
        indexes_sql=[
            "CREATE INDEX IF NOT EXISTS ix_sync_change_log_created ON sync_change_log(created_at);",
            "CREATE INDEX IF NOT EXISTS ix_sync_change_log_record ON sync_change_log(table_name, record_sync_uuid);",
        ],
    ))


def _coalesce_timestamp_expr(columns: set[str], candidates: tuple[str, ...], fallback: str) -> str:
    parts = [
        f"NULLIF(TRIM(CAST({name} AS TEXT)), '')"
        for name in candidates
        if name in columns
    ]
    escaped_fallback = fallback.replace("'", "''")
    parts.append(f"'{escaped_fallback}'")
    return "COALESCE(" + ", ".join(parts) + ")"


def _backfill_timestamp_columns(
    conn,
    *,
    table_name: str,
    created_candidates: tuple[str, ...],
    updated_candidates: tuple[str, ...],
) -> None:
    if not _table_exists(conn, table_name):
        return

    cols = _table_columns(conn, table_name)
    if "created_at" not in cols and "updated_at" not in cols:
        return

    now_iso = _now_iso_text()
    set_parts: list[str] = []
    where_parts: list[str] = []

    if "created_at" in cols:
        set_parts.append(
            f"created_at = {_coalesce_timestamp_expr(cols, created_candidates, now_iso)}"
        )
        where_parts.append(
            "(created_at IS NULL OR TRIM(CAST(created_at AS TEXT)) = '')"
        )
    if "updated_at" in cols:
        set_parts.append(
            f"updated_at = {_coalesce_timestamp_expr(cols, updated_candidates, now_iso)}"
        )
        where_parts.append(
            "(updated_at IS NULL OR TRIM(CAST(updated_at AS TEXT)) = '')"
        )

    if not set_parts:
        return

    conn.exec_driver_sql(
        f"UPDATE {table_name} SET {', '.join(set_parts)} WHERE {' OR '.join(where_parts)}"
    )


def _backfill_audit_timestamps(conn) -> None:
    for table_name in SOURCE_IDENTITY_TABLES:
        _backfill_timestamp_columns(
            conn,
            table_name=table_name,
            created_candidates=("created_at", "createdAt", "updated_at", "updatedAt"),
            updated_candidates=("updated_at", "updatedAt", "created_at", "createdAt"),
        )


def _backfill_system_audit_timestamps(conn) -> None:
    for table_name in ("sync_outbox", "sync_state", "sync_change_log"):
        _backfill_timestamp_columns(
            conn,
            table_name=table_name,
            created_candidates=("created_at", "updated_at"),
            updated_candidates=("updated_at", "created_at"),
        )


def _table_exists(conn, table_name: str) -> bool:
    cache = _schema_cache(conn)
    tables = cache.get("tables")
    if tables is None:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {str(row[0]) for row in rows}
        cache["tables"] = tables
    return str(table_name or "") in tables


def _table_columns(conn, table_name: str) -> set[str]:
    cache = _schema_cache(conn)
    columns_cache = cache.setdefault("columns", {})
    cached = columns_cache.get(table_name)
    if cached is not None:
        return set(cached)
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name});").fetchall()
    columns = frozenset(str(r[1]) for r in rows)
    columns_cache[table_name] = columns
    return set(columns)


def _schema_cache(conn) -> dict:
    return conn.info.setdefault("_orderscout_bootstrap_schema", {})


def _clear_schema_cache(conn) -> None:
    conn.info.pop("_orderscout_bootstrap_schema", None)


def _backfill_sync_columns(conn) -> None:
    now_iso = _now_iso_text()
    default_source = "desktop-local"

    for table_name in (
        "apiaccount",
        "financetransaction",
        "financecargoinvoiceitem",
        "trendyol_finance_transaction",
        "trendyol_finance_cargo_invoice_item",
        "finance_invoice_document",
        "finance_manual_transaction",
        "trendyol_order_header",
        "trendyol_order_data",
        "trendyol_order_item",
        "trendyol_return_claim",
        "trendyol_listing_product",
        "trendyol_listing_product_item",
        "trendyol_listing_product_history",
        "stock_item",
        "stock_tx",
        "company",
        "brand",
        "warehouse",
        "license_state",
        "license_action_log",
    ):
        if not _table_exists(conn, table_name):
            continue

        cols = _table_columns(conn, table_name)
        if "sync_uuid" not in cols:
            continue
        pk_name = "pk" if "pk" in cols else "id" if "id" in cols else None
        if not pk_name:
            continue

        if "sync_updated_at" in cols:
            if "created_at" in cols:
                conn.exec_driver_sql(
                    f"""
                    UPDATE {table_name}
                    SET sync_updated_at = COALESCE(sync_updated_at, created_at, ?)
                    WHERE sync_updated_at IS NULL
                    """,
                    (now_iso,),
                )
            else:
                conn.exec_driver_sql(
                    f"""
                    UPDATE {table_name}
                    SET sync_updated_at = COALESCE(sync_updated_at, ?)
                    WHERE sync_updated_at IS NULL
                    """,
                    (now_iso,),
                )

        if "sync_source_device" in cols:
            conn.exec_driver_sql(
                f"""
                UPDATE {table_name}
                SET sync_source_device = COALESCE(sync_source_device, ?)
                WHERE sync_source_device IS NULL OR sync_source_device = ''
                """,
                (default_source,),
            )

        if "sync_version" in cols:
            conn.exec_driver_sql(
                f"""
                UPDATE {table_name}
                SET sync_version = COALESCE(sync_version, 1)
                WHERE sync_version IS NULL
                """
            )

        assignments = ["sync_uuid = lower(hex(randomblob(16)))"]
        params: list[object] = []
        if "sync_updated_at" in cols:
            assignments.append("sync_updated_at = COALESCE(sync_updated_at, ?)")
            params.append(now_iso)
        if "sync_source_device" in cols:
            assignments.append("sync_source_device = COALESCE(sync_source_device, ?)")
            params.append(default_source)
        if "sync_version" in cols:
            assignments.append("sync_version = COALESCE(sync_version, 1)")
        conn.exec_driver_sql(
            f"""
            UPDATE {table_name}
            SET {', '.join(assignments)}
            WHERE sync_uuid IS NULL OR sync_uuid = ''
            """,
            tuple(params),
        )


def _backfill_source_identity(conn) -> None:
    for table_name in SOURCE_IDENTITY_TABLES:
        if not _table_exists(conn, table_name):
            continue

        cols = _table_columns(conn, table_name)
        if "sourceType" not in cols or "sourceId" not in cols:
            continue

        pk_name = SOURCE_IDENTITY_PK_COLUMNS.get(table_name)
        if not pk_name or pk_name not in cols:
            continue

        needed_cols = (
            pk_name,
            "sourceType",
            "sourceId",
            "source_id",
            "sync_uuid",
            "isBuiltin",
            *SOURCE_IDENTITY_BACKFILL_KEYS.get(table_name, ()),
        )
        select_columns = []
        seen_columns = set()
        for col_name in needed_cols:
            if col_name in cols and col_name not in seen_columns:
                select_columns.append(col_name)
                seen_columns.add(col_name)
        if pk_name not in seen_columns:
            continue

        rows = conn.exec_driver_sql(
            f"""
            SELECT {', '.join(select_columns)}
            FROM {table_name}
            WHERE sourceType IS NULL
               OR TRIM(COALESCE(sourceType, '')) = ''
               OR sourceId IS NULL
               OR TRIM(CAST(COALESCE(sourceId, '') AS TEXT)) = ''
            """
        ).mappings().all()

        updates = []
        for row in rows:
            payload = dict(row)
            source_type, source_id = backfill_source_identity_row(table_name, payload)
            pk_value = payload.get(pk_name)
            if pk_value in (None, ""):
                continue
            updates.append((source_type, source_id, pk_value))
        if updates:
            conn.exec_driver_sql(
                f"""
                UPDATE {table_name}
                SET sourceType = ?,
                    sourceId = ?
                WHERE {pk_name} = ?
                """,
                updates,
            )


def _now_iso_text() -> str:
    return _now_utc_naive().isoformat()


def _normalize_bool_int(value) -> int:
    return 1 if bool(value) else 0


def _table_has_columns(conn, table_name: str, required: set[str]) -> bool:
    cols = _table_columns(conn, table_name)
    return required.issubset(cols)


def _update_row_if_needed(
    conn,
    table_name: str,
    pk_value,
    updates: dict[str, object],
    *,
    columns: Optional[set[str]] = None,
) -> None:
    cols = columns if columns is not None else _table_columns(conn, table_name)
    filtered = {key: value for key, value in dict(updates or {}).items() if key in cols}
    if not filtered:
        return
    assignments = ", ".join(f"{key} = ?" for key in filtered)
    params = [filtered[key] for key in filtered]
    params.append(pk_value)
    conn.exec_driver_sql(
        f"UPDATE {table_name} SET {assignments} WHERE pk = ?",
        tuple(params),
    )


def _load_builtin_cargo_tariff_records() -> list[dict[str, object]]:
    from Logistics.constants.catalog_constants import default_cargo_tariff_records

    return [dict(row or {}) for row in default_cargo_tariff_records()]


def _reconcile_builtin_source_identity(conn) -> None:
    from Finance.constants.domain_constants import FINANCE_BUILTIN_COST_ITEM_RECORDS
    from Logistics.constants.catalog_constants import builtin_cargo_provider_records
    from Marketplaces.constants.catalog_constants import load_default_marketplaces

    table_columns_cache: dict[str, set[str]] = {}

    def _columns_for(table_name: str) -> set[str]:
        cached = table_columns_cache.get(table_name)
        if cached is None:
            cached = _table_columns(conn, table_name)
            table_columns_cache[table_name] = cached
        return cached

    def _update(
        table_name: str,
        pk_value,
        updates: dict[str, object],
    ) -> None:
        _update_row_if_needed(
            conn,
            table_name,
            pk_value,
            updates,
            columns=_columns_for(table_name),
        )

    builtin_marketplace_rows = [
        dict(row or {})
        for row in load_default_marketplaces()
        if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) is not None
    ]
    builtin_provider_rows = [
        dict(row or {})
        for row in builtin_cargo_provider_records()
        if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) is not None
    ]
    builtin_cost_item_rows = [
        dict(row or {})
        for row in FINANCE_BUILTIN_COST_ITEM_RECORDS
        if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) is not None
    ]
    builtin_cargo_tariff_rows = [
        dict(row or {})
        for row in _load_builtin_cargo_tariff_records()
        if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) is not None
    ]

    builtin_marketplace_by_source_id = {
        coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")): dict(row or {})
        for row in builtin_marketplace_rows
        if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) is not None
    }
    builtin_provider_by_source_id = {
        coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")): dict(row or {})
        for row in builtin_provider_rows
        if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) is not None
    }
    builtin_cost_item_by_source_id = {
        coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")): dict(row or {})
        for row in builtin_cost_item_rows
        if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) is not None
    }
    builtin_cargo_tariff_by_source_id = {
        coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")): dict(row or {})
        for row in builtin_cargo_tariff_rows
        if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) is not None
    }
    builtin_marketplace_by_code = {
        str((row or {}).get("code") or "").strip().upper(): dict(row or {})
        for row in builtin_marketplace_rows
        if str((row or {}).get("code") or "").strip()
    }
    builtin_provider_by_key = {
        (
            str((row or {}).get("platformCode") or "").strip().upper(),
            str((row or {}).get("cargoProviderCode") or "").strip().upper(),
        ): dict(row or {})
        for row in builtin_provider_rows
        if str((row or {}).get("platformCode") or "").strip()
        and str((row or {}).get("cargoProviderCode") or "").strip()
    }
    builtin_cost_item_by_key = {
        str((row or {}).get("costKey") or "").strip().casefold(): dict(row or {})
        for row in builtin_cost_item_rows
        if str((row or {}).get("costKey") or "").strip()
    }
    builtin_cargo_tariff_by_key = {
        str((row or {}).get("tariffKey") or "").strip().casefold(): dict(row or {})
        for row in builtin_cargo_tariff_rows
        if str((row or {}).get("tariffKey") or "").strip()
    }
    now_iso = _now_iso_text()

    if _table_exists(conn, "marketplace"):
        rows = conn.exec_driver_sql("SELECT pk, code, sourceType, sourceId FROM marketplace").mappings().all()
        for row in rows:
            key = str(row.get("code") or "").strip().upper()
            current_source_id = coerce_source_id(row.get("sourceId"))
            target_row = builtin_marketplace_by_source_id.get(current_source_id) or builtin_marketplace_by_code.get(key)
            if target_row is None:
                if str(row.get("sourceType") or "").strip().lower() == "builtin":
                    _update(
                        "marketplace",
                        row.get("pk"),
                        {"sourceType": "builtin", "isActive": 0, "updatedAt": now_iso},
                    )
                continue
            target_source_id = coerce_source_id(target_row.get("sourceId") or target_row.get("source_id"))
            _update(
                "marketplace",
                row.get("pk"),
                {
                    "sourceType": "builtin",
                    "sourceId": target_source_id,
                    "label": str(target_row.get("label") or "").strip(),
                    "description": str(target_row.get("description") or "").strip() or None,
                    "logoPath": str(target_row.get("logoPath") or "").strip() or None,
                    "isActive": _normalize_bool_int(target_row.get("isActive", True)),
                    "updatedAt": now_iso,
                },
            )

    marketplace_pk_by_source_id: dict[int, int] = {}
    if {"pk", "sourceId"}.issubset(_columns_for("marketplace")):
        for row in conn.exec_driver_sql("SELECT pk, sourceId FROM marketplace").mappings().all():
            source_id = coerce_source_id(row.get("sourceId"))
            pk_value = int(row.get("pk") or 0)
            if source_id is not None and pk_value > 0:
                marketplace_pk_by_source_id[source_id] = pk_value

    if _table_exists(conn, "logistics_cargo_provider"):
        rows = conn.exec_driver_sql(
            "SELECT pk, platformCode, cargoProviderCode, sourceType, sourceId FROM logistics_cargo_provider"
        ).mappings().all()
        for row in rows:
            current_source_id = coerce_source_id(row.get("sourceId"))
            key = (
                str(row.get("platformCode") or "").strip().upper(),
                str(row.get("cargoProviderCode") or "").strip().upper(),
            )
            target_row = builtin_provider_by_source_id.get(current_source_id) or builtin_provider_by_key.get(key)
            if target_row is None:
                if str(row.get("sourceType") or "").strip().lower() == "builtin":
                    _update(
                        "logistics_cargo_provider",
                        row.get("pk"),
                        {"sourceType": "builtin", "updatedAt": now_iso},
                    )
                continue
            target_source_id = coerce_source_id(target_row.get("sourceId") or target_row.get("source_id"))
            platform_source_id = coerce_source_id(target_row.get("platformSourceId") or target_row.get("platform_source_id"))
            _update(
                "logistics_cargo_provider",
                row.get("pk"),
                {
                    "sourceType": "builtin",
                    "sourceId": target_source_id,
                    "platform_id": marketplace_pk_by_source_id.get(int(platform_source_id or 0)),
                    "cargoProviderName": str(target_row.get("cargoProviderName") or target_row.get("name") or "").strip() or None,
                    "logoPath": str(target_row.get("logoPath") or "").strip() or None,
                    "note": str(target_row.get("note") or "").strip() or None,
                    "updatedAt": now_iso,
                },
            )

    cargo_provider_pk_by_source_id: dict[int, int] = {}
    if {"pk", "sourceId"}.issubset(_columns_for("logistics_cargo_provider")):
        for row in conn.exec_driver_sql("SELECT pk, sourceId FROM logistics_cargo_provider").mappings().all():
            source_id = coerce_source_id(row.get("sourceId"))
            pk_value = int(row.get("pk") or 0)
            if source_id is not None and pk_value > 0:
                cargo_provider_pk_by_source_id[source_id] = pk_value

    if _table_exists(conn, "cost_item"):
        rows = conn.exec_driver_sql("SELECT pk, costKey, sourceType, sourceId FROM cost_item").mappings().all()
        for row in rows:
            current_source_id = coerce_source_id(row.get("sourceId"))
            key = str(row.get("costKey") or "").strip().casefold()
            target_row = builtin_cost_item_by_source_id.get(current_source_id) or builtin_cost_item_by_key.get(key)
            if target_row is None:
                if str(row.get("sourceType") or "").strip().lower() == "builtin":
                    _update(
                        "cost_item",
                        row.get("pk"),
                        {"sourceType": "builtin", "isActive": 0, "updatedAt": now_iso},
                    )
                continue
            target_source_id = coerce_source_id(target_row.get("sourceId") or target_row.get("source_id"))
            supported_platform_source_ids = [
                int(source_id)
                for source_id in (
                    target_row.get("supportedPlatformSourceIds")
                    or target_row.get("supported_platform_source_ids")
                    or []
                )
                if coerce_source_id(source_id) is not None
            ]
            supported_platform_codes = [
                str(payload.get("code") or "").strip().upper()
                for payload in builtin_marketplace_rows
                if coerce_source_id((payload or {}).get("sourceId") or (payload or {}).get("source_id")) in supported_platform_source_ids
            ]
            _update(
                "cost_item",
                row.get("pk"),
                {
                    "sourceType": "builtin",
                    "sourceId": target_source_id,
                    "name": str(target_row.get("name") or "").strip() or None,
                    "description": str(target_row.get("description") or "").strip() or None,
                    "valueType": str(target_row.get("valueType") or "").strip() or None,
                    "defaultMatchMode": str(target_row.get("defaultMatchMode") or "").strip() or None,
                    "defaultAmount": target_row.get("defaultAmount"),
                    "currency": str(target_row.get("currency") or "TRY").strip() or "TRY",
                    "isVatIncluded": _normalize_bool_int(target_row.get("isVatIncluded", True)),
                    "vatRate": target_row.get("vatRate"),
                    "supportedPlatformsJson": json.dumps(supported_platform_codes, ensure_ascii=False),
                    "supportedPlatformSourceIdsJson": json.dumps(supported_platform_source_ids, ensure_ascii=False),
                    "supportedSourceTypesJson": json.dumps(list(target_row.get("supportedSourceTypes") or []), ensure_ascii=False),
                    "defaultSourceType": str(target_row.get("defaultSourceType") or "").strip() or None,
                    "defaultSourceConfigJson": (
                        json.dumps(dict(target_row.get("defaultSourceConfig") or {}), ensure_ascii=False)
                        if dict(target_row.get("defaultSourceConfig") or {})
                        else None
                    ),
                    "isActive": _normalize_bool_int(target_row.get("isActive", True)),
                    "updatedAt": now_iso,
                },
            )
            if _table_exists(conn, "cost_item_marketplace_link"):
                cost_item_id = int(row.get("pk") or 0)
                link_rows = conn.exec_driver_sql(
                    "SELECT pk, marketplace_id FROM cost_item_marketplace_link WHERE cost_item_id = ?",
                    (cost_item_id,),
                ).mappings().all()
                existing_by_marketplace_id = {
                    int(link_row.get("marketplace_id") or 0): int(link_row.get("pk") or 0)
                    for link_row in link_rows
                    if int(link_row.get("marketplace_id") or 0) > 0 and int(link_row.get("pk") or 0) > 0
                }
                target_marketplace_ids = {
                    int(marketplace_pk_by_source_id[source_id])
                    for source_id in supported_platform_source_ids
                    if int(source_id) in marketplace_pk_by_source_id
                }
                for marketplace_id, link_pk in list(existing_by_marketplace_id.items()):
                    if marketplace_id in target_marketplace_ids:
                        continue
                    conn.exec_driver_sql(
                        "DELETE FROM cost_item_marketplace_link WHERE pk = ?",
                        (link_pk,),
                    )
                for marketplace_id in sorted(target_marketplace_ids):
                    existing_link_pk = existing_by_marketplace_id.get(marketplace_id)
                    link_source_id = build_source_id(
                        "cost_item_marketplace_link",
                        {"cost_item_id": cost_item_id, "marketplace_id": marketplace_id},
                        source_type="builtin",
                    )
                    if existing_link_pk is not None:
                        _update(
                            "cost_item_marketplace_link",
                            existing_link_pk,
                            {
                                "sourceType": "builtin",
                                "sourceId": link_source_id,
                                "updatedAt": now_iso,
                            },
                        )
                        continue
                    link_cols = _columns_for("cost_item_marketplace_link")
                    insert_payload = {
                        "cost_item_id": cost_item_id,
                        "marketplace_id": marketplace_id,
                        "sourceType": "builtin",
                        "sourceId": link_source_id,
                        "createdAt": now_iso,
                        "updatedAt": now_iso,
                        "created_at": now_iso,
                        "updated_at": now_iso,
                        "sync_version": 1,
                    }
                    cols = [name for name in insert_payload if name in link_cols]
                    values = [insert_payload[name] for name in cols]
                    conn.exec_driver_sql(
                        f"INSERT INTO cost_item_marketplace_link ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
                        tuple(values),
                    )

    if _table_exists(conn, "cargo_tariff"):
        rows = conn.exec_driver_sql("SELECT pk, tariffKey, sourceType, sourceId FROM cargo_tariff").mappings().all()
        for row in rows:
            current_source_id = coerce_source_id(row.get("sourceId"))
            key = str(row.get("tariffKey") or "").strip().casefold()
            target_row = builtin_cargo_tariff_by_source_id.get(current_source_id) or builtin_cargo_tariff_by_key.get(key)
            if target_row is None:
                if str(row.get("sourceType") or "").strip().lower() == "builtin":
                    _update(
                        "cargo_tariff",
                        row.get("pk"),
                        {"sourceType": "builtin", "isActive": 0, "updatedAt": now_iso},
                    )
                continue
            target_source_id = coerce_source_id(target_row.get("sourceId") or target_row.get("source_id"))
            provider_source_id = coerce_source_id(target_row.get("cargoProviderSourceId") or target_row.get("cargo_provider_source_id"))
            _update(
                "cargo_tariff",
                row.get("pk"),
                {
                    "sourceType": "builtin",
                    "sourceId": target_source_id,
                    "name": str(target_row.get("name") or "").strip() or None,
                    "description": str(target_row.get("description") or "").strip() or None,
                    "cargo_provider_id": cargo_provider_pk_by_source_id.get(int(provider_source_id or 0)),
                    "cargoProviderCode": str(target_row.get("cargoProviderCode") or "").strip().upper() or None,
                    "cargoProviderName": str(target_row.get("cargoProviderName") or "").strip() or None,
                    "minDesi": target_row.get("minDesi"),
                    "maxDesi": target_row.get("maxDesi"),
                    "minSalePrice": target_row.get("minSalePrice"),
                    "maxSalePrice": target_row.get("maxSalePrice"),
                    "amount": target_row.get("amount"),
                    "currency": str(target_row.get("currency") or "TRY").strip() or "TRY",
                    "isVatIncluded": _normalize_bool_int(target_row.get("isVatIncluded", True)),
                    "vatRate": target_row.get("vatRate"),
                    "isActive": _normalize_bool_int(target_row.get("isActive", True)),
                    "updatedAt": now_iso,
                },
            )


def _ensure_sync_indexes(conn) -> None:
    for table_name in (
        "apiaccount",
        "financetransaction",
        "financecargoinvoiceitem",
        "trendyol_finance_transaction",
        "trendyol_finance_cargo_invoice_item",
        "finance_invoice_document",
        "finance_manual_transaction",
        "trendyol_order_header",
        "trendyol_order_data",
        "trendyol_order_item",
        "trendyol_return_claim",
        "trendyol_listing_product",
        "trendyol_listing_product_item",
        "trendyol_listing_product_history",
        "stock_item",
        "stock_tx",
        "company",
        "brand",
        "warehouse",
        "license_state",
        "license_action_log",
    ):
        if not _table_exists(conn, table_name):
            continue
        cols = _table_columns(conn, table_name)
        if "sync_uuid" in cols:
            conn.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_{table_name}_sync_uuid ON {table_name}(sync_uuid);"
            )
        if "sync_updated_at" in cols:
            conn.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_{table_name}_sync_updated_at ON {table_name}(sync_updated_at);"
            )


def init_database(
    db_name: str = DB_NAME,
    *,
    domain_migrations: Optional[Iterable[DomainMigration]] = None,
) -> None:
    # ✅ modeller metadata'ya dahil olsun
    from Core.db import model_registry  # noqa: F401

    engine = get_engine(db_name)
    SQLModel.metadata.create_all(engine)
    _register_auto_migrations()
    with engine.connect() as conn:
        pending_migrations = pending_domain_migrations(conn, migrations=domain_migrations)

    try:
        with engine.begin() as conn:
            run_auto_migrations(conn)
            _backfill_source_identity(conn)
            run_domain_migrations(conn, migrations=pending_migrations)
            _clear_schema_cache(conn)
            _reconcile_builtin_source_identity(conn)
            _backfill_audit_timestamps(conn)
            _backfill_system_audit_timestamps(conn)
            _backfill_sync_columns(conn)
            _ensure_sync_indexes(conn)
    except Exception:
        try:
            engine.dispose()
        except Exception:
            pass
        clear_engine_cache()
        raise
