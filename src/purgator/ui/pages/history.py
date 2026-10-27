from PySide6.QtCore import QDateTime, Qt, QTime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from purgator.ui.colors import ACCENT, BACKGROUND, BORDER, STRIPE, TEXT
from purgator.ui.components import ThinScrollBar, page_layout, rounded_box, set_list_palette
from purgator.ui.styles import BOX_TITLE_STYLE

# The narrowest the columns of the history table may get
MIN_COLUMN_WIDTHS = {0: 220, 1: 220, 2: 200}


class HistoryPage(QWidget):
    """The table of the past runs and the log of everything that happened."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.history_log = self._build_log()
        self.history_list = self._build_table()

        layout = page_layout(self)
        top, top_layout = rounded_box("historyTopBox")
        top_layout.setContentsMargins(14, 6, 14, 14)
        top_layout.setSpacing(6)
        label_top = QLabel("History")
        label_top.setStyleSheet(BOX_TITLE_STYLE)
        top_layout.addWidget(label_top)
        top_layout.addWidget(self.history_list)

        bottom, bottom_layout = rounded_box("historyLogBox")
        bottom_layout.setContentsMargins(14, 6, 14, 14)
        bottom_layout.setSpacing(6)
        label_bot = QLabel("Logs")
        label_bot.setStyleSheet(BOX_TITLE_STYLE)
        bottom_layout.addWidget(label_bot)
        bottom_layout.addWidget(self.history_log)

        layout.addWidget(top)
        layout.addWidget(bottom, stretch=1)

    def _build_log(self) -> QListWidget:
        log = QListWidget()
        log.setVerticalScrollBar(ThinScrollBar(Qt.Orientation.Vertical, log))
        log.setHorizontalScrollBar(ThinScrollBar(Qt.Orientation.Horizontal, log))
        log.setStyleSheet(
            f"QListWidget {{ background-color: {BACKGROUND}; border: none; outline: none; font-size: 13px; }}"
            "QListWidget::item { padding: 4px 6px; }"
            f"QListWidget::item:selected {{ background: transparent; color: {TEXT}; }}"
        )
        return log

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Task", "Action", "When", "Status"])
        h = table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setStretchLastSection(True)
        for column, width in MIN_COLUMN_WIDTHS.items():
            table.setColumnWidth(column, width)
        table.setVerticalScrollBar(ThinScrollBar(Qt.Orientation.Vertical, table))
        table.setHorizontalScrollBar(ThinScrollBar(Qt.Orientation.Horizontal, table))
        set_list_palette(table, alternate=STRIPE)
        table.setAlternatingRowColors(False)
        table.setStyleSheet(
            f"QTableWidget {{ background: {BACKGROUND}; border: none; outline: none; gridline-color: transparent; }}"
            f"QTableWidget::item {{ color: {TEXT}; padding: 4px 16px; }}"
            f"QTableWidget::item:selected {{ background: transparent; color: {TEXT}; }}"
            f"QHeaderView {{ background: {BACKGROUND}; border: none; }}"
            f"QHeaderView::section {{ background: {BACKGROUND}; color: {ACCENT};"
            f" border: none; border-bottom: 1px solid {BORDER}; padding: 6px 16px;"
            " font-size: 14px; font-weight: 600; }"
            "QTableCornerButton::section { background: transparent; border: none; }"
        )
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        return table

    def add_entry(self, task: str, action: str, status: str) -> None:
        try:
            stamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
            self.history_list.insertRow(0)
            for c, val in enumerate([str(task), str(action), str(stamp), str(status)]):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == 1:
                    it.setToolTip(val)
                self.history_list.setItem(0, c, it)
            # stripe all rows
            for r in range(self.history_list.rowCount()):
                bg = QColor(STRIPE) if r % 2 == 1 else QColor(BACKGROUND)
                for c in range(self.history_list.columnCount()):
                    it = self.history_list.item(r, c)
                    if it:
                        it.setBackground(bg)
            self.history_list.resizeColumnsToContents()
            for column, width in MIN_COLUMN_WIDTHS.items():
                if self.history_list.columnWidth(column) < width:
                    self.history_list.setColumnWidth(column, width)
        except Exception:
            pass

    def log(self, message: str) -> None:
        stamp = QTime.currentTime().toString("HH:mm:ss")
        line = f"[{stamp}] {message}"
        print(line)
        try:
            item = QListWidgetItem(line)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.history_log.addItem(item)
            self.history_log.scrollToBottom()
        except Exception:
            pass
        try:
            self._entry_from_log(message)
        except Exception:
            pass

    def _entry_from_log(self, m: str) -> None:
        """Some log lines also leave an entry in the history table."""
        if "applications: FAILED" in m:
            self.add_entry("Applications:scan", "-", "Failed")
        elif m.strip().startswith("applications:") and "found" in m:
            self.add_entry("Applications:scan", m.split("applications:")[-1].strip(), "Successfull")
        elif "remove" in m.lower() and "applications" in m.lower() and ("done" in m.lower() or "→ done" in m):
            self.add_entry("Applications:remove", m.split("remove")[-1].strip() if "remove" in m else "-", "Successfull")
        elif "schedule" in m.lower() and "fired" in m.lower():
            self.add_entry("Schedule:run", "-", "Successfull")
