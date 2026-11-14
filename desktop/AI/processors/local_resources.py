from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


GIB = 1024 ** 3


@dataclass(frozen=True)
class ResourceSnapshot:
    total_ram_bytes: int
    available_ram_bytes: int
    cpu_count: int
    gpu_names: tuple[str, ...] = ()
    gpu_total_vram_bytes: int = 0
    gpu_free_vram_bytes: int = 0
    disk_free_bytes: int = 0
    virtual_available_bytes: int = 0
    swap_free_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["gpu_names"] = list(self.gpu_names)
        return payload


@dataclass(frozen=True)
class LocalModelResourcePlan:
    profile: str
    safe_to_run: bool
    reason: str
    model_hint: str
    estimated_model_bytes: int
    ram_budget_bytes: int
    gpu_budget_bytes: int
    num_ctx: int
    max_tokens: int
    num_thread: int
    num_batch: int
    num_gpu: int
    keep_alive: str
    reasoning_effort: str = "medium"
    runtime_strategy: str = "llama_cpp"
    use_mmap: bool = True
    use_mlock: bool = False
    offload_strategy: str = "auto"
    disk_budget_bytes: int = 0
    performance_score: float = 0.0
    memory_pressure: float = 0.0
    allow_unsafe: bool = False
    os_reserve_bytes: int = 0
    available_after_reserve_bytes: int = 0
    process_priority: str = "normal"
    trim_working_set: bool = False
    startup_timeout_seconds: int = 45
    estimated_runtime_bytes: int = 0
    estimated_kv_bytes: int = 0
    estimated_resident_bytes: int = 0
    virtual_available_bytes: int = 0
    requires_paging: bool = False
    suitability: str = "unknown"
    capacity_label: str = "Boyut bilinmiyor"
    warnings: tuple[str, ...] = ()
    context_policy: str = "preserve_grow_or_error"
    tool_menu_limit: int = 6
    model_layers: int = 0
    architecture: str = ""
    cache_type_k: str = "q8_0"
    cache_type_v: str = "q8_0"
    num_ubatch: int = 32
    inference_timeout_seconds: int = 3600
    sampling_defaults: dict[str, Any] = field(default_factory=dict)

    def to_openai_request_options(self) -> dict[str, Any]:
        return {
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
        }

    def to_llama_cpp_args(self) -> list[str]:
        args = [
            "-n",
            str(self.max_tokens),
            "-c",
            str(self.num_ctx),
            "-t",
            str(self.num_thread),
            "--temp",
            "0",
        ]
        args.extend(["-ngl", str(self.num_gpu)])
        args.append("--mmap" if self.use_mmap else "--no-mmap")
        return args

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _optional_bool(value: Any, default: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _compact_text(value).casefold()
    if text in {"1", "true", "yes", "evet", "on"}:
        return True
    if text in {"0", "false", "no", "hayir", "off"}:
        return False
    return default


def _record_text(record: dict[str, Any] | None, *extra: str) -> str:
    values: list[str] = list(extra)
    if isinstance(record, dict):
        for key in (
            "repo_id",
            "filename",
            "display_name",
            "local_path",
            "model_path",
            "openai_model",
        ):
            values.append(_compact_text(record.get(key)))
    return " ".join(value for value in values if value).casefold()


def _runtime_config(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    config = record.get("runtime_config")
    return dict(config) if isinstance(config, dict) else {}


def _parse_nvidia_smi() -> tuple[tuple[str, ...], int, int]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except Exception:
        return (), 0, 0
    if result.returncode != 0:
        return (), 0, 0

    names: list[str] = []
    total_mb = 0
    free_mb = 0
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        names.append(parts[0])
        total_mb += _optional_int(parts[1]) or 0
        free_mb += _optional_int(parts[2]) or 0
    return tuple(names), total_mb * 1024 * 1024, free_mb * 1024 * 1024


def _windows_memory_status():
    if os.name != "nt":
        return None
    try:
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ("total_physical", "available_physical", "total_commit",
                    "available_commit", "total_virtual", "available_virtual", "extended")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        return status if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
    except Exception:
        return None


def capture_resource_snapshot(disk_path: str | Path | None = None) -> ResourceSnapshot:
    total_ram = 0
    available_ram = 0
    virtual_available = 0
    swap_free = 0
    try:
        import psutil  # type: ignore

        memory = psutil.virtual_memory()
        total_ram = int(memory.total)
        available_ram = int(memory.available)
        swap_free = int(psutil.swap_memory().free)
        virtual_available = available_ram + swap_free
    except Exception:
        pass

    if os.name == "nt":
        status = _windows_memory_status()
        if status is not None:
            total_ram, available_ram = status.total_physical, status.available_physical
            virtual_available = status.available_commit
    gpu_names, gpu_total, gpu_free = _parse_nvidia_smi()
    disk_free = 0
    try:
        target = Path(disk_path or os.environ.get("ORDERSCOUT_MODELS_DIR") or os.getcwd())
        while not target.exists() and target.parent != target:
            target = target.parent
        disk_free = int(shutil.disk_usage(str(target)).free)
    except Exception:
        disk_free = 0
    return ResourceSnapshot(
        total_ram_bytes=total_ram,
        available_ram_bytes=available_ram,
        cpu_count=max(1, int(os.cpu_count() or 1)),
        gpu_names=gpu_names,
        gpu_total_vram_bytes=gpu_total,
        gpu_free_vram_bytes=gpu_free,
        disk_free_bytes=disk_free,
        virtual_available_bytes=virtual_available,
        swap_free_bytes=swap_free,
    )


def estimate_model_bytes(record: dict[str, Any] | None = None, *, model_hint: str = "") -> int:
    if isinstance(record, dict):
        for key in ("local_path", "model_path", "gguf_path"):
            path_text = _compact_text(record.get(key))
            if not path_text:
                continue
            try:
                path = Path(path_text)
                if path.is_file():
                    return int(path.stat().st_size)
            except Exception:
                pass
        size_bytes = _optional_int(record.get("size_bytes"))
        if size_bytes and size_bytes > 0:
            return size_bytes

    haystack = _record_text(record, model_hint)
    if "gpt-oss:20b" in haystack or "gpt-oss-20b" in haystack:
        return int(13 * GIB)
    if "gpt-oss:120b" in haystack or "gpt-oss-120b" in haystack:
        return int(70 * GIB)

    match = re.search(r"(\d+(?:\.\d+)?)\s*b\b", haystack)
    if not match:
        return 0

    params_b = float(match.group(1))
    quant = "q4"
    if any(token in haystack for token in ("fp16", "bf16")):
        bytes_per_param = 2.05
    elif "q8" in haystack or "int8" in haystack:
        bytes_per_param = 1.1
    elif "q6" in haystack:
        bytes_per_param = 0.95
    elif "q5" in haystack:
        bytes_per_param = 0.82
    elif "q3" in haystack:
        bytes_per_param = 0.55
    elif "q2" in haystack:
        bytes_per_param = 0.42
    else:
        bytes_per_param = 0.7 if quant == "q4" else 0.75
    return int(params_b * 1_000_000_000 * bytes_per_param + 1.2 * GIB)


def _env_int(name: str) -> int | None:
    value = _optional_int(os.environ.get(name))
    return value if value is not None and value >= 0 else None


def local_model_sort_key(record):
    """Prefer fitting candidates over tiny alphabetical defaults.

    This is a capacity ordering, not a benchmark or model-quality certificate.
    Large paging candidates remain selectable directly below resident models.
    """
    plan = record.get("resource_plan") or {}
    return (not bool(plan.get("safe_to_run", False)), bool(plan.get("requires_paging", False)),
            -int(record.get("size_bytes") or plan.get("estimated_model_bytes") or 0),
            str(record.get("repo_id") or "").casefold())


def local_sampling_defaults(record=None, *, architecture="", thinking=False):
    if architecture == "qwen35" or "qwen3.5" in _record_text(record):
        # Qwen's published non-thinking/thinking general-task recommendations.
        return {"temperature": 1.0 if thinking else 0.7, "top_p": 0.95 if thinking else 0.8,
                "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5, "repeat_penalty": 1.0}
    return {"temperature": 0.2}


def _model_metadata(record):
    from AI.processors.gguf_metadata import read_gguf_metadata
    for key in ("local_path", "model_path", "gguf_path"):
        candidate = _compact_text((record or {}).get(key))
        if candidate and Path(candidate).is_file():
            try:
                return read_gguf_metadata(candidate), ""
            except (OSError, ValueError) as error:
                return {}, str(error)
    return {}, ""


def build_local_resource_plan(
    record: dict[str, Any] | None = None,
    *,
    model_hint: str = "",
    snapshot: ResourceSnapshot | None = None,
    requested_ctx: int | None = None,
) -> LocalModelResourcePlan:
    """Plan a single runner, keeping context useful and OS allocations bounded.

    Read-only mmap weights can be paged from their model file. Free disk is NOT
    memory or commit capacity. KV/scratch allocations still need real headroom.
    These are estimates; runner allocation failures are handled at startup.
    """
    record = dict(record or {})
    snap = snapshot or capture_resource_snapshot(record.get("local_path") or record.get("download_root"))
    config = _runtime_config(record)
    metadata, invalid_model = _model_metadata(record)
    architecture = str(metadata.get("general.architecture") or "")
    layers = int(metadata.get(architecture + ".block_count") or 32)
    total = max(0, int(snap.total_ram_bytes))
    available = max(0, int(snap.available_ram_bytes))
    reserve = max(int(1.5 * GIB), int(total * 0.12))
    ram_budget = max(0, available - reserve)
    # Leave display/desktop and compute workspace on the GPU, even on laptops.
    gpu_budget = max(0, int(snap.gpu_free_vram_bytes) - max(512 * 1024**2, int(snap.gpu_total_vram_bytes * 0.12)))
    virtual = int(snap.virtual_available_bytes or (available + snap.swap_free_bytes))
    estimated = estimate_model_bytes(record, model_hint=model_hint)
    preset = _compact_text(config.get("performance_preset") or "auto").casefold()
    reasoning_model = any(token in _record_text(record, model_hint) for token in ("qwen3", "gpt-oss", "gemma-4", "gemma4", "deepseek-r1"))
    effort = _compact_text(config.get("reasoning_effort") or "auto").casefold()
    if effort == "auto":
        effort = "low" if preset in {"eco", "fast"} or not reasoning_model else "medium"
    if effort not in {"low", "medium", "high"}:
        effort = "medium" if reasoning_model else "low"
    thinking = effort in {"medium", "high"}
    ctx = 4096 if preset in {"eco", "fast"} else 8192 if preset == "balanced" else 16384 if thinking or preset == "quality" else 12288
    output = 1024 if preset in {"eco", "fast"} else 2048 if preset == "balanced" else 4096 if thinking or preset == "quality" else 2048
    ctx = int(_env_int("ORDERSCOUT_LOCAL_NUM_CTX") or requested_ctx or config.get("num_ctx") or ctx)
    ctx = max(2048, min(ctx, 32768))
    trained = int(metadata.get(architecture + ".context_length") or 32768)
    ctx = min(ctx, trained)
    output = max(128, min(int(_env_int("ORDERSCOUT_LOCAL_MAX_TOKENS") or config.get("max_tokens") or output), ctx // 2, 8192))
    warnings = []
    # q8 cache avoids the very large f16 allocation; architecture metadata wins
    # over model-name guesses. Some hybrid models use additional recurrent state.
    heads = int(metadata.get(architecture + ".attention.head_count") or 32)
    kv_heads = int(metadata.get(architecture + ".attention.head_count_kv") or 4)
    dim = int(metadata.get(architecture + ".embedding_length") or 4096)
    key_dim = int(metadata.get(architecture + ".attention.key_length") or max(64, dim // max(1, heads)))
    value_dim = int(metadata.get(architecture + ".attention.value_length") or key_dim)
    kv_bytes = int(ctx * layers * kv_heads * (key_dim + value_dim) * 1.063)
    # Hybrid attention/recurrent state estimation is deliberately conservative.
    if architecture in {"qwen35", "qwen3next"}:
        kv_bytes = max(kv_bytes // 4, 256 * 1024**2)
    scratch = max(512 * 1024**2, min(GIB, int(estimated * 0.08)))
    # Keep some VRAM for KV and graph buffers, then offload as many whole layers
    # as fit. Never count integrated/shared graphics as additional physical RAM.
    per_layer = max(1, estimated // max(1, layers))
    gpu_weight_budget = max(0, gpu_budget - min(kv_bytes, 512 * 1024**2) - 384 * 1024**2)
    auto_gpu = min(layers, gpu_weight_budget // per_layer) if estimated else 0
    explicit_gpu = _env_int("ORDERSCOUT_LLAMA_CPP_NUM_GPU")
    if explicit_gpu is None and config.get("num_gpu") is not None:
        explicit_gpu = _optional_int(config.get("num_gpu"))
    num_gpu = auto_gpu if explicit_gpu is None else min(auto_gpu, max(0, explicit_gpu))
    cpu_weights = max(0, estimated - num_gpu * per_layer)
    cpu_kv = int(kv_bytes * max(0, layers - num_gpu) / max(1, layers))
    resident = cpu_weights + cpu_kv + scratch
    mmap = _optional_bool(config.get("use_mmap"), True) is not False
    paging = bool(estimated and resident > ram_budget)
    # File-backed weights do not all need to be resident, but kernels, scratch
    # and an actual working set do. Do not lock pages for a paging workload.
    working_set = cpu_kv + scratch + min(cpu_weights, int(1.25 * GIB))
    allocation = cpu_kv + scratch + (cpu_weights if not mmap else 0)
    safe = bool(total and available and working_set <= ram_budget and allocation + reserve <= virtual)
    if not paging:
        safe = bool(total and resident <= ram_budget and allocation + reserve <= virtual)
    if not estimated:
        safe = False
        warnings.append("Dosya boyutu bilinmiyor; indirme tamamlandığında yeniden değerlendirilir.")
    auxiliary = any(token in architecture.casefold() for token in ("mtp", "support", "clip", "projector")) or int(metadata.get("split.count") or 1) > 1
    if invalid_model or auxiliary:
        safe = False
        reason = invalid_model or "Bu dosya tek başına bir sohbet modeli değil; yardımcı veya bölünmüş model dosyası."
        label, suitability, profile = "Sohbet modeli değil" if auxiliary else "Dosya okunamadı", "blocked", "blocked_invalid_model"
    elif not estimated:
        reason, label, suitability, profile = "Model boyutu doğrulanmalı.", "Boyut bilinmiyor", "unknown", "unknown_model_safe_defaults"
    elif not safe:
        reason = "Modelin çalışma belleği için yeterli boş RAM veya Windows ayırma kapasitesi yok. Bellek boşaltıp yeniden deneyin."
        label, suitability, profile = "Şu an bellek yetersiz", "blocked", "blocked_insufficient_memory"
    elif paging:
        reason = "Ağırlıkların bir bölümü model dosyasından okunacak; CPU ve GPU birlikte çalışır. Yanıt belirgin şekilde yavaşlayabilir."
        label, suitability, profile = "Disk desteğiyle · yavaş", "slow", "disk_guarded_large_model"
        warnings.append("Disk model ağırlıklarını taşır; RAM ve ekran kartı belleğinin yerini tamamen alamaz.")
    else:
        reason = "Model CPU ve GPU arasında paylaştırılabilir; uygulama ve işletim sistemi için bellek payı ayrıldı."
        label, suitability, profile = "Bu bilgisayara uygun", "recommended", "balanced_local_model"
    if config.get("use_mlock") and paging:
        warnings.append("Disk desteği gerektiği için RAM kilidi uygulanmadı.")
    default_threads = min(4, max(1, snap.cpu_count // 2)) if preset == "eco" else max(1, snap.cpu_count // 2)
    threads = max(1, min(int(_env_int("ORDERSCOUT_LOCAL_NUM_THREAD") or config.get("num_thread") or default_threads), snap.cpu_count))
    batch = max(16, min(int(_env_int("ORDERSCOUT_LOCAL_NUM_BATCH") or config.get("num_batch") or (64 if preset == "eco" else 128)), 256))
    return LocalModelResourcePlan(
        profile=profile, safe_to_run=safe, reason=reason, model_hint=model_hint or _record_text(record),
        estimated_model_bytes=estimated, ram_budget_bytes=ram_budget, gpu_budget_bytes=gpu_budget,
        num_ctx=ctx, max_tokens=output, num_thread=threads, num_batch=batch, num_gpu=num_gpu,
        keep_alive=_compact_text(config.get("keep_alive") or "5m"), reasoning_effort=effort,
        use_mmap=mmap, use_mlock=bool(_optional_bool(config.get("use_mlock"), False) and not paging),
        offload_strategy="disk_mmap_gpu_cpu" if mmap and num_gpu else "disk_mmap_cpu" if mmap else "ram_resident",
        disk_budget_bytes=0, memory_pressure=round(resident / max(1, ram_budget), 2),
        allow_unsafe=False, os_reserve_bytes=reserve, available_after_reserve_bytes=ram_budget,
        process_priority="below_normal", trim_working_set=False, startup_timeout_seconds=1800,
        estimated_runtime_bytes=estimated + kv_bytes + scratch, estimated_kv_bytes=kv_bytes,
        estimated_resident_bytes=resident, virtual_available_bytes=virtual, requires_paging=paging,
        suitability=suitability, capacity_label=label, warnings=tuple(warnings), model_layers=layers,
        architecture=architecture, num_ubatch=min(batch, 32), tool_menu_limit=6,
        inference_timeout_seconds=max(600, min(int(config.get("timeout_seconds") or 3600), 86400)),
        sampling_defaults=local_sampling_defaults(record, architecture=architecture, thinking=effort in {"medium", "high"}),
    )
