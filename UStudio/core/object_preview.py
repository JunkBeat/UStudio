"""PyQt-free per-object preview/export/import logic — the actual business logic
behind main.py's Preview/Json Dump tabs and its "Export object"/"Import from JSON"
context-menu actions. Kept separate from PyQt6 (same reasoning as core/loader.py
and core/cab_archive.py) so a future console-mode front end can call build_preview()/
export_object()/import_object_json() directly instead of the GUI layer being the
only place this logic exists.

Reuses UnityPy's own image/audio/mesh/shader conversion (classes/legacy_patch,
export/) — the same properties/methods the GUI's parse_as_dict()/patch() calls
already rely on elsewhere in this project, just dispatched per type instead of
always falling through to a raw JSON dump."""

from core.i18n import tr
import json
import traceback
from dataclasses import dataclass
from typing import Any, Optional
from .file_utils import format_size
from .progress import OperationCancelled

from .object_common import CancelCheck, _TEXTASSET_JSON_FORMAT_LIMIT, _check_cancelled, _sprite_empty_reason, _texture_empty_reason, resolve_object_name, resolve_texture_format_name
from .object_dump import _format_hex_dump, _looks_binary, _resolve_parsed_data, build_preview_json, dump_structure_text, dump_typed_text
from .object_resources import check_resource_reference, read_videoclip_bytes


@dataclass
class PreviewResult:
    kind: str  # "image" | "audio" | "video" | "text" | "info" | "json" | "font" | "mesh"
    title: str = ""
    image: Any = None  # PIL.Image.Image
    array_images: Optional[list] = None  # Texture2DArray only — every decoded slice,
    # `image` above is always array_images[0]; PreviewPanel's "< N/N >" navigator
    # indexes into this instead of re-decoding per slice.
    audio_samples: Optional[dict] = None
    audio_name: str = ""
    video_data: Optional[bytes] = None
    video_ext: str = ""
    video_name: str = ""
    text: str = ""
    text_editable: bool = False
    # False for a hex dump: its columns only line up unwrapped, so the preview forces NoWrap and hides the
    # "Перенос строк" checkbox for it (the saved checkbox state is left alone).
    text_wrappable: bool = True
    info_text: str = ""
    font_data: Optional[bytes] = None
    json_text: Optional[str] = None
    json_error: Optional[str] = None
    dump_text: Optional[str] = None
    dump_error: Optional[str] = None
    dump_partial: bool = False
    structure_text: Optional[str] = None
    structure_error: Optional[str] = None
    resource_warning: Optional[str] = None
    compact_summary: str = ""
    # Set only for the "json" kind (MonoBehaviour/Material/AnimationClip/
    # GameObject/... — see build_preview()'s own docstring): the ONE
    # parse_as_dict()/_get_typetree_node() this whole preview build did,
    # handed back so PreviewPanel can feed the SAME result into
    # ObjectStructureTree.set_object() instead of it re-parsing a fourth time.
    # None for every other kind (image/audio/video/text/font/info) — those
    # never had this redundancy in the first place (their own type-specific
    # decode already uses parse_as_object(), a different representation), so
    # ObjectStructureTree falls back to its own default parse for them,
    # unchanged from before.
    parsed_data: Optional[dict] = None
    parsed_node: Any = None
    # Set only for the handful of rich-preview types where a real, measured
    # cost (not just theoretical) was found in build_compact_summary()
    # independently re-parsing/re-decoding via its own obj.parse_as_object()
    # call — currently Texture2D/Texture2DArray (a real, measured 0.03-0.15s
    # per redundant parse) and AudioClip (a REAL AUDIO DECODE — FMOD/Vorbis→PCM
    # — done twice per selection, measured 0.3-0.8s each time on a real 7MB
    # clip). Sprite/VideoClip/Font were measured too and found cheap enough
    # (single-digit ms) not to be worth this — see the module's own commit
    # history for the actual numbers. None for every other kind.
    parsed_object: Any = None
    mesh_geometry: Any = None  # "mesh" only: core.mesh_geometry.MeshGeometry, built here in the worker
    model_materials: Optional[list] = None  # a GameObject's model: «Материалы и текстуры» rows (Reference)
    model_materials_total: int = 0
    # The «Сведения» tab (core/object_references.py): the object's plain facts and what it refers to (the first
    # MAX_REFERENCES references, reference_total of them in all), from the same parse as the Dump tab.
    facts: Any = None
    references: Optional[list] = None
    reference_total: int = 0


def _info(title: str, text: str) -> PreviewResult:
    return PreviewResult(kind="info", title=title, info_text=text)


def _type_specific_preview(obj, type_name: str, name: str, should_cancel: CancelCheck = None) -> PreviewResult:
    try:
        if type_name in ("Texture2D", "Texture2DArray"):
            data, err = None, None
            try:
                data = obj.parse_as_object()
            except Exception as e:
                err = f"{e}\n{traceback.format_exc()}"
            if err:
                return _info(tr("Ошибка предпросмотра: {name}", name=name), err)
            empty_reason = _texture_empty_reason(data)
            if empty_reason:
                return _info(f"{type_name}: {name}", tr("{reason} — предпросмотр недоступен.", reason=empty_reason))
            fmt_str = resolve_texture_format_name(getattr(data, "m_TextureFormat", None))

            if type_name == "Texture2DArray":
                # Real reported crash: Texture2DArray has no .image at all (only
                # the plural .images — confirmed in UnityPy/classes/legacy_patch/
                # Texture2DArray.py, one PIL image per depth slice, decoded all
                # at once from the array's single contiguous byte blob). Decoded
                # once here and cached on the result rather than lazily per-slice
                # — PreviewPanel's "< N/N >" navigator then just indexes into an
                # already-decoded list, no re-decode per click.
                images = data.images
                if not images:
                    return _info(f"{type_name}: {name}", tr("Слои текстуры не найдены — предпросмотр недоступен."))
                img = images[0]
                return PreviewResult(
                    kind="image", image=img, array_images=images,
                    title=tr("{name}  ({width}x{height}, {format}, слой {layer}/{layers})", name=name,
                             width=img.width, height=img.height, format=fmt_str, layer=1, layers=len(images)),
                    parsed_object=data,
                )

            img = data.image
            return PreviewResult(
                kind="image", image=img, title=f"{name}  ({img.width}x{img.height}, {fmt_str})",
                parsed_object=data,
            )

        if type_name == "Sprite":
            data = obj.parse_as_object()
            empty_reason = _sprite_empty_reason(data)
            if empty_reason:
                return _info(f"{type_name}: {name}", tr("{reason} — предпросмотр недоступен.", reason=empty_reason))
            img = data.image
            return PreviewResult(kind="image", image=img, title=f"{name}  ({img.width}x{img.height})")

        if type_name == "AudioClip":
            # data.samples is a REAL audio decode (FMOD/Vorbis -> PCM, not a
            # cheap TypeTree read) — measured 0.3-0.8s on a real 7MB clip.
            # build_compact_summary()'s own AudioClip builder used to
            # independently trigger this SAME decode again just to read the
            # WAV header (frequency/channels/bit depth) — stashing the
            # already-decoded `data` here lets it reuse this one instead.
            data = obj.parse_as_object()
            return PreviewResult(kind="audio", audio_samples=data.samples, audio_name=name, parsed_object=data)

        if type_name == "TextAsset":
            data = obj.parse_as_object()
            text = data.m_Script
            # read_aligned_string() (the reader m_Script goes through) always
            # decodes via UTF-8 with errors="surrogateescape" — it never raises
            # and never leaves text as raw bytes, so this always was already a
            # str, never bytes. A binary TextAsset (a custom data format some
            # games ship this way) used to render as-is: potentially megabytes of
            # garbled text handed straight to QTextEdit.setPlainText() with a
            # syntax highlighter attached, which is what could actually make the
            # GUI stall/appear frozen — not a UnicodeDecodeError, which never
            # happens here. _looks_binary()/_format_hex_dump() below detect that
            # case and show a small, bounded hex dump instead.
            if _looks_binary(text):
                hex_text = _format_hex_dump(text)
                # len(text) (character count), not a full re-encode to bytes — for
                # a huge binary blob (hundreds of MB), re-encoding the ENTIRE thing
                # just to report a byte count would itself take real time for a
                # value the hex dump below only ever samples the first bit of
                # anyway. Effectively exact for genuinely binary content (each
                # non-UTF8 byte maps to exactly one surrogate-escaped char), only
                # approximate if some valid multi-byte UTF-8 sequence happens to
                # appear by coincidence within the binary data.
                title = tr("TextAsset: {name} (бинарные данные, ~{size})", name=name, size=format_size(len(text)))
                return PreviewResult(kind="text", text=hex_text, text_editable=False, text_wrappable=False, title=title)

            # Games routinely ship config/data TextAssets as minified (single-
            # line) JSON — pretty-print it via the stdlib json module (already
            # imported, already used elsewhere in this file for the Json Dump
            # tab — no new formatting logic needed) so it's actually readable.
            # JsonHighlighter is already attached to this preview tab's text
            # widget unconditionally (see preview_panel.py), so once the text
            # is reformatted it gets colored for free, no extra wiring here.
            # Size-capped: json.loads()+dumps() means holding the whole thing
            # parsed AND re-serialized in memory at once, which isn't worth
            # doing automatically for a huge TextAsset — it still displays
            # fine as plain text past this size, just not reformatted.
            title = f"TextAsset: {name}"
            if len(text) <= _TEXTASSET_JSON_FORMAT_LIMIT:
                try:
                    parsed = json.loads(text)
                except (ValueError, TypeError):
                    pass
                else:
                    # Only actual structured JSON (an object or array) — a
                    # TextAsset whose entire content is just a bare number/
                    # string/bool happens to be technically valid JSON too,
                    # but reformatting it wouldn't mean anything.
                    if isinstance(parsed, (dict, list)):
                        text = json.dumps(parsed, indent=2, ensure_ascii=False)
                        title = f"TextAsset: {name} (JSON)"
            return PreviewResult(kind="text", text=text, text_editable=False, title=title)

        if type_name == "Shader":
            data = obj.parse_as_object()
            try:
                shader_text = data.export()
            except Exception as e:
                # Known gap (confirmed present in upstream UnityPy and the
                # AssetStudio it was ported from, not something introduced here):
                # a platform whose compiled data is split across multiple
                # sequential LZ4 chunks (offsets/compressedLengths/decompressedLengths
                # nested more than one level deep) only ever gets its first chunk
                # decompiled — everything past that chunk reads into a buffer that
                # was never assembled. Confirmed via a real 22MB Shader from a
                # shipped Steam game (Escape Simulator, 73 chunks under one
                # platform). Not fixed — would need reconstructing untested
                # multi-chunk concatenation logic, and even a correct decompile
                # would likely be huge (that shader alone: 108,923 subprograms).
                # Surfacing the real exception here instead of a bare "failed"
                # message at least tells the user (or a future debugging session)
                # what actually went wrong instead of a dead end.
                shader_text = tr("Не удалось декомпилировать шейдер: {error}", error=f"{type(e).__name__}: {e}")
            return PreviewResult(kind="text", text=shader_text, text_editable=False, title=f"Shader: {name}")

        if type_name == "VideoClip":
            # AssetStudioGUI itself has no video preview at all (confirmed against
            # its source: "Only supported export.") — this app's own QtMultimedia
            # stack (already relied on for AudioClip playback) can actually decode
            # and play video too, so this is new UI, not a port. See
            # gui_widgets.VideoPreviewWidget's own docstring for why this adds no
            # new dependency beyond what audio preview already needed.
            raw, ext, skip_reason = read_videoclip_bytes(obj)
            if skip_reason:
                return _info(f"VideoClip: {name}", skip_reason)
            return PreviewResult(kind="video", video_data=raw, video_ext=ext, video_name=name, title=f"VideoClip: {name}")

        if type_name == "Font":
            data = obj.parse_as_object()
            font_data = bytes(data.m_FontData) if data.m_FontData else b""
            if not font_data:
                return _info(f"Font: {name}", tr("В шрифте нет встроенных данных — предпросмотр недоступен."))
            return PreviewResult(kind="font", font_data=font_data, title=f"Font: {name}")

        if type_name == "GameObject":
            # its meshes (and its children's) assembled into one model (core/model_assembly.py); a GameObject with
            # nothing visible under it keeps the JSON view below
            from .model_assembly import NoModel, gameobject_model
            try:
                model = gameobject_model(obj, should_cancel)
            except NoModel:
                model = None
            if model is not None:
                from .object_references import incoming_references
                rows, total = incoming_references(model.sources)
                return PreviewResult(kind="mesh", mesh_geometry=model, title=f"GameObject: {name}",
                                     model_materials=rows, model_materials_total=total)

        if type_name == "Mesh":
            from .mesh_geometry import MeshNotDrawable, mesh_geometry
            data = obj.parse_as_object()
            try:
                geometry = mesh_geometry(data)
            except MeshNotDrawable as e:
                return _info(f"Mesh: {name}", f"{e} " + tr("Показывать нечего."))
            return PreviewResult(kind="mesh", mesh_geometry=geometry, title=f"Mesh: {name}", parsed_object=data)

    except OperationCancelled:
        raise                       # a newer selection: not an error (the GameObject model walk checks it)
    except Exception as e:
        return _info(tr("Ошибка предпросмотра: {name}", name=name),
                     tr("Тип: {type}", type=type_name) + "\n\n" + tr("Ошибка:") + f"\n{e}\n{traceback.format_exc()}")

    # MonoBehaviour, GameObject, Material, AnimationClip, AnimatorController, and
    # anything else without a dedicated preview above: tab 1 shows the parsed JSON
    # directly instead of a summary (filled in by build_preview, below) — the typed
    # Dump tab (tab 2) always has the full structure regardless of kind.
    return PreviewResult(kind="json", title=f"{type_name}: {name}")


def build_preview(
    obj, should_cancel: CancelCheck = None, skip_rich_preview: bool = False
) -> PreviewResult:
    """The one entry point main.py's background preview worker calls. Never raises
    for a bad/malformed object — worst case returns an "info" result describing the
    error. Can raise OperationCancelled if should_cancel() fires while the JSON/Dump
    text is being built (the parts of this that are actually interruptible
    mid-work).

    skip_rich_preview=True (CONFIG.preview_enabled off, via the Вид menu) skips
    ONLY _type_specific_preview()/build_preview_json() — the per-type decode
    (image/audio/font decoding, a full typetree JSON walk) that's the actual
    expensive part for a hard-case object (e.g. the 18MB-compressedBlob Shader
    from CLAUDE.md's own perf story). dump_text is still built either way: a
    real reported bug was disabling preview also silently killing the
    structure tree and Dump tab, which have nothing to do with the expensive
    part and have their own separate CONFIG.show_tree_view/show_dump_view
    switches already — this keeps them independent."""
    type_name = obj.type.name
    name = resolve_object_name(obj)

    # Cheap (a bounded peek + a couple of dict/stat lookups, no decoding) — run
    # unconditionally, even when skip_rich_preview is on, so the warning still
    # shows up for the one case that matters most: a user about to trust an
    # image/audio/mesh preview that isn't actually this object's data.
    issue = check_resource_reference(obj)

    is_partial = False
    if skip_rich_preview:
        result = _info(name, tr("Предпросмотр отключён в настройках программы."))
    else:
        result = _type_specific_preview(obj, type_name, name, should_cancel)
        if result.kind == "json":
            # Real, measured problem this branch closes: MonoBehaviour/
            # TMP_FontAsset/GameObject/Material/... (everything routed to this
            # shared "json" kind) used to get parsed from scratch
            # independently FOUR times per selection — build_preview_json()
            # below, dump_typed_text() further down, ObjectStructureTree.
            # set_object() (GUI thread, in preview_panel.py), and
            # build_compact_summary()'s TMP_FontAsset Cyrillic check — each a
            # full re-read of the same object's raw bytes. Measured directly
            # against a real 250-300KB TMP_FontAsset: ~100ms settling time,
            # UNCHANGED whether cold or already warm — i.e. not a one-time
            # cost, a recurring one paid on every single selection, and (once
            # this session's UnityPy reader-lock fix made concurrent reads of
            # the same file correctly serialize instead of silently racing)
            # visibly staggered besides. Parsing once HERE and handing the
            # SAME (data, node) to every consumer below — and, via
            # PreviewResult.parsed_data/parsed_node, back to PreviewPanel for
            # the structure tree — is the actual fix.
            _check_cancelled(should_cancel)
            data, is_partial, _parse_err = _resolve_parsed_data(obj)
            node = None
            if data is not None:
                try:
                    node = obj._get_typetree_node()
                except Exception:
                    node = None
            result.parsed_data = data
            result.parsed_node = node
            result.json_text, result.json_error = build_preview_json(
                obj, should_cancel=should_cancel, data=data, is_partial=is_partial,
            )

    if issue is not None:
        result.resource_warning = issue.message

    _check_cancelled(should_cancel)
    # One parse for the Dump tab AND the «Сведения» references: the "json" kind already has it; for the other kinds
    # dump_typed_text() used to parse on its own — the same parse, now made here and handed in. When it fails,
    # dump_typed_text() gets nothing and reports the error exactly as before.
    dump_data, dump_node = result.parsed_data, result.parsed_node
    if dump_data is None:
        dump_data, is_partial, _parse_err = _resolve_parsed_data(obj)
        if dump_data is not None:
            try:
                dump_node = obj._get_typetree_node()
            except Exception:
                dump_data = dump_node = None
    result.dump_text, result.dump_error, result.dump_partial = dump_typed_text(
        obj, should_cancel=should_cancel, data=dump_data, is_partial=is_partial, node=dump_node,
    )
    _check_cancelled(should_cancel)
    from .object_references import merge_same_targets, object_facts, outgoing_references
    try:
        result.facts = object_facts(obj)
        # one row per target object (a Material's _BaseMap and _MainTex holding the same texture: one row)
        result.references, result.reference_total = merge_same_targets(
            *outgoing_references(obj, dump_data, dump_node))
    except Exception:
        result.references, result.reference_total = None, 0     # «Сведения» must never break the preview
    _check_cancelled(should_cancel)
    result.structure_text, result.structure_error = dump_structure_text(obj, should_cancel=should_cancel)

    # Same shared-parse reuse for the compact one-line summary strip under the
    # preview (core/object_metadata.py) — computed here now (a plain string,
    # safe to build off the GUI thread) instead of PreviewPanel calling it
    # synchronously on the GUI thread before this background read even
    # started. That original split (two GUI-thread reads + two background-
    # thread reads of the same object) is exactly what produced the "preview
    # and tree load staggered" symptom once the reads were correctly
    # serialized against each other. Local import to avoid a circular one —
    # object_metadata.py already imports FROM this module — same precedent
    # object_metadata._compact_monobehaviour() itself already uses for
    # core.sdf_resolver.
    from .object_metadata import build_compact_summary
    result.compact_summary = build_compact_summary(
        obj,
        data=result.parsed_data if result.parsed_data is not None else result.parsed_object,
        audio_samples=result.audio_samples,
    )
    if result.kind == "mesh":
        # the 3D view's facts go in the strip under the preview, like every other type's (user request)
        from .mesh_geometry import summary_parts
        from .object_metadata import COMPACT_SEPARATOR
        result.compact_summary = COMPACT_SEPARATOR.join(summary_parts(result.mesh_geometry))

    return result


# Everything that used to live in this module is re-exported so existing imports keep working.
# ruff: noqa: F401,E402
from .object_common import (
    CancelCheck, IMPORT_WARNING_PREFIX, MAX_IMPORT_JSON_BYTES, RESOURCE_BACKED_TYPES,
    RICH_PREVIEW_TYPES, ROW_FIELD_UNRESOLVED, _DUMP_MAX_DEPTH, _DUMP_MAX_LIST_ITEMS,
    _FULL_MIPMAP_CHAIN, _INLINE_CONTENT_FIELD, _MAX_GAMEOBJECT_FALLBACK_NAME_LEN, _PENDING_RESOURCE_TEMP_FILES,
    _PRIMITIVE_TYPES, _RESOURCE_BACKED_TYPES, _STREAM_FIELD_INFO, _TEXTASSET_JSON_FORMAT_LIMIT,
    _TEXTURE_QUALITY_TO_ENCODER, _atexit_cleanup_registered, _check_cancelled, _cleanup_pending_resource_temp_files,
    _peek_gameobject_fallback_name, _register_pending_resource_temp_file, _texture_empty_reason, _truncate_name,
    default_object_name, get_row_name, get_row_script_name, resolve_graphics_format_name,
    resolve_object_name, resolve_script_name, resolve_shader_name, resolve_texture_format_name,
    row_matches_script_selector, safe_parse_dict, script_checklist_entries, script_identity_tooltip,
)
from .object_dump import (
    _BINARY_STRING_MARKER_KEY, _BYTES_MARKER_KEY, _DUMP_MAX_STRING_LEN, _EDIT_OMIT_BYTES_THRESHOLD,
    _HEX_DUMP_MAX_BYTES, _HEX_DUMP_SAMPLE_CHARS, _OMITTED_BYTES_MARKER_KEY, _OMITTED_STRING_MARKER_KEY,
    _dump_node, _format_hex_dump, _looks_binary,
    _resolve_parsed_data, _to_jsonable, _walk_structure_node, build_export_json,
    build_json_text, build_preview_json, dump_structure_text, dump_typed_text,
    format_typed_value,
)
from .object_resources import (
    ResourceReferenceIssue, _MAX_WARNING_SNIPPET_LENGTH, _display_path, _environment_load_root,
    _probe_video_file_metadata, _safe_warning_snippet, check_resource_reference, peek_videoclip_ext,
    probe_video_mismatch_warning, read_videoclip_bytes, resolve_cab_source, resolve_display_size,
)
from .object_sprite import (
    _SPRITE_PACKING_DISPLAY_TRANSPOSE, _SPRITE_PACKING_INVERSE_TRANSPOSE, _resolve_sprite_render_data, build_sprite_region_image,
    import_sprite_converted, resolve_sprite_texture,
)
from .object_export import (
    _MAX_SANITIZED_NAME_LENGTH, _WINDOWS_RESERVED_NAMES, _bare_resolved_name, _detect_textasset_extension,
    build_export_stem, export_object, prepare_dict_for_json_edit, restore_dict_from_json_edit,
    sanitize_export_filename,
)
from .object_import import (
    CONVERTED_IMPORT_SUPPORTED_TYPES, PARTIAL_PARSE_BLOCK_MESSAGE, TEXTURE_MANUAL_FORMAT_OPTIONS, _CONVERTED_IMPORT_EXTENSIONS,
    _DESKTOP_CONSOLE_PLATFORMS, _MOBILE_ONLY_FAMILIES, _TEXTURE_ARRAY_SLICE_RE, _check_converted_import_extension,
    _contains_omitted_bytes_note, _resolve_texture_import_settings, export_object_raw, import_object_converted,
    import_object_json, import_object_raw, import_texture_array_slices, partial_parse_block_reason,
    texture_format_family, texture_format_platform_warning,
)
from .object_content_raw import (
    export_object_content_raw, import_object_content_raw,
)
from .patch_matching import (
    IMPORT_MODE_ORDER, MatchedPatch, PatchFolderScan, _CONVERTED_SUFFIXES,
    _PATCH_STEM_RE, _UNRESOLVED_SCRIPT_NAME, _check_patch_identity, apply_matched_patch,
    classify_import_mode, match_patch_files, order_patches_for_apply, scan_patch_folder,
)
