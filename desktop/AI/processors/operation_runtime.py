from __future__ import annotations

import hashlib
import asyncio
import importlib
import inspect
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

from AI.constants.paths import AI_DOMAIN_ROOT, ensure_ai_paths
from AI.processors.manual_capabilities import (
    MANUAL_EXECUTE_ADAPTERS,
    ManualCapability,
    find_manual_capability,
    list_manual_capabilities,
    manual_execute_blockers,
    manual_read_blockers,
)
from Feedback.processors.pipeline import Result, map_error_to_message
from Stock.processors import pipeline as stock_pipeline
from settings import DB_NAME, MEDIA_EXPORTS


DEFAULT_OPERATION_AUDIT_FILE = AI_DOMAIN_ROOT / "operation_audit.jsonl"
STAGING_MARKETPLACE_MUTATION_ENV = "ORDERSCOUT_ALLOW_STAGING_MARKETPLACE_MUTATION"
STAGING_MARKETPLACE_ACTION_TYPES = {
    "listing.action_update_approved_content_for_account",
    "listing.action_update_price_inventory_for_account",
    "listing.content_update",
    "listing.update_price",
    "listing.update_stock",
    "orders.approve_return_claim",
    "orders.change_order_cargo_provider",
    "orders.change_orders_cargo_provider_bulk",
}
STAGING_MARKETPLACE_PLACEHOLDER_VALUES = {
    "<CONTROLLED_STAGING_REASON>",
    "<IDEMPOTENCY_KEY>",
    "<STAGING_ACCOUNT_ID>",
    "<STAGING_SELLER_ID>",
    "CONTROLLED_STAGING_REASON",
    "IDEMPOTENCY_KEY",
    "STAGING_ACCOUNT_ID",
    "STAGING_SELLER_ID",
    "TBD",
    "TODO",
}
SPECIALIZED_EXECUTE_ACTION_TYPES = {
    "stock.item_create": "Stok karti create executor",
    "stock.item_update": "Stok karti update executor",
}
UNBOUND_EXECUTE_ACTION_TYPES = {
    "listing.content_optimize": "Ilan icerik iyilestirme execute adapter henuz bagli degil; yalnizca dry-run onay taslagi destekleniyor.",
}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _truthy_env(name: str) -> bool:
    return _compact_text(os.environ.get(name)).casefold() in {"1", "true", "yes", "on"}


def looks_like_staging_marketplace_placeholder(value: Any) -> bool:
    text = _compact_text(value)
    if not text:
        return False
    upper = text.upper()
    return upper in STAGING_MARKETPLACE_PLACEHOLDER_VALUES or bool(re.fullmatch(r"<[A-Z0-9_ -]+>", upper))


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(payload: Any) -> Any:
    try:
        return json.loads(json.dumps(payload, sort_keys=True, default=str))
    except Exception:
        return str(payload)


def _without_secretish_keys(payload: Any) -> Any:
    blocked = {"accounts", "comp_api_account_list", "api_key", "api_secret", "token", "authorization", "headers"}
    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = _compact_text(key)
            if key_text.casefold() in blocked:
                continue
            cleaned[key] = _without_secretish_keys(value)
        return cleaned
    if isinstance(payload, list):
        return [_without_secretish_keys(item) for item in payload]
    if isinstance(payload, tuple):
        return [_without_secretish_keys(item) for item in payload]
    return payload


def _claim_ids_from_rows(rows: list[Any]) -> list[str]:
    ids: list[str] = []
    for row in list(rows or []):
        claim_id = ""
        if isinstance(row, dict):
            claim_id = _compact_text(row.get("claimId") or row.get("claim_id") or row.get("claimNumber") or row.get("claim_number"))
        else:
            claim_id = _compact_text(getattr(row, "claimId", "") or getattr(row, "claim_id", "") or getattr(row, "claimNumber", ""))
        if claim_id and claim_id not in ids:
            ids.append(claim_id)
    return ids


def operation_idempotency_key(action: dict[str, Any], *, namespace: str = "agent-operation") -> str:
    body = json.dumps(_jsonable(action), sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{namespace}|{body}".encode("utf-8")).hexdigest()
    return digest[:32]


def _audit_path(path: str | Path | None = None) -> Path:
    if path not in (None, ""):
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved
    ensure_ai_paths()
    DEFAULT_OPERATION_AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    return DEFAULT_OPERATION_AUDIT_FILE


def _same_filesystem_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except Exception:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def _read_audit_entries(path: str | Path | None = None) -> list[dict[str, Any]]:
    resolved = _audit_path(path)
    if not resolved.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in resolved.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _append_audit_entry(entry: dict[str, Any], *, audit_path: str | Path | None = None) -> None:
    resolved = _audit_path(audit_path)
    with resolved.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_jsonable(entry), ensure_ascii=False, sort_keys=True, default=str))
        fh.write("\n")


def _previous_success(idempotency_key: str, *, audit_path: str | Path | None = None) -> dict[str, Any] | None:
    for entry in reversed(_read_audit_entries(audit_path)):
        if entry.get("idempotency_key") == idempotency_key and entry.get("status") == "success":
            return entry
    return None


def _previous_attempt(idempotency_key: str, *, audit_path: str | Path | None = None) -> dict[str, Any] | None:
    for entry in reversed(_read_audit_entries(audit_path)):
        if entry.get("idempotency_key") == idempotency_key:
            return entry
    return None


def _approved_action(action: dict[str, Any], *, expected_action_type: str) -> Result | None:
    if not isinstance(action, dict):
        return Result.fail("Agent operation action payload gecersiz.", close_dialog=False)
    if _compact_text(action.get("action_type")) != expected_action_type:
        return Result.fail("Agent operation action_type beklenen islemle eslesmiyor.", close_dialog=False)
    if not bool(action.get("approval_required")):
        return Result.fail("Agent operation approval payload degil.", close_dialog=False)
    if bool(action.get("warnings")):
        return Result.fail("Uyarili agent operation execute edilemez; once prepare sorunlari giderilmeli.", close_dialog=False)
    if not bool(action.get("execute_enabled")):
        return Result.fail("Agent operation execute_enabled degil.", close_dialog=False)
    return None


def _manual_capability_is_execute_safe(capability: ManualCapability) -> tuple[bool, list[str]]:
    reasons = manual_execute_blockers(capability)
    return not reasons, reasons


def _manual_capability_is_read_safe(capability: ManualCapability) -> tuple[bool, list[str]]:
    reasons = manual_read_blockers(capability)
    return not reasons, reasons


def _manual_payload_from_action(action: dict[str, Any]) -> dict[str, Any]:
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    payload = arguments.get("payload")
    if payload is None:
        rows = action.get("rows") if isinstance(action.get("rows"), list) else []
        first = rows[0] if rows and isinstance(rows[0], dict) else {}
        payload = first.get("payload")
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _missing_required_payload(capability: ManualCapability, payload: dict[str, Any]) -> list[str]:
    alternative_groups = {
        "finance.action_sync_finance_for_accounts": {
            "accounts": ("accounts", "api_account_ids", "selected_company_pks", "company_pks", "company_ids"),
        },
        "orders.get_orders_from_companies": {
            "accounts": ("accounts", "comp_api_account_list", "api_account_ids", "selected_company_pks", "company_pks", "company_ids"),
        },
        "orders.update_last_used_at_for_accounts": {
            "accounts": ("accounts", "comp_api_account_list", "api_account_ids", "selected_company_pks", "company_pks", "company_ids"),
        },
    }
    missing: list[str] = []
    for name in list(capability.required_parameters or []):
        alternatives = alternative_groups.get(capability.capability_id, {}).get(str(name), (str(name),))
        found = False
        for alternative in alternatives:
            value = dict(payload or {}).get(str(alternative))
            if value in (None, ""):
                continue
            if isinstance(value, (list, tuple, dict)) and not value:
                continue
            found = True
            break
        if not found:
            missing.append(str(name))
    return missing


def _required_payload_guard(capability: ManualCapability, payload: dict[str, Any]) -> Result | None:
    missing = _missing_required_payload(capability, payload)
    if not missing:
        return None
    return Result.fail(
        "Manuel action payload alanlari eksik.",
        close_dialog=False,
        data={
            "capability": capability.to_dict(),
            "payload": dict(payload or {}),
            "missing_parameters": missing,
        },
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _callable_for_capability(capability: ManualCapability):
    module = importlib.import_module(capability.module_path)
    return getattr(module, capability.function_name)


def _bind_manual_payload(func: Any, payload: dict[str, Any]) -> Result | None:
    try:
        signature = inspect.signature(func)
        signature.bind(**payload)
    except TypeError as exc:
        return Result.fail(f"Manuel action payload semasi uyumsuz: {exc}", close_dialog=False)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
    return None


def _result_from_manual_return(value: Any) -> Result:
    if isinstance(value, Result):
        return value
    return Result.ok(
        "Manuel action calisti; Result donmedigi icin cikti data olarak kaydedildi.",
        close_dialog=False,
        data={"return_value": _jsonable(value)},
    )


def _resolve_manual_return(value: Any) -> Result:
    if not inspect.isawaitable(value):
        return _result_from_manual_return(value)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return _result_from_manual_return(
                loop.run_until_complete(value)
            )
        finally:
            try:
                from Core.utils.request_utils import (
                    close_async_request_clients,
                )

                loop.run_until_complete(
                    close_async_request_clients()
                )
                loop.run_until_complete(asyncio.sleep(0.05))
            except Exception:
                pass
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
    close = getattr(value, "close", None)
    if callable(close):
        close()
    return Result.fail("Async manuel action aktif event loop icinde sync execute edilemez.", close_dialog=False)


def _ean13_check_digit(first_12_digits: str) -> str:
    total = 0
    for index, char in enumerate(first_12_digits[:12]):
        multiplier = 1 if index % 2 == 0 else 3
        total += int(char) * multiplier
    return str((10 - (total % 10)) % 10)


def _fallback_barcode(prefix: str = "869") -> str:
    clean_prefix = "".join(ch for ch in str(prefix or "") if ch.isdigit()) or "869"
    clean_prefix = clean_prefix[:12]
    seed = datetime.now(timezone.utc).strftime("%H%M%S%f")
    digest = hashlib.sha1(f"{clean_prefix}:{seed}".encode("utf-8"), usedforsecurity=False).hexdigest()
    digits = "".join(ch for ch in f"{clean_prefix}{seed}{digest}" if ch.isdigit())
    first_12 = digits[:12].ljust(12, "0")
    return f"{first_12}{_ean13_check_digit(first_12)}"


def _execute_manual_adapter(capability: ManualCapability, payload: dict[str, Any]) -> Result | None:
    capability_id = capability.capability_id
    if capability_id == "listing.action_fetch_listings":
        from Account.processors.pipeline import get_company_by_id
        from Core.processors.credential_store import is_credential_reference
        from Listing.processors import pipeline as listing_pipeline
        from Listing.views import actions as listing_actions
        from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs

        def _account_ids_from_payload() -> list[int]:
            raw_ids = (
                payload.get("api_account_ids")
                or payload.get("selected_company_pks")
                or payload.get("company_pks")
                or payload.get("company_ids")
            )
            ids: list[int] = []
            for raw_id in _as_list(raw_ids):
                try:
                    account_pk = int(raw_id)
                except Exception:
                    continue
                if account_pk > 0 and account_pk not in ids:
                    ids.append(account_pk)
            return ids

        def _explicit_account_rows() -> list[list[Any]]:
            rows: list[list[Any]] = []
            for raw_row in _as_list(payload.get("accounts") or payload.get("comp_api_account_list")):
                if isinstance(raw_row, dict):
                    row = [
                        raw_row.get("pk") or raw_row.get("id") or raw_row.get("api_account_id"),
                        raw_row.get("api_key"),
                        raw_row.get("api_secret"),
                        raw_row.get("account_id") or raw_row.get("seller_id"),
                        raw_row.get("acceptLanguage") or raw_row.get("accept_language") or "",
                        raw_row.get("environment") or raw_row.get("api_environment") or "production",
                        raw_row.get("credential_reference") or raw_row.get("credential_ref") or "",
                    ]
                elif isinstance(raw_row, (list, tuple)) and len(raw_row) >= 4:
                    row = list(raw_row[:7])
                    if len(row) < 5:
                        row.append("")
                    if len(row) < 6:
                        row.append("production")
                    if len(row) < 7:
                        row.append("")
                else:
                    continue
                if row[0] not in (None, "") and _compact_text(row[1]) and _compact_text(row[2]) and _compact_text(row[3]):
                    rows.append(row)
            return rows

        db_name = _compact_text(payload.get("db_name")) or DB_NAME
        account_rows = _explicit_account_rows()
        account_ids = _account_ids_from_payload()
        if not account_rows and account_ids:
            account_result = get_company_by_id(account_ids, db_name=db_name)
            if not account_result.success:
                return account_result
            accounts = list((account_result.data or {}).get("records") or [])
            by_pk = {int(getattr(account, "pk", 0) or 0): account for account in accounts}
            for account_pk in account_ids:
                account = by_pk.get(int(account_pk))
                if account is None:
                    return Result.fail(
                        "Listing veri cekme icin API hesabi bulunamadi.",
                        close_dialog=False,
                        data={"api_account_id": account_pk},
                    )
                accept_language = ""
                extra_config = getattr(account, "extra_config", None)
                if isinstance(extra_config, dict):
                    accept_language = _compact_text(extra_config.get("acceptLanguage") or extra_config.get("accept_language"))
                else:
                    extra_config = {}
                client_scope = trendyol_account_client_kwargs(account)
                credential_reference = _compact_text(client_scope.get("credential_reference"))
                account_row = [
                    int(account_pk),
                    _compact_text(client_scope.get("api_key_id")) or credential_reference,
                    _compact_text(client_scope.get("api_key_secret")),
                    _compact_text(client_scope.get("supplier_id")),
                    accept_language,
                    _compact_text(client_scope.get("environment")) or "production",
                ]
                if credential_reference:
                    account_row.append(credential_reference)
                account_rows.append(
                    account_row
                )
        if not account_rows:
            return Result.fail("listing.action_fetch_listings adapter icin api_account_ids gerekir.", close_dialog=False)

        missing_credentials = [
            int(row[0])
            for row in account_rows
            if not (
                _compact_text(row[3])
                and (
                    (len(row) > 6 and _compact_text(row[6]))
                    or is_credential_reference(_compact_text(row[1]))
                    or (_compact_text(row[1]) and _compact_text(row[2]))
                )
            )
        ]
        if missing_credentials:
            return Result.fail(
                "Listing veri cekme icin API kimlik bilgileri eksik.",
                close_dialog=False,
                data={"api_account_ids": missing_credentials},
            )

        allowed = {
            "page",
            "size",
            "approved",
            "barcode",
            "stock_code",
            "product_main_id",
            "brand_ids",
            "start_date",
            "end_date",
            "date_query_type",
            "status",
            "next_page_token",
            "extra_params",
            "fetch_all_pages",
            "max_pages",
            "progress_callback",
        }
        call_payload = {key: value for key, value in payload.items() if key in allowed}
        if "page" in call_payload:
            call_payload["page"] = int(call_payload["page"] or 0)
        if "size" in call_payload:
            call_payload["size"] = int(call_payload["size"] or 50)
        if "max_pages" in call_payload and call_payload.get("max_pages") not in (None, ""):
            call_payload["max_pages"] = int(call_payload["max_pages"] or 0)
        fetch_result = _resolve_manual_return(listing_actions.action_fetch_listings(account_rows, **call_payload))
        if not fetch_result.success:
            return fetch_result
        fetch_data = dict(fetch_result.data or {}) if isinstance(fetch_result.data, dict) else {}
        items = [dict(row) for row in list(fetch_data.get("items") or []) if isinstance(row, dict)]
        save_result = listing_pipeline.save_listings_to_db(
            items,
            db_name=db_name,
            sync_api_account_ids=[int(row[0]) for row in account_rows if row and row[0] not in (None, "")],
            prune_missing=bool(payload.get("prune_missing", True)),
        )
        if not save_result.success:
            return save_result
        return Result.ok(
            "Listingler agent adapter ile cekildi ve DB'ye yazildi.",
            close_dialog=False,
            data={
                "fetch": {
                    key: value
                    for key, value in fetch_data.items()
                    if key not in {"accounts", "comp_api_account_list", "api_key", "api_secret"}
                },
                "save": dict(save_result.data or {}),
                "api_account_ids": [int(row[0]) for row in account_rows if row and row[0] not in (None, "")],
                "fetched_count": len(items),
                "saved_product_ids": [
                    _compact_text(
                        row.get("product_id")
                        or row.get("productId")
                        or row.get("variantId")
                        or row.get("contentId")
                        or row.get("platformListingId")
                        or row.get("id")
                    )
                    for row in items
                    if _compact_text(
                        row.get("product_id")
                        or row.get("productId")
                        or row.get("variantId")
                        or row.get("contentId")
                        or row.get("platformListingId")
                        or row.get("id")
                    )
                ],
            },
        )

    if capability_id in {
        "listing.action_update_price_inventory_for_account",
        "listing.action_update_approved_content_for_account",
    }:
        from Account.processors.pipeline import get_company_by_id
        from Listing.views import actions as listing_actions
        from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs
        from Marketplaces.processors.catalog import normalize_marketplace_environment

        call_payload = dict(payload)
        db_name = _compact_text(call_payload.pop("db_name", ""))
        api_account_id = call_payload.pop("api_account_id", None)
        if not call_payload.get("items"):
            return Result.fail(f"{capability_id} adapter icin items gerekir.", close_dialog=False)
        if api_account_id not in (None, ""):
            account_result = get_company_by_id([int(api_account_id)], db_name=db_name or DB_NAME)
            if not account_result.success:
                return Result.fail("Listing pazaryeri guncellemesi icin API hesabi bulunamadi.", close_dialog=False)
            account = list((account_result.data or {}).get("records") or [None])[0]
            if account is None:
                return Result.fail("Listing pazaryeri guncellemesi icin API hesabi bulunamadi.", close_dialog=False)
            extra_config = getattr(account, "extra_config", None)
            extra = dict(extra_config or {}) if isinstance(extra_config, dict) else {}
            client_scope = trendyol_account_client_kwargs(account)
            call_payload["api_key"] = _compact_text(client_scope.get("api_key_id"))
            call_payload["api_secret"] = _compact_text(client_scope.get("api_key_secret"))
            call_payload["seller_id"] = _compact_text(client_scope.get("supplier_id"))
            call_payload["environment"] = normalize_marketplace_environment(
                client_scope.get("environment") or "production"
            )
            credential_reference = _compact_text(client_scope.get("credential_reference"))
            if credential_reference:
                call_payload["credential_reference"] = credential_reference
            accept_language = _compact_text(extra.get("acceptLanguage") or extra.get("accept_language"))
            if accept_language:
                call_payload["accept_language"] = accept_language
        credential_reference = _compact_text(call_payload.get("credential_reference"))
        missing = []
        if not _compact_text(call_payload.get("seller_id")):
            missing.append("seller_id")
        if not credential_reference:
            missing.extend(
                key
                for key in ("api_key", "api_secret")
                if not _compact_text(call_payload.get(key))
            )
        if missing:
            return Result.fail(
                "Listing pazaryeri guncellemesi icin API kimlik bilgileri eksik.",
                close_dialog=False,
                data={"missing_parameters": missing, "api_account_id": api_account_id},
            )
        if capability_id == "listing.action_update_approved_content_for_account":
            return _resolve_manual_return(
                listing_actions.action_update_approved_content_for_account(**call_payload)
            )
        return _resolve_manual_return(
            listing_actions.action_update_price_inventory_for_account(**call_payload)
        )

    if capability_id == "account.delete_company_and_refresh":
        from Account.processors import pipeline as account_pipeline

        pk = payload.get("pk") or payload.get("company_pk") or payload.get("account_pk")
        if pk in (None, ""):
            return Result.fail("account.delete_company_and_refresh adapter icin pk gerekir.", close_dialog=False)
        return _resolve_manual_return(account_pipeline.delete_company_from_db(int(pk)))

    if capability_id == "finance.action_sync_finance_for_accounts":
        from Account.processors.pipeline import get_company_by_id
        from Finance.views import actions as finance_actions
        from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs

        call_payload = dict(payload)
        db_name = _compact_text(call_payload.pop("db_name", ""))
        raw_ids = (
            call_payload.pop("api_account_ids", None)
            or call_payload.pop("selected_company_pks", None)
            or call_payload.pop("company_pks", None)
            or call_payload.pop("company_ids", None)
        )
        accounts = call_payload.get("accounts")
        if accounts is None and raw_ids is not None:
            account_ids: list[int] = []
            for raw_id in _as_list(raw_ids):
                try:
                    account_pk = int(raw_id)
                except Exception:
                    continue
                if account_pk > 0 and account_pk not in account_ids:
                    account_ids.append(account_pk)
            if not account_ids:
                return Result.fail("finance.action_sync_finance_for_accounts adapter icin api_account_ids gerekir.", close_dialog=False)
            account_result = get_company_by_id(account_ids, db_name=db_name or DB_NAME)
            if not account_result.success:
                return account_result
            rows = list((account_result.data or {}).get("records") or [])
            by_pk = {int(getattr(row, "pk", 0) or 0): row for row in rows}
            accounts = []
            for account_pk in account_ids:
                account = by_pk.get(account_pk)
                if account is None:
                    return Result.fail(
                        "Finans sync icin API hesabi bulunamadi.",
                        close_dialog=False,
                        data={"api_account_id": account_pk},
                    )
                accounts.append(
                    {
                        "pk": account_pk,
                        "api_key": _compact_text(getattr(account, "api_key", "")),
                        "api_secret": _compact_text(getattr(account, "api_secret", "")),
                        "seller_id": _compact_text(getattr(account, "account_id", "")),
                        "comp_name": _compact_text(getattr(account, "comp_name", "")),
                        "extra_config": dict(getattr(account, "extra_config", None) or {}),
                    }
                )
        accounts = [dict(row or {}) for row in _as_list(accounts) if isinstance(row, dict)]
        if not accounts:
            return Result.fail("finance.action_sync_finance_for_accounts adapter icin accounts veya api_account_ids gerekir.", close_dialog=False)
        normalized_accounts: list[dict[str, Any]] = []
        missing_credentials: list[Any] = []
        for row in accounts:
            normalized_row = dict(row)
            extra_config = (
                dict(normalized_row.get("extra_config") or {})
                if isinstance(normalized_row.get("extra_config"), dict)
                else {}
            )
            for key in (
                "environment",
                "api_environment",
                "credential_reference",
                "credential_ref",
            ):
                if normalized_row.get(key) not in (None, "") and key not in extra_config:
                    extra_config[key] = normalized_row.get(key)
            if extra_config:
                normalized_row["extra_config"] = extra_config
            else:
                normalized_row.pop("extra_config", None)
            try:
                trendyol_account_client_kwargs(normalized_row)
            except Exception:
                missing_credentials.append(normalized_row.get("pk"))
                continue
            normalized_accounts.append(normalized_row)
        if missing_credentials:
            return Result.fail(
                "Finans sync icin API kimlik bilgileri eksik.",
                close_dialog=False,
                data={"api_account_ids": missing_credentials},
            )
        call_payload["accounts"] = normalized_accounts
        return _resolve_manual_return(finance_actions.action_sync_finance_for_accounts(**call_payload))

    if capability_id == "finance.action_sync_finance_for_selected_companies":
        from Finance.views import actions as finance_actions

        selected_company_pks = payload.get("selected_company_pks", payload.get("company_pks", payload.get("company_ids")))
        if selected_company_pks is not None:
            call_payload = dict(payload)
            for key in ("selected_company_pks", "company_pks", "company_ids", "company_list_widget"):
                call_payload.pop(key, None)
            raw_result = finance_actions.action_sync_finance_for_company_pks(
                [int(pk) for pk in _as_list(selected_company_pks)],
                **call_payload,
            )
            return _resolve_manual_return(raw_result)
        accounts = payload.get("accounts")
        if accounts is not None:
            call_payload = dict(payload)
            for key in ("accounts", "company_list_widget"):
                call_payload.pop(key, None)
            raw_result = finance_actions.action_sync_finance_for_accounts(_as_list(accounts), **call_payload)
            return _resolve_manual_return(raw_result)
        return Result.fail(
            "finance.action_sync_finance_for_selected_companies adapter icin selected_company_pks veya accounts gerekir.",
            close_dialog=False,
        )

    if capability_id == "labels.action_create_labels_from_selected_orders":
        from Labels.processors import pipeline as labels_pipeline

        order_numbers = payload.get("order_numbers") or payload.get("selected_order_numbers") or payload.get("orders")
        label_kwargs = {
            "brand_code": _compact_text(payload.get("brand_code")) or "TANEX",
            "model_code": _compact_text(payload.get("model_code")) or "TANEX_2736",
        }
        if _compact_text(payload.get("db_name")):
            label_kwargs["db_name"] = _compact_text(payload.get("db_name"))
        if payload.get("order_refs"):
            label_kwargs["order_refs"] = list(_as_list(payload.get("order_refs")))
        raw_result = labels_pipeline.create_order_label_from_orders(
            [str(order_no).strip() for order_no in _as_list(order_numbers) if str(order_no).strip()],
            **label_kwargs,
        )
        result = _resolve_manual_return(raw_result)
        if not result.success:
            return result
        result_data = dict(result.data or {})
        label_payload = result_data.get("label_payload") if isinstance(result_data.get("label_payload"), dict) else {}
        if label_payload:
            output_path = _compact_text(payload.get("output_path"))
            if not output_path:
                output_dir = MEDIA_EXPORTS / "labels"
                output_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = str(output_dir / f"agent_labels_{stamp}.docx")
            export_res = labels_pipeline.export_labels_to_word(
                label_payload=label_payload,
                brand_code=_compact_text(payload.get("brand_code")) or "TANEX",
                model_code=_compact_text(payload.get("model_code")) or "TANEX_2736",
                output_path=output_path,
            )
            export_result = _resolve_manual_return(export_res)
            if not export_result.success:
                return export_result
            result_data["output_path"] = output_path
            result_data["export"] = dict(export_result.data or {})
            result.data = result_data
        return result

    if capability_id == "labels.mark_orders_extracted_from_label_result":
        from Orders.processors import agentic_repository as orders_repo

        order_refs = [row for row in _as_list(payload.get("order_refs")) if isinstance(row, dict)]
        if not order_refs:
            order_refs = [
                {"orderNumber": _compact_text(order_number)}
                for order_number in _as_list(payload.get("order_numbers") or payload.get("orders"))
                if _compact_text(order_number)
            ]
        if not order_refs:
            return Result.fail("labels.mark_orders_extracted_from_label_result adapter icin order_numbers gerekir.", close_dialog=False)

        db_name = _compact_text(payload.get("db_name"))
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        domain_result = orders_repo.mark_order_headers_extracted(
            order_refs,
            db_name=db_name or DB_NAME,
            extracted_at=now_ms,
        )
        if not domain_result.success:
            return domain_result
        domain_data = dict(domain_result.data or {})
        updated = list(domain_data.get("order_numbers") or [])
        missing = list(domain_data.get("missing_order_numbers") or [])
        affected = int(domain_data.get("affected") or 0)

        if missing:
            return Result.fail(
                "Fis cikarildi isaretlenecek siparis bulunamadi: " + ", ".join(missing),
                close_dialog=False,
                data={"updated_order_numbers": updated, "missing_order_numbers": missing, "affected": affected},
            )
        return Result.ok(
            f"{len(updated)} siparis fis cikarildi olarak isaretlendi.",
            close_dialog=False,
            data={"order_numbers": updated, "updated_order_numbers": updated, "affected": affected, "extracted_at": now_ms},
        )

    if capability_id == "orders.save_return_claims_to_db":
        from Orders.processors.trendyol import pipeline as orders_pipeline

        if isinstance(payload.get("result"), Result):
            result_payload = payload["result"]
        else:
            claim_rows = (
                payload.get("return_claim_list")
                or payload.get("claims")
                or payload.get("records")
                or payload.get("return_claims")
                or []
            )
            result_payload = Result.ok(
                "Agent adapter return claim payload hazirladi.",
                close_dialog=False,
                data={"return_claim_list": list(claim_rows or [])},
            )
        db_name = _compact_text(payload.get("db_name"))
        raw_result = (
            orders_pipeline.save_return_claims_to_db(result_payload, db_name=db_name)
            if db_name
            else orders_pipeline.save_return_claims_to_db(result_payload)
        )
        return _resolve_manual_return(raw_result)

    if capability_id == "orders.mark_return_claims_stale":
        from Orders.processors.trendyol import pipeline as orders_pipeline

        claim_ids = [_compact_text(value) for value in _as_list(payload.get("claim_ids")) if _compact_text(value)]
        if not claim_ids:
            return Result.fail("orders.mark_return_claims_stale adapter icin claim_ids gerekir.", close_dialog=False)
        account_ids = payload.get("api_account_ids")
        kwargs: dict[str, Any] = {
            "claim_ids": claim_ids,
            "api_account_ids": [int(value) for value in _as_list(account_ids) if _compact_text(value)] if account_ids is not None else None,
            "claim_keys": [row for row in _as_list(payload.get("claim_keys")) if isinstance(row, dict)] or None,
            "reason": _compact_text(payload.get("reason")),
        }
        db_name = _compact_text(payload.get("db_name"))
        if db_name:
            kwargs["db_name"] = db_name
        return _resolve_manual_return(orders_pipeline.mark_return_claims_stale(**kwargs))

    if capability_id == "orders.restore_return_claims_from_stale":
        from Orders.processors.trendyol import pipeline as orders_pipeline

        claim_ids = [_compact_text(value) for value in _as_list(payload.get("claim_ids")) if _compact_text(value)]
        if not claim_ids:
            return Result.fail("orders.restore_return_claims_from_stale adapter icin claim_ids gerekir.", close_dialog=False)
        account_ids = payload.get("api_account_ids")
        kwargs: dict[str, Any] = {
            "claim_ids": claim_ids,
            "api_account_ids": [int(value) for value in _as_list(account_ids) if _compact_text(value)] if account_ids is not None else None,
            "claim_keys": [row for row in _as_list(payload.get("claim_keys")) if isinstance(row, dict)] or None,
            "reason": _compact_text(payload.get("reason")),
        }
        db_name = _compact_text(payload.get("db_name"))
        if db_name:
            kwargs["db_name"] = db_name
        return _resolve_manual_return(orders_pipeline.restore_return_claims_from_stale(**kwargs))

    if capability_id in {"orders.change_order_cargo_provider", "orders.change_orders_cargo_provider_bulk"}:
        from Orders.processors import agentic_repository as orders_repo
        from Orders.views import actions as orders_actions

        def _resolve_order(raw_order: Any, *, api_account_id: Any = None) -> Result | Any:
            if hasattr(raw_order, "orderNumber"):
                return raw_order
            token = _compact_text(raw_order)
            if not token:
                return Result.fail("orders.change_order_cargo_provider adapter icin order gerekir.", close_dialog=False)
            db_name = _compact_text(payload.get("db_name")) or DB_NAME
            resolved = orders_repo.resolve_order_record(
                token,
                api_account_id=int(api_account_id) if api_account_id not in (None, "") else None,
                db_name=db_name,
            )
            return (resolved.data or {}).get("record") if resolved.success else resolved

        provider_code = _compact_text(payload.get("cargo_provider_code")).upper()
        if not provider_code:
            return Result.fail("orders.change_order_cargo_provider adapter icin cargo_provider_code gerekir.", close_dialog=False)
        if capability_id == "orders.change_order_cargo_provider":
            raw_order = payload.get("order") or payload.get("order_number") or payload.get("package_id")
            order = _resolve_order(raw_order, api_account_id=payload.get("api_account_id"))
            if isinstance(order, Result):
                return order
            return _resolve_manual_return(orders_actions.change_order_cargo_provider(order, cargo_provider_code=provider_code))

        raw_order_refs = [row for row in _as_list(payload.get("order_refs")) if isinstance(row, dict)]
        raw_orders = payload.get("orders") or payload.get("order_numbers") or payload.get("package_ids")
        resolved_orders: list[Any] = []
        scoped_orders = (
            [
                (
                    row.get("order_number") or row.get("order") or row.get("package_id"),
                    row.get("api_account_id"),
                )
                for row in raw_order_refs
            ]
            if raw_order_refs
            else [(raw_order, None) for raw_order in _as_list(raw_orders)]
        )
        for raw_order, api_account_id in scoped_orders:
            order = _resolve_order(raw_order, api_account_id=api_account_id)
            if isinstance(order, Result):
                return order
            resolved_orders.append(order)
        return _resolve_manual_return(orders_actions.change_orders_cargo_provider_bulk(resolved_orders, cargo_provider_code=provider_code))

    if capability_id == "orders.approve_return_claim":
        from Orders.processors import agentic_repository as orders_repo
        from Orders.views import actions as orders_actions

        raw_order = payload.get("order")
        if hasattr(raw_order, "claimId"):
            claim = raw_order
        else:
            order_token = _compact_text(raw_order)
            if not order_token:
                return Result.fail("orders.approve_return_claim adapter icin order gerekir.", close_dialog=False)
            db_name = _compact_text(payload.get("db_name")) or DB_NAME
            resolved = orders_repo.resolve_return_claim(
                order_token,
                api_account_id=(
                    int(payload.get("api_account_id"))
                    if payload.get("api_account_id") not in (None, "")
                    else None
                ),
                db_name=db_name,
            )
            if not resolved.success:
                return Result.fail("Onaylanacak iade kaydi bulunamadi.", close_dialog=False)
            claim = (resolved.data or {}).get("record")
        call_payload = {"order": claim}
        for optional_name in ("date_from", "date_to"):
            if payload.get(optional_name) not in (None, ""):
                call_payload[optional_name] = payload.get(optional_name)
        return _resolve_manual_return(orders_actions.approve_return_claim(**call_payload))

    if capability_id == "orders.get_orders_from_companies":
        from Account.processors.pipeline import get_company_by_id
        from Orders.constants.trendyol.constants import TRENDYOL_STATUS_LIST
        from Orders.processors.trendyol import pipeline as orders_pipeline

        accounts = payload.get("comp_api_account_list") or payload.get("accounts")
        account_records: list[Any] = [
            row
            for row in _as_list(payload.get("account_records"))
            if row is not None
        ]
        selected_company_pks = (
            payload.get("api_account_ids")
            or payload.get("selected_company_pks")
            or payload.get("company_pks")
            or payload.get("company_ids")
        )
        db_name = _compact_text(payload.get("db_name"))
        if accounts is None and selected_company_pks is not None:
            company_res = get_company_by_id(
                [int(pk) for pk in _as_list(selected_company_pks)],
                db_name=db_name or DB_NAME,
            )
            if not company_res.success:
                return company_res
            accounts = (company_res.data or {}).get("accounts", []) or []
            account_records = list(
                (company_res.data or {}).get("records", []) or []
            )
        accounts = _as_list(accounts)
        if not accounts:
            return Result.fail("orders.get_orders_from_companies adapter icin accounts veya api_account_ids gerekir.", close_dialog=False)
        if bool(payload.get("fetch_returns", True)) and not account_records:
            account_ids_for_records: list[int] = []
            for account in accounts:
                if not isinstance(account, (list, tuple)) or not account:
                    continue
                try:
                    account_id = int(account[0])
                except Exception:
                    continue
                if account_id > 0 and account_id not in account_ids_for_records:
                    account_ids_for_records.append(account_id)
            if account_ids_for_records:
                records_result = get_company_by_id(
                    account_ids_for_records,
                    db_name=db_name or DB_NAME,
                )
                if records_result.success:
                    account_records = list(
                        (records_result.data or {}).get("records", [])
                        or []
                    )

        final_ep_time = int(payload.get("final_ep_time") or payload.get("end_ms") or int(datetime.now(timezone.utc).timestamp() * 1000))
        start_ep_time = int(payload.get("start_ep_time") or payload.get("start_ms") or (final_ep_time - 24 * 60 * 60 * 1000))
        status_list = [str(status) for status in _as_list(payload.get("status_list") or TRENDYOL_STATUS_LIST) if str(status).strip()]
        fetch_result = _resolve_manual_return(
            orders_pipeline.fetch_orders_all(
                status_list=status_list,
                final_ep_time=final_ep_time,
                start_ep_time=start_ep_time,
                comp_api_account_list=accounts,
                start_page=int(payload.get("start_page") or 0),
            )
        )
        if not fetch_result.success:
            return fetch_result
        if bool(payload.get("save_to_db", True)):
            save_result = (
                orders_pipeline.save_orders_to_db(fetch_result, db_name=db_name)
                if db_name
                else orders_pipeline.save_orders_to_db(fetch_result)
            )
            if not save_result.success:
                return save_result
            raw_fetch_data = dict(fetch_result.data or {})
            fetched_order_rows = [
                dict(row)
                for row in list(raw_fetch_data.get("order_data_list") or [])
                if isinstance(row, dict)
            ]
            fetched_item_rows = [
                dict(row)
                for row in list(raw_fetch_data.get("order_item_list") or [])
                if isinstance(row, dict)
            ]
            data = {
                "fetch": {
                    "order_snapshot_count": len(fetched_order_rows),
                    "item_row_count": len(fetched_item_rows),
                    "sync_diagnostics": _without_secretish_keys(
                        dict(raw_fetch_data.get("sync_diagnostics") or {})
                    ),
                },
                "save": dict(save_result.data or {}),
            }
            returns_rows = list(
                payload.get("return_claim_list")
                or payload.get("return_claims")
                or payload.get("observed_return_claims")
                or []
            )
            return_snapshot_complete = bool(
                payload.get("return_snapshot_complete")
                or payload.get("observed_return_snapshot_complete")
            )
            returns_fetch_data: dict[str, Any] = {}
            if bool(payload.get("fetch_returns", True)) and not returns_rows:
                try:
                    from Orders.views import actions as orders_actions

                    returns_fetch = _resolve_manual_return(
                        orders_actions._run_async_safely(
                            orders_actions._fetch_returns_from_active_companies_async(
                                account_records,
                                start_ms=start_ep_time,
                                end_ms=final_ep_time,
                                size=int(payload.get("return_page_size") or 50),
                                claim_ids=[str(item) for item in _as_list(payload.get("claim_ids")) if str(item).strip()] or None,
                            )
                        )
                    )
                    returns_fetch_data = dict(returns_fetch.data or {})
                    if returns_fetch.success:
                        returns_rows = list(returns_fetch_data.get("return_claim_list") or [])
                        return_snapshot_complete = True
                    else:
                        data["returns_fetch_error"] = returns_fetch.message
                except Exception as exc:
                    data["returns_fetch_error"] = map_error_to_message(exc)
            elif returns_rows:
                returns_fetch_data = {"return_claim_list": list(returns_rows), "source": "payload"}
                return_snapshot_complete = True

            if returns_fetch_data:
                data["returns_fetch"] = {
                    "return_claim_count": len(returns_rows),
                    "error_count": len(list(returns_fetch_data.get("errors") or [])),
                    "source": _compact_text(returns_fetch_data.get("source")) or "marketplace",
                }
            if returns_rows and bool(payload.get("save_returns_to_db", True)):
                return_result_payload = Result.ok(
                    "Agent adapter return claim payload hazirladi.",
                    close_dialog=False,
                    data={"return_claim_list": list(returns_rows)},
                )
                returns_save_result = (
                    orders_pipeline.save_return_claims_to_db(return_result_payload, db_name=db_name)
                    if db_name
                    else orders_pipeline.save_return_claims_to_db(return_result_payload)
                )
                if not returns_save_result.success:
                    return returns_save_result
                data["returns_save"] = dict(returns_save_result.data or {})

            observed_ids = (
                [str(item).strip() for item in _as_list(payload.get("observed_return_claim_ids")) if str(item).strip()]
                or _claim_ids_from_rows(returns_rows)
            )
            observed_account_ids = sorted(
                {
                    int(row.get("api_account_id"))
                    for row in returns_rows
                    if isinstance(row, dict)
                    and row.get("api_account_id") not in (None, "")
                }
            )
            if observed_ids or bool(payload.get("verify_return_reconciliation", False)):
                from AI.processors.tools import returns_reconcile_snapshot

                from settings import DB_NAME as SETTINGS_DB_NAME

                reconcile_result = returns_reconcile_snapshot(
                    db_name=db_name or SETTINGS_DB_NAME,
                    observed_claim_ids=observed_ids,
                    period="all",
                    start_ms=start_ep_time,
                    end_ms=final_ep_time,
                    snapshot_complete=return_snapshot_complete,
                    filters={
                        "api_account_ids": observed_account_ids,
                    }
                    if observed_account_ids
                    else {},
                    limit=int(payload.get("return_reconcile_limit") or 100),
                )
                data["return_reconciliation"] = dict(reconcile_result.data or {})
                data["return_reconciliation_message"] = reconcile_result.message
            account_ids: list[int] = []
            for account in accounts:
                if not isinstance(account, (list, tuple)) or not account:
                    continue
                try:
                    account_id = int(account[0])
                except Exception:
                    continue
                if account_id > 0 and account_id not in account_ids:
                    account_ids.append(account_id)
            orders_pipeline.update_last_used_at_for_accounts(
                accounts,
                db_name=db_name or DB_NAME,
                safety_minutes=int(payload.get("safety_minutes") or 0),
            )
            last_used_rows: list[dict[str, Any]] = []
            if account_ids:
                from Account.processors.pipeline import get_company_by_id

                account_result = get_company_by_id(account_ids, db_name=db_name or DB_NAME)
                account_rows = (
                    list((account_result.data or {}).get("records") or [])
                    if account_result.success
                    else []
                )
                last_used_rows = [
                    {
                        "account_id": int(getattr(row, "pk", 0) or 0),
                        "last_used_at": (
                            getattr(row, "last_used_at", None).isoformat()
                            if getattr(row, "last_used_at", None) is not None
                            else ""
                        ),
                    }
                    for row in account_rows
                ]
            data["last_used_update"] = {
                "requested_account_ids": account_ids,
                "rows": last_used_rows,
                "verified": (
                    bool(account_ids)
                    and {row.get("account_id") for row in last_used_rows}
                    == set(account_ids)
                    and all(
                        _compact_text(row.get("last_used_at"))
                        for row in last_used_rows
                    )
                ),
            }
            data["fetched_identifiers"] = {
                "order_numbers": list(
                    dict.fromkeys(
                        _compact_text(row.get("orderNumber") or row.get("order_number"))
                        for row in fetched_order_rows
                        if _compact_text(row.get("orderNumber") or row.get("order_number"))
                    )
                ),
                "claim_ids": _claim_ids_from_rows(returns_rows),
            }
            sync_observability = orders_pipeline.build_orders_sync_observability(
                fetch_result,
                save_result,
                account_ids=account_ids,
                account_records=account_records,
                return_claim_rows=returns_rows,
                returns_save_data=dict(data.get("returns_save") or {}),
                start_ms=start_ep_time,
                end_ms=final_ep_time,
                db_name=db_name or DB_NAME,
            )
            sync_observability.setdefault("watermark", {}).update(
                {
                    "last_used_rows": last_used_rows,
                    "last_used_readback_verified": data["last_used_update"]["verified"],
                }
            )
            if data.get("returns_fetch_error"):
                errors = sync_observability.setdefault("errors", {})
                errors["return_fetch_errors"] = 1
                errors["count"] = int(errors.get("count") or 0) + 1
                errors["return_fetch_message"] = _compact_text(data.get("returns_fetch_error"))
            data["sync_observability"] = sync_observability
            data["db_readback"] = dict(sync_observability.get("db_readback") or {})
            return Result.ok("Siparisler agent adapter ile cekildi ve DB'ye yazildi.", close_dialog=False, data=data)
        return fetch_result

    if capability_id == "orders.update_last_used_at_for_accounts":
        from Account.processors.pipeline import get_company_by_id
        from Orders.processors.trendyol import pipeline as orders_pipeline

        accounts = payload.get("comp_api_account_list") or payload.get("accounts")
        selected_company_pks = (
            payload.get("api_account_ids")
            or payload.get("selected_company_pks")
            or payload.get("company_pks")
            or payload.get("company_ids")
        )
        db_name = _compact_text(payload.get("db_name"))
        if accounts is None and selected_company_pks is not None:
            company_res = get_company_by_id(
                [int(pk) for pk in _as_list(selected_company_pks)],
                db_name=db_name or DB_NAME,
            )
            if not company_res.success:
                return company_res
            accounts = (company_res.data or {}).get("accounts", []) or []
        accounts = _as_list(accounts)
        if not accounts:
            return Result.fail("orders.update_last_used_at_for_accounts adapter icin accounts veya api_account_ids gerekir.", close_dialog=False)
        safety_minutes = int(payload.get("safety_minutes") or 0)
        if db_name:
            orders_pipeline.update_last_used_at_for_accounts(accounts, db_name=db_name, safety_minutes=safety_minutes)
        else:
            orders_pipeline.update_last_used_at_for_accounts(accounts, safety_minutes=safety_minutes)
        return Result.ok(
            "Hesap last_used_at alanlari agent adapter ile guncellendi.",
            close_dialog=False,
            data={"account_count": len(accounts), "db_name": db_name or None, "safety_minutes": safety_minutes},
        )
    if capability_id == "stock.action_export_txs_excel":
        from Stock.processors import agentic_repository as stock_repo
        from Stock.views import actions as stock_actions

        output_path = _compact_text(payload.get("output_path"))
        if not output_path:
            return Result.fail("stock.action_export_txs_excel adapter icin output_path gerekir.", close_dialog=False)
        tx_ids: list[int] = []
        for raw_tx_id in _as_list(payload.get("tx_ids") or payload.get("tx_id")):
            try:
                tx_id = int(raw_tx_id or 0)
            except Exception:
                tx_id = 0
            if tx_id > 0 and tx_id not in tx_ids:
                tx_ids.append(tx_id)
        if not tx_ids and isinstance(payload.get("txs"), list):
            call_payload = dict(payload)
            call_payload.pop("tx_ids", None)
            call_payload.pop("tx_id", None)
            call_payload.pop("db_name", None)
            return _resolve_manual_return(stock_actions.action_export_txs_excel(**call_payload))
        if not tx_ids:
            return Result.fail("stock.action_export_txs_excel adapter icin tx_ids gerekir.", close_dialog=False)
        db_name = _compact_text(payload.get("db_name"))
        tx_result = stock_repo.list_transactions(db_name=db_name or DB_NAME)
        if not tx_result.success:
            return tx_result
        by_pk = {
            int(getattr(tx, "pk", 0) or 0): tx
            for tx in list((tx_result.data or {}).get("records") or [])
        }
        txs = [by_pk[tx_id] for tx_id in tx_ids if tx_id in by_pk]
        if len(txs) != len(tx_ids):
            return Result.fail(
                "Excel export icin bazi stok hareketleri bulunamadi.",
                close_dialog=False,
                data={"requested_tx_ids": tx_ids, "found_count": len(txs)},
            )
        return _resolve_manual_return(stock_actions.action_export_txs_excel(txs=txs, output_path=output_path))
    if capability_id in {
        "stock.action_create_brand",
        "stock.action_update_brand",
        "stock.action_delete_brand",
        "stock.action_create_company",
        "stock.action_update_company",
        "stock.action_delete_company",
    }:
        from Finance.views import actions as finance_actions

        db_name = _compact_text(payload.get("db_name"))
        call_payload = dict(payload)
        call_payload.pop("db_name", None)
        if db_name:
            call_payload["db_name"] = db_name
        action_map = {
            "stock.action_create_brand": finance_actions.action_create_brand,
            "stock.action_update_brand": finance_actions.action_update_brand,
            "stock.action_delete_brand": finance_actions.action_delete_brand,
            "stock.action_create_company": finance_actions.action_create_company,
            "stock.action_update_company": finance_actions.action_update_company,
            "stock.action_delete_company": finance_actions.action_delete_company,
        }
        return _resolve_manual_return(action_map[capability_id](**call_payload))
    return None


def _stock_call_in_db(db_name: str, func: Any, **payload: Any) -> Result:
    with stock_pipeline.database_scope(db_name):
        return _resolve_manual_return(func(**payload))


def _stock_item_by_sku(sku: str, *, db_name=None) -> dict[str, Any] | None:
    result = stock_pipeline.list_items(only_active=False, **({"db_name": db_name} if db_name else {}))
    if not result.success:
        return None
    for row in list((result.data or {}).get("records") or []):
        if _compact_text(getattr(row, "sku", "")).casefold() == _compact_text(sku).casefold():
            return {
                "id": int(getattr(row, "pk", 0) or 0),
                "sku": _compact_text(getattr(row, "sku", "")),
                "name": _compact_text(getattr(row, "name", "")),
                "barcode": _compact_text(getattr(row, "barcode", "")),
                "brand": _compact_text(getattr(row, "brand", "")),
                "category": _compact_text(getattr(row, "category", "")),
                "unit": _compact_text(getattr(row, "unit", "")),
                "is_active": bool(getattr(row, "is_active", True)),
            }
    return None


def verify_stock_item_create(action: dict[str, Any]) -> Result:
    try:
        rows = action.get("rows") if isinstance(action, dict) else []
        row = dict(rows[0]) if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
        after = dict(row.get("after") or {})
        sku = _compact_text(after.get("sku"))
        if not sku:
            return Result.fail("Verify icin SKU bulunamadi.", close_dialog=False)
        record = _stock_item_by_sku(sku, db_name=_manual_payload_from_action(action).get("db_name"))
        if record is None:
            return Result.fail("Stok karti execute sonrasi bulunamadi.", close_dialog=False)
        return Result.ok(
            "Stok karti execute sonrasi dogrulandi.",
            close_dialog=False,
            data={"verified": True, "record": record},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def execute_stock_item_create(
    action: dict[str, Any],
    *,
    approved_by: str = "user",
    idempotency_key: str | None = None,
    audit_path: str | Path | None = None,
) -> Result:
    try:
        guard = _approved_action(action, expected_action_type="stock.item_create")
        if guard is not None:
            return guard
        key = _compact_text(idempotency_key) or operation_idempotency_key(action, namespace="stock.item_create")
        previous = _previous_success(key, audit_path=audit_path)
        if previous is not None:
            return Result.ok(
                "Stok karti olusturma daha once ayni idempotency key ile tamamlanmis.",
                close_dialog=False,
                data={"idempotent": True, "audit": previous},
            )

        rows = action.get("rows") if isinstance(action.get("rows"), list) else []
        row = dict(rows[0]) if rows and isinstance(rows[0], dict) else {}
        payload = dict(row.get("after") or {})
        allowed = {
            "sku",
            "name",
            "barcode",
            "unit",
            "brand",
            "category",
            "sub_category",
        }
        call_payload = {key_name: value for key_name, value in payload.items() if key_name in allowed}
        result = _stock_call_in_db(_manual_payload_from_action(action).get("db_name") or stock_pipeline.DB_NAME,
                                   stock_pipeline.create_item, **call_payload)
        verify = verify_stock_item_create(action) if result.success else Result.fail("Execute basarisiz; verify atlandi.", close_dialog=False)
        entry = {
            "timestamp": _utcnow_iso(),
            "idempotency_key": key,
            "operation": "stock.item_create",
            "approved_by": _compact_text(approved_by) or "user",
            "status": "success" if result.success and verify.success else "failed",
            "action": action,
            "result_message": result.message,
            "verify_message": verify.message,
            "verify": dict(verify.data or {}),
        }
        _append_audit_entry(entry, audit_path=audit_path)
        if not result.success:
            return result
        if not verify.success:
            return verify
        return Result.ok(
            "Stok karti olusturuldu ve dogrulandi.",
            close_dialog=False,
            data={
                "idempotency_key": key,
                "audit": entry,
                "result": dict(result.data or {}),
                "verify": dict(verify.data or {}),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_stock_item_update(action: dict[str, Any]) -> Result:
    try:
        rows = action.get("rows") if isinstance(action, dict) else []
        verified_rows: list[dict[str, Any]] = []
        for row in [dict(item) for item in rows if isinstance(item, dict)]:
            after = dict(row.get("after") or {})
            sku = _compact_text(after.get("sku"))
            record = _stock_item_by_sku(sku, db_name=_manual_payload_from_action(action).get("db_name"))
            if record is None:
                return Result.fail(f"Stok karti bulunamadi: {sku}", close_dialog=False)
            for key, expected in after.items():
                if key in {"id"}:
                    continue
                if key in record and record.get(key) != expected:
                    return Result.fail(f"Verify alani eslesmedi: {sku}/{key}", close_dialog=False)
            verified_rows.append(record)
        return Result.ok(
            "Stok karti guncelleme execute sonrasi dogrulandi.",
            close_dialog=False,
            data={"verified": True, "records": verified_rows},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def execute_stock_item_update(
    action: dict[str, Any],
    *,
    approved_by: str = "user",
    idempotency_key: str | None = None,
    audit_path: str | Path | None = None,
) -> Result:
    try:
        guard = _approved_action(action, expected_action_type="stock.item_update")
        if guard is not None:
            return guard
        key = _compact_text(idempotency_key) or operation_idempotency_key(action, namespace="stock.item_update")
        previous = _previous_success(key, audit_path=audit_path)
        if previous is not None:
            return Result.ok(
                "Stok karti guncelleme daha once ayni idempotency key ile tamamlanmis.",
                close_dialog=False,
                data={"idempotent": True, "audit": previous},
            )

        rows = [dict(item) for item in list(action.get("rows") or []) if isinstance(item, dict)]
        for row in rows:
            item_id = int(row.get("id") or 0)
            changes = dict(row.get("changes") or {})
            update_data = {name: (change or {}).get("after") for name, change in changes.items() if isinstance(change, dict)}
            if item_id <= 0 or not update_data:
                continue
            result = _stock_call_in_db(_manual_payload_from_action(action).get("db_name") or stock_pipeline.DB_NAME,
                                       stock_pipeline.update_item, pk=item_id, update_data=update_data)
            if not result.success:
                entry = {
                    "timestamp": _utcnow_iso(),
                    "idempotency_key": key,
                    "operation": "stock.item_update",
                    "approved_by": _compact_text(approved_by) or "user",
                    "status": "failed",
                    "action": action,
                    "result_message": result.message,
                }
                _append_audit_entry(entry, audit_path=audit_path)
                return result
        verify = verify_stock_item_update(action)
        entry = {
            "timestamp": _utcnow_iso(),
            "idempotency_key": key,
            "operation": "stock.item_update",
            "approved_by": _compact_text(approved_by) or "user",
            "status": "success" if verify.success else "failed",
            "action": action,
            "verify_message": verify.message,
            "verify": dict(verify.data or {}),
        }
        _append_audit_entry(entry, audit_path=audit_path)
        if not verify.success:
            return verify
        return Result.ok(
            "Stok karti guncellendi ve dogrulandi.",
            close_dialog=False,
            data={
                "idempotency_key": key,
                "audit": entry,
                "verify": dict(verify.data or {}),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _action_rows(action: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in list((action or {}).get("rows") or []) if isinstance(row, dict)]


def _expected_cargo_provider_names(action: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for row in _action_rows(action):
        after = dict(row.get("after") or {})
        provider = _compact_text(after.get("cargo_provider") or after.get("cargo_provider_name"))
        if provider:
            names.add(provider.casefold())
    return names


def verify_order_cargo_provider_change(action: dict[str, Any]) -> Result:
    try:
        from Orders.processors import agentic_repository as orders_repo

        payload = _manual_payload_from_action(action)
        db_name = _compact_text(payload.get("db_name")) or DB_NAME
        expected_names = _expected_cargo_provider_names(action)
        verified_rows: list[dict[str, Any]] = []
        if not expected_names:
            return Result.fail("Kargo verify icin beklenen provider adi bulunamadi.", close_dialog=False)
        staging_proof = dict((action or {}).get("staging_proof") or {})
        staging_verify = bool(staging_proof)
        for row in _action_rows(action):
            before = dict(row.get("before") or {})
            after = dict(row.get("after") or {})
            order_number = _compact_text(row.get("order_number") or before.get("order_number"))
            package_id = row.get("package_id") or before.get("package_id")
            api_account_id = row.get("api_account_id") or before.get("api_account_id")
            token = order_number or package_id
            if not _compact_text(token):
                return Result.fail("Kargo verify icin siparis referansi bulunamadi.", close_dialog=False)
            resolved = orders_repo.resolve_order_record(
                token,
                api_account_id=(int(api_account_id) if api_account_id not in (None, "") else None),
                db_name=db_name,
            )
            if not resolved.success:
                return Result.fail(f"Kargo verify siparis kaydi bulunamadi: {token}", close_dialog=False)
            record = (resolved.data or {}).get("record")
            provider_name = _compact_text(getattr(record, "cargoProviderName", ""))
            if provider_name.casefold() not in expected_names:
                return Result.fail(
                    f"Kargo verify eslesmedi: {token} provider={provider_name}",
                    close_dialog=False,
                    data={"expected_provider_names": sorted(expected_names), "actual_provider": provider_name},
                )

            verified_by = "db"
            if staging_verify:
                from Orders.views import actions as orders_actions

                api_account = getattr(record, "api_account", None)
                if api_account is None:
                    return Result.fail("Stage kargo verify icin API hesabi bulunamadi.", close_dialog=False)
                api = orders_actions._trendyol_api_for_account(api_account)
                expected_codes = {
                    _compact_text(after.get("cargo_provider_code")).upper(),
                } - {""}

                async def _read_back_remote() -> tuple[Result, dict[str, Any] | None]:
                    last_result: Result | None = None
                    for attempt in range(6):
                        last_result = await api.get_order_by_number(order_number, page=0, size=50)
                        if last_result.success:
                            content = list((last_result.data or {}).get("content") or [])
                            remote_row = next(
                                (
                                    item
                                    for item in content
                                    if _compact_text(item.get("orderNumber")) == order_number
                                    and _compact_text(item.get("id") or item.get("shipmentPackageId"))
                                    == _compact_text(package_id)
                                ),
                                None,
                            )
                            if remote_row is not None:
                                remote_provider = _compact_text(remote_row.get("cargoProviderName"))
                                platform_code = _compact_text(getattr(api_account, "platform", ""))
                                remote_code = _compact_text(
                                    orders_actions.cargo_provider_code_for_name(
                                        remote_provider,
                                        platform_code=platform_code or None,
                                    )
                                ).upper()
                                if remote_provider.casefold() in expected_names or remote_code in expected_codes:
                                    return last_result, remote_row
                        if attempt < 5:
                            await asyncio.sleep(1.5)
                    return last_result or Result.fail("Stage kargo read-back calismadi.", close_dialog=False), None

                read_result, remote_row = orders_actions._run_async_safely(_read_back_remote())
                if not read_result.success:
                    return Result.fail(
                        "Stage kargo degisikligi API read-back istegi basarisiz.",
                        close_dialog=False,
                        data={"verified": False, "status_code": (read_result.data or {}).get("status_code")},
                    )
                if remote_row is None:
                    return Result.fail(
                        "Stage kargo degisikligi getShipmentPackages read-back ile dogrulanamadi.",
                        close_dialog=False,
                        data={"verified": False},
                    )
                verified_by = "db+stage_get_order_by_number"

            verified_rows.append(
                {
                    "api_account_id": api_account_id,
                    "order_number": order_number,
                    "package_id": package_id,
                    "cargo_provider": provider_name,
                    "verified_by": verified_by,
                }
            )
        message = (
            "Kargo firmasi DB ve Stage API read-back ile dogrulandi."
            if staging_verify
            else "Kargo firmasi DB verify ile dogrulandi."
        )
        return Result.ok(message, close_dialog=False, data={"verified": True, "rows": verified_rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_labels_create(
    action: dict[str, Any],
    result: Result | None = None,
    *,
    semantic_only: bool = False,
) -> Result:
    try:
        payload = _manual_payload_from_action(action)
        expected = [_compact_text(value) for value in list(payload.get("order_numbers") or []) if _compact_text(value)]
        if not expected:
            return Result.fail("Label verify icin order_numbers bulunamadi.", close_dialog=False)
        arguments = (
            dict(action.get("arguments") or {})
            if isinstance(action.get("arguments"), dict)
            else {}
        )
        source_selection_id = _compact_text(arguments.get("source_selection_id"))
        db_name = _compact_text(payload.get("db_name"))
        semantic_scope_required = bool(source_selection_id and db_name)
        semantic_rows: list[dict[str, Any]] = []
        # New label preparations carry authoritative Orders provenance. Keep
        # legacy/manual verification compatible, but never execute a newly
        # prepared label without re-reading the current Orders status.
        if semantic_scope_required:
            action_selection_id = _compact_text(action.get("selection_id"))
            if action_selection_id and action_selection_id != source_selection_id:
                return Result.fail(
                    "Label selection kimligi prepare kaynagiyla eslesmiyor.",
                    close_dialog=False,
                    data={"verified": False, "semantic_scope_verified": False},
                )
            from Orders.processors import agentic_repository as orders_repo
            from Orders.processors.trendyol.pipeline import (
                is_ready_to_ship_order_status,
            )

            account_by_order = {
                _compact_text(key): _compact_text(value)
                for key, value in dict(arguments.get("account_by_order") or {}).items()
                if _compact_text(key) and _compact_text(value)
            }
            account_ids = sorted(
                {
                    int(value)
                    for value in account_by_order.values()
                    if value.isdigit()
                }
            )
            current_result = orders_repo.list_orders(
                order_numbers=expected,
                api_account_ids=account_ids or None,
                db_name=db_name or DB_NAME,
            )
            if not current_result.success:
                return current_result
            latest_by_ref: dict[tuple[str, str], Any] = {}
            for row in list((current_result.data or {}).get("records") or []):
                order_number = _compact_text(getattr(row, "orderNumber", ""))
                account_id = _compact_text(getattr(row, "api_account_id", ""))
                key = (order_number, account_id)
                current = latest_by_ref.get(key)
                if current is None or int(getattr(row, "pk", 0) or 0) > int(
                    getattr(current, "pk", 0) or 0
                ):
                    latest_by_ref[key] = row

            missing: list[str] = []
            ineligible: list[dict[str, str]] = []
            ambiguous: list[str] = []
            for order_number in expected:
                expected_account = account_by_order.get(order_number, "")
                candidates = [
                    row
                    for (number, account_id), row in latest_by_ref.items()
                    if number == order_number
                    and (not expected_account or account_id == expected_account)
                ]
                if not candidates:
                    missing.append(order_number)
                    continue
                if len(candidates) != 1:
                    ambiguous.append(order_number)
                    continue
                row = candidates[0]
                status = _compact_text(
                    getattr(row, "shipmentPackageStatus", "")
                    or getattr(row, "status", "")
                )
                simulated = (
                    order_number.upper().startswith("SIM-")
                    or _compact_text(getattr(row, "cargoProviderName", ""))
                    .casefold()
                    .startswith("simulated ")
                )
                semantic_rows.append(
                    {
                        "order_number": order_number,
                        "api_account_id": _compact_text(
                            getattr(row, "api_account_id", "")
                        ),
                        "status": status,
                    }
                )
                if simulated or not is_ready_to_ship_order_status(status):
                    ineligible.append(
                        {
                            "order_number": order_number,
                            "status": status or "Unknown",
                            "reason": "simulation" if simulated else "not_ready_to_ship",
                        }
                    )
            if missing or ambiguous or ineligible:
                return Result.fail(
                    "Label execute oncesi Orders uygunluk dogrulamasi basarisiz; "
                    "dosya veya yazici ciktisi olusturulmadi.",
                    close_dialog=False,
                    data={
                        "verified": False,
                        "semantic_scope_verified": False,
                        "missing_order_numbers": missing,
                        "ambiguous_order_numbers": ambiguous,
                        "ineligible_orders": ineligible,
                        "api_call_performed": False,
                        "db_write_performed": False,
                        "file_output_performed": False,
                    },
                )
        if semantic_only:
            return Result.ok(
                "Label execute oncesi Orders uygunluk dogrulamasi tamamlandi.",
                close_dialog=False,
                data={
                    "verified": True,
                    "semantic_scope_verified": semantic_scope_required,
                    "semantic_rows": semantic_rows,
                    "order_numbers": expected,
                },
            )
        result_data = dict((result.data if result is not None and isinstance(result.data, dict) else {}) or {})
        actual = [_compact_text(value) for value in list(result_data.get("order_numbers") or []) if _compact_text(value)]
        if actual and actual != expected:
            return Result.fail(
                "Label verify order_numbers eslesmedi.",
                close_dialog=False,
                data={"expected_order_numbers": expected, "actual_order_numbers": actual},
            )
        output_path = _compact_text(payload.get("output_path") or result_data.get("output_path"))
        verify_data: dict[str, Any] = {
            "verified": True,
            "order_numbers": expected,
            "semantic_scope_verified": semantic_scope_required,
            "semantic_rows": semantic_rows,
        }
        if output_path:
            path = Path(output_path)
            if not path.exists() or not path.is_file():
                return Result.fail(
                    "Label verify dosyayi bulamadi.",
                    close_dialog=False,
                    data={"verified": False, "order_numbers": expected, "output_path": str(path)},
                )
            size_bytes = path.stat().st_size
            if size_bytes <= 0:
                return Result.fail(
                    "Label verify dosya bos gorundu.",
                    close_dialog=False,
                    data={"verified": False, "order_numbers": expected, "output_path": str(path), "size_bytes": size_bytes},
                )
            if path.suffix.casefold() == ".docx":
                try:
                    with zipfile.ZipFile(path) as archive:
                        xml_names = [
                            name
                            for name in archive.namelist()
                            if name.startswith("word/") and name.endswith(".xml")
                        ]
                        if not xml_names:
                            return Result.fail(
                                "Label verify docx icerigini okuyamadi.",
                                close_dialog=False,
                                data={
                                    "verified": False,
                                    "order_numbers": expected,
                                    "output_path": str(path),
                                    "size_bytes": size_bytes,
                                },
                            )
                        text_parts: list[str] = []
                        for name in xml_names:
                            xml_text = archive.read(name).decode("utf-8", errors="ignore")
                            text_parts.append(unescape(xml_text))
                            text_parts.append(unescape(re.sub(r"<[^>]+>", "", xml_text)))
                except zipfile.BadZipFile:
                    return Result.fail(
                        "Label verify docx dosyasi gecersiz.",
                        close_dialog=False,
                        data={"verified": False, "order_numbers": expected, "output_path": str(path), "size_bytes": size_bytes},
                    )
                docx_text = "\n".join(text_parts)
                missing = [order_number for order_number in expected if order_number not in docx_text]
                if missing:
                    return Result.fail(
                        "Label verify docx icinde beklenen siparisleri bulamadi.",
                        close_dialog=False,
                        data={
                            "verified": False,
                            "order_numbers": expected,
                            "missing_order_numbers": missing,
                            "output_path": str(path),
                            "size_bytes": size_bytes,
                        },
                    )
                verify_data.update(
                    {
                        "output_path": str(path),
                        "size_bytes": size_bytes,
                        "verified_by": "payload_and_docx_content",
                        "docx_order_numbers_verified": True,
                    }
                )
            else:
                verify_data.update({"output_path": str(path), "size_bytes": size_bytes, "verified_by": "payload_and_filesystem"})
        return Result.ok("Label olusturma payload/result verify ile dogrulandi.", close_dialog=False, data=verify_data)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_labels_mark_extracted(action: dict[str, Any], result: Result | None = None) -> Result:
    try:
        from Orders.processors import agentic_repository as orders_repo

        payload = _manual_payload_from_action(action)
        expected = [_compact_text(value) for value in list(payload.get("order_numbers") or []) if _compact_text(value)]
        result_data = dict((result.data if result is not None and isinstance(result.data, dict) else {}) or {})
        if not expected:
            expected = [_compact_text(value) for value in list(result_data.get("order_numbers") or []) if _compact_text(value)]
        if not expected:
            return Result.fail("Fis cikarildi verify icin order_numbers bulunamadi.", close_dialog=False)

        db_name = _compact_text(payload.get("db_name")) or DB_NAME
        domain_result = orders_repo.list_order_headers(expected, db_name=db_name)
        if not domain_result.success:
            return domain_result
        rows = list((domain_result.data or {}).get("records") or [])
        extracted = {
            _compact_text(getattr(row, "orderNumber", ""))
            for row in rows
            if bool(getattr(row, "is_extracted", False))
        }
        missing = [order_number for order_number in expected if order_number not in extracted]
        if missing:
            return Result.fail(
                "Fis cikarildi verify eksik kaldi.",
                close_dialog=False,
                data={"verified": False, "order_numbers": expected, "missing_order_numbers": missing},
            )
        return Result.ok(
            "Fis cikarildi DB verify ile dogrulandi.",
            close_dialog=False,
            data={"verified": True, "order_numbers": expected, "verified_by": "order_header_is_extracted"},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_order_profit_excel_export(action: dict[str, Any], result: Result | None = None) -> Result:
    try:
        payload = _manual_payload_from_action(action)
        result_data = dict((result.data if result is not None and isinstance(result.data, dict) else {}) or {})
        output_path = _compact_text(payload.get("output_path") or result_data.get("output_path"))
        if not output_path:
            for row in _action_rows(action):
                file_info = dict(row.get("file") or {})
                output_path = _compact_text(row.get("output_path") or file_info.get("path"))
                if output_path:
                    break
        if not output_path:
            return Result.fail("Excel export verify icin output_path bulunamadi.", close_dialog=False)
        path = Path(output_path)
        if not path.exists() or not path.is_file():
            return Result.fail(
                "Excel export verify dosyayi bulamadi.",
                close_dialog=False,
                data={"verified": False, "output_path": str(path)},
            )
        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            return Result.fail(
                "Excel export verify dosya bos gorundu.",
                close_dialog=False,
                data={"verified": False, "output_path": str(path), "size_bytes": size_bytes},
            )
        return Result.ok(
            "Excel export dosya sistemi verify ile dogrulandi.",
            close_dialog=False,
            data={"verified": True, "output_path": str(path), "size_bytes": size_bytes, "verified_by": "filesystem"},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_report_snapshot_xlsx_export(
    action: dict[str, Any],
    result: Result | None = None,
) -> Result:
    try:
        from Core.processors.report_artifacts import verify_report_snapshot_xlsx

        payload = _manual_payload_from_action(action)
        result_data = dict(
            (result.data if result is not None and isinstance(result.data, dict) else {})
            or {}
        )
        report_snapshot = payload.get("report_snapshot")
        output_path = _compact_text(
            payload.get("output_path") or result_data.get("output_path")
        )
        if not isinstance(report_snapshot, dict):
            return Result.fail(
                "Excel report verify icin immutable snapshot bulunamadi.",
                close_dialog=False,
                data={"verified": False},
            )
        if not output_path:
            return Result.fail(
                "Excel report verify icin output_path bulunamadi.",
                close_dialog=False,
                data={"verified": False},
            )
        verification = verify_report_snapshot_xlsx(report_snapshot, output_path)
        if not bool(verification.get("verified")):
            return Result.fail(
                "Excel report snapshot read-back ile dogrulanamadi.",
                close_dialog=False,
                data=verification,
            )
        return Result.ok(
            "Excel report exact snapshot read-back ile dogrulandi.",
            close_dialog=False,
            data=verification,
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_return_approval(action: dict[str, Any]) -> Result:
    try:
        from Orders.processors import agentic_repository as orders_repo

        payload = _manual_payload_from_action(action)
        db_name = _compact_text(payload.get("db_name")) or DB_NAME
        claim_ids = [
            _compact_text(row.get("claim_id") or (row.get("before") or {}).get("claim_id"))
            for row in _action_rows(action)
            if _compact_text(row.get("claim_id") or (row.get("before") or {}).get("claim_id"))
        ]
        if not claim_ids:
            token = _compact_text(payload.get("order"))
            if token:
                claim_ids = [token]
        verified_rows: list[dict[str, Any]] = []
        for token in claim_ids:
            scoped_row = next(
                (
                    row
                    for row in _action_rows(action)
                    if _compact_text(row.get("claim_id") or (row.get("before") or {}).get("claim_id")) == token
                ),
                {},
            )
            before = dict(scoped_row.get("before") or {})
            api_account_id = scoped_row.get("api_account_id") or before.get("api_account_id") or payload.get("api_account_id")
            resolved = orders_repo.resolve_return_claim(
                token,
                api_account_id=(int(api_account_id) if api_account_id not in (None, "") else None),
                db_name=db_name,
            )
            if not resolved.success:
                return Result.fail(f"Iade verify kaydi bulunamadi: {token}", close_dialog=False)
            record = (resolved.data or {}).get("record")
            status = _compact_text(getattr(record, "claimItemStatus", ""))
            waiting_ids = [str(item or "").strip() for item in list(getattr(record, "waitingClaimLineItemIds", None) or []) if str(item or "").strip()]
            if status == "WaitingInAction" and waiting_ids:
                return Result.fail(
                    f"Iade verify tamamlanmadi: {token} hala WaitingInAction.",
                    close_dialog=False,
                    data={"claim_id": token, "status": status, "waiting_line_item_ids": waiting_ids},
                )
            verified_rows.append({"claim_id": _compact_text(getattr(record, "claimId", "")), "status": status, "waiting_line_item_ids": waiting_ids})
        return Result.ok("Iade onayi DB verify ile dogrulandi.", close_dialog=False, data={"verified": True, "rows": verified_rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_orders_sync_from_result(action: dict[str, Any], result: Result) -> Result:
    try:
        data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        save_data = dict(data.get("save") or {})
        returns_save_data = dict(data.get("returns_save") or {})
        reconciliation = dict(data.get("return_reconciliation") or {})
        last_used_update = dict(data.get("last_used_update") or {})
        observability = dict(data.get("sync_observability") or {})
        fetch_diagnostics = dict((data.get("fetch") or {}).get("sync_diagnostics") or {})
        if observability and fetch_diagnostics:
            from Orders.processors.trendyol.pipeline import (
                apply_order_sync_policy_to_observability,
            )

            observability = apply_order_sync_policy_to_observability(
                observability,
                fetch_diagnostics,
            )
        readback = dict(observability.get("db_readback") or data.get("db_readback") or {})
        watermark = dict(observability.get("watermark") or {})
        errors = dict(observability.get("errors") or {})
        readback_required = readback.get("required") is True
        source_contract_complete = (
            not readback_required
            or readback.get("source_identity_contract_complete") is not False
        )
        source_complete = watermark.get("source_rows_complete") is not False
        readback_ok = not readback_required or readback.get("verified") is True
        no_sync_errors = int(errors.get("count") or 0) == 0
        verified = bool(save_data or returns_save_data or reconciliation) and all(
            (source_contract_complete, source_complete, readback_ok, no_sync_errors)
        )
        payload = _manual_payload_from_action(action)
        warnings: list[str] = []
        if data.get("returns_fetch_error"):
            warnings.append(_compact_text(data.get("returns_fetch_error")))
        excluded = dict(observability.get("excluded") or {})
        policy_excluded_count = int(excluded.get("source_rows") or 0)
        if policy_excluded_count:
            warnings.append(
                f"{policy_excluded_count} Awaiting satiri kalici shipment package "
                "kimligi olusana kadar operational siparis snapshot'i disinda tutuldu."
            )
        if reconciliation:
            if bool(reconciliation.get("needs_remote_snapshot")):
                warnings.append("Return reconciliation icin fresh snapshot eksik.")
            else:
                stale_count = int(reconciliation.get("stale_count") or 0)
                if stale_count:
                    warnings.append(f"{stale_count} stale lokal iade bulundu.")
        if (
            list(last_used_update.get("requested_account_ids") or [])
            and last_used_update.get("verified") is not True
        ):
            warnings.append(
                "Hesap last_used_at guncellemesi read-back ile dogrulanamadi."
            )
        verify_data = {
            "verified": verified,
            "verified_by": "orders_sync_observability_and_db_readback",
            "accounts": list(observability.get("accounts") or []),
            "fetched": dict(observability.get("fetched") or {}),
            "writes": dict(observability.get("writes") or {}),
            "skipped": dict(observability.get("skipped") or {}),
            "excluded": excluded,
            "errors": errors,
            "watermark": watermark,
            "db_readback": readback,
            "save_counts": save_data.get("counts") or {},
            "return_save_counts": returns_save_data.get("counts") or {},
            "return_reconciliation": reconciliation,
            "last_used_update": last_used_update,
            "warnings": warnings,
            "db_name": _compact_text(payload.get("db_name")) or None,
        }
        if not verified:
            failure_reasons: list[str] = []
            if not source_contract_complete:
                failure_reasons.append("source identity contract eksik")
            if not source_complete:
                failure_reasons.append("source snapshot eksik")
            if not readback_ok:
                failure_reasons.append("exact DB read-back eksik")
            if not no_sync_errors:
                failure_reasons.append(f"{int(errors.get('count') or 0)} sync hatasi")
            verify_data["failure_reasons"] = failure_reasons
            return Result.fail(
                "Siparis/iade sync execute tamamlandi ancak authoritative verify kapanmadi: "
                + ", ".join(failure_reasons or ["kalici yazim kaniti eksik"]),
                close_dialog=False,
                data=verify_data,
            )
        return Result.ok(
            "Siparis/iade sync execute sonrasi verify tamamlandi.",
            close_dialog=False,
            data=verify_data,
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_return_claims_save(action: dict[str, Any], result: Result) -> Result:
    try:
        payload = _manual_payload_from_action(action)
        data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        claim_rows = [dict(row) for row in _as_list(payload.get("return_claim_list")) if isinstance(row, dict)]
        claim_ids = [
            _compact_text(row.get("claimId") or row.get("claim_id"))
            for row in claim_rows
            if _compact_text(row.get("claimId") or row.get("claim_id"))
        ]
        claim_ids = list(dict.fromkeys(claim_ids))
        if not claim_ids:
            counts = dict(data.get("counts") or {}) if isinstance(data.get("counts"), dict) else {}
            if int(counts.get("claims_inserted") or 0) == 0:
                return Result.ok(
                    "Iade kaydetme verify: kaydedilecek claim yok.",
                    close_dialog=False,
                    data={"verified": True, "claim_ids": [], "verified_by": "empty_payload"},
                )
            return Result.fail("Iade kaydetme verify icin claim id bulunamadi.", close_dialog=False)

        db_name = _compact_text(payload.get("db_name"))
        if db_name:
            from Orders.processors import agentic_repository as orders_repo

            domain_result = orders_repo.list_return_claims(claim_ids=claim_ids, active=True, db_name=db_name)
            if not domain_result.success:
                return domain_result
            rows = list((domain_result.data or {}).get("records") or [])
            active_ids = {
                _compact_text(getattr(row, "claimId", ""))
                for row in rows
                if _compact_text(getattr(row, "claimId", "")) and getattr(row, "sync_deleted_at", None) is None
            }
            if set(claim_ids).issubset(active_ids):
                return Result.ok(
                    "Iade kaydetme DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "claim_ids": claim_ids, "active_claim_ids": sorted(active_ids), "verified_by": "db"},
                )

        result_rows = [dict(row) for row in _as_list(data.get("rows")) if isinstance(row, dict)]
        result_ids = {
            _compact_text(row.get("claimId") or row.get("claim_id"))
            for row in result_rows
            if _compact_text(row.get("claimId") or row.get("claim_id"))
        }
        if set(claim_ids).issubset(result_ids):
            return Result.ok(
                "Iade kaydetme result payload verify ile dogrulandi.",
                close_dialog=False,
                data={"verified": True, "claim_ids": claim_ids, "result_claim_ids": sorted(result_ids), "verified_by": "result_payload"},
            )
        return Result.fail(
            "Iade kaydetme verify tamamlanmadi; claim DB/result icinde bulunamadi.",
            close_dialog=False,
            data={"verified": False, "claim_ids": claim_ids, "result_claim_ids": sorted(result_ids)},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_return_claims_stale_mark(action: dict[str, Any], result: Result) -> Result:
    try:
        payload = _manual_payload_from_action(action)
        data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        claim_ids = (
            [_compact_text(value) for value in _as_list(payload.get("claim_ids")) if _compact_text(value)]
            or [_compact_text(value) for value in _as_list(data.get("claim_ids")) if _compact_text(value)]
        )
        if not claim_ids:
            return Result.fail("Stale verify icin claim_ids bulunamadi.", close_dialog=False)
        db_name = _compact_text(payload.get("db_name"))

        from AI.processors.tools import returns_lookup

        still_active: list[str] = []
        for claim_id in claim_ids:
            kwargs: dict[str, Any] = {"query": claim_id, "limit": 10}
            if db_name:
                kwargs["db_name"] = db_name
            lookup = returns_lookup(**kwargs)
            if not lookup.success:
                return lookup
            for row in (lookup.data or {}).get("returns") or []:
                if _compact_text(row.get("claim_id")).casefold() == claim_id.casefold():
                    still_active.append(claim_id)
                    break
        if still_active:
            return Result.fail(
                "Stale isaretlenen iade aktif latest listede hala gorunuyor.",
                close_dialog=False,
                data={"verified": False, "claim_ids": claim_ids, "still_active_claim_ids": still_active},
            )
        return Result.ok(
            "Stale iade isaretleme DB verify ile dogrulandi.",
            close_dialog=False,
            data={
                "verified": True,
                "claim_ids": claim_ids,
                "matched": int(data.get("matched") or 0),
                "stale_marked": int(data.get("stale_marked") or 0),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_return_claims_stale_restore(action: dict[str, Any], result: Result) -> Result:
    try:
        payload = _manual_payload_from_action(action)
        data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        claim_ids = (
            [_compact_text(value) for value in _as_list(payload.get("claim_ids")) if _compact_text(value)]
            or [_compact_text(value) for value in _as_list(data.get("claim_ids")) if _compact_text(value)]
        )
        if not claim_ids:
            return Result.fail("Stale restore verify icin claim_ids bulunamadi.", close_dialog=False)
        db_name = _compact_text(payload.get("db_name"))

        from AI.processors.tools import returns_lookup

        active: list[str] = []
        missing: list[str] = []
        for claim_id in claim_ids:
            kwargs: dict[str, Any] = {"query": claim_id, "limit": 10}
            if db_name:
                kwargs["db_name"] = db_name
            lookup = returns_lookup(**kwargs)
            if not lookup.success:
                return lookup
            found = False
            for row in (lookup.data or {}).get("returns") or []:
                if _compact_text(row.get("claim_id")).casefold() == claim_id.casefold():
                    active.append(claim_id)
                    found = True
                    break
            if not found:
                missing.append(claim_id)
        if missing:
            return Result.fail(
                "Restore edilen iade active latest listede gorunmuyor.",
                close_dialog=False,
                data={"verified": False, "claim_ids": claim_ids, "missing_claim_ids": missing, "active_claim_ids": active},
            )
        return Result.ok(
            "Stale iade restore DB verify ile dogrulandi.",
            close_dialog=False,
            data={
                "verified": True,
                "claim_ids": claim_ids,
                "active_claim_ids": active,
                "matched": int(data.get("matched") or 0),
                "restored": int(data.get("restored") or 0),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _account_pks_from_payload(payload: dict[str, Any]) -> list[int]:
    pks: list[int] = []
    for raw in _as_list(payload.get("accounts") or payload.get("comp_api_account_list")):
        pk_value = None
        if isinstance(raw, dict):
            pk_value = raw.get("pk") or raw.get("id") or raw.get("account_pk")
        elif isinstance(raw, (list, tuple)) and raw:
            pk_value = raw[0]
        try:
            pk = int(pk_value)
        except Exception:
            continue
        if pk > 0:
            pks.append(pk)
    for raw in _as_list(
        payload.get("api_account_ids")
        or payload.get("selected_company_pks")
        or payload.get("company_pks")
        or payload.get("company_ids")
    ):
        try:
            pk = int(raw)
        except Exception:
            continue
        if pk > 0:
            pks.append(pk)
    return list(dict.fromkeys(pks))


def verify_accounts_last_used_update(action: dict[str, Any], result: Result) -> Result:
    try:
        payload = _manual_payload_from_action(action)
        data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        account_pks = _account_pks_from_payload(payload)
        if not account_pks:
            return Result.fail("Last-used verify icin account pk bulunamadi.", close_dialog=False)
        db_name = _compact_text(payload.get("db_name"))
        updated_pks: list[int] = []
        missing_pks: list[int] = []
        if db_name:
            from Account.processors.pipeline import get_company_by_id

            account_result = get_company_by_id(account_pks, db_name=db_name)
            records = list((account_result.data or {}).get("records") or []) if account_result.success else []
            by_pk = {int(getattr(account, "pk", 0) or 0): account for account in records}
            for pk in account_pks:
                account = by_pk.get(pk)
                if account is None:
                    missing_pks.append(pk)
                elif getattr(account, "last_used_at", None) is not None:
                    updated_pks.append(pk)
        if updated_pks and set(updated_pks) == set(account_pks):
            return Result.ok(
                "Hesap last_used_at DB verify ile dogrulandi.",
                close_dialog=False,
                data={"verified": True, "account_pks": account_pks, "updated_pks": updated_pks, "verified_by": "db"},
            )
        if int(data.get("account_count") or 0) == len(account_pks):
            return Result.ok(
                "Hesap last_used_at result payload verify ile dogrulandi.",
                close_dialog=False,
                data={
                    "verified": True,
                    "account_pks": account_pks,
                    "updated_pks": updated_pks,
                    "missing_pks": missing_pks,
                    "verified_by": "result_payload",
                },
            )
        return Result.fail(
            "Hesap last_used_at verify tamamlanmadi.",
            close_dialog=False,
            data={"verified": False, "account_pks": account_pks, "updated_pks": updated_pks, "missing_pks": missing_pks},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_marketplace_manual_action(capability: ManualCapability, action: dict[str, Any], result: Result) -> Result:
    try:
        if not result.success:
            return Result.fail("Execute basarisiz; marketplace verify atlandi.", close_dialog=False)
        payload = _manual_payload_from_action(action)
        db_name = _compact_text(payload.get("db_name"))
        capability_id = capability.capability_id
        from Marketplaces.processors import agentic_repository as marketplace_repo
        from Marketplaces.constants.catalog_constants import canonical_platform_code

        def _row_for(code: Any):
            normalized = canonical_platform_code(code)
            if not normalized:
                return None, normalized
            domain_result = marketplace_repo.list_marketplaces(db_name=db_name or DB_NAME)
            rows = list((domain_result.data or {}).get("records") or []) if domain_result.success else []
            row = next((item for item in rows if canonical_platform_code(getattr(item, "code", "")) == normalized), None)
            if row is None:
                return None, normalized
            return {
                "pk": int(getattr(row, "pk", 0) or 0),
                "code": _compact_text(getattr(row, "code", "")),
                "label": _compact_text(getattr(row, "label", "")),
                "description": _compact_text(getattr(row, "description", "")),
                "is_active": bool(getattr(row, "isActive", True)),
                "source_type": _compact_text(getattr(row, "sourceType", "")),
                "source_id": getattr(row, "sourceId", None),
            }, normalized

        if capability_id == "marketplaces.accept_marketplace_record":
            row, normalized = _row_for(payload.get("code"))
            if row and row.get("source_type") == "builtin":
                return Result.ok(
                    "Marketplace accept DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "code": normalized, "row": row},
                )
        elif capability_id == "marketplaces.save_marketplace":
            payload_row = dict(payload.get("payload") or {}) if isinstance(payload.get("payload"), dict) else {}
            row, normalized = _row_for(payload_row.get("code"))
            expected_label = _compact_text(payload_row.get("label"))
            expected_description = _compact_text(payload_row.get("description"))
            expected_active = bool(payload_row.get("isActive", row.get("is_active") if row else True))
            if row and (not expected_label or row.get("label") == expected_label) and (
                not expected_description or row.get("description") == expected_description
            ) and row.get("is_active") == expected_active:
                return Result.ok(
                    "Marketplace save DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "code": normalized, "row": row},
                )
        elif capability_id == "marketplaces.set_marketplaces_active_state":
            expected_active = bool(payload.get("is_active"))
            codes = [canonical_platform_code(code) for code in list(payload.get("codes") or []) if canonical_platform_code(code)]
            rows: list[dict[str, Any]] = []
            missing: list[str] = []
            mismatched: list[str] = []
            for code in codes:
                row, normalized = _row_for(code)
                if not row:
                    missing.append(normalized)
                    continue
                rows.append(row)
                if bool(row.get("is_active")) != expected_active:
                    mismatched.append(normalized)
            if codes and not missing and not mismatched:
                return Result.ok(
                    "Marketplace active state DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "codes": codes, "is_active": expected_active, "rows": rows},
                )
            return Result.fail(
                "Marketplace active state verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "codes": codes, "missing": missing, "mismatched": mismatched},
            )
        elif capability_id == "marketplaces.delete_marketplace":
            row, normalized = _row_for(payload.get("code"))
            if row is None and normalized:
                return Result.ok(
                    "Marketplace delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "code": normalized},
                )
        return Result.fail(
            "Marketplace DB verify tamamlanmadi.",
            close_dialog=False,
            data={"verified": False, "capability": capability.to_dict(), "payload": payload},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_logistics_manual_action(capability: ManualCapability, action: dict[str, Any], result: Result) -> Result:
    try:
        if not result.success:
            return Result.fail("Execute basarisiz; logistics verify atlandi.", close_dialog=False)
        payload = _manual_payload_from_action(action)
        db_name = _compact_text(payload.get("db_name"))
        capability_id = capability.capability_id
        from Logistics.processors import agentic_repository as logistics_repo
        from Marketplaces.constants.catalog_constants import canonical_platform_code

        def _provider_payload() -> dict[str, Any]:
            return dict(payload.get("provider_payload") or {}) if isinstance(payload.get("provider_payload"), dict) else {}

        def _tariff_payload() -> dict[str, Any]:
            return dict(payload.get("tariff_payload") or {}) if isinstance(payload.get("tariff_payload"), dict) else {}

        def _row_for(provider_payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str, int]:
            provider_pk = 0
            try:
                provider_pk = int(provider_payload.get("pk") or provider_payload.get("dbPk") or 0)
            except Exception:
                provider_pk = 0
            platform = canonical_platform_code(provider_payload.get("platformCode")) or _compact_text(provider_payload.get("platformCode")).upper()
            code = _compact_text(provider_payload.get("cargoProviderCode")).upper()
            domain_result = logistics_repo.list_providers(db_name=db_name or DB_NAME)
            rows = list((domain_result.data or {}).get("records") or []) if domain_result.success else []
            row = next((item for item in rows if provider_pk > 0 and int(getattr(item, "pk", 0) or 0) == provider_pk), None)
            if row is None and platform and code:
                row = next(
                    (
                        item for item in rows
                        if canonical_platform_code(getattr(item, "platformCode", "")) == platform
                        and _compact_text(getattr(item, "cargoProviderCode", "")).upper() == code
                    ),
                    None,
                )
            if row is None:
                return None, platform, code, provider_pk
            return {
                "pk": int(getattr(row, "pk", 0) or 0),
                "platform_code": _compact_text(getattr(row, "platformCode", "")),
                "cargo_provider_code": _compact_text(getattr(row, "cargoProviderCode", "")),
                "cargo_provider_name": _compact_text(getattr(row, "cargoProviderName", "")),
                "source_type": _compact_text(getattr(row, "sourceType", "")),
                "source_id": getattr(row, "sourceId", None),
            }, platform, code, provider_pk

        def _tariff_rows(*, search_text: str = "", source_state: str = "") -> list[dict[str, Any]]:
            from Logistics.views.actions import load_logistics_cargo_tariffs

            kwargs: dict[str, Any] = {
                "search_text": search_text,
                "source_state": source_state,
            }
            if db_name:
                kwargs["db_name"] = db_name
            for optional_key in ("storage_path", "default_storage_path"):
                if payload.get(optional_key):
                    kwargs[optional_key] = payload.get(optional_key)
            result = load_logistics_cargo_tariffs(**kwargs)
            return [dict(row) for row in list((result.data or {}).get("records") or []) if isinstance(row, dict)] if result.success else []

        def _tariff_runtime_pk(row: dict[str, Any]) -> int:
            try:
                return int(row.get("pk") or row.get("dbPk") or row.get("sourceId") or row.get("source_id") or 0)
            except Exception:
                return 0

        def _tariff_row_for(tariff_payload: dict[str, Any], item_pk: int = 0, *, source_state: str = "") -> tuple[dict[str, Any] | None, int, str, str]:
            tariff_key = _compact_text(tariff_payload.get("tariffKey"))
            name = _compact_text(tariff_payload.get("name"))
            search = name or tariff_key
            rows = _tariff_rows(search_text=search, source_state=source_state)
            if not rows and search:
                rows = _tariff_rows(source_state=source_state)
            for row in rows:
                runtime_pk = _tariff_runtime_pk(row)
                if item_pk > 0 and runtime_pk == item_pk:
                    return row, runtime_pk, _compact_text(row.get("tariffKey")), _compact_text(row.get("name"))
                if tariff_key and _compact_text(row.get("tariffKey")) == tariff_key:
                    return row, runtime_pk, tariff_key, _compact_text(row.get("name"))
                if name and _compact_text(row.get("name")) == name:
                    return row, runtime_pk, _compact_text(row.get("tariffKey")), name
            return None, item_pk, tariff_key, name

        if capability_id == "logistics.accept_logistics_cargo_provider_record":
            provider_payload = _provider_payload()
            row, platform, code, _provider_pk = _row_for(provider_payload)
            if row and row.get("source_type") == "builtin":
                return Result.ok(
                    "Logistics cargo provider accept DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "platform_code": platform, "cargo_provider_code": code, "row": row},
                )
        elif capability_id == "logistics.save_logistics_cargo_provider_record":
            provider_payload = _provider_payload()
            row, platform, code, _provider_pk = _row_for(provider_payload)
            expected_name = _compact_text(provider_payload.get("cargoProviderName"))
            if row and (not expected_name or row.get("cargo_provider_name") == expected_name):
                return Result.ok(
                    "Logistics cargo provider save DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "platform_code": platform, "cargo_provider_code": code, "row": row},
                )
        elif capability_id == "logistics.delete_logistics_cargo_provider_record":
            provider_payload = _provider_payload()
            row, platform, code, provider_pk = _row_for(provider_payload)
            if row is None and (provider_pk > 0 or (platform and code)):
                return Result.ok(
                    "Logistics cargo provider delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "platform_code": platform, "cargo_provider_code": code, "provider_pk": provider_pk},
                )
        elif capability_id == "logistics.save_logistics_cargo_tariff":
            tariff_payload = _tariff_payload()
            row, runtime_pk, tariff_key, name = _tariff_row_for(tariff_payload, source_state="saved")
            expected_amount = tariff_payload.get("amount")
            amount_ok = True
            if expected_amount is not None and row is not None:
                try:
                    amount_ok = float(row.get("amount") or 0) == float(expected_amount)
                except Exception:
                    amount_ok = False
            if row and amount_ok:
                return Result.ok(
                    "Logistics cargo tariff save DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "tariff_pk": runtime_pk, "tariff_key": tariff_key, "name": name, "row": row},
                )
        elif capability_id == "logistics.accept_logistics_cargo_tariff":
            try:
                item_pk = int(payload.get("item_pk") or 0)
            except Exception:
                item_pk = 0
            row, runtime_pk, tariff_key, name = _tariff_row_for({}, item_pk, source_state="saved")
            if row and bool(row.get("isBuiltinAccepted")):
                return Result.ok(
                    "Logistics cargo tariff accept DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "tariff_pk": runtime_pk, "tariff_key": tariff_key, "name": name, "row": row},
                )
        elif capability_id == "logistics.accept_logistics_cargo_tariffs":
            item_pks = []
            for raw_pk in list(payload.get("item_pks") or []):
                try:
                    pk = int(raw_pk or 0)
                except Exception:
                    pk = 0
                if pk > 0 and pk not in item_pks:
                    item_pks.append(pk)
            rows: list[dict[str, Any]] = []
            missing: list[int] = []
            not_accepted: list[int] = []
            for item_pk in item_pks:
                row, runtime_pk, _tariff_key, _name = _tariff_row_for({}, item_pk, source_state="saved")
                if row is None:
                    missing.append(item_pk)
                    continue
                rows.append(row)
                if not bool(row.get("isBuiltinAccepted")):
                    not_accepted.append(runtime_pk or item_pk)
            if item_pks and not missing and not not_accepted:
                return Result.ok(
                    "Logistics bulk cargo tariff accept DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "tariff_pks": item_pks, "rows": rows},
                )
        elif capability_id == "logistics.delete_logistics_cargo_tariff":
            try:
                item_pk = int(payload.get("item_pk") or 0)
            except Exception:
                item_pk = 0
            row, runtime_pk, tariff_key, name = _tariff_row_for({}, item_pk)
            if row is None and item_pk > 0:
                return Result.ok(
                    "Logistics cargo tariff delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "tariff_pk": item_pk, "tariff_key": tariff_key, "name": name},
                )
        elif capability_id == "logistics.delete_logistics_cargo_tariffs":
            item_pks = []
            for raw_pk in list(payload.get("item_pks") or []):
                try:
                    pk = int(raw_pk or 0)
                except Exception:
                    pk = 0
                if pk > 0 and pk not in item_pks:
                    item_pks.append(pk)
            remaining: list[int] = []
            for item_pk in item_pks:
                row, _runtime_pk, _tariff_key, _name = _tariff_row_for({}, item_pk)
                if row is not None:
                    remaining.append(item_pk)
            if item_pks and not remaining:
                return Result.ok(
                    "Logistics bulk cargo tariff delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "tariff_pks": item_pks},
                )
        return Result.fail(
            "Logistics DB verify tamamlanmadi.",
            close_dialog=False,
            data={"verified": False, "capability": capability.to_dict(), "payload": payload},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_finance_manual_action(capability: ManualCapability, action: dict[str, Any], result: Result) -> Result:
    try:
        if not result.success:
            return Result.fail("Execute basarisiz; finance verify atlandi.", close_dialog=False)
        payload = _manual_payload_from_action(action)
        db_name = _compact_text(payload.get("db_name"))
        capability_id = capability.capability_id

        from Finance.processors import agentic_repository as finance_repo
        from Logistics.processors import agentic_repository as logistics_repo

        def _finance_rows(kind: str) -> list[Any]:
            query = finance_repo.list_records(kind, db_name=db_name or DB_NAME)
            return list((query.data or {}).get("records") or []) if query.success else []

        def _tariff_records() -> list[Any]:
            query = logistics_repo.list_tariffs(db_name=db_name or DB_NAME)
            return list((query.data or {}).get("records") or []) if query.success else []

        if capability_id in {
            "finance.action_sync_finance_for_accounts",
            "finance.action_sync_finance_for_company_pks",
            "finance.action_sync_finance_for_selected_companies",
        }:
            data = dict(result.data or {}) if isinstance(result.data, dict) else {}
            db_counts = dict(data.get("db_counts") or {}) if isinstance(data.get("db_counts"), dict) else {}
            counts = dict(data.get("counts") or {}) if isinstance(data.get("counts"), dict) else {}
            errors = list(data.get("errors") or []) if isinstance(data.get("errors"), list) else []
            if db_counts or counts or "changed" in data:
                return Result.ok(
                    "Finance sync result verify ile dogrulandi.",
                    close_dialog=False,
                    data={
                        "verified": True,
                        "verified_by": "result_db_counts",
                        "db_counts": db_counts,
                        "counts": counts,
                        "changed": bool(data.get("changed")),
                        "errors": errors,
                        "job_count": data.get("job_count"),
                        "successful_job_count": data.get("successful_job_count"),
                    },
                )
            return Result.fail(
                "Finance sync verify icin db_counts/counts bilgisi bulunamadi.",
                close_dialog=False,
                data={"verified": False, "result_data": data},
            )

        def _row_by_pk(item_pk: int) -> dict[str, Any] | None:
            if item_pk <= 0:
                return None
            row = next((item for item in _finance_rows("cost_item") if int(getattr(item, "pk", 0) or 0) == item_pk), None)
            if row is None:
                return None
            return {
                    "pk": int(getattr(row, "pk", 0) or 0),
                    "cost_key": _compact_text(getattr(row, "costKey", "")),
                    "name": _compact_text(getattr(row, "name", "")),
                    "default_amount": getattr(row, "defaultAmount", None),
                    "currency": _compact_text(getattr(row, "currency", "")),
                    "is_active": bool(getattr(row, "isActive", True)),
                    "is_deleted": bool(getattr(row, "isDeleted", False)),
            }

        def _row_by_payload(cost_payload: dict[str, Any], result_record: dict[str, Any]) -> dict[str, Any] | None:
            item_pk = 0
            try:
                item_pk = int(result_record.get("pk") or result_record.get("dbPk") or 0)
            except Exception:
                item_pk = 0
            if item_pk > 0:
                return _row_by_pk(item_pk)
            expected_name = _compact_text(cost_payload.get("name"))
            expected_key = _compact_text(result_record.get("costKey") or cost_payload.get("costKey"))
            if not expected_key and not expected_name:
                return None
            row = next(
                (
                    item for item in _finance_rows("cost_item")
                    if (expected_key and _compact_text(getattr(item, "costKey", "")) == expected_key)
                    or (not expected_key and _compact_text(getattr(item, "name", "")) == expected_name)
                ),
                None,
            )
            if row is None:
                return None
            return {
                    "pk": int(getattr(row, "pk", 0) or 0),
                    "cost_key": _compact_text(getattr(row, "costKey", "")),
                    "name": _compact_text(getattr(row, "name", "")),
                    "default_amount": getattr(row, "defaultAmount", None),
                    "currency": _compact_text(getattr(row, "currency", "")),
                    "is_active": bool(getattr(row, "isActive", True)),
                    "is_deleted": bool(getattr(row, "isDeleted", False)),
            }

        if capability_id in {"finance.save_finance_cost_item", "finance.accept_finance_cost_item"}:
            cost_payload = dict(payload.get("cost_payload") or {}) if isinstance(payload.get("cost_payload"), dict) else {}
            result_record = dict((result.data or {}).get("record") or {}) if isinstance(result.data, dict) else {}
            row = _row_by_payload(cost_payload, result_record)
            expected_name = _compact_text(cost_payload.get("name"))
            expected_amount = cost_payload.get("defaultAmount")
            if row and not row.get("is_deleted") and (not expected_name or row.get("name") == expected_name):
                amount_ok = True
                if expected_amount not in (None, ""):
                    try:
                        amount_ok = float(row.get("default_amount") or 0) == float(expected_amount)
                    except Exception:
                        amount_ok = False
                if amount_ok:
                    return Result.ok(
                        "Finance maliyet kalemi save/accept DB verify ile dogrulandi.",
                        close_dialog=False,
                        data={"verified": True, "verified_by": "db", "row": row},
                    )
            return Result.fail(
                "Finance maliyet kalemi save/accept verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "payload": cost_payload, "result_record": result_record, "row": row},
            )

        if capability_id == "finance.delete_finance_cost_item":
            try:
                item_pk = int(payload.get("item_pk") or 0)
            except Exception:
                item_pk = 0
            row = _row_by_pk(item_pk)
            if item_pk > 0 and (row is None or bool(row.get("is_deleted"))):
                return Result.ok(
                    "Finance maliyet kalemi delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "item_pk": item_pk, "row": row},
                )
            return Result.fail(
                "Finance maliyet kalemi delete verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "item_pk": item_pk, "row": row},
            )

        if capability_id == "finance.delete_finance_cost_items":
            item_pks: list[int] = []
            for raw_pk in _as_list(payload.get("item_pks")):
                try:
                    item_pk = int(raw_pk or 0)
                except Exception:
                    item_pk = 0
                if item_pk > 0 and item_pk not in item_pks:
                    item_pks.append(item_pk)
            rows = [_row_by_pk(item_pk) for item_pk in item_pks]
            if item_pks and all(row is None or bool(row.get("is_deleted")) for row in rows):
                return Result.ok(
                    "Finance maliyet kalemi bulk delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "item_pks": item_pks, "rows": rows},
                )
            return Result.fail(
                "Finance maliyet kalemi bulk delete verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "item_pks": item_pks, "rows": rows},
            )

        def _manual_tx_row(tx_pk: int) -> dict[str, Any] | None:
            if tx_pk <= 0:
                return None
            tx = next((item for item in _finance_rows("manual_transaction") if int(getattr(item, "pk", 0) or 0) == tx_pk), None)
            if tx is None:
                return None
            return {
                    "pk": int(getattr(tx, "pk", 0) or 0),
                    "direction": _compact_text(getattr(tx, "direction", "")),
                    "category_name": _compact_text(getattr(tx, "categoryName", "")),
                    "description": _compact_text(getattr(tx, "description", "")),
                    "amount": getattr(tx, "amount", None),
                    "currency": _compact_text(getattr(tx, "currency", "")),
                    "is_deleted": bool(getattr(tx, "isDeleted", False)),
            }

        if capability_id == "finance.save_manual_finance_transaction":
            tx_payload = dict(payload.get("payload") or {}) if isinstance(payload.get("payload"), dict) else {}
            result_record = dict((result.data or {}).get("record") or {}) if isinstance(result.data, dict) else {}
            try:
                tx_pk = int(result_record.get("pk") or 0)
            except Exception:
                tx_pk = 0
            row = _manual_tx_row(tx_pk)
            expected_amount = tx_payload.get("amount")
            expected_direction = _compact_text(tx_payload.get("direction"))
            if row and not row.get("is_deleted"):
                amount_ok = True
                if expected_amount not in (None, ""):
                    try:
                        amount_ok = float(row.get("amount") or 0) == float(expected_amount)
                    except Exception:
                        amount_ok = False
                direction_ok = not expected_direction or row.get("direction") == expected_direction
                if amount_ok and direction_ok:
                    return Result.ok(
                        "Finance manuel hareket save DB verify ile dogrulandi.",
                        close_dialog=False,
                        data={"verified": True, "verified_by": "db", "row": row},
                    )
            return Result.fail(
                "Finance manuel hareket save verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "payload": tx_payload, "result_record": result_record, "row": row},
            )

        if capability_id == "finance.delete_manual_finance_transaction":
            try:
                tx_pk = int(payload.get("tx_pk") or 0)
            except Exception:
                tx_pk = 0
            row = _manual_tx_row(tx_pk)
            if tx_pk > 0 and row and bool(row.get("is_deleted")):
                return Result.ok(
                    "Finance manuel hareket delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "tx_pk": tx_pk, "row": row},
                )
            return Result.fail(
                "Finance manuel hareket delete verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "tx_pk": tx_pk, "row": row},
            )

        def _invoice_row(invoice_pk: int) -> dict[str, Any] | None:
            if invoice_pk <= 0:
                return None
            invoice = next((item for item in _finance_rows("invoice_document") if int(getattr(item, "pk", 0) or 0) == invoice_pk), None)
            if invoice is None:
                return None
            return {
                    "pk": int(getattr(invoice, "pk", 0) or 0),
                    "invoice_number": _compact_text(getattr(invoice, "invoiceNumber", "")),
                    "invoice_type": _compact_text(getattr(invoice, "invoiceType", "")),
                    "total_amount": getattr(invoice, "totalAmount", None),
                    "currency": _compact_text(getattr(invoice, "currency", "")),
                    "file_path": _compact_text(getattr(invoice, "filePath", "")),
                    "is_deleted": bool(getattr(invoice, "isDeleted", False)),
            }

        if capability_id == "finance.save_finance_invoice_document":
            invoice_payload = dict(payload.get("payload") or {}) if isinstance(payload.get("payload"), dict) else {}
            result_record = dict((result.data or {}).get("record") or {}) if isinstance(result.data, dict) else {}
            try:
                invoice_pk = int(result_record.get("pk") or 0)
            except Exception:
                invoice_pk = 0
            row = _invoice_row(invoice_pk)
            expected_number = _compact_text(invoice_payload.get("invoiceNumber") or invoice_payload.get("invoiceSerialNumber"))
            expected_amount = invoice_payload.get("totalAmount", invoice_payload.get("amount"))
            expected_file = _compact_text(invoice_payload.get("filePath") or invoice_payload.get("path"))
            if row and not row.get("is_deleted") and (not expected_number or row.get("invoice_number") == expected_number):
                amount_ok = True
                if expected_amount not in (None, ""):
                    try:
                        amount_ok = float(row.get("total_amount") or 0) == float(expected_amount)
                    except Exception:
                        amount_ok = False
                file_ok = not expected_file or Path(row.get("file_path") or "").resolve() == Path(expected_file).resolve()
                if amount_ok and file_ok:
                    return Result.ok(
                        "Finance fatura dokumani save DB verify ile dogrulandi.",
                        close_dialog=False,
                        data={"verified": True, "verified_by": "db", "row": row},
                    )
            return Result.fail(
                "Finance fatura dokumani save verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "payload": invoice_payload, "result_record": result_record, "row": row},
            )

        if capability_id == "finance.delete_finance_invoice_document":
            try:
                invoice_pk = int(payload.get("invoice_pk") or 0)
            except Exception:
                invoice_pk = 0
            row = _invoice_row(invoice_pk)
            if invoice_pk > 0 and row and bool(row.get("is_deleted")):
                return Result.ok(
                    "Finance fatura dokumani delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "invoice_pk": invoice_pk, "row": row},
                )
            return Result.fail(
                "Finance fatura dokumani delete verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "invoice_pk": invoice_pk, "row": row},
            )

        def _catalog_dict(row: Any) -> dict[str, Any]:
            return {
                key: getattr(row, key, None)
                for key in (
                    "pk",
                    "name",
                    "code",
                    "registration_no",
                    "country",
                    "website",
                    "contact_email",
                    "contact_phone",
                    "tax_no",
                    "phone",
                    "email",
                    "address",
                    "note",
                    "is_active",
                )
                if hasattr(row, key)
            }

        def _catalog_row(kind: str, *, pk: int = 0, name: str = "") -> dict[str, Any] | None:
            rows = _finance_rows(kind)
            if pk > 0:
                row = next((item for item in rows if int(getattr(item, "pk", 0) or 0) == pk), None)
                return _catalog_dict(row) if row is not None else None
            if name:
                row = next((item for item in rows if _compact_text(getattr(item, "name", "")) == name), None)
                return _catalog_dict(row) if row is not None else None
            return None

        def _catalog_expected_ok(row: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
            if not row:
                return False
            for key, expected_value in dict(expected or {}).items():
                if key == "db_name" or expected_value in (None, ""):
                    continue
                if key == "update_data":
                    if not _catalog_expected_ok(row, expected_value if isinstance(expected_value, dict) else {}):
                        return False
                    continue
                row_value = row.get(key)
                if isinstance(expected_value, bool):
                    if bool(row_value) != expected_value:
                        return False
                elif _compact_text(row_value) != _compact_text(expected_value):
                    return False
            return True

        if capability_id in {"finance.action_create_brand", "finance.action_create_company"}:
            kind = "brand" if capability_id.endswith("brand") else "company"
            expected = {key: value for key, value in payload.items() if key != "db_name"}
            row = _catalog_row(kind, name=_compact_text(payload.get("name")))
            if _catalog_expected_ok(row, expected):
                return Result.ok(
                    "Finance marka/sirket create DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "row": row},
                )
            return Result.fail(
                "Finance marka/sirket create verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "payload": payload, "row": row},
            )

        if capability_id in {"finance.action_update_brand", "finance.action_update_company"}:
            kind = "brand" if capability_id.endswith("brand") else "company"
            try:
                pk = int(payload.get("pk") or 0)
            except Exception:
                pk = 0
            expected = dict(payload.get("update_data") or {}) if isinstance(payload.get("update_data"), dict) else {}
            row = _catalog_row(kind, pk=pk)
            if pk > 0 and _catalog_expected_ok(row, expected):
                return Result.ok(
                    "Finance marka/sirket update DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "row": row},
                )
            return Result.fail(
                "Finance marka/sirket update verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "pk": pk, "expected": expected, "row": row},
            )

        if capability_id in {"finance.action_delete_brand", "finance.action_delete_company"}:
            kind = "brand" if capability_id.endswith("brand") else "company"
            try:
                pk = int(payload.get("pk") or 0)
            except Exception:
                pk = 0
            row = _catalog_row(kind, pk=pk)
            if pk > 0 and row is None:
                return Result.ok(
                    "Finance marka/sirket delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "pk": pk, "row": row},
                )
            return Result.fail(
                "Finance marka/sirket delete verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "pk": pk, "row": row},
            )

        def _tariff_dict(row: Any) -> dict[str, Any]:
            return {
                "pk": int(getattr(row, "pk", 0) or 0),
                "tariff_key": _compact_text(getattr(row, "tariffKey", "")),
                "name": _compact_text(getattr(row, "name", "")),
                "platform": _compact_text(getattr(row, "platform", "")),
                "cargo_provider_code": _compact_text(getattr(row, "cargoProviderCode", "")),
                "amount": getattr(row, "amount", None),
                "currency": _compact_text(getattr(row, "currency", "")),
                "is_active": bool(getattr(row, "isActive", True)),
                "is_deleted": bool(getattr(row, "isDeleted", False)),
            }

        def _tariff_row_for(tariff_payload: dict[str, Any], item_pk: int = 0) -> dict[str, Any] | None:
            rows = _tariff_records()
            if item_pk > 0:
                row = next((item for item in rows if int(getattr(item, "pk", 0) or 0) == item_pk), None)
                if row is not None:
                    return _tariff_dict(row)
            expected_key = _compact_text(tariff_payload.get("tariffKey"))
            expected_name = _compact_text(tariff_payload.get("name"))
            row = next(
                (
                    item for item in rows
                    if (expected_key and _compact_text(getattr(item, "tariffKey", "")) == expected_key)
                    or (not expected_key and expected_name and _compact_text(getattr(item, "name", "")) == expected_name)
                ),
                None,
            )
            return _tariff_dict(row) if row is not None else None

        if capability_id in {"finance.save_finance_cargo_tariff", "finance.accept_finance_cargo_tariff"}:
            tariff_payload = dict(payload.get("tariff_payload") or {}) if isinstance(payload.get("tariff_payload"), dict) else {}
            result_record = dict((result.data or {}).get("record") or {}) if isinstance(result.data, dict) else {}
            try:
                item_pk = int(result_record.get("dbPk") or result_record.get("pk") or payload.get("item_pk") or 0)
            except Exception:
                item_pk = 0
            row = _tariff_row_for({**tariff_payload, **result_record}, item_pk)
            expected_amount = tariff_payload.get("amount")
            if row and not row.get("is_deleted"):
                amount_ok = True
                if expected_amount not in (None, ""):
                    try:
                        amount_ok = float(row.get("amount") or 0) == float(expected_amount)
                    except Exception:
                        amount_ok = False
                if amount_ok:
                    return Result.ok(
                        "Finance kargo tarifesi save/accept DB verify ile dogrulandi.",
                        close_dialog=False,
                        data={"verified": True, "verified_by": "db", "row": row},
                    )
            return Result.fail(
                "Finance kargo tarifesi save/accept verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "payload": tariff_payload, "result_record": result_record, "row": row},
            )

        if capability_id == "finance.accept_finance_cargo_tariffs":
            item_pks: list[int] = []
            for raw_pk in _as_list(payload.get("item_pks")):
                try:
                    pk = int(raw_pk or 0)
                except Exception:
                    pk = 0
                if pk > 0 and pk not in item_pks:
                    item_pks.append(pk)
            rows = [_tariff_row_for({}, item_pk) for item_pk in item_pks]
            if item_pks and all(row and not row.get("is_deleted") and bool(row.get("is_active")) for row in rows):
                return Result.ok(
                    "Finance kargo tarifesi bulk accept DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "item_pks": item_pks, "rows": rows},
                )
            return Result.fail(
                "Finance kargo tarifesi bulk accept verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "item_pks": item_pks, "rows": rows},
            )

        if capability_id in {"finance.delete_finance_cargo_tariff", "finance.delete_finance_cargo_tariffs"}:
            raw_pks = payload.get("item_pks") if capability_id.endswith("tariffs") else [payload.get("item_pk")]
            item_pks: list[int] = []
            for raw_pk in _as_list(raw_pks):
                try:
                    pk = int(raw_pk or 0)
                except Exception:
                    pk = 0
                if pk > 0 and pk not in item_pks:
                    item_pks.append(pk)
            rows = [_tariff_row_for({}, item_pk) for item_pk in item_pks]
            if item_pks and all(row and bool(row.get("is_deleted")) for row in rows):
                return Result.ok(
                    "Finance kargo tarifesi delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "item_pks": item_pks, "rows": rows},
                )
            return Result.fail(
                "Finance kargo tarifesi delete verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "item_pks": item_pks, "rows": rows},
            )

        return Result.ok(
            "Finance manuel action Result.success ile dogrulandi.",
            close_dialog=False,
            data={"verified": True, "verified_by": "manual_action_result_success", "capability": capability.to_dict()},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_stock_manual_action(capability: ManualCapability, action: dict[str, Any], result: Result) -> Result:
    try:
        from Finance.processors import agentic_repository as finance_repo
        from Stock.constants.domain_constants import StockTxDirection
        from Stock.processors import agentic_repository as stock_repo
        from Stock.processors import pipeline as stock_domain_pipeline

        payload = _manual_payload_from_action(action)
        db_name = _compact_text(payload.get("db_name"))
        capability_id = capability.capability_id

        def _repo_rows(result: Result) -> list[Any]:
            return list((result.data or {}).get("records") or []) if result.success else []

        def _stock_items() -> list[Any]:
            return _repo_rows(stock_repo.list_items(db_name=db_name or DB_NAME))

        def _stock_txs() -> list[Any]:
            return _repo_rows(stock_repo.list_transactions(db_name=db_name or DB_NAME))

        def _warehouses() -> list[Any]:
            return _repo_rows(stock_repo.list_warehouses(db_name=db_name or DB_NAME))

        def _tx_dict(tx: Any | None) -> dict[str, Any] | None:
            if tx is None:
                return None
            direction = getattr(tx, "direction", "")
            direction_value = _compact_text(getattr(direction, "value", direction)).casefold()
            return {
                "pk": int(getattr(tx, "pk", 0) or 0),
                "item_id": int(getattr(tx, "item_id", 0) or 0),
                "warehouse_id": int(getattr(tx, "warehouse_id", 0) or 0),
                "direction": "in" if direction_value in {"in", "in_"} else "out" if direction_value == "out" else direction_value,
                "reason": _compact_text(getattr(getattr(tx, "reason", ""), "value", getattr(tx, "reason", ""))),
                "qty": float(getattr(tx, "qty", 0) or 0),
                "unit_cost": getattr(tx, "unit_cost", None),
                "currency": _compact_text(getattr(tx, "currency", "")),
                "note": _compact_text(getattr(tx, "note", "")),
            }

        def _tx_by_pk(tx_pk: int) -> dict[str, Any] | None:
            if tx_pk <= 0:
                return None
            return _tx_dict(next((tx for tx in _stock_txs() if int(getattr(tx, "pk", 0) or 0) == tx_pk), None))

        def _stock_balance(item_id: int, warehouse_id: int | None = None) -> float:
            rows = [tx for tx in _stock_txs() if int(getattr(tx, "item_id", 0) or 0) == int(item_id)]
            if warehouse_id not in (None, ""):
                rows = [tx for tx in rows if int(getattr(tx, "warehouse_id", 0) or 0) == int(warehouse_id or 0)]
            total = 0.0
            for tx in rows:
                direction = getattr(tx, "direction", "")
                direction_value = _compact_text(getattr(direction, "value", direction)).casefold()
                qty = float(getattr(tx, "qty", 0) or 0)
                total += qty if direction_value in {"in", "in_"} or direction == StockTxDirection.IN_ else -qty
            return total

        if capability_id in {"stock.action_manual_in", "stock.action_manual_out"}:
            data = dict(result.data or {}) if isinstance(result.data, dict) else {}
            tx_pk = int(data.get("tx_id") or 0)
            row = _tx_by_pk(tx_pk)
            expected_direction = "in" if capability_id.endswith("manual_in") else "out"
            expected_qty = payload.get("qty")
            qty_ok = True
            if expected_qty not in (None, "") and row:
                qty_ok = abs(float(row.get("qty") or 0) - float(expected_qty)) < 1e-9
            if row and row.get("direction") == expected_direction and qty_ok:
                return Result.ok(
                    "Stock manuel hareket DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={
                        "verified": True,
                        "verified_by": "db",
                        "tx_pk": tx_pk,
                        "row": row,
                        "on_hand": _stock_balance(int(row.get("item_id") or 0), int(row.get("warehouse_id") or 0)),
                    },
                )
            return Result.fail(
                "Stock manuel hareket verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "tx_pk": tx_pk, "row": row, "payload": payload},
            )

        if capability_id == "stock.action_adjust_item_stock_to":
            item_id = int(payload.get("item_id") or 0)
            warehouse_id = payload.get("warehouse_id")
            target_qty = float(payload.get("target_qty") or 0)
            on_hand = _stock_balance(item_id, int(warehouse_id) if warehouse_id not in (None, "") else None)
            if item_id > 0 and abs(on_hand - target_qty) < 1e-9:
                return Result.ok(
                    "Stock duzeltme DB bakiye verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "item_id": item_id, "warehouse_id": warehouse_id, "target_qty": target_qty, "on_hand": on_hand},
                )
            return Result.fail(
                "Stock duzeltme verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "item_id": item_id, "warehouse_id": warehouse_id, "target_qty": target_qty, "on_hand": on_hand},
            )

        if capability_id == "stock.action_export_txs_excel":
            output_path = Path(_compact_text(payload.get("output_path")))
            if output_path and output_path.exists() and output_path.stat().st_size > 0:
                return Result.ok(
                    "Stock hareket Excel export filesystem verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "filesystem", "output_path": str(output_path), "size": output_path.stat().st_size},
                )
            return Result.fail(
                "Stock hareket Excel export verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "output_path": str(output_path)},
            )

        if capability_id == "stock.action_delete_item":
            pk = int(payload.get("pk") or 0)
            item_row = next((item for item in _stock_items() if int(getattr(item, "pk", 0) or 0) == pk), None)
            tx_rows = [tx for tx in _stock_txs() if int(getattr(tx, "item_id", 0) or 0) == pk] if pk > 0 else []
            if pk > 0 and item_row is None and not tx_rows:
                return Result.ok(
                    "Stock kart delete DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "pk": pk, "tx_count": 0},
                )
            return Result.fail(
                "Stock kart delete verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "pk": pk, "item_exists": item_row is not None, "tx_count": len(tx_rows)},
            )

        if capability_id == "stock.action_update_tx_attachments":
            tx_id = int(payload.get("tx_id") or 0)
            expected = payload.get("attachments")
            row = next((tx for tx in _stock_txs() if int(getattr(tx, "pk", 0) or 0) == tx_id), None)
            actual = getattr(row, "attachments", None) if row is not None else None
            if tx_id > 0 and _compact_text(actual) == _compact_text(expected):
                return Result.ok(
                    "Stock hareket attachment DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "tx_id": tx_id, "attachments": actual},
                )
            return Result.fail(
                "Stock hareket attachment verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "tx_id": tx_id, "expected": expected, "actual": actual},
            )

        if capability_id == "stock.action_update_tx_edit_fields":
            tx_id = int(payload.get("tx_id") or 0)
            row = next((tx for tx in _stock_txs() if int(getattr(tx, "pk", 0) or 0) == tx_id), None)
            row_data = {
                "attachments": getattr(row, "attachments", None),
                "unit_cost_input_mode": getattr(row, "unit_cost_input_mode", None),
                "unit_cost_vat_rate": getattr(row, "unit_cost_vat_rate", None),
            } if row is not None else None
            ok = bool(row_data)
            for key in ("attachments", "unit_cost_input_mode", "unit_cost_vat_rate"):
                if key not in payload or payload.get(key) in (None, ""):
                    continue
                if key == "unit_cost_vat_rate":
                    ok = ok and abs(float((row_data or {}).get(key) or 0) - float(payload.get(key) or 0)) < 1e-9
                else:
                    ok = ok and _compact_text((row_data or {}).get(key)) == _compact_text(payload.get(key))
            if tx_id > 0 and ok:
                return Result.ok(
                    "Stock hareket edit fields DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "tx_id": tx_id, "row": row_data},
                )
            return Result.fail(
                "Stock hareket edit fields verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "tx_id": tx_id, "expected": payload, "row": row_data},
            )

        if capability_id == "stock.action_auto_deduct_order_items":
            data = dict(result.data or {}) if isinstance(result.data, dict) else {}
            records = list(data.get("created_records") or [])
            tx_ids = [int(row.get("tx_id") or 0) for row in records if int(row.get("tx_id") or 0) > 0]
            rows = [tx for tx in _stock_txs() if int(getattr(tx, "pk", 0) or 0) in tx_ids] if tx_ids else []
            rows_by_pk = {int(getattr(row, "pk", 0) or 0): row for row in rows}
            verified_rows: list[dict[str, Any]] = []
            for record in records:
                tx_pk = int(record.get("tx_id") or 0)
                row = rows_by_pk.get(tx_pk)
                row_data = _tx_dict(row)
                if not row_data or row_data.get("direction") != "out":
                    continue
                if _compact_text(getattr(getattr(row, "reason", ""), "value", getattr(row, "reason", ""))) != "order_out":
                    continue
                verified_rows.append(row_data)
            if records and len(verified_rows) == len(records):
                return Result.ok(
                    "Stock siparis auto-deduct DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={
                        "verified": True,
                        "verified_by": "db",
                        "tx_created": int(data.get("tx_created") or 0),
                        "rows": verified_rows,
                    },
                )
            return Result.fail(
                "Stock siparis auto-deduct verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "created_records": records, "verified_rows": verified_rows},
            )

        if capability_id == "stock.action_create_warehouse":
            expected_name = _compact_text(payload.get("name"))
            row = next(
                (
                    item
                    for item in _warehouses()
                    if _compact_text(getattr(item, "name", "")) == expected_name
                ),
                None,
            )
            row_data = {
                "pk": int(getattr(row, "pk", 0) or 0),
                "name": _compact_text(getattr(row, "name", "")),
                "code": _compact_text(getattr(row, "code", "")),
                "manager_name": _compact_text(getattr(row, "manager_name", "")),
                "phone": _compact_text(getattr(row, "phone", "")),
                "email": _compact_text(getattr(row, "email", "")),
                "address": _compact_text(getattr(row, "address", "")),
                "city": _compact_text(getattr(row, "city", "")),
                "country": _compact_text(getattr(row, "country", "")),
                "note": _compact_text(getattr(row, "note", "")),
            } if row is not None else None
            ok = bool(expected_name and row_data)
            for key, expected_value in payload.items():
                if key == "db_name" or expected_value in (None, ""):
                    continue
                if key == "capacity_m3":
                    actual = getattr(row, key, None) if row is not None else None
                    ok = ok and actual is not None and abs(float(actual) - float(expected_value)) < 1e-9
                elif row_data is not None and key in row_data and _compact_text(row_data.get(key)) != _compact_text(expected_value):
                    ok = False
            if ok:
                return Result.ok(
                    "Stock depo create DB verify ile dogrulandi.",
                    close_dialog=False,
                    data={"verified": True, "verified_by": "db", "row": row_data},
                )
            return Result.fail(
                "Stock depo create verify tamamlanmadi.",
                close_dialog=False,
                data={"verified": False, "payload": payload, "row": row_data},
            )

        if capability_id == "stock.action_update_warehouse":
            pk = int(payload.get("pk") or 0)
            expected = dict(payload.get("update_data") or {}) if isinstance(payload.get("update_data"), dict) else {}
            row = next((item for item in _warehouses() if int(getattr(item, "pk", 0) or 0) == pk), None)
            row_data = {
                "pk": int(getattr(row, "pk", 0) or 0),
                "name": _compact_text(getattr(row, "name", "")),
                "code": _compact_text(getattr(row, "code", "")),
                "note": _compact_text(getattr(row, "note", "")),
                "is_active": bool(getattr(row, "is_active", False)),
            } if row is not None else None
            ok = bool(row_data)
            for key, expected_value in expected.items():
                if expected_value in (None, ""):
                    continue
                if _compact_text((row_data or {}).get(key)) != _compact_text(expected_value):
                    ok = False
                    break
            if pk > 0 and ok:
                return Result.ok("Stock depo update DB verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "db", "row": row_data})
            return Result.fail("Stock depo update verify tamamlanmadi.", close_dialog=False, data={"verified": False, "pk": pk, "expected": expected, "row": row_data})

        if capability_id == "stock.action_delete_warehouse":
            pk = int(payload.get("pk") or 0)
            row = next((item for item in _warehouses() if int(getattr(item, "pk", 0) or 0) == pk), None)
            if pk > 0 and row is None:
                return Result.ok("Stock depo delete DB verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "db", "pk": pk})
            return Result.fail("Stock depo delete verify tamamlanmadi.", close_dialog=False, data={"verified": False, "pk": pk, "exists": row is not None})

        if capability_id == "stock.action_create_upper_group":
            expected = _compact_text(payload.get("name"))
            records = (stock_domain_pipeline.list_upper_group_records().data or {}).get("records", [])
            row = next((record for record in records if _compact_text(getattr(record, "name", "")) == expected), None)
            if expected and row is not None:
                return Result.ok("Stock ust grup create catalog verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "catalog", "pk": int(getattr(row, "pk", 0) or 0), "name": expected})
            return Result.fail("Stock ust grup create verify tamamlanmadi.", close_dialog=False, data={"verified": False, "name": expected})

        if capability_id == "stock.action_update_upper_group":
            pk = int(payload.get("pk") or 0)
            expected = _compact_text((payload.get("update_data") or {}).get("name") if isinstance(payload.get("update_data"), dict) else "")
            records = (stock_domain_pipeline.list_upper_group_records().data or {}).get("records", [])
            row = next((record for record in records if int(getattr(record, "pk", 0) or 0) == pk), None)
            if pk > 0 and row is not None and _compact_text(getattr(row, "name", "")) == expected:
                return Result.ok("Stock ust grup update catalog verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "catalog", "pk": pk, "name": expected})
            return Result.fail("Stock ust grup update verify tamamlanmadi.", close_dialog=False, data={"verified": False, "pk": pk, "expected": expected})

        if capability_id == "stock.action_delete_upper_group":
            pk = int(payload.get("pk") or 0)
            records = (stock_domain_pipeline.list_upper_group_records().data or {}).get("records", [])
            row = next((record for record in records if int(getattr(record, "pk", 0) or 0) == pk), None)
            if pk > 0 and row is None:
                return Result.ok("Stock ust grup delete catalog verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "catalog", "pk": pk})
            return Result.fail("Stock ust grup delete verify tamamlanmadi.", close_dialog=False, data={"verified": False, "pk": pk, "exists": row is not None})

        if capability_id in {"stock.action_create_sub_group", "stock.action_update_sub_group"}:
            expected_category = _compact_text(payload.get("category") or ((payload.get("update_data") or {}).get("category") if isinstance(payload.get("update_data"), dict) else ""))
            expected_name = _compact_text(payload.get("name") or ((payload.get("update_data") or {}).get("name") if isinstance(payload.get("update_data"), dict) else ""))
            records = (stock_domain_pipeline.list_sub_groups(category=expected_category or None, only_active=False).data or {}).get("records", [])
            row = next((record for record in records if _compact_text(getattr(record, "name", "")) == expected_name), None)
            if expected_name and row is not None:
                return Result.ok("Stock alt grup catalog verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "catalog", "pk": int(getattr(row, "pk", 0) or 0), "category": _compact_text(getattr(row, "category", "")), "name": expected_name})
            return Result.fail("Stock alt grup verify tamamlanmadi.", close_dialog=False, data={"verified": False, "category": expected_category, "name": expected_name})

        if capability_id == "stock.action_delete_sub_group":
            pk = int(payload.get("pk") or 0)
            records = (stock_domain_pipeline.list_sub_groups(only_active=False).data or {}).get("records", [])
            row = next((record for record in records if int(getattr(record, "pk", 0) or 0) == pk), None)
            if pk > 0 and row is None:
                return Result.ok("Stock alt grup delete catalog verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "catalog", "pk": pk})
            return Result.fail("Stock alt grup delete verify tamamlanmadi.", close_dialog=False, data={"verified": False, "pk": pk, "exists": row is not None})

        def _stock_catalog_dict(row: Any) -> dict[str, Any] | None:
            if row is None:
                return None
            return {
                key: getattr(row, key, None)
                for key in (
                    "pk",
                    "name",
                    "code",
                    "registration_no",
                    "country",
                    "website",
                    "contact_email",
                    "contact_phone",
                    "tax_no",
                    "phone",
                    "email",
                    "address",
                    "note",
                    "is_active",
                )
                if hasattr(row, key)
            }

        def _stock_catalog_row(kind: str, *, pk: int = 0, name: str = "") -> dict[str, Any] | None:
            query = finance_repo.list_records(kind, db_name=db_name or DB_NAME)
            rows = _repo_rows(query)
            if pk > 0:
                return _stock_catalog_dict(next((item for item in rows if int(getattr(item, "pk", 0) or 0) == pk), None))
            if name:
                row = next((item for item in rows if _compact_text(getattr(item, "name", "")) == name), None)
                return _stock_catalog_dict(row)
            return None

        def _stock_catalog_expected_ok(row: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
            if not row:
                return False
            for key, expected_value in dict(expected or {}).items():
                if key == "db_name" or expected_value in (None, ""):
                    continue
                if key == "update_data":
                    if not _stock_catalog_expected_ok(row, expected_value if isinstance(expected_value, dict) else {}):
                        return False
                    continue
                row_value = row.get(key)
                if isinstance(expected_value, bool):
                    if bool(row_value) != expected_value:
                        return False
                elif _compact_text(row_value) != _compact_text(expected_value):
                    return False
            return True

        if capability_id in {"stock.action_create_brand", "stock.action_create_company"}:
            kind = "brand" if capability_id.endswith("brand") else "company"
            expected = {key: value for key, value in payload.items() if key != "db_name"}
            row = _stock_catalog_row(kind, name=_compact_text(payload.get("name")))
            if _stock_catalog_expected_ok(row, expected):
                return Result.ok("Stock marka/sirket create DB verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "db", "row": row})
            return Result.fail("Stock marka/sirket create verify tamamlanmadi.", close_dialog=False, data={"verified": False, "payload": payload, "row": row})

        if capability_id in {"stock.action_update_brand", "stock.action_update_company"}:
            kind = "brand" if capability_id.endswith("brand") else "company"
            pk = int(payload.get("pk") or 0)
            expected = dict(payload.get("update_data") or {}) if isinstance(payload.get("update_data"), dict) else {}
            row = _stock_catalog_row(kind, pk=pk)
            if pk > 0 and _stock_catalog_expected_ok(row, expected):
                return Result.ok("Stock marka/sirket update DB verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "db", "row": row})
            return Result.fail("Stock marka/sirket update verify tamamlanmadi.", close_dialog=False, data={"verified": False, "pk": pk, "expected": expected, "row": row})

        if capability_id in {"stock.action_delete_brand", "stock.action_delete_company"}:
            kind = "brand" if capability_id.endswith("brand") else "company"
            pk = int(payload.get("pk") or 0)
            row = _stock_catalog_row(kind, pk=pk)
            if pk > 0 and (row is None or bool(row.get("is_active")) is False):
                return Result.ok("Stock marka/sirket delete DB verify ile dogrulandi.", close_dialog=False, data={"verified": True, "verified_by": "db", "pk": pk, "row": row})
            return Result.fail("Stock marka/sirket delete verify tamamlanmadi.", close_dialog=False, data={"verified": False, "pk": pk, "row": row})

        return Result.ok(
            "Stock manuel action Result.success ile dogrulandi.",
            close_dialog=False,
            data={"verified": True, "verified_by": "manual_action_result_success", "capability": capability.to_dict()},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_listing_manual_action(capability: ManualCapability, action: dict[str, Any], result: Result) -> Result:
    try:
        from Listing.processors import agentic_repository as listing_repo

        capability_id = capability.capability_id
        payload = _manual_payload_from_action(action)
        db_name = _compact_text(payload.get("db_name")) or DB_NAME

        if capability_id == "listing.action_update_approved_content_for_account":
            result_data = dict(result.data or {}) if isinstance(result.data, dict) else {}
            if bool(result_data.get("verified")) and not bool(result_data.get("pending")):
                return Result.ok(
                    "Listing icerik mutation batch sonucu ile dogrulandi.",
                    close_dialog=False,
                    data={
                        "verified": True,
                        "verified_by": "trendyol_batch_result",
                        "batch_request_id": result_data.get("batch_request_id"),
                        "content_id": result_data.get("content_id"),
                        "item_status": result_data.get("item_status"),
                    },
                )
            return Result.fail(
                "Listing icerik mutation batch sonucu henuz dogrulanmadi.",
                close_dialog=False,
                data={
                    "verified": False,
                    "pending": bool(result_data.get("pending")),
                    "batch_request_id": result_data.get("batch_request_id"),
                    "content_id": result_data.get("content_id"),
                    "item_status": result_data.get("item_status"),
                },
            )

        bundle_result = listing_repo.verification_bundle(db_name=db_name)
        if not bundle_result.success:
            return Result.fail(
                "Listing verify kayitlari okunamadi.",
                error=bundle_result.error,
                close_dialog=False,
                data={"verified": False, "repository_message": bundle_result.message},
            )
        bundle = dict(bundle_result.data or {}) if isinstance(bundle_result.data, dict) else {}
        products = list(bundle.get("products") or [])
        stock_snapshots = list(bundle.get("stock_snapshots") or [])
        cost_snapshots = list(bundle.get("cost_snapshots") or [])

        def _listing_pk() -> int | None:
            listing_id = payload.get("listing_id") or payload.get("listingId")
            if listing_id not in (None, ""):
                try:
                    return int(listing_id)
                except Exception:
                    return None
            api_account_id = payload.get("api_account_id")
            product_id = _compact_text(payload.get("product_id") or payload.get("productId"))
            if api_account_id in (None, "") or not product_id:
                item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
                listing_id = item.get("listing_id") or item.get("listingId")
                if listing_id not in (None, ""):
                    try:
                        return int(listing_id)
                    except Exception:
                        return None
                api_account_id = item.get("api_account_id")
                product_id = _compact_text(item.get("product_id") or item.get("productId") or item.get("variantId") or item.get("contentId"))
            if api_account_id in (None, "") or not product_id:
                return None
            row = next(
                (
                    item
                    for item in products
                    if int(getattr(item, "api_account_id", 0) or 0) == int(api_account_id)
                    and _compact_text(getattr(item, "product_id", "")) == product_id
                ),
                None,
            )
            row_pk = getattr(row, "pk", None) if row is not None else None
            return int(row_pk) if row_pk is not None else None

        def _latest_stock_rows(listing_id: int) -> dict[int, Any]:
            rows = sorted(
                (
                    row
                    for row in stock_snapshots
                    if int(getattr(row, "listing_id", 0) or 0) == int(listing_id)
                ),
                key=lambda row: (getattr(row, "created_at", None), int(getattr(row, "pk", 0) or 0)),
                reverse=True,
            )
            latest: dict[int, Any] = {}
            for row in rows:
                key = int(getattr(row, "stock_item_id", 0) or 0)
                if key > 0 and key not in latest:
                    latest[key] = row
            return latest

        def _latest_cost_rows(listing_id: int) -> dict[str, Any]:
            rows = sorted(
                (
                    row
                    for row in cost_snapshots
                    if int(getattr(row, "listing_id", 0) or 0) == int(listing_id)
                ),
                key=lambda row: (getattr(row, "created_at", None), int(getattr(row, "pk", 0) or 0)),
                reverse=True,
            )
            latest: dict[str, Any] = {}
            for row in rows:
                key = _compact_text(getattr(row, "cost_key", "")).casefold()
                if key and key not in latest:
                    latest[key] = row
            return latest

        def _active_status(row: Any) -> bool:
            return _compact_text(getattr(row, "status", "")).casefold() not in {"remove", "removed", "delete", "deleted"}

        def _verify_from_bundle() -> Result | None:
            if capability_id == "listing.action_fetch_listings":
                data = dict(result.data or {}) if isinstance(result.data, dict) else {}
                account_ids = [
                    int(value)
                    for value in _as_list(data.get("api_account_ids") or payload.get("api_account_ids"))
                    if _compact_text(value)
                ]
                product_ids = [
                    _compact_text(value)
                    for value in _as_list(data.get("saved_product_ids"))
                    if _compact_text(value)
                ]
                if not product_ids:
                    fetch_data = dict(data.get("fetch") or {}) if isinstance(data.get("fetch"), dict) else {}
                    for row in list(fetch_data.get("items") or []):
                        if not isinstance(row, dict):
                            continue
                        product_id = _compact_text(
                            row.get("product_id")
                            or row.get("productId")
                            or row.get("variantId")
                            or row.get("contentId")
                            or row.get("platformListingId")
                            or row.get("id")
                        )
                        if product_id:
                            product_ids.append(product_id)
                product_ids = list(dict.fromkeys(product_ids))
                if not product_ids:
                    return Result.ok(
                        "Listing fetch/save verify: kaydedilecek ilan yok.",
                        close_dialog=False,
                        data={"verified": True, "verified_by": "empty_fetch", "api_account_ids": account_ids},
                    )
                rows = [
                    row
                    for row in products
                    if _compact_text(getattr(row, "product_id", "")) in product_ids
                    and (
                        not account_ids
                        or int(getattr(row, "api_account_id", 0) or 0) in account_ids
                    )
                ]
                saved_pairs = {
                    (int(getattr(row, "api_account_id", 0) or 0), _compact_text(getattr(row, "product_id", "")))
                    for row in rows
                }
                saved_product_ids = {_compact_text(getattr(row, "product_id", "")) for row in rows}
                if set(product_ids).issubset(saved_product_ids):
                    return Result.ok(
                        "Listing fetch/save DB verify ile dogrulandi.",
                        close_dialog=False,
                        data={
                            "verified": True,
                            "verified_by": "db",
                            "api_account_ids": account_ids,
                            "product_ids": product_ids,
                            "saved_pairs": sorted(saved_pairs),
                        },
                    )
                missing = [product_id for product_id in product_ids if product_id not in saved_product_ids]
                return Result.fail(
                    "Listing fetch/save verify tamamlanmadi.",
                    close_dialog=False,
                    data={"verified": False, "api_account_ids": account_ids, "product_ids": product_ids, "missing_product_ids": missing},
                )

            if capability_id == "listing.action_update_listing_price_inventory_cache":
                row = next(
                    (
                        item
                        for item in products
                        if int(getattr(item, "api_account_id", 0) or 0) == int(payload.get("api_account_id"))
                        and _compact_text(getattr(item, "product_id", "")) == _compact_text(payload.get("product_id"))
                    ),
                    None,
                )
                expected = {
                    "quantity": payload.get("quantity"),
                    "list_price": payload.get("list_price"),
                    "sale_price": payload.get("sale_price"),
                }
                ok = row is not None
                for key, expected_value in expected.items():
                    if expected_value is None:
                        ok = ok and getattr(row, key, None) is None
                    else:
                        ok = ok and abs(float(getattr(row, key, 0.0) or 0.0) - float(expected_value)) < 0.0001
                if ok:
                    return Result.ok(
                        "Listing cache write DB verify ile dogrulandi.",
                        close_dialog=False,
                        data={"verified": True, "verified_by": "db", "product_id": payload.get("product_id"), "expected": expected},
                    )
                return Result.fail(
                    "Listing cache write verify tamamlanmadi.",
                    close_dialog=False,
                    data={"verified": False, "product_id": payload.get("product_id"), "expected": expected},
                )

            if capability_id == "listing.action_set_listing_stock_items":
                listing_id = _listing_pk()
                if listing_id is None:
                    return Result.fail("Listing stock link verify icin ilan bulunamadi.", close_dialog=False, data={"verified": False})
                latest = _latest_stock_rows(listing_id)
                desired = {
                    int((row or {}).get("stock_item_id") or (row or {}).get("id")): float((row or {}).get("qty") if "qty" in (row or {}) else (row or {}).get("quantity") or 0.0)
                    for row in list(payload.get("stock_items") or [])
                    if isinstance(row, dict) and ((row.get("stock_item_id") or row.get("id")) not in (None, ""))
                }
                ok = True
                for stock_id, qty in desired.items():
                    latest_row = latest.get(stock_id)
                    ok = ok and latest_row is not None and _active_status(latest_row) and abs(float(getattr(latest_row, "qty", 0.0) or 0.0) - qty) < 0.0001
                for stock_id, latest_row in latest.items():
                    if stock_id not in desired:
                        ok = ok and not _active_status(latest_row)
                if ok:
                    return Result.ok(
                        "Listing stock link DB verify ile dogrulandi.",
                        close_dialog=False,
                        data={"verified": True, "verified_by": "db", "listing_id": listing_id, "stock_item_ids": sorted(desired.keys())},
                    )
                return Result.fail(
                    "Listing stock link verify tamamlanmadi.",
                    close_dialog=False,
                    data={"verified": False, "listing_id": listing_id, "stock_item_ids": sorted(desired.keys())},
                )

            if capability_id in {"listing.action_set_listing_cost_items", "listing.action_sync_listing_cost_snapshots_for_item"}:
                listing_id = _listing_pk()
                if listing_id is None:
                    return Result.fail("Listing cost verify icin ilan bulunamadi.", close_dialog=False, data={"verified": False})
                latest = _latest_cost_rows(listing_id)
                if capability_id == "listing.action_set_listing_cost_items":
                    desired_keys = {
                        _compact_text(row.get("cost_key") or row.get("costKey")).casefold()
                        for row in list(payload.get("cost_items") or [])
                        if isinstance(row, dict) and _compact_text(row.get("cost_key") or row.get("costKey"))
                    }
                else:
                    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
                    detail = dict((payload.get("estimation") or {}).get("estimated_profit_detail") or {}) if isinstance(payload.get("estimation"), dict) else {}
                    desired_keys = {
                        _compact_text(row.get("cost_key") or row.get("costKey")).casefold()
                        for row in list(item.get("cost_items") or [])
                        if isinstance(row, dict) and _compact_text(row.get("cost_key") or row.get("costKey"))
                    }
                    desired_keys.update(
                        _compact_text(row.get("key")).casefold()
                        for row in list(detail.get("applied_costs") or [])
                        if isinstance(row, dict) and _compact_text(row.get("key")) and _compact_text(row.get("key")).casefold() != "stock"
                    )
                ok = bool(desired_keys)
                for key in desired_keys:
                    latest_row = latest.get(key)
                    ok = ok and latest_row is not None and _active_status(latest_row)
                if capability_id == "listing.action_set_listing_cost_items":
                    for key, latest_row in latest.items():
                        if key not in desired_keys:
                            ok = ok and not _active_status(latest_row)
                if ok:
                    return Result.ok(
                        "Listing cost snapshot DB verify ile dogrulandi.",
                        close_dialog=False,
                        data={"verified": True, "verified_by": "db", "listing_id": listing_id, "cost_keys": sorted(desired_keys)},
                    )
                return Result.fail(
                    "Listing cost snapshot verify tamamlanmadi.",
                    close_dialog=False,
                    data={"verified": False, "listing_id": listing_id, "cost_keys": sorted(desired_keys)},
                )

        verified_result = _verify_from_bundle()
        if verified_result is not None:
            return verified_result

        return Result.ok(
            "Listing manuel action Result.success ile dogrulandi.",
            close_dialog=False,
            data={"verified": True, "verified_by": "manual_action_result_success", "capability": capability.to_dict()},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_workflow_spec_save(action: dict[str, Any], result: Result | None = None) -> Result:
    """Independently reopen the exact immutable revision from the approved recipe."""
    try:
        from AI.processors.workflow_store import _validated_action, read_workflow
        if result is not None and not result.success:
            return Result.fail("İş talimatı kaydedilemedi; doğrulama yapılmadı.", close_dialog=False)
        proposal = _validated_action(_manual_payload_from_action(action).get("proposal") or {})
        revision = read_workflow(proposal["workflow_id"], revision_id=proposal["revision_id"])
        current = read_workflow(proposal["workflow_id"])
        exact = (revision.parent_revision_id == proposal["expected_revision_id"]
                 and revision.spec.content_hash == proposal["spec_hash"]
                 and revision.spec.to_dict() == proposal["spec"]
                 and current.revision_id == revision.revision_id
                 and current.spec.content_hash == revision.spec.content_hash)
        evidence = {"verified": exact, "verified_by": "workflow_exact_revision_sqlite_readback",
                    "workflow_id": revision.workflow_id, "revision_id": revision.revision_id,
                    "parent_revision_id": revision.parent_revision_id, "spec_hash": revision.spec.content_hash,
                    "current_revision_id": current.revision_id,
                    "current_head_matches_approved_revision": current.revision_id == revision.revision_id,
                    "proposal_hash": proposal["action_hash"], "fresh_model_plan_required": True,
                    "saved_execution_authority": False}
        if not exact:
            return Result.fail("Kayıtlı iş sürümü onaylanan talimatlarla eşleşmedi.", close_dialog=False, data=evidence)
        return Result.ok("Kayıtlı işin tam sürümü yeniden okunarak doğrulandı.", close_dialog=False, data=evidence)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False,
                           data={"verified": False, "verified_by": "workflow_exact_revision_sqlite_readback"})


def _verify_manual_action_result(capability: ManualCapability, action: dict[str, Any], result: Result) -> Result:
    if not result.success:
        return Result.fail("Execute basarisiz; verify atlandi.", close_dialog=False)
    if capability.capability_id == "ai.action_save_workflow_spec":
        return verify_workflow_spec_save(action, result)
    if capability.capability_id == "orders.get_orders_from_companies":
        return verify_orders_sync_from_result(action, result)
    if capability.capability_id == "orders.save_return_claims_to_db":
        return verify_return_claims_save(action, result)
    if capability.capability_id == "orders.update_last_used_at_for_accounts":
        return verify_accounts_last_used_update(action, result)
    if capability.capability_id in {"orders.change_order_cargo_provider", "orders.change_orders_cargo_provider_bulk"}:
        return verify_order_cargo_provider_change(action)
    if capability.capability_id == "labels.action_create_labels_from_selected_orders":
        return verify_labels_create(action, result)
    if capability.capability_id == "labels.mark_orders_extracted_from_label_result":
        return verify_labels_mark_extracted(action, result)
    if capability.capability_id == "orders.action_export_order_profit_excel":
        return verify_order_profit_excel_export(action, result)
    if capability.capability_id in {
        "orders.action_export_report_snapshot_xlsx",
        "ai.action_export_report_snapshot_xlsx",
    }:
        return verify_report_snapshot_xlsx_export(action, result)
    if capability.capability_id == "orders.approve_return_claim":
        return verify_return_approval(action)
    if capability.capability_id == "orders.mark_return_claims_stale":
        return verify_return_claims_stale_mark(action, result)
    if capability.capability_id == "orders.restore_return_claims_from_stale":
        return verify_return_claims_stale_restore(action, result)
    if capability.domain == "marketplaces":
        return verify_marketplace_manual_action(capability, action, result)
    if capability.domain == "logistics" and ("cargo_provider" in capability.capability_id or "cargo_tariff" in capability.capability_id):
        return verify_logistics_manual_action(capability, action, result)
    if capability.domain == "finance":
        return verify_finance_manual_action(capability, action, result)
    if capability.domain == "stock":
        return verify_stock_manual_action(capability, action, result)
    if capability.domain == "listing":
        return verify_listing_manual_action(capability, action, result)
    return Result.ok(
        "Bu manuel capability icin generic verify, action Result.success auditine dayanir.",
        close_dialog=False,
        data={"capability": capability.to_dict(), "verified_by": "manual_action_result_success"},
    )


def _staging_marketplace_fail(message: str, *, action_type: str, **data: Any) -> Result:
    payload = {"action_type": action_type, "api_call_performed": False, "db_write_performed": False}
    payload.update(data)
    return Result.fail(message, close_dialog=False, data=payload)


def _lookup_api_account_scope(*, db_name: str, api_account_pk: Any) -> dict[str, str]:
    from Account.processors.pipeline import get_company_by_id
    from Marketplaces.processors.catalog import normalize_marketplace_environment

    try:
        pk = int(api_account_pk)
    except Exception:
        return {}
    result = get_company_by_id([pk], db_name=db_name or DB_NAME)
    if not result.success:
        return {}
    records = list((result.data or {}).get("records") or [])
    account = records[0] if records else None
    if account is None:
        return {}
    extra = getattr(account, "extra_config", None)
    extra_config = dict(extra or {}) if isinstance(extra, dict) else {}
    try:
        environment = normalize_marketplace_environment(
            extra_config.get("environment")
            or extra_config.get("api_environment")
            or "production"
        )
    except Exception:
        environment = _compact_text(
            extra_config.get("environment")
            or extra_config.get("api_environment")
            or "production"
        ).casefold()
    return {
        "account_id": _compact_text(getattr(account, "account_id", "")),
        "environment": environment,
    }


def _staging_order_target_account_ids(action: dict[str, Any]) -> Result:
    from Orders.processors import agentic_repository as orders_repo

    payload = _manual_payload_from_action(action)
    db_name = _compact_text(payload.get("db_name")) or DB_NAME
    tokens: list[Any] = []
    for row in _action_rows(action):
        before = dict(row.get("before") or {})
        api_account_id = row.get("api_account_id") or before.get("api_account_id")
        for value in (
            row.get("order_number"),
            before.get("order_number"),
            row.get("package_id"),
            before.get("package_id"),
        ):
            scoped = {"token": value, "api_account_id": api_account_id}
            if _compact_text(value) and scoped not in tokens:
                tokens.append(scoped)
    for ref in _as_list(payload.get("order_refs")):
        if not isinstance(ref, dict):
            continue
        scoped = {
            "token": ref.get("order_number") or ref.get("order") or ref.get("package_id"),
            "api_account_id": ref.get("api_account_id"),
        }
        if _compact_text(scoped.get("token")) and scoped not in tokens:
            tokens.append(scoped)
    for value in (
        payload.get("order"),
        payload.get("order_number"),
        payload.get("package_id"),
    ):
        scoped = {"token": value, "api_account_id": payload.get("api_account_id")}
        if _compact_text(value) and scoped not in tokens:
            tokens.append(scoped)
    for values in (
        payload.get("orders"),
        payload.get("order_numbers"),
        payload.get("package_ids"),
    ):
        for value in _as_list(values):
            scoped = {"token": value, "api_account_id": payload.get("api_account_id")}
            if _compact_text(value) and scoped not in tokens:
                tokens.append(scoped)
    if not tokens:
        return _staging_marketplace_fail(
            "Staging marketplace guard hedef siparis referansi bulamadi.",
            action_type=_compact_text(action.get("action_type")),
        )

    result = orders_repo.target_account_ids("order", tokens, db_name=db_name)
    if not result.success:
        return _staging_marketplace_fail(
            "Staging marketplace guard siparis hedefini veya API hesabini DB'de dogrulayamadi.",
            action_type=_compact_text(action.get("action_type")),
            domain_message=result.message,
        )
    return result


def _staging_return_target_account_ids(action: dict[str, Any]) -> Result:
    from Orders.processors import agentic_repository as orders_repo

    payload = _manual_payload_from_action(action)
    db_name = _compact_text(payload.get("db_name")) or DB_NAME
    tokens: list[Any] = []
    for row in _action_rows(action):
        before = dict(row.get("before") or {})
        api_account_id = row.get("api_account_id") or before.get("api_account_id")
        for value in (
            row.get("claim_id"),
            before.get("claim_id"),
            row.get("order_number"),
            before.get("order_number"),
        ):
            scoped = {"token": value, "api_account_id": api_account_id}
            if _compact_text(value) and scoped not in tokens:
                tokens.append(scoped)
    for value in (payload.get("order"), payload.get("claim_id"), payload.get("claim_number"), payload.get("order_number")):
        scoped = {"token": value, "api_account_id": payload.get("api_account_id")}
        if _compact_text(value) and scoped not in tokens:
            tokens.append(scoped)
    if not tokens:
        return _staging_marketplace_fail(
            "Staging marketplace guard iade hedef referansi bulamadi.",
            action_type=_compact_text(action.get("action_type")),
        )

    result = orders_repo.target_account_ids("return", tokens, db_name=db_name)
    if not result.success:
        return _staging_marketplace_fail(
            "Staging marketplace guard iade hedefini veya API hesabini DB'de dogrulayamadi.",
            action_type=_compact_text(action.get("action_type")),
            domain_message=result.message,
        )
    return result


def _staging_listing_target_account_ids(action: dict[str, Any]) -> Result:
    payload = _manual_payload_from_action(action)
    db_name = _compact_text(payload.get("db_name")) or DB_NAME
    target_accounts: set[str] = set()
    target_environments: set[str] = set()
    seller_id = _compact_text(payload.get("seller_id"))
    if seller_id:
        target_accounts.add(seller_id)
    api_account_id = payload.get("api_account_id")
    if api_account_id not in (None, ""):
        account_scope = _lookup_api_account_scope(db_name=db_name, api_account_pk=api_account_id)
        account_id = _compact_text(account_scope.get("account_id"))
        if not account_id:
            return _staging_marketplace_fail(
                "Staging marketplace guard listing API hesabini dogrulayamadi.",
                action_type=_compact_text(action.get("action_type")),
                api_account_id=api_account_id,
            )
        target_accounts.add(account_id)
        environment = _compact_text(account_scope.get("environment")).casefold()
        if environment:
            target_environments.add(environment)
    if not target_accounts:
        return _staging_marketplace_fail(
            "Staging marketplace guard listing hedef hesabini dogrulayamadi.",
            action_type=_compact_text(action.get("action_type")),
        )
    return Result.ok(
        "Staging marketplace hedef listing hesabi dogrulandi.",
        close_dialog=False,
        data={
            "target_account_ids": sorted(target_accounts),
            "target_environments": sorted(target_environments),
            "db_name": db_name,
        },
    )


def _verify_staging_marketplace_target_accounts(action: dict[str, Any], *, staging_account_id: str) -> Result:
    action_type = _compact_text(action.get("action_type"))
    if action_type in {"orders.change_order_cargo_provider", "orders.change_orders_cargo_provider_bulk"}:
        result = _staging_order_target_account_ids(action)
    elif action_type == "orders.approve_return_claim":
        result = _staging_return_target_account_ids(action)
    elif action_type in {
        "listing.action_update_price_inventory_for_account",
        "listing.action_update_approved_content_for_account",
    }:
        result = _staging_listing_target_account_ids(action)
    else:
        result = _staging_marketplace_fail(
            "Staging marketplace guard bu action hedef hesabini dogrulayamiyor.",
            action_type=action_type,
        )
    if not result.success:
        return result
    data = dict(result.data or {}) if isinstance(result.data, dict) else {}
    target_accounts = [_compact_text(value) for value in list(data.get("target_account_ids") or []) if _compact_text(value)]
    target_environments = [
        _compact_text(value).casefold()
        for value in list(data.get("target_environments") or [])
        if _compact_text(value)
    ]
    requested = _compact_text(staging_account_id)
    if not target_accounts or target_accounts != [requested]:
        return _staging_marketplace_fail(
            "Staging marketplace hedef hesabi staging_account_id ile eslesmedi.",
            action_type=action_type,
            staging_account_id=requested,
            target_account_ids=target_accounts,
        )
    if target_environments != ["stage"]:
        return _staging_marketplace_fail(
            "Staging marketplace hedef hesabi environment=stage degil.",
            action_type=action_type,
            staging_account_id=requested,
            target_account_ids=target_accounts,
            target_environments=target_environments,
        )
    return Result.ok(
        "Staging marketplace hedef hesabi staging_account_id ile dogrulandi.",
        close_dialog=False,
        data=data,
    )


def _staging_marketplace_action_private_payload_findings(payload: Any, *, path: str = "action") -> list[str]:
    findings: list[str] = []
    private_key_tokens = (
        "customer",
        "musteri",
        "alici",
        "recipient",
        "address",
        "adres",
        "phone",
        "telefon",
        "email",
        "e-posta",
    )
    email_pattern = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    phone_pattern = re.compile(r"(?:\+?\d[\s().-]*){10,}")
    allowed_contact_keys = {"cargo_provider", "cargo_provider_code", "cargo_provider_name", "provider", "provider_name"}
    allowed_leaf_keys = {
        "api_account_id",
        "api_account_ids",
        "claim_id",
        "claim_ids",
        "claim_line_item_ids",
        "claim_number",
        "created_at",
        "currency",
        "db_name",
        "idempotency_key",
        "last_modified",
        "line_id",
        "line_item_id",
        "order",
        "order_date",
        "order_number",
        "order_numbers",
        "orders",
        "package_id",
        "package_ids",
        "record_id",
        "shipment_package_id",
        "staging_account_id",
        "status",
        "timestamp",
        "updated_at",
        "waiting_line_item_ids",
    }

    def _has_nonempty_leaf(value: Any) -> bool:
        if isinstance(value, dict):
            return any(_has_nonempty_leaf(child) for child in value.values())
        if isinstance(value, (list, tuple)):
            return any(_has_nonempty_leaf(child) for child in value)
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    def _walk(value: Any, current_path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = _compact_text(key)
                key_cf = key_text.casefold()
                child_path = f"{current_path}.{key_text}" if key_text else current_path
                if key_cf not in allowed_contact_keys and _has_nonempty_leaf(child) and any(token in key_cf for token in private_key_tokens):
                    findings.append(f"{child_path}:private_key")
                _walk(child, child_path)
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                _walk(child, f"{current_path}[{index}]")
            return
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text:
            return
        leaf = current_path.rsplit(".", 1)[-1].split("[", 1)[0].casefold()
        if leaf in allowed_contact_keys:
            return
        if (
            leaf in allowed_leaf_keys
            or leaf.endswith("_date")
            or leaf.endswith("_at")
            or leaf.endswith("_ms")
            or leaf.endswith("_id")
            or leaf.endswith("_ids")
            or leaf.endswith("_hash")
            or leaf.endswith("_fingerprint")
        ):
            return
        if email_pattern.search(text):
            findings.append(f"{current_path}:email")
        if phone_pattern.search(text):
            findings.append(f"{current_path}:phone")

    _walk(payload, path)
    return findings


def _staging_marketplace_evidence_path(idempotency_key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in (_compact_text(idempotency_key) or "staging-marketplace"))
    return AI_DOMAIN_ROOT / "docs" / "live_llm_transcripts" / "staging-marketplace" / f"{safe}.json"


def _staging_marketplace_preflight(
    action: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    staging_reason: str = "",
    marketplace: str = "trendyol",
    staging_account_id: str | None = None,
    require_env: bool = True,
) -> Result:
    action_type = _compact_text(action.get("action_type")) if isinstance(action, dict) else ""
    if action_type in {"listing.update_price", "listing.update_stock", "listing.content_update"}:
        staging_action = action.get("staging_action") if isinstance(action.get("staging_action"), dict) else None
        if not staging_action:
            return Result.fail(
                "Listing mutation dry-run staging action payload'i icermiyor.",
                close_dialog=False,
                data={"action_type": action_type, "api_call_performed": False, "db_write_performed": False},
            )
        action = dict(staging_action)
        action_type = _compact_text(action.get("action_type"))
    if action_type not in STAGING_MARKETPLACE_ACTION_TYPES:
        return Result.fail(
            "Bu action staging marketplace mutation kaniti icin desteklenmiyor.",
            close_dialog=False,
            data={
                "action_type": action_type,
                "allowed_action_types": sorted(STAGING_MARKETPLACE_ACTION_TYPES),
                "api_call_performed": False,
                "db_write_performed": False,
            },
        )
    if action_type == "listing.action_update_approved_content_for_account":
        content_payload = _manual_payload_from_action(action)
        content_items = list(content_payload.get("items") or [])
        try:
            expected_content_id = int(content_payload.get("content_id") or 0)
        except Exception:
            expected_content_id = 0
        item_content_id = 0
        if len(content_items) == 1 and isinstance(content_items[0], dict):
            try:
                item_content_id = int(content_items[0].get("contentId") or 0)
            except Exception:
                item_content_id = 0
        if (
            not bool(content_payload.get("wait_result"))
            or expected_content_id <= 0
            or len(content_items) != 1
            or item_content_id != expected_content_id
        ):
            return _staging_marketplace_fail(
                "Listing icerik mutation exact tek contentId ve zorunlu batch verify gerektirir.",
                action_type=action_type,
                problems=["content_batch_verify_scope"],
            )
    capability = find_manual_capability(action_type)
    if capability is None or not bool(capability.external_write):
        return Result.fail(
            "Staging marketplace mutation sadece external_write manuel capability icin kullanilir.",
            close_dialog=False,
            data={"action_type": action_type, "api_call_performed": False, "db_write_performed": False},
        )
    private_findings = _staging_marketplace_action_private_payload_findings(action)
    secretish_payload = _contains_secretish_key(action)
    if private_findings or secretish_payload:
        problems: list[str] = []
        if private_findings:
            problems.append("action_private_payload")
        if secretish_payload:
            problems.append("action_secretish_payload")
        return _staging_marketplace_fail(
            "Staging marketplace action payload must not contain customer/contact/address data or credentials.",
            action_type=action_type,
            problems=problems,
            action_private_findings=private_findings,
        )
    if require_env and not _truthy_env(STAGING_MARKETPLACE_MUTATION_ENV):
        return Result.fail(
            f"Staging marketplace mutation kapali. {STAGING_MARKETPLACE_MUTATION_ENV}=1 olmadan gercek pazar yeri yazma calismaz.",
            close_dialog=False,
            data={
                "action_type": action_type,
                "env": STAGING_MARKETPLACE_MUTATION_ENV,
                "api_call_performed": False,
                "db_write_performed": False,
            },
        )
    reason = _compact_text(staging_reason)
    if len(reason) < 12:
        return Result.fail(
            "Staging marketplace mutation icin acik bir staging_reason gerekir.",
            close_dialog=False,
            data={"action_type": action_type, "api_call_performed": False, "db_write_performed": False},
        )
    if looks_like_staging_marketplace_placeholder(reason):
        return _staging_marketplace_fail(
            "Staging marketplace mutation icin placeholder olmayan gercek bir staging_reason gerekir.",
            action_type=action_type,
            problems=["staging_reason_placeholder"],
        )
    marketplace_value = _compact_text(marketplace).casefold() or "trendyol"
    if marketplace_value != "trendyol":
        return Result.fail(
            "Su anda staging marketplace mutation kaniti sadece Trendyol aksiyonlari icin acik.",
            close_dialog=False,
            data={"action_type": action_type, "marketplace": marketplace_value, "api_call_performed": False},
        )
    key = _compact_text(idempotency_key)
    if not key:
        return _staging_marketplace_fail(
            "Staging marketplace mutation icin acik idempotency_key gerekir.",
            action_type=action_type,
            missing="idempotency_key",
        )
    if looks_like_staging_marketplace_placeholder(key):
        return _staging_marketplace_fail(
            "Staging marketplace mutation icin placeholder olmayan gercek bir idempotency_key gerekir.",
            action_type=action_type,
            problems=["idempotency_key_placeholder"],
        )
    clean_staging_account_id = _compact_text(staging_account_id)
    if not clean_staging_account_id:
        return _staging_marketplace_fail(
            "Staging marketplace mutation icin staging_account_id gerekir.",
            action_type=action_type,
            missing="staging_account_id",
        )
    if looks_like_staging_marketplace_placeholder(clean_staging_account_id):
        return _staging_marketplace_fail(
            "Staging marketplace mutation icin placeholder olmayan gercek bir staging_account_id gerekir.",
            action_type=action_type,
            problems=["staging_account_id_placeholder"],
        )
    target_guard = _verify_staging_marketplace_target_accounts(action, staging_account_id=clean_staging_account_id)
    if not target_guard.success:
        return target_guard
    target_data = dict(target_guard.data or {}) if isinstance(target_guard.data, dict) else {}
    staging_proof = {
        "mode": "staging_marketplace_mutation",
        "marketplace": marketplace_value,
        "staging_account_id": clean_staging_account_id,
        "target_account_ids": list(target_data.get("target_account_ids") or []),
        "verified_references": list(target_data.get("verified_references") or []),
        "idempotency_key": key,
        "reason": reason,
        "env": STAGING_MARKETPLACE_MUTATION_ENV,
        "timestamp": _utcnow_iso(),
    }
    return Result.ok(
        "Staging marketplace preflight dogrulandi; execute icin hazir.",
        close_dialog=False,
        data={
            "ready": True,
            "action": action,
            "action_type": action_type,
            "idempotency_key": key,
            "staging_proof": staging_proof,
            "target": target_data,
            "api_call_performed": False,
            "db_write_performed": False,
        },
    )


def preflight_staging_marketplace_operation(
    action: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    staging_reason: str = "",
    marketplace: str = "trendyol",
    staging_account_id: str | None = None,
    require_env: bool = True,
) -> Result:
    result = _staging_marketplace_preflight(
        action,
        idempotency_key=idempotency_key,
        staging_reason=staging_reason,
        marketplace=marketplace,
        staging_account_id=staging_account_id,
        require_env=require_env,
    )
    if not result.success:
        return result
    data = dict(result.data or {}) if isinstance(result.data, dict) else {}
    data["action"] = _without_secretish_keys(data.get("action"))
    result.data = data
    return result


def execute_manual_action(
    action: dict[str, Any],
    *,
    approved_by: str = "user",
    idempotency_key: str | None = None,
    audit_path: str | Path | None = None,
) -> Result:
    try:
        action_type = _compact_text(action.get("action_type")) if isinstance(action, dict) else ""
        capability = find_manual_capability(action_type)
        if capability is None:
            return Result.fail("Manuel capability execute icin bulunamadi.", close_dialog=False)

        guard = _approved_action(action, expected_action_type=capability.capability_id)
        if guard is not None:
            return guard

        safe, reasons = _manual_capability_is_execute_safe(capability)
        if not safe:
            return Result.fail(
                f"Manuel capability genel executor icin guvenli degil: {', '.join(reasons)}.",
                close_dialog=False,
                data={"capability": capability.to_dict(), "reasons": reasons},
            )

        key = _compact_text(idempotency_key) or operation_idempotency_key(action, namespace=capability.capability_id)
        previous = _previous_success(key, audit_path=audit_path)
        if previous is not None:
            previous_result = (
                dict(previous.get("result_data") or {})
                if isinstance(previous.get("result_data"), dict)
                else {"value": _jsonable(previous.get("result_data"))}
            )
            previous_verify = (
                dict(previous.get("verify") or {})
                if isinstance(previous.get("verify"), dict)
                else {"value": _jsonable(previous.get("verify"))}
            )
            if capability.capability_id == "ai.action_save_workflow_spec":
                current_payload = _manual_payload_from_action(action)
                if previous.get("payload") != current_payload:
                    return Result.fail("İş kaydetme anahtarı farklı bir onay paketi için kullanıldı.", close_dialog=False,
                                       data={"idempotent": True, "replay_blocked": True})
                fresh_verify = verify_workflow_spec_save(action)
                if not fresh_verify.success:
                    return fresh_verify
                previous_verify = dict(fresh_verify.data or {})
            return Result.ok(
                "Manuel action daha once ayni idempotency key ile tamamlanmis.",
                close_dialog=False,
                data={
                    "idempotent": True,
                    "idempotency_key": key,
                    "audit": previous,
                    "capability": capability.to_dict(),
                    "execute_adapter": bool(previous.get("execute_adapter")),
                    "result": previous_result,
                    "verify": previous_verify,
                },
            )
        previous_attempt = _previous_attempt(key, audit_path=audit_path)
        if previous_attempt is not None and bool(capability.external_write):
            return Result.fail(
                "External write ayni idempotency key ile daha once denendi; sonuc incelenmeden yeniden oynatilamaz.",
                close_dialog=False,
                data={
                    "idempotent": True,
                    "replay_blocked": True,
                    "idempotency_key": key,
                    "previous_status": previous_attempt.get("status"),
                    "api_call_performed": bool(previous_attempt.get("execute_success")),
                    "db_write_performed": bool(previous_attempt.get("execute_success")),
                },
            )

        if capability.capability_id == "labels.action_create_labels_from_selected_orders":
            preflight = verify_labels_create(action, semantic_only=True)
            if not preflight.success:
                data = (
                    dict(preflight.data or {})
                    if isinstance(preflight.data, dict)
                    else {}
                )
                data.update(
                    {
                        "preflight_failed": True,
                        "operation_execute_success": False,
                        "api_call_performed": False,
                        "db_write_performed": False,
                        "file_output_performed": False,
                    }
                )
                return Result.fail(
                    preflight.message,
                    close_dialog=False,
                    data=data,
                )

        payload = _manual_payload_from_action(action)
        call_payload = dict(payload)
        stock_db_name = ""
        if capability.domain == "stock":
            stock_db_name = _compact_text(call_payload.pop("db_name", ""))
        payload_guard = _required_payload_guard(capability, call_payload)
        if payload_guard is not None:
            return payload_guard
        adapter_payload = dict(payload) if capability.domain == "stock" else call_payload
        adapted_result = _execute_manual_adapter(capability, adapter_payload)
        if adapted_result is None:
            func = _callable_for_capability(capability)
            bind_error = _bind_manual_payload(func, call_payload)
            if bind_error is not None:
                return bind_error
            if stock_db_name:
                result = _stock_call_in_db(stock_db_name, func, **call_payload)
            else:
                raw_result = func(**call_payload)
                result = _resolve_manual_return(raw_result)
        else:
            result = adapted_result
        verify = _verify_manual_action_result(capability, action, result)
        entry = {
            "timestamp": _utcnow_iso(),
            "idempotency_key": key,
            "operation": capability.capability_id,
            "approved_by": _compact_text(approved_by) or "user",
            "status": "success" if result.success and verify.success else "failed",
            "execute_success": bool(result.success),
            "action": _without_secretish_keys(action),
            "payload": _without_secretish_keys(payload),
            "result_message": result.message,
            "result_data": _without_secretish_keys(dict(result.data or {})) if isinstance(result.data, dict) else _jsonable(result.data),
            "verify_message": verify.message,
            "verify": _without_secretish_keys(dict(verify.data or {})) if isinstance(verify.data, dict) else _jsonable(verify.data),
            "execute_adapter": capability.capability_id in MANUAL_EXECUTE_ADAPTERS,
        }
        _append_audit_entry(entry, audit_path=audit_path)
        if not result.success:
            return result
        if not verify.success:
            return Result.fail(
                verify.message,
                close_dialog=False,
                data={
                    "idempotency_key": key,
                    "capability": capability.to_dict(),
                    "execute_adapter": capability.capability_id in MANUAL_EXECUTE_ADAPTERS,
                    "result": dict(result.data or {}) if isinstance(result.data, dict) else {"value": _jsonable(result.data)},
                    "verify": dict(verify.data or {}) if isinstance(verify.data, dict) else {"value": _jsonable(verify.data)},
                    "operation_execute_success": True,
                    "api_call_performed": bool(capability.external_write),
                    "db_write_performed": True,
                },
            )
        return Result.ok(
            "Manuel action onayli runtime uzerinden calistirildi.",
            close_dialog=False,
            data={
                "idempotency_key": key,
                "audit": entry,
                "capability": capability.to_dict(),
                "execute_adapter": capability.capability_id in MANUAL_EXECUTE_ADAPTERS,
                "result": dict(result.data or {}) if isinstance(result.data, dict) else {"value": _jsonable(result.data)},
                "verify": dict(verify.data or {}) if isinstance(verify.data, dict) else {"value": _jsonable(verify.data)},
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def execute_manual_read_action(
    *,
    capability_id: str,
    payload: dict[str, Any] | None = None,
    db_name: str | None = None,
    audit_path: str | Path | None = None,
) -> Result:
    try:
        capability = find_manual_capability(capability_id)
        if capability is None:
            return Result.fail("Manuel read capability bulunamadi.", close_dialog=False)
        safe, reasons = _manual_capability_is_read_safe(capability)
        if not safe:
            return Result.fail(
                f"Manuel read capability guvenli read executor icin uygun degil: {', '.join(reasons)}.",
                close_dialog=False,
                data={"capability": capability.to_dict(), "reasons": reasons},
            )
        action_payload = dict(payload or {})
        payload_guard = _required_payload_guard(capability, action_payload)
        if payload_guard is not None:
            return payload_guard
        func = _callable_for_capability(capability)
        clean_db_name = _compact_text(db_name)
        if clean_db_name and "db_name" in set(capability.parameters or []) and not action_payload.get("db_name"):
            action_payload["db_name"] = clean_db_name
        bind_error = _bind_manual_payload(func, action_payload)
        if bind_error is not None:
            return bind_error
        if clean_db_name and capability.domain == "stock":
            previous_db_name = getattr(stock_pipeline, "DB_NAME", None)
            previous_engine = getattr(stock_pipeline, "_ENGINE", None)
            previous_engine_db_name = getattr(stock_pipeline, "_ENGINE_DB_NAME", None)
            try:
                stock_pipeline.DB_NAME = clean_db_name
                if hasattr(stock_pipeline, "_ENGINE"):
                    stock_pipeline._ENGINE = None
                if hasattr(stock_pipeline, "_ENGINE_DB_NAME"):
                    stock_pipeline._ENGINE_DB_NAME = None
                result = _resolve_manual_return(func(**action_payload))
            finally:
                if previous_db_name is not None:
                    stock_pipeline.DB_NAME = previous_db_name
                if hasattr(stock_pipeline, "_ENGINE"):
                    stock_pipeline._ENGINE = previous_engine
                if hasattr(stock_pipeline, "_ENGINE_DB_NAME"):
                    stock_pipeline._ENGINE_DB_NAME = previous_engine_db_name
        else:
            result = _resolve_manual_return(func(**action_payload))
        if not result.success and capability.capability_id == "stock.action_generate_unique_barcode":
            prefix = str(action_payload.get("prefix") or "869")
            result = Result.ok(
                "Veritabani kontrolu yapilamadi; gecici barkod onerisi uretildi.",
                close_dialog=False,
                data={"barcode": _fallback_barcode(prefix), "fallback": True, "prefix": prefix},
            )
        entry = {
            "timestamp": _utcnow_iso(),
            "operation": capability.capability_id,
            "status": "success" if result.success else "failed",
            "mode": "read",
            "payload": action_payload,
            "result_message": result.message,
            "result_data": dict(result.data or {}) if isinstance(result.data, dict) else _jsonable(result.data),
        }
        if audit_path is not None:
            _append_audit_entry(entry, audit_path=audit_path)
        if not result.success:
            return result
        return Result.ok(
            "Manuel read action calistirildi.",
            close_dialog=False,
            data={
                "capability": capability.to_dict(),
                "audit": entry,
                "result": dict(result.data or {}) if isinstance(result.data, dict) else {"value": _jsonable(result.data)},
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_approved_operation(action: dict[str, Any]) -> Result:
    action_type = _compact_text(action.get("action_type")) if isinstance(action, dict) else ""
    if action_type == "ai.action_save_workflow_spec":
        return verify_workflow_spec_save(action)
    if action_type in UNBOUND_EXECUTE_ACTION_TYPES:
        return Result.fail(
            UNBOUND_EXECUTE_ACTION_TYPES[action_type],
            close_dialog=False,
            data={
                "action_type": action_type,
                "execute_enabled": False,
                "execute_adapter_bound": False,
            },
        )
    if action_type == "stock.item_create":
        return verify_stock_item_create(action)
    if action_type == "stock.item_update":
        return verify_stock_item_update(action)
    if action_type in {"orders.change_order_cargo_provider", "orders.change_orders_cargo_provider_bulk"}:
        return verify_order_cargo_provider_change(action)
    if action_type == "labels.action_create_labels_from_selected_orders":
        return verify_labels_create(action)
    if action_type == "labels.mark_orders_extracted_from_label_result":
        return verify_labels_mark_extracted(action)
    if action_type == "orders.approve_return_claim":
        return verify_return_approval(action)
    if action_type == "listing.action_update_approved_content_for_account":
        return Result.fail(
            "Listing icerik mutation verify sonucu yalniz execute sonrasi Trendyol batch sonucundan gelir.",
            close_dialog=False,
            data={"verified": False, "verified_by": "trendyol_batch_result_required"},
        )
    capability = find_manual_capability(action_type)
    if capability is not None:
        safe, reasons = _manual_capability_is_execute_safe(capability)
        if safe:
            payload = _manual_payload_from_action(action)
            payload_guard = _required_payload_guard(capability, payload)
            if payload_guard is not None:
                return payload_guard
            if capability.domain == "finance":
                return verify_finance_manual_action(capability, action, Result.ok("Verify-only finance action.", close_dialog=False))
            return Result.ok(
                "Bu manuel capability icin generic verify, action Result.success auditine dayanir.",
                close_dialog=False,
                data={"capability": capability.to_dict(), "verified_by": "manual_action_result_success"},
            )
        return Result.fail(
            f"Bu manuel capability icin generic verify hazir degil: {', '.join(reasons)}.",
            close_dialog=False,
            data={"capability": capability.to_dict(), "reasons": reasons},
        )
    return Result.fail("Bu action_type icin verify handler bulunamadi.", close_dialog=False)


def execute_approved_operation(
    action: dict[str, Any],
    *,
    approved_by: str = "user",
    idempotency_key: str | None = None,
    audit_path: str | Path | None = None,
) -> Result:
    action_type = _compact_text(action.get("action_type")) if isinstance(action, dict) else ""
    if action_type in UNBOUND_EXECUTE_ACTION_TYPES:
        return Result.fail(
            UNBOUND_EXECUTE_ACTION_TYPES[action_type],
            close_dialog=False,
            data={
                "action_type": action_type,
                "execute_enabled": False,
                "execute_adapter_bound": False,
                "api_call_performed": False,
                "db_write_performed": False,
            },
        )
    if action_type in {"listing.update_price", "listing.update_stock", "listing.content_update"}:
        staging_action = action.get("staging_action") if isinstance(action.get("staging_action"), dict) else {}
        return Result.fail(
            "Listing dry-run dogrudan execute edilmez; gercek pazaryeri mutation icin staging guard gerekir.",
            close_dialog=False,
            data={
                "action_type": action_type,
                "execute_enabled": False,
                "api_call_performed": False,
                "db_write_performed": False,
                "staging_action_type": staging_action.get("action_type"),
                "staging_action_available": bool(staging_action),
            },
        )
    if action_type in {
        "listing.action_update_price_inventory_for_account",
        "listing.action_update_approved_content_for_account",
    }:
        proof = dict(action.get("staging_proof") or {}) if isinstance(action, dict) else {}
        proof_key = _compact_text(proof.get("idempotency_key"))
        expected_key = _compact_text(idempotency_key)
        if (
            proof.get("mode") != "staging_marketplace_mutation"
            or proof.get("env") != STAGING_MARKETPLACE_MUTATION_ENV
            or not expected_key
            or proof_key != expected_key
            or not _truthy_env(STAGING_MARKETPLACE_MUTATION_ENV)
        ):
            return Result.fail(
                "Listing pazaryeri mutation dogrudan execute edilemez; dogrulanmis staging preflight gerekir.",
                close_dialog=False,
                data={
                    "action_type": action_type,
                    "execute_enabled": False,
                    "staging_preflight_verified": False,
                    "api_call_performed": False,
                    "db_write_performed": False,
                },
            )
    if action_type == "stock.item_create":
        return execute_stock_item_create(
            action,
            approved_by=approved_by,
            idempotency_key=idempotency_key,
            audit_path=audit_path,
        )
    if action_type == "stock.item_update":
        return execute_stock_item_update(
            action,
            approved_by=approved_by,
            idempotency_key=idempotency_key,
            audit_path=audit_path,
        )
    if find_manual_capability(action_type) is not None:
        return execute_manual_action(
            action,
            approved_by=approved_by,
            idempotency_key=idempotency_key,
            audit_path=audit_path,
        )
    return Result.fail("Bu action_type icin execute handler bulunamadi.", close_dialog=False)


def execute_staging_marketplace_operation(
    action: dict[str, Any],
    *,
    approved_by: str = "staging",
    idempotency_key: str | None = None,
    audit_path: str | Path | None = None,
    staging_reason: str = "",
    marketplace: str = "trendyol",
    staging_account_id: str | None = None,
) -> Result:
    preflight = _staging_marketplace_preflight(
        action,
        idempotency_key=idempotency_key,
        staging_reason=staging_reason,
        marketplace=marketplace,
        staging_account_id=staging_account_id,
        require_env=True,
    )
    if not preflight.success:
        return preflight
    preflight_data = dict(preflight.data or {}) if isinstance(preflight.data, dict) else {}
    action_type = _compact_text(preflight_data.get("action_type"))
    key = _compact_text(preflight_data.get("idempotency_key"))
    staging_proof = dict(preflight_data.get("staging_proof") or {})
    action_with_proof = dict(preflight_data.get("action") or {})
    action_with_proof["staging_proof"] = staging_proof
    result = execute_approved_operation(
        action_with_proof,
        approved_by=_compact_text(approved_by) or "staging",
        idempotency_key=key,
        audit_path=audit_path,
    )
    data = dict(result.data or {}) if isinstance(result.data, dict) else {"value": _jsonable(result.data)}
    data["staging_proof"] = staging_proof
    result.data = data
    return result


def execute_staging_marketplace_evidence_run(
    action: dict[str, Any],
    *,
    approved_by: str = "staging",
    idempotency_key: str | None = None,
    audit_path: str | Path | None = None,
    evidence_path: str | Path | None = None,
    staging_reason: str = "",
    marketplace: str = "trendyol",
    staging_account_id: str | None = None,
) -> Result:
    evidence_id = _compact_text(idempotency_key) or operation_idempotency_key(_without_secretish_keys(action), namespace="staging-evidence")
    resolved_evidence_path = Path(evidence_path) if evidence_path not in (None, "") else _staging_marketplace_evidence_path(evidence_id)
    resolved_audit_path = Path(audit_path) if audit_path not in (None, "") else AI_DOMAIN_ROOT / "operation_audit.jsonl"
    if resolved_evidence_path.exists():
        return Result.fail(
            "Staging marketplace evidence dosyasi zaten var; overwrite edilmeden validate/attach akisini kullanin veya yeni evidence path secin.",
            close_dialog=False,
            data={
                "artifact_type": "orders_staging_marketplace_evidence",
                "idempotency_key": _compact_text(idempotency_key),
                "staging_account_id": _compact_text(staging_account_id),
                "evidence_path": str(resolved_evidence_path),
                "problems": ["evidence_path_exists"],
                "api_call_performed": False,
                "db_write_performed": False,
            },
        )
    previous = _previous_success(evidence_id, audit_path=resolved_audit_path)
    if previous is not None:
        return Result.fail(
            "Staging marketplace idempotency_key bu audit path icinde daha once basariyla execute edilmis; yeni mutation calistirmadan mevcut evidence'i validate edin veya yeni idempotency_key kullanin.",
            close_dialog=False,
            data={
                "artifact_type": "orders_staging_marketplace_evidence",
                "idempotency_key": evidence_id,
                "staging_account_id": _compact_text(staging_account_id),
                "audit_path": str(resolved_audit_path),
                "problems": ["idempotency_already_executed"],
                "previous_audit": _without_secretish_keys(previous),
                "api_call_performed": False,
                "db_write_performed": False,
            },
        )
    preflight = preflight_staging_marketplace_operation(
        action,
        idempotency_key=idempotency_key,
        staging_reason=staging_reason,
        marketplace=marketplace,
        staging_account_id=staging_account_id,
        require_env=True,
    )

    result: Result
    if preflight.success:
        result = execute_staging_marketplace_operation(
            action,
            approved_by=approved_by,
            idempotency_key=idempotency_key,
            audit_path=resolved_audit_path,
            staging_reason=staging_reason,
            marketplace=marketplace,
            staging_account_id=staging_account_id,
        )
        _redact_staging_marketplace_audit_entries(resolved_audit_path, idempotency_key=evidence_id)
    else:
        result = preflight

    result_data = dict(result.data or {}) if isinstance(result.data, dict) else {"value": _jsonable(result.data)}
    preflight_data = dict(preflight.data or {}) if isinstance(preflight.data, dict) else {"value": _jsonable(preflight.data)}
    operation_execute_success = bool(
        result.success
        or result_data.get("operation_execute_success")
    )
    runtime_verify = dict(result_data.get("verify") or {}) if isinstance(result_data.get("verify"), dict) else {}
    runtime_verify_success = bool(result.success or runtime_verify.get("verified"))
    evidence = {
        "artifact_type": "orders_staging_marketplace_evidence",
        "timestamp": _utcnow_iso(),
        "approved_by": _compact_text(approved_by) or "staging",
        "idempotency_key": _compact_text(idempotency_key),
        "staging_account_id": _compact_text(staging_account_id),
        "marketplace": _compact_text(marketplace).casefold() or "trendyol",
        "env": STAGING_MARKETPLACE_MUTATION_ENV,
        "preflight_success": bool(preflight.success),
        "execute_success": bool(operation_execute_success) if preflight.success else False,
        "runtime_verify_success": bool(runtime_verify_success) if preflight.success else False,
        "message": result.message,
        "action": _redact_staging_marketplace_private_identifiers(_without_secretish_keys(action)),
        "preflight": _redact_staging_marketplace_private_identifiers(_without_secretish_keys(preflight_data)),
        "result": _redact_staging_marketplace_private_identifiers(_without_secretish_keys(result_data)),
        "audit_path": str(resolved_audit_path),
        "api_call_performed": bool(
            preflight.success
            and result_data.get("api_call_performed", result.success)
        ),
        "db_write_performed": bool(
            preflight.success
            and result_data.get("db_write_performed", result.success)
        ),
    }
    resolved_evidence_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_evidence_path.write_text(json.dumps(_jsonable(evidence), ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")

    data = dict(result_data)
    data["evidence_path"] = str(resolved_evidence_path)
    data["evidence"] = evidence
    result.data = data
    return result


def _external_verification_private_findings(payload: Any, *, path: str = "external_verification") -> list[str]:
    findings: list[str] = []
    identifier_pattern = re.compile(r"\b(?:ORD|ORDER|CLAIM|CLM|TRK|TRACK|PKG|SHP)[-_][A-Z0-9][A-Z0-9_-]{3,}\b", re.IGNORECASE)
    email_pattern = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    phone_pattern = re.compile(r"(?:\+?\d[\s().-]*){10,}")
    long_number_pattern = re.compile(r"\b\d{8,}\b")
    private_key_tokens = (
        "customer",
        "musteri",
        "alici",
        "recipient",
        "order_number",
        "ordernumber",
        "claim_id",
        "claimid",
        "tracking",
        "takip",
        "phone",
        "telefon",
        "email",
        "e-posta",
    )
    allowed_identifier_keys = {"idempotency_key", "staging_account_id"}

    def _walk(value: Any, current_path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = _compact_text(key)
                key_cf = key_text.casefold()
                child_path = f"{current_path}.{key_text}" if key_text else current_path
                if any(token in key_cf for token in private_key_tokens):
                    findings.append(f"{child_path}:private_key")
                if key_cf in allowed_identifier_keys:
                    continue
                _walk(child, child_path)
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                _walk(child, f"{current_path}[{index}]")
            return
        if not isinstance(value, str):
            return
        leaf = current_path.rsplit(".", 1)[-1].split("[", 1)[0].casefold()
        if leaf in {
            "timestamp",
            "checked_at",
            "created_at",
            "updated_at",
            "idempotency_key",
            "staging_account_id",
            "target_account_ids",
            "audit_path",
            "evidence_path",
            "proof_template_path",
            "env",
        }:
            return
        text = value.strip()
        if not text:
            return
        if email_pattern.search(text):
            findings.append(f"{current_path}:email")
        if identifier_pattern.search(text):
            findings.append(f"{current_path}:identifier")
        if long_number_pattern.search(text):
            findings.append(f"{current_path}:long_number")
        if phone_pattern.search(text):
            findings.append(f"{current_path}:phone")

    _walk(payload, path)
    return findings


def _external_verification_problems(
    external_verification: dict[str, Any],
    *,
    actual_key: str,
    actual_account: str,
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    if not external_verification:
        problems.append("external_verification")
        return problems, []
    if not bool(external_verification.get("verified")):
        problems.append("external_verification.verified")
    if not bool(external_verification.get("marketplace_state_checked")):
        problems.append("external_verification.marketplace_state_checked")
    if not bool(external_verification.get("operation_matches")):
        problems.append("external_verification.operation_matches")
    if not bool(external_verification.get("staging_account_only")):
        problems.append("external_verification.staging_account_only")
    if actual_account and _compact_text(external_verification.get("staging_account_id")) != actual_account:
        problems.append("external_verification.staging_account_id")
    if actual_key and _compact_text(external_verification.get("idempotency_key")) != actual_key:
        problems.append("external_verification.idempotency_key")
    if not _compact_text(external_verification.get("checked_at")):
        problems.append("external_verification.checked_at")
    if not _compact_text(external_verification.get("checked_by")):
        problems.append("external_verification.checked_by")
    private_findings = _external_verification_private_findings(external_verification)
    if private_findings:
        problems.append("external_verification.private_identifiers")
    return problems, private_findings


def _normalized_external_verification_for_manifest(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return {}
    return _jsonable(_without_secretish_keys(payload))


def _external_verification_manifest_mismatch_keys(
    evidence_external: dict[str, Any],
    external_proof: dict[str, Any],
) -> list[str]:
    evidence_normalized = _normalized_external_verification_for_manifest(evidence_external)
    proof_normalized = _normalized_external_verification_for_manifest(external_proof)
    if evidence_normalized == proof_normalized:
        return []
    keys = sorted(set(evidence_normalized) | set(proof_normalized))
    return [
        key
        for key in keys
        if evidence_normalized.get(key) != proof_normalized.get(key)
    ] or ["external_verification"]


def _staging_marketplace_private_value_findings(payload: Any, *, path: str = "staging_evidence") -> list[str]:
    findings: list[str] = []
    identifier_pattern = re.compile(r"\b(?:ORD|ORDER|CLAIM|CLM|TRK|TRACK|PKG|SHP)[-_][A-Z0-9][A-Z0-9_-]{3,}\b", re.IGNORECASE)
    email_pattern = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    phone_pattern = re.compile(r"(?:\+?\d[\s().-]*){10,}")
    long_number_pattern = re.compile(r"\b\d{8,}\b")

    def _walk(value: Any, current_path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = _compact_text(key)
                _walk(child, f"{current_path}.{key_text}" if key_text else current_path)
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                _walk(child, f"{current_path}[{index}]")
            return
        if not isinstance(value, str):
            return
        leaf = current_path.rsplit(".", 1)[-1].split("[", 1)[0].casefold()
        if leaf in {
            "timestamp",
            "checked_at",
            "created_at",
            "updated_at",
            "idempotency_key",
            "staging_account_id",
            "target_account_ids",
            "audit_path",
            "evidence_path",
            "proof_template_path",
            "env",
        }:
            return
        text = value.strip()
        if not text:
            return
        if email_pattern.search(text):
            findings.append(f"{current_path}:email")
        if identifier_pattern.search(text):
            findings.append(f"{current_path}:identifier")
        if long_number_pattern.search(text):
            findings.append(f"{current_path}:long_number")
        if phone_pattern.search(text):
            findings.append(f"{current_path}:phone")

    _walk(payload, path)
    return findings


def _redact_staging_marketplace_private_identifiers(payload: Any, *, key_path: str = "") -> Any:
    private_key_tokens = (
        "order",
        "claim",
        "tracking",
        "takip",
        "shipment",
        "package",
        "customer",
        "musteri",
        "recipient",
        "phone",
        "telefon",
        "email",
        "e-posta",
        "api_account",
    )
    allowed_keys = {
        "idempotency_key",
        "staging_account_id",
        "target_account_ids",
        "marketplace",
        "mode",
        "env",
        "timestamp",
        "checked_at",
    }

    def _redacted_scalar(value: Any) -> Any:
        if value in (None, ""):
            return value
        return "[redacted]"

    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = _compact_text(key)
            key_cf = key_text.casefold()
            child_path = f"{key_path}.{key_text}" if key_path else key_text
            if key_cf == "verified_references":
                cleaned["verified_references_redacted"] = True
                cleaned["verified_references_count"] = len(list(value or [])) if isinstance(value, (list, tuple)) else 1
                continue
            if key_cf in allowed_keys:
                cleaned[key] = _without_secretish_keys(value)
                continue
            if any(token in key_cf for token in private_key_tokens):
                if isinstance(value, (list, tuple)):
                    cleaned[key] = {"redacted": True, "count": len(list(value))}
                elif isinstance(value, dict):
                    cleaned[key] = {"redacted": True}
                else:
                    cleaned[key] = _redacted_scalar(value)
                continue
            cleaned[key] = _redact_staging_marketplace_private_identifiers(value, key_path=child_path)
        return cleaned
    if isinstance(payload, list):
        return [_redact_staging_marketplace_private_identifiers(item, key_path=f"{key_path}[]") for item in payload]
    if isinstance(payload, tuple):
        return [_redact_staging_marketplace_private_identifiers(item, key_path=f"{key_path}[]") for item in payload]
    if isinstance(payload, str):
        if _staging_marketplace_private_value_findings(payload, path=key_path or "value"):
            return "[redacted]"
    return payload


def _redact_staging_marketplace_audit_entries(audit_path: str | Path, *, idempotency_key: str) -> None:
    path = Path(audit_path)
    if not path.exists() or not path.is_file():
        return
    rewritten: list[str] = []
    changed = False
    key = _compact_text(idempotency_key)
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except Exception:
            rewritten.append(line)
            continue
        if isinstance(entry, dict) and _compact_text(entry.get("idempotency_key")) == key:
            entry = _redact_staging_marketplace_private_identifiers(_without_secretish_keys(entry))
            changed = True
        rewritten.append(json.dumps(_jsonable(entry), ensure_ascii=False, sort_keys=True, default=str))
    if changed:
        path.write_text("\n".join(rewritten) + ("\n" if rewritten else ""), encoding="utf-8")


def staging_marketplace_external_proof_template(
    evidence_path: str | Path,
    *,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
) -> Result:
    try:
        path = Path(evidence_path)
        if not path.exists() or not path.is_file():
            return Result.fail(
                "Staging marketplace evidence dosyasi bulunamadi.",
                close_dialog=False,
                data={"evidence_path": str(path)},
            )
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict):
            return Result.fail(
                "Staging marketplace evidence JSON object degil.",
                close_dialog=False,
                data={"evidence_path": str(path)},
            )
        problems: list[str] = []
        if evidence.get("artifact_type") != "orders_staging_marketplace_evidence":
            problems.append("artifact_type")
        actual_key = _compact_text(evidence.get("idempotency_key"))
        actual_account = _compact_text(evidence.get("staging_account_id"))
        expected_key = _compact_text(idempotency_key)
        expected_account = _compact_text(staging_account_id)
        if expected_key and actual_key != expected_key:
            problems.append("idempotency_key")
        if expected_account and actual_account != expected_account:
            problems.append("staging_account_id")
        if not actual_key:
            problems.append("idempotency_key")
        if not actual_account:
            problems.append("staging_account_id")
        if problems:
            return Result.fail(
                "External verification template uretilemedi.",
                close_dialog=False,
                data={
                    "evidence_path": str(path),
                    "problems": problems,
                    "idempotency_key": actual_key,
                    "staging_account_id": actual_account,
                },
            )
        template = {
            "verified": False,
            "marketplace_state_checked": False,
            "operation_matches": False,
            "staging_account_only": False,
            "staging_account_id": actual_account,
            "idempotency_key": actual_key,
            "checked_at": "",
            "checked_by": "",
            "mutation_summary": "Describe the observed staging marketplace state without order, claim, tracking, customer, email, phone, token, header, or credential values.",
            "privacy_note": "Keep this proof identifier-free except staging_account_id and idempotency_key.",
        }
        private_findings = _external_verification_private_findings(template)
        if private_findings:
            return Result.fail(
                "External verification template ozel veri kontrolunden gecemedi.",
                close_dialog=False,
                data={
                    "evidence_path": str(path),
                    "problems": ["external_verification.private_identifiers"],
                    "external_verification_private_findings": private_findings,
                },
            )
        return Result.ok(
            "External verification template hazirlandi.",
            close_dialog=False,
            data={
                "evidence_path": str(path),
                "template": template,
                "idempotency_key": actual_key,
                "staging_account_id": actual_account,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def attach_staging_marketplace_external_proof(
    evidence_path: str | Path,
    external_verification: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
    overwrite: bool = False,
) -> Result:
    try:
        path = Path(evidence_path)
        if not path.exists() or not path.is_file():
            return Result.fail(
                "Staging marketplace evidence dosyasi bulunamadi.",
                close_dialog=False,
                data={"verified": False, "evidence_path": str(path)},
            )
        if not isinstance(external_verification, dict):
            return Result.fail(
                "External verification JSON object olmali.",
                close_dialog=False,
                data={"verified": False, "evidence_path": str(path)},
            )
        private_findings = _external_verification_private_findings(external_verification)
        if private_findings:
            return Result.fail(
                "External verification yerel siparis/musteri/takip gibi ozel veri icermemeli.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(path),
                    "problems": ["external_verification.private_identifiers"],
                    "external_verification_private_findings": private_findings,
                },
            )
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict):
            return Result.fail(
                "Staging marketplace evidence JSON object degil.",
                close_dialog=False,
                data={"verified": False, "evidence_path": str(path)},
            )
        existing_external = evidence.get("external_verification")
        if isinstance(existing_external, dict) and existing_external and not overwrite:
            return Result.fail(
                "External verification evidence icinde zaten var; overwrite edilmeden validate/manifest akisini kullanin veya acik overwrite isteyin.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(path),
                    "problems": ["external_verification_exists"],
                },
            )
        base_validation = verify_staging_marketplace_evidence_artifact(
            path,
            idempotency_key=idempotency_key,
            staging_account_id=staging_account_id,
            require_external_verification=False,
        )
        if not base_validation.success:
            return Result.fail(
                "External verification yalnizca temel staging evidence dogrulaninca eklenir.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(path),
                    "problems": (base_validation.data or {}).get("problems") if isinstance(base_validation.data, dict) else [],
                    "base_validation": base_validation.data if isinstance(base_validation.data, dict) else {"value": base_validation.data},
                },
            )
        actual_key = _compact_text(evidence.get("idempotency_key"))
        actual_account = _compact_text(evidence.get("staging_account_id"))
        problems: list[str] = []
        expected_key = _compact_text(idempotency_key)
        expected_account = _compact_text(staging_account_id)
        if not actual_key:
            problems.append("idempotency_key")
        if expected_key and actual_key != expected_key:
            problems.append("idempotency_key")
        if not actual_account:
            problems.append("staging_account_id")
        if expected_account and actual_account != expected_account:
            problems.append("staging_account_id")
        proof_problems, proof_private_findings = _external_verification_problems(
            external_verification,
            actual_key=actual_key,
            actual_account=actual_account,
        )
        problems.extend(proof_problems)
        if problems:
            return Result.fail(
                "External verification staging evidence ile eslesmedi.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(path),
                    "problems": sorted(set(problems)),
                    "idempotency_key": actual_key,
                    "staging_account_id": actual_account,
                    "external_verification_private_findings": proof_private_findings,
                },
            )
        evidence["external_verification"] = _without_secretish_keys(external_verification)
        path.write_text(json.dumps(_jsonable(evidence), ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return verify_staging_marketplace_evidence_artifact(
            path,
            idempotency_key=idempotency_key,
            staging_account_id=staging_account_id,
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _contains_secretish_key(payload: Any) -> bool:
    blocked = {"api_key", "api_secret", "token", "authorization", "headers", "accounts", "comp_api_account_list"}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _compact_text(key).casefold() in blocked:
                return True
            if _contains_secretish_key(value):
                return True
    if isinstance(payload, list):
        return any(_contains_secretish_key(item) for item in payload)
    if isinstance(payload, tuple):
        return any(_contains_secretish_key(item) for item in payload)
    return False


def verify_staging_marketplace_evidence_artifact(
    evidence_path: str | Path,
    *,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
    require_audit_entry: bool = True,
    require_external_verification: bool = True,
) -> Result:
    try:
        path = Path(evidence_path)
        if not path.exists() or not path.is_file():
            return Result.fail(
                "Staging marketplace evidence dosyasi bulunamadi.",
                close_dialog=False,
                data={"verified": False, "evidence_path": str(path)},
            )
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict):
            return Result.fail("Staging marketplace evidence JSON object degil.", close_dialog=False, data={"verified": False, "evidence_path": str(path)})
        problems: list[str] = []
        if evidence.get("artifact_type") != "orders_staging_marketplace_evidence":
            problems.append("artifact_type")
        action = dict(evidence.get("action") or {}) if isinstance(evidence.get("action"), dict) else {}
        action_type = _compact_text(action.get("action_type"))
        if action_type not in STAGING_MARKETPLACE_ACTION_TYPES:
            problems.append("action.action_type")
        if not bool(evidence.get("preflight_success")):
            problems.append("preflight_success")
        if not bool(evidence.get("execute_success")):
            problems.append("execute_success")
        if not bool(evidence.get("api_call_performed")):
            problems.append("api_call_performed")
        if not bool(evidence.get("db_write_performed")):
            problems.append("db_write_performed")
        expected_key = _compact_text(idempotency_key)
        actual_key = _compact_text(evidence.get("idempotency_key"))
        if not actual_key:
            problems.append("idempotency_key")
        if expected_key and actual_key != expected_key:
            problems.append("idempotency_key")
        expected_account = _compact_text(staging_account_id)
        actual_account = _compact_text(evidence.get("staging_account_id"))
        if not actual_account:
            problems.append("staging_account_id")
        if expected_account and actual_account != expected_account:
            problems.append("staging_account_id")
        result_data = dict(evidence.get("result") or {}) if isinstance(evidence.get("result"), dict) else {}
        staging_proof = dict(result_data.get("staging_proof") or {}) if isinstance(result_data.get("staging_proof"), dict) else {}
        target_accounts = [_compact_text(value) for value in list(staging_proof.get("target_account_ids") or []) if _compact_text(value)]
        if actual_account and target_accounts != [actual_account]:
            problems.append("target_account_ids")
        if actual_key and _compact_text(staging_proof.get("idempotency_key")) != actual_key:
            problems.append("staging_proof.idempotency_key")
        verify_data = dict(result_data.get("verify") or {}) if isinstance(result_data.get("verify"), dict) else {}
        if not bool(verify_data.get("verified")):
            problems.append("verify.verified")
        external_verification = dict(evidence.get("external_verification") or {}) if isinstance(evidence.get("external_verification"), dict) else {}
        external_private_findings: list[str] = []
        if require_external_verification:
            external_problems, external_private_findings = _external_verification_problems(
                external_verification,
                actual_key=actual_key,
                actual_account=actual_account,
            )
            problems.extend(external_problems)
        if _contains_secretish_key(evidence):
            problems.append("secretish_keys")
        staging_private_findings = _staging_marketplace_private_value_findings(evidence)
        if staging_private_findings:
            problems.append("staging_private_identifiers")

        audit_verified = False
        audit_path = Path(_compact_text(evidence.get("audit_path")))
        if require_audit_entry:
            if not audit_path.exists() or not audit_path.is_file():
                problems.append("audit_path")
            else:
                for entry in _read_audit_entries(audit_path):
                    if _compact_text(entry.get("idempotency_key")) != actual_key:
                        continue
                    proof = dict(entry.get("staging_proof") or {}) if isinstance(entry.get("staging_proof"), dict) else {}
                    if not proof and isinstance(entry.get("action"), dict):
                        proof = dict((entry.get("action") or {}).get("staging_proof") or {})
                    if _compact_text(proof.get("staging_account_id")) == actual_account and entry.get("status") == "success":
                        audit_verified = True
                        break
                if not audit_verified:
                    problems.append("audit_entry")

        if problems:
            return Result.fail(
                "Staging marketplace evidence dogrulanamadi.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(path),
                    "problems": problems,
                    "idempotency_key": actual_key,
                    "staging_account_id": actual_account,
                    "action_type": action_type,
                    "audit_path": str(audit_path) if _compact_text(audit_path) else "",
                    "staging_private_findings": staging_private_findings,
                    "external_verification_private_findings": external_private_findings,
                },
            )
        return Result.ok(
            "Staging marketplace evidence artifact dogrulandi.",
            close_dialog=False,
            data={
                "verified": True,
                "evidence_path": str(path),
                "idempotency_key": actual_key,
                "staging_account_id": actual_account,
                "action_type": action_type,
                "target_account_ids": target_accounts,
                "audit_path": str(audit_path),
                "audit_verified": bool(audit_verified or not require_audit_entry),
                "external_verified": True,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def staging_marketplace_evidence_manifest(
    evidence_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    external_proof_path: str | Path | None = None,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
    overwrite: bool = False,
) -> Result:
    try:
        verified = verify_staging_marketplace_evidence_artifact(
            evidence_path,
            idempotency_key=idempotency_key,
            staging_account_id=staging_account_id,
        )
        if not verified.success:
            return Result.fail(
                "Manifest yalnizca dogrulanmis staging marketplace evidence icin uretilir.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(evidence_path),
                    "validation": verified.data if isinstance(verified.data, dict) else {"value": verified.data},
                },
            )
        validation = dict(verified.data or {}) if isinstance(verified.data, dict) else {}
        evidence_file = Path(evidence_path)
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
        external_proof_text = _compact_text(external_proof_path)
        if not external_proof_text:
            return Result.fail(
                "Manifest icin external proof dosyasi gerekir.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(evidence_file),
                    "problems": ["external_proof_path"],
                },
            )
        external_proof_file = Path(external_proof_text)
        if not external_proof_file.exists() or not external_proof_file.is_file():
            return Result.fail(
                "Manifest icin external proof dosyasi bulunamadi.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(evidence_file),
                    "external_proof_path": str(external_proof_file),
                    "problems": ["external_proof_path"],
                },
            )
        external_proof = json.loads(external_proof_file.read_text(encoding="utf-8"))
        if not isinstance(external_proof, dict):
            return Result.fail(
                "Manifest external proof JSON object olmali.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(evidence_file),
                    "external_proof_path": str(external_proof_file),
                    "problems": ["external_proof_json"],
                },
            )
        evidence_external = dict(evidence.get("external_verification") or {}) if isinstance(evidence.get("external_verification"), dict) else {}
        external_private_findings = _external_verification_private_findings(external_proof)
        mismatch_keys = _external_verification_manifest_mismatch_keys(evidence_external, external_proof)
        if external_private_findings or mismatch_keys:
            problems = []
            if external_private_findings:
                problems.append("external_proof.private_identifiers")
            if mismatch_keys:
                problems.append("external_proof.content_mismatch")
            return Result.fail(
                "Manifest external proof dosyasi evidence ile eslesmedi.",
                close_dialog=False,
                data={
                    "verified": False,
                    "evidence_path": str(evidence_file),
                    "external_proof_path": str(external_proof_file),
                    "problems": problems,
                    "external_verification_private_findings": external_private_findings,
                    "mismatch_keys": mismatch_keys,
                },
            )
        files: list[dict[str, Any]] = []

        def _add_file(label: str, path_value: str | Path | None) -> None:
            text = _compact_text(path_value)
            if not text:
                return
            path = Path(text)
            if not path.exists() or not path.is_file():
                return
            body = path.read_bytes()
            files.append(
                {
                    "label": label,
                    "path": str(path),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "bytes": len(body),
                }
            )

        _add_file("evidence", evidence_file)
        _add_file("audit", evidence.get("audit_path"))
        _add_file("external_proof", external_proof_file)
        manifest = {
            "artifact_type": "orders_staging_marketplace_evidence_manifest",
            "generated_at": _utcnow_iso(),
            "idempotency_key": _compact_text(validation.get("idempotency_key")),
            "staging_account_id": _compact_text(validation.get("staging_account_id")),
            "action_type": _compact_text(validation.get("action_type")),
            "evidence_path": str(evidence_file),
            "evidence_validation": validation,
            "files": files,
        }
        target = Path(manifest_path) if manifest_path not in (None, "") else evidence_file.with_suffix(".manifest.json")
        if target.exists() and not overwrite:
            return Result.fail(
                "Staging marketplace evidence manifest dosyasi zaten var; overwrite edilmeden verify-manifest kullanin veya acik overwrite isteyin.",
                close_dialog=False,
                data={
                    "verified": False,
                    "manifest_path": str(target),
                    "evidence_path": str(evidence_file),
                    "problems": ["manifest_path_exists"],
                },
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(_jsonable(manifest), ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return Result.ok(
            "Staging marketplace evidence manifest hazirlandi.",
            close_dialog=False,
            data={**manifest, "manifest_path": str(target)},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_staging_marketplace_evidence_manifest(
    manifest_path: str | Path,
    *,
    evidence_path: str | Path | None = None,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
) -> Result:
    try:
        path = Path(manifest_path)
        if not path.exists() or not path.is_file():
            return Result.fail(
                "Staging marketplace evidence manifest dosyasi bulunamadi.",
                close_dialog=False,
                data={"verified": False, "manifest_path": str(path)},
            )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return Result.fail(
                "Staging marketplace evidence manifest JSON object degil.",
                close_dialog=False,
                data={"verified": False, "manifest_path": str(path)},
            )
        problems: list[str] = []
        if manifest.get("artifact_type") != "orders_staging_marketplace_evidence_manifest":
            problems.append("artifact_type")
        expected_key = _compact_text(idempotency_key)
        actual_key = _compact_text(manifest.get("idempotency_key"))
        if not actual_key:
            problems.append("idempotency_key")
        if expected_key and actual_key != expected_key:
            problems.append("idempotency_key")
        expected_account = _compact_text(staging_account_id)
        actual_account = _compact_text(manifest.get("staging_account_id"))
        if not actual_account:
            problems.append("staging_account_id")
        if expected_account and actual_account != expected_account:
            problems.append("staging_account_id")

        explicit_evidence_text = _compact_text(evidence_path)
        manifest_evidence_text = _compact_text(manifest.get("evidence_path"))
        evidence_text = explicit_evidence_text or manifest_evidence_text
        if not evidence_text:
            problems.append("evidence_path")
        elif explicit_evidence_text and (not manifest_evidence_text or not _same_filesystem_path(explicit_evidence_text, manifest_evidence_text)):
            problems.append("evidence_path")

        validation = dict(manifest.get("evidence_validation") or {}) if isinstance(manifest.get("evidence_validation"), dict) else {}
        if not bool(validation.get("verified")):
            problems.append("evidence_validation.verified")
        if actual_key and _compact_text(validation.get("idempotency_key")) != actual_key:
            problems.append("evidence_validation.idempotency_key")
        if actual_account and _compact_text(validation.get("staging_account_id")) != actual_account:
            problems.append("evidence_validation.staging_account_id")
        action_type = _compact_text(validation.get("action_type"))
        if action_type not in STAGING_MARKETPLACE_ACTION_TYPES:
            problems.append("evidence_validation.action_type")

        evidence_external_verification: dict[str, Any] = {}
        if evidence_text:
            try:
                evidence_payload = json.loads(Path(evidence_text).read_text(encoding="utf-8"))
                if isinstance(evidence_payload, dict) and isinstance(evidence_payload.get("external_verification"), dict):
                    evidence_external_verification = dict(evidence_payload.get("external_verification") or {})
            except Exception:
                evidence_external_verification = {}

        file_rows = [dict(row) for row in list(manifest.get("files") or []) if isinstance(row, dict)]
        by_label = {_compact_text(row.get("label")): row for row in file_rows if _compact_text(row.get("label"))}
        required_labels = ("evidence", "audit", "external_proof")
        for label in required_labels:
            row = by_label.get(label)
            if not row:
                problems.append(f"files.{label}")
                continue
            file_path_text = _compact_text(row.get("path"))
            if not file_path_text:
                problems.append(f"files.{label}.path")
                continue
            file_path = Path(file_path_text)
            if not file_path.exists() or not file_path.is_file():
                problems.append(f"files.{label}.path")
                continue
            if label == "evidence" and evidence_text and not _same_filesystem_path(file_path, evidence_text):
                problems.append("files.evidence.path_mismatch")
            body = file_path.read_bytes()
            if label == "external_proof":
                try:
                    external_proof_payload = json.loads(body.decode("utf-8"))
                except Exception:
                    external_proof_payload = None
                if not isinstance(external_proof_payload, dict):
                    problems.append("files.external_proof.json")
                else:
                    if _external_verification_private_findings(external_proof_payload):
                        problems.append("files.external_proof.private_identifiers")
                    if evidence_external_verification:
                        mismatch_keys = _external_verification_manifest_mismatch_keys(
                            evidence_external_verification,
                            external_proof_payload,
                        )
                        if mismatch_keys:
                            problems.append("files.external_proof.content_mismatch")
            if _compact_text(row.get("sha256")) != hashlib.sha256(body).hexdigest():
                problems.append(f"files.{label}.sha256")
            try:
                expected_size = int(row.get("bytes"))
            except Exception:
                expected_size = -1
            if expected_size != len(body):
                problems.append(f"files.{label}.bytes")

        evidence_verified = False
        evidence_validation_result: dict[str, Any] | None = None
        if evidence_text:
            verified = verify_staging_marketplace_evidence_artifact(
                evidence_text,
                idempotency_key=actual_key or idempotency_key,
                staging_account_id=actual_account or staging_account_id,
            )
            evidence_verified = bool(verified.success)
            evidence_validation_result = verified.data if isinstance(verified.data, dict) else {"value": verified.data}
            if not evidence_verified:
                problems.append("evidence_current_validation")

        if problems:
            return Result.fail(
                "Staging marketplace evidence manifest dogrulanamadi.",
                close_dialog=False,
                data={
                    "verified": False,
                    "manifest_path": str(path),
                    "evidence_path": evidence_text,
                    "idempotency_key": actual_key,
                    "staging_account_id": actual_account,
                    "action_type": action_type,
                    "problems": problems,
                    "evidence_validation": evidence_validation_result or validation,
                },
            )
        return Result.ok(
            "Staging marketplace evidence manifest dogrulandi.",
            close_dialog=False,
            data={
                "verified": True,
                "manifest_path": str(path),
                "evidence_path": evidence_text,
                "idempotency_key": actual_key,
                "staging_account_id": actual_account,
                "action_type": action_type,
                "files": file_rows,
                "evidence_verified": evidence_verified,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def operation_coverage_report() -> dict[str, Any]:
    capabilities = list_manual_capabilities()
    operation_contracts: list[dict[str, Any]] = []
    operation_contract_problems: list[dict[str, Any]] = []
    for capability in capabilities:
        try:
            metadata = capability.operation_metadata().to_dict()
            operation_contracts.append(
                {
                    "capability_id": capability.capability_id,
                    "domain": capability.domain,
                    "metadata": metadata,
                }
            )
        except Exception as exc:
            operation_contract_problems.append(
                {
                    "capability_id": capability.capability_id,
                    "domain": capability.domain,
                    "problem": str(exc),
                }
            )
    write_capabilities = [capability for capability in capabilities if capability.mode == "write"]
    read_capabilities = [capability for capability in capabilities if capability.mode == "read"]
    generic_safe: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for capability in write_capabilities:
        safe, reasons = _manual_capability_is_execute_safe(capability)
        row = capability.to_dict()
        if capability.capability_id in MANUAL_EXECUTE_ADAPTERS:
            row["execute_adapter"] = MANUAL_EXECUTE_ADAPTERS[capability.capability_id]
        if safe:
            generic_safe.append(row)
        else:
            row["blocked_reasons"] = reasons
            blocked.append(row)
    read_safe: list[dict[str, Any]] = []
    read_blocked: list[dict[str, Any]] = []
    for capability in read_capabilities:
        safe, reasons = _manual_capability_is_read_safe(capability)
        row = capability.to_dict()
        if safe:
            read_safe.append(row)
        else:
            row["blocked_reasons"] = reasons
            read_blocked.append(row)
    domains: dict[str, dict[str, Any]] = {}
    for capability in capabilities:
        bucket = domains.setdefault(
            capability.domain,
            {
                "total": 0,
                "read_total": 0,
                "write_total": 0,
                "capability_ids": [],
                "read_capability_ids": [],
                "write_capability_ids": [],
                "generic_execute_safe_ids": [],
                "generic_execute_blocked_ids": [],
                "generic_read_safe_ids": [],
                "generic_read_blocked_ids": [],
                "operation_contract_ids": [],
                "operation_contract_problem_ids": [],
            },
        )
        bucket["total"] += 1
        bucket["capability_ids"].append(capability.capability_id)
        if capability.mode == "write":
            bucket["write_total"] += 1
            bucket["write_capability_ids"].append(capability.capability_id)
        else:
            bucket["read_total"] += 1
            bucket["read_capability_ids"].append(capability.capability_id)
    for key, rows in (
        ("generic_execute_safe_ids", generic_safe),
        ("generic_execute_blocked_ids", blocked),
        ("generic_read_safe_ids", read_safe),
        ("generic_read_blocked_ids", read_blocked),
    ):
        for row in rows:
            domain = _compact_text(row.get("domain"))
            capability_id = _compact_text(row.get("capability_id"))
            if domain in domains and capability_id:
                domains[domain][key].append(capability_id)
    for row in operation_contracts:
        domain = _compact_text(row.get("domain"))
        capability_id = _compact_text(row.get("capability_id"))
        if domain in domains and capability_id:
            domains[domain]["operation_contract_ids"].append(capability_id)
    for row in operation_contract_problems:
        domain = _compact_text(row.get("domain"))
        capability_id = _compact_text(row.get("capability_id"))
        if domain in domains and capability_id:
            domains[domain]["operation_contract_problem_ids"].append(capability_id)
    for bucket in domains.values():
        for key, value in list(bucket.items()):
            if key.endswith("_ids") and isinstance(value, list):
                bucket[key] = sorted(value)
    return {
        "manual_total": len(capabilities),
        "operation_contract_total": len(operation_contracts) + len(operation_contract_problems),
        "operation_contract_valid_total": len(operation_contracts),
        "operation_contract_invalid_total": len(operation_contract_problems),
        "operation_contract_problems": operation_contract_problems,
        "manual_write_total": len(write_capabilities),
        "manual_read_total": len(read_capabilities),
        "domains": domains,
        "specialized_execute_total": len(SPECIALIZED_EXECUTE_ACTION_TYPES),
        "specialized_execute_action_types": dict(SPECIALIZED_EXECUTE_ACTION_TYPES),
        "unbound_execute_total": len(UNBOUND_EXECUTE_ACTION_TYPES),
        "unbound_execute_action_types": dict(UNBOUND_EXECUTE_ACTION_TYPES),
        "manual_execute_adapter_total": len(MANUAL_EXECUTE_ADAPTERS),
        "manual_execute_adapters": dict(MANUAL_EXECUTE_ADAPTERS),
        "generic_execute_safe_total": len(generic_safe),
        "generic_execute_blocked_total": len(blocked),
        "generic_read_safe_total": len(read_safe),
        "generic_read_blocked_total": len(read_blocked),
        "generic_execute_safe": generic_safe,
        "generic_execute_blocked": blocked,
        "generic_read_safe": read_safe,
        "generic_read_blocked": read_blocked,
    }
