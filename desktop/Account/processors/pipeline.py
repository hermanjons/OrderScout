from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import httpx
from sqlalchemy import delete, or_
from sqlmodel import Session, select

from Account.constants import (
    ACCOUNT_CREATE_FIELDS,
    ACCOUNT_DELETE_CHUNK_SIZE,
    ACCOUNT_EMPTY_TO_NONE_FIELDS,
    ACCOUNT_HEALTH_BATCH_CONCURRENCY,
    ACCOUNT_HEALTH_GATHER_BATCH_SIZE,
    ACCOUNT_HEALTH_IDENTITY_FIELDS,
    ACCOUNT_LOGO_ALLOWED_EXTENSIONS,
    ACCOUNT_REQUIRED_FIELD_MESSAGES,
    ACCOUNT_REQUIRED_IDENTITY_FIELDS,
    ACCOUNT_UPDATE_FIELDS,
    account_platform_code,
)
from Account.constants.paths import company_logos_dir
from Account.models.models import ApiAccount
from Account.signals.signals import account_signals
from Core.processors.credential_store import (
    coalesce_credential_bundle_reference,
    resolve_credential_bundle,
)
from Core.utils.request_utils import async_make_request
from Core.utils.model_utils import (
    create_records,
    get_engine,
    get_records,
    make_normalizer,
)
from Feedback.processors.pipeline import Result, map_error_to_message
from Marketplaces.constants.catalog_constants import marketplace_db_id_for_code
from Marketplaces.constants.catalog_constants import (
    marketplace_account_health_profile,
    marketplace_account_profile,
    normalize_marketplace_environment,
)
from Orders.signals.signals import order_signals
from settings import DB_NAME

def _normalize_account_platform_fields(record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record or {})
    platform_code = account_platform_code(row.get("platform"))
    if platform_code:
        row["platform"] = platform_code
    elif "platform" in row and isinstance(row.get("platform"), str):
        row["platform"] = row["platform"].strip().upper()
    return row


account_normalizer = make_normalizer(
    strip_strings=True,
    extra=_normalize_account_platform_fields,
)

account_update_normalizer = make_normalizer(
    strip_strings=True,
    extra=_normalize_account_platform_fields,
)


def _engine(db_name: str | None = None):
    return get_engine(db_name or DB_NAME)


def _coalesce_account_empty_values(payload: Dict[str, Any]) -> dict[str, Any]:
    row = dict(payload or {})
    for field_name, default_value in ACCOUNT_EMPTY_TO_NONE_FIELDS.items():
        if field_name not in row:
            continue
        if row.get(field_name) in (None, ""):
            row[field_name] = default_value
    return row


def _sanitize_account_payload(payload: Dict[str, Any], *, allowed_fields: frozenset[str], normalizer) -> dict[str, Any]:
    row = normalizer(dict(payload or {}))
    row = _coalesce_account_empty_values(row)
    return {key: value for key, value in row.items() if key in allowed_fields}


def _validate_account_payload(payload: Dict[str, Any], *, partial: bool) -> Result:
    if not payload:
        return Result.fail("İşlenecek geçerli şirket verisi bulunamadı.", close_dialog=False)

    extra_config = payload.get("extra_config")
    if extra_config is not None and not isinstance(extra_config, dict):
        return Result.fail("Extra Config bir JSON nesnesi olmalıdır.", close_dialog=False)

    required_fields = ACCOUNT_REQUIRED_IDENTITY_FIELDS if not partial else tuple(
        field_name for field_name in ACCOUNT_REQUIRED_IDENTITY_FIELDS if field_name in payload
    )
    for field_name in required_fields:
        if str(payload.get(field_name) or "").strip():
            continue
        return Result.fail(ACCOUNT_REQUIRED_FIELD_MESSAGES[field_name], close_dialog=False)

    platform = payload.get("platform")
    if platform is not None:
        platform_code = account_platform_code(platform)
        if not platform_code:
            return Result.fail(f"Geçersiz platform: {platform}", close_dialog=False)
        payload["platform"] = platform_code

    return Result.ok("Şirket payload doğrulandı.", close_dialog=False)


def _prepare_account_create_payload(payload: Dict[str, Any]) -> tuple[dict[str, Any], Result]:
    sanitized = _sanitize_account_payload(
        payload,
        allowed_fields=ACCOUNT_CREATE_FIELDS,
        normalizer=account_normalizer,
    )
    validation = _validate_account_payload(sanitized, partial=False)
    if validation.success:
        platform_code = str(sanitized.get("platform") or "").strip().upper()
        platform_id = marketplace_db_id_for_code(platform_code, db_name=DB_NAME)
        if not platform_id:
            validation = Result.fail(f"Geçersiz platform: {platform_code}", close_dialog=False)
        else:
            sanitized["platform_id"] = platform_id
    return sanitized, validation


def _prepare_account_update_payload(payload: Dict[str, Any]) -> tuple[dict[str, Any], Result]:
    sanitized = _sanitize_account_payload(
        payload,
        allowed_fields=ACCOUNT_UPDATE_FIELDS,
        normalizer=account_update_normalizer,
    )
    validation = _validate_account_payload(sanitized, partial=True)
    if validation.success and "platform" in sanitized:
        platform_code = str(sanitized.get("platform") or "").strip().upper()
        platform_id = marketplace_db_id_for_code(platform_code, db_name=DB_NAME)
        if not platform_id:
            validation = Result.fail(f"Geçersiz platform: {platform_code}", close_dialog=False)
        else:
            sanitized["platform_id"] = platform_id
    return sanitized, validation


def _account_field_value(value: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _health_identity_changed(account: ApiAccount, update_data: Dict[str, Any]) -> bool:
    for field_name in ACCOUNT_HEALTH_IDENTITY_FIELDS:
        if field_name not in update_data:
            continue
        if _account_field_value(update_data.get(field_name)) != _account_field_value(getattr(account, field_name, None)):
            return True
    return False


def _changed_account_fields(account: ApiAccount, update_data: Dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for field_name, value in update_data.items():
        if _account_field_value(value) == _account_field_value(getattr(account, field_name, None)):
            continue
        changed[field_name] = value
    return changed


def _accounts_payload(records: List[ApiAccount], include_last_used_at: bool = False) -> List[list]:
    payload: List[list] = []
    for record in records:
        row = [record.pk, record.api_key, record.api_secret, str(record.account_id)]
        row.append(getattr(record, "last_used_at", None) if include_last_used_at else None)
        row.append(dict(getattr(record, "extra_config", None) or {}))
        payload.append(row)
    return payload


def _emit_company_changed() -> None:
    try:
        account_signals.company_changed.emit()
    except Exception as exc:
        map_error_to_message(exc)


def _emit_orders_changed() -> None:
    try:
        order_signals.orders_changed.emit()
    except Exception as exc:
        map_error_to_message(exc)


def _run_async_result(coro) -> Result:
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(coro)
        if isinstance(res, Result):
            return res
        return Result.fail("API doğrulama sonucu geçersiz.", close_dialog=False)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
    finally:
        if loop is not None:
            try:
                from Core.utils.request_utils import close_async_request_clients

                loop.run_until_complete(close_async_request_clients())
            except Exception:
                pass
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass
        asyncio.set_event_loop(None)


def _account_health_payload(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        payload = row
    else:
        payload = {
            "pk": getattr(row, "pk", None),
            "comp_name": getattr(row, "comp_name", None),
            "platform": getattr(row, "platform", None),
            "account_id": getattr(row, "account_id", None),
            "api_key": getattr(row, "api_key", None),
            "api_secret": getattr(row, "api_secret", None),
            "integration_code": getattr(row, "integration_code", None),
            "token": getattr(row, "token", None),
            "extra_config": getattr(row, "extra_config", None),
        }

    return {
        "pk": payload.get("pk"),
        "comp_name": payload.get("comp_name"),
        "platform": payload.get("platform"),
        "account_id": payload.get("account_id"),
        "api_key": payload.get("api_key"),
        "api_secret": payload.get("api_secret"),
        "integration_code": payload.get("integration_code"),
        "token": payload.get("token"),
        "extra_config": payload.get("extra_config") if isinstance(payload.get("extra_config"), dict) else None,
    }


def _health_context(
    *,
    platform: str,
    account_id: str,
    api_key: str | None,
    api_secret: str | None,
    integration_code: str | None,
    token: str | None,
    extra_config: dict | None,
    credential_reference: str | None = None,
) -> dict[str, Any]:
    extra = dict(extra_config or {})
    reference = str(
        credential_reference
        or extra.get("credential_reference")
        or extra.get("credential_ref")
        or ""
    ).strip()
    key_value = str(api_key or "").strip()
    secret_value = str(api_secret or "").strip()
    reference, key_value = coalesce_credential_bundle_reference(
        reference,
        key_value,
        companion_value=secret_value,
    )
    bundle = resolve_credential_bundle(reference) if reference else {}

    context: dict[str, Any] = {
        "platform": str(platform or "").strip(),
        "account_id": str(account_id or "").strip(),
        "seller_id": str(account_id or "").strip(),
        "api_key": key_value or str(bundle.get("api_key") or "").strip(),
        "api_secret": secret_value or str(bundle.get("api_secret") or "").strip(),
        "integration_code": str(integration_code or bundle.get("integration_code") or "").strip(),
        "token": str(token or bundle.get("token") or "").strip(),
        "credential_reference": reference,
        "_credential_bundle_seller_id": str(
            bundle.get("seller_id")
            or bundle.get("supplier_id")
            or bundle.get("account_id")
            or ""
        ).strip(),
    }
    for key, value in extra.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            context[str(key)] = value
    return context


class _SafeTemplateDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _render_health_template(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        try:
            return value.format_map(_SafeTemplateDict(context))
        except Exception:
            return value
    if isinstance(value, dict):
        return {str(key): _render_health_template(raw, context) for key, raw in value.items()}
    if isinstance(value, list):
        return [_render_health_template(item, context) for item in value]
    return value


def _missing_health_credentials(profile: dict[str, Any], context: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    platform_code = str(profile.get("platformCode") or context.get("platform") or "").strip()
    field_labels = dict((marketplace_account_profile(platform_code) or {}).get("fieldLabels") or {})
    for field_name in list(profile.get("requiredCredentials") or []):
        if str(context.get(field_name) or "").strip():
            continue
        missing.append(str(field_labels.get(field_name) or field_name))
    return missing


def _health_auth_for_profile(profile: dict[str, Any], context: dict[str, Any]) -> Any:
    strategy = str(profile.get("authStrategy") or "none").strip().casefold()
    if strategy in {"", "none"}:
        return None
    if strategy == "basic_api_key_secret":
        return httpx.BasicAuth(
            str(context.get("api_key") or "").strip(),
            str(context.get("api_secret") or "").strip(),
        )
    return None


def _status_message_for_profile(profile: dict[str, Any], status_code: int | None) -> str:
    messages = dict(profile.get("statusMessages") or {})
    if status_code is None:
        return str(messages.get("*") or "API bağlantı kontrolü başarısız.")
    return str(messages.get(str(int(status_code))) or messages.get("*") or f"API bağlantı kontrolü başarısız (HTTP {int(status_code)}).")


async def _check_company_api_health_async(
    *,
    platform: str,
    account_id: str,
    api_key: str | None,
    api_secret: str | None,
    integration_code: str | None = None,
    token: str | None = None,
    extra_config: dict | None = None,
    environment: str | None = None,
    credential_reference: str | None = None,
) -> Result:
    try:
        platform_code = account_platform_code(platform) or str(platform or "").strip().upper()
        seller_id = str(account_id or "").strip()
        if not seller_id:
            return Result.fail("Satıcı ID boş olamaz.", close_dialog=False)

        extra = dict(extra_config or {})
        environment_key = normalize_marketplace_environment(
            environment
            or extra.get("environment")
            or extra.get("api_environment")
            or "production"
        )
        profile = dict(marketplace_account_health_profile(platform_code, environment_key) or {})
        url_template = str(profile.get("urlTemplate") or "").strip()
        if not url_template:
            if profile.get("path") and not profile.get("environmentSupported"):
                return Result.fail(
                    f"{platform_code} için {environment_key} endpoint'i tanımlı değil.",
                    close_dialog=False,
                    data={"platform": platform_code, "environment": environment_key},
                )
            return Result.ok(
                f"{platform_code or 'Bilinmeyen platform'} için bağlantı kontrolü atlandı.",
                close_dialog=False,
                data={"platform": platform_code, "environment": environment_key, "skipped": True},
            )

        context = _health_context(
            platform=platform_code,
            account_id=seller_id,
            api_key=api_key,
            api_secret=api_secret,
            integration_code=integration_code,
            token=token,
            extra_config=extra,
            credential_reference=credential_reference,
        )
        bundle_seller_id = str(context.pop("_credential_bundle_seller_id", "") or "").strip()
        if bundle_seller_id and bundle_seller_id != seller_id:
            return Result.fail(
                "Credential bundle satıcı kapsamı istenen Satıcı ID ile eşleşmiyor.",
                close_dialog=False,
                data={"platform": platform_code, "environment": environment_key},
            )
        missing = _missing_health_credentials(profile, context)
        if missing:
            return Result.fail(
                f"Eksik zorunlu alanlar: {', '.join(missing)}",
                close_dialog=False,
                data={"platform": platform_code, "missingFields": missing},
            )

        method = str(profile.get("method") or "GET").strip().upper() or "GET"
        url = str(_render_health_template(url_template, context) or "").strip()
        headers = _render_health_template(profile.get("headers") or {}, context)
        params = _render_health_template(profile.get("query") or {}, context)
        timeout = int(profile.get("timeout") or 15)
        auth = _health_auth_for_profile(profile, context)

        res = await async_make_request(
            method=method,
            url=url,
            headers=headers if isinstance(headers, dict) else None,
            auth=auth,
            params=params if isinstance(params, dict) else None,
            timeout=timeout,
        )

        status_code_raw = (res.data or {}).get("status_code")
        status_code = int(status_code_raw) if status_code_raw not in (None, "") else None
        success_codes = {int(code) for code in list(profile.get("successStatusCodes") or [200])}
        status_message = _status_message_for_profile(profile, status_code)
        result_data = {
            "platform": platform_code,
            "environment": environment_key,
            "status_code": status_code,
            "endpoint": url,
            "method": method,
        }

        if res.success and status_code in success_codes:
            return Result.ok(status_message, close_dialog=False, data=result_data)
        if status_code is not None:
            return Result.fail(status_message, error=res.error, close_dialog=False, data=result_data)
        return Result.fail(
            f"API bağlantı kontrolü başarısız: {res.message}",
            error=res.error,
            close_dialog=False,
            data=result_data,
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def check_company_api_health(
    *,
    platform: str,
    account_id: str,
    api_key: str | None,
    api_secret: str | None,
    integration_code: str | None = None,
    token: str | None = None,
    extra_config: dict | None = None,
    environment: str | None = None,
    credential_reference: str | None = None,
) -> Result:
    return _run_async_result(
        _check_company_api_health_async(
            platform=platform,
            account_id=account_id,
            api_key=api_key,
            api_secret=api_secret,
            integration_code=integration_code,
            token=token,
            extra_config=extra_config,
            environment=environment,
            credential_reference=credential_reference,
        )
    )


async def _run_company_api_health_check_batch_async(accounts: List[Any]) -> Result:
    rows = [_account_health_payload(row) for row in list(accounts or [])]
    if not rows:
        return Result.ok("Kontrol edilecek şirket bulunamadı.", close_dialog=False, data={"checked": 0})

    summary: list[dict] = []
    ok_count = 0
    fail_count = 0
    skip_count = 0
    token_valid_updates: dict[int, bool] = {}
    concurrency = max(1, min(ACCOUNT_HEALTH_BATCH_CONCURRENCY, len(rows)))
    semaphore = asyncio.Semaphore(concurrency)

    def _iter_batches(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
        size = max(1, int(batch_size or 1))
        return [items[idx: idx + size] for idx in range(0, len(items), size)]

    async def _run_single(payload: dict[str, Any]) -> tuple[dict[str, Any], Result]:
        async with semaphore:
            health = await _check_company_api_health_async(
                platform=str(payload.get("platform") or ""),
                account_id=str(payload.get("account_id") or ""),
                api_key=payload.get("api_key"),
                api_secret=payload.get("api_secret"),
                integration_code=payload.get("integration_code"),
                token=payload.get("token"),
                extra_config=payload.get("extra_config"),
            )
            return payload, health

    for batch in _iter_batches(rows, min(len(rows), ACCOUNT_HEALTH_GATHER_BATCH_SIZE)):
        for payload, health in await asyncio.gather(*(_run_single(row) for row in batch)):
            skipped = bool((health.data or {}).get("skipped"))
            if skipped:
                skip_count += 1
            elif health.success:
                ok_count += 1
                if payload.get("pk") is not None:
                    token_valid_updates[int(payload["pk"])] = True
            else:
                fail_count += 1
                if payload.get("pk") is not None:
                    token_valid_updates[int(payload["pk"])] = False

            summary.append(
                {
                    "pk": payload.get("pk"),
                    "comp_name": str(payload.get("comp_name") or ""),
                    "platform": str(payload.get("platform") or ""),
                    "success": bool(health.success),
                    "skipped": skipped,
                    "message": str(health.message or ""),
                }
            )

    return Result.ok(
        f"API bağlantı kontrolü tamamlandı. Başarılı: {ok_count}, Hatalı: {fail_count}, Atlandı: {skip_count}",
        close_dialog=False,
        data={
            "checked": len(rows),
            "ok": ok_count,
            "failed": fail_count,
            "skipped": skip_count,
            "results": summary,
            "token_valid_updates": token_valid_updates,
        },
    )


def run_company_api_health_check_batch(accounts: List[Any]) -> Result:
    try:
        batch_result = _run_async_result(_run_company_api_health_check_batch_async(accounts))
        if not batch_result.success:
            return batch_result

        data = dict(batch_result.data or {})
        token_valid_updates = {
            int(company_pk): bool(token_valid)
            for company_pk, token_valid in dict(data.pop("token_valid_updates") or {}).items()
        }

        if token_valid_updates:
            with Session(_engine()) as session:
                changed = False
                accounts_to_update = session.exec(
                    select(ApiAccount).where(ApiAccount.pk.in_(list(token_valid_updates.keys())))
                ).all()
                for account in accounts_to_update:
                    company_pk = int(getattr(account, "pk", 0) or 0)
                    token_valid = token_valid_updates.get(company_pk)
                    if token_valid is None:
                        continue
                    if bool(getattr(account, "token_valid", True)) == token_valid:
                        continue
                    account.token_valid = token_valid
                    changed = True
                if changed:
                    session.commit()
                    _emit_company_changed()

        return Result.ok(batch_result.message or "API bağlantı kontrolü tamamlandı.", close_dialog=False, data=data)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def save_company_to_db(form_values: Dict[str, Any]) -> Result:
    try:
        payload, validation = _prepare_account_create_payload(form_values)
        if not validation.success:
            return validation

        result = create_records(
            model=ApiAccount,
            mode="plain",
            data_list=[payload],
            db_name=DB_NAME,
            conflict_keys=["account_id", "comp_name", "platform"],
        )
        if not result.success:
            return result

        _emit_company_changed()
        return Result.ok("Şirket başarıyla kaydedildi.")
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc)


def _delete_company_related_records(session: Session, company_pk: int) -> None:
    from Finance.models.trendyol.models import FinanceCargoInvoiceItem, FinanceTransaction
    from Listing.models import (
        ListingProduct,
        ListingProductCostSnapshot,
        ListingProductHistory,
        ListingProductStockSnapshot,
    )
    from Orders.models.trendyol.models import (
        OrderData,
        OrderHeader,
        OrderItem,
        ReturnClaim,
    )
    from Stock.models import StockTx

    company_pk = int(company_pk)
    def _iter_pk_batches(model, pk_attr: str, where_clause):
        pk_col = getattr(model, pk_attr)
        last_pk = None
        while True:
            stmt = (
                select(pk_col)
                .where(where_clause)
                .order_by(pk_col.asc())
                .limit(ACCOUNT_DELETE_CHUNK_SIZE)
            )
            if last_pk is not None:
                stmt = stmt.where(pk_col > last_pk)
            batch = [int(value) for value in (session.exec(stmt).all() or []) if value is not None]
            if not batch:
                break
            yield batch
            last_pk = batch[-1]

    session.exec(delete(OrderItem).where(OrderItem.api_account_id == company_pk))
    session.exec(delete(OrderData).where(OrderData.api_account_id == company_pk))

    for header_ids in _iter_pk_batches(OrderHeader, "pk", OrderHeader.api_account_id == company_pk):
        session.exec(delete(OrderItem).where(OrderItem.order_header_id.in_(header_ids)))
        session.exec(delete(OrderData).where(OrderData.order_header_id.in_(header_ids)))
        session.exec(delete(StockTx).where(StockTx.order_header_id.in_(header_ids)))
        session.exec(delete(OrderHeader).where(OrderHeader.pk.in_(header_ids)))
        session.flush()

    session.exec(delete(ReturnClaim).where(ReturnClaim.api_account_id == company_pk))
    session.exec(delete(FinanceCargoInvoiceItem).where(FinanceCargoInvoiceItem.api_account_id == company_pk))
    session.exec(delete(FinanceTransaction).where(FinanceTransaction.api_account_id == company_pk))
    session.exec(delete(ListingProductHistory).where(ListingProductHistory.api_account_id == company_pk))

    for listing_ids in _iter_pk_batches(ListingProduct, "pk", ListingProduct.api_account_id == company_pk):
        session.exec(delete(ListingProductCostSnapshot).where(ListingProductCostSnapshot.listing_id.in_(listing_ids)))
        session.exec(delete(ListingProductStockSnapshot).where(ListingProductStockSnapshot.listing_id.in_(listing_ids)))
        session.exec(delete(ListingProduct).where(ListingProduct.pk.in_(listing_ids)))
        session.flush()


def update_company(pk: int, update_data: Dict[str, Any]) -> Result:
    try:
        normalized_update, validation = _prepare_account_update_payload(update_data)
        if not validation.success:
            return validation

        with Session(_engine()) as session:
            account = session.get(ApiAccount, int(pk))
            if account is None:
                return Result.fail("Güncellenecek şirket bulunamadı.", close_dialog=False)

            if not normalized_update:
                return Result.fail("Güncellenecek geçerli alan bulunamadı.", close_dialog=False)

            changed_update = _changed_account_fields(account, normalized_update)
            if not changed_update:
                return Result.ok("Şirket verisinde değişiklik yok.", close_dialog=False)

            reset_token_valid = _health_identity_changed(account, changed_update)
            for field_name, value in changed_update.items():
                setattr(account, field_name, value)

            if reset_token_valid:
                account.token_valid = False

            session.add(account)
            session.commit()

        _emit_company_changed()
        return Result.ok("Şirket başarıyla güncellendi.")
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc)


def delete_company_from_db(pk: int) -> Result:
    try:
        company_pk = int(pk)
        with Session(_engine()) as session:
            account = session.get(ApiAccount, company_pk)
            if account is None:
                return Result.fail("Silinecek kayıt bulunamadı.", close_dialog=False)

            _delete_company_related_records(session, company_pk)
            session.delete(account)
            session.commit()

        _emit_company_changed()
        _emit_orders_changed()
        return Result.ok(f"Şirket (id={company_pk}) başarıyla silindi.")
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc)


def process_logo(file_path: str) -> Result:
    try:
        if not file_path:
            return Result.fail("Geçerli bir dosya yolu verilmedi.", close_dialog=False)

        src = Path(file_path)
        if not src.exists() or not src.is_file():
            return Result.fail("Logo dosyası bulunamadı.", close_dialog=False)
        if src.suffix.lower() not in ACCOUNT_LOGO_ALLOWED_EXTENSIONS:
            return Result.fail(
                f"Desteklenmeyen logo formatı: {src.suffix or 'uzantısız dosya'}",
                close_dialog=False,
            )

        logos_dir = company_logos_dir()
        logos_dir.mkdir(parents=True, exist_ok=True)

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


def get_all_companies() -> Result:
    try:
        result = get_records(model=ApiAccount, db_engine=_engine())
        if not result.success:
            return result

        records = result.data.get("records", []) or []
        return Result.ok(
            f"{len(records)} şirket bulundu." if records else "Hiç şirket bulunmuyor.",
            close_dialog=False,
            data={
                "records": records,
                "accounts": _accounts_payload(records, include_last_used_at=False),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def get_active_companies(*, db_name: str | None = None) -> Result:
    try:
        result = get_records(
            db_engine=_engine(db_name),
            custom_stmt=select(ApiAccount).where(ApiAccount.is_active.is_(True)),
        )
        if not result.success:
            return result

        records = result.data.get("records", []) or []
        return Result.ok(
            f"{len(records)} aktif şirket bulundu." if records else "Aktif şirket bulunmuyor.",
            close_dialog=False,
            data={
                "records": records,
                "accounts": _accounts_payload(records, include_last_used_at=False),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def get_company_by_id(pks: List[int], *, db_name: str | None = None) -> Result:
    try:
        if not pks:
            return Result.fail("Hiçbir şirket seçilmedi.", close_dialog=False)

        result = get_records(
            model=ApiAccount,
            db_engine=_engine(db_name),
            filters={"pk": pks},
        )
        if not result.success:
            return result

        records = result.data.get("records", []) or []
        if not records:
            return Result.fail("Seçilen şirketler bulunamadı.", close_dialog=False)

        return Result.ok(
            f"{len(records)} şirket bulundu.",
            close_dialog=False,
            data={
                "records": records,
                "accounts": _accounts_payload(records, include_last_used_at=True),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)

