from __future__ import annotations

import datetime
import json
import os
from typing import Any, Callable, Dict, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QTableWidgetItem

from Account.constants import (
    ACCOUNT_ALWAYS_ENABLED_FIELDS,
    ACCOUNT_DEFAULT_ENABLED_FIELDS,
    ACCOUNT_DEFAULT_PLATFORM_CODE,
    ACCOUNT_DEFAULT_PLATFORM_LABEL,
    ACCOUNT_TABLE_ROW_HEIGHT,
    account_platform_code,
)
from Account.processors.pipeline import (
    delete_company_from_db,
    check_company_api_health,
    process_logo,
    save_company_to_db,
    update_company,
)
from Feedback.processors.pipeline import Result, map_error_to_message
from Core.views import SwitchButton, ListSmartItemWidget, optimized_table_updates
from Marketplaces.constants.catalog_constants import (
    marketplace_account_enabled_fields,
    platform_record_for_code,
    platform_label_for_code,
    platform_select_options,
)


# ==========================================================
# Helpers
# ==========================================================
_ACCOUNT_ICON_CACHE_LIMIT = 128
_ACCOUNT_ICON_CACHE: dict[tuple[str, int, int], QIcon] = {}


def _account_icon_signature(path: str) -> tuple[str, int, int] | None:
    try:
        stat = os.stat(path)
        return (os.path.abspath(path), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return None


def _cached_account_icon(path: str) -> QIcon:
    signature = _account_icon_signature(path)
    if signature is None:
        return QIcon()
    cached = _ACCOUNT_ICON_CACHE.get(signature)
    if cached is not None:
        return cached
    icon = QIcon(signature[0])
    _ACCOUNT_ICON_CACHE[signature] = icon
    if len(_ACCOUNT_ICON_CACHE) > _ACCOUNT_ICON_CACHE_LIMIT:
        _ACCOUNT_ICON_CACHE.pop(next(iter(_ACCOUNT_ICON_CACHE)), None)
    return icon


def _json_loads_safe(text: str) -> Tuple[Optional[dict], Optional[Exception]]:
    text = (text or "").strip()
    if not text:
        return None, None
    try:
        return json.loads(text), None
    except Exception as e:
        return None, e


def _set_item_readonly(item: QTableWidgetItem) -> None:
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)


def _widget_enabled(w: Any) -> bool:
    try:
        return bool(w.isEnabled())
    except Exception:
        return True


def account_platform_options() -> list[tuple[str, str]]:
    return list(platform_select_options(include_all=False))


def account_default_platform_code() -> str:
    return ACCOUNT_DEFAULT_PLATFORM_CODE


def account_default_platform_label() -> str:
    return ACCOUNT_DEFAULT_PLATFORM_LABEL


def _platform_display_label(value: object) -> str:
    code = account_platform_code(value)
    return str(platform_label_for_code(code) or str(value or "").strip())


def account_visual_status(account: Any) -> str:
    from Account.processors.local_health import local_account_status
    return local_account_status(account)["display_status"]


def action_load_local_account_health(*, api_account_ids=None, db_name=None) -> Result:
    from Account.processors.local_health import summarize_local_account_health
    options = {"db_name": db_name} if db_name else {}
    return summarize_local_account_health(api_account_ids=api_account_ids, **options)


def action_find_local_accounts(*, query="", limit=10, db_name=None) -> Result:
    from Account.processors.local_health import lookup_local_accounts
    return lookup_local_accounts(query=query, limit=limit, **({"db_name": db_name} if db_name else {}))


def _widget_current_platform(widget: Any) -> str:
    if widget is None:
        return ""
    try:
        data = widget.currentData()
        code = account_platform_code(data)
        if code:
            return code
    except Exception:
        pass
    try:
        return account_platform_code(widget.currentText())
    except Exception:
        return ""


def _set_widget_platform(widget: Any, platform: object) -> None:
    code = account_platform_code(platform)
    if not code:
        try:
            widget.setCurrentText("")
        except Exception:
            return
        return
    label = str(platform_label_for_code(code) or code)

    try:
        idx = widget.findData(code)
        if isinstance(idx, int) and idx >= 0:
            widget.setCurrentIndex(idx)
            return
    except Exception:
        pass

    try:
        widget.setCurrentText(label)
        return
    except Exception:
        pass

    try:
        widget.setCurrentText(code)
    except Exception:
        return


# ==========================================================
# Platform Rules (sadece kural dondurur, UI'ya dokunmaz)
# ==========================================================
def get_platform_enabled_fields(platform: str) -> set[str]:
    key = account_platform_code(platform)
    if not key:
        key = account_default_platform_code()
    fields = set(marketplace_account_enabled_fields(key) or []) or ACCOUNT_DEFAULT_ENABLED_FIELDS
    return set(fields) | set(ACCOUNT_ALWAYS_ENABLED_FIELDS)


# ==========================================================
# Table Render (Result ile)
# ==========================================================
def build_company_table(table_widget, result: Optional[Result] = None) -> Result:
    """
    Standard: views Result uretir, actions render eder.
    """
    try:
        if result is None:
            return Result.fail("Result nesnesi zorunludur.", close_dialog=False)

        if not isinstance(result, Result):
            return Result.fail("Ge\u00e7ersiz Result objesi al\u0131nd\u0131.", close_dialog=False)

        if not result.success:
            return result

        records = result.data.get("records", []) or []

        added = 0
        with optimized_table_updates(table_widget, len(records)):
            if not records:
                return Result.ok("Hi\u00e7 \u015firket bulunmuyor.", close_dialog=False, data={"count": 0})

            for row, acc in enumerate(records):
                # Logo sutunu (pk burada gizli tutuluyor)
                item_logo = QTableWidgetItem()
                pk = getattr(acc, "pk", None)
                item_logo.setData(Qt.ItemDataRole.UserRole, pk)

                logo_path = getattr(acc, "logo_path", None)
                if logo_path and os.path.exists(logo_path):
                    item_logo.setIcon(_cached_account_icon(str(logo_path)))

                item_name = QTableWidgetItem(getattr(acc, "comp_name", "") or "")
                item_seller = QTableWidgetItem(getattr(acc, "account_id", "") or "")
                item_platform = QTableWidgetItem(_platform_display_label(getattr(acc, "platform", "") or ""))
                item_status = QTableWidgetItem(account_visual_status(acc))

                for col, it in enumerate([item_logo, item_name, item_seller, item_platform, item_status]):
                    _set_item_readonly(it)
                    table_widget.setItem(row, col, it)

                table_widget.setRowHeight(row, ACCOUNT_TABLE_ROW_HEIGHT)
                added += 1
        return Result.ok(
            f"\u015eirketler tabloya y\u00fcklendi. (toplam: {added})",
            close_dialog=False,
            data={"count": added},
        )

    except Exception as e:
        try:
            table_widget.setUpdatesEnabled(True)
        except Exception:
            pass
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ==========================================================
# Form Fill / Validate / Collect
# ==========================================================
def fill_company_form(dialog_instance, account) -> Result:
    try:
        dialog_instance.seller_id_input.setText(getattr(account, "account_id", "") or "")
        dialog_instance.comp_name_input.setText(getattr(account, "comp_name", "") or "")
        dialog_instance.api_key_input.setText(getattr(account, "api_key", "") or "")
        dialog_instance.api_secret_input.setText(getattr(account, "api_secret", "") or "")
        dialog_instance.integration_code_input.setText(getattr(account, "integration_code", "") or "")
        dialog_instance.token_input.setText(getattr(account, "token", "") or "")

        # Platform
        current_platform = getattr(account, "platform", None)
        if current_platform:
            _set_widget_platform(dialog_instance.platform_input, current_platform)

        # Extra Config
        extra = getattr(account, "extra_config", None)
        if isinstance(extra, dict):
            dialog_instance.extra_config_input.setPlainText(json.dumps(extra, indent=2, ensure_ascii=False))
        elif isinstance(extra, str):
            parsed, err = _json_loads_safe(extra)
            if err:
                dialog_instance.extra_config_input.setPlainText(extra)
            else:
                dialog_instance.extra_config_input.setPlainText(json.dumps(parsed, indent=2, ensure_ascii=False))
        else:
            dialog_instance.extra_config_input.setPlainText("")

        dialog_instance.is_active_input.setChecked(bool(getattr(account, "is_active", False)))

        # Logo
        logo_path = getattr(account, "logo_path", None)
        dialog_instance.logo_path = None
        if hasattr(dialog_instance, "logo_selector"):
            dialog_instance.logo_selector.setFiles([], emit_signal=False)

        if logo_path and os.path.exists(logo_path):
            dialog_instance.logo_path = logo_path
            if hasattr(dialog_instance, "logo_selector"):
                dialog_instance.logo_selector.setFiles([logo_path], emit_signal=False)

        return Result.ok("Form dolduruldu.", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def validate_form_values(values: Dict[str, Any]) -> Result:
    if not values.get("account_id"):
        return Result.fail("Sat\u0131c\u0131 ID bo\u015f b\u0131rak\u0131lamaz.", close_dialog=False)
    if not values.get("comp_name"):
        return Result.fail("\u015eirket ad\u0131 bo\u015f b\u0131rak\u0131lamaz.", close_dialog=False)
    if not values.get("platform"):
        return Result.fail("Platform se\u00e7ilmelidir.", close_dialog=False)
    platform_code = account_platform_code(values.get("platform"))
    if not platform_code:
        return Result.fail("Platform se\u00e7ilmelidir.", close_dialog=False)
    if platform_record_for_code(platform_code) is None:
        return Result.fail(f"Ge\u00e7ersiz platform: {values['platform']}", close_dialog=False)
    values["platform"] = platform_code
    return Result.ok("Validasyon ba\u015far\u0131l\u0131.", close_dialog=False)


def collect_form_values(dialog_instance) -> Tuple[Optional[Dict[str, Any]], Result]:
    """
    Disabled alanlar:
      - CREATE: hic yokmus gibi kalir (model default)
      - UPDATE: payload'dan cikar, DB'deki deger ezilmez
    """
    try:
        values: Dict[str, Any] = {
            "account_id": dialog_instance.seller_id_input.text().strip(),
            "comp_name": dialog_instance.comp_name_input.text().strip(),
            "platform": _widget_current_platform(getattr(dialog_instance, "platform_input", None)),
            "logo_path": getattr(dialog_instance, "logo_path", None),
            "is_active": dialog_instance.is_active_input.isChecked(),
        }

        # Optional fields (enabled ise ekle)
        if _widget_enabled(dialog_instance.api_key_input):
            values["api_key"] = dialog_instance.api_key_input.text().strip()
        if _widget_enabled(dialog_instance.api_secret_input):
            values["api_secret"] = dialog_instance.api_secret_input.text().strip()
        if _widget_enabled(dialog_instance.integration_code_input):
            values["integration_code"] = dialog_instance.integration_code_input.text().strip()
        if _widget_enabled(dialog_instance.token_input):
            values["token"] = dialog_instance.token_input.text().strip()

        if _widget_enabled(dialog_instance.extra_config_input):
            parsed, err = _json_loads_safe(dialog_instance.extra_config_input.toPlainText())
            if err:
                return None, Result.fail("Extra Config JSON format\u0131 ge\u00e7ersiz.", error=err, close_dialog=False)
            values["extra_config"] = parsed

        vres = validate_form_values(values)
        if not vres.success:
            return None, vres

        return values, vres

    except Exception as e:
        return None, Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ==========================================================
# Submit / Logo
# ==========================================================
def submit_company_values(*, account_pk: int | None, values: Dict[str, Any]) -> Result:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    # Create
    if account_pk is None:
        health_res = check_company_api_health(
            platform=str(values.get("platform") or ""),
            account_id=str(values.get("account_id") or ""),
            api_key=values.get("api_key"),
            api_secret=values.get("api_secret"),
            integration_code=values.get("integration_code"),
            token=values.get("token"),
            extra_config=values.get("extra_config") if isinstance(values.get("extra_config"), dict) else None,
        )
        if not health_res.success:
            return Result.fail(
                f"API do\u011frulamas\u0131 ba\u015far\u0131s\u0131z: {health_res.message}",
                error=health_res.error,
                close_dialog=False,
                data=health_res.data,
            )

        values["created_at"] = now
        save_res = save_company_to_db(values)
        if not save_res.success:
            return save_res

        skipped = bool((health_res.data or {}).get("skipped"))
        msg = (
            "\u015eirket kaydedildi. API ba\u011flant\u0131 kontrol\u00fc atland\u0131."
            if skipped
            else "\u015eirket kaydedildi ve API ba\u011flant\u0131s\u0131 do\u011fruland\u0131."
        )
        merged_data = dict(save_res.data or {})
        merged_data["health"] = dict(health_res.data or {})
        return Result.ok(msg, close_dialog=False, data=merged_data)

    # Update
    values["last_used_at"] = now
    update_res = update_company(account_pk, values)
    if not update_res.success:
        return update_res
    return Result.ok(update_res.message or "\u015eirket ba\u015far\u0131yla g\u00fcncellendi.", close_dialog=False, data=update_res.data or {})


def handle_company_submit(dialog_instance) -> Result:
    values, validation = collect_form_values(dialog_instance)
    if not values:
        return validation
    account_pk = getattr(getattr(dialog_instance, "account", None), "pk", None)
    return submit_company_values(account_pk=account_pk, values=values)


def handle_logo_selection(dialog_instance, file_path: str) -> Result:
    try:
        res = process_logo(file_path)
        if not res.success:
            return res

        save_path = res.data.get("path")
        if not save_path:
            return Result.fail("Logo kaydedildi ancak yol al\u0131namad\u0131.", close_dialog=False)

        dialog_instance.logo_path = save_path
        return Result.ok("Logo ba\u015far\u0131yla y\u00fcklendi.", close_dialog=False, data={"path": save_path})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ==========================================================
# Delete (cift refresh yok)
# ==========================================================
def delete_company_and_refresh(table, pk: int) -> Result:
    """
    Refresh yapmaz. Sinyal zaten tabloyu yeniletecek.
    """
    try:
        return delete_company_from_db(pk)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ==========================================================
# Company List Render
# ==========================================================
def build_company_list(
    list_widget: QListWidget,
    result: Result,
    interaction_cb: Optional[Callable] = None,
) -> Result:
    try:
        if not isinstance(result, Result):
            return Result.fail("Ge\u00e7ersiz Result objesi al\u0131nd\u0131.", close_dialog=False)

        if not result.success:
            return result

        records = result.data.get("records", []) or []
        list_widget.clear()

        if not records:
            return Result.ok("Hi\u00e7 \u015firket bulunmuyor.", close_dialog=False, data={"count": 0})

        added = 0
        for acc in records:
            pk = getattr(acc, "pk", None)

            switch = SwitchButton()
            switch.setChecked(True)

            icon_path = getattr(acc, "logo_path", None) or None
            if icon_path and not os.path.exists(icon_path):
                icon_path = None

            item_widget = ListSmartItemWidget(
                title=getattr(acc, "comp_name", None) or "-",
                identifier=str(pk) if pk is not None else "",
                icon_path=icon_path,
                optional_widget=switch,
            )

            if interaction_cb:
                item_widget.interaction.connect(interaction_cb)

            item = QListWidgetItem(list_widget)
            item.setSizeHint(item_widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, pk)

            list_widget.setItemWidget(item, item_widget)
            added += 1

        return Result.ok(
            f"\u015eirket listesi ba\u015far\u0131yla olu\u015fturuldu. (toplam: {added})",
            close_dialog=False,
            data={"count": added},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def collect_selected_companies(list_widget: QListWidget) -> Result:
    try:
        if list_widget.count() == 0:
            return Result.fail("Listede \u015firket bulunamad\u0131.", close_dialog=False)

        selected_pks: list[int] = []

        for i in range(list_widget.count()):
            item = list_widget.item(i)
            widget = list_widget.itemWidget(item)

            btn = getattr(widget, "right_widget", None)
            if isinstance(btn, SwitchButton) and btn.isChecked():
                pk = item.data(Qt.ItemDataRole.UserRole)
                if pk is not None:
                    selected_pks.append(pk)

        if not selected_pks:
            return Result.fail("Hi\u00e7bir \u015firket se\u00e7ilmedi.", close_dialog=False)

        return Result.ok(
            f"{len(selected_pks)} \u015firket se\u00e7ildi.",
            close_dialog=False,
            data={"selected_company_pks": selected_pks},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


