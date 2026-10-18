from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from Core.constants.db_constants import SYNC_READY_EXTRA_COLUMNS
from Core.db.models import backfill_source_identity_row
from Core.db.migration_ops import (
    add_column_if_missing,
    append_rows_to_table,
    backfill_stock_tx_legacy_cost_defaults,
    copy_column_values,
    create_indexes,
    drop_table_if_exists,
    has_rows_missing_stock_tx_legacy_cost_defaults,
    merged_listing_resolution_meta,
    promote_legacy_table,
    quote_ident,
    rebuild_table,
    rehome_table,
    table_columns,
    table_exists,
    table_has_index,
    table_row_count,
)


def _now_iso_text() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
from Core.db.migration_runner import DomainMigration
from Core.db.migration_validators import (
    assert_columns_absent,
    assert_columns_exist,
    assert_non_blank_strings,
)


def _as_source_names(value: str | Sequence[str] | None, target_name: str) -> tuple[str, ...]:
    if value is None:
        return (target_name,)
    if isinstance(value, str):
        return (value,)
    cleaned = tuple(str(item) for item in value if str(item))
    return cleaned or (target_name,)


def make_row_mapper(
    *,
    target_columns: Iterable[str],
    source_aliases: Mapping[str, str | Sequence[str]] | None = None,
    value_resolvers: Mapping[str, Callable[[Mapping[str, object]], object]] | None = None,
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
) -> Callable[[Mapping[str, object]], dict[str, object]]:
    aliases = {str(key): value for key, value in dict(source_aliases or {}).items()}
    resolvers = {str(key): value for key, value in dict(value_resolvers or {}).items()}
    default_map = {str(key): value for key, value in dict(defaults or {}).items()}
    targets = [str(column) for column in target_columns]

    def _resolve_default(column_name: str, row: Mapping[str, object]) -> object:
        default = default_map.get(column_name)
        if callable(default):
            return default(row)
        return default

    def _mapper(row: Mapping[str, object]) -> dict[str, object]:
        mapped: dict[str, object] = {}
        for column_name in targets:
            resolver = resolvers.get(column_name)
            if resolver is not None:
                mapped[column_name] = resolver(row)
                continue

            value = None
            for source_name in _as_source_names(aliases.get(column_name), column_name):
                current = row.get(source_name)
                if current is not None:
                    value = current
                    break

            if value is None and column_name in default_map:
                value = _resolve_default(column_name, row)

            mapped[column_name] = value
        return mapped

    return _mapper


def _model_create_table_sql(model: type[SQLModel]) -> str:
    return str(CreateTable(model.__table__).compile(dialect=sqlite_dialect()))


def build_create_table_with_extra_columns_sql(
    *,
    model: type[SQLModel],
    extra_columns: Mapping[str, str] | None = None,
    excluded_foreign_keys: Iterable[tuple[str, str, str]] = (),
) -> str:
    base_sql = _model_create_table_sql(model).strip()
    extra_defs = [f"{name} {definition}" for name, definition in dict(extra_columns or {}).items()]
    excluded_fk_set = {
        (str(source).strip().lower(), str(target_table).strip().lower(), str(target_column).strip().lower())
        for source, target_table, target_column in (excluded_foreign_keys or ())
    }

    prefix = "CREATE TABLE "
    open_paren = "(\n\t"
    close_paren = "\n)"
    if prefix not in base_sql or open_paren not in base_sql or not base_sql.endswith(close_paren):
        return base_sql

    head, tail = base_sql.split(open_paren, 1)
    inner = tail[: -len(close_paren)]
    defs = inner.split(", \n\t") if inner else []

    filtered_defs: list[str] = []
    for definition in defs:
        stripped = str(definition or "").strip()
        if stripped.startswith("FOREIGN KEY(") and excluded_fk_set:
            try:
                source_part, target_part = stripped.split(" REFERENCES ", 1)
                source_column = source_part[len("FOREIGN KEY(") :].split(")", 1)[0].strip().lower()
                target_table = target_part.split("(", 1)[0].strip().lower()
                target_column = target_part.split("(", 1)[1].split(")", 1)[0].strip().lower()
            except Exception:
                filtered_defs.append(definition)
                continue
            if (source_column, target_table, target_column) in excluded_fk_set:
                continue
        filtered_defs.append(definition)

    if extra_defs:
        constraint_index = next(
            (
                idx
                for idx, definition in enumerate(filtered_defs)
                if str(definition or "").strip().startswith(("PRIMARY KEY", "CONSTRAINT", "FOREIGN KEY"))
            ),
            len(filtered_defs),
        )
        filtered_defs[constraint_index:constraint_index] = extra_defs

    rebuilt_inner = ", \n\t".join(filtered_defs)
    return f"{head}{open_paren}{rebuilt_inner}{close_paren}"


def table_has_foreign_key(
    conn,
    *,
    table_name: str,
    from_column: str,
    target_table: str,
    target_column: str,
) -> bool:
    if not table_exists(conn, table_name):
        return False

    rows = conn.exec_driver_sql(f"PRAGMA foreign_key_list('{table_name}')").fetchall()
    source = str(from_column or "").strip().lower()
    target_tbl = str(target_table or "").strip().lower()
    target_col = str(target_column or "").strip().lower()
    for row in rows:
        if (
            str(row[2] or "").strip().lower() == target_tbl
            and str(row[3] or "").strip().lower() == source
            and str(row[4] or "").strip().lower() == target_col
        ):
            return True
    return False


def make_foreign_key_validator(
    *,
    table_name: str,
    from_column: str,
    target_table: str,
    target_column: str,
) -> Callable[[object], None]:
    def _validate(conn) -> None:
        if not table_has_foreign_key(
            conn,
            table_name=table_name,
            from_column=from_column,
            target_table=target_table,
            target_column=target_column,
        ):
            raise ValueError(
                f"{table_name}.{from_column} foreign key to {target_table}.{target_column} is missing."
            )

    return _validate


def make_name_foreign_key_row_mapper(
    conn,
    *,
    target_columns: Iterable[str],
    name_fk_specs: Mapping[str, Mapping[str, str]],
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    lookup_maps: dict[str, dict[str, int]] = {}
    normalized_specs: dict[str, dict[str, str]] = {}

    for target_column, raw_spec in dict(name_fk_specs or {}).items():
        spec = {str(key): str(value) for key, value in dict(raw_spec or {}).items()}
        normalized_specs[str(target_column)] = spec
        table_name = spec.get("lookup_table", "")
        id_column = spec.get("lookup_id", "id")
        name_column = spec.get("lookup_name", "name")

        rows_map: dict[str, int] = {}
        if table_name and table_exists(conn, table_name):
            rows = conn.exec_driver_sql(
                f"SELECT {quote_ident(id_column)}, {quote_ident(name_column)} FROM {quote_ident(table_name)}"
            ).fetchall()
            for row in rows:
                try:
                    pk = int(row[0])
                except Exception:
                    continue
                name_text = str(row[1] or "").strip().casefold()
                if pk > 0 and name_text:
                    rows_map[name_text] = pk
        lookup_maps[str(target_column)] = rows_map

    base_mapper = make_row_mapper(
        target_columns=target_columns,
        defaults=defaults,
    )

    def _mapper(row: Mapping[str, object]) -> Mapping[str, object]:
        mapped = dict(base_mapper(row))
        for target_column, spec in normalized_specs.items():
            if mapped.get(target_column) not in (None, ""):
                continue
            source_column = spec.get("source_column", "")
            source_value = str(row.get(source_column) or "").strip()
            if not source_value:
                continue
            mapped[target_column] = lookup_maps.get(target_column, {}).get(source_value.casefold())
        return mapped

    return _mapper


def _wrap_source_identity_row_mapper(
    *,
    table_name: str,
    target_columns: Iterable[str],
    row_mapper: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    target_set = {str(column) for column in target_columns}
    if "sourceType" not in target_set and "sourceId" not in target_set:
        return row_mapper

    def _mapper(row: Mapping[str, object]) -> Mapping[str, object]:
        mapped = dict(row_mapper(row))
        source_type, source_id = backfill_source_identity_row(table_name, mapped)
        if "sourceType" in target_set:
            mapped["sourceType"] = source_type
        if "sourceId" in target_set:
            mapped["sourceId"] = source_id
        return mapped

    return _mapper


def _wrap_audit_timestamp_row_mapper(
    *,
    target_columns: Iterable[str],
    row_mapper: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    target_set = {str(column) for column in target_columns}
    audit_names = {"created_at", "updated_at", "createdAt", "updatedAt"}
    if not (target_set & audit_names):
        return row_mapper

    def _first_non_empty(*values: object) -> object:
        for value in values:
            if value not in (None, ""):
                return value
        return None

    def _mapper(row: Mapping[str, object]) -> Mapping[str, object]:
        mapped = dict(row_mapper(row))
        now_iso = _now_iso_text()
        created_at = _first_non_empty(
            mapped.get("created_at"),
            mapped.get("createdAt"),
            row.get("created_at"),
            row.get("createdAt"),
            row.get("updated_at"),
            row.get("updatedAt"),
            now_iso,
        )
        updated_at = _first_non_empty(
            mapped.get("updated_at"),
            mapped.get("updatedAt"),
            row.get("updated_at"),
            row.get("updatedAt"),
            created_at,
            now_iso,
        )

        if "created_at" in target_set and created_at not in (None, ""):
            mapped["created_at"] = created_at
        if "updated_at" in target_set and updated_at not in (None, ""):
            mapped["updated_at"] = updated_at
        if "createdAt" in target_set and created_at not in (None, ""):
            mapped["createdAt"] = created_at
        if "updatedAt" in target_set and updated_at not in (None, ""):
            mapped["updatedAt"] = updated_at
        return mapped

    return _mapper


def _normalize_lookup_value(value: object) -> object:
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def make_lookup_foreign_key_row_mapper(
    conn,
    *,
    target_columns: Iterable[str],
    target_fk_column: str,
    lookup_table: str,
    lookup_id_column: str,
    source_columns: Sequence[str],
    lookup_columns: Sequence[str],
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    lookup_map: dict[tuple[object, ...], int] = {}
    if table_exists(conn, lookup_table):
        select_columns = [lookup_id_column, *lookup_columns]
        sql = ", ".join(quote_ident(column_name) for column_name in select_columns)
        rows = conn.exec_driver_sql(f"SELECT {sql} FROM {quote_ident(lookup_table)}").fetchall()
        for row in rows:
            try:
                lookup_id = int(row[0])
            except Exception:
                continue
            lookup_key = tuple(_normalize_lookup_value(value) for value in row[1:])
            if lookup_id > 0 and all(value not in (None, "") for value in lookup_key):
                lookup_map[lookup_key] = lookup_id

    base_mapper = make_row_mapper(
        target_columns=target_columns,
        defaults=defaults,
    )

    def _mapper(row: Mapping[str, object]) -> Mapping[str, object]:
        mapped = dict(base_mapper(row))
        if mapped.get(target_fk_column) not in (None, ""):
            return mapped

        lookup_key = tuple(_normalize_lookup_value(row.get(column_name)) for column_name in source_columns)
        if all(value not in (None, "") for value in lookup_key):
            mapped[target_fk_column] = lookup_map.get(lookup_key)
        return mapped

    return _mapper


def _format_default_sql(value: object) -> str | None:
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


def _compile_column_definition(column) -> str:
    col_type = str(column.type.compile(dialect=sqlite_dialect())).strip() or "TEXT"
    parts = [str(column.name), col_type]

    if bool(getattr(column, "primary_key", False)):
        parts.append("PRIMARY KEY")
    if not bool(getattr(column, "nullable", True)):
        parts.append("NOT NULL")

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
        parts.append(f"DEFAULT {default_clause}")

    return " ".join(parts)


def build_create_table_sql(
    *,
    table_name: str,
    model: type[SQLModel],
    extra_columns: Mapping[str, str] | None = None,
) -> str:
    column_defs = [_compile_column_definition(column) for column in model.__table__.columns]
    for column_name, definition in dict(extra_columns or {}).items():
        column_defs.append(f"{column_name} {definition}")
    joined = ",\n    ".join(column_defs)
    return f"CREATE TABLE {table_name} (\n    {joined}\n)"


def _model_indexes_sql(model: type[SQLModel]) -> list[str]:
    return [
        str(CreateIndex(index).compile(dialect=sqlite_dialect()))
        for index in model.__table__.indexes
    ]


def _model_insert_sql(table_name: str, columns: Iterable[str]) -> str:
    names = [str(column) for column in columns]
    insert_columns = ", ".join(names)
    insert_values = ", ".join(f":{name}" for name in names)
    return f"INSERT INTO {table_name} ({insert_columns}) VALUES ({insert_values})"


def build_target_columns(
    *,
    model: type[SQLModel],
    extra_columns: Mapping[str, str] | None = None,
) -> list[str]:
    return [str(column.name) for column in model.__table__.columns] + [
        str(column_name) for column_name in dict(extra_columns or {}).keys()
    ]


def build_model_rebuild_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
    model: type[SQLModel],
    should_run: Callable[[object], bool],
    row_mapper: Callable[[Mapping[str, object]], Mapping[str, object]],
    row_mapper_factory: Callable[[object], Callable[[Mapping[str, object]], Mapping[str, object]]] | None = None,
    validators: Iterable[Callable[[object], None]] = (),
    old_suffix: str = "__old",
    create_sql: str | None = None,
    indexes_sql: Iterable[str] | None = None,
    target_columns: Iterable[str] | None = None,
) -> DomainMigration:
    column_names = [str(column) for column in (target_columns or [column.name for column in model.__table__.columns])]
    create_table_sql = str(create_sql or _model_create_table_sql(model))
    insert_sql = _model_insert_sql(table_name, column_names)
    create_index_sql = list(indexes_sql or _model_indexes_sql(model))
    validator_list = list(validators or ())

    def _apply(conn) -> None:
        if not table_exists(conn, table_name):
            return
        if not bool(should_run(conn)):
            return
        effective_row_mapper = row_mapper_factory(conn) if row_mapper_factory is not None else row_mapper
        effective_row_mapper = _wrap_source_identity_row_mapper(
            table_name=table_name,
            target_columns=column_names,
            row_mapper=effective_row_mapper,
        )
        effective_row_mapper = _wrap_audit_timestamp_row_mapper(
            target_columns=column_names,
            row_mapper=effective_row_mapper,
        )

        rebuild_table(
            conn,
            table_name=table_name,
            create_sql=create_table_sql,
            insert_sql=insert_sql,
            row_mapper=effective_row_mapper,
            indexes_sql=create_index_sql,
            old_suffix=old_suffix,
            validate=lambda run_conn: [validator(run_conn) for validator in validator_list],
        )

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )


def build_rehome_table_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    old_table_name: str,
    new_table_name: str,
    model: type[SQLModel],
    source_aliases: Mapping[str, str | Sequence[str]] | None = None,
    value_resolvers: Mapping[str, Callable[[Mapping[str, object]], object]] | None = None,
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
    row_mapper_factory: Callable[[object], Callable[[Mapping[str, object]], Mapping[str, object]]] | None = None,
    extra_columns: Mapping[str, str] | None = None,
    required_non_blank: Iterable[str] = (),
    validators: Iterable[Callable[[object], None]] = (),
    drop_old: bool = True,
) -> DomainMigration:
    target_columns = build_target_columns(model=model, extra_columns=extra_columns)
    create_sql = build_create_table_with_extra_columns_sql(model=model, extra_columns=extra_columns)
    indexes_sql = _model_indexes_sql(model)
    insert_sql = _model_insert_sql(new_table_name, target_columns)
    validator_list = list(validators or ())

    def _validate(conn) -> None:
        assert_columns_exist(conn, new_table_name, target_columns)
        if required_non_blank:
            assert_non_blank_strings(conn, new_table_name, required_non_blank)
        if drop_old and table_exists(conn, old_table_name):
            raise ValueError(f"Legacy table {old_table_name} still exists after rehome.")
        for validator in validator_list:
            validator(conn)

    def _apply(conn) -> None:
        if not table_exists(conn, old_table_name):
            return
        if table_exists(conn, new_table_name) and old_table_name == new_table_name:
            return
        if table_exists(conn, new_table_name):
            for column_name, column_sql in dict(extra_columns or {}).items():
                add_column_if_missing(
                    conn,
                    table_name=new_table_name,
                    column_name=column_name,
                    column_sql=column_sql,
                )
        effective_row_mapper = (
            row_mapper_factory(conn)
            if row_mapper_factory is not None
            else make_row_mapper(
                target_columns=target_columns,
                source_aliases=source_aliases,
                value_resolvers=value_resolvers,
                defaults=defaults,
            )
        )
        effective_row_mapper = _wrap_source_identity_row_mapper(
            table_name=new_table_name,
            target_columns=target_columns,
            row_mapper=effective_row_mapper,
        )
        effective_row_mapper = _wrap_audit_timestamp_row_mapper(
            target_columns=target_columns,
            row_mapper=effective_row_mapper,
        )
        rehome_table(
            conn,
            source_table_name=old_table_name,
            target_table_name=new_table_name,
            create_sql=create_sql,
            insert_sql=insert_sql,
            row_mapper=effective_row_mapper,
            indexes_sql=indexes_sql,
            validate=_validate,
            drop_source=drop_old,
        )

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )


def build_append_rows_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    old_table_name: str,
    new_table_name: str,
    model: type[SQLModel],
    source_aliases: Mapping[str, str | Sequence[str]] | None = None,
    value_resolvers: Mapping[str, Callable[[Mapping[str, object]], object]] | None = None,
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
    row_mapper_factory: Callable[[object], Callable[[Mapping[str, object]], Mapping[str, object]]] | None = None,
    extra_columns: Mapping[str, str] | None = None,
    required_non_blank: Iterable[str] = (),
    validators: Iterable[Callable[[object], None]] = (),
    drop_old: bool = True,
) -> DomainMigration:
    target_columns = build_target_columns(model=model, extra_columns=extra_columns)
    create_sql = build_create_table_sql(table_name=new_table_name, model=model, extra_columns=extra_columns)
    indexes_sql = _model_indexes_sql(model)
    insert_sql = _model_insert_sql(new_table_name, target_columns)
    validator_list = list(validators or ())

    def _validate(conn) -> None:
        assert_columns_exist(conn, new_table_name, target_columns)
        if required_non_blank:
            assert_non_blank_strings(conn, new_table_name, required_non_blank)
        if drop_old and table_exists(conn, old_table_name):
            raise ValueError(f"Legacy table {old_table_name} still exists after append migration.")
        for validator in validator_list:
            validator(conn)

    def _apply(conn) -> None:
        if not table_exists(conn, old_table_name):
            return
        if table_exists(conn, new_table_name):
            for column_name, column_sql in dict(extra_columns or {}).items():
                add_column_if_missing(
                    conn,
                    table_name=new_table_name,
                    column_name=column_name,
                    column_sql=column_sql,
                )
        effective_row_mapper = (
            row_mapper_factory(conn)
            if row_mapper_factory is not None
            else make_row_mapper(
                target_columns=target_columns,
                source_aliases=source_aliases,
                value_resolvers=value_resolvers,
                defaults=defaults,
            )
        )
        effective_row_mapper = _wrap_source_identity_row_mapper(
            table_name=new_table_name,
            target_columns=target_columns,
            row_mapper=effective_row_mapper,
        )
        effective_row_mapper = _wrap_audit_timestamp_row_mapper(
            target_columns=target_columns,
            row_mapper=effective_row_mapper,
        )
        append_rows_to_table(
            conn,
            source_table_name=old_table_name,
            target_table_name=new_table_name,
            create_sql=create_sql,
            insert_sql=insert_sql,
            row_mapper=effective_row_mapper,
            indexes_sql=indexes_sql,
            validate=_validate,
            drop_source=drop_old,
        )

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )


def make_listing_snapshot_row_mapper(
    conn,
    *,
    target_columns: Iterable[str],
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
    listing_table_name: str = "trendyol_listing_product",
    cost_item_table_name: str = "cost_item",
) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    listing_id_map: dict[tuple[int, str], int] = {}
    if table_exists(conn, listing_table_name):
        rows = conn.exec_driver_sql(
            f"SELECT pk, api_account_id, product_id FROM {listing_table_name}"
        ).fetchall()
        for row in rows:
            try:
                listing_pk = int(row[0])
                api_account_id = int(row[1])
                product_id = str(row[2] or "").strip()
            except Exception:
                continue
            if product_id:
                listing_id_map[(api_account_id, product_id)] = listing_pk

    cost_item_id_map: dict[str, int] = {}
    if table_exists(conn, cost_item_table_name):
        rows = conn.exec_driver_sql(
            f"SELECT pk, costKey FROM {cost_item_table_name}"
        ).fetchall()
        for row in rows:
            try:
                cost_item_pk = int(row[0])
            except Exception:
                continue
            cost_key = str(row[1] or "").strip().casefold()
            if cost_key:
                cost_item_id_map[cost_key] = cost_item_pk

    base_mapper = make_row_mapper(
        target_columns=target_columns,
        defaults=defaults,
    )

    def _mapper(row: Mapping[str, object]) -> Mapping[str, object]:
        mapped = dict(base_mapper(row))

        listing_id = row.get("listing_id")
        if listing_id is None:
            try:
                api_account_id = int(row.get("api_account_id"))
                product_id = str(row.get("product_id") or "").strip()
            except Exception:
                api_account_id = None
                product_id = ""
            if api_account_id is not None and product_id:
                listing_id = listing_id_map.get((api_account_id, product_id))
        mapped["listing_id"] = listing_id

        cost_item_id = row.get("cost_item_id")
        if cost_item_id is None:
            cost_key = str(row.get("cost_key") or "").strip().casefold()
            if cost_key:
                cost_item_id = cost_item_id_map.get(cost_key)
        mapped["cost_item_id"] = cost_item_id
        if "resolution_meta" in target_columns:
            mapped["resolution_meta"] = merged_listing_resolution_meta(row)
        if "status" in target_columns:
            mapped["status"] = legacy_listing_cost_snapshot_status(row)
        return mapped

    return _mapper


def make_listing_cost_binding_snapshot_row_mapper(
    conn,
    *,
    target_columns: Iterable[str],
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
    listing_table_name: str = "trendyol_listing_product",
    cost_item_table_name: str = "cost_item",
) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    listing_id_map: dict[tuple[int, str], int] = {}
    if table_exists(conn, listing_table_name):
        rows = conn.exec_driver_sql(
            f"SELECT pk, api_account_id, product_id FROM {listing_table_name}"
        ).fetchall()
        for row in rows:
            try:
                listing_pk = int(row[0])
                api_account_id = int(row[1])
                product_id = str(row[2] or "").strip()
            except Exception:
                continue
            if product_id:
                listing_id_map[(api_account_id, product_id)] = listing_pk

    cost_item_id_map: dict[str, int] = {}
    if table_exists(conn, cost_item_table_name):
        rows = conn.exec_driver_sql(
            f"SELECT pk, costKey FROM {cost_item_table_name}"
        ).fetchall()
        for row in rows:
            try:
                cost_item_pk = int(row[0])
            except Exception:
                continue
            cost_key = str(row[1] or "").strip().casefold()
            if cost_key:
                cost_item_id_map[cost_key] = cost_item_pk

    base_mapper = make_row_mapper(
        target_columns=target_columns,
        defaults=defaults,
    )

    def _mapper(row: Mapping[str, object]) -> Mapping[str, object]:
        mapped = dict(base_mapper(row))
        try:
            api_account_id = int(row.get("api_account_id"))
            product_id = str(row.get("product_id") or "").strip()
        except Exception:
            api_account_id = None
            product_id = ""
        mapped["listing_id"] = listing_id_map.get((api_account_id, product_id)) if api_account_id is not None and product_id else None

        cost_key = str(row.get("cost_key") or "").strip()
        normalized_key = cost_key.casefold()
        mapped["cost_key"] = cost_key or None
        mapped["cost_item_id"] = cost_item_id_map.get(normalized_key) if normalized_key else None

        source_type = str(row.get("source_type") or "").strip() or None
        source_config = row.get("source_config")
        tariff_key = str(row.get("tariff_key") or "").strip() or None
        calculation_type = str(row.get("calculation_type") or "").strip().casefold()

        if source_type is None:
            if calculation_type == "manual":
                source_type = "manual_value"
            elif calculation_type == "automatic":
                source_type = "builtin_resolver"

        if source_config is None and source_type == "manual_value":
            amount = row.get("amount")
            quantity = row.get("quantity")
            payload: dict[str, object] = {}
            if amount is not None:
                payload["amount"] = amount
            if quantity is not None:
                payload["quantity"] = quantity
            source_config = payload or None
        elif source_config is None and source_type == "builtin_resolver":
            payload = {"ruleKey": "cargo_amount_matcher"}
            if tariff_key:
                payload["tariffKey"] = tariff_key
            source_config = payload

        mapped["source_type"] = source_type
        mapped["source_config"] = source_config
        created_at = row.get("updated_at") or row.get("created_at")
        mapped["created_at"] = created_at
        mapped["updated_at"] = row.get("updated_at") or created_at
        resolution_meta = {}
        if row.get("tariff_key") not in (None, ""):
            resolution_meta["tariff_key"] = tariff_key
        mapped["resolution_meta"] = resolution_meta or None
        if "status" in target_columns:
            mapped["status"] = "set"
        return mapped

    return _mapper


def make_listing_stock_binding_snapshot_row_mapper(
    conn,
    *,
    target_columns: Iterable[str],
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
    listing_table_name: str = "trendyol_listing_product",
) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    listing_id_map: dict[tuple[int, str], int] = {}
    if table_exists(conn, listing_table_name):
        rows = conn.exec_driver_sql(
            f"SELECT pk, api_account_id, product_id FROM {listing_table_name}"
        ).fetchall()
        for row in rows:
            try:
                listing_pk = int(row[0])
                api_account_id = int(row[1])
                product_id = str(row[2] or "").strip()
            except Exception:
                continue
            if product_id:
                listing_id_map[(api_account_id, product_id)] = listing_pk

    base_mapper = make_row_mapper(
        target_columns=target_columns,
        defaults=defaults,
    )

    def _mapper(row: Mapping[str, object]) -> Mapping[str, object]:
        mapped = dict(base_mapper(row))
        try:
            api_account_id = int(row.get("api_account_id"))
            product_id = str(row.get("product_id") or "").strip()
        except Exception:
            api_account_id = None
            product_id = ""

        mapped["listing_id"] = (
            listing_id_map.get((api_account_id, product_id))
            if api_account_id is not None and product_id
            else None
        )
        mapped["stock_item_id"] = row.get("stock_item_id")
        mapped["qty"] = row.get("qty")
        mapped["created_at"] = row.get("updated_at") or row.get("created_at")
        mapped["updated_at"] = row.get("updated_at") or row.get("created_at")
        if "status" in target_columns:
            mapped["status"] = "append"
        return mapped

    return _mapper


def legacy_listing_cost_snapshot_status(row: Mapping[str, object]) -> str:
    raw_status = str(row.get("status") or "").strip().casefold()
    if raw_status in {"append", "set", "remove"}:
        return raw_status

    removed_value = row.get("removed")
    if removed_value in (1, "1", True, "true", "True"):
        return "remove"

    resolution_meta = row.get("resolution_meta")
    if isinstance(resolution_meta, str):
        try:
            resolution_meta = json.loads(resolution_meta)
        except Exception:
            resolution_meta = None
    if isinstance(resolution_meta, Mapping):
        if bool(resolution_meta.get("removed")):
            return "remove"
        binding_event = str(resolution_meta.get("binding_event") or "").strip().casefold()
        if binding_event in {"append", "set", "remove"}:
            return binding_event
    return "set"


def _legacy_listing_snapshot_clean_meta(row: Mapping[str, object]) -> dict[str, object] | None:
    resolution_meta = row.get("resolution_meta")
    if isinstance(resolution_meta, str):
        try:
            resolution_meta = json.loads(resolution_meta)
        except Exception:
            resolution_meta = None
    if not isinstance(resolution_meta, Mapping):
        return None
    cleaned = {
        str(key): value
        for key, value in dict(resolution_meta).items()
        if str(key) not in {"binding_event", "removed", "status"}
    }
    return cleaned or None


def _legacy_listing_snapshot_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _legacy_listing_snapshot_normalized_payload(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": row.get("id"),
        "status": legacy_listing_cost_snapshot_status(row),
        "cost_item_id": row.get("cost_item_id"),
        "listing_id": row.get("listing_id"),
        "cost_key": str(row.get("cost_key") or "").strip() or None,
        "source_type": str(row.get("source_type") or "").strip() or None,
        "source_config": row.get("source_config"),
        "resolved_amount": _legacy_listing_snapshot_float(row.get("resolved_amount")),
        "resolved_net_amount": _legacy_listing_snapshot_float(row.get("resolved_net_amount")),
        "resolved_vat_amount": _legacy_listing_snapshot_float(row.get("resolved_vat_amount")),
        "currency": str(row.get("currency") or "TRY").strip() or "TRY",
        "note": str(row.get("note") or "").strip() or None,
        "resolution_meta": _legacy_listing_snapshot_clean_meta(row),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at") or row.get("created_at"),
        "sync_uuid": row.get("sync_uuid"),
        "sync_version": row.get("sync_version"),
        "sync_updated_at": row.get("sync_updated_at"),
        "sync_deleted_at": row.get("sync_deleted_at"),
        "sync_source_device": row.get("sync_source_device"),
    }


def _legacy_listing_snapshot_signature(row: Mapping[str, object]) -> tuple[object, ...]:
    payload = _legacy_listing_snapshot_normalized_payload(row)
    source_config = payload.get("source_config")
    resolution_meta = payload.get("resolution_meta")
    return (
        payload.get("cost_item_id"),
        payload.get("cost_key"),
        payload.get("source_type"),
        json.dumps(source_config, ensure_ascii=False, sort_keys=True) if source_config is not None else None,
        payload.get("resolved_amount"),
        payload.get("resolved_net_amount"),
        payload.get("resolved_vat_amount"),
        payload.get("currency"),
        payload.get("note"),
        json.dumps(resolution_meta, ensure_ascii=False, sort_keys=True) if resolution_meta is not None else None,
    )


def compact_listing_cost_snapshot_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[int | None, str], list[Mapping[str, object]]] = {}
    for row in rows:
        try:
            listing_id = int(row.get("listing_id")) if row.get("listing_id") is not None else None
        except Exception:
            listing_id = None
        cost_key = str(row.get("cost_key") or "").strip().casefold()
        grouped.setdefault((listing_id, cost_key), []).append(row)

    compacted: list[dict[str, object]] = []
    for _group_key in sorted(grouped.keys(), key=lambda key: (key[0] or 0, key[1])):
        pending_event: dict[str, object] | None = None
        pending_status: str | None = None
        last_active: dict[str, object] | None = None

        for row in sorted(
            grouped[_group_key],
            key=lambda current: (
                str(current.get("created_at") or ""),
                int(current.get("pk") or 0),
            ),
        ):
            payload = _legacy_listing_snapshot_normalized_payload(row)
            status = str(payload.get("status") or "set")
            has_resolved = any(
                (
                    payload.get("resolved_amount") is not None,
                    payload.get("resolved_net_amount") is not None,
                    payload.get("resolved_vat_amount") is not None,
                    payload.get("note") is not None,
                    payload.get("resolution_meta") is not None,
                )
            )

            if status == "remove":
                remove_payload = dict(payload)
                if last_active is not None:
                    for field_name in (
                        "cost_item_id",
                        "source_type",
                        "source_config",
                        "resolved_amount",
                        "resolved_net_amount",
                        "resolved_vat_amount",
                        "currency",
                        "note",
                        "resolution_meta",
                    ):
                        if remove_payload.get(field_name) in (None, ""):
                            remove_payload[field_name] = last_active.get(field_name)
                compacted.append(remove_payload)
                pending_event = None
                pending_status = None
                last_active = None
                continue

            if not has_resolved:
                pending_event = dict(payload)
                pending_status = "append" if last_active is None else "set"
                continue

            effective = dict(payload)
            if pending_event is not None:
                for field_name in ("cost_item_id", "source_type", "source_config", "currency"):
                    if pending_event.get(field_name) not in (None, ""):
                        effective[field_name] = pending_event.get(field_name)
                effective["status"] = pending_status or ("append" if last_active is None else "set")
                pending_event = None
                pending_status = None
            else:
                effective["status"] = "append" if last_active is None else "set"

            if last_active is not None and _legacy_listing_snapshot_signature(effective) == _legacy_listing_snapshot_signature(last_active):
                last_active = dict(effective)
                continue

            compacted.append(effective)
            last_active = dict(effective)

        if pending_event is not None:
            effective = dict(pending_event)
            effective["status"] = pending_status or ("append" if last_active is None else "set")
            if last_active is None or _legacy_listing_snapshot_signature(effective) != _legacy_listing_snapshot_signature(last_active):
                compacted.append(effective)

    compacted.sort(
        key=lambda row: (
            str(row.get("created_at") or ""),
            int(row.get("pk") or 0),
        )
    )
    return compacted


def build_listing_cost_snapshot_compaction_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
    model: type[SQLModel],
    extra_columns: Mapping[str, str] | None = None,
    validators: Iterable[Callable[[object], None]] = (),
    old_suffix: str = "__old",
) -> DomainMigration:
    target_columns = build_target_columns(model=model, extra_columns=extra_columns)
    create_sql = build_create_table_with_extra_columns_sql(model=model, extra_columns=extra_columns)
    insert_sql = _model_insert_sql(table_name, target_columns)
    indexes_sql = _model_indexes_sql(model)
    validator_list = list(validators or ())

    def _apply(conn) -> None:
        if not table_exists(conn, table_name):
            return
        if table_row_count(conn, table_name) <= 0:
            return

        rows = conn.exec_driver_sql(
            f"SELECT * FROM {quote_ident(table_name)} ORDER BY listing_id, cost_key, created_at, pk"
        ).mappings().all()
        compacted_rows = compact_listing_cost_snapshot_rows(rows)
        old_name = f"{table_name}{old_suffix}"
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {quote_ident(old_name)}")
        conn.exec_driver_sql(f"ALTER TABLE {quote_ident(table_name)} RENAME TO {quote_ident(old_name)}")
        conn.exec_driver_sql(create_sql)
        insert_sql_local = _model_insert_sql(table_name, target_columns)
        for row in compacted_rows:
            payload = {}
            for column_name in target_columns:
                value = row.get(column_name)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                payload[column_name] = value
            now_iso = _now_iso_text()
            created_at = (
                payload.get("created_at")
                or payload.get("createdAt")
                or row.get("created_at")
                or row.get("createdAt")
                or now_iso
            )
            updated_at = (
                payload.get("updated_at")
                or payload.get("updatedAt")
                or row.get("updated_at")
                or row.get("updatedAt")
                or created_at
            )
            if "created_at" in payload:
                payload["created_at"] = created_at
            if "updated_at" in payload:
                payload["updated_at"] = updated_at
            if "createdAt" in payload:
                payload["createdAt"] = created_at
            if "updatedAt" in payload:
                payload["updatedAt"] = updated_at
            source_type, source_id = backfill_source_identity_row(table_name, payload)
            if "sourceType" in payload and not payload.get("sourceType"):
                payload["sourceType"] = source_type
            if "sourceId" in payload and not payload.get("sourceId"):
                payload["sourceId"] = source_id
            conn.exec_driver_sql(insert_sql_local, payload)
        conn.exec_driver_sql(f"DROP TABLE {quote_ident(old_name)}")
        create_indexes(conn, indexes_sql)
        for validator in validator_list:
            validator(conn)

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )


def should_run_when_columns_need_replacement(
    conn,
    *,
    table_name: str,
    replacements: Mapping[str, str | Sequence[str]],
) -> bool:
    if not table_exists(conn, table_name):
        return False

    columns = table_columns(conn, table_name)
    for target_name, legacy_names in dict(replacements or {}).items():
        sources = _as_source_names(legacy_names, target_name)
        legacy_sources = [source_name for source_name in sources if source_name != target_name]
        if any(source_name in columns for source_name in legacy_sources):
            return True
        if target_name not in columns and any(source_name in columns for source_name in sources):
            return True
    return False


def build_replace_columns_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
    model: type[SQLModel],
    replacements: Mapping[str, str | Sequence[str]],
    extra_columns: Mapping[str, str] | None = None,
    required_non_blank: Iterable[str] = (),
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
    validators: Iterable[Callable[[object], None]] = (),
    old_suffix: str = "__old",
) -> DomainMigration:
    replacement_map = {str(key): value for key, value in dict(replacements or {}).items()}
    target_columns = build_target_columns(model=model, extra_columns=extra_columns)
    create_sql = build_create_table_sql(table_name=table_name, model=model, extra_columns=extra_columns)
    legacy_columns = []
    for target_name, sources in replacement_map.items():
        for source_name in _as_source_names(sources, target_name):
            if source_name != target_name:
                legacy_columns.append(source_name)

    def _validate_replacements(conn) -> None:
        assert_columns_exist(conn, table_name, replacement_map.keys())
        if legacy_columns:
            assert_columns_absent(conn, table_name, legacy_columns)
        if required_non_blank:
            assert_non_blank_strings(conn, table_name, required_non_blank)

    return build_model_rebuild_migration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        table_name=table_name,
        model=model,
        should_run=lambda conn: should_run_when_columns_need_replacement(
            conn,
            table_name=table_name,
            replacements=replacement_map,
        ),
        row_mapper=make_row_mapper(
            target_columns=target_columns,
            source_aliases=replacement_map,
            defaults=defaults,
        ),
        validators=[_validate_replacements, *list(validators or ())],
        old_suffix=old_suffix,
        create_sql=create_sql,
        indexes_sql=_model_indexes_sql(model),
        target_columns=target_columns,
    )


def build_copy_columns_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
    replacements: Mapping[str, str | Sequence[str]],
    column_defs: Mapping[str, str] | None = None,
    required_non_blank: Iterable[str] = (),
    copy_when_blank: Iterable[str] = (),
    validators: Iterable[Callable[[object], None]] = (),
) -> DomainMigration:
    replacement_map = {str(key): value for key, value in dict(replacements or {}).items()}
    copy_when_blank_set = {str(name) for name in copy_when_blank or ()}
    column_def_map = {str(key): str(value) for key, value in dict(column_defs or {}).items()}
    validator_list = list(validators or ())

    def _should_run(conn) -> bool:
        if not table_exists(conn, table_name):
            return False
        columns = table_columns(conn, table_name)
        for _target_name, source_names in replacement_map.items():
            if any(source in columns for source in _as_source_names(source_names, "")):
                return True
        return False

    def _validate(conn) -> None:
        assert_columns_exist(conn, table_name, replacement_map.keys())
        if required_non_blank:
            assert_non_blank_strings(conn, table_name, required_non_blank)
        for validator in validator_list:
            validator(conn)

    def _apply(conn) -> None:
        if not _should_run(conn):
            return
        for target_name, column_sql in column_def_map.items():
            add_column_if_missing(conn, table_name=table_name, column_name=target_name, column_sql=column_sql)
        for target_name, source_names in replacement_map.items():
            copy_column_values(
                conn,
                table_name=table_name,
                target_name=target_name,
                source_names=_as_source_names(source_names, target_name),
                copy_when_blank=target_name in copy_when_blank_set,
            )
        _validate(conn)

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )


def build_backfill_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    should_run: Callable[[object], bool],
    apply_sql: Callable[[object], None],
    validators: Iterable[Callable[[object], None]] = (),
) -> DomainMigration:
    validator_list = list(validators or ())

    def _apply(conn) -> None:
        if not bool(should_run(conn)):
            return
        apply_sql(conn)
        for validator in validator_list:
            validator(conn)

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )


def build_drop_table_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
) -> DomainMigration:
    return build_backfill_migration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        should_run=lambda conn: table_exists(conn, table_name),
        apply_sql=lambda conn: drop_table_if_exists(conn, table_name),
    )


def build_stock_tx_legacy_cost_defaults_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str = "stock_tx",
    stock_item_table_name: str = "stock_item",
) -> DomainMigration:
    return build_backfill_migration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        should_run=lambda conn: has_rows_missing_stock_tx_legacy_cost_defaults(
            conn,
            table_name=table_name,
        ),
        apply_sql=lambda conn: backfill_stock_tx_legacy_cost_defaults(
            conn,
            table_name=table_name,
            stock_item_table_name=stock_item_table_name,
        ),
    )


def build_listing_cost_snapshot_tariff_meta_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
    model: type[SQLModel],
    extra_columns: Mapping[str, str] | None = None,
    validators: Iterable[Callable[[object], None]] = (),
) -> DomainMigration:
    target_columns = build_target_columns(model=model, extra_columns=extra_columns)
    validator_list = list(validators or ())

    return build_model_rebuild_migration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        table_name=table_name,
        model=model,
        should_run=lambda conn: table_exists(conn, table_name)
        and (
            "matched_tariff_key" in table_columns(conn, table_name)
            or "matched_tariff_name" in table_columns(conn, table_name)
        ),
        row_mapper=make_row_mapper(target_columns=[]),
        row_mapper_factory=lambda conn: make_listing_snapshot_row_mapper(
            conn,
            target_columns=target_columns,
        ),
        create_sql=build_create_table_with_extra_columns_sql(
            model=model,
            extra_columns=extra_columns,
        ),
        target_columns=target_columns,
        validators=validator_list,
    )


def build_platform_id_backfill_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
    pk_column: str,
    source_platform_column: str,
) -> DomainMigration:
    def _apply(conn) -> None:
        from Marketplaces.constants.catalog_constants import marketplace_db_id_for_code

        if not table_exists(conn, table_name):
            return
        add_column_if_missing(
            conn,
            table_name=table_name,
            column_name="platform_id",
            column_sql="INTEGER",
        )
        rows = conn.exec_driver_sql(
            f"SELECT {quote_ident(pk_column)}, {quote_ident(source_platform_column)} "
            f"FROM {quote_ident(table_name)} "
            "WHERE (platform_id IS NULL OR platform_id = '') "
            f"AND {quote_ident(source_platform_column)} IS NOT NULL "
            f"AND TRIM({quote_ident(source_platform_column)}) != ''"
        ).fetchall()
        for row_pk, platform_code in rows:
            platform_id = marketplace_db_id_for_code(platform_code)
            if not platform_id:
                continue
            conn.exec_driver_sql(
                f"UPDATE {quote_ident(table_name)} SET platform_id=? WHERE {quote_ident(pk_column)}=?",
                (platform_id, row_pk),
            )

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )


def build_lookup_foreign_key_rebuild_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
    model: type[SQLModel],
    target_fk_column: str,
    target_table: str,
    target_column: str,
    lookup_table: str,
    lookup_id_column: str,
    source_columns: Sequence[str],
    lookup_columns: Sequence[str],
    defaults: Mapping[str, Any | Callable[[Mapping[str, object]], object]] | None = None,
    validators: Iterable[Callable[[object], None]] = (),
    old_suffix: str = "__old",
) -> DomainMigration:
    target_columns = build_target_columns(model=model)
    validator_list = [
        make_foreign_key_validator(
            table_name=table_name,
            from_column=target_fk_column,
            target_table=target_table,
            target_column=target_column,
        ),
        *list(validators or ()),
    ]

    return build_model_rebuild_migration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        table_name=table_name,
        model=model,
        should_run=lambda conn: table_exists(conn, table_name)
        and (
            target_fk_column not in table_columns(conn, table_name)
            or not table_has_foreign_key(
                conn,
                table_name=table_name,
                from_column=target_fk_column,
                target_table=target_table,
                target_column=target_column,
            )
        ),
        row_mapper=make_row_mapper(target_columns=[]),
        row_mapper_factory=lambda conn: make_lookup_foreign_key_row_mapper(
            conn,
            target_columns=target_columns,
            target_fk_column=target_fk_column,
            lookup_table=lookup_table,
            lookup_id_column=lookup_id_column,
            source_columns=source_columns,
            lookup_columns=lookup_columns,
            defaults=defaults,
        ),
        validators=validator_list,
        old_suffix=old_suffix,
        create_sql=build_create_table_with_extra_columns_sql(model=model),
        indexes_sql=_model_indexes_sql(model),
        target_columns=target_columns,
    )


def build_drop_columns_rebuild_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    table_name: str,
    model: type[SQLModel],
    dropped_columns: Iterable[str],
    validators: Iterable[Callable[[object], None]] = (),
    old_suffix: str = "__old",
) -> DomainMigration:
    target_columns = build_target_columns(model=model)
    removed = {str(column_name) for column_name in dropped_columns or () if str(column_name)}

    return build_model_rebuild_migration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        table_name=table_name,
        model=model,
        should_run=lambda conn: table_exists(conn, table_name)
        and any(column_name in table_columns(conn, table_name) for column_name in removed),
        row_mapper=make_row_mapper(target_columns=target_columns, defaults={"sync_version": 1}),
        validators=list(validators or ()),
        old_suffix=old_suffix,
        create_sql=build_create_table_with_extra_columns_sql(model=model),
        indexes_sql=_model_indexes_sql(model),
        target_columns=target_columns,
    )


def build_cost_item_platform_link_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    link_model: type[SQLModel],
    source_table_name: str = "cost_item",
    marketplace_table_name: str = "marketplace",
    link_table_name: str = "cost_item_platform_link",
    source_pk_column: str = "pk",
    source_platforms_json_column: str = "supportedPlatformsJson",
) -> DomainMigration:
    create_sql = build_create_table_with_extra_columns_sql(model=link_model)
    indexes_sql = _model_indexes_sql(link_model)

    def _apply(conn) -> None:
        from Marketplaces.constants.catalog_constants import canonical_platform_code

        if not table_exists(conn, source_table_name):
            return

        if not table_exists(conn, link_table_name):
            conn.exec_driver_sql(create_sql)
        create_indexes(conn, indexes_sql)

        if not table_exists(conn, marketplace_table_name):
            return
        if source_platforms_json_column not in table_columns(conn, source_table_name):
            return

        marketplace_rows = conn.exec_driver_sql(
            f"SELECT {quote_ident('pk')}, {quote_ident('code')} FROM {quote_ident(marketplace_table_name)}"
        ).fetchall()
        marketplace_id_by_code: dict[str, int] = {}
        for marketplace_id, marketplace_code in marketplace_rows:
            try:
                normalized_id = int(marketplace_id or 0)
            except Exception:
                normalized_id = 0
            normalized_code = canonical_platform_code(marketplace_code)
            if normalized_id > 0 and normalized_code:
                marketplace_id_by_code[normalized_code] = normalized_id

        existing_rows = conn.exec_driver_sql(
            f"SELECT {quote_ident('cost_item_id')}, {quote_ident('marketplace_id')} FROM {quote_ident(link_table_name)}"
        ).fetchall()
        existing_pairs = {
            (int(cost_item_id or 0), int(marketplace_id or 0))
            for cost_item_id, marketplace_id in existing_rows
            if int(cost_item_id or 0) > 0 and int(marketplace_id or 0) > 0
        }

        source_rows = conn.exec_driver_sql(
            f"""
            SELECT {quote_ident(source_pk_column)}, {quote_ident(source_platforms_json_column)}
            FROM {quote_ident(source_table_name)}
            WHERE {quote_ident(source_pk_column)} IS NOT NULL
            """
        ).fetchall()
        insert_sql = (
            f"INSERT INTO {quote_ident(link_table_name)} "
            f"({quote_ident('cost_item_id')}, {quote_ident('marketplace_id')}) VALUES (?, ?)"
        )
        for cost_item_id, raw_platforms_json in source_rows:
            try:
                normalized_cost_item_id = int(cost_item_id or 0)
            except Exception:
                normalized_cost_item_id = 0
            if normalized_cost_item_id <= 0:
                continue
            try:
                parsed = json.loads(str(raw_platforms_json or "[]"))
            except Exception:
                parsed = []
            for raw_platform in list(parsed or []):
                platform_code = canonical_platform_code(raw_platform)
                marketplace_id = marketplace_id_by_code.get(platform_code)
                pair = (normalized_cost_item_id, int(marketplace_id or 0))
                if not platform_code or not marketplace_id or pair in existing_pairs:
                    continue
                conn.exec_driver_sql(insert_sql, pair)
                existing_pairs.add(pair)

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )


def build_promote_table_migration(
    *,
    migration_id: str,
    domain: str,
    description: str,
    old_table_name: str,
    new_table_name: str,
    indexes_sql: Iterable[str] = (),
) -> DomainMigration:
    def _apply(conn) -> None:
        if not table_exists(conn, old_table_name):
            return
        promote_legacy_table(
            conn,
            old_table_name=old_table_name,
            new_table_name=new_table_name,
        )
        if table_exists(conn, new_table_name):
            create_indexes(conn, indexes_sql)

    return DomainMigration(
        migration_id=migration_id,
        domain=domain,
        description=description,
        apply=_apply,
    )
