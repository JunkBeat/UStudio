"""ImportMatchDialog — the confirmation checklist shown by both folder-based
("mass") import entry points in object_actions.py (scoped-to-selection and
unscoped-whole-Environment). Never shown for single-file import — that's an
explicit, deliberate action against one already-selected object with no
ambiguity to confirm.

A table (Имя / Тип / Источник / Path ID / Режим), not a free-text checkbox
list — real reported gap: a plain concatenated string per row ("{name} —
{mode}") had no column of its own for the underlying Unity TYPE
(Texture2D/AudioClip/VideoClip/...), which matters more now that a single
bulk import can span several different converted-import types at once, each
configured by a different section of ConvertedImportSettingsDialog — a user
needs to see at a glance which rows are which type to understand which
settings will apply to them. Path ID/Источник were later split out of the
combined "Имя" column too (same reasoning, plus each is independently
sortable now — Path ID numerically via helpers.NumericTableWidgetItem). The
checkbox lives in column 0's own check state (QTableWidgetItem.setCheckState),
not a separate embedded QCheckBox widget — lighter weight, and it's what a
"select some rows" table normally looks like. Still pre-checked by default,
same as before: the whole point is "here's what I found, uncheck anything you
don't want" rather than opt-in from empty."""

from core.i18n import N_, tr, trn
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from core.object_preview import MatchedPatch, resolve_object_name
from helpers import NumericTableWidgetItem

_MODE_LABELS = {
    "json_dump": N_("JSON дамп"),
    "raw": N_("Raw дамп"),
    "content_raw": N_("Raw контент"),
    "converted": N_("Конвертированный"),
}

# Same warning color already used elsewhere in this app for a soft,
# non-blocking advisory (BC7 version gating, texture/platform format
# mismatch) — kept consistent rather than picking a new color for this one.
_MISMATCH_COLOR = QColor("#b8860b")


class ImportMatchDialog(QDialog):
    def __init__(self, matches: List[MatchedPatch], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Импорт патчей из папки"))
        self.resize(640, 480)
        self._rows: List[tuple] = []  # (QTableWidgetItem — the checkable name cell, MatchedPatch)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Найдено совпадений: {count}. Отметьте, что применить:", count=len(matches))))

        header_row = QHBoxLayout()
        btn_all = QPushButton(tr("Выбрать всё"))
        btn_none = QPushButton(tr("Снять всё"))
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        header_row.addWidget(btn_all)
        header_row.addWidget(btn_none)
        header_row.addStretch()
        layout.addLayout(header_row)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([tr("Имя"), tr("Тип"), tr("Источник"), "Path ID", tr("Режим")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        # Split out of a single combined "Имя #PathID (Источник)" column — real
        # reported gap: each of these is a genuinely independent, sortable axis
        # (e.g. "show me everything from this one source file"), which a single
        # concatenated string column can't offer. Populated with sorting
        # disabled, enabled only after (same reasoning CabBrowserDialog's own
        # table already documents: setSortingEnabled(True) re-sorts using
        # whatever the header's CURRENT indicator is, so doing it mid-populate
        # would re-sort on every row inserted).
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(matches))
        mismatch_count = 0
        for row, m in enumerate(matches):
            # name_mismatch (see match_patch_files()'s own docstring for why
            # this can legitimately happen — path_id isn't a stable
            # cross-build identifier): unchecked by default instead of the
            # usual pre-checked state, so a possibly-stale patch needs an
            # explicit opt-in rather than silently riding along with
            # everything else the user meant to import.
            if m.name_mismatch:
                mismatch_count += 1
                if m.mismatch_kind == "script":
                    was_now = (
                        tr("Патч был экспортирован для скрипта «{declared_name}», но сейчас по этому PathID/источнику "
                           "находится объект со скриптом «{current_name}».", declared_name=m.declared_name, current_name=m.current_name)
                    )
                elif m.mismatch_kind == "shifted":
                    was_now = (
                        tr("У объекта нет имени, по которому его можно проверить, а соседние объекты этого файла сменили "
                           "номера — скорее всего, на этом месте теперь другой объект.")
                    )
                else:
                    was_now = (
                        tr("Патч был экспортирован для «{declared_name}», но сейчас по этому PathID/источнику находится "
                           "«{current_name}».", declared_name=m.declared_name, current_name=m.current_name)
                    )
                tooltip = (
                    tr("⚠ {was_now} Возможно, патч устарел (например, после обновления игры) и путь: {file_path}", was_now=was_now, file_path=m.file_path)
                )
            elif m.name_unverified:
                reason = (tr("Скрипт объекта не удалось определить") if m.mismatch_kind == "script"
                          else tr("У объекта нет имени, по которому его можно проверить"))
                tooltip = tr("{file_path}\n{reason} — соответствие патча не проверено.", file_path=m.file_path, reason=reason)
            else:
                tooltip = str(m.file_path)

            name_item = QTableWidgetItem(resolve_object_name(m.obj))
            name_item.setFlags(name_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            name_item.setCheckState(Qt.CheckState.Unchecked if m.name_mismatch else Qt.CheckState.Checked)
            name_item.setToolTip(tooltip)
            self.table.setItem(row, 0, name_item)

            type_item = QTableWidgetItem(getattr(getattr(m.obj, "type", None), "name", "?"))
            type_item.setToolTip(tooltip)
            self.table.setItem(row, 1, type_item)

            source_item = QTableWidgetItem(m.source)
            source_item.setToolTip(tooltip)
            self.table.setItem(row, 2, source_item)

            pathid_item = NumericTableWidgetItem(str(m.path_id), m.path_id)
            pathid_item.setToolTip(tooltip)
            self.table.setItem(row, 3, pathid_item)

            mode_item = QTableWidgetItem(tr(_MODE_LABELS.get(m.mode, m.mode)))
            mode_item.setToolTip(tooltip)
            self.table.setItem(row, 4, mode_item)

            if m.name_mismatch:
                for item in (name_item, pathid_item, source_item, type_item, mode_item):
                    item.setForeground(QBrush(_MISMATCH_COLOR))

            self._rows.append((name_item, m))
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        layout.addWidget(self.table)

        if mismatch_count:
            # Real reported bug: an unbounded, unwrapped QLabel stretches the
            # whole dialog to its own text width instead of wrapping within
            # the available space — the same class of bug already fixed for
            # several other labels in this app (see CLAUDE.md's "audio-only
            # dialog was ~1474px wide" fixup). setWordWrap(True) is the fix
            # every one of those used.
            warning_label = QLabel(
                trn(mismatch_count,
                    "⚠ {n} объект помечен как, возможно, устаревший: не совпадает имя объекта или скрипта, или у "
                    "безымянного объекта сменили номера соседние объекты файла. Отметить такую строку — значит "
                    "импортировать её без учёта этого.",
                    "⚠ {n} объекта помечены как, возможно, устаревшие: не совпадает имя объекта или скрипта, или у "
                    "безымянного объекта сменили номера соседние объекты файла. Отметить такие строки — значит "
                    "импортировать их без учёта этого.",
                    "⚠ {n} объектов помечены как, возможно, устаревшие: не совпадает имя объекта или скрипта, или у "
                    "безымянного объекта сменили номера соседние объекты файла. Отметить такие строки — значит "
                    "импортировать их без учёта этого.")
            )
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Импортировать"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item, _m in self._rows:
            item.setCheckState(state)

    def selected_matches(self) -> List[MatchedPatch]:
        return [m for item, m in self._rows if item.checkState() == Qt.CheckState.Checked]
