from __future__ import annotations

from typing import Any, Optional, Union

from Core.api.Api_engine import ConfiguredMarketplaceOperationApi
from Marketplaces.api.trendyol.base_api import BaseTrendyolApi
from Core.utils.request_utils import async_make_request
from Feedback.processors.pipeline import Result


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _coerce_paginated_body(raw_body: Any, *, default_page: int = 0) -> dict[str, Any]:
    if isinstance(raw_body, dict):
        content = _as_list(raw_body.get("content"))
        if not content:
            content = _as_list(raw_body.get("items"))
        if not content:
            content = _as_list(raw_body.get("data"))
        return {
            "content": content,
            "totalPages": _to_int(raw_body.get("totalPages"), default=0),
            "page": _to_int(raw_body.get("page"), default=default_page),
            "totalElements": _to_int(raw_body.get("totalElements"), default=len(content)),
        }

    content = _as_list(raw_body)
    return {
        "content": content,
        "totalPages": 1 if content else 0,
        "page": int(default_page),
        "totalElements": len(content),
    }


class TrendyolApi(ConfiguredMarketplaceOperationApi, BaseTrendyolApi):
    """
    Trendyol orders API client.

    Marketplaces owns the static contract:
    - endpoint path / method
    - query defaults
    - request field mappings
    - success and error messages

    This class stays focused on runtime behavior:
    - authentication / headers
    - validation
    - request execution
    - response shaping
    """

    PLATFORM_CODE = "TRENDYOL"
    API_SCOPE = "orders"

    async def _send_request(self, **kwargs) -> Result:
        return await async_make_request(**kwargs)

    async def find_orders(
        self,
        status: str,
        start_date: int,
        end_date: int,
        page: int,
        size: int = 50,
    ) -> Result:
        operation_name = "list_orders"
        res = await self._execute_operation(
            operation_name,
            request_values={
                "status": status,
                "start_date": start_date,
                "end_date": end_date,
                "page": page,
                "size": size,
            },
            fallback_message="Siparisler basariyla alindi.",
        )
        if not res.success:
            return res

        payload = dict(res.data or {})
        body = _coerce_paginated_body(payload.get("json"), default_page=page)
        return Result.ok(
            str((payload.get("profile") or {}).get("successMessage") or "Siparisler basariyla alindi."),
            close_dialog=False,
            data={
                "environment": self.environment,
                "seller_id": self.supplier_id,
                "content": body.get("content", []) or [],
                "totalPages": body.get("totalPages", 0),
                "page": body.get("page", 0),
                "totalElements": body.get("totalElements", 0),
                "status_code": payload.get("status_code", 0),
                "request_attempts": int(payload.get("request_attempts", 1) or 1),
                "request_retries": int(payload.get("request_retries", 0) or 0),
            },
        )

    async def get_order_by_number(
        self,
        order_number: str,
        page: int = 0,
        size: int = 50,
    ) -> Result:
        order_number_text = str(order_number or "").strip()
        if not order_number_text:
            return Result.fail("Gecersiz orderNumber.", close_dialog=False)

        operation_name = "get_order_by_number"
        res = await self._execute_operation(
            operation_name,
            request_values={
                "order_number": order_number_text,
                "page": page,
                "size": size,
            },
            fallback_message="Siparis basariyla alindi.",
        )
        if not res.success:
            return res

        payload = dict(res.data or {})
        body = _coerce_paginated_body(payload.get("json"), default_page=page)
        content = body.get("content", []) or []
        message = (
            str((payload.get("profile") or {}).get("successMessage") or "Siparis basariyla alindi.")
            if content
            else "Bu orderNumber icin siparis bulunamadi."
        )
        return Result.ok(
            message,
            close_dialog=False,
            data={
                "environment": self.environment,
                "seller_id": self.supplier_id,
                "content": content,
                "totalPages": body.get("totalPages", 0),
                "page": body.get("page", 0),
                "totalElements": body.get("totalElements", 0),
                "status_code": payload.get("status_code", 0),
                "request_attempts": int(payload.get("request_attempts", 1) or 1),
                "request_retries": int(payload.get("request_retries", 0) or 0),
            },
        )

    async def find_claims(
        self,
        *,
        start_date: int,
        end_date: int,
        page: int = 0,
        size: int = 50,
        claim_item_status: Optional[str] = None,
        order_shipment_package_id: Optional[Union[int, str]] = None,
        shipment_package_id: Optional[Union[int, str]] = None,
        claim_ids: Optional[list[str]] = None,
        order_number: Optional[Union[int, str]] = None,
    ) -> Result:
        operation_name = "list_claims"
        package_value = (
            order_shipment_package_id
            if order_shipment_package_id not in (None, "")
            else shipment_package_id
        )
        res = await self._execute_operation(
            operation_name,
            request_values={
                "start_date": int(start_date),
                "end_date": int(end_date),
                "page": int(page),
                "size": int(size),
                "claim_item_status": claim_item_status,
                "order_shipment_package_id": package_value,
                "claim_ids": claim_ids or [],
                "order_number": order_number,
            },
            fallback_message="Iadeler basariyla alindi.",
        )
        if not res.success:
            return res

        payload = dict(res.data or {})
        body = _coerce_paginated_body(payload.get("json"), default_page=page)
        return Result.ok(
            str((payload.get("profile") or {}).get("successMessage") or "Iadeler basariyla alindi."),
            close_dialog=False,
            data={
                "environment": self.environment,
                "seller_id": self.supplier_id,
                "content": body.get("content", []) or [],
                "totalPages": int(body.get("totalPages", 0) or 0),
                "page": int(body.get("page", page) or page),
                "totalElements": int(body.get("totalElements", 0) or 0),
                "status_code": payload.get("status_code", 0),
                "request_attempts": int(payload.get("request_attempts", 1) or 1),
                "request_retries": int(payload.get("request_retries", 0) or 0),
            },
        )

    async def approve_claim_line_items(
        self,
        *,
        claim_id: Union[int, str],
        claim_line_item_ids: list[Union[int, str]],
    ) -> Result:
        claim_id_text = str(claim_id or "").strip()
        if not claim_id_text:
            return Result.fail("Gecersiz claim id.", close_dialog=False)

        normalized_line_ids = list(
            dict.fromkeys(
                str(row or "").strip()
                for row in (claim_line_item_ids or [])
                if str(row or "").strip()
            )
        )
        if not normalized_line_ids:
            return Result.fail("Onaylanacak claim line item bulunamadi.", close_dialog=False)

        operation_name = "approve_claim_line_items"
        res = await self._execute_operation(
            operation_name,
            request_values={
                "claim_id": claim_id_text,
                "claim_line_item_ids": normalized_line_ids,
            },
            fallback_message="Iade onayi gonderildi.",
        )
        if not res.success:
            return res

        payload = dict(res.data or {})
        return Result.ok(
            str((payload.get("profile") or {}).get("successMessage") or "Iade onayi gonderildi."),
            close_dialog=False,
            data={
                "environment": self.environment,
                "seller_id": self.supplier_id,
                "status_code": payload.get("status_code", 0),
                "request_attempts": int(payload.get("request_attempts", 1) or 1),
                "request_retries": int(payload.get("request_retries", 0) or 0),
                "response": payload.get("json"),
                "request": payload.get("request_json", {}),
                "claim_id": claim_id_text,
            },
        )

    async def change_cargo_provider(
        self,
        *,
        package_id: Union[int, str],
        cargo_provider: str,
    ) -> Result:
        package_id_text = str(package_id or "").strip()
        cargo_provider_code = str(cargo_provider or "").strip().upper()
        if not package_id_text:
            return Result.fail("Gecersiz shipment package id.", close_dialog=False)
        if not cargo_provider_code:
            return Result.fail("Gecersiz kargo saglayici kodu.", close_dialog=False)

        operation_name = "change_cargo_provider"
        res = await self._execute_operation(
            operation_name,
            request_values={
                "package_id": package_id_text,
                "cargo_provider": cargo_provider_code,
            },
            fallback_message="Kargo saglayici guncellendi.",
        )
        if not res.success:
            return res

        payload = dict(res.data or {})
        return Result.ok(
            str((payload.get("profile") or {}).get("successMessage") or "Kargo saglayici guncellendi."),
            close_dialog=False,
            data={
                "environment": self.environment,
                "seller_id": self.supplier_id,
                "status_code": payload.get("status_code", 0),
                "request_attempts": int(payload.get("request_attempts", 1) or 1),
                "request_retries": int(payload.get("request_retries", 0) or 0),
                "response": payload.get("json"),
                "package_id": package_id_text,
                "cargo_provider": cargo_provider_code,
            },
        )
