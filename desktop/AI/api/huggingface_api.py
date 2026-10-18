from __future__ import annotations

from typing import Any

import requests

from Feedback.processors.pipeline import Result, map_error_to_message


HF_API_BASE = "https://huggingface.co/api"
HF_WEB_BASE = "https://huggingface.co"
_HF_SESSION: requests.Session | None = None


def _session() -> requests.Session:
    global _HF_SESSION

    if _HF_SESSION is None:
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "OrderScout Desktop",
            }
        )
        _HF_SESSION = session
    return _HF_SESSION


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _request_json(url: str, *, params: dict[str, Any] | None = None, timeout_sec: int = 20) -> Result:
    try:
        response = _session().get(url, params=params, timeout=timeout_sec)
        response.raise_for_status()
        payload = _safe_json(response)
        return Result.ok(
            "Hugging Face API iste?i ba?ar?l?.",
            close_dialog=False,
            data={
                "json": payload,
                "status_code": int(response.status_code or 0),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def search_public_models(
    query: str,
    *,
    limit: int = 16,
    pipeline_tag: str = "text-generation",
) -> Result:
    params = {
        "search": str(query or "").strip() or None,
        "limit": max(1, min(int(limit or 16), 40)),
        "sort": "downloads",
        "direction": -1,
        "pipeline_tag": pipeline_tag or None,
        "full": "true",
    }
    return _request_json(f"{HF_API_BASE}/models", params=params)


def fetch_model_details(repo_id: str) -> Result:
    clean_repo_id = str(repo_id or "").strip()
    if not clean_repo_id:
        return Result.fail("Model repo id bos olamaz.", close_dialog=False)
    return _request_json(f"{HF_API_BASE}/models/{clean_repo_id}")


def build_model_download_url(repo_id: str, filename: str, *, revision: str = "main") -> str:
    clean_repo_id = str(repo_id or "").strip().strip("/")
    clean_filename = str(filename or "").strip().lstrip("/")
    clean_revision = str(revision or "main").strip() or "main"
    return f"{HF_WEB_BASE}/{clean_repo_id}/resolve/{clean_revision}/{clean_filename}?download=true"


def close_hf_session() -> None:
    global _HF_SESSION

    session = _HF_SESSION
    _HF_SESSION = None
    if session is None:
        return
    try:
        session.close()
    except Exception:
        pass
