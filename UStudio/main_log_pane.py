"""The main window's log pane: log(), turning logging records into coloured lines, and the clickable folder links.

Kept out of main.py as a mixin (MainWindow inherits it), like main_save_flow.py. Behaviour is unchanged; this is a
mechanical move (every method body is byte-identical to its old place in main.py)."""

from core.i18n import tr
import logging
import os
from pathlib import Path
from html import escape
from typing import Optional

from PyQt6.QtCore import QUrl

from config import LogLevel


# LogLevel (INFO/WARNING/ERROR — the app's own friendly enum, used at every self.log()
# call site) <-> Python's stdlib logging levels, now the single actual logging
# pathway (see MainWindow.log()/on_log_record() below and gui_logging.QtLogHandler).
_LOGLEVEL_TO_PY = {
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
    LogLevel.DEBUG: logging.DEBUG,
}
_PY_TO_LOGLEVEL = {
    logging.DEBUG: LogLevel.DEBUG,
    logging.INFO: LogLevel.INFO,
    logging.WARNING: LogLevel.WARNING,
    logging.ERROR: LogLevel.ERROR,
    logging.CRITICAL: LogLevel.ERROR,
}


def _py_level_to_loglevel(levelno: int) -> LogLevel:
    if levelno in _PY_TO_LOGLEVEL:
        return _PY_TO_LOGLEVEL[levelno]
    # anything in between the named levels (e.g. a custom level number) — round down
    # to the nearest named tier below it, matching how logging itself treats levels
    for threshold in (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO):
        if levelno >= threshold:
            return _PY_TO_LOGLEVEL[threshold]
    return LogLevel.DEBUG


class LogPaneMixin:
    def log(self, message, level=LogLevel.INFO):
        """Logs a message from GUI-thread code in this file. Goes through the same
        logging.getLogger("ustudio...") pathway as everything in core/ (see
        gui_logging.QtLogHandler) — self.log() is just a thin, LogLevel-typed
        convenience wrapper over it for the ~40 call sites already using this name
        throughout this file, not a separate logging mechanism. The actual widget
        rendering happens in _on_log_record(), triggered by the handler regardless of
        whether the record came from here or from core/ (possibly off-thread)."""
        try:
            if not isinstance(level, LogLevel):
                level = LogLevel(level)
        except (ValueError, TypeError):
            level = LogLevel.INFO
        logging.getLogger("ustudio.gui").log(_LOGLEVEL_TO_PY[level], str(message))

    def _log_line_html(self, body_html: str, level: LogLevel) -> str:
        """Shared by _on_log_record() and log_with_folder_link() — wraps
        body_html (already escaped, and already carrying any link markup the
        caller built, e.g. log_with_folder_link()'s linked path) in this
        level's color span + prefix. Colors follow self._theme_colors, updated
        by _apply_theme_name(); already-appended log lines keep whatever color they
        were written with (HTML baked into the widget's content, not
        re-rendered on toggle) — only new lines pick up a switch. See theme.py's
        module docstring for why hardcoded dark-theme-only colors were wrong
        here in the first place."""
        body_colors = {
            LogLevel.INFO: self._theme_colors.log_info,
            LogLevel.WARNING: self._theme_colors.log_warning,
            LogLevel.ERROR: self._theme_colors.log_error,
            LogLevel.DEBUG: self._theme_colors.log_info,
        }
        # Real reported request: the GUI log had no text tag at all, unlike
        # console mode's [INFO]/[WARNING]/[ERROR] (rich.RichHandler's own
        # default level column, see core/logging_setup.py). The glyph
        # prefixes below already existed and stay.
        #
        # Real follow-up report: INFO's tag looked "uncolored" — confirmed
        # directly against rich's actual rendering (RichHandler's default
        # level styles: logging.level.info -> blue), not assumed: console
        # mode colors ONLY the level word itself blue, the message text after
        # it stays the terminal's plain default color — this app's own
        # log_info (#d4d4d4, near-white) was never meant to BE that blue, it
        # was always just "info messages don't need to scream" for the body
        # text. The tag now gets its own color, matching console mode: INFO's
        # tag uses the app's own accent/highlight blue (theme-consistent
        # instead of a new hardcoded hex); WARNING/ERROR's tag stays the same
        # color as their body always was (nothing to fix there — unlike INFO,
        # nobody reported those blending into the background).
        tag_colors = {
            LogLevel.INFO: self._theme_colors.highlight,
            LogLevel.WARNING: self._theme_colors.log_warning,
            LogLevel.ERROR: self._theme_colors.log_error,
            LogLevel.DEBUG: self._theme_colors.disabled_text,
        }
        tags = {
            LogLevel.INFO: "[INFO] ",
            LogLevel.WARNING: "[WARNING] ",
            LogLevel.ERROR: "[ERROR] ",
            LogLevel.DEBUG: "[DEBUG] ",
        }
        prefixes = {
            LogLevel.INFO: "",
            LogLevel.WARNING: "⚠ ",
            LogLevel.ERROR: "❌ ",
            LogLevel.DEBUG: "",
        }
        return (
            f'<span style="color:{tag_colors[level]};">{tags[level]}</span>'
            f'<span style="color:{body_colors[level]};">{prefixes[level]}{body_html}</span>'
        )

    def _on_log_record(self, record: logging.LogRecord):
        """Slot for QtLogHandler.record_logged — renders ANY log record (from this
        file's own log() calls, or from core/'s loader/CAB-archive logic, possibly
        logged from a background thread) into the log panel. Qt's queued connection
        already guarantees this runs on the GUI thread regardless of which thread
        the record originated on."""
        level = _py_level_to_loglevel(record.levelno)
        body = escape(record.getMessage()).replace("\n", "<br>")
        reveal = getattr(record, "reveal_path", None)
        if reveal:
            # A file the message talks about (e.g. the error log): its words become a link that
            # shows the file in Explorer — see _on_log_link_clicked().
            url = QUrl.fromLocalFile(str(reveal))
            url.setFragment("reveal")
            link_style = f"color:{self._theme_colors.highlight}; text-decoration: underline;"
            anchor = f'<a href="{url.toString()}" style="{link_style}">'
            marker = tr("журнал ошибок")
            body = (body.replace(marker, f"{anchor}{marker}</a>", 1) if marker in body
                    else f'{body} — {anchor}📂 ' + tr("Показать файл") + '</a>')
        folder = getattr(record, "folder_path", None)
        if folder:
            # a folder named in a message from core/ (e.g. the prepared IL2CPP files): same link as log_with_folder_link
            body = self._link_folder_in(body, str(folder))
        self.log_area.append(self._log_line_html(body, level))

    def _link_folder_in(self, escaped_message: str, folder_str: str) -> str:
        """The folder path as it appears in the (already escaped) message becomes a link that opens it; if the path
        is not in the text, a «📂 Открыть папку» link is appended instead."""
        folder_url = QUrl.fromLocalFile(folder_str).toString()
        link_style = f"color:{self._theme_colors.highlight}; text-decoration: underline;"
        escaped_path = escape(folder_str)
        if escaped_path and escaped_path in escaped_message:
            return escaped_message.replace(
                escaped_path, f'<a href="{folder_url}" style="{link_style}">{escaped_path}</a>', 1)
        return escaped_message + f' — <a href="{folder_url}" style="{link_style}">📂 ' + tr("Открыть папку") + '</a>'

    def log_with_folder_link(self, message: str, folder: Optional[Path], level=LogLevel.INFO) -> None:
        """Same rendering as log()/_on_log_record(), except the folder PATH AS
        IT APPEARS in message becomes a clickable link in place — not a
        separate "open folder" link tacked on after. Real request: message
        already reads "...дампов в C:\\...\\dumps_MB_Image"; that path itself
        should be the link, not extra text appended past it. folder=None
        (nothing to link) falls back to plain log().

        Every export-task followup (object_actions.py's _on_task_finished)
        builds its own message with the SAME folder value embedded via an
        f-string (e.g. _format_bulk_result's f"...в {out_dir}"), so str(folder)
        reliably appears in message verbatim — replaced (after both sides are
        escaped, so the match is apples-to-apples) with an anchor wrapping
        that exact substring. If it genuinely doesn't appear (a caller
        formatted the path differently in its own message text), falls back
        to appending a "📂 Открыть папку" link instead of silently losing it.

        Bypasses the logging.Logger/QtLogHandler pipeline log() normally goes
        through: the link HTML must stay outside escape()'s reach, and this is
        always called directly from the GUI thread (object_actions.py's
        task-queue callbacks), so there's no cross-thread delivery need to
        justify going through the full record_logged round-trip just for this
        one enhanced case."""
        if folder is None:
            self.log(message, level)
            return
        try:
            if not isinstance(level, LogLevel):
                level = LogLevel(level)
        except (ValueError, TypeError):
            level = LogLevel.INFO

        body = self._link_folder_in(escape(message).replace("\n", "<br>"), str(folder))
        self.log_area.append(self._log_line_html(body, level))

    def _on_log_link_clicked(self, url: QUrl) -> None:
        """anchorClicked handler for log_area — currently only log_with_folder_link()
        ever puts a link in the log, always a local folder path, so this doesn't
        need to distinguish link types yet. os.startfile() (not
        QDesktopServices.openUrl) to match _maybe_open_folder()'s own existing
        convention for "open this folder in Explorer" elsewhere in the app."""
        if not url.isLocalFile():
            return
        path = url.toLocalFile()
        if url.fragment() == "reveal":
            # a FILE: show it selected in Explorer (not open it in an editor)
            self.object_actions.reveal_path_in_explorer(path)
            return
        try:
            os.startfile(path)
        except OSError as e:
            self.log(tr("Не удалось открыть папку {folder}: {error}", folder=path, error=e), LogLevel.WARNING)
