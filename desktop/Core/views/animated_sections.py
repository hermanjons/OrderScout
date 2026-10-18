from __future__ import annotations

from PyQt6.QtCore import QSize, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QSizePolicy, QWidget


class SmoothHeightFrame(QFrame):
    expansionFinished = pyqtSignal(bool)
    heightProgressChanged = pyqtSignal()

    def __init__(self, parent=None, *, duration_ms: int = 700):
        super().__init__(parent)
        self._expanded = False
        self._duration_ms = max(0, int(duration_ms))
        self._target_height = 0
        self._step_px = 1
        self._height_timer = QTimer(self)
        self._height_timer.setInterval(16)
        self._height_timer.timeout.connect(self._step_animation)
        self.setMinimumHeight(0)
        self.setMaximumHeight(0)
        self.setVisible(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def isExpanded(self) -> bool:
        return bool(self._expanded)

    def isAnimating(self) -> bool:
        return self._height_timer.isActive()

    def targetHeight(self) -> int:
        return max(0, int(self._target_height))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def sizeHint(self) -> QSize:
        maximum_height = max(0, int(self.maximumHeight()))
        if maximum_height >= 16777215:
            maximum_height = self.expandedHeight()
        return QSize(0, maximum_height)

    def expandedHeight(self) -> int:
        layout = self.layout()
        if layout is not None:
            margins = layout.contentsMargins()
            spacing = max(0, int(layout.spacing()))
            height = int(margins.top() + margins.bottom())
            measured_items = 0
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item is None:
                    continue
                widget = item.widget()
                if widget is not None:
                    item_height = self._widget_height_hint(widget)
                elif item.layout() is not None:
                    hint = item.layout().sizeHint()
                    item_height = max(0, int(hint.height()))
                else:
                    hint = item.sizeHint()
                    item_height = max(0, int(hint.height()))
                if item_height <= 0:
                    continue
                if measured_items:
                    height += spacing
                height += item_height
                measured_items += 1
            if measured_items:
                return max(1, height)
            layout.activate()
            return max(1, int(layout.sizeHint().height()))
        return max(1, int(super().sizeHint().height()))

    @staticmethod
    def _widget_height_hint(widget: QWidget) -> int:
        hint_height = int(widget.sizeHint().height())
        if hint_height > 0:
            return hint_height
        min_height = int(widget.minimumHeight())
        max_height = int(widget.maximumHeight())
        if min_height > 0 and max_height < 16777215:
            return min(max_height, min_height)
        if min_height > 0:
            return min_height
        if max_height > 0 and max_height < 16777215:
            return max_height
        return max(0, int(widget.height()))

    def refreshExpandedHeight(self, *, animated: bool = False) -> None:
        if not self._expanded:
            return
        target = self.expandedHeight()
        if animated and self._duration_ms > 0:
            self._animate_to(target)
            return
        self._height_timer.stop()
        self.setMaximumHeight(target)
        self.updateGeometry()

    def setExpanded(self, expanded: bool, *, animated: bool = True) -> None:
        expanded = bool(expanded)
        if expanded:
            self._expanded = True
            self.setVisible(True)
            target = self.expandedHeight()
            if animated and self._duration_ms > 0:
                self._animate_to(target)
            else:
                self._height_timer.stop()
                self.setMaximumHeight(target)
                self.updateGeometry()
            return

        self._expanded = False
        start = max(0, int(self.height()))
        if start <= 0:
            start = self.expandedHeight()
        if animated and self._duration_ms > 0 and not self.isHidden():
            self._animate_to(0, start=start)
            return
        self._height_timer.stop()
        self.setMaximumHeight(0)
        self.setVisible(False)
        self.updateGeometry()

    def _animate_to(self, target: int, *, start: int | None = None) -> None:
        current = max(0, int(self.maximumHeight() if start is None else start))
        target = max(0, int(target))
        self._target_height = target
        delta = abs(target - current)
        if delta <= 0:
            self._on_animation_finished()
            return
        ticks = max(1, int(round(max(16, self._duration_ms) / 16)))
        self._step_px = max(2, min(8, int((delta + ticks - 1) // ticks)))
        self._height_timer.start()

    def _step_animation(self) -> None:
        current = max(0, int(self.maximumHeight()))
        target = self.targetHeight()
        if current == target:
            self._height_timer.stop()
            self._on_animation_finished()
            return
        direction = 1 if target > current else -1
        next_height = current + direction * min(abs(target - current), self._step_px)
        self.setMaximumHeight(max(0, int(next_height)))
        self.updateGeometry()
        self.heightProgressChanged.emit()
        if next_height == target:
            self._height_timer.stop()
            self._on_animation_finished()

    def hideEvent(self, event) -> None:
        self._height_timer.stop()
        super().hideEvent(event)

    def _on_animation_finished(self) -> None:
        if not self._expanded:
            self.setMaximumHeight(0)
            self.setVisible(False)
        else:
            self.setMaximumHeight(self.expandedHeight())
            self.setVisible(True)
        self.updateGeometry()
        self.heightProgressChanged.emit()
        self.expansionFinished.emit(self._expanded)
