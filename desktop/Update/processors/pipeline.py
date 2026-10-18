from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from PyQt6.QtCore import QThread

from Feedback.processors.pipeline import Result, map_error_to_message
from Update.api.github_release_api import fetch_latest_release
from Update.constants.paths import UPDATE_CONFIG_FILE, UPDATE_STATE_FILE, UPDATES_ROOT
from Update.constants.config_constants import DEFAULT_UPDATE_CONFIG, VALID_UPDATE_CHANNELS, VERSION_DIR_PREFIX
from settings import APP_VERSION

_SEMVER_RE = re.compile(r"(?P<v>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)")
_VALID_UPDATE_CHANNELS = set(VALID_UPDATE_CHANNELS)
_VERSION_DIR_PREFIX = VERSION_DIR_PREFIX
_UPDATE_STARTUP_WATCH_SECONDS = 12.0
_ROLLBACK_REASON_PROMPT_NOT_REACHED = "target_prompt_not_reached"


def _same_resolved_path(left: str, right: str) -> bool:
    if not str(left or "").strip() or not str(right or "").strip():
        return False
    try:
        return Path(str(left).strip()).resolve() == Path(str(right).strip()).resolve()
    except Exception:
        return False


def _thread_sleep(seconds: float) -> None:
    QThread.msleep(max(1, int(float(seconds or 0.0) * 1000)))


def load_update_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_UPDATE_CONFIG)
    if not isinstance(cfg, dict):
        raise RuntimeError("Update config JSON obje olmalidir.")

    required_root = ("enabled", "check_on_startup", "startup_delay_ms", "provider", "github", "request", "asset")
    for key in required_root:
        if key not in cfg:
            raise RuntimeError(f"Update config zorunlu alan eksik: {key}")
    if not isinstance(cfg.get("github"), dict):
        raise RuntimeError("Update config 'github' alani obje olmalidir.")
    if not isinstance(cfg.get("request"), dict):
        raise RuntimeError("Update config 'request' alani obje olmalidir.")
    if not isinstance(cfg.get("asset"), dict):
        raise RuntimeError("Update config 'asset' alani obje olmalidir.")
    if "integrity" in cfg and not isinstance(cfg.get("integrity"), dict):
        raise RuntimeError("Update config 'integrity' alani obje olmalidir.")
    if "dev" in cfg and not isinstance(cfg.get("dev"), dict):
        raise RuntimeError("Update config 'dev' alani obje olmalidir.")
    if "dev" in cfg and isinstance(cfg.get("dev"), dict):
        dev_cfg = cfg.get("dev") or {}
        if "allow_non_frozen_apply" in dev_cfg and not isinstance(dev_cfg.get("allow_non_frozen_apply"), bool):
            raise RuntimeError("Update config 'dev.allow_non_frozen_apply' bool olmalidir.")
    if "channel" in cfg:
        channel = str(cfg.get("channel") or "").strip().lower()
        if channel not in _VALID_UPDATE_CHANNELS:
            raise RuntimeError("Update config 'channel' alani stable/beta olmalidir.")
    return cfg


def _emit_progress(
    callback: Optional[Callable[[str, int, int], None]],
    stage: str,
    current: int,
    total: int,
) -> None:
    if callback is None:
        return
    try:
        callback(str(stage or ""), int(current or 0), int(total or 0))
    except Exception:
        pass


def _parse_timeout_sec(request_cfg: dict[str, Any]) -> int:
    try:
        timeout_sec = int(request_cfg.get("timeout_sec"))
    except Exception as exc:
        raise RuntimeError("Update config hatalÄ±: request.timeout_sec geÃ§ersiz.") from exc
    if timeout_sec <= 0:
        raise RuntimeError("Update config hatalÄ±: request.timeout_sec pozitif olmalÄ±.")
    return timeout_sec


def _parse_retry_count(request_cfg: dict[str, Any]) -> int:
    raw = request_cfg.get("retry_count", 3)
    try:
        retry_count = int(raw)
    except Exception as exc:
        raise RuntimeError("Update config hatali: request.retry_count gecersiz.") from exc
    if retry_count <= 0:
        raise RuntimeError("Update config hatali: request.retry_count pozitif olmali.")
    return retry_count


def _parse_retry_backoff_sec(request_cfg: dict[str, Any]) -> float:
    raw = request_cfg.get("retry_backoff_sec", 1.0)
    try:
        backoff_sec = float(raw)
    except Exception as exc:
        raise RuntimeError("Update config hatalÄ±: request.retry_backoff_sec geÃ§ersiz.") from exc
    if backoff_sec < 0:
        raise RuntimeError("Update config hatalÄ±: request.retry_backoff_sec negatif olamaz.")
    return backoff_sec


def _normalize_sha256_text(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("sha256:"):
        raw = raw.split(":", 1)[1].strip()
    return raw if re.fullmatch(r"[0-9a-f]{64}", raw) else ""


def _asset_expected_sha256(asset: dict[str, Any]) -> str:
    if not isinstance(asset, dict):
        return ""
    return _normalize_sha256_text(asset.get("digest"))


def _parse_bool_text(value: Any) -> Optional[bool]:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "on", "yes", "y", "enable", "enabled"}:
        return True
    if raw in {"0", "false", "off", "no", "n", "disable", "disabled"}:
        return False
    return None


def _allow_non_frozen_apply(config: Optional[dict[str, Any]] = None) -> bool:
    env_choice = _parse_bool_text(os.environ.get("ORDER_SCOUT_UPDATE_DEV_APPLY"))
    if env_choice is not None:
        return bool(env_choice)

    cfg = config if isinstance(config, dict) else load_update_config()
    dev_cfg = cfg.get("dev") if isinstance(cfg.get("dev"), dict) else {}
    return bool(dev_cfg.get("allow_non_frozen_apply", False))


def _state_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_update_state() -> dict[str, Any]:
    path = UPDATE_STATE_FILE
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_update_state(state: dict[str, Any]) -> None:
    path = UPDATE_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state or {}, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_update_state() -> None:
    try:
        UPDATE_STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _resolve_runtime_executable_path() -> Path:
    if bool(getattr(sys, "frozen", False)):
        return Path(sys.executable).resolve()
    install_dir, exe_name = _runtime_context()
    return (install_dir / exe_name).resolve()


def _safe_version_folder_name(version: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z._-]+", "-", str(version or "").strip())
    clean = clean.strip("-. _")
    if not clean:
        clean = "unknown"
    return f"{_VERSION_DIR_PREFIX}{clean}"


def _resolve_install_parent_dir(current_install_dir: Path) -> Path:
    folder = str(current_install_dir.name or "").strip().lower()
    if folder.startswith(_VERSION_DIR_PREFIX):
        return current_install_dir.parent
    return current_install_dir


def _resolve_version_slot(*, current_install_dir: Path, release_version: str, exe_name: str) -> tuple[Path, Path]:
    parent = _resolve_install_parent_dir(current_install_dir)
    target_dir = parent / _safe_version_folder_name(release_version)
    return target_dir, target_dir / str(exe_name or "OrderScout.exe")


def _cleanup_previous_install_payload(*, from_exe: str, target_exe: str) -> tuple[bool, list[str]]:
    removed_any = False
    removed_items: list[str] = []

    old_exe = Path(str(from_exe or "").strip()).resolve()
    new_exe = Path(str(target_exe or "").strip()).resolve()
    if not str(old_exe) or not str(new_exe):
        return False, removed_items

    old_dir = old_exe.parent
    new_dir = new_exe.parent
    if not old_dir.exists() or old_dir == new_dir:
        return False, removed_items

    def _remove_path(path: Path) -> None:
        nonlocal removed_any
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=False)
                removed_any = True
                removed_items.append(str(path))
                return
            if path.exists():
                path.unlink(missing_ok=True)
                removed_any = True
                removed_items.append(str(path))
        except Exception:
            # Cleanup should be best-effort and should not break accepted state.
            pass

    # Previous version in version-slot directory (os-<version>).
    if old_dir.name.lower().startswith(_VERSION_DIR_PREFIX):
        _remove_path(old_dir)
        return removed_any, removed_items

    # Previous root install payload when the new version is installed into an
    # os-<version> slot below the same install root. Keep unrelated user data.
    if new_dir.parent == old_dir and new_dir.name.lower().startswith(_VERSION_DIR_PREFIX):
        _remove_path(old_exe)
        _remove_path(old_dir / "_internal")
        for pattern in ("unins*.exe", "unins*.dat", "unins*.msg"):
            for candidate in old_dir.glob(pattern):
                if candidate.parent == old_dir:
                    _remove_path(candidate)

    return removed_any, removed_items


def _ps_sq(text: Any) -> str:
    return str(text or "").replace("'", "''")


def _write_windows_installer_runner_script(
    *,
    installer_path: Path,
    target_dir: Path,
    installer_log: Path,
    runner_state_path: Path,
    target_exe: Path,
    previous_exe: Path,
    script_path: Path,
) -> Result:
    try:
        ins = _ps_sq(str(installer_path.resolve()))
        tdir = _ps_sq(str(target_dir.resolve()))
        log = _ps_sq(str(installer_log.resolve()))
        state = _ps_sq(str(runner_state_path.resolve()))
        nex = _ps_sq(str(target_exe.resolve()))
        old = _ps_sq(str(previous_exe.resolve()))

        script = f"""Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = 'SilentlyContinue'
$InstallerPath = '{ins}'
$TargetDir = '{tdir}'
$LogPath = '{log}'
$StatePath = '{state}'
$NewExe = '{nex}'
        $OldExe = '{old}'

function Write-State([string]$Status, [int]$Progress, [string]$Message) {{
    try {{
        $obj = [ordered]@{{
            status = $Status
            progress = $Progress
            message = $Message
            updated_at = (Get-Date).ToString('o')
        }}
        $json = $obj | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText($StatePath, $json, [System.Text.Encoding]::UTF8)
    }} catch {{}}
}}

function To-Ascii([string]$Text) {{
    if (-not $Text) {{ return '' }}
    try {{
        $sanitized = [regex]::Replace([string]$Text, '[^\\u0020-\\u007E]', ' ')
        $sanitized = [regex]::Replace($sanitized, '\\s+', ' ')
        return $sanitized.Trim()
    }} catch {{
        return [string]$Text
    }}
}}

Write-State 'runner_starting' 2 'Runner started.'

$form = New-Object System.Windows.Forms.Form
$form.Text = 'OrderScout Update'
$form.Size = New-Object System.Drawing.Size(620, 250)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)

$header = New-Object System.Windows.Forms.Panel
$header.Left = 0
$header.Top = 0
$header.Width = 620
$header.Height = 56
$header.BackColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$form.Controls.Add($header)

$title = New-Object System.Windows.Forms.Label
$title.AutoSize = $false
$title.Width = 584
$title.Height = 26
$title.Left = 16
$title.Top = 14
$title.Font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::White
$title.Text = 'OrderScout güncellemesi uygulanıyor...'
$header.Controls.Add($title)

$note = New-Object System.Windows.Forms.Label
$note.AutoSize = $false
$note.Width = 584
$note.Height = 20
$note.Left = 18
$note.Top = 72
$note.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$note.ForeColor = [System.Drawing.Color]::FromArgb(71, 85, 105)
$note.Text = 'Kurulum bitince uygulama otomatik olarak acilacak.'
$form.Controls.Add($note)

$stage = New-Object System.Windows.Forms.Label
$stage.AutoSize = $false
$stage.Width = 520
$stage.Height = 40
$stage.Left = 18
$stage.Top = 96
$stage.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Regular)
$stage.ForeColor = [System.Drawing.Color]::FromArgb(30, 41, 59)
$stage.Text = 'Kurulum baslatiliyor...'
$form.Controls.Add($stage)

$percent = New-Object System.Windows.Forms.Label
$percent.AutoSize = $false
$percent.Width = 62
$percent.Height = 20
$percent.Left = 542
$percent.Top = 136
$percent.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$percent.ForeColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$percent.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$percent.Text = '6%'
$form.Controls.Add($percent)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Minimum = 0
$bar.Maximum = 100
$bar.Value = 6
$bar.Style = 'Continuous'
$bar.Width = 584
$bar.Height = 24
$bar.Left = 18
$bar.Top = 160
$form.Controls.Add($bar)

function Set-UiProgress([int]$Value, [string]$StageText, [string]$Status = 'running') {{
    try {{
        $safe = [Math]::Max(0, [Math]::Min(100, [int]$Value))
        if ($bar.Value -ne $safe) {{ $bar.Value = $safe }}
        $percent.Text = "$safe%"
        if (-not [string]::IsNullOrWhiteSpace([string]$StageText)) {{
            $stage.Text = [string]$StageText
        }}
        $percent.Refresh()
        $stage.Refresh()
        $bar.Refresh()
        $form.Refresh()
        Write-State $Status $safe $stage.Text
    }} catch {{}}
}}

$form.Add_Shown({{
    Write-State 'ui_ready' 6 'Installer UI opened.'
}})

if (Test-Path $LogPath) {{
    try {{ Remove-Item -Force $LogPath -ErrorAction SilentlyContinue }} catch {{}}
}}

try {{
    $procName = [System.IO.Path]::GetFileNameWithoutExtension($OldExe)
    if ($procName) {{
        for ($i = 0; $i -lt 50; $i++) {{
            $running = Get-Process -Name $procName -ErrorAction SilentlyContinue
            if (-not $running) {{ break }}
            Start-Sleep -Milliseconds 300
        }}
    }}
}} catch {{}}

$argList = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/LOG=$LogPath", "/DIR=$TargetDir")
$proc = Start-Process -FilePath $InstallerPath -ArgumentList $argList -PassThru
Write-State 'installer_started' 10 'Installer process started.'

$lastLine = ''
$pulse = 12
$stallTicks = 0

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 450
$timer.Add_Tick({{
    $progressChanged = $false
    if (Test-Path $LogPath) {{
        try {{
            $line = Get-Content $LogPath -Tail 1 -ErrorAction SilentlyContinue
            if ($line -and $line -ne $lastLine) {{
                $lastLine = $line
                $cleanLine = To-Ascii([string]$line)
                if ([string]::IsNullOrWhiteSpace($cleanLine)) {{
                    $cleanLine = 'Installing files...'
                }}
                $stallTicks = 0
                $pulse = [Math]::Min(93, $pulse + 4)
                Set-UiProgress $pulse "Adim: $cleanLine" 'running'
                $progressChanged = $true
            }}
        }} catch {{}}
    }}

    if ((-not $proc.HasExited) -and (-not $progressChanged)) {{
        $stallTicks = [Math]::Min(9999, $stallTicks + 1)
        $step = 0
        if ($pulse -lt 30) {{
            $step = 2
        }} elseif ($pulse -lt 80) {{
            $step = 1
        }} elseif ((($stallTicks % 3) -eq 0) -and ($pulse -lt 96)) {{
            $step = 1
        }}

        if ($step -gt 0) {{
            $pulse = [Math]::Min(96, $pulse + $step)
            $currentStage = [string]$stage.Text
            if ([string]::IsNullOrWhiteSpace($currentStage)) {{
                $currentStage = 'Kurulum devam ediyor...'
            }}
            Set-UiProgress $pulse $currentStage 'running'
        }}
    }}

    if ($proc.HasExited) {{
        $timer.Stop()
        if ($proc.ExitCode -eq 0) {{
            $bar.Value = 100
            $percent.Text = '100%'
            $stage.Text = 'Guncelleme tamamlandi. Uygulama aciliyor...'
            Write-State 'completed' 100 $stage.Text
            if (Test-Path $NewExe) {{
                Start-Process -FilePath $NewExe
            }} elseif (Test-Path $OldExe) {{
                Start-Process -FilePath $OldExe
            }}
        }} else {{
            $bar.Value = 0
            $percent.Text = '0%'
            $stage.Text = "Güncelleme başarısız (Kod: $($proc.ExitCode)). Uygulama yeniden açılıyor..."
            Write-State 'failed' 0 $stage.Text
            if (Test-Path $OldExe) {{
                Start-Process -FilePath $OldExe
            }}
        }}
        Start-Sleep -Milliseconds 1800
        $form.Close()
    }}
}})
$timer.Start()
[void]$form.ShowDialog()
"""
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script, encoding="utf-8-sig")
        return Result.ok(
            "Installer runner script prepared.",
            close_dialog=False,
            data={"script_path": str(script_path)},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _load_runner_state(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8-sig")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _wait_for_runner_ready(state_path: Path, timeout_sec: float = 6.0) -> bool:
    deadline = time.monotonic() + max(0.5, float(timeout_sec or 0.0))
    ready_states = {"runner_starting", "ui_ready", "installer_started", "running", "completed", "failed"}
    while time.monotonic() < deadline:
        state = _load_runner_state(state_path)
        status = str(state.get("status") or "").strip().lower()
        if status in ready_states:
            return True
        _thread_sleep(0.12)
    return False


def _write_installer_runner_payload(
    *,
    installer_path: Path,
    target_dir: Path,
    installer_log: Path,
    runner_state_path: Path,
    target_exe: Path,
    previous_exe: Path,
    payload_path: Path,
    release_version: str,
) -> Result:
    try:
        payload = {
            "installer_path": str(installer_path.resolve()),
            "target_dir": str(target_dir.resolve()),
            "installer_log": str(installer_log.resolve()),
            "runner_state": str(runner_state_path.resolve()),
            "target_exe": str(target_exe.resolve()),
            "previous_exe": str(previous_exe.resolve()),
            "release_version": str(release_version or "").strip(),
            "startup_watch_seconds": _UPDATE_STARTUP_WATCH_SECONDS,
        }
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return Result.ok(
            "Installer runner payload prepared.",
            close_dialog=False,
            data={"payload_path": str(payload_path)},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _main_entry_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "main.py"


def _build_installer_runner_command(*, current_exe: str, runner_payload: Path) -> list[str]:
    payload_arg = str(runner_payload)
    current_exe_text = str(current_exe or "").strip()
    if current_exe_text.lower().endswith(".exe"):
        return [current_exe_text, "--update-runner", payload_arg]
    if bool(getattr(sys, "frozen", False)):
        return [str(Path(sys.executable).resolve()), "--update-runner", payload_arg]
    return [str(Path(sys.executable).resolve()), str(_main_entry_script_path()), "--update-runner", payload_arg]


def _begin_installer_update_state(
    *,
    release_version: str,
    workspace: str,
    from_exe: str,
    target_exe: str,
) -> None:
    now = _state_now_iso()
    state = {
        "status": "pending_install",
        "release_version": str(release_version or "").strip(),
        "workspace": str(workspace or "").strip(),
        "from_exe": str(from_exe or "").strip(),
        "target_exe": str(target_exe or "").strip(),
        "updated_at": now,
        "created_at": now,
    }
    _save_update_state(state)


def _parse_semver_tuple(text: str) -> Optional[tuple[int, int, int]]:
    src = str(text or "").strip()
    if not src:
        return None
    match = _SEMVER_RE.search(src)
    if not match:
        return None
    try:
        semver = str(match.group("v") or "").split("+", 1)[0]
        core = semver.split("-", 1)[0]
        parts = core.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return None


def _extract_semver_string(text: str) -> Optional[str]:
    src = str(text or "").strip()
    if not src:
        return None
    match = _SEMVER_RE.search(src)
    if not match:
        return None
    return match.group("v")


def _parse_semver_components(text: str) -> Optional[tuple[tuple[int, int, int], list[str]]]:
    raw = _extract_semver_string(text)
    if not raw:
        return None
    raw = str(raw).split("+", 1)[0]
    core = _parse_semver_tuple(raw)
    if core is None:
        return None
    if "-" not in raw:
        return core, []
    pre_raw = raw.split("-", 1)[1]
    pre_ids = [str(p).strip().lower() for p in pre_raw.split(".") if str(p).strip()]
    return core, pre_ids


def _compare_prerelease_identifiers(left: list[str], right: list[str]) -> int:
    max_len = max(len(left), len(right))
    for idx in range(max_len):
        if idx >= len(left):
            return -1
        if idx >= len(right):
            return 1

        a = left[idx]
        b = right[idx]
        a_is_num = a.isdigit()
        b_is_num = b.isdigit()

        if a_is_num and b_is_num:
            ai = int(a)
            bi = int(b)
            if ai < bi:
                return -1
            if ai > bi:
                return 1
            continue

        if a_is_num and not b_is_num:
            return -1
        if not a_is_num and b_is_num:
            return 1

        if a < b:
            return -1
        if a > b:
            return 1

    return 0


def _compare_semver(left_text: str, right_text: str) -> Optional[int]:
    left = _parse_semver_components(left_text)
    right = _parse_semver_components(right_text)
    if left is None or right is None:
        return None

    left_core, left_pre = left
    right_core, right_pre = right
    if left_core < right_core:
        return -1
    if left_core > right_core:
        return 1

    # Same core: stable is newer than prerelease.
    if not left_pre and not right_pre:
        return 0
    if not left_pre and right_pre:
        return 1
    if left_pre and not right_pre:
        return -1

    return _compare_prerelease_identifiers(left_pre, right_pre)


def _is_prerelease_version(text: str) -> bool:
    parsed = _parse_semver_components(text)
    return bool(parsed and parsed[1])


def _release_version(release: dict[str, Any]) -> Optional[str]:
    for key in ("tag_name", "name"):
        found = _extract_semver_string(str(release.get(key) or ""))
        if found:
            return found
    return None


def _is_newer_version(current_version: str, latest_version: str) -> bool:
    comp = _compare_semver(current_version, latest_version)
    if comp is None:
        return False
    return comp < 0


def select_release_asset(release: dict[str, Any], config: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    cfg = config or load_update_config()
    asset_cfg = cfg.get("asset") if isinstance(cfg, dict) else {}
    if not isinstance(asset_cfg, dict):
        raise RuntimeError("Update config 'asset' alani obje olmalidir.")

    if not isinstance(asset_cfg.get("prefer_extensions"), list):
        raise RuntimeError("Update config 'asset.prefer_extensions' listesi zorunludur.")
    if not isinstance(asset_cfg.get("name_contains"), list):
        raise RuntimeError("Update config 'asset.name_contains' listesi zorunludur.")
    if not isinstance(asset_cfg.get("exclude_contains"), list):
        raise RuntimeError("Update config 'asset.exclude_contains' listesi zorunludur.")

    prefer_extensions = [str(x).lower() for x in asset_cfg.get("prefer_extensions") if str(x).strip()]
    if not prefer_extensions:
        raise RuntimeError("Update config 'asset.prefer_extensions' bos olamaz.")
    name_contains = [str(x).lower() for x in asset_cfg.get("name_contains") if str(x).strip()]
    exclude_contains = [str(x).lower() for x in asset_cfg.get("exclude_contains") if str(x).strip()]

    assets = release.get("assets") if isinstance(release, dict) else []
    if not isinstance(assets, list) or not assets:
        return None

    scored: list[tuple[int, dict[str, Any]]] = []

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        url = str(asset.get("download_url") or "").strip()
        if not name or not url:
            continue

        name_l = name.lower()
        if any(tok in name_l for tok in exclude_contains):
            continue

        score = 0
        matched_extension = ""
        for idx, ext in enumerate(prefer_extensions):
            if name_l.endswith(ext):
                matched_extension = ext
                score += 200 - (idx * 30)
                break
        if not matched_extension:
            continue
        if matched_extension == ".zip":
            continue

        for kw in name_contains:
            if kw in name_l:
                score += 20

        score += min(int(asset.get("size") or 0) // (1024 * 1024), 15)
        scored.append((score, asset))

    if not scored:
        return None

    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[0][1]


def check_for_updates(current_version: Optional[str] = None) -> Result:
    try:
        cfg = load_update_config()
        if not bool(cfg.get("enabled")):
            return Result.ok(
                "Update system is disabled.",
                close_dialog=False,
                data={"enabled": False, "available": False},
            )

        provider = str(cfg.get("provider") or "").strip().lower()
        if provider != "github":
            return Result.fail(f"Unsupported update provider: {provider}", close_dialog=False)

        gh = cfg.get("github")
        req = cfg.get("request")
        if not isinstance(gh, dict):
            return Result.fail("Update config hatali: 'github' alani yok.", close_dialog=False)
        if not isinstance(req, dict):
            return Result.fail("Update config hatali: 'request' alani yok.", close_dialog=False)

        owner = str(gh.get("owner") or "").strip()
        repo = str(gh.get("repo") or "").strip()
        api_base = str(gh.get("api_base") or "").strip()
        current = str(current_version or APP_VERSION or "0.0.0").strip()
        channel = str(cfg.get("channel") or "stable").strip().lower()
        if channel not in _VALID_UPDATE_CHANNELS:
            return Result.fail("Update config hatali: channel stable/beta olmalidir.", close_dialog=False)
        include_prerelease = bool(gh.get("include_prerelease"))
        if channel == "beta":
            include_prerelease = True
        if _is_prerelease_version(current):
            include_prerelease = True
        try:
            timeout_sec = _parse_timeout_sec(req)
            retry_count = _parse_retry_count(req)
            retry_backoff_sec = _parse_retry_backoff_sec(req)
        except Exception as exc:
            return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
        if not owner or not repo or not api_base or timeout_sec <= 0:
            return Result.fail("Update config zorunlu alanlari eksik/gecersiz.", close_dialog=False)

        release_res = fetch_latest_release(
            owner=owner,
            repo=repo,
            include_prerelease=include_prerelease,
            api_base=api_base,
            timeout_sec=timeout_sec,
            retry_count=retry_count,
            retry_backoff_sec=retry_backoff_sec,
        )
        if not release_res.success:
            return release_res

        release = (release_res.data or {}).get("release") or {}
        latest_version = _release_version(release)
        if not latest_version:
            return Result.fail("Latest release version could not be parsed.", close_dialog=False)

        available = _is_newer_version(current, latest_version)

        selected_asset: dict[str, Any] | None = None
        if available:
            selected_asset = select_release_asset(release, cfg)
            if not selected_asset:
                return Result.fail("Release found but no suitable update asset is available.", close_dialog=False)

        return Result.ok(
            "Update check completed.",
            close_dialog=False,
            data={
                "enabled": True,
                "available": bool(available),
                "current_version": current,
                "latest_version": latest_version,
                "channel": channel,
                "release": release,
                "selected_asset": selected_asset,
            },
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def _runtime_context() -> tuple[Path, str]:
    if bool(getattr(sys, "frozen", False)):
        exe_path = Path(sys.executable).resolve()
        return exe_path.parent, exe_path.name
    desktop_root = Path(__file__).resolve().parents[2]
    return desktop_root, "OrderScout.exe"


def _download_asset(
    *,
    asset: dict[str, Any],
    target_path: Path,
    timeout_sec: int,
    retry_count: int = 1,
    retry_backoff_sec: float = 0.0,
    expected_sha256: Optional[str] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> Result:
    url = str(asset.get("download_url") or "").strip()
    if not url:
        return Result.fail("Update asset URL is missing.", close_dialog=False)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = target_path.with_name(f"{target_path.name}.part")
    tries = max(1, int(retry_count or 1))
    backoff = max(0.0, float(retry_backoff_sec or 0.0))
    expected = _normalize_sha256_text(expected_sha256)

    for attempt in range(1, tries + 1):
        try:
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                partial_path.unlink(missing_ok=True)
            except Exception:
                pass

            with requests.get(url, stream=True, timeout=max(5, int(timeout_sec))) as response:
                status = int(response.status_code or 0)
                if status >= 400:
                    if (status == 429 or status >= 500) and attempt < tries:
                        raise RuntimeError(f"Retriable asset download error ({status}).")
                    return Result.fail(f"Asset download failed ({status}).", close_dialog=False)

                total_bytes = int(response.headers.get("Content-Length") or 0)
                written = 0
                hasher = hashlib.sha256()
                _emit_progress(progress_callback, "download", written, total_bytes)

                with partial_path.open("wb") as out:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if not chunk:
                            continue
                        out.write(chunk)
                        hasher.update(chunk)
                        written += len(chunk)
                        _emit_progress(progress_callback, "download", written, total_bytes)

            file_sha256 = hasher.hexdigest().lower()
            if expected and file_sha256 != expected:
                try:
                    partial_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return Result.fail(
                    "Downloaded asset SHA256 mismatch. Update package rejected.",
                    close_dialog=False,
                )

            partial_path.replace(target_path)
            return Result.ok(
                "Asset downloaded.",
                close_dialog=False,
                data={"path": str(target_path), "bytes": written, "sha256": file_sha256},
            )
        except Exception as e:
            if attempt >= tries:
                try:
                    partial_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
            if backoff > 0:
                delay = min(15.0, backoff * (2 ** (attempt - 1)))
                _thread_sleep(delay)

    return Result.fail("Asset download failed.", close_dialog=False)


def _resolve_zip_payload_root(extract_dir: Path) -> Path:
    exe_name = "OrderScout.exe"

    if (extract_dir / exe_name).exists():
        return extract_dir

    children = [p for p in extract_dir.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / exe_name).exists():
        return children[0]

    for child in children:
        if (child / exe_name).exists():
            return child

    return extract_dir


def _is_path_within(base_dir: Path, target: Path) -> bool:
    try:
        target.relative_to(base_dir)
        return True
    except ValueError:
        return False


def _resolve_safe_zip_member_path(extract_dir: Path, member_name: str) -> Path:
    normalized = str(member_name or "").replace("\\", "/").strip()
    if not normalized:
        raise RuntimeError("Update package contains an empty ZIP entry.")
    if "\x00" in normalized:
        raise RuntimeError("Update package contains an invalid ZIP entry.")

    base = extract_dir.resolve()
    target = (extract_dir / normalized).resolve()
    if not _is_path_within(base, target):
        raise RuntimeError(f"Unsafe ZIP entry blocked: {normalized}")
    return target


def _write_windows_apply_script(
    *,
    source_dir: Path,
    install_dir: Path,
    backup_dir: Path,
    exe_name: str,
    script_path: Path,
) -> Result:
    try:
        source = str(source_dir.resolve())
        destination = str(install_dir.resolve())
        backup = str(backup_dir.resolve())
        executable = str(exe_name or "OrderScout.exe").strip() or "OrderScout.exe"

        script_body = (
            "@echo off\n"
            "setlocal enableextensions\n"
            f"set \"SRC={source}\"\n"
            f"set \"DST={destination}\"\n"
            f"set \"BKP={backup}\"\n"
            f"set \"EXE={executable}\"\n"
            "echo [OrderScout] waiting for process to exit...\n"
            ":waitloop\n"
            "tasklist /FI \"IMAGENAME eq %EXE%\" 2>NUL | find /I \"%EXE%\" >NUL\n"
            "if %ERRORLEVEL%==0 (\n"
            "  timeout /t 1 /nobreak >NUL\n"
            "  goto waitloop\n"
            ")\n"
            "if exist \"%BKP%\" rmdir /S /Q \"%BKP%\" >NUL 2>NUL\n"
            "mkdir \"%BKP%\" >NUL 2>NUL\n"
            "echo [OrderScout] creating backup...\n"
            "robocopy \"%DST%\" \"%BKP%\" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >NUL\n"
            "if %ERRORLEVEL% GEQ 8 (\n"
            "  echo [OrderScout] backup failed with error %ERRORLEVEL%\n"
            "  exit /b %ERRORLEVEL%\n"
            ")\n"
            "echo [OrderScout] applying update files...\n"
            "robocopy \"%SRC%\" \"%DST%\" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >NUL\n"
            "if %ERRORLEVEL% GEQ 8 (\n"
            "  echo [OrderScout] file copy failed with error %ERRORLEVEL%\n"
            "  echo [OrderScout] rolling back previous version...\n"
            "  robocopy \"%BKP%\" \"%DST%\" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >NUL\n"
            "  if %ERRORLEVEL% GEQ 8 (\n"
            "    echo [OrderScout] rollback failed with error %ERRORLEVEL%\n"
            "    exit /b %ERRORLEVEL%\n"
            "  )\n"
            "  start \"\" \"%DST%\\%EXE%\"\n"
            "  exit /b 0\n"
            ")\n"
            "echo [OrderScout] restarting app...\n"
            "start \"\" \"%DST%\\%EXE%\"\n"
            "exit /b 0\n"
        )

        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script_body, encoding="utf-8")

        return Result.ok(
            "Apply script prepared.",
            close_dialog=False,
            data={"script_path": str(script_path)},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def download_and_prepare_update(
    *,
    release: dict[str, Any],
    asset: dict[str, Any],
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> Result:
    try:
        cfg = load_update_config()
        req = cfg.get("request")
        if not isinstance(req, dict):
            return Result.fail("Update config hatali: request alani yok.", close_dialog=False)
        integrity_cfg = cfg.get("integrity") if isinstance(cfg.get("integrity"), dict) else {}
        require_sha256 = bool(integrity_cfg.get("require_sha256", True))
        try:
            timeout_sec = _parse_timeout_sec(req)
            retry_count = _parse_retry_count(req)
            retry_backoff_sec = _parse_retry_backoff_sec(req)
        except Exception as exc:
            return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)

        latest_version = _release_version(release) or "unknown"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        workspace = UPDATES_ROOT / latest_version / stamp
        download_dir = workspace / "download"

        asset_name = str(asset.get("name") or "update.bin").strip() or "update.bin"
        if asset_name in {".", ".."} or "/" in asset_name or "\\" in asset_name or Path(asset_name).name != asset_name:
            return Result.fail("Release asset name is invalid.", close_dialog=False)
        lower_name = asset_name.lower()
        if lower_name.endswith(".zip"):
            return Result.fail(
                "Portable ZIP update packages are not supported for automatic updates. Publish a signed installer EXE asset.",
                close_dialog=False,
                data={
                    "unsupported_asset_kind": "portable_zip",
                    "asset_name": asset_name,
                    "workspace": str(workspace),
                },
            )
        download_path = download_dir / asset_name
        expected_sha256 = _asset_expected_sha256(asset)
        if require_sha256 and not expected_sha256:
            return Result.fail(
                "Release asset SHA256 bilgisi bulunamadÄ±. GÃ¼venlik nedeniyle indirme durduruldu.",
                close_dialog=False,
            )

        _emit_progress(progress_callback, "prepare", 0, 100)
        dl_res = _download_asset(
            asset=asset,
            target_path=download_path,
            timeout_sec=timeout_sec,
            retry_count=retry_count,
            retry_backoff_sec=retry_backoff_sec,
            expected_sha256=expected_sha256,
            progress_callback=progress_callback,
        )
        if not dl_res.success:
            return dl_res
        dl_data = dl_res.data or {}
        expected_size = int(asset.get("size") or 0)
        actual_size = int(dl_data.get("bytes") or 0)
        if expected_size > 0 and actual_size > 0 and expected_size != actual_size:
            return Result.fail(
                "Downloaded asset size does not match release metadata.",
                close_dialog=False,
            )
        file_sha256 = str(dl_data.get("sha256") or "").strip().lower()

        install_dir, exe_name = _runtime_context()
        current_exe_path = (install_dir / exe_name).resolve()

        if lower_name.endswith(".exe"):
            target_install_dir, target_exe_path = _resolve_version_slot(
                current_install_dir=install_dir,
                release_version=latest_version,
                exe_name=exe_name,
            )
            installer_log = workspace / "installer.log"
            runner_state = workspace / "runner_state.json"
            runner_payload = workspace / "runner_payload.json"
            payload_res = _write_installer_runner_payload(
                installer_path=download_path,
                target_dir=target_install_dir,
                installer_log=installer_log,
                runner_state_path=runner_state,
                target_exe=target_exe_path,
                previous_exe=current_exe_path,
                payload_path=runner_payload,
                release_version=latest_version,
            )
            if not payload_res.success:
                return payload_res
            _emit_progress(progress_callback, "prepare", 100, 100)
            return Result.ok(
                "Installer update package is ready.",
                close_dialog=False,
                data={
                    "plan": {
                        "kind": "installer_exe",
                        "release_version": latest_version,
                        "workspace": str(workspace),
                        "installer_path": str(download_path),
                        "runner_payload": str(runner_payload),
                        "runner_state": str(runner_state),
                        "installer_log": str(installer_log),
                        "current_exe": str(current_exe_path),
                        "target_install_dir": str(target_install_dir),
                        "target_exe": str(target_exe_path),
                        "sha256": file_sha256 or expected_sha256,
                    }
                },
            )

        return Result.fail(f"Unsupported update asset type: {asset_name}", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_update_state() -> dict[str, Any]:
    state = _load_update_state()
    return dict(state or {})


def clear_update_state() -> Result:
    _clear_update_state()
    return Result.ok("Update state cleared.", close_dialog=False)


def mark_update_decision_prompt_shown(*, current_exe: Optional[str] = None) -> Result:
    try:
        state = _load_update_state()
        if not state:
            return Result.fail("Update state bulunamadı.", close_dialog=False)

        cur = str(current_exe or _resolve_runtime_executable_path()).strip()
        target_exe = str(state.get("target_exe") or "").strip()
        if target_exe and Path(target_exe).exists() and not _same_resolved_path(cur, target_exe):
            return Result.fail("Doğrulama sorusu yalnızca yeni sürümden işaretlenebilir.", close_dialog=False)

        now = _state_now_iso()
        state["decision_prompt_shown_at"] = now
        state["updated_at"] = now
        if str(state.get("status") or "").strip().lower() == "pending_install":
            state["status"] = "await_decision"
        _save_update_state(state)
        return Result.ok("Update prompt marker saved.", close_dialog=False, data={"state": state})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def mark_update_target_launch_attempted(*, target_exe: Optional[str] = None) -> Result:
    try:
        state = _load_update_state()
        if not state:
            return Result.fail("Update state bulunamadı.", close_dialog=False)

        expected_target = str(state.get("target_exe") or "").strip()
        actual_target = str(target_exe or expected_target or "").strip()
        if expected_target and actual_target and not _same_resolved_path(expected_target, actual_target):
            return Result.fail("Target exe update state ile eşleşmiyor.", close_dialog=False)

        now = _state_now_iso()
        try:
            launch_attempts = int(state.get("target_launch_attempts") or 0) + 1
        except Exception:
            launch_attempts = 1
        state["target_launch_attempts"] = launch_attempts
        state["target_launch_attempted_at"] = now
        state["updated_at"] = now
        _save_update_state(state)
        return Result.ok("Update target launch marker saved.", close_dialog=False, data={"state": state})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def mark_update_rollback_notice_seen() -> Result:
    try:
        state = _load_update_state()
        if not state:
            return Result.ok("Update rollback notice already cleared.", close_dialog=False)
        state["notify_user"] = False
        state["rollback_notice_seen_at"] = _state_now_iso()
        state["updated_at"] = state["rollback_notice_seen_at"]
        _save_update_state(state)
        return Result.ok("Update rollback notice marked.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def evaluate_update_startup_state(current_exe: Optional[str] = None) -> Result:
    try:
        state = _load_update_state()
        if not state:
            return Result.ok(close_dialog=False, data={"action": "none"})

        cur = str(current_exe or _resolve_runtime_executable_path()).strip()
        target_exe = str(state.get("target_exe") or "").strip()
        from_exe = str(state.get("from_exe") or "").strip()
        status = str(state.get("status") or "").strip().lower()

        if status == "accepted":
            if target_exe and Path(target_exe).exists() and not _same_resolved_path(cur, target_exe):
                return Result.ok(close_dialog=False, data={"action": "redirect", "target_exe": target_exe, "state": state})
            if target_exe and Path(target_exe).exists():
                return Result.ok(close_dialog=False, data={"action": "none", "state": state})
            return Result.ok(close_dialog=False, data={"action": "clear_invalid", "state": state})

        if status in {"pending_install", "await_decision"}:
            if target_exe and Path(target_exe).exists():
                if _same_resolved_path(cur, target_exe):
                    now = _state_now_iso()
                    if status != "await_decision":
                        state["status"] = "await_decision"
                    try:
                        state["target_start_attempts"] = int(state.get("target_start_attempts") or 0) + 1
                    except Exception:
                        state["target_start_attempts"] = 1
                    state["target_started_at"] = now
                    state["updated_at"] = now
                    _save_update_state(state)
                    return Result.ok(close_dialog=False, data={"action": "prompt_decision", "state": state})

                prompt_was_shown = bool(str(state.get("decision_prompt_shown_at") or "").strip())
                try:
                    target_start_attempts = int(state.get("target_start_attempts") or 0)
                except Exception:
                    target_start_attempts = 0
                try:
                    target_launch_attempts = int(state.get("target_launch_attempts") or 0)
                except Exception:
                    target_launch_attempts = 0
                target_was_started = (
                    bool(str(state.get("target_started_at") or "").strip())
                    or bool(str(state.get("target_launch_attempted_at") or "").strip())
                    or target_start_attempts > 0
                    or target_launch_attempts > 0
                )
                if target_was_started and not prompt_was_shown and _same_resolved_path(cur, from_exe):
                    return Result.ok(
                        close_dialog=False,
                        data={
                            "action": "auto_rollback",
                            "reason": _ROLLBACK_REASON_PROMPT_NOT_REACHED,
                            "target_exe": target_exe,
                            "state": state,
                        },
                    )
                return Result.ok(close_dialog=False, data={"action": "redirect", "target_exe": target_exe, "state": state})
            if from_exe and Path(from_exe).exists() and not _same_resolved_path(cur, from_exe):
                return Result.ok(close_dialog=False, data={"action": "redirect", "target_exe": from_exe, "state": state})
            return Result.ok(close_dialog=False, data={"action": "clear_invalid", "state": state})

        if status == "rolled_back":
            if bool(state.get("notify_user")):
                if not from_exe or _same_resolved_path(cur, from_exe) or not Path(from_exe).exists():
                    return Result.ok(close_dialog=False, data={"action": "notify_rollback", "state": state})
            return Result.ok(close_dialog=False, data={"action": "clear_invalid", "state": state})

        return Result.ok(close_dialog=False, data={"action": "none", "state": state})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def accept_installed_update(*, current_exe: Optional[str] = None, cleanup_previous: bool = False) -> Result:
    try:
        state = _load_update_state()
        if not state:
            return Result.fail("Update state bulunamadÄ±.", close_dialog=False)

        cur = str(current_exe or _resolve_runtime_executable_path()).strip()
        target_exe = str(state.get("target_exe") or "").strip()
        from_exe = str(state.get("from_exe") or "").strip()
        if target_exe and Path(target_exe).exists() and not _same_resolved_path(cur, target_exe):
            return Result.fail("Onay işlemi yalnızca yeni sürümden yapılabilir.", close_dialog=False)

        state["status"] = "accepted"
        state["updated_at"] = _state_now_iso()
        _save_update_state(state)

        removed_previous = False
        if cleanup_previous and from_exe:
            removed_previous, _removed_items = _cleanup_previous_install_payload(
                from_exe=from_exe,
                target_exe=target_exe or cur,
            )

        return Result.ok(
            "Update accepted.",
            close_dialog=False,
            data={"accepted_exe": target_exe or cur, "removed_previous": removed_previous},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def rollback_installed_update(
    *,
    current_exe: Optional[str] = None,
    reason: str = "",
    notify_user: bool = False,
    exit_code: Optional[int] = None,
) -> Result:
    try:
        state = _load_update_state()
        if not state:
            return Result.fail("Update state bulunamadÄ±.", close_dialog=False)
        cur = str(current_exe or _resolve_runtime_executable_path()).strip()
        from_exe = str(state.get("from_exe") or "").strip()
        target_exe = str(state.get("target_exe") or "").strip()
        if not from_exe or not Path(from_exe).exists():
            _clear_update_state()
            return Result.fail("Geri dönülecek önceki sürüm bulunamadı.", close_dialog=False)

        now = _state_now_iso()
        state["status"] = "rolled_back"
        state["updated_at"] = now
        state["rolled_back_at"] = now
        clean_reason = str(reason or "").strip()
        if clean_reason:
            state["rollback_reason"] = clean_reason
        if notify_user:
            state["notify_user"] = True
        if exit_code is not None:
            try:
                state["failed_target_exit_code"] = int(exit_code)
            except Exception:
                state["failed_target_exit_code"] = str(exit_code)
        _save_update_state(state)

        remove_target = False
        try:
            if target_exe:
                tdir = Path(target_exe).resolve().parent
                if tdir.exists() and tdir.name.lower().startswith(_VERSION_DIR_PREFIX):
                    remove_target = True
                    shutil.rmtree(tdir, ignore_errors=False)
        except Exception:
            remove_target = False

        return Result.ok(
            "Rollback requested.",
            close_dialog=False,
            data={"rollback_exe": from_exe, "current_exe": cur, "removed_target": remove_target},
        )
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def is_runtime_updatable(config: Optional[dict[str, Any]] = None) -> bool:
    if os.name != "nt":
        return False
    if bool(getattr(sys, "frozen", False)):
        return True
    try:
        return _allow_non_frozen_apply(config=config)
    except Exception:
        return False


def launch_prepared_update(plan: dict[str, Any]) -> Result:
    try:
        kind = str((plan or {}).get("kind") or "").strip().lower()
        if kind not in {"portable_zip", "installer_exe"}:
            return Result.fail("Invalid update plan.", close_dialog=False)

        if os.name != "nt":
            return Result.fail("Auto update apply is only available on Windows runtime.", close_dialog=False)

        if kind == "portable_zip":
            return Result.fail(
                "Portable ZIP update plans are disabled because they cannot be startup-verified.",
                close_dialog=False,
                data={"unsupported_asset_kind": "portable_zip"},
            )

        installer_path_text = str(plan.get("installer_path") or "").strip()
        runner_payload_text = str(plan.get("runner_payload") or "").strip()
        installer_path = Path(installer_path_text) if installer_path_text else None
        runner_payload = Path(runner_payload_text) if runner_payload_text else None
        runner_state_text = str(plan.get("runner_state") or "").strip()
        runner_state = Path(runner_state_text) if runner_state_text else None
        target_exe = str(plan.get("target_exe") or "").strip()
        target_install_dir = str(plan.get("target_install_dir") or "").strip()
        current_exe = str(plan.get("current_exe") or "").strip() or str(_resolve_runtime_executable_path())
        release_version = str(plan.get("release_version") or "").strip()
        workspace = str(plan.get("workspace") or "").strip()
        if installer_path is None:
            return Result.fail("Installer file path is missing.", close_dialog=False)
        if runner_payload is None:
            return Result.fail("Installer runner payload path is missing.", close_dialog=False)
        if not installer_path.is_file():
            return Result.fail("Installer file is missing.", close_dialog=False)
        if not runner_payload.is_file():
            return Result.fail("Installer runner payload is missing.", close_dialog=False)
        if runner_state is None:
            return Result.fail("Installer runner state path is missing.", close_dialog=False)
        if not target_exe or not target_install_dir or not current_exe or not release_version or not workspace:
            return Result.fail("Installer update plan is incomplete.", close_dialog=False)
        if not Path(current_exe).is_file():
            return Result.fail("Current executable is missing; rollback would be unsafe.", close_dialog=False)

        _begin_installer_update_state(
            release_version=release_version,
            workspace=workspace,
            from_exe=current_exe,
            target_exe=target_exe,
        )

        try:
            runner_state.unlink(missing_ok=True)
        except Exception:
            pass

        runner_cmd = _build_installer_runner_command(
            current_exe=current_exe,
            runner_payload=runner_payload,
        )

        try:
            runner_proc = subprocess.Popen(
                runner_cmd,
                close_fds=True,
            )
        except Exception as e:
            _clear_update_state()
            return Result.fail(
                f"Installer runner başlatılamadı: {map_error_to_message(e)}",
                error=e,
                close_dialog=False,
            )

        if _wait_for_runner_ready(runner_state, timeout_sec=6.0):
            return Result.ok(
                "Installer runner launched.",
                close_dialog=False,
                data={"mode": "runner_ui"},
            )

        try:
            runner_alive = runner_proc.poll() is None
        except Exception:
            runner_alive = False
        if runner_alive:
            return Result.ok(
                "Installer runner launched but readiness has not been confirmed yet.",
                close_dialog=False,
                data={
                    "mode": "runner_ui_pending",
                    "runner_state": str(runner_state),
                    "installer_path": str(installer_path),
                    "target_install_dir": target_install_dir,
                },
            )

        _clear_update_state()

        return Result.fail(
            "Installer runner doğrulanamadı.",
            close_dialog=False,
            data={
                "runner_state": str(runner_state),
                "installer_path": str(installer_path),
                "target_install_dir": target_install_dir,
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
