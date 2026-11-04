"""SDF mapping file (`sdf_map.txt`) — one file that says which source .ttf/.otf
feeds which TMP_FontAsset, with which settings and which characters. Dropped
into a patch folder it drives on-the-fly SDF generation for GUI "import into
environment" and CLI `import` alike (both go through load_sdf_map_jobs()).

Grammar, one mapping per line:

    # comment
    default: mode=add, range=8, chars=my_chars.txt
    "Arial SDF", "Some SDF" = font.ttf
    level0:55, resources.assets:120 = font2.ttf
    "Pixel SDF" = "my fonts/pixel.ttf", size=24, range=4
    "Rebaked SDF" = font5.ttf, mode=full, atlas=512x512, chars="ABCabc"

Left of `=`: comma-separated targets. A target is a font DISPLAY NAME (matches
every loaded TMP_FontAsset with that exact name) or a `source:path_id` /
`folder/source:path_id` reference (core.identity.parse_ref() syntax). Quotes
are needed only when a name contains a comma or would itself parse as a
reference.

Right of `=`: the font file first (quotes optional, needed when the path
contains a comma), then any of these `key=value` options, any order:

    size=<pt>|fit    font size to bake at (default: the font's own size);
                     `fit` = the largest size that fits the font's current
                     texture (the texture grows instead of shrinking the glyphs
                     below the font's original size). mode=full only
    match_height=on|off  make the new glyphs as tall on screen as the original
                     ones (default: on). mode=full only
    range=<px>       edge sharpness / SDF spread (default: the font's own).
                     mode=full only
    add_chars=on|off  on (default) also generates, from the new font, the
                     characters the font asset already has but `chars` does not
                     name, so a full replacement does not lose them; off = only
                     the listed characters. mode=full only
    mode=<m>         add (default) | replace | full
                     add = only characters missing from the font;
                     replace = regenerate the listed characters;
                     full = rebuild the whole font from the new ttf/otf
    atlas=<W>x<H>    pins the atlas to this size (powers of two, e.g. 1024x512);
                     normally the atlas is chosen automatically and grows as
                     needed. mode=full only
    chars=<spec>     characters to generate. "text" in double quotes is the
                     characters themselves (\\" is a quote, \\\\ a backslash,
                     \\uXXXX / \\UXXXXXXXX a code point); without quotes it is
                     the name of a text file (relative to the map file),
                     e.g. chars=my_chars.txt

Characters fall back, in order, to: this line's chars= -> `default:` line's
chars= -> a `chars.txt` next to the map file. A line with none of the three
is an error.

`default:` (at most one per file, anywhere) gives values for every line that
does not set its own. A relative font/chars path resolves against the map
file's own folder, so a map and its fonts can be moved around together.

Cascade applied by the callers: line -> `default:` -> the GUI dialog (none in
the CLI) -> built-in (mode add, font's own size and range, match_height=on).
`default:` values for size/match_height/range/atlas/add_chars only reach mode=full lines
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from core.identity import ObjectRefError, parse_ref

SDF_MAP_FILENAME = "sdf_map.txt"
SDF_CHARS_FILENAME = "chars.txt"

# Short names in the file -> core.sdf_generator.MODE_* values (asserted equal in
# tests/test_sdf_map.py so the two can't drift). Kept as literals so scanning a
# patch folder does not have to import the whole generator (PIL and friends).
MODES = {"add": "add", "replace": "replace_entered", "full": "replace_all"}
_MODE_FULL = MODES["full"]
_ATLAS_SIZES = (8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192)  # core.sdf_generator._STANDARD_ATLAS_SIZES

class FontMapError(Exception):
    """A syntax or semantic error in an SDF map — always carries enough
    context (file, line number) to fix by hand."""


@dataclass
class TargetSpec:
    kind: str  # "name" | "ref"
    raw: str
    name: Optional[str] = None
    source: Optional[str] = None
    path_id: Optional[int] = None


@dataclass
class _Options:
    """The key=value part, shared by a mapping line and the `default:` line."""
    point_size: Optional[float] = None
    size_fit: bool = False
    match_height: Optional[bool] = None
    pxrange: Optional[float] = None
    mode: Optional[str] = None
    atlas: Optional[Tuple[int, int]] = None
    characters: Optional[List[int]] = None
    add_missing: Optional[bool] = None


@dataclass
class FontMapEntry:
    targets: List[TargetSpec]
    font_path: Path
    line_no: int
    raw_line: str
    point_size: Optional[float] = None
    size_fit: bool = False
    match_height: Optional[bool] = None
    pxrange: Optional[float] = None
    mode: Optional[str] = None
    atlas_width: Optional[int] = None
    atlas_height: Optional[int] = None
    characters: Optional[List[int]] = None
    add_missing: Optional[bool] = None
    # Which of the mode=full-only settings (see _FULL_ONLY_GROUPS) were filled in from the `default:` line
    # rather than written on the line itself. A default never makes a font fail: if the font's final mode
    # turns out not to be full, default-derived values are ignored; only the line's OWN values are an error.
    from_default: frozenset = frozenset()


@dataclass
class MapDefaults:
    """What a `default:` line set (all None when the file has none)."""
    point_size: Optional[float] = None
    size_fit: bool = False
    match_height: Optional[bool] = None
    pxrange: Optional[float] = None
    mode: Optional[str] = None
    atlas: Optional[Tuple[int, int]] = None
    characters: Optional[List[int]] = None
    add_missing: Optional[bool] = None


@dataclass
class FontMapFile:
    path: Path
    entries: List[FontMapEntry]
    defaults: MapDefaults


def text_to_codepoints(text: str) -> List[int]:
    """Unique code points in order; line breaks and tabs are not characters here."""
    seen = set()
    out: List[int] = []
    for ch in text:
        if ch in ("\n", "\r", "\t"):
            continue
        cp = ord(ch)
        if cp not in seen:
            seen.add(cp)
            out.append(cp)
    return out


def read_chars_file(path: Path) -> List[int]:
    return text_to_codepoints(Path(path).read_text(encoding="utf-8-sig"))


def _split_top_level_commas(text: str) -> List[str]:
    """Splits on commas OUTSIDE double quotes; inside quotes `\\"` and `\\\\`
    are skipped as pairs, so an escaped quote does not end the string."""
    parts: List[str] = []
    buf: List[str] = []
    in_quotes = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quotes and ch == "\\" and i + 1 < len(text) and text[i + 1] in ('"', "\\"):
            buf.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "," and not in_quotes:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _unquote(text: str) -> str:
    """Strips one pair of surrounding quotes, raw (no escapes: paths and names)."""
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


_ESCAPE_RE = re.compile(r'\\(?:u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8})|(["\\]))')


def _unescape_chars(inner: str, line_no: int) -> str:
    """`\\"` -> `"`, `\\\\` -> `\\`, `\\uXXXX`/`\\UXXXXXXXX` -> that code point.
    Any other backslash is an error — a literal one must be written `\\\\`."""
    def repl(m: "re.Match") -> str:
        if m.group(1) or m.group(2):
            try:
                return chr(int(m.group(1) or m.group(2), 16))
            except (ValueError, OverflowError):
                raise FontMapError(f"line {line_no}: invalid code point {m.group(0)!r} in chars=")
        return m.group(3)
    out = _ESCAPE_RE.sub(repl, inner)
    # Whatever backslash is left was not part of a valid escape.
    stray = _ESCAPE_RE.sub("", inner)
    if "\\" in stray:
        raise FontMapError(
            f"line {line_no}: a backslash in chars=\"...\" must be written \\\\ "
            f"(other escapes: \\\" \\uXXXX \\UXXXXXXXX)"
        )
    return out


def _parse_chars_value(value: str, line_no: int, base_dir: Path) -> List[int]:
    if value.startswith('"'):
        if len(value) < 2 or not value.endswith('"'):
            raise FontMapError(f"line {line_no}: unterminated quoted chars=: {value!r}")
        codepoints = text_to_codepoints(_unescape_chars(value[1:-1], line_no))
        if not codepoints:
            raise FontMapError(f"line {line_no}: chars=\"\" holds no characters")
        return codepoints
    if not value:
        raise FontMapError(f"line {line_no}: empty chars= (characters go in double quotes, or give a file name)")
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        raise FontMapError(
            f"line {line_no}: chars file not found: {path} "
            f"(to give the characters themselves, wrap them in double quotes: chars=\"abc\")"
        )
    codepoints = read_chars_file(path)
    if not codepoints:
        raise FontMapError(f"line {line_no}: {path} holds no characters")
    return codepoints


_ATLAS_RE = re.compile(r"^(\d+)\s*[xX×]\s*(\d+)$")
_VALID_KEYS = "size, range, mode, atlas, chars, match_height, add_chars"


def _parse_options(items: Sequence[str], line_no: int, base_dir: Path) -> _Options:
    opts = _Options()
    for extra in items:
        key, sep, value = extra.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if not sep:
            raise FontMapError(f"line {line_no}: expected 'key=value' ({_VALID_KEYS}), got {extra!r}")
        if key == "size" and value.lower() == "fit":
            opts.size_fit = True
            opts.point_size = None
        elif key == "match_height":
            if value.lower() not in ("on", "off"):
                raise FontMapError(f"line {line_no}: match_height={value!r} must be on or off")
            opts.match_height = value.lower() == "on"
        elif key == "add_chars":
            if value.lower() not in ("on", "off"):
                raise FontMapError(f"line {line_no}: add_chars={value!r} must be on or off")
            opts.add_missing = value.lower() == "on"
        elif key in ("size", "range"):
            try:
                number = float(value)
            except ValueError:
                raise FontMapError(f"line {line_no}: {key}={value!r} is not a number")
            if number <= 0:
                raise FontMapError(f"line {line_no}: {key} must be positive, got {value!r}")
            if key == "size":
                opts.point_size = number
                opts.size_fit = False
            else:
                opts.pxrange = number
        elif key == "mode":
            if value not in MODES:
                raise FontMapError(f"line {line_no}: mode={value!r} is not one of {', '.join(MODES)}")
            opts.mode = MODES[value]
        elif key == "atlas":
            m = _ATLAS_RE.match(value)
            if not m:
                raise FontMapError(f"line {line_no}: atlas={value!r} must look like 1024x512")
            w, h = int(m.group(1)), int(m.group(2))
            if w not in _ATLAS_SIZES or h not in _ATLAS_SIZES:
                raise FontMapError(
                    f"line {line_no}: atlas sizes must be powers of two "
                    f"({', '.join(map(str, _ATLAS_SIZES))}), got {w}x{h}"
                )
            opts.atlas = (w, h)
        elif key == "chars":
            opts.characters = _parse_chars_value(value, line_no, base_dir)
        else:
            raise FontMapError(f"line {line_no}: unknown option {key!r} — expected one of {_VALID_KEYS}")
    return opts


def _parse_target_spec(raw: str) -> TargetSpec:
    """Quotes are optional for a name; they matter only for a name with a
    comma, or one that would itself parse as a source:path_id reference."""
    text = raw.strip()
    if not text:
        raise FontMapError(f"empty target in list: {raw!r}")
    if text.startswith('"'):
        if not text.endswith('"') or len(text) < 2:
            raise FontMapError(f"unterminated quoted name: {raw!r}")
        return TargetSpec(kind="name", raw=raw, name=text[1:-1])
    try:
        source, path_id = parse_ref(text)
    except ObjectRefError:
        # Not a reference at all (no colon, or nothing integer after the last
        # one — "Chapter: Intro SDF"): the whole trimmed text is a name.
        return TargetSpec(kind="name", raw=raw, name=text)
    if source is None:
        raise FontMapError(
            f"target {raw!r} is a bare number, not source:path_id — quote it "
            f'("{text}") to match a font literally named that number, or '
            f"give a full source:path_id"
        )
    return TargetSpec(kind="ref", raw=raw, source=source, path_id=path_id)


_DEFAULT_LINE_RE = re.compile(r"^default:(\s|$)", re.IGNORECASE)


def _is_default_line(stripped: str) -> bool:
    # `default:12` would be a source named "default" — only `default:` followed
    # by whitespace/end is the directive (a quoted name starts with `"`).
    return bool(_DEFAULT_LINE_RE.match(stripped))


def _parse_default_line(stripped: str, line_no: int, base_dir: Path) -> MapDefaults:
    body = stripped[len("default:"):]
    items = [p.strip() for p in _split_top_level_commas(body) if p.strip()]
    opts = _parse_options(items, line_no, base_dir)
    return MapDefaults(point_size=opts.point_size, size_fit=opts.size_fit, match_height=opts.match_height,
                       pxrange=opts.pxrange, mode=opts.mode, atlas=opts.atlas, characters=opts.characters,
                       add_missing=opts.add_missing)


def parse_font_map_line(line: str, line_no: int, base_dir: Path) -> Optional[FontMapEntry]:
    """One mapping line (None for blank/comment). `default:` is NOT handled
    here — see parse_font_map_file()."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in stripped:
        raise FontMapError(f"line {line_no}: missing '=' separating targets from font file: {line!r}")
    # FIRST '=': the right-hand side legitimately holds more of them (size=...).
    lhs, _, rhs = stripped.partition("=")
    parts = [p.strip() for p in _split_top_level_commas(rhs) if p.strip()]
    if not parts:
        raise FontMapError(f"line {line_no}: empty font file path")
    font_path = Path(_unquote(parts[0]))
    if not font_path.is_absolute():
        font_path = base_dir / font_path
    opts = _parse_options(parts[1:], line_no, base_dir)
    targets = [_parse_target_spec(t) for t in _split_top_level_commas(lhs) if t.strip()]
    if not targets:
        raise FontMapError(f"line {line_no}: no targets given before '='")
    return FontMapEntry(
        targets=targets, font_path=font_path, line_no=line_no, raw_line=line,
        point_size=opts.point_size, size_fit=opts.size_fit, match_height=opts.match_height,
        pxrange=opts.pxrange, mode=opts.mode,
        atlas_width=opts.atlas[0] if opts.atlas else None,
        atlas_height=opts.atlas[1] if opts.atlas else None,
        characters=opts.characters, add_missing=opts.add_missing,
    )


# The mode=full-only settings, as one unit each (size and "fit" are one setting): the names used in
# `from_default` sets.
_FULL_ONLY_GROUPS = ("size", "match_height", "range", "atlas", "add_chars")


def _set_groups(point_size, size_fit, match_height, pxrange, atlas_width, add_missing) -> frozenset:
    """Which full-only settings carry a value."""
    out = set()
    if point_size is not None or size_fit:
        out.add("size")
    if match_height is not None:
        out.add("match_height")
    if pxrange is not None:
        out.add("range")
    if atlas_width is not None:
        out.add("atlas")
    if add_missing is not None:
        out.add("add_chars")
    return frozenset(out)


def _apply_defaults(entry: FontMapEntry, d: MapDefaults) -> FontMapEntry:
    mode = entry.mode if entry.mode is not None else d.mode
    # size / match / range / atlas belong to mode=full lines only: a default for them must not turn
    # every add/replace line into a "only with mode=full" error.
    full_ok = mode in (None, _MODE_FULL)
    atlas_w, atlas_h = entry.atlas_width, entry.atlas_height
    if atlas_w is None and d.atlas is not None and full_ok:
        atlas_w, atlas_h = d.atlas
    if entry.point_size is not None or entry.size_fit:
        point_size, size_fit = entry.point_size, entry.size_fit
    elif full_ok:
        point_size, size_fit = d.point_size, d.size_fit
    else:
        point_size, size_fit = None, False
    match = entry.match_height if entry.match_height is not None else (d.match_height if full_ok else None)
    own = _set_groups(entry.point_size, entry.size_fit, entry.match_height, entry.pxrange,
                      entry.atlas_width, entry.add_missing)
    pxrange = entry.pxrange if entry.pxrange is not None else (d.pxrange if full_ok else None)
    add_missing = entry.add_missing if entry.add_missing is not None else (d.add_missing if full_ok else None)
    merged = _set_groups(point_size, size_fit, match, pxrange, atlas_w, add_missing)
    return replace(
        entry,
        from_default=merged - own,
        point_size=point_size, size_fit=size_fit, match_height=match,
        pxrange=pxrange,
        mode=mode, atlas_width=atlas_w, atlas_height=atlas_h,
        characters=entry.characters if entry.characters is not None else d.characters,
        add_missing=add_missing,
    )


def parse_font_map_file(path: Path) -> FontMapFile:
    """Parses `path`, applies the `default:` line to every entry that lacks a
    value and fills missing characters from a sibling chars.txt. Every error
    names the file."""
    path = Path(path)
    base_dir = path.resolve().parent
    entries: List[FontMapEntry] = []
    defaults: Optional[MapDefaults] = None
    try:
        with open(path, encoding="utf-8-sig") as f:
            for i, line in enumerate(f, 1):
                stripped = line.strip()
                if _is_default_line(stripped):
                    if defaults is not None:
                        raise FontMapError(f"line {i}: a second 'default:' line (only one per file)")
                    defaults = _parse_default_line(stripped, i, base_dir)
                    continue
                entry = parse_font_map_line(line, i, base_dir)
                if entry is not None:
                    entries.append(entry)

        defaults = defaults or MapDefaults()
        entries = [_apply_defaults(e, defaults) for e in entries]

        sibling: Optional[List[int]] = None
        sibling_path = base_dir / SDF_CHARS_FILENAME
        for idx, e in enumerate(entries):
            if e.characters is not None:
                continue
            if sibling is None and sibling_path.is_file():
                sibling = read_chars_file(sibling_path)
                if not sibling:
                    raise FontMapError(f"{sibling_path} holds no characters")
            if not sibling:
                raise FontMapError(
                    f"line {e.line_no}: no characters to generate — give chars= on the line or in "
                    f"'default:', or put a {SDF_CHARS_FILENAME} next to the map"
                )
            entries[idx] = replace(e, characters=sibling)
    except FontMapError as err:
        raise FontMapError(f"{path}: {err}") from None
    return FontMapFile(path=path, entries=entries, defaults=defaults)


def find_sdf_maps(root: Path) -> List[Path]:
    """Every sdf_map.txt under `root`, recursively (same as patch files)."""
    return sorted(p for p in Path(root).rglob(SDF_MAP_FILENAME) if p.is_file())


@dataclass
class ResolvedMapping:
    row: dict
    font_path: Path
    point_size: Optional[float] = None
    size_fit: bool = False
    match_height: Optional[bool] = None
    pxrange: Optional[float] = None
    mode: Optional[str] = None
    atlas_width: Optional[int] = None
    atlas_height: Optional[int] = None
    characters: Optional[List[int]] = None
    add_missing: Optional[bool] = None
    from_default: frozenset = frozenset()  # see FontMapEntry.from_default

    @property
    def is_fully_specified(self) -> bool:
        """Everything a GUI would ask about is fixed by the map (line or `default:`): the mode and — only
        for mode=full, the one mode where size and range can be set — the size and the range."""
        if self.mode is None:
            return False
        if self.mode == _MODE_FULL:
            return (self.point_size is not None or self.size_fit) and self.pxrange is not None
        return True


def resolve_font_map(entries: List[FontMapEntry], rows: list) -> Tuple[List[ResolvedMapping], List[str]]:
    """Resolves every entry's targets against `rows` (RowItem-shaped dicts,
    already through core.identity.prefer_canonical_registration() where the
    caller has an Environment) into ResolvedMappings ready for
    add_characters_to_font_asset().

    Policy (confirmed with the user):
    - A NAME matching several loaded TMP_FontAssets applies to ALL of them; a
      source:path_id reference is the way to target just one.
    - The SAME object in two entries with a different font file, size, range,
      mode, atlas or character set is a hard error listing every conflict — a
      silent "last one wins" is an easy mistake to miss in a hand-edited map.
    - An entry with no value for a field never conflicts with one that has
      it (None = no opinion); the later value fills the gap.

    Returns (mappings, warnings); `warnings` lists targets that matched
    nothing (typo'd name, stale path_id) — the caller decides if that is fatal."""
    from core.sdf_resolver import SDF_FONT_SCRIPT_NAME
    from core.object_preview import get_row_name, get_row_script_name
    from core.identity import format_ref, resolve_ref

    @dataclass
    class _Accum:
        row: dict
        font_path: Path
        point_size: Optional[float]
        size_fit: bool
        match_height: Optional[bool]
        pxrange: Optional[float]
        mode: Optional[str]
        atlas_width: Optional[int]
        atlas_height: Optional[int]
        characters: Optional[List[int]]
        line_no: int
        add_missing: Optional[bool] = None
        from_default: frozenset = frozenset()

    resolved: dict = {}  # (source, path_id) -> _Accum
    conflicts: List[str] = []
    warnings: List[str] = []

    for entry in entries:
        for spec in entry.targets:
            if spec.kind == "ref":
                try:
                    matches = [resolve_ref(rows, spec.path_id, spec.source)]
                except ObjectRefError as e:
                    warnings.append(f"line {entry.line_no}: {spec.raw!r}: {e}")
                    continue
            else:
                matches = [
                    r for r in rows
                    if get_row_script_name(r) == SDF_FONT_SCRIPT_NAME and get_row_name(r) == spec.name
                ]
                if not matches:
                    warnings.append(f"line {entry.line_no}: no TMP_FontAsset named {spec.name!r}")
                    continue

            for row in matches:
                key = (row["source"], row["path_id"])
                prev = resolved.get(key)
                if prev is None:
                    resolved[key] = _Accum(
                        row=row, font_path=entry.font_path,
                        point_size=entry.point_size, size_fit=entry.size_fit, match_height=entry.match_height,
                        pxrange=entry.pxrange, mode=entry.mode,
                        atlas_width=entry.atlas_width, atlas_height=entry.atlas_height,
                        characters=entry.characters, line_no=entry.line_no,
                        add_missing=entry.add_missing, from_default=entry.from_default,
                    )
                    continue
                diffs = []
                if prev.font_path != entry.font_path:
                    diffs.append(f"font {prev.font_path} vs {entry.font_path}")
                if entry.point_size is not None and prev.point_size is not None and entry.point_size != prev.point_size:
                    diffs.append(f"size {prev.point_size:g} vs {entry.point_size:g}")
                if (entry.size_fit and prev.point_size is not None) or (prev.size_fit and entry.point_size is not None):
                    diffs.append("size fit vs a fixed size")
                if (
                    entry.match_height is not None and prev.match_height is not None
                    and entry.match_height != prev.match_height
                ):
                    diffs.append("match_height")
                if entry.pxrange is not None and prev.pxrange is not None and entry.pxrange != prev.pxrange:
                    diffs.append(f"range {prev.pxrange:g} vs {entry.pxrange:g}")
                if entry.mode is not None and prev.mode is not None and entry.mode != prev.mode:
                    diffs.append(f"mode {prev.mode} vs {entry.mode}")
                if (
                    entry.atlas_width is not None and prev.atlas_width is not None
                    and (entry.atlas_width, entry.atlas_height) != (prev.atlas_width, prev.atlas_height)
                ):
                    diffs.append(
                        f"atlas {prev.atlas_width}x{prev.atlas_height} vs {entry.atlas_width}x{entry.atlas_height}"
                    )
                if (
                    entry.characters is not None and prev.characters is not None
                    and entry.characters != prev.characters
                ):
                    diffs.append("different characters")
                if (
                    entry.add_missing is not None and prev.add_missing is not None
                    and entry.add_missing != prev.add_missing
                ):
                    diffs.append("add_chars")
                if diffs:
                    conflicts.append(
                        f"{format_ref(row)} ({get_row_name(row)!r}): line {prev.line_no} vs "
                        f"line {entry.line_no} disagree on " + ", ".join(diffs)
                    )
                    continue
                # No disagreement: a later non-None value fills whatever the earlier one left unset.
                # A merged setting counts as default-derived only if no line wrote it explicitly.
                had_e = _set_groups(entry.point_size, entry.size_fit, entry.match_height, entry.pxrange,
                                    entry.atlas_width, entry.add_missing)
                had_p = _set_groups(prev.point_size, prev.size_fit, prev.match_height, prev.pxrange,
                                    prev.atlas_width, prev.add_missing)
                explicit = (had_e - entry.from_default) | (had_p - prev.from_default)
                resolved[key] = _Accum(
                    row=row, font_path=entry.font_path,
                    point_size=prev.point_size if entry.point_size is None else entry.point_size,
                    size_fit=prev.size_fit or entry.size_fit,
                    match_height=prev.match_height if entry.match_height is None else entry.match_height,
                    pxrange=prev.pxrange if entry.pxrange is None else entry.pxrange,
                    mode=prev.mode if entry.mode is None else entry.mode,
                    atlas_width=prev.atlas_width if entry.atlas_width is None else entry.atlas_width,
                    atlas_height=prev.atlas_height if entry.atlas_height is None else entry.atlas_height,
                    characters=prev.characters if entry.characters is None else entry.characters,
                    line_no=prev.line_no,
                    add_missing=prev.add_missing if entry.add_missing is None else entry.add_missing,
                    from_default=(had_e | had_p) - explicit,
                )

    if conflicts:
        raise FontMapError("conflicting font mappings:\n  " + "\n  ".join(conflicts))

    mappings = [
        ResolvedMapping(
            row=a.row, font_path=a.font_path, point_size=a.point_size, size_fit=a.size_fit,
            match_height=a.match_height, pxrange=a.pxrange, mode=a.mode,
            atlas_width=a.atlas_width, atlas_height=a.atlas_height, characters=a.characters,
            add_missing=a.add_missing, from_default=a.from_default,
        )
        for a in resolved.values()
    ]
    return mappings, warnings


@dataclass
class SdfMapJob:
    map_file: FontMapFile
    mappings: List[ResolvedMapping]


def load_sdf_map_jobs(map_paths: Sequence[Path], rows: list) -> Tuple[List[SdfMapJob], List[str]]:
    """Parses and resolves every map. One job per map that resolved to at least
    one target — kept separate because two maps in different folders may want
    different characters/fonts, and conflict detection only applies within one
    map. Returns (jobs, warnings); raises FontMapError (naming the file) on a
    syntax/conflict error."""
    jobs: List[SdfMapJob] = []
    warnings: List[str] = []
    for map_path in map_paths:
        map_file = parse_font_map_file(map_path)
        if not map_file.entries:
            continue
        try:
            mappings, warns = resolve_font_map(map_file.entries, rows)
        except FontMapError as err:
            raise FontMapError(f"{map_path}: {err}") from None
        warnings.extend(f"{Path(map_path).name}: {w}" for w in warns)
        if mappings:
            jobs.append(SdfMapJob(map_file=map_file, mappings=mappings))
    return jobs, warnings


@dataclass
class SdfFallback:
    """What applies to a target after its own line and the file's `default:`:
    the GUI dialog's choices, or (CLI) the built-in values. Size settings only
    ever apply to mode=full."""
    mode: str = "add"
    point_size: Optional[float] = None
    point_size_fit: bool = False
    match_height: bool = True
    pxrange: Optional[float] = None
    add_missing: bool = True


@dataclass
class EffectiveSdfSettings:
    mode: str
    point_size: Optional[float]
    point_size_fit: bool
    match_height: bool
    pxrange: Optional[float]
    atlas_width: Optional[int]
    atlas_height: Optional[int]
    add_missing: bool = True


def effective_settings(m: ResolvedMapping, fb: SdfFallback) -> EffectiveSdfSettings:
    """line/default (already merged into `m`) -> fallback. Raises FontMapError when the LINE ITSELF sets size,
    match_height, range, add_chars or an atlas for a mode other than full (decided per target because the
    final mode is only known here, after the fallback). Values that only came from `default:` and fallback
    values are simply ignored outside mode=full — so a line behaves the same whether it says mode=add or
    gets add from the fallback."""
    mode = m.mode if m.mode is not None else fb.mode
    if mode != _MODE_FULL:
        own = _set_groups(m.point_size, m.size_fit, m.match_height, m.pxrange, m.atlas_width,
                          m.add_missing) - m.from_default
        if "atlas" in own:
            raise FontMapError(f"atlas {m.atlas_width}x{m.atlas_height} is set, but the mode is not 'full'")
        if own:
            raise FontMapError("size/match_height/range/add_chars are set, but they only apply to mode 'full'")
        return EffectiveSdfSettings(
            mode=mode, point_size=None, point_size_fit=False, match_height=False,
            pxrange=None, atlas_width=None, atlas_height=None, add_missing=False,
        )
    own_size = m.point_size is not None or m.size_fit
    return EffectiveSdfSettings(
        mode=mode,
        point_size=m.point_size if own_size else fb.point_size,
        point_size_fit=m.size_fit if own_size else (fb.point_size_fit and fb.point_size is None),
        match_height=m.match_height if m.match_height is not None else fb.match_height,
        pxrange=m.pxrange if m.pxrange is not None else fb.pxrange,
        atlas_width=m.atlas_width, atlas_height=m.atlas_height,
        add_missing=m.add_missing if m.add_missing is not None else fb.add_missing,
    )
