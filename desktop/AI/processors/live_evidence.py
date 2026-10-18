from __future__ import annotations

import argparse
import ipaddress
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit


_SECRET_KEYS = {"api_key", "api_secret", "token", "password", "db_name"}
_CUSTOMER_KEYS = {
    "customer",
    "customer_name",
    "customer_full_name",
    "full_customer_name",
    "buyer_name",
    "recipient_name",
    "customer_first_name",
    "customer_last_name",
    "customer_names",
}
_PHONE_KEYS = {"phone", "phone_number", "customer_phone", "recipient_phone"}
_EMAIL_KEYS = {"email", "email_address", "customer_email", "recipient_email"}
_ORDER_KEYS = {
    "order",
    "ordernumber",
    "order_number",
    "order_numbers",
    "target_order",
    "target_order_number",
    "recent_order_numbers",
    "selected_order_numbers",
    "prepared_order_numbers",
    "tool_order_numbers",
    "last_8_days_ready_order_numbers",
    "all_ready_order_numbers",
}
_CLAIM_KEYS = {
    "claim",
    "claimid",
    "claim_id",
    "claim_ids",
    "claimnumber",
    "claim_number",
    "claim_numbers",
    "target_claim",
    "target_claim_id",
    "waiting_claim_ids",
    "prepared_claim_ids",
    "selected_claim_ids",
    "tool_claim_ids",
}
_TRACKING_KEYS = {
    "tracking",
    "tracking_number",
    "tracking_numbers",
    "cargotrackingnumber",
    "cargo_tracking_number",
}
_PACKAGE_KEYS = {
    "package",
    "package_id",
    "package_ids",
    "shipment_package_id",
    "shipment_package_ids",
}
_ADDRESS_KEYS = {
    "address",
    "address_text",
    "delivery_address",
    "full_address",
    "fulladdress",
    "shipment_address_text",
    "street_address",
}

_ORDER_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])")
_ORDER_PREFIX_RE = re.compile(r"(?<![A-Za-z0-9])1\d{8,9}(?![A-Za-z0-9])")
_TRACKING_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])7\d{15}(?![A-Za-z0-9])")
_CLAIM_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"(?![A-Za-z0-9])"
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?90[\s().-]?)?0?5\d{2}(?:[\s().-]?\d{2,3}){3}(?!\d)")
_CUSTOMER_LABEL_RE = re.compile(
    r"(?i)\b(m[üu]şteri|musteri|customer)(\s*:\s*)(\*\*)?\s*([^|,\n]+)"
)
_GENERIC_CUSTOMER_VALUES = {
    "-",
    "alici",
    "alıcı",
    "buyer",
    "customer",
    "musteri",
    "müşteri",
    "recipient",
    "unknown",
}
_IDENTIFIER_PRIORITY = {"order": 1, "tracking": 2, "claim": 3}
_IDENTIFIER_MAPPING_KEYS = {
    "account_by_order": "order",
    "db_cargo_provider_by_order": "order",
    "environment_by_order": "order",
    "items_by_order": "order",
    "account_by_claim": "claim",
}
_OPAQUE_DIGEST_RE = re.compile(r"[0-9a-fA-F]{32,128}")
_PUBLIC_URL_KEYS = {
    "canonical_url",
    "href",
    "requested_url",
    "source_url",
    "url",
}
_PUBLIC_URL_SECRET_QUERY_KEYS = {
    "api_key",
    "apikey",
    "api-secret",
    "api_secret",
    "password",
    "secret",
    "token",
}


def _is_opaque_digest(key: str, value: Any) -> bool:
    key_fold = str(key or "").strip().casefold()
    digest_key = (
        key_fold == "sha256"
        or key_fold.endswith("_sha256")
        or "state_hash" in key_fold
        or key_fold in {
            "content_hash", "prepare_fingerprint", "query_fingerprint", "source_snapshot_hash",
            "runtime_source_fingerprint", "runtime_source_fingerprint_current",
        }
    )
    return bool(
        digest_key
        and isinstance(value, str)
        and _OPAQUE_DIGEST_RE.fullmatch(value)
    )


def _is_preservable_public_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or "<" in candidate or ">" in candidate:
        return False
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return False
    query_keys = {
        key.casefold()
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if query_keys & _PUBLIC_URL_SECRET_QUERY_KEYS:
        return False
    if any(
        pattern.search(parsed.query) or pattern.search(parsed.fragment)
        for pattern in (_ORDER_NUMBER_RE, _TRACKING_NUMBER_RE, _CLAIM_ID_RE)
    ):
        return False
    return True


class LiveEvidenceRedactor:
    def __init__(self) -> None:
        self._aliases: dict[str, dict[str, str]] = defaultdict(dict)
        self._compiled_alias_patterns: dict[str, re.Pattern[str] | None] = {}
        self._public_urls: set[str] = set()
        self._did_redact = False

    def collect_public_urls(self, value: Any, *, key: str = "") -> None:
        key_fold = str(key or "").strip().casefold()
        if isinstance(value, dict):
            for item_key, item_value in value.items():
                self.collect_public_urls(item_value, key=str(item_key))
            return
        if isinstance(value, list):
            for item in value:
                self.collect_public_urls(item, key=key)
            return
        if key_fold in _PUBLIC_URL_KEYS and _is_preservable_public_url(value):
            self._public_urls.add(str(value).strip())

    def collect(self, value: Any, *, key: str = "") -> None:
        key_fold = str(key or "").strip().casefold()
        if _is_opaque_digest(key_fold, value):
            return
        if isinstance(value, dict):
            mapping_category = _IDENTIFIER_MAPPING_KEYS.get(key_fold, "")
            for item_key, item_value in value.items():
                if mapping_category:
                    self._alias(mapping_category, str(item_key))
                else:
                    self.collect(str(item_key))
                self.collect(item_value, key=str(item_key))
            return
        if isinstance(value, list):
            for item in value:
                self.collect(item, key=key)
            return
        if value in (None, ""):
            return
        identifier_category = self._identifier_category_for_key(key_fold)
        if identifier_category:
            self._alias(identifier_category, str(value))
            return
        if key_fold in _CUSTOMER_KEYS:
            self._alias("customer", str(value))
            return
        if key_fold in _PHONE_KEYS:
            self._alias("phone", str(value))
            return
        if key_fold in _EMAIL_KEYS:
            self._alias("email", str(value))
            return
        if key_fold in _ADDRESS_KEYS:
            self._alias("address", str(value))
            return
        if not isinstance(value, str):
            return
        scan_value = self._without_public_urls(value)
        for match in _TRACKING_NUMBER_RE.finditer(scan_value):
            self._alias("tracking", match.group(0))
        for match in _ORDER_NUMBER_RE.finditer(scan_value):
            self._alias("order", match.group(0))
        for match in _CLAIM_ID_RE.finditer(scan_value):
            self._alias("claim", match.group(0))
        for match in _EMAIL_RE.finditer(scan_value):
            self._alias("email", match.group(0))
        for match in _PHONE_RE.finditer(scan_value):
            self._alias("phone", match.group(0))
        for match in _CUSTOMER_LABEL_RE.finditer(scan_value):
            self._alias("customer", match.group(4).strip().strip("*_` "))

    def redact(self, value: Any, *, key: str = "") -> Any:
        key_fold = str(key or "").strip().casefold()
        if _is_opaque_digest(key_fold, value):
            return value
        if key_fold in _SECRET_KEYS:
            self._did_redact = True
            return "<redacted>"
        if isinstance(value, dict):
            mapping_category = _IDENTIFIER_MAPPING_KEYS.get(key_fold, "")
            return {
                (
                    self._alias(mapping_category, str(item_key))
                    if mapping_category
                    else self._redact_text(
                        str(item_key),
                        redact_customers=False,
                    )
                ): self.redact(
                    item_value,
                    key=str(item_key),
                )
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item, key=key) for item in value]
        identifier_category = self._identifier_category_for_key(key_fold)
        if identifier_category and value not in (None, ""):
            return self._alias(identifier_category, str(value))
        if key_fold in _CUSTOMER_KEYS and value not in (None, ""):
            return self._alias("customer", str(value))
        if key_fold in _PHONE_KEYS and value not in (None, ""):
            return self._alias("phone", str(value))
        if key_fold in _EMAIL_KEYS and value not in (None, ""):
            return self._alias("email", str(value))
        if key_fold in _ADDRESS_KEYS and value not in (None, ""):
            return self._alias("address", str(value))
        if not isinstance(value, str):
            return value
        return self._redact_text(value)

    def metadata(self) -> dict[str, Any]:
        counts = {
            category: len(values)
            for category, values in sorted(self._aliases.items())
            if values
        }
        return {
            "version": 4,
            "redacted": self._did_redact,
            "redaction_scope": [
                "customer names",
                "order numbers",
                "claim ids",
                "tracking numbers",
                "shipment package ids",
                "email addresses",
                "phone numbers",
                "shipping addresses",
                "provider secrets",
                "local paths",
            ],
            "alias_counts": counts,
            "aliases_are_stable_within_artifact": True,
            "original_values_persisted": False,
            "verified_public_urls_preserved": len(self._public_urls),
        }

    def _without_public_urls(self, value: str) -> str:
        text = value
        for public_url in sorted(self._public_urls, key=len, reverse=True):
            text = text.replace(public_url, "")
        return text

    def _protect_public_urls(self, value: str) -> tuple[str, dict[str, str]]:
        text = value
        protected: dict[str, str] = {}
        for index, public_url in enumerate(
            sorted(self._public_urls, key=len, reverse=True),
            start=1,
        ):
            if public_url not in text:
                continue
            placeholder = f"\ue000PUBLIC_URL_{index}\ue001"
            text = text.replace(public_url, placeholder)
            protected[placeholder] = public_url
        return text, protected

    def _alias(self, category: str, raw_value: str) -> str:
        clean_value = str(raw_value or "").strip()
        if not clean_value:
            return clean_value
        existing_alias = re.fullmatch(
            rf"<{re.escape(category)}-\d{{3,}}>",
            clean_value,
        )
        if existing_alias:
            self._aliases[category].setdefault(clean_value, clean_value)
            self._compiled_alias_patterns.pop(category, None)
            return clean_value
        if category == "customer":
            customer_token = re.sub(r"\s+", " ", clean_value.casefold()).strip(" .,:;_-")
            if customer_token in _GENERIC_CUSTOMER_VALUES:
                return clean_value
        if category in _IDENTIFIER_PRIORITY:
            existing_categories = [
                known_category
                for known_category in _IDENTIFIER_PRIORITY
                if clean_value in self._aliases.get(known_category, {})
            ]
            if existing_categories:
                strongest_category = max(
                    existing_categories,
                    key=lambda value: _IDENTIFIER_PRIORITY[value],
                )
                if _IDENTIFIER_PRIORITY[strongest_category] >= _IDENTIFIER_PRIORITY[category]:
                    self._did_redact = True
                    return self._aliases[strongest_category][clean_value]
                for known_category in existing_categories:
                    self._aliases[known_category].pop(clean_value, None)
                    self._compiled_alias_patterns.pop(known_category, None)
        known = self._aliases[category]
        if clean_value not in known:
            used_aliases = set(known.values())
            next_index = len(known) + 1
            alias = f"<{category}-{next_index:03d}>"
            while alias in used_aliases:
                next_index += 1
                alias = f"<{category}-{next_index:03d}>"
            known[clean_value] = alias
            self._compiled_alias_patterns.pop(category, None)
        self._did_redact = True
        return known[clean_value]

    def _replace_known_aliases(self, text: str, category: str) -> str:
        known = self._aliases.get(category, {})
        if not known:
            return text
        if category not in self._compiled_alias_patterns:
            raw_values = sorted(
                (value for value in known if value),
                key=len,
                reverse=True,
            )
            self._compiled_alias_patterns[category] = (
                re.compile(
                    r"(?<!\w)(?:"
                    + "|".join(re.escape(value) for value in raw_values)
                    + r")(?!\w)"
                )
                if raw_values
                else None
            )
        pattern = self._compiled_alias_patterns[category]
        if pattern is None:
            return text
        return pattern.sub(lambda match: known.get(match.group(0), match.group(0)), text)

    @staticmethod
    def _identifier_category_for_key(key_fold: str) -> str:
        if key_fold in _ORDER_KEYS:
            return "order"
        if key_fold in _CLAIM_KEYS:
            return "claim"
        if key_fold in _TRACKING_KEYS:
            return "tracking"
        if key_fold in _PACKAGE_KEYS:
            return "package"
        return ""

    def _redact_text(
        self,
        value: str,
        *,
        redact_customers: bool = True,
    ) -> str:
        text = value
        text = re.sub(
            r"(?i)(api[_ -]?key|api[_ -]?secret|token|password|db[_ -]?name)"
            r"\s*[:=]\s*['\"]?[^'\"\s,;}]+",
            r"\1=<redacted>",
            text,
        )
        text = re.sub(
            r"(?i)\b[A-Z]:[\\/][^\s\"']*?([^\\/\s\"']+\.(?:xlsx|jsonl|sqlite3|db|docx|pdf))",
            r"<local_path>/\1",
            text,
        )
        text = re.sub(r"(?i)\b[A-Z]:[\\/][^\s\"']+", "<local_path>", text)
        for category in ("claim", "tracking", "package", "order", "address"):
            text = self._replace_known_aliases(text, category)
        text, protected_public_urls = self._protect_public_urls(text)
        text = _TRACKING_NUMBER_RE.sub(lambda match: self._alias("tracking", match.group(0)), text)
        text = _ORDER_NUMBER_RE.sub(lambda match: self._alias("order", match.group(0)), text)
        text = _ORDER_PREFIX_RE.sub(self._redact_order_prefix, text)
        text = _CLAIM_ID_RE.sub(lambda match: self._alias("claim", match.group(0)), text)
        text = _EMAIL_RE.sub(lambda match: self._alias("email", match.group(0)), text)
        text = _PHONE_RE.sub(lambda match: self._alias("phone", match.group(0)), text)
        if redact_customers:
            for raw_value, alias in sorted(
                self._aliases.get("customer", {}).items(),
                key=lambda item: len(item[0]),
                reverse=True,
            ):
                if not raw_value:
                    continue
                name_parts = [
                    part
                    for part in re.split(r"[\s\u00a0\u202f]+", raw_value)
                    if part
                ]
                flexible_name = r"[\s\u00a0\u202f]+".join(
                    re.escape(part)
                    for part in name_parts
                )
                text = re.sub(
                    rf"(?<!\w){flexible_name}(?!\w)",
                    alias,
                    text,
                    flags=re.IGNORECASE,
                )
            text = _CUSTOMER_LABEL_RE.sub(
                self._redact_customer_label,
                text,
            )
        for placeholder, public_url in protected_public_urls.items():
            text = text.replace(placeholder, public_url)
        if text != value:
            self._did_redact = True
        return text

    def _redact_customer_label(self, match: re.Match[str]) -> str:
        raw_value = match.group(4).strip().strip("*_` ")
        alias = (
            raw_value
            if re.fullmatch(r"<customer-\d{3}>", raw_value)
            else self._alias("customer", raw_value)
        )
        return f"{match.group(1)}:{match.group(3) or ''} {alias}"

    def _redact_order_prefix(self, match: re.Match[str]) -> str:
        prefix = match.group(0)
        matches = {
            alias
            for raw_value, alias in self._aliases.get("order", {}).items()
            if raw_value.startswith(prefix)
        }
        if len(matches) == 1:
            self._did_redact = True
            return next(iter(matches))
        return self._alias("order_partial", prefix)


def redact_live_evidence(value: Any) -> tuple[Any, dict[str, Any]]:
    redactor = LiveEvidenceRedactor()
    redactor.collect_public_urls(value)
    redactor.collect(value)
    return redactor.redact(value), redactor.metadata()


def write_live_evidence_file(target_path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(target_path)
    redacted, metadata = redact_live_evidence(payload)
    redacted["privacy_redaction"] = metadata
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(redacted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def redact_live_evidence_file(
    source_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    source = Path(source_path)
    target = Path(output_path) if output_path is not None else source
    payload = json.loads(source.read_text(encoding="utf-8"))
    previous_metadata = payload.get("privacy_redaction") if isinstance(payload, dict) else None
    redacted, metadata = redact_live_evidence(payload)
    if isinstance(previous_metadata, dict):
        previous_counts = previous_metadata.get("alias_counts") or {}
        current_counts = metadata.get("alias_counts") or {}
        metadata["alias_counts"] = {
            category: max(int(previous_counts.get(category) or 0), int(current_counts.get(category) or 0))
            for category in sorted(set(previous_counts) | set(current_counts))
        }
        metadata["redacted"] = bool(previous_metadata.get("redacted")) or bool(metadata.get("redacted"))
    if isinstance(redacted, dict):
        redacted["privacy_redaction"] = metadata
    target.write_text(
        json.dumps(redacted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Redact private identifiers from a live evidence JSON file.")
    parser.add_argument("source", help="Source JSON path.")
    parser.add_argument("--output", help="Optional output JSON path; defaults to in-place rewrite.")
    args = parser.parse_args(argv)
    target = redact_live_evidence_file(args.source, output_path=args.output)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
