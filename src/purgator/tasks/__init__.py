from purgator.tasks.base import Cancelled, PurgeTask, TaskResult, human_size
from purgator.tasks.builtin import ProjectBuildsTask, StaleFilesTask, UserCacheTask

TASKS: dict[str, type[PurgeTask]] = {
    cls.id: cls for cls in (UserCacheTask, StaleFilesTask, ProjectBuildsTask)
}


def create_task(task_id: str, **kwargs) -> PurgeTask:
    return TASKS[task_id](**kwargs)


__all__ = ["TASKS", "Cancelled", "PurgeTask", "TaskResult", "create_task", "human_size"]