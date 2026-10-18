from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from Core.views.tab_widgets import GlowTabBar, GlowTabWidget


class TestTabWidgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            try:
                widget.close()
            except Exception:
                pass
            try:
                widget.deleteLater()
            except Exception:
                pass
        self._app.processEvents()

    def test_set_tab_icon_invalidates_glow_tab_bar_pixmap_cache(self) -> None:
        tabs = GlowTabWidget()
        self.addCleanup(tabs.deleteLater)
        self.addCleanup(tabs.close)

        pixmap = QPixmap(24, 24)
        pixmap.fill(QColor("#EF4444"))
        icon = QIcon(pixmap)
        index = tabs.addTab(QWidget(), icon, "Orders")
        bar = tabs.tabBar()

        self.assertIsInstance(bar, GlowTabBar)
        assert isinstance(bar, GlowTabBar)
        bar._cached_icon_pixmap(index, icon, 48)
        self.assertTrue(any(key[0] == index for key in bar._icon_pixmap_cache))

        updated = QPixmap(24, 24)
        updated.fill(QColor("#22C55E"))
        tabs.setTabIcon(index, QIcon(updated))

        self.assertFalse(any(key[0] == index for key in bar._icon_pixmap_cache))

    def test_ai_tab_draws_cable_glow_without_covering_label_band(self) -> None:
        tabs = GlowTabWidget()
        self.addCleanup(tabs.deleteLater)
        self.addCleanup(tabs.close)

        icon_pixmap = QPixmap(32, 32)
        icon_pixmap.fill(QColor("#FFFFFF"))
        icon = QIcon(icon_pixmap)
        for label in ("Siparişler", "Stok", "İlanlar", "Pazaryerleri", "Finans", "Lojistik", "AI"):
            tabs.addTab(QWidget(), icon, label)
        tabs.resize(1500, 130)
        tabs.show()

        tabs.setCurrentIndex(0)
        self._app.processEvents()
        inactive_image = tabs.tabBar().grab().toImage()

        tabs.setCurrentIndex(6)
        self._app.processEvents()
        ai_image = tabs.tabBar().grab().toImage()

        def green_pixels(image, *, y0: int, y1: int) -> int:
            count = 0
            for y in range(max(0, y0), min(image.height(), y1)):
                for x in range(image.width()):
                    color = image.pixelColor(x, y)
                    if color.green() > color.red() + 18 and color.green() > color.blue() + 8:
                        count += 1
            return count

        upper_band_before = green_pixels(inactive_image, y0=8, y1=44)
        upper_band_after = green_pixels(ai_image, y0=8, y1=44)
        label_band_after = green_pixels(ai_image, y0=78, y1=105)

        self.assertGreater(upper_band_after, upper_band_before + 60)
        self.assertLess(label_band_after, upper_band_after)


if __name__ == "__main__":
    unittest.main()
