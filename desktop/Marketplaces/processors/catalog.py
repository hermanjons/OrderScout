from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session, select

from Core.processors.operation_contracts import OperationMetadata
from Core.utils.model_utils import get_engine
from Core.db.models import SOURCE_TYPE_BUILTIN, SOURCE_TYPE_USER, coerce_source_id
from Marketplaces.constants.paths import (
    DEFAULT_MARKETPLACES_FILE,
    MARKETPLACE_LABEL_OVERRIDES_FILE,
    ensure_marketplaces_paths,
    platform_api_config_file,
    platform_cargo_config_file,
)
from Marketplaces.models.models import Marketplace
from settings import DB_NAME

_MARKETPLACE_CACHE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None
_MARKETPLACE_CACHE_RECORDS: list[dict[str, Any]] | None = None
_PLATFORM_API_CONFIG_CACHE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None
_PLATFORM_API_CONFIG_CACHE_RECORD: dict[str, Any] | None = None
_PLATFORM_API_CONFIG_CACHE_VERSION = 0
_MARKETPLACE_DB_ROWS_CACHE: dict[str, list[dict[str, Any]]] = {}
_CANONICAL_PLATFORM_LOOKUP_CACHE: dict[str, tuple[dict[str, str], set[str]]] = {}
_PLATFORM_CARGO_CONFIG_CACHE: dict[str, dict[str, Any]] = {}
_MARKETPLACE_LOOKUP_CACHE: dict[str, dict[str, Any]] = {}
_MARKETPLACE_RESULT_CACHE: dict[tuple[str, str, str], Any] = {}
_API_SCOPE_PROFILE_CACHE: dict[tuple[int, str, str, str], dict[str, Any]] = {}
_API_OPERATION_PROFILE_CACHE: dict[tuple[int, str, str, str, str], dict[str, Any]] = {}
_ACCOUNT_PROFILE_CACHE: dict[tuple[int, str], dict[str, Any]] = {}
_ACCOUNT_HEALTH_PROFILE_CACHE: dict[tuple[int, str, str], dict[str, Any]] = {}
_MARKETPLACE_LABEL_OVERRIDES_SIGNATURE: tuple[str, int, int] | None = None
_MARKETPLACE_LABEL_OVERRIDES_CACHE: dict[str, str] | None = None
_PLATFORM_SELECT_OPTIONS_CACHE: dict[tuple[str, bool, bool], tuple[tuple[str, str], ...]] = {}
_PLATFORM_ALL_OPTION = ("T\u00fcm\u00fc", "")

_ACCOUNT_FORM_FIELD_KEYS: set[str] = {
    "seller_id",
    "comp_name",
    "api_key",
    "api_secret",
    "integration_code",
    "token",
    "extra_config",
}

_CARGO_FORM_FIELD_KEYS: set[str] = {
    "cargoProvider",
    "desiRange",
    "salePriceRange",
    "amount",
    "vatRate",
}


def _compact_text(value: object) -> str:
    return str(value or "").strip()


def normalize_marketplace_environment(value: object, *, default: str = "production") -> str:
    text = _compact_text(value).casefold()
    if not text:
        text = _compact_text(default).casefold()
    if text in {"prod", "production", "live"}:
        return "production"
    if text in {"stage", "staging", "test"}:
        return "stage"
    raise ValueError(f"Desteklenmeyen marketplace environment: {value!r}")


def _normalize_environment_base_urls(
    value: object,
    *,
    fallback: dict[str, str] | None = None,
    legacy_base_url: object = None,
) -> dict[str, str]:
    out = {
        normalize_marketplace_environment(key): _compact_text(url).rstrip("/")
        for key, url in dict(fallback or {}).items()
        if _compact_text(url)
    }
    if isinstance(value, dict):
        for key, url in value.items():
            clean_url = _compact_text(url).rstrip("/")
            if clean_url:
                out[normalize_marketplace_environment(key)] = clean_url
    legacy = _compact_text(legacy_base_url).rstrip("/")
    if legacy:
        out["production"] = legacy
    return out


def _read_json_required(path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw)


def _read_json_optional_dict(path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _write_json(path, data: Any) -> None:
    ensure_marketplaces_paths()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_file_signature(path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def normalize_marketplace_code(value: object) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def coerce_marketplace_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "evet", "yes", "on"}:
        return True
    if text in {"0", "false", "hayir", "hayÄ±r", "no", "off"}:
        return False
    return bool(default)


def _normalize_logo_path(value: object) -> str:
    return str(value or "").strip().replace("\\", "/")


def coerce_marketplace_row(row: dict[str, Any], *, builtin: bool) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    code = normalize_marketplace_code(row.get("code"))
    label = str(row.get("label") or "").strip()
    if not code or not label:
        return None

    packed: dict[str, Any] = {
        "code": code,
        "label": label,
        "defaultLabel": label,
        "description": str(row.get("description") or "").strip(),
        "logoPath": _normalize_logo_path(row.get("logoPath")),
        "isActive": coerce_marketplace_bool(row.get("isActive"), True),
        "isBuiltin": bool(builtin),
        "key": code,
        "sourceType": SOURCE_TYPE_BUILTIN if builtin else SOURCE_TYPE_USER,
        "sourceId": coerce_source_id(row.get("sourceId") or row.get("source_id")),
        "source_id": coerce_source_id(row.get("sourceId") or row.get("source_id")),
    }
    return packed


def load_default_marketplaces() -> list[dict[str, Any]]:
    global _MARKETPLACE_CACHE_SIGNATURE, _MARKETPLACE_CACHE_RECORDS

    signature = _json_file_signature(DEFAULT_MARKETPLACES_FILE)
    if _MARKETPLACE_CACHE_RECORDS is not None and _MARKETPLACE_CACHE_SIGNATURE == signature:
        return [dict(row or {}) for row in _MARKETPLACE_CACHE_RECORDS]

    raw = _read_json_required(DEFAULT_MARKETPLACES_FILE)
    rows = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        packed = coerce_marketplace_row(row, builtin=True)
        if packed is None:
            continue
        code = str(packed["code"])
        if code in seen:
            continue
        seen.add(code)
        out.append(packed)
    _MARKETPLACE_CACHE_SIGNATURE = signature
    _MARKETPLACE_CACHE_RECORDS = [dict(row or {}) for row in out]
    return [dict(row or {}) for row in out]


def builtin_marketplace_codes() -> tuple[str, ...]:
    return tuple(
        _compact_text(row.get("code")).upper()
        for row in load_default_marketplaces()
        if _compact_text(row.get("code"))
    )


def builtin_marketplace_records() -> list[dict[str, Any]]:
    return [dict(row or {}) for row in load_default_marketplaces()]


def _marketplace_db_rows(*, db_name: str | None = None) -> list[dict[str, Any]]:
    cache_key = str(db_name or DB_NAME)
    cached = _MARKETPLACE_DB_ROWS_CACHE.get(cache_key)
    if cached is not None:
        return [dict(row or {}) for row in cached]
    try:
        builtin_by_code = {
            _compact_text(row.get("code")).upper(): dict(row or {})
            for row in load_default_marketplaces()
            if _compact_text(row.get("code"))
        }
        engine = get_engine(db_name or DB_NAME)
        with Session(engine) as session:
            rows = session.exec(
                select(Marketplace).order_by(Marketplace.label.asc(), Marketplace.code.asc())
            ).all() or []
        records = [
            {
                "pk": int(getattr(row, "pk", 0) or 0),
                "code": _compact_text(getattr(row, "code", "")).upper(),
                "label": _compact_text(getattr(row, "label", "")),
                "defaultLabel": _compact_text(getattr(row, "label", "")),
                "description": _compact_text(getattr(row, "description", "")),
                "logoPath": _normalize_logo_path(getattr(row, "logoPath", "")),
                "isActive": bool(getattr(row, "isActive", True)),
                "key": _compact_text(getattr(row, "code", "")).upper(),
                "sourceType": (
                    SOURCE_TYPE_BUILTIN
                    if _compact_text(getattr(row, "code", "")).upper() in builtin_by_code
                    else _compact_text(getattr(row, "sourceType", "")) or SOURCE_TYPE_USER
                ),
                "sourceId": (
                    coerce_source_id(
                        builtin_by_code.get(_compact_text(getattr(row, "code", "")).upper(), {}).get("sourceId")
                        or builtin_by_code.get(_compact_text(getattr(row, "code", "")).upper(), {}).get("source_id")
                    )
                    or coerce_source_id(getattr(row, "sourceId", None))
                ),
                "source_id": (
                    coerce_source_id(
                        builtin_by_code.get(_compact_text(getattr(row, "code", "")).upper(), {}).get("sourceId")
                        or builtin_by_code.get(_compact_text(getattr(row, "code", "")).upper(), {}).get("source_id")
                    )
                    or coerce_source_id(getattr(row, "sourceId", None))
                ),
            }
            for row in rows
            if _compact_text(getattr(row, "code", ""))
        ]
        _MARKETPLACE_DB_ROWS_CACHE[cache_key] = [dict(row or {}) for row in records]
        return [dict(row or {}) for row in records]
    except Exception:
        return []


def load_marketplace_label_overrides() -> dict[str, str]:
    global _MARKETPLACE_LABEL_OVERRIDES_SIGNATURE, _MARKETPLACE_LABEL_OVERRIDES_CACHE

    try:
        signature = _json_file_signature(MARKETPLACE_LABEL_OVERRIDES_FILE)
    except FileNotFoundError:
        _MARKETPLACE_LABEL_OVERRIDES_SIGNATURE = None
        _MARKETPLACE_LABEL_OVERRIDES_CACHE = {}
        return {}

    if (
        _MARKETPLACE_LABEL_OVERRIDES_CACHE is not None
        and _MARKETPLACE_LABEL_OVERRIDES_SIGNATURE == signature
    ):
        return dict(_MARKETPLACE_LABEL_OVERRIDES_CACHE)

    raw = _read_json_optional_dict(MARKETPLACE_LABEL_OVERRIDES_FILE)
    out: dict[str, str] = {}
    for raw_code, raw_label in raw.items():
        code = normalize_marketplace_code(raw_code)
        label = str(raw_label or "").strip()
        if not code or not label:
            continue
        out[code] = label
    _MARKETPLACE_LABEL_OVERRIDES_SIGNATURE = signature
    _MARKETPLACE_LABEL_OVERRIDES_CACHE = dict(out)
    return out


def persist_marketplace_label_override(code: str, label: str) -> None:
    key = normalize_marketplace_code(code)
    if not key:
        return
    defaults = {str(row["code"]): row for row in load_default_marketplaces()}
    if key not in defaults:
        raise RuntimeError(f"Bilinmeyen yerleÅŸik pazaryeri kodu: {key}")

    default_label = str(defaults[key].get("label") or key).strip()
    overrides = load_marketplace_label_overrides()
    normalized_label = str(label or "").strip()
    if not normalized_label or normalized_label == default_label:
        overrides.pop(key, None)
    else:
        overrides[key] = normalized_label
    _write_json(MARKETPLACE_LABEL_OVERRIDES_FILE, overrides)
    _invalidate_marketplace_cache()


def reset_marketplace_label_override(code: str) -> None:
    key = normalize_marketplace_code(code)
    if not key:
        return
    overrides = load_marketplace_label_overrides()
    if key in overrides:
        overrides.pop(key, None)
        _write_json(MARKETPLACE_LABEL_OVERRIDES_FILE, overrides)
        _invalidate_marketplace_cache()


def merge_marketplaces() -> list[dict[str, Any]]:
    defaults = load_default_marketplaces()
    overrides = load_marketplace_label_overrides()
    records: list[dict[str, Any]] = []
    for row in defaults:
        code = str(row.get("code") or "").strip().upper()
        record = dict(row)
        override_label = str(overrides.get(code) or "").strip()
        has_override = bool(override_label and override_label != str(row.get("label") or "").strip())
        if has_override:
            record["label"] = override_label
            record["sourceCode"] = "override"
            record["sourceLabel"] = "YerleÅŸik + Etiket Ã–zelleÅŸtirmesi"
        else:
            record["sourceCode"] = "builtin"
            record["sourceLabel"] = "YerleÅŸik"
        record["hasLabelOverride"] = has_override
        records.append(record)

    return sorted(
        records,
        key=lambda item: (
            0 if bool(item.get("isActive")) else 1,
            str(item.get("label") or "").casefold(),
        ),
    )


def _marketplace_catalog_signature() -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for path in (DEFAULT_MARKETPLACES_FILE, MARKETPLACE_LABEL_OVERRIDES_FILE):
        try:
            stat = path.stat()
            signature.append((str(path), int(stat.st_mtime_ns), int(stat.st_size)))
        except FileNotFoundError:
            signature.append((str(path), -1, -1))
    return tuple(signature)


def _invalidate_marketplace_cache() -> None:
    global _MARKETPLACE_CACHE_SIGNATURE, _MARKETPLACE_CACHE_RECORDS
    global _PLATFORM_API_CONFIG_CACHE_SIGNATURE, _PLATFORM_API_CONFIG_CACHE_RECORD
    global _PLATFORM_API_CONFIG_CACHE_VERSION
    global _MARKETPLACE_LABEL_OVERRIDES_SIGNATURE, _MARKETPLACE_LABEL_OVERRIDES_CACHE
    _MARKETPLACE_CACHE_SIGNATURE = None
    _MARKETPLACE_CACHE_RECORDS = None
    _PLATFORM_API_CONFIG_CACHE_SIGNATURE = None
    _PLATFORM_API_CONFIG_CACHE_RECORD = None
    _PLATFORM_API_CONFIG_CACHE_VERSION += 1
    _MARKETPLACE_LABEL_OVERRIDES_SIGNATURE = None
    _MARKETPLACE_LABEL_OVERRIDES_CACHE = None
    _MARKETPLACE_DB_ROWS_CACHE.clear()
    _CANONICAL_PLATFORM_LOOKUP_CACHE.clear()
    _PLATFORM_CARGO_CONFIG_CACHE.clear()
    _MARKETPLACE_LOOKUP_CACHE.clear()
    _MARKETPLACE_RESULT_CACHE.clear()
    _API_SCOPE_PROFILE_CACHE.clear()
    _API_OPERATION_PROFILE_CACHE.clear()
    _ACCOUNT_PROFILE_CACHE.clear()
    _ACCOUNT_HEALTH_PROFILE_CACHE.clear()
    _PLATFORM_SELECT_OPTIONS_CACHE.clear()


def invalidate_marketplace_runtime_cache() -> None:
    _invalidate_marketplace_cache()


def marketplace_records(*, active_only: bool = False, db_name: str | None = None) -> list[dict[str, Any]]:
    records = list(_marketplace_db_rows(db_name=db_name))
    if active_only:
        return [row for row in records if bool(row.get("isActive"))]
    return records


def _marketplace_lookup(*, db_name: str | None = None) -> dict[str, Any]:
    cache_key = str(db_name or DB_NAME)
    cached = _MARKETPLACE_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached

    db_rows = _marketplace_db_rows(db_name=db_name)
    builtin_rows = builtin_marketplace_records()
    record_by_code: dict[str, dict[str, Any]] = {}
    record_by_source_id: dict[int, dict[str, Any]] = {}
    db_id_by_code: dict[str, int] = {}
    db_id_by_source_id: dict[int, int] = {}

    for row in builtin_rows:
        code = _compact_text((row or {}).get("code")).upper()
        source_id = coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
        if code:
            record_by_code.setdefault(code, dict(row or {}))
        if source_id is not None:
            record_by_source_id.setdefault(source_id, dict(row or {}))

    for row in db_rows:
        code = _compact_text((row or {}).get("code")).upper()
        source_id = coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
        if code:
            record_by_code[code] = dict(row or {})
            try:
                pk_value = int((row or {}).get("pk") or 0)
            except Exception:
                pk_value = 0
            if pk_value > 0:
                db_id_by_code[code] = pk_value
        if source_id is not None:
            record_by_source_id[source_id] = dict(row or {})
            try:
                pk_value = int((row or {}).get("pk") or 0)
            except Exception:
                pk_value = 0
            if pk_value > 0:
                db_id_by_source_id[source_id] = pk_value

    source_id_by_code = {
        code: coerce_source_id(row.get("sourceId") or row.get("source_id"))
        for code, row in record_by_code.items()
    }
    code_by_source_id = {
        source_id: _compact_text(row.get("code")).upper()
        for source_id, row in record_by_source_id.items()
        if _compact_text(row.get("code"))
    }
    payload = {
        "record_by_code": record_by_code,
        "record_by_source_id": record_by_source_id,
        "source_id_by_code": source_id_by_code,
        "code_by_source_id": code_by_source_id,
        "db_id_by_code": db_id_by_code,
        "db_id_by_source_id": db_id_by_source_id,
    }
    _MARKETPLACE_LOOKUP_CACHE[cache_key] = payload
    return payload


def _fast_platform_code(value: object, lookup: dict[str, Any] | None = None) -> str:
    text = _compact_text(value)
    if not text:
        return ""
    normalized_code = normalize_marketplace_code(text)
    lookup = lookup or _marketplace_lookup()
    source_by_code = lookup.get("source_id_by_code") or {}
    if normalized_code and normalized_code in source_by_code:
        return normalized_code
    label_lookup, _code_set = _canonical_platform_lookup()
    return label_lookup.get(text.casefold(), normalized_code or text.upper())


def _canonical_platform_lookup(*, db_name: str | None = None) -> tuple[dict[str, str], set[str]]:
    cache_key = str(db_name or DB_NAME)
    cached = _CANONICAL_PLATFORM_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached

    records = marketplace_records(db_name=db_name)
    if not records:
        records = builtin_marketplace_records()

    code_set = {
        str(row.get("code") or "").strip().upper()
        for row in records
        if str(row.get("code") or "").strip()
    }
    label_lookup = {
        str(row.get("label") or "").casefold(): str(row.get("code") or "").strip().upper()
        for row in records
        if str(row.get("label") or "").strip()
    }
    payload = (label_lookup, code_set)
    _CANONICAL_PLATFORM_LOOKUP_CACHE[cache_key] = payload
    return payload


def marketplace_codes(*, active_only: bool = False, db_name: str | None = None) -> list[str]:
    return [
        str(row.get("code") or "").strip().upper()
        for row in marketplace_records(active_only=active_only, db_name=db_name)
        if str(row.get("code") or "").strip()
    ]


def platform_record_for_code(value: object, *, db_name: str | None = None) -> dict[str, Any] | None:
    lookup = _marketplace_lookup(db_name=db_name)
    code = _fast_platform_code(value, lookup)
    if not code:
        return None
    row = (lookup.get("record_by_code") or {}).get(code)
    return dict(row or {}) if row is not None else None


def marketplace_record_for_source_id(source_id: object, *, db_name: str | None = None) -> dict[str, Any] | None:
    normalized_source_id = coerce_source_id(source_id)
    if normalized_source_id is None:
        return None
    lookup = _marketplace_lookup(db_name=db_name)
    row = (lookup.get("record_by_source_id") or {}).get(normalized_source_id)
    return dict(row or {}) if row is not None else None


def canonical_platform_code(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized_code = normalize_marketplace_code(text)
    label_lookup, code_set = _canonical_platform_lookup()
    if normalized_code and normalized_code in code_set:
        return normalized_code
    return label_lookup.get(text.casefold(), normalized_code or text.upper())


def platform_label_for_code(value: object, *, db_name: str | None = None) -> str:
    record = platform_record_for_code(value, db_name=db_name)
    if record is not None:
        return str(record.get("label") or "").strip()
    builtin = next(
        (
            dict(row or {})
            for row in builtin_marketplace_records()
            if _compact_text(row.get("code")).upper() == canonical_platform_code(value)
        ),
        None,
    )
    if builtin is not None:
        return _compact_text(builtin.get("label"))
    code = canonical_platform_code(value)
    return code.title() if code else ""


def marketplace_source_id_for_code(value: object, *, db_name: str | None = None) -> int | None:
    cache_key = ("source_id_for_code", str(db_name or DB_NAME), _compact_text(value).casefold())
    if cache_key in _MARKETPLACE_RESULT_CACHE:
        return _MARKETPLACE_RESULT_CACHE[cache_key]
    normalized_code = normalize_marketplace_code(value)
    if normalized_code:
        rows = marketplace_records(db_name=db_name)
        if len(rows) <= 32:
            for row in rows:
                if _compact_text((row or {}).get("code")).upper() == normalized_code:
                    result = coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
                    _MARKETPLACE_RESULT_CACHE[cache_key] = result
                    return result
            for row in builtin_marketplace_records():
                if _compact_text((row or {}).get("code")).upper() == normalized_code:
                    result = coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id"))
                    _MARKETPLACE_RESULT_CACHE[cache_key] = result
                    return result
    lookup = _marketplace_lookup(db_name=db_name)
    code = _fast_platform_code(value, lookup)
    if not code:
        return None
    result = (lookup.get("source_id_by_code") or {}).get(code)
    _MARKETPLACE_RESULT_CACHE[cache_key] = result
    return result


def marketplace_code_for_source_id(source_id: object, *, db_name: str | None = None) -> str:
    raw_cache_key = ("code_for_source_id", str(db_name or DB_NAME), str(source_id or ""))
    if raw_cache_key in _MARKETPLACE_RESULT_CACHE:
        return str(_MARKETPLACE_RESULT_CACHE[raw_cache_key] or "")
    normalized_source_id = coerce_source_id(source_id)
    if normalized_source_id is None:
        return ""
    cache_key = ("code_for_source_id", str(db_name or DB_NAME), str(normalized_source_id))
    if cache_key in _MARKETPLACE_RESULT_CACHE:
        result = str(_MARKETPLACE_RESULT_CACHE[cache_key] or "")
        _MARKETPLACE_RESULT_CACHE[raw_cache_key] = result
        return result
    rows = marketplace_records(db_name=db_name)
    if len(rows) <= 32:
        for row in rows:
            if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) == normalized_source_id:
                result = _compact_text((row or {}).get("code")).upper()
                _MARKETPLACE_RESULT_CACHE[cache_key] = result
                _MARKETPLACE_RESULT_CACHE[raw_cache_key] = result
                return result
        for row in builtin_marketplace_records():
            if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) == normalized_source_id:
                result = _compact_text((row or {}).get("code")).upper()
                _MARKETPLACE_RESULT_CACHE[cache_key] = result
                _MARKETPLACE_RESULT_CACHE[raw_cache_key] = result
                return result
    lookup = _marketplace_lookup(db_name=db_name)
    result = str((lookup.get("code_by_source_id") or {}).get(normalized_source_id) or "")
    _MARKETPLACE_RESULT_CACHE[cache_key] = result
    _MARKETPLACE_RESULT_CACHE[raw_cache_key] = result
    return result


def marketplace_db_id_for_source_id(source_id: object, *, db_name: str | None = None) -> int | None:
    normalized_source_id = coerce_source_id(source_id)
    if normalized_source_id is None:
        return None
    cache_key = ("db_id_for_source_id", str(db_name or DB_NAME), str(normalized_source_id))
    if cache_key in _MARKETPLACE_RESULT_CACHE:
        return _MARKETPLACE_RESULT_CACHE[cache_key]
    rows = _marketplace_db_rows(db_name=db_name)
    if len(rows) <= 32:
        for row in rows:
            if coerce_source_id((row or {}).get("sourceId") or (row or {}).get("source_id")) != normalized_source_id:
                continue
            try:
                marketplace_pk = int(row.get("pk") or 0)
            except Exception:
                marketplace_pk = 0
            if marketplace_pk > 0:
                _MARKETPLACE_RESULT_CACHE[cache_key] = marketplace_pk
                return marketplace_pk
        _MARKETPLACE_RESULT_CACHE[cache_key] = None
        return None
    lookup = _marketplace_lookup(db_name=db_name)
    result = (lookup.get("db_id_by_source_id") or {}).get(normalized_source_id)
    _MARKETPLACE_RESULT_CACHE[cache_key] = result
    return result


def marketplace_db_id_for_code(value: object, *, db_name: str | None = None) -> int | None:
    cache_key = ("db_id_for_code", str(db_name or DB_NAME), _compact_text(value).casefold())
    if cache_key in _MARKETPLACE_RESULT_CACHE:
        return _MARKETPLACE_RESULT_CACHE[cache_key]
    normalized_code = normalize_marketplace_code(value)
    if normalized_code:
        rows = _marketplace_db_rows(db_name=db_name)
        if len(rows) <= 32:
            for row in rows:
                if _compact_text(row.get("code")).upper() != normalized_code:
                    continue
                try:
                    marketplace_pk = int(row.get("pk") or 0)
                except Exception:
                    marketplace_pk = 0
                if marketplace_pk > 0:
                    _MARKETPLACE_RESULT_CACHE[cache_key] = marketplace_pk
                    return marketplace_pk
            _MARKETPLACE_RESULT_CACHE[cache_key] = None
            return None
    lookup = _marketplace_lookup(db_name=db_name)
    code = _fast_platform_code(value, lookup)
    if not code:
        return None
    result = (lookup.get("db_id_by_code") or {}).get(code)
    _MARKETPLACE_RESULT_CACHE[cache_key] = result
    return result


def platform_select_options(
    *,
    include_all: bool = True,
    active_only: bool = False,
    db_name: str | None = None,
) -> list[tuple[str, str]]:
    cache_key = (str(db_name or DB_NAME), bool(include_all), bool(active_only))
    cached = _PLATFORM_SELECT_OPTIONS_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    options = [
        (str(row.get("label") or "").strip(), str(row.get("code") or "").strip().upper())
        for row in marketplace_records(active_only=active_only, db_name=db_name)
        if str(row.get("label") or "").strip() and str(row.get("code") or "").strip()
    ]
    if include_all:
        options = [_PLATFORM_ALL_OPTION, *options]
    _PLATFORM_SELECT_OPTIONS_CACHE[cache_key] = tuple(options)
    return list(options)


def _normalize_account_enabled_fields(values: Any, *, fallback: list[str] | None = None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in list(values or []):
        field_name = str(raw or "").strip()
        if not field_name or field_name not in _ACCOUNT_FORM_FIELD_KEYS:
            continue
        key = field_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(field_name)
    if cleaned:
        return cleaned
    return list(fallback or sorted(_ACCOUNT_FORM_FIELD_KEYS))


def _normalize_account_field_labels(values: Any) -> dict[str, str]:
    labels: dict[str, str] = {}
    for raw_key, raw_label in dict(values or {}).items():
        field_name = str(raw_key or "").strip()
        label = str(raw_label or "").strip()
        if not field_name or not label:
            continue
        labels[field_name] = label
    return labels


def _normalize_status_messages(values: Any) -> dict[str, str]:
    return {
        str(code_value): str(message)
        for code_value, message in dict(values or {}).items()
        if str(code_value).strip()
    }


def _normalize_scope_services(values: Any) -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = {}
    for raw_key, raw_payload in dict(values or {}).items():
        service_key = str(raw_key or "").strip()
        if not service_key:
            continue
        payload = dict(raw_payload or {}) if isinstance(raw_payload, dict) else {}
        services[service_key] = {
            "label": str(payload.get("label") or service_key).strip(),
            "transactionTypes": [
                str(item).strip()
                for item in list(payload.get("transactionTypes") or [])
                if str(item).strip()
            ],
        }
    return services


def _normalize_operation_request_rules(values: Any) -> dict[str, list[dict[str, str]]]:
    normalized: dict[str, list[dict[str, str]]] = {"path": [], "query": [], "json": []}
    raw = dict(values or {}) if isinstance(values, dict) else {}
    for section_name in ("path", "query", "json"):
        items = list(raw.get(section_name) or [])
        rows: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            source_name = str(item.get("source") or "").strip()
            target_name = str(item.get("target") or source_name).strip()
            transform_name = str(item.get("transform") or "").strip()
            if not source_name or not target_name:
                continue
            rows.append(
                {
                    "source": source_name,
                    "target": target_name,
                    "transform": transform_name,
                }
            )
        normalized[section_name] = rows
    return normalized


def _normalize_visible_field_list(values: Any) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in list(values or []):
        field_name = str(raw or "").strip()
        if not field_name or field_name not in _CARGO_FORM_FIELD_KEYS or field_name in seen:
            continue
        seen.add(field_name)
        cleaned.append(field_name)
    return cleaned


def _load_platform_config_record(code: str) -> dict[str, Any] | None:
    path = platform_api_config_file(code)
    try:
        raw = _read_json_required(path)
    except FileNotFoundError:
        return None
    if not isinstance(raw, dict):
        raise RuntimeError(f"Platform API config JSON obje olmalÄ±dÄ±r: {path}")
    return raw


def _load_platform_cargo_config_record(code: str) -> dict[str, Any] | None:
    path = platform_cargo_config_file(code)
    try:
        raw = _read_json_required(path)
    except FileNotFoundError:
        return None
    if not isinstance(raw, dict):
        raise RuntimeError(f"Platform cargo config JSON obje olmalÄ±dÄ±r: {path}")
    return raw


def _platform_api_config_signature() -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = list(_marketplace_catalog_signature())
    for code in marketplace_codes():
        path = platform_api_config_file(code)
        try:
            stat = path.stat()
            signature.append((str(path), int(stat.st_mtime_ns), int(stat.st_size)))
        except FileNotFoundError:
            signature.append((str(path), -1, -1))
    return tuple(signature)


def load_platform_api_config() -> dict[str, Any]:
    global _PLATFORM_API_CONFIG_CACHE_SIGNATURE, _PLATFORM_API_CONFIG_CACHE_RECORD
    global _PLATFORM_API_CONFIG_CACHE_VERSION

    signature = _platform_api_config_signature()
    if _PLATFORM_API_CONFIG_CACHE_RECORD is not None and _PLATFORM_API_CONFIG_CACHE_SIGNATURE == signature:
        return _PLATFORM_API_CONFIG_CACHE_RECORD

    profiles: dict[str, Any] = {}

    all_codes = sorted({*marketplace_codes(), *builtin_marketplace_codes()})
    for code in all_codes:
        raw = _load_platform_config_record(code)
        if raw is None:
            continue

        common_status_messages = _normalize_status_messages(raw.get("commonStatusMessages") or {})
        common_base_urls = _normalize_environment_base_urls(
            raw.get("baseUrls"),
            legacy_base_url=raw.get("baseUrl"),
        )

        account_raw = raw.get("account") or {}
        if not isinstance(account_raw, dict):
            account_raw = {}

        account_payload = {
            "enabledFields": _normalize_account_enabled_fields(
                account_raw.get("enabledFields"),
                fallback=sorted(_ACCOUNT_FORM_FIELD_KEYS),
            ),
            "authStrategy": str(account_raw.get("authStrategy") or "").strip() or None,
            "fieldLabels": _normalize_account_field_labels(account_raw.get("fieldLabels") or {}),
        }

        profile: dict[str, Any] = {
            "account": account_payload,
            "baseUrls": common_base_urls,
            "scopes": {},
        }

        health_raw = raw.get("healthCheck") or {}
        if isinstance(health_raw, dict) and (health_raw.get("path") or health_raw.get("baseUrl")):
            health_base_urls = _normalize_environment_base_urls(
                health_raw.get("baseUrls"),
                fallback=common_base_urls,
                legacy_base_url=health_raw.get("baseUrl"),
            )
            profile["healthCheck"] = {
                "method": str(health_raw.get("method") or "GET").strip().upper() or "GET",
                "baseUrl": str(health_base_urls.get("production") or ""),
                "baseUrls": health_base_urls,
                "path": str(health_raw.get("path") or "").strip(),
                "queryDefaults": dict(health_raw.get("queryDefaults") or {}),
                "headers": dict(health_raw.get("headers") or {}),
                "timeout": int(health_raw.get("timeout") or 15),
                "successStatusCodes": [
                    int(code_value)
                    for code_value in list(health_raw.get("successStatusCodes") or [200])
                ],
                "requiredCredentials": [
                    str(field).strip()
                    for field in list(health_raw.get("requiredCredentials") or [])
                    if str(field).strip()
                ],
                "authStrategy": str(health_raw.get("authStrategy") or "none").strip() or "none",
                "statusMessages": {
                    **common_status_messages,
                    **_normalize_status_messages(health_raw.get("statusMessages") or {}),
                },
            }

        scopes_raw = raw.get("scopes") or {}
        if not isinstance(scopes_raw, dict):
            scopes_raw = {}

        scopes: dict[str, Any] = {}
        for scope_name, scope_payload in scopes_raw.items():
            if not isinstance(scope_payload, dict):
                continue

            scope_base_urls = _normalize_environment_base_urls(
                scope_payload.get("baseUrls"),
                fallback=common_base_urls,
                legacy_base_url=scope_payload.get("baseUrl"),
            )

            scope_common_status_messages = {
                **common_status_messages,
                **_normalize_status_messages(scope_payload.get("commonStatusMessages") or {}),
            }

            operations_raw = scope_payload.get("operations") or {}
            if not isinstance(operations_raw, dict):
                operations_raw = {}

            operations: dict[str, Any] = {}
            for operation_name, operation_payload in operations_raw.items():
                if not isinstance(operation_payload, dict):
                    continue
                operation_base_urls = _normalize_environment_base_urls(
                    operation_payload.get("baseUrls"),
                    fallback=scope_base_urls,
                    legacy_base_url=operation_payload.get("baseUrl"),
                )
                operations[operation_name] = {
                    "label": str(operation_payload.get("label") or operation_name).strip(),
                    "method": str(operation_payload.get("method") or "GET").strip().upper() or "GET",
                    "baseUrl": str(operation_base_urls.get("production") or ""),
                    "baseUrls": operation_base_urls,
                    "path": str(operation_payload.get("path") or "").strip(),
                    "queryDefaults": dict(operation_payload.get("queryDefaults") or {}),
                    "headers": dict(operation_payload.get("headers") or {}),
                    "timeout": int(operation_payload.get("timeout") or 15),
                    "successStatusCodes": [
                        int(code_value)
                        for code_value in list(operation_payload.get("successStatusCodes") or [200])
                    ],
                    "statusMessages": {
                        **scope_common_status_messages,
                        **_normalize_status_messages(operation_payload.get("statusMessages") or {}),
                    },
                    "errorCodeMessages": _normalize_status_messages(operation_payload.get("errorCodeMessages") or {}),
                    "successMessage": str(operation_payload.get("successMessage") or "").strip(),
                    "request": _normalize_operation_request_rules(operation_payload.get("request") or {}),
                }

            scopes[scope_name] = {
                "baseUrl": str(scope_base_urls.get("production") or ""),
                "baseUrls": scope_base_urls,
                "maxRangeDays": int(scope_payload.get("maxRangeDays") or 0),
                "safeRangeDays": int(scope_payload.get("safeRangeDays") or 0),
                "defaultFetchDays": int(scope_payload.get("defaultFetchDays") or 0),
                "defaultPageSize": int(scope_payload.get("defaultPageSize") or 0),
                "maxPageSize": int(scope_payload.get("maxPageSize") or 0),
                "defaultMaxPages": int(scope_payload.get("defaultMaxPages") or 0),
                "services": _normalize_scope_services(scope_payload.get("services") or {}),
                "supportedStatuses": [
                    str(item).strip()
                    for item in list(scope_payload.get("supportedStatuses") or [])
                    if str(item).strip()
                ],
                "statusLabels": _normalize_status_messages(scope_payload.get("statusLabels") or {}),
                "commonStatusMessages": scope_common_status_messages,
                "operations": operations,
            }

        profile["scopes"] = scopes
        profiles[code] = profile

    payload = {"profiles": profiles}
    _PLATFORM_API_CONFIG_CACHE_SIGNATURE = signature
    _PLATFORM_API_CONFIG_CACHE_RECORD = payload
    _PLATFORM_API_CONFIG_CACHE_VERSION += 1
    return payload


def _cached_platform_api_config() -> tuple[dict[str, Any], int]:
    payload = _PLATFORM_API_CONFIG_CACHE_RECORD
    if payload is None:
        payload = load_platform_api_config()
    return payload, _PLATFORM_API_CONFIG_CACHE_VERSION


def marketplace_cargo_config(value: object) -> dict[str, Any]:
    code = canonical_platform_code(value)
    if code in _PLATFORM_CARGO_CONFIG_CACHE:
        return dict(_PLATFORM_CARGO_CONFIG_CACHE[code])
    raw = _load_platform_cargo_config_record(code) or {}
    form_payload = dict(raw.get("form") or {})
    visible_fields = _normalize_visible_field_list(form_payload.get("visibleFields"))
    if not visible_fields:
        visible_fields = ["cargoProvider", "desiRange", "salePriceRange", "amount", "vatRate"]
    payload = {
        "platformCode": code,
        "form": {
            "visibleFields": visible_fields,
        },
    }
    _PLATFORM_CARGO_CONFIG_CACHE[code] = dict(payload)
    return dict(payload)


def marketplace_cargo_form_visible_fields(value: object) -> list[str]:
    config = marketplace_cargo_config(value)
    return list(dict(config.get("form") or {}).get("visibleFields") or [])


def marketplace_account_default_enabled_fields() -> list[str]:
    return list(sorted(_ACCOUNT_FORM_FIELD_KEYS))


def marketplace_account_profile(value: object) -> dict[str, Any]:
    code = canonical_platform_code(value)
    payload = load_platform_api_config()
    config_version = _PLATFORM_API_CONFIG_CACHE_VERSION
    cache_key = (config_version, code)
    cached = _ACCOUNT_PROFILE_CACHE.get(cache_key)
    if cached is not None:
        out = dict(cached)
        out["enabledFields"] = list(out.get("enabledFields") or [])
        out["fieldLabels"] = dict(out.get("fieldLabels") or {})
        return out

    profile = dict((payload.get("profiles") or {}).get(code) or {})
    account_payload = dict(profile.get("account") or {})
    account_payload["enabledFields"] = _normalize_account_enabled_fields(
        account_payload.get("enabledFields"),
        fallback=marketplace_account_default_enabled_fields(),
    )
    account_payload["fieldLabels"] = _normalize_account_field_labels(account_payload.get("fieldLabels") or {})
    account_payload["authStrategy"] = str(account_payload.get("authStrategy") or "").strip() or None
    account_payload["platformCode"] = code
    _ACCOUNT_PROFILE_CACHE[cache_key] = {
        **account_payload,
        "enabledFields": list(account_payload.get("enabledFields") or []),
        "fieldLabels": dict(account_payload.get("fieldLabels") or {}),
    }
    out = dict(_ACCOUNT_PROFILE_CACHE[cache_key])
    out["enabledFields"] = list(out.get("enabledFields") or [])
    out["fieldLabels"] = dict(out.get("fieldLabels") or {})
    return out


def marketplace_account_enabled_fields(value: object) -> set[str]:
    profile = marketplace_account_profile(value)
    return set(profile.get("enabledFields") or marketplace_account_default_enabled_fields())


def marketplace_account_field_label(value: object, field_name: object) -> str:
    profile = marketplace_account_profile(value)
    labels = dict(profile.get("fieldLabels") or {})
    key = str(field_name or "").strip()
    return str(labels.get(key) or key)


def marketplace_account_health_profile(
    value: object,
    environment: object = "production",
) -> dict[str, Any]:
    code = canonical_platform_code(value)
    environment_key = normalize_marketplace_environment(environment)
    payload = load_platform_api_config()
    config_version = _PLATFORM_API_CONFIG_CACHE_VERSION
    cache_key = (config_version, code, environment_key)
    cached = _ACCOUNT_HEALTH_PROFILE_CACHE.get(cache_key)
    if cached is not None:
        out = dict(cached)
        out["query"] = dict(out.get("query") or {})
        out["successStatusCodes"] = list(out.get("successStatusCodes") or [])
        out["requiredCredentials"] = list(out.get("requiredCredentials") or [])
        out["statusMessages"] = dict(out.get("statusMessages") or {})
        return out

    profile = dict((payload.get("profiles") or {}).get(code) or {})
    health = dict(profile.get("healthCheck") or {})
    base_urls = dict(health.get("baseUrls") or {})
    base_url = _compact_text(base_urls.get(environment_key)).rstrip("/")
    health["platformCode"] = code
    health["environment"] = environment_key
    health["baseUrls"] = base_urls
    health["baseUrl"] = base_url
    health["supportedEnvironments"] = sorted(base_urls)
    health["environmentSupported"] = bool(base_url)
    health["urlTemplate"] = f"{base_url}{str(health.get('path') or '')}" if base_url else ""
    health["query"] = dict(health.get("queryDefaults") or {})
    health["successStatusCodes"] = [int(item) for item in list(health.get("successStatusCodes") or [200])]
    health["requiredCredentials"] = [
        str(field).strip()
        for field in list(health.get("requiredCredentials") or [])
        if str(field).strip()
    ]
    health["statusMessages"] = _normalize_status_messages(health.get("statusMessages") or {})
    _ACCOUNT_HEALTH_PROFILE_CACHE[cache_key] = {
        **health,
        "baseUrls": dict(health.get("baseUrls") or {}),
        "query": dict(health.get("query") or {}),
        "successStatusCodes": list(health.get("successStatusCodes") or []),
        "requiredCredentials": list(health.get("requiredCredentials") or []),
        "statusMessages": dict(health.get("statusMessages") or {}),
    }
    out = dict(_ACCOUNT_HEALTH_PROFILE_CACHE[cache_key])
    out["baseUrls"] = dict(out.get("baseUrls") or {})
    out["query"] = dict(out.get("query") or {})
    out["successStatusCodes"] = list(out.get("successStatusCodes") or [])
    out["requiredCredentials"] = list(out.get("requiredCredentials") or [])
    out["statusMessages"] = dict(out.get("statusMessages") or {})
    return out


def marketplace_api_scope_profile(
    value: object,
    scope_name: object,
    environment: object = "production",
) -> dict[str, Any]:
    code = canonical_platform_code(value)
    scope_key = str(scope_name or "").strip()
    environment_key = normalize_marketplace_environment(environment)
    payload, config_version = _cached_platform_api_config()
    cache_key = (config_version, code, scope_key, environment_key)
    cached = _API_SCOPE_PROFILE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    scopes = dict(((payload.get("profiles") or {}).get(code) or {}).get("scopes") or {})
    scope = dict(scopes.get(scope_key) or {})
    base_urls = dict(scope.get("baseUrls") or {})
    base_url = _compact_text(base_urls.get(environment_key)).rstrip("/")
    scope["platformCode"] = code
    scope["scopeName"] = scope_key
    scope["environment"] = environment_key
    scope["baseUrls"] = base_urls
    scope["baseUrl"] = base_url
    scope["supportedEnvironments"] = sorted(base_urls)
    scope["environmentSupported"] = bool(base_url)
    scope["supportedStatuses"] = [
        str(item).strip()
        for item in list(scope.get("supportedStatuses") or [])
        if str(item).strip()
    ]
    scope["statusLabels"] = _normalize_status_messages(scope.get("statusLabels") or {})
    scope["commonStatusMessages"] = _normalize_status_messages(scope.get("commonStatusMessages") or {})
    _API_SCOPE_PROFILE_CACHE[cache_key] = scope
    return scope


def marketplace_api_operation_profile(
    value: object,
    scope_name: object,
    operation_name: object,
    environment: object = "production",
) -> dict[str, Any]:
    code = canonical_platform_code(value)
    scope_key = str(scope_name or "").strip()
    operation_key = str(operation_name or "").strip()
    environment_key = normalize_marketplace_environment(environment)
    _, config_version = _cached_platform_api_config()
    cache_key = (config_version, code, scope_key, operation_key, environment_key)
    cached = _API_OPERATION_PROFILE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    scope = marketplace_api_scope_profile(value, scope_name, environment_key)
    operations = dict(scope.get("operations") or {})
    operation = dict(operations.get(operation_key) or {})
    base_urls = dict(operation.get("baseUrls") or scope.get("baseUrls") or {})
    base_url = _compact_text(base_urls.get(environment_key)).rstrip("/")
    operation["platformCode"] = str(scope.get("platformCode") or "")
    operation["scopeName"] = str(scope.get("scopeName") or "")
    operation["operationName"] = operation_key
    operation["environment"] = environment_key
    operation["baseUrls"] = base_urls
    operation["baseUrl"] = base_url
    operation["supportedEnvironments"] = sorted(base_urls)
    operation["environmentSupported"] = bool(base_url)
    operation["successStatusCodes"] = [int(code_value) for code_value in list(operation.get("successStatusCodes") or [200])]
    operation["statusMessages"] = _normalize_status_messages(operation.get("statusMessages") or {})
    operation["errorCodeMessages"] = _normalize_status_messages(operation.get("errorCodeMessages") or {})
    method = str(operation.get("method") or "GET").strip().upper() or "GET"
    is_read = method in {"GET", "HEAD", "OPTIONS"}
    timeout_seconds = max(1, int(operation.get("timeout") or 15))
    operation["operationContract"] = OperationMetadata(
        name=f"{code.casefold()}.{scope_key}.{operation_key}",
        version="1.0",
        owner_domain="marketplaces",
        effect_class="read" if is_read else "external_mutation",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "object"},
                "query": {"type": "object"},
                "json": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "additionalProperties": True},
        record_ref_types=(f"{scope_key}.record",),
        environment_scope=tuple(sorted(base_urls)),
        account_scope="marketplace_account",
        risk_level="R0" if is_read else "R2",
        approval_policy="none" if is_read else "prepare_then_confirm",
        idempotency="safe" if is_read else "key_required",
        retry_behavior="safe" if is_read else "never_without_idempotency",
        supports_prepare=not is_read,
        supports_execute=True,
        supports_verify=not is_read,
        timeout_seconds=timeout_seconds,
        supports_cancellation=True,
        supports_progress=True,
        sensitive_fields=("api_key", "api_secret", "token", "authorization"),
        required_capabilities=(f"http:{method.casefold()}", f"marketplace:{code.casefold()}"),
    ).to_dict()
    _API_OPERATION_PROFILE_CACHE[cache_key] = operation
    return operation


def marketplace_api_status_message(
    value: object,
    scope_name: object,
    operation_name: object,
    status_code: object,
) -> str:
    operation = marketplace_api_operation_profile(value, scope_name, operation_name)
    status_messages = operation.get("statusMessages") or {}
    code = str(status_code or "").strip()
    return str(status_messages.get(code) or status_messages.get("*") or "").strip()


def marketplace_api_error_code_message(
    value: object,
    scope_name: object,
    operation_name: object,
    error_code: object,
) -> str:
    operation = marketplace_api_operation_profile(value, scope_name, operation_name)
    error_messages = operation.get("errorCodeMessages") or {}
    code = str(error_code or "").strip()
    return str(error_messages.get(code) or "").strip()


def marketplace_scope_supported_statuses(value: object, scope_name: object) -> list[str]:
    scope = marketplace_api_scope_profile(value, scope_name)
    return list(scope.get("supportedStatuses") or [])


def marketplace_scope_status_labels(value: object, scope_name: object) -> dict[str, str]:
    scope = marketplace_api_scope_profile(value, scope_name)
    return dict(scope.get("statusLabels") or {})


def marketplace_scope_status_list(value: object, scope_name: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in marketplace_scope_supported_statuses(value, scope_name):
        name = str(raw or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def marketplace_finance_service_definitions(value: object) -> dict[str, dict[str, Any]]:
    scope = marketplace_api_scope_profile(value, "finance")
    return {
        str(service_key): dict(service_payload or {})
        for service_key, service_payload in dict(scope.get("services") or {}).items()
        if str(service_key).strip()
    }


def marketplace_finance_service_options(value: object, *, include_all: bool = True) -> list[tuple[str, str]]:
    services = marketplace_finance_service_definitions(value)
    options = [
        (str(payload.get("label") or service_key).strip(), str(service_key))
        for service_key, payload in services.items()
        if str(service_key).strip()
    ]
    return ([("TÃ¼mÃ¼", "")] + options) if include_all else options


def marketplace_finance_transaction_types(value: object, service_key: object | None = None) -> list[str]:
    services = marketplace_finance_service_definitions(value)
    target_key = str(service_key or "").strip()
    if target_key:
        payload = dict(services.get(target_key) or {})
        return list(payload.get("transactionTypes") or [])

    all_types: set[str] = set()
    for payload in services.values():
        for item in list((payload or {}).get("transactionTypes") or []):
            text = str(item or "").strip()
            if text:
                all_types.add(text)
    return sorted(all_types)


def marketplace_finance_scope_int(value: object, field_name: object, default: int = 0) -> int:
    scope = marketplace_api_scope_profile(value, "finance")
    try:
        parsed = int(scope.get(str(field_name or "").strip()) or default)
    except Exception:
        parsed = int(default)
    return parsed
