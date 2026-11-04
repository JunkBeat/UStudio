"""Where a game's Unity data comes from — one place to add a platform.

A Windows/Linux build is just a folder, which the loader reads directly. Other platforms ship
the data inside a container (an Android APK, an iOS IPA, ...) or with its own layout, and each
needs the same three questions answered:

  1. can this input be handled by me?                       ``matches(path)``
  2. how do I get the Unity data onto disk as a folder?     ``prepare(path, ...)``
  3. where are the script-metadata files the TypeTreeGenerator needs (IL2CPP binary +
     global-metadata.dat, or the Managed DLL folder), and can the result be saved back
     over the original?                                     ``PreparedSource``

Everything downstream is platform-neutral: ``EnvironmentLoader`` asks ``find_adapter()``
first and, when an adapter claims the input, loads the ``PreparedSource.data_dir`` as an
ordinary folder; ``init_typetree`` uses ``il2cpp_binary``/``il2cpp_metadata``/``managed_dir``
whatever their platform; saving refuses an in-place overwrite when
``read_only_reason`` is set (``env.source_read_only_reason``) and otherwise treats the
unpacked folder like any other. So supporting one more platform UnityPy can already read is
one adapter class registered here — see ``AndroidApkAdapter`` and ``ZipContainerAdapter``
(a new zip-based layout, e.g. an iOS IPA, is a few lines of configuration).

Why unpack a container at all instead of reading it in place: a zip entry is a compressed
stream, and Unity's readers seek and query the length constantly — every backwards seek makes
``ZipExtFile`` re-inflate the entry from its start. Profiled on "Lookouts Android v1.3.apk"
(136 MB): 48 s to load, 37 s of it ``zlib.decompress`` (19,000 calls on a few big entries).
Unpacking each entry once takes seconds, after which everything behaves as for a folder:
memory-mapped loose files, ``.splitN`` merging, ``.resource`` files beside the assets that
need them, the nearest-resource logic — and the IL2CPP files are real files on disk, which
the TypeTreeGenerator requires.

Unpacked data is a cache under ``%LOCALAPPDATA%/UStudio/<adapter>_cache/<key>/``. The key is a
fingerprint of the container's CONTENT (entry names, sizes and CRC-32s from the zip's central
directory), so a newer APK — even one that keeps its name, size and timestamp — can never be
served an older unpack; an unpack of the same path that became obsolete is removed; and the
cache is bounded (``prune_cache``: unused for 30 days, or beyond 4 GB oldest-used first) and
can be emptied (``clear_cache``)."""

from core.i18n import N_, tr
import hashlib
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

ProgressCallback = Optional[Callable[[int, int, str], None]]
CancelCheck = Optional[Callable[[], bool]]


@dataclass
class PreparedSource:
    """A game's data on disk, as the loader needs it."""
    label: str                    # shown to the user, e.g. "Android APK"
    origin: str                   # the input the data came from (the .apk path)
    data_dir: str                 # folder holding globalgamemanagers/levelN/bundles/resources
    il2cpp_binary: str = ""       # libil2cpp.so / GameAssembly.dll / UnityFramework ... ("" = none)
    il2cpp_metadata: str = ""     # global-metadata.dat ("" = none)
    managed_dir: str = ""         # folder of Managed DLLs for a Mono build ("" = none)
    read_only_reason: str = ""    # non-empty: saving over the original is impossible; why
    reused: bool = False          # an earlier unpack was reused


class GameSourceAdapter:
    """One platform's way of turning an input into a ``PreparedSource``."""

    name = "generic"

    def matches(self, path: str) -> bool:
        raise NotImplementedError

    def prepare(self, path: str, progress_cb: ProgressCallback = None,
                should_cancel: CancelCheck = None) -> PreparedSource:
        raise NotImplementedError


_ADAPTERS: List[GameSourceAdapter] = []


def register_adapter(adapter: GameSourceAdapter) -> None:
    """Later registrations are asked first, so a specific adapter can override a broad one."""
    _ADAPTERS.insert(0, adapter)


def find_adapter(path: str) -> Optional[GameSourceAdapter]:
    for adapter in _ADAPTERS:
        try:
            if adapter.matches(path):
                return adapter
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------------------
# zip-based containers (Android APK today; an iOS IPA is another configuration)
# --------------------------------------------------------------------------------------

def _safe_target(root: Path, name: str) -> Optional[Path]:
    """root/name, or None if the entry would land outside root (zip-slip)."""
    import posixpath
    if posixpath.normpath(name) != name or name.startswith("/"):
        return None  # ".." segments, doubled slashes, absolute names: never a real Unity entry
    target = (root / name).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


class ZipContainerAdapter(GameSourceAdapter):
    """A zip whose Unity data sits under one prefix. Configure:

    suffixes          file extensions this adapter claims
    data_prefixes     entry-name prefixes that hold the Unity data (first one with entries wins);
                      may contain one ``*`` path segment (e.g. ``Payload/*.app/Data/``)
    il2cpp_libs       (entry glob-ish suffix, preference order) for the IL2CPP binary
    metadata_relpath  metadata location relative to the data folder
    read_only_reason  why saving in place is impossible (a signed package)
    """

    name = "zip"
    suffixes: tuple = ()
    data_prefixes: tuple = ()
    il2cpp_lib_suffixes: tuple = ()          # entry-name suffixes, in preference order
    metadata_relpath = "Managed/Metadata/global-metadata.dat"
    label = "zip"
    read_only_reason = ""

    def matches(self, path: str) -> bool:
        return str(path).lower().endswith(self.suffixes) and zipfile.is_zipfile(path)

    # -- helpers a subclass may override -------------------------------------------------
    def _split_prefix(self, names) -> Optional[str]:
        """The concrete data prefix present in `names` (expands the optional ``*``, one
        path segment: "Payload/*.app/Data/" -> "Payload/Some.app/Data/")."""
        for pattern in self.data_prefixes:
            if "*" not in pattern:
                if any(n.startswith(pattern) for n in names):
                    return pattern
                continue
            head, tail = pattern.split("*", 1)
            for n in names:
                if not n.startswith(head):
                    continue
                rest = n[len(head):]
                idx = rest.find(tail)
                if idx > 0 and "/" not in rest[:idx]:
                    return head + rest[:idx] + tail
        return None

    def _pick_lib(self, names) -> Optional[str]:
        for suffix in self.il2cpp_lib_suffixes:
            for n in names:
                if n.endswith(suffix):
                    return n
        return None

    # -- the work ------------------------------------------------------------------------
    def _content_key(self, wanted) -> str:
        """Identifies the CONTENT of what would be unpacked: entry names, sizes and CRC-32s
        (all stored in the zip's central directory — reading them costs milliseconds and no
        decompression). Unlike path/size/mtime this changes whenever the APK's Unity data does,
        even if the file keeps its name, size and timestamp — so a cached unpack can never be
        served for a newer APK — and the same APK found under two paths shares one unpack."""
        digest = hashlib.sha1()
        for info in sorted(wanted, key=lambda i: i.filename):
            digest.update(f"{info.filename}|{info.file_size}|{info.CRC}\n".encode("utf-8", "replace"))
        return digest.hexdigest()[:20]

    def prepare(self, path: str, progress_cb: ProgressCallback = None,
                should_cancel: CancelCheck = None) -> PreparedSource:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            prefix = self._split_prefix(names)
            if prefix is None:
                raise ValueError(tr("В файле нет данных Unity."))
            data_entries = [i for i in infos if i.filename.startswith(prefix) and not i.is_dir()]
            lib_name = self._pick_lib(names)
            wanted = list(data_entries) + ([z.getinfo(lib_name)] if lib_name else [])
            root = cache_base(self.name) / self._content_key(wanted)
            marker = root / _MARKER

            reused = _read_marker(marker)
            if reused is not None:
                try:
                    os.utime(marker)  # "last used": what pruning orders by
                except OSError:
                    pass
                _remember_origin(marker, reused, path)
                result = self._result_from_marker(root, reused, path, reused=True)
                self._drop_superseded(path, keep=root)
                return result

            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            total = sum(i.file_size for i in wanted) or 1
            done = 0
            for info in wanted:
                if should_cancel is not None and should_cancel():
                    shutil.rmtree(root, ignore_errors=True)
                    raise InterruptedError("cancelled")
                target = _safe_target(root, info.filename)
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                done += info.file_size
                if progress_cb is not None:
                    progress_cb(done, total, info.filename)

        data_dir = root / prefix.rstrip("/")
        metadata = data_dir / self.metadata_relpath
        lib = root / lib_name if lib_name else None
        info = {
            "data_dir": os.path.relpath(data_dir, root),
            "il2cpp_binary": os.path.relpath(lib, root) if lib is not None and lib.is_file() else "",
            "il2cpp_metadata": os.path.relpath(metadata, root) if metadata.is_file() else "",
            "origin": os.path.abspath(path),
            "created": time.time(),
            "size_bytes": _dir_size(root),
        }
        marker.write_text(json.dumps(info), encoding="utf-8")
        self._drop_superseded(path, keep=root)
        prune_cache(keep=[root])
        return self._result_from_marker(root, info, path, reused=False)

    def _result_from_marker(self, root: Path, info: dict, origin: str, reused: bool) -> PreparedSource:
        def abs_of(rel: str) -> str:
            return str(root / rel) if rel else ""
        # A Mono build ships its script DLLs in the data folder's Managed (an IL2CPP one only Metadata there):
        # without it every MonoBehaviour of such a package failed to read (artificer 0.7.4.apk: 960 of 981).
        # Looked up here, not stored in the marker, so packages unpacked before this change get it too.
        managed = Path(abs_of(info["data_dir"])) / "Managed"
        has_dlls = managed.is_dir() and any(managed.glob("*.dll"))
        return PreparedSource(
            label=self.label, origin=origin, data_dir=abs_of(info["data_dir"]),
            managed_dir=str(managed) if has_dlls else "",
            il2cpp_binary=abs_of(info.get("il2cpp_binary", "")),
            il2cpp_metadata=abs_of(info.get("il2cpp_metadata", "")),
            read_only_reason=self.read_only_reason, reused=reused,
        )

    def _drop_superseded(self, path: str, keep: Path) -> None:
        """Older unpacks of the SAME file path (an APK replaced by a newer build) are of no
        further use: remove them so a changed APK never leaves its previous version behind."""
        base = cache_base(self.name)
        origin = os.path.abspath(path)
        if not base.is_dir():
            return
        for child in base.iterdir():
            if child == keep or not child.is_dir():
                continue
            info = _read_marker(child / _MARKER)
            if info is not None and info.get("origin") == origin:
                shutil.rmtree(child, ignore_errors=True)


# --------------------------------------------------------------------------------------
# cache housekeeping — the unpacked data is a cache, never the only copy of anything
# --------------------------------------------------------------------------------------

_MARKER = ".complete"
DEFAULT_CACHE_LIMIT_BYTES = 4 * 1024 ** 3     # oldest-used unpacks go first beyond this
DEFAULT_CACHE_MAX_AGE_DAYS = 30               # unused for this long -> removed


def cache_base(kind: str) -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "UStudio" / f"{kind}_cache"


def _read_marker(marker: Path) -> Optional[dict]:
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
        return info if "data_dir" in info else None
    except (OSError, ValueError):
        return None


def _remember_origin(marker: Path, info: dict, path: str) -> None:
    """Records the latest file path that used this unpack (drives _drop_superseded)."""
    origin = os.path.abspath(path)
    if info.get("origin") != origin:
        info["origin"] = origin
        try:
            marker.write_text(json.dumps(info), encoding="utf-8")  # also refreshes "last used"
        except OSError:
            pass


def _dir_size(root: Path) -> int:
    total = 0
    for dirpath, _dirs, filenames in os.walk(root):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


@dataclass
class CacheEntry:
    path: Path
    size: int
    last_used: float
    origin: str


def list_cache() -> List[CacheEntry]:
    """Every complete unpack of every registered adapter, oldest-used first."""
    entries: List[CacheEntry] = []
    for kind in {getattr(a, "name", "") for a in _ADAPTERS}:
        base = cache_base(kind)
        if not base.is_dir():
            continue
        for child in base.iterdir():
            marker = child / _MARKER
            info = _read_marker(marker)
            if info is None:
                # an interrupted unpack (no marker) is garbage too — count it, oldest
                entries.append(CacheEntry(child, _dir_size(child), 0.0, ""))
                continue
            try:
                used = marker.stat().st_mtime
            except OSError:
                used = 0.0
            entries.append(CacheEntry(child, info.get("size_bytes") or _dir_size(child), used, info.get("origin", "")))
    return sorted(entries, key=lambda e: e.last_used)


def cache_size() -> int:
    return sum(e.size for e in list_cache())


def prune_cache(keep=(), max_bytes: int = DEFAULT_CACHE_LIMIT_BYTES,
                max_age_days: float = DEFAULT_CACHE_MAX_AGE_DAYS) -> int:
    """Removes unpacks unused for `max_age_days`, then the least recently used ones until the
    total fits `max_bytes`. Never touches a folder in `keep` (the data just loaded), and skips
    anything that cannot be deleted right now (a file still open elsewhere). Returns bytes freed."""
    keep_set = {Path(k).resolve() for k in keep}
    freed = 0
    entries = list_cache()
    total = sum(e.size for e in entries)
    now = time.time()
    for entry in entries:  # oldest-used first
        if entry.path.resolve() in keep_set:
            continue
        too_old = entry.last_used and (now - entry.last_used) > max_age_days * 86400
        if not (too_old or entry.last_used == 0.0 or total > max_bytes):
            continue
        shutil.rmtree(entry.path, ignore_errors=True)
        if not entry.path.exists():
            freed += entry.size
            total -= entry.size
    return freed


def clear_cache(keep=()) -> int:
    """Removes every unpack (except folders in `keep`); returns bytes freed."""
    return prune_cache(keep=keep, max_bytes=0, max_age_days=0)


class AndroidApkAdapter(ZipContainerAdapter):
    name = "android"
    label = "Android APK"
    suffixes = (".apk", ".obb")
    data_prefixes = ("assets/bin/Data/",)
    # 64-bit ARM first: the TypeTreeGenerator's IL2CPP reader handles it; armeabi-v7a needs a
    # native disassembler DLL that is not shipped (verified: "Unable to load DLL 'capstone'").
    il2cpp_lib_suffixes = ("lib/arm64-v8a/libil2cpp.so", "lib/x86_64/libil2cpp.so",
                           "lib/armeabi-v7a/libil2cpp.so", "lib/x86/libil2cpp.so")
    read_only_reason = (N_("Данные загружены из APK: перезаписать сам APK нельзя (после изменения его нужно "
                        "заново собрать и подписать). Сохраните изменения в другое место."))


register_adapter(AndroidApkAdapter())
