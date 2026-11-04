"""Loading data into the main window: clearing the previous session, starting the loader thread, progress,
errors/cancel, and filling the table when the load finishes (including the slow-fill announcement).

Kept out of main.py as a mixin (MainWindow inherits it), like main_save_flow.py. Behaviour is unchanged; this is a
mechanical move (every method body is byte-identical to its old place in main.py)."""


from core.i18n import tr
from PyQt6.QtWidgets import QDialog, QApplication

from config import CONFIG, LogLevel
from dialogs import LargeLoadDialog
from loader_thread import DataLoaderThread
from core.save_manager import release_environment
from helpers import reset_script_name_cache
from cab_collision_handler import handle_cab_collisions
from core.loader import restricted_indexed_types
from object_table import LegacyFilterProxyModel
from background_passes import BackgroundPasses

from UnityPy.files.BundleFile import clear_bundle_cache
from core import gc_freeze
from gui_common import exec_and_dispose


class LoadFlowMixin:
    # --- Data thread management ---

    def _clear_loaded_session(self):
        """Called right before a new load actually starts (not just when the
        previous one finishes) — a real reported request: starting a new game
        load used to leave the OLD table/preview/env fully visible and usable
        for however long the new scan/load takes, which is both confusing (the
        table looks "loaded" while a totally different game is being read in
        the background) and wasteful (the old Environment/objects stay
        referenced, doubling peak memory use for as long as both are alive).
        Drops the reference to self.env here so Python can reclaim it as soon
        as nothing else holds it — clear_bundle_cache() (called right after
        this, in start_loading_data()) handles the separate GlobalBlockCache."""
        # The game's objects were frozen after the load (on_loading_finished): their reference cycles must be
        # collectable again before the gc.collect() that every teardown path runs next (core/gc_freeze.py).
        gc_freeze.unfreeze()
        self._stop_usage_index()
        self.env = None
        self.raw_data_list = []
        self._loaded_via_cab_browser = False
        reset_script_name_cache()
        CONFIG.cab_index = None
        self._update_save_overwrite_enabled()
        self._last_previewed_obj = None
        self._forget_table_notice()     # its object belongs to the old rows
        self.table_model.replace_data([])
        self.filter_input.clear()
        self.proxy_model.set_type_script_filter(None, None)
        self.apply_table_filter()
        self.preview_panel.show_welcome()
        self._update_title()

    def start_loading_data(self):
        if getattr(self, "loader_thread", None) is not None and self.loader_thread.isRunning():
            self.log(tr("Загрузка уже выполняется, дождитесь её завершения."), LogLevel.WARNING)
            return
        # Same hazard as pause_for_environment_teardown() below, different
        # background thread: object_actions.py's queued export/import/dump
        # tasks (task_queue_manager) also read raw bytes through the CURRENT
        # environment's native readers, but — unlike a load — File/Settings/
        # Tools are NOT disabled while one runs, so this was reachable: start
        # a bulk export, then immediately start a new load before it finishes.
        # Unlike a preview read (bounded, ~instant, safe to just wait out),
        # an export/import task can legitimately run for minutes, so the
        # right behavior here is the same as the loader_thread check just
        # above — refuse and ask the user to wait/cancel, not block or race.
        running_task = self.task_queue_manager.running_task()
        if running_task is not None:
            self.log(
                tr("Выполняется задача «{title}» — дождитесь её завершения или отмените (Esc) перед новой "
                   "загрузкой.", title=running_task.title),
                LogLevel.WARNING,
            )
            return
        # Real reported crash (Windows access violation, confirmed via
        # crash.log): _clear_loaded_session() below drops self.env, which can
        # be the LAST reference to the previous Environment — if the user
        # selected an object right before starting this new load and its
        # preview is still being built on PreviewPanel's own background
        # worker, that worker can still be mid-read through the OLD
        # environment's mmap at the exact moment this teardown (plus
        # clear_bundle_cache() just below) releases it out from under it. Same
        # exact hazard already found and fixed once for the Save path — see
        # PreviewPanel.pause_for_environment_teardown()'s docstring.
        #
        # A SECOND, separate real crash of the identical shape (Windows access
        # violation, crash.log pointing at the NEW load's own folder scan —
        # helpers.ImportHelper.list_all_files() via core.loader._load_folder,
        # i.e. heap corruption surfacing on the next unrelated allocation
        # after the actual fault, not a bug in the scan itself) was traced
        # here to a gap PreviewPanel's own guard doesn't cover: TextSearchDialog
        # (tools.text_search_tool.TextSearchThread.env — holds the whole
        # Environment directly and can still be actively reading through
        # every loaded file's mmap, including raw binary reads across the
        # object table when "искать в бинарных данных" is enabled) and
        # CabBrowserDialog (once its own "Загрузить" has been used,
        # MainWindow.env literally IS the parsed CAB entry — self.env aliases
        # the exact same mmap-backed BundleFile the dialog's own background
        # worker can independently still be reading/rebuilding at any time)
        # are both persistent singletons that start_loading_data() never used
        # to touch at all — unlike loader_thread/task_queue_manager above,
        # NOTHING here refused/waited for either of them before proceeding.
        # This is the exact same class of gap _start_overwrite_save() already
        # had to close (three separate times — see
        # _close_dialogs_before_env_teardown()'s own docstring) for the
        # identical hazard on the Save path; a fresh load replaces self.env
        # just as completely as an overwrite does, so it needs the same
        # guarantee. No confirmation prompt here (unlike Save) — starting a
        # new load already unconditionally discards the current table/preview
        # with no "are you sure" (see _clear_loaded_session's own docstring),
        # so silently tearing down these tool windows too is consistent with
        # that existing behavior, not a new UX decision.
        self._close_dialogs_before_env_teardown()
        self._stop_background_readers()
        # A fresh load replaces the Environment just like an overwrite does, so it
        # needs the same explicit release — otherwise the old mappings stay open for
        # as long as anything (a dialog, a task closure) still references the old
        # objects, and a later overwrite of one of those files finds it locked.
        release_environment(self.env)
        self._clear_loaded_session()
        clear_bundle_cache()
        self.progress_bar.show()
        # Real reported bug: the bar previously kept whatever value/range it
        # was last left at — 0% on the very first load ever (its untouched
        # initial state), or 100% on any RELOAD (wherever the previous load's
        # own final update_loading_progress() call left it) — for the ENTIRE
        # scan/load phase, since that phase's own progress
        # (on_progress()/_render(), driven by progress_extended_signal) only
        # ever updates status_label's TEXT, never this widget. The bar only
        # starts moving once update_loading_progress() (the indexing phase,
        # a much later step) begins firing. Confirmed by a real user report
        # matching this exactly: "stuck at 0%" on the first load, "stuck at
        # 100%" on a reload, both correctly resolving once indexing started.
        # Indeterminate ("marquee") mode is the correct state for a phase
        # that has no reliable total yet — same convention this project's
        # own TaskQueuePanel already uses for exactly this "no real total
        # yet" case — rather than a static, misleadingly-precise 0% or a
        # stale leftover value from whatever the last load happened to end
        # at. update_loading_progress()'s own setMaximum(total)/setValue()
        # naturally exits this mode the moment real numbers are available.
        self.progress_bar.setRange(0, 0)
        self.esc_hint_label.show()
        self._set_menus_locked_for_load(True)
        self.log(tr("Идёт загрузка… Esc — прервать."), LogLevel.WARNING)
        # parent=self: every OTHER QThread subclass in this app (save_thread.py's
        # three, gui_workers.BackgroundWorker wherever it's constructed) is parented to a
        # stable, long-lived Qt object for exactly this reason — a QThread with NO
        # parent, reassigned to a fresh instance on every retry (as this one is,
        # once per load attempt) with the old Python reference simply dropped,
        # relies entirely on Python's own GC timing lining up with Qt's internal
        # signal-delivery bookkeeping for that now-finished thread instead of Qt's
        # own object-tree lifetime management doing it deterministically. Real
        # reported symptom this plausibly explains: a load that fails, followed
        # immediately by starting another one, silently closing the whole app —
        # exactly the "fail once, retry" shape a dangling QThread reference would
        # produce. TextSearchThread (tools/text_search_tool.py) had the identical
        # gap, fixed alongside this one.
        self.loader_thread = DataLoaderThread(parent=self)
        self.loader_thread.progress_extended_signal.connect(self.on_progress)
        self.loader_thread.progress_signal.connect(self.update_loading_progress)
        self.loader_thread.error_signal.connect(self.on_loading_error)
        self.loader_thread.finished_signal.connect(self.on_loading_finished)
        self.loader_thread.cancelled_signal.connect(self.on_loading_cancelled)
        self.loader_thread.large_load_signal.connect(self.on_large_load_detected)
        self.status_label.setText(tr("Загрузка..."))
        self.loader_thread.start()

    def update_loading_progress(self, current, total, status):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(status)
        # Fully drain the event queue on every delivery of this signal — otherwise
        # a tight CPU-bound loop in the background thread (indexing/bulk export) may
        # never give the GUI thread a chance to repaint or react to Esc until
        # the very end of the operation. Safe: Load/Settings/Tools are already
        # locked out while loading, so a second concurrent run is excluded.
        #
        # Reentrancy-guarded: real reported crash (Windows access violation)
        # showed the save-flow's own equivalent handler (_on_save_progress)
        # appearing on the call stack twice in a row — processEvents() here
        # dispatches whatever's queued, which can include ANOTHER delivery of
        # this exact signal if the background thread emits faster than the
        # GUI thread drains, and that nested call would processEvents() again
        # itself, and so on — unbounded reentrant depth with no Python
        # RecursionError to catch it, since each level is a genuine new C
        # call into Qt's event loop. Skipping the nested processEvents() call
        # (not the widget updates above, which stay cheap and always run)
        # breaks the cycle at one level deep instead of letting it grow.
        if self._load_progress_reentrant:
            return
        self._load_progress_reentrant = True
        try:
            QApplication.processEvents()
        finally:
            self._load_progress_reentrant = False

    def _set_menus_locked_for_load(self, locked: bool):
        """Settings, File, and Tools all get disabled for the duration of an active
        load/save — see the comments at their declaration in init_menu()."""
        self.settings_menu.setEnabled(not locked)
        self.file_menu.setEnabled(not locked)
        self.tools_menu.setEnabled(not locked)

    def on_loading_error(self, err_msg):
        self.log(err_msg, LogLevel.ERROR)
        self.status_label.setText(tr("Ошибка загрузки данных."))
        self.progress_bar.hide()
        self.esc_hint_label.hide()
        self._set_menus_locked_for_load(False)

    def on_loading_cancelled(self):
        self.log(tr("Операция прервана пользователем."), LogLevel.WARNING)
        self.status_label.setText(tr("Загрузка отменена пользователем."))
        self.progress_bar.hide()
        self.esc_hint_label.hide()
        self._set_menus_locked_for_load(False)

    # From this many rows the table fill is slow enough to warn about it in the status bar and the log.
    # With the legacy QSortFilterProxyModel proxy (USTUDIO_LEGACY_PROXY=1) a fill took a few seconds at 2M
    # rows with the window not repainting; with the NumPy index proxy it is well under a second even then
    # (0.45 s measured on the 1.95M-row Lego Party table), so the warning would be untrue far below this.
    TABLE_FILL_SLOW_ROWS = 300_000
    TABLE_FILL_SLOW_ROWS_INDEX = 5_000_000
    # Below this the fill is instant: no need to spend a repaint on announcing it.
    TABLE_FILL_PAINT_ROWS = 20_000

    def _table_fill_slow_rows(self) -> int:
        legacy = isinstance(self.proxy_model, LegacyFilterProxyModel)
        return self.TABLE_FILL_SLOW_ROWS if legacy else self.TABLE_FILL_SLOW_ROWS_INDEX

    def _announce_table_fill(self, count: int) -> None:
        """The loading thread is done, but the rows still have to be put into the table, and that happens
        on the GUI thread (the view needs the model here): for a huge load it is the longest silent
        step. Say what is going on BEFORE it starts — and paint it right now, since nothing repaints
        while the fill blocks the thread."""
        text = tr("Заполнение таблицы: {count} объектов…", count=f"{count:,}".replace(",", " "))
        slow = count >= self._table_fill_slow_rows()
        if slow:
            text += " " + tr("Это может занять продолжительное время, окно может перестать отвечать.")
        self.status_label.setText(text)
        self.esc_hint_label.hide()  # nothing to cancel any more: the load itself is finished
        self.progress_bar.setRange(0, 0)  # indeterminate: the fill has no meaningful total
        self.progress_bar.show()
        if slow:
            self.log(text, LogLevel.WARNING)
        if count >= self.TABLE_FILL_PAINT_ROWS and not self._load_progress_reentrant:
            self._load_progress_reentrant = True  # same guard as update_loading_progress()
            try:
                QApplication.processEvents()
            finally:
                self._load_progress_reentrant = False

    def on_loading_finished(self, data, env):
        self.env = env
        self.raw_data_list = data
        self._update_save_overwrite_enabled()
        self._fill_environment_view(env)    # the «Окружение» tab (also for a load with no table rows)
        self._bookmarks_attach(env)         # which rows have a star
        self._announce_table_fill(len(data))
        # A fresh load's object set has nothing to do with whatever type/script/quick filter was applied
        # before it — start unfiltered every time ("all checkboxes enabled by default after loading game
        # files"). Cleared BEFORE the data swap, without re-filtering: the swap below makes the proxy
        # rebuild its whole row mapping anyway (see reset_for_new_dataset()).
        self.proxy_model.reset_for_new_dataset()
        # replace_data(), not `data_list = data` + a bare layoutChanged.emit():
        # that pair is invalid for a wholesale dataset change and was the cause
        # of a native access violation right here on a reload (see
        # ObjectTableModel.replace_data()'s docstring). It also fixes the older
        # bug the two calls below were added for: layoutChanged did NOT clear
        # the view's selection/current index, so row 0 stayed "selected" by
        # INDEX across a reload although a completely different object now sat
        # there, and clicking it again fired no selectionChanged. A reset drops
        # both itself; the explicit calls stay as a cheap, harmless guarantee.
        self._forget_table_notice()     # its object belongs to the old rows
        self.table_model.replace_data(data)
        self.table_view.clearSelection()
        self.table_view.selectionModel().clearCurrentIndex()
        self.quick_filters_bar.refresh_files(data, reset_proxy=False)
        self.progress_bar.hide()
        self._set_menus_locked_for_load(False)
        self.esc_hint_label.hide()
        self.table_view.setSortingEnabled(True)
        self._update_title()

        handle_cab_collisions(env, self, self.log)

        if self.act_mode_sdf.isChecked():
            self._refresh_sdf_groups()

        if not data:
            self.preview_panel.show_welcome()
            self.log(
                tr("Загрузка завершена, но подходящие для таблицы объекты не найдены. "
                   "Несмотря на то, что таблица пустая, вы по-прежнему можете воспользоваться "
                   "инструментом для поиска текста в загруженных файлах"),
                LogLevel.WARNING
            )
            self.status_label.setText(tr("Загрузка завершена, объекты не найдены."))
            return

        # Nothing selects a row automatically after a load — without this, the
        # Preview tab keeps showing whatever show_welcome() was last given (at
        # construction, that's game_loaded=False's "Игра не загружена" text),
        # stale even though a game is now genuinely loaded and there's something
        # to select.
        self.preview_panel.show_welcome(game_loaded=True)

        self.status_label.setText(tr("Загружено объектов: {count}", count=len(data)))
        files = getattr(env, "loaded_files_count", None)
        self.log(tr("Загружено файлов: {files}, объектов: {count}", files=files, count=len(data)) if files is not None
                 else tr("Загружено объектов: {count}", count=len(data)))
        restricted = restricted_indexed_types(CONFIG.load_all_assets, CONFIG.indexed_types)
        if restricted:
            # A forgotten "only Texture2D" setting looks exactly like a game with nothing else in it.
            #self.log(f"Показаны следующие типы: {format_type_names(restricted, limit=10)} (см. настройки индексации). "
            #         , LogLevel.WARNING)
            self.status_label.setText(tr("Загружено объектов: {count} — действуют настройки индексации",
                                         count=len(data)))
        # Read the names/scripts of a big table in the background so a later Имя/Скрипт sort or
        # text search finds them ready (no-op for small tables).
        self.table_model.start_name_warmup()
        # «Используется в» (the «Сведения» tab): who refers to what, read in the background.
        self._start_usage_index(env)
        # Keep automatic full garbage collections off the loaded game: each walked all of it (~300 ms frozen GUI on
        # Phonopolis) and freed nothing. Undone in _clear_loaded_session (core/gc_freeze.py).
        gc_freeze.freeze_loaded()

    # --- Background passes that read the loaded game (background_passes.py) ---

    def _init_background_passes(self) -> None:
        """Registers every pass that reads the loaded files, in the order they used to be stopped by hand. Lambdas:
        each looks its owner up when called."""
        passes = BackgroundPasses()
        passes.register(tr("просмотр"), lambda: self.preview_panel.pause_for_environment_teardown())
        passes.register(tr("таблица"), lambda: self.table_model.stop_background_reads())
        passes.register(tr("фильтр таблицы"), lambda: self.proxy_model.stop_background_reads())
        passes.register(tr("«Используется в»"), lambda: self._stop_usage_index(drop_environment=False))
        passes.register(tr("SDF-шрифты"), lambda: self._stop_sdf_background())
        passes.register(tr("файл зависимости"), lambda: self._wait_for_dependency_load())
        self.background_passes = passes

    def _wait_for_dependency_load(self) -> None:
        """«Добавить их в таблицу» (main_navigation._load_dependency_into_table) reads one file's objects with the
        menus locked; it has no early exit, so a teardown waits it out (one file: bounded)."""
        worker = getattr(self, "_dependency_load_worker", None)
        if worker is not None and worker.isRunning():
            worker.wait(30000)

    def _background_busy(self) -> bool:
        """The user is scrolling, typing, clicking: background passes wait (core.progress.Pacer's should_pause)."""
        tracker = getattr(self, "_user_activity", None)
        return bool(tracker is not None and tracker.busy())

    # One at a time, what the user is looking at first. Each pass rests on its own (Pacer), but several resting
    # passes still take the GIL in turn and the GUI waits behind all of them: Phonopolis' SDF view right after a
    # load had the warm-up, the usage index, the SDF build and the SDF coverage reading at once — 4-8 GUI pauses
    # over 100 ms (up to 0.33 s) in 6 s, stacks dumped by faulthandler. So: the SDF passes (only in the SDF view)
    # wait for nobody; the usage index waits for them; the name warm-up (only a future Имя/Скрипт sort needs it)
    # waits for both. A search the user typed (the table proxy's background filter pass) comes first of all: the
    # index and the warm-up wait for it (Lego Party: the search and the index reading at once blocked the window
    # 62.5 s of a 65.8 s search).

    def _search_running(self) -> bool:
        proxy = getattr(self, "proxy_model", None)
        return bool(proxy is not None and getattr(proxy, "filter_pending", False))

    def _sdf_background_running(self) -> bool:
        build = getattr(self, "_sdf_build_worker", None)
        coverage = getattr(self, "_sdf_coverage_worker", None)
        return bool((build is not None and build.isRunning()) or (coverage is not None and coverage.isRunning()))

    def _index_should_wait(self) -> bool:
        return self._background_busy() or self._sdf_background_running() or self._search_running()

    def _warmup_should_wait(self) -> bool:
        runner = getattr(self, "usage_index_runner", None)
        return self._index_should_wait() or (runner is not None and runner.building)

    def _stop_background_readers(self, keep_loaded_views: bool = False) -> None:
        """Stops every background pass that reads the loaded files and waits for each — call before the files are
        released or replaced. Also drops the «Окружение» tab and the bookmarks' hold on the files (as
        _stop_usage_index() always did at these points), unless `keep_loaded_views`: the save menu, which may keep
        the game loaded (_resume_background_readers() then)."""
        self.background_passes.stop_all()
        if not keep_loaded_views:
            self._drop_environment_view()
            self._bookmarks_detach()

    def _resume_background_readers(self) -> None:
        """After _stop_background_readers(keep_loaded_views=True) when the game stayed loaded (nothing to save, the
        folder dialog cancelled, «Сохранить как…» finished/failed/cancelled, an overwrite declined): starts again
        what the stop cut off. Before, the usage index, the «Окружение» tab and the bookmark stars were gone for the
        rest of the session after any of those."""
        env = getattr(self, "env", None)
        if env is None:
            return
        self.table_model.resume_background_reads()
        self.proxy_model.resume_background_reads()
        self.table_model.start_name_warmup()
        if not self._loaded_via_cab_browser:       # an archive entry gets no index (load_entry_objects)
            self._start_usage_index(env)
        self._resume_sdf_background()

    def _start_usage_index(self, env) -> None:
        """Builds the game's usage index in a background thread (usage_index_runner.py); the preview's
        «Используется в» shows its progress, then the list. Paused while the user is active."""
        self._stop_usage_index(drop_environment=False)     # the same game: its «Окружение» tab stays
        from core.loader import collect_serialized_files
        from usage_index_runner import UsageIndexRunner
        runner = UsageIndexRunner(collect_serialized_files(env), should_pause=self._index_should_wait, parent=self)
        runner.progress.connect(self.preview_panel.on_usage_index_progress)
        runner.finished.connect(self.preview_panel.on_usage_index_finished)
        self.usage_index_runner = runner
        self.preview_panel.usage_runner = runner
        runner.start()

    def _stop_usage_index(self, drop_environment: bool = True) -> None:
        """Stops the usage index and WAITS for its thread — it reads objects through the game's files, which
        must not be closed or replaced under it (same rule as the table's name warm-up) — then drops it."""
        if drop_environment:
            # The «Окружение» tab and the bookmarks hold the game's files too, and every teardown point already
            # calls this.
            self._drop_environment_view()
            self._bookmarks_detach()
        runner = getattr(self, "usage_index_runner", None)
        if runner is None:
            return
        self.usage_index_runner = None
        self.preview_panel.usage_runner = None
        runner.stop()
        runner.deleteLater()

    def load_entry_objects(self, data: list, env, source_label: str = ""):
        """Loads an already-prepared list of objects (e.g. from the CAB browser — one
        internal file of an archive) into the main table, the same way a normal load does."""
        # Every pass still reading the old game (the index; also the preview, the table's reads, SDF — which this
        # point used not to stop). One archive entry gets no index («Используется в» hidden).
        self._stop_background_readers()
        gc_freeze.unfreeze()        # the old game is being replaced: its cycles must be collectable (gc_freeze.py)
        self.env = env
        self.raw_data_list = data
        # See its own declaration's comment — disables "Сохранить файлы игры"
        # (overwrite-in-place) while the table holds a CAB-browser-loaded entry.
        self._loaded_via_cab_browser = True
        self._update_save_overwrite_enabled()
        self._fill_environment_view(env)    # the archive entry's own files
        self._bookmarks_attach(env)
        self._announce_table_fill(len(data))
        # Same reasoning as on_loading_finished — this replaces the ENTIRE
        # dataset too (one archive entry's objects instead of another), so it
        # needs a real model reset, not a bare layoutChanged.
        self.proxy_model.reset_for_new_dataset()
        self._forget_table_notice()     # its object belongs to the old rows
        self.table_model.replace_data(data)
        self.table_view.clearSelection()
        self.table_view.selectionModel().clearCurrentIndex()
        self.quick_filters_bar.refresh_files(data, reset_proxy=False)
        self.progress_bar.hide()
        self.table_view.setSortingEnabled(True)

        if self.act_mode_sdf.isChecked():
            self._refresh_sdf_groups()

        if not data:
            self.preview_panel.show_welcome()
            self.status_label.setText(tr("Объекты не найдены ({source}).", source=source_label))
            self.log(tr("В «{source}» подходящие для таблицы объекты не найдены.", source=source_label),
                     LogLevel.WARNING)
            return

        self.preview_panel.show_welcome(game_loaded=True)
        self.status_label.setText(tr("Загружено объектов: {count} ({source})", count=len(data), source=source_label))
        self.log(tr("Загружено объектов из «{source}»: {count}", count=len(data), source=source_label))

    def on_large_load_detected(self, object_count, load_all, legacy_size_bytes, single_big_bundle):
        dlg = LargeLoadDialog(object_count, load_all, legacy_size_bytes, single_big_bundle, parent=self,
                              restricted_types=restricted_indexed_types(load_all, CONFIG.indexed_types))
        proceed = exec_and_dispose(dlg) == QDialog.DialogCode.Accepted
        self.loader_thread.submit_bundle_decision("continue" if proceed else "cancel")
