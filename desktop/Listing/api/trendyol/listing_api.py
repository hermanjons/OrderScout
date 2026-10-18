from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from Marketplaces.api.trendyol.base_api import BaseTrendyolApi
from Core.utils.request_utils import async_make_request
from Feedback.processors.pipeline import Result, map_error_to_message
from Listing.constants.trendyol.constants import (
    LISTING_TRENDYOL_API_SCOPE,
    LISTING_TRENDYOL_PLATFORM_CODE,
    trendyol_listing_operation_profile,
    trendyol_listing_scope_profile,
    trendyol_listing_status_message,
)


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_items(payload: Any) -> list:
    if isinstance(payload, dict):
        for key in ("content", "items", "products", "data"):
            val = payload.get(key)
            if isinstance(val, list):
                return val
    if isinstance(payload, list):
        return payload
    return []

def _compact_params(params: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple, set)) and not value:
            continue
        out[key] = value
    return out


async def _await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _emit_page_progress(
    callback: Any,
    fetched_pages: int,
    total_pages: Optional[int],
    has_more: bool,
    state: str | None = None,
) -> None:
    if callback is None:
        return
    if state:
        try:
            await _await_maybe(callback(fetched_pages, total_pages, has_more, state))
            return
        except TypeError:
            pass
    await _await_maybe(callback(fetched_pages, total_pages, has_more))

def _sanitize_page_size(size: Any, *, approved: bool) -> int:
    try:
        parsed = int(size)
    except Exception:
        parsed = _default_page_size()
    if parsed <= 0:
        parsed = _default_page_size()
    max_size = _approved_max_page_size() if approved else _unapproved_max_page_size()
    return max(1, min(parsed, max_size))


def _page_boundary_requires_next_token(next_page_index: int, page_size: int) -> bool:
    try:
        next_page = max(int(next_page_index), 0)
        size = max(int(page_size), 1)
    except Exception:
        return False
    return (next_page * size) >= 10_000

def _coerce_brand_ids(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (list, tuple, set)):
        out = [_compact_text(v) for v in value if _compact_text(v)]
        return out or None
    text = _compact_text(value)
    if not text:
        return None
    if "," in text:
        out = [_compact_text(part) for part in text.split(",") if _compact_text(part)]
        return out or None
    return [text]

def _scope_profile(environment: str = "production") -> dict[str, Any]:
    return trendyol_listing_scope_profile(environment)


def _operation_profile(operation_name: str, environment: str = "production") -> dict[str, Any]:
    return trendyol_listing_operation_profile(operation_name, environment)


def _normalize_approved_content_items(items: Any) -> list[Dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ValueError("Gonderilecek onayli urun icerigi yok.")
    if len(items) > 1000:
        raise ValueError("Tek istekte en fazla 1000 onayli urun icerigi guncellenebilir.")

    normalized: list[Dict[str, Any]] = []
    allowed_fields = {"contentId", "title", "description", "images"}
    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            raise ValueError(f"Icerik guncelleme satiri nesne olmali: {index + 1}.")
        unsupported = sorted(set(raw_item) - allowed_fields)
        if unsupported:
            raise ValueError(
                "Icerik guncellemede desteklenmeyen alan var: " + ", ".join(unsupported)
            )
        try:
            content_id = int(raw_item.get("contentId") or 0)
        except Exception as exc:
            raise ValueError(f"Gecerli contentId gerekir: {index + 1}.") from exc
        if content_id <= 0:
            raise ValueError(f"Gecerli contentId gerekir: {index + 1}.")

        item: Dict[str, Any] = {"contentId": content_id}
        if "title" in raw_item:
            title = _compact_text(raw_item.get("title"))
            if not title:
                raise ValueError(f"Baslik bos olamaz: {index + 1}.")
            if len(title) > 100:
                raise ValueError(f"Baslik en fazla 100 karakter olabilir: {index + 1}.")
            item["title"] = title
        if "description" in raw_item:
            description = _compact_text(raw_item.get("description"))
            if not description:
                raise ValueError(f"Aciklama bos olamaz: {index + 1}.")
            if len(description) > 30_000:
                raise ValueError(f"Aciklama en fazla 30000 karakter olabilir: {index + 1}.")
            item["description"] = description
        if "images" in raw_item:
            raw_images = raw_item.get("images")
            if not isinstance(raw_images, list) or not raw_images:
                raise ValueError(f"Gorseller bos olmayan bir liste olmali: {index + 1}.")
            if len(raw_images) > 8:
                raise ValueError(f"En fazla 8 gorsel gonderilebilir: {index + 1}.")
            images: list[dict[str, str]] = []
            for image_index, raw_image in enumerate(raw_images):
                url = _compact_text(
                    raw_image.get("url") if isinstance(raw_image, dict) else raw_image
                )
                parsed = urlparse(url)
                if parsed.scheme.casefold() != "https" or not parsed.netloc:
                    raise ValueError(
                        f"Gorsel URL HTTPS olmali: {index + 1}/{image_index + 1}."
                    )
                images.append({"url": url})
            item["images"] = images
        if len(item) == 1:
            raise ValueError(
                f"En az bir guncellenecek alan gerekir (title, description veya images): {index + 1}."
            )
        normalized.append(item)
    return normalized


def _default_page_size() -> int:
    try:
        return max(1, int(_scope_profile().get("defaultPageSize") or 50))
    except Exception:
        return 50


def _approved_max_page_size() -> int:
    try:
        return max(1, int(_scope_profile().get("approvedMaxPageSize") or 100))
    except Exception:
        return 100


def _unapproved_max_page_size() -> int:
    try:
        return max(1, int(_scope_profile().get("unapprovedMaxPageSize") or 1000))
    except Exception:
        return 1000


def _merge_listing_result_payloads(results: list[Result], *, size: int) -> Result:
    items: list[dict[str, Any]] = []
    per_state: list[dict[str, Any]] = []
    total_elements = 0
    pages_fetched = 0
    success_messages: list[str] = []
    for result in results:
        if not result.success:
            return result
        payload = result.data or {}
        items.extend(payload.get("items", []) or [])
        pages_fetched += int(payload.get("pages_fetched") or 0)
        try:
            total_elements += int(payload.get("totalElements") or 0)
        except Exception:
            pass
        per_state.append(
            {
                "approved": payload.get("approved"),
                "totalPages": payload.get("totalPages"),
                "totalElements": payload.get("totalElements"),
                "pages_fetched": payload.get("pages_fetched"),
                "nextPageToken": payload.get("nextPageToken"),
            }
        )
        if result.message:
            success_messages.append(str(result.message))
    return Result.ok(
        "Products fetched (all states)." if success_messages else "Products fetched.",
        close_dialog=False,
        data={
            "items": items,
            "size": size,
            "approved": None,
            "pages_fetched": pages_fetched,
            "totalElements": total_elements or len(items),
            "per_state": per_state,
            "totalPages": None,
            "last_page": None,
        },
    )


class TrendyolListingApi(BaseTrendyolApi):
    """
    Trendyol product listing API client aligned with approved/unapproved v2 endpoints.
    """

    PLATFORM_CODE = LISTING_TRENDYOL_PLATFORM_CODE
    API_SCOPE = LISTING_TRENDYOL_API_SCOPE

    def __init__(
        self,
        api_key_id: str | None,
        api_key_secret: str | None,
        supplier_id: str | int | None,
        *,
        base_url: Optional[str] = None,
        approved_products_endpoint: Optional[str] = None,
        unapproved_products_endpoint: Optional[str] = None,
        accept_language: Optional[str] = None,
        environment: str = "production",
        credential_reference: Optional[str] = None,
    ) -> None:
        super().__init__(
            api_key_id,
            api_key_secret,
            supplier_id,
            environment=environment,
            credential_reference=credential_reference,
        )
        configured_base_url = str(base_url or "").strip().rstrip("/")
        if configured_base_url:
            environment_base_url = str(
                _scope_profile(self.environment).get("baseUrl") or ""
            ).strip().rstrip("/")
            if not environment_base_url or configured_base_url.casefold() != environment_base_url.casefold():
                raise ValueError(
                    "Listing API base URL does not match the selected marketplace environment."
                )
        self.base_url = configured_base_url
        self.approved_products_endpoint = str(approved_products_endpoint or "").strip()
        self.unapproved_products_endpoint = str(unapproved_products_endpoint or "").strip()
        self._operation_profile_cache: dict[str, dict[str, Any]] = {}
        self._operation_url_cache: dict[tuple[str, str, tuple[tuple[str, str], ...]], str] = {}
        if _compact_text(accept_language):
            self.header["Accept-Language"] = _compact_text(accept_language)

    def _scope_profile(self) -> dict[str, Any]:
        return _scope_profile(self.environment)

    def _operation_profile(self, operation_name: str) -> dict[str, Any]:
        key = str(operation_name or "").strip()
        cached = self._operation_profile_cache.get(key)
        if cached is not None:
            return cached
        profile = _operation_profile(key, self.environment)
        self._operation_profile_cache[key] = profile
        return profile

    def _operation_url(self, operation_name: str, **path_params: object) -> tuple[str, dict[str, Any]]:
        profile = self._operation_profile(operation_name)
        base_url = self.base_url or str(profile.get("baseUrl") or "").strip().rstrip("/")
        path_template = str(profile.get("path") or "").strip()
        if not base_url or not path_template:
            raise RuntimeError(f"Listing API endpoint URL tanımı eksik: {operation_name}")
        template_values = {
            "sellerId": self.supplier_id,
            "seller_id": self.supplier_id,
            "supplierId": self.supplier_id,
            "supplier_id": self.supplier_id,
        }
        template_values.update({key: value for key, value in path_params.items() if value is not None})
        path_key = tuple(sorted((str(key), str(value)) for key, value in path_params.items() if value is not None))
        cache_key = (str(operation_name or "").strip(), base_url, path_key)
        cached_url = self._operation_url_cache.get(cache_key)
        if cached_url is not None:
            return cached_url, profile
        url = f"{base_url}{path_template.format(**template_values)}"
        self._operation_url_cache[cache_key] = url
        return url, profile

    def _operation_failure_result(
        self,
        operation_name: str,
        *,
        status_code: int = 0,
        body: object = None,
        error: Exception | None = None,
        data: dict[str, Any] | None = None,
        fallback_message: str = "",
    ) -> Result:
        profile = self._operation_profile(operation_name)
        label = str(profile.get("label") or operation_name).strip()
        detail = trendyol_listing_status_message(operation_name, status_code)
        message = (
            f"{label} başarısız: {detail}"
            if detail
            else f"{label} başarısız: {fallback_message}".strip()
            if fallback_message
            else f"{label} başarısız."
        )
        payload = dict(data or {})
        if status_code and "status_code" not in payload:
            payload["status_code"] = status_code
        if body is not None and "response" not in payload:
            payload["response"] = body
        return Result.fail(message, error=error, close_dialog=False, data=payload)

    def _failure_from_request_result(
        self,
        operation_name: str,
        request_result: Result,
        *,
        extra_data: dict[str, Any] | None = None,
    ) -> Result:
        payload = dict(request_result.data or {})
        if extra_data:
            payload.update(extra_data)
        status_code = int(payload.get("status_code") or 0)
        body = payload.get("json")
        return self._operation_failure_result(
            operation_name,
            status_code=status_code,
            body=body,
            error=request_result.error,
            data=payload,
            fallback_message=str(request_result.message or "").strip(),
        )

    def _products_operation_name(self, *, approved: bool) -> str:
        return "list_approved_products" if approved else "list_unapproved_products"

    async def _list_products_single_state(
        self,
        *,
        approved: bool,
        page: int = 0,
        size: int = 50,
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
    ) -> Result:
        try:
            size_value = _sanitize_page_size(size, approved=approved)
            operation_name = self._products_operation_name(approved=approved)
            url, profile = self._operation_url(operation_name)
            params = {
                "size": size_value,
                "barcode": barcode,
                "stockCode": stock_code,
                "productMainId": _compact_text(product_main_id) or None,
                "startDate": start_date,
                "endDate": end_date,
                "dateQueryType": date_query_type,
                "status": status,
            }
            if approved:
                params["brandIds"] = _coerce_brand_ids(brand_ids)
            if _compact_text(next_page_token):
                params["nextPageToken"] = _compact_text(next_page_token)
            else:
                params["page"] = max(int(page), 0)
            if extra_params:
                params.update(_compact_params(dict(extra_params)))
            request_params = dict(profile.get("queryDefaults") or {})
            request_params.update(_compact_params(params))

            res = await async_make_request(
                method=str(profile.get("method") or "GET"),
                url=url,
                headers=self.header,
                auth=self.auth,
                params=request_params,
                timeout=int(profile.get("timeout") or 15),
            )
            if not res.success:
                return self._failure_from_request_result(
                    operation_name,
                    res,
                    extra_data={"request_params": request_params},
                )

            data = res.data.get("json", {})
            status_code = res.data.get("status_code", 0)
            if status_code not in list(profile.get("successStatusCodes") or [200]):
                return self._operation_failure_result(
                    operation_name,
                    status_code=status_code,
                    body=data,
                    data={"status_code": status_code, "request_params": request_params, "response": data},
                )

            raw_items = []
            for row in _extract_items(data):
                if not isinstance(row, dict):
                    continue
                packed = dict(row)
                packed["_listingApprovedState"] = bool(approved)
                raw_items.append(packed)
            return Result.ok(
                str(profile.get("successMessage") or "Products fetched."),
                close_dialog=False,
                data={
                    "items": raw_items,
                    "page": data.get("page", page),
                    "size": size_value,
                    "totalPages": data.get("totalPages"),
                    "totalElements": data.get("totalElements") or data.get("totalItems") or len(raw_items),
                    "nextPageToken": data.get("nextPageToken"),
                    "approved": approved,
                    "status_code": status_code,
                    "raw": data,
                },
            )
        except Exception as e:
            return self._operation_failure_result(operation_name, error=e, fallback_message=map_error_to_message(e))

    async def list_products(
        self,
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
    ) -> Result:
        if approved is None and _compact_text(next_page_token):
            return Result.fail(
                "next_page_token sadece approved durumu seçiliyken kullanılabilir.",
                close_dialog=False,
            )
        if approved is None:
            results = await asyncio.gather(
                self._list_products_single_state(
                    approved=True,
                    page=page,
                    size=size,
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
                ),
                self._list_products_single_state(
                    approved=False,
                    page=page,
                    size=size,
                    barcode=barcode,
                    stock_code=stock_code,
                    product_main_id=product_main_id,
                    start_date=start_date,
                    end_date=end_date,
                    date_query_type=date_query_type,
                    status=status,
                    extra_params=extra_params,
                ),
            )
            return _merge_listing_result_payloads(
                list(results),
                size=size,
            )

        return await self._list_products_single_state(
            approved=bool(approved),
            page=page,
            size=size,
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

    async def list_products_all(
        self,
        *,
        start_page: int = 0,
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
        max_pages: Optional[int] = None,
        page_progress_callback: Optional[Any] = None,
    ) -> Result:
        try:
            if approved is None and _compact_text(next_page_token):
                return Result.fail(
                    "next_page_token sadece approved durumu seçiliyken kullanılabilir.",
                    close_dialog=False,
                )
            if approved is None:
                async def _approved_progress(fetched_pages: int, total_pages: Optional[int], has_more: bool, *_args: Any) -> None:
                    await _emit_page_progress(page_progress_callback, fetched_pages, total_pages, has_more, "approved")

                async def _unapproved_progress(fetched_pages: int, total_pages: Optional[int], has_more: bool, *_args: Any) -> None:
                    await _emit_page_progress(page_progress_callback, fetched_pages, total_pages, has_more, "unapproved")

                results = await asyncio.gather(
                    self.list_products_all(
                        start_page=start_page,
                        size=size,
                        approved=True,
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
                        page_progress_callback=_approved_progress,
                    ),
                    self.list_products_all(
                        start_page=start_page,
                        size=size,
                        approved=False,
                        barcode=barcode,
                        stock_code=stock_code,
                        product_main_id=product_main_id,
                        start_date=start_date,
                        end_date=end_date,
                        date_query_type=date_query_type,
                        status=status,
                        extra_params=extra_params,
                        max_pages=max_pages,
                        page_progress_callback=_unapproved_progress,
                    ),
                )
                return _merge_listing_result_payloads(
                    list(results),
                    size=size,
                )

            all_items: list[dict[str, Any]] = []
            page = max(int(start_page), 0)
            fetched_pages = 0
            total_pages = None
            total_elements = None
            current_token = _compact_text(next_page_token) or None
            explicit_token = bool(current_token)
            size_value = _sanitize_page_size(size, approved=bool(approved))

            while True:
                use_token = bool(current_token) and (
                    explicit_token or _page_boundary_requires_next_token(page, size_value)
                )
                res = await self._list_products_single_state(
                    approved=bool(approved),
                    page=page,
                    size=size_value,
                    barcode=barcode,
                    stock_code=stock_code,
                    product_main_id=product_main_id,
                    brand_ids=brand_ids,
                    start_date=start_date,
                    end_date=end_date,
                    date_query_type=date_query_type,
                    status=status,
                    next_page_token=current_token if use_token else None,
                    extra_params=extra_params,
                )
                if not res.success:
                    return res

                payload = res.data or {}
                items = payload.get("items", []) or []
                all_items.extend(items)
                fetched_pages += 1
                total_pages = payload.get("totalPages", total_pages)
                total_elements = payload.get("totalElements", total_elements)
                current_token = _compact_text(payload.get("nextPageToken")) or None
                explicit_token = False
                next_page = page + 1
                total_pages_int = None
                if total_pages is not None:
                    try:
                        total_pages_int = int(total_pages)
                    except Exception:
                        total_pages_int = None
                has_more = False
                if max_pages is not None and fetched_pages >= int(max_pages):
                    has_more = False
                elif current_token and _page_boundary_requires_next_token(next_page, size_value):
                    has_more = True
                elif total_pages_int is not None:
                    has_more = page < (total_pages_int - 1)
                elif len(items) >= int(size_value):
                    has_more = True

                await _emit_page_progress(
                    page_progress_callback,
                    fetched_pages,
                    total_pages_int,
                    has_more,
                    "approved" if approved else "unapproved",
                )

                if not items:
                    break
                if max_pages is not None and fetched_pages >= int(max_pages):
                    break
                if current_token and _page_boundary_requires_next_token(next_page, size_value):
                    page = next_page
                    continue
                if total_pages is not None:
                    if total_pages_int is not None and page >= total_pages_int - 1:
                        break
                if len(items) < int(size_value):
                    break
                page = next_page

            return Result.ok(
                "Products fetched (all pages).",
                close_dialog=False,
                data={
                    "items": all_items,
                    "pages_fetched": fetched_pages,
                    "totalPages": total_pages,
                    "totalElements": total_elements or len(all_items),
                    "last_page": page,
                    "size": size_value,
                    "approved": approved,
                    "nextPageToken": current_token,
                },
            )
        except Exception as e:
            return Result.fail(map_error_to_message(e), error=e, close_dialog=False)

    async def update_price_and_inventory(self, *, items: list[Dict[str, Any]]) -> Result:
        """
        Update price and inventory for given items.
        Payload format: {"items": [{"barcode": str, "quantity": int, "salePrice": float, "listPrice": float}, ...]}
        """
        try:
            if not items:
                return Result.fail("Gonderilecek urun yok.", close_dialog=False)

            operation_name = "update_price_and_inventory"
            url, profile = self._operation_url(operation_name)
            payload = {"items": items}

            res = await async_make_request(
                method=str(profile.get("method") or "POST"),
                url=url,
                headers=self.header,
                auth=self.auth,
                json=payload,
                timeout=int(profile.get("timeout") or 15),
            )

            if not res.success:
                return self._failure_from_request_result(operation_name, res, extra_data={"payload": payload})

            data = res.data.get("json", {})
            status_code = res.data.get("status_code", 0)

            if status_code not in list(profile.get("successStatusCodes") or [200, 201, 202]):
                return self._operation_failure_result(
                    operation_name,
                    status_code=status_code,
                    body=data,
                    data={"status_code": status_code, "response": data, "payload": payload},
                )

            return Result.ok(
                str(profile.get("successMessage") or "Stok/fiyat guncellendi."),
                close_dialog=False,
                data={
                    "status_code": status_code,
                    "batch_request_id": data.get("batchRequestId") or data.get("batchId") or data.get("id"),
                    "raw": data,
                },
            )

        except Exception as e:
            return self._operation_failure_result(
                "update_price_and_inventory",
                error=e,
                fallback_message=map_error_to_message(e),
            )

    async def update_approved_content(self, *, items: list[Dict[str, Any]]) -> Result:
        """Update approved-product title, description and/or HTTPS image URLs via v2."""
        operation_name = "update_approved_content"
        try:
            normalized_items = _normalize_approved_content_items(items)
            url, profile = self._operation_url(operation_name)
            payload = {"items": normalized_items}
            res = await async_make_request(
                method=str(profile.get("method") or "POST"),
                url=url,
                headers=self.header,
                auth=self.auth,
                json=payload,
                timeout=int(profile.get("timeout") or 15),
            )
            if not res.success:
                return self._failure_from_request_result(operation_name, res)
            data = res.data.get("json", {})
            status_code = int(res.data.get("status_code") or 0)
            if status_code not in list(profile.get("successStatusCodes") or [200, 201, 202]):
                return self._operation_failure_result(
                    operation_name,
                    status_code=status_code,
                    body=data,
                    data={"status_code": status_code, "response": data},
                )
            return Result.ok(
                str(profile.get("successMessage") or "Onayli urun icerik guncelleme istegi gonderildi."),
                close_dialog=False,
                data={
                    "status_code": status_code,
                    "batch_request_id": data.get("batchRequestId") or data.get("batchId") or data.get("id"),
                    "raw": data,
                    "item_count": len(normalized_items),
                },
            )
        except Exception as e:
            return self._operation_failure_result(
                operation_name,
                error=e,
                fallback_message=map_error_to_message(e),
            )

    async def get_batch_request_result(self, *, batch_request_id: str) -> Result:
        """
        Fetch batch request result details.
        """
        try:
            if not batch_request_id:
                return Result.fail("Batch request id bulunamadi.", close_dialog=False)

            operation_name = "get_batch_request_result"
            url, profile = self._operation_url(operation_name, batch_request_id=str(batch_request_id))

            res = await async_make_request(
                method=str(profile.get("method") or "GET"),
                url=url,
                headers=self.header,
                auth=self.auth,
                timeout=int(profile.get("timeout") or 15),
            )

            if not res.success:
                return self._failure_from_request_result(
                    operation_name,
                    res,
                    extra_data={"batch_request_id": str(batch_request_id)},
                )

            data = res.data.get("json", {})
            status_code = res.data.get("status_code", 0)

            if status_code not in list(profile.get("successStatusCodes") or [200]):
                return self._operation_failure_result(
                    operation_name,
                    status_code=status_code,
                    body=data,
                    data={"status_code": status_code, "response": data, "batch_request_id": str(batch_request_id)},
                )

            return Result.ok(
                str(profile.get("successMessage") or "Batch request sonucu alindi."),
                close_dialog=False,
                data={"status_code": status_code, "raw": data},
            )

        except Exception as e:
            return self._operation_failure_result(
                "get_batch_request_result",
                error=e,
                fallback_message=map_error_to_message(e),
            )
