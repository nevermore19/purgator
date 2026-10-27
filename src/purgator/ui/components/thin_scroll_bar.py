from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollBar, QWidget

from purgator.ui.colors import SCROLLBAR, SCROLLBAR_HOVER

# Width of the custom scroll bar used by the lists
SCROLLBAR_WIDTH = 8


class ThinScrollBar(QScrollBar):
    """A slim scroll bar with a plain handle in the accent colour."""

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        if orientation == Qt.Orientation.Vertical:
            self.setFixedWidth(SCROLLBAR_WIDTH)
            self.setStyleSheet(
                f"QScrollBar:vertical {{ background: transparent; width: {SCROLLBAR_WIDTH}px; }}"
                f"QScrollBar::handle:vertical {{ background: {SCROLLBAR};"
                " border-radius: 3px; min-height: 30px; }"
                f"QScrollBar::handle:vertical:hover {{ background: {SCROLLBAR_HOVER}; }}"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,"
                " QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent;"
                " border: none; height: 0; width: 0; }"
            )
        else:
            self.setFixedHeight(SCROLLBAR_WIDTH)
            self.setStyleSheet(
                f"QScrollBar:horizontal {{ background: transparent; height: {SCROLLBAR_WIDTH}px; }}"
                f"QScrollBar::handle:horizontal {{ background: {SCROLLBAR};"
                " border-radius: 3px; min-width: 30px; }"
                f"QScrollBar::handle:horizontal:hover {{ background: {SCROLLBAR_HOVER}; }}"
                "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,"
                " QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent;"
                " border: none; height: 0; width: 0; }"
            )
