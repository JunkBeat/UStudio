"""Procedural icons for PreviewPanel's image-preview toolbar buttons (fullscreen
popup, background-cycle, jump-to-texture, sprite-region toggle) — same
"colored rounded-square chip + white glyph" style as type_icons.py, for the
same reason (no icon assets exist anywhere in this project; emoji glyphs
were tried first and reported as not fitting the button descriptions well
enough, and render inconsistently — a color emoji's exact appearance depends
on the OS font, unlike a procedurally-drawn chip which looks identical
everywhere). Kept in a separate module from type_icons.py rather than folded
in: these aren't Unity type icons, and mixing "table row type" lookups with
"toolbar button" lookups in one cache/dict would conflate two unrelated
concerns. jump-to-texture's glyph intentionally reuses the same visual
language as type_icons.py's own Texture2D icon (a tiny image/mountain glyph)
so the button reads as "goes to a texture" at a glance, consistent with how
that same shape already means "texture" in the table."""

import math

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_SIZE = 22
_ICON_CACHE: dict = {}


def _get_icon(key: str, color_hex: str, glyph_key: str) -> QIcon:
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    icon = QIcon(_draw_icon(color_hex, glyph_key))
    _ICON_CACHE[key] = icon
    return icon


def _draw_icon(color_hex: str, glyph_key: str) -> QPixmap:
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color_hex))
    painter.drawRoundedRect(QRectF(0, 0, _SIZE, _SIZE), 5, 5)

    painter.setPen(Qt.GlobalColor.white)
    painter.setBrush(Qt.GlobalColor.white)
    _GLYPH_DRAWERS[glyph_key](painter)

    painter.end()
    return pixmap


def _glyph_expand(p: QPainter) -> None:
    """Fullscreen/zoom popup — four corner brackets, the standard
    "expand to full view" pictogram (same idea as the Unicode "⛶" this
    replaces, drawn explicitly instead of relying on font glyph support)."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    arm = 5.5
    corners = [
        # (corner x, corner y, horizontal arm dx, vertical arm dy)
        (4, 4, 1, 1), (18, 4, -1, 1), (4, 18, 1, -1), (18, 18, -1, -1),
    ]
    for cx, cy, dx, dy in corners:
        p.drawLine(int(cx), int(cy), int(cx + arm * dx), int(cy))
        p.drawLine(int(cx), int(cy), int(cx), int(cy + arm * dy))


def _glyph_checker(p: QPainter) -> None:
    """Background-cycle — a small 2x2 checkerboard, the actual pattern the
    button cycles through (checker/white/gray/black), rather than an
    unrelated symbol standing in for it."""
    p.setPen(Qt.PenStyle.NoPen)
    s = 6
    x0, y0 = 5, 5
    for row in range(2):
        for col in range(2):
            if (row + col) % 2 == 0:
                p.drawRect(int(x0 + col * s), int(y0 + row * s), s, s)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(Qt.GlobalColor.white)
    p.drawRect(QRectF(x0, y0, s * 2, s * 2))


def _glyph_region_focus(p: QPainter) -> None:
    """Sprite region toggle (off state) — a full frame with a smaller
    highlighted sub-rectangle inside it: "show where this crops from
    within the bigger picture", the actual thing this toggle does."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3, 3, 16, 16), 1, 1)
    p.drawRect(QRectF(8, 8, 7, 7))
    # Corner ticks on the inner region, like a crop/focus indicator.
    for x, y, dx, dy in ((8, 8, 1, 1), (15, 8, -1, 1), (8, 15, 1, -1), (15, 15, -1, -1)):
        p.drawLine(int(x), int(y), int(x + dx * 2.5), int(y))
        p.drawLine(int(x), int(y), int(x), int(y + dy * 2.5))


def _glyph_return_arrow(p: QPainter) -> None:
    """Sprite region toggle (on state) — "go back to the cropped sprite". A curved
    return-arrow glyph was tried here twice (see git history) and both times read as an
    ugly, disconnected/crooked shape at 22px — a real, twice-reported problem with the
    GLYPH CHOICE itself, not a drawing bug to fix a third time the same way. Replaced with
    the same frame-plus-inner-rectangle "crop" glyph _glyph_region_focus uses for the OFF
    state, just with the inner rectangle filled solid instead of outlined — reads as "the
    crop is now active/highlighted, click to return to it", no arrow geometry to get wrong."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3, 3, 16, 16), 1, 1)
    p.setBrush(Qt.GlobalColor.white)
    p.drawRect(QRectF(7.5, 7.5, 8, 8))


def _glyph_volume(p: QPainter) -> None:
    """Volume/mute toggle (unmuted state) — a speaker-plus-sound-waves glyph,
    replacing Qt's native SP_MediaVolume standard icon. Real reported bug:
    that icon renders as a fixed dark shape under Fusion style, which doesn't
    adapt to the app's palette — invisible on the dark theme specifically,
    since this button (setAutoRaise, no background) sits flat/transparent
    unlike the play/pause/stop/loop buttons next to it, which are readable
    regardless because they sit on AccentRoundButton/RoundToolButton's own
    colored circular backgrounds.

    Real reported follow-up: the two-arc version of this glyph looked "kind
    of cut off" — confirmed literal, not just a stylistic complaint: the
    outer arc's own bounding rect (15.5, 3, 8, 16) has a right edge at 23.5,
    past this glyph's 22px canvas, so the widest wave was genuinely clipped
    by the pixmap edge on every render. Redrawn as three concentric arcs
    (the "2-3 bars" a volume icon is expected to have), all sharing the same
    left edge and each bounded well within the canvas (widest right edge at
    20, 2px of margin) so none of them clip.

    Second real reported follow-up, once this glyph started being drawn via
    _draw_glyph_icon() (the backdrop-less, theme-colored path — see
    gui_widgets._mute_button_icon()) instead of only ever _draw_icon()'s
    fixed-white-on-a-colored-chip path: the arcs stayed hardcoded to
    Qt.GlobalColor.white regardless of caller, so they went invisible against
    a light theme's pale background — confirmed in a live screenshot: the
    cone recolored correctly (it just reuses whatever pen/brush the caller
    already set), but the arcs never did, since they explicitly overrode the
    pen to white. Fixed by capturing the CALLER's already-set color
    (p.pen().color(), read before this function's own first setPen() call)
    and reusing it for the arc pen too, instead of a hardcoded constant —
    correct in both drawing contexts: literal white when called via
    _draw_icon() (which itself sets the pen to white beforehand), the real
    theme color when called via _draw_glyph_icon().

    Third real reported follow-up: bounding an arc in a tall, narrow
    rectangle (as the two fixes above still did) draws a stretched slice of
    an ELLIPSE, not a circle — confirmed literal, not just a stylistic
    complaint: a genuinely round "sound wave" needs a SQUARE bounding rect
    (width == height) per arc. Redrawn as three concentric circles (shared
    center, increasing radius) instead of three independently-sized
    ellipses, matching how a real speaker icon's waves are conventionally
    drawn."""
    color = p.pen().color()
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(4, 8.5, 3, 5))
    cone = QPainterPath()
    cone.moveTo(7, 8.5)
    cone.lineTo(11, 5)
    cone.lineTo(11, 17)
    cone.lineTo(7, 13.5)
    cone.closeSubpath()
    p.drawPath(cone)
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    cx, cy = 11.0, 11.0
    for r in (3.0, 6.0, 9.0):
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), -50 * 16, 100 * 16)


def _glyph_volume_muted(p: QPainter) -> None:
    """Volume/mute toggle (muted state) — same speaker as _glyph_volume, sound
    waves replaced with an X. Same color-capture fix as _glyph_volume's own
    (see its docstring) — the X was equally hardcoded to white before."""
    color = p.pen().color()
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(4, 8.5, 3, 5))
    cone = QPainterPath()
    cone.moveTo(7, 8.5)
    cone.lineTo(11, 5)
    cone.lineTo(11, 17)
    cone.lineTo(7, 13.5)
    cone.closeSubpath()
    p.drawPath(cone)
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(14, 7, 20, 15)
    p.drawLine(20, 7, 14, 15)


def _glyph_chevron_left(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    tri = QPainterPath()
    tri.moveTo(14, 5)
    tri.lineTo(14, 17)
    tri.lineTo(6, 11)
    tri.closeSubpath()
    p.drawPath(tri)


def _glyph_chevron_right(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    tri = QPainterPath()
    tri.moveTo(8, 5)
    tri.lineTo(8, 17)
    tri.lineTo(16, 11)
    tri.closeSubpath()
    p.drawPath(tri)


def _glyph_play(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    tri = QPainterPath()
    tri.moveTo(7.5, 5)
    tri.lineTo(7.5, 17)
    tri.lineTo(17, 11)
    tri.closeSubpath()
    p.drawPath(tri)


def _glyph_pause(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(6, 5, 4, 12), 1, 1)
    p.drawRoundedRect(QRectF(13, 5, 4, 12), 1, 1)


def _glyph_stop(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(6, 6, 10, 10), 1.5, 1.5)


_LOOP_CX, _LOOP_CY = 11.0, 11.0
_LOOP_R_OUTER, _LOOP_R_INNER = 8.5, 5.8
_LOOP_ANGLE_START, _LOOP_ANGLE_END = 25.0, 305.0  # degrees; leaves an 80° open gap


def _loop_ring_point(radius: float, angle_deg: float) -> "tuple[float, float]":
    rad = math.radians(angle_deg)
    return (_LOOP_CX + radius * math.cos(rad), _LOOP_CY - radius * math.sin(rad))


def _glyph_loop(p: QPainter) -> None:
    """Repeat/loop toggle — a solid ring band with an arrowhead at its open
    end (the standard "repeat" pictogram), replacing Qt's native
    SP_BrowserReload standard icon. Real reported issue this replaces: that
    native glyph doesn't track this app's own theme at all, and read like a
    mismatched icon glued onto an otherwise consistent transport row.

    Drawn as a filled ring-segment (outer arc + inner arc, like the
    play/pause/stop glyphs' solid shapes) rather than a thin stroked arc —
    a first attempt using QPainter.drawArc() read fine enlarged but washed
    out to a plain, arrow-less "C" at this button's real ~16-28px on-screen
    size once actually rendered and looked at (not just eyeballed at 9x
    zoom); confirmed via rendering at every real size this glyph is
    actually shown at (16/20/24/28/32px) before settling on this version.
    The arrowhead's own base exactly matches the ring's own edge width
    (flared slightly past it) so it reads as one continuous shape, not a
    separate triangle stuck on — still legible from about 20px up; below
    that it reads as an open ring, which (with this button's own checked-
    state highlight and tooltip) still reads as "repeat" from convention."""
    color = p.pen().color()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)

    outer_rect = QRectF(
        _LOOP_CX - _LOOP_R_OUTER, _LOOP_CY - _LOOP_R_OUTER, 2 * _LOOP_R_OUTER, 2 * _LOOP_R_OUTER
    )
    inner_rect = QRectF(
        _LOOP_CX - _LOOP_R_INNER, _LOOP_CY - _LOOP_R_INNER, 2 * _LOOP_R_INNER, 2 * _LOOP_R_INNER
    )
    span = _LOOP_ANGLE_END - _LOOP_ANGLE_START
    ring = QPainterPath()
    ring.arcMoveTo(outer_rect, _LOOP_ANGLE_START)
    ring.arcTo(outer_rect, _LOOP_ANGLE_START, span)
    ring.lineTo(*_loop_ring_point(_LOOP_R_INNER, _LOOP_ANGLE_END))
    ring.arcTo(inner_rect, _LOOP_ANGLE_END, -span)
    ring.closeSubpath()
    p.drawPath(ring)

    flare, head_len = 1.6, 7.0
    outer_edge = _loop_ring_point(_LOOP_R_OUTER + flare, _LOOP_ANGLE_END)
    inner_edge = _loop_ring_point(_LOOP_R_INNER - flare, _LOOP_ANGLE_END)
    rad = math.radians(_LOOP_ANGLE_END)
    # Direction the tip points: tangent (continuing the ring's own curve)
    # blended with radially-outward — pure tangent reads as just more curve,
    # pure radial reads as a stub; the blend is what actually looks like a
    # distinct arrowhead once rendered (confirmed by comparing all three).
    tangent = (-math.sin(rad), -math.cos(rad))
    radial_out = (math.cos(rad), math.sin(rad))
    bx, by = tangent[0] + radial_out[0], tangent[1] + radial_out[1]
    blend_len = math.hypot(bx, by)
    bx, by = bx / blend_len, by / blend_len
    mid_x, mid_y = _loop_ring_point((_LOOP_R_OUTER + _LOOP_R_INNER) / 2, _LOOP_ANGLE_END)
    tip = (mid_x + head_len * bx, mid_y + head_len * by)
    head = QPainterPath()
    head.moveTo(*tip)
    head.lineTo(*outer_edge)
    head.lineTo(*inner_edge)
    head.closeSubpath()
    p.drawPath(head)


_GLYPH_DRAWERS = {
    "expand": _glyph_expand,
    "checker": _glyph_checker,
    "region_focus": _glyph_region_focus,
    "return_arrow": _glyph_return_arrow,
    "volume": _glyph_volume,
    "volume_muted": _glyph_volume_muted,
    "chevron_left": _glyph_chevron_left,
    "chevron_right": _glyph_chevron_right,
    "play": _glyph_play,
    "pause": _glyph_pause,
    "stop": _glyph_stop,
    "loop": _glyph_loop,
}

# Fixed style per button — colors chosen to tie into type_icons.py's own
# palette where there's a natural match (texture-related buttons use its
# same blue/teal), neutral gray for the purely-UI background-cycle button.
_ZOOM_COLOR = "#6366f1"
_BG_CYCLE_COLOR = "#6b7280"
_SPRITE_REGION_COLOR = "#06b6d4"
# Real reported issue: an earlier version used amber (#f59e0b) here, an
# orange that didn't fit anywhere near this cool blue/indigo/cyan/gray
# family — every other icon in this file picks its color from that same
# family (or type_icons.py's, itself the same family). _ZOOM_COLOR is
# literally this app's own accent/highlight color (theme.py's DARK.highlight
# is the identical #6366f1) — reused here instead of inventing yet another
# hue, since volume has no more inherent tie to any one color than zoom does.
_VOLUME_COLOR = _ZOOM_COLOR
# Matches type_icons.py's own Texture2DArray row color exactly (#1d4ed8) — a
# deliberate tie-in, this navigator only ever appears for that one type.
_ARRAY_NAV_COLOR = "#1d4ed8"


def get_zoom_icon() -> QIcon:
    return _get_icon("zoom", _ZOOM_COLOR, "expand")


def get_background_cycle_icon() -> QIcon:
    return _get_icon("bg_cycle", _BG_CYCLE_COLOR, "checker")


def get_sprite_region_icon() -> QIcon:
    return _get_icon("sprite_region_off", _SPRITE_REGION_COLOR, "region_focus")


def get_sprite_region_back_icon() -> QIcon:
    return _get_icon("sprite_region_on", _SPRITE_REGION_COLOR, "return_arrow")


def get_volume_icon() -> QIcon:
    return _get_icon("volume", _VOLUME_COLOR, "volume")


def get_volume_muted_icon() -> QIcon:
    return _get_icon("volume_muted", _VOLUME_COLOR, "volume_muted")


def get_array_prev_icon() -> QIcon:
    return _get_icon("array_prev", _ARRAY_NAV_COLOR, "chevron_left")


def _draw_glyph_icon(color_hex: str, glyph_key: str) -> QPixmap:
    """Same canvas size as _draw_icon() but with NO colored chip backdrop —
    for buttons that already render their own round colored QSS background
    (AccentRoundButton/RoundToolButton); a second colored square underneath
    would just look like a chip stuck inside a circle."""
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(color_hex)
    painter.setPen(color)
    painter.setBrush(color)
    _GLYPH_DRAWERS[glyph_key](painter)
    painter.end()
    return pixmap


_TRANSPORT_ICON_CACHE: dict = {}


def get_transport_icon(kind: str, color_hex: str) -> QIcon:
    """Play/pause/stop/loop glyphs for a media player's transport row — a
    plain colored glyph on a transparent background, unlike the toolbar
    icons above (those need their own chip; these already sit on a round
    AccentRoundButton/RoundToolButton QSS background). `color_hex` is
    resolved by the CALLER from the current theme, since the right glyph
    color depends on which button it's going on: AccentRoundButton
    (play/pause) always sits on the same fairly dark `highlight` color in
    both themes, so it wants theme.py's `highlighted_text` (always white);
    RoundToolButton (stop/loop) sits on `button`, which genuinely inverts
    between themes (dark navy in dark mode, pale off-white in light mode),
    so it wants `button_text` — white in dark theme, black-ish in light
    theme, matching the real reported request. Replaces Qt's native
    style.standardIcon(SP_MediaPlay/SP_MediaPause/SP_MediaStop/
    SP_BrowserReload) glyphs, which render in a fixed OS/Fusion-style color
    that never tracked this app's own theme at all — specifically flagged
    as looking like a mismatched "emoji" stuck onto the loop button."""
    key = f"{kind}:{color_hex}"
    cached = _TRANSPORT_ICON_CACHE.get(key)
    if cached is not None:
        return cached
    icon = QIcon(_draw_glyph_icon(color_hex, kind))
    _TRANSPORT_ICON_CACHE[key] = icon
    return icon


def get_array_next_icon() -> QIcon:
    return _get_icon("array_next", _ARRAY_NAV_COLOR, "chevron_right")
