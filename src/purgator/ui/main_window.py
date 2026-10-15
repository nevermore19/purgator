from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QRectF, QSettings, Qt, QTime
from PySide6.QtGui import QCloseEvent, QColor, QPainter, QPen, QPixmap
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
    ("schedule", "Schedule"),
    ("history", "History"),
    ("whitelist", "Whitelist"),
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
        available = QLabel(f"{usage.free / (1024**3):.0f} GB available")
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
            f"<tr><td align='center'><span style='font-size: 16px;'>{used_gb:.0f} GB / {total_gb:.0f} GB</span></td></tr>"
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

        lbl = QLabel(f"<span style='font-size:16px;color:black;'>{home_used/(1024**3):.0f} GB</span>")
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