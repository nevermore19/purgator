"""The applications that are installed on the system.

They come from the places where applications live: the desktop entries of the
freedesktop menu, the sandboxes of flatpak and snap and the packages of the
system package manager. Every application keeps the place it came from, so the
removal can pick the right command later on.

The app itself may live in a sandbox (a flatpak), while the system it cleans
up lives on the host. Every command is therefore sent to the host with
flatpak-spawn, and the removals that need the root password ask for it with a
window of their own.
"""

from __future__ import annotations

import configparser
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from purgator.usage import (
    add_flatpak_times,
    add_jetbrains_times,
    add_program_times,
    add_steam_times,
    collect_usage,
)

# report(percent, message) is not needed here; the scan only reports at the end
CancelCheck = Callable[[], bool]

# Used for the small commands that are worth no cancel
NO_CANCEL: CancelCheck = lambda: False

# The desktop entries of the freedesktop menu, the user first. The entries of
# flatpak and snap are left out on purpose: they show up as their own kind.
DESKTOP_DIRS: tuple[Path, ...] = (
    Path.home() / ".local/share/applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
)

# The sources that hold packages of their own
PACKAGE_SOURCES: tuple[str, ...] = ("flatpak", "snap", "dpkg", "rpm", "pacman")

# The commands that need the root password
ROOT_COMMANDS: tuple[str, ...] = ("pacman", "apt-get", "rpm")

# Where flatpak keeps its apps: the user first
FLATPAK_ROOTS: tuple[Path, ...] = (
    Path.home() / ".local/share/flatpak",
    Path("/var/lib/flatpak"),
)

# Where snap keeps its apps
SNAP_ROOT = Path("/snap")

# Where snap keeps the icons of its apps, inside every snap
SNAP_ICON_NAMES: tuple[str, ...] = ("icon.svg", "icon.png")

# The databases of the package managers, used when their tool is missing
DPKG_STATUS = Path("/var/lib/dpkg/status")
PACMAN_LOCAL = Path("/var/lib/pacman/local")

# How long a package manager may take before it is given up on
COMMAND_TIMEOUT = 30

# How long a removal may take; the password window waits for the user
REMOVE_TIMEOUT = 600

# A desktop entry of a Steam game starts Steam with this address
STEAM_GAME = re.compile(r"steam://rungameid/(\d+)")

# The size of the units the package managers use
SIZE_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


@dataclass(frozen=True)
class Application:
    """One installed application."""

    name: str
    source: str  # "desktop", "flatpak", "snap", "dpkg", "rpm", "pacman"
    package: str  # the identifier the source uses
    size: int = 0  # bytes, 0 when the source does not tell
    needs_root: bool = False  # the removal wants the root password
    summary: str = ""  # the version or the short description
    path: Path | None = None  # the file it lives in, for desktop entries
    owner: str | None = None  # the package the program belongs to
    owner_source: str | None = None  # the source of that package
    last_used: float = 0.0  # when it was used for the last time, 0 when never
    used_from: str = ""  # where that moment comes from
    program: str = ""  # the program it starts, for the trace of the usage
    icon: str = ""  # a name of the icon theme or the path of an image
    steam_game: str = ""  # the id of the game, for the entries Steam made


def discover_applications(is_cancelled: CancelCheck | None = None) -> list[Application]:
    """Look for every application the user can start.

    Only the programs are listed: the desktop entries of the menu, the flatpaks
    and the snaps. The packages of the system are looked at too, but only to
    know which one a desktop entry belongs to.
    """
    cancelled = is_cancelled if is_cancelled is not None else NO_CANCEL
    desktop = _desktop_apps(cancelled)
    _fill_owners(desktop)  # before the list is put together
    apps = list(desktop)
    apps.extend(_flatpak_apps(cancelled))
    apps.extend(_snap_apps(cancelled))
    _fill_usage(apps)
    apps.sort(key=_order)
    return apps


def _order(app: Application) -> tuple:
    """The apps that were not used for a long time come first."""
    when = app.last_used
    return (0 if when <= 0 else 1, when or 0.0, app.name.lower())


def _fill_owners(desktop: list[Application]) -> None:
    """Give the desktop entries the size of the package they belong to.

    The program of a desktop entry is often a small script, so the size of the
    package behind it tells much more about the room the app takes. The name of
    that package is also the one the removal has to use.
    """
    if not desktop:
        return
    paths = [str(app.path) for app in desktop if app.path is not None]
    owners = _pacman_owners(paths)
    source = "pacman"
    if not owners:
        owners = _dpkg_owners(paths)
        source = "dpkg"
    if not owners:
        return
    names = set(owners.values())
    details = _pacman_details(names) if source == "pacman" else _dpkg_details(names)
    for index, app in enumerate(desktop):
        name = owners.get(str(app.path).lstrip("/"))
        if not name:
            continue
        info = details.get(name, {})
        desktop[index] = replace(
            app,
            size=max(app.size, info.get("size", 0)),
            summary=app.summary or info.get("version", ""),
            needs_root=True,  # the package of the system asks for the password
            owner=name,
            owner_source=source,
        )


def _pacman_owners(paths: list[str]) -> dict[str, str]:
    """The pacman package that owns every one of the files."""
    if not paths:
        return {}
    # The database of pacman says which files belong to which package. It keeps
    # the paths without the first slash.
    script = "grep -H -F " + " ".join(f"-e {shlex.quote(p.lstrip('/'))}" for p in paths)
    script += " /var/lib/pacman/local/*/files"
    output = _host_run(["sh", "-c", script], NO_CANCEL) or ""
    directories: dict[str, str] = {}
    for line in output.splitlines():
        # the package of an epoch has a colon in its name, so the last colon wins
        file_part, sep, path = line.rpartition(":")
        if not sep:
            continue
        directories[path.strip().lstrip("/")] = file_part.rsplit("/files", 1)[0]
    if not directories:
        return {}
    names = _pacman_names(set(directories.values()))
    return {
        path: names[directory]
        for path, directory in directories.items()
        if directory in names
    }


def _pacman_names(directories: set[str]) -> dict[str, str]:
    """The name of every package, taken from its own description."""
    if not directories:
        return {}
    files = " ".join(shlex.quote(f"{directory}/desc") for directory in sorted(directories))
    # the name is written on the line after its key
    script = f"for f in {files}; do printf '%s\\t' \"$f\"; sed -n '/^%NAME%$/{{n;p;q}}' \"$f\"; done"
    output = _host_run(["sh", "-c", script], NO_CANCEL) or ""
    names: dict[str, str] = {}
    for line in output.splitlines():
        file_part, sep, name = line.partition("\t")
        if not sep:
            continue
        name = name.strip()
        if name:
            names[file_part.rsplit("/desc", 1)[0]] = name
    return names


def _pacman_details(names: set[str]) -> dict[str, dict[str, object]]:
    """What pacman tells about the packages: the size they take and the day
    they came in.
    """
    if not names:
        return {}
    # the words of pacman are translated, so the language is set to English
    script = "LC_ALL=C pacman -Qi " + " ".join(shlex.quote(name) for name in sorted(names))
    output = _host_run(["sh", "-c", script], NO_CANCEL) or ""
    details: dict[str, dict[str, object]] = {}
    current: dict[str, object] = {}
    for line in output.splitlines():
        field, sep, value = line.partition(":")
        if not sep:
            continue
        field = field.strip()
        value = value.strip()
        if field == "Name":
            current = {"name": value}
            details[value] = current
        elif current and field == "Version":
            current["version"] = value
        elif current and field == "Installed Size":
            current["size"] = _parse_size(value)
        elif current and field == "Install Date":
            current["installed"] = _parse_date(value)
    return details


def _dpkg_owners(paths: list[str]) -> dict[str, str]:
    """The dpkg package that owns every one of the files."""
    if not paths:
        return {}
    script = "dpkg-query -S " + " ".join(shlex.quote(p) for p in paths)
    output = _host_run(["sh", "-c", script], NO_CANCEL) or ""
    owners: dict[str, str] = {}
    for line in output.splitlines():
        name, sep, path = line.partition(":")
        if sep:
            owners[path.strip().lstrip("/")] = name.strip()
    return owners


def _fill_usage(apps: list[Application]) -> None:
    """Say when every application was used for the last time."""
    if not apps:
        return
    index = collect_usage()
    programs = [app.program for app in apps if app.program]
    # Toolbox reads the files of the IDEs, so only their settings count
    ides = add_jetbrains_times(index, programs)
    add_program_times(index, [program for program in programs if program not in ides])
    add_flatpak_times(index, [app.package for app in apps if app.source == "flatpak"])
    add_steam_times(index)
    for position, app in enumerate(apps):
        found = index.get(_usage_keys(app))
        apps[position] = replace(app, last_used=found.when, used_from=found.source)


def _usage_keys(app: Application) -> list[str]:
    """The names an application can be known by in the traces of the usage."""
    if app.steam_game:
        # the program is Steam itself, so only Steam knows when the game ran
        return [f"steam:{app.steam_game}"]
    keys = [app.package, app.name]
    if app.program:
        keys.extend((app.program, Path(app.program).name))
    if app.path is not None:
        keys.append(app.path.stem)
    return [key for key in keys if key]


def removal_command(app: Application) -> list[str]:
    """The command that uninstalls the application."""
    if app.source == "desktop":
        # A desktop entry of the system belongs to a package: that package goes
        # away, and with it the program the entry starts.
        if app.owner and app.owner_source in PACKAGE_SOURCES:
            return _package_command(app.owner_source, app.owner)
        return ["rm", "-f", str(app.path)] if app.path else []
    return _package_command(app.source, app.package)


def _package_command(source: str, package: str) -> list[str]:
    """The command of the package manager that removes a package."""
    if source == "flatpak":
        return ["flatpak", "uninstall", "-y", package]
    if source == "snap":
        return ["snap", "remove", package]
    if source == "dpkg":
        return ["apt-get", "remove", "-y", package]
    if source == "rpm":
        return ["rpm", "-e", package]
    if source == "pacman":
        return ["pacman", "-R", "--noconfirm", package]
    return []


def removal_command_for(app: Application) -> list[str]:
    """The command that removes the application, the password window included."""
    command = removal_command(app)
    if not command:
        return []
    if app.source == "desktop" and not app.owner:
        # only a launcher file: the ones of the user go right here
        if app.path is not None and _in_home(app.path):
            return ["rm", "-f", str(app.path)]
        return [*_host_prefix(), *command]
    if command[0] in ROOT_COMMANDS or app.needs_root:
        program = _which(command[0]) or command[0]
        return [*_host_prefix(), "pkexec", program, *command[1:]]
    return [*_host_prefix(), *command]


def remove_application(app: Application) -> tuple[bool, str]:
    """Remove the application; the answer tells if it worked and why not."""
    command = removal_command_for(app)
    if not command:
        return False, "there is no way to remove it"
    try:
        finished = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=REMOVE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return finished.returncode == 0, finished.stdout.strip()


# --- the host ---------------------------------------------------------------


def _host_prefix() -> list[str]:
    """The words that send a command to the host instead of the sandbox."""
    if os.environ.get("FLATPAK_ID") and shutil.which("flatpak-spawn"):
        return ["flatpak-spawn", "--host"]
    return []


def _host_run(command: list[str], is_cancelled: CancelCheck) -> str | None:
    """Run a command on the host when the app lives in a sandbox."""
    return _run([*_host_prefix(), *command], is_cancelled)


def _read_text(path: Path) -> str:
    """The content of a file, from the host when the app lives in a sandbox."""
    prefix = _host_prefix()
    if prefix:
        return _run([*prefix, "cat", str(path)], NO_CANCEL) or ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _list_names(path: Path) -> list[str]:
    """The names of the entries of a directory, from the host when needed."""
    prefix = _host_prefix()
    if prefix:
        output = _run([*prefix, "ls", "-1", str(path)], NO_CANCEL) or ""
        return output.splitlines()
    try:
        return sorted(p.name for p in path.iterdir())
    except OSError:
        return []


def _path_size(path: str) -> int:
    """The size of a file or a directory in bytes."""
    if not path:
        return 0
    prefix = _host_prefix()
    output = _run([*prefix, "du", "-sb", "--", path], NO_CANCEL) or ""
    parts = output.split()
    return int(parts[0]) if parts and parts[0].isdigit() else 0


def _which(program: str) -> str | None:
    """Where a program is, on the host when the app lives in a sandbox."""
    prefix = _host_prefix()
    if prefix:
        output = _run([*prefix, "which", program], NO_CANCEL) or ""
        return output.strip() or None
    return shutil.which(program)


def _in_home(path: Path) -> bool:
    """True when the path is inside the home directory of the user."""
    home = str(Path.home())
    text = str(path)
    return text == home or text.startswith(home + os.sep)


# --- the sources ------------------------------------------------------------


def _desktop_apps(is_cancelled: CancelCheck) -> list[Application]:
    """The entries of the freedesktop menu."""
    apps: list[Application] = []
    seen: set[str] = set()
    for directory in DESKTOP_DIRS:
        for name in _list_names(directory):
            if not name.endswith(".desktop"):
                continue
            if is_cancelled():
                return apps
            app = _read_desktop_entry(directory / name, directory)
            if app is None or app.package in seen:
                continue
            seen.add(app.package)
            apps.append(app)
    return apps


def _read_desktop_entry(entry: Path, directory: Path) -> Application | None:
    """Read one .desktop file; None when it does not show up in the menu."""
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # the keys are written in camel case
    try:
        parser.read_string(_read_text(entry))
    except (configparser.Error, OSError):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    data = parser["Desktop Entry"]
    if data.get("Type", "Application") != "Application":
        return None
    hidden = data.get("NoDisplay", "false").strip().lower()
    hidden = hidden == "true" or data.get("Hidden", "false").strip().lower() == "true"
    name = data.get("Name", "").strip()
    if hidden or not name:
        return None
    exec_line = data.get("Exec", "")
    program = _program_of(exec_line)
    steam_game = STEAM_GAME.search(exec_line)
    return Application(
        name=name,
        source="desktop",
        package=entry.stem,
        summary=data.get("Comment", "").strip(),
        size=_path_size(program),
        needs_root=not _in_home(directory),
        path=entry,
        program=program,
        icon=data.get("Icon", "").strip(),
        steam_game=steam_game.group(1) if steam_game else "",
    )


def _program_of(exec_line: str) -> str:
    """The program a desktop entry starts."""
    try:
        parts = shlex.split(exec_line)  # the path may be in quotes
    except ValueError:
        parts = exec_line.split()
    if not parts:
        return ""
    program = parts[0]
    if program.startswith("/"):
        return program
    return _which(program) or ""


def _flatpak_apps(is_cancelled: CancelCheck) -> list[Application]:
    """The sandboxes of flatpak."""
    apps = _flatpak_cli_apps(is_cancelled)
    if apps:
        return apps
    return _flatpak_metadata_apps(is_cancelled)


def _flatpak_cli_apps(is_cancelled: CancelCheck) -> list[Application]:
    """The sandboxes flatpak itself reports."""
    if not _which("flatpak"):
        return []
    user_apps = set()
    user_output = _host_run(
        ["flatpak", "list", "--user", "--app", "--columns=application"], is_cancelled
    )
    if user_output:
        user_apps = {line.strip() for line in user_output.splitlines() if line.strip()}
    output = _host_run(
        ["flatpak", "list", "--app", "--columns=application,name,size"], is_cancelled
    )
    if output is None:  # an older flatpak does not know the size column
        output = _host_run(
            ["flatpak", "list", "--app", "--columns=application,name"], is_cancelled
        )
    if not output:
        return []
    apps = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        package, name = parts[0].strip(), parts[1].strip()
        if not package:
            continue
        size = _parse_size(parts[2]) if len(parts) > 2 else 0
        apps.append(
            Application(
                name=name or package,
                source="flatpak",
                package=package,
                size=size,
                needs_root=package not in user_apps,
                icon=package,  # flatpak exports the icon under the id of the app
            )
        )
    return apps


def _flatpak_metadata_apps(is_cancelled: CancelCheck) -> list[Application]:
    """The sandboxes flatpak keeps on disk, used when flatpak itself is gone."""
    apps = []
    for root in FLATPAK_ROOTS:
        needs_root = root != FLATPAK_ROOTS[0]
        for app_id in _list_names(root / "app"):
            if is_cancelled():
                return apps
            if not app_id or app_id.startswith("."):
                continue
            apps.append(
                Application(
                    name=_flatpak_display_name(app_id, root),
                    source="flatpak",
                    package=app_id,
                    needs_root=needs_root,
                    icon=app_id,
                )
            )
    return apps


def _flatpak_display_name(app_id: str, root: Path) -> str:
    """The name of the app as the menu shows it."""
    entry = root / "exports" / "share" / "applications" / f"{app_id}.desktop"
    if entry.is_file() or _host_prefix():
        app = _read_desktop_entry(entry, entry.parent)
        if app is not None:
            return app.name
    return app_id


def _snap_apps(is_cancelled: CancelCheck) -> list[Application]:
    """The packages of snap."""
    apps = _snap_cli_apps(is_cancelled)
    if apps:
        return apps
    return _snap_metadata_apps(is_cancelled)


def _snap_cli_apps(is_cancelled: CancelCheck) -> list[Application]:
    """The packages snap itself reports."""
    if not _which("snap"):
        return []
    output = _host_run(["snap", "list"], is_cancelled)
    if not output:
        return []
    user = os.environ.get("USER", "")
    apps = []
    for line in output.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 4 or parts[0] == "Name":
            continue  # the header of the table
        name, version, tracking = parts[0], parts[1], parts[3]
        # a user snap tracks a channel of the user, a system snap does not
        needs_root = not (user and tracking.endswith("/" + user))
        apps.append(
            Application(
                name=name,
                source="snap",
                package=name,
                summary=version,
                size=_path_size(f"{SNAP_ROOT}/{name}"),
                needs_root=needs_root,
                icon=_snap_icon(name),
            )
        )
    return apps


def _snap_metadata_apps(is_cancelled: CancelCheck) -> list[Application]:
    """The packages snap keeps on disk, used when snap itself is gone."""
    apps = []
    for entry in _list_names(SNAP_ROOT):
        if is_cancelled():
            return apps
        if entry.startswith("."):
            continue
        name, version = _read_snap_yaml(SNAP_ROOT / entry)
        apps.append(
            Application(
                name=name or entry,
                source="snap",
                package=entry,
                summary=version,
                size=_path_size(f"{SNAP_ROOT}/{entry}"),
                needs_root=True,
                icon=_snap_icon(entry),
            )
        )
    return apps


def _snap_icon(name: str) -> str:
    """The path of the icon a snap carries, empty when it has none."""
    gui = SNAP_ROOT / name / "current" / "meta" / "gui"
    for icon in SNAP_ICON_NAMES:
        if (gui / icon).is_file():
            return str(gui / icon)
    return ""


def _read_snap_yaml(path: Path) -> tuple[str, str]:
    """The name and the version of a snap, taken from its own file."""
    text = _read_text(path / "meta" / "snap.yaml")
    name = version = ""
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep or line.startswith((" ", "\t", "#")):
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "name" and not name:
            name = value
        elif key == "version" and not version:
            version = value
    return name, version


def _dpkg_details(names: set[str]) -> dict[str, dict[str, object]]:
    """What dpkg tells about the packages: the room they take."""
    if not names:
        return {}
    script = "dpkg-query -W -f='${Package}\t${Installed-Size}\n' "
    script += " ".join(shlex.quote(name) for name in sorted(names))
    output = _host_run(["sh", "-c", script], NO_CANCEL) or ""
    details: dict[str, dict[str, object]] = {}
    for line in output.splitlines():
        name, sep, size = line.partition("\t")
        if not sep:
            continue
        try:
            details[name.strip()] = {"size": int(size.strip()) * 1024}  # the size is in KiB
        except ValueError:
            continue
    return details


# --- helpers ----------------------------------------------------------------


def _run(command: list[str], is_cancelled: CancelCheck) -> str | None:
    """Run a command and return its output; None when it did not work."""
    if is_cancelled():
        return None
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


def _parse_size(value: str) -> int:
    """Turn "1234" or "1,2 GiB" into bytes."""
    text = value.strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        pass
    parts = text.split()
    if len(parts) != 2:
        return 0
    try:
        # some tools write the decimal comma of their language
        number = float(parts[0].replace(",", "."))
    except ValueError:
        return 0
    unit = parts[1].strip().lower()
    if unit.endswith("b"):
        unit = unit[:-1]  # "kib" -> "ki", "mb" -> "m"
    if unit.endswith("i"):
        unit = unit[:-1]  # "ki" -> "k"
    return int(number * SIZE_UNITS.get(unit, 1))


def _parse_date(value: str) -> float:
    """Turn "Thu Oct 22 13:37:47 2026" into a time."""
    try:
        return time.mktime(time.strptime(value.strip(), "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return 0.0
