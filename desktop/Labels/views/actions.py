# Labels/views/actions.py
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from datetime import datetime
from time import time
from typing import Optional, Any, Callable, List

from Feedback.processors.pipeline import Result, map_error_to_message

from settings import MEDIA_EXPORTS


def _label_pipeline(name: str):
    return getattr(import_module("Labels.processors.pipeline"), name)


def update_records(*args, **kwargs):
    from Core.utils.model_utils import update_records as _update_records

    return _update_records(*args, **kwargs)


# ============================================================
# State DTO
# ============================================================
@dataclass
class LabelExportState:
    label_result: Optional[Result] = None
    payload: Optional[dict] = None
    sort_mode: str = "none"
    output_path: Optional[Path] = None
    brand_code: Optional[str] = None
    model_code: Optional[str] = None
    template_path: Optional[Path] = None


# ============================================================
# Helpers
# ============================================================
def build_default_output_dir() -> Result:
    try:
        default_dir = MEDIA_EXPORTS / "labels"
        default_dir.mkdir(parents=True, exist_ok=True)
        return Result.ok("Default output dir hazır.", close_dialog=False, data={"dir": default_dir})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def build_suggested_filename(*, model_code: str) -> Result:
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"labels_{model_code}_{ts}.docx"
        return Result.ok("Suggested filename OK.", close_dialog=False, data={"filename": name})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def resolve_list_widget_from_parent(dialog) -> Result:
    """
    Bu dialog OrdersManagerWindow üzerinden açılmalı.
    parent.list_widget bekleniyor.
    """
    try:
        parent = dialog.parent()
        if parent is None or not hasattr(parent, "list_widget"):
            return Result.fail(
                "Liste kaynağı bulunamadı. Bu pencere OrdersManagerWindow üzerinden açılmalı.",
                close_dialog=False
            )
        return Result.ok("list_widget bulundu.", close_dialog=False, data={"list_widget": parent.list_widget})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def ensure_any_selected_orders(list_widget) -> Result:
    """
    Modern model tabanlı seçim kontrolü.
    """
    try:
        if list_widget is None:
            return Result.fail("list_widget yok.", close_dialog=False)

        if not hasattr(list_widget, "get_selected_orders"):
            return Result.fail("list_widget.get_selected_orders() yok.", close_dialog=False)

        selected_orders = list_widget.get_selected_orders() or []
        if not selected_orders:
            return Result.fail("En az bir sipariş seçmelisiniz.", close_dialog=False)

        return Result.ok("Seçili sipariş var.", close_dialog=False, data={"selected_orders": selected_orders})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def extract_order_numbers_from_list_widget(list_widget) -> Result:
    """
    UI katmanı: OrdersListWidget -> seçili Order objelerinden orderNumber listesi çıkarır.
    """
    try:
        if list_widget is None:
            return Result.fail("list_widget yok.", close_dialog=False)

        if not hasattr(list_widget, "get_selected_orders"):
            return Result.fail("list_widget.get_selected_orders() yok.", close_dialog=False)

        selected = list_widget.get_selected_orders() or []
        order_numbers: List[str] = []
        order_refs: List[dict] = []

        for o in selected:
            num = getattr(o, "orderNumber", None) or getattr(o, "order_number", None)
            if num is None:
                continue
            s = str(num).strip()
            if s:
                order_numbers.append(s)
                api_account_id = getattr(o, "api_account_id", None)
                if api_account_id is None:
                    header = getattr(o, "header", None)
                    api_account_id = getattr(header, "api_account_id", None) if header is not None else None
                try:
                    api_account_id = int(api_account_id)
                except Exception:
                    api_account_id = None
                if api_account_id is not None and api_account_id > 0:
                    order_refs.append({"orderNumber": s, "api_account_id": api_account_id})

        # seçim sırası bozulmasın + uniq
        order_numbers = list(dict.fromkeys(order_numbers))
        order_refs = list(
            {
                (ref["orderNumber"], ref["api_account_id"]): ref
                for ref in order_refs
            }.values()
        )

        if not order_numbers:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        scoped_numbers = {ref["orderNumber"] for ref in order_refs}
        return Result.ok(
            "Order numbers çıkarıldı.",
            close_dialog=False,
            data={
                "order_numbers": order_numbers,
                "order_refs": order_refs,
                "order_refs_complete": all(number in scoped_numbers for number in order_numbers),
            },
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def resolve_template_path_from_cfg(*, brand_code: str, model_code: str) -> Result:
    """
    ✅ Tek kaynak: get_label_model_config
    UI tarafında base_dir ile template arama bitti.
    """
    try:
        vres = _label_pipeline("validate_label_model_config")(brand_code, model_code)
        if not vres.success:
            return vres
        cfg = vres.data.get("cfg") or {}

        tp_raw = cfg.get("template_path")
        tp = Path(tp_raw) if tp_raw else Path("")
        if not tp.is_file():
            return Result.fail(f"Word şablonu bulunamadı: {tp}", close_dialog=False)

        return Result.ok("Template path OK.", close_dialog=False, data={"template_path": tp})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ============================================================
# Main Flow: build payload + sort
# ============================================================
def build_label_payload(
    *,
    list_widget,
    brand_code: str,
    model_code: str,
) -> Result:
    """
    1) UI -> order_numbers çıkar
    2) pipeline.create_order_label_from_orders(order_numbers) çağır
    """
    try:
        nums_res = extract_order_numbers_from_list_widget(list_widget)
        if not nums_res.success:
            return nums_res

        order_numbers = nums_res.data["order_numbers"]

        call_kwargs = {"brand_code": brand_code, "model_code": model_code}
        if (nums_res.data or {}).get("order_refs_complete"):
            call_kwargs["order_refs"] = list((nums_res.data or {}).get("order_refs") or [])
        res = _label_pipeline("create_order_label_from_orders")(order_numbers, **call_kwargs)
        if not res or not isinstance(res, Result):
            return Result.fail("Etiket verisi hazırlanırken beklenmeyen bir hata oluştu.", close_dialog=False)

        if not res.success:
            return res

        payload = (res.data or {}).get("label_payload", {})
        if not payload:
            return Result.fail("Label payload üretilemedi.", close_dialog=False)

        return Result.ok(
            "Label payload üretildi.",
            close_dialog=False,
            data={"label_result": res, "payload": payload},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def apply_sort_to_payload(*, payload: dict, sort_mode: str) -> Result:
    """
    sort_label_payload -> Result döner.
    """
    try:
        sres = _label_pipeline("sort_label_payload")(payload, sort_mode)
        if not sres or not isinstance(sres, Result):
            return Result.fail("Sıralama yanıtı beklenmeyen formatta.", close_dialog=False)

        if not sres.success:
            return sres

        new_payload = (sres.data or {}).get("label_payload") or payload
        return Result.ok("Sıralama uygulandı.", close_dialog=False, data={"payload": new_payload})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ============================================================
# Worker starter
# ============================================================
def make_export_worker(
    *,
    worker_cls,
    payload: dict,
    brand_code: str,
    model_code: str,
    output_path: Path,
    template_path: Path,
    progress_cb: Callable[[int], None],
) -> Result:
    try:
        worker = worker_cls(
            _label_pipeline("export_labels_to_word"),
            label_payload=payload,
            brand_code=brand_code,
            model_code=model_code,
            output_path=str(output_path),
            template_path=str(template_path),
            progress_cb=progress_cb,
        )
        return Result.ok("Worker hazır.", close_dialog=False, data={"worker": worker})
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ============================================================
# Post-success: flag update
# ============================================================
def mark_orders_extracted_from_label_result(label_result: Result) -> Result:
    """
    label_result.data["order_numbers"] içinden OrderHeader update eder
    """
    try:
        if not label_result or not isinstance(label_result, Result) or not label_result.success:
            return Result.ok("Label result yok / başarısız, flag update atlandı.", close_dialog=False)

        payload = label_result.data or {}
        order_refs = payload.get("order_refs", []) or []
        if not order_refs:
            return Result.fail("order_refs bulunamadı; güncel payload formatı zorunlu.", close_dialog=False)

        now_ts = int(time() * 1000)
        from Orders.models.trendyol.models import OrderHeader

        failed = []
        updated_any = False
        seen_refs: set[tuple[str, Optional[int]]] = set()

        for ref in order_refs:
            if not isinstance(ref, dict):
                continue

            ord_no = str(ref.get("orderNumber") or "").strip()
            if not ord_no:
                continue

            api_account_id = ref.get("api_account_id")
            try:
                api_account_id = int(api_account_id) if api_account_id is not None else None
            except Exception:
                api_account_id = None

            ref_key = (ord_no, api_account_id)
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)

            filters = {"orderNumber": ord_no}
            if api_account_id is not None:
                filters["api_account_id"] = api_account_id

            upd_res = update_records(
                model=OrderHeader,
                filters=filters,
                update_data={
                    "is_extracted": True,
                    "extracted_at": now_ts,
                },
            )
            if not upd_res.success:
                failed.append((f"{ord_no}/{api_account_id}", upd_res.message))
                continue

            affected = int((upd_res.data or {}).get("affected", 0) or 0)
            if affected > 0:
                updated_any = True

        if not updated_any and not failed:
            return Result.fail("Güncellenecek sipariş bulunamadı.", close_dialog=False)

        if failed:
            msg = "\n".join([f"{o} -> {m}" for o, m in failed])
            return Result.fail(f"Bazı OrderHeader kayıtları güncellenemedi:\n{msg}", close_dialog=False)

        return Result.ok("OrderHeader flag update OK.", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ============================================================
# Optional: direct action (UI layer) - standalone usage
# ============================================================
def action_create_labels_from_selected_orders(
    list_widget: Any,
    *,
    brand_code: str = "TANEX",
    model_code: str = "TANEX_2736",
) -> Result:
    """
    UI ile konuşan katman.
    - list_widget.get_selected_orders() üzerinden seçili orderNumber'ları alır
    - pipeline'a order_numbers gönderir
    """
    try:
        nums_res = extract_order_numbers_from_list_widget(list_widget)
        if not nums_res.success:
            return nums_res

        order_numbers = nums_res.data["order_numbers"]

        call_kwargs = {"brand_code": brand_code, "model_code": model_code}
        if (nums_res.data or {}).get("order_refs_complete"):
            call_kwargs["order_refs"] = list((nums_res.data or {}).get("order_refs") or [])
        return _label_pipeline("create_order_label_from_orders")(order_numbers, **call_kwargs)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
