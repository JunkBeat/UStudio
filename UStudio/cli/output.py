"""Output formatting for the CLI. Stdout/stderr discipline (deliberate, not
incidental): machine-readable results (list/inspect/export output) go to
stdout so `ustudio list --format json | jq ...` works cleanly; progress,
prompts, and human-facing status lines go to stderr (see session.py's
callbacks) so they never pollute a piped result.

core/file_utils.py's own format_size() uses Cyrillic units (Б/КБ/МБ/...) to
match the GUI's Russian-language table — the CLI stays English by design (per
explicit request), so this file has its own tiny formatter rather than
reusing that one and fighting its unit labels."""

import contextlib
import json
import os
import sys
from typing import Any, Dict, List

from core.models import RowItem


@contextlib.contextmanager
def redirect_native_stdout_to_stderr():
    """Some native components this app depends on write straight to the
    process's OS-level stdout file descriptor, completely bypassing
    sys.stdout (and so any redirection done at the Python level) — confirmed
    by an actual test run, not theoretical: `list --type MonoBehaviour
    --format json` against a real IL2CPP fixture came back with "Error
    generating tree nodes:\\nSequence contains no matching element" (the
    documented IL2CPP TypeTree-generation limitation — see this project's own
    "il2cpp TypeTree generation failures" notes) sitting BEFORE the actual
    JSON on stdout, breaking every consumer of --format json for any fixture
    that hits it. That text isn't from any Python print() call in this
    codebase (grepped for it — none), so it's TypeTreeGeneratorAPI's .NET
    side writing directly to the real OS stdout handle.

    Redirects for the duration of the `with` block, then restores — used
    around cmd_load() specifically (see its call sites), since that's the
    only phase where native TypeTree generation runs; cmd_load() itself
    never legitimately writes to stdout (its own "Loaded. N objects..."
    line already goes to stderr), so nothing real is lost by redirecting
    the whole phase rather than trying to scope it more tightly.

    Redirects BOTH the POSIX-style CRT file descriptor (os.dup2, what a
    C-runtime-level fprintf(stdout, ...) would use) AND the Win32-level
    STD_OUTPUT_HANDLE (via SetStdHandle, what WriteConsole/WriteFile-based
    native output — and .NET's Console.WriteLine — actually reads on
    Windows). Needed both: a first attempt using only os.dup2 was verified
    NOT to catch this text (confirmed by an actual round-trip test, not
    assumed) — Windows keeps the CRT fd table and the Win32 standard-handle
    table only loosely in sync, so redirecting one doesn't guarantee the
    other follows. Windows-only (ctypes.windll) — this project only ships
    on Windows, matching every other Windows-specific mechanism already in
    this codebase (see e.g. main.py's SetCurrentProcessExplicitAppUserModelID)."""
    if sys.platform != "win32":
        yield
        return

    import ctypes

    STD_OUTPUT_HANDLE = -11
    STD_ERROR_HANDLE = -12
    kernel32 = ctypes.windll.kernel32

    sys.stdout.flush()
    saved_fd = os.dup(1)
    saved_handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    try:
        os.dup2(2, 1)
        kernel32.SetStdHandle(STD_OUTPUT_HANDLE, kernel32.GetStdHandle(STD_ERROR_HANDLE))
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved_fd, 1)
        os.close(saved_fd)
        kernel32.SetStdHandle(STD_OUTPUT_HANDLE, saved_handle)
from core.object_preview import get_row_name, get_row_script_name


_unicode_ok_cache: Dict[int, bool] = {}


def supports_unicode(file=sys.stdout) -> bool:
    """Whether `file`'s own reported encoding can actually represent the box-
    drawing/block characters this module can render. Checked directly against
    the stream's real encoding rather than assumed — confirmed necessary by
    testing, not theoretical: a real Windows console reporting cp1251 (a
    Cyrillic codepage, plausible as this app's own actual target environment,
    not just an edge case) cannot encode ANY of ─│├└█░ at all. Without this
    check every one of those would render as literal "?" — configure_console_
    logging()'s errors="replace" prevents a crash, but a "?"-filled table
    border or progress bar is not what "looks good visually" means, so this
    picks a plain-ASCII rendering there instead rather than degrade silently.
    Cached per stream object — the encoding doesn't change mid-process."""
    key = id(file)
    if key not in _unicode_ok_cache:
        encoding = getattr(file, "encoding", None)
        try:
            "─│├└█░".encode(encoding or "ascii")
            _unicode_ok_cache[key] = True
        except (UnicodeEncodeError, LookupError, TypeError):
            _unicode_ok_cache[key] = False
    return _unicode_ok_cache[key]


def tree_connectors(file=sys.stdout) -> "tuple[str, str, str, str]":
    """(branch, last_branch, pipe, blank) prefixes for a tree printout —
    Unicode box-drawing when the stream can render it, plain ASCII otherwise
    (see supports_unicode's own docstring for why this fallback is real, not
    speculative)."""
    if supports_unicode(file):
        return "├── ", "└── ", "│   ", "    "
    return "|-- ", "`-- ", "|   ", "    "


def render_bar(current: int, total: int, width: int = 24, file=sys.stderr) -> str:
    """Progress bar, shared by every progress printer in the CLI (session.py's
    load/scan callbacks, commands.py's save/cab export/rebuild) so they all
    look the same instead of each inventing its own. Block characters (█/░)
    when the target stream supports them, plain ASCII (#/-) otherwise."""
    if total <= 0:
        filled = width
    else:
        filled = int(width * min(max(current, 0), total) / total)
    if supports_unicode(file):
        return "█" * filled + "░" * (width - filled)
    return "#" * filled + "-" * (width - filled)


def format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    val = float(size_bytes)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024
        i += 1
    return f"{int(val)} {units[i]}" if i == 0 else f"{val:.1f} {units[i]}"


def row_to_dict(row: RowItem) -> Dict[str, Any]:
    """The one canonical dict shape every output format (table/json/csv)
    renders from — resolves the lazy name/script_name fields (see
    get_row_name/get_row_script_name's own docstrings: RowItem stores an
    unresolved sentinel until something actually asks) exactly once here,
    so a caller never accidentally prints the sentinel object itself."""
    return {
        "path_id": row["path_id"],
        "name": get_row_name(row),
        "type": row["type"],
        "script_name": get_row_script_name(row) if row["type"] == "MonoBehaviour" else "",
        "source": row["source"],
        "size": row["size"],
        "modified": row["obj_ref"].data is not None,
    }


def print_json(data: Any, file=sys.stdout) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False), file=file)


def print_table(rows: List[Dict[str, Any]], columns: List[str], file=sys.stdout) -> None:
    if not rows:
        print("(no results)", file=file)
        return

    def cell(row: Dict[str, Any], col: str) -> str:
        val = row.get(col, "")
        if col == "size" and isinstance(val, int):
            return format_size(val)
        if col == "modified":
            return "*" if val else ""
        return str(val)

    widths = {c: max(len(c), *(len(cell(r, c)) for r in rows)) for c in columns}
    header = "  ".join(c.upper().ljust(widths[c]) for c in columns)
    print(header, file=file)
    sep_char = "─" if supports_unicode(file) else "-"
    print(sep_char * len(header), file=file)
    for r in rows:
        print("  ".join(cell(r, c).ljust(widths[c]) for c in columns), file=file)
    print(f"\n{len(rows)} object(s)", file=file)


def print_csv(rows: List[Dict[str, Any]], columns: List[str], file=sys.stdout) -> None:
    import csv as _csv
    # lineterminator="\n", not csv's own default "\r\n": found via a real
    # test that piping to stdout produced doubled "\r\r\n" line endings —
    # csv.writer's own "\r\n" terminator gets a SECOND newline translation
    # pass from the destination text stream itself (sys.stdout is opened
    # without newline="", unlike emit_rows()'s --out file path, which
    # already passes newline="" precisely to avoid this). Forcing "\n" here
    # means there's only ever one newline-translation pass, however the
    # destination stream itself is configured, instead of depending on every
    # possible destination already being newline=""-safe.
    writer = _csv.writer(file, lineterminator="\n")
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r.get(c, "") for c in columns])


DEFAULT_COLUMNS = ["path_id", "name", "type", "source", "size", "modified"]


def emit_rows(rows: List[RowItem], fmt: str, out=None) -> None:
    """out=None writes to stdout; a Path writes to that file instead (still
    the same content — `--out FILE` on `list` is a convenience, not a
    different code path from what would otherwise print to stdout)."""
    dicts = [row_to_dict(r) for r in rows]
    file = open(out, "w", encoding="utf-8", newline="") if out else sys.stdout
    try:
        if fmt == "json":
            print_json(dicts, file=file)
        elif fmt == "csv":
            print_csv(dicts, DEFAULT_COLUMNS, file=file)
        else:
            print_table(dicts, DEFAULT_COLUMNS, file=file)
    finally:
        if out:
            file.close()


def error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
