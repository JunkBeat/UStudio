"""Инструменты -> «Перенести патчи на новую версию игры...»: a folder of patch files exported from an OLDER build of
the loaded game gets new names for the new build. Everything is decided from the patch files themselves (their
names, the neighbouring patches, their content) - no old build, no backups (user decision). The user looks at the
list, ticks / unticks, picks a variant where several objects fit, and saves renamed copies into a new folder; the
patch folder is never touched. Then the folder is imported as usual.

Non-modal; reads the loaded game's objects, so MainWindow closes it before they are released (main_save_flow's
teardown lists)."""

from core.i18n import N_, tr, trn
import html
import logging
from pathlib import Path

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, QThread, QUrl
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSplitter, QTableView, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app_settings import app_settings
from core import patch_relocation as pr
from core.progress import OperationCancelled
from gui_common import exec_and_dispose, pil_to_qpixmap
from gui_workers import BackgroundWorker
from helpers import wrap_tooltip

logger = logging.getLogger(__name__)

_SETTINGS = "patch_relocation"
_PICTURE = 260                      # px, the side of each picture on the right

_STATE_TEXT = {"on_spot": N_("на месте"), "choose": N_("требует действий"), "lost": N_("не найден")}

# What the right side says about a patch, by how its place was found (PatchEntry.how). {where} = « в файле X» when
# the object moved to another file, {number} = its new PathID, {count} = PatchEntry.count. Short: a status, then
# at most one reason.
_FOUND = N_("Новый номер: #{number}{where}.")
_CHOOSE = N_("Подходят несколько объектов. Выберите свой по тексту.")
_NOT_FOUND = N_("Объекта с таким именем больше нет.")
_NAMELESS_CONTENT = "nameless_content"
_EXPLANATIONS = {
    pr.HOW_SPOT: N_("Объект на прежнем месте."),
    pr.HOW_SAME_FILE: _FOUND,
    pr.HOW_OTHER_FILE: _FOUND,
    pr.HOW_SCRIPT_UNREAD: _FOUND,
    pr.HOW_NEIGHBOURS: N_("Новый номер: #{number}{where}. Выбран по соседним патчам."),
    pr.HOW_CONTENT: N_("Новый номер: #{number}{where}. Выбран по содержимому патча."),
    _NAMELESS_CONTENT: N_("Новый номер: #{number}{where}. Выбран по содержимому патча."),
    pr.HOW_NAMELESS_NEIGHBOURS: N_("Новый номер: #{number}{where}. Выбран по соседним патчам."),
    pr.HOW_IDENTICAL: _CHOOSE,
    pr.HOW_SEVERAL: _CHOOSE,
    pr.HOW_CLAIMED: _CHOOSE,
    pr.HOW_CANT_TELL: N_("Подходят несколько одинаковых объектов ({count}). Не понять, какой ваш."),
    pr.HOW_NAMELESS_UNPLACED: N_("Объект без имени: невозможно определить положение после обновления."),
    pr.HOW_SAME_SCRIPT: _NOT_FOUND,
    pr.HOW_NO_NAME: _NOT_FOUND,
}
_PICTURE_CHOOSE = N_("Подходят несколько объектов. Выберите свой по картинке.")
_STATE_FALLBACK = {  # a `how` with no text of its own
    "on_spot": _EXPLANATIONS[pr.HOW_SPOT],
    "found": _FOUND,
    "choose": _CHOOSE,
    "lost": _NOT_FOUND,
}
_OTHER_FIELDS_NOTE = N_("⚠ Изменены настройки ({fields}). Возможно, это другой объект.")
_MAX_DIFF_ROWS = 300
_STATE_COLOR = {"on_spot": "#3fa34d", "found": "#3fa34d", "choose": "#d9822b", "lost": "#9a9a9a"}
_FILTERS = [  # (text, states)
    (N_("Все"), None),
    (N_("Нужно решить"), ("choose", "lost")),
    (N_("С новым номером"), ("found",)),
    (N_("На месте"), ("on_spot",)),
]


def _dot(color: str) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, 10, 10)
    p.end()
    return QIcon(pix)


def _object_title(obj) -> str:
    return f"#{obj.path_id} ({obj.assets_file.name})"


def _result_text(e: pr.PatchEntry) -> str:
    if e.state == "found":
        obj = e.chosen or e.target
        where = "" if obj.assets_file.name == e.source else " " + tr("в {name}", name=obj.assets_file.name)
        return tr("новый номер #{path_id}{where}", path_id=obj.path_id, where=where)
    if e.state == "choose" and e.chosen is not None and e.decision == "accept":
        return tr("выбран #{path_id}", path_id=e.chosen.path_id)
    if e.how == pr.HOW_CANT_TELL:
        return tr("не определён")
    return tr(_STATE_TEXT[e.state])


def explanation(e: pr.PatchEntry) -> str:
    """One or two short sentences about the patch, for the right side: the text of its `how` (_EXPLANATIONS)."""
    key = _NAMELESS_CONTENT if e.how == pr.HOW_CONTENT and e.nameless else e.how
    text = _EXPLANATIONS.get(key) or _STATE_FALLBACK[e.state]
    if e.state == "choose" and pr.is_picture(e):
        text = _PICTURE_CHOOSE
    obj = e.target if e.state == "found" else None
    where = (" " + tr("в файле {name}", name=obj.assets_file.name)
             if obj is not None and obj.assets_file.name != e.source else "")
    return tr(text, where=where, number=obj.path_id if obj is not None else "", count=e.count)


class _EntryModel(QAbstractTableModel):
    HEADERS = [N_("Патч"), N_("Результат")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._icons = {k: _dot(c) for k, c in _STATE_COLOR.items()}

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 2

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(self.HEADERS[section])
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0 and self.rows[index.row()].state != "lost":
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.rows[index.row()]
        if index.column() == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return e.path.name
            if role == Qt.ItemDataRole.CheckStateRole and e.state != "lost":
                return Qt.CheckState.Checked if e.checked else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.ToolTipRole:
                return wrap_tooltip(str(e.rel))
        else:
            if role == Qt.ItemDataRole.DisplayRole:
                return _result_text(e)
            if role == Qt.ItemDataRole.DecorationRole:
                return self._icons[e.state]
            if role == Qt.ItemDataRole.ToolTipRole:
                return wrap_tooltip(explanation(e))
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        e = self.rows[index.row()]
        on = Qt.CheckState(value) == Qt.CheckState.Checked
        if on:
            e.decision = "accept"
            if e.chosen is None and e.target is None and e.candidates:
                e.chosen = e.candidates[0]
        else:
            e.decision = "skip"
        self.refresh_row(index.row())
        parent = self.parent()
        if parent is not None and hasattr(parent, "_after_tick"):
            parent._after_tick(e)
        return True

    def refresh_row(self, row: int):
        if 0 <= row < len(self.rows):
            self.dataChanged.emit(self.index(row, 0), self.index(row, 1))


def _picture_label() -> QLabel:
    label = QLabel()
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFixedSize(_PICTURE, _PICTURE)
    label.setStyleSheet("QLabel { border: 1px solid palette(mid); }")
    return label


class PatchRelocationDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle(tr("Перенос патчей на новую версию игры"))
        self.setModal(False)
        self._fit_to_screen(1150, 720)

        self._entries = []
        self._check_worker = None
        self._detail_worker = None
        self._write_worker = None
        self._detail_generation = 0
        self._current = None
        self._ranked = []                 # [(obj, Match)] of the shown patch
        self._filling_variants = False

        self._build_ui()
        self.patch_edit.setText(str(app_settings().value(f"{_SETTINGS}/patch_folder", "") or ""))
        self._update_buttons()

    # --- UI ---

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Папка с патчами:")))
        self.patch_edit = QLineEdit()
        self.patch_edit.setPlaceholderText(tr("Файлы, экспортированные из прежней версии игры"))
        self.patch_edit.returnPressed.connect(self._start_check)
        top.addWidget(self.patch_edit, 1)
        btn_browse = QPushButton(tr("Обзор…"))
        btn_browse.clicked.connect(self._browse_patches)
        top.addWidget(btn_browse)
        self.btn_check = QPushButton(tr("Проверить"))
        self.btn_check.clicked.connect(self._start_check)
        top.addWidget(self.btn_check)
        layout.addLayout(top)

        status_row = QHBoxLayout()
        self.summary_label = QLabel(tr("Выберите папку с патчами."))
        self.summary_label.setWordWrap(True)
        status_row.addWidget(self.summary_label, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(180)
        self.progress.setVisible(False)
        status_row.addWidget(self.progress)
        self.btn_cancel = QPushButton(tr("Отмена"))
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_work)
        status_row.addWidget(self.btn_cancel)
        layout.addLayout(status_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        filter_row = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.filter_combo.currentIndexChanged.connect(lambda *_: self._apply_filter())
        filter_row.addWidget(self.filter_combo)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("Поиск"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda *_: self._apply_filter())
        filter_row.addWidget(self.search_edit, 1)
        left_lay.addLayout(filter_row)
        self.model = _EntryModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().currentRowChanged.connect(lambda cur, _prev: self._show_entry(cur.row()))
        left_lay.addWidget(self.table, 1)
        split.addWidget(left)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 0, 0, 0)
        self.entry_title = QLabel()
        self.entry_title.setWordWrap(True)
        self.entry_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_lay.addWidget(self.entry_title)
        self.entry_text = QLabel()
        self.entry_text.setWordWrap(True)
        right_lay.addWidget(self.entry_text)

        variant_row = QHBoxLayout()
        self.variant_label = QLabel(tr("Вариант:"))
        variant_row.addWidget(self.variant_label)
        self.patch_text_label = QLabel()
        self.patch_text_label.setWordWrap(True)
        self.patch_text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_lay.addWidget(self.patch_text_label)
        self.variant_combo = QComboBox()
        self.variant_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.variant_combo.setMinimumContentsLength(20)
        self.variant_combo.currentIndexChanged.connect(self._on_variant_chosen)
        variant_row.addWidget(self.variant_combo, 1)
        right_lay.addLayout(variant_row)

        pictures = QHBoxLayout()
        self.patch_box = QVBoxLayout()
        self.patch_caption = QLabel(tr("Патч"))
        self.patch_picture = _picture_label()
        self.patch_box.addWidget(self.patch_caption)
        self.patch_box.addWidget(self.patch_picture)
        self.game_box = QVBoxLayout()
        self.game_caption = QLabel(tr("В игре"))
        self.game_picture = _picture_label()
        self.game_box.addWidget(self.game_caption)
        self.game_box.addWidget(self.game_picture)
        pictures.addLayout(self.patch_box)
        pictures.addLayout(self.game_box)
        pictures.addStretch(1)
        self.pictures_widget = QWidget()
        self.pictures_widget.setLayout(pictures)
        pictures.setContentsMargins(0, 6, 0, 0)
        right_lay.addWidget(self.pictures_widget)

        self.compare_label = QLabel()
        self.compare_label.setWordWrap(True)
        self.compare_label.setTextFormat(Qt.TextFormat.RichText)
        self.compare_label.linkActivated.connect(lambda *_: self._toggle_differences())
        right_lay.addWidget(self.compare_label)
        # the field differences, shown by «Подробнее»
        self.differences = QWidget()
        diff_lay = QVBoxLayout(self.differences)
        diff_lay.setContentsMargins(0, 4, 0, 0)
        self.diff_table = QTableWidget(0, 3)
        self.diff_table.setHorizontalHeaderLabels([tr("Поле"), tr("В патче"), tr("В игре")])
        self.diff_table.verticalHeader().setVisible(False)
        self.diff_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.diff_table.setWordWrap(False)
        self.diff_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.diff_table.horizontalHeader().setStretchLastSection(True)
        diff_lay.addWidget(self.diff_table, 1)
        self.differences.setVisible(False)
        right_lay.addWidget(self.differences, 1)
        right_lay.addStretch(0)

        self.chk_move = QCheckBox(tr("Перенести этот патч"))
        self.chk_move.clicked.connect(self._on_move_clicked)
        right_lay.addWidget(self.chk_move)
        self.right_panel = right
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([540, 580])

        bottom = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        bottom.addWidget(self.status_label, 1)
        self.btn_save = QPushButton(tr("Сохранить отмеченные…"))
        self.btn_save.clicked.connect(self._save)
        bottom.addWidget(self.btn_save)
        btn_close = QPushButton(tr("Закрыть"))
        btn_close.clicked.connect(self.close)
        bottom.addWidget(btn_close)
        for b in (btn_browse, self.btn_check, self.btn_save, btn_close, self.btn_cancel):
            b.setAutoDefault(False)
        layout.addLayout(bottom)
        self._show_entry(-1)

    def _fit_to_screen(self, width: int, height: int) -> None:
        screen = (self.main_window.screen() if self.main_window is not None else None) or QApplication.primaryScreen()
        if screen is None:
            self.resize(width, height)
            return
        free = screen.availableGeometry()
        width = min(width, int(free.width() * 0.85))
        height = min(height, int(free.height() * 0.85))
        self.resize(width, height)
        self.move(free.x() + (free.width() - width) // 2, free.y() + (free.height() - height) // 2)

    def _browse_patches(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Папка с патчами"), self.patch_edit.text().strip())
        if folder:
            self.patch_edit.setText(folder)
            self._start_check()

    # --- check ---

    def _busy(self) -> bool:
        return any(w is not None and w.isRunning() for w in (self._check_worker, self._write_worker))

    def _start_check(self):
        if self._busy():
            return
        text = self.patch_edit.text().strip().strip('"')
        folder = Path(text)
        if not text or not folder.is_dir():
            self.summary_label.setText(tr("Папка с патчами не найдена."))
            return
        rows = list(getattr(self.main_window, "raw_data_list", None) or [])
        if getattr(self.main_window, "env", None) is None or not rows:
            self.summary_label.setText(tr("Сначала откройте обновлённую игру."))
            return
        app_settings().setValue(f"{_SETTINGS}/patch_folder", text)
        self._set_entries([])

        def work(report):
            thread = QThread.currentThread()
            entries, ignored = pr.scan_entries(folder)
            if entries:
                index = pr.GameIndex(rows, should_cancel=thread.isInterruptionRequested, progress=report)
                pr.propose(entries, index)
                pr.settle_by_content(entries, should_cancel=thread.isInterruptionRequested, progress=report)
                pr.drop_guesses(entries, should_cancel=thread.isInterruptionRequested, progress=report)
            return entries, ignored

        self._check_worker = BackgroundWorker(work, parent=self)
        self._check_worker.progress_signal.connect(self._on_progress)
        self._check_worker.succeeded_signal.connect(self._on_checked)
        self._check_worker.failed_signal.connect(self._on_work_failed)
        self._set_working(True, tr("Проверка…"))
        self._check_worker.start()

    def _on_progress(self, _phase, current, total):
        if total:
            self.progress.setMaximum(int(total))
            self.progress.setValue(int(current))
        else:
            self.progress.setMaximum(0)

    def _set_working(self, on: bool, text: str = ""):
        self.progress.setVisible(on)
        self.btn_cancel.setVisible(on)
        if on:
            self.progress.setMaximum(0)
            self.summary_label.setText(text)
        self._update_buttons()

    def _cancel_work(self):
        for w in (self._check_worker, self._write_worker):
            if w is not None and w.isRunning():
                w.requestInterruption()

    def _on_work_failed(self, message: str):
        cancelled = any(w is not None and w.isInterruptionRequested() for w in (self._check_worker, self._write_worker))
        self._set_working(False)
        self.summary_label.setText(tr("Отменено.") if cancelled or message == OperationCancelled.__name__
                                   else tr("Не удалось: {message}", message=message))

    def _on_checked(self, result):
        entries, ignored = result
        self._set_working(False)
        self._set_entries(entries)
        if not entries:
            self.summary_label.setText(tr("В папке нет файлов, экспортированных из UStudio."))
            return
        self._ignored = ignored
        self.summary_label.setText(self._summary_text(ignored))

    def _summary_text(self, ignored: int = 0) -> str:
        n = len(self._entries)
        states = {s: sum(1 for e in self._entries if e.state == s) for s in ("on_spot", "found", "choose", "lost")}
        parts = [trn(n, "{n} патч", "{n} патча", "{n} патчей")]
        if states["on_spot"] == n:
            parts.append(tr("все объекты на месте, патчи не требуют переименовки"))
        else:
            for state, label in (("on_spot", tr("присутствуют")), ("found", tr("сменился PathID")),
                                 ("choose", tr("требуют действий")), ("lost", tr("не найдено"))):
                if states[state]:
                    parts.append(f"{label}: {states[state]}")
        if ignored:
            parts.append(tr("пропущено .ORIGINAL: {ignored}", ignored=ignored))
        return " • ".join(parts)

    # --- list ---

    def _set_entries(self, entries):
        self._entries = entries
        self._refill_filter()
        self._apply_filter()

    def _refill_filter(self):
        current = self.filter_combo.currentIndex()
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        for text, states in _FILTERS:
            n = sum(1 for e in self._entries if states is None or e.state in states)
            self.filter_combo.addItem(f"{text} ({n})", states)
        self.filter_combo.setCurrentIndex(max(current, 0))
        self.filter_combo.blockSignals(False)

    def _apply_filter(self):
        states = self.filter_combo.currentData()
        needle = self.search_edit.text().strip().lower()
        rows = [e for e in self._entries if (states is None or e.state in states)
                and (not needle or needle in e.path.name.lower())]
        self.model.set_rows(rows)
        if rows:
            self.table.selectRow(0)
        else:
            self._show_entry(-1)
        self._update_buttons()

    def _update_buttons(self):
        busy = self._busy()
        self.btn_check.setEnabled(not busy)
        n = sum(1 for e in self._entries if e.final_target() is not None)
        self.btn_save.setText(tr("Сохранить отмеченные ({n_})…", n_=n))
        self.btn_save.setEnabled(n > 0 and not busy)

    def _after_tick(self, e: pr.PatchEntry):
        """Two patches of one kind may not go to one object: the later tick is undone with a word why."""
        obj = e.final_target()
        if obj is not None:
            other = next((x for x in self._entries if x is not e and x.final_target() is obj
                          and x.tail.lower() == e.tail.lower()), None)
            if other is not None:
                e.decision = "skip"
                self.status_label.setText(tr("Этот объект уже выбран для патча «{name}».", name=other.path.name))
                self.model.refresh_row(self.model.rows.index(e) if e in self.model.rows else -1)
        if e is self._current:
            self._sync_move_checkbox()
        self._update_buttons()

    # --- one patch ---

    def _show_entry(self, row: int):
        e = self.model.rows[row] if 0 <= row < len(self.model.rows) else None
        self._current = e
        self._ranked = []
        self._detail_generation += 1
        self.differences.setVisible(False)
        self.right_panel.setVisible(e is not None)
        if e is None:
            return
        self.entry_title.setText(f"<b>{html.escape(_breakable(e.path.name))}</b>")
        self.entry_text.setText(explanation(e))
        choose = e.state == "choose" or len(e.candidates) > 1 and e.state == "found"
        self.patch_text_label.setVisible(bool(e.patch_text) and e.state == "choose")
        self.patch_text_label.setText(tr("Текст в патче: {quoted}", quoted=_quoted(e.patch_text)))
        self.variant_label.setVisible(choose)
        self.variant_combo.setVisible(choose)
        self._fill_variants([(o, None) for o in self._variant_objects(e)])
        self.patch_picture.clear()
        self.game_picture.clear()
        self.pictures_widget.setVisible(False)
        self.compare_label.setText(tr("Сравнение…") if e.state != "lost" else "")
        self._sync_move_checkbox()
        self._start_detail(e)

    def _variant_objects(self, e):
        if e.state == "found":
            return [e.target] + [o for o in e.candidates if o is not e.target]
        return list(e.candidates)

    def _fill_variants(self, ranked):
        e = self._current
        self._filling_variants = True
        self.variant_combo.clear()
        chosen = e.chosen or e.target
        for obj, match in ranked:
            if e.candidate_texts:                     # a dump: what a person recognises is the object's text
                text = e.candidate_texts.get(id(obj)) or ""
                label = f"{_quoted(text) if text else tr('без текста')} — {_object_title(obj)}"
            else:
                label = pr.object_label(obj)
                if match is not None and match.note:
                    label += f" — {match.note[0].lower()}{match.note[1:]}"
            self.variant_combo.addItem(label, obj)
            if match is not None and match.note:
                self.variant_combo.setItemData(self.variant_combo.count() - 1, match.note,
                                               Qt.ItemDataRole.ToolTipRole)
            if obj is chosen:
                self.variant_combo.setCurrentIndex(self.variant_combo.count() - 1)
        self._filling_variants = False

    def _shown_object(self):
        e = self._current
        if e is None:
            return None
        if self.variant_combo.isVisible() and self.variant_combo.currentIndex() >= 0:
            return self.variant_combo.currentData()
        return e.chosen or e.target

    def _on_variant_chosen(self, _index):
        if self._filling_variants or self._current is None:
            return
        e = self._current
        obj = self.variant_combo.currentData()
        if obj is None:
            return
        e.chosen = obj
        if e.state == "found" and obj is not e.target:
            e.decision = "accept"
        self.model.refresh_row(self.model.rows.index(e))
        self._show_comparison(obj)

    def _sync_move_checkbox(self):
        e = self._current
        if e is None:
            return
        self.chk_move.setEnabled(e.state != "lost")
        self.chk_move.setChecked(e.checked and e.state != "lost")

    def _on_move_clicked(self, on: bool):
        e = self._current
        if e is None:
            return
        row = self.model.rows.index(e)
        self.model.setData(self.model.index(row, 0),
                           (Qt.CheckState.Checked if on else Qt.CheckState.Unchecked).value,
                           Qt.ItemDataRole.CheckStateRole)
        if on and e.state == "choose":
            e.chosen = self._shown_object()
            self.model.refresh_row(row)

    def _start_detail(self, e: pr.PatchEntry):
        """Ranks the variants by the patch's content (choose), or compares with the one object - in the background."""
        generation = self._detail_generation
        if self._detail_worker is not None and self._detail_worker.isRunning():
            self._detail_worker.wait(15000)
        objs = self._variant_objects(e) if e.state != "on_spot" else [e.target]
        if e.state == "lost":
            objs = []

        def work(_report):
            thread = QThread.currentThread()
            if e.state == "choose":
                ranked = pr.rank_candidates(e, should_cancel=thread.isInterruptionRequested)
            else:
                ranked = [(o, pr.compare_patch(e, o)) for o in objs[:1]] + [(o, None) for o in objs[1:]]
            pictures = {}
            first = ranked[0][0] if ranked else None
            for obj, _m in ranked[:1]:
                pictures[id(obj)] = _thumb(pr.game_picture(obj))
            return generation, ranked, _thumb(pr.patch_picture(e)), pictures, first

        self._detail_worker = BackgroundWorker(work, parent=self)
        self._detail_worker.succeeded_signal.connect(self._on_detail)
        self._detail_worker.start()

    def _on_detail(self, result):
        generation, ranked, patch_pic, pictures, first = result
        if generation != self._detail_generation or self._current is None:
            return
        e = self._current
        self._ranked = ranked
        self._pictures = pictures
        self._patch_pic = patch_pic
        if e.state == "choose":
            self._fill_variants(ranked)
            if e.chosen is None and ranked:
                self.variant_combo.setCurrentIndex(0)
        self._show_comparison(self._shown_object())

    def _show_comparison(self, obj):
        e = self._current
        match = next((m for o, m in self._ranked if o is obj), None)
        if obj is not None and match is None and self._ranked is not None:
            match = pr.compare_patch(e, obj)
        pictures = getattr(self, "_pictures", {})
        game_pic = pictures.get(id(obj)) if obj is not None else None
        if obj is not None and id(obj) not in pictures and obj.type.name in ("Texture2D", "Sprite"):
            game_pic = _thumb(pr.game_picture(obj))
            pictures[id(obj)] = game_pic
        patch_pic = getattr(self, "_patch_pic", None)
        show = patch_pic is not None or game_pic is not None
        self.pictures_widget.setVisible(show)
        self.patch_picture.setVisible(patch_pic is not None)
        self.patch_caption.setVisible(patch_pic is not None)
        if show:
            self._set_picture(self.patch_picture, patch_pic, "")
            self._set_picture(self.game_picture, game_pic, tr("Нет картинки"))
            self.game_caption.setText(tr("В игре: {object_label}", object_label=pr.object_label(obj)) if obj is not None else tr("В игре"))
            self.game_caption.setWordWrap(True)
            self.game_caption.setMaximumWidth(_PICTURE)
        if match is None or not match.note:
            self.compare_label.setText("")
            return
        text = html.escape(match.note)
        if match.differing:
            color = QApplication.palette().highlight().color().name()
            text += (f' • <a href="#" style="color:{color}">'
                     f'{tr("Скрыть") if self.differences.isVisible() else tr("Подробнее")}</a>')
            self._fill_differences(match.differing)
        else:
            self.differences.setVisible(False)
        if match.verdict != pr.SAME and match.other_fields_differ:
            n = match.other_fields_differ
            note = tr(_OTHER_FIELDS_NOTE, fields=trn(n, "{n} поле", "{n} поля", "{n} полей"))
            text += f'<br><span style="color:{_STATE_COLOR["choose"]}">{html.escape(note)}</span>'
        self.compare_label.setText(text)

    def _fill_differences(self, differing):
        """One row per differing field: its readable name, the patch's value, the game's (the full ones in the
        tooltips; «—» for a field one side does not have)."""
        rows = differing[:_MAX_DIFF_ROWS]
        table = self.diff_table
        table.setRowCount(len(rows))
        muted = QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        for r, d in enumerate(rows):
            name = QTableWidgetItem(d.label)
            name.setToolTip(wrap_tooltip(d.path))
            table.setItem(r, 0, name)
            for c, value in ((1, d.in_patch), (2, d.in_game)):
                item = QTableWidgetItem("—" if value is None else _one_line(value))
                if value is None:
                    item.setForeground(muted)
                    item.setToolTip(tr("Такого поля нет"))
                else:
                    item.setToolTip(wrap_tooltip(value))
                table.setItem(r, c, item)
        table.resizeColumnToContents(0)
        table.setColumnWidth(0, min(table.columnWidth(0), 260))
        table.setColumnWidth(1, max(table.viewport().width() - table.columnWidth(0), 160) // 2)

    def _toggle_differences(self):
        self.differences.setVisible(not self.differences.isVisible())
        self._show_comparison(self._shown_object())

    @staticmethod
    def _set_picture(label: QLabel, image, empty: str):
        if image is None:
            label.setPixmap(QPixmap())
            label.setText(empty)
            return
        label.setPixmap(pil_to_qpixmap(image).scaled(QSize(_PICTURE - 4, _PICTURE - 4),
                                                     Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))

    # --- writing ---

    def _save(self):
        if not self._entries or self._busy():
            return
        patch_folder = Path(self.patch_edit.text().strip().strip('"'))
        start = str(patch_folder.parent) if patch_folder.parent.is_dir() else ""
        chosen = QFileDialog.getExistingDirectory(self, tr("Куда сохранить копии"), start)
        if not chosen:
            return
        out = Path(chosen)
        if pr.output_folder_problem(out):
            out = _unique_subfolder(out, tr("{name} (новая версия)", name=patch_folder.name))
        if pr._inside(out, patch_folder):
            box = QMessageBox(QMessageBox.Icon.Warning, tr("Перенос патчей"),
                              tr("Выберите папку за пределами папки с патчами."), QMessageBox.StandardButton.Ok, self)
            exec_and_dispose(box)
            return
        entries = list(self._entries)

        def work(report):
            thread = QThread.currentThread()
            return pr.write_copies(entries, out, patch_folder, should_cancel=thread.isInterruptionRequested,
                                   progress=report)

        self._write_worker = BackgroundWorker(work, parent=self)
        self._write_worker.progress_signal.connect(self._on_progress)
        self._write_worker.succeeded_signal.connect(self._on_written)
        self._write_worker.failed_signal.connect(self._on_work_failed)
        self._set_working(True, tr("Сохранение…"))
        self.status_label.clear()
        self._write_worker.start()

    def _on_written(self, result):
        self._set_working(False)
        n = len(result.written)
        left = len(result.left_out) + len(result.problems)
        text = trn(n, "Сохранён {n} файл в «{folder}».", "Сохранено {n} файла в «{folder}».",
                   "Сохранено {n} файлов в «{folder}».", folder=result.folder)
        if left:
            text += " " + tr("Не перенесено: {left} (см. «{report_name}»).", left=left, report_name=pr.REPORT_NAME)
        # the check's summary goes back to the top; the save's result is the bottom status line
        self.summary_label.setText(self._summary_text(getattr(self, "_ignored", 0)))
        self.status_label.setText(text + " " + tr("Импортируйте эту папку как обычно."))
        log = getattr(self.main_window, "log_with_folder_link", None)
        if log is not None:
            try:
                log(tr("Перенос патчей: {text_}", text_=text), result.folder)
            except Exception:
                logger.debug("log line failed", exc_info=True)
        self._show_saved_notice(result, n, left)

    def _show_saved_notice(self, result, n: int, left: int):
        """The end of a save the user asked for: a message (the summary line alone was easy to miss - user
        report), with a button that opens the folder."""
        text = trn(n, "Сохранён {n} файл.", "Сохранено {n} файла.", "Сохранено {n} файлов.")
        if left:
            text += " " + tr("Не перенесено: {left}.", left=left)
        box = QMessageBox(QMessageBox.Icon.Information, tr("Перенос патчей"), text, QMessageBox.StandardButton.Ok, self)
        box.setInformativeText(tr("Папка: {folder}\nИмпортируйте её как обычно.", folder=result.folder)
                               + (" " + tr("Причины — в «{report_name}».", report_name=pr.REPORT_NAME) if left else ""))
        open_button = box.addButton(tr("Открыть папку"), QMessageBox.ButtonRole.ActionRole)
        exec_and_dispose(box)
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.folder)))

    # --- closing ---

    def _shut_down(self):
        for w in (self._check_worker, self._write_worker, self._detail_worker):
            if w is not None and w.isRunning():
                w.requestInterruption()
                w.wait(15000)
        self._entries = []
        self._current = None
        self._ranked = []
        self._pictures = {}
        self.model.set_rows([])

    def closeEvent(self, event):
        self._shut_down()
        super().closeEvent(event)

    def reject(self):
        self._shut_down()
        super().reject()


def _thumb(image):
    if image is None:
        return None
    image = image.copy()
    image.thumbnail((_PICTURE, _PICTURE))
    return image


def _one_line(value: str) -> str:
    """A value for one table cell: line breaks shown as ⏎ (as in the field inspector), a long float rounded to two
    places («84.86000061035156» -> «84.86»; the tooltip keeps the full value)."""
    value = str(value)
    if ("." in value or "e" in value) and not value.isalpha():
        try:
            number = float(value)
        except ValueError:
            pass
        else:
            if number == number and abs(number) != float("inf"):
                return f"{number:.2f}".rstrip("0").rstrip(".") or "0"
    return value.replace("\r\n", "\n").replace("\n", " ⏎ ")


def _quoted(text: str, limit: int = 80) -> str:
    text = _one_line(text)
    return f"«{text}»" if len(text) <= limit else f"«{text[:limit]}…»"


def _breakable(text: str) -> str:
    try:
        from details_view import breakable
        return breakable(text)
    except Exception:
        return text


def _unique_subfolder(parent: Path, name: str) -> Path:
    candidate = parent / name
    n = 2
    while candidate.exists():
        candidate = parent / f"{name} {n}"
        n += 1
    return candidate
