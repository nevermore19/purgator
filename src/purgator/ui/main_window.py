from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
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
from purgator.tasks import PurgeTask, create_task
from purgator.tasks.builtin import ProjectBuildsTask
from purgator.ui.assets import ICONS_DIR
from purgator.ui.colors import ACCENT, BACKGROUND, BORDER, TEXT
from purgator.ui.pages import (
    ApplicationsPage,
    CleanupPage,
    HistoryPage,
    OverviewPage,
    PlaceholderPage,
    SchedulePage,
)
from purgator.workers import TaskRunner

BUILDS_ROOT_KEY = "tasks/project_builds/root"

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
        self.overview = OverviewPage(self.runner.pool)
        self.cleanup = CleanupPage(self.runner, self.make_task)
        self.applications = ApplicationsPage(self.runner.pool)
        self.schedule = SchedulePage(self.scheduler)
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
        self.stack.addWidget(PlaceholderPage("Whitelist"))
        self.stack.addWidget(PlaceholderPage("Settings"))
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
        logo = QPixmap(str(ICONS_DIR / "purgator-logo.svg"))
        self.header_right = QLabel("Overview")
        self.header_right.setStyleSheet(
            f"font-size: 24px; font-weight: 600; padding: 12px 12px 12px 12px; border: 1px solid {BORDER}; border-top: none; border-right: none; border-left: none;"
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
        self.running_label.setText(f"{count} task(s) running" if count else "Idle")

    def make_task(self, task_id: str, dry_run: bool = False) -> PurgeTask:
        if task_id == ProjectBuildsTask.id:
            root = self.settings.value(BUILDS_ROOT_KEY, str(Path.home()))
            return create_task(task_id, dry_run=dry_run, root=Path(root))
        return create_task(task_id, dry_run=dry_run)

    def log(self, message: str) -> None:
        self.history.log(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.overview.shutdown()
        self.runner.shutdown()
        super().closeEvent(event)
