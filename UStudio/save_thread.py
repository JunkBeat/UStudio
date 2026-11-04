"""Thin QThread adapters around core.save_manager — mirrors loader_thread.py's own
"PyQt-free core + thin Qt adapter" split (see that file's module docstring). Both
threads reuse the exact same isInterruptionRequested()/requestInterruption()
cancellation idiom DataLoaderThread already uses, so MainWindow.keyPressEvent's
existing Esc handling can drive either the same way.

CustomPathSaveThread runs the whole "Save files (custom path)" flow in one pass.

OverwritePrepareThread / OverwriteCommitThread are the two phases of "Save files
(overwrite)" — split across a required Environment-teardown step that only
MainWindow can perform (see core.save_manager.prepare_overwrite's docstring for
why overwriting in place needs this at all): MainWindow runs OverwritePrepareThread
first, drops every reference to the loaded Environment once it succeeds, then runs
OverwriteCommitThread to actually write to disk before triggering a fresh reload."""

from PyQt6.QtCore import QThread, pyqtSignal

from core.progress import OperationCancelled
from core.save_manager import commit_overwrite, prepare_overwrite, save_to_custom_path


class CustomPathSaveThread(QThread):
    progress_signal = pyqtSignal(int, int, str)  # current, total, status
    # rows_to_clear is `object`, not `list` — its items are plain dicts holding
    # UnityPy ObjectReader instances (see core.models.RowItem), and PyQt's `list`
    # signal type tries to convert each element to a QVariant; `object` passes
    # the Python list through untouched instead, same reasoning
    # gui_workers.BackgroundWorker's docstring gives for using `object` over
    # `int` for byte counts that could overflow a C++ int.
    finished_signal = pyqtSignal(int, object)     # files_saved, rows_to_clear
    error_signal = pyqtSignal(str)
    cancelled_signal = pyqtSignal()

    def __init__(self, groups, dest_root, base_dir, parent=None):
        super().__init__(parent)
        self._groups = groups
        self._dest_root = dest_root
        self._base_dir = base_dir

    def run(self):
        def report_progress(phase, current, total):
            self.progress_signal.emit(current, total, phase)

        try:
            count, rows = save_to_custom_path(
                self._groups, self._dest_root, self._base_dir,
                report_progress, should_cancel=self.isInterruptionRequested,
            )
        except OperationCancelled:
            self.cancelled_signal.emit()
        except Exception as e:
            # Some exception types (MemoryError, notably) have an empty str() —
            # fall back to the type name, matching every other worker in this
            # app's own handling of this (see gui_workers.BackgroundWorker/
            # task_queue._QueueWorkerThread).
            self.error_signal.emit(str(e) or type(e).__name__)
        else:
            self.finished_signal.emit(count, rows)


class OverwritePrepareThread(QThread):
    progress_signal = pyqtSignal(int, int, str)
    prepared_signal = pyqtSignal(object)  # List[PreparedOverwrite]
    error_signal = pyqtSignal(str)
    cancelled_signal = pyqtSignal()

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self._groups = groups

    def run(self):
        def report_progress(phase, current, total):
            self.progress_signal.emit(current, total, phase)

        try:
            prepared = prepare_overwrite(
                self._groups, report_progress, should_cancel=self.isInterruptionRequested,
            )
        except OperationCancelled:
            self.cancelled_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e) or type(e).__name__)
        else:
            self.prepared_signal.emit(prepared)

    def release_groups(self) -> None:
        """Drops this thread's own reference to `groups` — and, through it, every
        RowItem/ObjectReader/SerializedFile/BundleFile it reaches, all the way
        down to the mmap the source Environment holds open. MUST be called
        (see MainWindow._on_overwrite_prepared) right after prepared_signal's
        payload has been received and BEFORE the caller drops its own
        references and garbage-collects: this QThread is constructed with
        parent=main_window, so PyQt/sip keeps its Python wrapper — and
        therefore this attribute — alive via Qt's own parent-child ownership
        for as long as MainWindow exists, regardless of whether MainWindow
        still assigns it to self.save_thread. Without this, tearing down the
        Environment elsewhere wouldn't actually release anything: this thread
        object would still be pinning the exact same objects alive."""
        self._groups = None


class OverwriteCommitThread(QThread):
    """No cancellation support — by the time this runs, MainWindow has already
    dropped the loaded Environment, so there's no "clean" state left to cancel
    back to; see core.save_manager.commit_overwrite's docstring."""

    progress_signal = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(int)  # files_saved
    error_signal = pyqtSignal(str)
    backup_signal = pyqtSignal(str)  # folder the originals were copied to

    def __init__(self, prepared, make_backup=False, backup_keep=None, parent=None, game_version=None):
        super().__init__(parent)
        self._prepared = prepared
        self._make_backup = make_backup
        self._backup_keep = backup_keep
        self._game_version = game_version

    def run(self):
        def report_progress(phase, current, total):
            self.progress_signal.emit(current, total, phase)

        try:
            count = commit_overwrite(self._prepared, report_progress, make_backup=self._make_backup, backup_keep=self._backup_keep,
                                     on_backup=lambda folder: self.backup_signal.emit(str(folder)),
                                     game_version=self._game_version)
        except Exception as e:
            self.error_signal.emit(str(e) or type(e).__name__)
        else:
            self.finished_signal.emit(count)


class RestoreThread(QThread):
    """Puts files back from backups (core.backup.restore_backup) off the GUI thread."""

    finished_signal = pyqtSignal(list)  # restored original paths
    error_signal = pyqtSignal(str)

    def __init__(self, originals, safety_copy=True, keep_latest=1, parent=None, pairs=None):
        super().__init__(parent)
        self._originals = list(originals)
        self._pairs = list(pairs) if pairs else None  # [(copy_path, original_path)] — chosen copies
        self._safety_copy = safety_copy
        self._keep_latest = keep_latest

    def run(self):
        from core.backup import BackupError, restore_backup, restore_copies
        try:
            if self._pairs:
                done = restore_copies(self._pairs, safety_copy=self._safety_copy, keep_latest=self._keep_latest)
            else:
                done = restore_backup(names=self._originals, safety_copy=self._safety_copy, keep_latest=self._keep_latest)
        except BackupError as e:
            self.error_signal.emit(str(e))
        except Exception as e:  # noqa: BLE001 - reported to the user, never lost
            self.error_signal.emit(str(e) or type(e).__name__)
        else:
            self.finished_signal.emit([str(orig) for _src, orig in done])


