from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _compact_text(value)
        if text:
            return text
    return ""


def _append_distinct(parts: list[str], value: Any) -> None:
    text = _compact_text(value)
    if not text:
        return
    normalized = " ".join(text.casefold().split())
    if any(
        normalized == " ".join(existing.casefold().split())
        for existing in parts
    ):
        return
    parts.append(text)


def normalize_contact_address(
    value: Any,
    *,
    source: str = "",
) -> dict[str, str]:
    """Return one marketplace-neutral, display-ready contact/address record."""

    src = _mapping(value)
    if not src:
        return {}

    nested_lines = _mapping(src.get("addressLines"))
    recipient_name = _first_non_empty(
        src.get("fullName"),
        " ".join(
            part
            for part in (
                _compact_text(src.get("firstName")),
                _compact_text(src.get("lastName")),
            )
            if part
        ),
    )
    phone = _first_non_empty(
        src.get("phone"),
        src.get("phoneNumber"),
        src.get("gsmNumber"),
        src.get("mobilePhone"),
        src.get("mobilePhoneNumber"),
        src.get("telephone"),
    )
    city = _first_non_empty(
        src.get("city"),
        src.get("cityName"),
        src.get("province"),
    )
    district = _first_non_empty(
        src.get("district"),
        src.get("town"),
        src.get("county"),
        src.get("countyName"),
    )
    neighborhood = _first_non_empty(
        src.get("neighborhood"),
        src.get("neighbourhood"),
        src.get("quarter"),
    )
    postal_code = _first_non_empty(
        src.get("postalCode"),
        src.get("zipCode"),
        src.get("zipcode"),
    )
    country_code = _first_non_empty(
        src.get("countryCode"),
        src.get("country"),
    )

    line_parts: list[str] = []
    primary_line = _first_non_empty(
        src.get("fullAddress"),
        src.get("address"),
        src.get("shortAddress"),
    )
    _append_distinct(line_parts, primary_line)
    if not primary_line:
        for candidate in (
            src.get("address1"),
            src.get("address2"),
            src.get("addressLine1"),
            src.get("addressLine2"),
            nested_lines.get("addressLine1"),
            nested_lines.get("addressLine2"),
            neighborhood,
        ):
            _append_distinct(line_parts, candidate)

    address_parts = list(line_parts)
    address_haystack = " ".join(address_parts).casefold()
    for location_part in (neighborhood, district, city, postal_code):
        if location_part and location_part.casefold() not in address_haystack:
            _append_distinct(address_parts, location_part)
            address_haystack = " ".join(address_parts).casefold()

    normalized = {
        "source": _compact_text(source),
        "recipient_name": recipient_name,
        "company": _compact_text(src.get("company")),
        "phone": phone,
        "address": ", ".join(address_parts),
        "neighborhood": neighborhood,
        "district": district,
        "city": city,
        "postal_code": postal_code,
        "country_code": country_code,
    }
    return {
        key: value
        for key, value in normalized.items()
        if value
    }


def select_contact_address(
    shipment_address: Any,
    invoice_address: Any,
) -> dict[str, str]:
    shipment = normalize_contact_address(
        shipment_address,
        source="shipment",
    )
    if shipment:
        return shipment
    return normalize_contact_address(
        invoice_address,
        source="invoice",
    )


def extract_contact_and_address(
    shipment_address: Any,
    invoice_address: Any,
) -> tuple[str, str]:
    contact = select_contact_address(shipment_address, invoice_address)
    return (
        _compact_text(contact.get("phone")) or "-",
        _compact_text(contact.get("address")) or "-",
    )
