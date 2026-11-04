from core.i18n import tr
import os
from typing import List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QRadioButton, QButtonGroup, QListWidget, QDialogButtonBox, QFileDialog,
    QMessageBox, QToolButton,
)


class InputSettingDialog(QDialog):
    def __init__(self, parent, title, label_text, hint_text=None, current_value=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(350, 120)
        self.init_ui(label_text, hint_text, current_value)

    def init_ui(self, label_text, hint_text, current_value):
        layout = QVBoxLayout(self)

        if hint_text:
            hint_lbl = QLabel(hint_text)
            hint_lbl.setStyleSheet("color: gray; font-size: 11px;")
            layout.addWidget(hint_lbl)

        layout.addWidget(QLabel(label_text))

        self.line_edit = QLineEdit(current_value)
        layout.addWidget(self.line_edit)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_value(self):
        return self.line_edit.text().strip()


class CabCollisionSettingsDialog(QDialog):
    """Two same-named files (two "level0"s of different games) are BOTH loaded; resources,
    cross-file references and "go to object" already pick the copy nearest the object. What
    is left for this setting is only the lookup by NAME ALONE (and ties): which file takes
    the single name slot — the first found (default) — or whether to stop the load at the
    first collision ("raise", for strict/scripted use). Also manages the list of folders
    excluded from folder-mode loads."""
    def __init__(self, parent, current_policy: str, current_excluded: List[str]):
        super().__init__(parent)
        self.setWindowTitle(tr("Совпадения имён файлов"))
        self.setModal(True)
        self.resize(460, 360)

        layout = QVBoxLayout(self)

        # Real reported feedback: the full explanation was a wall of text always
        # visible at the top of the dialog. Kept out of sight by default — a
        # short one-line summary stays visible, the rest (what this actually
        # does, and the "doesn't exclude files" caveat) sits behind the "?"
        # button, same discoverable-on-demand idea as a title-bar help button.
        info_row = QHBoxLayout()
        info_row.addWidget(QLabel(tr("Как поступать, если разные файлы имеют одинаковое имя?")))
        btn_help = QToolButton()
        btn_help.setText("?")
        btn_help.setObjectName("RoundToolButton")
        btn_help.setFixedSize(22, 22)
        btn_help.setToolTip(tr("Подробнее"))
        btn_help.clicked.connect(self._show_help)
        info_row.addWidget(btn_help)
        info_row.addStretch()
        layout.addLayout(info_row)

        self.group = QButtonGroup(self)
        self.rb_first = QRadioButton(tr("Загружать всё; при поименном поиске файла брать самый первый"))
        self.rb_raise = QRadioButton(tr("Прерывать загрузку при первом совпадении имён"))
        for i, rb in enumerate([self.rb_first, self.rb_raise]):
            self.group.addButton(rb, i)
            layout.addWidget(rb)
        # Older saved values ("keep_last", "ask") no longer exist and count as the default.
        (self.rb_raise if current_policy == "raise" else self.rb_first).setChecked(True)

        layout.addSpacing(12)
        layout.addWidget(QLabel(tr("Папки, исключённые из загрузки по папке:")))
        self.folder_list = QListWidget()
        self.folder_list.addItems(current_excluded)
        layout.addWidget(self.folder_list)

        folder_buttons = QHBoxLayout()
        btn_add = QPushButton(tr("Добавить папку..."))
        btn_add.clicked.connect(self._add_folder)
        btn_remove = QPushButton(tr("Убрать выбранную"))
        btn_remove.clicked.connect(self._remove_selected)
        btn_clear = QPushButton(tr("Очистить список"))
        btn_clear.clicked.connect(self.folder_list.clear)
        folder_buttons.addWidget(btn_add)
        folder_buttons.addWidget(btn_remove)
        folder_buttons.addWidget(btn_clear)
        folder_buttons.addStretch()
        layout.addLayout(folder_buttons)

        layout.addSpacing(12)
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _show_help(self):
        QMessageBox.information(
            self,
            tr("Совпадения имён файлов"),
            tr("Если в разных подпапках найдены файлы с одинаковым именем (например, «level0» в разных играх), "
               "программа загрузит их все. Внутренние ссылки автоматически распознают файлы по полному "
               "пути.\n\nНастройка ниже нужна, когда поиск файла идет только по имени (без указания папки):\n• По "
               "умолчанию программа использует первый найденный файл.\n• «Остановить загрузку»: прерывает "
               "сканирование при первом же совпадении имён.\n\nЧтобы полностью пропустить ненужные папки, "
               "добавьте их в список исключений ниже.")
        )

    def _add_folder(self):
        # A general-purpose blacklist, not tied to any specific name collision — the
        # user can pre-emptively exclude a folder from folder-mode loads without ever
        # having ever seen a name collision.
        folder = QFileDialog.getExistingDirectory(self, tr("Выберите папку для исключения"))
        if not folder:
            return
        existing_norm = {
            os.path.normcase(os.path.abspath(self.folder_list.item(i).text()))
            for i in range(self.folder_list.count())
        }
        if os.path.normcase(os.path.abspath(folder)) not in existing_norm:
            self.folder_list.addItem(folder)

    def _remove_selected(self):
        for item in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(item))

    def get_policy(self) -> str:
        return {0: "keep_first", 1: "raise"}[self.group.checkedId()]

    def get_excluded_folders(self) -> List[str]:
        return [self.folder_list.item(i).text() for i in range(self.folder_list.count())]
