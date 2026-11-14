"""Exercise the frozen desktop and its worker executables on synthetic data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch


def _wait_until(app, predicate, description: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise RuntimeError(description)


def _require(condition, description: str) -> None:
    if not condition:
        raise RuntimeError(description)


def _exercise_bundle(isolated: str) -> dict:
    from PyQt6.QtWidgets import QApplication
    from AI.processors.local_runtime import find_bundled_llama_server
    from AI.processors.manual_capabilities import list_manual_capabilities
    from AI.processors import tools
    from AI.runtime.provider_response import ProviderText
    from AI.views import chat_tab
    from Core.db.bootstrap import init_database
    from Core.db.migration_runner import discover_domain_migrations
    from Core.process.process_runner import GenericProcessRunner, ProcessTarget
    from Core.utils.model_utils import clear_engine_cache
    from Feedback.processors.pipeline import Result
    from Finance.processors.rule_loader import build_finance_rule_handler_map
    from Main_interface.views.views import MainInterface
    from Testing.processors.business_agent_fixtures import seed_business_fixture
    from settings import APP_VERSION, ASSETS_DIR, DB_NAME

    app = QApplication([sys.argv[0]])
    init_database()
    migrations = discover_domain_migrations()
    _require({"orders", "finance", "stock", "listing"} <= {m.domain for m in migrations},
             "Packaged database migrations are missing.")
    _require((ASSETS_DIR / "orderscout-ai-v2.png").is_file(), "Packaged AI icon is missing.")
    _require(build_finance_rule_handler_map(), "Packaged finance rules are missing.")
    _require(list_manual_capabilities(), "Packaged action sources are missing.")
    fixture = seed_business_fixture(DB_NAME, isolation_root=isolated)
    scope = fixture["orders"]["primary_account_id"]
    result = tools.orders_summary(period="all", api_account_ids=[scope])
    count = (result.data or {}).get("total_orders")
    _require(result.success and count == fixture["orders"]["total"], "Wrong synthetic order count.")

    runtime_path = find_bundled_llama_server()
    _require(runtime_path, "Packaged local model runtime is missing.")
    runtime = subprocess.run([runtime_path, "--version"], capture_output=True,
                             timeout=20, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _require(b"version:" in runtime.stdout + runtime.stderr, "Local runtime version failed.")

    workers = []
    for domain in ("Orders", "Listing"):
        completed = []
        runner = GenericProcessRunner(ProcessTarget(f"{domain}/processors/trendyol/db_save_worker.py"))
        runner.finished.connect(completed.append)
        runner.start()
        runner.send_json({}, close_stdin=True)
        try:
            _wait_until(app, lambda: bool(completed), f"{domain} worker did not return JSON.")
            _require(completed[0]["success"], f"{domain} worker failed: {completed[0]['message']}")
        finally:
            runner.terminate()
        workers.append(domain)

    class RecordedModel:
        runtime_name = "release_test"
        model_name = "release-test-model"
        resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}

        def invoke_tools(self, prompt, *, tools):
            names = {tool["name"] for tool in tools}
            if "orders.summary" not in names:
                return json.dumps({"mode": "tool", "tool": "operations.discover",
                                   "arguments": {"query": "orders.summary", "limit": 1}})
            if re.search(r'"total_orders"\s*:\s*5\b', prompt):
                return ProviderText("Pilot Ana mağazasında 5 sipariş var.")
            return json.dumps({"mode": "tool", "tool": "orders.summary",
                               "arguments": {"period": "all", "api_account_ids": [scope]}})

    window = MainInterface(defer_startup=True)
    tab = None
    try:
        _require(window.ai_toolbar_action is not None, "Release has AI disabled.")
        window.show()
        for key in ("orders", "stock", "listing", "marketplaces", "finance", "logistics", "ai"):
            host = window._tab_hosts[key]
            window.tabs.setCurrentWidget(host)
            host.request_load()
            _wait_until(app, host.is_loaded, f"Packaged tab failed: {key}")
        tab = window._tab_hosts["ai"].content
        tab.source_combo.blockSignals(True)
        tab.source_combo.setCurrentIndex(tab.source_combo.findData("cloud"))
        tab.source_combo.blockSignals(False)
        provider = {"id": 1, "provider_code": "test", "default_model": RecordedModel.model_name}
        with patch.object(tab, "_selected_provider_record", return_value=provider), patch.object(
            chat_tab.ai_actions, "action_get_provider_account",
            return_value=Result.ok("Loaded", data={"record": provider}),
        ), patch.object(chat_tab, "build_provider_chat_client", return_value=RecordedModel()):
            tab.composer.setPlainText("Pilot Ana mağazasının toplam sipariş sayısı kaç?")
            tab._send_message()
            _wait_until(app, lambda: tab._chat_worker is None, "Packaged AI chat timed out.")
        _require(tab._last_chat_success and "mağazasında 5 sipariş var." in tab.transcript.toPlainText(),
                 "Packaged AI chat failed to answer using its order tool.")
    finally:
        if tab is not None:
            tab.close()
        window.close()
        app.processEvents()
        clear_engine_cache()
    return {"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
            "migration_count": len(migrations), "tabs": list(window._tab_hosts),
            "workers": workers, "orders_answer": count, "local_runtime": Path(runtime_path).name}


def run(output_directory: str) -> None:
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = output / "smoke.json"
    with tempfile.TemporaryDirectory(prefix="orderscout-release-smoke-", ignore_cleanup_errors=True) as isolated:
        try:
            os.environ.update(LOCALAPPDATA=isolated, XDG_DATA_HOME=isolated, QT_QPA_PLATFORM="offscreen",
                              ORDERSCOUT_CREDENTIAL_STORE_PATH=str(Path(isolated) / "credentials.json"))
            for name in ("ENABLE_AI_UI", "ENABLE_TEST_LAB_UI", "ORDER_SCOUT_VERSION", "ORDERSCOUT_LLAMA_SERVER"):
                os.environ.pop(name, None)
            payload = _exercise_bundle(isolated)
            report.write_text(json.dumps({"passed": True, **payload}, indent=2), encoding="utf-8")
        except Exception:
            import traceback

            report.write_text(json.dumps({"passed": False, "error": traceback.format_exc()}), encoding="utf-8")
            raise SystemExit(1) from None
