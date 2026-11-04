"""Day/night theme system for the app.

Root cause of the light-theme readability bug: main.py's log() colors and
helpers.py's JsonHighlighter colors were hardcoded literal hex values tuned
against a dark background (VS Code Dark+-style: #d4d4d4 text, #CE9178 strings,
etc.) — those are QTextCharFormat/HTML colors, which Qt applies exactly as given
regardless of the active QPalette or OS theme. They looked fine only as long as
the surrounding QTextEdit backgrounds happened to also be dark (e.g. Qt
auto-detecting a dark Windows theme); once the OS/Qt palette went light, the
backgrounds turned white but these literal colors didn't change with them,
producing washed-out, low-contrast text.

The fix is two curated, independent palettes (not OS auto-detection) covering
BOTH the QPalette (for native widget backgrounds/text) AND the literal colors
used outside the palette system (log() HTML, JsonHighlighter) — kept in one
place so the two families of color never drift out of sync with each other
again like they did here.
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPalette, QPixmap, QPolygonF
from PyQt6.QtWidgets import QApplication
from app_settings import app_settings

_SETTINGS_KEY = "theme"
_DEFAULT_THEME = "dark"  # matches the color values this app's UI was originally tuned for


@dataclass(frozen=True)
class ThemeColors:
    name: str
    icon: str  # shown on the toggle button

    # QPalette roles — these drive every native widget's background/text automatically
    # (table, buttons, menus, text edits, ...) as long as the app style is "Fusion"
    # (see apply_theme's comment on why the native Windows11 style doesn't fully honor a
    # custom QPalette).
    window: str
    window_text: str
    base: str
    alternate_base: str
    text: str
    button: str
    button_text: str
    highlight: str
    highlighted_text: str
    tooltip_base: str
    tooltip_text: str
    disabled_text: str

    # Outside the QPalette system entirely — consumed directly by APP_QSS below
    # (and by a couple of widgets that need one literal color inline, e.g. a
    # hover/pressed state QPalette has no dedicated role for).
    border: str
    surface: str  # a step above `base` — panel/tab backgrounds that need to read
    # as slightly "raised" against the base content area behind them
    accent_hover: str
    accent_pressed: str
    scrollbar_handle: str
    scrollbar_handle_hover: str

    # main.py's log() — literal HTML colors, outside the QPalette system
    log_info: str
    log_warning: str
    log_error: str

    # helpers.py's JsonHighlighter — literal QTextCharFormat colors, also outside QPalette
    json_string: str
    json_key: str
    json_number: str
    json_keyword: str
    # A distinct hue from json_keyword for Unity REFERENCE types (PPtr<...> — a
    # pointer to another object, conceptually different from an ordinary value
    # type like int/string/vector) — used by ObjectStructureTree/TypedDumpHighlighter
    # so a PPtr field visually stands out from a plain typed field at a glance,
    # not just via the tree's existing bold-whole-line treatment for PPtr rows.
    json_reference_type: str


DARK = ThemeColors(
    name="dark",
    icon="🌙",
    window="#16171d",
    window_text="#e4e4ea",
    base="#1c1d24",
    alternate_base="#23242c",
    text="#e4e4ea",
    button="#2a2b35",
    button_text="#e4e4ea",
    highlight="#6366f1",
    highlighted_text="#ffffff",
    tooltip_base="#23242c",
    tooltip_text="#e4e4ea",
    disabled_text="#63636e",
    border="#2f303b",
    surface="#1f2028",
    accent_hover="#7678f5",
    accent_pressed="#5254d6",
    scrollbar_handle="#3a3b47",
    scrollbar_handle_hover="#4a4b5a",
    log_info="#d4d4d4",
    log_warning="#d7ba7d",
    log_error="#f14c4c",
    json_string="#CE9178",
    json_key="#9CDCFE",
    json_number="#B5CEA8",
    json_keyword="#569CD6",
    json_reference_type="#4EC9B0",  # VS Code Dark+'s own class/type-name teal
)

LIGHT = ThemeColors(
    name="light",
    icon="☀️",
    window="#f5f5f9",
    window_text="#1c1c24",
    base="#ffffff",
    alternate_base="#f0f0f6",
    text="#1c1c24",
    button="#eceef4",
    button_text="#1c1c24",
    highlight="#4f46e5",  # a touch deeper than DARK's accent — better contrast on white
    highlighted_text="#ffffff",
    tooltip_base="#ffffff",
    tooltip_text="#1c1c24",
    disabled_text="#9b9ba6",
    border="#dcdce6",
    surface="#fbfbfd",
    accent_hover="#6a61ea",
    accent_pressed="#4038c2",
    scrollbar_handle="#d3d3de",
    scrollbar_handle_hover="#bcbcca",
    log_info="#1e1e1e",
    log_warning="#8a6a00",
    log_error="#c42b1c",
    json_string="#a31515",
    json_key="#0451a5",
    json_number="#098658",
    json_keyword="#0000ff",
    json_reference_type="#267f99",  # VS Code Light+'s own class/type-name teal
)

THEMES = {"dark": DARK, "light": LIGHT}

# Shared by main.py's main object table and CabBrowserDialog's entry table — both
# hit the same two Qt/Windows11-style artifacts on a row-selectable QTableView:
# a dotted/colored current-cell outline overlapping the text, and (Windows11 style
# specifically) a thick accent bar QWindows11Style draws on the left edge of a
# selected item — meant for single-column lists like File Explorer, but drawn PER
# CELL on a multi-column view, cutting into every column's text. Any ::item
# selector switches Qt to CSS-based item painting instead of the native per-style
# delegate, which drops both.
#
# A function of the CURRENT theme's colors, not a fixed string: DARK and LIGHT
# used to share one literal accent color, so a single constant built from DARK's
# was harmless either way — now that the modernized palette gives each theme its
# own accent (better contrast on light backgrounds), a fixed reference to DARK's
# would paint the wrong color under the light theme. Callers re-apply this
# whenever the active theme changes, same as apply_theme_colors() elsewhere.
def table_selection_qss(colors: ThemeColors) -> str:
    return f"""
        QTableView {{ outline: 0; }}
        QTableView::item:selected {{
            background-color: {colors.highlight};
            color: white;
            border: none;
        }}
    """


# What the user picked in Настройки -> Тема: one of the two palettes, or SYSTEM = whichever of them matches
# Windows' own light/dark setting (followed live, see MainWindow._on_system_color_scheme_changed). Still the
# two curated palettes either way — "system" only chooses between them.
SYSTEM = "system"
THEME_CHOICES = ("dark", "light", SYSTEM)


def load_theme_choice() -> str:
    choice = app_settings().value(_SETTINGS_KEY, _DEFAULT_THEME)
    return choice if choice in THEME_CHOICES else _DEFAULT_THEME


def save_theme_choice(choice: str) -> None:
    app_settings().setValue(_SETTINGS_KEY, choice if choice in THEME_CHOICES else _DEFAULT_THEME)


def system_theme_name() -> str:
    """"light" or "dark" as Windows is set (Qt's style hints); the default palette when it cannot tell."""
    app = QApplication.instance()
    if app is None:
        return _DEFAULT_THEME
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Light:
        return "light"
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    return _DEFAULT_THEME


def resolve_theme_name(choice: str) -> str:
    """The palette a choice stands for: "dark"/"light" as they are, SYSTEM -> the system's one."""
    if choice == SYSTEM:
        return system_theme_name()
    return choice if choice in THEMES else _DEFAULT_THEME


def load_saved_theme_name() -> str:
    """The palette to use now ("dark" or "light") — the saved choice, with SYSTEM resolved."""
    return resolve_theme_name(load_theme_choice())


def get_colors(name: str) -> ThemeColors:
    return THEMES.get(name, DARK)


def _build_palette(colors: ThemeColors) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(colors.window))
    p.setColor(QPalette.ColorRole.WindowText, QColor(colors.window_text))
    p.setColor(QPalette.ColorRole.Base, QColor(colors.base))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(colors.alternate_base))
    p.setColor(QPalette.ColorRole.Text, QColor(colors.text))
    p.setColor(QPalette.ColorRole.Button, QColor(colors.button))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(colors.button_text))
    p.setColor(QPalette.ColorRole.Highlight, QColor(colors.highlight))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(colors.highlighted_text))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors.tooltip_base))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(colors.tooltip_text))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(colors.disabled_text))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(colors.disabled_text))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(colors.disabled_text))
    # Real reported bug: a QTextEdit/QLineEdit's PLACEHOLDER text (shown when
    # empty — task_queue_dialog.py's "Журнал" tab is the reported case, but
    # any placeholder anywhere in the app would have the same problem)
    # rendered nearly invisible in dark mode — confirmed via direct pixel
    # measurement (lightness ~40-53 against a ~29 background), NOT literally
    # pure black but close enough to read as "invisible" against a dark
    # background. Root cause: QTextEdit's own QSS rule below sets
    # background-color/border/padding but deliberately never sets `color`
    # (regular typed/inserted text already renders correctly from this
    # palette's own Text role, set above — confirmed by a separate direct
    # test with real content) — but Qt's placeholder-color computation for a
    # STYLED widget (one with any applicable stylesheet rule at all) doesn't
    # reliably fall back to blending THIS custom palette's Text/Base the way
    # an unstyled widget would; leaving PlaceholderText unset here meant it
    # fell back to something close to Qt's own factory-default (dark) value
    # regardless. Setting it explicitly, once, app-wide fixes this at the
    # root instead of special-casing task_queue_dialog.py's one reported
    # widget — reusing disabled_text (the same muted-but-legible color
    # #MutedCaption already uses elsewhere in this app for secondary/hint
    # text) is the right semantic match: a placeholder should read as
    # "dimmer than real content" without being unreadable.
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors.disabled_text))
    return p


_ARROW_ICON_DIR = Path(tempfile.gettempdir()) / "ustudio_theme_arrows"


def _write_arrow_icon(color_hex: str, direction: str) -> str:
    """Draws a small solid-color chevron (procedural, same "draw into a
    QPixmap" pattern as preview_icons.py/type_icons.py/menu_icons.py — no
    icon assets exist anywhere in this project) and saves it to a per-color
    temp file, returning a forward-slash path usable in a QSS url().

    Needed because QComboBox/QAbstractSpinBox below get styled with
    border/background/padding — the moment ANY box-model QSS property
    targets these widgets, Qt switches them to the CSS rendering path
    entirely, which does NOT fall back to Fusion's native arrow drawing for
    the drop-down/up/down-button subcontrols: confirmed by a direct
    before/after screenshot of a real QComboBox/QSpinBox under this exact
    stylesheet — the arrows were rendering as nothing at all (a blank
    reserved area), not just low-contrast. QSS's `image:` property needs an
    actual file, not inline pixmap data, hence writing to a temp file rather
    than embedding a data: URI (which Qt's QSS parser doesn't reliably
    support across versions)."""
    _ARROW_ICON_DIR.mkdir(parents=True, exist_ok=True)
    path = _ARROW_ICON_DIR / f"{direction}_{color_hex.lstrip('#')}.png"
    if not path.exists():
        size = 12
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color_hex))
        if direction == "down":
            points = [QPointF(2.5, 4.5), QPointF(9.5, 4.5), QPointF(6, 8.5)]
        else:  # "up"
            points = [QPointF(2.5, 7.5), QPointF(9.5, 7.5), QPointF(6, 3.5)]
        painter.drawPolygon(QPolygonF(points))
        painter.end()
        pixmap.save(str(path))
    return str(path).replace("\\", "/")


def scrollbar_arrows_qss(colors: ThemeColors) -> str:
    """A vertical scroll bar WITH up/down arrow buttons, for a widget's own setStyleSheet() — the app-wide rules
    below hide them everywhere (add-line/sub-line 0 px); the «Сведения» lists show them (user request: long
    lists of references). Same look otherwise; the arrows use the combo/spin-box arrow images."""
    up = _write_arrow_icon(colors.text, "up")
    down = _write_arrow_icon(colors.text, "down")
    return f"""
        QScrollBar:vertical {{ margin: 15px 2px 15px 2px; }}
        QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {{
            subcontrol-origin: margin; height: 14px; width: 12px; border: none; border-radius: 3px;
            background: transparent;
        }}
        QScrollBar::sub-line:vertical {{ subcontrol-position: top; }}
        QScrollBar::add-line:vertical {{ subcontrol-position: bottom; }}
        QScrollBar::sub-line:vertical:hover, QScrollBar::add-line:vertical:hover {{
            background: {colors.scrollbar_handle};
        }}
        QScrollBar::up-arrow:vertical {{ image: url({up}); width: 10px; height: 10px; }}
        QScrollBar::down-arrow:vertical {{ image: url({down}); width: 10px; height: 10px; }}
    """


def build_app_qss(colors: ThemeColors) -> str:
    """App-wide stylesheet layered on top of the Fusion QPalette above — the
    palette alone gives every widget correct, theme-aware COLORS, but Fusion's own
    default shapes (square corners, flat 3D-ish button bevels, thick native
    scrollbars, plain tab strip) are what actually read as dated. This is the
    "modern redesign" pass: rounded corners, slimmer scrollbars, a flatter tab
    strip with an accent underline, and the #AppHeader/#AppTitle bar from
    main.py's init_ui(). Inspired by the clean, flat look of modern Unity-modding
    tools like UABEANext (a completely different UI toolkit — Avalonia/Fluent, not
    Qt/Fusion) without copying any of its actual QSS/XAML, since none exists to
    copy in the first place; this is an independent, from-scratch pass tuned to
    this app's own ThemeColors."""
    arrow_down = _write_arrow_icon(colors.text, "down")
    arrow_up = _write_arrow_icon(colors.text, "up")
    return f"""
        QPushButton {{
            background-color: {colors.button};
            border: 1px solid {colors.border};
            border-radius: 6px;
            padding: 5px 14px;
        }}
        QPushButton:hover {{ background-color: {colors.surface}; border-color: {colors.highlight}; }}
        QPushButton:pressed {{ background-color: {colors.alternate_base}; }}
        QPushButton:disabled {{ color: {colors.disabled_text}; border-color: {colors.border}; }}
        QPushButton:default {{ border-color: {colors.highlight}; }}
        /* icon-only buttons of a narrow gui_common.AdaptiveRow (the Details tab, the tree toolbar) */
        QPushButton[compact="true"] {{ padding: 5px 7px; }}
        /* a split button (Details tab -> Export ▾): two buttons joined into one control */
        QPushButton#SplitMain {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
        QPushButton#SplitArrow {{
            border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: none; padding: 5px 5px;
        }}

        QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox {{
            background-color: {colors.base};
            border: 1px solid {colors.border};
            border-radius: 6px;
            padding: 3px 6px;
            selection-background-color: {colors.highlight};
        }}
        QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {{ border-color: {colors.highlight}; }}

        /* The generic QAbstractSpinBox/QComboBox rule above styles border/
        background/padding on these widgets, which switches Qt off Fusion's
        native arrow rendering for their button subcontrols entirely — without
        these, the drop-down/up/down buttons render as a blank reserved area,
        not just a low-contrast arrow (confirmed via a direct screenshot before
        this fix). image: needs a real file — see _write_arrow_icon()'s
        docstring for why these are generated to a temp file instead of an
        inline data URI. */
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox::down-arrow {{ image: url({arrow_down}); width: 10px; height: 10px; }}
        QComboBox::down-arrow:disabled {{ image: none; }}

        QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
            subcontrol-origin: border;
            width: 16px;
            border-left: 1px solid {colors.border};
            background: transparent;
        }}
        QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
        QAbstractSpinBox::down-button {{
            subcontrol-position: bottom right;
            border-bottom-right-radius: 6px;
            border-top: 1px solid {colors.border};
        }}
        QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {colors.surface}; }}
        QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{ background: {colors.alternate_base}; }}
        QAbstractSpinBox::up-arrow {{ image: url({arrow_up}); width: 8px; height: 8px; }}
        QAbstractSpinBox::down-arrow {{ image: url({arrow_down}); width: 8px; height: 8px; }}
        QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}

        QTableView, QTreeView, QListView {{
            background-color: {colors.base};
            alternate-background-color: {colors.alternate_base};
            border: 1px solid {colors.border};
            border-radius: 6px;
            gridline-color: {colors.border};
        }}
        QHeaderView::section {{
            background-color: {colors.surface};
            color: {colors.text};
            border: none;
            border-bottom: 1px solid {colors.border};
            border-right: 1px solid {colors.border};
            padding: 4px 6px;
        }}

        QTabWidget::pane {{ border: 1px solid {colors.border}; border-radius: 6px; top: -1px; }}
        QTabBar::tab {{
            background-color: transparent;
            color: {colors.disabled_text};
            padding: 6px 16px;
            margin-right: 2px;
            border-bottom: 2px solid transparent;
        }}
        QTabBar::tab:selected {{ color: {colors.text}; border-bottom: 2px solid {colors.highlight}; }}
        QTabBar::tab:hover:!selected {{ color: {colors.text}; }}

        QMenuBar {{ background-color: {colors.window}; border-bottom: 1px solid {colors.border}; }}
        QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 4px; }}
        QMenuBar::item:selected {{ background-color: {colors.surface}; }}
        QMenu {{ background-color: {colors.surface}; border: 1px solid {colors.border}; border-radius: 6px; padding: 4px; icon-size: 16px; }}
        /* padding-left tight (8px, not 20px) and icon-size pinned to match
        menu_icons.py's actual 16x16 pixmaps exactly — without icon-size set
        explicitly, Qt reserved a wider icon column than 16px (its own
        default toolbar-icon-sized metric), leaving the checkbox/radio icon
        flush against the menu's left edge with a large dead gap before the
        text (real reported visual bug, confirmed via a direct screenshot
        comparison before/after this fix). */
        QMenu::item {{ padding: 5px 20px 5px 12px; border-radius: 4px; }}
        /* Real reported bug: the icon/text gap above was only actually fixed for
        an UNSELECTED item — hovering a checkable item reintroduced the exact
        same large gap. Root cause: a Qt style sheet pseudo-state rule doesn't
        inherit properties left unset from the base (non-pseudo) rule for the
        same selector the way real CSS cascading would — padding must be
        repeated here explicitly, or Qt falls back to its own built-in default
        padding for the :selected state specifically, wider than the 8px set
        above. Confirmed via a direct before/after screenshot with an item
        actively hovered, not just the resting state. */
        QMenu::item:selected {{
            background-color: {colors.highlight};
            color: {colors.highlighted_text};
            padding: 5px 20px 5px 12px;
            border-radius: 4px;
        }}
        QMenu::separator {{ height: 1px; background: {colors.border}; margin: 4px 6px; }}

        /* Checkable menu items (View/Settings toggles, the SDF/standard mode
        radio pair) get their checkbox-with-checkmark visual from a real icon
        instead (menu_icons.py, set via QAction.setIcon() and swapped on the
        action's own toggled signal — see main.py's _register_checkable_icon())
        — styling this indicator directly can only ever fill it solid on
        :checked with no way to draw an actual checkmark glyph without an
        image asset. Zeroed out here so Qt's own native indicator box doesn't
        additionally render next to that icon. */
        QMenu::indicator {{ width: 0px; height: 0px; }}
        /* Real reported regression: the blanket zero-out above (needed for the
        icon-based checkable menus just described) also silently wiped out the
        native checkbox for every OTHER checkable menu action that has no icon
        of its own — confirmed the only such case in this app is the column-
        visibility header menu (main.py's _show_column_visibility_menu: plain
        action.setCheckable(True), no _register_checkable_icon() call), whose
        checkboxes disappeared entirely with nothing to replace them. Scoped
        back on via objectName (menu.setObjectName("columnVisibilityMenu")) —
        a more specific selector, so it wins over the bare QMenu::indicator
        rule above regardless of declaration order. 16px matches this menu's
        own icon-size (set on the QMenu rule above) rather than an arbitrary
        number. */
        QMenu#columnVisibilityMenu::indicator {{ width: 16px; height: 16px; }}

        QProgressBar {{
            background-color: {colors.base};
            border: 1px solid {colors.border};
            border-radius: 6px;
            text-align: center;
        }}
        QProgressBar::chunk {{ background-color: {colors.highlight}; border-radius: 5px; }}

        QSplitter::handle {{ background-color: {colors.border}; }}
        QSplitter::handle:hover {{ background-color: {colors.highlight}; }}
        QSplitter::handle:horizontal {{ width: 2px; }}
        QSplitter::handle:vertical {{ height: 2px; }}

        QScrollBar:vertical {{ background: transparent; width: 16px; margin: 2px; }}
        QScrollBar::handle:vertical {{
            background: {colors.scrollbar_handle};
            border-radius: 6px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {colors.scrollbar_handle_hover}; }}
        QScrollBar:horizontal {{ background: transparent; height: 16px; margin: 2px; }}
        QScrollBar::handle:horizontal {{
            background: {colors.scrollbar_handle};
            border-radius: 6px;
            min-width: 24px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {colors.scrollbar_handle_hover}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; border: none; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

        QToolTip {{
            background-color: {colors.tooltip_base};
            color: {colors.tooltip_text};
            border: 1px solid {colors.border};
            border-radius: 4px;
            padding: 4px 6px;
        }}

        QGroupBox {{
            border: 1px solid {colors.border};
            border-radius: 6px;
            margin-top: 10px;
            padding-top: 8px;
            font-weight: 600;
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}

        QStatusBar {{ border-top: 1px solid {colors.border}; }}

        #CompactSummaryBar {{
            background-color: {colors.surface};
            border-top: 1px solid {colors.border};
            color: {colors.disabled_text};
            font-size: 11px;
        }}

        /* Quick Filters Bar (quick_filters_bar.py) — deliberately NOT its own bordered "card" (an earlier,
           more colourful pass read as a widget from a different app): its two drop-downs inherit the plain
           QComboBox rules like the Filters button above them. Addition: an accent OUTLINE on a drop-down while it
           filters something (the `active` property), so a filtered table is visible at a glance. */
        QComboBox#QuickFilterCombo[active="true"] {{ border: 1px solid {colors.highlight}; }}

        /* AudioPreviewWidget's icon-first transport controls (gui_widgets.py) */
        #MutedCaption {{ color: {colors.disabled_text}; font-size: 11px; }}
        #AccentRoundButton {{
            background-color: {colors.highlight};
            border: none;
            border-radius: 22px;
        }}
        #AccentRoundButton:hover {{ background-color: {colors.accent_hover}; }}
        #AccentRoundButton:pressed {{ background-color: {colors.accent_pressed}; }}
        #AccentRoundButton:disabled {{ background-color: {colors.border}; }}
        #RoundToolButton {{
            background-color: {colors.button};
            border: 1px solid {colors.border};
            border-radius: 16px;
        }}
        #RoundToolButton:hover {{ background-color: {colors.surface}; border-color: {colors.highlight}; }}
        #RoundToolButton:checked {{ background-color: {colors.highlight}; border-color: {colors.highlight}; }}
        #RoundToolButton:disabled {{ background-color: transparent; border-color: {colors.border}; }}
    """ + _indicator_qss(colors)


_INDICATOR_DIR = Path(tempfile.gettempdir()) / "ustudio_theme_indicators"


def _mix(a: str, b: str, t: float) -> str:
    """`a` moved `t` of the way towards `b` (hex colors)."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def indicator_image(colors: ThemeColors, kind: str, state: str, hover: bool = False, disabled: bool = False,
                    selected: bool = False) -> str:
    """A checkbox ("check") or radio ("radio") indicator as an SVG file for the stylesheet; state is "off", "on" or
    "partial" (checkbox only). Returns a forward-slash path.

    Why our own: with Fusion + the dark palette the native indicators were barely visible (a dark box on a dark
    background, user report 2026-10-14). The box's border is a clearly visible grey (text color mixed into the
    background), the accent on hover; "on" is an accent fill with a white tick / ring + dot. SVG, not PNG, so it is
    sharp at 125/150 % scaling (the qsvg image plugin ships with the GUI build). menu_icons.py draws checkable menu
    items from the same files."""
    border = _mix(colors.base, colors.text, 0.55)
    edge = colors.highlight if hover else border
    accent, mark, base = colors.highlight, colors.highlighted_text, colors.base
    if selected:
        # on a SELECTED row of a list/table/tree the background is the accent itself, so an accent-filled box
        # vanished (user report): reversed — a white box with an accent tick, or a white border with no fill
        accent, mark, edge, base = colors.highlighted_text, colors.highlight, colors.highlighted_text, "none"
    if kind == "radio":
        body = (f'<circle cx="8" cy="8" r="6.25" fill="{base}" stroke="{accent if state == "on" else edge}" '
                f'stroke-width="1.5"/>'
                + (f'<circle cx="8" cy="8" r="3.4" fill="{accent}"/>' if state == "on" else ""))
    elif state == "on":
        body = (f'<rect x="1" y="1" width="14" height="14" rx="3" fill="{accent}"/>'
                f'<path d="M4.2 8.3 L6.9 11 L11.9 5.3" fill="none" stroke="{mark}" stroke-width="2" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    elif state == "partial":
        body = (f'<rect x="1" y="1" width="14" height="14" rx="3" fill="{accent}"/>'
                f'<path d="M4.5 8 H11.5" stroke="{mark}" stroke-width="2" stroke-linecap="round"/>')
    else:
        body = f'<rect x="1.75" y="1.75" width="12.5" height="12.5" rx="2.5" fill="{base}" stroke="{edge}" stroke-width="1.5"/>'
    if disabled:
        body = f'<g opacity="0.45">{body}</g>'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{body}</svg>'
    _INDICATOR_DIR.mkdir(parents=True, exist_ok=True)
    tag = "".join(c for c in (colors.name + border + accent + mark + base) if c.isalnum())
    path = _INDICATOR_DIR / (f"{kind}_{state}{'_h' if hover else ''}{'_d' if disabled else ''}"
                             f"{'_s' if selected else ''}_{tag}.svg")
    if not path.exists():
        path.write_text(svg, encoding="utf-8")
    return str(path).replace("\\", "/")


def _indicator_qss(colors: ThemeColors) -> str:
    """Every checkbox and radio button in the app (plain widgets, group boxes and the checkboxes inside lists,
    tables and trees) uses indicator_image()."""
    def img(kind, state, hover=False, disabled=False, selected=False):
        return f"image: url({indicator_image(colors, kind, state, hover, disabled, selected)});"

    check = ("QCheckBox::indicator", "QAbstractItemView::indicator", "QGroupBox::indicator")

    def rule(selectors, pseudo, body):
        return ", ".join(f"{s}{pseudo}" for s in selectors) + f" {{ {body} }}\n"

    qss = rule(check + ("QRadioButton::indicator",), "", "width: 16px; height: 16px;")
    qss += rule(check, ":unchecked", img("check", "off"))
    qss += rule(check, ":unchecked:hover", img("check", "off", hover=True))
    qss += rule(check, ":checked", img("check", "on"))
    qss += rule(check, ":indeterminate", img("check", "partial"))
    qss += rule(check, ":unchecked:disabled", img("check", "off", disabled=True))
    qss += rule(check, ":checked:disabled", img("check", "on", disabled=True))
    qss += rule(check, ":indeterminate:disabled", img("check", "partial", disabled=True))
    view = ("QAbstractItemView::indicator",)              # a selected row's background is the accent: reversed
    qss += rule(view, ":unchecked:selected", img("check", "off", selected=True))
    qss += rule(view, ":checked:selected", img("check", "on", selected=True))
    qss += rule(view, ":indeterminate:selected", img("check", "partial", selected=True))
    radio = ("QRadioButton::indicator",)
    qss += rule(radio, ":unchecked", img("radio", "off"))
    qss += rule(radio, ":unchecked:hover", img("radio", "off", hover=True))
    qss += rule(radio, ":checked", img("radio", "on"))
    qss += rule(radio, ":unchecked:disabled", img("radio", "off", disabled=True))
    qss += rule(radio, ":checked:disabled", img("radio", "on", disabled=True))
    return qss


_current_colors = None


def current_colors():
    """The ThemeColors last applied by apply_theme() (None before the first call)."""
    return _current_colors


def apply_theme(app: QApplication, theme_name: str) -> ThemeColors:
    """Applies the palette app-wide — every window/dialog picks it up automatically since
    none of them set their own palette — and returns the ThemeColors so the caller can also
    re-color whatever uses literal colors outside the palette system (see the module
    docstring: main.py's log() and helpers.py's JsonHighlighter).

    Style is forced to Fusion, not left as the native Windows style: the native
    windows11 style only partially honors a custom QPalette (several widgets keep
    pulling colors from the live OS theme regardless of what's set here), which defeats
    the whole point of an explicit, OS-independent theme. Fusion actually respects
    QPalette consistently — already the established fix for this project's other
    windows11-style quirks (see cab_browser_dialog.py's per-cell selection-accent-bar fix)."""
    global _current_colors
    colors = get_colors(theme_name)
    _current_colors = colors
    app.setStyle("Fusion")
    app.setPalette(_build_palette(colors))
    app.setStyleSheet(build_app_qss(colors))
    # Widgets that carry their OWN setStyleSheet() (e.g. the table selection-accent-bar
    # fix in main.py/cab_browser_dialog.py) can end up with a stale, cached style/palette
    # resolution that doesn't automatically follow a later QApplication.setPalette() —
    # a known Qt quirk, and exactly what made a table look "inverted" (stuck on the old
    # theme) after a live toggle while the rest of that same window updated correctly.
    # Forcing a full unpolish/polish pass on every widget that exists RIGHT NOW is the
    # general, Qt-documented fix — not just widgets this module knows about, since a
    # dialog like CabBrowserDialog may or may not even be open yet when this runs.
    for widget in app.allWidgets():
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
    return colors
