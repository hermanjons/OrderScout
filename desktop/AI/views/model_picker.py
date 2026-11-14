"""Lightweight painted model rows; no per-model QWidget/layout tree."""
from __future__ import annotations

import math
import re
import unicodedata

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPalette
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate


SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
PRESENTATION_ROLE = int(Qt.ItemDataRole.UserRole) + 2


def search_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value).casefold().replace("ı", "i"))
    return " ".join(re.sub(r"[^\w]+", " ", "".join(
        char for char in value if not unicodedata.combining(char))).split())


def model_identity(payload: dict) -> tuple:
    return (payload.get("_source_kind"), payload.get("id"),
            payload.get("default_model") or payload.get("local_path") or payload.get("repo_id"))


def _price(value) -> str | None:
    try:
        number = float(value) * 1_000_000
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return f"${number:.4f}".rstrip("0").rstrip(".") if number else "$0"


def model_presentation(payload: dict, title: str, local_meta: str = "") -> dict:
    kind = payload.get("_source_kind")
    if kind == "cloud_provider_header":
        return {"title": title, "meta": f"{payload.get('_model_count', 0)} model · bağlı",
                "badge": "", "kind": kind, "collapsed": bool(payload.get("_collapsed"))}
    if kind == "local_model":
        plan = payload.get("resource_plan") or {}
        blocked = not payload.get("exists_on_disk", True) or not plan.get("safe_to_run", True)
        badge = "Dosya eksik" if not payload.get("exists_on_disk", True) else "Uygun değil" if blocked else (
            "Yavaş" if plan.get("requires_paging") or plan.get("suitability") == "slow" else "Yerel")
        return {"title": title, "meta": local_meta, "badge": badge, "kind": kind}
    metadata = payload.get("model_metadata") or {}
    pricing = metadata.get("pricing") or {}
    in_price, out_price = _price(pricing.get("prompt")), _price(pricing.get("completion"))
    parts = []
    if metadata.get("is_free"):
        parts.append("Ücretsiz")
    elif in_price is not None and out_price is not None:
        parts.append(f"{in_price} giriş · {out_price} çıkış / 1M token")
    else:
        parts.append("Fiyat bilgisi yok")
    context = metadata.get("context_length") or 0
    if context:
        compact = f"{context / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        parts.append(f"{compact}M bağlam" if context >= 1_000_000 else f"{context // 1000:,}K bağlam")
    capability = metadata.get("capability_profile") or {}
    if capability.get("native_tool_calling_available") or "tools" in (metadata.get("supported_parameters") or []):
        parts.append("Araçlar")
    return {"title": title, "meta": " · ".join(parts), "badge": "", "kind": kind}


class ModelChoiceDelegate(QStyledItemDelegate):
    """Paint only viewport rows; selection follows the actual chosen model."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_identity = None

    def sizeHint(self, option, index):
        row = index.data(PRESENTATION_ROLE) or {}
        return QSize(300, 48 if row.get("kind") == "cloud_provider_header" else 70)

    def paint(self, painter: QPainter, option, index):
        row = index.data(PRESENTATION_ROLE)
        if not isinstance(row, dict):
            return super().paint(painter, option, index)
        payload = index.data(Qt.ItemDataRole.UserRole) or {}
        header = row.get("kind") == "cloud_provider_header"
        selected = not header and model_identity(payload) == self.selected_identity
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(2, 2, -2, -2)
        palette = option.palette
        primary = palette.color(QPalette.ColorRole.Highlight)
        foreground = palette.color(QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        if selected or hover or focused:
            fill = QColor(primary)
            fill.setAlpha(23 if selected else 12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 7, 7)
        left = rect.left() + (10 if header else 14)
        trailing = "⌄" if header and row.get("collapsed") else "⌃" if header else "✓" if selected else row.get("badge", "")
        font = QFont(option.font)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(foreground)
        metrics = painter.fontMetrics()
        badge_width = metrics.horizontalAdvance(trailing) + 14 if trailing else 0
        title_rect = QRect(left, rect.top() + (4 if header else 9), max(0, rect.width() - (left - rect.left()) - badge_width - 10), 22)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         metrics.elidedText(row.get("title", ""), Qt.TextElideMode.ElideRight, title_rect.width()))
        if trailing:
            painter.setPen(primary if selected else muted)
            painter.drawText(QRect(rect.right() - badge_width - 5, rect.top(), badge_width, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, trailing)
        font.setWeight(QFont.Weight.Normal)
        if font.pointSizeF() > 1:
            font.setPointSizeF(max(8, font.pointSizeF() - 1))
        painter.setFont(font)
        painter.setPen(muted)
        meta_rect = QRect(left, rect.top() + (24 if header else 33), max(0, rect.width() - (left - rect.left()) - 12), 22)
        meta = row.get("meta", "").replace("\n", " · ")
        painter.drawText(meta_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         painter.fontMetrics().elidedText(meta, Qt.TextElideMode.ElideRight, meta_rect.width()))
        painter.restore()
