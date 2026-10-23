"""In-app cron: fires tasks on cron expressions while the app is running."""

from __future__ import annotations

import calendar
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Callable

from croniter import croniter
from PySide6.QtCore import QObject, QSettings, QTimer, Signal

from purgator.tasks import TASKS, PurgeTask
from purgator.workers import TaskRunner

# Re-check at least this often so sleep/suspend or clock changes can't make us miss a run
MAX_SLEEP_MS = 60_000
SETTINGS_KEY = "scheduler/jobs"


@dataclass
class Job:
    cron: str = ""
    task_id: str = ""
    enabled: bool = True
    start: str = ""
    every: int = 0
    unit: str = ""

    @property
    def is_interval(self) -> bool:
        return bool(self.start) and self.every > 0 and self.unit in ("day", "month")

    def start_datetime(self) -> datetime:
        return datetime.fromisoformat(self.start)

    def describe(self) -> str:
        """A readable form of the schedule for the table of jobs."""
        if not self.is_interval:
            return self.cron
        start = self.start_datetime()
        unit = self.unit if self.every == 1 else f"{self.unit}s"
        return f"Every {self.every} {unit} at {start:%H:%M}, from {start:%Y-%m-%d}"


def _add_months(moment: datetime, months: int) -> datetime:
    """Move a moment by whole months, keeping the day where possible."""
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


class CronScheduler(QObject):
    jobs_changed = Signal()
    job_fired = Signal(object, bool)  # Job, started (False if task was already running)

    def __init__(
        self,
        runner: TaskRunner,
        task_factory: Callable[[str], PurgeTask],
        settings: QSettings | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.runner = runner
        self.task_factory = task_factory
        self.settings = settings or QSettings()
        self.jobs: list[Job] = []
        self._next: dict[int, datetime] = {}  # id(job) -> next fire time
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._load()

    @staticmethod
    def validate(cron: str, task_id: str) -> str | None:
        """Return an error message, or None if the job is valid."""
        if task_id not in TASKS:
            return f"Unknown task {task_id!r}"
        if not croniter.is_valid(cron):
            return f"Invalid cron expression {cron!r}"
        return None

    @staticmethod
    def validate_interval(start: datetime, every: int, unit: str, task_id: str) -> str | None:
        """Return an error message, or None if the interval job is valid."""
        if task_id not in TASKS:
            return f"Unknown task {task_id!r}"
        if every < 1:
            return "The frequency must be at least 1"
        if unit not in ("day", "month"):
            return f"Unknown frequency unit {unit!r}"
        return None

    def add_job(self, cron: str, task_id: str) -> Job:
        if error := self.validate(cron, task_id):
            raise ValueError(error)
        job = Job(cron.strip(), task_id)
        self.jobs.append(job)
        self._changed()
        return job

    def add_interval_job(
        self, start: datetime, every: int, unit: str, task_id: str
    ) -> Job:
        """Add a job that starts on a date and repeats every N days or months."""
        if error := self.validate_interval(start, every, unit, task_id):
            raise ValueError(error)
        start = start.replace(second=0, microsecond=0)
        job = Job(
            task_id=task_id,
            start=start.isoformat(timespec="minutes"),
            every=every,
            unit=unit,
        )
        self.jobs.append(job)
        self._changed()
        return job

    def remove_job(self, index: int) -> None:
        job = self.jobs.pop(index)
        self._next.pop(id(job), None)
        self._changed()

    def set_enabled(self, index: int, enabled: bool) -> None:
        self.jobs[index].enabled = enabled
        self._changed()

    def next_run(self, job: Job) -> datetime | None:
        return self._next.get(id(job)) if job.enabled else None

    def _changed(self) -> None:
        self._save()
        self._rearm()
        self.jobs_changed.emit()

    def _next_time(self, job: Job, now: datetime) -> datetime:
        """The moment the job should run next, after now."""
        if not job.is_interval:
            return croniter(job.cron, now).get_next(datetime)
        start = job.start_datetime()
        if start > now:
            return start
        if job.unit == "day":
            steps = (now - start).days // job.every
            moment = start + timedelta(days=steps * job.every)
            while moment <= now:
                moment += timedelta(days=job.every)
            return moment
        steps = ((now.year - start.year) * 12 + now.month - start.month) // job.every
        moment = _add_months(start, steps * job.every)
        while moment <= now:
            steps += 1
            moment = _add_months(start, steps * job.every)
        return moment

    def _rearm(self) -> None:
        now = datetime.now()
        live = {id(j) for j in self.jobs if j.enabled}
        self._next = {k: v for k, v in self._next.items() if k in live}
        for job in self.jobs:
            if job.enabled and id(job) not in self._next:
                self._next[id(job)] = self._next_time(job, now)
        if not self._next:
            self._timer.stop()
            return
        soonest = min(self._next.values())
        delay_ms = int((soonest - now).total_seconds() * 1000)
        self._timer.start(max(0, min(delay_ms, MAX_SLEEP_MS)))

    def _tick(self) -> None:
        now = datetime.now()
        for job in self.jobs:
            due = self._next.get(id(job))
            if job.enabled and due is not None and due <= now:
                started = self.runner.run(self.task_factory(job.task_id))
                self.job_fired.emit(job, started)
                self._next[id(job)] = self._next_time(job, now)
        self._rearm()
        self.jobs_changed.emit()

    def _load(self) -> None:
        raw = self.settings.value(SETTINGS_KEY, "[]")
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            items = []
        jobs = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                job = Job(**item)
            except TypeError:
                continue
            if job.is_interval:
                try:
                    start = job.start_datetime()
                except ValueError:
                    continue
                if self.validate_interval(start, job.every, job.unit, job.task_id):
                    continue
            elif self.validate(job.cron, job.task_id):
                continue
            jobs.append(job)
        self.jobs = jobs
        self._rearm()

    def _save(self) -> None:
        self.settings.setValue(SETTINGS_KEY, json.dumps([asdict(j) for j in self.jobs]))
