from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from typing import Any

from Stock.constants.domain_constants import StockItemType
from Stock.constants.paths import (
    DEFAULT_SUB_GROUPS_FILE,
    DEFAULT_UPPER_GROUPS_FILE,
    ITEM_TYPE_OPTIONS_FILE,
    USER_SUB_GROUPS_FILE,
    USER_UPPER_GROUPS_FILE,
    ensure_constants_paths,
)

_ITEM_TYPE_CACHE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None
_ITEM_TYPE_CACHE_RECORDS: list[tuple[str, str]] | None = None
_UPPER_GROUP_CACHE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None
_UPPER_GROUP_CACHE_ROWS: list[dict[str, Any]] | None = None
_SUB_GROUP_CACHE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None
_SUB_GROUP_CACHE_MAP: dict[str, list[dict[str, Any]]] | None = None


def _now_iso_text() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _text_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).casefold()


def _read_json_required(path) -> Any:
    if not path.exists():
        raise RuntimeError(f"Gerekli config dosyasi bulunamadi: {path}")
    try:
        raw = path.read_text(encoding="utf-8-sig").strip()
        if not raw:
            raise RuntimeError(f"Config dosyasi bos: {path}")
        return json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"Config JSON okunamadi/bozuk: {path}") from exc


def _write_json(path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _path_signature(*paths) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
            signature.append((str(path), int(stat.st_mtime_ns), int(stat.st_size)))
        except FileNotFoundError:
            signature.append((str(path), -1, -1))
    return tuple(signature)


def _invalidate_catalog_cache() -> None:
    global _ITEM_TYPE_CACHE_SIGNATURE, _ITEM_TYPE_CACHE_RECORDS
    global _UPPER_GROUP_CACHE_SIGNATURE, _UPPER_GROUP_CACHE_ROWS
    global _SUB_GROUP_CACHE_SIGNATURE, _SUB_GROUP_CACHE_MAP
    _ITEM_TYPE_CACHE_SIGNATURE = None
    _ITEM_TYPE_CACHE_RECORDS = None
    _UPPER_GROUP_CACHE_SIGNATURE = None
    _UPPER_GROUP_CACHE_ROWS = None
    _SUB_GROUP_CACHE_SIGNATURE = None
    _SUB_GROUP_CACHE_MAP = None


def _normalize_string_list(values: list[Any]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value or "").strip()
        if not name:
            continue
        key = _text_key(name)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    return cleaned


def item_type_options() -> list[tuple[str, str]]:
    global _ITEM_TYPE_CACHE_SIGNATURE, _ITEM_TYPE_CACHE_RECORDS

    signature = _path_signature(ITEM_TYPE_OPTIONS_FILE)
    if _ITEM_TYPE_CACHE_RECORDS is not None and _ITEM_TYPE_CACHE_SIGNATURE == signature:
        return list(_ITEM_TYPE_CACHE_RECORDS)

    allowed_values = {item.value for item in StockItemType}
    raw = _read_json_required(ITEM_TYPE_OPTIONS_FILE)
    if not isinstance(raw, list):
        raise RuntimeError(f"Beklenen liste formati bulunamadi: {ITEM_TYPE_OPTIONS_FILE}")

    cleaned: list[tuple[str, str]] = []
    seen_values: set[str] = set()
    for row in raw:
        if isinstance(row, dict):
            label = str(row.get("label") or "").strip()
            value = str(row.get("value") or "").strip()
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            label = str(row[0] or "").strip()
            value = str(row[1] or "").strip()
        else:
            continue

        if value not in allowed_values or value in seen_values:
            continue
        if not label:
            label = value
        seen_values.add(value)
        cleaned.append((label, value))

    if not cleaned:
        raise RuntimeError(f"Item type options bos/hatali: {ITEM_TYPE_OPTIONS_FILE}")

    _ITEM_TYPE_CACHE_SIGNATURE = signature
    _ITEM_TYPE_CACHE_RECORDS = list(cleaned)
    return list(cleaned)


def _default_upper_group_id(name: str) -> int:
    seed = f"upper|{name}".encode("utf-8", errors="ignore")
    digest = hashlib.sha1(seed, usedforsecurity=False).hexdigest()[:8]
    rid = int(digest, 16)
    return -(rid if rid > 0 else 1)


def _default_sub_group_id(category: str, name: str) -> int:
    seed = f"{category}|{name}".encode("utf-8", errors="ignore")
    digest = hashlib.sha1(seed, usedforsecurity=False).hexdigest()[:8]
    rid = int(digest, 16)
    return -(rid if rid > 0 else 1)


def _read_default_upper_groups() -> list[str]:
    ensure_constants_paths()
    raw = _read_json_required(DEFAULT_UPPER_GROUPS_FILE)
    if not isinstance(raw, list):
        raise RuntimeError(f"Ust grup config listesi hatali: {DEFAULT_UPPER_GROUPS_FILE}")
    groups = _normalize_string_list(raw)
    if not groups:
        raise RuntimeError(f"Ust grup config listesi bos: {DEFAULT_UPPER_GROUPS_FILE}")
    return groups


def _read_default_upper_group_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in _read_default_upper_groups():
        text = str(name or "").strip()
        if not text:
            continue
        key = _text_key(text)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "id": _default_upper_group_id(text),
                "name": text,
                "created_at": "",
                "source": "default",
            }
        )
    return rows


def user_upper_group_rows() -> list[dict[str, Any]]:
    ensure_constants_paths()
    if not USER_UPPER_GROUPS_FILE.exists():
        return []
    try:
        raw = json.loads(USER_UPPER_GROUPS_FILE.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Kullanici ust grup dosyasi okunamadi/bozuk: {USER_UPPER_GROUPS_FILE}") from exc
    if not isinstance(raw, list):
        raise RuntimeError(f"Kullanici ust grup dosyasi hatali formatta: {USER_UPPER_GROUPS_FILE}")

    rows: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    max_id = 0
    for entry in raw:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            rid = entry.get("id")
            created_at = str(entry.get("created_at") or _now_iso_text())
        else:
            name = str(entry or "").strip()
            rid = None
            created_at = _now_iso_text()
        if not name:
            continue
        name_key = _text_key(name)
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        try:
            rid_int = int(rid)
        except Exception:
            rid_int = None
        if rid_int is None or rid_int <= 0:
            max_id += 1
            rid_int = max_id
        max_id = max(max_id, rid_int)
        rows.append(
            {
                "id": rid_int,
                "name": name,
                "created_at": created_at,
                "source": "user",
            }
        )
    return rows


def save_user_upper_group_rows(rows: list[dict[str, Any]]) -> None:
    ensure_constants_paths()
    payload: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for row in rows or []:
        name = str((row or {}).get("name") or "").strip()
        if not name:
            continue
        name_key = _text_key(name)
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        try:
            rid = int((row or {}).get("id"))
        except Exception:
            continue
        if rid <= 0:
            continue
        payload.append(
            {
                "id": rid,
                "name": name,
                "created_at": str((row or {}).get("created_at") or _now_iso_text()),
            }
        )
    _write_json(USER_UPPER_GROUPS_FILE, payload)
    _invalidate_catalog_cache()


def next_user_upper_group_id(rows: list[dict[str, Any]]) -> int:
    max_id = 0
    for row in rows or []:
        try:
            rid = int((row or {}).get("id"))
        except Exception:
            rid = 0
        if rid > max_id:
            max_id = rid
    return max_id + 1


def upper_group_rows() -> list[dict[str, Any]]:
    global _UPPER_GROUP_CACHE_SIGNATURE, _UPPER_GROUP_CACHE_ROWS

    signature = _path_signature(DEFAULT_UPPER_GROUPS_FILE, USER_UPPER_GROUPS_FILE)
    if _UPPER_GROUP_CACHE_ROWS is not None and _UPPER_GROUP_CACHE_SIGNATURE == signature:
        return [dict(row) for row in _UPPER_GROUP_CACHE_ROWS]

    out: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for row in _read_default_upper_group_rows():
        name = str((row or {}).get("name") or "").strip()
        if not name:
            continue
        key = _text_key(name)
        if key in seen_names:
            continue
        seen_names.add(key)
        out.append(dict(row))
    for row in user_upper_group_rows():
        name = str((row or {}).get("name") or "").strip()
        if not name:
            continue
        key = _text_key(name)
        if key in seen_names:
            continue
        seen_names.add(key)
        out.append(dict(row))

    _UPPER_GROUP_CACHE_SIGNATURE = signature
    _UPPER_GROUP_CACHE_ROWS = [dict(row) for row in out]
    return [dict(row) for row in out]


def upper_group_names() -> list[str]:
    return [
        str((row or {}).get("name") or "").strip()
        for row in upper_group_rows()
        if str((row or {}).get("name") or "").strip()
    ]


def _read_default_sub_group_map() -> dict[str, list[dict[str, Any]]]:
    raw = _read_json_required(DEFAULT_SUB_GROUPS_FILE)
    if not isinstance(raw, dict):
        raise RuntimeError(f"Alt grup config sozlugu hatali: {DEFAULT_SUB_GROUPS_FILE}")

    out: dict[str, list[dict[str, Any]]] = {}
    for cat, items in raw.items():
        category = str(cat or "").strip()
        if not category:
            continue
        rows: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        if isinstance(items, list):
            for entry in items:
                if isinstance(entry, dict):
                    name = str(entry.get("name") or "").strip()
                else:
                    name = str(entry or "").strip()
                if not name:
                    continue
                key = _text_key(name)
                if key in seen_names:
                    continue
                seen_names.add(key)
                rows.append(
                    {
                        "id": _default_sub_group_id(category, name),
                        "name": name,
                        "is_active": True,
                        "created_at": "",
                        "source": "default",
                    }
                )
        if rows:
            out[category] = rows

    if not out:
        raise RuntimeError(f"Alt grup config bos/hatali: {DEFAULT_SUB_GROUPS_FILE}")
    return out


def user_sub_group_map() -> dict[str, list[dict[str, Any]]]:
    ensure_constants_paths()
    if not USER_SUB_GROUPS_FILE.exists():
        return {}
    try:
        raw = json.loads(USER_SUB_GROUPS_FILE.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Kullanici alt grup dosyasi okunamadi/bozuk: {USER_SUB_GROUPS_FILE}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Kullanici alt grup dosyasi hatali formatta: {USER_SUB_GROUPS_FILE}")

    default_groups = upper_group_names()
    default_lookup = {_text_key(group): group for group in default_groups}

    out: dict[str, list[dict[str, Any]]] = {}
    max_id = 0
    for cat, items in raw.items():
        raw_category = str(cat or "").strip()
        category = default_lookup.get(_text_key(raw_category))
        if not category or not isinstance(items, list):
            continue
        rows: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for entry in items:
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
                rid = entry.get("id")
                is_active = bool(entry.get("is_active", True))
                created_at = str(entry.get("created_at") or _now_iso_text())
            else:
                name = str(entry or "").strip()
                rid = None
                is_active = True
                created_at = _now_iso_text()
            if not name:
                continue
            name_key = _text_key(name)
            if name_key in seen_names:
                continue
            seen_names.add(name_key)
            try:
                rid_int = int(rid)
            except Exception:
                rid_int = None
            if rid_int is None or rid_int <= 0:
                max_id += 1
                rid_int = max_id
            max_id = max(max_id, rid_int)
            rows.append(
                {
                    "id": rid_int,
                    "name": name,
                    "is_active": is_active,
                    "created_at": created_at,
                    "source": "user",
                }
            )
        if rows:
            out[category] = rows
    return out


def save_user_sub_group_map(data: dict[str, list[dict[str, Any]]]) -> None:
    ensure_constants_paths()
    default_groups = upper_group_names()
    default_lookup = {_text_key(group): group for group in default_groups}
    payload: dict[str, list[dict[str, Any]]] = {}
    for cat, rows in dict(data or {}).items():
        raw_category = str(cat or "").strip()
        category = default_lookup.get(_text_key(raw_category))
        if not category:
            continue
        packed_rows: list[dict[str, Any]] = []
        for row in rows or []:
            name = str((row or {}).get("name") or "").strip()
            if not name:
                continue
            try:
                rid = int((row or {}).get("id"))
            except Exception:
                continue
            if rid <= 0:
                continue
            packed_rows.append(
                {
                    "id": rid,
                    "name": name,
                    "is_active": bool((row or {}).get("is_active", True)),
                    "created_at": str((row or {}).get("created_at") or _now_iso_text()),
                }
            )
        if packed_rows:
            payload[category] = packed_rows
    _write_json(USER_SUB_GROUPS_FILE, payload)
    _invalidate_catalog_cache()


def next_user_sub_group_id(data: dict[str, list[dict[str, Any]]]) -> int:
    max_id = 0
    for rows in dict(data or {}).values():
        for row in rows or []:
            try:
                rid = int((row or {}).get("id"))
            except Exception:
                rid = 0
            if rid > max_id:
                max_id = rid
    return max_id + 1


def _merge_sub_group_maps(
    default_map: dict[str, list[dict[str, Any]]],
    user_map: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    all_categories: list[str] = []
    seen_categories: set[str] = set()
    for category in upper_group_names():
        cat_name = str(category or "").strip()
        if not cat_name:
            continue
        cat_key = _text_key(cat_name)
        if cat_key in seen_categories:
            continue
        seen_categories.add(cat_key)
        all_categories.append(cat_name)

    out: dict[str, list[dict[str, Any]]] = {}
    for category in all_categories:
        merged_rows: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for row in default_map.get(category, []):
            name = str((row or {}).get("name") or "").strip()
            if not name:
                continue
            key = _text_key(name)
            if key in seen_names:
                continue
            seen_names.add(key)
            merged_rows.append(dict(row))
        for row in user_map.get(category, []):
            name = str((row or {}).get("name") or "").strip()
            if not name:
                continue
            key = _text_key(name)
            if key in seen_names:
                continue
            seen_names.add(key)
            merged_rows.append(dict(row))
        if merged_rows:
            out[category] = merged_rows
    return out


def sub_group_map() -> dict[str, list[dict[str, Any]]]:
    global _SUB_GROUP_CACHE_SIGNATURE, _SUB_GROUP_CACHE_MAP

    signature = _path_signature(DEFAULT_UPPER_GROUPS_FILE, DEFAULT_SUB_GROUPS_FILE, USER_UPPER_GROUPS_FILE, USER_SUB_GROUPS_FILE)
    if _SUB_GROUP_CACHE_MAP is not None and _SUB_GROUP_CACHE_SIGNATURE == signature:
        return {key: [dict(row) for row in rows] for key, rows in _SUB_GROUP_CACHE_MAP.items()}

    merged = _merge_sub_group_maps(_read_default_sub_group_map(), user_sub_group_map())
    _SUB_GROUP_CACHE_SIGNATURE = signature
    _SUB_GROUP_CACHE_MAP = {key: [dict(row) for row in rows] for key, rows in merged.items()}
    return {key: [dict(row) for row in rows] for key, rows in merged.items()}


__all__ = [
    "item_type_options",
    "upper_group_names",
    "upper_group_rows",
    "user_upper_group_rows",
    "save_user_upper_group_rows",
    "next_user_upper_group_id",
    "sub_group_map",
    "user_sub_group_map",
    "save_user_sub_group_map",
    "next_user_sub_group_id",
]
