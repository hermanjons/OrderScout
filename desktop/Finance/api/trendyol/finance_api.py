from __future__ import annotations

from typing import Any

from Core.api.Api_engine import ConfiguredMarketplaceOperationApi
from Marketplaces.api.trendyol.base_api import BaseTrendyolApi
from Core.utils.request_utils import async_make_request
from Feedback.processors.pipeline import Result
from Finance.constants.trendyol.constants import FINANCE_API_SCOPE, FINANCE_PLATFORM_TRENDYOL
from Marketplaces.constants.catalog_constants import marketplace_api_scope_profile


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _extract_items(payload: Any) -> list:
    if isinstance(payload, dict):
        for key in ("content", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    if isinstance(payload, list):
        return payload
    return []


def _extract_total_pages(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("totalPages", "pageCount", "pages"):
        if key in payload:
            value = _as_int(payload.get(key), default=-1)
            if value >= 0:
                return value
    return None


def _extract_total_elements(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("totalElements", "totalCount", "count"):
        if key in payload:
            value = _as_int(payload.get(key), default=-1)
            if value >= 0:
                return value
    return None


class TrendyolFinanceApi(ConfiguredMarketplaceOperationApi, BaseTrendyolApi):
    PLATFORM_CODE = FINANCE_PLATFORM_TRENDYOL
    API_SCOPE = FINANCE_API_SCOPE

    def __init__(
        self,
        api_key_id: str | None,
        api_key_secret: str | None,
        supplier_id: str | int | None,
        *,
        base_url: str | None = None,
        environment: str = "production",
        credential_reference: str | None = None,
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
                marketplace_api_scope_profile(
                    self.PLATFORM_CODE,
                    self.API_SCOPE,
                    self.environment,
                ).get("baseUrl")
                or ""
            ).strip().rstrip("/")
            if not environment_base_url or configured_base_url.casefold() != environment_base_url.casefold():
                raise ValueError(
                    "Finance API base URL does not match the selected marketplace environment."
                )
        self.base_url = configured_base_url

    async def _send_request(self, **kwargs) -> Result:
        return await async_make_request(**kwargs)

    def _scope_profile(self) -> dict[str, Any]:
        profile = marketplace_api_scope_profile(
            self.PLATFORM_CODE,
            self.API_SCOPE,
            self.environment,
        )
        if not profile:
            raise RuntimeError("Finance API scope tanÄ±mÄ± bulunamadÄ±.")
        return profile

    def _default_page_size(self) -> int:
        return max(1, _as_int(self._scope_profile().get("defaultPageSize"), 500))

    def _max_page_size(self) -> int:
        return max(1, _as_int(self._scope_profile().get("maxPageSize"), 1000))

    def _sanitize_page_size(self, size: int | None) -> int:
        value = _as_int(size, self._default_page_size())
        if value <= 0:
            value = self._default_page_size()
        return min(value, self._max_page_size())

    async def _get_paginated(
        self,
        *,
        operation_name: str,
        request_values: dict[str, Any],
        fallback_message: str,
    ) -> Result:
        res = await self._execute_operation(
            operation_name,
            request_values=request_values,
            fallback_message=fallback_message,
        )
        if not res.success:
            return res

        payload = dict(res.data or {})
        body = payload.get("json", {}) or {}
        page = _as_int((body or {}).get("page"), _as_int(request_values.get("page"), 0))
        return Result.ok(
            str((payload.get("profile") or {}).get("successMessage") or fallback_message),
            close_dialog=False,
            data={
                "content": _extract_items(body),
                "page": page,
                "totalPages": _extract_total_pages(body),
                "totalElements": _extract_total_elements(body),
                "status_code": payload.get("status_code", 0),
                "raw": body,
            },
        )

    async def get_settlements(
        self,
        *,
        transaction_date_start: int,
        transaction_date_end: int,
        page: int = 0,
        size: int | None = None,
        transaction_type: str | None = None,
    ) -> Result:
        return await self._get_paginated(
            operation_name="list_settlements",
            request_values={
                "transaction_date_start": _as_int(transaction_date_start),
                "transaction_date_end": _as_int(transaction_date_end),
                "page": _as_int(page, 0),
                "size": self._sanitize_page_size(size),
                "transaction_type": transaction_type,
            },
            fallback_message="Uzlasma hareketleri alindi.",
        )

    async def get_other_financials(
        self,
        *,
        transaction_date_start: int,
        transaction_date_end: int,
        page: int = 0,
        size: int | None = None,
        transaction_type: str | None = None,
    ) -> Result:
        return await self._get_paginated(
            operation_name="list_other_financials",
            request_values={
                "transaction_date_start": _as_int(transaction_date_start),
                "transaction_date_end": _as_int(transaction_date_end),
                "page": _as_int(page, 0),
                "size": self._sanitize_page_size(size),
                "transaction_type": transaction_type,
            },
            fallback_message="Diger finansal hareketler alindi.",
        )

    async def get_cargo_invoice_items(
        self,
        *,
        invoice_serial_number: str,
        page: int = 0,
        size: int | None = None,
    ) -> Result:
        serial = str(invoice_serial_number or "").strip()
        if not serial:
            return Result.fail("Fatura seri numarasi bos olamaz.", close_dialog=False)

        res = await self._get_paginated(
            operation_name="list_cargo_invoice_items",
            request_values={
                "invoice_serial_number": serial,
                "page": _as_int(page, 0),
                "size": self._sanitize_page_size(size),
            },
            fallback_message="Kargo fatura kalemleri alindi.",
        )
        if not res.success:
            return res

        data = dict(res.data or {})
        data["invoice_serial_number"] = serial
        return Result.ok(res.message, close_dialog=False, data=data)
