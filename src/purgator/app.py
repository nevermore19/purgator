from __future__ import annotations

import argparse
import sys
from pathlib import Path

from purgator.tasks import TASKS, Cancelled, create_task


def run_headless(task_id: str, delete: bool, root: str | None) -> int:
    """Run one task synchronously without a GUI (for system cron / scripts)."""
    kwargs = {"dry_run": not delete}
    if root:
        kwargs["root"] = Path(root).expanduser()
    task = create_task(task_id, **kwargs)
    try:
        result = task.run(lambda pct, msg: None, lambda: False)
    except Cancelled:
        return 1
    for path in result.paths:
        print(path)
    print(result.summary())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="purgator")
    parser.add_argument("--run", choices=sorted(TASKS), help="run a task headless and exit")
    parser.add_argument("--delete", action="store_true", help="actually delete (default is dry run)")
    parser.add_argument("--root", help="directory to operate on (task-specific)")
    args, qt_args = parser.parse_known_args(argv)

    if args.run:
        return run_headless(args.run, args.delete, args.root)

    from PySide6.QtWidgets import QApplication

    from purgator.ui import MainWindow

    app = QApplication([sys.argv[0], *qt_args])
    app.setOrganizationName("purgator")
    app.setApplicationName("purgator")
    window = MainWindow()
    window.show()
    return app.exec()
