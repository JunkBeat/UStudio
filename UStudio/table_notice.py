"""A thin, non-blocking line above the main table — says why the object in the preview has no selected row
(hidden by filters, its file's objects not in the table, its type not loaded) and offers the one action that
fixes it as a link. Replaced the modal «Объект скрыт фильтром» / «Объект не найден в таблице» boxes that every
jump used to show (user request: intrusive). Knows nothing about the table: MainWindow decides the text and
handles `action_requested` (see main_navigation.py)."""
from core.i18n import tr
import html

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton

from helpers import wrap_tooltip

_ACTION_HREF = "action"


class TableNoticeBar(QFrame):
    action_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TableNotice")
        self._shown = None          # (text, action_text) on screen — re-rendered on a theme switch
        self._link_color = ""       # the theme's highlight, as the log's folder links (main_log_pane.py)
        # palette() roles follow the theme switch without a re-apply
        self.setStyleSheet(
            "#TableNotice { background: palette(alternate-base); border: 1px solid palette(mid); border-radius: 3px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 2, 1)
        layout.setSpacing(4)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.label.linkActivated.connect(self._on_link)
        layout.addWidget(self.label, 1)
        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setAutoRaise(True)
        self.btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_close.setToolTip(wrap_tooltip(tr("Скрыть")))
        self.btn_close.clicked.connect(self.clear)
        layout.addWidget(self.btn_close)
        self.hide()

    def show_notice(self, text: str, action_text: str = "") -> None:
        self._shown = (text, action_text)
        self._render()
        self.show()

    def apply_theme_colors(self, colors) -> None:
        self._link_color = colors.highlight
        if self._shown is not None:
            self._render()

    def _render(self) -> None:
        text, action_text = self._shown
        body = html.escape(text)
        if action_text:
            style = f' style="color:{self._link_color}; text-decoration: underline;"' if self._link_color else ""
            body += f' <a href="{_ACTION_HREF}"{style}>{html.escape(action_text)}</a>'
        self.label.setText(body)

    def clear(self) -> None:
        self._shown = None
        self.label.setText("")
        self.hide()

    def has_action(self) -> bool:
        return self.isVisible() and _ACTION_HREF in self.label.text()

    def _on_link(self, href: str) -> None:
        if href == _ACTION_HREF:
            self.action_requested.emit()
