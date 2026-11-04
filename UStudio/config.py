import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# Re-exported — see core/options.py and core/models.py for why these pure data
# shapes live in the PyQt-free core/ package rather than here.
from core.options import LoadMode
from core.models import RowItem
from core.object_metadata import DEFAULT_CHAR_COVERAGE_CHARS, DEFAULT_CHAR_COVERAGE_LABEL
from core.object_preview import RICH_PREVIEW_TYPES, TEXTURE_MANUAL_FORMAT_OPTIONS
from core.addressables_resolver import CabIndex

from app_info import APP_NAME, APP_VERSION  # noqa: F401 (re-exported; defined in app_info.py)
from app_settings import app_settings

# Preview panel's monospace font (Дерево/Дамп/Json Dump tabs) — the actual
# QFont is built by preview_panel.py's/gui_widgets.py's own _mono_font()
# (duplicated between the two rather than shared — see gui_widgets.py's
# _mono_font() docstring), but the default family/size and fallback chain
# live here so ApplicationSettingsDialog can show/reset to the same values
# both of those functions fall back to when CONFIG.preview_font_family is
# empty (never customized). Chosen per a real eye-fatigue report comparing
# this app's dense text views against UABEA's: Cascadia Mono over Consolas
# for thicker strokes and a more open letterform at small sizes; 11pt over
# the previous 10pt. Cascadia CODE (the ligature variant) deliberately
# excluded from the chain — merging adjacent characters like "!=" into one
# glyph is wrong for a raw data dump.
DEFAULT_PREVIEW_FONT_FAMILY = "Cascadia Mono"
DEFAULT_PREVIEW_FONT_SIZE = 11
PREVIEW_FONT_FALLBACK_CHAIN = ["Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "Monospace"]


class LogLevel(Enum):
    INFO = 0
    WARNING = 1
    ERROR = 2
    # Details nobody needs on every load (lists of skipped files, which DLL folder was used...).
    # Not shown in the log window unless CONFIG.show_debug_log is on.
    DEBUG = 3

DEFAULT_SDF_CHARACTER_PRESETS: Dict[str, str] = {
    "Default": r""" ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя0123456789!@#$%^&*()_+-=[]{}|;:'",.<>/?\`~№«»—–…°©®™€$₽£¥+×÷=≠≈±<≤>≥%‰/\&""",  # i18n: keep
}


@dataclass
class AppConfig:
    game_data_dir: str = ""
    managed_dir: str = ""
    unity_version: str = "2021.3.0f1"
    # Build target platform (e.g. "StandaloneWindows64", "Android") — resolved
    # alongside unity_version at the end of each load (see EnvironmentLoader.
    # resolve_platform()), used only for the window title's Platform segment.
    platform_name: str = ""
    # {simplified cab name: bundle path} index built as a free byproduct of the last
    # folder/files-mode load's own quick scan (see EnvironmentLoader._scan_and_confirm()
    # / core/addressables_resolver.py) — NOT persisted (not in PERSISTED_FIELDS; a
    # session-only cache tied to whatever's actually loaded right now, same lifetime
    # as env/raw_data_list, reset in MainWindow._clear_loaded_session()). None until
    # the first load of a session completes.
    cab_index: Optional[CabIndex] = None
    fallback_version: str = ""
    unity_cn_key: str = ""
    load_mode: LoadMode = LoadMode.FOLDER
    selected_dir: str = ""
    selected_files: List[str] = field(default_factory=list)
    game_root_dir: str = ""
    object_count_threshold: int = 2_000_000
    is_il2cpp: bool = False
    # Two different files with the same internal name (e.g. two "level0"s of different
    # games) are both loaded; resources, PPtr references and "go to object" pick the copy
    # nearest the object. This only decides the lookup by name ALONE (and ties):
    # "keep_first" (default) lets the first-registered file take the name slot, "raise"
    # aborts the load the moment a collision is hit. (Older "keep_last"/"ask" values are
    # read as "keep_first" — see _validate_cab_collision_policy.)
    cab_collision_policy: str = "keep_first"
    # Folders (absolute paths) skipped entirely during a folder-mode recursive scan —
    # editable in Settings → «Совпадения имён файлов...».
    excluded_folders: List[str] = field(default_factory=list)

    # Named character sets saved from the SDF generator dialog (name -> raw
    # text, exactly as typed — not codepoints, so a saved preset still shows
    # as readable text if the presets list is ever inspected directly).
    # Persisted as its own JSON-encoded string (see load/save_persisted_config
    # below) rather than through the generic PERSISTED_FIELDS loop — that
    # loop's (qtype, validator) shape assumes a scalar or a flat list, and a
    # name->text mapping doesn't fit either without round-tripping through
    # JSON regardless, so it gets its own small dedicated pair instead of
    # forcing an ill-fitting entry into the shared table.
    sdf_character_presets: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SDF_CHARACTER_PRESETS))

    # Remembers the SDF generator dialog's own last-used font path/characters/
    # mode for the CURRENT SESSION only — deliberately plain CONFIG fields,
    # not added to PERSISTED_FIELDS/QSettings: a real reported gap was having
    # to re-browse for the same font file and retype the same characters on
    # every single "Генерировать SDF..." invocation, which named presets
    # don't solve on their own (a preset is an explicit, named save; this is
    # just "keep whatever I last used" with zero extra action). Session-only
    # is a deliberate choice, not a shortcut — surviving a restart would mean
    # a font path from a completely different game silently reappearing next
    # time the app is opened, which is the wrong default for a per-game path.
    sdf_last_font_path: str = ""
    sdf_last_characters: str = ""
    sdf_last_mode: str = "add"
    # "Добавлять недостающие символы из шрифта" checkbox of the SDF generator dialog; on by default.
    sdf_add_missing: bool = True
    # None = "Как в оригинале" was last selected (the default) — a real,
    # explicit numeric value means "Свой размер"/pxrange was last used with
    # exactly that value. Session-only for the same reason as the three
    # fields above: a custom size/spread tuned for one font asset has no
    # business silently reapplying to a completely different one, whether
    # across a restart OR across fonts within the same session — a fresh
    # SDFGeneratorDialog for a DIFFERENT font asset always re-defaults to
    # "Как в оригинале" regardless of what these hold; they only pre-fill the
    # CUSTOM VALUE's own text field so re-entering the same number twice in a
    # row isn't required.
    sdf_last_custom_point_size: Optional[float] = None
    sdf_last_custom_pxrange: Optional[float] = None

    # --- Настройки menu (checkable QAction, see MainWindow.init_menu) ---
    # Off by default: only objects whose type is in RICH_PREVIEW_TYPES (core/
    # object_preview.py) become table rows at all — bounds table growth on huge
    # fixtures to types actually worth individually browsing (see
    # core.loader.build_row_item's own docstring for why lifting this is safe
    # performance-wise). Checking "Загружать все ассеты" indexes every object
    # regardless of type — takes effect on the next load, not retroactively.
    load_all_assets: bool = False

    # --- ApplicationSettingsDialog (Настройки → Настройки приложения) — indexing section ---
    # Which object types actually become table rows — user-configurable counterpart
    # to the hardcoded RICH_PREVIEW_TYPES allow-list (core/object_preview.py), read
    # by core/loader.py's build_row_item() via LoadOptions.indexed_types. Defaults
    # to today's RICH_PREVIEW_TYPES contents. load_all_assets above bypasses it
    # entirely. When the data volume is large (see LargeLoadDialog) these types, plus
    # EnvironmentLoader.SUPPORT_TYPE_NAMES, are also all that gets parsed at all.
    indexed_types: List[str] = field(default_factory=lambda: sorted(RICH_PREVIEW_TYPES))

    # --- Вид menu (checkable QActions, see MainWindow.init_menu) ---
    # Master switch for the whole preview pipeline — off skips the background
    # read entirely on selection (see PreviewPanel.request_preview), a real
    # perf knob at hard-case object counts rather than just a UI preference.
    preview_enabled: bool = True
    show_tree_view: bool = True
    show_dump_view: bool = True
    # The "Структура" tab (schema only — type/name/align-bit per field, no
    # values) — a cheap, always-fast complement to Дамп: unlike that tab, it
    # never touches the object's actual byte data, so it stays available even
    # when a Дамп/JSON parse fails outright (an IL2CPP script that desyncs, say).
    show_structure_view: bool = True
    # Also drives video autoplay (PreviewPanel) — real reported feedback: a
    # separate video-specific toggle wasn't worth it, since games rarely have
    # more than a handful of VideoClip objects to begin with.
    autoplay_audio: bool = False
    show_quick_filters_bar: bool = True

    # --- ApplicationSettingsDialog (Настройки → Настройки приложения) — export section ---
    # How a bulk export groups its output files into subfolders — "none" (flat,
    # same as before this setting existed), "type" (one subfolder per Unity
    # type), "source" (one subfolder per source file/bundle-internal name).
    export_grouping: str = "none"
    # Every GUI export goes into a "UStudio_Assets" folder INSIDE the folder the user picks, so the picked folder
    # (often the game's or a mod's own folder) does not fill up with loose files. See gui_common.export_target_dir.
    export_assets_subfolder: bool = True
    export_overwrite: bool = True
    # Copy the original files aside just before "save files" overwrites them (core/backup.py).
    backup_before_overwrite: bool = False
    # Old copies are pruned: the first copy of each file is kept forever, plus this many newest.
    backup_keep_latest: int = 1
    export_open_folder_after: bool = False

    # --- ApplicationSettingsDialog (Настройки → Настройки приложения) ---
    # Global default packer for any bundle rebuild that doesn't have a more
    # specific per-operation override — e.g. CabBrowserDialog's own "без
    # сжатия" checkbox stays the fast override; unchecked, it now falls back
    # to this instead of a hardcoded "original". Values match BundleFile.
    # save()'s accepted packer strings. "lz4hc" is accepted there too (since
    # upstream 1.25.4) but deliberately not offered: compress_lz4 already
    # compresses at high-compression level, so "lz4hc" differs from "lz4" only
    # in the flag written to the header — same data, same size.
    bundle_compression_packer: str = "original"

    # --- ApplicationSettingsDialog (Настройки → Настройки приложения) — font section ---
    # Empty family = "never customized, use DEFAULT_PREVIEW_FONT_FAMILY/the
    # fallback chain above" — kept distinct from actually storing that name so
    # a future change to the built-in default still takes effect for anyone
    # who never touched this setting. Applies to the Preview tab's Tree/Dump/
    # Json Dump/info text (see preview_panel.py's/gui_widgets.py's _mono_font()).
    preview_font_family: str = ""
    preview_font_size: int = DEFAULT_PREVIEW_FONT_SIZE

    # --- ApplicationSettingsDialog — character-coverage check ("does this font support ___") ---
    # Real request, once localization was raised as a later goal: this used to be a hardcoded
    # Cyrillic check (Font's cmap, TMP_FontAsset's own character table); a label+character-set
    # pair the user can redefine for any language/project instead. See core/object_metadata.py's
    # set_char_coverage() for how these reach the (PyQt-free) check itself. Defaults preserve the
    # exact old built-in check unchanged for anyone who never opens this setting.
    char_coverage_label: str = DEFAULT_CHAR_COVERAGE_LABEL
    char_coverage_chars: str = DEFAULT_CHAR_COVERAGE_CHARS

    # --- ApplicationSettingsDialog (Настройки → Настройки приложения) — converted import ---
    # No "ask before import" toggle — ConvertedImportSettingsDialog is reached by a dedicated
    # menu action ("Импортировать из файла (с настройками)...") instead, shown unconditionally
    # when chosen. The plain "Импортировать из файла..." action always runs silently with
    # whatever's saved here. Two settings-carrying entry points, not one gated by a global
    # switch — see CLAUDE.md's "Converted import" section for why the earlier ask/don't-show-
    # again design was replaced.
    #
    # "match_original" (default, safest — always re-encodes into whatever format the object
    # ALREADY declares, so a platform-incompatible choice is structurally impossible) vs
    # "manual" (texture_import_manual_format below picks the actual format explicitly, from a
    # curated list of formats this pipeline can actually encode — see
    # core.object_preview.TEXTURE_MANUAL_FORMAT_OPTIONS — with a platform-mismatch warning
    # shown in the dialog, not a hard block). There's no auto-pick-format-from-quality-tier
    # mode: an earlier "by_quality" attempt tied quality and format together through a hidden
    # lookup table and produced incoherent pairings (e.g. "medium" quality and "high" quality
    # picking the identical format) — manual selection is strictly more capable and more
    # honest about what's actually happening.
    texture_import_format_mode: str = "match_original"
    # Only consulted when texture_import_format_mode == "manual" — a TextureFormat name from
    # core.object_preview.TEXTURE_MANUAL_FORMAT_OPTIONS (validated against that exact list, so
    # this can never end up holding a format the encoder pipeline doesn't actually support).
    texture_import_manual_format: str = "BC7"
    # "medium" (BC quality "balanced") / "high" ("best") — deliberately just two tiers: a third
    # ("lossless") was dropped since no block-compressed format is actually lossless, and
    # "fast" was dropped since it measured SLOWER than "balanced" at 2048px+ in real testing
    # (an encoder-side quirk, not a tradeoff worth exposing as a "faster" option when it isn't
    # reliably one). ETC1/ETC2/ASTC targets have no quality knob of their own yet, so the two
    # tiers are indistinguishable for those.
    texture_import_quality: str = "high"
    # Mipmap generation on converted texture import — on/off only (no count picker, per explicit
    # request to keep this simple): on generates a full chain down to 1x1.
    texture_import_mipmaps: bool = False
    # AudioClip converted import (PCM/Vorbis via FSBank, see
    # UnityPy/helpers/Fsb5Encoder.py) — FSBank's own 0-100 quality scale, 0 being
    # its documented "normal" default. No format picker exists here (unlike
    # texture_import_format_mode) — the target format is always Unity's own
    # declared m_CompressionFormat, since FSBank can only reproduce PCM/Vorbis
    # at all (see Fsb5Encoder's module docstring for the hard capability
    # ceiling that makes a manual format choice meaningless here).
    audio_import_quality: int = 0

    # Resource-backed import target (core.object_preview.import_object_content_raw)
    # — where a resource-backed object's appended bytes actually land. Named
    # generically, not after "content raw" specifically: this same setting also
    # governs converted imports for the same two types (AudioClip/VideoClip), since
    # import_object_converted()'s branches for both delegate their actual byte-
    # writing to import_object_content_raw() internally — "content-raw-*" in the
    # name would have implied it only applied to the raw content-raw import MODE,
    # which was never true and was a real, reported point of confusion. In
    # practice this only ever applies to AudioClip/VideoClip today: those are the
    # only two types registered in core.object_preview._STREAM_FIELD_INFO, the
    # allow-list this whole mechanism is gated on. Texture2D/Mesh also stream data
    # externally, but into .resS specifically via a different struct
    # (m_StreamData) that this feature doesn't touch — not wired in here (a real
    # correction from the user, not an assumption: they store there, not in
    # .resource, and neither type is in _STREAM_FIELD_INFO regardless). "original"
    # (default) keeps today's behavior: append to whatever resource the object
    # already declares. "custom_resource" redirects every such import into ONE
    # shared, separately-named resource (resource_name below) instead — a real
    # reported request: the original resource can be huge, and routing patches
    # into their own small file makes them shareable/self-contained instead of a
    # multi-GB diff against the original. Deliberately a single GLOBAL toggle, not
    # a per-object-type or per-storage-shape auto-choice — see CLAUDE.md's own
    # writeup of why: a second axis of "where did my edit actually go"
    # unpredictability was judged worse than the (real, but this app's own
    # get_writeable_cab()-based handling already makes cheap) memory cost of
    # appending to a large original bundle-internal resource.
    resource_target_mode: str = "original"
    # Only consulted when resource_target_mode == "custom_resource". Deliberately not
    # validated against "does this collide with a real file/entry name" here — that's
    # checked live at import time, inside import_object_content_raw() itself, since the
    # answer depends on whichever game happens to be loaded, not something a
    # settings-load-time check could know.
    resource_name: str = "res_new.resource"

    # VideoClip converted-import transcode (core.video_transcode) — target
    # codec/quality ONLY, remembered as a convenience across imports. The
    # CHECKBOX that actually enables transcoding is deliberately NOT
    # persisted anywhere (no CONFIG field for it at all) — real reported
    # design goal: transcoding is real, potentially slow encoding work, and
    # this app's own established preference is that it must never run except
    # as an explicit, one-off choice via "...с настройками"; the plain
    # silent "Импортировать из файла..." action must never see it turn
    # itself on. Remembering the target/quality doesn't reintroduce that
    # risk — the checkbox still has to be explicitly re-checked every single
    # time — it just means the dialog doesn't reset back to "h264"/70 after
    # the user deliberately picked "vp8" last time, which was itself a real
    # reported point of confusion (a subsequent import looked like it used
    # the wrong format, when it had actually just silently reset).
    #
    # "original" is a synthetic sentinel (not a real core.video_transcode.
    # TRANSCODE_TARGETS key) meaning "match the object's own current
    # container" — resolved at the point of actually importing (see
    # object_actions._show_converted_import_settings_dialog and
    # object_preview.import_object_converted's VideoClip branch), never
    # stored anywhere as a literal transcode target. Replaces an earlier
    # design that silently auto-picked a matching format behind the user's
    # back on every dialog open — real feedback was that an explicit,
    # rememberable "same as original" choice in the dropdown itself is
    # clearer than a default that quietly changes depending on what object
    # happens to be selected.
    video_transcode_target: str = "original"
    video_transcode_quality: int = 70

    # Settings -> «Показывать отладочные сообщения»: lines logged at LogLevel.DEBUG (stdlib
    # logging.DEBUG) appear in the log window only when this is on.
    show_debug_log: bool = False

# CONFIG is read from DataLoaderThread (background thread) during loading, and mutated
# from the GUI thread by menu/dialog handlers. As long as start_loading_data() blocks a
# second concurrent load, the only risk is mutating CONFIG via the "Settings" dialogs WHILE
# a load is already in progress (e.g. changing the fallback version mid-file-read).
CONFIG = AppConfig()

# Everything else on CONFIG (selected files/dirs, unity_cn_key, fallback_version, ...) is
# per-session by design — it describes "what am I loading right now", not a preference.
# These four are genuine settings the user configures once via a menu and expects to
# stick across restarts (theme already persists the same way, via theme.py's own
# QSettings calls) — same QSettings store ("UStudio", "UStudio"), a dedicated group so
# these keys can't collide with theme's or the last-dir keys main.py also keeps there.
_PERSISTED_CONFIG_GROUP = "persisted_config"


def _validate_cab_collision_policy(value):
    if value == "raise":
        return "raise"
    # "keep_last" and "ask" (the interactive dialog) were removed; a saved one is migrated.
    return "keep_first" if value in ("keep_first", "keep_last", "ask") else None


def _validate_excluded_folders(value):
    if isinstance(value, str):
        value = [value] if value else []
    return list(value or [])


def _validate_export_grouping(value):
    return value if value in ("none", "type", "source") else None


def _validate_bundle_compression_packer(value):
    return value if value in ("original", "none", "lz4", "lzma") else None


def _validate_indexed_types(value):
    if isinstance(value, str):
        value = [value] if value else []
    return list(value or [])


def _validate_preview_font_size(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if 6 <= value <= 32 else None


def _validate_char_coverage_label(value):
    value = str(value or "").strip()
    return value or None  # empty/whitespace-only: fall back to the built-in default


def _validate_char_coverage_chars(value):
    value = str(value or "")
    return value or None  # empty: fall back to the built-in default (never "checks nothing")


def _validate_texture_import_quality(value):
    return value if value in ("medium", "high") else None


def _validate_texture_import_format_mode(value):
    return value if value in ("match_original", "manual") else None


def _validate_texture_import_manual_format(value):
    valid_names = {name for name, _family, _label in TEXTURE_MANUAL_FORMAT_OPTIONS}
    return value if value in valid_names else None


def _validate_audio_import_quality(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


def _validate_resource_target_mode(value):
    return value if value in ("original", "custom_resource") else None


def _validate_resource_name(value):
    # Same idea as excluded_folders/indexed_types: a non-string persisted value (or one
    # that's gone empty/whitespace-only) falls back to the field's own default rather
    # than persisting something import_object_content_raw() would have to re-validate
    # anyway.
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _validate_video_transcode_target(value):
    return value if value in ("original", "h264", "vp8") else None


def _validate_video_transcode_quality(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


# (CONFIG attribute name, QSettings `type=` coercion or None, validator/normalizer or
# None) — one entry per persisted setting, driving both load_persisted_config() and
# save_persisted_config() below so adding a new persisted setting can't desync the two
# (previously each hand-listed the same 4 keys independently).
PERSISTED_FIELDS = (
    ("object_count_threshold", int, None),
    ("cab_collision_policy", None, _validate_cab_collision_policy),
    ("excluded_folders", None, _validate_excluded_folders),
    ("load_all_assets", bool, None),
    ("preview_enabled", bool, None),
    ("show_tree_view", bool, None),
    ("show_dump_view", bool, None),
    ("show_structure_view", bool, None),
    ("autoplay_audio", bool, None),
    ("show_debug_log", bool, None),
    ("show_quick_filters_bar", bool, None),
    ("export_grouping", None, _validate_export_grouping),
    ("export_assets_subfolder", bool, None),
    ("export_overwrite", bool, None),
    ("backup_before_overwrite", bool, None),
    ("backup_keep_latest", int, None),
    ("export_open_folder_after", bool, None),
    ("bundle_compression_packer", None, _validate_bundle_compression_packer),
    ("indexed_types", None, _validate_indexed_types),
    ("preview_font_family", None, None),
    ("preview_font_size", int, _validate_preview_font_size),
    ("char_coverage_label", None, _validate_char_coverage_label),
    ("char_coverage_chars", None, _validate_char_coverage_chars),
    ("texture_import_format_mode", None, _validate_texture_import_format_mode),
    ("texture_import_manual_format", None, _validate_texture_import_manual_format),
    ("texture_import_quality", None, _validate_texture_import_quality),
    ("texture_import_mipmaps", bool, None),
    ("audio_import_quality", int, _validate_audio_import_quality),
    ("resource_target_mode", None, _validate_resource_target_mode),
    ("resource_name", None, _validate_resource_name),
    ("video_transcode_target", None, _validate_video_transcode_target),
    ("video_transcode_quality", int, _validate_video_transcode_quality),
)


def load_persisted_config() -> None:
    settings = app_settings()
    settings.beginGroup(_PERSISTED_CONFIG_GROUP)
    for name, qtype, validator in PERSISTED_FIELDS:
        current = getattr(CONFIG, name)
        value = settings.value(name, current, type=qtype) if qtype is not None else settings.value(name, current)
        if validator is not None:
            value = validator(value)
            if value is None:
                continue  # invalid/unrecognized persisted value — keep the current default
        setattr(CONFIG, name, value)

    raw_presets = settings.value("sdf_character_presets", "")
    # Key absent = first run: keep the built-in default preset. Once saved (even
    # as an empty {}), the stored value wins, so a deleted default stays deleted.
    if raw_presets:
        try:
            parsed = json.loads(raw_presets)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            CONFIG.sdf_character_presets = {str(k): str(v) for k, v in parsed.items()}

    settings.endGroup()


def save_persisted_config() -> None:
    settings = app_settings()
    settings.beginGroup(_PERSISTED_CONFIG_GROUP)
    for name, _qtype, _validator in PERSISTED_FIELDS:
        settings.setValue(name, getattr(CONFIG, name))
    settings.setValue("sdf_character_presets", json.dumps(CONFIG.sdf_character_presets))
    settings.endGroup()


def reset_persisted_config() -> None:
    """Clears every PERSISTED_FIELDS key from QSettings — used by
    ApplicationSettingsDialog's "Сбросить все настройки" button. Deliberately
    does NOT touch the live CONFIG singleton, so nothing changes mid-session
    (e.g. excluded_folders shifting under an in-progress load) — the reset
    only takes effect the next time load_persisted_config() runs, i.e. after
    the app is restarted."""
    settings = app_settings()
    settings.beginGroup(_PERSISTED_CONFIG_GROUP)
    settings.remove("")
    settings.endGroup()
