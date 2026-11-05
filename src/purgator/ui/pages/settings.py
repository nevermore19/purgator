from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QWidget,
)

from purgator.ui import theme
from purgator.ui.colors import ACCENT, BACKGROUND, BORDER, HOVER, TEXT, TEXT_ON_ACCENT
from purgator.ui.components import DropdownComboBox, page_layout, rounded_box
from purgator.ui.styles import BOX_TITLE_STYLE, PLAIN_BUTTON_STYLE

COMBO_STYLE = (
    f"QComboBox {{ background-color: {BACKGROUND}; color: {TEXT};"
    f" border: 1px solid {BORDER}; border-radius: 4px; padding: 3px 8px;"
    " font-size: 15px; min-width: 160px; }"
    "QComboBox::drop-down { border: none; background: transparent; width: 24px; }"
    "QComboBox::down-arrow { image: none; }"
    f"QComboBox QAbstractItemView {{ background-color: {BACKGROUND}; color: {TEXT};"
    f" selection-background-color: {HOVER}; selection-color: {TEXT};"
    " outline: none; }"
    f"QComboBox QAbstractItemView::item:hover {{ background-color: {HOVER};"
    f" color: {TEXT}; }}"
)


class SettingsPage(QWidget):
    """The application settings."""

    theme_changed = Signal(str)
    task_paths_reset = Signal()

    def __init__(
        self,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings or QSettings()

        # "Settings" appears only in the top header, not as a page heading.
        layout = page_layout(self)
        layout.addWidget(self._build_appearance())
        layout.addWidget(self._build_task_paths())
        layout.addStretch()

    def _build_appearance(self) -> QWidget:
        container, column = rounded_box("settingsBox")
        column.setContentsMargins(14, 12, 14, 14)

        title = QLabel("Appearance")
        title.setStyleSheet(BOX_TITLE_STYLE)
        column.addWidget(title)

        label = QLabel("Theme")
        label.setStyleSheet(f"font-size: 15px; color: {TEXT};")

        self.theme_combo = DropdownComboBox()
        for value, text in theme.THEMES:
            self.theme_combo.addItem(text, value)
        self.theme_combo.setStyleSheet(COMBO_STYLE)
        self.theme_combo.setItemDelegate(QStyledItemDelegate(self.theme_combo))
        self._set_input_palette(self.theme_combo)
        if view := self.theme_combo.view():
            view_palette = view.palette()
            view_palette.setColor(QPalette.ColorRole.Base, QColor(BACKGROUND))
            view_palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
            view_palette.setColor(QPalette.ColorRole.Highlight, QColor(HOVER))
            view_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
            view.setPalette(view_palette)

        current = theme.stored_theme(self.settings)
        index = self.theme_combo.findData(current)
        self.theme_combo.setCurrentIndex(max(index, 0))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_selected)

        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)
        form.setSpacing(10)
        form.addRow(label, self.theme_combo)
        column.addLayout(form)

        return container

    def _build_task_paths(self) -> QWidget:
        container, column = rounded_box("taskPathsBox")
        column.setContentsMargins(14, 12, 14, 14)

        title = QLabel("Task paths")
        title.setStyleSheet(BOX_TITLE_STYLE)
        column.addWidget(title)

        description = QLabel(
            "Restore the built-in tasks and their default scan paths."
        )
        description.setStyleSheet(f"font-size: 15px; color: {TEXT};")
        description.setWordWrap(True)
        column.addWidget(description)

        reset = QPushButton("Restore defaults")
        reset.setStyleSheet(
            PLAIN_BUTTON_STYLE
            + "QPushButton { padding: 2px 14px; border-radius: 10px; font-size: 14px; }"
        )
        reset.clicked.connect(self.task_paths_reset.emit)
        column.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)

        return container

    @staticmethod
    def _set_input_palette(widget: QWidget) -> None:
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(BACKGROUND))
        palette.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND))
        palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT_ON_ACCENT))
        widget.setPalette(palette)

    def _on_theme_selected(self, index: int) -> None:
        name = self.theme_combo.itemData(index)
        if not name:
            return
        previous = theme.stored_theme(self.settings)
        if name == previous:
            return
        changed = theme.resolve(name) != theme.resolve(previous)
        theme.save_theme(name, self.settings)
        if changed:
            self.theme_changed.emit(name)
