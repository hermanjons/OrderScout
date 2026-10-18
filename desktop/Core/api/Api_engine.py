from __future__ import annotations

import asyncio
from typing import Any, Mapping

from Feedback.processors.pipeline import Result, map_error_to_message
from Marketplaces.constants.catalog_constants import (
    marketplace_api_error_code_message,
    marketplace_api_operation_profile,
    marketplace_api_status_message,
)


_SAFE_RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _request_failure_is_transient(result: Result) -> bool:
    payload = dict(result.data or {})
    status_code = int(payload.get("status_code") or 0)
    if status_code:
        return status_code in _TRANSIENT_HTTP_STATUS_CODES
    error = result.error
    if error is None:
        return False
    error_name = type(error).__name__.casefold()
    return any(token in error_name for token in ("timeout", "network", "connect", "transport", "requesterror"))


def _compact_mapping(values: Mapping[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in dict(values or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, set)) and not value:
            continue
        out[str(key)] = value
    return out


def _normalize_string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(dict.fromkeys(str(item or "").strip() for item in value if str(item or "").strip()))
    text = str(value or "").strip()
    if not text:
        return []
    if "," in text:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        return list(dict.fromkeys(parts))
    return [text]


def _apply_transform(name: str, value: Any) -> Any:
    transform = str(name or "").strip().lower()
    if transform in ("", "passthrough"):
        return value
    if transform in ("strip", "string"):
        text = str(value or "").strip()
        return text or None
    if transform == "upper":
        text = str(value or "").strip().upper()
        return text or None
    if transform == "int":
        if value in (None, ""):
            return None
        return int(value)
    if transform == "string_list":
        values = _normalize_string_list(value)
        return values or None
    if transform == "csv_string_list":
        values = _normalize_string_list(value)
        return ",".join(values) if values else None
    raise ValueError(f"Unsupported marketplace request transform: {name!r}")


class ConfiguredMarketplaceOperationApi:
    PLATFORM_CODE = ""
    API_SCOPE = ""

    def _operation_profile(self, operation_name: str) -> dict[str, Any]:
        cache = self.__dict__.setdefault("_operation_profile_cache", {})
        environment = str(getattr(self, "environment", "production") or "production").strip().casefold()
        cache_key = (
            str(self.PLATFORM_CODE),
            str(self.API_SCOPE),
            str(operation_name or ""),
            environment,
        )
        if cache_key in cache:
            return cache[cache_key]
        profile = marketplace_api_operation_profile(
            self.PLATFORM_CODE,
            self.API_SCOPE,
            operation_name,
            environment,
        )
        if not profile.get("path"):
            raise RuntimeError(f"API endpoint profile not found: {self.PLATFORM_CODE}/{self.API_SCOPE}/{operation_name}")
        if not profile.get("environmentSupported"):
            raise RuntimeError(
                "Marketplace environment endpoint is not configured: "
                f"{self.PLATFORM_CODE}/{self.API_SCOPE}/{operation_name}/{environment}"
            )
        cache[cache_key] = profile
        return profile

    def _operation_url(self, operation_name: str, **path_params: object) -> tuple[str, dict[str, Any]]:
        profile = self._operation_profile(operation_name)
        path_key = tuple(sorted((str(key), str(value)) for key, value in dict(path_params or {}).items() if value is not None))
        url_cache = self.__dict__.setdefault("_operation_url_cache", {})
        cache_key = (
            str(self.PLATFORM_CODE),
            str(self.API_SCOPE),
            str(operation_name or ""),
            str(getattr(self, "environment", "production") or "production"),
            str(getattr(self, "base_url", "") or profile.get("baseUrl") or "").strip().rstrip("/"),
            str(getattr(self, "supplier_id", "") or ""),
            path_key,
        )
        if cache_key in url_cache:
            return url_cache[cache_key], profile
        base_url = str(getattr(self, "base_url", "") or profile.get("baseUrl") or "").strip().rstrip("/")
        path_template = str(profile.get("path") or "").strip()
        if not base_url or not path_template:
            raise RuntimeError(
                f"API endpoint URL definition missing: {self.PLATFORM_CODE}/{self.API_SCOPE}/{operation_name}"
            )
        template_values = {
            "sellerId": getattr(self, "supplier_id", None),
            "seller_id": getattr(self, "supplier_id", None),
            "supplierId": getattr(self, "supplier_id", None),
            "supplier_id": getattr(self, "supplier_id", None),
        }
        template_values.update({key: value for key, value in dict(path_params or {}).items() if value is not None})
        url = f"{base_url}{path_template.format(**template_values)}"
        url_cache[cache_key] = url
        return url, profile

    def _build_request_section(self, rules: list[dict[str, Any]], values: Mapping[str, Any] | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        source_values = dict(values or {})
        for rule in list(rules or []):
            source_name = str(rule.get("source") or "").strip()
            target_name = str(rule.get("target") or source_name).strip()
            transform = str(rule.get("transform") or "").strip()
            if not source_name or not target_name:
                continue
            raw_value = source_values.get(source_name)
            value = _apply_transform(transform, raw_value) if transform else raw_value
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, tuple, set)) and not value:
                continue
            out[target_name] = value
        return out

    def _operation_request_parts(
        self,
        operation_name: str,
        *,
        request_values: Mapping[str, Any] | None = None,
        extra_path_params: Mapping[str, Any] | None = None,
        extra_query_params: Mapping[str, Any] | None = None,
        extra_json_payload: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        profile = self._operation_profile(operation_name)
        request_profile = dict(profile.get("request") or {})
        path_params = self._build_request_section(list(request_profile.get("path") or []), request_values)
        query_params = dict(profile.get("queryDefaults") or {})
        query_params.update(self._build_request_section(list(request_profile.get("query") or []), request_values))
        query_params.update(_compact_mapping(extra_query_params))
        json_payload = self._build_request_section(list(request_profile.get("json") or []), request_values)
        json_payload.update(_compact_mapping(extra_json_payload))
        path_params.update(_compact_mapping(extra_path_params))
        return path_params, _compact_mapping(query_params), _compact_mapping(json_payload), profile

    @staticmethod
    def _parse_error_code(body: object) -> str:
        if isinstance(body, dict):
            direct = str(body.get("errorCode") or body.get("code") or "").strip()
            if direct:
                return direct
            errors = body.get("errors")
            if isinstance(errors, list):
                for row in errors:
                    if not isinstance(row, dict):
                        continue
                    nested = str(row.get("errorCode") or row.get("code") or "").strip()
                    if nested:
                        return nested
        return ""

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
        error_code = self._parse_error_code(body)
        detail = ""
        if error_code:
            detail = marketplace_api_error_code_message(
                self.PLATFORM_CODE,
                self.API_SCOPE,
                operation_name,
                error_code,
            )
        if not detail:
            detail = marketplace_api_status_message(
                self.PLATFORM_CODE,
                self.API_SCOPE,
                operation_name,
                status_code,
            )
        message = (
            f"{label} basarisiz: {detail}"
            if detail
            else f"{label} basarisiz: {fallback_message}".strip()
            if fallback_message
            else f"{label} basarisiz."
        )
        payload = dict(data or {})
        if error_code and "error_code" not in payload:
            payload["error_code"] = error_code
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

    async def _send_request(self, **kwargs) -> Result:  # pragma: no cover
        raise NotImplementedError

    async def _execute_operation(
        self,
        operation_name: str,
        *,
        request_values: Mapping[str, Any] | None = None,
        extra_path_params: Mapping[str, Any] | None = None,
        extra_query_params: Mapping[str, Any] | None = None,
        extra_json_payload: Mapping[str, Any] | None = None,
        fallback_message: str = "",
    ) -> Result:
        try:
            path_params, query_params, json_payload, profile = self._operation_request_parts(
                operation_name,
                request_values=request_values,
                extra_path_params=extra_path_params,
                extra_query_params=extra_query_params,
                extra_json_payload=extra_json_payload,
            )
            url, profile = self._operation_url(operation_name, **path_params)
            method = str(profile.get("method") or "GET").strip().upper() or "GET"
            operation_contract = dict(profile.get("operationContract") or {})
            retry_is_safe = (
                method in _SAFE_RETRY_METHODS
                and str(operation_contract.get("retry_behavior") or "").strip().casefold() == "safe"
            )
            max_attempts = (
                max(1, int(profile.get("retryMaxAttempts") or 3))
                if retry_is_safe
                else 1
            )
            retry_backoff_seconds = max(0.0, float(profile.get("retryBackoffSeconds") or 0.25))
            request_result: Result | None = None
            attempts = 0
            for attempt in range(1, max_attempts + 1):
                attempts = attempt
                request_result = await self._send_request(
                    method=method,
                    url=url,
                    headers=getattr(self, "header", None),
                    auth=getattr(self, "auth", None),
                    params=query_params or None,
                    json=json_payload or None,
                    timeout=int(profile.get("timeout") or 15),
                )
                if request_result.success or not _request_failure_is_transient(request_result):
                    break
                if attempt < max_attempts:
                    await asyncio.sleep(retry_backoff_seconds * attempt)

            if request_result is None:  # pragma: no cover - defensive invariant
                raise RuntimeError("Marketplace request was not attempted.")
            request_meta = {
                "environment": str(profile.get("environment") or getattr(self, "environment", "production")),
                "request_params": query_params,
                "request_json": json_payload,
                "path_params": path_params,
                "url": url,
                "request_attempts": attempts,
                "request_retries": max(0, attempts - 1),
            }
            if not request_result.success:
                return self._failure_from_request_result(operation_name, request_result, extra_data=request_meta)

            body = ((request_result.data or {}).get("json", {})) or {}
            status_code = int(((request_result.data or {}).get("status_code", 0)) or 0)
            success_status_codes = list(profile.get("successStatusCodes") or [200])
            if status_code not in success_status_codes:
                return self._operation_failure_result(
                    operation_name,
                    status_code=status_code,
                    body=body,
                    data={**request_meta, "status_code": status_code, "response": body},
                    fallback_message=fallback_message,
                )

            return Result.ok(
                str(profile.get("successMessage") or fallback_message or "Request completed."),
                close_dialog=False,
                data={
                    "json": body,
                    "status_code": status_code,
                    "profile": profile,
                    **request_meta,
                },
            )
        except Exception as e:
            return self._operation_failure_result(
                operation_name,
                error=e,
                fallback_message=map_error_to_message(e),
            )
