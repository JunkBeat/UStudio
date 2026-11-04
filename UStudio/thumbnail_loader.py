"""Background thumbnails for the «Сведения» lists (core/thumbnails.py does the drawing).

One worker thread. request(jobs) REPLACES whatever is waiting (only the rows on screen matter, and a new
selection makes the old rows irrelevant); finished pictures are kept in a small LRU cache. The thread reads
objects through the game's files, so — like the preview worker and the usage index — it is stopped and waited out
before the Environment is torn down (stop_for_teardown, from PreviewPanel.pause_for_environment_teardown). Results
travel as PIL images; the GUI thread turns them into icons (the project rule: no QImage/QPixmap off the GUI thread,
see gui_common.pil_to_qpixmap)."""

import threading
from collections import OrderedDict

from PyQt6.QtCore import QObject, pyqtSignal

from core.thumbnails import AtlasScope, batch_order, thumbnail


def thumbnail_key(obj) -> tuple:
    return (id(obj.assets_file), getattr(obj.assets_file, "name", ""), obj.path_id)


class ThumbnailLoader(QObject):
    ready = pyqtSignal(object, object)      # key, PIL image or None (nothing to draw)

    CACHE_SIZE = 600                        # pictures of <= 48x48: a few MB at most

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: "OrderedDict[tuple, object]" = OrderedDict()   # key -> QIcon (None = no picture)
        self._jobs: list = []
        self._generation = 0
        self._cond = threading.Condition()
        self._busy = False
        self._thread = None

    # ---------------------------------------------------------------- GUI thread

    def cached(self, key):
        """(found, icon): icon may be None when the object has no picture."""
        if key in self._cache:
            self._cache.move_to_end(key)
            return True, self._cache[key]
        return False, None

    def store(self, key, icon) -> None:
        self._cache[key] = icon
        self._cache.move_to_end(key)
        while len(self._cache) > self.CACHE_SIZE:
            self._cache.popitem(last=False)

    def request(self, objects: list) -> None:
        """Draw these (not cached yet) objects' thumbnails, dropping anything still waiting."""
        jobs = [(thumbnail_key(o), o) for o in objects]
        jobs = [(k, o) for k, o in jobs if k not in self._cache]
        with self._cond:
            self._generation += 1
            self._jobs = jobs
            if jobs and self._thread is None:
                self._thread = threading.Thread(target=self._run, name="thumbnails", daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def stop_for_teardown(self, wait_s: float = 3.0) -> None:
        """Drop the waiting jobs and wait for the one being drawn; forget every picture (a new game follows)."""
        with self._cond:
            self._generation += 1
            self._jobs = []
            self._cond.notify_all()
            if self._busy:
                self._cond.wait_for(lambda: not self._busy, wait_s)
        self._cache.clear()

    # ---------------------------------------------------------------- worker thread

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: bool(self._jobs))
                jobs, generation = self._jobs, self._generation
                self._jobs = []
                self._busy = True
            try:
                self._draw(jobs, generation)
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def _draw(self, jobs: list, generation: int) -> None:
        by_object = {id(o): k for k, o in jobs}
        objects = batch_order([o for _k, o in jobs])
        with AtlasScope(objects):
            for obj in objects:
                if self._generation != generation:
                    return              # a new selection / teardown: the rest is not wanted any more
                image = thumbnail(obj)
                try:
                    self.ready.emit(by_object[id(obj)], image)
                except RuntimeError:
                    return              # the loader's QObject is gone (window closed)
