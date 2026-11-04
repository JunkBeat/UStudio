"""Fills the SDF view's per-font "how many characters / does it cover ___" text in the background:
every font asset has to be parsed to know, which is too slow to do while building the tree."""
import time

from PyQt6.QtCore import QThread, pyqtSignal

from core.object_metadata import coverage_part_text
from core.progress import Pacer
from core.sdf_resolver import sdf_font_coverage


def coverage_text(coverage) -> str:
    """A short line, e.g. "275 chars" or "275 chars   ·   Cyrillic support" — the label is
    whatever Settings currently has configured (core.object_metadata.set_char_coverage), not
    fixed to Cyrillic; shown only when the font actually covers it, same as before. The wide
    "   ·   " separator matches the one sdf_group_model._group_data uses between the group's
    name and this text, so both joins in the line read the same way (real reported request —
    a narrower " · " here looked inconsistent next to that one)."""
    if coverage is None:
        return ""
    count, covered = coverage
    return f"{count} chars" + (f"   ·   {coverage_part_text()}" if covered else "")


class SDFCoverageWorker(QThread):
    result = pyqtSignal(str, str)  # group id, text

    def __init__(self, groups, parent=None, should_pause=None):
        super().__init__(parent)
        self._groups = [(g.group_id, g.font["obj_ref"]) for g in groups]
        self._should_pause = should_pause

    def _busy(self) -> bool:
        try:
            return bool(self._should_pause and self._should_pause())
        except Exception:  # a broken hook must never kill the pass
            return False

    def run(self):
        # Parsing a font asset is pure Python and holds the GIL for its whole duration, so a long
        # run of them would make the GUI sluggish: yield the GIL between fonts, and parse none while the
        # user is busy (MainWindow._background_busy — the same signal the other background passes wait on).
        self.setPriority(QThread.Priority.LowPriority)
        for group_id, obj in self._groups:
            while self._busy() and not self.isInterruptionRequested():
                time.sleep(Pacer.BUSY_SLEEP_S)
            if self.isInterruptionRequested():
                return
            self.result.emit(group_id, coverage_text(sdf_font_coverage(obj)))
            time.sleep(0.03)
