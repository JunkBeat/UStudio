from core.i18n import N_, tr, trn
import os
from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from core.backup import (
    STATUS_DIFFERENT, STATUS_MISSING, STATUS_SAME, STATUS_UNKNOWN, BackupError, copies_of, delete_all_backups,
    delete_backups_of, delete_copy, exact_status, originals_with_backups, quick_status,
)
from helpers import format_size, wrap_tooltip

_STATUS_TEXT = {
    STATUS_SAME: N_("Без изменений"),
    STATUS_DIFFERENT: N_("Изменён"),
    STATUS_MISSING: N_("Файла нет"),
    STATUS_UNKNOWN: N_("Проверка…"),
}
_REASON_TEXT = {"overwrite": N_("перед сохранением"), "restore": N_("перед возвратом"), "version": N_("перед записью версии")}
_OTHER_GAMES = N_("Прочее")

# tree columns
COL_NAME, COL_STATUS, COL_COPY = 0, 1, 2

_STYLE = """
QLabel#Muted { color: palette(mid); }
QLabel#Heading { font-size: 16px; font-weight: bold; }
QListWidget#Games { border: none; outline: 0; background: transparent; }
QListWidget#Games::item { padding: 8px 10px; border-radius: 6px; }
QListWidget#Games::item:selected { background: palette(alternate-base); color: palette(text); }
QTreeWidget { border: none; outline: 0; background: transparent; }
QTreeWidget::item { min-height: 30px; border: none; padding-right: 18px; }
QTreeWidget::item:selected { background: palette(alternate-base); color: palette(text); }
QPushButton#Link { border: none; background: transparent; padding: 4px 8px; color: palette(highlight); }
QPushButton#Danger { background: #c62828; color: white; border: 1px solid #b71c1c; border-radius: 4px;
                     padding: 5px 12px; }
QPushButton#Danger:hover { background: #d32f2f; }
QPushButton#Danger:pressed { background: #b71c1c; }
QPushButton#Danger:disabled { background: palette(button); color: palette(mid); border-color: palette(mid); }
"""


class _StatusWorker(QThread):
    """Compares each file with its backup off the GUI thread (a big file has to be hashed)."""
    status_ready = pyqtSignal(str, str)  # original path, status

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self._entries = list(entries)

    def run(self):
        for entry in self._entries:
            if self.isInterruptionRequested():
                return
            try:
                status = exact_status(entry, should_cancel=self.isInterruptionRequested)
            except InterruptedError:
                return
            self.status_ready.emit(entry.original, status)


class RevertDialog(QDialog):
    """Backups of the game files. Left: the games that have backups. Right: that game's files, each
    with a checkbox — tick the ones to put back to a chosen stored copy.

    Deliberately whole-file only — an earlier version could also restore single objects inside an
    already-edited file (a per-file diff engine, a tri-state object tree). Removed: it added real bug
    surface in exactly the feature whose whole job is being trustworthy once something already went
    wrong, for a case whole-file restore already covers in the overwhelming majority of real "I made
    a mistake" moments.

    `entries` are the backups of the game that is open (may be empty), `all_entries` every backup;
    `scope_note` is shown when the open game has none.

    «Вернуть выбранное» closes the window only when the open game has to be released and reloaded
    for it: `restore_here(originals)` says whether the files can be put back with the window open
    (none of them is loaded) — then the restore runs here and the window stays (user report: it closed
    for another game's files too, for no visible reason). Without `restore_here` it always closes.
    `log(text)` reports what happened in the main window's log."""

    def __init__(self, entries: List, parent=None, all_entries: Optional[List] = None, scope_note: str = "",
                 restore_here: Optional[Callable[[List[str]], bool]] = None, keep_latest: int = 1,
                 log: Optional[Callable[[str], None]] = None):
        super().__init__(parent)
        self._restore_here = restore_here
        self._keep_latest = keep_latest
        self._log = log
        self._restore_thread = None
        self._pending_notice = None
        self.setWindowTitle(tr("Резервные копии"))
        self.resize(750, 500)
        self._scope_note = scope_note
        everything = list(all_entries) if all_entries is not None else list(entries)
        self._games: Dict[str, List] = {}
        for e in everything:
            self._games.setdefault(e.game or _OTHER_GAMES, []).append(e)
        self._open_game = (entries[0].game or _OTHER_GAMES) if entries else None
        self._current_game: Optional[str] = None
        self._items: Dict[str, QTreeWidgetItem] = {}          # original -> file item
        self._chosen: Dict[str, object] = {}                  # original -> BackupCopy in use
        self._worker: Optional[_StatusWorker] = None
        self._updating = False

        self.setStyleSheet(_STYLE)
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(18)

        # --- games (left) -------------------------------------------------------------------------
        left = QVBoxLayout()
        left.setSpacing(8)
        root.addLayout(left)
        self.games = QListWidget()
        self.games.setObjectName("Games")
        self.games.setFixedWidth(170)
        self.games.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.games.currentRowChanged.connect(self._on_game_selected)
        self.games.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.games.customContextMenuRequested.connect(self._on_games_context_menu)
        left.addWidget(self.games, 1)
        # bottom-left, red (user request): every backup of every game, after a confirmation
        self.btn_delete_all = QPushButton(tr("Удалить все копии"))
        self.btn_delete_all.setObjectName("Danger")
        self.btn_delete_all.setFixedWidth(170)
        self.btn_delete_all.setAutoDefault(False)
        self.btn_delete_all.setToolTip(wrap_tooltip(tr("Удалить резервные копии всех игр.")))
        self.btn_delete_all.clicked.connect(self._delete_all)
        left.addWidget(self.btn_delete_all)
        # Always visible, even for a single game: the list is built and populated in
        # _fill_games() below, so hiding/showing it depending on how many games turned up
        # made the right-hand table flash full-width for a moment before the sidebar
        # (dis)appeared — a real reported layout jump. A fixed-width sidebar that is
        # simply always there has nothing to jump.

        # --- files (right) --------------------------------------------------------------------------
        right = QVBoxLayout()
        right.setSpacing(8)
        root.addLayout(right, 1)
        head = QHBoxLayout()
        self.lbl_game = QLabel("")
        self.lbl_game.setObjectName("Heading")
        head.addWidget(self.lbl_game, 1)
        self.btn_delete_game = QPushButton(tr("Удалить копии игры…"))
        self.btn_delete_game.setObjectName("Link")
        self.btn_delete_game.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete_game.setAutoDefault(False)
        self.btn_delete_game.setToolTip(wrap_tooltip(tr("Удалить все резервные копии файлов этой игры.")))
        self.btn_delete_game.clicked.connect(self._delete_current_game)
        head.addWidget(self.btn_delete_game)
        self.btn_toggle_all = QPushButton(tr("Выбрать все"))
        self.btn_toggle_all.setObjectName("Link")
        self.btn_toggle_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_all.clicked.connect(self._toggle_all)
        head.addWidget(self.btn_toggle_all)
        right.addLayout(head)

        self.stack = QStackedWidget()
        self.lbl_empty = QLabel("")
        self.lbl_empty.setObjectName("Muted")
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.lbl_empty)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(0)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setUniformRowHeights(True)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, header.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_STATUS, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_COPY, header.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.stack.addWidget(self.tree)
        right.addWidget(self.stack, 1)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("Muted")
        right.addWidget(self.lbl_summary)

        bottom = QHBoxLayout()
        self.chk_safety = QCheckBox(tr("Сохранить текущую версию"))
        self.chk_safety.setChecked(True)
        self.chk_safety.setToolTip(wrap_tooltip(
            tr("Перед заменой текущие версии файлов копируются, чтобы возврат можно было отменить. Лишние копии "
               "удаляются сами: остаются первая и последняя.")))
        bottom.addWidget(self.chk_safety)
        bottom.addStretch()
        self.btn_restore = QPushButton(tr("Вернуть выбранное"))
        self.btn_restore.setDefault(True)
        self.btn_restore.clicked.connect(self._on_restore_clicked)
        self.btn_close = QPushButton(tr("Закрыть"))
        self.btn_close.clicked.connect(self.reject)
        bottom.addWidget(self.btn_restore)
        bottom.addWidget(self.btn_close)
        right.addLayout(bottom)

        self._fill_games()

    # ---- games -------------------------------------------------------------------------------------
    def _fill_games(self) -> None:
        self.games.blockSignals(True)
        self.games.clear()
        names = sorted(self._games, key=lambda n: (n != self._open_game, n == _OTHER_GAMES, n.lower()))
        for name in names:
            files = self._games[name]
            item = QListWidgetItem(f"{tr(name) if name == _OTHER_GAMES else name}  ·  {len(files)}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            version = self._representative_version(name)
            tooltip = os.path.dirname(files[0].original)
            if version:
                tooltip += "\n" + tr("Версия игры (самая старая копия): {version}", version=version)
            item.setToolTip(tooltip)
            self.games.addItem(item)
        self.games.blockSignals(False)
        if self._open_game in self._games or (len(self._games) == 1 and not self._scope_note):
            self.games.setCurrentRow(0)
            self._on_game_selected(0)
        else:
            self._show_game(None)

    def _representative_version(self, name: Optional[str]) -> str:
        """The game version (PlayerSettings.bundleVersion) recorded on the OLDEST backup of any
        file belonging to this game — "" if it was never resolved (old backups, or a restore's own
        safety copy, never carry one). Not necessarily every file's own version if the game was
        updated mid-way and only some files got a fresh backup since — just the best single
        representative value, same spirit as OriginalEntry.game_version's own "oldest copy" scope."""
        for e in self._games.get(name, []):
            if e.game_version:
                return e.game_version
        return ""

    def _on_game_selected(self, row: int) -> None:
        item = self.games.item(row)
        name = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if name != self._current_game or not self._items:
            self._show_game(name)

    def _show_game(self, name: Optional[str]) -> None:
        self._stop_workers()
        self._current_game = name
        self._updating = True
        self.tree.clear()
        self._updating = False
        self._items = {}
        if name is None:
            self.lbl_game.setText("")
            self.lbl_empty.setText(self._scope_note or tr("Выберите игру слева."))
            self.stack.setCurrentIndex(0)
            self._update_summary()
            return
        entries = self._games.get(name, [])
        version = self._representative_version(name)
        self.lbl_game.setText(f"{name}  ·  {version}" if version else name)
        self.lbl_empty.setText("" if entries else tr("Для этой игры резервных копий нет."))
        self.stack.setCurrentIndex(1 if entries else 0)
        self._updating = True
        for e in entries:
            copies = copies_of(e.original)
            self._chosen[e.original] = copies[0] if copies else None
            item = QTreeWidgetItem([os.path.basename(e.original), tr(_STATUS_TEXT[quick_status(e)]), ""])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
            item.setData(COL_NAME, Qt.ItemDataRole.UserRole, e.original)
            item.setToolTip(COL_NAME, e.original)
            self.tree.addTopLevelItem(item)
            self._items[e.original] = item
            self._refresh_copy_cell(e.original)
        self._updating = False
        self._worker = _StatusWorker(entries, self)
        self._worker.status_ready.connect(self._on_status)
        self._worker.start()
        if entries:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._update_summary()

    def _on_status(self, original: str, status: str) -> None:
        item = self._items.get(original)
        if item is not None:
            item.setText(COL_STATUS, tr(_STATUS_TEXT.get(status, status)))

    # ---- workers -----------------------------------------------------------------------------------
    def _stop_workers(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.requestInterruption()
            worker.wait(5000)

    def done(self, result) -> None:
        if self._restore_thread is not None:
            return                      # files are being put back: the window stays until that ends
        self._stop_workers()
        super().done(result)

    def closeEvent(self, event) -> None:
        if self._restore_thread is not None:
            event.ignore()
            return
        self._stop_workers()
        super().closeEvent(event)

    # ---- one file --------------------------------------------------------------------------------
    @staticmethod
    def _original_of(item) -> Optional[str]:
        return item.data(COL_NAME, Qt.ItemDataRole.UserRole) if item is not None else None

    def _refresh_copy_cell(self, original: str) -> None:
        item, copy = self._items.get(original), self._chosen.get(original)
        if item is None:
            return
        copies = copies_of(original)
        first = copy is not None and bool(copies) and copies[0].path == copy.path
        item.setText(COL_COPY, (f"{copy.created[:16]}" + (" · " + tr("первая") if first else "") + "  ▾") if copy else "")
        item.setForeground(COL_COPY, self.palette().mid())
        item.setToolTip(COL_COPY, wrap_tooltip(
            tr("Копия, которая будет возвращена. Нажмите, чтобы выбрать другую копию, показать её папку или удалить её.")))

    # ---- copy menu ---------------------------------------------------------------------------------
    def _on_item_clicked(self, item, column) -> None:
        if column == COL_COPY:
            self._copy_menu(self._original_of(item)).exec(QCursor.pos())

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        original = self._original_of(item) if item is not None else None
        if original:
            self._copy_menu(original).exec(self.tree.viewport().mapToGlobal(pos))

    def _copy_menu(self, original: str) -> QMenu:
        menu = QMenu(self)
        chosen = self._chosen.get(original)
        for i, c in enumerate(copies_of(original)):
            why = tr(_REASON_TEXT.get(c.reason, ""))
            text = c.created + (f" · {why}" if why else "") + f" · {format_size(c.size)}" + (" · " + tr("первая") if i == 0 else "")
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(chosen is not None and c.path == chosen.path)
            act.triggered.connect(lambda _c=False, o=original, k=i: self._choose_copy(o, k))
        menu.addSeparator()
        menu.addAction(tr("Показать папку копии")).triggered.connect(lambda: self._open_copy_folder(original))
        menu.addAction(tr("Удалить эту копию…")).triggered.connect(lambda: self._delete_copy_of(original))
        return menu

    def _choose_copy(self, original: str, index: int) -> None:
        copies = copies_of(original)
        if not 0 <= index < len(copies):
            return
        self._chosen[original] = copies[index]
        self._refresh_copy_cell(original)
        self._update_summary()

    def _open_copy_folder(self, original: str) -> None:
        copy = self._chosen.get(original)
        if copy is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(copy.folder))

    def _delete_copy_of(self, original: str) -> None:
        copy = self._chosen.get(original)
        if copy is None:
            return
        copies = copies_of(original)
        first = bool(copies) and copies[0].path == copy.path
        text = (tr("Удалить копию от {created}?", created=copy.created) +
                ("\n\n" + tr("Это самая первая копия — то, каким файл был до ваших изменений. Другого такого "
                                "экземпляра нет.") if first else ""))
        if QMessageBox.question(self, tr("Удалить копию"), text) != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_copy(copy)
        except BackupError as e:
            QMessageBox.warning(self, tr("Удалить копию"), str(e))
            return
        remaining = copies_of(original)
        if remaining:
            self._chosen[original] = remaining[0]
            self._refresh_copy_cell(original)
            self._update_summary()
            return
        self._remove_file(original)

    def _remove_file(self, original: str) -> None:
        game = self._current_game
        self._games[game] = [e for e in self._games.get(game, []) if e.original != original]
        item = self._items.pop(original, None)
        if item is not None:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        if not self._games[game]:
            del self._games[game]
            if self._open_game == game:
                self._open_game = None
            self._current_game = None
            self._fill_games()
            return
        row = self.games.currentRow()
        if row >= 0:
            self.games.item(row).setText(f"{game}  ·  {len(self._games[game])}")
        self._update_summary()

    # ---- ticking -----------------------------------------------------------------------------------
    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != COL_NAME:
            return
        self._update_summary()

    def _toggle_all(self) -> None:
        any_unticked = any(it.checkState(COL_NAME) != Qt.CheckState.Checked for it in self._items.values())
        state = Qt.CheckState.Checked if any_unticked else Qt.CheckState.Unchecked
        self._updating = True
        for item in self._items.values():
            item.setCheckState(COL_NAME, state)
        self._updating = False
        self._update_summary()

    # ---- restoring with the window open ------------------------------------------------------------
    def _on_restore_clicked(self) -> None:
        originals = self.selected_originals()
        if not originals:
            return
        if self._restore_here is None or not self._restore_here(originals):
            self.accept()               # the open game is released and reloaded: the main window does it
            return
        pairs = [(self.copy_path_for(o), o) for o in originals]
        pairs = [p for p in pairs if p[0]]
        if not pairs:
            return
        from save_thread import RestoreThread
        self._stop_workers()
        thread = RestoreThread([], self.safety_copy(), self._keep_latest, parent=self, pairs=pairs)
        thread.finished_signal.connect(self._on_restored_here)
        thread.error_signal.connect(self._on_restore_here_failed)
        thread.finished.connect(self._on_restore_thread_finished)
        self._restore_thread = thread
        self._set_busy(True)
        self.lbl_summary.setText(tr("Файлы возвращаются…"))
        thread.start()

    def _set_busy(self, busy: bool) -> None:
        for w in (self.games, self.tree, self.btn_toggle_all, self.btn_delete_game, self.btn_delete_all,
                  self.chk_safety, self.btn_restore, self.btn_close):
            w.setEnabled(not busy)

    def _on_restored_here(self, restored: list) -> None:
        n = len(restored)
        if n and self._log is not None:
            self._log(tr("Возвращено файлов: {count}.", count=n))
        self._pending_notice = trn(n, "Возвращено: {n} файл.", "Возвращено: {n} файла.", "Возвращено: {n} файлов.")

    def _on_restore_here_failed(self, message: str) -> None:
        if self._log is not None:
            self._log(message)
        self._pending_notice = None
        QMessageBox.warning(self, tr("Резервные копии"), message)

    def _on_restore_thread_finished(self) -> None:
        thread, self._restore_thread = self._restore_thread, None
        if thread is not None:
            thread.deleteLater()
        self._set_busy(False)
        notice, self._pending_notice = self._pending_notice, None
        self._reload_entries()          # new statuses, and the restore's own safety copies
        if notice:
            self.lbl_summary.setText(notice)

    def _reload_entries(self) -> None:
        """Re-reads every backup from disk and shows the same game again (if it still has any)."""
        self._stop_workers()
        self._games = {}
        for e in originals_with_backups():
            self._games.setdefault(e.game or _OTHER_GAMES, []).append(e)
        if self._open_game not in self._games:
            self._open_game = None
        keep = self._current_game
        self._current_game = None
        self._items = {}
        self._fill_games()
        names = [self.games.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.games.count())]
        if keep in names:
            self.games.blockSignals(True)
            self.games.setCurrentRow(names.index(keep))
            self.games.blockSignals(False)
            if self._current_game != keep:
                self._show_game(keep)
        elif not names:
            self._show_game(None)
            self.lbl_empty.setText(tr("Резервных копий нет."))
        self._update_delete_buttons()

    # ---- deleting backups --------------------------------------------------------------------------
    def _on_games_context_menu(self, pos) -> None:
        item = self.games.itemAt(pos)
        if item is None or not self.games.isEnabled():
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(tr("Удалить копии игры…")).triggered.connect(lambda: self._delete_game(name))
        menu.exec(self.games.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _delete_current_game(self) -> None:
        if self._current_game is not None:
            self._delete_game(self._current_game)

    def _delete_game(self, name: str) -> None:
        entries = self._games.get(name, [])
        if not entries:
            return
        files = len(entries)
        text = (trn(files, "Удалить все резервные копии игры «{name}» ({n} файл)?",
                    "Удалить все резервные копии игры «{name}» ({n} файла)?",
                    "Удалить все резервные копии игры «{name}» ({n} файлов)?", name=name)
                + "\n\n" + tr("Вы уверены? Вернуть эти файлы к сохранённым версиям будет уже нельзя."))
        if QMessageBox.question(self, tr("Удалить копии игры"), text) != QMessageBox.StandardButton.Yes:
            return
        self._stop_workers()
        try:
            freed = delete_backups_of([e.original for e in entries])
        except BackupError as e:
            QMessageBox.warning(self, tr("Удалить копии игры"), str(e))
            self._reload_entries()
            return
        if self._log is not None:
            self._log(tr("Удалены резервные копии игры «{name}» ({size}).", name=name, size=format_size(freed)))
        self._reload_entries()

    def _delete_all(self) -> None:
        if not self._games:
            return
        games = len(self._games)
        text = (trn(games, "Удалить все резервные копии ({n} игра)?", "Удалить все резервные копии ({n} игры)?",
                    "Удалить все резервные копии ({n} игр)?")
                + "\n\n" + tr("Вы уверены? Вернуть файлы к сохранённым версиям будет уже нельзя."))
        if QMessageBox.question(self, tr("Удалить все копии"), text) != QMessageBox.StandardButton.Yes:
            return
        self._stop_workers()
        try:
            freed = delete_all_backups()
        except BackupError as e:
            QMessageBox.warning(self, tr("Удалить все копии"), str(e))
            self._reload_entries()
            return
        if self._log is not None:
            self._log(tr("Удалены все резервные копии ({size}).", size=format_size(freed)))
        self._reload_entries()

    def _update_delete_buttons(self) -> None:
        self.btn_delete_all.setEnabled(bool(self._games))
        self.btn_delete_game.setVisible(bool(self._current_game and self._games.get(self._current_game)))

    # ---- results -----------------------------------------------------------------------------------
    def selected_originals(self) -> List[str]:
        """Files ticked to be restored."""
        return [o for o, it in self._items.items() if it.checkState(COL_NAME) == Qt.CheckState.Checked]

    def copy_path_for(self, original: str) -> str:
        copy = self._chosen.get(original)
        if copy is not None:
            return copy.path
        copies = copies_of(original)
        return copies[0].path if copies else ""

    def safety_copy(self) -> bool:
        return self.chk_safety.isChecked()

    def _update_summary(self) -> None:
        files = len(self.selected_originals())
        self.lbl_summary.setText(
            trn(files, "Будет возвращён {n} файл", "Будет возвращено {n} файла", "Будет возвращено {n} файлов")
            if files else tr("Отметьте, что вернуть."))
        self.btn_restore.setEnabled(bool(files))
        self.btn_toggle_all.setVisible(bool(self._items))
        all_ticked = bool(self._items) and all(
            it.checkState(COL_NAME) == Qt.CheckState.Checked for it in self._items.values())
        self.btn_toggle_all.setText(tr("Снять все") if all_ticked else tr("Выбрать все"))
        self._update_delete_buttons()
