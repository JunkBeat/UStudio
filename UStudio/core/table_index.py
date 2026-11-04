"""Columnar index for the main object table — the Qt-free half of the NumPy filter proxy.

Why this exists: with ~2M rows the per-row Python call QSortFilterProxyModel makes into
filterAcceptsRow() is the whole cost of filling the table, applying a filter or re-applying the
sort (measured: 2.0 s / 3.3 s / 2.8 s on 1.95M rows), and nothing but removing the per-row call
helps. The two columns a filter can restrict statically — type and source — are small sets of
strings, so they are kept as integer category codes (one small int per row) and "which rows pass"
becomes a vectorised mask. Anything that has to look at the live row (script selectors, the
"modified" flag, free text) is still decided by the same Python predicate as before, but only for the
rows the mask already let through.

Nothing here knows about Qt; the proxy (object_table.IndexFilterProxyModel) is a thin shell around
these functions, and tests/test_table_index.py checks them against a plain Python filter without a
QApplication.

Arrays are treated as IMMUTABLE once built: every "change" (permute, extend, update) returns a new
ColumnStore, so a background sort can hold a reference to a store while the GUI thread keeps using
the current one without any locking.
"""

from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

# Row keys the store derives codes from. Rows are plain dicts (config.RowItem); a missing key is
# treated as None, exactly like the legacy predicate's item.get("type").
TYPE_KEY = "type"
SOURCE_KEY = "source"


def _codes(values: Iterable, count: int):
    """(int32 array of category codes, {value: code}) — codes in first-seen order."""
    cats: Dict = {}
    codes = np.fromiter((cats.setdefault(v, len(cats)) for v in values), dtype=np.int32, count=count)
    return codes, cats


class ColumnStore:
    """Category codes of the type and source columns for a given row list, built lazily.

    A store describes ONE specific ordering of ONE specific row list: the codes line up with the
    rows by position. It is therefore replaced (never edited) whenever the list changes: see
    permuted() for a re-sort, extended() for appended rows, updated() for rows edited in place.
    """

    __slots__ = ("count", "type_codes", "type_cats", "source_codes", "source_cats", "__weakref__")

    def __init__(self, count: int = 0, type_codes=None, type_cats=None, source_codes=None, source_cats=None):
        self.count = count
        self.type_codes = type_codes
        self.type_cats = type_cats if type_cats is not None else {}
        self.source_codes = source_codes
        self.source_cats = source_cats if source_cats is not None else {}

    @classmethod
    def build(cls, rows: Sequence[dict]) -> "ColumnStore":
        n = len(rows)
        type_codes, type_cats = _codes((r.get(TYPE_KEY) for r in rows), n)
        source_codes, source_cats = _codes((r.get(SOURCE_KEY) for r in rows), n)
        return cls(n, type_codes, type_cats, source_codes, source_cats)

    @property
    def built(self) -> bool:
        return self.type_codes is not None

    def matches(self, rows: Sequence[dict]) -> bool:
        """Cheap sanity check used before trusting the store: same row count. (Content can only
        diverge through a code path that forgot to replace the store — the proxy's own consistency
        test in the test-suite is what guards that, this only stops an obviously stale store.)"""
        return self.built and self.count == len(rows)

    def permuted(self, order) -> "ColumnStore":
        """Store for the rows after `new_rows = [rows[i] for i in order]`."""
        order = np.asarray(order, dtype=np.int64)
        if not self.built:
            return ColumnStore()
        return ColumnStore(
            len(order), self.type_codes[order], self.type_cats, self.source_codes[order], self.source_cats,
        )

    def extended(self, new_rows: Sequence[dict]) -> "ColumnStore":
        """Store after `rows.extend(new_rows)` (categories may grow; existing codes stay valid)."""
        if not self.built:
            return ColumnStore()
        k = len(new_rows)
        type_cats = dict(self.type_cats)
        source_cats = dict(self.source_cats)
        new_t = np.fromiter((type_cats.setdefault(r.get(TYPE_KEY), len(type_cats)) for r in new_rows),
                            dtype=np.int32, count=k)
        new_s = np.fromiter((source_cats.setdefault(r.get(SOURCE_KEY), len(source_cats)) for r in new_rows),
                            dtype=np.int32, count=k)
        return ColumnStore(
            self.count + k, np.concatenate((self.type_codes, new_t)), type_cats,
            np.concatenate((self.source_codes, new_s)), source_cats,
        )

    def updated(self, rows: Sequence[dict], first: int, last: int) -> "ColumnStore":
        """Store after rows[first..last] were edited in place (their type/source may have changed).
        Returns self when nothing in the range actually changed, so the common dataChanged for a
        size/name edit costs a small scan and no copy."""
        if not self.built or first > last or last >= self.count:
            return self
        type_cats = self.type_cats
        source_cats = self.source_cats
        inv_t = {c: v for v, c in type_cats.items()}
        inv_s = {c: v for v, c in source_cats.items()}
        changed = False
        for i in range(first, last + 1):
            r = rows[i]
            if inv_t.get(int(self.type_codes[i])) != r.get(TYPE_KEY) or inv_s.get(int(self.source_codes[i])) != r.get(SOURCE_KEY):
                changed = True
                break
        if not changed:
            return self
        type_cats = dict(type_cats)
        source_cats = dict(source_cats)
        tc = self.type_codes.copy()
        sc = self.source_codes.copy()
        for i in range(first, last + 1):
            r = rows[i]
            tc[i] = type_cats.setdefault(r.get(TYPE_KEY), len(type_cats))
            sc[i] = source_cats.setdefault(r.get(SOURCE_KEY), len(source_cats))
        return ColumnStore(self.count, tc, type_cats, sc, source_cats)


def _member_codes(allowed, cats: Dict) -> np.ndarray:
    """Codes of the categories named in `allowed` (names not present in the data are ignored —
    exactly what `item.get(key) not in allowed` does for a value that never occurs)."""
    return np.fromiter((cats[v] for v in allowed if v in cats), dtype=np.int32)


def accepted_rows(
    store: Optional[ColumnStore],
    rows: Sequence[dict],
    allowed_types=None,
    allowed_sources=None,
    residual: Optional[Callable[[dict], bool]] = None,
    first: int = 0,
    last: Optional[int] = None,
) -> np.ndarray:
    """Ascending int64 array of the row numbers in [first, last] that pass the filter.

    allowed_types / allowed_sources: None = unrestricted, otherwise any container supporting
    iteration (a set, normally). residual: the full Python predicate for everything the codes cannot
    decide (script selectors, modified, free text); applied only to rows the vectorised part kept.
    The residual should itself be the COMPLETE predicate (it may re-check type/source — harmless and
    cheap on the survivors), which keeps the two halves from ever disagreeing."""
    n = len(rows)
    if last is None:
        last = n - 1
    if n == 0 or last < first:
        return np.empty(0, dtype=np.int64)
    needs_codes = allowed_types is not None or allowed_sources is not None
    if needs_codes and (store is None or not store.matches(rows)):
        raise ValueError("ColumnStore does not match the row list (stale store)")

    if not needs_codes:
        candidates = np.arange(first, last + 1, dtype=np.int64)  # nothing for the codes to decide
    else:
        mask = np.ones(last - first + 1, dtype=bool)
        if allowed_types is not None:
            mask &= np.isin(store.type_codes[first:last + 1], _member_codes(allowed_types, store.type_cats))
        if allowed_sources is not None:
            mask &= np.isin(store.source_codes[first:last + 1], _member_codes(allowed_sources, store.source_cats))
        candidates = np.flatnonzero(mask).astype(np.int64)
        if first:
            candidates += first

    if residual is None or candidates.size == 0:
        return candidates
    return np.fromiter((i for i in candidates.tolist() if residual(rows[i])), dtype=np.int64)


def proxy_row_of(idx: np.ndarray, source_row: int) -> int:
    """Position of `source_row` in the ascending index array, or -1 when it is filtered out."""
    n = len(idx)
    if n == 0 or source_row < 0:
        return -1
    if idx[-1] == n - 1:  # idx is ascending & unique, so this means it is the identity [0..n-1]
        return source_row if source_row < n else -1
    pos = int(np.searchsorted(idx, source_row))
    return pos if pos < n and idx[pos] == source_row else -1


def remap_rows(old_idx: np.ndarray, new_idx: np.ndarray, proxy_rows: Sequence[int]) -> List[int]:
    """For persistent-index updating after a re-filter: where each OLD proxy row ended up in the NEW
    index array (the same source row), or -1 when that row is no longer visible."""
    out: List[int] = []
    for r in proxy_rows:
        if 0 <= r < len(old_idx):
            out.append(proxy_row_of(new_idx, int(old_idx[r])))
        else:
            out.append(-1)
    return out


def splice_range(idx: np.ndarray, first: int, last: int, new_in_range: np.ndarray) -> np.ndarray:
    """New index array after the membership of source rows [first, last] was recomputed."""
    a = int(np.searchsorted(idx, first, side="left"))
    b = int(np.searchsorted(idx, last, side="right"))
    return np.concatenate((idx[:a], new_in_range.astype(np.int64, copy=False), idx[b:]))
