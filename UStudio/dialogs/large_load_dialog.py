from core.i18n import tr
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox

from helpers import format_size, format_type_names


class LargeLoadDialog(QDialog):
    """Warns that the selected files hold a very large amount of data. Only two answers:
    continue or cancel — which object types get loaded follows the indexing settings.

    `restricted_types`: the types the narrowed indexing settings will load (core.loader.restricted_indexed_types),
    named in the text so a forgotten "only Texture2D" setting is noticed BEFORE a long load, not after it."""

    def __init__(self, object_count: int, load_all: bool, legacy_size_bytes: int = 0,
                 single_big_bundle: bool = False, parent=None, restricted_types=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Большой объём данных"))
        self.setMinimumWidth(440)

        count = f"{object_count:,}".replace(",", " ")
        if object_count > 0:
            head = tr("В выбранных файлах {count} объектов.", count=count) + " "
        else:
            head = tr("Выбранные файлы занимают {size}.", size=format_size(legacy_size_bytes)) + " "

        if load_all:
            body = (tr("Будут загружены все объекты, поэтому процесс может занять много времени и памяти. Если нужны не "
               "все объекты, отключите загрузку всех ассетов в настройках."))
        elif object_count == 0:
            body = tr("Загрузка может занять много времени и памяти.")
        elif restricted_types:
            body = (tr("В соответствии с настройками индексации будут загружены следующие типы: {format_type_names}. "
               "Обработка такого объёма данных всё равно потребует много времени и памяти.", format_type_names=format_type_names(restricted_types)))
        else:
            body = (tr("В соответствии с настройками индексации будет загружена лишь часть типов, но обработка такого "
               "объёма данных всё равно потребует много времени и памяти."))
        text = head + body
        if single_big_bundle:
            text += "\n\n" + tr("Если нужен только один файл из юнити архива, откройте его в Просмотре архива — так вам "
                                 "не придётся загружать его целиком.")

        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)

        buttons = QDialogButtonBox()
        ok = buttons.addButton(tr("Продолжить"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("Отмена"), QDialogButtonBox.ButtonRole.RejectRole)
        ok.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
