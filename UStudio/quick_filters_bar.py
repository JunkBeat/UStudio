"""Quick Filters Bar — the row under the main window's search field (main.py's init_ui()):

    [ Все файлы ▾ ][ Все типы ▾ ]      (each half of the bar's width)

* The TYPE drop-down offers «Все типы», «Изменённые», «Закладки», the user's presets
  (core/quick_filters.py's QuickFilterDef, «Настроить наборы…» edits them), every type the loaded game
  has with its row count, and «Свой выбор…» (opens the Фильтры dialog). One choice at a time: picking
  «Изменённые» shows every changed object of any type, picking a type switches «Изменённые»/«Закладки»
  off (2026-10-19, user request — as separate toggles they ANDed with the type, so seeing all changed
  objects needed «Все типы» first). Combining is the dialog's job; a combination set elsewhere shows as
  «Свой выбор (…)».
* The FILE drop-down is one file or all of them; it combines with any type entry.

Both drop-downs are a VIEW of the table proxy's filter state (allowed_types/
allowed_scripts, allowed_sources, modified_only, bookmark_matcher): a choice here writes that one dimension, and the
bar redraws itself from the proxy's `filter_state_changed` — so a filter set anywhere else (the
Фильтры dialog, «Отобразить все объекты этого типа», revealing a hidden row, a reset) always shows
here. A state no entry stands for is shown as «Свой выбор (…)» / «Несколько файлов (N)» — never as
«Все …» while the table is in fact filtered. A drop-down that filters something is outlined in the
accent colour (the `active` property, theme.py).

This replaced a row of toggle buttons (2026-10-17, user request): they were a single-choice list in
disguise that needed four width-dependent layouts and an overflow menu to fit a narrow panel."""

from core.i18n import N_, tr, trn
from collections import Counter
from typing import List, Optional, Set, Tuple

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QAbstractItemDelegate, QComboBox, QHBoxLayout, QSizePolicy, QWidget

import theme

from core.quick_filters import (
    MODIFIED_SPECIAL, QuickFilterDef, compute_source_counts, load_quick_filters, merge_active_filters,
    save_quick_filters,
)
from helpers import wrap_tooltip
from type_icons import get_action_icon, get_bookmark_icon, get_builtin_icon, get_type_icon
from gui_common import exec_and_dispose

_ALL_TYPES_LABEL = N_("Все типы")
_ALL_FILES_LABEL = N_("Все файлы")
_MODIFIED_LABEL = N_("Изменённые")
_BOOKMARKS_LABEL = N_("Закладки")

# What a type drop-down entry is (Qt.UserRole): ("all",), ("modified",), ("bookmarks",), ("custom",) — the
# state shown when no entry stands for it —, ("preset", key), ("type", name), ("pick",) «Свой выбор…»,
# ("setup",) «Настроить наборы…».
_KIND_ROLE = Qt.ItemDataRole.UserRole
# The file drop-down's data: None = all files, a source name, or _MANY_FILES for «Несколько файлов (N)».
_MANY_FILES = "\x00many"

_COMBO_MIN = 60


_EMOJI_ICON_CACHE: dict = {}


def _emoji_icon(emoji: str) -> QIcon:
    """The user's own emoji drawn into an icon, so it sits in the same icon column and has the same
    size as the type icons (as plain text in the label it pushed the label out of line)."""
    cached = _EMOJI_ICON_CACHE.get(emoji)
    if cached is not None:
        return cached
    pixmap = QPixmap(32, 32)                       # 2x, so it stays sharp on a scaled display
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    font = QFont("Segoe UI Emoji")
    font.setPixelSize(24)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    icon = QIcon(pixmap)
    _EMOJI_ICON_CACHE[emoji] = icon
    return icon


def filter_visual(definition: QuickFilterDef) -> Tuple[Optional[QIcon], str]:
    """The icon a preset shows (in the drop-down and the settings dialog): the icon the user picked (a
    built-in one, or their own symbol drawn as an icon), else automatically the icon of its first type
    (the same icons the table uses), the "edit" icon for «Изменено», else the first letters of the label."""
    key = definition.builtin_icon_key
    if key is not None:
        icon = get_builtin_icon(key)
        if icon is not None:
            return icon, ""
        # an unknown name (a newer/older build wrote it): fall back to the automatic choice below
    elif definition.icon:
        return _emoji_icon(definition.icon), ""
    if definition.special == MODIFIED_SPECIAL:
        return get_action_icon("edit"), ""
    if definition.types:
        return get_type_icon(definition.types[0]), ""
    return None, tr(definition.label)[:2]


def type_presets(definitions: List[QuickFilterDef]) -> List[QuickFilterDef]:
    """The presets the type drop-down lists: «only modified» is the bar's own toggle now, not a preset."""
    return [d for d in definitions if d.special != MODIFIED_SPECIAL]


def describe_custom_types(types: Optional[Set[str]], scripts: Optional[Set[str]],
                          modified: bool = False, bookmarked: bool = False) -> str:
    """«Свой выбор (…)» for a type/script/«Изменённые»/«Закладки» combination no drop-down entry stands for."""
    parts = []
    if types:
        names = sorted(types)
        parts.append(", ".join(names) if len(names) <= 2 else trn(len(names), "{n} тип", "{n} типа", "{n} типов"))
    if scripts:
        parts.append(trn(len(scripts), "{n} скрипт", "{n} скрипта", "{n} скриптов"))
    if modified:
        parts.append(tr("изменённые"))
    if bookmarked:
        parts.append(tr("закладки"))
    return tr("Свой выбор ({parts})", parts="; ".join(parts)) if parts else tr("Свой выбор")


class _SeparatorDelegate(QAbstractItemDelegate):
    """The type list's separators (between «Все типы», the presets, the game's types and the actions) as a
    clearly visible line with room around it — Qt's own was a faint line, invisible in the dark theme (user
    request). Every other entry is drawn by the combo's own delegate, unchanged."""
    HEIGHT = 11

    def __init__(self, inner, parent=None):
        super().__init__(parent)
        self._inner = inner

    @staticmethod
    def _is_separator(index) -> bool:
        return index.data(Qt.ItemDataRole.AccessibleDescriptionRole) == "separator"

    def paint(self, painter, option, index) -> None:
        if not self._is_separator(index):
            self._inner.paint(painter, option, index)
            return
        colors = theme.current_colors()
        color = QColor(colors.disabled_text) if colors is not None else option.palette.color(option.palette.ColorRole.Mid)
        painter.save()
        painter.setPen(QPen(color, 1))
        y = option.rect.center().y()
        painter.drawLine(option.rect.left() + 6, y, option.rect.right() - 6, y)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        if self._is_separator(index):
            return QSize(option.rect.width(), self.HEIGHT)
        return self._inner.sizeHint(option, index)


def _repolish(widget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _set_active(widget, active: bool) -> None:
    if bool(widget.property("active")) != active:
        widget.setProperty("active", active)
        _repolish(widget)


class QuickFiltersBar(QWidget):
    # «Свой выбор…» in the type drop-down: MainWindow opens the Фильтры dialog.
    open_filters_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proxy_model = None  # set via attach()
        self._theme_colors = None
        self._definitions: List[QuickFilterDef] = type_presets(load_quick_filters())
        self._type_counts: List[Tuple[str, int]] = []
        # Session-only "where was I" for the presets dialog (QuickFilterSettingsDialog.current_row).
        self._last_customize_row: int = 0
        # MainWindow sets it: () -> a fresh core.bookmarks matcher for the «Закладки» entry
        self.bookmark_matcher_provider = None

        self.setObjectName("QuickFiltersBar")
        # Fixed vertical policy: without it the parent QVBoxLayout once gave this strip 124 px instead
        # of its ~50 px size hint.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(6)

        self.type_combo = QComboBox()
        self.type_combo.setObjectName("QuickFilterCombo")
        self.type_combo.setIconSize(QSize(16, 16))
        self.type_combo.setToolTip(wrap_tooltip(
            tr("Показать объекты только этого типа или набора типов, только изменённые или только из закладок")))
        self.type_combo.activated.connect(self._on_type_activated)
        self.type_combo.setItemDelegate(_SeparatorDelegate(self.type_combo.itemDelegate(), self.type_combo))
        self.file_combo = QComboBox()
        self.file_combo.setObjectName("QuickFilterCombo")
        self.file_combo.setToolTip(wrap_tooltip(tr("Показать объекты только из выбранного файла")))
        self.file_combo.activated.connect(self._on_file_activated)
        for combo in (self.file_combo, self.type_combo):    # files first (user request)
            # Each takes half of the bar (user request, 2026-10-19): equal stretch, and a size hint that does
            # not follow the entries (a long file name must never widen the left panel — 2026-10-16 report);
            # a text that does not fit is cut with «…» by the style.
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(4)
            combo.setMinimumWidth(_COMBO_MIN)
            combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            outer.addWidget(combo, 1)

        self._rebuild_type_items()
        self._rebuild_file_items([])

    # --- wiring ---

    def attach(self, proxy_model) -> None:
        self.proxy_model = proxy_model
        proxy_model.filter_state_changed.connect(self.sync_from_proxy)
        self.sync_from_proxy()

    def apply_theme_colors(self, colors) -> None:
        # Kept for symmetry with the other panels (main.py calls it on a theme switch); the look comes
        # from theme.py's global stylesheet. Metrics can change with the theme: fit the heights again.
        self._theme_colors = colors
        self._fit_heights()

    # --- the drop-downs' contents ---

    def _rebuild_type_items(self) -> None:
        combo = self.type_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr(_ALL_TYPES_LABEL), ("all",))
        combo.addItem(get_action_icon("edit"), tr(_MODIFIED_LABEL), ("modified",))
        combo.addItem(get_bookmark_icon(), tr(_BOOKMARKS_LABEL), ("bookmarks",))
        presets = self._definitions
        if presets:
            combo.insertSeparator(combo.count())
            for d in presets:
                icon, _text = filter_visual(d)
                combo.addItem(icon if icon is not None else QIcon(), tr(d.label), ("preset", d.key))
        if self._type_counts:
            combo.insertSeparator(combo.count())
            for name, count in self._type_counts:
                combo.addItem(get_type_icon(name), f"{name} ({count:,})".replace(",", " "), ("type", name))
        combo.insertSeparator(combo.count())
        combo.addItem(tr("Свой выбор…"), ("pick",))
        combo.addItem(tr("Настроить наборы…"), ("setup",))
        combo.blockSignals(False)
        self._fit_popup(combo)
        self.sync_from_proxy()

    def _rebuild_file_items(self, data_list: list) -> None:
        combo = self.file_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr(_ALL_FILES_LABEL), None)
        for source, count in compute_source_counts(data_list):
            combo.addItem(f"{source} ({count})", source)
        combo.blockSignals(False)
        self._fit_popup(combo)

    def _sync_file_items(self, data_list: list) -> None:
        """Updates the file list in place (no clear(): that reset the popup's scroll position on every
        dependency load). The table only ever WIDENS on this path, so files are never removed mid-list."""
        combo = self.file_combo
        combo.blockSignals(True)
        if combo.count() > 1 and combo.itemData(1) == _MANY_FILES:
            combo.removeItem(1)
        i = 1  # index 0 is always «Все файлы»
        for source, count in compute_source_counts(data_list):
            label = f"{source} ({count})"
            if i < combo.count() and combo.itemData(i) == source:
                if combo.itemText(i) != label:
                    combo.setItemText(i, label)
            else:
                combo.insertItem(i, label, source)
            i += 1
        while combo.count() > i:
            combo.removeItem(combo.count() - 1)
        combo.blockSignals(False)
        self._fit_popup(combo)

    @staticmethod
    def _fit_popup(combo: QComboBox) -> None:
        """The closed combo may be narrow; its drop-down list still shows the longest entry in full."""
        metrics = combo.fontMetrics()
        longest = max((metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
        combo.view().setMinimumWidth(min(max(longest + 60, combo.width()), 700))

    def refresh_files(self, data_list: list, reset_proxy: bool = True) -> None:
        """A fresh load (or «Сбросить вид»): the type and file lists are rebuilt from the table and every
        dimension goes back to unrestricted. reset_proxy=False: the caller already cleared the proxy
        (a load does it with reset_for_new_dataset() before swapping the data in, so the proxy is not
        asked to re-filter millions of rows once more)."""
        self._type_counts = sorted(Counter(str(item.get("type", "")) for item in data_list).items())
        self._rebuild_file_items(data_list)
        self._rebuild_type_items()
        if self.proxy_model is not None and reset_proxy:
            self.proxy_model.set_type_script_filter(None, None)
            self.proxy_model.set_quick_filter_state(None, False)
        self.sync_from_proxy()

    def update_file_list(self, data_list: list) -> None:
        """Rows were ADDED (a dependency file's objects): both lists follow, nothing selected changes."""
        self._type_counts = sorted(Counter(str(item.get("type", "")) for item in data_list).items())
        self._sync_file_items(data_list)
        self._rebuild_type_items()

    # --- the proxy's state -> the bar ---

    def sync_from_proxy(self) -> None:
        """Shows the proxy's current filter state in both drop-downs."""
        proxy = self.proxy_model
        if proxy is None:
            return
        types, scripts = proxy.requested_type_script_filter()
        self._show_type_state(types, scripts, bool(proxy.modified_only),
                              getattr(proxy, "bookmark_matcher", None) is not None)
        self._show_file_state(proxy.allowed_sources)
        self._fit_heights()

    def _type_index_for(self, types, scripts, modified: bool = False, bookmarked: bool = False) -> int:
        combo = self.type_combo
        if modified or bookmarked:
            if types is not None or scripts is not None or (modified and bookmarked):
                return -1
            wanted = ("modified",) if modified else ("bookmarks",)
            # not findData(): a Python tuple stored as item data is compared by identity there
            return next((i for i in range(combo.count()) if combo.itemData(i, _KIND_ROLE) == wanted), -1)
        if types is None and scripts is None:
            return 0
        for i in range(combo.count()):
            kind = combo.itemData(i, _KIND_ROLE)
            if not kind:
                continue
            if kind[0] == "preset":
                d = next((d for d in self._definitions if d.key == kind[1]), None)
                if d is not None and merge_active_filters([d])[:2] == (types, scripts):
                    return i
            elif kind[0] == "type" and scripts is None and types == {kind[1]}:
                return i
        return -1

    def _show_type_state(self, types, scripts, modified: bool = False, bookmarked: bool = False) -> None:
        combo = self.type_combo
        combo.blockSignals(True)
        if combo.count() > 1 and (combo.itemData(1, _KIND_ROLE) or ("",))[0] == "custom":
            combo.removeItem(1)
        index = self._type_index_for(types, scripts, modified, bookmarked)
        if index < 0:
            combo.insertItem(1, describe_custom_types(types, scripts, modified, bookmarked), ("custom",))
            index = 1
        combo.setCurrentIndex(index)
        combo.blockSignals(False)
        _set_active(combo, index != 0)

    def _show_file_state(self, sources) -> None:
        combo = self.file_combo
        combo.blockSignals(True)
        if combo.count() > 1 and combo.itemData(1) == _MANY_FILES:
            combo.removeItem(1)
        if not sources:
            index = 0
        elif len(sources) == 1:
            index = combo.findData(next(iter(sources)))
        else:
            index = -1
        if index < 0:
            combo.insertItem(1, tr("Несколько файлов ({count})", count=len(sources)), _MANY_FILES)
            index = 1
        combo.setCurrentIndex(index)
        combo.blockSignals(False)
        _set_active(combo, index != 0)

    # --- heights ---

    def _fit_heights(self) -> None:
        # One height for the row: the type drop-down's icons make it 2 px taller than the file drop-down.
        height = max(self.type_combo.sizeHint().height(), self.file_combo.sizeHint().height())
        for combo in (self.type_combo, self.file_combo):
            if combo.minimumHeight() != height:
                combo.setMinimumHeight(height)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_heights()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_heights()

    # --- the user's choices -> the proxy ---

    def _on_type_activated(self, index: int) -> None:
        kind = self.type_combo.itemData(index, _KIND_ROLE) or ("all",)
        proxy = self.proxy_model
        if kind[0] in ("pick", "setup", "custom") or proxy is None:
            self.sync_from_proxy()            # an action, not a state: show the real state again
            if kind[0] == "pick":
                self.open_filters_requested.emit()
            elif kind[0] == "setup":
                self._open_customize_dialog()
            return
        types = scripts = None
        if kind[0] == "type":
            types = {kind[1]}
        elif kind[0] == "preset":
            d = next((d for d in self._definitions if d.key == kind[1]), None)
            if d is None:
                self.sync_from_proxy()
                return
            types, scripts, _modified = merge_active_filters([d])
        modified = kind[0] == "modified"
        bookmarks = kind[0] == "bookmarks"
        provider = self.bookmark_matcher_provider
        if bookmarks and provider is None:
            self.sync_from_proxy()
            return
        # Only what changes is written: each write re-filters the whole table.
        if proxy.requested_type_script_filter() != (types, scripts):
            proxy.set_type_script_filter(types, scripts)
        if bool(proxy.modified_only) != modified:
            proxy.set_quick_filter_state(proxy.allowed_sources, modified)
        if bookmarks or getattr(proxy, "bookmark_matcher", None) is not None:
            proxy.set_bookmark_filter(provider() if bookmarks else None)
        self.sync_from_proxy()

    def _on_file_activated(self, index: int) -> None:
        proxy = self.proxy_model
        source = self.file_combo.itemData(index)
        if proxy is None or source == _MANY_FILES:
            self.sync_from_proxy()
            return
        proxy.set_quick_filter_state({source} if source else None, proxy.modified_only)

    # --- presets ---

    def _open_customize_dialog(self) -> None:
        """«Настроить наборы…»: edits the presets. The table's filter is left as it is; if it was one of
        the presets that the dialog changed, the drop-down then shows it as «Свой выбор»."""
        from dialogs import QuickFilterSettingsDialog

        dialog = QuickFilterSettingsDialog(self._definitions, self, initial_row=self._last_customize_row)
        accepted = exec_and_dispose(dialog) == dialog.DialogCode.Accepted
        # Remembered on OK and Cancel alike — a session-only "where was I", not saved with the presets.
        self._last_customize_row = dialog.current_row if dialog.current_row is not None else 0
        if not accepted:
            return
        self._definitions = type_presets(dialog.get_definitions())
        save_quick_filters(self._definitions)
        self._rebuild_type_items()
