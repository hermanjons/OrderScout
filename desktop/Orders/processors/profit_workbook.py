"""Orders-owned profit projection over the shared verified workbook primitives."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from Core.processors import report_artifacts
from Core.processors.report_artifacts import ReportColumn, ReportSheetSnapshot, ReportSnapshot
from Feedback.processors.pipeline import Result, map_error_to_message
from Orders.processors.profit import _amount_text, _optional_float, _safe_str


def normalize_profit_output_path(output_path: str | Path) -> Path:
    if not _safe_str(output_path):
        raise ValueError("Excel export icin output_path gerekir.")
    path = Path(output_path).expanduser()
    return path if path.suffix.casefold() == ".xlsx" else path.with_suffix(".xlsx")


def build_profit_report_snapshot(*, order_number: str, estimated_profit_payload: Mapping[str, Any],
                                api_account_id: int | None = None) -> ReportSnapshot:
    """Project an existing estimate; this operation never recalculates profit."""
    if (not isinstance(estimated_profit_payload, Mapping)
            or not isinstance(estimated_profit_payload.get("estimated_profit_detail"), Mapping)
            or not isinstance(estimated_profit_payload.get("estimated_profit_ready"), bool)):
        raise ValueError("A calculated profit payload with an explicit ready status is required.")
    payload = dict(estimated_profit_payload)
    detail = dict(payload["estimated_profit_detail"])
    results = dict(detail.get("results") or {})
    summary = dict(detail.get("summary") or {})
    lines = [row for row in detail.get("lines") or [] if isinstance(row, dict)]
    number = _safe_str(order_number) or _safe_str(summary.get("order_number"))
    if not number:
        raise ValueError("Profit workbook requires an order number.")
    summary_number = _safe_str(summary.get("order_number"))
    if summary_number and summary_number != number:
        raise ValueError("Profit payload belongs to a different order.")
    sale = results.get("sale_price")
    if sale is None:
        sale = summary.get("sale_price")
    cost_text = _safe_str(results.get("total_costs_text")) or _amount_text(_optional_float(results.get("total_costs")))
    profit_text = _safe_str(payload.get("estimated_profit_text")) or _safe_str(results.get("estimated_profit_text")) or "-"
    summary_rows = (
        ("Sipariş", number),
        ("Toplam ürün adedi", _safe_str(summary.get("item_quantity_total_text")) or "-"),
        ("Toplam satış", _amount_text(_optional_float(sale))),
        ("Toplam maliyet", cost_text),
        ("Tahmini kar", profit_text),
        ("Durum", "Hazır" if payload["estimated_profit_ready"] else "Bekliyor"),
    )
    sales_rows = tuple((
        _safe_str(line.get("title")) or "Ürün", _safe_str(line.get("listing_title")),
        _safe_str(line.get("qty_text")) or "-", _safe_str(line.get("unit_price_text")) or "-",
        _safe_str(line.get("amount_text")) or _amount_text(_optional_float(line.get("amount"))),
    ) for line in lines)
    costs = [row for row in detail.get("applied_costs") or [] if isinstance(row, dict)]
    if not costs:
        costs = [cost for line in lines for cost in (line.get("detail") or {}).get("applied_costs") or []
                 if isinstance(cost, dict)]
    cost_rows = []
    for cost in costs:
        amount = cost.get("gross")
        if amount is None:
            amount = cost.get("value")
        cost_rows.append((
            _safe_str(cost.get("label")) or _safe_str(cost.get("key")) or "Maliyet",
            _safe_str(cost.get("note")), _amount_text(_optional_float(amount)),
        ))
    cost_rows.append(("Maliyet Toplamı", "", cost_text))
    def sheet(name, labels, rows):
        return ReportSheetSnapshot(name=name, columns=tuple(
            ReportColumn(key=f"column_{index}", label=label, width=28 if index == 0 else 58 if index == 1 else 18)
            for index, label in enumerate(labels)
        ), rows=tuple(rows))
    return ReportSnapshot.create(
        title=f"Sipariş kârı: {number}", source_domain="orders", report_type="order_profit",
        filters={"order_number": number, "api_account_id": api_account_id},
        metadata={"estimated_profit_ready": payload["estimated_profit_ready"],
                  "missing_reasons": list(payload.get("estimated_profit_missing_reasons") or [])},
        sheets=(sheet("Ozet", ("Alan", "Değer"), summary_rows),
                sheet("Satis", ("Ürün", "İlan", "Adet", "Birim", "Tutar"), sales_rows),
                sheet("Maliyetler", ("Kalem", "Açıklama", "Tutar"), cost_rows)),
    )


def write_order_profit_payload_to_excel(*, order_number: str, output_path: str,
                                       estimated_profit_payload: Mapping[str, Any],
                                       api_account_id: int | None = None) -> Result:
    try:
        path = normalize_profit_output_path(output_path)
        snapshot = build_profit_report_snapshot(order_number=order_number,
            estimated_profit_payload=estimated_profit_payload, api_account_id=api_account_id)
        result = report_artifacts.export_report_snapshot_xlsx(report_snapshot=snapshot.to_dict(), output_path=str(path))
        if result.success:
            result.data = {**result.data, "order_number": snapshot.filters["order_number"], "exists": True}
        return result
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verify_order_profit_payload_xlsx(*, order_number: str, output_path: str,
                                    estimated_profit_payload: Mapping[str, Any],
                                    api_account_id: int | None = None) -> Result:
    """Read every exported cell against the exact approved estimate and account."""
    phase = "profit_snapshot"
    try:
        path = normalize_profit_output_path(output_path)
        snapshot = build_profit_report_snapshot(order_number=order_number,
            estimated_profit_payload=estimated_profit_payload, api_account_id=api_account_id)
        phase = "workbook_readback"
        verification = report_artifacts.verify_report_snapshot_xlsx(snapshot, path)
        if not verification["verified"]:
            return Result.fail("Kâr Excel içeriği onaylanan hesapla eşleşmiyor.", close_dialog=False, data=verification)
        return Result.ok("Kâr Excel içeriği onaylanan hesapla doğrulandı.", close_dialog=False, data=verification)
    except Exception as exc:
        return Result.fail("Kâr Excel doğrulaması tamamlanamadı.", close_dialog=False, data={
            "verified": False, "phase": phase, "error_type": type(exc).__name__,
        })
