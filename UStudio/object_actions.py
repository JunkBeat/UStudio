"""Row context-menu actions (edit/import/export/dump) — split out of MainWindow,
which previously owned this alongside window chrome, data loading, and preview
rendering. Holds a `main_window` back-reference for the pieces of UI it doesn't
own itself (status bar, the table model, the preview panel) — the same pattern
dialogs/cab_browser_dialog.py's CabBrowserDialog already uses.

Every file-touching action here (single export, single JSON dump, JSON import, bulk
dump-by-script-type) goes through main_window.task_queue_manager instead of running
synchronously or spinning up its own QThread — see task_queue.py's module docstring
for why that's what actually guarantees export and import can never run at the same
time or interleave."""

from core.i18n import tr
import os
import subprocess

from PyQt6.QtWidgets import QDialog, QMessageBox

from config import LogLevel
from dialogs import JsonEditorDialog
from core.object_preview import (
    partial_parse_block_reason, resolve_display_size, prepare_dict_for_json_edit, restore_dict_from_json_edit,
)
from core.sdf_generator import MODE_REPLACE_ALL
from gui_common import exec_and_dispose
from actions_menu import MenuActionsMixin
from actions_export import ExportActionsMixin
from actions_import import ImportActionsMixin
from actions_sdf import SdfActionsMixin


class ObjectActionsController(MenuActionsMixin, ExportActionsMixin, ImportActionsMixin, SdfActionsMixin):
    """Everything the row context menu can do to a single selected object (or, for
    "dump by script type", every object sharing its name): edit in place, import/
    export JSON, export in a type-appropriate format, view metadata. File-touching
    actions are enqueued onto main_window.task_queue_manager rather than run
    directly — try_cancel() plugs into MainWindow's existing Esc-cancel handling by
    cancelling whichever queued task is currently running, alongside loader_thread."""

    def __init__(self, main_window):
        self.main_window = main_window
        # task_id -> {"title": str, "on_success": Optional[Callable[[], None]]} —
        # only for tasks THIS controller enqueued; looked up (and popped) once the
        # queue reports a terminal state for that task_id.
        self._task_followups: dict = {}

        qm = main_window.task_queue_manager
        qm.task_finished.connect(self._on_task_finished)
        qm.task_failed.connect(self._on_task_failed)
        qm.task_cancelled.connect(self._on_task_cancelled)

    # (the context menus — one object, several objects — live in actions_menu.py — MenuActionsMixin)

    # --- Edit a single object in place (not queued — no file I/O, just an in-memory patch) ---

    def edit_row_activated(self, index) -> None:
        """Double-click or Enter on a table row = the context menu's first entry, «Отредактировать данные».
        QAbstractItemView.activated fires for both. Does nothing for a virtual select-all, for a selection of
        several rows (Enter then means nothing in particular) or while the table is locked."""
        win = self.main_window
        view = win.table_view
        if not index.isValid() or view.select_all_active or not view.isEnabled():
            return
        if len(view.selectionModel().selectedRows()) > 1:
            return
        source_row = win.proxy_model.mapToSource(index).row()
        if 0 <= source_row < len(win.table_model.data_list):
            self.open_json_editor_dialog(win.table_model.data_list[source_row])

    def open_json_editor_dialog(self, item_data: dict):
        """Invokes the modal editor and overwrites the UnityPy object's raw data."""
        win = self.main_window
        obj = item_data.get("obj_ref")
        blocked = partial_parse_block_reason(obj)
        if blocked:
            QMessageBox.warning(win, tr("Редактирование недоступно"), blocked)
            return

        try:
            raw_dict = obj.parse_as_dict()
        except Exception as e:
            win.status_label.setText(tr("Не удалось прочитать дамп: {error}", error=e))
            return

        # Real reported bug: parse_as_dict() can contain raw bytes (a
        # TypelessData field, a Mesh's index buffer, ...) for types
        # beyond MonoBehaviour, which used to crash JsonEditorDialog's
        # json.dumps() outright — wrapped into a JSON-safe, round-trip
        # reversible marker (restored below before patch()) so editing
        # actually works for any type, not just ones that happen to have
        # no such fields. A field big enough that hex-encoding it inline
        # would make the dialog slow to open (a texture's pixels, an
        # AudioClip's samples, ...) is instead OMITTED from the text —
        # `omitted` collects its real bytes, keyed by the placeholder's
        # own marker id, so restore_dict_from_json_edit() below can splice
        # them back in automatically as long as the user didn't touch that
        # id. See prepare_dict_for_json_edit()'s docstring — this replaced
        # an earlier flat "refuse the whole dialog if any field is over
        # 1 MB" gate, which both stayed slow well under that cap and
        # banned editing every OTHER field of an object too.
        omitted: dict = {}
        current_dict = prepare_dict_for_json_edit(raw_dict, omitted)

        dialog = JsonEditorDialog(win, current_dict)
        if exec_and_dispose(dialog) == QDialog.DialogCode.Accepted and dialog.result_data is not None:
            try:
                obj.patch(restore_dict_from_json_edit(dialog.result_data, omitted))
                self._refresh_row_after_patch(item_data, obj)
                win.status_label.setText(tr("Данные объекта успешно изменены в памяти"))
            except Exception as e:
                QMessageBox.critical(win, tr("Ошибка сохранения"), tr("Не удалось изменить объект:\n{error}", error=e))

    def show_in_explorer(self, item_data: dict):
        """Opens Windows Explorer with the object's parent file selected — works
        for both a loose file and a bundle-internal object (walks .parent up to
        the top-level physical file either way). Needs no new path bookkeeping:
        Environment.load_file() already stores the original full path STRING as
        the env.files dict key (captured before the local variable is reassigned
        to an opened buffer/mmap), even though File.__init__ itself only keeps the
        basename — see UnityPy/environment.py."""
        win = self.main_window
        obj = item_data.get("obj_ref")
        try:
            current = obj.assets_file
            while current.parent is not current.environment:
                current = current.parent
            path = next((p for p, f in win.env.files.items() if f is current), None)
        except Exception as e:
            win.log(tr("Не удалось определить файл объекта: {error}", error=e), LogLevel.WARNING)
            return
        if not path:
            win.log(tr("Не удалось определить путь к файлу объекта (источник, возможно, был удалён или перемещён)."), LogLevel.WARNING)
            return
        self.reveal_path_in_explorer(path)

    def find_loaded_file_path(self, file_name: str):
        """Full path of a loaded top-level file by its base name (the text search
        keeps only the base name for a whole-file/binary hit), or None."""
        env = getattr(self.main_window, "env", None)
        candidates = list(getattr(env, "files", {}) or {}) + list(getattr(env, "unloaded_binary_files", None) or [])
        for path in candidates:
            if os.path.basename(path) == file_name:
                return path
        return None

    def reveal_path_in_explorer(self, path: str):
        win = self.main_window
        try:
            # Real reported bug: this used to combine the flag and path into ONE
            # argv string ("/select,{path}") — fine for a path with no spaces, but
            # for a path that DOES contain spaces (a real case: "Truck-kun is
            # Supporting Me from Another World"), Windows' own argv-to-command-line
            # quoting (subprocess.list2cmdline) wraps that WHOLE string in quotes
            # since it contains spaces, producing `explorer "/select,C:\...\file"`
            # — confirmed via subprocess.list2cmdline() directly, not assumed —
            # and explorer.exe does not parse "/select," correctly when it's
            # trapped INSIDE the same quoted token as the path; it silently falls
            # back to its default view (Documents) instead of selecting anything.
            # Passing the flag and path as two SEPARATE argv items lets Windows
            # quote only the path (which needs it), producing the standard,
            # documented-working `explorer /select, "C:\...\file"` form instead —
            # confirmed via the same list2cmdline() check.
            subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        except OSError as e:
            # explorer.exe can return a non-zero exit code on ordinary success —
            # this is best-effort, same try/except-only shape as _maybe_open_folder.
            win.log(tr("Не удалось открыть проводник: {error}", error=e), LogLevel.WARNING)

    # (imports — one file, Texture2DArray slices, into a selection, from a folder, sdf_map.txt — live in actions_import.py — ImportActionsMixin)

    # (exports — one object, several, by script/type, raw/content, JSON dumps — live in actions_export.py — ExportActionsMixin)

    def _refresh_row_after_patch(self, item_data: dict, obj):
        """Shared by open_json_editor_dialog and import_from_file (as a queued
        task's on_success follow-up): both end by replacing obj's raw bytes via
        obj.patch(...)/set_raw_data(...), which invalidates this row's cached size
        (and raw_bytes, if it had already been read once) — refreshes the local
        cache and tells the model/view the row is stale.

        Real reported bug: this used obj.byte_size directly, which is correct
        for most types but WRONG for the resource-backed ones (Texture2D/
        Texture2DArray/AudioClip/Mesh/VideoClip) — their Size column shows the
        real external-resource size (resolve_display_size(), resolved once at
        load time — see core/loader.py's own note on why), not the small
        header record obj.byte_size reports. After a content-raw/converted
        import that appends new resource bytes and repoints
        m_Resource/m_StreamData/m_ExternalResources at them, byte_size stays
        essentially unchanged (still just the header) while the real resource
        size actually changed — so the Size column kept showing the OLD
        value, or a value that never reflected the resource at all. Reusing
        resolve_display_size() here is the same call the initial load already
        makes, so the two can never disagree."""
        win = self.main_window
        item_data["size"] = resolve_display_size(obj)
        on_patched = getattr(win, "on_object_patched", None)
        if on_patched is not None:
            on_patched(obj)   # SDF view: coverage text and sizes of the tree rows
        scene_viewer = getattr(win, "scene_viewer_dialog", None)
        if scene_viewer is not None:
            scene_viewer.object_patched(obj)   # a kept scene hierarchy of this file is read again
        if "raw_bytes" in item_data:
            item_data["raw_bytes"] = obj.get_raw_data()

        row = win.table_model.find_row(item_data)
        if row is None:
            # an object whose type the load left out: its edit adopted it into the file (see _add_row_for_adopted)
            add_row = getattr(win, "_add_row_for_adopted", None)
            new_item = add_row(obj) if add_row is not None else None
            if new_item is not None:
                row = win.table_model.find_row(new_item)
        if row is not None:
            top_left = win.table_model.index(row, 0)
            bottom_right = win.table_model.index(row, win.table_model.columnCount() - 1)
            win.table_model.dataChanged.emit(top_left, bottom_right)

        # The Quick Filters Bar's "Изменено" toggle (object_table.py's
        # modified_only) reads obj.data is not None live per row — dataChanged
        # above repaints the "Изменено" column's asterisk correctly, but a row
        # that just BECAME modified (or, via undo-like re-import, un-modified)
        # can also need to newly appear/disappear from that filter entirely,
        # which only invalidateFilter() actually re-evaluates. Cheap: this
        # only runs on a genuine user edit, not per-frame.
        if win.proxy_model.modified_only:
            win.proxy_model.invalidateFilter()

        # Only re-run the preview if `obj` is the object CURRENTLY selected/
        # shown in the main table — real reported bug: this used to fire
        # unconditionally whenever anything was selected at all, so editing an
        # object from elsewhere (e.g. the text search tool's own context menu,
        # which can edit any match regardless of what's selected in the main
        # table) hijacked the preview panel away to show that edited object
        # instead of whatever the user actually had selected there.
        #
        # "Currently shown" is asked of the preview panel itself, not read off the
        # main table's selection: the object can just as well be shown because it
        # was picked in the SDF tree (the table's selection is then unrelated or
        # empty, and the preview used to stay stale after an import/generation).
        if win.preview_panel.is_showing(obj):
            win.preview_panel.request_preview(obj)


    # (SDF fonts — export one / all, generate characters — live in actions_sdf.py — SdfActionsMixin)


    # --- Esc-cancel + queue task outcome handling ---

    def try_cancel(self) -> bool:
        """Called from MainWindow.keyPressEvent's Esc handling — cancels whichever
        queued export/import task is currently running, if any (at most one, ever —
        see task_queue.py's module docstring). Returns whether there was anything to
        cancel, matching the shape of the loader_thread check it's tried alongside."""
        running = self.main_window.task_queue_manager.running_task()
        if running is not None:
            self.main_window.task_queue_manager.cancel_task(running.task_id)
            return True
        return False

    def _on_task_finished(self, task_id, result):
        followup = self._task_followups.pop(task_id, None)
        folder = followup.get("folder") if followup else None
        # Real reported issue: a single-object export whose whole result is
        # "Пропущено: ..." (export_object/export_object_content_raw declining
        # because there's genuinely nothing to write — an empty texture, data
        # stored inline with no external resource, ...) still showed the
        # folder link, even though no file was ever written there. The
        # "Пропущено: " prefix is this file's own established convention for
        # exactly this case (see export_object_content_raw/export_selected_object
        # above) — a bulk task's own aggregate summary never starts with it
        # (those use "Экспортирован(о)..."/_format_bulk_result wording even
        # when some individual items were skipped), so checking it here only
        # ever suppresses the link for the single-item nothing-was-written case.
        skipped_only = isinstance(result, str) and result.startswith(tr("Пропущено:"))
        if result:
            # Real request: a clickable link straight to the output folder,
            # instead of having to copy the path out of the log by hand.
            # folder is set on every export-task followup above (the same
            # directory _maybe_open_folder() would open); log_with_folder_link
            # falls back to plain log() itself if folder is None.
            self.main_window.log_with_folder_link(result, None if skipped_only else folder)
        if followup is not None and followup.get("on_success") and not skipped_only:
            followup["on_success"]()

    def _on_task_failed(self, task_id, error):
        followup = self._task_followups.pop(task_id, None)
        title = followup.get("title") if followup else None
        self.main_window.log(tr("Ошибка задачи «{title}»: {error}", title=title, error=error) if title
                             else tr("Ошибка задачи очереди: {error}", error=error), LogLevel.ERROR)

    def _on_task_cancelled(self, task_id):
        followup = self._task_followups.pop(task_id, None)
        title = followup.get("title") if followup else None
        message = tr("Задача «{title}» отменена.", title=title) if title else tr("Задача очереди отменена.")
        self.main_window.log(message, LogLevel.WARNING)
