from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
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
        if self.num_gpu > 0:
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


def capture_resource_snapshot() -> ResourceSnapshot:
    total_ram = 0
    available_ram = 0
    try:
        import psutil  # type: ignore

        memory = psutil.virtual_memory()
        total_ram = int(memory.total)
        available_ram = int(memory.available)
    except Exception:
        pass

    gpu_names, gpu_total, gpu_free = _parse_nvidia_smi()
    disk_free = 0
    try:
        target = os.environ.get("ORDERSCOUT_MODELS_DIR") or os.getcwd()
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
    )


def estimate_model_bytes(record: dict[str, Any] | None = None, *, model_hint: str = "") -> int:
    if isinstance(record, dict):
        size_bytes = _optional_int(record.get("size_bytes"))
        if size_bytes and size_bytes > 0:
            return size_bytes
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


def build_local_resource_plan(
    record: dict[str, Any] | None = None,
    *,
    model_hint: str = "",
    snapshot: ResourceSnapshot | None = None,
    requested_ctx: int | None = None,
) -> LocalModelResourcePlan:
    snap = snapshot or capture_resource_snapshot()
    config = _runtime_config(record)
    estimated = estimate_model_bytes(record, model_hint=model_hint)
    total_ram = max(0, int(snap.total_ram_bytes or 0))
    available_ram = max(0, int(snap.available_ram_bytes or 0))
    allow_unsafe = bool(_optional_bool(config.get("allow_unsafe"), False))
    if total_ram and total_ram <= 24 * GIB:
        reserve = max(4 * GIB, int(total_ram * 0.30))
    elif total_ram:
        reserve = max(6 * GIB, int(total_ram * 0.22))
    else:
        reserve = 4 * GIB
    ram_budget = max(0, available_ram - reserve)
    gpu_budget = max(0, int((snap.gpu_free_vram_bytes or 0) * 0.85))
    disk_free = max(0, int(snap.disk_free_bytes or 0))
    disk_budget = max(0, min(int(disk_free * 0.35), 64 * GIB))
    cpu_threads = max(2, min(6, int(snap.cpu_count or 1) // 3 or 1))

    primary_runtime_budget = ram_budget + gpu_budget
    total_capacity = primary_runtime_budget + min(disk_budget, 12 * GIB)
    is_large = estimated >= 10 * GIB
    tight_available = bool(estimated and primary_runtime_budget < int(estimated * 0.85))
    hard_reserve = max(2 * GIB, int(total_ram * 0.12)) if total_ram else 2 * GIB
    os_guard_ok = available_ram >= reserve if total_ram else True
    disk_fallback_ok = bool(
        estimated
        and available_ram >= hard_reserve
        and disk_budget >= min(estimated, 2 * GIB)
        and total_capacity >= estimated
    )
    survival_mmap_ok = bool(
        is_large
        and total_ram >= 15 * GIB
        and available_ram >= int(3.25 * GIB)
        and disk_free >= estimated + 8 * GIB
        and disk_budget >= min(estimated, 8 * GIB)
    )
    safe = not estimated or ((os_guard_ok and total_capacity >= estimated + GIB) or disk_fallback_ok)
    large_disk_only_risk = bool(is_large and total_ram < 24 * GIB and primary_runtime_budget < int(estimated * 0.95))
    if survival_mmap_ok:
        safe = True
    elif large_disk_only_risk and not allow_unsafe:
        safe = False
    performance_score = round(
        min(100.0, ((total_ram / GIB) * 2.2) + ((snap.gpu_free_vram_bytes / GIB) * 5.0) + (snap.cpu_count * 2.4)),
        1,
    )
    memory_denominator = max(1, primary_runtime_budget + min(disk_budget, 12 * GIB))
    memory_pressure = round(float(estimated / memory_denominator), 2) if estimated else 0.0
    os_pressure = bool(safe and not os_guard_ok)
    disk_guarded = bool(is_large and safe and (tight_available or memory_pressure >= 0.70 or os_pressure))
    process_priority = "below_normal" if estimated else "normal"
    if os_pressure:
        process_priority = "idle"
    startup_timeout_seconds = 45

    if not estimated:
        profile = "unknown_model_safe_defaults"
        reason = "Model boyutu bilinmiyor; guvenli varsayilan limitler uygulanacak."
        num_ctx = 1536
        max_tokens = 384
        num_batch = 48
        cpu_threads = max(1, min(cpu_threads, 4))
        keep_alive = "0s"
    elif not safe:
        profile = "blocked_insufficient_memory"
        reason = "Model OS koruma rezervini veya guvenli bellek butcesini asiyor; app model baslatmayi engellemeli."
        num_ctx = 512
        max_tokens = 128
        num_batch = 8
        keep_alive = "0s"
        process_priority = "idle"
    elif disk_guarded:
        if survival_mmap_ok and not os_guard_ok:
            profile = "survival_mmap_large_model"
            reason = "Buyuk model sinirli RAM ile mmap agirlikli survival modda calisacak; hiz dusuk, uygulama onceligi korunur."
        else:
            profile = "disk_guarded_large_model"
            reason = "Buyuk model OS rezervini korumak icin mmap/disk agirlikli ve dusuk concurrency ile calisacak."
        num_ctx = 512
        max_tokens = 160 if survival_mmap_ok and not os_guard_ok else 192
        num_batch = 4 if survival_mmap_ok and not os_guard_ok else 8
        cpu_threads = max(1, min(cpu_threads, 2))
        keep_alive = "0s"
        startup_timeout_seconds = 240 if survival_mmap_ok else 180
    elif os_pressure:
        profile = "os_guarded_low_memory"
        reason = "Bos RAM OS rezervinin altinda; model idle priority ve disk mmap ile yavas ama guvenli calisacak."
        num_ctx = 768
        max_tokens = 192
        num_batch = 16
        cpu_threads = max(1, min(cpu_threads, 3))
        keep_alive = "0s"
    elif is_large and tight_available:
        profile = "tight_large_model"
        reason = "Buyuk model dusuk bos bellekle calisacak; kisa context ve tek tur cevap limiti uygulanacak."
        num_ctx = 1024
        max_tokens = 192
        num_batch = 32
        keep_alive = "0s"
        startup_timeout_seconds = 150
    elif is_large:
        profile = "balanced_large_model"
        reason = "Buyuk model icin dengeli CPU/GPU kaynak plani uygulanacak."
        num_ctx = 2048
        max_tokens = 384
        num_batch = 64
        keep_alive = "0s"
        startup_timeout_seconds = 120
    else:
        profile = "balanced_local_model"
        reason = "Model boyutu bu makine icin uygun; OS korumali yerel sohbet limitleri uygulanacak."
        num_ctx = 4096
        max_tokens = 512
        num_batch = 64
        cpu_threads = max(1, min(cpu_threads, 4))
        keep_alive = "0s"

    preset = _compact_text(config.get("performance_preset")).casefold()
    if preset == "eco":
        num_ctx = min(num_ctx, 1024)
        max_tokens = min(max_tokens, 192)
        num_batch = min(num_batch, 32)
        cpu_threads = max(1, min(cpu_threads, 4))
        keep_alive = "0s"
    elif preset == "fast":
        if safe and memory_pressure <= 0.55 and not disk_guarded:
            num_ctx = min(4096, max(num_ctx, 2048))
            max_tokens = min(768, max(max_tokens, 512))
            num_batch = min(160, max(num_batch, 96))
            cpu_threads = min(max(1, snap.cpu_count or 1), max(cpu_threads, 8))
    elif preset == "balanced":
        if not disk_guarded:
            num_ctx = min(3072, max(num_ctx, 2048))
            max_tokens = min(512, max(max_tokens, 384))

    if requested_ctx:
        num_ctx = max(512, min(int(requested_ctx), num_ctx))
    env_ctx = _env_int("ORDERSCOUT_LOCAL_NUM_CTX")
    env_tokens = _env_int("ORDERSCOUT_LOCAL_MAX_TOKENS")
    env_threads = _env_int("ORDERSCOUT_LOCAL_NUM_THREAD")
    env_batch = _env_int("ORDERSCOUT_LOCAL_NUM_BATCH")
    env_gpu = _env_int("ORDERSCOUT_LLAMA_CPP_NUM_GPU")
    config_ctx = _optional_int(config.get("num_ctx"))
    config_tokens = _optional_int(config.get("max_tokens"))
    config_threads = _optional_int(config.get("num_thread"))
    config_batch = _optional_int(config.get("num_batch"))
    config_gpu = _optional_int(config.get("num_gpu"))
    if config_ctx:
        num_ctx = max(512, min(config_ctx, 8192))
    if config_tokens:
        max_tokens = max(64, min(config_tokens, 2048))
    if config_threads:
        cpu_threads = max(1, min(config_threads, max(1, snap.cpu_count or 1)))
    if config_batch:
        num_batch = max(8, min(config_batch, 512))
    if env_ctx:
        num_ctx = max(512, min(env_ctx, 8192))
    if env_tokens:
        max_tokens = max(64, min(env_tokens, 2048))
    if env_threads:
        cpu_threads = max(1, min(env_threads, max(1, snap.cpu_count or 1)))
    if env_batch:
        num_batch = max(8, min(env_batch, 512))

    if env_gpu is not None:
        num_gpu = env_gpu
    elif config_gpu is not None:
        num_gpu = max(0, min(config_gpu, 99))
    elif gpu_budget >= int(8 * GIB):
        num_gpu = 24 if is_large else 12
    elif gpu_budget >= int(3 * GIB):
        num_gpu = 8 if is_large else 6
    elif gpu_budget >= int(1.5 * GIB):
        num_gpu = 4 if is_large else 2
    else:
        num_gpu = 0

    default_reasoning_effort = "low" if (disk_guarded or os_pressure) else "medium"
    reasoning_effort = _compact_text(config.get("reasoning_effort")).casefold() or default_reasoning_effort
    if reasoning_effort not in {"auto", "low", "medium", "high"}:
        reasoning_effort = "medium"
    if reasoning_effort == "auto":
        reasoning_effort = "low" if is_large and memory_pressure >= 1.0 else "medium"
    reasoning_model = any(
        token in _record_text(record, model_hint)
        for token in ("gpt-oss", "deepseek-r1", "reasoning", "qwen-r1")
    )
    if reasoning_model:
        min_reasoning_tokens = {"low": 256, "medium": 384, "high": 640}.get(reasoning_effort, 384)
        max_tokens = max(max_tokens, min_reasoning_tokens)
    if not allow_unsafe and (disk_guarded or os_pressure or profile == "blocked_insufficient_memory"):
        num_ctx = min(num_ctx, 512 if disk_guarded else 1024 if os_pressure else 512)
        num_batch = min(num_batch, 4 if profile == "survival_mmap_large_model" else 8 if disk_guarded else 24 if os_pressure else 8)
        cpu_threads = min(cpu_threads, 2 if disk_guarded else 3 if os_pressure else 2)
        if profile == "blocked_insufficient_memory":
            max_tokens = min(max_tokens, 256)
    runtime_strategy = "llama_cpp"
    use_mmap = _optional_bool(config.get("use_mmap"), True)
    use_mlock = _optional_bool(config.get("use_mlock"), False)
    if use_mmap is None:
        use_mmap = True
    if use_mlock is None:
        use_mlock = False
    keep_alive_override = _compact_text(config.get("keep_alive"))
    if keep_alive_override:
        keep_alive = keep_alive_override
    offload_strategy = "disk_mmap_gpu_cpu" if use_mmap and num_gpu > 0 else "disk_mmap_cpu" if use_mmap else "ram_resident"

    return LocalModelResourcePlan(
        profile=profile,
        safe_to_run=safe,
        reason=reason,
        model_hint=_compact_text(model_hint) or _record_text(record),
        estimated_model_bytes=estimated,
        ram_budget_bytes=ram_budget,
        gpu_budget_bytes=gpu_budget,
        num_ctx=num_ctx,
        max_tokens=max_tokens,
        num_thread=cpu_threads,
        num_batch=num_batch,
        num_gpu=num_gpu,
        keep_alive=keep_alive,
        reasoning_effort=reasoning_effort,
        runtime_strategy=runtime_strategy,
        use_mmap=bool(use_mmap),
        use_mlock=bool(use_mlock),
        offload_strategy=offload_strategy,
        disk_budget_bytes=disk_budget,
        performance_score=performance_score,
        memory_pressure=memory_pressure,
        allow_unsafe=allow_unsafe,
        os_reserve_bytes=reserve,
        available_after_reserve_bytes=ram_budget,
        process_priority=process_priority,
        trim_working_set=bool(disk_guarded or os_pressure or memory_pressure >= 0.55),
        startup_timeout_seconds=startup_timeout_seconds,
    )
