from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from purgator.ui.colors import ACCENT, BACKGROUND, TRACK


class RatioBar(QWidget):
    def __init__(self, frac: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frac = max(0.0, min(1.0, frac))

    def set_frac(self, frac: float) -> None:
        self._frac = max(0.0, min(1.0, frac))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(BACKGROUND))

        height = self.height()
        radius = height / 2
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QColor(TRACK))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), height), radius, radius)

        if self._frac > 0.0:
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(QRectF(0, 0, self.width() * self._frac, height), radius, radius)
        painter.end()
