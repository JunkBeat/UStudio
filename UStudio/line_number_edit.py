"""A QPlainTextEdit with a line-number ruler on its left, like a code editor.

Follows Qt's own "Code Editor" recipe: the ruler is a child widget parked in the editor's left
margin and painted for the visible lines only, so it costs the same on a 150,000-line dump as on
a short one. Colors come from the palette at paint time, so a live theme switch just works. With
word wrap on, a wrapped line keeps a single number (at its first row)."""

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPalette
from PyQt6.QtWidgets import QPlainTextEdit, QWidget


class _Ruler(QWidget):
    def __init__(self, editor: "LineNumberedPlainTextEdit"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.ruler_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_ruler(event)


class LineNumberedPlainTextEdit(QPlainTextEdit):
    _PADDING = 8  # px on each side of the numbers

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ruler = _Ruler(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._scroll_ruler)
        self._update_margin()

    # -- geometry ---------------------------------------------------------------------------
    def ruler_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return self._PADDING * 2 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, *_args) -> None:
        self.setViewportMargins(self.ruler_width(), 0, 0, 0)

    def _scroll_ruler(self, rect, dy) -> None:
        if dy:
            self._ruler.scroll(0, dy)
        else:
            self._ruler.update(0, rect.y(), self._ruler.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._ruler.setGeometry(QRect(cr.left(), cr.top(), self.ruler_width(), cr.height()))

    def setFont(self, font) -> None:  # the ruler's width follows the font
        super().setFont(font)
        self._update_margin()

    # -- painting ---------------------------------------------------------------------------
    def paint_ruler(self, event) -> None:
        pal = self.palette()
        base, text = pal.color(QPalette.ColorRole.Base), pal.color(QPalette.ColorRole.Text)
        # a step toward the text color for the ruler background, and a dimmer text for numbers
        background = QColor(
            (base.red() * 9 + text.red()) // 10, (base.green() * 9 + text.green()) // 10,
            (base.blue() * 9 + text.blue()) // 10)
        numbers = QColor(
            (base.red() + text.red() * 2) // 3, (base.green() + text.green() * 2) // 3,
            (base.blue() + text.blue() * 2) // 3)
        painter = QPainter(self._ruler)
        painter.fillRect(event.rect(), background)
        painter.setPen(numbers)
        painter.setFont(self.font())

        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        height = self.fontMetrics().height()
        width = self._ruler.width() - self._PADDING
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1
