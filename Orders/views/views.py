# ============================================================
# 🧠 CORE IMPORTS
# ============================================================
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
    QListWidget, QPushButton, QLineEdit, QComboBox, QGridLayout,
    QDateEdit, QCheckBox
)

from PyQt6.QtCore import Qt, QDate, QTimer, QRegularExpression, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator, QIcon

from datetime import datetime, date

# Core widgets
from Core.views.views import (
    CircularProgressButton, PackageButton, SwitchButton, ListSmartItemWidget, ActionPulseButton
)
from Core.threads.sync_worker import SyncWorker

# ============================================================
# 🧩 DOMAIN IMPORTS
# ============================================================
from Orders.signals.signals import order_signals
from Orders.views.actions import (
    get_orders_from_companies,
    collect_selected_orders,
    load_ready_to_ship_orders,
    extract_cargo_names,
    build_order_list,
    filter_orders,
    refresh_cargo_filter,
    start_filter_worker
)
from Labels.views.views import LabelPrintManagerWindow

from Account.views.views import CompanyListWidget
from Feedback.processors.pipeline import MessageHandler, Result, map_error_to_message


# ============================================================
# 🔹 1. OrdersListWidget — Sipariş Listeleme Bileşeni
# ============================================================

class OrdersListWidget(QListWidget):
    """
    Siparişleri göstermek için optimize edilmiş özel liste widget'i.
    - Gösterildiğinde kendini otomatik yükler.
    - Sinyal geldiğinde yeniden yükler.
    - Filtreli sonuçları kendisi uygular.
    - Sayfalama: page_size / current_page
    - Seçimler model üzerinde tutulur: order._selected
    """

    # Seçim değişince dışarıya haber veriyoruz
    selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        self.orders: list = []           # DB'den gelen RAW veri (tam liste)
        self.filtered_orders: list = []  # aktif filtre ile gelen sonuçlar (tam liste)

        # ⚡ Dahili durum filtresi:
        self.status_filter: str = "all"  # all | unprocessed | extracted | printed | both

        # 🧾 Sayfalama
        self.page_size: int = 20         # varsayılan: 20 kayıt/sayfa
        self.current_page: int = 1       # 1-based

        # 🔧 Reload sonrası otomatik build yapalım mı?
        # OrdersManagerWindow bu flag'i False yapıyor; böylece ilk açılışta çift repaint olmaz.
        self.auto_build_on_reload: bool = True

        # Siparişler değiştiğinde kendini yenile
        order_signals.orders_changed.connect(self.reload_orders)

    # --------------------------------------------------------
    # 🧾 Sayfalama yardımcıları
    # --------------------------------------------------------
    def get_total_pages(self) -> int:
        total = len(self.filtered_orders or [])
        if total <= 0:
            return 1
        return (total + self.page_size - 1) // self.page_size

    def set_page_size(self, size: int):
        """Sayfa başına gösterilecek kayıt sayısı."""
        if size <= 0:
            return
        self.page_size = size
        self.current_page = 1
        self._safe_build(self.filtered_orders)

    def go_to_page(self, page: int):
        """Belirli sayfaya git."""
        total_pages = self.get_total_pages()
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        self.current_page = page
        self._safe_build(self.filtered_orders)

    def next_page(self):
        self.go_to_page(self.current_page + 1)

    def prev_page(self):
        self.go_to_page(self.current_page - 1)

    # ============================================================
    # 🔄 Yaşam Döngüsü
    # ============================================================
    def showEvent(self, event):
        """Widget ilk gösterildiğinde siparişleri yükle."""
        super().showEvent(event)
        if not self.orders:
            self.reload_orders()

    # --------------------------------------------------------
    # 🗓 Epoch → datetime normalizasyonu (GENEL)
    # --------------------------------------------------------
    def _normalize_epoch_dates(self, orders: list):
        """
        Trendyol API'den gelen epoch timestamp alanlarını datetime'e çevirir.
        - Alan adında 'date' veya 'time' geçen her attribute taranır.
        - Değer int/float/str-digit ise ve epoch aralığındaysa datetime'e çevrilir.
        """
        for o in orders:
            for attr in dir(o):
                if attr.startswith("_"):
                    continue
                lower = attr.lower()
                if "date" not in lower and "time" not in lower:
                    continue

                try:
                    val = getattr(o, attr)
                except AttributeError:
                    continue

                ts = None
                if isinstance(val, (int, float)):
                    ts = val
                elif isinstance(val, str) and val.isdigit():
                    try:
                        ts = int(val)
                    except ValueError:
                        ts = None

                if ts is None:
                    continue

                # epoch saniye: ~1.7e9 civarı, ms: 1.7e12 civarı
                if ts < 10**9:
                    continue

                try:
                    if ts > 10**11:  # büyük olasılıkla ms
                        dt = datetime.fromtimestamp(ts / 1000)
                    else:            # saniye
                        dt = datetime.fromtimestamp(ts)
                    setattr(o, attr, dt)
                except Exception:
                    continue

    # ============================================================
    # 🔄 Ana Yeniden Yükleme
    # ============================================================
    def reload_orders(self):
        """
        DB'den siparişleri ÇALIŞAN THREAD içinde çekip,
        UI'yi minimum yükle günceller.
        """

        self.reload_worker = SyncWorker(load_ready_to_ship_orders)

        def handle_reload_result(result: Result):
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                return

            # RAW veriyi al
            self.orders = result.data.get("records", []) or []

            # Epoch tarihleri normalize et
            self._normalize_epoch_dates(self.orders)

            # reload sonrasında dış filtrelerin base'i: tüm siparişler
            self.filtered_orders = list(self.orders)

            # default sayfa
            self.current_page = 1

            # 🔧 Bu widget için auto_build açıksa hemen build et,
            # kapalıysa sadece sinyal at, OrdersManagerWindow kendi filtresiyle build edecek.
            if getattr(self, "auto_build_on_reload", True):
                self.set_status_filter(self.status_filter)

            # Sinyal (OrdersManagerWindow filtreleri vs. buraya bağlı)
            order_signals.orders_loaded.emit(self.filtered_orders)

        self.reload_worker.result_ready.connect(handle_reload_result)
        self.reload_worker.start()

    # ============================================================
    # 🎚 DIŞTAN GELEN FİLTRE
    # ============================================================
    def apply_filter_result(self, filtered_orders: list):
        """
        FilterWorker'dan gelen text / tarih / kargo filtreleri.
        Bu filtrelerin ÜZERİNE işlem durumu filtresini uygularız.
        """
        # Dış filtre sonucu bizim base listemiz olsun
        self.filtered_orders = list(filtered_orders or [])
        self.current_page = 1
        self.set_status_filter(self.status_filter)

    # ============================================================
    # 🧠 Dahili İşlem Durumu Filtresi
    # ============================================================
    def set_status_filter(self, mode: str):
        """
        OrdersManagerWindow tarafından çağrılabilir.
        mode: all | unprocessed | extracted | printed | both
        """
        self.status_filter = mode

        base = list(self.filtered_orders or [])
        final = self._apply_internal_status_filter(base)
        self.filtered_orders = final

        # filtre değişince başa dön
        self.current_page = 1
        self._safe_build(self.filtered_orders)

    def _apply_internal_status_filter(self, orders: list):
        """
        is_extracted / is_printed alanlarına göre filtre uygular.
        """
        mode = self.status_filter

        if mode == "all":
            return list(orders)

        result = []

        for o in orders:
            ex = getattr(o, "is_extracted", False)
            pr = getattr(o, "is_printed", False)

            if mode == "unprocessed":
                if not ex and not pr:
                    result.append(o)

            elif mode == "extracted":
                if ex and not pr:
                    result.append(o)

            elif mode == "printed":
                if pr:
                    result.append(o)

            elif mode == "both":
                if ex and pr:
                    result.append(o)

        return result

    # ============================================================
    # 🧰 Listeyi İnşa Et (Sayfalama + Seçim Sync)
    # ============================================================
    def _safe_build(self, orders: list):
        """
        'orders' = TAM filtreli liste.
        Buradan sadece current_page / page_size kadarını render ederiz.
        Seçimler order._selected üzerinden tutulur, UI ile sync edilir.
        """
        try:
            all_orders = list(orders or [])
            total = len(all_orders)

            # UI repaint yükünü azalt
            self.setUpdatesEnabled(False)

            # Eski widget'ları temizle
            for i in range(self.count()):
                widget = self.itemWidget(self.item(i))
                if widget:
                    widget.deleteLater()
            self.clear()

            if total == 0:
                self.setUpdatesEnabled(True)
                self.viewport().update()
                return

            # Sayfalama hesapları
            page_size = max(1, int(getattr(self, "page_size", 20)))
            total_pages = (total + page_size - 1) // page_size

            if self.current_page < 1:
                self.current_page = 1
            if self.current_page > total_pages:
                self.current_page = total_pages

            start_idx = (self.current_page - 1) * page_size
            end_idx = start_idx + page_size
            show_list = all_orders[start_idx:end_idx]

            result = build_order_list(
                self,
                show_list,
                self.on_item_interaction,
                self.clear_other_selections
            )

            if not result.success:
                self.setUpdatesEnabled(True)
                self.viewport().update()
                MessageHandler.show(self, result, only_errors=True)
                return

            # 🔁 UI'yi modeldeki seçime göre güncelle
            for row, order in enumerate(show_list):
                if getattr(order, "_selected", False):
                    item = self.item(row)
                    if not item:
                        continue
                    widget = self.itemWidget(item)
                    if widget and hasattr(widget, "right_widget"):
                        try:
                            widget.right_widget.blockSignals(True)
                            widget.right_widget.setChecked(True)
                        finally:
                            widget.right_widget.blockSignals(False)

            self.setUpdatesEnabled(True)
            self.viewport().update()

        except Exception as e:
            self.setUpdatesEnabled(True)
            self.viewport().update()
            msg = map_error_to_message(e)
            MessageHandler.show(self, Result.fail(msg, error=e), only_errors=True)

    # ============================================================
    # 🎯 Event Callbacks
    # ============================================================
    def on_item_interaction(self, identifier, value: bool):
        """
        Toggle değiştiğinde seçim durumunu model üzerinde güncelle.
        Mevcut sayfadaki tüm widget'ları okuyup filtered_orders içindeki ilgili kayda yansıtıyoruz.
        """
        all_orders = list(self.filtered_orders or [])
        total = len(all_orders)
        if total == 0:
            self.selection_changed.emit()
            return

        page_size = max(1, int(getattr(self, "page_size", 20)))
        total_pages = (total + page_size - 1) // page_size
        if self.current_page < 1:
            self.current_page = 1
        if self.current_page > total_pages:
            self.current_page = total_pages

        start_idx = (self.current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total)

        for row, idx in enumerate(range(start_idx, end_idx)):
            order = all_orders[idx]
            item = self.item(row)
            if not item:
                continue
            widget = self.itemWidget(item)
            if widget and hasattr(widget, "right_widget"):
                checked = bool(widget.right_widget.isChecked())
                setattr(order, "_selected", checked)

        # Dışarıya "seçim değişti" diye haber ver
        self.selection_changed.emit()

    def clear_other_selections(self, keep_widget):
        """Tek seçim modu için dursun, şu an kullanılmıyor."""
        for i in range(self.count()):
            widget = self.itemWidget(self.item(i))
            if widget is not keep_widget and hasattr(widget, "set_selected"):
                widget.set_selected(False)

    def get_selected_orders(self) -> list:
        """
        Seçili siparişleri döndür.
        - Tüm sayfalar / tüm filtreli liste üzerinden bakar.
        """
        return [o for o in (self.filtered_orders or []) if getattr(o, "_selected", False)]


# ============================================================
# 🔹 2. OrdersManagerWindow — Filtreleme + Sayfalama Penceresi
# ============================================================

class OrdersManagerWindow(QWidget):
    """
    Kargoya hazır siparişleri yöneten ana pencere.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kargoya Hazır Siparişler")
        # 🧿 Siparişler butonundaki icon ile aynı
        self.setWindowIcon(QIcon("images/orders_img.png"))

        self.setGeometry(200, 200, 1000, 650)

        # === ANA LAYOUT YATAY ===
        main_layout = QHBoxLayout(self)

        # SOL PANEL: filtreler + liste + sayaç + toplu seçim + sayfalama
        left_panel = QVBoxLayout()
        main_layout.addLayout(left_panel, stretch=1)

        # SAĞ PANEL: aksiyon butonu
        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(10, 10, 10, 10)
        right_panel.setSpacing(20)
        main_layout.addLayout(right_panel, stretch=0)

        # ============================================================
        # 📦 Liste Widget
        # ============================================================
        self.list_widget = OrdersListWidget(self)
        # İlk açılışta gereksiz çift repaint olmasın:
        self.list_widget.auto_build_on_reload = False
        # Seçim değişince label + buton + sayfalama güncelle
        self.list_widget.selection_changed.connect(self._on_selection_changed)

        # ============================================================
        # 🔍 Filtre Paneli
        # ============================================================
        filter_box = QGroupBox("Filtreler")
        filter_layout = QGridLayout(filter_box)

        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Genel Ara (müşteri, ürün, sipariş no, kargo...)")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Sipariş No Ara...")
        numeric_validator = QRegularExpressionValidator(QRegularExpression(r"^\d*$"))
        self.search_input.setValidator(numeric_validator)

        self.cargo_filter = QComboBox()
        self.cargo_filter.addItem("Tümü")

        self.customer_input = QLineEdit()
        self.customer_input.setPlaceholderText("Müşteri Adı Ara...")

        self.date_filter_enable = QCheckBox("Tarih filtresini uygula")
        self.date_filter_enable.setChecked(False)

        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd.MM.yyyy")
        self.date_from.setFixedWidth(130)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd.MM.yyyy")
        self.date_to.setFixedWidth(130)
        self.date_to.setDate(QDate.currentDate())

        self.date_from.setStyleSheet("QDateEdit { padding: 3px; border-radius: 4px; }")
        self.date_to.setStyleSheet("QDateEdit { padding: 3px; border-radius: 4px; }")

        self._toggle_date_inputs(self.date_filter_enable.isChecked())
        self.date_filter_enable.stateChanged.connect(
            lambda _: self._toggle_date_inputs(self.date_filter_enable.isChecked())
        )

        # 🟣 İşlenme durumu filtresi
        self.processed_filter = QComboBox()
        self.processed_filter.addItem("Yazdırılmayı / Çıkartılmayı Bekleyenler", userData="pending")
        self.processed_filter.addItem("İşlenmiş Siparişler (Yazdırılmış / Çıkartılmış)", userData="processed")
        self.processed_filter.addItem("Tümü", userData="all")
        self.processed_filter.setCurrentIndex(0)

        # Debounce timer
        self.filter_timer = QTimer()
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.apply_filters)

        # filtre input'larını debounce'a bağla
        inputs = [
            self.global_search,
            self.search_input,
            self.customer_input,
            self.cargo_filter,
            self.date_filter_enable,
            self.date_from,
            self.date_to,
            self.processed_filter,
        ]
        for w in inputs:
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._trigger_debounce)
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(self._trigger_debounce)
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(self._trigger_debounce)
            elif hasattr(w, "dateChanged"):
                w.dateChanged.connect(self._trigger_debounce)

        # filtre layout yerleşimi
        filter_layout.addWidget(QLabel("Genel Ara:"), 0, 0)
        filter_layout.addWidget(self.global_search, 0, 1, 1, 3)
        filter_layout.addWidget(QLabel("Sipariş No:"), 1, 0)
        filter_layout.addWidget(self.search_input, 1, 1)
        filter_layout.addWidget(QLabel("Kargo:"), 1, 2)
        filter_layout.addWidget(self.cargo_filter, 1, 3)
        filter_layout.addWidget(QLabel("Müşteri:"), 2, 0)
        filter_layout.addWidget(self.customer_input, 2, 1)
        filter_layout.addWidget(self.date_filter_enable, 2, 2)

        dates_row = QHBoxLayout()
        dates_row.addWidget(self.date_from)
        dates_row.addWidget(QLabel(" - "))
        dates_row.addWidget(self.date_to)
        dates_row.addStretch()
        filter_layout.addLayout(dates_row, 2, 3)

        # Durum filtresi satırı
        filter_layout.addWidget(QLabel("Durum:"), 3, 0)
        filter_layout.addWidget(self.processed_filter, 3, 1, 1, 3)

        # sol panel'e ekle
        left_panel.addWidget(filter_box)
        left_panel.addWidget(self.list_widget)

        # ============================================================
        # 📊 Seçim Bilgisi
        # ============================================================
        self.selected_count_label = QLabel("Seçili: 0 / Toplam: 0 (Filtreli: 0)")
        left_panel.addWidget(self.selected_count_label)

        # ============================================================
        # 📑 Sayfalama Paneli
        # ============================================================
        pagination_box = QGroupBox("Sayfalama")
        pagination_layout = QHBoxLayout(pagination_box)

        self.prev_page_btn = QPushButton("◀")
        self.next_page_btn = QPushButton("▶")
        self.pagination_label = QLabel("Sayfa 0/1 | Toplam: 0 kayıt")

        self.page_size_box = QComboBox()
        self.page_size_box.addItems(["20", "50", "100"])
        self.page_size_box.setCurrentText("20")

        self.prev_page_btn.clicked.connect(self._on_prev_page)
        self.next_page_btn.clicked.connect(self._on_next_page)
        self.page_size_box.currentTextChanged.connect(self._on_page_size_changed)

        pagination_layout.addWidget(self.prev_page_btn)
        pagination_layout.addWidget(self.next_page_btn)
        pagination_layout.addWidget(self.pagination_label)
        pagination_layout.addStretch()
        pagination_layout.addWidget(QLabel("Sayfa başına:"))
        pagination_layout.addWidget(self.page_size_box)

        left_panel.addWidget(pagination_box)

        # ============================================================
        # 🚚 Sipariş Yüklendiğinde
        # ============================================================
        order_signals.orders_loaded.connect(self._refresh_cargo_filter)
        order_signals.orders_loaded.connect(self._update_label)
        order_signals.orders_loaded.connect(self._update_action_button_state)
        order_signals.orders_loaded.connect(lambda _orders: self._update_pagination_ui())

        # Sipariş her yüklendiğinde filtreyi otomatik uygula
        order_signals.orders_loaded.connect(lambda _orders: self._trigger_debounce())

        # ============================================================
        # 🧰 Toplu İşlemler
        # ============================================================
        control_box = QGroupBox("Toplu İşlemler")
        control_layout = QHBoxLayout(control_box)

        select_all_btn = QPushButton("Tümünü Seç")
        deselect_all_btn = QPushButton("Seçimi Kaldır")

        # 🔍 Butonları biraz büyüt + göze getir
        select_all_btn.setMinimumHeight(36)
        deselect_all_btn.setMinimumHeight(36)
        select_all_btn.setStyleSheet("QPushButton { font-weight: 600; padding: 6px 14px; }")
        deselect_all_btn.setStyleSheet("QPushButton { padding: 6px 14px; }")

        select_all_btn.clicked.connect(self.select_all)
        deselect_all_btn.clicked.connect(self.deselect_all)

        control_layout.addStretch()
        control_layout.addWidget(select_all_btn)
        control_layout.addWidget(deselect_all_btn)

        left_panel.addWidget(control_box)

        # ============================================================
        # 👉 Sağ Panel: Aksiyon Butonu
        # ============================================================
        self.action_button = ActionPulseButton(text="Yazdır")
        self.action_button.setEnabled(False)  # başta kapalı
        self.action_button.clicked.connect(self._on_action_button_clicked)

        right_panel.addStretch()
        right_panel.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignTop)
        right_panel.addStretch()

        # Pencere açılır açılmaz “bekleyenler” filtresini çalıştır
        QTimer.singleShot(0, self._trigger_debounce)

    # ============================================================
    # 🔁 Seçim değişince çağrılır
    # ============================================================
    def _on_selection_changed(self):
        self._update_label()
        self._update_pagination_ui()

    # ============================================================
    # 🔁 Butonun aktif/pasif olması (seçime göre)
    # ============================================================
    def _update_action_button_state(self):
        selected_list = self.list_widget.get_selected_orders()
        self.action_button.setEnabled(len(selected_list) > 0)

    # ============================================================
    # 🔘 Yazdır Butonu davranışı
    # ============================================================
    def _on_action_button_clicked(self):
        chosen_orders = self.get_selected_orders()
        if not chosen_orders:
            return

        self.label_window = LabelPrintManagerWindow(self)
        self.label_window.exec()
        self.label_window.setWindowModality(Qt.WindowModality.NonModal)
        self.label_window.raise_()
        self.label_window.activateWindow()

    # ============================================================
    # 📑 Sayfalama UI Güncelleme
    # ============================================================
    def _update_pagination_ui(self):
        total = len(self.list_widget.filtered_orders or [])
        page_size = getattr(self.list_widget, "page_size", 20)

        if total == 0:
            total_pages = 1
            current = 0
        else:
            total_pages = (total + page_size - 1) // page_size
            current = getattr(self.list_widget, "current_page", 1)

        self.pagination_label.setText(
            f"Sayfa {current}/{total_pages} | Toplam: {total} kayıt"
        )

        self.prev_page_btn.setEnabled(current > 1)
        self.next_page_btn.setEnabled(current < total_pages)

    def _on_page_size_changed(self, text: str):
        try:
            size = int(text)
        except ValueError:
            size = 20
        self.list_widget.set_page_size(size)
        self._update_label()
        self._update_pagination_ui()

    def _on_prev_page(self):
        self.list_widget.prev_page()
        self._update_label()
        self._update_pagination_ui()

    def _on_next_page(self):
        self.list_widget.next_page()
        self._update_label()
        self._update_pagination_ui()

    # ============================================================
    # Yardımcılar (filtre + label)
    # ============================================================
    def _refresh_cargo_filter(self, orders=None):
        res = refresh_cargo_filter(self.cargo_filter, self.list_widget.orders)
        MessageHandler.show(self, res, only_errors=True)

    def _toggle_date_inputs(self, enabled: bool):
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        self.date_from.setStyleSheet("" if enabled else "color: gray;")
        self.date_to.setStyleSheet("" if enabled else "color: gray;")

    def _trigger_debounce(self):
        self.filter_timer.start(350)

    def apply_filters(self):
        try:
            filters = {
                "global": self.global_search.text().strip(),
                "order_no": self.search_input.text().strip(),
                "cargo": self.cargo_filter.currentText(),
                "customer": self.customer_input.text().strip(),
                "date_enabled": self.date_filter_enable.isChecked(),
                "date_from": self.date_from.date().toPyDate(),
                "date_to": self.date_to.date().toPyDate(),
                "processed_mode": self.processed_filter.currentData() or "pending",
            }

            self.selected_count_label.setText("🔄 Filtre uygulanıyor...")
            self.filter_worker = start_filter_worker(self, self.list_widget, filters)

            # Filtre bittiğinde label + sayfalama güncelle
            def _after_filter(_res: Result):
                self._update_label()
                self._update_pagination_ui()

            self.filter_worker.result_ready.connect(_after_filter)
            self.filter_worker.start()

        except Exception as e:
            msg = map_error_to_message(e)
            MessageHandler.show(self, Result.fail(msg, error=e), only_errors=True)

    def _update_label(self):
        selected = self.list_widget.get_selected_orders()
        total = len(self.list_widget.orders)
        filtered = len(self.list_widget.filtered_orders or [])
        shown = self.list_widget.count()

        extra = ""
        if shown < filtered:
            extra = f" | Gösterilen: {shown} (sayfa)"

        self.selected_count_label.setText(
            f"Seçili: {len(selected)} / Toplam: {total} (Filtreli: {filtered}){extra}"
        )
        self._update_action_button_state()

    def select_all(self):
        """
        Tümünü Seç:
        - Tüm filtrelenmiş siparişlerde order._selected = True
        - Tüm sayfalara yayılır (filtered_orders üzerinden).
        """
        for o in (self.list_widget.filtered_orders or []):
            setattr(o, "_selected", True)

        # Şu anki sayfayı yeniden çizip checkbox'ları güncelle
        self.list_widget._safe_build(self.list_widget.filtered_orders)
        self.list_widget.selection_changed.emit()

    def deselect_all(self):
        """
        Seçimi Kaldır:
        - Tüm filtrelenmiş siparişlerin seçimini kaldırır.
        """
        for o in (self.list_widget.filtered_orders or []):
            if hasattr(o, "_selected"):
                o._selected = False

        self.list_widget._safe_build(self.list_widget.filtered_orders)
        self.list_widget.selection_changed.emit()

    def get_selected_orders(self):
        return self.list_widget.get_selected_orders()


# ============================================================
# 🔹 3. OrdersTab — Ana Tab / Veri Çekme Arayüzü
# ============================================================

class OrdersTab(QWidget):
    """
    OrdersManagerWindow ve veri çekme işlemini yöneten ana sekme bileşeni.
    """

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # 🟡 Üst bilgilendirme yazısı
        self.info_label = QLabel("Siparişleri buradan yönetebilirsin.")

        # 🔵 Ana sipariş yönetim penceresi butonu
        self.order_btn = PackageButton("Siparişler", icon_path="images/orders_img.png")
        self.order_btn.clicked.connect(self.open_orders_window)

        layout.addWidget(self.order_btn)
        layout.addWidget(self.info_label)

        # 🟢 Başlatma butonu (API'den sipariş çekme)
        self.fetch_button = CircularProgressButton("BAŞLAT")
        self.fetch_button.clicked.connect(self.get_orders)

        # 🔴 Şirket listesi → CompanyListWidget
        self.company_list = CompanyListWidget()
        self.company_list.setFixedWidth(240)

        # 🟤 Alt panel: Şirketler + Buton
        self.bottom_panel = QGroupBox("Veri Çekme Paneli")
        self.bottom_panel.setFixedHeight(200)
        bottom_layout = QHBoxLayout(self.bottom_panel)

        company_box = QGroupBox("Şirketler")
        company_layout = QVBoxLayout(company_box)
        company_layout.setContentsMargins(5, 5, 5, 5)
        company_layout.addWidget(self.company_list)
        bottom_layout.addWidget(company_box)

        btn_container = QWidget()
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.addStretch()
        btn_layout.addWidget(self.fetch_button, alignment=Qt.AlignmentFlag.AlignCenter)
        btn_layout.addStretch()
        bottom_layout.addWidget(btn_container)

        layout.addWidget(self.bottom_panel)

        # referanslar
        self.orders_window = None

        # ❌ DİKKAT: Artık orders_loaded / orders_changed'e bağlamıyoruz
        # order_signals.orders_loaded.connect(...)
        # order_signals.orders_changed.connect(...)

    # ============================================================
    # 📡 Siparişleri API'den Getir
    # ============================================================
    def get_orders(self):
        """
        Seçili şirketlerden siparişleri çeker, progress'i başlatır.
        İşlem bitene kadar tekrar basılamaz.
        """
        # Zaten kilitliyse tekrar basılmasın
        if not self.fetch_button.isEnabled():
            return

        # Kilitle
        self.fetch_button.setEnabled(False)

        result = get_orders_from_companies(self, self.company_list, self.fetch_button)
        if not result.success:
            # Worker hiç başlamadan hata döndüyse → hemen butonu aç
            self.fetch_button.fail()
            self.fetch_button.setEnabled(True)
            MessageHandler.show(self, result, only_errors=True)
            self.info_label.setText("⚠️ Siparişler alınırken hata oluştu.")
            return

        self.info_label.setText("⏳ Veri çekiliyor...")

    # ============================================================
    # 🪟 Sipariş Penceresi Aç
    # ============================================================
    def open_orders_window(self):
        """Filtreleme ve listeleme penceresini açar."""
        try:
            if self.orders_window is None:
                self.orders_window = OrdersManagerWindow()
            self.orders_window.show()
            self.orders_window.raise_()
            self.orders_window.activateWindow()
        except Exception as e:
            res = Result.fail(map_error_to_message(e), error=e, close_dialog=False)
            MessageHandler.show(self, res, only_errors=True)

    # ============================================================
    # ⚠️ Worker Callback — Hata Durumu
    # ============================================================
    def on_orders_failed(self, result: Result, button: CircularProgressButton):
        """
        Worker zincirinden gelen hatalarda çalışır.
        Progress butonunu sıfırlar, kullanıcıya hata mesajı gösterir.
        """
        button.fail()
        button.setEnabled(True)
        MessageHandler.show(self, result, only_errors=True)
        self.info_label.setText("⚠️ İşlem başarısız.")

    # ============================================================
    # ✅ Worker Callback — Başarı Durumu
    # ============================================================
    def on_orders_fetched(self, result: Result):
        """
        API ve DB işlemleri başarılı olduğunda çalışır.
        DİKKAT: Burada butona dokunmuyoruz; buton %100 progress'te açılıyor.
        """
        self.info_label.setText("✅ Siparişler başarıyla kaydedildi.")
