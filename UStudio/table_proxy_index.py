"""IndexFilterProxyModel — the NumPy index-array filter proxy the application uses (visible rows kept as an
array of source row numbers; optional background text-filter pass). Split out of object_table.py (mechanical
move, no logic changes)."""

from core.i18n import tr
import logging
from typing import Optional

import numpy as np
from PyQt6.QtCore import (
    Qt, QAbstractProxyModel, QModelIndex, QRegularExpression,
    QTimer, pyqtSignal,
)

from core.object_preview import ROW_FIELD_UNRESOLVED, get_row_name, get_row_script_name
from core.progress import Pacer, ProgressThrottle
from core.table_index import accepted_rows, proxy_row_of, remap_rows, splice_range
from gui_workers import BackgroundWorker
from table_filter import _NO_TEXT_FILTER, _item_passes_filter, text_value_matcher
from table_model import ObjectTableModel, _RESOLVE_PLACEHOLDER_DELAY_MS

class _Superseded(Exception):
    """A background filter pass was told to stop while its pacer waited (a newer filter, a teardown)."""


# The filter pass's progress phase carrying the rows it found since its last report (see _show_found_rows).
_FOUND_ROWS = "found"


class IndexFilterProxyModel(QAbstractProxyModel):
    """Filter-only proxy over ObjectTableModel that keeps the visible rows as a NumPy index array.

    Why: QSortFilterProxyModel calls a Python filterAcceptsRow() for every source row on every mapping
    rebuild — at ~2M rows that is the whole cost of filling the table (2.0 s), applying a filter (3.3 s)
    or re-applying a sort (2.8 s), all on the GUI thread (measured on the 1.95M-row Lego Party table).
    Here "which rows are visible" is an ascending int64 array of SOURCE row numbers (`_idx`):
      * type/source restrictions are a vectorised mask over small integer category codes the source
        model keeps (core/table_index.py) — milliseconds;
      * anything that has to look at the live row (script selectors, the modified flag, free text) is
        decided by the SAME Python predicate as before (_item_passes_filter), but only for the rows the
        mask already let through;
      * sorting is not this class's business: ObjectTableModel keeps the rows themselves sorted (its
        sort worker also permutes the codes), so `_idx` ascending == the visible order.
    mapToSource/mapFromSource are array lookups (a binary search for the way back).

    Everything the application used on AdvancedFilterProxyModel is kept (set_type_script_filter,
    set_quick_filter_state, reset_for_new_dataset, get_visible_items, the allowed_* attributes, the
    free-text setters, the resolve_* signals, cleanup()), and tests/test_index_proxy_parity.py checks it
    against LegacyFilterProxyModel row for row through filters, sorts, appends, edits and reloads.
    A source that is not an ObjectTableModel is shown unfiltered."""

    resolve_started = pyqtSignal()
    resolve_progress = pyqtSignal(int, int)  # current, total
    resolve_finished = pyqtSignal()
    # The type/script, file or «modified» filter changed (or was requested: a script filter waiting for its
    # scripts to be read counts). The quick filters bar and the «Фильтры» button show the state from it.
    filter_state_changed = pyqtSignal()
    # What the pass behind these signals is doing, for the status line: "scripts" (resolving the script names a
    # script filter needs) or "filter" (the background free-text/type filter pass).
    resolve_kind = "scripts"

    # A free-text filter over at least this many rows runs on a worker thread (the GUI stays alive, the
    # result lands when ready, typing again restarts it): measured 7.4 s on 2M rows even with the cheaper
    # literal-needle predicate, and on a freshly loaded table the first search must also READ every name.
    # Below it the filter is applied inline (a few hundred ms at most). Tests lower it to exercise the
    # worker path on small tables.
    ASYNC_FILTER_MIN_ROWS = 100_000
    _FILTER_CHUNK_ROWS = 4096
    # () -> bool: the user is busy, the background filter pass waits (MainWindow: its UserActivityTracker.busy).
    search_should_pause = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._resolve_worker = None
        self._resolve_gen = 0       # bumped by stop_background_reads(): a running resolve ends at its next row
        # What a stop cut off, for resume_background_reads(): a script filter waiting for its scripts, and whether a
        # background text-filter pass was cut (the visible rows are then still the previous filter's).
        self._interrupted_script_filter = None
        self._interrupted_text_filter = False
        self._pending_script_filter = None
        self._resolve_placeholder_shown = False
        self.allowed_types = None
        self.allowed_scripts = None
        self.allowed_sources = None
        self.modified_only = False
        self.bookmark_matcher = None     # «Закладки» (core.bookmarks matcher), None = not restricted
        self._case_sensitivity = Qt.CaseSensitivity.CaseSensitive  # QSortFilterProxyModel's default
        self._text_regex = QRegularExpression()
        self._text_filter_active = False
        # The literal the current text filter was set from (setFilterFixedString), or None for a real
        # regular expression: a literal needle allows the one-regex-per-row fast path in _residual().
        self._text_literal: Optional[str] = None
        self._idx = np.empty(0, dtype=np.int64)
        self._connections = []
        # Async text filter (see _start_async_filter): a generation counter makes every older result
        # stale, so typing another character simply starts over.
        self._filter_worker = None
        self._filter_generation = 0
        self._filter_restart = False
        self._filter_placeholder_shown = False
        self._showing_partial = False   # the running pass has put its first matches on screen

    # ------------------------------------------------------------------ source wiring
    def setSourceModel(self, source_model) -> None:
        self.beginResetModel()
        self._filter_generation += 1
        self._disconnect_source()
        super().setSourceModel(source_model)
        self._connect_source()
        self._idx = self._compute_idx()
        self.endResetModel()

    def _connect_source(self) -> None:
        source = self.sourceModel()
        if source is None:
            return
        for signal, slot in (
            (source.modelAboutToBeReset, self._on_source_about_to_reset),
            (source.modelReset, self._on_source_reset),
            (source.layoutAboutToBeChanged, self._on_source_about_to_reset),
            (source.layoutChanged, self._on_source_reset),
            (source.rowsInserted, self._on_source_rows_inserted),
            (source.rowsRemoved, self._on_source_rows_removed),
            (source.dataChanged, self._on_source_data_changed),
        ):
            signal.connect(slot)
            self._connections.append((signal, slot))

    def _disconnect_source(self) -> None:
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):  # source already destroyed
                pass
        self._connections = []

    def _on_source_about_to_reset(self, *_args) -> None:
        self.beginResetModel()

    def _on_source_reset(self, *_args) -> None:
        source = self.sourceModel()
        perm = getattr(source, "reset_permutation", None)
        n = len(source.data_list) if isinstance(source, ObjectTableModel) else -1
        if (perm is not None and len(perm) == n and self._filter_worker is None and not self._filter_restart
                and (self._idx.size == 0 or int(self._idx[-1]) < n)):
            # A finished sort only REORDERED the same rows (new_rows[j] = old_rows[perm[j]]): the visible
            # set is the same rows at new positions — an O(n) remap, not a re-evaluation of the filter.
            if self._idx.size:
                inverse = np.empty(n, dtype=np.int64)
                inverse[perm] = np.arange(n, dtype=np.int64)
                self._idx = np.sort(inverse[self._idx])
            self.endResetModel()
            return
        self._filter_generation += 1  # whatever was in flight described the old rows
        if self._should_filter_async(source):
            self._idx = np.empty(0, dtype=np.int64)  # nothing shown until the worker has the answer
            self.endResetModel()
            self._start_async_filter()
            return
        self._filter_restart = False
        self._idx = self._compute_idx()
        self.endResetModel()

    def _on_source_rows_removed(self, *_args) -> None:
        # Nothing in this app removes rows; if something ever does, rebuild from scratch rather than guess.
        self.beginResetModel()
        self._filter_generation += 1
        self._filter_restart = False
        self._idx = self._compute_idx()
        self.endResetModel()

    def _filter_in_flight(self) -> bool:
        return self._filter_worker is not None or self._filter_restart

    def _on_source_rows_inserted(self, parent, first, last) -> None:
        if parent.isValid():
            return
        if self._filter_in_flight():
            # The running pass worked from a snapshot that no longer matches: it starts over.
            self._filter_generation += 1
            self._filter_restart = True
            return
        if len(self._idx) and int(self._idx[-1]) >= first:
            # Rows went in BEFORE existing ones (append_rows never does): later row numbers shift.
            self.beginResetModel()
            self._idx = self._compute_idx()
            self.endResetModel()
            return
        new_rows = self._compute_idx(first, last)  # the model extended its codes before signalling
        if new_rows.size == 0:
            return
        start = len(self._idx)
        self.beginInsertRows(QModelIndex(), start, start + int(new_rows.size) - 1)
        self._idx = np.concatenate((self._idx, new_rows))
        self.endInsertRows()

    def _on_source_data_changed(self, top_left, bottom_right, roles=None) -> None:
        source = self.sourceModel()
        if not isinstance(source, ObjectTableModel) or not top_left.isValid() or not bottom_right.isValid():
            return
        first, last = top_left.row(), min(bottom_right.row(), len(source.data_list) - 1)
        if first > last:
            return
        source.refresh_column_store(first, last)  # a type/source edited in place changes the codes
        if self._filter_in_flight():
            self._filter_generation += 1
            self._filter_restart = True
            return
        old = self._idx
        a = int(np.searchsorted(old, first, side="left"))
        b = int(np.searchsorted(old, last, side="right"))
        in_range = self._compute_idx(first, last)  # who passes NOW (live predicate, like the legacy proxy)
        c0, c1 = top_left.column(), bottom_right.column()
        if in_range.size == b - a and np.array_equal(in_range, old[a:b]):
            if b > a:  # membership unchanged: the visible rows just repaint
                self.dataChanged.emit(self.index(a, c0), self.index(b - 1, c1), roles or [])
            return
        self._set_idx(splice_range(old, first, last, in_range))
        a2 = int(np.searchsorted(self._idx, first, side="left"))
        b2 = int(np.searchsorted(self._idx, last, side="right"))
        if b2 > a2:
            self.dataChanged.emit(self.index(a2, c0), self.index(b2 - 1, c1), roles or [])

    # ------------------------------------------------------------------ the visible-row index
    def _residual(self):
        """The complete Python predicate for the criteria the integer codes cannot decide, or None."""
        if (self.allowed_scripts is None and not self.modified_only and not self._text_filter_active
                and self.bookmark_matcher is None):
            return None
        types, scripts, sources, modified = self.allowed_types, self.allowed_scripts, self.allowed_sources, self.modified_only
        bookmarks = self.bookmark_matcher
        if self._text_filter_active and self._text_literal:
            return self._literal_text_residual(types, scripts, sources, modified, bookmarks)
        regex = self.filterRegularExpression() if self._text_filter_active else _NO_TEXT_FILTER
        return lambda item: _item_passes_filter(item, types, scripts, regex, sources, modified, bookmarks)

    def _literal_text_residual(self, types, scripts, sources, modified, bookmarks=None):
        """Same answer as _item_passes_filter() for a LITERAL needle, much cheaper per row.

        The legacy predicate asks the regex once per field of the row (name, path, script, type, source,
        PathID, size) and accepts on the first hit; text_value_matcher() gives the same per-field answer but
        matches each distinct string once and skips numbers a needle cannot match (Lego Party, 1.95M rows:
        6.3 s -> 2.2 s; it was one regex over the fields joined with NUL before). Everything else
        (type/script/source/modified restrictions, resolving the lazy name and script first) is done by the
        same code, in the same order. One matcher per residual: its memo lives for one filter pass."""
        matches = text_value_matcher(self.filterRegularExpression(), self._text_literal)
        restricted = (types is not None or scripts is not None or sources is not None or modified
                      or bookmarks is not None)

        def residual(item):
            if restricted and not _item_passes_filter(item, types, scripts, _NO_TEXT_FILTER, sources, modified, bookmarks):
                return False
            get_row_name(item)  # a text search is exactly where the lazy name/script must be read
            get_row_script_name(item)
            return matches(item.values())

        return residual

    def _compute_idx(self, first: int = 0, last: Optional[int] = None) -> np.ndarray:
        """Ascending source row numbers in [first, last] that pass the current filter."""
        source = self.sourceModel()
        if source is None:
            return np.empty(0, dtype=np.int64)
        if not isinstance(source, ObjectTableModel):
            n = source.rowCount()
            hi = n - 1 if last is None else min(last, n - 1)
            return np.arange(first, hi + 1, dtype=np.int64)
        needs_codes = self.allowed_types is not None or self.allowed_sources is not None
        store = source.column_store() if needs_codes else None
        return accepted_rows(
            store, source.data_list, self.allowed_types, self.allowed_sources, self._residual(), first, last,
        )

    def _should_filter_async(self, source) -> bool:
        return (self._text_filter_active and isinstance(source, ObjectTableModel)
                and len(source.data_list) >= self.ASYNC_FILTER_MIN_ROWS)

    def _refilter(self) -> None:
        if self._should_filter_async(self.sourceModel()):
            self._start_async_filter()
            return
        # Inline. This also supersedes any pass still running for an older state of the filter.
        self._filter_generation += 1
        self._filter_restart = False
        self._end_filter_status()
        self._set_idx(self._compute_idx())

    # ------------------------------------------------------------------ async text filter
    @property
    def filter_pending(self) -> bool:
        """True while a background filter pass is running or about to restart (the visible rows are
        then still those of the previous filter)."""
        return self._filter_in_flight()

    @property
    def search_in_progress(self) -> bool:
        """True from the moment the background text-filter pass is announced (resolve_started) until its
        resolve_finished — what the «Поиск… N %» note next to the search field shows."""
        return self._filter_placeholder_shown

    def _start_async_filter(self) -> None:
        self._filter_generation += 1
        if self._filter_worker is not None:
            # The running pass sees the new generation at its next chunk and stops; we start over then.
            self._filter_restart = True
            return
        self._launch_filter_worker()

    def _launch_filter_worker(self) -> None:
        source = self.sourceModel()
        if not isinstance(source, ObjectTableModel):
            return
        self._filter_restart = False
        self._showing_partial = False
        generation = self._filter_generation
        rows = source.data_list
        types, sources = self.allowed_types, self.allowed_sources
        store = source.column_store() if (types is not None or sources is not None) else None
        chunk = self._FILTER_CHUNK_ROWS
        QTimer.singleShot(_RESOLVE_PLACEHOLDER_DELAY_MS, self._maybe_announce_filter_started)
        # Paced like every other pass that reads the game (core.progress.Pacer), and no work at all while the user
        # clicks/scrolls/types (search_should_pause): it rested 1 ms per 150 ms before, and a click on a found row
        # froze the window for seconds (user report, Lego Party; measured in the real window: the GUI blocked
        # 62.5 s of a 65.8 s first search, the search and the usage index reading at once — stacks dumped).
        pacer = Pacer(should_pause=self.search_should_pause,
                      should_stop=lambda: self._filter_generation != generation)
        check = self._residual()

        def residual(item):
            if not pacer.step():
                raise _Superseded
            return check(item)

        def fn(report_progress):
            try:
                return scan(report_progress)
            except _Superseded:
                return None

        def scan(report_progress):
            n = len(rows)
            parts = []
            shown = 0   # how many of `parts` the table already has (sent with the progress)
            throttle = ProgressThrottle()
            for lo in range(0, n, chunk):
                if self._filter_generation != generation:
                    return None  # superseded: stop at once, the newer request has its own pass
                hi = min(n - 1, lo + chunk - 1)
                parts.append(accepted_rows(store, rows, types, sources, residual, lo, hi))
                if throttle.should_report(hi, n):
                    found = parts[shown:]
                    shown = len(parts)
                    report_progress(_FOUND_ROWS, generation,
                                    np.concatenate(found) if found else np.empty(0, dtype=np.int64))
                    report_progress("", hi + 1, n)
            return generation, (np.concatenate(parts) if parts else np.empty(0, dtype=np.int64))

        worker = BackgroundWorker(fn, parent=self)
        self._filter_worker = worker
        worker.progress_signal.connect(self._on_filter_progress)
        worker.succeeded_signal.connect(self._on_async_filter_done)
        worker.failed_signal.connect(self._on_async_filter_failed)
        worker.finished.connect(lambda w=worker: self._on_filter_worker_finished(w))
        worker.start()

    def _maybe_announce_filter_started(self) -> None:
        if self._filter_worker is not None and not self._filter_placeholder_shown:
            self._filter_placeholder_shown = True
            self.resolve_kind = "filter"
            self.resolve_started.emit()

    def _on_filter_progress(self, phase: str, current, total) -> None:
        if phase == _FOUND_ROWS:
            self._show_found_rows(current, total)
        elif self._filter_placeholder_shown:
            self.resolve_progress.emit(current, total)

    def _show_found_rows(self, generation: int, found: np.ndarray) -> None:
        """The pass's matches so far go into the table as they are found (user report, Lego Party: a first
        search reads every row's name — ~45 s — and with the old rows on screen until the end the search
        looked broken). The first report REPLACES the previous filter's rows (a layout change: a selected row
        found by then stays selected); later ones are appended — the pass walks the rows in order, so every
        new row comes after the shown ones. A report from a superseded pass is ignored; the finished pass's
        full answer then equals what was shown (a no-op in _set_idx)."""
        if generation != self._filter_generation or self._filter_restart:
            return
        if not self._showing_partial:
            self._showing_partial = True
            self._set_idx(found)
            return
        if found.size == 0:
            return
        if self._idx.size and int(found[0]) <= int(self._idx[-1]):   # not expected; never show a wrong order
            self._set_idx(np.union1d(self._idx, found))
            return
        start = len(self._idx)
        self.beginInsertRows(QModelIndex(), start, start + int(found.size) - 1)
        self._idx = np.concatenate((self._idx, found))
        self.endInsertRows()

    def _end_filter_status(self) -> None:
        if self._filter_placeholder_shown:
            self._filter_placeholder_shown = False
            self.resolve_finished.emit()

    def _on_async_filter_done(self, result) -> None:
        if result is None:
            return
        generation, idx = result
        if generation != self._filter_generation or self._filter_restart:
            return  # stale: a newer pass is (about to be) running
        self._end_filter_status()
        self._set_idx(idx)
        source = self.sourceModel()
        if isinstance(source, ObjectTableModel):
            source.resort_if_needed()

    def _on_async_filter_failed(self, message: str) -> None:
        if self._filter_restart:
            return  # the pass died because the rows changed under it; the restart recomputes
        logging.getLogger("ustudio.table").warning(tr("Фоновая фильтрация не удалась (%s) — применяю фильтр сразу."), message)
        self._filter_generation += 1
        self._end_filter_status()
        self._set_idx(self._compute_idx())

    def _on_filter_worker_finished(self, worker) -> None:
        if worker is self._filter_worker:
            self._filter_worker = None
        worker.deleteLater()
        if self._filter_restart:
            self._launch_filter_worker()

    def _set_idx(self, new_idx: np.ndarray) -> None:
        """Installs a new visible-row array as a LAYOUT change, remapping persistent indexes (the
        selection, the current row) onto the rows that are still visible — what
        QSortFilterProxyModel.invalidate() does, minus the per-row Python calls."""
        old = self._idx
        if len(old) == len(new_idx) and np.array_equal(old, new_idx):
            return
        self.layoutAboutToBeChanged.emit()
        persistent = self.persistentIndexList()
        columns = [p.column() for p in persistent]
        new_rows = remap_rows(old, new_idx, [p.row() for p in persistent])
        self._idx = new_idx
        self.changePersistentIndexList(
            persistent, [self.createIndex(r, c) if r >= 0 else QModelIndex() for r, c in zip(new_rows, columns)],
        )
        self.layoutChanged.emit()

    # ------------------------------------------------------------------ QAbstractProxyModel interface
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._idx)

    def columnCount(self, parent=QModelIndex()):
        source = self.sourceModel()
        return 0 if parent.isValid() or source is None else source.columnCount()

    def hasChildren(self, parent=QModelIndex()):
        return not parent.isValid() and len(self._idx) > 0

    def index(self, row, column, parent=QModelIndex()):
        if parent.isValid() or not (0 <= row < len(self._idx)) or not (0 <= column < self.columnCount()):
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, child=None):
        if child is None:  # QObject.parent()
            return super().parent()
        return QModelIndex()

    def mapToSource(self, proxy_index):
        source = self.sourceModel()
        if source is None or not proxy_index.isValid() or proxy_index.model() is not self:
            return QModelIndex()
        row = proxy_index.row()
        if not (0 <= row < len(self._idx)):
            return QModelIndex()
        return source.index(int(self._idx[row]), proxy_index.column())

    def mapFromSource(self, source_index):
        if not source_index.isValid() or source_index.model() is not self.sourceModel():
            return QModelIndex()
        row = proxy_row_of(self._idx, source_index.row())
        return self.createIndex(row, source_index.column()) if row >= 0 else QModelIndex()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        source = self.sourceModel()
        if source is None or orientation != Qt.Orientation.Horizontal:
            return None
        return source.headerData(section, orientation, role)

    # ------------------------------------------------------------------ filter API (as the legacy proxy)
    def set_type_script_filter(self, allowed_types, allowed_scripts):
        """Restricts the table to allowed_types/allowed_scripts (both None = no restriction). A script
        restriction needs every MonoBehaviour row's script name; those resolve lazily, so when some are
        still unresolved they are read on a background worker first and the filter is applied when it
        finishes (resolving them inside one filter call froze the GUI and, before the native reader was
        locked, crashed it — see LegacyFilterProxyModel's notes)."""
        if allowed_scripts is not None:
            unresolved = self._unresolved_monobehaviour_rows()
            if unresolved:
                self._pending_script_filter = (allowed_types, allowed_scripts)
                self._start_resolve_worker(unresolved)
                self.filter_state_changed.emit()
                return
        self._pending_script_filter = None
        self.allowed_types = allowed_types
        self.allowed_scripts = allowed_scripts
        self.invalidateFilter()
        self.filter_state_changed.emit()

    def requested_type_script_filter(self):
        """(allowed_types, allowed_scripts) as last asked for — a script filter that is still waiting for its
        scripts to be read is already the user's choice, so it is what the quick filters bar shows."""
        if self._pending_script_filter is not None:
            return self._pending_script_filter
        return self.allowed_types, self.allowed_scripts

    def set_quick_filter_state(self, allowed_sources, modified_only: bool):
        self.allowed_sources = allowed_sources
        self.modified_only = modified_only
        self.invalidateFilter()
        self.filter_state_changed.emit()

    def set_bookmark_filter(self, matcher) -> None:
        """«Закладки»: only rows `matcher` accepts (a fresh matcher after the bookmarks change), None = all."""
        self.bookmark_matcher = matcher
        self.invalidateFilter()
        self.filter_state_changed.emit()

    def reset_for_new_dataset(self) -> None:
        """Clears the type/script and quick filters (NOT the free-text box) WITHOUT re-filtering — for a
        fresh load, right before ObjectTableModel.replace_data(), whose model reset re-filters anyway."""
        self._pending_script_filter = None
        self._interrupted_script_filter = None
        self._interrupted_text_filter = False
        self._filter_generation += 1
        self.allowed_types = None
        self.allowed_scripts = None
        self.allowed_sources = None
        self.modified_only = False
        self.bookmark_matcher = None
        self.filter_state_changed.emit()

    def _apply_text_regex(self, regex: QRegularExpression, literal: Optional[str] = None) -> None:
        self._text_literal = literal
        options = regex.patternOptions()
        if self._case_sensitivity == Qt.CaseSensitivity.CaseInsensitive:
            options |= QRegularExpression.PatternOption.CaseInsensitiveOption
        else:
            options &= ~QRegularExpression.PatternOption.CaseInsensitiveOption
        regex.setPatternOptions(options)
        self._text_regex = regex
        self._text_filter_active = bool(regex.pattern())
        self.invalidateFilter()

    def setFilterFixedString(self, pattern: str) -> None:
        self._apply_text_regex(QRegularExpression(QRegularExpression.escape(pattern)), literal=pattern)

    def setFilterRegularExpression(self, regex) -> None:
        if isinstance(regex, str):
            regex = QRegularExpression(regex)
        self._apply_text_regex(QRegularExpression(regex))

    def filterRegularExpression(self) -> QRegularExpression:
        return QRegularExpression(self._text_regex)

    def setFilterCaseSensitivity(self, sensitivity) -> None:
        self._case_sensitivity = sensitivity
        self._apply_text_regex(QRegularExpression(self._text_regex), literal=self._text_literal)

    def filterCaseSensitivity(self):
        return self._case_sensitivity

    def filterAcceptsRow(self, source_row, source_parent=QModelIndex()):
        """Kept for callers/tests that ask about one row; the proxy itself never calls it."""
        source = self.sourceModel()
        if not isinstance(source, ObjectTableModel) or not (0 <= source_row < len(source.data_list)):
            return True
        return _item_passes_filter(
            source.data_list[source_row], self.allowed_types, self.allowed_scripts, self.filterRegularExpression(),
            self.allowed_sources, self.modified_only, self.bookmark_matcher,
        )

    def get_visible_items(self) -> list:
        """Every row of the source that passes the CURRENT filter, evaluated now (a plain list built
        without any Qt model-interface calls — used by select-all and by name sorts)."""
        source = self.sourceModel()
        if not isinstance(source, ObjectTableModel):
            return []
        rows = source.data_list
        # The live index IS the current answer (dataChanged / appends / resets keep it up to date, and a
        # background pass replaces it when done) — no need to evaluate the predicate over every row again.
        if len(self._idx) == len(rows):
            return list(rows)
        return [rows[i] for i in self._idx.tolist()]

    def invalidate(self) -> None:
        self.invalidateFilter()

    def invalidateFilter(self) -> None:
        self._refilter()
        source = self.sourceModel()
        if isinstance(source, ObjectTableModel) and not self._filter_in_flight():
            source.resort_if_needed()  # (a pending background pass calls it itself when it lands)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        # The rows themselves are sorted by the source model (one list sort in a worker thread, with the
        # filter codes permuted alongside); this proxy only ever filters, so `_idx` ascending IS the order.
        source = self.sourceModel()
        if isinstance(source, ObjectTableModel):
            source.sort(column, order, visible_provider=self.get_visible_items)

    # ------------------------------------------------------------------ script-name resolution (as legacy)
    def _unresolved_monobehaviour_rows(self) -> list:
        source = self.sourceModel()
        if not isinstance(source, ObjectTableModel):
            return []
        return [
            item for item in source.data_list
            if item.get("type") == "MonoBehaviour" and item["script_name"] is ROW_FIELD_UNRESOLVED
        ]

    def _start_resolve_worker(self, unresolved: list) -> None:
        if self._resolve_worker is not None:
            return  # it re-scans for unresolved rows when it finishes, so a newer request is still honoured
        self._resolve_placeholder_shown = False
        QTimer.singleShot(_RESOLVE_PLACEHOLDER_DELAY_MS, self._maybe_announce_resolve_started)

        gen = self._resolve_gen

        def fn(report_progress):
            total = len(unresolved)
            throttle = ProgressThrottle()
            for i, item in enumerate(unresolved):
                if self._resolve_gen != gen:
                    return None  # stopped: the loaded files are about to be released
                get_row_script_name(item)  # resolves + memoizes in place
                if throttle.should_report(i, total):
                    report_progress("", i + 1, total)
                    throttle.pause()
            return None

        worker = BackgroundWorker(fn, parent=self)
        self._resolve_worker = worker
        worker.progress_signal.connect(self._on_resolve_progress)
        worker.succeeded_signal.connect(self._on_resolve_done)
        worker.failed_signal.connect(self._on_resolve_done)
        worker.finished.connect(lambda w=worker: self._on_resolve_worker_finished(w))
        worker.start()

    def _maybe_announce_resolve_started(self) -> None:
        if self._resolve_worker is not None and not self._resolve_placeholder_shown:
            self._resolve_placeholder_shown = True
            self.resolve_kind = "scripts"
            self.resolve_started.emit()

    def _on_resolve_progress(self, _phase: str, current, total) -> None:
        if self._resolve_placeholder_shown:
            self.resolve_progress.emit(current, total)

    def _on_resolve_done(self, *_args) -> None:
        if self._resolve_placeholder_shown:
            self.resolve_finished.emit()
        pending = self._pending_script_filter
        self._pending_script_filter = None
        if pending is not None:
            self.set_type_script_filter(*pending)

    def _on_resolve_worker_finished(self, worker) -> None:
        if worker is self._resolve_worker:
            self._resolve_worker = None
        worker.deleteLater()

    def stop_background_reads(self) -> None:
        """Stops the background filter pass (a text filter reads every row's name) and the script resolve (a
        script filter waiting for its scripts) and WAITS for both: they read the loaded objects, and ran on until
        done unless told — measured on Phonopolis, both were still reading when a new load released the old game's
        files. A script filter still waiting for its scripts is dropped. One of MainWindow's background passes
        (background_passes.py); also what closeEvent's cleanup() does."""
        if self._filter_in_flight():
            self._interrupted_text_filter = True
        if self._pending_script_filter is not None:
            self._interrupted_script_filter = self._pending_script_filter
        self._filter_generation += 1  # the filter pass stops at its next chunk
        self._filter_restart = False
        self._resolve_gen += 1
        had_pending = self._pending_script_filter is not None
        self._pending_script_filter = None
        if self._filter_worker is not None and self._filter_worker.isRunning():
            self._filter_worker.wait(3000)
        if self._resolve_worker is not None and self._resolve_worker.isRunning():
            self._resolve_worker.wait(3000)
        self._end_filter_status()
        if had_pending:
            self.filter_state_changed.emit()    # the bar stops showing a filter that will not come

    def resume_background_reads(self) -> None:
        """After stop_background_reads() when the same rows stay (a save to another folder): what the stop cut off is
        asked for again — the waiting script filter, the text filter's pass."""
        script, self._interrupted_script_filter = self._interrupted_script_filter, None
        text, self._interrupted_text_filter = self._interrupted_text_filter, False
        if script is not None:
            self.set_type_script_filter(*script)       # re-filters too
        elif text:
            self.invalidateFilter()

    def cleanup(self) -> None:
        """Call from MainWindow.closeEvent: lets in-flight background passes stop instead of being
        destroyed while running."""
        self.stop_background_reads()
