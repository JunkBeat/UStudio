"""Adding new characters to an existing TMP_FontAsset SDF atlas — the
msdf-atlas-gen subprocess wrapper, the verified unit-conversion formula, atlas
compositing, and TypeTree table write-back.

PyQt-free (same layer as core/sdf_resolver.py, core/object_preview.py) so
this is usable from a CLI front end, not just the GUI dialog — see
cli/commands.py's own "sdf-add" command.

SDF-only, deliberately — msdf-atlas-gen's `-type sdf` (single-channel), never
`msdf`. Every real font asset examined while building this feature uses
classic single-channel SDFAA, never true multi-channel MSDF, and stock TMP's
own shipped shaders have no multi-channel decode path at all (confirmed
against a decompiled runtime DLL, the package's own bundled shader source,
and a real engine shader from two real games — see the project's own SDF
research notes). Writing MSDF pixel data into one of these atlases would
render as broken/undecoded noise under the existing Material. True MSDF
support needs a custom shader — a separate, larger, not-yet-started piece of
work; nothing here should be pointed at `-type msdf` until that exists.

Unit-conversion formula (derived and cross-checked against real font assets
from three independent real games spanning both the modern engine-integrated
schema and the older package-era schema):

    m_HorizontalAdvance    = advance_em                     * pointSize
    m_HorizontalBearingX   = planeBounds.left_em             * pointSize + pxrange/2
    m_HorizontalBearingY   = planeBounds.top_em               * pointSize - pxrange/2
    m_Width                = (planeBounds.right - left)_em    * pointSize - pxrange
    m_Height               = (planeBounds.top - bottom)_em    * pointSize - pxrange

`m_GlyphRect` is the glyph's TIGHT box — the same region m_Width/m_Height
describe — NOT msdf-atlas-gen's `atlasBounds` (which is that box plus pxrange/2
of SDF spread on every side). TMP builds the quad from the metrics box and the
UVs from m_GlyphRect, both extended by the same material-dependent padding
(TMP_Text.SaveGlyphVertexInfo), so the two must be the same region at 1:1 scale;
every real font asset checked has glyphRect.width == metrics.width. See
_tight_glyph_geometry(). Y-origin convention (bottom-left, Y increasing upward)
matches TMP's `m_GlyphRect` exactly, so no Y-flip is needed.

`pxrange` should always be read from the target atlas's own Material
`_GradientScale` (not guessed), so a newly-added glyph's edge softness
matches its neighbors — see resolve_gradient_scale().
"""

from __future__ import annotations

from core.i18n import N_, tr
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from PIL import Image

import UnityPy.resources.msdf_atlas_gen  # noqa: F401 — see UnityPy/helpers/Fsb5Encoder.py's own
# comment for why this otherwise-pointless import is required: Nuitka's
# package-config DLL/data bundling only fires for a resource submodule its
# own import-graph discovery has already found, which a YAML-only reference
# (cli_onefile_dlls.nuitka-package.config.yml) never triggers by itself.

from .font_cmap import find_covered_codepoints
from .sdf_resolver import resolve_sdf_components

_RESOURCE_DIR = Path(__file__).resolve().parent.parent / "UnityPy" / "resources" / "msdf_atlas_gen"
_EXE_NAME = "msdf-atlas-gen.exe"

# The same power-of-two progression TMP's own Font Asset Creator offers in its
# "Atlas Resolution" dropdown (8 through 8192) — not an arbitrary growth
# factor. When an atlas runs out of free space for a new glyph, the next
# value in this list bigger than the current size is what a user manually
# re-baking that font in the Unity Editor would pick too.
_STANDARD_ATLAS_SIZES = (8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192)

# Empty (distance-field 0) gutter, in texels, kept free on every side of each glyph's
# padded box — msdf-atlas-gen packs boxes edge to edge otherwise. TMP does not sample
# only the glyph's own box: it extends the UV window by `padding` texels
# (TMP_Text.SaveGlyphVertexInfo), where padding = 1.25 + (face-dilate + outline +
# softness) * ScaleRatioA * _GradientScale (ShaderUtilities.GetPadding). Whenever that
# exceeds the baked margin of pxrange/2 — always at small sharpness, and for outlined
# materials — the window reaches into the NEIGHBOURING glyph and draws a thin strip of
# it beside the letter (the thin vertical/horizontal "streaks"). Two texels absorbs the
# 1.25 base plus the bilinear footprint; real TMP atlases keep the same kind of gutter
# (their glyph padding). Not part of atlasBounds/planeBounds, so it does not enter the
# glyph metrics or m_GlyphRect at all.
_GLYPH_GUTTER_PX = 2

# msdf-atlas-gen's own default SDF distance range, used only when the target
# atlas's Material has no readable _GradientScale at all (a malformed/unusual
# font asset) — real fonts should always hit resolve_gradient_scale()'s real
# path instead.
_FALLBACK_PXRANGE = 4.0


class SDFGenerationError(RuntimeError):
    pass


class SDFAtlasTooSmallError(SDFGenerationError):
    """msdf-atlas-gen was given a FIXED atlas size (-dimensions) and the
    requested characters don't fit it at the requested point size — an
    expected, user-fixable outcome (bigger atlas / smaller size / fewer
    characters), not a tool failure. unfit/total are msdf-atlas-gen's own
    "Could not fit N out of M glyphs" numbers."""

    def __init__(self, message: str, unfit: int, total: int):
        super().__init__(message)
        self.unfit = unfit
        self.total = total


def msdf_atlas_gen_path() -> Path:
    path = _RESOURCE_DIR / _EXE_NAME
    if not path.exists():
        raise SDFGenerationError(tr("msdf-atlas-gen.exe не найден: {path}", path=path))
    return path


# Reason stamped on every character of a run that failed as a whole — the real
# cause lives once in AddCharactersResult.run_error (see there).
_RUN_FAILED_REASON = N_("не сгенерирован: ошибка генерации")
# How many code points a grouped "Пропущено N: ..." summary line spells out.
_MAX_LISTED_CODEPOINTS = 8


@dataclass
class NewCharacterResult:
    codepoint: int
    added: bool
    reason: str = ""  # set when added=False (already present / not in font / no atlas space)


@dataclass
class AddCharactersResult:
    font_name: str
    requested: List[int]
    results: List[NewCharacterResult] = field(default_factory=list)
    old_atlas_size: Optional[Tuple[int, int]] = None
    new_atlas_size: Optional[Tuple[int, int]] = None
    # Set only when add_characters_to_font_asset() is called with
    # auto_commit=False (the dialog's Generate-then-Save/Cancel workflow —
    # see that parameter's own docstring) and at least one character was
    # actually added. The new, not-yet-written atlas — for on-screen preview
    # before the user decides whether to keep it.
    atlas_preview_image: Optional["Image.Image"] = None
    # A closure that performs the actual patch()-and-persist step, deferred
    # until the caller explicitly wants it (the dialog's "Сохранить" button).
    # None when auto_commit=True (the commit already happened, matching every
    # existing caller's behavior) or when nothing was actually added (nothing
    # to commit either way).
    commit: Optional[Callable[[], None]] = None
    # Set when the generation run as a WHOLE failed (msdf-atlas-gen refused the
    # request — most commonly "the characters don't fit the fixed atlas"), as
    # opposed to individual characters being skipped for their own reasons. It
    # used to be recorded as one identical per-character skip for EVERY
    # requested character, each carrying the tool's full raw output — 182
    # copies of the same paragraph in the log, and a CLI that reported it as
    # "already present/unavailable". One cause is now stated once here; the
    # per-character results are still appended (so counts stay consistent) but
    # carry _RUN_FAILED_REASON, which summary_text() leaves out.
    run_error: str = ""
    # Plain-language remarks about decisions made for the caller (what "fit to texture"
    # chose, how the original height was matched, or why it could not be).
    notes: List[str] = field(default_factory=list)

    @property
    def added_count(self) -> int:
        return sum(1 for r in self.results if r.added)

    @property
    def atlas_resized(self) -> bool:
        return self.new_atlas_size is not None and self.new_atlas_size != self.old_atlas_size

    def summary_text(self) -> str:
        lines = [tr("«{font_name}»: сгенерировано {added_count} из {count} символов.", font_name=self.font_name, added_count=self.added_count, count=len(self.requested))]
        if self.atlas_resized:
            ow, oh = self.old_atlas_size
            nw, nh = self.new_atlas_size
            # Direction-aware wording — real bug found once "Полная замена"
            # started auto-fitting the atlas to the requested character set
            # instead of always reusing the font asset's old dimensions (see
            # MODE_REPLACE_ALL's own handling in _add_characters_*_schema):
            # the atlas can now genuinely SHRINK (a full rebuild with a small
            # character set no longer keeps whatever much larger atlas the
            # font used to have), not just grow the way plain "add"'s own
            # atlas-growth-on-demand always did before. A hardcoded
            # "увеличен" ("enlarged") would be factually wrong for that case.
            old_area, new_area = ow * oh, nw * nh
            sizes = dict(ow=ow, oh=oh, nw=nw, nh=nh)
            if new_area > old_area:
                lines.append("  " + tr("Атлас увеличен: {ow}×{oh} → {nw}×{nh}.", **sizes))
            elif new_area < old_area:
                lines.append("  " + tr("Атлас уменьшен: {ow}×{oh} → {nw}×{nh}.", **sizes))
            else:
                lines.append("  " + tr("Атлас изменён: {ow}×{oh} → {nw}×{nh}.", **sizes))
        if self.run_error:
            lines.append("  " + tr("Ошибка генерации: {run_error}", run_error=self.run_error))
        lines.extend(f"  {note}" for note in self.notes)
        # Group identical reasons: 30 characters that are all "уже есть в этом
        # SDF" (or a whole failed run) used to be 30 near-identical lines that
        # buried everything else. A reason that applies to a single character
        # keeps the original one-line form.
        by_reason: dict = {}
        for r in self.results:
            if not r.added and r.reason != _RUN_FAILED_REASON:
                by_reason.setdefault(r.reason, []).append(r.codepoint)
        for reason, codepoints in by_reason.items():
            if len(codepoints) == 1:
                lines.append("  " + tr("U+{code:04X}: пропущен — {reason}", code=codepoints[0], reason=reason))
                continue
            shown = ", ".join(f"U+{cp:04X}" for cp in codepoints[:_MAX_LISTED_CODEPOINTS])
            more = (" " + tr("и ещё {count}", count=len(codepoints) - _MAX_LISTED_CODEPOINTS)
                    if len(codepoints) > _MAX_LISTED_CODEPOINTS else "")
            lines.append("  " + tr("Пропущено {count}: {shown}{more} — {reason}", count=len(codepoints), shown=shown,
                                   more=more, reason=reason))
        return "\n".join(lines)


def is_legacy_schema(full: dict) -> bool:
    """The exact schema dispatch add_characters_to_font_asset() already used
    (below) — factored out so anything ELSE needing to know "which schema is
    this" (currently: resolve_current_point_size(), and the settings dialog's
    own "Match original" display) asks the same, single-source-of-truth
    question instead of re-deriving it."""
    return "m_glyphInfoList" in full and "m_GlyphTable" not in full


def resolve_current_point_size(full: dict) -> Optional[float]:
    """The font asset's OWN current point size — read from whichever field
    its ACTUAL schema uses, not a field-A-then-field-B fallback chain.
    Real, confirmed trap this avoids (checked across Truck-kun, Deep Sleep,
    and Petscop — not guessed): a MODERN-schema asset (m_GlyphTable present)
    keeps a vestigial m_fontInfo dict alongside its real m_FaceInfo one, and
    m_fontInfo.PointSize on it is near-always 0.0 (confirmed: 4/4 sampled
    Truck-kun fonts, 10/12 sampled Deep Sleep fonts) — silently falling back
    to it if m_FaceInfo ever came back empty would produce a confidently
    wrong zero, not an honest "unknown". A LEGACY-schema asset (Petscop-style,
    pre-1.4.0 TMP package) has no m_FaceInfo at all and must read
    m_fontInfo.PointSize instead — confirmed real, non-zero values there
    (16/64/86 across 4 sampled Petscop fonts).

    Returns None (not 0) when the correct-for-this-schema field is itself
    missing or falsy — a real, if uncommon, case: TMP auto-creates a
    "- Fallback" companion font asset per font whether or not the game ever
    renders through it, and that companion can be entirely unbaked (see
    add_characters_to_font_asset()'s own "genuinely degenerate atlas
    Texture2D" handling for the same underlying phenomenon)."""
    if is_legacy_schema(full):
        value = (full.get("m_fontInfo") or {}).get("PointSize")
    else:
        value = (full.get("m_FaceInfo") or {}).get("m_PointSize")
    return float(value) if value else None


def resolve_gradient_scale(material_obj) -> float:
    """Reads the target atlas's own Material `_GradientScale` — the real
    convention every neighboring glyph on that atlas was already generated
    against (confirmed: `_GradientScale == atlasPadding + 1` on every real
    font asset checked). Falls back to a fixed default only when the
    Material can't be read at all, which should not happen for any real,
    already-working font asset."""
    if material_obj is None:
        return _FALLBACK_PXRANGE
    try:
        data = material_obj.parse_as_dict()
        floats = data["m_SavedProperties"]["m_Floats"]
        for name, value in floats:
            if name == "_GradientScale":
                return float(value)
    except Exception:
        pass
    return _FALLBACK_PXRANGE


# Real sfnt version tags (TrueType/OpenType-CFF/legacy Apple/PostScript-in-
# sfnt-wrapper/TrueType Collection) — confirmed against the actual spec
# (OpenType "sfnt" table directory, offset 0). Any font file msdf-atlas-gen
# (via FreeType) can actually load starts with one of these; a file that
# doesn't is not a font at all, regardless of its extension.
_SFNT_SIGNATURES = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"ttcf")


def _looks_like_font_file(font_bytes: bytes) -> bool:
    return font_bytes[:4] in _SFNT_SIGNATURES


def _existing_codepoints(font_dict: dict) -> set:
    table = font_dict.get("m_CharacterTable") or []
    codepoints = {c["m_Unicode"] for c in table if isinstance(c, dict) and "m_Unicode" in c}
    if codepoints:
        return codepoints
    legacy = font_dict.get("m_glyphInfoList") or []
    return {c["id"] for c in legacy if isinstance(c, dict) and "id" in c}


def _charset_arg(codepoints: Sequence[int]) -> str:
    # msdf-atlas-gen's own charset syntax: comma/whitespace-separated entries,
    # a bare decimal number per single codepoint is valid on its own (no
    # quoting needed) — see -help's own "Character set specification syntax".
    return ",".join(str(cp) for cp in codepoints)


# msdf-atlas-gen's own wording when a fixed -dimensions atlas is too small
# (exit code nonzero, no JSON): "Error: Could not fit N out of M glyphs into the atlas."
_RE_COULD_NOT_FIT = re.compile(r"Could not fit (\d+) out of (\d+) glyphs")


def _run_msdf_atlas_gen(font_path: str, codepoints: Sequence[int], point_size: float, pxrange: float,
                         workdir: Path, atlas_dimensions: Optional[Tuple[int, int]] = None) -> Tuple[dict, Path]:
    """atlas_dimensions=None (default) lets msdf-atlas-gen pick the tightest
    power-of-two fit itself (-pots) — the atlas-auto-fit behavior. Given a
    (width, height) pair instead (-dimensions W H, fixed size), msdf-atlas-gen
    fails cleanly (nonzero exit, no JSON, "Error: Could not fit N out of M
    glyphs into the atlas.") if the requested character set doesn't fit —
    empirically verified, and already handled below like any other
    msdf-atlas-gen failure, no special-casing needed here."""
    exe = msdf_atlas_gen_path()
    json_path = workdir / "atlas.json"
    png_path = workdir / "atlas.png"
    cmd = [
        str(exe),
        "-font", font_path,
        "-chars", _charset_arg(codepoints),
        "-type", "sdf",
        "-size", str(point_size),
        "-pxrange", str(pxrange),
        # Snaps every glyph's origin to the texel grid. Without it the glyph lands
        # at an arbitrary sub-texel offset inside its box, so the straight edges
        # of a pixel/retro font can fall exactly on texel CENTRES — where the
        # distance is 0, i.e. the field reads 0.5 across the whole stroke. That is
        # a flat "half-transparent" plateau which TMP's shader turns into grey
        # blocks / streaks around the letters (confirmed on TinyUnicode: the
        # plateaus vanish with this flag). It changes nothing else: planeBounds
        # and atlasBounds in the JSON already account for the snap, and
        # _tight_glyph_geometry() derives the metrics from those, so on-screen
        # glyph placement is unchanged for ordinary vector fonts.
        "-pxalign", "on",
        "-outerpxpadding", str(_GLYPH_GUTTER_PX),
    ]
    if atlas_dimensions is not None:
        cmd += ["-dimensions", str(atlas_dimensions[0]), str(atlas_dimensions[1])]
    else:
        cmd += ["-pots"]
    cmd += [
        "-imageout", str(png_path),
        "-json", str(json_path),
        "-format", "png",
    ]
    # CREATE_NO_WINDOW: without it the tool opens (and flashes) its own black console window per call.
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0 or not json_path.exists():
        if atlas_dimensions is not None:
            # Real reported report: this whole-run outcome used to surface as the
            # tool's raw output pasted verbatim (its own "Loaded geometry of N
            # out of N glyphs." progress line and an English "Error: Could not
            # fit ..." line) — see AddCharactersResult.run_error/summary_text().
            # Naming the atlas size, point size and range that were actually
            # used, and the ways out, is what makes it actionable.
            m = _RE_COULD_NOT_FIT.search(f"{proc.stdout}\n{proc.stderr}")
            if m:
                unfit, total = int(m.group(1)), int(m.group(2))
                raise SDFAtlasTooSmallError(
                    tr("В атлас {value}×{value2} не помещается {unfit} из {total} символов при размере шрифта "
                       "{point_size:g} pt. Выберите «Автоподбор» в поле «Размер шрифта», уменьшите размер, увеличьте "
                       "атлас или сократите набор символов.", value=atlas_dimensions[0], value2=atlas_dimensions[1], unfit=unfit, total=total, point_size=point_size),
                    unfit, total,
                )
        raise SDFGenerationError(tr("msdf-atlas-gen завершился с ошибкой: {stdout}\n{stderr}", stdout=proc.stdout, stderr=proc.stderr))
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    if not data.get("glyphs"):
        raise SDFGenerationError(tr("msdf-atlas-gen не сгенерировал ни одного глифа (шрифт не поддерживает запрошенные символы?)"))
    return data, png_path


# Matches the GUI's own point-size spin box ceiling (_SizeOverrideGroup's
# spin_range in dialogs/sdf_generator_dialog.py) — reusing the same already-
# agreed "large enough for any real font asset" ceiling rather than picking
# a second, independent number.
_MAX_AUTO_POINT_SIZE = 4096
_MIN_AUTO_POINT_SIZE = 1


def _probe_fits(font_file_path: str, codepoints: Sequence[int], size: float, pxrange: float,
                atlas_w: int, atlas_h: int) -> bool:
    """One REAL msdf-atlas-gen run against a fixed atlas: did everything fit? (Not an estimate —
    the same -dimensions outcome the real generation call relies on, so the two cannot disagree.)"""
    with tempfile.TemporaryDirectory(prefix="ustudio_sdf_probe_") as tmp:
        try:
            _run_msdf_atlas_gen(
                font_file_path, codepoints, float(size), pxrange, Path(tmp), atlas_dimensions=(atlas_w, atlas_h),
            )
            return True
        except SDFGenerationError:
            return False


def _largest_fitting_size(font_file_path: str, codepoints: Sequence[int], pxrange: float,
                          atlas_w: int, atlas_h: int, lo: int) -> float:
    """Binary search over INTEGER point sizes for the largest one that still fits, given that `lo`
    itself is already known to fit. Integer-only: msdf-atlas-gen builds SDFs from the raw outlines and
    ignores hinting/pixel-grid snapping, so there is no extractable finer "safe increment" — integer
    points is the universal convention (confirmed with the user)."""
    hi = _MAX_AUTO_POINT_SIZE
    if lo >= hi:
        return float(lo)
    if _probe_fits(font_file_path, codepoints, hi, pxrange, atlas_w, atlas_h):
        return float(hi)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _probe_fits(font_file_path, codepoints, mid, pxrange, atlas_w, atlas_h):
            lo = mid
        else:
            hi = mid - 1
    return float(lo)


def _find_max_point_size_for_atlas(
    font_file_path: str, codepoints: Sequence[int], pxrange: float, atlas_w: int, atlas_h: int,
) -> float:
    """The largest integer point size whose msdf-atlas-gen output still fits a FIXED atlas_w x atlas_h
    (-dimensions). Raises SDFGenerationError if not even _MIN_AUTO_POINT_SIZE fits — a genuinely
    too-small atlas for this character count, surfaced as one clear message up front."""
    if not _probe_fits(font_file_path, codepoints, _MIN_AUTO_POINT_SIZE, pxrange, atlas_w, atlas_h):
        raise SDFGenerationError(
            tr("Даже при минимальном размере шрифта ({min_auto_point_size} pt) запрошенные символы не "
               "помещаются в атлас {atlas_w}×{atlas_h} — увеличьте размер атласа или уменьшите набор символов.", min_auto_point_size=_MIN_AUTO_POINT_SIZE, atlas_w=atlas_w, atlas_h=atlas_h)
        )
    return _largest_fitting_size(font_file_path, codepoints, pxrange, atlas_w, atlas_h, _MIN_AUTO_POINT_SIZE)


def _snap_atlas_size(value: int) -> int:
    for size in _STANDARD_ATLAS_SIZES:
        if size >= value:
            return size
    return _STANDARD_ATLAS_SIZES[-1]


# Used when the font asset's own atlas is missing/degenerate (an unbaked "- Fallback" companion has a
# 0x0 texture) and as the floor when its original point size is unknown.
_FIT_DEFAULT_ATLAS = 512
_FIT_DEFAULT_FLOOR = 32


def _fit_to_texture(
    font_file_path: str, codepoints: Sequence[int], pxrange: float, atlas_w: int, atlas_h: int, floor: float,
) -> Tuple[float, Tuple[int, int]]:
    """"Fit to the current texture": the largest integer size that fits the font asset's CURRENT atlas
    size — but never smaller than `floor` (the font's original size). If the characters do not fit at
    the floor, the atlas grows to the next power of two (smaller axis first, up to 8192, TMP's largest)
    until they do, instead of shrinking the glyphs into something unusably small. Returns
    (size, (atlas_w, atlas_h)); the caller bakes into exactly that atlas. Only if even the largest
    atlas cannot hold the set at the floor does it fall back to the best size for that largest atlas
    (raising SDFGenerationError if not even 1 pt fits)."""
    if atlas_w < 32 or atlas_h < 32:
        atlas_w = atlas_h = _FIT_DEFAULT_ATLAS
    w, h = _snap_atlas_size(atlas_w), _snap_atlas_size(atlas_h)
    floor_size = min(_MAX_AUTO_POINT_SIZE, max(_MIN_AUTO_POINT_SIZE, int(round(floor or _FIT_DEFAULT_FLOOR))))
    while True:
        if _probe_fits(font_file_path, codepoints, floor_size, pxrange, w, h):
            return _largest_fitting_size(font_file_path, codepoints, pxrange, w, h, floor_size), (w, h)
        next_w, next_h = _next_atlas_size(w), _next_atlas_size(h)
        if next_w is None and next_h is None:
            break
        if next_w is not None and (next_h is None or w <= h):
            w = next_w
        else:
            h = next_h
    return _find_max_point_size_for_atlas(font_file_path, codepoints, pxrange, w, h), (w, h)


def _original_glyph_em_heights(full: dict, legacy: bool) -> dict:
    """codepoint -> tight glyph height in em units (height / point size) of the font asset AS IT IS
    NOW — read before a full replacement throws its glyphs away. Empty when it has none."""
    out: dict = {}
    if legacy:
        pt = float((full.get("m_fontInfo") or {}).get("PointSize") or 0)
        if pt <= 0:
            return out
        for g in full.get("m_glyphInfoList") or []:
            if isinstance(g, dict) and "id" in g and (g.get("height") or 0) > 0:
                out[g["id"]] = g["height"] / pt
        return out
    pt = float((full.get("m_FaceInfo") or {}).get("m_PointSize") or 0)
    if pt <= 0:
        return out
    heights = {}
    for g in full.get("m_GlyphTable") or []:
        height = (g.get("m_Metrics") or {}).get("m_Height") or 0
        if "m_Index" in g and height > 0:
            heights[g["m_Index"]] = height
    for c in full.get("m_CharacterTable") or []:
        height = heights.get(c.get("m_GlyphIndex"))
        if height and "m_Unicode" in c:
            out.setdefault(c["m_Unicode"], height / pt)
    return out


def _original_vertical_layout(full: dict, legacy: bool) -> Optional[dict]:
    """The font asset's CURRENT line box as fractions of its point size: {"asc", "desc", "line"}
    (ascent line, descent line — negative — and line height). None if any of it is missing."""
    if legacy:
        info = full.get("m_fontInfo") or {}
        pt = float(info.get("PointSize") or 0)
        asc, desc, line = info.get("Ascender"), info.get("Descender"), info.get("LineHeight")
    else:
        info = full.get("m_FaceInfo") or {}
        pt = float(info.get("m_PointSize") or 0)
        asc, desc, line = info.get("m_AscentLine"), info.get("m_DescentLine"), info.get("m_LineHeight")
    if pt <= 0 or asc is None or desc is None or line is None:
        return None
    return {"asc": asc / pt, "desc": desc / pt, "line": line / pt}


def _zero_bold_spacing(full: dict, declared: Optional[float], result: "AddCharactersResult") -> None:
    """Part of "match the original height" (full replacement): switch off the asset's extra BOLD spacing.

    TMP adds `boldSpacing` (7 = 7 % of the font size) to the advance of EVERY bold character
    (TMP_Text: `num27 = m_currentFontAsset.boldSpacing`, then `(normalSpacingOffset + ... +
    boldSpacingAdjustment) * emScale` per character), to make room for the thickened glyphs of a
    proportional font. A pixel font does not thicken in any useful way, but its lines still grow by
    ~2.5 px per character (~90 px on a 37-character line at 35 px text), so a bold — typically the
    hovered/selected — UI string becomes wider than the original was and wraps. Measured on ROUNDS with
    TinyUnicode. Same top-level field in the modern and the legacy TMP_FontAsset schema."""
    if declared is None or not full.get("boldSpacing"):
        return
    full["boldSpacing"] = 0.0
    result.notes.append(
        tr("Дополнительный интервал полужирного текста отключён.")
    )


def _resolve_declared_point_size(
    match: bool, orig_em: dict, atlas_json: dict, baked: float, pxrange: float, result: "AddCharactersResult",
) -> Optional[float]:
    """"Match the original glyph height" (full replacement only). Returns the point size to DECLARE in
    the font asset (None = declare the bake size, i.e. no matching).

    On-screen glyph height is glyph_em_height x fontSize whatever size was baked at, because TMP scales
    every glyph by fontSize / m_PointSize and a full replacement stores the bake size there. So a font
    whose glyphs are small relative to its em (a pixel font) next to a tall original comes out smaller on
    screen, and no bake size fixes that. What does: declaring m_PointSize smaller than the bake size by
    the ratio of the two fonts' glyph heights — TMP then scales the WHOLE asset (glyphs and line
    metrics) up together, and the 1:1 texel:metric relationship the shader relies on is untouched
    (scaling the metrics instead would break it).

    Together with this the ORIGINAL line box (ascent line, descent line, line height — see
    _original_vertical_layout) is kept in on-screen terms. TMP places text vertically from the asset's
    ascent/descent lines, not from the letters' real shape (TMP_Text: the per-character ascender is
    `faceInfo.ascentLine`, the glyph baseline is 0 — `faceInfo.baseline` is not used — and "Middle"
    alignment centres (maxAscender + maxDescender)). A pixel font's own hhea lines put its capitals
    well below the centre the original had (measured on ROUNDS: -0.215 em against +0.014 em, about
    8 px at 35 px text); reusing the original's lines puts the baseline exactly where the original
    had it for Top, Middle and Bottom alignment alike, and keeps multi-line spacing. The ratio is the median, over the characters both
    fonts have (letters and digits when there are at least three), of original height / new height."""
    if not match:
        return None
    new_em = {}
    for g in atlas_json.get("glyphs") or []:
        cp = g.get("unicode")
        if cp is None or "planeBounds" not in g or "atlasBounds" not in g:
            continue
        # The height that will actually be WRITTEN (pixel-snapped, see _tight_glyph_geometry) — matching the
        # unsnapped outline height instead leaves a pixel font's glyphs up to a texel taller than intended.
        _rect, metrics = _tight_glyph_geometry(g, baked, pxrange)
        if metrics["m_Height"] > 0:
            new_em[cp] = metrics["m_Height"] / baked
    common = [cp for cp in new_em if cp in orig_em]
    letters = [cp for cp in common if chr(cp).isalnum()]
    use = letters if len(letters) >= 3 else common
    if not use:
        result.notes.append(
            tr("Высота букв не подогнана под оригинал: в прежнем шрифте нет символов, общих с новым набором.")
        )
        return None
    ratios = sorted(orig_em[cp] / new_em[cp] for cp in use)
    mid = len(ratios) // 2
    ratio = ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2
    declared = baked / ratio
    result.notes.append(
        tr("Высота букв подогнана под оригинал (по {count} общим символам): в ассете записан размер "
           "{declared:.0f} pt при запекании {baked:g} pt.", count=len(use), declared=declared, baked=baked)
    )
    return declared


def _derive_metrics(glyph_entry: dict, point_size: float, pxrange: float) -> dict:
    pb = glyph_entry["planeBounds"]
    return {
        "m_Width": (pb["right"] - pb["left"]) * point_size - pxrange,
        "m_Height": (pb["top"] - pb["bottom"]) * point_size - pxrange,
        "m_HorizontalBearingX": pb["left"] * point_size + pxrange / 2,
        "m_HorizontalBearingY": pb["top"] * point_size - pxrange / 2,
        "m_HorizontalAdvance": glyph_entry["advance"] * point_size,
    }


def _crop_padded_bitmap(atlas_png: Path, glyph_entry: dict) -> Image.Image:
    """The glyph's own padded (spread-inclusive) bitmap, repacked from
    msdf-atlas-gen's plain-grayscale `sdf` PNG convention (R=G=B=distance,
    alpha fixed at 255) into the alpha-channel convention TMP's own atlas
    textures actually use (confirmed against a real Alpha8-decoded atlas:
    R=G=B=0, the real distance value lives in Alpha) — pasting the raw
    grayscale image in directly would put the data in the wrong channel
    entirely and silently produce a flat, undecoded result.

    Opens the source PNG in a `with` block, not a bare `Image.open()` — a
    real bug, caught via a real generation run: this function is called once
    per new character, all against the SAME shared `atlas_png` path (one
    msdf-atlas-gen invocation batches every requested glyph into one output
    file). PIL's `Image.open()` keeps its file handle open until explicitly
    closed, and `Image.merge()` doesn't need that to happen automatically —
    it copies pixel data into a new image but never closes its inputs. Across
    a batch of several new characters this accumulated one open handle per
    character on the same file, and Windows (unlike POSIX) refuses to delete
    a file — or the temp directory containing it — while any handle to it is
    still open, surfacing as `WinError 32` when the caller's
    `TemporaryDirectory` context tried to clean up afterward."""
    with Image.open(atlas_png) as raw:
        if raw.mode != "L":
            raise SDFGenerationError(tr("неожиданный формат PNG от msdf-atlas-gen: {mode}", mode=raw.mode))
        left, upper, padded_w, padded_h = _padded_crop_box(glyph_entry, raw.height)
        zeros = Image.new("L", raw.size, 0)
        repacked = Image.merge("RGBA", (zeros, zeros, zeros, raw))
        return repacked.crop((left, upper, left + padded_w, upper + padded_h))


def _padded_crop_box(glyph_entry: dict, atlas_png_height: int) -> Tuple[int, int, int, int]:
    """(left, upper, width, height) of a glyph's padded box inside msdf-atlas-gen's
    own PNG, in PIL's top-down pixel coordinates — the ONE place this rounding
    lives, shared by _crop_padded_bitmap() (which crops it) and the packing path
    (which needs the same origin to work out where the glyph's tight box ended up
    after being pasted elsewhere).

    Derives width/height first and the far edges from them, rather than rounding
    both edges independently — atlasBounds are half-integer pixel coordinates,
    and Python's round-half-to-even can give the two edges of one box different
    rounding parity if rounded separately."""
    ab = glyph_entry["atlasBounds"]
    padded_w = round(ab["right"] - ab["left"])
    padded_h = round(ab["top"] - ab["bottom"])
    left = int(round(ab["left"]))
    upper = int(round(atlas_png_height - ab["top"]))
    return left, upper, padded_w, padded_h


def _tight_glyph_geometry(glyph_entry: dict, point_size: float, pxrange: float,
                          offset_x: float = 0.0, offset_y: float = 0.0) -> Tuple[dict, dict]:
    """The glyph's TIGHT box as TMP wants it: `(m_GlyphRect, m_Metrics)`.

    TMP treats m_GlyphRect as exactly the region m_Metrics describes (width x
    height at bearingX/Y), at a 1:1 texel:unit scale — its vertex code builds the
    quad from the metrics box plus a material-dependent `padding`, and the UVs
    from m_GlyphRect plus that SAME padding (TMP_Text.SaveGlyphVertexInfo /
    TextMeshPro.GenerateTextMesh; every real font asset checked has
    glyphRect.width == metrics.width, e.g. Liberation 9x59 == 9x59). The SDF
    spread around the glyph is NOT part of the rect — it is the padding TMP
    extends the UVs by.

    This module used to write msdf-atlas-gen's PADDED box (tight + pxrange) into
    m_GlyphRect while the metrics stayed tight. TMP then mapped a UV window
    `pxrange` texels wider than the quad it draws, so every glyph came out
    shrunk by (w + 2*pad) / (w + pxrange + 2*pad) and the shader's distance-decode
    scale (which assumes 1 texel == 1 unit) was wrong — worse the larger the
    sharpness ("Edge Sharpness"/pxrange), which is exactly what was reported.

    atlasBounds are fractional, but m_GlyphRect fields are integers. Rounding the
    rect alone would leave it out of step with the metrics by up to half a texel
    (visible on a 1-texel pixel-font stroke), so the rect is the smallest integer
    box COVERING the tight bounds and the metrics are then derived from that same
    integer box — the two always describe the same region. Covering never leaves
    the glyph's own padded box by more than a texel (its own margin is
    pxrange/2); for pxrange < 2 the extra sliver lies in the neighbour's empty
    gutter, where the field is 0 anyway.

    offset_x/offset_y: where the glyph's msdf-atlas-gen coordinates sit in the
    FINAL atlas (final = msdf + offset; bottom-up Y, like m_GlyphRect) — (0, 0)
    when the msdf-atlas-gen PNG is used verbatim, the paste displacement when it
    was cropped out and packed elsewhere."""
    pb, ab = glyph_entry["planeBounds"], glyph_entry["atlasBounds"]
    half = pxrange / 2
    eps = 1e-6  # keep an exactly-integer edge (e.g. 26.0) from being widened by float noise
    left = ab["left"] + half + offset_x
    right = ab["right"] - half + offset_x
    bottom = ab["bottom"] + half + offset_y
    top = ab["top"] - half + offset_y
    x0, x1 = math.floor(left + eps), math.ceil(right - eps)
    y0, y1 = math.floor(bottom + eps), math.ceil(top - eps)
    x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)  # a hairline glyph must still own a texel
    rect = {"m_X": x0, "m_Y": y0, "m_Width": x1 - x0, "m_Height": y1 - y0}
    # atlas texel `a` <-> plane coordinate pb.left*size + (a - offset_x - ab.left): the same
    # 1 texel == 1 unit mapping the rect gets in TMP, so the integer rect's own edges give
    # the bearings directly.
    metrics = {
        "m_Width": float(x1 - x0),
        "m_Height": float(y1 - y0),
        "m_HorizontalBearingX": pb["left"] * point_size + (x0 - offset_x - ab["left"]),
        "m_HorizontalBearingY": pb["top"] * point_size - (ab["top"] - (y1 - offset_y)),
        "m_HorizontalAdvance": glyph_entry["advance"] * point_size,
    }
    return rect, metrics


def _sdf_png_to_atlas_image(atlas_png: Path) -> Image.Image:
    """Same repacking as _crop_padded_bitmap() (msdf-atlas-gen's plain-
    grayscale "sdf" PNG convention -> TMP's own alpha-channel convention),
    applied to the WHOLE image instead of one glyph's crop — used by
    MODE_REPLACE_ALL, where msdf-atlas-gen's own PNG canvas already IS the
    entire final atlas verbatim (see that mode's own comment in
    _add_characters_modern_schema/_add_characters_legacy_schema for why no
    per-glyph cropping/re-packing/pasting happens in that mode at all): every
    glyph's own atlasBounds gives its exact final position within THIS
    image unchanged, since nothing here moves a single pixel, only
    reinterprets which channel already-decoded-correctly holds the
    distance value.

    Same "open in a `with` block, not a bare Image.open()" fix
    _crop_padded_bitmap() already needed, for the identical reason — a
    lingering open handle on `atlas_png` blocks Windows from deleting the
    TemporaryDirectory it lives in once the caller's own `with
    tempfile.TemporaryDirectory(...)` block exits."""
    with Image.open(atlas_png) as raw:
        if raw.mode != "L":
            raise SDFGenerationError(tr("неожиданный формат PNG от msdf-atlas-gen: {mode}", mode=raw.mode))
        zeros = Image.new("L", raw.size, 0)
        return Image.merge("RGBA", (zeros, zeros, zeros, raw))


def _find_free_rect_index(free_rects: List[dict], width: int, height: int,
                           atlas_w: int, atlas_h: int) -> Optional[int]:
    """Shelf-style best-fit: among every free rect that's actually big enough
    in BOTH dimensions and genuinely fits inside the atlas bounds, prefers
    the one whose HEIGHT is closest to (but not less than) the item's own
    height — checked explicitly, not inferred from "is the destination
    empty" after the fact. (A real bug hit while building this feature:
    picking a free rect by area alone let a too-short rect through, silently
    clipping part of the glyph — PIL's own crop()/paste() don't error on
    out-of-bounds coordinates, they just clip, so an emptiness check alone
    can't catch this.)

    Was pure best-fit-by-AREA until a real reported complaint with a
    screenshot: many same-width glyphs ended up stacked in tall, narrow
    columns, wasting most of the atlas width and triggering growth despite
    plenty of free space elsewhering — root-caused to area being the wrong
    metric here. After placing one glyph flush in a rect's corner, the
    leftover splits into a WIDE-but-shorter piece (the rest of the row) and
    a NARROW-but-taller piece (the same column, more headroom) — see
    _consume_free_rect()'s own docstring for the actual split shape. Pure
    area comparison keeps preferring the narrow/tall piece for the next
    similar-width glyph (a tight width match reads as "less wasted area"
    even though the height waste above it never gets reclaimed), so the
    column just keeps growing instead of ever moving on to a new row.
    Height-closeness fixes this by construction: once a rect has been
    carved into a shelf (see _consume_free_rect()), its same-height
    remainder-to-the-right is the closest possible height match for the
    NEXT similar-height glyph, so it's always preferred over an unrelated,
    much-taller candidate — glyphs fill left-to-right along one shelf before
    a new one is ever started."""
    best_idx = None
    best_height_diff = None
    for i, r in enumerate(free_rects):
        if r["m_Width"] < width or r["m_Height"] < height:
            continue
        if r["m_X"] + width > atlas_w or r["m_Y"] + height > atlas_h:
            continue
        height_diff = r["m_Height"] - height
        if best_height_diff is None or height_diff < best_height_diff:
            best_height_diff = height_diff
            best_idx = i
    return best_idx


def _subtract_rect(free_rect: dict, used: dict) -> List[dict]:
    """`free_rect` with `used`'s area removed, as 0-4 non-overlapping
    remainder pieces (the standard rectangle-subtraction decomposition:
    left/right strips spanning the free rect's full height, plus
    bottom/top strips spanning only the horizontal range the two rects
    actually share). Returns `[free_rect]` unchanged when they don't
    overlap at all.

    Needed for more than just the one rect a placement was chosen from: a
    real bug, caught via a real fixture, not anticipated in advance — a real
    game's own `m_FreeGlyphRects` list can (and, confirmed, does) already
    contain multiple OVERLAPPING entries describing the same physical empty
    area more than once. Splitting only the single rect a placement came
    from left every OTHER pre-existing entry that also covered that same
    area still listed as free — so a later glyph in the same batch could
    pick one of those and land directly on top of an earlier one. Applying
    this subtraction to every entry in the list, not just the chosen one,
    closes that regardless of how messy the real, pre-existing free-rect
    bookkeeping turns out to be."""
    fx0, fy0 = free_rect["m_X"], free_rect["m_Y"]
    fx1, fy1 = fx0 + free_rect["m_Width"], fy0 + free_rect["m_Height"]
    ux0, uy0 = used["m_X"], used["m_Y"]
    ux1, uy1 = ux0 + used["m_Width"], uy0 + used["m_Height"]

    if ux1 <= fx0 or ux0 >= fx1 or uy1 <= fy0 or uy0 >= fy1:
        return [dict(free_rect)]

    pieces = []
    if ux0 > fx0:
        pieces.append({"m_X": fx0, "m_Y": fy0, "m_Width": ux0 - fx0, "m_Height": fy1 - fy0})
    if ux1 < fx1:
        pieces.append({"m_X": ux1, "m_Y": fy0, "m_Width": fx1 - ux1, "m_Height": fy1 - fy0})
    mid_x0, mid_x1 = max(fx0, ux0), min(fx1, ux1)
    if mid_x1 > mid_x0:
        if uy0 > fy0:
            pieces.append({"m_X": mid_x0, "m_Y": fy0, "m_Width": mid_x1 - mid_x0, "m_Height": uy0 - fy0})
        if uy1 < fy1:
            pieces.append({"m_X": mid_x0, "m_Y": uy1, "m_Width": mid_x1 - mid_x0, "m_Height": fy1 - uy1})
    return pieces


def _consume_free_rect(free_rects: List[dict], index: int, width: int, height: int) -> dict:
    """Places the new glyph at the chosen free rect's own bottom-left corner.

    The CHOSEN rect gets a shelf-style split, not a plain rectangle
    subtraction: the placed item claims a strip spanning the rect's FULL
    WIDTH at just the item's own height (a "shelf"), which splits into up to
    two remainders — the rest of THAT shelf, to the right (same height,
    reduced width — the natural next-glyph target for a same-height
    neighbor) and the leftover headroom above the whole shelf (full width,
    reduced height — becomes a new, WIDE candidate once the current shelf
    fills up, instead of a narrow column). This is what actually makes
    _find_free_rect_index()'s height-closeness heuristic behave like real
    shelf packing — seeded here, not by construction of the heuristic alone.

    Every OTHER entry in free_rects still gets the plain, exact-placed-area
    subtraction (_subtract_rect(r, used)) — deliberately narrower than the
    chosen rect's own shelf-shaped split, since a pre-existing, possibly
    overlapping entry elsewhere in the list has no relationship to THIS
    shelf; only the physically-occupied pixels need clearing from it (see
    _subtract_rect()'s own docstring for why overlapping entries are handled
    this way at all)."""
    chosen = free_rects[index]
    used = {"m_X": chosen["m_X"], "m_Y": chosen["m_Y"], "m_Width": width, "m_Height": height}
    new_list: List[dict] = []
    for i, r in enumerate(free_rects):
        if i == index:
            if width < chosen["m_Width"]:
                new_list.append({
                    "m_X": chosen["m_X"] + width, "m_Y": chosen["m_Y"],
                    "m_Width": chosen["m_Width"] - width, "m_Height": height,
                })
            if height < chosen["m_Height"]:
                new_list.append({
                    "m_X": chosen["m_X"], "m_Y": chosen["m_Y"] + height,
                    "m_Width": chosen["m_Width"], "m_Height": chosen["m_Height"] - height,
                })
            continue
        new_list.extend(_subtract_rect(r, used))
    free_rects[:] = new_list
    return used


def _next_atlas_size(current: int) -> Optional[int]:
    """Next larger size in TMP's own standard progression — None once already
    at (or somehow past) the largest size that dropdown offers, at which
    point growing further isn't something a real TMP font asset could
    represent either."""
    for size in _STANDARD_ATLAS_SIZES:
        if size > current:
            return size
    return None


def _grow_atlas_canvas(atlas_img: Image.Image, free_rects: List[dict],
                        old_w: int, old_h: int, new_w: int, new_h: int) -> Image.Image:
    """Grows the atlas to a new, larger canvas without touching a single
    existing glyph's own m_GlyphRect coordinates.

    This needs real care, not just `Image.new(...); paste(old, (0, 0))`:
    m_GlyphRect.m_Y is measured bottom-left-up (confirmed against real TMP
    shader code — see this module's own docstring), while PIL images are
    addressed top-left-down. As long as the canvas HEIGHT doesn't change,
    those two conventions stay in a fixed relationship and pasting at PIL
    (0, 0) is fine. But the moment height grows, row 0 no longer means the
    same "distance from the bottom" it used to — pasting the old content at
    the PIL origin would silently shift every existing glyph's true Y
    position without ever touching its stored m_GlyphRect, corrupting every
    glyph that existed before the resize, not just leaving new space
    unusable. Anchoring the old content to the canvas's own bottom-left
    corner instead — PIL position (0, new_h - old_h) — keeps every existing
    glyph exactly where its already-written m_GlyphRect says it is, with no
    table rewrite needed at all."""
    new_img = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
    y_offset = new_h - old_h
    new_img.paste(atlas_img, (0, y_offset))

    if new_w > old_w:
        free_rects.append({"m_X": old_w, "m_Y": 0, "m_Width": new_w - old_w, "m_Height": new_h})
    if new_h > old_h:
        free_rects.append({"m_X": 0, "m_Y": old_h, "m_Width": old_w, "m_Height": new_h - old_h})

    return new_img


def _patch_material_texture_size(material_obj, width: float, height: float) -> bool:
    """Keeps the Material's `_TextureWidth`/`_TextureHeight` in sync with a
    resized atlas. `m_AtlasWidth`/`m_AtlasHeight` on the FontAsset itself
    (updated by the caller) are what TMP's own mesh/UV generation actually
    reads for glyph positioning (confirmed against real decompiled
    TMP_Text.cs code) — these Material properties are a second, separate
    copy the SHADER reads directly for texel-accurate effects (outline
    softness, glow, underlay). Leaving them stale after a resize wouldn't
    break basic glyph placement, but would desync those effects — so this
    is real, disclosed Material-sync work, not decoration. Returns False
    (non-fatal — the caller still has a structurally correct, just
    imperfectly-synced, result) if the Material can't be read/patched at
    all, which shouldn't happen for any font asset that already worked well
    enough to reach this point."""
    if material_obj is None:
        return False
    try:
        data = material_obj.parse_as_dict()
        floats = data["m_SavedProperties"]["m_Floats"]
        new_floats = []
        changed = False
        for name, value in floats:
            if name == "_TextureWidth":
                value = float(width)
                changed = True
            elif name == "_TextureHeight":
                value = float(height)
                changed = True
            new_floats.append((name, value))
        if not changed:
            return False
        data["m_SavedProperties"]["m_Floats"] = new_floats
        material_obj.patch(data)
        return True
    except Exception:
        return False


def _patch_material_gradient_scale(material_obj, gradient_scale: float) -> bool:
    """Keeps the Material's `_GradientScale` in sync with whatever pxrange
    THIS generation actually used to bake the new/regenerated glyphs.

    Real gap found and fixed here: `_GradientScale` is the ONE shared,
    atlas-wide runtime parameter TMP's own shader uses to decode EVERY
    glyph's distance-field data — there is no per-glyph equivalent. Before
    this fix, `pxrange_override` only ever influenced how msdf-atlas-gen
    baked the newly-added glyphs' own pixels (their spread/padding and
    `_derive_metrics()`'s bearing math) — the Material's own `_GradientScale`
    was read (resolve_gradient_scale()) but never written back, in any mode.
    Passing a pxrange different from the atlas's existing `_GradientScale`
    therefore baked new glyphs the shader would then decode at RUNTIME using
    the OLD, mismatched value — a genuine rendering bug (the new glyphs
    could come out visibly too soft or too sharp relative to what was
    actually requested), not just a cosmetic inconsistency with older
    glyphs. Called unconditionally on every commit with whatever `pxrange`
    this generation resolved to (override-or-existing) — when no override
    was given, that value already equals the Material's current
    `_GradientScale`, so the write is a genuine no-op then; the fix is only
    load-bearing when an override actually differed.

    Note this is intentionally the SAME resolution this project's own
    methodology already accepted for point size in Unity's own additive
    workflow: changing a shared, atlas-wide parameter on ANY commit
    (including a plain `add`) affects how every OTHER already-baked glyph on
    this atlas decodes too — there is no way to give only the NEW glyphs a
    different sharpness without a per-glyph decode parameter TMP's shader
    does not have. Keeping the Material honest about what was actually baked
    is the correct trade-off: leaving it stale (the pre-fix behavior) doesn't
    avoid this shared-parameter reality, it just makes the mismatch silent
    and guarantees the NEW glyphs specifically are wrong instead of a
    deliberate, disclosed choice about the WHOLE atlas's sharpness. Same
    signature/return convention as `_patch_material_texture_size()` — `False`
    (non-fatal) only if the Material can't be read/patched at all."""
    if material_obj is None:
        return False
    try:
        data = material_obj.parse_as_dict()
        floats = data["m_SavedProperties"]["m_Floats"]
        new_floats = []
        changed = False
        for name, value in floats:
            if name == "_GradientScale":
                value = float(gradient_scale)
                changed = True
            new_floats.append((name, value))
        if not changed:
            return False
        data["m_SavedProperties"]["m_Floats"] = new_floats
        material_obj.patch(data)
        return True
    except Exception:
        return False


MODE_ADD = "add"
MODE_REPLACE_ENTERED = "replace_entered"
MODE_REPLACE_ALL = "replace_all"


def _remove_character(char_table: List[dict], glyph_table: List[dict], free_rects: List[dict],
                       used_rects: List[dict], codepoint: int) -> None:
    """Removes one character's table entry, and — only if no OTHER character
    entry still references the same glyph index (multiple codepoints
    sharing one glyph is rare for simple Latin/Cyrillic text but real fonts
    can do it, e.g. case/canonical-equivalence setups) — its glyph entry
    too, freeing the atlas space it occupied back into free_rects (and
    dropping the matching entry from used_rects, kept in sync alongside it —
    see add_characters_to_font_asset()'s own note on why m_UsedGlyphRects is
    tracked at all). Used by "replace_entered" mode right before
    regenerating a codepoint that's already present."""
    idx = next((i for i, c in enumerate(char_table) if c.get("m_Unicode") == codepoint), None)
    if idx is None:
        return
    removed_char = char_table.pop(idx)
    glyph_index = removed_char.get("m_GlyphIndex")
    if any(c.get("m_GlyphIndex") == glyph_index for c in char_table):
        return  # another character still needs this glyph — leave it in place
    gidx = next((i for i, g in enumerate(glyph_table) if g.get("m_Index") == glyph_index), None)
    if gidx is None:
        return
    removed_glyph = glyph_table.pop(gidx)
    rect = removed_glyph.get("m_GlyphRect")
    if rect and rect.get("m_Width", 0) > 0 and rect.get("m_Height", 0) > 0:
        # m_GlyphRect is the glyph's TIGHT box (see _tight_glyph_geometry()); the atlas
        # space it actually owns is the padded packing rect around it, which is what
        # m_UsedGlyphRects holds. Free THAT — freeing only the tight box would leave the
        # glyph's whole SDF margin permanently unusable, and no new (padded) glyph would
        # ever fit the hole. Smallest containing entry wins; an exact match (font assets
        # whose tight and packing rects coincide) is just the degenerate case.
        rx0, ry0 = rect["m_X"], rect["m_Y"]
        rx1, ry1 = rx0 + rect["m_Width"], ry0 + rect["m_Height"]
        # Sanity bound on how far a packing rect may overshoot the tight box per side: a real
        # one is only the SDF margin (a few texels to a few tens), while a malformed
        # m_UsedGlyphRects entry that happens to enclose the glyph (say, the whole atlas)
        # must never be handed back as "free" — it would let a new glyph land on top of
        # neighbours.
        max_margin = 64
        containing = [
            (i, r) for i, r in enumerate(used_rects)
            if 0 <= rx0 - r.get("m_X", 0) <= max_margin and 0 <= ry0 - r.get("m_Y", 0) <= max_margin
            and 0 <= r.get("m_X", 0) + r.get("m_Width", 0) - rx1 <= max_margin
            and 0 <= r.get("m_Y", 0) + r.get("m_Height", 0) - ry1 <= max_margin
        ]
        if containing:
            ridx, packing_rect = min(containing, key=lambda ir: ir[1].get("m_Width", 0) * ir[1].get("m_Height", 0))
            free_rects.append(dict(packing_rect))
            used_rects.pop(ridx)
        else:
            free_rects.append(dict(rect))


def _schema_glyph_template(font_obj, list_field_name: str = "m_GlyphTable") -> Optional[dict]:
    """Fallback for `_new_glyph_dict()`'s template when the font asset has an
    EMPTY m_GlyphTable (a real, confirmed case — 'Be Kind To The Earth SDF' in
    a real Truck-kun fixture has zero pre-existing glyphs, so there's no
    existing row to copy the schema's extra fields — like
    m_ClassDefinitionType — from). `full["m_GlyphTable"][0]` not existing
    doesn't mean the SCHEMA is unknown, though: the object's own TypeTree node
    still describes the Glyph struct's exact field set regardless of how many
    (zero, in this case) rows are actually populated, so this walks
    m_GlyphTable → Array → data (the array-element node, named after its own
    struct type, e.g. "Glyph") to recover that field list directly, rather
    than needing another already-populated glyph to copy from.

    `list_field_name` generalizes this to the legacy pre-1.4.0 schema's own
    combined character+glyph list, `m_glyphInfoList` (its element type is
    `TMP_Glyph`, not `Glyph`, but the walk is identical) — see
    `_new_legacy_glyph_dict()`.

    Values are all `0` — deliberately, matching `_new_glyph_dict()`'s own
    existing precedent for a compound/unknown extra field, and a safe default
    for `m_ClassDefinitionType` specifically (0 is Unity's own default enum
    value pattern; every real font asset checked with a non-empty table that
    DOES have this field uses 0 for glyphs added via TMP's own normal
    generation path). Returns None (matching the old "no template" behavior)
    if the schema can't be walked this way for any reason — this is a
    best-effort improvement over crashing, not a hard requirement."""
    try:
        node = font_obj._get_typetree_node()
    except Exception:
        return None
    if node is None:
        return None

    def _find_child(n, name):
        for c in getattr(n, "m_Children", None) or []:
            if getattr(c, "m_Name", None) == name:
                return c
        return None

    def _find_named(n, name):
        if getattr(n, "m_Name", None) == name:
            return n
        for c in getattr(n, "m_Children", None) or []:
            found = _find_named(c, name)
            if found is not None:
                return found
        return None

    glyph_table_node = _find_named(node, list_field_name)
    if glyph_table_node is None:
        return None
    array_node = _find_child(glyph_table_node, "Array")
    if array_node is None:
        return None
    data_node = _find_child(array_node, "data")
    if data_node is None:
        return None
    field_names = [c.m_Name for c in (getattr(data_node, "m_Children", None) or []) if getattr(c, "m_Name", None)]
    if not field_names:
        return None
    return {name: 0 for name in field_names}


def _new_glyph_dict(template: Optional[dict], index: int, metrics: dict, rect: dict) -> dict:
    """Builds the new glyph entry with EXACTLY the field set a real
    neighboring glyph on this same font asset already has — confirmed across
    real fixtures that this can genuinely vary (one real game's Glyph struct
    has `m_ClassDefinitionType`, another, identically-shaped at the
    TMP_FontAsset level, does not) — copying an existing entry's own key set
    is what makes this schema-agnostic instead of hardcoding one shape."""
    base = {
        "m_Index": index,
        "m_Metrics": dict(metrics),
        "m_GlyphRect": dict(rect),
        "m_Scale": 1.0,
        "m_AtlasIndex": 0,
    }
    if template:
        for key in template:
            if key not in base:
                base[key] = template[key] if not isinstance(template[key], (dict, list)) else 0
    return base


# ---------------------------------------------------------------------------
# Legacy (pre-1.4.0 TMP package) schema — a genuinely different container,
# not a variant of the modern one. Real, populated fixture: "Emily is Away
# Too" (a 2018.4.36f1 game whose TMP_FontAsset predates the m_GlyphTable/
# m_CharacterTable rework entirely — glyph data lives in a single combined
# `m_glyphInfoList` list of `TMP_Glyph` entries, `id` IS the Unicode
# codepoint directly (no separate character table — one entry serves both
# roles), the atlas is a single `atlas` PPtr (not `m_AtlasTextures[]`), atlas
# dimensions live INSIDE `m_fontInfo` (`AtlasWidth`/`AtlasHeight`, not a
# top-level `m_AtlasWidth`), and there is no `m_FreeGlyphRects`/
# `m_UsedGlyphRects` at all — this era never persisted atlas-packing
# bookkeeping, so free space is recomputed fresh from existing glyph
# positions every call instead of read back.
#
# Verified real-data findings this section relies on (see the conversation
# that derived them — every number below was cross-checked against actual
# game data, not assumed by analogy to the modern schema):
#   - `TMP_Glyph.xOffset/yOffset/width/height/xAdvance` are numerically the
#     SAME quantities as the modern schema's `m_HorizontalBearingX/Y`/
#     `m_Width/m_Height`/`m_HorizontalAdvance` — confirmed by generating a
#     real glyph ('A') via msdf-atlas-gen at Emily's own real point size and
#     _GradientScale, and finding the EXISTING `_derive_metrics()` formula's
#     output matches the real stored TMP_Glyph values to within the same
#     small hinting-residual margin already documented for the modern
#     schema. So `_derive_metrics()` is reused completely unchanged here.
#   - Material property names (`_GradientScale`, `_TextureWidth`,
#     `_TextureHeight`) are IDENTICAL to the modern schema — confirmed
#     against Emily's own real Material (`_GradientScale=10.0`, matching the
#     same convention). `resolve_gradient_scale()`/`_patch_material_texture_size()`
#     are reused unchanged.
#   - The Y-axis convention is TOP-DOWN (row 0 = top of atlas) — the OPPOSITE
#     of the modern schema's bottom-up `m_GlyphRect`. Confirmed by cropping a
#     real glyph's own declared (x, y, width, height) both ways and looking
#     at the result: top-down produced a clean, correctly-oriented "A";
#     bottom-up produced a corrupted partial crop. This is why placement/
#     growth logic below anchors and paste-positions differently from the
#     modern schema's own `_grow_atlas_canvas()`, even though the underlying
#     rect-subtraction math (`_subtract_rect()`, `_find_free_rect_index()`,
#     `_consume_free_rect()`) is orientation-agnostic and reused as-is.
#   - No persisted free-rect list exists, so a reserved footprint has to be
#     estimated for each EXISTING glyph instead of read back exactly. Raw
#     alpha-thresholding a real atlas to measure the "true" SDF footprint
#     turned out to be unreliable (an SDF's distance value decays gradually,
#     never hitting a hard zero, so a low alpha threshold reads as "ink"
#     almost all the way to a neighboring glyph regardless of true spread) —
#     rather than trust that noisy measurement, `_legacy_initial_free_rects()`
#     reserves each existing glyph's declared rect expanded by a full
#     `pxrange` margin on every side (not the modern schema's tighter,
#     already-verified `pxrange/2`), deliberately erring toward reserving
#     MORE space than strictly necessary — this can only make new placements
#     more conservative (never fitting quite as many characters as a
#     perfectly tight packer might), never cause an overlap/bleed artifact.
# ---------------------------------------------------------------------------

def _legacy_existing_ids(glyph_list: List[dict]) -> set:
    return {g["id"] for g in glyph_list if isinstance(g, dict) and "id" in g}


def _legacy_initial_free_rects(glyph_list: List[dict], atlas_w: int, atlas_h: int, pxrange: float) -> List[dict]:
    """Recomputed from scratch every call (see module note above) — the
    complement of every existing glyph's reserved footprint within the whole
    atlas rectangle, via the same general rectangle-subtraction the modern
    schema already uses for a different reason (its own pre-existing
    free-rect list can itself contain overlapping entries). A zero-footprint
    entry (a whitespace/invisible character — width or height <= 0) reserves
    nothing, matching how it consumed zero atlas space when it was placed."""
    free_rects = [{"m_X": 0, "m_Y": 0, "m_Width": atlas_w, "m_Height": atlas_h}]
    for g in glyph_list:
        width, height = g.get("width", 0), g.get("height", 0)
        if width <= 0 or height <= 0:
            continue
        rx = max(0.0, g["x"] - pxrange)
        ry = max(0.0, g["y"] - pxrange)
        rw = min(atlas_w, g["x"] + width + pxrange) - rx
        rh = min(atlas_h, g["y"] + height + pxrange) - ry
        if rw <= 0 or rh <= 0:
            continue
        reserved = {"m_X": rx, "m_Y": ry, "m_Width": rw, "m_Height": rh}
        new_list: List[dict] = []
        for r in free_rects:
            new_list.extend(_subtract_rect(r, reserved))
        free_rects = new_list
    return free_rects


def _grow_atlas_canvas_topdown(atlas_img: Image.Image, free_rects: List[dict],
                                old_w: int, old_h: int, new_w: int, new_h: int) -> Image.Image:
    """The legacy schema's own top-down counterpart to `_grow_atlas_canvas()`
    — existing content is anchored at the canvas's TOP-left corner (PIL
    (0, 0)) instead of the bottom, since `y=0` already means "top of atlas"
    in this convention regardless of how tall the canvas becomes (unlike the
    modern schema's bottom-up `m_GlyphRect`, where `y=0` means "bottom" and
    growing height shifts every existing row's true position unless the old
    content is re-anchored to match)."""
    new_img = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
    new_img.paste(atlas_img, (0, 0))
    if new_w > old_w:
        free_rects.append({"m_X": old_w, "m_Y": 0, "m_Width": new_w - old_w, "m_Height": new_h})
    if new_h > old_h:
        free_rects.append({"m_X": 0, "m_Y": old_h, "m_Width": old_w, "m_Height": new_h - old_h})
    return new_img


def _new_legacy_glyph_dict(template: Optional[dict], codepoint: int, metrics: dict, x: float, y: float) -> dict:
    """`TMP_Glyph`'s counterpart to `_new_glyph_dict()` — one flat dict
    combines what the modern schema splits across `m_CharacterTable`
    (codepoint → glyph index) and `m_GlyphTable` (glyph index → metrics/rect),
    since this era's `id` field IS the codepoint directly. `metrics` is the
    SAME dict `_derive_metrics()` already produces for the modern schema
    (see the module note above for why that formula transfers unchanged) —
    just re-read under this schema's own field names."""
    base = {
        "id": codepoint,
        "x": x, "y": y,
        "width": metrics["m_Width"], "height": metrics["m_Height"],
        "xOffset": metrics["m_HorizontalBearingX"], "yOffset": metrics["m_HorizontalBearingY"],
        "xAdvance": metrics["m_HorizontalAdvance"],
    }
    if template:
        for key in template:
            if key not in base:
                base[key] = template[key] if not isinstance(template[key], (dict, list)) else 0
    return base


def _apply_replace_all_face_metrics(face_info: dict, atlas_json: dict, point_size: float, legacy: bool,
                                    declared_point_size: Optional[float] = None,
                                    original_layout: Optional[dict] = None) -> None:
    """MODE_REPLACE_ALL only: rewrites the font asset's face-wide metrics (point
    size / line height / ascender / descender / baseline / underline) from the font
    that was ACTUALLY just baked, instead of leaving them as whatever font this
    asset was originally created from.

    Real reported bug, TWO compounding causes: swapping a font asset's
    characters+atlas to a completely different font via "Полная замена"
    (TinyUnicode replacing Roboto, real fixtures: `Unity samples/SDF lines bug/
    ROUNDS`) left the text visibly shifted (and, depending on the point size
    picked, wrongly SCALED) — even though every individual glyph's own
    m_GlyphRect/m_Metrics were correct (baked from the real TinyUnicode outlines).
    add_characters_to_font_asset() never touched m_FaceInfo/m_fontInfo at all, for
    any mode:

    1. **Point size.** TMP scales every glyph's metrics at runtime by
       `(the TextMeshPro component's own font size) / m_FaceInfo.m_PointSize`
       (confirmed via decompiled `TextMeshPro.cs`: `num23 = m_currentFontSize *
       ... / faceInfo.pointSize * ...`, which then scales bearingX/Y/width/height
       when building the glyph quad) — i.e. `m_PointSize` is the divisor the WHOLE
       bake is implicitly relative to. A generation at any point size OTHER than
       "Match original" (custom, or "Автоподбор" against a fixed atlas) leaves
       `m_PointSize` at the OLD font's value, so every glyph — baked assuming a 1:1
       relationship at the ACTUAL bake size — gets an extra, wrong scale factor
       applied on top at runtime. Confirmed directly: baking at 32pt onto a font
       whose stored PointSize stayed 74 left every glyph scaled by an extra,
       unintended 32/74 ≈ 0.43x. "Match original" is silently immune (bake size ==
       stored PointSize == ratio 1), which is exactly why a first, same-settings
       A/B comparison of this fix's own earlier commit against the streaks/
       shrinkage fix before it (both done at "Match original") showed no
       meaningful difference — this bug only shows up once a DIFFERENT point size
       is actually used, which is the likely real trigger for a report that
       surfaced across two separate manual generation attempts.
    2. **Line height / ascender / descender / baseline.** TMP's own vertical-layout
       code (`TMP_Text.cs`'s `GenerateTextMesh`: `num16 = faceInfo.baseline * ...`
       for each glyph's pen Y, `num8 = lineHeight - (ascentLine - descentLine)` for
       line spacing/block centering) reads the WHOLE FONT ASSET's m_FaceInfo, never
       anything per-glyph. Roboto's own FaceInfo (ascentLine 68.65/74pt = 0.928 em,
       descentLine -18.07/74pt = -0.244 em) is ~30-40% taller/deeper than
       TinyUnicode's real metrics (hhea ascent 0.666 em, descent -0.125 em) — large
       enough on its own to visibly shift where TMP centers/lines up the block,
       independent of the point-size bug above.

    Only for MODE_REPLACE_ALL: MODE_ADD/MODE_REPLACE_ENTERED add or refresh a
    SUBSET of glyphs while the rest of the font (and its identity, including its
    own point size) stays the original — rewriting face-wide metrics from
    whatever font supplied just the added glyphs would misalign every OTHER,
    untouched glyph instead.

    Source for line height/ascender/descender/underline: msdf-atlas-gen's own
    JSON output already includes them in em units (`atlas_json["metrics"]`, from
    its own FreeType-backed read of the font file) — confirmed these are the
    font's whole-face values (unaffected by which characters were requested) by
    comparing the same font's "metrics" block across differently-sized character
    subsets. No new font-parsing dependency needed for this: this project
    deliberately dropped fontTools (see core/font_cmap.py's own docstring)
    specifically to avoid pulling in a font library just to read a few header
    fields — reusing data msdf-atlas-gen computes anyway keeps that intact. Point
    size itself needs no external source at all — `point_size` is simply what
    THIS generation actually baked at, already a parameter here.

    Deliberately narrow beyond that: only the fields TMP's own layout code was
    confirmed (by reading its decompiled source) to actually use. m_CapLine/
    m_MeanLine (cap-height/x-height — used only for italic-slant origin, not
    implicated in the report) and the sub/superscript offset/size (msdf-atlas-gen
    has no verified value for these) are deliberately left as the original
    font's — guessing them would be exactly the kind of unverified binary/metrics
    assumption this project's methodology avoids."""
    # `declared_point_size` (see _resolve_declared_point_size) is what is WRITTEN as the asset's point size;
    # every other metric below stays in units of the size actually baked (`point_size`).
    declared = declared_point_size if declared_point_size is not None else point_size
    if legacy:
        face_info["PointSize"] = float(declared)
    else:
        # m_PointSize is a genuine Unity `int` field (confirmed against the real
        # TypeTree node, not assumed from a print()'s formatting) — unlike every
        # other field this function touches. A fractional custom point size (the
        # dialog's own spin box allows one decimal place) is rounded for storage;
        # the glyphs themselves are still baked at the exact requested float, so
        # this can leave a sub-1-point residual between m_PointSize and the real
        # bake size — a real, but far smaller, version of the same scale mismatch
        # this fix closes (worst case ~1-2%, vs. the unbounded mismatch before).
        face_info["m_PointSize"] = max(1, int(round(declared)))
    m = atlas_json.get("metrics") or {}
    line_height, ascender, descender = m.get("lineHeight"), m.get("ascender"), m.get("descender")
    underline_y, underline_thickness = m.get("underlineY"), m.get("underlineThickness")
    if line_height is None or ascender is None or descender is None:
        return  # msdf-atlas-gen always emits these for a real font; nothing more to update if it didn't
    if legacy:
        face_info["LineHeight"] = line_height * point_size
        face_info["Ascender"] = ascender * point_size
        face_info["Descender"] = descender * point_size
        face_info["Baseline"] = 0.0
        if underline_y is not None:
            face_info["Underline"] = underline_y * point_size
        if underline_thickness is not None:
            face_info["UnderlineThickness"] = underline_thickness * point_size
    else:
        face_info["m_LineHeight"] = line_height * point_size
        face_info["m_AscentLine"] = ascender * point_size
        face_info["m_DescentLine"] = descender * point_size
        face_info["m_Baseline"] = 0.0
        if underline_y is not None:
            face_info["m_UnderlineOffset"] = underline_y * point_size
        if underline_thickness is not None:
            face_info["m_UnderlineThickness"] = underline_thickness * point_size
    if declared_point_size is not None and original_layout:
        # Height matching is on: keep the ORIGINAL line box as it appears on screen (see
        # _resolve_declared_point_size). Stored values are in units of the declared size.
        stored = float(face_info["PointSize"] if legacy else face_info["m_PointSize"])
        keys = ("LineHeight", "Ascender", "Descender") if legacy else ("m_LineHeight", "m_AscentLine", "m_DescentLine")
        for key, name in zip(keys, ("line", "asc", "desc")):
            face_info[key] = original_layout[name] * stored


def _add_characters_legacy_schema(
    font_obj, full: dict, result: AddCharactersResult, font_file_path: str, covered: Optional[set],
    mode: str, progress_cb: Optional[Callable[[int, int], None]], should_cancel: Optional[Callable[[], bool]],
    point_size_override: Optional[float] = None, point_size_fit: bool = False,
    pxrange_override: Optional[float] = None,
    atlas_width_override: Optional[int] = None, atlas_height_override: Optional[int] = None,
    auto_commit: bool = True, match_original_height: bool = False,
) -> AddCharactersResult:
    face_info = full["m_fontInfo"]
    atlas_w, atlas_h = int(face_info["AtlasWidth"]), int(face_info["AtlasHeight"])
    result.old_atlas_size = (atlas_w, atlas_h)
    orig_em_heights = _original_glyph_em_heights(full, legacy=True) if match_original_height else {}
    orig_layout = _original_vertical_layout(full, legacy=True) if match_original_height else None

    glyph_list = list(full["m_glyphInfoList"])
    glyph_template = glyph_list[0] if glyph_list else _schema_glyph_template(font_obj, "m_glyphInfoList")

    clear_atlas_pixels = False
    if mode == MODE_REPLACE_ALL:
        glyph_list = []
        existing = set()
        clear_atlas_pixels = True
    else:
        existing = _legacy_existing_ids(glyph_list)

    to_generate = []
    for cp in result.requested:
        if cp in existing:
            if mode == MODE_REPLACE_ENTERED:
                # No separate glyph-index indirection to worry about here
                # (see the module note above) — removing the one entry with
                # this id is the whole operation, and the freed space is
                # picked up automatically by _legacy_initial_free_rects()
                # recomputing from the post-removal glyph_list below.
                glyph_list = [g for g in glyph_list if g.get("id") != cp]
                to_generate.append(cp)
            else:
                result.results.append(NewCharacterResult(cp, False, tr("уже есть в этом SDF")))
        elif covered is not None and cp not in covered:
            result.results.append(NewCharacterResult(cp, False, tr("отсутствует в ttf/otf")))
        else:
            to_generate.append(cp)

    if not to_generate:
        return result

    components = resolve_sdf_components(font_obj)
    if components.texture_obj is None:
        raise SDFGenerationError(tr("не найдена текстура атласа: {texture_error}", texture_error=components.texture_error))

    pxrange = pxrange_override or resolve_gradient_scale(components.material_obj)
    # point_size_fit is its OWN explicit flag now, not inferred from
    # point_size_override being None — see add_characters_to_font_asset()'s
    # own docstring for why (a real, reported confusion with the earlier
    # implicit version). Already validated there (requires mode=replace_all
    # + a fixed atlas + no point_size_override), so no re-check needed here.
    fit_atlas = None
    if point_size_fit and atlas_width_override is not None:
        point_size = _find_max_point_size_for_atlas(
            font_file_path, to_generate, pxrange, atlas_width_override, atlas_height_override,
        )
    elif point_size_fit:
        point_size, fit_atlas = _fit_to_texture(
            font_file_path, to_generate, pxrange, atlas_w, atlas_h, face_info.get("PointSize") or 0,
        )
    else:
        point_size = point_size_override or face_info["PointSize"]

    tex_data = components.texture_obj.parse_as_object()
    # Same real, confirmed edge case as the modern schema's own equivalent
    # check (see add_characters_to_font_asset's docstring history) — an
    # unused font asset's atlas Texture2D can be a genuine 0×0 placeholder.
    texture_is_empty = tex_data.m_Width == 0 or tex_data.m_Height == 0
    if texture_is_empty and glyph_list:
        raise SDFGenerationError(
            tr("Текстура атласа этого шрифта пуста (0×0), но список глифов не пуст — данные этого шрифта "
               "повреждены или несовместимы.")
        )
    if mode != MODE_REPLACE_ALL:
        atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0)) if texture_is_empty \
            else tex_data.image.convert("RGBA")
        free_rects = _legacy_initial_free_rects(glyph_list, atlas_w, atlas_h, pxrange)
    # else: atlas_img/free_rects deferred below, once msdf-atlas-gen's own
    # "-pots" pass has told us the tight fit for this exact character set —
    # see the modern schema's identical comment (_add_characters_modern_schema)
    # for the full explanation of why a full rebuild shouldn't just reuse this
    # font asset's old, unrelated atlas_w/atlas_h.

    # See _add_characters_modern_schema's identical comment for why this is
    # gated on mode == MODE_REPLACE_ALL here too.
    atlas_dims_arg = (
        (atlas_width_override, atlas_height_override)
        if mode == MODE_REPLACE_ALL and atlas_width_override is not None
        else fit_atlas
    )

    with tempfile.TemporaryDirectory(prefix="ustudio_sdf_") as tmp:
        tmp_path = Path(tmp)
        try:
            atlas_json, atlas_png = _run_msdf_atlas_gen(
                font_file_path, to_generate, point_size, pxrange, tmp_path, atlas_dimensions=atlas_dims_arg,
            )
        except SDFGenerationError as e:
            # One whole-run failure, stated once (see AddCharactersResult.run_error) — not a
            # copy of the same reason on every requested character.
            result.run_error = str(e)
            for cp in to_generate:
                result.results.append(NewCharacterResult(cp, False, _RUN_FAILED_REASON))
            return result

        if mode == MODE_REPLACE_ALL:
            fitted = atlas_json.get("atlas") or {}
            if "width" in fitted and "height" in fitted:
                atlas_w, atlas_h = int(fitted["width"]), int(fitted["height"])
            # No free_rects/our-own-packer pass for this mode — see
            # replace_all_direct_layout below, same reasoning as the modern
            # schema's identical fix (its own comment has the full
            # real-bug writeup: this project's own packer can disagree with
            # msdf-atlas-gen's, silently growing PAST an explicitly
            # requested/point-size-searched fixed size at real character-
            # count scale).
            free_rects = []
            # See _apply_replace_all_face_metrics()'s own docstring — a full font
            # swap needs the font ASSET's own face-wide line/ascender/descender
            # metrics updated too, not just its glyphs.
            declared = _resolve_declared_point_size(
                match_original_height, orig_em_heights, atlas_json, point_size, pxrange, result)
            _apply_replace_all_face_metrics(
                face_info, atlas_json, point_size, legacy=True,
                declared_point_size=declared, original_layout=orig_layout,
            )
            _zero_bold_spacing(full, declared, result)

        replace_all_direct_layout = mode == MODE_REPLACE_ALL
        if replace_all_direct_layout:
            atlas_img = _sdf_png_to_atlas_image(atlas_png)

        by_codepoint = {g["unicode"]: g for g in atlas_json["glyphs"]}
        total = len(to_generate)
        for i, cp in enumerate(to_generate):
            if should_cancel and should_cancel():
                break
            if progress_cb:
                progress_cb(i, total)

            entry = by_codepoint.get(cp)
            if entry is None:
                result.results.append(NewCharacterResult(cp, False, tr("шрифт не смог сгенерировать глиф")))
                continue

            if "atlasBounds" not in entry or "planeBounds" not in entry:
                # Same whitespace/invisible-character convention as the
                # modern schema (see its own docstring) — zero footprint,
                # real advance only.
                metrics = {
                    "m_Width": 0.0, "m_Height": 0.0,
                    "m_HorizontalBearingX": 0.0, "m_HorizontalBearingY": 0.0,
                    "m_HorizontalAdvance": entry.get("advance", 0.0) * point_size,
                }
                x = y = 0.0
            elif replace_all_direct_layout:
                # Same "the pixel data is already exactly here, no crop/pack/
                # paste needed" shortcut as the modern schema's identical
                # branch — just expressed in THIS schema's own TOP-DOWN (x, y)
                # convention (see the module note above) instead of the
                # modern schema's bottom-left GlyphRect. `ab["left"]`/
                # `mh - ab["top"]` is the EXACT same left/upper pair
                # _crop_padded_bitmap() already computes for the crop origin
                # (mh == atlas_h here, msdf-atlas-gen's own PNG height) — so
                # this is that same position, just never actually cropped
                # out and pasted back since it's already sitting there.
                ab = entry["atlasBounds"]
                rect_x = int(round(ab["left"]))
                rect_y = int(round(atlas_h - ab["top"]))
                metrics = _derive_metrics(entry, point_size, pxrange)
                x = rect_x + pxrange / 2
                y = rect_y + pxrange / 2
            else:
                patch = _crop_padded_bitmap(atlas_png, entry)
                padded_w, padded_h = patch.size
                # Same empty gutter around the padded box as the modern schema's packing
                # path keeps — see _GLYPH_GUTTER_PX.
                alloc_w, alloc_h = padded_w + 2 * _GLYPH_GUTTER_PX, padded_h + 2 * _GLYPH_GUTTER_PX

                idx = _find_free_rect_index(free_rects, alloc_w, alloc_h, atlas_w, atlas_h)
                while idx is None:
                    next_w = _next_atlas_size(atlas_w)
                    next_h = _next_atlas_size(atlas_h)
                    if next_w is None and next_h is None:
                        break
                    grow_width = next_w is not None and (next_h is None or atlas_w <= atlas_h)
                    new_w = next_w if grow_width else atlas_w
                    new_h = atlas_h if grow_width else next_h
                    atlas_img = _grow_atlas_canvas_topdown(atlas_img, free_rects, atlas_w, atlas_h, new_w, new_h)
                    atlas_w, atlas_h = new_w, new_h
                    idx = _find_free_rect_index(free_rects, alloc_w, alloc_h, atlas_w, atlas_h)
                if idx is None:
                    result.results.append(NewCharacterResult(
                        cp, False, tr("недостаточно места даже при максимальном размере атласа ({atlas_w}×{atlas_h})", atlas_w=atlas_w, atlas_h=atlas_h)
                    ))
                    continue
                rect = _consume_free_rect(free_rects, idx, alloc_w, alloc_h)
                # The padded box sits one gutter in from the allocation's edge.
                rect = {**rect, "m_X": rect["m_X"] + _GLYPH_GUTTER_PX, "m_Y": rect["m_Y"] + _GLYPH_GUTTER_PX}

                # Top-down convention (see the module note above): the paste
                # position IS the rect's own (m_X, m_Y) directly, no flip.
                atlas_img.paste(patch, (int(round(rect["m_X"])), int(round(rect["m_Y"]))))

                metrics = _derive_metrics(entry, point_size, pxrange)
                # The declared (x, y) are the LOGICAL (unpadded) position,
                # inset pxrange/2 from the padded rect's own edge on each
                # side — the same relationship the modern schema's
                # m_HorizontalBearingX/Y already have to their own
                # m_GlyphRect, just expressed here as an absolute atlas
                # position rather than a baseline-relative offset (this
                # schema's x/y ARE the absolute placement, confirmed
                # against real data — see the module note above).
                x = rect["m_X"] + pxrange / 2
                y = rect["m_Y"] + pxrange / 2

            glyph_list.append(_new_legacy_glyph_dict(glyph_template, cp, metrics, x, y))
            result.results.append(NewCharacterResult(cp, True))

    if progress_cb:
        progress_cb(total, total)

    result.new_atlas_size = (atlas_w, atlas_h)

    if not any(r.added for r in result.results):
        return result

    result.atlas_preview_image = atlas_img

    def _commit():
        tex_data.set_image(atlas_img, target_format=tex_data.m_TextureFormat)
        components.texture_obj.patch(tex_data)

        full["m_glyphInfoList"] = glyph_list
        face_info["CharacterCount"] = len(glyph_list)
        if result.atlas_resized:
            face_info["AtlasWidth"] = float(atlas_w)
            face_info["AtlasHeight"] = float(atlas_h)
            _patch_material_texture_size(components.material_obj, atlas_w, atlas_h)
        # See _patch_material_gradient_scale()'s own docstring for why this
        # runs unconditionally (not just when result.atlas_resized) -- pxrange
        # is a shared, atlas-wide runtime decode parameter with no per-glyph
        # override, so it has to stay in sync with whatever THIS generation
        # actually baked regardless of whether the atlas itself grew.
        _patch_material_gradient_scale(components.material_obj, pxrange)
        full["m_fontInfo"] = face_info
        font_obj.patch(full)

    if auto_commit:
        _commit()
    else:
        result.commit = _commit

    return result


def add_characters_to_font_asset(
    font_obj,
    font_file_path: str,
    characters: Sequence[int],
    mode: str = MODE_ADD,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    point_size_override: Optional[float] = None,
    point_size_fit: bool = False,
    pxrange_override: Optional[float] = None,
    atlas_width_override: Optional[int] = None,
    atlas_height_override: Optional[int] = None,
    auto_commit: bool = True,
    match_original_height: bool = False,
    include_existing_characters: bool = False,
) -> AddCharactersResult:
    """Adds `characters` (a sequence of Unicode codepoints) to a real
    TMP_FontAsset's atlas — reading its current state, generating real SDF
    bitmaps for whatever's needed under the chosen `mode`, compositing them
    into a copy of the real atlas texture, and writing the new
    glyph/character/free-rect entries back via the same generic obj.patch()
    path already used throughout this app. Never raises for a single bad
    character (not in the font file) — those are reported per-character in
    the result instead; only a structural failure (msdf-atlas-gen itself
    failing, no atlas space at all) raises.

    `mode` is one of:
    - MODE_ADD (default) — skip any requested codepoint already present.
    - MODE_REPLACE_ENTERED — a requested codepoint already present gets its
      existing glyph removed and freshly regenerated (e.g. to pick up a
      different source font or re-baked metrics); anything else already in
      the font that ISN'T in the requested list is left untouched.
    - MODE_REPLACE_ALL — every existing glyph/character is discarded first,
      regardless of whether it's also requested, so the font ends up
      containing ONLY the requested codepoints. The atlas pixel buffer is
      cleared too, not just the tables, so no orphaned pixel data lingers
      where an old, now-unreferenced glyph used to be.

    point_size_override/pxrange_override: real, user-facing "Custom" values
    from the settings dialog's Font Size / SDF Spread groups — None (default)
    means "Match original", i.e. keep using resolve_current_point_size(full)/
    resolve_gradient_scale(material_obj) exactly as before this parameter
    existed. Custom point size changes how large NEW glyphs are baked
    relative to EXISTING ones on the same atlas — a deliberate, disclosed
    tradeoff the dialog itself warns about, not something this function
    second-guesses.

    point_size_fit: "Fit to the current texture" (GUI size item, map `size=fit`) — the largest integer
    size that fits the font asset's current atlas size, never below the font's original size: if the
    characters do not fit at that floor the atlas grows to the next power of two instead (see
    _fit_to_texture()). With a PINNED atlas (atlas_*_override, the map's `atlas=`) it fits inside that
    atlas without growing. Its OWN explicit flag, not inferred from point_size_override=None (an earlier
    implicit version silently changed what "Match original" meant). Mutually exclusive with
    point_size_override.

    match_original_height: make the new glyphs look as tall on screen as the font asset's current ones
    by declaring a smaller point size (see _resolve_declared_point_size() for why this, and not the bake
    size, is what controls on-screen size).

    point_size_override / point_size_fit / match_original_height / pxrange_override are MODE_REPLACE_ALL
    only: in every other mode the new glyphs join existing ones baked at the asset's own size, and a
    different bake size would give them the wrong scale next to them. The same goes for the range
    (edge sharpness): it is one atlas-wide decode parameter (the material's _GradientScale), so a
    different value would change how every EXISTING glyph is decoded.

    atlas_width_override/atlas_height_override: fixes the REPLACE_ALL atlas
    canvas to an exact size instead of letting msdf-atlas-gen auto-fit it
    (-pots) — must be given together (both or neither) and only make sense
    for mode=MODE_REPLACE_ALL, since every other mode preserves existing
    atlas content it can't safely resize around; both constraints are
    enforced here, not left to the caller, since a direct API/GUI caller has
    no other gate before this function (the CLI import has its own earlier,
    friendlier CommandError check for the CLI's specific error style, but
    this function can't rely on every caller doing that first).

    include_existing_characters: also (re)generate every character the font asset ALREADY has but the
    given list does not name, so a font swap / re-bake does not silently lose them — the glyphs come
    from the new font like all the others (a character the new font lacks is reported as skipped, as
    any other). MODE_REPLACE_ALL only: MODE_ADD keeps every existing glyph anyway, and
    MODE_REPLACE_ENTERED is defined as leaving whatever is not listed untouched — bringing the rest
    over would contradict it.

    auto_commit=True (default, matches every caller from before this
    parameter existed: object_actions.py, cli/commands.py) performs the
    actual obj.patch() write-back immediately, as always. auto_commit=False
    builds the new atlas/tables and returns them via
    AddCharactersResult.atlas_preview_image/.commit WITHOUT writing anything
    — used by the settings dialog's Generate-preview-then-Save/Cancel
    workflow (SDFGeneratorDialog) so a rejected/cancelled generation never
    touches the real object at all. Call result.commit() later to actually
    persist; it's None when there was nothing to commit (nothing added)."""
    if (atlas_width_override is None) != (atlas_height_override is None):
        raise SDFGenerationError(
            tr("Ширина и высота атласа должны быть заданы ОБА или ни один — одного значения недостаточно, чтобы "
               "определить прямоугольник.")
        )
    if atlas_width_override is not None and mode != MODE_REPLACE_ALL:
        raise SDFGenerationError(
            tr("Фиксированный размер атласа поддерживается только в режиме «Полная замена».")
        )
    if mode != MODE_REPLACE_ALL and (
        point_size_override is not None or point_size_fit or match_original_height or pxrange_override is not None
        or include_existing_characters
    ):
        raise SDFGenerationError(
            tr("Размер шрифта, резкость краёв, подгонка высоты букв и добавление символов из шрифта доступны "
               "только в режиме «Полная замена»: в остальных режимах новые символы добавляются к уже "
               "существующим и должны иметь тот же масштаб и ту же резкость (она общая для всей текстуры).")
        )
    if point_size_fit and point_size_override is not None:
        raise SDFGenerationError(
            tr("«Вписывание в текстуру» нельзя сочетать с указанием точного размера шрифта — выберите что-то "
               "одно.")
        )
    full = font_obj.parse_as_dict()
    font_name = full.get("m_Name", "?")

    kept_existing: List[int] = []
    if include_existing_characters:
        named = set(characters)
        kept_existing = sorted(cp for cp in _existing_codepoints(full) if cp not in named)
        characters = list(characters) + kept_existing

    with open(font_file_path, "rb") as f:
        font_bytes = f.read()
    if not _looks_like_font_file(font_bytes):
        # Real reported case: a .ttf-named file that was actually something
        # else entirely (confirmed via its own header bytes — "MZ", a DOS/PE
        # executable signature, not any real sfnt version tag) reproduced
        # msdf-atlas-gen's "Loaded geometry of 0 out of N glyphs" for EVERY
        # requested character, ASCII included — the tool doesn't distinguish
        # "this font doesn't have that glyph" from "this isn't a font at
        # all", so a bad file produced one confusing, giant, per-character
        # failure dump (repeated once per requested codepoint) instead of
        # one clear message naming the actual problem. Checking the file's
        # own signature up front turns that into a single early, specific
        # error before ever invoking the subprocess.
        raise SDFGenerationError(
            tr("«{font_file_path}» — не найдена сигнатура TrueType/OpenType. Проверьте, что выбран корректный "
               ".ttf/.otf файл.", font_file_path=font_file_path)
        )
    covered = find_covered_codepoints(font_bytes, characters)

    result = AddCharactersResult(font_name=font_name, requested=list(characters))
    if kept_existing:
        result.notes.append(
            tr("Добавлено недостающих символов из SDF шрифтов: {count}.", count=len(kept_existing))
        )

    if is_legacy_schema(full):
        # The genuinely different, pre-1.4.0 TMP package schema — see the
        # module note above _legacy_existing_ids() for the full real-data
        # derivation this write path is built on.
        return _add_characters_legacy_schema(
            font_obj, full, result, font_file_path, covered, mode, progress_cb, should_cancel,
            point_size_override, point_size_fit, pxrange_override,
            atlas_width_override, atlas_height_override, auto_commit, match_original_height,
        )

    if "m_AtlasWidth" not in full:
        # Neither the modern schema nor the one legacy shape this module
        # actually supports — an as-yet-unencountered schema variant.
        raise SDFGenerationError(
            tr("Схема этого TMP_FontAsset не распознана (нет ни m_AtlasWidth, ни m_glyphInfoList) — ключи "
               "объекта: {sorted}", sorted=sorted(full.keys()))
        )

    return _add_characters_modern_schema(
        font_obj, full, result, font_file_path, covered, characters, mode, progress_cb, should_cancel,
        point_size_override, point_size_fit, pxrange_override,
        atlas_width_override, atlas_height_override, auto_commit, match_original_height,
    )


def _add_characters_modern_schema(
    font_obj, full: dict, result: AddCharactersResult, font_file_path: str, covered: Optional[set],
    characters: Sequence[int], mode: str,
    progress_cb: Optional[Callable[[int, int], None]], should_cancel: Optional[Callable[[], bool]],
    point_size_override: Optional[float] = None, point_size_fit: bool = False,
    pxrange_override: Optional[float] = None,
    atlas_width_override: Optional[int] = None, atlas_height_override: Optional[int] = None,
    auto_commit: bool = True, match_original_height: bool = False,
) -> AddCharactersResult:
    atlas_w, atlas_h = full["m_AtlasWidth"], full["m_AtlasHeight"]
    result.old_atlas_size = (atlas_w, atlas_h)
    # Read before MODE_REPLACE_ALL throws the glyphs away (see _resolve_declared_point_size).
    orig_em_heights = _original_glyph_em_heights(full, legacy=False) if match_original_height else {}
    orig_layout = _original_vertical_layout(full, legacy=False) if match_original_height else None
    free_rects = list(full.get("m_FreeGlyphRects") or [])
    # Real gap found and fixed after this module first shipped: m_UsedGlyphRects
    # (the atlas-packing companion to m_FreeGlyphRects — every real font asset
    # checked keeps both) was never read, updated, or written back at all.
    # TMP's own runtime dynamic-atlas-population code reads it for a
    # Dynamic/DynamicOS font asset that gets MORE characters added during
    # actual gameplay — leaving it stale after this tool edits the same
    # tables wouldn't break anything THIS tool does, but could feed wrong
    # packing decisions to TMP's own code later. Kept in sync the same way
    # free_rects already is.
    used_rects = list(full.get("m_UsedGlyphRects") or [])
    glyph_table = list(full["m_GlyphTable"])
    char_table = list(full["m_CharacterTable"])
    # Captured from the ORIGINAL table, before MODE_REPLACE_ALL potentially
    # empties it below — still the correct schema template for whatever this
    # font asset's own Glyph shape actually is (see _new_glyph_dict()'s own
    # docstring for why this can genuinely vary between font assets), and
    # still a safe, collision-free starting point for fresh indices even
    # though nothing in a cleared table references the old ones anymore.
    # A real, confirmed case (a Truck-kun font asset with zero pre-existing
    # glyphs) has no row to copy at all — _schema_glyph_template() recovers
    # the same field set straight from the object's own TypeTree schema
    # instead, so an extra field like m_ClassDefinitionType still gets
    # populated and font_obj.patch() below doesn't KeyError on it.
    glyph_template = glyph_table[0] if glyph_table else _schema_glyph_template(font_obj)
    next_glyph_index = max((g.get("m_Index", 0) for g in glyph_table), default=0) + 1

    clear_atlas_pixels = False
    if mode == MODE_REPLACE_ALL:
        glyph_table = []
        char_table = []
        # NOT sized here yet — real reported request: reusing this font
        # asset's OWN pre-existing atlas_w/atlas_h for a full rebuild means
        # either wasting VRAM on a needlessly gigantic texture (if the new
        # character set is much smaller than whatever the atlas used to
        # hold) or paying for several wasted power-of-two growth steps mid-
        # generation (if it's much bigger). Left empty here and properly
        # sized further down, once msdf-atlas-gen's own "-pots" pass has
        # already told us the tightest fit for the ACTUAL requested set at
        # the ACTUAL point size/pxrange being used this time.
        free_rects = []
        used_rects = []
        existing = set()
        clear_atlas_pixels = True
    else:
        existing = _existing_codepoints(full)

    to_generate = []
    for cp in characters:
        if cp in existing:
            if mode == MODE_REPLACE_ENTERED:
                _remove_character(char_table, glyph_table, free_rects, used_rects, cp)
                to_generate.append(cp)
            else:
                result.results.append(NewCharacterResult(cp, False, tr("уже есть в этом SDF")))
        elif covered is not None and cp not in covered:
            result.results.append(NewCharacterResult(cp, False, tr("отсутствует в ttf/otf")))
        else:
            to_generate.append(cp)

    if not to_generate:
        return result

    components = resolve_sdf_components(font_obj)
    if components.texture_obj is None:
        raise SDFGenerationError(tr("не найдена текстура атласа: {texture_error}", texture_error=components.texture_error))

    pxrange = pxrange_override or resolve_gradient_scale(components.material_obj)
    # See _add_characters_legacy_schema's identical comment for the full
    # reasoning on point_size_fit being its own explicit flag.
    fit_atlas = None
    if point_size_fit and atlas_width_override is not None:
        point_size = _find_max_point_size_for_atlas(
            font_file_path, to_generate, pxrange, atlas_width_override, atlas_height_override,
        )
    elif point_size_fit:
        point_size, fit_atlas = _fit_to_texture(
            font_file_path, to_generate, pxrange, atlas_w, atlas_h, full["m_FaceInfo"].get("m_PointSize") or 0,
        )
    else:
        point_size = point_size_override or full["m_FaceInfo"]["m_PointSize"]

    tex_data = components.texture_obj.parse_as_object()
    # Real case found while sweep-testing other games: a font asset's own
    # "- Fallback" companion (TMP auto-creates one per font, whether or not
    # the game ever actually renders any text through it) can carry a
    # genuinely degenerate atlas Texture2D — m_Width/m_Height both 0, no
    # inline pixel data, an empty m_StreamData.path — alongside an empty
    # glyph table. Calling tex_data.image on THAT unconditionally (the old
    # behavior for every non-REPLACE_ALL mode) tries to load a streamed
    # resource from a blank path, which resolves badly deep inside UnityPy's
    # own dependency loader and surfaces as a confusing PermissionError
    # naming the whole game folder — nothing about that trace points at the
    # real cause. Since a 0×0 texture has no real pixel data to read in the
    # first place, treating it exactly like clear_atlas_pixels (a fresh
    # blank canvas at the font asset's own declared atlas size) is both
    # simpler than special-casing an error AND makes generation actually
    # WORK for this case — there was never anything to preserve. Only
    # refuse outright if the glyph table still isn't empty despite the
    # texture being degenerate — that combination means the existing
    # m_GlyphRect entries reference pixels that provably don't exist
    # anywhere, a genuine data inconsistency this tool shouldn't paper over
    # by guessing.
    texture_is_empty = tex_data.m_Width == 0 or tex_data.m_Height == 0
    if texture_is_empty and glyph_table:
        raise SDFGenerationError(
            tr("Текстура атласа этого шрифта пуста (0×0), но таблица глифов не пуста — данные этого шрифта "
               "повреждены или несовместимы.")
        )

    # Fixed atlas dimensions are only ever passed for MODE_REPLACE_ALL (the
    # only mode with no pre-existing content a resize could conflict with) —
    # already enforced by add_characters_to_font_asset()'s own validation
    # above it, re-checked here defensively since this function has its own
    # direct access to `mode`.
    atlas_dims_arg = (
        (atlas_width_override, atlas_height_override)
        if mode == MODE_REPLACE_ALL and atlas_width_override is not None
        else fit_atlas
    )

    with tempfile.TemporaryDirectory(prefix="ustudio_sdf_") as tmp:
        tmp_path = Path(tmp)
        try:
            atlas_json, atlas_png = _run_msdf_atlas_gen(
                font_file_path, to_generate, point_size, pxrange, tmp_path, atlas_dimensions=atlas_dims_arg,
            )
        except SDFGenerationError as e:
            # One whole-run failure, stated once (see AddCharactersResult.run_error) — not a
            # copy of the same reason on every requested character.
            result.run_error = str(e)
            for cp in to_generate:
                result.results.append(NewCharacterResult(cp, False, _RUN_FAILED_REASON))
            return result

        if mode == MODE_REPLACE_ALL:
            # msdf-atlas-gen was invoked with either "-pots" (auto-fit) or
            # "-dimensions W H" (atlas_dims_arg, a fixed size) — see
            # _run_msdf_atlas_gen — and its own JSON output reports back the
            # atlas size IT actually used, which for the fixed-size case is
            # just atlas_dims_arg echoed back (already-verified msdf-atlas-gen
            # behavior: it fails cleanly instead of returning a DIFFERENT size
            # than what was requested). Confirmed against a real invocation:
            # atlas["width"]/["height"]). Using that as the STARTING canvas
            # for our own packing loop below — rather than this font asset's
            # old, unrelated atlas_w/atlas_h — is what actually avoids the
            # "gigantic texture" waste. This is only ever a starting point,
            # not a guarantee: our own bin-packer (_find_free_rect_index/
            # _crop_padded_bitmap below) can pack slightly differently than
            # msdf-atlas-gen's internal layout, so the EXISTING grow-on-
            # demand fallback (_next_atlas_size/_grow_atlas_canvas_topdown,
            # already relied on for plain "add") stays as the safety net for
            # that gap rather than trusting this number blindly.
            fitted = atlas_json.get("atlas") or {}
            if "width" in fitted and "height" in fitted:
                atlas_w, atlas_h = int(fitted["width"]), int(fitted["height"])
            # No free_rects/our-own-packer pass for this mode at all anymore
            # — see replace_all_direct_layout below for why.
            free_rects = []
            # See _apply_replace_all_face_metrics()'s own docstring — a full font
            # swap needs the font ASSET's own face-wide line/ascender/descender
            # metrics updated too, not just its glyphs.
            declared = _resolve_declared_point_size(
                match_original_height, orig_em_heights, atlas_json, point_size, pxrange, result)
            _apply_replace_all_face_metrics(
                full["m_FaceInfo"], atlas_json, point_size, legacy=False,
                declared_point_size=declared, original_layout=orig_layout,
            )
            _zero_bold_spacing(full, declared, result)

        # REAL BUG, found via a real ~180-character generation (not caught by
        # this feature's own earlier small-fixture tests, which only ever
        # used 3-4 characters — exactly the "small fixture hides a bug that
        # only appears at real scale" trap this project has hit before):
        # MODE_REPLACE_ALL used to still crop each glyph out of msdf-atlas-gen's
        # own atlas_png via _crop_padded_bitmap(), then re-pack it into a
        # BLANK canvas via this project's OWN, independent shelf-packer
        # (_find_free_rect_index/_grow_atlas_canvas) — a completely separate
        # layout algorithm from whatever msdf-atlas-gen itself used to
        # confirm the character set fits within atlas_w×atlas_h (via -pots
        # OR the -dimensions override, and — since the auto-point-size
        # feature was added — the size that _find_max_point_size_for_atlas()
        # itself already verified fits). The two packers can and do disagree
        # at real scale — this project's own is less space-efficient — so a
        # batch msdf-atlas-gen ALREADY proved fits inside an EXPLICITLY
        # requested fixed size (whether picked directly or found by the
        # point-size search) could still trip this project's OWN grow-on-
        # demand fallback and silently end up LARGER than what was actually
        # verified to fit — defeating the entire point of a "fixed" atlas
        # size (and, for the point-size search specifically, making its own
        # "largest size that fits" guarantee meaningless downstream).
        #
        # Root-cause fix, not a narrower band-aid (e.g. "fail instead of
        # growing when fixed"): MODE_REPLACE_ALL has NO pre-existing atlas
        # content to coexist with (the whole reason this project built its
        # OWN packer in the first place is to fit new glyphs into an
        # EXISTING atlas's leftover free space for add/replace_entered,
        # which msdf-atlas-gen has no visibility into) — so for this mode
        # specifically, there is no need to re-pack anything at all. The
        # ENTIRE atlas_png IS the exact, already-verified-to-fit final
        # layout; every glyph's own atlasBounds already gives its exact
        # placement within it. Repacking-then-discarding that layout only
        # ever throws away a strictly-better arrangement in favor of a
        # strictly-worse one that can (and, at real scale, does) need more
        # room. Reusing atlas_png directly is simultaneously the fix for the
        # silent-growth bug AND strictly cheaper (no per-glyph crop+paste,
        # no packing search).
        replace_all_direct_layout = mode == MODE_REPLACE_ALL
        if replace_all_direct_layout:
            atlas_img = _sdf_png_to_atlas_image(atlas_png)
        else:
            atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0)) if (clear_atlas_pixels or texture_is_empty) \
                else tex_data.image.convert("RGBA")

        by_codepoint = {g["unicode"]: g for g in atlas_json["glyphs"]}
        total = len(to_generate)
        for i, cp in enumerate(to_generate):
            if should_cancel and should_cancel():
                break
            if progress_cb:
                progress_cb(i, total)

            entry = by_codepoint.get(cp)
            if entry is None:
                result.results.append(NewCharacterResult(cp, False, tr("шрифт не смог сгенерировать глиф")))
                continue

            if "atlasBounds" not in entry or "planeBounds" not in entry:
                # A real bug hit on the first real multi-character batch, not
                # anticipated in advance: msdf-atlas-gen omits both bounds
                # entirely for a glyph with no visible ink at all — space
                # being the obvious, near-always-requested example, but any
                # whitespace/invisible codepoint the font recognizes behaves
                # the same way. `entry["atlasBounds"]` raised a bare KeyError
                # the first time this was hit. Confirmed against a REAL
                # shipped font asset's own space-character entry (not
                # guessed): TMP itself stores exactly this case as an
                # all-zero Metrics/GlyphRect except m_HorizontalAdvance
                # (still real — space still needs to move the cursor) and
                # consumes zero atlas space — matches TMP's own
                # AddSynthesizedCharacter() convention for invisible
                # characters. Reproduced here rather than skipped as an
                # error, since requesting space is entirely legitimate.
                metrics = {
                    "m_Width": 0.0, "m_Height": 0.0,
                    "m_HorizontalBearingX": 0.0, "m_HorizontalBearingY": 0.0,
                    "m_HorizontalAdvance": entry.get("advance", 0.0) * point_size,
                }
                rect = {"m_X": 0, "m_Y": 0, "m_Width": 0, "m_Height": 0}
            elif replace_all_direct_layout:
                # The pixel data is ALREADY at exactly this position in
                # atlas_img (== the whole converted atlas_png) — see
                # _sdf_png_to_atlas_image()'s own docstring for the Y-axis
                # derivation proving this rect is the SAME position
                # _crop_padded_bitmap()/the paste destination below would
                # have computed, just without ever cropping or pasting.
                ab = entry["atlasBounds"]
                # The PADDED box is what this glyph occupies in the atlas (packing
                # bookkeeping); the glyph table gets the TIGHT box instead — see
                # _tight_glyph_geometry().
                used_rects.append({
                    "m_X": int(round(ab["left"])), "m_Y": int(round(ab["bottom"])),
                    "m_Width": round(ab["right"] - ab["left"]), "m_Height": round(ab["top"] - ab["bottom"]),
                })
                rect, metrics = _tight_glyph_geometry(entry, point_size, pxrange)
            else:
                patch = _crop_padded_bitmap(atlas_png, entry)
                padded_w, padded_h = patch.size
                # Reserve the empty gutter around the padded box too (see _GLYPH_GUTTER_PX):
                # msdf-atlas-gen already leaves it in its own layout, this path has to
                # leave it in ours.
                alloc_w, alloc_h = padded_w + 2 * _GLYPH_GUTTER_PX, padded_h + 2 * _GLYPH_GUTTER_PX

                idx = _find_free_rect_index(free_rects, alloc_w, alloc_h, atlas_w, atlas_h)
                while idx is None:
                    # Grow one axis at a time (the currently-smaller one
                    # first) rather than always bumping BOTH width and
                    # height to the next standard size together — a real
                    # reported complaint: doubling both dimensions at once
                    # can quadruple total atlas area when growing just one
                    # axis would have been enough to fit the pending glyph.
                    # This also fixes a latent bug in the old "both together"
                    # approach: if one axis was already at the largest
                    # standard size but the other still had room, the old
                    # code computed next_size from max(atlas_w, atlas_h) and
                    # gave up entirely instead of growing the axis that
                    # could still grow. The loop still ends up growing both
                    # axes across successive iterations if one alone isn't
                    # enough — this only changes how much area gets added
                    # per step, not whether growth eventually succeeds.
                    next_w = _next_atlas_size(atlas_w)
                    next_h = _next_atlas_size(atlas_h)
                    if next_w is None and next_h is None:
                        break
                    grow_width = next_w is not None and (next_h is None or atlas_w <= atlas_h)
                    new_w = next_w if grow_width else atlas_w
                    new_h = atlas_h if grow_width else next_h
                    atlas_img = _grow_atlas_canvas(atlas_img, free_rects, atlas_w, atlas_h, new_w, new_h)
                    atlas_w, atlas_h = new_w, new_h
                    idx = _find_free_rect_index(free_rects, alloc_w, alloc_h, atlas_w, atlas_h)
                if idx is None:
                    result.results.append(NewCharacterResult(
                        cp, False, tr("недостаточно места даже при максимальном размере атласа ({atlas_w}×{atlas_h})", atlas_w=atlas_w, atlas_h=atlas_h)
                    ))
                    continue
                placed = _consume_free_rect(free_rects, idx, alloc_w, alloc_h)
                used_rects.append(dict(placed))

                # The padded box sits inside the allocation, one gutter in from each side.
                box_x = placed["m_X"] + _GLYPH_GUTTER_PX
                box_y = placed["m_Y"] + _GLYPH_GUTTER_PX
                dest_upper = atlas_h - box_y - padded_h
                atlas_img.paste(patch, (box_x, dest_upper))

                # Where the glyph's own msdf-atlas-gen coordinates ended up: the crop's
                # bottom-left corner (in msdf-atlas-gen's bottom-up Y) moved to (box_x, box_y).
                crop_left, crop_upper, _, _ = _padded_crop_box(entry, atlas_json["atlas"]["height"])
                crop_bottom = atlas_json["atlas"]["height"] - crop_upper - padded_h
                rect, metrics = _tight_glyph_geometry(
                    entry, point_size, pxrange,
                    offset_x=box_x - crop_left, offset_y=box_y - crop_bottom,
                )

            glyph_index = next_glyph_index
            next_glyph_index += 1
            glyph_table.append(_new_glyph_dict(glyph_template, glyph_index, metrics, rect))
            char_table.append({
                "m_ElementType": 1, "m_Unicode": cp, "m_GlyphIndex": glyph_index, "m_Scale": 1.0,
            })
            result.results.append(NewCharacterResult(cp, True))

    if progress_cb:
        progress_cb(total, total)

    result.new_atlas_size = (atlas_w, atlas_h)

    if not any(r.added for r in result.results):
        return result

    result.atlas_preview_image = atlas_img

    def _commit():
        tex_data.set_image(atlas_img, target_format=tex_data.m_TextureFormat)
        components.texture_obj.patch(tex_data)

        full["m_GlyphTable"] = glyph_table
        full["m_CharacterTable"] = char_table
        full["m_FreeGlyphRects"] = free_rects
        full["m_UsedGlyphRects"] = used_rects
        if result.atlas_resized:
            full["m_AtlasWidth"] = atlas_w
            full["m_AtlasHeight"] = atlas_h
            _patch_material_texture_size(components.material_obj, atlas_w, atlas_h)
        # See _patch_material_gradient_scale()'s own docstring for why this
        # runs unconditionally (not just when result.atlas_resized) -- pxrange
        # is a shared, atlas-wide runtime decode parameter with no per-glyph
        # override, so it has to stay in sync with whatever THIS generation
        # actually baked regardless of whether the atlas itself grew.
        _patch_material_gradient_scale(components.material_obj, pxrange)
        font_obj.patch(full)

    if auto_commit:
        _commit()
    else:
        result.commit = _commit

    return result
