"""Настройки → Настройки приложения — a single consolidated window folding
together the warning threshold, export settings, and the global bundle-
compression default (previously three separate dialogs: settings_dialogs.py's
ThresholdSettingsDialog and export_settings_dialog.py's ExportSettingsDialog,
both removed in favor of this). One window with labeled QGroupBox sections,
not tabs, per the real request — plus a destructive "Сбросить все настройки"
action.

CAB collision policy/excluded folders and the two InputSettingDialog uses
(fallback version, Unity CN key) are deliberately NOT folded in here — kept
as their own existing Настройки menu items, per explicit scope decision."""

from core.i18n import N_, tr
import html
import os
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFontComboBox, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from config import DEFAULT_PREVIEW_FONT_FAMILY, DEFAULT_PREVIEW_FONT_SIZE, reset_persisted_config
from core.object_metadata import DEFAULT_CHAR_COVERAGE_CHARS, DEFAULT_CHAR_COVERAGE_LABEL
from core.object_preview import RICH_PREVIEW_TYPES, TEXTURE_MANUAL_FORMAT_OPTIONS
from core.quick_filters import reset_quick_filters
from .indexed_types_dialog import IndexedTypesDialog
from gui_common import exec_and_dispose
from helpers import wrap_tooltip
from app_settings import app_settings

_GROUPING_OPTIONS = (
    ("none", N_("Без группировки (всё в одну папку)")),
    ("type", N_("По типу объекта (подпапка на каждый Тип)")),
    ("source", N_("По исходному файлу (подпапка на каждый Источник)")),
)

# BundleFile.save()'s packer strings. "lz4hc" is accepted there as well but
# deliberately not offered: our LZ4 already compresses at high-compression
# level, so "lz4hc" would only change the flag in the bundle header, not the
# data. "original" preserves today's default behavior (keeps the file's own flags).
_COMPRESSION_OPTIONS = (
    ("original", N_("Как в исходном файле (по умолчанию)")),
    ("none", N_("Без сжатия (быстрее всего)")),
    ("lz4", N_("LZ4 (быстрое сжатие)")),
    ("lzma", N_("LZMA (медленнее, лучше сжатие; не рекомендуется)")),
)

# No texture quality choice (removed 2026-10-20): every encoder runs at its one measured
# setting (UnityPy Texture2DConverter.compress_bcn). This picks the FORMAT (see
# core/object_preview.py's _resolve_texture_import_settings). No
# auto-pick-format-from-quality-tier mode exists — see _resolve_texture_import_settings's own
# docstring for why that was tried and dropped.
TEXTURE_FORMAT_MODE_OPTIONS = (
    ("match_original", N_("Как в оригинале")),
    ("manual", N_("Выбрать вручную")),
)


def build_texture_manual_format_combo(exclude_names=frozenset()) -> QComboBox:
    """Shared between this dialog and ConvertedImportSettingsDialog so the two
    never drift apart. Grouped by family (uncompressed/BC/ETC/ASTC/ATC) via
    plain separators — this is a picker meant to stay simple, not a tree.

    `exclude_names` (a set of TEXTURE_MANUAL_FORMAT_OPTIONS names) omits
    entries entirely rather than showing them disabled — used for BC7 version
    gating (BC7 has no TextureFormat enum value before Unity 5): this
    function has no object/version context of its own to gate with (it's
    plain data, shared by BOTH the per-import dialog AND the Settings-level
    default picker, which has no specific object at all) — the caller that
    actually knows the target object's version decides what to exclude. Empty
    by default, so ApplicationSettingsDialog's own Settings-level default
    combo (no object in scope, nothing to gate against) is entirely
    unaffected."""
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(1)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    last_family = None
    for name, family, label in TEXTURE_MANUAL_FORMAT_OPTIONS:
        if name in exclude_names:
            continue
        if last_family is not None and family != last_family:
            combo.insertSeparator(combo.count())
        combo.addItem(tr(label), name)
        last_family = family
    return combo


def _grow_to_fit(dialog: QDialog) -> None:
    """Resizes an already-shown top-level dialog to fit a just-changed
    layout — but ONLY ever grows it, never shrinks. Shared between this
    dialog and ConvertedImportSettingsDialog, both of which dynamically
    show/hide a widget in response to a combo box and need to resize
    afterward.

    Real reported bug this fixes: toggling "Формат текстур" between "Как в
    оригинале"/"Выбрать вручную" made the whole window come out visibly
    distorted — overlapping/truncated text in "Настройки индексации" plus the
    bottom button row (Сбросить все настройки / OK / Cancel) appearing
    TWICE. Root-caused via direct measurement, not guessed: an already-shown
    top-level QDialog's real native window, once shown on this Qt/Windows
    combination (reproduced on Qt 6.11 with 150% display scaling), can get
    permanently stuck at whatever size it was FIRST shown at — confirmed by
    querying WM_GETMINMAXINFO directly on the dialog's own HWND after a
    resize attempt: Windows was enforcing a minimum TRACK size pinned to the
    dialog's original on-screen size, and refused to let it shrink below
    that — not just via Qt's resize()/adjustSize(), but even via a raw
    win32 SetWindowPos() call from completely outside Qt, which was also
    silently clamped back up. Meanwhile Qt's OWN internal widget geometry
    (QWidget.size()) correctly updates to the SMALLER, intended value and
    repaints child widgets accordingly — so the dialog ends up with its
    child widgets correctly laid out for a SMALLER logical size while the
    real on-screen window never actually shrinks: the leftover area below
    the new (smaller) content is never touched by Qt's own paint logic
    (which only redraws what it believes changed) and keeps showing
    whatever was drawn there before — the OLD, larger layout's own bottom
    row — which is exactly the "duplicate content" that was reported.

    Since neither Qt's own resize machinery nor a direct WinAPI call can
    reliably shrink this dialog's real native window once shown, the fix is
    to stop trying: only ever resize UP to fit new content, never back down.
    The existing trailing addStretch(1) in each column absorbs the leftover
    space harmlessly when a later toggle needs less room again — a small,
    permanent, and far less noticeable cosmetic tradeoff against the
    genuine visual corruption this replaces. Verified via a real (non-
    offscreen) window with this project's actual persisted CONFIG: growing
    onto a wider column and back is now clean in both directions, with no
    overlap or duplication, confirmed by screen-capturing the dialog's own
    HWND directly (via PrintWindow, immune to on-screen occlusion) at each
    step."""
    target = dialog.layout().sizeHint()
    current = dialog.size()
    new_w = max(current.width(), target.width())
    new_h = max(current.height(), target.height())
    if new_w != current.width() or new_h != current.height():
        dialog.resize(new_w, new_h)

    # Real reported complaint: the dialog opens roughly centered, but this
    # function only ever GROWS its size (see the docstring above for why
    # shrinking can't be fixed) while never touching its POSITION — so
    # checking a box that reveals enough new content (e.g. VideoClip's
    # transcode options) can grow the window past the bottom/right edge of
    # a smaller screen, with no way back short of dragging it manually.
    #
    # Capping the SIZE itself to the screen was tried first and confirmed
    # NOT to work, not assumed: a live test showed that making a hidden
    # child widget visible (Qt's own reaction to setVisible(True) on a
    # widget inside an already-shown top-level dialog's layout) grows the
    # real native window to its full natural size IMMEDIATELY — before this
    # function even runs, and even with setMaximumSize() pre-set on the
    # dialog, which did not stop it either. Once grown, asking resize() to
    # shrink it back down hits the exact same "native window stuck at
    # whatever size it was first shown at" limitation this function's own
    # docstring already documents for the ORIGINAL bug — just encountered
    # from the other direction. So the size this dialog ends up at, once
    # something has made it grow past the screen, genuinely cannot be
    # capped after the fact through anything tried here.
    #
    # What CAN still be done, and is verified to work: reposition (never
    # resize) so the window's bottom-right corner — where OK/Cancel live —
    # stays anchored within the visible screen even if that means the
    # top/left extends past its edge. A window that's genuinely bigger than
    # the screen will still show truncated at the top/left either way; the
    # difference this makes is that the buttons needed to actually close the
    # dialog stay reachable, instead of a centered dialog risking OK/Cancel
    # landing entirely below the screen's bottom edge with no way to reach
    # them short of dragging the title bar blind.
    screen = dialog.screen()
    available = screen.availableGeometry() if screen is not None else None
    if available is not None:
        geo = dialog.frameGeometry()
        x = min(max(geo.x(), available.x()), available.x() + available.width() - geo.width())
        y = min(max(geo.y(), available.y()), available.y() + available.height() - geo.height())
        if x != geo.x() or y != geo.y():
            dialog.move(x, y)


def _make_help_icon(tooltip: str) -> QLabel:
    """A small "?" hint carrying a longer explanation on hover, instead of an
    always-visible multi-line QLabel note next to a control — real reported
    request: a long explanatory paragraph made the settings window feel
    cluttered even though it's only relevant to someone who actually needs
    it. The window stays compact by default; the detail is still one hover
    away.

    Real reported follow-up: a plain-text QToolTip never wraps at all — Qt
    just renders it as one line, however long, confirmed in a live
    screenshot stretching most of the screen's width. Wrapped in a
    width-constrained <div> instead, which switches Qt's tooltip renderer
    into rich-text mode and makes it actually wrap like a normal paragraph.
    html.escape() first so a literal "&"/"<"/">" in the source text (none
    currently, but not guaranteed forever) can't be misread as markup;
    \\n is then restored as an explicit <br> so an existing caller that
    already hand-placed line breaks (cb_resource_custom's own tooltip) still
    gets them, on top of the new automatic wrapping."""
    icon = QLabel("(?)")
    icon.setObjectName("MutedCaption")
    escaped = html.escape(tooltip).replace("\n", "<br>")
    icon.setToolTip(f'<div style="max-width: 280px;">{escaped}</div>')   # i18n: keep (markup)
    icon.setCursor(Qt.CursorShape.WhatsThisCursor)
    icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return icon


_QUALITY_SLIDER_NOTE = N_("0 — обычное (среднее) качество, 100 — наилучшее (медленнее кодирование).")


def build_audio_quality_slider(initial: int, help_icon: bool = False):
    """Shared between this dialog and ConvertedImportSettingsDialog, same
    reasoning as build_texture_manual_format_combo() above. Returns
    (container_widget, slider, help_icon_widget) — callers add
    container_widget to their own layout and read the final value back via
    slider.value(). help_icon_widget is None unless help_icon=True, in which
    case it's a standalone "(?)" widget (not yet placed in any layout) the
    caller places next to its OWN "Качество:"-equivalent label — real
    reported follow-up: an earlier version tucked the icon into this
    function's own slider row instead, but the natural reading position for
    a help hint is right next to the label it explains, matching this same
    dialog's "Сохранить результат в: (?)" row.

    Real reported bug this replaces a QSpinBox for: this app's dark theme's
    global stylesheet apparently assigns an icon font to QAbstractSpinBox
    (for its up/down arrow glyphs) that also affects the embedded QLineEdit's
    own digit rendering — "0" rendered as "þ" in a live screenshot, not a
    theoretical concern. A QSlider has no text-entry field of its own to be
    affected by that same styling, and a plain QLabel (not participating in
    whatever spin-box-specific QSS rule caused this) shows the live value
    instead — also a real UX preference expressed directly ("I'd prefer a
    slider instead of a text input field").

    help_icon=True (used only by ConvertedImportSettingsDialog — real
    reported complaint that dialog specifically felt cluttered) puts the
    explanation behind a "(?)" hover icon (_make_help_icon()) instead of an
    always-visible two-line QLabel above the slider. ApplicationSettingsDialog's
    own calls leave the default False — that dialog wasn't the one reported
    as cluttered, so its presentation stays exactly as it already was."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QSlider, QVBoxLayout, QWidget

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    if not help_icon:
        note = QLabel(tr(_QUALITY_SLIDER_NOTE).replace(", ", ",\n", 1))
        note.setWordWrap(True)
        layout.addWidget(note)

    row = QHBoxLayout()
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(initial)
    slider.setTickInterval(10)
    slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    row.addWidget(slider, 1)
    value_label = QLabel(str(initial))
    value_label.setMinimumWidth(28)
    slider.valueChanged.connect(lambda v: value_label.setText(str(v)))
    row.addWidget(value_label)
    layout.addLayout(row)

    help_icon_widget = _make_help_icon(tr(_QUALITY_SLIDER_NOTE)) if help_icon else None
    return container, slider, help_icon_widget


_NAV_ICON_SVG = {
    N_("Общие"): '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2.4" class="k"/>'
             '<circle cx="15" cy="12" r="2.4" class="k"/><circle cx="8" cy="18" r="2.4" class="k"/>',
    N_("Загрузка"): '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
    N_("Экспорт"): '<path d="M12 15V4M8 8l4-4 4 4M5 14v6h14v-6"/>',
    N_("Импорт"): '<path d="M12 4v11M8 11l4 4 4-4M5 19h14"/>',
    N_("Сохранение"): '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
}


def _nav_icon(title: str, normal: str = "#6cb2ff", selected: str = "#ffffff") -> QIcon:
    """A simple line icon for a settings page, drawn from SVG in the accent colour (white when the
    page is selected)."""
    icon = QIcon()
    body = _NAV_ICON_SVG.get(title, "")
    for color, mode in ((normal, QIcon.Mode.Normal), (selected, QIcon.Mode.Selected)):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
               f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
               f'{body}</svg>').replace('class="k"', f'fill="{color}"')
        renderer = QSvgRenderer(svg.encode("utf-8"))
        pix = QPixmap(96, 96)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pix, mode)
    return icon


_SECTION_STYLE = (
    # Sections are plain headed blocks — no frames around them.
    "QGroupBox { border: none; margin-top: 22px; padding-top: 0px; }"
    "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 0px; padding: 0; "
    "font-weight: bold; font-size: 15px; }"
)


class ApplicationSettingsDialog(QDialog):
    # Emitted by "Применить" in the font section — (family, size). MainWindow
    # connects this to immediately write CONFIG.preview_font_family/_size and
    # refresh the preview panel's fonts WITHOUT closing this dialog, so a font
    # choice can be seen against real content before committing to it via
    # OK/Cancel. Scoped to just the font fields, not the whole dialog's
    # values — every other section here only ever applies on OK, unchanged.
    font_apply_requested = pyqtSignal(str, int)

    def __init__(self, parent, config_values: dict):
        super().__init__(parent)
        self.setWindowTitle(tr("Настройки программы"))
        self.setModal(True)
        self.resize(430, 560)

        self.setStyleSheet(_SECTION_STYLE)
        outer = QVBoxLayout(self)

        # qBittorrent-style: a list of sections on the left, the selected section's settings on the
        # right. Every section is one page of a stacked widget, so the window never has to grow or
        # shrink when the user switches between them (the old two-column layout plus a collapsible
        # "Дополнительно" block did, which is what kept breaking its size).
        body = QHBoxLayout()
        self.nav = QListWidget()
        self.nav.setViewMode(QListWidget.ViewMode.IconMode)   # icon above its label, centred
        self.nav.setFlow(QListWidget.Flow.TopToBottom)
        self.nav.setWrapping(False)
        self.nav.setMovement(QListWidget.Movement.Static)
        self.nav.setIconSize(QSize(40, 40))
        self.nav.setGridSize(QSize(150, 84))
        self.nav.setSpacing(2)
        self.nav.setFixedWidth(160)
        self.nav.setFrameShape(QListWidget.Shape.NoFrame)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The WHOLE tile (icon + caption) is highlighted: in icon mode Qt highlights only the caption, so the
        # selected page's white icon sat on the plain list background — invisible in the light theme (user report).
        self.nav.setStyleSheet(
            # one uniform tile: the style's own caption highlight (a second band) is made transparent
            "QListWidget { show-decoration-selected: 1; selection-background-color: transparent; }"
            "QListWidget::item { border-radius: 6px; }"
            "QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }"
            "QListWidget::item:hover:!selected { background: palette(alternate-base); }")
        self.pages = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        # icons follow the theme's accent, so they match the selection colour
        pal = self.palette()
        icon_color = pal.color(pal.ColorRole.Highlight).lighter(125).name()
        icon_selected = pal.color(pal.ColorRole.HighlightedText).name()

        def add_page(title: str) -> QVBoxLayout:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(8, 0, 12, 8)
            layout.setSpacing(4)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
            item = QListWidgetItem(_nav_icon(title, icon_color, icon_selected), tr(title))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            item.setSizeHint(QSize(150, 84))
            self.nav.addItem(item)
            return layout

        page_general = add_page(N_("Общие"))
        page_loading = add_page(N_("Загрузка"))
        page_export = add_page(N_("Экспорт"))
        page_import = add_page(N_("Импорт"))
        page_saving = add_page(N_("Сохранение"))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)

        # --- Порог предупреждения ---
        threshold_box = QGroupBox(tr("Порог предупреждения"))
        threshold_layout = QVBoxLayout(threshold_box)
        threshold_label = QLabel(tr("Показывать предупреждение при превышении количества объектов:"))
        # Real reported issue: this was the ACTUAL dominant cause of the two
        # columns ending up visibly different widths, more so than either
        # combo box above — every other instructional label in this dialog
        # already wraps (see info/indexing_info/font_info below), this one
        # was simply missed; its full unwrapped text (732px sizeHint) forced
        # this whole column, and therefore the dialog itself, wider than
        # intended instead of wrapping within the column like its siblings.
        threshold_label.setWordWrap(True)
        threshold_layout.addWidget(threshold_label)
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(10_000, 500_000_000)
        self.spin_threshold.setSingleStep(100_000)
        self.spin_threshold.setGroupSeparatorShown(True)
        self.spin_threshold.setValue(config_values["object_count_threshold"])
        threshold_layout.addWidget(self.spin_threshold)
        page_loading.addWidget(threshold_box)

        # --- Настройки экспорта ---
        export_box = QGroupBox(tr("Настройки экспорта"))
        export_layout = QVBoxLayout(export_box)
        export_layout.addWidget(QLabel(tr("Группировка экспортируемых файлов:")))
        self.combo_grouping = QComboBox()
        # Real reported issue: by default a QComboBox's sizeHint is driven by
        # its LONGEST item's full text ("По исходному файлу (подпапка на
        # каждый Источник)" here) — with no cap, that alone forced this
        # column noticeably wider than the other one, even with the two
        # columns given equal (1, 1) layout stretch further down, since equal
        # stretch only splits space BEYOND each column's own natural minimum.
        # Capping the size-adjust policy lets the layout (not the longest
        # item) decide this combo's actual width; the popup still shows full
        # text, only the closed/current selection elides if it doesn't fit.
        self.combo_grouping.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_grouping.setMinimumContentsLength(1)
        self.combo_grouping.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for value, label in _GROUPING_OPTIONS:
            self.combo_grouping.addItem(tr(label), value)
        idx = self.combo_grouping.findData(config_values["export_grouping"])
        self.combo_grouping.setCurrentIndex(idx if idx >= 0 else 0)
        export_layout.addWidget(self.combo_grouping)

        self.cb_assets_subfolder = QCheckBox(tr("Складывать экспорт в подпапку UStudio_Assets"))
        self.cb_assets_subfolder.setToolTip(wrap_tooltip(
            tr("Внутри выбранной вами папки создаётся папка UStudio_Assets, и все экспортированные файлы "
               "попадают в неё. Так в вашей папке не накапливается россыпь файлов.")))
        self.cb_assets_subfolder.setChecked(config_values.get("export_assets_subfolder", True))
        export_layout.addWidget(self.cb_assets_subfolder)

        self.cb_overwrite = QCheckBox(tr("Перезаписывать существующие файлы"))
        self.cb_overwrite.setChecked(config_values["export_overwrite"])
        export_layout.addWidget(self.cb_overwrite)

        self.cb_open_folder = QCheckBox(tr("Открывать папку после экспорта"))
        self.cb_open_folder.setChecked(config_values["export_open_folder_after"])
        export_layout.addWidget(self.cb_open_folder)
        page_export.addWidget(export_box)


        # --- Сжатие бандлов по умолчанию ---
        compression_box = QGroupBox(tr("Сжатие бандлов по умолчанию"))
        compression_layout = QVBoxLayout(compression_box)
        info = QLabel(
            tr("Применяется при пересборке бандла, если локальная опция его не переопределяет.")
        )
        info.setWordWrap(True)
        compression_layout.addWidget(info)
        self.combo_compression = QComboBox()
        # Same fix as combo_grouping above — this one's longest item ("LZMA
        # (медленнее, лучше сжатие; не рекомендуется)") was the single biggest
        # contributor to the left column's oversized natural width.
        self.combo_compression.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_compression.setMinimumContentsLength(1)
        self.combo_compression.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for value, label in _COMPRESSION_OPTIONS:
            self.combo_compression.addItem(tr(label), value)
        idx = self.combo_compression.findData(config_values["bundle_compression_packer"])
        self.combo_compression.setCurrentIndex(idx if idx >= 0 else 0)
        compression_layout.addWidget(self.combo_compression)
        page_saving.addWidget(compression_box)

        # --- Конвертированный импорт ---
        # These are just the SAVED DEFAULTS used by the plain "Импортировать из файла..."
        # action (always silent) — "Импортировать из файла (с настройками)..." opens
        # ConvertedImportSettingsDialog to override them for one import instead. No "ask
        # before import" toggle here anymore — see config.py's own comment on why that
        # design (a global switch gating a single action) was replaced by two actions.
        conv_import_box = self._conv_import_box = QGroupBox(tr("Конвертированный импорт (значения по умолчанию)"))
        conv_import_layout = QVBoxLayout(conv_import_box)

        conv_import_layout.addWidget(QLabel(tr("Формат текстур:")))
        self.combo_texture_format_mode = QComboBox()
        self.combo_texture_format_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_texture_format_mode.setMinimumContentsLength(1)
        self.combo_texture_format_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for value, label in TEXTURE_FORMAT_MODE_OPTIONS:
            self.combo_texture_format_mode.addItem(tr(label), value)
        idx = self.combo_texture_format_mode.findData(config_values["texture_import_format_mode"])
        self.combo_texture_format_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_texture_format_mode.currentIndexChanged.connect(self._update_manual_format_visibility)
        conv_import_layout.addWidget(self.combo_texture_format_mode)

        self.combo_texture_manual_format = build_texture_manual_format_combo()
        idx = self.combo_texture_manual_format.findData(config_values["texture_import_manual_format"])
        self.combo_texture_manual_format.setCurrentIndex(idx if idx >= 0 else 0)
        conv_import_layout.addWidget(self.combo_texture_manual_format)

        self.cb_texture_mipmaps = QCheckBox(tr("Генерировать мип-уровни"))
        self.cb_texture_mipmaps.setChecked(config_values["texture_import_mipmaps"])
        conv_import_layout.addWidget(self.cb_texture_mipmaps)

        # Audio (FSBank's own 0-100 scale, no format picker — see
        # core.object_preview.CONVERTED_IMPORT_SUPPORTED_TYPES's own comment
        # for why AudioClip's target format is never user-chosen).
        conv_import_layout.addWidget(QLabel(tr("Качество аудио:")))
        audio_quality_widget, self.slider_audio_quality, _ = build_audio_quality_slider(
            config_values["audio_import_quality"]
        )
        conv_import_layout.addWidget(audio_quality_widget)

        page_import.addWidget(conv_import_box)

        # --- Ресурс для импорта AudioClip/VideoClip (raw и converted — оба
        # пишут через один и тот же механизм; см. комментарий в config.py к
        # resource_target_mode, почему только эти два типа) ---
        # A real reported request: the resource these two types append their
        # raw bytes into can be huge, and routing patches into their own
        # small, separately-named resource makes them shareable/self-
        # contained instead of a multi-GB diff against the original. Global
        # toggle, not per-import — see CLAUDE.md's own writeup of why a
        # second per-import axis was judged worse than what this already
        # costs (nothing extra: get_writeable_cab()-based redirection is
        # actually CHEAPER than appending to a large original bundle-
        # internal resource, not a tradeoff).
        resource_box = self._resource_box = QGroupBox(tr("Импорт аудио/видео"))
        resource_layout = QVBoxLayout(resource_box)

        resource_checkbox_row = QHBoxLayout()
        self.cb_resource_custom = QCheckBox(tr("Использовать отдельный ресурс вместо исходного"))
        self.cb_resource_custom.setChecked(config_values["resource_target_mode"] == "custom_resource")
        self.cb_resource_custom.toggled.connect(self._update_resource_name_enabled)
        resource_checkbox_row.addWidget(self.cb_resource_custom)
        resource_checkbox_row.addWidget(_make_help_icon(
            tr("При каждом импорте AudioClip/VideoClip их содержимое\nбудет дописываться в этот отдельный ресурс "
               "(создаётся\nпри первом использовании) вместо исходного .resource-файла.\n\nИзменение имени ПОЗЖЕ "
               "не переносит уже импортированные\nобъекты — они останутся ссылаться на прежний ресурс,\nа новые "
               "начнут заполнять уже новый.")
        ))
        resource_checkbox_row.addStretch(1)
        resource_layout.addLayout(resource_checkbox_row)

        self.edit_resource_name = QLineEdit(config_values["resource_name"])
        self.edit_resource_name.setPlaceholderText("res_new.resource")
        resource_layout.addWidget(self.edit_resource_name)

        self._update_resource_name_enabled(self.cb_resource_custom.isChecked())
        page_import.addWidget(resource_box)

        # --- Настройки индексации ---
        # CONFIG.indexed_types — user-configurable counterpart to the hardcoded
        # RICH_PREVIEW_TYPES allow-list (core/object_preview.py) that decides
        # which object types actually become table rows.
        indexing_box = QGroupBox(tr("Настройки индексации"))
        indexing_layout = QVBoxLayout(indexing_box)
        indexing_info = QLabel(
            tr("Выберите какие типы объектов будут добавляться в таблицу. Не действует, если включена загрузка "
               "всех ассетов.")
        )
        indexing_info.setWordWrap(True)
        indexing_layout.addWidget(indexing_info)

        self._indexed_types = list(config_values["indexed_types"])
        self.lbl_indexed_types_count = QLabel()
        self._update_indexed_types_label()
        indexing_layout.addWidget(self.lbl_indexed_types_count)

        indexed_types_row = QHBoxLayout()
        btn_indexed_types = QPushButton(tr("Выбрать типы объектов..."))
        btn_indexed_types.clicked.connect(self._open_indexed_types_dialog)
        indexed_types_row.addWidget(btn_indexed_types)
        btn_indexed_types_reset = QPushButton(tr("Сбросить"))
        btn_indexed_types_reset.setToolTip(tr("Вернуть список типов объектов к значению по умолчанию"))
        btn_indexed_types_reset.clicked.connect(self._reset_indexed_types)
        indexed_types_row.addWidget(btn_indexed_types_reset)
        indexed_types_row.addStretch(1)
        indexing_layout.addLayout(indexed_types_row)
        page_loading.addWidget(indexing_box)

        # --- Шрифт предпросмотра (Дерево/Дамп/Json Dump) ---
        font_box = QGroupBox(tr("Шрифт предпросмотра"))
        font_layout = QVBoxLayout(font_box)

        font_row = QHBoxLayout()
        self.font_combo = QFontComboBox()
        # ScalableFonts excludes legacy bitmap fonts (Fixedsys, Terminal, ...) —
        # without it, MonospacedFonts alone still let those through (they DO
        # report as monospaced), and Qt's DirectWrite backend can't build a
        # real font face for a non-scalable bitmap font at all: every time this
        # combo box tried to render one as its own list-item preview, it logged
        # "qt.qpa.fonts: DirectWrite: CreateFontFaceFromHDC() failed" — a real
        # reported warning, and picking one of these wouldn't have rendered
        # correctly in the preview panel anyway.
        self.font_combo.setFontFilters(
            QFontComboBox.FontFilter.MonospacedFonts | QFontComboBox.FontFilter.ScalableFonts
        )
        current_family = config_values["preview_font_family"] or DEFAULT_PREVIEW_FONT_FAMILY
        self.font_combo.setCurrentFont(QFont(current_family))
        font_row.addWidget(self.font_combo, 1)

        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(6, 32)
        self.spin_font_size.setSuffix(" pt")
        self.spin_font_size.setValue(config_values["preview_font_size"])
        font_row.addWidget(self.spin_font_size)
        font_layout.addLayout(font_row)

        font_buttons_row = QHBoxLayout()
        btn_font_apply = QPushButton(tr("Применить"))
        btn_font_apply.setToolTip(tr("Сразу применить шрифт к области предпросмотра, не закрывая это окно"))
        btn_font_apply.clicked.connect(self._apply_font_now)
        font_buttons_row.addWidget(btn_font_apply)
        btn_font_reset = QPushButton(tr("Сбросить"))
        btn_font_reset.clicked.connect(self._reset_font)
        font_buttons_row.addWidget(btn_font_reset)
        font_layout.addLayout(font_buttons_row)
        page_general.addWidget(font_box)

        # --- Проверка поддержки символов ---
        # Real request, once localization was raised as a later goal: this check used to be
        # hardcoded to Cyrillic (a Font's cmap, or a TMP_FontAsset's own baked character table) —
        # a label and character set the user can redefine for any language/project instead. Shown
        # in the Font/TMP_FontAsset preview's metadata line and, for TMP_FontAsset, in the SDF
        # Viewer's per-font header line.
        coverage_box = QGroupBox(tr("Проверка поддержки символов"))
        coverage_layout = QVBoxLayout(coverage_box)
        coverage_label_row = QHBoxLayout()
        coverage_label_row.addWidget(QLabel(tr("Название:")))
        self.edit_coverage_label = QLineEdit(config_values["char_coverage_label"])
        self.edit_coverage_label.setPlaceholderText(DEFAULT_CHAR_COVERAGE_LABEL)
        coverage_label_row.addWidget(self.edit_coverage_label, 1)
        coverage_layout.addLayout(coverage_label_row)
        coverage_chars_row = QHBoxLayout()
        coverage_chars_row.addWidget(QLabel(tr("Символы:")))
        self.edit_coverage_chars = QLineEdit(config_values["char_coverage_chars"])
        self.edit_coverage_chars.setPlaceholderText(tr("АБВГ..."))
        coverage_chars_row.addWidget(self.edit_coverage_chars, 1)
        coverage_chars_row.addWidget(_make_help_icon(
            tr("Помогает быстро увидеть, каким шрифтам игры не хватает символов нужного вам языка. Шрифт "
               "считается поддерживающим эту группу, если среди его символов есть хотя бы 90% перечисленных "
               "здесь. Метка нужна для отображения в строке метаданных.")
        ))
        coverage_layout.addLayout(coverage_chars_row)
        btn_coverage_reset = QPushButton(tr("Сбросить"))
        btn_coverage_reset.clicked.connect(self._reset_char_coverage)
        coverage_layout.addWidget(btn_coverage_reset)
        page_general.addWidget(coverage_box)

        # --- Прочее (журнал) ---
        other_general_box = QGroupBox(tr("Прочее"))
        other_general_layout = QVBoxLayout(other_general_box)
        log_row = QHBoxLayout()
        self.cb_debug_log = QCheckBox(tr("Показывать отладочные сообщения"))
        self.cb_debug_log.setChecked(config_values["show_debug_log"])
        log_row.addWidget(self.cb_debug_log)
        log_row.addWidget(_make_help_icon(
            tr("Добавляет в журнал подробности, которые обычно не нужны: списки пропущенных файлов, какие папки "
               "с библиотеками использованы и т. п. Пригодится, если что-то загрузилось не так, как ожидалось.")
        ))
        log_row.addStretch(1)
        other_general_layout.addLayout(log_row)
        # The program's own folder in AppData (user request: here, on «Общие», not in the bottom button row).
        folder_row = QHBoxLayout()
        self.btn_app_folder = QPushButton(tr("Открыть служебную папку UStudio"))
        self.btn_app_folder.clicked.connect(self._open_app_data_folder)
        folder_row.addWidget(self.btn_app_folder)
        folder_row.addWidget(_make_help_icon(tr("Журнал ошибок, резервные копии и временные данные программы.")))
        folder_row.addStretch(1)
        other_general_layout.addLayout(folder_row)
        page_general.addWidget(other_general_box)

        # --- Резервные копии ---
        other_box = QGroupBox(tr("Резервные копии"))
        other_layout = QVBoxLayout(other_box)
        self.cb_backup = QCheckBox(tr("Делать резервную копию оригиналов перед перезаписью"))
        self.cb_backup.setChecked(config_values["backup_before_overwrite"])
        self.cb_backup.setToolTip(tr("Копии складываются в отдельную папку вне папки игры, по одной на каждое сохранение."))
        other_layout.addWidget(self.cb_backup)
        keep_row = QHBoxLayout()
        keep_row.addSpacing(22)
        keep_row.addWidget(QLabel(tr("Хранить последних копий (шт.):")))
        self.spin_backup_keep = QSpinBox()
        self.spin_backup_keep.setRange(0, 20)
        self.spin_backup_keep.setValue(config_values["backup_keep_latest"])
        keep_row.addWidget(self.spin_backup_keep)
        keep_row.addWidget(_make_help_icon(
            tr("Первая копия каждого файла (оригинал до любых изменений) хранится всегда. Из остальных остаются "
               "только самые новые — так копии не разрастаются.")
        ))
        keep_row.addStretch(1)
        other_layout.addLayout(keep_row)
        self.cb_backup.toggled.connect(lambda on: self.spin_backup_keep.setEnabled(on))
        self.spin_backup_keep.setEnabled(self.cb_backup.isChecked())
        page_saving.addWidget(other_box)

        for layout in (page_general, page_loading, page_export, page_import, page_saving):
            layout.addStretch(1)

        # remembered between openings
        last_page = app_settings().value("app_settings/last_page", 0, type=int)
        self.nav.setCurrentRow(last_page if 0 <= last_page < self.nav.count() else 0)
        self.nav.currentRowChanged.connect(
            lambda row: app_settings().setValue("app_settings/last_page", row))

        # --- Bottom row: red Reset (left) + Ok/Cancel (right), visually
        # separated so the destructive action can't be misclicked. ---
        bottom = QHBoxLayout()
        btn_reset = QPushButton(tr("Сбросить все настройки"))
        btn_reset.setToolTip(tr("Сбрасывает ВСЕ сохранённые настройки программы"))
        btn_reset.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; padding: 5px 12px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #e74c3c; }"
            "QPushButton:pressed { background-color: #a93226; }"
        )
        btn_reset.clicked.connect(self._on_reset_all)
        bottom.addWidget(btn_reset)
        bottom.addStretch(1)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        bottom.addWidget(btn_box)
        outer.addLayout(bottom)

        # Must run only once the ENTIRE layout exists (both columns, bottom row
        # included) — this is the same widget-visibility toggle the currentIndexChanged
        # signal calls live later, but calling it earlier (right after building just
        # the two format combos, before conv_import_box even had its remaining widgets
        # or was added to right_col) made its own adjustSize() lock in a size computed
        # from a still-empty right column, permanently narrowing "Конвертированный
        # импорт" — real reported bug, not present when the combo is left on its
        # default "Как в оригинале" precisely because this call used to run before
        # anything downstream existed to be sized correctly in the first place.
        self._update_manual_format_visibility()

    def _update_indexed_types_label(self) -> None:
        self.lbl_indexed_types_count.setText(tr("Выбрано типов: {count}", count=len(self._indexed_types)))

    def _open_indexed_types_dialog(self) -> None:
        dialog = IndexedTypesDialog(self, self._indexed_types)
        if exec_and_dispose(dialog) == QDialog.DialogCode.Accepted:
            self._indexed_types = dialog.get_selected_types()
            self._update_indexed_types_label()

    def _apply_font_now(self) -> None:
        self.font_apply_requested.emit(self.font_combo.currentFont().family(), self.spin_font_size.value())

    def _reset_font(self) -> None:
        # Local-only reset (unlike "Сбросить все настройки" below) — reverts
        # just this dialog's working values; still needs Ok to actually
        # apply/persist, same as _reset_indexed_types below.
        self.font_combo.setCurrentFont(QFont(DEFAULT_PREVIEW_FONT_FAMILY))
        self.spin_font_size.setValue(DEFAULT_PREVIEW_FONT_SIZE)

    def _reset_char_coverage(self) -> None:
        # Local-only reset, same convention as _reset_font above — still needs Ok to apply.
        self.edit_coverage_label.setText(DEFAULT_CHAR_COVERAGE_LABEL)
        self.edit_coverage_chars.setText(DEFAULT_CHAR_COVERAGE_CHARS)

    def _reset_indexed_types(self) -> None:
        # Local-only reset (unlike "Сбросить все настройки" below) — reverts
        # just this working value back to RICH_PREVIEW_TYPES; still needs Ok
        # to actually apply/persist, same as any other field in this dialog.
        self._indexed_types = sorted(RICH_PREVIEW_TYPES)
        self._update_indexed_types_label()

    def _update_manual_format_visibility(self) -> None:
        self.combo_texture_manual_format.setVisible(self.combo_texture_format_mode.currentData() == "manual")
        self._conv_import_box.layout().activate()
        self.layout().activate()
        _grow_to_fit(self)

    def _update_resource_name_enabled(self, checked: bool) -> None:
        # setEnabled (grey out), not setVisible — the field's own size never
        # changes, so unlike _update_manual_format_visibility above there's
        # nothing here that needs the layout-reactivate/_grow_to_fit dance.
        self.edit_resource_name.setEnabled(checked)

    @staticmethod
    def app_data_folder() -> Path:
        """%LOCALAPPDATA%\\UStudio — crash.log, backups, the APK and IL2CPP caches."""
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "UStudio"

    def _open_app_data_folder(self) -> None:
        folder = self.app_data_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as e:
            QMessageBox.warning(self, tr("Папка UStudio"), tr("Не удалось открыть папку {folder}: {error}", folder=folder, error=e))

    def _on_reset_all(self) -> None:
        reply = QMessageBox.question(
            self,
            tr("Сбросить все настройки?"),
            tr("Вы уверены? Это сбросит ВСЕ настройки программы к значениям по умолчанию."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        reset_persisted_config()
        reset_quick_filters()
        QMessageBox.information(
            self,
            tr("Настройки сброшены"),
            tr("Изменения вступят в силу после перезапуска программы."),
        )

    def get_values(self) -> dict:
        return {
            "object_count_threshold": self.spin_threshold.value(),
            "export_grouping": self.combo_grouping.currentData(),
            "export_assets_subfolder": self.cb_assets_subfolder.isChecked(),
            "export_overwrite": self.cb_overwrite.isChecked(),
            "export_open_folder_after": self.cb_open_folder.isChecked(),
            "backup_before_overwrite": self.cb_backup.isChecked(),
            "backup_keep_latest": self.spin_backup_keep.value(),
            "bundle_compression_packer": self.combo_compression.currentData(),
            "indexed_types": self._indexed_types,
            "preview_font_family": self.font_combo.currentFont().family(),
            "preview_font_size": self.spin_font_size.value(),
            "texture_import_format_mode": self.combo_texture_format_mode.currentData(),
            "texture_import_manual_format": self.combo_texture_manual_format.currentData(),
            "texture_import_mipmaps": self.cb_texture_mipmaps.isChecked(),
            "audio_import_quality": self.slider_audio_quality.value(),
            "resource_target_mode": (
                "custom_resource" if self.cb_resource_custom.isChecked() else "original"
            ),
            "resource_name": self.edit_resource_name.text().strip() or "res_new.resource",
            "char_coverage_label": self.edit_coverage_label.text().strip() or DEFAULT_CHAR_COVERAGE_LABEL,
            "char_coverage_chars": self.edit_coverage_chars.text() or DEFAULT_CHAR_COVERAGE_CHARS,
            "show_debug_log": self.cb_debug_log.isChecked(),
        }
