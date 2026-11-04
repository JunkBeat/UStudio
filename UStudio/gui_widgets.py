"""Small reusable GUI widget helpers: the eliding-label pattern (CabBrowserDialog
previously redefined a path-label and a status-label copy of the same
elide-with-tooltip-fallback logic), and the preview-panel widgets used by
preview_panel.py's Preview tab (ImagePreviewWidget/TextureZoomDialog,
AudioPreviewWidget, FontPreviewWidget, ObjectStructureTree, and the PIL-to-QPixmap
conversion several of them need)."""

# The widgets live in the gui_*_widgets modules; everything is re-exported here so
# `from gui_widgets import X` keeps working.
# ruff: noqa: F401
from gui_tree_widgets import (
    ObjectStructureTree, SceneHierarchyTree, _HorizontalScrollStableTreeWidget, _PRIMITIVE_TYPES,
    _QtOpaque, _RichTextItemDelegate, _TREE_MAX_ARRAY_ITEMS,
)
from gui_common import (
    TextFindBar, _mute_button_icon, _reapply, _refresh_transport_icons,
    _transport_icon_color, pil_to_qpixmap, reapply_elided_labels, set_elided_label_text,
)
from gui_table_widgets import (
    ObjectTableView, SDFGroupSpacingDelegate, TaskQueueStatusWidget,
)
from gui_image_widgets import (
    CompactSummaryBar, FontPreviewWidget, ImagePreviewWidget, TextureZoomDialog,
)
from gui_media_widgets import (
    AudioPreviewWidget, ClickableSeekSlider, VideoPreviewWidget,
)
