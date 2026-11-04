"""What the «Инструменты» menu opens (dialogs/ holds the dialogs reached from elsewhere)."""

from .text_search_tool import TextSearchDialog
from .field_table_tool import FieldTableDialog
from .patch_relocation_tool import PatchRelocationDialog
from .quick_jump_dialog import QuickJumpDialog
from .scene_viewer_dialog import SceneViewerDialog
from .version_writer_dialog import VersionWriterDialog

__all__ = [
    "TextSearchDialog",
    "FieldTableDialog",
    "PatchRelocationDialog",
    "QuickJumpDialog",
    "SceneViewerDialog",
    "VersionWriterDialog",
]
