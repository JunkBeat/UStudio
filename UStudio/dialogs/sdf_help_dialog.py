"""Справка → «Генерация SDF-шрифтов...» — a short read-only guide. End-user wording on
purpose: what the feature is for and the two ways to use it; the command line has its own
text file and is not described here. The format reference and examples are NOT written here: they are
docs/ru/sdf_map.md (one file for the GUI and the command-line tool), rendered below the GUI-only steps.
Every fenced block in that file is a real sdf_map.txt that must parse (tests/test_sdf_help_examples.py)."""

from core.i18n import N_, current_language, tr
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QPalette
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from help_docs import read_doc, render_markdown
from helpers import mono_font

_EXTRA_POINTS = 1.5   # added to the UI font size for the help text
_MAX_HEIGHT = 900     # px; also capped at 85% of the screen's available height

_TABLE = 'border="1" cellspacing="0" cellpadding="5" width="100%"'

def _help_intro_html() -> str:
    return tr("\n<h2>Генерация SDF-шрифтов</h2>\n<p>Если в SDF шрифтах нет нужных букв, их можно\n<b>добавить</b> "
   "или <b>заменить шрифт целиком</b> путем генерации SDF с помощью файлов <i>.ttf</i> / "
   "<i>.otf</i>.</p>\n\n<table {table}>\n<tr><th align=\"left\">Способ генерации</th><th "
   "align=\"left\">Когда подходит</th></tr>\n<tr><td><b>1. Вручную</b></td><td>Протестировать "
   "генерацию; подобрать оптимальные настройки; замена на скорую руку.</td></tr>\n<tr><td><b>2. "
   "Через mapping файл</b></td><td>Для массовой автоматической замены; когда много шрифтов и каждый "
   "требует отдельных настроек.</td></tr>\n</table>\n\n<h3>1. Генерация вручную</h3>\n<ol>\n<li>Выберите "
   "в таблице MonoBehaviour объект, имеющий в столбце «Скрипт» значение «TMP_FontAsset». Можно "
   "выделить сразу <b>несколько</b> объектов с помощью Ctrl или Shift + ЛКМ.</li>\n<li>Щёлкните "
   "правой кнопкой мыши и выберите пункт <b>«Генерировать SDF...»</b>.</li>\n<li>Укажите необходимые "
   "настройки, нажмите <b>«Генерировать»</b>, "
   "затем\n<b>«Сохранить»</b>.</li>\n</ol>\n<p><i>Примечание: для массовой генерации предпросмотр "
   "недоступен: при нажатии кнопки «ОК» сразу запускается генерация и применяются "
   "изменения.</i></p>\n\n<h3>2. Генерация через mapping файл</h3>\n<ol>\n<li>Подготовьте файл "
   "<code>sdf_map.txt</code>, содержащий настройки (см. ниже).</li>\n<li>Положите в одну папку "
   "векторные шрифты, <code>sdf_map.txt</code>, и, по желанию, "
   "<code>chars.txt</code>.</li>\n<li>Нажмите правой кнопкой мыши на любом объекте в таблице, "
   "выберите пункт <b>«Импорт в окружение...»</b> и укажите папку из предыдущего "
   "пункта.</li>\n<li>Генерация запустится автоматически либо сперва будет предложено указать "
   "дефолтные настройки генерации.</li>\n</ol>\n<p><i>Примечание: при нажатии на пункт <b>«Импорт в "
   "окружение...»</b> из указанной папки сперва применяются обычные патч файлы (если они есть), а "
   "затем генерируются SDF по карте (если она есть).</i></p>\n", table=_TABLE)

_MAP_DOC = "sdf_map.md"
_MAP_DOC_MISSING_HTML = (
    N_("<p><i>Описание формата файла sdf_map.txt не найдено: файл {path} "
    "должен лежать рядом с программой.</i></p>")
)


def build_help_html() -> str:
    """The GUI-only part (what the feature is for, how to run it from the window) followed by the format
    reference and examples, which are the same document the command-line tool ships: docs/ru/sdf_map.md."""
    text = read_doc(_MAP_DOC)
    if text is not None:
        return _help_intro_html() + render_markdown(text)
    return _help_intro_html() + tr(_MAP_DOC_MISSING_HTML, path=f"docs/{current_language()}/{_MAP_DOC}")


class SDFHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Генерация SDF-шрифтов"))
        layout = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        # Slightly larger text than the UI default: this is a reading window, not a settings form.
        base = self.view.font()
        base.setPointSizeF(base.pointSizeF() + _EXTRA_POINTS)
        self.view.setFont(base)
        # Code blocks use the app's own monospace font (the one the Preview/Dump tabs show, so it
        # also follows the user's font setting) on a tinted background. The default <pre> came out
        # tiny and hard to read. Must be set before setHtml().
        mono = mono_font()
        tint = self.view.palette().color(QPalette.ColorRole.AlternateBase).name()
        self.view.document().setDefaultStyleSheet(
            f"pre {{ font-family: '{mono.family()}'; font-size: {mono.pointSizeF():g}pt; "
            f"background-color: {tint}; }} "
            f"code {{ font-family: '{mono.family()}'; font-size: {mono.pointSizeF():g}pt; }}"
        )
        self.view.setHtml(build_help_html())
        layout.addWidget(self.view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # A fixed height would stretch across a small screen: cap it at most of the available height.
        screen = self.screen() or QGuiApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 800
        self.resize(700, min(_MAX_HEIGHT, int(available_height * 0.85)))
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
