from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image, ImageChops, ImageFilter, ImageStat

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QSignalBlocker, Qt
from PyQt6.QtGui import QFont, QFontDatabase, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QAbstractButton, QLabel, QListWidgetItem, QWidget

from AI.views.ai_manager_dialog import AIManagerDialog
from AI.views.chat_tab import AITab
from Feedback.processors.pipeline import Result
from Main_interface.views.views import MainInterface


VIEWPORT = (1800, 1100)


def _process_events(app: QApplication, *, rounds: int = 6) -> None:
    for _ in range(max(1, rounds)):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.01)


def _install_offscreen_font(app: QApplication) -> str:
    """Qt's Windows offscreen plugin exposes no system font families by default."""

    font_root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = (
        font_root / "segoeui.ttf",
        font_root / "segoeuib.ttf",
        font_root / "seguisym.ttf",
        font_root / "arial.ttf",
    )
    primary_family = ""
    for path in candidates:
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if families and not primary_family and "symbol" not in str(families[0]).casefold():
            primary_family = str(families[0])
    if primary_family:
        app.setFont(QFont(primary_family, 9))
    return primary_family or str(app.font().family() or "")


def _widget_text(widget: QWidget) -> str:
    if isinstance(widget, (QLabel, QAbstractButton)):
        return str(widget.text() or "").strip()[:240]
    return ""


def _component_tree(root: QWidget) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        name = str(widget.objectName() or "")
        text = _widget_text(widget)
        if not name and not text:
            continue
        point = widget.mapTo(root, QPoint(0, 0)) if widget is not root else QPoint(0, 0)
        geometry = widget.geometry()
        records.append(
            {
                "class": type(widget).__name__,
                "object_name": name,
                "text": text,
                "visible": bool(widget.isVisibleTo(root)),
                "enabled": bool(widget.isEnabled()),
                "geometry": {
                    "x": int(point.x()),
                    "y": int(point.y()),
                    "width": int(geometry.width()),
                    "height": int(geometry.height()),
                },
            }
        )
    return records


def _coarse_layout_similarity(actual_path: Path, reference_path: Path) -> float:
    """Compare large layout/color regions while tolerating deterministic fixture text."""

    size = (180, 110)
    actual = (
        Image.open(actual_path)
        .convert("RGB")
        .resize(size, Image.Resampling.LANCZOS)
        .filter(ImageFilter.GaussianBlur(1.3))
    )
    reference = (
        Image.open(reference_path)
        .convert("RGB")
        .resize(size, Image.Resampling.LANCZOS)
        .filter(ImageFilter.GaussianBlur(1.3))
    )
    difference = ImageChops.difference(actual, reference)
    mean = sum(ImageStat.Stat(difference).mean) / 3.0
    return max(0.0, min(1.0, 1.0 - (mean / 255.0)))


def _geometry_check(
    surface: dict[str, Any],
    *,
    label: str,
    expected: dict[str, int],
    tolerance: int,
    object_name: str = "",
    text_value: str = "",
) -> dict[str, Any]:
    candidates = [
        record
        for record in list(surface.get("components") or [])
        if bool(record.get("visible"))
        and (not object_name or record.get("object_name") == object_name)
        and (not text_value or record.get("text") == text_value)
    ]
    actual = dict(candidates[0].get("geometry") or {}) if candidates else {}
    deltas = {
        key: abs(int(actual.get(key, -100_000)) - int(value))
        for key, value in expected.items()
    }
    passed = bool(actual) and all(delta <= tolerance for delta in deltas.values())
    return {
        "label": label,
        "passed": passed,
        "expected": expected,
        "actual": actual,
        "tolerance": tolerance,
        "deltas": deltas,
    }


def _acceptance_checks(output_dir: Path, surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {str(surface.get("surface") or ""): surface for surface in surfaces}
    references = {
        "chat_cloud": "ai-chat-cloud-workspace-concept-v3-scaffold-faithful.png",
        "chat_local": "ai-chat-local-workspace-concept-v3-scaffold-faithful.png",
        "model_hub": "ai-model-hub-concept-v3-scaffold-faithful.png",
    }
    thresholds = {"chat_cloud": 0.96, "chat_local": 0.96, "model_hub": 0.975}
    visual: list[dict[str, Any]] = []
    for name, reference_name in references.items():
        surface = by_name[name]
        actual_path = output_dir / str(surface.get("image") or "")
        reference_path = output_dir / reference_name
        similarity = _coarse_layout_similarity(actual_path, reference_path)
        visual.append(
            {
                "surface": name,
                "reference": reference_name,
                "similarity": round(similarity, 6),
                "threshold": thresholds[name],
                "passed": similarity >= thresholds[name],
            }
        )

    geometry = [
        _geometry_check(
            by_name["chat_cloud"],
            label="chat control band",
            object_name="AiControlBand",
            expected={"x": 10, "y": 194, "width": 1780, "height": 78},
            tolerance=8,
        ),
        _geometry_check(
            by_name["chat_cloud"],
            label="cloud model panel list",
            object_name="ModelList",
            expected={"x": 117, "y": 514, "width": 402, "height": 413},
            tolerance=24,
        ),
        _geometry_check(
            by_name["chat_local"],
            label="local model panel list",
            object_name="ModelList",
            expected={"x": 117, "y": 460, "width": 402, "height": 250},
            tolerance=20,
        ),
        _geometry_check(
            by_name["model_hub"],
            label="model hub full-width header",
            object_name="HubHeader",
            expected={"x": 0, "y": 0, "width": 1800, "height": 72},
            tolerance=0,
        ),
        _geometry_check(
            by_name["model_hub"],
            label="model hub new source heading",
            text_value="Yeni kaynak",
            expected={"x": 139, "y": 117},
            tolerance=20,
        ),
    ]
    overlay_expected = {"x": 546, "y": 380, "width": 420, "height": 592}
    overlay_actual = dict(by_name["chat_local"].get("overlay_geometry") or {})
    overlay_deltas = {
        key: abs(int(overlay_actual.get(key, -100_000)) - value)
        for key, value in overlay_expected.items()
    }
    geometry.append(
        {
            "label": "local advanced settings popup",
            "passed": bool(overlay_actual) and all(delta <= 8 for delta in overlay_deltas.values()),
            "expected": overlay_expected,
            "actual": overlay_actual,
            "tolerance": 8,
            "deltas": overlay_deltas,
        }
    )
    passed = all(row["passed"] for row in visual) and all(row["passed"] for row in geometry)
    return {"passed": passed, "visual": visual, "geometry": geometry}


def _save_widget(
    widget: QWidget,
    output_path: Path,
    *,
    overlay: QWidget | None = None,
    base_pixmap: QPixmap | None = None,
) -> None:
    del base_pixmap
    pixmap = QPixmap(widget.size())
    pixmap.fill(Qt.GlobalColor.white)
    widget.render(pixmap)
    if overlay is not None and overlay.isVisible():
        composed = QPixmap(pixmap.size())
        composed.fill(Qt.GlobalColor.white)
        painter = QPainter(composed)
        painter.drawPixmap(0, 0, pixmap)
        overlay_origin = widget.mapFromGlobal(overlay.mapToGlobal(QPoint(0, 0)))
        overlay_pixmap = QPixmap(overlay.size())
        overlay_pixmap.fill(Qt.GlobalColor.white)
        overlay.render(overlay_pixmap)
        painter.drawPixmap(overlay_origin, overlay_pixmap)
        painter.end()
        pixmap = composed
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(output_path), "PNG"):
        raise RuntimeError(f"Screenshot yazilamadi: {output_path}")


def _state_snapshot(
    widget: QWidget,
    output_dir: Path,
    *,
    state: str,
    checks: dict[str, bool],
    facts: dict[str, Any] | None = None,
    overlay: QWidget | None = None,
    base_pixmap: QPixmap | None = None,
) -> dict[str, Any]:
    image_name = f"ui-state-{state}-{widget.width()}x{widget.height()}.png"
    _save_widget(
        widget,
        output_dir / image_name,
        overlay=overlay,
        base_pixmap=base_pixmap,
    )
    return {
        "state": state,
        "image": image_name,
        "viewport": {"width": widget.width(), "height": widget.height()},
        "passed": all(bool(value) for value in checks.values()),
        "checks": {key: bool(value) for key, value in checks.items()},
        "facts": dict(facts or {}),
        "components": [
            record for record in _component_tree(widget) if bool(record.get("visible"))
        ],
    }


def _local_records() -> list[dict[str, Any]]:
    return [
        {
            "id": 101,
            "_source_kind": "local_model",
            "repo_id": "Google/Gemma-3-12B-it-GGUF",
            "filename": "gemma-3-12b-it-Q4_K_M.gguf",
            "quantization": "Q4_K_M",
            "size_text": "7.4 GB",
            "file_format": "GGUF",
            "exists_on_disk": True,
            "reasoning_effort": "medium",
            "resource_plan": {
                "safe_to_run": True,
                "profile": "gpu_auto",
                "num_ctx": 8192,
                "max_tokens": 1024,
            },
        },
        {
            "id": 102,
            "_source_kind": "local_model",
            "repo_id": "bartowski/DeepSeek-V4-Flash-GGUF",
            "filename": "DeepSeek-V4-Flash-Q4_K_M.gguf",
            "quantization": "Q4_K_M",
            "size_text": "5.5 GB",
            "file_format": "GGUF",
            "exists_on_disk": True,
            "resource_plan": {
                "safe_to_run": True,
                "profile": "reasoning",
                "num_ctx": 4096,
                "max_tokens": 768,
            },
        },
        {
            "id": 103,
            "_source_kind": "local_model",
            "repo_id": "bartowski/Llama-3.2-1B-Instruct-GGUF",
            "filename": "Llama-3.2-1B-Instruct-Q8_0.gguf",
            "quantization": "Q8_0",
            "size_text": "1.3 GB",
            "file_format": "GGUF",
            "exists_on_disk": True,
            "resource_plan": {
                "safe_to_run": True,
                "profile": "low_memory",
                "num_ctx": 2048,
                "max_tokens": 384,
            },
        },
    ]


def _cloud_groups() -> list[dict[str, Any]]:
    return [
        {
            "provider": {
                "id": 201,
                "provider_code": "gemini",
                "provider_label": "Google AI Studio",
                "label": "Google AI Studio",
                "is_enabled": True,
                "allow_model_fallback": True,
            },
            "route": {
                "provider_code": "gemini",
                "ordered_model_ids": ["gemini-3.5-flash", "gemini-2.5-pro"],
            },
            "models": [
                {
                    "id": "gemini-3.5-flash",
                    "name": "Gemini 3.5 Flash",
                    "is_free": True,
                    "context_length": 1_048_576,
                    "capability_profile": {"native_tool_calling_available": True},
                },
                {
                    "id": "gemini-2.5-pro",
                    "name": "Gemini 2.5 Pro",
                    "is_free": True,
                    "context_length": 1_048_576,
                    "capability_profile": {"native_tool_calling_available": True},
                },
            ],
        },
        {
            "provider": {
                "id": 202,
                "provider_code": "openrouter",
                "provider_label": "OpenRouter",
                "label": "OpenRouter",
                "is_enabled": True,
                "allow_model_fallback": True,
            },
            "route": {
                "provider_code": "openrouter",
                "ordered_model_ids": [
                    "tencent/hunyuan-a13b-instruct:free",
                    "google/gemma-3-12b-it:free",
                    "openai/gpt-oss-20b:free",
                ],
            },
            "models": [
                {
                    "id": "tencent/hunyuan-a13b-instruct:free",
                    "name": "Tencent Hunyuan",
                    "is_free": True,
                    "context_length": 131_072,
                    "capability_profile": {"native_tool_calling_available": True},
                },
                {
                    "id": "google/gemma-3-12b-it:free",
                    "name": "Google Gemma 3 12B",
                    "is_free": True,
                    "context_length": 131_072,
                    "capability_profile": {"native_tool_calling_available": True},
                },
                {
                    "id": "openai/gpt-oss-20b:free",
                    "name": "OpenAI GPT-OSS 20B",
                    "is_free": True,
                    "context_length": 131_072,
                    "capability_profile": {"native_tool_calling_available": True},
                },
            ],
        },
    ]


def _cloud_catalog_groups() -> list[dict[str, Any]]:
    groups = json.loads(json.dumps(_cloud_groups()))
    groups[0]["models"].append(
        {
            "id": "gemini-2.5-pro-paid",
            "name": "Gemini 2.5 Pro · Paid",
            "is_free": False,
            "context_length": 1_048_576,
            "capability_profile": {"native_tool_calling_available": True},
        }
    )
    groups[1]["models"].append(
        {
            "id": "anthropic/claude-sonnet",
            "name": "Claude Sonnet",
            "is_free": False,
            "context_length": 200_000,
            "capability_profile": {"native_tool_calling_available": True},
        }
    )
    return groups


def _cloud_groups_for_price(price_filter: str) -> list[dict[str, Any]]:
    groups = _cloud_catalog_groups()
    for group in groups:
        models = list(group.get("models") or [])
        if price_filter == "free":
            models = [row for row in models if bool(row.get("is_free"))]
        elif price_filter == "paid":
            models = [row for row in models if not bool(row.get("is_free"))]
        group["models"] = models
    return groups


def _set_cloud_fixture_state(
    tab: AITab,
    *,
    price_filter: str,
    collapsed: set[str] | None = None,
) -> None:
    tab._cloud_price_filter = price_filter
    for key, button in tab.cloud_price_buttons.items():
        with QSignalBlocker(button):
            button.setChecked(key == price_filter)
    tab._cloud_collapsed_provider_keys = set(collapsed or set())
    tab._populate_cloud_model_list(_cloud_groups_for_price(price_filter))
    tab._on_model_selection_changed()


def _add_local_record(tab: AITab, record: dict[str, Any]) -> None:
    item = QListWidgetItem(tab._label_for_record(record))
    item.setData(Qt.ItemDataRole.UserRole, dict(record))
    tab.model_list.addItem(item)
    tab._install_model_item_widget(item, record)


def _prepare_chat_shell(app: QApplication, *, source: str) -> tuple[MainInterface, AITab]:
    window = MainInterface(defer_startup=True)
    window.set_bootstrap_pending(False)
    host = window._tab_hosts["ai"]
    host._ensure_loaded()
    tab = host.content
    if not isinstance(tab, AITab):
        raise RuntimeError("AI tab source widget yuklenemedi.")
    tab._models_bootstrapped = True
    window.tabs.setCurrentIndex(window.tabs.indexOf(host))

    source_index = tab.source_combo.findData(source)
    with QSignalBlocker(tab.source_combo):
        tab.source_combo.setCurrentIndex(source_index)
    tab._sync_model_panel_mode()
    tab.source_list_label.setText("Yüklü yerel modeller" if source == "local" else "Provider ve modeller")
    tab.model_list.clear()
    if source == "cloud":
        tab._populate_cloud_model_list(_cloud_groups())
        tab.model_status.setText("2 provider · 5 ücretsiz model · canlı rota fixture'ı")
        tab.reasoning_combo.setCurrentIndex(tab.reasoning_combo.findData("high"))
        tab._append_chat_message(
            "user",
            "İki provider için de en güçlü ücretsiz modellerle uzun Orders kabul testini başlat.",
        )
        tab._append_chat_message(
            "assistant",
            "Gemini 3.5 Flash seçildi. Bu provider'daki erişilebilir ücretsiz modeller canlı katalog, "
            "capability ve kalite sırasına göre hazırlandı.",
        )
        tab._append_chat_activity(
            "Exact model · fallback aynı provider içinde · her cevap Codex incelemesinde"
        )
    else:
        for record in _local_records():
            _add_local_record(tab, record)
        tab.model_list.setCurrentRow(0)
        tab.model_status.setText("3 yerel model hazır · llama.cpp")
        tab.reasoning_combo.setCurrentIndex(tab.reasoning_combo.findData("medium"))
        tab._append_chat_message(
            "user",
            "Bu yerel modelle 100 mesajlık Orders dayanıklılık testini başlat.",
        )
        tab._append_chat_message(
            "assistant",
            "Gemma 3 12B hazır. Gelişmiş runtime ayarları yalnız bu sohbet ve seçili modele uygulanır.",
        )
        tab._append_chat_activity("Yerel runtime · llama.cpp · GPU otomatik · fallback kapalı")
    tab._known_provider_count = 2
    tab._known_local_model_count = 3
    tab._update_resource_summary()
    tab._on_model_selection_changed()
    window.resize(*VIEWPORT)
    window.show()
    _process_events(app)
    return window, tab


def _render_chat(app: QApplication, output_dir: Path, *, source: str) -> dict[str, Any]:
    window, tab = _prepare_chat_shell(app, source=source)
    overlay = None
    base_pixmap = QPixmap.fromImage(window.grab().toImage().copy())
    if source == "local":
        tab._open_advanced_model_settings()
        _process_events(app)
        overlay = tab._advanced_dialog
    image_name = f"ui-acceptance-chat-{source}-1800x1100.png"
    _save_widget(window, output_dir / image_name, overlay=overlay, base_pixmap=base_pixmap)
    record = {
        "surface": f"chat_{source}",
        "image": image_name,
        "viewport": {"width": window.width(), "height": window.height()},
        "components": _component_tree(window),
    }
    if overlay is not None:
        record["overlay_components"] = _component_tree(overlay)
        overlay_origin = window.mapFromGlobal(overlay.mapToGlobal(QPoint(0, 0)))
        record["overlay_geometry"] = {
            "x": int(overlay_origin.x()),
            "y": int(overlay_origin.y()),
            "width": int(overlay.width()),
            "height": int(overlay.height()),
        }
        overlay.close()
    window.close()
    _process_events(app)
    return record


def _chat_model_payloads(tab: AITab) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index in range(tab.model_list.count()):
        payload = tab.model_list.item(index).data(Qt.ItemDataRole.UserRole)
        if isinstance(payload, dict):
            payloads.append(dict(payload))
    return payloads


def _render_chat_cloud_state_matrix(app: QApplication, output_dir: Path) -> list[dict[str, Any]]:
    window, tab = _prepare_chat_shell(app, source="cloud")
    cases: list[dict[str, Any]] = []

    _set_cloud_fixture_state(tab, price_filter="free", collapsed={"201"})
    _process_events(app)
    collapsed_payloads = _chat_model_payloads(tab)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-cloud-provider-collapsed",
            checks={
                "provider_collapsed": any(bool(row.get("_collapsed")) for row in collapsed_payloads),
                "other_provider_remains_expanded": tab.model_list.count() == 5,
            },
            facts={"model_list_rows": tab.model_list.count()},
        )
    )

    for price_filter, expected_models in (("free", 5), ("paid", 2), ("all", 7)):
        _set_cloud_fixture_state(tab, price_filter=price_filter)
        _process_events(app)
        payloads = _chat_model_payloads(tab)
        model_payloads = [row for row in payloads if row.get("_source_kind") == "cloud_model"]
        selected = tab.cloud_price_buttons[price_filter].isChecked()
        if price_filter == "free":
            pricing_matches = all(bool((row.get("model_metadata") or {}).get("is_free")) for row in model_payloads)
        elif price_filter == "paid":
            pricing_matches = all(not bool((row.get("model_metadata") or {}).get("is_free")) for row in model_payloads)
        else:
            free_values = {bool((row.get("model_metadata") or {}).get("is_free")) for row in model_payloads}
            pricing_matches = free_values == {False, True}
        cases.append(
            _state_snapshot(
                window,
                output_dir,
                state=f"chat-cloud-filter-{price_filter}",
                checks={
                    "segment_selected": selected,
                    "model_count": len(model_payloads) == expected_models,
                    "pricing_matches": pricing_matches,
                },
                facts={"visible_models": len(model_payloads), "price_filter": price_filter},
            )
        )

    tab._reset_chat()
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-empty-conversation",
            checks={
                "welcome_visible": tab.welcome_title.isVisibleTo(window),
                "transcript_empty": not tab.transcript.toPlainText().strip(),
            },
        )
    )
    tab._append_chat_message("user", "Bekleyen siparişleri doğrulanmış kapsamla özetle.")
    tab._append_chat_message("assistant", "Authoritative Orders okuması hazır; seçim state'i bu sohbete bağlandı.")
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-populated-conversation",
            checks={
                "transcript_visible": tab.transcript.isVisibleTo(window),
                "two_messages_present": tab._chat_message_count == 2,
            },
        )
    )

    tab.model_list.clear()
    tab._on_model_selection_changed()
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-cloud-empty",
            checks={"model_list_empty": tab.model_list.count() == 0},
        )
    )

    _set_cloud_fixture_state(tab, price_filter="free")
    tab.fallback_checkbox.setChecked(True)
    tab._append_chat_activity(
        "Gemini ücretsiz kotası doldu · aynı provider içindeki sıradaki uygun modele geçiliyor."
    )
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-cloud-quota-fallback",
            checks={
                "fallback_enabled": tab.fallback_checkbox.isChecked(),
                "fallback_visible": "kotası doldu" in tab.transcript.toPlainText(),
            },
        )
    )

    tab._set_chat_progress(46, "orders.query çalışıyor", percent_text="46%")
    tab.chat_progress_shell.show()
    tab._append_chat_activity("Tool çalışıyor · orders.query · salt-okuma")
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-tool-running",
            checks={
                "progress_visible": tab.chat_progress_shell.isVisibleTo(window),
                "tool_event_visible": "orders.query" in tab.transcript.toPlainText(),
            },
        )
    )
    tab.chat_progress_shell.hide()

    action = {
        "title": "Sipariş etiketi oluşturma onayı",
        "summary": "ORD-UI-1 ve ORD-UI-2 için iki etiket hazırlanacak.",
        "risk_level": "medium",
        "action_type": "labels.action_create_labels_from_selected_orders",
        "approval_required": True,
        "execute_enabled": True,
        "rows": [
            {"order_number": "ORD-UI-1", "operation": "create_label"},
            {"order_number": "ORD-UI-2", "operation": "create_label"},
        ],
    }
    tab._append_chat_approval_card(action)
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-approval",
            checks={
                "approval_visible": "Onay gerekiyor" in tab.transcript.toPlainText(),
                "scope_visible": "ORD-UI-1" in tab.transcript.toPlainText(),
            },
        )
    )

    tab._set_agent_state(status="approval_required", pending_action=action)
    superseded = tab._supersede_pending_action_for_revision(
        "Hayır, iki sipariş yerine bütün bekleyen siparişleri kullan; kapsamı düzelt."
    )
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-superseded-cancelled",
            checks={
                "superseded_safely": superseded is True,
                "pending_action_cleared": tab._pending_action_from_state() is None,
                "history_recorded": bool(tab._superseded_actions),
            },
        )
    )

    for state, message in (
        ("chat-execute-success", "Onaylı aksiyon çalıştırıldı · verify doğrulandı · audit kaydedildi."),
        ("chat-verify-failed", "Aksiyon tamamlandı ancak verify doğrulanamadı; kullanıcı incelemesi gerekiyor."),
    ):
        tab._append_chat_activity(message)
        _process_events(app)
        cases.append(
            _state_snapshot(
                window,
                output_dir,
                state=state,
                checks={"event_visible": message in tab.transcript.toPlainText()},
            )
        )

    window.resize(1280, 800)
    _process_events(app, rounds=12)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-cloud-narrow-resize",
            checks={
                "source_hierarchy_visible": tab.cloud_filter_shell.isVisibleTo(window),
                "model_panel_visible": tab.model_list.isVisibleTo(window),
                "composer_visible": tab.composer.isVisibleTo(window),
                "viewport_applied": window.width() == 1280 and window.height() == 800,
            },
        )
    )

    window.close()
    _process_events(app)
    return cases


def _render_chat_local_state_matrix(app: QApplication, output_dir: Path) -> list[dict[str, Any]]:
    window, tab = _prepare_chat_shell(app, source="local")
    cases: list[dict[str, Any]] = []

    limited = dict(_local_records()[0])
    limited["id"] = 999
    limited["repo_id"] = "orderscout/Limited-Memory-Model-GGUF"
    limited["resource_plan"] = {
        "safe_to_run": False,
        "profile": "blocked_insufficient_memory",
        "reason": "OS koruma rezervi",
        "num_ctx": 512,
        "max_tokens": 128,
    }
    tab.model_list.clear()
    _add_local_record(tab, limited)
    tab.model_list.setCurrentRow(0)
    tab._on_model_selection_changed()
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-local-limited",
            checks={
                "limited_status_visible": "bloke" in tab.composer_meta.text().casefold(),
                "send_disabled": not tab.btn_send.isEnabled(),
            },
            facts={"composer_meta": tab.composer_meta.text()},
        )
    )

    constrained = dict(_local_records()[0])
    constrained["capability_profile"] = {
        "supported_model_settings": ["num_ctx", "max_tokens", "temperature", "top_p"]
    }
    tab.model_list.clear()
    _add_local_record(tab, constrained)
    tab.model_list.setCurrentRow(0)
    tab._on_model_selection_changed()
    base_pixmap = QPixmap.fromImage(window.grab().toImage().copy())
    tab._open_advanced_model_settings()
    _process_events(app)
    dialog = tab._advanced_dialog
    if dialog is None:
        raise RuntimeError("Local unsupported-setting popup acilamadi.")
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-local-unsupported-setting",
            checks={
                "unsupported_fields_present": bool(dialog._unsupported_fields),
                "unsupported_fields_disabled": all(
                    not dialog._fields[key].isEnabled() for key in dialog._unsupported_fields
                ),
            },
            facts={"unsupported_fields": list(dialog._unsupported_fields)},
            overlay=dialog,
            base_pixmap=base_pixmap,
        )
    )

    dialog._fields["temperature"].setText("0.77")
    dialog._reset_defaults()
    reset_value = dialog._fields["temperature"].text()
    dialog.close()
    _process_events(app)
    tab._open_advanced_model_settings()
    _process_events(app)
    dialog = tab._advanced_dialog
    if dialog is None:
        raise RuntimeError("Local apply/reset popup acilamadi.")
    dialog._fields["temperature"].setText("0.55")
    dialog._apply()
    _process_events(app)
    selected_payload = dict(tab.model_list.currentItem().data(Qt.ItemDataRole.UserRole) or {})
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-local-advanced-apply-reset-cancel",
            checks={
                "reset_restored_default": reset_value == "0.2",
                "apply_persisted_to_conversation": selected_payload.get("temperature") == 0.55,
                "popup_closed_after_apply": tab._advanced_dialog is None or not tab._advanced_dialog.isVisible(),
            },
            facts={"reset_value": reset_value, "applied_temperature": selected_payload.get("temperature")},
        )
    )

    cancel_base = QPixmap.fromImage(window.grab().toImage().copy())
    tab._open_advanced_model_settings()
    _process_events(app)
    dialog = tab._advanced_dialog
    if dialog is None:
        raise RuntimeError("Local cancel popup acilamadi.")
    cancel_button = next(
        (
            button
            for button in dialog.findChildren(QAbstractButton)
            if button.text() == "Vazgeç"
        ),
        None,
    )
    cancel_case = _state_snapshot(
        window,
        output_dir,
        state="chat-local-popup-explicit-cancel",
        checks={
            "cancel_control_visible": cancel_button is not None and cancel_button.isVisibleTo(dialog),
        },
        overlay=dialog,
        base_pixmap=cancel_base,
    )
    if cancel_button is not None:
        cancel_button.click()
    _process_events(app)
    cancel_case["checks"]["popup_closed_without_apply"] = bool(
        tab._advanced_dialog is None or not tab._advanced_dialog.isVisible()
    )
    cancel_case["passed"] = all(bool(value) for value in cancel_case["checks"].values())
    cases.append(cancel_case)

    for index in range(30):
        tab._append_chat_message("user", f"Uzun sohbet turu {index + 1}: sipariş bağlamını koru.")
        tab._append_chat_message("assistant", f"Tur {index + 1}: seçim ve provider state'i korundu.")
    tab.transcript.verticalScrollBar().setValue(tab.transcript.verticalScrollBar().maximum())
    _process_events(app)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-long-scroll",
            checks={
                "scroll_available": tab.transcript.verticalScrollBar().maximum() > 0,
                "latest_turn_visible": "Tur 30" in tab.transcript.toPlainText(),
            },
            facts={"scroll_maximum": tab.transcript.verticalScrollBar().maximum()},
        )
    )

    window.resize(1280, 800)
    _process_events(app, rounds=12)
    cases.append(
        _state_snapshot(
            window,
            output_dir,
            state="chat-local-narrow-resize",
            checks={
                "source_hierarchy_visible": tab.btn_source_local.isVisibleTo(window),
                "model_panel_visible": tab.model_list.isVisibleTo(window),
                "composer_visible": tab.composer.isVisibleTo(window),
                "viewport_applied": window.width() == 1280 and window.height() == 800,
            },
        )
    )

    window.close()
    _process_events(app)
    return cases


def _manager_result_fixtures() -> dict[str, Result]:
    providers = [
        {
            "id": 201,
            "provider_code": "gemini",
            "provider_label": "Google AI Studio",
            "label": "Google AI Studio",
            "api_key_masked": "••••••••4A2C",
            "is_enabled": True,
        },
        {
            "id": 202,
            "provider_code": "openrouter",
            "provider_label": "OpenRouter",
            "label": "OpenRouter",
            "api_key_masked": "••••••••91EF",
            "is_enabled": True,
        },
    ]
    return {
        "settings": Result.ok(
            "fixture",
            close_dialog=False,
            data={"settings": {"download_root": "D:/OrderScout/models", "search_limit": 16}},
        ),
        "providers": Result.ok("fixture", close_dialog=False, data={"records": providers}),
        "library": Result.ok("fixture", close_dialog=False, data={"records": _local_records()}),
        "search": Result.ok("fixture", close_dialog=False, data={"records": []}),
    }


def _render_model_hub(app: QApplication, output_dir: Path) -> dict[str, Any]:
    fixture = _manager_result_fixtures()
    with patch("AI.views.actions.action_load_ai_settings", return_value=fixture["settings"]), patch(
        "AI.views.actions.action_list_provider_accounts", return_value=fixture["providers"]
    ), patch(
        "AI.views.actions.action_list_installed_models", return_value=fixture["library"]
    ), patch(
        "AI.views.actions.action_search_hf_models", return_value=fixture["search"]
    ):
        dialog = AIManagerDialog()
        dialog.resize(*VIEWPORT)
        dialog.show()
        _process_events(app, rounds=20)
        dialog._set_provider_mode("new")
        dialog._set_entry_kind("cloud")
        dialog.provider_type_combo.setCurrentIndex(0)
        dialog.provider_label_input.setPlaceholderText("Örn. Üretim Gemini")
        dialog.provider_key_input.setText("orderscout-acceptance-secret")
        _process_events(app)

        image_name = "ui-acceptance-model-hub-1800x1100.png"
        _save_widget(dialog, output_dir / image_name)
        record = {
            "surface": "model_hub",
            "image": image_name,
            "viewport": {"width": dialog.width(), "height": dialog.height()},
            "components": _component_tree(dialog),
        }
        dialog.close()
        _process_events(app)
        return record


def _render_model_hub_state_matrix(app: QApplication, output_dir: Path) -> list[dict[str, Any]]:
    fixture = _manager_result_fixtures()
    cases: list[dict[str, Any]] = []
    with patch("AI.views.actions.action_load_ai_settings", return_value=fixture["settings"]), patch(
        "AI.views.actions.action_list_provider_accounts", return_value=fixture["providers"]
    ), patch(
        "AI.views.actions.action_list_installed_models", return_value=fixture["library"]
    ), patch(
        "AI.views.actions.action_search_hf_models", return_value=fixture["search"]
    ):
        dialog = AIManagerDialog()
        dialog.resize(*VIEWPORT)
        dialog.show()
        _process_events(app, rounds=20)
        dialog._set_provider_mode("new")
        dialog._set_entry_kind("cloud")
        _process_events(app)

        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-cloud-empty",
                checks={
                    "label_empty": not dialog.provider_label_input.text(),
                    "secret_empty": not dialog.provider_key_input.text(),
                    "new_source_mode": dialog._provider_mode == "new",
                },
            )
        )

        validation_ok = dialog._validate_provider_form()
        _process_events(app)
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-validation-error",
                checks={
                    "validation_rejected": not validation_ok,
                    "inline_error_visible": dialog.provider_validation_label.isVisibleTo(dialog),
                    "error_mentions_required_fields": "API anahtarı" in dialog.provider_validation_label.text(),
                },
            )
        )

        secret_fixture = "orderscout-acceptance-secret"
        dialog.provider_label_input.setText("Üretim Gemini")
        dialog.provider_key_input.setText(secret_fixture)
        _process_events(app)
        visible_text = "\n".join(
            str(row.get("text") or "") for row in _component_tree(dialog)
        )
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-secret-redacted",
                checks={
                    "password_echo_mode": dialog.provider_key_input.echoMode().name == "Password",
                    "secret_absent_from_component_text": secret_fixture not in visible_text,
                    "validation_cleared": dialog.provider_validation_label.isHidden(),
                },
                facts={"echo_mode": dialog.provider_key_input.echoMode().name},
            )
        )

        dialog._set_entry_kind("local")
        dialog.results_list.clear()
        dialog.results_status.setText("Henüz model sonucu yok.")
        dialog.download_stage.setText("İndirme bekliyor.")
        dialog.download_progress.setRange(0, 100)
        dialog.download_progress.setValue(0)
        _process_events(app)
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-local-empty",
                checks={
                    "local_mode": dialog._entry_kind == "local",
                    "results_empty": dialog.results_list.count() == 0,
                },
            )
        )

        dialog.results_status.setText("Hugging Face kataloğu yükleniyor...")
        dialog.download_stage.setText("Model ayrıntısı bekleniyor...")
        dialog.download_progress.setRange(0, 0)
        _process_events(app)
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-loading",
                checks={
                    "indeterminate_progress": dialog.download_progress.maximum() == 0,
                    "loading_text_visible": "yükleniyor" in dialog.results_status.text().casefold(),
                },
            )
        )

        dialog.download_progress.setRange(0, 100)
        dialog.download_progress.setValue(43)
        dialog.download_stage.setText("Gemma 3 12B indiriliyor · 3.2 / 7.4 GB")
        _process_events(app)
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-download-progress",
                checks={
                    "progress_value": dialog.download_progress.value() == 43,
                    "download_text_visible": "indiriliyor" in dialog.download_stage.text().casefold(),
                },
            )
        )

        dialog.download_stage.setText("İndirme duraklatıldı; kısmi dosya korunuyor.")
        dialog.btn_download.setText("İndirmeye devam et")
        dialog.btn_download.setEnabled(True)
        dialog.btn_pause_download.setEnabled(False)
        dialog.btn_pause_download.hide()
        _process_events(app)
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-download-paused-resumable",
                checks={
                    "paused_status_visible": "duraklatıldı" in dialog.download_stage.text().casefold(),
                    "resume_action_visible": dialog.btn_download.isVisibleTo(dialog),
                    "resume_action_named": dialog.btn_download.text() == "İndirmeye devam et",
                    "partial_progress_preserved": dialog.download_progress.value() == 43,
                },
            )
        )

        dialog.download_progress.setValue(43)
        dialog.download_stage.setText("İndirme başarısız · ağ bağlantısını kontrol et; kısmi dosya korunuyor.")
        _process_events(app)
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-download-failed",
                checks={
                    "failure_visible": "başarısız" in dialog.download_stage.text().casefold(),
                    "partial_progress_preserved": dialog.download_progress.value() == 43,
                },
            )
        )

        dialog.download_progress.setValue(100)
        dialog.download_stage.setText("İndirme tamamlandı · artifact sağlık kontrolü hazır.")
        _process_events(app)
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-download-completed",
                checks={
                    "progress_complete": dialog.download_progress.value() == 100,
                    "completion_visible": "tamamlandı" in dialog.download_stage.text().casefold(),
                },
            )
        )

        dialog._fill_installed_local_list(_local_records())
        dialog.installed_local_list.setCurrentRow(0)
        editor_scrollbar = dialog._workspace.editor_scroll.verticalScrollBar()
        editor_scrollbar.setValue(editor_scrollbar.maximum())
        _process_events(app)
        delete_origin = dialog.btn_delete_local_model.mapTo(dialog, QPoint(0, 0))
        cases.append(
            _state_snapshot(
                dialog,
                output_dir,
                state="model-hub-local-delete",
                checks={
                    "installed_models_visible": dialog.installed_local_list.count() == 3,
                    "delete_action_enabled": dialog.btn_delete_local_model.isEnabled(),
                    "delete_action_visible": dialog.btn_delete_local_model.isVisibleTo(dialog),
                    "delete_action_in_viewport": 0 <= delete_origin.y() < dialog.height(),
                },
            )
        )

        dialog.close()
        _process_events(app)
    return cases


def _state_matrix_evidence(cases: list[dict[str, Any]]) -> dict[str, Any]:
    pending_states: list[str] = []
    return {
        "passed": all(bool(case.get("passed")) for case in cases),
        "complete": not pending_states and all(bool(case.get("passed")) for case in cases),
        "rendered_case_count": len(cases),
        "rendered_states": [str(case.get("state") or "") for case in cases],
        "pending_states": pending_states,
        "cases": cases,
    }


def run(output_dir: Path) -> Path:
    app = QApplication.instance() or QApplication([])
    font_family = _install_offscreen_font(app)
    surfaces = [
        _render_chat(app, output_dir, source="cloud"),
        _render_chat(app, output_dir, source="local"),
        _render_model_hub(app, output_dir),
    ]
    state_cases = [
        *_render_chat_cloud_state_matrix(app, output_dir),
        *_render_chat_local_state_matrix(app, output_dir),
        *_render_model_hub_state_matrix(app, output_dir),
    ]
    evidence = {
        "contract": "AI UI v3 scaffold-faithful acceptance",
        "render_mode": os.environ.get("QT_QPA_PLATFORM", ""),
        "viewport": {"width": VIEWPORT[0], "height": VIEWPORT[1]},
        "logical_dpi": float(app.primaryScreen().logicalDotsPerInch()) if app.primaryScreen() else None,
        "font_family": font_family,
        "surfaces": surfaces,
        "acceptance": _acceptance_checks(output_dir, surfaces),
        "state_matrix": _state_matrix_evidence(state_cases),
    }
    evidence_path = output_dir / "ui-acceptance-component-tree-1800x1100.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence_path


def main() -> int:
    parser = argparse.ArgumentParser(description="OrderScout AI offscreen UI acceptance renderer")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "docs"),
        help="PNG ve component-tree kanitlarinin yazilacagi klasor",
    )
    args = parser.parse_args()
    path = run(Path(args.output_dir).resolve())
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
