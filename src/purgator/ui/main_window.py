from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCharts import (
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import QMargins, QSettings, Qt, QTime
from PySide6.QtGui import QBrush, QCloseEvent, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from purgator.scheduler import CronScheduler, Job
from purgator.tasks import TASKS, PurgeTask, TaskResult, create_task
from purgator.tasks.builtin import ProjectBuildsTask
from purgator.workers import TaskRunner

BUILDS_ROOT_KEY = "tasks/project_builds/root"

NAV_ITEMS = [
    ("overview", "Overview"),
    ("cleanup", "Cleanup"),
    ("applications", "Applications"),
    ("system_maintenance", "System Maintenance"),
    ("schedule", "Schedule"),
    ("history", "History"),
    ("settings", "Settings"),
]


def _page_widget(title: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    heading = QLabel(title)
    heading.setStyleSheet(
        "font-size: 22px; font-weight: 600; color: black; padding: 4px 0 12px 4px;"
    )
    layout.addWidget(heading)
    return page, layout


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Purgator")
        self.resize(960, 680)

        self.settings = QSettings()
        self.runner = TaskRunner(self)
        self.scheduler = CronScheduler(self.runner, self.make_task, self.settings, self)

        self.buttons: dict[str, QPushButton] = {}
        self.bars: dict[str, QProgressBar] = {}

        central = QWidget()
        central.setStyleSheet("background-color: #F7EEE2; color: black;")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header_left = QLabel("Purgator")
        self.header_left.setFixedWidth(190)
        self.header_left.setStyleSheet(
            "font-size: 24px; font-weight: 600; padding: 12px 12px 12px 12px; border: 1px solid #CCCCCC; border-left: none; border-top: none; border-right: 1px solid #CCCCCC;"
        )
        self.header_right = QLabel("Overview")
        self.header_right.setStyleSheet(
            "font-size: 24px; font-weight: 600; padding: 12px 12px 12px 12px; border: 1px solid #CCCCCC; border-top: none; border-right: none; border-left: none;"
        )
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
        self.stack.addWidget(self._build_placeholder_page("System Maintenance"))
        self.stack.addWidget(self._build_schedule_page())
        self.stack.addWidget(self._build_placeholder_page("History"))
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
        nav.setFixedWidth(190)
        nav.setStyleSheet(
            "QListWidget { background: #F7EEE2; border: 1px solid #CCCCCC; border-top: none; border-left: none; border-bottom: none; font-size: 14px; outline: none; }"
            "QListWidget::item { padding: 10px 12px; border: none; }"
            "QListWidget::item:selected { background: #F7EEE2; color: #4E4242; border: none; }"
            "QListWidget::item:hover { color: #7D6D6B; }"
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

        box = QGroupBox()
        box.setFixedWidth(400)
        box.setStyleSheet(
            "QGroupBox { background-color: #F7EEE2; border: 1px solid #CCCCCC; }"
        )
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(10, 10, 10, 4)
        box_layout.setSpacing(8)
        box_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("Disk usage")
        title.setStyleSheet("font-size: 20px; font-weight: 600; color: black;")
        box_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignLeft)
        view = self._build_disk_usage_chart(usage)
        available = QLabel(f"{usage.free / (1024**3):.0f} GB available", view)
        available.setAlignment(Qt.AlignmentFlag.AlignCenter)
        available.setStyleSheet("font-size: 15px; color: black; background: transparent;")
        available.setGeometry(0, int(view.height() * 0.66), view.width(), 22)
        available.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box_layout.addWidget(view)
        bar_view = self._build_home_to_disk_bar(home_usage, usage)
        box_layout.addWidget(bar_view)
        layout.addWidget(box)
        layout.addStretch()
        return page

    def _build_disk_usage_chart(self, usage) -> QChartView:
        used_gb = usage.used / (1024**3)
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        used_pct = usage.used / usage.total * 100 if usage.total else 0

        series = QPieSeries()
        series.setHoleSize(0.6)
        used_slice = series.append("Used", usage.used)
        free_slice = series.append("Free", usage.free)
        used_slice.setColor(QColor("#7D6D6B"))
        free_slice.setColor(QColor("#D8C9B8"))
        used_slice.setPen(QPen(Qt.PenStyle.NoPen))
        free_slice.setPen(QPen(Qt.PenStyle.NoPen))
        # series.setPen not available on QPieSeries in PySide6; set on slices instead

        top_margin = -122
        chart = QChart()
        chart.addSeries(series)
        chart.setBackgroundBrush(QBrush(QColor("#F7EEE2")))
        chart.setBackgroundRoundness(0)
        chart.setMargins(QMargins(0, top_margin, 0, 0))
        chart.legend().setVisible(False)
        # chart.setPen not available on QChart in PySide6; try theme/outline via style instead

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setFixedSize(360, 360)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setLineWidth(0)

        center = QLabel(
            "<div style='text-align: center;'>"
            f"<span style='font-size: 40px; font-weight: 700;'>{used_pct:.0f}%</span>"
            "<br>"
            "<span style='font-size: 13px; color: black;'>used</span>"
            "<br>"
            f"<span style='font-size: 20px; font-weight: 600;'>{used_gb:.0f} GB / {total_gb:.0f} GB</span>"
            "</div>",
            view,
        )
        center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.setStyleSheet("color: black; background: transparent;")
        center.setGeometry(0, int(top_margin / 2), view.width(), view.height())
        center.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return view

    def _build_home_to_disk_bar(self, home_usage, disk_usage) -> QChartView:
        disk_total = disk_usage.total
        disk_used = disk_usage.used
        home_used = home_usage.used

        set_home = QBarSet("/home")
        set_other = QBarSet("Other")

        set_home.setColor(QColor("#7D6D6B"))
        set_other.setColor(QColor("#B9B0A8"))

        for s in (set_home, set_other):
            s.setPen(QPen(Qt.PenStyle.NoPen))

        occupied = disk_used
        if occupied < 0:
            occupied = 0
        other = occupied - home_used
        if other < 0:
            other = 0
        if occupied == 0:
            occupied = 1

        set_home << (home_used * 100.0 / occupied)
        set_other << (other * 100.0 / occupied)

        series = QBarSeries()
        series.append(set_home)
        series.append(set_other)
        series.setBarWidth(1.2)

        chart = QChart()
        chart.addSeries(series)
        chart.setBackgroundBrush(QBrush(QColor("#F7EEE2")))
        chart.setBackgroundRoundness(0)
        chart.setMargins(QMargins(0, 0, 0, 0))
        chart.legend().setVisible(False)

        axis_y = QValueAxis()
        axis_y.setRange(0, 100)
        axis_y.setLabelsVisible(False)
        axis_y.setGridLineVisible(False)
        axis_y.setLineVisible(False)
        axis_y.setTitleVisible(False)

        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setFixedHeight(50)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setLineWidth(0)

        home_pct = home_used * 100.0 / occupied
        other_pct = other * 100.0 / occupied
        lbl = QLabel(
            f"<span style='font-size:11px;color:black;'>/home {home_used/(1024**3):.0f}GB ({home_pct:.0f}%) | other {other/(1024**3):.0f}GB ({other_pct:.0f}%) of occupied {occupied/(1024**3):.0f}GB</span>",
            view,
        )
        lbl.setStyleSheet("background: transparent;")
        lbl.setGeometry(8, 0, view.width() - 16, 20)

        return view

    def _build_placeholder_page(self, title: str) -> QWidget:
        page, layout = _page_widget(title)
        hint = QLabel("Nothing here yet.")
        hint.setStyleSheet("color: black; padding-left: 4px;")
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def _build_cleanup_page(self) -> QWidget:
        page, layout = _page_widget("Cleanup")
        layout.addWidget(self._build_tasks_box())
        layout.addStretch()
        return page

    def _build_tasks_box(self) -> QGroupBox:
        box = QGroupBox("Tasks")
        grid = QGridLayout(box)
        for row, (task_id, cls) in enumerate(TASKS.items()):
            button = QPushButton(cls.name)
            button.clicked.connect(lambda _=False, t=task_id: self.start_task(t))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("idle")
            grid.addWidget(button, row, 0)
            grid.addWidget(bar, row, 1)
            self.buttons[task_id] = button
            self.bars[task_id] = bar
        grid.setColumnStretch(1, 1)

        controls = QHBoxLayout()
        self.dry_run = QCheckBox("Dry run (only report, don't delete)")
        self.dry_run.setChecked(True)
        cancel = QPushButton("Cancel all")
        cancel.clicked.connect(self.runner.cancel_all)
        controls.addWidget(self.dry_run)
        controls.addStretch()
        controls.addWidget(cancel)
        grid.addLayout(controls, len(TASKS), 0, 1, 2)
        return box

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

    def make_task(self, task_id: str) -> PurgeTask:
        dry = self.dry_run.isChecked()
        if task_id == ProjectBuildsTask.id:
            root = self.settings.value(BUILDS_ROOT_KEY, str(Path.home()))
            return create_task(task_id, dry_run=dry, root=Path(root))
        return create_task(task_id, dry_run=dry)

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
        if not self.dry_run.isChecked():
            answer = QMessageBox.warning(
                self,
                "Delete files?",
                f"“{TASKS[task_id].name}” will permanently delete files. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.runner.run(self.make_task(task_id))

    def log(self, message: str) -> None:
        stamp = QTime.currentTime().toString("HH:mm:ss")
        self.log_view.appendPlainText(f"[{stamp}] {message}")

    def _set_idle(self, task_id: str, text: str) -> None:
        bar = self.bars[task_id]
        bar.setRange(0, 100)
        bar.setFormat(text)
        self.buttons[task_id].setText(TASKS[task_id].name)

    def _on_started(self, task_id: str) -> None:
        bar = self.bars[task_id]
        bar.setRange(0, 0)  # busy indicator until first percentage arrives
        self.buttons[task_id].setText(f"Cancel: {TASKS[task_id].name}")
        self.log(f"{task_id}: started")

    def _on_progress(self, task_id: str, percent: int, message: str) -> None:
        bar = self.bars[task_id]
        if percent < 0:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(percent)
            bar.setFormat("%p%")
        bar.setToolTip(message)

    def _on_finished(self, task_id: str, result: TaskResult) -> None:
        self.bars[task_id].setValue(100)
        self._set_idle(task_id, "done")
        self.log(result.summary())
        for path in result.paths[:20]:
            self.log(f"    {path}")
        if len(result.paths) > 20:
            self.log(f"    … and {len(result.paths) - 20} more")

    def _on_failed(self, task_id: str, error: str) -> None:
        self._set_idle(task_id, "failed")
        self.log(f"{task_id}: FAILED\n{error}")

    def _on_cancelled(self, task_id: str) -> None:
        self.bars[task_id].setValue(0)
        self._set_idle(task_id, "cancelled")
        self.log(f"{task_id}: cancelled")

    def _on_running_changed(self, count: int) -> None:
        self.running_label.setText(f"{count} task(s) running" if count else "Idle")

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