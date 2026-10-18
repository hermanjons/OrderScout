from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from sqlmodel import Session, select

from AI.api.huggingface_api import (
    build_model_download_url,
    fetch_model_details,
    search_public_models,
)
from AI.processors.local_resources import build_local_resource_plan
from AI.processors.model_routing import build_free_model_test_route
from AI.processors.provider_catalog_policy import (
    provider_free_model_quality_prior,
    provider_model_access,
)
from AI.processors.provider_adapters import capability_profile_from_record
from AI.processors.cloud_runtime import (
    DEFAULT_BASE_URLS,
    provider_reasoning_capabilities,
    raise_for_status_safely,
)
from AI.constants import (
    AI_CONFIG_FILE,
    AI_DEFAULT_MODELS_DIR,
    ensure_ai_paths,
)
from AI.constants.config_constants import (
    AI_DEFAULT_PREFERRED_EXTENSIONS,
    AI_DEFAULT_SEARCH_LIMIT,
    AI_DEFAULT_SETTINGS,
)
from AI.models import AiModelArtifact, AiProviderAccount
from Core.processors.credential_store import (
    delete_secret,
    is_credential_reference,
    resolve_secret,
    store_secret,
)
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from settings import DB_NAME


def _engine(db_name: str = DB_NAME):
    return get_engine(db_name)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _read_json(path: Path, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        if not path.exists():
            return dict(default or {})
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else dict(default or {})
    except Exception:
        return dict(default or {})


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload or {}), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _model_config_key_from_parts(repo_id: str, filename: str, local_path: str = "") -> str:
    clean_local_path = _compact_text(local_path)
    if clean_local_path:
        return f"llama_cpp::{clean_local_path}"
    return f"{_compact_text(repo_id)}::{_compact_text(filename)}"


def _model_config_key(record: dict[str, Any]) -> str:
    return _model_config_key_from_parts(
        _compact_text(record.get("repo_id")),
        _compact_text(record.get("filename")),
        _compact_text(record.get("local_path")),
    )


def _runtime_config_store(settings: dict[str, Any]) -> dict[str, Any]:
    store = settings.get("model_runtime_configs")
    return dict(store) if isinstance(store, dict) else {}


def _provider_runtime_config_store(settings: dict[str, Any]) -> dict[str, Any]:
    store = settings.get("provider_runtime_configs")
    return dict(store) if isinstance(store, dict) else {}


def _default_settings() -> dict[str, Any]:
    ensure_ai_paths()
    defaults = dict(AI_DEFAULT_SETTINGS)
    defaults.setdefault("search_limit", AI_DEFAULT_SEARCH_LIMIT)
    defaults.setdefault("prefer_extensions", list(AI_DEFAULT_PREFERRED_EXTENSIONS))
    defaults["download_root"] = str(AI_DEFAULT_MODELS_DIR)
    return defaults


def _normalize_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clean = dict(payload or {})
    clean["prefer_extensions"] = [".gguf"]
    store = clean.get("model_runtime_configs")
    if isinstance(store, dict):
        clean["model_runtime_configs"] = {
            str(key): value
            for key, value in store.items()
            if isinstance(value, dict) and not str(key).casefold().startswith("ollama::")
        }
    provider_store = clean.get("provider_runtime_configs")
    if isinstance(provider_store, dict):
        clean["provider_runtime_configs"] = {
            str(key): value
            for key, value in provider_store.items()
            if isinstance(value, dict)
        }
    return clean


def _normalize_dir(path_value: str | Path | None) -> Path:
    raw = str(path_value or "").strip()
    if not raw:
        return Path(AI_DEFAULT_MODELS_DIR)
    return Path(raw).expanduser().resolve()


def load_ai_settings(*, settings_path: str | Path | None = None) -> Result:
    try:
        defaults = _default_settings()
        path = Path(settings_path) if settings_path not in (None, "") else AI_CONFIG_FILE
        payload = _normalize_settings_payload({**defaults, **_read_json(path, default={})})
        payload["download_root"] = str(_normalize_dir(payload.get("download_root")))
        return Result.ok("AI ayarlari yuklendi.", close_dialog=False, data={"settings": payload})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def set_ai_download_root(
    download_root: str,
    *,
    settings_path: str | Path | None = None,
) -> Result:
    try:
        clean_root = _normalize_dir(download_root)
        clean_root.mkdir(parents=True, exist_ok=True)

        defaults = _default_settings()
        path = Path(settings_path) if settings_path not in (None, "") else AI_CONFIG_FILE
        payload = _normalize_settings_payload({**defaults, **_read_json(path, default={})})
        payload["download_root"] = str(clean_root)
        _write_json(path, payload)

        return Result.ok(
            "AI indirme klasoru kaydedildi.",
            close_dialog=False,
            data={"settings": payload},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


_PROVIDER_LABELS = {
    "gemini": "Google Gemini",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "anthropic": "Anthropic",
    "groq": "Groq",
    "together": "Together AI",
    "mistral": "Mistral AI",
}


def list_provider_connection_specs() -> Result:
    records = [
        {
            "code": code,
            "label": label,
            "endpoint": _compact_text(DEFAULT_BASE_URLS.get(code)),
        }
        for code, label in _PROVIDER_LABELS.items()
    ]
    return Result.ok(
        "Provider baglanti katalogu getirildi.",
        close_dialog=False,
        data={"records": records},
    )


def _provider_models_endpoint(provider_code: str, endpoint_url: str | None = None) -> str:
    base = _compact_text(endpoint_url) or DEFAULT_BASE_URLS.get(_compact_text(provider_code).casefold(), "")
    return f"{base.rstrip('/')}/models" if base else ""


def _provider_model_is_free(row: dict[str, Any], *, provider_code: str = "") -> bool:
    pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
    return provider_model_access(
        provider_code,
        _compact_text(row.get("id")),
        pricing=pricing,
    ).is_free


def _provider_model_pricing_label(row: dict[str, Any], *, provider_code: str = "") -> str:
    pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
    return provider_model_access(
        provider_code,
        _compact_text(row.get("id")),
        pricing=pricing,
    ).pricing_label


def _provider_model_to_dict(row: dict[str, Any], *, provider_code: str = "") -> dict[str, Any]:
    model_id = _compact_text(row.get("id"))
    name = _compact_text(row.get("name")) or model_id
    context_length = row.get("context_length")
    try:
        context_length = int(context_length or 0)
    except Exception:
        context_length = 0
    pricing = dict(row.get("pricing") or {}) if isinstance(row.get("pricing"), dict) else {}
    access = provider_model_access(provider_code, model_id, pricing=pricing)
    record = {
        "id": model_id,
        "name": name,
        "description": _compact_text(row.get("description")),
        "context_length": context_length,
        "pricing": pricing,
        "is_free": access.is_free,
        "free_tier_status": access.free_tier_status,
        "pricing_label": access.pricing_label,
        "chat_eligible": access.chat_eligible,
        "supported_parameters": [
            _compact_text(value)
            for value in list(row.get("supported_parameters") or [])
            if _compact_text(value)
        ],
        "reasoning": dict(row.get("reasoning") or {}) if isinstance(row.get("reasoning"), dict) else {},
    }
    record["reasoning_capabilities"] = provider_reasoning_capabilities(
        provider_code,
        model_id,
        model_metadata=record,
    )
    record["capability_profile"] = capability_profile_from_record(
        {
            "provider_code": provider_code,
            "default_model": model_id,
            "model_metadata": record,
        },
        reasoning=record["reasoning_capabilities"],
    ).to_dict()
    return record


def _gemini_model_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    raw_name = _compact_text(row.get("name"))
    model_id = raw_name.removeprefix("models/")
    methods = [str(item) for item in (row.get("supportedGenerationMethods") or []) if str(item or "").strip()]
    try:
        context_length = int(row.get("inputTokenLimit") or 0)
    except Exception:
        context_length = 0
    try:
        output_token_limit = int(row.get("outputTokenLimit") or 0)
    except Exception:
        output_token_limit = 0
    access = provider_model_access("gemini", model_id)
    record = {
        "id": model_id,
        "name": _compact_text(row.get("displayName")) or model_id,
        "description": _compact_text(row.get("description")),
        "context_length": context_length,
        "output_token_limit": output_token_limit,
        "pricing": {},
        "is_free": access.is_free,
        "free_tier_status": access.free_tier_status,
        "pricing_label": access.pricing_label,
        "chat_eligible": access.chat_eligible,
        "pricing_policy_source": access.policy_source,
        "pricing_policy_reviewed_at": access.policy_reviewed_at,
        "supported_generation_methods": methods,
    }
    record["reasoning_capabilities"] = provider_reasoning_capabilities("gemini", model_id)
    record["capability_profile"] = capability_profile_from_record(
        {
            "provider_code": "gemini",
            "default_model": model_id,
            "model_metadata": record,
        },
        reasoning=record["reasoning_capabilities"],
    ).to_dict()
    return record


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _optional_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _compact_text(value).casefold()
    if text in {"1", "true", "yes", "evet", "on"}:
        return True
    if text in {"0", "false", "no", "hayir", "off"}:
        return False
    return bool(default)


def _format_bytes(value: Any) -> str:
    size = _optional_int(value)
    if size is None or size < 0:
        return "-"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"


def _mask_secret(value: Any) -> str:
    raw = _compact_text(value)
    if not raw:
        return "-"
    if len(raw) <= 8:
        return "****"
    return f"{raw[:4]}...{raw[-4:]}"


def _safe_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _guess_format(filename: str) -> str:
    lower = _compact_text(filename).lower()
    if lower.endswith(".gguf"):
        return "GGUF"
    if lower.endswith(".safetensors"):
        return "SafeTensors"
    if lower.endswith(".bin"):
        return "BIN"
    if "." not in lower:
        return "FILE"
    return lower.rsplit(".", 1)[-1].upper()


_QUANT_RE = re.compile(r"(q\d+(?:_[a-z0-9]+)+|mxfp4|fp16|bf16|int8)", re.IGNORECASE)


def _guess_quantization(filename: str) -> str:
    match = _QUANT_RE.search(_compact_text(filename))
    return match.group(1).upper() if match else "-"


def _file_size_from_payload(row: dict[str, Any]) -> int | None:
    direct = _optional_int(row.get("size"))
    if direct is not None:
        return direct
    lfs = row.get("lfs")
    if isinstance(lfs, dict):
        return _optional_int(lfs.get("size"))
    return None


def _is_downloadable_model_file(filename: str) -> bool:
    lower = _compact_text(filename).lower()
    if not lower:
        return False
    return lower.endswith(".gguf")


def _download_rank(filename: str, preferred_extensions: list[str]) -> tuple[int, int, str]:
    lower = _compact_text(filename).lower()
    ext = Path(lower).suffix.lower()
    try:
        ext_rank = preferred_extensions.index(ext)
    except ValueError:
        ext_rank = len(preferred_extensions) + 1

    quant = _guess_quantization(lower)
    quant_order = {
        "Q4_K_M": 0,
        "Q5_K_M": 1,
        "Q4_K_S": 2,
        "Q6_K": 3,
        "Q8_0": 4,
        "FP16": 5,
        "BF16": 6,
        "-": 7,
    }
    return ext_rank, quant_order.get(quant, 20), lower


def _normalize_search_row(row: dict[str, Any]) -> dict[str, Any]:
    repo_id = _compact_text(row.get("id") or row.get("modelId"))
    siblings = _safe_list(row.get("siblings"))
    card_data = row.get("cardData") if isinstance(row.get("cardData"), dict) else {}
    has_downloadable = any(
        _is_downloadable_model_file(_compact_text(item.get("rfilename")))
        for item in siblings
        if isinstance(item, dict)
    )
    return {
        "repo_id": repo_id,
        "title": repo_id,
        "downloads": _optional_int(row.get("downloads")) or 0,
        "likes": _optional_int(row.get("likes")) or 0,
        "last_modified": _compact_text(row.get("lastModified")) or "-",
        "pipeline_tag": _compact_text(row.get("pipeline_tag")) or "-",
        "gated": bool(row.get("gated", False)),
        "private": bool(row.get("private", False)),
        "description": _compact_text(row.get("description") or card_data.get("summary")),
        "tags": [str(tag) for tag in _safe_list(row.get("tags"))[:8]],
        "has_downloadable": has_downloadable,
    }


def search_hf_models(
    query: str,
    *,
    limit: int | None = None,
) -> Result:
    try:
        settings_res = load_ai_settings()
        if not settings_res.success:
            return settings_res
        settings = settings_res.data.get("settings", {}) or {}
        safe_limit = max(1, min(int(limit or settings.get("search_limit") or 16), 30))

        api_res = search_public_models(query, limit=safe_limit)
        if not api_res.success:
            return api_res

        rows = _safe_list((api_res.data or {}).get("json"))
        records = [
            _normalize_search_row(row)
            for row in rows
            if isinstance(row, dict)
        ]
        records = [
            row for row in records
            if row.get("repo_id") and not row.get("private") and not row.get("gated")
        ]

        return Result.ok(
            "Hugging Face model arama tamamlandi.",
            close_dialog=False,
            data={"records": records},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def get_hf_model_details(repo_id: str) -> Result:
    try:
        clean_repo_id = _compact_text(repo_id)
        if not clean_repo_id:
            return Result.fail("Model seçilmedi.", close_dialog=False)

        settings_res = load_ai_settings()
        if not settings_res.success:
            return settings_res
        settings = settings_res.data.get("settings", {}) or {}
        preferred_extensions = [
            str(ext or "").strip().lower()
            for ext in list(settings.get("prefer_extensions") or [".gguf"])
            if str(ext or "").strip()
        ]

        api_res = fetch_model_details(clean_repo_id)
        if not api_res.success:
            return api_res

        payload = dict((api_res.data or {}).get("json") or {})
        card_data = payload.get("cardData") if isinstance(payload.get("cardData"), dict) else {}
        siblings = _safe_list(payload.get("siblings"))
        files: list[dict[str, Any]] = []
        for row in siblings:
            if not isinstance(row, dict):
                continue
            filename = _compact_text(row.get("rfilename"))
            if not _is_downloadable_model_file(filename):
                continue
            size_bytes = _file_size_from_payload(row)
            files.append(
                {
                    "filename": filename,
                    "format": _guess_format(filename),
                    "quantization": _guess_quantization(filename),
                    "size_bytes": size_bytes,
                    "size_text": _format_bytes(size_bytes),
                    "download_url": build_model_download_url(clean_repo_id, filename),
                }
            )

        files.sort(key=lambda item: _download_rank(str(item.get("filename") or ""), preferred_extensions))

        detail = {
            "repo_id": clean_repo_id,
            "title": clean_repo_id,
            "author": _compact_text(payload.get("author")),
            "downloads": _optional_int(payload.get("downloads")) or 0,
            "likes": _optional_int(payload.get("likes")) or 0,
            "last_modified": _compact_text(payload.get("lastModified")) or "-",
            "pipeline_tag": _compact_text(payload.get("pipeline_tag")) or "-",
            "tags": [str(tag) for tag in _safe_list(payload.get("tags"))[:12]],
            "description": _compact_text(payload.get("description") or card_data.get("summary")),
            "files": files,
        }

        return Result.ok(
            "Model detayı yüklendi.",
            close_dialog=False,
            data={"detail": detail},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _safe_repo_dir(repo_id: str) -> Path:
    clean = _compact_text(repo_id).strip("/")
    parts = [part for part in clean.split("/") if part]
    if not parts:
        parts = ["model"]
    return Path(*parts)


def _record_to_dict(record: AiModelArtifact) -> dict[str, Any]:
    local_path = Path(str(record.local_path or ""))
    exists = local_path.exists() if str(record.local_path or "").strip() else False
    return {
        "id": int(record.pk or 0),
        "repo_id": str(record.repo_id or ""),
        "filename": str(record.filename or ""),
        "display_name": str(record.display_name or "") or str(record.repo_id or ""),
        "file_format": str(record.file_format or ""),
        "quantization": str(record.quantization or ""),
        "size_bytes": record.size_bytes,
        "size_text": _format_bytes(record.size_bytes),
        "local_path": str(record.local_path or ""),
        "download_root": str(record.download_root or ""),
        "source_url": str(record.source_url or ""),
        "exists_on_disk": bool(exists),
        "updated_at": record.updated_at.isoformat() if isinstance(record.updated_at, datetime) else str(record.updated_at or ""),
    }


def infer_local_model_capabilities(record: dict[str, Any]) -> dict[str, Any]:
    haystack = " ".join(
        _compact_text(record.get(key))
        for key in ("repo_id", "filename", "display_name", "file_format", "quantization", "local_path")
    ).casefold()
    is_gguf = "gguf" in haystack or _compact_text(record.get("file_format")).casefold() == "gguf"
    reasoning = any(token in haystack for token in ("gpt-oss", "reason", "deepseek-r1", "qwen", "r1"))
    return {
        "supports_reasoning_effort": reasoning,
        "supports_gpu_layers": is_gguf,
        "supports_mmap": is_gguf,
        "supports_keep_alive": True,
        "runtime_sources": ["llama_cpp"] if is_gguf and bool(_compact_text(record.get("local_path"))) else [],
    }


def _default_runtime_config(record: dict[str, Any]) -> dict[str, Any]:
    capabilities = infer_local_model_capabilities(record)
    plan = build_local_resource_plan(record)
    reasoning_effort = "auto"
    if capabilities.get("supports_reasoning_effort"):
        reasoning_effort = "low" if str(plan.profile).startswith("disk_guarded") or float(plan.memory_pressure or 0) >= 0.55 else "medium"
    return {
        "performance_preset": "auto",
        "runtime_strategy": "llama_cpp",
        "reasoning_effort": reasoning_effort,
        "num_ctx": plan.num_ctx,
        "max_tokens": plan.max_tokens,
        "num_thread": plan.num_thread,
        "num_batch": plan.num_batch,
        "num_gpu": plan.num_gpu,
        "keep_alive": plan.keep_alive,
        "use_mmap": True,
        "use_mlock": False,
        "allow_unsafe": False,
    }


def _merge_runtime_config(record: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    key = _model_config_key(record)
    store = _runtime_config_store(settings)
    saved = store.get(key)
    if not isinstance(saved, dict):
        saved = {}
    return {**_default_runtime_config(record), **saved, "config_key": key}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        parsed = default
    return max(minimum, min(int(parsed), maximum))


def _sanitize_runtime_config(record: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_runtime_config(record)
    capabilities = infer_local_model_capabilities(record)
    runtime_strategy = "llama_cpp"

    performance_preset = _compact_text(config.get("performance_preset") or defaults.get("performance_preset")).casefold()
    if performance_preset not in {"auto", "eco", "balanced", "fast"}:
        performance_preset = "auto"

    reasoning_effort = _compact_text(config.get("reasoning_effort") or defaults.get("reasoning_effort")).casefold()
    if reasoning_effort not in {"auto", "low", "medium", "high"}:
        reasoning_effort = str(defaults.get("reasoning_effort") or "auto")
    if not bool(capabilities.get("supports_reasoning_effort")):
        reasoning_effort = "auto"

    keep_alive = _compact_text(config.get("keep_alive") or defaults.get("keep_alive"))
    if not re.fullmatch(r"\d+\s*(ms|s|m|h)", keep_alive.casefold()):
        keep_alive = str(defaults.get("keep_alive") or "0s")

    clean = {
        "performance_preset": performance_preset,
        "runtime_strategy": runtime_strategy,
        "reasoning_effort": reasoning_effort,
        "num_ctx": _bounded_int(config.get("num_ctx"), default=int(defaults.get("num_ctx") or 2048), minimum=512, maximum=8192),
        "max_tokens": _bounded_int(config.get("max_tokens"), default=int(defaults.get("max_tokens") or 384), minimum=64, maximum=2048),
        "num_thread": _bounded_int(config.get("num_thread"), default=int(defaults.get("num_thread") or 2), minimum=1, maximum=max(1, os.cpu_count() or 1)),
        "num_batch": _bounded_int(config.get("num_batch"), default=int(defaults.get("num_batch") or 64), minimum=8, maximum=512),
        "num_gpu": _bounded_int(config.get("num_gpu"), default=int(defaults.get("num_gpu") or 0), minimum=0, maximum=99),
        "keep_alive": keep_alive,
        "use_mmap": bool(_optional_bool(config.get("use_mmap"), bool(defaults.get("use_mmap", True)))) if capabilities.get("supports_mmap") else False,
        "use_mlock": bool(_optional_bool(config.get("use_mlock"), bool(defaults.get("use_mlock", False)))),
        "allow_unsafe": bool(_optional_bool(config.get("allow_unsafe"), bool(defaults.get("allow_unsafe", False)))),
    }
    return {**clean, "config_key": _model_config_key(record)}


def _provider_runtime_config_key(record: dict[str, Any]) -> str:
    return "::".join(
        (
            "provider",
            str(_optional_int(record.get("id")) or 0),
            _compact_text(record.get("provider_code")).casefold(),
            _compact_text(record.get("default_model")).casefold(),
        )
    )


def _merge_provider_runtime_config(record: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    capabilities = provider_reasoning_capabilities(
        _compact_text(record.get("provider_code")),
        _compact_text(record.get("default_model")),
        model_metadata=dict(record.get("model_metadata") or {}) if isinstance(record.get("model_metadata"), dict) else {},
    )
    key = _provider_runtime_config_key(record)
    saved = _provider_runtime_config_store(settings).get(key)
    if not isinstance(saved, dict):
        saved = {}
    effort = _compact_text(saved.get("reasoning_effort")).casefold() or "auto"
    allowed = list(capabilities.get("efforts") or ["auto"])
    if effort not in allowed:
        effort = "auto"
    return {
        "config_key": key,
        "reasoning_effort": effort,
        "reasoning_capabilities": capabilities,
    }


def _enrich_provider_runtime_config(record: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    runtime = _merge_provider_runtime_config(record, settings)
    return {
        **record,
        "reasoning_effort": runtime["reasoning_effort"],
        "reasoning_capabilities": runtime["reasoning_capabilities"],
        "provider_runtime_config": runtime,
    }


def save_provider_runtime_config(
    record: dict[str, Any],
    *,
    reasoning_effort: str = "auto",
    settings_path: str | Path | None = None,
) -> Result:
    try:
        if not isinstance(record, dict) or not _optional_int(record.get("id")):
            return Result.fail("Cloud provider runtime ayari icin kayit gerekir.", close_dialog=False)
        path = Path(settings_path) if settings_path not in (None, "") else AI_CONFIG_FILE
        payload = _normalize_settings_payload({**_default_settings(), **_read_json(path, default={})})
        enriched = _enrich_provider_runtime_config(record, payload)
        capabilities = dict(enriched.get("reasoning_capabilities") or {})
        effort = _compact_text(reasoning_effort).casefold() or "auto"
        allowed = list(capabilities.get("efforts") or ["auto"])
        if effort not in allowed:
            effort = "auto"
        store = _provider_runtime_config_store(payload)
        store[_provider_runtime_config_key(record)] = {"reasoning_effort": effort}
        payload["provider_runtime_configs"] = store
        _write_json(path, payload)
        saved = _enrich_provider_runtime_config(record, payload)
        return Result.ok(
            "Cloud provider reasoning ayari kaydedildi.",
            close_dialog=False,
            data={"record": saved, "settings": payload},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def _provider_record_to_dict(
    record: AiProviderAccount,
    *,
    include_secret: bool = False,
) -> dict[str, Any]:
    stored_credential = str(record.api_key or "")
    secret = (
        resolve_secret(stored_credential)
        if is_credential_reference(stored_credential)
        else stored_credential
    )
    payload = {
        "id": int(record.pk or 0),
        "provider_code": str(record.provider_code or ""),
        "provider_label": _PROVIDER_LABELS.get(str(record.provider_code or "").strip().lower(), str(record.provider_code or "")),
        "label": str(record.label or ""),
        "endpoint_url": str(record.endpoint_url or ""),
        "default_model": str(record.default_model or ""),
        "is_enabled": bool(record.is_enabled),
        "api_key_masked": _mask_secret(secret),
        "credential_managed": is_credential_reference(stored_credential),
        "updated_at": record.updated_at.isoformat() if isinstance(record.updated_at, datetime) else str(record.updated_at or ""),
    }
    if include_secret:
        payload["api_key"] = secret
    return payload


def _ensure_provider_credential_ref(record: AiProviderAccount) -> bool:
    stored = str(record.api_key or "").strip()
    if not stored or is_credential_reference(stored):
        return False
    record.api_key = store_secret(
        f"ai-provider-{str(record.provider_code or 'custom').strip().casefold()}",
        stored,
    )
    return True


def _upsert_installed_model(
    *,
    repo_id: str,
    filename: str,
    local_path: str,
    download_root: str,
    file_format: str,
    quantization: str,
    size_bytes: int | None,
    source_url: str,
    etag: str | None = None,
    db_name: str = DB_NAME,
) -> dict[str, Any]:
    now = _utcnow_naive()
    with Session(_engine(db_name)) as session:
        existing = session.exec(
            select(AiModelArtifact).where(
                AiModelArtifact.local_path == local_path,
            )
        ).first()
        if existing is None:
            existing = session.exec(
            select(AiModelArtifact).where(
                AiModelArtifact.repo_id == repo_id,
                AiModelArtifact.filename == filename,
            )
            ).first()

        if existing is None:
            existing = AiModelArtifact(
                repo_id=repo_id,
                filename=filename,
                display_name=repo_id,
                file_format=file_format,
                quantization=quantization,
                size_bytes=size_bytes,
                local_path=local_path,
                download_root=download_root,
                source_url=source_url,
                etag=etag,
                exists_on_disk=True,
                created_at=now,
                updated_at=now,
            )
            session.add(existing)
        else:
            existing.display_name = repo_id
            existing.file_format = file_format
            existing.quantization = quantization
            existing.size_bytes = size_bytes
            existing.local_path = local_path
            existing.download_root = download_root
            existing.source_url = source_url
            existing.etag = etag
            existing.exists_on_disk = True
            existing.updated_at = now

        session.commit()
        session.refresh(existing)
        return _record_to_dict(existing)


def _repo_id_from_download_path(download_root: Path, model_path: Path) -> str:
    """Recover the Hugging Face repository represented by our download layout.

    Model Hub stores downloads as ``<root>/<owner>/<repo>/<filename>``. Files
    manually copied directly below the root are still discoverable, but receive
    an explicit local identity instead of pretending to have a remote source.
    """
    relative = model_path.relative_to(download_root)
    parent_parts = [part for part in relative.parts[:-1] if part]
    if len(parent_parts) >= 2:
        return "/".join(parent_parts[:2])
    if parent_parts:
        return parent_parts[0]
    return f"local/{model_path.stem}"


def reconcile_installed_models(
    *,
    download_root: str | Path | None = None,
    settings_path: str | Path | None = None,
    db_name: str = DB_NAME,
) -> Result:
    """Rebuild the local-model registry from complete GGUF files on disk.

    The database is an index, not the source of truth for downloaded model
    binaries. Reconciliation is deliberately non-destructive: missing rows are
    marked unavailable and retained, while complete files are upserted. Partial
    downloads and symlinks escaping the configured root are ignored.
    """
    try:
        if download_root in (None, ""):
            settings_res = load_ai_settings(settings_path=settings_path)
            if not settings_res.success:
                return settings_res
            settings = dict((settings_res.data or {}).get("settings") or {})
            resolved_root = _normalize_dir(settings.get("download_root"))
        else:
            resolved_root = _normalize_dir(download_root)

        discovered_paths: list[Path] = []
        if resolved_root.exists() and resolved_root.is_dir():
            for candidate in resolved_root.rglob("*"):
                if candidate.suffix.casefold() != ".gguf" or not candidate.is_file():
                    continue
                resolved_candidate = candidate.resolve()
                try:
                    resolved_candidate.relative_to(resolved_root)
                except ValueError:
                    continue
                discovered_paths.append(resolved_candidate)

        records: list[dict[str, Any]] = []
        for model_path in sorted(discovered_paths, key=lambda value: str(value).casefold()):
            repo_id = _repo_id_from_download_path(resolved_root, model_path)
            is_remote_layout = len(model_path.relative_to(resolved_root).parts) >= 3
            source_url = build_model_download_url(repo_id, model_path.name) if is_remote_layout else ""
            records.append(
                _upsert_installed_model(
                    repo_id=repo_id,
                    filename=model_path.name,
                    local_path=str(model_path),
                    download_root=str(resolved_root),
                    file_format=_guess_format(model_path.name),
                    quantization=_guess_quantization(model_path.name),
                    size_bytes=model_path.stat().st_size,
                    source_url=source_url,
                    db_name=db_name,
                )
            )

        missing_count = 0
        with Session(_engine(db_name)) as session:
            rows = session.exec(select(AiModelArtifact)).all()
            for row in rows:
                try:
                    row_root = Path(str(row.download_root or "")).expanduser().resolve()
                except Exception:
                    continue
                if row_root != resolved_root:
                    continue
                exists = bool(str(row.local_path or "").strip()) and Path(str(row.local_path)).is_file()
                if bool(row.exists_on_disk) != exists:
                    row.exists_on_disk = exists
                    row.updated_at = _utcnow_naive()
                    session.add(row)
                if not exists:
                    missing_count += 1
            session.commit()

        return Result.ok(
            "Yerel model kayıtları disk ile uzlaştırıldı.",
            close_dialog=False,
            data={
                "download_root": str(resolved_root),
                "discovered_count": len(discovered_paths),
                "missing_count": missing_count,
                "records": records,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_installed_models(
    *,
    db_name: str = DB_NAME,
    settings_path: str | Path | None = None,
    download_root: str | Path | None = None,
    reconcile_disk: bool = True,
) -> Result:
    try:
        settings: dict[str, Any] = {}
        should_load_settings = str(db_name) == str(DB_NAME) or settings_path not in (None, "")
        if should_load_settings:
            settings_res = load_ai_settings(settings_path=settings_path)
            if settings_res.success:
                settings = dict((settings_res.data or {}).get("settings") or {})
        if reconcile_disk and (download_root not in (None, "") or should_load_settings):
            reconcile_res = reconcile_installed_models(
                download_root=download_root,
                settings_path=settings_path,
                db_name=db_name,
            )
            if not reconcile_res.success:
                return reconcile_res
        with Session(_engine(db_name)) as session:
            rows = session.exec(
                select(AiModelArtifact).order_by(AiModelArtifact.updated_at.desc())
            ).all()
        records = [_record_to_dict(row) for row in rows]
        if settings:
            for record in records:
                config = _merge_runtime_config(record, settings)
                enriched = {**record, "runtime_config": config}
                record["runtime_config"] = config
                record["runtime_capabilities"] = infer_local_model_capabilities(record)
                record["resource_plan"] = build_local_resource_plan(enriched).to_dict()
        return Result.ok(
            "Yüklü AI modelleri listelendi.",
            close_dialog=False,
            data={"records": records},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def get_local_model_runtime_config(
    record: dict[str, Any],
    *,
    settings_path: str | Path | None = None,
) -> Result:
    try:
        if not isinstance(record, dict) or not _compact_text(record.get("repo_id")):
            return Result.fail("Lokal model kaydi secilmedi.", close_dialog=False)
        settings_res = load_ai_settings(settings_path=settings_path)
        if not settings_res.success:
            return settings_res
        settings = dict((settings_res.data or {}).get("settings") or {})
        config = _merge_runtime_config(record, settings)
        enriched = {**record, "runtime_config": config}
        capabilities = infer_local_model_capabilities(record)
        plan = build_local_resource_plan(enriched)
        return Result.ok(
            "Lokal model calisma ayarlari yuklendi.",
            close_dialog=False,
            data={
                "record": enriched,
                "config": config,
                "capabilities": capabilities,
                "resource_plan": plan.to_dict(),
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def save_local_model_runtime_config(
    record: dict[str, Any],
    config: dict[str, Any],
    *,
    settings_path: str | Path | None = None,
) -> Result:
    try:
        if not isinstance(record, dict) or not _compact_text(record.get("repo_id")):
            return Result.fail("Lokal model kaydi secilmedi.", close_dialog=False)
        if not isinstance(config, dict):
            config = {}

        path = Path(settings_path) if settings_path not in (None, "") else AI_CONFIG_FILE
        payload = _normalize_settings_payload({**_default_settings(), **_read_json(path, default={})})
        clean = _sanitize_runtime_config(record, dict(config))
        key = str(clean.get("config_key") or _model_config_key(record))
        store = _runtime_config_store(payload)
        store[key] = {name: value for name, value in clean.items() if name != "config_key"}
        payload["model_runtime_configs"] = store
        _write_json(path, payload)

        merged = _merge_runtime_config(record, payload)
        enriched = {**record, "runtime_config": merged}
        capabilities = infer_local_model_capabilities(record)
        plan = build_local_resource_plan(enriched)
        return Result.ok(
            "Lokal model calisma ayarlari kaydedildi.",
            close_dialog=False,
            data={
                "record": enriched,
                "config": merged,
                "capabilities": capabilities,
                "resource_plan": plan.to_dict(),
                "settings": payload,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_provider_accounts(
    *,
    db_name: str = DB_NAME,
    include_secret: bool = False,
    settings_path: str | Path | None = None,
) -> Result:
    try:
        with Session(_engine(db_name)) as session:
            rows = session.exec(
                select(AiProviderAccount).order_by(
                    AiProviderAccount.is_enabled.desc(),
                    AiProviderAccount.updated_at.desc(),
                )
            ).all()
            migrated = False
            for row in rows:
                if _ensure_provider_credential_ref(row):
                    session.add(row)
                    migrated = True
            if migrated:
                session.commit()
                for row in rows:
                    session.refresh(row)
        settings_res = load_ai_settings(settings_path=settings_path)
        settings = dict((settings_res.data or {}).get("settings") or {}) if settings_res.success else {}
        records = [
            _enrich_provider_runtime_config(
                _provider_record_to_dict(row, include_secret=include_secret),
                settings,
            )
            for row in rows
        ]
        return Result.ok(
            "Cloud provider hesapları listelendi.",
            close_dialog=False,
            data={"records": records},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_provider_models(
    *,
    provider_code: str,
    endpoint_url: str | None = None,
    api_key: str | None = None,
    query: str | None = None,
    free_only: bool = False,
    limit: int | None = None,
    route_state: dict[str, Any] | None = None,
    accessibility: dict[str, dict[str, Any]] | None = None,
    quality: dict[str, dict[str, Any]] | None = None,
) -> Result:
    try:
        clean_provider = _compact_text(provider_code).casefold()
        endpoint = _provider_models_endpoint(clean_provider, endpoint_url)
        if not endpoint:
            return Result.fail("Provider model endpointi bulunamadi.", close_dialog=False)

        headers = {"Accept": "application/json"}
        clean_key = _compact_text(api_key)
        request_params: dict[str, str] = {}
        if clean_provider == "gemini" and clean_key:
            request_params["key"] = clean_key
        elif clean_key:
            headers["Authorization"] = f"Bearer {clean_key}"

        response = requests.get(endpoint, headers=headers, params=request_params or None, timeout=45)
        raise_for_status_safely(response)
        payload = response.json()
        if clean_provider == "gemini":
            raw_models = payload.get("models") if isinstance(payload, dict) else None
        else:
            raw_models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            raw_models = payload if isinstance(payload, list) else []

        clean_query = _compact_text(query).casefold()
        records: list[dict[str, Any]] = []
        for raw in raw_models:
            if not isinstance(raw, dict):
                continue
            record = _gemini_model_to_dict(raw) if clean_provider == "gemini" else _provider_model_to_dict(raw, provider_code=clean_provider)
            if not record.get("id"):
                continue
            if clean_provider == "gemini" and "generateContent" not in (record.get("supported_generation_methods") or []):
                continue
            if not bool(record.get("chat_eligible", True)):
                continue
            haystack = f"{record.get('id')} {record.get('name')} {record.get('description')}".casefold()
            if clean_query and clean_query not in haystack:
                continue
            if free_only and not bool(record.get("is_free")):
                continue
            records.append(record)

        records.sort(
            key=lambda row: (
                not bool(row.get("is_free")),
                _compact_text(row.get("id")).casefold(),
            )
        )
        explicit_quality = dict(quality or {})
        quality_rows: dict[str, dict[str, Any]] = {}
        for record in records:
            model_id = _compact_text(record.get("id")).removeprefix("models/")
            quality_rows[model_id] = {
                **provider_free_model_quality_prior(clean_provider, model_id),
                **dict(explicit_quality.get(model_id) or {}),
            }
        free_model_test_route = build_free_model_test_route(
            clean_provider,
            records,
            state_payload=route_state,
            accessibility=accessibility,
            quality=quality_rows,
            generated_from_live_catalog=True,
        )
        max_rows = max(1, min(int(limit or 120), 500))
        return Result.ok(
            "Provider modelleri listelendi.",
            close_dialog=False,
            data={
                "records": records[:max_rows],
                "total": len(records),
                "free_total": sum(1 for row in records if bool(row.get("is_free"))),
                "free_model_test_route": free_model_test_route.to_dict(),
                "endpoint": endpoint,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def get_provider_account(
    provider_id: int,
    *,
    db_name: str = DB_NAME,
    settings_path: str | Path | None = None,
) -> Result:
    try:
        provider_pk = _optional_int(provider_id)
        if provider_pk is None or provider_pk <= 0:
            return Result.fail("Cloud provider hesabı seçilmedi.", close_dialog=False)

        with Session(_engine(db_name)) as session:
            record = session.get(AiProviderAccount, provider_pk)
            if record is None:
                return Result.fail("Cloud provider hesabı bulunamadı.", close_dialog=False)
            if _ensure_provider_credential_ref(record):
                session.add(record)
                session.commit()
                session.refresh(record)

        settings_res = load_ai_settings(settings_path=settings_path)
        settings = dict((settings_res.data or {}).get("settings") or {}) if settings_res.success else {}
        payload = _enrich_provider_runtime_config(
            _provider_record_to_dict(record, include_secret=True),
            settings,
        )
        return Result.ok(
            "Cloud provider hesabı yüklendi.",
            close_dialog=False,
            data={"record": payload},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def save_provider_account(
    *,
    provider_code: str,
    label: str,
    api_key: str,
    provider_id: int | None = None,
    endpoint_url: str | None = None,
    default_model: str | None = None,
    is_enabled: bool = True,
    db_name: str = DB_NAME,
) -> Result:
    new_credential_ref = ""
    previous_credential_ref = ""
    credential_committed = False
    try:
        clean_provider_code = _compact_text(provider_code).lower()
        clean_label = _compact_text(label)
        clean_api_key = _compact_text(api_key)
        clean_endpoint = _compact_text(endpoint_url)
        clean_model = _compact_text(default_model)
        provider_pk = _optional_int(provider_id)

        if not clean_provider_code:
            return Result.fail("Provider secimi zorunludur.", close_dialog=False)
        if not clean_label:
            return Result.fail("Hesap etiketi zorunludur.", close_dialog=False)
        if not clean_api_key:
            return Result.fail("API key zorunludur.", close_dialog=False)

        now = _utcnow_naive()
        with Session(_engine(db_name)) as session:
            record: AiProviderAccount | None = None
            if provider_pk is not None and provider_pk > 0:
                record = session.get(AiProviderAccount, provider_pk)
                if record is None:
                    return Result.fail("Duzenlenecek cloud hesabi bulunamadi.", close_dialog=False)
                previous_credential_ref = (
                    str(record.api_key or "").strip()
                    if is_credential_reference(record.api_key)
                    else ""
                )

            new_credential_ref = store_secret(
                f"ai-provider-{clean_provider_code}",
                clean_api_key,
            )

            if record is None:
                record = AiProviderAccount(
                    provider_code=clean_provider_code,
                    label=clean_label,
                    endpoint_url=clean_endpoint or None,
                    api_key=new_credential_ref,
                    default_model=clean_model or None,
                    is_enabled=bool(is_enabled),
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.provider_code = clean_provider_code
                record.label = clean_label
                record.endpoint_url = clean_endpoint or None
                record.api_key = new_credential_ref
                record.default_model = clean_model or None
                record.is_enabled = bool(is_enabled)
                record.updated_at = now

            session.commit()
            session.refresh(record)
            credential_committed = True

        if previous_credential_ref and previous_credential_ref != new_credential_ref:
            try:
                delete_secret(previous_credential_ref)
            except Exception:
                pass

        return Result.ok(
            "Cloud provider hesabi kaydedildi.",
            close_dialog=False,
            data={"record": _provider_record_to_dict(record)},
        )
    except Exception as exc:
        if new_credential_ref and not credential_committed:
            try:
                delete_secret(new_credential_ref)
            except Exception:
                pass
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def delete_provider_accounts(provider_ids: list[int] | tuple[int, ...], *, db_name: str = DB_NAME) -> Result:
    try:
        cleaned_ids = sorted({
            provider_id
            for provider_id in (_optional_int(value) for value in list(provider_ids or []))
            if provider_id is not None and provider_id > 0
        })
        if not cleaned_ids:
            return Result.fail("Silmek icin en az bir cloud hesabi secin.", close_dialog=False)

        deleted_count = 0
        credential_refs: list[str] = []
        with Session(_engine(db_name)) as session:
            for provider_id in cleaned_ids:
                record = session.get(AiProviderAccount, provider_id)
                if record is None:
                    continue
                if is_credential_reference(record.api_key):
                    credential_refs.append(str(record.api_key))
                session.delete(record)
                deleted_count += 1
            session.commit()
        for credential_ref in credential_refs:
            delete_secret(credential_ref)

        return Result.ok(
            "Cloud provider hesaplari silindi." if deleted_count > 1 else "Cloud provider hesabi silindi.",
            close_dialog=False,
            data={"deleted_count": deleted_count},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def download_hf_model_file(
    *,
    repo_id: str,
    filename: str,
    download_root: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    pause_requested: Callable[[], bool] | None = None,
    settings_path: str | Path | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        clean_repo_id = _compact_text(repo_id)
        clean_filename = _compact_text(filename)
        if not clean_repo_id or not clean_filename:
            return Result.fail("Model repo id ve dosya adi zorunludur.", close_dialog=False)

        if download_root in (None, ""):
            settings_res = load_ai_settings(settings_path=settings_path)
            if not settings_res.success:
                return settings_res
            resolved_root = _normalize_dir((settings_res.data.get("settings") or {}).get("download_root"))
        else:
            resolved_root = _normalize_dir(download_root)

        target_dir = resolved_root / _safe_repo_dir(clean_repo_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / Path(clean_filename).name
        download_url = build_model_download_url(clean_repo_id, clean_filename)

        if target_path.exists() and target_path.is_file():
            record = _upsert_installed_model(
                repo_id=clean_repo_id,
                filename=clean_filename,
                local_path=str(target_path),
                download_root=str(resolved_root),
                file_format=_guess_format(clean_filename),
                quantization=_guess_quantization(clean_filename),
                size_bytes=target_path.stat().st_size,
                source_url=download_url,
                db_name=db_name,
            )
            return Result.ok(
                "Model dosyasi zaten mevcut.",
                close_dialog=False,
                data={"record": record, "already_exists": True},
            )

        temp_name = f"{Path(clean_filename).name}.part"
        temp_path = target_dir / temp_name
        resume_from = temp_path.stat().st_size if temp_path.exists() and temp_path.is_file() else 0
        headers = {"Range": f"bytes={resume_from}-"} if resume_from > 0 else None

        with requests.get(download_url, stream=True, timeout=(20, 120), headers=headers) as response:
            response.raise_for_status()
            if resume_from > 0 and response.status_code != 206:
                resume_from = 0
            content_length = _optional_int(response.headers.get("Content-Length")) or 0
            total_bytes = content_length + resume_from if resume_from > 0 else content_length
            if total_bytes > 0:
                free_bytes = int(shutil.disk_usage(str(target_dir)).free)
                needed_bytes = max(0, total_bytes - resume_from)
                if free_bytes < needed_bytes + 2 * 1024 * 1024 * 1024:
                    return Result.fail("Model icin yeterli bos disk alani yok.", close_dialog=False)
            etag = _compact_text(response.headers.get("ETag")) or None
            bytes_written = resume_from

            with open(temp_path, "ab" if resume_from > 0 else "wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if pause_requested is not None and pause_requested():
                        return Result.ok(
                            "İndirme duraklatıldı; kısmi dosya korunuyor.",
                            close_dialog=False,
                            data={
                                "paused": True,
                                "partial_path": str(temp_path),
                                "bytes_written": bytes_written,
                                "total_bytes": total_bytes,
                            },
                        )
                    if not chunk:
                        continue
                    fh.write(chunk)
                    bytes_written += len(chunk)
                    if progress_callback is not None:
                        progress_callback(bytes_written, total_bytes, f"{clean_repo_id} indiriliyor...")

        os.replace(temp_path, target_path)

        record = _upsert_installed_model(
            repo_id=clean_repo_id,
            filename=clean_filename,
            local_path=str(target_path),
            download_root=str(resolved_root),
            file_format=_guess_format(clean_filename),
            quantization=_guess_quantization(clean_filename),
            size_bytes=target_path.stat().st_size,
            source_url=download_url,
            etag=etag,
            db_name=db_name,
        )

        return Result.ok(
            "Model dosyasi basariyla indirildi.",
            close_dialog=False,
            data={"record": record, "already_exists": False},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def delete_installed_model(
    model_id: int,
    *,
    settings_path: str | Path | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        clean_id = _optional_int(model_id)
        if clean_id is None or clean_id <= 0:
            return Result.fail("Silmek için geçerli bir yerel model seçin.", close_dialog=False)

        with Session(_engine(db_name)) as session:
            record = session.get(AiModelArtifact, clean_id)
            if record is None:
                return Result.fail("Yerel model kaydı bulunamadı.", close_dialog=False)
            payload = _record_to_dict(record)
            local_path = Path(str(record.local_path or "")).expanduser()
            download_root = Path(str(record.download_root or "")).expanduser()
            if local_path.exists():
                resolved_path = local_path.resolve()
                resolved_root = download_root.resolve()
                try:
                    resolved_path.relative_to(resolved_root)
                except ValueError:
                    return Result.fail(
                        "Güvenlik sınırı: indirme kökü dışındaki model dosyası silinmedi.",
                        close_dialog=False,
                    )
                if not resolved_path.is_file():
                    return Result.fail("Yerel model yolu normal bir dosya değil.", close_dialog=False)
                resolved_path.unlink()
            session.delete(record)
            session.commit()

        path = Path(settings_path) if settings_path not in (None, "") else AI_CONFIG_FILE
        if path.exists():
            settings = _normalize_settings_payload({**_default_settings(), **_read_json(path, default={})})
            store = _runtime_config_store(settings)
            store.pop(_model_config_key(payload), None)
            settings["model_runtime_configs"] = store
            _write_json(path, settings)

        return Result.ok(
            "Yerel model dosyası ve kaydı silindi.",
            close_dialog=False,
            data={"deleted_model_id": clean_id, "record": payload},
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
