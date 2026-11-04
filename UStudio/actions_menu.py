"""The row context menus of ObjectActionsController: the one-object menu (with its Export as / per-script /
per-type / Copy submenus) and the multi-object menu.

Kept out of object_actions.py as a mixin (ObjectActionsController inherits it). Behaviour is unchanged; this is a
mechanical move (every method body is byte-identical to its old place in object_actions.py)."""


from core.i18n import tr
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtGui import QAction, QCursor

from core.object_preview import (
    RESOURCE_BACKED_TYPES, CONVERTED_IMPORT_SUPPORTED_TYPES, get_row_name, get_row_script_name,
)
from core.file_utils import format_size
from core.sdf_resolver import SDF_FONT_SCRIPT_NAME
from type_icons import get_action_icon, get_type_icon


# Types whose «Экспортировать...» writes a real file (image/audio/text/mesh/...) rather than the JSON fallback.
CONVERTED_EXPORT_TYPES = {"Texture2D", "Texture2DArray", "Sprite", "AudioClip", "TextAsset", "Mesh", "Shader",
                          "Font", "VideoClip"}


class MenuActionsMixin:
    # --- Context menu ---

    def show_context_menu(self, pos):
        win = self.main_window

        # Virtual select-all (Ctrl+A) — see gui_widgets.ObjectTableView.
        # select_all_active/selectAll()'s docstrings for why this doesn't go
        # through Qt's real QItemSelectionModel at all. A right click
        # ANYWHERE in the table while this is active acts on every currently
        # visible row, regardless of exactly where the click landed — there's
        # no real per-row Qt selection to check against.
        if win.table_view.select_all_active:
            items = win.proxy_model.get_visible_items()
            if items:
                self._show_bulk_context_menu(items)
            return

        index = win.table_view.indexAt(pos)
        if not index.isValid(): return

        # Right-clicking a row that's OUTSIDE the current multi-selection acts
        # on just that row instead — standard list/table UX (Windows Explorer
        # does the same), and avoids a right-click silently acting on a stale
        # selection the user isn't looking at.
        #
        # Real reported bug: comparing `index` (from indexAt(pos), whichever
        # COLUMN the click actually landed on) directly against selectedRows()
        # (always column-0 QModelIndexes, regardless of which column each row
        # was originally selected via) meant this ALWAYS evaluated to "not in
        # selection" unless the user happened to right-click exactly column 0
        # — QModelIndex equality requires a matching column, not just row. In
        # practice that collapsed the multi-selection down to one row on
        # nearly every right-click, since this table's rows are usually
        # clicked somewhere in the middle (Тип/Источник/...), not column 0.
        # Comparing by ROW instead is what SelectRows behavior actually means.
        selected = win.table_view.selectionModel().selectedRows()
        selected_row_numbers = {i.row() for i in selected}  # proxy row numbers
        if index.row() not in selected_row_numbers:
            win.table_view.setCurrentIndex(index)
            selected = [index]

        if len(selected) > 1:
            items = [
                win.table_model.data_list[win.proxy_model.mapToSource(proxy_index).row()]
                for proxy_index in selected
            ]
            self._show_bulk_context_menu(items)
            return

        source_index = win.proxy_model.mapToSource(index)
        item_data = win.table_model.data_list[source_index.row()]
        self._build_single_item_menu(item_data).exec(QCursor.pos())

    def show_context_menu_for_item(self, item_data: dict):
        """Same single-row menu as show_context_menu()'s tail, for a caller
        that already has an item_data dict instead of a QTableView position —
        SDF Viewer Mode's QTreeView (see main.py's _show_sdf_tree_context_menu),
        which has its own row->item_data resolution (SDFGroupModel.item_at)
        entirely separate from the flat table's proxy/selection machinery."""
        self._build_single_item_menu(item_data).exec(QCursor.pos())

    def show_bulk_menu_for_items(self, items: list):
        """The multi-object menu for a caller that already has the RowItems (SDF Viewer Mode's tree)."""
        self._show_bulk_context_menu(items)

    def _build_single_item_menu(self, item_data: dict) -> QMenu:
        """Two distinct shapes depending on type — MonoBehaviour rows care about
        script-level grouping (dump/filter by script), everything else cares about
        type-appropriate converted export (export_selected_object) and content-level
        raw access for resource-backed types. Both start Edit, then Export, then Import, and share
        Copy/Explorer/the unscoped folder-import entry."""
        win = self.main_window
        type_name = item_data.get("type")
        menu = QMenu()

        act_edit = QAction(get_action_icon("edit"), tr("Отредактировать данные\tEnter"), win)   # \t: shortcut-style hint only
        act_edit.triggered.connect(lambda: self.open_json_editor_dialog(item_data))
        menu.addAction(act_edit)

        # Export first, then import (user request: exporting is what the menu is used for most), each group
        # with its "all of these" submenu — for a MonoBehaviour the group is "same script", else "same type".
        script_name = str(get_row_script_name(item_data) or "").strip() if type_name == "MonoBehaviour" else ""
        act_export_object = QAction(get_action_icon("export"), tr("Экспортировать..."), win)
        act_export_object.triggered.connect(lambda: self.export_selected_object(item_data))
        menu.addAction(act_export_object)
        menu.addMenu(self._build_export_as_submenu(item_data))
        if type_name == "MonoBehaviour":
            menu.addMenu(self._build_export_script_submenu(item_data))
        else:
            menu.addMenu(self._build_export_type_submenu(type_name))
        menu.addSeparator()   # the export group, then the import group (user request)

        if type_name == "Texture2DArray":
            # Folder-based, not file-based — a Texture2DArray import needs a
            # whole set of slice files (see import_texture_array_slices()'s
            # own docstring for the naming convention and the "individual
            # slices, not all-or-nothing" design), so the generic single-file
            # picker below doesn't apply to this type at all.
            act_import_slices = QAction(get_action_icon("import"), tr("Импортировать срезы из папки..."), win)
            act_import_slices.triggered.connect(lambda: self.import_texture_array_slices_from_folder(item_data))
            act_import_slices_settings = QAction(
                get_action_icon("import"), tr("Импортировать срезы из папки (с настройками)..."), win
            )
            act_import_slices_settings.triggered.connect(
                lambda: self.import_texture_array_slices_from_folder_with_settings(item_data)
            )
            menu.addAction(act_import_slices)
            menu.addAction(act_import_slices_settings)
        else:
            act_import_file = QAction(get_action_icon("import"), tr("Импортировать из файла..."), win)
            act_import_file.triggered.connect(lambda: self.import_from_file(item_data))
            menu.addAction(act_import_file)
            # Only offered for types with a real converted-import branch —
            # showing a settings dialog for a type that has nothing to
            # configure would be pointless.
            if type_name in CONVERTED_IMPORT_SUPPORTED_TYPES:
                act_import_file_settings = QAction(
                    get_action_icon("import"), tr("Импортировать из файла (с настройками)..."), win
                )
                act_import_file_settings.triggered.connect(lambda: self.import_from_file_with_settings(item_data))
                menu.addAction(act_import_file_settings)
        if type_name == "Sprite":
            act_full_rect = QAction(tr("Сделать сетку прямоугольной [Exp]"), win)
            act_full_rect.triggered.connect(lambda: self.make_sprite_meshes_rectangular([item_data]))
            menu.addAction(act_full_rect)
        menu.addSeparator()
        menu.addAction(win.bookmark_action([item_data], menu))      # «Закладки» (main_bookmarks.py)

        if type_name == "MonoBehaviour":
            act_show_type = QAction(get_type_icon(type_name), tr("Показать объекты типа {type}", type=type_name), win)
            act_show_type.triggered.connect(lambda: win.filter_to_type_or_script(type_name, False))
            menu.addAction(act_show_type)
            if script_name:
                act_show_script = QAction(get_type_icon(type_name), tr("Показать объекты скрипта {script}", script=script_name), win)
                act_show_script.triggered.connect(lambda: win.filter_to_type_or_script(script_name, True))
                menu.addAction(act_show_script)
            menu.addMenu(self._build_copy_submenu(item_data))
            act_explorer = QAction(get_action_icon("explorer"), tr("Показать файл в проводнике"), win)
            act_explorer.triggered.connect(lambda: self.show_in_explorer(item_data))
            menu.addAction(act_explorer)

            if script_name == SDF_FONT_SCRIPT_NAME:
                menu.addSeparator()
                act_generate_sdf = QAction(tr("Генерировать SDF... [Exp]"), win)
                act_generate_sdf.triggered.connect(lambda: self.generate_sdf_font(item_data))
                menu.addAction(act_generate_sdf)
                export_sdf_submenu = QMenu(tr("Экспортировать SDF"), win)
                act_export_sdf = QAction(tr("Только этот шрифт"), win)
                act_export_sdf.triggered.connect(lambda: self.export_sdf_font(item_data))
                act_export_all_sdf = QAction(tr("Все шрифты"), win)
                act_export_all_sdf.triggered.connect(self.export_all_sdf_fonts)
                export_sdf_submenu.addAction(act_export_sdf)
                export_sdf_submenu.addAction(act_export_all_sdf)
                menu.addMenu(export_sdf_submenu)

            menu.addSeparator()
            act_import_all = QAction(get_action_icon("import"), tr("Импорт в окружение..."), win)
            act_import_all.triggered.connect(lambda: self._import_patches_unscoped())
            menu.addAction(act_import_all)

        else:
            act_show_type = QAction(get_type_icon(type_name), tr("Показать все {type}", type=type_name), win)
            act_show_type.triggered.connect(lambda: win.filter_to_type_or_script(type_name, False))
            menu.addAction(act_show_type)
            menu.addMenu(self._build_copy_submenu(item_data))
            act_explorer = QAction(get_action_icon("explorer"), tr("Показать файл в проводнике"), win)
            act_explorer.triggered.connect(lambda: self.show_in_explorer(item_data))
            menu.addAction(act_explorer)

            menu.addSeparator()
            act_import_all = QAction(get_action_icon("import"), tr("Импорт в окружение..."), win)
            act_import_all.triggered.connect(lambda: self._import_patches_unscoped())
            menu.addAction(act_import_all)

        return menu

    def _build_export_as_submenu(self, item_data: dict) -> QMenu:
        """"Экспортировать как →" — JSON-дамп/Raw always, Content Raw only for a
        resource-backed type (Texture2D/Texture2DArray/AudioClip/Mesh/VideoClip;
        Sprite is deliberately NOT in this set — it has no m_StreamData/m_Resource
        of its own, its pixels come from the referenced Texture2D instead)."""
        win = self.main_window
        submenu = QMenu(tr("Экспортировать как"), win)
        if item_data.get("type") in CONVERTED_EXPORT_TYPES:
            # Same as «Экспортировать...», listed first so every export format is in one place.
            act_converted = QAction(tr("Конвертированный"), win)
            act_converted.triggered.connect(lambda: self.export_selected_object(item_data))
            submenu.addAction(act_converted)
        act_json = QAction(tr("JSON дамп"), win)
        act_json.triggered.connect(lambda: self.dump_single_object(item_data))
        act_raw = QAction(tr("Raw дамп"), win)
        act_raw.triggered.connect(lambda: self.export_raw_single(item_data))
        submenu.addAction(act_json)
        submenu.addAction(act_raw)
        if item_data.get("type") in RESOURCE_BACKED_TYPES:
            act_content = QAction(tr("Raw контент"), win)
            act_content.triggered.connect(lambda: self.export_content_raw_single(item_data))
            submenu.addAction(act_content)
        return submenu

    def _build_export_script_submenu(self, item_data: dict) -> QMenu:
        """"Экспортировать все объекты этого скрипта как →" — the MonoBehaviour counterpart of
        _build_export_type_submenu(): a MonoBehaviour's useful group is its script, not the type."""
        win = self.main_window
        submenu = QMenu(tr("Экспортировать объекты этого скрипта как"), win)
        for label, mode in ((tr("Json дамп"), "json_dump"), (tr("Raw дамп"), "raw")):
            act = QAction(label, win)
            act.triggered.connect(lambda checked=False, m=mode: self.dump_by_script_type(item_data, m))
            submenu.addAction(act)
        return submenu

    def _build_export_type_submenu(self, type_name: str) -> QMenu:
        """"Экспортировать все объекты типа X как →" — a quick bulk export of every
        object of this type currently indexed (win.raw_data_list, deliberately
        unfiltered by the table's current filter/selection — the whole point is
        skipping the Filters-dialog-then-select-all workflow)."""
        win = self.main_window
        submenu = QMenu(tr("Экспортировать все {type} как", type=type_name), win)
        entries = [(tr("Конвертированный"), "converted"), (tr("Json дамп"), "json_dump"), (tr("Raw дамп"), "raw")]
        if type_name in RESOURCE_BACKED_TYPES:
            entries.append((tr("Raw контент"), "content_raw"))
        for label, mode in entries:
            act = QAction(label, win)
            act.triggered.connect(lambda checked=False, m=mode: self.export_type_objects_as(type_name, m))
            submenu.addAction(act)
        return submenu

    def copy_object_facts(self, item_data: dict) -> None:
        from core.object_references import object_facts
        from details_view import ObjectDetailsView
        obj = item_data.get("obj_ref")
        if obj is not None:
            QApplication.clipboard().setText(ObjectDetailsView.text_of_facts(object_facts(obj)))

    def _build_copy_submenu(self, item_data: dict) -> QMenu:
        """"Копировать →" — one action per table column, copying that cell's
        displayed value to the clipboard. "Изменено" is skipped: it's computed live
        from obj_ref.data is not None (object_table.py), not a stored field, so
        there's no fixed value to copy."""
        win = self.main_window
        submenu = QMenu(tr("Копировать"), win)
        submenu.setIcon(get_action_icon("copy"))
        # the same text as the «Сведения» tab's copy button (user request)
        act_facts = QAction(tr("Сведения об объекте"), win)
        act_facts.setEnabled(item_data.get("obj_ref") is not None)
        act_facts.triggered.connect(lambda: self.copy_object_facts(item_data))
        submenu.addAction(act_facts)
        submenu.addSeparator()
        columns = [
            (tr("Имя"), "name"), (tr("Путь в контейнере"), "container_path"), (tr("Скрипт"), "script_name"),
            (tr("Тип"), "type"), (tr("Источник"), "source"), ("PathID", "path_id"), (tr("Размер"), "size"),
        ]
        for label, key in columns:
            if key == "script_name" and not get_row_script_name(item_data):
                continue  # nothing meaningful to copy for a non-MonoBehaviour row
            if key == "name":
                value = get_row_name(item_data)
            elif key == "script_name":
                value = get_row_script_name(item_data)
            elif key == "size":
                value = format_size(item_data.get("size", 0))
            else:
                value = str(item_data.get(key, ""))
            act = QAction(label, win)
            act.triggered.connect(lambda checked=False, v=value: QApplication.clipboard().setText(v))
            submenu.addAction(act)
        return submenu

    # --- Multi-row selection (queued, with real progress) ---

    def _show_bulk_context_menu(self, items: list):
        """Shared by a real multi-row Qt selection and virtual select-all
        (see show_context_menu()) — both just need "export/dump every one of
        these items", regardless of how the list was built."""
        win = self.main_window
        menu = QMenu()

        act_export = QAction(get_action_icon("export"), tr("Экспортировать..."), win)
        act_export.triggered.connect(lambda: self.export_selected_objects(items))
        menu.addAction(act_export)

        export_as = QMenu(tr("Экспортировать выбранное как"), win)
        act_json = QAction(tr("JSON дамп"), win)
        act_json.triggered.connect(lambda: self.dump_multiple_objects_json(items))
        act_raw = QAction(tr("Raw дамп"), win)
        act_raw.triggered.connect(lambda: self.export_selected_objects_raw(items))
        export_as.addAction(act_json)
        export_as.addAction(act_raw)
        menu.addMenu(export_as)
        menu.addSeparator()

        # then the imports (export first: see _build_single_item_menu)
        act_import_selected = QAction(get_action_icon("import"), tr("Импортировать из папки..."), win)
        act_import_selected.triggered.connect(lambda: self.import_patches_from_selection(items))
        menu.addAction(act_import_selected)

        # Only offered when the WHOLE selection is a single, homogeneous type
        # that actually has converted-import settings to show — real reported
        # request: a mixed-type selection showed this action too, even though
        # ConvertedImportSettingsDialog's per-type sections (see its own
        # docstring) are meant for a folder that happens to contain patches
        # for several types, not for the user's own table selection spanning
        # types they didn't intend to configure together.
        selected_types = {item.get("type") for item in items}
        if len(selected_types) == 1 and next(iter(selected_types)) in CONVERTED_IMPORT_SUPPORTED_TYPES:
            act_import_selected_settings = QAction(
                get_action_icon("import"), tr("Импортировать из папки (с настройками)..."), win
            )
            act_import_selected_settings.triggered.connect(
                lambda: self.import_patches_from_selection_with_settings(items)
            )
            menu.addAction(act_import_selected_settings)

        from core.patch_matching import SINGLE_FILE_FOR_SELECTION_TYPES
        if any(item.get("type") in SINGLE_FILE_FOR_SELECTION_TYPES for item in items):
            act_import_one_file = QAction(get_action_icon("import"), tr("Импортировать из одного файла..."), win)
            act_import_one_file.triggered.connect(lambda: self.import_file_into_selection(items))
            menu.addAction(act_import_one_file)

        sprite_items = [item for item in items if item.get("type") == "Sprite"]
        if sprite_items:
            act_full_rect = QAction(tr("Сделать сетку прямоугольной x{count} [Exp]", count=len(sprite_items)), win)
            act_full_rect.triggered.connect(lambda: self.make_sprite_meshes_rectangular(sprite_items))
            menu.addAction(act_full_rect)

        # Real reported request: generating SDF glyphs one font asset at a
        # time (the single-row action) doesn't scale to "add Cyrillic to
        # every font in this game" — offered whenever the selection contains
        # AT LEAST ONE TMP_FontAsset (same "don't require a pure-type
        # selection" convention as the converted-import action above), and
        # generate_sdf_font_multi() itself only ever touches the eligible
        # rows, silently ignoring anything else in the selection.
        font_items = [item for item in items if get_row_script_name(item) == SDF_FONT_SCRIPT_NAME]
        if font_items:
            menu.addSeparator()
            act_generate_sdf_multi = QAction(tr("Генерировать SDF... x{count} [Exp]", count=len(font_items)), win)
            act_generate_sdf_multi.triggered.connect(lambda: self.generate_sdf_font_multi(font_items))
            menu.addAction(act_generate_sdf_multi)

        menu.addSeparator()
        menu.addAction(win.bookmark_action(items, menu))      # «Закладки» for the whole selection (main_bookmarks.py)

        act_import_all = QAction(get_action_icon("import"), tr("Импорт в окружение..."), win)
        act_import_all.triggered.connect(lambda: self._import_patches_unscoped())
        menu.addAction(act_import_all)

        menu.exec(QCursor.pos())
