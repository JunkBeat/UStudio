"""«Окружение» tab of the left panel: the loaded game's files as a tree (folders -> files -> what a bundle holds),
facts about the selected file under it, and a right-click menu (show its objects in the table, export them, open
the archive viewer, Explorer, copy the path). The tree itself comes from core.environment_tree; this widget only
draws it and emits what the user asked for — MainWindow does the work (main_environment.py).

Rows are created lazily (a node's children on its first expansion: PUSS! has ~500 files, Lego Party thousands).
The tree holds references to the game's UnityPy files: `clear()` must run before they are closed (MainWindow's
teardown points, next to the usage index)."""
from core.i18n import tr
import html

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import (
    QLabel, QMenu, QScrollArea, QSplitter, QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import environment_tree as et
from details_view import breakable
from gui_common import show_copied_notice
from type_icons import get_action_icon

_NODE_ROLE = Qt.ItemDataRole.UserRole + 1
_POPULATED_ROLE = Qt.ItemDataRole.UserRole + 2
_CHANGED_MARK = " •"


class EnvironmentView(QWidget):
    show_objects_requested = pyqtSignal(list)          # [SerializedFile]
    export_requested = pyqtSignal(list, str)           # [SerializedFile], mode ("converted"/"json_dump"/"raw")
    open_archive_requested = pyqtSignal(str)           # the bundle's path
    reveal_requested = pyqtSignal(str)                 # a file/folder path for Explorer

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roots = []
        self._icons = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel(tr("Загрузите игру — здесь появятся её файлы."))
        self.placeholder.setObjectName("MutedCaption")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemExpanded.connect(self._populate)
        self.tree.itemActivated.connect(self._on_activated)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._show_facts(self.node_of(cur)))
        self.splitter.addWidget(self.tree)

        self.facts_label = QLabel()
        self.facts_label.setWordWrap(True)
        self.facts_label.setTextFormat(Qt.TextFormat.RichText)
        self.facts_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.facts_label.setContentsMargins(6, 6, 6, 6)
        self.facts_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.facts_label.customContextMenuRequested.connect(self._show_facts_menu)
        facts_scroll = QScrollArea()
        facts_scroll.setWidgetResizable(True)
        facts_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        facts_scroll.setWidget(self.facts_label)
        self.splitter.addWidget(facts_scroll)
        self.splitter.setSizes([2000, 1000])         # kept proportionally: a third for the facts (a path wraps)
        layout.addWidget(self.splitter)
        self._facts = []
        self.clear()

    # --- content ---

    def set_environment(self, env) -> None:
        """Builds the tree of `env`'s loaded files (cheap: in-memory data only)."""
        self.clear()
        roots = et.build_tree(env) if env is not None else []
        if not roots:
            return
        self._roots = roots
        self._common = et.common_versions(roots)
        self.placeholder.hide()
        self.splitter.show()
        for node in roots:
            self.tree.addTopLevelItem(self._make_item(node))
        if len(roots) == 1:
            self.tree.topLevelItem(0).setExpanded(True)     # the game's own folder is the obvious start
        self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def clear(self) -> None:
        """Drops every reference to the game's files (call before they are closed)."""
        self.tree.clear()
        self._roots = []
        self._common = ("", "")
        self._facts = []
        self.facts_label.setText("")
        self.splitter.hide()
        self.placeholder.show()

    def has_content(self) -> bool:
        return bool(self._roots)

    def refresh_marks(self) -> None:
        """Re-reads «изменён» for the rows already created (after an edit/import) and the shown facts."""
        def walk(item):
            node = self.node_of(item)
            if node is not None:
                self._apply_mark(item, node)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        self._show_facts(self.node_of(self.tree.currentItem()))

    @staticmethod
    def node_of(item):
        return item.data(0, _NODE_ROLE) if item is not None else None

    def _make_item(self, node) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setData(0, _NODE_ROLE, node)
        item.setIcon(0, self._kind_icon(node.kind))
        self._apply_mark(item, node)
        if node.children:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        return item

    def _kind_icon(self, kind):
        """One shared QIcon per pixmap: on Windows every standardIcon() call builds a NEW icon holding the shell
        icon at every size up to 256 px (~1.35 MB) — one per row made expanding Phonopolis' tree cost ~450 MB."""
        pixmap = {
            et.FOLDER: QStyle.StandardPixmap.SP_DirIcon,
            et.BUNDLE: QStyle.StandardPixmap.SP_DriveHDIcon,
            et.WEB: QStyle.StandardPixmap.SP_DriveHDIcon,
        }.get(kind, QStyle.StandardPixmap.SP_FileIcon)
        icon = self._icons.get(pixmap)
        if icon is None:
            icon = self._icons[pixmap] = self.style().standardIcon(pixmap)
        return icon

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.StyleChange:
            self._icons = {}
        super().changeEvent(event)

    def _apply_mark(self, item, node) -> None:
        changed = node.is_changed()
        item.setText(0, node.name + (_CHANGED_MARK if changed else ""))
        font = item.font(0)
        font.setBold(changed)
        item.setFont(0, font)
        if node.is_dependency() or node.kind == et.OTHER:
            # muted: loaded only for references, or a non-Unity file the folder load picked up (.json, boot.config)
            item.setForeground(0, self.palette().color(self.palette().ColorRole.PlaceholderText))
        tip = [et.KIND_TEXT.get(node.kind, "")]
        if changed:
            tip.append(tr("Изменён — изменения ещё не сохранены"))
        if node.is_dependency():
            tip.append(tr("Загружен только для ссылок других файлов"))
        from helpers import wrap_tooltip
        item.setToolTip(0, wrap_tooltip("\n".join(t for t in tip if t)))

    def _populate(self, item) -> None:
        if item.data(0, _POPULATED_ROLE):
            return
        item.setData(0, _POPULATED_ROLE, True)
        node = self.node_of(item)
        for child in getattr(node, "children", []):
            item.addChild(self._make_item(child))

    # --- facts ---

    def _show_facts(self, node) -> None:
        if node is None:
            self._facts = []
            self.facts_label.setText("")
            return
        self._facts = et.file_facts(node, self._common)
        # one «Label: value» line each (a two-column table gave the labels half the width)
        muted = self.palette().color(self.palette().ColorRole.PlaceholderText).name()
        rows = "".join(
            f"<div style='margin-top:2px;'><span style='color:{muted};'>{html.escape(label)}:</span> "
            f"{html.escape(breakable(str(value)))}</div>"
            for label, value in self._facts
        )
        self.facts_label.setText(f"<b>{html.escape(breakable(node.name))}</b>{rows}")

    def facts_text(self) -> str:
        return "\n".join(f"{label}: {value}" for label, value in self._facts)

    def _show_facts_menu(self, pos) -> None:
        if not self._facts:
            return
        menu = QMenu(self)
        act = QAction(get_action_icon("copy"), tr("Копировать сведения"), menu)
        act.triggered.connect(self._copy_facts)
        menu.addAction(act)
        menu.exec(self.facts_label.mapToGlobal(pos))
        menu.deleteLater()

    def _copy_facts(self) -> None:
        QGuiApplication.clipboard().setText(self.facts_text())
        show_copied_notice(self.facts_label)

    # --- actions ---

    def _on_activated(self, item, _column) -> None:
        node = self.node_of(item)
        files = et.serialized_files(node) if node is not None else []
        if node is not None and node.kind != et.FOLDER and files:
            self.show_objects_requested.emit(files)

    def build_menu(self, node) -> QMenu:
        """The right-click menu for `node` (separate from _show_context_menu so tests can read it)."""
        menu = QMenu(self)
        files = et.serialized_files(node)
        if files:
            # the hint after a tab, as the table menu's «Отредактировать данные\tEnter»; a folder opens on double-click
            text = tr("Показать объекты") if node.kind == et.FOLDER else tr("Показать объекты\tДвойной щелчок")
            act_show = QAction(get_action_icon("view"), text, menu)
            act_show.triggered.connect(lambda: self.show_objects_requested.emit(files))
            menu.addAction(act_show)
            menu.addSeparator()
            act_export = QAction(get_action_icon("export"), tr("Экспортировать объекты..."), menu)
            act_export.triggered.connect(lambda: self.export_requested.emit(files, "converted"))
            menu.addAction(act_export)
            export_as = menu.addMenu(tr("Экспортировать объекты как"))
            for label, mode in ((tr("Конвертированный"), "converted"), (tr("JSON дамп"), "json_dump"), (tr("Raw дамп"), "raw")):
                act = QAction(label, export_as)
                act.triggered.connect(lambda checked=False, m=mode: self.export_requested.emit(files, m))
                export_as.addAction(act)
            menu.addSeparator()
        if node.kind == et.BUNDLE and node.path:
            act_archive = QAction(tr("Открыть в просмотре архива"), menu)
            act_archive.triggered.connect(lambda: self.open_archive_requested.emit(node.path))
            menu.addAction(act_archive)
        path = et.container_path(node)
        if path:
            act_reveal = QAction(get_action_icon("explorer"), tr("Показать в проводнике"), menu)
            act_reveal.triggered.connect(lambda: self.reveal_requested.emit(path))
            menu.addAction(act_reveal)
            act_copy = QAction(get_action_icon("copy"), tr("Копировать путь"), menu)
            act_copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(path))
            menu.addAction(act_copy)
        return menu

    def _show_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        node = self.node_of(item)
        if node is None:
            return
        menu = self.build_menu(node)
        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(pos))
        menu.deleteLater()
