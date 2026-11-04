import sys
import ctypes
import gc
import logging
import os
import tempfile
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QTextEdit, QTextBrowser,
    QLabel, QProgressBar, QAbstractItemView, QLineEdit, QPushButton, QFileDialog, QHeaderView, QMenu, QMessageBox,
    QTreeView, QStackedWidget, QTabWidget,
)
from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer, QThread, QObject
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence

from config import APP_NAME, APP_VERSION, CONFIG, LogLevel, LoadMode, load_persisted_config, save_persisted_config
from dialogs import (
    RevertDialog, CabBrowserDialog, FiltersDialog, InputSettingDialog, CabCollisionSettingsDialog, TaskQueuePanel,
    ApplicationSettingsDialog, AboutDialog, AddressablesResolverDialog, Il2CppPrepareDialog,
)
from save_thread import CustomPathSaveThread, OverwritePrepareThread, OverwriteCommitThread, RestoreThread
from core.save_manager import find_modified_roots, compute_base_dir
from tools import TextSearchDialog, FieldTableDialog, PatchRelocationDialog, SceneViewerDialog, VersionWriterDialog
from helpers import detect_game_paths, format_size, format_type_names, read_app_info, wrap_tooltip
import crash_log
from single_instance import SingleInstance
from main_save_flow import SaveFlowMixin
from main_load_flow import LoadFlowMixin
from main_log_pane import LogPaneMixin
from main_sdf_view import SdfViewMixin
from main_navigation import NavigationMixin
from main_environment import EnvironmentMixin
from main_bookmarks import BookmarksMixin
from environment_view import EnvironmentView
from gui_logging import QtLogHandler, detach_qt_log_handler
from core.logging_setup import configure_console_logging
from core import object_metadata
from object_table import ObjectTableModel, AdvancedFilterProxyModel, UserActivityTracker
from sdf_group_model import SDFGroupModel
from quick_filters_bar import QuickFiltersBar
from table_notice import TableNoticeBar
from preview_panel import PreviewPanel
from object_actions import ObjectActionsController
from task_queue import TaskQueueManager
from gui_widgets import ObjectTableView, TaskQueueStatusWidget, SDFGroupSpacingDelegate
from gui_layout import save_layout, restore_layout
import theme
import app_language
import menu_icons
import app_icon

from gui_common import FieldNote, exec_and_dispose
from app_settings import app_settings
from core.i18n import N_, tr, translate_to


def update_game_paths(selected_path: Path):
    """
    Automatically detects paths related to the Unity game and updates CONFIG.
    """
    paths = detect_game_paths(selected_path)
    CONFIG.game_data_dir = paths["data_dir"]
    CONFIG.managed_dir = paths["managed_dir"]
    CONFIG.game_root_dir = paths["game_root_dir"]
    CONFIG.is_il2cpp = paths["is_il2cpp"]
    return paths


# --- Main application window ---

class MainWindow(LoadFlowMixin, LogPaneMixin, SdfViewMixin, NavigationMixin, EnvironmentMixin, BookmarksMixin, SaveFlowMixin,
                 QMainWindow):
    def __init__(self):
        super().__init__()
        self._update_title()

        self.settings = app_settings()
        load_persisted_config()
        object_metadata.set_char_coverage(CONFIG.char_coverage_label, CONFIG.char_coverage_chars)

        # Every self.log() call (this file) and every logging.getLogger("ustudio...")
        # call anywhere in core/ (the loader, the CAB archive logic — including calls
        # made from DataLoaderThread's/CabBrowserDialog's background threads) reaches
        # the log panel through this one handler — see gui_logging.QtLogHandler's
        # docstring for why a plain logging.Handler is what makes that cross-thread
        # delivery safe. Registered on the "ustudio" logger (not a specific submodule)
        # so it picks up everything below it in the hierarchy.
        self._qt_log_handler = QtLogHandler()
        self._qt_log_handler.record_logged.connect(self._on_log_record)
        self._qt_log_handler.show_debug = CONFIG.show_debug_log
        ustudio_logger = logging.getLogger("ustudio")
        ustudio_logger.addHandler(self._qt_log_handler)
        # DEBUG so debug records exist at all (configure_console_logging() has already set
        # INFO by now — which silently swallowed every debug line); the Qt handler drops them
        # unless CONFIG.show_debug_log is on, the console handler has its own level.
        if ustudio_logger.level == logging.NOTSET or ustudio_logger.level > logging.DEBUG:
            ustudio_logger.setLevel(logging.DEBUG)

        self.env = None
        self._sdf_coverage_cache = {}
        self.raw_data_list = []
        # True only while the table's current data came from CabBrowserDialog.
        # load_entry_objects() (one internal file of a bundle, loaded via the CAB
        # Archives Viewer for inspection) rather than a normal Load files/Load
        # folder — see on_menu_save_files()'s own guard and _clear_loaded_session()
        # for why "Сохранить файлы игры" (overwrite-in-place) is refused in that
        # state: real reported request, after a real crash report investigating the
        # same scenario (see CLAUDE.md) — the CAB browser only fully parses the ONE
        # entry the user picked (plus its declared dependencies), so overwriting
        # the WHOLE original bundle in place from what was meant as a narrower,
        # exploratory session is a bigger and less deliberate action than the user
        # intended; "Сохранить файлы игры как..." (a new destination) stays
        # available and does the identical rebuild, just never touching the
        # original.
        self._loaded_via_cab_browser = False
        # See on_selection_changed()'s own comment — guards against a
        # filter-triggered re-fire of selectionChanged for the SAME already-
        # selected row from needlessly rebuilding (and collapsing) the
        # preview panel's structure tree.
        self._last_previewed_obj = None
        self.search_tool_dialog = None
        self.field_table_dialog = None
        self.patch_relocation_dialog = None
        self._dependency_load_worker = None
        self.save_thread = None
        self.cab_browser_dialog = None
        self.scene_viewer_dialog = None
        self.import_match_dialog = None  # the patch-import list — non-modal, see object_actions
        # Reentrancy guards for _on_save_progress/update_loading_progress's
        # own QApplication.processEvents() calls — see their own comments for
        # why: a real reported crash (access violation) showed
        # _on_save_progress on the call stack twice in a row, i.e. genuinely
        # re-entering itself via processEvents() dispatching an already-
        # queued repeat of the same signal.
        self._save_progress_reentrant = False
        self._load_progress_reentrant = False
        # "Virtual select-all" state (see gui_widgets.ObjectTableView.
        # selectAll()'s docstring) lives on self.table_view itself — see
        # select_all_active there — since its own mousePressEvent() needs
        # synchronous access to it on every click.

        # The single FIFO export/import queue for the row context menu's actions —
        # see task_queue.py's module docstring for why export and import can never
        # run at the same time. Created before init_ui() (which adds the status-bar
        # indicator for it) and before object_actions (which enqueues onto it).
        self.task_queue_manager = TaskQueueManager(self)
        self.task_queue_panel = None

        # tracking the Unity file nesting level
        self._top = (0, 0, "")
        self._inner = None

        self.filter_timer = QTimer()
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.apply_table_filter)

        # Theme is applied to the whole QApplication before MainWindow is even constructed
        # (see the __main__ block) — this just keeps track of which one, so log()/
        # JsonHighlighter (both use literal colors outside the QPalette system — see
        # theme.py's module docstring) can follow it too, including live toggles.
        self._theme_choice = theme.load_theme_choice()        # "dark" / "light" / "system" (the menu)
        self._theme_name = theme.resolve_theme_name(self._theme_choice)   # the palette in use
        self._theme_colors = theme.get_colors(self._theme_name)
        # (action, is_radio) for every checkable QAction registered via
        # _register_checkable_icon() below — re-icon'd in _apply_theme_name() so the
        # checkbox/radio glyph follows a live theme switch (menu_icons.py's
        # icons are pixmaps captured from the style/palette at draw time, not
        # something that re-renders itself automatically on a palette change).
        self._checkable_menu_actions: list[tuple[QAction, bool]] = []

        self.init_menu()
        self.init_ui()
        # Everything the row context menu can do (edit/import/export/dump) — split
        # out into its own controller, see object_actions.py. Constructed after
        # init_ui() since it reaches into self.table_view/preview_panel/etc.
        self.object_actions = ObjectActionsController(self)
        self.table_view.customContextMenuRequested.connect(self.object_actions.show_context_menu)
        self.table_view.activated.connect(self.object_actions.edit_row_activated)   # double-click / Enter
        self.sdf_tree_view.customContextMenuRequested.connect(self._show_sdf_tree_context_menu)
        self.sdf_tree_view.selectionModel().selectionChanged.connect(self._on_sdf_selection_changed)
        self._init_background_passes()      # what every teardown stops (background_passes.py)
        # IMPORTANT: fitting the size to the screen must happen AFTER init_ui() — the splitter/column
        # widths give the child widgets their minimum sizes, and calling this earlier means the layout
        # after init_ui() stretches the window back out again, ignoring the earlier resize()
        self._fit_to_screen(1320, 680)

    def _fit_to_screen(self, preferred_width: int, preferred_height: int):
        """Prevents the window from exceeding the current screen resolution's bounds on
        first launch (relevant on monitors smaller than 1350x780) — fits the size to the
        available screen area and centers the window within it."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(preferred_width, preferred_height)
            return

        available = screen.availableGeometry()
        # small margin (see setHighDpiScaleFactorRoundingPolicy in main.py) —
        # at fractional Windows scaling (125%/150%), even with PassThrough, a window sized
        # EXACTLY to available sometimes physically renders 1-2px wider/taller than the
        # screen itself; without the margin this is still visible as a window slightly overflowing the edge
        MARGIN = 4
        width = min(preferred_width, available.width() - MARGIN)
        height = min(preferred_height, available.height() - MARGIN)
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

    def _update_title(self):
        """Program Name Version [- Project name] [- Unity version] [- Platform] —
        each segment only appended once it's actually known. Project name comes
        from {game_data_dir}/app.info (read_app_info() — the standard Unity
        standalone loose-file layout's company/product name file); Unity
        version/platform are resolved once per load (see EnvironmentLoader.
        resolve_version()/resolve_platform() in core/loader.py) and land on
        CONFIG the same way loader_thread.py already does for unity_version.
        Before any successful load, self.env is still None — CONFIG.unity_version
        already holds a non-empty *fallback* default at that point (unrelated to
        anything actually loaded), so it's deliberately not read until a load has
        actually finished, or the title would misleadingly show that default."""
        parts = [f"{APP_NAME} {APP_VERSION}"]
        if getattr(self, "env", None) is not None:
            project = read_app_info(CONFIG.game_data_dir)
            if project:
                parts.append(project)
            if CONFIG.unity_version:
                parts.append(CONFIG.unity_version)
            if CONFIG.platform_name:
                parts.append(CONFIG.platform_name)
        self.setWindowTitle(" - ".join(parts))

    def init_menu(self):
        menubar = self.menuBar()

        # Section 1: File
        file_menu = menubar.addMenu(tr("Файл"))
        # disabled while a load/save is active, along with Settings and Tools —
        # see the comment on settings_menu below
        self.file_menu = file_menu

        act_load_files = QAction(tr("Загрузить файлы..."), self)
        act_load_files.triggered.connect(self.on_menu_load_files)
        file_menu.addAction(act_load_files)

        act_load_folder = QAction(tr("Загрузить папку..."), self)
        act_load_folder.triggered.connect(self.on_menu_load_folder)
        file_menu.addAction(act_load_folder)

        act_cab_browser = QAction(tr("Просмотр архива..."), self)
        act_cab_browser.triggered.connect(self.open_cab_browser)
        file_menu.addAction(act_cab_browser)

        file_menu.addSeparator()

        # Saves only objects with a pending in-memory edit (obj_ref.data is not
        # None — the same "Изменено"/asterisk check object_table.py's
        # ObjectTableModel._is_modified uses), grouped by their root container
        # file — see core/save_manager.py's module docstring for why that's the
        # actual unit UnityPy can (re)write.
        self.act_save_overwrite = QAction(tr("Сохранить файлы игры..."), self)
        self.act_save_overwrite.triggered.connect(lambda: self.on_menu_save_files("overwrite"))
        file_menu.addAction(self.act_save_overwrite)

        act_save_custom = QAction(tr("Сохранить файлы игры как..."), self)
        act_save_custom.triggered.connect(lambda: self.on_menu_save_files("custom"))
        file_menu.addAction(act_save_custom)

        # Puts files back from the backups made before overwriting (core/backup.py).
        file_menu.addSeparator()
        self.act_revert = QAction(tr("Резервные копии..."), self)
        self.act_revert.triggered.connect(self.on_menu_revert_originals)
        file_menu.addAction(self.act_revert)

        # Section 2: Settings
        settings_menu = menubar.addMenu(tr("Настройки"))
        # Settings, Load, and Tools all get disabled while a load is active:
        # Settings — CONFIG is read from DataLoaderThread in the background, editing the fallback version/
        # key/threshold while it's being read is a race (see the comment on the CONFIG declaration);
        # Load — running a second, parallel load/scan is not supported;
        # Tools (text search, field export) — read the main window's env/raw_data_list,
        # which DataLoaderThread hasn't finished populating/replacing yet.
        self.settings_menu = settings_menu
        # Rarely needed options live in a sub-menu so the Settings menu itself stays short;
        # it is attached at the end of the menu (below).
        advanced_menu = QMenu(tr("Дополнительно"), self)

        act_set_fallback = QAction(tr("Указать fallback версию..."), self)
        act_set_fallback.triggered.connect(self.on_menu_set_fallback)
        advanced_menu.addAction(act_set_fallback)
        
        act_set_unity_cn = QAction(tr("Указать ключ Unity CN..."), self)
        act_set_unity_cn.triggered.connect(self.on_menu_set_unity_cn)
        advanced_menu.addAction(act_set_unity_cn)

        act_set_cab_collision = QAction(tr("Совпадения имён файлов..."), self)
        act_set_cab_collision.triggered.connect(self.on_menu_set_cab_collision_policy)
        advanced_menu.addAction(act_set_cab_collision)

        # Distinct from "Совпадения имён файлов..." above (what to do about same-named
        # files) — this one finds a reference
        # that's missing entirely because it lives inside a SIBLING bundle never
        # loaded at all (Addressables' shared-asset bundles, e.g. MonoScripts split
        # into a dedicated *_monoscripts.bundle). See dialogs/addressables_resolver_dialog.py
        # and core/addressables_resolver.py's own docstrings for the full picture.
        act_addressables = QAction(tr("Разрешение ссылок в соседних бандлах..."), self)
        act_addressables.triggered.connect(self.open_addressables_resolver)
        advanced_menu.addAction(act_addressables)

        act_clear_apk_cache = QAction(tr("Очистить кэш распакованных APK..."), self)
        act_clear_apk_cache.triggered.connect(self.clear_platform_cache)
        advanced_menu.addAction(act_clear_apk_cache)
        act_clear_il2cpp_cache = QAction(tr("Очистить кэш IL2CPP..."), self)
        act_clear_il2cpp_cache.triggered.connect(self.clear_il2cpp_cache)
        advanced_menu.addAction(act_clear_il2cpp_cache)

        # Consolidated: warning threshold + export settings + default bundle
        # compression, previously three separate dialogs (ThresholdSettingsDialog,
        # ExportSettingsDialog, no prior compression setting) — see
        # dialogs/app_settings_dialog.py's own docstring for what's deliberately
        # NOT folded in here (CAB collision policy above, fallback version/Unity
        # CN key below).
        act_app_settings = QAction(tr("Настройки программы..."), self)
        act_app_settings.triggered.connect(self.on_menu_app_settings)
        settings_menu.addAction(act_app_settings)

        # Off by default — see core.loader.build_row_item's own docstring for
        # why lifting the RICH_PREVIEW_TYPES row filter is safe to do, and
        # config.py's AppConfig.load_all_assets for why it's unchecked by
        # default regardless (table growth on a huge fixture). Takes effect
        # on the NEXT load, not retroactively — this only feeds into
        # LoadOptions at the start of a load (see loader_thread.py's
        # _build_options()), so the currently-loaded table doesn't change
        # just from toggling this.
        self.act_load_all_assets = QAction(tr("Загружать все ассеты"), self, checkable=True)
        self.act_load_all_assets.setChecked(CONFIG.load_all_assets)
        self.act_load_all_assets.toggled.connect(self._on_load_all_assets_toggled)
        self._register_checkable_icon(self.act_load_all_assets)
        settings_menu.addAction(self.act_load_all_assets)

        # Тема: the two palettes, or whichever of them Windows is set to (followed live).
        theme_menu = settings_menu.addMenu(tr("Тема"))
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self.theme_actions = {}
        for choice, caption in (("dark", tr("Тёмная")), ("light", tr("Светлая")), (theme.SYSTEM, tr("Как в системе"))):
            action = QAction(caption, self, checkable=True)
            action.setChecked(choice == self._theme_choice)
            theme_group.addAction(action)
            self._register_checkable_icon(action, radio=True)
            action.triggered.connect(lambda _checked, c=choice: self.set_theme_choice(c))
            theme_menu.addAction(action)
            self.theme_actions[choice] = action
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._on_system_color_scheme_changed)

        # Язык: takes effect after a restart (app_language.py's docstring).
        language_menu = settings_menu.addMenu(tr("Язык"))
        language_group = QActionGroup(self)
        language_group.setExclusive(True)
        self._language_choice = app_language.load_choice()
        self.language_actions = {}
        for choice in app_language.CHOICES:
            action = QAction(app_language.choice_caption(choice), self, checkable=True)
            action.setChecked(choice == self._language_choice)
            language_group.addAction(action)
            self._register_checkable_icon(action, radio=True)
            action.triggered.connect(lambda _checked, c=choice: self.set_language_choice(c))
            language_menu.addAction(action)
            self.language_actions[choice] = action
            if choice == app_language.CHOICES[0]:
                language_menu.addSeparator()

        settings_menu.addSeparator()
        settings_menu.addMenu(advanced_menu)

        # Section 3: View — preview-panel on/off switches, previously
        # AppSettingsDialog's whole reason to exist (it had nothing else in
        # it). Checkable QActions directly on the menu instead of a dialog:
        # each toggle takes effect immediately (via apply_settings()), so a
        # modal OK/Cancel round-trip was never buying anything here. Left
        # enabled during a load (unlike Settings/Load/Tools below) — none of
        # these four CONFIG fields are ever read by DataLoaderThread, only by
        # the preview panel's own, GUI-thread-only rendering.
        view_menu = menubar.addMenu(tr("Вид"))
        self.view_menu = view_menu

        self.act_preview_enabled = QAction(tr("Включить предпросмотр"), self, checkable=True)
        self.act_preview_enabled.setChecked(CONFIG.preview_enabled)
        self.act_preview_enabled.toggled.connect(lambda checked: self._on_view_toggle("preview_enabled", checked))
        self._register_checkable_icon(self.act_preview_enabled)
        view_menu.addAction(self.act_preview_enabled)

        self.act_show_tree_view = QAction(tr("Показывать дерево и сведения"), self, checkable=True)
        self.act_show_tree_view.setChecked(CONFIG.show_tree_view)
        self.act_show_tree_view.toggled.connect(lambda checked: self._on_view_toggle("show_tree_view", checked))
        self._register_checkable_icon(self.act_show_tree_view)
        view_menu.addAction(self.act_show_tree_view)

        self.act_show_dump_view = QAction(tr("Показывать вкладку Дамп"), self, checkable=True)
        self.act_show_dump_view.setChecked(CONFIG.show_dump_view)
        self.act_show_dump_view.toggled.connect(lambda checked: self._on_view_toggle("show_dump_view", checked))
        self._register_checkable_icon(self.act_show_dump_view)
        view_menu.addAction(self.act_show_dump_view)

        self.act_show_structure_view = QAction(tr("Показывать вкладку Структура"), self, checkable=True)
        self.act_show_structure_view.setChecked(CONFIG.show_structure_view)
        self.act_show_structure_view.toggled.connect(lambda checked: self._on_view_toggle("show_structure_view", checked))
        self._register_checkable_icon(self.act_show_structure_view)
        view_menu.addAction(self.act_show_structure_view)

        # Also drives video autoplay (PreviewPanel) — see config.py's
        # autoplay_audio field comment for why a separate video-specific
        # toggle isn't worth having.
        self.act_autoplay_audio = QAction(tr("Автовоспроизведение аудио/видео"), self, checkable=True)
        self.act_autoplay_audio.setChecked(CONFIG.autoplay_audio)
        self.act_autoplay_audio.toggled.connect(lambda checked: self._on_view_toggle("autoplay_audio", checked))
        self._register_checkable_icon(self.act_autoplay_audio)
        view_menu.addAction(self.act_autoplay_audio)

        self.act_show_quick_filters_bar = QAction(tr("Показывать панель быстрых фильтров"), self, checkable=True)
        self.act_show_quick_filters_bar.setChecked(CONFIG.show_quick_filters_bar)
        self.act_show_quick_filters_bar.toggled.connect(self._on_quick_filters_bar_toggled)
        self._register_checkable_icon(self.act_show_quick_filters_bar)
        view_menu.addAction(self.act_show_quick_filters_bar)

        # Section 3.5: Mode — mutually exclusive workspace switch, not a
        # per-feature toggle like Вид above. SDF Viewer Mode swaps the flat
        # table for a grouped tree (see set_sdf_mode()) and isn't meant to
        # coexist with normal filtering/search, which is why this is a radio
        # pair rather than another checkable QAction next to it.
        mode_menu = menubar.addMenu(tr("Режим"))
        self.mode_menu = mode_menu
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        self.act_mode_standard = QAction(tr("Стандартный режим"), self, checkable=True)
        self.act_mode_standard.setChecked(True)
        mode_group.addAction(self.act_mode_standard)
        self._register_checkable_icon(self.act_mode_standard, radio=True)
        mode_menu.addAction(self.act_mode_standard)

        self.act_mode_sdf = QAction(tr("Режим SDF-шрифтов"), self, checkable=True)
        mode_group.addAction(self.act_mode_sdf)
        self._register_checkable_icon(self.act_mode_sdf, radio=True)
        mode_menu.addAction(self.act_mode_sdf)

        self.act_mode_sdf.toggled.connect(self.set_sdf_mode)

        # Section 4: Tools
        tools_menu = menubar.addMenu(tr("Инструменты"))
        self.tools_menu = tools_menu

        # First position, per request — the action used most often/reflexively
        # (jump straight to a known File ID/PathID) shouldn't sit below two
        # less frequently used tools.
        quick_jump_action = QAction(tr("Переход к объекту (File ID / PathID)..."), self)
        quick_jump_action.setShortcut(QKeySequence("Ctrl+G"))
        quick_jump_action.triggered.connect(self.show_quick_jump_dialog)
        tools_menu.addAction(quick_jump_action)

        search_action = QAction(tr("Поиск текста в объектах..."), self)
        search_action.triggered.connect(self.open_text_search_tool)
        tools_menu.addAction(search_action)

        field_table_action = QAction(tr("Инспектор полей MonoBehaviour..."), self)
        field_table_action.triggered.connect(self.open_field_table_tool)
        tools_menu.addAction(field_table_action)

        patch_relocation_action = QAction(tr("Перенести патчи на новую версию игры... [Exp]"), self)
        patch_relocation_action.triggered.connect(self.open_patch_relocation_tool)
        tools_menu.addAction(patch_relocation_action)


        scene_viewer_action = QAction(tr("Просмотр сцены..."), self)
        scene_viewer_action.triggered.connect(lambda: self.open_scene_viewer())
        tools_menu.addAction(scene_viewer_action)

        # Writes a Unity version into files whose header has none (instead of typing the fallback
        # version into the settings every session). Works on files on disk, so it needs no loaded game.
        version_writer_action = QAction(tr("Вшить версию в Unity файлы..."), self)
        version_writer_action.triggered.connect(self.open_version_writer)
        tools_menu.addAction(version_writer_action)
        # (IL2CPP script preparation is NOT a menu item — user request: it opens from «Исправить» next to the
        # preview's IL2CPP warning, and only when it would help; see _il2cpp_fix_available.)

        # Section 5: Help
        help_menu = menubar.addMenu(tr("Справка"))
        sdf_help_action = QAction(tr("Генерация SDF-шрифтов..."), self)
        sdf_help_action.triggered.connect(self.show_sdf_help_dialog)
        help_menu.addAction(sdf_help_action)
        about_action = QAction(tr("О программе..."), self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def _register_checkable_icon(self, action: QAction, radio: bool = False) -> None:
        """Gives a checkable QAction a real checkbox/radio icon (menu_icons.py,
        rendered from the app's own live QStyle — same look as every plain
        QCheckBox/QRadioButton elsewhere in the app) instead of relying on
        QMenu::indicator's QSS styling, which strips Qt's native indicator
        rendering for menu items specifically and can only ever fill the slot
        solid on :checked. radio=True for the mutually-exclusive Режим pair
        (a real radio dot, not a checkbox) — every other toggle in this app's
        menus is an independent on/off switch, so checkbox is the default.
        Sets the icon for the action's CURRENT checked state right away, then
        keeps it in sync via toggled — and registers the action so
        _apply_theme_name() can refresh it after a live theme switch (the icon is a
        pixmap captured from the style/palette at draw time, not something
        that re-renders itself automatically)."""
        get_icon = menu_icons.get_radio_icon if radio else menu_icons.get_checkbox_icon
        action.setIcon(get_icon(action.isChecked()))
        action.toggled.connect(lambda checked, act=action: act.setIcon(get_icon(checked)))
        self._checkable_menu_actions.append((action, radio))

    def _on_view_toggle(self, name: str, value: bool) -> None:
        setattr(CONFIG, name, value)
        save_persisted_config()
        self.preview_panel.apply_settings()

    def _on_quick_filters_bar_toggled(self, checked: bool) -> None:
        CONFIG.show_quick_filters_bar = checked
        save_persisted_config()
        self.quick_filters_bar.setVisible(checked)

    def set_language_choice(self, choice: str) -> None:
        """Настройки -> Язык: saved; the windows get the new language after a restart (said in that language)."""
        if choice == self._language_choice:
            return
        self._language_choice = choice
        app_language.save_choice(choice)
        for key, action in self.language_actions.items():
            action.setChecked(key == choice)
        QMessageBox.information(
            self, translate_to(choice, "Язык"),
            translate_to(choice, "Язык программы сменится после перезапуска UStudio."))

    def set_theme_choice(self, choice: str) -> None:
        """Настройки -> Тема: «Тёмная» / «Светлая» / «Как в системе» (saved; applied at once)."""
        self._theme_choice = choice
        theme.save_theme_choice(choice)
        for key, action in self.theme_actions.items():
            if action.isChecked() != (key == choice):
                action.setChecked(key == choice)
        self._apply_theme_name(theme.resolve_theme_name(choice))

    def _on_system_color_scheme_changed(self, *_args) -> None:
        """Windows switched between light and dark: followed only while the choice is «Как в системе»."""
        if self._theme_choice == theme.SYSTEM:
            self._apply_theme_name(theme.system_theme_name())

    def _apply_theme_name(self, name: str) -> None:
        if name == self._theme_name:
            return
        self._theme_name = name
        self._theme_colors = theme.apply_theme(QApplication.instance(), self._theme_name)

        # menu_icons' checkbox/radio icons are pixmaps captured from the style/
        # palette at draw time, not something that re-renders itself automatically
        # on a palette change — clear the cache and re-fetch each one now that
        # apply_theme() above has actually changed the palette they're drawn from.
        menu_icons.clear_cache()
        for action, is_radio in self._checkable_menu_actions:
            get_icon = menu_icons.get_radio_icon if is_radio else menu_icons.get_checkbox_icon
            action.setIcon(get_icon(action.isChecked()))

        # log()'s colors and JsonHighlighter's colors are literal, outside the QPalette
        # system that apply_theme() just updated everything else through — see
        # theme.py's module docstring. Already-appended log lines keep their old color
        # (baked into the widget's HTML content already), only the syntax highlighter
        # re-renders live since rehighlight() is cheap for the currently-shown document.
        self.preview_panel.apply_theme_colors(self._theme_colors)
        # table_selection_qss() is a per-widget setStyleSheet(), not covered by
        # apply_theme()'s app-wide QPalette/QSS refresh above — each theme now has
        # its own accent color (they used to share one, so this was previously a
        # no-op either way), so it needs an explicit re-apply on every toggle.
        self.table_view.setStyleSheet(theme.table_selection_qss(self._theme_colors))
        # Same reasoning — each quick-filter button's :checked color is baked
        # into its own literal stylesheet (per-button accent, not a single
        # global QSS rule — see quick_filters_bar.py), so it needs the same
        # explicit re-apply theme.py's own module docstring describes.
        self.quick_filters_bar.apply_theme_colors(self._theme_colors)
        self.table_notice.apply_theme_colors(self._theme_colors)     # its link colour (literal, like the log's)

    def init_ui(self):
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 0, 5, 5)     # no gap above the «Объекты» / «Окружение» tab bar

        search_box = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(tr("Начните печатать..."))
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self.on_filter_text_changed)
        
        self.btn_reset_view = QPushButton(tr("Сбросить вид"))
        self.btn_reset_view.setToolTip(wrap_tooltip(tr("Показать все объекты: снять фильтры и очистить поиск")))
        self.btn_reset_view.clicked.connect(self.reset_table_view)

        self.btn_filters = QPushButton(tr("Фильтры"))
        self.btn_filters.clicked.connect(self.open_filters_dialog)

        # «Поиск… N %» while a big table is searched in the background (user report, Lego Party: a first search
        # takes ~45 s and the field looked dead; the status line at the bottom went unnoticed). Inside the field
        # (gui_common.FieldNote): beside it, it widened the panel during every search (user report, 2026-10-19).
        self.search_progress_label = FieldNote(self.filter_input)

        search_box.addWidget(self.filter_input)
        search_box.addWidget(self.btn_filters)
        search_box.addWidget(self.btn_reset_view)
        # «Объекты» tab: search row, quick filters bar, the table / SDF tree (left_view_stack, added below)
        objects_page = QWidget()
        objects_layout = QVBoxLayout(objects_page)
        objects_layout.setContentsMargins(0, 8, 0, 0)    # under the tab bar, as the preview's side tabs
        objects_layout.addLayout(search_box)

        # File and type drop-downs (the type one also holds «Изменённые»/«Закладки»), right under the search
        # row — see quick_filters_bar.py's own module docstring. Shares
        # self.proxy_model with the flat table's own filtering (attach()
        # below), so it needs constructing after proxy_model exists but the
        # widget itself before that — built here, attached once proxy_model
        # is set up a few lines down.
        self.quick_filters_bar = QuickFiltersBar()
        self.quick_filters_bar.setVisible(CONFIG.show_quick_filters_bar)
        objects_layout.addWidget(self.quick_filters_bar)

        self.table_view = ObjectTableView()
        v_header = self.table_view.verticalHeader()
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        v_header.setDefaultSectionSize(22)

        h_header = self.table_view.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h_header.setDefaultSectionSize(120)
        h_header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

        self.table_model = ObjectTableModel()
        self.proxy_model = AdvancedFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.quick_filters_bar.attach(self.proxy_model)
        self.quick_filters_bar.open_filters_requested.connect(self.open_filters_dialog)
        # «Фильтры (N)» and an enabled «Сбросить вид» say that the table is filtered, whatever set it.
        self.proxy_model.filter_state_changed.connect(self._update_filter_buttons)
        self.proxy_model.filter_state_changed.connect(self._on_filter_state_for_reveal)   # the notice's «Показать в таблице»
        self.filter_input.textChanged.connect(self._update_filter_buttons)
        self._update_filter_buttons()
        # The background name warm-up (ObjectTableModel.start_name_warmup) pauses while the user scrolls/types.
        self._user_activity = UserActivityTracker(self)
        self._user_activity.attach(QApplication.instance())   # not installEventFilter: see attach()
        self.table_view.verticalScrollBar().valueChanged.connect(self._user_activity.touch)
        self.proxy_model.search_should_pause = self._background_busy         # the search waits while the user clicks
        self.table_model.warmup_should_pause = self._warmup_should_wait     # (main_load_flow.py: who waits for whom)

        self.table_view.setModel(self.proxy_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # ExtendedSelection (Ctrl/Shift-click) — needed for multi-row export
        # from the context menu (see object_actions.py's
        # _show_bulk_context_menu). Ctrl+A itself does NOT use this mode's
        # native selectAll() at all — see ObjectTableView.selectAll()'s
        # docstring for why. setCurrentIndex() (used by _jump_to_object/
        # PreviewPanel's back-navigation) still clears any multi-selection down
        # to just the target row under this mode — verified directly, not
        # assumed — so single-object navigation is unaffected.
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_view.setSortingEnabled(False)
        # No stretch column: a Stretch-mode column shrinks along with the table
        # whenever the main splitter moves (previously Размер was Stretch-mode and
        # got squeezed down to just a few visible characters whenever the left
        # panel was narrowed). Every column now has its own fixed, Interactive
        # width instead, and the table scrolls horizontally when it doesn't all
        # fit — same as it already did for the non-stretch columns before this.
        # See theme.TABLE_SELECTION_QSS's docstring for what this actually fixes
        # (current-cell outline + a Windows11-style per-cell selection artifact) —
        # shared with CabBrowserDialog's entry table, which has the same issue.
        self.table_view.setStyleSheet(theme.table_selection_qss(self._theme_colors))

        # Real reported request: narrowed across the board (Путь в контейнере/
        # Скрипт/PathID/Изменено in particular — usually short or empty content)
        # so the table fits without horizontal scrolling at 1920x1080. Only the
        # DEFAULT for a first run — gui_layout.py remembers whatever the user
        # actually resizes these to afterward.
        self.table_view.setColumnWidth(0, 140)   # Имя
        self.table_view.setColumnWidth(1, 50)    # Путь в контейнере
        self.table_view.setColumnWidth(2, 50)    # Скрипт
        self.table_view.setColumnWidth(3, 100)   # Тип
        self.table_view.setColumnWidth(4, 70)   # Источник
        self.table_view.setColumnWidth(5, 60)    # PathID
        self.table_view.setColumnWidth(6, 60)    # Размер
        self.table_view.setColumnWidth(7, 20)    # Изменено

        self.table_view.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.table_view.select_all_requested.connect(self._on_select_all_requested)
        self._init_bookmarks()          # «Закладки»: store, Ctrl+D, the bar's toggle (main_bookmarks.py)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # customContextMenuRequested is connected to self.object_actions.show_context_menu
        # in __init__, after object_actions itself is constructed.

        # Right-click a column header to show/hide any column — useful now that
        # Путь в контейнере (usually empty for most rows) competes for space with
        # everything else.
        h_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        h_header.customContextMenuRequested.connect(self._show_column_visibility_menu)

        # SDF Viewer Mode's grouped tree (see set_sdf_mode()) — a separate,
        # isolated view swapped in for the flat table, not a filter layered
        # on top of it (see sdf_group_model.py's own module docstring for
        # why). Built here unconditionally (cheap — an empty model until
        # set_sdf_mode(True) first populates it) so toggling the mode never
        # has to lazily construct UI mid-session.
        self.sdf_group_model = SDFGroupModel()
        self._sdf_coverage_cache = {}   # group id -> "N симв. · кириллица", see _start_sdf_coverage
        self._sdf_build_generation = 0  # bumped by every _refresh_sdf_groups() / stop: stale results are dropped
        self._sdf_build_worker = None
        self.sdf_tree_view = QTreeView()
        self.sdf_tree_view.setModel(self.sdf_group_model)
        self.sdf_tree_view.setItemDelegate(SDFGroupSpacingDelegate(self.sdf_tree_view))
        # Same selection as the main table: Ctrl/Shift click and dragging down across rows.
        self.sdf_tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sdf_tree_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sdf_tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sdf_tree_view.setColumnWidth(0, 240)  # Имя
        self.sdf_tree_view.setColumnWidth(1, 100)  # Тип
        self.sdf_tree_view.setColumnWidth(2, 100)  # Источник

        self.left_view_stack = QStackedWidget()
        # Standard Mode page: the table with a thin notice line above it, shown when the object a jump opened
        # has no selected row (hidden by filters / not in the table) — see main_navigation._sync_table_to.
        table_page = QWidget()
        table_page_layout = QVBoxLayout(table_page)
        table_page_layout.setContentsMargins(0, 0, 0, 0)
        table_page_layout.setSpacing(2)
        self.table_notice = TableNoticeBar()
        self.table_notice.apply_theme_colors(self._theme_colors)
        self.table_notice.action_requested.connect(self._on_table_notice_action)
        self.table_notice.btn_close.clicked.connect(self._forget_table_notice)
        table_page_layout.addWidget(self.table_notice)
        table_page_layout.addWidget(self.table_view)
        self.left_view_stack.addWidget(table_page)   # index 0 — Standard Mode
        # SDF Viewer Mode page: its own search box (the main table's filter box acts on the flat
        # table, which is not the visible view here) above the tree.
        sdf_page = QWidget()
        sdf_page_layout = QVBoxLayout(sdf_page)
        sdf_page_layout.setContentsMargins(0, 0, 0, 0)
        self.sdf_filter_input = QLineEdit()
        self.sdf_filter_input.setPlaceholderText(tr("Поиск шрифта, материала или атласа..."))
        self.sdf_filter_input.setClearButtonEnabled(True)
        self.sdf_filter_input.textChanged.connect(self._on_sdf_filter_changed)
        # Quick expand/collapse of every group — a loaded game can have dozens of font groups.
        sdf_page_layout.addWidget(self.sdf_filter_input)
        sdf_toolbar = QHBoxLayout()
        sdf_toolbar.setContentsMargins(0, 0, 0, 0)
        self.btn_sdf_expand_all = QPushButton(tr("Развернуть всё"))
        self.btn_sdf_expand_all.setToolTip(wrap_tooltip(tr("Раскрыть все группы шрифтов.")))
        self.btn_sdf_expand_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_sdf_expand_all.clicked.connect(self.sdf_tree_view.expandAll)
        self.btn_sdf_collapse_all = QPushButton(tr("Свернуть всё"))
        self.btn_sdf_collapse_all.setToolTip(wrap_tooltip(tr("Свернуть все группы шрифтов.")))
        self.btn_sdf_collapse_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_sdf_collapse_all.clicked.connect(self.sdf_tree_view.collapseAll)
        sdf_toolbar.addWidget(self.btn_sdf_expand_all)
        sdf_toolbar.addWidget(self.btn_sdf_collapse_all)
        sdf_page_layout.addLayout(sdf_toolbar)
        # "Поиск SDF-шрифтов…" while the groups are being built in the background; "не найдены" after
        # a build that found none. Hidden otherwise.
        self.sdf_status_label = QLabel("")
        self.sdf_status_label.setObjectName("MutedCaption")
        self.sdf_status_label.hide()
        sdf_page_layout.addWidget(self.sdf_status_label)
        sdf_page_layout.addWidget(self.sdf_tree_view)
        self.left_view_stack.addWidget(sdf_page)  # index 1 — SDF Viewer Mode

        # QTextBrowser, not plain QTextEdit — a strict superset (append()/clear()/
        # toHtml()/etc. all still work identically), needed for anchorClicked,
        # which plain QTextEdit doesn't have at all. setOpenLinks(False) disables
        # QTextBrowser's OWN default link handling (which otherwise treats a
        # clicked link as "navigate this widget's document to a new source" —
        # for a file:// URL, it would try to load that path as this browser's
        # own content, wiping the log) — log_with_folder_link()'s anchorClicked
        # connection below is the only thing that should react to a click.
        self.log_area = QTextBrowser()
        self.log_area.setOpenLinks(False)
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(40)
        self.log_area.anchorClicked.connect(self._on_log_link_clicked)

        # Real reported request: the log area's height was a hardcoded
        # setMaximumHeight(120), not adjustable at all. A vertical QSplitter
        # (kept in place UNDER the table — see the same request's own doubts
        # about relocating it under the preview panel instead, declined:
        # log lines are about table-driven operations — loads, exports,
        # imports — not tied to whatever object happens to be previewed, and
        # the preview panel's own tab1_splitter already manages its own
        # sidebar split, so folding a third, unrelated concern into it would
        # break PreviewPanel's documented narrow public surface for no real
        # gain) replaces the old fixed addWidget pair. gui_layout.py persists
        # its size the same way as main_splitter/tab1_splitter.
        objects_layout.addWidget(self.left_view_stack)
        # «Объекты» / «Окружение» (the loaded files as a tree — environment_view.py, main_environment.py); the log
        # stays under both.
        self.environment_view = EnvironmentView()
        self.environment_view.show_objects_requested.connect(self._show_file_objects)
        self.environment_view.export_requested.connect(self._export_file_objects)
        self.environment_view.open_archive_requested.connect(self._open_archive_from_environment)
        self.environment_view.reveal_requested.connect(self._reveal_from_environment)
        environment_page = QWidget()
        environment_layout = QVBoxLayout(environment_page)
        environment_layout.setContentsMargins(0, 8, 0, 0)    # under the tab bar, as the preview's side tabs
        environment_layout.addWidget(self.environment_view)
        self.left_tabs = QTabWidget()
        self.left_tabs.setDocumentMode(True)
        self.left_tabs.tabBar().setDrawBase(False)     # its base line is a white stripe in the dark theme (as side_tabs)
        self.left_tabs.addTab(objects_page, tr("Объекты"))
        self.left_tabs.addTab(environment_page, tr("Окружение"))

        self.left_splitter = QSplitter(Qt.Orientation.Vertical)
        self.left_splitter.addWidget(self.left_tabs)
        self.left_splitter.addWidget(self.log_area)
        self.left_splitter.setSizes([600, 120])
        left_layout.addWidget(self.left_splitter)

        # Preview + Dump tabs, and the background-threaded read pipeline behind
        # them — see preview_panel.py.
        self.preview_panel = PreviewPanel()
        # apply_theme_colors() is otherwise only called from _apply_theme_name() (a live
        # switch) — needs an initial call too, or the JsonHighlighter/structure tree
        # never learn the colors self._theme_colors was already computed with in
        # __init__ before the very first thing gets previewed.
        self.preview_panel.apply_theme_colors(self._theme_colors)
        self.preview_panel.jump_to_object_requested.connect(self._jump_to_object)
        self.preview_panel.edit_object_requested.connect(self._edit_object_from_tree)
        self.preview_panel.export_object_requested.connect(self._export_object_from_details)
        self.preview_panel.export_menu_requested.connect(self._export_menu_from_details)
        self.preview_panel.import_object_requested.connect(self._import_object_from_details)
        self.preview_panel.il2cpp_prepare_requested.connect(self.open_il2cpp_prepare)
        self.preview_panel.il2cpp_fix_available = self._il2cpp_fix_available
        self.preview_panel.scene_viewer_requested.connect(lambda obj: self.open_scene_viewer(highlight_obj=obj))
        # Same "needs an initial call too" reasoning as preview_panel above —
        # each quick-filter button's stylesheet is built once it exists, not
        # derived from the app-wide QPalette apply_theme() already handled.
        self.quick_filters_bar.apply_theme_colors(self._theme_colors)

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(self.preview_panel)
        
        main_splitter.setSizes([460, 700])
        self.main_splitter = main_splitter

        self.status_label = QLabel(tr("Ожидание выбора источника загрузки..."))
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.hide()
        # explicit reminder that a long operation (loading/scanning/extraction)
        # can be cancelled with Esc — visible while progress is showing
        self.esc_hint_label = QLabel(tr("Esc — отмена"))
        self.esc_hint_label.setStyleSheet("color: gray;")
        self.esc_hint_label.hide()
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addWidget(self.esc_hint_label)
        self.statusBar().addWidget(self.progress_bar)

        # Indicator + entry point for the export/import task queue (task_queue.py) —
        # a permanent widget (right-aligned, survives status_label's temporary
        # messages) since queue state is meaningful independent of load progress.
        self.task_queue_status_widget = TaskQueueStatusWidget(self.task_queue_manager)
        self.task_queue_status_widget.clicked_for_panel.connect(self._show_task_queue_panel)
        self.statusBar().addPermanentWidget(self.task_queue_status_widget)

        # A script-restricted Quick Filter / FiltersDialog Apply (proxy_model),
        # or sorting by Имя/Скрипт (table_model), can each force a background
        # name/script-name resolution pass — see
        # object_table.AdvancedFilterProxyModel.set_type_script_filter() and
        # object_table.ObjectTableModel.sort()'s own docstrings for why. Both
        # report through the same status_label/progress_bar every other
        # background operation in this app already uses, rather than inventing
        # a separate indicator per source.
        self.proxy_model.resolve_started.connect(self._on_script_resolve_started)
        self.proxy_model.resolve_progress.connect(self._on_script_resolve_progress)
        self.proxy_model.resolve_finished.connect(self._on_script_resolve_finished)
        self.table_model.resolve_started.connect(self._on_script_resolve_started)
        self.table_model.resolve_progress.connect(self._on_script_resolve_progress)
        self.table_model.resolve_finished.connect(self._on_script_resolve_finished)

        # Overrides the defaults just set above (column widths, splitter sizes,
        # hidden columns) with whatever was saved last session — see
        # gui_layout.py's own docstring for the fallback-to-defaults safeguard
        # when a saved value doesn't match the current layout shape.
        restore_layout(self)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            loader = getattr(self, "loader_thread", None)
            if loader is not None and loader.isRunning():
                loader.requestInterruption()
                self.log(tr("Нажат Esc — прерывание текущей операции..."), LogLevel.WARNING)
                self.status_label.setText(tr("Отмена операции..."))
                event.accept()
                return
            # SaveThread checks isInterruptionRequested() BETWEEN files only — see
            # save_thread.py/core.save_manager.save_changed_files's docstrings for why.
            save_thread = getattr(self, "save_thread", None)
            if save_thread is not None and save_thread.isRunning():
                save_thread.requestInterruption()
                self.log(tr("Нажат Esc — прерывание текущей операции..."), LogLevel.WARNING)
                self.status_label.setText(tr("Отмена операции..."))
                event.accept()
                return
            # object_actions owns the bulk-dump thread — see try_cancel()'s docstring.
            if self.object_actions.try_cancel():
                self.log(tr("Нажат Esc — прерывание текущей операции..."), LogLevel.WARNING)
                self.status_label.setText(tr("Отмена операции..."))
                event.accept()
                return
        super().keyPressEvent(event)

    def _show_task_queue_panel(self):
        if self.task_queue_panel is None:
            self.task_queue_panel = TaskQueuePanel(self.task_queue_manager, self)
        self.task_queue_panel.show()
        self.task_queue_panel.raise_()
        self.task_queue_panel.activateWindow()

    def closeEvent(self, event):
        save_layout(self)

        # Every background thread the app can have in flight gets a real chance to
        # stop here, not just "usually can't happen because menus were locked" — the
        # window's own close button (unlike the menu actions) was never actually
        # gated on a load being in progress, so a user closing mid-load is a real
        # case, not just a hypothetical one. loader_thread already treats
        # isInterruptionRequested() as its should_cancel signal (see loader_thread.py)
        # — request it and give it a bounded window to actually exit before
        # proceeding, same reasoning as PreviewPanel.cleanup()'s own wait() just
        # below, just a longer budget since a load does more work per cancellation
        # check than a single preview read.
        loader = getattr(self, "loader_thread", None)
        if loader is not None and loader.isRunning():
            loader.requestInterruption()
            loader.wait(5000)
        self._stop_sdf_background()

        # The export/import queue's own worker thread — see task_queue.py's
        # shutdown() docstring; this replaces what used to be a standalone
        # object_actions._BulkDumpThread with no close-time handling at all.
        self.task_queue_manager.shutdown()

        self.preview_panel.cleanup()
        self.proxy_model.cleanup()
        self.table_model.cleanup()
        self._user_activity.detach()

        # Fix for a real reported crash: "Exception ignored in atexit callback
        # <function shutdown ...>: RuntimeError: wrapped C/C++ object of type
        # QtLogHandler has been deleted" — see detach_qt_log_handler()'s docstring
        # for the full root-cause chain (it's not just "call close()").
        detach_qt_log_handler(self._qt_log_handler, logging.getLogger("ustudio"))

        super().closeEvent(event)

    def on_progress(self, level, i, total, name, status_description):
        if level == 0:
            self._top = (i, total, name)
            self._inner = None   # new top-level file -> reset the nested progress
        else:
            self._inner = (i, total, name)
        self._render(status_description)

    def _render(self, status_description: str):
        parts = []

        # Top-level progress (files in the folder)
        if self._top:
            i, total, name = self._top
            if total:
                label = f"{status_description} {i}/{total}"
                # Real reported bug: the final progress update (e.g. "1/1", load
                # complete) can carry an empty name — there's no longer a specific
                # file to name — but the ": " separator was always appended
                # regardless, leaving a dangling "Загружено 1/1:" with nothing
                # after the colon. Only append the name (and its colon) when
                # there actually is one.
                if name:
                    label += f": {Path(name).name}"
                parts.append(label)

        # Inner progress (files inside a bundle)
        if self._inner:
            ii, itotal, iname = self._inner
            if itotal:
                prefix = "" if parts else f"{status_description} "
                label = f"{prefix}{ii}/{itotal}"
                if iname:
                    label += f": {iname}"
                parts.append(label)

        text = " → ".join(parts) if parts else "N/N"
        self.status_label.setText(text)

    # --- New menu item handlers ---

    def on_menu_load_files(self):
        start_dir = self.settings.value("last_files_dir", "")
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("Выберите файлы для загрузки"), start_dir, tr("Все файлы (*)")
        )
        if files:
            self.settings.setValue("last_files_dir", str(Path(files[0]).parent))
            self.log_area.clear()

            CONFIG.load_mode = LoadMode.FILES
            CONFIG.selected_files = files

            #self.log(f"[DEBUG] Выбрано файлов для импорта: {len(files)}")

            paths = update_game_paths(Path(files[0]))
            #if paths["managed_dir"]:
            #    self.log(f"[DEBUG] Найдена папка Managed: {paths['managed_dir']}")

            #if paths["game_root_dir"]:
            #    self.log(f"[DEBUG] Определена корневая папка игры: {paths['game_root_dir']}")

            self.start_loading_data()
    
    def on_menu_load_folder(self):
        start_dir = self.settings.value("last_folder_dir", "")
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("Выберите папку с игровыми данными"),
            start_dir,
        )

        if not folder:
            return

        self.settings.setValue("last_folder_dir", folder)
        self.log_area.clear()

        CONFIG.load_mode = LoadMode.FOLDER
        CONFIG.selected_dir = folder
        #self.log(f"[DEBUG] Установлена папка для импорта: {folder}")

        paths = update_game_paths(Path(folder))

        #if paths["managed_dir"]:
        #    self.log(f"[DEBUG] Найдена папка Managed: {paths['managed_dir']}")

        #if paths["game_root_dir"]:
        #    self.log(f"[DEBUG] Определена корневая папка игры: {paths['game_root_dir']}")

        self.start_loading_data()

    def on_menu_set_fallback(self):
        dialog = InputSettingDialog(
            self, 
            tr("Fallback версия Unity"), 
            tr("Введите версию Unity для использования при сбоях автоопределения:"), 
            hint_text=tr("Формат ввода версии: например, 2021.3.0f1 или 6000.0.58f2"),
            current_value=CONFIG.fallback_version
        )
        if exec_and_dispose(dialog) == QDialog.DialogCode.Accepted:
            CONFIG.fallback_version = dialog.get_value()
            self.log(tr("Установлена резервная версия Unity: {version}", version=CONFIG.fallback_version))

    def on_menu_set_unity_cn(self):
        dialog = InputSettingDialog(
            self, 
            tr("Ключ Unity CN"), 
            tr("Укажите ключ расшифровки для Unity CN (китайский регион):"), 
            current_value=CONFIG.unity_cn_key
        )
        if exec_and_dispose(dialog) == QDialog.DialogCode.Accepted:
            CONFIG.unity_cn_key = dialog.get_value()
            self.log(tr("Ключ шифрования Unity CN сохранен."))

    def on_menu_app_settings(self):
        config_values = {
            "object_count_threshold": CONFIG.object_count_threshold,
            "export_grouping": CONFIG.export_grouping,
            "export_assets_subfolder": CONFIG.export_assets_subfolder,
            "export_overwrite": CONFIG.export_overwrite,
            "export_open_folder_after": CONFIG.export_open_folder_after,
            "backup_before_overwrite": CONFIG.backup_before_overwrite,
            "backup_keep_latest": CONFIG.backup_keep_latest,
            "bundle_compression_packer": CONFIG.bundle_compression_packer,
            "indexed_types": CONFIG.indexed_types,
            "preview_font_family": CONFIG.preview_font_family,
            "preview_font_size": CONFIG.preview_font_size,
            "texture_import_format_mode": CONFIG.texture_import_format_mode,
            "texture_import_manual_format": CONFIG.texture_import_manual_format,
            "texture_import_quality": CONFIG.texture_import_quality,
            "texture_import_mipmaps": CONFIG.texture_import_mipmaps,
            "audio_import_quality": CONFIG.audio_import_quality,
            "resource_target_mode": CONFIG.resource_target_mode,
            "resource_name": CONFIG.resource_name,
            "char_coverage_label": CONFIG.char_coverage_label,
            "char_coverage_chars": CONFIG.char_coverage_chars,
            "show_debug_log": CONFIG.show_debug_log,
        }
        dialog = ApplicationSettingsDialog(self, config_values)
        dialog.font_apply_requested.connect(self._apply_font_live)
        if exec_and_dispose(dialog) == QDialog.DialogCode.Accepted:
            values = dialog.get_values()
            coverage_changed = (values.get("char_coverage_label") != CONFIG.char_coverage_label
                                or values.get("char_coverage_chars") != CONFIG.char_coverage_chars)
            for name, value in values.items():
                setattr(CONFIG, name, value)
            self._qt_log_handler.show_debug = CONFIG.show_debug_log
            save_persisted_config()
            self.preview_panel.refresh_fonts()
            if coverage_changed:
                self._apply_char_coverage_setting()
            self.log(tr("Настройки программы обновлены."))

    def _apply_char_coverage_setting(self) -> None:
        """The "does this font support ___" check was just redefined (label and/or character set)
        — takes effect immediately for the next preview (nothing there is cached), but the SDF
        Viewer's own per-font coverage text (see _sdf_coverage_cache) IS cached to avoid re-parsing
        every font on every refresh, so that cache holds text computed against the OLD setting and
        needs an explicit nudge or it would keep showing stale results."""
        object_metadata.set_char_coverage(CONFIG.char_coverage_label, CONFIG.char_coverage_chars)
        self._sdf_coverage_cache = {}
        if self.left_view_stack.currentIndex() == 1:
            self._stop_sdf_coverage()
            self._start_sdf_coverage(self.sdf_group_model._all_groups)

    def _apply_font_live(self, family: str, size: int) -> None:
        # "Применить" in the font section — commits just these two fields
        # immediately (same Apply-vs-OK/Cancel convention as any standard
        # settings dialog: a Cancel afterward does not undo an already-
        # applied change), so the effect is visible against the real preview
        # panel without closing the dialog first.
        CONFIG.preview_font_family = family
        CONFIG.preview_font_size = size
        save_persisted_config()
        self.preview_panel.refresh_fonts()

    def on_menu_set_cab_collision_policy(self):
        dialog = CabCollisionSettingsDialog(self, CONFIG.cab_collision_policy, CONFIG.excluded_folders)
        if exec_and_dispose(dialog) == QDialog.DialogCode.Accepted:
            CONFIG.cab_collision_policy = dialog.get_policy()
            CONFIG.excluded_folders = dialog.get_excluded_folders()
            save_persisted_config()
            self.log(tr("Настройки коллизий обновлены."))
            # behaviour = ("загрузка прерывается при первом совпадении имён"
            #              if CONFIG.cab_collision_policy == "raise"
            #              else "файлы с одинаковыми именами загружаются все")
            # self.log(f"Совпадения имён файлов: {behaviour}. Исключённых папок: {len(CONFIG.excluded_folders)}.")

    def _on_load_all_assets_toggled(self, checked: bool) -> None:
        CONFIG.load_all_assets = checked
        save_persisted_config()
        self.log(tr("Индексирование всех объектов включено. Изменение вступит в силу при следующей загрузке.")
                 if checked else
                 tr("Индексирование всех объектов выключено. Изменение вступит в силу при следующей загрузке."))

    # (the save / overwrite / revert flow lives in main_save_flow.py — SaveFlowMixin)

    # (loading data — start, progress, finish, table fill — lives in main_load_flow.py — LoadFlowMixin)

    # --- Basic interface methods ---

    def on_filter_text_changed(self, text): self.filter_timer.start(500)
    def apply_table_filter(self):
        # A filter change makes "every currently-visible row" (virtual
        # select-all's meaning) potentially a different set than what was
        # active when it was triggered — reset it, same as a real selection
        # change (on_selection_changed). Covers text search (this method is
        # the debounced handler for it), reset_table_view(),
        # filter_to_type_or_script(), and _jump_to_object() — all of which
        # already call this as their last step.
        self.table_view.select_all_active = False
        self.proxy_model.setFilterFixedString(self.filter_input.text())
    def reset_table_view(self):
        # Always a full, one-step reset — a first attempt at a "one-level
        # undo" (restore whatever type/script filter was active right before
        # a hard filter) was reported back as more confusing than helpful:
        # the previous, fully predictable "always shows everything" behavior
        # was preferred. Now that hard filtering (filter_to_type_or_script())
        # IS the type/script filter rather than a separate layer on top of it
        # (see AdvancedFilterProxyModel's docstring), there's nothing left
        # that a partial rollback would even need to distinguish.
        self.filter_input.clear()
        self.proxy_model.set_type_script_filter(None, None)
        self.proxy_model.set_quick_filter_state(None, False)
        self.proxy_model.set_bookmark_filter(None)
        self.apply_table_filter()
        self.log(tr("Отображение таблицы сброшено."))

    def open_filters_dialog(self):
        if not self.raw_data_list:
            self.log(tr("Сначала загрузите файлы игры."), LogLevel.WARNING)
            return

        dialog = FiltersDialog(
            self.raw_data_list, self.proxy_model.allowed_types, self.proxy_model.allowed_scripts,
            self.proxy_model.allowed_sources, parent=self, keep_busy=self._user_activity.touch,
        )
        if exec_and_dispose(dialog) != QDialog.DialogCode.Accepted:
            return

        selected_types = dialog.get_selected_types()
        selected_scripts = dialog.get_selected_scripts()
        selected_sources = dialog.get_selected_sources()
        # Every value the dialog listed, from its own checklists (no second pass over the rows). The script
        # values are the qualified names the checklist shows, so «everything ticked» is recognised for
        # namespaced scripts too (comparing them with bare names never matched).
        all_types = dialog.all_types()
        all_scripts = dialog.all_scripts()
        all_sources = dialog.all_sources()
        # Everything selected == no restriction — treated as None (cheaper
        # filterAcceptsRow check, and semantically the same thing) rather than
        # stored as a full set that happens to match everything.
        type_filter = None if selected_types >= all_types else selected_types
        script_filter = None if selected_scripts >= all_scripts else selected_scripts
        if not dialog.scripts_ready:
            # «Применить» before the MonoBehaviour tab finished building its list: nothing was chosen there.
            script_filter = self.proxy_model.allowed_scripts
        source_filter = None if selected_sources >= all_sources else selected_sources
        self.table_view.select_all_active = False  # see apply_table_filter()'s comment — same reasoning
        self.proxy_model.set_type_script_filter(type_filter, script_filter)
        self.proxy_model.set_quick_filter_state(source_filter, self.proxy_model.modified_only)
        # (the quick filters bar follows the proxy's filter_state_changed on its own)

    def active_filter_count(self) -> int:
        """How many filter dimensions restrict the table: type/script, file, «only modified», «Закладки»."""
        proxy = self.proxy_model
        types, scripts = proxy.requested_type_script_filter()
        return (int(types is not None or scripts is not None) + int(proxy.allowed_sources is not None)
                + int(bool(proxy.modified_only)) + int(proxy.bookmark_matcher is not None))

    def _update_filter_buttons(self, *_args) -> None:
        count = self.active_filter_count()
        self.btn_filters.setText(tr("Фильтры ({count})", count=count) if count else tr("Фильтры"))
        self.btn_reset_view.setEnabled(bool(count) or bool(self.filter_input.text()))

    # --- background name/script-name resolution (Quick Filters / Фильтры / sorting) ---
    # Shared by TWO independent background-resolve mechanisms with the identical
    # shape and signal names — object_table.AdvancedFilterProxyModel.
    # set_type_script_filter() (a script-restricted Quick Filter/FiltersDialog)
    # and object_table.ObjectTableModel.sort() (sorting by Имя/Скрипт) — see
    # either method's own docstring for why each needed this. Generic wording
    # here since either one can trigger it (a name sort resolves Имя, not
    # scripts) — this handler doesn't need to know or care which.

    # What the emitting model is doing (its `resolve_kind`): each gets its own wording, because one shared
    # "names/scripts" line made two different passes in a row look like the same operation running twice.
    _RESOLVE_STATUS = {
        "names": (N_("Определение имён объектов..."), N_("Имена объектов определены.")),
        "scripts": (N_("Определение скриптов объектов..."), N_("Скрипты объектов определены.")),
        "filter": (N_("Фильтрация объектов..."), N_("Фильтрация завершена.")),
    }

    def _resolve_status(self) -> tuple:
        texts = self._RESOLVE_STATUS.get(getattr(self.sender(), "resolve_kind", "scripts"), self._RESOLVE_STATUS["scripts"])
        return tuple(tr(t) for t in texts)

    def _is_search_pass(self) -> bool:
        return getattr(self.sender(), "resolve_kind", None) == "filter"

    def _on_script_resolve_started(self) -> None:
        self.status_label.setText(self._resolve_status()[0])
        self.progress_bar.setRange(0, 0)  # indeterminate until the first real report
        self.progress_bar.show()
        if self._is_search_pass():
            self._search_shown_percent = None
            self.search_progress_label.start()

    def _on_script_resolve_progress(self, current: int, total: int) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(current)
        if not self._is_search_pass():
            self.status_label.setText(f"{self._resolve_status()[0]} {current}/{total}")
            return
        # A search: the status line keeps its one text (the bar beside it moves), and the note by the field (fixed size)
        # changes only with the percentage, at most ~3 times a second. A text change re-lays-out the window and
        # repainted the table — hundreds of Python calls that wait behind the search thread; measured in the real window
        # (Lego Party, a repeated search): 18 GUI pauses over 100 ms (3.1 s) with a new text per report, 5 (0.8 s) without.
        percent = current * 100 // max(total, 1)
        now = time.monotonic()
        if percent == getattr(self, "_search_shown_percent", None) or (
                now - getattr(self, "_search_shown_at", 0.0) < 0.3 and percent < 100):
            return
        self._search_shown_percent, self._search_shown_at = percent, now
        self.search_progress_label.set_percent(percent)

    def _on_script_resolve_finished(self) -> None:
        self.progress_bar.hide()
        self.status_label.setText(self._resolve_status()[1])
        # Not by resolve_kind: a script pass of the same proxy may have changed it meanwhile.
        if self.sender() is self.proxy_model and not getattr(self.proxy_model, "search_in_progress", False):
            self.search_progress_label.stop()

    def _show_column_visibility_menu(self, pos):
        """Right-click on any column header — a checkable list of every column,
        toggling hideColumn()/showColumn(). Not persisted across restarts (unlike
        the column widths, which QTableView already keeps in sync with user
        drags on its own within a session) — a lightweight per-session
        convenience, not a setting."""
        header = self.table_view.horizontalHeader()
        menu = QMenu(self)
        # Real reported regression: theme.py's global QMenu::indicator zero-out
        # (needed for the icon-based checkable menus elsewhere) also hid this
        # menu's own plain native checkboxes, with no icon to replace them —
        # this objectName is exactly what theme.py's scoped override rule
        # matches to bring them back for this menu specifically.
        menu.setObjectName("columnVisibilityMenu")
        for col in range(self.table_model.columnCount()):
            label = self.table_model.headers[col]
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.table_view.isColumnHidden(col))
            action.toggled.connect(lambda checked, c=col: self.table_view.setColumnHidden(c, not checked))
        menu.exec(header.mapToGlobal(pos))

    def filter_to_type_or_script(self, target_value: str, is_script: bool):
        """"Hard filtering" to exactly one type (or, for a MonoBehaviour
        script, exactly one script) — used by tools/text_search_tool.py's
        "Отобразить все объекты этого типа" context menu action.

        This restricts the table by directly setting the SAME type/script
        filter the Filters dialog's own checkboxes control (allowed_types/
        allowed_scripts on AdvancedFilterProxyModel), rather than through a
        separate isolation layer stacked on top of it (the previous design).
        That separation was a real reported bug: isolating to a type that
        happened to be UNCHECKED in Filters produced a silently empty table —
        the isolation and the checkbox filter combined with AND logic, so the
        isolation's own target could be excluded by leftover checkbox state
        with no indication why. Since "hard filtering" now directly IS the
        Filters selection, that can no longer happen, and Reset View's plain
        full reset is already the complete undo for it."""
        if is_script:
            self.proxy_model.set_type_script_filter({"MonoBehaviour"}, {target_value})
        else:
            self.proxy_model.set_type_script_filter({target_value}, None)
        self.apply_table_filter()
        self.log(tr("Включена фильтрация по значению: «{value}». Для сброса нажмите кнопку «Сбросить вид».",
                    value=target_value))
        self.raise_()
        self.activateWindow()

    def open_text_search_tool(self):
        if not self.search_tool_dialog:
            self.search_tool_dialog = TextSearchDialog(self)
            self.search_tool_dialog.show()
        else:
            self.search_tool_dialog.show()

    def open_field_table_tool(self, focus_obj=None, needle: str = ""):
        """Инструменты -> Инспектор полей MonoBehaviour...» (tools/field_table_tool.py). One window per main window,
        like the text search; it reads the loaded objects, so it is closed before they are released
        (main_save_flow's teardown lists). From the text search: `focus_obj` (a MonoBehaviour) and the text
        searched for — its script is selected and the fields holding that text are ticked."""
        if self.field_table_dialog is None:
            self.field_table_dialog = FieldTableDialog(self)
        if focus_obj is not None:
            self.field_table_dialog.focus_object(focus_obj, needle)
        self.field_table_dialog.show()
        self.field_table_dialog.raise_()
        self.field_table_dialog.activateWindow()

    def open_patch_relocation_tool(self):
        """Инструменты -> «Перенести патчи на новую версию игры...» (tools/patch_relocation_tool.py): new names for a
        folder of patches exported from an older build. One window per main window; it reads the loaded objects, so
        it is in main_save_flow's teardown lists. Without a loaded game it only says so (user request)."""
        if self.env is None or not self.raw_data_list:
            exec_and_dispose(QMessageBox(QMessageBox.Icon.Warning, tr("Перенос патчей"),
                                         tr("Сначала откройте обновлённую игру."), QMessageBox.StandardButton.Ok, self))
            return
        if self.patch_relocation_dialog is None:
            self.patch_relocation_dialog = PatchRelocationDialog(self)
        self.patch_relocation_dialog.show()
        self.patch_relocation_dialog.raise_()
        self.patch_relocation_dialog.activateWindow()

    def add_to_field_table(self, objs, needle: str) -> str:
        """The text search's «Добавить в инспектор полей»: the fields of `objs` holding `needle` are ticked in the
        field inspector, which is created if needed but NOT shown (FieldTableDialog.add_objects). Returns the line
        the text search shows."""
        if self.field_table_dialog is None:
            self.field_table_dialog = FieldTableDialog(self)
        return self.field_table_dialog.add_objects(objs, needle)

    def open_cab_browser(self):
        if not self.cab_browser_dialog:
            self.cab_browser_dialog = CabBrowserDialog(self)
            self.cab_browser_dialog.show()
        else:
            self.cab_browser_dialog.show()

    def _build_source_assets_file_map(self) -> dict:
        """{source file name: its SerializedFile} for every distinct source
        currently in the main table — reuses obj_ref.assets_file already
        sitting on each row rather than walking self.env.files separately
        (which would also need to recurse into BundleFile.files to find
        nested SerializedFiles, duplicating work the table's own rows already
        did at load time). One row per distinct source is enough; every row
        from the same file shares the same assets_file instance."""
        files_by_name = {}  # source name -> distinct assets files carrying it
        for item in self.raw_data_list:
            source = item.get("source")
            obj = item.get("obj_ref")
            if source and obj is not None and obj.assets_file is not None:
                bucket = files_by_name.setdefault(source, {})
                bucket.setdefault(id(obj.assets_file), obj.assets_file)
        result = {}
        self._scene_label_by_file_id = {}
        for source, bucket in files_by_name.items():
            for assets_file in bucket.values():
                # Several loaded games/folders can each have a "level0": those get the
                # containing folder appended so every file is its own entry instead of one
                # silently replacing the others.
                label = source if len(bucket) == 1 else f"{source} — {self._file_folder_hint(assets_file)}"
                result[label] = assets_file
                self._scene_label_by_file_id[id(assets_file)] = label
        return result

    def _file_folder_hint(self, assets_file) -> str:
        """Short folder text telling same-named files apart: the containing folder's last
        two path segments (the top-level file's folder — a bundle's, for a nested entry)."""
        path = self.env.source_path_of(assets_file) if getattr(self, "env", None) is not None else None
        if not path:
            return "?"
        parts = os.path.normpath(os.path.dirname(path)).split(os.sep)
        return os.sep.join(parts[-2:])

    def open_scene_viewer(self, highlight_obj=None):
        """Тools -> "Просмотр сцены..." (generic open, highlight_obj=None) and
        the Preview panel's own "Просмотр сцены" button (GameObject-only,
        see preview_panel.py's scene_viewer_requested signal) both funnel
        through here. highlight_obj, when given, is the GameObject to select
        in the hierarchy once its file's tree is built — see
        SceneViewerDialog.highlight_object()."""
        if not self.raw_data_list:
            self.log(tr("Нет загруженных данных для просмотра сцены."), LogLevel.WARNING)
            return
        if self.scene_viewer_dialog is None:
            self.scene_viewer_dialog = SceneViewerDialog(self)
        files = self._build_source_assets_file_map()
        source_name = None
        if highlight_obj is not None and highlight_obj.assets_file is not None:
            source_name = self._scene_label_by_file_id.get(
                id(highlight_obj.assets_file), highlight_obj.assets_file.name)
        # Opened for a GameObject: only its file is shown (built), not first the one shown last time.
        self.scene_viewer_dialog.set_available_files(files, select=source_name)
        if source_name:
            self.scene_viewer_dialog.highlight_object(source_name, highlight_obj.path_id)
        self.scene_viewer_dialog.show()
        self.scene_viewer_dialog.raise_()
        self.scene_viewer_dialog.activateWindow()

    def clear_platform_cache(self):
        """Настройки → «Очистить кэш распакованных APK...»: data unpacked from an APK/OBB is a
        cache (core/platform_sources.py) — bounded automatically, but this frees it on demand.
        The copy currently loaded is skipped (its files are open)."""
        from core import platform_sources as ps
        entries = ps.list_cache()
        if not entries:
            QMessageBox.information(self, tr("Кэш APK"), tr("Кэш пуст."))
            return
        in_use = getattr(getattr(self, "env", None), "source_data_dir", "")
        total = sum(e.size for e in entries)
        reply = QMessageBox.question(
            self, tr("Очистить кэш APK"),
            tr("Распакованных копий: {count}, занято {size} МБ.\n"
               "Они будут распакованы заново при следующей загрузке APK.",
               count=len(entries), size=f"{total / 1024 ** 2:,.0f}")
            + ("\n" + tr("Загруженная сейчас копия останется до следующей загрузки.") if in_use else "")
            + "\n\n" + tr("Очистить?"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        keep = [in_use] if in_use else []
        # data_dir is <cache>/<key>/assets/bin/Data; keep the whole <key> folder
        keep = [str(p) for k in keep for p in Path(k).parents if (p / ".complete").is_file()][:1]
        freed = ps.clear_cache(keep=keep)
        self.log(tr("Кэш APK очищен: освобождено {size} МБ.", size=f"{freed / 1024 ** 2:,.0f}"))

    def clear_il2cpp_cache(self):
        """Настройки → «Очистить кэш IL2CPP...» (user request): removes the prepared IL2CPP script DLLs
        (core/il2cpp_dummy.py). The set the loaded game reads its scripts with is kept."""
        from core import il2cpp_dummy
        entries = il2cpp_dummy.cache_entries()
        if not entries:
            QMessageBox.information(self, tr("Кэш IL2CPP"), tr("Кэш пуст."))
            return
        in_use = getattr(getattr(self, "env", None), "il2cpp_dummy_dir", None)
        reply = QMessageBox.question(
            self, tr("Очистить кэш IL2CPP"),
            tr("Подготовленных игр: {count}, занято {size} МБ.",
               count=len(entries), size=f"{il2cpp_dummy.cache_size() / 1024 ** 2:,.1f}")
            + ("\n" + tr("Файлы загруженной сейчас игры останутся.") if in_use else "")
            + "\n\n" + tr("Очистить?"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        freed = il2cpp_dummy.clear_cache(keep=[in_use] if in_use else [])
        self.log(tr("Кэш IL2CPP очищен: освобождено {size} МБ.", size=f"{freed / 1024 ** 2:,.1f}"))

    def open_version_writer(self):
        """Инструменты -> "Вшить версию Unity в файлы..." — see tools/version_writer_dialog.py.
        Modal and one-shot; independent of the loaded session (it edits files on disk)."""
        exec_and_dispose(VersionWriterDialog(self))

    def _il2cpp_fix_available(self) -> bool:
        """Whether «Исправить» next to the preview's IL2CPP warning would help: an IL2CPP game is loaded, this load
        does not already read scripts with prepared DLLs (never prepared, prepared for an older build of the game —
        a different cache key — or prepared after this load), and the game has no Managed folder of its own (that
        one wins over prepared DLLs, so preparing would change nothing)."""
        env = getattr(self, "env", None)
        if getattr(env, "il2cpp_inputs", None) is None or getattr(env, "il2cpp_dummy_dir", None) is not None:
            return False
        return not (CONFIG.managed_dir and os.path.isdir(CONFIG.managed_dir))

    def open_il2cpp_prepare(self):
        """«Исправить» next to the preview's IL2CPP warning (_il2cpp_fix_available) — see
        dialogs/il2cpp_prepare_dialog.py and core/il2cpp_dummy.py. Works on the loaded game (env.il2cpp_inputs,
        set by the loader) and switches it to the prepared DLLs in place — no reload (_after_il2cpp_switch)."""
        inputs = getattr(getattr(self, "env", None), "il2cpp_inputs", None)
        if inputs is None:
            return
        has_own_managed = bool(CONFIG.managed_dir) and os.path.isdir(CONFIG.managed_dir)
        in_use = getattr(self.env, "il2cpp_dummy_dir", None) is not None
        exec_and_dispose(Il2CppPrepareDialog(inputs, env=self.env, has_own_managed=has_own_managed, in_use=in_use,
                                             on_applied=self._after_il2cpp_switch, parent=self))

    def _after_il2cpp_switch(self) -> None:
        """The loaded game reads scripts with the prepared DLLs now: show the current object again (its data, the
        warning and «Исправить» are re-evaluated) and, in SDF view, rebuild the groups (TMP fonts are MonoBehaviours)."""
        obj = self.preview_panel._current_obj or self._last_previewed_obj
        if obj is not None:
            self._last_previewed_obj = obj
            self.preview_panel.request_preview(obj)
        if self.left_view_stack.currentIndex() == 1:
            self._refresh_sdf_groups()

    def open_addressables_resolver(self):
        """Настройки -> "Разрешить ссылки в соседних бандлах..." — the explicit,
        user-triggered fallback for when a folder-mode load's own free piggyback
        scan never ran (a single bundle loaded via "Load files", the exact
        reported scenario — see dialogs/addressables_resolver_dialog.py's own
        docstring). Modal, one-shot, not a stored singleton (unlike
        cab_browser_dialog/scene_viewer_dialog) — it has nothing to keep alive
        once closed."""
        if not self.raw_data_list:
            self.log(tr("Нет загруженных данных для разрешения ссылок."), LogLevel.WARNING)
            return
        dlg = AddressablesResolverDialog(self)
        exec_and_dispose(dlg)

    # (the log pane — log(), records from logging, folder links — lives in main_log_pane.py — LogPaneMixin)

    def _on_select_all_requested(self):
        """ObjectTableView.selectAll()'s replacement for Ctrl+A — see its
        docstring for why this never touches Qt's real selection model (it has
        already set self.table_view.select_all_active = True itself by the
        time this runs). get_visible_items() is a plain Python loop over the
        (possibly 250,000+) row data, not a Qt/PyQt call per row, so this
        stays fast at exactly the scale where the real selectAll() wasn't.

        Deliberately just the preview panel — no status bar message: a real
        reported complaint was the status bar getting cluttered with a
        selection-count message on top of everything else it already shows."""
        items = self.proxy_model.get_visible_items()
        self.preview_panel.show_multi_selection(len(items))

    def on_selection_changed(self, selected, deselected):
        # A real selection change (a click, arrow-key nav, ...) always ends
        # virtual select-all — see _on_select_all_requested()'s docstring. Note
        # this also fires from ObjectTableView.selectAll()'s own
        # clearSelection() call, which runs BEFORE select_all_active is set
        # True there — so the reset below never stomps on it (see
        # ObjectTableView.selectAll()'s own docstring for the exact order).
        self.table_view.select_all_active = False
        # Listens for selectionChanged rather than currentChanged — a real
        # reported bug (right-clicking a table header, then clicking the
        # window's own title bar, could promote row 0 to currentIndex via Qt's
        # own focus-in handling, loading a preview no one asked for) needed a way
        # to tell a genuine selection apart from a spurious currentIndex-only
        # promotion. currentChanged fires for BOTH cases, so it can't be used to
        # tell them apart — but a first attempt at guarding it by checking
        # isSelected(current) INSIDE the currentChanged handler broke every real
        # click too: for an actual mouse click, currentChanged fires BEFORE the
        # click's selection is applied (isSelected() is still False at that
        # point — confirmed directly, not assumed), so that guard rejected
        # legitimate clicks as if they were the spurious case.
        # selectionChanged only ever fires when the selection set itself
        # actually changes — which the phantom focus-promotion case never does
        # (confirmed: a bare focus-in with no click fires neither signal) — and
        # for a real click/arrow-key-nav/programmatic setCurrentIndex(), it
        # fires AFTER the selection is applied (also confirmed), so
        # currentIndex() is already valid and selected by the time this runs.
        # Multi-row selection (see object_actions.py's _show_bulk_context_menu
        # for the export side of this): the preview area doesn't try to show
        # anything for 2+ selected rows — there's no single object to preview,
        # and reading N objects just because they got selected would be
        # unbounded, surprising work for something that might just be en route
        # to a multi-export.
        selected_rows = self.table_view.selectionModel().selectedRows()
        if selected_rows:
            self._forget_table_notice()     # a row is selected again: the notice was about an object without one
        if len(selected_rows) > 1:
            self._last_previewed_obj = None
            self.preview_panel.show_multi_selection(len(selected_rows))
            return

        current = self.table_view.selectionModel().currentIndex()
        if not current.isValid() or not self.table_view.selectionModel().isSelected(current):
            self._last_previewed_obj = None
            return
        source_index = self.proxy_model.mapToSource(current)
        item_data = self.table_model.data_list[source_index.row()]
        obj = item_data["obj_ref"]
        if obj is self._last_previewed_obj:
            # Real reported bug: applying Filters (or anything else that makes
            # the proxy model re-evaluate row visibility) can make Qt re-fire
            # selectionChanged for the SAME row that was already selected —
            # its proxy index just moved, the underlying object didn't change
            # at all. Re-running request_preview() for an object that's
            # already the current preview needlessly rebuilds the structure
            # tree from scratch (ObjectStructureTree.set_object() always
            # clears() first), collapsing whatever branches the user had
            # expanded for no reason. Doesn't affect the legitimate "refresh
            # after an in-place edit" call (object_actions._refresh_row_after_
            # patch's own request_preview() call) — that's a different call
            # site entirely, not routed through here.
            return
        self._last_previewed_obj = obj
        self.preview_panel.request_preview(obj)

    # (SDF Viewer Mode lives in main_sdf_view.py — SdfViewMixin)

    # (going to an object — jumps, dependency loading, quick jump — lives in main_navigation.py — NavigationMixin)

    def show_about_dialog(self):
        """Справка → "О программе..." — logo/name/version/short description,
        no state to collect first."""
        exec_and_dispose(AboutDialog(self))

    def show_sdf_help_dialog(self):
        """Справка → "Генерация SDF-шрифтов..." — read-only guide, see dialogs/sdf_help_dialog.py."""
        from dialogs.sdf_help_dialog import SDFHelpDialog
        exec_and_dispose(SDFHelpDialog(self))

def fast_exit(code: int, window=None) -> None:
    """End the process right after the window closed, skipping Python's interpreter finalization.

    With a big game loaded the table holds millions of row dicts and reader objects, and the interpreter
    spends the last seconds of the process freeing them one by one (Lego Party, 1.95M rows: close() returns
    in 0.06 s, the console then stays open another ~6.5 s — all of it finalization; every atexit handler
    is done within 0.1 s). Nothing in it is needed: the OS releases memory, mappings and handles.

    What finalization would still have done is done here first, explicitly and selectively: the one
    long-lived QSettings is synced, crash_log's "clean exit" marker is written and logging is shut down.

    The atexit handlers are deliberately NOT run (an earlier version called atexit._run_exitfuncs()): that
    also runs PyQt's own teardown (sip's `_sip_exit`, Qt's `_qtcore_cleanup`) while windows, media players
    and worker threads are still alive, and in real sessions that crashed with an access violation inside
    fast_exit (crash.log, three times in one afternoon) — a crash on exit is worse than the slow exit it was
    meant to avoid, and which objects are alive at that moment decides whether it happens.
    USTUDIO_CLEAN_EXIT=1 keeps the normal slow exit (leak hunting, tools that need finalizers to run)."""
    if os.environ.get("USTUDIO_CLEAN_EXIT") == "1":
        return
    try:
        if window is not None:
            window.settings.sync()
    except Exception:
        pass
    try:
        crash_log.mark_clean_exit()
    except Exception:
        pass
    try:
        logging.shutdown()
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except Exception:
            pass
    os._exit(code)


if __name__ == "__main__":
    # Windows groups taskbar buttons/resolves the taskbar icon by the process's
    # "Application User Model ID", not just by window icon or exe-file icon. A
    # frozen Python app that never sets one gets left on Python's own default
    # AppID (or none at all under Nuitka), which is why the taskbar button can
    # show a generic/blank icon even though the exe's own file icon (Explorer)
    # and the in-app title bar icon (app.setWindowIcon below) are both correct —
    # this is a well-documented Windows quirk for frozen PyQt/PySide apps, not a
    # code bug in icon rendering itself. Must be set before the first window is
    # created (here, before QApplication) for Windows to pick it up reliably.
    # Harmless/no-op on non-Windows, hence the platform guard.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Ambigram.UStudio.AssetBrowser.1"
            )
        except (AttributeError, OSError):
            pass

    # Crash logging — see crash_log.py's docstring. Replaces the earlier bare
    # faulthandler.enable(): that only ever caught a few native fault kinds, wrote no
    # date, and recorded NOTHING for the most common real crash (an uncaught Python
    # exception in a Qt slot, which PyQt6 turns into qFatal() -> exit code
    # 0xc0000409 unless a sys.excepthook is installed). Installed before anything
    # else so startup failures are covered too.
    crash_log.install()

    # Colored console output (via rich), alongside the GUI log panel — same log
    # records, same source (logging.getLogger("ustudio...")), just a second
    # destination. A no-op if there's no attached console to write to (e.g. a
    # --windowed build launched without one) — see configure_console_logging()'s
    # docstring.
    configure_console_logging()

    # At fractional Windows scaling factors (125%/150%/175% — the typical
    # "small screen + increased scaling in Windows settings for
    # readability" case), the default DPI rounding policy (Round) can give a window
    # sized exactly to screen().availableGeometry() (see _fit_to_screen)
    # a physical size 1-2px LARGER than the screen itself — because Qt rounds logical
    # and physical coordinates in separate steps, and at a fractional factor these
    # roundings don't always agree. PassThrough uses the scale factor as-is, without
    # additional rounding, and eliminates exactly this source of desync.
    # Must be set BEFORE creating QApplication.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon.get_app_icon())
    # Applied BEFORE MainWindow is constructed so every widget is built under the right
    # palette from the start (a widget can inherit a palette set before or after its own
    # construction, but applying it first avoids any window of mismatched colors during
    # startup). See theme.py's module docstring for why this exists as an explicit,
    # curated pair of palettes rather than relying on Qt/Windows theme auto-detection.
    theme.apply_theme(app, theme.load_saved_theme_name())
    # The language of every text (saved in Настройки -> Язык), before any window is built.
    app_language.install(app)
    # One copy at a time — see single_instance.py. A second launch brings the running
    # window to the front and exits before building anything.
    single_instance = SingleInstance()
    if not single_instance.acquire():
        sys.exit(0)
    window = MainWindow()

    def _bring_to_front():
        window.setWindowState((window.windowState() & ~Qt.WindowState.WindowMinimized)
                              | Qt.WindowState.WindowActive)
        window.show()
        window.raise_()
        window.activateWindow()

    single_instance.activation_requested.connect(_bring_to_front)
    # Maximized (not showFullScreen()) — keeps the title bar/close button and the
    # taskbar visible, just uses the whole work area. This sidesteps the small-screen
    # overflow problem entirely (the OS handles the sizing), while still leaving a
    # sane restored geometry from _fit_to_screen() for when the user un-maximizes.
    window.showMaximized()
    exit_code = app.exec()
    fast_exit(exit_code, window)
    sys.exit(exit_code)  # only reached with USTUDIO_CLEAN_EXIT=1