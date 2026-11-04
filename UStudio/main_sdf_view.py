"""SDF Viewer Mode of the main window: switching to the grouped font tree, building the groups in the background,
the character-coverage pass, and the tree's selection / context menu.

Kept out of main.py as a mixin (MainWindow inherits it), like main_save_flow.py. Behaviour is unchanged; this is a
mechanical move (every method body is byte-identical to its old place in main.py). Tests that replace
build_sdf_groups patch it HERE (main_sdf_view.build_sdf_groups), not in main."""


from core.i18n import tr
from config import CONFIG, LogLevel
from core.progress import Pacer
from core.sdf_resolver import build_sdf_groups


class SdfViewMixin:
    # --- SDF Viewer Mode ---

    def set_sdf_mode(self, enabled: bool) -> None:
        """Режим menu's radio pair (see init_menu()) — swaps the flat table
        for the grouped SDF tree (self.left_view_stack, built in init_ui())
        and disables the search bar/filters, which have nothing meaningful
        to act on in this isolated workspace (its own font/material/texture
        rows aren't what free-text search or the type/script FiltersDialog
        are for) — including the Quick Filters Bar, same reasoning: its
        type/script/file/modified toggles all act on the flat table's
        proxy_model, which isn't even the visible view here. Standard Mode's
        own state (filter text, active FiltersDialog/quick-filter selection)
        is left untouched underneath — toggling back just un-hides
        everything exactly as it was, respecting CONFIG.show_quick_filters_bar
        rather than unconditionally re-showing the bar if the user had
        already hidden it via Вид before ever entering SDF mode."""
        self.left_view_stack.setCurrentIndex(1 if enabled else 0)
        self._forget_table_notice()     # about a jump made in the other view
        self.filter_input.setVisible(not enabled)
        self.btn_filters.setVisible(not enabled)
        self.btn_reset_view.setVisible(not enabled)
        self.quick_filters_bar.setVisible(not enabled and CONFIG.show_quick_filters_bar)
        if enabled:
            self._refresh_sdf_groups()

    def _refresh_sdf_groups(self) -> None:
        """Rebuilds the SDF tree's data from the current table contents —
        called when switching INTO SDF mode, and again whenever the
        underlying data changes while it's already active (a fresh load, or
        the CAB browser's load_entry_objects) — see on_loading_finished()/
        load_entry_objects()'s own calls to this. Not kept incrementally in
        sync with every flat-table mutation (sorting/filtering there doesn't
        change SDF group membership at all)."""
        self._stop_sdf_background()        # cancels a build still running, too
        self.sdf_group_model.set_groups([])
        self.sdf_status_label.setText(tr("Поиск SDF-шрифтов…"))
        self.sdf_status_label.show()
        rows = self.raw_data_list
        self._sdf_build_generation += 1
        gen = self._sdf_build_generation

        # Off the GUI thread: resolving every font parses it (and a font the script definitions do
        # not fit can take seconds to fail — a folder with two games measured ~15 s), which froze
        # the window when this ran inline.
        def work(report_progress):
            cancelled = lambda: gen != self._sdf_build_generation    # noqa: E731
            return build_sdf_groups(rows, should_cancel=cancelled, pacer=Pacer(self._background_busy, cancelled))

        from gui_workers import BackgroundWorker
        worker = BackgroundWorker(work, parent=self)
        self._sdf_build_worker = worker
        worker.succeeded_signal.connect(lambda groups, g=gen: self._on_sdf_groups_built(g, groups))
        worker.failed_signal.connect(lambda msg, g=gen: self._on_sdf_groups_failed(g, msg))
        worker.finished.connect(lambda w=worker: self._on_sdf_build_worker_finished(w))
        worker.start()

    def _on_sdf_groups_built(self, gen: int, groups) -> None:
        if gen != self._sdf_build_generation:
            return   # superseded (another refresh, new load, teardown)
        self._sdf_build_interrupted = False
        self.sdf_group_model.set_groups(groups)
        self.sdf_group_model.set_filter(self.sdf_filter_input.text())
        self.sdf_tree_view.expandAll()
        self._span_sdf_group_rows()
        if groups:
            self.sdf_status_label.hide()
        else:
            self.sdf_status_label.setText(tr("SDF-шрифты не найдены."))
        self._start_sdf_coverage(groups)

    def _on_sdf_groups_failed(self, gen: int, message: str) -> None:
        if gen != self._sdf_build_generation:
            return
        self.sdf_status_label.setText(tr("Не удалось собрать список SDF-шрифтов."))
        self.log(tr("Не удалось собрать список SDF-шрифтов: {error}", error=message), LogLevel.ERROR)

    def _on_sdf_build_worker_finished(self, worker) -> None:
        if worker is self._sdf_build_worker:
            self._sdf_build_worker = None
        worker.deleteLater()

    def _stop_sdf_build(self) -> None:
        """Cancels the background groups build and waits for it to leave the loaded files alone —
        the same reason _stop_sdf_coverage() waits (an environment is about to be released/replaced).
        The cancel is polled once per font, so the wait is at most one font's parse."""
        self._sdf_build_generation += 1
        worker = self._sdf_build_worker
        if worker is not None and worker.isRunning():
            # Until a build lands, the groups are incomplete: _resume_sdf_background() builds them again (a save that
            # keeps the game loaded stops this build too).
            self._sdf_build_interrupted = True
            worker.wait(30000)

    def _span_sdf_group_rows(self) -> None:
        """Each top-level "SDF Font Pack" row spans the whole row width instead of being split
        into per-column cells — matches how QTreeView already treats a real folder row elsewhere
        in Qt, and is what actually fixes the coverage text (see sdf_group_model._group_data's own
        comment): with no separate narrow "Тип" cell to truncate it, the whole row has room."""
        from PyQt6.QtCore import QModelIndex
        for row in range(self.sdf_group_model.rowCount()):
            self.sdf_tree_view.setFirstColumnSpanned(row, QModelIndex(), True)

    def _start_sdf_coverage(self, groups) -> None:
        """Fills the header rows' character/Cyrillic text: what is already known comes from the cache,
        only the fonts without an entry are parsed (in the background)."""
        cache = self._sdf_coverage_cache
        for g in groups:
            if g.group_id in cache:
                self.sdf_group_model.set_coverage(g.group_id, cache[g.group_id])
        missing = [g for g in groups if g.group_id not in cache]
        if not missing:
            return
        from sdf_coverage import SDFCoverageWorker
        worker = SDFCoverageWorker(missing, self, should_pause=self._background_busy)
        worker.result.connect(self._on_sdf_coverage)
        self._sdf_coverage_worker = worker
        worker.start()

    def _on_sdf_coverage(self, group_id: str, text: str) -> None:
        self._sdf_coverage_cache[group_id] = text
        self.sdf_group_model.set_coverage(group_id, text)

    def on_object_patched(self, obj) -> None:
        """An object was edited/imported/generated: if it is the font of an SDF group its character
        coverage changed (for example after generating glyphs), so forget the old text and read it again;
        the tree's other rows (sizes) are repainted too."""
        self.environment_view.refresh_marks()   # its file is «изменён» now (the «Окружение» tab)
        model = self.sdf_group_model
        stale = [g for g in model._all_groups if g.font.get("obj_ref") is obj]
        if not stale:
            model.refresh_rows()
            return
        for g in stale:
            self._sdf_coverage_cache.pop(g.group_id, None)
            model.set_coverage(g.group_id, "")
        model.refresh_rows()
        if self.left_view_stack.currentIndex() == 1:
            self._stop_sdf_coverage()
            self._start_sdf_coverage(model._all_groups)

    def _stop_sdf_background(self) -> None:
        """Stops ALL the SDF view's background work (groups build + coverage) — for teardown (close,
        a new load, an overwrite save) and for rebuilding the groups. Patch-triggered coverage
        refreshes use _stop_sdf_coverage() alone: they must not cancel a build in progress, whose
        result nothing would then re-request."""
        self._stop_sdf_build()
        self._stop_sdf_coverage()

    def _resume_sdf_background(self) -> None:
        """After _stop_sdf_background() with the same game still loaded (the save menu stops every background pass
        but a «Сохранить как…» keeps the game): finish what was stopped — the groups build again if it was cut off,
        else the coverage of the fonts still without it (the cache keeps what was read)."""
        if self.left_view_stack.currentIndex() != 1 or getattr(self, "env", None) is None:
            return
        if getattr(self, "_sdf_build_interrupted", False):
            self._refresh_sdf_groups()
        else:
            self._start_sdf_coverage(self.sdf_group_model._all_groups)

    def _stop_sdf_coverage(self) -> None:
        worker, self._sdf_coverage_worker = getattr(self, "_sdf_coverage_worker", None), None
        if worker is not None:
            worker.requestInterruption()
            worker.wait(5000)

    def _on_sdf_filter_changed(self, text: str) -> None:
        self.sdf_group_model.set_filter(text)
        self.sdf_tree_view.expandAll()
        self._span_sdf_group_rows()

    def _on_sdf_selection_changed(self, selected, deselected):
        """Same rules as on_selection_changed() for the main table: nothing is previewed for two or
        more selected rows (there is no single object to show, and reading several just because they
        were selected would be needless work on the way to a bulk action)."""
        selection = self.sdf_tree_view.selectionModel()
        rows = selection.selectedRows(0)
        if len(rows) > 1:
            self.preview_panel.show_multi_selection(len(rows))
            return
        current = selection.currentIndex()
        if not current.isValid() or not selection.isSelected(current):
            return
        item_data = self.sdf_group_model.item_at(current)
        if item_data is None:
            # A group header row itself — preview its font (the group's own
            # identity), rather than leaving whatever was previously shown.
            group = self.sdf_group_model.group_at(current)
            if group is not None:
                self.preview_panel.request_preview(group.font["obj_ref"])
            return
        self.preview_panel.request_preview(item_data["obj_ref"])

    def _show_sdf_tree_context_menu(self, pos):
        index = self.sdf_tree_view.indexAt(pos)
        if not index.isValid():
            return
        selection = self.sdf_tree_view.selectionModel()
        # Right-clicking a row outside the selection acts on just that row (as in the main table).
        if not selection.isRowSelected(index.row(), index.parent()):
            self.sdf_tree_view.setCurrentIndex(index)
        rows = selection.selectedRows(0)
        items = self.sdf_group_model.items_for_indexes(rows)
        if not items:
            return
        # Same rule as the main table: two or more selected rows -> the multi-object menu.
        if len(rows) > 1:
            self.object_actions.show_bulk_menu_for_items(items)
        else:
            self.object_actions.show_context_menu_for_item(items[0])
