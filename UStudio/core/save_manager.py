"""PyQt-free logic behind the File menu's "Save files" actions.

An object is "modified" exactly the way object_table.ObjectTableModel._is_modified
already defines it: obj_ref.data is not None (set by ObjectReader.patch()/
save_typetree()/set_raw_data() — UnityPy's own in-place-edit mechanism, which also
calls assets_file.mark_changed() to flag every File on the way up to the root, see
UnityPy/files/File.py — confirmed to actually reach the true root, not just the
immediate parent). Saving only ever happens at the root container's granularity —
SerializedFile (standalone/loose), BundleFile ("data.unity3d" and friends), or
WebFile — since that's the actual on-disk unit UnityPy knows how to (re)write; a
"modified object" is really "a pending edit inside one of its parent container's
objects".

Two save flows, two shapes:
  - save_to_custom_path(): single-phase, per-file save-then-write — the
    destination is a NEW path, so it never conflicts with anything this process
    already has open.
  - prepare_overwrite() / commit_overwrite(): a deliberate two-phase split for
    overwriting the ORIGINAL loaded files in place — see prepare_overwrite's
    docstring for why a single-phase save-then-write (like the custom-path flow
    above) can't work here at all.

Kept import-light (only reaches into UnityPy) so its pieces stay usable from a
gui_workers.BackgroundWorker fn: report_progress(phase, current, total) is exactly
that class's callback contract.
"""

from core.i18n import tr
import gc
import logging
import mmap
import os
import shutil
import time
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Tuple

from UnityPy.files.BundleFile import BundleFile, FlaggedBytesSource
from UnityPy.files.File import File
from UnityPy.files.WebFile import WebFile

from core import addressables_crc
from core.backup import BackupError, create_backup, game_info_for
from core.gc_freeze import collect_everything
from core.models import RowItem
from core.options import LoadMode
from core.progress import OperationCancelled

logger = logging.getLogger("ustudio.core.save_manager")


class SaveError(Exception):
    """str(e) is already a complete, user-facing message — either raised here or
    propagated from UnityPy's own .save() (e.g. SerializedFile.save() raising
    RuntimeError for a file that was loaded with a type filter, see its own
    docstring), so callers can log it as-is."""


def _root_file(assets_file):
    """Walks File.parent up to the true root — the SerializedFile/BundleFile/
    WebFile actually backed by a file on disk. A loose/standalone
    SerializedFile is its own root.

    Real bug caught by the user's own testing (not by this module's earlier
    synthetic tests, which is exactly why — their mocks didn't reproduce this):
    a top-level file's own .parent is NOT None — Environment.load_file() calls
    parse_file(reader, self, ...), i.e. `self` being the Environment instance
    itself, so File.__init__ sets .parent to the Environment, not None. The
    original `while root.parent is not None` walk therefore didn't stop at the
    real root — it took one extra step onto the Environment object (which has
    no _cache_id/name of its own), which is exactly why original_path() came
    back None and the file's display name fell back to "?". Checking
    isinstance(..., File) instead mirrors File.mark_changed()'s own identical
    check for the identical reason — an Environment is deliberately not a File
    subclass, so this stops in exactly the right place.

    _cab_browser_standalone_root (set by core/cab_archive.py's
    parse_entry_fully()) short-circuits the walk entirely: a SerializedFile
    loaded via the CAB Archives Viewer has its .parent set to the containing
    BundleFile purely so PPtr.deref() can resolve cross-file references within
    the archive (see parse_entry_fully's own docstring) — walking past it here
    would make ANY edit to a CAB-browser-loaded entry save the entire original
    archive, not just the one entry the user actually asked to load. A normal
    Load files/Load folder session never sets this flag, so its own
    BundleFile/SerializedFile root resolution is completely unaffected."""
    if getattr(assets_file, "_cab_browser_standalone_root", False):
        return assets_file
    root = assets_file
    while isinstance(getattr(root, "parent", None), File):
        root = root.parent
    return root


def find_modified_roots(rows: List[RowItem]) -> List[Tuple[object, List[RowItem]]]:
    """Groups every row with a pending edit by its root container file. Returns
    (root_file, rows_belonging_to_it) pairs, in first-seen order. Deliberately
    driven by the table's own rows (not by walking Environment.files/is_changed
    directly) — every edit in this app happens through a row's context menu, so
    this also works uniformly for objects loaded from the main env AND objects
    loaded via CabBrowserDialog into the same table (a separate Environment,
    never registered in main_window.env.files at all)."""
    roots: dict = {}
    order: list = []
    for item in rows:
        obj = item.get("obj_ref")
        if obj is None or obj.data is None:
            continue
        assets_file = obj.assets_file
        if assets_file is None:
            continue
        root = _root_file(assets_file)
        key = id(root)
        if key not in roots:
            roots[key] = (root, [])
            order.append(key)
        roots[key][1].append(item)
    return [roots[k] for k in order]


def _pending_loose_resources(environment) -> List[Tuple[str, str, Path]]:
    """(custom_name, intended_absolute_destination_path, temp_source_path) for
    every loose custom resource Content Raw import created this session but
    hasn't written to its real destination yet — see
    core.object_preview.import_object_content_raw's own comment on
    environment._pending_loose_resource_temp_files for why the accumulated
    bytes live in a scratch temp file (registered in environment.cabs like
    any other resource for correct in-session reads) instead of either
    touching the real destination immediately or being held as one big
    Python bytes object.

    temp_source_path points at that scratch file — callers copy it
    (shutil.copyfile, via this module's own _copy_file()) rather than reading
    it into memory themselves, so a large audio/video custom resource never
    has to be materialized whole in this process's RAM just to get saved.
    Real reported concern: the whole point of a custom resource is to hold
    potentially large media content the ORIGINAL resource file would
    otherwise have to carry — an in-memory-bytes design for it would trade
    the disk bloat this feature exists to avoid for RAM bloat instead,
    growing with every import made before the next save.

    Real reported bug this exists to fix: a resource file has no OBJECTS of
    its own, so find_modified_roots() — driven entirely by which TABLE ROWS
    have a pending obj.data edit — has no way to see it at all; only the
    OBJECTS that reference it (an AudioClip/VideoClip row) show up as
    modified, and their own root is the .assets file that row lives in, not
    the resource it points to. Both save_to_custom_path() and
    prepare_overwrite() call this once per save (not per group/root — a
    pending resource isn't owned by any one root) to pick these up
    separately.

    Returns [] for an Environment that never set the attributes (every
    ordinary load, and any session where resource_target_mode was never
    switched to "custom_resource") — getattr's default handles that without
    every caller needing its own hasattr check."""
    pending = getattr(environment, "_pending_loose_resources", None)
    temp_files = getattr(environment, "_pending_loose_resource_temp_files", None)
    if not pending or not temp_files:
        return []
    result = []
    for name, target_path in pending.items():
        temp_path = temp_files.get(name)
        if temp_path is None or not os.path.isfile(temp_path):
            continue
        result.append((name, target_path, Path(temp_path)))
    return result


def original_path(root_file) -> Optional[str]:
    """The full original path the file was loaded from. File.name is only ever a
    basename (see UnityPy/files/File.py's __init__: name = basename(name)) — the
    full path only survives in _cache_id, which __init__ sets from the same
    `name` argument BEFORE it's truncated. This is the same field
    GlobalBlockCache relies on as bundle_id for the identical reason (see
    CLAUDE.md's "bundle_id collision" note) — relying on it here follows that
    same established precedent. Returns None when the file was never given a
    real name (the f"id:{id(self):x}" synthetic fallback)."""
    cache_id = getattr(root_file, "_cache_id", None)
    if not isinstance(cache_id, str) or cache_id.startswith("id:"):
        return None
    return cache_id


def _save_bytes(root_file, group_rows: List[RowItem]) -> bytes:
    """packer choice per container type — see BundleFile.save()/WebFile.save()'s
    own docstrings: BundleFile defaults to uncompressed ("none") unless told
    "original", while WebFile's default packer="none" argument is itself literal
    (only a falsy value falls back to self.packer) — passing None is what
    actually preserves its detected original compression. SerializedFile has no
    compression of its own (that's the container's job), so it takes no packer
    argument at all.

    group_rows is only used for the BundleFile case — see
    _save_bundle_bytes()'s own docstring for why a bundle specifically can
    skip re-serializing its OWN untouched internal entries, and why a bare
    SerializedFile/WebFile root can't."""
    if isinstance(root_file, BundleFile):
        return _save_bundle_bytes(root_file, group_rows)
    if isinstance(root_file, WebFile):
        return root_file.save(packer=None)
    return root_file.save()


def _save_bundle_bytes(bundle: BundleFile, group_rows: List[RowItem]) -> bytes:
    """Real reported request: "the program re-checks all files during
    packaging, whereas ideally it should only replace the specific one that
    changed." Confirmed real — BundleFile.save()'s own save_fs() iterates
    EVERY internal entry and, for anything without a cheap `.bytes` shortcut,
    calls `.save()` on it — a full TypeTree re-serialization — even for an
    entry nobody touched. core/cab_archive.py's own rebuild path already
    avoids this (via FlaggedBytesSource, wrapping an untouched entry's raw
    byte range instead of re-parsing/re-writing it) but that optimization had
    never been carried over to this module's main "Save Game Files"/"Save As"
    flow, which just called bundle.save() directly.

    Fix: group_rows (this root's own modified rows, from find_modified_roots)
    tells us exactly which of the bundle's internal SerializedFile entries
    actually have a pending edit (via each row's own obj_ref.assets_file —
    identity-compared; File has no custom __eq__/__hash__, so this is safe,
    unlike the documented ObjectReader-is-unhashable case elsewhere in this
    project). Every OTHER internal entry — untouched SerializedFiles and any
    raw resource (.resS/.resource) entry, which can never appear in
    group_rows at all since only a SerializedFile is ever an obj_ref's own
    assets_file — gets wrapped in FlaggedBytesSource over its own `.reader`
    (the same technique core/cab_archive.py's rebuild_and_save already
    trusts), so save_fs() takes the cheap `.bytes` passthrough for it
    instead of re-running .save() on data that never changed.

    What this does NOT fix, and why: even with every untouched entry taking
    the cheap path, save_fs() still concatenates ALL entries (touched and
    passed-through alike) into one flat buffer and recompresses the WHOLE
    thing from scratch (chunk_based_compress()'s own chunking is a fixed
    128KB byte-stride over that flat buffer, not aligned to entry
    boundaries at all) — so this cuts the wasted TypeTree re-serialization
    cost for untouched entries, not the recompression cost, which still
    scales with the bundle's total size regardless of how few objects were
    actually edited. Only true block-level incremental patching would fix
    that, and that's the same "Incremental/partial bundle patching...
    deliberately deferred" item CLAUDE.md's own Known Open Items already
    tracks — not attempted here, since it needs verified binary-format
    surgery this project's own methodology doesn't ship without a trusted
    reference to check against."""
    modified_entries = {
        item["obj_ref"].assets_file
        for item in group_rows
        if item.get("obj_ref") is not None and item["obj_ref"].assets_file is not None
    }
    return save_bundle_with_entries(bundle, modified_entries)


def save_bundle_with_entries(bundle: BundleFile, modified_entries) -> bytes:
    """Bundle bytes where only the internal entries in `modified_entries` (File objects, compared by
    identity) are re-serialized with .save(); every other entry is passed through as the raw bytes it
    was loaded from. The second half of _save_bundle_bytes(), also used by core.version_writer (which
    changes a header field of every SerializedFile and so knows the set without any table rows)."""
    original_files = bundle.files
    new_files = {}
    for name, f in original_files.items():
        if f in modified_entries:
            new_files[name] = f
        else:
            stream = getattr(f, "reader", f)
            new_files[name] = FlaggedBytesSource(stream, getattr(f, "flags", 0))
    try:
        bundle.files = new_files
        return bundle.save(packer="original")
    finally:
        bundle.files = original_files


def compute_base_dir(load_mode: LoadMode, selected_dir: str, selected_files: List[str], env=None) -> Optional[Path]:
    """The root whose OWN folder name should appear as the top level of a custom-
    path save's preserved structure (see resolve_custom_dest) — the folder the
    user picked for "Load folder", or the common parent of an explicit "Load
    files" selection. Data unpacked from a container (an Android APK, see
    core/platform_sources.py) lives in a cache folder, not next to the picked file:
    its data folder is the root then (env.source_data_dir)."""
    data_dir = getattr(env, "source_data_dir", "") if env is not None else ""
    if data_dir:
        return Path(data_dir)
    if load_mode == LoadMode.FOLDER and selected_dir:
        return Path(selected_dir)
    if selected_files:
        try:
            base = Path(os.path.commonpath(selected_files))
        except ValueError:
            # Different drives on Windows — no common path at all.
            return Path(selected_files[0]).parent
        # os.path.commonpath() of a single path (or of several identical
        # paths) returns that path UNCHANGED — i.e. a FILE, not a directory,
        # when exactly one file was explicitly selected. base_dir must always
        # be a directory: resolve_custom_dest()'s relative_to() check treats
        # it as one regardless, so a file here silently makes the loaded root
        # itself match base_dir exactly (flattened straight into dest_root's
        # own top level) while everything else that references it (e.g. a
        # Content Raw custom resource sharing its folder) fails the same
        # check and falls to the "not under base_dir" fallback instead —
        # landing one level deeper than the root file it belongs next to.
        # Real reported bug: loading a single resources.assets from
        # Truck-kun_Data and importing an AudioClip into a custom resource,
        # then "Save as..." put resources.assets at dest_root/resources.assets
        # but res_new at dest_root/Truck-kun_Data/res_new — two different
        # folders for files that must live side by side.
        if any(base == Path(f) for f in selected_files):
            return base.parent
        return base
    return None


def resolve_custom_dest(orig_path: Path, base_dir: Optional[Path], dest_root: Path) -> Path:
    """dest_root/<base_dir's own folder name>/<orig_path relative to base_dir> —
    "preserving the folder structure starting from the last folder of the loaded
    files/directory path". Falls back to dest_root/<orig_path's parent folder
    name>/<orig_path's own name> when orig_path isn't actually under base_dir
    (e.g. a file loaded standalone via the CAB browser, unrelated to whatever
    the main table's own last load was) — still gives real structure instead of
    flattening everything into one folder, without needing base_dir to apply."""
    if base_dir is not None:
        try:
            rel = orig_path.resolve().relative_to(base_dir.resolve())
            return dest_root / base_dir.name / rel
        except ValueError:
            pass
    return dest_root / orig_path.parent.name / orig_path.name


# Real reported problem: a save/overwrite could fail outright on a lock that
# was only ever TRANSIENT — most plausibly antivirus real-time-scanning the
# just-written file before releasing it, not the (much shorter-lived) case of
# Explorer's thumbnail handler or a search indexer. The files this saves are
# often tens of MB to multiple GB, and a real AV scan of a large file can
# reasonably take several seconds, sometimes longer under load or with
# cloud-lookup scanning enabled — a flat handful of sub-second retries can
# expire before a scan like that even finishes, failing exactly the case
# this exists to catch. Failing outright turned "I made a series of edits"
# into "...and they just weren't saved, with no warning until I went
# looking for them" — a real trust problem for a tool whose one job is
# faithfully persisting edits.
#
# Exponential backoff, capped, totaling ~25s worst case: cheap to be generous
# here since both call sites this wraps (_check_not_locked's probe rename,
# _write_file/_copy_file's final os.replace) already run off the GUI thread
# (OverwriteCommitThread/CustomPathSaveThread), so the window itself never
# blocks. What DID look like a freeze was the silence: the status line sat
# on one message for the whole wait and nothing said a retry was happening —
# every attempt is now logged and, for the overwrite check, shown in the
# status line (see _check_batch_not_locked). A genuinely permanent lock (the
# game still running) still fails with the same clear error as before, just
# after a more realistic wait instead of giving up almost immediately.
_LOCK_RETRY_DELAYS_SECONDS = (0.3, 0.6, 1.2, 2.5, 5.0, 5.0, 5.0, 5.0)  # 8 waits, ~24.6s total

# Attempts (1-based) after which a full garbage collection is forced before the
# next wait. Real reported failure: "Файл держат: Python (PID …, эта программа)"
# — the lock was this process's OWN memory mapping of the file. A mapping stays
# alive as long as ANY zero-copy slice of it does, and File.close_source_handle()
# only releases the file's own view (measured: with a slice still held, dispose()
# does not release the mapping). When that slice sits in a reference CYCLE that
# only became garbage after the last collection (a widget/closure/parsed object
# dropped while the GUI tore the old Environment down), refcounting can't free
# it, and Python's automatic full collections are triggered by allocation growth,
# of which an idle wait has none — so waiting alone never helps, but a collection
# does (measured the same way). Attempts 1, 2 and 4 = right away, after the GUI
# thread has had a moment to run its deferred deletions, and again ~2 s later.
_GC_ON_LOCK_ATTEMPTS = (1, 2, 4)


def _collect_garbage_for_lock(context: str) -> int:
    freed = collect_everything()
    logger.info(tr("%s: принудительная сборка мусора освободила %d объектов."), context, freed)
    return freed


def _retry_on_lock(operation: Callable[[], None], label: str = "") -> None:
    """Runs `operation` (a zero-arg callable performing one filesystem
    rename/replace), retrying with exponentially increasing delays if it
    raises OSError — see the module-level comment above for why. Re-raises
    the LAST OSError if every attempt fails, so callers see the same
    exception type/shape they always did; only the timing changes.

    Every failed attempt is logged (which file, attempt i of N, how long until
    the next one, the OS error) — before this, a lock that never cleared just
    looked like a save that hung silently for ~25 seconds and then failed,
    with nothing to say it had been retrying at all, or how many times."""
    total_attempts = len(_LOCK_RETRY_DELAYS_SECONDS) + 1
    last_error: Optional[OSError] = None
    for attempt in range(total_attempts):
        try:
            operation()
            if attempt:
                logger.info(tr("Файл%s освободился с попытки %d/%d."), f" «{label}»" if label else "", attempt + 1, total_attempts)
            return
        except OSError as e:
            last_error = e
            if attempt < len(_LOCK_RETRY_DELAYS_SECONDS):
                delay = _LOCK_RETRY_DELAYS_SECONDS[attempt]
                logger.warning(
                    tr("Файл%s занят (попытка %d/%d), повтор через %g с: %s"),
                    f" «{label}»" if label else "", attempt + 1, total_attempts, delay, e,
                )
                if attempt + 1 in _GC_ON_LOCK_ATTEMPTS:
                    _collect_garbage_for_lock(tr("Файл «{name}»", name=label) if label else tr("Файл"))
                time.sleep(delay)
    logger.error(tr("Файл%s так и остался занят после %d попыток: %s"), f" «{label}»" if label else "", total_attempts, last_error)
    raise last_error


def describe_lockers(path) -> List[str]:
    """Best-effort: who has `path` open RIGHT NOW, via the Windows Restart
    Manager (the same API installers use to say "close these programs first").
    Each entry is "<app name> (PID n[, эта программа])" — "эта программа" when
    the PID is this very process. Exists to answer the one question a "file is
    used by another process (or by this program)" error can't: WHICH — an
    antivirus scan, Explorer, the game itself, or a handle this app forgot to
    close. Never raises and returns [] anywhere it can't tell (non-Windows,
    the API refusing, a handle-less mapping) — an empty list means "unknown",
    not "nobody"."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class _UniqueProcess(ctypes.Structure):
            _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]

        class _ProcessInfo(ctypes.Structure):
            _fields_ = [
                ("Process", _UniqueProcess),
                ("strAppName", ctypes.c_wchar * 256),
                ("strServiceShortName", ctypes.c_wchar * 64),
                ("ApplicationType", ctypes.c_int),
                ("AppStatus", wintypes.ULONG),
                ("TSSessionId", wintypes.DWORD),
                ("bRestartable", wintypes.BOOL),
            ]

        rm = ctypes.WinDLL("rstrtmgr")
        session = wintypes.DWORD(0)
        session_key = ctypes.create_unicode_buffer(33)  # CCH_RM_SESSION_KEY + 1
        if rm.RmStartSession(ctypes.byref(session), 0, session_key) != 0:
            return []
        try:
            files = (wintypes.LPCWSTR * 1)(str(path))
            if rm.RmRegisterResources(session, 1, files, 0, None, 0, None) != 0:
                return []
            needed, have, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
            rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(have), None, ctypes.byref(reasons))
            if rc == 0 and needed.value == 0:
                return []
            if rc != 234:  # ERROR_MORE_DATA is the expected answer to the size probe
                return []
            infos = (_ProcessInfo * needed.value)()
            have = wintypes.UINT(needed.value)
            if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(have), infos, ctypes.byref(reasons)) != 0:
                return []
            result = []
            for info in infos[:have.value]:
                pid = info.Process.dwProcessId
                mine = ", " + tr("эта программа") if pid == os.getpid() else ""
                result.append(f"{info.strAppName or '?'} (PID {pid}{mine})")
            return result
        finally:
            rm.RmEndSession(session)
    except Exception:  # noqa: BLE001 - diagnostics must never break a save
        return []


def describe_mapping_holders(path, max_views: int = 3, time_budget: float = 8.0) -> List[str]:
    """For a file that THIS process still has memory-mapped: which Python objects
    keep the mapping alive. A mapping outlives File.close_source_handle() for as
    long as any zero-copy slice of it (a memoryview) exists, and the file stays
    locked with it — so the useful question after "held by this program" is what
    holds that slice. Scans the GC-tracked heap for memoryviews over an open mmap
    of exactly this file's size and walks a few referrers up from each, e.g.
    "memoryview 9.3 МБ ← Texture2D ← dict ← ObjectStructureTree". Slow on a huge
    heap (every referrer lookup is a full scan), hence the time budget — meant
    to run once, when a save is about to fail anyway. Never raises; [] means
    nothing found (or out of time)."""
    try:
        size = os.path.getsize(path)
        deadline = time.monotonic() + time_budget
        views = []
        for o in gc.get_objects():
            if type(o) is memoryview:
                try:
                    base = o.obj
                    if isinstance(base, mmap.mmap) and len(base) == size:
                        views.append(o)
                except (ValueError, TypeError):
                    continue  # a released view / closed mapping
        result = []
        for mv in views[:max_views]:
            chain = [tr("memoryview {nbytes} Б", nbytes=mv.nbytes)]
            node = mv
            for _ in range(3):
                if time.monotonic() > deadline:
                    break
                referrers = [r for r in gc.get_referrers(node) if r is not views and type(r).__name__ != "frame"]
                if not referrers:
                    break
                # "cell" by substring: a Nuitka build's closure cells are `compiled_cell` and said nothing
                # (a real report listed "memoryview 16 Б ← compiled_cell ← compiled_cell ← compiled_cell").
                node = next((r for r in referrers
                             if type(r).__name__ not in ("dict", "list", "tuple") and "cell" not in type(r).__name__),
                            referrers[0])
                if isinstance(node, dict):
                    owner = next((x for x in gc.get_referrers(node) if getattr(x, "__dict__", None) is node), None)
                    node = owner if owner is not None else node
                name = type(node).__name__
                qualname = getattr(node, "__qualname__", None)    # a function / method that keeps it alive
                chain.append(f"{name} {qualname}" if isinstance(qualname, str) and "function" in name.lower() else name)
            result.append(" ← ".join(chain))
        return result
    except Exception:  # noqa: BLE001 - diagnostics must never break a save
        return []


def release_environment(env) -> int:
    """Closes the OS-level handle/mapping of EVERY file and resource reader a
    loaded Environment holds — not just the files being overwritten. Call it when
    the Environment is being discarded (an overwrite save's teardown, a fresh
    load replacing it); nothing may read through it afterwards. Returns how many
    were released. Best effort: a reader something is still mid-read on simply
    refuses and is skipped.

    Real reported failure, and why prepare_overwrite()'s per-root close isn't
    enough: after a first overwrite (which modified, say, resources.assets) and the
    reload it triggers, the user modified a DIFFERENT file — sharedassets0.assets —
    and the second overwrite hit "file held by this program". The log's own
    diagnostic named the holder: "memoryview 21255056 B ← EndianBinaryReader_
    Memoryview ← ObjectReader ← cell", a full-file mapping of sharedassets0.assets
    from the FIRST load. Only resources.assets' handle had been closed then; every
    other file of that Environment stayed mapped until its Python objects died, and
    here a closure still referenced one of its ObjectReaders (dropping references
    is not something the app can guarantee — dialogs, task closures and models all
    keep some). The unmodified file only became a problem once it was the one being
    overwritten. Releasing the handles explicitly makes the outcome independent of
    what still references the old objects."""
    released = 0
    seen = set()

    def _release(obj) -> None:
        nonlocal released
        if obj is None or id(obj) in seen:
            return
        seen.add(id(obj))
        try:
            if hasattr(obj, "close_source_handle"):      # SerializedFile / BundleFile / WebFile
                obj.close_source_handle()
            elif hasattr(obj, "dispose"):                # a raw resource reader (.resS / .resource)
                obj.dispose()
            else:
                return
            released += 1
        except Exception:  # noqa: BLE001 - best effort, see docstring
            pass

    for container in (getattr(env, "files", None), getattr(env, "cabs", None)):
        if container:
            for f in list(container.values()):
                _release(f)
    return released


def _probe_lock(path: Path) -> Optional[OSError]:
    """One attempt at the check _check_not_locked() is built on: renaming a
    file onto its own name needs the same delete-sharing access a real replace
    does, without touching its content. None if the file is free."""
    try:
        os.rename(str(path), str(path))
        return None
    except OSError as e:
        return e


def _locked_message(path: Path, error: Optional[OSError]) -> str:
    text = (
        tr("Файл «{name}» занят другим процессом (или всё ещё используется этой программой — попробуйте "
           "перезагрузить текущие данные) и не может быть перезаписан: {error}", name=path.name, error=error)
    )
    lockers = describe_lockers(path)
    if lockers:
        text += "\n" + tr("Файл держат: {holders}.", holders=", ".join(lockers))
        if any(tr("эта программа") in holder for holder in lockers):      # the mark describe_lockers() adds
            # It's this very process — say which objects inside it (see
            # describe_mapping_holders()); that is the part that can actually be fixed.
            inside = describe_mapping_holders(path)
            if inside:
                text += "\n" + tr("Внутри программы отображение файла удерживают: {holders}.", holders="; ".join(inside))
                logger.error(tr("Держатели отображения файла «%s»: %s"), path.name, "; ".join(inside))
    return text


def _check_not_locked(path: Path, orig_path: Optional[Path] = None) -> None:
    """Best-effort pre-flight check that `path` can actually be overwritten —
    catches both a lock held by another program (the game itself running, an
    editor, an antivirus scan) and the confirmed real scenario documented in
    CLAUDE.md: a bundle this same process still has open via mmap for reading
    refuses even a same-process rename-over on Windows (OSError [Errno 22] /
    WinError 5 — the mapping keeps the file locked even after the originating
    open() context manager exits). os.rename(path, path) is the standard cheap
    way to probe this: renaming a file onto its own name still requires the
    same delete-sharing access a real replace needs, without writing any data
    or touching the file's actual content. Only applies to a mode/file
    combination where the destination already exists — a brand-new path under
    a custom destination has nothing to conflict with.

    orig_path, when given, is the file's own currently-loaded source path —
    real reported confusion: "Save Game Files As..." into the SAME folder the
    files are currently loaded from resolves out_path to that exact source
    file, which is ALWAYS still locked (this process itself has it open) — the
    generic "occupied by another process" wording below reads like a random
    program bug in that specific, entirely expected case, instead of telling
    the user the one thing that actually fixes it: pick a different folder."""
    if not path.exists():
        return
    if orig_path is not None:
        try:
            same_file = path.resolve() == Path(orig_path).resolve()
        except OSError:
            same_file = False
        if same_file:
            raise SaveError(
                tr("Нельзя сохранить «{name}» в ту же папку, откуда файлы игры были загружены. Выберите другую "
                   "папку. Чтобы изменить исходные файлы, сохраняйте с заменой, а не в новое место.", name=path.name)
            )
    try:
        _retry_on_lock(lambda: os.rename(str(path), str(path)), label=path.name)
    except OSError as e:
        raise SaveError(_locked_message(path, e)) from e


def _write_file(out_path: Path, data: bytes) -> None:
    """Write-then-replace instead of a direct open(out_path, "wb") — an error
    partway through (disk full, permissions) leaves the ORIGINAL file untouched
    instead of a truncated/corrupt one in its place."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".ustudio_tmp")
    with open(tmp_path, "wb") as f:
        f.write(data)
    _retry_on_lock(lambda: os.replace(tmp_path, out_path), label=out_path.name)


def _copy_file(out_path: Path, source_path: Path) -> None:
    """Same write-then-replace safety as _write_file(), but streams from an
    existing source file (shutil.copyfile) instead of writing an in-memory
    bytes object — used for pending loose custom resources, which are kept
    spooled to a scratch temp file rather than materialized as one big bytes
    object in this process's RAM (see _pending_loose_resources()'s own
    docstring for why)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".ustudio_tmp")
    shutil.copyfile(str(source_path), str(tmp_path))
    _retry_on_lock(lambda: os.replace(tmp_path, out_path), label=out_path.name)


def _addressables_catalog_updates(
    saved: dict, report_progress: Callable[[str, int, int], None], total: int,
) -> List[addressables_crc.CatalogUpdate]:
    """Catalogs of an Addressables game whose bundle CRCs must follow the bundles being written (see
    core/addressables_crc.py: with a stale CRC the game refuses the changed bundle). Empty for every other game.
    A catalog that cannot be read is logged and left as it is — never a reason to stop the save."""
    if not any(addressables_crc.find_aa_root(path) for path in saved):
        return []
    report_progress(tr("Каталог Addressables..."), total, total)
    updates, problems = addressables_crc.catalog_updates(saved)
    for problem in problems:
        logger.warning(problem)
    for update in updates:
        logger.info(addressables_crc.describe(update))
    return updates


def save_to_custom_path(
    groups: List[Tuple[object, List[RowItem]]],
    dest_root: Path,
    base_dir: Optional[Path],
    report_progress: Callable[[str, int, int], None],
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[int, List[RowItem]]:
    """"Save files (custom path)" — writes every (root_file, rows) group from
    find_modified_roots() to a NEW destination, so none of it conflicts with
    whatever this process still has open/mmap'd (unlike overwrite — see
    prepare_overwrite/commit_overwrite below for why THAT mode needs a very
    different two-phase approach). Stops at the first failure and raises
    SaveError — see MainWindow.on_menu_save_files's docstring for why a
    partially-completed save silently reported as "done" is worse than an
    explicit, immediate stop. Files already written before the failure keep
    their changes cleared (they really were saved correctly).

    should_cancel, if given, is polled BETWEEN files only — the only safe
    checkpoint, since one container's own .save() call is a single monolithic
    UnityPy call with no internal checkpoints of its own (the same limitation
    CLAUDE.md documents for BundleFile.save()/the CAB browser's in-memory
    rebuild path).

    Deliberately does NOT clear obj_ref.data/is_changed on success, unlike
    the overwrite flow — real reported bug: it originally did, matching
    "Save As" semantics, but that made the Изменено asterisk (and
    find_modified_roots' own "what needs saving" scan) go quiet the instant a
    custom-path export happened even though the game's OWN files were never
    touched. A user who then deleted the exported copy and tried to save
    again hit a misleading "nothing to save" — there was still a real,
    un-applied edit sitting in memory, this just could no longer see it. Only
    "overwrite" (which writes to the actual loaded game files) is treated as
    the edit having been applied; a custom-path save is more like a
    repeatable export/preview of a still-pending edit.

    Returns (files_saved, rows_touched) — rows_touched is every row across
    every successfully-saved group, for the caller's own bookkeeping (e.g.
    logging); it no longer implies anything about the Изменено column."""
    if not groups:
        raise SaveError(tr("Нет изменённых объектов для сохранения."))

    total = len(groups)
    saved_rows: List[RowItem] = []
    saved_bundles: dict = {}  # original path -> new bytes, for the Addressables catalog check below

    for i, (root_file, group_rows) in enumerate(groups, start=1):
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        orig = original_path(root_file)
        display_name = Path(orig).name if orig else (getattr(root_file, "name", "") or "?")
        report_progress(tr("Сохранение... {i}/{total}: {display_name}", i=i, total=total, display_name=display_name), i - 1, total)

        base = Path(orig) if orig else Path(display_name)
        out_path = resolve_custom_dest(base, base_dir, dest_root)

        # Checked BEFORE the (potentially slow) .save() serialization below, not
        # just at the final write — a locked destination should fail fast, not
        # after doing all that work for nothing. Only actually matters when
        # re-saving over a destination from an earlier custom-path save, OR
        # when the chosen custom destination happens to land back on the
        # currently-loaded source file itself (see _check_not_locked's own
        # orig_path handling for that specific, clearer-worded case).
        #
        # is_absolute() guard: `orig` is a real filesystem path for a normal
        # Load files/Load folder root, but for a CAB-browser-loaded entry
        # (root_file._cab_browser_standalone_root — see _root_file()) it's just
        # that entry's own bare internal name (e.g. "level65", never a real
        # path on disk at all — it was never opened as its own OS file handle
        # in the first place, so there's no "same locked source file" concept
        # to check here). Passing it through anyway would resolve() it against
        # the CWD and compare against that instead — meaningless, not just
        # unnecessary.
        orig_path_obj = Path(orig) if orig and Path(orig).is_absolute() else None
        _check_not_locked(out_path, orig_path=orig_path_obj)

        try:
            data = _save_bytes(root_file, group_rows)
            _write_file(out_path, data)
        except Exception as e:
            raise SaveError(tr("Ошибка сохранения «{display_name}»: {error}", display_name=display_name, error=e)) from e

        if orig_path_obj is not None:
            saved_bundles[orig_path_obj] = data
        saved_rows.extend(group_rows)

    # The game's own Addressables catalog, with the new CRCs, goes next to the copies (where the game expects it
    # relative to the bundles) — copying the bundles into the game without it would get them refused.
    for update in _addressables_catalog_updates(saved_bundles, report_progress, total):
        dest = resolve_custom_dest(update.catalog_path, base_dir, dest_root)
        _check_not_locked(dest)
        try:
            _write_file(dest, update.data)
        except Exception as e:
            raise SaveError(tr("Ошибка сохранения каталога «{name}»: {error}", name=update.catalog_path.name, error=e)) from e
    saved_bundles.clear()

    # Loose custom resources (Content Raw's "отдельный ресурс" target mode)
    # aren't owned by any one group above — see _pending_loose_resources()'s
    # own docstring for why find_modified_roots() can't see them on its own.
    # One pass over the whole batch, not per-group, since the same pending
    # resource could in principle be referenced by rows in more than one
    # group (multiple .assets files whose own AudioClips all got redirected
    # to the same custom name).
    for name, target_path, temp_source_path in _pending_loose_resources(groups[0][0].environment):
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        dest = resolve_custom_dest(Path(target_path), base_dir, dest_root)
        _check_not_locked(dest)
        try:
            _copy_file(dest, temp_source_path)
        except Exception as e:
            raise SaveError(tr("Ошибка сохранения отдельного ресурса «{name}»: {error}", name=name, error=e)) from e

    report_progress(tr("Сохранение... {total}/{total}: Готово", total=total), total, total)
    return total, saved_rows


class PreparedOverwrite(NamedTuple):
    display_name: str
    out_path: Path
    data: Optional[bytes] = None
    source_path: Optional[Path] = None
    # Exactly one of data/source_path is set. A root file's fully-serialized
    # bytes (from _save_bytes()) always goes through `data` — that content
    # only exists in memory in the first place, there's no file to copy from.
    # A pending loose custom resource (see _pending_loose_resources()) goes
    # through `source_path` instead, pointing at its scratch temp file —
    # commit_overwrite() streams a copy from it rather than reading the whole
    # thing into a `data` bytes object, which is the actual point: a large
    # audio/video custom resource never gets fully materialized in this
    # process's RAM just to reach commit_overwrite().
    #
    # Deliberately NOT carrying the group's RowItems/root_file here (unlike
    # save_to_custom_path's return value) — this tuple is handed to
    # commit_overwrite() only AFTER the caller has dropped every reference to
    # the source Environment (see prepare_overwrite's docstring). Keeping a
    # RowItem alive would keep its obj_ref -> assets_file -> ... -> mmap chain
    # alive right through that teardown, defeating the entire point of it.


def prepare_overwrite(
    groups: List[Tuple[object, List[RowItem]]],
    report_progress: Callable[[str, int, int], None],
    should_cancel: Optional[Callable[[], bool]] = None,
) -> List[PreparedOverwrite]:
    """Phase 1 of "Save files (overwrite)": resolves each group's original path,
    serializes its bytes via .save(), then closes that specific file's own
    underlying OS handle/mmap (root_file.close_source_handle() — see
    UnityPy/files/File.py's docstring for the actual release mechanism) now
    that nothing will read from it again. This is the actual fix for
    overwrite failing while this app still has the file open: Windows only
    cares whether the real OS handle is still open, not how many Python
    objects still technically reference the (now inert) wrapper around it —
    closing the specific handle this file's own reader opened is a bounded
    operation, unlike hunting down and dropping every Python reference that
    might exist somewhere in a large GUI app (a queued signal argument, a
    dialog's own cache, a stray closure — an earlier version of this feature
    tried exactly that, repeatedly found a new specific holder each round,
    and was abandoned for this approach instead once the pattern became
    clear).

    Nothing is written to disk here and no destination lock is checked yet —
    that's commit_overwrite's job, once every file in the batch has been
    prepared. Still split into two phases (matching save_to_custom_path's
    single-phase shape) because MainWindow also tears the whole loaded
    Environment down and reloads it fresh between prepare and commit — no
    longer load-bearing for the lock itself now that each handle is closed
    explicitly, but kept anyway: the Environment's own Python objects
    (SerializedFile/ObjectReader wrappers) are permanently unusable once
    their reader is disposed, so the table needs refreshing regardless of
    what actually released the OS-level lock.

    should_cancel is polled BETWEEN files, same as save_to_custom_path — safe
    here since nothing has touched disk yet, so a cancellation at this stage
    is a clean no-op for the caller (a handle already closed for an earlier
    file in the same batch doesn't need undoing — that file's Environment
    wrapper is about to be discarded via the reload either way)."""
    if not groups:
        raise SaveError(tr("Нет изменённых объектов для сохранения."))

    total = len(groups)
    prepared: List[PreparedOverwrite] = []

    for i, (root_file, group_rows) in enumerate(groups, start=1):
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        orig = original_path(root_file)
        display_name = Path(orig).name if orig else (getattr(root_file, "name", "") or "?")
        report_progress(tr("Подготовка... {i}/{total}: {display_name}", i=i, total=total, display_name=display_name), i - 1, total)

        if not orig:
            raise SaveError(
                tr("Не удалось определить исходный путь файла «{display_name}» для перезаписи.", display_name=display_name)
            )

        try:
            data = _save_bytes(root_file, group_rows)
        except Exception as e:
            raise SaveError(tr("Ошибка сохранения «{display_name}»: {error}", display_name=display_name, error=e)) from e

        # The actual fix for "overwrite fails while this app still has the
        # file open": close the underlying OS handle/mmap THIS SPECIFIC file
        # was read from, now that its data is fully extracted into `data`
        # above and nothing will read from root_file again. This is a
        # bounded operation (the one handle this file's own reader opened),
        # unlike hunting down and dropping every Python reference that might
        # still exist somewhere in the app (a QDialog, a queued signal, a
        # stray closure, ...) — Windows only cares whether the underlying
        # handle is still open, not how many Python objects still technically
        # point at the (now inert) wrapper around it. See
        # File.close_source_handle()'s docstring (and its SerializedFile/
        # BundleFile overrides) for the actual release mechanism.
        try:
            root_file.close_source_handle()
        except Exception:
            # Best-effort — a failure here shouldn't block the save outright:
            # commit_overwrite's own _check_not_locked still catches a file
            # that's genuinely still locked, just without this shortcut.
            pass

        prepared.append(PreparedOverwrite(display_name, Path(orig), data))

    # An Addressables game's catalog, with the CRCs of the rewritten bundles, is one more file of the batch: it
    # gets the same lock check, backup and write-then-replace as the bundles (see core/addressables_crc.py).
    saved = {item.out_path: item.data for item in prepared if item.data is not None}
    for update in _addressables_catalog_updates(saved, report_progress, total):
        prepared.append(PreparedOverwrite(update.catalog_path.name, update.catalog_path, update.data))

    # Loose custom resources (Content Raw's "отдельный ресурс" target mode)
    # aren't owned by any one group above and never went through
    # close_source_handle() (there's no real OS handle backing them — they
    # live in a scratch temp file, not one of the game's own loaded files).
    # See _pending_loose_resources()'s own docstring. Appended as
    # PreparedOverwrite entries with `source_path` set (not `data`):
    # commit_overwrite() streams a copy from the temp file instead of this
    # function reading it into memory first — a Path string is exactly as
    # safe to carry across the environment teardown as the `data` bytes
    # every other entry already survives it as (see this NamedTuple's own
    # docstring on why it holds no live object/row references), and it
    # avoids materializing a potentially large audio/video resource in RAM
    # a second time on top of whatever save_to_custom_path() already avoided.
    for name, target_path, temp_source_path in _pending_loose_resources(groups[0][0].environment):
        prepared.append(PreparedOverwrite(name, Path(target_path), source_path=temp_source_path))

    report_progress(tr("Подготовка... {total}/{total}: Готово", total=total), total, total)
    return prepared


def _check_batch_not_locked(
    prepared: List[PreparedOverwrite],
    report_progress: Callable[[str, int, int], None],
) -> None:
    """commit_overwrite()'s "Проверка" pass: every destination must be free
    before ANY is written. Retries are SHARED across the batch — all files
    still locked are re-probed together after each wait — instead of each
    locked file running its own full retry schedule one after another. With the
    old per-file loop, N stuck files meant N x ~25 s of silence (five files: two
    minutes) before the error, the status line frozen on the same "Проверка..."
    text the whole time — which is what a lock that never clears looked like
    from the outside: the save "hangs at Validation". Now the total wait is one
    schedule (~25 s) however many files are stuck, and every wait says which
    files are still busy and which attempt this is, in the status line and the
    log. Raises SaveError naming every file still locked (and, where Windows
    can say, who holds it — see describe_lockers())."""
    total = len(prepared)
    attempts_total = len(_LOCK_RETRY_DELAYS_SECONDS) + 1
    pending = list(range(total))
    errors: dict = {}
    ever_locked = False

    for attempt in range(1, attempts_total + 1):
        still_locked = []
        for idx in pending:
            item = prepared[idx]
            if attempt == 1:
                report_progress(tr("Проверка... {value}/{total}: {display_name}", value=idx + 1, total=total, display_name=item.display_name), idx, total)
            if not item.out_path.exists():
                errors.pop(idx, None)
                continue
            error = _probe_lock(item.out_path)
            if error is None:
                errors.pop(idx, None)
            else:
                errors[idx] = error
                still_locked.append(idx)
        pending = still_locked
        ever_locked = ever_locked or bool(pending)
        if pending and attempt in _GC_ON_LOCK_ATTEMPTS:
            # See _GC_ON_LOCK_ATTEMPTS: a mapping kept alive by cyclic garbage frees
            # only on a full collection. Re-probe right away — if that was it, the
            # save must not then sit out a wait it no longer needs.
            _collect_garbage_for_lock(tr("Проверка перед записью"))
            still_locked = []
            for idx in pending:
                error = _probe_lock(prepared[idx].out_path)
                if error is None:
                    errors.pop(idx, None)
                else:
                    errors[idx] = error
                    still_locked.append(idx)
            pending = still_locked
        if not pending:
            if ever_locked:
                logger.info(tr("Все файлы освободились с попытки %d/%d."), attempt, attempts_total)
            return
        if attempt == attempts_total:
            break

        delay = _LOCK_RETRY_DELAYS_SECONDS[attempt - 1]
        names = ", ".join(prepared[idx].display_name for idx in pending)
        logger.warning(
            tr("Проверка перед записью: файл занят — %s (попытка %d/%d), повтор через %g с: %s"),
            names, attempt, attempts_total, delay, errors[pending[0]],
        )
        report_progress(
            tr("Файл занят: {names} — попытка {attempt}/{attempts_total}, повтор через {delay:g} с", names=names, attempt=attempt, attempts_total=attempts_total, delay=delay),
            total - len(pending), total,
        )
        time.sleep(delay)

    logger.error(tr("Файлы так и остались заняты после %d попыток: %s"),
                 attempts_total, ", ".join(prepared[idx].display_name for idx in pending))
    raise SaveError("\n".join(_locked_message(prepared[idx].out_path, errors[idx]) for idx in pending))


def commit_overwrite(
    prepared: List[PreparedOverwrite],
    report_progress: Callable[[str, int, int], None],
    make_backup: bool = False,
    backup_root: Optional[Path] = None,
    backup_keep: Optional[int] = None,
    on_backup: Optional[Callable[[Path], None]] = None,
    game_version: Optional[str] = None,
) -> int:
    """Phase 2 of "Save files (overwrite)" — writes each already-serialized
    PreparedOverwrite to disk. Each file's own underlying handle was already
    closed explicitly during prepare_overwrite() (root_file.
    close_source_handle(), right after its bytes were extracted) — that's
    what actually makes the file writable now, not anything this phase does.
    _check_not_locked here is a safety net confirming that (or catching a
    genuinely different lock — another program, an antivirus scan, ...), not
    the release mechanism itself.

    Two passes, not one: EVERY file is lock-checked first, before ANY of them
    are written — real reported request. A single check-then-write-per-file
    loop meant a lock on file 3 of 5 left files 1-2 already written to disk
    and 3+ not: a partially-applied save. Checking the whole batch upfront
    means either every file gets written or (if even one is still locked)
    none do, and the error names every file that's still a problem, not just
    the first one hit.

    No cancellation support and no is_changed/obj.data clearing: by the time
    this runs, the Environment is already gone and about to be replaced by a
    fresh reload (see MainWindow.on_menu_save_files) regardless of how this
    finishes, so there's nothing left in this process to keep consistent.

    game_version (core.loader.resolve_game_version's result — PlayerSettings.
    bundleVersion, the developer-set app version) has to be resolved by the
    CALLER while the Environment this save came from is still alive, and
    passed in as a plain string — by the time this function runs, the
    Environment is already gone (see above), so there's nothing left here to
    resolve it FROM. Tagged onto the backup's manifest so a much later restore
    can show which game version it was made against."""
    total = len(prepared)

    _check_batch_not_locked(prepared, report_progress)

    if make_backup:
        # After the lock check (every original is free to read) and before the first
        # write: if the copy fails, nothing has been changed yet. on_backup(folder) tells
        # the caller where the copies went.
        report_progress(tr("Резервная копия..."), 0, total)
        try:
            out_paths = [item.out_path for item in prepared]
            game = game_info_for(out_paths, game_version=game_version or "")
            folder = create_backup(out_paths, backup_root, backup_keep, game=game)
        except BackupError as e:
            raise SaveError(str(e)) from e
        if folder is not None and on_backup is not None:
            on_backup(folder)

    for i, item in enumerate(prepared, start=1):
        report_progress(tr("Сохранение... {i}/{total}: {display_name}", i=i, total=total, display_name=item.display_name), i - 1, total)
        try:
            if item.source_path is not None:
                _copy_file(item.out_path, item.source_path)
                # Overwrite (unlike Save As) treats the edit as applied — the
                # real destination now holds this exact content, so the
                # scratch temp file has fully served its purpose. Best-effort:
                # a failure here leaves an orphaned temp file in the OS temp
                # directory, harmless (no different from any other leftover
                # temp file there) and not worth failing an otherwise-
                # successful save over.
                try:
                    os.remove(item.source_path)
                except OSError:
                    pass
            else:
                _write_file(item.out_path, item.data)
        except Exception as e:
            raise SaveError(tr("Ошибка сохранения «{display_name}»: {error}", display_name=item.display_name, error=e)) from e

    report_progress(tr("Сохранение... {total}/{total}: Готово", total=total), total, total)
    return total
