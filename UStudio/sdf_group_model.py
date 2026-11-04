"""Hierarchical Qt model for SDF Viewer Mode's QTreeView (see main.py's
set_sdf_mode()) — shown INSTEAD of the flat QTableView while that mode is
active, not a filtered view layered on top of it. Deliberately not built on
ObjectTableModel/AdvancedFilterProxyModel: those are flat-row-shaped by
design (object_table.py's own get_visible_items()/sort() docstrings explain
why QSortFilterProxyModel's normal per-row Qt calls are already a measured
bottleneck at this app's object counts even without faking hierarchy on top),
and SDF Viewer Mode is meant to be a small, isolated workspace, not a filter
of the main table.

Two levels: a top-level row per SDFGroup (a synthetic "SDF Font Pack" folder
row, no obj_ref of its own — see type_icons.get_folder_icon()), each with up
to 4 children (font/material/texture/source font, whichever resolved — see
core.sdf_resolver.SDFGroup.children()). A child row's UserRole data IS the
exact same RowItem dict the flat table uses for that object when it was
already indexed there — editing/exporting through either view stays
consistent, since it's the same dict either way. Which real object a child
row IS (font vs material vs texture) is conveyed by its icon + Тип column,
same vocabulary the flat table already uses — no separate "role" text
column. Container path/script name (available on the flat table) are
deliberately left out here — this view is meant to stay a compact, at-a-
glance folder listing, not a second copy of every flat-table column."""

from core.i18n import N_, tr
from typing import List, Optional, Tuple

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt

from core.file_utils import format_size
from core.object_preview import get_row_name
from core.sdf_resolver import SDFGroup
from type_icons import get_folder_icon, get_type_icon


class SDFGroupModel(QAbstractItemModel):
    HEADERS = (N_("Имя"), N_("Тип"), N_("Источник"), N_("Размер"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups: List[SDFGroup] = []
        # Parallel to self.groups — each entry is a list of (group_row, item)
        # tuples, ONE tuple object per child row, built exactly once here (not
        # on every index()/data() call, and not stored on the RowItem dicts
        # themselves — those are shared with the flat table; a Material/
        # Texture2D reused by two different fonts would otherwise get its
        # parent silently overwritten by whichever group built last).
        #
        # This single-construction requirement isn't just tidiness: PyQt6's
        # createIndex(row, col, obj) ties its internal pointer bookkeeping to
        # the Python object's OWN identity, not its value — an index() that
        # instead built a FRESH tuple per call (same values, different
        # object) crashed with a real Windows access violation the moment a
        # second column was requested for an already-visited row, confirmed
        # directly via faulthandler (not assumed): the very next createIndex
        # call for that row returned a corrupted internalPointer(). Every
        # child row's node object must be created once and returned by
        # identity from then on, exactly like self.groups[row] already is
        # for top-level rows.
        self._children: List[List[Tuple[int, dict]]] = []
        self._all_groups: List[SDFGroup] = []
        self._filter = ""
        self._coverage = {}   # group_id -> text shown in the header row's second column

    def set_groups(self, groups: List[SDFGroup]) -> None:
        self._all_groups = list(groups)
        self._coverage = {}
        self._apply_filter()

    def set_filter(self, text: str) -> None:
        """Keeps only the groups whose font, material, atlas or source font name contains `text`."""
        self._filter = (text or "").strip().lower()
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self._filter
        if needle:
            groups = [g for g in self._all_groups
                      if any(needle in str(get_row_name(item)).lower() for item in g.children())]
        else:
            groups = list(self._all_groups)
        self.beginResetModel()
        self.groups = groups
        self._children = [
            [(group_row, item) for item in g.children()]
            for group_row, g in enumerate(groups)
        ]
        self.endResetModel()

    def set_coverage(self, group_id: str, text: str) -> None:
        self._coverage[group_id] = text
        for row, g in enumerate(self.groups):
            if g.group_id == group_id:
                idx = self.index(row, 0)  # rendered as part of the name cell now, see _group_data
                self.dataChanged.emit(idx, idx)
                break

    def refresh_rows(self) -> None:
        """Tells the view every row's data may have changed (an object was patched: sizes, names)."""
        if not self.groups:
            return
        last_col = self.columnCount() - 1
        self.dataChanged.emit(self.index(0, 0), self.index(len(self.groups) - 1, last_col))
        for row, children in enumerate(self._children):
            if children:
                parent = self.index(row, 0)
                self.dataChanged.emit(self.index(0, 0, parent), self.index(len(children) - 1, last_col, parent))

    def items_for_indexes(self, indexes) -> List[dict]:
        """The RowItems behind the selected rows, each once. A group header stands for its font asset
        (the group's identity); a child row is its own object."""
        seen, items = set(), []
        for index in indexes:
            if index.column() != 0 or not index.isValid():
                continue
            item = self.item_at(index)
            if item is None:
                group = self.group_at(index)
                item = group.font if group is not None else None
            if item is not None and id(item) not in seen:
                seen.add(id(item))
                items.append(item)
        return items

    # --- QAbstractItemModel plumbing ---

    def index(self, row, column, parent=QModelIndex()):
        if not parent.isValid():
            if 0 <= row < len(self.groups):
                return self.createIndex(row, column, self.groups[row])
            return QModelIndex()
        node = parent.internalPointer()
        if isinstance(node, SDFGroup):
            group_row = parent.row()
            children = self._children[group_row]
            if 0 <= row < len(children):
                return self.createIndex(row, column, children[row])
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if isinstance(node, SDFGroup):
            return QModelIndex()
        group_row, _item = node
        return self.createIndex(group_row, 0, self.groups[group_row])

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            return len(self.groups)
        node = parent.internalPointer()
        if isinstance(node, SDFGroup):
            return len(self._children[parent.row()])
        return 0

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(self.HEADERS[section])
        return None

    # --- Data ---

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        col = index.column()

        if isinstance(node, SDFGroup):
            return self._group_data(node, col, role)
        group_row, item = node
        return self._item_data(item, col, role)

    def _group_data(self, group: SDFGroup, col: int, role):
        if role == Qt.ItemDataRole.UserRole:
            # No single RowItem for a group header — see main.py's SDF-mode
            # selection handler, which previews the font row itself instead.
            return None
        if role == Qt.ItemDataRole.ToolTipRole and (group.material_error or group.texture_error):
            return "\n".join(e for e in (group.material_error, group.texture_error) if e)
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return get_folder_icon()
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        # Real reported request: Тип/Источник/Размер left blank for a folder
        # row — "SDF Font Pack" and an aggregate size read as noise once the
        # folder icon (DecorationRole above) already conveys "this is a
        # group", not a real object; each child row still shows its own real
        # type/source/size underneath.
        if col == 0:
            name = get_row_name(group.font)
            coverage = self._coverage.get(group.group_id, "")
            # Real reported bug: this used to live in column 1 ("Тип") alone, which is sized for
            # a short child-row type name ("MonoBehaviour") and truncated the coverage text
            # ("275 симв. · Кириллица") hard. Group header rows are spanned across the whole row
            # width (main.py sets QTreeView.setFirstColumnSpanned for every top-level row) so
            # there is no separate "Тип" cell to put it in anyway — folded into the name itself.
            return f"{name}   ·   {coverage}" if coverage else name
        return ""

    def _item_data(self, item: dict, col: int, role):
        if role == Qt.ItemDataRole.UserRole:
            return item
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return get_type_icon(item.get("type", ""))
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if col == 0: return get_row_name(item)
        if col == 1: return item.get("type", "")
        if col == 2: return item.get("source", "")
        if col == 3: return format_size(item.get("size", 0))
        return None

    def item_at(self, index: QModelIndex) -> Optional[dict]:
        """Convenience accessor for main.py's selection/context-menu handling
        — the RowItem for a child row, or None for a group header (same as
        data(index, UserRole), just without the Qt role ceremony at call sites)."""
        return self.data(index, Qt.ItemDataRole.UserRole)

    def group_at(self, index: QModelIndex) -> Optional[SDFGroup]:
        if not index.isValid():
            return None
        node = index.internalPointer()
        if isinstance(node, SDFGroup):
            return node
        group_row, _item = node
        return self.groups[group_row]
