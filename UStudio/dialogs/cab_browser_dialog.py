from core.i18n import N_, tr
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QProgressBar, QSizePolicy, QGroupBox, QCheckBox
)

from UnityPy.helpers import CompressionHelper

from config import CONFIG
from core.cab_archive import CabArchive, IMPORT_INMEMORY_WARNING_THRESHOLD, IMPORT_INMEMORY_HARD_LIMIT
from core.progress import CoreOperationError
from core.eta import EtaEstimator
from helpers import format_size, NumericTableWidgetItem
import theme
from gui_workers import BackgroundWorker
from gui_widgets import set_elided_label_text, reapply_elided_labels
from gui_common import exec_and_dispose, export_target_dir
from app_settings import app_settings


# Raw resource payloads (streamed texture/audio/mesh bytes for other objects) —
# never a SerializedFile, so "parsing" one just means reading the whole thing
# into RAM for nothing. A real report: selecting one of these and clicking
# "Загрузить" ran parse_entry_fully()'s `bytes(stream.read(stream.Length))`
# unconditionally, before ImportHelper.parse_file() ever got a chance to say
# "not a SerializedFile" — for a large .resS (routinely hundreds of MB to
# multiple GB, since this is exactly where texture/mesh/audio bulk data lives)
# that's an instant OOM/crash, not a slow parse. Blocked by name/extension here,
# before the background worker even starts, rather than relying on the parser
# to fail gracefully after already having read the whole entry.
_RAW_RESOURCE_SUFFIXES = (".ress", ".resource")


class CabBrowserDialog(QDialog):
    """Browses the contents of a single archive (bundle) — a list of internal files (CAB/level*/
    sharedassets*.assets/...) with View/Export/Import for a single file or for all at once.
    Equivalent to UABEA's "Bundle Contents". A thin Qt adapter: the actual archive logic lives
    in core.cab_archive.CabArchive (no PyQt dependency), run on a background QThread here."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle(tr("Просмотр архива"))
        self.archive: "CabArchive | None" = None
        self.bundle_path = None
        self._worker = None
        self._cancel_requested = False
        self._eta = EtaEstimator()
        # Shared starting directory for the 4 Export/Import file dialogs. Starts unset
        # (falls back to the bundle's own folder, see _start_dir()) and is reset to unset
        # again each time a new archive is opened — so switching to a different archive
        # doesn't drag along wherever exports/imports happened to go for the PREVIOUS one,
        # but within one archive session, Export and Import consistently follow each other
        # (export somewhere, then Import opens there too, and vice versa).
        self._last_used_dir = None
        self._init_ui()
        # IMPORTANT: resize() must come AFTER _init_ui() — otherwise the layout built
        # from the widgets (buttons, table) stretches the dialog again on the first show()
        self.resize(560, 480)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.btn_open = QPushButton(tr("Открыть архив..."))
        self.btn_open.clicked.connect(self.open_archive)
        self.path_label = QLabel(tr("Файл не выбран"))
        # without this a long path dictates its own width to the layout, and the window
        # can be made neither narrower nor smaller — the full path stays visible via tooltip
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top_row.addWidget(self.btn_open)
        top_row.addWidget(self.path_label, 1)
        layout.addLayout(top_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Имя"), tr("Размер"), tr("Объектов")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        # Real reported bug: the table came up sorted by "Имя" in REVERSE
        # (descending) order every time an archive was opened. Root cause,
        # confirmed empirically (not by guessing at Qt's docs, which read the
        # opposite way): QHeaderView's sort indicator defaults to
        # Qt.SortOrder.DescendingOrder when never explicitly set, and
        # setSortingEnabled(True) re-sorts using whatever the indicator
        # currently is — _populate_table()'s own setSortingEnabled(False)/
        # populate/setSortingEnabled(True) sequence re-triggers exactly that on
        # every load, with nothing here having ever set it to ascending.
        # Setting it explicitly once, up front, fixes every future population.
        self.table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        # removes the dotted/colored border around the current cell in row-selection mode —
        # it overlaps the text and makes the value hard to read.
        # ::item:selected with an explicit border:none also kills a Windows-11-style-
        # specific artifact: QWindows11Style draws a thick accent bar on the left edge
        # of a selected item (meant for single-column lists like File Explorer), but
        # on a multi-column view it's drawn per CELL, not once per row, so every column
        # gets its own stripe cutting into the text. Any ::item selector switches Qt to
        # CSS-based item painting instead of the native per-style delegate, which drops it.
        self.table.setStyleSheet(theme.table_selection_qss(theme.get_colors(theme.load_saved_theme_name())))
        self.table.itemSelectionChanged.connect(self._update_button_states)
        layout.addWidget(self.table)

        # Buttons are grouped by meaning (selected entry / whole archive), labeled and
        # aligned to a single fixed width — this used to be one unreadable row of
        # 5 buttons of varying (and in places too narrow) width, which because of "Export
        # all"/"Import all" required a ~800px minimum dialog width.
        actions_box = QGroupBox(tr("Действия"))
        actions_layout = QVBoxLayout(actions_box)

        # fixed (not "Expanding") button width instead of stretching across the row —
        # otherwise the row with 3 buttons and the row with 2 would stretch each button
        # to a different width and stop visually lining up with each other
        BTN_WIDTH = 120
        LABEL_WIDTH = 130

        entry_row = QHBoxLayout()
        entry_label = QLabel(tr("Выбранная запись:"))
        entry_label.setFixedWidth(LABEL_WIDTH)
        entry_row.addWidget(entry_label)
        self.btn_view = QPushButton(tr("Загрузить"))
        self.btn_export = QPushButton(tr("Экспорт"))
        self.btn_import = QPushButton(tr("Импорт"))
        for b in (self.btn_view, self.btn_export, self.btn_import):
            b.setEnabled(False)
            b.setFixedWidth(BTN_WIDTH)
            entry_row.addWidget(b)
        entry_row.addStretch(1)
        actions_layout.addLayout(entry_row)

        archive_row = QHBoxLayout()
        archive_label = QLabel(tr("Весь архив:"))
        archive_label.setFixedWidth(LABEL_WIDTH)
        archive_row.addWidget(archive_label)
        # empty "slot" the width of a button — shifts "Export all"/"Import all" one
        # column to the right so they land under "Export"/"Import" from the row above, not
        # under "Load"/"Export"
        spacer = QLabel("")
        spacer.setFixedWidth(BTN_WIDTH)
        archive_row.addWidget(spacer)
        self.btn_export_all = QPushButton(tr("Экспорт всех"))
        self.btn_import_all = QPushButton(tr("Импорт всех"))
        for b in (self.btn_export_all, self.btn_import_all):
            b.setEnabled(False)
            b.setFixedWidth(BTN_WIDTH)
            archive_row.addWidget(b)
        archive_row.addStretch(1)
        actions_layout.addLayout(archive_row)

        # Applies to Import/Import All (the only operations that rebuild the archive —
        # Export just streams existing bytes out, nothing to compress there). Off by
        # default: unchecked defers to CONFIG.bundle_compression_packer (Настройки →
        # Настройки приложения — Original/None/LZ4/LZMA, "Original" i.e. whatever the
        # archive already used, unless the user changed the global default) instead of
        # a hardcoded "original" — checking it is a fast local override that always
        # skips compression regardless of the global setting. Skipping compression
        # trades a larger output file for a much faster rebuild — the compress phase is
        # consistently the slowest one (see the ETA/progress work elsewhere in this
        # file), so this matters most on the exact large archives where users are
        # already choosing "через диск".
        self.chk_no_compression = QCheckBox(tr("Запаковка без сжатия (в разы быстрее)"))
        self.chk_no_compression.setToolTip(
            tr("Если не отмечено, используется глобальная настройка сжатия из настроек.")
        )
        actions_layout.addWidget(self.chk_no_compression)

        self.actions_box = actions_box
        layout.addWidget(actions_box)

        self.btn_view.clicked.connect(self.view_selected)
        self.btn_export.clicked.connect(self.export_selected)
        self.btn_import.clicked.connect(self.import_selected)
        self.btn_export_all.clicked.connect(self.export_all)
        self.btn_import_all.clicked.connect(self.import_all)

        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        # same treatment as path_label — an un-elided long status message (e.g. a full
        # export path) would otherwise force the dialog wider to fit it
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status_label)

        # second row — speed/ETA and the Esc-cancel hint. Kept separate from
        # status_label so the primary status (phase + byte counts) doesn't have to
        # share one line with this supplementary info; on a narrow dialog the combined
        # line was long enough to force horizontal growth or get elided.
        self.status_label2 = QLabel("")
        self.status_label2.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label2)

    # --- Background execution of heavy operations (don't block the GUI thread) ---

    def _set_busy(self, busy: bool, text: str = "", hint: str = ""):
        """Switches the dialog in/out of a "busy" state for the duration of a background
        operation — disables the buttons and opening a new archive, shows an indeterminate
        progress bar, and explicitly mentions Esc (the only practical way to interrupt an
        already-started operation — the call inside UnityPy itself isn't interrupted, but
        the GUI stops waiting for its result). `text` goes on the primary status line,
        `hint` (e.g. the Esc reminder, or speed/ETA once available) on the second row."""
        self.btn_open.setEnabled(not busy)
        self.table.setEnabled(not busy)
        # disables all 5 buttons at once (load/export/import/export all/import all) —
        # otherwise, for example, "Export" stayed clickable while "Load" was still
        # running in the background for the same archive (a race over self.archive.bundle.files)
        self.actions_box.setEnabled(not busy)
        if busy:
            self.progress_bar.setRange(0, 0)  # indeterminate progress — duration isn't known in advance
            self.progress_bar.show()
            self._set_status_text(text)
            self.status_label2.setText(hint)
        else:
            self.progress_bar.hide()
            self.status_label2.setText("")
            self._update_button_states()

    def _run_background(self, fn, on_success, on_error, busy_text, on_progress=None):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.warning(self, tr("Занято"), tr("Дождитесь завершения текущей операции."))
            return

        self._cancel_requested = False
        self._set_busy(True, busy_text, tr("Esc — отмена"))

        worker = BackgroundWorker(fn, parent=self)
        self._worker = worker
        if on_progress is not None:
            worker.progress_signal.connect(on_progress)

        def _on_succeeded(result):
            self._set_busy(False)
            if self._cancel_requested:
                self._set_status_text(tr("Операция отменена."))
                return
            on_success(result)

        def _on_failed(msg):
            self._set_busy(False)
            if self._cancel_requested:
                self._set_status_text(tr("Операция отменена."))
                return
            on_error(msg)

        worker.succeeded_signal.connect(_on_succeeded)
        worker.failed_signal.connect(_on_failed)
        worker.start()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            # Always intercept Esc entirely, never falling through to QDialog's default
            # "Esc = close window" behavior — otherwise there's a small window between
            # the worker actually finishing (isRunning() becomes False) and the GUI
            # thread processing the already-queued succeeded/failed signal, during which
            # a stray/late Esc would fall through into closing the dialog instead of
            # cancelling (the same bug that existed in TextSearchDialog).
            if self._worker is not None and self._worker.isRunning():
                # soft cancel: the background operation itself is one blocking call inside
                # UnityPy and doesn't check for interruption, but the GUI immediately stops
                # waiting and discards the result once the thread eventually finishes
                self._cancel_requested = True
                self._set_status_text(tr("Отмена... завершение текущего шага (может занять время)."))
            event.accept()
            return
        super().keyPressEvent(event)

    # --- Opening an archive ---

    def open_archive(self):
        settings = app_settings()
        start_dir = settings.value("last_cab_archive_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, tr("Открыть архив"), start_dir, tr("Все файлы (*)"))
        if not path:
            return
        settings.setValue("last_cab_archive_dir", str(Path(path).parent))
        self.open_path(path)

    def open_path(self, path: str):
        """Opens the archive at `path` (the «Окружение» tab's «Открыть в просмотре архива», or the picker above);
        while another operation runs _run_background says so and does nothing."""
        self.raise_()
        self.activateWindow()

        def work(report_progress):
            # BackgroundWorker.run() uses a single fn(report_progress) signature for
            # all tasks — this particular operation doesn't need real progress (one
            # quick scan), so the parameter is simply unused
            return CabArchive.open(path)

        self._run_background(
            work,
            on_success=lambda archive: self._on_archive_opened(path, archive),
            on_error=lambda msg: QMessageBox.critical(self, tr("Ошибка открытия"), tr("Не удалось открыть архив:\n{msg}", msg=msg)),
            busy_text=tr("Сканирование «{name}»...", name=Path(path).name),
        )

    def _on_archive_opened(self, path: str, archive: CabArchive):
        self.archive = archive
        self.bundle_path = path
        self._last_used_dir = None  # new archive — Export/Import should start fresh at its folder
        self._set_path_label_text(path)
        self._populate_table()

    def _set_path_label_text(self, path: str):
        set_elided_label_text(self.path_label, path)

    def _set_status_text(self, text: str):
        """Sets status_label's text, eliding it (full text kept as a tooltip) the same
        way _set_path_label_text does for path_label — a status message can contain a
        full absolute path (e.g. "Экспортировано: C:\\...\\long\\path\\file.dat"), and
        an un-elided QLabel forces the dialog wider to fit it instead of just truncating."""
        set_elided_label_text(self.status_label, text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.bundle_path:
            self._set_path_label_text(self.bundle_path)
        reapply_elided_labels(self.status_label)

    def _populate_table(self):
        self.table.setSortingEnabled(False)
        entries = self.archive.entries()
        self.table.setRowCount(len(entries))
        for row, (name, size, obj_count) in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, NumericTableWidgetItem(format_size(size), size))
            obj_count_text = "-" if obj_count is None else f"{obj_count:,}".replace(",", " ")
            self.table.setItem(row, 2, NumericTableWidgetItem(obj_count_text, -1 if obj_count is None else obj_count))

        self.table.setSortingEnabled(True)
        self._set_status_text(tr("Загружено записей: {count}", count=len(entries)))
        self._update_button_states()

    def _update_button_states(self):
        has_archive = self.archive is not None
        has_selection = has_archive and self.table.currentRow() >= 0
        selected_name = self._selected_name() if has_selection else None
        is_raw_resource = selected_name is not None and selected_name.lower().endswith(_RAW_RESOURCE_SUFFIXES)
        self.btn_view.setEnabled(has_selection and not is_raw_resource)
        self.btn_view.setToolTip(
            tr("Файл сырых ресурсов (.resS/.resource) — нет объектов для отображения, используйте «Экспорт».")
            if is_raw_resource else ""
        )
        self.btn_export.setEnabled(has_selection)
        self.btn_import.setEnabled(has_selection)
        self.btn_export_all.setEnabled(has_archive)
        self.btn_import_all.setEnabled(has_archive)

    def _selected_name(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).text()

    # --- Viewing / exporting a single file ---

    def view_selected(self):
        """Fully parses the selected entry (plus its declared dependencies) and loads
        its objects into the main window's table — the same as a normal file/folder
        load, just for a single internal file of the bundle, without parsing the
        archive's other (potentially huge) entries. Parsing (and the subsequent
        collection of MonoBehaviour objects) runs on a background thread — for large
        internal files this can take noticeable time and used to completely freeze
        the dialog."""
        name = self._selected_name()
        if name is None:
            return

        if name.lower().endswith(_RAW_RESOURCE_SUFFIXES):
            QMessageBox.warning(
                self, tr("Загрузка недоступна"),
                tr("«{name}» — это файл ресурсов (.resS/.resource), а не файл с объектами.\nВ нём нет объектов для "
                   "отображения — только данные, на которые ссылаются объекты из других файлов архива.\n\nИспользуйте "
                   "«Экспорт», чтобы сохранить его содержимое как есть.", name=name)
            )
            return

        def work(report_progress):
            # no real progress needed here (see the comment in open_archive)
            return self.archive.view_entry(name)

        self._run_background(
            work,
            on_success=lambda result: self._on_entry_parsed(name, *result),
            on_error=lambda msg: QMessageBox.critical(self, tr("Ошибка разбора"), tr("Не удалось разобрать «{name}»:\n{msg}", name=name, msg=msg)),
            busy_text=tr("Разбор «{name}»...", name=name),
        )

    def _on_entry_parsed(self, name: str, parsed_entry, data):
        if data is None:
            QMessageBox.information(
                self, tr("Просмотр"),
                tr("«{name}» не содержит объектов для отображения.", name=name)
            )
            return

        if self.main_window is not None and hasattr(self.main_window, "load_entry_objects"):
            source_label = f"{Path(self.bundle_path).name}/{name}"
            self.main_window.load_entry_objects(data, parsed_entry, source_label)
            # Deliberately doesn't repeat the object count here — main_window.load_entry_objects()
            # already reports it in both the status bar and the log (the same two places any
            # normal load reports it), so this dialog's own status line only confirms the
            # action, instead of being a third copy of the identical number.
            self._set_status_text(tr("«{name}» загружено в основное окно", name=name))
        else:
            QMessageBox.information(
                self, tr("Просмотр"),
                tr("«{name}»: всего объектов {count}, из них MonoBehaviour: {count2}.", name=name, count=len(parsed_entry.objects), count2=len(data))
            )

    def _start_dir(self) -> str:
        """Starting directory for the 4 Export/Import file dialogs: wherever Export/Import
        last actually went during this archive session (self._last_used_dir), falling back
        to the bundle's own folder if nothing's been picked yet. See the comment on
        self._last_used_dir in __init__ for why it's reset per-archive rather than shared
        via QSettings across different archives/sessions."""
        if self._last_used_dir:
            return self._last_used_dir
        if not self.bundle_path:
            return ""
        return str(Path(self.bundle_path).parent)

    def export_selected(self):
        name = self._selected_name()
        if name is None:
            return

        start_dir = self._start_dir()
        suggested = str(Path(start_dir) / name) if start_dir else name
        out_path, _ = QFileDialog.getSaveFileName(self, tr("Сохранить как..."), suggested)
        if not out_path:
            return

        self._last_used_dir = str(Path(out_path).parent)
        self._eta.reset()

        # Runs on the background worker thread (not a synchronous call here on the GUI
        # thread) and reports real byte-weighted progress — a single large entry (e.g. a
        # multi-GB .resS) used to just block the GUI outright with no feedback at all.
        # should_cancel wires up Esc to actually interrupt mid-copy instead of only being
        # checked between whole files. The disk-space pre-flight check and the
        # "no data in this entry" check both live in CabArchive.export_entry now — a
        # failure there surfaces through on_error below, same end result as the old
        # inline pre-checks.
        def work(report_progress):
            report = CompressionHelper.ThrottledProgress(lambda cur, tot: report_progress("export", cur, tot))
            self.archive.export_entry(
                name, out_path,
                progress_callback=report,
                should_cancel=lambda: self._cancel_requested,
            )
            return out_path

        self._run_background(
            work,
            on_success=lambda path: self._set_status_text(tr("Экспортировано: {path}", path=path)),
            on_error=lambda msg: QMessageBox.critical(self, tr("Ошибка экспорта"), msg),
            busy_text=tr("Экспорт «{name}»...", name=name),
            on_progress=self._on_export_progress,
        )

    def export_all(self):
        dir_path = QFileDialog.getExistingDirectory(self, tr("Выберите папку для экспорта"), self._start_dir())
        if not dir_path:
            return

        self._last_used_dir = dir_path
        self._eta.reset()
        export_dir = str(export_target_dir(dir_path))   # <chosen>/UStudio_Assets unless that setting is off

        # Same fix as export_selected above, generalized across all entries: progress is
        # byte-weighted across the WHOLE export (not per-entry-index, which would sit stuck
        # at "entry N of M" for however long one disproportionately large entry takes — the
        # exact "reaches 99% then freezes" symptom, mirrored across entries too), runs off
        # the GUI thread, and should_cancel makes Esc responsive mid-entry. Disk-space
        # pre-flight check lives in CabArchive.export_all now.
        def work(report_progress):
            report = CompressionHelper.ThrottledProgress(lambda cur, tot: report_progress("export", cur, tot))
            return self.archive.export_all(export_dir, progress_callback=report, should_cancel=lambda: self._cancel_requested)

        self._run_background(
            work,
            on_success=lambda exported: self._set_status_text(tr("Экспортировано {exported} файлов в {export_dir}", exported=exported, export_dir=export_dir)),
            on_error=lambda msg: QMessageBox.critical(self, tr("Ошибка экспорта"), msg),
            busy_text=tr("Экспорт всех файлов..."),
            on_progress=self._on_export_progress,
        )

    # --- Import (rebuilds the archive entirely and saves it as a new file) ---

    def _choose_rebuild_mode(self) -> str:
        """Returns 'memory' / 'disk' / 'cancel'. Below the warning threshold — always
        'memory' with no dialog (as before). Above it — lets the user choose between the
        old approach (faster, but requires free RAM roughly equal to the decompressed
        archive size, and — importantly — can barely be interrupted mid-way, see below)
        and a streamed rebuild via disk (slower, barely uses RAM, temporarily requires
        disk space roughly twice the decompressed archive size —
        BundleFile.save_to_file() checks this itself before starting and fails with a
        clear error if there isn't enough space — but genuinely gets interrupted by Esc
        within seconds). Above the hard limit, there's no real choice to make — 'in
        memory' was never offered there anyway (on the real 7GB/~35GB-decompressed
        archive the user chose it, tried to cancel, and couldn't short of force-quitting)
        — so it goes straight to 'disk' without a confirmation dialog: a dialog whose
        only button is "proceed the only way this can proceed" isn't a real choice, just
        an extra click. Esc still works once the operation is running (see
        save_to_file's should_cancel)."""
        total_size = self.archive.bundle.decompressed_size
        if total_size <= IMPORT_INMEMORY_WARNING_THRESHOLD:
            return "memory"

        if total_size > IMPORT_INMEMORY_HARD_LIMIT:
            return "disk"

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("Пересборка архива"))
        box.setText(
            tr("Разжатый вес архива — {size}. Архив пересобирается ЦЕЛИКОМ, включая нетронутые записи — так "
               "устроен этот формат. Выберите способ:", size=format_size(total_size))
        )
        box.setInformativeText(
            tr("«Через диск» — медленнее (данные временно пишутся на диск), почти не расходует ОЗУ, требует "
               "свободного места на диске примерно вдвое больше разжатого архива — и реально прерывается по Esc "
               "за секунды (видно, на каком шаге: запись/сжатие/сборка).\n\n«В памяти» — быстрее, требует "
               "свободной ОЗУ примерно в объёме разжатого архива, но ПОЧТИ НЕ МОЖЕТ БЫТЬ ПРЕРВАНА на середине — "
               "Esc/«Отмена» лишь перестанут ждать её и отбросят результат, когда она сама закончится, что "
               "может занять долго.")
        )
        btn_disk = box.addButton(tr("Через диск"), QMessageBox.ButtonRole.AcceptRole)
        btn_memory = box.addButton(tr("В памяти"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Отмена"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_disk)
        exec_and_dispose(box)

        clicked = box.clickedButton()
        if clicked is btn_disk:
            return "disk"
        if clicked is btn_memory:
            return "memory"
        return "cancel"

    def import_selected(self):
        name = self._selected_name()
        if name is None:
            return

        name_filter = f"{name}"
        all_files_filter = tr("Все файлы (*)")
        filters = f"{name_filter};;{all_files_filter}"

        src_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Выберите файл для замены «{name}»", name=name),
            self._start_dir(),
            filters,
            name_filter,  # selectedFilter: makes the name-based filter the active/default one
        )
        if not src_path:
            return
        self._last_used_dir = str(Path(src_path).parent)
        self._rebuild_and_save({name: src_path})

    def import_all(self):
        dir_path = QFileDialog.getExistingDirectory(self, tr("Выберите папку с файлами для импорта"), self._start_dir())
        if not dir_path:
            return
        self._last_used_dir = dir_path

        replacements = self.archive.match_files_for_import(dir_path)

        if not replacements:
            QMessageBox.information(
                self, tr("Импорт"),
                tr("В выбранной папке не найдено файлов, совпадающих по имени с содержимым архива.")
            )
            return

        # Automatic check instead of always asking "are you sure" — a generic warning on
        # every single Import All just trains the user to click through it without
        # reading. The one thing actually worth flagging, and checkable without any
        # guesswork about what the user "meant": Windows filesystems are case-insensitive,
        # so two DIFFERENT archive entry names differing only by case would both resolve
        # to the SAME physical file here — meaning the same content silently gets packed
        # into two logically distinct entries. That's a real, mechanical problem, not a
        # vague "maybe wrong folder" worry, so it's the only thing that interrupts the user.
        collisions = self.archive.find_import_all_collisions(replacements)

        if collisions:
            lines = "\n".join("  • " + tr("«{a}» и «{b}» → {path}", a=a, b=b, path=p) for a, b, p in collisions)
            confirm = QMessageBox.question(
                self, tr("Импорт всех — обнаружено совпадение путей"),
                tr("{count} записей архива совпадают по имени файла с уже использованным файлом в «{dir_path}» "
                   "(файловая система Windows не различает регистр букв):\n\n{lines}\n\nЭто значит, что одно и то же "
                   "содержимое будет упаковано в несколько разных записей архива одновременно. Продолжить всё равно?", count=len(collisions), dir_path=dir_path, lines=lines),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self._rebuild_and_save(replacements)

    def _rebuild_and_save(self, replacements: dict):
        mode = self._choose_rebuild_mode()
        if mode == "cancel":
            return

        out_path, _ = QFileDialog.getSaveFileName(self, tr("Сохранить изменённый архив как..."), self.bundle_path)
        if not out_path:
            return

        # read on the GUI thread now, before work() runs in the background — Qt widget
        # access isn't safe from a worker thread, so the checkbox's state is captured
        # here as a plain value, not read live from inside work(). Unchecked falls back
        # to the global default (Настройки приложения) instead of a hardcoded "original".
        packer = "none" if self.chk_no_compression.isChecked() else CONFIG.bundle_compression_packer

        def work(report_progress):
            return self.archive.rebuild_and_save(
                out_path, replacements, mode=mode, packer=packer,
                progress_callback=report_progress,
                should_cancel=lambda: self._cancel_requested,
            )

        # reset the speed/ETA tracker before each new run — otherwise, if the
        # previous rebuild was cancelled in the middle of the same phase ("write" -> "write"),
        # the phase change wouldn't be detected and the estimate would be computed from
        # stale, no-longer-relevant reference points and timestamps
        self._eta.reset()

        self._run_background(
            work,
            on_success=lambda count: self._on_rebuild_saved(out_path, count),
            on_error=lambda msg: QMessageBox.critical(self, tr("Ошибка сохранения"), msg),
            busy_text=(tr("Пересборка архива (через диск)...") if mode == "disk"
                       else tr("Пересборка архива (в памяти)...")),
            # disk-mode-only: save_to_file() reports write/compress/assemble progress via
            # checkpoints; bundle.save() (memory mode) is a couple of monolithic calls with
            # nothing to report progress from (see the comment on mode == "disk" above)
            on_progress=self._on_rebuild_progress if mode == "disk" else None,
        )

    _PHASE_LABELS = {
        "write": N_("Запись содержимого архива"),
        "compress": N_("Сжатие"),
        "assemble": N_("Сборка итогового файла"),
        "export": N_("Экспорт"),
    }

    def _update_progress_display(self, phase: str, current: int, total: int):
        """Shared by _on_rebuild_progress and _on_export_progress — both report byte
        counts for a possibly multi-gigabyte operation, so both need the same 32-bit
        QProgressBar workaround and the same speed/ETA row-2 treatment."""
        label = tr(self._PHASE_LABELS.get(phase, phase))
        # QProgressBar.setRange()/setValue() take a 32-bit (C++) int — max ~2.1
        # billion. current/total here are measured in BYTES, and for an archive
        # in the tens of gigabytes they easily exceed that limit several times over. Passing
        # such a value directly causes overflow/truncation on Qt's side:
        # the bar jumps to ~200%, then to negative millions, to zero, and around again —
        # it looks like "compression broke", though in reality only the progress
        # widget itself broke, not the operation. So the fraction is computed here in
        # Python (Python ints have no bit-width limit) and only a small,
        # guaranteed-safe 0..SCALE scale is handed to Qt.
        SCALE = 10000
        fraction = current / total if total > 0 else 0.0
        safe_value = max(0, min(int(fraction * SCALE), SCALE))
        self.progress_bar.setRange(0, SCALE)
        self.progress_bar.setValue(safe_value)
        eta_fragment = self._eta.update(phase, current, total)
        # the status line text is assembled as a plain Python string — there's no
        # bit-width limit here, so the real (large) numbers are shown as-is.
        # eta_fragment is formatted separately (not via replace) — it doesn't use
        # a comma as a thousands separator, and the .replace(",", " ") below applies
        # only to current/total.
        counts = f"{current:,} / {total:,}".replace(",", " ")
        self._set_status_text(f"{label}: {counts}")
        # second row: speed/ETA once available, plus the Esc reminder — kept off the
        # primary line so it doesn't force the dialog wider or get elided on a small window
        hint = tr("{eta_fragment}, Esc — отмена", eta_fragment=eta_fragment) if eta_fragment else tr("Esc — отмена")
        self.status_label2.setText(hint)

    def _on_rebuild_progress(self, phase: str, current: int, total: int):
        self._update_progress_display(phase, current, total)

    def _on_export_progress(self, phase: str, current: int, total: int):
        self._update_progress_display(phase, current, total)

    def _on_rebuild_saved(self, out_path: str, replaced_count: int):
        self._set_status_text(tr("Сохранено: {out_path} ({replaced_count} файлов заменено)", out_path=out_path, replaced_count=replaced_count))
        QMessageBox.information(
            self, tr("Готово"),
            tr("Изменённый архив сохранён:\n{out_path}\n\nНапоминание: это НЕ гарантирует, что игра примет "
               "изменённый файл — некоторые сборки Unity проверяют хэш data.unity3d при запуске и отклонят "
               "любое изменение.", out_path=out_path)
        )
