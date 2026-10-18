from __future__ import annotations

from typing import Any

from Feedback.processors.pipeline import Result, map_error_to_message
from Logistics.constants.catalog_constants import builtin_cargo_provider_records, cargo_provider_records
from Logistics.processors.pipeline import (
    accept_logistics_cargo_provider,
    delete_logistics_cargo_provider,
    save_logistics_cargo_provider,
)
from Logistics.signals.signals import logistics_signals
from Marketplaces.constants.catalog_constants import (
    canonical_platform_code,
    marketplace_cargo_form_visible_fields,
    marketplace_code_for_source_id,
    platform_label_for_code,
    platform_select_options,
)


def _finance_action(name: str):
    from Finance.views import actions as finance_actions

    return getattr(finance_actions, name)


def _compact_text(value) -> str:
    return str(value or "").strip()


def logistics_cargo_provider_platform_options(
    *,
    include_all: bool = True,
    db_name: str | None = None,
) -> list[tuple[str, str]]:
    return platform_select_options(include_all=include_all, db_name=db_name)


def load_logistics_cargo_providers(
    *,
    platform_code: Any = None,
    search: str = "",
    source_filter: str = "",
    db_name: str | None = None,
) -> Result:
    try:
        normalized_platform = marketplace_code_for_source_id(platform_code, db_name=db_name) or canonical_platform_code(platform_code)
        if normalized_platform.casefold() in ("", "all", "tumu"):
            normalized_platform = ""
        search_text = _compact_text(search).casefold()
        normalized_source_filter = _compact_text(source_filter).casefold()
        records: list[dict[str, Any]] = []

        if normalized_platform:
            platform_codes = [normalized_platform]
        else:
            platform_codes = [
                str(code or "").strip().upper()
                for _label, code in logistics_cargo_provider_platform_options(include_all=False, db_name=db_name)
                if str(code or "").strip()
            ]

        db_rows = cargo_provider_records(db_name=db_name)
        accepted_map = {
            f"{_compact_text(row.get('platformCode')).upper()}:{_compact_text(row.get('cargoProviderCode')).upper()}": dict(row or {})
            for row in db_rows
            if _compact_text(row.get("platformCode")) and _compact_text(row.get("cargoProviderCode"))
        }

        for current_platform in platform_codes:
            if not current_platform:
                continue
            platform_label = platform_label_for_code(current_platform, db_name=db_name)
            for row in builtin_cargo_provider_records(current_platform):
                provider_code = _compact_text(row.get("cargoProviderCode")).upper()
                provider_name = _compact_text(row.get("cargoProviderName"))
                if not provider_code or not provider_name:
                    continue
                key = f"{current_platform}:{provider_code}"
                accepted = dict(accepted_map.pop(key, {}) or {})
                payload = {**dict(row or {}), **accepted}
                payload["platformCode"] = current_platform
                payload["platformLabel"] = platform_label
                payload["cargoProviderCode"] = provider_code
                payload["cargoProviderName"] = _compact_text(payload.get("cargoProviderName")) or provider_name
                payload["key"] = key
                payload["isBuiltin"] = True
                payload["isBuiltinAccepted"] = bool(accepted)
                payload["sourceLabel"] = "Kullanıma Alınmış" if accepted else "Önerilen Kayıt"
                payload["sourceNote"] = (
                    "Bu kayıt veritabanına alınmış durumdadır."
                    if accepted
                    else "Bu kayıt Logistics catalog tarafından önerilir."
                )
                haystack = " | ".join(
                    [
                        payload["cargoProviderName"].casefold(),
                        provider_code.casefold(),
                        platform_label.casefold(),
                        current_platform.casefold(),
                    ]
                )
                if search_text and search_text not in haystack:
                    continue
                records.append(payload)

        for row in accepted_map.values():
            current_platform = _compact_text(row.get("platformCode")).upper()
            if normalized_platform and current_platform != normalized_platform:
                continue
            platform_label = platform_label_for_code(current_platform, db_name=db_name)
            payload = dict(row or {})
            provider_code = _compact_text(payload.get("cargoProviderCode")).upper()
            provider_name = _compact_text(payload.get("cargoProviderName"))
            haystack = " | ".join(
                [
                    provider_name.casefold(),
                    provider_code.casefold(),
                    platform_label.casefold(),
                    current_platform.casefold(),
                ]
            )
            if search_text and search_text not in haystack:
                continue
            payload["platformLabel"] = platform_label
            payload["isBuiltin"] = False
            payload["isBuiltinAccepted"] = True
            payload["sourceLabel"] = "Veritabani"
            payload["sourceNote"] = "Bu kayıt kullanıcı tarafından eklenmiş veya kabul edilmiştir."
            records.append(payload)

        records.sort(
            key=lambda row: (
                0 if bool(row.get("isBuiltinAccepted")) else 1,
                _compact_text(row.get("platformLabel")).casefold(),
                _compact_text(row.get("cargoProviderName")).casefold(),
                _compact_text(row.get("cargoProviderCode")).casefold(),
            )
        )

        if normalized_source_filter in {"pending", "builtin"}:
            records = [row for row in records if bool(row.get("isBuiltin")) and not bool(row.get("isBuiltinAccepted"))]
        elif normalized_source_filter in {"saved", "accepted"}:
            records = [row for row in records if bool(row.get("isBuiltinAccepted"))]

        return Result.ok(
            "Kargo firmaları yüklendi.",
            close_dialog=False,
            data={
                "records": records,
                "count": len(records),
                "platform_code": normalized_platform,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def save_logistics_cargo_provider_record(
    provider_payload: dict[str, Any],
    *,
    db_name: str | None = None,
) -> Result:
    try:
        result = save_logistics_cargo_provider(dict(provider_payload or {}), db_name=db_name)
        if result.success:
            logistics_signals.cargo_providers_changed.emit()
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def accept_logistics_cargo_provider_record(
    provider_payload: dict[str, Any],
    *,
    db_name: str | None = None,
) -> Result:
    try:
        result = accept_logistics_cargo_provider(dict(provider_payload or {}), db_name=db_name)
        if result.success:
            logistics_signals.cargo_providers_changed.emit()
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def delete_logistics_cargo_provider_record(
    provider_payload: dict[str, Any],
    *,
    db_name: str | None = None,
) -> Result:
    try:
        payload = dict(provider_payload or {})
        if bool(payload.get("isBuiltin")):
            return Result.fail("Önerilen veya kabul edilmiş yerleşik kargo firmaları silinmez.", close_dialog=False)
        pk = int(payload.get("pk") or 0)
        if pk <= 0:
            return Result.fail("Silinecek kayıt bulunamadı.", close_dialog=False)
        result = delete_logistics_cargo_provider(pk, db_name=db_name)
        if result.success:
            logistics_signals.cargo_providers_changed.emit()
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def logistics_cargo_tariff_platform_options(
    *,
    include_all: bool = True,
    db_name: str | None = None,
) -> list[tuple[str, str]]:
    return platform_select_options(include_all=include_all, db_name=db_name)


def logistics_cargo_provider_options(
    platform_code: str | None = None,
    *,
    include_all: bool = True,
    db_name: str | None = None,
) -> list[tuple[str, str]]:
    options = [
        (
            _compact_text(row.get("cargoProviderName")),
            _compact_text(row.get("sourceId") or row.get("source_id") or row.get("cargoProviderCode")),
        )
        for row in cargo_provider_records(platform_code, db_name=db_name)
        if _compact_text(row.get("cargoProviderName"))
        and _compact_text(row.get("sourceId") or row.get("source_id") or row.get("cargoProviderCode"))
    ]
    return ([("Tümü", "")] + options) if include_all else options


def logistics_cargo_tariff_visible_fields(platform_code: object | None = None) -> set[str]:
    normalized_platform = marketplace_code_for_source_id(platform_code) or platform_code
    return set(marketplace_cargo_form_visible_fields(normalized_platform))


def load_logistics_cargo_tariffs(**kwargs) -> Result:
    return _finance_action("load_finance_cargo_tariffs")(**kwargs)


def load_logistics_cargo_tariffs_summary(**kwargs) -> Result:
    return _finance_action("load_finance_cargo_tariffs_summary")(**kwargs)


def save_logistics_cargo_tariff(tariff_payload: dict[str, Any], **kwargs) -> Result:
    result = _finance_action("save_finance_cargo_tariff")(tariff_payload, **kwargs)
    if result.success:
        logistics_signals.cargo_tariffs_changed.emit()
    return result


def accept_logistics_cargo_tariff(item_pk: int, **kwargs) -> Result:
    result = _finance_action("accept_finance_cargo_tariff")(item_pk, **kwargs)
    if result.success:
        logistics_signals.cargo_tariffs_changed.emit()
    return result


def accept_logistics_cargo_tariffs(item_pks: list[int], **kwargs) -> Result:
    result = _finance_action("accept_finance_cargo_tariffs")(item_pks, **kwargs)
    if result.success:
        logistics_signals.cargo_tariffs_changed.emit()
    return result


def delete_logistics_cargo_tariff(item_pk: int, **kwargs) -> Result:
    result = _finance_action("delete_finance_cargo_tariff")(item_pk, **kwargs)
    if result.success:
        logistics_signals.cargo_tariffs_changed.emit()
    return result


def delete_logistics_cargo_tariffs(item_pks: list[int], **kwargs) -> Result:
    result = _finance_action("delete_finance_cargo_tariffs")(item_pks, **kwargs)
    if result.success:
        logistics_signals.cargo_tariffs_changed.emit()
    return result
