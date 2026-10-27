from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from purgator.tasks import TASKS, PurgeTask, TaskResult, human_size
from purgator.ui.assets import ICONS_DIR
from purgator.ui.colors import BACKGROUND, STRIPE
from purgator.ui.components import (
    RowDelegate,
    ThinScrollBar,
    actions_row,
    page_layout,
    rounded_box,
    set_list_palette,
)
from purgator.ui.styles import PLAIN_BUTTON_STYLE, PRIMARY_BUTTON_STYLE, TREE_STYLE
from purgator.workers import TaskRunner

# Label of the per-category panel shown on the Cleanup page
CATEGORY_LABELS = {
    "user_cache": "User logs",
    "stale_files": "Stale temp files",
    "project_builds": "Project builds",
}

# Heights of the rows: the category header is a bit taller than the file rows
CATEGORY_HEIGHT = 36
FILE_HEIGHT = 28

# Icons in front of a scanned path: a directory or a single file
FOLDER_ICON_PATH = ICONS_DIR / "folder.svg"
FILE_ICON_PATH = ICONS_DIR / "file.svg"
KIND_ICON_SIZE = 16

# Width of the column with the check boxes
CHECK_COLUMN_WIDTH = 34

# Arrow in front of a category name: the dropdown is open or closed
ARROW_DOWN = "▾"
ARROW_RIGHT = "▸"


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
        self.setItemDelegate(RowDelegate(self))
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setExpandsOnDoubleClick(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        # The scroll bar always keeps its space, so opening a category never
        # shifts the rows sideways.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBar(ThinScrollBar(Qt.Orientation.Vertical, self))
        set_list_palette(self)
        self.setStyleSheet(TREE_STYLE)
        self.setIconSize(QSize(KIND_ICON_SIZE, KIND_ICON_SIZE))
        self._folder_icon = QIcon(str(FOLDER_ICON_PATH))
        self._file_icon = QIcon(str(FILE_ICON_PATH))
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
        self._paint(item, BACKGROUND)

    def _paint(self, item: QTreeWidgetItem, colour: str) -> None:
        brush = QColor(colour)
        item.setBackground(0, brush)
        item.setBackground(1, brush)
        item.setBackground(2, brush)

    def _paint_files(self, category: QTreeWidgetItem) -> None:
        """The files of a category alternate; the header stays plain."""
        for index in range(category.childCount()):
            colour = STRIPE if index % 2 else BACKGROUND
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
            icon = self._folder_icon if path in result.directories else self._file_icon
            size = human_size(result.sizes.get(path, 0))
            child = QTreeWidgetItem(item, [_display_path(path), size, ""])
            child.setIcon(0, icon)
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


class CleanupPage(QWidget):
    """Scans for files that can go and deletes the ticked ones."""

    logged = Signal(str)
    history_added = Signal(str, str, str)  # task, action, status

    def __init__(
        self,
        runner: TaskRunner,
        make_task: Callable[..., PurgeTask],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.runner = runner
        self.make_task = make_task
        self.results = _ResultTree()
        self._active_action: str | None = None  # "scan" / "cleanup" while a run is in flight
        self._cleanup_action_was: str | None = None  # the last button that was clicked
        self._starting = False  # True while _run_all_tasks is still queueing tasks
        self._found_bytes = 0  # size of the files the last run found
        self._found_files = 0  # number of those files
        self._found_categories = 0  # number of tasks that found something

        # "Cleanup" appears only in the top header, not as a page heading.
        layout = page_layout(self)
        layout.addLayout(self._build_actions())
        layout.addWidget(self._build_categories(), stretch=1)

        self.runner.task_started.connect(self._on_started)
        self.runner.task_finished.connect(self._on_finished)
        self.runner.task_failed.connect(self._on_failed)
        self.runner.task_cancelled.connect(self._on_cancelled)
        self.runner.running_changed.connect(self._on_running_changed)
        self._on_running_changed(0)

    def _build_categories(self) -> QWidget:
        container, column = rounded_box("categoryBox")
        for task_id, cls in TASKS.items():
            self.results.add_category(task_id, CATEGORY_LABELS.get(task_id, cls.name))
        column.addWidget(self.results, stretch=1)
        return container

    def _build_actions(self):
        self.info_label = QLabel("Nothing scanned yet")

        self.scan_button = QPushButton("Scan")
        self.scan_button.setStyleSheet(PLAIN_BUTTON_STYLE)
        self.scan_button.clicked.connect(lambda: self._on_action_clicked("scan"))

        self.cleanup_button = QPushButton("Clean up")
        self.cleanup_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.cleanup_button.clicked.connect(lambda: self._on_action_clicked("cleanup"))

        return actions_row(self.info_label, self.scan_button, self.cleanup_button)

    def _on_action_clicked(self, action: str) -> None:
        """The button shows 'Cancel' while it is the one running: cancel instead."""
        if self._active_action is not None:
            if self._active_action == action:
                self._cleanup_action_was = action
                self.runner.cancel_all()
            return
        self._cleanup_action_was = action
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

    def _task_name(self, task_id: str) -> str:
        return TASKS[task_id].name if task_id in TASKS else task_id

    def _on_started(self, task_id: str) -> None:
        self.logged.emit(f"{task_id}: started")

    def _on_finished(self, task_id: str, result: TaskResult) -> None:
        self._add_found(result)
        self.results.show_result(result)
        self.logged.emit(result.summary())
        action = self._cleanup_action_was or self._active_action
        found = f"{result.files} files · {human_size(result.bytes)}"
        if action == "scan":
            self.history_added.emit(f"Cleanup:{self._task_name(task_id)}:scan", found, "Successfull")
        elif action == "cleanup":
            self.history_added.emit(f"Cleanup:{self._task_name(task_id)}:remove", found, "Successfull")
        for path in result.paths[:20]:
            self.logged.emit(f"    {path}")
        if len(result.paths) > 20:
            self.logged.emit(f"    … and {len(result.paths) - 20} more")

    def _on_failed(self, task_id: str, error: str) -> None:
        self.logged.emit(f"{task_id}: FAILED\n{error}")
        action = self._cleanup_action_was or self._active_action
        task_name = self._task_name(task_id)
        if action == "scan":
            self.history_added.emit(f"Cleanup:{task_name}:scan", "-", "Failed")
        elif action == "cleanup":
            self.history_added.emit(f"Cleanup:{task_name}:remove", "-", "Failed")
        else:
            self.history_added.emit(task_name, "-", "Failed")

    def _on_cancelled(self, task_id: str) -> None:
        self.logged.emit(f"{task_id}: cancelled")
        action = self._cleanup_action_was
        task_name = self._task_name(task_id)
        if action == "scan":
            self.history_added.emit(f"Cleanup:{task_name}:scan", "-", "Canceled")
        elif action == "cleanup":
            self.history_added.emit(f"Cleanup:{task_name}:remove", "-", "Canceled")
        else:
            self.history_added.emit(task_name, "-", "Canceled")

    def _on_running_changed(self, count: int) -> None:
        busy = count > 0
        if not busy and not self._starting:
            self._active_action = None  # run is over: the buttons get their labels back
        # The button that started the run turns into "Cancel"; the other one stays disabled.
        self.scan_button.setText("Cancel" if self._active_action == "scan" else "Scan")
        self.cleanup_button.setText("Cancel" if self._active_action == "cleanup" else "Clean up")
        running = busy or self._starting
        self.scan_button.setEnabled(not running or self._active_action == "scan")
        self.cleanup_button.setEnabled(not running or self._active_action == "cleanup")
