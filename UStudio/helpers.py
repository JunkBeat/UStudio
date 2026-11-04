from core.i18n import tr
from PyQt6.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QColor
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import QTableWidgetItem

from UnityPy.helpers.TypeTreeHelper import FUNCTION_READ_MAP

from config import CONFIG, PREVIEW_FONT_FALLBACK_CHAIN
import theme as _theme


class NumericTableWidgetItem(QTableWidgetItem):
    """Table item that sorts by numeric value rather than by its displayed string."""

    def __init__(self, text: str, sort_value):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.sort_value < other.sort_value
        return super().__lt__(other)


def mono_font() -> QFont:
    """The one shared monospace font used by every dense text/tree view that
    shows closely related data side by side (Preview/Json Dump/Dump tabs,
    ObjectStructureTree) — a font mismatch between them makes scanning back
    and forth unnecessarily jarring. Used to live as two near-identical,
    deliberately-duplicated copies (preview_panel.py's and gui_widgets.py's
    own _mono_font(), each importing from the other being circular) — moved
    here instead, since helpers.py sits below both of them in the import
    graph (neither imports the other's replacement; both already import
    JsonHighlighter/TypedDumpHighlighter from here), so there's exactly one
    definition to keep in sync now, not two.

    Default is Cascadia Mono at 11pt (config.py's DEFAULT_PREVIEW_FONT_FAMILY/
    _SIZE) — thicker strokes and a more open letterform at small sizes than
    Consolas has, per a real eye-fatigue report comparing this app's dense
    text views against UABEA's. Cascadia CODE (the ligature variant)
    deliberately avoided: merging adjacent characters like "!=" into one
    glyph is wrong for a raw data dump. CONFIG.preview_font_family/_size
    (ApplicationSettingsDialog's font section) override this when set;
    setFamilies() (a list, not a single name) lets Qt fall through to the
    next candidate when a preferred family isn't installed, ending on the
    platform's own generic monospace hint rather than an unrelated
    proportional font."""
    font = QFont()
    families = list(PREVIEW_FONT_FALLBACK_CHAIN)
    if CONFIG.preview_font_family:
        families.insert(0, CONFIG.preview_font_family)
    font.setFamilies(families)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(CONFIG.preview_font_size)
    return font

# Same primitive-type source of truth as core/object_preview.py's/gui_widgets.py's
# own _PRIMITIVE_TYPES — used by TypedDumpHighlighter to decide which type names
# get the ordinary keyword color vs. the distinct reference-type color (any
# Unity-specific class/compound type, not just PPtr<...>).
_PRIMITIVE_TYPES = frozenset(FUNCTION_READ_MAP.keys())

# The actual implementations live in core/file_utils.py — a PyQt-free module, since
# core/ (the loader/CAB-archive logic meant to be reusable from a future console-mode
# build without PyQt6) needs them too. Re-exported here so this module keeps being the
# one thing GUI code imports from ("from helpers import X") without every call site
# needing to know which of the two modules a given helper now lives in.
from core.file_utils import (  # noqa: F401
    safe_join,
    stream_to_file,
    write_entry_safely,
    detect_game_paths,
    peek_mb_name,
    peek_mb_identity,
    ScriptIdentity,
    reset_script_name_cache,
    bytes_to_hex_dump_with_map,
    format_size,
    shorten_path,
    read_app_info,
)


class JsonHighlighter(QSyntaxHighlighter):
    """Lightweight JSON syntax highlighter class. Shared between JsonEditorDialog
    and the Json Dump tab in the main window — do not duplicate, edit here.

    Colors default to the app's current saved theme (see theme.py) rather than a
    fixed set of hex values — these are QTextCharFormat colors, which Qt applies
    literally regardless of the active QPalette/OS theme, so a hardcoded dark-tuned
    palette here looked washed out the moment the surrounding widget's background
    wasn't also dark. Pass colors explicitly, or call set_colors() later, to follow
    a live theme toggle instead of just the value read at construction time."""
    def __init__(self, parent=None, colors: "_theme.ThemeColors | None" = None):
        super().__init__(parent)
        self.set_colors(colors or _theme.get_colors(_theme.load_saved_theme_name()))

    def set_colors(self, colors: "_theme.ThemeColors") -> None:
        self.rules = []

        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor(colors.json_string))
        self.rules.append((QRegularExpression(r'"([^"\\]|\\.)*"'), string_format))

        # Keys (same quote-escaping pattern as strings, plus require ":" after)
        key_format = QTextCharFormat()
        key_format.setForeground(QColor(colors.json_key))
        key_format.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(r'"([^"\\]|\\.)*"\s*(?=:)'), key_format))

        # Numbers
        number_format = QTextCharFormat()
        number_format.setForeground(QColor(colors.json_number))
        self.rules.append((QRegularExpression(r'\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b'), number_format))

        # true / false / null
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor(colors.json_keyword))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(r'\b(true|false|null)\b'), keyword_format))

        self.rehighlight()

    def highlightBlock(self, text):
        for expression, char_format in self.rules:
            match_iterator = expression.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), char_format)


class TypedDumpHighlighter(QSyntaxHighlighter):
    """Highlights core.object_preview.dump_typed_text()'s AssetStudioGUI-style
    "Type Name = value" text (the Dump tab's content for every type) — e.g.
    "\tPPtr<GameObject> m_GameObject" / "\t\tint m_FileID = 0" /
    '\tstring m_Name = "GameSkin"'. A separate highlighter from JsonHighlighter
    since this isn't JSON (no colons, unquoted keys, "= value" instead of ": value")
    — reuses the same theme color ROLES for visual consistency across tabs, just
    applied to a different grammar. Same set_colors()/live-theme-toggle pattern as
    JsonHighlighter, for the same reason (literal QTextCharFormat colors, outside
    the QPalette system — see theme.py's module docstring)."""

    # Three regexes tried in order, instead of one grouped pattern (the first
    # attempt at that used a variable-length lookbehind, "(?<=^[\t ]*\S+\s)\S+", to
    # isolate the name token — Qt's QRegularExpression (PCRE2) rejects that outright
    # ("length of lookbehind assertion is not limited"), which silently produced
    # zero highlighting AND spammed the log on every call; a lookbehind-free single
    # grouped pattern fixed that, but assumed the type was always exactly one
    # token — wrong for any multi-word TypeTree primitive name ("unsigned int",
    # "unsigned short", "long long", "unsigned long long"), where dump_typed_text's
    # own "{type} {name} = {value}"/"{type} {name}" formatting still has to fit into
    # "type" + "name" either way. Fixed by using a LAZY (.+?) type instead of \S+:
    # it tries the shortest possible type first and only grows it until the rest of
    # the pattern (name, then "= value" or end-of-line) actually fits, so it
    # naturally stops at "unsigned int" rather than just "unsigned" — verified
    # against "unsigned int m_Flags = 0", "PPtr<GameObject> m_GameObject" (header,
    # no value), and "[0]" (bare index, no type at all).
    # Separators between indent/type/name/value are literal spaces in the real
    # output (_dump_node()'s f"{type} {name} = {value}"/f"{type} {name}") — only
    # the leading INDENT itself uses tabs. Using \s (which also matches a tab)
    # for these separators let a bare index-marker line with 2+ leading tabs
    # ("\t\t\t[0]") get mis-parsed here as type="\t"/name="[0]" instead of falling
    # through to PLAIN_RE below: [\t ]* is greedy but backtracks to satisfy the
    # rest of the pattern, and \s happily accepted one of the leading tabs as the
    # type/name separator. A literal space can never match a tab, so this can no
    # longer misfire on a line that's pure indent + one token.
    _ASSIGN_RE = QRegularExpression(r'^([\t ]*)(.+?) (\S+) = (.*)$')
    _HEADER_RE = QRegularExpression(r'^([\t ]*)(.+?) (\S+)$')
    _PLAIN_RE = QRegularExpression(r'^([\t ]*)(\S+)$')

    # Field names/type-name pairs that core.object_preview.dump_typed_text()'s
    # _dump_node() emits verbatim as pure structural scaffolding, not data a
    # person is actually scanning for — see _is_boilerplate()'s docstring.
    _BOILERPLATE_LEAF_NAMES = frozenset({"m_FileID", "m_PathID"})

    def __init__(self, parent=None, colors: "_theme.ThemeColors | None" = None):
        super().__init__(parent)
        self.set_colors(colors or _theme.get_colors(_theme.load_saved_theme_name()))

    def set_colors(self, colors: "_theme.ThemeColors") -> None:
        self._type_format = QTextCharFormat()
        self._type_format.setForeground(QColor(colors.json_keyword))

        # Any Unity-specific class/compound type (GameObject, ComponentPair,
        # PPtr<...>, a MonoBehaviour's own script class name, ... — anything
        # not in _PRIMITIVE_TYPES) gets a distinct color from an ordinary
        # simple/primitive type (int, string, bool, vector, ...) — same
        # distinction gui_widgets.ObjectStructureTree makes, kept consistent
        # across both views per a real request (initially scoped to just
        # PPtr<...>, then corrected to cover every non-primitive type).
        self._reference_type_format = QTextCharFormat()
        self._reference_type_format.setForeground(QColor(colors.json_reference_type))

        self._name_format = QTextCharFormat()
        self._name_format.setForeground(QColor(colors.json_key))
        self._name_format.setFontWeight(QFont.Weight.Bold)

        self._string_format = QTextCharFormat()
        self._string_format.setForeground(QColor(colors.json_string))

        self._number_format = QTextCharFormat()
        self._number_format.setForeground(QColor(colors.json_number))

        # Reuses the QPalette "disabled text" role's color — same "de-emphasized,
        # secondary" meaning it already carries elsewhere in the app (e.g.
        # unselected tab labels), so this needed no new theme.py color of its own.
        self._dim_format = QTextCharFormat()
        self._dim_format.setForeground(QColor(colors.disabled_text))

        self.rehighlight()

    def highlightBlock(self, text):
        stripped = text.lstrip("\t ")
        if stripped.startswith("<") or stripped.startswith("..."):
            # "<ошибка: ...>" / "<достигнута максимальная глубина>" /
            # "... (ещё N элементов)" — free-text lines, not "type name = value"
            # shaped, but HEADER_RE below is lenient enough (lazy type match) to
            # otherwise mis-parse their last two words as a type/name pair. No
            # highlighting is the correct outcome here, same as before this fix.
            return

        match = self._ASSIGN_RE.match(text)
        if match.hasMatch():
            if self._is_boilerplate(match.captured(2), match.captured(3), has_value=True):
                self.setFormat(0, len(text), self._dim_format)
                return
            self._apply_type_name(match)
            value = match.captured(4)
            fmt = self._string_format if value.startswith('"') else self._number_format
            self.setFormat(match.capturedStart(4), len(value), fmt)
            return

        match = self._HEADER_RE.match(text)
        if match.hasMatch():
            if self._is_boilerplate(match.captured(2), match.captured(3), has_value=False):
                self.setFormat(0, len(text), self._dim_format)
                return
            self._apply_type_name(match)
            return

        match = self._PLAIN_RE.match(text)
        if match.hasMatch() and match.capturedLength(2):
            token = match.captured(2)
            if token.startswith("[") and token.endswith("]"):
                # Bare array index markers ("[0]", "[41]", ...) — pure position
                # counters with no data of their own, dimmed the same way.
                self.setFormat(0, len(text), self._dim_format)
                return
            self.setFormat(match.capturedStart(2), match.capturedLength(2), self._type_format)

    def _apply_type_name(self, match) -> None:
        if match.capturedLength(2):
            type_text = match.captured(2)
            fmt = self._type_format if type_text in _PRIMITIVE_TYPES else self._reference_type_format
            self.setFormat(match.capturedStart(2), match.capturedLength(2), fmt)
        if match.capturedLength(3):
            self.setFormat(match.capturedStart(3), match.capturedLength(3), self._name_format)

    @classmethod
    def _is_boilerplate(cls, type_text: str, name_text: str, has_value: bool) -> bool:
        """True for lines that are pure structural scaffolding rather than
        actual data worth scanning for: the two universal PPtr leaf fields
        (m_FileID/m_PathID — present on every single object/component
        reference in the file, easily dozens of times per object, and never
        meaningful on their own without resolving the reference they form),
        the synthetic "Array Array"/"int size = N" wrapper lines
        _dump_node() always emits for every array regardless of content, and
        a compound array element's own header line.

        That last one needs has_value to get right: Unity's own TypeTree
        schema names EVERY vector<T>'s per-element field "data" — for a
        primitive array (vector<int>, ...) that's a real value line ("int
        data = 5", has_value=True, NOT boilerplate — that number IS the
        content), but for a compound array (vector<ComponentPair>, a real
        `pair` field, ...) it's a header line with no value of its own
        ("ComponentPair data" / "pair data", has_value=False — pure
        "here comes the next element's fields" scaffolding, confirmed against
        a real GameObject's m_Component dump, which produces exactly
        "ComponentPair data" this way rather than the "pair data" this
        function originally assumed from just reading _dump_node()'s source).

        Dimmed rather than removed either way: still there to copy/verify
        exactly, just visually out of the way so real field names and values
        are what catches the eye scanning down a long dump."""
        if name_text in cls._BOILERPLATE_LEAF_NAMES:
            return True
        if type_text == "int" and name_text == "size":
            return True
        if not has_value:
            if type_text == "Array" and name_text == "Array":
                return True
            if name_text == "data":
                return True
        return False


# Real reported feedback: the Structure tab's highlighting wasn't worth it —
# unlike the Dump tab, there's no actual DATA value to visually distinguish
# from scaffolding, so the marginal benefit (primitive/reference-type color,
# dimming the align-bit) didn't earn its keep. Reverted to plain, unhighlighted
# text (preview_panel.py no longer imports/instantiates this) — left here
# commented out, not deleted, in case it's wanted again later; re-enabling is
# just uncommenting this class plus the three call sites preview_panel.py's
# own history has (import, construction alongside txt_structure, and the
# apply_theme_colors() line).
#
# class StructureDumpHighlighter(QSyntaxHighlighter):
#     """Highlights core.object_preview.dump_structure_text()'s schema-only output
#     (the Structure tab's content) — e.g. " 0 PPtr<GameObject> m_GameObject" /
#     "  1 UInt8 m_Enabled". Same "type name" shape as TypedDumpHighlighter's
#     header lines, plus one extra leading token that format doesn't have: a
#     bare 0/1 (metaflag_is_aligned(node.m_MetaFlag) — see dump_structure_text()'s
#     own docstring), dimmed the same way TypedDumpHighlighter dims m_FileID/
#     m_PathID — a low-level implementation detail, not something to actually
#     scan for the way the type/name pair is. Reuses the same color ROLES (and
#     the same lazy-type-match trick, for multi-word primitive names like
#     "unsigned int"/"unsigned long long") as TypedDumpHighlighter for visual
#     consistency between the two tabs — kept as its own class rather than
#     folded into that one since the two grammars only share their type/name
#     half: no "= value" here at all, an extra leading align-bit token
#     TypedDumpHighlighter's lines never have, and plain-space indent instead
#     of tabs (dump_structure_text()'s own choice)."""
#
#     _LINE_RE = QRegularExpression(r'^( *)([01]) (.+?) (\S+)$')
#
#     def __init__(self, parent=None, colors: "_theme.ThemeColors | None" = None):
#         super().__init__(parent)
#         self.set_colors(colors or _theme.get_colors(_theme.load_saved_theme_name()))
#
#     def set_colors(self, colors: "_theme.ThemeColors") -> None:
#         self._type_format = QTextCharFormat()
#         self._type_format.setForeground(QColor(colors.json_keyword))
#
#         self._reference_type_format = QTextCharFormat()
#         self._reference_type_format.setForeground(QColor(colors.json_reference_type))
#
#         self._name_format = QTextCharFormat()
#         self._name_format.setForeground(QColor(colors.json_key))
#         self._name_format.setFontWeight(QFont.Weight.Bold)
#
#         self._dim_format = QTextCharFormat()
#         self._dim_format.setForeground(QColor(colors.disabled_text))
#
#         self.rehighlight()
#
#     def highlightBlock(self, text):
#         stripped = text.lstrip(" ")
#         if stripped.startswith("<"):
#             # "<ошибка: ...>" / "<достигнута максимальная глубина>" — free-text
#             # lines, not "N type name" shaped; _LINE_RE simply won't match
#             # these anyway (no leading 0/1 token), but skip the attempt.
#             return
#
#         match = self._LINE_RE.match(text)
#         if not match.hasMatch():
#             return
#
#         self.setFormat(match.capturedStart(2), match.capturedLength(2), self._dim_format)
#
#         type_text = match.captured(3)
#         fmt = self._type_format if type_text in _PRIMITIVE_TYPES else self._reference_type_format
#         self.setFormat(match.capturedStart(3), match.capturedLength(3), fmt)
#
#         self.setFormat(match.capturedStart(4), match.capturedLength(4), self._name_format)


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """The Russian noun form for a count: plural_ru(1, "файл", "файла", "файлов") -> "файл", 2 -> "файла",
    5 -> "файлов", 11 -> "файлов", 21 -> "файл"."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def format_type_names(names, limit: int = 6) -> str:
    """"Texture2D, Sprite, AudioClip и ещё 5" — a short list of type names for a message."""
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return tr("{names} и ещё {count}", names=", ".join(names[:limit]), count=len(names) - limit)


def wrap_tooltip(text: str, width: int = 56) -> str:
    """Plain-text tooltips are not wrapped by Qt, so a long sentence becomes one very wide line.
    Breaks `text` into lines of at most `width` characters (existing line breaks are kept). Breaks only
    at spaces: a file name or a CAB id ("CAB-1810b55a...", "a_b_c.bundle") stays whole on its own line
    (wider than `width` if it has to be) instead of being cut in the middle."""
    import textwrap
    return "\n".join(
        textwrap.fill(part, width, break_long_words=False, break_on_hyphens=False) if part.strip() else ""
        for part in text.split("\n"))
