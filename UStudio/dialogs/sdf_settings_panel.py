"""The generation settings shared by the SDF generator dialog (one font, with a live preview) and
the "import by sdf_map.txt" fallback dialog: the mode, font size, edge sharpness and the two
full-replacement checkboxes, together with what they mean for each other (size, sharpness and both
checkboxes apply only to «Полная замена») and the getters that already return "no value" outside it.

One implementation, two hosts — the two dialogs used to build the same rows twice and had drifted
(the map dialog lacked «Добавлять недостающие символы» and cut its heading off)."""

from core.i18n import N_, tr
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.sdf_generator import MODE_ADD, MODE_REPLACE_ALL, MODE_REPLACE_ENTERED
from dialogs.app_settings_dialog import _make_help_icon
from helpers import wrap_tooltip

# Shared by EVERY settings row (not just the two _SizeOverrideGroup ones) so
# every row's control starts at the same X — real reported request: the
# whole settings column should read as one aligned, tight two-column grid,
# matching Unity's own Font Asset Creator layout, not each row sized to its
# own content. Sized from real measured text metrics (Segoe UI 9pt, this
# app's own default UI font) for the actual longest label ("Резкость
# краёв:", 85px) plus its "(?)" icon (13px) and a small 4px gap between them
# — see _make_label_cell()'s own docstring — with a small buffer for
# hinting/DPI variance across machines, deliberately NOT the old, far more
# generous 110/200/90: those were real reported "why is this all so wide"
# feedback, and were sized well beyond what any real label/combo/spin
# content here actually needs.
_SIZE_LABEL_WIDTH = 106
_SIZE_COMBO_WIDTH = 170
_SIZE_SPIN_WIDTH = 76

# Every single-line interactive control in the settings column (line edits,
# combos, spinboxes, buttons) gets this SAME explicit height. Real reported
# issue: left to their own natural sizeHint(), a QComboBox/QLineEdit came out
# at 26px while a QDoubleSpinBox (whose up/down-arrow subcontrols need a
# little more room) came out at 29px and a QPushButton at 28px — a real,
# measured 3px inconsistency that read as "no unified vertical grid" even
# though every row was otherwise column-aligned.
_CONTROL_HEIGHT = 28

# (label shown in the combo, mode constant) — order matters: least destructive
# first, matching the same "safe default" convention this app already uses
# elsewhere (e.g. TextureFormatMode's own match_original-first ordering).
_MODE_OPTIONS = (
    ("Добавление новых символов", MODE_ADD),
    ("Замена + добавление символов", MODE_REPLACE_ENTERED),
    ("Полная замена", MODE_REPLACE_ALL),
)



def _make_label_cell(title: str, help_text: str = "") -> QWidget:
    """A fixed-width "label, then a "(?)" if help_text is given" cell used at
    the START of every settings row, so every row's actual CONTROL starts at
    the same X regardless of which row it is or how long ITS OWN label text
    happens to be — the one thing that makes the settings column read as a
    clean grid instead of a scatter of independently-sized rows (real
    reported comparison against Unity's own Font Asset Creator).

    Real reported bug in an earlier version of this: the "(?)" was reserved
    as a SEPARATE fixed-width widget placed immediately after the label
    widget — which left a visible dead gap before the icon, made of two
    stacked things: (a) whatever width the label's OWN (usually shorter)
    text didn't use inside its fixed-width box, plus (b) the layout's
    default inter-widget spacing between the label widget and the icon
    widget. Packing the label text and the icon into ONE inner layout with a
    small explicit gap between them, THEN fixing THAT container's total
    width, means the icon (when present) sits immediately after its own
    label's actual text every time — no dead space — while every row's cell
    still occupies the identical total width, icon or not."""
    cell = QWidget()
    cell.setFixedWidth(_SIZE_LABEL_WIDTH)
    layout = QHBoxLayout(cell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(QLabel(title))
    if help_text:
        layout.addWidget(_make_help_icon(help_text))
    layout.addStretch(1)
    return cell


_PXRANGE_HELP = (
    N_("Насколько резкими или мягкими получаются края букв.\n\n"
    "Меньшее значение — более резкие, менее сглаженные края (подходит для пиксельных "
    "и ретро-шрифтов). Большее — более мягкий, плавный переход.\n\n"
    "Доступно только в режиме «Полная замена».")
)

_MAP_DEFAULTS_HELP = (
    N_("Эти настройки применяются только к тем шрифтам, для которых они не заданы в файле sdf_map.txt "
    "(ни в самой строке шрифта, ни в строке «default:»).\n\n"
    "Всё, что указано в файле, имеет приоритет над выбранным здесь.")
)

_MODE_HELP = (
    N_("Добавление новых символов — пропускает символы, уже присутствующие в шрифте, "
    "добавляет только новые. Ничего из существующего не трогает и не пересобирает.\n\n"
    "Замена + добавление символов — пересобирает указанные символы, "
    "если они уже есть в шрифте — иначе добавляет (не трогая остальные существующие символы).\n\n"
    "Полная замена — удаляет все символы в SDF шрифте, генерируя "
    "с нуля. Размер текстуры при этом подбирается автоматически, и увеличивается, если символы не помещаются.")
)

_SIZE_HELP = (
    N_("Размер букв при создании.\n\n"
    "«Исходный» — как у шрифта сейчас. «Указать» — свой размер.\n\n"
    "«Вписать в текстуру» — самый крупный размер, при котором все символы помещаются в текущий "
    "атлас. А если не помещаются, текстура увеличивается\n\n"
    "Доступно только в режиме «Полная замена».")
)

_ADD_MISSING_HELP = (
    N_("Добавляет в пресет недостающие символы из SDF шрифтов, чтобы избежать квадратов вместо букв. "
    "Если в векторном шрифте какого-то символа не окажется, он будет пропущен.\n\n"
    "Доступно только в режиме «Полная замена».")
)

_MATCH_HEIGHT_HELP = (
    N_("Подбирает масштаб так, чтобы новые символы выглядели в игре такой же высоты, как прежние. "
    "Полезно, когда новый шрифт заметно мельче или крупнее. "
    "Размер текстуры это не меняет. Заодно берётся высота строки из оригинала, а добавочный "
    "интервал полужирного текста отключается, чтобы строки не становились шире "
    "обычных и не переносились.")
)


class _SizeOverrideGroup(QWidget):
    """One "[label:] [Как в оригинале (N) ▾]  <input, only when 'Свой'>" row —
    used twice (font size, SDF spread), same shape both times, so built once
    here instead of duplicating the combo-plus-spinbox wiring.

    One compact row (a combo box, not two radio-button rows) per real
    feedback against the first version of this dialog: modeled directly on
    Unity's own Font Asset Creator, whose "Sampling Point Size" is exactly
    this shape — a dropdown (Auto Sizing / Custom Size) that only shows a
    numeric field once "Custom Size" is picked, not two permanently-visible
    rows. The input field is genuinely SHOWN/HIDDEN (not just enabled/
    disabled) on selection change, matching that same reference behavior.

    `current_value`: the font asset's OWN existing value, for both the
    "Как в оригинале (N)" combo item text AND as the spinbox's own fallback
    pre-fill. Two genuinely different reasons this can be None, distinguished
    by `original_available`:
    - Single object, value genuinely unresolvable (original_available=False)
      — see core.sdf_generator.resolve_current_point_size()'s own docstring
      for a real case: an unbaked TMP "- Fallback" companion asset. The
      "Как в оригинале" combo item isn't offered at all here — there's
      nothing to match, and a real value is required to proceed, not a
      silent arbitrary default.
    - Batch mode, N DIFFERENT font assets each with their OWN value
      (original_available=True, current_value=None) — "Как в оригинале"
      stays fully selectable and meaningful (each font keeps using ITS OWN
      value, exactly like the existing character-set/mode settings already
      apply uniformly while size doesn't have to); there's just no single
      number to show in the item text, so it reads as plain "Как в
      оригинале" with no number — the same text used when a single object's
      value just happens to be unavailable-but-still-selectable.

    `last_custom_value`: pre-fills the spinbox so re-entering the same custom
    number for a following font asset in the same session isn't required —
    see config.py's own sdf_last_custom_point_size/sdf_last_custom_pxrange
    docstring for why this is session-only and never changes which combo
    item starts selected.

    `supports_fit` (only ever True for the Font Size instance, never SDF Spread): adds a third
    item, "Вписать в текстуру" (the largest size that fits the font's current texture; the
    texture grows instead of the glyphs shrinking below the original size — see
    core.sdf_generator._fit_to_texture). An explicit item of its own, not a side effect of
    leaving "Исходный" selected, so "Исходный" always means the font's own current value. The
    whole group is hidden outside the "Полная замена" mode, the only one where size matters."""

    _CUSTOM_LABEL = N_("Указать")
    _FIT_LABEL = N_("Вписать в текстуру")

    def __init__(
        self, title: str, current_value: Optional[float], last_custom_value: Optional[float],
        spin_range: tuple, spin_decimals: int, spin_suffix: str, help_text: str = "",
        original_available: bool = True, supports_fit: bool = False, parent=None,
    ):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        outer.addWidget(_make_label_cell(f"{title}:", help_text))

        self._original_available = original_available
        self._supports_fit = supports_fit

        self.combo = QComboBox()
        self.combo.setFixedWidth(_SIZE_COMBO_WIDTH)
        self.combo.setFixedHeight(_CONTROL_HEIGHT)
        if original_available:
            if current_value is not None:
                # Unit included next to the number (real reported request) —
                # spin_suffix is the SAME unit the custom field below uses
                # (" pt"/" px"), so the two rows never disagree about units.
                # Formatted with the SAME decimals as spin_custom itself
                # (not `:g`, which strips trailing zeros) — real reported
                # bug: a real font's baked size is routinely a whole number
                # (90.0, since Unity's own Font Asset Creator UI has always
                # only accepted whole numbers for this field), and `:g`
                # rendered that as a bare "90" right next to a spinbox that
                # always shows one decimal place ("90,0") the instant you
                # switch to "Указать" — reading as "this is an integer
                # field" even though m_FaceInfo.m_PointSize's own TypeTree
                # schema is a genuine float (confirmed against a real
                # fixture). Always showing the decimal here matches the
                # spinbox's own presentation and makes the field's real
                # type unambiguous regardless of what the baked value
                # happens to be.
                original_text = tr("Исходный — {value}", value=f"{current_value:.{spin_decimals}f}{spin_suffix}")
            else:
                # Covers both "batch mode, no single shared value to show"
                # (varies_per_object=True) and the plain single-object case
                # with nothing to display — real reported feedback: spelling
                # out "each font has its own value" here was unnecessary and
                # already obvious from context, so both collapse to the same
                # plain label now instead of a separate explanatory variant.
                original_text = tr("Исходный")
            self.combo.addItem(original_text)
        self.combo.addItem(tr(self._CUSTOM_LABEL))
        if supports_fit:
            self.combo.addItem(tr(self._FIT_LABEL))
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        outer.addWidget(self.combo)

        self.spin_custom = QDoubleSpinBox()
        self.spin_custom.setFixedWidth(_SIZE_SPIN_WIDTH)
        self.spin_custom.setFixedHeight(_CONTROL_HEIGHT)
        self.spin_custom.setRange(*spin_range)
        self.spin_custom.setDecimals(spin_decimals)
        if spin_suffix:
            self.spin_custom.setSuffix(spin_suffix)
        self.spin_custom.setValue(
            last_custom_value if last_custom_value is not None else (current_value or spin_range[0])
        )
        # Keeps this row's own total width CONSTANT whether the spinbox is
        # shown or hidden — real reported issue: a hidden widget's layout
        # space collapses by default in Qt, so toggling the combo used to
        # change how much horizontal room these settings needed, which (being
        # the left pane of a QSplitter next to the atlas preview) shifted the
        # splitter boundary and visibly resized the preview area on the right
        # every time "Свой"/"Как в оригинале" was picked.
        spin_size_policy = self.spin_custom.sizePolicy()
        spin_size_policy.setRetainSizeWhenHidden(True)
        self.spin_custom.setSizePolicy(spin_size_policy)
        outer.addWidget(self.spin_custom)
        outer.addStretch(1)

        self.combo.setCurrentIndex(0)
        self._on_combo_changed(0)

    def _is_custom_selected(self) -> bool:
        return self.combo.currentText() == tr(self._CUSTOM_LABEL)

    def _on_combo_changed(self, _index: int) -> None:
        self.spin_custom.setVisible(self._is_custom_selected())

    def is_fit_selected(self) -> bool:
        return self._supports_fit and self.combo.currentText() == tr(self._FIT_LABEL)

    def get_override(self) -> Optional[float]:
        """None means "Исходный" OR "Вписать в текстуру" (see is_fit_selected() for telling the two
        apart) — see add_characters_to_font_asset()'s point_size_override/point_size_fit docstring."""
        return self.spin_custom.value() if self._is_custom_selected() else None


def refresh_nested_geometry(widget: QWidget, top: QWidget) -> None:
    """After rows inside `widget` were shown/hidden, make the size hints of every level between it and
    `top` (a dialog) current. A nested widget's layout caches a size hint, and each parent layout caches
    that widget's — a plain invalidate() on `top` alone leaves the stale hints, and a dialog sized from
    them (adjustSize()/resize(sizeHint())) does not shrink. Hiding rows that sit directly in the dialog's
    own layout never needed this."""
    w = widget
    while w is not None and w is not top:
        layout = w.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        w.updateGeometry()
        w = w.parentWidget()


class SDFSettingsPanel(QWidget):
    """Mode + font size + edge sharpness + «подогнать высоту» + «добавлять недостающие символы».

    `varies_per_object`: the settings apply to several font assets, each with its own current size
    and sharpness — «Исходный» then means "each font's own" and shows no number (see
    _SizeOverrideGroup). `mode_changed` is emitted after the visibility of the full-replacement-only
    rows has been updated, so a host dialog can refit its height."""

    mode_changed = pyqtSignal()

    def __init__(
        self, current_point_size: Optional[float] = None, current_pxrange: Optional[float] = None,
        varies_per_object: bool = False, mode: str = MODE_ADD,
        last_custom_point_size: Optional[float] = None, last_custom_pxrange: Optional[float] = None,
        add_missing: bool = True, parent=None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        mode_row = QHBoxLayout()
        # Real reported issue: choosing "Полная замена" auto-sizes the atlas to tightly fit the requested
        # characters instead of reusing this font asset's own old atlas dimensions (see
        # core.sdf_generator's own MODE_REPLACE_ALL handling) -- and nothing in the UI said so. A "(?)"
        # hint here, matching group_pxrange, is simpler and more honest than a separate "autosize"
        # toggle, since this behavior isn't optional -- it's what "Полная замена" does.
        mode_row.addWidget(_make_label_cell(tr("Режим:"), tr(_MODE_HELP)))
        self.combo_mode = QComboBox()
        self.combo_mode.setFixedHeight(_CONTROL_HEIGHT)
        for text_key, _mode in _MODE_OPTIONS:
            self.combo_mode.addItem(tr(text_key), _mode)
        self.combo_mode.setCurrentIndex(
            next((i for i, (_label, m) in enumerate(_MODE_OPTIONS) if m == mode), 0))
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.combo_mode, 1)
        layout.addLayout(mode_row)

        self.group_point_size = _SizeOverrideGroup(
            tr("Размер шрифта"), current_point_size, last_custom_point_size,
            spin_range=(1.0, 4096.0), spin_decimals=1, spin_suffix=" pt", help_text=tr(_SIZE_HELP),
            original_available=varies_per_object or current_point_size is not None, supports_fit=True,
        )
        layout.addWidget(self.group_point_size)

        self.group_pxrange = _SizeOverrideGroup(
            tr("Резкость краёв"), current_pxrange, last_custom_pxrange,
            spin_range=(0.5, 128.0), spin_decimals=1, spin_suffix=" px", help_text=tr(_PXRANGE_HELP),
            original_available=varies_per_object or current_pxrange is not None,
        )
        layout.addWidget(self.group_pxrange)

        self.chk_match_height = QCheckBox(tr("Подогнать высоту букв под оригинал"))
        self.chk_match_height.setChecked(True)
        self.chk_match_height.setToolTip(wrap_tooltip(tr(_MATCH_HEIGHT_HELP)))
        layout.addWidget(self.chk_match_height)

        self.chk_add_missing = QCheckBox(tr("Добавлять недостающие символы из SDF шрифта"))
        self.chk_add_missing.setChecked(add_missing)
        self.chk_add_missing.setToolTip(wrap_tooltip(tr(_ADD_MISSING_HELP)))
        layout.addWidget(self.chk_add_missing)

        self._update_visibility()

    # --- what is shown ---

    def _update_visibility(self) -> None:
        # Size, sharpness and the two checkboxes apply only to a full replacement: in every other mode
        # new glyphs join existing ones baked at the asset's own size and sharpness.
        full = self.get_mode() == MODE_REPLACE_ALL
        self.group_point_size.setVisible(full)
        self.group_pxrange.setVisible(full)
        self.chk_match_height.setVisible(full)
        self.chk_add_missing.setVisible(full)

    def _on_mode_changed(self, _index: int) -> None:
        self._update_visibility()
        self.mode_changed.emit()

    # --- values (None / False outside the full-replacement mode, where the rows are hidden and may
    # still hold a stale choice) ---

    def get_mode(self) -> str:
        return _MODE_OPTIONS[self.combo_mode.currentIndex()][1]

    def _full(self) -> bool:
        return self.get_mode() == MODE_REPLACE_ALL

    def get_point_size_override(self) -> Optional[float]:
        return self.group_point_size.get_override() if self._full() else None

    def get_point_size_fit(self) -> bool:
        """True only when "Вписать в текстуру" is selected AND the mode is full replacement — see
        add_characters_to_font_asset()'s point_size_fit docstring."""
        return self._full() and self.group_point_size.is_fit_selected()

    def get_match_height(self) -> bool:
        return self._full() and self.chk_match_height.isChecked()

    def get_pxrange_override(self) -> Optional[float]:
        """None outside the full-replacement mode (the sharpness is an atlas-wide parameter, see _PXRANGE_HELP)."""
        return self.group_pxrange.get_override() if self._full() else None

    def get_add_missing(self) -> bool:
        return self._full() and self.chk_add_missing.isChecked()

    # --- what to remember between openings (the raw choices, whatever mode is selected now) ---

    def remembered_add_missing(self) -> bool:
        return self.chk_add_missing.isChecked()

    def remembered_point_size(self) -> Optional[float]:
        return self.group_point_size.get_override()

    def remembered_pxrange(self) -> Optional[float]:
        return self.group_pxrange.get_override()
