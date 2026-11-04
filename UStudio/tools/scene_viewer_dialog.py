"""Scene Viewer (Инструменты -> Просмотр сцены) — a UABEA-style "GameObject
Viewer": the scene hierarchy (GameObject/Transform tree) of one loaded file in
the left pane, and the existing "Tree View" component inspector
(gui_widgets.ObjectStructureTree — unmodified logic, just fed multiple root
objects at once via its new set_objects()) on the right, showing every
component attached to whichever GameObject is selected on the left.

Modeless (like TextSearchDialog/CabBrowserDialog — same "keep it around,
re-show() rather than reconstruct" singleton pattern, wired up the same way in
MainWindow.open_scene_viewer()).

A file's hierarchy is built in a background worker (a big scene — Truck-kun level3, 88k Transforms — took
~4 s on the GUI thread, on every open) and KEPT for the session (`_KEEP_FILES` most recent files): reopening
the window or switching back to a file shows it at once. A kept hierarchy is dropped when one of that
file's Transforms/GameObjects is edited (`object_patched`); a new load or an overwrite save destroys the
whole window (main_save_flow's teardown, which also stops the worker: it is a child QThread)."""

from core.i18n import tr
from collections import OrderedDict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from core.progress import OperationCancelled
from core.scene_hierarchy import build_scene_hierarchy, resolve_gameobject_components
from gui_widgets import ObjectStructureTree, SceneHierarchyTree
from gui_workers import BackgroundWorker
import theme
from helpers import wrap_tooltip
from app_settings import app_settings


_SCENE_TYPES = ("Transform", "RectTransform", "GameObject")


class SceneViewerDialog(QDialog):
    _KEEP_FILES = 4  # built hierarchies kept (level3 of Truck-kun: ~90k SceneNodes)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle(tr("Просмотр сцены"))
        self.setModal(False)
        # source file name -> its SerializedFile (assets_file) — the pool
        # highlight_object()/the "Файл:" combo pick from. Built by
        # MainWindow.open_scene_viewer() from the main table's own rows (every
        # row already carries obj_ref.assets_file), not by walking self.env
        # separately — reuses exactly what's already loaded, no new file-
        # enumeration mechanism needed.
        self._source_files = {}
        self._current_source = None
        # id(assets_file) -> (assets_file, roots); the file is kept in the entry so a reused id() can never
        # hand out another file's hierarchy.
        self._built = OrderedDict()
        self._shown_file = None          # the assets_file whose hierarchy the tree shows now
        self._worker = None
        self._build_gen = 0              # a finished build is used only if it is still the latest one
        self._pending_highlight = None   # (source, path_id) to select once the build in progress ends
        self._init_ui()
        self.resize(900, 600)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        # Real reported issue: zero margins meant btn_search_next sat flush
        # against the splitter handle, with no breathing room at all — a small
        # right margin here (mirrored as a left margin on right_layout below,
        # for the same reason on the other side of the handle) instead of the
        # previous 0 on every side.
        left_layout.setContentsMargins(0, 0, 6, 0)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("Поиск по имени..."))
        self.search_input.returnPressed.connect(self._do_search)
        self.btn_search_next = QPushButton(tr("Далее"))
        self.btn_search_next.clicked.connect(self._do_search)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.btn_search_next)
        left_layout.addLayout(search_row)

        self.search_status_label = QLabel("")
        self.search_status_label.setStyleSheet("color: gray;")
        # Real reported request: the "Иерархия сцены"/"Компоненты" header
        # labels that used to sit above each pane took up vertical space
        # without adding information the panes' own contents/tooltips didn't
        # already make obvious — dropped in favor of giving that space back to
        # the trees themselves. search_status_label stays (it's stateful
        # feedback, "Не найдено") but hidden (not just empty-text) whenever
        # there's nothing to say — an empty QLabel still reserves its own line
        # height in the layout, which is exactly the "empty space under the
        # search bar" a real report flagged once the static labels above it
        # were removed and this became the only thing left in that gap.
        self.search_status_label.hide()
        left_layout.addWidget(self.search_status_label)

        # «Строится иерархия сцены… N %» while a file's hierarchy is built in the background; hidden otherwise.
        self.build_status_label = QLabel("")
        self.build_status_label.setStyleSheet("color: gray;")
        self.build_status_label.setWordWrap(True)
        self.build_status_label.hide()
        left_layout.addWidget(self.build_status_label)

        self.hierarchy_tree = SceneHierarchyTree()
        self.hierarchy_tree.object_selected.connect(self._on_object_selected)
        self.hierarchy_tree.jump_requested.connect(self._on_jump_requested)
        self.hierarchy_tree.edit_requested.connect(self._on_hierarchy_edit_requested)
        left_layout.addWidget(self.hierarchy_tree, 1)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 0, 0, 0)

        # Same "Развернуть всё"/"Свернуть всё" toolbar the main Preview tab's
        # own Tree View already has — real reported gap: ObjectStructureTree
        # already implements both (expand_all_branches()/collapse_all_
        # branches(), see gui_widgets.py — deliberately leaving PPtr rows
        # collapsed so expanding everything can't trigger an unbounded chain
        # of resolves), this dialog's Components pane just never exposed a
        # way to call them.
        components_toolbar = QHBoxLayout()
        btn_expand_all = QPushButton(tr("Развернуть всё"))
        btn_expand_all.setToolTip(
            tr("Разворачивает все ветки, кроме ссылок на другие объекты — их разворачивание загружает эти "
               "объекты.")
        )
        btn_collapse_all = QPushButton(tr("Свернуть всё"))
        btn_expand_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_collapse_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        components_toolbar.addWidget(btn_expand_all)
        components_toolbar.addWidget(btn_collapse_all)
        components_toolbar.addStretch(1)
        # The same «Перенос строк» as the main Tree view, and the same saved setting (the two panes
        # are one widget class): read when the dialog is built, written when it is toggled here.
        self.chk_word_wrap = QCheckBox(tr("Перенос строк"))
        self.chk_word_wrap.setToolTip(wrap_tooltip(
            tr("Длинные строки дерева переносятся по ширине панели, без горизонтальной прокрутки.")))
        self.chk_word_wrap.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        components_toolbar.addWidget(self.chk_word_wrap)
        right_layout.addLayout(components_toolbar)

        self.components_tree = ObjectStructureTree()
        self.components_tree.apply_theme_colors(theme.get_colors(theme.load_saved_theme_name()))
        wrap_on = app_settings().value("tree_view/word_wrap", False, type=bool)
        self.chk_word_wrap.setChecked(wrap_on)
        self.components_tree.set_word_wrap(wrap_on)
        self.chk_word_wrap.toggled.connect(self._on_word_wrap_toggled)
        btn_expand_all.clicked.connect(self.components_tree.expand_all_branches)
        btn_collapse_all.clicked.connect(self.components_tree.collapse_all_branches)
        # Same reuse as the main Preview tab's own structure tree — a
        # component's own PPtr fields (m_GameObject, m_Father, a
        # MonoBehaviour's m_Script, ...) get the identical "jump to the
        # referenced object in the main table" / "edit its data" actions,
        # routed straight to MainWindow's own already-built handlers rather
        # than reimplementing either here.
        self.components_tree.jump_requested.connect(self._on_jump_requested)
        self.components_tree.edit_requested.connect(self.main_window._edit_object_from_tree)
        right_layout.addWidget(self.components_tree, 1)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 500])
        layout.addWidget(splitter, 1)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(QLabel(tr("Файл:")))
        self.file_combo = QComboBox()
        self.file_combo.currentIndexChanged.connect(self._on_file_changed)
        bottom_row.addWidget(self.file_combo, 1)
        layout.addLayout(bottom_row)

    def _on_word_wrap_toggled(self, checked: bool) -> None:
        self.components_tree.set_word_wrap(checked)
        app_settings().setValue("tree_view/word_wrap", checked)

    # --- file selection / hierarchy building ---

    def set_available_files(self, source_to_assets_file: dict, select: str = None) -> None:
        """Rebuilds the "Файл:" dropdown — called every time
        MainWindow.open_scene_viewer() opens/re-shows this dialog, since the
        set of loaded files can genuinely differ from the last time it was
        open (a fresh load happened, or the CAB browser pulled in a new
        entry). Shows `select` when given (the file of the GameObject the
        window was opened for — so only that file is built), else keeps the
        previously-selected file if it's still present, else the first file
        alphabetically. A file whose hierarchy is already shown or kept is not
        built again."""
        previous = self._current_source
        self._source_files = dict(source_to_assets_file)
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        for source in sorted(self._source_files.keys()):
            self.file_combo.addItem(source)
        self.file_combo.blockSignals(False)
        if not self._source_files:
            self._cancel_build()
            self._current_source = None
            self._shown_file = None
            self.hierarchy_tree.set_roots([], None)
            self.components_tree.clear_object()
            return
        index = self.file_combo.findText(select) if select else -1
        if index < 0:
            index = self.file_combo.findText(previous) if previous else -1
        self.file_combo.blockSignals(True)
        self.file_combo.setCurrentIndex(index if index >= 0 else 0)
        self.file_combo.blockSignals(False)
        self._load_current_file()

    def _on_file_changed(self, index: int) -> None:
        self._load_current_file()

    def _load_current_file(self) -> None:
        source = self.file_combo.currentText()
        assets_file = self._source_files.get(source)
        self._current_source = source or None
        if assets_file is None:
            self._cancel_build()
            self._shown_file = None
            self.components_tree.clear_object()
            self.hierarchy_tree.set_roots([], source)
            return
        if assets_file is self._shown_file and self._kept(assets_file) is not None and self._worker is None:
            return  # already on screen: keep the expanded rows and the selection
        self.components_tree.clear_object()
        roots = self._kept(assets_file)
        if roots is not None:
            self._cancel_build()
            self._show(assets_file, source, roots)
            return
        self._start_build(assets_file, source)

    def _kept(self, assets_file):
        entry = self._built.get(id(assets_file))
        if entry is None or entry[0] is not assets_file:
            return None
        self._built.move_to_end(id(assets_file))
        return entry[1]

    def _keep(self, assets_file, roots) -> None:
        self._built[id(assets_file)] = (assets_file, roots)
        self._built.move_to_end(id(assets_file))
        while len(self._built) > self._KEEP_FILES:
            self._built.popitem(last=False)

    def _show(self, assets_file, source, roots) -> None:
        self.build_status_label.hide()
        self._shown_file = assets_file
        self.hierarchy_tree.set_roots(roots, source)
        pending, self._pending_highlight = self._pending_highlight, None
        if pending is not None and pending[0] == source:
            self.hierarchy_tree.highlight_object(*pending)

    def _start_build(self, assets_file, source) -> None:
        """Builds `source`'s hierarchy in a worker; the tree is empty with a status line meanwhile. A build
        still running for another file is asked to stop (it checks every 1000 objects) and its result is
        ignored."""
        self._cancel_build()
        self._build_gen += 1
        gen = self._build_gen
        self._shown_file = None
        self.hierarchy_tree.set_roots([], source)
        self.build_status_label.setText(tr("Строится иерархия сцены…"))
        self.build_status_label.show()

        worker = None

        def fn(report):
            return build_scene_hierarchy(
                assets_file, should_cancel=worker.isInterruptionRequested,
                progress=lambda done, total: report("", done, total), paced=True)

        worker = BackgroundWorker(fn, parent=self)
        self._worker = worker
        worker.progress_signal.connect(lambda _p, done, total, g=gen: self._on_build_progress(g, done, total))
        worker.succeeded_signal.connect(
            lambda roots, g=gen, f=assets_file, s=source: self._on_build_done(g, f, s, roots))
        worker.failed_signal.connect(lambda msg, g=gen: self._on_build_failed(g, msg))
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _cancel_build(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()
            self._worker = None
        self._build_gen += 1
        self.build_status_label.hide()

    def _on_build_progress(self, gen, done, total) -> None:
        if gen == self._build_gen and total:
            self.build_status_label.setText(tr("Строится иерархия сцены… {value} %", value=done * 100 // total))

    def _on_build_done(self, gen, assets_file, source, roots) -> None:
        if gen != self._build_gen:
            return
        self._worker = None
        self._keep(assets_file, roots)
        self._show(assets_file, source, roots)

    def _on_build_failed(self, gen, message) -> None:
        if gen != self._build_gen:
            return
        self._worker = None
        self._pending_highlight = None
        if message == OperationCancelled.__name__:
            self.build_status_label.hide()
            return
        self.build_status_label.setText(tr("Не удалось построить иерархию сцены: {message}", message=message))
        self.build_status_label.show()

    @staticmethod
    def _on_worker_finished(worker) -> None:
        worker.deleteLater()

    def object_patched(self, obj) -> None:
        """An object was edited/imported (object_actions._refresh_row_after_patch): a kept hierarchy of its
        file is dropped if the object is part of one, so the next showing of that file reads it again (as
        every open did before hierarchies were kept). The tree on screen stays as it is until then."""
        if getattr(getattr(obj, "type", None), "name", None) not in _SCENE_TYPES:
            return
        assets_file = getattr(obj, "assets_file", None)
        if assets_file is not None and self._kept(assets_file) is not None:
            del self._built[id(assets_file)]
            if assets_file is self._shown_file:
                self._shown_file = None

    # --- selection / components ---

    def _on_object_selected(self, game_object_obj) -> None:
        self.components_tree.set_objects(resolve_gameobject_components(game_object_obj))

    def _on_hierarchy_edit_requested(self, game_object_obj) -> None:
        """Right-click "Отредактировать данные" on a GameObject — the same modal
        data editor the Components pane and the table use; afterwards the row's
        label and the components list are refreshed (an edit may have renamed
        the GameObject or changed its m_Component list)."""
        self.main_window._edit_object_from_tree(game_object_obj)
        self.hierarchy_tree.refresh_item_name(game_object_obj)
        current = self.hierarchy_tree.currentItem()
        node = current.data(0, self.hierarchy_tree._NODE_ROLE) if current is not None else None
        if node is not None and node.game_object_obj is game_object_obj:
            self._on_object_selected(game_object_obj)

    def _on_jump_requested(self, obj) -> None:
        self.main_window._jump_to_object(obj)
        self.main_window.raise_()
        self.main_window.activateWindow()

    # --- search ---

    def _do_search(self) -> None:
        text = self.search_input.text()
        if not text.strip():
            self.search_status_label.hide()
            return
        found = self.hierarchy_tree.find_next(text)
        self.search_status_label.setText("" if found else tr("Не найдено"))
        self.search_status_label.setVisible(not found)

    # --- external entry point (toolbar button) ---

    def highlight_object(self, source_name: str, path_id: int) -> None:
        """Selects source_name in the file dropdown (switching to its
        hierarchy if it isn't already showing) and selects+scrolls to the
        GameObject matching path_id within it — at once, or when the build in
        progress ends. No-op (leaves whatever was already showing alone) if
        source_name was never in the set passed to set_available_files() — the
        caller (MainWindow.open_scene_viewer) already logs a clear message for
        that case."""
        if source_name not in self._source_files:
            return
        index = self.file_combo.findText(source_name)
        if index < 0:
            return
        self._pending_highlight = (source_name, path_id)
        if self.file_combo.currentIndex() != index:
            self.file_combo.setCurrentIndex(index)  # shows a kept hierarchy now, or starts its build
        if self._worker is None and self._shown_file is self._source_files.get(source_name):
            self._pending_highlight = None
            self.hierarchy_tree.highlight_object(source_name, path_id)
