"""«Настроить наборы…» in the quick filters bar's type drop-down — add/remove/edit the presets
(label, optional icon, which types/scripts they show), see core/quick_filters.py for the underlying
QuickFilterDef shape and quick_filters_bar.py for how the bar applies them. «Only modified objects» is
the bar's own toggle, not a preset (it used to be a special button made here). Master-detail layout: the
presets on the left, one editable form on the right — switching the list selection commits whatever's in
the form for the PREVIOUSLY selected entry first, so nothing is lost by clicking around."""

from core.i18n import tr
import uuid
from typing import List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from UnityPy.enums import ClassIDType

from core.quick_filters import QuickFilterDef
from helpers import wrap_tooltip
from type_icons import builtin_icon_caption
from .icon_picker import IconPickerButton
from .script_list_dialog import ScriptListDialog, split_names
from gui_common import exec_and_dispose

# Every Unity class ID UnityPy knows about, not just RICH_PREVIEW_TYPES (the
# curated subset that actually gets a table row by default — see
# core/loader.py's build_row_item()) — a quick filter is allowed to name a
# type outside that subset, it just won't show anything unless CONFIG.
# load_all_assets is also on. Real reported request: the type list here was
# artificially narrow.
_AVAILABLE_TYPES = sorted({member.name for member in ClassIDType})


class QuickFilterSettingsDialog(QDialog):
    def __init__(self, definitions: List[QuickFilterDef], parent=None, initial_row: Optional[int] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Наборы фильтров"))
        self.resize(560, 420)

        # Working copy — the caller's list is only replaced (via
        # get_definitions()) if the dialog is Accepted.
        self._definitions: List[QuickFilterDef] = [
            QuickFilterDef(**{**vars(d)}) for d in definitions
        ]
        self._current_index: Optional[int] = None

        root = QHBoxLayout()

        left = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self.list_widget)

        add_remove_row = QHBoxLayout()
        btn_add = QPushButton(tr("Добавить"))
        btn_add.clicked.connect(self._add_definition)
        btn_remove = QPushButton(tr("Удалить"))
        btn_remove.clicked.connect(self._remove_current)
        add_remove_row.addWidget(btn_add)
        add_remove_row.addWidget(btn_remove)
        left.addLayout(add_remove_row)

        move_row = QHBoxLayout()
        self.btn_up = QPushButton(tr("▲ Вверх"))
        self.btn_up.clicked.connect(self._move_current_up)
        self.btn_down = QPushButton(tr("▼ Вниз"))
        self.btn_down.clicked.connect(self._move_current_down)
        move_row.addWidget(self.btn_up)
        move_row.addWidget(self.btn_down)
        left.addLayout(move_row)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.label_edit = QLineEdit()
        self.label_edit.editingFinished.connect(self._commit_current)
        form.addRow(tr("Название:"), self.label_edit)

        # The icon: automatic (by the preset's first type) unless one is picked — a built-in icon,
        # or a symbol of the user's own (see dialogs/icon_picker.py). Shown beside the preset's name
        # in the type drop-down.
        self._icon_value = ""
        self.icon_button = IconPickerButton()
        self.icon_button.value_changed.connect(self._on_icon_chosen)
        form.addRow(tr("Иконка:"), self.icon_button)

        right.addLayout(form)

        # Types list and the scripts field are stacked as their own
        # label-then-widget blocks below the form, not addRow()'d into it —
        # QFormLayout places label and field SIDE BY SIDE on one row, which
        # reads wrong for a tall QListWidget (real reported feedback: the
        # visual hierarchy was off). Same label wording as before.
        types_label = QLabel(tr("Типы объектов:"))
        right.addWidget(types_label)

        # ~368 entries (every UnityPy ClassIDType, not just the curated
        # preview subset) is too many to scan by eye — a live substring
        # filter is the natural companion to widening the list this much.
        self.types_filter_edit = QLineEdit()
        self.types_filter_edit.setPlaceholderText(tr("Поиск типа..."))
        self.types_filter_edit.textChanged.connect(self._filter_types_list)
        right.addWidget(self.types_filter_edit)

        self.types_list = QListWidget()
        self.types_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.types_list.setMaximumHeight(160)
        for type_name in _AVAILABLE_TYPES:
            item = QListWidgetItem(type_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.types_list.addItem(item)
        self.types_list.itemChanged.connect(lambda _item: self._commit_current())
        right.addWidget(self.types_list)

        scripts_label = QLabel(tr("Скрипты MonoBehaviour (через запятую):"))
        right.addWidget(scripts_label)

        self.scripts_edit = QLineEdit()
        self.scripts_edit.setPlaceholderText(tr("напр., TMP_FontAsset. Пусто = без ограничений"))
        # A bare name matches every script with that name, even if the game
        # has more than one (see core.object_common.row_matches_script_selector()).
        # If that's too broad, "Пространство_имён.Имя" narrows it to one.
        self.scripts_edit.setToolTip(wrap_tooltip(
            tr("Обычно достаточно имени скрипта, например TMP_FontAsset. Если в игре есть два разных скрипта с "
               "одинаковым именем, уточните через точку: ПространствоИмён.ИмяСкрипта.")
        ))
        self.scripts_edit.editingFinished.connect(self._commit_current)
        # The one-line field is fine for one name, awkward for several: the button opens a scrollable
        # list with add / remove / edit-in-place (dialogs/script_list_dialog.py). Both edit the same
        # value, so either can be used.
        scripts_row = QHBoxLayout()
        scripts_row.addWidget(self.scripts_edit, 1)
        self.scripts_button = QPushButton(tr("Список…"))
        self.scripts_button.setToolTip(wrap_tooltip(tr("Открыть список скриптов: добавлять и удалять имена по одному.")))
        self.scripts_button.clicked.connect(self._edit_scripts_list)
        scripts_row.addWidget(self.scripts_button)
        right.addLayout(scripts_row)

        right.addStretch()
        root.addLayout(right, 2)

        outer = QVBoxLayout(self)
        outer.addLayout(root)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._reload_list()
        if self._definitions:
            # Real reported gap: a fresh QuickFilterSettingsDialog instance is
            # constructed every time it is opened, so this used
            # to always jump back to row 0 regardless of which entry was last
            # being edited earlier in the same app session. `initial_row`
            # lets the caller (QuickFiltersBar) remember and restore it —
            # clamped here since the definitions list could have shrunk
            # (an entry removed) since that row was last recorded.
            row = initial_row if initial_row is not None and 0 <= initial_row < len(self._definitions) else 0
            self.list_widget.setCurrentRow(row)
        else:
            self._set_form_enabled(False)
            self._update_move_buttons()

    # --- list <-> form ---

    def _reload_list(self) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for d in self._definitions:
            item = QListWidgetItem(tr(d.label))      # the icon column carries the icon: no symbol in the text
            item.setIcon(self._icon_for(d))
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (self.label_edit, self.icon_button, self.types_filter_edit,
                  self.types_list, self.scripts_edit, self.scripts_button):
            w.setEnabled(enabled)

    def _filter_types_list(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.types_list.count()):
            item = self.types_list.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())
        self.types_list.scrollToTop()

    def _on_row_changed(self, row: int) -> None:
        self._commit_current()
        if row < 0 or row >= len(self._definitions):
            self._current_index = None
            self._set_form_enabled(False)
            self._update_move_buttons()
            return
        self._set_form_enabled(True)
        self._current_index = row
        self._update_move_buttons()
        d = self._definitions[row]

        self.label_edit.blockSignals(True)
        self.label_edit.setText(tr(d.label))
        self.label_edit.blockSignals(False)

        self._icon_value = d.icon
        self._refresh_icon_button(d)

        self.types_list.blockSignals(True)
        for i in range(self.types_list.count()):
            item = self.types_list.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.text() in d.types else Qt.CheckState.Unchecked)
        self.types_list.blockSignals(False)

        self.scripts_edit.blockSignals(True)
        self.scripts_edit.setText(", ".join(d.scripts) if d.scripts else "")
        self.scripts_edit.blockSignals(False)

    def _edit_scripts_list(self) -> None:
        dlg = ScriptListDialog(split_names(self.scripts_edit.text()), self)
        if exec_and_dispose(dlg) == QDialog.DialogCode.Accepted:
            self.scripts_edit.setText(", ".join(dlg.get_names()))
            self._commit_current()

    def _commit_current(self) -> None:
        """Writes the form's current values back into self._definitions[self._current_index]
        — called on every meaningful form edit (not just on OK), so switching
        the list selection or clicking Add/Remove never silently discards an
        in-progress edit."""
        if self._current_index is None or not (0 <= self._current_index < len(self._definitions)):
            return
        old = self._definitions[self._current_index]
        types = tuple(
            self.types_list.item(i).text()
            for i in range(self.types_list.count())
            if self.types_list.item(i).checkState() == Qt.CheckState.Checked
        )
        raw_scripts = [s.strip() for s in self.scripts_edit.text().split(",") if s.strip()]
        scripts = tuple(raw_scripts) if raw_scripts else None

        new = QuickFilterDef(
            key=old.key,
            label=(old.label if self.label_edit.text().strip() in ("", tr(old.label))
                   else self.label_edit.text().strip()),
            types=types,
            scripts=scripts,
            color=old.color,  # no UI to change this anymore — carried over unchanged, see the module docstring
            special=None,
            icon=self._icon_value,
        )
        self._definitions[self._current_index] = new
        item = self.list_widget.item(self._current_index)
        if item is not None:
            item.setText(tr(new.label))
            item.setIcon(self._icon_for(new))
        self._refresh_icon_button(new)

    def _icon_for(self, definition: QuickFilterDef):
        from PyQt6.QtGui import QIcon
        from quick_filters_bar import filter_visual
        icon, _text = filter_visual(definition)
        return icon if icon is not None else QIcon()

    def _refresh_icon_button(self, definition: QuickFilterDef) -> None:
        """The button shows what the bar will show — for the automatic choice that depends on the
        filter's types, so it is refreshed on every commit."""
        if not definition.icon:
            caption = tr("Авто")
        elif definition.builtin_icon_key is not None:
            caption = builtin_icon_caption(definition.builtin_icon_key)
        else:
            caption = tr("Свой символ")      # the symbol itself is already drawn as the icon beside it
        self.icon_button.set_state(definition.icon, self._icon_for(definition), caption)

    def _on_icon_chosen(self, value: str) -> None:
        self._icon_value = value
        self._commit_current()

    # --- add/remove ---

    def _add_definition(self) -> None:
        self._commit_current()
        new_def = QuickFilterDef(key=f"custom_{uuid.uuid4().hex[:8]}", label=tr("Новый набор"))
        self._definitions.append(new_def)
        item = QListWidgetItem(tr(new_def.label))
        self.list_widget.addItem(item)
        self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def _remove_current(self) -> None:
        if self._current_index is None:
            return
        row = self._current_index
        self._current_index = None  # prevent _commit_current() from writing into a row we're about to delete
        del self._definitions[row]
        self.list_widget.takeItem(row)
        if self._definitions:
            self.list_widget.setCurrentRow(min(row, len(self._definitions) - 1))
        else:
            self._set_form_enabled(False)
            self._update_move_buttons()

    # --- reorder ---

    def _update_move_buttons(self) -> None:
        row = self._current_index
        self.btn_up.setEnabled(row is not None and row > 0)
        self.btn_down.setEnabled(row is not None and row < len(self._definitions) - 1)

    def _move_current_up(self) -> None:
        self._move_current(-1)

    def _move_current_down(self) -> None:
        self._move_current(1)

    def _move_current(self, offset: int) -> None:
        self._commit_current()
        row = self._current_index
        if row is None:
            return
        new_row = row + offset
        if not (0 <= new_row < len(self._definitions)):
            return
        self._definitions[row], self._definitions[new_row] = self._definitions[new_row], self._definitions[row]
        self._current_index = None  # about to reselect via setCurrentRow -> _on_row_changed
        self._reload_list()
        self.list_widget.setCurrentRow(new_row)

    # --- result ---

    def _on_accept(self) -> None:
        self._commit_current()
        self.accept()

    def get_definitions(self) -> List[QuickFilterDef]:
        return list(self._definitions)

    @property
    def current_row(self) -> Optional[int]:
        """Whichever left-list row was selected when the dialog closed —
        read by the caller (regardless of Accept/Cancel) so the NEXT time
        this dialog opens in the same session, it can reopen on the same
        entry instead of always resetting to row 0. See __init__'s own
        `initial_row` parameter."""
        return self._current_index
