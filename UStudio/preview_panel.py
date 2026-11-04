"""The object-preview panel: a self-contained widget (Preview / Dump tabs, a
structure-tree sidebar next to the Preview tab, and a compact one-line metadata
strip under the preview widget itself) that owns the background-threaded,
generation-guarded read pipeline described in core/object_preview.py. Split out
of MainWindow — MainWindow's only touchpoints are request_preview(obj),
show_welcome(), apply_theme_colors(), and cleanup()."""

from core.i18n import N_, tr
import html

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QFontMetricsF, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter, QStackedWidget,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

import preview_icons
import theme as _theme
from config import CONFIG
from gui_workers import BackgroundWorker
from gui_widgets import (
    AudioPreviewWidget, CompactSummaryBar, FontPreviewWidget, ImagePreviewWidget,
    ObjectStructureTree, TextFindBar, TextureZoomDialog, VideoPreviewWidget, pil_to_qpixmap,
)
from helpers import JsonHighlighter, TypedDumpHighlighter, mono_font as _mono_font, wrap_tooltip
from gui_common import AdaptiveRow
from type_icons import get_action_icon
from core.object_metadata import build_compact_summary
from core.object_preview import (
    PreviewResult, build_preview, build_sprite_region_image, resolve_object_name,
)
from app_settings import app_settings
from details_view import ObjectDetailsView

# A read-size mismatch ("Expected to read N bytes, but only read M bytes", see
# TypeTreeHelper.py's check_read) for an IL2CPP game usually means the generator
# loaded without error but still produced a wrong/incomplete TypeTree for this
# particular script — see EnvironmentLoader._warn_if_il2cpp() for the fuller
# explanation. Shown in preview_warning_label (only known here, not in
# core/object_preview.py, since CONFIG.is_il2cpp is GUI-session state) — a
# standalone banner now, not text appended after something else, hence no
# leading "\n\n"/"Примечание:" of its own.
# Next to it, the «Исправить» button (btn_il2cpp_fix) when preparing the game's scripts would help.
_IL2CPP_HINT = N_("Не удалось правильно прочитать структуру скрипта — это частое ограничение для игр на IL2CPP.")

# Debounces how often a selection change actually starts a background read —
# during fast arrow-key/scroll navigation, only the LAST selection within this
# window triggers a read, not every intermediate one.
_SELECTION_DEBOUNCE_MS = 150

# How long a read has to still be running before the "Загрузка..." placeholder
# actually appears — the common case (a small/fast object) finishes well within
# this window and the placeholder never flashes on screen at all.
_LOADING_PLACEHOLDER_DELAY_MS = 200

def _welcome_html() -> str:
    return (f'<div style="text-align:center; color:gray;"><h2>{html.escape(tr("Объект не выбран"))}</h2>'
            f'<p>{html.escape(tr("Выберите объект в таблице слева, чтобы увидеть предпросмотр."))}</p>'
            f'<p>{html.escape(tr("Двойной щелчок — отредактировать."))}<br>'
            f'{html.escape(tr("Правая кнопка мыши — открыть список действий."))}</p></div>')

# Shown instead of _WELCOME_HTML when nothing has been loaded yet at all — telling
# the user to "select an object" is misleading when there's no game loaded for an
# object to even come from; this points at the actual next step instead.
def _no_game_html() -> str:
    return (f'<div style="text-align:center; color:gray;"><h2>{html.escape(tr("Игра не загружена"))}</h2>'
            f'<p>{html.escape(tr("Откройте файлы игры через меню «Файл», чтобы начать работу."))}</p></div>')

# Shown instead of _WELCOME_HTML for a 2+ row selection — see show_multi_selection().
def _multi_selection_html(count: int) -> str:
    return (f'<div style="text-align:center; color:gray;"><h2>{html.escape(tr("Выбрано объектов: {count}", count=count))}</h2>'
            f'<p>{html.escape(tr("Предпросмотр недоступен для нескольких объектов. Вызовите контекстное меню правой "
                            "кнопкой мыши, чтобы экспортировать все выбранные объекты."))}</p></div>')


class PreviewPanel(QWidget):
    # Emitted for a jump from the «Сведения» tab's «Ссылается на» list OR "Перейти
    # к объекту" on a structure-tree PPtr row's context menu — both just an
    # ObjectReader. MainWindow listens and selects that row in the main table
    # (see main.py's _jump_to_object). PreviewPanel doesn't touch the table
    # itself, matching its existing decoupling from MainWindow.
    jump_to_object_requested = pyqtSignal(object)
    # Emitted from a structure-tree PPtr row's "Отредактировать данные" —
    # PreviewPanel doesn't know how to open the edit dialog itself (that's
    # object_actions.py's job); MainWindow bridges the two.
    edit_object_requested = pyqtSignal(object)
    # «Сведения» tab's Экспорт / Импорт buttons (the shown object) — MainWindow bridges them like the edit above.
    export_object_requested = pyqtSignal(object)
    export_menu_requested = pyqtSignal(object, object)     # the shown object, QPoint: «Экспорт ▾» formats menu
    import_object_requested = pyqtSignal(object)
    # "Просмотр сцены" button (GameObject preview only, see its own visibility
    # toggle in _on_preview_ready) — PreviewPanel doesn't know how to open the
    # Scene Viewer itself (that dialog lives in dialogs/, constructed and
    # owned by MainWindow, same as CabBrowserDialog/TextSearchDialog); carries
    # the GameObject to highlight once it's open.
    scene_viewer_requested = pyqtSignal(object)
    # «Исправить» next to the IL2CPP banner (_IL2CPP_HINT): MainWindow opens the IL2CPP preparation dialog.
    il2cpp_prepare_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Background object-preview read — a monotonically increasing counter, not
        # a boolean flag: every new request_preview() call bumps it and captures the
        # new value as its "generation", so should_cancel (passed into
        # core.object_preview.build_preview) and the succeeded/failed handlers below
        # can both tell a superseded read apart from the current one, even if
        # several selections happen in quick succession before any of their reads
        # finish.
        self._preview_generation = 0
        self._preview_worker = None
        self._result_pending = False  # True while the CURRENT generation's read is
        # still in flight — distinct from the generation check itself, which only
        # tells a stale read apart from a current one, not whether the current
        # one has already finished (see _maybe_show_loading_placeholder).

        self._pending_obj = None
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.timeout.connect(self._start_preview_worker)

        self._current_image_pixmap = None
        self._current_title = ""
        self._current_obj = None  # the ObjectReader the CURRENT preview is for —
        # needed by the Sprite-only "На текстуре" button, which acts
        # on the selected Sprite itself rather than on the already-decoded result.
        self._sprite_title = None    # saved title/summary to restore when
        self._sprite_summary = ""    # "На текстуре" is toggled back off.
        # The game's «Используется в» index (usage_index_runner.UsageIndexRunner), set by MainWindow after a load;
        # None: no index (that section of «Сведения» stays hidden).
        self.usage_runner = None
        # «Контуры спрайтов» (core/sprite_outlines.py): the Texture2D shown (None for anything else), the outlines
        # read for it (texture, [SpriteOutline]) and the background read (generation-checked like the preview's).
        self._outline_texture = None
        self._outline_result = None
        self._outline_generation = 0
        self._outline_worker = None
        self._jump_back_stack = []      # the objects a chain of jumps was made FROM, oldest first («← Назад» pops)
        self._pending_jump_source = None  # FROM, set right before emitting jump_to_object_requested — see
                                           # _jump_from_tree()/_navigate_back()'s docstrings.
        self._pending_back_target = None  # the object «← Назад» is on its way to (popped off the stack already)

        self._build_ui()
        self.show_welcome(game_loaded=False)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        tabs = self.tabs = QTabWidget()
        outer.addWidget(tabs)

        # --- Tab 1: preview (left) + metadata/structure sidebar (right) ---
        tab1_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.preview_stack = QStackedWidget()
        (
            self.PREVIEW_WELCOME, self.PREVIEW_IMAGE, self.PREVIEW_AUDIO, self.PREVIEW_VIDEO,
            self.PREVIEW_TEXT, self.PREVIEW_FONT, self.PREVIEW_INFO, self.PREVIEW_MESH,
        ) = range(8)

        # A QLabel inside a stretch-padded QVBoxLayout, not a QTextEdit — QTextEdit
        # has no way to center its content vertically within the viewport (only
        # horizontally, via CSS text-align), so the placeholder ended up pinned to
        # the top no matter what margin was applied to the HTML.
        welcome_page = QWidget()
        welcome_layout = QVBoxLayout(welcome_page)
        welcome_layout.addStretch(1)
        self.welcome_label = QLabel(_no_game_html())
        self.welcome_label.setTextFormat(Qt.TextFormat.RichText)
        # Real reported bug: without word wrap, a QLabel's rich-text sizeHint()
        # is based on the UNWRAPPED single-line width of its content — the two
        # original messages (_WELCOME_HTML/_NO_GAME_HTML) were short enough
        # that this never visibly mattered, but show_multi_selection()'s
        # longer message (two full sentences) was wide enough unwrapped to
        # force this label — and with it the splitter it sits in — wider,
        # visibly shifting the splitter open on a multi-row selection.
        self.welcome_label.setWordWrap(True)
        welcome_layout.addWidget(self.welcome_label, 0, Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addStretch(1)
        self.preview_stack.addWidget(welcome_page)

        self.image_preview = ImagePreviewWidget()
        self.image_preview.set_free_pan(True)  # the texture can be dragged even when it fits
        image_page = QWidget()
        image_layout = QVBoxLayout(image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)
        image_toolbar = QHBoxLayout()
        btn_stretch = QPushButton(tr("Растянуть"))
        btn_stretch.clicked.connect(lambda: self.image_preview.fit_in_view())
        btn_actual = QPushButton("1:1")
        btn_actual.clicked.connect(lambda: self.image_preview.zoom_actual_size())
        # Real reported request: emoji glyphs (tried right after the earlier
        # plain-text/Unicode-symbol labels) didn't suit these buttons well
        # either and render inconsistently across fonts/OSes — replaced with
        # procedurally-drawn icons (preview_icons.py, same "colored chip +
        # white glyph" style as the main table's own type_icons.py) that
        # actually depict what each button does; full description stays in
        # each one's tooltip.
        btn_popup = QPushButton()
        btn_popup.setIcon(preview_icons.get_zoom_icon())
        btn_popup.setIconSize(QSize(22, 22))
        btn_popup.setToolTip(tr("Открыть в отдельном окне (или двойной клик по изображению)"))
        btn_popup.setFixedSize(40, 32)
        btn_popup.clicked.connect(self._open_texture_zoom)
        # Cycles the checkerboard/white/gray/black backdrop — a single small,
        # always-in-the-same-place button rather than a dropdown, so it stays easy
        # to find/remember by muscle memory.
        self._btn_bg = QPushButton()
        self._btn_bg.setIcon(preview_icons.get_background_cycle_icon())
        self._btn_bg.setIconSize(QSize(22, 22))
        self._btn_bg.setFixedSize(40, 32)
        self._btn_bg.clicked.connect(self._cycle_image_background)
        # NoFocus on every plain click-trigger button in this panel (see the same
        # treatment below for the sprite/tree buttons and gui_widgets.py's
        # AudioPreviewWidget controls): a QPushButton/QToolButton defaults to
        # StrongFocus, so clicking one moved keyboard focus onto the button itself
        # — meaning Up/Down afterwards stopped navigating the main table (whatever
        # had focus before) until the user clicked a row again. None of these
        # buttons need keyboard focus of their own (no Tab-cycling through them is
        # expected here), so NoFocus lets a click just click, leaving focus — and
        # arrow-key table navigation — wherever it already was.
        for _btn in (btn_stretch, btn_actual, btn_popup, self._btn_bg):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._update_bg_button_tooltip("checker")

        # R/G/B channel isolation (AssetStudio-style) — mouse-clickable
        # counterpart to the image_preview widget's own R/G/B keyboard toggle
        # (see gui_widgets.ImagePreviewWidget.keyPressEvent's own comment for
        # why those are plain, unmodified keys rather than Ctrl+R/G/B: Ctrl+G
        # already opens the main window's Quick Jump dialog window-wide, and
        # binding Ctrl+G here too would make Qt treat the two as an ambiguous
        # shortcut whenever the image widget has focus). This is the RELIABLE
        # path — always clickable regardless of which widget currently has
        # keyboard focus (the keyboard shortcut only fires once the image
        # view itself is focused, e.g. after a click into it).
        #
        # Real reported bug: a first version used setFixedSize(26, 32) — the
        # app's global QSS gives every QPushButton 14px of horizontal padding
        # per side (28px total), which alone exceeds a 26px-wide button, so
        # there was no room left to actually paint the letter — the buttons
        # rendered as blank rectangles. Every OTHER small fixed-size button in
        # this toolbar sidesteps this by using an icon instead of text (see
        # preview_icons.py) — these are the first plain-text ones, so this
        # padding/width interaction had never come up before. Fixed by only
        # constraining height, letting width follow the QSS-padded sizeHint
        # like an ordinary QPushButton would.
        self._channel_buttons = []
        for index, (letter, tip) in enumerate(
            (("R", tr("Красный")), ("G", tr("Зелёный")), ("B", tr("Синий")))
        ):
            btn = QPushButton(letter)
            btn.setObjectName(f"ChannelButton{letter}")
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFixedHeight(32)
            btn.setToolTip(tr("Канал {letter} ({color}) — клавиша {letter} при фокусе на изображении",
                              letter=letter, color=tip))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.toggled.connect(lambda checked, i=index: self._on_channel_button_toggled(i, checked))
            self._channel_buttons.append(btn)
        self.image_preview.channelsChanged.connect(self._on_channels_changed)
        # Colors literal/fixed rather than theme-derived on purpose — R=red/
        # G=green/B=blue is a universal convention this button row exists to
        # invoke, not something a theme swap should reinterpret. Only the
        # OFF-state (unchecked) color below comes from the theme, so a
        # disabled channel still reads as "muted" consistently with the rest
        # of the app in both light and dark.
        self._channel_accent_colors = {"R": "#e5534b", "G": "#3fb950", "B": "#4a90e2"}
        self._style_channel_buttons(_theme.get_colors(_theme.load_saved_theme_name()))

        # Texture2DArray-only: step through the array's decoded slices (already
        # all decoded up front by build_preview() — see PreviewResult.array_images'
        # own docstring — so this is just indexing into an existing list, no
        # re-decode per click). Real reported bug: a first version used plain
        # QPushButton("<")/(">") text at a small fixed size — the app's own
        # QPushButton QSS padding left basically no room for the glyph at that
        # size, rendering as blank buttons. Icon-based (same preview_icons.py
        # convention — and size/style — as btn_bg/btn_popup right above, which
        # already render correctly) instead of relying on button text at all.
        # Also its own dedicated ROW (not crammed into the already-busy main
        # toolbar) per the same report, centered below it — shown/hidden as
        # one unit via this row widget rather than three separate calls.
        self._array_nav_row_widget = QWidget()
        array_nav_row = QHBoxLayout(self._array_nav_row_widget)
        array_nav_row.setContentsMargins(0, 4, 0, 4)
        array_nav_row.addStretch(1)
        self._btn_array_prev = QPushButton()
        self._btn_array_prev.setIcon(preview_icons.get_array_prev_icon())
        self._btn_array_prev.setIconSize(QSize(22, 22))
        self._btn_array_prev.setFixedSize(40, 32)
        self._btn_array_prev.setToolTip(tr("Предыдущий слой текстуры"))
        self._btn_array_prev.clicked.connect(self._on_array_prev)
        self._btn_array_prev.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        array_nav_row.addWidget(self._btn_array_prev)
        self._array_index_label = QLabel("")
        self._array_index_label.setObjectName("MutedCaption")
        self._array_index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._array_index_label.setMinimumWidth(56)
        array_nav_row.addWidget(self._array_index_label)
        self._btn_array_next = QPushButton()
        self._btn_array_next.setIcon(preview_icons.get_array_next_icon())
        self._btn_array_next.setIconSize(QSize(22, 22))
        self._btn_array_next.setFixedSize(40, 32)
        self._btn_array_next.setToolTip(tr("Следующий слой текстуры"))
        self._btn_array_next.clicked.connect(self._on_array_next)
        self._btn_array_next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        array_nav_row.addWidget(self._btn_array_next)
        array_nav_row.addStretch(1)
        self._array_nav_row_widget.hide()
        self._array_images = None  # Texture2DArray's full decoded slice list, or None
        self._array_index = 0

        # Sprite-only: toggle showing the full texture with the sprite's region outlined instead of just the
        # cropped sprite (hidden for every other type; set visible in _on_preview_ready). The jump to that texture
        # is in the «Сведения» tab («Ссылается на»), with every other reference.
        self._btn_sprite_region = QPushButton()
        self._btn_sprite_region.setIcon(preview_icons.get_sprite_region_icon())
        self._btn_sprite_region.setIconSize(QSize(22, 22))
        self._btn_sprite_region.setFixedSize(40, 32)
        self._btn_sprite_region.setToolTip(tr("Показать область спрайта на полной текстуре"))
        self._btn_sprite_region.setCheckable(True)
        self._btn_sprite_region.toggled.connect(self._toggle_sprite_region)
        self._btn_sprite_region.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_sprite_region.hide()
        # Texture2D with sprites only (_update_sprite_outlines): the areas its sprites take their pictures from,
        # drawn over it; hover = the sprite's name, double-click = go to that sprite.
        self.chk_sprite_outlines = QCheckBox(tr("Контуры спрайтов"))
        self.chk_sprite_outlines.setChecked(app_settings().value("preview/sprite_outlines", False, type=bool))
        self.chk_sprite_outlines.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_sprite_outlines.toggled.connect(self._on_sprite_outlines_toggled)
        self.chk_sprite_outlines.hide()
        self.image_preview.outlineActivated.connect(self._jump_from_tree)
        image_toolbar.addWidget(btn_stretch)
        image_toolbar.addWidget(btn_actual)
        image_toolbar.addWidget(self._btn_bg)
        for btn in self._channel_buttons:
            image_toolbar.addWidget(btn)
        image_toolbar.addWidget(self._btn_sprite_region)
        image_toolbar.addSpacing(6)
        image_toolbar.addWidget(self.chk_sprite_outlines)
        image_toolbar.addStretch(1)
        image_toolbar.addWidget(btn_popup)
        image_layout.addLayout(image_toolbar)
        image_layout.addWidget(self._array_nav_row_widget)
        image_layout.addWidget(self.image_preview, 1)
        self.preview_stack.addWidget(image_page)
        # Faster path to the same fullscreen view as the zoom/popup button.
        self.image_preview.doubleClicked.connect(self._open_texture_zoom)

        self.audio_preview = AudioPreviewWidget()
        self.preview_stack.addWidget(self.audio_preview)

        self.video_preview = VideoPreviewWidget()
        self.preview_stack.addWidget(self.video_preview)

        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        self.chk_word_wrap = QCheckBox(tr("Перенос строк"))
        # Remembered across restarts (own QSettings group, same store theme.py/
        # config.py/FontPreviewWidget's custom-text already use) — a plain
        # per-session default would reset to NoWrap every launch, which is what
        # this checkbox exists to stop happening for a long TextAsset/binary hex
        # dump/JSON fallback the user keeps re-enabling wrap for.
        wrap_on = app_settings().value("text_preview/word_wrap", False, type=bool)
        self.chk_word_wrap.setChecked(wrap_on)
        self.chk_word_wrap.toggled.connect(self._on_word_wrap_toggled)
        text_layout.addWidget(self.chk_word_wrap)

        self.txt_preview = QTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setFont(_mono_font())
        self.txt_preview.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth if wrap_on else QTextEdit.LineWrapMode.NoWrap
        )
        # Highlights this tab whenever it's showing kind="json" content (the
        # no-rich-preview fallback for MonoBehaviour/GameObject/...) — a harmless
        # no-op on the plain TextAsset/Shader source text it also displays for
        # kind="text", since JSON syntax rarely appears by coincidence there.
        self.json_highlighter = JsonHighlighter(self.txt_preview.document())
        self.find_bar_preview = TextFindBar(self.txt_preview)
        text_layout.addWidget(self.find_bar_preview)
        text_layout.addWidget(self.txt_preview, 1)
        self.preview_stack.addWidget(text_page)

        self.font_preview = FontPreviewWidget()
        self.preview_stack.addWidget(self.font_preview)

        self.txt_info = QTextEdit()
        self.txt_info.setReadOnly(True)
        self.txt_info.setFont(_mono_font())
        self.preview_stack.addWidget(self.txt_info)

        # The 3D view of a Mesh (mesh_view.py). Created the first time a mesh is shown: an OpenGL context is
        # not worth making at startup for something many sessions never open.
        self._mesh_page = QWidget()
        self._mesh_page_layout = QVBoxLayout(self._mesh_page)
        self._mesh_page_layout.setContentsMargins(0, 0, 0, 0)
        self._mesh_view = None
        self.preview_stack.addWidget(self._mesh_page)

        # Compact one-line summary strip under the preview widget (dimensions/
        # format/etc., English, terse) — replaces the old side-panel MetadataPanel,
        # modeled after UABEA's own texture preview (a slim caption row directly
        # below the image rather than a whole separate panel).
        preview_container = QWidget()
        preview_container_layout = QVBoxLayout(preview_container)
        preview_container_layout.setContentsMargins(0, 0, 0, 0)
        preview_container_layout.setSpacing(0)

        # Real reported bug: this used to live inside image_toolbar, part of
        # ONLY the "image" kind's own stack page — _on_preview_ready() always
        # set it visible=True correctly regardless of what kind the jump
        # landed on (its own intent, see the comment that used to sit here:
        # "not tied to the current object's own type... any PPtr target, not
        # necessarily a Sprite's texture"), but a jump to anything other than
        # an image-kind object (a Material, GameObject, MonoBehaviour, ...)
        # switches preview_stack to a DIFFERENT page, so the button — however
        # "visible" it thought it was — was never actually on screen. Placed
        # here instead, in its own toolbar ABOVE preview_stack, so it stays
        # visible no matter which kind's page ends up showing. A QPushButton
        # that's .hide()'d still costs zero layout height when not needed, so
        # this adds no space back when there's nothing to go back to.
        back_toolbar = QHBoxLayout()
        # Real reported issue: no top margin meant this row (and, once it was
        # added, the "Просмотр сцены" button in it) sat flush against the tab
        # bar right above it with zero breathing room.
        back_toolbar.setContentsMargins(0, 4, 0, 4)
        self._btn_jump_back = QPushButton(tr("← Назад"))
        self._btn_jump_back.setToolTip(tr("Вернуться к объекту, из которого был выполнен переход"))
        self._btn_jump_back.clicked.connect(self._navigate_back)
        self._btn_jump_back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_jump_back.hide()
        back_toolbar.addWidget(self._btn_jump_back)
        # GameObject-only (see its own visibility toggle in _on_preview_ready's
        # "json" branch — GameObject has no dedicated preview of its own, so it
        # renders through the same page as MonoBehaviour/Material/... and
        # shares that page's "Перенос строк" checkbox) — real request: a quick
        # way from a previewed GameObject straight into the Scene Viewer's
        # hierarchy, placed here (above preview_stack, same as _btn_jump_back)
        # specifically so it sits above EVERY stacked page's own content
        # rather than living inside just one page the way the Sprite-only
        # buttons do. Added BEFORE the stretch below (real reported bug: a
        # first version added it after, which pushed it to the far right of
        # the row instead of sitting left-aligned next to _btn_jump_back).
        self._btn_scene_viewer = QPushButton(tr("Просмотр на сцене"))
        self._btn_scene_viewer.setToolTip(tr("Отобразить этот объект на сцене в иерархии GameObject"))
        self._btn_scene_viewer.clicked.connect(
            lambda: self.scene_viewer_requested.emit(self._current_obj)
        )
        self._btn_scene_viewer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_scene_viewer.hide()
        back_toolbar.addWidget(self._btn_scene_viewer)
        back_toolbar.addStretch(1)
        preview_container_layout.addLayout(back_toolbar)

        # Shared "something is wrong with THIS preview, here's why" banner —
        # two distinct triggers, never both at once (see _on_preview_ready):
        # (1) core.object_preview.check_resource_reference() flags the
        # selected object's external resource reference as broken (resolved
        # to the wrong physical file, out of bounds, or missing entirely) —
        # without this, a garbage image/audio/mesh preview reads to the user
        # as "this object's data is corrupted", when the object was never
        # touched, its resource REFERENCE just resolved to the wrong file;
        # (2) the object's own Dump failed to parse AND the game is IL2CPP —
        # previously a paragraph of advice appended inline to the Dump tab's
        # error text (easy to miss, and read as a per-object quirk rather
        # than a whole-game caveat); moved here to make it a prominent,
        # global-feeling warning instead, matching a real request. Plain
        # inline styling (not a theme color token): this is a rare,
        # deliberately attention-grabbing state, not part of the normal
        # light/dark palette.
        # One orange block: the warning text and, inside it on the right, «Исправить» (user request — a separate
        # button next to the bar looked odd). The frame is what shows/hides (_update_warning / _hide_warning).
        self.preview_warning_frame = QFrame()
        self.preview_warning_frame.setObjectName("PreviewWarning")
        self.preview_warning_frame.setStyleSheet(
            "QFrame#PreviewWarning { background-color: #7a4a00; border-radius: 3px; }"
            "QFrame#PreviewWarning QLabel { color: #ffe4b0; background: transparent; }"
            "QFrame#PreviewWarning QPushButton { background-color: #ffe4b0; color: #4a2c00; border: none;"
            " border-radius: 3px; padding: 4px 12px; }"
            "QFrame#PreviewWarning QPushButton:hover { background-color: #fff2d6; }"
        )
        warning_row = QHBoxLayout(self.preview_warning_frame)
        warning_row.setContentsMargins(10, 6, 18, 6)       # «Исправить» not glued to the right edge (user request)
        self.preview_warning_label = QLabel()
        self.preview_warning_label.setWordWrap(True)
        self.preview_warning_label.setTextFormat(Qt.TextFormat.RichText)   # texts are html-escaped where shown
        warning_row.addWidget(self.preview_warning_label, 1)
        # «Исправить»: shown with the IL2CPP warning only when preparing the game's scripts would help — MainWindow
        # answers that through `il2cpp_fix_available` (not prepared yet, prepared for an older build of the game, or
        # prepared but not used by this load; not when this load already uses them or the game has its own Managed).
        self.btn_il2cpp_fix = QPushButton(tr("Исправить"))
        self.btn_il2cpp_fix.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_il2cpp_fix.setCursor(Qt.CursorShape.PointingHandCursor)   # it reads as a link-like action
        self.btn_il2cpp_fix.clicked.connect(self.il2cpp_prepare_requested.emit)
        self.btn_il2cpp_fix.hide()
        warning_row.addWidget(self.btn_il2cpp_fix, 0, Qt.AlignmentFlag.AlignVCenter)
        self.il2cpp_fix_available = lambda: False
        self.preview_warning_frame.hide()
        preview_container_layout.addWidget(self.preview_warning_frame)

        preview_container_layout.addWidget(self.preview_stack, 1)
        # Wraps (centred, between parts) instead of widening the pane — see CompactSummaryBar.
        self.compact_summary_label = CompactSummaryBar()
        preview_container_layout.addWidget(self.compact_summary_label)
        self.preview_container = preview_container
        tab1_splitter.addWidget(preview_container)

        self.tab1_splitter = tab1_splitter
        tree_page = self.tree_page = QWidget()
        tree_layout = QVBoxLayout(tree_page)
        tree_layout.setContentsMargins(0, 8, 0, 0)     # air under the «Дерево»/«Сведения» tab bar (user request)
        # icon-only buttons and a shorter checkbox caption when the panel is too narrow (gui_common.AdaptiveRow)
        self.tree_toolbar = AdaptiveRow()
        tree_toolbar = self.tree_toolbar.row
        tree_toolbar.setContentsMargins(0, 0, 0, 0)
        # a space before the text: Qt puts the icon right against it (as «Сведения»'s buttons)
        btn_expand_all = self.btn_expand_all = QPushButton(get_action_icon("expand"), " " + tr("Развернуть всё"))
        btn_expand_all.setToolTip(wrap_tooltip(
            tr("Развернуть всё: все ветки, кроме ссылок на другие объекты — их разворачивание загружает эти объекты.")
        ))
        self.structure_tree = ObjectStructureTree()
        self.structure_tree.jump_requested.connect(self._jump_from_tree)
        self.structure_tree.edit_requested.connect(self.edit_object_requested.emit)
        btn_expand_all.clicked.connect(self.structure_tree.expand_all_branches)
        btn_collapse_all = self.btn_collapse_all = QPushButton(get_action_icon("collapse"), " " + tr("Свернуть всё"))
        btn_collapse_all.setToolTip(wrap_tooltip(tr("Свернуть всё")))
        btn_collapse_all.clicked.connect(self.structure_tree.collapse_all_branches)
        # See the image-toolbar buttons above for why: NoFocus so clicking these
        # doesn't steal keyboard focus (and with it, Up/Down table navigation)
        # away from wherever it already was.
        btn_expand_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_collapse_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tree_toolbar.addWidget(btn_expand_all)
        tree_toolbar.addWidget(btn_collapse_all)
        tree_toolbar.addStretch(1)
        # Optional wrapping of long lines; remembered across restarts like the text preview's own
        # «Перенос строк» (separate key: the two views are wrapped independently).
        self.chk_tree_word_wrap = QCheckBox(tr("Перенос строк"))
        self.chk_tree_word_wrap.setToolTip(wrap_tooltip(
            tr("Длинные строки дерева переносятся по ширине панели, без горизонтальной прокрутки.")))
        self.chk_tree_word_wrap.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # same reason as the buttons
        tree_wrap_on = app_settings().value("tree_view/word_wrap", False, type=bool)
        self.chk_tree_word_wrap.setChecked(tree_wrap_on)
        self.structure_tree.set_word_wrap(tree_wrap_on)
        self.chk_tree_word_wrap.toggled.connect(self._on_tree_word_wrap_toggled)
        tree_toolbar.addWidget(self.chk_tree_word_wrap)
        self.tree_toolbar.add_adaptive(btn_expand_all, "")
        self.tree_toolbar.add_adaptive(btn_collapse_all, "")
        # «Перенос строк» keeps its whole text in a narrow row too (user request: «Перенос» read badly).
        tree_layout.addWidget(self.tree_toolbar)
        tree_layout.addWidget(self.structure_tree, 1)
        # The right half: «Дерево» (above) and «Сведения» (facts + what the object refers to; details_view.py).
        # The last tab used is remembered.
        self.details_view = ObjectDetailsView()
        self.details_view.jump_requested.connect(self._jump_from_tree)
        self.details_view.edit_target_requested.connect(self.edit_object_requested.emit)   # a list row's menu
        self.details_view.edit_requested.connect(lambda: self._emit_for_current(self.edit_object_requested))
        self.details_view.export_requested.connect(lambda: self._emit_for_current(self.export_object_requested))
        self.details_view.export_menu_requested.connect(
            lambda pos: self._current_obj is not None and self.export_menu_requested.emit(self._current_obj, pos))
        self.details_view.import_requested.connect(lambda: self._emit_for_current(self.import_object_requested))
        side_tabs = self.side_tabs = QTabWidget()
        side_tabs.setDocumentMode(True)
        # The document-mode tab bar draws a base line across the whole width — a light one in the dark theme,
        # which read as a white stripe over the right half (user report).
        side_tabs.tabBar().setDrawBase(False)
        side_tabs.addTab(tree_page, tr("Дерево"))
        side_tabs.addTab(self.details_view, tr("Сведения"))
        side_tabs.setCurrentIndex(1 if app_settings().value("preview/side_tab", 0, type=int) == 1 else 0)
        side_tabs.currentChanged.connect(lambda index: app_settings().setValue("preview/side_tab", index))
        tab1_splitter.addWidget(side_tabs)
        tab1_splitter.setSizes([550, 350])

        tabs.addTab(tab1_splitter, tr("Просмотр"))

        # --- Tab 2: Dump — always the typed structure dump, for every type ---
        self.txt_dump = QTextEdit()
        self.txt_dump.setReadOnly(True)
        self.txt_dump.setFont(_mono_font())
        # dump_typed_text() indents with a literal tab per level (matching
        # AssetStudioGUI's own format) — Qt's default tab-stop distance (~8
        # characters wide) renders each level far wider than the content needs;
        # deeply nested objects were running off-screen fast. Half that (4
        # characters) keeps the same tab-based text (still copy-pasteable as real
        # tabs) but ~doubles how much depth fits on screen.
        self.txt_dump.setTabStopDistance(QFontMetricsF(self.txt_dump.font()).horizontalAdvance(" ") * 4)
        self.dump_highlighter = TypedDumpHighlighter(self.txt_dump.document())
        self.find_bar_dump = TextFindBar(self.txt_dump)
        dump_page = QWidget()
        dump_layout = QVBoxLayout(dump_page)
        dump_layout.setContentsMargins(0, 0, 0, 0)
        dump_layout.setSpacing(0)
        dump_layout.addWidget(self.find_bar_dump)
        dump_layout.addWidget(self.txt_dump, 1)
        self._dump_tab_index = tabs.addTab(dump_page, tr("Дамп"))

        # --- Tab 3: Structure — schema only (type/name/align-bit), no values ---
        self.txt_structure = QTextEdit()
        self.txt_structure.setReadOnly(True)
        self.txt_structure.setFont(_mono_font())
        self.txt_structure.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        # Real reported feedback: syntax highlighting here wasn't worth it —
        # unlike Дамп, there's no data VALUE to visually distinguish from
        # scaffolding. Reverted to plain text; helpers.StructureDumpHighlighter
        # is kept (commented out, not deleted) if this is wanted again later.
        self.find_bar_structure = TextFindBar(self.txt_structure)
        structure_page = QWidget()
        structure_layout = QVBoxLayout(structure_page)
        structure_layout.setContentsMargins(0, 0, 0, 0)
        structure_layout.setSpacing(0)
        structure_layout.addWidget(self.find_bar_structure)
        structure_layout.addWidget(self.txt_structure, 1)
        self._structure_tab_index = tabs.addTab(structure_page, tr("Структура"))

        # Ctrl+F opens the find bar for whichever of the three plain-text tabs
        # is currently showing — WidgetWithChildrenShortcut (not a window-wide
        # QAction shortcut like Ctrl+G's Quick Jump) so it only fires while
        # focus is actually somewhere inside this panel, same reasoning as the
        # R/G/B channel keys elsewhere in this file: Ctrl+F carries much lower
        # collision risk than a bare letter key (nobody types the CHORD
        # "Ctrl+F" as text), but scoping it here still means it can never
        # steal focus/intent from an unrelated Ctrl+F a future feature
        # elsewhere in the window might want.
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._find_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._find_shortcut.activated.connect(self._open_find_bar_for_current_tab)

        self.apply_settings()

    def _open_find_bar_for_current_tab(self) -> None:
        if self.tabs.currentIndex() == self._dump_tab_index:
            self.find_bar_dump.open_bar()
        elif self.tabs.currentIndex() == self._structure_tab_index:
            self.find_bar_structure.open_bar()
        elif self.preview_stack.currentIndex() == self.PREVIEW_TEXT:
            # The "Просмотр" tab's text-editable page — shared by kind="text"
            # (TextAsset/Shader source) and kind="json" (the generic fallback
            # for MonoBehaviour/GameObject/...). Every other preview_stack
            # page (image/audio/video/font/info) has nothing this bar can
            # usefully search, so Ctrl+F is a no-op there rather than opening
            # a bar over content it can't search.
            self.find_bar_preview.open_bar()

    def refresh_fonts(self) -> None:
        """Re-applies _mono_font() to every widget that uses it — called once
        at construction (implicitly, via each widget's own setFont(_mono_font())
        at build time) and again whenever ApplicationSettingsDialog's font
        section changes CONFIG.preview_font_family/_size, so a font change
        takes effect immediately rather than needing a restart (same
        instant-apply expectation as every other Вид/Настройки toggle)."""
        font = _mono_font()
        self.txt_preview.setFont(font)
        self.txt_info.setFont(font)
        self.txt_dump.setFont(font)
        self.txt_dump.setTabStopDistance(QFontMetricsF(self.txt_dump.font()).horizontalAdvance(" ") * 4)
        self.txt_structure.setFont(font)
        self.structure_tree.setFont(font)

    def apply_settings(self) -> None:
        """Applies CONFIG.show_tree_view/show_dump_view/preview_enabled's
        combined effect on the tab1 splitter — called once at construction
        and again whenever the Вид menu's checkable actions change any of
        them (see MainWindow._on_view_toggle; that's the only place any of
        these three ever change, so this one method is the single place their
        combination needs handling).

        Real reported shortcoming: with preview disabled, the rich-preview
        side just showed a small "Предпросмотр отключён" message while still
        occupying its usual half of the splitter — if the tree is enabled,
        it should get that reclaimed space instead of leaving it empty."""
        preview_side_useful = CONFIG.preview_enabled
        self.preview_container.setVisible(preview_side_useful)
        self.side_tabs.setVisible(CONFIG.show_tree_view)    # «Дерево» and «Сведения» share the right half

        if CONFIG.show_tree_view and preview_side_useful:
            self.tab1_splitter.setSizes([550, 350])
        elif CONFIG.show_tree_view:
            # Preview disabled, tree enabled — tree gets the whole area.
            self.tab1_splitter.setSizes([0, 1])
        else:
            # Tree disabled (regardless of preview_enabled) — preview side
            # (or, if that's ALSO disabled, just nothing) gets it all.
            self.tab1_splitter.setSizes([1, 0])

        dump_widget = self.tabs.widget(self._dump_tab_index) if self._dump_tab_index >= 0 else None
        if dump_widget is not None:
            self.tabs.setTabVisible(self._dump_tab_index, CONFIG.show_dump_view)

        structure_widget = self.tabs.widget(self._structure_tab_index) if self._structure_tab_index >= 0 else None
        if structure_widget is not None:
            self.tabs.setTabVisible(self._structure_tab_index, CONFIG.show_structure_view)

    # --- Public API ---

    def request_preview(self, obj) -> None:
        """Call on every selection change with the newly selected object's
        ObjectReader — debounces internally, so callers don't need to.

        CONFIG.preview_enabled off does NOT skip this — the structure tree
        and Dump tab (their own separate CONFIG.show_tree_view/
        show_dump_view switches) still populate normally; only the
        expensive per-type rich-preview decode is skipped, via
        build_preview()'s own skip_rich_preview flag inside
        _start_preview_worker(). See that flag's docstring for why (real
        reported bug: this used to kill the tree/dump too)."""
        self._pending_obj = obj
        self._selection_timer.start(_SELECTION_DEBOUNCE_MS)

    def is_showing(self, obj) -> bool:
        """True when `obj` is what the panel currently shows (or is about to show, the debounce
        not having fired yet) — whichever list/tree selected it. Used to refresh the preview after
        an edit/import without hijacking it away from whatever else is selected."""
        return obj is not None and (self._current_obj is obj or self._pending_obj is obj)

    def show_welcome(self, game_loaded: bool = True) -> None:
        """Shown at construction and whenever the table ends up empty (a fresh
        launch, or a load that produced no rows).

        game_loaded distinguishes "a game IS loaded but nothing's selected/no rows
        matched" (the default — "select an object" is the right prompt) from "no
        game has been loaded at all yet" (pass False — "select an object" would be
        misleading when there's nothing to select from; points at the Загрузить
        menu instead)."""
        self._reset_to_placeholder(_welcome_html() if game_loaded else _no_game_html())

    def show_multi_selection(self, count: int) -> None:
        """Call when 2+ table rows are selected at once — the preview area has
        nothing single to show, so this just says how many are selected and
        points at the multi-export context menu instead of trying to preview
        (or read) any of them."""
        self._reset_to_placeholder(_multi_selection_html(count))

    def _ensure_mesh_view(self):
        if self._mesh_view is None:
            from mesh_view import MeshView
            self._mesh_view = MeshView()
            self._mesh_page_layout.addWidget(self._mesh_view)
            import theme
            self._mesh_view.apply_theme_colors(theme.current_colors())     # the theme in use now
        return self._mesh_view

    def _release_mesh(self) -> None:
        """Drops the shown mesh's GPU data (a big mesh is tens of MB) when something else is shown."""
        if self._mesh_view is not None:
            self._mesh_view.clear()

    def _reset_to_placeholder(self, html: str) -> None:
        """Shared by show_welcome()/show_multi_selection(): switches to the
        welcome page with the given message and invalidates any in-flight
        read/sprite-navigation state — there's no longer a single selection
        for any of it to belong to."""
        self._preview_generation += 1
        self._selection_timer.stop()
        self._pending_obj = None
        self.welcome_label.setText(html)
        self._update_welcome_label_height()
        self.preview_stack.setCurrentIndex(self.PREVIEW_WELCOME)
        self.compact_summary_label.set_summary("")
        self.structure_tree.clear_object()
        self.details_view.clear()
        self._release_mesh()
        self.txt_dump.setPlainText("")
        self.txt_structure.setPlainText("")
        self._current_image_pixmap = None
        self._current_obj = None
        self._jump_back_stack = []
        self._pending_jump_source = None
        self._pending_back_target = None
        self._btn_sprite_region.hide()
        self._drop_sprite_outlines()
        self._btn_jump_back.hide()
        self._btn_scene_viewer.hide()
        self._hide_warning()
        self._array_images = None
        self._array_index = 0
        self._array_nav_row_widget.hide()

    def _update_welcome_label_height(self) -> None:
        """Real reported bug: welcome_label's own word-wrapped text was
        visibly cut off (not fully displayed) — confirmed directly, not
        guessed: at its actual allocated width, heightForWidth() reported the
        text needs 116px, but the surrounding stretch-padded QVBoxLayout
        (welcome_layout, AlignCenter + addStretch() on both sides) was only
        giving it 68px. Neither the label's own updateGeometry() nor the
        page's layout().activate() changed that — this specific combination
        of a height-for-width QLabel inside stretch items just doesn't
        renegotiate its height correctly on its own in Qt. Explicitly setting
        a minimum height from heightForWidth() is what actually works
        (confirmed the same way) — called after every text change
        (_reset_to_placeholder()) and on every resize (below), since a
        different available width needs a different wrapped height."""
        width = self.welcome_label.width()
        if width > 0:
            self.welcome_label.setMinimumHeight(self.welcome_label.heightForWidth(width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.preview_stack.currentIndex() == self.PREVIEW_WELCOME:
            self._update_welcome_label_height()

    def apply_theme_colors(self, colors) -> None:
        if self._mesh_view is not None:
            self._mesh_view.apply_theme_colors(colors)
        self.json_highlighter.set_colors(colors)
        self.dump_highlighter.set_colors(colors)
        self._style_channel_buttons(colors)
        self.structure_tree.apply_theme_colors(colors)
        self.details_view.apply_theme_colors(colors)
        self.video_preview.apply_theme_colors(colors)
        self.audio_preview.apply_theme_colors(colors)

    def cleanup(self) -> None:
        """Cancels any in-flight read and stops audio playback — call from
        MainWindow.closeEvent so the app doesn't warn about a QThread destroyed
        while still running."""
        self._preview_generation += 1
        if self._preview_worker is not None and self._preview_worker.isRunning():
            self._preview_worker.wait(1000)
        self.audio_preview.cleanup()
        self.video_preview.cleanup()

    def pause_for_environment_teardown(self) -> None:
        """Real reported crash, hit via two different call sites so far —
        same root mechanism both times, not two separate bugs:

        (1) "Save game files" (overwrite) closes each modified file's own OS
        handle/mmap once its bytes are serialized
        (core.save_manager.prepare_overwrite -> root_file.close_source_handle())
        and then tears down and reloads the whole Environment.
        (2) Starting a NEW load (MainWindow.start_loading_data) drops the
        MainWindow's own reference to the current Environment
        (_clear_loaded_session's self.env = None) and clears the shared
        cross-bundle block cache (clear_bundle_cache()) — if that was the
        last live reference, native teardown (mmap/file-handle release) can
        happen the instant that assignment runs.

        In both cases, nothing stopped THIS panel's own background worker
        (BackgroundWorker, started by _start_preview_worker for the
        currently-selected row) from still being mid-read through that exact
        same mmap at the moment it gets disposed. Reading through a released
        mmap view is undefined behavior — a plausible cause of both reported
        symptoms: an intermittent "file is being used by another process" (if
        disposal itself gets interrupted/delayed by a concurrent reader) and
        a silent crash with no error output (a hard access violation on the
        worker thread, which Python has no way to catch) — confirmed via a
        real crash.log Windows access-violation dump for case (2), pointing
        at QFileDialog.getExistingDirectory's nested event loop / the
        load-finished handler as the main thread's own frame at fault time.

        Call this from MainWindow right before EITHER a save starts or a new
        load starts — same bump-generation-then-wait shape as cleanup() (so
        any in-flight read is both told to stop ASAP via should_cancel AND
        actually waited out before this returns), plus stopping the pending
        debounce timer so a queued-but-not-yet-started read from a
        just-before selection can't start immediately after this returns and
        race whatever teardown follows it."""
        self._selection_timer.stop()
        self._preview_generation += 1
        if self._preview_worker is not None and self._preview_worker.isRunning():
            self._preview_worker.wait(3000)
        # The «Сведения» thumbnails read through the same files (thumbnail_loader.py).
        self.details_view.thumbnails.stop_for_teardown()
        # So do the sprite outlines (and the ones shown hold the sprites' readers).
        self._drop_sprite_outlines()

    # --- Background read pipeline ---

    def _start_preview_worker(self):
        obj = self._pending_obj
        if obj is None:
            return
        self._current_obj = obj

        # A track/video left playing from a previous selection otherwise keeps
        # going in the background regardless of what's now selected — stop it the
        # moment the selection actually changes (here, not after the read finishes,
        # which could be a while for a slow object) rather than only when landing on
        # ANOTHER AudioClip/VideoClip (set_audio()/set_video() already stop the old
        # one for that case).
        self.audio_preview.stop_playback()
        self.video_preview.stop_playback()

        # Every new request bumps the generation and captures its own value — see
        # the comment on self._preview_generation in __init__. should_cancel is the
        # generation-mismatch check itself: build_preview's JSON/Dump-building loops
        # (the parts of the read we can actually interrupt mid-work) poll it and
        # bail out via OperationCancelled the moment this selection is superseded,
        # instead of grinding on uselessly until the (later-discarded) end.
        self._preview_generation += 1
        gen = self._preview_generation
        self._result_pending = True

        QTimer.singleShot(_LOADING_PLACEHOLDER_DELAY_MS, lambda g=gen: self._maybe_show_loading_placeholder(g))

        # Compact summary + structure tree used to read the object directly HERE,
        # synchronously on the GUI thread, before the background worker even
        # started — on the (mostly true) assumption that "a single object's own
        # top-level parse is fast enough to do inline". Real, measured counter-
        # example: a large TMP_FontAsset's own parse alone took ~30-100ms, and
        # build_preview() below ALSO independently re-parsed the same object
        # (for the JSON dump, the typed dump, and the Cyrillic-coverage check) —
        # four full re-reads of one object per selection, which is what actually
        # produced the "preview and tree load staggered" symptom once concurrent
        # reads of the same file were correctly serialized (see this session's
        # UnityPy reader-lock fix). Both are now populated from
        # build_preview()'s own single shared parse instead — see
        # _on_preview_ready()'s handling of result.compact_summary/parsed_data/
        # parsed_node below.

        def work(report_progress):
            return build_preview(
                obj, should_cancel=lambda: gen != self._preview_generation,
                skip_rich_preview=not CONFIG.preview_enabled,
            )

        worker = BackgroundWorker(work, parent=self)
        self._preview_worker = worker
        worker.succeeded_signal.connect(lambda result, g=gen: self._on_preview_ready(g, result))
        worker.failed_signal.connect(lambda msg, g=gen: self._on_preview_failed(g, msg))
        worker.finished.connect(lambda w=worker: self._on_preview_worker_finished(w))
        worker.start()

    def _maybe_show_loading_placeholder(self, gen: int):
        if gen != self._preview_generation or not self._result_pending:
            return  # superseded, or the result already arrived — no flash
        self.preview_stack.setCurrentIndex(self.PREVIEW_INFO)
        self.txt_info.setPlainText(tr("Загрузка предпросмотра..."))

    def _on_preview_worker_finished(self, worker):
        if worker is self._preview_worker:
            self._preview_worker = None
        worker.deleteLater()

    def _on_preview_ready(self, gen: int, result: "PreviewResult"):
        self._result_pending = False
        # Final safety net: even a read that ran to completion (parts of it, like
        # image decoding, can't be interrupted mid-call) gets discarded here if a
        # newer selection has already superseded it — this is what actually
        # guarantees a late-finishing read can never overwrite what's now selected.
        if gen != self._preview_generation:
            return

        # Compact summary + structure tree — now filled from build_preview()'s
        # own single shared parse (result.compact_summary/parsed_data/parsed_node)
        # instead of each independently re-parsing the object a second/third time
        # on the GUI thread — see _start_preview_worker()'s own comment for the
        # real, measured problem this fixes. parsed_data/parsed_node are None for
        # every non-"json" kind (image/audio/video/text/font/info) — set_object()
        # falls back to its own default parse for those, unchanged from before.
        self.compact_summary_label.set_summary(result.compact_summary)
        self.structure_tree.set_object(self._current_obj, data=result.parsed_data, node=result.parsed_node)
        self.details_view.set_details(result.facts, result.references, result.reference_total)
        self.details_view.set_materials(result.model_materials, result.model_materials_total)
        self._refresh_usage()

        # Resolved together with dump_text/dump_error below, once both are known
        # — see that block for why the IL2CPP case belongs in this same banner.
        self._current_image_pixmap = None
        self._current_title = result.title
        # A fresh selection invalidates any saved pre-"На текстуре" title/summary
        # from a previous Sprite — otherwise switching sprites while still toggled
        # on to the previous one's texture view could restore the WRONG sprite's
        # info when later unchecked.
        self._sprite_title = None
        self._sprite_summary = ""

        # GameObject-only button — same "hidden by default every time" reset as
        # the Sprite-only buttons just below, shown again only in the "info"
        # branch when the object actually is a GameObject.
        self._btn_scene_viewer.hide()

        # Sprite-only buttons — hidden by default every time, shown again below
        # only for the "image" branch when the object actually is a Sprite, so
        # switching from a Sprite to any other type reliably hides them again.
        self._btn_sprite_region.blockSignals(True)
        self._btn_sprite_region.setChecked(False)
        self._btn_sprite_region.blockSignals(False)
        self._btn_sprite_region.setIcon(preview_icons.get_sprite_region_icon())
        self._btn_sprite_region.hide()
        self._outline_texture = None    # set again below for a Texture2D

        # Texture2DArray navigator — same "hidden by default every time" reset,
        # shown again below only for the "image" branch when array_images is
        # actually a 2+ list.
        self._array_images = None
        self._array_index = 0
        self._array_nav_row_widget.hide()

        self._settle_jump_history()

        if result.kind != "mesh":
            self._release_mesh()
        if result.kind == "mesh":
            view = self._ensure_mesh_view()
            view.set_geometry(result.mesh_geometry)
            self.preview_stack.setCurrentIndex(self.PREVIEW_MESH)
            # a GameObject shown as its assembled model keeps its way into the scene viewer
            self._btn_scene_viewer.setVisible(getattr(self._current_obj.type, "name", "") == "GameObject")
        elif result.kind == "image":
            pixmap = pil_to_qpixmap(result.image)
            self._current_image_pixmap = pixmap
            self.image_preview.set_image(pixmap)
            self.preview_stack.setCurrentIndex(self.PREVIEW_IMAGE)
            is_sprite = getattr(self._current_obj.type, "name", "") == "Sprite"
            self._btn_sprite_region.setVisible(is_sprite)
            if result.array_images and len(result.array_images) > 1:
                self._array_images = result.array_images
                self._array_index = 0
                self._array_nav_row_widget.show()
                self._update_array_nav_label()
            if getattr(self._current_obj.type, "name", "") == "Texture2D":
                self._outline_texture = self._current_obj
        elif result.kind == "audio":
            self.audio_preview.set_audio(
                result.audio_samples, result.audio_name, autoplay=CONFIG.autoplay_audio
            )
            self.preview_stack.setCurrentIndex(self.PREVIEW_AUDIO)
        elif result.kind == "video":
            self.video_preview.set_video(
                result.video_data, result.video_name, result.video_ext, autoplay=CONFIG.autoplay_audio
            )
            self.preview_stack.setCurrentIndex(self.PREVIEW_VIDEO)
        elif result.kind == "text":
            self._set_text_wrappable(result.text_wrappable)
            self.txt_preview.setPlainText(result.text)
            self.preview_stack.setCurrentIndex(self.PREVIEW_TEXT)
        elif result.kind == "font":
            self.font_preview.set_font_data(result.font_data)
            self.preview_stack.setCurrentIndex(self.PREVIEW_FONT)
        elif result.kind == "json":
            self._set_text_wrappable(True)
            self.txt_preview.setPlainText(result.json_text if result.json_text is not None else (result.json_error or tr("Нет данных.")))
            self.preview_stack.setCurrentIndex(self.PREVIEW_TEXT)
            # GameObject (along with MonoBehaviour/Material/AnimationClip/...)
            # has no dedicated preview of its own — _type_specific_preview()
            # falls it through to this same "show the parsed JSON" kind, which
            # is why this check lives HERE and not in the "info"/PREVIEW_INFO
            # branch below (a first version put it there — wrong, since
            # GameObject never actually reaches that branch at all).
            is_game_object = getattr(self._current_obj.type, "name", "") == "GameObject"
            self._btn_scene_viewer.setVisible(is_game_object)
        else:
            self.txt_info.setPlainText(result.info_text)
            self.preview_stack.setCurrentIndex(self.PREVIEW_INFO)

        if result.dump_text is not None:
            self.txt_dump.setPlainText(result.dump_text)
        else:
            self.txt_dump.setPlainText(result.dump_error or tr("Нет данных."))

        if result.structure_text is not None:
            self.txt_structure.setPlainText(result.structure_text)
        else:
            self.txt_structure.setPlainText(result.structure_error or tr("Нет данных."))
        # Triggers the IL2CPP banner below on either an outright dump failure
        # OR a silent partial-parse fallback (result.dump_partial — a real
        # request: a MonoBehaviour that "mostly" reads, just missing whatever
        # comes after the point its TypeTree desynced, used to show no
        # warning at all since dump_text wasn't None in that case).
        il2cpp_dump_failure = CONFIG.is_il2cpp and (result.dump_text is None or result.dump_partial)

        # One shared banner, two mutually-exclusive triggers (a resource-backed
        # type — Texture2D/AudioClip/Mesh/... — is never a MonoBehaviour, so
        # these can't both fire for the same object): a broken resource
        # reference is the more specific, actionable finding when present,
        # so it takes priority. The IL2CPP case used to be a paragraph
        # appended inline to the Dump tab's own error text — moved here so
        # it reads as a prominent, whole-game caveat instead of something
        # easy to miss buried in one object's error message.
        self._update_warning(result.resource_warning, il2cpp_dump_failure)
        self._update_sprite_outlines()

    def _update_warning(self, resource_warning: str, il2cpp_failure: bool) -> None:
        if resource_warning:
            self.preview_warning_label.setText(f"⚠ {html.escape(resource_warning)}")
            self.btn_il2cpp_fix.hide()
            self.preview_warning_frame.show()
        elif il2cpp_failure:
            self.preview_warning_label.setText(f"⚠ {tr(_IL2CPP_HINT)}")
            self.btn_il2cpp_fix.setVisible(bool(self.il2cpp_fix_available()))
            self.preview_warning_frame.show()
        else:
            self._hide_warning()

    def _hide_warning(self) -> None:
        self.preview_warning_frame.hide()
        self.btn_il2cpp_fix.hide()

    def _on_preview_failed(self, gen: int, message: str):
        # In practice this only fires for a genuinely unexpected error — build_preview
        # catches everything else internally and returns an "info" result instead of
        # raising. A superseded read's OperationCancelled also lands here (raised from
        # inside build_preview's JSON/Dump step) and is silently discarded by the same
        # generation check as _on_preview_ready, not shown as an error.
        self._result_pending = False
        if gen != self._preview_generation:
            return
        self._btn_sprite_region.hide()
        self._drop_sprite_outlines()
        self._btn_jump_back.hide()
        self._btn_scene_viewer.hide()
        self._hide_warning()
        self._jump_back_stack = []
        self._pending_jump_source = None
        self._pending_back_target = None
        self._array_images = None
        self._array_index = 0
        self._array_nav_row_widget.hide()
        self.txt_info.setPlainText(tr("Ошибка чтения объекта: {error}", error=message))
        self.preview_stack.setCurrentIndex(self.PREVIEW_INFO)
        self.txt_dump.setPlainText("")
        self.txt_structure.setPlainText("")
        # Compact summary/structure tree are no longer set synchronously before
        # the background read starts (see _start_preview_worker()'s own comment)
        # — on a genuine failure they'd otherwise be left showing the PREVIOUS
        # selection's content instead of something honest about this one.
        self.compact_summary_label.set_summary("")
        self.structure_tree.set_object(self._current_obj)
        self.details_view.clear()

    # --- Texture zoom ---

    def _set_text_wrappable(self, wrappable: bool) -> None:
        """A hex dump is never wrapped (its columns would break) and the wrap checkbox is hidden for it; any other
        text restores the checkbox and the user's saved choice."""
        self.chk_word_wrap.setVisible(wrappable)
        wrap = wrappable and self.chk_word_wrap.isChecked()
        self.txt_preview.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth if wrap else QTextEdit.LineWrapMode.NoWrap
        )

    def _on_word_wrap_toggled(self, checked: bool):
        self.txt_preview.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth if checked else QTextEdit.LineWrapMode.NoWrap
        )
        app_settings().setValue("text_preview/word_wrap", checked)

    def _on_tree_word_wrap_toggled(self, checked: bool):
        self.structure_tree.set_word_wrap(checked)
        app_settings().setValue("tree_view/word_wrap", checked)

    def _open_texture_zoom(self):
        if self._current_image_pixmap is None:
            return
        dialog = TextureZoomDialog(self._current_image_pixmap, self._current_title, self,
                                     background_mode=self.image_preview.background_mode())
        dialog.show()

    _BG_LABELS = {"checker": N_("сетка"), "white": N_("белый"), "gray": N_("серый"), "black": N_("чёрный")}

    def _cycle_image_background(self):
        mode = self.image_preview.cycle_background()
        self._update_bg_button_tooltip(mode)

    def _update_bg_button_tooltip(self, mode: str):
        self._btn_bg.setToolTip(tr("Фон: {background} (нажмите для переключения)",
                                   background=tr(self._BG_LABELS[mode])))

    # --- R/G/B channel isolation ---

    def _on_channel_button_toggled(self, index: int, checked: bool) -> None:
        if self.image_preview.channel_state()[index] != checked:
            self.image_preview.toggle_channel(index)

    def _on_channels_changed(self, state: tuple) -> None:
        # Keeps the buttons in sync when the change came from the R/G/B
        # keyboard shortcut instead of a button click — blockSignals so this
        # doesn't loop back into _on_channel_button_toggled and re-toggle.
        for btn, enabled in zip(self._channel_buttons, state):
            btn.blockSignals(True)
            btn.setChecked(enabled)
            btn.blockSignals(False)

    def _style_channel_buttons(self, colors) -> None:
        """ON (checked) shows the channel's own fixed red/green/blue accent,
        bold; OFF (unchecked) fades to the theme's ordinary disabled-text
        color — so which channels are currently isolated reads at a glance
        without needing to inspect each button's sunken/checked outline."""
        for btn in self._channel_buttons:
            accent = self._channel_accent_colors[btn.text()]
            btn.setStyleSheet(
                f"QPushButton {{ color: {accent}; font-weight: 700; }}"
                f"QPushButton:!checked {{ color: {colors.disabled_text}; font-weight: 400; }}"
            )

    # --- Texture2DArray slice navigation ---

    def _on_array_prev(self):
        if not self._array_images:
            return
        self._array_index = (self._array_index - 1) % len(self._array_images)
        self._show_array_slice()

    def _on_array_next(self):
        if not self._array_images:
            return
        self._array_index = (self._array_index + 1) % len(self._array_images)
        self._show_array_slice()

    def _show_array_slice(self):
        # Already-decoded (see PreviewResult.array_images) — this is just an
        # index into an existing list, no re-decode/background-worker round
        # trip per click.
        pixmap = pil_to_qpixmap(self._array_images[self._array_index])
        self._current_image_pixmap = pixmap
        self.image_preview.set_image(pixmap)
        self._update_array_nav_label()

    def _update_array_nav_label(self):
        self._array_index_label.setText(f"{self._array_index + 1}/{len(self._array_images)}")

    # --- Sprite -> source texture ---

    # --- «Используется в» ---

    def _refresh_usage(self) -> None:
        """Fill «Используется в» for the object shown, from the usage index (or its progress while it builds)."""
        runner, obj = self.usage_runner, self._current_obj
        if runner is None or obj is None:
            self.details_view.set_usage(None)
            return
        users = runner.users(obj)
        if users is None:
            self.details_view.set_usage(None, progress=runner.progress_now())
            return
        from core.object_references import incoming_references
        rows, total = incoming_references(users)
        self.details_view.set_usage(rows, total)

    def on_usage_index_progress(self, done: int, total: int) -> None:
        if self._current_obj is not None and self.usage_runner is not None and not self.usage_runner.finished_building:
            self.details_view.set_usage(None, progress=(done, total))

    def on_usage_index_finished(self) -> None:
        self._refresh_usage()
        if self._outline_texture is not None:
            self._update_sprite_outlines()

    # --- «Контуры спрайтов» ---

    _OUTLINES_WAIT_TIP = N_("Список спрайтов ещё собирается — флажок станет доступен через несколько секунд.")
    _OUTLINES_TIP = N_("Показать, какие части текстуры занимают её спрайты. Наведите на контур, чтобы увидеть имя "
                       "спрайта; двойной щелчок по контуру — перейти к спрайту.")

    def _drop_sprite_outlines(self) -> None:
        """Forgets the texture's outlines and waits out their read (a teardown or a placeholder follows)."""
        self._outline_generation += 1
        if self._outline_worker is not None and self._outline_worker.isRunning():
            self._outline_worker.wait(3000)
        self._outline_texture = None
        self._outline_result = None
        self.image_preview.set_outlines([])
        self.chk_sprite_outlines.hide()

    def _update_sprite_outlines(self) -> None:
        """After a preview is shown (or the usage index finishes): for a Texture2D, finds the objects that may
        hold its sprites — the index's users of it, or, without an index, the Sprites/SpriteAtlases of its own
        file — and reads their rectangles in the background. The checkbox shows once there is at least one;
        while the index is still being built it is shown disabled. Anything else hides it."""
        texture = self._outline_texture
        chk = self.chk_sprite_outlines
        if texture is None:
            chk.hide()
            return
        if self._outline_result is not None and self._outline_result[0] is texture:
            self._show_sprite_outlines()
            return
        from core.sprite_outlines import candidate_sources, sprite_outlines
        runner = self.usage_runner
        if runner is not None:
            users = runner.users(texture)
            if users is None:
                chk.setEnabled(False)
                chk.setToolTip(wrap_tooltip(tr(self._OUTLINES_WAIT_TIP)))
                chk.show()
                return
            sources = candidate_sources(texture, users)
        else:
            sources = candidate_sources(texture)
        if not sources:
            chk.hide()
            return
        self._outline_generation += 1
        gen = self._outline_generation

        def work(report_progress):
            return sprite_outlines(texture, sources, should_cancel=lambda: gen != self._outline_generation)

        worker = BackgroundWorker(work, parent=self)
        self._outline_worker = worker
        worker.succeeded_signal.connect(
            lambda outlines, g=gen, t=texture: self._on_sprite_outlines_read(g, t, outlines))
        worker.finished.connect(lambda w=worker: self._on_outline_worker_finished(w))
        worker.start()

    def _on_outline_worker_finished(self, worker) -> None:
        if worker is self._outline_worker:
            self._outline_worker = None
        worker.deleteLater()

    def _on_sprite_outlines_read(self, gen: int, texture, outlines: list) -> None:
        if gen != self._outline_generation or texture is not self._outline_texture:
            return
        self._outline_result = (texture, outlines)
        self._show_sprite_outlines()

    def _show_sprite_outlines(self) -> None:
        outlines = self._outline_result[1]
        chk = self.chk_sprite_outlines
        if not outlines:
            chk.hide()
            return
        chk.setEnabled(True)
        chk.setToolTip(wrap_tooltip(tr(self._OUTLINES_TIP)))
        chk.show()
        self.image_preview.set_outlines(outlines if chk.isChecked() else [])

    def _on_sprite_outlines_toggled(self, checked: bool) -> None:
        app_settings().setValue("preview/sprite_outlines", checked)
        if self._outline_result is not None and self._outline_result[0] is self._outline_texture:
            self._show_sprite_outlines()

    def _settle_jump_history(self) -> None:
        """Called when a preview lands (_on_preview_ready)."""
        # This selection either IS the jump _jump_from_tree() was waiting for (its
        # source goes on the back stack — a chain of jumps keeps every step, so
        # «← Назад» can walk all the way to where the chain started; user report:
        # only one level used to be remembered), the step back _navigate_back()
        # was waiting for (already popped), or an ordinary selection unrelated to
        # any jump (the history no longer applies once the user has browsed away).
        if self._pending_jump_source is not None:
            self._jump_back_stack.append(self._pending_jump_source)
            self._pending_jump_source = None
        elif self._pending_back_target is not None:
            self._pending_back_target = None
        else:
            self._jump_back_stack = []
        self._btn_jump_back.setVisible(bool(self._jump_back_stack))

    def clear_pending_jump(self):
        """Cancels a jump recorded by _jump_from_tree()
        that never actually landed on a row (see main.py's _jump_to_object()
        docstring for the real case this covers — a resolvable PPtr target with
        no table row). Left set, a stale _pending_jump_source would misattach to
        the next, unrelated selection once _on_preview_ready() fires for it,
        showing a "← Назад" button that points at the wrong object. A failed
        step BACK puts its target back on the stack (nothing was left)."""
        self._pending_jump_source = None
        if self._pending_back_target is not None:
            self._jump_back_stack.append(self._pending_back_target)
            self._pending_back_target = None

    def _emit_for_current(self, signal) -> None:
        if self._current_obj is not None:
            signal.emit(self._current_obj)

    def _jump_from_tree(self, target_obj):
        """Structure tree's "Перейти к объекту в таблице" context menu action
        (ObjectStructureTree.jump_requested) and the «Сведения» tab's reference list
        (ObjectDetailsView.jump_requested) — records where the jump was made from
        for "← Назад" (the Sprite "→ Текстура" and TMP font buttons that also used
        this were removed: «Ссылается на» lists those targets). Real reported gap: jumping via the tree used
        to forward straight to jump_to_object_requested without ever recording
        _pending_jump_source, so _on_preview_ready never saw a source to show a
        "← Назад" button for — the mechanism already existed, it just wasn't
        wired up for this entry point. See that method's own comment for why
        _current_obj is captured here and not read back off the table later."""
        self._pending_jump_source = self._current_obj
        self.jump_to_object_requested.emit(target_obj)

    def _navigate_back(self):
        """"← Назад" — undoes the last jump (from the «Сведения» list or the
        structure tree's "Перейти к объекту в таблице"), back to wherever it was
        made from; pressed again, the jump before that, down to the object the
        chain started from. A back history only — no "forward"."""
        if not self._jump_back_stack:
            return
        target = self._jump_back_stack.pop()
        self._pending_back_target = target
        self.jump_to_object_requested.emit(target)

    def _toggle_sprite_region(self, checked: bool):
        if self._current_obj is None:
            return
        if not checked:
            # Back to the plain cropped sprite — already decoded and cached from
            # the normal preview read, no need to redo any work.
            if self._current_image_pixmap is not None:
                self.image_preview.set_image(self._current_image_pixmap)
            if self._sprite_title is not None:
                self._current_title = self._sprite_title
                self.compact_summary_label.set_summary(self._sprite_summary)
            self._btn_sprite_region.setIcon(preview_icons.get_sprite_region_icon())
            return
        try:
            region_image, texture_obj = build_sprite_region_image(self._current_obj)
        except Exception as e:
            QMessageBox.warning(self, tr("Область на текстуре"), tr("Не удалось построить предпросмотр:\n{error}", error=e))
            self._btn_sprite_region.blockSignals(True)
            self._btn_sprite_region.setChecked(False)
            self._btn_sprite_region.blockSignals(False)
            return
        # Save the sprite's own title/summary so unchecking restores them exactly
        # — a real reported bug was this view giving no indication at all of
        # WHICH texture is now on screen, since neither the title bar nor the
        # metadata strip below the image ever changed to reflect it.
        self._sprite_title = self._current_title
        self._sprite_summary = self.compact_summary_label.summary_text()
        self.image_preview.set_image(pil_to_qpixmap(region_image))
        self._current_title = (
            tr("{texture}  (полная текстура спрайта «{sprite}»)",
               texture=resolve_object_name(texture_obj), sprite=self._sprite_title)
        )
        self.compact_summary_label.set_summary(build_compact_summary(texture_obj))
        # Relabels the (checkable) button itself while active, so it's obvious at
        # a glance that clicking it again goes back to the cropped sprite —
        # reported as "no way back", even though unchecking it always did exactly
        # that; the button just gave no visual hint it was a toggle you could undo.
        self._btn_sprite_region.setIcon(preview_icons.get_sprite_region_back_icon())
