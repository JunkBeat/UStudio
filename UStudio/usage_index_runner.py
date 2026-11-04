"""Builds the «Используется в» index (core/usage_index.py) for the loaded game in a background thread.

One runner per load: MainWindow starts it when a load finishes and stops it (waiting for the thread) before the
Environment is torn down or replaced — the thread reads objects through the game's files, which must not be
closed under it (the same rule as the table's name warm-up). It pauses while the user is active (the window's
UserActivityTracker) and reports progress as a Qt signal (emitted from the thread; delivered queued)."""

import threading
from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from core.usage_index import UsageIndex


class UsageIndexRunner(QObject):
    progress = pyqtSignal(int, int)     # sources read, sources in all
    finished = pyqtSignal()

    _PROGRESS_STEP = 2000               # signal at most every N sources

    def __init__(self, files: list, should_pause: Optional[Callable[[], bool]] = None, parent=None):
        super().__init__(parent)
        self._index = UsageIndex(files, should_pause=should_pause)
        self._thread: Optional[threading.Thread] = None
        self._last_reported = -self._PROGRESS_STEP

    # ---------------------------------------------------------------- life cycle

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="usage-index", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            if self._index.build(on_progress=self._report):
                self.finished.emit()
        except RuntimeError:
            pass        # the runner's QObject is gone (window closed): nothing to tell
        except Exception:
            import logging
            logging.getLogger(__name__).debug("usage index build failed", exc_info=True)

    def _report(self, done: int, total: int) -> None:
        if done - self._last_reported >= self._PROGRESS_STEP or done >= total:
            self._last_reported = done
            self.progress.emit(done, total)

    def stop(self, wait_s: float = 5.0) -> None:
        """Stop and wait for the thread (it checks between small chunks), then drop every object reference."""
        self._index.stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(wait_s)
        self._index.release()

    # ---------------------------------------------------------------- queries

    @property
    def finished_building(self) -> bool:
        return self._index.finished

    @property
    def building(self) -> bool:
        """The thread is still at work (False once it finished, failed or was stopped — never stuck True)."""
        return self._thread is not None and self._thread.is_alive()

    def progress_now(self) -> Tuple[int, int]:
        return self._index.sources_done, self._index.sources_total

    def users(self, obj) -> Optional[List[tuple]]:
        return self._index.users(obj)
