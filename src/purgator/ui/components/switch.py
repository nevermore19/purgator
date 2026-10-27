from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from purgator.ui.colors import ACCENT, BACKGROUND, STRIPE


class Switch(QWidget):
    """A small on/off switch used to enable a scheduled task."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(38, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if checked != self._checked:
            self._checked = checked
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self.height() / 2
        painter.setBrush(QColor(ACCENT) if self._checked else QColor(STRIPE))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        diameter = self.height() - 4
        left = self.width() - diameter - 2 if self._checked else 2
        painter.setBrush(QColor(BACKGROUND))
        painter.drawEllipse(QRectF(left, 2, diameter, diameter))
        painter.end()
