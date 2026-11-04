"""Opens a load's files a few at a time AHEAD of the pre-scan, so the scan does not wait for each one in turn.

Measured on Phonopolis (2,032 files, NVMe SSD, Windows Defender on; a fresh copy made with unbuffered copying,
i.e. files Windows has not seen yet - the state after installing or updating a game, and often after a reboot):
the FIRST open of a file costs ~7.6 ms (the system checking it), reading its head only ~0.9 ms. One by one the
opens took 15.5 s of the scan's 20.3 s; the file loading after the scan found everything checked and cached
(4.2 s, the same as a reload) - so "the scan is slower than the load" and "the second load is much faster" are
both this one cost. Sixteen opens at a time take 3.5 s.

So while the scan walks its list in order, a small pool opens each file and reads its first HEAD_BYTES (what
the scan needs: header, block info, metadata start). Files the next steps open are added too (the game's script
DLLs / GameAssembly.dll + metadata, which the script reader opens right after the load). Nothing here is
required: a failed open is ignored, the scan reads for itself whatever is not there yet, and stop() drops what
is still queued (a cancelled load, the scan done) without waiting for it.

When the files were opened recently (a reload, a second load of the same game) every open is fast and reading
ahead is just the same work twice (measured: the scan 0.6 s slower). So the first SAMPLE opens are timed, and
if their median is under WARM_OPEN_S the rest is skipped. Cold opens in parallel take ~20 ms each, cached ones
well under 1 ms.

PyQt-free; used by core.loader.EnvironmentLoader (GUI and CLI)."""

import logging
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

HEAD_BYTES = 256 * 1024
# 16 measured best on the 8-core test machine (8: slower; 32: slower again - the system's checks compete for
# the CPU with the scan itself).
MAX_THREADS = 16
SAMPLE = 32
WARM_OPEN_S = 0.002


class FilePrefetcher:
    """`with FilePrefetcher(paths):` - opens and reads the head of every path in the background, in order."""

    def __init__(self, paths: Iterable[str], threads: Optional[int] = None):
        self.paths: List[str] = list(paths)
        self.threads = threads or min(MAX_THREADS, 2 * (os.cpu_count() or 4))
        self._pool: Optional[ThreadPoolExecutor] = None
        self._lock = threading.Lock()
        self._open_times: List[float] = []
        self.skipped = False      # the files turned out to be cached: the rest was not opened ahead

    def _open_head(self, path: str) -> None:
        if self.skipped:
            return
        try:
            t = time.perf_counter()
            with open(path, "rb", buffering=0) as f:
                took = time.perf_counter() - t
                f.read(HEAD_BYTES)
        except OSError:
            return
        with self._lock:
            if len(self._open_times) < SAMPLE:
                self._open_times.append(took)
                if len(self._open_times) == SAMPLE and statistics.median(self._open_times) < WARM_OPEN_S:
                    self.skipped = True

    def start(self) -> "FilePrefetcher":
        if self.paths and self._pool is None:
            self._pool = ThreadPoolExecutor(self.threads, thread_name_prefix="file-prefetch")
            for path in self.paths:
                self._pool.submit(self._open_head, path)
        return self

    def stop(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> "FilePrefetcher":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def script_files(managed_dir: str = "", il2cpp_inputs=None) -> List[str]:
    """The files the script reader opens after the load: a Mono game's Managed/*.dll, or an IL2CPP game's binary
    and metadata (whose fingerprint picks the prepared DLLs)."""
    found: List[str] = []
    if il2cpp_inputs is not None:
        for p in (getattr(il2cpp_inputs, "binary", None), getattr(il2cpp_inputs, "metadata", None)):
            if p:
                found.append(str(p))
    if managed_dir and os.path.isdir(managed_dir):
        try:
            found.extend(os.path.join(managed_dir, n) for n in sorted(os.listdir(managed_dir))
                         if n.lower().endswith(".dll"))
        except OSError:
            pass
    return found
