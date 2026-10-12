from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTime, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Purgator")
        self.resize(820, 640)

        self.settings = QSettings()
        self.runner = TaskRunner(self)
        self.scheduler = CronScheduler(self.runner, self.make_task, self.settings, self)

        self.buttons: dict[str, QPushButton] = {}
        self.bars: dict[str, QProgressBar] = {}

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._build_tasks_box())
        layout.addWidget(self._build_log_box(), stretch=1)
        layout.addWidget(self._build_schedule_box())
        self.setCentralWidget(central)

        self.running_label = QLabel()
        self.clock_label = QLabel()
        self.statusBar().addWidget(self.running_label)
        self.statusBar().addPermanentWidget(self.clock_label)
        # Ticking clock: a visible proof that the GUI thread is never blocked
        self._clock = QTimer(self, interval=500, timeout=self._update_clock)
        self._clock.start()
        self._update_clock()
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

    def _build_log_box(self) -> QGroupBox:
        box = QGroupBox("Log")
        layout = QVBoxLayout(box)
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view)
        return box

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

    def _update_clock(self) -> None:
        self.clock_label.setText(QTime.currentTime().toString("HH:mm:ss"))

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

