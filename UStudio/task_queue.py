"""Single FIFO export/import task queue for the main object table's row-context-menu
actions (see object_actions.ObjectActionsController) — export and import must never
run at the same time, and must never interleave with each other. That guarantee comes
entirely from the shape of this module: there is at most one worker thread
(_QueueWorkerThread) draining one queue.Queue, one task at a time, strictly in
submission order, regardless of whether a given task is an export or an import. No
separate locking is needed to keep the two kinds from overlapping — a single worker can
only ever be doing one thing.

The worker only exists while there is work: it is started on enqueue and exits on its
own once the queue goes idle (see TaskQueueManager._ensure_worker). It used to be started
in __init__ and run forever, relying on MainWindow.closeEvent -> shutdown() to stop it —
so any teardown that didn't go through closeEvent (a script/test constructing MainWindow,
interpreter exit with the window still alive) destroyed a still-running QThread, which is
a Qt qFatal ("QThread: Destroyed while thread is still running") and aborted the process
with exit code 127 after all user code had already finished.

Mirrors this project's established QThread/pyqtSignal/queue.Queue handshake pattern
(see loader_thread.py's docstring) rather than introducing a new concurrency idiom."""

import itertools
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.progress import OperationCancelled


class TaskKind(Enum):
    EXPORT = auto()
    IMPORT = auto()


class TaskStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()
    CANCELLED = auto()


TERMINAL_STATUSES = (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED)

# fn(report_progress, should_cancel) -> result summary (str) or None. Called on the
# worker thread only — must never touch a Qt widget directly (same rule as
# gui_workers.BackgroundWorker/loader_thread.DataLoaderThread). report_progress(current,
# total, phase, succeeded=None, failed=None, log_entries=None) and should_cancel() are
# both safe to call from there; raise core.progress.OperationCancelled (or just return
# after should_cancel() is True) to cooperatively abort.
#
# succeeded/failed are optional — pass them from any per-item loop that tracks its own
# success/failure counts (see object_actions.py's bulk export/dump loops) so the queue
# panel's header stats can show live succeeded/failed counters; omit them (or leave as
# None) for a task with no such per-item breakdown, and the panel just won't show that
# particular stat.
#
# log_entries is an optional list of str or LogNote — per-item notes worth surfacing somewhere
# without cluttering the main app log (a skipped item that's legitimately empty, e.g.
# a Font with no embedded data — not a failure; or a genuine per-item error in a bulk
# operation that otherwise only reports an aggregate count). Batch these locally in the
# fn and pass a batch here at the SAME throttled cadence as everything else — never one
# report_progress call per item — see _MAX_LOG_ENTRIES below for why volume still needs
# a hard cap regardless.
TaskFn = Callable[..., Optional[str]]


@dataclass(frozen=True)
class LogNote:
    """A structured log entry: `count` items shared one `reason` (kind is "skipped" or
    "error"), `names` holds only the first few of them (the producer caps it, so a
    note stays small however many items it stands for). TaskQueuePanel merges notes
    with the same (kind, reason) across the whole task when rendering, so a producer
    can flush whenever it likes without the same reason showing up several times.
    A plain str entry is still fine for anything without that shape."""
    kind: str
    reason: str
    count: int
    names: tuple = ()


_MAX_LOG_ENTRIES = 2000  # per task, and per history entry — see QueuedTask.log_entries'
# docstring: bounds memory even in the pathological case of a bulk operation whose
# every single item logs something (a task with 250,000+ items is a real scenario in
# this app — CLAUDE.md's own fixtures reach into the tens of millions of objects).


@dataclass
class QueuedTask:
    task_id: int
    kind: TaskKind
    title: str
    fn: TaskFn
    status: TaskStatus = TaskStatus.PENDING
    progress_current: int = 0
    progress_total: int = 0
    progress_phase: str = ""
    succeeded_count: int = 0
    failed_count: int = 0
    started_at: Optional[float] = None  # time.monotonic() at the moment it started RUNNING
    error: Optional[str] = None
    result: Optional[str] = None
    # Per-item notes (skipped-but-not-a-failure items, or individual errors within
    # a bulk operation) — see TaskFn's docstring above. Capped at _MAX_LOG_ENTRIES;
    # log_truncated is set once further entries stop being kept, so the UI can say
    # so instead of silently showing an incomplete list as if it were complete.
    log_entries: list = field(default_factory=list)
    log_truncated: bool = False
    cancel_requested: bool = field(default=False, repr=False)


@dataclass
class TaskHistoryEntry:
    """A snapshot of a QueuedTask taken the moment it left the active queue (see
    TaskQueueManager._archive() below) — the active queue itself only ever holds
    active/pending work (see TaskQueueManager's docstring), so without this, a
    finished task's log_entries would simply be gone by the time anything asks to
    see them (e.g. right after a bulk export completes)."""
    kind: TaskKind
    title: str
    status: TaskStatus  # DONE, FAILED, or CANCELLED — never PENDING/RUNNING
    finished_at: float
    succeeded_count: int
    failed_count: int
    result: Optional[str]
    error: Optional[str]
    log_entries: list
    log_truncated: bool


class TaskQueueManager(QObject):
    """Owns the FIFO queue and its one worker thread. Finished/failed/cancelled tasks
    are dropped from the ACTIVE queue right after their terminal signal is emitted —
    the active queue only ever represents "active and pending" work (matching what the
    status-bar indicator/popup panel need to show), not a persistent history, so memory
    use stays bounded regardless of how many exports/imports a long session runs.

    A separate, small, bounded history (see history()/_MAX_HISTORY) keeps a snapshot of
    the last few finished tasks specifically so their log_entries (skipped-but-not-a-
    failure items, per-item errors within a bulk operation — see TaskFn's docstring)
    are still available right after the task itself disappears from the active queue,
    not lost the instant it completes."""

    _MAX_HISTORY = 20  # small — this is "what just happened", not an audit trail

    task_added = pyqtSignal(int)
    task_started = pyqtSignal(int)
    task_progress = pyqtSignal(int, object, object, str)   # task_id, current, total, phase
    task_finished = pyqtSignal(int, str)                    # task_id, result summary
    task_failed = pyqtSignal(int, str)                      # task_id, error message
    task_cancelled = pyqtSignal(int)
    queue_changed = pyqtSignal()
    history_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: dict[int, QueuedTask] = {}
        self._order: list[int] = []
        self._history: list[TaskHistoryEntry] = []  # newest first
        self._id_counter = itertools.count(1)
        self._lock = threading.Lock()
        self._queue: "queue.Queue[Optional[int]]" = queue.Queue()
        # Separate from _lock (which the worker takes inside its _mark_* callbacks) —
        # guards only the start-worker vs. worker-exits-on-idle handoff.
        self._worker_lock = threading.Lock()
        self._worker: Optional[_QueueWorkerThread] = None
        self._worker_active = False   # guarded by _worker_lock

    # --- public API (GUI thread) ---

    def enqueue(self, kind: TaskKind, title: str, fn: TaskFn) -> int:
        task_id = next(self._id_counter)
        task = QueuedTask(task_id=task_id, kind=kind, title=title, fn=fn)
        with self._lock:
            self._tasks[task_id] = task
            self._order.append(task_id)
        self._queue.put(task_id)
        self._ensure_worker()
        self.task_added.emit(task_id)
        self.queue_changed.emit()
        return task_id

    def list_tasks(self) -> list:
        """Active + pending tasks only, in queue order — see the class docstring for
        why finished/failed/cancelled tasks never accumulate here."""
        with self._lock:
            return [self._tasks[tid] for tid in self._order if tid in self._tasks]

    def running_task(self):
        """The single task currently executing, if any — at most one, ever (see the
        module docstring). Used by ObjectActionsController.try_cancel() for Esc."""
        for task in self.list_tasks():
            if task.status == TaskStatus.RUNNING:
                return task
        return None

    def history(self) -> list:
        """The last _MAX_HISTORY finished/failed/cancelled tasks, newest first —
        see the class docstring for why this exists alongside the active-only
        list_tasks()."""
        with self._lock:
            return list(self._history)

    def cancel_task(self, task_id: int) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
            elif task.status == TaskStatus.RUNNING:
                task.cancel_requested = True
                return
            else:
                return
        self._drop_and_emit_cancelled(task_id)

    def cancel_all(self) -> None:
        for task in self.list_tasks():
            self.cancel_task(task.task_id)

    def shutdown(self) -> None:
        """Cancels everything queued, asks the worker to stop after its current task
        notices should_cancel(), and waits briefly for it to exit — call from
        MainWindow.closeEvent, same as PreviewPanel.cleanup(), so the app doesn't warn
        about (or crash on) a QThread destroyed while still running."""
        self.cancel_all()
        with self._worker_lock:
            worker = self._worker
        if worker is None or not worker.isRunning():
            return
        worker.request_stop()
        self._queue.put(None)   # wakes a blocked get() so the stop flag gets seen promptly
        worker.wait(3000)

    def _ensure_worker(self) -> None:
        """Starts a worker if none is currently committed to draining the queue. Must be
        called AFTER the task was put on the queue: the worker only exits when it finds
        the queue empty while holding _worker_lock, so either it sees this task and keeps
        going, or it has already cleared _worker_active and a fresh one is started here.

        A fresh QThread object is created rather than re-start()ing the old one —
        QThread.start() is a silent no-op while isRunning() is still True, which it can
        briefly be after run() has decided to return."""
        with self._worker_lock:
            if self._worker_active:
                return
            old = self._worker
            if old is not None:
                old.wait()   # already committed to exiting — returns almost immediately
                old.deleteLater()
            self._worker = _QueueWorkerThread(self)
            self._worker_active = True
            self._worker.start()

    # --- worker-thread callbacks (each hands off to Qt's queued-connection delivery,
    # so every signal below is safe to connect a GUI-thread slot to directly) ---

    def _mark_running(self, task_id: int) -> Optional[QueuedTask]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != TaskStatus.PENDING:
                return None
            task.status = TaskStatus.RUNNING
            task.started_at = time.monotonic()
        self.task_started.emit(task_id)
        self.queue_changed.emit()
        return task

    def _report_progress(
        self, task_id: int, current: int, total: int, phase: str,
        succeeded: Optional[int] = None, failed: Optional[int] = None,
        log_entries: Optional[list] = None,
    ) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.progress_current = current
            task.progress_total = total
            task.progress_phase = phase
            if succeeded is not None:
                task.succeeded_count = succeeded
            if failed is not None:
                task.failed_count = failed
            if log_entries:
                room = _MAX_LOG_ENTRIES - len(task.log_entries)
                if room > 0:
                    task.log_entries.extend(log_entries[:room])
                if room < len(log_entries):
                    task.log_truncated = True
        # Signal payload deliberately doesn't carry succeeded/failed/log_entries
        # — every listener (TaskQueuePanel) already re-reads the full
        # QueuedTask via list_tasks() on this signal rather than using its
        # arguments, so widening it would just be more plumbing for no one to
        # consume.
        self.task_progress.emit(task_id, current, total, phase)

    def _should_cancel(self, task_id: int) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            return task is not None and task.cancel_requested

    def _mark_finished(self, task_id: int, result: Optional[str]) -> None:
        self._archive_and_drop(task_id, TaskStatus.DONE, result=result)
        self.task_finished.emit(task_id, result or "")
        self.queue_changed.emit()

    def _mark_failed(self, task_id: int, error: str) -> None:
        self._archive_and_drop(task_id, TaskStatus.FAILED, error=error)
        self.task_failed.emit(task_id, error)
        self.queue_changed.emit()

    def _mark_cancelled(self, task_id: int) -> None:
        self._drop_and_emit_cancelled(task_id)

    def _drop_and_emit_cancelled(self, task_id: int) -> None:
        self._archive_and_drop(task_id, TaskStatus.CANCELLED)
        self.task_cancelled.emit(task_id)
        self.queue_changed.emit()

    def _archive_and_drop(
        self, task_id: int, status: TaskStatus,
        result: Optional[str] = None, error: Optional[str] = None,
    ) -> None:
        """Removes task_id from the active queue and — if it was still there
        (it always should be, but cancel_task() on an already-PENDING-turned-
        CANCELLED task can call this a second time defensively) — snapshots it
        into _history first, capped at _MAX_HISTORY, newest first."""
        with self._lock:
            task = self._tasks.pop(task_id, None)
            if task_id in self._order:
                self._order.remove(task_id)
            if task is None:
                return
            task.status = status
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            self._history.insert(0, TaskHistoryEntry(
                kind=task.kind, title=task.title, status=status, finished_at=time.monotonic(),
                succeeded_count=task.succeeded_count, failed_count=task.failed_count,
                result=task.result, error=task.error,
                log_entries=list(task.log_entries), log_truncated=task.log_truncated,
            ))
            del self._history[self._MAX_HISTORY:]
        self.history_changed.emit()


class _QueueWorkerThread(QThread):
    """The one thread that ever runs task fn()s — see the module docstring for why
    this single-worker shape is the whole "export/import can't overlap" guarantee."""

    def __init__(self, manager: TaskQueueManager):
        super().__init__(manager)
        self._manager = manager
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        mgr = self._manager
        while True:
            if self._stop_requested:
                with mgr._worker_lock:
                    mgr._worker_active = False
                return
            try:
                task_id = mgr._queue.get(timeout=0.2)
            except queue.Empty:
                # Idle — exit so no thread outlives the work (see the module docstring).
                with mgr._worker_lock:
                    if mgr._queue.empty():
                        mgr._worker_active = False
                        return
                continue
            if self._stop_requested or task_id is None:
                continue

            task = mgr._mark_running(task_id)
            if task is None:
                # Already cancelled while still pending, or otherwise gone.
                continue

            def report_progress(current, total, phase, succeeded=None, failed=None, log_entries=None, _tid=task_id):
                mgr._report_progress(_tid, current, total, phase, succeeded, failed, log_entries)

            def should_cancel(_tid=task_id):
                return mgr._should_cancel(_tid)

            try:
                result = task.fn(report_progress, should_cancel)
            except OperationCancelled:
                mgr._mark_cancelled(task_id)
            except Exception as e:
                # Some exception types (MemoryError, notably) have an empty str() —
                # fall back to the type name so there's always something to show,
                # matching gui_workers.BackgroundWorker's own handling of this.
                mgr._mark_failed(task_id, str(e) or type(e).__name__)
            else:
                mgr._mark_finished(task_id, result)
