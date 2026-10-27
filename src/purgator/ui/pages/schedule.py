from datetime import datetime

from PySide6.QtCore import QDate, Qt, QTime, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from purgator.scheduler import CronScheduler, Job
from purgator.tasks import TASKS
from purgator.ui.colors import (
    ACCENT,
    BACKGROUND,
    BORDER,
    HINT,
    HOVER,
    REMOVE_HOVER,
    STRIPE,
    TEXT,
    TEXT_ON_ACCENT,
)
from purgator.ui.components import Switch, actions_row, page_layout, rounded_box, set_list_palette
from purgator.ui.styles import PLAIN_BUTTON_STYLE, PRIMARY_BUTTON_STYLE

LINE_EDIT_STYLE = f"QLineEdit {{ background-color: {BACKGROUND}; color: {TEXT}; border: none; }}"


class _NewTaskDialog(QDialog):
    """Asks how a new scheduled run looks: which task, and when."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New task")
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {BACKGROUND}; color: {TEXT}; }}"
            f"QLabel {{ font-size: 17px; color: {TEXT}; background: transparent; }}"
            f"QComboBox {{ background-color: {BACKGROUND}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 4px; padding: 2px 6px; }}"
            "QComboBox::drop-down { border: none; background: transparent; width: 24px; }"
            f"QComboBox QAbstractItemView {{ background-color: {BACKGROUND}; selection-background-color: {ACCENT}; selection-color: {TEXT_ON_ACCENT}; color: {TEXT}; }}"
            f"QComboBox QAbstractItemView::item {{ color: {TEXT}; }}"
            f"QComboBox QAbstractItemView::item:hover {{ background-color: {STRIPE}; color: {TEXT}; }}"
            f"QDateEdit, QTimeEdit, QSpinBox {{ background-color: {BACKGROUND}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 4px; padding: 2px 6px; }}"
            f"QDateEdit QLineEdit, QTimeEdit QLineEdit, QSpinBox QLineEdit {{ background-color: {BACKGROUND}; color: {TEXT}; border: none; padding: 0px; selection-background-color: {ACCENT}; selection-color: {TEXT_ON_ACCENT}; }}"
            f"QComboBox QLineEdit {{ background-color: {BACKGROUND}; color: {TEXT}; border: none; }}"
            "QDateEdit::calendar-button, QTimeEdit::calendar-button"
            " { border: none; background: transparent; border-top-right-radius: 3px; border-bottom-right-radius: 3px; }"
            f"QDateEdit::calendar-button:hover, QTimeEdit::calendar-button:hover {{ background-color: {HOVER}; }}"
            "QSpinBox::up-button, QSpinBox::down-button { border: none; background: transparent; }"
            f"QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background-color: {HOVER}; }}"
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
            le.setStyleSheet(LINE_EDIT_STYLE)
            le.setPalette(le.palette())

        self.every_spin = QSpinBox()
        self.every_spin.setRange(1, 999)
        self.every_spin.setValue(1)
        if self.every_spin.lineEdit():
            le = self.every_spin.lineEdit()
            le.setReadOnly(False)
            le.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            le.setStyleSheet(LINE_EDIT_STYLE)
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
            le.setStyleSheet(LINE_EDIT_STYLE)
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
                self._set_input_palette(input_widget)
                if hasattr(input_widget, 'lineEdit') and input_widget.lineEdit() is not None:
                    le = input_widget.lineEdit()
                    le.setAutoFillBackground(True)
                    le.setStyleSheet(LINE_EDIT_STYLE)
                    self._set_input_palette(le)
            except Exception:
                pass

        for combo in (self.task_combo, self.unit_combo):
            if view := combo.view():
                view_palette = view.palette()
                view_palette.setColor(QPalette.ColorRole.Base, QColor(BACKGROUND))
                view_palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
                view_palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
                view_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT_ON_ACCENT))
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
        hint.setStyleSheet(f"font-size: 14px; color: {HINT}; background: transparent;")
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

    @staticmethod
    def _set_input_palette(widget: QWidget) -> None:
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(BACKGROUND))
        palette.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND))
        palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT_ON_ACCENT))
        widget.setPalette(palette)

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


class SchedulePage(QWidget):
    """The scheduled runs: turn them on and off, add and remove them."""

    logged = Signal(str)

    def __init__(self, scheduler: CronScheduler, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scheduler = scheduler

        # "Schedule" appears only in the top header, not as a page heading.
        layout = page_layout(self)
        layout.addLayout(self._build_actions())
        layout.addWidget(self._build_box(), stretch=1)

        self.scheduler.jobs_changed.connect(self._refresh_jobs)
        self.scheduler.job_fired.connect(self._on_job_fired)
        self._refresh_jobs()

    def _build_actions(self):
        self.schedule_info_label = QLabel("0 tasks · 0 active · 0 inactive")
        self.new_task_button = QPushButton("New Task")
        self.new_task_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.new_task_button.clicked.connect(self._new_task)
        return actions_row(self.schedule_info_label, self.new_task_button)

    def _build_box(self) -> QWidget:
        container, column = rounded_box("scheduleBox")

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

        set_list_palette(self.jobs_table)
        self.jobs_table.setStyleSheet(
            f"QTableWidget {{ background: {BACKGROUND}; border: none; outline: none; }}"
            f"QTableWidget::item {{ background: {BACKGROUND}; color: {TEXT}; }}"
            f"QTableWidget::item:selected {{ background: {BACKGROUND}; color: {TEXT}; }}"
            f"QHeaderView::section {{ background: {BACKGROUND}; color: {ACCENT};"
            f" border: none; border-bottom: 1px solid {BORDER}; padding: 4px 6px;"
            " font-size: 14px; font-weight: 600; }"
        )
        column.addWidget(self.jobs_table, stretch=1)
        return container

    def _new_task(self) -> None:
        """Ask how the new task looks and add it to the schedule."""
        dialog = _NewTaskDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        job = self.scheduler.add_interval_job(
            dialog.start(), dialog.every(), dialog.unit(), dialog.task_id()
        )
        self.logged.emit(f"scheduled {job.task_id}: {job.describe()}")

    def _set_job_enabled(self, row: int, enabled: bool) -> None:
        if 0 <= row < len(self.scheduler.jobs):
            self.scheduler.set_enabled(row, enabled)

    def _remove_job_row(self, row: int) -> None:
        if 0 <= row < len(self.scheduler.jobs):
            self.scheduler.remove_job(row)

    def _on_job_fired(self, job: Job, started: bool) -> None:
        note = "" if started else " (skipped, already running)"
        self.logged.emit(f"schedule '{job.describe()}' fired {job.task_id}{note}")

    @staticmethod
    def _centered(widget: QWidget) -> QWidget:
        """Wrap a widget so it sits in the middle of a table cell."""
        cell = QWidget()
        cell.setStyleSheet("background: transparent;")
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cell_layout.addWidget(widget)
        return cell

    def _refresh_jobs(self) -> None:
        table = self.jobs_table
        table.setRowCount(len(self.scheduler.jobs))
        for row, job in enumerate(self.scheduler.jobs):
            toggle = Switch(job.enabled)
            toggle.setToolTip("Enabled" if job.enabled else "Disabled")
            toggle.toggled.connect(lambda checked, r=row: self._set_job_enabled(r, checked))
            table.setCellWidget(row, 0, self._centered(toggle))

            table.setItem(row, 1, QTableWidgetItem(job.describe()))
            table.setItem(row, 2, QTableWidgetItem(TASKS[job.task_id].name))
            nxt = self.scheduler.next_run(job)
            table.setItem(row, 3, QTableWidgetItem(nxt.strftime("%Y-%m-%d %H:%M") if nxt else "—"))

            remove = QPushButton("×")
            remove.setFixedSize(22, 22)
            remove.setStyleSheet(
                f"QPushButton {{ background-color: transparent; color: {ACCENT}; border: none; font-size: 16px; }}"
                f"QPushButton:hover {{ color: {REMOVE_HOVER}; }}"
            )
            remove.clicked.connect(lambda _=False, r=row: self._remove_job_row(r))
            table.setCellWidget(row, 4, self._centered(remove))
        total = len(self.scheduler.jobs)
        active = sum(1 for job in self.scheduler.jobs if job.enabled)
        tasks = "task" if total == 1 else "tasks"
        self.schedule_info_label.setText(
            f"{total} {tasks} · {active} active · {total - active} inactive"
        )
