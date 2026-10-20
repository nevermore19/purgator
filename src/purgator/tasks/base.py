from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# report(percent, message); percent is -1 when progress is indeterminate
Reporter = Callable[[int, str], None]
CancelCheck = Callable[[], bool]


class Cancelled(Exception):
    pass


@dataclass
class TaskResult:
    task_id: str
    files: int = 0
    bytes: int = 0
    dry_run: bool = True
    paths: list[Path] = field(default_factory=list)
    # the paths that are directories; the rest are plain files
    directories: set[Path] = field(default_factory=set)
    # size of every single path
    sizes: dict[Path, int] = field(default_factory=dict)

    def summary(self) -> str:
        verb = "would free" if self.dry_run else "freed"
        return f"{self.task_id}: {self.files} files, {verb} {human_size(self.bytes)}"


class PurgeTask(ABC):
    id: str
    name: str

    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        # When set, the task works on exactly these paths instead of looking
        # for candidates itself; used when the user picked what to delete.
        self.only: set[Path] | None = None

    @abstractmethod
    def run(self, report: Reporter, is_cancelled: CancelCheck) -> TaskResult: ...


def human_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def dir_size(path: Path, is_cancelled: CancelCheck) -> tuple[int, int]:
    """Return (file_count, total_bytes) under path without following symlinks."""
    files = total = 0
    stack = [path]
    while stack:
        if is_cancelled():
            raise Cancelled
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            files += 1
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return files, total