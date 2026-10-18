from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Optional

from Marketplaces.constants.catalog_constants import canonical_platform_code


DEFAULT_SERVICE_VAT_RATE = 20.0
_TARIFF_INDEX_CACHE_LIMIT = 16
_TARIFF_INDEX_CACHE: dict[tuple[int, int, str, str], dict[str, Any]] = {}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _gross_amount(
    amount: Any,
    *,
    is_vat_included: bool,
    vat_rate: Any,
    default_vat_rate: float = DEFAULT_SERVICE_VAT_RATE,
) -> float | None:
    numeric = _optional_float(amount)
    if numeric is None:
        return None
    rate = _optional_float(vat_rate)
    if rate is None:
        rate = default_vat_rate
    if is_vat_included:
        return numeric
    return numeric * (1.0 + max(0.0, float(rate)) / 100.0)


def _range_matches(value: Any, minimum: Any, maximum: Any) -> bool:
    min_val = _optional_float(minimum)
    max_val = _optional_float(maximum)
    probe = _optional_float(value)
    if probe is None:
        return min_val is None and max_val is None
    if min_val is not None and probe < min_val:
        return False
    if max_val is not None and probe > max_val:
        return False
    return True


def _range_span(minimum: Any, maximum: Any) -> float:
    min_val = _optional_float(minimum)
    max_val = _optional_float(maximum)
    if min_val is None or max_val is None:
        return 999999999.0
    return max(0.0, max_val - min_val)


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


@lru_cache(maxsize=256)
def _provider_name_key(value: Any) -> str:
    raw = _compact_text(value).casefold()
    if not raw:
        return ""
    chars = []
    for ch in raw:
        if ch.isalnum():
            chars.append(ch)
    normalized = "".join(chars)
    normalized = normalized.replace("marketplace", "")
    normalized = normalized.replace("kargo", "")
    normalized = normalized.replace("lojistik", "")
    return normalized


@lru_cache(maxsize=256)
def _provider_code_candidates(value: Any) -> set[str]:
    code = _compact_text(value).upper()
    if not code:
        return set()
    variants = {code}
    if code.endswith("MP") and len(code) > 2:
        variants.add(code[:-2])
    else:
        variants.add(f"{code}MP")
    return {variant for variant in variants if variant}


def _provider_matches_tariff(
    *,
    requested_provider_id: int | None,
    requested_provider_codes: set[str],
    requested_provider_name_key: str,
    tariff_row: dict[str, Any],
) -> bool:
    if requested_provider_id is None and not requested_provider_codes and not requested_provider_name_key:
        return True

    row_provider_id = _positive_int_or_none(tariff_row.get("cargo_provider_id") or tariff_row.get("cargoProviderId"))
    row_provider_code = _compact_text(tariff_row.get("cargoProviderCode")).upper()
    row_provider_name_key = _provider_name_key(tariff_row.get("cargoProviderName"))

    if requested_provider_id is not None and row_provider_id is not None:
        return row_provider_id == requested_provider_id

    if requested_provider_codes and row_provider_code and row_provider_code in requested_provider_codes:
        return True

    if requested_provider_name_key and row_provider_name_key and row_provider_name_key == requested_provider_name_key:
        return True

    return False


def _tariff_cache_key(cargo_tariffs: list[dict] | None) -> tuple[int, int, str, str] | None:
    if not isinstance(cargo_tariffs, list):
        return None
    if not cargo_tariffs:
        return (id(cargo_tariffs), 0, "", "")
    first = cargo_tariffs[0] if isinstance(cargo_tariffs[0], dict) else {}
    last = cargo_tariffs[-1] if isinstance(cargo_tariffs[-1], dict) else {}
    return (
        id(cargo_tariffs),
        len(cargo_tariffs),
        _compact_text(first.get("tariffKey") if isinstance(first, dict) else ""),
        _compact_text(last.get("tariffKey") if isinstance(last, dict) else ""),
    )


def _build_tariff_index(cargo_tariffs: list[dict] | None) -> dict[str, Any]:
    entries: list[tuple[Any, ...]] = []
    by_platform: dict[str, list[tuple[Any, ...]]] = {}
    global_entries: list[tuple[Any, ...]] = []

    for row in cargo_tariffs or ():
        if not isinstance(row, dict):
            continue
        if row.get("isActive") is False:
            continue

        effective_amount = _gross_amount(
            row.get("amount"),
            is_vat_included=bool(row.get("isVatIncluded", True)),
            vat_rate=row.get("vatRate"),
            default_vat_rate=DEFAULT_SERVICE_VAT_RATE,
        )
        if effective_amount is None:
            continue

        row_platform = canonical_platform_code(row.get("platformCode") or row.get("platform"))
        entry = (
            row,
            row_platform,
            _positive_int_or_none(row.get("cargo_provider_id") or row.get("cargoProviderId")),
            _compact_text(row.get("cargoProviderCode")).upper(),
            _provider_name_key(row.get("cargoProviderName")),
            _optional_float(row.get("minDesi")),
            _optional_float(row.get("maxDesi")),
            _optional_float(row.get("minSalePrice")),
            _optional_float(row.get("maxSalePrice")),
            effective_amount,
            _range_span(row.get("minDesi"), row.get("maxDesi")),
            _range_span(row.get("minSalePrice"), row.get("maxSalePrice")),
            str(row.get("tariffKey") or ""),
        )
        entries.append(entry)
        if row_platform:
            by_platform.setdefault(row_platform, []).append(entry)
        else:
            global_entries.append(entry)

    global_entries_tuple = tuple(global_entries)
    by_platform_tuple = {platform: tuple(rows) for platform, rows in by_platform.items()}
    return {
        "entries": tuple(entries),
        "by_platform": by_platform_tuple,
        "global_entries": global_entries_tuple,
        "candidate_by_platform": {
            platform: rows + global_entries_tuple
            for platform, rows in by_platform_tuple.items()
        },
    }


def _tariff_index(cargo_tariffs: list[dict] | None) -> dict[str, Any]:
    key = _tariff_cache_key(cargo_tariffs)
    if key is None:
        return _build_tariff_index(cargo_tariffs)
    cached = _TARIFF_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_TARIFF_INDEX_CACHE) >= _TARIFF_INDEX_CACHE_LIMIT:
        _TARIFF_INDEX_CACHE.clear()
    cached = _build_tariff_index(cargo_tariffs)
    _TARIFF_INDEX_CACHE[key] = cached
    return cached


def _entry_matches_provider(
    *,
    requested_provider_id: int | None,
    requested_provider_codes: set[str],
    requested_provider_name_key: str,
    entry: tuple[Any, ...],
) -> bool:
    if requested_provider_id is None and not requested_provider_codes and not requested_provider_name_key:
        return True

    row_provider_id = entry[2]
    row_provider_code = entry[3]
    row_provider_name_key = entry[4]

    if requested_provider_id is not None and row_provider_id is not None:
        return row_provider_id == requested_provider_id

    if requested_provider_codes and row_provider_code and row_provider_code in requested_provider_codes:
        return True

    if requested_provider_name_key and row_provider_name_key and row_provider_name_key == requested_provider_name_key:
        return True

    return False


def _range_matches_prepared(probe: float | None, min_val: float | None, max_val: float | None) -> bool:
    if probe is None:
        return min_val is None and max_val is None
    if min_val is not None and probe < min_val:
        return False
    if max_val is not None and probe > max_val:
        return False
    return True


def _resolve_platform_code(source_context: dict[str, Any]) -> str:
    direct_platform = canonical_platform_code(source_context.get("platform_code"))
    if direct_platform:
        return direct_platform
    item_payload = dict(source_context.get("item") or {})
    return (
        canonical_platform_code(item_payload.get("platformCode"))
        or canonical_platform_code(item_payload.get("platform"))
        or canonical_platform_code(item_payload.get("platform_code"))
        or ""
    )


def match_cargo_amount(
    *,
    sale_price: Any,
    dimensional_weight: Any,
    platform_code: Any,
    cargo_tariffs: list[dict] | None,
    cargo_provider_id: Any = None,
    cargo_provider_code: Any = None,
    cargo_provider_name: Any = None,
) -> Optional[dict]:
    normalized_platform = canonical_platform_code(platform_code)
    requested_provider_id = _positive_int_or_none(cargo_provider_id)
    requested_provider_codes = _provider_code_candidates(cargo_provider_code)
    requested_provider_name_key = _provider_name_key(cargo_provider_name)
    sale_price_val = _optional_float(sale_price)
    desi_val = _optional_float(dimensional_weight)
    if desi_val is None or desi_val < 0:
        desi_probes: list[float | None] = [0.0]
    else:
        desi_probes = [desi_val]
        ceil_desi = float(math.ceil(desi_val))
        if ceil_desi != desi_val:
            desi_probes.append(ceil_desi)
    tariff_index = _tariff_index(cargo_tariffs)
    if normalized_platform:
        candidate_entries = tariff_index["candidate_by_platform"].get(normalized_platform)
        if candidate_entries is None:
            candidate_entries = tariff_index["global_entries"]
    else:
        candidate_entries = tariff_index["entries"]

    def _best_candidate(desi_probe: float | None) -> dict[str, Any] | None:
        best_sort_key: tuple[Any, ...] | None = None
        best_payload: dict[str, Any] | None = None
        for entry in candidate_entries:
            row = entry[0]
            row_platform = entry[1]
            if not _entry_matches_provider(
                requested_provider_id=requested_provider_id,
                requested_provider_codes=requested_provider_codes,
                requested_provider_name_key=requested_provider_name_key,
                entry=entry,
            ):
                continue

            if not _range_matches_prepared(desi_probe, entry[5], entry[6]):
                continue
            if not _range_matches_prepared(sale_price_val, entry[7], entry[8]):
                continue

            effective_amount = entry[9]

            sort_key = (
                0 if row_platform else 1,
                effective_amount,
                entry[10],
                entry[11],
                entry[12],
            )
            if best_sort_key is not None and sort_key >= best_sort_key:
                continue
            payload = dict(row)
            payload["effectiveAmount"] = effective_amount
            best_sort_key = sort_key
            best_payload = payload
        return best_payload

    best_match: dict[str, Any] | None = None
    for desi_probe in desi_probes:
        best_match = _best_candidate(desi_probe)
        if best_match is not None:
            break

    return best_match


def resolve_cargo_amount_matcher(
    source_config: dict[str, Any] | None,
    source_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context = dict(source_context or {})
    config = dict(source_config or {})
    selected_provider_id = _positive_int_or_none(
        config.get("cargoProviderId")
        if "cargoProviderId" in config
        else config.get("cargo_provider_id")
    )
    selected_provider_code = _compact_text(
        config.get("cargoProviderCode")
        if "cargoProviderCode" in config
        else config.get("cargo_provider_code")
    ).upper()
    selected_provider_name = _compact_text(
        config.get("cargoProviderName")
        if "cargoProviderName" in config
        else config.get("cargo_provider_name")
    )
    matched_tariff = match_cargo_amount(
        sale_price=context.get("sale_price"),
        dimensional_weight=context.get("effective_dimensional_weight"),
        platform_code=_resolve_platform_code(context),
        cargo_tariffs=context.get("cargo_tariffs"),
        cargo_provider_id=selected_provider_id,
        cargo_provider_code=selected_provider_code,
        cargo_provider_name=selected_provider_name,
    )
    if matched_tariff is None:
        return {"missing_reason": "Uygun kargo tarifesi bulunamadı."}
    tariff_label = str(
        matched_tariff.get("name")
        or matched_tariff.get("label")
        or matched_tariff.get("tariffKey")
        or ""
    ).strip()
    return {
        "amount": _optional_float(matched_tariff.get("effectiveAmount")) or 0.0,
        "amount_is_gross": True,
        "note": tariff_label,
        "meta": {
            "kind": "cargo",
            "selectedCargoProviderId": selected_provider_id,
            "selectedCargoProviderCode": selected_provider_code or None,
            "selectedCargoProviderName": selected_provider_name or None,
            "matchedTariffKey": matched_tariff.get("tariffKey"),
            "matchedTariffName": matched_tariff.get("name") or matched_tariff.get("label"),
            "matchedTariff": dict(matched_tariff),
            "ruleKey": "cargo_amount_matcher",
        },
    }
