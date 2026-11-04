"""PyQt-free per-object metadata field extraction — the small compact one-line
summary strip shown under the preview (build_compact_summary()). Trimmed to what's
meaningfully knowable here (no FMOD live decode, no OpenGL Mesh viewer, so Mesh/
Sprite/AudioClip fields are the ones this app can actually compute)."""

import wave
from io import BytesIO
from typing import List, Tuple

from .file_utils import format_size, peek_mb_identity
from .font_cmap import find_covered_codepoints
from .object_preview import resolve_graphics_format_name, resolve_texture_format_name

Fields = List[Tuple[str, str]]
StrList = List[str]


# Core lowercase+uppercase Russian Cyrillic alphabet (excludes Ё/ё — many
# otherwise-complete Cyrillic fonts omit it, so requiring it would false-negative
# fonts that genuinely support Cyrillic text for practical purposes). Checking
# only this range (not every Unicode Cyrillic code point, which also covers
# extra letters for other Slavic/non-Slavic languages) matches what "does this
# font support Cyrillic" actually means to this project's user — kept as the
# built-in DEFAULT for the configurable check below, not hardcoded into it.
CYRILLIC_SAMPLE_RANGE = range(0x0410, 0x0450)  # А-я
DEFAULT_CHAR_COVERAGE_LABEL = "Cyrillic"
DEFAULT_CHAR_COVERAGE_CHARS = "".join(chr(c) for c in CYRILLIC_SAMPLE_RANGE)

# "Does this font support ___" is deliberately not hardcoded to Cyrillic — a real request,
# once localization was raised as a later goal, to let the user define their OWN label and
# character set (any language, any project) instead of a fixed English/Cyrillic-only check.
# Module-level, set via set_char_coverage() rather than reading CONFIG directly: this module
# (like core.sdf_resolver, its sibling consumer) is PyQt-free by convention, and config.py
# pulls in QSettings — a plain setter the app calls once at startup (and again whenever the
# setting changes) keeps that boundary intact while still making the check configurable.
_char_coverage_label = DEFAULT_CHAR_COVERAGE_LABEL
_char_coverage_chars = DEFAULT_CHAR_COVERAGE_CHARS


def set_char_coverage(label: str, chars: str) -> None:
    """Changes what "does this font support ___" checks for, app-wide, from now on. Safe to call
    mid-session (e.g. the user edits it in Settings while a game is loaded): every check reads the
    module-level values fresh each time, so the very next preview/SDF-view read already uses the
    new label/characters — nothing is baked in at load time. The one thing that DOES need an
    explicit nudge is the SDF Viewer's own per-font coverage cache (MainWindow._sdf_coverage_cache) —
    see main.py's Settings-apply handler, which clears it and re-triggers a background re-check
    right after calling this, so stale text from the old character set doesn't linger."""
    global _char_coverage_label, _char_coverage_chars
    _char_coverage_label = label.strip() or DEFAULT_CHAR_COVERAGE_LABEL
    _char_coverage_chars = chars or DEFAULT_CHAR_COVERAGE_CHARS


def char_coverage_label() -> str:
    return _char_coverage_label


def coverage_part_text() -> str:
    """The summary fragment that says a font covers the character set ("Cyrillic support"). One place builds
    it, and the GUI recognises it by this exact text to highlight it."""
    return f"{_char_coverage_label} support"


def char_coverage_codepoints() -> range:
    """The currently configured character set, as the same codepoints-iterable shape
    find_covered_codepoints() already expects (a real range for the untouched default, a
    plain set of ordinals otherwise — both are iterables of int, which is all that needs)."""
    if _char_coverage_chars == DEFAULT_CHAR_COVERAGE_CHARS:
        return CYRILLIC_SAMPLE_RANGE
    return {ord(c) for c in _char_coverage_chars}


def font_supports_cyrillic(font_data: bytes):
    """Despite the name (kept for now — see the module-level char-coverage note above for why
    this no longer means literally Cyrillic when the user has changed the setting), checks the
    font's cmap against whatever character set is currently configured.

    Returns True/False, or None if it couldn't be determined (the font
    data doesn't parse as a font at all, or has no cmap subtable in a format
    core.font_cmap decodes) — a soft-fail cousin of every other per-field
    lookup in this module, via the same _safe()-style "just omit the field"
    policy, applied by the caller.

    This used to go through fontTools' TTFont.getBestCmap() — the only use of
    fontTools anywhere in this codebase, and one that dragged a lot of
    unrelated machinery into a Nuitka build just to answer this one narrow
    question. core/font_cmap.py replaces it with a small, self-contained cmap
    parser (verified byte-for-byte against fontTools across all 340 real
    fonts on a real Windows machine, zero mismatches) — this function just
    supplies the configured sample and the 90% coverage threshold on top of
    it."""
    wanted = char_coverage_codepoints()
    try:
        covered = find_covered_codepoints(font_data, wanted)
    except Exception:
        return None
    if covered is None:
        return None
    # >=90% rather than 100%: tolerates the odd missing rarely-used letter
    # without the check swinging on a single glyph.
    return len(covered) >= len(wanted) * 0.9


def _compact_texture(data) -> StrList:
    parts = []
    try:
        parts.append(f"{data.m_Width} × {data.m_Height} px")
    except Exception:
        pass
    # Real reported bug: Texture2DArray has no m_TextureFormat field at all
    # (only Texture2D does — see UnityPy/classes/generated.py) — its own
    # format lives in m_Format, a GraphicsFormat, a DIFFERENT enum with a
    # different numbering than TextureFormat. getattr(data, "m_TextureFormat",
    # None) silently returned None for every Texture2DArray, dropping the
    # "Format: ..." part entirely rather than showing a wrong one — but still
    # a real gap, not a graceful fallback. resolve_texture_format_name() (a
    # TextureFormat lookup) must never be fed a raw GraphicsFormat value —
    # feeding GraphicsFormat 100 (RGBA_DXT5_SRGB) into it would resolve
    # against a completely different TextureFormat member by coincidence,
    # which is worse than showing nothing.
    fmt = getattr(data, "m_TextureFormat", None)
    if fmt is not None:
        parts.append(f"Format: {resolve_texture_format_name(fmt)}")
    else:
        graphics_fmt = getattr(data, "m_Format", None)
        if graphics_fmt is not None:
            parts.append(f"Format: {resolve_graphics_format_name(graphics_fmt)}")
    try:
        parts.append(data.image.mode)
    except Exception:
        pass
    return parts


def _compact_audio(data, samples=None) -> StrList:
    """samples: an already-decoded data.samples result a caller (build_preview(),
    via PreviewResult.audio_samples) computed once and wants reused. data.samples
    is a REAL audio decode (FMOD/Vorbis -> PCM), not a cheap property read — this
    used to trigger that SAME decode a second time on every single AudioClip
    selection, just to read the WAV header for this caption (measured 0.3-0.8s
    on a real 7MB clip). None by default, in which case this decodes fresh
    exactly as before."""
    parts = []
    try:
        from UnityPy.enums.Audio import AudioCompressionFormat
        raw = getattr(data, "m_CompressionFormat", None)
        if raw is not None:
            fmt = AudioCompressionFormat(raw) if not hasattr(raw, "name") else raw
            parts.append(f"Format: {fmt.name if hasattr(fmt, 'name') else fmt}")
    except Exception:
        pass
    try:
        if samples is None:
            samples = data.samples
        if samples:
            sample_name, sample_data = next(iter(samples.items()))
            if sample_name.lower().endswith(".wav"):
                with wave.open(BytesIO(sample_data), "rb") as w:
                    parts.append(f"{w.getframerate()} Hz")
                    parts.append(f"{w.getnchannels()}ch")
                    parts.append(f"{w.getsampwidth() * 8}-bit")
    except Exception:
        pass
    return parts


def _compact_sprite(data) -> StrList:
    try:
        img = data.image
        return [f"{img.width} × {img.height} px"]
    except Exception:
        return []


def _compact_mesh(data) -> StrList:
    parts = []
    try:
        parts.append(f"{data.m_VertexCount} verts")
    except Exception:
        pass
    try:
        parts.append(f"{len(data.m_SubMeshes)} submeshes")
    except Exception:
        pass
    return parts


def _compact_font(data) -> StrList:
    parts = []
    try:
        font_data = bytes(data.m_FontData) if data.m_FontData else b""
        if font_data:
            parts.append("OTF" if font_data[:4] == b"OTTO" else "TTF")
            parts.append(format_size(len(font_data), english=True))   # the metadata line stays English
    except Exception:
        font_data = b""
    try:
        if data.m_FontSize:
            parts.append(f"{data.m_FontSize}pt")
    except Exception:
        pass
    # Last, per request: the Cyrillic verdict is the most "situational" fact, so
    # it sits at the end of the metadata line rather than between size and pt.
    try:
        if font_data:
            supported = font_supports_cyrillic(font_data)
            if supported is not None:
                parts.append(coverage_part_text() if supported else "")
    except Exception:
        pass
    return parts


def _compact_video(data) -> StrList:
    parts = []
    try:
        parts.append(f"{data.Width} × {data.Height} px")
    except Exception:
        pass
    try:
        parts.append(f"{data.m_FrameRate:g} fps")
    except Exception:
        pass
    try:
        parts.append(f"{data.m_FrameCount} frames")
    except Exception:
        pass
    return parts


def _compact_monobehaviour(obj, data=None) -> StrList:
    """data: an already-parsed obj.parse_as_dict() result a caller (build_preview())
    computed once and wants reused for the TMP_FontAsset Cyrillic check below,
    instead of this function triggering its own independent full re-parse — see
    build_preview()'s own docstring for the real, measured redundant-parsing
    problem (this was the 4th of 4 separate re-reads of the same object).
    Defaults to None, in which case sdf_font_supports_cyrillic() parses fresh
    exactly as before."""
    # peek_mb_identity() is the SAME cache/resolver every other script-name
    # lookup in the app already goes through (Script column, export
    # filenames, Filters dialog) — reusing it here means an object whose
    # script was already resolved elsewhere this session costs nothing
    # further, instead of this function paying for its own independent
    # deref_parse_as_dict() full parse (previously one of four separate
    # re-reads of the same object — see build_preview()'s own docstring).
    parts = []
    identity = peek_mb_identity(obj)
    script_class = identity.class_name if identity.class_name != "Unknown" else None
    if script_class:
        parts.append(identity.namespace or "<global>")
        parts.append(script_class)
        if identity.assembly_name:
            # A real Unity m_AssemblyName already ends in ".dll" (confirmed
            # against a real fixture: "Assembly-CSharp.dll", not
            # "Assembly-CSharp") -- the previous code appended ".dll"
            # unconditionally, producing "Assembly-CSharp.dll.dll". Only
            # append it when genuinely missing.
            asm = identity.assembly_name
            parts.append(asm if asm.lower().endswith(".dll") else f"{asm}.dll")
    # TMP_FontAsset (an SDF font pack, see core/sdf_resolver.py) is the one
    # MonoBehaviour type this app has a real, verified way to answer "does it
    # support Cyrillic" for — its own m_CharacterTable already lists every
    # Unicode codepoint it has a baked SDF glyph for. Imported here (not the
    # reverse) to avoid a circular import — see sdf_resolver.py's own
    # _CYRILLIC_SAMPLE_RANGE comment.
    if script_class == "TMP_FontAsset":
        from .sdf_resolver import sdf_font_supports_cyrillic
        supported = sdf_font_supports_cyrillic(obj, data=data)
        if supported is not None:
            parts.append(coverage_part_text() if supported else "")
    return parts


_COMPACT_BUILDERS = {
    "Texture2D": _compact_texture,
    "Texture2DArray": _compact_texture,
    "AudioClip": _compact_audio,
    "Sprite": _compact_sprite,
    "Mesh": _compact_mesh,
    "Font": _compact_font,
    "VideoClip": _compact_video,
}


# What build_compact_summary() puts between its parts. Also what the preview's metadata bar
# (gui_widgets.CompactSummaryBar) splits on to lay the parts out itself, so the two stay in step.
COMPACT_SEPARATOR = "   ·   "


def build_compact_summary(obj, data=None, audio_samples=None) -> str:
    """A single short, English line of the most preview-relevant facts about obj —
    e.g. "128 × 128 px  ·  Format: DXT5  ·  RGBA" for a texture — meant to sit in a
    slim strip directly under the preview widget (see UABEA's own texture preview
    for the layout this is modeled after — dimensions/zoom/format in one row below
    the image, not a whole separate side panel). English and terse by design: this
    is a glanceable caption.

    data: an already-parsed result a caller (build_preview()) computed once and
    wants reused instead of this independently re-parsing — for MonoBehaviour,
    obj.parse_as_dict() (threaded to _compact_monobehaviour(), see its own
    docstring); for Texture2D/Texture2DArray/AudioClip specifically,
    obj.parse_as_object() (see PreviewResult.parsed_object's own docstring for
    why only these three — the others were measured and found cheap enough not
    to need this). audio_samples: AudioClip's own already-decoded data.samples
    (a REAL FMOD/Vorbis decode, not a cheap read — see _compact_audio()'s own
    docstring for the real, measured cost this closes). Both None by default,
    in which case every type parses/decodes fresh exactly as before."""
    type_name = obj.type.name
    if type_name == "MonoBehaviour":
        parts = _compact_monobehaviour(obj, data=data)
    else:
        builder = _COMPACT_BUILDERS.get(type_name)
        parts = []
        if builder is not None:
            try:
                parsed = data if data is not None else obj.parse_as_object()
                if type_name == "AudioClip":
                    parts = builder(parsed, samples=audio_samples)
                else:
                    parts = builder(parsed)
            except Exception:
                parts = []
    return COMPACT_SEPARATOR.join(p for p in parts if p)
