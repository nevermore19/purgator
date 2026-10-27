"""Style sheets shared by the pages."""

from purgator.ui.colors import (
    ACCENT,
    ACCENT_DISABLED,
    ACCENT_HOVER,
    BACKGROUND,
    BORDER,
    DISABLED,
    HOVER,
    TEXT,
)

# The look of the result lists
TREE_STYLE = (
    f"QTreeWidget {{ background: {BACKGROUND}; border: none; outline: none;"
    " font-size: 13px; }"
    "QTreeWidget::item { padding: 3px 2px; }"
    f"QTreeWidget::item:selected {{ background: transparent; color: {TEXT}; }}"
    f"QHeaderView::section {{ background: transparent; color: {ACCENT};"
    f" border: none; border-bottom: 1px solid {BORDER}; padding: 2px 6px 4px 6px;"
    " font-size: 13px; font-weight: 600; }"
)

# The two kinds of buttons: the plain one and the one that does the work
PLAIN_BUTTON_STYLE = (
    f"QPushButton {{ background-color: {BACKGROUND}; color: {ACCENT};"
    f" border: 1px solid {ACCENT}; border-radius: 15px;"
    " padding: 4px 22px; font-size: 18px; }"
    f"QPushButton:hover {{ background-color: {HOVER}; }}"
    f"QPushButton:disabled {{ color: {DISABLED}; border-color: {DISABLED}; }}"
)

PRIMARY_BUTTON_STYLE = (
    f"QPushButton {{ background-color: {ACCENT}; color: {BACKGROUND};"
    f" border: 1px solid {ACCENT}; border-radius: 15px;"
    " padding: 4px 22px; font-size: 18px; }"
    f"QPushButton:hover {{ background-color: {ACCENT_HOVER}; }}"
    f"QPushButton:disabled {{ background-color: {ACCENT_DISABLED}; border-color: {ACCENT_DISABLED}; }}"
)

# The line of text next to the buttons at the top of a page
INFO_LABEL_STYLE = f"font-size: 19px; color: {TEXT}; background: transparent;"

# The title inside a rounded box
BOX_TITLE_STYLE = f"font-size: 16px; font-weight: 600; color: {TEXT};"


def box_style(name: str) -> str:
    """A rounded box with a thin border; its labels have no background of their own."""
    return (
        f"QFrame#{name} {{ background-color: {BACKGROUND};"
        f" border: 1px solid {BORDER}; border-radius: 15px; }}"
        "QLabel { background: transparent; border: none; }"
    )
