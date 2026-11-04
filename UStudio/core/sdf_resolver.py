"""SDF font package resolution — PyQt-free, same layer as core/object_preview.py
(no PyQt import, reusable from a console front end or a standalone script).

A TMP_FontAsset is a MonoBehaviour/ScriptableObject reflected via
TypeTreeGenerator (not a built-in Unity type, so it has no TPK typetree of its
own — see core/loader.py's init_typetree()). It references a Material, which
in turn references the Texture2D holding its SDF atlas, and optionally the
original source .ttf/.otf (m_SourceFontFile, a Font object) it was generated
from. Together these make up one "SDF font package".

Field names CONFIRMED against a real TMP_FontAsset dump (Dump tab output from
a real game, not guessed): m_Material (capital M — the earlier m_material/
material guesses were both wrong), m_AtlasTextures (a populated list — the
correct, current field) alongside a present-but-always-empty legacy `atlas`
singular field (m_FileID=0, m_PathID=0 — must NOT be preferred over
m_AtlasTextures just because it's present, see _normalize_pptr()'s docstring
for the truthiness bug this caused), and m_SourceFontFile. The candidate
lists below still check multiple names defensively (older TMP package
versions may differ), but are now ordered with the confirmed real names
first.

Reads via font_obj.parse_as_object(), NOT parse_as_dict() — this matters:
UnityPy/helpers/TypeTreeHelper.py's read_value() only wraps a PPtr-typed
field into a real PPtr instance when config.as_dict is False (line ~259:
`if not config.as_dict: if node.m_Type.startswith("PPtr<"): value =
PPtr[Any](...)`) — parse_as_dict() skips that block entirely and leaves
PPtr-shaped values as plain {"m_FileID": ..., "m_PathID": ...} dicts,
confirmed both by reading this function directly and by reproducing it
against the real TypeTreeHelper with a synthetic node tree (as_dict=True ->
dict, as_dict=False -> real PPtr, same input bytes). An earlier version of
this module used parse_as_dict() and worked around the dict-shaped PPtrs by
hand-reconstructing them (see _normalize_pptr()) — unnecessary complexity
once the actual UnityPy entry point is the right one; kept only as a cheap
defensive fallback below, not the primary mechanism."""

from core.i18n import N_, tr
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from UnityPy.classes import PPtr as _PPtr

from .loader import build_row_item
from .object_metadata import char_coverage_codepoints
from .progress import OperationCancelled
from .object_preview import (
    build_export_stem, export_object, get_row_name, get_row_script_name, resolve_object_name, resolve_script_name,
    sanitize_export_filename,
)

logger = logging.getLogger("ustudio.core.sdf_resolver")

# core.object_metadata imports sdf_font_supports_cyrillic() FROM this module
# for its own MonoBehaviour compact-summary branch — but does so via a
# LOCAL (inside-the-function) import specifically so this top-level import
# here doesn't create a real circular-import failure: by the time that
# function actually runs, both modules have already finished loading. See
# object_metadata.py's own _compact_monobehaviour() comment.

# The one script name that makes a MonoBehaviour row a TMP_FontAsset — every
# call site that already has a RowItem should compare item["script_name"]
# against this directly (a cheap dict lookup, already resolved at load time)
# instead of calling is_tmp_font_asset(obj) below, which re-derefs m_Script.
SDF_FONT_SCRIPT_NAME = "TMP_FontAsset"

_MATERIAL_FIELD_CANDIDATES = ("m_Material", "m_material", "material")
_ATLAS_LIST_FIELD_CANDIDATES = ("m_AtlasTextures", "m_atlasTextures")
_ATLAS_SINGLE_FIELD_CANDIDATES = ("m_AtlasTexture", "m_atlasTexture", "atlas", "m_Atlas")
_SOURCE_FONT_FIELD_CANDIDATES = ("m_SourceFontFile", "m_sourceFontFile", "sourceFontFile")
_MAIN_TEXTURE_PROPERTY_NAMES = ("_MainTex", "_texture", "_Texture")


@dataclass
class SDFComponents:
    font_obj: object  # ObjectReader for the TMP_FontAsset itself
    material_obj: Optional[object] = None
    texture_obj: Optional[object] = None
    source_font_obj: Optional[object] = None  # the original .ttf/.otf (Font), if linked
    material_error: str = ""
    texture_error: str = ""
    source_font_error: str = ""


def is_tmp_font_asset(obj) -> bool:
    """Standalone check for a bare ObjectReader with no RowItem at hand (e.g.
    from CabBrowserDialog). Prefer item["script_name"] == SDF_FONT_SCRIPT_NAME
    wherever a RowItem is already available — see the module docstring."""
    return obj.type.name == "MonoBehaviour" and resolve_script_name(obj) == SDF_FONT_SCRIPT_NAME


def _extract_character_codepoints(data: dict) -> Optional[set]:
    """m_CharacterTable is the current TMP format (confirmed against a real
    TMP_FontAsset dump — see sdf_font_supports_cyrillic()'s own docstring):
    each entry's Unicode codepoint lives in m_Unicode. Older TMP_FontAsset
    serializations (pre the GlyphTable/CharacterTable split introduced with
    TextMeshPro's dynamic-atlas rework) instead store this in m_glyphInfoList,
    whose per-entry codepoint field is named plainly `id` (no m_ prefix — an
    inconsistency in TextMeshPro's own legacy TMP_Glyph class, not a typo
    here). Not verified against a local fixture (every real TMP_FontAsset
    seen in this project's own fixtures already uses the current format,
    m_glyphInfoList present but empty on all of them) — instead confirmed
    against a known-working community dump/reimport script for exactly this
    legacy field and key name, per this project's own standing rule that a
    real, working reference is an acceptable substitute for a local fixture
    when neither is guessed.

    Only falls back to m_glyphInfoList when m_CharacterTable is missing/
    empty, not as an alternate/override source — "older SDF version" implies
    the current field genuinely isn't there, not that both might coexist."""
    table = data.get("m_CharacterTable")
    if table:
        codepoints = {c["m_Unicode"] for c in table if isinstance(c, dict) and "m_Unicode" in c}
        if codepoints:
            return codepoints
    legacy_table = data.get("m_glyphInfoList")
    if legacy_table:
        codepoints = {c["id"] for c in legacy_table if isinstance(c, dict) and "id" in c}
        if codepoints:
            return codepoints
    return None


def sdf_font_supports_cyrillic(font_obj, data=None) -> Optional[bool]:
    """data: an already-parsed font_obj.parse_as_dict() result a caller
    (object_metadata._compact_monobehaviour(), via build_preview()) computed
    once and wants reused — this used to be an independent full re-parse of
    the SAME TMP_FontAsset every single call, one of four redundant re-reads
    per object selection (see build_preview()'s own docstring). None by
    default, in which case this parses fresh exactly as before.

    Cyrillic-coverage check for the TMP_FontAsset ITSELF — a different
    question from object_metadata.font_supports_cyrillic() (which parses a
    raw .ttf/.otf file's own cmap table): an SDF font asset already declares
    exactly which Unicode codepoints it has a baked SDF glyph for, so there's
    no font-file bytes to parse at all here — see _extract_character_codepoints()
    for where that list actually comes from (current vs. legacy TMP format).

    Field names CONFIRMED against a real TMP_FontAsset dump (Phonopolis
    fixture, not guessed — see the module docstring's own note on why this
    project verifies TypeTreeGenerator-reflected field names against a real
    object before trusting them): m_CharacterTable is a flat list of dicts,
    each with an m_Unicode int field holding the plain decimal codepoint
    (confirmed range 0x20-0x20AC on that real font; NOT nested under an
    m_Character sub-object, and not named m_UnicodeValue on this TMP
    version). Reuses object_metadata.CYRILLIC_SAMPLE_RANGE and its same
    >=90% threshold so this check and the raw-font-file one agree on what
    "supports Cyrillic" means.

    Returns None (not False) when neither table is usable — most likely
    because this asset's own TypeTreeGenerator reflection failed (this
    project's own documented il2cpp-reflection gaps), in which case "can't
    tell" is the honest answer, not "no"."""
    if data is None:
        try:
            data = font_obj.parse_as_dict()
        except Exception:
            return None
    covered = _extract_character_codepoints(data)
    if covered is None:
        return None
    needed = set(char_coverage_codepoints())
    return len(covered & needed) >= len(needed) * 0.9


def sdf_font_coverage(font_obj):
    """(number of characters, supports Cyrillic) for a TMP_FontAsset, or None when its character table
    cannot be read. One parse of the asset — call it off the GUI thread."""
    try:
        data = font_obj.parse_as_dict()
    except Exception:  # noqa: BLE001 - "cannot tell" is the honest answer
        return None
    covered = _extract_character_codepoints(data)
    if covered is None:
        return None
    needed = set(char_coverage_codepoints())
    return len(covered), len(covered & needed) >= len(needed) * 0.9


def _peek_font_object(font_obj):
    try:
        return font_obj.parse_as_object()
    except EOFError:
        # The schema wants more bytes than the object has (a script definition from another
        # game/version): retrying without the length check fails identically — and a failing
        # parse can take seconds, so do not pay for it twice.
        raise
    except Exception:
        # Mirrors build_json_text()'s own fallback (core/object_preview.py) —
        # a partial parse still exposes the top-level fields this resolver
        # needs, even if some later field in the object fails to read.
        return font_obj.parse_as_object(check_read=False)


def _normalize_pptr(value, owner_obj) -> Optional[object]:
    """Defensive fallback only — parse_as_object() (what every caller here
    actually uses, see the module docstring) already returns real PPtr
    instances directly, confirmed both by reading TypeTreeHelper.read_value()
    and by reproducing it against a synthetic node tree. This just guards
    against a dict slipping through some path not yet observed, reconstructing
    a real PPtr anchored to owner_obj's own assets_file — correct for
    m_FileID == 0 (same-file) and for a genuine cross-file reference too,
    since PPtr.deref() resolves m_FileID via that assetsfile's own
    `externals` list regardless of how the PPtr object was built.

    Also why this checks m_PathID != 0 via PPtr.__bool__ rather than plain
    Python truthiness: a raw dict's truthiness only reflects whether the
    dict is non-empty, NOT whether the pointer is actually set — an
    explicitly-empty PPtr-shaped dict ({"m_FileID": 0, "m_PathID": 0}, e.g.
    TMP_FontAsset's legacy unused `atlas` field) would otherwise look
    "present"."""
    if value is None:
        return None
    if isinstance(value, dict):
        file_id = value.get("m_FileID")
        path_id = value.get("m_PathID")
        if file_id is None or path_id is None:
            return None
        value = _PPtr(m_FileID=file_id, m_PathID=path_id, assetsfile=owner_obj.assets_file)
    return value if value else None


def _first_pptr(obj, candidates, owner_obj) -> Optional[object]:
    for name in candidates:
        value = _normalize_pptr(getattr(obj, name, None), owner_obj)
        if value is not None:
            return value
    return None


def _first_pptr_from_list(obj, candidates, owner_obj) -> Optional[object]:
    for name in candidates:
        values = getattr(obj, name, None)
        if values:
            value = _normalize_pptr(values[0], owner_obj)
            if value is not None:
                return value
    return None


def _deref_safe(pptr, label: str) -> Tuple[Optional[object], str]:
    if pptr is None:
        return None, tr("ссылка на объект {label} пустая", label=label)
    try:
        return pptr.deref(), ""
    except Exception as e:
        return None, tr("не удалось разрешить ссылку для {label} — {error}", label=label, error=e)


def _texture_from_material(material_obj) -> Tuple[Optional[object], str]:
    try:
        data = material_obj.parse_as_object()
        tex_envs = data.m_SavedProperties.m_TexEnvs
    except Exception as e:
        return None, tr("не удалось прочитать материал — {error}", error=e)

    by_key = dict(tex_envs)
    env = None
    for key in _MAIN_TEXTURE_PROPERTY_NAMES:
        if key in by_key:
            env = by_key[key]
            break
    if env is None and tex_envs:
        # No recognized property name — fall back to the material's first
        # texture slot rather than giving up (an SDF shader routinely has
        # exactly one texture property regardless of its exact name).
        env = tex_envs[0][1]
    if env is None:
        return None, tr("у материала нет ни одного текстурного свойства")
    # Material is a built-in type (a static dataclass, not TypeTreeGeneratorAPI-
    # reflected — see _normalize_pptr()'s docstring), so env.m_Texture should
    # already be a real PPtr here; normalized defensively anyway rather than
    # assuming, now that the font-side fields already proved that assumption
    # wrong once.
    texture_pptr = _normalize_pptr(env.m_Texture, material_obj)
    if texture_pptr is None:
        return None, tr("у материала нет ни одного текстурного свойства")
    return _deref_safe(texture_pptr, "Texture2D")


_UNREADABLE_FONT_PREFIX = N_("не удалось прочитать шрифт")


def resolve_sdf_components(font_obj, known_unreadable: Optional[dict] = None) -> SDFComponents:
    """`known_unreadable` (optional, owned by the caller for ONE batch): {key: message} of font
    kinds that already failed to read in this batch — a later font of the same file and script
    type fails the same way, and a failing parse can take seconds, so it is not attempted again.

    Never raises — a dangling/unrecognized reference becomes an error
    string on the result instead, so a caller can still export/display
    whatever DID resolve (mirrors export_object()'s own partial-success
    convention)."""
    result = SDFComponents(font_obj=font_obj)
    kind_key = (id(getattr(font_obj, "assets_file", None)), id(getattr(font_obj, "serialized_type", None)))
    if known_unreadable is not None and kind_key in known_unreadable:
        result.material_error = result.texture_error = known_unreadable[kind_key]
        return result
    try:
        obj = _peek_font_object(font_obj)
    except Exception as e:  # noqa: BLE001 - one unreadable font must not take the whole SDF mode down
        # Real report: a folder holding two games (Emily is Away Too + EmilyOnline, different TextMeshPro
        # versions) read every font of the second one with the first game's script definitions, ran off
        # the end of the data (EOFError) and the uncaught error aborted switching to SDF mode.
        message = f"{tr(_UNREADABLE_FONT_PREFIX)} — {type(e).__name__}: {e}"
        result.material_error = result.texture_error = message
        if known_unreadable is not None:
            known_unreadable[kind_key] = message
        return result

    material_pptr = _first_pptr(obj, _MATERIAL_FIELD_CANDIDATES, font_obj)
    result.material_obj, result.material_error = _deref_safe(material_pptr, "Material")

    # m_AtlasTextures (the current, multi-atlas-capable list) checked BEFORE
    # the legacy singular atlas/m_AtlasTexture fields — confirmed against real
    # content that the singular `atlas` field can be PRESENT but always empty
    # (m_PathID=0) on a modern asset, while m_AtlasTextures holds the real
    # reference; only the reverse (a real singular field, no list) should fall
    # back to the list check, not the other way around.
    atlas_pptr = _first_pptr_from_list(obj, _ATLAS_LIST_FIELD_CANDIDATES, font_obj)
    if atlas_pptr is None:
        atlas_pptr = _first_pptr(obj, _ATLAS_SINGLE_FIELD_CANDIDATES, font_obj)

    if atlas_pptr is not None:
        result.texture_obj, result.texture_error = _deref_safe(atlas_pptr, "Txture2D")
    elif result.material_obj is not None:
        result.texture_obj, result.texture_error = _texture_from_material(result.material_obj)
    else:
        result.texture_error = tr("ни у шрифта, ни у материала нет ссылки на атлас")

    # Optional — most fonts have no linked source .ttf/.otf (Unity doesn't
    # require keeping it around at runtime), so an absent field/empty PPtr is
    # NOT an error, unlike material/texture above (which every real SDF font
    # package needs). Only a present-but-unresolvable reference is reported.
    source_pptr = _first_pptr(obj, _SOURCE_FONT_FIELD_CANDIDATES, font_obj)
    if source_pptr is not None:
        result.source_font_obj, result.source_font_error = _deref_safe(source_pptr, "Source Font")

    return result


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@dataclass
class SDFExportItemResult:
    label: str  # "font" | "material" | "texture"
    out_path: Optional[Path]
    message: Optional[str]
    skipped: bool


def export_sdf_package(
    components: SDFComponents, base_out_dir, overwrite: bool = True, folder_name: Optional[str] = None
) -> Tuple[Path, List[SDFExportItemResult]]:
    """One subfolder per font ({FontName}/font.json, material.json,
    texture.png, ...) — each component's own export_object() naming is kept
    as-is (already collision-safe), the subfolder is what bundles the three
    together under one clean, descriptive name.

    folder_name: pre-resolved, already-sanitized subfolder name — used by export_all_sdf_fonts()
    (via unique_sdf_folder_names() below) so two fonts that happen to share a name land in two
    DIFFERENT subfolders instead of one silently overwriting the other's files. None (the
    single-font "Только этот шрифт" export, which has no such batch to collide within) falls back
    to the plain font name, same as before."""
    font_name = folder_name or sanitize_export_filename(
        resolve_object_name(components.font_obj), fallback=f"font_{components.font_obj.path_id}"
    )
    out_dir = Path(base_out_dir) / font_name
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[SDFExportItemResult] = []
    for label, obj, prior_error in (
        ("font", components.font_obj, ""),
        ("material", components.material_obj, components.material_error),
        ("texture", components.texture_obj, components.texture_error),
        ("source_font", components.source_font_obj, components.source_font_error),
    ):
        if obj is None:
            if label == "source_font" and not prior_error:
                # No linked .ttf/.otf at all — routine (see resolve_sdf_components()),
                # not worth a "skipped" line cluttering the result the way a genuinely
                # missing material/texture is.
                continue
            results.append(SDFExportItemResult(label, None, prior_error or tr("{label}: объект не найден", label=label), True))
            continue
        out_path, message, skipped = export_object(obj, out_dir, overwrite=overwrite)
        results.append(SDFExportItemResult(label, out_path, message, skipped))
    return out_dir, results


# ---------------------------------------------------------------------------
# Grouping — SDF Viewer Mode's tree (see sdf_group_model.py)
# ---------------------------------------------------------------------------

@dataclass
class SDFGroup:
    group_id: str
    font: dict  # RowItem
    material: Optional[dict] = None
    texture: Optional[dict] = None
    source_font: Optional[dict] = None
    material_error: str = ""
    texture_error: str = ""

    def children(self) -> List[dict]:
        items = [self.font]
        for item in (self.material, self.texture, self.source_font):
            if item is not None:
                items.append(item)
        return items


def build_sdf_groups(row_items: List[dict], should_cancel=None, pacer=None) -> List[SDFGroup]:
    """One SDFGroup per TMP_FontAsset row in row_items. `should_cancel()` (optional) is polled once
    per row and raises OperationCancelled — this runs off the GUI thread and must stop promptly when
    superseded or when the loaded files are about to be released. `pacer` (a core.progress.Pacer, optional)
    rests the thread between rows and holds it while the user is busy: reading every MonoBehaviour's script
    here kept the GUI waiting for the GIL (Phonopolis' SDF view: 6 pauses over 100 ms in its first 30 s). Matches a resolved
    material/texture back to an EXISTING RowItem by (source, path_id) —
    Python object identity (`is`) is NOT reliable here: Environment.load_file()
    can transparently replace a SerializedFile (and every ObjectReader in it)
    on a later, unrelated cross-file PPtr resolution — see main.py's
    _jump_to_object() docstring for the confirmed case this works around.
    A component not already indexed in row_items (e.g. RICH_PREVIEW_TYPES
    excluded it, or it lives in a dependency file never pulled into the main
    table — see _jump_to_object() again) gets a synthetic RowItem built
    directly from its own ObjectReader instead, same shape build_row_item()
    always produces."""
    index = {(item.get("source"), item.get("path_id")): item for item in row_items}
    # With several games loaded, the same source name + PathID exists more than once: the
    # file object tells the rows apart (name + PathID stays the fallback for a reloaded file).
    file_index = {}
    for item in row_items:
        af = getattr(item.get("obj_ref"), "assets_file", None)
        if af is not None:
            file_index[(id(af), item.get("path_id"))] = item

    def _lookup(obj) -> Optional[dict]:
        if obj is None:
            return None
        existing = file_index.get((id(obj.assets_file), obj.path_id)) if obj.assets_file else None
        if existing is None:
            source = obj.assets_file.name if obj.assets_file else None
            existing = index.get((source, obj.path_id))
        if existing is not None:
            return existing
        return build_row_item(obj, include_all=True)

    groups: List[SDFGroup] = []
    unreadable: List[Tuple[str, str]] = []
    known_unreadable: dict = {}
    for item in row_items:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        if pacer is not None and not pacer.step():
            raise OperationCancelled()
        # script_name is lazily resolved on a RowItem now (see
        # core/object_preview.py's get_row_script_name()) — build_sdf_groups()
        # only ever runs while SDF mode is explicitly active, so paying to
        # resolve every row's script name here (there's no way to find the
        # SDF font packs without it) is the same intentional, on-demand-only
        # cost object_table.py's own sort-by-Script/search cases already pay.
        if get_row_script_name(item) != SDF_FONT_SCRIPT_NAME:
            continue
        components = resolve_sdf_components(item["obj_ref"], known_unreadable)
        if components.material_error.startswith(tr(_UNREADABLE_FONT_PREFIX)):
            unreadable.append((get_row_name(item), components.material_error))
        group_id = f"{item.get('source')}:{item.get('path_id')}"
        if any(g.group_id == group_id for g in groups):
            group_id = f"{group_id}#{len(groups)}"  # same file name in another game: keep ids unique
        groups.append(SDFGroup(
            group_id=group_id,
            font=item,
            material=_lookup(components.material_obj),
            texture=_lookup(components.texture_obj),
            source_font=_lookup(components.source_font_obj),
            material_error=components.material_error,
            texture_error=components.texture_error,
        ))
    # A→Z by font name (case-insensitive); same-named fonts keep a stable order by file and PathID.
    groups.sort(key=lambda g: (str(get_row_name(g.font)).casefold(), str(g.font.get("source")), g.font.get("path_id") or 0))
    if unreadable:
        logger.warning(tr("Не удалось прочитать SDF-шрифтов: %d. Подробности — в отладочных сообщениях."), len(unreadable))
        for name, message in unreadable:
            logger.debug("SDF-шрифт «%s»: %s", name, message)
    return groups


def unique_sdf_folder_names(groups: List[SDFGroup]) -> Dict[str, str]:
    """{group_id: subfolder name} for export_all_sdf_fonts() — real reported case: two SDF fonts
    can genuinely share the same name (the same font shipped twice under different scripts, a
    "Fallback" variant named after its base font, two different games/languages loaded together,
    ...), and plainly exporting each one to Path(base_dir)/{font_name} would put a second font's
    files on top of the first's, in the SAME folder, silently. Only a NAME that actually collides
    within this batch gets a disambiguating suffix — the common case (every name unique) still
    gets the same plain, clean folder name export_sdf_package() would use on its own.

    First disambiguation step matches build_export_stem()'s own established "#PathID (Source)"
    suffix convention used everywhere else in this project for exactly this kind of collision;
    if that STILL collides (two fonts sharing name AND source — the same file, so build_export_stem
    already includes both distinguishing pieces and would itself be identical), path_id alone is
    guaranteed unique per source and used as a last-resort suffix."""
    base_names = {
        g.group_id: sanitize_export_filename(
            resolve_object_name(g.font["obj_ref"]), fallback=f"font_{g.font['obj_ref'].path_id}"
        )
        for g in groups
    }
    counts: Dict[str, int] = {}
    for name in base_names.values():
        counts[name] = counts.get(name, 0) + 1

    result: Dict[str, str] = {}
    seen: Dict[str, int] = {}
    for g in groups:
        base = base_names[g.group_id]
        if counts[base] <= 1:
            result[g.group_id] = base
            continue
        candidate = sanitize_export_filename(
            build_export_stem(g.font["obj_ref"]), fallback=f"font_{g.font['obj_ref'].path_id}"
        )
        if seen.get(candidate, 0) > 0:
            candidate = f"{candidate}_{g.font['obj_ref'].path_id}"
        seen[candidate] = seen.get(candidate, 0) + 1
        result[g.group_id] = candidate
    return result
