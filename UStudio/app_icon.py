"""Procedural UStudio app mark — same "draw it with QPainterPath, don't ship an
asset file" convention preview_icons.py/type_icons.py already establish for
every other icon in this project (no image/SVG assets exist anywhere here).
Used by AboutDialog (a larger rendering) and available for the window/taskbar
icon via get_app_icon().

Design: a faceted "U" badge — two angle-tipped bars (echoing a crown-like
top, without literally reproducing any specific existing logo's geometry)
joined by a rounded base, with a small diamond "locator" mark floating above
the gap — reads as "pointing at/inspecting an asset" (UStudio's own job),
not just a bare letterform. Three fixed color variants (color/black/white),
matching the three-variant convention of the reference logo this was
requested to take inspiration from."""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPainterPath, QPixmap, QColor

# The app's own established accent/highlight color (theme.py's DARK.highlight,
# also reused by preview_icons.py's _ZOOM_COLOR) — the logo's "color" variant
# ties directly into the app's real visual identity instead of inventing a new
# brand hue from scratch.
ACCENT_COLOR = "#6366f1"

_ICON_CACHE: dict = {}


def _build_path() -> QPainterPath:
    """Builds the mark in a 200x240 local coordinate space; callers scale via
    QPainter transforms rather than baking a fixed pixel size into the path."""
    path = QPainterPath()

    # Left bar: angled top tip, straight outer/inner edges down into the base.
    path.moveTo(30, 62)
    path.lineTo(58, 50)
    path.lineTo(86, 62)
    path.lineTo(86, 158)
    path.lineTo(58, 158)
    path.lineTo(58, 82)
    path.lineTo(30, 94)
    path.closeSubpath()

    # Right bar: mirror of the left.
    right = QPainterPath()
    right.moveTo(170, 62)
    right.lineTo(142, 50)
    right.lineTo(114, 62)
    right.lineTo(114, 158)
    right.lineTo(142, 158)
    right.lineTo(142, 82)
    right.lineTo(170, 94)
    right.closeSubpath()
    path.addPath(right)

    # Rounded base joining both bars into one "U".
    base = QPainterPath()
    base.moveTo(30, 94)
    base.lineTo(58, 82)
    base.lineTo(58, 158)
    base.cubicTo(58, 195, 142, 195, 142, 158)
    base.lineTo(142, 82)
    base.lineTo(170, 94)
    base.lineTo(170, 160)
    base.cubicTo(170, 214, 30, 214, 30, 160)
    base.closeSubpath()
    path.addPath(base)

    # Small diamond "locator" mark floating above the U's own gap — the
    # "inspecting/pointing at an asset" idea the module docstring describes.
    diamond = QPainterPath()
    diamond.moveTo(100, 6)
    diamond.lineTo(122, 28)
    diamond.lineTo(100, 50)
    diamond.lineTo(78, 28)
    diamond.closeSubpath()
    path.addPath(diamond)

    return path.simplified()


_PATH = _build_path()


def render_logo_pixmap(size: int, variant: str = "color") -> QPixmap:
    """variant: 'color' (ACCENT_COLOR) | 'black' | 'white'. Transparent
    background — callers that need a solid tile (e.g. a taskbar icon on a
    platform with no alpha support) can flatten it themselves."""
    color = {"color": ACCENT_COLOR, "black": "#000000", "white": "#ffffff"}[variant]

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Path's own local box is 200x240 — scale to fill `size` with a small
    # margin, preserving aspect ratio, then center.
    margin = size * 0.08
    avail_w = size - 2 * margin
    avail_h = size - 2 * margin
    scale = min(avail_w / 200, avail_h / 240)
    offset_x = (size - 200 * scale) / 2
    offset_y = (size - 240 * scale) / 2

    painter.translate(offset_x, offset_y)
    painter.scale(scale, scale)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPath(_PATH)
    painter.end()
    return pixmap


def get_app_icon() -> QIcon:
    """The color variant, at the sizes Qt commonly requests for a window/
    taskbar icon — QIcon picks the closest match itself."""
    cached = _ICON_CACHE.get("app_icon")
    if cached is not None:
        return cached
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(render_logo_pixmap(size, "color"))
    _ICON_CACHE["app_icon"] = icon
    return icon
