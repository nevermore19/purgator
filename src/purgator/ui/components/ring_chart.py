from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from purgator.ui.colors import ACCENT, BACKGROUND, TRACK


class RingChart(QWidget):
    def __init__(self, used_frac: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._used = max(0.0, min(1.0, used_frac))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(BACKGROUND))

        side = self.width()
        band = side * 0.085
        outer_radius = side * 0.43
        radius = outer_radius - band / 2
        cx = self.width() / 2
        cy = self.height() / 2
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

        track_pen = QPen(QColor(TRACK))
        track_pen.setWidthF(band)
        painter.setPen(track_pen)
        painter.drawEllipse(rect)

        if self._used >= 1.0:
            used_pen = QPen(QColor(ACCENT))
            used_pen.setWidthF(band)
            painter.setPen(used_pen)
            painter.drawEllipse(rect)
        elif self._used > 0.0:
            used_pen = QPen(QColor(ACCENT))
            used_pen.setWidthF(band)
            used_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(used_pen)
            span = int(round(self._used * 360 * 16))
            painter.drawArc(rect, 90 * 16, span)
        painter.end()
