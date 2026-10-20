from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSettings, QSize, Qt, QTime
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
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from purgator.scheduler import CronScheduler, Job
from purgator.tasks import TASKS, PurgeTask, TaskResult, create_task, human_size
from purgator.tasks.builtin import ProjectBuildsTask
from purgator.workers import TaskRunner

BUILDS_ROOT_KEY = "tasks/project_builds/root"

# Label of the per-category panel shown on the Cleanup page
CATEGORY_LABELS = {
    "user_cache": "User logs",
    "stale_files": "Stale temp files",
    "project_builds": "Project builds",
}

# How many paths to list per category before it starts truncating
MAX_ROWS = 100

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

# Arrow in front of a category name: the dropdown is open or closed
ARROW_DOWN = "▾"
ARROW_RIGHT = "▸"

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


class _CheckBoxDelegate(QStyledItemDelegate):
    """Draws the check box in the last column of the result list."""

    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)

    def paint(self, painter, option, index) -> None:
        raw = index.data(Qt.ItemDataRole.CheckStateRole)
        if raw is None:
            super().paint(painter, option, index)
            return
        state = Qt.CheckState(raw)
        side = min(option.rect.height() - 10, 16)
        box = QRectF(
            option.rect.left() + (option.rect.width() - side) / 2,
            option.rect.top() + (option.rect.height() - side) / 2,
            side,
            side,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # the cell and the empty box keep the background of its row
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        row_colour = QColor(ROW_COLOR)
        if isinstance(background, QBrush):
            row_colour = background.color()
        elif isinstance(background, QColor):
            row_colour = background
        painter.fillRect(option.rect, row_colour)
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
        self.setItemDelegateForColumn(2, _CheckBoxDelegate(self))
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setExpandsOnDoubleClick(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        # The scroll bar always keeps its space, so opening a category never
        # shifts the rows sideways.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(ROW_COLOR))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(ROW_COLOR))
        # A transparent highlight keeps the row looking the same when it is clicked.
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
        self.setPalette(palette)
        self.setStyleSheet(
            "QTreeWidget { background: #F7EEE2; border: none; outline: none;"
            " font-size: 13px; }"
            "QTreeWidget::item { padding: 3px 2px; }"
            "QTreeWidget::item:selected { background: transparent; color: black; }"
            "QHeaderView::section { background: transparent; color: #4E4242;"
            " border: none; border-bottom: 1px solid #BDB6AA; padding: 4px 6px;"
            " font-size: 13px; font-weight: 600; }"
        )
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
        for path in result.paths[:MAX_ROWS]:
            kind = "D" if path in result.directories else "F"
            size = human_size(result.sizes.get(path, 0))
            child = QTreeWidgetItem(item, [f"{kind}{KIND_GAP}{_display_path(path)}", size, ""])
            child.setData(2, Qt.ItemDataRole.UserRole, path)
            child.setCheckState(2, Qt.CheckState.Checked)
            child.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            child.setSizeHint(0, QSize(0, FILE_HEIGHT))
        if len(result.paths) > MAX_ROWS:
            more = QTreeWidgetItem(item, [f"… and {len(result.paths) - MAX_ROWS} more", "", ""])
            more.setSizeHint(0, QSize(0, FILE_HEIGHT))
        self._paint_files(item)
        self._sync(result.task_id)

    @staticmethod
    def _clear_children(item: QTreeWidgetItem) -> None:
        # takeChildren() hands the rows over to Python, so dropping them deletes them.
        item.takeChildren()


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
        self._active_action: str | None = None  # "scan" / "cleanup" while a run is in flight
        self._starting = False  # True while _run_all_tasks is still queueing tasks
        self._found_bytes = 0  # size of the files the last run found
        self._found_files = 0  # number of those files
        self._found_categories = 0  # number of tasks that found something

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

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_overview_page())
        self.stack.addWidget(self._build_cleanup_page())
        self.stack.addWidget(self._build_placeholder_page("Applications"))
        self.stack.addWidget(self._build_schedule_page())
        self.stack.addWidget(self._build_placeholder_page("History"))
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
        layout.addWidget(self._build_categories())
        layout.addStretch()
        return page

    def _build_categories(self) -> QWidget:
        container = QFrame()
        container.setObjectName("categoryBox")
        container.setStyleSheet(
            "QFrame#categoryBox { background-color: #F7EEE2;"
            " border: 1px solid #BDB6AA; border-radius: 15px; }"
            "QLabel { background: transparent; border: none; }"
        )
        container.setFixedHeight(520)

        column = QVBoxLayout(container)
        column.setContentsMargins(14, 10, 14, 14)
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
        self.scan_button.setStyleSheet(
            "QPushButton { background-color: #F7EEE2; color: #4E4242;"
            " border: 1px solid #4E4242; border-radius: 15px;"
            " padding: 4px 22px; font-size: 18px; }"
            "QPushButton:hover { background-color: #EDE2D1; }"
            "QPushButton:disabled { color: #A79E92; border-color: #A79E92; }"
        )
        self.scan_button.clicked.connect(lambda: self._on_action_clicked("scan"))

        self.cleanup_button = QPushButton("Clean up")
        self.cleanup_button.setStyleSheet(
            "QPushButton { background-color: #4E4242; color: #F7EEE2;"
            " border: 1px solid #4E4242; border-radius: 15px;"
            " padding: 4px 22px; font-size: 18px; }"
            "QPushButton:hover { background-color: #5C4E4E; }"
            "QPushButton:disabled { background-color: #9C9393; border-color: #9C9393; }"
        )
        self.cleanup_button.clicked.connect(lambda: self._on_action_clicked("cleanup"))

        row.addWidget(self.scan_button)
        row.addWidget(self.cleanup_button)
        return row

    def log(self, message: str) -> None:
        stamp = QTime.currentTime().toString("HH:mm:ss")
        print(f"[{stamp}] {message}")

    def _build_schedule_page(self) -> QWidget:
        page, layout = _page_widget("Schedule")
        layout.addWidget(self._build_schedule_box())
        layout.addStretch()
        return page

    def _build_schedule_box(self) -> QGroupBox:
        box = QGroupBox("Schedule (cron)")
        layout = QVBoxLayout(box)

        self.jobs_table = QTableWidget(0, 4)
        self.jobs_table.setHorizontalHeaderLabels(["Enabled", "Cron", "Task", "Next run"])
        self.jobs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.jobs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.jobs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.jobs_table.setMaximumHeight(160)
        self.jobs_table.itemChanged.connect(self._on_job_item_changed)
        layout.addWidget(self.jobs_table)

        row = QHBoxLayout()
        self.cron_edit = QLineEdit(placeholderText="e.g. 0 3 * * *  (daily at 03:00)")
        self.task_combo = QComboBox()
        for task_id, cls in TASKS.items():
            self.task_combo.addItem(cls.name, task_id)
        add = QPushButton("Add")
        add.clicked.connect(self._add_job)
        self.cron_edit.returnPressed.connect(self._add_job)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_job)
        row.addWidget(self.cron_edit, stretch=1)
        row.addWidget(self.task_combo)
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        return box

    def make_task(self, task_id: str, dry_run: bool = False) -> PurgeTask:
        if task_id == ProjectBuildsTask.id:
            root = self.settings.value(BUILDS_ROOT_KEY, str(Path.home()))
            return create_task(task_id, dry_run=dry_run, root=Path(root))
        return create_task(task_id, dry_run=dry_run)

    def _on_action_clicked(self, action: str) -> None:
        """The button shows 'Cancel' while it is the one running: cancel instead."""
        if self._active_action is not None:
            if self._active_action == action:
                self.runner.cancel_all()
            return
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
        for path in result.paths[:20]:
            self.log(f"    {path}")
        if len(result.paths) > 20:
            self.log(f"    … and {len(result.paths) - 20} more")

    def _on_failed(self, task_id: str, error: str) -> None:
        self._set_idle(task_id, "failed")
        self.log(f"{task_id}: FAILED\n{error}")

    def _on_cancelled(self, task_id: str) -> None:
        if bar := self.bars.get(task_id):
            bar.setValue(0)
        self._set_idle(task_id, "cancelled")
        self.log(f"{task_id}: cancelled")

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

    def _add_job(self) -> None:
        cron = self.cron_edit.text().strip()
        task_id = self.task_combo.currentData()
        if error := CronScheduler.validate(cron, task_id):
            QMessageBox.warning(self, "Invalid job", error)
            return
        self.scheduler.add_job(cron, task_id)
        self.cron_edit.clear()
        self.log(f"scheduled {task_id} at '{cron}'")

    def _remove_job(self) -> None:
        rows = sorted({i.row() for i in self.jobs_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.scheduler.remove_job(row)

    def _on_job_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self.scheduler.set_enabled(item.row(), item.checkState() == Qt.CheckState.Checked)

    def _on_job_fired(self, job: Job, started: bool) -> None:
        note = "" if started else " (skipped, already running)"
        self.log(f"cron '{job.cron}' fired {job.task_id}{note}")

    def _refresh_jobs(self) -> None:
        table = self.jobs_table
        table.blockSignals(True)
        table.setRowCount(len(self.scheduler.jobs))
        for row, job in enumerate(self.scheduler.jobs):
            enabled = QTableWidgetItem()
            enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            enabled.setCheckState(Qt.CheckState.Checked if job.enabled else Qt.CheckState.Unchecked)
            nxt = self.scheduler.next_run(job)
            table.setItem(row, 0, enabled)
            table.setItem(row, 1, QTableWidgetItem(job.cron))
            table.setItem(row, 2, QTableWidgetItem(TASKS[job.task_id].name))
            table.setItem(row, 3, QTableWidgetItem(nxt.strftime("%Y-%m-%d %H:%M") if nxt else "—"))
        table.blockSignals(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.runner.shutdown()
        super().closeEvent(event)