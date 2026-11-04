"""The GUI's language: the saved choice (Настройки -> Язык), core.i18n set to it, and Qt's own texts.

install(app) runs in main() BEFORE the main window is built; a new choice takes effect after a restart
(every window is built with its texts once — retranslating them all live is not worth it).

Qt's own texts (standard buttons of message boxes, the text fields' right-click menu, file dialogs) come
from Qt's translation files qtbase_<code>.qm: first locales/qt/ next to the program (the GUI build copies
them there — Nuitka does not carry them), else the PyQt6 installation (development).
"""

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QLibraryInfo, QTranslator

from app_settings import app_settings
from core import i18n

SETTINGS_KEY = "language"
CHOICES = (i18n.SYSTEM, "en", "ru", "uk")       # the menu's order
QT_CATALOGS = ("qtbase", "qtmultimedia")         # Qt modules whose texts the user can see

_translators: List[QTranslator] = []            # kept alive: Qt holds only a pointer


def load_choice() -> str:
    choice = app_settings().value(SETTINGS_KEY, i18n.SYSTEM)
    return choice if choice in CHOICES else i18n.SYSTEM


def save_choice(choice: str) -> None:
    app_settings().setValue(SETTINGS_KEY, choice if choice in CHOICES else i18n.SYSTEM)


def qt_translation_dirs() -> List[Path]:
    out = []
    ours = i18n.find_locales_dir()
    if ours is not None:
        out.append(ours / "qt")
    out.append(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)))
    return out


def _install_qt_translations(app, code: str) -> None:
    for translator in _translators:
        app.removeTranslator(translator)
    _translators.clear()
    if code == "en":
        return                                    # Qt's texts are English already
    for catalog in QT_CATALOGS:
        for folder in qt_translation_dirs():
            translator = QTranslator(app)
            if translator.load(f"{catalog}_{code}", str(folder)):
                app.installTranslator(translator)
                _translators.append(translator)
                break


def install(app, choice: Optional[str] = None) -> str:
    """Sets the language of every text from the saved choice (or `choice`). Returns the language in use."""
    code = i18n.set_language(load_choice() if choice is None else choice)
    if app is not None:
        _install_qt_translations(app, code)
    return code


def choice_caption(choice: str) -> str:
    """The menu entry: a language in its own name, «Как в системе» in the current language."""
    if choice == i18n.SYSTEM:
        return i18n.tr("Как в системе")
    return i18n.LANGUAGE_NAMES[choice]
