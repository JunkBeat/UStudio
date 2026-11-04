"""Bounded, crash-safe JSON dumps and the AssetStudioGUI-style typed structure dump."""

from core.i18n import tr
import json
import traceback
from typing import Any, Optional, Tuple
from UnityPy.helpers.TypeTreeHelper import metaflag_is_aligned
from .file_utils import format_size
from .progress import OperationCancelled

from .object_common import CancelCheck, _DUMP_MAX_DEPTH, _DUMP_MAX_LIST_ITEMS, _PRIMITIVE_TYPES, _check_cancelled, safe_parse_dict


# Shared with prepare_dict_for_json_edit()/restore_dict_from_json_edit() below —
# _to_jsonable() and the Edit Data path must encode raw bytes fields (TypelessData,
# a Mesh's index buffer, ...) the SAME way, so a round-trip through either "Edit
# Data" or "Export object"/"Extract this dump" -> hand-edit -> "Импортировать из
# JSON..." produces identical, correctly-typed results. See restore_dict_from_json_edit()'s
# docstring — patch()/write_typetree() write based on the TypeTree schema, not the
# JSON's own types, and pass a bare hex string straight to EndianBinaryWriter.write(),
# which raises TypeError on a str (confirmed against the real write path, not assumed).
_BYTES_MARKER_KEY = "__bytes_hex__"


# Distinct from _BYTES_MARKER_KEY above: this one marks a STRING field whose
# content looks binary (_looks_binary()) rather than an actually-bytes-typed
# field — restore_dict_from_json_edit() needs to tell the two apart to decode
# back to the right Python type (str vs bytes), since write_typetree() cares
# which one a given field's TypeTree schema actually expects.
_BINARY_STRING_MARKER_KEY = "__binary_str_hex__"


# A LIST of integers 0..255 that is really binary data (a Font's m_FontData is `vector<UInt8>`, which UnityPy
# hands back as a Python list) and is longer than the export's list cap: written whole as hex instead of being
# cut at max_list_items (Phonopolis/PUSS! fonts over 2,000,000 bytes used to export an incomplete dump without a
# word). Restored back to a list of ints - not bytes - by restore_dict_from_json_edit(). Lists under the cap
# keep their plain [1, 2, 3] form, so every dump that already worked looks the same.
_BYTE_LIST_MARKER_KEY = "__byte_list_hex__"


def _long_byte_list(value: list) -> Optional[bytes]:
    """The list's bytes when every item is an int in 0..255 (bools excluded by checking the ends' exact type;
    bytes() raises for anything else), else None."""
    if not value or type(value[0]) is not int or type(value[-1]) is not int:
        return None
    try:
        return bytes(value)
    except (ValueError, TypeError):
        return None


def _to_jsonable(
    value: Any,
    *,
    max_depth: int,
    max_list_items: int,
    max_string_len: int,
    max_bytes_len: int,
    should_cancel: CancelCheck,
    max_byte_list_len: int = 0,
    _depth: int = 0,
    _counter: Optional[list] = None,
) -> Any:
    """Recursively converts a parsed Unity object (dict/list/primitives, possibly
    containing raw bytes) into something json.dumps can handle: bounded depth,
    bounded list/dict length, bounded string/bytes length. A crafted object with a
    huge embedded count can't hang this — it gets truncated with a note instead.
    Any single field that fails to convert becomes an "<error: ...>" placeholder
    instead of aborting the whole dump. should_cancel(), if given, is polled
    periodically and raises OperationCancelled the moment a caller (the GUI's
    generation-counter guard) no longer wants the result."""
    if _counter is None:
        _counter = [0]
    _counter[0] += 1
    if _counter[0] % 500 == 0:
        _check_cancelled(should_cancel)

    try:
        if _depth > max_depth:
            return tr("<достигнута максимальная глубина>")

        if isinstance(value, dict):
            out = {}
            for i, (k, v) in enumerate(value.items()):
                if i >= max_list_items:
                    out["..."] = tr("(ещё {count} ключей)", count=len(value) - max_list_items)
                    break
                try:
                    out[str(k)] = _to_jsonable(
                        v, max_depth=max_depth, max_list_items=max_list_items,
                        max_string_len=max_string_len, max_bytes_len=max_bytes_len,
                        should_cancel=should_cancel, max_byte_list_len=max_byte_list_len,
                        _depth=_depth + 1, _counter=_counter,
                    )
                except OperationCancelled:
                    raise
                except Exception as e:
                    out[str(k)] = tr("<ошибка: {error}>", error=e)
            return out

        if isinstance(value, (list, tuple)):
            if max_byte_list_len and len(value) > max_list_items and type(value) is list:
                raw = _long_byte_list(value)
                if raw is not None:
                    if len(raw) > max_byte_list_len:
                        return f"<bytes: {format_size(len(raw))}>"   # import refuses it as an incomplete dump
                    return {_BYTE_LIST_MARKER_KEY: raw.hex()}
            out = []
            for i, v in enumerate(value):
                if i >= max_list_items:
                    out.append(tr("... (ещё {count} элементов)", count=len(value) - max_list_items))
                    break
                try:
                    out.append(_to_jsonable(
                        v, max_depth=max_depth, max_list_items=max_list_items,
                        max_string_len=max_string_len, max_bytes_len=max_bytes_len,
                        should_cancel=should_cancel, max_byte_list_len=max_byte_list_len,
                        _depth=_depth + 1, _counter=_counter,
                    ))
                except OperationCancelled:
                    raise
                except Exception as e:
                    out.append(tr("<ошибка: {error}>", error=e))
            return out

        if isinstance(value, (bytes, bytearray)):
            if len(value) > max_bytes_len:
                # Not reversible either way (data discarded past the cap) — a plain
                # note, not the marker, since there's nothing to restore regardless.
                return f"<bytes: {format_size(len(value))}>"
            return {_BYTES_MARKER_KEY: bytes(value).hex()}

        if isinstance(value, str):
            # A string decoded from binary-ish content (read_aligned_string()'s
            # errors="surrogateescape" codec — the common real case is a
            # TextAsset storing a custom binary format, see _looks_binary()'s own
            # docstring) can be megabytes of garbled surrogate-laden text and/or
            # contain lone surrogates the strict UTF-8 codec can't encode later.
            # Same {_BYTES_MARKER_KEY: hex} treatment as an actual bytes field
            # just below — round-tripped back to a real str (not bytes) by
            # restore_dict_from_json_edit(), which already needs to tell the two
            # apart for exactly this reason.
            if _looks_binary(value):
                return {_BINARY_STRING_MARKER_KEY: value.encode("utf-8", "surrogateescape").hex()}
            if len(value) > max_string_len:
                return value[:max_string_len] + tr("... (всего {count} симв.)", count=len(value))
            return value

        if isinstance(value, (int, float, bool)) or value is None:
            return value

        return str(value)
    except OperationCancelled:
        raise
    except Exception as e:
        return tr("<ошибка: {error}>", error=e)


def _resolve_parsed_data(obj) -> Tuple[Optional[dict], bool, Optional[str]]:
    """The full-parse-then-partial-fallback sequence previously duplicated
    between build_json_text() and dump_typed_text() (see git history —
    reconstructing this in the middle of each function separately, byte for
    byte identical logic in both). Factored out so build_preview() can also
    call it exactly once per object and hand the SAME (data, is_partial) pair
    to both consumers instead of each independently re-reading the object —
    see build_preview()'s own docstring for why that redundancy mattered.
    Returns (data_or_None, is_partial, error_or_None)."""
    data, err = safe_parse_dict(obj)
    if err:
        try:
            return obj.parse_as_dict(check_read=False), True, None
        except Exception:
            return None, False, err
    return data, False, None


def build_json_text(
    obj,
    *,
    max_depth: int,
    max_list_items: int,
    max_string_len: int,
    max_bytes_len: int,
    should_cancel: CancelCheck = None,
    partial_parse_note: bool = False,
    data: Optional[dict] = None,
    is_partial: bool = False,
    max_byte_list_len: int = 0,
) -> Tuple[Optional[str], Optional[str]]:
    """Returns (json_text, error) — parses obj via parse_as_dict(), converts the
    result through _to_jsonable() (bounded, crash-safe), then serializes. Raises
    OperationCancelled if should_cancel() reports the caller no longer wants this.

    If the full read fails (e.g. "Expected to read N bytes, but only read M" — a
    common IL2CPP TypeTree-generation symptom), falls back to a partial parse
    (check_read=False) rather than giving up entirely — mirrors main.py's previous
    inline fallback before this moved into core/. partial_parse_note controls
    whether a human-readable note gets PREPENDED to the returned text: True for the
    preview path (build_preview_json feeds a text widget meant for a person to
    read), False for the export path (build_export_json's output is a .json file
    expected to be valid, re-importable JSON on its own — a prepended sentence
    would corrupt it, exactly the bug a round-trip export-then-import test caught).

    data/is_partial: an already-parsed dict a caller computed once and wants
    reused instead of parsing again (see build_preview()'s own docstring for
    the real, measured redundant-parsing problem this closes for a large
    object). Both default to None/False, in which case this parses fresh
    exactly as before — every existing caller (cli/commands.py included)
    that doesn't pass these keeps working unchanged."""
    if data is None:
        data, is_partial, err = _resolve_parsed_data(obj)
        if data is None:
            return None, err

    safe_data = _to_jsonable(
        data, max_depth=max_depth, max_list_items=max_list_items,
        max_string_len=max_string_len, max_bytes_len=max_bytes_len,
        should_cancel=should_cancel, max_byte_list_len=max_byte_list_len,
    )
    try:
        text = json.dumps(safe_data, indent=2, ensure_ascii=False)
    except Exception as e:
        return None, tr("Не удалось записать JSON: {error}", error=e)

    if is_partial and partial_parse_note:
        text = tr("Не удалось прочитать полный дамп.\nНиже приведён результат частичного парсинга.") + "\n\n" + text
    return text, None


def build_preview_json(
    obj, should_cancel: CancelCheck = None, data: Optional[dict] = None, is_partial: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """Small caps — this feeds the GUI's Json Dump tab, which should stay
    responsive even against a crafted/huge object. data/is_partial: see
    build_json_text()'s own docstring."""
    return build_json_text(
        obj, max_depth=10, max_list_items=200, max_string_len=2000,
        max_bytes_len=48, should_cancel=should_cancel, partial_parse_note=True,
        data=data, is_partial=is_partial,
    )


def build_export_json(
    obj, data: Optional[dict] = None, is_partial: bool = False,
) -> Tuple[Optional[str], Optional[str], bool]:
    """Generous caps — export is a deliberate user action expecting full fidelity,
    but still bounded so a pathological file can't hang or exhaust memory.

    Real reported problem: a PARTIAL parse (the common IL2CPP TypeTree-generation
    failure — see "Known open items" in CLAUDE.md) used to still export as a
    "complete-looking" .dump.json, silently missing most of the object's fields
    with nothing in the file itself indicating that (build_json_text()'s
    partial_parse_note is deliberately off for export, precisely so the output
    stays valid, re-importable JSON — but that same silence meant an incomplete
    dump was indistinguishable from a real one once saved to disk). Returns
    (None, reason, True) for this case instead — every export call site treats
    is_partial=True as a SKIP (an expected, non-error "nothing usable to write"
    outcome, the same category export_object()'s own docstring already
    established for an empty texture/no-samples AudioClip), not a genuine
    failure, and nothing gets written.

    Returns (json_text, error, is_partial). data/is_partial: an already-resolved
    parse a caller computed once and wants reused instead of parsing again — see
    build_json_text()'s own docstring for the general pattern (unused by any
    current caller of THIS function specifically, kept for API symmetry with
    build_preview_json())."""
    if data is None:
        data, is_partial, err = _resolve_parsed_data(obj)
        if data is None:
            return None, err, False
    if is_partial:
        # Short by design (see object_actions.py::_make_bulk_export_fn's own
        # grouped-log-line handling) — a bulk export with many objects sharing
        # this exact reason collapses them onto one line ("Пропущено N: name1,
        # name2, ... — причина"), so the reason text itself needs to stay
        # short, not read like a standalone sentence.
        return None, tr("неполный дамп"), True

    text, err = build_json_text(
        obj, max_depth=64, max_list_items=2_000_000, max_string_len=50_000_000,
        max_bytes_len=1_000_000, should_cancel=None, partial_parse_note=False,
        data=data, is_partial=False, max_byte_list_len=50_000_000,
    )
    return text, err, False


# prepare_dict_for_json_edit()'s cutoff between hex-encoding a bytes/binary-
# string field inline (as {_BYTES_MARKER_KEY: hex}) and OMITTING its content
# from the editable text entirely (see _OMITTED_BYTES_MARKER_KEY below for
# why, and why that's better than the flat 1 MB "refuse the whole dialog"
# gate this replaces). At the ~0.23 s/MB-of-hex-TEXT rate measured against a
# real widget (see git history for the original measurement), this many bytes
# hex-encodes to well under 100 ms of setPlainText()/highlighter cost even in
# the worst case (one single-line JSON value, no chunked-loading protection
# possible) — small enough that ordinary padding/lookup-table bytes fields
# stay fully inline and hand-editable as before, while any real texture/
# audio/mesh-sized blob (which starts in the tens-of-KB range at minimum)
# gets omitted regardless of the surrounding object's total dump size.
_EDIT_OMIT_BYTES_THRESHOLD = 8192


# A bytes/binary-string field over _EDIT_OMIT_BYTES_THRESHOLD gets THIS
# marker instead of {_BYTES_MARKER_KEY: hex}/{_BINARY_STRING_MARKER_KEY: hex}
# — its content is never turned into text at all, so opening "Edit Data" on
# an object with a multi-MB pixel/audio/mesh field stays fast regardless of
# size (see prepare_dict_for_json_edit()'s docstring for the real report this
# replaces: a flat "refuse the whole dialog above 1 MB" gate, which fixed the
# freeze but banned editing any OTHER field of that same object too — a real,
# reported regression in its own right for objects that legitimately mix a
# huge binary blob with small fields worth hand-editing).
#
# The marker's value is an int id, unique within one prepare_dict_for_json_edit()
# call, used as the key into the `omitted` side-table that call fills — see
# restore_dict_from_json_edit() for how the real bytes come back. A SEPARATE
# key from _OMITTED_STRING_MARKER_KEY below (same reasoning _BYTES_MARKER_KEY/
# _BINARY_STRING_MARKER_KEY are already kept separate for) since the two must
# decode back to different Python types (bytes vs. str).
_OMITTED_BYTES_MARKER_KEY = "__omitted_bytes__"
_OMITTED_STRING_MARKER_KEY = "__omitted_str__"
# Same idea for a field that arrives as a LIST OF INTEGERS 0..255 but is really binary data (a Font's
# m_FontData is `vector<UInt8>`, which UnityPy hands back as a Python list, not bytes). It must come
# back as a list of ints, not bytes, hence its own marker.
_OMITTED_BYTE_LIST_MARKER_KEY = "__omitted_byte_list__"


_DUMP_MAX_STRING_LEN = 4096  # A single huge string field (e.g. a multi-MB/GB


def format_typed_value(type_name: str, value: Any) -> str:
    if type_name == "string":
        s = str(value)
        if len(s) > _DUMP_MAX_STRING_LEN:
            s = s[:_DUMP_MAX_STRING_LEN] + tr("... (обрезано, всего {count} симв.)", count=len(s))
        return f'"{s}"'
    if type_name == "bool":
        return "True" if value else "False"
    return str(value)


_HEX_DUMP_SAMPLE_CHARS = 65536  # Comfortably covers _HEX_DUMP_MAX_BYTES's worth


# of raw bytes even in the worst case (every char re-encoding to multiple UTF-8
# bytes) — avoids re-encoding a potentially huge (100+MB) TextAsset in full just
# to build a preview that only ever shows its first _HEX_DUMP_MAX_BYTES anyway.
_HEX_DUMP_MAX_BYTES = 16 * 1024


def _looks_binary(text: str, sample_chars: int = 8192) -> bool:
    """Same heuristic git itself uses for "is this file binary": a NUL byte within
    the first N bytes is something no genuine text file contains, but is common in
    binary payloads Unity sometimes ships as TextAsset (e.g. a custom binary
    format an addressables/modding pipeline stashes there for import-time access).
    Checked against a small bounded prefix, not read_aligned_string()'s full
    (possibly huge) decoded text, so this stays cheap regardless of asset size."""
    sample = text[:sample_chars].encode("utf-8", "surrogateescape")
    return b"\0" in sample


def _format_hex_dump(text: str) -> str:
    """Classic offset/hex/ascii hexdump of text's underlying bytes (recovered via
    the same surrogateescape codec read_aligned_string() decoded them with — a
    lossless round-trip for arbitrary byte sequences), bounded to
    _HEX_DUMP_MAX_BYTES regardless of the asset's real size — the whole point of
    this function existing is to never hang formatting an unbounded amount of
    binary data into the preview widget."""
    sample = text[:_HEX_DUMP_SAMPLE_CHARS].encode("utf-8", "surrogateescape")
    shown = sample[:_HEX_DUMP_MAX_BYTES]
    lines = []
    for offset in range(0, len(shown), 16):
        chunk = shown[offset:offset + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part:<47}  {ascii_part}")
    dump_text = "\n".join(lines)
    if len(text) > len(shown):
        dump_text += "\n\n" + tr("... предпросмотр обрезан после {size} — полные данные доступны через экспорт объекта.",
                                  size=format_size(len(shown)))
    return dump_text


def _dump_node(
    node, value: Any, level: int, lines: list,
    should_cancel: CancelCheck, counter: list,
) -> None:
    counter[0] += 1
    if counter[0] % 500 == 0:
        _check_cancelled(should_cancel)

    tabs = "\t" * level
    try:
        if level > _DUMP_MAX_DEPTH:
            lines.append(tabs + tr("<достигнута максимальная глубина>"))
            return

        # TypelessData and generic primitives are both checked BEFORE the vector/
        # array test below, matching UnityPy's own read_value()'s branch order
        # exactly: "string"/"TypelessData" structurally have an "Array" child in the
        # raw schema too (Unity encodes them as char/byte vectors under the hood),
        # but read_value short-circuits via FUNCTION_READ_MAP before ever looking at
        # m_Children — checking the array shape first here produced a wrong "Array
        # Array / int size = 0" dump for every string field instead of `string
        # m_Name = "..."`. TypelessData is checked ahead of the generic primitive
        # branch specifically because AssetStudioGUI dumps it as two lines (header +
        # size), not the primitive "= value" shape — and it's never worth printing
        # raw bytes inline here regardless.
        if node.m_Type == "TypelessData":
            lines.append(f"{tabs}{node.m_Type} {node.m_Name}")
            lines.append(f"{tabs}\tint size = {len(value) if value is not None else 0}")
            return

        if node.m_Type in _PRIMITIVE_TYPES:
            lines.append(f"{tabs}{node.m_Type} {node.m_Name} = {format_typed_value(node.m_Type, value)}")
            return

        # Vector/array field — same "node.m_Children[0].m_Type == 'Array'" test
        # UnityPy's own read_value() uses to recognize a vector during parsing.
        if node.m_Children and node.m_Children[0].m_Type == "Array":
            lines.append(f"{tabs}{node.m_Type} {node.m_Name}")
            array_node = node.m_Children[0]
            subtype = array_node.m_Children[1]
            seq = value if isinstance(value, (list, tuple)) else []
            size = len(seq)
            lines.append(f"{tabs}\tArray Array")
            lines.append(f"{tabs}\tint size = {size}")
            is_pair = subtype.m_Type == "pair"
            shown = min(size, _DUMP_MAX_LIST_ITEMS)
            for j in range(shown):
                item_tabs = tabs + "\t\t"
                lines.append(f"{item_tabs}[{j}]")
                if is_pair and len(subtype.m_Children) == 2:
                    lines.append(f"{item_tabs}pair data")
                    k, v = seq[j] if isinstance(seq[j], (tuple, list)) and len(seq[j]) == 2 else (None, None)
                    _dump_node(subtype.m_Children[0], k, level + 3, lines, should_cancel, counter)
                    _dump_node(subtype.m_Children[1], v, level + 3, lines, should_cancel, counter)
                else:
                    _dump_node(subtype, seq[j], level + 2, lines, should_cancel, counter)
            if size > shown:
                lines.append(tabs + "\t\t" + tr("... (ещё {count} элементов)", count=size - shown))
            return

        if node.m_Type == "pair" and len(node.m_Children) == 2:
            lines.append(f"{tabs}{node.m_Type} {node.m_Name}")
            first, second = value if isinstance(value, (tuple, list)) and len(value) == 2 else (None, None)
            _dump_node(node.m_Children[0], first, level + 1, lines, should_cancel, counter)
            _dump_node(node.m_Children[1], second, level + 1, lines, should_cancel, counter)
            return

        # Class / compound — includes PPtr<...>, which UnityPy's own read_value()
        # also treats as a plain Class of m_FileID/m_PathID: no resolved-name
        # lookup here either, matching AssetStudioGUI's reference dump exactly.
        lines.append(f"{tabs}{node.m_Type} {node.m_Name}")
        child_value = value if isinstance(value, dict) else {}
        for child in node.m_Children:
            _dump_node(child, child_value.get(child.m_Name), level + 1, lines, should_cancel, counter)
    except OperationCancelled:
        raise
    except Exception as e:
        lines.append(tabs + tr("<ошибка: {error}>", error=e))


def dump_typed_text(
    obj, should_cancel: CancelCheck = None, data: Optional[dict] = None, is_partial: bool = False,
    node=None,
) -> Tuple[Optional[str], Optional[str], bool]:
    """Renders obj's parsed field tree as AssetStudioGUI's typed dump text (e.g.
    "MonoBehaviour Base" / "\tPPtr<GameObject> m_GameObject" / "\t\tint m_FileID =
    0") — this is the Dump tab's content for every type. Walks the TypeTreeNode
    schema (obj._get_typetree_node(), the same accessor dump_typetree_structure()
    already uses) alongside parse_as_dict()'s value tree — UnityPy builds both from
    the same node list in the same order, so child.m_Name reliably indexes into the
    value dict at every level. Bounded/cancellable the same way as
    build_json_text().

    Returns (text, error, is_partial) — is_partial is True exactly when the full
    parse failed and this fell back to a partial one (check_read=False); the
    caller (build_preview()) surfaces this via PreviewResult.dump_partial so a
    real, non-obvious failure (a MonoBehaviour that "mostly" read but is
    missing fields past the point it desynced) still triggers the IL2CPP
    warning banner — a real request, since it used to only fire when the dump
    failed outright (dump_text is None), not when it silently degraded to a
    partial result instead.

    data/is_partial/node: an already-parsed dict and/or schema node a caller
    computed once and wants reused instead of re-reading the object — see
    build_json_text()'s own docstring for the shared reasoning (this function
    used to independently repeat the EXACT SAME parse build_preview_json()
    also does, for every single object). All default to None/False, in which
    case this parses fresh exactly as before — cli/commands.py's own direct
    dump_typed_text(obj) call keeps working unchanged."""
    if node is None:
        try:
            node = obj._get_typetree_node()
        except Exception as e:
            return None, f"{e}\n{traceback.format_exc()}", False

    note = ""
    if data is None:
        data, is_partial, err = _resolve_parsed_data(obj)
        if data is None:
            return None, err, False
    if is_partial:
        note = tr("Не удалось прочитать полный дамп.\nНиже приведён результат частичного парсинга.") + "\n\n"

    lines: list = []
    _dump_node(node, data, 0, lines, should_cancel, [0])
    return note + "\n".join(lines), None, is_partial


def _walk_structure_node(node, level: int, lines: list, should_cancel: CancelCheck, counter: list) -> None:
    counter[0] += 1
    if counter[0] % 500 == 0:
        _check_cancelled(should_cancel)
    if level > _DUMP_MAX_DEPTH:
        lines.append(" " * level + tr("<достигнута максимальная глубина>"))
        return
    align = "1" if metaflag_is_aligned(node.m_MetaFlag) else "0"
    lines.append(f"{' ' * level}{align} {node.m_Type} {node.m_Name}")
    for child in node.m_Children:
        _walk_structure_node(child, level + 1, lines, should_cancel, counter)


def dump_structure_text(obj, should_cancel: CancelCheck = None) -> Tuple[Optional[str], Optional[str]]:
    """Renders obj's TypeTree SCHEMA only — type/name/alignment per field, no
    values at all — the Structure tab's content. Unlike dump_typed_text(), this
    never touches the object's actual byte data (parse_as_dict()/read_typetree()),
    only obj._get_typetree_node() — so it stays fast regardless of the object's own
    size (a vector field's schema is always just one "Array"/"size"/"data" shape,
    never expanded per actual runtime array length, unlike the Dump tab's per-
    element walk) and stays available even for an object whose VALUE parse fails
    (e.g. a read-size-mismatch IL2CPP script), since nothing here ever reads past
    the schema.

    The leading 0/1 on each line is metaflag_is_aligned(node.m_MetaFlag) — whether
    the parser aligns to a 4-byte boundary after this field — the one piece of
    per-field debug information worth surfacing here that a plain type/name pair
    on its own wouldn't show."""
    try:
        node = obj._get_typetree_node()
    except Exception as e:
        return None, f"{e}\n{traceback.format_exc()}"

    lines: list = []
    try:
        _walk_structure_node(node, 0, lines, should_cancel, [0])
    except OperationCancelled:
        raise
    except Exception as e:
        lines.append(tr("<ошибка: {error}>", error=e))
    return "\n".join(lines), None
