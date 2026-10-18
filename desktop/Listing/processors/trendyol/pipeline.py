# Listing/processors/trendyol/pipeline.py
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any

from Feedback.processors.pipeline import Result, map_error_to_message
from Listing.api.trendyol.listing_api import TrendyolListingApi


@dataclass
class _ProgressTracker:
    total: int
    callback: Optional[Callable[[int, int], None]] = None
    expected_page_keys: tuple[tuple[Any, str], ...] | None = None

    def __post_init__(self) -> None:
        self.current: int = 0
        self._lock = asyncio.Lock()
        self._disabled = False
        self._page_current: dict[tuple[Any, str], int] = {}
        self._page_total: dict[tuple[Any, str], int] = {}
        for key in self.expected_page_keys or ():
            current_key = self._normalize_page_key(key)
            self._page_current.setdefault(current_key, 0)
            self._page_total.setdefault(current_key, 1)

    @staticmethod
    def _normalize_page_key(key: tuple[Any, str]) -> tuple[Any, str]:
        return (key[0], str(key[1] or "all"))

    async def step(self, inc: int = 1) -> None:
        async with self._lock:
            if self._disabled:
                return
            self.current += inc
            if self.callback:
                self.callback(self.current, self.total)

    async def add_total(self, inc: int) -> None:
        async with self._lock:
            if self._disabled:
                return
            self.total += max(0, int(inc))
            if self.callback:
                self.callback(self.current, self.total)

    async def disable(self) -> None:
        async with self._lock:
            self._disabled = True

    async def set_page_progress(
        self,
        key: tuple[Any, str],
        fetched_pages: int,
        total_pages: int | None,
        has_more: bool,
    ) -> None:
        async with self._lock:
            if self._disabled:
                return
            fetched = max(0, int(fetched_pages or 0))
            try:
                known_total = int(total_pages) if total_pages is not None else 0
            except Exception:
                known_total = 0
            if known_total <= 0:
                known_total = fetched + (1 if has_more else 0)
            known_total = max(known_total, fetched, 1)
            current_key = self._normalize_page_key(key)
            self._page_current[current_key] = max(fetched, self._page_current.get(current_key, 0))
            self._page_total[current_key] = max(known_total, self._page_total.get(current_key, 0))
            self.current = sum(self._page_current.values())
            self.total = max(sum(self._page_total.values()), self.current, 1)
            if self.callback:
                self.callback(self.current, self.total)


def _attach_account_id(items: list, api_account_id: int) -> None:
    for it in items:
        if isinstance(it, dict):
            it["api_account_id"] = api_account_id


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _to_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_brand_name(value: Any) -> str:
    if isinstance(value, dict):
        return _compact_text(value.get("name"))
    return _compact_text(value)


def _normalize_brand_id(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("id")
    return None


def _normalize_category_name(value: Any) -> str:
    if isinstance(value, dict):
        return _compact_text(value.get("name"))
    return _compact_text(value)


def _normalize_image_rows(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            url = _compact_text(row.get("url") or row.get("imageUrl") or row.get("link"))
            packed = dict(row)
        else:
            url = _compact_text(row)
            packed = {"url": url}
        if not url or url in seen:
            continue
        seen.add(url)
        packed["url"] = url
        out.append(packed)
    return out


def _merge_attribute_rows(*groups: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        rows = group if isinstance(group, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            packed = dict(row)
            key = json.dumps(packed, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            out.append(packed)
    return out


def _product_id_from_listing_row(item: dict[str, Any]) -> str:
    content_id = _compact_text(item.get("contentId") or item.get("productContentId") or item.get("platformListingId"))
    barcode = _compact_text(item.get("barcode"))
    if content_id and barcode:
        return f"{content_id}:{barcode}"
    stock_code = _compact_text(item.get("stockCode") or item.get("stock_code"))
    if content_id and stock_code:
        return f"{content_id}:{stock_code}"
    for key in ("variantId", "stockId", "id"):
        value = _compact_text(item.get(key))
        if value:
            return value
    for key in ("productId", "product_id", "contentId", "platformListingId"):
        value = _compact_text(item.get(key))
        if value:
            return value
    if barcode:
        return barcode
    product_main_id = _compact_text(item.get("productMainId"))
    if stock_code and product_main_id:
        return f"{product_main_id}:{stock_code}"
    return stock_code


def _flatten_approved_items(items: list[Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for content in items:
        if not isinstance(content, dict):
            continue
        shared_images = _normalize_image_rows(content.get("images") or content.get("media"))
        shared_attributes = _merge_attribute_rows(content.get("attributes"))
        brand = content.get("brand")
        category = content.get("category")
        variants = content.get("variants") if isinstance(content.get("variants"), list) else []
        if not variants:
            variants = [{}]

        for variant in variants:
            variant = dict(variant) if isinstance(variant, dict) else {}
            price_block = variant.get("price") if isinstance(variant.get("price"), dict) else {}
            stock_block = variant.get("stock") if isinstance(variant.get("stock"), dict) else {}
            currency_code = _compact_text(
                variant.get("currencyCode")
                or price_block.get("currency")
                or price_block.get("currencyCode")
                or content.get("currencyCode")
            ).upper()
            row = {
                "productId": _product_id_from_listing_row(
                    {
                        **content,
                        **variant,
                        "platformListingId": content.get("contentId") or variant.get("platformListingId"),
                    }
                ),
                "platformListingId": content.get("contentId") or variant.get("platformListingId"),
                "productContentId": content.get("contentId"),
                "productMainId": content.get("productMainId"),
                "title": content.get("title") or variant.get("title"),
                "description": content.get("description") or variant.get("description"),
                "barcode": variant.get("barcode") or content.get("barcode"),
                "stockCode": variant.get("stockCode") or content.get("stockCode"),
                "brand": _normalize_brand_name(brand or variant.get("brand")),
                "brandId": _normalize_brand_id(brand or variant.get("brand")),
                "categoryName": _normalize_category_name(category or variant.get("category")),
                "quantity": _to_float(
                    variant.get("quantity")
                    or variant.get("stockQuantity")
                    or stock_block.get("quantity")
                    or stock_block.get("stockQuantity")
                    or content.get("quantity")
                ),
                "approved": True,
                "archived": variant.get("archived"),
                "onSale": variant.get("onSale"),
                "listPrice": _to_float(variant.get("listPrice") or price_block.get("listPrice")),
                "salePrice": _to_float(variant.get("salePrice") or price_block.get("salePrice")),
                "currencyCode": currency_code or None,
                "vatRate": _to_float(variant.get("vatRate") or content.get("vatRate")),
                "dimensionalWeight": _to_float(variant.get("dimensionalWeight") or content.get("dimensionalWeight")),
                "deliveryOption": (
                    variant.get("deliveryOption")
                    or variant.get("deliveryOptions")
                    or content.get("deliveryOption")
                    or content.get("deliveryOptions")
                ),
                "images": list(shared_images),
                "attributes": _merge_attribute_rows(
                    shared_attributes,
                    variant.get("attributes"),
                    variant.get("attributeValues"),
                ),
                "productUrl": variant.get("productUrl") or content.get("productUrl"),
                "locked": variant.get("locked"),
                "hasActiveCampaign": variant.get("hasActiveCampaign") or content.get("hasActiveCampaign"),
                "version": content.get("version") or variant.get("version"),
                "createDateTime": variant.get("sellerCreatedDate") or content.get("createDateTime") or content.get("creationDate"),
                "lastUpdateDate": variant.get("sellerModifiedDate") or content.get("lastUpdateDate") or content.get("lastModifiedDate"),
                "rawSource": {"content": content, "variant": variant, "endpoint": "approved_v2"},
            }
            if _compact_text(row.get("productId")):
                flattened.append(row)
    return flattened


def _flatten_unapproved_items(items: list[Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        price_block = item.get("price") if isinstance(item.get("price"), dict) else {}
        row = dict(item)
        row.update(
            {
                "productId": _product_id_from_listing_row(item),
                "brand": _normalize_brand_name(item.get("brand") or item.get("brandName")),
                "brandId": item.get("brandId") or _normalize_brand_id(item.get("brand")),
                "categoryName": _normalize_category_name(item.get("category") or item.get("categoryName")),
                "images": _normalize_image_rows(item.get("images") or item.get("media")),
                "attributes": _merge_attribute_rows(item.get("attributes"), item.get("attributeValues")),
                "approved": False if item.get("approved") is None else item.get("approved"),
                "listPrice": _to_float(item.get("listPrice") or price_block.get("listPrice")),
                "salePrice": _to_float(item.get("salePrice") or price_block.get("salePrice")),
                "currencyCode": _compact_text(
                    item.get("currencyCode") or price_block.get("currency") or price_block.get("currencyCode")
                ).upper() or None,
                "deliveryOption": item.get("deliveryOption") or item.get("deliveryOptions"),
                "rawSource": {"item": item, "endpoint": "unapproved_v2"},
            }
        )
        if _compact_text(row.get("productId")):
            flattened.append(row)
    return flattened


def _normalize_listing_api_items(items: list[Any], approved: Optional[bool]) -> list[dict[str, Any]]:
    approved_rows: list[dict[str, Any]] = []
    unapproved_rows: list[dict[str, Any]] = []
    for row in list(items or []):
        if not isinstance(row, dict):
            continue
        packed = dict(row)
        state = approved if approved is not None else packed.pop("_listingApprovedState", None)
        if bool(state):
            approved_rows.append(packed)
        else:
            unapproved_rows.append(packed)
    return _flatten_approved_items(approved_rows) + _flatten_unapproved_items(unapproved_rows)


def _norm_status(value: Any) -> str:
    return str(value or "").strip().upper()


def _status_is_success(status: str, failure_reasons: list) -> bool:
    if failure_reasons:
        return False
    return status in {"SUCCESS", "COMPLETED", "OK"}


def _status_is_failure(status: str, failure_reasons: list) -> bool:
    if failure_reasons:
        return True
    return status in {"FAILURE", "FAILED", "ERROR", "REJECTED"}


def _find_item_status(payload: Any, barcode: str) -> tuple[Optional[str], list]:
    if not isinstance(payload, dict):
        return None, []
    items = payload.get("items") or payload.get("content") or payload.get("data") or []
    if not isinstance(items, list):
        return None, []
    target = str(barcode or "")
    for item in items:
        if not isinstance(item, dict):
            continue
        req_item = item.get("requestItem") or item.get("request_item") or {}
        req_barcode = None
        if isinstance(req_item, dict):
            req_barcode = req_item.get("barcode") or req_item.get("stockCode")
            if not req_barcode:
                product = req_item.get("product") or {}
                if isinstance(product, dict):
                    req_barcode = product.get("barcode")
        if not req_barcode:
            req_barcode = item.get("barcode")
        if req_barcode is not None and str(req_barcode) == target:
            status = item.get("status")
            failure = item.get("failureReasons") or item.get("failure_reasons") or []
            if not isinstance(failure, list):
                failure = [failure]
            return str(status or "").strip(), failure
    return None, []


def _find_content_item_status(payload: Any, content_id: int) -> tuple[Optional[str], list]:
    if not isinstance(payload, dict):
        return None, []
    items = payload.get("items") or payload.get("content") or payload.get("data") or []
    if not isinstance(items, list):
        return None, []
    target = str(int(content_id or 0))
    for item in items:
        if not isinstance(item, dict):
            continue
        request_item = item.get("requestItem") or item.get("request_item") or {}
        request_content_id = None
        if isinstance(request_item, dict):
            request_content_id = request_item.get("contentId") or request_item.get("content_id")
            if request_content_id in (None, ""):
                product = request_item.get("product") or {}
                if isinstance(product, dict):
                    request_content_id = product.get("contentId") or product.get("content_id")
        if request_content_id in (None, ""):
            request_content_id = item.get("contentId") or item.get("content_id")
        if request_content_id is not None and str(request_content_id) == target:
            status = item.get("status")
            failure = item.get("failureReasons") or item.get("failure_reasons") or []
            if not isinstance(failure, list):
                failure = [failure]
            return str(status or "").strip(), failure
    return None, []


async def fetch_listings_for_account(
    api: TrendyolListingApi,
    *,
    api_account_id: int,
    page: int = 0,
    size: int = 50,
    approved: Optional[bool] = None,
    barcode: Optional[str] = None,
    stock_code: Optional[str] = None,
    product_main_id: Optional[str] = None,
    brand_ids: Any = None,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
    date_query_type: Optional[str] = None,
    status: Optional[str] = None,
    next_page_token: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    fetch_all_pages: bool = False,
    max_pages: Optional[int] = None,
    tracker: Optional[_ProgressTracker] = None,
) -> Result:
    try:
        if fetch_all_pages:
            async def _page_progress(
                fetched_pages: int,
                total_pages: int | None,
                has_more: bool,
                state: str | None = None,
            ) -> None:
                if tracker is not None:
                    await tracker.set_page_progress(
                        (api_account_id, state or "all"),
                        fetched_pages,
                        total_pages,
                        has_more,
                    )

            res = await api.list_products_all(
                start_page=page,
                size=size,
                approved=approved,
                barcode=barcode,
                stock_code=stock_code,
                product_main_id=product_main_id,
                brand_ids=brand_ids,
                start_date=start_date,
                end_date=end_date,
                date_query_type=date_query_type,
                status=status,
                next_page_token=next_page_token,
                extra_params=extra_params,
                max_pages=max_pages,
                page_progress_callback=_page_progress,
            )
            if not res.success:
                return res
            all_items = _normalize_listing_api_items((res.data or {}).get("items", []) or [], approved)
            _attach_account_id(all_items, api_account_id)
            fetched_pages = int((res.data or {}).get("pages_fetched") or 0)
            total_pages = (res.data or {}).get("totalPages")
            total_elements = (res.data or {}).get("totalElements")

            return Result.ok(
                "Listing fetched for account.",
                close_dialog=False,
                data={
                    "items": all_items,
                    "pages_fetched": fetched_pages,
                    "totalPages": total_pages,
                    "totalElements": total_elements,
                    "last_page": (res.data or {}).get("last_page"),
                },
            )

        res = await api.list_products(
            page=page,
            size=size,
            approved=approved,
            barcode=barcode,
            stock_code=stock_code,
            product_main_id=product_main_id,
            brand_ids=brand_ids,
            start_date=start_date,
            end_date=end_date,
            date_query_type=date_query_type,
            status=status,
            next_page_token=next_page_token,
            extra_params=extra_params,
        )

        if not res.success:
            return res

        items = _normalize_listing_api_items((res.data or {}).get("items", []) or [], approved)
        _attach_account_id(items, api_account_id)

        return Result.ok(
            "Listing fetched for account.",
            close_dialog=False,
            data={
                "items": items,
                "meta": res.data or {},
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


async def fetch_listings_all(
    comp_api_account_list: list,
    *,
    page: int = 0,
    size: int = 50,
    approved: Optional[bool] = None,
    barcode: Optional[str] = None,
    stock_code: Optional[str] = None,
    product_main_id: Optional[str] = None,
    brand_ids: Any = None,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
    date_query_type: Optional[str] = None,
    status: Optional[str] = None,
    next_page_token: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    fetch_all_pages: bool = False,
    max_pages: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Result:
    """
    comp_api_account_list item layout (expected):
      [pk, api_key, api_secret, seller_id, accept_language, environment, credential_reference]
    """
    try:
        if not comp_api_account_list:
            return Result.fail("Company list is empty.", close_dialog=False)

        expected_page_keys: tuple[tuple[Any, str], ...] | None = None
        tracker_total = len(comp_api_account_list)
        if fetch_all_pages:
            states = ("approved", "unapproved") if approved is None else ("approved" if approved else "unapproved",)
            expected_page_keys = tuple(
                (comp_api_account[0], state)
                for comp_api_account in comp_api_account_list
                for state in states
            )
            tracker_total = max(len(expected_page_keys), 1)
        tracker = _ProgressTracker(
            total=tracker_total,
            callback=progress_callback,
            expected_page_keys=expected_page_keys,
        )

        all_items: list = []
        all_meta: list = []
        account_ids: list[int] = []

        for comp_api_account in comp_api_account_list:
            acc_pk = comp_api_account[0]
            api_key = comp_api_account[1]
            api_secret = comp_api_account[2]
            seller_id = comp_api_account[3]
            accept_language = str(comp_api_account[4] or "").strip() if len(comp_api_account) > 4 else ""
            raw_environment = comp_api_account[5] if len(comp_api_account) > 5 else "production"
            if isinstance(raw_environment, dict):
                environment = _compact_text(
                    raw_environment.get("environment")
                    or raw_environment.get("api_environment")
                    or "production"
                )
            else:
                environment = _compact_text(raw_environment) or "production"
            credential_reference = (
                _compact_text(comp_api_account[6]) if len(comp_api_account) > 6 else ""
            )

            api = TrendyolListingApi(
                api_key,
                api_secret,
                seller_id,
                accept_language=accept_language or None,
                environment=environment,
                credential_reference=credential_reference or None,
            )

            res = await fetch_listings_for_account(
                api=api,
                api_account_id=acc_pk,
                page=page,
                size=size,
                approved=approved,
                barcode=barcode,
                stock_code=stock_code,
                product_main_id=product_main_id,
                brand_ids=brand_ids,
                start_date=start_date,
                end_date=end_date,
                date_query_type=date_query_type,
                status=status,
                next_page_token=next_page_token,
                extra_params=extra_params,
                fetch_all_pages=fetch_all_pages,
                max_pages=max_pages,
                tracker=tracker,
            )

            if not res.success:
                return res

            items = (res.data or {}).get("items", []) or []
            all_items.extend(items)
            all_meta.append({"api_account_id": acc_pk, "meta": res.data.get("meta")})
            account_ids.append(int(acc_pk))
            if not fetch_all_pages:
                await tracker.step(1)

        return Result.ok(
            "Listings fetched.",
            close_dialog=False,
            data={
                "items": all_items,
                "per_account": all_meta,
                "total_items": len(all_items),
                "api_account_ids": account_ids,
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


async def update_price_and_inventory_for_account(
    *,
    api_key: str,
    api_secret: str,
    seller_id: str,
    items: list[dict],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    barcode: Optional[str] = None,
    wait_result: bool = True,
    poll_interval: float = 1.5,
    max_wait: float = 60.0,
    environment: str = "production",
    accept_language: Optional[str] = None,
    credential_reference: Optional[str] = None,
) -> Result:
    try:
        if not items:
            return Result.fail("Gönderilecek ürün yok.", close_dialog=False)

        api = TrendyolListingApi(
            api_key,
            api_secret,
            seller_id,
            environment=environment,
            accept_language=accept_language,
            credential_reference=credential_reference,
        )
        res = await api.update_price_and_inventory(items=items)
        if not res.success:
            return res

        batch_request_id = (res.data or {}).get("batch_request_id")
        if not wait_result or not batch_request_id or not barcode:
            return res

        deadline = time.monotonic() + float(max_wait)
        last_status = None
        last_failure: list = []

        while time.monotonic() < deadline:
            check = await api.get_batch_request_result(batch_request_id=str(batch_request_id))
            if not check.success:
                await asyncio.sleep(poll_interval)
                continue

            raw = (check.data or {}).get("raw") or {}
            status, failure = _find_item_status(raw, barcode)
            if status:
                last_status = status
                last_failure = failure
                norm = _norm_status(status)
                if _status_is_success(norm, failure):
                    return Result.ok(
                        "Stok/fiyat güncellendi.",
                        close_dialog=False,
                        data={
                            "batch_request_id": batch_request_id,
                            "item_status": norm,
                            "raw": raw,
                        },
                    )
                if _status_is_failure(norm, failure):
                    reason = ""
                    if failure:
                        reason = f" Neden: {', '.join(str(x) for x in failure if x)}"
                    return Result.fail(
                        f"Stok/fiyat güncellenemedi.{reason}",
                        close_dialog=False,
                        data={
                            "batch_request_id": batch_request_id,
                            "item_status": norm,
                            "raw": raw,
                        },
                    )

            await asyncio.sleep(poll_interval)

        return Result.ok(
            "İşlem doğrulama aşamasında.",
            close_dialog=False,
            data={
                "pending": True,
                "batch_request_id": batch_request_id,
                "item_status": _norm_status(last_status),
                "failure_reasons": last_failure,
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


async def update_approved_content_for_account(
    *,
    api_key: str,
    api_secret: str,
    seller_id: str,
    items: list[dict],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    content_id: Optional[int] = None,
    wait_result: bool = True,
    poll_interval: float = 1.5,
    max_wait: float = 60.0,
    environment: str = "production",
    accept_language: Optional[str] = None,
    credential_reference: Optional[str] = None,
) -> Result:
    try:
        if not items:
            return Result.fail("Gönderilecek içerik güncellemesi yok.", close_dialog=False)
        api = TrendyolListingApi(
            api_key,
            api_secret,
            seller_id,
            environment=environment,
            accept_language=accept_language,
            credential_reference=credential_reference,
        )
        result = await api.update_approved_content(items=items)
        if not result.success:
            return result
        batch_request_id = (result.data or {}).get("batch_request_id")
        if not wait_result or not batch_request_id or not content_id:
            return result

        deadline = time.monotonic() + float(max_wait)
        last_status = None
        last_failure: list = []
        while time.monotonic() < deadline:
            check = await api.get_batch_request_result(batch_request_id=str(batch_request_id))
            if not check.success:
                await asyncio.sleep(poll_interval)
                continue
            raw = (check.data or {}).get("raw") or {}
            status, failure = _find_content_item_status(raw, int(content_id))
            if status:
                last_status = status
                last_failure = failure
                normalized_status = _norm_status(status)
                if _status_is_success(normalized_status, failure):
                    return Result.ok(
                        "Onaylı ürün içeriği güncellendi.",
                        close_dialog=False,
                        data={
                            "verified": True,
                            "batch_request_id": batch_request_id,
                            "content_id": int(content_id),
                            "item_status": normalized_status,
                            "raw": raw,
                        },
                    )
                if _status_is_failure(normalized_status, failure):
                    reason = f" Neden: {', '.join(str(x) for x in failure if x)}" if failure else ""
                    return Result.fail(
                        f"Onaylı ürün içeriği güncellenemedi.{reason}",
                        close_dialog=False,
                        data={
                            "verified": True,
                            "batch_request_id": batch_request_id,
                            "content_id": int(content_id),
                            "item_status": normalized_status,
                            "raw": raw,
                        },
                    )
            await asyncio.sleep(poll_interval)
        return Result.ok(
            "İçerik güncellemesi doğrulama aşamasında.",
            close_dialog=False,
            data={
                "verified": False,
                "pending": True,
                "batch_request_id": batch_request_id,
                "content_id": int(content_id),
                "item_status": _norm_status(last_status),
                "failure_reasons": last_failure,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


async def check_batch_request_for_account(
    *,
    api_key: str,
    api_secret: str,
    seller_id: str,
    batch_request_id: str,
    barcode: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    environment: str = "production",
    accept_language: Optional[str] = None,
    credential_reference: Optional[str] = None,
) -> Result:
    try:
        if not batch_request_id or not barcode:
            return Result.fail("Batch request bilgisi eksik.", close_dialog=False)

        api = TrendyolListingApi(
            api_key,
            api_secret,
            seller_id,
            environment=environment,
            accept_language=accept_language,
            credential_reference=credential_reference,
        )
        check = await api.get_batch_request_result(batch_request_id=str(batch_request_id))
        if not check.success:
            return check

        raw = (check.data or {}).get("raw") or {}
        status, failure = _find_item_status(raw, barcode)
        if status:
            norm = _norm_status(status)
            if _status_is_success(norm, failure):
                return Result.ok(
                    "Stok/fiyat güncellendi.",
                    close_dialog=False,
                    data={
                        "verified": True,
                        "item_status": norm,
                        "raw": raw,
                    },
                )
            if _status_is_failure(norm, failure):
                reason = ""
                if failure:
                    reason = f" Neden: {', '.join(str(x) for x in failure if x)}"
                return Result.fail(
                    f"Stok/fiyat güncellenemedi.{reason}",
                    close_dialog=False,
                    data={
                        "verified": True,
                        "item_status": norm,
                        "raw": raw,
                    },
                )

        return Result.ok(
            "İşlem doğrulama aşamasında.",
            close_dialog=False,
            data={"pending": True, "raw": raw},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
