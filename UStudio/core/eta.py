"""Speed/ETA estimation for a phased, byte-counted operation (write/compress/assemble,
export, ...) — previously duplicated as CabBrowserDialog._update_eta/_format_duration.
Pure math with no PyQt dependency, so it lives in core/ rather than gui_workers.py —
a future console-mode progress bar wants the exact same "12.4 MB/s, ~2 min remaining"
estimate CabBrowserDialog already shows."""

from core.i18n import tr
import time

from .file_utils import format_size


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 5:
        return tr("несколько секунд")
    if seconds < 60:
        return tr("{seconds} с", seconds=seconds)
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return tr("{minutes} мин", minutes=minutes + (1 if sec >= 30 else 0))
    hours, minutes = divmod(minutes, 60)
    return tr("{hours} ч {minutes} мин", hours=hours, minutes=minutes)


class EtaEstimator:
    """Returns a fragment like "12.4 MB/s, ~2 min remaining" (like Windows Explorer),
    or "" while there isn't enough data yet for an estimate. Speed is computed per
    CURRENT phase ("write"/"compress"/"assemble"/... — each phase typically has a
    different speed, e.g. compression is slower than plain copying), not across the
    whole operation at once, and is smoothed exponentially (EMA) so it doesn't jump
    around on every (already throttled elsewhere, e.g. by ProgressThrottle) update."""

    def __init__(self, alpha: float = 0.3, warmup_seconds: float = 0.5):
        self.alpha = alpha
        self.warmup_seconds = warmup_seconds
        self._phase = None
        self._start_time = 0.0
        self._last_time = 0.0
        self._last_bytes = 0
        self._speed_ema = None

    def reset(self) -> None:
        """Call before starting a new run — otherwise, if the previous run was
        cancelled mid-phase and a new one starts in that SAME phase name, the phase
        change wouldn't be detected and the estimate would be computed from stale,
        no-longer-relevant reference points and timestamps."""
        self._phase = None

    def update(self, phase: str, current: int, total: int) -> str:
        now = time.monotonic()

        if self._phase != phase or current < self._last_bytes:
            # new phase (or the counter went backwards — shouldn't happen, but just
            # in case) — the speed reference point needs to reset, otherwise the
            # estimate for the first seconds of the new phase would use the previous
            # phase's speed
            self._phase = phase
            self._start_time = now
            self._last_time = now
            self._last_bytes = current
            self._speed_ema = None
            return ""

        instant_elapsed = now - self._last_time
        instant_bytes = current - self._last_bytes
        if instant_elapsed > 0 and instant_bytes > 0:
            instant_speed = instant_bytes / instant_elapsed
            prev = self._speed_ema
            self._speed_ema = instant_speed if prev is None else self.alpha * instant_speed + (1 - self.alpha) * prev
        self._last_time = now
        self._last_bytes = current

        # too early to compute during the first ~0.5s of a phase — over such a small
        # window even a smoothed estimate is still too noisy (jumps between "3
        # seconds" and "2 hours")
        if now - self._start_time < self.warmup_seconds:
            return ""

        speed = self._speed_ema
        if not speed or speed <= 0:
            return ""

        remaining_seconds = max(0, total - current) / speed
        return tr("{speed}/с, осталось ~{time}", speed=format_size(int(speed)), time=format_duration(remaining_seconds))
