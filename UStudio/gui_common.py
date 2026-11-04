"""Shared GUI helpers: elided labels, transport-button icons, PIL -> QPixmap, and the in-text find bar."""

from core.i18n import N_, tr
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QImage, QPalette, QPixmap, QTextCursor, QTextDocument
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QWidget
import preview_icons
from config import CONFIG

EXPORT_SUBFOLDER = "UStudio_Assets"


def export_target_dir(chosen: str) -> Path:
    """Where an export into the folder the user picked really goes: `<chosen>/UStudio_Assets` (created), unless
    the setting is off or the user picked such a folder themselves (re-exporting must not nest another one).
    Real feedback: with grouping off, everything landed loose in the chosen folder — often the game's or a mod's
    own folder — and piled up there."""
    base = Path(chosen)
    if not CONFIG.export_assets_subfolder or base.name == EXPORT_SUBFOLDER:
        return base
    target = base / EXPORT_SUBFOLDER
    target.mkdir(parents=True, exist_ok=True)
    return target


def set_elided_label_text(label, full_text: str) -> None:
    """Sets a QLabel's text elided to its CURRENT width (Qt.TextElideMode.ElideMiddle),
    keeping the untruncated text as a tooltip whenever it's actually been elided.
    Without this, an unbounded string (a full absolute path, a long status message)
    forces the whole layout to that width instead of just truncating. Stores
    full_text on the label itself so a later resizeEvent can re-elide it to the new
    width without the caller needing to remember the original string — see
    reapply_elided_labels()."""
    label._elided_full_text = full_text
    _reapply(label)


COPIED_NOTICE = N_("Скопировано")
COPIED_NOTICE_MS = 1500


def show_copied_notice(widget: QWidget, local_pos=None) -> None:
    """A brief «Скопировано» next to what was copied (user request: the copy button gave no sign it worked).
    A tooltip shown for COPIED_NOTICE_MS: it disappears on its own, takes no focus and blocks nothing.
    `local_pos`: where in `widget` (default: just under its bottom-left corner)."""
    from PyQt6.QtCore import QPoint, QRect
    from PyQt6.QtWidgets import QToolTip
    pos = local_pos if local_pos is not None else QPoint(0, widget.height())
    QToolTip.showText(widget.mapToGlobal(pos), tr(COPIED_NOTICE), widget, QRect(), COPIED_NOTICE_MS)


def coverage_highlight_color(palette) -> QColor:
    """Green that reads on the current background — for the one metadata fact a localiser looks for first
    ("Cyrillic support"). Picked by the background's lightness, so a theme switch needs nothing else."""
    dark_background = palette.color(QPalette.ColorRole.Window).lightness() < 128
    return QColor("#4cc38a" if dark_background else "#1a7f37")


def _transport_icon_color(colors, kind: str, checked: bool = False) -> str:
    """Resolves the glyph color for a media player's play/pause/stop/loop (and
    VideoPreviewWidget's own fullscreen toggle, which shares RoundToolButton
    styling with stop/loop and so falls into the same default branch below)
    button from the current theme — shared by AudioPreviewWidget and
    VideoPreviewWidget so the two can't drift apart. Real reported request:
    these icons should be white on the dark theme and black on the light
    theme, like the rest of the app's icon-ish elements — but applied
    literally, that would make play/pause unreadable, since AccentRoundButton
    (play/pause) sits on `colors.highlight`, a fairly dark/saturated color in
    BOTH themes (unlike RoundToolButton's `colors.button`, which genuinely
    flips from dark navy to pale off-white between themes). So play/pause
    uses `highlighted_text` (already white in both themes, theme.py's own
    role for text on the highlight color) and stop/loop uses `button_text`
    (theme.py's own role for text on the button/RoundToolButton color, which
    does invert light/dark exactly as requested).

    `checked` only matters for "loop": theme.py's own QSS
    (#RoundToolButton:checked) swaps ITS background to the same `highlight`
    color AccentRoundButton uses the moment repeat is toggled on — so the
    icon needs to follow that same background switch (real reported bug:
    without this, a checked loop button in the light theme showed a
    near-black glyph, `button_text`, sitting on the same dark purple
    `highlight` background play/pause already proves needs a white glyph).
    Stop is never checkable, so this is a no-op for it."""
    if kind in ("play", "pause"):
        return colors.highlighted_text
    if kind == "loop" and checked:
        return colors.highlighted_text
    return colors.button_text


def _mute_button_icon(colors, muted: bool):
    """Real reported bug: get_volume_icon()/get_volume_muted_icon() draw
    their own colored chip backdrop — chosen back when this button used
    Qt's native SP_MediaVolume icon (a fixed dark shape, invisible on the
    dark theme) specifically because _mute_btn has no round QSS background
    of its own (setAutoRaise, no objectName) to make an icon readable
    against on its own. But a plain flat glyph in a THEME-matched color
    (_transport_icon_color, same "button_text" role stop/loop/expand
    already use) is just as readable against this widget's own dark
    background — confirmed by rendering the actual widget — without the
    bright, saturated square badge that made it look out of place next to
    the calmer, flat transport/fullscreen icons right above it. Same
    get_transport_icon() mechanism as those, not new drawing code: "volume"/
    "volume_muted" were already registered glyph keys, just never routed
    through the backdrop-less path."""
    kind = "volume_muted" if muted else "volume"
    return preview_icons.get_transport_icon(kind, _transport_icon_color(colors, "volume"))


def _refresh_transport_icons(colors, player, play_pause_btn, stop_btn, loop_btn) -> None:
    """Re-sets the play/pause/stop/loop icons from the current theme colors,
    playback state, and the loop button's own checked state — shared by
    AudioPreviewWidget.apply_theme_colors()/_on_state_changed() and
    VideoPreviewWidget's equivalents, so the two widgets' identical
    transport rows can't silently drift apart."""
    is_playing = player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    play_pause_btn.setIcon(
        preview_icons.get_transport_icon(
            "pause" if is_playing else "play", _transport_icon_color(colors, "play")
        )
    )
    stop_btn.setIcon(preview_icons.get_transport_icon("stop", _transport_icon_color(colors, "stop")))
    loop_btn.setIcon(
        preview_icons.get_transport_icon("loop", _transport_icon_color(colors, "loop", loop_btn.isChecked()))
    )


def reapply_elided_labels(*labels) -> None:
    """Call from a dialog's resizeEvent for every label previously set via
    set_elided_label_text() — re-elides each to its current (possibly just-changed)
    width. A no-op for a label that was never given elided text."""
    for label in labels:
        _reapply(label)


def _reapply(label) -> None:
    full_text = getattr(label, "_elided_full_text", "")
    if not full_text:
        label.setText("")
        label.setToolTip("")
        return
    metrics = QFontMetrics(label.font())
    elided = metrics.elidedText(full_text, Qt.TextElideMode.ElideMiddle, label.width())
    label.setText(elided)
    label.setToolTip(full_text if elided != full_text else "")


def exec_and_dispose(dialog) -> int:
    """`dialog.exec()`, then schedules the dialog's destruction. Use it for every modal dialog / message box that is
    created per use (so for all of them).

    Why: a widget created with a parent is owned by the parent, so a dialog that merely goes out of scope stays alive,
    hidden, as a child of the main window — and in the compiled (Nuitka) build the garbage collector then wipes the
    attributes of its Python wrapper while the C++ widget keeps receiving events. Real report: "Edit data" -> Cancel ->
    "Edit quick filters" raised `AttributeError: 'TextFindBar' object has no attribute '_input'` (the closed editor's
    find bar got the window-blocked events of the next modal dialog). Plain Python never showed it (the dialog is
    destroyed when its wrapper is dropped), which is why it could not be reproduced from source; a small compiled
    reproduction showed the hidden dialogs piling up (and, for the JSON editor, each one keeping its whole text in
    memory). deleteLater() is safe right after exec(): the destruction happens when control returns to the event loop,
    after the caller has read the result from the dialog."""
    result = dialog.exec()
    dialog.deleteLater()
    return result


def pil_to_qpixmap(pil_image) -> QPixmap:
    """Converts a PIL Image (what Texture2D/Sprite's .image property returns) to a
    QPixmap. Runs on the GUI thread — QPixmap/QImage construction isn't safe to do
    off it, so main.py's background preview worker passes the raw PIL Image through
    and this conversion happens only after the result reaches the GUI thread."""
    if pil_image.mode == "P":
        pil_image = pil_image.convert("RGBA")
    if pil_image.mode not in ("RGBA", "RGB"):
        pil_image = pil_image.convert("RGBA")

    if pil_image.mode == "RGBA":
        fmt = QImage.Format.Format_RGBA8888
        raw = pil_image.tobytes("raw", "RGBA")
        stride = pil_image.width * 4
    else:
        fmt = QImage.Format.Format_RGB888
        raw = pil_image.tobytes("raw", "RGB")
        stride = pil_image.width * 3

    qimage = QImage(raw, pil_image.width, pil_image.height, stride, fmt)
    return QPixmap.fromImage(qimage.copy())


class FieldNote(QLabel):
    """A short muted note INSIDE a QLineEdit, at its right end (left of the clear button): «Поиск… 42 %» while the
    main table is searched. It used to sit beside the field in the row's layout: showing it widened the row's
    minimum, so the left panel grew and shrank back after every search, and in a narrow panel it left the field
    almost no room (user report, 2026-10-19). As a child of the field it changes no layout; its size is fixed, so
    a new text re-lays-out nothing either (each re-layout repainted the table — see MainWindow's search progress).
    The field keeps room for it with its text margins while it shows; a narrow field gets only «N %»."""
    LONG, SHORT = N_("Поиск… {} %"), "{} %"
    _ROOM_FOR_TEXT = 100        # the long form only when this much of the field stays for the typed text

    def __init__(self, field: QLineEdit):
        super().__init__(field)
        self._field = field
        self._form = self.LONG
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._apply_colors()
        self.hide()
        field.installEventFilter(self)
        # A QLineEdit counts its text margins in its minimum size: the room kept for the note would widen the panel
        # again. A minimum width set once (the field's own, without margins) is what the layout uses instead.
        if field.minimumWidth() == 0:
            field.setMinimumWidth(field.minimumSizeHint().width())

    def _apply_colors(self) -> None:
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText,
                         self._field.palette().color(QPalette.ColorRole.PlaceholderText))
        self.setPalette(palette)

    def start(self) -> None:
        """Shows «Поиск…» (no percentage yet), sized for the form that fits the field."""
        metrics = self.fontMetrics()
        long_form = tr(self.LONG)
        long_width = metrics.horizontalAdvance(long_form.format(100)) + 6
        self._form = long_form if self._field.width() - long_width >= self._ROOM_FOR_TEXT else self.SHORT
        width = long_width if self._form is long_form else metrics.horizontalAdvance(self.SHORT.format(100)) + 6
        self.setFixedSize(width, max(16, self._field.height() - 4))
        self.setText(tr("Поиск…") if self._form is long_form else "…")
        self._field.setTextMargins(0, 0, width + 2, 0)
        self._place()
        self.show()

    def set_percent(self, percent: int) -> None:
        self.setText(self._form.format(percent))

    def stop(self) -> None:
        if not self.isHidden():
            self.hide()
            self._field.setTextMargins(0, 0, 0, 0)

    def _place(self) -> None:
        from PyQt6.QtWidgets import QToolButton
        right = self._field.width() - 6
        for button in self._field.findChildren(QToolButton):     # the clear button, when it shows
            if button.isVisible() and button.geometry().right() > self._field.width() // 2:
                right = min(right, button.geometry().left() - 2)
        self.move(right - self.width(), (self._field.height() - self.height()) // 2)

    def eventFilter(self, obj, event):
        if obj is self._field:
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show) and not self.isHidden():
                self._place()
            elif event.type() == QEvent.Type.PaletteChange:
                self._apply_colors()
        return False


class TextFindBar(QWidget):
    """Small inline Ctrl+F find bar for a single QTextEdit or QPlainTextEdit — used by
    PreviewPanel for its three plain-text tabs (Просмотр's text/json page,
    Дамп, Структура) and by JsonEditorDialog. Hidden until opened; Esc (or the ✕ button) hides it
    again. Case-insensitive substring search with wraparound in both
    directions, live "find as you type", and a plain match-count label
    (not a tracked "match X of N" index — computing/maintaining an exact
    current-match index would need re-scanning the whole document on every
    move anyway for a QTextEdit this size range, so a simple count is the
    cheaper, still genuinely useful signal).

    One instance per QTextEdit, not one shared bar dynamically re-pointed at
    whichever tab is current — each tab's find state (query text, current
    match) staying independent when switching tabs matches how a browser's
    own per-page find bar behaves, and avoids needing to save/restore state
    across a re-point."""

    def __init__(self, text_edit: QTextEdit, parent=None):
        super().__init__(parent)
        self._text_edit = text_edit

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText(tr("Поиск..."))
        self._input.textChanged.connect(self._on_text_changed)
        self._input.installEventFilter(self)
        layout.addWidget(self._input, 1)

        self._status = QLabel("")
        self._status.setObjectName("MutedCaption")
        # Real reported feedback: a fixed setMinimumWidth(90) here — sized for
        # the longest realistic status text — left a big, oddly empty-looking
        # gap before the buttons for anything shorter ("не найдено"). Sized to
        # content instead; the small resulting side-to-side jitter as the
        # count changes length is the same tradeoff a browser's own find bar
        # makes, and reads as far less strange than a static gap.
        layout.addWidget(self._status)

        # Prev/Next grouped into one visually-joined pair (zero gap between
        # them, adjoining corners squared off) — they're one "step through
        # matches" control, not two independent peer actions, so they
        # shouldn't be spaced apart identically to Close, which is a wholly
        # separate action ("dismiss the bar"). Real reported feedback: the
        # original layout gave all three buttons the same even spacing, which
        # read as three unrelated actions in a row instead of nav+close.
        nav_group = QWidget()
        nav_layout = QHBoxLayout(nav_group)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        btn_prev = QPushButton("▲")
        btn_prev.setObjectName("FindBarNavPrev")
        btn_prev.setToolTip(tr("Предыдущее совпадение (Shift+Enter)"))
        btn_prev.clicked.connect(lambda: self._find(backward=True))
        btn_next = QPushButton("▼")
        btn_next.setObjectName("FindBarNavNext")
        btn_next.setToolTip(tr("Следующее совпадение (Enter)"))
        btn_next.clicked.connect(lambda: self._find(backward=False))
        # Squares off the adjoining inner corners/border so the pair reads as
        # one pill-shaped control instead of two separate chip buttons
        # touching edge-to-edge — the outer corners keep the theme's normal
        # 6px QPushButton radius (see theme.py's global QPushButton rule).
        btn_prev.setStyleSheet(
            "QPushButton#FindBarNavPrev { border-top-right-radius: 0; border-bottom-right-radius: 0; border-right: none; }"
        )
        btn_next.setStyleSheet(
            "QPushButton#FindBarNavNext { border-top-left-radius: 0; border-bottom-left-radius: 0; }"
        )
        nav_layout.addWidget(btn_prev)
        nav_layout.addWidget(btn_next)
        layout.addWidget(nav_group)

        btn_close = QPushButton("✕")
        btn_close.setToolTip(tr("Закрыть (Esc)"))
        btn_close.clicked.connect(self.close_bar)
        layout.addWidget(btn_close)

        # Deliberately NOT setFixedWidth() on any of these — see
        # ImagePreviewWidget's R/G/B buttons in preview_panel.py for the exact
        # same bug already hit once this session: the app's global QSS gives
        # every QPushButton 14px of padding per side (28px total), so any
        # fixed width at or below that leaves no room to paint the glyph at
        # all and the button renders blank. Left unconstrained, so width
        # follows the QSS-padded sizeHint like an ordinary QPushButton.
        for btn in (btn_prev, btn_next, btn_close):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.hide()

    def open_bar(self) -> None:
        # Prefills from the text edit's own current selection (if any) —
        # matching the same convenience a browser's Ctrl+F gives when text is
        # already selected on the page.
        selected = self._text_edit.textCursor().selectedText()
        if selected and " " not in selected:  # skip a multi-paragraph selection
            self._input.setText(selected)
        self.show()
        self._input.setFocus()
        self._input.selectAll()
        if self._input.text():
            self._update_status()

    def close_bar(self) -> None:
        self.hide()
        cursor = self._text_edit.textCursor()
        cursor.clearSelection()
        self._text_edit.setTextCursor(cursor)
        self._text_edit.setFocus()

    _lost_input_reported = False

    def _report_lost_input_once(self, obj, event) -> None:
        """The cause of the vanished `_input` is not known: it never happens when the app runs as plain Python (the
        real WhatTheDub load / SDF export / generate / overwrite flow keeps all three preview bars intact), only in the
        compiled build. So the first time it is seen, the bar's state goes into the crash log — what is left of its
        attributes, who still references it, whether Qt thinks it alive. Once per run; never raises."""
        if TextFindBar._lost_input_reported:
            return
        TextFindBar._lost_input_reported = True
        try:
            import gc
            import sys
            import traceback
            from PyQt6 import sip
            import crash_log
            referrers = [type(r).__name__ for r in gc.get_referrers(self)][:10]
            parent = self.parent()
            crash_log.write(
                "TextFindBar lost its `_input` (diagnostic, written once): "
                f"event={event.type().name} watched={type(obj).__name__} "
                f"remaining_attrs={sorted(self.__dict__)} deleted={sip.isdeleted(self)} visible={self.isVisible()} "
                f"parent={type(parent).__name__ if parent is not None else None} "
                f"refcount={sys.getrefcount(self)} referrers={referrers} gc_enabled={gc.isenabled()} "
                f"stack={[f.name for f in traceback.extract_stack(limit=8)]}")
        except Exception:
            pass

    def eventFilter(self, obj, event) -> bool:
        # Qt calls this for EVERY event of the input field (also while the bar is hidden: window activation, style
        # changes, ...). crash.log showed `AttributeError: ... no attribute '_input'` here, over and over, for an
        # instance whose Python attributes were gone while its C++ widget still received events; an event filter must
        # never raise, so a missing field simply means "not ours".
        field = getattr(self, "_input", None)
        if field is None:
            TextFindBar._report_lost_input_once(self, obj, event)
        if field is not None and obj is field and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._find(backward=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                return True
        return super().eventFilter(obj, event)

    def _on_text_changed(self, text: str) -> None:
        if not text:
            self._status.setText("")
            cursor = self._text_edit.textCursor()
            cursor.clearSelection()
            self._text_edit.setTextCursor(cursor)
            return
        # Re-anchors the search at the START of whatever's currently
        # selected (rather than after it) before each keystroke's search, so
        # narrowing/widening the query re-finds from the same spot instead of
        # drifting forward through the document as the user types.
        cursor = self._text_edit.textCursor()
        cursor.setPosition(min(cursor.selectionStart(), cursor.position()))
        self._text_edit.setTextCursor(cursor)
        self._find(backward=False)

    def _find(self, backward: bool) -> None:
        text = self._input.text()
        if not text:
            return
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        found = self._text_edit.find(text, flags)
        if not found:
            # Wrap around: jump to the far end and retry once.
            cursor = self._text_edit.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
            )
            self._text_edit.setTextCursor(cursor)
            self._text_edit.find(text, flags)
        self._update_status()

    def _update_status(self) -> None:
        text = self._input.text()
        if not text:
            self._status.setText("")
            return
        count = self._text_edit.toPlainText().lower().count(text.lower())
        self._status.setText(tr("не найдено") if count == 0 else tr("совпадений: {count}", count=count))


class AdaptiveRow(QWidget):
    """A row of buttons/checkboxes that never decides how narrow its panel may get (user report: «Сведения»'s
    action row and the tree toolbar held the right half at 419 px). With room, each registered widget shows its full
    text; below the width every one of them needs with text, ALL switch to their compact text at once ("" =
    icon-only — their tooltips still name them). The decision depends only on the available width, never on the
    current state, so it cannot flip back and forth at one width (the quick filters bar's «Изменённые» lesson).

    Use `self.row` (a QHBoxLayout) as the row's layout; `add_adaptive(widget, compact_text)` registers a widget
    already in it. minimumSizeHint() = the compact row; the layout itself sets no minimum (SetNoConstraint)."""
    compact_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.row = QHBoxLayout(self)
        self.row.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)
        self._adaptive = []              # [(widget, full text, compact text)]
        self._widths = None              # (full, compact) of the whole row, measured once per font/style
        self._compact = False

    def add_adaptive(self, widget, compact_text: str = "") -> None:
        self._adaptive.append((widget, widget.text(), compact_text))
        self._widths = None

    def is_compact(self) -> bool:
        return self._compact

    def _set_state(self, compact: bool) -> None:
        for widget, full, short in self._adaptive:
            widget.setText(short if compact else full)
            if isinstance(widget, QPushButton) and bool(widget.property("compact")) != compact:
                widget.setProperty("compact", compact)          # the tighter padding (theme.py)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.updateGeometry()                         # a repolish alone leaves the layout's old size

    def _row_width(self, compact: bool) -> int:
        self._set_state(compact)
        layout = self.row
        margins = layout.contentsMargins()
        width, count = margins.left() + margins.right(), 0
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.spacerItem() is not None:
                continue
            nested = item.layout()
            if nested is not None:
                nested.invalidate()
                width += nested.minimumSize().width()
            elif item.widget() is not None and not item.widget().isHidden():
                width += max(item.widget().minimumSizeHint().width(), item.widget().sizeHint().width())
            else:
                continue
            count += 1
        return width + max(0, count - 1) * max(0, layout.spacing())

    def _measure(self):
        if self._widths is None:
            full, compact = self._row_width(False), self._row_width(True)
            self._widths = (full, compact)
            self._apply(self._compact, force=True)
        return self._widths

    def _apply(self, compact: bool, force: bool = False) -> None:
        if compact == self._compact and not force:
            return
        self._compact = compact
        self._set_state(compact)
        if not force:
            self.compact_changed.emit(compact)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(self._measure()[1])
        return hint

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply(event.size().width() < self._measure()[0])

    def showEvent(self, event) -> None:
        self._widths = None              # measured again once the stylesheet has reached the buttons
        super().showEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._widths = None
            self.updateGeometry()
        super().changeEvent(event)
