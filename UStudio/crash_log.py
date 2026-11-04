"""Crash logging: every kind of failure ends up in one timestamped file.

Real report: the app died with exception 0xc0000409 in Qt6Core.dll (Windows Event
Log) while changing a value in the SDF generator window, and crash.log was EMPTY.
0xc0000409 is Qt's own fast-fail abort. Under PyQt6, an uncaught Python exception
in a slot/timer/event handler calls qFatal() when sys.excepthook is still the
default (reproduced: a KeyError inside a QTimer callback exits with exactly
-1073740791 == 0xC0000409). faulthandler cannot intercept that, and nothing else
was installed, so nothing was recorded — no exception, no date.

What is recorded now, all in <LOCALAPPDATA>/UStudio/crash.log, each entry with a
local timestamp:
- a header per session (pid, versions);
- uncaught Python exceptions — main thread, other threads, and unraisable ones.
  Installing our own sys.excepthook also stops PyQt from aborting the process, so
  most of these become a logged error instead of a crash;
- Qt critical/fatal messages (qFatal's text is written BEFORE the abort, so the
  reason is captured even when the process still dies) and a capped number of
  warnings;
- faulthandler's native tracebacks (segfaults/access violations). It cannot stamp
  a time itself, so the file's modification time is the crash time;
- abnormal termination detection: a heartbeat file is refreshed while the app
  runs and marked clean at normal exit. If the NEXT launch finds a session that
  never marked itself clean, it logs that, with the last time it was alive — this
  is what identifies crashes nothing above can see (fast-fail aborts, killed
  process)."""

from core.i18n import tr
import atexit
import datetime
import faulthandler
import json
import logging
import os
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Optional

_HEARTBEAT_SECONDS = 15
_MAX_LOG_BYTES = 2 * 1024 * 1024
_MAX_QT_WARNINGS = 200
# Qt's font fallback complaining about system fonts that cannot shape some script, or a legacy bitmap font
# ("Fixedsys") DirectWrite cannot open. Nothing is wrong with the app or its data; the text still renders.
_HARMLESS_QT_WARNINGS = ("OpenType support missing for", "DirectWrite: CreateFontFaceFromHDC() failed")
_font_noise_count = 0

_log_file = None  # kept open for the whole process: faulthandler writes into it at fault time
_log_path = None  # the crash.log path (for the in-app link to it)
_log_lock = threading.Lock()
_state_path: Optional[Path] = None
_state: dict = {}
_qt_warning_count = 0
_logger = logging.getLogger("ustudio.crash")


def now_str() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def default_log_dir() -> Path:
    # USTUDIO_LOG_DIR lets tests and harnesses that launch the real app write somewhere else instead of
    # filling the user's own crash.log with test sessions.
    override = os.environ.get("USTUDIO_LOG_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "UStudio"


def write(text: str) -> None:
    """Appends one timestamped entry. Never raises — logging must not be able to
    cause the failure it is recording."""
    try:
        with _log_lock:
            if _log_file is None:
                return
            _log_file.write(f"[{now_str()}] {text}\n")
            _log_file.flush()
    except Exception:
        pass


def _write_state(clean: bool = False) -> None:
    if _state_path is None:
        return
    try:
        _state["last_alive"] = now_str()
        _state["clean_exit"] = clean
        tmp = _state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state), encoding="utf-8")
        os.replace(tmp, _state_path)
    except Exception:
        pass


def _heartbeat_loop() -> None:
    import time
    while True:
        time.sleep(_HEARTBEAT_SECONDS)
        _write_state(clean=False)


def _check_previous_session(state_path: Path) -> None:
    try:
        prev = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if prev.get("clean_exit"):
        return
    write(
        "PREVIOUS SESSION DID NOT EXIT CLEANLY "
        f"(pid {prev.get('pid')}, started {prev.get('started')}, last alive {prev.get('last_alive')}). "
        "Likely a native crash or a forced kill; compare with the Windows Event Log "
        "(Application, source 'Application Error') around that time."
    )


def _reveal_extra() -> dict:
    """LogRecord extra for the in-app log: the GUI turns the words «журнал ошибок» into a link that
    shows this file in Explorer (MainWindow._on_log_record / _on_log_link_clicked)."""
    return {"reveal_path": str(_log_path)} if _log_path else {}


def _format_exception(exc_type, exc, tb) -> str:
    return "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()


_MAX_CALLER_FRAMES = 25


def _caller_stack(tb) -> str:
    """The Python frames BELOW the traceback's outermost frame. A traceback only holds the frames between the
    raise and the place that caught it; when Qt calls Python (an event filter, a slot, a virtual method) that is
    just the one innermost frame — report said `File "gui_common.py", line 247, in eventFilter` and nothing else. The
    frames that were on the stack when Qt was entered (the handler, a nested modal exec(), main) are still reachable
    through f_back and say what the user was doing."""
    if tb is None:
        return ""
    outer = tb.tb_frame.f_back
    frames = traceback.extract_stack(outer) if outer is not None else []
    if not frames:
        return ""
    lines = traceback.format_list(frames[-_MAX_CALLER_FRAMES:])
    omitted = len(frames) - _MAX_CALLER_FRAMES
    head = f"Called from ({len(frames)} frame(s), outermost first" + (f", first {omitted} omitted" if omitted > 0 else "") + "):\n"
    return head + "".join(lines).rstrip()


def _qt_context() -> str:
    """What the user was looking at: the modal dialog, the active window and the focused widget. Only on the GUI
    thread (Qt widgets must not be touched from another one). Never raises."""
    try:
        if threading.current_thread() is not threading.main_thread():
            return ""
        from PyQt6.QtWidgets import QApplication
        if QApplication.instance() is None:
            return ""

        def name(widget) -> str:
            if widget is None:
                return "none"
            object_name = widget.objectName()
            return type(widget).__name__ + (f"({object_name})" if object_name else "")

        return (f"Qt: modal={name(QApplication.activeModalWidget())}, active window={name(QApplication.activeWindow())}, "
                f"focus={name(QApplication.focusWidget())}")
    except Exception:
        return ""


def _attribute_error_state(exc) -> str:
    """For AttributeError: what the object actually has. `'X' object has no attribute '_y'` alone cannot tell a typo
    from an instance that lost its attributes (the real `TextFindBar` report: all of them were gone)."""
    try:
        if not isinstance(exc, AttributeError) or getattr(exc, "obj", None) is None:
            return ""
        owner = exc.obj
        present = sorted(getattr(owner, "__dict__", {}))
        shown = ", ".join(present[:30]) + (f", ... ({len(present)} in total)" if len(present) > 30 else "")
        return f"Object: {type(owner).__name__} id={id(owner):#x}, missing '{getattr(exc, 'name', '?')}', attributes present: [{shown}]"
    except Exception:
        return ""


def _exception_report(exc_type, exc, tb) -> str:
    parts = [_format_exception(exc_type, exc, tb), _caller_stack(tb), _attribute_error_state(exc), _qt_context()]
    return "\n".join(part for part in parts if part)


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    write("UNCAUGHT EXCEPTION\n" + _exception_report(exc_type, exc, tb))
    try:
        sys.__excepthook__(exc_type, exc, tb)  # console, as before
    except Exception:
        pass
    try:
        # Reaches the in-app log panel (QtLogHandler) in plain words.
        _logger.error(tr("Произошла внутренняя ошибка (%s: %s). Подробности записаны в журнал ошибок."),
                      exc_type.__name__, exc, extra=_reveal_extra())
    except Exception:
        pass


def _thread_excepthook(args) -> None:
    write(
        f"UNCAUGHT EXCEPTION in thread {getattr(args.thread, 'name', '?')}\n"
        + "\n".join(part for part in (_format_exception(args.exc_type, args.exc_value, args.exc_traceback),
                                      _attribute_error_state(args.exc_value)) if part)
    )
    try:
        _logger.error(tr("Произошла внутренняя ошибка в фоновой задаче (%s: %s). Подробности записаны в журнал ошибок."),
                      args.exc_type.__name__, args.exc_value, extra=_reveal_extra())
    except Exception:
        pass


def _unraisable_hook(unraisable) -> None:
    write(
        f"UNRAISABLE EXCEPTION ({unraisable.err_msg or 'no message'}) in {unraisable.object!r}\n"
        + _format_exception(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback)
    )


def _install_qt_message_handler() -> None:
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    names = {
        QtMsgType.QtDebugMsg: "debug", QtMsgType.QtInfoMsg: "info", QtMsgType.QtWarningMsg: "warning",
        QtMsgType.QtCriticalMsg: "CRITICAL", QtMsgType.QtFatalMsg: "FATAL",
    }

    def handler(msg_type, context, message):
        global _qt_warning_count, _font_noise_count
        if msg_type == QtMsgType.QtWarningMsg and message.startswith(_HARMLESS_QT_WARNINGS):
            # Neither on the console nor in crash.log (they came by the dozen, e.g. 8 lines per script for every
            # text with an unusual script in it); one line records that they exist.
            _font_noise_count += 1
            if _font_noise_count == 1:
                write(f"Qt font warnings are not logged (harmless; first one: {message})")
            return
        try:
            sys.stderr.write(message + "\n")  # keep Qt's default console output
        except Exception:
            pass
        if msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            where = f" ({context.file}:{context.line})" if getattr(context, "file", None) else ""
            write(f"Qt {names[msg_type]}: {message}{where}")
        elif msg_type == QtMsgType.QtWarningMsg:
            _qt_warning_count += 1
            if _qt_warning_count <= _MAX_QT_WARNINGS:
                write(f"Qt warning: {message}")
            elif _qt_warning_count == _MAX_QT_WARNINGS + 1:
                write(f"Qt warning: further warnings suppressed (>{_MAX_QT_WARNINGS} this session)")

    qInstallMessageHandler(handler)


_clean_exit_marked = False


def mark_clean_exit() -> None:
    """Records "session end (clean exit)" and the clean flag in session.json. Idempotent. Registered with
    atexit, and called directly by main.fast_exit(), which ends the process WITHOUT running atexit."""
    global _clean_exit_marked
    if _clean_exit_marked or _log_file is None:
        return
    _clean_exit_marked = True
    write("session end (clean exit)")
    _write_state(clean=True)


def install(log_dir: Optional[Path] = None) -> Path:
    """Call once, first thing in the entry point. Returns the crash.log path."""
    global _log_file, _state_path, _state, _log_path
    log_dir = Path(log_dir) if log_dir else default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "crash.log"
    _log_path = log_path

    try:  # keep the file bounded: one rotated generation is enough
        if log_path.exists() and log_path.stat().st_size > _MAX_LOG_BYTES:
            os.replace(log_path, log_dir / "crash.log.1")
    except OSError:
        pass

    _log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    _state_path = log_dir / "session.json"

    _check_previous_session(_state_path)
    _state = {"pid": os.getpid(), "started": now_str()}
    _write_state(clean=False)

    try:
        import PyQt6.QtCore as qc
        qt_info = f"PyQt {qc.PYQT_VERSION_STR}, Qt {qc.QT_VERSION_STR}"
    except Exception:
        qt_info = "PyQt unavailable"
    write(f"===== session start pid={os.getpid()} python={sys.version.split()[0]} {qt_info} =====")

    faulthandler.enable(file=_log_file, all_threads=True)  # native crashes; file mtime = crash time
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    sys.unraisablehook = _unraisable_hook
    _install_qt_message_handler()

    atexit.register(mark_clean_exit)
    threading.Thread(target=_heartbeat_loop, name="crash-log-heartbeat", daemon=True).start()
    return log_path
