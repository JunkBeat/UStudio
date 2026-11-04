from core.i18n import tr
from typing import List, Optional, Tuple

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QLineEdit, QDialogButtonBox, QMessageBox
)


class QuickJumpDialog(QDialog):
    """File ID (every distinct `source` value currently loaded, see
    core/models.py's RowItem — the internal SerializedFile's own name, e.g.
    "level0"/"sharedassets0.assets"/a cab-xxxx name) + PathID + OK/Cancel,
    same minimal skeleton as settings_dialogs.py's InputSettingDialog.
    PathID is a plain QLineEdit rather than a
    QSpinBox: real Unity path_ids can exceed a QSpinBox's 32-bit C++ int
    range (see CLAUDE.md's own note on QProgressBar's 32-bit int limit for
    the same underlying reason) — parsed as a Python int (arbitrary
    precision, including negative) on accept instead."""

    def __init__(self, parent, sources: List[str]):
        super().__init__(parent)
        self.setWindowTitle(tr("Переход к объекту"))
        self.setModal(True)
        self.resize(420, 150)
        self._path_id: Optional[int] = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(tr("Файл (File ID):")))
        self.combo_source = QComboBox()
        self.combo_source.addItems(sources)
        layout.addWidget(self.combo_source)

        layout.addWidget(QLabel("PathID:"))
        self.edit_path_id = QLineEdit()
        self.edit_path_id.setPlaceholderText(tr("например, 123456789"))
        layout.addWidget(self.edit_path_id)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def showEvent(self, event) -> None:
        """Real reported request: focus the PathID field automatically, so a
        user who already knows the number (the common case — File ID rarely
        needs changing from whatever's first in the list) can start typing
        immediately instead of clicking into the field first. Set here rather
        than in __init__: Qt's own show()/exec() machinery assigns initial
        focus (normally landing on the first tab-stop widget, the combo box)
        AFTER __init__ runs, which would silently override a setFocus() call
        made too early."""
        super().showEvent(event)
        self.edit_path_id.setFocus()

    def _on_accept(self):
        text = self.edit_path_id.text().strip()
        try:
            self._path_id = int(text)
        except ValueError:
            QMessageBox.warning(self, tr("Переход к объекту"), tr("PathID должен быть целым числом."))
            return
        self.accept()

    def get_values(self) -> Tuple[str, int]:
        return self.combo_source.currentText(), self._path_id
