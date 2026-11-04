"""Writing a Unity version INTO game files whose header has none.

Some games ship files with the version stripped: a UnityFS bundle whose header says
"5.x.x" / "0.0.0" and whose SerializedFiles carry unity_version "0.0.0" (typically with no type tree,
so reading the objects needs the version to pick the right layouts). Such files load only with a
"fallback version" typed into the settings — every session, every tool. This module writes the real
version into the files once, so they carry it themselves.

What is written (everything else is left as it was):
  * UnityFS bundle: the header's engine version (BundleFile.version_engine; the player version
    "5.x.x" is what Unity itself writes and stays) and, in every SerializedFile entry, unity_version.
    Entries that are not SerializedFiles (.resS / .resource) are passed through byte for byte.
  * Loose SerializedFile (level0, *.assets, ...): its unity_version.
Both go through UnityPy's own save(), the path every edit of this app already saves through (see
save_manager.save_bundle_with_entries) — no hand-made byte surgery on the headers. A file that already
has a real version is skipped unless `force` is given; with `force` a differing version is replaced
(re-flashing after a wrong one), and a file that already carries exactly the requested version is left as it is.

Safety: the result is never trusted blindly. patch_file() writes it beside the target, REOPENS it with
no fallback version set at all (the point of the whole exercise), and compares it with the original
(versions written; same entries, same objects, byte-identical object data) before anything is replaced.
"""

from __future__ import annotations

from core.i18n import tr
import contextlib
import hashlib
import logging
import os
import re
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import UnityPy
from UnityPy import config as _unitypy_config
from UnityPy.enums import FileType
from UnityPy.files.BundleFile import BundleFile, clear_bundle_cache
from UnityPy.files.SerializedFile import SerializedFile
from UnityPy.helpers.ImportHelper import check_file_type
from UnityPy.helpers.UnityVersion import UnityVersion

from core.backup import create_backup
from core.gc_freeze import collect_everything
from core.loader import NON_UNITY_BINARY_SUFFIXES
from core.save_manager import (
    SaveError, _check_not_locked, _retry_on_lock, release_environment, save_bundle_with_entries,
)
from core.save_manager import original_path as _bundle_id_of

logger = logging.getLogger(__name__)

# 2020.3.47f1, 6000.0.63f1, 2017.4.40f1c1 (the Chinese-region suffix) — written to the file as typed.
_VERSION_RE = re.compile(r"^\d{1,4}\.\d{1,2}\.\d{1,3}[abfpc]\d{1,3}([a-z]\d{1,3})?$")

# Resource payloads next to assets files: never a Unity container themselves.
_RESOURCE_SUFFIXES = frozenset({".ress", ".resource"})

STATUS_PATCHED = "patched"
STATUS_ALREADY_OK = "already_ok"
STATUS_NOT_UNITY = "not_unity"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"


class VersionWriteError(Exception):
    """str(e) is a complete, user-facing message."""


def validate_version(text: str) -> str:
    """The version as it will be written ("6000.0.63f1"), or ValueError with a user-facing message."""
    version = (text or "").strip()
    if not _VERSION_RE.match(version):
        raise ValueError(tr("Версия должна выглядеть так: 2021.3.0f1 или 6000.0.58f2."))
    try:
        if UnityVersion.from_str(version).major == 0:
            raise ValueError
    except ValueError:
        raise ValueError(tr("Версия должна выглядеть так: 2021.3.0f1 или 6000.0.58f2.")) from None
    return version


def is_stripped_version(text) -> bool:
    """True for a version string a reader cannot use: empty, "0.0.0", "5.x.x", anything unparsable."""
    if not isinstance(text, str) or not text.strip():
        return True
    try:
        return UnityVersion.from_str(text.strip()).major == 0
    except Exception:  # noqa: BLE001 - from_str raises ValueError, but any failure means "unusable"
        return True


@contextlib.contextmanager
def _fallback_version(version: Optional[str]):
    """UnityPy.config.FALLBACK_UNITY_VERSION set for the block (None = no fallback at all), restored after.
    A process-wide setting: callers run one operation at a time (the dialog is modal)."""
    saved = _unitypy_config.FALLBACK_UNITY_VERSION
    _unitypy_config.FALLBACK_UNITY_VERSION = version
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield
    finally:
        _unitypy_config.FALLBACK_UNITY_VERSION = saved


@dataclass
class VersionState:
    """What a file currently says about its version."""
    path: str
    kind: str                                   # "bundle" | "serialized"
    bundle_engine: Optional[str] = None         # a bundle's header engine version
    entries: List[tuple] = field(default_factory=list)   # [(entry name, unity_version)] of its SerializedFiles

    @property
    def needs_version(self) -> bool:
        """Some place that should carry a version has none."""
        if self.kind == "bundle" and is_stripped_version(self.bundle_engine):
            return True
        return any(is_stripped_version(v) for _n, v in self.entries)


@dataclass
class PatchResult:
    path: str
    status: str
    message: str = ""
    written_to: str = ""
    backup_folder: str = ""


# --------------------------------------------------------------------------- finding files

def find_unity_files(paths: Iterable[str], should_cancel: Callable[[], bool] = lambda: False) -> List[str]:
    """Files among `paths` (files and/or folders, searched recursively) that are Unity bundles or
    loose SerializedFiles, sorted. Judged by content (a header check), not by extension."""
    found: List[str] = []
    candidates: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for dirpath, _dirs, names in os.walk(p):
                candidates.extend(os.path.join(dirpath, n) for n in names)
        elif os.path.isfile(p):
            candidates.append(p)
    for path in candidates:
        if should_cancel():
            break
        suffix = os.path.splitext(path)[1].lower()
        if suffix in NON_UNITY_BINARY_SUFFIXES or suffix in _RESOURCE_SUFFIXES:
            continue
        if _file_kind(path) in ("bundle", "serialized"):
            found.append(path)
    return sorted(found, key=str.lower)


def _file_kind(path: str) -> Optional[str]:
    """"bundle" (UnityFS), "serialized" (a loose SerializedFile), "unsupported" (another Unity container:
    old UnityWeb/UnityRaw bundles, web data) or None (not a Unity file / unreadable)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if head.startswith(b"UnityFS\x00"):
            return "bundle"
        file_type, reader = check_file_type(path)
        try:
            if file_type == FileType.AssetsFile:
                return "serialized"
            if file_type in (FileType.BundleFile, FileType.WebFile):
                return "unsupported"
            return None
        finally:
            dispose = getattr(reader, "dispose", None)
            if dispose is not None:
                dispose()
    except Exception:  # noqa: BLE001 - an unreadable file is simply "not a Unity file" here
        return None


# --------------------------------------------------------------------------- reading / patching

def _open(path: str, version_for_loading: Optional[str]):
    """Loads one file; returns (env, root file). A stripped file cannot be loaded without some fallback
    version, hence `version_for_loading`."""
    name = os.path.basename(str(path))
    try:
        with _fallback_version(version_for_loading):
            env = UnityPy.load(str(path))
    except Exception as e:  # noqa: BLE001 - UnityPy raises many kinds; the user needs one clear sentence
        cause = (str(e).splitlines() or [type(e).__name__])[0]
        if version_for_loading:
            raise VersionWriteError(
                tr("«{name}»: с версией {version_for_loading} файл не читается. Проверьте, что версия указана "
                   "верно. ({cause})", name=name, version_for_loading=version_for_loading, cause=cause)) from e
        raise VersionWriteError(tr("«{name}»: файл не открывается без указания версии. ({cause})", name=name, cause=cause)) from e
    roots = list(env.files.values())
    if len(roots) != 1:
        release_environment(env)
        raise VersionWriteError(tr("«{basename}»: ожидался один файл, найдено {count}.", basename=os.path.basename(path), count=len(roots)))
    return env, roots[0]


def _release(env, root=None) -> None:
    """Lets go of everything a loaded file holds, so the file can be replaced right after. Besides the
    environment's own handles that includes the global block cache: for an UNCOMPRESSED bundle a cached
    block is a zero-copy view of the file's own memory mapping, which keeps the file locked (found
    here: replacing a verified copy of an uncompressed bundle failed with "file in use")."""
    release_environment(env)
    bundle_id = _bundle_id_of(root) if root is not None else None
    if bundle_id:
        clear_bundle_cache(bundle_id)


def _state_of(path: str, root) -> VersionState:
    if isinstance(root, BundleFile):
        entries = [(name, f.unity_version) for name, f in root.files.items() if isinstance(f, SerializedFile)]
        return VersionState(path, "bundle", root.version_engine, entries)
    if isinstance(root, SerializedFile):
        return VersionState(path, "serialized", None, [(root.name, root.unity_version)])
    raise VersionWriteError(tr("«{basename}»: этот тип файла не поддерживается.", basename=os.path.basename(path)))


def read_versions(path: str, probe_version: str = "2020.3.47f1") -> Optional[VersionState]:
    """The version fields of `path`, or None when it is not a supported Unity file. `probe_version` only
    lets a stripped file load at all; it is never written anywhere."""
    kind = _file_kind(path)
    if kind not in ("bundle", "serialized"):
        return None
    env, root = _open(path, probe_version)
    try:
        return _state_of(path, root)
    finally:
        _release(env, root)


def _needs(current, version: str, force: bool) -> bool:
    """Whether a place holding `current` has to be written: without `force` only a missing/unusable version,
    with `force` anything but exactly `version`."""
    return current != version if force else is_stripped_version(current)


def build_patched_bytes(path: str, version: str, force: bool = False):
    """(bytes or None, VersionState before, count of places changed). None bytes = nothing to write
    (no place needs it: all have a real version and `force` is off, or all already hold `version`)."""
    env, root = _open(path, version)
    try:
        before = _state_of(path, root)
        if isinstance(root, BundleFile):
            if root.signature != "UnityFS":
                raise VersionWriteError(tr("«{basename}»: поддерживаются бандлы UnityFS (здесь {signature}).", basename=os.path.basename(path), signature=root.signature))
            engine = _needs(root.version_engine, version, force)
            stale = [e for e in root.files.values()
                     if isinstance(e, SerializedFile) and _needs(e.unity_version, version, force)]
            if not engine and not stale:
                return None, before, 0
            if engine:
                root.version_engine = version
            for entry in stale:
                entry.set_version(version)
            return save_bundle_with_entries(root, stale), before, len(stale) + engine
        if not _needs(root.unity_version, version, force):
            return None, before, 0
        root.set_version(version)
        return root.save(), before, 1
    finally:
        _release(env, root)


def _remove_quietly(path: Path) -> None:
    """Deletes a leftover temporary file. A copy that failed to open may still be mapped until the garbage
    collector has run, so a refused delete is retried after one."""
    for _attempt in range(4):
        try:
            if path.exists():
                path.unlink()
            return
        except OSError:
            collect_everything()
            time.sleep(0.1)


def _digest(data) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def verify_patched(patched_path: str, original_path: str, version: str, force: bool = False) -> None:
    """Raises VersionWriteError unless `patched_path` is the original with the version written and
    nothing else different. Opens the patched file with NO fallback version, so a file that still
    needs one fails here instead of in the user's next session."""
    name = os.path.basename(original_path)
    try:
        env_new, new = _open(patched_path, None)
    except VersionWriteError as e:
        raise VersionWriteError(
            tr("«{name}»: с записанной версией {version} файл не читается. Проверьте, что версия указана верно. "
               "Файл не изменён. ({error})", name=name, version=version, error=e)) from e
    env_old = old = None
    try:
        env_old, old = _open(original_path, version)
        state = _state_of(patched_path, new)
        if state.needs_version:
            raise VersionWriteError(tr("«{name}»: в записанном файле версия всё ещё не указана.", name=name))
        if isinstance(new, BundleFile):
            if (force or is_stripped_version(old.version_engine)) and new.version_engine != version:
                raise VersionWriteError(tr("«{name}»: версия в заголовке бандла не записалась.", name=name))
            if list(new.files) != list(old.files):
                raise VersionWriteError(tr("«{name}»: изменился состав файлов внутри бандла.", name=name))
            pairs = [(old.files[n], new.files[n]) for n in old.files]
        else:
            pairs = [(old, new)]
        for old_f, new_f in pairs:
            if isinstance(old_f, SerializedFile):
                if not isinstance(new_f, SerializedFile):
                    raise VersionWriteError(tr("«{name}»: внутренний файл потерял формат.", name=name))
                if (force or is_stripped_version(old_f.unity_version)) and new_f.unity_version != version:
                    raise VersionWriteError(tr("«{name}»: версия в «{name2}» не записалась.", name=name, name2=new_f.name))
                if set(old_f.objects) != set(new_f.objects):
                    raise VersionWriteError(tr("«{name}»: изменился список объектов в «{name2}».", name=name, name2=new_f.name))
                for pid, old_obj in old_f.objects.items():
                    if old_obj.type.name != new_f.objects[pid].type.name or \
                            _digest(old_obj.get_raw_data()) != _digest(new_f.objects[pid].get_raw_data()):
                        raise VersionWriteError(tr("«{name}»: данные объекта {pid} в «{name2}» изменились.", name=name, pid=pid, name2=new_f.name))
            else:
                old_bytes, new_bytes = getattr(old_f, "bytes", None), getattr(new_f, "bytes", None)
                if old_bytes is not None and (new_bytes is None or _digest(old_bytes) != _digest(new_bytes)):
                    raise VersionWriteError(tr("«{name}»: изменилось содержимое ресурса внутри бандла.", name=name))
    finally:
        _release(env_new, new)
        if env_old is not None:
            _release(env_old, old)


# --------------------------------------------------------------------------- the operation

def patch_file(src: str, version: str, dest: Optional[str] = None, *, force: bool = False,
               backup: bool = False, backup_keep: Optional[int] = None) -> PatchResult:
    """See _patch_one(). A file that failed part-way is still mapped by the half-built objects of the
    failed attempt (they live in reference cycles, and the exception's traceback holds them until it is
    gone), which would keep it locked for the next attempt or for the game: collect right after."""
    result = _patch_one(src, version, dest, force=force, backup=backup, backup_keep=backup_keep)
    if result.status == STATUS_ERROR:
        collect_everything()
    return result


def _patch_one(src: str, version: str, dest: Optional[str] = None, *, force: bool = False,
               backup: bool = False, backup_keep: Optional[int] = None) -> PatchResult:
    """Writes `version` into `src`.
      dest   - write the result there (folders are created) and leave `src` alone; None = replace `src`.
      force  - also replace a version that is already real but differs from `version`.
      backup - when replacing `src`: copy it into the backups folder first (see core.backup).
    Nothing is replaced unless the result passed verify_patched(). Never raises for a per-file problem:
    the outcome is in PatchResult.status/.message."""
    src = str(src)
    try:
        kind = _file_kind(src)
        if kind is None:
            return PatchResult(src, STATUS_NOT_UNITY, tr("не файл Unity"))
        if kind == "unsupported":
            return PatchResult(src, STATUS_UNSUPPORTED, tr("этот тип контейнера не поддерживается"))
        data, before, _changed = build_patched_bytes(src, version, force)
        if data is None:
            return PatchResult(src, STATUS_ALREADY_OK, tr("версия уже указана"))
        target = Path(dest) if dest else Path(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".ustudio_tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            del data
            verify_patched(str(tmp), src, version, force)
            backup_folder = ""
            if dest is None:
                collect_everything()  # the loaded copies of `src` die in reference cycles; they must not hold it
                if backup:
                    folder = create_backup([Path(src)], keep_latest=backup_keep, reason="version")
                    backup_folder = str(folder) if folder else ""
                _check_not_locked(target)
            _retry_on_lock(lambda: os.replace(tmp, target), label=target.name)
        finally:
            _remove_quietly(tmp)
        return PatchResult(src, STATUS_PATCHED, tr("версия записана"), str(target), backup_folder)
    except (VersionWriteError, SaveError) as e:
        return PatchResult(src, STATUS_ERROR, str(e))
    except Exception as e:  # noqa: BLE001 - one bad file must not stop a batch
        logger.exception("version write failed for %s", src)
        return PatchResult(src, STATUS_ERROR, str(e) or type(e).__name__)


# --------------------------------------------------------------------------- many files at once

@dataclass
class BatchResult:
    results: List[PatchResult] = field(default_factory=list)
    backup_folder: str = ""
    cancelled: bool = False

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)


def plan_files(sources: Iterable[str], out_dir: Optional[str] = None,
               should_cancel: Callable[[], bool] = lambda: False) -> List[tuple]:
    """[(file, destination or None)] for files and/or folders in `sources`. With `out_dir` the copies go
    there, keeping each folder's own name and the structure below it (a single file lands directly in
    `out_dir`); without it the destination is None = replace in place."""
    plan: List[tuple] = []
    for source in sources:
        base = os.path.dirname(os.path.abspath(source)) if os.path.isdir(source) else os.path.dirname(source)
        for path in find_unity_files([source], should_cancel):
            dest = os.path.join(out_dir, os.path.relpath(path, base)) if out_dir else None
            plan.append((path, dest))
    return plan


def patch_many(plan: List[tuple], version: str, *, force: bool = False, backup: bool = False,
               backup_keep: Optional[int] = None,
               progress: Callable[[str, int, int, str], None] = lambda phase, i, n, name: None,
               should_cancel: Callable[[], bool] = lambda: False) -> BatchResult:
    """patch_file() for every (file, dest) in `plan`. When files are replaced in place and `backup` is on,
    ONE backup folder holds exactly the files that will change (found in a first pass), made before
    anything is touched; if it cannot be made, nothing is changed."""
    batch = BatchResult()
    in_place = any(dest is None for _src, dest in plan)
    if in_place and backup:
        needing = []
        for i, (src, dest) in enumerate(plan):
            if should_cancel():
                batch.cancelled = True
                return batch
            progress("check", i, len(plan), os.path.basename(src))
            if dest is not None:
                continue
            try:
                state = read_versions(src, version)
            except Exception:  # noqa: BLE001 - reported properly by the patch pass below
                state = None
            if state is not None and (force or state.needs_version):
                needing.append(Path(src))
        if needing:
            try:
                folder = create_backup(needing, keep_latest=backup_keep, reason="version")
            except Exception as e:  # noqa: BLE001 - BackupError: files are untouched
                batch.results.append(PatchResult("", STATUS_ERROR, str(e)))
                return batch
            batch.backup_folder = str(folder) if folder else ""
    for i, (src, dest) in enumerate(plan):
        if should_cancel():
            batch.cancelled = True
            break
        progress("write", i, len(plan), os.path.basename(src))
        batch.results.append(patch_file(src, version, dest, force=force, backup=False))
    return batch
