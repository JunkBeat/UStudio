"""External-resource handling: display size, video probing and the resource-reference sanity check."""

from core.i18n import tr
import ntpath
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple
from UnityPy.environment import simplify_name
from UnityPy.helpers.ResourceReader import get_resource_data
from . import video_transcode as _video_transcode

from .object_common import _RESOURCE_BACKED_TYPES, _STREAM_FIELD_INFO


def _stream_path_is_empty(obj) -> bool:
    """True only when this object's `m_StreamData` is its LAST field and its `path` is empty — decided
    from the object's last 4 bytes, without parsing the object. `path` is the last member of
    StreamingInfo and a string is stored as `int32 length, characters, padding to 4`: an EMPTY path ends
    the object with its zero length, while a non-empty one ends with its last character plus at most 3
    padding bytes — so it can never end in four zero bytes. Meant for inline Meshes: m_StreamData is the
    last field of a Mesh, so even the bounded peek had to read the whole (up to 66 MB) body to reach it
    (measured: a 66 MB Mesh took 3.8 s, a dozen 10-15 MB ones ~0.6 s each, in The Mortuary Assistant).
    False = "cannot tell cheaply" (the caller then does the ordinary peek), never "not empty"."""
    try:
        node = obj._get_typetree_node()
        last = node.m_Children[-1] if node.m_Children else None
        if last is None or last.m_Name != "m_StreamData" or not last.m_Children:
            return False
        path = last.m_Children[-1]
        if path.m_Name != "path" or path.m_Type != "string":
            return False
        return obj.peek_tail(4) == b"\x00\x00\x00\x00"
    except Exception:
        return False


def resolve_display_size(obj) -> int:
    """For AudioClip/Texture2D/Texture2DArray/Mesh/VideoClip, the header byte_size
    is mostly metadata — the real payload lives in an external .resS/.resource file
    referenced by m_Resource/m_StreamData/m_ExternalResources. Returns that real
    size when the data is actually externalized (non-empty source path); falls back
    to byte_size otherwise (every other type, and these 5 types too when their data
    happens to be stored inline instead). Never raises — a wrong displayed size is
    cosmetic, not worth failing the whole load over.

    Reads only that one field via obj.peek_field() (a bounded TypeTree read, same
    technique as peek_name()) instead of a full obj.parse_as_object() — this used
    to fully parse every Texture2D/AudioClip/Mesh/... object (including large
    fields like compressed texture data or mesh vertex buffers) just to read one
    small nested field for the table's Size column, at load time, for every such
    object in the load."""
    if obj.type.name not in _RESOURCE_BACKED_TYPES:
        return obj.byte_size
    try:
        if obj.type.name == "AudioClip":
            resource = obj.peek_field(("m_Resource",))
            if resource and resource.get("m_Source"):
                return resource["m_Size"]
        elif obj.type.name == "VideoClip":
            resource = obj.peek_field(("m_ExternalResources",))
            if resource and resource.get("m_Source"):
                return resource["m_Size"]
        else:  # Texture2D, Texture2DArray, Mesh
            if _stream_path_is_empty(obj):
                return obj.byte_size  # data is inline: nothing external to measure
            stream = obj.peek_field(("m_StreamData",))
            if stream and stream.get("path"):
                return stream["size"]
    except Exception:
        pass
    return obj.byte_size


def probe_video_mismatch_warning(file_path, width: int, height: int, frame_rate: float) -> Optional[str]:
    """Best-effort pre-flight sanity check for VideoClip converted import —
    packaging is raw-bytes-only (no transcode, see ROADMAP.md's explicit
    scope), so a candidate file whose actual codec/dimensions don't match
    what the VideoClip itself declares would silently produce a broken or
    black-screen clip in-game with no error anywhere in this pipeline. Warns,
    never blocks — same non-blocking-advisory shape as
    Fsb5Encoder.verify_decodable() (see IMPORT_WARNING_PREFIX).

    Deliberately does NOT compare codec name against the object's own
    `m_Format` field: that's a Unity-internal video-format identifier with no
    verified public enum in this project (unlike TextureFormat/
    AudioCompressionFormat, both hand-verified against real fixtures) —
    guessing a codec-id-to-name mapping without a reference to check it
    against is exactly the kind of unverified binary-format assumption this
    project's own methodology says not to ship. Width/height/frame rate are
    directly interpretable with no such mapping needed, so those are what
    get compared.

    Uses this project's own vendored ffprobe (video_transcode.probe()) —
    NOT the "ffmpeg" PyPI package this function originally used, which is a
    thin subprocess wrapper with no binary of its own and depends on a
    system-installed ffprobe that isn't guaranteed (or, on the machine this
    was fixed on, even present) to exist on PATH at all."""
    info = _video_transcode.probe(file_path)
    if info is None:
        return tr("не удалось проверить файл через ffprobe.")
    video_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        return tr("в файле не найдена видеодорожка — возможно, это не видео.")
    stream = video_streams[0]
    probed_width = int(stream.get("width", 0) or 0)
    probed_height = int(stream.get("height", 0) or 0)
    probed_fps = _video_transcode._parse_rational(stream.get("r_frame_rate") or stream.get("avg_frame_rate"))

    mismatches = []
    if width and height and probed_width and probed_height and (probed_width != width or probed_height != height):
        mismatches.append(tr("размер {new} вместо {old}", new=f"{probed_width}x{probed_height}", old=f"{width}x{height}"))
    if frame_rate and probed_fps and abs(probed_fps - frame_rate) > 0.5:
        mismatches.append(tr("частота кадров {new} вместо {old}", new=f"{probed_fps:.2f}", old=f"{frame_rate:.2f}"))
    if not mismatches:
        return None
    return tr("выбранный файл отличается от исходного видео ({differences}) — размер и частота кадров объекта "
              "обновлены, но видео не перекодируется, поэтому в игре оно может не воспроизвестись.",
              differences="; ".join(mismatches))


def _probe_video_file_metadata(file_path) -> Optional[dict]:
    """Reads width/height/frame_rate/duration straight from `file_path` via
    ffprobe — used by the plain-packaging (no transcode) VideoClip import
    path so its declared Width/Height/m_FrameRate/m_FrameCount can be
    corrected to match the real file just packaged, the same "never leave
    metadata stale/wrong" principle a transcode's own re-probe of its output
    already applies (see import_object_converted's VideoClip branch below).
    Real reported concern this closes: probe_video_mismatch_warning() above
    already reads these exact values just to WARN about a mismatch — leaving
    the object's own declared fields at their old, now-confirmed-wrong values
    afterward made no sense once the real ones were already known.

    Returns None on any probe failure or missing video stream — the caller
    then simply leaves the object's existing metadata untouched, the same
    fallback this path always had before this existed."""
    info = _video_transcode.probe(file_path)
    if info is None:
        return None
    video_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        return None
    stream = video_streams[0]
    width = int(stream.get("width", 0) or 0)
    height = int(stream.get("height", 0) or 0)
    frame_rate = _video_transcode._parse_rational(stream.get("r_frame_rate") or stream.get("avg_frame_rate"))
    if not width or not height:
        return None
    try:
        duration = float(info.get("format", {}).get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return {"width": width, "height": height, "frame_rate": frame_rate, "duration": duration}


def read_videoclip_bytes(obj) -> Tuple[Optional[bytes], str, Optional[str]]:
    """Reads a VideoClip's raw external-resource bytes plus a guessed playable
    extension (from m_OriginalPath, falling back to ".mp4"). Returns (data, ext,
    skip_reason) — skip_reason is set (data is None) when there's no linked
    external resource, mirroring export_object()'s own skipped=True convention.
    Shared by export_object()'s VideoClip branch and the Preview tab's video
    playback (_type_specific_preview) so the two can never disagree about which
    bytes/extension a given VideoClip actually resolves to."""
    data = obj.parse_as_object()
    resource = getattr(data, "m_ExternalResources", None)
    if resource is None or not resource.m_Source:
        return None, "", tr("Внешний ресурс видео не найден")
    raw = get_resource_data(resource.m_Source, obj.assets_file, resource.m_Offset, resource.m_Size)
    ext = Path(data.m_OriginalPath).suffix if getattr(data, "m_OriginalPath", "") else ".mp4"
    return raw, ext, None


def peek_videoclip_ext(obj) -> str:
    """Same m_OriginalPath-derived extension read_videoclip_bytes() guesses
    for playback (falling back to ".mp4" the same way), but via a cheap
    top-level peek_field() instead of a full parse_as_object() + external-
    resource read — used by the converted-import settings dialog just to
    pre-select a matching transcode format, which needs the extension alone,
    never the actual video bytes. Returns "" on any read failure (missing
    field, parse error) — the caller falls back to CONFIG's last-remembered
    choice in that case, same as it always did before this existed."""
    try:
        value = obj.peek_field(("m_OriginalPath",))
    except Exception:
        return ""
    return Path(value).suffix if value else ".mp4"


def _environment_load_root(environment) -> str:
    """Best-effort "the folder these files were loaded from", used only to
    shorten absolute paths in check_resource_reference()'s messages.

    Environment.path (UnityPy's own field, set from CONFIG.selected_dir et al.
    by the caller) is NOT reliable for this: when a folder-mode load feeds many
    individual file paths in one by one (this app's own loader does exactly
    that), Environment.__init__ (environment.py) overwrites .path with each
    file's own dirname in turn — `self.path = ntpath.dirname(arg)` runs once
    per file — so after a real folder load it ends up as whatever the LAST
    file's directory happened to be, not the folder the user actually picked.
    Also can't just import CONFIG.selected_dir here even for the main-window
    case: config.py already imports RICH_PREVIEW_TYPES from this module, so
    importing config.py back from here would be circular — and it wouldn't
    even be the right answer for a CabBrowserDialog's own standalone
    Environment anyway, which has no CONFIG.selected_dir of its own.

    The common ancestor of every file this environment has actually
    registered is a self-computed answer that doesn't depend on how the load
    was driven or which Environment instance this is."""
    paths = [p for p in environment.files.keys() if isinstance(p, str) and os.path.isabs(p)]
    if len(paths) >= 2:
        try:
            return os.path.commonpath(paths)
        except ValueError:
            pass  # e.g. paths spanning different drives on Windows
    return getattr(environment, "path", "") or ""


def _display_path(path: str, environment) -> str:
    """Renders an absolute path relative to _environment_load_root() when
    possible. A real game install's absolute path is routinely 80+ characters
    deep, which drowns out the actual signal in a warning message meant to be
    read at a glance (which two folders differ) — see the wrong_directory case
    below, where that's the whole point of the message. Falls back to the
    original absolute path whenever a relative one can't be computed (no load
    root known, a different drive on Windows, ...) rather than guessing. The
    ResourceReferenceIssue dataclass itself still stores the raw absolute
    resolved_source — only the human-readable message text goes through this."""
    root = _environment_load_root(environment)
    if not path or not root:
        return path
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def resolve_cab_source(environment, declared_path: str, assets_file=None) -> Tuple[Any, Optional[str], Optional[str]]:
    """Resolves a declared resource path (m_Resource.m_Source / m_StreamData.path /
    m_ExternalResources.m_Source) to (reader, resolved_source, registered_name) via
    the environment's cab registry — the exact lookup get_resource_data() and
    check_resource_reference() each already did independently; factored out here so
    export_object_content_raw()/import_object_content_raw() reuse the same resolution
    instead of a third slightly-different copy.

    resolved_source is an absolute filesystem path for a loose external file, or the
    original registered name (never a real path) for a bundle-internal resource —
    check_resource_reference()'s wrong_directory check and import_object_content_raw()
    both rely on os.path.isabs() on the result to tell the two apart.

    registered_name is the RAW string environment._cab_source_names[key] actually
    holds — often the same bare name declared_path's own basename reduces to, but
    not always (see the second bug below): whatever it is, it's the one string
    Environment.register_cab() will treat as "the same source, no collision" the
    next time it's registered under. import_object_content_raw()'s reload needs this
    (not resolved_source) — see that function's own comment on the real bug this
    fixed (a live-caught reload silently discarded by cab_collision_policy).

    Real bug fixed here (caught via a live test against the Petscop fixture, not
    assumed): environment._cab_source_names[key] is NOT always already absolute even
    for a genuine loose external file — SerializedFile.load_dependencies() registers a
    dependency by its bare relative name (self.environment.load_file(file_id.path,
    ...)), and Environment.load_file() captures that bare name into `name`/stream_name
    BEFORE resolving it against self.path further down — so a resource pulled in via
    the automatic dependency mechanism (the common case for AudioClip/Texture2D/Mesh
    external data) registers under its bare basename, not a path. Without resolving it
    here, every such case would be misidentified as bundle-internal. Joining against
    environment.path and confirming the result is a real file on disk is what
    Environment.load_file() itself would have done with this same bare name.

    Second real bug fixed here (also caught via a live test, not assumed): a resource
    is only ever registered as a cab lazily, the first time something actually reads
    its bytes (get_resource_data()'s own load_dependencies() fallback). Nothing
    guarantees that's already happened by the time content-raw export/import runs —
    e.g. a user importing straight into an object they never previewed this session,
    or a batch "Import from Folder (All Objects)" over objects nobody individually
    clicked. Without attempting the same lazy load here, resolution would fail with a
    misleading "resource not found" for a resource that's perfectly loadable. Mirrors
    get_resource_data()'s own retry list (ResourceReader.py) so the two never
    disagree about what counts as a valid alternate name for the same resource."""
    basename = ntpath.basename(declared_path)
    key = simplify_name(basename)
    picked = environment.pick_cab_alternative(basename, assets_file)
    reader = picked[1] if picked is not None else environment.get_cab(basename)
    if reader is None and assets_file is not None:
        name, ext = ntpath.splitext(basename)
        possible_names = [basename, f"{name}.resource", f"{name}.assets.resS", f"{name}.resS"]
        try:
            assets_file.load_dependencies(possible_names)
        except Exception:
            pass
        for possible_name in possible_names:
            reader = environment.get_cab(possible_name)
            if reader is not None:
                key = simplify_name(possible_name)
                break

    registered_name = picked[0] if picked is not None else environment._cab_source_names.get(key)
    resolved_source = registered_name
    if resolved_source is not None and not os.path.isabs(resolved_source):
        candidate = os.path.join(environment.path, resolved_source)
        if os.path.isfile(candidate):
            resolved_source = candidate
    return reader, resolved_source, registered_name


@dataclass
class ResourceReferenceIssue:
    kind: str  # "missing" | "out_of_bounds" | "wrong_directory"
    field_name: str
    declared_path: str
    resolved_source: str
    message: str


_MAX_WARNING_SNIPPET_LENGTH = 40


def _safe_warning_snippet(text: str) -> str:
    """Bounds a string sourced from PARSED OBJECT DATA (not this app's own
    trusted code) before it's embedded into a user-facing warning message.

    Real reported bug: a resource-backed object whose m_StreamData.path field
    got misparsed (a corrupted/unusual build's TypeTree not matching this
    app's assumptions — the same general class of offset/alignment bug this
    project has hit before, producing repeating garbage rather than a real
    path) yielded a several-hundred-character string with no whitespace
    anywhere in it. Two compounding problems from that one string: (1) it
    flooded the warning banner with an unreadable wall of replacement
    characters, and (2) far worse, QLabel's word-wrap only breaks at
    whitespace — a single unbreakable "word" that long forced the WHOLE
    preview panel/splitter to grow to fit it, and it never shrank back down
    again even after selecting a normal object afterward, since nothing ever
    re-shrinks a splitter that was pushed wide by a one-time minimumSizeHint.
    Truncating before the string ever reaches a label fixes both at once,
    regardless of why the underlying data was corrupted — the fix does not
    depend on root-causing that per-object parsing bug."""
    if len(text) <= _MAX_WARNING_SNIPPET_LENGTH:
        return text
    return text[:_MAX_WARNING_SNIPPET_LENGTH] + "…"


def check_resource_reference(obj) -> Optional[ResourceReferenceIssue]:
    """Sanity-checks a resource-backed object's external stream reference
    (m_Resource/m_StreamData/m_ExternalResources) BEFORE any preview is built
    from it, to separate "this object's own data is corrupted" from "this
    object's resource reference resolved to the WRONG physical file, so what
    you're about to see is valid-looking but unrelated data". Three concrete,
    checkable red flags:

    - missing: the declared resource file was never loaded into the
      environment at all — whatever preview follows (if any) can't possibly
      be this object's real data.
    - out_of_bounds: offset+size exceeds the resolved file's actual length —
      an unambiguous sign the reference doesn't fit the file it resolved to.
    - wrong_directory: the resolved physical file lives in a DIFFERENT
      directory than the object's own SerializedFile/bundle. Standard Unity
      loose-file layout always ships a resource file alongside the .assets
      file that references it — a match from elsewhere means the resource
      name was satisfied by an unrelated "borrowed" file (the exact scenario
      this was built for — see the module docstring above this section).
      Only checked when both paths are real, absolute filesystem paths (a
      no-op for bundle-internal objects, where there's no per-directory
      ambiguity to begin with — resolution always stays within the same
      bundle's own shared stream).

    Returns None if nothing suspicious was found — this is NOT proof the data
    is correct, only that none of the above red flags fired (e.g. two
    genuinely byte-identical duplicate resource files in different folders
    would still resolve "wrong_directory" but produce correct pixels; this
    function has no way to know that, and correctly stays silent about
    out_of_bounds/missing in that case since those two are unaffected by
    which of two identical files gets picked). Never raises: this is a
    diagnostic aid, not a required step, and a failure while checking must
    never block or break an otherwise-working preview."""
    field_info = _STREAM_FIELD_INFO.get(obj.type.name)
    if field_info is None:
        return None
    struct_field, source_key, offset_key, size_key = field_info

    try:
        struct_value = obj.peek_field((struct_field,))
        if not struct_value:
            return None
        declared_path = struct_value.get(source_key) or ""
        if not declared_path:
            return None  # data stored inline — nothing external to check
        offset = int(struct_value.get(offset_key, 0) or 0)
        size = int(struct_value.get(size_key, 0) or 0)

        environment = obj.assets_file.environment
        reader, resolved_source, _registered_name = resolve_cab_source(environment, declared_path, obj.assets_file)

        if reader is None or resolved_source is None:
            return ResourceReferenceIssue(
                kind="missing", field_name=struct_field, declared_path=declared_path,
                resolved_source="", message=(
                    tr('Ресурс «{name}» не найден среди загруженных файлов — показанные ниже данные (если они вообще '
                       'получены) не связаны с реальным содержимым объекта.', name=_safe_warning_snippet(declared_path))
                ),
            )

        try:
            resolved_length = reader.Length
        except Exception:
            resolved_length = None
        if resolved_length is not None and offset + size > resolved_length:
            return ResourceReferenceIssue(
                kind="out_of_bounds", field_name=struct_field, declared_path=declared_path,
                resolved_source=resolved_source, message=(
                    tr('Некорректная ссылка на ресурс «{name}»: смещение {offset} + размер {size} выходит за пределы '
                       'файла «{file}» ({length} байт). Показанные ниже данные НЕ являются реальным содержимым объекта.',
                       name=_safe_warning_snippet(declared_path), offset=f"{offset:,}", size=f"{size:,}",
                       file=_display_path(resolved_source, environment), length=f"{resolved_length:,}")
                ),
            )

        assets_file_id = getattr(obj.assets_file, "_cache_id", None)
        if not (isinstance(assets_file_id, str) and os.path.isabs(assets_file_id)):
            # a file inside a bundle has no path of its own: the bundle's is what matters
            source_path = environment.source_path_of(obj.assets_file) if hasattr(environment, "source_path_of") else None
            if source_path and os.path.isabs(source_path):
                assets_file_id = source_path
        if isinstance(assets_file_id, str) and os.path.isabs(assets_file_id):
            expected_dir = os.path.dirname(assets_file_id)
            actual_dir = os.path.dirname(resolved_source) if isinstance(resolved_source, str) else ""
            if (
                actual_dir and os.path.isabs(actual_dir)
                and os.path.normcase(os.path.normpath(actual_dir)) != os.path.normcase(os.path.normpath(expected_dir))
            ):
                return ResourceReferenceIssue(
                    kind="wrong_directory", field_name=struct_field, declared_path=declared_path,
                    # Names both the expected and actual location directly (not
                    # a general "somewhere else" statement) — a real folder can
                    # easily contain many duplicate-named files (multiple
                    # copies/builds, backups, mod exports, ...), but this
                    # states the one specific pair actually involved in THIS
                    # object's mismatch rather than speculating about the
                    # folder's contents in general.
                    resolved_source=resolved_source, message=(
                        tr('Подозрительная ссылка на ресурс: «{name}» не найден в «{expected}» и был загружен из '
                           '«{actual}». Объект может случайно ссылаться на чужие данные. Показанные ниже данные, '
                           'скорее всего, НЕ являются реальным содержимым объекта.',
                           name=_safe_warning_snippet(declared_path), expected=_display_path(expected_dir, environment),
                           actual=_display_path(actual_dir, environment))
                    ),
                )
    except Exception:
        return None
    return None
