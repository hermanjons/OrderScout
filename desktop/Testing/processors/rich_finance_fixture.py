"""Linked finance/logistics inputs for an explicitly isolated rich seed.

The entry point refuses the configured live database. All application imports
are lazy so the caller can configure isolation before loading domain settings.
Money is gross TRY; commission is a separate debit, never also subtracted from
sale netAmount. PDF copies are real files with a normal invoice layout and an
explicit footer identifying their local, unofficial origin.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
import json
import math


COMMISSION_RATE = 15.0
SERVICE_GROSS = 13.19
PACKAGING_GROSS = 4.80
PROTECTIVE_PACKAGING_GROSS = 2.40
_LOCAL_TZ = timezone(timedelta(hours=3))
_UNOFFICIAL_NOTE = "Yerel örnek kayıtlardan oluşturulmuştur; resmî fatura değildir."


def _money(value: Any) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _require(result: Any, operation: str) -> Any:
    if not getattr(result, "success", False):
        raise RuntimeError(f"{operation}: {getattr(result, 'message', 'Operation failed')}")
    return result


def _month_start(now: datetime, offset: int) -> datetime:
    month_index = now.year * 12 + now.month - 1 + offset
    year, month = divmod(month_index, 12)
    return now.replace(year=year, month=month + 1, day=1, hour=10, minute=0, second=0, microsecond=0)


def _stamp(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=_LOCAL_TZ)
    return int(value.timestamp() * 1000)


def _month_text(stamp: int) -> str:
    return datetime.fromtimestamp(stamp / 1000, _LOCAL_TZ).strftime("%Y%m")


def _vat(gross: float, rate: float = 20.0) -> float:
    return _money(Decimal(str(gross)) * Decimal(str(rate)) / (Decimal(100) + Decimal(str(rate))))


def _invoice_pdf(path: Path, *, number: str, date: datetime, issuer: str,
                 recipient: str, rows: list[tuple[str, float]], vat_amount: float,
                 reference: str = "") -> None:
    """Write a readable, selectable-text invoice copy without network assets."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    regular = next((candidate for candidate in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ) if candidate.is_file()), None)
    font = "Helvetica"
    if regular:
        font = "OrderScoutSeedBody"
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font, str(regular)))
    styles = getSampleStyleSheet()
    body = ParagraphStyle("SeedBody", parent=styles["Normal"], fontName=font,
                          fontSize=9, leading=13, textColor=colors.HexColor("#243342"))
    title = ParagraphStyle("SeedTitle", parent=body, fontSize=20, leading=25, spaceAfter=8 * mm)
    small = ParagraphStyle("SeedSmall", parent=body, fontSize=8, leading=11)
    right = ParagraphStyle("SeedRight", parent=body, alignment=TA_RIGHT)
    total = _money(sum(amount for _, amount in rows))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=(210 * mm, 297 * mm),
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=20 * mm, bottomMargin=24 * mm,
                            title=f"Fatura sureti {number}", author=issuer)
    p = lambda text, style=body: Paragraph(escape(str(text)), style)
    story: list[Any] = [p("Fatura sureti", title)]
    info = Table([
        [p(issuer), p(f"Belge no: {number}", right)],
        [p(f"Alıcı: {recipient}"), p(f"Tarih: {date.strftime('%d.%m.%Y')}", right)],
        [p("Para birimi: TRY"), p(f"Referans: {reference or number}", right)],
    ], colWidths=[85 * mm, 85 * mm])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([info, Spacer(1, 9 * mm)])
    grid = [[p("Açıklama"), p("KDV dahil tutar (TRY)", right)]]
    grid.extend([[p(label), p(f"{amount:,.2f}", right)] for label, amount in rows])
    table = Table(grid, colWidths=[122 * mm, 48 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f5")),
        ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor("#a9bac9")),
        ("LINEBELOW", (0, 1), (-1, -1), .25, colors.HexColor("#dfe5eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.extend([table, Spacer(1, 7 * mm),
                  p(f"KDV hariç: {total - vat_amount:,.2f} TRY", right),
                  p(f"KDV: {vat_amount:,.2f} TRY", right),
                  p(f"Genel toplam: {total:,.2f} TRY", right)])

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d3dce5"))
        canvas.line(20 * mm, 20 * mm, 190 * mm, 20 * mm)
        canvas.setFont(font, 7.5)
        canvas.setFillColor(colors.HexColor("#607080"))
        canvas.drawString(20 * mm, 15 * mm, _UNOFFICIAL_NOTE)
        canvas.drawRightString(190 * mm, 15 * mm, f"{_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def seed_finance_fixture(db_name: str, *, accounts: list[dict[str, Any]],
                         products: list[dict[str, Any]], orders: list[dict[str, Any]],
                         companies: list[dict[str, Any]], assets_root: str | Path,
                         now: datetime) -> dict[str, Any]:
    """Populate the passed staged DB; ``orders[].account_id`` is ApiAccount.pk.

    Requires existing accounts, products, stock movements, listings and orders.
    ``accounts[].account_id`` is the separate fictional marketplace seller ID.
    Caller must pass an empty finance fixture; repeat invocation is rejected.
    """
    from settings import DB_NAME
    from sqlmodel import Session, select
    from Core.utils.model_utils import get_engine
    from Finance.models.trendyol.models import (
        FinanceManualTransaction, FinanceInvoiceDocument, FinanceTransaction,
        FinanceCargoInvoiceItem, FinanceCostItem,
    )
    from Finance.processors.catalog import finance_builtin_cost_item_records
    from Finance.processors.trendyol.pipeline import (
        save_finance_transactions_to_db, save_finance_cargo_items_to_db,
    )
    from Finance.views.actions import (
        save_finance_cost_item, save_finance_cargo_tariff,
        save_manual_finance_transaction, save_finance_invoice_document,
    )
    from Listing.models.models import ListingProduct
    from Listing.processors.pipeline import set_listing_cost_snapshots
    from Logistics.processors.catalog import builtin_cargo_provider_records
    from Logistics.models.models import LogisticsCargoProvider, LogisticsCargoTariff
    from Logistics.processors.pipeline import accept_logistics_cargo_provider
    from Marketplaces.models.models import Marketplace
    from Marketplaces.processors.pipeline import accept_marketplace
    from Orders.models.trendyol.models import OrderData
    from Stock.models.models import StockTx
    from Stock.constants.domain_constants import StockTxDirection
    from Stock.processors.pipeline import database_scope, update_tx_attachments

    database = Path(db_name).resolve()
    if database == Path(DB_NAME).resolve():
        raise ValueError("Finance fixture only writes an explicitly staged database.")
    if not database.is_file():
        raise ValueError("Initialize and seed the staged database before finance.")
    if not accounts or not companies:
        raise ValueError("Finance fixture requires accounts and synthetic counterparties.")
    current = now.replace(tzinfo=_LOCAL_TZ) if now.tzinfo is None else now.astimezone(_LOCAL_TZ)
    now_ms = _stamp(current)
    engine = get_engine(str(database))
    with Session(engine) as session:
        for model in (FinanceTransaction, FinanceCargoInvoiceItem,
                      FinanceManualTransaction, FinanceInvoiceDocument):
            if session.exec(select(model.pk).limit(1)).first() is not None:
                raise ValueError("Finance fixture requires empty transaction/document tables.")

    _require(accept_marketplace("TRENDYOL", db_name=str(database)), "Accept marketplace")
    wanted_providers = {"ARASMP", "YKMP", "TEXMP"}
    for provider in builtin_cargo_provider_records(platform_code="TRENDYOL"):
        if provider.get("cargoProviderCode") in wanted_providers:
            _require(accept_logistics_cargo_provider(provider, db_name=str(database)), "Accept cargo provider")
    with Session(engine) as session:
        platform = session.exec(select(Marketplace).where(Marketplace.code == "TRENDYOL")).one()
        platform_pk, platform_source_id = int(platform.pk), int(platform.sourceId)
        provider_rows = session.exec(select(LogisticsCargoProvider).where(
            LogisticsCargoProvider.platformCode == "TRENDYOL")).all()
        provider_info = {row.cargoProviderCode: {"pk": int(row.pk), "source_id": int(row.sourceId),
                                               "name": row.cargoProviderName}
                         for row in provider_rows if row.cargoProviderCode in wanted_providers}
    if set(provider_info) != wanted_providers:
        raise ValueError("Canonical cargo providers were not accepted completely.")

    for card in finance_builtin_cost_item_records():
        payload = dict(card)
        payload["sourceId"] = payload.get("sourceId") or payload.get("source_id")
        payload["sourceType"] = "builtin"
        payload["isBuiltin"] = True
        _require(save_finance_cost_item(payload, db_name=str(database)), "Save canonical cost card")
    _require(save_finance_cost_item({
        "costKey": "koruyucu-ambalaj-demo", "name": "Koruyucu iç ambalaj-demo",
        "description": "Kırılabilir ürünler için ek koruyucu dolgu malzemesi.",
        "valueType": "numeric", "defaultMatchMode": "manual", "defaultAmount": PROTECTIVE_PACKAGING_GROSS,
        "currency": "TRY", "isVatIncluded": True, "vatRate": 20.0,
        "supportedPlatformSourceIds": [platform_source_id], "supportedSourceTypes": ["manual_value"],
        "defaultSourceType": "manual_value", "isActive": True,
    }, db_name=str(database)), "Save protective packaging card")

    tariff_amounts = [(0.0, 3.0, 39.90), (3.01, 6.0, 59.90),
                      (6.01, 15.0, 84.90), (15.01, 100.0, 129.90)]
    for code in sorted(wanted_providers):
        for index, (minimum, maximum, amount) in enumerate(tariff_amounts, 1):
            _require(save_finance_cargo_tariff({
                "tariffKey": f"DEMO-{code}-{index}",
                "name": f"{code} {minimum:g}-{maximum:g} desi-demo",
                "description": "Yerel siparişlerde kullanılan sözleşmeli kargo tarifesi.",
                "platform": "TRENDYOL", "platformSourceId": platform_source_id,
                "cargoProviderCode": code, "cargoProviderSourceId": provider_info[code]["source_id"],
                "minDesi": minimum, "maxDesi": maximum,
                "minSalePrice": 0, "maxSalePrice": 10_000_000,
                "amount": amount, "currency": "TRY", "isVatIncluded": True,
                "vatRate": 20, "isActive": True,
            }, db_name=str(database)), "Save synthetic cargo tariff")

    account_by_pk = {int(row["pk"]): row for row in accounts}
    product_by_barcode = {str(row["barcode"]): row for row in products}
    company_by_pk = {int(row["pk"]): row for row in companies}
    default_company = companies[0]
    service_company = next((company for company in companies
                            if "hizmet" in str(company["name"]).casefold()), default_company)
    cargo_company = next((company for company in companies
                          if "lojistik" in str(company["name"]).casefold()), default_company)
    with Session(engine) as session:
        listing_rows = session.exec(select(ListingProduct)).all()
        listing_info = [{"pk": int(row.pk), "api_account_id": row.api_account_id,
                         "product_id": row.product_id, "barcode": row.barcode,
                         "sale_price": float(row.sale_price or 0)} for row in listing_rows]
        snapshot_rows = session.exec(select(OrderData).order_by(OrderData.lastModifiedDate)).all()
        package_info = {(int(row.api_account_id), int(row.id)): row for row in snapshot_rows}
        purchase_rows = session.exec(select(StockTx).where(StockTx.direction == StockTxDirection.IN_)).all()
        stock_inputs = [row.model_dump() for row in purchase_rows]
        cost_rows = session.exec(select(FinanceCostItem)).all()
        cost_ids = {row.costKey: int(row.pk) for row in cost_rows}

    def cargo_price(desi: float) -> float:
        rounded = max(1, math.ceil(desi))
        return next((amount for minimum, maximum, amount in tariff_amounts
                     if minimum <= rounded <= maximum), tariff_amounts[-1][2])

    for listing in listing_info:
        product = product_by_barcode.get(str(listing["barcode"]))
        if product is None:
            continue
        unit_desi = max(1, math.ceil(float(product["length_cm"]) * float(product["width_cm"]) *
                                   float(product["height_cm"]) / 3000))
        snapshots = []
        for key, value, source_type, source_config in (
            ("komisyon", _money(listing["sale_price"] * COMMISSION_RATE / 100), "manual_value", {"amount": COMMISSION_RATE}),
            ("paketleme", PACKAGING_GROSS, "manual_value", {"amount": PACKAGING_GROSS}),
            ("platform-hizmet-bedeli", SERVICE_GROSS, "manual_value", {"amount": 10.99}),
            ("koruyucu-ambalaj-demo", PROTECTIVE_PACKAGING_GROSS, "manual_value", {"amount": PROTECTIVE_PACKAGING_GROSS}),
            ("kargo", cargo_price(unit_desi), "builtin_resolver", {
                "ruleKey": "cargo_amount_matcher", "cargoProviderId": provider_info["ARASMP"]["pk"],
                "cargoProviderCode": "ARASMP", "cargoProviderName": provider_info["ARASMP"]["name"]}),
        ):
            vat = _vat(value)
            snapshots.append({"status": "append", "cost_item_id": cost_ids[key], "cost_key": key,
                              "source_type": source_type, "source_config": source_config,
                              "resolved_amount": value, "resolved_net_amount": _money(value - vat),
                              "resolved_vat_amount": vat, "currency": "TRY",
                              "created_at": _month_start(current, -12).astimezone(timezone.utc).replace(tzinfo=None),
                              "resolution_meta": {"resolved": True, "vat_rate": 20.0}})
        _require(set_listing_cost_snapshots(listing_id=listing["pk"], snapshot_rows=snapshots,
                                           db_name=str(database)), "Save listing cost snapshots")

    transactions: list[dict[str, Any]] = []
    cargo_items: list[dict[str, Any]] = []
    invoice_groups: dict[tuple[str, int, str], list[tuple[str, float]]] = defaultdict(list)
    invoice_dates: dict[tuple[str, int, str], int] = {}
    invoice_vats: dict[tuple[str, int, str], float] = defaultdict(float)
    sales_sample: dict[tuple[int, str], dict[str, Any]] = {}
    totals = {"sales_gross_try": 0.0, "refunds_gross_try": 0.0,
              "commission_gross_try": 0.0, "commission_reversals_gross_try": 0.0,
              "cargo_gross_try": 0.0, "service_gross_try": 0.0}

    def tx(order, kind, date, *, credit=0.0, debt=0.0, barcode=None, suffix="", invoice=None,
           commission=0.0):
        account_pk = int(order["account_id"])
        account = account_by_pk[account_pk]
        transactions.append({
            "api_account_id": account_pk, "sellerId": int(account["account_id"]),
            "serviceKey": "settlements" if kind in {"Sale", "Return"} else "otherfinancials",
            "recordId": f"DEMO-{order['orderNumber']}-{kind}-{suffix or len(transactions)}",
            "transactionType": kind, "description": f"{kind} / {order['orderNumber']}",
            "transactionDate": int(date), "orderDate": int(order["orderDate"]),
            "paymentDate": int(date) + 14 * 86400_000 if int(date) + 14 * 86400_000 <= now_ms else None,
            "paymentOrderId": f"ODE-{account_pk}-{_month_text(int(date))}" if int(date) + 14 * 86400_000 <= now_ms else None,
            "paymentPeriod": int(_month_text(int(date))), "receiptId": int(order["package_id"]) + 900_000_000,
            "affiliate": "TRENDYOL", "orderNumber": order["orderNumber"],
            "shipmentPackageId": order["package_id"], "barcode": barcode,
            "currency": "TRY", "country": "TR", "debt": _money(debt), "credit": _money(credit),
            "netAmount": _money(credit - debt), "sellerRevenue": _money(credit - debt),
            "commissionRate": COMMISSION_RATE if commission else None,
            "commissionAmount": _money(commission) if commission else None,
            "commissionInvoiceSerialNumber": invoice,
            "storeId": int(account["account_id"]), "storeName": account["comp_name"],
            "storeAddress": "Tedarik Sokak No: 18, İstanbul",
        })

    for order in orders:
        account_pk = int(order["account_id"])
        if account_pk not in account_by_pk:
            raise ValueError("An order uses an unknown local API account key.")
        status = str(order.get("status") or "").casefold()
        if status == "cancelled":
            continue
        delivered_at = order.get("delivered_at")
        lines = list(order.get("lines") or [])
        total = _money(order["totalPrice"])
        return_info = dict(order.get("return") or {})
        accepted = str(return_info.get("status") or "").casefold() in {
            "accepted", "approved", "returned", "refunded", "completed", "acceptedreturn"}
        if delivered_at is not None and int(delivered_at) <= now_ms:
            date = int(delivered_at)
            month = _month_text(date)
            invoice = f"KOM-{account_pk}-{month}-demo"
            commission_total = 0.0
            observed_revenue = 0.0
            for line in lines:
                amount = line.get("lineNetAmount")
                if amount is None:
                    amount = float(line.get("lineGrossAmount") or float(line.get("price") or 0) * int(line["quantity"])) - float(line.get("lineTotalDiscount") or 0)
                amount = _money(amount)
                observed_revenue += amount
                commission = _money(amount * COMMISSION_RATE / 100)
                commission_total += commission
                tx(order, "Sale", date, credit=amount, barcode=line.get("barcode"), suffix=str(line["id"]),
                   invoice=invoice)
            if abs(_money(observed_revenue) - total) > .02:
                raise ValueError(f"Order line totals differ from order total for {order['orderNumber']}.")
            commission_total = _money(commission_total)
            tx(order, "CommissionAgreementInvoice", date, debt=commission_total,
               invoice=invoice, commission=commission_total)
            tx(order, "FinancialItem", date, debt=SERVICE_GROSS, suffix="service",
               invoice=f"HIZ-{account_pk}-{month}-demo")
            commission_key = ("commission", account_pk, month)
            invoice_groups[commission_key].append((f"Komisyon / {order['orderNumber']}", commission_total))
            invoice_dates[commission_key] = max(date, invoice_dates.get(commission_key, 0))
            invoice_vats[commission_key] += _vat(commission_total)
            service_key = ("service", account_pk, month)
            invoice_groups[service_key].append((f"Platform hizmeti / {order['orderNumber']}", SERVICE_GROSS))
            invoice_dates[service_key] = max(date, invoice_dates.get(service_key, 0))
            invoice_vats[service_key] += _vat(SERVICE_GROSS)
            totals["sales_gross_try"] += total
            totals["commission_gross_try"] += commission_total
            totals["service_gross_try"] += SERVICE_GROSS
            sales_sample.setdefault((account_pk, month), order)
            if accepted and int(return_info.get("date") or 0) <= now_ms:
                refund = min(total, _money(return_info.get("totalPrice")))
                refund_date = int(return_info.get("date") or date)
                refund_commission = _money(commission_total * refund / total) if total else 0.0
                tx(order, "Return", refund_date, debt=refund, suffix="refund")
                tx(order, "ReturnInvoice", refund_date, credit=refund_commission,
                   suffix="commission-reversal", commission=-refund_commission,
                   invoice=f"IAD-{account_pk}-{_month_text(refund_date)}-demo")
                reversal_key = ("commission_return", account_pk, _month_text(refund_date))
                invoice_groups[reversal_key].append((f"İade komisyon düzeltmesi / {order['orderNumber']}", refund_commission))
                invoice_dates[reversal_key] = max(refund_date, invoice_dates.get(reversal_key, 0))
                invoice_vats[reversal_key] += _vat(refund_commission)
                totals["refunds_gross_try"] += refund
                totals["commission_reversals_gross_try"] += refund_commission

        if status in {"shipped", "delivered", "undelivered", "undeliveredandreturned",
                      "atcollectionpoint", "returned"} or delivered_at is not None:
            shipment = package_info.get((account_pk, int(order["package_id"])))
            ship_date = min(now_ms, int(getattr(shipment, "originShipmentDate", None) or delivered_at or
                                        (int(order["orderDate"]) + 2 * 86400_000)))
            month = _month_text(ship_date)
            invoice = f"KRG-{account_pk}-{month}-demo"
            desi = float(getattr(shipment, "cargoDeci", None) or 0)
            if desi <= 0:
                desi = sum(float(product_by_barcode[str(line["barcode"])]["length_cm"]) *
                           float(product_by_barcode[str(line["barcode"])]["width_cm"]) *
                           float(product_by_barcode[str(line["barcode"])]["height_cm"]) /
                           3000 * int(line["quantity"]) for line in lines)
            desi = max(1, math.ceil(desi))
            charge = cargo_price(desi)
            tx(order, "DeductionInvoices", ship_date, debt=charge, suffix="cargo", invoice=invoice)
            cargo_items.append({"api_account_id": account_pk,
                                "sellerId": int(account_by_pk[account_pk]["account_id"]),
                                "invoiceSerialNumber": invoice, "parcelUniqueId": order["package_id"],
                                "orderNumber": order["orderNumber"], "shipmentPackageType": "Outbound",
                                "amount": charge, "desi": desi})
            key = ("cargo", account_pk, month)
            invoice_groups[key].append((f"Gönderi / {order['orderNumber']} / {desi:g} desi", charge))
            invoice_dates[key] = max(ship_date, invoice_dates.get(key, 0))
            invoice_vats[key] += _vat(charge)
            totals["cargo_gross_try"] += charge

    _require(save_finance_transactions_to_db(transactions, db_name=str(database)), "Save finance transactions")
    _require(save_finance_cargo_items_to_db(cargo_items, db_name=str(database)), "Save cargo invoice items")
    documents = Path(assets_root).resolve() / "invoices"
    documents.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    def document(number, kind, stamp, issuer, recipient, rows, vat_amount, *, account_pk=None,
                 company_pk=None, source_table=None, source_pk=None, reference=None):
        path = documents / f"{number}.pdf"
        _invoice_pdf(path, number=number, date=datetime.fromtimestamp(stamp / 1000, _LOCAL_TZ),
                     issuer=issuer, recipient=recipient, rows=rows, vat_amount=_money(vat_amount),
                     reference=str(reference or number))
        _require(save_finance_invoice_document({
            "invoiceNumber": number, "invoiceType": kind, "invoiceDate": stamp,
            "dueDate": stamp + 14 * 86400_000, "company_id": company_pk,
            "counterparty": issuer, "totalAmount": _money(sum(amount for _, amount in rows)),
            "vatAmount": _money(vat_amount), "currency": "TRY", "filePath": str(path),
            "marketplace_id": platform_pk if account_pk else None, "api_account_id": account_pk,
            "sourceTable": source_table, "sourcePk": source_pk,
            "sourceReference": str(reference or number), "note": _UNOFFICIAL_NOTE,
        }, db_name=str(database)), "Save invoice document")
        paths.append(str(path))
        return str(path)

    number_prefix = {"cargo": "KRG", "commission": "KOM", "service": "HIZ", "commission_return": "IAD"}
    for (kind, account_pk, month), rows in sorted(invoice_groups.items()):
        issuer = "Trendyol Hizmetleri-demo" if kind != "cargo" else cargo_company["name"]
        document(f"{number_prefix[kind]}-{account_pk}-{month}-demo",
                 "cargo" if kind == "cargo" else "commission" if kind == "commission" else "expense",
                 invoice_dates[(kind, account_pk, month)], issuer, account_by_pk[account_pk]["comp_name"],
                 rows, invoice_vats[(kind, account_pk, month)], account_pk=account_pk,
                 company_pk=int(cargo_company["pk"]) if kind == "cargo" else None,
                 source_table="trendyol_finance_transaction")

    manual_count = 0
    manual_total = 0.0
    categories = [("rent", "Depo kira gideri", 12_900.0), ("utilities", "Elektrik ve internet", 1_140.0),
                  ("software", "Yazılım aboneliği", 420.0), ("marketing", "Pazarlama gideri", 2_160.0)]
    for offset in range(-11, 1):
        date = _month_start(current, offset).replace(day=5)
        if date > current:
            continue
        month = date.strftime("%Y%m")
        number = f"GDR-{month}-demo"
        rows = [(label, _money(amount * (1 + (offset + 11) * .012))) for _, label, amount in categories]
        path = document(number, "expense", _stamp(date), service_company["name"], accounts[0]["comp_name"],
                        rows, sum(_vat(amount) for _, amount in rows), company_pk=int(service_company["pk"]))
        for (key, label, _), (_, amount) in zip(categories, rows):
            result = _require(save_manual_finance_transaction({
                "transactionDate": _stamp(date), "direction": "expense", "categoryKey": key,
                "categoryName": f"{label}-demo", "description": f"{date:%Y-%m} / {label}",
                "referenceNo": f"{number}-{key}", "amount": amount, "currency": "TRY",
                "isVatIncluded": True, "vatRate": 20.0, "company_id": int(service_company["pk"]),
                "counterparty": service_company["name"], "paymentMethod": "Banka havalesi",
                "attachments": [path], "note": "Yerel işletme kayıtları.",
            }, db_name=str(database)), "Save operating expense")
            manual_count += 1
            manual_total += amount

    purchases: dict[tuple[str, int], list[tuple[str, float]]] = defaultdict(list)
    purchase_dates: dict[tuple[str, int], int] = {}
    purchase_tx_ids: dict[tuple[str, int], list[int]] = defaultdict(list)
    for row in stock_inputs:
        reason = str(getattr(row.get("reason"), "value", row.get("reason")) or "")
        if reason != "manual_in" or not row.get("unit_cost"):
            continue
        occurred = row["occurred_at"]
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        date_ms = int(occurred.timestamp() * 1000)
        company_pk = int(row.get("company_id") or default_company["pk"])
        if company_pk not in company_by_pk:
            company_pk = int(default_company["pk"])
        key = (_month_text(date_ms), company_pk)
        amount = _money(float(row["qty"]) * float(row["unit_cost"]))
        product = next((product for product in products if int(product["stock_item_id"]) == int(row["item_id"])), None)
        label = product["title"] if product else "Stok malzemesi-demo"
        purchases[key].append((f"{label} / {row['qty']:g} adet", amount))
        purchase_tx_ids[key].append(int(row["pk"]))
        purchase_dates[key] = max(date_ms, purchase_dates.get(key, 0))
    for (month, company_pk), rows in sorted(purchases.items()):
        company = company_by_pk[company_pk]
        number = f"ALS-{company_pk}-{month}-demo"
        amount = _money(sum(amount for _, amount in rows))
        path = document(number, "purchase", purchase_dates[(month, company_pk)], company["name"],
                        accounts[0]["comp_name"], rows, sum(_vat(value) for _, value in rows), company_pk=company_pk)
        _require(save_manual_finance_transaction({
            "transactionDate": purchase_dates[(month, company_pk)], "direction": "expense",
            "categoryKey": "inventory-purchase", "categoryName": "Stok mal alımı-demo",
            "description": f"{month} stok girişleri", "referenceNo": number,
            "amount": amount, "currency": "TRY", "isVatIncluded": True, "vatRate": 20.0,
            "company_id": company_pk, "counterparty": company["name"], "paymentMethod": "Banka havalesi",
            "attachments": [path], "note": "Tutar, bağlı stok girişlerinin miktar ve maliyet toplamıdır.",
        }, db_name=str(database)), "Save inventory purchase expense")
        with database_scope(str(database)):
            for tx_id in purchase_tx_ids[(month, company_pk)]:
                _require(update_tx_attachments(tx_id=tx_id, attachments=json.dumps([path], ensure_ascii=False)),
                         "Attach purchase invoice to stock movement")
        manual_count += 1
        manual_total += amount

    for (account_pk, month), order in sorted(sales_sample.items()):
        rows = []
        vat_amount = 0.0
        for line in order["lines"]:
            amount = _money(line.get("lineNetAmount") if line.get("lineNetAmount") is not None else
                            float(line.get("lineGrossAmount") or float(line["price"]) * int(line["quantity"])) -
                            float(line.get("lineTotalDiscount") or 0))
            product = product_by_barcode.get(str(line["barcode"]), {})
            rows.append((f"{product.get('title', 'Ürün-demo')} / {line['quantity']} adet", amount))
            vat_amount += _vat(amount, float(line.get("vatRate") or 0))
        document(f"STS-{account_pk}-{month}-demo", "sales", int(order["delivered_at"]),
                 account_by_pk[account_pk]["comp_name"], "Perakende Müşteri-demo", rows, vat_amount,
                 account_pk=account_pk, source_table="trendyol_order_header", source_pk=int(order["header_pk"]),
                 reference=order["orderNumber"])

    with Session(engine) as session:
        counts = {model.__tablename__: len(session.exec(select(model.pk)).all()) for model in (
            FinanceTransaction, FinanceCargoInvoiceItem, FinanceManualTransaction,
            FinanceInvoiceDocument, FinanceCostItem, LogisticsCargoProvider, LogisticsCargoTariff)}
    return {"counts": counts, "invoice_files": paths, "invoice_directory": str(documents),
            "commission_rate_percent": COMMISSION_RATE, "manual_rows_created": manual_count,
            "manual_expense_gross_try": _money(manual_total),
            "totals": {key: _money(value) for key, value in totals.items()},
            "bank_balance_observed": False, "settlement_realization_observed": False}


__all__ = ["seed_finance_fixture", "COMMISSION_RATE"]
