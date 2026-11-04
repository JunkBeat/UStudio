"""The «Окружение» tab of the left panel (environment_view.EnvironmentView): filled after a load, emptied at every
teardown point (it holds the game's files — `_drop_environment_view` runs inside `_stop_usage_index`, which every
teardown already calls), and what its menu asks for: show a file's objects in the table, export them, open a bundle
in the archive viewer, Explorer.

Kept out of main.py as a mixin (MainWindow inherits it), like main_navigation.py."""

from core.i18n import tr
from config import LogLevel


class EnvironmentMixin:
    LEFT_TAB_OBJECTS, LEFT_TAB_ENVIRONMENT = 0, 1

    def _fill_environment_view(self, env) -> None:
        self.environment_view.set_environment(env)

    def _drop_environment_view(self) -> None:
        view = getattr(self, "environment_view", None)
        if view is not None:
            view.clear()

    def _rows_of_files(self, files) -> list:
        ids = {id(f) for f in files}
        return [item for item in self.table_model.data_list
                if id(getattr(item.get("obj_ref"), "assets_file", None)) in ids]

    def _show_file_objects(self, files) -> None:
        """«Показать объекты» / double-click: the Objects tab with the table filtered to these files — every object
        of them (the type/script filter, the search and «Изменённые» are reset; the bar shows the new state)."""
        if not files:
            return
        if len(files) == 1 and getattr(files[0], "is_dependency", False) and not self._rows_of_files(files):
            # loaded only to resolve references: its objects are not in the table yet — add them first
            if self.table_view.isEnabled():
                self._load_dependency_into_table(files[0])
                self._pending_file_filter = files
            return
        if self.act_mode_sdf.isChecked():
            self.act_mode_standard.setChecked(True)         # the file filter acts on the flat table
        self.left_tabs.setCurrentIndex(self.LEFT_TAB_OBJECTS)
        self.table_view.select_all_active = False
        self.filter_input.clear()
        self.proxy_model.setFilterFixedString("")            # synchronously (the box only starts its debounce)
        self.proxy_model.set_type_script_filter(None, None)
        self.proxy_model.set_quick_filter_state({f.name for f in files}, False)
        if not self._rows_of_files(files):
            self.log(tr("В таблице нет объектов этого файла (их типы не загружались)."), LogLevel.WARNING)

    def _after_dependency_rows_added(self, assets_file) -> None:
        """A dependency file's rows arrived (main_navigation): finish a «Показать объекты» that waited for them."""
        pending = getattr(self, "_pending_file_filter", None)
        self._pending_file_filter = None
        if pending and pending[0] is assets_file:
            self._show_file_objects(pending)
        self.environment_view.refresh_marks()               # the file is no longer «только для ссылок»

    def _export_file_objects(self, files, mode: str) -> None:
        """«Экспортировать объекты» — every table row of these files, through the same queued bulk export as a
        multi-row selection (folder picker, UStudio_Assets subfolder, task queue)."""
        if not self.table_view.isEnabled():                 # locked while a save/load runs (as the table's menu)
            return
        items = self._rows_of_files(files)
        if not items:
            self.log(tr("В таблице нет объектов этого файла для экспорта."), LogLevel.WARNING)
            return
        kind_word = {"json_dump": tr("дампов"), "raw": tr("объектов (Raw)")}.get(mode, tr("объектов"))
        title = (tr("Экспорт объектов файла «{file}»", file=files[0].name) if len(files) == 1
                 else tr("Экспорт объектов файлов"))
        self.object_actions._run_bulk_export(items, mode, kind_word, title)

    def _open_archive_from_environment(self, path: str) -> None:
        self.open_cab_browser()
        self.cab_browser_dialog.open_path(path)

    def _reveal_from_environment(self, path: str) -> None:
        self.object_actions.reveal_path_in_explorer(path)
