from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QDateEdit, QTimeEdit

from purgator.ui import colors

CHEVRON_HALF_WIDTH = 4.0
CHEVRON_HEIGHT = 4.0
CHEVRON_RIGHT_OFFSET = 12.0


def _paint_chevron(
    painter: QPainter, center_x: float, center_y: float, pointing_down: bool
) -> None:
    pen = QPen(QColor(colors.ACCENT), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    if pointing_down:
        outer_y = center_y - CHEVRON_HEIGHT / 2
        tip_y = center_y + CHEVRON_HEIGHT / 2
    else:
        outer_y = center_y + CHEVRON_HEIGHT / 2
        tip_y = center_y - CHEVRON_HEIGHT / 2
    painter.drawPolyline(
        [
            QPointF(center_x - CHEVRON_HALF_WIDTH, outer_y),
            QPointF(center_x, tip_y),
            QPointF(center_x + CHEVRON_HALF_WIDTH, outer_y),
        ]
    )


def _paint_dropdown_chevron(painter: QPainter, width: int, height: int) -> None:
    _paint_chevron(
        painter,
        width - CHEVRON_RIGHT_OFFSET,
        height / 2,
        pointing_down=True,
    )


class DropdownComboBox(QComboBox):
    """A combo box with a small chevron that marks it as a dropdown."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_dropdown_chevron(painter, self.width(), self.height())


class ChevronDateEdit(QDateEdit):
    """A date edit whose calendar button looks like the dropdown chevron."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(
            QRect(self.width() - 22, 2, 21, self.height() - 3),
            QColor(colors.BACKGROUND),
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_dropdown_chevron(painter, self.width(), self.height())


class ChevronTimeEdit(QTimeEdit):
    """A time edit with custom up and down chevrons instead of spin buttons."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(
            QRect(self.width() - 22, 2, 21, self.height() - 3),
            QColor(colors.BACKGROUND),
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x = self.width() - CHEVRON_RIGHT_OFFSET
        center_y = self.height() / 2
        _paint_chevron(painter, center_x, center_y - 5, pointing_down=False)
        _paint_chevron(painter, center_x, center_y + 5, pointing_down=True)
