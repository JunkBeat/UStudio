from core.i18n import tr
import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFileDialog, QMessageBox, QProgressBar,
)

from config import CONFIG, LoadMode
from core.addressables_resolver import CabIndex, build_cab_index_for_folder
from core.object_preview import ROW_FIELD_UNRESOLVED, get_row_script_name
from dialogs.app_settings_dialog import _make_help_icon
from gui_workers import BackgroundWorker


class AddressablesResolverDialog(QDialog):
    """Explicit, user-triggered fallback for the case core/loader.py's own free
    piggyback scan (see EnvironmentLoader._scan_and_confirm()) doesn't cover: a
    single bundle loaded via "Load files" has no whole-folder scan to build a
    CabIndex from at all, which is exactly the reported scenario (one Addressables
    asset bundle loaded on its own, its MonoBehaviours' Script column showing
    "Unknown" because their scripts live in a sibling *_monoscripts.bundle that was
    never opened). See core/addressables_resolver.py's own module docstring for the
    full root cause.

    Modal and one-shot by design (not a singleton like CabBrowserDialog/
    SceneViewerDialog) — it doesn't hold any live state of its own once closed, and
    "scan this folder, then refresh the table" is a single, complete action rather
    than an ongoing tool a user would reopen mid-session."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle(tr("Разрешение ссылок в соседних бандлах"))
        # Halved per direct request, now that the always-visible explanatory
        # paragraph (moved behind the "(?)" hint above) no longer needs the extra
        # width to read comfortably — the remaining content (folder path field,
        # buttons, status/progress) is comfortable well below the old 560px floor.
        self.setMinimumWidth(400)
        self._worker = None
        self._cancel_requested = False

        layout = QVBoxLayout(self)

        # Real reported request: the always-visible explanatory paragraph made the
        # window feel cluttered — moved behind a "(?)" hover icon next to a short
        # label instead (same _make_help_icon() pattern already used elsewhere for
        # exactly this "keep the window compact, the detail is one hover away"
        # complaint — see app_settings_dialog.py's own docstring for it). Wording
        # simplified for an end user, not a developer: no "Addressables"/"CAB"/
        # ".bundle" jargon, no example path.
        folder_label_row = QHBoxLayout()
        folder_label_row.addWidget(QLabel(tr("Папка для поиска:")))
        folder_label_row.addWidget(_make_help_icon(
            tr("Некоторые скрипты могут находиться в других файлах рядом с загруженными — из-за этого их имена "
               "не определяются. Укажите папку, где их искать: обычно это та же папка, где лежат файлы игры.")
        ))
        folder_label_row.addStretch(1)
        layout.addLayout(folder_label_row)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(self._default_folder())
        folder_row.addWidget(self.folder_edit)
        btn_browse = QPushButton(tr("Обзор..."))
        btn_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(btn_browse)
        layout.addLayout(folder_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_start = QPushButton(tr("Начать поиск"))
        self.btn_start.clicked.connect(self._start)
        btn_row.addWidget(self.btn_start)
        self.btn_close = QPushButton(tr("Закрыть"))
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        self.layout().activate()
        self.adjustSize()

    def _default_folder(self) -> str:
        # The reported case is a single bundle opened with "Load files": the missing script file is
        # most likely beside it, so that folder comes first (selected_dir may be a stale earlier pick).
        beside_loaded = ""
        if CONFIG.load_mode == LoadMode.FILES and CONFIG.selected_files:
            beside_loaded = os.path.dirname(CONFIG.selected_files[0])
        for candidate in (beside_loaded, CONFIG.selected_dir, CONFIG.game_data_dir, CONFIG.game_root_dir):
            if candidate and Path(candidate).is_dir():
                return candidate
        return ""

    def _browse_folder(self):
        start = self.folder_edit.text().strip() or self._default_folder()
        chosen = QFileDialog.getExistingDirectory(self, tr("Выберите папку для поиска"), start)
        if chosen:
            self.folder_edit.setText(chosen)

    def _start(self):
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, tr("Разрешение ссылок"), tr("Укажите существующую папку."))
            return
        if self._worker is not None and self._worker.isRunning():
            return

        # Extends CONFIG.cab_index IN PLACE (add_bundle() mutates its own dict, never
        # reassigns it) rather than replacing it — core/loader.py's own
        # env.external_cab_resolver closure (wired at load time, see
        # EnvironmentLoader.prepare_environment()) already points at this exact
        # object, so nothing here needs to re-wire it for the common case; the
        # defensive re-wire in _on_succeeded below only matters if that assumption
        # ever turns out to be wrong for some environment.
        if CONFIG.cab_index is None:
            CONFIG.cab_index = CabIndex()
        index = CONFIG.cab_index

        self._cancel_requested = False
        self.btn_start.setEnabled(False)
        self.folder_edit.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText(tr("Сканирование..."))

        def work(report_progress):
            def progress_cb(current, total, path):
                pct = int(current / total * 100) if total else 0
                report_progress("scan", pct, os.path.basename(path))
            build_cab_index_for_folder(
                folder, progress_cb=progress_cb,
                should_cancel=lambda: self._cancel_requested, index=index,
            )
            return index

        worker = BackgroundWorker(work, parent=self)
        self._worker = worker
        worker.progress_signal.connect(self._on_progress)
        worker.succeeded_signal.connect(self._on_succeeded)
        worker.failed_signal.connect(self._on_failed)
        worker.start()

    def _on_progress(self, _phase, current, _total):
        self.progress_bar.setValue(int(current))

    def _finish_busy(self):
        self.btn_start.setEnabled(True)
        self.folder_edit.setEnabled(True)
        self.progress_bar.hide()

    def _on_succeeded(self, index: CabIndex):
        self._finish_busy()
        if self._cancel_requested:
            self.status_label.setText(tr("Отменено."))
            return
        CONFIG.cab_index = index

        win = self.main_window
        if win.env is not None:
            # Defensive re-wire (see _start()'s own comment) plus, critically,
            # clearing find_file()'s negative cache — a name that already failed
            # once is recorded in Environment._missing_files and short-circuits
            # BEFORE find_file() ever reaches external_cab_resolver again, so
            # without this, every reference this dialog was specifically opened to
            # fix would keep failing even after the index now has the answer.
            # Confirmed by direct testing against the real Lego Party fixture: the
            # exact same resolver, wired without this clear, still left every
            # MonoBehaviour showing "Unknown".
            win.env.external_cab_resolver = lambda cab_name: index.find(cab_name)
            win.env.reset_missing_files_cache()

        resolved = self._resolve_unknown_rows()
        self.status_label.setText(
            tr("Готово: просканировано файлов {bundles_scanned}, найдено связанных данных: {count}. Обновлено "
               "строк: {resolved}.", bundles_scanned=index.bundles_scanned, count=len(index.entries), resolved=resolved)
        )

    def _on_failed(self, msg):
        self._finish_busy()
        if self._cancel_requested:
            self.status_label.setText(tr("Отменено."))
            return
        QMessageBox.critical(self, tr("Разрешение ссылок"), tr("Ошибка сканирования:\n{msg}", msg=msg))

    def _resolve_unknown_rows(self) -> int:
        """Re-resolves every row currently showing "Unknown" in the Script
        column. get_row_script_name() memoizes on first call (see its own
        docstring in core/object_preview.py) — a row that already resolved to
        "Unknown" needs its cached field reset to ROW_FIELD_UNRESOLVED before
        asking again, otherwise it would just return the same stale cached
        value without ever touching PPtr.deref()/find_file() a second time."""
        win = self.main_window
        model = win.table_model
        resolved_count = 0
        col_count = model.columnCount()
        for item in win.raw_data_list:
            if item.get("script_name") != "Unknown":
                continue
            item["script_name"] = ROW_FIELD_UNRESOLVED
            new_name = get_row_script_name(item)
            if new_name == "Unknown":
                continue
            resolved_count += 1
            row = model.find_row(item)
            if row is not None:
                top_left = model.index(row, 0)
                bottom_right = model.index(row, col_count - 1)
                model.dataChanged.emit(top_left, bottom_right)
        return resolved_count

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self._worker is not None and self._worker.isRunning():
                self._cancel_requested = True
                self.status_label.setText(tr("Отмена... завершение текущего шага."))
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._cancel_requested = True
        super().closeEvent(event)
