from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThreadPool, Signal
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

from purgator.apps import Application, discover_applications, remove_application
from purgator.tasks import Cancelled, human_size
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
from purgator.usage import describe as describe_usage
from purgator.usage import describe_exact, is_old
from purgator.workers import Worker

ROW_HEIGHT = 28

# Icon of an application whose own icon cannot be found
APPLICATION_ICON_PATH = ICONS_DIR / "application.svg"
APP_ICON_SIZE = 20

# The old place of the application icons, outside the icon theme
PIXMAPS_DIR = Path("/usr/share/pixmaps")
PIXMAP_SUFFIXES = (".svg", ".png", ".xpm")

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


def _find_icon(name: str) -> QIcon | None:
    """Look an icon up by its path, in the icon theme or among the pixmaps."""
    if not name:
        return None
    if name.startswith("/"):
        return QIcon(name) if Path(name).is_file() else None
    stem = name.removesuffix(Path(name).suffix) if name.endswith(PIXMAP_SUFFIXES) else name
    icon = QIcon.fromTheme(stem)
    if not icon.isNull():
        return icon
    for suffix in PIXMAP_SUFFIXES:
        path = PIXMAPS_DIR / f"{stem}{suffix}"
        if path.is_file():
            return QIcon(str(path))
    return None


def _usage_tip(app: Application) -> str:
    """Say where the moment of the last use comes from."""
    if app.last_used <= 0:
        return "never used, as far as the system knows"
    source = app.used_from or "the last time it was used"
    return f"{source}, on {describe_exact(app.last_used)}"


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
        self.setItemDelegate(RowDelegate(self))
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBar(ThinScrollBar(Qt.Orientation.Vertical, self))
        self.setIconSize(QSize(APP_ICON_SIZE, APP_ICON_SIZE))
        self._fallback_icon = QIcon(str(APPLICATION_ICON_PATH))
        self._icons: dict[str, QIcon] = {}  # one lookup per icon name
        # the rows are sorted by hand: the order depends on the moment of the
        # last use, not on the words of the column
        self._sort_column = LAST_USED_COLUMN
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.header().sectionClicked.connect(self._sort_by_column)
        self.header().setSortIndicator(LAST_USED_COLUMN, Qt.SortOrder.AscendingOrder)
        set_list_palette(self)
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
                item.setIcon(NAME_COLUMN, self._icon_of(app))
                item.setCheckState(CHECK_COLUMN, Qt.CheckState.Unchecked)
                item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setSizeHint(0, QSize(0, ROW_HEIGHT))
                if app.summary:
                    item.setToolTip(0, app.summary)
                item.setToolTip(LAST_USED_COLUMN, _usage_tip(app))
            self._paint_rows()
        finally:
            self.blockSignals(False)
            self.setUpdatesEnabled(True)

    def _icon_of(self, app: Application) -> QIcon:
        """The icon of an application, or the generic one when it has none."""
        if app.icon not in self._icons:
            self._icons[app.icon] = _find_icon(app.icon) or self._fallback_icon
        return self._icons[app.icon]

    def _paint_rows(self) -> None:
        """Give the rows their stripes; they follow the place of the row."""
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            colour = QColor(STRIPE if index % 2 else BACKGROUND)
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


class ApplicationsPage(QWidget):
    """Lists the installed applications and uninstalls the ticked ones."""

    logged = Signal(str)
    history_added = Signal(str, str, str)  # task, action, status

    def __init__(self, pool: QThreadPool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pool = pool
        self.app_list = _ApplicationList()
        self._apps_worker: Worker | None = None  # the worker that looks for the apps
        self._apps_workers: list[Worker] = []  # they are kept alive until the app ends
        self._apps_action: str | None = None  # "scan" / "remove" while a run is in flight
        self._apps_action_was: str | None = None  # the last button that started a run
        self._apps_scanned = False  # True when the applications were looked for

        # "Applications" appears only in the top header, not as a page heading.
        layout = page_layout(self)
        layout.addLayout(self._build_actions())
        layout.addWidget(self._build_box(), stretch=1)

    def _build_box(self) -> QWidget:
        container, column = rounded_box("applicationBox")
        self.app_list.itemChanged.connect(self._update_apps_info)
        column.addWidget(self.app_list, stretch=1)
        return container

    def _build_actions(self):
        self.apps_info_label = QLabel("Nothing scanned yet")

        self.apps_scan_button = QPushButton("Scan")
        self.apps_scan_button.setStyleSheet(PLAIN_BUTTON_STYLE)
        self.apps_scan_button.clicked.connect(self._on_apps_scan_clicked)

        self.apps_remove_button = QPushButton("Remove")
        self.apps_remove_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.apps_remove_button.clicked.connect(self._on_apps_remove_clicked)

        return actions_row(self.apps_info_label, self.apps_scan_button, self.apps_remove_button)

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

    def _start_worker(self, worker: Worker, on_finished) -> None:
        self._apps_worker = worker
        self._apps_workers.append(worker)  # the pool does not delete them
        worker.signals.finished.connect(on_finished)
        worker.signals.failed.connect(self._on_apps_failed)
        worker.signals.cancelled.connect(self._on_apps_cancelled)
        worker.signals.progress.connect(self._on_apps_progress)
        self.pool.start(worker)
        self._update_apps_buttons()

    def _scan_applications(self) -> None:
        """Look for the installed applications, without freezing the window."""
        self._apps_action = "scan"
        self.apps_info_label.setText("Looking for applications…")
        self._start_worker(Worker(_ApplicationsScan()), self._on_apps_found)

    def _on_apps_found(self, _task_id: str, apps: list[Application]) -> None:
        self._apps_action = None
        self._apps_scanned = True
        self._apps_worker = None
        self.app_list.set_applications(apps)
        self._update_apps_buttons()
        self._update_apps_info()
        self.logged.emit(f"applications: {len(apps)} found")
        self.history_added.emit("Applications:scan", f"{len(apps)} found", "Successfull")

    def _on_apps_failed(self, _task_id: str, error: str) -> None:
        self._apps_action = None
        self._apps_worker = None
        self._update_apps_buttons()
        self.apps_info_label.setText("Looking for the applications failed")
        self.logged.emit(f"applications: FAILED\n{error}")
        self.history_added.emit("Applications:scan", "-", "Failed")

    def _on_apps_cancelled(self, _task_id: str) -> None:
        self._apps_action = None
        self._apps_worker = None
        self._update_apps_buttons()
        self.apps_info_label.setText("Looking for the applications was cancelled")
        self.logged.emit("applications: cancelled")
        if self._apps_action_was == "remove":
            self.history_added.emit("Applications:remove", "-", "Canceled")
        else:
            self.history_added.emit("Applications:scan", "-", "Canceled")

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
        self._start_worker(Worker(_ApplicationsRemoval(apps)), self._on_apps_removed)

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
            self.logged.emit(f"remove {app.source}: {app.package} → {'done' if ok else 'failed'}")
            if message and not ok:
                self.logged.emit(f"    {message}")
        if failed:
            self.history_added.emit(
                "Applications:remove", f"{len(removed)} removed, {len(failed)} failed", "Failed"
            )
        else:
            self.history_added.emit("Applications:remove", f"{len(removed)} removed", "Successfull")
