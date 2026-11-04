"""Table-related widgets: the main object table view, the SDF group spacing delegate and the task-queue status button."""

from core.i18n import tr
import html as _html

from PyQt6.QtCore import QPersistentModelIndex, Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPalette, QTextDocument
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
)

from core.object_metadata import coverage_part_text
from gui_common import coverage_highlight_color


class ObjectTableView(QTableView):
    """Plain QTableView, except a selection change never scrolls (either axis)
    when the target cell is already fully on screen. Real reported bug: since
    this table can scroll horizontally (it has more columns than reliably fit —
    see main.py's no-stretch-column comment), Qt's own default QAbstractItemView
    behavior (auto-calling scrollTo(currentIndex, EnsureVisible) whenever the
    current index changes) meant simply clicking between rows could yank the
    scrollbar around — reported first for the horizontal axis ("moves left and
    right by itself"), then again for vertical ("leave vertical scrolling
    unchanged when clicking a row... uncontrollable").

    A mouse click can only ever land on a cell that's already fully visible —
    that's what made it clickable — so EnsureVisible has no legitimate reason to
    move anything for a click; skipping scrollTo() entirely whenever the target
    is already fully contained in the viewport rect keys off that fact directly,
    on both axes, rather than pinning one bar's value after letting Qt move it
    (the first, narrower fix that only addressed the horizontal report).
    Genuine off-screen navigation — arrowing past the last visible row, or
    _jump_to_object()'s setCurrentIndex() to a row that isn't currently shown —
    still scrolls normally, since that target is NOT already fully visible and
    this falls through to the real implementation."""

    select_all_requested = pyqtSignal()  # emitted by Ctrl+A instead of ever
    # calling the real selectAll() — see that method's own docstring. Purely
    # informational (e.g. so MainWindow can update the preview panel) —
    # select_all_active below is the actual state, owned by this view since
    # mousePressEvent() needs to check it synchronously on every click.

    def __init__(self, parent=None):
        super().__init__(parent)
        self._select_all_active = False
        self._in_mouse_press = False
        # The cell the mouse last clicked (see scrollTo); forgotten on the next key press.
        self._clicked_index = QPersistentModelIndex()
        # Real follow-up request, after selectAll() was fixed to a lightweight flag instead of a
        # real Qt selection (see that method's own docstring for why the real one is too slow at
        # this row count): a virtual select-all should still LOOK selected, not just say so in the
        # status bar. This paints it without ever touching QItemSelectionModel — see
        # _SelectAllHighlightDelegate's own docstring for why that keeps it just as cheap.
        self.setItemDelegate(_SelectAllHighlightDelegate(self))

    @property
    def select_all_active(self) -> bool:
        return self._select_all_active

    @select_all_active.setter
    def select_all_active(self, value: bool) -> None:
        value = bool(value)
        if value == self._select_all_active:
            return
        self._select_all_active = value
        # Every call site just assigns this flag directly (there are several, scattered across
        # main.py/object_actions.py — a filter change, a real click, a fresh load, ...); a property
        # setter is what lets a repaint happen automatically at every one of them without having to
        # remember to add it by hand each time. Cheap regardless of table size: paint() only ever
        # runs for cells Qt is already about to draw, i.e. bounded by the VIEWPORT's row count, not
        # the table's — the same reason a plain repaint is already cheap at any row count.
        self.viewport().update()

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible) -> None:
        rect = self.visualRect(index)
        viewport = self.viewport().rect()
        if viewport.contains(rect):
            return
        # A click on a cell that is only PARTLY visible (typically the last visible
        # column, cut off by the viewport edge) used to make Qt scroll it fully into
        # view — the "scrollbar jumps right when I click the last column" report. A
        # click has a target the user can already see, so it never scrolls; keyboard
        # navigation and programmatic jumps (not in a mouse press) still do.
        if self._in_mouse_press and viewport.intersects(rect):
            return
        # ...and the report came back: Qt's mousePressEvent ALSO starts a delayed auto-scroll (double-click
        # interval + 100 ms, so a double click is not read as two clicks) whose timerEvent calls
        # scrollTo(currentIndex()) after the click handlers have returned. Any scroll request for the cell
        # the mouse clicked last is the same "a click never scrolls" case, until a key is pressed (keyboard
        # navigation onto that cell must still bring it into view).
        clicked = self._clicked_index
        # (row/column/model compared one by one: PyQt6's QPersistentModelIndex == QModelIndex is False here)
        if (clicked.isValid() and index.isValid() and clicked.model() is index.model()
                and clicked.row() == index.row() and clicked.column() == index.column()
                and viewport.intersects(rect)):
            return
        super().scrollTo(index, hint)

    def keyPressEvent(self, event) -> None:
        self._clicked_index = QPersistentModelIndex()
        super().keyPressEvent(event)

    def selectAll(self) -> None:
        """Real reported bug: Ctrl+A (bound to this by Qt's default shortcut,
        which does call this override — confirmed directly, not assumed) took
        ~1.7s measured on a 250,000-row table. Profiled (not guessed) to find
        the actual cause: it isn't QItemSelectionModel bookkeeping or the proxy
        model — it's QAbstractItemView's own selectAll() implementation
        calling this Python-implemented model's rowCount()/columnCount()
        roughly 8 times PER ROW (2 million+ PyQt boundary crossings for
        250,000 rows), confirmed identical with or without a proxy in front of
        it, and confirmed NOT fixable by making those methods themselves any
        cheaper (they're already a bare len() call — the cost is in the sheer
        NUMBER of Python/C++ round trips Qt's own C++ implementation makes,
        not what happens inside each one). A first attempt wrapping the call
        in setUpdatesEnabled(False) APPEARED to fix it (0.000s measured) but
        that measurement didn't drain the event queue far enough to catch
        where the real cost actually lands — a proper before/after comparison
        (call + full drain, both patched and unpatched) showed no real
        difference at all (1.71s vs 1.80s) once measured honestly.

        The only way to avoid this at this row count is to never call Qt's
        real selectAll() in the first place. This just flips a lightweight
        boolean (select_all_active) instead of building a real
        QItemSelectionModel selection, and bulk actions (the context menu's
        multi-export) read straight from the underlying data list via
        AdvancedFilterProxyModel.get_visible_items() when it's set, never
        touching QItemSelectionModel for the bulk case. Whatever REAL (small)
        selection existed before Ctrl+A is cleared, so the view doesn't show a
        stale partial highlight alongside the "N objects selected" message
        MainWindow shows instead of a real highlight."""
        self.clearSelection()
        self.select_all_active = True
        self.select_all_requested.emit()

    def mousePressEvent(self, event) -> None:
        """Real reported bug: right-clicking ANY row while select_all_active
        was on immediately turned it back off, showing a single-object preview
        and the regular one-row context menu instead of the bulk one. Cause:
        activating virtual select-all deliberately clears the REAL Qt
        selection (see selectAll() above), so as far as Qt's own click
        handling is concerned every row is unselected — its default
        mousePressEvent for a plain right-click on an unselected row (under
        ExtendedSelection) issues its own ClearAndSelect, which fires
        selectionChanged for real and (via MainWindow.on_selection_changed)
        turns select_all_active back off before the context menu handler ever
        runs. Skipping the base implementation for exactly this one case — a
        right-click, while select_all_active is on — stops Qt from doing that,
        without affecting anything else: a left-click still selects normally
        (and, via on_selection_changed, still ends select-all, which is
        correct — that's a real, deliberate selection change), and a
        right-click when select_all_active is already off behaves exactly as
        before. customContextMenuRequested still fires afterward regardless —
        that's Qt's separate contextMenuEvent() delivery path, not driven by
        mousePressEvent's own selection handling.

        Real reported bug: a plain click landing past the last row (or in any
        other empty margin of the viewport) has no item to act on, but Qt's
        own default ExtendedSelection behavior for a click on an invalid index
        is still ClearAndSelect — silently dropping whatever was selected (and,
        via MainWindow.on_selection_changed, resetting the whole Preview panel
        back to its welcome screen) for a click that wasn't aimed at anything.
        Skipped only for a plain, unmodified left-click with no valid index
        under it: right-click's own interaction with select_all_active is
        handled above and left untouched, and Ctrl/Shift-click keep Qt's
        normal behavior since those are deliberate selection-modifying
        gestures, not the reported complaint."""
        if event.button() == Qt.MouseButton.RightButton and self.select_all_active:
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and not self.indexAt(event.pos()).isValid()
        ):
            return
        self._pinned_click(lambda: super(ObjectTableView, self).mousePressEvent(event), event)

    def mouseReleaseEvent(self, event) -> None:
        self._pinned_click(lambda: super(ObjectTableView, self).mouseReleaseEvent(event), event)

    def _pinned_click(self, action, event) -> None:
        """Runs a mouse press/release handler with the horizontal scroll position
        pinned: whatever the click sets in motion (Qt's own scrollTo, a slot reacting
        to the selection change, ...), a click on a cell the user can already see
        never moves the table sideways. Genuine drags past the edge (Qt's
        auto-scroll timer) happen in mouseMoveEvent, not here."""
        bar = self.horizontalScrollBar()
        clicked = self.indexAt(event.pos())
        pinned = bar.value() if clicked.isValid() else None
        self._clicked_index = QPersistentModelIndex(clicked)
        self._in_mouse_press = True
        try:
            action()
        finally:
            self._in_mouse_press = False
            if pinned is not None and bar.value() != pinned:
                bar.setValue(pinned)


class _SelectAllHighlightDelegate(QStyledItemDelegate):
    """Paints every currently visible cell of ObjectTableView using the platform's normal
    "selected" look while select_all_active is on — the visible counterpart to that flag (see
    ObjectTableView.selectAll()'s own docstring: at this table's row counts, building a REAL
    QItemSelectionModel selection is what made Ctrl+A take ~1.7s, so this deliberately never does
    that). Safe to do unconditionally: paint() only ever runs for a cell Qt is actually about to
    draw on screen, so the cost is bounded by how many rows fit in the viewport, never by how many
    rows the table actually has — the same property that already makes an ordinary repaint cheap
    regardless of table size."""

    def __init__(self, view: "ObjectTableView"):
        super().__init__(view)
        self._view = view

    def paint(self, painter, option, index) -> None:
        if self._view.select_all_active:
            option = QStyleOptionViewItem(option)
            option.state |= QStyle.StateFlag.State_Selected
        super().paint(painter, option, index)


class SDFGroupSpacingDelegate(QStyledItemDelegate):
    """SDF Viewer Mode's QTreeView (main.py's sdf_tree_view) — a little extra
    vertical space ABOVE each top-level "SDF Font Pack" group row (skipping
    the very first one, which has nothing above it to separate from), so
    consecutive font packages read as distinct blocks instead of every row —
    group headers and their children alike — butting directly against the
    next with no breathing room. Matches the blank line between groups in the
    user's own Explorer-style mockup. Checked via index.parent().isValid()
    (the standard Qt way to ask "is this a top-level row") rather than
    reaching into SDFGroupModel's internals, so this stays reusable if the
    model's own node representation ever changes."""

    _GROUP_TOP_MARGIN = 8
    # Same wide join sdf_group_model._group_data/sdf_coverage.coverage_text use — matched here
    # so splitting the DisplayRole text back into "name" vs "everything after" finds the right
    # boundary, and so a row with no coverage text yet (nothing to split) just isn't touched.
    _GROUP_META_SEPARATOR = "   ·   "

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        if not index.parent().isValid() and index.row() > 0:
            size = QSize(size.width(), size.height() + self._GROUP_TOP_MARGIN)
        return size

    def paint(self, painter, option, index) -> None:
        # Real reported request: a group header row ("Roboto-Thin SDF   ·   275 chars   ·
        # Cyrillic support") read as one dense, equally-weighted run of text — the font pack's
        # actual NAME (the thing you're scanning the list for) competed for attention with the
        # coverage annotation next to it instead of standing out. Only column 0, only a
        # TOP-LEVEL row, and only once there is actually a "   ·   " to split on (nothing to
        # gain by rebuilding this for a plain name, or for any child row, which keeps the
        # ordinary fast plain-text paint below).
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if index.column() != 0 or index.parent().isValid() or self._GROUP_META_SEPARATOR not in text:
            super().paint(painter, option, index)
            return
        name, _sep, meta = text.partition(self._GROUP_META_SEPARATOR)

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        opt.text = ""  # let the style draw background/selection/branch/icon; we draw the text
        painter.save()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        # QPalette.PlaceholderText: the standard "secondary, de-emphasized text" role — already
        # themed correctly by Qt/this app's own palette in both light and dark, so no separate
        # color needs plumbing in from theme.py just for this one delegate.
        muted = opt.palette.color(QPalette.ColorRole.PlaceholderText).name()
        # The "Cyrillic support" part is the one fact worth finding at a glance: bold, and green unless the row
        # is selected (a green on the selection colour would be hard to read).
        coverage = coverage_part_text()
        green = "" if opt.state & QStyle.StateFlag.State_Selected else f" style='color:{coverage_highlight_color(opt.palette).name()};'"
        meta_html = self._GROUP_META_SEPARATOR.join(
            f"<b{green}>{_html.escape(piece)}</b>" if piece == coverage else _html.escape(piece)
            for piece in meta.split(self._GROUP_META_SEPARATOR)
        )
        html_text = f"{_html.escape(name)}<span style='color:{muted};'>{self._GROUP_META_SEPARATOR}{meta_html}</span>"
        doc = QTextDocument()
        doc.setDefaultFont(opt.font)
        doc.setDocumentMargin(0)
        doc.setHtml(html_text)
        # The item's own decoration (folder icon) is drawn by CE_ItemViewItem above, in its own
        # sub-rect to the LEFT of the text — opt.rect is the whole cell including that icon, so
        # painting at its raw topLeft() drew the name text starting underneath/behind the icon.
        # SE_ItemViewItemText is the same sub-rect the style would have used for opt.text itself.
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        # Real reported bug: this sub-rect's left edge is NOT where native item-view text is
        # actually drawn — Qt's own CE_ItemViewItem (QCommonStyle::viewItemDrawText) insets it by
        # PM_FocusFrameHMargin+1 (3px on Fusion) on both sides before calling drawText. Painting
        # flush against text_rect's own left edge — as an earlier version of this code did — put a
        # metadata-bearing header row's name 3px closer to its icon than every plain-painted row
        # (every other header, every child row), a small but real, visible inconsistency.
        h_margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, opt, opt.widget) + 1
        text_rect = text_rect.adjusted(h_margin, 0, -h_margin, 0)
        if text_rect.width() > 0:
            doc.setTextWidth(text_rect.width())
        # Real reported bug: painting at text_rect's raw top pins the text to the TOP of the row
        # instead of centering it — invisible for a normal-height row (where top and centered are
        # the same pixel), but a visible upward jump for a row sizeHint() made taller (every group
        # after the first, which gets _GROUP_TOP_MARGIN of extra height above it — see its own
        # docstring): the extra space then landed entirely BELOW the text instead of being split
        # around it the way the style's own default (bypassed by drawing the text ourselves)
        # already centers plain, undecorated rows. Centering vertically here is what the plain
        # QStyledItemDelegate.paint() path used for every other row already does for free.
        y = text_rect.top() + max(0, (text_rect.height() - doc.size().height()) / 2)
        painter.translate(text_rect.left(), y)
        doc.documentLayout().draw(painter, _text_doc_paint_context(opt))
        painter.restore()


def _text_doc_paint_context(opt: QStyleOptionViewItem):
    from PyQt6.QtGui import QAbstractTextDocumentLayout
    ctx = QAbstractTextDocumentLayout.PaintContext()
    if opt.state & QStyle.StateFlag.State_Selected:
        ctx.palette.setColor(
            QPalette.ColorRole.Text,
            opt.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText),
        )
    return ctx


class TaskQueueStatusWidget(QPushButton):
    """Clickable status-bar indicator for task_queue.TaskQueueManager — shows the
    currently running export/import task (if any) plus how many more are waiting,
    and opens dialogs.task_queue_dialog.TaskQueuePanel on click. A flat QPushButton
    rather than a QLabel specifically so it gets a real clicked signal and hover/
    pressed visual feedback for free, without reinventing either."""

    clicked_for_panel = pyqtSignal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.clicked_for_panel.emit)

        manager.queue_changed.connect(self._refresh)
        manager.task_progress.connect(lambda *_: self._refresh())
        self._refresh()

    def _refresh(self) -> None:
        # Real reported request: kept this terse on purpose — "Экспорт... N/N",
        # nothing else. The task's own title, per-task type, succeeded/failed
        # breakdown, and the rest of the queue all belong in the popup panel
        # (dialogs.task_queue_dialog.TaskQueuePanel) instead, not crammed into
        # a status bar label.
        tasks = self._manager.list_tasks()
        running = next((t for t in tasks if t.status.name == "RUNNING"), None)

        if running is None:
            self.setText(tr("Очередь задач: пусто"))
            self.setToolTip(tr("Нет активных задач экспорта/импорта"))
            return

        kind_label = tr("Экспорт") if running.kind.name == "EXPORT" else tr("Импорт")
        progress = f" {running.progress_current}/{running.progress_total}" if running.progress_total else ""
        self.setText(f"{kind_label}...{progress}")
        self.setToolTip(tr("Нажмите, чтобы посмотреть очередь задач"))
