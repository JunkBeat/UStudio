"""The console tool's start-up banner: a block-letter UStudio logo in colour.

Printed to stderr (stdout stays clean for piping) and only when stderr is a real terminal, so
scripts and `--format json` results never see it. NO_COLOR turns the colour off; USTUDIO_NO_BANNER=1
turns the banner off. Windows consoles need virtual-terminal mode switched on for colour."""

import os
import sys

from app_info import APP_VERSION

_LETTERS = {
    "U": ["██╗   ██╗", "██║   ██║", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "D": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
    "I": ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
}
_WORD = "USTUDIO"
_GRADIENT = (27, 33, 39, 45, 51, 87)  # 256-colour blues, top to bottom


def _logo_rows() -> list:
    return ["".join(_LETTERS[c][row] for c in _WORD) for row in range(6)]


def _enable_windows_vt() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:  # noqa: BLE001 - colour is a nicety; never fail the tool over it
        pass


def render_banner(color: bool = True, unicode_ok: bool = True) -> str:
    """The banner text (no trailing hint). ASCII fallback when the terminal can't show block letters."""
    if unicode_ok:
        rows = _logo_rows()
        if color:
            rows = [f"\x1b[38;5;{_GRADIENT[i]}m{r}\x1b[0m" for i, r in enumerate(rows)]
        tag = f"   C  L  I    v{APP_VERSION}"
        tag = f"\x1b[2m{tag}\x1b[0m" if color else tag
        return "\n".join([""] + ["  " + r for r in rows] + ["", tag, ""])
    name = f"\x1b[1mUStudio CLI\x1b[0m" if color else "UStudio CLI"
    return f"\n  {name}  v{APP_VERSION}\n"


def print_banner(file=None, hint: bool = True, force: bool = False) -> bool:
    """Prints the banner if `file` (default stderr) is a terminal. Returns whether it printed."""
    file = file or sys.stderr
    if os.environ.get("USTUDIO_NO_BANNER") == "1":
        return False
    if not force and not (hasattr(file, "isatty") and file.isatty()):
        return False
    color = "NO_COLOR" not in os.environ
    if color:
        _enable_windows_vt()
    try:
        "".join(_logo_rows()).encode(getattr(file, "encoding", None) or "ascii")
        unicode_ok = True
    except (UnicodeEncodeError, LookupError):
        unicode_ok = False
    text = render_banner(color=color, unicode_ok=unicode_ok)
    if hint:
        line = "Type ustudio_cli help to see all commands."
        text += "\n  " + (line.replace("ustudio_cli help", "\x1b[36mustudio_cli help\x1b[0m") if color else line) + "\n"
    print(text, file=file)
    return True
