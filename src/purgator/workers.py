"""Workers only talk to the GUI through Qt signals; because the receivers live in
the GUI thread, Qt queues those calls onto the GUI event loop automatically.
"""

from __future__ import annotations

import threading
import time
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from purgator.tasks import Cancelled, PurgeTask

PROGRESS_INTERVAL = 0.1  # seconds; throttles progress signals so the event queue isn't flooded


class WorkerSignals(QObject):
    started = Signal(str)
    progress = Signal(str, int, str)  # task_id, percent (-1 = busy), message
    finished = Signal(str, object)  # task_id, TaskResult
    failed = Signal(str, str)  # task_id, error
    cancelled = Signal(str)


class Worker(QRunnable):
    def __init__(self, task: PurgeTask) -> None:
        super().__init__()
        self.task = task
        self.signals = WorkerSignals()
        self._cancel = threading.Event()
        self._last_report = 0.0
        # Lifetime is managed by TaskRunner, not by the pool
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self._cancel.set()

    def _report(self, percent: int, message: str) -> None:
        now = time.monotonic()
        if percent >= 100 or now - self._last_report >= PROGRESS_INTERVAL:
            self._last_report = now
            self.signals.progress.emit(self.task.id, percent, message)

    def run(self) -> None:
        task_id = self.task.id
        self.signals.started.emit(task_id)
        try:
            result = self.task.run(self._report, self._cancel.is_set)
        except Cancelled:
            self.signals.cancelled.emit(task_id)
        except Exception:
            self.signals.failed.emit(task_id, traceback.format_exc())
        else:
            self.signals.finished.emit(task_id, result)


class TaskRunner(QObject):
    task_started = Signal(str)
    task_progress = Signal(str, int, str)
    task_finished = Signal(str, object)
    task_failed = Signal(str, str)
    task_cancelled = Signal(str)
    running_changed = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self._workers: dict[str, Worker] = {}

    def is_running(self, task_id: str) -> bool:
        return task_id in self._workers

    @property
    def running_count(self) -> int:
        return len(self._workers)

    def run(self, task: PurgeTask) -> bool:
        """Start task in the background; returns False if it is already running."""
        if task.id in self._workers:
            return False
        worker = Worker(task)
        s = worker.signals
        s.started.connect(self.task_started)
        s.progress.connect(self.task_progress)
        s.finished.connect(self.task_finished)
        s.failed.connect(self.task_failed)
        s.cancelled.connect(self.task_cancelled)
        for done in (s.finished, s.failed, s.cancelled):
            done.connect(self._on_done)
        self._workers[task.id] = worker
        self.pool.start(worker)
        self.running_changed.emit(self.running_count)
        return True

    def cancel(self, task_id: str) -> None:
        if worker := self._workers.get(task_id):
            worker.cancel()

    def cancel_all(self) -> None:
        for worker in self._workers.values():
            worker.cancel()

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self.cancel_all()
        self.pool.waitForDone(timeout_ms)

    def _on_done(self, task_id: str, *_) -> None:
        self._workers.pop(task_id, None)
        self.running_changed.emit(self.running_count)