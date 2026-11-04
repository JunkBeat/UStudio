"""A sprite's mesh replaced by a plain rectangle (two triangles) over a pixel box of its texture. No Qt.

Why: a sprite with Unity's «Tight» mesh is drawn only inside the outline of its ORIGINAL picture (the mesh
follows its alpha), and its `textureRect` is that outline's fractional bounding box. New pixels outside the
old outline are never drawn in game — an imported translation gets clipped. A rectangle over the whole box
draws every pixel (transparent ones stay invisible).

Works on the typetree DICT of an unpacked sprite with its own `m_RD` (not one on a SpriteAtlas or packed by
the legacy packer, whose pixels may be interleaved with other sprites'), one submesh, 16-bit indices, and a
vertex layout of float positions + float UV0 (what every surveyed sprite has: Unity 5.6, 2018, 2019, 2022);
other per-vertex channels (Unity 2022 stores unused bone weights) are copied when every old vertex has the same
values, and refused otherwise; a sprite with bones is refused.

Measured layouts (the survey in the 2026-10-18 CLAUDE.md entry): Unity 2018+ = 14 channels, position in
stream 0, UV0 (channel 4) in stream 1, streams 16-byte aligned; Unity 5.6 = 8 channels, UV0 (channel 3) in
stream 0 at offset 12. A full-rect quad is TL, TR, BL, BR with indices 0,1,2, 2,1,3 (Petscop's own full-rect
sprites). Positions = (pixel in m_Rect - pivot * m_Rect size) / pixels-per-unit; UVs (when stored — many
sprites keep all zeros, and those are kept zero) = texture pixel / texture size. Both formulas reproduce the
stored data of every sampled sprite."""

from __future__ import annotations

from core.i18n import N_, tr
import struct
from typing import Optional, Tuple

Box = Tuple[float, float, float, float]   # x, y, width, height in texture pixels, bottom-left origin

_MESH_TYPE_TIGHT_BIT = 1 << 6             # settingsRaw: SpriteSettings.meshType
_PACKED_BIT = 1


def _uv0_channel(channels: list) -> int:
    # Unity 2018.1 grew the channel list to 14 (tangent/color moved), UV0 went from 3 to 4.
    return 4 if len(channels) > 8 else 3


def _component_size(version, fmt: int) -> int:
    from UnityPy.enums.VertexFormat import (
        VERTEX_CHANNEL_FORMAT_STRUCT_TYPE_MAP, VERTEX_FORMAT_2017_STRUCT_TYPE_MAP, VERTEX_FORMAT_STRUCT_TYPE_MAP,
        VertexChannelFormat, VertexFormat, VertexFormat2017,
    )
    if version[0] < 2017:
        code = VERTEX_CHANNEL_FORMAT_STRUCT_TYPE_MAP[VertexChannelFormat(fmt)]
    elif version[0] < 2019:
        code = VERTEX_FORMAT_2017_STRUCT_TYPE_MAP[VertexFormat2017(fmt)]
    else:
        code = VERTEX_FORMAT_STRUCT_TYPE_MAP[VertexFormat(fmt)]
    return struct.calcsize("<" + code)


def _stream_layout(channels: list, vertex_count: int, version):
    """{channel index: (absolute byte offset of vertex 0, stride, byte length of one value)} and the data size —
    MeshHandler.get_streams' rule (streams one after another, each padded to 16 bytes)."""
    sizes = {i: (ch["dimension"] & 0xF) * _component_size(version, ch["format"])
             for i, ch in enumerate(channels) if ch["dimension"]}
    layout = {}
    offset = end = 0
    for s in range(1 + max(ch["stream"] for ch in channels)):
        stride = sum(n for i, n in sizes.items() if channels[i]["stream"] == s)
        for i, n in sizes.items():
            if channels[i]["stream"] == s:
                layout[i] = (offset + channels[i]["offset"], stride, n)
        end = offset + vertex_count * stride      # the last stream is not padded (Music Racer: 7 vertices = 152)
        offset = (end + 15) & ~15
    return layout, end


def _extra_channel_values(vd: dict, layout: dict):
    """For each channel other than position/UV0 (in channel order): its bytes if every vertex has the same
    ones, else None."""
    data = bytes(vd["m_DataSize"])
    uv0 = _uv0_channel(vd["m_Channels"])
    out = []
    for i, (off, stride, n) in sorted(layout.items()):
        if i in (0, uv0):
            continue
        values = {data[off + k * stride: off + k * stride + n] for k in range(vd["m_VertexCount"])}
        out.append(values.pop() if len(values) == 1 else None)
    return out


def full_rect_problem(tree: dict, version) -> Optional[str]:
    """Why this sprite's mesh cannot be replaced by a rectangle, in user words — or None. `version` = the
    object's Unity version tuple (obj.version)."""
    rd = tree.get("m_RD") or {}
    atlas = tree.get("m_SpriteAtlas") or {}
    if atlas.get("m_PathID") or tree.get("m_AtlasTags") or (rd.get("settingsRaw", 0) & _PACKED_BIT):
        return tr("спрайт упакован в атлас вместе с другими спрайтами")
    if tree.get("m_Bones") or rd.get("m_Bindpose"):
        return tr("у спрайта есть кости (анимация сетки)")
    vd = rd.get("m_VertexData")
    if not isinstance(vd, dict) or "m_Channels" not in vd or "m_SubMeshes" not in rd:
        return tr("сетка спрайта хранится в формате старых версий Unity")
    if len(rd["m_SubMeshes"]) != 1:
        return tr("у сетки спрайта несколько частей")
    channels = vd["m_Channels"]
    if not channels or channels[0].get("dimension") != 3 or channels[0].get("format") != 0:
        return tr("у сетки спрайта нет обычных координат вершин")
    uv = channels[_uv0_channel(channels)]
    if uv.get("dimension") not in (0, 2) or (uv.get("dimension") and uv.get("format")):
        return tr("у сетки спрайта нестандартные текстурные координаты")
    sub = rd["m_SubMeshes"][0]
    if len(rd.get("m_IndexBuffer") or b"") != sub.get("indexCount", -1) * 2:
        return tr("у сетки спрайта нестандартный формат индексов")
    try:
        layout, size = _stream_layout(channels, vd["m_VertexCount"], version)
        if len(vd["m_DataSize"]) < size:
            return tr("данные вершин спрайта короче, чем должны быть")
        if any(value is None for value in _extra_channel_values(vd, layout)):
            # e.g. bone weights that differ per vertex — a rectangle cannot keep them
            return tr("у вершин сетки разные дополнительные данные (веса костей)")
    except Exception:
        return tr("данные вершин спрайта не удалось прочитать")
    return None


def _read_vertices(rd: dict, version):
    vd = rd["m_VertexData"]
    channels = vd["m_Channels"]
    count = vd["m_VertexCount"]
    layout, _size = _stream_layout(channels, count, version)
    data = bytes(vd["m_DataSize"])
    pos_off, pos_stride, _n = layout[0]
    positions = [struct.unpack_from("<3f", data, pos_off + k * pos_stride) for k in range(count)]
    uvs = None
    uv0 = _uv0_channel(channels)
    if uv0 in layout:
        uv_off, uv_stride, _n = layout[uv0]
        uvs = [struct.unpack_from("<2f", data, uv_off + k * uv_stride) for k in range(count)]
    return positions, uvs


def _corners(tree: dict, box: Box):
    """Positions of TL, TR, BL, BR of `box` (texture pixels) in the sprite's units."""
    rect, pivot, ppu = tree["m_Rect"], tree["m_Pivot"], tree["m_PixelsToUnits"]
    px, py = pivot["x"] * rect["width"], pivot["y"] * rect["height"]
    x0 = (box[0] - rect["x"] - px) / ppu
    x1 = (box[0] + box[2] - rect["x"] - px) / ppu
    y0 = (box[1] - rect["y"] - py) / ppu
    y1 = (box[1] + box[3] - rect["y"] - py) / ppu
    return [(x0, y1), (x1, y1), (x0, y0), (x1, y0)]


def is_full_rect(tree: dict, box: Box, version) -> bool:
    """The mesh is already one rectangle over `box` (and the render data points at it)."""
    rd = tree["m_RD"]
    texture_rect = rd["textureRect"]
    if any(abs(a - b) > 1e-3 for a, b in zip((texture_rect["x"], texture_rect["y"], texture_rect["width"], texture_rect["height"]), box)):
        return False
    if rd["m_VertexData"].get("m_VertexCount") != 4 or rd["m_SubMeshes"][0].get("indexCount") != 6:
        return False
    try:
        positions, _uvs = _read_vertices(rd, version)
    except Exception:
        return False
    tol = 1e-3 / max(tree["m_PixelsToUnits"], 1e-6) + 1e-4
    have = sorted((x, y) for x, y, _z in positions)
    want = sorted(_corners(tree, box))
    return all(abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol for a, b in zip(have, want))


def set_full_rect(tree: dict, box: Box, texture_size: Tuple[int, int], version) -> None:
    """Replaces the mesh of `tree` (a typetree dict, changed in place) by a rectangle over `box`. Call
    full_rect_problem() first. m_Rect, pivot, pixels-per-unit stay — the sprite sits where it sat. Other
    per-vertex values (Unity 2022's unused bone weights) are the same on every old vertex and are copied."""
    rd = tree["m_RD"]
    vd = rd["m_VertexData"]
    channels = vd["m_Channels"]
    _old_positions, old_uvs = _read_vertices(rd, version)
    keep_zero_uvs = not old_uvs or not any(u or v for u, v in old_uvs)
    old_layout, _old_size = _stream_layout(channels, vd["m_VertexCount"], version)
    extras = _extra_channel_values(vd, old_layout)

    layout, size = _stream_layout(channels, 4, version)
    data = bytearray(size)
    uv0 = _uv0_channel(channels)
    extra_ids = [i for i in sorted(layout) if i not in (0, uv0)]
    for i, value in zip(extra_ids, extras):
        off, stride, n = layout[i]
        for k in range(4):
            data[off + k * stride: off + k * stride + n] = value
    pos_off, pos_stride, _n = layout[0]
    for k, (x, y) in enumerate(_corners(tree, box)):
        struct.pack_into("<3f", data, pos_off + k * pos_stride, x, y, 0.0)
    if uv0 in layout and not keep_zero_uvs:
        tw, th = texture_size
        u0, u1 = box[0] / tw, (box[0] + box[2]) / tw
        v0, v1 = box[1] / th, (box[1] + box[3]) / th
        uv_off, uv_stride, _n = layout[uv0]
        for k, (u, v) in enumerate([(u0, v1), (u1, v1), (u0, v0), (u1, v0)]):
            struct.pack_into("<2f", data, uv_off + k * uv_stride, u, v)

    vd["m_VertexCount"] = 4
    vd["m_DataSize"] = bytes(data)
    rd["m_IndexBuffer"] = list(struct.pack("<6H", 0, 1, 2, 2, 1, 3))
    sub = rd["m_SubMeshes"][0]
    sub["firstByte"] = 0
    sub["indexCount"] = 6
    sub["firstVertex"] = 0
    sub["vertexCount"] = 4
    if "baseVertex" in sub:
        sub["baseVertex"] = 0
    rect = tree["m_Rect"]
    rd["textureRect"] = {"x": float(box[0]), "y": float(box[1]), "width": float(box[2]), "height": float(box[3])}
    rd["textureRectOffset"] = {"x": float(box[0] - rect["x"]), "y": float(box[1] - rect["y"])}
    rd["settingsRaw"] = rd.get("settingsRaw", 0) & ~_MESH_TYPE_TIGHT_BIT


def rect_box(tree: dict) -> Box:
    r = tree["m_Rect"]
    return (r["x"], r["y"], r["width"], r["height"])


def visible_box(tree: dict, image) -> Optional[Box]:
    """The whole-pixel box (texture pixels, bottom-left origin) around the pixels of `image` (the sprite's
    texture as a PIL image, top-left origin) that are not fully transparent inside the sprite's m_Rect, or
    None when there are none."""
    r = tree["m_Rect"]
    x0, y0 = round(r["x"]), round(r["y"])
    x1, y1 = round(r["x"] + r["width"]), round(r["y"] + r["height"])
    height = image.size[1]
    crop = image.convert("RGBA").crop((x0, height - y1, x1, height - y0))
    bbox = crop.getchannel("A").getbbox()
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    return (float(x0 + left), float(y0 + (y1 - y0) - bottom), float(right - left), float(bottom - top))


def _drawn_box(tree: dict) -> Box:
    """The old textureRect as whole pixels — rounded like the sprite's export (object_sprite._pixel_box), kept
    inside m_Rect."""
    texture_rect, r = tree["m_RD"]["textureRect"], tree["m_Rect"]
    x0, y0 = max(round(texture_rect["x"]), round(r["x"])), max(round(texture_rect["y"]), round(r["y"]))
    x1 = min(round(texture_rect["x"] + texture_rect["width"]), round(r["x"] + r["width"]))
    y1 = min(round(texture_rect["y"] + texture_rect["height"]), round(r["y"] + r["height"]))
    return (float(x0), float(y0), float(max(0, x1 - x0)), float(max(0, y1 - y0)))


def _union(a: Box, b: Box) -> Box:
    if b[2] <= 0 or b[3] <= 0:
        return a
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    return (x0, y0, max(a[0] + a[2], b[0] + b[2]) - x0, max(a[1] + a[3], b[1] + b[3]) - y0)


# The one "nothing to do" answer of make_sprite_full_rect (the window logs it as information, any other refusal as a
# warning) — compared by value, so keep it a constant.
ALREADY_FULL_RECT = N_("сетка уже прямоугольная")


def make_sprite_full_rect(obj) -> Tuple[bool, str]:
    """The «Сделать сетку прямоугольной» action, for a sprite whose texture was edited directly: the mesh becomes
    a rectangle around the pixels the texture shows inside the sprite's m_Rect NOW (new ones outside the old
    outline included) joined with the old trimmed box (so a picture exported before still fits back). Not the
    whole m_Rect (until 2026-10-19): a sprite whose m_Rect is a whole, mostly empty
    texture (Phonopolis PHONO_00064: 2200 x 1237 around a 375 x 248 picture) became a huge empty quad, and its
    exported picture no longer fitted back (user report). Returns (changed, message for the log)."""
    try:
        tree = obj.read_typetree()
    except Exception as e:
        return False, tr("не удалось прочитать спрайт: {error}", error=e)
    problem = full_rect_problem(tree, obj.version)
    if problem:
        return False, tr("сетку нельзя заменить: {problem}", problem=problem)
    try:
        texture = obj.parse_as_object().m_RD.texture.deref_parse_as_object()
        tex = (int(texture.m_Width), int(texture.m_Height))
        box = visible_box(tree, texture.image)
    except Exception as e:
        return False, tr("не удалось прочитать текстуру спрайта: {error}", error=e)
    if box is None:
        return False, tr("в спрайте нет видимых пикселей")
    box = _union(box, _drawn_box(tree))
    texture_rect = tree["m_RD"]["textureRect"]
    current = (texture_rect["x"], texture_rect["y"], texture_rect["width"], texture_rect["height"])
    # already a rectangle that holds every visible pixel (e.g. one over the whole m_Rect): left as it is
    if _union(current, box) == current and is_full_rect(tree, current, obj.version):
        return False, tr(ALREADY_FULL_RECT)
    set_full_rect(tree, box, tex, obj.version)
    obj.save_typetree(tree)
    return True, tr("сетка заменена прямоугольником {value:g} × {value2:g} вокруг видимой части спрайта", value=box[2], value2=box[3])
