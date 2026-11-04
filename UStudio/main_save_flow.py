"""The "save files" / "overwrite" / "return originals" flows of the main window.

Kept out of main.py as a mixin (MainWindow inherits it) because these methods form one
self-contained state machine — prepare, release the loaded files, commit, reload — that only
touches the window through its normal attributes (progress bar, status label, log, table
model, loader). Behaviour is unchanged; this is a mechanical move."""

from core.i18n import tr
import os
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QDialog, QApplication, QFileDialog, QMessageBox
from PyQt6 import sip
from PyQt6.QtCore import QThread, QObject
from config import CONFIG, LoadMode, LogLevel
from dialogs import RevertDialog
from save_thread import CustomPathSaveThread, OverwritePrepareThread, OverwriteCommitThread, RestoreThread
from core.save_manager import find_modified_roots, compute_base_dir, release_environment
from core.gc_freeze import collect_everything
from helpers import format_size
from UnityPy.files.BundleFile import clear_bundle_cache
from gui_common import exec_and_dispose


class SaveFlowMixin:
    # --- Save files (File menu) ---
    #
    # "Save files (custom path)" is a simple single-phase save: the destination
    # is a new location, so it can't conflict with anything this process
    # already has open — see _start_custom_save.
    #
    # "Save files (overwrite)" targets the EXACT files this app currently has
    # loaded (and, on Windows, still memory-mapped for reading) — confirmed
    # directly that even a same-process rename-over of such a file fails (see
    # core.save_manager._check_not_locked's docstring). The only way to make
    # overwrite actually work without asking the user to close and manually
    # copy files over is to release those mmaps ourselves:
    #   1. _close_dialogs_before_env_teardown() — every non-modal window this app
    #      can have open closed AND destroyed (not just hidden), since one of
    #      them (TextSearchDialog) was a real, confirmed source of a lingering
    #      reference to the whole Environment independent of MainWindow.env.
    #      (This same method is also called from start_loading_data() — see its
    #      own comment there for a separate real crash this exact gap caused
    #      on the LOAD path, not just Save.)
    #   2. prepare_overwrite() serializes every changed file to bytes while
    #      the Environment is still alive.
    #   3. Every reference to the Environment is dropped and garbage-collected
    #      (_on_overwrite_prepared).
    #   4. commit_overwrite() checks EVERY file's lock status first, in one
    #      pass, before writing ANY of them — so a lock on one file (typically
    #      something outside this app's own control at this point, now that
    #      step 1 has closed everything internal that could hold one) can't
    #      leave a batch of several files half-written.
    #   5. A fresh reload of the same folder/files, so the table comes back
    #      populated with the saved result.
    # See _start_overwrite_save/_on_overwrite_prepared/_on_overwrite_committed
    # below for the actual sequence.
    #
    # Both flows deliberately stop and report every failing file rather than
    # silently skipping it and continuing (unlike this app's bulk export/dump
    # actions, which do tolerate per-item failures) — a "Save" the user
    # believes succeeded is a much worse outcome than one that visibly stopped
    # and said exactly which file(s) and why: the whole point of Save is
    # knowing your edits actually reached disk.

    def _update_save_overwrite_enabled(self) -> None:
        """Reflects self._loaded_via_cab_browser onto the "Сохранить файлы игры"
        menu action itself, not just the runtime guard in on_menu_save_files() —
        greyed out (with an explanatory tooltip) is what actually tells the user
        it's unavailable, rather than letting them click it and read a refusal
        message every time."""
        reason = self._overwrite_block_reason()
        self.act_save_overwrite.setEnabled(not reason)
        self.act_save_overwrite.setToolTip(tr("Недоступно: {reason}", reason=reason) if reason else "")

    def _overwrite_block_reason(self) -> str:
        """Why "Сохранить файлы игры" (overwrite in place) must not run right now, or ""."""
        if self._loaded_via_cab_browser:
            return tr("таблица заполнена через «Просмотр архива (CAB)» — используйте «Сохранить файлы "
                      "игры как...», чтобы не перезаписывать весь исходный архив по частично загруженным данным.")
        # A platform source (an Android APK, ...) that cannot be written back — see
        # core/platform_sources.py; the reason text comes from its adapter.
        return tr(getattr(getattr(self, "env", None), "source_read_only_reason", "") or "")   # an N_() text

    def on_menu_save_files(self, mode: str):
        if mode == "overwrite" and self._overwrite_block_reason():
            self.log(tr("Сохранение с заменой недоступно: {reason}", reason=self._overwrite_block_reason()),
                     LogLevel.WARNING)
            return

        error = self._check_ready_for_save()
        if error:
            self.log(error, LogLevel.WARNING)
            return

        # Real reported crash: the preview panel's own background worker can
        # still be mid-read through a file's mmap at the exact moment overwrite
        # closes that same handle and tears down the Environment — see
        # PreviewPanel.pause_for_environment_teardown()'s docstring for the two
        # symptoms this produced (an intermittent "file in use" error, and a
        # silent crash with no error output). Must happen before
        # find_modified_roots() below reads obj_ref.data — a preview read never
        # modifies data, but stopping it first, unconditionally, is simpler
        # than reasoning about which of the two save modes actually need it.
        # Every background pass (background_passes.py), keeping the «Окружение» tab and the bookmarks: the game may
        # well stay loaded — every way out below that keeps it starts the passes again (_resume_background_readers).
        self._stop_background_readers(keep_loaded_views=True)

        groups = find_modified_roots(self.table_model.data_list)
        if not groups:
            self.log(tr("Нет изменённых объектов для сохранения."), LogLevel.WARNING)
            self._resume_background_readers()
            return

        if mode == "custom":
            dir_path = QFileDialog.getExistingDirectory(self, tr("Выберите папку для сохранения"))
            if not dir_path:
                self._resume_background_readers()
                return
            self._start_custom_save(groups, Path(dir_path))
        else:
            self._start_overwrite_save(groups)

    def _check_ready_for_save(self) -> Optional[str]:
        """Returns an error message if it's not safe to start a save right now,
        or None if it is. Neither mode may run while a load, another save, or a
        queued export/import is already in flight — all read/write the same
        obj_ref/assets_file state a save serializes, so overlapping them is a
        race, not just a UX inconvenience."""
        if getattr(self, "loader_thread", None) is not None and self.loader_thread.isRunning():
            return tr("Загрузка уже выполняется, дождитесь её завершения.")
        if self.save_thread is not None and self.save_thread.isRunning():
            return tr("Сохранение уже выполняется, дождитесь его завершения.")
        if self.task_queue_manager.list_tasks():
            return tr("В очереди задач есть выполняющийся или ожидающий экспорт/импорт — дождитесь его завершения.")
        return None

    def _close_dialogs_before_env_teardown(self) -> None:
        """Actually closes AND releases (not just hides) every non-modal
        window this app can have open — search tool, MonoBehaviour field
        exporter, CAB browser, task queue panel (every OTHER dialog here is
        modal, so it can't be open while the Save menu is even reachable).

        Originally written (and named) for the Save-overwrite path only —
        renamed once start_loading_data() ALSO needed it, see the real crash
        this second call site fixes in start_loading_data()'s own comment.
        Nothing below is actually overwrite-specific: it just guarantees no
        background reader is still touching whatever Environment is about to
        be dropped/replaced, which is equally true for "start a new load".

        Real reported bug this exists to fix, found TWICE: merely checking
        whether these were visible and refusing to proceed wasn't enough —
        closing a QDialog (the X button) just HIDES it, and TextSearchDialog
        in particular keeps the WHOLE loaded Environment alive via its own
        search thread (TextSearchThread.env) independently of
        MainWindow.env. The first fix (close() + deleteLater() +
        processEvents()) LOOKED right but was verified empirically to not
        actually work: deleteLater() only schedules destruction for whenever
        Qt's event loop next reaches the same nesting level it was posted
        at, which a plain processEvents() call from inside a menu handler
        does NOT reliably reach — confirmed directly with a throwaway
        QDialog holding a marked object: still alive (checked via weakref)
        after close()+deleteLater()+processEvents()+gc.collect(). Directly
        clearing the dialog's own __dict__ does NOT have that timing
        dependency — it drops every Python-level reference the instance
        holds immediately, regardless of when Qt gets around to the C++
        object's actual destruction — confirmed with the same test: the
        marked object was released right away.

        Order matters: processEvents() runs BEFORE __dict__.clear(), not
        after — the requestInterruption()+wait() below can leave the
        stopped thread's own finished/completion signal still queued for
        delivery to a slot on this dialog (e.g. TextSearchDialog.
        on_search_finished reading self.results_model); processEvents()
        first lets that queued signal be handled normally against the
        dialog's still-intact state, and only after that is __dict__
        cleared — confirmed directly: delivering the signal after clearing
        would otherwise hit a missing attribute.

        Real reported bug found a THIRD time: clearing only the dialog's own
        __dict__ still wasn't enough — TextSearchThread.env survived a real
        overwrite attempt regardless (confirmed via a live scan of the object
        graph at the time, which named a live env.files dict as the holder).
        Root cause, confirmed directly with a weakref-based test:
        TextSearchThread is constructed as `QThread.__init__(self)`
        with NO parent at all (unlike CabBrowserDialog's own workers, which
        do pass parent=self) — so dialog.findChildren(
        QThread) never found it in the first place, and its own __dict__
        (holding self.env) was never cleared. The same turned out to be true
        of TextSearchDialog's own SearchResultsModel (also constructed with
        no parent), which a QTableView keeps an independent internal Qt-level
        reference to via setModel() regardless of whether MainWindow's own
        Python attribute for it is dropped.

        Fixed by no longer relying on parent-child discovery alone: every
        QObject the dialog directly holds as a plain attribute (vars(dialog),
        catching anything constructed without a parent) is combined with
        every genuine Qt-child (findChildren(QObject) — catches the rest,
        transitively, without needing to know each dialog's own internal
        attribute names). Confirmed directly, replicating the exact
        thread+model+view shape real TextSearchDialog uses: dropping only the
        dialog's own reference left the marked object alive; clearing every
        one of these objects' own __dict__ released it immediately."""
        stop = getattr(self, "_stop_sdf_background", None)
        if stop is not None:
            stop()  # its workers (groups build, coverage) read the loaded files
        # CRITICAL exclusion: every one of these dialogs holds a back-reference
        # to MainWindow itself (TextSearchDialog.main_window,
        # CabBrowserDialog.main_window — all literally `self`, since this
        # method IS a MainWindow method), and
        # TaskQueuePanel holds the shared, app-lifetime task_queue_manager as
        # ._manager. vars(dialog).values() below can't tell "the dialog owns
        # this" from "the dialog merely references this" — a real, severe bug
        # this exact gap caused: clearing __dict__ on `self` (MainWindow)
        # wiped every one of ITS OWN attributes, including progress_bar,
        # crashing the very next line that touched it. Anything in this set
        # is a shared/long-lived object that must survive the dialog being
        # discarded, never a candidate for clearing.
        #
        # protected_ids is built two ways, deliberately not just one hand-
        # curated list: explicit known shared objects (task_queue_manager)
        # PLUS every actual Qt ANCESTOR of each dialog (walking .parent()) —
        # an ancestor can never legitimately be something the dialog owns, so
        # this is a structural guarantee that holds even for a future dialog
        # whose own back-reference attribute isn't named "main_window" and
        # so wouldn't be caught by a name-based check.
        protected_ids = {id(self.task_queue_manager)}

        for attr_name in ("search_tool_dialog", "cab_browser_dialog", "task_queue_panel", "scene_viewer_dialog",
                          "import_match_dialog", "field_table_dialog", "patch_relocation_dialog"):
            dialog = getattr(self, attr_name, None)
            if dialog is None:
                continue
            setattr(self, attr_name, None)

            ancestor_ids = set()
            ancestor = dialog.parent()
            while ancestor is not None:
                ancestor_ids.add(id(ancestor))
                ancestor = ancestor.parent()
            excluded_ids = protected_ids | ancestor_ids

            descendants = list(dialog.findChildren(QObject))
            seen_ids = {id(o) for o in descendants} | excluded_ids
            descendants.extend(
                v for v in vars(dialog).values() if isinstance(v, QObject) and id(v) not in seen_ids
            )
            descendants = [o for o in descendants if id(o) not in excluded_ids]

            for obj in descendants:
                if isinstance(obj, QThread) and obj.isRunning():
                    obj.requestInterruption()
                    obj.wait(3000)

            dialog.close()
            # Deliver anything a just-stopped thread already queued (e.g. its
            # own finished signal) BEFORE the dict clears below invalidate
            # the state those slots expect — see the docstring's "Order
            # matters" paragraph.
            QApplication.processEvents()
            for obj in descendants:
                obj.__dict__.clear()
            dialog.__dict__.clear()
            # A dialog that deletes itself when it finishes (the non-modal patch-import
            # list does) is already gone after the processEvents() above.
            if not sip.isdeleted(dialog):
                dialog.deleteLater()

    def _on_save_progress(self, current, total, status):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)
        self.status_label.setText(status)
        # Same reasoning as update_loading_progress(): keeps the GUI thread
        # responsive to Esc between files even though this loop is otherwise
        # entirely on the background thread. Reentrancy-guarded for the same
        # reason too — see that method's own comment; this is the handler a
        # real crash.log actually caught mid-recursion (this exact function
        # appeared on the stack twice in a row at the moment of a Windows
        # access violation).
        if self._save_progress_reentrant:
            return
        self._save_progress_reentrant = True
        try:
            QApplication.processEvents()
        finally:
            self._save_progress_reentrant = False

    def _on_save_thread_finished(self, thread):
        """Connected per-thread with the finishing thread bound as a default
        arg (thread=thread below) — NOT reading self.save_thread here, since
        the overwrite flow reassigns self.save_thread to a second (commit)
        thread while the first (prepare) thread's own finished signal is still
        in flight; using self.save_thread here would delete the wrong one."""
        if thread is self.save_thread:
            self.save_thread = None
        thread.deleteLater()

    # --- Save files (custom path) ---

    def _start_custom_save(self, groups, dest_root: Path):
        base_dir = compute_base_dir(CONFIG.load_mode, CONFIG.selected_dir, CONFIG.selected_files, getattr(self, "env", None))

        self.progress_bar.show()
        self.esc_hint_label.show()
        self._set_menus_locked_for_load(True)
        self.status_label.setText(tr("Сохранение... {done}/{total}", done=0, total=len(groups)))

        thread = CustomPathSaveThread(groups, dest_root, base_dir, parent=self)
        self.save_thread = thread
        thread.progress_signal.connect(self._on_save_progress)
        thread.finished_signal.connect(lambda count, rows, d=dest_root: self._on_custom_save_finished(count, rows, d))
        thread.error_signal.connect(self._on_save_error)
        thread.cancelled_signal.connect(self._on_save_cancelled)
        # The game stays loaded after a save to another folder, whatever the outcome: the background passes that
        # on_menu_save_files() stopped start again (after the handlers above: connected later).
        for signal in (thread.finished_signal, thread.error_signal, thread.cancelled_signal):
            signal.connect(lambda *_args: self._resume_background_readers())
        thread.finished.connect(lambda t=thread: self._on_save_thread_finished(t))
        thread.start()

    def _on_custom_save_finished(self, count: int, rows: list, dest_root: Path):
        self.progress_bar.hide()
        self.esc_hint_label.hide()
        self._set_menus_locked_for_load(False)
        # No table refresh here — unlike overwrite, save_to_custom_path()
        # deliberately leaves obj_ref.data/is_changed alone (see its own
        # docstring): the game's actual files were never touched, so the
        # Изменено asterisk correctly keeps showing a real pending edit.
        self.status_label.setText(tr("Сохранено файлов: {count}", count=count))
        self.log_with_folder_link(tr("Файлы успешно сохранены: {folder}", folder=dest_root), dest_root)

    def _on_save_error(self, message: str):
        self.progress_bar.hide()
        self.esc_hint_label.hide()
        self._set_menus_locked_for_load(False)
        self.status_label.setText(tr("Ошибка сохранения."))
        self.log(message, LogLevel.ERROR)

    def _on_save_cancelled(self):
        self.progress_bar.hide()
        self.esc_hint_label.hide()
        self._set_menus_locked_for_load(False)
        self.status_label.setText(tr("Сохранение отменено пользователем."))
        self.log(tr("Сохранение отменено пользователем."), LogLevel.WARNING)

    # --- Save files (overwrite) — two-phase, see the section comment above ---

    def _start_overwrite_save(self, groups):
        # Confirm before silently destroying any open tool window with state
        # a user might actually care about (search results, a browsed CAB
        # archive, ...) — _close_dialogs_before_env_teardown() below doesn't
        # just hide these, it tears them down (see its own docstring for
        # why that's necessary). task_queue_panel isn't asked about here even
        # though it's also closed — it's just a status view, nothing to lose.
        #
        # isVisible(), not "is not None": open_text_search_tool()/
        # open_cab_browser() deliberately keep the SAME instance alive across
        # close/reopen (a singleton-dialog pattern, so search results/the
        # browsed archive survive being closed and reopened) — closing either
        # via the X button just hides it, it doesn't clear the attribute back
        # to None or destroy the object. Real reported bug: checking "is not
        # None" meant this prompt fired on EVERY save for the rest of the
        # session the instant either dialog had been opened once, even long
        # after the user closed it — isVisible() reflects whether it's
        # actually on screen right now, which is what should gate a "this
        # will close an open window" warning. _close_dialogs_before_env_teardown()
        # below is intentionally NOT changed the same way — a hidden-but-alive
        # TextSearchDialog can still hold a live Environment reference via its
        # own search thread (see its own docstring), so that teardown must
        # still run unconditionally regardless of visibility.
        any_dialog_open = any(
            getattr(self, attr, None) is not None and getattr(self, attr).isVisible()
            for attr in ("search_tool_dialog", "cab_browser_dialog", "scene_viewer_dialog", "import_match_dialog",
                         "field_table_dialog", "patch_relocation_dialog")
        )
        if any_dialog_open:
            reply = QMessageBox.question(
                self, tr("Сохранение (перезапись)"),
                tr("Сохранение закроет открытые диалоговые окна и инструменты. Продолжить?"),
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._resume_background_readers()
                return

        # Must happen BEFORE anything else here — see
        # _close_dialogs_before_env_teardown's docstring: these windows can hold
        # their own independent reference to the loaded Environment, which
        # would otherwise survive _on_overwrite_prepared's own teardown later
        # and show up as an unexplained "file is locked" failure.
        self._close_dialogs_before_env_teardown()
        # The overwrite goes ahead: from here the loaded game is on its way out (its views too, as before).
        self._stop_background_readers()

        # Must be read BEFORE the prepare thread starts: it closes every modified root's own
        # handle, and reading PlayerSettings through a closed reader fails ("operation
        # forbidden on released memoryview") — the version would silently be missing from
        # the backup record. commit_overwrite() itself runs after the Environment is gone,
        # with nothing left to resolve this FROM (see its own docstring on game_version).
        from core.loader import resolve_game_version
        self._pending_game_version = resolve_game_version(self.env) if self.env is not None else ""

        self.progress_bar.show()
        self.esc_hint_label.show()
        self._set_menus_locked_for_load(True)
        self.status_label.setText(tr("Подготовка к сохранению... {done}/{total}", done=0, total=len(groups)))

        thread = OverwritePrepareThread(groups, parent=self)
        self.save_thread = thread
        thread.progress_signal.connect(self._on_save_progress)
        thread.prepared_signal.connect(self._on_overwrite_prepared)
        thread.error_signal.connect(self._on_save_error)
        thread.cancelled_signal.connect(self._on_save_cancelled)
        thread.finished.connect(lambda t=thread: self._on_save_thread_finished(t))
        thread.start()

    def _on_overwrite_prepared(self, prepared: list):
        """Every changed file's new bytes are already serialized in memory at
        this point, and each one's own underlying OS handle/mmap has already
        been closed explicitly (root_file.close_source_handle(), called from
        inside core.save_manager.prepare_overwrite right after that file's
        .save() — see its docstring) — that's the actual, bounded fix for
        overwrite failing while this app still has a file open, replacing an
        earlier approach that tried to hunt down and drop every Python
        reference that might still exist somewhere in the app instead.

        The whole loaded Environment is still dropped and reloaded fresh
        below regardless — no longer load-bearing for the lock itself, but
        the SerializedFile/ObjectReader Python wrappers are permanently
        unusable now that their readers are disposed (reading through a
        released mmap view would raise), so the table needs refreshing
        either way once any file in the batch has been prepared.

        Real reported crash (Windows access violation, confirmed via a
        crash.log pointing at on_loading_finished — the reload this method
        triggers below): PreviewPanel.pause_for_environment_teardown()'s own
        docstring already names this exact call site as one of the two cases
        it exists to guard ("Save game files (overwrite) ... tears down and
        reloads the whole Environment"), but the actual call was never wired
        in here — only start_loading_data() (the OTHER case, a fresh manual
        load) had it. Without it, PreviewPanel's own background worker could
        still be mid-read through a row's mmap at the exact moment
        release_groups()/_clear_loaded_session() below release it out from
        under it. Must run before either of those."""
        self._stop_background_readers()

        # Read in _start_overwrite_save, before prepare closed the handles.
        game_version = getattr(self, "_pending_game_version", "")
        self._pending_game_version = ""

        if isinstance(self.save_thread, OverwritePrepareThread):
            self.save_thread.release_groups()

        # Close EVERY file's handle of the Environment being discarded, not just
        # the modified roots' (prepare_overwrite did those). Real reported failure:
        # a second overwrite, of a file that was merely loaded (not modified) during
        # the first, failed with "held by this program" — its old mapping was still
        # open because a closure kept one of its ObjectReaders alive. See
        # core.save_manager.release_environment()'s docstring.
        release_environment(self.env)
        self._clear_loaded_session()
        clear_bundle_cache()
        collect_everything()

        self.status_label.setText(tr("Сохранение... {done}/{total}", done=0, total=len(prepared)))

        thread = OverwriteCommitThread(prepared, make_backup=CONFIG.backup_before_overwrite,
                                       backup_keep=CONFIG.backup_keep_latest, parent=self,
                                       game_version=game_version)
        thread.backup_signal.connect(self._on_backup_created)
        self.save_thread = thread
        thread.progress_signal.connect(self._on_save_progress)
        thread.finished_signal.connect(self._on_overwrite_committed)
        thread.error_signal.connect(self._on_overwrite_commit_error)
        thread.finished.connect(lambda t=thread: self._on_save_thread_finished(t))
        thread.start()

    # --- Revert to the original files (from backups) ---

    def _revert_scope(self):
        """Files/folders of what is open right now — the backups of THIS game are shown first."""
        if getattr(self, "env", None) is None:
            return None
        paths = []
        if CONFIG.load_mode == LoadMode.FOLDER and CONFIG.selected_dir:
            paths.append(CONFIG.selected_dir)
        else:
            paths.extend(CONFIG.selected_files)
        source_dir = getattr(self.env, "source_data_dir", "")
        if source_dir:
            paths.append(source_dir)
        return paths or None

    def _loaded_file_paths(self) -> list:
        """Every file on disk the open Environment is using — the files it was loaded from and the
        resource files (.resS/.resource) pulled in on demand, which may live outside the chosen folder."""
        env = getattr(self, "env", None)
        if env is None:
            return []
        paths = [k for k in getattr(env, "files", {}) if isinstance(k, str) and os.path.isabs(k)]
        paths += [v for v in getattr(env, "_cab_source_names", {}).values() if isinstance(v, str) and os.path.isabs(v)]
        return paths

    def _restore_touches_loaded(self, originals: list) -> bool:
        """True if any of the files about to be put back is part of what is open right now. Only then
        does the open data have to be released and reloaded; restoring another game's files (or any
        file that is not loaded) must leave the table alone."""
        from core.backup import path_within
        if getattr(self, "env", None) is None:
            return False
        scope = (self._revert_scope() or []) + self._loaded_file_paths()
        return any(path_within(original, scope) for original in originals)

    def on_menu_revert_originals(self):
        from core.backup import originals_with_backups
        error = self._check_ready_for_save()
        if error:
            self.log(error, LogLevel.WARNING)
            return
        entries_all = originals_with_backups()
        scope = self._revert_scope()
        entries = originals_with_backups(within=scope) if scope else entries_all
        if not entries_all:
            QMessageBox.information(
                self, tr("Резервные копии"),
                tr("Резервных копий пока нет. Включите резервное копирование в настройках — "
                   "тогда копии будут создаваться перед каждой перезаписью файлов игры."))
            return
        note = ""
        if scope and not entries:
            note = tr("Для открытой сейчас игры резервных копий нет.")
        # Files outside the open game are put back with the window open (it closes only when the open
        # game has to be released and reloaded for the restore).
        dialog = RevertDialog(entries, self, all_entries=entries_all, scope_note=note,
                              restore_here=lambda originals: not self._restore_touches_loaded(originals),
                              keep_latest=CONFIG.backup_keep_latest, log=self.log)
        if exec_and_dispose(dialog) != QDialog.DialogCode.Accepted:
            return
        whole = [(dialog.copy_path_for(o), o) for o in dialog.selected_originals()]
        whole = [p for p in whole if p[0]]
        if not whole:
            return

        # "had_data" below means: the restore touches what is open, so it is released first and
        # reloaded afterwards. Restoring files of a game that is not open does neither.
        had_data = self._restore_touches_loaded([o for _copy, o in whole])
        if had_data:
            if find_modified_roots(self.table_model.data_list):
                reply = QMessageBox.question(
                    self, tr("Резервные копии"),
                    tr("Есть несохранённые изменения — при возврате оригиналов они будут потеряны. Продолжить?"))
                if reply != QMessageBox.StandardButton.Yes:
                    return
            self._stop_background_readers()
            # The files being replaced may be open (memory-mapped) here: let them go first,
            # exactly as an overwrite save does.
            self._close_dialogs_before_env_teardown()
            release_environment(self.env)
            self._clear_loaded_session()
            clear_bundle_cache()
            collect_everything()

        self.progress_bar.show()
        self._set_menus_locked_for_load(True)
        self.status_label.setText(tr("Возврат оригиналов..."))
        thread = RestoreThread([], dialog.safety_copy(), CONFIG.backup_keep_latest, parent=self, pairs=whole)
        thread.finished_signal.connect(lambda done, r=had_data: self._on_revert_job_done(done, r))
        self.save_thread = thread
        thread.error_signal.connect(lambda msg, r=had_data: self._on_restore_error(msg, r))
        thread.finished.connect(lambda t=thread: self._on_save_thread_finished(t))
        thread.start()

    def _after_restore(self, reload: bool) -> None:
        self.progress_bar.hide()
        if reload:
            self.start_loading_data()  # same files/folder as before, now as they are on disk
        else:
            self._set_menus_locked_for_load(False)
            self.status_label.setText(tr("Готово."))

    def _on_revert_job_done(self, restored_paths: list, reload: bool) -> None:
        if restored_paths:
            self.log(tr("Возвращено файлов: {count}.", count=len(restored_paths)))
        self._after_restore(reload)

    def _on_restore_error(self, message: str, reload: bool) -> None:
        self.log(message, LogLevel.ERROR)
        self._after_restore(reload)

    def _on_backup_created(self, folder: str) -> None:
        from core.backup import backups_total_size, folder_size
        from pathlib import Path
        here = format_size(folder_size(Path(folder)))
        total = format_size(backups_total_size(Path(folder).parent))
        self.log_with_folder_link(
            tr("Создана резервная копия оригиналов: {folder} ({size}; все резервные копии занимают {total})",
               folder=folder, size=here, total=total), folder)

    def _on_overwrite_committed(self, count: int):
        self.log(tr("Файлы успешно перезаписаны."))
        self._reload_after_overwrite(count)

    def _on_overwrite_commit_error(self, message: str):
        # The Environment was already torn down before this phase started (see
        # _on_overwrite_prepared) — there's no "clean" state left to fall back
        # to other than reloading whatever's now actually on disk. Always a
        # safe, real state either way: commit_overwrite checks every file's
        # lock BEFORE writing any of them, so a lock error here means NOTHING
        # was written at all; a write error (disk full, permissions) partway
        # through the second pass can leave some files newly-saved and others
        # still original, but never a truncated/corrupt file (see
        # save_manager._write_file's write-then-replace).
        self.log(message, LogLevel.ERROR)
        self.log(
            tr("Часть файлов не сохранена, но данные уже были выгружены из памяти для записи — "
               "выполняется повторная загрузка текущего состояния с диска."), LogLevel.WARNING,
        )
        self._reload_after_overwrite(0)

    def _reload_after_overwrite(self, count: int):
        self.esc_hint_label.hide()
        if count:
            self.log(tr("Сохранено файлов: {count}. Выполняется повторная загрузка...", count=count),
                     LogLevel.WARNING)
        # start_loading_data() re-locks the menus and shows its own progress
        # itself — no need to unlock/hide anything here first, and CONFIG's
        # load_mode/selected_dir/selected_files are untouched since the
        # original load, so this reloads the exact same folder/files, now
        # reflecting whatever was just written to disk.
        self.start_loading_data()
