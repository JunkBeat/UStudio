"""Quick Filters Bar's data model — PyQt-free (same layer as core/object_preview.py/
core/sdf_resolver.py), covering the button definitions, how a set of active buttons
merges into the flat table's existing allowed_types/allowed_scripts filter
(object_table.py's AdvancedFilterProxyModel), and the file/source list the bar's
combobox and FiltersDialog's new "Файлы" tab both need — one shared computation so
the two never disagree about what "resources.assets (14200)" means.

Persistence uses the same QSettings store/pattern as config.py's PERSISTED_FIELDS
(group "quick_filters", not "persisted_config" — a distinct list-shaped setting,
not a handful of independent scalars), stored as one JSON string rather than
QSettings' own list/QVariant machinery — same reasoning config.py already gives for
excluded_folders-style values: simpler to validate as a single unit before ever
touching a widget. The settings store is the GUI's own (app_settings.py, which imports PyQt6), so the
three persistence functions import it when called: importing this module stays Qt-free."""

from core.i18n import N_
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set, Tuple

_SETTINGS_GROUP = "quick_filters"
_SETTINGS_KEY = "definitions"

# "modified" is the one button whose meaning isn't a type/script filter at all
# (see merge_active_filters()) — every other special value is reserved for future use.
MODIFIED_SPECIAL = "modified"

# QuickFilterDef.icon has three forms: "" = automatic (the icon of the filter's first type),
# "icon:<Name>" = one of the app's built-in painted icons (type_icons.builtin_icon_choices()),
# anything else = a symbol/emoji typed by the user.
BUILTIN_ICON_PREFIX = "icon:"


@dataclass
class QuickFilterDef:
    key: str  # stable id — survives a label edit, used for the active-set/persistence
    label: str
    types: Tuple[str, ...] = ()
    # None = "MonoBehaviour rows are unrestricted by script" (only meaningful when
    # "MonoBehaviour" is in `types`) — NOT the same as an empty tuple, which would mean
    # "restrict to zero scripts", i.e. reject every MonoBehaviour row. See
    # merge_active_filters()'s docstring.
    scripts: Optional[Tuple[str, ...]] = None
    color: str = "#6366f1"
    special: Optional[str] = None  # MODIFIED_SPECIAL, or None for an ordinary type/script button
    icon: str = ""  # see BUILTIN_ICON_PREFIX: "" (automatic) | "icon:<Name>" | a user's own symbol/emoji

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "QuickFilterDef":
        return QuickFilterDef(
            key=str(d["key"]),
            label=str(d.get("label", d["key"])),
            types=tuple(d.get("types") or ()),
            scripts=tuple(d["scripts"]) if d.get("scripts") is not None else None,
            color=str(d.get("color", "#6366f1")),
            special=d.get("special"),
            icon=str(d.get("icon", "")),
        )

    @property
    def builtin_icon_key(self) -> Optional[str]:
        """The built-in icon's name when `icon` is "icon:<Name>", else None."""
        return self.icon[len(BUILTIN_ICON_PREFIX):] if self.icon.startswith(BUILTIN_ICON_PREFIX) else None

    @property
    def display_label(self) -> str:
        """The label for the full-width style: a user's own symbol goes in front of it as text; a
        built-in icon is not text, so the label stands alone (the icon shows in compact mode/menus)."""
        symbol = "" if self.icon.startswith(BUILTIN_ICON_PREFIX) else self.icon
        return f"{symbol} {self.label}" if symbol else self.label


# Real reported feedback: colorful per-button icons/backgrounds (an earlier
# version had both) read as visual noise / an element from a different app —
# plain text labels, no icon, every button styled identically except while
# actively toggled (see theme.py's #QuickFilterButton:checked, one shared
# accent for all of them). `color` is kept on each entry only as inert,
# persisted data (QuickFilterButton no longer reads it for rendering) —
# harmless to leave set, not worth stripping from already-saved JSON.
# «Only modified objects» is not a preset any more: the quick filters bar has its own toggle for it (a
# saved list from an older build may still hold the special entry; the bar leaves it out).
DEFAULT_QUICK_FILTERS: List[QuickFilterDef] = [
    QuickFilterDef(key="textures", label=N_("Текстуры"), types=("Texture2D", "Texture2DArray"), color="#3A628F"),
    QuickFilterDef(key="fonts", label=N_("Шрифты"), types=("Font", "MonoBehaviour"), scripts=("TMP_FontAsset",), color="#3A628F"),
    QuickFilterDef(key="audio", label=N_("Аудио"), types=("AudioClip",), color="#3A628F"),
    QuickFilterDef(key="video", label=N_("Видео"), types=("VideoClip",), color="#3A628F"),
    QuickFilterDef(key="text", label=N_("Текст"), types=("TextAsset",), scripts=("I2.Loc.LanguageSourceAsset", "UnityEngine.Localization.Tables.StringTable"), color="#3A628F"),
    QuickFilterDef(key="monobehaviour", label="MonoBehaviour", types=("MonoBehaviour",), color="#3A628F"),
]


def load_quick_filters() -> List[QuickFilterDef]:
    from app_settings import app_settings
    settings = app_settings()
    settings.beginGroup(_SETTINGS_GROUP)
    raw = settings.value(_SETTINGS_KEY, "", type=str)
    settings.endGroup()
    if not raw:
        return list(DEFAULT_QUICK_FILTERS)
    try:
        data = json.loads(raw)
        parsed = [QuickFilterDef.from_dict(d) for d in data]
        return parsed if parsed else list(DEFAULT_QUICK_FILTERS)
    except Exception:
        # A corrupted/foreign value here shouldn't be fatal to opening the app —
        # fall back to the shipped defaults, same "discard rather than partially
        # apply a malformed saved value" policy gui_layout.py's restore_layout()
        # already follows for its own persisted state.
        return list(DEFAULT_QUICK_FILTERS)


def save_quick_filters(filters: List[QuickFilterDef]) -> None:
    from app_settings import app_settings
    settings = app_settings()
    settings.beginGroup(_SETTINGS_GROUP)
    settings.setValue(_SETTINGS_KEY, json.dumps([f.to_dict() for f in filters]))
    settings.endGroup()


def reset_quick_filters() -> None:
    """Clears the persisted quick-filter definitions — used by
    ApplicationSettingsDialog's "Сбросить все настройки" button (see
    config.py's reset_persisted_config(), the counterpart for the other
    settings groups). The next load_quick_filters() call then falls back to
    DEFAULT_QUICK_FILTERS, same as a first run — takes effect after the app
    is restarted, same as everything else that button resets."""
    from app_settings import app_settings
    settings = app_settings()
    settings.beginGroup(_SETTINGS_GROUP)
    settings.remove("")
    settings.endGroup()


def merge_active_filters(
    active: List[QuickFilterDef],
) -> Tuple[Optional[Set[str]], Optional[Set[str]], bool]:
    """Returns (allowed_types, allowed_scripts, modified_only) — the exact shape
    AdvancedFilterProxyModel.set_type_script_filter() already takes, plus a third,
    independently-ANDed "only modified rows" flag (see object_table.py's
    _item_passes_filter). None means "no restriction", matching the dialog's own
    convention, so turning every quick-filter button off is identical to never
    having touched the filter at all.

    Multiple active buttons OR together (Textures + Audio active shows both) —
    except for MonoBehaviour's script restriction specifically, where the more
    permissive selection wins: if "MonoBehaviour" (unrestricted) is active
    alongside "Fonts" (MonoBehaviour restricted to TMP_FontAsset), the union is
    "all MonoBehaviour" — Fonts' narrower slice is already a subset of that, so
    there's nothing left to restrict. Only when EVERY active button that
    contributes MonoBehaviour narrows it by script does the result stay
    restricted to the union of those scripts."""
    type_defs = [f for f in active if f.special != MODIFIED_SPECIAL]
    modified_only = any(f.special == MODIFIED_SPECIAL for f in active)

    if not type_defs:
        return None, None, modified_only

    allowed_types: Set[str] = set()
    mono_unrestricted = False
    mono_scripts: Set[str] = set()
    for f in type_defs:
        allowed_types.update(f.types)
        # Real reported bug: this used to only ever look at f.scripts when
        # "MonoBehaviour" was ALSO explicitly present in f.types — so a
        # custom quick filter created via QuickFilterSettingsDialog with a
        # script name entered but the "MonoBehaviour" type checkbox left
        # unchecked (a completely reasonable thing to do — the script field
        # reads as its own restriction, not as secretly requiring a second,
        # separate checkbox) silently showed nothing at all: the script
        # restriction was ignored AND "MonoBehaviour" was never added to
        # allowed_types either, so no MonoBehaviour row could ever pass.
        # This only ever worked for the shipped "Fonts" default because that
        # ONE definition happens to list types=("Font", "MonoBehaviour")
        # explicitly. A script restriction only makes sense for MonoBehaviour
        # rows in the first place, so f.scripts being set at all now implies
        # "MonoBehaviour" regardless of what f.types itself lists.
        mono_wanted = "MonoBehaviour" in f.types or f.scripts is not None
        if mono_wanted:
            allowed_types.add("MonoBehaviour")
            if f.scripts is None:
                mono_unrestricted = True
            else:
                mono_scripts.update(f.scripts)

    if "MonoBehaviour" not in allowed_types or mono_unrestricted:
        allowed_scripts = None
    else:
        allowed_scripts = mono_scripts

    return allowed_types, allowed_scripts, modified_only


def compute_source_counts(data_list: List[dict]) -> List[Tuple[str, int]]:
    """(source name, row count) pairs, sorted alphabetically — the single source
    of truth for both the Quick Filters Bar's file combobox and FiltersDialog's
    "Файлы" tab, so the two never present a different file list from each
    other. Every RowItem always has a non-empty `source` (see core/models.py),
    so no "Unknown" fallback is needed here."""
    counts: Dict[str, int] = {}
    for item in data_list:
        source = item.get("source", "")
        counts[source] = counts.get(source, 0) + 1
    return sorted(counts.items())


def compute_source_roots(data_list: List[dict]) -> Dict[str, List[str]]:
    """source name -> names of the root files (the bundle / archive / loose file actually
    on disk) its rows live in, sorted. A source is an entry name (a CAB inside a bundle,
    "level0" inside data.unity3d), so the root is what tells the user WHERE it came from;
    a loose file is its own root. Usually one name per source; several when files with
    the same entry name were loaded from different bundles. Walks once per distinct
    assets file, not per row."""
    from core.save_manager import _root_file

    root_name_of: Dict[int, str] = {}
    roots: Dict[str, Set[str]] = {}
    last = (None, None)
    for item in data_list:
        source = item.get("source", "")
        assets_file = getattr(item.get("obj_ref"), "assets_file", None)
        # Rows come file by file: a row of the file just seen adds nothing (Lego Party's 1.9 M rows:
        # 1.1-1.7 s -> a fraction, it ran each time «Фильтры» opened).
        if assets_file is last[0] and source == last[1]:
            continue
        last = (assets_file, source)
        if assets_file is None:
            continue
        key = id(assets_file)
        name = root_name_of.get(key)
        if name is None:
            name = str(getattr(_root_file(assets_file), "name", "") or "")
            root_name_of[key] = name
        if name:
            roots.setdefault(source, set()).add(name)
    return {source: sorted(names, key=str.lower) for source, names in roots.items()}


_MAX_ROOTS_IN_TOOLTIP = 8


def source_roots_tooltip(root_names: List[str]) -> str:
    """The Файлы tab's tooltip for one source ("" when its root is unknown)."""
    if not root_names:
        return ""
    if len(root_names) == 1:
        return f"Parent: {root_names[0]}"
    shown = root_names[:_MAX_ROOTS_IN_TOOLTIP]
    lines = [f"Parents ({len(root_names)}):"] + shown
    if len(root_names) > len(shown):
        lines.append(f"...and {len(root_names) - len(shown)} more")
    return "\n".join(lines)
