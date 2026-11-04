"""ScriptListDialog — a scrollable list editor for the script names of a quick filter (opened by the «Список…»
button next to the one-line "scripts, comma separated" field of QuickFilterSettingsDialog).

A one-line comma-separated field is awkward once a filter names more than two or three scripts: it cannot be
scanned, one name cannot be removed without retyping the line, and a typo hides in the middle. Here every name is
its own row: type a name and press Enter (or «Добавить») to add it; pasting a comma/semicolon/newline separated
list adds each name; select rows and press «Удалить» or Delete to remove them; double-click a row (or F2) to
correct a name in place. Duplicates are skipped silently and the existing row is selected instead, so it is
visible why nothing was added."""

from core.i18n import tr
import re
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

_SPLIT = re.compile(r"[,;\n\r]+")


def split_names(text: str) -> List[str]:
    """Names in a pasted/typed string, trimmed, empty pieces dropped (order kept)."""
    return [part.strip() for part in _SPLIT.split(text) if part.strip()]


class ScriptListDialog(QDialog):
    def __init__(self, names: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Скрипты MonoBehaviour"))
        self.resize(380, 420)

        layout = QVBoxLayout(self)
        hint = QLabel(tr("Введите имя в формате m_ClassName или m_Namespace.m_ClassName. Можно вставить сразу несколько через запятую."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        add_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("Имя скрипта и Enter"))
        self.input.returnPressed.connect(self._add_from_input)
        add_row.addWidget(self.input, 1)
        self.btn_add = QPushButton(tr("Добавить"))
        self.btn_add.clicked.connect(self._add_from_input)
        add_row.addWidget(self.btn_add)
        layout.addLayout(add_row)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list_widget.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.list_widget, 1)

        bottom = QHBoxLayout()
        self.btn_remove = QPushButton(tr("Удалить"))
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton(tr("Очистить"))
        self.btn_clear.clicked.connect(self._clear)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: gray;")
        bottom.addWidget(self.btn_remove)
        bottom.addWidget(self.btn_clear)
        bottom.addStretch()
        bottom.addWidget(self.count_label)
        layout.addLayout(bottom)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for name in names:
            self._append(name)
        self._update_buttons()
        self.input.setFocus()

    # ------------------------------------------------------------------ editing
    def _make_item(self, name: str) -> QListWidgetItem:
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def _find(self, name: str):
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).text() == name:
                return self.list_widget.item(i)
        return None

    def _append(self, name: str):
        """Adds `name` unless already listed; returns the (new or existing) row."""
        existing = self._find(name)
        if existing is not None:
            return existing
        item = self._make_item(name)
        self.list_widget.addItem(item)
        return item

    def _add_from_input(self) -> None:
        last = None
        for name in split_names(self.input.text()):
            last = self._append(name)
        self.input.clear()
        if last is not None:
            self.list_widget.setCurrentItem(last)       # also shows the existing row of a duplicate
            self.list_widget.scrollToItem(last)
        self._update_buttons()
        self.input.setFocus()

    def _remove_selected(self) -> None:
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))
        self._update_buttons()

    def _clear(self) -> None:
        self.list_widget.clear()
        self._update_buttons()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete and self.list_widget.hasFocus():
            self._remove_selected()
            return
        super().keyPressEvent(event)

    def _update_buttons(self) -> None:
        count = self.list_widget.count()
        self.btn_remove.setEnabled(bool(self.list_widget.selectedItems()))
        self.btn_clear.setEnabled(count > 0)
        self.count_label.setText(tr("Скриптов: {count}", count=count) if count else "")

    # ------------------------------------------------------------------ result
    def get_names(self) -> List[str]:
        """The names in list order: trimmed, empty ones (an edited-away row) dropped, duplicates (a row edited
        into an existing name) kept once."""
        seen = set()
        out: List[str] = []
        for i in range(self.list_widget.count()):
            name = self.list_widget.item(i).text().strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out
