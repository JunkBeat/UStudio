"""Persists/restores the main window's user-adjustable layout — table column
widths, hidden columns, and the three splitters (MainWindow.main_splitter,
MainWindow.left_splitter, PreviewPanel.tab1_splitter) — across restarts. Same QSettings store
("UStudio", "UStudio") as config.py/theme.py, own "layout" group so keys
can't collide with either (see config.py's own comment on this convention).

Real reported request: remember the window's layout instead of resetting it
every launch, WITH a fallback safeguard — if a saved value doesn't match the
CURRENT layout shape (wrong column count, wrong number of splitter panes,
e.g. after an app update changes them), discard it outright rather than
partially applying a stale/mismatched value. Everything here is stored as a
plain comma-separated string of ints rather than a native QSettings list —
simpler to validate as a single unit before ever touching a widget, and
avoids QSettings' own list/QVariant type-coercion quirks across platforms."""

from PyQt6.QtCore import QSettings

from config import CONFIG
from app_settings import app_settings

_GROUP = "layout"


def _save_ints(settings: QSettings, key: str, values) -> None:
    settings.setValue(key, ",".join(str(v) for v in values))


def _load_ints(settings: QSettings, key: str):
    """Returns a list of ints, or None if the key is missing/empty/malformed —
    callers treat None (and any shape mismatch) as "keep whatever's already
    there", never as "apply zero/empty"."""
    raw = settings.value(key, "", type=str)
    if not raw:
        return None
    try:
        return [int(v) for v in raw.split(",")]
    except ValueError:
        return None


def _restore_splitter(settings: QSettings, key: str, splitter) -> None:
    sizes = _load_ints(settings, key)
    if sizes is not None and len(sizes) == splitter.count() and all(s >= 0 for s in sizes):
        splitter.setSizes(sizes)


def save_layout(win) -> None:
    """Note: win.table_view.columnWidth(c) reads back as 0 for a currently
    HIDDEN column (Qt's own QHeaderView behavior, not something this module
    controls) — restore_layout() knows to skip applying those particular
    entries rather than treating one hidden column as reason to discard
    every other column's saved width too."""
    settings = app_settings()
    settings.beginGroup(_GROUP)

    col_count = win.table_model.columnCount()
    settings.setValue("column_count", col_count)
    _save_ints(settings, "column_widths", (win.table_view.columnWidth(c) for c in range(col_count)))
    hidden = [c for c in range(col_count) if win.table_view.isColumnHidden(c)]
    _save_ints(settings, "hidden_columns", hidden)

    _save_ints(settings, "main_splitter", win.main_splitter.sizes())
    _save_ints(settings, "left_splitter", win.left_splitter.sizes())
    _save_ints(settings, "preview_splitter", win.preview_panel.tab1_splitter.sizes())

    settings.endGroup()


def restore_layout(win) -> None:
    settings = app_settings()
    settings.beginGroup(_GROUP)

    col_count = win.table_model.columnCount()
    # Gates BOTH column_widths and hidden_columns below — checking each of
    # those independently isn't enough of a safeguard on its own: a saved
    # hidden-columns index can still happen to fall in-bounds for a
    # DIFFERENT column layout (e.g. a column added later) and get applied
    # to the wrong column, even though the two layouts aren't really the
    # same shape at all. One explicit column_count check up front closes
    # that gap for both.
    saved_col_count = settings.value("column_count", -1, type=int)
    if saved_col_count == col_count:
        widths = _load_ints(settings, "column_widths")
        # Individual entries of <= 0 are NOT treated as invalidating the
        # whole array: Qt's own columnWidth() reports 0 for a HIDDEN column
        # (see save_layout()'s docstring note), so a real, valid save
        # routinely has a few such entries — those are just skipped
        # (leaving that one column at its default width) rather than
        # discarding every other column's perfectly good saved width too.
        if widths is not None and len(widths) == col_count:
            for c, w in enumerate(widths):
                if w > 0:
                    win.table_view.setColumnWidth(c, w)

        hidden = _load_ints(settings, "hidden_columns")
        if hidden is not None and all(0 <= c < col_count for c in hidden):
            for c in range(col_count):
                win.table_view.setColumnHidden(c, c in hidden)

    _restore_splitter(settings, "main_splitter", win.main_splitter)
    _restore_splitter(settings, "left_splitter", win.left_splitter)
    # Skipped entirely when CONFIG.show_tree_view is off — PreviewPanel.
    # apply_settings() already collapsed this splitter to hide the tree page
    # (the widget itself is also .setVisible(False), but a stale saved size
    # would otherwise still reserve blank space for it); restoring here would
    # fight that collapsed state instead of complementing it.
    if CONFIG.show_tree_view:
        _restore_splitter(settings, "preview_splitter", win.preview_panel.tab1_splitter)

    settings.endGroup()
