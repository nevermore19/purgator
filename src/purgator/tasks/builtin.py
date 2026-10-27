from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from purgator.tasks.base import (
    CancelCheck,
    Cancelled,
    PurgeTask,
    Reporter,
    TaskResult,
    dir_size,
    human_size,
)


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def entry_size(path: Path, is_cancelled: CancelCheck) -> tuple[int, int]:
    if path.is_dir() and not path.is_symlink():
        return dir_size(path, is_cancelled)
    try:
        return 1, path.lstat().st_size
    except OSError:
        return 0, 0


class _EntriesTask(PurgeTask):
    """Measures (and optionally removes) a list of top-level paths."""

    def candidates(self, is_cancelled: CancelCheck) -> list[Path]:
        raise NotImplementedError

    def run(self, report: Reporter, is_cancelled: CancelCheck) -> TaskResult:
        result = TaskResult(self.id, dry_run=self.dry_run)
        report(-1, "Collecting candidates…")
        if self.only is not None:
            entries = sorted(self.only)  # the user picked what to delete
        else:
            entries = self.candidates(is_cancelled)
        for i, path in enumerate(entries, 1):
            if is_cancelled():
                raise Cancelled
            files, size = entry_size(path, is_cancelled)
            result.files += files
            result.bytes += size
            result.paths.append(path)
            result.sizes[path] = size
            if path.is_dir() and not path.is_symlink():
                result.directories.add(path)
            if not self.dry_run:
                remove_path(path)
            report(i * 100 // len(entries), f"{path} ({human_size(size)})")
        return result


class UserCacheTask(_EntriesTask):
    id = "user_cache"
    name = "Clean user cache"

    def __init__(self, dry_run: bool = True, root: Path | None = None) -> None:
        super().__init__(dry_run)
        xdg = os.environ.get("XDG_CACHE_HOME")
        self.root = root or (Path(xdg) if xdg else Path.home() / ".cache")

    def candidates(self, is_cancelled: CancelCheck) -> list[Path]:
        try:
            return sorted(self.root.iterdir())
        except OSError:
            return []


class StaleFilesTask(_EntriesTask):
    id = "stale_files"
    name = "Remove stale temp files"

    def __init__(self, dry_run: bool = True, root: Path | None = None, days: int = 7) -> None:
        super().__init__(dry_run)
        self.root = root or Path(tempfile.gettempdir())
        self.days = days

    def candidates(self, is_cancelled: CancelCheck) -> list[Path]:
        cutoff = time.time() - self.days * 86400
        uid = os.getuid()
        found = []
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return []
        for path in entries:
            try:
                st = path.lstat()
            except OSError:
                continue
            if st.st_uid == uid and st.st_mtime < cutoff:
                found.append(path)
        return sorted(found)


class ProjectBuildsTask(_EntriesTask):
    id = "project_builds"
    name = "Clean project builds"

    TARGETS = frozenset(
        {"node_modules", "build", "dist", "target", "__pycache__", ".venv", ".pytest_cache", ".gradle"}
    )

    def __init__(self, dry_run: bool = True, root: Path | None = None) -> None:
        super().__init__(dry_run)
        self.root = root or Path.home()

    def candidates(self, is_cancelled: CancelCheck) -> list[Path]:
        found = []
        stack = [self.root]
        while stack:
            if is_cancelled():
                raise Cancelled
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if entry.name in self.TARGETS:
                            found.append(Path(entry.path))
                        else:
                            stack.append(Path(entry.path))
            except OSError:
                continue
        return sorted(found)