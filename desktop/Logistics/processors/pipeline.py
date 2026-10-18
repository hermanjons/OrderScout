from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from Core.db.models import SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER, coerce_source_id
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Logistics.constants.paths import cargo_provider_logos_dir
from Logistics.models.models import LogisticsCargoProvider
from Logistics.constants.catalog_constants import builtin_cargo_provider_records, clear_cargo_provider_catalog_cache
from Marketplaces.constants.catalog_constants import canonical_platform_code, marketplace_db_id_for_code
from settings import DB_NAME


def _compact_text(value) -> str:
    return str(value or "").strip()


def _now_iso_text() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _db_pk_or_none(payload: dict | None) -> int | None:
    try:
        parsed = int((payload or {}).get("dbPk") or 0)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _next_logistics_cargo_provider_source_id(*, db_name: str | None = None) -> int:
    max_source_id = 0
    for row in builtin_cargo_provider_records():
        try:
            max_source_id = max(max_source_id, int(row.get("sourceId") or row.get("source_id") or 0))
        except Exception:
            continue
    engine = get_engine(db_name or DB_NAME)
    with Session(engine) as session:
        source_ids = session.exec(select(LogisticsCargoProvider.sourceId)).all() or []
    for source_id in source_ids:
        try:
            max_source_id = max(max_source_id, int(source_id or 0))
        except Exception:
            continue
    return max_source_id + 1


def process_cargo_provider_logo(file_path: str) -> Result:
    try:
        clean = _compact_text(file_path)
        if not clean:
            return Result.ok("Logo kaldırıldı.", close_dialog=False, data={"path": None})

        src = Path(clean)
        if not src.exists() or not src.is_file():
            return Result.fail("Logo dosyası bulunamadı.", close_dialog=False)

        logos_dir = cargo_provider_logos_dir()
        try:
            if src.resolve().parent == logos_dir.resolve():
                return Result.ok("Logo hazır.", close_dialog=False, data={"path": str(src.resolve())})
        except Exception:
            pass

        new_name = f"{src.stem}_{uuid4().hex[:8]}{src.suffix.lower()}"
        save_path = logos_dir / new_name
        shutil.copy2(src, save_path)
        return Result.ok(
            "Logo başarıyla kaydedildi.",
            close_dialog=False,
            data={"path": str(save_path)},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def save_logistics_cargo_provider(
    provider_payload: dict,
    *,
    db_name: str | None = None,
) -> Result:
    try:
        payload = dict(provider_payload or {})
        name = _compact_text(payload.get("cargoProviderName"))
        if not name:
            return Result.fail("Kargo firması adı zorunludur.", close_dialog=False)

        platform_code = canonical_platform_code(payload.get("platformCode"))
        if not platform_code:
            return Result.fail("Geçerli bir platform seçilmelidir.", close_dialog=False)
        platform_id = marketplace_db_id_for_code(platform_code, db_name=db_name)
        if not platform_id:
            return Result.fail("Bu platform once kabul edilmelidir.", close_dialog=False)

        provider_code = _compact_text(payload.get("cargoProviderCode")).upper()
        if not provider_code:
            return Result.fail("Kargo firma kodu zorunludur.", close_dialog=False)

        logo_path = _compact_text(payload.get("logoPath")) or None
        if logo_path:
            logo_result = process_cargo_provider_logo(logo_path)
            if not logo_result.success:
                return logo_result
            logo_path = str((logo_result.data or {}).get("path") or "") or None

        source_type = _compact_text(payload.get("sourceType") or payload.get("source_type")).lower()
        if source_type not in {SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER}:
            source_type = SOURCE_TYPE_USER
        source_id = coerce_source_id(payload.get("sourceId") or payload.get("source_id"))

        engine = get_engine(db_name or DB_NAME)
        now_iso = _now_iso_text()
        requested_db_pk = _db_pk_or_none(payload)

        with Session(engine) as session:
            existing = session.exec(
                select(LogisticsCargoProvider).where(
                    LogisticsCargoProvider.platformCode == platform_code,
                    LogisticsCargoProvider.cargoProviderCode == provider_code,
                )
            ).first()

            if existing is not None and requested_db_pk is not None and int(getattr(existing, "pk", 0) or 0) != requested_db_pk:
                return Result.fail("Bu platform ve kod için kayıt zaten var.", close_dialog=False)
            if existing is not None and requested_db_pk is None:
                row = existing
            elif requested_db_pk is not None:
                row = session.exec(
                    select(LogisticsCargoProvider).where(LogisticsCargoProvider.pk == requested_db_pk)
                ).first()
                if row is None:
                    return Result.fail("Düzenlenecek kargo firması bulunamadı.", close_dialog=False)
            else:
                row = None

            resolved_source_id = source_id or (int(getattr(row, "sourceId", 0) or 0) if row is not None else 0)
            if resolved_source_id <= 0:
                resolved_source_id = _next_logistics_cargo_provider_source_id(db_name=db_name)

            if row is None:
                row = LogisticsCargoProvider(
                    platform_id=platform_id,
                    platformCode=platform_code,
                    cargoProviderCode=provider_code,
                    cargoProviderName=name,
                    logoPath=logo_path,
                    note=_compact_text(payload.get("note")) or None,
                    sourceType=source_type,
                    sourceId=resolved_source_id,
                    createdAt=now_iso,
                    updatedAt=now_iso,
                )
                session.add(row)
            else:
                row.platform_id = platform_id
                row.platformCode = platform_code
                row.cargoProviderCode = provider_code
                row.cargoProviderName = name
                row.logoPath = logo_path
                row.note = _compact_text(payload.get("note")) or None
                row.sourceType = source_type
                row.sourceId = resolved_source_id
                row.updatedAt = now_iso

            session.commit()
            session.refresh(row)
        clear_cargo_provider_catalog_cache(db_name=db_name)

        return Result.ok(
            "Kargo firması kaydedildi.",
            close_dialog=False,
            data={"pk": int(getattr(row, "pk", 0) or 0)},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def delete_logistics_cargo_provider(
    provider_pk: int,
    *,
    db_name: str | None = None,
) -> Result:
    try:
        normalized_pk = int(provider_pk or 0)
        if normalized_pk <= 0:
            return Result.fail("Silinecek kayıt bulunamadı.", close_dialog=False)

        engine = get_engine(db_name or DB_NAME)
        with Session(engine) as session:
            row = session.exec(
                select(LogisticsCargoProvider).where(LogisticsCargoProvider.pk == normalized_pk)
            ).first()
            if row is None:
                return Result.fail("Silinecek kayıt bulunamadı.", close_dialog=False)
            session.delete(row)
            session.commit()
        clear_cargo_provider_catalog_cache(db_name=db_name)

        return Result.ok("Kargo firması silindi.", close_dialog=False)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def accept_logistics_cargo_provider(
    provider_payload: dict,
    *,
    db_name: str | None = None,
) -> Result:
    try:
        payload = dict(provider_payload or {})
        if not bool(payload.get("isBuiltin")):
            return Result.fail("Bu kayıt önerilen bir kargo firması değil.", close_dialog=False)
        save_payload = {
            "platformCode": _compact_text(payload.get("platformCode")).upper(),
            "cargoProviderCode": _compact_text(payload.get("cargoProviderCode")).upper(),
            "cargoProviderName": _compact_text(payload.get("cargoProviderName")),
            "note": _compact_text(payload.get("note")) or None,
            "logoPath": None,
            "sourceType": SOURCE_TYPE_BUILTIN,
            "sourceId": coerce_source_id(payload.get("sourceId") or payload.get("source_id")),
        }
        result = save_logistics_cargo_provider(save_payload, db_name=db_name)
        if result.success:
            result.message = "Önerilen kargo firması kullanıma alındı."
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
