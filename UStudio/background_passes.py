"""One list of the main window's background passes that read the loaded game, so a teardown stops them all.

Every pass that reads objects through the loaded files (the preview and its thumbnails/sprite outlines, the table's
name warm-up and sort/filter/script reads, the usage index, the SDF groups and coverage) must have left them before
the files are released or replaced — a reader still inside a bundle's mapping is an access violation (crash.log, more
than once) or a "file held by this program" on save. That stop used to be a list of calls copied by hand into every
teardown point (a new load, an overwrite save, a restore from backups, the save menu), and a pass added later was not
in it: the table's «Скрипт»-sort resolve and its text-filter pass were still reading Phonopolis when a new load
released it (measured, 2026-10-18).

Now MainWindow registers each pass's stop here once (`_init_background_passes`) and every teardown point calls
`MainWindow._stop_background_readers()`. A stop must WAIT until its pass has left the files, and must be safe to call
when nothing runs. The non-modal tool windows (text search, CAB browser...) are a separate step —
`_close_dialogs_before_env_teardown`, which destroys them — because not every caller closes them.

Not a scheduler: the passes still start themselves, and each paces itself with core.progress.Pacer (rests, waits
while the user is busy). No Qt here."""

from core.i18n import tr
import logging
from typing import Callable, List, Tuple

log = logging.getLogger("ustudio.background")


class BackgroundPasses:
    def __init__(self) -> None:
        self._stops: List[Tuple[str, Callable[[], None]]] = []

    def register(self, name: str, stop: Callable[[], None]) -> None:
        """`stop()` stops the pass and returns once it no longer reads the loaded files."""
        if any(n == name for n, _ in self._stops):
            raise ValueError(f"background pass {name!r} is already registered")
        self._stops.append((name, stop))

    def names(self) -> List[str]:
        return [n for n, _ in self._stops]

    def stop_all(self) -> List[str]:
        """Runs every stop in registration order, even after one fails (each failure is logged — a stop that raises
        must not leave the others running). Returns the names of the stops that raised."""
        failed = []
        for name, stop in self._stops:
            try:
                stop()
            except Exception:
                log.exception(tr("Не удалось остановить фоновую задачу «%s»"), name)
                failed.append(name)
        return failed
