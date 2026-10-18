from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


CREDENTIAL_REFERENCE_PREFIX = "credential://"
CREDENTIAL_STORE_PATH_ENV = "ORDERSCOUT_CREDENTIAL_STORE_PATH"
_LOCK = threading.RLock()


class CredentialStoreUnavailable(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _store_path(path: str | Path | None = None) -> Path:
    configured = str(path or os.getenv(CREDENTIAL_STORE_PATH_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".orderscout" / "credentials.dpapi.json").resolve()


def is_credential_reference(value: Any) -> bool:
    return str(value or "").strip().startswith(CREDENTIAL_REFERENCE_PREFIX)


def coalesce_credential_bundle_reference(
    explicit_reference: Any,
    inline_value: Any,
    *,
    companion_value: Any = None,
) -> tuple[str, str]:
    """Normalize one bundle reference that may be repeated in a legacy value field.

    Older schemas sometimes keep the opaque reference in a field that previously held
    a raw API key while newer metadata also carries the same reference explicitly.  A
    repeated reference is one identity, never an API key. Conflicting references and a
    bundle reference mixed with a raw companion secret are rejected before any request.
    """

    reference = str(explicit_reference or "").strip()
    value = str(inline_value or "").strip()
    companion = str(companion_value or "").strip()
    if not is_credential_reference(value):
        return reference, value
    if reference:
        if reference != value:
            raise ValueError("Conflicting credential bundle references.")
        if companion:
            raise ValueError("Credential bundle reference cannot be mixed with a companion secret.")
        return reference, ""
    if not companion:
        return value, ""
    return reference, value


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    return (
        _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))),
        buffer,
    )


def _protect(secret: str) -> bytes:
    if os.name != "nt":
        raise CredentialStoreUnavailable(
            "Secure credential storage requires Windows DPAPI on this runtime."
        )
    raw = str(secret or "").encode("utf-8")
    input_blob, input_buffer = _blob(raw)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "OrderScout credential",
        None,
        None,
        None,
        0x01,
        ctypes.byref(output_blob),
    )
    _ = input_buffer
    if not ok:
        raise CredentialStoreUnavailable("Windows DPAPI could not protect the credential.")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect(ciphertext: bytes) -> str:
    if os.name != "nt":
        raise CredentialStoreUnavailable(
            "Secure credential storage requires Windows DPAPI on this runtime."
        )
    input_blob, input_buffer = _blob(ciphertext)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0x01,
        ctypes.byref(output_blob),
    )
    _ = input_buffer
    if not ok:
        raise CredentialStoreUnavailable("Windows DPAPI could not open the credential.")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _read_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "credentials": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CredentialStoreUnavailable("Credential store payload is invalid.")
    credentials = payload.get("credentials")
    if not isinstance(credentials, dict):
        credentials = {}
    return {"schema_version": 1, "credentials": credentials}


def _write_store(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def store_secret(
    namespace: str,
    secret: str,
    *,
    reference: str | None = None,
    store_path: str | Path | None = None,
) -> str:
    clean_secret = str(secret or "")
    if not clean_secret:
        raise ValueError("Credential secret is required.")
    clean_namespace = "-".join(
        token for token in str(namespace or "general").strip().casefold().split() if token
    ) or "general"
    credential_ref = str(reference or "").strip()
    if not is_credential_reference(credential_ref):
        credential_ref = f"{CREDENTIAL_REFERENCE_PREFIX}{clean_namespace}/{uuid4().hex}"
    encrypted = base64.b64encode(_protect(clean_secret)).decode("ascii")
    now = datetime.now(timezone.utc).isoformat()
    path = _store_path(store_path)
    with _LOCK:
        payload = _read_store(path)
        credentials = dict(payload.get("credentials") or {})
        previous = credentials.get(credential_ref)
        credentials[credential_ref] = {
            "namespace": clean_namespace,
            "ciphertext": encrypted,
            "created_at": (
                str(previous.get("created_at") or now)
                if isinstance(previous, dict)
                else now
            ),
            "updated_at": now,
            "protection": "windows_dpapi_current_user",
        }
        payload["credentials"] = credentials
        _write_store(path, payload)
    return credential_ref


def store_credential_bundle(
    namespace: str,
    values: Mapping[str, Any],
    *,
    reference: str | None = None,
    store_path: str | Path | None = None,
) -> str:
    """Store a structured credential payload as one DPAPI-protected secret.

    Databases and configuration files keep only the returned opaque reference.  The
    bundle is intentionally generic so marketplace and provider domains can share the
    same Core primitive without Core learning their field names.
    """

    payload = {str(key): value for key, value in dict(values or {}).items()}
    if not payload:
        raise ValueError("Credential bundle is required.")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Credential bundle must be JSON serializable.") from exc
    return store_secret(
        namespace,
        encoded,
        reference=reference,
        store_path=store_path,
    )


def resolve_secret(
    reference: str,
    *,
    store_path: str | Path | None = None,
) -> str:
    credential_ref = str(reference or "").strip()
    if not is_credential_reference(credential_ref):
        raise ValueError("Credential reference is invalid.")
    path = _store_path(store_path)
    with _LOCK:
        payload = _read_store(path)
        row = (payload.get("credentials") or {}).get(credential_ref)
    if not isinstance(row, dict):
        raise CredentialStoreUnavailable("Credential reference was not found.")
    encoded = str(row.get("ciphertext") or "").strip()
    if not encoded:
        raise CredentialStoreUnavailable("Credential ciphertext is missing.")
    return _unprotect(base64.b64decode(encoded.encode("ascii")))


def resolve_credential_bundle(
    reference: str,
    *,
    store_path: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve a DPAPI-backed JSON credential bundle without exposing it to storage."""

    try:
        payload = json.loads(resolve_secret(reference, store_path=store_path))
    except json.JSONDecodeError as exc:
        raise CredentialStoreUnavailable("Credential bundle payload is invalid.") from exc
    if not isinstance(payload, dict):
        raise CredentialStoreUnavailable("Credential bundle payload is invalid.")
    return {str(key): value for key, value in payload.items()}


def delete_secret(
    reference: str,
    *,
    store_path: str | Path | None = None,
) -> bool:
    credential_ref = str(reference or "").strip()
    if not is_credential_reference(credential_ref):
        return False
    path = _store_path(store_path)
    with _LOCK:
        payload = _read_store(path)
        credentials = dict(payload.get("credentials") or {})
        removed = credentials.pop(credential_ref, None) is not None
        if removed:
            payload["credentials"] = credentials
            _write_store(path, payload)
    return removed
