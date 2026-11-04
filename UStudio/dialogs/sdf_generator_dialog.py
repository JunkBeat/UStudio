"""Settings collector (and, for the single-object case, live generator) for
adding new characters to an existing TMP_FontAsset's SDF atlas.

Two distinct shapes, controlled by `font_obj`/`show_preview`:
- Single object (ObjectActionsController.generate_sdf_font): show_preview=True
  — the dialog itself RUNS generation (on a background worker, so it stays
  responsive during the msdf-atlas-gen subprocess call) and shows the
  resulting atlas image before anything is written anywhere, mirroring
  Unity's own Font Asset Creator workflow (Generate -> inspect -> Save/
  discard) that this was explicitly modeled on. The actual obj.patch()/
  texture patch only happens if the user clicks "Сохранить" — see
  core.sdf_generator.add_characters_to_font_asset()'s own auto_commit
  parameter for how a rejected/never-saved generation ends up touching
  nothing at all.
- Batch (ObjectActionsController.generate_sdf_font_multi): show_preview=False
  — the classic settings-collector shape, unchanged in spirit from before
  this feature: OK/Cancel, no atlas preview (a batch spans several font
  assets, each with its own atlas — there's no single "the" atlas to show),
  actual generation runs afterward via the existing task-queue background
  task.

Both shapes share the same Font Size / SDF Spread settings (added this
session) — see _SizeOverrideGroup's own docstring for why "Match original"
resolves per-schema rather than blindly, and why "Rendering mode/anti-
aliasing" (as originally requested) isn't offered: confirmed against Unity's
own Font Asset Creator docs and msdf-atlas-gen's own -help output that
Raster/Smooth render modes are plain (non-SDF) bitmaps incompatible with this
app's SDF-only shader support, and msdf-atlas-gen has no hinting/anti-
aliasing toggle at all (it builds distance fields directly from vector
outlines, never a rasterized bitmap) — SDF spread (pxrange) is the real,
actionable equivalent for "sharper vs. softer edges" within an SDF pipeline.

SDF-only, deliberately — see core/sdf_generator.py's own module docstring for
why (stock TMP shaders have no MSDF decode path; this dialog doesn't offer a
type choice at all, since there's only ever one type to generate)."""

from core.i18n import tr
from typing import List, Optional

from PIL import Image
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter, QTextEdit,
    QVBoxLayout, QWidget,
)

from config import CONFIG, save_persisted_config
import os

import theme
from core.font_cmap import font_coverage
from dialogs.sdf_settings_panel import (
    SDFSettingsPanel, _CONTROL_HEIGHT, _MAP_DEFAULTS_HELP, _SIZE_LABEL_WIDTH, _make_label_cell,
    refresh_nested_geometry,
)
from core.sdf_generator import add_characters_to_font_asset
from dialogs.app_settings_dialog import _make_help_icon
from gui_widgets import pil_to_qpixmap
from gui_workers import BackgroundWorker
from helpers import mono_font, wrap_tooltip

# Below this share of the typed characters the font is flagged. Same 90 % the SDF view's "Cyrillic support"
# label uses (core.object_metadata.font_supports_cyrillic): one rarely used letter missing is not a warning.
_COVERAGE_WARN_BELOW = 0.9
_COVERAGE_DEBOUNCE_MS = 250
_MISSING_SHOWN = 40       # how many missing characters the tooltip lists


def coverage_caption(have: int, total: int) -> tuple:
    """(text, is_warning) for "the chosen font has `have` of the `total` typed characters". The percentage is
    rounded DOWN, so 99.6 % never reads as 100 %. One short line on purpose: the dialog's settings column is
    full, a caption that wraps to two lines pushed the rest around. The warning is shown by colour only."""
    if total <= 0:
        return "", False
    percent = have * 100 // total
    return tr("Наличие символов: {percent}% ({have} из {total})", percent=percent, have=have, total=total), have < total * _COVERAGE_WARN_BELOW


def _missing_tooltip(missing: list) -> str:
    if not missing:
        return ""
    shown = " ".join(chr(cp) if chr(cp).strip() else f"U+{cp:04X}" for cp in missing[:_MISSING_SHOWN])
    more = "…" if len(missing) > _MISSING_SHOWN else ""
    return wrap_tooltip(tr("Нет в шрифте ({count}): {shown}{more}", count=len(missing), shown=shown, more=more))


def _sdf_atlas_to_preview_image(atlas_img: Image.Image) -> Image.Image:
    """Real reported bug: showing the raw atlas image made it effectively
    invisible on a dark theme. An SDF atlas is RGBA with R=G=B=0 always and
    the actual distance value encoded in Alpha (this project's own
    established convention — see core/sdf_generator.py's
    _crop_padded_bitmap() docstring) — displayed as-is, both the opaque
    glyph interiors (pure black) AND the transparent background read as
    "dark" against a dark theme, so the whole preview looked blank
    regardless of what it actually contained. Extracting Alpha into a fully
    opaque grayscale image instead shows the real distance-field data
    directly (bright = deep inside a glyph, dark = far outside a glyph) and
    is visible against any background, light or dark, since nothing in the
    result is transparent."""
    alpha = atlas_img.split()[-1]
    return Image.merge("RGB", (alpha, alpha, alpha))

class SDFGeneratorDialog(QDialog):
    def __init__(
        self, parent, font_display_name: str, default_font_path: str = "",
        current_point_size: Optional[float] = None, current_pxrange: Optional[float] = None,
        font_obj=None, show_preview: bool = False, varies_per_object: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("Генерация SDF"))
        self.setModal(True)
        self._font_obj = font_obj
        self._show_preview = show_preview and font_obj is not None
        self._worker = None
        self._result = None  # the AddCharactersResult from the last successful Generate (preview mode only)

        outer = QVBoxLayout(self)

        # --- settings (always present) ---
        settings_widget = QWidget()
        settings = QVBoxLayout(settings_widget)
        # Right gutter only in preview mode: there the settings column butts
        # directly against the splitter handle, and without it the row-ending
        # buttons ("Обзор...", "Удалить") sit flush on the divider.
        settings.setContentsMargins(0, 0, 8 if self._show_preview else 0, 0)
        lbl_subject = QLabel(f"SDF: {font_display_name}")
        lbl_subject.setStyleSheet("font-weight: bold;")
        lbl_subject.setWordWrap(True)
        settings.addWidget(lbl_subject)

        # font_row and its optional hint are grouped in their OWN tight-
        # spacing layout (2px between them) rather than added as two
        # separate top-level items in `settings` (which would each get the
        # column's normal, much larger inter-row spacing on both sides) --
        # see the hint's own comment below for why this specific anchoring
        # was the real reported problem.
        font_group = QVBoxLayout()
        font_group.setContentsMargins(0, 0, 0, 0)
        font_group.setSpacing(2)
        font_row = QHBoxLayout()
        # A nested QHBoxLayout with no spacing of its own was found (by
        # direct measurement, not assumption) to inherit its PARENT layout's
        # spacing (font_group's tight 2px) instead of this app's normal 6px
        # inter-widget default -- pulling edit_font_path 4px closer to its
        # label than every other row, breaking the shared column alignment.
        # Set explicitly so this row's OWN internal spacing can't be affected
        # by font_group's unrelated (vertical, between font_row and the hint
        # below it) spacing setting.
        font_row.setSpacing(6)
        font_row.addWidget(_make_label_cell(tr("Файл шрифта:")))
        # An embedded source font (default_font_path, extracted specifically
        # for THIS font asset) takes priority over the generic last-used-this-
        # session path — it's the more correct default when it exists at all;
        # the remembered path is only a fallback for the (routine) case where
        # this asset has no embedded font, so the user isn't stuck re-browsing
        # for the same file on every single font asset in one session.
        # Kept so _on_accept() can tell whether the user left this exact
        # embedded default in place (see its own docstring for why that
        # case must NOT be persisted to CONFIG.sdf_last_font_path).
        self._embedded_font_path = default_font_path
        initial_font_path = default_font_path or CONFIG.sdf_last_font_path
        self.edit_font_path = QLineEdit(initial_font_path)
        self.edit_font_path.setPlaceholderText(tr("Путь к файлу .ttf / .otf"))
        self.edit_font_path.setFixedHeight(_CONTROL_HEIGHT)
        btn_browse = QPushButton(tr("Обзор..."))
        btn_browse.setFixedHeight(_CONTROL_HEIGHT)
        btn_browse.clicked.connect(self._browse_font)
        font_row.addWidget(self.edit_font_path, 1)
        font_row.addWidget(btn_browse)
        font_group.addLayout(font_row)
        # "How much of the typed text does this font have" — under the font field, like a hint about it.
        coverage_row = QHBoxLayout()
        coverage_row.setContentsMargins(_SIZE_LABEL_WIDTH + font_row.spacing(), 0, 0, 0)
        self.lbl_font_coverage = QLabel("")
        self.lbl_font_coverage.setObjectName("MutedCaption")
        self.lbl_font_coverage.setWordWrap(True)
        self.lbl_font_coverage.setVisible(False)
        coverage_row.addWidget(self.lbl_font_coverage)
        font_group.addLayout(coverage_row)
        ## if default_font_path:
            # A real reported issue with the earlier version of this hint:
            # it was just another full-width QLabel added straight to the
            # column with the SAME inter-row spacing as every real settings
            # row above AND below it -- nothing made it read as a secondary
            # note ABOUT the field above rather than its own independent row,
            # so it floated with no clear anchor either way. Fixed three
            # ways: grouped into font_row's own tight (2px) inner layout
            # instead of the column's normal ~8px inter-row spacing, so it
            # visibly hugs the field it explains rather than sitting
            # equidistant between two unrelated rows; indented to start where
            # the field itself starts (skipping past the label cell); and
            # styled via the app's existing #MutedCaption convention
            # (smaller, dimmer -- the same treatment already used for
            # secondary/hint text elsewhere, e.g. the atlas preview's own
            # placeholder), so it visually reads as commentary, not content.
            
            ## hint_row = QHBoxLayout()
            ## hint_row.setContentsMargins(_SIZE_LABEL_WIDTH, 0, 0, 0)
            ## hint = QLabel("(извлечён из SDF шрифта — при необходимости выберите другой файл)")
            ## hint.setObjectName("MutedCaption")
            ## hint.setWordWrap(True)
            ## hint_row.addWidget(hint)
            ## font_group.addLayout(hint_row)
        settings.addLayout(font_group)

        preset_row = QHBoxLayout()
        preset_row.addWidget(_make_label_cell(tr("Пресет:")))
        self.combo_presets = QComboBox()
        self.combo_presets.setFixedHeight(_CONTROL_HEIGHT)
        self.combo_presets.currentIndexChanged.connect(self._on_preset_selected)
        btn_save_preset = QPushButton(tr("Сохранить..."))
        btn_save_preset.setFixedHeight(_CONTROL_HEIGHT)
        btn_save_preset.clicked.connect(self._save_preset)
        btn_delete_preset = QPushButton(tr("Удалить"))
        btn_delete_preset.setFixedHeight(_CONTROL_HEIGHT)
        btn_delete_preset.clicked.connect(self._delete_preset)
        preset_row.addWidget(self.combo_presets, 1)
        preset_row.addWidget(btn_save_preset)
        preset_row.addWidget(btn_delete_preset)
        settings.addLayout(preset_row)
        self._reload_presets_combo()

        self.edit_characters = QTextEdit()
        self.edit_characters.setPlaceholderText(tr("Введите символы..."))
        self.edit_characters.setFont(mono_font())
        self.edit_characters.setFixedHeight(90)
        # QSS's `padding` on QTextEdit only insets the FRAME the scroll area
        # draws -- confirmed by direct measurement: viewportMargins() stayed
        # (0,0,0,0) despite the app-wide stylesheet's own "padding: 3px 6px"
        # rule, so real text content was only ever inset by the QTextDocument's
        # own small 4px default margin, nowhere near enough for dense text —
        # a real reported "collides with the border" bug, not a false read of
        # an already-padded box. Set explicitly in code since the stylesheet
        # can't reach this particular widget's actual content area.
        self.edit_characters.setViewportMargins(6, 6, 6, 6)
        if CONFIG.sdf_last_characters:
            self.edit_characters.setPlainText(CONFIG.sdf_last_characters)
        elif CONFIG.sdf_character_presets:
            # First run: start from the first (default) preset instead of an empty box.
            first = sorted(CONFIG.sdf_character_presets)[0]
            self.edit_characters.setPlainText(CONFIG.sdf_character_presets[first])
            self._reload_presets_combo(select_name=first)
        settings.addWidget(self.edit_characters)

        # The font file is read when the path changes; typing characters only re-checks the cached bytes.
        self._coverage_font_cache = ("", None, b"")    # (path, (mtime_ns, size), bytes)
        self._coverage_timer = QTimer(self)
        self._coverage_timer.setSingleShot(True)
        self._coverage_timer.setInterval(_COVERAGE_DEBOUNCE_MS)
        self._coverage_timer.timeout.connect(self._update_font_coverage)
        self.edit_font_path.textChanged.connect(self._coverage_timer.start)
        self.edit_characters.textChanged.connect(self._coverage_timer.start)
        self._update_font_coverage()      # on open: an embedded (Temp) font or the remembered path

        # Mode, size, sharpness and the two full-replacement checkboxes: one shared panel (also used by
        # the sdf_map.txt import dialog below), see dialogs/sdf_settings_panel.py.
        self.settings_panel = SDFSettingsPanel(
            current_point_size=current_point_size, current_pxrange=current_pxrange,
            varies_per_object=varies_per_object, mode=CONFIG.sdf_last_mode,
            last_custom_point_size=CONFIG.sdf_last_custom_point_size,
            last_custom_pxrange=CONFIG.sdf_last_custom_pxrange, add_missing=CONFIG.sdf_add_missing,
        )
        self.settings_panel.mode_changed.connect(self._on_mode_changed)
        settings.addWidget(self.settings_panel)

        if self._show_preview:
            # --- Unity Font Asset Creator-style layout: settings on the
            # left, atlas preview on the right, Generate/Save/Cancel instead
            # of OK/Cancel. Nothing is written anywhere until "Сохранить" —
            # see the module docstring's own explanation of why. ---

            # Results/log area, like Unity's own "Missing Characters" list —
            # lives at the BOTTOM of the settings column (below the actual
            # generation settings), not stacked into the preview pane on the
            # right, which stays exactly what its own label says: nothing
            # but the atlas image. A real per-character skip reason (see
            # AddCharactersResult.summary_text()) can be one line per
            # untranscribed character, i.e. genuinely log-shaped, not a
            # single short caption — QTextEdit(read-only) over QLabel so a
            # long report scrolls instead of pushing the buttons off-screen.
            #
            # Real reported issue with an earlier version of this: giving it
            # stretch=1 let it absorb ALL of the settings column's leftover
            # vertical height (however much that happened to be, driven by
            # the atlas preview's own much taller minimum size) -- for an
            # ordinary short 3-4 line result, that left a huge, mostly-empty
            # dark box that read as broken/unfinished rather than "waiting
            # for output". Capped to a modest height instead (roughly what
            # Unity's own Character Sequence box gets) with its own explicit
            # padding (same QSS-can't-reach-viewport-margins issue as
            # edit_characters above); the leftover space that's still there
            # regardless (settings is shorter than the preview column) now
            # goes to a plain trailing addStretch(1) at the very bottom of
            # the column instead of bloating a labeled box -- empty space
            # below everything reads as "this panel is just shorter", not as
            # a specific broken widget.
            settings.addWidget(QLabel(tr("Логи:")))
            self.txt_summary = QTextEdit()
            self.txt_summary.setReadOnly(True)
            # Real reported issue: mono_font() is this app's shared DENSE
            # DATA font (11pt Cascadia Mono, tuned for the Preview/Dump tabs'
            # code-like content) — visibly larger than the rest of this
            # dialog's own regular UI font. summary_text() is a plain,
            # short human-readable status line ("added N of M characters",
            # a resize note), not code or aligned columnar data, so it has
            # no actual need for a monospace face — inheriting the dialog's
            # normal font instead makes it read as a log line, not a
            # conspicuously oversized outlier. edit_characters right above
            # keeps mono_font() deliberately: a character SET genuinely
            # benefits from monospace alignment the way a log message
            # doesn't.
            self.txt_summary.setViewportMargins(6, 6, 6, 6)
            self.txt_summary.setFixedHeight(90)
            settings.addWidget(self.txt_summary)
            settings.addStretch(1)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.addWidget(settings_widget)

            preview_widget = QWidget()
            preview_layout = QVBoxLayout(preview_widget)
            preview_layout.setContentsMargins(8, 0, 0, 0)  # matching gutter on the divider's other side
            preview_layout.addWidget(QLabel(tr("Предпросмотр атласа:")))
            self.lbl_atlas_preview = QLabel(tr("Нажмите «Генерировать», чтобы увидеть новый атлас."))
            self.lbl_atlas_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_atlas_preview.setWordWrap(True)
            self.lbl_atlas_preview.setMinimumSize(480, 480)
            self.lbl_atlas_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.lbl_atlas_preview.setObjectName("MutedCaption")
            self.lbl_atlas_preview.setStyleSheet("border: 1px solid palette(mid);")
            preview_layout.addWidget(self.lbl_atlas_preview, 1)
            splitter.addWidget(preview_widget)
            # setStretchFactor() only governs how EXTRA space is redistributed
            # on a manual resize -- it has no effect on the splitter's INITIAL
            # split, which Qt derives from each side's own sizeHint(). Left at
            # (1, 1) this always gave the settings column (a tall stack of
            # rows) far more width than the preview needed, squashing the
            # atlas view. Settings stays fixed-width on resize (0); the
            # preview absorbs all extra space (1) -- and the explicit
            # setSizes() call below (after the layout is actually activated,
            # so sizeHint() is accurate) fixes the INITIAL split itself,
            # deliberately biased toward the preview like Unity's own Font
            # Asset Creator (narrower settings column, larger atlas view).
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            self._splitter = splitter
            outer.addWidget(splitter, 1)

            # All three explicitly share the SAME height/autoDefault setting
            # instead of relying on each one's own default QPushButton
            # sizeHint (already reported as visually inconsistent -- see
            # _CONTROL_HEIGHT's own docstring for the measured cause
            # elsewhere in this column). setAutoDefault(False) is a
            # deliberate defensive belt-and-suspenders addition on top of
            # that: none of the three ever calls setDefault(True) already,
            # so nothing here should get Qt's distinct ":default" highlighted-
            # border treatment (build_app_qss's own `QPushButton:default`
            # rule) -- but leaving autoDefault at Qt's own default (True)
            # means whichever button happens to hold keyboard focus when the
            # dialog is shown can silently become "the" default and pick up
            # that same highlighted look with no explicit code decision
            # behind it. Turning it off for all three removes that
            # possibility entirely, so the three can never visually diverge
            # for a reason nothing in this file actually chose.
            btn_row = QHBoxLayout()
            self.btn_generate = QPushButton(tr("Генерировать"))
            self.btn_save = QPushButton(tr("Сохранить"))
            self.btn_cancel = QPushButton(tr("Отмена"))
            for btn in (self.btn_generate, self.btn_save, self.btn_cancel):
                btn.setFixedHeight(_CONTROL_HEIGHT)
                btn.setAutoDefault(False)
            self.btn_generate.clicked.connect(self._on_generate_clicked)
            self.btn_save.setEnabled(False)
            self.btn_save.clicked.connect(self._on_save_clicked)
            self.btn_cancel.clicked.connect(self.reject)
            # The progress bar lives in this row, in the free space between "Сохранить" and "Отмена": as its own
            # row at the bottom of the settings column it needed ~36 px that the (already full) column did not
            # have, so starting a generation squeezed and shifted everything above it. Here it costs no height,
            # and it keeps its slot while hidden so the buttons never move.
            self.progress_bar = QProgressBar()
            self.progress_bar.setFixedHeight(_CONTROL_HEIGHT)
            self.progress_bar.setMinimumWidth(160)
            self.progress_bar.setMaximumWidth(360)
            retain = self.progress_bar.sizePolicy()
            retain.setRetainSizeWhenHidden(True)
            self.progress_bar.setSizePolicy(retain)
            self.progress_bar.hide()
            btn_row.addWidget(self.btn_generate)
            btn_row.addWidget(self.btn_save)
            btn_row.addSpacing(8)
            btn_row.addWidget(self.progress_bar, 1)
            btn_row.addStretch(1)
            btn_row.addWidget(self.btn_cancel)
            outer.addLayout(btn_row)
        else:
            outer.addWidget(settings_widget)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self._on_accept)
            buttons.rejected.connect(self.reject)
            outer.addWidget(buttons)

        self.layout().activate()
        self.adjustSize()
        self._splitter_sized = False
        self._built = True

    def showEvent(self, event):
        super().showEvent(event)
        # Deferred to showEvent rather than done in __init__, same reasoning
        # as TextureZoomDialog's own showEvent override elsewhere in this
        # project: QSplitter.setSizes() only sticks once the splitter has
        # real, on-screen geometry to distribute -- calling it during
        # construction (before the dialog is ever shown) gets silently
        # discarded the moment Qt lays the window out for display. Bias the
        # initial split toward the preview -- settings gets just what its own
        # content needs, the atlas view gets the rest, at roughly a 40:60
        # ratio (settings smaller, preview larger, like Unity's own Font
        # Asset Creator) -- guarded so a later re-show doesn't re-fight
        # whatever width the user has since dragged the handle to.
        if self._show_preview and not self._splitter_sized:
            self._splitter_sized = True
            settings_width = self._splitter.widget(0).sizeHint().width()
            # Real reported request: shrink the window slightly by letting
            # the preview settle at its own fixed minimum (480, still
            # comfortably wider than the settings column, so "left smaller,
            # right larger" still holds) instead of the previous
            # settings_width*1.5, which happened to always exceed that
            # minimum and made the window wider than it needed to be.
            preview_width = self.lbl_atlas_preview.minimumWidth()
            # Grow the WINDOW to the desired total first -- calling
            # setSizes() while the dialog is still at its old (smaller)
            # width just gets the requested sizes clamped back down to fit,
            # and a follow-up activate()/adjustSize() call was found (via
            # direct measurement) to discard the split entirely and recompute
            # from each side's bare sizeHint() again. Resizing the window
            # BEFORE calling setSizes() avoids both problems.
            handle_width = self._splitter.handleWidth()
            self.resize(settings_width + preview_width + handle_width, self.height())
            self._splitter.setSizes([settings_width, preview_width])

    def _font_bytes_for_coverage(self, path: str):
        """The file's bytes, or None if there is no readable file at `path` (nothing to report yet)."""
        try:
            st = os.stat(path)
            stamp = (st.st_mtime_ns, st.st_size)
            if self._coverage_font_cache[:2] != (path, stamp):
                with open(path, "rb") as f:
                    self._coverage_font_cache = (path, stamp, f.read())
            return self._coverage_font_cache[2]
        except (OSError, ValueError):
            return None

    def _update_font_coverage(self):
        text, warning, tip = "", False, ""
        path = self.get_font_path()
        codepoints = self.get_characters()
        font_bytes = self._font_bytes_for_coverage(path) if path and codepoints else None
        if font_bytes is not None:
            try:
                coverage = font_coverage(font_bytes, codepoints)
            except Exception:
                coverage = None
            if coverage is None:
                text = tr("Не удалось определить, какие символы есть в этом шрифте")
            else:
                have, total, missing = coverage
                text, warning = coverage_caption(have, total)
                tip = _missing_tooltip(missing)
        label = self.lbl_font_coverage
        label.setText(text)
        label.setToolTip(tip)
        label.setVisible(bool(text))
        label.setStyleSheet(
            f"color: {theme.get_colors(theme.load_saved_theme_name()).log_warning};" if warning else "")

    def _browse_font(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Выберите файл шрифта"), "", tr("Файлы шрифтов (*.ttf *.otf)"))
        if path:
            self.edit_font_path.setText(path)

    def _reload_presets_combo(self, select_name: str = ""):
        self.combo_presets.blockSignals(True)
        self.combo_presets.clear()
        for name in sorted(CONFIG.sdf_character_presets):
            self.combo_presets.addItem(name)
        if not select_name:
            # Real reported bug: only the character TEXT was ever persisted
            # (CONFIG.sdf_last_characters) — which preset (if any) it came
            # from was not. Reopening the dialog after picking a preset last
            # time correctly restored its characters into the text box, but
            # the combo itself had no memory of the choice and always fell
            # back to "(без пресета)" — a visible mismatch between what the
            # two controls were telling the user. Fixed without adding new
            # persisted state at all: if the text about to be shown exactly
            # matches a saved preset's own text, select THAT preset instead.
            # This is also correct (not just convenient) for the other two
            # callers below — after _save_preset(), the caller already
            # passes its own name explicitly so this branch never runs; after
            # _delete_preset(), re-checking here correctly re-selects a
            # different remaining preset if the current text happens to
            # match one, instead of assuming "no preset" unconditionally.
            # Uses CONFIG.sdf_last_characters at construction time, before
            # edit_characters exists yet — the exact same value the text box
            # is about to be pre-filled with a few lines below in __init__.
            current_text = self.edit_characters.toPlainText() if hasattr(self, "edit_characters") \
                else CONFIG.sdf_last_characters
            for name, preset_text in CONFIG.sdf_character_presets.items():
                if preset_text == current_text:
                    select_name = name
                    break
        # No "(без пресета)" placeholder any more: custom text simply leaves the
        # combo empty (index -1) instead of showing a fake entry.
        idx = self.combo_presets.findText(select_name) if select_name else -1
        self.combo_presets.setCurrentIndex(idx)
        self.combo_presets.blockSignals(False)

    def _on_preset_selected(self, _index: int):
        name = self.combo_presets.currentText()
        if not name:
            return
        text = CONFIG.sdf_character_presets.get(name, "")
        self.edit_characters.setPlainText(text)

    def _save_preset(self):
        text = self.edit_characters.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, tr("Сохранение пресета"), tr("Сначала введите символы для сохранения."))
            return
        current = self.combo_presets.currentText()
        default_name = current
        name, ok = QInputDialog.getText(self, tr("Сохранить пресет"), tr("Название пресета:"), text=default_name)
        name = name.strip()
        if not ok or not name:
            return
        if name in CONFIG.sdf_character_presets:
            reply = QMessageBox.question(
                self, tr("Сохранить пресет"), tr("Пресет «{name}» уже существует. Перезаписать?", name=name),
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        CONFIG.sdf_character_presets[name] = text
        save_persisted_config()
        self._reload_presets_combo(select_name=name)

    def _delete_preset(self):
        name = self.combo_presets.currentText()
        if name not in CONFIG.sdf_character_presets:
            return
        reply = QMessageBox.question(self, tr("Удалить пресет"), tr("Удалить пресет «{name}»?", name=name))
        if reply != QMessageBox.StandardButton.Yes:
            return
        del CONFIG.sdf_character_presets[name]
        save_persisted_config()
        self._reload_presets_combo()

    def _persist_settings(self) -> None:
        """Shared by both the plain-OK path (_on_accept) and the preview
        path's Save (_on_save_clicked) — same fields, same reasoning, no
        longer duplicated between the two."""
        # Real reported bug: an embedded source font is extracted to a fresh
        # TEMP file on every single generate_sdf_font() call (object_actions.py)
        # and unconditionally deleted right after the dialog closes — it's
        # never meant to outlive this dialog. If the user just accepted the
        # pre-filled embedded default without browsing to a different file,
        # persisting THAT path here would save a reference to a file that's
        # about to stop existing. The very next time this dialog opens for a
        # font asset with no embedded source of its own, it would pre-fill
        # from this now-dead path (CONFIG.sdf_last_font_path is exactly the
        # fallback used when there's no embedded default) — and accepting it
        # silently fails EVERY requested character, since msdf-atlas-gen
        # can't load a font file that no longer exists. Skipping the save
        # here for exactly this one case (the field still holds the untouched
        # embedded path) closes it: a real file the user actually chose (via
        # Browse, or the CONFIG fallback from an earlier real choice) is
        # unaffected and still gets remembered as before.
        font_path = self.get_font_path()
        if font_path != self._embedded_font_path:
            CONFIG.sdf_last_font_path = font_path
        CONFIG.sdf_last_characters = self.edit_characters.toPlainText()
        CONFIG.sdf_last_mode = self.get_mode()
        CONFIG.sdf_add_missing = self.settings_panel.remembered_add_missing()   # the raw choices, even
        CONFIG.sdf_last_custom_point_size = self.settings_panel.remembered_point_size()   # while hidden
        CONFIG.sdf_last_custom_pxrange = self.settings_panel.remembered_pxrange()

    def _on_mode_changed(self) -> None:
        # The panel has already shown/hidden its full-replacement-only rows.
        # Deferred one event-loop turn: right after setVisible() the layouts have not recomputed
        # yet, so sizeHint() is still the OLD height (measured: 374 while the real need was 281).
        QTimer.singleShot(0, self._refit_height)

    def _refresh_panel_geometry(self) -> None:
        refresh_nested_geometry(self.settings_panel, self)

    def _refit_height(self) -> None:
        """A shown dialog does not shrink or grow by itself when rows are hidden or shown — it keeps
        its old height and the layout spreads the remaining rows apart (gaps, a stretched character
        box). Refit the HEIGHT to the new content and keep the width the user has. Not needed with the
        preview (the atlas preview on the right sets the height there; the settings column just ends
        earlier), and skipped during construction (the dialog is sized once at the end of __init__)."""
        if self._show_preview or not getattr(self, "_built", False) or not self.isVisible():
            return
        # The panel is a nested widget: its own layout caches a size hint AND the dialog's layout caches
        # the panel's (per-item) — updateGeometry() on the panel is what clears the latter.
        self._refresh_panel_geometry()
        layout = self.layout()
        layout.invalidate()
        layout.activate()
        self.resize(self.width(), max(self.minimumSizeHint().height(), self.sizeHint().height()))

    def _validate(self) -> bool:
        if not self.edit_font_path.text().strip():
            QMessageBox.warning(self, tr("Генерация SDF"), tr("Укажите файл шрифта."))
            return False
        if not self.get_characters():
            QMessageBox.warning(self, tr("Генерация SDF"), tr("Введите хотя бы один символ."))
            return False
        return True

    def _on_accept(self):
        if not self._validate():
            return
        self._persist_settings()
        self.accept()

    # --- preview-mode (single object) generate/save workflow ---

    def _set_generating(self, generating: bool) -> None:
        self.btn_generate.setEnabled(not generating)
        self.btn_generate.setText(tr("Генерация...") if generating else tr("Генерировать"))
        self.progress_bar.setVisible(generating)
        if generating:
            self.progress_bar.setRange(0, 0)  # indeterminate until the first real report

    def _on_generate_clicked(self):
        if not self._validate():
            return
        font_path = self.get_font_path()
        characters = self.get_characters()
        mode = self.get_mode()
        point_size_override = self.get_point_size_override()
        point_size_fit = self.get_point_size_fit()
        match_original_height = self.get_match_height()
        pxrange_override = self.get_pxrange_override()
        add_missing = self.get_add_missing()

        self.btn_save.setEnabled(False)
        self._result = None
        self.txt_summary.setPlainText("")
        self._set_generating(True)

        def work(report_progress):
            return add_characters_to_font_asset(
                self._font_obj, font_path, characters, mode=mode,
                point_size_override=point_size_override, point_size_fit=point_size_fit,
                pxrange_override=pxrange_override, match_original_height=match_original_height,
                include_existing_characters=add_missing,
                progress_cb=lambda i, total: report_progress("", i, max(total, 1)),
                auto_commit=False,
            )

        worker = BackgroundWorker(work, parent=self)
        self._worker = worker
        worker.progress_signal.connect(self._on_generate_progress)
        worker.succeeded_signal.connect(self._on_generate_succeeded)
        worker.failed_signal.connect(self._on_generate_failed)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _on_generate_progress(self, _phase, current, total):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(current)

    def _on_generate_succeeded(self, result):
        self._set_generating(False)
        self._result = result
        self.txt_summary.setPlainText(result.summary_text())
        if result.atlas_preview_image is not None:
            pixmap = pil_to_qpixmap(_sdf_atlas_to_preview_image(result.atlas_preview_image))
            self.lbl_atlas_preview.setPixmap(
                pixmap.scaled(
                    self.lbl_atlas_preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.btn_save.setEnabled(result.added_count > 0)

    def _on_generate_failed(self, message: str):
        self._set_generating(False)
        QMessageBox.warning(self, tr("Генерация SDF"), tr("Не удалось сгенерировать SDF:\n{message}", message=message))

    def _on_worker_finished(self, worker):
        if worker is self._worker:
            self._worker = None
        worker.deleteLater()

    def _on_save_clicked(self):
        if self._result is None or self._result.added_count == 0:
            return
        self._persist_settings()
        self.accept()

    def release_references(self) -> None:
        """Drops what this dialog holds from the loaded Environment — the font
        asset's ObjectReader and the last generation's AddCharactersResult, whose
        deferred commit() closure captures that same ObjectReader (and the parsed
        atlas). The dialog is created with the main window as its Qt parent and is
        never destroyed by Python going out of scope, so without this it outlived
        its one job (generate_sdf_font takes get_result() and is done) for the rest
        of the session, keeping the OLD Environment's objects — and, through
        them, its file mappings — alive across reloads. That is what made a later
        overwrite of an unrelated file fail with "held by this program" (see
        core.save_manager.release_environment(), which now closes those handles
        regardless; this stops the leak itself). Call it after get_result(); the
        dialog is not usable for generation afterwards."""
        self._result = None
        self._font_obj = None

    def get_result(self):
        """The AddCharactersResult from the last successful Generate — only
        meaningful (non-None) after accept() in preview mode; the caller
        (ObjectActionsController.generate_sdf_font) calls .commit() on it."""
        return self._result

    def reject(self):
        # An in-flight generation shouldn't be silently abandoned mid-worker
        # while the dialog itself goes away — the worker's own signals would
        # then fire into a dialog that's already being torn down. Cheap
        # enough to just wait: the worker's own should_cancel isn't wired
        # here since generation is normally quick and the user closing the
        # dialog mid-generate is rare; blocking briefly is simpler and safer
        # than adding a cancellation path for a rare case.
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(30_000)
        super().reject()

    def get_font_path(self) -> str:
        return self.edit_font_path.text().strip()

    # The settings the panel holds (None / False outside the full-replacement mode).
    def get_mode(self) -> str:
        return self.settings_panel.get_mode()

    def get_point_size_override(self) -> Optional[float]:
        return self.settings_panel.get_point_size_override()

    def get_point_size_fit(self) -> bool:
        return self.settings_panel.get_point_size_fit()

    def get_match_height(self) -> bool:
        return self.settings_panel.get_match_height()

    def get_pxrange_override(self) -> Optional[float]:
        return self.settings_panel.get_pxrange_override()

    def get_add_missing(self) -> bool:
        return self.settings_panel.get_add_missing()

    def get_characters(self) -> List[int]:
        text = self.edit_characters.toPlainText()
        seen = set()
        codepoints = []
        for ch in text:
            if ch in ("\n", "\r", "\t"):
                continue
            cp = ord(ch)
            if cp not in seen:
                seen.add(cp)
                codepoints.append(cp)
        return codepoints


class SDFMapImportSettingsDialog(QDialog):
    """Fallback settings for the "sdf_map.txt found in this folder" import path
    (object_actions.py's _import_patches_from_folder, only reached via the
    whole-environment-scoped "Импорт в окружение..." entry point). Cascade:
    a font's own map line -> the map's `default:` line -> this dialog -> built-in
    (core.sdf_map.SdfFallback). Only opened when some target still has mode,
    size or range unset after the first two.

    Deliberately NOT SDFGeneratorDialog itself: that dialog also has a
    font-file field and a character-set textbox, neither of which applies here
    (the font and characters come from the map). The settings themselves are the SAME
    SDFSettingsPanel the generator dialog uses — «Исходный» there resolves per target, to THAT
    font's own current size/sharpness (varies_per_object)."""

    def __init__(self, parent, pair_count: int, target_count: int):
        super().__init__(parent)
        self.setWindowTitle(tr("Импорт по карте SDF"))
        layout = QVBoxLayout(self)

        info = QLabel(tr("Шрифтов для генерации SDF: {target_count}", target_count=target_count))
        info.setWordWrap(True)
        layout.addWidget(info)
        # A plain row, not _make_label_cell(): that is a fixed-width cell sized for the short labels of
        # the settings grid and cut this heading off ("Настройки генер").
        heading = QHBoxLayout()
        heading.addWidget(QLabel(tr("Настройки генерации по умолчанию:")))
        heading.addWidget(_make_help_icon(tr(_MAP_DEFAULTS_HELP)))
        heading.addStretch(1)
        layout.addLayout(heading)

        self.settings_panel = SDFSettingsPanel(varies_per_object=True, add_missing=CONFIG.sdf_add_missing)
        self.settings_panel.mode_changed.connect(self._on_mode_changed)
        layout.addWidget(self.settings_panel)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_mode_changed(self) -> None:
        # (see refresh_nested_geometry for why the panel's geometry is refreshed first)
        refresh_nested_geometry(self.settings_panel, self)
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()  # a shown dialog does not shrink/grow on its own when a row is hidden/shown

    def get_mode(self) -> str:
        return self.settings_panel.get_mode()

    def get_point_size_override(self) -> Optional[float]:
        return self.settings_panel.get_point_size_override()

    def get_point_size_fit(self) -> bool:
        return self.settings_panel.get_point_size_fit()

    def get_match_height(self) -> bool:
        return self.settings_panel.get_match_height()

    def get_pxrange_override(self) -> Optional[float]:
        return self.settings_panel.get_pxrange_override()

    def get_add_missing(self) -> bool:
        return self.settings_panel.get_add_missing()

    def to_fallback(self):
        """What the user chose, as the core.sdf_map.SdfFallback the import cascade ends with."""
        from core.sdf_map import SdfFallback
        return SdfFallback(
            mode=self.get_mode(), point_size=self.get_point_size_override(),
            point_size_fit=self.get_point_size_fit(), match_height=self.get_match_height(),
            pxrange=self.get_pxrange_override(), add_missing=self.get_add_missing(),
        )
