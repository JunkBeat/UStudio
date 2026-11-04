"""Checkbox/radio icons for checkable QMenu items (Вид/Настройки toggles, the
Режим radio pair), rendered from the app's OWN live QStyle/QPalette instead of
hand-picked colors — guarantees they look identical to every other checkbox/
radio button in the app (dialogs, settings) by construction, not by visual
approximation, and automatically follows a live theme toggle since each icon
is captured fresh from the current style/palette rather than baked once.

QMenu::indicator styled via QSS (theme.py) replaces Qt's native checkbox/radio
rendering entirely for a MENU item specifically — including the checkmark/dot
it would otherwise draw — so menu items need an actual icon supplied per
action to get that look back. A plain QCheckBox/QRadioButton elsewhere in the
app never had this problem; only QMenu strips it."""

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionButton

_SIZE = 16
_ICON_CACHE: dict = {}


def _draw(primitive: QStyle.PrimitiveElement, checked: bool) -> QPixmap:
    style = QApplication.style()
    option = QStyleOptionButton()
    option.rect = QRect(0, 0, _SIZE, _SIZE)
    option.state = QStyle.StateFlag.State_Enabled
    option.state |= QStyle.StateFlag.State_On if checked else QStyle.StateFlag.State_Off

    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    style.drawPrimitive(primitive, option, painter, None)
    painter.end()
    return pixmap


def _get(key: str, primitive: QStyle.PrimitiveElement, checked: bool) -> QIcon:
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    # The app's own indicator images (theme.indicator_image — the native ones were barely visible in the dark
    # theme), so menu checkmarks look exactly like every checkbox/radio button; drawing through the style below
    # would NOT pick them up (a stylesheet image applies to widgets, not to a bare drawPrimitive).
    import theme
    colors = theme.current_colors()
    if colors is not None:
        kind = "radio" if primitive == QStyle.PrimitiveElement.PE_IndicatorRadioButton else "check"
        state = "on" if checked else "off"
        icon = QIcon(theme.indicator_image(colors, kind, state))
        # A hovered menu item has the accent background, where the accent-filled box vanished (user report): the
        # style draws a highlighted item's icon in Active mode, so that mode gets the reversed (white) variant.
        reversed_file = theme.indicator_image(colors, kind, state, selected=True)
        for mode in (QIcon.Mode.Active, QIcon.Mode.Selected):
            icon.addFile(reversed_file, QSize(_SIZE, _SIZE), mode)
        _ICON_CACHE[key] = icon
        return icon
    icon = QIcon(_draw(primitive, checked))
    _ICON_CACHE[key] = icon
    return icon


def get_checkbox_icon(checked: bool) -> QIcon:
    return _get(f"check_{checked}", QStyle.PrimitiveElement.PE_IndicatorCheckBox, checked)


def get_radio_icon(checked: bool) -> QIcon:
    return _get(f"radio_{checked}", QStyle.PrimitiveElement.PE_IndicatorRadioButton, checked)


def clear_cache() -> None:
    """Call after a live theme toggle — cached icons are pixmaps captured from
    the style/palette at draw time, so they'd otherwise keep showing the OLD
    theme's colors until the app restarts."""
    _ICON_CACHE.clear()
