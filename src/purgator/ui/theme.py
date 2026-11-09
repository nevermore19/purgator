from __future__ import annotations

import importlib
import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication, QPalette

from purgator.ui import colors

SETTINGS_KEY = "appearance/theme"

LIGHT = "light"
DARK = "dark"
SYSTEM = "system"

DEFAULT = SYSTEM
THEMES = (
    (LIGHT, "Light"),
    (DARK, "Dark"),
    (SYSTEM, "System"),
)

COLOR_NAMES = (
    "BACKGROUND",
    "STRIPE",
    "BORDER",
    "TEXT",
    "TEXT_ON_ACCENT",
    "HINT",
    "ACCENT",
    "ACCENT_HOVER",
    "ACCENT_DISABLED",
    "TRACK",
    "HOVER",
    "DISABLED",
    "REMOVE_HOVER",
    "SCROLLBAR",
    "SCROLLBAR_HOVER",
)

# The palette the app was built with.
LIGHT_COLORS = {name: getattr(colors, name) for name in COLOR_NAMES}

DARK_COLORS = {
    "BACKGROUND": "#272524",
    "STRIPE": "#333333",
    "BORDER": "#333333",
    "TEXT": "#FFFFFF",
    "TEXT_ON_ACCENT": "#FFFFFF",
    "HINT": "#B7B0A0",
    "ACCENT": "#696259",
    "ACCENT_HOVER": "#7A7268",
    "ACCENT_DISABLED": "#4A4540",
    "TRACK": "#B7B0A0",
    "HOVER": "#333333",
    "DISABLED": "#6B6259",
    "REMOVE_HOVER": "#D08C8C",
    "SCROLLBAR": "#696259",
    "SCROLLBAR_HOVER": "#B7B0A0",
}


def stored_theme(settings: QSettings | None = None) -> str:
    """The theme chosen in the settings; light is the default."""
    settings = settings or QSettings()
    value = str(settings.value(SETTINGS_KEY, DEFAULT))
    return value if value in (LIGHT, DARK, SYSTEM) else DEFAULT


def save_theme(name: str, settings: QSettings | None = None) -> None:
    if name not in (LIGHT, DARK, SYSTEM):
        name = DEFAULT
    settings = settings or QSettings()
    settings.setValue(SETTINGS_KEY, name)
    settings.sync()


def system_colors() -> dict[str, str]:
    """The colours of the desktop, taken from Qt's own palette."""
    app = QGuiApplication.instance()
    if app is None:
        return dict(LIGHT_COLORS)
    palette = app.palette()
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.Text)
    alternate = palette.color(QPalette.ColorRole.AlternateBase)
    button = palette.color(QPalette.ColorRole.Button)
    highlight = palette.color(QPalette.ColorRole.Highlight)
    highlighted_text = palette.color(QPalette.ColorRole.HighlightedText)
    mid = palette.color(QPalette.ColorRole.Mid)
    dark = palette.color(QPalette.ColorRole.Dark)
    placeholder = palette.color(QPalette.ColorRole.PlaceholderText)
    return {
        "BACKGROUND": window.name(),
        "STRIPE": alternate.name(),
        "BORDER": mid.name(),
        "TEXT": text.name(),
        "TEXT_ON_ACCENT": highlighted_text.name(),
        "HINT": placeholder.name(),
        "ACCENT": highlight.name(),
        "ACCENT_HOVER": highlight.lighter(110).name(),
        "ACCENT_DISABLED": mid.name(),
        "TRACK": mid.name(),
        "HOVER": button.name(),
        "DISABLED": mid.name(),
        "REMOVE_HOVER": highlight.darker(110).name(),
        "SCROLLBAR": mid.name(),
        "SCROLLBAR_HOVER": dark.name(),
    }


def resolve(name: str) -> str:
    """Turn the chosen theme into the palette that is actually used."""
    if name == SYSTEM:
        return SYSTEM
    if name == DARK:
        return DARK
    return LIGHT


def colors_for(name: str) -> dict[str, str]:
    resolved = resolve(name)
    if resolved == SYSTEM:
        return system_colors()
    if resolved == DARK:
        return DARK_COLORS
    return LIGHT_COLORS


def apply(name: str | None = None) -> str:
    """Load the theme into the colour module before the UI is built."""
    name = name or stored_theme()
    for key, value in colors_for(name).items():
        setattr(colors, key, value)
    return resolve(name)


# The UI modules read the colours and styles while they are imported, so a
# live theme change rebuilds them (the colours module itself is updated above).
UI_MODULES = (
    "purgator.ui.styles",
    "purgator.ui.components.page",
    "purgator.ui.components.ratio_bar",
    "purgator.ui.components.ring_chart",
    "purgator.ui.components.row_delegate",
    "purgator.ui.components.switch",
    "purgator.ui.components.thin_scroll_bar",
    "purgator.ui.components",
    "purgator.ui.pages.placeholder",
    "purgator.ui.pages.cleanup",
    "purgator.ui.pages.whitelist",
    "purgator.ui.pages.applications",
    "purgator.ui.pages.schedule",
    "purgator.ui.pages.history",
    "purgator.ui.pages.overview",
    "purgator.ui.pages.settings",
    "purgator.ui.pages",
    "purgator.ui.main_window",
)


def reload_ui() -> None:
    """Re-import the pages so they pick up the colours that apply() set."""
    for name in UI_MODULES:
        module = sys.modules.get(name)
        if module is not None:
            importlib.reload(module)
