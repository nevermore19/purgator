from purgator.tasks.base import Cancelled, PurgeTask, TaskResult, human_size
from purgator.tasks.builtin import ProjectBuildsTask, StaleFilesTask, UserCacheTask

BUILTIN_TASKS: dict[str, type[PurgeTask]] = {
    cls.id: cls for cls in (UserCacheTask, StaleFilesTask, ProjectBuildsTask)
}
TASKS: dict[str, type[PurgeTask]] = dict(BUILTIN_TASKS)


def create_task(task_id: str, **kwargs) -> PurgeTask:
    return TASKS[task_id](**kwargs)


__all__ = [
    "BUILTIN_TASKS",
    "TASKS",
    "Cancelled",
    "PurgeTask",
    "TaskResult",
    "create_task",
    "human_size",
]
