"""Keep Python's full garbage collections off the loaded game (no Qt; the CLI never freezes).

A loaded game is millions of long-lived Python objects (Phonopolis: 1.34 M tracked by the collector, ~3 GB). Every
automatic FULL collection walks all of them — ~300 ms during which no thread runs, the GUI included — and finds
nothing to free (measured: "gen2: 297 ms, collected 0" right after a load, triggered by the «Используется в»
index's growth; the old builds had the same pause from the name warm-up in one run of two). `gc.freeze()` right
after a load moves them out of the collector's view (O(1); they are still freed by reference counting); after it no
pause over 100 ms was left (Phonopolis, 0 of 4 runs; 2-4 per run before).

The catch: a frozen reference CYCLE is never collected. Two kinds of code depend on collecting cycles:
- tearing a game down (a new load, an overwrite save, «Вернуть оригиналы»): `unfreeze()` comes first, in
  `MainWindow._clear_loaded_session`, before their own `gc.collect()`;
- the forced collections that release a file mapping held by a cycle while a game stays loaded (resource files
  written during an import, lock retries of a save, the version writer): they call `collect_everything()`.
"""

import gc


def freeze_loaded() -> None:
    """After a load: everything alive now is the game — keep full collections off it."""
    gc.freeze()


def unfreeze() -> None:
    """Before the game is torn down: its cycles must be collectable again."""
    gc.unfreeze()


def collect_everything() -> int:
    """gc.collect() that also reaches frozen objects (a cycle holding a file mapping may be one of them); the
    freeze is restored afterwards. A full pass over the game: only where a file must be released."""
    frozen = gc.get_freeze_count()
    if frozen:
        gc.unfreeze()
    try:
        return gc.collect()
    finally:
        if frozen:
            gc.freeze()
