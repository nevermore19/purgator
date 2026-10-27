from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from purgator.ui.colors import BACKGROUND, TEXT
from purgator.ui.styles import INFO_LABEL_STYLE, box_style


def page_layout(page: QWidget, title: str | None = None) -> QVBoxLayout:
    """The column of a page, with an optional heading on top."""
    layout = QVBoxLayout(page)
    if title is not None:
        heading = QLabel(title)
        heading.setStyleSheet(
            f"font-size: 22px; font-weight: 600; color: {TEXT}; padding: 4px 0 12px 4px;"
        )
        layout.addWidget(heading)
    return layout


def rounded_box(name: str) -> tuple[QFrame, QVBoxLayout]:
    """A rounded box that holds a list; the name keeps its style off the children."""
    box = QFrame()
    box.setObjectName(name)
    box.setStyleSheet(box_style(name))
    column = QVBoxLayout(box)
    column.setContentsMargins(14, 2, 14, 14)
    column.setSpacing(8)
    return box, column


def actions_row(info: QLabel, *buttons: QWidget) -> QHBoxLayout:
    """The line at the top of a page: what is going on, then the buttons."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 12)
    row.setSpacing(12)
    info.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    info.setStyleSheet(INFO_LABEL_STYLE)
    row.addWidget(info)
    row.addStretch()
    for button in buttons:
        row.addWidget(button)
    return row


def set_list_palette(widget: QWidget, alternate: str = BACKGROUND) -> None:
    """Rows on the background colour; a transparent highlight keeps a clicked row as it was."""
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor(BACKGROUND))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(alternate))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    widget.setPalette(palette)
