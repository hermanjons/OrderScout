from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Feedback.processors.pipeline import Result, map_error_to_message
from settings import DB_NAME


STOCK_GOAL = "Stok operasyonunu toparla"
EXPECTED_STEPS = (
    "stock.inventory_overview",
    "stock.low_stock",
    "stock.zero_or_negative_count",
)


def validate_domain_runtime_source_app_artifact(payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if payload.get("schema") != "orderscout-domain-runtime-source-app-acceptance-v1":
        problems.append("schema")
    if payload.get("valid") is not True:
        problems.append("valid")
    if payload.get("source_entrypoint") != "desktop/main.py":
        problems.append("source_entrypoint")
    if payload.get("ui_mode") != "full_source_app" or payload.get("render_mode") != "offscreen":
        problems.append("source_ui_mode")
    if payload.get("source_surface_constructed") is not True:
        problems.append("source_surface_constructed")
    if not str(payload.get("source_window_runtime_class") or "").endswith(".MainInterface"):
        problems.append("source_window_runtime_class")
    if not str(payload.get("source_widget_runtime_class") or "").endswith(".AITab"):
        problems.append("source_widget_runtime_class")
    if payload.get("real_source_db") is not True or payload.get("database") != Path(DB_NAME).name:
        problems.append("real_source_db")
    if payload.get("planner_kind") != "synthetic_allowlisted_planner" or payload.get("planner_is_model_evidence") is not False:
        problems.append("planner_classification")
    if payload.get("active_domain") != "stock" or payload.get("task_status") != "complete":
        problems.append("task_state")
    steps = [dict(row) for row in list(payload.get("steps") or []) if isinstance(row, dict)]
    if [row.get("step_id") for row in steps] != list(EXPECTED_STEPS):
        problems.append("step_ids")
    if not steps or not all(
        row.get("status") == "completed"
        and row.get("exact_tool_binding") is True
        and row.get("tool_names") == [row.get("step_id")]
        for row in steps
    ):
        problems.append("exact_tool_binding")
    return problems


def _synthetic_planner(prompt: str) -> str:
    text = str(prompt or "")
    if "stock domain agent task plani" in text:
        return json.dumps({"steps": [{"id": step_id} for step_id in EXPECTED_STEPS]})
    if "Stok envanterinin genel durumunu getir" in text:
        return '{"mode":"tool","tool":"stock.inventory_overview","arguments":{}}'
    if "Dusuk stoklu urunleri listele" in text:
        return '{"mode":"tool","tool":"stock.low_stock","arguments":{"limit":20}}'
    if "Sifir veya negatif stoklu urun sayisini getir" in text:
        return '{"mode":"tool","tool":"stock.zero_or_negative_count","arguments":{}}'
    if "task final cevabi" in text.casefold():
        return "Stock task adimlari real source DB uzerinde tamamlandi."
    return '{"mode":"answer","response":"Stock source-app acceptance adimi tamamlandi."}'


setattr(_synthetic_planner, "runtime_name", "source_app_acceptance_planner")
setattr(_synthetic_planner, "model_name", "synthetic-planner-not-model-evidence")
setattr(
    _synthetic_planner,
    "resource_plan",
    {
        "requested_model": "synthetic-planner-not-model-evidence",
        "actual_model": "synthetic-planner-not-model-evidence",
        "fallback_allowed": False,
        "fallback_used": False,
    },
)


def evaluate_domain_runtime_source_app(*, db_name: str = DB_NAME, timeout: float = 120.0) -> Result:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = None
    source_window = None
    tab = None
    try:
        from PyQt6.QtWidgets import QApplication

        from AI.processors.orders_source_ui_human_recheck_cli import (
            _ensure_provider_selection,
            _wait_for_workers,
        )
        from AI.views import chat_tab as chat_module
        from main import build_source_app_ai_acceptance_surface

        app = QApplication.instance() or QApplication([])
        source_window, tab = build_source_app_ai_acceptance_surface(app)
        app.processEvents()
        capture: dict[str, Any] = {}
        original_turn_runner = chat_module._run_chat_turn_with_runtime
        original_get_provider = chat_module.ai_actions.action_get_provider_account
        original_build_client = chat_module.build_provider_chat_client

        def capture_turn_runner(*args: Any, **kwargs: Any) -> Result:
            result = original_turn_runner(*args, **kwargs)
            capture["result"] = result
            return result

        def fake_provider(_provider_id: int) -> Result:
            return Result.ok(
                "Source-app acceptance provider hazir.",
                close_dialog=False,
                data={
                    "record": {
                        "id": 999_001,
                        "label": "Source App Acceptance Planner",
                        "provider_code": "acceptance",
                        "default_model": "synthetic-planner-not-model-evidence",
                        "is_enabled": True,
                        "allow_model_fallback": False,
                    }
                },
            )

        chat_module._run_chat_turn_with_runtime = capture_turn_runner
        chat_module.ai_actions.action_get_provider_account = fake_provider
        chat_module.build_provider_chat_client = lambda _record: _synthetic_planner
        try:
            _ensure_provider_selection(
                tab,
                provider_id=999_001,
                provider_label="Source App Acceptance Planner",
                provider_code="acceptance",
                model="synthetic-planner-not-model-evidence",
            )
            tab.composer.setPlainText(STOCK_GOAL)
            tab._send_message()
            _wait_for_workers(tab, app, timeout=timeout)
        finally:
            chat_module._run_chat_turn_with_runtime = original_turn_runner
            chat_module.ai_actions.action_get_provider_account = original_get_provider
            chat_module.build_provider_chat_client = original_build_client

        result = capture.get("result")
        if not isinstance(result, Result):
            return Result.fail("Source-app task sonucu yakalanamadi.", close_dialog=False)
        data = dict(result.data or {})
        state = dict(data.get("state") or {}) if isinstance(data.get("state"), dict) else {}
        completed = [dict(row) for row in list(state.get("completed_steps") or []) if isinstance(row, dict)]
        steps = [
            {
                "step_id": str(row.get("step_id") or ""),
                "status": str(row.get("status") or ""),
                "tool_names": list(row.get("tool_names") or []),
                "exact_tool_binding": list(row.get("tool_names") or []) == [str(row.get("step_id") or "")],
            }
            for row in completed
        ]
        valid = bool(
            result.success
            and state.get("active_domain") == "stock"
            and state.get("status") == "complete"
            and [row["step_id"] for row in steps] == list(EXPECTED_STEPS)
            and all(row["status"] == "completed" and row["exact_tool_binding"] for row in steps)
        )
        artifact = {
            "schema": "orderscout-domain-runtime-source-app-acceptance-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_entrypoint": "desktop/main.py",
            "ui_mode": "full_source_app",
            "render_mode": os.environ.get("QT_QPA_PLATFORM") or "offscreen",
            "source_surface_constructed": True,
            "source_window_runtime_class": f"{type(source_window).__module__}.{type(source_window).__name__}",
            "source_widget_runtime_class": f"{type(tab).__module__}.{type(tab).__name__}",
            "database": Path(db_name).name,
            "real_source_db": Path(db_name).exists(),
            "planner_kind": "synthetic_allowlisted_planner",
            "planner_is_model_evidence": False,
            "goal": STOCK_GOAL,
            "active_domain": state.get("active_domain"),
            "task_status": state.get("status"),
            "steps": steps,
            "valid": valid,
        }
        artifact["validation_problems"] = validate_domain_runtime_source_app_artifact(artifact)
        artifact["valid"] = not artifact["validation_problems"]
        if artifact["valid"]:
            return Result.ok("Domain runtime full source-app acceptance gecti.", close_dialog=False, data=artifact)
        return Result.fail("Domain runtime full source-app acceptance tamamlanmadi.", close_dialog=False, data=artifact)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
    finally:
        if tab is not None:
            tab.close()
            tab.deleteLater()
        if source_window is not None:
            source_window.close()
            source_window.deleteLater()
        if app is not None:
            app.processEvents()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stock task runtime through the offscreen source app and real DB.")
    parser.add_argument("--db-name", default=DB_NAME)
    parser.add_argument("--output", default="")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    result = evaluate_domain_runtime_source_app(db_name=str(args.db_name or DB_NAME), timeout=args.timeout)
    payload = {"success": result.success, "message": result.message, "data": result.data or {}}
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "\n", encoding="utf-8")
    print(body)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
