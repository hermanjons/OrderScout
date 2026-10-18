from __future__ import annotations

import json
import os
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
from AI.processors.cloud_runtime import build_openai_compatible_client
from AI.processors.local_resources import LocalModelResourcePlan, build_local_resource_plan
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


_SERVER_LOCK = threading.Lock()
_SERVER_CACHE: dict[str, _ManagedLlamaServer] = {}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _compact_local_prompt(
    prompt: str,
    *,
    num_ctx: int,
    max_tokens: int,
) -> tuple[str, dict[str, Any]]:
    text = str(prompt or "")
    input_token_budget = max(512, int(num_ctx or 4096) - int(max_tokens or 256) - 256)
    max_input_chars = max(2_000, input_token_budget * 3)
    original_chars = len(text)
    if original_chars <= max_input_chars:
        return text, {
            "prompt_compacted": False,
            "prompt_input_chars": original_chars,
            "prompt_output_chars": original_chars,
            "prompt_max_input_chars": max_input_chars,
            "prompt_compaction_strategy": "none",
        }

    def _compact_history_segment(value: str, start: str, end: str) -> str:
        start_at = value.find(start)
        if start_at < 0:
            return value
        payload_at = start_at + len(start)
        end_at = value.find(end, payload_at)
        if end_at < 0:
            return value
        payload = value[payload_at:end_at].strip()
        try:
            rows = json.loads(payload)
        except Exception:
            rows = []
        if not isinstance(rows, list) or not rows:
            return value
        compact_rows = rows[-6:]
        replacement = json.dumps(compact_rows, ensure_ascii=False)
        return f"{value[:payload_at]}{replacement}{value[end_at:]}"

    compacted = _compact_history_segment(text, "<history>", "</history>")
    compacted = _compact_history_segment(
        compacted,
        "Konusma gecmisi:\n",
        "\n\nIzinli read-only lokal DB tool'lari:",
    )
    strategy = "recent_history"
    if len(compacted) > max_input_chars:
        marker = "\n...[yerel model baglamina sigmasi icin orta bolum kisaltildi]...\n"
        available = max(256, max_input_chars - len(marker))
        head_chars = max(256, int(available * 0.32))
        tail_chars = max(256, available - head_chars)
        compacted = f"{compacted[:head_chars]}{marker}{compacted[-tail_chars:]}"
        strategy = "recent_history+head_tail"
    return compacted, {
        "prompt_compacted": True,
        "prompt_input_chars": original_chars,
        "prompt_output_chars": len(compacted),
        "prompt_max_input_chars": max_input_chars,
        "prompt_compaction_strategy": strategy,
    }


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
    with urllib.request.urlopen(request, timeout=timeout) as response:
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


def _runtime_process_names() -> tuple[str, ...]:
    return ("llama-server", "llama-server.exe", "server.exe")


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
    if not targets:
        for proc in psutil.process_iter(["name"]):
            try:
                name = str((proc.info or {}).get("name") or "").casefold()
                if name and any(token in name for token in _runtime_process_names()):
                    targets.append(proc)
            except Exception:
                continue
    for proc in targets:
        try:
            proc.nice(priority_value)
        except Exception:
            continue


def _trim_process_working_set(pid: int) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        psapi.EmptyWorkingSet.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x0400 | 0x0100, False, int(pid))
        if not handle:
            return
        try:
            psapi.EmptyWorkingSet(handle)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return


def _start_memory_guard(plan: LocalModelResourcePlan, process: subprocess.Popen) -> tuple[threading.Event, threading.Thread] | None:
    if not bool(getattr(plan, "trim_working_set", False)) or os.name != "nt":
        return None
    stop_event = threading.Event()
    priority = str(getattr(plan, "process_priority", "normal") or "normal")

    def _guard() -> None:
        while not stop_event.wait(0.5):
            _apply_runtime_process_priority(priority, process=process)
            if process.poll() is None:
                _trim_process_working_set(int(process.pid))

    _apply_runtime_process_priority(priority, process=process)
    if process.poll() is None:
        _trim_process_working_set(int(process.pid))
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
    if "qwen3" not in model:
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
    ]
    executable_text = str(executable or "").casefold()
    cpu_only_binary = any(token in executable_text for token in ("windows-x64-cpu", "linux-x64-cpu", "macos-x64-cpu"))
    if plan.num_gpu > 0 and not cpu_only_binary:
        args.extend(["-ngl", str(plan.num_gpu)])
    args.append("--mmap" if plan.use_mmap else "--no-mmap")
    if plan.use_mlock:
        args.append("--mlock")
    return args


def _server_key(model_path: str, plan: LocalModelResourcePlan) -> str:
    return "|".join(
        [
            str(Path(model_path).resolve()),
            str(plan.num_ctx),
            str(plan.num_thread),
            str(plan.num_batch),
            str(plan.num_gpu),
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

        port = _free_port()
        base_url = f"http://{LLAMA_HOST}:{port}"
        command = _llama_server_args(
            executable=executable,
            model_path=model_path,
            host=LLAMA_HOST,
            port=port,
            plan=plan,
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=_creation_flags_for_priority(getattr(plan, "process_priority", "normal")),
        )
        _apply_runtime_process_priority(getattr(plan, "process_priority", "normal"), process=process)
        guard = _start_memory_guard(plan, process)
        try:
            _wait_for_server(base_url, process, timeout=startup_timeout)
        except Exception:
            if guard is not None:
                guard[0].set()
            try:
                process.terminate()
            except Exception:
                pass
            raise
        managed = _ManagedLlamaServer(
            key=key,
            process=process,
            base_url=base_url,
            model_path=model_path,
            guard_stop_event=guard[0] if guard is not None else None,
        )
        _SERVER_CACHE[key] = managed
        return managed


def build_llama_cpp_server_client(record: dict[str, Any] | None, *, timeout: float = 600.0) -> LocalPlannerClient | None:
    executable = find_bundled_llama_server()
    model_path = _record_model_path(record)
    if not executable or not model_path:
        return None

    plan = build_local_resource_plan(record, model_hint=model_path)
    if (
        not plan.safe_to_run
        and not bool(getattr(plan, "allow_unsafe", False))
        and _compact_text(os.environ.get("ORDERSCOUT_LOCAL_ALLOW_UNSAFE")) != "1"
    ):
        raise RuntimeError(plan.reason)

    server = _start_managed_llama_server(
        executable=executable,
        model_path=model_path,
        plan=plan,
        startup_timeout=float(getattr(plan, "startup_timeout_seconds", 45) or 45),
    )
    client = build_openai_compatible_client(
        base_url=f"{server.base_url}/v1",
        api_key=DEFAULT_LOCAL_API_KEY,
        model=Path(model_path).name,
        timeout=timeout,
        request_options=plan.to_openai_request_options(),
    )
    if client is None:
        return None

    def _client(prompt: str) -> str:
        controlled_prompt, reasoning_control = _apply_local_reasoning_control(
            prompt,
            model_hint=model_path,
            reasoning_effort=plan.reasoning_effort,
        )
        compacted_prompt, compaction = _compact_local_prompt(
            controlled_prompt,
            num_ctx=plan.num_ctx,
            max_tokens=plan.max_tokens,
        )
        runtime_plan = _local_runtime_plan_payload(
            plan,
            record,
            model_path=model_path,
        )
        runtime_plan.update(compaction)
        runtime_plan["reasoning_control"] = reasoning_control
        setattr(_client, "resource_plan", runtime_plan)
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return client(compacted_prompt)
            except Exception as exc:
                last_exc = exc
                time.sleep(0.25 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
        return ""

    setattr(_client, "runtime_name", "llama_cpp_server")
    setattr(_client, "model_name", model_path)
    setattr(
        _client,
        "resource_plan",
        _local_runtime_plan_payload(plan, record, model_path=model_path),
    )
    setattr(_client, "server_url", server.base_url)
    setattr(_client, "server_key", server.key)
    setattr(
        _client,
        "release_after_turn",
        str(plan.keep_alive or "").strip().casefold() == "0s"
        and (bool(plan.trim_working_set) or int(plan.estimated_model_bytes or 0) >= 10 * 1024 ** 3),
    )
    return _client


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
        if (
            not plan.safe_to_run
            and not bool(getattr(plan, "allow_unsafe", False))
            and _compact_text(os.environ.get("ORDERSCOUT_LOCAL_ALLOW_UNSAFE")) != "1"
        ):
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
        except Exception:
            continue


def release_local_planner_client(planner_client: LocalPlannerClient | None) -> None:
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
    except Exception:
        return
