"""Type-appropriate object export (PNG/audio/text/JSON/...), export file naming and the JSON-edit helpers."""

from core.i18n import tr
import json
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from .file_utils import format_size, peek_object_name, safe_join

from .object_common import _TEXTASSET_JSON_FORMAT_LIMIT, _peek_gameobject_fallback_name, _sprite_empty_reason, _texture_empty_reason, resolve_script_name
from .object_dump import (
    _BINARY_STRING_MARKER_KEY, _BYTE_LIST_MARKER_KEY, _BYTES_MARKER_KEY, _EDIT_OMIT_BYTES_THRESHOLD,
    _OMITTED_BYTES_MARKER_KEY, _OMITTED_BYTE_LIST_MARKER_KEY, _OMITTED_STRING_MARKER_KEY, _looks_binary,
    build_export_json,
)
from .object_resources import read_videoclip_bytes


_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)


# Real reported issue: "Load all assets" (CONFIG.load_all_assets) surfaces every
# GameObject, including Unity's own runaway auto-naming for repeatedly cloned/
# instantiated ones at runtime — e.g. "X (Instance)(Clone) (Instance)(Clone) ..."
# chains observed well over a hundred characters long in a real fixture. Every
# call site combines this function's output with other pieces (a type prefix, a
# second sanitized name, a path_id, an extension — object_actions.py's
# dump_single_object is the worst case: "{type}_{name}_{source}_{path_id}.json").
# Capped HERE, the one choke point every one of them already routes through,
# rather than at each call site — keeps the combined worst case comfortably
# under Windows' 255-character-per-path-component limit regardless of how long
# the source name actually was, without needing every caller to reason about it
# individually.
_MAX_SANITIZED_NAME_LENGTH = 60


def sanitize_export_filename(name: str, fallback: str) -> str:
    """Normalizes a name derived from data embedded in the object itself (a
    MonoBehaviour's m_Name, an AudioClip sample name, ...) into something safe to
    use as a Windows filename — that data is attacker-controlled the moment the
    source file is (a crafted/modded bundle), same class of risk safe_join()
    already guards against for archive entry names, just for individual invalid
    characters rather than path traversal. Replaces every character outside
    Windows' allowed set (path separators, `<>:"|?*`, and control characters —
    isalnum() plus a small allow-list of ". _-" covers this while still passing
    non-ASCII names like Cyrillic through untouched) with "_", truncates to
    _MAX_SANITIZED_NAME_LENGTH characters (see its own docstring for why), strips
    the trailing dots/spaces Windows silently disallows (re-checked after
    truncation too, in case the cut landed on one), and falls back to `fallback`
    for an empty result or one of Windows' reserved device names (CON, COM1,
    LPT1, ...), which are invalid regardless of extension."""
    name = Path(str(name).replace("\\", "/")).name
    cleaned = "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip()
    cleaned = cleaned[:_MAX_SANITIZED_NAME_LENGTH].rstrip(". ")
    if not cleaned:
        return fallback
    stem = cleaned.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        return fallback
    return cleaned


def _bare_resolved_name(obj) -> str:
    """Same name resolution resolve_object_name() uses (Shader's nested-field
    lookup, everything else's own m_Name, MonoBehaviour's GameObject-name
    fallback), but returns "" when nothing resolves at all instead of falling
    back to resolve_object_name()'s own "TypeName #PathID" — build_export_stem()
    below needs a DIFFERENT fallback shape of its own (see its docstring), so it
    needs the "nothing resolved" case distinguishable from an actual name, which
    resolve_object_name()'s baked-in fallback doesn't allow."""
    if obj.type.name == "Shader":
        cheap = peek_object_name(obj)
        if cheap:
            return cheap
        try:
            data = obj.parse_as_object()
            parsed_form = getattr(data, "m_ParsedForm", None)
            return getattr(parsed_form, "m_Name", "") if parsed_form is not None else ""
        except Exception:
            return ""
    name = peek_object_name(obj)
    if name:
        return name
    if obj.type.name == "MonoBehaviour":
        return _peek_gameobject_fallback_name(obj)
    return ""


def build_export_stem(obj) -> str:
    """The shared "identity" portion of every exported filename — everything
    before the extension. One naming convention for every export path
    (type-specific standard export, JSON dump, raw/content binary dump), per
    a real request to standardize this instead of each call site building its
    own slightly-different ad-hoc pattern.

        MonoBehaviour: "ScriptName.ObjectName #PathID (SourceName)"
        everything else: "ObjectName #PathID (SourceName)"

    ObjectName falls back to the object's own TYPE NAME when it has none of
    its own (e.g. "RectTransform #123 (sharedassets0.assets)") — EXCEPT for
    MonoBehaviour, which tries its attached GameObject's name first
    (_peek_gameobject_fallback_name, e.g. "(GameObject) Player") and only falls
    back to the literal "Unnamed" if that's empty too: its own type name is
    always "MonoBehaviour", and "ScriptName.MonoBehaviour" would misleadingly
    read as if "MonoBehaviour" were the object's own name rather than "no name
    at all".

    SourceName is assets_file.name as-is (a plain basename — File.__init__
    already strips any directory), extension included — an earlier version
    stripped ".assets" off "resources.assets"/"sharedassetsN.assets"
    specifically, reverted per explicit request.

    Every embedded fragment (script name, object name, source name) is
    independently sanitized BEFORE being joined with the structural
    punctuation (".", "#", "()") — each fragment comes from data embedded in
    the object/file itself, attacker-controlled the moment the source is a
    crafted/modded bundle, same class of risk sanitize_export_filename()
    already guards against for a single name (see its own docstring)."""
    type_name = obj.type.name
    bare_name = _bare_resolved_name(obj)

    if type_name == "MonoBehaviour":
        script_name = sanitize_export_filename(resolve_script_name(obj), fallback="Script")
        object_name = sanitize_export_filename(bare_name, fallback="Unnamed")
        stem = f"{script_name}.{object_name}"
    else:
        object_name = sanitize_export_filename(bare_name, fallback=type_name)
        stem = object_name

    raw_source_name = getattr(obj.assets_file, "name", "") or "unknown"
    source_name = sanitize_export_filename(raw_source_name, fallback="unknown")
    return f"{stem} #{obj.path_id} ({source_name})"


def _detect_textasset_extension(text: str) -> str:
    """Best-effort original-format guess for a TextAsset's decoded text — real
    request: restore a plausible extension (.json/.bin/.txt) on export
    instead of always .txt. Same detection _type_specific_preview()'s
    TextAsset branch already uses for the Preview tab (_looks_binary()'s
    NUL-byte heuristic, then a bounded JSON-parse attempt) — one source of
    truth for "what kind of text is this", not two independently-drifting
    checks."""
    if _looks_binary(text):
        return ".bin"
    if len(text) <= _TEXTASSET_JSON_FORMAT_LIMIT:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            pass
        else:
            if isinstance(parsed, (dict, list)):
                return ".json"
    return ".txt"


def export_object(
    obj, output_dir: Path, overwrite: bool = True
) -> Tuple[Optional[Path], Optional[str], bool]:
    """Exports a single object to output_dir. Returns (output_path, message,
    skipped). Types with a dedicated binary exporter below (Texture2D/
    Texture2DArray/Sprite, AudioClip, TextAsset, Mesh, Shader, Font) use it;
    everything else (MonoBehaviour, GameObject, Material, AnimationClip,
    AnimatorController, and any other type reachable via the CAB browser) exports
    as JSON if its typetree parses, falling back to a raw .bin dump otherwise.

    skipped=True means `message` describes an EXPECTED, non-error condition —
    a texture with no pixel data, a Font with no embedded m_FontData, an
    AudioClip with no samples, a VideoClip with no linked external resource.
    Real reported clarification: these are legitimate, unremarkable states
    some objects are just genuinely in (a placeholder texture, an unused
    font asset, ...) — not something gone wrong, so callers doing a bulk
    export should NOT count them as failures, just note them somewhere.
    skipped=False + message set means a REAL error occurred (an exception, a
    genuinely missing resource that should have been there)."""
    output_dir = Path(output_dir)

    def existing(out_path: Path) -> bool:
        # ExportSettingsDialog's "Перезаписывать существующие файлы" — off by
        # default expectation is "don't clobber a file already exported in a
        # previous run"; checked right before each write below (never a
        # global up-front scan) since the exact filename isn't known until
        # this point for every type.
        return not overwrite and out_path.exists()

    try:
        type_name = obj.type.name
        stem = build_export_stem(obj)

        if type_name == "Texture2D":
            data = obj.parse_as_object()
            empty_reason = _texture_empty_reason(data)
            if empty_reason:
                return None, tr("{empty_reason} — экспорт недоступен.", empty_reason=empty_reason), True
            img = data.image
            out_path = safe_join(output_dir, f"{stem}.png")
            if existing(out_path):
                return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
            img.save(out_path)
            return out_path, None, False

        if type_name == "Texture2DArray":
            # Real reported bug: this shared the Texture2D branch above, which
            # calls .image — Texture2DArray has no such attribute (only the
            # plural .images, one PIL image per depth slice). Every slice gets
            # its own file, grouped into a subfolder named after the object's
            # own m_Name (per a follow-up request) — since every slice would
            # otherwise share the exact same {stem}.png filename, the slice
            # index is still included within that subfolder to keep them
            # distinct from each other.
            data = obj.parse_as_object()
            empty_reason = _texture_empty_reason(data)
            if empty_reason:
                return None, tr("{empty_reason} — экспорт недоступен.", empty_reason=empty_reason), True
            images = data.images
            if not images:
                return None, tr("Слои текстуры не найдены"), True
            array_dir = output_dir / sanitize_export_filename(peek_object_name(obj), "Texture2DArray")
            array_dir.mkdir(parents=True, exist_ok=True)
            pad = max(2, len(str(len(images) - 1)))
            written = 0
            for i, img in enumerate(images):
                out_path = safe_join(array_dir, f"{stem}_slice{i:0{pad}d}.png")
                if existing(out_path):
                    continue
                img.save(out_path)
                written += 1
            if written == 0:
                return array_dir, tr("Все {count} срезов уже существуют, пропущено", count=len(images)), True
            # array_dir, not a single file — there are len(images) of them;
            # the caller's log message reads fine either way ("Экспортирован
            # объект: <folder>"), and this is what _maybe_open_folder-style
            # follow-ups actually want to open regardless of object type.
            return array_dir, None, False

        if type_name == "Sprite":
            # No m_Width/m_Height/m_CompleteImageSize of its own (unlike
            # Texture2D/Texture2DArray) — _texture_empty_reason doesn't apply here,
            # its pixel data comes from the referenced Texture2D via m_RD instead.
            data = obj.parse_as_object()
            empty_reason = _sprite_empty_reason(data)
            if empty_reason:
                return None, tr("{empty_reason} — экспорт недоступен.", empty_reason=empty_reason), True
            img = data.image
            out_path = safe_join(output_dir, f"{stem}.png")
            if existing(out_path):
                return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
            img.save(out_path)
            return out_path, None, False

        if type_name == "AudioClip":
            # A standard/native export (a real, playable audio file — UnityPy's
            # own AudioClipConverter fully decodes it), not a raw content dump,
            # so it keeps a plain native extension rather than .resdata.bin —
            # taken from the sample's OWN filename (e.g. AudioClipConverter
            # names it "<clip>.wav"), since that's the only place the actual
            # container format is known; the stem/identity naming is still this
            # object's own build_export_stem(), not the sample's internal name.
            data = obj.parse_as_object()
            for sample_name, sample_data in data.samples.items():
                ext = Path(sample_name).suffix or ".wav"
                out_path = safe_join(output_dir, f"{stem}{ext}")
                if existing(out_path):
                    return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
                with open(out_path, "wb") as f:
                    f.write(sample_data)
                return out_path, None, False
            return None, tr("Аудиосэмплы не найдены"), True

        if type_name == "TextAsset":
            data = obj.parse_as_object()
            text = data.m_Script
            ext = _detect_textasset_extension(text)
            out_path = safe_join(output_dir, f"{stem}{ext}")
            if existing(out_path):
                return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
            # text is always a str here — read_aligned_string() decodes via UTF-8
            # with errors="surrogateescape", never raises and never leaves it as
            # raw bytes (see the Preview-tab TextAsset branch above for the same
            # note). Writing it back out needs that same codec: a genuinely
            # binary TextAsset's lone-surrogate codepoints raise
            # UnicodeEncodeError under the default strict handler, which is what
            # exporting one used to do (the isinstance(text, bytes) branch this
            # replaced was dead code — text is never bytes).
            # newline="" is required, not cosmetic: Python's default text-mode
            # newline translation rewrites every "\n" to os.linesep on write
            # (and the mirror-image translation happens on the import side's
            # read) — invisible and harmless for prose, but for a ".bin"-
            # detected binary TextAsset (a custom binary format some games
            # store this way, see _detect_textasset_extension()/_looks_binary())
            # any literal 0x0A byte in the data is not a line ending at all,
            # and would be corrupted into "\r\n" on this Windows build. Passing
            # newline="" disables the translation entirely, making this an
            # exact byte-for-byte transcription for every case, not just the
            # ones that happen to contain no embedded 0x0A.
            with open(out_path, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                f.write(text)
            return out_path, None, False

        if type_name == "Mesh":
            data = obj.parse_as_object()
            mesh_text = data.export()
            out_path = safe_join(output_dir, f"{stem}.obj")
            if existing(out_path):
                return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(mesh_text)
            return out_path, None, False

        if type_name == "Shader":
            data = obj.parse_as_object()
            shader_text = data.export()
            out_path = safe_join(output_dir, f"{stem}.shader")
            if existing(out_path):
                return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(shader_text)
            return out_path, None, False

        if type_name == "Font":
            data = obj.parse_as_object()
            font_data = bytes(data.m_FontData) if data.m_FontData else b""
            if not font_data:
                return None, tr("Данные шрифта отсутствуют"), True
            ext = ".otf" if font_data[:4] == b"OTTO" else ".ttf"
            out_path = safe_join(output_dir, f"{stem}{ext}")
            if existing(out_path):
                return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
            with open(out_path, "wb") as f:
                f.write(font_data)
            return out_path, None, False

        if type_name == "VideoClip":
            # No legacy_patch/export helper of its own (unlike AudioClip) — read the
            # external resource directly via the same mechanism
            # export/AudioClipConverter.py already relies on for AudioClip. This IS
            # conceptually a raw, unverified byte copy of an externally-referenced
            # resource (the .resdata.bin category exists for exactly this) — but
            # kept as a real, guessed playable extension instead (falling back to
            # ".mp4") per an explicit call: a video file that opens correctly by
            # double-click in Explorer/a media player is worth more here than
            # naming-scheme purity, and a wrong guess is harmless (Explorer/most
            # players still open it fine off the container format, not the
            # extension alone).
            raw, ext, skip_reason = read_videoclip_bytes(obj)
            if skip_reason:
                return None, skip_reason, True
            out_path = safe_join(output_dir, f"{stem}{ext}")
            if existing(out_path):
                return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
            with open(out_path, "wb") as f:
                f.write(raw)
            return out_path, None, False

        # Everything else: JSON if the typetree parses IN FULL, else a raw
        # binary dump of the object's OWN serialized bytes (.raw.bin) — a
        # PARTIAL parse is treated the same as "doesn't parse" here (see
        # build_export_json()'s own docstring): falling through to the raw
        # bytes is honest about what was actually read, unlike a JSON file
        # that would silently look complete while missing most fields.
        json_text, _err, _is_partial = build_export_json(obj)
        if json_text is not None:
            out_path = safe_join(output_dir, f"{stem}.dump.json")
            if existing(out_path):
                return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
            # Real reported bug: a string field decoded via errors="surrogateescape"
            # elsewhere in this object's data can contain lone surrogates the
            # strict UTF-8 codec refuses to encode — same fix as the TextAsset
            # branch above (errors="surrogateescape"), applied at encode time
            # instead of open() time so a bad string can't leave a partial/empty
            # file behind either (open(..., "w") creates the file immediately,
            # before write() would have raised).
            with open(out_path, "wb") as f:
                f.write(json_text.encode("utf-8", errors="surrogateescape"))
            return out_path, None, False

        raw = obj.get_raw_data()
        out_path = safe_join(output_dir, f"{stem}.raw.bin")
        if existing(out_path):
            return out_path, tr("Файл уже существует, пропущено: {name}", name=out_path.name), True
        with open(out_path, "wb") as f:
            f.write(raw)
        return out_path, None, False

    except Exception as e:
        return None, tr("Экспорт не удался: {error}\n{format_exc}", error=e, format_exc=traceback.format_exc()), False


def _byte_list_as_bytes(value: Any) -> Optional[bytes]:
    """If `value` is a long list of integers that are all 0..255, the list's bytes — i.e. it is binary
    data that arrived as a list of numbers (a Font's m_FontData: `vector<UInt8>` is returned by UnityPy
    as a list) — else None.

    "Is this really binary or a list of numbers somebody may want to edit?" can't be known for sure; the
    rule is the same one a person would use: a list of MORE than _EDIT_OMIT_BYTES_THRESHOLD items whose
    every item is an integer in 0..255 is not something to edit by hand as text (15,515,760 numbers for
    one font took minutes to build and show). bytes(list) is the check: it raises for any item that is
    not an int in 0..255 and costs ~10 ms per MB. Booleans are excluded (a vector<bool> is not bytes)
    by looking at the first and last item's exact type."""
    if type(value) is not list or len(value) <= _EDIT_OMIT_BYTES_THRESHOLD:
        return None
    if type(value[0]) is not int or type(value[-1]) is not int:
        return None
    try:
        return bytes(value)
    except (ValueError, TypeError):
        return None


def _omitted_bytes_placeholder(marker_key: str, omit_id: int, size: int, note: Optional[str] = None) -> dict:
    """The dict JsonEditorDialog's text shows in place of a big field's actual
    content — see prepare_dict_for_json_edit()'s docstring. Deliberately NOT
    the field's hex text at all: only its size and a plain-language note. Any
    extra key here (like "note") is cosmetic and can be freely hand-edited —
    restore_dict_from_json_edit() only ever looks at `marker_key`'s own value
    (the id), never the rest of this dict, when deciding whether to splice
    the real bytes back in."""
    return {
        marker_key: omit_id,
        "size": format_size(size),
        "note": note or (
            tr("[Содержимое этого поля было скрыто, чтобы диалоговое окно открылось без задержек. Для его "
               "редактирования экспортируйте объект как Json дамп]")
        ),
    }


def prepare_dict_for_json_edit(value: Any, omitted: Optional[Dict[int, bytes]] = None) -> Any:
    """Recursively wraps every raw bytes/bytearray value (e.g. a MonoBehaviour's
    TypelessData field, a Mesh's raw index buffer, ...) into a JSON-serializable
    marker so JsonEditorDialog's json.dumps() doesn't crash on it. Real reported
    bug: obj.parse_as_dict() was handed straight to json.dumps() with no such
    conversion, which worked by chance for most MonoBehaviour data (rarely has
    raw byte-array fields) but raised "Object of type bytes is not JSON
    serializable" for types that do — confirmed via a real Edit-data attempt on
    such an object, not theoretical. restore_dict_from_json_edit() is the exact
    inverse, called right before obj.patch() so the object actually receives
    real bytes again — patch()/save_typetree() write based on the TypeTree
    schema, not the JSON's own types, and don't know what to do with a plain
    hex string for a bytes-typed field.

    A SMALL bytes/binary-string field (<= _EDIT_OMIT_BYTES_THRESHOLD) is hex-
    encoded inline, same as always — {"__bytes_hex__": "<hex>"}
    (_BYTES_MARKER_KEY). This is the SAME marker _to_jsonable() uses for
    build_export_json()/build_preview_json() — import_object_json() runs the
    same restore pass, so "Edit Data" and "Export object" -> hand-edit ->
    "Импортировать из JSON..." are byte-for-byte consistent round-trips of
    each other for fields this small.

    A LARGE one (a texture's pixels, an AudioClip's samples, a Mesh's vertex/
    index buffer, ...) is instead OMITTED from the text entirely — its actual
    bytes go into the `omitted` dict (filled in place; pass the SAME dict to
    restore_dict_from_json_edit() afterward) keyed by a small int id, and the
    field's spot in the JSON gets a plain placeholder object naming its size
    instead of its content (_omitted_bytes_placeholder()). Real reported
    complaint about the PREVIOUS fix here (a flat "refuse the whole dialog if
    any field is over 1 MB" gate): it still left the dialog slow well under
    that cap (hex-encoding is what's slow, not the 1 MB number specifically —
    see _EDIT_OMIT_BYTES_THRESHOLD's own comment for the actual measured
    cost), AND it banned editing every OTHER field of an object just because
    ONE field happened to be huge, which is a real capability loss for an
    object that legitimately mixes a big binary blob with small fields worth
    hand-editing. This fixes both: the huge field's bytes never become text
    at all (so the dialog opens fast regardless of that field's size), and
    the rest of the object stays fully, normally editable. As long as the
    user doesn't touch the placeholder's own marker id, the field round-trips
    back byte-for-byte automatically — deleting the placeholder (or the whole
    field) is the one way to actually drop it, same as deleting any other
    field would (see restore_dict_from_json_edit()'s docstring).

    Real reported bug (separate from the bytes-field one above): a STRING field
    decoded from binary-ish content (read_aligned_string()'s errors=
    "surrogateescape" codec — a TextAsset storing a custom binary format is the
    common real case) can be megabytes of garbled surrogate-laden text, which
    made the editor dialog visibly lag rendering/highlighting it, AND can
    contain lone surrogates the strict UTF-8 codec refuses to encode later (the
    exact crash reported for JSON-dump export: "'utf-8' codec can't encode
    character '\\udcXX': surrogates not allowed"). Gets the identical small/
    large split as a real bytes field, just via its own pair of markers
    (_BINARY_STRING_MARKER_KEY/_OMITTED_STRING_MARKER_KEY, not the bytes
    ones) since it must round-trip back to a real str, not bytes —
    write_typetree() cares which type a given field's TypeTree schema
    actually expects. Uses the same _looks_binary() heuristic the Preview
    tab's TextAsset branch already trusts for this exact scenario, not a
    bare size cutoff — a large but genuinely plain-text field (a big i18n
    JSON blob, say) is still shown and editable normally, at any size."""
    if omitted is None:
        omitted = {}

    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) > _EDIT_OMIT_BYTES_THRESHOLD:
            omit_id = len(omitted)
            omitted[omit_id] = raw
            return _omitted_bytes_placeholder(_OMITTED_BYTES_MARKER_KEY, omit_id, len(raw))
        return {_BYTES_MARKER_KEY: raw.hex()}
    if isinstance(value, str) and _looks_binary(value):
        encoded = value.encode("utf-8", "surrogateescape")
        if len(encoded) > _EDIT_OMIT_BYTES_THRESHOLD:
            omit_id = len(omitted)
            omitted[omit_id] = encoded
            return _omitted_bytes_placeholder(_OMITTED_STRING_MARKER_KEY, omit_id, len(encoded))
        return {_BINARY_STRING_MARKER_KEY: encoded.hex()}
    if isinstance(value, dict):
        return {str(k): prepare_dict_for_json_edit(v, omitted) for k, v in value.items()}
    raw_list = _byte_list_as_bytes(value)
    if raw_list is not None:
        omit_id = len(omitted)
        omitted[omit_id] = raw_list
        return _omitted_bytes_placeholder(
            _OMITTED_BYTE_LIST_MARKER_KEY, omit_id, len(raw_list),
            note=(
                tr("[Большой массив байт скрыт для быстрого открытия диалогового окна. Для правки этого поля "
                   "экспортируйте объект как JSON-дамп.]")
            ),
        )
    if isinstance(value, (list, tuple)):
        return [prepare_dict_for_json_edit(v, omitted) for v in value]
    return value


def restore_dict_from_json_edit(value: Any, omitted: Optional[Dict[int, bytes]] = None) -> Any:
    """Inverse of prepare_dict_for_json_edit() — see its docstring. `omitted`
    must be the SAME dict that call filled, so an omitted field's placeholder
    (identified by its marker id, not its other, freely-editable content —
    see _omitted_bytes_placeholder()) can be replaced with the real bytes it
    stands for. Passing no `omitted` (the default) is only correct for a
    structure that can't contain one of these placeholders in the first
    place — e.g. import_object_json()'s own restore of a plain exported JSON
    dump, which uses _BYTES_MARKER_KEY/_BINARY_STRING_MARKER_KEY exclusively
    and never this dialog's own omission markers.

    Deleting a placeholder (or the whole field around it) is the one way to
    actually drop an omitted field instead of getting it back automatically
    — its marker id then appears nowhere in the restored structure, same as
    deleting any other field's key would; obj.patch() reacts to a missing
    field exactly the same way either way (see open_json_editor_dialog()'s
    own exception handling for that)."""
    if omitted is None:
        omitted = {}
    if isinstance(value, dict):
        omit_id = value.get(_OMITTED_BYTES_MARKER_KEY)
        if isinstance(omit_id, int) and omit_id in omitted:
            return omitted[omit_id]
        omit_id = value.get(_OMITTED_STRING_MARKER_KEY)
        if isinstance(omit_id, int) and omit_id in omitted:
            return omitted[omit_id].decode("utf-8", "surrogateescape")
        omit_id = value.get(_OMITTED_BYTE_LIST_MARKER_KEY)
        if isinstance(omit_id, int) and omit_id in omitted:
            return list(omitted[omit_id])
        if set(value.keys()) == {_BYTES_MARKER_KEY} and isinstance(value[_BYTES_MARKER_KEY], str):
            return bytes.fromhex(value[_BYTES_MARKER_KEY])
        if set(value.keys()) == {_BYTE_LIST_MARKER_KEY} and isinstance(value[_BYTE_LIST_MARKER_KEY], str):
            return list(bytes.fromhex(value[_BYTE_LIST_MARKER_KEY]))
        if set(value.keys()) == {_BINARY_STRING_MARKER_KEY} and isinstance(value[_BINARY_STRING_MARKER_KEY], str):
            return bytes.fromhex(value[_BINARY_STRING_MARKER_KEY]).decode("utf-8", "surrogateescape")
        return {k: restore_dict_from_json_edit(v, omitted) for k, v in value.items()}
    if isinstance(value, list):
        return [restore_dict_from_json_edit(v, omitted) for v in value]
    return value
