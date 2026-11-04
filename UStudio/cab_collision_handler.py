"""Reports the same-named-file collisions of a load (Environment.name_collisions).

Nothing is decided here any more: every same-named file is loaded and visible, resources /
cross-file references / "go to object" pick the copy nearest the object, and the setting
(Settings -> «Совпадения имён файлов...») only says whether the first file takes the name slot
or the load stops at the first collision. So this is a log-only report — the interactive
"ask" dialog was removed together with the "keep_last" policy."""

from core.i18n import tr
from config import CONFIG, LogLevel
from core.collision_report import meaningful_collisions
from helpers import shorten_path


def handle_cab_collisions(env, parent_widget, log) -> None:
    """`log(message, level)` is typically MainWindow.log; `parent_widget` is kept for the
    caller's signature."""
    collisions = getattr(env, "name_collisions", None)
    if not collisions:
        return

    # Only a collision where BOTH sides hold objects means "probably more than one game";
    # two folders sharing an identical DLL/config file are not worth a warning.
    if meaningful_collisions(collisions):
        log(
            tr("Загружены файлы с одинаковыми именами ({count}). Если что-то работает не так, исключите лишние "
               "папки в настройках.", count=len(collisions)),
            LogLevel.WARNING,
        )

    base = CONFIG.selected_dir or CONFIG.game_data_dir
    lines = [f"  • {shorten_path(c.rejected_name, base)}" for c in collisions]

    log("\n".join(lines), LogLevel.DEBUG)
