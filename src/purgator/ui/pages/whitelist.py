from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from purgator.ui.assets import ICONS_DIR, themed_icon
from purgator.ui.colors import ACCENT, BACKGROUND, BORDER, HOVER, REMOVE_HOVER, TEXT
from purgator.ui.components import ThinScrollBar, page_layout, rounded_box, set_list_palette
from purgator.ui.styles import PLAIN_BUTTON_STYLE, PRIMARY_BUTTON_STYLE

EDIT_BUTTON_STYLE = (
    f"QPushButton {{ background-color: {BACKGROUND}; color: {ACCENT};"
    f" border: 1px solid {ACCENT}; border-radius: 10px;"
    " padding: 2px 12px; font-size: 13px; }"
    f"QPushButton:hover {{ background-color: {HOVER}; }}"
)

REMOVE_BUTTON_STYLE = (
    f"QPushButton {{ background-color: transparent; color: {ACCENT};"
    " border: none; font-size: 16px; }"
    f"QPushButton:hover {{ color: {REMOVE_HOVER}; }}"
)

# Icon of the table header section that adds a new scan task
ADD_ICON_PATH = ICONS_DIR / "add.svg"
ADD_ICON_SIZE = 16
ADD_ICON_RIGHT_MARGIN = 12


class _AddTaskHeader(QHeaderView):
    """Header that paints the add icon at the right of the add column."""

    def __init__(self, icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self._icon = icon

    def paintSection(self, painter, rect, logical_index) -> None:
        super().paintSection(painter, rect, logical_index)
        if logical_index != 2:
            return
        pixmap = self._icon.pixmap(QSize(ADD_ICON_SIZE, ADD_ICON_SIZE))
        painter.save()
        painter.setClipRect(rect)
        painter.drawPixmap(
            rect.right() - pixmap.width() - ADD_ICON_RIGHT_MARGIN,
            rect.y() + (rect.height() - pixmap.height()) // 2,
            pixmap,
        )
        painter.restore()


def _display_path(path: Path) -> str:
    try:
        relative = path.relative_to(Path.home())
    except (ValueError, RuntimeError):
        return str(path)
    return "~" if str(relative) == "." else f"~/{relative}"


class _NewScanPathDialog(QDialog):
    """Asks for the name and the directory of a new scan task."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New task")
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {BACKGROUND}; color: {TEXT}; }}"
            f"QLabel {{ font-size: 15px; color: {TEXT}; background: transparent; }}"
            f"QLineEdit {{ background-color: {BACKGROUND}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 6px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Task name")
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Directory to scan")

        browse = QPushButton("Browse…")
        browse.setStyleSheet(EDIT_BUTTON_STYLE)
        browse.clicked.connect(self._browse)

        path_wrap = QWidget()
        path_row = QHBoxLayout(path_wrap)
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)
        path_row.addWidget(self.path_edit, stretch=1)
        path_row.addWidget(browse)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.addRow("Name", self.name_edit)
        form.addRow("Path", path_wrap)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(PLAIN_BUTTON_STYLE)
        cancel.clicked.connect(self.reject)
        add = QPushButton("Add")
        add.setStyleSheet(PRIMARY_BUTTON_STYLE)
        add.setDefault(True)
        add.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(add)
        layout.addLayout(buttons)

    def _browse(self) -> None:
        start = self.path_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Scan path", start)
        if chosen:
            self.path_edit.setText(chosen)

    def task_name(self) -> str:
        return self.name_edit.text().strip()

    def path(self) -> Path:
        return Path(self.path_edit.text().strip()).expanduser()

    def accept(self) -> None:
        if not self.task_name():
            QMessageBox.warning(self, "Cannot add the task", "The task needs a name.")
            return
        path_text = self.path_edit.text().strip()
        if not path_text or not Path(path_text).expanduser().is_dir():
            QMessageBox.warning(
                self, "Cannot add the task", "Choose an existing directory to scan."
            )
            return
        super().accept()


class WhitelistPage(QWidget):
    """The paths the cleanup tasks currently scan."""

    path_changed = Signal(str, str)  # task_id, new path
    task_added = Signal(str, str)  # task name, path
    task_removed = Signal(str)  # task_id

    def __init__(
        self,
        scan_roots: list[tuple[str, str, Path]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._roots = list(scan_roots)
        layout = page_layout(self)
        layout.addWidget(self._build_box(), stretch=1)

    def _build_box(self) -> QWidget:
        container, column = rounded_box("whitelistBox")

        self._table = QTableWidget(len(self._roots), 3)
        table = self._table
        table.setHorizontalHeader(_AddTaskHeader(themed_icon(ADD_ICON_PATH, ACCENT), table))
        table.setHorizontalHeaderLabels(["Task", "Scanned path", ""])
        task_header = table.horizontalHeaderItem(0)
        task_header.setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(2, 112)
        plus = table.horizontalHeaderItem(2)
        plus.setToolTip("Add a new task")
        header.sectionClicked.connect(self._on_header_clicked)
        table.setVerticalScrollBar(ThinScrollBar(Qt.Orientation.Vertical, table))
        table.setHorizontalScrollBar(ThinScrollBar(Qt.Orientation.Horizontal, table))
        set_list_palette(table)
        table.setStyleSheet(
            f"QTableWidget {{ background: {BACKGROUND}; border: none; outline: none; }}"
            f"QTableWidget::item {{ background: {BACKGROUND}; color: {TEXT};"
            " padding: 4px 8px; font-size: 15px; }"
            f"QTableWidget::item:selected {{ background: {BACKGROUND}; color: {TEXT}; }}"
            f"QHeaderView {{ background: {BACKGROUND}; border: none; }}"
            f"QHeaderView::section {{ background: {BACKGROUND}; color: {ACCENT};"
            f" border: none; border-bottom: 1px solid {BORDER}; padding: 6px 8px;"
            " font-size: 14px; font-weight: 600; }"
            "QTableCornerButton::section { background: transparent; border: none; }"
        )
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setShowGrid(False)

        for row, root in enumerate(self._roots):
            self._fill_row(row, *root)

        column.addWidget(table, stretch=1)
        return container

    def _fill_row(self, row: int, task_id: str, task_name: str, path: Path) -> None:
        table = self._table
        table.setItem(row, 0, QTableWidgetItem(task_name))
        path_item = QTableWidgetItem(_display_path(path))
        path_item.setToolTip(str(path))
        table.setItem(row, 1, path_item)

        edit = QPushButton("Edit")
        edit.setStyleSheet(EDIT_BUTTON_STYLE)
        edit.clicked.connect(lambda _=False, tid=task_id: self._edit_task(tid))

        remove = QPushButton("×")
        remove.setFixedSize(22, 22)
        remove.setStyleSheet(REMOVE_BUTTON_STYLE)
        remove.setToolTip("Remove this task")
        remove.clicked.connect(lambda _=False, tid=task_id: self._remove_task(tid))

        cell = QWidget()
        cell.setStyleSheet("background: transparent;")
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.setSpacing(8)
        cell_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cell_layout.addWidget(edit)
        cell_layout.addWidget(remove)
        table.setCellWidget(row, 2, cell)

    def add_root(self, task_id: str, task_name: str, path: Path) -> None:
        self._roots.append((task_id, task_name, path))
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._fill_row(row, task_id, task_name, path)

    def set_roots(self, scan_roots: list[tuple[str, str, Path]]) -> None:
        self._roots = list(scan_roots)
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._roots))
        for row, root in enumerate(self._roots):
            self._fill_row(row, *root)

    def _on_header_clicked(self, section: int) -> None:
        if section == 2:
            self._new_task()

    def _new_task(self) -> None:
        dialog = _NewScanPathDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.task_added.emit(dialog.task_name(), str(dialog.path()))

    def _row_for(self, task_id: str) -> int:
        for row, (tid, _, _) in enumerate(self._roots):
            if tid == task_id:
                return row
        return -1

    def _edit_task(self, task_id: str) -> None:
        row = self._row_for(task_id)
        if row < 0:
            return
        task_id, task_name, path = self._roots[row]
        chosen = QFileDialog.getExistingDirectory(
            self, f"Scan path for {task_name}", str(path)
        )
        if not chosen:
            return
        new_path = Path(chosen)
        self._roots[row] = (task_id, task_name, new_path)
        item = self._table.item(row, 1)
        item.setText(_display_path(new_path))
        item.setToolTip(str(new_path))
        self.path_changed.emit(task_id, str(new_path))

    def _remove_task(self, task_id: str) -> None:
        row = self._row_for(task_id)
        if row < 0:
            return
        self._roots.pop(row)
        self._table.removeRow(row)
        self.task_removed.emit(task_id)
