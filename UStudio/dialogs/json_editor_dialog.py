from core.i18n import tr
import json
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QKeySequence, QShortcut, QTextCursor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QPlainTextEdit, QPushButton, QMessageBox
)

from gui_common import TextFindBar
from helpers import JsonHighlighter, mono_font
from line_number_edit import LineNumberedPlainTextEdit
from app_settings import app_settings


class JsonEditorDialog(QDialog):
    # A dump up to this many lines is put into the editor in one go, exactly as before. Longer ones
    # are shown in slices (see _load_next_chunk()).
    _SYNC_LINE_LIMIT = 5000
    _FIRST_CHUNK_LINES = 3000   # what is there the instant the dialog appears
    _CHUNK_LINES = 500          # lines per insert while filling the rest
    _CHUNK_BUDGET_S = 0.03      # max time one slice may hold the GUI thread

    def __init__(self, parent, initial_data: dict):
        super().__init__(parent)
        self.setWindowTitle(tr("Редактирование данных объекта"))
        self.resize(600, 600)
        self.setModal(True)
        self.result_data = None

        layout = QVBoxLayout(self)

        self.chk_word_wrap = QCheckBox(tr("Перенос строк"))
        # Remembered across restarts, same idea/store as preview_panel.py's own
        # "Перенос строк" checkbox for the read-only Preview tab — a separate
        # key ("json_editor/word_wrap") since this is a different widget with
        # its own independent state, not the same setting.
        wrap_on = app_settings().value("json_editor/word_wrap", False, type=bool)
        self.chk_word_wrap.setChecked(wrap_on)
        self.chk_word_wrap.toggled.connect(self._on_word_wrap_toggled)
        layout.addWidget(self.chk_word_wrap)

        # QPlainTextEdit, not QTextEdit: this is plain text with a highlighter, and QTextEdit lays
        # the WHOLE document out as rich text in idle-time steps that each hold the GUI thread for
        # ~300 ms. On a real 4 MB / 150k-line dump (a 21,671-entry string table) that starved the
        # event loop for many seconds after the dialog appeared — resizing the window, dragging its
        # edge, anything, only got a turn every few hundred ms, i.e. the dialog could not be
        # resized. Measured on that dump: QTextEdit — half the event-loop ticks lost, 10-11 stalls
        # over 100 ms in the first 5 s, with or without the highlighter; QPlainTextEdit — no stalls
        # (worst gap 12 ms). QPlainTextEdit lays out only what is visible, which is exactly what
        # it exists for.
        self.text_edit = LineNumberedPlainTextEdit()  # with a line-number ruler, like a code editor
        # Same font as the Preview/Dump/Json Dump tabs (helpers.mono_font(),
        # respecting CONFIG.preview_font_family/_size) — this dialog used to
        # hardcode Consolas 10pt regardless of theme/settings, which made it
        # look visibly different (and, per a real report, less readable) than
        # every other JSON view in the app for no reason tied to this dialog
        # actually being different content.
        self.text_edit.setFont(mono_font())
        self.text_edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if wrap_on else QPlainTextEdit.LineWrapMode.NoWrap
        )

        # Wire up syntax highlighting
        self.highlighter = JsonHighlighter(self.text_edit.document())
        layout.addWidget(self.text_edit)

        # The same inline find bar the Preview/Dump tabs use (gui_common.TextFindBar — it only
        # needs find()/textCursor()/toPlainText(), which QPlainTextEdit has too). Hidden until
        # Ctrl+F; Esc in its field closes just the bar, not the dialog.
        self.find_bar = TextFindBar(self.text_edit)
        layout.addWidget(self.find_bar)
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._find_shortcut.activated.connect(self.find_bar.open_bar)

        # Control buttons
        btn_layout = QHBoxLayout()
        self.lbl_loading = QLabel()
        self.lbl_loading.hide()
        btn_layout.addWidget(self.lbl_loading)
        self.btn_ok = QPushButton(tr("ОК"))
        self.btn_ok.clicked.connect(self.accept_changes)
        btn_cancel = QPushButton(tr("Отмена"))
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        # Format the source JSON and put it in the editor.
        self._loading = False
        self._pending_lines = None
        self._next_line = 0
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(0)
        self._load_timer.timeout.connect(self._load_next_chunk)
        self._set_text(json.dumps(initial_data, indent=4, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Filling the editor
    # ------------------------------------------------------------------

    def _set_text(self, text: str) -> None:
        lines = text.split("\n")
        if len(lines) <= self._SYNC_LINE_LIMIT:
            self.text_edit.setPlainText(text)
            return
        # A huge dump: the highlighter alone costs ~2 s per 4 MB when the whole text goes in at
        # once, and the dialog would not even appear until it finished. Show the first screens
        # immediately and append the rest in short slices between event-loop turns, so the window
        # is responsive (and resizable) from the start. OK stays disabled until the text is
        # complete — accepting a half-loaded dump would silently drop the rest of the data — and
        # loading is not undoable (Ctrl+Z must not be able to un-load the dump).
        self.text_edit.document().setUndoRedoEnabled(False)
        self.text_edit.setPlainText("\n".join(lines[: self._FIRST_CHUNK_LINES]))
        self._pending_lines = lines
        self._next_line = self._FIRST_CHUNK_LINES
        self._loading = True
        self.btn_ok.setEnabled(False)
        self._update_loading_label()
        self.lbl_loading.show()
        self._load_timer.start()

    def _load_next_chunk(self) -> None:
        if not self._loading:
            return  # finished or cancelled while this tick was already queued
        lines, total = self._pending_lines, len(self._pending_lines)
        deadline = time.monotonic() + self._CHUNK_BUDGET_S
        # A cursor of our own: the editor's visible cursor and scroll position are not touched.
        cursor = QTextCursor(self.text_edit.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        # Deliberately NOT wrapped in beginEditBlock()/endEditBlock(): that defers the highlighting
        # and layout of everything inserted to the END of the block, i.e. after the deadline below
        # has been checked — measured: a "30 ms" slice of five 2000-line inserts really took ~145 ms.
        # Inserting directly keeps each insert's real cost inside the loop where the deadline sees it.
        while self._next_line < total and time.monotonic() < deadline:
            end = min(total, self._next_line + self._CHUNK_LINES)
            cursor.insertText("\n" + "\n".join(lines[self._next_line:end]))
            self._next_line = end
        if self._next_line >= total:
            self._finish_loading()
        else:
            self._update_loading_label()

    def _update_loading_label(self) -> None:
        pct = 100 * self._next_line // max(1, len(self._pending_lines or ()))
        self.lbl_loading.setText(tr("Загрузка… {pct}%", pct=pct))

    def _finish_loading(self) -> None:
        self._stop_loading()
        self.text_edit.document().setUndoRedoEnabled(True)  # also clears the (empty) undo stack
        self.btn_ok.setEnabled(True)

    def _stop_loading(self) -> None:
        self._load_timer.stop()
        self._loading = False
        self._pending_lines = None
        self.lbl_loading.hide()

    def done(self, result: int) -> None:
        # Closing/cancelling mid-load must not leave a timer filling a hidden dialog.
        self._stop_loading()
        super().done(result)

    # ------------------------------------------------------------------

    def _on_word_wrap_toggled(self, checked: bool):
        self.text_edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if checked else QPlainTextEdit.LineWrapMode.NoWrap
        )
        app_settings().setValue("json_editor/word_wrap", checked)

    def accept_changes(self):
        if self._loading:
            return  # the text is not complete yet — see _set_text()
        try:
            data = json.loads(self.text_edit.toPlainText())

            if not isinstance(data, dict):
                raise ValueError(tr("Корневой элемент JSON должен быть объектом."))

            self.result_data = data
            self.accept()

        except json.JSONDecodeError as e:
            QMessageBox.critical(
                self,
                tr("Ошибка JSON"),
                tr("Синтаксическая ошибка JSON.\n\nСтрока: {lineno}\nСтолбец: {colno}\n\n{msg}", lineno=e.lineno, colno=e.colno, msg=e.msg)
            )

        except ValueError as e:
            QMessageBox.critical(
                self,
                tr("Ошибка"),
                str(e)
            )
