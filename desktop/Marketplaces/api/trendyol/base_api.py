from __future__ import annotations

from typing import Any, Mapping

from Core.processors.credential_store import (
    coalesce_credential_bundle_reference,
    is_credential_reference,
    resolve_credential_bundle,
    resolve_secret,
)
from Marketplaces.processors.catalog import normalize_marketplace_environment


def _account_field(account: Any, name: str, default: Any = None) -> Any:
    if isinstance(account, Mapping):
        return account.get(name, default)
    return getattr(account, name, default)


def trendyol_account_client_kwargs(account: Any) -> dict[str, Any]:
    """Build a Trendyol client scope from an ApiAccount-like object without secrets leaking."""

    extra = _account_field(account, "extra_config", None)
    extra_config = dict(extra or {}) if isinstance(extra, Mapping) else {}
    api_key = str(_account_field(account, "api_key", "") or "").strip()
    api_secret = str(_account_field(account, "api_secret", "") or "").strip()
    supplier_id = str(
        _account_field(account, "account_id", "")
        or _account_field(account, "seller_id", "")
        or _account_field(account, "supplier_id", "")
        or ""
    ).strip()
    reference = str(
        extra_config.get("credential_reference")
        or extra_config.get("credential_ref")
        or ""
    ).strip()
    reference, api_key = coalesce_credential_bundle_reference(
        reference,
        api_key,
        companion_value=api_secret,
    )
    environment = normalize_marketplace_environment(
        extra_config.get("environment")
        or extra_config.get("api_environment")
        or "production"
    )
    if not supplier_id:
        raise ValueError("Trendyol seller/supplier ID is required.")
    if not reference and (not api_key or not api_secret):
        raise ValueError("Trendyol API key and API secret are required.")
    return {
        "api_key_id": api_key or None,
        "api_key_secret": api_secret or None,
        "supplier_id": supplier_id,
        "environment": environment,
        "credential_reference": reference or None,
    }


def trendyol_account_payload_client_kwargs(payload: Any) -> dict[str, Any]:
    """Adapt the legacy account row `[pk, key, secret, seller, last_used, extra]`."""

    if isinstance(payload, Mapping) or not isinstance(payload, (list, tuple)):
        return trendyol_account_client_kwargs(payload)
    if len(payload) < 4:
        raise ValueError("Trendyol account payload is incomplete.")
    extra_config = payload[5] if len(payload) >= 6 and isinstance(payload[5], Mapping) else {}
    return trendyol_account_client_kwargs(
        {
            "api_key": payload[1],
            "api_secret": payload[2],
            "account_id": payload[3],
            "extra_config": dict(extra_config or {}),
        }
    )


class BaseTrendyolApi:
    def __init__(
        self,
        api_key_id: str | None = None,
        api_key_secret: str | None = None,
        supplier_id: str | int | None = None,
        *,
        environment: str = "production",
        credential_reference: str | None = None,
    ):
        self.environment = normalize_marketplace_environment(environment)

        reference = str(credential_reference or "").strip()
        key_value = str(api_key_id or "").strip()
        secret_value = str(api_key_secret or "").strip()
        bundle: dict[str, Any] = {}

        reference, key_value = coalesce_credential_bundle_reference(
            reference,
            key_value,
            companion_value=secret_value,
        )
        if reference:
            bundle = resolve_credential_bundle(reference)
        else:
            if is_credential_reference(key_value):
                key_value = resolve_secret(key_value)
            if is_credential_reference(secret_value):
                secret_value = resolve_secret(secret_value)

        bundle_supplier = str(
            bundle.get("seller_id")
            or bundle.get("supplier_id")
            or bundle.get("account_id")
            or ""
        ).strip()
        requested_supplier = str(supplier_id or "").strip()
        if requested_supplier and bundle_supplier and requested_supplier != bundle_supplier:
            raise ValueError("Credential bundle seller does not match requested supplier.")

        self.api_key_id = key_value or str(bundle.get("api_key") or "").strip()
        self.api_key_secret = secret_value or str(bundle.get("api_secret") or "").strip()
        self.supplier_id = requested_supplier or bundle_supplier
        self.integration_code = str(bundle.get("integration_code") or "").strip()
        self.token = str(bundle.get("token") or "").strip()
        self.credential_reference = reference
        self.credential_managed = bool(reference)

        if not self.supplier_id:
            raise ValueError("Trendyol seller/supplier ID is required.")
        if not self.api_key_id or not self.api_key_secret:
            raise ValueError("Trendyol API key and API secret are required.")

        self.header = {
            "User-Agent": f"{self.supplier_id}-SelfIntegration",
            "Content-Type": "application/json",
        }

        self.auth = (self.api_key_id, self.api_key_secret)

    @classmethod
    def from_account(cls, account: Any):
        return cls(**trendyol_account_client_kwargs(account))

    @classmethod
    def from_account_payload(cls, payload: Any):
        return cls(**trendyol_account_payload_client_kwargs(payload))
