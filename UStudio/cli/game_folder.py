"""Where a CLI command loads from when the caller passed neither -p nor -F.

Auto-detects a `*_Data` folder directly inside the current directory — but only
for commands that can't overwrite the originals (see destructive_reason()): a
wrong guess there costs a wasted run, while a wrong guess before `--in-place`
overwrites files with no backup (save_manager writes a temp file and
os.replace()s it over the original).

Deliberately strict:
- "_Data" is matched CASE-SENSITIVELY (`Game_Data`, never `game_data`), and
  only among the current directory's direct children — no recursion, so a
  `BACKUP/Game_Data` mirror further down is never a candidate.
- A candidate must also LOOK like Unity data (is_unity_data_folder()). Names
  and a few leading bytes only — nothing is parsed — so a directory that merely
  ends in "_Data" is ignored, not loaded.
- Zero or several candidates is an error that lists what was found; nothing is
  ever picked on the caller's behalf.

PyQt-free, like the rest of cli/."""

import os
from pathlib import Path
from typing import List, Optional, Tuple

DATA_FOLDER_SUFFIX = "_Data"

# Names whose presence alone identifies a Unity player data folder (the
# standalone Windows/Linux layout). Compared lower-cased, so the check doesn't
# depend on how a given file system reports case.
_MARKER_NAMES = frozenset({
    "globalgamemanagers", "globalgamemanagers.assets", "maindata", "data.unity3d",
    "level0", "resources.assets", "sharedassets0.assets", "unity default resources",
})

# Fallback for a data folder with none of the standard names (custom-named
# bundles): a top-level file that starts with an AssetBundle signature.
_BUNDLE_SIGNATURES = (b"UnityFS", b"UnityWeb", b"UnityRaw", b"UnityArchive")
_SNIFF_FILE_LIMIT = 25


class DefaultFolderError(Exception):
    """Auto-detection couldn't (or, for a destructive command, mustn't) pick a
    folder — message is user-facing, printed via output.error() by main()."""


def is_unity_data_folder(folder: Path) -> bool:
    try:
        entries = [e for e in os.scandir(folder) if e.is_file()]
    except OSError:
        return False
    if any(e.name.lower() in _MARKER_NAMES for e in entries):
        return True
    for e in entries[:_SNIFF_FILE_LIMIT]:
        try:
            with open(e.path, "rb") as f:
                if f.read(12).startswith(_BUNDLE_SIGNATURES):
                    return True
        except OSError:
            continue
    return False


def find_data_folders(cwd: Path) -> Tuple[List[Path], List[Path]]:
    """(valid, rejected) among `cwd`'s direct children ending in "_Data".
    `rejected` are the ones that have the name but don't look like Unity data."""
    valid: List[Path] = []
    rejected: List[Path] = []
    for child in sorted(cwd.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or not child.name.endswith(DATA_FOLDER_SUFFIX):
            continue
        (valid if is_unity_data_folder(child) else rejected).append(child)
    return valid, rejected


def resolve_default_folder(cwd: Optional[Path] = None) -> Path:
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    valid, rejected = find_data_folders(cwd)

    if len(valid) == 1:
        return valid[0]

    how = "pass -p FOLDER (or -F FILE) to say what to load"
    if len(valid) > 1:
        listing = "\n".join(f"  {p}" for p in valid)
        raise DefaultFolderError(f"found several *{DATA_FOLDER_SUFFIX} folders in {cwd}:\n{listing}\n{how}")

    msg = (f"no *{DATA_FOLDER_SUFFIX} folder found in {cwd} (only folders directly inside the current "
           f"directory whose name ends in '{DATA_FOLDER_SUFFIX}', case-sensitive, that contain Unity data)")
    if rejected:
        msg += "; ignored, not Unity data: " + ", ".join(p.name for p in rejected)
    raise DefaultFolderError(f"{msg}\n{how}")


def destructive_reason(args) -> Optional[str]:
    """Why this invocation can overwrite the originals (so it must NOT get a
    guessed folder), or None when it can't. Judged from the parsed args:
    `--in-place` on import, `save` without `--save-as` (its default is
    to overwrite), and `shell` — an interactive session where `save` or
    `import --in-place` can still overwrite whatever was loaded, at any later
    point the guess can no longer be questioned."""
    command = getattr(args, "command", None)
    if command == "shell":
        return "shell (its `save` / `import --in-place` can overwrite the originals)"
    if getattr(args, "in_place", False):
        return "--in-place"
    if command == "save" and not getattr(args, "save_as", None):
        return "save without --save-as (it overwrites the originals)"
    return None


def apply_default_load_source(args, cwd: Optional[Path] = None) -> Optional[Path]:
    """Fills args.folder from the current directory when the caller gave
    neither -p nor -F, and returns the folder used (None if nothing was
    needed — a flag was given, or the command takes no load flags at all, like
    `cab`). Raises DefaultFolderError for a destructive command or when
    auto-detection finds zero/several candidates."""
    if not hasattr(args, "folder") or args.folder or args.files:
        return None
    reason = destructive_reason(args)
    if reason:
        raise DefaultFolderError(
            f"{reason} needs an explicit -p FOLDER or -F FILE: the game folder is never auto-detected "
            f"for a command that can overwrite it"
        )
    folder = resolve_default_folder(cwd)
    args.folder = str(folder)
    return folder
