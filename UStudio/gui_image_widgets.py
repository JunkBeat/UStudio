"""Image-like preview widgets: texture viewer (with zoom dialog), font specimen and the compact summary bar."""

from core.i18n import N_, tr
from io import BytesIO
from typing import Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PyQt6.QtCore import QEvent, Qt, QRectF, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QGraphicsItem, QGraphicsScene, QGraphicsView, QToolTip, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QStyle, QStyleOption, QVBoxLayout, QWidget
from core.object_metadata import COMPACT_SEPARATOR, coverage_part_text

from gui_common import coverage_highlight_color, pil_to_qpixmap
from helpers import wrap_tooltip
from app_settings import app_settings


class CompactSummaryBar(QWidget):
    """The one-line metadata caption under the preview ("128 × 128 px  ·  Format: DXT5" /
    "Koala.Audio  ·  AudioStartupConfig  ·  Koala.Audio.dll"), which wraps instead of growing.

    It used to be a plain fixed-height QLabel. A QLabel's minimum width is the width of its full
    text, so a long line — a MonoBehaviour's "Namespace · Class · Some.Long.Assembly.dll" is the
    usual one — became the minimum width of the whole preview pane and stretched it (or ran off
    its edge). Now: whole parts are packed onto lines greedily and every line is centred, so a
    wrap always falls BETWEEN parts and a separator never dangles at a line edge; a single part
    wider than the pane is broken by characters rather than overflowing; and the widget reports
    NO minimum width at all (Ignored horizontal policy), so its text can never push the pane wider.
    Its height follows its width (heightForWidth) and is one line, like the old bar, when the text
    fits.

    Styled by the app stylesheet's `#CompactSummaryBar` rule (background, top border, colour, font
    size) — the colour is read from the palette that rule sets, so a live theme switch just works."""

    _MIN_HEIGHT = 26      # a single line: the old fixed height
    _PAD_X = 10
    _PAD_Y = 5
    _LINE_GAP = 2
    _MIN_TEXT_WIDTH = 40  # never lay out for a sliver, however narrow the pane gets

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("CompactSummaryBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._summary = ""
        self._lines_cache: "tuple | None" = None

    # -- public API (QLabel's setText()/text() equivalents) ------------------------------------

    def set_summary(self, text: str) -> None:
        self._summary = text or ""
        self._lines_cache = None
        self.updateGeometry()
        self.update()

    def summary_text(self) -> str:
        return self._summary

    # -- layout --------------------------------------------------------------------------------

    def _parts(self) -> "list[str]":
        return [p.strip() for p in self._summary.split(COMPACT_SEPARATOR.strip()) if p.strip()]

    def _text_width(self, widget_width: int) -> int:
        return max(self._MIN_TEXT_WIDTH, widget_width - 2 * self._PAD_X)

    @staticmethod
    def _break_long(part: str, avail: int, fm: QFontMetrics) -> "list[str]":
        """A part that alone is wider than a line, split by characters."""
        chunks, cur = [], ""
        for ch in part:
            if cur and fm.horizontalAdvance(cur + ch) > avail:
                chunks.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            chunks.append(cur)
        return chunks

    def _layout_lines(self, widget_width: int) -> "list[str]":
        self.ensurePolished()  # the stylesheet's font-size must be in effect before measuring
        fm = self.fontMetrics()
        avail = self._text_width(widget_width)
        key = (self._summary, avail, self.font().key())
        if self._lines_cache is not None and self._lines_cache[0] == key:
            return self._lines_cache[1]
        sep = COMPACT_SEPARATOR
        lines: "list[str]" = []
        cur = ""
        for part in self._parts():
            if fm.horizontalAdvance(part) > avail:
                chunks = self._break_long(part, avail, fm)
                # the first chunk may still share the current line; the rest each start their own
                candidate = cur + sep + chunks[0] if cur else chunks[0]
                if cur and fm.horizontalAdvance(candidate) <= avail:
                    cur = candidate
                else:
                    if cur:
                        lines.append(cur)
                    cur = chunks[0]
                for chunk in chunks[1:]:
                    lines.append(cur)
                    cur = chunk
                continue
            candidate = cur + sep + part if cur else part
            if cur and fm.horizontalAdvance(candidate) > avail:
                lines.append(cur)
                cur = part
            else:
                cur = candidate
        if cur:
            lines.append(cur)
        self._lines_cache = (key, lines)
        return lines

    def _height_for(self, widget_width: int) -> int:
        n = max(1, len(self._layout_lines(widget_width)))
        lh = self.fontMetrics().height()
        return max(self._MIN_HEIGHT, 2 * self._PAD_Y + n * lh + (n - 1) * self._LINE_GAP)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._height_for(width)

    def sizeHint(self) -> QSize:
        w = self.width() if self.width() > 0 else 200
        return QSize(w, self._height_for(w))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self._MIN_HEIGHT)  # width 0: the text must never widen the pane

    # -- painting ------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        # background + top border come from the stylesheet rule
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)
        lines = self._layout_lines(self.width())
        if not any(lines):
            return
        base_pen = self.palette().color(QPalette.ColorRole.WindowText)
        painter.setPen(base_pen)
        lh = self.fontMetrics().height()
        total = len(lines) * lh + (len(lines) - 1) * self._LINE_GAP
        y = max(self._PAD_Y, (self.height() - total) // 2)  # vertically centred; padded when taller
        for line in lines:
            self._draw_line(painter, line, y, lh, base_pen)
            y += lh + self._LINE_GAP

    def _draw_line(self, painter: QPainter, line: str, y: int, lh: int, base_pen: QColor) -> None:
        """One centred line. The "Cyrillic support" part (see core.object_metadata.coverage_part_text) is drawn
        bold in green so it stands out; every other line is plain centred text, as before."""
        sep, coverage = COMPACT_SEPARATOR, coverage_part_text()
        width = self.width() - 2 * self._PAD_X
        pieces = line.split(sep)
        if coverage not in pieces:
            painter.drawText(self._PAD_X, y, width, lh,
                             int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter), line)
            return
        normal = self.font()
        bold = QFont(normal)
        bold.setBold(True)
        highlight = coverage_highlight_color(self.palette())
        segments = []   # (text, font, colour)
        for i, piece in enumerate(pieces):
            if i:
                segments.append((sep, normal, base_pen))
            is_coverage = piece == coverage
            segments.append((piece, bold if is_coverage else normal, highlight if is_coverage else base_pen))
        widths = [QFontMetrics(font).horizontalAdvance(text) for text, font, _ in segments]
        x = self._PAD_X + max(0, (width - sum(widths)) // 2)
        for (text, font, colour), seg_width in zip(segments, widths):
            painter.setFont(font)
            painter.setPen(colour)
            painter.drawText(x, y, seg_width + 2, lh, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
            x += seg_width
        painter.setFont(normal)
        painter.setPen(base_pen)

    def changeEvent(self, event) -> None:
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange, QEvent.Type.PaletteChange):
            self._lines_cache = None
            self.updateGeometry()
            self.update()
        super().changeEvent(event)


class SpriteOutlineItem(QGraphicsItem):
    """The «Контуры спрайтов» overlay: one rectangle per sprite (core/sprite_outlines.SpriteOutline, in the
    picture's pixel coordinates), drawn above the texture. Cosmetic pens without antialiasing: the lines stay one
    crisp screen pixel at every zoom. A dark halo under a light line keeps them visible on any picture and backdrop
    (the colours are the picture's, not the theme's). The hovered one is highlighted."""

    _LINE = QColor("#3fd8ff")
    _HALO = QColor(0, 0, 0, 170)
    _HOVER_LINE = QColor("#ffd400")
    _HOVER_FILL = QColor(255, 212, 0, 45)

    def __init__(self, outlines):
        super().__init__()
        self.rects = [QRectF(o.x, o.y, o.width, o.height) for o in outlines]
        self.hovered = -1
        bounds = QRectF()
        for rect in self.rects:
            bounds = bounds.united(rect)
        self._bounds = bounds.adjusted(-2, -2, 2, 2)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self) -> QRectF:
        return self._bounds

    @staticmethod
    def _pen(color: QColor, width: int) -> QPen:
        pen = QPen(color, width)
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        return pen

    def paint(self, painter, option, widget=None) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._pen(self._HALO, 3))
        painter.drawRects(self.rects)
        painter.setPen(self._pen(self._LINE, 1))
        painter.drawRects(self.rects)
        if 0 <= self.hovered < len(self.rects):
            rect = self.rects[self.hovered]
            painter.fillRect(rect, self._HOVER_FILL)
            painter.setPen(self._pen(self._HALO, 4))
            painter.drawRect(rect)
            painter.setPen(self._pen(self._HOVER_LINE, 2))
            painter.drawRect(rect)
        painter.restore()


class ImagePreviewWidget(QGraphicsView):
    """Zoom/pan image viewer with a checkerboard background (so texture alpha is
    visible) — used by main.py's Preview tab for Texture2D/Texture2DArray/Sprite
    rows."""

    # Grid (checkerboard, default) / white / gray / black — cycled by
    # cycle_background(), which the toolbar's small background-toggle button
    # calls. Grid first since that's the default every image starts on.
    _BG_MODES = ("checker", "white", "gray", "black")
    _BG_SOLID_COLORS = {"white": QColor("white"), "gray": QColor("#808080"), "black": QColor("black")}

    doubleClicked = pyqtSignal()  # emitted on a double-click anywhere in the view —
    # preview_panel.py wires this to opening the fullscreen TextureZoomDialog, an
    # extra, faster path next to the small "⤢" button.

    # Emitted whenever R/G/B channel isolation changes (via the keyboard toggle
    # below) — carries the new (r_on, g_on, b_on) tuple so preview_panel.py can
    # keep its own small indicator label in sync without polling.
    channelsChanged = pyqtSignal(tuple)
    # A double-click on a sprite outline (set_outlines): the Sprite's ObjectReader. That double-click does not
    # emit doubleClicked.
    outlineActivated = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = None
        self._outlines: list = []
        self._outline_item: Optional[SpriteOutlineItem] = None
        self._fill_height_on_resize = False
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # Wheel zoom is anchored by hand in wheelEvent() (see there).
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        # The checkerboard is painted in VIEWPORT pixels (drawBackground), not scene
        # coordinates. With the default (smart) update mode, scrolling — now routine,
        # since dragging/zooming can move the picture anywhere — makes QGraphicsView
        # shift the already-painted pixels and repaint only the newly exposed strip,
        # so the grid slid with the picture and showed a seam of the wrong phase at
        # the edge. Repainting the whole viewport keeps the grid pinned and seamless.
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._bg_mode = "checker"
        self._wheel_zoom_enabled = True  # see set_wheel_zoom_enabled()
        self.user_zoomed = False  # set by a wheel zoom; cleared by set_image()/fit/1:1/fill
        self._checker_tile = self._make_checker_tile()
        # R/G/B channel isolation (AssetStudio-style) — plain R/G/B keys (no
        # modifier), scoped to this widget alone via its own keyPressEvent, not
        # global QShortcuts: Ctrl+G already opens the main window's Quick Jump
        # dialog window-wide, and a Ctrl+G channel toggle here would make Qt
        # treat the two as an ambiguous shortcut (neither firing) whenever this
        # widget has focus. Plain, unmodified keys scoped to this widget avoid
        # that collision entirely. Sticky across set_image() calls — comparing
        # a texture's channels across several selections in a row is the whole
        # point, so a fresh image shouldn't silently reset it back to "all on".
        self._channel_mask = [True, True, True]  # R, G, B
        self._source_pixmap: Optional[QPixmap] = None
        # No setBackgroundBrush() — see drawBackground() below. A brush set that
        # way is painted in SCENE coordinates by QGraphicsView, so the visible
        # portion of the (repeating) tile pattern shifts every time the scene
        # rect or the view's scroll/transform changes — exactly what made the
        # checkerboard appear to "jump" whenever the selection switched between
        # differently-sized textures. Painting it directly onto the viewport in
        # drawBackground() instead keeps the pattern pinned to the widget itself.

    @staticmethod
    def _make_checker_tile() -> QPixmap:
        size = 16
        tile = QPixmap(size * 2, size * 2)
        tile.fill(QColor("#2a2a2a"))
        painter = QPainter(tile)
        painter.fillRect(0, 0, size, size, QColor("#353535"))
        painter.fillRect(size, size, size, size, QColor("#353535"))
        painter.end()
        return tile

    def drawBackground(self, painter, rect) -> None:
        if self._bg_mode == "checker":
            painter.save()
            # resetTransform() so the tile is drawn in VIEWPORT (device) pixels,
            # not scene coordinates — see the comment in __init__ for why.
            painter.resetTransform()
            painter.drawTiledPixmap(self.viewport().rect(), self._checker_tile)
            painter.restore()
        else:
            painter.fillRect(rect, self._BG_SOLID_COLORS[self._bg_mode])

    def cycle_background(self) -> str:
        """Grid -> white -> gray -> black -> Grid. Returns the new mode name, for
        the toggle button to update its own tooltip with."""
        idx = (self._BG_MODES.index(self._bg_mode) + 1) % len(self._BG_MODES)
        self._bg_mode = self._BG_MODES[idx]
        self.viewport().update()
        return self._bg_mode

    def set_image(self, pixmap: QPixmap) -> None:
        self.user_zoomed = False
        self._fill_height_on_resize = False
        self._source_pixmap = pixmap
        # scene.clear() deletes the outline item too: a new picture starts without outlines (set_outlines again)
        self._outline_item = None
        self._outlines = []
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(self._channel_masked_pixmap(pixmap))
        self._apply_scene_rect(pixmap)
        self.resetTransform()
        # 1:1 by default, but only when the image actually fits the current
        # viewport — a texture larger than the preview area (or the popup window,
        # even maximized) showing at native resolution just means panning around
        # to see any of it at all, which isn't a useful default; fall back to
        # "Растянуть" (scale-to-fit) for anything that doesn't fit as-is.
        viewport_size = self.viewport().size()
        if pixmap.width() > viewport_size.width() or pixmap.height() > viewport_size.height():
            self.fit_in_view()
        else:
            self.zoom_actual_size()
        self._update_smoothing()

    def set_free_pan(self, enabled: bool) -> None:
        """Lets the picture be dragged anywhere with the mouse even when it is
        smaller than the view (or fitted): the scene is made much larger than the
        pixmap so the view can always scroll, and the scrollbars are hidden since
        they would always be present. Off by default (FontPreviewWidget's specimen
        keeps its normal scrollbars)."""
        self._free_pan = enabled
        policy = Qt.ScrollBarPolicy.ScrollBarAlwaysOff if enabled else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)
        if self._source_pixmap is not None:
            self._apply_scene_rect(self._source_pixmap)

    def _apply_scene_rect(self, pixmap: QPixmap) -> None:
        rect = QRectF(pixmap.rect())
        if getattr(self, "_free_pan", False):
            vp = self.viewport().size()
            rect = rect.adjusted(-(rect.width() + vp.width()), -(rect.height() + vp.height()),
                                 rect.width() + vp.width(), rect.height() + vp.height())
        self._scene.setSceneRect(rect)

    def _content_rect(self) -> QRectF:
        return self._pixmap_item.boundingRect() if self._pixmap_item is not None else self._scene.sceneRect()

    def _recenter(self) -> None:
        if getattr(self, "_free_pan", False) and self._pixmap_item is not None:
            self.centerOn(self._pixmap_item)

    def fit_in_view(self) -> None:
        """"Растянуть" — scale-to-fit, aspect preserved. Stays in effect across a
        resize (re-fitted from resizeEvent) until the next set_image()/
        zoom_actual_size() call switches back to a fixed 1:1 scale."""
        self.user_zoomed = False
        self._stretch_on_resize = True
        self._fill_height_on_resize = False
        if self._pixmap_item is not None:
            self.fitInView(self._content_rect(), Qt.AspectRatioMode.KeepAspectRatio)
            self._update_smoothing()

    def zoom_actual_size(self) -> None:
        """"1:1" — native resolution, no scaling. The default for a newly loaded
        image (textures are shown at their real size unless the user asks to fit)."""
        self.user_zoomed = False
        self._stretch_on_resize = False
        self._fill_height_on_resize = False
        self.resetTransform()
        self._recenter()
        self._update_smoothing()

    def fill_height_top_left(self) -> None:
        """Scales uniformly (x and y by the same factor, so aspect ratio is
        preserved) so the content's height exactly fills the viewport, and aligns
        it to the top-left corner instead of QGraphicsView's default centering.
        Used by FontPreviewWidget: a font specimen that's wider than the viewport
        used to open centered, meaning the visible portion started somewhere in
        the horizontal middle of the sample text — the user had to scroll left by
        hand just to see its beginning. Stays in effect across a resize (like
        fit_in_view()'s _stretch_on_resize) until the next set_image() call."""
        self.user_zoomed = False
        self._stretch_on_resize = False
        self._fill_height_on_resize = True
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.resetTransform()
        if self._pixmap_item is None:
            return
        viewport_h = self.viewport().height()
        pixmap_h = self._pixmap_item.pixmap().height()
        if viewport_h > 0 and pixmap_h > 0:
            factor = viewport_h / pixmap_h
            self.scale(factor, factor)
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # A picture set before the widget was laid out (the first texture, while its page was
        # still hidden) was centred and given its scene margins for a tiny default viewport; now
        # that the real size is known, do both again — otherwise it sits off to one side.
        if getattr(self, "_free_pan", False) and self._source_pixmap is not None:
            self._apply_scene_rect(self._source_pixmap)
        if getattr(self, "_stretch_on_resize", False):
            self.fit_in_view()
        elif getattr(self, "_fill_height_on_resize", False):
            self.fill_height_top_left()
        elif not self.user_zoomed:
            self._recenter()

    def restore_user_zoom(self, transform, h_scroll: int, v_scroll: int) -> None:
        """Re-applies a zoom/position the user set, after set_image() replaced the
        picture (set_image() ends in fit_in_view()/zoom_actual_size(), which switch
        the re-fit-on-resize flags ON — those must be cleared again or the very
        next resize silently discards the zoom)."""
        self._stretch_on_resize = False
        self._fill_height_on_resize = False
        self.setTransform(transform)
        self.horizontalScrollBar().setValue(h_scroll)
        self.verticalScrollBar().setValue(v_scroll)
        self.user_zoomed = True

    def set_wheel_zoom_enabled(self, enabled: bool) -> None:
        """Off for FontPreviewWidget's specimen view (real reported request) —
        a font specimen is meant to be read at the sizes it was rendered at,
        not scaled; wheel scrolling still works normally (falls through to
        QGraphicsView's own default wheelEvent, which scrolls when there's a
        scrollbar to move) once zoom is disabled. TextureZoomDialog/the
        ordinary Texture2D/Sprite preview leave this on (the default) —
        zoom is exactly what those are for."""
        self._wheel_zoom_enabled = enabled

    def wheelEvent(self, event) -> None:
        if not self._wheel_zoom_enabled:
            super().wheelEvent(event)
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        # The user now owns the zoom: a later resize must not silently re-fit
        # it away (fit_in_view()/fill_height_top_left() re-apply on resize while
        # their flags are set). The next set_image()/fit/1:1/fill hands it back.
        self.user_zoomed = True
        self._stretch_on_resize = False
        self._fill_height_on_resize = False
        # Zoom around the cursor: remember which scene point is under it, scale, then
        # shift the view so that same point is under the cursor again (done by hand —
        # AnchorUnderMouse relies on QGraphicsView's last-seen mouse-move position,
        # which is stale/absent for a wheel event arriving first).
        pos = event.position().toPoint()
        anchor = self.mapToScene(pos)
        self.scale(factor, factor)
        moved = self.mapToScene(pos)
        self.translate(moved.x() - anchor.x(), moved.y() - anchor.y())
        self._update_smoothing()

    def _update_smoothing(self) -> None:
        """Smooth (bilinear) when shrinking, nearest-neighbour once magnified past
        100% — zooming in on a texture is for inspecting real pixels, and bilinear
        turns them into blur."""
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.transform().m11() < 1.0)

    def background_mode(self) -> str:
        return self._bg_mode

    def set_background_mode(self, mode: str) -> None:
        if mode in self._BG_MODES:
            self._bg_mode = mode
            self.viewport().update()

    # --- «Контуры спрайтов» ---

    def set_outlines(self, outlines: list) -> None:
        """Draws these sprite outlines (core/sprite_outlines.SpriteOutline, picture pixel coordinates) over the
        picture, or removes them ([]). Kept until the next set_image()."""
        if self._outline_item is not None:
            self._scene.removeItem(self._outline_item)
            self._outline_item = None
        self._outlines = list(outlines or [])
        if self._outlines and self._pixmap_item is not None:
            self._outline_item = SpriteOutlineItem(self._outlines)
            self._scene.addItem(self._outline_item)
            self.viewport().setMouseTracking(True)      # hover highlight without a pressed button
        self.viewport().update()

    def outlines(self) -> list:
        return list(self._outlines)

    def outline_at(self, view_pos) -> int:
        """Index of the outline under a viewport point (the smallest one, when they nest), or -1."""
        if self._outline_item is None:
            return -1
        point = self.mapToScene(view_pos)
        best, best_area = -1, None
        for i, rect in enumerate(self._outline_item.rects):
            if rect.contains(point):
                area = rect.width() * rect.height()
                if best_area is None or area < best_area:
                    best, best_area = i, area
        return best

    def _set_hovered_outline(self, index: int) -> None:
        if self._outline_item is not None and self._outline_item.hovered != index:
            self._outline_item.hovered = index
            self._outline_item.update()
            self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self._outline_item is not None:
            self._set_hovered_outline(self.outline_at(event.position().toPoint()))

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._set_hovered_outline(-1)

    def outline_tooltip(self, index: int) -> str:
        outline = self._outlines[index]
        size = tr("{width} × {height} пикс.", width=round(outline.width), height=round(outline.height))
        if outline.sprite is None:
            return tr("Спрайт из файла, который не загружен") + "\n" + size
        return "\n".join((outline.name or tr("Спрайт без имени"), size, tr("Двойной щелчок — перейти к спрайту")))

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip and self._outline_item is not None:
            index = self.outline_at(event.pos())
            if index >= 0:
                QToolTip.showText(event.globalPos(), wrap_tooltip(self.outline_tooltip(index)), self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.outline_at(event.position().toPoint())
        if index >= 0 and self._outlines[index].sprite is not None:
            event.accept()
            self.outlineActivated.emit(self._outlines[index].sprite)
            return
        super().mouseDoubleClickEvent(event)
        self.doubleClicked.emit()

    def _channel_masked_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Returns `pixmap` with any disabled channel (self._channel_mask, R/G/B
        at indices 0/1/2) zeroed out — alpha is always left untouched, so
        transparency stays exactly as it was regardless of which color channels
        are toggled. Returns `pixmap` itself, unmodified, when every channel is
        enabled (the common case) — no pointless copy/convert on every image
        load for a feature that's off by default."""
        if pixmap.isNull() or all(self._channel_mask):
            return pixmap
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        w, h = image.width(), image.height()
        if w <= 0 or h <= 0:
            return pixmap
        bytes_per_line = image.bytesPerLine()
        ptr = image.bits()
        ptr.setsize(bytes_per_line * h)
        # A view onto the QImage's own buffer (not a copy) — writes below land
        # directly in `image`, which is a freshly detached QImage from
        # toImage()/convertToFormat() above, so this can't alias any other
        # pixmap's data.
        arr = np.ndarray(shape=(h, bytes_per_line // 4, 4), dtype=np.uint8, buffer=ptr)
        for i, enabled in enumerate(self._channel_mask):
            if not enabled:
                arr[:, :w, i] = 0
        return QPixmap.fromImage(image)

    def channel_state(self) -> tuple:
        return tuple(self._channel_mask)

    def toggle_channel(self, index: int) -> None:
        """Flips R(0)/G(1)/B(2) isolation and refreshes the displayed pixmap in
        place — re-applies masking to the untouched self._source_pixmap (never
        the already-displayed, possibly-already-masked one, which would let
        toggling a channel back on stay stuck at zero) without resetting the
        current pan/zoom, unlike set_image()."""
        if self._source_pixmap is None:
            return
        self._channel_mask[index] = not self._channel_mask[index]
        if self._pixmap_item is not None:
            self._pixmap_item.setPixmap(self._channel_masked_pixmap(self._source_pixmap))
        self.channelsChanged.emit(self.channel_state())

    # Windows virtual-key codes for R/G/B — these are PHYSICAL-key-position
    # codes (VK_R=0x52/VK_G=0x47/VK_B=0x42), not translated characters, so
    # they fire the same way regardless of which keyboard layout is active.
    # Real reported bug: matching on Qt.Key.Key_R/_G/_B (via event.key()) only
    # worked with an English layout active — Qt's own key-code translation for
    # letter keys isn't reliably layout-independent on Windows for every
    # layout, particularly non-Latin ones. nativeVirtualKey() reads the raw OS
    # VK code before any of that translation, sidestepping the problem.
    _CHANNEL_VK_CODES = {0x52: 0, 0x47: 1, 0x42: 2}

    def keyPressEvent(self, event) -> None:
        # Plain R/G/B only (no modifier) — see the __init__ comment for why
        # these are scoped to this widget's own keyPressEvent (only fires while
        # it has focus) instead of app-wide QShortcuts.
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and self._source_pixmap is not None:
            index = self._CHANNEL_VK_CODES.get(event.nativeVirtualKey())
            if index is None:
                # Fallback for when there's no native virtual key to read (a
                # synthetic QKeyEvent, as in tests, or a non-Windows Qt build)
                # — tracks the English layout correctly, just not every other
                # one, which is exactly why the VK-code path above is tried
                # first.
                channel_by_key = {Qt.Key.Key_R: 0, Qt.Key.Key_G: 1, Qt.Key.Key_B: 2}
                index = channel_by_key.get(Qt.Key(event.key()))
            if index is not None:
                self.toggle_channel(index)
                event.accept()
                return
        super().keyPressEvent(event)


class TextureZoomDialog(QDialog):
    """Full-window texture preview with mouse-wheel zoom (ImagePreviewWidget's own
    wheelEvent, reused as-is) — opened via the "⤢" button next to a Texture2D/
    Sprite preview. Not a port of anything: AssetStudioGUI's own texture preview has
    no zoom/pop-out at all (confirmed against its source — it's a static
    fit-if-larger-else-center choice), this is new UI built directly from how the
    user described wanting it."""

    _BG_LABELS = {"checker": N_("сетка"), "white": N_("белый"), "gray": N_("серый"), "black": N_("чёрный")}

    def __init__(self, pixmap: QPixmap, title: str, parent=None, background_mode: str = "checker"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        # Sized against the screen's AVAILABLE area (excludes the taskbar) with room
        # for the title bar/frame, so the window never reaches behind the taskbar.
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        self.resize(min(1000, int(avail.width() * 0.9)), min(800, int(avail.height() * 0.85)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        self._btn_bg = QPushButton(tr("Сменить фон"))
        self._btn_bg.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_bg.clicked.connect(self._cycle_background)
        bar.addWidget(self._btn_bg)
        bar.addStretch(1)
        layout.addLayout(bar)
        self._view = ImagePreviewWidget()
        self._view.set_free_pan(True)
        # Same background as the preview area the dialog was opened from.
        self._view.set_background_mode(background_mode)
        self._update_bg_tooltip()
        layout.addWidget(self._view, 1)
        # set_image()'s fit-vs-1:1 decision reads the view's CURRENT viewport size —
        # at construction time (before the dialog has ever been laid out/shown) that
        # size is still whatever Qt's default is, not the real size this dialog
        # is about to have. Deferred to showEvent so the decision sees the actual
        # on-screen size instead.
        self._pending_pixmap = pixmap

    def _cycle_background(self) -> None:
        self._view.cycle_background()
        self._update_bg_tooltip()

    def _update_bg_tooltip(self) -> None:
        self._btn_bg.setToolTip(tr("Фон: {background} (нажмите для переключения)",
                                   background=tr(self._BG_LABELS[self._view.background_mode()])))

    def _fit_on_screen(self) -> None:
        """Keeps the whole window (frame included) inside the screen's available
        area — the taskbar is not part of it."""
        avail = self.screen().availableGeometry()
        frame = self.frameGeometry()
        x = min(max(frame.x(), avail.left()), max(avail.right() - frame.width() + 1, avail.left()))
        y = min(max(frame.y(), avail.top()), max(avail.bottom() - frame.height() + 1, avail.top()))
        if (x, y) != (frame.x(), frame.y()):
            self.move(x, y)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_on_screen()
        if self._pending_pixmap is not None:
            self._view.set_image(self._pending_pixmap)
            self._pending_pixmap = None


class FontPreviewWidget(QWidget):
    """Font specimen preview: renders sample text at several sizes (via PIL, reusing
    ImagePreviewWidget/pil_to_qpixmap — a specimen is just an image) plus a text
    field below to preview custom text live. AssetStudioGUI's own font preview has
    a fixed 8-size specimen with no custom-text input at all (confirmed against its
    source) — the custom-text field here is new UI, not a port."""

    _DEFAULT_TEXT = "The quick brown fox jumps over the lazy dog 0123456789"
    _SIZES = (12, 18, 24, 36, 48, 72)
    _RENDER_DEBOUNCE_MS = 150

    # Same QSettings store theme.py/config.py already use, own group so this key
    # can't collide with theirs.
    _SETTINGS_GROUP = "font_preview"
    _SETTINGS_KEY = "custom_text"
    _HISTORY_KEY = "text_history"
    _HISTORY_LIMIT = 8
    # Ready samples in the drop-down: (what it is, the text). The first is also the placeholder / default.
    _PRESETS = (
        (N_("Английская фраза"), _DEFAULT_TEXT),
        (N_("Русская фраза"), "Съешь же ещё этих мягких французских булок, да выпей чаю 0123456789"),  # i18n: keep
        (N_("Русский алфавит"), "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ абвгдеёжзийклмнопрстуфхцчшщъыьэюя"),  # i18n: keep
        (N_("Английский алфавит"), "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz"),
        (N_("Цифры и знаки"), "0123456789 .,:;!?-—()[]«»\"'@#%&*+=/"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_data: Optional[bytes] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._image_view = ImagePreviewWidget()
        # Wheel zoom ON (real request — it used to be off so the wheel scrolled).
        # A user zoom survives re-renders (see _render) and resizes; double-click
        # returns to the fitted view.
        self._image_view.set_wheel_zoom_enabled(True)
        self._image_view.doubleClicked.connect(self._reset_zoom)
        # Explicit Expanding/Expanding (not just relying on QGraphicsView's default
        # policy) so the specimen genuinely claims the whole tab's available height
        # instead of only its natural image height — a multi-size specimen (6 sizes
        # up to 72pt) can easily be taller than the preview area, at which point
        # ScrollBarAsNeeded (also explicit here, not just relying on the Qt default)
        # is what lets the rest be reached instead of it being clipped.
        self._image_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._image_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self._image_view, 1)

        # An editable drop-down: the field used to be a bare line edit whose placeholder (the English sample
        # sentence) looked like a caption, so nobody noticed it could be typed into. The list offers ready samples
        # (Russian ones included) and the strings the user typed before; the line edit inside it is still
        # `_text_edit`, so everything below works on it exactly as before. It is the page's toolbar row, at the TOP
        # right under the preview tabs, with no caption (user request — it used to sit under the specimen with a
        # «Предпросмотр:» label).
        text_row = QHBoxLayout()
        text_row.setContentsMargins(0, 0, 0, 0)
        self._text_combo = QComboBox()
        self._text_combo.setEditable(True)
        self._text_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._text_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._text_combo.setMinimumContentsLength(10)
        self._text_combo.setToolTip(wrap_tooltip(tr("Введите свой текст или выберите готовый пример из списка. "
                                                    "Ранее введённые строки запоминаются.")))
        self._text_edit = self._text_combo.lineEdit()
        self._text_edit.setPlaceholderText(self._DEFAULT_TEXT)
        self._history = [t for t in app_settings().value(
            f"{self._SETTINGS_GROUP}/{self._HISTORY_KEY}", [], type=list) if isinstance(t, str) and t]
        self._fill_text_combo()
        text_row.addWidget(self._text_combo, 1)
        layout.insertLayout(0, text_row)                 # above the specimen
        # Restored once here at construction, not re-loaded per set_font_data()
        # call — the field is no longer cleared when the selection switches to a
        # different Font object (see set_font_data() below), so whatever the user
        # typed just keeps living in the widget for the rest of the session; this
        # initial restore is only for surviving an app restart.
        persisted = app_settings().value(f"{self._SETTINGS_GROUP}/{self._SETTINGS_KEY}", "", type=str)
        self._text_edit.setText(persisted)   # also empties the field the first list item filled in
        self._text_edit.textChanged.connect(self._schedule_render)
        self._text_edit.textChanged.connect(self._save_text)
        # On Enter only: editingFinished also fires when the field merely loses focus, i.e. as the user opens the
        # drop-down, and rebuilding the list then would pull it away. (The text itself is saved as it is typed.)
        self._text_edit.returnPressed.connect(self._remember_text)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render)

    def set_font_data(self, font_data: bytes) -> None:
        self._font_data = font_data
        # No longer clears self._text_edit here — the whole point of persisting
        # custom text across restarts is defeated if it's also wiped the instant
        # the user clicks a different Font row within the same session.
        self._render()

    def _reset_zoom(self) -> None:
        self._image_view.fill_height_top_left()

    def _save_text(self) -> None:
        app_settings().setValue(
            f"{self._SETTINGS_GROUP}/{self._SETTINGS_KEY}", self._text_edit.text()
        )

    def _fill_text_combo(self) -> None:
        """The drop-down list: the ready samples, then (after a separator) what the user typed before."""
        self._text_combo.blockSignals(True)
        self._text_combo.clear()
        self._text_combo.addItems([text for _name, text in self._PRESETS])
        for i, (name, _text) in enumerate(self._PRESETS):
            self._text_combo.setItemData(i, name, Qt.ItemDataRole.ToolTipRole)
        if self._history:
            self._text_combo.insertSeparator(self._text_combo.count())
            self._text_combo.addItems(self._history)
        self._text_combo.setCurrentIndex(-1)
        self._text_combo.blockSignals(False)

    def _remember_text(self) -> None:
        """Called when the user finishes typing (Enter / leaves the field): a new string joins the list."""
        text = self._text_edit.text().strip()
        known = {t for _name, t in self._PRESETS}
        if not text or text in known:
            return
        if text in self._history:
            self._history.remove(text)
        self._history.insert(0, text)
        del self._history[self._HISTORY_LIMIT:]
        app_settings().setValue(f"{self._SETTINGS_GROUP}/{self._HISTORY_KEY}", self._history)
        typed = self._text_edit.text()
        self._fill_text_combo()
        self._text_edit.setText(typed)

    def _schedule_render(self) -> None:
        self._render_timer.start(self._RENDER_DEBOUNCE_MS)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Still reported blurry even with supersampling (see _render()'s
        # content_scale comment below): the specimen was rendered once at a
        # fixed resolution and then only ever RESCALED by
        # ImagePreviewWidget.fill_height_top_left() to match whatever height
        # the preview area happened to have — including scaling UP well past
        # the specimen's native resolution on a large window/panel, which is
        # inherently blurry regardless of supersampling. Re-rendering (debounced,
        # same timer as a text edit) on resize means the specimen gets rebuilt
        # at a resolution matching the new size instead.
        # A zoomed-in specimen is left alone: re-rendering for the new size would
        # throw the user's zoom away.
        if self._font_data is not None and not self._image_view.user_zoomed:
            self._schedule_render()

    # Rendered at this multiple of every target size/padding, then downsampled
    # with a high-quality filter — noticeably smoother edges than relying on
    # FreeType's own antialiasing alone at native resolution, which is what
    # looked jagged especially once fill_height_top_left() scales the specimen
    # up further to fill the preview area (magnifying whatever aliasing was
    # already there).
    _SUPERSAMPLE = 2
    _LABEL_FONT_SIZE = 12
    _LABEL_COLOR = "#888888"
    _MAX_CONTENT_SCALE = 4.0

    def _natural_total_height(self, text: str) -> int:
        """The specimen's height at content_scale=1 (literal _SIZES, no
        supersampling) — a cheap reference used only to size the REAL render
        below; see _render()'s content_scale comment for why this exists."""
        total = 0
        for size in self._SIZES:
            try:
                font = ImageFont.truetype(BytesIO(self._font_data), size)
            except Exception:
                continue
            bbox = font.getbbox(text) if hasattr(font, "getbbox") else (0, 0, *font.getsize(text))
            total += (bbox[3] - bbox[1]) + 10 * 2
        return total

    def _render(self) -> None:
        if not self._font_data:
            return
        text = self._text_edit.text() or self._DEFAULT_TEXT
        ss = self._SUPERSAMPLE

        # Still reported blurry even with supersampling: fill_height_top_left()
        # (ImagePreviewWidget) scales the FINISHED specimen image up to fill
        # whatever height the preview area/window actually has — for a large
        # panel that's well past the specimen's native resolution, and scaling a
        # raster image up is inherently soft no matter how it was antialiased
        # going in. content_scale renders the specimen at a resolution that
        # already covers the current viewport, so that final scale-up factor
        # stays at (or near) 1 instead. Bounded below at 1 (a tiny preview pane
        # shouldn't shrink the specimen under its own literal point sizes) and
        # above by _MAX_CONTENT_SCALE (so an extreme window size can't demand an
        # unreasonably large PIL render).
        natural_height = self._natural_total_height(text)
        target_height = max(1, self._image_view.viewport().height())
        content_scale = target_height / natural_height if natural_height > 0 else 1.0
        content_scale = max(1.0, min(content_scale, self._MAX_CONTENT_SCALE))

        try:
            label_font = ImageFont.truetype(
                BytesIO(self._font_data), max(1, round(self._LABEL_FONT_SIZE * content_scale * ss))
            )
        except Exception:
            label_font = None  # e.g. a font whose own glyphs can't render the "12pt" label text

        rendered = []
        max_text_width = 0
        label_width = 0
        for size in self._SIZES:
            try:
                font = ImageFont.truetype(BytesIO(self._font_data), max(1, round(size * content_scale * ss)))
            except Exception:
                continue
            bbox = font.getbbox(text) if hasattr(font, "getbbox") else (0, 0, *font.getsize(text))
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            max_text_width = max(max_text_width, width)
            label = f"{size}pt"
            if label_font is not None:
                lb = label_font.getbbox(label) if hasattr(label_font, "getbbox") else (0, 0, *label_font.getsize(label))
                label_width = max(label_width, lb[2] - lb[0])
            rendered.append((font, height, label))

        if not rendered:
            self._image_view.set_image(QPixmap())
            return

        padding = round(10 * content_scale * ss)
        label_gap = round(12 * content_scale * ss) if label_font is not None else 0
        text_x = padding + label_width + label_gap
        total_height = sum(h + padding * 2 for _, h, _ in rendered)
        image = Image.new("RGB", (max(1, text_x + max_text_width + padding), max(1, total_height)), "white")
        draw = ImageDraw.Draw(image)
        y = 0
        for font, height, label in rendered:
            if label_font is not None:
                # Same baseline y as the specimen line it labels (not centered
                # against the label font's own, smaller height) — keeps the size
                # label visually aligned with the line of text it describes.
                draw.text((padding, y + padding), label, font=label_font, fill=self._LABEL_COLOR)
            draw.text((text_x, y + padding), text, font=font, fill="black")
            y += height + padding * 2

        if ss > 1:
            image = image.resize(
                (max(1, image.width // ss), max(1, image.height // ss)), Image.Resampling.LANCZOS
            )

        view = self._image_view
        keep_zoom = view.user_zoomed
        saved = (view.transform(), view.horizontalScrollBar().value(), view.verticalScrollBar().value()) if keep_zoom else None
        view.set_image(pil_to_qpixmap(image))
        if saved is not None:
            # Re-render (custom text typed while zoomed): keep the zoom and position.
            view.restore_user_zoom(*saved)
            return
        # set_image()'s own fit-vs-1:1 heuristic (shrink to fit if larger than the
        # viewport, else show at 1:1) is wrong for a font specimen either way: 1:1
        # can leave the specimen far shorter than the available height (wasted
        # space), and centering (QGraphicsView's default alignment) meant a
        # specimen wider than the viewport opened scrolled to its horizontal
        # middle, hiding the very start of the sample text. fill_height_top_left()
        # scales uniformly so the specimen's height always fills the preview area
        # and starts at the top-left corner — any leftover width is reached via
        # the horizontal scrollbar set up in __init__.
        self._image_view.fill_height_top_left()
