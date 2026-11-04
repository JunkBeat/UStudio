"""Backups of the original files, made on request right before they are overwritten.

A backup is a plain folder of copies — one folder per save, named by date and time — with
a small manifest.json that says where every copy came from, so it can be restored by hand
or by a later restore command. The default location is outside any game folder on purpose:
a copy left next to the game would be picked up by the next folder load as a duplicate.

Backups of big games are big, so they are pruned after every new one (prune_backups): for each
original file the very first copy (the untouched original - the one that matters most when
something goes wrong) is kept forever, plus the newest `keep_latest` copies; anything in between
is deleted.

PyQt-free, only stdlib, so the GUI and the CLI share it."""

from core.i18n import tr
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

MANIFEST_NAME = "manifest.json"
_SPACE_MARGIN = 64 * 1024 * 1024  # keep a little room free after the copies


class BackupError(Exception):
    """str(e) is a complete, user-facing message."""


class BackupFolderMissing(BackupError):
    """A file could not be restored because the folder it came from no longer exists (the game was moved
    or deleted). `folders` are the missing folders; callers that can offer a way out (the CLI's
    --relocate) catch this subclass to add it to the message."""

    def __init__(self, message: str, folders: List[str]):
        super().__init__(message)
        self.folders = folders


def default_backup_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "UStudio" / "backups"


def _unique_folder(root: Path) -> Path:
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    folder = root / stamp
    n = 1
    while folder.exists():
        n += 1
        folder = root / f"{stamp}_{n}"
    return folder


def _relative_names(paths: List[Path]) -> List[str]:
    """Each file's path inside the backup: relative to the folder all of them share, so a
    game's own layout is kept (and two same-named files never collide)."""
    resolved = [os.path.abspath(p) for p in paths]
    if len(resolved) == 1:
        return [os.path.basename(resolved[0])]
    try:
        common = os.path.commonpath(resolved)
    except ValueError:  # files on different drives
        common = ""
    names = []
    for p in resolved:
        if common:
            names.append(os.path.relpath(p, common))
        else:
            drive, tail = os.path.splitdrive(p)
            names.append(os.path.join(drive.replace(":", ""), tail.lstrip("\\/")))
    return names


def hash_file(path, chunk: int = 4 * 1024 * 1024, should_cancel=None) -> str:
    """Content hash of a file (blake2b, 128 bit) — what "identical" means for backups."""
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        while True:
            if should_cancel is not None and should_cancel():
                raise InterruptedError("cancelled")
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _copy_with_hash(src: Path, dest: Path, chunk: int = 4 * 1024 * 1024) -> str:
    """Copies src to dest (keeping times) and returns the content hash, in one pass."""
    h = hashlib.blake2b(digest_size=16)
    with open(src, "rb") as fin, open(dest, "wb") as fout:
        while True:
            block = fin.read(chunk)
            if not block:
                break
            h.update(block)
            fout.write(block)
    shutil.copystat(src, dest)
    return h.hexdigest()


def game_info_for(paths, unity_version: str = "", game_version: str = "") -> dict:
    """Which game these files belong to: the folder that holds the `*_Data` folder (name from the
    game's own app.info when present), else the folder the files share.

    `game_version` (the developer-set app version, PlayerSettings.bundleVersion — see
    core.loader.resolve_game_version's own docstring for why it's a different field entirely from
    `unity_version`, the Unity ENGINE version) is only ever known by a caller that still has the
    game's Environment loaded at backup time — not resolvable from bare file paths the way
    everything else in this function is, so it's accepted, not derived here."""
    resolved = [os.path.abspath(p) for p in paths]
    data_dir = ""
    for p in resolved:
        cur = os.path.dirname(p)
        while cur and cur != os.path.dirname(cur):
            if os.path.basename(cur).lower().endswith("_data"):
                data_dir = cur
                break
            cur = os.path.dirname(cur)
        if data_dir:
            break
    if data_dir:
        root = os.path.dirname(data_dir)
        name = os.path.basename(root) or os.path.basename(data_dir)[:-5]
        try:
            with open(os.path.join(data_dir, "app.info"), encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
            if len(lines) >= 2:
                name = lines[1]
        except OSError:
            pass
    else:
        try:
            root = os.path.commonpath([os.path.dirname(p) for p in resolved]) if resolved else ""
        except ValueError:
            root = ""
        name = os.path.basename(root) or "?"
    info = {"name": name, "root": root}
    if unity_version:
        info["unity_version"] = unity_version
    if game_version:
        info["game_version"] = game_version
    return info


def path_within(path: str, scope) -> bool:
    """True if `path` is one of the files, or inside one of the folders, listed in `scope`."""
    target = os.path.normcase(os.path.abspath(path))
    for item in scope or []:
        cand = os.path.normcase(os.path.abspath(item))
        if target == cand or target.startswith(cand.rstrip("\\/") + os.sep):
            return True
    return False


def create_backup(paths: List[Path], root: Optional[Path] = None,
                  keep_latest: Optional[int] = None, reason: str = "overwrite",
                  game: Optional[dict] = None) -> Optional[Path]:
    """Copies every EXISTING file in `paths` into a new dated folder under `root` (default:
    default_backup_root()) and returns that folder — None if none of the files exist yet
    (nothing to protect). Raises BackupError if there isn't room or a copy fails; the
    half-made folder is removed then, so a failed backup never looks like a good one.
    keep_latest (if given) prunes older copies afterwards - see prune_backups().
    The manifest also records the game the files belong to (`game`, or worked out from the paths),
    why the backup was made (`reason`) and each file's size, time and content hash.""" 
    existing = [Path(p) for p in paths if Path(p).is_file()]
    if not existing:
        return None
    root = Path(root) if root else default_backup_root()

    needed = sum(p.stat().st_size for p in existing)
    try:
        root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(root).free
    except OSError as e:
        raise BackupError(tr("Не удалось подготовить папку для резервной копии «{root}»: {error}", root=root, error=e)) from e
    if free < needed + _SPACE_MARGIN:
        raise BackupError(
            tr("Недостаточно места для резервной копии: нужно {value:,.0f} МБ, свободно {value2:,.0f} МБ (папка "
               "«{root}»). Файлы не изменены.", value=needed / 1024 ** 2, value2=free / 1024 ** 2, root=root)
        )

    folder = _unique_folder(root)
    entries = []
    try:
        for src, rel in zip(existing, _relative_names(existing)):
            dest = folder / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            digest = _copy_with_hash(src, dest)
            st = src.stat()
            entries.append({"backup": rel.replace("\\", "/"), "original": str(os.path.abspath(src)),
                            "size": st.st_size, "mtime": st.st_mtime, "hash": digest})
        (folder / MANIFEST_NAME).write_text(
            json.dumps({"created": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": reason,
                        "game": game or game_info_for(existing), "files": entries},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise BackupError(tr("Не удалось создать резервную копию: {error}. Файлы не изменены.", error=e)) from e
    if keep_latest is not None:
        try:
            prune_backups(root, keep_latest)
        except OSError:
            pass  # cleaning up is best-effort; the new backup itself is fine
    return folder


def _read_manifest(folder: Path) -> Optional[dict]:
    try:
        return json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def prune_backups(root: Optional[Path] = None, keep_latest: int = 1) -> int:
    """Deletes copies nobody needs. Per original file: keep the oldest copy and the newest
    `keep_latest` copies. A backup folder that ends up with no files is removed. Returns the
    number of bytes freed."""
    root = Path(root) if root else default_backup_root()
    if not root.is_dir():
        return 0
    folders = []
    for f in sorted(p for p in root.iterdir() if p.is_dir()):  # names sort by time
        manifest = _read_manifest(f)
        if manifest is not None:
            folders.append((f, manifest))

    by_original = {}
    for f, manifest in folders:
        for entry in manifest.get("files", []):
            by_original.setdefault(entry["original"], []).append((f, entry))
    doomed = set()  # (folder, backup-relative name)
    for items in by_original.values():
        keep = {0} | set(range(max(0, len(items) - max(0, keep_latest)), len(items)))
        for i, (f, entry) in enumerate(items):
            if i not in keep:
                doomed.add((f, entry["backup"]))

    freed = 0
    for f, manifest in folders:
        gone = [e for e in manifest.get("files", []) if (f, e["backup"]) in doomed]
        if not gone:
            continue
        for e in gone:
            target = f / e["backup"]
            try:
                freed += target.stat().st_size
                target.unlink()
            except OSError:
                pass
        manifest["files"] = [e for e in manifest["files"] if (f, e["backup"]) not in doomed]
        if not manifest["files"]:
            shutil.rmtree(f, ignore_errors=True)
            continue
        (f / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        for sub in sorted((q for q in f.rglob("*") if q.is_dir()), reverse=True):
            try:
                sub.rmdir()  # only succeeds when empty
            except OSError:
                pass
    return freed


def folder_size(folder: Path) -> int:
    total = 0
    for dirpath, _dirs, names in os.walk(folder):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(dirpath, n))
            except OSError:
                pass
    return total


def backups_total_size(root: Optional[Path] = None) -> int:
    root = Path(root) if root else default_backup_root()
    return folder_size(root) if root.is_dir() else 0


@dataclass
class BackupInfo:
    folder: Path
    created: str
    files: List[dict] = field(default_factory=list)  # manifest entries: backup / original / size / hash
    game: dict = field(default_factory=dict)  # name / root / unity_version (empty for old backups)
    reason: str = ""

    @property
    def size(self) -> int:
        return sum(int(e.get("size", 0)) for e in self.files)


def list_backups(root: Optional[Path] = None) -> List[BackupInfo]:
    """Every backup under root, oldest first."""
    root = Path(root) if root else default_backup_root()
    found = []
    if root.is_dir():
        for f in sorted(p for p in root.iterdir() if p.is_dir()):
            manifest = _read_manifest(f)
            if manifest is not None:
                found.append(BackupInfo(f, manifest.get("created", ""), list(manifest.get("files", [])),
                                    dict(manifest.get("game") or {}), manifest.get("reason", "")))
    return found


def _game_matches(info_game: dict, wanted: str) -> bool:
    return wanted in (info_game.get("name", "") + " " + info_game.get("root", "")).lower()


def relocate_restore_targets(result: List[tuple], relocate: List[Tuple[str, str]]) -> List[tuple]:
    """Re-points restore targets after a game folder was moved: `relocate` is [(old, new)] and a target
    inside `old` is rewritten to the same place inside `new` (the first rule that fits wins). A rule that
    fits no target at all is refused - it is nearly always a typo, and silently ignoring it would restore
    into the old, wrong place after all."""
    rules = [(os.path.abspath(old), os.path.abspath(new)) for old, new in relocate]
    used = [False] * len(rules)
    moved = []
    for src, orig in result:
        target = Path(orig)
        absolute = os.path.abspath(orig)
        for i, (old, new) in enumerate(rules):
            if path_within(absolute, [old]):
                target = Path(new) / os.path.relpath(absolute, old)
                used[i] = True
                break
        moved.append((src, target))
    for (old, _new), hit in zip(rules, used):
        if not hit:
            raise BackupError(tr("В резервной копии нет файлов из «{old}» - проверьте путь. Ничего не изменено.", old=old))
    return moved


def _require_target_folders(result: List[tuple]) -> None:
    """Every restore target's own folder must still exist. Recreating a vanished folder tree used to be
    silent: after a game was moved, the restore "succeeded" by writing a stray half-copy of the game at
    the OLD location while the real, moved files stayed patched."""
    missing = sorted({str(orig.parent) for _s, orig in result if not orig.parent.is_dir()})
    if not missing:
        return
    shown = "\n".join(f"  {m}" for m in missing[:5]) + ("\n  " + tr("… и ещё {count}", count=len(missing) - 5) if len(missing) > 5 else "")
    raise BackupFolderMissing(
        tr("Эти папки больше не существуют, поэтому файлы из них некуда восстановить (возможно, игру "
           "перенесли или удалили):\n{shown}\nНичего не изменено.", shown=shown), missing)


def restore_backup(folder: Optional[Path] = None, root: Optional[Path] = None,
                   names: Optional[List[str]] = None, safety_copy: bool = True,
                   dry_run: bool = False, keep_latest: Optional[int] = 1,
                   copy: Optional[str] = None, game: Optional[str] = None,
                   relocate: Optional[List[Tuple[str, str]]] = None) -> List[tuple]:
    """Copies files from backups back to where they came from. Returns [(source_in_backup,
    original_path)] of what was (or, with dry_run, would be) restored.

    folder=None restores, for every original file, its OLDEST copy - the untouched original.
    `copy` (a date/time prefix such as "2026-09-24" or "2026-09-24 19:32", or a backup folder name)
    picks, for every file, its NEWEST copy made at that time instead; files without one are skipped.
    Otherwise it restores the files of that one backup folder. `names` (file names or full
    original paths, case-insensitive) narrows it down; a NAME that is not an exact path match for
    any candidate and matches more than one candidate BY BASENAME is refused with a list of what it
    matched, rather than silently restoring all of them — real reported gap: two different games
    happening to share a file name (e.g. both ship a "resources.assets") used to restore both from
    one `-f resources.assets`, with no warning either file belonged to another game. `game` (part of
    a game's name or folder, case-insensitive, same matching `backup list --game` already uses)
    narrows the candidate set to one game BEFORE names are resolved, which is what actually
    disambiguates a name that's ambiguous game-wide but not within one game — the two together are
    how the GUI stays exact even though the CLI's own selection here is fuzzy: `folder`/an exact
    full path always pins down one specific file/copy regardless of name collisions elsewhere; a
    bare name with no `--game` and no full path is refused if it's genuinely unclear which file it
    means, instead of guessing. `game` is ignored together with `folder` (that already pins an exact
    set of files). Unless safety_copy is off, the files that are about to be replaced are first
    backed up into a new folder, so a restore can itself be undone. Each file is written next to its
    target and swapped in, so a failure never leaves a half-written file. Raises BackupError if
    nothing matches, a name is ambiguous, or a copy fails.

    The safety copy counts as a normal backup: once the restore is done, old copies are pruned the
    usual way (prune_backups with keep_latest), so repeated restores never pile copies up. Pruning
    happens AFTER the files are back, since the chosen source may be one of the copies it would delete.

    A file whose own folder no longer exists (the game was moved) is never restored into a re-created
    copy of the old path: BackupFolderMissing is raised, nothing is changed, and `relocate`
    ([(old_folder, new_folder)]) says where the game lives now."""
    game_wanted = (game or "").strip().lower() or None
    if folder is not None:
        folder = Path(folder)
        manifest = _read_manifest(folder)
        if manifest is None:
            raise BackupError(tr("«{folder}» не похожа на папку резервной копии (нет {manifest_name}).", folder=folder, manifest_name=MANIFEST_NAME))
        candidates = [(folder / e["backup"], e["original"]) for e in manifest.get("files", [])]
    elif copy:
        chosen = {}
        for info in list_backups(root):
            if game_wanted and not _game_matches(info.game, game_wanted):
                continue
            if info.created.startswith(copy) or info.folder.name.startswith(copy):
                for e in info.files:
                    chosen[e["original"]] = info.folder / e["backup"]  # later copy wins
        candidates = [(src, original) for original, src in chosen.items()]
    else:
        oldest = {}
        for info in list_backups(root):
            if game_wanted and not _game_matches(info.game, game_wanted):
                continue
            for e in info.files:
                oldest.setdefault(e["original"], info.folder / e["backup"])
        candidates = [(src, original) for original, src in oldest.items()]

    if names:
        wanted = {n.lower() for n in names}
        exact_paths = {orig.lower() for _s, orig in candidates}
        ambiguous = {}
        for n in wanted:
            if n in exact_paths:  # a full path always pins down exactly one file
                continue
            hits = sorted({orig for _s, orig in candidates if os.path.basename(orig).lower() == n})
            if len(hits) > 1:
                ambiguous[n] = hits
        if ambiguous:
            lines = ["  " + tr("«{name}» — сразу в нескольких играх:", name=n) + "\n    " + "\n    ".join(hits)
                     for n, hits in ambiguous.items()]
            raise BackupError(
                tr("Неоднозначное имя файла, нужен полный путь или --game:") + "\n" + "\n".join(lines)
            )
        candidates = [(src, orig) for src, orig in candidates
                      if orig.lower() in wanted or os.path.basename(orig).lower() in wanted]
    if not candidates:
        raise BackupError(tr("Нет подходящих резервных копий для восстановления."))
    missing = [str(src) for src, _o in candidates if not Path(src).is_file()]
    if missing:
        raise BackupError(tr("В резервной копии не хватает файлов: {files}", files=", ".join(missing)))

    result = [(Path(src), Path(orig)) for src, orig in candidates]
    if relocate:
        result = relocate_restore_targets(result, relocate)
    _require_target_folders(result)  # also for a dry run: it must not promise what the real run refuses
    if dry_run:
        return result

    _apply_restore(result, root, safety_copy, keep_latest)
    return result


def _apply_restore(result, root, safety_copy: bool, keep_latest) -> None:
    _require_target_folders(result)
    if safety_copy:
        create_backup([orig for _s, orig in result], root, reason="restore")  # None if none of them exists
    for src, orig in result:
        tmp = orig.with_name(orig.name + ".ustudio-restore")
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, orig)
        except OSError as e:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise BackupError(tr("Не удалось восстановить «{orig}»: {error}. Возможно, файл занят другой программой.", orig=orig, error=e)) from e
    if safety_copy and keep_latest is not None:
        try:
            prune_backups(root, keep_latest)
        except OSError:
            pass  # best-effort cleanup


def restore_copies(pairs: List[tuple], root: Optional[Path] = None, safety_copy: bool = True,
                   keep_latest: Optional[int] = 1) -> List[tuple]:
    """Puts each chosen copy back: `pairs` is [(copy_path, original_path)]. Same safety copy, atomic
    swap and pruning as restore_backup()."""
    result = [(Path(src), Path(orig)) for src, orig in pairs]
    if not result:
        raise BackupError(tr("Не выбрано ни одного файла."))
    missing = [str(src) for src, _o in result if not src.is_file()]
    if missing:
        raise BackupError(tr("В резервной копии не хватает файлов: {files}", files=", ".join(missing)))
    _apply_restore(result, root, safety_copy, keep_latest)
    return result


@dataclass
class OriginalEntry:
    """One original file that has backups: where it lives, its oldest copy and how many there are."""
    original: str
    oldest_created: str
    copies: int
    size: int                 # size of the oldest copy
    oldest_path: str = ""     # the oldest copy itself (what a plain restore puts back)
    oldest_hash: str = ""     # its content hash ("" for backups made before hashes were recorded)
    game: str = ""            # game name from the manifest ("" for old backups)
    game_version: str = ""    # the game's own version at the OLDEST copy ("" if never resolved)


def originals_with_backups(root: Optional[Path] = None, within=None) -> List[OriginalEntry]:
    """Every original file that has at least one backup, sorted by path. `within` (a list of files
    and/or folders — typically what is loaded right now) keeps only the files inside it."""
    seen = {}
    for info in list_backups(root):  # oldest first
        for e in info.files:
            if within is not None and not path_within(e["original"], within):
                continue
            entry = seen.get(e["original"])
            if entry is None:
                seen[e["original"]] = OriginalEntry(
                    e["original"], info.created, 1, int(e.get("size", 0)),
                    str(info.folder / e["backup"]), e.get("hash", ""), info.game.get("name", ""),
                    info.game.get("game_version", ""))
            else:
                entry.copies += 1
    return sorted(seen.values(), key=lambda x: x.original.lower())


@dataclass
class BackupCopy:
    """One stored copy of one original file."""
    original: str
    path: str          # the copy itself
    folder: str        # the backup folder it lives in
    backup_name: str   # its name inside that folder (manifest key)
    created: str
    reason: str        # "overwrite" | "restore" | "version" | "" (old backups)
    size: int
    hash: str = ""
    game: str = ""


def copies_of(original: str, root: Optional[Path] = None) -> List[BackupCopy]:
    """Every stored copy of `original`, oldest first."""
    found = []
    key = os.path.normcase(os.path.abspath(original))
    for info in list_backups(root):
        for e in info.files:
            if os.path.normcase(os.path.abspath(e["original"])) == key:
                path = info.folder / e["backup"]
                found.append(BackupCopy(e["original"], str(path), str(info.folder), e["backup"], info.created,
                                        info.reason, int(e.get("size", 0)), e.get("hash", ""),
                                        info.game.get("name", "")))
    return found


def delete_copy(copy: BackupCopy) -> None:
    """Removes one stored copy (its file and its manifest entry; the folder goes when it is empty)."""
    folder = Path(copy.folder)
    manifest = _read_manifest(folder)
    if manifest is None:
        raise BackupError(tr("«{folder}» не похожа на папку резервной копии.", folder=folder))
    try:
        Path(copy.path).unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        raise BackupError(tr("Не удалось удалить копию: {error}", error=e)) from e
    manifest["files"] = [e for e in manifest.get("files", []) if e["backup"] != copy.backup_name]
    if not manifest["files"]:
        shutil.rmtree(folder, ignore_errors=True)
        return
    (folder / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_backup_folder(folder: Path) -> None:
    try:
        shutil.rmtree(folder)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise BackupError(tr("Не удалось удалить папку резервной копии «{folder}»: {error}", folder=folder, error=e)) from e


def delete_backups_of(originals, root: Optional[Path] = None) -> int:
    """Removes EVERY stored copy of each of `originals` (all their backup folders' entries; a folder
    left with no files goes). Other files' copies in the same folders stay. Returns the bytes freed."""
    wanted = {os.path.normcase(os.path.abspath(o)) for o in originals}
    freed = 0
    for info in list_backups(root):
        gone = [e for e in info.files if os.path.normcase(os.path.abspath(e["original"])) in wanted]
        if not gone:
            continue
        keep = [e for e in info.files if e not in gone]
        if not keep:
            freed += folder_size(info.folder)
            _remove_backup_folder(info.folder)
            continue
        for e in gone:
            target = info.folder / e["backup"]
            try:
                size = target.stat().st_size
                target.unlink()
                freed += size
            except FileNotFoundError:
                pass
            except OSError as err:
                raise BackupError(tr("Не удалось удалить копию «{target}»: {error}", target=target, error=err)) from err
        manifest = _read_manifest(info.folder) or {}
        manifest["files"] = keep
        (info.folder / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        for sub in sorted((q for q in info.folder.rglob("*") if q.is_dir()), reverse=True):
            try:
                sub.rmdir()  # only succeeds when empty
            except OSError:
                pass
    return freed


def delete_all_backups(root: Optional[Path] = None) -> int:
    """Removes every backup folder under root (only folders with a backup manifest — anything else
    in that folder is left alone). Returns the bytes freed."""
    freed = 0
    for info in list_backups(root):
        freed += folder_size(info.folder)
        _remove_backup_folder(info.folder)
    return freed


STATUS_MISSING = "missing"      # the file no longer exists
STATUS_DIFFERENT = "different"  # it differs from the backup (was changed since)
STATUS_SAME = "same"            # identical to the backup
STATUS_UNKNOWN = "unknown"      # same size, content not compared yet


def quick_status(entry: OriginalEntry) -> str:
    """Cheap comparison of the current file with the backup: existence and size only."""
    try:
        size = os.path.getsize(entry.original)
    except OSError:
        return STATUS_MISSING
    return STATUS_DIFFERENT if size != entry.size else STATUS_UNKNOWN


def exact_status(entry: OriginalEntry, should_cancel=None) -> str:
    """Full comparison (hashes the current file when the size matches)."""
    status = quick_status(entry)
    if status != STATUS_UNKNOWN:
        return status
    try:
        current = hash_file(entry.original, should_cancel=should_cancel)
        reference = entry.oldest_hash or hash_file(entry.oldest_path, should_cancel=should_cancel)
    except OSError:
        return STATUS_MISSING
    return STATUS_SAME if current == reference else STATUS_DIFFERENT
