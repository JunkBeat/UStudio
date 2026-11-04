"""LegacyFilterProxyModel — the original QSortFilterProxyModel-based filter proxy, kept as the rollback
(USTUDIO_LEGACY_PROXY=1) and as the reference the parity tests compare the index proxy against. Split out of
object_table.py (mechanical move, no logic changes)."""

from PyQt6.QtCore import (
    Qt, QSortFilterProxyModel, QTimer, pyqtSignal,
)

from core.object_preview import ROW_FIELD_UNRESOLVED, get_row_script_name
from core.progress import ProgressThrottle
from gui_workers import BackgroundWorker
from table_filter import _NO_TEXT_FILTER, _item_passes_filter
from table_model import ObjectTableModel, _RESOLVE_PLACEHOLDER_DELAY_MS


class LegacyFilterProxyModel(QSortFilterProxyModel):
    """The original QSortFilterProxyModel-based proxy: one Python filterAcceptsRow() call per row, so at
    ~2M rows every mapping rebuild costs seconds on the GUI thread. Replaced by IndexFilterProxyModel
    below; kept (selectable with USTUDIO_LEGACY_PROXY=1) as the rollback and as the reference the new
    proxy is tested against, row for row (tests/test_index_proxy_parity.py)."""
    # Emitted only around a background MonoBehaviour script-name resolution pass —
    # see set_type_script_filter()'s own docstring for why this exists at all.
    # MainWindow wires these to its existing status_label/progress_bar, the same
    # status surface every other background operation in this app already reports
    # through — this model deliberately doesn't touch any widget itself.
    resolve_started = pyqtSignal()
    resolve_progress = pyqtSignal(int, int)  # current, total
    resolve_finished = pyqtSignal()
    # The type/script, file or «modified» filter changed (or was requested: a script filter waiting for its
    # scripts to be read counts). The quick filters bar and the «Фильтры» button show the state from it.
    filter_state_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._resolve_worker = None
        # (allowed_types, allowed_scripts) a caller actually wants applied once the
        # in-flight resolve pass finishes — see set_type_script_filter()'s docstring.
        self._pending_script_filter = None
        self._resolve_placeholder_shown = False
        # Both None = no restriction (the default, and what a fresh load resets
        # to) — see dialogs.FiltersDialog / MainWindow.open_filters_dialog().
        # allowed_scripts only ever restricts MonoBehaviour rows; every other
        # type is unaffected by it regardless of its contents.
        #
        # This used to also have a separate isolated_value filter (an exact
        # name/type/script match applied on top of these, independently) for
        # "show only objects of this type" — removed: it could end up ANDed
        # against a type/script selection that excluded its own target,
        # silently producing an empty table with no indication why (a real
        # reported bug). "Hard filtering to type/script X" now just means
        # restricting allowed_types/allowed_scripts to X directly — see
        # MainWindow.filter_to_type_or_script() — so there's nothing separate
        # left that could disagree with it.
        # Whether a free-text filter is set, as a plain attribute: filterAcceptsRow() runs for every row
        # on every mapping rebuild (millions of calls), and the nothing-restricted case has to be
        # decided without asking Qt for filterRegularExpression() each time. Kept in sync by the
        # setFilter*() overrides below — the only ways this app sets the text filter.
        self._text_filter_active = False
        self.allowed_types = None
        self.allowed_scripts = None
        # Quick Filters Bar's own two dimensions (core/quick_filters.py) — both
        # AND with allowed_types/allowed_scripts/free-text above, see
        # _item_passes_filter()'s docstring.
        self.allowed_sources = None
        self.modified_only = False
        self.bookmark_matcher = None     # «Закладки» (core.bookmarks matcher), None = not restricted

    def set_type_script_filter(self, allowed_types, allowed_scripts):
        """Restricts the table to allowed_types/allowed_scripts (both None = no
        restriction) — called by the Quick Filters Bar, FiltersDialog's Apply, and
        MainWindow.filter_to_type_or_script()'s "isolate this row's type/script"
        actions; every one of them funnels through here, which is exactly what
        makes this the single choke point for the fix below.

        A script restriction only ever matters for MonoBehaviour rows, and
        get_row_script_name() (core/object_preview.py) resolves + memoizes that
        field LAZILY — the whole point being that a row nobody has ever looked at
        never pays for it. Naively calling invalidateFilter() here used to defeat
        that entirely: Qt re-running filterAcceptsRow() for every row the instant
        allowed_scripts becomes non-None forces EVERY still-unresolved MonoBehaviour
        row (a whole freshly-loaded table's worth, easily hundreds of thousands) to
        resolve synchronously, on the GUI thread, inside one Qt call — a real,
        reproduced access-violation crash (see UnityPy/helpers/TypeTreeGenerator.py's
        own docstring for the underlying data race this exposed, now fixed there
        too) once anything else — a background task-queue job touching a
        MonoBehaviour-classed object, e.g. SDF font-atlas generation on a
        TMP_FontAsset — was calling into the same shared, then-unlocked native
        generator concurrently. Locking the shared UnityPy state closes the crash;
        this closes the OTHER half of the same problem — a GUI freeze proportional
        to table size, on the GUI thread, every single time a script-restricted
        filter is (re)applied — which would still be there even with perfectly
        thread-safe reads underneath.

        Fix: when a script restriction is requested and the table still has
        unresolved MonoBehaviour rows, don't apply it inline — kick off a
        background pass (BackgroundWorker, same as PreviewPanel's own read
        pipeline) that resolves+memoizes every one of them off the GUI thread, and
        apply the filter only once that finishes (see _on_resolve_done()). Once a
        row's script_name is resolved it stays resolved (get_row_script_name()'s
        own memoization), so this pass never repeats work a previous one already
        did — the common case (script filter toggled a second time, or a small/
        already-fully-resolved table) takes the immediate synchronous path below
        exactly as before, with no worker and no delay at all."""
        if allowed_scripts is not None:
            unresolved = self._unresolved_monobehaviour_rows()
            if unresolved:
                self._pending_script_filter = (allowed_types, allowed_scripts)
                self._start_resolve_worker(unresolved)
                self.filter_state_changed.emit()
                return
        # No script restriction needed, or nothing left to resolve for one — the
        # fast, synchronous path. Also clears any stale pending request from an
        # EARLIER call this one supersedes (e.g. the user toggled the script
        # filter back off while a resolve for the old selection was still running).
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
            # Already running — it re-scans for unresolved rows (fresh, not from
            # this stale list) via _on_resolve_done() -> set_type_script_filter()
            # once it finishes, so the newer request above is still honored.
            return
        self._resolve_placeholder_shown = False
        QTimer.singleShot(_RESOLVE_PLACEHOLDER_DELAY_MS, self._maybe_announce_resolve_started)

        def fn(report_progress):
            total = len(unresolved)
            throttle = ProgressThrottle()
            for i, item in enumerate(unresolved):
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
        # Mirrors preview_panel.py's own _maybe_show_loading_placeholder(): only
        # surfaces anything to the user if the pass is STILL running once the
        # debounce delay elapses — a fast resolve never flashes a status message.
        if self._resolve_worker is not None and not self._resolve_placeholder_shown:
            self._resolve_placeholder_shown = True
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
            # Re-enter through set_type_script_filter() (not a direct attribute
            # assignment) rather than assume this one pass covered everything —
            # a dependency file that finished loading mid-resolve can have added
            # MORE unresolved MonoBehaviour rows in the meantime, and this correctly
            # kicks off a second pass for those instead of silently missing them.
            self.set_type_script_filter(*pending)

    def _on_resolve_worker_finished(self, worker) -> None:
        if worker is self._resolve_worker:
            self._resolve_worker = None
        worker.deleteLater()

    def cleanup(self) -> None:
        """Call from MainWindow.closeEvent, same convention as PreviewPanel.cleanup()/
        TaskQueueManager.shutdown() — gives an in-flight background resolve pass a
        real chance to stop instead of warning about (or crashing on) a QThread
        destroyed while still running."""
        if self._resolve_worker is not None and self._resolve_worker.isRunning():
            self._resolve_worker.wait(3000)

    def stop_background_reads(self) -> None:
        """As IndexFilterProxyModel.stop_background_reads (MainWindow's background passes call it): the script
        resolve is waited for, and a script filter waiting for it is dropped. This rollback proxy's resolve has no
        early exit — it is kept as it was."""
        self._interrupted_script_filter = self._pending_script_filter
        self._pending_script_filter = None
        self.cleanup()

    def resume_background_reads(self) -> None:
        """As IndexFilterProxyModel.resume_background_reads: the script filter a stop cut off is asked for again."""
        script, self._interrupted_script_filter = getattr(self, "_interrupted_script_filter", None), None
        if script is not None:
            self.set_type_script_filter(*script)

    def set_quick_filter_state(self, allowed_sources, modified_only: bool):
        self.allowed_sources = allowed_sources
        self.modified_only = modified_only
        self.invalidateFilter()
        self.filter_state_changed.emit()

    def set_bookmark_filter(self, matcher) -> None:
        """«Закладки» — as IndexFilterProxyModel.set_bookmark_filter."""
        self.bookmark_matcher = matcher
        self.invalidateFilter()
        self.filter_state_changed.emit()

    def setFilterFixedString(self, pattern: str) -> None:
        # Qt re-filters INSIDE the call below, so the flag must already say "maybe active" (the full
        # predicate reads the live regex, which is correct either way); the exact value follows.
        self._text_filter_active = True
        super().setFilterFixedString(pattern)
        self._text_filter_active = bool(self.filterRegularExpression().pattern())

    def setFilterRegularExpression(self, regex) -> None:
        self._text_filter_active = True
        super().setFilterRegularExpression(regex)
        self._text_filter_active = bool(self.filterRegularExpression().pattern())

    def reset_for_new_dataset(self) -> None:
        """Clears the type/script and quick filters (NOT the free-text box) WITHOUT re-filtering — for a
        fresh load, right BEFORE ObjectTableModel.replace_data(): that model reset makes this proxy
        rebuild its whole row mapping anyway, so invalidating the filter here (or, as the load code
        used to, once more after the swap) only made it rebuild the mapping again and again — measured
        ~4.6 s each at 1.95M rows, on the GUI thread."""
        self._pending_script_filter = None
        self.allowed_types = None
        self.allowed_scripts = None
        self.allowed_sources = None
        self.modified_only = False
        self.bookmark_matcher = None
        self.filter_state_changed.emit()

    def filterAcceptsRow(self, source_row, source_parent):
        # Nothing restricted (the state right after a load): accept at once. This is called for every row
        # of the source on every mapping rebuild, so the per-call cost is the whole price of filling the
        # table.
        if (self.allowed_types is None and self.allowed_scripts is None and self.allowed_sources is None
                and not self.modified_only and not self._text_filter_active and self.bookmark_matcher is None):
            return True
        source = self.sourceModel()
        # Direct access to data_list instead of model.index()/model.data() per cell —
        # on a large table this gets called for EVERY row on every filter change,
        # and crossing the Qt/Python boundary (QModelIndex + a virtual data() call) per
        # cell is many times more expensive than plain dict access. This used to be a bottleneck
        # of the same kind as the row-by-row sorting in sort() below.
        if isinstance(source, ObjectTableModel) and 0 <= source_row < len(source.data_list):
            item = source.data_list[source_row]
            return _item_passes_filter(
                item, self.allowed_types, self.allowed_scripts,
                self.filterRegularExpression() if self._text_filter_active else _NO_TEXT_FILTER,
                self.allowed_sources, self.modified_only, self.bookmark_matcher,
            )

        # Fallback to the standard (slow but universal) implementation for any
        # other source model
        model = source
        filter_regex = self.filterRegularExpression()
        if not filter_regex.pattern():
            return True
        for col in range(model.columnCount()):
            index = model.index(source_row, col, source_parent)
            text = str(model.data(index, Qt.ItemDataRole.DisplayRole) or "")
            if filter_regex.match(text).hasMatch():
                return True
        return False

    def get_visible_items(self) -> list:
        """Every item in the source model's data_list that currently passes
        this proxy's filter (type/script + free-text) — computed directly
        against the plain dict list, with NO QModelIndex/Qt model-interface
        calls at all (unlike, say, iterating rowCount() and mapping each proxy
        row back to source).

        This exists for the "virtual select-all" mechanism (see
        ObjectTableView.select_all_active / ObjectTableView.selectAll()'s
        docstring): Qt's own QAbstractItemView.selectAll() was measured (via
        profiling, not guessed) to call this Python model's rowCount()/
        columnCount() roughly 8 times PER ROW — 2 million+ PyQt boundary
        crossings for a 250,000-row table — which is what actually made it
        slow, confirmed identical with or without this proxy in the way. A
        plain Python loop over data_list applying the same predicate
        filterAcceptsRow() already uses is orders of magnitude cheaper at this
        scale, because it never crosses back into Qt/PyQt per row at all."""
        source = self.sourceModel()
        if not isinstance(source, ObjectTableModel):
            return []
        allowed_types, allowed_scripts = self.allowed_types, self.allowed_scripts
        allowed_sources, modified_only = self.allowed_sources, self.modified_only
        bookmarks = self.bookmark_matcher
        filter_regex = self.filterRegularExpression()
        return [
            item for item in source.data_list
            if _item_passes_filter(item, allowed_types, allowed_scripts, filter_regex, allowed_sources, modified_only,
                                   bookmarks)
        ]

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        # By default QSortFilterProxyModel sorts via row-by-row comparison through
        # lessThan(), which calls data() across the Python/Qt boundary on every comparison —
        # on large tables (hundreds of thousands+ rows) this is exactly why "sorting takes
        # forever". Instead, delegate the actual sorting to the source model: there
        # it's a single native Python list.sort() by key in one pass — orders of magnitude faster.
        source = self.sourceModel()
        if isinstance(source, ObjectTableModel):
            source.sort(column, order, visible_provider=self.get_visible_items)
        else:
            super().sort(column, order)

    def invalidateFilter(self) -> None:
        # invalidate(), not QSortFilterProxyModel.invalidateFilter(): the latter updates the row mapping
        # incrementally (row-range bookkeeping per accepted/rejected row), which degrades badly when a
        # LOT of rows change state at once. Measured on 2M rows: widening the filter back to everything
        # took 200 s (18.7 s on the 1.95M-row Lego Party table) through invalidateFilter(), 1.9 s through
        # invalidate(), which just drops the mapping and rebuilds it. Qt sorting is not used here (sort()
        # below delegates to the source model), so invalidate()'s extra "re-sort" half is a no-op.
        self.invalidate()
        source = self.sourceModel()
        if isinstance(source, ObjectTableModel):
            source.resort_if_needed()
