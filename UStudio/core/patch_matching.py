"""Matching files in a patches folder to loaded objects, and applying the matches."""

from core.i18n import tr
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Tuple
from . import video_transcode as _video_transcode

from .object_common import resolve_object_name, resolve_script_name
from .object_content_raw import import_object_content_raw
from .object_export import build_export_stem, sanitize_export_filename
from .sdf_map import SDF_MAP_FILENAME
from .object_import import import_object_converted, import_object_json, import_object_raw, partial_parse_block_reason
from .object_resources import peek_videoclip_ext


# build_export_stem()'s "#{path_id} ({source})" suffix is the only place a "#"/
# "("/")" can appear in an export filename — sanitize_export_filename()'s
# allow-list (alnum + "._- ") strips those characters out of every embedded
# name/script/source fragment, so this search is unambiguous regardless of what
# the object's own name/script/source contained. Path IDs are signed 64-bit,
# hence the leading "-?".
_PATCH_STEM_RE = re.compile(r"#(-?\d+)\s*\(([^()]+)\)")


# ".dump.json"/".dump.bin"/".resdata.bin" are all compound (two-dot) suffixes —
# each must be checked via endswith() before the bare single-suffix case below,
# since Path.suffix only ever reports the LAST dot-segment (".json"/".bin"/".bin"
# respectively) which would otherwise misroute all three into the generic
# _CONVERTED_SUFFIXES ".bin"/".json" branch (mode "converted" — wrong for all of
# them). ".dump.bin"/".resdata.bin" are deliberately distinct from
# export_object()'s own unrelated ".raw.bin" fallback name (still classified as
# "converted" below, via the generic ".bin" branch — that fallback dump was never
# meant to be re-imported through this matcher in the first place) and from
# Mesh's converted ".obj" export, so none of these ever collide with each other
# on disk or in this matcher. ".png" added for Texture2D's converted import
# (import_object_converted). ".wav" added for AudioClip's (PCM/Vorbis only —
# see UnityPy/helpers/Fsb5Encoder.py for why the rest of Unity's
# AudioCompressionFormat values aren't supported). ".mp4"/".webm" added for
# VideoClip's (packaging only, no transcode — see probe_video_mismatch_warning
# for the pre-flight sanity check that's the only thing standing in for
# format validation here). ".ttf"/".otf" added for Font's converted import —
# real reported bug: import_object_converted() already had a working Font
# branch (raw bytes straight into m_FontData, no format-specific parsing
# needed either way) but this matcher never listed either extension, so
# picking a real .ttf/.otf file always failed with "unrecognized file
# extension" before ever reaching that branch. Every other converted-export
# extension this matcher doesn't list (.obj, .shader, ...) still has no
# importer behind it at all.
_CONVERTED_SUFFIXES = {
    ".json", ".txt", ".bin", ".png", ".wav", ".mp4", ".webm", ".ttf", ".otf",
    # VideoClip transcode SOURCE containers — deliberately only extensions
    # this project's own vendored ffmpeg build can actually demux (mov,
    # matroska, avi, webm, ogg — confirmed against its real enabled-demuxer
    # list, not guessed; .flv/.wmv/.mpg etc. were left out of that trimmed
    # build and would just fail with a confusing ffprobe error instead of a
    # clean "wrong extension" one). Plain packaging's own .mp4/.webm-only
    # allow-list (_CONVERTED_IMPORT_EXTENSIONS) is untouched and still
    # applies whenever video_transcode isn't on — see
    # import_object_converted()'s own bypass condition for why widening
    # THIS set doesn't weaken that.
    ".mkv", ".avi", ".mov", ".m4v", ".ogv",
}


def classify_import_mode(filename: str) -> Optional[str]:
    """Extension -> import mode. Used both by match_patch_files() below (the two
    folder-based mass-import paths) and directly by object_actions.py's single-file
    "Import from File..." (which has no filename-pattern matching to do, just an
    extension to dispatch on) — one source of truth for the mapping either way."""
    lower_name = filename.lower()
    if lower_name.endswith(".dump.json"):
        return "json_dump"
    if lower_name.endswith(".dump.bin"):
        return "raw"
    if lower_name.endswith(".resdata.bin"):
        return "content_raw"
    suffix = Path(filename).suffix.lower()
    if suffix in _CONVERTED_SUFFIXES:
        return "converted"
    return None  # a recognized converted-export extension with no importer (.obj, .shader,


# Which object types a converted file is meant for, by extension — used when ONE file is written into
# a whole selection, so objects it does not fit are left out instead of failing one by one.
_SUFFIX_OBJECT_TYPES = {
    ".png": {"Texture2D", "Sprite"},
    ".wav": {"AudioClip"},
    ".mp4": {"VideoClip"}, ".webm": {"VideoClip"}, ".mkv": {"VideoClip"}, ".avi": {"VideoClip"},
    ".mov": {"VideoClip"}, ".m4v": {"VideoClip"}, ".ogv": {"VideoClip"},
    ".ttf": {"Font"}, ".otf": {"Font"},
    ".txt": {"TextAsset"}, ".json": {"TextAsset"}, ".bin": {"TextAsset"},
}
SINGLE_FILE_FOR_SELECTION_TYPES = set().union(*_SUFFIX_OBJECT_TYPES.values())


def types_for_converted_suffix(filename: str) -> Optional[set]:
    """The object types a converted-import file with this extension fits, or None when unknown."""
    return _SUFFIX_OBJECT_TYPES.get(Path(filename).suffix.lower())


@dataclass
class MatchedPatch:
    obj: Any  # UnityPy.files.ObjectReader.ObjectReader
    file_path: Path
    mode: str  # "json_dump" | "raw" | "content_raw" | "converted"
    display_name: str
    # Same (path_id, source) the match was keyed on — split out from display_name
    # so ImportMatchDialog can show them as their own sortable columns instead of
    # parsing them back out of the combined "{name} #{path_id} ({source})" string.
    path_id: int = 0
    source: str = ""
    # Only meaningful for mode == "converted" and a Texture2D target — see
    # import_object_converted()'s own docstring for why this module can't just
    # read CONFIG.texture_import_* itself. None means "use
    # import_object_converted()'s own hardcoded defaults", which callers that
    # never resolved a real value (tests, anything not driven by the GUI) can
    # rely on instead of having to pass every field through by hand.
    texture_quality: Optional[str] = None
    texture_mipmaps: Optional[bool] = None
    texture_format_mode: Optional[str] = None
    texture_manual_format: Optional[str] = None
    # Same "None = use import_object_converted()'s own default" convention,
    # for AudioClip's FSBank quality (0-100) instead of the texture axes above.
    audio_quality: Optional[int] = None
    # Same "None = use the importer's own default" convention, for mode ==
    # "content_raw" and for "converted" targets that delegate to it internally
    # (AudioClip/VideoClip) — see import_object_content_raw()'s own docstring.
    resource_target_mode: Optional[str] = None
    resource_name: Optional[str] = None
    # Same "None = use the importer's own default" convention, for whether/how
    # import_object_content_raw() backs up a loose resource file the first
    # time this session writes to it — see that function's own docstring.
    backup_before_overwrite: Optional[bool] = None
    backup_keep_latest: Optional[int] = None
    # Same "None = use the importer's own default" convention, for
    # VideoClip's optional transcode-before-packaging step — see
    # import_object_converted()'s own docstring. Set by the single-object
    # "Импортировать из файла (с настройками)..." path, by the CLI's
    # `import` command, and by the GUI's own bulk folder-import path
    # (object_actions.py's _import_patches_from_folder()) — all three go
    # through match_patch_files()'s own video_transcode* params (see that
    # function's docstring for how a batch — no per-object dialog
    # opportunity — gets a real output path per clip anyway).
    video_transcode: Optional[bool] = None
    video_transcode_target: Optional[str] = None
    video_transcode_quality: Optional[int] = None
    video_transcode_output_path: Optional[str] = None
    # True when the patch filename's embedded name/script.name no longer
    # matches what this same (source, path_id) slot currently resolves to —
    # see match_patch_files()'s own comment for why this is a real, cheap
    # signal that path_id may have been reassigned to a different object
    # across a game update, not proof of anything wrong on its own (a
    # deliberately renamed export file would also trigger it).
    # ImportMatchDialog surfaces this as an unchecked-by-default warning
    # rather than either blocking the match or silently trusting it.
    name_mismatch: bool = False
    # What the identity check above compared: "name" (the export name — for a
    # MonoBehaviour "Script.ObjectName"), "script" (the referenced script's
    # class name, MonoBehaviour only — see _check_patch_identity()) or
    # "shifted" (a nameless patch whose neighbours in the same file no longer
    # match — _flag_nameless_in_shifted_files()). declared_name/current_name
    # hold the two values that disagreed ("name"/"script"), so a caller's
    # warning text can say what was actually compared instead of a generic "name".
    mismatch_kind: str = "name"
    declared_name: str = ""
    current_name: str = ""
    # True when the check couldn't run at all (a MonoBehaviour whose script
    # doesn't resolve right now, or whose patch was exported while it
    # didn't; a nameless patch with no named patch of its file around it) —
    # distinct from name_mismatch: nothing is known to be wrong, there's just
    # nothing to confirm it against.
    name_unverified: bool = False


# peek_mb_name()'s own "couldn't determine" value (core/file_utils.py) — also
# what a filename exported while the script didn't resolve carries as its
# script part. Neither side of a comparison against it means anything.
_UNRESOLVED_SCRIPT_NAME = "Unknown"


# A dump read only to confirm whose it is (_dump_names_this_object): bigger files are not opened for that.
_IDENTITY_PROBE_MAX_BYTES = 64 * 1024 * 1024


def _pptr_key(value) -> Optional[Tuple[int, int]]:
    if not isinstance(value, dict):
        return None
    try:
        return int(value.get("m_FileID", 0)), int(value.get("m_PathID", 0))
    except (TypeError, ValueError):
        return None


def _dump_names_this_object(obj_ref, patch_path: Optional[Path], mode: str) -> bool:
    """True when a MonoBehaviour's .dump.json says by its own content that it belongs to `obj_ref`, although the
    name in its FILE name differs from the object's: its m_Name equals the object's (an m_Name changed by an earlier
    install of the same patch), or — no m_Name — its m_GameObject points where the object's does (the borrowed
    GameObject name changed). Any doubt (another mode, unreadable, too big) is False."""
    if mode != "json_dump" or patch_path is None:
        return False
    try:
        if patch_path.stat().st_size > _IDENTITY_PROBE_MAX_BYTES:
            return False
        with open(patch_path, encoding="utf-8") as f:
            data = json.load(f)
        current = obj_ref.peek_dict(("m_GameObject", "m_Name")) or {}
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    name = data.get("m_Name")
    if isinstance(name, str) and name:
        return name == current.get("m_Name")
    owner = _pptr_key(data.get("m_GameObject"))
    return owner is not None and owner[1] != 0 and owner == _pptr_key(current.get("m_GameObject"))


def _check_patch_identity(obj_ref, path_id: int, declared_prefix: str, patch_path: Optional[Path] = None,
                          mode: str = "") -> Tuple[bool, bool, str, str, str]:
    """Sanity-checks that a patch file still belongs to the object sitting at its
    (source, path_id) slot — see match_patch_files()'s docstring for why this
    exists at all. `declared_prefix` is everything in the filename before
    " #{path_id}" (build_export_stem()'s own stem). Returns (mismatch,
    unverified, kind, declared_label, current_label).

    MonoBehaviour compares the script class name first ("script" mismatch), then
    the whole name: "ScriptName.ObjectName", where the object part is the
    object's own m_Name or — when that's empty — the attached GameObject's name
    borrowed by _peek_gameobject_fallback_name(). It used to compare the script
    ONLY, on the grounds that neither name is a stable identity; measured on a
    real game update (Phonopolis, USTUDIO_CLI_KNOWN_BUGS.md C7) that let patches
    through onto the neighbouring object of the same script when PathIDs shifted
    (about 1 in 80 MonoBehaviour patches written to another object, silently).
    The two cases that rule was for are still let through, by the patch's own
    content (_dump_names_this_object): an m_Name the patch itself changed (it
    was installed before) and a renamed GameObject. The script comparison is a
    `startswith` on the sanitized script name rather than a split on the first
    ".": sanitize_export_filename() keeps dots, so a script whose class name
    contains one would break a split, and object names like "Main.Camera" mean a
    split-from-the-right is wrong too.

    Every other type keeps the original full-stem comparison against
    build_export_stem()'s own name part."""
    type_name = getattr(getattr(obj_ref, "type", None), "name", "")

    if type_name == "MonoBehaviour":
        current_script = resolve_script_name(obj_ref)
        declared_script = declared_prefix.split(".", 1)[0]
        if current_script == _UNRESOLVED_SCRIPT_NAME:
            return False, True, "script", declared_script, current_script
        current_key = sanitize_export_filename(current_script, fallback="Script")
        if declared_prefix == current_key:
            return False, False, "script", current_key, current_key
        if not declared_prefix.startswith(current_key + "."):
            if declared_script == _UNRESOLVED_SCRIPT_NAME:
                return False, True, "script", declared_script, current_key
            return True, False, "script", declared_script, current_key
        current_name = build_export_stem(obj_ref).split(f" #{path_id}", 1)[0]
        if declared_prefix == current_name or _dump_names_this_object(obj_ref, patch_path, mode):
            return False, False, "name", declared_prefix, current_name
        return True, False, "name", declared_prefix, current_name

    current_stem = build_export_stem(obj_ref)
    current_name = current_stem.split(f" #{path_id}", 1)[0]
    return declared_prefix != current_name, False, "name", declared_prefix, current_name


def _has_no_name(obj_ref, declared_prefix: str) -> bool:
    """A patch whose file name carries no name of its own to check: "Script.Unnamed" (build_export_stem()'s
    nameless MonoBehaviour) or a bare type name (any other nameless object)."""
    type_name = getattr(getattr(obj_ref, "type", None), "name", "")
    if type_name == "MonoBehaviour":
        return declared_prefix.endswith(".Unnamed")
    return declared_prefix == type_name


def _flag_nameless_in_shifted_files(matches: List["MatchedPatch"], nameless: set, slot_gone: list) -> None:
    """A nameless patch passes the name check by definition (its slot is nameless too), so after a game update
    renumbered a file it lands on whatever object now has its old PathID. The only evidence is the folder's NAMED
    patches of the same file: if the nearest one below or above it (by PathID) no longer matches its slot, the file
    was renumbered there and the nameless patch is flagged (mismatch_kind "shifted"); with no named patch around it
    it is only "unverified". Measured on the Phonopolis update: every nameless patch this places was right."""
    import bisect
    named: dict = {}                          # source -> [(path_id, still matches)]
    for m in matches:
        if id(m) not in nameless and not m.name_unverified:
            named.setdefault(m.source, []).append((m.path_id, not m.name_mismatch))
    for _path, path_id, source in slot_gone:
        named.setdefault(source, []).append((path_id, False))
    for entries in named.values():
        entries.sort()
    for m in matches:
        if id(m) not in nameless or m.name_mismatch:
            continue
        entries = named.get(m.source, [])
        k = bisect.bisect_left(entries, (m.path_id, False))
        around = [entries[j] for j in (k - 1, k) if 0 <= j < len(entries)]
        if not around:
            m.name_unverified = True
        elif not all(ok for _pid, ok in around):
            m.name_mismatch, m.mismatch_kind = True, "shifted"


@dataclass
class PatchFolderScan:
    """What a patch folder actually contains, in the two stages a file has to
    clear to be importable at all — kept separate so a caller can say WHICH
    stage failed (nothing follows the naming convention vs. it does but has an
    extension no importer handles) instead of one generic "nothing matched".

    files_scanned: every regular file under the folder (recursive).
    name_matches: how many of those follow build_export_stem()'s
        "... #{path_id} ({source}) ..." convention.
    importable: (path, the _PATCH_STEM_RE match, mode) for each of THOSE whose
        extension classify_import_mode() has an importer for.
    sdf_maps: every sdf_map.txt found (core.sdf_map) — a second kind of input that
        names its targets by font name, not by the export naming."""
    files_scanned: int = 0
    name_matches: int = 0
    importable: List[Tuple[Path, "re.Match", str]] = field(default_factory=list)
    sdf_maps: List[Path] = field(default_factory=list)

    @property
    def has_anything_to_import(self) -> bool:
        return bool(self.importable or self.sdf_maps)


def scan_patch_folder(folder: Path) -> PatchFolderScan:
    """Recursively scans `folder` for patch files — recursive because
    ExportSettingsDialog's grouping mode nests exports under type/source
    subfolders, and a flat scan would fail to re-import the app's own grouped
    output. Cheap (names only, no file is opened), so a caller can run it BEFORE
    committing to a slow load to find out whether there's anything to import at
    all. Says nothing about whether any of it matches a loaded object — that's
    match_patch_files()'s job, which builds on this."""
    scan = PatchFolderScan()
    for path in Path(folder).rglob("*"):
        if not path.is_file():
            continue
        scan.files_scanned += 1
        if path.name.lower() == SDF_MAP_FILENAME:
            scan.sdf_maps.append(path)
            continue
        m = _PATCH_STEM_RE.search(path.name)
        if not m:
            continue
        scan.name_matches += 1
        mode = classify_import_mode(path.name)
        if mode is None:
            continue
        scan.importable.append((path, m, mode))
    return scan


# Order in which SEVERAL patch files for the SAME object are applied. Each later mode
# starts from the object's CURRENT state, so the coarsest/most-stale state goes first
# and the most deliberate, derived edit last:
#   raw          (.dump.bin)     replaces the whole serialized object -> wipes anything before it
#   json_dump    (.dump.json)    rewrites every typetree field, INCLUDING the old pixel/stream
#                                fields it was exported with -> reverts anything before it
#   content_raw  (.resdata.bin)  replaces the external resource payload
#   converted    (.png/.wav/...) re-encodes an edited source file into the object -> applied last
#                                so an edited PNG wins over the unedited dump/raw copies
# Verified on real Petscop textures: converted->json and converted->raw both silently put the
# ORIGINAL pixels back; raw->json->converted keeps the edit. Before this the order was simply
# whatever Path.rglob() yielded (alphabetical by filename on NTFS, not guaranteed).
IMPORT_MODE_ORDER = {"raw": 0, "json_dump": 1, "content_raw": 2, "converted": 3}


def order_patches_for_apply(matches: List["MatchedPatch"]) -> List["MatchedPatch"]:
    """Stable: objects keep the order they first appeared in; patches of one object are
    sorted by IMPORT_MODE_ORDER (ties keep scan order)."""
    first_seen: dict = {}
    for m in matches:
        first_seen.setdefault((m.source, m.path_id), len(first_seen))
    return sorted(matches, key=lambda m: (first_seen[(m.source, m.path_id)], IMPORT_MODE_ORDER.get(m.mode, 99)))


def _skipped_in(files, path_id: int):
    """The object `path_id` of the first of `files` whose large load skipped it (its type), or None."""
    for assets_file in files:
        skipped = getattr(assets_file, "skipped_object", None)
        try:
            obj = skipped(path_id) if skipped is not None else None
        except Exception:
            obj = None
        if obj is not None:
            return obj
    return None


def adopted_without_row(objects, rows) -> list:
    """The `objects` a patch adopted into their file (their type was not loaded) that have no row in `rows` yet —
    callers append rows for them: saving is driven by the rows (core.save_manager.find_modified_roots)."""
    have = {id(r.get("obj_ref")) for r in rows}
    out, seen = [], set()
    for obj in objects:
        if id(obj) in have or id(obj) in seen:
            continue
        if obj.path_id in getattr(getattr(obj, "assets_file", None), "adopted_ids", ()):
            seen.add(id(obj))
            out.append(obj)
    return out


def match_patch_files(
    folder: Path,
    candidates: Iterable[Tuple[int, str, Any]],
    *,
    texture_quality: Optional[str] = None,
    texture_mipmaps: Optional[bool] = None,
    texture_format_mode: Optional[str] = None,
    texture_manual_format: Optional[str] = None,
    audio_quality: Optional[int] = None,
    resource_target_mode: Optional[str] = None,
    resource_name: Optional[str] = None,
    backup_before_overwrite: Optional[bool] = None,
    backup_keep_latest: Optional[int] = None,
    video_transcode: Optional[bool] = None,
    video_transcode_target: Optional[str] = None,
    video_transcode_quality: Optional[int] = None,
    unmatched: Optional[list] = None,
) -> List[MatchedPatch]:
    """Recursively scans `folder` for files whose name encodes "#{path_id} ({source})"
    (build_export_stem()'s convention) and matches them against `candidates` — an
    iterable of (path_id, source, obj_ref) triples, so the same function serves both
    RowItems (pre-extracted by the caller) and raw ObjectReaders from
    collect_serialized_files() without caring which. Recursive because
    ExportSettingsDialog's grouping mode already nests exports under type/source
    subfolders — a flat scan would fail to re-import the app's own grouped output.

    A file matching the naming pattern but pointing at an object not present in
    `candidates`, or whose extension has no matching importer, is skipped — not an
    error for the GUI, most folders will contain unrelated files. A caller that treats
    the folder as a SET of patches (the CLI's `import`, an installer) passes a list as
    `unmatched`: every importable patch file whose (path_id, source) matches no
    candidate is appended to it as (path, path_id, source), so a patch that quietly
    found nothing (typically: a game update shifted the ids) can be reported instead
    of vanishing — see USTUDIO_CLI_KNOWN_BUGS.md, C1. Files whose extension has no
    importer are never reported there.

    texture_quality/texture_mipmaps/texture_format_mode are stamped onto every
    resulting "converted"-mode match (harmless no-op for any other mode) — a
    batch folder import has no per-object dialog opportunity, so the caller
    resolves CONFIG's saved defaults once and passes them in here rather than
    each match falling back to import_object_converted()'s own hardcoded ones.

    Real reported risk: matching is keyed purely on (path_id, source) — path_id
    is NOT a stable cross-build identifier, so a game update can silently
    reassign it to a completely different object, and a stale patch folder
    would then overwrite the wrong asset with no warning at all. The filename
    already embeds the object's name at export time (build_export_stem()'s own
    "{name} #{path_id} ({source})" convention, MonoBehaviour's own
    "{script}.{name} #{path_id} ({source})") — comparing that declared name
    against what this exact (source, path_id) slot resolves to RIGHT NOW is a
    free, already-available sanity check, not a new mechanism (see
    _check_patch_identity() for exactly what gets compared — for a
    MonoBehaviour, only the script part). It can't distinguish "path_id moved
    to a different object" from "the user renamed the export file by hand" —
    both look identical from here — so a mismatch is surfaced as a warning
    (MatchedPatch.name_mismatch, unchecked by default in ImportMatchDialog),
    never a silent block or a silent pass. A check that couldn't run at all
    (MatchedPatch.name_unverified) is NOT a mismatch and doesn't uncheck
    anything.

    video_transcode/video_transcode_target/video_transcode_quality extend the
    same "stamp CONFIG's resolved default onto every match" convention above
    to VideoClip's own transcode-before-packaging step, for a caller that
    deliberately wants it available in a batch context — the CLI's `import`
    command (cli/commands.py) and the GUI's own bulk folder-import path
    (object_actions.py's _import_patches_from_folder(), fed from
    _resolve_bulk_texture_settings()'s dialog) both go through this.
    video_transcode_output_path can't be resolved the same way —
    there's no single shared destination for a whole batch of clips — so
    when video_transcode is truthy, each matched VideoClip gets its own
    output path auto-derived next to its own patch file (mirroring
    ConvertedImportSettingsDialog's "{stem}_transcoded{ext}" naming), with
    the extension resolved via the exact same target_for_container_ext()/
    peek_videoclip_ext() logic import_object_converted() itself falls back
    to for an unresolved "original" — so the guessed filename's extension
    can never disagree with what actually gets encoded into it later."""
    # Real, confirmed bug found via testing (not theoretical): a game folder
    # with its own internal backup/duplicate-content subfolder — the same
    # pattern CLAUDE.md already documents for Petscop, found again for a
    # Truck-kun fixture — can register TWO distinct objects that both claim
    # the identical (path_id, source) key: one backed by the real, current
    # file, one by a stale pre-update snapshot. The old code below built
    # `by_key` with a plain dict assignment per candidate, so whichever
    # object happened to come LAST in the caller's own iteration order
    # silently won the slot — no relationship to which one is actually
    # active in the game. Confirmed via a real export→modify→reimport round
    # trip: apply_matched_patch() reported success, but the object actually
    # holding the game's real data was never touched — the patch landed on
    # the OTHER, inactive duplicate instead, invisible unless you happen to
    # check that specific object's data afterward. Grouping first and then
    # preferring whichever candidate is backed by the file that actually WON
    # that source's cab-name registration (env.get_cab() — the same file any
    # real cross-file PPtr reference already resolves through) fixes this
    # for every caller of this function at once (the GUI's own "Импортировать
    # из папки..." action included, not just the CLI's `import`).
    groups: dict = {}
    files_by_source: dict = {}      # sanitized source -> its loaded files (for objects a large load skipped)
    for path_id, source, obj_ref in candidates:
        sanitized_source = sanitize_export_filename(str(source), fallback="unknown")
        groups.setdefault((path_id, sanitized_source), []).append((source, obj_ref))
        assets_file = getattr(obj_ref, "assets_file", None)
        if assets_file is not None:
            known = files_by_source.setdefault(sanitized_source, [])
            if not any(f is assets_file for f in known):
                known.append(assets_file)

    by_key: dict = {}
    for key, entries in groups.items():
        if len(entries) == 1:
            by_key[key] = entries[0][1]
            continue
        chosen = entries[-1][1]  # preserves the old "last one wins" fallback
        for source, obj_ref in entries:
            try:
                winning_cab = obj_ref.assets_file.environment.get_cab(source)
            except Exception:
                continue
            if obj_ref.assets_file is winning_cab:
                chosen = obj_ref
                break
        by_key[key] = chosen

    matches: List[MatchedPatch] = []
    nameless: set = set()                       # id() of the matches whose file name has no name to check
    slot_gone: list = []                        # (path, path_id, source) of the patches whose slot is gone
    for path, m, mode in scan_patch_folder(folder).importable:
        path_id = int(m.group(1))
        source = m.group(2)
        obj_ref = by_key.get((path_id, source))
        if obj_ref is None:
            # an object whose TYPE the load left out (a large load): read it through its file; applying the patch
            # adopts it into the file so the change is saved (SerializedFile.adopt_skipped) — the caller adds its
            # row (saving is driven by the rows)
            obj_ref = _skipped_in(files_by_source.get(source, ()), path_id)
        if obj_ref is None:
            slot_gone.append((path, path_id, source))
            if unmatched is not None:
                unmatched.append((path, path_id, source))
            continue

        # See this function's own docstring for why this check exists.
        # declared_prefix is everything in the filename before " #{path_id}" —
        # exactly build_export_stem()'s own stem prefix, so comparing it
        # against what the CURRENT object at this slot would export as is
        # comparing like with like. What exactly gets compared (m_Name, or
        # just the script for a MonoBehaviour) is _check_patch_identity()'s
        # business.
        declared_prefix = path.name[:m.start()].rstrip()
        name_mismatch, name_unverified, mismatch_kind, declared_name, current_name = _check_patch_identity(
            obj_ref, path_id, declared_prefix, path, mode,
        )

        video_transcode_output_path = None
        if video_transcode and mode == "converted" and getattr(obj_ref.type, "name", "") == "VideoClip":
            target_key = video_transcode_target or "original"
            if target_key == "original":
                target_key = (_video_transcode.target_for_container_ext(peek_videoclip_ext(obj_ref))
                              or next(iter(_video_transcode.TRANSCODE_TARGETS)))
            ext = _video_transcode.TRANSCODE_TARGETS[target_key]["container_ext"]
            video_transcode_output_path = str(path.with_name(path.stem + "_transcoded" + ext))

        matches.append(MatchedPatch(
            obj=obj_ref, file_path=path, mode=mode,
            display_name=f"{resolve_object_name(obj_ref)} #{path_id} ({source})",
            path_id=path_id,
            source=source,
            texture_quality=texture_quality,
            texture_mipmaps=texture_mipmaps,
            texture_format_mode=texture_format_mode,
            texture_manual_format=texture_manual_format,
            audio_quality=audio_quality,
            resource_target_mode=resource_target_mode,
            resource_name=resource_name,
            backup_before_overwrite=backup_before_overwrite,
            backup_keep_latest=backup_keep_latest,
            video_transcode=video_transcode,
            video_transcode_target=video_transcode_target,
            video_transcode_quality=video_transcode_quality,
            video_transcode_output_path=video_transcode_output_path,
            name_mismatch=name_mismatch,
            mismatch_kind=mismatch_kind,
            declared_name=declared_name,
            current_name=current_name,
            name_unverified=name_unverified,
        ))
        if _has_no_name(obj_ref, declared_prefix):
            nameless.add(id(matches[-1]))
    _flag_nameless_in_shifted_files(matches, nameless, slot_gone)
    return order_patches_for_apply(matches)


def apply_matched_patch(
    patch: "MatchedPatch", *,
    report_progress: Optional[Callable[..., None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Optional[str]:
    """Dispatches one MatchedPatch to the right import function by its mode — shared
    by both folder-import entry points' queued task loop, and by the single-object
    "Импортировать из файла..." action.

    A non-None return is normally an error, EXCEPT when it starts with
    IMPORT_WARNING_PREFIX — the AudioClip converted-import branch can return
    that for a successful import with an advisory attached (see its own
    comment in import_object_converted). Callers must check for the prefix
    before treating any non-None return as a failure.

    report_progress/should_cancel use the task_queue.TaskFn calling
    convention and are only actually consulted by a VideoClip patch with
    video_transcode set — every other mode/type is fast enough not to need
    them, so omitting these (the folder-import bulk loops currently do) is
    fine as long as none of the batch is a transcoding VideoClip, which
    match_patch_files() never produces (see MatchedPatch's own docstring on
    why video_transcode is single-object-only for now)."""
    if patch.mode in ("converted", "content_raw"):
        blocked = partial_parse_block_reason(patch.obj)
        if blocked:
            return blocked
    if patch.mode == "json_dump":
        return import_object_json(patch.obj, patch.file_path)
    if patch.mode == "raw":
        return import_object_raw(patch.obj, patch.file_path)
    if patch.mode == "content_raw":
        kwargs = {}
        if patch.resource_target_mode is not None:
            kwargs["resource_target_mode"] = patch.resource_target_mode
        if patch.resource_name is not None:
            kwargs["resource_name"] = patch.resource_name
        if patch.backup_before_overwrite is not None:
            kwargs["backup_before_overwrite"] = patch.backup_before_overwrite
        if patch.backup_keep_latest is not None:
            kwargs["backup_keep_latest"] = patch.backup_keep_latest
        return import_object_content_raw(patch.obj, patch.file_path, **kwargs)
    if patch.mode == "converted":
        kwargs = {}
        if patch.texture_quality is not None:
            kwargs["texture_quality"] = patch.texture_quality
        if patch.texture_mipmaps is not None:
            kwargs["texture_mipmaps"] = patch.texture_mipmaps
        if patch.texture_format_mode is not None:
            kwargs["texture_format_mode"] = patch.texture_format_mode
        if patch.texture_manual_format is not None:
            kwargs["texture_manual_format"] = patch.texture_manual_format
        if patch.audio_quality is not None:
            kwargs["audio_quality"] = patch.audio_quality
        if patch.resource_target_mode is not None:
            kwargs["resource_target_mode"] = patch.resource_target_mode
        if patch.resource_name is not None:
            kwargs["resource_name"] = patch.resource_name
        if patch.backup_before_overwrite is not None:
            kwargs["backup_before_overwrite"] = patch.backup_before_overwrite
        if patch.backup_keep_latest is not None:
            kwargs["backup_keep_latest"] = patch.backup_keep_latest
        if patch.video_transcode is not None:
            kwargs["video_transcode"] = patch.video_transcode
        if patch.video_transcode_target is not None:
            kwargs["video_transcode_target"] = patch.video_transcode_target
        if patch.video_transcode_quality is not None:
            kwargs["video_transcode_quality"] = patch.video_transcode_quality
        if patch.video_transcode_output_path is not None:
            kwargs["video_transcode_output_path"] = patch.video_transcode_output_path
        if patch.video_transcode:
            kwargs["report_progress"] = report_progress
            kwargs["should_cancel"] = should_cancel
        return import_object_converted(patch.obj, patch.file_path, **kwargs)
    return tr("Неизвестный режим импорта: {mode}", mode=patch.mode)
