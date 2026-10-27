from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QTreeWidget

from purgator.ui.colors import ACCENT, BACKGROUND


class RowDelegate(QStyledItemDelegate):
    """Paints every row with its own background colour and draws the check box.

    The selection highlight would replace the row colour with the base colour,
    so the "selected" state is dropped before the default painting runs.
    """

    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)

    @staticmethod
    def _row_colour(index) -> QColor:
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(background, QBrush):
            return background.color()
        if isinstance(background, QColor):
            return background
        return QColor(BACKGROUND)

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        row_colour = self._row_colour(index)
        painter.fillRect(option.rect, row_colour)
        raw = index.data(Qt.ItemDataRole.CheckStateRole)
        if raw is None:
            option.state &= ~QStyle.StateFlag.State_Selected
            super().paint(painter, option, index)
            painter.restore()
            return
        state = Qt.CheckState(raw)
        side = min(option.rect.height() - 10, 16)
        box = QRectF(
            option.rect.left() + (option.rect.width() - side) / 2,
            option.rect.top() + (option.rect.height() - side) / 2,
            side,
            side,
        )
        painter.setPen(QPen(QColor(ACCENT), 1.4))
        painter.setBrush(row_colour)
        painter.drawRoundedRect(box, 3, 3)
        if state in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked):
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(box, 3, 3)
            pen = QPen(QColor(BACKGROUND), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            if state == Qt.CheckState.Checked:
                mark = QPainterPath()
                mark.moveTo(box.left() + box.width() * 0.24, box.top() + box.height() * 0.52)
                mark.lineTo(box.left() + box.width() * 0.43, box.top() + box.height() * 0.72)
                mark.lineTo(box.left() + box.width() * 0.77, box.top() + box.height() * 0.28)
                painter.drawPath(mark)
            else:
                painter.drawLine(
                    QPointF(box.left() + box.width() * 0.28, box.center().y()),
                    QPointF(box.right() - box.width() * 0.28, box.center().y()),
                )
        painter.restore()
