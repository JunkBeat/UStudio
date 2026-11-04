"""LoaderCallbacks implementations — the CLI's side of the same seam
loader_thread.py implements for the GUI (see core/loader.py's LoaderCallbacks
docstring: "A future console-mode front end would implement LoaderCallbacks by
printing to the terminal / reading stdin instead."). Two variants:

- NonInteractiveCallbacks: for one-shot invocations. Never blocks on stdin —
  a scripted/CI invocation has nobody to answer a prompt. A load that would
  have shown the "large data volume" dialog in the GUI FAILS LOUDLY here
  unless the caller already agreed to continue (--large continue),
  rather than silently guessing one. Silent guessing on a multi-million-object
  decision is exactly the kind of surprise a scripted invocation shouldn't get.
- InteractiveCallbacks: for `shell` mode, where a human is actually there —
  asks the same continue/cancel question the GUI's dialog does, as text.

Progress goes to stderr in both cases (see output.py's stdout/stderr
discipline note) so stdout stays clean for --format json piping."""

import os
import re
import shutil
import signal
import sys
from typing import Dict, List, Optional, Set, Tuple

from core.progress import ProgressThrottle
from core.loader import LargeLoadInfo, LoaderCallbacks  # noqa: F401 (documents the Protocol being implemented)

from cli.output import render_bar


class OperationAbortedError(Exception):
    """A one-shot load hit the large-data-volume question with no answer supplied
    to give it non-interactively."""


class _BaseCallbacks:
    """Shared progress/cancellation plumbing for both callback variants."""

    # Matches a "current/total"-shaped count core/loader.py sometimes bakes
    # straight into its status text (e.g. on_index_progress's own "...
    # 2/61804"), stripped back out before that text is used as the fixed-
    # width phase label below — see on_progress()'s own docstring note.
    _TRAILING_COUNT_RE = re.compile(r"\s*[\d,]+\s*/\s*[\d,]+\s*$")

    # Widest real phase label this app's core/loader.py actually sends, once
    # any trailing count is stripped ("Индексация объектов..." — 23 chars) —
    # a little headroom over that so the common cases never truncate.
    _LABEL_WIDTH = 24

    # A FIXED width for the "current/total" field, the same for every phase
    # of one run — not sized per-phase off that phase's own `total` — so the
    # bar starts at the identical column for every progress line the whole
    # boot sequence prints, not just while one phase's own total stays
    # constant. "999,999/999,999" (15 chars) comfortably covers every real
    # fixture's object/file count this project has ever measured (tens of
    # thousands to a few hundred thousand — see CLAUDE.md's own fixture
    # numbers); a genuinely huge count (the documented ~78M-object hard-case
    # bundle) is never truncated, it just overflows this width for that one
    # rare case rather than the column staying aligned for it too — numbers
    # themselves are never shortened, only the alignment can give a little.
    _COUNT_WIDTH = 15

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self._throttle = ProgressThrottle()
        self._cancelled = False
        try:
            signal.signal(signal.SIGINT, self._on_sigint)
        except ValueError:
            pass  # not the main thread — should_cancel() just never trips from here

    def _on_sigint(self, signum, frame):
        self._cancelled = True
        print("\n^C - cancelling...", file=sys.stderr)

    def should_cancel(self) -> bool:
        return self._cancelled

    def on_progress(self, level: int, current: int, total: int, name: str, status: str) -> None:
        if self.quiet or total <= 0:
            return
        if not self._throttle.should_report(current, total):
            return
        pct = int(current / total * 100) if total else 100
        bar = render_bar(current, total)

        # Real reported bug: the bar's own start column jumped around on
        # every line — "status" varies in length between phases
        # ("Сканирование..." vs "Индексация объектов...") AND, for index
        # progress specifically, even WITHIN one phase, since
        # core/loader.py bakes the running count straight INTO the status
        # string ("...2/61804" growing to "...61804/61804" — 7 vs 11
        # characters, so the bar visibly crept rightward as indexing
        # advanced). A well-aligned progress line (git/tqdm/docker pull)
        # keeps its label column and the bar's own position FIXED
        # regardless of which phase is running or how far along it is —
        # any embedded count belongs in its own fixed-width numeric field,
        # not folded into the label text, so it's stripped back out here
        # before the label is padded to a constant width.
        phase = self._TRAILING_COUNT_RE.sub("", status).rstrip()
        label = phase[: self._LABEL_WIDTH].ljust(self._LABEL_WIDTH)
        count = f"{current:,}/{total:,}".rjust(self._COUNT_WIDTH)
        head = f"{label} {count}  [{bar}] {pct:3d}%"

        # Real reported bug: this used to fall back to `label = name or status`
        # — for every call with no per-item name (a completion line, or
        # on_index_progress, which has none by construction), that printed
        # the whole status text a second time right after itself. A real
        # per-item detail (a file path during scan/load) is still shown,
        # just after the now-fixed head instead of folded into it.
        #
        # Real reported bug, the actual "garbled/overlapping" one: the whole
        # line used to be padded to a FIXED 130 columns regardless of the
        # real terminal width. In any narrower window that WRAPS onto more
        # than one physical row, and "\r" only returns to the start of the
        # row it's actually on — the LAST wrapped row gets overwritten each
        # redraw, but earlier wrapped rows' stale content never does, so
        # rapid redraws (this fires many times a second during indexing)
        # pile up as exactly the kind of overlapping fragments reported.
        # Width is now the real terminal width (queried against stderr,
        # since that's where progress actually goes — see this class's own
        # module docstring on why — not shutil's stdout-based default),
        # falling back to the old 130 only when stderr isn't a real console
        # (e.g. redirected to a file/pipe) and never exceeding it either.
        try:
            columns = os.get_terminal_size(sys.stderr.fileno()).columns
        except (OSError, ValueError, AttributeError):
            columns = shutil.get_terminal_size(fallback=(120, 24)).columns
        width = min(130, max(20, columns - 1))

        body = head
        if name:
            room = width - len(head) - 2  # 2 for the "  " separating head and label
            if room > 0:
                # Truncate from the FRONT, keeping the tail — a long path's
                # informative part (the actual filename) is at the end, and
                # the old flat [:130] slice on the whole line cut straight
                # through it instead ("...Truck-kun (Unity 6000.0." with the
                # filename itself never shown at all).
                path_label = name if len(name) <= room else "…" + name[-(room - 1):]
                body = f"{head}  {path_label}"

        print("\r" + body[:width].ljust(width), end="", file=sys.stderr, flush=True)
        if current >= total - 1:
            print(file=sys.stderr)

    def on_index_progress(self, current: int, total: int, status: str) -> None:
        self.on_progress(0, current, total, "", status)


class NonInteractiveCallbacks(_BaseCallbacks):
    def __init__(self, on_large_file: Optional[str] = None, quiet: bool = False):
        super().__init__(quiet=quiet)
        self.on_large_file = on_large_file

    def ask_about_large_load(self, info: LargeLoadInfo) -> bool:
        if self.on_large_file is None:
            amount = (f"{info.object_count:,} objects" if info.object_count
                      else f"{info.legacy_size_bytes / 1024 ** 2:,.0f} MB of data")
            raise OperationAbortedError(
                f"{amount} to load - pass --large continue to proceed "
                f"non-interactively (or use `shell` mode to be prompted instead)."
            )
        return True


class InteractiveCallbacks(_BaseCallbacks):
    """Used by `shell` mode — a human is at the terminal, so this actually
    prompts instead of requiring every policy up front."""

    def ask_about_large_load(self, info: LargeLoadInfo) -> bool:
        amount = (f"{info.object_count:,} objects" if info.object_count
                  else f"{info.legacy_size_bytes / 1024 ** 2:,.0f} MB of data")
        if info.load_all:
            note = "all of them will be loaded"
        else:
            note = "fewer will actually be loaded (only the indexed types)"
        print(f"\n{amount} in the selected files - {note}, but it may take a lot of memory and time.",
              file=sys.stderr)
        while True:
            raw = input("  Continue? [y/n] > ").strip().lower()
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False
            print("  please answer y or n", file=sys.stderr)


class CliSession:
    """Holds the state a `shell` invocation keeps alive across many commands —
    exactly the "load once, run many commands" value the REPL exists for. A
    one-shot invocation builds one of these, uses it for a single command, and
    discards it."""

    def __init__(self):
        self.env = None
        self.rows: List[Dict] = []
        self.unity_version: str = ""
        self.platform_name: str = ""
        self.folder_label: str = ""
        # Needed by save_manager.compute_base_dir() for a custom-path save's
        # "preserve folder structure" behavior — set by cmd_load(), mirroring
        # what LoadOptions itself was given for that same load.
        self.load_mode = None
        self.selected_dir: str = ""
        self.selected_files: List[str] = []
        # A separately-opened single bundle for the `cab` verb (core.cab_archive.
        # CabArchive) — deliberately independent of env/rows above, matching the
        # GUI's own CabBrowserDialog being a separate Environment from the main
        # table. Flat, not nested: `cab open` sets this, `cab list/export/
        # rebuild` all act on it directly — no separate nested sub-prompt (the
        # earlier schematic sketch showed one; this is a simpler, lower-risk
        # implementation of the same underlying capability).
        self.cab = None
        self.cab_path: str = ""

    def clear(self) -> None:
        """After a successful overwrite-in-place save, every root_file's own
        OS handle was deliberately closed (see save_manager.prepare_overwrite's
        docstring) — the loaded Environment is permanently unusable from that
        point on, exactly like the GUI's own post-overwrite reload. A `shell`
        session must not let a later command touch it; the user has to
        `load` again to keep working."""
        self.env = None
        self.rows = []
        self.unity_version = ""
        self.platform_name = ""

    @property
    def loaded(self) -> bool:
        return self.env is not None
