from PySide6.QtWidgets import QLabel, QWidget

from purgator.ui.colors import TEXT
from purgator.ui.components import page_layout


class PlaceholderPage(QWidget):
    """A section that has nothing in it yet."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = page_layout(self, title)
        hint = QLabel("Nothing here yet.")
        hint.setStyleSheet(f"color: {TEXT}; padding-left: 4px;")
        layout.addWidget(hint)
        layout.addStretch()
