from __future__ import annotations

import json
import atexit
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from AI.constants.paths import AI_BUNDLED_RUNTIME_ROOT, AI_RUNTIME_ROOT
from AI.processors.local_resources import LocalModelResourcePlan, build_local_resource_plan
from AI.processors.local_transport import build_local_http_client, LocalContextExceeded
from AI.processors.provider_adapters import capability_profile_from_record


LocalPlannerClient = Callable[[str], str]

LLAMA_HOST = "127.0.0.1"
LLAMA_SERVER_ENV = "ORDERSCOUT_LLAMA_SERVER"
MODEL_PATH_ENV = "ORDERSCOUT_GGUF_MODEL_PATH"
DEFAULT_LOCAL_API_KEY = "orderscout-local"


def _local_capability_profile_payload(
    record: dict[str, Any] | None,
    *,
    model_path: str = "",
) -> dict[str, Any]:
    local_record = dict(record or {})
    local_record["provider_code"] = "local"
    local_record["default_model"] = _compact_text(
        local_record.get("default_model")
        or local_record.get("filename")
        or local_record.get("repo_id")
        or model_path
    )
    return capability_profile_from_record(
        local_record,
        reasoning=(
            dict(local_record.get("reasoning_capabilities") or {})
            if isinstance(local_record.get("reasoning_capabilities"), dict)
            else {}
        ),
        native_tool_runtime_enabled=False,
        structured_output_runtime_enabled=False,
    ).to_dict()


def _local_runtime_plan_payload(
    plan: LocalModelResourcePlan,
    record: dict[str, Any] | None,
    *,
    model_path: str,
) -> dict[str, Any]:
    payload = dict(plan.to_dict())
    capability_profile = _local_capability_profile_payload(
        record,
        model_path=model_path,
    )
    payload["provider_code"] = "local"
    payload["capability_profile"] = capability_profile
    payload["degradation_mode"] = capability_profile.get("degradation_mode")
    return payload


@dataclass
class _ManagedLlamaServer:
    key: str
    process: subprocess.Popen
    base_url: str
    model_path: str
    guard_stop_event: threading.Event | None = None
    log_path: str = ""
    plan: LocalModelResourcePlan | None = None
    request_key: str = ""


_SERVER_LOCK = threading.RLock()
_INFERENCE_LOCK = threading.RLock()
_SERVER_CACHE: dict[str, _ManagedLlamaServer] = {}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _compact_local_prompt(prompt: str, *, num_ctx: int, max_tokens: int):
    """Compatibility metadata only; the HTTP tokenizer owns actual limits."""
    text = str(prompt or "")
    return text, {"prompt_compacted": False, "prompt_input_chars": len(text),
        "prompt_output_chars": len(text), "prompt_compaction_strategy": "preserve_or_error",
        "num_ctx": num_ctx, "max_tokens": max_tokens}


def _record_value(record: dict[str, Any] | None, key: str) -> str:
    if not isinstance(record, dict):
        return ""
    return _compact_text(record.get(key))


def _request_json(url: str, payload: dict[str, Any] | None = None, *, timeout: float = 8.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body or "{}")
    return parsed if isinstance(parsed, dict) else {}


def _platform_runtime_dirs() -> list[Path]:
    roots = (AI_BUNDLED_RUNTIME_ROOT, AI_RUNTIME_ROOT)
    if os.name == "nt":
        variants = ("windows-x64-cuda", "windows-x64-vulkan", "windows-x64-cpu", "")
        return [root / "llama.cpp" / variant for root in roots for variant in variants]
    if sys.platform == "darwin":
        variants = ("macos-universal-metal", "macos-arm64-metal", "macos-x64-cpu", "")
        return [root / "llama.cpp" / variant for root in roots for variant in variants]
    variants = ("linux-x64-cuda", "linux-x64-vulkan", "linux-x64-cpu", "")
    return [root / "llama.cpp" / variant for root in roots for variant in variants]


def candidate_llama_server_paths() -> list[str]:
    explicit = _compact_text(os.environ.get(LLAMA_SERVER_ENV))
    candidates: list[Path] = [Path(explicit)] if explicit else []
    executable_names = ["llama-server.exe", "server.exe"] if os.name == "nt" else ["llama-server", "server"]
    for root in _platform_runtime_dirs():
        candidates.extend(root / name for name in executable_names)

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate)
        if text not in seen:
            out.append(text)
            seen.add(text)
    return out


def find_bundled_llama_server() -> str:
    for candidate in candidate_llama_server_paths():
        try:
            path = Path(candidate)
            if path.is_file():
                return str(path)
        except Exception:
            continue
    return ""


def _apply_runtime_process_priority(priority: str, *, process: subprocess.Popen | None = None) -> None:
    clean = str(priority or "").strip().casefold()
    if clean not in {"below_normal", "idle"}:
        return
    try:
        import psutil  # type: ignore
    except Exception:
        return

    priority_value = None
    if os.name == "nt":
        priority_value = getattr(
            psutil,
            "IDLE_PRIORITY_CLASS" if clean == "idle" else "BELOW_NORMAL_PRIORITY_CLASS",
            None,
        )
    if priority_value is None:
        priority_value = 10 if clean == "idle" else 5

    targets = []
    if process is not None and process.poll() is None:
        try:
            targets.append(psutil.Process(int(process.pid)))
        except Exception:
            pass
    for proc in targets:
        try:
            proc.nice(priority_value)
        except Exception:
            continue


def _start_memory_guard(plan: LocalModelResourcePlan, process: subprocess.Popen) -> tuple[threading.Event, threading.Thread] | None:
    stop_event = threading.Event()
    priority = str(getattr(plan, "process_priority", "normal") or "normal")

    def _guard() -> None:
        pressure_samples = 0
        while not stop_event.wait(1.0) and process.poll() is None:
            try:
                import psutil
                memory = psutil.virtual_memory()
                # Stop only the runner owned by this app. Repeated working-set
                # trimming used to evict mmap pages every 0.5s and cause thrash.
                # A low available-RAM reading alone is expected during mmap
                # paging. The real failure is exhausted allocation capacity.
                commit_available = memory.available + psutil.swap_memory().free
                if os.name == "nt":
                    import ctypes
                    from AI.processors.local_resources import _windows_memory_status
                    status = _windows_memory_status()
                    if status is not None:
                        commit_available = status.available_commit
                pressure_samples = pressure_samples + 1 if commit_available < 512 * 1024**2 else 0
                if pressure_samples >= 4:
                    process.terminate()
                    return
            except Exception:
                return

    _apply_runtime_process_priority(priority, process=process)
    thread = threading.Thread(target=_guard, name="orderscout-llama-server-memory-guard", daemon=True)
    thread.start()
    return stop_event, thread


def _creation_flags_for_priority(priority: str) -> int:
    if os.name != "nt":
        return 0
    clean = str(priority or "").strip().casefold()
    if clean == "idle":
        return int(getattr(subprocess, "IDLE_PRIORITY_CLASS", 0))
    if clean == "below_normal":
        return int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
    return 0


def _record_model_path(record: dict[str, Any] | None) -> str:
    explicit = _compact_text(os.environ.get(MODEL_PATH_ENV))
    candidates = [explicit] if explicit else []
    if isinstance(record, dict):
        for key in ("local_path", "model_path", "gguf_path"):
            candidates.append(_compact_text(record.get(key)))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(candidate)
            if path.is_file() and path.suffix.casefold() == ".gguf":
                return str(path)
        except Exception:
            continue
    return ""


def _apply_local_reasoning_control(
    prompt: str,
    *,
    model_hint: str,
    reasoning_effort: str,
) -> tuple[str, str]:
    """Translate the shared effort setting into supported family controls."""
    text = str(prompt or "")
    model = _compact_text(model_hint).casefold().replace("_", "-")
    effort = _compact_text(reasoning_effort).casefold()
    if "qwen3" not in model or "qwen3.5" in model:
        return text, ""
    if text.lstrip().startswith(("/think", "/no_think")):
        return text, "qwen3_explicit"
    if effort == "low":
        return f"/no_think\n{text}", "qwen3_no_think"
    if effort == "high":
        return f"/think\n{text}", "qwen3_think"
    return text, ""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LLAMA_HOST, 0))
        return int(sock.getsockname()[1])


def _llama_server_args(
    *,
    executable: str,
    model_path: str,
    host: str,
    port: int,
    plan: LocalModelResourcePlan,
) -> list[str]:
    args = [
        executable,
        "-m",
        model_path,
        "--host",
        host,
        "--port",
        str(port),
        "-c",
        str(plan.num_ctx),
        "-t",
        str(plan.num_thread),
        "-n",
        str(plan.max_tokens),
        "--temp",
        "0",
        "--parallel",
        "1",
        "-b",
        str(plan.num_batch),
        "-ub", str(plan.num_ubatch),
        "--jinja", "-fa", "on", "--cache-type-k", plan.cache_type_k,
        "--cache-type-v", plan.cache_type_v,
        "--timeout", str(plan.inference_timeout_seconds),
        "--poll", "0",
        "--cache-ram", "0",
        "--ctx-checkpoints", "0",
    ]
    executable_text = str(executable or "").casefold()
    cpu_only_binary = any(token in executable_text for token in ("windows-x64-cpu", "linux-x64-cpu", "macos-x64-cpu"))
    args.extend(["-ngl", str(plan.num_gpu if not cpu_only_binary else 0)])
    args.append("--mmap" if plan.use_mmap else "--no-mmap")
    if plan.use_mlock:
        args.append("--mlock")
    idle = re.fullmatch(r"(\d+)\s*(ms|s|m|h)", str(plan.keep_alive or "").casefold())
    if idle:
        seconds = int(idle.group(1)) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[idle.group(2)]
        if seconds > 0:
            args.extend(["--sleep-idle-seconds", str(max(1, int(seconds)))])
    return args


def _server_key(model_path: str, plan: LocalModelResourcePlan) -> str:
    return "|".join(
        [
            str(Path(model_path).resolve()),
            str(plan.num_ctx),
            str(plan.num_thread),
            str(plan.num_batch),
            str(plan.num_gpu),
            plan.cache_type_k, plan.cache_type_v, str(plan.num_ubatch), str(plan.max_tokens),
            str(plan.keep_alive), str(plan.inference_timeout_seconds),
            "mmap" if plan.use_mmap else "nommap",
            "mlock" if plan.use_mlock else "nomlock",
        ]
    )


def _wait_for_server(base_url: str, process: subprocess.Popen, *, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + max(1.0, float(timeout or 45.0))
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = ""
            try:
                stderr = process.stderr.read() if process.stderr is not None else ""
            except Exception:
                stderr = ""
            raise RuntimeError((stderr or "llama-server beklenmeden kapandi.").strip())
        for suffix in ("/health", "/v1/models"):
            try:
                _request_json(f"{base_url}{suffix}", timeout=1.0)
                return
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"llama-server zamaninda hazir olmadi: {last_error}")


def _start_managed_llama_server(
    *,
    executable: str,
    model_path: str,
    plan: LocalModelResourcePlan,
    startup_timeout: float = 45.0,
) -> _ManagedLlamaServer:
    key = _server_key(model_path, plan)
    with _SERVER_LOCK:
        existing = _SERVER_CACHE.get(key)
        if existing is not None and existing.process.poll() is None:
            return existing

        # A model switch must release the previous model before allocating the
        # new one. Never stop independently launched llama/Ollama processes.
        shutdown_managed_llama_servers()

        port = _free_port()
        base_url = f"http://{LLAMA_HOST}:{port}"
        command = _llama_server_args(
            executable=executable,
            model_path=model_path,
            host=LLAMA_HOST,
            port=port,
            plan=plan,
        )
        log_dir = AI_RUNTIME_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"llama-server-{port}.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, text=True,
                creationflags=_creation_flags_for_priority(getattr(plan, "process_priority", "normal"))
                    | (getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0))
        _apply_runtime_process_priority(getattr(plan, "process_priority", "normal"), process=process)
        guard = _start_memory_guard(plan, process)
        try:
            _wait_for_server(base_url, process, timeout=startup_timeout)
        except Exception as error:
            if guard is not None:
                guard[0].set()
            try:
                process.terminate()
                process.wait(timeout=10)
            except Exception:
                pass
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-5000:]
            raise RuntimeError(str(error) + "\n" + detail) from error
        managed = _ManagedLlamaServer(
            key=key,
            process=process,
            base_url=base_url,
            model_path=model_path,
            guard_stop_event=guard[0] if guard is not None else None,
            log_path=str(log_path),
        )
        _SERVER_CACHE[key] = managed
        return managed


def build_llama_cpp_server_client(record: dict[str, Any] | None, *, timeout: float = 3600.0) -> LocalPlannerClient | None:
    executable = find_bundled_llama_server()
    model_path = _record_model_path(record)
    if not executable or not model_path:
        return None
    model_stat = Path(model_path).stat() if Path(model_path).is_file() else None
    request_key = json.dumps({"runtime": (record or {}).get("runtime_config") or {},
        "model": str(Path(model_path).resolve()), "executable": executable,
        "model_file": (model_stat.st_size, model_stat.st_mtime_ns) if model_stat else None,
        "environment": {key: os.environ.get(key) for key in ("ORDERSCOUT_LOCAL_NUM_CTX", "ORDERSCOUT_LOCAL_MAX_TOKENS",
            "ORDERSCOUT_LOCAL_NUM_THREAD", "ORDERSCOUT_LOCAL_NUM_BATCH", "ORDERSCOUT_LLAMA_CPP_NUM_GPU")}}, sort_keys=True, default=str)
    with _INFERENCE_LOCK:
        server = None
        with _SERVER_LOCK:
            for owned in _SERVER_CACHE.values():
                if owned.process.poll() is None and owned.request_key == request_key and owned.plan is not None:
                    try:
                        if not _request_json(owned.base_url + "/props", timeout=2).get("is_sleeping", False):
                            server = owned
                            break
                    except (OSError, ValueError):
                        pass
            if server is None:
                shutdown_managed_llama_servers()
        plan = server.plan if server is not None else build_local_resource_plan(record, model_hint=model_path)
        if not plan.safe_to_run:
            raise RuntimeError(plan.reason)
        fallback_reason = ""
        try:
            if server is None:
                server = _start_managed_llama_server(executable=executable, model_path=model_path,
                    plan=plan, startup_timeout=plan.startup_timeout_seconds)
        except RuntimeError as error:
            reason = str(error).casefold()
            if not any(token in reason for token in ("out of memory", "failed to allocate", "alloc failed", "cuda error")):
                raise
            # Same model, same context. Lower GPU allocation and batch once;
            # CPU fallback remains subject to an updated resource check.
            fallback_reason = "GPU allocation failed; retried same model with fewer GPU layers"
            retry_record = {**dict(record or {}), "runtime_config": {
                **dict((record or {}).get("runtime_config") or {}), "num_gpu": max(0, plan.num_gpu // 2),
                "num_batch": 32, "num_ctx": plan.num_ctx, "max_tokens": plan.max_tokens}}
            plan = build_local_resource_plan(retry_record, model_hint=model_path)
            if not plan.safe_to_run:
                raise RuntimeError(plan.reason) from error
            server = _start_managed_llama_server(executable=executable, model_path=model_path,
                plan=plan, startup_timeout=plan.startup_timeout_seconds)
        server.plan, server.request_key = plan, request_key
        client = build_local_http_client(base_url=server.base_url, model=Path(model_path).name,
            plan=plan, record=record)
        client.resource_plan["fallback_reason"] = fallback_reason
        client.runtime_name = "llama_cpp_server"
        client.model_name = model_path
        client.server_url = server.base_url
        client.server_key = server.key
        client.release_after_turn = str(plan.keep_alive).strip().casefold() == "0s"
        client.runtime_lock = _INFERENCE_LOCK
        def cancel_generation():
            with _SERVER_LOCK:
                owned = _SERVER_CACHE.pop(client.server_key, None)
            if owned is not None:
                if owned.guard_stop_event is not None:
                    owned.guard_stop_event.set()
                if owned.process.poll() is None:
                    owned.process.terminate()
                    try:
                        owned.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        owned.process.kill()
                        owned.process.wait(timeout=5)
        def restart_runtime():
            nonlocal plan
            shutdown_managed_llama_servers()
            retry_record = {**dict(record or {}), "runtime_config": {
                **dict((record or {}).get("runtime_config") or {}), "num_ctx": plan.num_ctx,
                "max_tokens": plan.max_tokens}}
            fresh = build_local_resource_plan(retry_record, model_hint=model_path)
            if not fresh.safe_to_run:
                raise RuntimeError(fresh.reason)
            resumed = _start_managed_llama_server(executable=executable, model_path=model_path,
                plan=fresh, startup_timeout=fresh.startup_timeout_seconds)
            resumed.plan, resumed.request_key = fresh, request_key
            plan = fresh
            client.resource_plan.update(fresh.to_dict())
            client.server_key, client.server_url = resumed.key, resumed.base_url
            return resumed.base_url
        def resize_context(required_tokens):
            nonlocal plan
            target = ((int(required_tokens) + 4095) // 4096) * 4096
            if target > 32768 or ((record or {}).get("runtime_config") or {}).get("allow_context_growth") is False:
                raise LocalContextExceeded("Tam girdi yerel bağlam sınırını aşıyor; kayıtlar korundu, içerik kesilmedi.")
            previous_context = plan.num_ctx
            shutdown_managed_llama_servers()
            grown_record = {**dict(record or {}), "runtime_config": {
                **dict((record or {}).get("runtime_config") or {}), "num_ctx": target,
                "max_tokens": plan.max_tokens, "reasoning_effort": plan.reasoning_effort}}
            fresh = build_local_resource_plan(grown_record, model_hint=model_path)
            if not fresh.safe_to_run or fresh.num_ctx < required_tokens:
                client.resource_plan["restart_required"] = True
                raise LocalContextExceeded("Bağlam büyütmek için yeterli çalışma belleği yok veya model/ayar sınırı aşıldı. "
                    "Kayıtlar korundu; içerik kesilmedi.")
            grown = _start_managed_llama_server(executable=executable, model_path=model_path,
                plan=fresh, startup_timeout=fresh.startup_timeout_seconds)
            grown.plan, grown.request_key = fresh, request_key
            plan = fresh
            client.server_key, client.server_url = grown.key, grown.base_url
            client.resource_plan.update(fresh.to_dict())
            client.resource_plan.update({"context_resized_from": previous_context,
                "context_resized_to": fresh.num_ctx, "context_resize_reason": "preserve_complete_input_and_output_budget"})
            client.resource_plan["capability_profile"]["context_tokens"] = fresh.num_ctx
            return grown.base_url, fresh
        def ensure_runtime():
            with _SERVER_LOCK:
                owned = _SERVER_CACHE.get(client.server_key)
            if owned is not None and owned.process.poll() is None:
                try:
                    if not _request_json(owned.base_url + "/props", timeout=2).get("is_sleeping", False):
                        return owned.base_url
                except (OSError, ValueError):
                    pass
            return restart_runtime()
        client.cancel_generation = cancel_generation
        client.restart_runtime = restart_runtime
        client.ensure_runtime = ensure_runtime
        client.resize_context = resize_context
        return client


def build_llama_cpp_cli_client(record: dict[str, Any] | None, *, timeout: float = 600.0) -> LocalPlannerClient | None:
    """Diagnostic fallback for tests and developer environments.

    Product chat uses managed llama-server. This remains intentionally unadvertised
    so local inference still has one public runner contract: llama.cpp.
    """
    explicit = _compact_text(os.environ.get("ORDERSCOUT_LLAMA_CPP_CLI"))
    executable = explicit if explicit and Path(explicit).exists() else ""
    if not executable:
        for name in ("llama-cli.exe", "llama-cli"):
            resolved = shutil.which(name)
            if resolved:
                executable = resolved
                break
    model_path = _record_model_path(record)
    if not executable or not model_path:
        return None
    plan = build_local_resource_plan(record, model_hint=model_path)

    def _planner(prompt: str) -> str:
        if not plan.safe_to_run:
            raise RuntimeError(plan.reason)
        controlled_prompt, reasoning_control = _apply_local_reasoning_control(
            prompt,
            model_hint=model_path,
            reasoning_effort=plan.reasoning_effort,
        )
        runtime_plan = _local_runtime_plan_payload(
            plan,
            record,
            model_path=model_path,
        )
        runtime_plan["reasoning_control"] = reasoning_control
        setattr(_planner, "resource_plan", runtime_plan)
        command = [
            executable,
            "-m",
            model_path,
            "-p",
            controlled_prompt,
            *plan.to_llama_cpp_args(),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=_creation_flags_for_priority(getattr(plan, "process_priority", "normal")),
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "llama.cpp runner failed").strip())
        return str(result.stdout or "").strip()

    setattr(_planner, "runtime_name", "llama_cpp_cli")
    setattr(_planner, "model_name", model_path)
    setattr(
        _planner,
        "resource_plan",
        _local_runtime_plan_payload(plan, record, model_path=model_path),
    )
    return _planner


def build_local_planner_client(record: dict[str, Any] | None, *, host: str | None = None) -> LocalPlannerClient | None:
    del host
    return build_llama_cpp_server_client(record)


def shutdown_managed_llama_servers() -> None:
    with _SERVER_LOCK:
        servers = list(_SERVER_CACHE.values())
        _SERVER_CACHE.clear()
    for server in servers:
        if server.guard_stop_event is not None:
            server.guard_stop_event.set()
        try:
            if server.process.poll() is None:
                server.process.terminate()
                server.process.wait(timeout=10)
        except Exception:
            continue


def release_local_planner_client(planner_client: LocalPlannerClient | None) -> None:
    close = getattr(planner_client, "close", None)
    if callable(close):
        close()
    key = _compact_text(getattr(planner_client, "server_key", ""))
    if not key:
        return
    with _SERVER_LOCK:
        server = _SERVER_CACHE.pop(key, None)
    if server is None:
        return
    if server.guard_stop_event is not None:
        server.guard_stop_event.set()
    try:
        if server.process.poll() is None:
            server.process.terminate()
            server.process.wait(timeout=10)
    except Exception:
        return


atexit.register(shutdown_managed_llama_servers)
