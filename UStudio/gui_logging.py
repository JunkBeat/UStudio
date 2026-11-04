"""Bridges Python's stdlib `logging` (used throughout core/, and now by the GUI
layer too — see MainWindow.log()) into the GUI's log panel.

A logging.Handler's emit() can be invoked from ANY thread that calls
logging.getLogger(...).info()/.warning()/etc — including core/'s background-thread
code (DataLoaderThread/CabBrowserDialog's worker both run core/ calls off the GUI
thread) — so QtLogHandler itself must never touch a Qt widget directly (widgets
aren't thread-safe). It only emits a Qt signal; Qt's signal/slot machinery takes
care of safely delivering that to whichever thread the connected slot's QObject
actually lives on (the GUI thread, since QtLogHandler and MainWindow are both
constructed there) via an automatic queued connection."""

import logging

from PyQt6.QtCore import QObject, pyqtSignal


class QtLogHandler(logging.Handler, QObject):
    """A logging.Handler that's ALSO a QObject so it can own a real Qt signal —
    needs to inherit both: logging.Handler so the logging machinery calls emit() on
    every record, QObject so record_logged can be connected to a slot with Qt's
    normal cross-thread-safe queued-connection delivery."""

    record_logged = pyqtSignal(logging.LogRecord)

    def __init__(self, level: int = logging.NOTSET):
        logging.Handler.__init__(self, level)
        QObject.__init__(self)
        # DEBUG records are dropped here (before crossing to the GUI thread) unless this is on —
        # the "Показывать отладочные сообщения" setting.
        self.show_debug = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO and not self.show_debug:
            return
        self.record_logged.emit(record)


def detach_qt_log_handler(handler: "QtLogHandler", logger: logging.Logger) -> None:
    """Call this (from MainWindow.closeEvent) before `handler`'s underlying Qt
    C++ object can go away — otherwise logging.shutdown() (registered via Python's
    own atexit, so it runs long after this app's windows/widgets are gone) crashes
    with "Exception ignored in atexit callback ...: RuntimeError: wrapped C/C++
    object of type QtLogHandler has been deleted".

    Two independent things keep a handler reachable long after this app is done
    with it, and both have to be undone:

    1. logger.handlers (a plain Python list on the *logger*, which is itself a
       long-lived singleton in logging.Logger.manager — unrelated to this app's own
       object lifetimes) holds a strong reference to `handler`, keeping the Python
       wrapper alive well past MainWindow's own destruction. removeHandler() drops
       that.
    2. Independently of (1), every Handler ever constructed is also weakly
       referenced from logging's own module-level `_handlerList` (added in
       Handler.__init__ via `_addHandlerRef`) — this is what `logging.shutdown()`
       actually iterates. Handler.close() does NOT remove it from there (verified
       against the stdlib source: close() only ever touches the separate *named*-
       handler table, `_handlers`) — a weakref is only dropped from `_handlerList`
       when the referent is actually garbage-collected, which doesn't happen here
       since (1) already keeps it alive, and even after fixing (1), Qt/PyQt can
       still delete the underlying C++ object out from under a still-alive Python
       wrapper (confirmed via a direct reproduction: sip.delete() on a handler
       whose weakref was still resolvable made logging.shutdown() crash exactly as
       reported, and calling only Handler.close() first did NOT prevent it — only
       removing the entry from _handlerList did). So that entry has to be pulled
       out explicitly, the same thing CPython's own `_removeHandlerRef` does
       automatically for a normally-collected handler.
    """
    logger.removeHandler(handler)
    with logging._lock:
        logging._handlerList[:] = [wr for wr in logging._handlerList if wr() is not handler]
    handler.close()
