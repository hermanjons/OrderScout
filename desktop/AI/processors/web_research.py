from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
from typing import Any, Callable, Iterable, Mapping
import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request

from Core.processors.report_artifacts import ReportColumn, ReportSnapshot, make_report_sheet


UTC = timezone.utc

# Shared input/output contracts expose the fields produced by an opened source.
# Planners can bind text, links and stable source IDs without guessing object
# structure or copying a search snippet into an evidence-bearing argument.
_WEB_OBSERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "observation_id": {"type": "string"},
        "query_summary": {"type": "string"},
        "url": {"type": "string"},
        "title": {"type": "string"},
        "source_domain": {"type": "string"},
        "published_at": {"type": "string"},
        "accessed_at": {"type": "string"},
        "relevant_text": {"type": "string"},
        "source_class": {"type": "string"},
        "freshness": {"type": "string"},
        "trust": {"type": "string"},
        "supported_claims": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
        "links": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
            "required": ["title", "url"],
        }},
        "prompt_injection_detected": {"type": "boolean"},
        "prompt_injection_findings": {"type": "array", "items": {"type": "string"}},
        "untrusted_content": {"type": "boolean"},
        "content_hash": {"type": "string"},
    },
    "required": ["observation_id", "url", "relevant_text", "content_hash"],
}
_RESEARCH_CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string", "minLength": 1},
        "status": {"type": "string"},
        "inference": {"type": "boolean"},
        "source_observation_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
    "required": ["claim", "source_observation_ids"],
}


def web_observation_schema() -> dict[str, Any]:
    return deepcopy(_WEB_OBSERVATION_SCHEMA)


def research_claim_schema() -> dict[str, Any]:
    return deepcopy(_RESEARCH_CLAIM_SCHEMA)


PUBLIC_PRODUCT_FIELDS = frozenset(
    {"product_name", "brand", "model", "manufacturer_code", "gtin", "barcode"}
)
PRIVATE_PRODUCT_FIELDS = frozenset(
    {
        "order_number",
        "claim_id",
        "tracking_number",
        "package_id",
        "customer",
        "address",
        "phone",
        "email",
        "sku",
        "merchant_sku",
        "stock_code",
        "cost",
        "price",
        "revenue",
    }
)
PROMPT_INJECTION_PATTERNS = (
    r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions?",
    r"(?:onceki|önceki)\s+(?:talimatlari|talimatları)\s+(?:yok\s+say|unut)",
    r"system\s+prompt",
    r"developer\s+message",
    r"(?:upload|yükle|yukle)\s+(?:the\s+)?(?:file|dosya|credentials?)",
    r"(?:run|execute|calistir|çalıştır)\s+(?:this\s+)?(?:command|komut|powershell|shell)",
    r"(?:reveal|goster|göster|print)\s+(?:the\s+)?(?:api\s*key|secret|token|credentials?)",
)


class WebResearchError(ValueError):
    pass


class WebPrivacyError(WebResearchError):
    def __init__(self, findings: Iterable[str]):
        self.findings = tuple(sorted({_text(value) for value in findings if _text(value)}))
        super().__init__("web_privacy_blocked:" + ",".join(self.findings))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return (
        _text(value)
        .casefold()
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _iso_now(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def canonical_public_url(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return ""
    ignored = {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "referrer",
        "source",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
    query = urllib.parse.urlencode(
        [
            (key, item)
            for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in ignored
        ],
        doseq=True,
    )
    host = parsed.hostname.casefold()
    port = parsed.port
    netloc = host if port is None else f"{host}:{port}"
    path = urllib.parse.quote(
        urllib.parse.unquote(parsed.path or "/"), safe="/:@-._~!$&'()*+,;="
    )
    return urllib.parse.urlunsplit((parsed.scheme.casefold(), netloc, path, query, ""))


def _public_hostname(hostname: str) -> bool:
    host = _text(hostname).casefold().rstrip(".")
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        direct = ipaddress.ip_address(host)
    except ValueError:
        direct = None
    if direct is not None:
        return direct.is_global
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


def public_url_allowed(value: Any, *, resolve_dns: bool = True) -> bool:
    canonical = canonical_public_url(value)
    host = urllib.parse.urlsplit(canonical).hostname or ""
    if not canonical or not host:
        return False
    try:
        direct = ipaddress.ip_address(host)
    except ValueError:
        direct = None
    if direct is not None:
        return direct.is_global
    if host == "localhost" or host.endswith(".local"):
        return False
    return _public_hostname(host) if resolve_dns else True


@dataclass(frozen=True)
class PublicProductField:
    field: str
    value: str
    public: bool = False

    @classmethod
    def from_value(cls, value: Mapping[str, Any]) -> "PublicProductField":
        return cls(
            field=_text(value.get("field")).casefold(),
            value=_text(value.get("value")),
            public=bool(value.get("public")),
        )


def sanitize_public_product_context(
    fields: Iterable[Mapping[str, Any] | PublicProductField] | None,
) -> tuple[PublicProductField, ...]:
    clean: list[PublicProductField] = []
    findings: list[str] = []
    for raw in list(fields or []):
        field_value = raw if isinstance(raw, PublicProductField) else PublicProductField.from_value(raw)
        if not field_value.field or not field_value.value:
            continue
        if field_value.field in PRIVATE_PRODUCT_FIELDS:
            findings.append(f"private_product_field:{field_value.field}")
            continue
        if field_value.field not in PUBLIC_PRODUCT_FIELDS or not field_value.public:
            findings.append(f"unapproved_product_field:{field_value.field}")
            continue
        clean.append(field_value)
    if findings:
        raise WebPrivacyError(findings)
    return tuple(clean)


def web_query_privacy_findings(
    query: Any,
    *,
    public_product_fields: Iterable[Mapping[str, Any] | PublicProductField] | None = None,
) -> tuple[str, ...]:
    text = _text(query)
    normalized = _normalized(text)
    approved = sanitize_public_product_context(public_product_fields)
    approved_values = {_normalized(row.value) for row in approved if row.value}
    scrubbed = normalized
    for value in sorted(approved_values, key=len, reverse=True):
        scrubbed = scrubbed.replace(value, " ")
    findings: list[str] = []
    patterns = {
        "email": r"\b[\w.%+-]+@[\w.-]+\.[a-zA-Z]{2,}\b",
        "order_or_claim_id": r"\b(?:ORD|ORDER|CLAIM|CLM|TRK|TRACK|PKG|SHP)[-_]?[A-Z0-9][A-Z0-9_-]{3,}\b",
        "long_numeric_identifier": r"\b\d{8,}\b",
        "phone_like_identifier": r"(?:\+?\d[\s().-]*){10,}",
        "api_or_bearer_secret": r"\b(?:sk-[a-z0-9_-]{12,}|AIza[a-z0-9_-]{16,}|bearer\s+[a-z0-9._=-]{12,})\b",
        "credential_assignment": r"\b(?:api[_ -]?key|api[_ -]?secret|access[_ -]?token|password|sifre|şifre)\s*[:=]\s*\S+",
        "internal_url": r"\bhttps?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)(?::\d+)?\b",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, scrubbed if label in {"long_numeric_identifier", "phone_like_identifier"} else text, flags=re.I):
            findings.append(label)
    if any(token in scrubbed for token in ("musteri", "customer", "alici", "telefon", "e-posta", "email")):
        findings.append("customer_private_context")
    if any(token in scrubbed for token in ("siparis no", "siparis numara", "order number", "takip no", "tracking number", "claim id")):
        findings.append("local_order_identifier_context")
    if any(
        token in scrubbed
        for token in (
            "siparisim",
            "siparisimi",
            "siparislerim",
            "siparislerimi",
            "magazamin siparis",
            "hesabimin siparis",
            "my order",
            "my orders",
            "our order",
            "our orders",
        )
    ):
        findings.append("private_order_context")
    if any(token in scrubbed for token in ("maliyet", "ciro", "stok miktari", "ozel fiyat", "private price")):
        findings.append("private_business_metric")
    return tuple(sorted(set(findings)))


@dataclass(frozen=True)
class SanitizedWebQuery:
    query: str
    redacted_summary: str
    public_product_fields: tuple[PublicProductField, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "redacted_summary": self.redacted_summary,
            "public_product_fields": [row.__dict__ for row in self.public_product_fields],
        }


def sanitize_web_query(
    query: Any,
    *,
    public_product_fields: Iterable[Mapping[str, Any] | PublicProductField] | None = None,
) -> SanitizedWebQuery:
    clean_query = re.sub(r"\s+", " ", _text(query)).strip()
    if not clean_query:
        raise WebResearchError("web_query_required")
    approved = sanitize_public_product_context(public_product_fields)
    findings = web_query_privacy_findings(
        clean_query,
        public_product_fields=approved,
    )
    if findings:
        raise WebPrivacyError(findings)
    return SanitizedWebQuery(
        query=clean_query,
        redacted_summary=clean_query[:240],
        public_product_fields=approved,
    )


def prompt_injection_findings(value: Any) -> tuple[str, ...]:
    normalized = _normalized(value)
    findings = [
        f"pattern_{index}"
        for index, pattern in enumerate(PROMPT_INJECTION_PATTERNS, start=1)
        if re.search(pattern, normalized, flags=re.I)
    ]
    return tuple(findings)


_WEB_GOAL_META_TOKENS = frozenset(
    {
        "ac",
        "acilan",
        "actigin",
        "actigim",
        "anlat",
        "ara",
        "arastir",
        "bak",
        "bana",
        "bul",
        "dayanarak",
        "dogrula",
        "degerlendirme",
        "degerlendirmeler",
        "deneyim",
        "deneyimler",
        "feedback",
        "guncel",
        "insanlar",
        "internet",
        "internette",
        "kaynak",
        "kaynaklar",
        "kaynaklara",
        "kaynaklariyla",
        "kisaca",
        "kullanicilar",
        "memnuniyet",
        "musteriler",
        "ozet",
        "ozetle",
        "people",
        "rating",
        "ratings",
        "review",
        "reviews",
        "sikayet",
        "soyle",
        "users",
        "ver",
        "web",
        "webde",
        "yorum",
        "yorumlar",
    }
)
_WEB_GOAL_META_PREFIXES = (
    "acikla",
    "arastir",
    "dayan",
    "degerlend",
    "deneyim",
    "dogrula",
    "excel",
    "feedback",
    "hakk",
    "insan",
    "internet",
    "karsilastir",
    "kaynak",
    "kisaca",
    "kullanici",
    "memnun",
    "musteri",
    "ozellik",
    "ozet",
    "people",
    "rating",
    "rapor",
    "review",
    "sikayet",
    "soyl",
    "soyle",
    "spec",
    "teknik",
    "technical",
    "user",
    "yorum",
)
_WEB_MEASUREMENT_TOKENS = frozenset(
    {
        "amount",
        "cost",
        "fee",
        "fiyat",
        "fiyatlar",
        "maliyet",
        "price",
        "prices",
        "pricing",
        "tarife",
        "tarifeler",
        "tutar",
        "ucret",
        "ucretler",
    }
)
_WEB_TURKISH_MEASUREMENT_ROOTS = ("fiyat", "ucret", "tutar", "maliyet")
_WEB_TURKISH_MEASUREMENT_SUFFIXES = frozenset(
    {
        "",
        "i",
        "in",
        "ini",
        "inin",
        "u",
        "un",
        "unu",
        "unun",
        "a",
        "e",
        "da",
        "de",
        "dan",
        "den",
        "lar",
        "ler",
        "lari",
        "leri",
        "larin",
        "lerin",
        "larini",
        "lerini",
        "larda",
        "lerde",
        "lardan",
        "lerden",
    }
)
_WEB_AMOUNT_PATTERN = re.compile(
    r"(?:"
    r"[₺$€£]\s*\d+(?:[.,]\d+)?|"
    r"\d+(?:[.,]\d+)?\s*(?:tl|try|usd|eur|dolar|euro|sterlin)\b|"
    r"(?:tl|try|usd|eur)\s*\d+(?:[.,]\d+)?"
    r")",
    flags=re.IGNORECASE,
)


def _is_web_measurement_token(token: Any) -> bool:
    normalized = _normalized(token)
    if not normalized or not re.fullmatch(r"[a-z0-9]+", normalized):
        return False
    if normalized in _WEB_MEASUREMENT_TOKENS:
        return True
    return any(
        normalized.startswith(root)
        and normalized[len(root) :] in _WEB_TURKISH_MEASUREMENT_SUFFIXES
        for root in _WEB_TURKISH_MEASUREMENT_ROOTS
    )


def _web_measurement_requested(value: Any) -> bool:
    return any(
        _is_web_measurement_token(token)
        for token in re.findall(r"[a-z0-9]+", _normalized(value))
    )


def _web_goal_topic_tokens(value: Any) -> tuple[str, ...]:
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", _normalized(value)):
        if (
            len(token) < 3
            or token.isdigit()
            or token in _WEB_GOAL_META_TOKENS
            or token.startswith(_WEB_GOAL_META_PREFIXES)
        ):
            continue
        stem = token[:10]
        if stem not in tokens:
            tokens.append(stem)
    return tuple(tokens[:20])


def _web_opinion_requested(value: Any) -> bool:
    """Return whether the public-web goal asks for user-opinion evidence.

    URL text is deliberately removed first: a host or path containing ``review``
    is not user intent and must not silently strengthen the evidence contract.
    """

    opinion_goal_text = re.sub(
        r"https?://\S+",
        " ",
        _normalized(value),
        flags=re.I,
    )
    return bool(
        re.search(
            r"(?<!\w)(?:yorum|degerlendirme|deneyim|memnuniyet|sikayet|"
            r"review|rating|feedback)\w*(?!\w)",
            opinion_goal_text,
        )
        or re.search(
            r"(?<!\w)(?:insanlar|kullanicilar|musteriler|people|users|customers)"
            r"\w*.{0,48}(?:ne\s+soyl|neler\s+soyl|dusun|konus|say|think)",
            opinion_goal_text,
        )
    )


def _web_opinion_counts(value: Any) -> dict[str, int]:
    """Extract explicit review/evaluation counts without treating them as sentiment.

    A page saying ``12 yorum`` proves that reviews exist, but does not reveal
    what users said.  Keeping this weaker evidence separate prevents both the
    false claim that no reviews exist and the opposite error of inventing a
    sentiment summary from a count alone.
    """

    normalized = _normalized(value)

    def largest(label: str) -> int:
        counts: list[int] = []
        patterns = (
            rf"(?<![a-z0-9]){label}\w*(?:\s+gor\w*)?\s*\(\s*(\d+)\s*\)",
            rf"(?<![a-z0-9])(\d+)\s+{label}\w*(?![a-z0-9])",
        )
        for pattern in patterns:
            counts.extend(
                int(match.group(1))
                for match in re.finditer(pattern, normalized)
            )
        return max(counts, default=0)

    return {
        "review_count": largest("yorum"),
        "evaluation_count": largest("degerlendirme"),
    }


def select_goal_relevant_web_link(
    observation: Mapping[str, Any] | "WebObservation",
    goal: Any,
    *,
    excluded_urls: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Select an exact contained link that can close the typed evidence gap.

    This is navigation policy, not a replacement business plan.  It can only
    return a public URL already present in the immutable WebObservation.  The
    actual open remains the atomic ``web.follow`` operation, which revalidates
    the exact containment and public-network boundary.
    """

    if not _web_opinion_requested(goal):
        return {}
    row = (
        observation
        if isinstance(observation, WebObservation)
        else WebObservation.from_dict(observation)
    )
    excluded = {
        canonical_public_url(value)
        for value in list(excluded_urls or [])
        if canonical_public_url(value)
    }
    current_url = canonical_public_url(row.url)
    candidates: list[dict[str, Any]] = []
    for index, link in enumerate(row.links):
        url = canonical_public_url(link.get("url"))
        title = _text(link.get("title"))
        if not url or not title or url == current_url or url in excluded:
            continue
        title_text = _normalized(title)
        url_text = _normalized(urllib.parse.urlsplit(url).path)
        score = 0
        if re.search(
            r"(?<!\w)(?:musteri|kullanici|customer|user)?\s*"
            r"(?:yorum|degerlendirme|puan|yildiz|review|rating|feedback|comment)\w*",
            title_text,
        ):
            score += 8
        if re.search(
            r"(?:product[-_/]?reviews?|customer[-_/]?reviews?|reviews?|ratings?|"
            r"comments?|yorum|degerlendirme|puan|yildiz)",
            url_text,
        ):
            score += 5
        if not score:
            continue
        candidates.append(
            {
                "title": title,
                "url": url,
                "score": score,
                "source_index": index,
                "reason": "typed_user_opinion_link",
            }
        )
    return max(
        candidates,
        key=lambda item: (int(item.get("score") or 0), -int(item.get("source_index") or 0)),
        default={},
    )


def evaluate_web_observation_goal_evidence(
    observation: Mapping[str, Any] | "WebObservation",
    goal: Any,
) -> dict[str, Any]:
    """Verify that an opened source contains evidence for the user's fact goal.

    Reaching a URL proves only source accessibility.  This verifier deliberately
    uses small, deterministic evidence shapes so a search result cannot become
    authoritative merely because it is official, high-ranked, or successfully
    opened.
    """

    row = (
        observation
        if isinstance(observation, WebObservation)
        else WebObservation.from_dict(observation)
    )
    normalized_goal = _normalized(goal)
    normalized_source = _normalized(
        " ".join((row.title, row.url, row.relevant_text))
    )
    # ``query_summary`` is the privacy-sanitized public subject that actually
    # produced this observation.  The full conversational goal still owns
    # intent/facet detection, but using it for bounded topic tokens lets
    # anaphora and control prose crowd the product identity out of the first
    # twenty slots.
    topic_basis = row.query_summary or normalized_goal
    topic_tokens = set(_web_goal_topic_tokens(topic_basis))
    source_tokens = set(_web_goal_topic_tokens(normalized_source))
    matched_topic_tokens = sorted(topic_tokens & source_tokens)
    required_topic_matches = (
        0
        if not topic_tokens
        else 1
        if len(topic_tokens) <= 2
        else 2
    )
    findings: list[str] = []
    if len(matched_topic_tokens) < required_topic_matches:
        findings.append("goal_topic_evidence_missing")

    opinion_requested = _web_opinion_requested(normalized_goal)
    normalized_opinion_text = _normalized(row.relevant_text)
    opinion_section_present = bool(
        re.search(
            r"(?<!\w)(?:(?:musteri|kullanici|customer|user)\s+)?"
            r"(?:yorum|degerlendirme|review|rating)\w*(?!\w)",
            normalized_opinion_text,
        )
    )
    opinion_rating_or_distribution_present = bool(
        re.search(
            r"(?<!\w)(?:[0-5](?:[.,]\d+)?\s*(?:/\s*5|puan)|"
            r"5\s+yildiz\s+uzerinden\s+[0-5](?:[.,]\d+)?|"
            r"[1-5]\s+yildiz\s*%\s*\d+)(?!\w)",
            normalized_opinion_text,
        )
        or re.search(
            r"(?<!\w)(?:musteri|kullanici)\s+yorum\w*.{0,260}"
            r"(?:%\s*\d+|\d+\s+degerlendirme|\d+\s+yorum)(?!\w)",
            normalized_opinion_text,
        )
    )
    opinion_statement_present = bool(
        re.search(
            r"(?<!\w)(?:kullanici|musteri|yorum|degerlendirme|review)\w*"
            r".{0,120}(?:belirt|soyl|diyor|begeni|memnun|sikayet|tavsiye|"
            r"oner|ov|elestir|report|recommend|complain|praise)(?!\w)",
            normalized_opinion_text,
        )
    )
    explicit_no_opinion_present = bool(
        re.search(
            r"(?<!\w)(?:yorum|degerlendirme|review)\w*.{0,40}"
            r"(?:yok|bulunmuyor|henuz\s+yok|0\s*(?:adet|yorum|degerlendirme))",
            normalized_opinion_text,
        )
        or re.search(
            r"(?<!\w)(?:musteri|kullanici)\s+yorum\w*.{0,260}"
            r"(?:5\s+yildiz\s*%\s*0).{0,180}(?:1\s+yildiz\s*%\s*0)",
            normalized_opinion_text,
        )
    )
    opinion_counts = _web_opinion_counts(row.relevant_text)
    opinion_review_count = int(opinion_counts.get("review_count") or 0)
    opinion_evaluation_count = int(
        opinion_counts.get("evaluation_count") or 0
    )
    opinion_count_present = bool(
        opinion_review_count or opinion_evaluation_count
    )
    opinion_evidence_present = bool(
        opinion_section_present
        and (
            opinion_rating_or_distribution_present
            or opinion_statement_present
            or explicit_no_opinion_present
            or bool(row.supported_claims)
        )
    )
    if opinion_requested and not opinion_evidence_present:
        findings.append("requested_user_opinion_evidence_missing")

    amount_requested = _web_measurement_requested(normalized_goal)
    amount_matches = list(_WEB_AMOUNT_PATTERN.finditer(row.relevant_text))
    amount_evidence_present = bool(amount_matches)
    measurement_relation_present = not amount_requested
    if amount_requested:
        if not amount_evidence_present:
            findings.append("requested_amount_evidence_missing")
        host_tokens = set(
            _web_goal_topic_tokens(
                (urllib.parse.urlsplit(row.url).hostname or "").replace(".", " ")
            )
        )
        subject_tokens = {
            token
            for token in topic_tokens - host_tokens
            if not _is_web_measurement_token(token)
        }
        normalized_public_text = _normalized(row.relevant_text)
        for amount_match in amount_matches:
            start = max(0, amount_match.start() - 320)
            end = min(len(normalized_public_text), amount_match.end() + 320)
            window = normalized_public_text[start:end]
            measurement_nearby = _web_measurement_requested(window)
            required_subject_matches = min(
                2,
                max(1, len(subject_tokens)),
            )
            subject_matches = sum(
                1
                for token in subject_tokens
                if token and token in window
            )
            if (
                measurement_nearby
                and (
                    not subject_tokens
                    or subject_matches >= required_subject_matches
                )
            ):
                measurement_relation_present = True
                break
        if amount_evidence_present and not measurement_relation_present:
            findings.append("requested_measurement_relation_missing")

    return {
        "adequate": not findings,
        "findings": findings,
        "topic_token_count": len(topic_tokens),
        "topic_basis": "query_summary" if row.query_summary else "goal",
        "matched_topic_token_count": len(matched_topic_tokens),
        "required_topic_match_count": required_topic_matches,
        "opinion_requested": opinion_requested,
        "opinion_section_present": opinion_section_present,
        "opinion_rating_or_distribution_present": (
            opinion_rating_or_distribution_present
        ),
        "opinion_statement_present": opinion_statement_present,
        "explicit_no_opinion_present": explicit_no_opinion_present,
        "opinion_count_present": opinion_count_present,
        "opinion_review_count": opinion_review_count,
        "opinion_evaluation_count": opinion_evaluation_count,
        "opinion_evidence_present": opinion_evidence_present,
        "amount_requested": amount_requested,
        "amount_evidence_present": amount_evidence_present,
        "measurement_relation_present": measurement_relation_present,
        "prompt_injection_detected": row.prompt_injection_detected,
        "source_opened": bool(row.url and row.relevant_text),
        "observation_id": row.observation_id,
        "source_domain": row.source_domain,
    }


def _source_class(url: str, *, official: bool = False) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").casefold()
    if official or host.endswith((".gov", ".gov.tr", ".edu", ".edu.tr")):
        return "primary"
    if any(token in host for token in ("docs.", "developer", "support.", "help.")):
        return "primary"
    return "secondary"


def _freshness(published_at: str, *, now: datetime | None = None) -> str:
    if not published_at:
        return "unknown"
    try:
        published = date.fromisoformat(published_at[:10])
    except ValueError:
        return "unknown"
    current = (now or datetime.now(UTC)).date()
    age = max(0, (current - published).days)
    if age <= 90:
        return "fresh"
    if age <= 730:
        return "aging"
    return "stale"


@dataclass(frozen=True)
class WebObservation:
    observation_id: str
    query_summary: str
    url: str
    title: str
    source_domain: str
    published_at: str
    accessed_at: str
    relevant_text: str
    source_class: str
    freshness: str
    trust: str
    supported_claims: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    links: tuple[dict[str, str], ...] = ()
    prompt_injection_detected: bool = False
    prompt_injection_findings: tuple[str, ...] = ()
    untrusted_content: bool = True
    content_hash: str = ""

    @classmethod
    def create(
        cls,
        *,
        query_summary: str,
        url: str,
        title: str,
        relevant_text: str,
        published_at: str = "",
        official: bool = False,
        links: Iterable[Mapping[str, Any]] | None = None,
        supported_claims: Iterable[str] | None = None,
        contradictions: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> "WebObservation":
        canonical = canonical_public_url(url)
        if not canonical:
            raise WebResearchError("invalid_public_url")
        clean_text = re.sub(r"\s+", " ", _text(relevant_text)).strip()[:20_000]
        if not clean_text:
            raise WebResearchError("empty_web_content")
        clean_links = tuple(
            {
                "title": _text(row.get("title"))[:240],
                "url": canonical_public_url(row.get("url")),
            }
            for row in list(links or [])[:100]
            if canonical_public_url(row.get("url"))
        )
        injection = prompt_injection_findings(clean_text)
        payload = {
            "query_summary": _text(query_summary)[:240],
            "url": canonical,
            "title": _text(title)[:300],
            "published_at": _text(published_at)[:32],
            "relevant_text": clean_text,
            "source_class": _source_class(canonical, official=official),
            "supported_claims": [_text(value) for value in list(supported_claims or []) if _text(value)],
            "contradictions": [_text(value) for value in list(contradictions or []) if _text(value)],
        }
        digest = _content_hash(payload)
        return cls(
            observation_id=f"webobs-{digest[:20]}",
            query_summary=payload["query_summary"],
            url=canonical,
            title=payload["title"],
            source_domain=(urllib.parse.urlsplit(canonical).hostname or "").casefold(),
            published_at=payload["published_at"],
            accessed_at=_iso_now(now),
            relevant_text=clean_text,
            source_class=payload["source_class"],
            freshness=_freshness(payload["published_at"], now=now),
            trust="high" if payload["source_class"] == "primary" and not injection else "medium" if not injection else "untrusted_injection",
            supported_claims=tuple(payload["supported_claims"]),
            contradictions=tuple(payload["contradictions"]),
            links=clean_links,
            prompt_injection_detected=bool(injection),
            prompt_injection_findings=injection,
            content_hash=digest,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WebObservation":
        return cls(
            observation_id=_text(payload.get("observation_id")),
            query_summary=_text(payload.get("query_summary")),
            url=canonical_public_url(payload.get("url")),
            title=_text(payload.get("title")),
            source_domain=_text(payload.get("source_domain")),
            published_at=_text(payload.get("published_at")),
            accessed_at=_text(payload.get("accessed_at")),
            relevant_text=_text(payload.get("relevant_text")),
            source_class=_text(payload.get("source_class")),
            freshness=_text(payload.get("freshness")),
            trust=_text(payload.get("trust")),
            supported_claims=tuple(_text(value) for value in list(payload.get("supported_claims") or []) if _text(value)),
            contradictions=tuple(_text(value) for value in list(payload.get("contradictions") or []) if _text(value)),
            links=tuple(dict(row) for row in list(payload.get("links") or []) if isinstance(row, dict)),
            prompt_injection_detected=bool(payload.get("prompt_injection_detected")),
            prompt_injection_findings=tuple(_text(value) for value in list(payload.get("prompt_injection_findings") or []) if _text(value)),
            untrusted_content=True,
            content_hash=_text(payload.get("content_hash")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "query_summary": self.query_summary,
            "url": self.url,
            "title": self.title,
            "source_domain": self.source_domain,
            "published_at": self.published_at,
            "accessed_at": self.accessed_at,
            "relevant_text": self.relevant_text,
            "source_class": self.source_class,
            "freshness": self.freshness,
            "trust": self.trust,
            "supported_claims": list(self.supported_claims),
            "contradictions": list(self.contradictions),
            "links": [dict(row) for row in self.links],
            "prompt_injection_detected": self.prompt_injection_detected,
            "prompt_injection_findings": list(self.prompt_injection_findings),
            "untrusted_content": True,
            "content_hash": self.content_hash,
        }


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        canonical = canonical_public_url(newurl)
        if not canonical or not public_url_allowed(canonical):
            raise WebResearchError("unsafe_web_redirect")
        return super().redirect_request(req, fp, code, msg, headers, canonical)


def fetch_public_source(url: str, *, max_bytes: int = 1_500_000, timeout: float = 15.0) -> dict[str, Any]:
    canonical = canonical_public_url(url)
    if not canonical or not public_url_allowed(canonical):
        raise WebResearchError("unsafe_or_private_web_url")
    request = urllib.request.Request(
        canonical,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; OrderScout/1.0; +agentic-web-reader)",
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        },
    )
    opener = urllib.request.build_opener(_PublicRedirectHandler())
    with opener.open(request, timeout=max(1.0, float(timeout))) as response:
        status = int(getattr(response, "status", 200) or 200)
        final_url = canonical_public_url(response.geturl())
        content_type = _text(response.headers.get("Content-Type")).casefold()
        if status >= 400 or not final_url or not public_url_allowed(final_url):
            raise WebResearchError(f"web_http_status:{status}")
        body = response.read(max(1, int(max_bytes)) + 1)
        truncated = len(body) > max_bytes
        if truncated:
            body = body[:max_bytes]
    return {
        "url": final_url,
        "content_type": content_type,
        "body": body,
        "truncated": truncated,
    }


def _html_payload(body: bytes, content_type: str, base_url: str) -> dict[str, Any]:
    charset_match = re.search(r"charset=([a-zA-Z0-9._-]+)", content_type)
    charset = charset_match.group(1) if charset_match else "utf-8"
    page = body.decode(charset, errors="replace")
    page = re.sub(r"<(?:script|style|noscript|svg)\b.*?</(?:script|style|noscript|svg)>", " ", page, flags=re.I | re.S)
    title_match = re.search(r"<title[^>]*>(?P<text>.*?)</title>", page, flags=re.I | re.S)
    title = html.unescape(re.sub(r"<[^>]+>", " ", title_match.group("text"))).strip() if title_match else ""
    published = ""
    for pattern in (
        r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|date|datePublished)["\'][^>]+content=["\'](?P<date>[^"\']+)',
        r'<time[^>]+datetime=["\'](?P<date>[^"\']+)',
    ):
        match = re.search(pattern, page, flags=re.I)
        if match:
            published = _text(match.group("date"))[:32]
            break
    content_match = (
        re.search(r"<article\b[^>]*>(?P<text>.*?)</article>", page, flags=re.I | re.S)
        or re.search(r"<main\b[^>]*>(?P<text>.*?)</main>", page, flags=re.I | re.S)
    )
    content = content_match.group("text") if content_match else page
    content = re.sub(r"<(nav|aside|header|footer)\b[^>]*>.*?</\1>", " ", content, flags=re.I | re.S)
    blocks = re.findall(r"<(?:h1|h2|h3|p|li|td)\b[^>]*>(?P<text>.*?)</(?:h1|h2|h3|p|li|td)>", content, flags=re.I | re.S)
    clean_blocks: list[str] = []
    for block in blocks:
        value = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", block))).strip()
        if value and value not in clean_blocks:
            clean_blocks.append(value)
    text = " ".join(clean_blocks) or re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", content))).strip()
    links: list[dict[str, str]] = []
    seen_links: set[str] = set()
    for match in re.finditer(r'<a[^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<title>.*?)</a>', content + page, flags=re.I | re.S):
        target = canonical_public_url(urllib.parse.urljoin(base_url, html.unescape(match.group("href"))))
        label = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", match.group("title")))).strip()
        if target and label and target not in seen_links:
            seen_links.add(target)
            links.append({"title": label[:240], "url": target})
        if len(links) >= 100:
            break
    return {"title": title, "published_at": published, "text": text, "links": links}


def _pdf_text(body: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise WebResearchError("pdf_reader_dependency_unavailable") from exc
    reader = PdfReader(BytesIO(body))
    parts = [_text(page.extract_text()) for page in reader.pages[:100]]
    return "\n".join(part for part in parts if part)


def open_web_source(
    url: str,
    *,
    query_summary: str = "",
    title: str = "",
    published_at: str = "",
    official: bool = False,
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> WebObservation:
    fetched = dict((fetcher or fetch_public_source)(url) or {})
    final_url = canonical_public_url(fetched.get("url") or url)
    if not final_url:
        raise WebResearchError("invalid_public_url")
    body = fetched.get("body")
    content_type = _text(fetched.get("content_type")).casefold()
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, bytes):
        raise WebResearchError("web_body_missing")
    if "pdf" in content_type or final_url.casefold().endswith(".pdf"):
        text = _pdf_text(body)
        payload = {"title": title or final_url.rsplit("/", 1)[-1], "published_at": published_at, "text": text, "links": []}
    elif "html" in content_type or not content_type or "text/plain" in content_type:
        payload = _html_payload(body, content_type, final_url) if "html" in content_type or b"<html" in body[:1000].lower() else {
            "title": title,
            "published_at": published_at,
            "text": body.decode("utf-8", errors="replace"),
            "links": [],
        }
    else:
        raise WebResearchError("unsupported_web_content_type")
    return WebObservation.create(
        query_summary=query_summary,
        url=final_url,
        # For HTML, the fetched final page title is source evidence while the
        # search-candidate title is only discovery metadata.  Preferring the
        # candidate title after a redirect can make a generic/category page
        # masquerade as the requested product.  PDF/plain payloads already use
        # the caller title as their parsed fallback above.
        title=payload.get("title") or title or final_url,
        relevant_text=payload.get("text"),
        published_at=published_at or payload.get("published_at") or "",
        official=official,
        links=payload.get("links") or [],
        now=now,
    )


def find_in_web_observation(
    observation: Mapping[str, Any] | WebObservation,
    pattern: str,
    *,
    max_matches: int = 8,
    context_chars: int = 280,
) -> dict[str, Any]:
    row = observation if isinstance(observation, WebObservation) else WebObservation.from_dict(observation)
    needle = _text(pattern)
    if not needle:
        raise WebResearchError("web_find_pattern_required")
    matches: list[dict[str, Any]] = []
    for match in re.finditer(re.escape(needle), row.relevant_text, flags=re.I):
        start = max(0, match.start() - max(40, int(context_chars)))
        end = min(len(row.relevant_text), match.end() + max(40, int(context_chars)))
        matches.append({"start": match.start(), "end": match.end(), "excerpt": row.relevant_text[start:end].strip()})
        if len(matches) >= max(1, min(50, int(max_matches))):
            break
    return {
        "observation_id": row.observation_id,
        "pattern": needle,
        "count": len(matches),
        "matches": matches,
        "url": row.url,
    }


def follow_web_observation_link(
    observation: Mapping[str, Any] | WebObservation,
    *,
    link_url: str = "",
    link_title: str = "",
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> WebObservation:
    row = observation if isinstance(observation, WebObservation) else WebObservation.from_dict(observation)
    requested_url = canonical_public_url(link_url)
    requested_title = _normalized(link_title)
    selected: dict[str, str] | None = None
    for link in row.links:
        if requested_url and canonical_public_url(link.get("url")) == requested_url:
            selected = dict(link)
            break
        if requested_title and requested_title in _normalized(link.get("title")):
            selected = dict(link)
            break
    if selected is None:
        raise WebResearchError("web_follow_link_not_in_observation")
    return open_web_source(
        selected["url"],
        query_summary=row.query_summary,
        title=selected.get("title", ""),
        fetcher=fetcher,
        now=now,
    )


def compare_web_observations(
    observations: Iterable[Mapping[str, Any] | WebObservation],
    *,
    claim: str = "",
) -> dict[str, Any]:
    rows = [row if isinstance(row, WebObservation) else WebObservation.from_dict(row) for row in observations]
    if len(rows) < 2:
        raise WebResearchError("at_least_two_web_observations_required")
    claim_tokens = {token for token in re.findall(r"[a-z0-9]+", _normalized(claim)) if len(token) >= 3}
    support: list[str] = []
    weak: list[str] = []
    conflicts: list[str] = []
    measurement_rows: dict[str, dict[str, set[str]]] = {}
    conflict_details: list[dict[str, Any]] = []
    for row in rows:
        text_tokens = set(re.findall(r"[a-z0-9]+", _normalized(row.relevant_text)))
        coverage = (len(claim_tokens & text_tokens) / len(claim_tokens)) if claim_tokens else 0.0
        if coverage >= 0.7 and not row.prompt_injection_detected:
            support.append(row.observation_id)
        else:
            weak.append(row.observation_id)
        if row.contradictions:
            conflicts.append(row.observation_id)
            conflict_details.append(
                {
                    "kind": "declared_contradiction",
                    "observation_id": row.observation_id,
                    "details": list(row.contradictions),
                }
            )
        normalized_text = _normalized(row.relevant_text)
        if re.search(r"\b(?:not|does not|is not|degil|desteklemez|bulunmuyor)\b", normalized_text):
            if coverage >= 0.5:
                conflicts.append(row.observation_id)
                conflict_details.append(
                    {
                        "kind": "claim_negation",
                        "observation_id": row.observation_id,
                    }
                )
        for match in re.finditer(
            r"(?<!\w)(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>dpi|mm|cm|kg|g|ml|l|w|v|mah|gb|tb|hz|khz|mhz|ghz|percent|yuzde|%)\b",
            normalized_text,
            flags=re.I,
        ):
            unit = _normalized(match.group("unit"))
            value = match.group("value").replace(",", ".")
            measurement_rows.setdefault(unit, {}).setdefault(value, set()).add(
                row.observation_id
            )
    for unit, values in sorted(measurement_rows.items()):
        if len(values) <= 1:
            continue
        involved = sorted({obs_id for obs_ids in values.values() for obs_id in obs_ids})
        conflicts.extend(involved)
        conflict_details.append(
            {
                "kind": "measurement_mismatch",
                "unit": unit,
                "values": [
                    {"value": value, "observation_ids": sorted(observation_ids)}
                    for value, observation_ids in sorted(values.items())
                ],
            }
        )
    conflicts = list(dict.fromkeys(conflicts))
    source_classes = {row.source_class for row in rows}
    freshness_values = {row.freshness for row in rows}
    supporting_domains = {
        row.source_domain for row in rows if row.observation_id in support
    }
    status = (
        "conflicted"
        if conflicts
        else "supported"
        if len(supporting_domains) >= 2
        else "partially_supported"
    )
    return {
        "claim": _text(claim),
        "status": status,
        "supporting_observation_ids": support,
        "weak_observation_ids": weak,
        "conflicting_observation_ids": conflicts,
        "conflict_details": conflict_details,
        "source_count": len(rows),
        "independent_source_count": len({row.source_domain for row in rows}),
        "source_classes": sorted(source_classes),
        "freshness": sorted(freshness_values),
        "citations": [{"title": row.title, "url": row.url, "observation_id": row.observation_id} for row in rows],
    }


@dataclass(frozen=True)
class ResearchReportSnapshot:
    snapshot_id: str
    title: str
    query_summary: str
    product_context: tuple[PublicProductField, ...]
    claims: tuple[dict[str, Any], ...]
    observations: tuple[WebObservation, ...]
    created_at: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        title: str,
        query_summary: str,
        product_context: Iterable[Mapping[str, Any] | PublicProductField] | None,
        claims: Iterable[Mapping[str, Any]],
        observations: Iterable[Mapping[str, Any] | WebObservation],
        now: datetime | None = None,
    ) -> "ResearchReportSnapshot":
        products = sanitize_public_product_context(product_context)
        rows = tuple(row if isinstance(row, WebObservation) else WebObservation.from_dict(row) for row in observations)
        if not rows:
            raise WebResearchError("research_observations_required")
        observations_by_id = {row.observation_id: row for row in rows}
        if not all(row.observation_id and row.url and row.relevant_text and row.content_hash for row in rows):
            raise WebResearchError("research_observation_evidence_required")
        clean_claims_list: list[dict[str, Any]] = []
        for row in claims:
            if not isinstance(row, Mapping) or not _text(row.get("claim")):
                raise WebResearchError("research_claim_text_required")
            source_ids = row.get("source_observation_ids")
            if not isinstance(source_ids, (list, tuple)) or not source_ids:
                raise WebResearchError("research_claim_source_observations_required")
            if any(not isinstance(value, str) or not value.strip() for value in source_ids):
                raise WebResearchError("research_claim_source_observations_invalid")
            clean_ids = list(dict.fromkeys(value.strip() for value in source_ids))
            if any(source_id not in observations_by_id for source_id in clean_ids):
                raise WebResearchError("research_claim_source_observation_not_opened")
            if (any(observations_by_id[source_id].prompt_injection_detected for source_id in clean_ids)
                    and _text(row.get("status")) != "blocked_untrusted_injection"):
                raise WebResearchError("research_claim_uses_injection_source")
            clean_claims_list.append({**dict(row), "source_observation_ids": clean_ids})
        clean_claims = tuple(clean_claims_list)
        created_at = _iso_now(now)
        payload = {
            "title": _text(title),
            "query_summary": _text(query_summary)[:240],
            "product_context": [row.__dict__ for row in products],
            "claims": list(clean_claims),
            "observation_hashes": [row.content_hash for row in rows],
            "created_at": created_at,
        }
        digest = _content_hash(payload)
        return cls(
            snapshot_id=f"research-{digest[:20]}",
            title=payload["title"] or "Web Araştırma Raporu",
            query_summary=payload["query_summary"],
            product_context=products,
            claims=clean_claims,
            observations=rows,
            created_at=created_at,
            content_hash=digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "title": self.title,
            "query_summary": self.query_summary,
            "product_context": [row.__dict__ for row in self.product_context],
            "claims": [dict(row) for row in self.claims],
            "observations": [row.to_dict() for row in self.observations],
            "created_at": self.created_at,
            "content_hash": self.content_hash,
            "contains_private_order_data": False,
        }

    def to_report_snapshot(self) -> ReportSnapshot:
        summary_rows = [
            {"metric": "Araştırma", "value": self.title},
            {"metric": "Sorgu özeti", "value": self.query_summary},
            {"metric": "Kaynak sayısı", "value": len(self.observations)},
            {"metric": "İddia sayısı", "value": len(self.claims)},
            {"metric": "Oluşturulma", "value": self.created_at},
        ]
        claim_rows = [
            {
                "claim": _text(row.get("claim")),
                "status": _text(row.get("status")),
                "inference": bool(row.get("inference")),
                "source_ids": ", ".join(_text(value) for value in list(row.get("source_observation_ids") or []) if _text(value)),
            }
            for row in self.claims
        ]
        source_rows = [
            {
                "title": row.title,
                "url": row.url,
                "domain": row.source_domain,
                "source_class": row.source_class,
                "published_at": row.published_at,
                "accessed_at": row.accessed_at,
                "freshness": row.freshness,
                "trust": row.trust,
                "injection": row.prompt_injection_detected,
                "excerpt": row.relevant_text[:1000],
            }
            for row in self.observations
        ]
        product_rows = [
            {"field": row.field, "value": row.value, "public": row.public}
            for row in self.product_context
        ]
        return ReportSnapshot.create(
            title=self.title,
            source_domain="web",
            report_type="web.research",
            filters={"query_summary": self.query_summary},
            metadata={
                "research_snapshot_id": self.snapshot_id,
                "research_content_hash": self.content_hash,
                "source_count": len(self.observations),
                "claim_count": len(self.claims),
                "contains_customer_pii": False,
                "contains_private_order_data": False,
            },
            sheets=(
                make_report_sheet(
                    name="Araştırma Özeti",
                    columns=(ReportColumn("metric", "Ölçüm", width=28), ReportColumn("value", "Değer", width=72)),
                    rows=summary_rows,
                ),
                make_report_sheet(
                    name="Bulgular",
                    columns=(
                        ReportColumn("claim", "İddia/Bulgu", width=72),
                        ReportColumn("status", "Durum", width=20),
                        ReportColumn("inference", "Çıkarım", data_type="boolean", width=12),
                        ReportColumn("source_ids", "Kaynak Observation", width=48),
                    ),
                    rows=claim_rows,
                ),
                make_report_sheet(
                    name="Kaynaklar",
                    columns=(
                        ReportColumn("title", "Başlık", width=48),
                        ReportColumn("url", "URL", width=72),
                        ReportColumn("domain", "Domain", width=28),
                        ReportColumn("source_class", "Kaynak Sınıfı", width=18),
                        ReportColumn("published_at", "Yayın/Güncelleme", width=20),
                        ReportColumn("accessed_at", "Erişim", width=24),
                        ReportColumn("freshness", "Güncellik", width=14),
                        ReportColumn("trust", "Güven", width=20),
                        ReportColumn("injection", "Injection", data_type="boolean", width=12),
                        ReportColumn("excerpt", "İlgili Bölüm", width=90),
                    ),
                    rows=source_rows,
                ),
                make_report_sheet(
                    name="Public Ürün Bağlamı",
                    columns=(
                        ReportColumn("field", "Alan", width=24),
                        ReportColumn("value", "Public Değer", width=64),
                        ReportColumn("public", "Public", data_type="boolean", width=12),
                    ),
                    rows=product_rows,
                ),
            ),
        )
