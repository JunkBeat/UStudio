"""Application Settings → Настройки индексации's "Выбрать типы объектов..."
button — a search-filtered checklist of every Unity type UnityPy knows about,
picking which ones core/loader.py's build_row_item() turns into table rows
(CONFIG.indexed_types). Same list-source and search-filter pattern as
dialogs/quick_filter_settings_dialog.py's own types_list (a few lines,
duplicated rather than imported — no reason to couple two otherwise-unrelated
dialogs over one list comprehension)."""

from core.i18n import tr
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from UnityPy.enums import ClassIDType

# Every Unity class ID UnityPy knows about — same source dialogs/quick_filter_settings_dialog.py
# uses for the same reason: the user should be able to index a type outside the
# curated RICH_PREVIEW_TYPES default, not just narrow within it.
_AVAILABLE_TYPES = sorted({member.name for member in ClassIDType})


class IndexedTypesDialog(QDialog):
    def __init__(self, parent, selected_types: List[str]):
        super().__init__(parent)
        self.setWindowTitle(tr("Типы объектов для индексации"))
        self.setModal(True)
        self.resize(420, 480)

        selected = set(selected_types)
        layout = QVBoxLayout(self)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(tr("Поиск типа..."))
        self.filter_edit.textChanged.connect(self._filter_list)
        layout.addWidget(self.filter_edit)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for type_name in _AVAILABLE_TYPES:
            item = QListWidgetItem(type_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if type_name in selected else Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        select_row = QHBoxLayout()
        btn_select_all = QPushButton(tr("Выбрать всё"))
        btn_select_all.clicked.connect(lambda: self._set_all_checked(Qt.CheckState.Checked))
        btn_select_none = QPushButton(tr("Снять всё"))
        btn_select_none.clicked.connect(lambda: self._set_all_checked(Qt.CheckState.Unchecked))
        select_row.addWidget(btn_select_all)
        select_row.addWidget(btn_select_none)
        select_row.addStretch(1)
        layout.addLayout(select_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        btn_apply = QPushButton(tr("Применить"))
        btn_apply.clicked.connect(self._on_apply)
        btn_cancel = QPushButton(tr("Отмена"))
        btn_cancel.clicked.connect(self.reject)
        button_row.addWidget(btn_apply)
        button_row.addWidget(btn_cancel)
        layout.addLayout(button_row)

    def _on_apply(self) -> None:
        # Refuses an empty selection rather than silently accepting it —
        # CONFIG.indexed_types=[] would still be handled safely elsewhere
        # (EnvironmentLoader.parse_objects() falls back to RICH_PREVIEW_TYPES),
        # but "select nothing, index nothing" is confusing to end up with by
        # accident and gives no indication anything is wrong until a later
        # load looks empty — same "empty selection is a worse default" call
        # TypeChecklistDialog already makes elsewhere, just enforced up front
        # here instead of papered over by a fallback.
        if not self.get_selected_types():
            QMessageBox.warning(
                self, tr("Ничего не выбрано"),
                tr("Выберите хотя бы один тип объекта, либо нажмите «Отмена»."),
            )
            return
        self.accept()

    def _filter_list(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _set_all_checked(self, state: Qt.CheckState) -> None:
        # Only visible (non-filtered-out) rows — mirrors the intuitive "select
        # what I'm looking at" behavior rather than silently also toggling
        # rows currently hidden by the search filter.
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(state)

    def get_selected_types(self) -> List[str]:
        return [
            self.list_widget.item(i).text()
            for i in range(self.list_widget.count())
            if self.list_widget.item(i).checkState() == Qt.CheckState.Checked
        ]
