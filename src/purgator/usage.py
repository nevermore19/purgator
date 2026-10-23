"""When the user opened an application for the last time.

Linux keeps no list of the programs that were used, so the date is looked for
in the few places that leave a trace:

  - the recently-used database of the desktop (recently-used.xbel): it says
    which program opened which file, and when
  - the folders where an application keeps its settings (~/.config and the
    like): the last change of them is close to the last time it was open
  - the program itself: when it starts, its own file is read

An application without any of these was never used, or was used long before the
traces began to be kept.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from purgator.host import access_times, list_names, read_text

# The databases of the desktop
RECENT_FILES: tuple[Path, ...] = (
    Path.home() / ".local/share/recently-used.xbel",
    Path.home() / ".local/share/krecentlyused.xbel",
)

# The folders where the applications keep their things
SETTINGS_FOLDERS: tuple[Path, ...] = (
    Path.home() / ".config",
    Path.home() / ".local/share",
    Path.home() / ".cache",
)

# The flatpaks keep their things here
FLATPAK_FOLDER = Path.home() / ".var/app"

# An application that was not touched for that many days is old
OLD_DAYS = 90

# A bookmark of the recently-used database looks like this:
#   <bookmark:application count="3" exec="kate %u" modified="2026-10-22T10:49:40.000000Z" name="org.kde.kate"/>
_APPLICATION = re.compile(
    r'<bookmark:application count="(\d+)" exec="([^"]*)" modified="([^"]*)" name="([^"]*)"'
)


@dataclass(frozen=True)
class Usage:
    """The moment an application was used for the last time."""

    when: float  # the time of the last use, 0 when there is no trace
    source: str  # where the date comes from

    @property
    def known(self) -> bool:
        return self.when > 0


NEVER = Usage(0.0, "")


class UsageIndex:
    """What is known about the last use of every application."""

    def __init__(self) -> None:
        self._times: dict[str, tuple[float, str]] = {}

    def add(self, key: str, when: float, source: str) -> None:
        """Remember a moment; the newest one wins."""
        if not key or when <= 0:
            return
        key = key.lower()
        known = self._times.get(key)
        if known is None or when > known[0]:
            self._times[key] = (when, source)

    def get(self, keys: list[str]) -> Usage:
        """The newest moment that belongs to one of the keys."""
        best = NEVER
        for key in keys:
            if not key:
                continue
            found = self._times.get(key.lower())
            if found is None:
                continue
            if found[0] > best.when:
                best = Usage(found[0], found[1])
        return best

    def __len__(self) -> int:
        return len(self._times)


def collect_usage() -> UsageIndex:
    """Look for the last use of everything the user can start."""
    index = UsageIndex()
    _read_recently_used(index)
    _read_settings_folders(index)
    return index


def _read_recently_used(index: UsageIndex) -> None:
    """The database of the desktop says which program opened which file."""
    for path in RECENT_FILES:
        text = read_text(path)
        if not text:
            continue
        for match in _APPLICATION.finditer(text):
            when = _parse_stamp(match.group(3))
            if when <= 0:
                continue
            program = (match.group(2).split() or [""])[0]
            index.add(program, when, "the last file it opened")
            index.add(match.group(4), when, "the last file it opened")


def _read_settings_folders(index: UsageIndex) -> None:
    """The folders of the applications say when they were changed."""
    for base in SETTINGS_FOLDERS:
        for name in list_names(base):
            when = _newest_mtime(base / name)
            if when > 0:
                index.add(name, when, "the last change of its settings")


def add_program_times(index: UsageIndex, programs: list[str]) -> None:
    """Add the moment the programs themselves were read the last time."""
    paths = [p for p in programs if p.startswith("/")]
    for path, when in access_times(paths).items():
        index.add(path.rsplit("/", 1)[-1], when, "the last time it was started")


def add_flatpak_times(index: UsageIndex, app_ids: list[str]) -> None:
    """The flatpaks keep their settings in the home directory."""
    for app_id in app_ids:
        when = _newest_mtime(FLATPAK_FOLDER / app_id)
        if when > 0:
            index.add(app_id, when, "the last change of its settings")


def _newest_mtime(path: Path, depth: int = 1) -> float:
    """The newest moment that something inside the folder changed."""
    try:
        newest = path.stat().st_mtime
    except OSError:
        return 0.0
    if depth <= 0:
        return newest
    try:
        for child in path.iterdir():
            try:
                if child.is_dir() and not child.is_symlink():
                    newest = max(newest, _newest_mtime(child, depth - 1))
                else:
                    newest = max(newest, child.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest


def _parse_stamp(text: str) -> float:
    """Turn "2026-10-22T10:49:40.000000Z" into a time."""
    try:
        return datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
    except ValueError:
        return 0.0


def describe(when: float) -> str:
    """Say how long ago that was, in words the user understands."""
    if when <= 0:
        return "never"
    days = int((time.time() - when) // 86400)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    if days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years > 1 else ''} ago"


def describe_exact(when: float) -> str:
    """The day of the last use, for the tip of the row."""
    if when <= 0:
        return "no trace of it being used"
    return datetime.fromtimestamp(when).strftime("%Y-%m-%d %H:%M")


def is_old(when: float, days: int = OLD_DAYS) -> bool:
    """True when the application was not used for a long time (or never)."""
    if when <= 0:
        return True
    return (time.time() - when) > days * 86400
