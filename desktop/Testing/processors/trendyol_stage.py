from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable

from Account.processors.pipeline import get_company_by_id
from Feedback.processors.pipeline import Result, map_error_to_message
from Listing.processors.pipeline import get_listings_from_db
from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs
from Marketplaces.processors.catalog import canonical_platform_code, normalize_marketplace_environment
from Orders.api.trendyol.orders_api import TrendyolApi
from Orders.processors.trendyol.pipeline import (
    get_latest_orders,
    get_latest_return_claims,
    normalize_order_data,
    normalize_return_claim,
    save_orders_to_db,
    save_return_claims_to_db,
)
from Testing.constants.trendyol_stage_constants import (
    TRENDYOL_STAGE_BASE_URL,
    TRENDYOL_STAGE_CARGO_PROVIDER_IDS,
    TRENDYOL_STAGE_OFFICIAL_TEST_BARCODE,
    TRENDYOL_STAGE_ORDER_STATUS_FLOW,
    TRENDYOL_STAGE_VERIFY_ATTEMPTS,
)
from settings import DB_NAME


@dataclass(frozen=True)
class _StageScope:
    api_account_id: int
    account: Any
    api: TrendyolApi
    seller_id: str


def _compact(value: Any) -> str:
    return str(value or "").strip()


def _positive_int(value: Any, *, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return int(default)
    return parsed if parsed > 0 else int(default)


def _run_async(awaitable: Awaitable[Result]) -> Result:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(awaitable)
        return result if isinstance(result, Result) else Result.fail(
            "Stage API beklenmeyen bir sonuç döndürdü.",
            close_dialog=False,
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
    finally:
        try:
            from Core.utils.request_utils import close_async_request_clients

            loop.run_until_complete(close_async_request_clients())
        except Exception:
            pass
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


def _load_stage_scope(api_account_id: int, *, db_name: str = DB_NAME) -> Result:
    try:
        account_id = _positive_int(api_account_id)
        if account_id <= 0:
            return Result.fail("Geçerli bir şirket seçmelisin.", close_dialog=False)

        account_res = get_company_by_id([account_id], db_name=db_name)
        if not account_res.success:
            return account_res
        records = list((account_res.data or {}).get("records") or [])
        if not records:
            return Result.fail("Seçilen şirket bulunamadı.", close_dialog=False)
        account = records[0]

        platform_code = canonical_platform_code(getattr(account, "platform", None))
        if platform_code != "TRENDYOL":
            return Result.fail(
                "Stage laboratuvarı yalnızca Trendyol hesaplarında çalışır.",
                close_dialog=False,
                data={"platform": platform_code or "unknown"},
            )

        extra_config = dict(getattr(account, "extra_config", None) or {})
        environment = normalize_marketplace_environment(
            extra_config.get("environment")
            or extra_config.get("api_environment")
            or "production"
        )
        if environment != "stage":
            return Result.fail(
                "Güvenlik engeli: Bu işlem yalnızca Stage hesabında çalışabilir.",
                close_dialog=False,
                data={"environment": environment, "production_blocked": True},
            )

        api = TrendyolApi(**trendyol_account_client_kwargs(account))
        return Result.ok(
            "Trendyol Stage hesabı doğrulandı.",
            close_dialog=False,
            data={
                "scope": _StageScope(
                    api_account_id=account_id,
                    account=account,
                    api=api,
                    seller_id=_compact(getattr(account, "account_id", None)),
                ),
                "environment": environment,
                "platform": platform_code,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _scope_or_result(api_account_id: int, *, db_name: str = DB_NAME) -> tuple[_StageScope | None, Result]:
    result = _load_stage_scope(api_account_id, db_name=db_name)
    scope = (result.data or {}).get("scope") if result.success else None
    return (scope if isinstance(scope, _StageScope) else None), result


async def _stage_request(
    scope: _StageScope,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Result:
    url = f"{TRENDYOL_STAGE_BASE_URL}{path}"
    headers = dict(scope.api.header or {})
    headers["SellerID"] = scope.seller_id
    return await scope.api._send_request(
        method=str(method or "GET").upper(),
        url=url,
        headers=headers,
        auth=scope.api.auth,
        json=payload,
        timeout=max(5, int(timeout)),
    )


def _response_value(payload: Any, *keys: str) -> Any:
    wanted = {_compact(key).casefold() for key in keys if _compact(key)}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _compact(key).casefold() in wanted and value not in (None, ""):
                return value
        for value in payload.values():
            found = _response_value(value, *keys)
            if found not in (None, ""):
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _response_value(value, *keys)
            if found not in (None, ""):
                return found
    return None


def _remote_order(scope: _StageScope, order_number: str) -> Result:
    order_no = _compact(order_number)
    if not order_no:
        return Result.fail("Sipariş numarası gerekli.", close_dialog=False)
    result = _run_async(scope.api.get_order_by_number(order_no, page=0, size=50))
    if not result.success:
        return result
    content = list((result.data or {}).get("content") or [])
    match = next(
        (row for row in content if _compact((row or {}).get("orderNumber")) == order_no),
        content[0] if content else None,
    )
    if not isinstance(match, dict):
        return Result.fail(
            f"Stage siparişi henüz okunamıyor: {order_no}",
            close_dialog=False,
            data={"order_number": order_no},
        )
    return Result.ok(
        "Stage siparişi okundu.",
        close_dialog=False,
        data={"order": match, "order_number": order_no},
    )


def _sync_remote_order(scope: _StageScope, order_number: str, *, db_name: str = DB_NAME) -> Result:
    remote = _remote_order(scope, order_number)
    if not remote.success:
        return remote
    order = dict((remote.data or {}).get("order") or {})
    order_rows, item_rows = normalize_order_data(order, scope.api_account_id)
    save_result = save_orders_to_db(
        Result.ok(
            "Stage siparişi normalize edildi.",
            close_dialog=False,
            data={"order_data_list": order_rows, "order_item_list": item_rows},
        ),
        db_name=db_name,
    )
    if not save_result.success:
        return save_result
    status = _compact(order.get("shipmentPackageStatus") or order.get("status"))
    return Result.ok(
        "Stage siparişi uygulama veritabanına işlendi.",
        close_dialog=False,
        data={
            "order": order,
            "order_number": _compact(order.get("orderNumber") or order_number),
            "shipment_package_id": order.get("shipmentPackageId") or order.get("id"),
            "status": status,
            "save": save_result.data or {},
        },
    )


def sync_stage_order(
    *,
    api_account_id: int,
    order_number: str,
    attempts: int = 1,
    db_name: str = DB_NAME,
) -> Result:
    scope, scope_result = _scope_or_result(api_account_id, db_name=db_name)
    if scope is None:
        return scope_result
    last = Result.fail("Stage siparişi okunamadı.", close_dialog=False)
    for attempt in range(max(1, min(int(attempts), 15))):
        last = _sync_remote_order(scope, order_number, db_name=db_name)
        if last.success:
            return last
        if attempt + 1 < max(1, min(int(attempts), 15)):
            time.sleep(1)
    return last


def _claim_rows_from_remote(scope: _StageScope, *, claim_id: str = "", order_number: str = "") -> Result:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    result = _run_async(
        scope.api.find_claims(
            start_date=now_ms - int(timedelta(days=365).total_seconds() * 1000),
            end_date=now_ms + int(timedelta(days=1).total_seconds() * 1000),
            page=0,
            size=200,
            claim_ids=[_compact(claim_id)] if _compact(claim_id) else None,
            order_number=_compact(order_number) or None,
        )
    )
    if not result.success:
        return result
    rows = [row for row in list((result.data or {}).get("content") or []) if isinstance(row, dict)]
    if claim_id:
        rows = [
            row
            for row in rows
            if _compact(row.get("claimId") or row.get("id")) == _compact(claim_id)
        ]
    if order_number:
        rows = [row for row in rows if _compact(row.get("orderNumber")) == _compact(order_number)]
    return Result.ok("Stage iadeleri okundu.", close_dialog=False, data={"rows": rows})


def _sync_remote_claims(
    scope: _StageScope,
    *,
    claim_id: str = "",
    order_number: str = "",
    db_name: str = DB_NAME,
) -> Result:
    remote = _claim_rows_from_remote(scope, claim_id=claim_id, order_number=order_number)
    if not remote.success:
        return remote
    rows = list((remote.data or {}).get("rows") or [])
    if not rows:
        return Result.fail(
            "Stage iadesi henüz okunamıyor.",
            close_dialog=False,
            data={"claim_id": _compact(claim_id), "order_number": _compact(order_number)},
        )
    normalized = [normalize_return_claim(row, scope.api_account_id) for row in rows]
    save_result = save_return_claims_to_db(
        Result.ok(
            "Stage iadeleri normalize edildi.",
            close_dialog=False,
            data={"return_claim_list": normalized},
        ),
        db_name=db_name,
    )
    if not save_result.success:
        return save_result
    selected_id = _compact(claim_id) or _compact(normalized[0].get("claimId"))
    readback = get_latest_return_claims(
        claim_ids=[selected_id] if selected_id else None,
        api_account_ids=[scope.api_account_id],
        db_name=db_name,
    )
    if not readback.success:
        return readback
    claims = list((readback.data or {}).get("claims") or [])
    claim = claims[0] if claims else None
    if claim is None:
        return Result.fail("İade DB geri okumasında bulunamadı.", close_dialog=False)
    return Result.ok(
        "Stage iadesi uygulama veritabanına işlendi.",
        close_dialog=False,
        data={
            "claim": claim,
            "claim_id": _compact(getattr(claim, "claimId", None)),
            "order_number": _compact(getattr(claim, "orderNumber", None)),
            "status": _compact(getattr(claim, "claimItemStatus", None)),
            "shipment_package_id": getattr(claim, "orderShipmentPackageId", None),
            "save": save_result.data or {},
        },
    )


def sync_stage_claim(
    *,
    api_account_id: int,
    claim_id: str = "",
    order_number: str = "",
    attempts: int = 1,
    expected_statuses: list[str] | None = None,
    db_name: str = DB_NAME,
) -> Result:
    scope, scope_result = _scope_or_result(api_account_id, db_name=db_name)
    if scope is None:
        return scope_result
    expected = {_compact(value).casefold() for value in (expected_statuses or []) if _compact(value)}
    last = Result.fail("Stage iadesi okunamadı.", close_dialog=False)
    for attempt in range(max(1, min(int(attempts), 15))):
        last = _sync_remote_claims(
            scope,
            claim_id=claim_id,
            order_number=order_number,
            db_name=db_name,
        )
        if last.success:
            status = _compact((last.data or {}).get("status")).casefold()
            if not expected or status in expected:
                return last
        if attempt + 1 < max(1, min(int(attempts), 15)):
            time.sleep(1)
    if last.success and expected:
        return Result.fail(
            "Stage iadesi beklenen duruma ulaşmadı.",
            close_dialog=False,
            data={**(last.data or {}), "expected_statuses": sorted(expected)},
        )
    return last


def _listing_context(api_account_id: int, *, db_name: str) -> list[dict[str, Any]]:
    result = get_listings_from_db(api_account_ids=[int(api_account_id)], db_name=db_name)
    if not result.success:
        return []
    out: list[dict[str, Any]] = []
    for row in list((result.data or {}).get("items") or []):
        if not isinstance(row, dict):
            continue
        barcode = _compact(row.get("barcode"))
        if not barcode or not bool(row.get("approved")) or bool(row.get("archived")):
            continue
        out.append(
            {
                "product_id": _compact(row.get("productId") or row.get("product_id")),
                "barcode": barcode,
                "title": _compact(row.get("title") or row.get("name") or barcode),
                "quantity": row.get("quantity"),
                "on_sale": bool(row.get("onSale") or row.get("on_sale")),
                "stock_item_id": row.get("stock_item_id"),
            }
        )
    out.sort(key=lambda row: (not bool(row.get("on_sale")), -_positive_int(row.get("quantity")), row["title"].casefold()))
    return out[:300]


def stage_lab_context(*, api_account_id: int, db_name: str = DB_NAME) -> Result:
    scope, scope_result = _scope_or_result(api_account_id, db_name=db_name)
    if scope is None:
        return scope_result
    orders_result = get_latest_orders(
        api_account_ids=[scope.api_account_id],
        db_name=db_name,
        exclude_simulated=True,
    )
    claims_result = get_latest_return_claims(
        api_account_ids=[scope.api_account_id],
        db_name=db_name,
    )
    if not orders_result.success:
        return orders_result
    if not claims_result.success:
        return claims_result

    orders = []
    for row in list((orders_result.data or {}).get("orders") or []):
        orders.append(
            {
                "order_number": _compact(getattr(row, "orderNumber", None)),
                "status": _compact(
                    getattr(row, "shipmentPackageStatus", None)
                    or getattr(row, "status", None)
                ),
                "shipment_package_id": getattr(row, "shipmentPackageId", None),
                "cargo_provider_name": _compact(getattr(row, "cargoProviderName", None)),
                "customer_id": getattr(row, "customerId", None),
                "order_date": getattr(row, "orderDate", None),
            }
        )
    orders.sort(key=lambda row: (_positive_int(row.get("order_date")), row["order_number"]), reverse=True)

    claims = []
    for row in list((claims_result.data or {}).get("claims") or []):
        claims.append(
            {
                "claim_id": _compact(getattr(row, "claimId", None)),
                "order_number": _compact(getattr(row, "orderNumber", None)),
                "status": _compact(getattr(row, "claimItemStatus", None)),
                "shipment_package_id": getattr(row, "orderShipmentPackageId", None),
                "claim_date": getattr(row, "claimDate", None),
            }
        )
    claims.sort(key=lambda row: (_positive_int(row.get("claim_date")), row["claim_id"]), reverse=True)

    listings = _listing_context(scope.api_account_id, db_name=db_name)
    listings = [
        {
            "product_id": f"official:{TRENDYOL_STAGE_OFFICIAL_TEST_BARCODE}",
            "barcode": TRENDYOL_STAGE_OFFICIAL_TEST_BARCODE,
            "title": "Trendyol resmi Stage test ürünü (önerilen)",
            "quantity": "-",
            "on_sale": True,
            "stock_item_id": None,
            "official_test_product": True,
        },
        *[
            row
            for row in listings
            if _compact(row.get("barcode")) != TRENDYOL_STAGE_OFFICIAL_TEST_BARCODE
        ],
    ]

    return Result.ok(
        "Stage laboratuvar bağlamı hazır.",
        close_dialog=False,
        data={
            "account": {
                "api_account_id": scope.api_account_id,
                "company_name": _compact(getattr(scope.account, "comp_name", None)),
                "seller_id": scope.seller_id,
                "platform": "TRENDYOL",
                "environment": "stage",
            },
            "listings": listings,
            "orders": orders[:500],
            "claims": claims[:500],
            "allowed_order_statuses": list(TRENDYOL_STAGE_ORDER_STATUS_FLOW),
        },
    )


def create_stage_test_order(
    *,
    api_account_id: int,
    barcode: str,
    quantity: int = 1,
    seller_discount_percentage: int = 0,
    trendyol_discount_percentage: int = 0,
    db_name: str = DB_NAME,
) -> Result:
    scope, scope_result = _scope_or_result(api_account_id, db_name=db_name)
    if scope is None:
        return scope_result
    barcode_text = _compact(barcode)
    qty = max(1, min(_positive_int(quantity, default=1), 20))
    if not barcode_text:
        return Result.fail("Test siparişi için barkod seçmelisin.", close_dialog=False)

    address = {
        "addressText": "OrderScout TestLab Stage test adresi",
        "city": "İzmir",
        "company": "",
        "district": "Bornova",
        "email": "testlab@orderscout.local",
        "latitude": "38.4237",
        "longitude": "27.1428",
        "neighborhood": "Kazımdirik",
        "phone": "5000000000",
        "postalCode": "35040",
    }
    payload = {
        "customer": {
            "customerFirstName": "OrderScout",
            "customerLastName": "TestLab",
        },
        "invoiceAddress": {
            **address,
            "invoiceFirstName": "OrderScout",
            "invoiceLastName": "TestLab",
            "invoiceTaxNumber": "",
            "invoiceTaxOffice": "",
        },
        "lines": [
            {
                "barcode": barcode_text,
                "quantity": qty,
                "discountPercentage": max(0, min(int(seller_discount_percentage), 100)),
                "trendyolDiscountPercentage": max(0, min(int(trendyol_discount_percentage), 100)),
            }
        ],
        "seller": {"sellerId": _positive_int(scope.seller_id)},
        "shippingAddress": {
            **address,
            "shippingFirstName": "OrderScout",
            "shippingLastName": "TestLab",
        },
        "commercial": False,
    }
    response = _run_async(
        _stage_request(
            scope,
            method="POST",
            path="/integration/test/order/orders/core",
            payload=payload,
        )
    )
    if not response.success:
        return response
    body = (response.data or {}).get("json")
    order_number = _compact(_response_value(body, "orderNumber", "order_number"))
    if not order_number:
        return Result.fail(
            "Stage test siparişi oluşturuldu ancak orderNumber okunamadı.",
            close_dialog=False,
            data={"status_code": (response.data or {}).get("status_code")},
        )
    synced = sync_stage_order(
        api_account_id=scope.api_account_id,
        order_number=order_number,
        attempts=12,
        db_name=db_name,
    )
    if not synced.success:
        return Result.fail(
            "Stage siparişi oluşturuldu fakat uygulamaya henüz senkronize edilemedi.",
            close_dialog=False,
            data={"order_number": order_number, "sync": synced.data or {}},
        )
    return Result.ok(
        "Stage test siparişi oluşturuldu ve uygulamaya çekildi.",
        close_dialog=False,
        data={**(synced.data or {}), "barcode": barcode_text, "quantity": qty},
    )


def advance_stage_order_status(
    *,
    api_account_id: int,
    order_number: str,
    target_status: str,
    db_name: str = DB_NAME,
) -> Result:
    scope, scope_result = _scope_or_result(api_account_id, db_name=db_name)
    if scope is None:
        return scope_result
    target = _compact(target_status)
    if target not in TRENDYOL_STAGE_ORDER_STATUS_FLOW:
        return Result.fail("Desteklenmeyen Stage sipariş durumu.", close_dialog=False)
    remote = _remote_order(scope, order_number)
    if not remote.success:
        return remote
    order = dict((remote.data or {}).get("order") or {})
    package_id = _positive_int(order.get("shipmentPackageId") or order.get("id"))
    lines = []
    for line in list(order.get("lines") or []):
        if not isinstance(line, dict):
            continue
        line_id = _positive_int(line.get("lineId") or line.get("id"))
        quantity = max(1, _positive_int(line.get("quantity"), default=1))
        if line_id > 0:
            lines.append({"lineId": line_id, "quantity": quantity})
    if package_id <= 0 or not lines:
        return Result.fail("Stage siparişinin paket veya satır kimliği eksik.", close_dialog=False)
    response = _run_async(
        _stage_request(
            scope,
            method="PUT",
            path=(
                f"/integration/test/order/sellers/{scope.seller_id}"
                f"/shipment-packages/{package_id}/status"
            ),
            payload={"lines": lines, "params": {}, "status": target},
        )
    )
    if not response.success:
        return response
    last = Result.fail("Sipariş durumu henüz Stage'de görünmüyor.", close_dialog=False)
    for attempt in range(TRENDYOL_STAGE_VERIFY_ATTEMPTS):
        last = _sync_remote_order(scope, order_number, db_name=db_name)
        if last.success and _compact((last.data or {}).get("status")).casefold() == target.casefold():
            return Result.ok(
                f"Stage siparişi {target} durumuna geçirildi ve doğrulandı.",
                close_dialog=False,
                data=last.data or {},
            )
        if attempt < TRENDYOL_STAGE_VERIFY_ATTEMPTS - 1:
            time.sleep(1)
    return Result.fail(
        f"Stage isteği başarılı ancak {target} durumu geri okumada doğrulanamadı.",
        close_dialog=False,
        data=last.data or {},
    )


def _cargo_provider_id(order: dict[str, Any]) -> int:
    code = _compact(order.get("cargoProviderCode")).upper()
    name = _compact(order.get("cargoProviderName")).casefold()
    if code in TRENDYOL_STAGE_CARGO_PROVIDER_IDS:
        return TRENDYOL_STAGE_CARGO_PROVIDER_IDS[code]
    name_tokens = {
        "trendyol express": "TEXMP",
        "yurti": "YKMP",
        "aras": "ARASMP",
        "sürat": "SURATMP",
        "surat": "SURATMP",
        "ptt": "PTTMP",
        "horoz": "HOROZMP",
        "dhl": "DHLECOMMP",
        "ceva tedarik": "CEVATEDARIK",
        "ceva": "CEVAMP",
        "kolay gelsin": "KOLAYGELSINMP",
    }
    for token, provider_code in name_tokens.items():
        if token in name:
            return TRENDYOL_STAGE_CARGO_PROVIDER_IDS[provider_code]
    return 4


def create_stage_return_claim(
    *,
    api_account_id: int,
    order_number: str,
    quantity: int = 1,
    reason_id: int = 401,
    db_name: str = DB_NAME,
) -> Result:
    scope, scope_result = _scope_or_result(api_account_id, db_name=db_name)
    if scope is None:
        return scope_result
    remote = _remote_order(scope, order_number)
    if not remote.success:
        return remote
    order = dict((remote.data or {}).get("order") or {})
    lines = [line for line in list(order.get("lines") or []) if isinstance(line, dict)]
    if not lines:
        return Result.fail("İade oluşturulacak sipariş satırı bulunamadı.", close_dialog=False)
    line = lines[0]
    barcode = _compact(line.get("barcode") or line.get("merchantSku") or line.get("sku"))
    customer_id = _positive_int(order.get("customerId"))
    if not barcode or customer_id <= 0:
        return Result.fail("İade için barkod veya müşteri kimliği eksik.", close_dialog=False)
    max_quantity = max(1, _positive_int(line.get("quantity"), default=1))
    requested_quantity = max(1, min(_positive_int(quantity, default=1), max_quantity))
    payload = {
        "claimItems": [
            {
                "barcode": barcode,
                "customerNote": "OrderScout TestLab Stage iade testi",
                "quantity": requested_quantity,
                "reasonId": _positive_int(reason_id, default=401),
            }
        ],
        "customerId": customer_id,
        "excludeListing": True,
        "forcePackageCreation": True,
        "orderNumber": _compact(order.get("orderNumber") or order_number),
        "shipmentCompanyId": _cargo_provider_id(order),
    }
    response = _run_async(
        _stage_request(
            scope,
            method="POST",
            path=f"/integration/order/sellers/{scope.seller_id}/claims/create",
            payload=payload,
        )
    )
    if not response.success:
        return response
    body = (response.data or {}).get("json")
    claim_id = _compact(_response_value(body, "claimId", "id"))
    if not claim_id:
        return Result.fail(
            "Stage iadesi oluşturuldu ancak claimId okunamadı.",
            close_dialog=False,
            data={"order_number": payload["orderNumber"]},
        )
    synced = sync_stage_claim(
        api_account_id=scope.api_account_id,
        claim_id=claim_id,
        attempts=12,
        expected_statuses=["Created", "WaitingInAction", "Accepted"],
        db_name=db_name,
    )
    if not synced.success:
        return Result.fail(
            "Stage iadesi oluşturuldu fakat uygulamaya henüz senkronize edilemedi.",
            close_dialog=False,
            data={"claim_id": claim_id, "order_number": payload["orderNumber"]},
        )
    return Result.ok(
        "Stage iadesi oluşturuldu ve uygulamaya çekildi.",
        close_dialog=False,
        data=synced.data or {},
    )


def advance_stage_claim_to_waiting_action(
    *,
    api_account_id: int,
    claim_id: str,
    db_name: str = DB_NAME,
) -> Result:
    scope, scope_result = _scope_or_result(api_account_id, db_name=db_name)
    if scope is None:
        return scope_result
    synced = sync_stage_claim(
        api_account_id=scope.api_account_id,
        claim_id=claim_id,
        attempts=3,
        db_name=db_name,
    )
    if not synced.success:
        return synced
    package_id = _positive_int((synced.data or {}).get("shipment_package_id"))
    if package_id <= 0:
        return Result.fail("İade shipmentPackageId bilgisi eksik.", close_dialog=False)
    response = _run_async(
        _stage_request(
            scope,
            method="PUT",
            path=f"/integration/test/order/sellers/{scope.seller_id}/claims/waiting-in-action",
            payload={"shipmentPackageId": package_id},
        )
    )
    if not response.success:
        return response
    verified = sync_stage_claim(
        api_account_id=scope.api_account_id,
        claim_id=claim_id,
        attempts=12,
        expected_statuses=["WaitingInAction"],
        db_name=db_name,
    )
    if not verified.success:
        return verified
    return Result.ok(
        "Stage iadesi WaitingInAction durumuna geçirildi ve doğrulandı.",
        close_dialog=False,
        data=verified.data or {},
    )


def prepare_stage_return_lifecycle(
    *,
    api_account_id: int,
    barcode: str,
    quantity: int = 1,
    db_name: str = DB_NAME,
) -> Result:
    steps: list[dict[str, Any]] = []

    created = create_stage_test_order(
        api_account_id=api_account_id,
        barcode=barcode,
        quantity=quantity,
        db_name=db_name,
    )
    steps.append({"step": "stage.order.create", "success": created.success, "detail": created.message})
    if not created.success:
        return Result.fail(created.message, error=created.error, close_dialog=False, data={"steps": steps})
    order_number = _compact((created.data or {}).get("order_number"))

    for status in ("Shipped", "AtCollectionPoint", "Delivered"):
        advanced = advance_stage_order_status(
            api_account_id=api_account_id,
            order_number=order_number,
            target_status=status,
            db_name=db_name,
        )
        steps.append(
            {"step": f"stage.order.status.{status}", "success": advanced.success, "detail": advanced.message}
        )
        if not advanced.success:
            return Result.fail(advanced.message, error=advanced.error, close_dialog=False, data={"steps": steps, "order_number": order_number})

    claim_created = create_stage_return_claim(
        api_account_id=api_account_id,
        order_number=order_number,
        quantity=1,
        db_name=db_name,
    )
    steps.append(
        {"step": "stage.claim.create", "success": claim_created.success, "detail": claim_created.message}
    )
    if not claim_created.success:
        return Result.fail(
            claim_created.message,
            error=claim_created.error,
            close_dialog=False,
            data={"steps": steps, "order_number": order_number},
        )
    claim_id = _compact((claim_created.data or {}).get("claim_id"))

    waiting = advance_stage_claim_to_waiting_action(
        api_account_id=api_account_id,
        claim_id=claim_id,
        db_name=db_name,
    )
    steps.append(
        {"step": "stage.claim.waiting_in_action", "success": waiting.success, "detail": waiting.message}
    )
    if not waiting.success:
        return Result.fail(
            waiting.message,
            error=waiting.error,
            close_dialog=False,
            data={"steps": steps, "order_number": order_number, "claim_id": claim_id},
        )

    return Result.ok(
        "Stage sipariş ve iade hazırlık yaşam döngüsü tamamlandı.",
        close_dialog=False,
        data={
            "steps": steps,
            "order_number": order_number,
            "claim_id": claim_id,
            "claim": (waiting.data or {}).get("claim"),
            "status": (waiting.data or {}).get("status"),
        },
    )


__all__ = [
    "advance_stage_claim_to_waiting_action",
    "advance_stage_order_status",
    "create_stage_return_claim",
    "create_stage_test_order",
    "prepare_stage_return_lifecycle",
    "stage_lab_context",
    "sync_stage_claim",
    "sync_stage_order",
]
