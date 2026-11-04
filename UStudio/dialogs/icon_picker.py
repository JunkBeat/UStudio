"""Icon picker for a quick filter (QuickFilterSettingsDialog): one button showing the current icon;
clicking it opens a small grid of the app's own painted icons, an «Авто» entry and a field for a
symbol of the user's own.

Why a grid of built-in icons rather than a free emoji field: they are drawn by the app, so they look
the same on every machine and in both themes and match the icons used all over the table, whereas an
emoji comes from the system font (different per Windows version, can be monochrome or clash with the
theme). A user's own symbol is still possible, as the last resort.

The value is the string stored in QuickFilterDef.icon (see core.quick_filters.BUILTIN_ICON_PREFIX):
"" = automatic, "icon:<Name>" = built-in, anything else = the user's own symbol."""

from core.i18n import tr
from typing import Dict, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget,
    QWidgetAction,
)

from core.quick_filters import BUILTIN_ICON_PREFIX
from helpers import wrap_tooltip
from type_icons import builtin_icon_choices, get_builtin_icon

_COLUMNS = 5
_CELL = 34


class _PickerPanel(QWidget):
    """The content of the popup. `chosen` = a final pick (the popup closes); `typed` = the own-symbol
    field changed while the user is still typing (applied at once, the popup stays open)."""
    chosen = pyqtSignal(str)
    typed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.auto_button = QPushButton(tr("Авто (по типу объектов)"))
        self.auto_button.setCheckable(True)
        self.auto_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.auto_button.clicked.connect(lambda: self.chosen.emit(""))
        layout.addWidget(self.auto_button)

        grid = QGridLayout()
        grid.setSpacing(4)
        self.cells: Dict[str, QToolButton] = {}
        for n, (key, caption) in enumerate(builtin_icon_choices()):
            cell = QToolButton()
            cell.setCheckable(True)
            cell.setAutoRaise(True)
            cell.setIcon(get_builtin_icon(key) or QIcon())
            cell.setIconSize(QSize(20, 20))
            cell.setFixedSize(_CELL, _CELL)
            cell.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            cell.setToolTip(wrap_tooltip(caption))
            cell.clicked.connect(lambda _checked=False, k=key: self.chosen.emit(BUILTIN_ICON_PREFIX + k))
            grid.addWidget(cell, n // _COLUMNS, n % _COLUMNS)
            self.cells[key] = cell
        layout.addLayout(grid)

        own_row = QHBoxLayout()
        own_row.addWidget(QLabel(tr("Свой символ:")))
        self.own_edit = QLineEdit()
        self.own_edit.setMaxLength(8)   # a symbol or a couple of emoji code points, not a second label
        self.own_edit.setFixedWidth(70)
        self.own_edit.setPlaceholderText(tr("вставьте"))
        self.own_edit.setToolTip(wrap_tooltip(
            tr("Любой символ или эмодзи — применяется сразу. Пустое поле — автоматическая иконка. Внешний вид "
               "эмодзи зависит от шрифтов системы.")))
        self.own_edit.textEdited.connect(lambda text: self.typed.emit(text.strip()))   # "" = automatic
        self.own_edit.returnPressed.connect(self._own_entered)
        own_row.addWidget(self.own_edit)
        own_row.addStretch(1)
        layout.addLayout(own_row)

    def _own_entered(self) -> None:
        text = self.own_edit.text().strip()
        if text:
            self.chosen.emit(text)

    def show_value(self, value: str) -> None:
        """Marks the current choice."""
        builtin = value[len(BUILTIN_ICON_PREFIX):] if value.startswith(BUILTIN_ICON_PREFIX) else None
        self.auto_button.setChecked(value == "")
        for key, cell in self.cells.items():
            cell.setChecked(key == builtin)
        self.own_edit.setText(value if value and builtin is None else "")


class IconPickerButton(QToolButton):
    """Shows the current icon + a short caption; a click opens the picker. `value_changed` carries the
    new QuickFilterDef.icon string."""
    value_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = ""
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(18, 18))
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(wrap_tooltip(tr("Иконка кнопки: из встроенных, автоматическая или свой символ")))

        self.panel = _PickerPanel()
        self.panel.chosen.connect(self._on_chosen)
        self.panel.typed.connect(self._on_typed)
        self._menu = QMenu(self)
        action = QWidgetAction(self._menu)
        action.setDefaultWidget(self.panel)
        self._menu.addAction(action)
        self._menu.aboutToShow.connect(lambda: self.panel.show_value(self._value))
        self.setMenu(self._menu)

    @property
    def value(self) -> str:
        return self._value

    def set_state(self, value: str, icon: Optional[QIcon], caption: str) -> None:
        """What the button shows — the dialog works the icon out (it depends on the filter's types
        when the choice is automatic); this widget only displays it."""
        self._value = value
        self.setIcon(icon if icon is not None else QIcon())
        self.setText(caption)

    def _on_chosen(self, value: str) -> None:
        self._menu.close()
        self._on_typed(value)

    def _on_typed(self, value: str) -> None:
        if value != self._value:
            self._value = value
            self.value_changed.emit(value)
