"""Shared background-thread infrastructure for the GUI layer.

BackgroundWorker is the generic "run one function off the GUI thread, get a single
succeeded/failed result plus optional progress" pattern (originally
CabBrowserDialog's _CabWorkerThread) — it fits any operation whose cancellation is
"soft" (a plain flag the work() closure itself checks, like CabBrowserDialog's
should_cancel=lambda: self._cancel_requested) and that reports one result at the end.

ProgressThrottle (re-exported here from core.progress, where it actually lives —
core/loader.py's parse_objects() needs it too, and core/ can't depend on anything
that pulls in PyQt6) is the time-based progress-throttling idiom duplicated across
several of this app's background operations (TextSearchThread,
and — as a task_queue.TaskQueueManager task fn rather than its own QThread subclass
these days, see object_actions.py's dump_by_script_type — the bulk MonoBehaviour
dump) — extracted since it's genuinely identical everywhere it appears, unlike the
threads' actual cancellation/result-delivery shapes, which differ enough
(TextSearchThread streams incremental result batches; DataLoaderThread has several
distinct decision-point signals; both use QThread's own
isInterruptionRequested()/requestInterruption() hard-cancel mechanism rather than
BackgroundWorker's soft-flag model) that forcing them onto one common worker class
would trade working, well-fitted code for a worse abstraction — so those two keep
their own QThread subclasses, just built on this shared timing utility instead of
each re-deriving it."""

from PyQt6.QtCore import QThread, pyqtSignal

from core.progress import ProgressThrottle  # noqa: F401 — re-exported, see module docstring


class BackgroundWorker(QThread):
    """Runs a single heavy operation (fn) in the background so it doesn't block the
    GUI thread.

    fn is called as fn(report_progress) -> result — report_progress(phase: str,
    current: int, total: int) can (optionally) be called from fn for real progress
    instead of an indeterminate indicator; it's safe to call from the background
    thread — pyqtSignal.emit() itself routes delivery to the GUI thread.

    current/total are declared as `object` rather than `int`: pyqtSignal(..., int,
    int) marshals arguments through a 32-bit C++ int when delivering across threads,
    and some callers report byte counts that, for multi-gigabyte archives, easily
    exceed 2^31 — the result is silent overflow/truncation at the signal level,
    before the value even reaches the Python handler (the same class of bug already
    fixed once on the QProgressBar side — see CabBrowserDialog._update_progress_display).
    `object` passes the Python int through as-is, with no loss of width, whether a
    given caller's counts are small (object counts) or large (byte counts)."""

    succeeded_signal = pyqtSignal(object)
    failed_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str, object, object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn(self.progress_signal.emit)
        except Exception as e:
            # Some exception types (MemoryError, notably) have an empty str(), which
            # used to surface as a QMessageBox with no visible text at all —
            # confusing, not just unhelpful. Fall back to the type name so there's
            # always SOMETHING to go on.
            self.failed_signal.emit(str(e) or type(e).__name__)
        else:
            self.succeeded_signal.emit(result)
