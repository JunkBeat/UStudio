"""Инструменты -> «Таблица полей MonoBehaviour…»: pick scripts, tick their fields, build their tables (core/field_table.py).

Successor of the old «Извлекатель полей из дампов MonoBehaviour» (Downloads\\UStudio old\\tools\\mb_field_parser_tool.py),
which exported straight to CSV/XLSX from a field tree built by parsing the first object and grouped objects by their OWN
name. Here (the user's choices):
  * the field tree comes from the script's LAYOUT — instant, no object is read until the tables are built;
  * one build covers several scripts, but each script gets its OWN tab and table (redesign 2026-10-14: one combined
    table was "a sieve" — every row filled only its own script's columns);
  * one row per list item (core/field_table.py's rows_for_object);
  * sort by a column, a filter (all tabs), Ctrl+C copies the selected cells, CSV export of the open tab (UTF-8 with
    BOM, ';' — opens split into columns in a Russian Excel).

Layout (redesign): left the scripts (search, ☐ include, full "Namespace.ClassName" name like the Filters window);
right the fields of the selected script (a search box, «Снять отметки», the tree collapsed to its top level) and,
under them, what the build will cover («2 скрипта · 5 полей») with «Построить таблицы»; below, the results with their
own row (filter, «Сохранить CSV…»), one tab per script, and one status line. Bare by the user's standing request (no
explanatory paragraphs).

The script list and the tables are built off the GUI thread (BackgroundWorker); building can be cancelled with
«Отмена» or Esc, closing the window cancels and waits, and the main window's teardown (requestInterruption) is honoured.
Non-modal, one per main window (`field_table_dialog`); closed before the loaded files are released (main_save_flow)."""

from core.i18n import tr, trn
import csv
import logging
import time

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel, Qt, QThread
from PyQt6.QtGui import QFont, QKeySequence, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton, QSplitter, QTableView, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

from app_settings import app_settings
from core.field_table import (
    BASE_COLUMNS, dump_presets, is_blank, parse_presets, paths_containing, resolve_preset, rows_for_object,
    sample_values, script_fields,
)
from core.file_utils import ScriptIdentity, peek_mb_identity
from core.object_common import get_row_name, get_row_script_name, script_identity_tooltip
from gui_workers import BackgroundWorker
from helpers import wrap_tooltip
from type_icons import get_action_icon, get_type_icon

logger = logging.getLogger("ustudio.gui.field_table")

_PATH_ROLE = Qt.ItemDataRole.UserRole + 1
_MAX_COLUMN_WIDTH = 420
_PRESETS_KEY = "field_table/presets"
_HIDE_BLANK_KEY = "field_table/hide_blank_rows"
_SAMPLE_OBJECTS = 200          # «Пример»: at most this many objects are read to find a non-empty value per field
_SAMPLE_SECONDS = 1.5          # ...and for at most this long


def _one_line(text: str) -> str:
    """A sample in one tree row: line breaks shown as ⏎ (translations have them)."""
    return text.replace("\r\n", " ⏎ ").replace("\n", " ⏎ ").replace("\r", " ⏎ ")


def _object_rows(item, paths):
    """One object's table rows (Имя, Источник, PathID + its ticked fields; one row per list item), or None when it
    cannot be read. Used by the build (worker thread) and to refresh an object after «Отредактировать данные»."""
    try:
        data = item["obj_ref"].parse_as_dict()
    except Exception:  # noqa: BLE001 - an unreadable object is counted by the caller, not fatal
        return None
    col_index = {p: k for k, p in enumerate(paths)}
    base = [get_row_name(item), item.get("source", ""), str(item.get("path_id", ""))]   # BASE_COLUMNS' order
    rows = []
    for cells in rows_for_object(data, paths):
        row = base + [""] * len(paths)
        for path, text in cells.items():
            row[len(base) + col_index[path]] = text
        rows.append(row)
    return rows


class _ResultModel(QAbstractTableModel):
    """One built table: plain strings, one list per row; `items[i]` is the RowItem row i came from (an object with
    a list has several rows)."""

    def __init__(self, headers, rows, items, parent=None):
        super().__init__(parent)
        self.headers, self.rows, self.items = headers, rows, items

    def replace_object(self, item, new_rows) -> None:
        """An object's rows after it was edited (their number can change: one row per list item)."""
        indexes = [k for k, it in enumerate(self.items) if it is item]
        if not indexes:
            return
        at = indexes[0]
        self.beginResetModel()
        keep = [(r, it) for r, it in zip(self.rows, self.items) if it is not item]
        merged = keep[:at] + [(r, item) for r in new_rows] + keep[at:]
        self.rows = [r for r, _it in merged]
        self.items = [it for _r, it in merged]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole) and index.isValid():
            return self.rows[index.row()][index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None


class _SortProxy(QSortFilterProxyModel):
    """Filter over every column; numbers sort as numbers (PathID, counts, floats)."""

    def lessThan(self, left, right):
        a, b = left.data() or "", right.data() or ""
        try:
            return float(a) < float(b)
        except ValueError:
            return a.casefold() < b.casefold()


class _ResultProxy(_SortProxy):
    """A result tab's proxy: also hides the rows whose ticked fields are all empty or only spaces/tabs (user
    request; «Без пустых строк», on by default)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide_blank = True

    def set_hide_blank(self, on: bool) -> None:
        self.hide_blank = on
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if self.hide_blank:
            row = self.sourceModel().rows[source_row]
            if all(is_blank(cell) for cell in row[len(BASE_COLUMNS):]):
                return False
        return super().filterAcceptsRow(source_row, source_parent)


class _ResultTab(QTableView):
    """One script's table (a tab of the results): whole rows are selected (user request)."""

    def __init__(self, script, paths, rows, items, failed, parent=None):
        super().__init__(parent)
        self.script, self.paths, self.failed = script, paths, failed
        self.model_ = _ResultModel([tr(c) if c != "PathID" else c for c in BASE_COLUMNS] + list(paths), rows, items, self)
        self.proxy = _ResultProxy(self)
        self.proxy.setSourceModel(self.model_)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setModel(self.proxy)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.sortByColumn(-1, Qt.SortOrder.AscendingOrder)                    # the reading order until asked
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)                 # user request: no column stretched across the tab
        header.setHighlightSections(False)                  # a selected whole row would bold every title
        self.verticalHeader().setDefaultSectionSize(22)
        self.resizeColumnsToContents()
        for col in range(self.model_.columnCount()):
            # never narrower than the header (it was cut: «m_spriteAni…»), never wider than _MAX_COLUMN_WIDTH
            # because of a long cell
            self.setColumnWidth(col, max(min(self.columnWidth(col), _MAX_COLUMN_WIDTH), header.sectionSizeHint(col)))


def _item_for(tab, proxy_index):
    """The RowItem behind a row of a result tab (a proxy index: sorted/filtered)."""
    if not proxy_index.isValid():
        return None
    return tab.model_.items[tab.proxy.mapToSource(proxy_index).row()]


class FieldTableDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle(tr("Инспектор полей MonoBehaviour"))
        self.setModal(False)
        self._fit_to_screen(1100, 680)

        self._groups = {}              # full script name -> [RowItem]
        self._selections = {}          # full script name -> [ticked paths, in the order ticked]
        self._current_script = None
        self._filling_tree = False
        self._worker = None
        self._list_worker = None
        self._cancel = False
        self._fields = {}              # full script name -> its field tree (None: unreadable)
        self._samples = {}             # full script name -> {path: sample text}
        self._focus = {}               # full script name -> (RowItem, needle): samples from that object (text search)
        self._matched = {}             # full script name -> {paths whose value holds the text searched for}
        self._sample_workers = []      # every sample read still running (waited for on close)
        self._sample_cancel = {}       # worker -> [flag]
        self._sample_generation = 0
        self._pending_focus = None     # (obj, needle) asked before the script list was ready

        self._build_ui()
        self._load_scripts()

    # --- UI ---

    def _build_ui(self):
        layout = QVBoxLayout(self)
        # named sets of ticked fields, by script name — not tied to one game (the same scripts are in many)
        preset_bar = QHBoxLayout()
        preset_bar.addWidget(QLabel(tr("Набор полей:")))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(160)
        self.preset_combo.activated.connect(self._on_preset_chosen)
        preset_bar.addWidget(self.preset_combo)
        self.btn_save_preset = QPushButton(tr("Сохранить…"))
        self.btn_save_preset.setToolTip(wrap_tooltip(
            tr("Запоминает отмеченные поля отмеченных скриптов. Набор можно применить в любой игре, где есть "
               "скрипты с такими именами.")))
        self.btn_save_preset.clicked.connect(self._save_preset)
        preset_bar.addWidget(self.btn_save_preset)
        self.btn_delete_preset = QPushButton(tr("Удалить"))
        self.btn_delete_preset.clicked.connect(self._delete_preset)
        preset_bar.addWidget(self.btn_delete_preset)
        preset_bar.addStretch(1)
        layout.addLayout(preset_bar)
        vsplit = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(vsplit, 1)

        top = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.script_search = QLineEdit()
        self.script_search.setPlaceholderText(tr("Поиск скрипта"))
        self.script_search.setClearButtonEnabled(True)
        script_bar = QHBoxLayout()
        script_bar.addWidget(self.script_search, 1)
        self.btn_uncheck_scripts = QPushButton(tr("Снять отметки"))
        self.btn_uncheck_scripts.clicked.connect(self._uncheck_all_scripts)
        script_bar.addWidget(self.btn_uncheck_scripts)
        left_layout.addLayout(script_bar)
        self.script_model = QStandardItemModel(0, 2, self)
        self.script_model.setHorizontalHeaderLabels([tr("Скрипт"), tr("Объектов")])
        self.script_model.itemChanged.connect(lambda _item: self._update_scope())
        self.script_proxy = _SortProxy(self)
        self.script_proxy.setSourceModel(self.script_model)
        self.script_proxy.setFilterKeyColumn(0)
        self.script_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.script_search.textChanged.connect(self.script_proxy.setFilterFixedString)
        self.script_view = QTableView()
        self.script_view.setModel(self.script_proxy)
        self.script_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.script_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.script_view.setSortingEnabled(True)
        self.script_view.verticalHeader().hide()
        self.script_view.verticalHeader().setDefaultSectionSize(26)          # room for the larger checkboxes
        self.script_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # the same header look as the field tree beside it (user request): left-aligned, normal weight — a table
        # header is centred by default and bolds every column holding the selection (a whole row = both titles)
        self.script_view.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.script_view.horizontalHeader().setHighlightSections(False)
        self.script_view.selectionModel().currentRowChanged.connect(self._on_script_selected)
        left_layout.addWidget(self.script_view, 1)
        top.addWidget(left)

        fields = QWidget()
        fields_layout = QVBoxLayout(fields)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        field_bar = QHBoxLayout()
        self.field_search = QLineEdit()
        self.field_search.setPlaceholderText(tr("Поиск поля или значения"))
        self.field_search.setClearButtonEnabled(True)
        self.field_search.textChanged.connect(self._filter_fields)
        field_bar.addWidget(self.field_search, 1)
        self.btn_clear_ticks = QPushButton(tr("Снять отметки"))
        self.btn_clear_ticks.clicked.connect(self._clear_ticks)
        field_bar.addWidget(self.btn_clear_ticks)
        fields_layout.addLayout(field_bar)
        self.field_tree = QTreeWidget()
        # «Пример»: what the field holds (user report: picking fields without seeing any data was "blind")
        self.field_tree.setHeaderLabels([tr("Поле"), tr("Тип"), tr("Пример")])
        tree_header = self.field_tree.header()
        tree_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tree_header.setStretchLastSection(True)
        self.field_tree.setColumnWidth(0, 240)
        self.field_tree.setColumnWidth(1, 110)
        self.field_tree.itemChanged.connect(self._on_field_toggled)
        fields_layout.addWidget(self.field_tree, 1)
        self.sample_label = QLabel()                          # «Пример — читается…» while reading, else hidden
        self.sample_label.setEnabled(False)                   # muted
        fields_layout.addWidget(self.sample_label)
        top.addWidget(fields)
        top.setSizes([380, 620])
        vsplit.addWidget(top)

        results = QWidget()
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(0, 0, 0, 0)
        # ONE action row between the top and the results: what the build covers, the filter, «Построить таблицы»
        # at the right end (user requests: one row; then «Сохранить CSV…» moved under the results, like the text
        # search's «Сохранить лог…», and the build button took its place)
        results_bar = QHBoxLayout()
        self.scope_label = QLabel()
        self.scope_label.setContentsMargins(6, 0, 8, 0)      # not glued to the window edge (user request)
        results_bar.addWidget(self.scope_label)
        self.table_filter = QLineEdit()
        self.table_filter.setPlaceholderText(tr("Фильтр"))
        self.table_filter.setClearButtonEnabled(True)
        self.table_filter.textChanged.connect(self._apply_filter)
        results_bar.addWidget(self.table_filter, 1)
        self.chk_hide_blank = QCheckBox(tr("Без пустых строк"))
        self.chk_hide_blank.setToolTip(wrap_tooltip(
            tr("Скрывает строки, в которых все выбранные поля пустые или содержат только пробелы и табуляцию.")))
        self.chk_hide_blank.setChecked(app_settings().value(_HIDE_BLANK_KEY, True, type=bool))
        self.chk_hide_blank.toggled.connect(self._on_hide_blank_toggled)
        results_bar.addWidget(self.chk_hide_blank)
        self.btn_build = QPushButton(tr("Построить таблицы"))
        self.btn_build.clicked.connect(self._on_build_clicked)
        results_bar.addWidget(self.btn_build)
        results_layout.addLayout(results_bar)
        self.result_tabs = QTabWidget()
        self.result_tabs.currentChanged.connect(lambda _i: self._show_counts())
        results_layout.addWidget(self.result_tabs, 1)
        csv_row = QHBoxLayout()                               # right above the status line
        self.btn_csv = QPushButton(tr("Сохранить CSV…"))
        self.btn_csv.setEnabled(False)
        self.btn_csv.clicked.connect(self._save_csv)
        csv_row.addWidget(self.btn_csv)
        csv_row.addStretch(1)
        results_layout.addLayout(csv_row)
        self.status_separator = QFrame()                      # a thin line above the status line (user request)
        self.status_separator.setFrameShape(QFrame.Shape.NoFrame)
        self.status_separator.setFixedHeight(1)
        self.status_separator.setStyleSheet("background-color: palette(mid);")
        results_layout.addWidget(self.status_separator)
        status_row = QHBoxLayout()
        self.status_label = QLabel()
        status_row.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setMaximumHeight(14)
        self.progress.setTextVisible(False)
        self.progress.hide()
        status_row.addWidget(self.progress)
        results_layout.addLayout(status_row)
        vsplit.addWidget(results)
        vsplit.setSizes([330, 350])
        # Larger checkboxes in the script list and the field tree (user: 16 px was hard to hit with the mouse when
        # clicking through many scripts/fields); only the size — the images come from the app stylesheet.
        self.setStyleSheet("QAbstractItemView::indicator { width: 20px; height: 20px; }")
        # No default button: Enter in a search/filter field must not "press" one (it made «Снять все» the
        # default — Enter in the script search would have unchecked every script)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self._fill_presets()
        self._update_scope()

    def _fit_to_screen(self, width: int, height: int) -> None:
        """At most 85 % of the screen's free area (room for the title bar and the taskbar — at 150 % scaling
        1100x680 went past the taskbar), centred on it."""
        screen = (self.main_window.screen() if self.main_window is not None else None) or QApplication.primaryScreen()
        if screen is None:
            self.resize(width, height)
            return
        free = screen.availableGeometry()
        width = min(width, int(free.width() * 0.85))
        height = min(height, int(free.height() * 0.85))
        self.resize(width, height)
        self.move(free.x() + (free.width() - width) // 2, free.y() + (free.height() - height) // 2)

    # --- scripts ---

    def _load_scripts(self):
        rows = list(getattr(self.main_window, "raw_data_list", None) or [])

        def work(report_progress):
            """Grouped by the FULL script name ("Namespace.ClassName"), like the Filters window
            (script_checklist_entries): two scripts with the same class name in different namespaces stay apart."""
            groups, tooltips = {}, {}
            for item in rows:
                if item.get("type") != "MonoBehaviour":
                    continue
                bare = get_row_script_name(item) or "?"
                identity = peek_mb_identity(item.get("obj_ref")) if item.get("obj_ref") is not None else None
                if identity is None:
                    identity = ScriptIdentity(class_name=bare, namespace="", assembly_name="")
                name = identity.qualified_name
                groups.setdefault(name, []).append(item)
                tooltips.setdefault(name, script_identity_tooltip(identity))
            return groups, tooltips

        self.status_label.setText(tr("Поиск скриптов…"))
        self._list_worker = BackgroundWorker(work, parent=self)
        self._list_worker.succeeded_signal.connect(self._on_scripts_ready)
        self._list_worker.failed_signal.connect(lambda msg: self.status_label.setText(msg))
        self._list_worker.start()

    def _on_scripts_ready(self, result):
        groups, tooltips = result
        self._groups = groups
        self.script_model.blockSignals(True)
        self.script_model.setRowCount(0)
        for name in sorted(groups, key=str.casefold):
            name_item = QStandardItem(name)
            name_item.setToolTip(tooltips.get(name, ""))
            name_item.setCheckable(True)
            if self._selections.get(name):              # added from the text search before the list was ready
                name_item.setCheckState(Qt.CheckState.Checked)
            name_item.setEditable(False)
            count_item = QStandardItem(str(len(groups[name])))
            count_item.setEditable(False)
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.script_model.appendRow([name_item, count_item])
        self.script_model.blockSignals(False)
        self._update_scope()
        self.script_proxy.invalidate()
        self.script_view.resizeColumnToContents(1)
        if not groups:
            self.status_label.setText(tr("Нет загруженных объектов MonoBehaviour."))
            return
        self.status_label.setText(trn(len(groups), "{n} скрипт", "{n} скрипта", "{n} скриптов"))
        if self._pending_focus is not None:
            obj, needle = self._pending_focus
            self._pending_focus = None
            if self.focus_object(obj, needle):
                return
        self.script_view.selectRow(0)

    def _script_item(self, name):
        for row in range(self.script_model.rowCount()):
            item = self.script_model.item(row, 0)
            if item.text() == name:
                return item
        return None

    def _on_script_selected(self, current, _previous):
        if not current.isValid():
            return
        name = self.script_proxy.index(current.row(), 0).data()
        self._current_script = name
        self._fill_tree(name)
        self._read_samples(name)

    def _select_script_row(self, name) -> bool:
        """Selects `name` in the script list (the search is cleared if it hides it)."""
        for attempt in range(2):
            for row in range(self.script_proxy.rowCount()):
                if self.script_proxy.index(row, 0).data() == name:
                    if self._current_script == name:
                        self._fill_tree(name)
                        self._read_samples(name)
                    else:
                        self.script_view.selectRow(row)
                    self.script_view.scrollTo(self.script_proxy.index(row, 0))
                    return True
            self.script_search.clear()
        return False

    # --- fields ---

    def _fields_of(self, name):
        """The script's field tree (cached), None when its layout cannot be read; KeyError when not loaded."""
        if name not in self._fields:
            fields = None
            try:
                fields = script_fields(self._groups[name][0]["obj_ref"]._get_typetree_node())
            except KeyError:
                raise
            except Exception as e:  # noqa: BLE001 - one unreadable script must not break the window
                logger.debug("Поля скрипта %s не прочитаны: %s", name, e)
            self._fields[name] = fields
        return self._fields[name]

    def _fill_tree(self, name):
        self._filling_tree = True
        self.field_tree.clear()
        try:
            fields = self._fields_of(name)
            if fields is None:
                item = QTreeWidgetItem([tr("Не удалось прочитать поля этого скрипта")])
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.field_tree.addTopLevelItem(item)
                return
            ticked = set(self._selections.get(name, []))
            samples = self._samples.get(name, {})
            matched = self._matched.get(name, set())
            bold = QFont(self.field_tree.font())
            bold.setBold(True)
            reveal = []

            def add(parent, node):
                sample = samples.get(node.path, "")
                item = QTreeWidgetItem([f"{node.name}[]" if node.is_list else node.name, node.type,
                                        _one_line(sample)])
                if sample:
                    item.setToolTip(2, wrap_tooltip(sample, 80))
                if node.path in matched:                 # holds the text the text search found
                    for col in range(3):
                        item.setFont(col, bold)
                    reveal.append(item)
                item.setData(0, _PATH_ROLE, node.path)
                item.setSizeHint(0, QSize(0, 24))       # rows tall enough for the 20 px checkboxes (else squashed)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if node.path in ticked else Qt.CheckState.Unchecked)
                if parent is None:
                    self.field_tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                for child in node.children:
                    add(item, child)

            for node in fields:
                add(None, node)
            self.field_tree.collapseAll()                # the top level only (TMP scripts have 100+ fields)
        finally:
            self._filling_tree = False
        self._filter_fields(self.field_search.text())
        for item in reveal:                              # the fields the text search found: opened, in view
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
        if reveal:
            self.field_tree.scrollToItem(reveal[0])
        self._show_sample_source(name)

    def _show_sample_source(self, name):
        """Only while «Пример» is being read (user request: no line about where the values come from)."""
        reading = name not in self._samples and bool(self._fields.get(name))
        self.sample_label.setText(tr("Пример читается…") if reading else "")
        self.sample_label.setVisible(reading)

    def _read_samples(self, name):
        """Fills «Пример» for `name` in the background (once per script; from the text search: that object)."""
        if name in self._samples or self._fields.get(name) is None:
            return
        self._sample_generation += 1
        generation = self._sample_generation
        for flag in self._sample_cancel.values():        # an older read for another script is not needed now
            flag[0] = True
        fields = self._fields[name]
        focus = self._focus.get(name)
        items = [focus[0]] if focus is not None else list(self._groups.get(name, ()))
        needle = focus[1] if focus is not None else ""
        cancel = [False]

        def work(report_progress):
            thread = QThread.currentThread()
            start = time.monotonic()
            found = []

            def datas():
                for k, item in enumerate(items):
                    if (cancel[0] or thread.isInterruptionRequested() or k >= _SAMPLE_OBJECTS
                            or time.monotonic() - start > _SAMPLE_SECONDS):
                        return
                    try:
                        data = item["obj_ref"].parse_as_dict()
                    except Exception:  # noqa: BLE001 - an unreadable object just gives no sample
                        continue
                    if needle:
                        found.extend(paths_containing(data, fields, needle))
                    yield data

            samples = sample_values(datas(), fields)
            return None if cancel[0] else (samples, found)

        worker = BackgroundWorker(work, parent=self)
        self._sample_cancel[worker] = cancel
        self._sample_workers.append(worker)

        def done(result, worker=worker):
            self._sample_cancel.pop(worker, None)
            if result is None or generation != self._sample_generation:
                return
            samples, found = result
            self._samples[name] = samples
            if found:
                self._matched[name] = set(found)
                paths = self._selections.setdefault(name, [])
                paths.extend(p for p in found if p not in paths)
                script_item = self._script_item(name)
                if script_item is not None:
                    script_item.setCheckState(Qt.CheckState.Checked)
                self._update_scope()
            if self._current_script == name:
                self._fill_tree(name)
            if focus is not None:
                self._report_focus(name, found, needle)

        worker.succeeded_signal.connect(done)
        worker.failed_signal.connect(lambda msg, worker=worker: self._sample_cancel.pop(worker, None))
        worker.finished.connect(lambda worker=worker: self._sample_workers.remove(worker)
                                if worker in self._sample_workers else None)
        self._show_sample_source(name)
        worker.start()

    def _report_focus(self, name, found, needle):
        if not needle:
            return
        if found:
            self.status_label.setText(
                trn(len(found), "«{needle}» найден в {n} поле — оно отмечено.", "«{needle}» найден в {n} полях — они отмечены.",
                    "«{needle}» найден в {n} полях — они отмечены.", needle=needle))
        else:
            self.status_label.setText(tr("«{needle}» не найден в полях этого объекта — посмотрите столбец «Пример»", needle=needle))

    def focus_object(self, obj, needle: str = "") -> bool:
        """From the text search («Изучить поля скрипта»): selects the script of `obj`, takes «Пример» from that
        object and ticks the fields whose value holds `needle` (what was searched for). False when `obj` is not
        one of the listed MonoBehaviours."""
        if not self._groups:
            if self._list_worker is not None and self._list_worker.isRunning():
                self._pending_focus = (obj, needle)
                return True
            return False
        key = (id(getattr(obj, "assets_file", None)), getattr(obj, "path_id", None))
        for name, items in self._groups.items():
            for item in items:
                ref = item.get("obj_ref")
                if ref is obj or (id(getattr(ref, "assets_file", None)), getattr(ref, "path_id", None)) == key:
                    self._focus[name] = (item, needle.strip())
                    self._samples.pop(name, None)
                    self._matched.pop(name, None)
                    return self._select_script_row(name)
        self.status_label.setText(tr("Этого объекта нет среди загруженных MonoBehaviour."))
        return False

    def add_objects(self, objs, needle: str) -> str:
        """«Добавить в инспектор полей» (text search; user request: collect several hits without opening and
        closing the window each time): ticks, for each MonoBehaviour of `objs`, the fields whose value holds `needle`
        in its script's selection, without showing or changing what the window shows. Each object is parsed here,
        once (what focus_object() reads in the background, but there a second request cancels the first). The
        script list may still be building: its rows are ticked when it arrives. Returns the line the text search
        shows."""
        needle = needle.strip()
        if not needle:
            return tr("Сначала найдите текст — в инспектор полей добавляются поля, где он есть.")
        added = objects = missing = unreadable = 0
        scripts = []
        for obj in objs:
            identity = peek_mb_identity(obj)
            name = identity.qualified_name if identity is not None else (get_row_script_name({"obj_ref": obj}) or "?")
            try:
                if name not in self._fields:
                    self._fields[name] = script_fields(obj._get_typetree_node())
                fields = self._fields[name]
                found = paths_containing(obj.parse_as_dict(), fields, needle) if fields else []
            except Exception as e:  # noqa: BLE001 - one unreadable object must not stop the others
                logger.debug("Поля объекта для инспектора не прочитаны: %s", e)
                fields, found = None, []
            if not fields:
                unreadable += 1
                continue
            if not found:
                missing += 1
                continue
            objects += 1
            paths = self._selections.setdefault(name, [])
            new = [p for p in found if p not in paths]
            paths.extend(new)
            added += len(new)
            self._matched.setdefault(name, set()).update(found)
            script_item = self._script_item(name)
            if script_item is not None:
                script_item.setCheckState(Qt.CheckState.Checked)
            if name not in scripts:
                scripts.append(name)
        if scripts:
            self._update_scope()
            if self._current_script in scripts:
                self._fill_tree(self._current_script)
        return self._added_message(added, objects, scripts, missing, unreadable, needle)

    @staticmethod
    def _added_message(added, objects, scripts, missing, unreadable, needle) -> str:
        if not objects:
            if unreadable and not missing:
                return tr("Поля этого скрипта не удалось прочитать — в инспектор полей ничего не добавлено.")
            if missing + unreadable > 1:
                return tr("«{needle}» нет в полях этих объектов — в инспектор полей ничего не добавлено.", needle=needle)
            return tr("«{needle}» нет в полях этого объекта — в инспектор полей ничего не добавлено.", needle=needle)
        where = scripts[0].rsplit(".", 1)[-1] if len(scripts) == 1 else \
            trn(len(scripts), "{n} скрипт", "{n} скрипта", "{n} скриптов")
        if added:
            text = trn(added, "В инспектор полей добавлено {n} поле: {where}", "В инспектор полей добавлено {n} поля: {where}",
                       "В инспектор полей добавлено {n} полей: {where}", where=where)
        else:
            text = tr("Эти поля уже есть в инспекторе полей: {where}", where=where)
        skipped = missing + unreadable
        if skipped:
            text += " " + trn(skipped, "(в {n} объекте текст в полях не найден)", "(в {n} объектах текст в полях не найден)",
                              "(в {n} объектах текст в полях не найден)")
        return text + "."

    def _filter_fields(self, text):
        """Shows the fields whose name or sample value contains `text` (and their parents, expanded); empty text
        shows all."""
        needle = text.strip().casefold()

        def visit(item) -> bool:
            child_match = False
            for k in range(item.childCount()):
                child_match = visit(item.child(k)) or child_match
            match = (not needle or needle in item.text(0).casefold()
                     or needle in (item.toolTip(2) or item.text(2)).casefold())
            item.setHidden(not (match or child_match))
            if needle:
                item.setExpanded(child_match)
            return match or child_match

        for k in range(self.field_tree.topLevelItemCount()):
            visit(self.field_tree.topLevelItem(k))
        if not needle:
            self.field_tree.collapseAll()

    def _on_field_toggled(self, item, column):
        if self._filling_tree or column != 0 or self._current_script is None:
            return
        path = item.data(0, _PATH_ROLE)
        paths = self._selections.setdefault(self._current_script, [])
        if item.checkState(0) == Qt.CheckState.Checked:
            if path not in paths:
                paths.append(path)
        elif path in paths:
            paths.remove(path)
        script_item = self._script_item(self._current_script)
        if script_item is not None:            # a script with ticked fields takes part in the build (can be unticked)
            script_item.setCheckState(Qt.CheckState.Checked if paths else Qt.CheckState.Unchecked)
        self._update_scope()

    def _clear_ticks(self):
        """«Снять отметки»: the selected script's ticked fields."""
        if self._current_script is None:
            return
        self._selections[self._current_script] = []
        self._filling_tree = True
        try:
            it = QTreeWidgetItemIterator(self.field_tree)
            while it.value():
                if it.value().flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    it.value().setCheckState(0, Qt.CheckState.Unchecked)
                it += 1
        finally:
            self._filling_tree = False
        script_item = self._script_item(self._current_script)
        if script_item is not None:
            script_item.setCheckState(Qt.CheckState.Unchecked)
        self._update_scope()

    def _uncheck_all_scripts(self):
        """«Снять все»: no script takes part in the build (their ticked fields stay, ticking one checks it again)."""
        for row in range(self.script_model.rowCount()):
            self.script_model.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self._update_scope()

    def _chosen(self):
        """{script: ticked paths} for the scripts that are checked AND have ticked fields (list order)."""
        chosen = {}
        for row in range(self.script_model.rowCount()):
            item = self.script_model.item(row, 0)
            paths = self._selections.get(item.text())
            if item.checkState() == Qt.CheckState.Checked and paths:
                chosen[item.text()] = list(paths)
        return chosen

    def _update_scope(self):
        """What «Построить таблицы» covers, right next to it (it was unclear whether it means the selected script or
        every checked one)."""
        chosen = self._chosen()
        if not chosen:
            self.scope_label.setText(tr("Отметьте поля"))
            self.btn_build.setEnabled(self._worker is not None and self._worker.isRunning())
            self.btn_save_preset.setEnabled(False)
            return
        self.btn_save_preset.setEnabled(True)
        scripts, fields = len(chosen), sum(len(p) for p in chosen.values())
        self.scope_label.setText(trn(scripts, "{n} скрипт", "{n} скрипта", "{n} скриптов") + " · "
                                 + trn(fields, "{n} поле", "{n} поля", "{n} полей"))
        self.btn_build.setEnabled(True)

    # --- presets («Набор полей») ---

    @staticmethod
    def _load_presets() -> dict:
        return parse_presets(app_settings().value(_PRESETS_KEY, "", type=str))

    @staticmethod
    def _store_presets(presets: dict) -> None:
        app_settings().setValue(_PRESETS_KEY, dump_presets(presets))

    def _fill_presets(self, select: str = "") -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("—")
        for name in sorted(self._load_presets(), key=str.casefold):
            self.preset_combo.addItem(name)
        self.preset_combo.setCurrentIndex(max(self.preset_combo.findText(select), 0) if select else 0)
        self.preset_combo.blockSignals(False)
        self.btn_delete_preset.setEnabled(self.preset_combo.currentIndex() > 0)

    def _on_preset_chosen(self, index):
        self.btn_delete_preset.setEnabled(index > 0)
        if index > 0:
            self.apply_preset(self.preset_combo.itemText(index))

    def apply_preset(self, name: str) -> None:
        """Replaces the ticked fields with the preset's, for the scripts of this game that it names (same full
        name, else the same class name)."""
        preset = self._load_presets().get(name)
        if preset is None:
            return
        selections, missing, dropped = resolve_preset(preset, self._groups, self._fields_of)
        self._selections = {s: list(p) for s, p in selections.items()}
        for row in range(self.script_model.rowCount()):
            item = self.script_model.item(row, 0)
            item.setCheckState(Qt.CheckState.Checked if item.text() in selections else Qt.CheckState.Unchecked)
        if selections:
            first = next(iter(selections))
            if self._current_script in selections:
                first = self._current_script
            self._select_script_row(first)
            if first == self._current_script:
                self._fill_tree(first)
        elif self._current_script is not None:
            self._fill_tree(self._current_script)
        self._update_scope()
        found = len(selections)
        text = (tr("Набор «{name}»: {scripts}", name=name, scripts=trn(found, "{n} скрипт", "{n} скрипта", "{n} скриптов"))
                if found
                else tr("Набор «{name}»: его скриптов в этой игре нет", name=name))
        if missing and found:
            text += "; " + tr("нет в этой игре: {count}", count=len(missing))
        if dropped:
            text += "; " + tr("полей, которых у скриптов уже нет: {dropped}", dropped=dropped)
        self.status_label.setText(text)

    def _save_preset(self):
        chosen = self._chosen()
        if not chosen:
            return
        current = self.preset_combo.currentText() if self.preset_combo.currentIndex() > 0 else ""
        name, ok = QInputDialog.getText(self, tr("Сохранить набор"), tr("Название набора:"), text=current)
        name = name.strip()
        if not ok or not name:
            return
        presets = self._load_presets()
        if name in presets and name != current:
            answer = QMessageBox.question(self, tr("Сохранить набор"), tr("Набор «{name}» уже есть. Заменить его?", name=name))
            if answer != QMessageBox.StandardButton.Yes:
                return
        presets[name] = chosen
        self._store_presets(presets)
        self._fill_presets(select=name)
        self.status_label.setText(tr("Набор «{name}» сохранён", name=name))

    def _delete_preset(self):
        if self.preset_combo.currentIndex() <= 0:
            return
        name = self.preset_combo.currentText()
        answer = QMessageBox.question(self, tr("Удалить набор"), tr("Удалить набор «{name}»?", name=name))
        if answer != QMessageBox.StandardButton.Yes:
            return
        presets = self._load_presets()
        presets.pop(name, None)
        self._store_presets(presets)
        self._fill_presets()
        self.status_label.setText(tr("Набор «{name}» удалён", name=name))

    # --- building ---

    def _on_build_clicked(self):
        if self._worker is not None and self._worker.isRunning():
            self._cancel = True
            self.status_label.setText(tr("Отмена…"))
            return
        chosen = self._chosen()
        if not chosen:
            return
        jobs = [(name, paths, self._groups[name]) for name, paths in chosen.items()]
        total = sum(len(items) for _n, _p, items in jobs)
        self._cancel = False

        def work(report_progress):
            """-> [(script, paths, rows, row_items, failed)] in list order, or None when cancelled."""
            tables, done, last = [], 0, 0.0
            thread = QThread.currentThread()
            for name, paths, items in jobs:
                rows, row_items, failed = [], [], 0
                for item in items:
                    # «Отмена»/Esc/closing, or the main window's teardown (requestInterruption) before it
                    # releases the loaded files
                    if self._cancel or thread.isInterruptionRequested():
                        return None
                    done += 1
                    now = time.monotonic()
                    if now - last > 0.15:
                        last = now
                        report_progress("", done, total)
                    object_rows = _object_rows(item, paths)
                    if object_rows is None:
                        failed += 1
                        continue
                    rows.extend(object_rows)
                    row_items.extend([item] * len(object_rows))
                tables.append((name, list(paths), rows, row_items, failed))
            return tables

        self.btn_build.setText(tr("Отмена"))
        self.btn_csv.setEnabled(False)
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText(tr("Чтение объектов…"))
        self._worker = BackgroundWorker(work, parent=self)
        self._worker.progress_signal.connect(lambda _p, cur, tot: self.progress.setValue(cur))
        self._worker.succeeded_signal.connect(self._on_tables_built)
        self._worker.failed_signal.connect(self._on_build_failed)
        self._worker.start()

    def _end_build(self):
        self.progress.hide()
        self.btn_build.setText(tr("Построить таблицы"))
        self._update_scope()

    def _on_tables_built(self, tables):
        self._end_build()
        if tables is None:
            self.status_label.setText(tr("Отменено."))
            return
        self.result_tabs.clear()
        for name, paths, rows, items, failed in tables:
            tab = _ResultTab(name, paths, rows, items, failed)
            tab.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tab.customContextMenuRequested.connect(self._result_menu)
            # double-click edits the object, as in the main table (user request)
            tab.doubleClicked.connect(lambda index, t=tab: self._edit_object(t, _item_for(t, index)))
            tab.proxy.hide_blank = self.chk_hide_blank.isChecked()
            tab.proxy.setFilterFixedString(self.table_filter.text())
            index = self.result_tabs.addTab(tab, self._tab_title(tab))
            self.result_tabs.setTabToolTip(index, name)
        self.btn_csv.setEnabled(any(rows for _n, _p, rows, _i, _f in tables))
        self._show_counts()

    @staticmethod
    def _tab_title(tab) -> str:
        # the class name only: the row count is in the status line (it was shown twice — user report)
        return tab.script.rsplit('.', 1)[-1]

    def _on_build_failed(self, message):
        self._end_build()
        self.status_label.setText(message)

    def current_tab(self):
        tab = self.result_tabs.currentWidget()
        return tab if isinstance(tab, _ResultTab) else None

    def _show_counts(self):
        tab = self.current_tab()
        if tab is None:
            return
        shown, total = tab.proxy.rowCount(), tab.model_.rowCount()
        text = tr("Строк: {shown}", shown=shown) if shown == total else tr("Строк: {shown} из {total}", shown=shown, total=total)
        if tab.failed:
            text += ". " + tr("Не прочитано объектов: {failed}", failed=tab.failed)
        self.status_label.setText(text)

    def _on_hide_blank_toggled(self, on):
        app_settings().setValue(_HIDE_BLANK_KEY, on)
        for k in range(self.result_tabs.count()):
            self.result_tabs.widget(k).proxy.set_hide_blank(on)
        self._show_counts()

    def _apply_filter(self, text):
        for k in range(self.result_tabs.count()):
            self.result_tabs.widget(k).proxy.setFilterFixedString(text)
        self._show_counts()

    # --- copy / CSV ---

    def _selected_text(self) -> str:
        tab = self.current_tab()
        indexes = tab.selectionModel().selectedIndexes() if tab is not None else []
        if not indexes:
            return ""
        cells = {(idx.row(), idx.column()): idx.data() or "" for idx in indexes}
        rows = sorted({r for r, _c in cells})
        cols = sorted({c for _r, c in cells})

        def cell(text):
            # texts with line breaks (translations often have them): quoted, as Excel expects when pasting
            if any(ch in text for ch in '\t\n\r"'):
                return '"' + text.replace('"', '""') + '"'
            return text

        return "\n".join("\t".join(cell(cells.get((r, c), "")) for c in cols) for r in rows)

    def _copy_selection(self):
        text = self._selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def _result_menu(self, pos):
        """Copy the clicked value / the selected rows; edit the object's data (also: double-click; the main
        table's editor — its rows here are refreshed after the edit); go to the object in the main table."""
        tab = self.current_tab()
        index = tab.indexAt(pos) if tab is not None else QModelIndex()
        if not index.isValid():
            return
        menu = self._build_result_menu(tab, index)
        menu.exec(tab.viewport().mapToGlobal(pos))
        menu.deleteLater()        # a per-use child of the window: not left behind (with its Ctrl+C action) after closing

    def _build_result_menu(self, tab, index) -> QMenu:
        item = _item_for(tab, index)
        several = len(tab.selectionModel().selectedRows()) > 1
        # the same icons as the other menus: copy, the pencil for editing, the object's type icon for going to it
        # the user's order: edit | go to the object | copy
        menu = QMenu(self)
        menu.addAction(get_action_icon("edit"), tr("Отредактировать данные\tДвойной щелчок"),   # \t: a hint only
                       lambda: self._edit_object(tab, item))
        menu.addSeparator()
        menu.addAction(get_type_icon("MonoBehaviour"), tr("Перейти к объекту"), lambda: self._go_to_object(item))
        menu.addSeparator()
        menu.addAction(get_action_icon("copy"), tr("Копировать значение"), lambda: self._copy_value(index))
        act_rows = menu.addAction(get_action_icon("copy"), tr("Копировать строки") if several else tr("Копировать строку"),
                                  self._copy_selection)
        act_rows.setShortcut(QKeySequence(QKeySequence.StandardKey.Copy))
        return menu

    @staticmethod
    def _copy_value(index):
        """The one clicked cell (with whole rows selected, Ctrl+C copies whole rows)."""
        QApplication.clipboard().setText(index.data() or "")

    def _go_to_object(self, item):
        """Selects the object's row in the main table and brings the main window forward."""
        if item is None or self.main_window is None:
            return
        self.main_window._jump_to_object(item["obj_ref"])
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _edit_object(self, tab, item):
        """The main table's «Отредактировать данные» (modal editor); then this object's rows are read again —
        a changed list can mean more or fewer rows."""
        if item is None or self.main_window is None:
            return
        self.main_window.object_actions.open_json_editor_dialog(item)
        new_rows = _object_rows(item, tab.paths)
        if new_rows is None:
            return
        tab.model_.replace_object(item, new_rows)
        self.result_tabs.setTabText(self.result_tabs.indexOf(tab), self._tab_title(tab))
        self._show_counts()

    def _save_csv(self):
        tab = self.current_tab()
        if tab is None:
            return
        default = f"{tab.script.rsplit('.', 1)[-1]}.csv"
        path, _ = QFileDialog.getSaveFileName(self, tr("Сохранить таблицу"), default, tr("Таблица CSV (*.csv)"))
        if not path:
            return
        try:
            self.write_csv(path)
        except OSError as e:
            self.status_label.setText(tr("Не удалось сохранить: {error}", error=e))
            return
        self.status_label.setText(tr("Сохранено: {path}", path=path))

    def write_csv(self, path) -> int:
        """The open tab as shown (filter and sort applied): UTF-8 with BOM, ';'. Returns the number of rows written."""
        tab = self.current_tab()
        proxy, cols = tab.proxy, tab.model_.columnCount()
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(tab.model_.headers)
            for r in range(proxy.rowCount()):
                writer.writerow([proxy.index(r, c).data() or "" for c in range(cols)])
        return proxy.rowCount()

    # --- keys / closing ---

    def keyPressEvent(self, event):
        tab = self.current_tab()
        if event.matches(QKeySequence.StandardKey.Copy) and tab is not None and tab.hasFocus():
            self._copy_selection()
            return
        if event.key() == Qt.Key.Key_Escape and self._worker is not None and self._worker.isRunning():
            self._on_build_clicked()                     # Esc cancels a build instead of closing the window
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self._stop_workers()
        super().closeEvent(event)

    def reject(self):
        self._stop_workers()
        super().reject()

    def _stop_workers(self):
        self._cancel = True
        for flag in self._sample_cancel.values():
            flag[0] = True
        for worker in (self._worker, self._list_worker, *self._sample_workers):
            if worker is not None and worker.isRunning():
                worker.wait(15000)
