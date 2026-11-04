"""FiltersDialog — the main table's "Фильтры" button, next to "Сбросить вид".
Three independent checklists (object type; script name, only meaningful for
MonoBehaviour rows; and source file), each with its own Select All/Deselect All.
Type/script apply together via AdvancedFilterProxyModel.set_type_script_filter()
(object_table.py); the Файлы tab applies via set_quick_filter_state()'s
allowed_sources, the same underlying state the Quick Filters Bar's file
combobox drives (core/quick_filters.py) — so the two always agree, whichever
one the user last touched. All three compose with the existing free-text
filter rather than replacing it.

Opening fast (2026-10-18, user report; measured in the real window right after a load): Phonopolis 15.4 s,
Truck-kun 7.9 s, Lego Party 88 s before the window appeared. Two causes: every row was its own QCheckBox
(setItemWidget) — Lego's 2,743 scripts + 1,558 files took 30 + 18 s, Phonopolis' 2,017 files 1.3-3.9 s even
on later opens — and the script list reads every MonoBehaviour's script on a first open (Lego 32 s). Rows are
now plain checkable list items, and the MonoBehaviour tab is filled by a background worker that shows its
progress in the tab («Собирается список скриптов… N %») while the rest of the window is already usable."""

from core.i18n import tr
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from core.object_preview import script_checklist_entries
from core.progress import OperationCancelled
from core.quick_filters import compute_source_counts, compute_source_roots, source_roots_tooltip
from gui_workers import BackgroundWorker
from helpers import wrap_tooltip
from type_icons import get_action_icon

_VALUE_ROLE = Qt.ItemDataRole.UserRole + 1


class _ChecklistTab(QWidget):
    """One tab: a Select All/Deselect All row + a search field + a list of checkable rows.

    `items` is (value, display_label, tooltip) triples rather than bare
    strings — needed for the Файлы tab, where the row needs to SHOW
    "resources.assets (14200)" but the filter needs to MATCH plain
    "resources.assets" against each row's `source` field; the script tab
    additionally uses the tooltip slot to show the full Assembly/Namespace/
    Class identity behind a namespace-qualified label (see
    core.object_common.script_checklist_entries()). Tabs with nothing extra
    to say just pass (v, v, "") — an empty tooltip is simply never set.
    items=None: the list is filled later (set_items), set_loading() says how far it has got.

    The rows are checkable QListWidgetItems, not a QCheckBox widget per row (that cost seconds for a
    couple of thousand rows); a click anywhere on a row toggles it, as the checkbox's label did.

    `only_button=(value, caption)` adds a button that keeps ONLY that value checked (everything else is
    unchecked, whatever the search currently shows) and emits only_applied(value) — the types tab uses it
    for «Только MonoBehaviour», the one-click version of "Снять всё, find MonoBehaviour, tick it"."""

    only_applied = pyqtSignal(str)
    check_changed = pyqtSignal(str, bool)   # value, checked

    def __init__(self, items: Optional[List[Tuple[str, str, str]]], checked_values: Optional[Set[str]],
                 parent=None, only_button: Optional[Tuple[str, str]] = None):
        super().__init__(parent)
        self.items: Dict[str, QListWidgetItem] = {}   # keyed by VALUE, not display label
        self._only_button = only_button
        self._enabled = True
        self._pressed_state = None

        layout = QVBoxLayout(self)
        header_row = QHBoxLayout()
        self.btn_all = QPushButton(tr("Выбрать всё"))
        self.btn_none = QPushButton(tr("Снять всё"))
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        header_row.addWidget(self.btn_all)
        header_row.addWidget(self.btn_none)
        self.btn_only: Optional[QPushButton] = None
        if only_button is not None:
            only_value, caption = only_button
            self.btn_only = QPushButton(caption)
            self.btn_only.clicked.connect(lambda: self._set_only(only_value))
            self.btn_only.hide()
            header_row.addWidget(self.btn_only)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Real reported gap: no way to search a long checklist — a game with
        # hundreds of source files or MonoBehaviour script names made "find
        # the one I want" a manual scroll. Same live substring-filter pattern
        # QuickFilterSettingsDialog's own types list already uses.
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("Поиск..."))
        self.search_edit.textChanged.connect(self._filter_items)
        layout.addWidget(self.search_edit)

        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: gray;")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.itemPressed.connect(self._on_item_pressed)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list_widget)

        if items is None:
            self.set_loading("")
        else:
            self.set_items(items, checked_values)

    # --- filling ---

    def set_loading(self, text: str) -> None:
        """The list is not there yet: `text` says why / how far."""
        self.status_label.setText(text)
        self.status_label.show()
        self.list_widget.hide()
        for w in (self.search_edit, self.btn_all, self.btn_none):
            w.setEnabled(False)

    def set_items(self, items: List[Tuple[str, str, str]], checked_values: Optional[Set[str]]) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self.items = {}
        for value, display_label, tooltip in items:
            item = QListWidgetItem(display_label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked_values is None or value in checked_values
                               else Qt.CheckState.Unchecked)
            item.setData(_VALUE_ROLE, value)
            if tooltip:
                item.setToolTip(wrap_tooltip(tooltip))
            self.list_widget.addItem(item)
            self.items[value] = item
        self.list_widget.blockSignals(False)
        if self.btn_only is not None:
            self.btn_only.setVisible(self._only_button[0] in self.items)
        self.list_widget.show()
        if items:
            self.status_label.hide()
        else:
            self.status_label.setText(tr("Нет доступных значений."))
            self.status_label.show()
        self.search_edit.setEnabled(bool(items))
        for w in (self.btn_all, self.btn_none):
            w.setEnabled(True)
        self.list_widget.setEnabled(self._enabled)
        if self.search_edit.text():
            self._filter_items(self.search_edit.text())

    # --- state ---

    def is_checked(self, value: str) -> bool:
        return self.items[value].checkState() == Qt.CheckState.Checked

    def set_checked(self, value: str, checked: bool) -> None:
        self.items[value].setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def selected(self) -> Set[str]:
        return {value for value, item in self.items.items() if item.checkState() == Qt.CheckState.Checked}

    def set_enabled_all(self, enabled: bool):
        self._enabled = enabled
        self.list_widget.setEnabled(enabled)

    # --- interaction ---

    def _on_item_pressed(self, item: QListWidgetItem) -> None:
        self._pressed_state = (item, item.checkState())

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        # A click on the indicator has already toggled the row; a click on its text has not.
        pressed, self._pressed_state = self._pressed_state, None
        if pressed is not None and pressed[0] is item and item.checkState() == pressed[1]:
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        self.check_changed.emit(item.data(_VALUE_ROLE), item.checkState() == Qt.CheckState.Checked)

    def _shown_values(self) -> List[str]:
        """Values of the rows the search currently shows, in list order."""
        return [value for value, item in self.items.items() if not item.isHidden()]

    def _on_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is not None:
            self.copy_menu(item.data(_VALUE_ROLE)).exec(self.list_widget.viewport().mapToGlobal(pos))

    def copy_menu(self, value: str) -> QMenu:
        """The right-click menu of one row (built, not shown — the caller execs it)."""
        menu = QMenu(self)
        copy_icon = get_action_icon("copy")
        clipboard = QApplication.clipboard()
        act_value = menu.addAction(copy_icon, tr("Копировать значение"))
        act_value.triggered.connect(lambda: clipboard.setText(value))
        shown = self._shown_values()
        if len(shown) > 1:
            act_all = menu.addAction(copy_icon, tr("Копировать все показанные ({count})", count=len(shown)))
            act_all.triggered.connect(lambda: clipboard.setText("\n".join(shown)))
        return menu

    def _filter_items(self, text: str) -> None:
        needle = text.strip().lower()
        for item in self.items.values():
            item.setHidden(bool(needle) and needle not in item.text().lower())
        self.list_widget.scrollToTop()

    def _set_all(self, checked: bool):
        # Only touches VISIBLE (search-matched) rows — "select all" while a search narrows the list should
        # mean "all of what I'm looking at", not silently also toggling hundreds of hidden, unrelated entries.
        for value, item in self.items.items():
            if not item.isHidden():
                self.set_checked(value, checked)

    def _set_only(self, value: str) -> None:
        # Unlike _set_all this ignores the search: it is a preset ("only X"), and leaving a hidden row
        # checked would silently break exactly that.
        for key in self.items:
            self.set_checked(key, key == value)
        self.only_applied.emit(value)


class FiltersDialog(QDialog):
    def __init__(
        self, data_list: list,
        current_allowed_types: Optional[Set[str]], current_allowed_scripts: Optional[Set[str]],
        current_allowed_sources: Optional[Set[str]] = None,
        parent=None, keep_busy: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("Фильтры"))
        self.resize(370, 480)
        self._current_allowed_scripts = current_allowed_scripts
        self._script_worker: Optional[BackgroundWorker] = None
        self._cancel_scripts = False
        self.scripts_ready = False
        self._data_list = data_list
        # MainWindow's UserActivityTracker.touch: while the list is built the background passes of a load
        # (usage index, name warm-up) stay paused - they and the list read the same objects and slowed each
        # other down; a click pauses them for only 0.6 s.
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(200)
        if keep_busy is not None:
            self._busy_timer.timeout.connect(keep_busy)

        types = sorted({str(item.get("type", "")) for item in data_list})
        # Tooltip: which root file (bundle / archive / loose file) each source entry came from.
        roots = compute_source_roots(data_list)
        files = [(source, f"{source} ({count})", source_roots_tooltip(roots.get(source, [])))
                 for source, count in compute_source_counts(data_list)]

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.tabs = tabs
        self.type_tab = _ChecklistTab([(t, t, "") for t in types], current_allowed_types, self,
                                      only_button=("MonoBehaviour", tr("Только MonoBehaviour")))
        self.script_tab = _ChecklistTab(None, current_allowed_scripts, self)
        self.files_tab = _ChecklistTab(files, current_allowed_sources, self)
        tabs.addTab(self.type_tab, tr("Типы объектов"))
        tabs.addTab(self.script_tab, "MonoBehaviour")
        tabs.addTab(self.files_tab, tr("Файлы"))
        layout.addWidget(tabs)

        # The script tab only means anything once MonoBehaviour rows can appear
        # at all — greyed out otherwise so it doesn't look like an independent
        # "MonoBehaviour name" filter that's separate from the type checkbox.
        # «Только MonoBehaviour» leaves only that type on and goes straight to where the scripts are chosen.
        self.type_tab.only_applied.connect(self._on_only_type)
        if "MonoBehaviour" in self.type_tab.items:
            self.type_tab.check_changed.connect(self._on_type_checked)
            self.script_tab.set_enabled_all(self.type_tab.is_checked("MonoBehaviour"))
        else:
            self.script_tab.set_enabled_all(False)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Применить"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if any(item.get("type") == "MonoBehaviour" for item in data_list):
            self.script_tab.set_loading(tr("Собирается список скриптов… 0 %"))
        else:
            self._on_scripts_built([])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Started once the window is on screen: started earlier, the worker held up the window's first paint
        # by ~2 s (Phonopolis, right after a load).
        if not self.scripts_ready and self._script_worker is None and not self._cancel_scripts:
            QTimer.singleShot(0, self._start_script_list)

    # --- the script list, built in the background ---

    def _start_script_list(self) -> None:
        if self.scripts_ready or self._script_worker is not None or self._cancel_scripts:
            return
        data_list = self._data_list
        last_rest = [time.perf_counter()]

        def cancelled_or_rest() -> bool:
            # The same pacing as the usage index: a thread reading objects in plain Python starves the GUI
            # thread of the GIL unless it lets go now and then (time.sleep(0) is not enough on Windows).
            now = time.perf_counter()
            if now - last_rest[0] >= 0.010:
                time.sleep(0.001)
                last_rest[0] = time.perf_counter()
            return self._cancel_scripts

        def build(report):
            return script_checklist_entries(data_list, progress=lambda done, total: report("", done, total),
                                            should_cancel=cancelled_or_rest)
        worker = BackgroundWorker(build, parent=self)
        worker.progress_signal.connect(self._on_scripts_progress)
        worker.succeeded_signal.connect(self._on_scripts_built)
        worker.failed_signal.connect(self._on_scripts_failed)
        self._script_worker = worker
        self._busy_timer.start()
        worker.start()

    def _on_scripts_progress(self, _phase, done, total) -> None:
        if self.scripts_ready or not total:
            return
        self.script_tab.set_loading(tr("Собирается список скриптов… {value} %", value=int(done * 100 / total)))

    def _on_scripts_built(self, entries) -> None:
        self._busy_timer.stop()
        if self._cancel_scripts:
            return
        self.scripts_ready = True
        self.script_tab.set_items(entries, self._current_allowed_scripts)

    def _on_scripts_failed(self, message: str) -> None:
        self._busy_timer.stop()
        if self._cancel_scripts or message == str(OperationCancelled()):
            return
        self.script_tab.set_loading(tr("Не удалось собрать список скриптов: {message}", message=message))

    def wait_for_scripts(self, timeout_ms: int = 60000) -> bool:
        """Blocks until the script list is in the tab (tests; nothing in the app needs it)."""
        if not self.scripts_ready and self._script_worker is None:
            self._start_script_list()          # never shown (a test): start it now
        worker = self._script_worker
        if worker is not None:
            worker.wait(timeout_ms)
            QApplication.processEvents()
        return self.scripts_ready

    def _stop_script_list(self) -> None:
        self._cancel_scripts = True
        self._busy_timer.stop()
        worker, self._script_worker = self._script_worker, None
        if worker is not None:
            worker.wait()     # it reads the game's objects: never leave it running behind the dialog

    def done(self, result: int) -> None:
        self._stop_script_list()
        super().done(result)

    # --- the rest ---

    def _on_type_checked(self, value: str, checked: bool) -> None:
        if value == "MonoBehaviour":
            self.script_tab.set_enabled_all(checked)

    def _on_only_type(self, value: str) -> None:
        if value == "MonoBehaviour":
            self.tabs.setCurrentWidget(self.script_tab)
            self.script_tab.search_edit.setFocus()

    def get_selected_types(self) -> Set[str]:
        return self.type_tab.selected()

    def get_selected_scripts(self) -> Set[str]:
        return self.script_tab.selected()

    def get_selected_sources(self) -> Set[str]:
        return self.files_tab.selected()

    def all_types(self) -> Set[str]:
        return set(self.type_tab.items)

    def all_scripts(self) -> Set[str]:
        return set(self.script_tab.items)

    def all_sources(self) -> Set[str]:
        return set(self.files_tab.items)
