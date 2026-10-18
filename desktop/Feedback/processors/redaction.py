"""Remove credentials from formatted logs, including exception tracebacks."""
from __future__ import annotations

import logging
import re

_SECRET_FIELD = (
    r"(?:api[_-]?(?:key|secret)|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|passwd|authorization|license[_-]?key|"
    r"private[_-]?key|secret[_-]?key|token)"
)
_QUOTED_VALUE = re.compile(
    rf"(?P<prefix>['\"]?{_SECRET_FIELD}['\"]?\s*[:=]\s*)(?P<quote>['\"])"
    r"(?:\\.|(?!\2)[^\\])*?(?P=quote)",
    re.IGNORECASE,
)
_PLAIN_VALUE = re.compile(
    rf"(?P<prefix>\b{_SECRET_FIELD}\s*[:=]\s*)(?!['\"])([^\s&,;}}\]]+)",
    re.IGNORECASE,
)
_AUTH = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9_+/=.\-]+", re.IGNORECASE)
_URL_AUTH = re.compile(r"(https?://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z]+ )?PRIVATE KEY-----",
    re.DOTALL,
)


def redact_sensitive_text(value: str) -> str:
    text = str(value)
    text = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", text)
    text = _AUTH.sub(lambda m: m[1] + ' [REDACTED]', text)
    text = _QUOTED_VALUE.sub(lambda m: m['prefix'] + m['quote'] + '[REDACTED]' + m['quote'], text)
    text = _PLAIN_VALUE.sub(lambda m: m['prefix'] + '[REDACTED]', text)
    return _URL_AUTH.sub(r"\1[REDACTED]@", text)


class SecretRedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_text(super().format(record))
