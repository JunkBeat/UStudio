"""Per-type row icons for the main object table's "Имя" column (col 0) —
intuitive at a glance, inspired by the general idea of UABEA's own type
icons (a small distinguishing glyph per Unity type) without copying its
actual artwork. There are no icon/resource assets anywhere in this project
(confirmed — no icons/ folder, no .qrc, nothing) and the existing convention
for anything icon-like (see gui_widgets.ImagePreviewWidget._make_checker_tile)
is to draw it procedurally with QPainter rather than ship image files, so
these are drawn the same way: a small flat-colored rounded-square "chip" per
Unity type category, plus a simple glyph on top distinguishing it from
other types in the same color family.

Icons are cached per type name (module-level dict) — ObjectTableModel.data()
calls get_type_icon() on every DecorationRole request, which at hard-case
object counts (millions of rows) means this needs to be O(1) after the
first call per type, not redrawn from scratch per row/per repaint."""

from core.i18n import N_, tr
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_SIZE = 16
_ICON_CACHE: dict = {}

# (background color, glyph key) — grouped loosely by category via color:
# blue = image/texture, green = audio, orange = mesh/3D, purple = script/
# code, pink = material/paint, yellow = shader, teal = game object, red =
# animation/playback, gray-blue = plain text/document.
_TYPE_STYLE = {
    "Texture2D": ("#3b82f6", "image"),
    "Texture2DArray": ("#1d4ed8", "image_stack"),
    "Sprite": ("#06b6d4", "image_cut"),
    "AudioClip": ("#22c55e", "speaker"),
    "TextAsset": ("#64748b", "document"),
    "Mesh": ("#f97316", "cube_wire"),
    "Shader": ("#eab308", "bolt"),
    "Font": ("#a855f7", "letter"),
    "Material": ("#ec4899", "paint"),
    "GameObject": ("#14b8a6", "cube_solid"),
    "AnimationClip": ("#ef4444", "play_circle"),
    "AnimatorController": ("#b91c1c", "play_hex"),
    "MonoBehaviour": ("#8b5cf6", "script"),
    "VideoClip": ("#dc2626", "film"),
}
_FALLBACK_STYLE = ("#9ca3af", "dot")


def get_type_icon(type_name: str) -> QIcon:
    cached = _ICON_CACHE.get(type_name)
    if cached is not None:
        return cached
    color_hex, glyph = _TYPE_STYLE.get(type_name, _FALLBACK_STYLE)
    icon = QIcon(_draw_icon(color_hex, glyph))
    _ICON_CACHE[type_name] = icon
    return icon


# Not a Unity type (so it doesn't belong in _TYPE_STYLE above) — the group/
# "folder" row sdf_group_model.py's SDFGroupModel shows for one SDF font
# package (font + material + atlas texture bundled together). Same cached-
# QIcon, same procedural-QPainter convention as every type icon here, just
# keyed separately since "SDF Font Pack" is a synthetic row type, not a real
# obj.type.name.
_FOLDER_CACHE_KEY = "__sdf_folder__"


def get_folder_icon() -> QIcon:
    cached = _ICON_CACHE.get(_FOLDER_CACHE_KEY)
    if cached is not None:
        return cached
    icon = QIcon(_draw_icon("#f59e0b", "folder"))
    _ICON_CACHE[_FOLDER_CACHE_KEY] = icon
    return icon


def _draw_icon(color_hex: str, glyph: str) -> QPixmap:
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    bg = QColor(color_hex)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(QRectF(0, 0, _SIZE, _SIZE), 4, 4)

    painter.setPen(Qt.GlobalColor.white)
    painter.setBrush(Qt.GlobalColor.white)
    _GLYPH_DRAWERS.get(glyph, _glyph_dot)(painter)

    painter.end()
    return pixmap


def _glyph_image(p: QPainter) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3, 3.5, 10, 8), 1, 1)
    p.setBrush(Qt.GlobalColor.white)
    p.drawEllipse(QRectF(5, 5, 2, 2))
    path = QPainterPath()
    path.moveTo(3.5, 11)
    path.lineTo(7, 7)
    path.lineTo(9, 9.2)
    path.lineTo(11, 6.5)
    path.lineTo(12.5, 11)
    path.closeSubpath()
    p.drawPath(path)


def _glyph_image_stack(p: QPainter) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2, 2, 9, 7), 1, 1)
    p.drawRoundedRect(QRectF(5, 6.5, 9, 7), 1, 1)


def _glyph_image_cut(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(3, 4)
    path.lineTo(11, 4)
    path.lineTo(13, 8)
    path.lineTo(9, 8)
    path.lineTo(9, 13)
    path.lineTo(5, 13)
    path.lineTo(5, 8)
    path.lineTo(3, 8)
    path.closeSubpath()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _glyph_speaker(p: QPainter) -> None:
    """AudioClip's row icon. Real reported follow-up (same complaint as
    preview_icons.py's media-player volume glyph — "looks kind of cut off",
    "volume icons usually have 2-3 bars"): the previous 2-arc version relied
    on the painter's default hairline pen (no explicit width), which at this
    icon's small 16px canvas rendered the two closely-spaced arcs as a single
    blurred/merged wedge rather than two distinct waves. Redrawn with an
    explicit pen (crisp, consistent width) and three clearly-separated
    concentric arcs, all bounded well inside the 16px canvas (widest right
    edge at 15, 1px of margin) so nothing clips."""
    path = QPainterPath()
    path.moveTo(3.5, 6.5)
    path.lineTo(6, 6.5)
    path.lineTo(9, 4)
    path.lineTo(9, 12)
    path.lineTo(6, 9.5)
    path.lineTo(3.5, 9.5)
    path.closeSubpath()
    p.setBrush(Qt.GlobalColor.white)
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(Qt.GlobalColor.white, 1.1)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawArc(QRectF(9.7, 6.3, 2.2, 3.4), -55 * 16, 110 * 16)
    p.drawArc(QRectF(9.7, 5.0, 3.8, 6.0), -55 * 16, 110 * 16)
    p.drawArc(QRectF(9.7, 3.5, 5.3, 9.0), -55 * 16, 110 * 16)


def _glyph_document(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4, 2.5)
    path.lineTo(9.5, 2.5)
    path.lineTo(12, 5)
    path.lineTo(12, 13.5)
    path.lineTo(4, 13.5)
    path.closeSubpath()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    for y in (6.2, 8.4, 10.6):
        p.drawLine(QPointF(5.5, y), QPointF(10, y))


def _glyph_cube_wire(p: QPainter) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    top = QPainterPath()
    top.moveTo(8, 2.5)
    top.lineTo(13, 5.2)
    top.lineTo(8, 8)
    top.lineTo(3, 5.2)
    top.closeSubpath()
    p.drawPath(top)
    p.drawLine(QPointF(3, 5), QPointF(3, 10.5))
    p.drawLine(QPointF(13, 5), QPointF(13, 10.5))
    p.drawLine(QPointF(8, 8), QPointF(8, 13.5))
    p.drawLine(QPointF(3, 10.5), QPointF(8, 13.5))
    p.drawLine(QPointF(13, 10.5), QPointF(8, 13.5))


def _glyph_cube_solid(p: QPainter) -> None:
    p.setBrush(QColor(255, 255, 255, 235))
    top = QPainterPath()
    top.moveTo(8, 2.5)
    top.lineTo(13, 5.2)
    top.lineTo(8, 8)
    top.lineTo(3, 5.2)
    top.closeSubpath()
    p.drawPath(top)
    p.setBrush(QColor(255, 255, 255, 170))
    left = QPainterPath()
    left.moveTo(3, 5.2)
    left.lineTo(8, 8)
    left.lineTo(8, 13.5)
    left.lineTo(3, 10.5)
    left.closeSubpath()
    p.drawPath(left)
    p.setBrush(QColor(255, 255, 255, 120))
    right = QPainterPath()
    right.moveTo(13, 5.2)
    right.lineTo(8, 8)
    right.lineTo(8, 13.5)
    right.lineTo(13, 10.5)
    right.closeSubpath()
    p.drawPath(right)


def _glyph_bolt(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(9, 2.5)
    path.lineTo(4.5, 9)
    path.lineTo(7.5, 9)
    path.lineTo(6.5, 13.5)
    path.lineTo(11.5, 7)
    path.lineTo(8.5, 7)
    path.closeSubpath()
    p.setBrush(Qt.GlobalColor.white)
    p.drawPath(path)


def _glyph_letter(p: QPainter) -> None:
    font = p.font()
    font.setBold(True)
    font.setPixelSize(11)
    p.setFont(font)
    p.drawText(QRectF(0, 0, _SIZE, _SIZE), Qt.AlignmentFlag.AlignCenter, "A")


def _glyph_paint(p: QPainter) -> None:
    p.setBrush(Qt.GlobalColor.white)
    p.drawEllipse(QRectF(3.5, 3.5, 9, 9))
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawEllipse(QRectF(6, 6, 3.2, 3.2))


def _glyph_play_circle(p: QPainter) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(2.5, 2.5, 11, 11))
    p.setBrush(Qt.GlobalColor.white)
    tri = QPainterPath()
    tri.moveTo(6.5, 5.5)
    tri.lineTo(11, 8)
    tri.lineTo(6.5, 10.5)
    tri.closeSubpath()
    p.drawPath(tri)


def _glyph_play_hex(p: QPainter) -> None:
    hexagon = QPainterPath()
    pts = [(8, 2), (12.5, 4.7), (12.5, 11.3), (8, 14), (3.5, 11.3), (3.5, 4.7)]
    hexagon.moveTo(*pts[0])
    for pt in pts[1:]:
        hexagon.lineTo(*pt)
    hexagon.closeSubpath()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(hexagon)
    p.setBrush(Qt.GlobalColor.white)
    tri = QPainterPath()
    tri.moveTo(6.7, 5.8)
    tri.lineTo(10.7, 8)
    tri.lineTo(6.7, 10.2)
    tri.closeSubpath()
    p.drawPath(tri)


def _glyph_script(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4, 2.5)
    path.lineTo(9.5, 2.5)
    path.lineTo(12, 5)
    path.lineTo(12, 13.5)
    path.lineTo(4, 13.5)
    path.closeSubpath()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.drawLine(QPointF(6, 8.2), QPointF(5, 9.5))
    p.drawLine(QPointF(5, 9.5), QPointF(6, 10.8))
    p.drawLine(QPointF(9, 8.2), QPointF(10, 9.5))
    p.drawLine(QPointF(10, 9.5), QPointF(9, 10.8))
    p.drawLine(QPointF(7.8, 7.5), QPointF(7.2, 11.5))


def _glyph_film(p: QPainter) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 3.5, 9, 9), 1, 1)
    p.setBrush(Qt.GlobalColor.white)
    for x in (4.3, 10.7):
        for y in (4.3, 6.9, 9.5, 11.4):
            if y == 11.4:
                continue
            p.drawRect(QRectF(x, y, 1.4, 1.4))
    tri = QPainterPath()
    tri.moveTo(7, 6)
    tri.lineTo(10.3, 8)
    tri.lineTo(7, 10)
    tri.closeSubpath()
    p.drawPath(tri)


def _glyph_dot(p: QPainter) -> None:
    p.setBrush(Qt.GlobalColor.white)
    p.drawEllipse(QRectF(6, 6, 4, 4))


def _glyph_folder(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(2.5, 5)
    path.lineTo(6, 5)
    path.lineTo(7.2, 6.3)
    path.lineTo(13.5, 6.3)
    path.lineTo(13.5, 12.5)
    path.lineTo(2.5, 12.5)
    path.closeSubpath()
    p.setBrush(Qt.GlobalColor.white)
    p.drawPath(path)


def _glyph_pencil(p: QPainter) -> None:
    p.setBrush(Qt.GlobalColor.white)
    body = QPainterPath()
    body.moveTo(3.2, 12.8)
    body.lineTo(4, 9.3)
    body.lineTo(9.8, 3.5)
    body.lineTo(12.5, 6.2)
    body.lineTo(6.7, 12)
    body.closeSubpath()
    p.drawPath(body)
    p.setBrush(QColor(0, 0, 0, 60))
    tip = QPainterPath()
    tip.moveTo(3.2, 12.8)
    tip.lineTo(4, 9.3)
    tip.lineTo(6.7, 12)
    tip.closeSubpath()
    p.drawPath(tip)


def _glyph_import_arrow(p: QPainter) -> None:
    # Down-arrow into a tray — matches the conventional "import"/"download" glyph.
    p.setBrush(Qt.GlobalColor.white)
    shaft = QPainterPath()
    shaft.moveTo(6.8, 2.5)
    shaft.lineTo(9.2, 2.5)
    shaft.lineTo(9.2, 7.5)
    shaft.lineTo(11.5, 7.5)
    shaft.lineTo(8, 11.2)
    shaft.lineTo(4.5, 7.5)
    shaft.lineTo(6.8, 7.5)
    shaft.closeSubpath()
    p.drawPath(shaft)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(3.5, 13), QPointF(12.5, 13))


def _glyph_export_arrow(p: QPainter) -> None:
    # Up-arrow out of a tray — the mirror of _glyph_import_arrow.
    p.setBrush(Qt.GlobalColor.white)
    shaft = QPainterPath()
    shaft.moveTo(6.8, 13)
    shaft.lineTo(9.2, 13)
    shaft.lineTo(9.2, 8)
    shaft.lineTo(11.5, 8)
    shaft.lineTo(8, 4.3)
    shaft.lineTo(4.5, 8)
    shaft.lineTo(6.8, 8)
    shaft.closeSubpath()
    p.drawPath(shaft)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(3.5, 13), QPointF(12.5, 13))


def _glyph_copy(p: QPainter) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.8, 2.8, 8, 8), 1, 1)
    p.setBrush(QColor(0, 0, 0, 45))
    p.drawRoundedRect(QRectF(5.2, 5.2, 8, 8), 1, 1)
    p.setBrush(Qt.GlobalColor.white)
    p.drawRoundedRect(QRectF(5.2, 5.2, 8, 8), 1, 1)


def _glyph_field_lens(p: QPainter) -> None:
    # «Изучить поля скрипта»: a list of fields (bullet + line) under a magnifying glass
    from PyQt6.QtGui import QPen
    for y in (3.5, 6.5):                         # on pixel centres: crisp 1 px lines at 16 px
        p.fillRect(QRectF(2, y - 1.5, 2, 2), Qt.GlobalColor.white)
        p.drawLine(QPointF(5.5, y), QPointF(12.5, y))
    p.fillRect(QRectF(2, 8, 2, 2), Qt.GlobalColor.white)
    p.drawLine(QPointF(5.5, 9.5), QPointF(6.5, 9.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(Qt.GlobalColor.white, 1.5))
    p.drawEllipse(QRectF(7.4, 7.6, 4.6, 4.6))
    p.setPen(QPen(Qt.GlobalColor.white, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(11.4, 11.6), QPointF(13.6, 13.8))


def _chevrons(p: QPainter, apart: bool) -> None:
    # two arrows (shaft + head) and a centre line: pointing away from it = expand, towards it = collapse.
    # (Bare chevrons were read as an asterisk at 16 px — user report.)
    from PyQt6.QtGui import QPen, QPolygonF
    p.setPen(QPen(Qt.GlobalColor.white, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for direction in (-1, 1):                     # -1: the upper arrow, 1: the lower one
        near, far = 8 + direction * 2.6, 8 + direction * 6.2   # shaft ends: by the line / by the edge
        tip, tail = (far, near) if apart else (near, far)
        back = tip + (2.2 if tail > tip else -2.2)                # the head's arms go back along the shaft
        p.drawLine(QPointF(8, tail), QPointF(8, tip))
        p.drawPolyline(QPolygonF([QPointF(5.6, back), QPointF(8, tip), QPointF(10.4, back)]))
    p.drawLine(QPointF(3.2, 8), QPointF(12.8, 8))


def _glyph_expand(p: QPainter) -> None:
    _chevrons(p, True)


def _glyph_collapse(p: QPainter) -> None:
    _chevrons(p, False)


_GLYPH_DRAWERS = {
    "expand": _glyph_expand,
    "collapse": _glyph_collapse,
    "image": _glyph_image,
    "image_stack": _glyph_image_stack,
    "image_cut": _glyph_image_cut,
    "speaker": _glyph_speaker,
    "document": _glyph_document,
    "cube_wire": _glyph_cube_wire,
    "cube_solid": _glyph_cube_solid,
    "bolt": _glyph_bolt,
    "letter": _glyph_letter,
    "paint": _glyph_paint,
    "play_circle": _glyph_play_circle,
    "play_hex": _glyph_play_hex,
    "script": _glyph_script,
    "film": _glyph_film,
    "dot": _glyph_dot,
    "folder": _glyph_folder,
    "pencil": _glyph_pencil,
    "import_arrow": _glyph_import_arrow,
    "export_arrow": _glyph_export_arrow,
    "copy": _glyph_copy,
    "field_lens": _glyph_field_lens,
}

# Generic context-menu action icons (Edit/Import/Export/Copy/Show in Explorer) — same
# procedurally-drawn-QPainter convention as the per-type icons above (this project has
# no bundled icon assets at all, see this file's own module docstring), just a single
# neutral background color distinct from the per-type palette so an action icon never
# reads as if it were naming a Unity type.
_ACTION_COLOR = "#475569"
_ACTION_GLYPH = {
    "edit": "pencil",
    "import": "import_arrow",
    "export": "export_arrow",
    "copy": "copy",
    "explorer": "folder",
    "view": "document",
    "expand": "expand",
    "collapse": "collapse",
    "study_fields": "field_lens",
}


# Offered by the quick-filter icon picker next to the type icons (key -> caption). "folder" is the
# orange SDF-group folder.
_PICKER_EXTRA = (
    ("folder", N_("Папка")),
    ("edit", N_("Правка")),
    ("import", N_("Импорт")),
    ("export", N_("Экспорт")),
    ("copy", N_("Копирование")),
)


def builtin_icon_choices() -> list:
    """[(key, caption)] of the built-in icons a quick filter may use: every type icon (caption = the
    type name) first, then a few general ones."""
    return [(name, name) for name in _TYPE_STYLE] + [(key, tr(caption)) for key, caption in _PICKER_EXTRA]


def get_builtin_icon(key: str):
    """The built-in icon named `key` (see builtin_icon_choices()) or None when there is none."""
    if key in _TYPE_STYLE:
        return get_type_icon(key)
    if key == "folder":
        return get_folder_icon()
    if any(key == k for k, _ in _PICKER_EXTRA):
        return get_action_icon(key)
    return None


def builtin_icon_caption(key: str) -> str:
    return next((caption for k, caption in builtin_icon_choices() if k == key), key)


def get_action_icon(action: str) -> QIcon:
    cache_key = f"__action_{action}__"
    cached = _ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached
    glyph = _ACTION_GLYPH.get(action, "dot")
    icon = QIcon(_draw_icon(_ACTION_COLOR, glyph))
    _ICON_CACHE[cache_key] = icon
    return icon


# --- bookmarks («Закладки») ---

_BOOKMARK_COLOR = "#f59e0b"     # amber — the usual "favourite" colour, readable in both themes


def _star_path(cx: float, cy: float, outer: float, inner: float) -> QPainterPath:
    import math
    path = QPainterPath()
    for k in range(10):
        r = outer if k % 2 == 0 else inner
        a = math.radians(-90 + 36 * k)
        point = QPointF(cx + r * math.cos(a), cy + r * math.sin(a))
        if k == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


def get_bookmark_icon() -> QIcon:
    """The bookmark action / «Закладки» toggle: a plain amber star (no tile — it stands out among the grey ones)."""
    cache_key = "__bookmark__"
    cached = _ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#b45309"), 1))
    p.setBrush(QColor(_BOOKMARK_COLOR))
    p.drawPath(_star_path(8, 8.6, 7.4, 3.1))
    p.end()
    icon = QIcon(pixmap)
    _ICON_CACHE[cache_key] = icon
    return icon


def get_bookmarked_type_icon(type_name: str) -> QIcon:
    """A bookmarked row's icon in the table: its type tile a little smaller (top-left) and an amber star in the
    freed bottom-right corner, over the table's own background — a star drawn ON the tile vanished on amber
    tiles (Shader) and covered the glyph."""
    cache_key = f"__bookmarked_{type_name}__"
    cached = _ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached
    color_hex, glyph = _TYPE_STYLE.get(type_name, _FALLBACK_STYLE)
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawPixmap(QRectF(0, 0, 12, 12), _draw_icon(color_hex, glyph), QRectF(0, 0, _SIZE, _SIZE))
    p.setPen(QPen(QColor("#b45309"), 0.8))
    p.setBrush(QColor(_BOOKMARK_COLOR))
    p.drawPath(_star_path(11.8, 11.9, 4.4, 1.9))
    p.end()
    icon = QIcon(pixmap)
    _ICON_CACHE[cache_key] = icon
    return icon
