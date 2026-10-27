"""The way to the host.

The app itself may live in a sandbox (a flatpak), while the system it looks at
lives on the host. Every command that reads the system is therefore sent to the
host with flatpak-spawn, and the removals that need the root password ask for
it with a window of their own.

Everything here works the same way with or without a sandbox: without one the
commands simply run here.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Callable

# report(percent, message) is not needed here; the scan only reports at the end
CancelCheck = Callable[[], bool]

# Used for the small commands that are worth no cancel
NO_CANCEL: CancelCheck = lambda: False

COMMAND_TIMEOUT = 30


def host_prefix() -> list[str]:
    """The words that send a command to the host instead of the sandbox."""
    if os.environ.get("FLATPAK_ID") and shutil.which("flatpak-spawn"):
        return ["flatpak-spawn", "--host"]
    return []


def run(command: list[str], is_cancelled: CancelCheck = NO_CANCEL) -> str | None:
    """Run a command and give back what it printed."""
    try:
        finished = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if finished.returncode != 0:
        return None
    return finished.stdout


def host_run(command: list[str], is_cancelled: CancelCheck = NO_CANCEL) -> str | None:
    """Run a command on the host when the app lives in a sandbox."""
    return run([*host_prefix(), *command], is_cancelled)


def read_text(path: Path) -> str:
    """The content of a file, from the host when the app lives in a sandbox."""
    prefix = host_prefix()
    if prefix:
        return run([*prefix, "cat", str(path)], NO_CANCEL) or ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def list_names(path: Path) -> list[str]:
    """The names of the entries of a directory, from the host when needed."""
    prefix = host_prefix()
    if prefix:
        output = run([*prefix, "ls", "-1", str(path)], NO_CANCEL) or ""
        return output.splitlines()
    try:
        return sorted(p.name for p in path.iterdir())
    except OSError:
        return []


def path_size(path: str) -> int:
    """The size of a file or a directory in bytes."""
    if not path:
        return 0
    prefix = host_prefix()
    output = run([*prefix, "du", "-sb", "--", path], NO_CANCEL) or ""
    parts = output.split()
    return int(parts[0]) if parts and parts[0].isdigit() else 0


def which(program: str) -> str | None:
    """Where a program is, on the host when the app lives in a sandbox."""
    prefix = host_prefix()
    if prefix:
        output = run([*prefix, "which", program], NO_CANCEL) or ""
        return output.strip() or None
    return shutil.which(program)


def in_home(path: Path) -> bool:
    """True when the path is inside the home directory of the user."""
    home = str(Path.home())
    text = str(path)
    return text == home or text.startswith(home + os.sep)


def access_times(paths: list[str]) -> dict[str, float]:
    """The moment each file was read the last time, on the host.

    A program that was started leaves that moment on its own file. It is the
    weakest of the traces, but it is the only one for the small tools.
    """
    if not paths:
        return {}
    times: dict[str, float] = {}
    # a long list of names does not fit in one command line
    for start in range(0, len(paths), 400):
        chunk = paths[start : start + 400]
        names = " ".join(shlex.quote(p) for p in chunk)
        command = f"stat -c '%X %n' -- {names} || true"
        output = host_run(["sh", "-c", command], NO_CANCEL) or ""
        for line in output.splitlines():
            stamp, _, name = line.partition(" ")
            if stamp.isdigit():
                times[name] = int(stamp)
    return times
