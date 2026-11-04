"""The main object table's Qt model (rows, sorting, lazy name/script reading, the background name warm-up)
and UserActivityTracker — split out of object_table.py (mechanical move, no logic changes). The filter
proxies are in table_proxy_index.py / table_proxy_legacy.py, the shared row predicate in table_filter.py;
object_table.py re-exports all of it under the old names."""

from core.i18n import tr
import atexit
import os
import threading
import time
import weakref
from typing import Callable, List, Optional

import numpy as np
from PyQt6.QtCore import (
    QEvent, QObject, QThread, Qt,
    QAbstractTableModel, QModelIndex, QTimer, pyqtSignal,
)

from config import RowItem
from core.file_utils import format_size
from core.object_preview import ROW_FIELD_UNRESOLVED, get_row_name, get_row_script_name
from core.progress import ProgressThrottle
from core.table_index import ColumnStore
from gui_workers import BackgroundWorker
from type_icons import get_bookmarked_type_icon, get_type_icon


class UserActivityTracker(QObject):
    """Remembers WHEN the user last did something (wheel, key, mouse button) so background work can keep out
    of the way of scrolling and typing. Installed on the application; the filter body is deliberately trivial
    (it sees every event) and ignores mouse moves, which are constant while the pointer merely rests over the
    window. A scrollbar drag is reported through touch() (its valueChanged), since dragging produces only
    mouse moves.

    Install it with attach(app), not app.installEventFilter() directly. A Python event filter left installed
    on the QApplication is called by Qt for events delivered while the interpreter shuts down, when the Python
    side is half torn down: that crashed the process with an access violation at exit (found as a flaky
    segfault at the end of tests/test_advanced_ui.py, 4 of 8 runs; 0 of 30 once the filter is removed first).
    A `sys.is_finalizing()` guard inside eventFilter does NOT help (18 of 30 still crashed). attach() therefore
    also registers the removal with atexit (it runs while Python is still fully alive); detach() does the same
    explicitly, for a window that is closed."""

    _INPUT_EVENTS = frozenset({
        QEvent.Type.Wheel, QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
    })

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last = 0.0

    def attach(self, app) -> None:
        """Install as an application-wide event filter and make sure it is removed again before the
        interpreter starts to shut down."""
        self._app = app
        app.installEventFilter(self)
        ref = weakref.ref(self)

        def _remove_at_exit() -> None:
            tracker = ref()
            if tracker is not None:
                tracker.detach()

        atexit.register(_remove_at_exit)

    def detach(self) -> None:
        app = getattr(self, "_app", None)
        if app is not None:
            self._app = None
            try:
                app.removeEventFilter(self)
            except RuntimeError:     # the QObject is already gone
                pass

    def touch(self, *_args) -> None:
        self._last = time.monotonic()

    def busy(self, within_s: float = 0.6) -> bool:
        return time.monotonic() - self._last < within_s

    def eventFilter(self, obj, event) -> bool:
        if event.type() in self._INPUT_EVENTS:
            self._last = time.monotonic()
        return False


class ObjectTableModel(QAbstractTableModel):
    _SORT_KEYS = ("name", "container_path", "script_name", "type", "source", "path_id", "size")

    # Column 7 ("Изменено"/Modified) isn't in here — it's not a static field on
    # RowItem but a live check of the underlying UnityPy object (see data()/sort()
    # below), so it doesn't fit the simple "look up this dict key" pattern the
    # other columns share.
    _MODIFIED_COL = 7

    # Same status-reporting shape as AdvancedFilterProxyModel's own
    # resolve_started/resolve_progress/resolve_finished (object_table.py, this
    # module) — see sort()'s own docstring for why this exists. Kept as its own,
    # separate mechanism rather than refactored to share one helper class with
    # the proxy model's already-verified-working version, to avoid touching
    # tested code for a small amount of duplication.
    resolve_started = pyqtSignal()
    resolve_progress = pyqtSignal(int, int)
    resolve_finished = pyqtSignal()
    # What the pass behind these signals resolves, for the status line: "names" or "scripts" (the sort column).
    resolve_kind = "names"

    def __init__(self, data_list: Optional[List[RowItem]] = None):
        super().__init__()
        self.data_list: List[RowItem] = data_list or []
        # «Закладки»: core.bookmarks matcher (row -> bookmarked?) — a bookmarked row's icon gets a star; None = none
        self.bookmark_matcher = None
        self.headers = [
            tr("Имя"), tr("Путь в контейнере"), tr("Скрипт"), tr("Тип"), tr("Источник"), "PathID", tr("Размер"), tr("Изменено"),
        ]
        self._sort_resolve_worker = None
        self._pending_sort = None  # (column, order) to apply once resolution finishes
        self._sort_placeholder_shown = False
        # The actual list.sort() itself (see _apply_sort()) — bumped by every new
        # sort request AND by replace_data()/append_rows(), so a stale background
        # sort's result (superseded by a newer sort, or by the dataset itself
        # changing underneath it) is discarded instead of applied.
        self._sort_generation = 0
        self._sort_worker = None
        # Set by the proxy: () -> the rows currently passing its filter. A Имя/Скрипт sort
        # only has to READ the names of rows the user can see; the rest sort as "" until
        # a filter change shows them (resort_if_needed()).
        self._visible_provider = None
        self._active_name_sort = None  # (column, order) while sorted by Имя/Скрипт
        # Category codes of the type/source columns for data_list's CURRENT order, built lazily on the
        # first filter (core/table_index.py). Replaced — never edited — whenever the rows change, see
        # column_store(). _cols_epoch counts in-place edits so a background sort's permuted copy can
        # tell it was derived from older data.
        self._cols = ColumnStore()
        self._cols_epoch = 0
        # Set ONLY while a finished sort's reset is being signalled (see _on_sort_worker_done): the
        # permutation new_rows[j] = old_rows[perm[j]], so a proxy can carry its visible-row index over to
        # the new order in O(n) instead of re-evaluating the whole filter.
        self.reset_permutation = None
        # Background name/script warm-up (see start_name_warmup()). _warm_gen invalidates a running pass
        # (dataset replaced / a newer start); _warm_pos/_warm_epoch are touched by the worker AND the GUI
        # thread (a finished sort swaps data_list for a reordered copy), hence the lock.
        self._warm_worker = None
        self._warm_gen = 0
        self._warm_pos = 0
        self._warm_epoch = 0
        self._warm_lock = threading.Lock()
        self._warm_restart = False
        self._warm_last_work_s = 0.004
        # Set by the window: () -> True while the user is busy (scrolling, typing, a heavier job running)
        # and the warm-up should keep out of the way.
        self.warmup_should_pause: Optional[Callable[[], bool]] = None
        # Bumped by stop_background_reads(): a running sort-resolve pass sees it at its next row and ends.
        self._sort_resolve_gen = 0
        self._interrupted_sort = None   # (column, order) a stop cut off; resume_background_reads() sorts again

    def rowCount(self, parent=QModelIndex()): return len(self.data_list)
    def columnCount(self, parent=QModelIndex()): return len(self.headers)

    @staticmethod
    def _is_modified(item: RowItem) -> bool:
        # ObjectReader.data starts out None and is only ever set by patch()/
        # save_typetree()/set_raw_data() (edit-in-place, JSON import, etc.) — so
        # "has been edited but not yet saved" is exactly "data is not None",
        # already tracked by UnityPy itself. Checked live (not cached on the row)
        # since it can flip mid-session and object_actions._refresh_row_after_patch
        # already emits dataChanged for the whole row whenever that happens.
        return item["obj_ref"].data is not None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.data_list)): return None
        item = self.data_list[index.row()]
        col = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            # get_row_name()/get_row_script_name() lazily resolve+memoize on
            # first access — see core/loader.py's build_row_item() and
            # core/object_preview.py's own comment on why these two fields
            # specifically are deferred instead of computed eagerly at load.
            if col == 0: return get_row_name(item)
            if col == 1: return item["container_path"]
            if col == 2: return get_row_script_name(item)
            if col == 3: return item["type"]
            if col == 4: return item["source"]
            if col == 5: return item["path_id"]
            # format_size() only changes the DISPLAY string — sort() below still
            # sorts by the raw stored int, same "CAB viewer" pattern
            # dialogs/cab_browser_dialog.py's NumericTableWidgetItem already uses.
            if col == 6: return format_size(item["size"])
            if col == self._MODIFIED_COL: return "*" if self._is_modified(item) else ""
        elif role == Qt.ItemDataRole.DecorationRole and col == 0:
            # Real reported request: an intuitive per-type icon in the first
            # column, UABEA-inspired (not a pixel copy — this project has no
            # icon assets at all, see type_icons.py's own docstring for why
            # these are drawn procedurally instead). get_type_icon() caches
            # by type name, so this stays O(1) per row after the first hit
            # for each type — matters at hard-case object counts where
            # data() gets called for every visible cell on every repaint.
            matcher = self.bookmark_matcher
            if matcher is not None and matcher(item):
                return get_bookmarked_type_icon(item["type"])
            return get_type_icon(item["type"])
        elif role == Qt.ItemDataRole.ToolTipRole and col in (0, 1, 2, 4):
            # Name, Container Path, Script (namespaced class names run long), and
            # Source are all routinely narrower than their actual content — full
            # text on hover instead of only whatever fits the column's usual width.
            if col == 0: return get_row_name(item)
            if col == 1: return item["container_path"]
            if col == 2: return get_row_script_name(item)
            return item["source"]
        elif role == Qt.ItemDataRole.TextAlignmentRole and col == self._MODIFIED_COL:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def column_store(self) -> ColumnStore:
        """The type/source category codes for the current rows, built on first use (~0.1 s per 300k rows
        — paid once, by the first filter, not by every load)."""
        if not self._cols.matches(self.data_list):
            self._cols = ColumnStore.build(self.data_list)
        return self._cols

    def refresh_column_store(self, first: int, last: int) -> None:
        """Rows first..last were edited in place: re-read their type/source codes if those changed."""
        if self._cols.matches(self.data_list):
            updated = self._cols.updated(self.data_list, first, last)
            if updated is not self._cols:
                self._cols = updated
                self._cols_epoch += 1

    def replace_data(self, data_list: List[RowItem]) -> None:
        """Swaps in a completely different dataset — the ONLY correct way to do
        that for this model. A load/reload/CAB-entry switch used to do
        `model.data_list = rows; model.layoutChanged.emit()` (MainWindow, three
        places), which is invalid Qt: layoutChanged is the second half of a
        layoutAboutToBeChanged/layoutChanged pair meaning "the SAME rows were
        rearranged", and here the row count and every row's identity change. The
        QSortFilterProxyModel above this model keeps a per-row source<->proxy
        mapping and the view's selection model keeps persistent indexes, all
        built for the OLD rows, and neither is told to drop them — so the next
        touch of a stale index (clearCurrentIndex(), a repaint, the next
        selection change) reads past the end of a mapping: a native Windows
        access violation, no Python exception, nothing but crash.log. Confirmed
        by a headless repro against this very model + AdvancedFilterProxyModel +
        QTableView (a few reload cycles with rows selected far down the list
        crash every time); the same loop through this method never does.

        beginResetModel()/endResetModel() tells the proxy and the selection
        model "everything is new", the same call _apply_sort() already uses for
        the same reason — and, as a bonus, drops the selection/current index
        the way a wholesale dataset change should."""
        # Invalidates any sort still running in the background (see
        # _apply_sort()) — its eventual result is a sorted snapshot of the OLD
        # data_list, which must never land on top of a freshly loaded one.
        self._sort_generation += 1
        self.stop_name_warmup()  # a running warm-up described the old rows
        self._interrupted_sort = None
        self.beginResetModel()
        self.data_list = data_list
        self._cols = ColumnStore()
        self._cols_epoch += 1
        self.endResetModel()

    def append_rows(self, new_items: List[RowItem]) -> None:
        """Adds rows without disturbing the existing ones — used by MainWindow's
        "load this dependency file's objects into the table" action (see
        _load_dependency_into_table), where the whole point is NOT resetting
        the table (current selection/scroll position/sort order for already-
        present rows must survive). beginInsertRows()/endInsertRows() tells the
        proxy model exactly what changed instead of beginResetModel()'s
        "everything changed, just rebuild" — which would drop the current
        selection and scroll position, the one thing this method exists to
        avoid."""
        if not new_items:
            return
        # Same reasoning as replace_data() — a background sort in flight is
        # working from a snapshot taken BEFORE these rows existed; applying it
        # now would silently drop the newly appended rows from the table.
        self._sort_generation += 1
        start = len(self.data_list)
        end = start + len(new_items) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        # Extend the codes BEFORE the rows signal goes out (endInsertRows): the proxy filters the new
        # rows when it hears about them and needs the store to already describe them.
        extended = self._cols.extended(new_items) if self._cols.built and self._cols.count == start else ColumnStore()
        self.data_list.extend(new_items)
        self._cols = extended
        self._cols_epoch += 1
        self.endInsertRows()

    def find_row(self, item: RowItem) -> Optional[int]:
        """Row index of `item` in data_list, or None if it's not (or no longer) in
        the model — an accessor instead of callers reaching into data_list directly
        (e.g. via .index()), which leaks the model's internal storage to its callers."""
        try:
            return self.data_list.index(item)
        except ValueError:
            return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder, visible_provider=None):
        """Real, measured bug (not the locking fix — this is independent of it,
        confirmed via cProfile against a real 253,597-row Truck-kun table):
        sorting by Имя or Скрипт used to call get_row_name()/get_row_script_name()
        — both lazily-resolved, see their own docstrings — for EVERY row inline,
        synchronously, inside this one call. On that real fixture this measured
        2.0-3.0s of a fully frozen GUI thread on the FIRST sort by either column
        (a warm re-sort afterward, already memoized, is back down to ~60-70ms) —
        the exact same shape of bug set_type_script_filter() above already had
        for a script-restricted Quick Filter, just triggered by clicking a
        column header instead of a filter button. At this project's own
        documented hard-case scale (tens of millions of objects) this would be
        tens of seconds of a frozen window, not a couple.

        Fix: same background-resolve-then-actually-sort deferral as
        set_type_script_filter() — see that method's own docstring for the full
        reasoning (this is deliberately a SEPARATE, smaller copy of the same
        shape rather than a shared refactor, so as not to touch that
        already-verified code for the sake of a little duplication)."""
        # Real confirmed bug: QTableView.setSortingEnabled(True) calls
        # proxy.sort(-1, AscendingOrder) to mean "no column sorted" (matching
        # the header's own sortIndicatorSection()==-1 "unset" state) — the
        # old `column < len(self._SORT_KEYS)` check let column=-1 slip
        # through via Python's negative-index wraparound, silently sorting by
        # self._SORT_KEYS[-1] (the LAST entry, "size") every time sorting was
        # (re-)enabled — confirmed via direct instrumentation: every fresh
        # load's table came out ascending-by-size, not in load order, with no
        # visible sort indicator anywhere to explain why. `0 <=` closes the
        # gap: any negative column now falls through to the same "not a real
        # column" `else: return` the _MODIFIED_COL branch already had.
        if visible_provider is not None:
            self._visible_provider = visible_provider
        self._active_name_sort = None
        if 0 <= column < len(self._SORT_KEYS):
            key = self._SORT_KEYS[column]
            if key in ("name", "script_name"):
                resolver = get_row_name if key == "name" else get_row_script_name
                # Real reported gap: with a filter on (say Fonts) and their names already
                # read, sorting by Имя still showed "reading names/scripts" — it resolved
                # EVERY row of the table, hidden ones included, though only the visible
                # rows' order can be seen. Only rows that pass the current filter are
                # resolved now; a hidden, still-unresolved row sorts as "" and is
                # resolved later, if a filter change ever shows it (resort_if_needed()).
                scope = self._visible_provider() if self._visible_provider is not None else self.data_list
                unresolved = [item for item in scope if item[key] is ROW_FIELD_UNRESOLVED]
                if unresolved:
                    self._pending_sort = (column, order)
                    self._start_sort_resolve_worker(unresolved, resolver)
                    return
                self._active_name_sort = (column, order)
                key_func = lambda item, r=resolver, k=key: "" if item[k] is ROW_FIELD_UNRESOLVED else r(item)
            else:
                key_func = lambda item: item[key]
        elif column == self._MODIFIED_COL:
            key_func = self._is_modified
        else:
            return
        self._pending_sort = None
        self._apply_sort(key_func, order)

    def resort_if_needed(self) -> None:
        """Called by the proxy after its filter changed: when the table is sorted by
        Имя/Скрипт and the change made still-unresolved rows visible, sort again so
        they get their names read and land where they belong."""
        if self._active_name_sort is None or self._visible_provider is None or self._sort_resolve_worker is not None:
            return
        column, order = self._active_name_sort
        key = self._SORT_KEYS[column]
        if any(item[key] is ROW_FIELD_UNRESOLVED for item in self._visible_provider()):
            self.sort(column, order)

    def _apply_sort(self, key_func, order) -> None:
        reverse = order == Qt.SortOrder.DescendingOrder

        # Real reported request: a warm re-sort is already fast (~60-70ms for a
        # real 253,597-row table, per this method's own measured history), but
        # at this project's documented hard-case scale (tens of millions of
        # objects) the same call runs into whole seconds of a frozen GUI
        # thread — and, the actual complaint, the user has no way to change
        # their mind mid-sort; clicking a different column just queues up
        # behind whichever one is already running.
        #
        # The actual list.sort() has nothing to do with Qt, so it's safe to do
        # off the GUI thread — sorted() (not the previous in-place .sort())
        # works from a SNAPSHOT of data_list, never touching the live list a
        # concurrent repaint/read might still be looking at, and the result is
        # only ever swapped in back on the GUI thread once it's ready.
        # "Cancel and restart": the exact same discard-stale-result shape
        # _start_sort_resolve_worker() above already uses one level up
        # (resolving names before this even runs) — a generation counter,
        # bumped by every new sort request AND by replace_data()/append_rows()
        # (so a reload or an appended dependency mid-sort can't have its rows
        # silently clobbered by a now-stale sorted snapshot). A result whose
        # generation no longer matches when it completes is simply discarded;
        # nothing needs to actually stop the old sorted() call early — it's
        # cheap enough to just let it finish and throw the answer away.
        self._sort_generation += 1
        generation = self._sort_generation
        snapshot = list(self.data_list)
        cols_snapshot = self._cols if self._cols.matches(snapshot) else None
        epoch = self._cols_epoch

        def fn(_report_progress):
            # Sort row NUMBERS by the precomputed keys (an identical, stable ordering to sorting the
            # rows themselves), so the same permutation can reorder the filter codes: the GUI thread
            # then installs rows + codes together and never has to rebuild the codes row by row.
            keys = [key_func(item) for item in snapshot]
            order = sorted(range(len(snapshot)), key=keys.__getitem__, reverse=reverse)
            result = [snapshot[i] for i in order]
            return (result, (cols_snapshot.permuted(order) if cols_snapshot is not None else None), epoch,
                    np.asarray(order, dtype=np.int64))

        worker = BackgroundWorker(fn, parent=self)
        self._sort_worker = worker
        worker.succeeded_signal.connect(lambda payload, g=generation: self._on_sort_worker_done(g, payload))
        # A key_func raising (shouldn't happen — every _SORT_KEYS entry is a
        # plain dict lookup or an already-exercised resolver) would otherwise
        # be silently swallowed by BackgroundWorker's own try/except; re-raise
        # on the GUI thread instead so it still reaches crash_log.py's own
        # excepthook-based safety net, same as the old synchronous call's
        # exception would have.
        worker.failed_signal.connect(self._on_sort_worker_failed)
        worker.finished.connect(lambda w=worker: self._on_sort_worker_finished(w))
        worker.start()

    def _on_sort_worker_done(self, generation: int, payload) -> None:
        if generation != self._sort_generation:
            return  # superseded by a newer sort, or the dataset itself changed — discard
        # payload: (rows, permuted store or None, epoch the store was derived at); a bare list (the
        # old shape) still works and simply leaves the store to be rebuilt on demand.
        perm = None
        if isinstance(payload, tuple):
            result, store, epoch = payload[:3]
            perm = payload[3] if len(payload) > 3 else None
        else:
            result, store, epoch = payload, None, -1
        # beginResetModel/endResetModel instead of layoutAboutToBeChanged/layoutChanged:
        # layoutChanged without an explicit changePersistentIndex mapping (we don't build one —
        # the list is fully re-sorted from scratch) forces QSortFilterProxyModel down the
        # heavier path of "try to preserve persistent indices over the new
        # order", and that — not the by-key sort itself — remained the bottleneck with
        # an active filter: the filter in filterAcceptsRow is already fast, but rebuilding
        # the mapping on top of layoutChanged was still expensive. Reset tells the proxy
        # plainly "everything changed, just rebuild" — cheaper and more correct for a full
        # re-sort.
        self.beginResetModel()
        self.data_list = result
        # An in-place edit that landed while the sort ran makes the permuted copy older than the data:
        # drop it (rebuilt lazily) rather than risk a stale code.
        self._cols = store if (store is not None and epoch == self._cols_epoch) else ColumnStore()
        with self._warm_lock:
            self._warm_epoch += 1
            self._warm_pos = 0  # the rows moved: scan again from the top (resolved rows are skipped cheaply)
        self.reset_permutation = perm  # valid whenever the generation matched: same rows as the snapshot
        try:
            self.endResetModel()
        finally:
            self.reset_permutation = None

    @staticmethod
    def _on_sort_worker_failed(message: str) -> None:
        raise RuntimeError(f"Не удалось отсортировать таблицу: {message}")  # i18n: keep (crash log)

    def _on_sort_worker_finished(self, worker) -> None:
        if worker is self._sort_worker:
            self._sort_worker = None
        worker.deleteLater()

    def _start_sort_resolve_worker(self, unresolved: list, resolver) -> None:
        if self._sort_resolve_worker is not None:
            # Already running — it re-scans for unresolved rows (fresh, not from
            # this stale list) via _on_sort_resolve_done() -> sort() once it
            # finishes, so a newer sort request is still honored correctly.
            return
        self._sort_placeholder_shown = False
        self.resolve_kind = "names" if resolver is get_row_name else "scripts"
        QTimer.singleShot(_RESOLVE_PLACEHOLDER_DELAY_MS, self._maybe_announce_sort_resolve_started)

        gen = self._sort_resolve_gen

        def fn(report_progress):
            total = len(unresolved)
            throttle = ProgressThrottle()
            for i, item in enumerate(unresolved):
                if self._sort_resolve_gen != gen:
                    return None  # stopped: the loaded files are about to be released (stop_background_reads)
                resolver(item)  # resolves + memoizes in place
                if throttle.should_report(i, total):
                    report_progress("", i + 1, total)
                    throttle.pause()
            return None

        worker = BackgroundWorker(fn, parent=self)
        self._sort_resolve_worker = worker
        worker.progress_signal.connect(self._on_sort_resolve_progress)
        worker.succeeded_signal.connect(self._on_sort_resolve_done)
        worker.failed_signal.connect(self._on_sort_resolve_done)
        worker.finished.connect(lambda w=worker: self._on_sort_resolve_worker_finished(w))
        worker.start()

    def _maybe_announce_sort_resolve_started(self) -> None:
        if self._sort_resolve_worker is not None and not self._sort_placeholder_shown:
            self._sort_placeholder_shown = True
            self.resolve_started.emit()

    def _on_sort_resolve_progress(self, _phase: str, current, total) -> None:
        if self._sort_placeholder_shown:
            self.resolve_progress.emit(current, total)

    def _on_sort_resolve_done(self, *_args) -> None:
        if self._sort_placeholder_shown:
            self.resolve_finished.emit()
        pending = self._pending_sort
        self._pending_sort = None
        if pending is not None:
            # Re-enter through sort() (not a direct _apply_sort() call) so a
            # newly-appeared unresolved row (unlikely mid-sort, but possible —
            # a dependency file finishing its own load) gets a second pass
            # instead of silently being left unresolved.
            self.sort(*pending)

    def _on_sort_resolve_worker_finished(self, worker) -> None:
        if worker is self._sort_resolve_worker:
            self._sort_resolve_worker = None
        worker.deleteLater()

    # ------------------------------------------------------------------ background warm-up
    # Reading the names/scripts of every row is what a Имя/Скрипт sort (and the first text search) has to
    # do, and on a big game it is the whole cost of that click (Lego Party, 1.95M rows: ~32 s). The
    # warm-up does that work in the background right after a load, in table (= file) order so the bundle
    # block cache is read sequentially, in small chunks followed by a pause of the same length (a worker
    # holding the GIL makes the window sluggish; the 5 ms switch interval bounds the wait only if chunks
    # are short), and keeps out of the way while a sort/filter pass or the user is busy. Rows resolved
    # here are simply skipped by a later sort, so clicking a header mid-way finishes the rest, not
    # everything.
    #
    # RAM: names are shared strings (sys.intern in get_row_name) and each row's cached MonoBehaviour
    # head is dropped once the row is done (it was ~250 MB for 716k heads); the rest is the bundle block
    # cache, which has its own 256 MB cap. Tables above WARMUP_MAX_ROWS stay lazy.
    WARMUP_MIN_ROWS = 100_000
    WARMUP_MAX_ROWS = 3_000_000
    _WARM_CHUNK_ROWS = 2048
    _WARM_MAX_RESOLUTIONS = 200  # ~4 ms of work per chunk at ~20 us/row
    _WARM_BUSY_SLEEP_S = 0.05

    def start_name_warmup(self) -> None:
        """Begin (or restart) resolving names and scripts of the current rows in the background.
        Call after a table fill; a no-op for small tables (resolved on demand almost instantly), for
        tables above WARMUP_MAX_ROWS, and when USTUDIO_NO_WARMUP=1."""
        if os.environ.get("USTUDIO_NO_WARMUP") == "1":
            return
        n = len(self.data_list)
        if not (self.WARMUP_MIN_ROWS <= n <= self.WARMUP_MAX_ROWS):
            return
        self._warm_gen += 1
        with self._warm_lock:
            self._warm_epoch += 1
            self._warm_pos = 0
        if self._warm_worker is not None:
            self._warm_restart = True  # the old pass sees the new generation and ends; then we relaunch
            return
        self._launch_warmup()

    def _launch_warmup(self) -> None:
        self._warm_restart = False
        gen = self._warm_gen

        def fn(_report):
            while self._warm_gen == gen:
                if self._warm_should_wait():
                    time.sleep(self._WARM_BUSY_SLEEP_S)
                    continue
                if self._warm_one_chunk(gen):
                    break
                time.sleep(self._warm_last_work_s)  # duty cycle: rest as long as we just worked
            return None

        worker = BackgroundWorker(fn, parent=self)
        self._warm_worker = worker
        worker.finished.connect(lambda w=worker: self._on_warm_worker_finished(w))
        worker.start()

    def _warm_should_wait(self) -> bool:
        if (self._sort_resolve_worker is not None or self._sort_worker is not None
                or self._pending_sort is not None):
            return True
        pause = self.warmup_should_pause
        try:
            return bool(pause()) if pause is not None else False
        except Exception:  # a broken hook must never kill the pass
            return False

    def _warm_one_chunk(self, gen: int) -> bool:
        """Resolve the next chunk. Returns True when the whole table has been covered."""
        t0 = time.perf_counter()
        with self._warm_lock:
            epoch, pos = self._warm_epoch, self._warm_pos
        rows = self.data_list
        end = min(len(rows), pos + self._WARM_CHUNK_ROWS)
        done = 0
        i = pos
        unresolved = ROW_FIELD_UNRESOLVED
        while i < end and done < self._WARM_MAX_RESOLUTIONS:
            item = rows[i]
            i += 1
            need_script = item.get("type") == "MonoBehaviour" and item["script_name"] is unresolved
            if need_script or item["name"] is unresolved:
                try:
                    if need_script:
                        get_row_script_name(item)
                    get_row_name(item)
                except Exception:
                    pass  # an unreadable object is reported when something actually looks at it
                item["obj_ref"]._mb_head_cache = None  # not needed again; ~350 bytes x hundreds of thousands
                done += 1
        with self._warm_lock:
            if epoch == self._warm_epoch and gen == self._warm_gen:
                self._warm_pos = i
        self._warm_last_work_s = max(time.perf_counter() - t0, 0.001)
        return i >= len(rows) and epoch == self._warm_epoch

    def stop_name_warmup(self) -> None:
        """Stop the warm-up and WAIT until it has left whatever object it was reading (at most one ~4 ms
        chunk plus its rest). Called wherever the loaded files are about to be released or replaced: a
        reader still inside a bundle's mapping while the file is released is exactly the crash the preview
        worker's pause_for_environment_teardown() exists to prevent."""
        self._warm_gen += 1
        self._warm_restart = False
        worker = self._warm_worker
        if worker is not None and worker.isRunning() and QThread.currentThread() is not worker:
            worker.wait(3000)

    def _on_warm_worker_finished(self, worker) -> None:
        if worker is self._warm_worker:
            self._warm_worker = None
        worker.deleteLater()
        if self._warm_restart:
            self._launch_warmup()

    def stop_background_reads(self) -> None:
        """Stops every pass of this model that reads the loaded objects — the name warm-up and a sort's name/script
        resolve (a «Скрипт» sort reads every MonoBehaviour: tens of seconds on a big game) — and WAITS for them; the
        sort worker itself only compares resolved values, but is waited for too. A sort waiting for its resolve is
        dropped (the rows it would sort are about to go). One of MainWindow's background passes
        (background_passes.py): called before the loaded files are released."""
        self.stop_name_warmup()
        self._sort_resolve_gen += 1
        if self._pending_sort is not None:
            self._interrupted_sort = self._pending_sort
        self._pending_sort = None
        if self._sort_resolve_worker is not None and self._sort_resolve_worker.isRunning():
            self._sort_resolve_worker.wait(3000)
        if self._sort_worker is not None and self._sort_worker.isRunning():
            self._sort_worker.wait(3000)

    def resume_background_reads(self) -> None:
        """After stop_background_reads() when the same rows stay (a save to another folder): the sort a stop cut off
        is asked for again (its resolve starts over; rows already read are skipped). The warm-up is MainWindow's to
        restart (start_name_warmup)."""
        pending, self._interrupted_sort = self._interrupted_sort, None
        if pending is not None:
            self.sort(*pending, visible_provider=self._visible_provider)

    def cleanup(self) -> None:
        """Call from MainWindow.closeEvent, same convention as
        AdvancedFilterProxyModel.cleanup()/PreviewPanel.cleanup()."""
        self.stop_background_reads()


_RESOLVE_PLACEHOLDER_DELAY_MS = 200  # same debounce-before-announcing idiom as
# preview_panel.py's own _LOADING_PLACEHOLDER_DELAY_MS — a fast resolve (small/
# already-mostly-resolved table) never flashes a status message at all.
