from core.i18n import N_, tr, trn
import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QVBoxLayout,
)

from config import CONFIG, LogLevel
from core.version_writer import (
    STATUS_ALREADY_OK, STATUS_ERROR, STATUS_PATCHED, STATUS_UNSUPPORTED, patch_many, plan_files, validate_version,
)
from dialogs.app_settings_dialog import _make_help_icon
from gui_workers import BackgroundWorker
from app_settings import app_settings

_TITLE = N_("Вшить версию в Unity файлы")   # window title, message boxes and the progress line

_FAILED = (STATUS_ERROR, STATUS_UNSUPPORTED)
_DONE = (STATUS_PATCHED, STATUS_ALREADY_OK)   # the file carries the version now (already_ok: it did before)


class _CompactList(QListWidget):
    """A QListWidget's own size hint is a tall 192 px, which made the dialog open much taller than it needs
    to be. This one asks for no more than its minimum height; it still grows when the window is dragged
    taller (it is the only widget that takes the extra room)."""

    def sizeHint(self):
        return QSize(super().sizeHint().width(), self.minimumHeight())


class _StatusLabel(QLabel):
    """A status line that takes no room (and no layout spacing) while it has nothing to say — an empty QLabel
    still left a blank band above the buttons."""

    def __init__(self):
        super().__init__("")
        self.hide()

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


class VersionWriterDialog(QDialog):
    """Инструменты -> «Вшить версию Unity в файлы...». Some games ship files whose header has no
    Unity version; the fallback version in the settings makes them readable, but must be given in
    every session. This writes the version into the files themselves, once (core/version_writer.py
    does the work and checks every result before replacing anything).

    Works on files on disk, independent of what is loaded in the window: pick files or a folder, type
    the version, choose copies or replacement. Modal and one-shot, like AddressablesResolverDialog."""

    _SETTINGS_KEY = "version_writer/last_version"

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle(tr(_TITLE))
        self.setMinimumWidth(520)
        self._worker = None
        self._cancel_requested = False
        self._sources = []   # files and folders, as added

        layout = QVBoxLayout(self)

        # Every section the same way (user request — the version field sat on its title's row, out of line with the
        # others): the title on its own row, the contents indented 16 px under it.
        self.version_title = self._section_title(tr("Версия Unity:"))
        layout.addWidget(self.version_title)
        version_row = QHBoxLayout()
        version_row.setContentsMargins(16, 0, 0, 0)
        saved = app_settings().value(self._SETTINGS_KEY, "", type=str)
        self.version_edit = QLineEdit(CONFIG.fallback_version or saved)
        self.version_edit.setPlaceholderText(tr("например, 6000.0.63f1"))
        version_row.addWidget(self.version_edit, 1)
        version_row.addWidget(_make_help_icon(
            tr("У некоторых игр версия Unity не записана в файлах, поэтому её приходится указывать вручную при "
               "каждой загрузке. Здесь она вшивается в сами файлы один раз. Укажите версию, на которой собрана "
               "игра. Если в файлах уже указана другая версия, она заменяется.")
        ))
        layout.addLayout(version_row)

        # Section titles: the list, the field and the buttons under «Файлы:» (and the choices under «Режим:») are
        # indented a little.
        layout.addSpacing(10)
        self.files_title = self._section_title(tr("Файлы:"))
        layout.addWidget(self.files_title)
        files_block = QVBoxLayout()
        files_block.setContentsMargins(16, 0, 0, 0)
        layout.addLayout(files_block)
        self.list_widget = _CompactList()
        self.list_widget.setMinimumHeight(110)
        files_block.addWidget(self.list_widget)
        # A path can be typed or pasted (Enter adds it, if it exists); the buttons below open the pickers.
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(tr("Введите путь или используйте кнопки ниже..."))
        self.path_edit.returnPressed.connect(self._add_typed_path)
        files_block.addWidget(self.path_edit)
        files_row = QHBoxLayout()
        self.btn_add_files = QPushButton(tr("Добавить файлы..."))
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_folder = QPushButton(tr("Добавить папку..."))
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_clear = QPushButton(tr("Очистить"))
        self.btn_clear.clicked.connect(self._clear)
        for b in (self.btn_add_files, self.btn_add_folder, self.btn_clear):
            files_row.addWidget(b)
        files_row.addStretch(1)
        files_block.addLayout(files_row)

        layout.addSpacing(10)
        self.mode_title = self._section_title(tr("Режим:"))
        layout.addWidget(self.mode_title)
        mode_block = QVBoxLayout()
        mode_block.setContentsMargins(16, 0, 0, 0)
        layout.addLayout(mode_block)
        self.radio_replace = QRadioButton(tr("Изменить указанные файлы"))
        self.radio_replace.setChecked(True)
        mode_block.addWidget(self.radio_replace)
        self.radio_copy = QRadioButton(tr("Сохранить результат в отдельную папку:"))
        mode_block.addWidget(self.radio_copy)
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setEnabled(False)
        self.btn_out = QPushButton(tr("Обзор..."))
        self.btn_out.setEnabled(False)
        self.btn_out.clicked.connect(self._browse_out)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(self.btn_out)
        mode_block.addLayout(out_row)
        self.radio_replace.toggled.connect(self._on_mode_changed)

        self.status_label = _StatusLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(90)
        self.log_box.hide()
        layout.addWidget(self.log_box)

        layout.addSpacing(10)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_start = QPushButton(tr("Запустить операцию"))
        self.btn_start.clicked.connect(self._start)
        self.btn_close = QPushButton(tr("Закрыть"))
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setPointSize(10)
        label.setFont(font)
        return label

    # ---------------------------------------------------------------- inputs

    def _start_dir(self) -> str:
        for candidate in (CONFIG.selected_dir, CONFIG.game_data_dir, CONFIG.game_root_dir):
            if candidate and os.path.isdir(candidate):
                return candidate
        return ""

    def _add_source(self, path: str) -> None:
        path = os.path.normpath(path)
        if path not in self._sources:
            self._sources.append(path)
            self.list_widget.addItem(path)

    def _add_typed_path(self):
        path = self.path_edit.text().strip().strip('"')   # "Copy as path" in Explorer wraps the path in quotes
        if not path:
            return
        if not os.path.exists(path):
            self.status_label.setText(tr("Не найдено: {path}", path=path))
            return
        self.status_label.setText("")
        self._add_source(path)
        self.path_edit.clear()

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Выберите файлы"), self._start_dir())
        for p in paths:
            self._add_source(p)

    def _add_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, tr("Выберите папку"), self._start_dir())
        if chosen:
            self._add_source(chosen)

    def _clear(self):
        self._sources.clear()
        self.list_widget.clear()

    def _browse_out(self):
        chosen = QFileDialog.getExistingDirectory(self, tr("Куда сохранить копии"), self.out_edit.text() or self._start_dir())
        if chosen:
            self.out_edit.setText(chosen)

    def _on_mode_changed(self, replace: bool):
        self.out_edit.setEnabled(not replace)
        self.btn_out.setEnabled(not replace)

    def _set_busy(self, busy: bool):
        for w in (self.version_edit, self.path_edit, self.list_widget, self.btn_add_files, self.btn_add_folder, self.btn_clear,
                  self.radio_replace, self.radio_copy, self.out_edit, self.btn_out, self.btn_start):
            w.setEnabled(not busy)
        if not busy:
            self._on_mode_changed(self.radio_replace.isChecked())
        self.progress_bar.setVisible(busy)

    # ---------------------------------------------------------------- run

    def _start(self):
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            version = validate_version(self.version_edit.text())
        except ValueError as e:
            QMessageBox.warning(self, tr(_TITLE), str(e))
            return
        if not self._sources:
            QMessageBox.warning(self, tr(_TITLE), tr("Добавьте файлы или папку."))
            return
        replace = self.radio_replace.isChecked()
        out_dir = None if replace else self.out_edit.text().strip()
        if not replace and not out_dir:
            QMessageBox.warning(self, tr(_TITLE), tr("Укажите папку для сохранения."))
            return
        app_settings().setValue(self._SETTINGS_KEY, version)

        self._cancel_requested = False
        self.log_box.clear()
        self.log_box.hide()
        self._set_busy(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(tr("Поиск файлов..."))
        sources = list(self._sources)

        def work(report):
            cancel = lambda: self._cancel_requested  # noqa: E731
            plan = plan_files(sources, out_dir, cancel)
            if not plan:
                return None

            return patch_many(plan, version, force=True,
                              progress=lambda _phase, i, n, name: report(name, i, n),
                              should_cancel=cancel)

        worker = BackgroundWorker(work, parent=self)
        self._worker = worker
        worker.progress_signal.connect(self._on_progress)
        worker.succeeded_signal.connect(self._on_done)
        worker.failed_signal.connect(self._on_failed)
        worker.start()

    def _on_progress(self, name, current, total):
        self.progress_bar.setRange(0, int(total) or 1)
        self.progress_bar.setValue(int(current))
        self.status_label.setText(tr("{title}: {name} ({done} из {total})", title=tr(_TITLE), name=name, done=int(current) + 1, total=int(total)))

    def _on_failed(self, message):
        self._set_busy(False)
        QMessageBox.critical(self, tr(_TITLE), tr("Ошибка:\n{message}", message=message))

    def _on_done(self, batch):
        self._set_busy(False)
        if batch is None:
            self.status_label.setText(tr("Не найдено файлов Unity."))
            return
        failed = [r for r in batch.results if r.status in _FAILED]
        done = sum(batch.count(s) for s in _DONE)
        text = trn(done, "Версия вшита в {n} файл", "Версия вшита в {n} файла", "Версия вшита в {n} файлов")
        if failed:
            text += " " + tr("(пропущено: {count})", count=len(failed))
        text += "."
        if batch.cancelled:
            text = tr("Отменено.") + " " + text
        self.status_label.setText(text)
        if failed:
            self.log_box.setPlainText("\n".join(
                f"{os.path.basename(r.path) or '—'}: {r.message}" for r in failed))
            self.log_box.show()
        self.main_window.log(text, LogLevel.WARNING if failed else LogLevel.INFO)

    # ---------------------------------------------------------------- closing

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._worker is not None and self._worker.isRunning():
            self._cancel_requested = True
            self.status_label.setText(tr("Отмена..."))
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._cancel_requested = True
            self._worker.wait(5000)
        super().closeEvent(event)
