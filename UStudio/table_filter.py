"""The row predicate shared by both filter proxies (type / script / source / modified / free text) — split
out of object_table.py (mechanical move, no logic changes)."""

from PyQt6.QtCore import (
    QRegularExpression,
)

from core.object_preview import get_row_name, get_row_script_name, row_matches_script_selector
from table_model import ObjectTableModel


# Passed to _item_passes_filter() when no free-text filter is set — avoids creating a regex object per row.
_NO_TEXT_FILTER = QRegularExpression()


_DIGITS = frozenset("0123456789-")


def text_value_matcher(regex: QRegularExpression, needle: str):
    """A predicate over a row's values that answers exactly what `regex.match(str(value)).hasMatch()` for any
    str/int value would (the per-field test of _item_passes_filter), ~3x faster over a whole table.

    - Every distinct string is matched ONCE (`memo`): a big table repeats the same few strings — names are
      interned (Lego Party: 123k distinct among 1.95M rows), types, files, scripts. Measured on Lego Party's
      1.95M rows: 6.3 s -> 2.2 s per search for a text needle, identical rows for every needle tried.
    - An int's text is digits and «-» only: a needle with any other character can never match it; a needle of
      digits/«-» only is matched with plain `in` (its case does not matter). Other int kinds (bool) go through
      the regex like before.
    `needle` is the literal the regex was built from (setFilterFixedString). The memo grows with the distinct
    strings seen — make a new matcher per filter pass."""
    memo = {}
    memo_get = memo.get
    digit_needle = bool(needle) and all(c in _DIGITS for c in needle)

    def matches(values) -> bool:
        for v in values:
            cls = v.__class__
            if cls is str:
                hit = memo_get(v)
                if hit is None:
                    hit = memo[v] = regex.match(v).hasMatch()
                if hit:
                    return True
            elif cls is int:
                if digit_needle and needle in str(v):
                    return True
            elif isinstance(v, (str, int)) and regex.match(str(v)).hasMatch():
                return True
        return False

    return matches


def _item_passes_filter(
    item, allowed_types, allowed_scripts, filter_regex, allowed_sources=None, modified_only=False,
    bookmark_matcher=None,
) -> bool:
    """The actual type/script/source/modified/text-search predicate — shared by
    AdvancedFilterProxyModel.filterAcceptsRow() (called by Qt, per row, through
    the normal QModelIndex-based model interface) and get_visible_items()
    (called directly against the plain dict list, with no Qt/PyQt boundary
    crossings at all — see that method's docstring for why that distinction
    matters at large row counts). Keeping one predicate function means the two
    call sites can't silently drift into filtering differently.

    allowed_sources/modified_only are the Quick Filters Bar's own additions
    (core/quick_filters.py) — both AND with everything else (a file selection
    narrows whatever type/script filter is already active; "Изменено" hides
    unmodified rows within whatever's already showing), unlike allowed_types
    itself, which is a plain membership test. bookmark_matcher (core.bookmarks.BookmarkStore.matcher(), or None)
    is the bar's «Закладки» toggle: it ANDs the same way."""
    if allowed_types is not None and item.get("type") not in allowed_types:
        return False
    if (
        allowed_scripts is not None
        and item.get("type") == "MonoBehaviour"
        # script_name is lazily resolved (see get_row_script_name()'s own
        # docstring) — an active script filter is exactly the case where
        # resolving it is unavoidable, same reasoning as sort() above.
        # row_matches_script_selector() checks the bare name first (same
        # cost as the old `not in allowed_scripts` check) and only falls
        # through to the namespace/assembly-qualified forms — needed since
        # a same-named-but-different script can share one bare class name
        # (core.object_common.script_checklist_entries()'s own docstring).
        and not row_matches_script_selector(item, allowed_scripts)
    ):
        return False
    if allowed_sources is not None and item.get("source") not in allowed_sources:
        return False
    if modified_only and not ObjectTableModel._is_modified(item):
        return False
    if bookmark_matcher is not None and not bookmark_matcher(item):
        return False

    pattern = filter_regex.pattern()
    if not pattern:
        return True
    # A real free-text search is exactly the case where every row's
    # name/script_name need resolving — you can't match text against a value
    # you haven't looked at — so this is the other intentional trigger point
    # (besides sorting by one of those columns) for paying that cost, and
    # only when the user has actually typed something to search for.
    get_row_name(item)
    get_row_script_name(item)
    for value in item.values():
        # obj_ref (a UnityPy object) — not a text field, doesn't participate in the filter
        if isinstance(value, (str, int)) and filter_regex.match(str(value)).hasMatch():
            return True
    return False
