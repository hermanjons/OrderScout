# ============================================================
# 🧠 CORE IMPORTS
# ============================================================
from __future__ import annotations

from PyQt6.QtWidgets import QListWidgetItem
from PyQt6.QtCore import Qt
from datetime import datetime, date

# Core utilities & base classes
from Core.views.views import SwitchButton, ListSmartItemWidget
from Core.threads.async_worker import AsyncWorker
from Core.threads.sync_worker import SyncWorker
from Core.utils.model_utils import get_engine
from Core.utils.time_utils import coerce_to_date, time_for_now, time_stamp_calculator
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message
from settings import MEDIA_ROOT

# ============================================================
# 🧩 DOMAIN IMPORTS
# ============================================================
from Orders.processors.trendyol_pipeline import (
    fetch_orders_all,
    save_orders_to_db,
    get_latest_ready_to_ship_orders,
    get_nonfinal_order_numbers, normalize_order_data
)
from Orders.constants.trendyol_constants import TRENDYOL_STATUS_LIST
from Account.models import ApiAccount
from Account.views.actions import collect_selected_companies, get_company_by_id

from Orders.api.trendyol_api import TrendyolApi


# ============================================================
# 🔹 1. OrdersListWidget — Liste render & seçim yönetimi
# ============================================================
# Bu bölüm doğrudan `OrdersListWidget` sınıfının arka planında çalışır.
# Liste oluşturma, sipariş özet biçimlendirme, seçim toplama vb. işlemleri içerir.
# ============================================================

def resolve_order_logo_path(order) -> str:
    """
    🧩 Bağlantılı: OrdersListWidget
    Siparişin bağlı olduğu hesabın logosunu döndürür.
    Eğer hesapta logo yoksa varsayılan sipariş görseli döner.
    """
    logo = getattr(getattr(order, "api_account", None), "logo_path", None)
    return logo or "images/orders_img.png"


def format_order_summary(order) -> dict:
    """
    🧩 Bağlantılı: OrdersListWidget
    Siparişin UI’da gösterilecek metinlerini biçimlendirir.
    (Liste kartları, detay sayfası, PDF çıktısı vb. yerlerde tekrar kullanılabilir.)
    """
    total = getattr(order, "totalPrice", 0)
    try:
        total_fmt = f"{float(total):,.2f}".replace(",", ".")  # Örn: 1.234.50 ₺
    except Exception:
        total_fmt = total

    date_part = getattr(order, "orderDate", None)
    date_str = date_part.strftime("%d.%m.%Y") if isinstance(date_part, datetime) else str(date_part or "—")

    return {
        "title": f"Sipariş: {getattr(order, 'orderNumber', '—')}",
        "subtitle": f"Müşteri: {getattr(order, 'customerFirstName', '—')} {getattr(order, 'customerLastName', '')}",
        "extra": f"Kargo: {getattr(order, 'cargoProviderName', '-')} | "
                 f"Tarih: {date_str} | Tutar: {total_fmt} ₺",
        "identifier": getattr(order, "orderNumber", "—"),
        "logo_path": resolve_order_logo_path(order),
    }


def build_order_list(list_widget, orders: list, interaction_cb=None, selection_cb=None) -> Result:
    """
    🧩 Bağlantılı: OrdersListWidget
    Sipariş listesini QListWidget içine render eder.
    Performans için setUpdatesEnabled kullanılır.
    """
    try:
        list_widget.setUpdatesEnabled(False)
        list_widget.clear()

        if not orders:
            info_item = QListWidgetItem("Gösterilecek sipariş bulunamadı.")
            info_item.setFlags(info_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            list_widget.addItem(info_item)
            return Result.ok("Liste boş, sipariş bulunamadı.", data={"count": 0})

        added = 0
        for order in orders:
            display = format_order_summary(order)
            switch = SwitchButton()

            item_widget = ListSmartItemWidget(
                title=display["title"],
                subtitle=display["subtitle"],
                extra=display["extra"],
                identifier=display["identifier"],
                icon_path=display["logo_path"],
                optional_widget=switch,
            )

            if interaction_cb:
                item_widget.interaction.connect(interaction_cb)
            if selection_cb:
                item_widget.selectionRequested.connect(selection_cb)

            item = QListWidgetItem(list_widget)
            item.setSizeHint(item_widget.sizeHint())
            list_widget.setItemWidget(item, item_widget)
            added += 1

        return Result.ok(f"{added} sipariş başarıyla listelendi.", data={"count": added})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)
    finally:
        list_widget.setUpdatesEnabled(True)


def collect_selected_orders(list_widget) -> Result:
    """
    🧩 Bağlantılı: OrdersListWidget, OrdersManagerWindow
    QListWidget içindeki SwitchButton'lara bakarak seçili siparişleri döndürür.
    """
    try:
        selected = []
        for i in range(list_widget.count()):
            w = list_widget.itemWidget(list_widget.item(i))
            if not w:
                continue
            btn = getattr(w, "right_widget", None)
            if btn and btn.isChecked():
                selected.append(w.identifier)

        if not selected:
            return Result.fail("Hiçbir sipariş seçilmedi.", close_dialog=False)

        return Result.ok(f"{len(selected)} sipariş seçildi.",
                         data={"selected_orders": selected},
                         close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def extract_cargo_names(orders: list) -> list[str]:
    """
    🧩 Bağlantılı: OrdersManagerWindow (cargo_filter)
    Sipariş listesinden tekrarsız ve alfabetik sıralı kargo firma adlarını döndürür.
    """
    return sorted({
        getattr(o, "cargoProviderName", "").strip()
        for o in orders if getattr(o, "cargoProviderName", None)
    })


# ============================================================
# 🔹 2. OrdersManagerWindow — Pipeline’dan veri yükleme
# ============================================================
# Bu bölüm filtreleme penceresinin (OrdersManagerWindow) iş mantığını destekler.
# Yani filtrelemeden önce DB'den verileri almak veya kargo listesini güncellemek gibi.
# ============================================================

def load_ready_to_ship_orders() -> Result:
    """
    ReadyToShip siparişleri pipeline’dan çeker ve UI’ye döndürür.
    DEBUG: is_extracted ve is_printed ekrana yazılır.
    """
    try:
        result = get_latest_ready_to_ship_orders()
        if not result.success:
            return result

        orders = result.data.get("orders", [])

        print("\n===== DEBUG: RTS ORDERS (load_ready_to_ship_orders) =====")
        for od in orders:
            print(
                f"Order {getattr(od, 'orderNumber', None)} | "
                f"is_extracted={getattr(od, 'is_extracted', None)} | "
                f"is_printed={getattr(od, 'is_printed', None)}"
            )
        print("===== DEBUG END =====\n")

        return Result.ok("ReadyToShip siparişler yüklendi.",
                         data={"records": orders})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


def refresh_cargo_filter(combo_box, orders: list) -> Result:
    """
    🧩 Bağlantılı: OrdersManagerWindow._refresh_cargo_filter()
    Kargo firmalarını combobox’a doldurur (UI-safe).
    """
    try:
        combo_box.blockSignals(True)
        combo_box.clear()
        combo_box.addItem("Tümü")
        cargos = extract_cargo_names(orders)
        combo_box.addItems(cargos)
        return Result.ok(f"{len(cargos)} kargo firması yüklendi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)
    finally:
        combo_box.blockSignals(False)


# ============================================================
# 🔹 3. OrdersTab — API'den sipariş çekme (Trendyol)
# ============================================================
# Bu bölüm Trendyol API’sinden veri çekme, kaydetme ve progress yönetimini içerir.
# Yani `OrdersTab` içindeki “BAŞLAT” butonu ve `CircularProgressButton` akışı.
# ============================================================


async def _refresh_nonfinal_orders_async(
        order_numbers: list[str],
        comp_api_account_list: list,
        progress_callback=None,
) -> Result:
    """
    Non-final (Delivered / Cancelled olmayan) siparişleri,
    orderNumber üzerinden Trendyol'dan tekrar çekip normalize eder.

    Dönüş: save_orders_to_db ile uyumlu olacak şekilde
        Result.data = {
            "order_data_list": [...],
            "order_item_list": [...],
        }
    """
    try:
        if not order_numbers:
            return Result.ok(
                "Güncellenecek non-final sipariş bulunamadı.",
                close_dialog=False,
                data={"order_data_list": [], "order_item_list": []},
            )

        all_orders: list[dict] = []
        all_items: list[dict] = []

        total_steps = max(len(order_numbers) * len(comp_api_account_list), 1)
        current_step = 0

        for comp_api_account in comp_api_account_list:
            api_account_id = comp_api_account[0]
            supplier_id = comp_api_account[1]
            username = comp_api_account[2]
            password = comp_api_account[3]

            api = TrendyolApi(supplier_id, username, password)

            for order_no in order_numbers:
                res = await api.get_order_by_number(order_no)

                if not res or not isinstance(res, Result):
                    current_step += 1
                    if progress_callback:
                        progress_callback(current_step, total_steps)
                    continue

                if not res.success:
                    current_step += 1
                    if progress_callback:
                        progress_callback(current_step, total_steps)
                    continue

                content = res.data.get("content", []) or []
                if not content:
                    current_step += 1
                    if progress_callback:
                        progress_callback(current_step, total_steps)
                    continue

                for raw_order in content:
                    norm_orders, norm_items = await normalize_order_data(raw_order, api_account_id)
                    all_orders.extend(norm_orders)
                    all_items.extend(norm_items)

                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_steps)

        return Result.ok(
            f"{len(all_orders)} adet order_data, {len(all_items)} adet order_item normalize edildi.",
            close_dialog=False,
            data={
                "order_data_list": all_orders,
                "order_item_list": all_items,
            }
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


def get_orders_from_companies(parent_widget, company_list_widget, progress_target) -> Result:
    """
    🧩 Bağlantılı: OrdersTab.get_orders()
    Seçilen şirketlerden API bilgilerini alır ve worker zincirini başlatır.
    (Async → API, ardından Sync → DB kaydı)
    """
    try:
        # 1️⃣ Seçilen şirketleri topla
        result = collect_selected_companies(company_list_widget)
        if not result.success:
            return result

        selected_company_pks = result.data["selected_company_pks"]

        # 2️⃣ API credential’ları getir
        res_creds = get_company_by_id(selected_company_pks)
        if not res_creds.success:
            return res_creds

        comp_api_account_list = res_creds.data.get("accounts", [])
        if not comp_api_account_list:
            return Result.fail("Seçili şirketler için API bilgisi bulunamadı.", close_dialog=False)

        # 3️⃣ Tarih aralığı belirle
        search_range_hour = 200
        start_ep_time = time_for_now()
        final_ep_time = time_for_now() - time_stamp_calculator(search_range_hour)

        # 4️⃣ Async Worker (API)
        parent_widget.api_worker = AsyncWorker(
            fetch_orders_all,
            TRENDYOL_STATUS_LIST,
            final_ep_time,
            start_ep_time,
            comp_api_account_list,
            kwargs={"progress_callback": lambda c, t: update_progress(progress_target, c, t)},
            parent=parent_widget
        )

        # 🧩 Callback zinciri
        def handle_api_result(res: Result):
            if not res.success:
                parent_widget.on_orders_failed(res, progress_target)
                return

            # ✅ API başarılı → DB Worker başlat
            parent_widget.db_worker = SyncWorker(save_orders_to_db, res)

            def handle_db_result(db_res: Result):
                if not db_res.success:
                    parent_widget.on_orders_failed(db_res, progress_target)
                else:
                    # Normal akış: UI'yi güncelle
                    parent_widget.on_orders_fetched(db_res)

                    # 🔥 BURADAN SONRASI: ARKA PLAN NON-FINAL SENKRONU
                    try:
                        print("işlem başlıyor")
                        # 1) DB'den final olmayan sipariş numaralarını çek
                        res_nonfinal = get_nonfinal_order_numbers()
                        if not res_nonfinal.success:
                            print("başarısız")
                            return
                        print("işlem devam ediyor")

                        order_numbers = res_nonfinal.data.get("order_numbers", []) or []
                        print(order_numbers)
                        if not order_numbers:
                            return  # güncellenecek non-final sipariş yoksa boşver

                        # 2) Arka planda Trendyol senkronu için AsyncWorker başlat
                        parent_widget.bg_api_worker = AsyncWorker(
                            _refresh_nonfinal_orders_async,
                            order_numbers,
                            comp_api_account_list,
                            kwargs={"progress_callback": None},  # tamamen sessiz
                            parent=parent_widget
                        )

                        def handle_bg_api(bg_res: Result):
                            # sessiz çalışacak, hata bile olsa mesaj yok
                            if not bg_res or not isinstance(bg_res, Result) or not bg_res.success:
                                return

                            parent_widget.bg_db_worker = SyncWorker(save_orders_to_db, bg_res)

                            def handle_bg_db(_db_res: Result):
                                # İstersen burada log yazarsın; kullanıcıya mesaj yok.
                                pass

                            parent_widget.bg_db_worker.result_ready.connect(handle_bg_db)
                            parent_widget.bg_db_worker.start()

                        parent_widget.bg_api_worker.result_ready.connect(handle_bg_api)
                        parent_widget.bg_api_worker.start()

                    except Exception:
                        # Arka plan hataları kullanıcıya gösterilmeyecek.
                        return

            parent_widget.db_worker.result_ready.connect(handle_db_result)
            parent_widget.db_worker.start()

        parent_widget.api_worker.result_ready.connect(handle_api_result)
        parent_widget.api_worker.start()

        return Result.ok("Worker başlatıldı.", close_dialog=False)

    except Exception as e:
        msg = map_error_to_message(e)
        return Result.fail(msg, error=e, close_dialog=False)


def update_progress(view_instance, current: int, total: int):
    """
    🧩 Bağlantılı: OrdersTab.get_orders()
    Progress butonunun yüzdesini günceller.
    """
    try:
        percent = int(current / total * 100) if total else 0
        view_instance.setProgress(percent)
        return Result.ok(f"Progress {percent}% olarak güncellendi.", close_dialog=False)
    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ============================================================
# 🔹 4. Filtreleme Yönetimi (OrdersManagerWindow.apply_filters)
# ============================================================
# Bu kısım filtrelerin asenkron çalıştırılması, tarih uyumluluğu ve
# CPU dostu arama optimizasyonlarını içerir.
# ============================================================

def get_order_date(order) -> date | None:
    """
    🧩 Yardımcı fonksiyon — bir siparişin tarih alanını normalize eder.
    """
    for attr in ("shipmentDate", "orderDate", "createdDate"):
        val = getattr(order, attr, None)
        coerced = coerce_to_date(val)
        if coerced:
            return coerced
    return None


def filter_orders(orders: list, filters: dict) -> Result:
    """
    🧩 Bağlantılı: OrdersManagerWindow.apply_filters()
    Sipariş listesini filtre parametrelerine göre süzer.
    """
    try:
        filtered = list(orders)

        # 🟣 Yazdırma / çıkartma durumu filtresi
        #  - "pending"   → hem is_printed = False hem is_extracted = False
        #  - "processed" → is_printed = True veya is_extracted = True
        #  - "all"       → durum filtresi yok
        processed_mode = filters.get("processed_mode", "pending")

        if processed_mode in ("pending", "processed"):
            tmp = []
            for o in filtered:
                is_pr = bool(getattr(o, "is_printed", False))
                is_ex = bool(getattr(o, "is_extracted", False))

                if processed_mode == "pending":
                    # Hiç işlenmemiş (ne yazdırılmış ne çıkartılmış)
                    if not is_pr and not is_ex:
                        tmp.append(o)
                else:  # processed
                    # En az bir işlem görmüş
                    if is_pr or is_ex:
                        tmp.append(o)
            filtered = tmp

        # ========================================================
        # 🔍 Diğer filtreler (senin mevcut mantığın)
        # ========================================================
        gtxt = filters.get("global", "").lower()
        order_no = filters.get("order_no", "").lower()
        cargo = filters.get("cargo")
        customer = filters.get("customer", "").lower()
        date_enabled = filters.get("date_enabled", False)
        df = filters.get("date_from")
        dt = filters.get("date_to")

        # --- Genel arama
        if gtxt:
            gtxt = gtxt.strip()
            temp = []
            for o in filtered:
                items = getattr(o, "items", [])
                in_items = any(
                    gtxt in str(getattr(it, "productName", "")).lower()
                    or gtxt in str(getattr(it, "productSku", "")).lower()
                    for it in items
                )
                in_order = any(
                    gtxt in str(getattr(o, f, "")).lower()
                    for f in ("orderNumber", "cargoProviderName", "customerFirstName")
                )
                if in_items or in_order:
                    temp.append(o)
            filtered = temp

        # --- Sipariş no
        if order_no:
            filtered = [o for o in filtered if order_no in str(getattr(o, "orderNumber", "")).lower()]

        # --- Kargo filtresi
        if cargo and cargo != "Tümü":
            filtered = [o for o in filtered if getattr(o, "cargoProviderName", None) == cargo]

        # --- Müşteri filtresi
        if customer:
            filtered = [o for o in filtered if customer in str(getattr(o, "customerFirstName", "")).lower()]

        # --- Tarih filtresi
        if date_enabled and df and dt:
            tmp = []
            for o in filtered:
                for attr in ("shipmentDate", "orderDate", "createdDate"):
                    d = coerce_to_date(getattr(o, attr, None))
                    if d and df <= d <= dt:
                        tmp.append(o)
                        break
            filtered = tmp

        return Result.ok("Filtre uygulandı.", data={"filtered": filtered})

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e)


def start_filter_worker(parent_widget, list_widget, filters: dict) -> SyncWorker:
    """
    🧩 Bağlantılı: OrdersManagerWindow.apply_filters()
    SyncWorker'ı başlatır, filtre işlemini arka planda yapar.
    UI donmadan sonucu parent’a bildirir.
    """
    worker = SyncWorker(filter_orders, list_widget.orders, filters)

    def handle_result(result: Result):
        if not result.success:
            MessageHandler.show(parent_widget, result, only_errors=True)
            parent_widget.selected_count_label.setText("⚠️ Filtreleme başarısız.")
            return

        filtered = result.data.get("filtered", [])
        list_widget.apply_filter_result(filtered)
        list_widget.filtered_orders = filtered
        parent_widget._update_label()
        parent_widget.selected_count_label.setText(f"✅ Filtre tamamlandı. (Kalan: {len(filtered)})")

    worker.result_ready.connect(handle_result)
    return worker
