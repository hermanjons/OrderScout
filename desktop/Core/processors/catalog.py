from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_core_constants_dir = Path(__file__).resolve().parent.parent / "constants"
_core_default_files_dir = _core_constants_dir / "files"
_unit_options_file = _core_default_files_dir / "unit_options.json"
_country_directory_file = _core_default_files_dir / "country_directory.json"
_currency_options_file = _core_default_files_dir / "currency_options.json"

_JSON_CACHE_SIGNATURES: dict[str, tuple[str, int, int]] = {}
_JSON_CACHE_PAYLOADS: dict[str, Any] = {}


def _path_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _load_json_required(file_path: Path) -> Any:
    try:
        signature = _path_signature(file_path)
    except Exception as exc:
        raise RuntimeError(f"Gerekli config dosyasi okunamadi: {file_path}") from exc

    cache_key = str(file_path)
    if _JSON_CACHE_SIGNATURES.get(cache_key) == signature:
        return _JSON_CACHE_PAYLOADS.get(cache_key)

    try:
        raw = file_path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        raise RuntimeError(f"Gerekli config dosyasi okunamadi: {file_path}") from exc
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"Config JSON bozuk: {file_path}") from exc

    _JSON_CACHE_SIGNATURES[cache_key] = signature
    _JSON_CACHE_PAYLOADS[cache_key] = payload
    return payload


def _load_string_list(file_path: Path, *, normalize_upper: bool = False) -> list[str]:
    raw = _load_json_required(file_path)
    if not isinstance(raw, list):
        raise RuntimeError(f"Beklenen liste formati bulunamadi: {file_path}")

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in raw:
        item = str(value or "").strip()
        if not item:
            continue
        if normalize_upper:
            item = item.upper()
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)

    if not cleaned:
        raise RuntimeError(f"Liste bos/hatali: {file_path}")
    return cleaned


def _normalize_dial_code(value: object) -> str:
    code = str(value or "").strip()
    if not code:
        return ""
    if code.startswith("00"):
        code = "+" + code[2:]
    if not code.startswith("+"):
        code = "+" + code.lstrip("+")
    code = "+" + "".join(ch for ch in code[1:] if ch.isdigit())
    return code if len(code) > 1 else ""


def _load_country_directory(file_path: Path) -> tuple[list[str], dict[str, list[str]], dict[str, str], list[str]]:
    raw = _load_json_required(file_path)
    if not isinstance(raw, list):
        raise RuntimeError(f"Beklenen liste formati bulunamadi: {file_path}")

    countries: list[str] = []
    city_map: dict[str, list[str]] = {}
    phone_code_map: dict[str, str] = {}
    dial_codes: list[str] = []
    seen_country_keys: set[str] = set()
    seen_dial_codes: set[str] = set()

    for row in raw:
        if not isinstance(row, dict):
            continue
        country_name = str(row.get("label") or "").strip()
        if not country_name:
            continue
        country_key = country_name.casefold()
        if country_key in seen_country_keys:
            continue
        seen_country_keys.add(country_key)
        countries.append(country_name)

        dial_code = _normalize_dial_code(row.get("dialCode"))
        if dial_code:
            phone_code_map[country_name] = dial_code
            if dial_code not in seen_dial_codes:
                seen_dial_codes.add(dial_code)
                dial_codes.append(dial_code)

        cities = row.get("cities")
        if not isinstance(cities, list):
            city_map[country_name] = []
            continue
        cleaned: list[str] = []
        seen: set[str] = set()
        for city in cities:
            city_name = str(city or "").strip()
            if not city_name:
                continue
            key = city_name.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(city_name)
        city_map[country_name] = cleaned

    if not countries:
        raise RuntimeError(f"Ulke dizini bos/hatali: {file_path}")
    return countries, city_map, phone_code_map, dial_codes


def unit_options() -> list[str]:
    return list(_load_string_list(_unit_options_file))


def currency_options() -> list[str]:
    return list(_load_string_list(_currency_options_file, normalize_upper=True))


def country_directory() -> tuple[list[str], dict[str, list[str]], dict[str, str], list[str]]:
    countries, city_map, phone_code_map, dial_codes = _load_country_directory(_country_directory_file)
    return (
        list(countries),
        {country: list(cities) for country, cities in city_map.items()},
        dict(phone_code_map),
        list(dial_codes),
    )


def country_options() -> list[str]:
    countries, _city_map, _phone_code_map, _dial_codes = country_directory()
    return countries


def city_options_by_country() -> dict[str, list[str]]:
    _countries, city_map, _phone_code_map, _dial_codes = country_directory()
    return city_map


def country_phone_code_by_country() -> dict[str, str]:
    _countries, _city_map, phone_code_map, _dial_codes = country_directory()
    return phone_code_map


def phone_dial_code_options() -> list[str]:
    _countries, _city_map, _phone_code_map, dial_codes = country_directory()
    return dial_codes


def clear_core_catalog_cache() -> None:
    _JSON_CACHE_SIGNATURES.clear()
    _JSON_CACHE_PAYLOADS.clear()


__all__ = [
    "city_options_by_country",
    "clear_core_catalog_cache",
    "country_directory",
    "country_options",
    "country_phone_code_by_country",
    "currency_options",
    "phone_dial_code_options",
    "unit_options",
]
