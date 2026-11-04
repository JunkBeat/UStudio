"""Going to an object from elsewhere in the main window: "go to object" from the preview (the preview shows it
at once; the table follows, or a thin notice above it says why it cannot), finding its row, loading a dependency
file into the table, revealing a row hidden by filters, and the quick-jump dialog.

Kept out of main.py as a mixin (MainWindow inherits it), like main_save_flow.py."""

from core.i18n import tr
from typing import Optional

from PyQt6.QtWidgets import QDialog, QMessageBox

from config import CONFIG, LogLevel
from tools import QuickJumpDialog
from core.object_preview import get_row_script_name, resolve_object_name
from core.loader import build_row_item, parse_dependency_file_objects
from core.patch_matching import adopted_without_row
from gui_workers import BackgroundWorker

from gui_common import exec_and_dispose


class NavigationMixin:
    def _edit_object_from_tree(self, obj):
        """Structure tree PPtr row -> "Отредактировать данные" — the referenced
        object usually already has a real row (and item_data dict) in the
        table; reuses that exact dict if found (so object_actions.
        _refresh_row_after_patch's later find_row()/dataChanged still works
        correctly), or falls back to a minimal synthetic one for a
        structural type this table never shows a row for at all (Transform,
        RectTransform, ... — excluded from RICH_PREVIEW_TYPES) — patching
        still works fine there, there's just no row to refresh afterward."""
        self.object_actions.open_json_editor_dialog(self._item_data_for(obj))

    def _item_data_for(self, obj) -> dict:
        row = next((i for i, item in enumerate(self.table_model.data_list) if item["obj_ref"] is obj), None)
        if row is not None:
            return self.table_model.data_list[row]
        return {"name": resolve_object_name(obj), "obj_ref": obj}

    def _export_object_from_details(self, obj):
        """«Сведения» -> «Экспорт»: the same type-appropriate export as the table menu's «Экспортировать...»."""
        if self.table_view.isEnabled():     # locked while a save/load runs (as the table's own menu)
            self.object_actions.export_selected_object(self._item_data_for(obj))

    def _export_menu_from_details(self, obj, pos):
        """«Сведения» -> «Экспорт ▾»: the table menu's own «Экспортировать как» list (Конвертированный where the type
        has one, JSON дамп, Raw дамп, Raw контент for resource-backed types) — one list, built in one place."""
        if not self.table_view.isEnabled():     # locked while a save/load runs (as the table's own menu)
            return
        menu = self.object_actions._build_export_as_submenu(self._item_data_for(obj))
        for action in menu.actions():
            action.setParent(menu)              # built as the window's children: let them go with the menu
        menu.exec(pos)
        menu.deleteLater()

    def _import_object_from_details(self, obj):
        """«Сведения» -> «Импорт»: the same file import as the table menu's «Импортировать...»."""
        if self.table_view.isEnabled():     # locked while a save/load runs (as the table's own menu)
            self.object_actions.import_from_file(self._item_data_for(obj))

    def _jump_to_object(self, obj):
        """«Перейти к объекту» / «← Назад» from the preview, the scene viewer, the field table — opens `obj`."""
        self._open_object(obj)

    def _open_object(self, obj, row: Optional[int] = None) -> None:
        """A jump: the PREVIEW shows `obj` at once, whatever the table can show (user request: the modal «Объект
        скрыт фильтром» / «Объект не найден в таблице» boxes every jump used to raise were intrusive). The table
        follows if it can (_sync_table_to): the row is selected when visible, else a thin notice line above the
        table says why there is none and offers the fix as a link — the filters are never changed unasked.

        Rows are matched by (source file name, PathID), not `is`: UnityPy's Environment.load_file() re-parses a
        file on every call, and a later cross-file PPtr resolution that touches it again (AudioClip resource
        lookups call SerializedFile.load_dependencies()) replaces it with new ObjectReaders — logically the same
        objects, no longer `is`-equal to the table's. When the row exists its own reader is previewed, so the
        table selection and the preview agree on identity (on_selection_changed's same-object check)."""
        if row is None:
            row = self._find_row_for_object(obj)
        if row is not None:
            obj = self.table_model.data_list[row]["obj_ref"]
        panel = self.preview_panel
        if _same_object(panel._current_obj, obj) and not panel._selection_timer.isActive():
            panel.clear_pending_jump()          # already shown: not a step anywhere (and no self-loop in «Назад»)
        else:
            panel.request_preview(obj)
        self._sync_table_to(obj, row)

    def _sync_table_to(self, obj, row: Optional[int] = None) -> bool:
        """Makes the table agree with the preview showing `obj`, without previewing anything: its row selected if
        visible (True), else no selection + the notice. Also re-run after a dependency file's rows arrive."""
        if row is None:
            row = self._find_row_for_object(obj)
        if row is not None and self._select_row_quietly(row):
            self._forget_table_notice()
            return True
        self.table_view.select_all_active = False
        self.table_view.clearSelection()        # a row left selected would claim to be what the preview shows
        self._last_previewed_obj = obj          # after clearSelection(): its handler resets it
        self._table_notice_obj = obj
        assets_file = getattr(obj, "assets_file", None)
        if row is not None:
            self._table_notice_kind = "hidden"
            self.table_notice.show_notice(tr("Открытый объект скрыт фильтрами."), tr("Показать в таблице"))
        elif getattr(assets_file, "is_dependency", False):
            self._table_notice_kind = "dependency"
            name = getattr(assets_file, "name", None) or "?"
            self.table_notice.show_notice(tr("Объектов файла «{name}» нет в таблице.", name=name),
                                          tr("Добавить их в таблицу"))
        else:
            self._table_notice_kind = "absent"
            text = tr("Этого объекта нет в таблице: объекты его типа не загружались.")
            if _is_skipped_reader(obj):
                text += " " + tr("После изменения он появится в таблице.")
            self.table_notice.show_notice(text)
        return False

    def _add_row_for_adopted(self, obj) -> Optional[dict]:
        """After an edit: an object whose type the load left out was adopted into its file's objects by that edit
        (UnityPy's SerializedFile.adopt_skipped — otherwise the save would have dropped the change); it gets a table
        row, so «Изменённые» and the change marks show it — and the save sees it: saving is driven by the rows
        (core.save_manager.find_modified_roots). Returns the new row, or None (not adopted / has a row)."""
        if self._find_row_for_object(obj) is not None:
            return None
        added = self._add_rows_for_adopted([obj])
        return added[0] if added else None

    def _add_rows_for_adopted(self, objects) -> list:
        """_add_row_for_adopted for many objects at once (a folder import): one insert, one recount of the type
        list, one log line. Returns the new rows."""
        objects = adopted_without_row(objects, self.table_model.data_list)
        items = [item for item in (build_row_item(obj, include_all=True) for obj in objects) if item is not None]
        if not items:
            return []
        self.table_model.append_rows(items)
        self.quick_filters_bar.update_file_list(self.table_model.data_list)
        if len(items) == 1:
            obj = items[0]["obj_ref"]
            self.log(tr("{type} #{path_id} («{file}») добавлен в таблицу: он изменён, а объекты его типа не "
                        "загружались.", type=obj.type.name, path_id=obj.path_id, file=obj.assets_file.name))
        else:
            self.log(tr("В таблицу добавлено изменённых объектов, чьи типы не загружались: {count}.",
                        count=len(items)))
        notice_obj = getattr(self, "_table_notice_obj", None)
        if notice_obj is not None and any(_same_object(notice_obj, item["obj_ref"]) for item in items):
            self._sync_table_to(notice_obj)
        return items

    def _select_row_quietly(self, row: int) -> bool:
        """Selects + scrolls to `row` if the current filters show it; the preview is NOT re-requested
        (_last_previewed_obj is set first, so on_selection_changed sees the object it already shows)."""
        proxy_index = self.proxy_model.mapFromSource(self.table_model.index(row, 0))
        if not proxy_index.isValid():
            return False
        self._last_previewed_obj = self.table_model.data_list[row]["obj_ref"]
        self.table_view.setCurrentIndex(proxy_index)
        self.table_view.scrollTo(proxy_index)
        return True

    def _on_filter_state_for_reveal(self) -> None:
        """proxy_model.filter_state_changed while «Показать в таблице» waits for its filter to apply: selects the
        row once it is shown; gives up (a warning in the log) if the filter applied and still hides it."""
        obj = getattr(self, "_reveal_waiting_obj", None)
        if obj is None or obj is not getattr(self, "_table_notice_obj", None):
            self._reveal_waiting_obj = None
            return
        row = self._find_row_for_object(obj)
        if row is not None and self._select_row_quietly(row):
            self._forget_table_notice()
        elif row is None or getattr(self.proxy_model, "_pending_script_filter", None) is None:
            # Shouldn't happen — the narrowed filter is built to show exactly this row — a safety net.
            self._reveal_waiting_obj = None
            self.log(tr("Не удалось показать объект в таблице."), LogLevel.WARNING)
            self._sync_table_to(obj)

    def _forget_table_notice(self) -> None:
        self._reveal_waiting_obj = None
        self._table_notice_obj = None
        self._table_notice_kind = None
        if hasattr(self, "table_notice"):
            self.table_notice.clear()

    def _on_table_notice_action(self) -> None:
        """The notice's link: «Показать в таблице» narrows the filters to reveal the row; «Добавить их в таблицу»
        loads the dependency file's objects. Nothing while a save/load locks the table."""
        obj, kind = getattr(self, "_table_notice_obj", None), getattr(self, "_table_notice_kind", None)
        if obj is None or not self.table_view.isEnabled():
            return
        if kind == "hidden":
            row = self._find_row_for_object(obj)
            if row is None:
                self._forget_table_notice()
                return
            if not self._select_row_quietly(row):
                self._reveal_row_via_filters(self.table_model.data_list[row])
                if not self._select_row_quietly(row):
                    # A script filter waits for the scripts' names to be read in the background
                    # (IndexFilterProxyModel.set_type_script_filter): finished in _on_filter_state_for_reveal.
                    self._reveal_waiting_obj = obj
                    self.table_notice.show_notice(tr("Объект показывается в таблице…"))
                    self._on_filter_state_for_reveal()
                    return
            self._forget_table_notice()
        elif kind == "dependency":
            self.table_notice.show_notice(tr("Объекты файла добавляются в таблицу…"))
            self._load_dependency_into_table(obj.assets_file)

    def _find_row_for_object(self, obj) -> Optional[int]:
        """Row of `obj` in the table. Matches (source file name, PathID) first — cheap and
        stable across reloads — but with several games/folders loaded at once the same
        name + PathID exists more than once ("level0" of the game and of its backup), so
        among such candidates the row whose file physically came from the SAME path as
        obj's file wins (falling back to the first candidate when that can't be told)."""
        assets_file = getattr(obj, "assets_file", None)
        source_name = assets_file.name if assets_file else None
        candidates = [
            i for i, item in enumerate(self.table_model.data_list)
            if item["source"] == source_name and item["path_id"] == obj.path_id
        ]
        if len(candidates) <= 1:
            return candidates[0] if candidates else None
        env = getattr(self, "env", None)
        wanted = env.source_path_of(assets_file) if env is not None else None
        if wanted:
            for i in candidates:
                row_file = getattr(self.table_model.data_list[i].get("obj_ref"), "assets_file", None)
                if row_file is assets_file or env.source_path_of(row_file) == wanted:
                    return i
        return candidates[0]


    def _load_dependency_into_table(self, assets_file) -> None:
        """"Подтвердить" from _show_jump_not_found()'s prompt — un-flags
        assets_file.is_dependency and appends its objects' rows to the table
        WITHOUT resetting it (ObjectTableModel.append_rows preserves the
        current selection/scroll/sort). Runs via BackgroundWorker rather than
        synchronously: a shared/common dependency file can carry as many
        objects as an ordinary loaded file, the exact scale concern
        parse_objects() itself already guards against — blocking the GUI
        thread here would just reintroduce that problem for one file instead
        of the whole environment. Settings/Load/Tools are locked for the
        duration via the same _set_menus_locked_for_load already used for a
        full load, since this mutates the same env/table_model state those
        actions read."""
        self._set_menus_locked_for_load(True)
        self.status_label.setText(tr("Загрузка объектов файла «{file}»...", file=assets_file.name))

        def work(report_progress):
            # Flipped here (on the background thread) rather than before
            # starting it: parse_dependency_file_objects() only reads
            # assets_file.objects directly and doesn't care about the flag
            # itself, so there's no race to worry about — but flipping it
            # only once the load has actually started avoids a window where
            # is_dependency is already False while the table doesn't have
            # the rows yet, which a future full reload's own env.objects walk
            # could otherwise observe mid-load.
            assets_file.is_dependency = False
            return parse_dependency_file_objects(
                assets_file, report_progress=report_progress, include_all=CONFIG.load_all_assets,
                allowed_types=set(CONFIG.indexed_types) if CONFIG.indexed_types else None,
            )

        worker = BackgroundWorker(work, parent=self)
        self._dependency_load_worker = worker
        worker.succeeded_signal.connect(lambda rows: self._on_dependency_load_succeeded(assets_file, rows))
        worker.failed_signal.connect(self._on_dependency_load_failed)
        worker.finished.connect(lambda w=worker: self._on_dependency_load_worker_finished(w))
        worker.start()


    def _on_dependency_load_succeeded(self, assets_file, rows) -> None:
        self.table_model.append_rows(rows)
        self.quick_filters_bar.update_file_list(self.table_model.data_list)
        self._set_menus_locked_for_load(False)
        self.status_label.setText(tr("В таблицу добавлено объектов: {count} (файл «{file}»).",
                                     count=len(rows), file=assets_file.name))
        self.log(tr("В таблицу добавлены объекты файла «{file}»: {count}.", count=len(rows), file=assets_file.name))
        # the object the notice was about now has a row (or its type was not loaded): show where it stands
        obj = getattr(self, "_table_notice_obj", None)
        if obj is not None and getattr(obj, "assets_file", None) is assets_file:
            self._sync_table_to(obj)
        self._after_dependency_rows_added(assets_file)     # the «Окружение» tab (main_environment.py)

    def _on_dependency_load_failed(self, message: str) -> None:
        self._set_menus_locked_for_load(False)
        self.status_label.setText(tr("Ошибка загрузки объектов файла."))
        QMessageBox.critical(self, tr("Загрузка объектов файла"), tr("Не удалось загрузить объекты файла:\n{message}", message=message))

    def _on_dependency_load_worker_finished(self, worker) -> None:
        if worker is self._dependency_load_worker:
            self._dependency_load_worker = None
        worker.deleteLater()


    def _jump_to_row(self, row: int) -> bool:
        """Opens the object of `row` (an index into table_model.data_list) — the quick jump's and the text
        search's way in. Returns whether its row ended up selected (False: hidden by filters, the notice shows)."""
        self._open_object(self.table_model.data_list[row]["obj_ref"], row)
        return self._table_notice_obj is None

    def _reveal_row_via_filters(self, item: dict) -> None:
        """The notice's «Показать в таблице» for a row hidden by the type/script/source/modified/text filter:
        narrows the filter so this ONE object becomes visible — File + Script for a MonoBehaviour, File + Type
        for everything else (the combination FiltersDialog's Files/Types tabs expose), plus clearing the free-text
        search and «Изменённые» — whichever of those hid it. Deliberately NOT a full «Сбросить вид»; the Quick
        Filters Bar follows the proxy's filter_state_changed on its own. (It used to run behind a modal
        «Изменить настройки фильтра?» box on every jump; the user asked for something less intrusive.)"""
        script_name = get_row_script_name(item) if item.get("type") == "MonoBehaviour" else ""
        if script_name:
            type_filter, script_filter = {"MonoBehaviour"}, {script_name}
        else:
            type_filter, script_filter = {item.get("type")}, None

        self.table_view.select_all_active = False  # see apply_table_filter()'s own comment — same reasoning
        self.filter_input.clear()
        self.proxy_model.setFilterFixedString("")  # applied synchronously — filter_input.clear() alone only starts the debounce timer
        self.proxy_model.set_type_script_filter(type_filter, script_filter)
        source_filter = {item.get("source")}
        self.proxy_model.set_quick_filter_state(source_filter, False)

    def show_quick_jump_dialog(self):
        """Ctrl+G / "Переход к объекту..." — jump straight to a specific
        object by its File ID (RowItem's "source" — the internal
        SerializedFile's own name) and PathID, instead of scrolling/filtering
        by hand to find it."""
        if not self.table_model.data_list:
            QMessageBox.information(self, tr("Переход к объекту"), tr("Сначала загрузите данные."))
            return

        sources = sorted({item["source"] for item in self.table_model.data_list})
        dialog = QuickJumpDialog(self, sources)
        if exec_and_dispose(dialog) != QDialog.DialogCode.Accepted:
            return

        source, path_id = dialog.get_values()
        self.jump_to_object_by_source_path_id(source, path_id)


    def jump_to_object_by_source_path_id(self, source: str, path_id, obj=None) -> None:
        """Opens the object (source, path_id) — Ctrl+G and the text search's «Перейти к объекту». With `obj`
        (the text search has the ObjectReader) it opens even without a table row and tells same-named files of
        several loaded games apart; without it the first matching row wins, and no row = a message (the user
        typed the identity — there is nothing to show)."""
        if obj is not None:
            self._open_object(obj)
            return
        row = next(
            (i for i, item in enumerate(self.table_model.data_list)
             if item["source"] == source and item["path_id"] == path_id),
            None,
        )
        if row is None:
            QMessageBox.warning(
                self, tr("Переход к объекту"),
                tr("Объект с PathID #{path_id} в файле «{file}» не найден в текущей таблице.",
                   path_id=path_id, file=source)
            )
            return
        self._jump_to_row(row)


def _is_skipped_reader(obj) -> bool:
    """`obj` was read through SerializedFile.skipped_object() (its type was left out of the load, not adopted yet)."""
    readers = getattr(getattr(obj, "assets_file", None), "_skipped_readers", None)
    return bool(readers) and readers.get(obj.path_id) is obj


def _same_object(a, b) -> bool:
    """The same Unity object — `is`, or the same file name and PathID (see _open_object on re-parsed files)."""
    if a is None or b is None:
        return False
    if a is b:
        return True
    return (a.path_id == b.path_id
            and getattr(getattr(a, "assets_file", None), "name", None) == getattr(getattr(b, "assets_file", None), "name", 0))
