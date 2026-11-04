"""Progress/cancellation seam between core (PyQt-free) business logic and whichever
front end drives it — today, the PyQt6 GUI (via Qt signals); eventually, a
console-mode CLI writing straight to the terminal. core/ code never imports PyQt6 or
emits a signal directly — it only ever talks to a ProgressReporter (or, for
EnvironmentLoader, the richer LoaderCallbacks in core/loader.py)."""

import time
from typing import Protocol


class ProgressReporter(Protocol):
    def on_progress(self, level: int, current: int, total: int, name: str, status: str) -> None:
        """Reports progress for one step of a long-running operation. level=0 is the
        outer/top-level step (e.g. "file N of M in a folder load"), level=1 is a
        nested inner step (e.g. "entry N of M inside one bundle")."""
        ...

    def should_cancel(self) -> bool:
        """Polled between steps — return True to abort the operation cleanly via
        OperationCancelled."""
        ...


class NullProgressReporter:
    """No-op reporter: never cancels, discards all progress. Default for core code
    driven outside of any front end (e.g. a quick script or a future test)."""

    def on_progress(self, level, current, total, name, status) -> None:
        pass

    def should_cancel(self) -> bool:
        return False


class OperationCancelled(Exception):
    """Raised by core code the moment a ProgressReporter.should_cancel() call returns
    True mid-operation — the PyQt-free equivalent of the old loader_thread.py-local
    _UserCancelled, now shared by every core/ operation instead of redefined per file."""


class CoreOperationError(Exception):
    """A core-level operation (loading, CAB archive export/import/rebuild, ...)
    failed in a way that should abort it and be surfaced to the user as an error, not
    just logged and continued — e.g. no files selected, no fallback Unity version
    available, insufficient disk space. The Qt adapter catches this and emits
    error_signal with str(exc), matching what the pre-refactor code did by emitting
    error_signal directly at each of these call sites."""


class ProgressThrottle:
    """Time-based (NOT count-based) progress throttling: reports at most once every
    `interval` seconds, always reporting the final item regardless of timing. Time-
    based throttling is essential once a dataset can legitimately reach tens of
    millions of items (see CLAUDE.md — real fixtures do): a fixed per-item overhead,
    even a cheap one, multiplied by tens of millions of iterations becomes a real,
    visible slowdown in its own right (this project measured ~26 minutes of pure
    sleep from an earlier "throttle every N items" version on the largest fixture).
    Time-based throttling keeps total overhead a roughly constant FRACTION of the
    operation's duration regardless of dataset size.

    Lives here (not in the GUI-only gui_workers.py) because core/loader.py's
    parse_objects() needs it too, and core/ can't import anything that pulls in
    PyQt6 — gui_workers.ProgressThrottle is this same class, re-exported for the
    GUI-thread call sites that already import BackgroundWorker from that module.

    Usage:
        throttle = ProgressThrottle()
        for i, item in enumerate(items):
            if should_cancel(): ...
            if throttle.should_report(i, total):
                report_progress(i + 1, total, f"...{i+1}/{total}")
                throttle.pause()
    """

    def __init__(self, interval: float = 0.15):
        self.interval = interval
        self._last_time = time.monotonic()

    def should_report(self, index: int, total: int) -> bool:
        now = time.monotonic()
        if now - self._last_time >= self.interval or index >= total - 1:
            self._last_time = now
            return True
        return False

    @staticmethod
    def pause():
        """A real, non-zero pause — more reliably yields the GIL (in particular so
        Esc/interruption registers promptly on the GUI thread) than a zero-length
        sleep, which doesn't guarantee the OS scheduler hands control anywhere else,
        especially on Windows."""
        time.sleep(0.001)


class Pacer:
    """The pacing every background pass that reads the loaded game shares (the usage index, the scene hierarchy,
    the SDF groups and coverage, the table's script/name reads): after WORK_SLICE_S of work a real REST_S sleep, and
    while `should_pause()` says the user is busy (MainWindow's UserActivityTracker.busy) no work at all.

    Why: the GUI thread needs the GIL to run, and `time.sleep(0)` does not hand it over reliably on Windows — the
    usage index froze the window 2-4 times for 0.2-0.46 s per load before it rested (measured, CLAUDE.md); 10/1 ms
    gave no stall over 100 ms. Call `step()` between small units of work (one object, one row); it costs one clock
    read. Returns False when `should_stop()` says so — also while waiting out a busy user, so a stop is never held
    up by the pause."""

    WORK_SLICE_S = 0.010
    REST_S = 0.001
    BUSY_SLEEP_S = 0.05

    def __init__(self, should_pause=None, should_stop=None):
        self._should_pause = should_pause
        self._should_stop = should_stop
        self._slice_end = time.perf_counter() + self.WORK_SLICE_S

    def _busy(self) -> bool:
        if self._should_pause is None:
            return False
        try:
            return bool(self._should_pause())
        except Exception:  # a broken hook must never kill the pass
            return False

    def stopped(self) -> bool:
        return self._should_stop is not None and bool(self._should_stop())

    def step(self) -> bool:
        """True = go on, False = stop now."""
        if time.perf_counter() < self._slice_end:
            return True
        if self.stopped():
            return False
        time.sleep(self.REST_S)
        while self._busy():
            if self.stopped():
                return False
            time.sleep(self.BUSY_SLEEP_S)
        self._slice_end = time.perf_counter() + self.WORK_SLICE_S
        return True
