from __future__ import annotations

import json
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from purgator.scheduler import CronScheduler
from purgator.tasks import BUILTIN_TASKS, TASKS, PurgeTask, create_task
from purgator.tasks.builtin import make_custom_path_task
from purgator.ui.assets import ICONS_DIR, themed_icon
from purgator.ui.colors import ACCENT, BACKGROUND, BORDER, TEXT
from purgator.ui.pages import (
    ApplicationsPage,
    CleanupPage,
    HistoryPage,
    OverviewPage,
    SchedulePage,
    SettingsPage,
    WhitelistPage,
)
from purgator.ui import theme
from purgator.workers import TaskRunner

CUSTOM_TASK_PREFIX = "custom_"
CUSTOM_TASKS_KEY = "whitelist/custom_tasks"
REMOVED_TASKS_KEY = "whitelist/removed_tasks"


def scan_root_key(task_id: str) -> str:
    return f"tasks/{task_id}/root"


NAV_ITEMS = [
    ("overview", "Overview"),
    ("cleanup", "Cleanup"),
    ("applications", "Applications"),
    ("schedule", "Schedule"),
    ("history", "History"),
    ("whitelist", "Whitelist"),
    ("settings", "Settings"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Purgator")
        self.resize(1100, 720)

        self.settings = QSettings()
        self._load_custom_tasks()
        self._load_removed_tasks()
        self.runner = TaskRunner(self)
        self.scheduler = CronScheduler(self.runner, self.make_task, self.settings, self)

        central = QWidget()
        central.setStyleSheet(f"background-color: {BACKGROUND}; color: {TEXT};")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(self._build_header())

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.addWidget(self._build_nav())

        self.history = HistoryPage()
        self.overview = OverviewPage(self.runner.pool, self.scheduler)
        self.cleanup = CleanupPage(self.runner, self.make_task)
        self.cleanup.run_finished.connect(self.overview.record_run)
        self.applications = ApplicationsPage(self.runner.pool)
        self.schedule = SchedulePage(self.scheduler)
        self.whitelist = WhitelistPage(self._scan_roots())
        self.whitelist.path_changed.connect(self._set_scan_root)
        self.whitelist.task_added.connect(self._add_custom_task)
        self.whitelist.task_removed.connect(self._remove_task)
        self.settings_page = SettingsPage(self.settings)
        self.settings_page.theme_changed.connect(self._change_theme)
        self.settings_page.task_paths_reset.connect(self._reset_task_paths)
        for page in (self.cleanup, self.applications, self.schedule):
            page.logged.connect(self.history.log)
        for page in (self.cleanup, self.applications):
            page.history_added.connect(self.history.add_entry)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.overview)
        self.stack.addWidget(self.cleanup)
        self.stack.addWidget(self.applications)
        self.stack.addWidget(self.schedule)
        self.stack.addWidget(self.history)
        self.stack.addWidget(self.whitelist)
        self.stack.addWidget(self.settings_page)
        content.addWidget(self.stack, stretch=1)

        layout.addLayout(content, stretch=1)
        self.setCentralWidget(central)

        self.stack.currentChanged.connect(self._on_page_changed)
        self._on_page_changed(self.stack.currentIndex())

        self.running_label = QLabel()
        self.statusBar().addWidget(self.running_label)
        self._on_running_changed(0)
        self.runner.running_changed.connect(self._on_running_changed)

    def _build_header(self) -> QHBoxLayout:
        self.header_left = QLabel()
        self.header_left.setFixedWidth(210)
        self.header_left.setStyleSheet(
            f"font-size: 24px; font-weight: 600; padding: 5px 12px 5px 12px; border: 1px solid {BORDER}; border-left: none; border-top: none; border-right: 1px solid {BORDER};"
        )
        logo = themed_icon(ICONS_DIR / "purgator-logo.svg", TEXT)
        self.header_right = QLabel("Overview")
        self.header_right.setStyleSheet(
            f"font-size: 24px; font-weight: 600; padding: 12px 12px 12px 12px; border: 1px solid {BORDER}; border-top: none; border-right: none; border-left: none;"
        )
        if not logo.isNull():
            inner_h = self.header_right.sizeHint().height() - 10
            logo_pixmap = logo.pixmap(512, 512)
            self.header_left.setPixmap(
                logo_pixmap.scaledToHeight(
                    inner_h, Qt.TransformationMode.SmoothTransformation
                )
            )
        else:
            self.header_left.setText("Purgator")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)
        header.addWidget(self.header_left)
        header.addWidget(self.header_right, stretch=1)
        return header

    def _build_nav(self) -> QListWidget:
        nav = QListWidget()
        nav.setFixedWidth(210)
        nav.setStyleSheet(
            f"QListWidget {{ background: {BACKGROUND}; border: 1px solid {BORDER}; border-top: none; border-left: none; border-bottom: none; font-size: 17px; outline: none; padding-top: 10px; }}"
            "QListWidget::item { padding: 8px 12px; border: none; }"
            f"QListWidget::item:selected {{ background: {BACKGROUND}; color: {ACCENT}; border: none; }}"
            f"QListWidget::item:hover {{ color: {ACCENT}; }}"
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

    def _on_running_changed(self, count: int) -> None:
        bar = self.statusBar()
        if count:
            self.running_label.setText(f"{count} task(s) running")
            bar.show()
        else:
            self.running_label.clear()
            bar.hide()

    def make_task(self, task_id: str, dry_run: bool = False) -> PurgeTask:
        root = self.settings.value(scan_root_key(task_id))
        if root:
            return create_task(task_id, dry_run=dry_run, root=Path(root))
        return create_task(task_id, dry_run=dry_run)

    def _scan_roots(self) -> list[tuple[str, str, Path]]:
        roots = []
        for task_id, task_cls in TASKS.items():
            task = self.make_task(task_id)
            root = getattr(task, "root", None)
            if root is not None:
                roots.append((task_id, task_cls.name, Path(root)))
        return roots

    def _set_scan_root(self, task_id: str, root: str) -> None:
        self.settings.setValue(scan_root_key(task_id), root)
        self.settings.sync()

    def _reset_task_paths(self) -> None:
        for task_id in list(self._removed_tasks):
            TASKS[task_id] = BUILTIN_TASKS[task_id]
            self.cleanup.add_task_category(task_id, BUILTIN_TASKS[task_id].name)
        self._removed_tasks.clear()
        self._save_removed_tasks()
        for task_id in TASKS:
            if task_id.startswith(CUSTOM_TASK_PREFIX):
                continue
            self.settings.remove(scan_root_key(task_id))
        self.settings.sync()
        self.whitelist.set_roots(self._scan_roots())

    def _remove_task(self, task_id: str) -> None:
        if task_id.startswith(CUSTOM_TASK_PREFIX):
            TASKS.pop(task_id, None)
            self._custom_tasks = [
                task for task in self._custom_tasks if task.get("id") != task_id
            ]
            self._save_custom_tasks()
        elif task_id in BUILTIN_TASKS:
            TASKS.pop(task_id, None)
            self._removed_tasks.add(task_id)
            self._save_removed_tasks()
        else:
            return
        self.settings.remove(scan_root_key(task_id))
        self.settings.sync()
        self.cleanup.remove_task_category(task_id)
        self.scheduler.remove_task_jobs(task_id)

    def _load_custom_tasks(self) -> None:
        for task_id in [tid for tid in TASKS if tid.startswith(CUSTOM_TASK_PREFIX)]:
            del TASKS[task_id]
        try:
            items = json.loads(self.settings.value(CUSTOM_TASKS_KEY, "[]"))
        except (TypeError, ValueError):
            items = []
        self._custom_tasks: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            task_id = item.get("id")
            name = item.get("name")
            if not isinstance(task_id, str) or not task_id.startswith(CUSTOM_TASK_PREFIX):
                continue
            if not isinstance(name, str) or not name.strip() or task_id in TASKS:
                continue
            TASKS[task_id] = make_custom_path_task(task_id, name)
            self._custom_tasks.append({"id": task_id, "name": name})

    def _save_custom_tasks(self) -> None:
        self.settings.setValue(CUSTOM_TASKS_KEY, json.dumps(self._custom_tasks))
        self.settings.sync()

    def _load_removed_tasks(self) -> None:
        try:
            items = json.loads(self.settings.value(REMOVED_TASKS_KEY, "[]"))
        except (TypeError, ValueError):
            items = []
        self._removed_tasks: set[str] = set()
        if not isinstance(items, list):
            return
        for task_id in items:
            if isinstance(task_id, str) and task_id in BUILTIN_TASKS:
                self._removed_tasks.add(task_id)
                TASKS.pop(task_id, None)

    def _save_removed_tasks(self) -> None:
        removed = sorted(self._removed_tasks)
        self.settings.setValue(REMOVED_TASKS_KEY, json.dumps(removed))
        self.settings.sync()

    def _add_custom_task(self, name: str, path: str) -> None:
        task_id = f"{CUSTOM_TASK_PREFIX}{uuid.uuid4().hex[:8]}"
        while task_id in TASKS:
            task_id = f"{CUSTOM_TASK_PREFIX}{uuid.uuid4().hex[:8]}"
        TASKS[task_id] = make_custom_path_task(task_id, name)
        self.settings.setValue(scan_root_key(task_id), path)
        self._custom_tasks.append({"id": task_id, "name": name})
        self._save_custom_tasks()
        self.cleanup.add_task_category(task_id, name)
        self.whitelist.add_root(task_id, name, Path(path))

    def log(self, message: str) -> None:
        self.history.log(message)

    def _change_theme(self, name: str) -> None:
        """Reload the pages and build the window again with the new colours."""
        geometry = self.geometry()
        page = self.stack.currentIndex()
        maximized = self.isMaximized()

        theme.apply(name)
        theme.reload_ui()

        from purgator.ui import MainWindow as FreshMainWindow

        window = FreshMainWindow()
        window.setGeometry(geometry)
        app = QApplication.instance()
        if app is not None:
            app._theme_window = window  # keep the new window alive
        if maximized:
            window.showMaximized()
        else:
            window.show()
        if 0 <= page < window.nav.count():
            window.nav.setCurrentRow(page)

        self.close()
        self.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.overview.shutdown()
        self.runner.shutdown()
        super().closeEvent(event)
