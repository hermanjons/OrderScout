from __future__ import annotations

import importlib
import json

from Feedback.constants.messages import (
    ERROR_DATABASE_GENERIC,
    ERROR_DB_OPERATION_FAILED,
    ERROR_DIRECTORY_GIVEN,
    ERROR_DUPLICATE_RECORD,
    ERROR_FILE_NOT_FOUND,
    ERROR_HTTP_CONNECTION,
    ERROR_HTTP_FAILED,
    ERROR_HTTP_STATUS_TEMPLATE,
    ERROR_HTTP_TIMEOUT,
    ERROR_INDEX_INVALID,
    ERROR_JSON_INVALID,
    ERROR_KEY_MISSING,
    ERROR_NETWORK_CONNECTION,
    ERROR_OS_FILE,
    ERROR_PERMISSION_DENIED,
    ERROR_RELATED_RECORD_NOT_FOUND,
    ERROR_REQUIRED_FIELD_MESSAGE,
    ERROR_REQUIRED_FIELD_TEMPLATE,
    ERROR_RUNTIME,
    ERROR_SERVER_CONNECTION_FAILED,
    ERROR_SQL_QUERY_FAILED,
    ERROR_TIMEOUT,
    ERROR_TYPE_UNEXPECTED,
    ERROR_UNKNOWN_TEMPLATE,
    ERROR_VALUE_INVALID,
    SQL_FOREIGN_KEY_CONSTRAINT_MARKER,
    SQL_NOT_NULL_CONSTRAINT_MARKER,
    SQL_UNIQUE_CONSTRAINT_MARKER,
)

_OPTIONAL_MODULE_UNLOADED = object()
httpx = _OPTIONAL_MODULE_UNLOADED  # type: ignore[assignment]
aiohttp = _OPTIONAL_MODULE_UNLOADED  # type: ignore[assignment]
requests = _OPTIONAL_MODULE_UNLOADED  # type: ignore[assignment]


def _optional_module(name: str):
    global httpx, aiohttp, requests
    current = globals().get(name, _OPTIONAL_MODULE_UNLOADED)
    if current is not _OPTIONAL_MODULE_UNLOADED:
        return current
    try:
        current = importlib.import_module(name)
    except Exception:  # pragma: no cover - optional dependency
        current = None
    globals()[name] = current
    return current


def _error_from_module(error: Exception, module_name: str) -> bool:
    prefix = f"{module_name}."
    try:
        modules = [str(cls.__module__ or "") for cls in type(error).__mro__]
    except Exception:
        modules = [str(type(error).__module__ or "")]
    return any(module == module_name or module.startswith(prefix) for module in modules)


def _sqlalchemy_exc_module(error: Exception):
    if not _error_from_module(error, "sqlalchemy"):
        return None
    return _optional_module("sqlalchemy.exc")


def map_error_to_message(error: Exception) -> str:
    try:
        sqlalchemy_exc = _sqlalchemy_exc_module(error)
        if sqlalchemy_exc is not None and isinstance(error, sqlalchemy_exc.IntegrityError):
            raw_text = str(getattr(error, "orig", None) or error or "").strip()
            raw_upper = raw_text.upper()
            if SQL_NOT_NULL_CONSTRAINT_MARKER in raw_upper:
                field = raw_text.split(":", 1)[-1].strip() if ":" in raw_text else ""
                if field:
                    return ERROR_REQUIRED_FIELD_TEMPLATE.format(field=field)
                return ERROR_REQUIRED_FIELD_MESSAGE
            if SQL_FOREIGN_KEY_CONSTRAINT_MARKER in raw_upper:
                return ERROR_RELATED_RECORD_NOT_FOUND
            if SQL_UNIQUE_CONSTRAINT_MARKER in raw_upper:
                return ERROR_DUPLICATE_RECORD
            return ERROR_DUPLICATE_RECORD
        if sqlalchemy_exc is not None and isinstance(error, sqlalchemy_exc.OperationalError):
            return ERROR_DB_OPERATION_FAILED
        if sqlalchemy_exc is not None and isinstance(error, sqlalchemy_exc.ProgrammingError):
            return ERROR_SQL_QUERY_FAILED
        if sqlalchemy_exc is not None and isinstance(error, sqlalchemy_exc.DatabaseError):
            return ERROR_DATABASE_GENERIC
    except Exception:
        pass

    if isinstance(error, ConnectionError):
        return ERROR_SERVER_CONNECTION_FAILED
    if isinstance(error, TimeoutError):
        return ERROR_TIMEOUT

    try:
        if _error_from_module(error, "httpx"):
            httpx_module = _optional_module("httpx")
        else:
            httpx_module = None
        if httpx_module is not None:
            if isinstance(error, httpx_module.HTTPStatusError):
                response = getattr(error, "response", None)
                status_code = getattr(response, "status_code", None)
                if status_code is not None:
                    return ERROR_HTTP_STATUS_TEMPLATE.format(status_code=int(status_code))
                return ERROR_HTTP_FAILED
            if isinstance(error, httpx_module.TimeoutException):
                return ERROR_HTTP_TIMEOUT
            if isinstance(error, httpx_module.RequestError):
                return ERROR_HTTP_CONNECTION
    except Exception:
        pass

    try:
        aiohttp_module = _optional_module("aiohttp") if _error_from_module(error, "aiohttp") else None
        if aiohttp_module is not None and isinstance(error, aiohttp_module.ClientError):
            return ERROR_NETWORK_CONNECTION
    except Exception:
        pass

    try:
        requests_module = _optional_module("requests") if _error_from_module(error, "requests") else None
        if requests_module is not None and isinstance(error, requests_module.exceptions.Timeout):
            return ERROR_HTTP_TIMEOUT
        if requests_module is not None and isinstance(error, requests_module.exceptions.RequestException):
            return ERROR_HTTP_FAILED
    except Exception:
        pass

    if isinstance(error, FileNotFoundError):
        return ERROR_FILE_NOT_FOUND
    if isinstance(error, PermissionError):
        return ERROR_PERMISSION_DENIED
    if isinstance(error, IsADirectoryError):
        return ERROR_DIRECTORY_GIVEN
    if isinstance(error, OSError):
        return ERROR_OS_FILE

    if isinstance(error, json.JSONDecodeError):
        return ERROR_JSON_INVALID
    if isinstance(error, ValueError):
        return ERROR_VALUE_INVALID
    if isinstance(error, TypeError):
        return ERROR_TYPE_UNEXPECTED
    if isinstance(error, KeyError):
        return ERROR_KEY_MISSING
    if isinstance(error, IndexError):
        return ERROR_INDEX_INVALID
    if isinstance(error, RuntimeError):
        return ERROR_RUNTIME

    return ERROR_UNKNOWN_TEMPLATE.format(error_type=type(error).__name__, error=error)
