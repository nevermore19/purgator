"""In-app cron: fires tasks on cron expressions while the app is running."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
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
    cron: str
    task_id: str
    enabled: bool = True


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

    def add_job(self, cron: str, task_id: str) -> Job:
        if error := self.validate(cron, task_id):
            raise ValueError(error)
        job = Job(cron.strip(), task_id)
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

    def _rearm(self) -> None:
        now = datetime.now()
        live = {id(j) for j in self.jobs if j.enabled}
        self._next = {k: v for k, v in self._next.items() if k in live}
        for job in self.jobs:
            if job.enabled and id(job) not in self._next:
                self._next[id(job)] = croniter(job.cron, now).get_next(datetime)
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
                self._next[id(job)] = croniter(job.cron, now).get_next(datetime)
        self._rearm()
        self.jobs_changed.emit()

    def _load(self) -> None:
        raw = self.settings.value(SETTINGS_KEY, "[]")
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            items = []
        self.jobs = [
            Job(**item) for item in items
            if isinstance(item, dict) and self.validate(item.get("cron", ""), item.get("task_id", "")) is None
        ]
        self._rearm()

    def _save(self) -> None:
        self.settings.setValue(SETTINGS_KEY, json.dumps([asdict(j) for j in self.jobs]))
