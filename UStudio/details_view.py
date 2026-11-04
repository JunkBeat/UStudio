"""The «Сведения» tab next to «Дерево» on the preview's «Просмотр» page: the selected object's plain facts, the
objects it refers to («Ссылается на») and the objects that refer to it («Используется в»), each a click away
(double-click / Enter jumps to it, like the tree's «Перейти к объекту»).

«Ссылается на» comes ready from the preview worker (core/object_references.py via PreviewResult); «Используется в»
from the game's usage index (core/usage_index.py, built in the background after a load — until it is ready the
section says how far it got). Nothing here reads an object."""

from core.i18n import tr
from typing import List, Optional

from PyQt6.QtCore import QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QSizePolicy, QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.file_utils import format_size
from gui_common import AdaptiveRow, show_copied_notice
import theme
from helpers import wrap_tooltip
from type_icons import get_action_icon, get_type_icon
from core.thumbnails import THUMBNAIL_TYPES
from thumbnail_loader import ThumbnailLoader, thumbnail_key

_TARGET_ROLE = Qt.ItemDataRole.UserRole + 1
_THUMB_KEY_ROLE = Qt.ItemDataRole.UserRole + 2
_PICTURE_ROLE = Qt.ItemDataRole.UserRole + 3     # True once the row shows its thumbnail (not the type icon)
_THUMB = 48                    # core/thumbnails.THUMB_SIZE (drawn smaller: sharp at 125-150 % display scaling)
_CARD_BOX = 40                 # the square box of every row: the fitted thumbnail or the type icon
_TYPE_ICON = 20                # a type icon in that box
_CARD_ROW = _CARD_BOX + 2      # row height: the box plus 1 px above and below (user request: no big padding)


def reference_text(ref) -> str:
    """How a referenced object is named in the lists: its name (a MonoBehaviour also its script, as the tree's
    «MonoBehaviour Base (Script)» rows do); without a name its type and PathID."""
    name = ref.name or f"{ref.type_name} #{ref.path_id}"
    return f"{name} ({ref.script})" if ref.script else name


_ZWSP = chr(0x200B)                       # zero-width space: an invisible break point
_BREAK_AFTER = "_-./:" + chr(92)          # chr(92) = a backslash (Windows paths)
_MAX_RUN = 12


def breakable(text: str) -> str:
    """`text` with invisible break points (zero-width spaces) after `_ - . / :` or a backslash, and inside any longer unbroken
    run, so a QLabel can wrap a long bundle/file name at any width instead of stretching the panel (a QLabel wraps
    only at break opportunities; "6a68fa4a1d…_unitybuiltinshaders_….bundle" has none)."""
    out, run = [], 0
    for ch in text:
        out.append(ch)
        run = 0 if ch.isspace() else run + 1
        if ch in _BREAK_AFTER or run >= _MAX_RUN:
            out.append(_ZWSP)
            run = 0
    return "".join(out)


class _FactValue(QLabel):
    """A fact's value: wraps anywhere (see breakable). Not selectable (user request: selecting and Ctrl+C was
    inconvenient — «Копировать сведения» copies them all at once); right-click «Копировать» copies this one value,
    always the CLEAN text (without the invisible break characters)."""

    def __init__(self, value: str):
        super().__init__(breakable(value))
        self.value = value
        self.setWordWrap(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos) -> None:
        menu = QMenu(self)
        act = menu.addAction(get_action_icon("copy"), tr("Копировать"))
        chosen = menu.exec(self.mapToGlobal(pos))
        menu.deleteLater()      # a per-use child: dropped right away (see CLAUDE.md, exec_and_dispose)
        if chosen is act:
            QApplication.clipboard().setText(self.value)
            show_copied_notice(self, pos)


class _RowDelegate(QStyledItemDelegate):
    """Every row of every list looks the same (user request: the look used to change with the list): a fixed square
    box — the thumbnail FITTED into it, or the type icon centred — then the name and, under it, the type in the muted
    color. Rows are only as tall as the box plus 1 px above and below. The box behind a picture is the panel's
    plain base color (a checkerboard hid black silhouettes and fine detail; a light box for dark pictures was tried
    and dropped — it changed how the texture looks)."""

    def __init__(self, view, tree: QTreeWidget):
        super().__init__(tree)
        self._view = view

    def sizeHint(self, option, index):
        return QSize(super().sizeHint(option, index).width(), _CARD_ROW)

    def paint(self, painter, option, index):
        if index.column() != 0:
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else None
        if style is not None:
            style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, widget)
        rect = option.rect
        box = QRect(rect.left() + 3, rect.top() + (rect.height() - _CARD_BOX) // 2, _CARD_BOX, _CARD_BOX)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if index.data(_PICTURE_ROLE):
            painter.fillRect(box, opt.palette.base().color())
            painter.setPen(self._view._muted)
            painter.drawRect(box.adjusted(0, 0, -1, -1))
            inner = box.adjusted(1, 1, -1, -1)
            pixmap = icon.pixmap(_THUMB, _THUMB) if isinstance(icon, QIcon) else QPixmap()
            if not pixmap.isNull():
                size = pixmap.size().scaled(inner.size(), Qt.AspectRatioMode.KeepAspectRatio)
                target = QRect(inner.left() + (inner.width() - size.width()) // 2,
                               inner.top() + (inner.height() - size.height()) // 2, size.width(), size.height())
                painter.drawPixmap(target, pixmap)
        elif isinstance(icon, QIcon):
            pad = (_CARD_BOX - _TYPE_ICON) // 2
            icon.paint(painter, box.adjusted(pad, pad, -pad, -pad))
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        text_color = opt.palette.highlightedText().color() if selected else opt.palette.text().color()
        muted = text_color if selected else self._view._muted
        text_rect = QRect(box.right() + 8, rect.top(), max(0, rect.right() - box.right() - 12), rect.height())
        metrics = opt.fontMetrics
        line = metrics.height()
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        kind = index.sibling(index.row(), 1).data(Qt.ItemDataRole.DisplayRole) or ""
        lines = 2 if kind else 1
        top = text_rect.top() + (text_rect.height() - lines * line) // 2
        painter.setFont(opt.font)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)     # a missing target is muted (_tint)
        if not selected and isinstance(foreground, QBrush):
            text_color = foreground.color()
        painter.setPen(text_color)
        painter.drawText(QRect(text_rect.left(), top, text_rect.width(), line), int(Qt.AlignmentFlag.AlignVCenter),
                         metrics.elidedText(name, Qt.TextElideMode.ElideRight, text_rect.width()))
        if kind:
            painter.setPen(muted)
            painter.drawText(QRect(text_rect.left(), top + line, text_rect.width(), line),
                             int(Qt.AlignmentFlag.AlignVCenter),
                             metrics.elidedText(kind, Qt.TextElideMode.ElideRight, text_rect.width()))
        painter.restore()


class _Section:
    """A titled list of references with an empty/progress line in its place when there is nothing to list."""

    def __init__(self, layout: QVBoxLayout, on_activated):
        self.title = QLabel()
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.title.setContentsMargins(0, 10, 0, 2)
        layout.addWidget(self.title)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setColumnHidden(1, True)      # the type is each row's second line (_RowDelegate)
        self.tree.setIconSize(QSize(_THUMB, _THUMB))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemActivated.connect(on_activated)
        layout.addWidget(self.tree, 1)

        self.empty = QLabel()
        self.empty.setContentsMargins(0, 2, 0, 0)
        layout.addWidget(self.empty)

    def hide(self) -> None:
        self.tree.clear()
        self.title.hide()
        self.tree.hide()
        self.empty.hide()

    def show_text(self, title: str, text: str) -> None:
        self.tree.clear()
        self.title.setText(title)
        self.title.show()
        self.tree.hide()
        self.empty.setText(text)
        self.empty.show()

    def show_items(self, title: str) -> None:
        self.title.setText(title)
        self.title.show()
        self.empty.hide()
        self.tree.show()


class ObjectDetailsView(QWidget):
    jump_requested = pyqtSignal(object)     # the referenced / referring ObjectReader
    edit_target_requested = pyqtSignal(object)      # a list row's «Отредактировать данные»
    # the action row (user request): the object SHOWN here — preview_panel adds it (its _current_obj)
    edit_requested = pyqtSignal()
    export_requested = pyqtSignal()
    export_menu_requested = pyqtSignal(object)      # the ▾ next to «Экспорт»: QPoint (global) to show the format menu at
    import_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._muted = QColor("#888888")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 0)     # the same 8 px under the tab bar as «Дерево» (user request)

        # icon-only when the panel is too narrow for the text (user report: the row held the right half at 419 px)
        self.actions_row = AdaptiveRow()
        actions = self.actions_row.row
        actions.setContentsMargins(0, 0, 0, 8)
        actions.setSpacing(6)
        self.btn_edit = self._action_button(actions, "edit", tr("Изменить"), tr("Отредактировать данные объекта"),
                                            self.edit_requested)
        # a split button (user request): the main part = the usual export (as the table's «Экспортировать...»),
        # the ▾ joined to it = the table's «Экспортировать как» formats (JSON / Raw dump of a texture, model, ...)
        export_pair = QHBoxLayout()
        export_pair.setSpacing(0)
        self.btn_export = self._action_button(export_pair, "export", tr("Экспорт"), tr("Экспортировать объект в файл"),
                                              self.export_requested)
        self.btn_export_menu = QPushButton()
        self.btn_export_menu.setAutoDefault(False)
        self.btn_export_menu.setToolTip(wrap_tooltip(tr("Экспортировать как: JSON дамп, Raw дамп…")))
        self.btn_export_menu.clicked.connect(
            lambda: self.export_menu_requested.emit(
                self.btn_export.mapToGlobal(self.btn_export.rect().bottomLeft())))
        export_pair.addWidget(self.btn_export_menu)
        # one joined control: no rounded corners where the two halves meet, one border between them (theme.py)
        self.btn_export.setObjectName("SplitMain")
        self.btn_export_menu.setObjectName("SplitArrow")
        self.btn_export_menu.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.btn_export.setSizePolicy(self.btn_export.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Preferred)
        self._set_export_arrow(theme.current_colors())
        actions.addLayout(export_pair)
        self.btn_import = self._action_button(actions, "import", tr("Импорт"), tr("Заменить объект данными из файла"),
                                              self.import_requested)
        actions.addStretch(1)       # with text: the copy button at the right end; icon-only: next to «Импорт»
        # every fact at once, «Тип: …» per line (user request: a quick way to copy the general information)
        # a plain QPushButton like the three above, so it has their grey button background (user request: as a
        # flat auto-raise tool button it did not look clickable)
        self.btn_copy_facts = QPushButton(get_action_icon("copy"), "")
        self.btn_copy_facts.setAutoDefault(False)
        self.btn_copy_facts.setToolTip(wrap_tooltip(tr("Копировать сведения об объекте")))
        self.btn_copy_facts.clicked.connect(self.copy_facts)
        self.btn_copy_facts.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        actions.addWidget(self.btn_copy_facts)
        actions.addStretch(0)
        self.actions_row.compact_changed.connect(self._place_copy_button)
        for button in (self.btn_edit, self.btn_export, self.btn_import, self.btn_copy_facts):
            self.actions_row.add_adaptive(button, "")
        layout.addWidget(self.actions_row)
        self._fact_values: List[tuple] = []

        self._facts = QFormLayout()
        self._facts.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._facts.setHorizontalSpacing(12)
        self._facts.setVerticalSpacing(3)
        layout.addLayout(self._facts)

        self._out = _Section(layout, self._on_activated)
        self._mat = _Section(layout, self._on_activated)      # a GameObject's model: what its parts are drawn with
        self._in = _Section(layout, self._on_activated)
        if theme.current_colors() is not None:       # the theme in use now (later switches: apply_theme_colors)
            arrows = theme.scrollbar_arrows_qss(theme.current_colors())
            for section in (self._out, self._mat, self._in):
                section.tree.verticalScrollBar().setStyleSheet(arrows)
        # the outgoing section under its old names (tests, preview_panel)
        self.refs_title, self.refs, self.refs_empty = self._out.title, self._out.tree, self._out.empty
        self.users_title, self.users, self.users_empty = self._in.title, self._in.tree, self._in.empty
        self.materials_title, self.materials = self._mat.title, self._mat.tree
        for section in (self._out, self._mat, self._in):
            tree = section.tree
            tree.setItemDelegate(_RowDelegate(self, tree))
            tree.customContextMenuRequested.connect(lambda pos, t=tree: self._row_menu(t, pos))
        layout.addStretch(0)

        # Thumbnails of the textures/sprites/materials in the lists: only the rows on screen, in the background
        # (thumbnail_loader.py), asked for again (debounced) when a list scrolls or the panel is resized.
        self.thumbnails = ThumbnailLoader(self)
        self.thumbnails.ready.connect(self._on_thumbnail)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(80)
        self._thumb_timer.timeout.connect(self._request_visible_thumbnails)
        for section in (self._out, self._mat, self._in):
            section.tree.verticalScrollBar().valueChanged.connect(self._thumb_timer.start)
        self.clear()

    # ---------------------------------------------------------------- public

    def apply_theme_colors(self, colors) -> None:
        self._muted = QColor(colors.disabled_text)
        self._set_export_arrow(colors)
        arrows = theme.scrollbar_arrows_qss(colors)
        for section in (self._out, self._mat, self._in):
            section.empty.setStyleSheet(f"color: {colors.disabled_text};")
            # up/down arrow buttons on the lists' scroll bars (user request; hidden app-wide)
            section.tree.verticalScrollBar().setStyleSheet(arrows)
            for i in range(section.tree.topLevelItemCount()):
                self._tint(section.tree.topLevelItem(i))

    def _place_copy_button(self, compact: bool) -> None:
        """Icon-only, the copy button joins the other buttons (user request: alone at the far right it looked
        detached); with text it stays at the right end. The spare width goes to whichever stretch has factor 1."""
        row = self.actions_row.row
        row.setStretch(row.indexOf(self.btn_import) + 1, 0 if compact else 1)
        row.setStretch(row.count() - 1, 1 if compact else 0)

    def _set_export_arrow(self, colors) -> None:
        color = colors.text if colors is not None else self.palette().color(self.palette().ColorRole.ButtonText).name()
        self.btn_export_menu.setIcon(QIcon(theme._write_arrow_icon(color, "down")))

    @staticmethod
    def _action_button(layout, icon: str, text: str, tip: str, signal) -> QPushButton:
        # a space before the text: Qt puts the icon right against it (user report: «not enough spacing after the
        # icon»); QPushButton has no icon-text spacing setting of its own
        button = QPushButton(get_action_icon(icon), " " + text)
        button.setToolTip(wrap_tooltip(tip))
        button.setAutoDefault(False)
        button.clicked.connect(signal.emit)
        layout.addWidget(button)
        return button

    def clear(self) -> None:
        self.actions_row.hide()
        self._set_facts([])
        self._out.hide()
        self._mat.hide()
        self._in.hide()
        self.thumbnails.request([])

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._thumb_timer.start()

    def set_details(self, facts, references: Optional[list], total: int) -> None:
        self._set_facts(self._fact_rows(facts) if facts is not None else [])
        self.actions_row.setVisible(facts is not None)
        if references is None:
            self._out.show_text(tr("Ссылается на"), tr("Не удалось прочитать ссылки этого объекта."))
            return
        title = tr("Ссылается на · {count}", count=total) if total else tr("Ссылается на")
        if not references:
            self._out.show_text(title, tr("Ни на что не ссылается."))
            return
        self._fill(self._out, references, total)
        self._out.show_items(title)

    def set_materials(self, rows: Optional[list], total: int = 0) -> None:
        """«Материалы и текстуры» of a GameObject's 3D model (user request): each material its parts use, followed
        by the texture drawn from it — with thumbnails, a double-click away like the other lists. None: hidden
        (anything that is not a model, or a model without materials)."""
        if not rows:
            self._mat.hide()
            return
        self._fill(self._mat, rows, total)
        self._mat.show_items(tr("Материалы и текстуры · {count}", count=total))

    def set_usage(self, users: Optional[list], total: int = 0, progress: Optional[tuple] = None) -> None:
        """«Используется в». users: Reference-like rows (the referring objects); None with `progress` = (done, all)
        while the index is being built; None without progress = no index (the section is hidden)."""
        if users is None:
            if progress is None:
                self._in.hide()
                return
            done, all_ = progress
            percent = int(done * 100 / all_) if all_ else 0
            self._in.show_text(tr("Используется в"), tr("Собирается список… {percent} %", percent=percent))
            return
        title = tr("Используется в · {count}", count=total) if total else tr("Используется в")
        if not users:
            self._in.show_text(title, tr("В загруженных файлах на этот объект никто не ссылается."))
            return
        self._fill(self._in, users, total)
        self._in.show_items(title)

    # ---------------------------------------------------------------- facts

    @staticmethod
    def _fact_rows(facts) -> List[tuple]:
        type_text = f"{facts.type_name} ({facts.script})" if facts.script else facts.type_name
        rows = [(tr("Тип"), type_text), (tr("Имя"), facts.name or "—"), ("PathID", str(facts.path_id)),
                (tr("Файл"), facts.file_name or "—")]
        if facts.source:
            rows.append((tr("Бандл"), facts.source))
        if facts.container:
            rows.append((tr("Путь"), facts.container))
        rows.append((tr("Размер"), format_size(facts.byte_size)))
        return rows

    @staticmethod
    def text_of_facts(facts) -> str:
        """What «Копировать сведения об объекте» copies for `facts` (core.object_references.object_facts) —
        also the table menu's «Копировать ▸ Сведения об объекте»."""
        return ObjectDetailsView._lines_text(ObjectDetailsView._fact_rows(facts))

    @staticmethod
    def _lines_text(rows) -> str:
        return "\n".join(f"{caption}: {value}" for caption, value in rows)

    def facts_text(self) -> str:
        return self._lines_text(self._fact_values)

    def copy_facts(self) -> None:
        if self._fact_values:
            QApplication.clipboard().setText(self.facts_text())
            show_copied_notice(self.btn_copy_facts)

    def _set_facts(self, rows: List[tuple]) -> None:
        self._fact_values = list(rows)
        while self._facts.rowCount():
            self._facts.removeRow(0)
        for caption, value in rows:
            label = QLabel(caption)
            label.setStyleSheet(f"color: {self._muted.name()};")
            self._facts.addRow(label, _FactValue(value))

    # ---------------------------------------------------------------- lists

    def _fill(self, section: _Section, rows: list, total: int) -> None:
        tree = section.tree
        tree.clear()
        # Every list has the same rows (_RowDelegate, a fixed height), whether it has pictures or not.
        pictures = any(ref.target is not None and ref.type_name in THUMBNAIL_TYPES for ref in rows)
        for ref in rows:
            self._add_reference(tree, ref)
        if pictures:
            self._thumb_timer.start()
        if total > len(rows):
            more = QTreeWidgetItem([tr("… и ещё {count}", count=total - len(rows)), ""])
            more.setFlags(Qt.ItemFlag.NoItemFlags)
            more.setData(0, _TARGET_ROLE, None)
            tree.addTopLevelItem(more)
            self._tint(more)

    def _add_reference(self, tree: QTreeWidget, ref) -> None:
        # second column: the type (user request — more useful at a glance than the field path, which is in the
        # tooltip)
        item = QTreeWidgetItem([reference_text(ref) if ref.target is not None
                                else f"{ref.type_name} #{ref.path_id}", ref.type_name])
        item.setIcon(0, get_type_icon(ref.type_name))
        item.setData(0, _TARGET_ROLE, ref.target)
        if ref.target is not None and ref.type_name in THUMBNAIL_TYPES:
            key = thumbnail_key(ref.target)
            item.setData(0, _THUMB_KEY_ROLE, key)
            found, icon = self.thumbnails.cached(key)
            if found and icon is not None:
                self._show_picture(item, icon)
        lines = [ref.type_name + (f" ({ref.script})" if ref.script else ""),
                 (tr("Поля: {fields}", fields=ref.field) if getattr(ref, "field_count", 1) > 1
                  else tr("Поле: {field}", field=ref.field)),
                 tr("Файл: {file}", file=ref.file_name), f"PathID: {ref.path_id}"]
        if ref.problem:
            lines.append(tr("Не найден: {reason}", reason=ref.problem))
            item.setText(0, f"{item.text(0)} — {ref.problem}")
        else:
            if getattr(ref, "note", ""):
                lines.append(tr("Объекты этого типа не загружались, поэтому его нет в таблице. "
                                "Его можно открыть и изменить; после изменения он появится в таблице."))
                item.setText(0, f"{item.text(0)} — {ref.note}")
            lines.append(tr("Двойной щелчок — перейти к объекту"))
        item.setToolTip(0, wrap_tooltip("\n".join(lines)))
        item.setToolTip(1, item.toolTip(0))
        tree.addTopLevelItem(item)
        self._tint(item)

    def _tint(self, item: QTreeWidgetItem) -> None:
        brush = QBrush(self._muted)
        item.setForeground(1, brush)
        if item.data(0, _TARGET_ROLE) is None:
            item.setForeground(0, brush)

    # ---------------------------------------------------------------- thumbnails

    def _visible_items(self):
        for section in (self._out, self._mat, self._in):
            tree = section.tree
            if tree.isHidden():
                continue
            viewport = tree.viewport().rect()
            for i in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(i)
                rect = tree.visualItemRect(item)
                if rect.bottom() < viewport.top() - rect.height() * 3:
                    continue
                if rect.top() > viewport.bottom() + rect.height() * 3:
                    break
                yield item

    def _request_visible_thumbnails(self) -> None:
        wanted = []
        for item in self._visible_items():
            key = item.data(0, _THUMB_KEY_ROLE)
            if key is not None and not self.thumbnails.cached(key)[0]:
                wanted.append(item.data(0, _TARGET_ROLE))
        self.thumbnails.request(wanted)

    def _on_thumbnail(self, key, image) -> None:
        if image is None:
            self.thumbnails.store(key, None)        # nothing to draw: the type icon stays
            return
        from gui_common import pil_to_qpixmap
        icon = QIcon(pil_to_qpixmap(image))
        self.thumbnails.store(key, icon)
        for section in (self._out, self._mat, self._in):
            tree = section.tree
            for i in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(i)
                if item.data(0, _THUMB_KEY_ROLE) == key:
                    self._show_picture(item, icon)

    @staticmethod
    def _show_picture(item: QTreeWidgetItem, icon: QIcon) -> None:
        item.setIcon(0, icon)
        item.setData(0, _PICTURE_ROLE, True)

    # ---------------------------------------------------------------- row menu / copy

    def _row_menu(self, tree: QTreeWidget, pos) -> None:
        item = tree.itemAt(pos)
        if item is None:
            return
        target = item.data(0, _TARGET_ROLE)
        if target is None:          # not found / «… и ещё N»: nothing to offer
            return
        menu = QMenu(self)
        edit = menu.addAction(get_action_icon("edit"), tr("Отредактировать данные"))
        menu.addSeparator()
        jump = menu.addAction(get_type_icon(getattr(target.type, "name", "")), tr("Перейти к объекту\tДвойной щелчок"))
        chosen = menu.exec(tree.viewport().mapToGlobal(pos))
        menu.deleteLater()      # a per-use child: dropped right away (see CLAUDE.md, exec_and_dispose)
        if chosen is edit:
            self.edit_target_requested.emit(target)
        elif chosen is jump:
            self.jump_requested.emit(target)

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        target = item.data(0, _TARGET_ROLE)
        if target is not None:
            self.jump_requested.emit(target)
