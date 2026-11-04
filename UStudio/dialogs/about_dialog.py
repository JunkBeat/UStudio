"""Справка → "О программе..." — a small, read-only informational dialog:
logo, name/version, author, a short plain-language description, and a linked
list of the real third-party libraries this app is built on. Modeled on
the minimalist, Close-only style (no setResize() fight
with the layout's real minimum — see that dialog's own comment on why a
fixed height was dropped in favor of setMinimumWidth alone)."""

from core.i18n import N_, tr
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout

import app_icon
from app_info import LICENSE_NAME, LICENSE_URL, SOURCE_URL
from config import APP_NAME, APP_VERSION

_AUTHOR = "Ambigram"

_DESCRIPTION = (
    N_("Браузер и редактор ассетов Unity: просмотр, экспорт и импорт объектов "
    "игровых файлов, а также инструменты для работы с бандлами и архивами.")
)

# The key libraries UStudio's own code directly builds on, plus two more the
# user explicitly asked to include with their own confirmed URLs
# (BCnEncoder.NET, Compressonator's etcpack, FSB5.Converter, msdfgen, ffmpeg, TypeTreeGeneratorAPI) — everything else UnityPy pulls in
# internally for narrow features (texture2ddecoder/etcpak/astc-encoder-py/
# tpk_ar/pythonnet/fmod_toolkit/pyfmodex, ...) stays out (FMOD itself is listed: its licence asks for a credit), per the
# earlier trim to "key libraries only": crediting UnityPy itself already
# covers those. (name, url, one-line purpose).
_RESOURCES = [
    ("UnityPy", "https://github.com/K0lb3/UnityPy", N_("чтение и запись файлов Unity")),
    ("PyQt6", "https://www.riverbankcomputing.com/software/pyqt/", N_("графический интерфейс")),
    ("NumPy", "https://numpy.org", N_("быстрая обработка бинарных данных")),
    ("Pillow", "https://python-pillow.github.io", N_("работа с изображениями")),
    ("BCnEncoder.NET", "https://github.com/Nominom/BCnEncoder.NET", N_("кодирование текстур в формат BC1-BC7")),
    ("Compressonator", "https://github.com/GPUOpen-Tools/compressonator", N_("кодирование текстур в формат ETC1/ETC2")),
    ("FSB5.Converter", "https://github.com/JunkBeat/FSB5.Converter", N_("кодирование звука в формат FSB5")),
    # FMOD's licence asks for this credit (the audio decoder and the FSB5 encoder both run on it).
    ("FMOD (Firelight Technologies)", "https://www.fmod.com", N_("воспроизведение и кодирование звука")),
    ("msdfgen", "https://github.com/Chlumsky/msdfgen", N_("генерация SDF шрифтов")),
    ("ffmpeg", "https://ffmpeg.org", N_("работа с видео")),
    ("TypeTreeGeneratorAPI", "https://github.com/UnityPy-Org/TypeTreeGeneratorAPI", N_("чтение структуры скриптов Unity")),
    ("Il2CppDumper", "https://github.com/Perfare/Il2CppDumper", N_("подготовка скриптов для IL2CPP игр")),
]


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("О программе {app_name}", app_name=APP_NAME))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()
        logo_label = QLabel()
        logo_label.setPixmap(app_icon.render_logo_pixmap(72, "color"))
        header_row.addWidget(logo_label)

        title_col = QVBoxLayout()
        name_label = QLabel(f"<b style='font-size:16pt;'>{APP_NAME}</b>")   # i18n: keep (markup)
        version_label = QLabel(tr("Версия {app_version}", app_version=APP_VERSION))
        author_label = QLabel(tr("Автор: {author}", author=_AUTHOR))
        title_col.addWidget(name_label)
        title_col.addWidget(version_label)
        title_col.addWidget(author_label)
        license_label = QLabel(tr("Лицензия: {license}", license=f'<a href="{LICENSE_URL}">{LICENSE_NAME}</a>'))
        license_label.setOpenExternalLinks(True)
        title_col.addWidget(license_label)
        if SOURCE_URL:
            source_label = QLabel(f'<a href="{SOURCE_URL}">{tr("Исходный код")}</a>')   # i18n: keep (markup)
            source_label.setOpenExternalLinks(True)
            title_col.addWidget(source_label)
        title_col.addStretch(1)
        header_row.addLayout(title_col)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        desc_label = QLabel(tr(_DESCRIPTION))
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(desc_label)

        layout.addWidget(QLabel(tr("<b>Использованные ресурсы:</b>")))

        # Just 4 short lines now that the list is trimmed to key libraries
        # only (see _RESOURCES' own comment) — no QScrollArea needed, unlike
        # the earlier, longer version of this list.
        resources_label = QLabel(_build_resources_html())
        resources_label.setWordWrap(True)
        resources_label.setOpenExternalLinks(True)
        resources_label.setTextFormat(Qt.TextFormat.RichText)
        resources_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(resources_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)


def _build_resources_html() -> str:
    rows = []
    for name, url, purpose in _RESOURCES:
        label = f'<a href="{url}">{name}</a>' if url else name
        rows.append(f"{label} — {tr(purpose)}")
    return "<br>".join(rows)
