"""Thin Qt adapter around core.loader.EnvironmentLoader — see that module for the
actual loading algorithm (PyQt-free, so it's reusable from a future console-mode
build). This file's only job is: build a LoadOptions from CONFIG, implement
LoaderCallbacks by emitting the signals below (blocking on a queue.Queue for the two
decision points, exactly as before), and translate core's exceptions back into the
signals the rest of the GUI already listens for."""

from core.i18n import tr
import logging
import queue
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from config import CONFIG
from core.options import LoadOptions
from core.loader import EnvironmentLoader
from core.progress import OperationCancelled, CoreOperationError

logger = logging.getLogger("ustudio.gui.loader")


class DataLoaderThread(QThread):
    progress_extended_signal = pyqtSignal(int, int, int, str, str)
    progress_signal = pyqtSignal(int, int, str)
    # `object`, NOT `list`: a list-typed signal argument is converted to a QVariantList element by element
    # (every row dict becomes a QVariantMap) on emit AND back to NEW Python objects on delivery — for a
    # 250k-row load that was ~1.7 s on this thread plus ~2 s on the GUI thread at the very end of loading,
    # all with the GIL held. `object` passes the very same list through.
    finished_signal = pyqtSignal(object, object)
    error_signal = pyqtSignal(str)

    large_load_signal = pyqtSignal(int, bool, int, bool)  # object_count, load_all, legacy_size_bytes, single_big_bundle
    cancelled_signal = pyqtSignal()               # operation was cleanly cancelled (Esc or "Cancel" in a dialog)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._decision_queue: "queue.Queue[str]" = queue.Queue()

    # --- called FROM the GUI thread after a decision dialog closes ---

    def submit_bundle_decision(self, choice: str):
        self._decision_queue.put(choice)

    # --- LoaderCallbacks protocol (see core/loader.py) ---

    def on_progress(self, level, current, total, name, status):
        self.progress_extended_signal.emit(level, current, total, name, status)

    def on_index_progress(self, current, total, status):
        self.progress_signal.emit(current, total, status)

    def should_cancel(self) -> bool:
        return self.isInterruptionRequested()

    def ask_about_large_load(self, info) -> bool:
        self.large_load_signal.emit(info.object_count, info.load_all, info.legacy_size_bytes, info.single_big_bundle)
        return self._decision_queue.get() == "continue"

    # --- entry point ---

    def _build_options(self) -> LoadOptions:
        return LoadOptions(
            load_mode=CONFIG.load_mode,
            selected_dir=CONFIG.selected_dir,
            selected_files=list(CONFIG.selected_files),
            game_data_dir=CONFIG.game_data_dir,
            managed_dir=CONFIG.managed_dir,
            game_root_dir=CONFIG.game_root_dir,
            is_il2cpp=CONFIG.is_il2cpp,
            fallback_version=CONFIG.fallback_version,
            unity_cn_key=CONFIG.unity_cn_key,
            object_count_threshold=CONFIG.object_count_threshold,
            excluded_folders=list(CONFIG.excluded_folders),
            cab_collision_policy=CONFIG.cab_collision_policy,
            load_all_assets=CONFIG.load_all_assets,
            indexed_types=list(CONFIG.indexed_types),
        )

    def run(self):
        loader = EnvironmentLoader(self._build_options(), self)
        try:
            result = loader.load()
        except OperationCancelled:
            logger.warning(tr("Операция прервана пользователем (Esc)."))
            self.cancelled_signal.emit()
            return
        except CoreOperationError as e:
            self.error_signal.emit(str(e))
            return
        except Exception:
            self.error_signal.emit(tr("Критическая ошибка:") + "\n" + traceback.format_exc())
            return

        CONFIG.unity_version = result.unity_version
        CONFIG.platform_name = result.platform_name
        CONFIG.cab_index = result.cab_index
        self.finished_signal.emit(result.objects, result.env)
