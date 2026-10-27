from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, QEvent, QPointF, QRectF, QSettings, QSize, Qt, QTime, Signal
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollBar,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from purgator.apps import (
    Application,
    discover_applications,
    remove_application,
)
from purgator.scheduler import CronScheduler, Job
from purgator.tasks import TASKS, Cancelled, PurgeTask, TaskResult, create_task, human_size
from purgator.tasks.builtin import ProjectBuildsTask
from purgator.usage import describe as describe_usage
from purgator.usage import describe_exact, is_old
from purgator.workers import TaskRunner, Worker

BUILDS_ROOT_KEY = "tasks/project_builds/root"

# Label of the per-category panel shown on the Cleanup page
CATEGORY_LABELS = {
    "user_cache": "User logs",
    "stale_files": "Stale temp files",
    "project_builds": "Project builds",
}

# Backgrounds of the scan result rows: the entries alternate between the two
STRIPE_COLOR = "#BDB6AA"
ROW_COLOR = "#F7EEE2"

# Heights of the rows: the category header is a bit taller than the file rows
CATEGORY_HEIGHT = 36
FILE_HEIGHT = 28

# Gap between the D/F marker and the path in front of it
KIND_GAP = "   "

# Width of the column with the check boxes
CHECK_COLUMN_WIDTH = 34

# The room between the size of an application and the day it was used
COLUMN_GAP_WIDTH = 14

# The columns of the list of applications
NAME_COLUMN = 0
SOURCE_COLUMN = 1
SIZE_COLUMN = 2
GAP_COLUMN = 3
LAST_USED_COLUMN = 4
CHECK_COLUMN = 5

# Arrow in front of a category name: the dropdown is open or closed
ARROW_DOWN = "▾"
ARROW_RIGHT = "▸"

# Width of the custom scroll bar used by the scan result list
SCROLLBAR_WIDTH = 8

# Colour of the scroll bar handle
SCROLLBAR_COLOR = "#837270"

# The look of the result lists
TREE_STYLE = (
    "QTreeWidget { background: #F7EEE2; border: none; outline: none;"
    " font-size: 13px; }"
    "QTreeWidget::item { padding: 3px 2px; }"
    "QTreeWidget::item:selected { background: transparent; color: black; }"
    "QHeaderView::section { background: transparent; color: #4E4242;"
    " border: none; border-bottom: 1px solid #BDB6AA; padding: 2px 6px 4px 6px;"
    " font-size: 13px; font-weight: 600; }"
)

# The two kinds of buttons: the plain one and the one that does the work
PLAIN_BUTTON_STYLE = (
    "QPushButton { background-color: #F7EEE2; color: #4E4242;"
    " border: 1px solid #4E4242; border-radius: 15px;"
    " padding: 4px 22px; font-size: 18px; }"
    "QPushButton:hover { background-color: #EDE2D1; }"
    "QPushButton:disabled { color: #A79E92; border-color: #A79E92; }"
)

PRIMARY_BUTTON_STYLE = (
    "QPushButton { background-color: #4E4242; color: #F7EEE2;"
    " border: 1px solid #4E4242; border-radius: 15px;"
    " padding: 4px 22px; font-size: 18px; }"
    "QPushButton:hover { background-color: #5C4E4E; }"
    "QPushButton:disabled { background-color: #9C9393; border-color: #9C9393; }"
)

NAV_ITEMS = [
    ("overview", "Overview"),
    ("cleanup", "Cleanup"),
    ("applications", "Applications"),
    ("schedule", "Schedule"),
    ("history", "History"),
    ("whitelist", "Whitelist"),
    ("settings", "Settings"),
]


def _display_path(path: Path) -> str:
    """Shorten paths inside the home directory: /home/me/x becomes ~/x."""
    try:
        home = Path.home()
    except RuntimeError:  # no home directory on this system
        return str(path)
    try:
        relative = path.relative_to(home)
    except ValueError:  # outside the home directory
        return str(path)
    if str(relative) == ".":
        return "~"
    return f"~/{relative}"


def _usage_tip(app: Application) -> str:
    """Say where the moment of the last use comes from."""
    if app.last_used <= 0:
        return "never used, as far as the system knows"
    source = app.used_from or "the last time it was used"
    return f"{source}, on {describe_exact(app.last_used)}"


def _page_widget(title: str, *, with_heading: bool = True) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    if with_heading:
        heading = QLabel(title)
        heading.setStyleSheet(
            "font-size: 22px; font-weight: 600; color: black; padding: 4px 0 12px 4px;"
        )
        layout.addWidget(heading)
    return page, layout


class _RingChart(QWidget):
    def __init__(self, used_frac: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._used = max(0.0, min(1.0, used_frac))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F7EEE2"))

        side = self.width()
        band = side * 0.085
        outer_radius = side * 0.43
        radius = outer_radius - band / 2
        cx = self.width() / 2
        cy = self.height() / 2
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

        track_pen = QPen(QColor("#82716F"))
        track_pen.setWidthF(band)
        painter.setPen(track_pen)
        painter.drawEllipse(rect)

        if self._used >= 1.0:
            used_pen = QPen(QColor("#4E4242"))
            used_pen.setWidthF(band)
            painter.setPen(used_pen)
            painter.drawEllipse(rect)
        elif self._used > 0.0:
            used_pen = QPen(QColor("#4E4242"))
            used_pen.setWidthF(band)
            used_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(used_pen)
            span = int(round(self._used * 360 * 16))
            painter.drawArc(rect, 90 * 16, span)
        painter.end()


class _RatioBar(QWidget):
    def __init__(self, frac: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frac = max(0.0, min(1.0, frac))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F7EEE2"))

        height = self.height()
        radius = height / 2
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QColor("#82716F"))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), height), radius, radius)

        if self._frac > 0.0:
            painter.setBrush(QColor("#4E4242"))
            painter.drawRoundedRect(QRectF(0, 0, self.width() * self._frac, height), radius, radius)
        painter.end()


class _RowDelegate(QStyledItemDelegate):
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
        return QColor(ROW_COLOR)

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
        painter.setPen(QPen(QColor("#4E4242"), 1.4))
        painter.setBrush(row_colour)
        painter.drawRoundedRect(box, 3, 3)
        if state in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked):
            painter.setBrush(QColor("#4E4242"))
            painter.drawRoundedRect(box, 3, 3)
            pen = QPen(QColor(ROW_COLOR), 2.0)
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


class _Switch(QWidget):
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
        painter.setBrush(QColor("#4E4242") if self._checked else QColor("#BDB6AA"))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        diameter = self.height() - 4
        left = self.width() - diameter - 2 if self._checked else 2
        painter.setBrush(QColor("#F7EEE2"))
        painter.drawEllipse(QRectF(left, 2, diameter, diameter))
        painter.end()


class _ThinScrollBar(QScrollBar):
    """A slim scroll bar with a plain handle in the accent colour."""

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        if orientation == Qt.Orientation.Vertical:
            self.setFixedWidth(SCROLLBAR_WIDTH)
            self.setStyleSheet(
                f"QScrollBar:vertical {{ background: transparent; width: {SCROLLBAR_WIDTH}px; }}"
                f"QScrollBar::handle:vertical {{ background: {SCROLLBAR_COLOR};"
                " border-radius: 3px; min-height: 30px; }"
                "QScrollBar::handle:vertical:hover { background: #6E605E; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,"
                " QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent;"
                " border: none; height: 0; width: 0; }"
            )
        else:
            self.setFixedHeight(SCROLLBAR_WIDTH)
            self.setStyleSheet(
                f"QScrollBar:horizontal {{ background: transparent; height: {SCROLLBAR_WIDTH}px; }}"
                f"QScrollBar::handle:horizontal {{ background: {SCROLLBAR_COLOR};"
                " border-radius: 3px; min-width: 30px; }"
                "QScrollBar::handle:horizontal:hover { background: #6E605E; }"
                "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,"
                " QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent;"
                " border: none; height: 0; width: 0; }"
            )


class _ResultTree(QTreeWidget):
    """All scan results in one list: every category is a collapsible dropdown.

    The list is flat: the files of a category sit right under it and the arrow
    in front of the name shows whether it is open. Closing a category hides
    only its own rows, so the categories below move up instead of leaving an
    empty gap in the middle of the list. The check box on the right says what
    will be deleted.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Category", "Found", ""])
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.header().resizeSection(2, CHECK_COLUMN_WIDTH)
        self.headerItem().setTextAlignment(
            1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.setItemDelegate(_RowDelegate(self))
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setExpandsOnDoubleClick(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        # The scroll bar always keeps its space, so opening a category never
        # shifts the rows sideways.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBar(_ThinScrollBar(Qt.Orientation.Vertical, self))
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(ROW_COLOR))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(ROW_COLOR))
        # A transparent highlight keeps the row looking the same when it is clicked.
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
        self.setPalette(palette)
        self.setStyleSheet(TREE_STYLE)
        self.itemExpanded.connect(self._on_expanded)
        self.itemCollapsed.connect(self._on_collapsed)
        self.viewport().installEventFilter(self)
        self._categories: dict[str, QTreeWidgetItem] = {}
        self._entries: dict[str, list[Path]] = {}  # every path the task found
        self._checked: dict[str, set[Path]] = {}  # the ones the user keeps

    def add_category(self, task_id: str, title: str) -> None:
        """Add a collapsible row for a task; its files are listed under it."""
        item = QTreeWidgetItem(self, [f"{ARROW_DOWN} {title}", "Not scanned yet", ""])
        font = item.font(0)
        font.setBold(True)
        font.setPixelSize(16)
        item.setFont(0, font)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setSizeHint(0, QSize(0, CATEGORY_HEIGHT))  # a bit taller than the file rows
        item.setExpanded(True)  # the dropdown starts open, like the old sections
        item.setData(0, Qt.ItemDataRole.UserRole, title)
        item.setData(2, Qt.ItemDataRole.UserRole, task_id)
        item.setCheckState(2, Qt.CheckState.Unchecked)
        self._categories[task_id] = item
        self._paint(item, ROW_COLOR)

    def _paint(self, item: QTreeWidgetItem, colour: str) -> None:
        brush = QColor(colour)
        item.setBackground(0, brush)
        item.setBackground(1, brush)
        item.setBackground(2, brush)

    def _paint_files(self, category: QTreeWidgetItem) -> None:
        """The files of a category alternate; the header stays plain."""
        for index in range(category.childCount()):
            colour = STRIPE_COLOR if index % 2 else ROW_COLOR
            self._paint(category.child(index), colour)

    def eventFilter(self, obj, event) -> bool:
        """Clicking a category header opens or closes it, the check box selects."""
        if obj is self.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            position = event.position().toPoint()
            index = self.indexAt(position)
            item = self.itemFromIndex(index) if index.isValid() else None
            if item is not None:
                if index.column() == 2:
                    self._toggle(item)
                    return True
                if item.parent() is None:
                    item.setExpanded(not item.isExpanded())
                    return True
        return super().eventFilter(obj, event)

    def _toggle(self, item: QTreeWidgetItem) -> None:
        """Check or uncheck a row: a category toggles all of its files."""
        parent = item.parent()
        if parent is None:
            self._toggle_category(item.data(2, Qt.ItemDataRole.UserRole))
        else:
            self._toggle_path(parent.data(2, Qt.ItemDataRole.UserRole), item)

    def _toggle_category(self, task_id: str) -> None:
        paths = self._entries.get(task_id, [])
        checked = self._checked.setdefault(task_id, set())
        if paths and len(checked) == len(paths):
            checked.clear()  # everything was checked: uncheck it all
        else:
            checked.update(paths)
        self._sync(task_id)

    def _toggle_path(self, task_id: str, item: QTreeWidgetItem) -> None:
        path = item.data(2, Qt.ItemDataRole.UserRole)
        checked = self._checked.setdefault(task_id, set())
        if path in checked:
            checked.discard(path)
        else:
            checked.add(path)
        self._sync(task_id)

    def _sync(self, task_id: str) -> None:
        """Copy the selection back into the check boxes of the rows."""
        category = self._categories.get(task_id)
        if category is None:
            return
        paths = self._entries.get(task_id, [])
        checked = self._checked.get(task_id, set())
        if not paths:
            state = Qt.CheckState.Unchecked
        elif len(checked) == len(paths):
            state = Qt.CheckState.Checked
        elif checked:
            state = Qt.CheckState.PartiallyChecked
        else:
            state = Qt.CheckState.Unchecked
        category.setCheckState(2, state)
        for index in range(category.childCount()):
            child = category.child(index)
            path = child.data(2, Qt.ItemDataRole.UserRole)
            if path is None:
                continue
            child.setCheckState(
                2,
                Qt.CheckState.Checked if path in checked else Qt.CheckState.Unchecked,
            )

    def checked_paths(self, task_id: str) -> set[Path]:
        """The paths of a task the user wants to delete."""
        return set(self._checked.get(task_id, set()))

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        self._set_arrow(item, ARROW_DOWN)

    def _on_collapsed(self, item: QTreeWidgetItem) -> None:
        self._set_arrow(item, ARROW_RIGHT)

    def _set_arrow(self, item: QTreeWidgetItem, arrow: str) -> None:
        title = item.data(0, Qt.ItemDataRole.UserRole)
        if title:
            item.setText(0, f"{arrow} {title}")

    def reset(self, status: str) -> None:
        for task_id, item in self._categories.items():
            item.setText(1, status)
            self._clear_children(item)
            self._entries.pop(task_id, None)
            self._checked.pop(task_id, None)
            item.setCheckState(2, Qt.CheckState.Unchecked)

    def show_result(self, result: TaskResult) -> None:
        item = self._categories.get(result.task_id)
        if item is None:
            return
        files = f"{result.files} file" if result.files == 1 else f"{result.files} files"
        item.setText(1, f"{human_size(result.bytes)} · {files}")
        self._clear_children(item)
        self._entries[result.task_id] = list(result.paths)
        self._checked[result.task_id] = set(result.paths)
        for path in result.paths:
            kind = "D" if path in result.directories else "F"
            size = human_size(result.sizes.get(path, 0))
            child = QTreeWidgetItem(item, [f"{kind}{KIND_GAP}{_display_path(path)}", size, ""])
            child.setData(2, Qt.ItemDataRole.UserRole, path)
            child.setCheckState(2, Qt.CheckState.Checked)
            child.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            child.setSizeHint(0, QSize(0, FILE_HEIGHT))
        self._paint_files(item)
        self._sync(result.task_id)

    @staticmethod
    def _clear_children(item: QTreeWidgetItem) -> None:
        # takeChildren() hands the rows over to Python, so dropping them deletes them.
        item.takeChildren()


class _ApplicationList(QTreeWidget):
    """The installed applications, one flat row per application.

    There are no categories here: every application stands on its own and the
    check box on the right says which of them will be removed. The column of the
    last use says when the application was open for the last time; the ones
    that were not used for a long time come first.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(6)
        self.setHeaderLabels(["Application", "Source", "Size", "", "Last used", ""])
        self.header().setStretchLastSection(False)
        # the small gap between the columns may be narrower than the padding
        # of the head
        self.header().setMinimumSectionSize(4)
        self.header().setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(SOURCE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(SIZE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        # the empty column in the middle keeps the size and the day apart
        self.header().setSectionResizeMode(GAP_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.header().resizeSection(GAP_COLUMN, COLUMN_GAP_WIDTH)
        self.header().setSectionResizeMode(LAST_USED_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(CHECK_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.header().resizeSection(CHECK_COLUMN, CHECK_COLUMN_WIDTH)
        self.headerItem().setTextAlignment(
            2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.setItemDelegate(_RowDelegate(self))
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBar(_ThinScrollBar(Qt.Orientation.Vertical, self))
        # the rows are sorted by hand: the order depends on the moment of the
        # last use, not on the words of the column
        self._sort_column = LAST_USED_COLUMN
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.header().sectionClicked.connect(self._sort_by_column)
        self.header().setSortIndicator(LAST_USED_COLUMN, Qt.SortOrder.AscendingOrder)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(ROW_COLOR))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(ROW_COLOR))
        # A transparent highlight keeps the row looking the same when it is clicked.
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
        self.setPalette(palette)
        self.setStyleSheet(TREE_STYLE)
        self.viewport().installEventFilter(self)

    def _sort_by_column(self, column: int) -> None:
        """Put the rows in order when the head of a column is clicked."""
        if column in (CHECK_COLUMN, GAP_COLUMN):
            return
        if column == self._sort_column:
            # the second click turns the order around
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = Qt.SortOrder.AscendingOrder
        self.header().setSortIndicator(self._sort_column, self._sort_order)
        self._apply_sort()

    def _apply_sort(self) -> None:
        """Put the rows in the order the user asked for."""
        rows = []
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            app = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(app, Application):
                rows.append((self._sort_key(app), app.name.lower(), item))
        if not rows:
            return
        rows.sort(key=lambda row: row[:2], reverse=self._sort_order == Qt.SortOrder.DescendingOrder)
        self.setUpdatesEnabled(False)
        try:
            for _, _, item in rows:
                self.takeTopLevelItem(self.indexOfTopLevelItem(item))
            for _, _, item in rows:
                self.addTopLevelItem(item)
            self._paint_rows()
        finally:
            self.setUpdatesEnabled(True)

    def _sort_key(self, app: Application) -> tuple:
        """What the rows are put in order by."""
        column = self._sort_column
        if column == SIZE_COLUMN:
            return (app.size,)
        if column == SOURCE_COLUMN:
            return (app.source,)
        if column == LAST_USED_COLUMN:
            # the applications that were never used come first
            return (app.last_used or 0.0,)
        return (app.name.lower(),)

    def eventFilter(self, obj, event) -> bool:
        """Clicking the check box on the right selects the application."""
        if obj is self.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            position = event.position().toPoint()
            index = self.indexAt(position)
            if index.isValid() and index.column() == CHECK_COLUMN:
                item = self.itemFromIndex(index)
                if item is not None:
                    self._toggle(item)
                    return True
        return super().eventFilter(obj, event)

    def _toggle(self, item: QTreeWidgetItem) -> None:
        state = item.checkState(CHECK_COLUMN)
        item.setCheckState(
            CHECK_COLUMN,
            Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked,
        )

    def set_applications(self, apps: list[Application]) -> None:
        """Show the applications that were found."""
        # There can be thousands of them: the drawing waits until the last one
        # is in place, otherwise every row would paint the whole list again.
        self.setUpdatesEnabled(False)
        self.blockSignals(True)
        try:
            self.clear()
            for app in apps:
                size = human_size(app.size) if app.size else "—"
                item = QTreeWidgetItem(
                    self,
                    [app.name, app.source, size, "", describe_usage(app.last_used), ""],
                )
                item.setData(0, Qt.ItemDataRole.UserRole, app)
                item.setCheckState(CHECK_COLUMN, Qt.CheckState.Unchecked)
                item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setSizeHint(0, QSize(0, FILE_HEIGHT))
                if app.summary:
                    item.setToolTip(0, app.summary)
                item.setToolTip(LAST_USED_COLUMN, _usage_tip(app))
            self._paint_rows()
        finally:
            self.blockSignals(False)
            self.setUpdatesEnabled(True)

    def _paint_rows(self) -> None:
        """Give the rows their stripes; they follow the place of the row."""
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            colour = QColor(STRIPE_COLOR if index % 2 else ROW_COLOR)
            for column in range(self.columnCount()):
                item.setBackground(column, colour)

    @property
    def count(self) -> int:
        return self.topLevelItemCount()

    @property
    def never_used_count(self) -> int:
        """How many of the applications were never used."""
        total = 0
        for index in range(self.topLevelItemCount()):
            app = self.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole)
            if isinstance(app, Application) and app.last_used <= 0:
                total += 1
        return total

    @property
    def old_count(self) -> int:
        """How many were used, but not for a long time."""
        total = 0
        for index in range(self.topLevelItemCount()):
            app = self.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole)
            if isinstance(app, Application) and app.last_used > 0 and is_old(app.last_used):
                total += 1
        return total

    def checked_applications(self) -> list[Application]:
        """The applications the user wants to remove."""
        apps = []
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item.checkState(CHECK_COLUMN) != Qt.CheckState.Checked:
                continue
            app = item.data(0, Qt.ItemDataRole.UserRole)
            if app is not None:
                apps.append(app)
        return apps

    def remove_applications(self, apps: list[Application]) -> None:
        """Drop the rows of the applications that are gone."""
        gone = set(apps)
        for index in range(self.topLevelItemCount() - 1, -1, -1):
            item = self.topLevelItem(index)
            app = item.data(0, Qt.ItemDataRole.UserRole)
            if app in gone:
                self.takeTopLevelItem(index)


class _ApplicationsScan:
    """Looks for the installed applications; the worker only needs the two
    methods of a task: the id and the run.
    """

    id = "applications"

    def __init__(self) -> None:
        self.dry_run = True

    def run(self, report, is_cancelled):
        report(-1, "Looking for applications…")
        apps = discover_applications(is_cancelled)
        if is_cancelled():
            raise Cancelled
        report(100, f"{len(apps)} applications found")
        return apps


class _ApplicationsRemoval:
    """Uninstalls the applications the user ticked.

    The ones of the system ask for the root password: a window of their own
    shows up and waits for the user to type it.
    """

    id = "applications_removal"

    def __init__(self, apps: list[Application]) -> None:
        self.apps = apps
        self.dry_run = False

    def run(self, report, is_cancelled):
        results = []
        for index, app in enumerate(self.apps, 1):
            if is_cancelled():
                raise Cancelled
            report(-1, f"Removing {app.name}…")
            ok, message = remove_application(app)
            results.append((app, ok, message))
            report(index * 100 // len(self.apps), f"Removed {app.name}")
        return results


class _NewTaskDialog(QDialog):
    """Asks how a new scheduled run looks: which task, and when."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New task")
        self.setModal(True)
        self.setStyleSheet(
            "QDialog { background-color: #F7EEE2; color: #000000; }"
            "QLabel { font-size: 17px; color: #000000; background: transparent; }"
            "QComboBox { background-color: #F7EEE2; color: #000000; border: 1px solid #BDB6AA; border-radius: 4px; padding: 2px 6px; }"
            "QComboBox::drop-down { border: none; background: transparent; width: 24px; }"
            "QComboBox QAbstractItemView { background-color: #F7EEE2; selection-background-color: #4E4242; selection-color: #FFFFFF; color: #000000; }"
            "QComboBox QAbstractItemView::item { color: #000000; }"
            "QComboBox QAbstractItemView::item:hover { background-color: #BDB6AA; color: #000000; }"
            "QDateEdit, QTimeEdit, QSpinBox { background-color: #F7EEE2; color: #000000; border: 1px solid #BDB6AA; border-radius: 4px; padding: 2px 6px; }"
            "QDateEdit QLineEdit, QTimeEdit QLineEdit, QSpinBox QLineEdit { background-color: #F7EEE2; color: #000000; border: none; padding: 0px; selection-background-color: #4E4242; selection-color: #FFFFFF; }"
            "QComboBox QLineEdit { background-color: #F7EEE2; color: #000000; border: none; }"
            "QDateEdit::calendar-button, QTimeEdit::calendar-button"
            " { border: none; background: transparent; border-top-right-radius: 3px; border-bottom-right-radius: 3px; }"
            "QDateEdit::calendar-button:hover, QTimeEdit::calendar-button:hover { background-color: #EDE2D1; }"
            "QSpinBox::up-button, QSpinBox::down-button { border: none; background: transparent; }"
            "QSpinBox::up-button:hover, QSpinBox::down-button:hover { background-color: #EDE2D1; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.task_combo = QComboBox()
        for task_id, cls in TASKS.items():
            self.task_combo.addItem(cls.name, task_id)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        if self.date_edit.lineEdit():
            le = self.date_edit.lineEdit()
            le.setReadOnly(False)
            le.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            le.setStyleSheet("QLineEdit { background-color: #F7EEE2; color: #000000; border: none; }")
            le.setPalette(le.palette())

        self.every_spin = QSpinBox()
        self.every_spin.setRange(1, 999)
        self.every_spin.setValue(1)
        if self.every_spin.lineEdit():
            le = self.every_spin.lineEdit()
            le.setReadOnly(False)
            le.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            le.setStyleSheet("QLineEdit { background-color: #F7EEE2; color: #000000; border: none; }")
            le.setPalette(le.palette())

        self.unit_combo = QComboBox()
        self.unit_combo.addItem("day(s)", "day")
        self.unit_combo.addItem("month(s)", "month")

        self.hour_edit = QTimeEdit()
        self.hour_edit.setDisplayFormat("HH:mm")
        self.hour_edit.setTime(QTime(3, 0))
        self.hour_edit.setCalendarPopup(True)
        if self.hour_edit.lineEdit():
            le = self.hour_edit.lineEdit()
            le.setReadOnly(False)
            le.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            le.setStyleSheet("QLineEdit { background-color: #F7EEE2; color: #000000; border: none; }")
            le.setPalette(le.palette())

        # The selected text is drawn in white on the deep accent colour of the
        # app; the focused dropdown shows the selected option the same way.
        for input_widget in (
            self.task_combo,
            self.date_edit,
            self.hour_edit,
            self.every_spin,
            self.unit_combo,
        ):
            try:
                input_widget.setAutoFillBackground(True)
                palette = input_widget.palette()
                palette.setColor(QPalette.ColorRole.Base, QColor("#F7EEE2"))
                palette.setColor(QPalette.ColorRole.Window, QColor("#F7EEE2"))
                palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
                palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
                palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
                palette.setColor(QPalette.ColorRole.Highlight, QColor("#4E4242"))
                palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
                input_widget.setPalette(palette)
                if hasattr(input_widget, 'lineEdit') and input_widget.lineEdit() is not None:
                    le = input_widget.lineEdit()
                    le.setAutoFillBackground(True)
                    le.setStyleSheet("QLineEdit { background-color: #F7EEE2; color: #000000; border: none; }")
                    le_palette = le.palette()
                    le_palette.setColor(QPalette.ColorRole.Base, QColor("#F7EEE2"))
                    le_palette.setColor(QPalette.ColorRole.Window, QColor("#F7EEE2"))
                    le_palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
                    le_palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
                    le_palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
                    le_palette.setColor(QPalette.ColorRole.Highlight, QColor("#4E4242"))
                    le_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
                    le.setPalette(le_palette)
            except Exception:
                pass

        for combo in (self.task_combo, self.unit_combo):
            if view := combo.view():
                view_palette = view.palette()
                view_palette.setColor(QPalette.ColorRole.Base, QColor(ROW_COLOR))
                view_palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
                view_palette.setColor(QPalette.ColorRole.Highlight, QColor("#4E4242"))
                view_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
                view.setPalette(view_palette)

        self.every_spin.setFixedWidth(70)
        self.hour_edit.setFixedWidth(100)
        self.unit_combo.setMinimumWidth(110)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.addRow("Task", self.task_combo)
        form.addRow("Date", self.date_edit)
        freq_wrap = QWidget()
        fw = QHBoxLayout(freq_wrap)
        fw.setContentsMargins(0, 0, 0, 0)
        fw.setSpacing(8)
        fw.addWidget(self.every_spin)
        fw.addWidget(self.unit_combo)
        fw.addStretch()
        form.addRow("Repeat every", freq_wrap)
        hour_wrap = QWidget()
        hw = QHBoxLayout(hour_wrap)
        hw.setContentsMargins(0, 0, 0, 0)
        hw.setSpacing(0)
        hw.addWidget(self.hour_edit)
        hw.addStretch()
        form.addRow("Hour", hour_wrap)
        layout.addLayout(form)

        hint = QLabel("The first run is on the chosen date at the chosen hour.")
        hint.setStyleSheet("font-size: 14px; color: #6B6259; background: transparent;")
        layout.addWidget(hint)

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

    def task_id(self) -> str:
        return self.task_combo.currentData()

    def start(self) -> datetime:
        date = self.date_edit.date()
        time = self.hour_edit.time()
        return datetime(date.year(), date.month(), date.day(), time.hour(), time.minute())

    def every(self) -> int:
        return self.every_spin.value()

    def unit(self) -> str:
        return self.unit_combo.currentData()

    def accept(self) -> None:
        """Add the task only when the chosen schedule makes sense."""
        error = CronScheduler.validate_interval(
            self.start(), self.every(), self.unit(), self.task_id()
        )
        if error:
            QMessageBox.warning(self, "Cannot add the task", error)
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Purgator")
        self.resize(1100, 720)

        self.settings = QSettings()
        self.runner = TaskRunner(self)
        self.scheduler = CronScheduler(self.runner, self.make_task, self.settings, self)

        self.buttons: dict[str, QPushButton] = {}
        self.bars: dict[str, QProgressBar] = {}
        self.results = _ResultTree()
        self.app_list = _ApplicationList()
        self._active_action: str | None = None  # "scan" / "cleanup" while a run is in flight
        self._starting = False  # True while _run_all_tasks is still queueing tasks
        self._found_bytes = 0  # size of the files the last run found
        self._found_files = 0  # number of those files
        self._found_categories = 0  # number of tasks that found something
        self._apps_worker: Worker | None = None  # the worker that looks for the apps
        self._apps_workers: list[Worker] = []  # they are kept alive until the app ends
        self._apps_action: str | None = None  # "scan" / "remove" while a run is in flight
        self._apps_scanned = False  # True when the applications were looked for

        central = QWidget()
        central.setStyleSheet("background-color: #F7EEE2; color: black;")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header_left = QLabel()
        self.header_left.setFixedWidth(210)
        self.header_left.setStyleSheet(
            "font-size: 24px; font-weight: 600; padding: 5px 12px 5px 12px; border: 1px solid #BDB6AA; border-left: none; border-top: none; border-right: 1px solid #BDB6AA;"
        )
        logo_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "assets" / "icons" / "purgator-logo.svg"
        )
        logo = QPixmap(str(logo_path))
        self.header_right = QLabel("Overview")
        self.header_right.setStyleSheet(
            "font-size: 24px; font-weight: 600; padding: 12px 12px 12px 12px; border: 1px solid #BDB6AA; border-top: none; border-right: none; border-left: none;"
        )
        if not logo.isNull():
            inner_h = self.header_right.sizeHint().height() - 10
            self.header_left.setPixmap(
                logo.scaledToHeight(inner_h, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.header_left.setText("Purgator")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)
        header.addWidget(self.header_left)
        header.addWidget(self.header_right, stretch=1)
        layout.addLayout(header)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.addWidget(self._build_nav())

        self.history_log = QListWidget()
        self.history_log.setVerticalScrollBar(_ThinScrollBar(Qt.Orientation.Vertical, self.history_log))
        self.history_log.setHorizontalScrollBar(_ThinScrollBar(Qt.Orientation.Horizontal, self.history_log))
        self.history_log.setStyleSheet(
            "QListWidget { background-color: #F7EEE2; border: none; outline: none; font-size: 13px; }"
            "QListWidget::item { padding: 4px 6px; }"
            "QListWidget::item:selected { background: transparent; color: black; }"
        )
        self.history_list = QTableWidget(0, 4)
        self.history_list.setHorizontalHeaderLabels(["Task", "Action", "When", "Status"])
        h = self.history_list.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setStretchLastSection(True)
        self.history_list.setColumnWidth(0, 220)
        self.history_list.setColumnWidth(1, 220)
        self.history_list.setColumnWidth(2, 200)
        self.history_list.setVerticalScrollBar(_ThinScrollBar(Qt.Orientation.Vertical, self.history_list))
        self.history_list.setHorizontalScrollBar(_ThinScrollBar(Qt.Orientation.Horizontal, self.history_list))
        palette_h = self.history_list.palette()
        palette_h.setColor(QPalette.ColorRole.Base, QColor(ROW_COLOR))
        palette_h.setColor(QPalette.ColorRole.AlternateBase, QColor(STRIPE_COLOR))
        palette_h.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        palette_h.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
        self.history_list.setPalette(palette_h)
        self.history_list.setAlternatingRowColors(False)
        self.history_list.setStyleSheet(
            f"QTableWidget {{ background: {ROW_COLOR}; border: none; outline: none; gridline-color: transparent; }}"
            f"QTableWidget::item {{ color: black; padding: 4px 16px; }}"
            f"QTableWidget::item:selected {{ background: transparent; color: black; }}"
            f"QHeaderView {{ background: {ROW_COLOR}; border: none; }}"
            f"QHeaderView::section {{ background: {ROW_COLOR}; color: #4E4242;"
            " border: none; border-bottom: 1px solid #BDB6AA; padding: 6px 16px;"
            " font-size: 14px; font-weight: 600; }"
            "QTableCornerButton::section { background: transparent; border: none; }"
        )
        self.history_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_list.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.history_list.setShowGrid(False)
        self.history_list.verticalHeader().setVisible(False)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_overview_page())
        self.stack.addWidget(self._build_cleanup_page())
        self.stack.addWidget(self._build_applications_page())
        self.stack.addWidget(self._build_schedule_page())
        self.stack.addWidget(self._build_history_page())
        self.stack.addWidget(self._build_placeholder_page("Whitelist"))
        self.stack.addWidget(self._build_placeholder_page("Settings"))
        content.addWidget(self.stack, stretch=1)

        layout.addLayout(content, stretch=1)
        self.setCentralWidget(central)

        self.stack.currentChanged.connect(self._on_page_changed)
        self._on_page_changed(self.stack.currentIndex())

        self.running_label = QLabel()
        self.statusBar().addWidget(self.running_label)
        self._on_running_changed(0)

        self.runner.task_started.connect(self._on_started)
        self.runner.task_progress.connect(self._on_progress)
        self.runner.task_finished.connect(self._on_finished)
        self.runner.task_failed.connect(self._on_failed)
        self.runner.task_cancelled.connect(self._on_cancelled)
        self.runner.running_changed.connect(self._on_running_changed)
        self.scheduler.jobs_changed.connect(self._refresh_jobs)
        self.scheduler.job_fired.connect(self._on_job_fired)
        self._refresh_jobs()

    def _build_nav(self) -> QListWidget:
        nav = QListWidget()
        nav.setFixedWidth(210)
        nav.setStyleSheet(
            "QListWidget { background: #F7EEE2; border: 1px solid #BDB6AA; border-top: none; border-left: none; border-bottom: none; font-size: 17px; outline: none; padding-top: 10px; }"
            "QListWidget::item { padding: 8px 12px; border: none; }"
            "QListWidget::item:selected { background: #F7EEE2; color: #4E4242; border: none; }"
            "QListWidget::item:hover { color: #4E4242; }"
            "QListWidget::item:focus { border: none; outline: none; }"
        )
        for item_id, label in NAV_ITEMS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, item_id)
            nav.addItem(item)
        self.nav = nav
        self.nav.currentRowChanged.connect(self._switch_page)
        return nav

    def _switch_page(self, row: int) -> None:
        self.stack.setCurrentIndex(row)

    def _on_page_changed(self, index: int) -> None:
        label = NAV_ITEMS[index][1] if 0 <= index < len(NAV_ITEMS) else "Overview"
        self.header_right.setText(label)
        if 0 <= index < self.nav.count():
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(index)
            self.nav.blockSignals(False)
        self._highlight_nav_item(index)

    def _highlight_nav_item(self, index: int) -> None:
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            font = item.font()
            selected = row == index
            font.setBold(selected)
            item.setFont(font)

    def _build_overview_page(self) -> QWidget:
        root_candidates = ["/run/host/root", "/home", "/"]
        root_path = "/"
        for c in root_candidates:
            try:
                p = Path(c)
                if p.exists():
                    root_path = c
                    break
            except Exception:
                continue
        usage = shutil.disk_usage(root_path)
        # compute home size from root fs perspective for accuracy
        home_size = usage.used
        try:
            import subprocess
            home_path_on_root = "/home"
            if root_path == "/run/host/root":
                home_path_on_root = "/run/host/root/home"
            r = subprocess.run(["du", "-s", "--block-size=1", home_path_on_root], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if r.returncode == 0:
                home_size = int(r.stdout.split()[0])
            else:
                home_size = shutil.disk_usage("/home").used
        except Exception:
            home_size = shutil.disk_usage("/home").used
        home_usage = type("U", (), {"total": usage.total, "used": home_size, "free": usage.free})()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        box_width = 340
        box = QGroupBox()
        box.setFixedWidth(box_width)
        box.setStyleSheet(
            "QGroupBox { background-color: #F7EEE2; border: 1px solid #BDB6AA; border-radius: 15px; }"
        )
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(10, 10, 10, 4)
        box_layout.setSpacing(0)
        box_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("Disk usage")
        title.setStyleSheet("font-size: 20px; font-weight: 600; color: black;")
        box_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignLeft)
        box_layout.addSpacing(0)
        chart_w = box_width - 20
        chart_h = int(chart_w * 0.86) + 6
        view = self._build_disk_usage_chart(usage, chart_w, chart_h)
        box_layout.addWidget(view)
        available = QLabel(f"{usage.free / (1024**3):.0f} GiB available")
        available.setAlignment(Qt.AlignmentFlag.AlignCenter)
        available.setStyleSheet("font-size: 16px; color: black; background: transparent;")
        box_layout.addSpacing(2)
        box_layout.addWidget(available)
        box_layout.addSpacing(24)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setStyleSheet("color: #BDB6AA; background-color: #BDB6AA;")
        separator.setFixedHeight(1)
        box_layout.addWidget(separator)
        box_layout.addSpacing(8)
        bar_view = self._build_home_to_disk_bar(home_usage, usage)
        box_layout.addWidget(bar_view)
        box_layout.addSpacing(60)

        right_container = QGroupBox()
        right_container.setFixedWidth(box_width)
        right_container.setStyleSheet(
            "QGroupBox { background-color: #F7EEE2; border: 1px solid #BDB6AA; border-radius: 15px; }"
        )
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(10, 10, 10, 4)
        right_layout.setSpacing(8)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_title = QLabel("Scheduled tasks")
        right_title.setStyleSheet("font-size: 20px; font-weight: 600; color: black;")
        right_layout.addWidget(right_title, alignment=Qt.AlignmentFlag.AlignLeft)
        right_container.setFixedHeight(box.sizeHint().height() // 2)

        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        row.setSpacing(60)
        row.addWidget(box, alignment=Qt.AlignmentFlag.AlignTop)
        row.addWidget(right_container, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        layout.addStretch()
        return page

    def _build_disk_usage_chart(self, usage, width: int = 360, height: int = 380) -> QWidget:
        used_gb = usage.used / (1024**3)
        total_gb = usage.total / (1024**3)
        used_pct = usage.used / usage.total * 100 if usage.total else 0
        used_frac = usage.used / usage.total if usage.total else 0

        view = _RingChart(used_frac)
        view.setFixedSize(width, height)

        center = QLabel(
            "<table cellpadding='0' cellspacing='0' align='center'>"
            f"<tr><td align='center' style='line-height: 70%;'><span style='font-size: 40px;'>{used_pct:.0f}%</span></td></tr>"
            "<tr><td align='center' style='padding-top: 5px; padding-bottom: 10px;'>"
            "<span style='font-size: 13px; color: black;'>used</span></td></tr>"
            f"<tr><td align='center'><span style='font-size: 16px;'>{used_gb:.0f} GiB / {total_gb:.0f} GiB</span></td></tr>"
            "</table>",
            view,
        )
        center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.setStyleSheet("color: black; background: transparent;")
        center.setGeometry(0, 0, width, height)
        center.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return view

    def _build_home_to_disk_bar(self, home_usage, disk_usage) -> QWidget:
        occupied = disk_usage.used
        home_used = home_usage.used

        if occupied <= 0:
            occupied = 1

        home_frac = home_used / occupied

        bar_width = 300
        bar = _RatioBar(home_frac)
        bar.setFixedHeight(12)
        bar.setFixedWidth(bar_width)

        section_title = QLabel("Home directory")
        section_title.setStyleSheet("font-size: 20px; font-weight: 600; color: black; background: transparent;")
        section_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        lbl = QLabel(f"<span style='font-size:16px;color:black;'>{home_used/(1024**3):.0f} GiB</span>")
        lbl.setStyleSheet("background: transparent;")
        lbl.setFixedWidth(bar_width)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 12)
        vbox.setSpacing(0)
        vbox.addWidget(section_title)
        vbox.addSpacing(16)
        vbox.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignHCenter)
        vbox.addSpacing(4)
        vbox.addWidget(bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        vbox.addSpacing(16)
        pct = QLabel(f"<span style='font-size:16px;color:black;'>{home_frac * 100:.0f}% of disk space is used by your files</span>")
        pct.setStyleSheet("background: transparent;")
        pct.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        vbox.addWidget(pct, alignment=Qt.AlignmentFlag.AlignHCenter)

        return container

    def _build_history_page(self) -> QWidget:
        page, layout = _page_widget("History", with_heading=False)
        top = QFrame()
        top.setObjectName("historyTopBox")
        top.setStyleSheet(
            "QFrame#historyTopBox { background-color: #F7EEE2;"
            " border: 1px solid #BDB6AA; border-radius: 15px; }"
            "QLabel { background: transparent; border: none; }"
        )
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(14, 6, 14, 14)
        top_layout.setSpacing(6)
        label_top = QLabel("History")
        label_top.setStyleSheet("font-size: 16px; font-weight: 600; color: black;")
        top_layout.addWidget(label_top)
        top_layout.addWidget(self.history_list)
        bottom = QFrame()
        bottom.setObjectName("historyLogBox")
        bottom.setStyleSheet(
            "QFrame#historyLogBox { background-color: #F7EEE2;"
            " border: 1px solid #BDB6AA; border-radius: 15px; }"
            "QLabel { background: transparent; border: none; }"
        )
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(14, 6, 14, 14)
        bottom_layout.setSpacing(6)
        label_bot = QLabel("Logs")
        label_bot.setStyleSheet("font-size: 16px; font-weight: 600; color: black;")
        bottom_layout.addWidget(label_bot)
        bottom_layout.addWidget(self.history_log)
        layout.addWidget(top)
        layout.addWidget(bottom, stretch=1)
        return page

    def _build_placeholder_page(self, title: str) -> QWidget:
        page, layout = _page_widget(title)
        hint = QLabel("Nothing here yet.")
        hint.setStyleSheet("color: black; padding-left: 4px;")
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def _build_cleanup_page(self) -> QWidget:
        # "Cleanup" appears only in the top header, not as a page heading.
        page, layout = _page_widget("Cleanup", with_heading=False)
        layout.addLayout(self._build_cleanup_actions())
        layout.addWidget(self._build_categories(), stretch=1)
        return page

    def _build_categories(self) -> QWidget:
        container = QFrame()
        container.setObjectName("categoryBox")
        container.setStyleSheet(
            "QFrame#categoryBox { background-color: #F7EEE2;"
            " border: 1px solid #BDB6AA; border-radius: 15px; }"
            "QLabel { background: transparent; border: none; }"
        )

        column = QVBoxLayout(container)
        column.setContentsMargins(14, 2, 14, 14)
        column.setSpacing(8)

        for task_id, cls in TASKS.items():
            self.results.add_category(task_id, CATEGORY_LABELS.get(task_id, cls.name))
        column.addWidget(self.results, stretch=1)
        return container

    def _build_cleanup_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 12)
        row.setSpacing(12)

        self.info_label = QLabel("Nothing scanned yet")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setStyleSheet(
            "font-size: 19px; color: black; background: transparent;"
        )
        row.addWidget(self.info_label)
        row.addStretch()

        self.scan_button = QPushButton("Scan")
        self.scan_button.setStyleSheet(PLAIN_BUTTON_STYLE)
        self.scan_button.clicked.connect(lambda: self._on_action_clicked("scan"))

        self.cleanup_button = QPushButton("Clean up")
        self.cleanup_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.cleanup_button.clicked.connect(lambda: self._on_action_clicked("cleanup"))

        row.addWidget(self.scan_button)
        row.addWidget(self.cleanup_button)
        return row

    def _build_applications_page(self) -> QWidget:
        # "Applications" appears only in the top header, not as a page heading.
        page, layout = _page_widget("Applications", with_heading=False)
        layout.addLayout(self._build_applications_actions())
        layout.addWidget(self._build_applications_box(), stretch=1)
        return page

    def _build_applications_box(self) -> QWidget:
        container = QFrame()
        container.setObjectName("applicationBox")
        container.setStyleSheet(
            "QFrame#applicationBox { background-color: #F7EEE2;"
            " border: 1px solid #BDB6AA; border-radius: 15px; }"
            "QLabel { background: transparent; border: none; }"
        )

        column = QVBoxLayout(container)
        column.setContentsMargins(14, 2, 14, 14)
        column.setSpacing(8)

        self.app_list.itemChanged.connect(self._update_apps_info)
        column.addWidget(self.app_list, stretch=1)
        return container

    def _build_applications_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 12)
        row.setSpacing(12)

        self.apps_info_label = QLabel("Nothing scanned yet")
        self.apps_info_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.apps_info_label.setStyleSheet(
            "font-size: 19px; color: black; background: transparent;"
        )
        row.addWidget(self.apps_info_label)
        row.addStretch()

        self.apps_scan_button = QPushButton("Scan")
        self.apps_scan_button.setStyleSheet(PLAIN_BUTTON_STYLE)
        self.apps_scan_button.clicked.connect(self._on_apps_scan_clicked)

        self.apps_remove_button = QPushButton("Remove")
        self.apps_remove_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.apps_remove_button.clicked.connect(self._on_apps_remove_clicked)

        row.addWidget(self.apps_scan_button)
        row.addWidget(self.apps_remove_button)
        return row

    def _add_history_entry(self, task: str, action: str, status: str) -> None:
        try:
            if hasattr(self, 'history_list'):
                stamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
                self.history_list.insertRow(0)
                for c, val in enumerate([str(task), str(action), str(stamp), str(status)]):
                    it = QTableWidgetItem(val)
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if c == 1:
                        it.setToolTip(val)
                    bg = QColor(STRIPE_COLOR) if 0 % 2 == 1 else QColor(ROW_COLOR)
                    it.setBackground(bg)
                    self.history_list.setItem(0, c, it)
                # stripe all rows
                for r in range(self.history_list.rowCount()):
                    bg = QColor(STRIPE_COLOR) if r % 2 == 1 else QColor(ROW_COLOR)
                    for c in range(self.history_list.columnCount()):
                        it = self.history_list.item(r, c)
                        if it:
                            it.setBackground(bg)
                self.history_list.resizeColumnsToContents()
                if self.history_list.columnWidth(0) < 220:
                    self.history_list.setColumnWidth(0, 220)
                if self.history_list.columnWidth(1) < 220:
                    self.history_list.setColumnWidth(1, 220)
                if self.history_list.columnWidth(2) < 200:
                    self.history_list.setColumnWidth(2, 200)
        except Exception:
            pass

    def log(self, message: str) -> None:
        stamp = QTime.currentTime().toString("HH:mm:ss")
        line = f"[{stamp}] {message}"
        print(line)
        try:
            if hasattr(self, 'history_log'):
                item = QListWidgetItem(line)
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                self.history_log.addItem(item)
                self.history_log.scrollToBottom()
        except Exception:
            pass
        try:
            m = message
            if m.startswith("["):
                # already prefixed
                pass
            # detect events
            if "applications: started" in m or ("Looking for applications" in m and "started" not in m.lower()):
                pass
            if "applications: FAILED" in m:
                self._add_history_entry("Applications:scan", "-", "Failed")
            elif m.strip().startswith("applications: cancelled") or "cancelled" in m and "applications" in m:
                if "scan" in getattr(self, '_apps_action', '') or 'scan' in m.lower():
                    self._add_history_entry("Applications:scan", "-", "Canceled")
                else:
                    self._add_history_entry("Applications:remove", "-", "Canceled")
            elif m.strip().startswith("applications:") and "found" in m:
                # found count logged elsewhere? try to infer
                self._add_history_entry("Applications:scan", m.split("applications:")[-1].strip(), "Successfull")
            elif "remove" in m.lower() and "applications" in m.lower() and ("done" in m.lower() or "→ done" in m):
                # count will be added from results; add generic if not
                self._add_history_entry("Applications:remove", m.split("remove")[-1].strip() if "remove" in m else "-", "Successfull")
            elif "schedule" in m.lower() and "fired" in m.lower():
                self._add_history_entry("Schedule:run", "-", "Successfull")
        except Exception:
            pass

    def _build_schedule_page(self) -> QWidget:
        # "Schedule" appears only in the top header, not as a page heading.
        page, layout = _page_widget("Schedule", with_heading=False)
        layout.addLayout(self._build_schedule_actions())
        layout.addWidget(self._build_schedule_box(), stretch=1)
        return page

    def _build_schedule_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 12)
        row.setSpacing(12)

        self.schedule_info_label = QLabel("0 tasks · 0 active · 0 inactive")
        self.schedule_info_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.schedule_info_label.setStyleSheet(
            "font-size: 19px; color: black; background: transparent;"
        )
        row.addWidget(self.schedule_info_label)
        row.addStretch()

        self.new_task_button = QPushButton("New Task")
        self.new_task_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.new_task_button.clicked.connect(self._new_task)
        row.addWidget(self.new_task_button)
        return row

    def _build_schedule_box(self) -> QWidget:
        container = QFrame()
        container.setObjectName("scheduleBox")
        container.setStyleSheet(
            "QFrame#scheduleBox { background-color: #F7EEE2;"
            " border: 1px solid #BDB6AA; border-radius: 15px; }"
        )

        column = QVBoxLayout(container)
        column.setContentsMargins(14, 2, 14, 14)
        column.setSpacing(8)

        self.jobs_table = QTableWidget(0, 5)
        self.jobs_table.setHorizontalHeaderLabels(["Enabled", "Schedule", "Task", "Next run", ""])
        header = self.jobs_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self.jobs_table.setColumnWidth(0, 70)
        self.jobs_table.setColumnWidth(2, 76)
        self.jobs_table.setColumnWidth(3, 44)
        self.jobs_table.setColumnWidth(4, 4)
        self.jobs_table.resizeColumnToContents(1)
        if self.jobs_table.columnWidth(1) < 450:
            self.jobs_table.setColumnWidth(1, 450)
        self.jobs_table.setColumnWidth(3, 44)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)

        palette = self.jobs_table.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(ROW_COLOR))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(ROW_COLOR))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
        self.jobs_table.setPalette(palette)
        self.jobs_table.setStyleSheet(
            f"QTableWidget {{ background: {ROW_COLOR}; border: none; outline: none; }}"
            f"QTableWidget::item {{ background: {ROW_COLOR}; color: black; }}"
            f"QTableWidget::item:selected {{ background: {ROW_COLOR}; color: black; }}"
            f"QHeaderView::section {{ background: {ROW_COLOR}; color: #4E4242;"
            " border: none; border-bottom: 1px solid #BDB6AA; padding: 4px 6px;"
            " font-size: 14px; font-weight: 600; }"
        )
        column.addWidget(self.jobs_table, stretch=1)

        row = QHBoxLayout()
        row.addStretch()
        column.addLayout(row)
        return container

    def make_task(self, task_id: str, dry_run: bool = False) -> PurgeTask:
        if task_id == ProjectBuildsTask.id:
            root = self.settings.value(BUILDS_ROOT_KEY, str(Path.home()))
            return create_task(task_id, dry_run=dry_run, root=Path(root))
        return create_task(task_id, dry_run=dry_run)

    def _on_action_clicked(self, action: str) -> None:
        """The button shows 'Cancel' while it is the one running: cancel instead."""
        if self._active_action is not None:
            if self._active_action == action:
                try:
                    self._cleanup_action_was = action
                except Exception:
                    pass
                self.runner.cancel_all()
            return
        try:
            self._cleanup_action_was = action
        except Exception:
            pass
        if action == "scan":
            self._scan_all()
        else:
            self._cleanup_all()

    def _scan_all(self) -> None:
        """Report what every task would delete, without touching anything."""
        self._active_action = "scan"
        self._reset_found("Scanning…")
        self._run_all_tasks(dry_run=True)

    def _cleanup_all(self) -> None:
        """Delete the checked entries, after asking for confirmation."""
        selection = {task_id: self.results.checked_paths(task_id) for task_id in TASKS}
        count = sum(len(paths) for paths in selection.values())
        if not count:
            QMessageBox.information(
                self,
                "Nothing selected",
                "No files are selected. Tick the files you want to delete first.",
            )
            return
        answer = QMessageBox.warning(
            self,
            "Delete files?",
            f"Cleaning up will permanently delete {count} selected entries. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._active_action = "cleanup"
        self._reset_found("Cleaning up…")
        self._run_all_tasks(dry_run=False, selection=selection)

    def _on_apps_scan_clicked(self) -> None:
        """The button shows 'Cancel' while it is the one running: cancel instead."""
        if self._apps_action == "scan":
            if self._apps_worker is not None:
                self._apps_worker.cancel()
            return
        if self._apps_action is not None:
            return
        self._apps_action_was = "scan"
        self._scan_applications()

    def _scan_applications(self) -> None:
        """Look for the installed applications, without freezing the window."""
        self._apps_action = "scan"
        self.apps_info_label.setText("Looking for applications…")
        worker = Worker(_ApplicationsScan())
        self._apps_worker = worker
        self._apps_workers.append(worker)  # the pool does not delete them
        worker.signals.finished.connect(self._on_apps_found)
        worker.signals.failed.connect(self._on_apps_failed)
        worker.signals.cancelled.connect(self._on_apps_cancelled)
        worker.signals.progress.connect(self._on_apps_progress)
        self.runner.pool.start(worker)
        self._update_apps_buttons()

    def _on_apps_found(self, _task_id: str, apps: list[Application]) -> None:
        self._apps_action = None
        self._apps_scanned = True
        self._apps_worker = None
        self.app_list.set_applications(apps)
        self._update_apps_buttons()
        self._update_apps_info()
        self.log(f"applications: {len(apps)} found")
        try:
            self._add_history_entry("Applications:scan", f"{len(apps)} found", "Successfull")
            if self.history_list.columnWidth(0) < 220:
                self.history_list.setColumnWidth(0, 220)
            if self.history_list.columnWidth(1) < 220:
                self.history_list.setColumnWidth(1, 220)
            if self.history_list.columnWidth(2) < 200:
                self.history_list.setColumnWidth(2, 200)
        except Exception:
            pass

    def _on_apps_failed(self, _task_id: str, error: str) -> None:
        self._apps_action = None
        self._apps_worker = None
        self._update_apps_buttons()
        self.apps_info_label.setText("Looking for the applications failed")
        self.log(f"applications: FAILED\n{error}")
        try:
            self._add_history_entry("Applications:scan", "-", "Failed")
        except Exception:
            pass

    def _on_apps_cancelled(self, _task_id: str) -> None:
        self._apps_action = None
        self._apps_worker = None
        self._update_apps_buttons()
        self.apps_info_label.setText("Looking for the applications was cancelled")
        self.log("applications: cancelled")
        try:
            if getattr(self, '_apps_action_was', None) == 'remove':
                self._add_history_entry("Applications:remove", "-", "Canceled")
            else:
                self._add_history_entry("Applications:scan", "-", "Canceled")
        except Exception:
            pass

    def _on_apps_progress(self, _task_id: str, _percent: int, message: str) -> None:
        """Say what the running worker is doing."""
        if message:
            self.apps_info_label.setText(message)

    def _update_apps_buttons(self) -> None:
        # The button that started the run turns into "Cancel"; the other one stays disabled.
        self.apps_scan_button.setText("Cancel" if self._apps_action == "scan" else "Scan")
        self.apps_remove_button.setText("Cancel" if self._apps_action == "remove" else "Remove")
        running = self._apps_action is not None
        self.apps_scan_button.setEnabled(not running or self._apps_action == "scan")
        self.apps_remove_button.setEnabled(not running or self._apps_action == "remove")

    def _update_apps_info(self, *_) -> None:
        """Show how many applications were found and how many are ticked."""
        if not self._apps_scanned:
            self.apps_info_label.setText("Nothing scanned yet")
            return
        found = self.app_list.count
        checked = len(self.app_list.checked_applications())
        text = f"Found {found} application" if found == 1 else f"Found {found} applications"
        unused = self.app_list.never_used_count
        if unused:
            text += f" · {unused} never used"
        old = self.app_list.old_count
        if old:
            text += f" · {old} not used for months"
        if checked:
            text += f" · {checked} selected"
        self.apps_info_label.setText(text)

    def _on_apps_remove_clicked(self) -> None:
        """Remove the ticked applications, after asking for confirmation."""
        if self._apps_action == "remove":
            if self._apps_worker is not None:
                self._apps_worker.cancel()
            return
        if self._apps_action is not None:
            return
        apps = self.app_list.checked_applications()
        if not apps:
            QMessageBox.information(
                self,
                "Nothing selected",
                "No applications are selected. Tick the applications you want to remove first.",
            )
            return
        answer = QMessageBox.warning(
            self,
            "Remove applications?",
            f"Removing will permanently uninstall {len(apps)} selected applications. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._apps_action_was = "remove"
        self._remove_applications(apps)

    def _remove_applications(self, apps: list[Application]) -> None:
        """Uninstall the applications; the ones of the system ask for the password."""
        self._apps_action = "remove"
        self.apps_info_label.setText(f"Removing {len(apps)} applications…")
        worker = Worker(_ApplicationsRemoval(apps))
        self._apps_worker = worker
        self._apps_workers.append(worker)
        worker.signals.finished.connect(self._on_apps_removed)
        worker.signals.failed.connect(self._on_apps_failed)
        worker.signals.cancelled.connect(self._on_apps_cancelled)
        worker.signals.progress.connect(self._on_apps_progress)
        self.runner.pool.start(worker)
        self._update_apps_buttons()

    def _on_apps_removed(self, _task_id: str, results: list) -> None:
        self._apps_action = None
        self._apps_worker = None
        self._update_apps_buttons()
        removed = [app for app, ok, _ in results if ok]
        failed = [(app, message) for app, ok, message in results if not ok]
        if removed:
            self.app_list.remove_applications(removed)
        text = f"Removed {len(removed)} application" + ("s" if len(removed) != 1 else "")
        if failed:
            text += f" · {len(failed)} failed"
        self.apps_info_label.setText(text)
        for app, ok, message in results:
            self.log(f"remove {app.source}: {app.package} → {'done' if ok else 'failed'}")
            if message and not ok:
                self.log(f"    {message}")
        try:
            if failed:
                self._add_history_entry("Applications:remove", f"{len(removed)} removed, {len(failed)} failed", "Failed")
            else:
                self._add_history_entry("Applications:remove", f"{len(removed)} removed", "Successfull")
        except Exception:
            pass

    def _reset_found(self, status: str) -> None:
        self._found_bytes = 0
        self._found_files = 0
        self._found_categories = 0
        self.info_label.setText(status)
        self.results.reset(status)

    def _add_found(self, result: TaskResult) -> None:
        """Add a finished task to the totals shown next to the buttons."""
        self._found_bytes += result.bytes
        self._found_files += result.files
        if result.files:
            self._found_categories += 1
        files = f"{self._found_files} file" if self._found_files == 1 else f"{self._found_files} files"
        categories = (
            "1 category" if self._found_categories == 1 else f"{self._found_categories} categories"
        )
        self.info_label.setText(
            f"Found {human_size(self._found_bytes)}\n{files} selected across {categories}"
        )

    def _run_all_tasks(
        self, dry_run: bool, selection: dict[str, set[Path]] | None = None
    ) -> None:
        self._starting = True
        try:
            for task_id in TASKS:
                task = self.make_task(task_id, dry_run=dry_run)
                if selection is not None:
                    task.only = selection.get(task_id, set())
                self.runner.run(task)
        finally:
            self._starting = False
        self._on_running_changed(self.runner.running_count)

    def start_task(self, task_id: str) -> None:
        if self.runner.is_running(task_id):
            self.runner.cancel(task_id)
            return
        if task_id == ProjectBuildsTask.id:
            current = self.settings.value(BUILDS_ROOT_KEY, str(Path.home()))
            root = QFileDialog.getExistingDirectory(self, "Scan for project builds in…", current)
            if not root:
                return
            self.settings.setValue(BUILDS_ROOT_KEY, root)
        answer = QMessageBox.warning(
            self,
            "Delete files?",
            f"“{TASKS[task_id].name}” will permanently delete files. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.runner.run(self.make_task(task_id))

    def _set_idle(self, task_id: str, text: str) -> None:
        if bar := self.bars.get(task_id):
            bar.setRange(0, 100)
            bar.setFormat(text)
        if button := self.buttons.get(task_id):
            button.setText(TASKS[task_id].name)

    def _on_started(self, task_id: str) -> None:
        if bar := self.bars.get(task_id):
            bar.setRange(0, 0)  # busy indicator until first percentage arrives
        if button := self.buttons.get(task_id):
            button.setText(f"Cancel: {TASKS[task_id].name}")
        self.log(f"{task_id}: started")

    def _on_progress(self, task_id: str, percent: int, message: str) -> None:
        bar = self.bars.get(task_id)
        if bar is None:
            return
        if percent < 0:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(percent)
            bar.setFormat("%p%")
        bar.setToolTip(message)

    def _on_finished(self, task_id: str, result: TaskResult) -> None:
        if bar := self.bars.get(task_id):
            bar.setValue(100)
        self._set_idle(task_id, "done")
        self._add_found(result)
        self.results.show_result(result)
        self.log(result.summary())
        try:
            action = getattr(self, '_cleanup_action_was', None) or getattr(self, '_active_action', None)
            if action == 'scan':
                task_name = TASKS.get(task_id).name if task_id in TASKS else task_id
                self._add_history_entry(f"Cleanup:{task_name}:scan", f"{result.files} files · {human_size(result.bytes)}", "Successfull")
            elif action == 'cleanup':
                task_name = TASKS.get(task_id).name if task_id in TASKS else task_id
                self._add_history_entry(f"Cleanup:{task_name}:remove", f"{result.files} files · {human_size(result.bytes)}", "Successfull")
        except Exception:
            pass
        for path in result.paths[:20]:
            self.log(f"    {path}")
        if len(result.paths) > 20:
            self.log(f"    … and {len(result.paths) - 20} more")

    def _on_failed(self, task_id: str, error: str) -> None:
        self._set_idle(task_id, "failed")
        self.log(f"{task_id}: FAILED\n{error}")
        try:
            action = getattr(self, '_cleanup_action_was', None) or getattr(self, '_active_action', None)
            task_name = TASKS.get(task_id).name if task_id in TASKS else task_id
            if action == 'scan':
                self._add_history_entry(f"Cleanup:{task_name}:scan", "-", "Failed")
            elif action == 'cleanup':
                self._add_history_entry(f"Cleanup:{task_name}:remove", "-", "Failed")
            else:
                self._add_history_entry(task_name, "-", "Failed")
        except Exception:
            pass

    def _on_cancelled(self, task_id: str) -> None:
        if bar := self.bars.get(task_id):
            bar.setValue(0)
        self._set_idle(task_id, "cancelled")
        self.log(f"{task_id}: cancelled")
        try:
            action = getattr(self, '_cleanup_action_was', None)
            task_name = TASKS.get(task_id).name if task_id in TASKS else task_id
            if action == 'scan':
                self._add_history_entry(f"Cleanup:{task_name}:scan", "-", "Canceled")
            elif action == 'cleanup':
                self._add_history_entry(f"Cleanup:{task_name}:remove", "-", "Canceled")
            else:
                self._add_history_entry(task_name, "-", "Canceled")
        except Exception:
            pass

    def _on_running_changed(self, count: int) -> None:
        self.running_label.setText(f"{count} task(s) running" if count else "Idle")
        busy = count > 0
        if not busy and not self._starting:
            self._active_action = None  # run is over: the buttons get their labels back
        # The button that started the run turns into "Cancel"; the other one stays disabled.
        self.scan_button.setText("Cancel" if self._active_action == "scan" else "Scan")
        self.cleanup_button.setText("Cancel" if self._active_action == "cleanup" else "Clean up")
        running = busy or self._starting
        self.scan_button.setEnabled(not running or self._active_action == "scan")
        self.cleanup_button.setEnabled(not running or self._active_action == "cleanup")

    # --- schedule -----------------------------------------------------------

    def _new_task(self) -> None:
        """Ask how the new task looks and add it to the schedule."""
        dialog = _NewTaskDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        job = self.scheduler.add_interval_job(
            dialog.start(), dialog.every(), dialog.unit(), dialog.task_id()
        )
        self.log(f"scheduled {job.task_id}: {job.describe()}")

    def _set_job_enabled(self, row: int, enabled: bool) -> None:
        if 0 <= row < len(self.scheduler.jobs):
            self.scheduler.set_enabled(row, enabled)

    def _remove_job_row(self, row: int) -> None:
        if 0 <= row < len(self.scheduler.jobs):
            self.scheduler.remove_job(row)

    def _on_job_fired(self, job: Job, started: bool) -> None:
        note = "" if started else " (skipped, already running)"
        self.log(f"schedule '{job.describe()}' fired {job.task_id}{note}")

    def _refresh_jobs(self) -> None:
        table = self.jobs_table
        table.setRowCount(len(self.scheduler.jobs))
        for row, job in enumerate(self.scheduler.jobs):
            toggle = _Switch(job.enabled)
            toggle.setToolTip("Enabled" if job.enabled else "Disabled")
            toggle.toggled.connect(lambda checked, r=row: self._set_job_enabled(r, checked))
            toggle_cell = QWidget()
            toggle_cell.setStyleSheet("background: transparent;")
            tc_layout = QHBoxLayout(toggle_cell)
            tc_layout.setContentsMargins(0, 0, 0, 0)
            tc_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tc_layout.addWidget(toggle)
            table.setCellWidget(row, 0, toggle_cell)

            table.setItem(row, 1, QTableWidgetItem(job.describe()))
            table.setItem(row, 2, QTableWidgetItem(TASKS[job.task_id].name))
            nxt = self.scheduler.next_run(job)
            table.setItem(row, 3, QTableWidgetItem(nxt.strftime("%Y-%m-%d %H:%M") if nxt else "—"))

            remove = QPushButton("×")
            remove.setFixedSize(22, 22)
            remove.setStyleSheet(
                "QPushButton { background-color: transparent; color: #4E4242; border: none; font-size: 16px; }"
                "QPushButton:hover { color: #7C6565; }"
            )
            remove.clicked.connect(lambda _=False, r=row: self._remove_job_row(r))
            remove_cell = QWidget()
            remove_cell.setStyleSheet("background: transparent;")
            rc_layout = QHBoxLayout(remove_cell)
            rc_layout.setContentsMargins(0, 0, 0, 0)
            rc_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rc_layout.addWidget(remove)
            table.setCellWidget(row, 4, remove_cell)
        total = len(self.scheduler.jobs)
        active = sum(1 for job in self.scheduler.jobs if job.enabled)
        tasks = "task" if total == 1 else "tasks"
        self.schedule_info_label.setText(
            f"{total} {tasks} · {active} active · {total - active} inactive"
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self.runner.shutdown()
        super().closeEvent(event)