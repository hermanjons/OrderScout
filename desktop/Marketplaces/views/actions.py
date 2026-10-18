from __future__ import annotations

from typing import Any

from Feedback.processors.pipeline import Result, map_error_to_message
from Marketplaces.constants.catalog_constants import builtin_marketplace_records, normalize_marketplace_code
from Marketplaces.processors.pipeline import (
    accept_marketplace,
    delete_marketplace_record,
    list_marketplace_rows,
    save_marketplace_record,
    set_marketplace_active_state,
)
from Marketplaces.signals.signals import marketplace_signals


def marketplace_status_filter_options() -> list[tuple[str, str]]:
    return [("Tumu", "all"), ("Aktif", "active"), ("Pasif", "passive")]


def marketplace_source_filter_options() -> list[tuple[str, str]]:
    return [("Tumu", "all"), ("Onerilen", "pending"), ("Kayitli", "saved")]


def load_marketplaces(
    *,
    search: str = "",
    status_filter: str = "all",
    source_filter: str = "all",
    db_name: str | None = None,
) -> Result:
    try:
        db_rows = list_marketplace_rows(db_name=db_name)
        builtin_rows = builtin_marketplace_records()
        builtin_source_ids = {
            int(row.get("sourceId") or row.get("source_id"))
            for row in builtin_rows
            if str(row.get("sourceId") or row.get("source_id") or "").strip()
        }
        accepted_map = {
            str(row.get("code") or "").strip().upper(): dict(row or {})
            for row in db_rows
            if str(row.get("code") or "").strip()
        }
        records: list[dict[str, Any]] = []

        for row in builtin_rows:
            code = str(row.get("code") or "").strip().upper()
            accepted = dict(accepted_map.pop(code, {}) or {})
            if accepted:
                payload = {**dict(row or {}), **accepted}
                payload["isBuiltin"] = True
                payload["isBuiltinAccepted"] = True
                payload["isSeedRemoved"] = False
                payload["sourceCode"] = "accepted"
                payload["sourceLabel"] = "Kullanima Alinmis"
                records.append(payload)
                continue
            payload = dict(row or {})
            payload["isBuiltin"] = True
            payload["isBuiltinAccepted"] = False
            payload["isSeedRemoved"] = False
            payload["sourceCode"] = "builtin"
            payload["sourceLabel"] = "Onerilen Kayit"
            records.append(payload)

        for row in accepted_map.values():
            payload = dict(row or {})
            payload_source_type = str(payload.get("sourceType") or "").strip().lower()
            payload_source_id = int(payload.get("sourceId") or payload.get("source_id") or 0)
            is_seed_removed = (
                payload_source_type == "builtin"
                or (
                    payload_source_type == "user"
                    and not bool(payload.get("isActive", True))
                    and payload_source_id > 0
                )
            ) and payload_source_id not in builtin_source_ids
            payload["isBuiltin"] = bool(is_seed_removed)
            payload["isBuiltinAccepted"] = True
            payload["isSeedRemoved"] = bool(is_seed_removed)
            payload["sourceCode"] = "removed" if is_seed_removed else "db"
            payload["sourceLabel"] = "Seed'den Kalkti" if is_seed_removed else "Veritabani"
            records.append(payload)

        q = str(search or "").strip().casefold()
        status = str(status_filter or "all").strip().casefold()
        source = str(source_filter or "all").strip().casefold()

        if q:
            filtered: list[dict[str, Any]] = []
            for row in records:
                haystack = " ".join(
                    [
                        str(row.get("code") or ""),
                        str(row.get("label") or ""),
                        str(row.get("description") or ""),
                        str(row.get("sourceLabel") or ""),
                    ]
                ).casefold()
                if q in haystack:
                    filtered.append(row)
            records = filtered

        if status == "active":
            records = [row for row in records if bool(row.get("isActive"))]
        elif status == "passive":
            records = [row for row in records if not bool(row.get("isActive"))]

        if source in {"builtin", "pending"}:
            records = [row for row in records if bool(row.get("isBuiltin")) and not bool(row.get("isBuiltinAccepted"))]
        elif source in {"accepted", "saved"}:
            records = [row for row in records if bool(row.get("isBuiltinAccepted"))]
        elif source == "db":
            records = [row for row in records if not bool(row.get("isBuiltin"))]

        records.sort(
            key=lambda row: (
                0 if bool(row.get("isBuiltinAccepted")) else 1,
                0 if bool(row.get("isActive")) else 1,
                str(row.get("label") or "").casefold(),
            )
        )
        return Result.ok(f"{len(records)} pazaryeri yüklendi.", data={"records": records}, close_dialog=False)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def save_marketplace(*, payload: dict[str, Any], db_name: str | None = None) -> Result:
    try:
        result = save_marketplace_record(dict(payload or {}), db_name=db_name)
        if result.success:
            marketplace_signals.marketplaces_changed.emit()
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def delete_marketplace(*, code: str, db_name: str | None = None) -> Result:
    _ = normalize_marketplace_code(code)
    try:
        result = delete_marketplace_record(code, db_name=db_name)
        if result.success:
            marketplace_signals.marketplaces_changed.emit()
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def accept_marketplace_record(*, code: str, db_name: str | None = None) -> Result:
    try:
        result = accept_marketplace(code, db_name=db_name)
        if result.success:
            marketplace_signals.marketplaces_changed.emit()
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def set_marketplaces_active_state(*, codes: list[str], is_active: bool, db_name: str | None = None) -> Result:
    try:
        result = set_marketplace_active_state(codes=list(codes or []), is_active=bool(is_active), db_name=db_name)
        if result.success:
            marketplace_signals.marketplaces_changed.emit()
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
