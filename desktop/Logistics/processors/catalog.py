from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Core.db.models import SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER, coerce_source_id
from Logistics.constants.paths import cargo_providers_file, cargo_tariffs_default_file
from Logistics.models.models import LogisticsCargoProvider
from Marketplaces.constants.catalog_constants import canonical_platform_code, load_default_marketplaces
from settings import ASSETS_DIR, DB_NAME


_CARGO_PROVIDERS_FILE = cargo_providers_file()
_DEFAULT_CARGO_TARIFFS_FILE = cargo_tariffs_default_file()
_CARGO_PROVIDER_CACHE_SIGNATURE: tuple[str, int, int] | None = None
_CARGO_PROVIDER_CACHE_MAP: dict[str, list[dict[str, Any]]] | None = None
_CARGO_PROVIDER_DB_ROWS_CACHE: dict[str, list[dict[str, Any]]] = {}
_CARGO_PROVIDER_LOOKUP_CACHE: dict[str, dict[str, Any]] = {}
_NORMALIZED_PLATFORM_CODE_CACHE: dict[str, str] = {}
_CARGO_PROVIDER_RESULT_CACHE: dict[tuple[str, str, str, str], Any] = {}
_DEFAULT_CARGO_TARIFF_CACHE_SIGNATURES: dict[str, tuple[str, int, int]] = {}
_DEFAULT_CARGO_TARIFF_CACHE_RECORDS: dict[str, list[dict[str, Any]]] = {}


def _compact_text(value) -> str:
    return str(value or "").strip()


def _load_required_json(path: Path):
    if not path.exists():
        raise RuntimeError(f"Gerekli config dosyası bulunamadı: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Config JSON okunamadı/bozuk: {path}") from exc


def _build_provider_key(platform_code: str, provider_code: str) -> str:
    return f"{_compact_text(platform_code).upper()}:{_compact_text(provider_code).upper()}"


def _normalize_platform_code(value: object) -> str:
    clean_source_id = coerce_source_id(value)
    if clean_source_id is not None:
        return _platform_code_for_source_id(clean_source_id)
    key = _compact_text(value).upper()
    if not key:
        return ""
    cached = _NORMALIZED_PLATFORM_CODE_CACHE.get(key)
    if cached is not None:
        return cached
    normalized = canonical_platform_code(value)
    _NORMALIZED_PLATFORM_CODE_CACHE[key] = normalized
    return normalized


def _platform_source_id(platform_code: str) -> int:
    normalized_code = canonical_platform_code(platform_code)
    for row in load_default_marketplaces():
        if canonical_platform_code(row.get("code")) == normalized_code:
            return int(coerce_source_id(row.get("sourceId") or row.get("source_id")) or 0)
    return 0


def _platform_code_for_source_id(platform_source_id: object) -> str:
    clean_source_id = coerce_source_id(platform_source_id)
    if clean_source_id is None:
        return ""
    for row in load_default_marketplaces():
        if coerce_source_id(row.get("sourceId") or row.get("source_id")) == clean_source_id:
            return canonical_platform_code(row.get("code"))
    return ""


def _normalize_logo_path(raw_logo_path: Any) -> str | None:
    clean = _compact_text(raw_logo_path)
    if not clean:
        return None
    full = os.path.abspath(clean)
    return full if os.path.exists(full) else clean


def _normalize_cargo_provider_seed_row(row: dict[str, Any], *, platform_code: str) -> dict[str, Any] | None:
    provider_code = _compact_text(row.get("code") or row.get("cargoProviderCode") or row.get("cargo_provider_code")).upper()
    provider_name = _compact_text(row.get("name") or row.get("cargoProviderName") or row.get("cargo_provider_name"))
    if not provider_code or not provider_name:
        return None
    platform_source_id = coerce_source_id(row.get("platformSourceId") or row.get("platform_source_id")) or _platform_source_id(platform_code)
    source_id = coerce_source_id(row.get("sourceId") or row.get("source_id"))
    if source_id is None:
        return None
    return {
        "key": _build_provider_key(platform_code, provider_code),
        "pk": int(source_id),
        "platformCode": platform_code,
        "platformSourceId": platform_source_id,
        "platform_source_id": platform_source_id,
        "cargoProviderCode": provider_code,
        "cargoProviderName": provider_name,
        "code": provider_code,
        "name": provider_name,
        "logoPath": _normalize_logo_path(row.get("logoPath")),
        "note": _compact_text(row.get("note")) or None,
        "isBuiltin": True,
        "hasUserOverride": False,
        "sourceType": SOURCE_TYPE_BUILTIN,
        "sourceId": source_id,
        "source_id": source_id,
    }


def _load_cargo_providers_by_platform(path: Path) -> dict[str, list[dict[str, Any]]]:
    parsed = _load_required_json(path)
    out: dict[str, list[dict[str, Any]]] = {}

    if isinstance(parsed, list) or (isinstance(parsed, dict) and isinstance(parsed.get("records"), list)):
        rows = parsed if isinstance(parsed, list) else list(parsed.get("records") or [])
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            platform_code = canonical_platform_code(
                row.get("platformCode")
                or row.get("platform")
                or row.get("platform_code")
                or _platform_code_for_source_id(row.get("platformSourceId") or row.get("platform_source_id"))
            )
            if not platform_code:
                continue
            normalized = _normalize_cargo_provider_seed_row(row, platform_code=platform_code)
            if normalized is None:
                continue
            provider_key = _compact_text(normalized.get("key")).casefold()
            if not provider_key or provider_key in seen:
                continue
            seen.add(provider_key)
            out.setdefault(platform_code, []).append(normalized)
        return out

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Kargo firması kataloğu hatalı formatta: {path}")

    for raw_platform, rows in parsed.items():
        platform_code = canonical_platform_code(raw_platform)
        if not platform_code or not isinstance(rows, list):
            continue
        providers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = _normalize_cargo_provider_seed_row(row, platform_code=platform_code)
            if normalized is None:
                continue
            provider_code = _compact_text(normalized.get("cargoProviderCode")).upper()
            if not provider_code or provider_code in seen:
                continue
            seen.add(provider_code)
            providers.append(normalized)
        out[platform_code] = providers
    return out


def _cargo_provider_catalog_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _builtin_cargo_providers_by_platform() -> dict[str, list[dict[str, Any]]]:
    global _CARGO_PROVIDER_CACHE_SIGNATURE, _CARGO_PROVIDER_CACHE_MAP

    signature = _cargo_provider_catalog_signature(_CARGO_PROVIDERS_FILE)
    if _CARGO_PROVIDER_CACHE_MAP is None or _CARGO_PROVIDER_CACHE_SIGNATURE != signature:
        _CARGO_PROVIDER_CACHE_SIGNATURE = signature
        _CARGO_PROVIDER_CACHE_MAP = _load_cargo_providers_by_platform(_CARGO_PROVIDERS_FILE)
    return dict(_CARGO_PROVIDER_CACHE_MAP or {})


def _user_cargo_provider_rows(*, db_name: str | None = None) -> list[dict[str, Any]]:
    cache_key = str(db_name or DB_NAME)
    cached = _CARGO_PROVIDER_DB_ROWS_CACHE.get(cache_key)
    if cached is not None:
        return [dict(row or {}) for row in cached]
    try:
        builtin_rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for rows in _builtin_cargo_providers_by_platform().values():
            for row in rows:
                platform_code = canonical_platform_code(row.get("platformCode"))
                provider_code = _compact_text(row.get("cargoProviderCode")).upper()
                if not platform_code or not provider_code:
                    continue
                builtin_rows_by_key[(platform_code, provider_code)] = dict(row or {})

        engine = get_engine(db_name or DB_NAME)
        with Session(engine) as session:
            rows = session.exec(
                select(LogisticsCargoProvider).order_by(
                    LogisticsCargoProvider.platformCode.asc(),
                    LogisticsCargoProvider.cargoProviderName.asc(),
                    LogisticsCargoProvider.cargoProviderCode.asc(),
                )
            ).all() or []
        out: list[dict[str, Any]] = []
        for row in rows:
            platform_code = canonical_platform_code(getattr(row, "platformCode", ""))
            provider_code = _compact_text(getattr(row, "cargoProviderCode", "")).upper()
            provider_name = _compact_text(getattr(row, "cargoProviderName", ""))
            if not platform_code or not provider_code or not provider_name:
                continue
            builtin_row = builtin_rows_by_key.get((platform_code, provider_code))
            source_type = SOURCE_TYPE_BUILTIN if builtin_row is not None else (_compact_text(getattr(row, "sourceType", "")) or SOURCE_TYPE_USER)
            source_id = (
                coerce_source_id((builtin_row or {}).get("sourceId") or (builtin_row or {}).get("source_id"))
                if builtin_row is not None
                else None
            ) or coerce_source_id(getattr(row, "sourceId", None))
            out.append(
                {
                    "key": _build_provider_key(platform_code, provider_code),
                    "pk": int(getattr(row, "pk", 0) or 0),
                    "dbPk": int(getattr(row, "pk", 0) or 0),
                    "platformCode": platform_code,
                    "platformSourceId": _platform_source_id(platform_code),
                    "platform_source_id": _platform_source_id(platform_code),
                    "cargoProviderCode": provider_code,
                    "cargoProviderName": provider_name,
                    "code": provider_code,
                    "name": provider_name,
                    "logoPath": _normalize_logo_path(getattr(row, "logoPath", None)),
                    "note": _compact_text(getattr(row, "note", "")) or None,
                    "createdAt": _compact_text(getattr(row, "createdAt", "")),
                    "updatedAt": _compact_text(getattr(row, "updatedAt", "")),
                    "isBuiltin": bool(builtin_row is not None),
                    "hasUserOverride": False,
                    "sourceType": source_type,
                    "sourceId": source_id,
                    "source_id": source_id,
                }
            )
        _CARGO_PROVIDER_DB_ROWS_CACHE[cache_key] = [dict(row or {}) for row in out]
        return [dict(row or {}) for row in out]
    except Exception:
        return []


def clear_cargo_provider_catalog_cache(*, db_name: str | None = None) -> None:
    if db_name in (None, ""):
        _CARGO_PROVIDER_DB_ROWS_CACHE.clear()
        _CARGO_PROVIDER_LOOKUP_CACHE.clear()
        _NORMALIZED_PLATFORM_CODE_CACHE.clear()
        _CARGO_PROVIDER_RESULT_CACHE.clear()
        _DEFAULT_CARGO_TARIFF_CACHE_SIGNATURES.clear()
        _DEFAULT_CARGO_TARIFF_CACHE_RECORDS.clear()
        return
    _CARGO_PROVIDER_DB_ROWS_CACHE.pop(str(db_name), None)
    _CARGO_PROVIDER_LOOKUP_CACHE.pop(str(db_name), None)
    cache_prefix = str(db_name)
    for key in list(_CARGO_PROVIDER_RESULT_CACHE):
        if len(key) > 1 and key[1] == cache_prefix:
            _CARGO_PROVIDER_RESULT_CACHE.pop(key, None)


def cargo_provider_records(
    platform_code: object | None = None,
    *,
    db_name: str | None = None,
) -> list[dict[str, Any]]:
    normalized_platform = _normalize_platform_code(platform_code)
    user_rows = _user_cargo_provider_rows(db_name=db_name)
    values = list(user_rows)
    if normalized_platform:
        values = [row for row in values if _compact_text(row.get("platformCode")).upper() == normalized_platform]

    values.sort(
        key=lambda row: (
            _compact_text(row.get("platformCode")).casefold(),
            _compact_text(row.get("cargoProviderName")).casefold(),
            _compact_text(row.get("cargoProviderCode")).casefold(),
        )
    )
    return values


def _cargo_provider_lookup(*, db_name: str | None = None) -> dict[str, Any]:
    cache_key = str(db_name or DB_NAME)
    cached = _CARGO_PROVIDER_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached

    records = cargo_provider_records(db_name=db_name)
    builtin_records = builtin_cargo_provider_records()
    record_by_source_id: dict[int, dict[str, Any]] = {}
    record_by_platform_code: dict[tuple[str, str], dict[str, Any]] = {}
    record_by_code: dict[str, dict[str, Any]] = {}
    source_id_by_platform_code: dict[tuple[str, str], int] = {}
    source_id_by_code: dict[str, int] = {}
    name_by_platform_code: dict[tuple[str, str], str] = {}
    name_by_code: dict[str, str] = {}
    code_by_source_id: dict[int, str] = {}

    for row in builtin_records:
        platform = _compact_text((row or {}).get("platformCode")).upper()
        provider_code = _compact_text((row or {}).get("cargoProviderCode")).upper()
        provider_name = _compact_text((row or {}).get("cargoProviderName"))
        source_id = coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
        if source_id is not None:
            record_by_source_id.setdefault(source_id, dict(row or {}))
            code_by_source_id.setdefault(source_id, provider_code)
        if platform and provider_code:
            record_by_platform_code.setdefault((platform, provider_code), dict(row or {}))
            if source_id is not None:
                source_id_by_platform_code.setdefault((platform, provider_code), source_id)
            if provider_name:
                name_by_platform_code.setdefault((platform, provider_code), provider_name)
        if provider_code:
            record_by_code.setdefault(provider_code, dict(row or {}))
            if source_id is not None:
                source_id_by_code.setdefault(provider_code, source_id)
            if provider_name:
                name_by_code.setdefault(provider_code, provider_name)

    for row in records:
        platform = _compact_text((row or {}).get("platformCode")).upper()
        provider_code = _compact_text((row or {}).get("cargoProviderCode")).upper()
        provider_name = _compact_text((row or {}).get("cargoProviderName"))
        source_id = coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
        if source_id is not None:
            record_by_source_id[source_id] = dict(row or {})
            code_by_source_id[source_id] = provider_code
        if platform and provider_code:
            record_by_platform_code[(platform, provider_code)] = dict(row or {})
            if source_id is not None:
                source_id_by_platform_code[(platform, provider_code)] = source_id
            if provider_name:
                name_by_platform_code[(platform, provider_code)] = provider_name
        if provider_code:
            record_by_code.setdefault(provider_code, dict(row or {}))
            if source_id is not None:
                source_id_by_code.setdefault(provider_code, source_id)
            if provider_name:
                name_by_code.setdefault(provider_code, provider_name)

    payload = {
        "record_by_source_id": record_by_source_id,
        "record_by_platform_code": record_by_platform_code,
        "record_by_code": record_by_code,
        "source_id_by_platform_code": source_id_by_platform_code,
        "source_id_by_code": source_id_by_code,
        "name_by_platform_code": name_by_platform_code,
        "name_by_code": name_by_code,
        "code_by_source_id": code_by_source_id,
    }
    _CARGO_PROVIDER_LOOKUP_CACHE[cache_key] = payload
    return payload


def builtin_cargo_provider_records(
    platform_code: object | None = None,
) -> list[dict[str, Any]]:
    normalized_platform = _normalize_platform_code(platform_code)
    providers_by_platform = _builtin_cargo_providers_by_platform()
    values: list[dict[str, Any]] = []
    for rows in providers_by_platform.values():
        values.extend(dict(row or {}) for row in rows)
    if normalized_platform:
        values = [row for row in values if _compact_text(row.get("platformCode")).upper() == normalized_platform]
    values.sort(
        key=lambda row: (
            _compact_text(row.get("platformCode")).casefold(),
            _compact_text(row.get("cargoProviderName")).casefold(),
            _compact_text(row.get("cargoProviderCode")).casefold(),
        )
    )
    return values


def cargo_provider_options(
    platform_code: object | None = None,
    *,
    include_all: bool = True,
    db_name: str | None = None,
) -> list[tuple[str, str]]:
    options = [
        (_compact_text(row.get("cargoProviderName")), _compact_text(row.get("cargoProviderCode")).upper())
        for row in cargo_provider_records(platform_code, db_name=db_name)
        if _compact_text(row.get("cargoProviderName")) and _compact_text(row.get("cargoProviderCode"))
    ]
    return ([("Tümü", "")] + options) if include_all else options


def cargo_provider_simple_records(
    platform_code: object | None = None,
    *,
    db_name: str | None = None,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in cargo_provider_records(platform_code, db_name=db_name):
        if not isinstance(row, dict):
            continue
        code = _compact_text(row.get("code") or row.get("cargoProviderCode")).upper()
        name = _compact_text(row.get("name") or row.get("cargoProviderName"))
        if not code or not name or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": name})
    return out


def changeable_cargo_provider_records(
    platform_code: object | None = None,
    *,
    db_name: str | None = None,
) -> list[dict[str, str]]:
    """Canonical provider choices shared by Orders UI and agent operations."""

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    candidates = [
        *builtin_cargo_provider_records(platform_code),
        *cargo_provider_records(platform_code, db_name=db_name),
    ]
    for row in candidates:
        if not isinstance(row, dict):
            continue
        code = _compact_text(row.get("code") or row.get("cargoProviderCode")).upper()
        name = _compact_text(row.get("name") or row.get("cargoProviderName"))
        if not code or not name or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": name})
    return out


def cargo_provider_record_for_source_id(
    source_id: object,
    *,
    db_name: str | None = None,
) -> dict[str, Any] | None:
    normalized_source_id = coerce_source_id(source_id)
    if normalized_source_id is None:
        return None
    row = (_cargo_provider_lookup(db_name=db_name).get("record_by_source_id") or {}).get(normalized_source_id)
    return dict(row or {}) if row is not None else None


def cargo_provider_source_id_for_code(
    code: object,
    *,
    platform_code: object | None = None,
    db_name: str | None = None,
) -> int | None:
    provider_code = _compact_text(code).upper()
    normalized_platform = _normalize_platform_code(platform_code)
    if not provider_code:
        return None
    cache_key = ("source_id_for_code", str(db_name or DB_NAME), normalized_platform, provider_code)
    if cache_key in _CARGO_PROVIDER_RESULT_CACHE:
        return _CARGO_PROVIDER_RESULT_CACHE[cache_key]
    rows = cargo_provider_records(normalized_platform or None, db_name=db_name)
    if len(rows) <= 32:
        for row in rows:
            if _compact_text(row.get("cargoProviderCode")).upper() == provider_code:
                result = coerce_source_id(row.get("sourceId") or row.get("source_id"))
                _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
                return result
        if normalized_platform:
            for row in builtin_cargo_provider_records(normalized_platform):
                if _compact_text(row.get("cargoProviderCode")).upper() == provider_code:
                    result = coerce_source_id(row.get("sourceId") or row.get("source_id"))
                    _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
                    return result
        for row in builtin_cargo_provider_records():
            if _compact_text(row.get("cargoProviderCode")).upper() == provider_code:
                result = coerce_source_id(row.get("sourceId") or row.get("source_id"))
                _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
                return result
        _CARGO_PROVIDER_RESULT_CACHE[cache_key] = None
        return None
    lookup = _cargo_provider_lookup(db_name=db_name)
    source_id = None
    if normalized_platform:
        source_id = (lookup.get("source_id_by_platform_code") or {}).get((normalized_platform, provider_code))
    if source_id is None:
        source_id = (lookup.get("source_id_by_code") or {}).get(provider_code)
    _CARGO_PROVIDER_RESULT_CACHE[cache_key] = source_id
    return source_id


def cargo_provider_code_for_source_id(
    source_id: object,
    *,
    db_name: str | None = None,
) -> str:
    raw_cache_key = ("code_for_source_id", str(db_name or DB_NAME), "", str(source_id or ""))
    if raw_cache_key in _CARGO_PROVIDER_RESULT_CACHE:
        return str(_CARGO_PROVIDER_RESULT_CACHE[raw_cache_key] or "")
    normalized_source_id = coerce_source_id(source_id)
    if normalized_source_id is None:
        return ""
    cache_key = ("code_for_source_id", str(db_name or DB_NAME), "", str(normalized_source_id))
    if cache_key in _CARGO_PROVIDER_RESULT_CACHE:
        result = str(_CARGO_PROVIDER_RESULT_CACHE[cache_key] or "")
        _CARGO_PROVIDER_RESULT_CACHE[raw_cache_key] = result
        return result
    rows = cargo_provider_records(db_name=db_name)
    if len(rows) <= 32:
        for row in rows:
            if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) == normalized_source_id:
                result = _compact_text((row or {}).get("cargoProviderCode")).upper()
                _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
                _CARGO_PROVIDER_RESULT_CACHE[raw_cache_key] = result
                return result
        for row in builtin_cargo_provider_records():
            if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) == normalized_source_id:
                result = _compact_text((row or {}).get("cargoProviderCode")).upper()
                _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
                _CARGO_PROVIDER_RESULT_CACHE[raw_cache_key] = result
                return result
        _CARGO_PROVIDER_RESULT_CACHE[cache_key] = ""
        _CARGO_PROVIDER_RESULT_CACHE[raw_cache_key] = ""
        return ""
    lookup = _cargo_provider_lookup(db_name=db_name)
    result = _compact_text((lookup.get("code_by_source_id") or {}).get(normalized_source_id)).upper()
    _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
    _CARGO_PROVIDER_RESULT_CACHE[raw_cache_key] = result
    return result


def cargo_provider_name_for_code(
    code: object,
    *,
    platform_code: object | None = None,
    db_name: str | None = None,
) -> str:
    provider_code = _compact_text(code).upper()
    if not provider_code:
        return ""
    normalized_platform = _normalize_platform_code(platform_code)
    cache_key = ("name_for_code", str(db_name or DB_NAME), normalized_platform, provider_code)
    if cache_key in _CARGO_PROVIDER_RESULT_CACHE:
        return str(_CARGO_PROVIDER_RESULT_CACHE[cache_key] or "")
    rows = cargo_provider_records(normalized_platform or None, db_name=db_name)
    if len(rows) <= 32:
        for row in rows:
            if _compact_text(row.get("cargoProviderCode")).upper() == provider_code:
                result = _compact_text(row.get("cargoProviderName"))
                _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
                return result
        for row in cargo_provider_records(db_name=db_name):
            if _compact_text(row.get("cargoProviderCode")).upper() == provider_code:
                result = _compact_text(row.get("cargoProviderName"))
                _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
                return result
        for row in builtin_cargo_provider_records(normalized_platform) if normalized_platform else []:
            if _compact_text(row.get("cargoProviderCode")).upper() == provider_code:
                result = _compact_text(row.get("cargoProviderName"))
                _CARGO_PROVIDER_RESULT_CACHE[cache_key] = result
                return result
        _CARGO_PROVIDER_RESULT_CACHE[cache_key] = ""
        return ""
    lookup = _cargo_provider_lookup(db_name=db_name)
    name = ""
    if normalized_platform:
        name = _compact_text((lookup.get("name_by_platform_code") or {}).get((normalized_platform, provider_code)))
    if not name:
        name = _compact_text((lookup.get("name_by_code") or {}).get(provider_code))
    if not name and normalized_platform:
        for row in builtin_cargo_provider_records(normalized_platform):
            if _compact_text(row.get("cargoProviderCode")).upper() == provider_code:
                name = _compact_text(row.get("cargoProviderName"))
                break
    _CARGO_PROVIDER_RESULT_CACHE[cache_key] = name
    return name


def default_cargo_tariffs_file() -> Path:
    return _DEFAULT_CARGO_TARIFFS_FILE


def default_cargo_tariff_records(path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path not in (None, "") else _DEFAULT_CARGO_TARIFFS_FILE
    if not target.exists():
        return []
    cache_key = str(target)
    try:
        signature = _cargo_provider_catalog_signature(target)
        cached = _DEFAULT_CARGO_TARIFF_CACHE_RECORDS.get(cache_key)
        if cached is not None and _DEFAULT_CARGO_TARIFF_CACHE_SIGNATURES.get(cache_key) == signature:
            return [dict(row or {}) for row in cached]
        parsed = _load_required_json(target)
    except Exception:
        return []
    records = parsed.get("records") if isinstance(parsed, dict) else parsed
    if not isinstance(records, list):
        return []
    out = [dict(row or {}) for row in records if isinstance(row, dict)]
    _DEFAULT_CARGO_TARIFF_CACHE_SIGNATURES[cache_key] = signature
    _DEFAULT_CARGO_TARIFF_CACHE_RECORDS[cache_key] = [dict(row or {}) for row in out]
    return [dict(row or {}) for row in out]


def default_cargo_provider_logo() -> str:
    return str(ASSETS_DIR / "logistics-cargo-providers-icon.png")
