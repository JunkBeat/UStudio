"""The main object table's Qt model + sort/filter proxies — the names the rest of the app imports.

The code lives in focused modules (split out of the old single file, mechanical move, no logic changes):
  table_model.py         ObjectTableModel (rows, sorting, lazy name/script reading, name warm-up), UserActivityTracker
  table_filter.py        the row predicate both proxies share
  table_proxy_index.py   IndexFilterProxyModel (the proxy the application uses)
  table_proxy_legacy.py  LegacyFilterProxyModel (rollback / parity reference)
This module re-exports them and picks the proxy: AdvancedFilterProxyModel."""

import os

from core.object_preview import get_row_name, get_row_script_name  # noqa: F401  (patched by patch_resolvers)
from table_filter import _NO_TEXT_FILTER, _item_passes_filter  # noqa: F401
from table_model import _RESOLVE_PLACEHOLDER_DELAY_MS, ObjectTableModel, UserActivityTracker  # noqa: F401
from table_proxy_index import IndexFilterProxyModel
from table_proxy_legacy import LegacyFilterProxyModel

__all__ = [
    "AdvancedFilterProxyModel", "IndexFilterProxyModel", "LegacyFilterProxyModel", "ObjectTableModel",
    "UserActivityTracker", "get_row_name", "get_row_script_name", "patch_resolvers",
    "_NO_TEXT_FILTER", "_item_passes_filter", "_RESOLVE_PLACEHOLDER_DELAY_MS",
]

# The proxy the application uses. USTUDIO_LEGACY_PROXY=1 switches back to the QSortFilterProxyModel one
# (rollback / A-B comparison); tests import both classes by name.
AdvancedFilterProxyModel = (
    LegacyFilterProxyModel if os.environ.get("USTUDIO_LEGACY_PROXY") == "1" else IndexFilterProxyModel
)


def patch_resolvers(name_fn=None, script_fn=None, selector_fn=None) -> None:
    """Test hook: replace get_row_name / get_row_script_name / row_matches_script_selector in EVERY module that
    calls them (each module holds its own reference, so patching only this facade would not reach the moved
    code). None leaves one unchanged."""
    import sys

    import table_filter
    import table_model
    import table_proxy_index
    import table_proxy_legacy
    for module in (table_model, table_filter, table_proxy_index, table_proxy_legacy, sys.modules[__name__]):
        if name_fn is not None and hasattr(module, "get_row_name"):
            module.get_row_name = name_fn
        if script_fn is not None and hasattr(module, "get_row_script_name"):
            module.get_row_script_name = script_fn
        if selector_fn is not None and hasattr(module, "row_matches_script_selector"):
            module.row_matches_script_selector = selector_fn
