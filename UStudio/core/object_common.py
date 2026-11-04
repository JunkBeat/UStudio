"""Shared constants, resource temp-file bookkeeping, format-name resolvers and object naming for the
per-object preview/export/import logic (see core/object_preview.py, the facade)."""

from core.i18n import tr
import atexit
import os
import struct
import sys
import traceback
from typing import Callable, Dict, List, Optional, Set, Tuple
from UnityPy.classes.PPtr import PPtr
from UnityPy.enums.TextureFormat import TextureFormat
from UnityPy.helpers.TypeTreeHelper import FUNCTION_READ_MAP
from .file_utils import ScriptIdentity, format_size, peek_mb_identity, shared_identity, peek_mb_name, peek_object_name
from .progress import OperationCancelled


# The curated set of types that get a real preview/export beyond a plain JSON dump —
# also used by core/loader.py's parse_objects() as the table's row filter (see that
# module's comment). Bounds table growth on huge fixtures to only the types actually
# worth individually browsing, instead of every Transform/RectTransform/etc.
RICH_PREVIEW_TYPES = {
    "MonoBehaviour", "Texture2D", "Texture2DArray", "Sprite", "AudioClip",
    "TextAsset", "Mesh", "Shader", "Font", "Material", "GameObject",
    "AnimationClip", "AnimatorController", "VideoClip", "TextMesh",
}


# Scratch temp files backing pending "custom resource" loose-file content-raw
# imports (see import_object_content_raw's use_custom branch below) — tracked
# process-wide, not per-Environment, purely so this atexit hook can clean up
# any that are still sitting in the OS temp directory when the app closes
# without ever saving them (an abandoned edit). Per-save cleanup (the normal,
# expected case) happens in core.save_manager.commit_overwrite() right after
# it successfully copies a temp file's content into its real destination —
# this set is a last-resort safety net, not the primary cleanup path, and a
# leftover entry here is harmless either way (an ordinary file in the user's
# OS temp directory, same as countless other apps leave behind, not inside
# any game folder).
_PENDING_RESOURCE_TEMP_FILES: set = set()


_atexit_cleanup_registered = False


def _cleanup_pending_resource_temp_files() -> None:
    for path in list(_PENDING_RESOURCE_TEMP_FILES):
        try:
            os.remove(path)
        except OSError:
            pass
    _PENDING_RESOURCE_TEMP_FILES.clear()


def _register_pending_resource_temp_file(path: str) -> None:
    global _atexit_cleanup_registered
    _PENDING_RESOURCE_TEMP_FILES.add(path)
    if not _atexit_cleanup_registered:
        atexit.register(_cleanup_pending_resource_temp_files)
        _atexit_cleanup_registered = True


# Per-type (top-level stream field, source-path key, offset key, size key) — the
# same two StreamingInfo-shaped layouts resolve_display_size() already reads, just
# spelled out here since check_resource_reference() needs all three sub-fields at
# once (resolve_display_size only ever needed one of them). Shared by every type
# that can point at external streamed data, so a new resource-backed type only
# needs one line added here.
_STREAM_FIELD_INFO = {
    "AudioClip": ("m_Resource", "m_Source", "m_Offset", "m_Size"),
    "VideoClip": ("m_ExternalResources", "m_Source", "m_Offset", "m_Size"),
    "Texture2D": ("m_StreamData", "path", "offset", "size"),
    "Texture2DArray": ("m_StreamData", "path", "offset", "size"),
    "Mesh": ("m_StreamData", "path", "offset", "size"),
}


# Top-level bytes field holding a type's OWN pixel/audio data when it's stored
# inline (declared_path empty in _STREAM_FIELD_INFO's struct) rather than in an
# external resource file — used by export/import_object_content_raw()'s inline
# branch below. Deliberately narrower than _STREAM_FIELD_INFO: Mesh's inline data
# lives nested under m_VertexData.m_DataSize (plus m_IndexBuffer), where a wrong
# replacement (byte count not matching m_Channels/m_Streams' declared stride)
# produces a mesh that fails to render rather than a clear error — that's a real
# binary-format risk this project's own methodology says not to ship without a
# verified reference, so Mesh keeps going through the generic refusal message
# (Edit Data / JSON dump still work for it, same as for any other field).
# VideoClip has no inline field at all (m_ExternalResources is non-Optional —
# always external), so it isn't listed either.
#
# IMPORTANT — these are the RAW TypeTree field names (parse_as_dict()'s own dict
# keys), NOT the generated.py attrs attribute names, and the two are NOT always
# the same string: Texture2D/Texture2DArray's real on-disk field is literally
# "image data" (lowercase, space, no "m_" prefix — a genuine Unity naming
# oddity, confirmed via both a real fixture's parse_as_dict() output and the TPK
# schema for Texture2DArray directly), which TypeTreeNode.clean_name() maps to
# the Python-side "image_data" attrs field — but parse_as_dict()'s own dict is
# keyed by the RAW m_Name (see read_value()'s Class branch: `child.m_Name if
# config.as_dict else child._clean_name`), so a naive full["image_data"] = ...
# here would silently set an UNUSED key and never touch the real field at all
# (confirmed by direct testing: this exact mistake was caught live — it wrote
# successfully-shaped-but-wrong output with no error at all, the worst kind of
# silent failure). m_AudioData has no such space/prefix quirk (confirmed via
# the TPK schema too), so it needs no translation — but it also only exists in
# the schema for pre-Unity-5 games (Unity 5+ dropped it entirely in favor of
# always-streamed m_Resource, confirmed by querying the TPK schema across
# 5.0–2019 versions), so declared_path being empty AND this field being
# present at all is a narrow, old-format-only case in practice — the
# in-dict presence check in export/import below is what keeps that from
# silently no-op'ing and reporting false success on a modern game.
_INLINE_CONTENT_FIELD = {
    "Texture2D": "image data",
    "Texture2DArray": "image data",
    "AudioClip": "m_AudioData",
}


# Types whose data mostly lives in an external .resS/.resource file rather than the
# object's own header — see resolve_display_size(). Derived from _STREAM_FIELD_INFO
# so the two can't silently drift apart as new resource-backed types get added.
# Public (unlike the leading-underscore module internals above) since
# object_actions.py needs it too, to decide whether "Content Raw" belongs in a
# given type's export menu — same convention as RICH_PREVIEW_TYPES just above.
RESOURCE_BACKED_TYPES = _RESOURCE_BACKED_TYPES = tuple(_STREAM_FIELD_INFO.keys())


CancelCheck = Optional[Callable[[], bool]]


# Primitive TypeTree type names UnityPy's own parser (read_value) treats as leaf
# values — same source of truth dump_typed_text() dispatches on, so the two never
# drift out of sync with each other.
_PRIMITIVE_TYPES = frozenset(FUNCTION_READ_MAP.keys())


_DUMP_MAX_DEPTH = 32


_DUMP_MAX_LIST_ITEMS = 500


MAX_IMPORT_JSON_BYTES = 200 * 1024 * 1024  # sanity ceiling before even opening a


_TEXTASSET_JSON_FORMAT_LIMIT = 5 * 1024 * 1024  # chars — see the TextAsset preview


def _check_cancelled(should_cancel: CancelCheck) -> None:
    if should_cancel is not None and should_cancel():
        raise OperationCancelled()


def resolve_texture_format_name(raw) -> str:
    """m_TextureFormat comes back from UnityPy as a plain int (Texture2D's
    generated dataclass types the field `int`, not the TextureFormat enum — see
    UnityPy/classes/generated.py), so callers that only did `fmt.name if
    hasattr(fmt, "name") else fmt` never actually converted it — that check
    always fell through to the raw int. Named via UnityPy's own TextureFormat
    enum (UnityPy/enums/TextureFormat.py), which already existed but wasn't
    actually being used for display anywhere. An unrecognized value (a format
    added upstream after this enum was last generated) falls back to the raw
    number rather than raising."""
    if raw is None:
        return "Unknown"
    try:
        return TextureFormat(raw).name
    except ValueError:
        return str(raw)


def resolve_graphics_format_name(raw) -> str:
    """Same idea as resolve_texture_format_name(), for Texture2DArray/
    Texture3D's own m_Format field — a GraphicsFormat, a DIFFERENT enum from
    TextureFormat with its own, unrelated numbering (see
    UnityPy/enums/GraphicsFormat.py). Deliberately a separate function rather
    than a second branch inside resolve_texture_format_name(): feeding a raw
    GraphicsFormat value through a TextureFormat(...) lookup would silently
    resolve to whichever TextureFormat member happens to share that same
    number — a wrong name, not a missing one, which is worse."""
    if raw is None:
        return "Unknown"
    try:
        from UnityPy.enums.GraphicsFormat import GraphicsFormat
        return GraphicsFormat(raw).name
    except ValueError:
        return str(raw)


def default_object_name(obj) -> str:
    """"TypeName #PathID" — the fallback display name for any object that has
    no resolvable name of its own (peek_object_name() returned "")."""
    try:
        type_name = obj.type.name
    except Exception:
        type_name = "Object"
    return f"{type_name} #{obj.path_id}"


def resolve_script_name(obj) -> str:
    """The MonoBehaviour's referenced script class name (e.g. "PlayerController")
    — a separate concern from the object's own display name (resolve_object_name)
    now that the table shows them in two different columns (Имя / Скрипт). Empty
    string for any non-MonoBehaviour object, so callers can tell "not a
    MonoBehaviour" apart from "MonoBehaviour but script resolution failed"
    (peek_mb_name's "Unknown")."""
    return peek_mb_name(obj) if obj.type.name == "MonoBehaviour" else ""


def resolve_shader_name(obj) -> str:
    """Shader.m_Name is routinely empty in practice (confirmed against real
    fixtures) — the actual human-readable name lives under m_ParsedForm.m_Name
    instead, a nested field with no cheap "peek just this one field" path (unlike
    a top-level m_Name, TypeTree parsing is inherently sequential — reaching a
    nested field means parsing everything before it, compiled shader program
    blobs included). Tries the cheap top-level peek first (covers the rare Shader
    that DOES have its own m_Name set) and only pays for the full parse when that
    comes back empty."""
    cheap = peek_object_name(obj)
    if cheap:
        return cheap
    try:
        data = obj.parse_as_object()
        parsed_form = getattr(data, "m_ParsedForm", None)
        name = getattr(parsed_form, "m_Name", "") if parsed_form is not None else ""
        if name:
            return name
    except Exception:
        pass
    return default_object_name(obj)


_MAX_GAMEOBJECT_FALLBACK_NAME_LEN = 24


def _truncate_name(name: str, max_len: int) -> str:
    if len(name) <= max_len:
        return name
    return name[:max_len].rstrip() + "…"


def _peek_gameobject_fallback_name(obj) -> str:
    """For a MonoBehaviour with no m_Name of its own, borrows its attached
    GameObject's name as a still-useful (if inherited, not authoritative) label —
    wrapped in "(GameObject) ..." so it's never mistaken for the object's OWN name
    field. Cheap: one peek_field() (no full parse of either object) plus a single
    PPtr deref (the same mechanism gui_widgets.ObjectStructureTree already uses
    for lazy PPtr navigation), only ever attempted once the object's own name has
    already come back empty.

    Multiple different-typed MonoBehaviours attached to the same GameObject will
    show the same fallback label — expected, since it's the GameObject's identity
    being borrowed, not a per-component one; build_export_stem()'s own
    "#{path_id} ({source})" suffix already keeps their exported filenames from
    colliding regardless."""
    try:
        go_field = obj.peek_field(("m_GameObject",))
        path_id = int((go_field or {}).get("m_PathID", 0) or 0)
        if not path_id:
            return ""
        file_id = int((go_field or {}).get("m_FileID", 0) or 0)
        go_obj = PPtr(m_FileID=file_id, m_PathID=path_id, assetsfile=obj.assets_file).deref()
        go_name = peek_object_name(go_obj) if go_obj else ""
    except Exception:
        return ""
    if not go_name:
        return ""
    return f"(GameObject) {_truncate_name(go_name, _MAX_GAMEOBJECT_FALLBACK_NAME_LEN)}"


def resolve_object_name(obj) -> str:
    """The single source of truth for "what should this object be called" — used
    both by loader.py's initial table population and by preview/export (so a
    row's Имя column and its exported filename always agree). MonoBehaviour uses
    its own m_Name like every other type now (peek_object_name() already reads
    whatever field is actually named m_Name in an object's own TypeTree schema,
    which MonoBehaviour has too) — its script's class name is a separate concern,
    see resolve_script_name(). Shader needs its own nested-field lookup, see
    resolve_shader_name(). A nameless MonoBehaviour tries its attached
    GameObject's name next (_peek_gameobject_fallback_name) before falling all
    the way to "TypeName #PathID" — still useful context even though it's
    borrowed, not the object's own."""
    if obj.type.name == "Shader":
        return resolve_shader_name(obj)
    name = peek_object_name(obj)
    if name:
        return name
    if obj.type.name == "MonoBehaviour":
        fallback = _peek_gameobject_fallback_name(obj)
        if fallback:
            return fallback
    return default_object_name(obj)


# Sentinel for RowItem's "name"/"script_name" fields meaning "not resolved
# yet" — distinct from any real value either function can return
# (resolve_object_name() always returns a real, non-None str; resolve_script_name()
# returns "" for a non-MonoBehaviour, never None). See get_row_name()/
# get_row_script_name() below for why this exists at all.
ROW_FIELD_UNRESOLVED = None


def get_row_name(item: dict) -> str:
    """Lazily resolves and memoizes RowItem's "name" field in place, the
    first time anything actually asks for it — the accessor every consumer
    of a row's name MUST go through instead of item["name"]/item.get("name")
    directly, now that build_row_item() no longer resolves it eagerly.

    Real, measured motivation: resolve_object_name() was found (via cProfile
    on a real ~78M-object fixture) to be the single largest cost in indexing
    a large game — dominated by peek_field()/PPtr.deref() chains for
    MonoBehaviour's GameObject-fallback-name feature — and, separately, the
    resolved string itself is a real, measured RAM cost at that scale
    (millions of table rows each holding their own name string). Computing
    it only for rows something actually looks at (a visible cell, an active
    text search, a sort by this column) rather than unconditionally for
    every row at load time is a direct fix for both: a load that's just
    going to be scrolled through never pays for it at all, and RAM stays
    proportional to what's actually been touched, not to the object count.

    Safe by construction: resolve_object_name() never returns None, so a
    still-None value unambiguously means "not resolved yet" — never
    confusable with a legitimately resolved value."""
    name = item["name"]
    if name is ROW_FIELD_UNRESOLVED:
        # Shared storage: a big table holds the same few names over and over (Lego Party: 123k
        # distinct among 1.95M rows = 144 MB of strings down to ~9 MB).
        name = sys.intern(resolve_object_name(item["obj_ref"]))
        item["name"] = name
    return name


def get_row_script_name(item: dict) -> str:
    """Same lazy-resolve-and-memoize pattern as get_row_name(), for RowItem's
    "script_name" field — resolve_script_name() never returns None either
    (an empty string for a non-MonoBehaviour is a legitimate, already-final
    value, not "unresolved").

    A MonoBehaviour row also keeps the full identity it was resolved from (`script_identity`, read by
    get_row_script_identity): the Фильтры dialog needs it for every MonoBehaviour, and reading it again
    meant re-reading 91,619 object heads on Truck-kun at every open (the warm-up drops the cached heads).
    Identities are shared objects (`shared_identity`), so a row pays one dict slot (it fits in the row
    dict's spare room — no resize)."""
    script_name = item["script_name"]
    if script_name is ROW_FIELD_UNRESOLVED:
        obj = item["obj_ref"]
        if obj.type.name == "MonoBehaviour":
            identity = shared_identity(peek_mb_identity(obj))
            item["script_identity"] = identity
            script_name = identity.class_name
        else:
            script_name = ""
        item["script_name"] = script_name
    return script_name


def get_row_script_identity(item: dict) -> "ScriptIdentity":
    """The ScriptIdentity behind a MonoBehaviour row's script name, memoized on the row (see
    get_row_script_name). A row whose name was set some other way (a test, an older row) is read once."""
    get_row_script_name(item)
    identity = item.get("script_identity")
    if identity is None:
        identity = shared_identity(peek_mb_identity(item["obj_ref"]))
        item["script_identity"] = identity
    return identity


def script_identity_tooltip(identity) -> str:
    """The full-detail tooltip for one script checklist entry (or anywhere
    else a script identity is shown compactly and the full picture should
    still be one hover away) — Assembly/Namespace/Class, one per line, in
    that order (matching UABEANext's own inspector field order). Namespace
    is shown even when empty (a real, common case — see ScriptIdentity's own
    docstring) rather than omitted, so the tooltip's shape never shifts
    depending on which script it's for.

    A script that could not be resolved at all (class "Unknown", nothing else known) says
    "Unknown" on every line instead of "(none)": "(none)" would read as "this script
    really has no assembly/namespace", when the truth is that the whole name failed to
    resolve."""
    if identity.class_name == "Unknown" and not identity.namespace and not identity.assembly_name:
        return "Assembly: Unknown\nNamespace: Unknown\nClass: Unknown"
    text = (
        f"Assembly: {identity.assembly_name or '(none)'}\n"
        f"Namespace: {identity.namespace or '(none)'}\n"
        f"Class: {identity.class_name}"
    )
    if getattr(identity, "inferred", False):
        text += "\n(determined based on fields)"
    return text


_PROGRESS_STEP = 2000
_CANCEL_STEP = 200     # also where a background caller rests (see FiltersDialog)


def script_checklist_entries(data_list, progress: Optional[Callable[[int, int], None]] = None,
                             should_cancel: Optional[Callable[[], bool]] = None) -> List[Tuple[str, str, str]]:
    """(value, display_label, tooltip) triples for a "filter by MonoBehaviour
    script" checklist (dialogs/filters_dialog.py's own tab; also usable
    anywhere else that needs the same "one entry per distinct script"
    listing).

    Real motivation (a direct user report, not a hypothetical): a script's
    BARE class name (what the Script column shows, what an export filename
    uses — see resolve_script_name()) is not always unique project-wide.
    Real, confirmed example from an actual shipped game's asset bundle:
    multiple third-party Unity packages define their own class named
    "SaveSystem"/"Bloom" etc. under different namespaces — a bare-name-only
    checklist can't tell them apart, and checking one silently also selects
    every other same-named-but-different class.

    Design, per explicit instruction: no dynamic "only qualify on collision"
    logic — an earlier version of this function DID do that, and was
    deliberately torn out. Qualifying a checkbox's value/label only when
    some OTHER, unrelated script happens to collide made the same real
    script's own checkbox spelling change depending on what else was loaded
    — an unstable UI. Instead, always show the namespace-qualified identity
    (ScriptIdentity.qualified_name — "Namespace.ClassName", or just
    "ClassName" when there's no namespace, since that already degenerates to
    the bare name) as BOTH value and label, unconditionally — the same
    convention UABEANext's own script filter uses. The full picture
    (Assembly/Namespace/Class) is always one hover away via the tooltip
    (script_identity_tooltip()) instead of being folded into the label only
    sometimes.

    Two distinct scripts that share BOTH namespace and class name (only
    possible across two different assemblies — e.g. two copies of the same
    third-party package) collapse into one checklist entry by design: this
    function intentionally does not split by assembly too, since that was
    exactly the extra layer of complexity being removed. Rare in practice
    (not observed in any of this project's own real sampled fixtures) and,
    if it happens, checking that one entry still selects every row sharing
    that qualified identity — correct, if slightly coarser than a
    per-assembly split would be.

    progress(done, total) - MonoBehaviour rows - every _PROGRESS_STEP rows, and should_cancel() (raises
    OperationCancelled) are for the Фильтры dialog, which builds this list in the background: on a first open
    after a load every script is read (Lego Party: 32 s, Phonopolis: 1.8 s)."""
    seen: Dict[str, "ScriptIdentity"] = {}
    behaviours = [item for item in data_list if item.get("type") == "MonoBehaviour"]
    total = len(behaviours)
    for done, item in enumerate(behaviours):
        if done % _CANCEL_STEP == 0:
            if should_cancel is not None and should_cancel():
                raise OperationCancelled()
            if progress is not None and done % _PROGRESS_STEP == 0:
                progress(done, total)
        bare = get_row_script_name(item)
        if not bare:
            continue
        identity = get_row_script_identity(item) if item.get("obj_ref") else None
        if identity is None:
            identity = ScriptIdentity(class_name=bare, namespace="", assembly_name="")
        qualified = identity.qualified_name
        # An identity read from the script wins over one worked out from the fields (same name, but its
        # tooltip is the real one).
        if qualified not in seen or (seen[qualified].inferred and not identity.inferred):
            seen[qualified] = identity

    return [
        (qualified, qualified, script_identity_tooltip(seen[qualified]))
        for qualified in sorted(seen)
    ]


def row_matches_script_selector(item: dict, allowed_scripts: Set[str]) -> bool:
    """True if `item` (a MonoBehaviour row) is identified by any value in
    `allowed_scripts` — the matching counterpart of script_checklist_entries()
    above, also used directly wherever a user can type a script name/filter
    by hand (Quick Filter free-text, "Export by script"/CLI --script) rather
    than pick from that checklist, so a hand-typed qualified name works
    exactly the same way a checklist-selected one does.

    Checks the bare class name first (a single set-membership test, same
    cost as before this existed) and only falls through to the
    namespace-qualified form if that misses — keeping the overwhelmingly
    common "unambiguous, plain bare name" case exactly as cheap as it always
    was. peek_mb_identity() is cache-backed (core.file_utils), so even the
    fallback path is a cache hit in practice: whatever resolved this row's
    bare name already populated the same cache entry."""
    bare = get_row_script_name(item)
    if not bare:
        return False
    if bare in allowed_scripts:
        return True
    obj = item.get("obj_ref")
    if not obj:
        return False
    identity = peek_mb_identity(obj)
    return identity.qualified_name in allowed_scripts


def write_error_reason(e: Exception) -> str:
    """One readable line for an exception raised while WRITING an object's data (obj.patch() /
    save_typetree()), which the user sees as "Не удалось применить ...: <this>". The bare str() of the usual
    ones says nothing on its own (user report, Truck-kun via the 1.3.0 CLI: "Не удалось применить JSON:
    'shadows'" - a KeyError for a field the data did not have; the CLI prints only the first line)."""
    if isinstance(e, KeyError):
        name = e.args[0] if e.args else "?"
        return tr("в данных нет поля «{name}», которое есть у объекта", name=name)
    if isinstance(e, (OverflowError, struct.error)):
        return tr("значение не помещается в поле объекта ({error})", error=e)
    if isinstance(e, (TypeError, ValueError)):
        return tr("значение не того вида для поля объекта ({error})", error=e)
    return str(e) or type(e).__name__


def safe_parse_dict(obj) -> Tuple[Optional[dict], Optional[str]]:
    try:
        return obj.parse_as_dict(), None
    except Exception as e:
        return None, f"{e}\n{traceback.format_exc()}"


def _texture_empty_reason(data) -> Optional[str]:
    """Checked before ever touching .image (which actually decodes pixel data) —
    m_Width/m_Height can legitimately be 0 (an empty/placeholder texture some
    games genuinely ship), and decoding one is at best wasted work, at worst an
    error from a converter that assumes a real image. Returns a human-readable
    reason string if the texture looks empty, None if it looks decodable.
    m_CompleteImageSize (Texture2D) / m_DataSize (Texture2DArray) are checked
    too — declared size fields, cheap to read, no need to materialize
    .image_data just to find out it's empty."""
    width = getattr(data, "m_Width", 0) or 0
    height = getattr(data, "m_Height", 0) or 0
    data_size = getattr(data, "m_CompleteImageSize", None)
    if data_size is None:
        data_size = getattr(data, "m_DataSize", None)
    if width <= 0 or height <= 0 or data_size == 0:
        return tr("Пустая текстура ({width}x{height}, данные: {size})", width=width, height=height,
                  size=format_size(data_size or 0))
    return None


def _sprite_empty_reason(data) -> Optional[str]:
    """A Sprite that points at no texture and no SpriteAtlas has no picture at all (real case: «There is no
    game - Wrong dimension», level7 Sprite #96 — a nameless 4x4 placeholder); SpriteHelper would raise
    "PPtr can't deref with m_PathID == 0!". Checked before touching .image."""
    def _null(pptr) -> bool:
        return pptr is None or not getattr(pptr, "m_PathID", 0)
    rd = getattr(data, "m_RD", None)
    if _null(getattr(rd, "texture", None)) and _null(getattr(data, "m_SpriteAtlas", None)):
        return tr("У спрайта нет текстуры")
    return None


# Prefix marking a converted-import return value as an ADVISORY, not a
# failure — apply_matched_patch()'s callers must check for this before
# treating a non-None return as an error. Currently only used by the
# AudioClip branch's FMOD-decode verification (see
# UnityPy/helpers/Fsb5Encoder.py's verify_decodable/ensure_fmod_dll_override)
# — the import itself already succeeded by the time this could be returned.
IMPORT_WARNING_PREFIX = "ПРЕДУПРЕЖДЕНИЕ: "   # i18n: keep (a marker callers strip, never shown)


_TEXTURE_QUALITY_TO_ENCODER = {
    "medium": "balanced",
    "high": "best",
}


# Arbitrarily large upper bound for _Texture2d_set_image's mipmap_count param
# when the caller just wants "the full chain" rather than a specific count —
# that function's own loop already stops early once a level would drop below
# 4x4, so anything at or above the level count a 4096x4096 texture needs (12)
# has the same effect; comfortably covers any realistic Unity texture size.
_FULL_MIPMAP_CHAIN = 32
