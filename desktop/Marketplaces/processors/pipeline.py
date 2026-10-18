from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Marketplaces.models.models import Marketplace
from Core.db.models import coerce_source_id
from Marketplaces.constants.catalog_constants import (
    canonical_platform_code,
    invalidate_marketplace_runtime_cache,
    load_default_marketplaces,
    marketplace_records,
)
from settings import DB_NAME


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _engine(db_name: str | None = None):
    return get_engine(db_name or DB_NAME)


def _now_iso_text() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _table_exists(session: Session, table_name: str) -> bool:
    try:
        row = session.connection().exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (str(table_name or "").strip(),),
        ).first()
    except Exception:
        return False
    return bool(row)


def _sync_marketplace_relations(
    marketplace_code: str,
    marketplace_pk: int,
    *,
    db_name: str | None = None,
) -> None:
    from Account.models.models import ApiAccount
    from Logistics.models.models import LogisticsCargoProvider

    if not marketplace_code or marketplace_pk <= 0:
        return

    engine = _engine(db_name)
    with Session(engine) as session:
        accounts = []
        providers = []
        if _table_exists(session, ApiAccount.__tablename__):
            accounts = session.exec(
                select(ApiAccount).where(ApiAccount.platform == marketplace_code)
            ).all() or []
        if _table_exists(session, LogisticsCargoProvider.__tablename__):
            providers = session.exec(
                select(LogisticsCargoProvider).where(LogisticsCargoProvider.platformCode == marketplace_code)
            ).all() or []
        changed = False
        for row in accounts:
            if int(getattr(row, "platform_id", 0) or 0) == marketplace_pk:
                continue
            row.platform_id = marketplace_pk
            session.add(row)
            changed = True
        for row in providers:
            if int(getattr(row, "platform_id", 0) or 0) == marketplace_pk:
                continue
            row.platform_id = marketplace_pk
            session.add(row)
            changed = True
        if changed:
            session.commit()


def list_marketplace_rows(*, db_name: str | None = None) -> list[dict[str, Any]]:
    try:
        return marketplace_records(db_name=db_name)
    except Exception:
        return []


def marketplace_id_for_code(code: object, *, db_name: str | None = None) -> int | None:
    normalized = canonical_platform_code(code)
    if not normalized:
        return None
    for row in list_marketplace_rows(db_name=db_name):
        if _compact_text(row.get("code")).upper() == normalized:
            try:
                marketplace_pk = int(row.get("pk") or 0)
            except Exception:
                marketplace_pk = 0
            if marketplace_pk > 0:
                return marketplace_pk
    return None


def accept_marketplace(
    code: object,
    *,
    db_name: str | None = None,
) -> Result:
    try:
        normalized = canonical_platform_code(code)
        if not normalized:
            return Result.fail("Geçerli pazaryeri kodu bulunamadı.", close_dialog=False)

        builtin = next(
            (
                dict(row or {})
                for row in load_default_marketplaces()
                if _compact_text(row.get("code")).upper() == normalized
            ),
            None,
        )
        if builtin is None:
            return Result.fail("Bu kayıt önerilen bir pazaryeri değil.", close_dialog=False)

        engine = _engine(db_name)
        now_iso = _now_iso_text()
        with Session(engine) as session:
            row = session.exec(
                select(Marketplace).where(Marketplace.code == normalized)
            ).first()
            if row is None:
                row = Marketplace(
                    code=normalized,
                    label=_compact_text(builtin.get("label")) or normalized,
                    description=_compact_text(builtin.get("description")) or None,
                    logoPath=_compact_text(builtin.get("logoPath")) or None,
                    isActive=bool(builtin.get("isActive", True)),
                    sourceType="builtin",
                    sourceId=coerce_source_id(builtin.get("sourceId") or builtin.get("source_id")),
                    createdAt=now_iso,
                    updatedAt=now_iso,
                )
                session.add(row)
            else:
                row.label = _compact_text(row.label) or _compact_text(builtin.get("label")) or normalized
                row.description = _compact_text(row.description) or _compact_text(builtin.get("description")) or None
                row.logoPath = _compact_text(row.logoPath) or _compact_text(builtin.get("logoPath")) or None
                row.sourceType = "builtin"
                row.sourceId = coerce_source_id(builtin.get("sourceId") or builtin.get("source_id"))
                row.updatedAt = now_iso
            session.commit()
            session.refresh(row)
        invalidate_marketplace_runtime_cache()
        _sync_marketplace_relations(normalized, int(getattr(row, "pk", 0) or 0), db_name=db_name)
        return Result.ok("Önerilen pazaryeri kullanıma alındı.", close_dialog=False)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def save_marketplace_record(
    payload: dict[str, Any],
    *,
    db_name: str | None = None,
) -> Result:
    try:
        row_payload = dict(payload or {})
        code = canonical_platform_code(row_payload.get("code"))
        label = _compact_text(row_payload.get("label"))
        if not code:
            return Result.fail("Pazaryeri kodu zorunlu.", close_dialog=False)
        if not label:
            return Result.fail("Pazaryeri etiketi zorunlu.", close_dialog=False)

        engine = _engine(db_name)
        now_iso = _now_iso_text()
        with Session(engine) as session:
            row = session.exec(
                select(Marketplace).where(Marketplace.code == code)
            ).first()
            if row is None:
                return Result.fail("Bu pazaryeri önce kabul edilmelidir.", close_dialog=False)
            row.label = label
            row.description = _compact_text(row_payload.get("description")) or row.description
            row.isActive = bool(row_payload.get("isActive", row.isActive))
            builtin = next(
                (
                    dict(default_row or {})
                    for default_row in load_default_marketplaces()
                    if _compact_text(default_row.get("code")).upper() == code
                ),
                None,
            )
            if builtin is not None:
                row.sourceType = "builtin"
                row.sourceId = coerce_source_id(builtin.get("sourceId") or builtin.get("source_id"))
            row.updatedAt = now_iso
            session.add(row)
            session.commit()
            session.refresh(row)
        invalidate_marketplace_runtime_cache()
        _sync_marketplace_relations(code, int(getattr(row, "pk", 0) or 0), db_name=db_name)
        return Result.ok("Pazaryeri güncellendi.", close_dialog=False)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def delete_marketplace_record(
    code: object,
    *,
    db_name: str | None = None,
) -> Result:
    try:
        normalized = canonical_platform_code(code)
        if not normalized:
            return Result.fail("Silinecek pazaryeri bulunamadi.", close_dialog=False)

        from Account.models.models import ApiAccount
        from Logistics.models.models import LogisticsCargoProvider

        engine = _engine(db_name)
        with Session(engine) as session:
            row = session.exec(
                select(Marketplace).where(Marketplace.code == normalized)
            ).first()
            if row is None:
                return Result.fail("Silinecek pazaryeri bulunamadi.", close_dialog=False)

            if _table_exists(session, ApiAccount.__tablename__):
                linked_accounts = session.exec(
                    select(ApiAccount).where(
                        (ApiAccount.platform_id == int(getattr(row, "pk", 0) or 0))
                        | (ApiAccount.platform == normalized)
                    )
                ).all() or []
                if linked_accounts:
                    return Result.fail("Bu pazaryerine bagli hesaplar var. Once iliskili kayitlari temizlemelisin.", close_dialog=False)

            if _table_exists(session, LogisticsCargoProvider.__tablename__):
                linked_providers = session.exec(
                    select(LogisticsCargoProvider).where(
                        (LogisticsCargoProvider.platform_id == int(getattr(row, "pk", 0) or 0))
                        | (LogisticsCargoProvider.platformCode == normalized)
                    )
                ).all() or []
                if linked_providers:
                    return Result.fail("Bu pazaryerine bagli kargo firmalari var. Once iliskili kayitlari temizlemelisin.", close_dialog=False)

            session.delete(row)
            session.commit()
        invalidate_marketplace_runtime_cache()
        return Result.ok("Pazaryeri silindi.", close_dialog=False)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def set_marketplace_active_state(
    *,
    codes: list[str],
    is_active: bool,
    db_name: str | None = None,
) -> Result:
    try:
        normalized_codes = {
            canonical_platform_code(code)
            for code in list(codes or [])
            if canonical_platform_code(code)
        }
        if not normalized_codes:
            return Result.fail("Seçili pazaryeri bulunamadı.", close_dialog=False)
        engine = _engine(db_name)
        now_iso = _now_iso_text()
        with Session(engine) as session:
            rows = session.exec(
                select(Marketplace).where(Marketplace.code.in_(sorted(normalized_codes)))
            ).all() or []
            if not rows:
                return Result.fail("Seçili pazaryerleri önce kabul edilmelidir.", close_dialog=False)
            for row in rows:
                row.isActive = bool(is_active)
                row.updatedAt = now_iso
                session.add(row)
            session.commit()
        invalidate_marketplace_runtime_cache()
        return Result.ok("Pazaryeri durumları güncellendi.", close_dialog=False)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
