"""Minimal, self-contained reader for a TrueType/OpenType font's own `cmap`
table (character-to-glyph mapping) — just enough to answer "does this font
map these specific code points to a real glyph", without a third-party font
library.

This exists purely to replace fontTools, which used to be pulled in solely
for object_metadata.py's Cyrillic-support check (font_supports_cyrillic()) —
the only place in this codebase that ever needed to look inside a font file.
Under Nuitka, fontTools dragged in a large amount of unrelated machinery
(subsetting, variable-font tooling, optional XML/compression backends) just
to answer that one narrow question.

The cmap format itself is a stable, decades-old, publicly documented part of
the OpenType spec (see the OpenType spec's "cmap" and "OTFF" chapters) — not
a reverse-engineered proprietary one — so implementing it directly here
(rather than guessing at an unverified binary layout) fits this project's own
methodology of only writing binary-format logic against a real, trustable
reference."""

import struct
from typing import List, Optional, Tuple

# Same platform/encoding preference order fontTools' own TTFont.getBestCmap()
# uses by default — kept identical so this replacement can't quietly change
# which subtable "wins" on a font that ships more than one.
_CMAP_PLATFORM_PREFERENCE = ((3, 10), (0, 6), (0, 4), (3, 1), (0, 3), (0, 2), (0, 1), (0, 0))


def _read_sfnt_table_directory(data: bytes) -> Optional[dict]:
    """Table directory {tag: (offset, length)} for font index 0 of an SFNT
    (.ttf/.otf) or 'ttcf' collection file — mirrors fontTools' own
    fontNumber=0 default."""
    if len(data) < 12:
        return None
    if data[:4] == b"ttcf":
        if len(data) < 16:
            return None
        num_fonts = struct.unpack_from(">I", data, 8)[0]
        if num_fonts < 1:
            return None
        base = struct.unpack_from(">I", data, 12)[0]
    else:
        base = 0
    if base + 12 > len(data):
        return None
    num_tables = struct.unpack_from(">H", data, base + 4)[0]
    tables = {}
    pos = base + 12
    for _ in range(num_tables):
        if pos + 16 > len(data):
            return None
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, pos)
        tables[tag] = (offset, length)
        pos += 16
    return tables


def _decode_cmap_format4(data: bytes, base: int, codepoints) -> set:
    seg_count_x2 = struct.unpack_from(">H", data, base + 6)[0]
    seg_count = seg_count_x2 // 2
    end_codes = struct.unpack_from(f">{seg_count}H", data, base + 14)
    start_codes_off = base + 16 + seg_count_x2
    start_codes = struct.unpack_from(f">{seg_count}H", data, start_codes_off)
    id_deltas_off = start_codes_off + seg_count_x2
    id_deltas = struct.unpack_from(f">{seg_count}h", data, id_deltas_off)
    id_range_offsets_off = id_deltas_off + seg_count_x2
    id_range_offsets = struct.unpack_from(f">{seg_count}H", data, id_range_offsets_off)

    found = set()
    for cp in codepoints:
        if cp > 0xFFFF:
            continue
        for i in range(seg_count):
            if not (start_codes[i] <= cp <= end_codes[i]):
                continue
            if id_range_offsets[i] == 0:
                glyph_id = (cp + id_deltas[i]) & 0xFFFF
            else:
                # Classic OpenType cmap format 4 pointer trick: idRangeOffset[i]
                # is a BYTE offset taken relative to the storage address of
                # idRangeOffset[i] itself, not the start of the array.
                addr = id_range_offsets_off + i * 2 + id_range_offsets[i] + (cp - start_codes[i]) * 2
                if addr + 2 > len(data):
                    glyph_id = 0
                else:
                    glyph_id = struct.unpack_from(">H", data, addr)[0]
                    if glyph_id != 0:
                        glyph_id = (glyph_id + id_deltas[i]) & 0xFFFF
            if glyph_id != 0:
                found.add(cp)
            break
    return found


def _decode_cmap_format6(data: bytes, base: int, codepoints) -> set:
    first_code, entry_count = struct.unpack_from(">HH", data, base + 6)
    glyph_ids = struct.unpack_from(f">{entry_count}H", data, base + 10)
    found = set()
    for cp in codepoints:
        idx = cp - first_code
        if 0 <= idx < entry_count and glyph_ids[idx] != 0:
            found.add(cp)
    return found


def _decode_cmap_format12(data: bytes, base: int, codepoints) -> set:
    num_groups = struct.unpack_from(">I", data, base + 12)[0]
    remaining = set(codepoints)
    found = set()
    pos = base + 16
    for _ in range(num_groups):
        if not remaining:
            break
        if pos + 12 > len(data):
            break
        start_char, end_char, _start_glyph = struct.unpack_from(">III", data, pos)
        matched = {cp for cp in remaining if start_char <= cp <= end_char}
        found |= matched
        remaining -= matched
        pos += 12
    return found


_CMAP_DECODERS = {4: _decode_cmap_format4, 6: _decode_cmap_format6, 12: _decode_cmap_format12}


def find_covered_codepoints(font_data: bytes, codepoints) -> Optional[set]:
    """The subset of `codepoints` this font's own "best" cmap subtable (same
    preference order as fontTools) maps to a real (non-.notdef) glyph.
    Returns None if the data doesn't parse as a font, has no `cmap` table, or
    its only Unicode-capable subtable(s) use a format this module doesn't
    decode (only formats 4/6/12 are implemented — the ones real-world fonts
    actually ship; verified against every real font on a real machine, not
    just synthetic input — see the call site's own verification note)."""
    tables = _read_sfnt_table_directory(font_data)
    if not tables or b"cmap" not in tables:
        return None
    cmap_offset, _cmap_length = tables[b"cmap"]
    if cmap_offset + 4 > len(font_data):
        return None
    num_subtables = struct.unpack_from(">H", font_data, cmap_offset + 2)[0]
    subtables = {}
    pos = cmap_offset + 4
    for _ in range(num_subtables):
        if pos + 8 > len(font_data):
            break
        platform_id, encoding_id, offset = struct.unpack_from(">HHI", font_data, pos)
        subtables[(platform_id, encoding_id)] = cmap_offset + offset
        pos += 8
    for platform_id, encoding_id in _CMAP_PLATFORM_PREFERENCE:
        sub_offset = subtables.get((platform_id, encoding_id))
        if sub_offset is None or sub_offset + 2 > len(font_data):
            continue
        fmt = struct.unpack_from(">H", font_data, sub_offset)[0]
        decoder = _CMAP_DECODERS.get(fmt)
        if decoder is None:
            continue
        try:
            return decoder(font_data, sub_offset, codepoints)
        except struct.error:
            continue
    return None


def font_coverage(font_data: bytes, codepoints) -> Optional[Tuple[int, int, List[int]]]:
    """(how many of `codepoints` the font covers, how many were asked about, the missing ones in the
    order given) — the numbers behind the SDF dialog's "the font has N% of these characters" line.
    Duplicates count once. None when the data is not a font this module can read (same cases as
    find_covered_codepoints)."""
    wanted = list(dict.fromkeys(codepoints))
    covered = find_covered_codepoints(font_data, wanted)
    if covered is None:
        return None
    missing = [cp for cp in wanted if cp not in covered]
    return len(wanted) - len(missing), len(wanted), missing
