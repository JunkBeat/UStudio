"""The structure tree (PPtr-navigable object view), the scene hierarchy tree and their shared base/delegate."""

from core.i18n import tr
import re
from typing import Optional
from PyQt6.QtCore import QEvent, Qt, QPoint, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QAbstractTextDocumentLayout, QColor, QPalette, QPen, QTextDocument, QTextOption
from PyQt6.QtWidgets import QAbstractItemView, QApplication, QMenu, QMessageBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem
from html import escape as _html_escape
from UnityPy.classes.PPtr import PPtr
from UnityPy.helpers.TypeTreeHelper import FUNCTION_READ_MAP
from type_icons import get_action_icon, get_type_icon
from core.object_preview import format_typed_value, resolve_script_name
from helpers import mono_font as _mono_font


_PRIMITIVE_TYPES = frozenset(FUNCTION_READ_MAP.keys())


_TREE_MAX_ARRAY_ITEMS = 200


class _RichTextItemDelegate(QStyledItemDelegate):
    """Paints a tree item's text as HTML instead of plain text — lets
    ObjectStructureTree color the name/type/value parts of a single-column line
    (matching JsonHighlighter/TypedDumpHighlighter's key/keyword/string/number
    roles) without splitting into separate Name/Type/Value columns, which ate up
    most of the sidebar's width and left long lines eliding to "...". A plain item
    (no markup — the "...", error, and index-only items) never reaches
    QTextDocument at all, cheaper and avoids the delegate for the common case
    where plain painting is exactly right anyway."""

    # Real reported bug: on a selected row, the per-role inline colors
    # (_build_html()'s json_key/json_string/json_number/json_reference_type
    # spans, tuned for contrast against the tree's normal `base` background)
    # stayed exactly as-is against the SELECTION highlight background too —
    # an inline `style="color:...;"` span always wins over a QTextDocument's
    # palette-based default text color, so the pre-existing
    # ctx.palette.setColor(..., HighlightedText) below never actually reached
    # any of this text at all. Confirmed via a real screenshot, both themes:
    # some role colors (a muted teal/blue) had genuinely poor contrast against
    # the selection blue, reading as "the text disappeared". Fix: when
    # painting a selected row, rewrite every inline color to the theme's own
    # `highlighted_text` (already the palette's HighlightedText color
    # elsewhere in this app) BEFORE building the document — flattens the
    # syntax-highlighting to one guaranteed-contrast color for that one row,
    # the same tradeoff any syntax-highlighted view normally makes on
    # selection.
    _INLINE_COLOR_RE = re.compile(r"color\s*:\s*[^;\"]+;?")

    def _doc(self, text: str, font, override_color: Optional[str] = None, wrapped: bool = False) -> QTextDocument:
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setDocumentMargin(0)
        if override_color is not None:
            text = self._INLINE_COLOR_RE.sub(f"color:{override_color};", text)
        # NoWrap regardless of whatever width paint() ends up constraining the
        # document to: sizeHint() below always measures a single unconstrained
        # line, so if the document were left free to word-wrap and paint() ever
        # handed it a narrower width (column not yet resized to content, a
        # just-changed splitter, etc.), it would wrap into extra lines that
        # overflow past the row height sizeHint() actually reserved for it —
        # exactly the overlapping-text bug from the field report. With wrapping
        # off, a too-narrow rect just means the (single-line) text draws past the
        # row's right edge instead of breaking into a second line — recoverable by
        # scrolling (see ObjectStructureTree's horizontal scrollbar), never by
        # bleeding into the next row.
        #
        # "Перенос строк" (ObjectStructureTree.set_word_wrap) is the one case where wrapping is wanted:
        # paint() and sizeHint() then both give the document the SAME width (the room left of the row's
        # indentation), so the row is exactly as tall as the lines it wraps into. WrapAnywhere as the
        # fallback: a long unbroken value (a hex string, a path) has no word boundary to break at.
        option = QTextOption()
        option.setWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if wrapped else QTextOption.WrapMode.NoWrap)
        doc.setDefaultTextOption(option)
        if "<" in text:
            doc.setHtml(text)
        else:
            doc.setPlainText(text)  # only reached when wrapped: the plain-text path otherwise never builds a doc
        return doc

    def _wrapped(self) -> bool:
        return bool(getattr(self.parent(), "word_wrap", False))

    def _wrap_width(self, index) -> int:
        """Width a wrapped row's text gets: what is left of the viewport after the row's own indentation
        (branch arrow included). Not option.rect — sizeHint() is asked before the column has a real width
        (see sizeHint()); a few pixels of slack so paint(), which has the real rect, never needs MORE
        lines than the height reserved here."""
        tree = self.parent()
        depth, parent = 0, index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        return max(60, tree.viewport().width() - (depth + 1) * tree.indentation() - 6)

    def paint(self, painter, option, index) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        # Real bug caught by actually rendering this and inspecting the
        # pixels, not by reading the code: the text was ALWAYS drawn starting
        # at option.rect's own top edge, completely ignoring
        # _BOUNDARY_TOP_MARGIN — so for a boundary row, the header text sat
        # flush at the top of its row (overlapping the very band the
        # separator line is drawn in) while the reserved margin ended up as
        # dead space AFTER the text instead of a clean gap BEFORE it. This is
        # what made a real, visible margin still read as "the margin was
        # ignored" — the space was there, just in the wrong place. Fixed by
        # actually pushing the text (and, via CE_ItemViewItem below, the
        # background/branch decorations already correctly cover the WHOLE
        # rect regardless) down past the reserved band for a boundary row.
        top_offset = self._BOUNDARY_TOP_MARGIN if self._is_boundary_row(index) else 0
        wrapped = self._wrapped()
        if "<" not in text and not wrapped:
            super().paint(painter, option, index)
        else:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            style = opt.widget.style() if opt.widget else QApplication.style()
            opt.text = ""  # the style should draw the background/selection/branch, not the text
            painter.save()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

            override_color = None
            if opt.state & QStyle.StateFlag.State_Selected:
                colors = getattr(self.parent(), "_colors", None)
                if colors is not None:
                    override_color = colors.highlighted_text
            doc = self._doc(text, opt.font, override_color=override_color, wrapped=wrapped)
            # opt.rect should be the real, already-laid-out row rect by the time
            # paint() runs (unlike sizeHint(), called earlier) — but guard the same
            # 0-width case defensively anyway rather than trust that unconditionally.
            if opt.rect.width() > 0:
                doc.setTextWidth(opt.rect.width())
            painter.translate(opt.rect.topLeft() + QPoint(0, top_offset))
            ctx = QAbstractTextDocumentLayout.PaintContext()
            if opt.state & QStyle.StateFlag.State_Selected:
                ctx.palette.setColor(
                    QPalette.ColorRole.Text,
                    opt.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText),
                )
            doc.documentLayout().draw(painter, ctx)
            painter.restore()

        self._paint_boundary_separator(painter, option, index)

    # Reserved space ABOVE a top-level "boundary" row (see ObjectStructureTree.
    # _make_item's boundary param — set on set_objects()'s per-component root
    # items) for the separator LINE _paint_boundary_separator() draws in it —
    # see paint()'s own comment above for the text-position bug that made this
    # margin look broken/absent even though it was genuinely being reserved.
    #
    # Went through several designs, each a real reported issue on the way to
    # this one: (1) originally a background tint boundary=True applied —
    # first `surface`, only 3 RGB units from the tree's own `base`, essentially
    # invisible; swapped for a translucent `highlight` wash, genuinely
    # visible — then dropped outright per direct request ("remove the
    # backlight, everything else is fine") once this line was already doing
    # the actual separating job on its own; (2) briefly pure whitespace with
    # nothing drawn in it — visible, but read as accidental padding, not a
    # deliberate divider; (3) landed here: a real drawn rule, no background
    # tint at all; (4) 2026-10-15, user request: the accent ("lilac") 2 px line in a 10 px band read as loud, wide
    # strips — now a quiet 1 px line in the neutral border color, in a 5 px band.
    _BOUNDARY_TOP_MARGIN = 5
    _BOUNDARY_LINE_WIDTH = 1
    # Marker role for "this item is one of set_objects()'s per-component
    # roots" — used to exist implicitly via BackgroundRole (the old
    # background-tint code doubled as the signal _is_boundary_row() read),
    # but removing the tint meant nothing set BackgroundRole anymore. A
    # dedicated role keeps _is_boundary_row() working exactly as before with
    # no visual side effect of its own — set directly by ObjectStructureTree.
    # _make_item() when boundary=True.
    _BOUNDARY_ROLE = Qt.ItemDataRole.UserRole + 100

    def _is_boundary_row(self, index) -> bool:
        """True for a top-level item after the first with _BOUNDARY_ROLE set —
        i.e. one of set_objects()'s per-component roots, EXCLUDING the very
        first one (nothing above it to separate from) and excluding the last
        one's OWN bottom (nothing is ever drawn below the final item either,
        since this only ever draws ABOVE a qualifying row) — real reported
        request: a divider between components, never one at the very
        top/bottom of the whole list."""
        return (
            not index.parent().isValid()
            and index.row() > 0
            and bool(index.data(self._BOUNDARY_ROLE))
        )

    def _paint_boundary_separator(self, painter, option, index) -> None:
        if not self._is_boundary_row(index):
            return
        tree = self.parent()
        colors = getattr(tree, "_colors", None)
        if colors is None:
            return
        painter.save()
        # The neutral `border` color (the accent `highlight` read as a loud lilac stripe — user request), still a
        # clear divider in both themes; see the class comment above for the earlier designs.
        pen = QPen(QColor(colors.border))
        pen.setWidth(self._BOUNDARY_LINE_WIDTH)
        painter.setPen(pen)
        y = option.rect.top() + self._BOUNDARY_TOP_MARGIN // 2
        painter.drawLine(option.rect.left(), y, option.rect.right(), y)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if self._wrapped():
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            width = self._wrap_width(index)
            doc = self._doc(text, opt.font, wrapped=True)
            doc.setTextWidth(width)
            size = QSize(width, int(doc.size().height()))
        elif "<" not in text:
            size = super().sizeHint(option, index)
        else:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            doc = self._doc(text, opt.font)
            # Deliberately NOT constraining doc.setTextWidth() to option.rect here —
            # sizeHint() gets queried during Qt's initial layout pass, before the
            # column's real width is established, and option.rect was coming through
            # as 0-width at that point. A QTextDocument given a ~0px text width wraps
            # almost character-by-character trying to fit, which is what produced the
            # wildly tall rows (every item, not just the selected one, since nearly
            # every item has a type — the html path fires for any of them). Leaving
            # the document's text width unconstrained (its default, -1) makes it lay
            # out as one natural single line instead, exactly like a plain item's text
            # already does — which is what a tree row actually wants: no wrapping,
            # any overflow handled by the tree's own horizontal scrollbar.
            size = QSize(int(doc.idealWidth()) + 4, int(doc.size().height()))

        if self._is_boundary_row(index):
            size = QSize(size.width(), size.height() + self._BOUNDARY_TOP_MARGIN)
        return size


class _HorizontalScrollStableTreeWidget(QTreeWidget):
    """Shared base for any QTreeWidget where a row's real content can extend far
    to the right of its indentation-based rect (ObjectStructureTree's field
    tree, SceneHierarchyTree's GameObject hierarchy) — factors out the
    horizontal-scroll behavior both need so there's one implementation to keep
    in sync, not two near-identical copies. Used to be duplicated once
    already (ObjectStructureTree's own _reveal_branch_horizontally +
    scrollTo() override) before SceneHierarchyTree needed the identical
    behavior for the Scene Viewer's hierarchy pane — see build_scene_hierarchy's
    own module for that feature.

    Provides: per-pixel horizontal scrolling (needed for _reveal_branch_
    horizontally() below to land precisely, not snap to whole-item widths), a
    scrollTo() override pinning the horizontal position across Qt's own
    auto-scroll-on-select (see its own docstring), and _reveal_branch_
    horizontally() itself for a subclass's itemExpanded handler to call."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible) -> None:
        """Pins the horizontal scroll position across Qt's own default
        auto-scroll-on-select — a real reported bug: merely (re-)clicking an
        already-visible item could snap the horizontal scrollbar to the far
        left, because Qt's built-in EnsureVisible only knows about the item's
        narrow indentation-based rect, not this tree's actual real content
        width (delegate-rendered for ObjectStructureTree, or simply a long
        GameObject name deep in the hierarchy for SceneHierarchyTree). Doesn't
        affect _reveal_branch_horizontally() below, which sets the horizontal
        scrollbar directly rather than going through scrollTo() — that's the
        one path that's actually supposed to move it."""
        bar = self.horizontalScrollBar()
        pos = bar.value()
        super().scrollTo(index, hint)
        bar.setValue(pos)

    # How far from the viewport's left edge a newly revealed branch's first
    # child gets positioned — a fraction of the viewport width, floored by a
    # fixed pixel amount so a very narrow panel still gets SOME left margin.
    # Deliberately not 0 (flush against the edge) and not 0.5 (true centering,
    # which was tried and reported unstable — see git history/CLAUDE.md for
    # the three earlier designs this replaced): a modest left bias means the
    # branch's own new content starts a little into the viewport rather than
    # jammed at the edge, while leaving most of the width to the right where
    # newly revealed, deeper content actually is.
    _HORIZONTAL_REVEAL_BIAS = 0.2
    _HORIZONTAL_REVEAL_MARGIN = 12

    def _reveal_branch_horizontally(self, item: QTreeWidgetItem) -> None:
        """Scrolls the horizontal scrollbar so the newly revealed indent level
        (item's first child, if it has one — otherwise item itself) starts a
        little way into the viewport rather than flush against either edge.

        Deliberately keys off the child's own LEFT EDGE (indentation-based,
        identical for every sibling at that depth) rather than any child's
        rendered text width: every sibling sits at essentially the same X
        position regardless of how long its own label is, so this is a stable,
        monotonically-increasing anchor as you drill deeper into a chain — an
        earlier "pick whichever sibling has the widest text" version varied
        with sibling content and could scroll backward mid-chain for no reason
        a user drilling deeper would expect."""
        anchor = item.child(0) if item.childCount() else item
        index = self.indexFromItem(anchor, 0)
        if not index.isValid():
            return
        rect = self.visualRect(index)
        if rect.isNull():
            return

        bar = self.horizontalScrollBar()
        viewport_width = self.viewport().width()
        # visualRect() is viewport-relative (an item scrolled past the left edge
        # has a negative x) — convert to content-space (scroll-offset-independent)
        # so the target scrollbar value can be computed directly.
        anchor_left = rect.left() + bar.value()
        bias = max(self._HORIZONTAL_REVEAL_MARGIN, round(viewport_width * self._HORIZONTAL_REVEAL_BIAS))
        target = anchor_left - bias
        bar.setValue(max(0, min(bar.maximum(), target)))


class _QtOpaque:
    """Holds a Python object inside a QTreeWidgetItem's data WITHOUT PyQt converting it.
    setData() turns a plain list/dict into a QVariantList/QVariantMap element by element
    (and item.data() builds a fresh copy on the way back). For a parsed object holding a
    big array — a 15 MB Font's m_FontData is a 15,515,760-element list — that conversion
    blocked the GUI thread for ~6 s (measured: 17 setData calls). An instance of an
    arbitrary class is stored as a plain Python reference instead, and read back as the
    very same object."""
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class ObjectStructureTree(_HorizontalScrollStableTreeWidget):
    """Lazily-expandable view of an object's parsed field tree ("View Data" style —
    only the top level is populated/expanded initially; a compound field's children
    are built the first time it's actually expanded, not eagerly, so this stays
    cheap even for a large object). A PPtr field is additionally expandable into the
    object it points to: expanding it constructs a PPtr and calls .deref() (the
    exact same class UnityPy's own parser builds — no separate resolution
    mechanism), then lazily populates the referenced object's own fields the same
    way, recursively.

    One column, "name type" or "name type = value" (_RichTextItemDelegate above
    renders the per-role coloring inline via HTML spans) — an earlier version used
    three separate Name/Type/Value columns for the coloring instead, but that ate
    most of the sidebar's width and left long lines truncated to "..."."""

    _KIND_ROLE = Qt.ItemDataRole.UserRole       # "class" | "array" | "pptr" | None (populated/leaf)
    _NODE_ROLE = Qt.ItemDataRole.UserRole + 1   # TypeTreeNode (class) or element subtype node (array)
    _VALUE_ROLE = Qt.ItemDataRole.UserRole + 2  # dict (class) / list (array) / (file_id, path_id) (pptr)
    _ASSETS_ROLE = Qt.ItemDataRole.UserRole + 3  # SerializedFile — resolution context for nested PPtrs
    # (file_id, path_id, assets_file) for a PPtr-typed item — set once at
    # creation and, unlike _KIND_ROLE/_VALUE_ROLE/_ASSETS_ROLE above, NEVER
    # cleared once the item is expanded/populated (_on_item_expanded resets
    # _KIND_ROLE to None to mark "already populated", which would otherwise
    # make an already-expanded PPtr row indistinguishable from a plain field
    # for the context menu below).
    _PPTR_REF_ROLE = Qt.ItemDataRole.UserRole + 4
    # The object THIS root row itself represents (an actual ObjectReader, not
    # a PPtr triple needing deref()) — set on set_object()'s single root and
    # each of set_objects()'s per-component roots. Real reported oversight:
    # _show_context_menu() only ever handled a PPtr row's own REFERENCED
    # object, with no way to act (Edit/Jump) on a "Base" root row's own
    # object directly — e.g. the Scene Viewer's Components pane shows a
    # MonoBehaviour's own "MonoBehaviour Base (Script)" root with no way to
    # jump to or edit that component itself without going and finding it in
    # the main table by hand first.
    _SELF_REF_ROLE = Qt.ItemDataRole.UserRole + 5

    # Class-level default: viewportEvent() can fire while QTreeWidget.__init__ is still running,
    # before __init__ below assigns anything (an AttributeError inside a Qt virtual aborts the process).
    _word_wrap = False

    # Emitted when the context menu's "Перейти к объекту" is used on a PPtr
    # row — the referenced object's own ObjectReader, same payload contract
    # as preview_panel.PreviewPanel.jump_to_object_requested (which this is
    # simply re-emitted through, see PreviewPanel._build_ui).
    jump_requested = pyqtSignal(object)
    # Emitted for "Отредактировать данные" — likewise just the ObjectReader;
    # PreviewPanel doesn't know how to open an editor itself (that's
    # object_actions.py's job), so this bubbles up through
    # PreviewPanel.edit_object_requested to MainWindow, which does.
    edit_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(_mono_font())
        self.setHeaderHidden(True)
        self.setItemDelegate(_RichTextItemDelegate(self))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        # The single column defaults to a fixed width unrelated to its items' real
        # content width, so a long line (deep indent + long type/value text) was
        # getting word-wrapped by the delegate's QTextDocument at that narrow width
        # — but sizeHint() (used to size the ROW) measures the text unconstrained/
        # single-line, so the wrapped paint() output overflowed into the row below
        # it, producing exactly the garbled overlapping text seen in the field
        # report. Fix is two-sided: resize the column to the actual content
        # (_resize_to_contents(), called after every population/expansion below) so
        # paint()'s available width usually already matches sizeHint()'s, and the
        # base class's per-pixel horizontal scrollbar (see
        # _HorizontalScrollStableTreeWidget.__init__) lets a line that's still
        # wider than the visible viewport scroll instead of wrapping.
        self._colors = None
        self._word_wrap = False
        self._suspend_resize = False  # True during expand_all_branches()'s recursive
        # expansion — each individual _on_item_expanded() would otherwise call
        # resizeColumnToContents() (an O(visible items) scan) once per node expanded,
        # making a full expand-all O(n^2); suppressed there in favor of one resize
        # after the whole traversal finishes.
        self.itemExpanded.connect(self._on_item_expanded)

    def apply_theme_colors(self, colors) -> None:
        """Stored and applied to items built from here on — like JsonHighlighter's
        already-rendered text, items built before a live theme toggle keep their
        old colors rather than being walked and recolored (same policy this app
        already applies to the log panel — see main.py's _on_log_record)."""
        self._colors = colors

    def _make_item(
        self, parent, name: str = "", type_text: str = "", value_text: str = "",
        is_string: bool = False, bold: bool = False, boundary: bool = False,
        array_size: Optional[int] = None, plain: bool = False,
    ) -> QTreeWidgetItem:
        # plain: an object's root row ("Transform Base") in ordinary text, no colors or bold — like UABEA; colored
        # like the fields below it, a component's header blended into them (user request, 2026-10-15).
        if (type_text or value_text) and self._colors is not None and not plain:
            text = self._build_html(name, type_text, value_text, is_string, bold, array_size)
        else:
            # Real reported request: type first, then name — was name-first
            # ("m_Component vector"), now type-first ("vector m_Component"),
            # matching the Dump tab's own "type name = value" convention
            # instead of deliberately differing from it.
            parts = [p for p in (type_text, name) if p]
            text = " ".join(parts)
            if array_size is not None:
                text += f" [{array_size}]"
            if value_text:
                text += f" = {value_text}"
            if plain and self._colors is not None:
                # Still drawn as rich text (just with nothing in it to color), so the row keeps the height of
                # the rich-text rows around it — a plain-text row was laid out a few pixels shorter.
                text = f"<span>{_html_escape(text)}</span>"
        item = QTreeWidgetItem(parent, [text])
        # Real reported request: a resolved PPtr's own header row (the "→
        # RectTransform, PathID 5" line _expand_pptr() builds) — and,
        # separately, each per-component root in set_objects() — needed to
        # read as "a different object starts here" at a glance. Went through
        # a background-tint phase (first `surface`, nearly invisible against
        # `base`; then a translucent `highlight` wash, genuinely visible but
        # ultimately dropped per direct request — "remove the backlight,
        # everything else is fine" once the bold separator line below was
        # already doing the actual job). What's left is just the marker role
        # _RichTextItemDelegate reads to decide which rows get the bold
        # separator line + text-position offset (see that class's
        # _is_boundary_row/_paint_boundary_separator) — no visual effect of
        # its own anymore.
        if boundary:
            item.setData(0, _RichTextItemDelegate._BOUNDARY_ROLE, True)
        return item

    def _build_html(
        self, name: str, type_text: str, value_text: str, is_string: bool,
        bold: bool = False, array_size: Optional[int] = None,
    ) -> str:
        c = self._colors
        # Real reported request: type first, then name (was the reverse) —
        # matches the Dump tab's own "type name = value" convention instead
        # of deliberately differing from it.
        parts = []
        if type_text:
            # Simple/primitive types (int, string, bool, vector, unsigned
            # int, ...) stay the ordinary keyword color; any Unity-specific
            # class/compound type — GameObject, ComponentPair, PPtr<...>,
            # StreamingInfo, a MonoBehaviour's own script class name,
            # anything not in UnityPy's own primitive-type set — gets a
            # distinct color instead, not just PPtr specifically (a real
            # request corrected this from an earlier PPtr-only version).
            type_color = c.json_keyword if type_text in _PRIMITIVE_TYPES else c.json_reference_type
            parts.append(f'<span style="color:{type_color};">{_html_escape(type_text)}</span>')
        if name:
            parts.append(f'<span style="color:{c.json_key}; font-weight:600;">{_html_escape(name)}</span>')
        html = " ".join(parts)
        if array_size is not None:
            html += f" [{array_size}]"
        if value_text:
            color = c.json_string if is_string else c.json_number
            html += f' = <span style="color:{color};">{_html_escape(value_text)}</span>'
        # Bolds the WHOLE line (name, type, and PathID/FileID value alike) — used
        # for PPtr rows, so a navigable reference stands out from a plain field at
        # a glance instead of only the name portion being visually distinct (as
        # every row already is, via json_key's own font-weight above).
        if bold:
            html = f"<b>{html}</b>"
        return html

    def set_object(self, obj, data=None, node=None) -> None:
        """data/node: an already-parsed obj.parse_as_dict()/obj._get_typetree_node()
        pair a caller (preview_panel.py, via PreviewResult.parsed_data/parsed_node —
        see build_preview()'s own docstring) computed once and wants reused, instead
        of this re-parsing the same object a THIRD or fourth time. Both default to
        None, in which case this parses fresh exactly as before — every other caller
        (Scene Viewer's set_objects(), any future one-off use) is unaffected."""
        self.clear()
        try:
            if node is None:
                node = obj._get_typetree_node()
            if data is None:
                data = obj.parse_as_dict()
        except Exception as e:
            self._make_item(self, name=tr("Ошибка чтения: {error}", error=e), plain=True)
            return
        root = self._make_item(self, name=node.m_Name, type_text=node.m_Type, plain=True)
        root.setData(0, self._SELF_REF_ROLE, obj)
        self._populate_children(root, node, data, obj.assets_file)
        root.setExpanded(True)
        self._resize_to_contents()

    def set_objects(self, objs: list) -> None:
        """Multi-root version of set_object() — one top-level item per object,
        all expanded by default, instead of clearing between them. Used by the
        Scene Viewer's Components pane to show every component attached to a
        selected GameObject side by side (Transform, MonoBehaviour, ...) the
        same way UABEA's own GameObject Viewer does — "Tree View" was already
        built for exactly this per-object field rendering, this just calls it
        once per component instead of adding a second implementation.

        Each root's label matches set_object()'s own convention (type first,
        then the TypeTree's root node name — normally the literal "Base"), with
        one addition: a MonoBehaviour's component also gets its resolved
        script name in parens (e.g. "MonoBehaviour Base (AudioLevels)"),
        since "MonoBehaviour Base" alone doesn't say which script — every
        OTHER component type's own class name already is that information.

        Every root gets boundary=True (the divider line above it) and is drawn
        as plain text, like UABEA's "Transform Base" rows — it used to be bold
        with the fields' colors, and the components blended into each other
        (user request, 2026-10-15)."""
        self.clear()
        for obj in objs:
            node = data = error = None
            try:
                node = obj._get_typetree_node()
                data = obj.parse_as_dict()
            except Exception as e:
                error = e
            # An unreadable component still gets its own header row, with the error line inside it (user
            # request: a bare error row sat between the components, belonging to none of them) — and the row
            # keeps the jump/edit menu, which is how such a component gets looked at.
            name = node.m_Name if node is not None else "Base"
            if obj.type.name == "MonoBehaviour":
                try:
                    script_name = resolve_script_name(obj)
                except Exception:
                    script_name = ""
                if script_name:
                    name = f"{name} ({script_name})"
            type_text = node.m_Type if node is not None else obj.type.name
            root = self._make_item(self, name=name, type_text=type_text, boundary=True, plain=True)
            root.setData(0, self._SELF_REF_ROLE, obj)
            if error is not None:
                self._make_item(root, name=tr("Ошибка чтения: {error}", error=error), plain=True)
            else:
                self._populate_children(root, node, data, obj.assets_file)
            root.setExpanded(True)
        self._resize_to_contents()

    def clear_object(self) -> None:
        self.clear()

    def _resize_to_contents(self) -> None:
        if not self._suspend_resize and not self._word_wrap:
            self.resizeColumnToContents(0)

    @property
    def word_wrap(self) -> bool:
        return self._word_wrap

    def set_word_wrap(self, on: bool) -> None:
        """Optional line wrapping ("Перенос строк"). On: a long line breaks to the width of the view
        (no horizontal scrollbar, the column follows the viewport instead of the widest line). Off (the
        default): one line per row and a horizontal scrollbar, as before."""
        on = bool(on)
        if on == self._word_wrap:
            return
        self._word_wrap = on
        self.setWordWrap(on)
        if on:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._fit_column_to_viewport()
        else:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.resizeColumnToContents(0)
        self.scheduleDelayedItemsLayout()  # every row's height depends on the mode

    def _fit_column_to_viewport(self) -> None:
        # Set by hand: the header is hidden, and a Stretch resize mode did not shrink a column that had
        # already been sized to a wide line.
        if self.viewport().width() > 0:
            self.setColumnWidth(0, self.viewport().width())

    def viewportEvent(self, event) -> bool:
        # The viewport (not the widget) is what changes width when the vertical scrollbar appears,
        # which is exactly what happens when wrapping makes the rows taller.
        handled = super().viewportEvent(event)
        if self._word_wrap and event.type() == QEvent.Type.Resize:
            self._fit_column_to_viewport()
            self.scheduleDelayedItemsLayout()  # the lines wrap differently at the new width
        return handled

    # --- Expand All / Collapse All ---

    def expand_all_branches(self) -> None:
        """Expands every branch EXCEPT PPtr fields, which are left collapsed (still
        showing their "..." placeholder) rather than auto-expanded — expanding a
        "pptr" item is exactly what triggers _on_item_expanded's PPtr(...).deref()
        call, i.e. a real read of whatever object it points to. A plain
        expandAll()/recursive-expand-everything would walk into every PPtr field
        too and transitively read every object reachable from the current one —
        exactly the unbounded, surprising work this tree's lazy-population design
        exists to avoid. So PPtr items are the one node kind expand_all_branches()
        stops AT, not just stops recursing past: the user can still open one by
        hand to resolve it, one at a time, same as before this button existed."""
        # Real reported complaint: clicking this button moved the scroll
        # position — expanding potentially the ENTIRE tree changes the row
        # count/column width dramatically (resizeColumnToContents() alone is
        # already established elsewhere in this class to reset horizontal
        # scroll as a side effect of the column growing), and _suspend_resize
        # only skips this class's OWN per-item reveal/vertical-restore logic
        # (see _on_item_expanded), not whatever Qt's own internals do underneath
        # such a large structural change. Capturing both bars before and
        # restoring them after, unconditionally, doesn't depend on knowing
        # every intermediate cause — it just guarantees the view ends up
        # exactly where it started, regardless of what moved it in between.
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        h_pos, v_pos = hbar.value(), vbar.value()
        self._suspend_resize = True
        try:
            self._expand_recursive(self.invisibleRootItem())
        finally:
            self._suspend_resize = False
        if not self._word_wrap:
            self.resizeColumnToContents(0)
        hbar.setValue(h_pos)
        vbar.setValue(v_pos)

    def _expand_recursive(self, item: QTreeWidgetItem) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, self._KIND_ROLE) == "pptr":
                continue  # leave collapsed — expanding it would deref/read the referenced object
            if not child.isExpanded():
                child.setExpanded(True)  # triggers _on_item_expanded's lazy populate
            self._expand_recursive(child)

    def collapse_all_branches(self) -> None:
        # Unlike expand_all_branches() (which preserves the exact scroll
        # position, since expanding only adds content the user was already
        # looking at more of), collapsing everything back to the top-level
        # items makes whatever was scrolled into view meaningless — there's
        # nothing left at the old position to preserve. Explicit (0, 0) instead
        # of just letting collapseAll() do whatever it does on its own: this
        # was specifically requested after collapse_all_branches previously
        # tried to restore the pre-collapse position (safe, since setValue()
        # clamps to the new smaller range, but not what was actually wanted
        # here) — collapsing should always land back at the top-left corner.
        self.collapseAll()
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    # --- population ---

    def _populate_children(self, parent_item: QTreeWidgetItem, node, value, assets_file) -> None:
        child_value = value if isinstance(value, dict) else {}
        for child_node in node.m_Children:
            self._add_field_item(parent_item, child_node, child_value.get(child_node.m_Name), assets_file)

    def _add_field_item(self, parent: QTreeWidgetItem, node, value, assets_file) -> None:
        # TypelessData/generic primitives are checked BEFORE the vector/array test
        # below — "string"/"TypelessData" structurally have an "Array" child in the
        # raw schema too (Unity encodes them as char/byte vectors under the hood),
        # but UnityPy's own read_value() short-circuits via FUNCTION_READ_MAP before
        # ever looking at m_Children. Same ordering core.object_preview.dump_typed_text
        # uses, for the same reason — see that module's _dump_node comment.
        if node.m_Type == "TypelessData":
            n = len(value) if value is not None else 0
            self._make_item(parent, name=node.m_Name, type_text=node.m_Type, value_text=f"(size={n})")
            return

        if node.m_Type in _PRIMITIVE_TYPES:
            self._make_item(
                parent, name=node.m_Name, type_text=node.m_Type,
                value_text=format_typed_value(node.m_Type, value), is_string=node.m_Type == "string",
            )
            return

        # Vector/array — same detection UnityPy's own read_value()/dump_typed_text()
        # use: the field's first child is an "Array" wrapper node.
        if node.m_Children and node.m_Children[0].m_Type == "Array":
            seq = value if isinstance(value, (list, tuple)) else []
            item = self._make_item(parent, name=node.m_Name, type_text=node.m_Type, array_size=len(seq))
            if seq:
                subtype = node.m_Children[0].m_Children[1]
                item.setData(0, self._KIND_ROLE, "array")
                item.setData(0, self._NODE_ROLE, subtype)
                item.setData(0, self._VALUE_ROLE, _QtOpaque(seq))
                item.setData(0, self._ASSETS_ROLE, assets_file)
                item.addChild(QTreeWidgetItem(["..."]))
            return

        # Class / compound — PPtr<...> is the special case: instead of showing its
        # raw m_FileID/m_PathID as ordinary sub-fields, expanding it resolves and
        # shows the REFERENCED object's own fields (see _expand_pptr) — that's the
        # whole point of this tree over the plain Dump tab text. Bolded (the whole
        # line, not just the name every row already bolds) so a reference stands
        # out from a plain field at a glance, whether or not it actually resolves
        # to anything (a dangling/null PPtr is still visually a PPtr).
        is_pptr_type = node.m_Type.startswith("PPtr<")
        # Real reported request: PPtr rows should stand out at a glance, not
        # just via the bold styling every row already gets a version of —
        # prefixed with "→ " (matching the same arrow _expand_pptr() already
        # uses for the resolved-object header once expanded, so the same
        # glyph means "this is/leads to a reference" consistently).
        display_name = f"→ {node.m_Name}" if is_pptr_type else node.m_Name
        # Real reported request: the raw m_FileID/m_PathID used to show inline
        # on the PPtr row itself — moved to be children instead (see
        # _expand_pptr, which builds them alongside the resolved-object
        # header), consistent with every other compound field showing its
        # own sub-fields only once actually expanded rather than crammed onto
        # one line. A null reference (m_PathID == 0 — PPtr.__bool__'s own
        # definition of "empty") is the one case still shown inline as plain
        # "null": there's nothing further to resolve for it, so there'd be
        # nothing new to see by expanding — matches how a null reference is
        # described everywhere else (dump_typed_text's Class dump aside,
        # which is a different, deliberately raw presentation — see its own
        # docstring).
        file_id = path_id = None
        if is_pptr_type and isinstance(value, dict):
            file_id = value.get("m_FileID", 0)
            path_id = value.get("m_PathID", 0)
        value_text = "null" if path_id == 0 else ""
        item = self._make_item(
            parent, name=display_name, type_text=node.m_Type, value_text=value_text, bold=is_pptr_type,
        )
        if is_pptr_type and path_id:
            item.setData(0, self._KIND_ROLE, "pptr")
            item.setData(0, self._VALUE_ROLE, (file_id, path_id))
            item.setData(0, self._ASSETS_ROLE, assets_file)
            item.setData(0, self._PPTR_REF_ROLE, (file_id, path_id, assets_file))
            item.addChild(QTreeWidgetItem(["..."]))
        elif node.m_Children:
            item.setData(0, self._KIND_ROLE, "class")
            item.setData(0, self._NODE_ROLE, node)
            item.setData(0, self._VALUE_ROLE, _QtOpaque(value))
            item.setData(0, self._ASSETS_ROLE, assets_file)
            item.addChild(QTreeWidgetItem(["..."]))

    # --- lazy expansion ---

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        kind = item.data(0, self._KIND_ROLE)
        if kind is None:
            return  # already populated on a previous expand, or a plain leaf
        # Restored at the end of this method (see the block right after the
        # horizontal-centering one below) — a real reported complaint was the
        # VERTICAL scroll position drifting once a deeply-expanded branch near
        # the bottom of the tree grew enough new rows below it, scrolling the
        # view further down than the branch itself and losing the very thing
        # the user just expanded off the top of the viewport. Nothing about
        # adding rows BELOW item changes where the rows ABOVE it sit, so simply
        # putting the vertical scrollbar back exactly where it was is correct,
        # not just a workaround — the item that was visible enough to click and
        # expand a moment ago is still visible at that same scroll position.
        vbar = self.verticalScrollBar()
        vbar_pos_before = vbar.value()
        item.takeChildren()  # drop the "..." placeholder
        item.setData(0, self._KIND_ROLE, None)  # mark populated so this doesn't re-run

        assets_file = item.data(0, self._ASSETS_ROLE)
        if kind == "class":
            self._populate_children(item, item.data(0, self._NODE_ROLE), item.data(0, self._VALUE_ROLE).value, assets_file)
        elif kind == "array":
            self._populate_array(item, item.data(0, self._NODE_ROLE), item.data(0, self._VALUE_ROLE).value, assets_file)
        elif kind == "pptr":
            file_id, path_id = item.data(0, self._VALUE_ROLE)
            self._expand_pptr(item, file_id, path_id, assets_file)
        self._resize_to_contents()
        # Manually expanding a branch reveals children indented one level deeper
        # — for an already-long/deeply-nested line, those new children extend
        # past the right edge of the current horizontal scroll position, invisible
        # until the user scrolls by hand. scrollToItem(EnsureVisible) on the
        # expanded item itself doesn't fix this: Qt's per-item rect for a tree is
        # based on indentation, not the delegate's actual rendered text width, so
        # Qt considers the (already-visible, unmoved) parent item "in view"
        # without scrolling further right to cover its newly-added children's
        # real content — and resizeColumnToContents() just above tends to reset
        # the scrollbar position to 0 as a side effect of the column's total
        # width changing, which is what made this look like it jumped to the
        # LEFT edge instead of doing nothing.
        #
        # Went through three designs before this one: (1) jump straight to the
        # scrollbar's new maximum — that's the widest item ANYWHERE in the whole
        # tree, usually unrelated to what's actually being expanded, reported as
        # its own annoyance; (2) reveal-minimally based on whichever DIRECT CHILD
        # had the widest rendered text — reported as basically working, but with
        # a preference for the branch sitting roughly centered; (3) centering on
        # that same widest-child pick — reported back with two real problems:
        # scrolling would sometimes jump LEFT while continuously drilling deeper
        # (confirmed why: every direct child sits at nearly the same indent, so
        # the only thing that varied between expand steps was which sibling
        # happened to have the longest text — an unstable, non-monotonic signal
        # to scroll off of), and branches near the tree's horizontal edges could
        # end up with their own text cut off once the centered target got
        # clamped to the scrollbar's real range.
        #
        # This version anchors on the new indent LEVEL itself instead of any
        # particular child's text — the base class's own
        # _reveal_branch_horizontally() (see _HorizontalScrollStableTreeWidget).
        if not self._suspend_resize:
            self._reveal_branch_horizontally(item)
            vbar.setValue(vbar_pos_before)

    def _populate_array(self, item: QTreeWidgetItem, subtype, seq, assets_file) -> None:
        is_pair = subtype.m_Type == "pair" and len(subtype.m_Children) == 2
        shown = min(len(seq), _TREE_MAX_ARRAY_ITEMS)
        for i in range(shown):
            if is_pair:
                pair_item = self._make_item(item, name=f"[{i}]", type_text="pair")
                k, v = seq[i] if isinstance(seq[i], (tuple, list)) and len(seq[i]) == 2 else (None, None)
                self._add_field_item(pair_item, subtype.m_Children[0], k, assets_file)
                self._add_field_item(pair_item, subtype.m_Children[1], v, assets_file)
            else:
                index_item = self._make_item(item, name=f"[{i}]")
                self._add_field_item(index_item, subtype, seq[i], assets_file)
        if len(seq) > shown:
            self._make_item(item, name=tr("... (ещё {count} элементов)", count=len(seq) - shown))

    @staticmethod
    def _resolve_pptr_file_name(file_id: int, assets_file) -> str:
        """Mirrors UnityPy's own PPtr.deref() file-id resolution (see
        UnityPy/classes/PPtr.py) just for the display name, without doing a
        full resolve/read: m_FileID == 0 means "this same file"; any other
        value 1-indexes into assets_file.externals (external_id =
        m_FileID - 1, exactly as deref() computes it). FileIdentifier.name is
        already the clean basename (strips the "archive:/..." container
        prefix a raw .path carries) — the same value deref()'s own external-
        name lookup normalizes to before searching by name, just not
        lowercased since this is for display, not matching."""
        if assets_file is None:
            return "?"
        if file_id == 0:
            return getattr(assets_file, "name", "") or "?"
        externals = getattr(assets_file, "externals", None) or []
        external_id = file_id - 1
        if 0 <= external_id < len(externals):
            return externals[external_id].name
        return "?"

    def _expand_pptr(self, item: QTreeWidgetItem, file_id: int, path_id: int, assets_file) -> None:
        # Real reported request: FileID/PathID moved off the PPtr row itself
        # and in here as real child rows instead (see _add_field_item, which
        # no longer puts them in the row's own value_text) — added BEFORE the
        # resolve attempt below, and unconditionally (not just on success), so
        # a dangling/unresolvable reference still shows its raw values instead
        # of only the (name-less) error message — useful for diagnosing WHY
        # it didn't resolve (e.g. an out-of-range FileID). FileID's value
        # additionally names the file it points to, parenthesized right next
        # to the number — the whole reason to resolve a PPtr in the first
        # place is usually "what does this actually point at", and the file
        # half of that answer costs nothing extra to compute (see
        # _resolve_pptr_file_name) even before knowing whether the PathID
        # half resolves to a real object at all.
        file_name = self._resolve_pptr_file_name(file_id, assets_file)
        self._make_item(item, name="FileID", type_text="int", value_text=f"{file_id} ({file_name})")
        self._make_item(item, name="PathID", type_text="int", value_text=str(path_id))

        try:
            ref_obj = PPtr(m_FileID=file_id, m_PathID=path_id, assetsfile=assets_file).deref()
            ref_node = ref_obj._get_typetree_node()
            ref_data = ref_obj.parse_as_dict()
        except Exception as e:
            # Wrapped in a span so the delegate (which reads any "<" as markup) shows the message
            # instead of swallowing "<не удалось…>" as an unknown tag, which left a blank row.
            QTreeWidgetItem(item, [f"<span>{_html_escape(tr('<не удалось открыть ссылку: {error}>', error=e))}</span>"])
            return
        # Lazy, same as every other compound field (_add_field_item's own
        # "class" branch) — real reported bug: this used to populate AND
        # expand the referenced object's fields immediately, so opening one
        # PPtr landed a whole object's worth of fields on the user at once
        # instead of the single "→ RectTransform, PathID 5" line one more
        # deliberate click away, exactly like drilling into any other nested
        # object already works. boundary=True tints this row's background
        # (theme.py's `surface` color) so it visually reads as "a different
        # object starts here" in a long expanded tree, not just another bold
        # PPtr-styled line like the row above it.
        header = self._make_item(
            item, name="→", type_text=ref_obj.type.name, value_text=f"PathID {ref_obj.path_id}", boundary=True,
        )
        # Real reported request: this resolved-object header row is itself
        # expandable (it's what you land on right after opening a PPtr), so it
        # should get the exact same context menu (Edit/Jump) as the PPtr row
        # above it — no more scrolling back up just to act on what you already
        # resolved. Same (file_id, path_id, assets_file) triple the original
        # PPtr row was given — re-deref'ing it in _show_context_menu()
        # reproduces this exact ref_obj, no separate resolution path needed.
        header.setData(0, self._PPTR_REF_ROLE, (file_id, path_id, assets_file))
        if ref_node.m_Children:
            header.setData(0, self._KIND_ROLE, "class")
            header.setData(0, self._NODE_ROLE, ref_node)
            header.setData(0, self._VALUE_ROLE, _QtOpaque(ref_data))
            header.setData(0, self._ASSETS_ROLE, ref_obj.assets_file)
            header.addChild(QTreeWidgetItem(["..."]))

    # --- PPtr row context menu ---

    def _show_context_menu(self, pos) -> None:
        """Real reported request: a PPtr row needed a way to act on the
        object it references without first expanding it — "Отредактировать
        данные" and "Перейти к объекту" (in the main table). Resolved here via
        the exact same PPtr(...).deref() call _expand_pptr() already uses (no
        separate resolution mechanism), regardless of whether the item is the
        original (collapsed-or-not) PPtr row or the resolved-object header row
        _expand_pptr() creates once expanded — both carry the same
        _PPTR_REF_ROLE triple, set once at creation and never cleared, unlike
        _KIND_ROLE. (A third "Информация о файле" entry lived here briefly —
        moved to Инструменты → "Информация о файле..." in main.py instead,
        since letting the user pick ANY loaded file is more useful than one
        scoped to whatever PPtr happens to be under the cursor.)

        Real reported oversight, fixed alongside: a top-level "Base" root row
        (set_object()'s single root, or one of set_objects()'s per-component
        roots) carries no _PPTR_REF_ROLE at all — it's not a pointer to
        anything, it just IS the object being shown — so right-clicking it
        did nothing. It carries _SELF_REF_ROLE instead (the real ObjectReader
        directly, no deref() needed since there's no PPtr to resolve), which
        gets the exact same two actions.

        Every row, with or without an object behind it, also gets "Копировать строку" (the line's
        text as shown, without markup) — alone when the row has no object to act on, otherwise
        below a separator."""
        item = self.itemAt(pos)
        if item is None:
            return
        ref_obj = None
        ref = item.data(0, self._PPTR_REF_ROLE)
        if ref is not None:
            file_id, path_id, assets_file = ref
            try:
                ref_obj = PPtr(m_FileID=file_id, m_PathID=path_id, assetsfile=assets_file).deref()
            except Exception as e:
                # The row can still be copied: the menu below just has no object actions.
                QMessageBox.warning(self, tr("Переход к объекту"), tr("Не удалось найти объект по ссылке:\n{error}", error=e))
        else:
            ref_obj = item.data(0, self._SELF_REF_ROLE)

        # Real reported gap: this menu's items had no icons at all, unlike every
        # other context menu in the app (object_actions.py's main-table menu,
        # tools/text_search_tool.py's own "Перейти к объекту" entry) — matches
        # the SAME two conventions those already use rather than inventing a
        # third: get_action_icon("edit") for the edit action (identical to
        # object_actions.py's own act_edit), and the target object's own TYPE
        # icon (get_type_icon(ref_obj.type.name)) for "jump to it" — the same
        # "go-to" = "icon of what you're going to" convention
        # text_search_tool.py's act_goto already established, since there's no
        # dedicated generic "jump/goto" glyph in type_icons.py to reuse instead.
        menu = QMenu(self)
        act_edit = act_jump = None
        if ref_obj is not None:
            act_edit = menu.addAction(get_action_icon("edit"), tr("Отредактировать данные"))
            act_jump = menu.addAction(get_type_icon(ref_obj.type.name), tr("Перейти к объекту в таблице"))
            menu.addSeparator()
        act_copy = menu.addAction(get_action_icon("copy"), tr("Копировать строку"))
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen is act_copy:
            QApplication.clipboard().setText(self.line_text(item))
        elif chosen is act_edit:
            self.edit_requested.emit(ref_obj)
        elif chosen is act_jump:
            self.jump_requested.emit(ref_obj)

    @staticmethod
    def line_text(item: QTreeWidgetItem) -> str:
        """The row's text as the user reads it: a coloured row stores HTML (see _build_html), which
        is flattened back to plain text; every other row's text is already plain."""
        text = item.text(0)
        if "<span" in text or text.startswith("<b>"):
            doc = QTextDocument()
            doc.setHtml(text)
            return doc.toPlainText()
        return text


class SceneHierarchyTree(_HorizontalScrollStableTreeWidget):
    """The Scene Viewer tool's left pane — a GameObject/Transform hierarchy
    tree, built from core.scene_hierarchy.build_scene_hierarchy(). The SceneNodes
    are all there from the start, but a row's child ROWS are created only when
    it is first expanded (Truck-kun level3: 88k QTreeWidgetItems + measuring
    them all took 1.3-3.8 s on every open); a row with children shows its
    arrow before that (ShowIndicator). find_next()/highlight_object()/
    refresh_item_name() therefore walk the SceneNodes, not the rows, and create
    the rows down to a match only when they need to show it.

    Reuses _HorizontalScrollStableTreeWidget's per-pixel scrolling/scrollTo()
    pin/_reveal_branch_horizontally() for the same "expanding a branch reveals
    deeper content off the right edge of the viewport" reason
    ObjectStructureTree needed them for — same request, same fix, this time
    for GameObject names deep in a scene instead of TypeTree field paths."""

    # SceneNode stored per top-level QTreeWidgetItem — read back on selection
    # to resolve the GameObject's components (see object_selected below).
    _NODE_ROLE = Qt.ItemDataRole.UserRole
    # (source_name, path_id) — the GameObject's own logical identity, matching
    # main.py._jump_to_object's own (source, path_id) convention (not Python
    # object identity — see that method's docstring for why: UnityPy can
    # replace an already-loaded file's ObjectReader instances on a later
    # reload). Used by highlight_object() to find the right row to select.
    _IDENTITY_ROLE = Qt.ItemDataRole.UserRole + 1
    # True once a row's child rows exist (see _ensure_children).
    _POPULATED_ROLE = Qt.ItemDataRole.UserRole + 2

    # Emitted whenever the current selection changes to a row with a resolved
    # GameObject — carries that GameObject's own ObjectReader (never the bare
    # Transform, and never emitted at all for a row whose GameObject didn't
    # resolve, since there's nothing meaningful to show components for).
    object_selected = pyqtSignal(object)
    # Emitted by the right-click menu's "Перейти к объекту в таблице" — the
    # row's GameObject ObjectReader (same payload/contract as
    # ObjectStructureTree.jump_requested, so the same MainWindow handler serves both).
    jump_requested = pyqtSignal(object)
    edit_requested = pyqtSignal(object)  # "Отредактировать данные" — the GameObject's ObjectReader

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.itemExpanded.connect(self._on_item_expanded)
        self.currentItemChanged.connect(self._on_current_item_changed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.header().setStretchLastSection(False)  # see _resize_to_contents()
        self.itemCollapsed.connect(self._on_item_collapsed)
        self._source_name = None
        self._roots = []

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        node = item.data(0, self._NODE_ROLE) if item is not None else None
        go = getattr(node, "game_object_obj", None)
        if go is None:
            return  # the row's GameObject didn't resolve — nothing to jump to
        menu = QMenu(self)
        act_edit = menu.addAction(get_action_icon("edit"), tr("Отредактировать данные"))
        act_jump = menu.addAction(get_type_icon("GameObject"), tr("Перейти к объекту в таблице"))
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is act_edit:
            self.edit_requested.emit(go)
        elif chosen is act_jump:
            self.jump_requested.emit(go)

    def refresh_item_name(self, game_object_obj) -> None:
        """Re-reads a GameObject's own m_Name into its SceneNode (and its row,
        if that row exists yet) — called after the data editor changed it, so
        the hierarchy label doesn't keep showing the old name until the tree
        is rebuilt."""
        path_id = getattr(game_object_obj, "path_id", None)
        path = self._path_to(lambda n: n.game_object_obj is not None and n.game_object_obj.path_id == path_id)
        if path is None:
            return
        try:
            new_name = game_object_obj.peek_name()
        except Exception:
            new_name = None
        if not new_name:
            return
        self._node_at(path).name = new_name
        item = self._item_at(path, create=False)
        if item is not None:
            item.setText(0, new_name)

    def set_roots(self, nodes: list, source_name: str) -> None:
        """Shows one file's worth of SceneNodes (core.scene_hierarchy.
        build_scene_hierarchy's return value): only the root rows are created
        here, child rows on first expansion. source_name is stored per-item for
        highlight_object()'s (source, path_id) matching — the tree itself
        doesn't otherwise care which file it's showing."""
        self.clear()
        self._source_name = source_name
        self._roots = list(nodes)
        for node in self._roots:
            self._add_node(self, node)
        self._resize_to_contents()

    def _add_node(self, parent, node) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [node.name])
        item.setData(0, self._NODE_ROLE, node)
        go = node.game_object_obj
        if go is not None:
            item.setData(0, self._IDENTITY_ROLE, (self._source_name, go.path_id))
        if node.children:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        return item

    def _ensure_children(self, item: QTreeWidgetItem) -> None:
        if item.data(0, self._POPULATED_ROLE):
            return
        item.setData(0, self._POPULATED_ROLE, True)
        node = item.data(0, self._NODE_ROLE)
        for child in getattr(node, "children", ()):
            self._add_node(item, child)

    def expandAll(self) -> None:
        """Every row has to exist before Qt can expand it."""
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop()
            self._ensure_children(item)
            stack.extend(item.child(i) for i in range(item.childCount()))
        super().expandAll()

    # --- SceneNode paths: (index among the roots, index among its children, ...) ---

    def _walk(self):
        """(path, node) for every SceneNode in display (pre-)order."""
        stack = [((i,), n) for i, n in reversed(list(enumerate(self._roots)))]
        while stack:
            path, node = stack.pop()
            yield path, node
            stack.extend((path + (i,), c) for i, c in reversed(list(enumerate(node.children))))

    def _path_to(self, predicate) -> Optional[tuple]:
        for path, node in self._walk():
            if predicate(node):
                return path
        return None

    def _node_at(self, path: tuple):
        node = self._roots[path[0]]
        for i in path[1:]:
            node = node.children[i]
        return node

    def _item_at(self, path: tuple, create: bool = True) -> Optional[QTreeWidgetItem]:
        """The row for `path`, creating the rows on the way when `create` (they stay collapsed)."""
        item = self.topLevelItem(path[0])
        for i in path[1:]:
            if item is None:
                return None
            if not item.data(0, self._POPULATED_ROLE):
                if not create:
                    return None
                self._ensure_children(item)
            item = item.child(i)
        return item

    def _path_of_item(self, item: QTreeWidgetItem) -> tuple:
        path = []
        while item is not None:
            parent = item.parent()
            path.append(parent.indexOfChild(item) if parent is not None else self.indexOfTopLevelItem(item))
            item = parent
        return tuple(reversed(path))

    def _resize_to_contents(self) -> None:
        # The column must follow the REAL widest visible row: with the header's
        # default stretch-last-section it is never narrower than the viewport, and
        # it was only sized once (collapsed, roots only), so after expanding deep
        # branches nothing was wider than the viewport and no horizontal scrollbar
        # ever appeared. The scroll position is kept across the resize.
        bar = self.horizontalScrollBar()
        pos = bar.value()
        self.resizeColumnToContents(0)
        bar.setValue(pos)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        self._ensure_children(item)
        self._resize_to_contents()
        self._reveal_branch_horizontally(item)

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        # Deferred: collapseAll() emits this per item before every row has
        # actually collapsed, so measuring right now would see stale widths.
        QTimer.singleShot(0, self._resize_to_contents)

    def _on_current_item_changed(self, current: Optional[QTreeWidgetItem], previous) -> None:
        node = current.data(0, self._NODE_ROLE) if current is not None else None
        if node is not None and node.game_object_obj is not None:
            self.object_selected.emit(node.game_object_obj)

    # --- search ("Enter" / "Далее" in the Scene Viewer dialog) ---

    def find_next(self, text: str) -> bool:
        """Case-insensitive substring search over EVERY GameObject name in the
        hierarchy (its SceneNodes — rows never expanded do not exist yet),
        starting just after the current selection and wrapping around —
        repeated calls (the dialog's "Далее" button, or pressing Enter again)
        cycle through every match in order. Returns False (and leaves the
        selection alone) when nothing matches or the query is empty, so the
        dialog can show a clear "not found" instead of silently doing nothing."""
        needle = text.strip().lower()
        if not needle:
            return False
        entries = list(self._walk())
        if not entries:
            return False
        start = 0
        current = self.currentItem()
        if current is not None:
            current_path = self._path_of_item(current)
            for i, (path, _node) in enumerate(entries):
                if path == current_path:
                    start = i + 1
                    break
        n = len(entries)
        for offset in range(n):
            path, node = entries[(start + offset) % n]
            if needle in node.name.lower():
                self._select_path(path)
                return True
        return False

    def _select_path(self, path: tuple) -> None:
        item = self._item_at(path)
        self._reveal_item(item)
        self.setCurrentItem(item)

    def _reveal_item(self, item: QTreeWidgetItem) -> None:
        ancestor = item.parent()
        while ancestor is not None:
            ancestor.setExpanded(True)
            ancestor = ancestor.parent()
        self.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

    def highlight_object(self, source_name: str, path_id: int) -> bool:
        """Selects and scrolls to the GameObject row matching (source_name,
        path_id) — same identity convention as main.py._jump_to_object(),
        used when the "GameObject Viewer" toolbar button opens this dialog for
        a specific object already selected in the main table's preview.
        Returns False (nothing selected) if this file's hierarchy has no
        matching row — e.g. the object is a MonoBehaviour/other non-GameObject
        type, or genuinely isn't in this particular file's Transform graph."""
        if source_name != self._source_name:
            return False
        path = self._path_to(lambda n: n.game_object_obj is not None and n.game_object_obj.path_id == path_id)
        if path is None:
            return False
        self._select_path(path)
        return True
