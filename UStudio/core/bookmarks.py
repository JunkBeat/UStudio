"""Bookmarks («Закладки»): objects the user marked to come back to — kept across sessions (no Qt).

An object is remembered by (the physical file it lives in, its file's name, PathID): the physical file is the path
the load opened (a loose .assets, or the bundle a CAB is inside — env.source_path_of), normalised; the name tells
CABs of one bundle apart. So a bookmark is found again by any later load that includes that file — the whole game
or just that bundle — and is lost if the game folder moves (it is per-path, like the backups).

`BookmarkStore` holds them all; `set_env(env)` narrows to the files of the loaded game; `matcher()` is a frozen,
thread-safe predicate over table rows (the filter proxy's background pass and the table's star use it). Persistence
is injected (`load`/`save` callables over a JSON string): the GUI keeps it in the app settings."""
import json
import os
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

Key = Tuple[str, str, int]          # (normalised physical path, file name, PathID)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class BookmarkStore:
    def __init__(self, load: Optional[Callable[[], str]] = None, save: Optional[Callable[[str], None]] = None):
        self._save = save
        self._data: Dict[str, Set[Tuple[str, int]]] = {}
        self._env = None
        self._loaded_paths: Set[str] = set()
        self._matcher = None
        if load is not None:
            try:
                raw = json.loads(load() or "{}")
                for path, entries in (raw or {}).items():
                    self._data[path] = {(str(s), int(p)) for s, p in entries}
            except (ValueError, TypeError):
                self._data = {}       # an unreadable value: start empty rather than fail the window

    # --- the loaded game ---

    def set_env(self, env) -> None:
        self._env = env
        files = getattr(env, "files", None) or {}
        self._loaded_paths = {_norm(k) for k in files if isinstance(k, str) and os.path.isabs(k)}
        self._matcher = None

    def key_of(self, item) -> Optional[Key]:
        """The bookmark key of a table row, or None (its file was not opened from disk — nothing to come back to)."""
        env = self._env
        obj = item.get("obj_ref")
        assets_file = getattr(obj, "assets_file", None)
        if env is None or assets_file is None:
            return None
        path = env.source_path_of(assets_file)
        if not path or not os.path.isabs(path):
            return None
        return _norm(path), item.get("source"), int(item.get("path_id"))

    def loaded_keys(self) -> Set[Key]:
        return {(p, s, i) for p in self._loaded_paths & self._data.keys() for s, i in self._data[p]}

    def matcher(self) -> Callable[[dict], bool]:
        """A predicate `row -> bookmarked?` over a SNAPSHOT of the bookmarks (rebuilt after a change): a cheap
        (name, PathID) test first, the physical path only for those few rows (cached per file)."""
        if self._matcher is not None:
            return self._matcher
        env, keys = self._env, frozenset(self.loaded_keys())
        quick = frozenset((s, i) for _p, s, i in keys)
        paths: Dict[int, Optional[str]] = {}

        def match(item) -> bool:
            if (item.get("source"), item.get("path_id")) not in quick:
                return False
            assets_file = getattr(item.get("obj_ref"), "assets_file", None)
            fid = id(assets_file)
            if fid not in paths:
                path = env.source_path_of(assets_file) if env is not None and assets_file is not None else None
                paths[fid] = _norm(path) if path and os.path.isabs(path) else None
            return (paths[fid], item.get("source"), item.get("path_id")) in keys

        self._matcher = match
        return match

    # --- changes ---

    def is_bookmarked(self, item) -> bool:
        return self.matcher()(item)

    def add(self, items: Iterable[dict]) -> int:
        return self._change(items, add=True)

    def remove(self, items: Iterable[dict]) -> int:
        return self._change(items, add=False)

    def _change(self, items, add: bool) -> int:
        changed = 0
        for item in items:
            key = self.key_of(item)
            if key is None:
                continue
            path, source, path_id = key
            entries = self._data.setdefault(path, set())
            if add and (source, path_id) not in entries:
                entries.add((source, path_id))
                changed += 1
            elif not add and (source, path_id) in entries:
                entries.discard((source, path_id))
                changed += 1
            if not entries:
                del self._data[path]
        if changed:
            self._matcher = None
            self._persist()
        return changed

    def loaded_count(self) -> int:
        return len(self.loaded_keys())

    def _persist(self) -> None:
        if self._save is not None:
            self._save(json.dumps({p: sorted([s, i] for s, i in e) for p, e in self._data.items()},
                                  ensure_ascii=False))
