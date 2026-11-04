"""Configures the app's logging — the single source of truth for both the GUI log
panel (via gui_logging.QtLogHandler, attached by main.py) and a nicely formatted,
colored terminal via `rich` (attached here). core/ code itself never touches a
handler directly, only ever `logging.getLogger("ustudio.core...")` calls — this
module (and gui_logging.py for the Qt side) is where those calls actually go
somewhere. A future console-mode entry point calls configure_console_logging() the
same way the GUI does and gets the same formatted output with no GUI involved at all."""

import logging
import sys

ROOT_LOGGER_NAME = "ustudio"


def get_logger(name: str) -> logging.Logger:
    """Convenience so callers don't need to remember the "ustudio." prefix
    convention — get_logger("core.loader") -> logging.getLogger("ustudio.core.loader")."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}" if name else ROOT_LOGGER_NAME)


def configure_console_logging(level: int = logging.INFO, stream=None) -> bool:
    """Attaches a rich-formatted console handler to the app's root ("ustudio")
    logger — colored level tags, dimmed timestamps, the same general style as
    GitHub Actions/modern CLI tool output. Safe to call from a GUI build with no
    attached console (e.g. a PyInstaller --windowed build, where sys.stdout can be
    None): in that case this is a no-op and returns False, since rich has nothing
    to write to. Returns True if the handler was actually attached.

    stream=None keeps the original default (rich's own Console(), which writes
    to stdout) — unchanged for the GUI's own call site. The CLI passes
    sys.stderr explicitly: its stdout must stay clean machine-readable output
    (see cli/output.py's stdout/stderr discipline note) with every log line —
    including core/'s own Russian-language ones — going to stderr instead."""
    if sys.stdout is None:
        return False

    from rich.console import Console
    from rich.logging import RichHandler

    # Some Windows consoles' active codepage (e.g. cp1251) can't encode every
    # character a log message might contain — not just exotic input, but symbols
    # this app's own messages use (e.g. an arrow character in the duplicate-files
    # summary). Without this, rich's Windows legacy-console writer raises
    # UnicodeEncodeError from inside emit(), which logging catches and reports as a
    # noisy "--- Logging error ---" traceback on every single such call — the
    # opposite of "neater console output". "replace" swaps just the offending
    # character for a placeholder instead, so one stray glyph doesn't take a whole
    # message (and every message after it, since this repeats on every emit) down
    # with it. Silently skipped if the stream doesn't support reconfigure() (e.g.
    # stdout has been replaced with a non-TextIOWrapper object).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    if logger.level == logging.NOTSET or logger.level > level:
        logger.setLevel(level)

    handler = RichHandler(
        console=Console(file=stream) if stream is not None else None,
        show_time=True,
        # Real reported complaint ("boot logging looks chaotic"): RichHandler's
        # own default blanks out the timestamp column for any log line that
        # lands in the same second as the previous one — reasonable for a
        # long-running log tail, but during a load nearly every INFO line
        # fires within the same second, so most of them showed no time at all
        # while a few did, an inconsistent look rather than a genuinely
        # cluttered one. Every line now always shows its timestamp.
        omit_repeated_times=False,
        show_path=False,
        markup=False,
        rich_tracebacks=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s", datefmt="%H:%M:%S"))
    # The logger itself may later be lowered to DEBUG (the GUI does, so its log window can show
    # debug lines on request); the console keeps the verbosity it was configured with.
    handler.setLevel(level)
    logger.addHandler(handler)
    return True
