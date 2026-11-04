"""PyQt-free environment-loading logic — the actual algorithm previously entangled
with QThread/pyqtSignal in loader_thread.py's DataLoaderThread. loader_thread.py is
now a thin Qt adapter: it builds a LoadOptions from CONFIG, implements LoaderCallbacks
by emitting the existing signals (and blocking on a queue.Queue for the two decision
points), and calls EnvironmentLoader.load(). A future console-mode front end would
implement LoaderCallbacks by printing to the terminal / reading stdin instead."""

from core.i18n import tr
import logging
import os
import time
import traceback
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Set, Tuple

import UnityPy
import UnityPy.config
from UnityPy import files
from UnityPy.enums import ClassIDType, FileType
from UnityPy.helpers import bundle_inspector, ImportHelper
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
from UnityPy.helpers.bundle_inspector import QuickScanResult
from UnityPy.exceptions import CabNameCollisionError
from UnityPy.environment import reSplit as _RE_SPLIT_FILE
try:
    from UnityPy.exceptions import UnityVersionFallbackError
except ImportError:
    UnityVersionFallbackError = None

from .options import LoadOptions, LoadMode
from .models import RowItem
from .progress import ProgressReporter, OperationCancelled, CoreOperationError, ProgressThrottle
from .file_utils import shorten_path
from .object_common import RESOURCE_BACKED_TYPES
from .object_preview import RICH_PREVIEW_TYPES, ROW_FIELD_UNRESOLVED, resolve_display_size
from .addressables_resolver import CabIndex
from .platform_sources import PreparedSource, find_adapter
from . import il2cpp_dummy
from .file_prefetch import FilePrefetcher, script_files

logger = logging.getLogger("ustudio.core.loader")

# UnityWeb/UnityRaw can't be cheaply counted for object_count (see quick_scan_bundle_contents) —
# so for those, "is this a big file?" falls back to a disk-size threshold instead.
LEGACY_EAGER_SIZE_THRESHOLD = 300 * 1024 * 1024


@dataclass
class LargeLoadInfo:
    """What the "large data volume" question needs to know."""
    object_count: int          # total objects in everything about to be loaded
    load_all: bool             # "load all assets" is on: every object will really be loaded
    legacy_size_bytes: int = 0  # size of old-format files whose objects can't be counted cheaply
    single_big_bundle: bool = False  # one bundle holds most of the objects


class LoaderCallbacks(ProgressReporter, Protocol):
    """Extends ProgressReporter with the one synchronous decision point a load can hit
    when the amount of data crosses LoadOptions.object_count_threshold. The call blocks
    until the front end has an answer — for the Qt adapter, that means emitting a
    signal and waiting on a queue.Queue for the dialog's result; a console front end
    can prompt on stdin or auto-answer for non-interactive use."""

    def ask_about_large_load(self, info: LargeLoadInfo) -> bool:
        """True to continue loading, False to cancel."""
        ...

    def on_index_progress(self, current: int, total: int, status: str) -> None:
        """A second, separate progress channel used only during parse_objects()'s
        final indexing pass — kept apart from on_progress()'s leveled/nested
        scan-and-load progress because the two drive different GUI elements (the Qt
        adapter wires this to progress_signal, which additionally moves the actual
        QProgressBar and pumps the Qt event queue; on_progress only updates the
        nested status text). Mirrors the pre-refactor code's own two-signal split."""
        ...


# Folder-mode loads never open these (see EnvironmentLoader._load_folder). Explicitly
# picked files ("Load files") are always opened, whatever their extension.
NON_UNITY_BINARY_SUFFIXES = frozenset({".dll", ".exe", ".pdb", ".mdb", ".aspx", ".so", ".dylib"})


class LoadResult:
    def __init__(self, objects: List[RowItem], env, unity_version: str, platform_name: str = "",
                 cab_index: Optional[CabIndex] = None):
        self.objects = objects
        self.env = env
        self.unity_version = unity_version
        self.platform_name = platform_name
        # See EnvironmentLoader._scan_and_confirm() — built as a free byproduct of the
        # quick scan every load already runs, not a separate pass. Threaded through the
        # same way unity_version/platform_name are (loader_thread.py stashes it onto
        # CONFIG rather than widening finished_signal's fixed (objects, env) shape).
        self.cab_index = cab_index


class EnvironmentLoader:
    """One load operation. Not reusable across multiple loads — construct a fresh
    instance per call to load(), same lifetime as the old DataLoaderThread."""

    def __init__(self, options: LoadOptions, callbacks: LoaderCallbacks):
        self.options = options
        self.callbacks = callbacks
        # Set by _load_file_list() whenever a per-file skip was specifically
        # UnityVersionFallbackError (a stripped/missing version header, no
        # fallback configured) — resolve_version() reads this afterward to tell
        # "every file was skipped for a KNOWN, specific reason" apart from
        # "these genuinely don't look like Unity files at all", instead of
        # collapsing both into one generic "no objects found" message. See
        # resolve_version()'s own docstring for the real reported confusion
        # this caused: a good per-file warning already existed (_log_unity_exception
        # below) but its information didn't survive to inform the FINAL message.
        self._version_fallback_skips: int = 0
        # Accumulated for free during _scan_and_confirm()'s existing per-file quick
        # scan (see QuickScanResult.cab_names) — every folder/files-mode load builds
        # this at zero extra I/O cost, so an Addressables-style cross-bundle CAB
        # reference resolved by resolve_via_index() often needs no separate scan at
        # all by the time a MonoBehaviour's Script column is first read. See
        # core/addressables_resolver.py's own module docstring for the problem this
        # solves and dialogs/addressables_resolver_dialog.py for the explicit,
        # user-triggered path used when there's no whole-folder scan to piggyback on
        # (a single bundle loaded via "Load files").
        self.cab_index = CabIndex()

    def _check_cancel(self):
        if self.callbacks.should_cancel():
            raise OperationCancelled()

    def load(self) -> LoadResult:
        """Runs the whole load: prepare -> load assets -> resolve version -> init
        typetree -> parse/index objects. Raises OperationCancelled if the user
        cancels partway, or CoreOperationError for a hard-stop condition."""
        env = UnityPy.Environment()
        self.prepared_source = self._prepare_platform_source()
        self.prepare_environment(env)
        self.load_assets(env)

        unity_version = self.resolve_version(env)
        platform_name = self.resolve_platform(env)
        self.init_typetree(env, unity_version)
        objects = self.parse_objects(env)

        # Restore settings
        if hasattr(UnityPy.config, "BUNDLE_BLOCK_CACHE_SIZE"):
            UnityPy.config.BUNDLE_BLOCK_CACHE_SIZE = 256 * 1024 * 1024

        return LoadResult(objects, env, unity_version, platform_name, cab_index=self.cab_index)

    def _prepare_platform_source(self) -> Optional[PreparedSource]:
        """A picked file that a platform adapter claims (an Android APK, ...) is unpacked
        into a cache folder and the load continues as an ordinary FOLDER load of its data
        directory — see core/platform_sources.py for why, and how to add a platform."""
        opts = self.options
        if opts.load_mode != LoadMode.FILES or not opts.selected_files:
            return None
        adapter = next((a for a in (find_adapter(p) for p in opts.selected_files) if a is not None), None)
        if adapter is None:
            return None
        path = next(p for p in opts.selected_files if find_adapter(p) is adapter)
        others = [p for p in opts.selected_files if p != path]
        if others:
            logger.warning(tr("Вместе с %s выбраны другие файлы — они не загружаются: %d шт."), adapter.label
                           if hasattr(adapter, "label") else adapter.name, len(others))

        last_report = [0.0]

        def progress(done, total, name):
            self._check_cancel()
            now = time.monotonic()
            if now - last_report[0] >= 0.15 or done >= total:
                last_report[0] = now
                self.callbacks.on_progress(0, done // 1024, max(total // 1024, 1), name, tr("Распаковка..."))

        self.callbacks.on_progress(0, 0, 1, path, tr("Распаковка..."))
        try:
            prepared = adapter.prepare(path, progress_cb=progress, should_cancel=self.callbacks.should_cancel)
        except InterruptedError:
            raise OperationCancelled()
        except (ValueError, OSError) as e:
            raise CoreOperationError(tr("Не удалось подготовить «{basename}»: {error}", basename=os.path.basename(path), error=e)) from e
        logger.info(
            "%s: %s (%s)", prepared.label,
            tr("данные взяты из кэша — содержимое файла не менялось") if prepared.reused
            else tr("данные распакованы заново"),
            prepared.data_dir)

        opts.load_mode = LoadMode.FOLDER
        opts.selected_dir = prepared.data_dir
        opts.selected_files = []
        opts.game_data_dir = prepared.data_dir
        opts.managed_dir = prepared.managed_dir
        opts.game_root_dir = ""
        opts.il2cpp_binary = prepared.il2cpp_binary
        opts.il2cpp_metadata = prepared.il2cpp_metadata
        opts.is_il2cpp = bool(prepared.il2cpp_binary)
        return prepared

    def prepare_environment(self, env):
        """Configures global UnityPy environment parameters."""
        prepared = getattr(self, "prepared_source", None)
        # Read by saving: a non-empty reason means "overwrite in place" is impossible.
        env.source_read_only_reason = prepared.read_only_reason if prepared else ""
        env.source_origin = prepared.origin if prepared else ""
        env.source_data_dir = prepared.data_dir if prepared else ""
        # Disable bundle block caching before the initial scan to save memory
        if hasattr(UnityPy.config, "BUNDLE_BLOCK_CACHE_SIZE"):
            UnityPy.config.BUNDLE_BLOCK_CACHE_SIZE = 0

        if self.options.fallback_version:
            UnityPy.config.FALLBACK_UNITY_VERSION = self.options.fallback_version

        if self.options.unity_cn_key:
            UnityPy.set_assetbundle_decrypt_key(self.options.unity_cn_key)

        # fix: path for dependency lookup - not the current directory
        env.path = (
            self.options.selected_dir or self.options.game_data_dir
            or (str(Path(self.options.selected_files[0]).parent) if self.options.selected_files else "")
        )
        if self.options.load_mode == LoadMode.FILES and self.options.selected_files:
            # Explicitly picked files: only search recursively when they really
            # live inside the detected game data folder. Otherwise the search root
            # is just the files' own folder, searched NON-recursively — a stale
            # selected_dir/game_data_dir from an earlier load, or a parent folder
            # full of unrelated games, must not supply dependencies (real bug: a
            # lone resources.assets picked up another game's globalgamemanagers).
            first = Path(self.options.selected_files[0]).resolve()
            data_dir = self.options.game_data_dir
            if data_dir and Path(data_dir).resolve() in first.parents:
                env.path = data_dir
            else:
                env.path = str(first.parent)
                env.local_search_recursive = False

        # Same-named files are all loaded; the policy only decides which one takes the
        # global name slot (see register_cab's docstring) — the first found, or, with
        # "raise", the load stops at the first collision. Anything else (the removed
        # "keep_last"/"ask") behaves as "keep_first".
        env.cab_collision_policy = "raise" if self.options.cab_collision_policy == "raise" else "keep_first"

        # Wires Environment.find_file()'s optional last-resort hook (see its own
        # docstring in UnityPy/environment.py) to this load's cab_index — bound by
        # closure over self.cab_index rather than its current (possibly still empty)
        # contents, so entries added later by _scan_and_confirm()'s own per-file loop
        # (which runs AFTER this, inside load_assets() below) are already visible by
        # the time anything actually calls find_file() (object indexing, the first
        # MonoBehaviour script-name resolution, ...) — none of that happens until
        # parse_objects(), well after the scan. Also the exact same CabIndex object
        # loader_thread.py later stashes onto CONFIG.cab_index (see LoadResult), so
        # a later explicit dialog action (dialogs/addressables_resolver_dialog.py)
        # extending CONFIG.cab_index in place is automatically visible here too, with
        # no separate re-wiring needed for the common case.
        env.external_cab_resolver = lambda cab_name: self.cab_index.find(cab_name)

    def load_assets(self, env) -> None:
        """Performs the import of files or a directory depending on the selected mode."""
        if self.options.load_mode == LoadMode.FILES:
            self._load_files(env)
        elif self.options.load_mode == LoadMode.FOLDER:
            self._load_folder(env)

        if env.skipped_duplicates:
            base = self.options.selected_dir or self.options.game_data_dir
            names = "\n".join(f"  • {shorten_path(skipped, base)}" for skipped, _kept in env.skipped_duplicates)
            logger.info(tr("Пропущено одинаковых по содержимому файлов: %d."), len(env.skipped_duplicates))
            logger.debug(names)

    def _load_files(self, env) -> None:
        if not self.options.selected_files:
            raise CoreOperationError(tr("Не выбраны файлы для загрузки."))

        # Same quick scan + large-file warning as for a folder — previously this
        # warning only showed up in "Load folder" mode, and explicitly selected large
        # files loaded without question and without progress.
        type_filters = self._scan_and_confirm(self.options.selected_files)
        self._load_file_list(env, list(self.options.selected_files), type_filters)

    def _load_folder(self, env) -> None:
        all_files = ImportHelper.list_all_files(self.options.selected_dir)

        if self.options.excluded_folders:
            excluded_norm = [os.path.normcase(os.path.abspath(f)) for f in self.options.excluded_folders]

            def _is_excluded(path: str) -> bool:
                norm = os.path.normcase(os.path.abspath(path))
                return any(norm == ex or norm.startswith(ex + os.sep) for ex in excluded_norm)

            before = len(all_files)
            all_files = [f for f in all_files if not _is_excluded(f)]
            if before != len(all_files):
                logger.info(tr("Пропущено файлов из исключённых папок: %d."), before - len(all_files))

        # Never Unity data, and by far the most expensive files to touch: measured on
        # real games, the FIRST open of a file costs the OS 8-30 ms for an asset/bundle
        # but 30-45 ms (.aspx: 265 ms) for a native/managed binary — antivirus/OS
        # inspection of executables — versus 0.1 ms once cached. A Mono game's Managed/
        # folder alone is 100+ DLLs, i.e. ~85% of the whole first-scan time, all spent
        # opening files that can never hold objects. (TypeTreeGenerator reads the game's
        # DLLs itself from managed_dir/GameAssembly.dll, not through env.files.)
        # Not opened here, but remembered: the text search's "search in binary files"
        # option still covers them, reading them from disk only when actually asked
        # (env.unloaded_binary_files, see tools/text_search_tool.py) — so the cold-open
        # cost is paid only by a user who wants that search, not by every load.
        unloaded = [f for f in all_files if os.path.splitext(f)[1].lower() in NON_UNITY_BINARY_SUFFIXES]
        all_files = [f for f in all_files if os.path.splitext(f)[1].lower() not in NON_UNITY_BINARY_SUFFIXES]
        env.unloaded_binary_files = unloaded
        if unloaded:
            logger.debug("Пропущено исполняемых файлов (dll/exe и т.п.): %d.", len(unloaded))

        type_filters = self._scan_and_confirm(all_files)
        self._load_file_list(env, all_files, type_filters)

    def _load_file_list(self, env, file_paths: List[str], type_filters: Dict[str, set]) -> None:
        """Loads file_paths one at a time via env.load_file(), tolerating a bad
        individual file instead of aborting the whole batch. Used by both
        _load_files() (explicit selection) and _load_folder() — folder-mode used to
        hand its whole list to env.load_files()/load_assets() in one call, which has
        NO per-file exception handling at all (confirmed by reading
        UnityPy/environment.py's load_assets(): the loop body has no try/except), so
        a single unrecognized file anywhere under the scanned tree (a stray
        StreamingAssets .txt/.info file with no null byte in its first ~20 bytes,
        for instance — confirmed via real games: RiffTraxTheGame's
        "Hope Hat.txt", White Shadows' own app.info) aborted the ENTIRE folder load.
        Explicit "Load files" mode never had this problem since it already looped
        per-file here — this just brings folder-mode up to the same standard rather
        than introducing a new one.

        A `.splitN` entry is only ever fed to env.load_file() once per basepath —
        load_file() itself merges all `.splitN` parts for a given basepath in one
        call (mirrors what load_assets()'s own dedup already does for the same
        reason), so a folder scan that lists every part separately doesn't
        re-merge-and-reload the same split file once per part.
        """
        loaded_count = 0
        skipped_files = []
        total = len(file_paths)
        seen_split_basepaths: set = set()

        for i, f_path in enumerate(file_paths):
            self._check_cancel()
            self.callbacks.on_progress(0, i, total, f_path, tr("Загрузка..."))

            split_match = _RE_SPLIT_FILE.match(f_path)
            if split_match:
                basepath = split_match.group(1)
                if basepath in seen_split_basepaths:
                    continue
                seen_split_basepaths.add(basepath)

            try:
                env.load_file(f_path, type_filter=type_filters.get(f_path), progress_callback=self._make_progress_callback(tr("Загрузка...")))
                loaded_count += 1
            except CabNameCollisionError as e:
                # Unlike an ordinary bad/corrupt file, this is the user explicitly
                # opting into "raise": they don't trust keep_first to guess
                # right and want to be stopped and forced to look. Treating it like
                # any other error would silently downgrade that to "first-wins, but
                # with a log line" — so this aborts the whole batch instead of being
                # absorbed into skipped_files like the catch-all below.
                logger.error(
                    tr("Загрузка прервана: совпадение имён файлов (%s). Измените политику в Настройках, если прерывание "
                       "загрузки при таких совпадениях не нужно."), e,
                )
                raise CoreOperationError(tr("Загрузка прервана: совпадение имён файлов ({error}).", error=e)) from e
            except OperationCancelled:
                # Raised from inside the progress_callback passed to env.load_file()
                # above (see _make_progress_callback) — must propagate, not be
                # absorbed into skipped_files like a real per-file error below.
                raise
            except Exception as e:
                skipped_files.append(Path(f_path).name)
                if self._is_unity_version_fallback_error(e):
                    self._version_fallback_skips += 1
                self._log_unity_exception(e)

        self.callbacks.on_progress(0, total, total, "", tr("Загрузка завершена"))
        # Real reported feedback: "Загружено файлов: 1, Пропущено: 0." — the
        # second half adds nothing when nothing was actually skipped, so only
        # include it when there's something to report.
        # The count goes into the final "Загружено файлов: N, объектов: M" line (MainWindow).
        env.loaded_files_count = loaded_count
        if skipped_files:
            logger.warning(tr("Не загружено файлов: %d (%s)"), len(skipped_files), ", ".join(skipped_files))

    def _make_progress_callback(self, status_text: str):
        """Wraps callbacks.on_progress into a callback for UnityPy (env.load_files/
        load_file/read_files) — these calls are blocking and don't check for
        cancellation themselves, so cancellation for them is implemented via an
        exception raised directly from the callback, which UnityPy invokes on every
        iteration of its inner loop.

        Real reported bug, root-caused via live instrumentation against the real
        Phonopolis folder (not guessed): this callback used to call
        callbacks.on_progress() UNCONDITIONALLY on every single UnityPy-side
        iteration, with no throttling at all. For a large file whose internal
        loop granularity doesn't match its own reported (i, total) (UnityPy
        iterates over many decompression blocks while (i, total) — an ENTRY
        count — stays fixed, e.g. "1/1" for a single-entry bundle), this fired
        the exact same progress_extended_signal payload hundreds of times over
        less than a second (measured: ~135 identical "1/1" emissions in ~0.7s
        for one file in that folder) — the same class of GUI-flooding bug this
        project has already found and fixed elsewhere (compression-chunk
        progress during CAB rebuild), just never applied here. The visible
        symptom this produces matches the report exactly: the status text
        shows something that reads as "done" (i == total) for an extended
        stretch while the file is still genuinely loading, with no further
        signal until the next real phase boundary — easily read as "progress
        reached 100% early."

        Deliberately a plain time-based gate here, NOT core.progress.
        ProgressThrottle — that class's own "always report when index >= total
        - 1" bypass (correct for a loop where i monotonically climbs to
        total-1 exactly ONCE, right at the end) is wrong for this callback:
        UnityPy repeatedly calls back with the SAME already-at-total i (e.g.
        "1/1", over and over, for the entire duration of decompressing one
        large entry) — that bypass would fire on literally every call and
        defeat the throttle completely, which is exactly what a first attempt
        at this fix did (confirmed by re-running the same live instrumentation
        afterward and seeing the identical flood, not assumed to be fixed).
        No such guarantee is needed here anyway: _load_file_list()'s own outer
        loop already emits its own guaranteed final "Загрузка завершена" once
        this whole per-file call returns, independent of whatever this inner
        callback did or didn't report along the way.

        should_cancel() is deliberately NOT throttled (checked every
        iteration, same as everywhere else this pattern is used, since it's a
        cheap flag read with no GUI-thread cost) — only the GUI-facing report
        is."""
        last_report_time = [0.0]
        interval = 0.15

        def _cb(level, i, total, name):
            self._check_cancel()
            now = time.monotonic()
            if now - last_report_time[0] >= interval:
                last_report_time[0] = now
                self.callbacks.on_progress(level, i, total, name, status_text)
        return _cb

    # Types every load keeps even when only the "indexed types" are wanted: other
    # features look these up on demand (script names, GameObject names, the scene
    # hierarchy, SDF font materials/atlases). Leaving them out of a filtered load
    # would turn those into "Unknown"/unresolved references.
    SUPPORT_TYPE_NAMES = frozenset({
        "MonoScript", "GameObject", "Transform", "RectTransform", "Material", "Texture2D",
    })

    def _derived_type_filter(self) -> Set[int]:
        """Class IDs to actually load when the data is large and "load all assets" is
        off: the user's indexed types plus SUPPORT_TYPE_NAMES. Everything else is left
        unparsed (and written back untouched on save)."""
        names = set(self.options.indexed_types) if self.options.indexed_types else set(RICH_PREVIEW_TYPES)
        names |= self.SUPPORT_TYPE_NAMES
        ids: Set[int] = set()
        for name in names:
            try:
                ids.add(int(ClassIDType[name].value))
            except KeyError:
                pass  # a type name this UnityPy build doesn't know — nothing to filter on
        return ids

    def _script_files_to_prefetch(self) -> List[str]:
        """What init_typetree() opens after the load (Managed DLLs, or GameAssembly + metadata) - see
        core/file_prefetch.py. Never raises: a guess that fails just means nothing extra is opened ahead."""
        try:
            o = self.options
            inputs = il2cpp_dummy.find_inputs(o.game_data_dir, o.game_root_dir, o.il2cpp_binary, o.il2cpp_metadata)
            return script_files(o.managed_dir, inputs)
        except Exception:  # noqa: BLE001
            return []

    def _scan_and_confirm(self, file_paths: List[str]) -> Dict[str, set]:
        """Quick scan of the file list (object_count_only — near-free, no object table
        read and no bundle block decompression) and, if the total object count exceeds
        the threshold, one confirmation via callbacks.ask_about_large_load. Shared by
        both load modes. Returns the per-file class-ID filters to load with (empty
        unless the data is large and "load all assets" is off)."""
        type_filters: Dict[str, set] = {}

        # Phase 1: quick scan of all files. The first open of a file the system has not checked yet costs
        # far more than reading it (core/file_prefetch.py: Phonopolis 20.3 s -> 6.9 s), so the files are opened
        # ahead of the scan, several at a time - and the script files the next step opens, too.
        scan_results: Dict[str, QuickScanResult] = {}
        total_scan = len(file_paths)
        with FilePrefetcher(list(file_paths) + self._script_files_to_prefetch()):
            for i, f_path in enumerate(file_paths):
                self._check_cancel()
                self.callbacks.on_progress(0, i, total_scan, f_path, tr("Сканирование..."))
                try:
                    scan = bundle_inspector.quick_scan_bundle_contents(f_path)
                    scan_results[f_path] = scan
                    if scan.cab_names:
                        self.cab_index.add_bundle(f_path, scan.cab_names)
                except Exception as e:
                    self._log_unity_exception(e)
        self.callbacks.on_progress(0, total_scan, total_scan, "", tr("Сканирование завершено"))
        if self.options.load_mode == LoadMode.FOLDER and self.options.selected_dir:
            if self.options.selected_dir not in self.cab_index.roots:
                self.cab_index.roots.append(self.options.selected_dir)

        # Phase 2: one decision for the whole selection
        total_objects = sum(r.object_count for r in scan_results.values())
        legacy_big_bytes = sum(
            r.disk_size_bytes for r in scan_results.values()
            if r.is_legacy_eager and r.disk_size_bytes > LEGACY_EAGER_SIZE_THRESHOLD
        )
        if total_objects <= self.options.object_count_threshold and not legacy_big_bytes:
            return type_filters

        biggest = max((r.object_count for r in scan_results.values()), default=0)
        info = LargeLoadInfo(
            object_count=total_objects,
            load_all=self.options.load_all_assets,
            legacy_size_bytes=legacy_big_bytes,
            single_big_bundle=total_objects > 0 and biggest * 2 > total_objects,
        )
        self._check_cancel()
        if not self.callbacks.ask_about_large_load(info):
            raise OperationCancelled()

        # Phase 3: with "load all assets" off only the indexed types will ever become
        # rows, so don't spend memory and time parsing the rest.
        if not self.options.load_all_assets:
            wanted = self._derived_type_filter()
            for f_path, scan in scan_results.items():
                if scan.is_legacy_eager or not scan.class_ids or scan.class_ids <= wanted:
                    continue  # nothing to leave out (or the format can't be filtered)
                type_filters[f_path] = wanted
        return type_filters

    def resolve_version(self, env) -> str:
        """Determines the engine version based on the asset structure.

        Real reported confusion: this used to treat "no object carries a
        resolvable unity_version" as the only failure mode, ending in a
        MonoBehaviour-specific dead end ("Fallback версия не задана. Чтение
        MonoBehaviour объектов невозможно.") — stale wording from when this app
        only supported MonoBehaviour, and misleading regardless of app version
        for the actual root cause seen in practice: env.load_file() can "succeed"
        (no exception, "Files loaded: N, Skipped: 0") on a file that simply isn't
        a Unity asset file at all (some unrelated file the user picked), which
        produces ZERO objects in env.objects entirely (the log now just reads
        "Загружено файлов: N." for this case — see this method's own
        skipped-count formatting further up) — a materially different,
        more fundamental problem than "objects exist but their version string
        couldn't be read," and one no fallback version could ever fix. Split into
        two distinct, accurately-worded failures instead of collapsing both into
        one MonoBehaviour-flavored message."""
        found_any_object = False
        try:
            for obj in env.objects:
                found_any_object = True
                version = getattr(getattr(obj, "assets_file", None), "unity_version", None)
                if version:
                    return version
        except Exception as e:
            logger.error(tr("Ошибка при определении версии Unity: %s"), e)

        if not found_any_object:
            # Real reported paradox, confirmed with a real stripped-version
            # fixture: env.load_file() raises UnityVersionFallbackError and
            # ABORTS registering the file at all (never reaching env.files/
            # env.objects) the moment it can't read a version AND no fallback
            # is configured — _load_file_list() already catches this per file
            # (logging a specific, correct warning) and counts it here via
            # _version_fallback_skips, but that information used to be
            # discarded by the time this generic "no objects found" message
            # got written, producing the self-contradictory pairing the user
            # pointed out: "no objects found, might not be Unity files" right
            # after a warning that already said exactly why (missing version
            # header + no fallback) — the two shouldn't be presented as if
            # they were unrelated possibilities when the real cause is
            # already known with certainty from the exception type itself.
            if self._version_fallback_skips > 0:
                raise CoreOperationError(
                    tr("Не удалось прочитать объекты: пропущено файлов: {version_fallback_skips} — из-за отсутствующей "
                       "версии Unity и незаданной fallback-версии. Укажите fallback-версию в настройках и повторите "
                       "загрузку.", version_fallback_skips=self._version_fallback_skips)
                )
            raise CoreOperationError(
                tr("Не найдено ни одного объекта. Возможно, выбранные файлы не являются файлами Unity, повреждены, "
                   "либо формат не поддерживается.")
            )

        logger.warning(tr("Не удалось автоматически определить версию Unity, будет задействована fallback версия."))

        if not self.options.fallback_version:
            raise CoreOperationError(
                tr("Не удалось автоматически определить версию Unity, а fallback-версия не задана в настройках — "
                   "без неё генерация дерева типов невозможна. Укажите fallback-версию в настройках программы и "
                   "повторите загрузку.")
            )

        return self.options.fallback_version

    def resolve_platform(self, env) -> str:
        """Determines the build target platform (e.g. "StandaloneWindows64",
        "Android") from the loaded assets — same "walk env.objects, take the first
        resolvable value" approach as resolve_version(), just reading
        target_platform instead. Best-effort: an empty string here just means the
        title bar omits that segment, not a load failure."""
        try:
            for obj in env.objects:
                target = getattr(getattr(obj, "assets_file", None), "target_platform", None)
                if target is not None and target.name != "UnknownPlatform":
                    return target.name
        except Exception as e:
            logger.error(tr("Ошибка при определении платформы: %s"), e)
        return ""

    def _warn_if_il2cpp(self):
        """A successfully-loaded generator is not proof it actually WORKS for this
        game — against a real IL2CPP fixture, the generator loaded without error but
        still failed to produce a correct TypeTree for most MonoBehaviour scripts,
        surfacing later as "Expected to read N bytes, but only read M bytes" when a
        specific object's full data is opened. There's no cheap way to verify every
        script up front, so this is a heads-up logged once right after a successful
        init for an IL2CPP game, not a promise that reading will work.

        Kept brief deliberately — the full explanation (what's actually wrong and
        how to fix it) now lives in preview_panel.py's preview_warning_label,
        shown prominently the moment a MonoBehaviour actually fails to parse,
        rather than duplicated in full here too."""
        if self.options.is_il2cpp:
            logger.warning(
                tr("Игра использует IL2CPP: часть скриптов может прочитаться не полностью.")
            )

    @staticmethod
    def _log_scripts_unreadable(env, message: str, *args) -> None:
        """The script reader (TypeTreeGenerator) is not available. That only matters to a user when some loaded
        file has MonoBehaviours WITHOUT type trees of its own (see scripts_need_generator()): a bundle that
        carries them (typical for Addressables) reads its scripts fine, and warning about a missing `Managed`
        folder there only sends people looking for something that would change nothing. Then it is debug."""
        if scripts_need_generator(env):
            logger.warning(message, *args)
        else:
            logger.debug("Чтение скриптов не подготовлено, но файлы содержат деревья типов: " + message, *args)

    def _warn_typetree_unavailable(self, env, error: Exception) -> None:
        """The data needed to read scripts could not be read from the game's folder: say so once, in plain
        words, and let the load go on (every other object type reads without it)."""
        self._log_scripts_unreadable(
            env,
            tr("Не удалось прочитать данные игры, нужные для чтения скриптов%s. Файлы загружены; объекты "
               "MonoBehaviour могут прочитаться не полностью."),
            " " + tr("(возможно, формат IL2CPP этой игры пока не поддерживается)") if self.options.is_il2cpp else "")
        logger.debug("Ошибка подготовки чтения скриптов: %r", error)

    def init_typetree(self, env, version: str) -> None:
        """Initializes TypeTreeGenerator structures with metadata from the executable files."""
        logger.debug("Подготовка чтения скриптов для версии Unity: %s", version)
        generator = TypeTreeGenerator(version)

        # Dummy DLLs prepared for this IL2CPP game (core/il2cpp_dummy.py — «Подготовить скрипты IL2CPP») come
        # before the native IL2CPP reader, which cannot read every game (metadata v38/v39); a game's own Managed
        # folder still wins. Only a stat of the two input files — no hashing of GameAssembly.dll.
        # env.typetree_unity_version: for switching to prepared DLLs later without a reload (build_prepared_generator).
        env.typetree_unity_version = version
        # env.il2cpp_inputs: what the GUI's «Подготовить скрипты IL2CPP» runs on (None: not an IL2CPP game).
        env.il2cpp_inputs = il2cpp_dummy.find_inputs(
            self.options.game_data_dir, self.options.game_root_dir,
            self.options.il2cpp_binary, self.options.il2cpp_metadata)
        # env.il2cpp_dummy_dir: the prepared DLL folder THIS load reads scripts with (None: not used) — the dialog
        # tells "ready" apart from "prepared, but load the game again to use it".
        env.il2cpp_dummy_dir = None
        dummy_dir = None
        if not (self.options.managed_dir and os.path.exists(self.options.managed_dir)):
            dummy_dir = il2cpp_dummy.cached_dummy_dir(env.il2cpp_inputs)
        if dummy_dir is not None:
            try:
                generator.load_local_dll_folder(str(dummy_dir))
            except Exception as e:  # noqa: BLE001 - a failed generator must not abort the load
                self._warn_typetree_unavailable(env, e)
                return
            env.typetree_generator = generator
            env.il2cpp_dummy_dir = dummy_dir
            logger.info(tr("Скрипты IL2CPP читаются по подготовленным DLL: %s"), dummy_dir,
                        extra={"folder_path": str(dummy_dir)})       # a link in the GUI log
            self._warn_if_il2cpp()
            return

        inputs = env.il2cpp_inputs
        if inputs is not None and not inputs.is_windows_binary:
            # IL2CPP outside Windows: the binary/metadata given explicitly (a platform adapter unpacked
            # them — e.g. Android libil2cpp.so) or found in a Linux/macOS game folder (GameAssembly.so /
            # .dylib) — load_local_game below only knows GameAssembly.dll. A universal macOS binary is
            # reduced to one slice first (il2cpp_dummy.binary_bytes). A Nintendo Switch NSO is not tried: the
            # native reader cannot read it («failed to load il2cpp», measured on KAMIKO) — only the dumper can
            # (the preview's «Исправить»).
            if inputs.is_nso:
                self._log_scripts_unreadable(
                    env, tr("Не удалось прочитать данные IL2CPP — часть скриптов может прочитаться не полностью."))
                return
            try:
                binary = il2cpp_dummy.binary_bytes(inputs)
                metadata = inputs.metadata.read_bytes()
                generator.load_il2cpp(binary, metadata)
                env.typetree_generator = generator
                logger.debug("Данные IL2CPP загружены")
                self._warn_if_il2cpp()
                return
            except Exception:  # noqa: BLE001 - a failed generator must not abort the load
                self._log_scripts_unreadable(
                    env, tr("Не удалось прочитать данные IL2CPP — часть скриптов может прочитаться не полностью."))
                return

        # Both folder routes below can fail on a perfectly ordinary game: the native reader of IL2CPP data
        # (load_local_game) refuses metadata it does not know — a real report: Lego Party, metadata v39,
        # "failed to load il2cpp" — and a DLL folder can hold an unreadable file. That must not abort the
        # load (see the comment further down: only MonoBehaviour scripts need the generator), exactly like
        # the explicit-IL2CPP route above and core/cab_archive.py already treat it.
        if self.options.managed_dir and os.path.exists(self.options.managed_dir):
            try:
                generator.load_local_dll_folder(self.options.managed_dir)
            except Exception as e:  # noqa: BLE001 - a failed generator must not abort the load
                self._warn_typetree_unavailable(env, e)
                return
            env.typetree_generator = generator
            logger.debug("Загружены DLL из папки Managed: %s", self.options.managed_dir)
            self._warn_if_il2cpp()
            return
        elif self.options.game_root_dir and os.path.exists(self.options.game_root_dir):
            try:
                generator.load_local_game(self.options.game_root_dir)
            except Exception as e:  # noqa: BLE001 - a failed generator must not abort the load
                self._warn_typetree_unavailable(env, e)
                return
            env.typetree_generator = generator
            logger.debug("Загружены DLL из папки игры: %s", self.options.game_root_dir)
            self._warn_if_il2cpp()
            return

        # Used to abort the whole load here (raise CoreOperationError) — but
        # TypeTreeGenerator is only ever needed for MonoBehaviour's
        # script-reflection-based fields; every other supported type
        # (Texture2D/AudioClip/TextAsset/Sprite/Mesh/Shader/GameObject/Material/
        # AnimationClip/AnimatorController/VideoClip) parses via Unity's built-in
        # TPK typetrees regardless (see UnityPy/helpers/Tpk.py), so a missing
        # Managed/game-root folder no longer has to block the whole load — just
        # MonoBehaviour objects, which will surface their own clear parse error
        # (via the Dump/Preview tabs) if actually opened.
        self._log_scripts_unreadable(
            env,
            tr("Не найдена папка Managed. Без неё MonoBehaviour скрипты могут прочитаться не полностью; "
               "остальные объекты это не затрагивает.")
        )

    def parse_objects(self, env) -> List[RowItem]:
        """Extracts and indexes objects from the loaded environment."""
        parsed_objects: List[RowItem] = []
        all_objs = list(env.objects)
        total_objs = len(all_objs)

        # Throttling by TIME (not by object count): total_objs legitimately reaches
        # tens of millions on real fixtures — see ProgressThrottle's docstring.
        throttle = ProgressThrottle()

        # indexed_types empty ("user saved zero selected types") falls back to
        # RICH_PREVIEW_TYPES rather than indexing nothing — same "empty selection
        # loading nothing is a worse default" reasoning TypeChecklistDialog already
        # applies elsewhere. Unioned with whatever a big-file/folder warning dialog's
        # own type selection explicitly picked this load (see __init__), so that
        # per-load choice always wins over the general setting.
        base_allowed = set(self.options.indexed_types) if self.options.indexed_types else RICH_PREVIEW_TYPES
        effective_allowed = base_allowed

        # The same rows as build_row_item(obj, ...) per object (tests/test_load_speed.py compares them), built
        # without its per-object overhead: on Lego Party (3.1 M objects, 1.95 M rows) that overhead — the enum's
        # .name (~7 M lookups), the `container` property, a progress check per object — was most of this phase.
        # Per type and per file values are looked up once; only resource-backed types read their real size.
        include_all = self.options.load_all_assets
        type_names: dict = {}           # class_id -> type name (obj.type is ClassIDType(class_id))
        file_info: dict = {}            # id(assets_file) -> (source name, container path_dict or None)
        environment_indexed = False
        last_file = object()            # env.objects hands objects out file by file: look up on a change only
        source = path_dict = None
        append = parsed_objects.append
        for i, obj in enumerate(all_objs):
            if not i & 1023 and throttle.should_report(i, total_objs):
                self._check_cancel()
                self.callbacks.on_index_progress(i + 1, total_objs, tr("Индексация объектов... {value}/{total_objs}", value=i + 1, total_objs=total_objs))
                throttle.pause()

            class_id = obj.class_id
            type_name = type_names.get(class_id)
            if type_name is None:
                type_name = type_names[class_id] = obj.type.name
            if not include_all and type_name not in effective_allowed:
                continue
            assets_file = obj.assets_file
            if assets_file is not last_file:
                last_file = assets_file
                info = file_info.get(id(assets_file))
                if info is None:
                    if not environment_indexed:
                        environment_indexed = True
                        try:
                            env._build_container_index()
                        except Exception:
                            pass
                    try:
                        path_dict = assets_file._container.path_dict
                    except Exception:
                        path_dict = None        # build_row_item's try/except: no container path
                    info = file_info[id(assets_file)] = (assets_file.name if assets_file else "Unknown", path_dict,
                                                         assets_file)
                source, path_dict, _keep_alive = info
            if path_dict is None:
                container_path = ""
            else:
                container_path = path_dict.get(obj.path_id) or ""
            append({
                "type": type_name,
                "name": ROW_FIELD_UNRESOLVED,
                "container_path": container_path,
                "script_name": ROW_FIELD_UNRESOLVED,
                "source": source,
                "path_id": obj.path_id,
                "size": resolve_display_size(obj) if type_name in RESOURCE_BACKED_TYPES else obj.byte_size,
                "obj_ref": obj,
            })

        self.callbacks.on_index_progress(total_objs, total_objs, tr("Загрузка завершена!"))
        return parsed_objects

    @staticmethod
    def _is_unity_version_fallback_error(exc: Exception) -> bool:
        if UnityVersionFallbackError is not None and isinstance(exc, UnityVersionFallbackError):
            return True
        return type(exc).__name__ == "UnityVersionFallbackError"

    def _log_unity_exception(self, e: Exception) -> None:
        """Logs a non-fatal UnityPy error encountered while loading one file (the
        batch as a whole continues) — fatal cases (CabNameCollisionError, missing
        fallback version) are raised as CoreOperationError at their call sites instead,
        which is what actually determines whether the operation aborts."""
        if self._is_unity_version_fallback_error(e):
            logger.warning(
                tr("В загруженных файлах обрезана шапка, поэтому не удалось автоматически определить версию Unity. "
                   "Укажите fallback-версию и повторите загрузку.")
            )
            return
        logger.error(tr("Ошибка чтения ресурсов:\n%s"), traceback.format_exc())


def build_row_item(obj, include_all: bool = False, allowed_types: Optional[Set[str]] = None) -> Optional[RowItem]:
    """The exact per-object RowItem construction EnvironmentLoader.parse_objects()
    uses — factored out (no logic change) so parse_dependency_file_objects()
    below builds identical rows for a single file without duplicating this.
    Returns None for a type outside allowed_types (parse_objects()'s own
    "not worth a table row" filter, applied here so both callers share it) —
    unless include_all is set (CONFIG.load_all_assets / the "Загружать все
    ассеты" Settings checkbox), which indexes every object regardless of
    type. allowed_types defaults to RICH_PREVIEW_TYPES when not given (every
    caller before CONFIG.indexed_types existed relied on exactly that
    default — e.g. core/sdf_resolver.py's always-include_all=True call never
    reaches this branch either way). Safe to lift: every per-object call below already dispatches on
    obj.type.name with a cheap, type-agnostic default for anything it
    doesn't specially handle — resolve_object_name()/resolve_shader_name()
    fall back to peek_object_name()/default_object_name() (a bounded "peek
    just the name field" read, not a full parse) for any type but Shader,
    resolve_script_name() returns "" for anything but MonoBehaviour, and
    resolve_display_size() returns obj.byte_size directly for any type
    outside the 5-type _RESOURCE_BACKED_TYPES list — none of that dispatch
    logic assumes the object's type is already RICH_PREVIEW_TYPES-filtered,
    so widening what reaches it introduces no new code path, just more
    objects taking the already-existing generic branch."""
    if not include_all and obj.type.name not in (allowed_types if allowed_types is not None else RICH_PREVIEW_TYPES):
        return None

    # resolve_object_name()/resolve_script_name() are deliberately NOT called
    # here anymore — real, measured finding via cProfile on a real
    # ~78M-object fixture: together they were the dominant cost of indexing a
    # large game (dominated by peek_field()/PPtr.deref() chains for
    # MonoBehaviour's GameObject-fallback-name feature), and the resolved
    # strings are a real, measured RAM cost at that scale too. RowItem's
    # "name"/"script_name" now start as ROW_FIELD_UNRESOLVED (see
    # core/object_preview.py) and get resolved+memoized lazily, the first
    # time something actually asks for a specific row's name/script — a
    # visible table cell, an active text search, a sort by that column —
    # via get_row_name()/get_row_script_name(). EVERY reader of these two
    # fields anywhere in the codebase must go through those two accessors,
    # never item["name"]/item.get("name") (or "script_name") directly, or
    # it'll see the unresolved sentinel instead of a real value.
    resolved_name = ROW_FIELD_UNRESOLVED
    script_name = ROW_FIELD_UNRESOLVED
    # AudioClip/Texture2D/Texture2DArray/Mesh/VideoClip objects are mostly a
    # small header — the actual data lives in an external .resS/.resource
    # file. resolve_display_size() reads that real size (falling back to
    # byte_size for everything else, and for these 5 types too when their
    # data happens to be stored inline instead) so the table's Size column
    # reflects what's actually on disk, not just the header.
    size = resolve_display_size(obj)

    # obj.container triggers Environment._build_container_index() on its
    # first call (cached after — see that method's docstring), so this is a
    # one-time cost for the whole load, not per object.
    try:
        container_path = obj.container or ""
    except Exception:
        container_path = ""

    return {
        "type": obj.type.name,
        "name": resolved_name,
        "container_path": container_path,
        "script_name": script_name,
        "source": obj.assets_file.name if obj.assets_file else "Unknown",
        "path_id": obj.path_id,
        "size": size,
        "obj_ref": obj,
    }


def parse_dependency_file_objects(
    assets_file, report_progress=None, include_all: bool = False, allowed_types: Optional[Set[str]] = None,
) -> List[RowItem]:
    """Builds RowItems for every object in `assets_file` alone, using the exact
    same per-object logic (build_row_item) as a full parse_objects() pass —
    used to widen the table with a single lazily-loaded dependency file's
    objects (see MainWindow._load_dependency_into_table) without re-walking
    the whole Environment. Caller is responsible for un-flagging
    assets_file.is_dependency (this function only reads assets_file.objects
    directly, so it works whether that's been flipped yet or not — but it
    should be, before the objects it returns are added to the table, so that
    a LATER full reload of the whole environment counts them too instead of
    silently reverting to excluding them again).

    include_all/allowed_types are passed straight through to build_row_item() —
    the caller should pass CONFIG.load_all_assets/CONFIG.indexed_types so a
    dependency file pulled in mid-session gets indexed the same way the
    original load would have.

    report_progress, if given, is called as report_progress(phase, current,
    total) — matching gui_workers.BackgroundWorker's fn(report_progress)
    contract, so this can run directly as a BackgroundWorker's work function."""
    all_objs = list(assets_file.objects.values())
    total = len(all_objs)
    throttle = ProgressThrottle()
    parsed: List[RowItem] = []
    for i, obj in enumerate(all_objs):
        if report_progress is not None and throttle.should_report(i, total):
            report_progress("index", i + 1, total)
            throttle.pause()
        row = build_row_item(obj, include_all=include_all, allowed_types=allowed_types)
        if row is not None:
            parsed.append(row)
    if report_progress is not None:
        report_progress("index", total, total)
    return parsed


def build_prepared_generator(unity_version: str, dummy_dir) -> TypeTreeGenerator:
    """A script reader over prepared IL2CPP DLLs (core/il2cpp_dummy.py). The slow part of switching a loaded game to
    them (~2.5 s for 79 DLLs the first time, then ~0.05 s) — run it off the GUI thread, then install_prepared_generator."""
    generator = TypeTreeGenerator(unity_version)
    generator.load_local_dll_folder(str(dummy_dir))
    return generator


def install_prepared_generator(env, generator: TypeTreeGenerator, dummy_dir) -> None:
    """Switches a LOADED game to `generator` without loading it again. UnityPy writes a generated MonoBehaviour layout
    back into the file's shared type entry (ObjectReader._get_typetree_node -> serialized_type.node) so the next object
    of that script skips generation; those layouts came from the OLD reader, so they are dropped here. Only in files
    that carry no layouts of their own (`_enable_type_tree` False — every write-back happened there, and save() does not
    write nodes for such files); a file's own layouts are never touched."""
    for f in collect_serialized_files(env):
        if getattr(f, "_enable_type_tree", True):
            continue
        for st in getattr(f, "types", None) or []:
            if st.class_id == 114 or st.class_id < 0:          # MonoBehaviour (negative ids: scripts in format < 16)
                st.node = None
    env.typetree_generator = generator
    env.il2cpp_dummy_dir = dummy_dir
    logger.info(tr("Скрипты IL2CPP читаются по подготовленным DLL: %s"), dummy_dir,
                extra={"folder_path": str(dummy_dir)})       # a link in the GUI log


def collect_serialized_files(env) -> List["files.SerializedFile"]:
    """Walks the whole Environment, including files nested inside a loaded
    BundleFile, collecting every SerializedFile — deliberately NOT limited to
    env.objects/the table's own contents, since that property skips any file
    pulled in lazily as a dependency (is_dependency=True, see PPtr.deref()'s
    find_file() fallback and environment.py's own Environment.objects) even
    though such a file is fully parsed and holds perfectly real header/
    externals metadata. Used by main.py's Инструменты → "Информация о
    файле..." — a general "pick any loaded file" tool, not scoped to whatever
    a PPtr happens to reference."""
    found: List["files.SerializedFile"] = []

    def _walk(container) -> None:
        for f in getattr(container, "files", {}).values():
            if isinstance(f, files.SerializedFile):
                found.append(f)
            elif getattr(f, "files", None):
                _walk(f)

    _walk(env)
    return found


def scripts_need_generator(env) -> bool:
    """True when reading the scripts of what is loaded depends on the TypeTreeGenerator: some loaded file has
    MonoBehaviours (class 114 in its type table) and no type trees of its own. Files that carry their own
    (most bundles) describe every field themselves; so does an environment with no MonoBehaviours at all.
    Conservative: a file whose type table could not be read counts as needing it."""
    for sf in collect_serialized_files(env):
        if getattr(sf, "_enable_type_tree", False):
            continue
        types = getattr(sf, "types", None)
        if not types or any(getattr(t, "class_id", None) == 114 for t in types):
            return True
    return False


def restricted_indexed_types(load_all_assets: bool, indexed_types) -> Optional[List[str]]:
    """The object types that become table rows when the indexing settings were NARROWED from the defaults (some
    default type switched off), else None. Used to remind the user — before a long load and after it — that
    what they will see is only part of the data: a forgotten "only Texture2D" setting looks exactly like a game that
    has nothing else in it. "Load all assets" lifts the restriction; adding types to the defaults is not one."""
    if load_all_assets:
        return None
    names = set(indexed_types) if indexed_types else set(RICH_PREVIEW_TYPES)
    return None if names >= set(RICH_PREVIEW_TYPES) else sorted(names)


def resolve_game_version(env) -> str:
    """The developer-set app version (Unity's `PlayerSettings.bundleVersion` — what
    `Application.version` reads at runtime), NOT the Unity engine version
    (EnvironmentLoader.resolve_version() reads that, from a completely different
    field). `PlayerSettings` (class id 129) is a small Unity built-in object
    always present at path_id=1 in a standalone build's globalgamemanagers/
    data.unity3d — a cheap single-object parse, not a scan, confirmed against
    real shipped games (Mono and IL2CPP alike: Amanda 2 "2.1.6", Kindergarten 3
    "0.01", Elevated Dread "0.1", Petscop "1.2-pre27" — matching that fixture's
    own already-documented name). Used to tag a backup with the game version it
    was made against (core.backup.game_info_for's game_version), so a much
    later restore can show "this backup predates a version you might have
    updated since" instead of silently assuming a byte difference always means
    your own edit. Best-effort: an empty string just means the tag is skipped,
    same as resolve_version()'s own "" convention for an unresolvable engine
    version — deliberately not a load failure, and deliberately not attempting
    to read the CURRENTLY installed version from disk without loading it (no
    reliable way to do that without guessing at a game's own folder layout).

    Real bug found via a real fixture, not assumed: on a very new Unity version
    (6000.0.58, Truck-kun), a plain check_read=True parse ALWAYS raised
    ("Expected to read 788 bytes, but only read 784 bytes") — a strict
    trailing-byte-count consistency check this newer PlayerSettings schema
    slightly disagrees with (the TPK schema's declared size vs. what's
    actually present), NOT a problem with bundleVersion's own value — verified
    directly: check_read=False parses cleanly and returns the correct,
    real "v26.32.4", every other field (including brand-new 6000.x-only ones
    like androidVulkanDenyFilterList) reading sane too. Passing check_read=False
    here mirrors resolve_version()/resolve_platform()'s own "best-effort, not a
    correctness gate" stance — this function only ever reads ONE field, it has
    no use for a whole-object byte-exact guarantee anyway.

    Real reported gap, root-caused via the user's own persisted QSettings
    (last_files_dir), not guessed: a "Load files" session that selects just
    ONE loose file (e.g. resources.assets — a normal, common workflow: "I only
    want to edit this") never loads globalgamemanagers at all, so PlayerSettings
    is never among env.objects, and this returned "" even for a game whose
    version WOULD have resolved fine under a folder load. Confirmed directly:
    loading only resources.assets via LoadMode.FILES leaves env.files with
    that ONE path and no PlayerSettings anywhere. Fixed with the fallback
    below — peeks at a sibling globalgamemanagers file in the same folder as
    whatever loose file WAS loaded, via its own separate, throwaway
    UnityPy.load() (never touches the caller's own `env` — this must stay a
    read-only side query, not a real dependency load with find_file()
    registration/cab-collision side effects). Deliberately narrow: only helps
    when globalgamemanagers is a real LOOSE file next to what was loaded — a
    bundle-only game (data.unity3d) has no such sibling to peek at, and this
    makes no attempt to open/scan a whole bundle just for one field (that
    would defeat the point of it being a cheap, standalone read)."""
    try:
        for obj in env.objects:
            if obj.type.name == "PlayerSettings":
                version = obj.parse_as_dict(check_read=False).get("bundleVersion")
                if version:
                    return str(version)
    except Exception as e:
        logger.error(tr("Ошибка при определении версии игры: %s"), e)
        return ""

    try:
        checked_dirs = set()
        for path in getattr(env, "files", {}):
            if not isinstance(path, str) or not os.path.isabs(path):
                continue
            folder = os.path.dirname(path)
            if folder in checked_dirs:
                continue
            checked_dirs.add(folder)
            candidate = os.path.join(folder, "globalgamemanagers")
            if not os.path.isfile(candidate):
                continue
            try:
                side_env = UnityPy.load(candidate)
                for obj in side_env.objects:
                    if obj.type.name == "PlayerSettings":
                        version = obj.parse_as_dict(check_read=False).get("bundleVersion")
                        if version:
                            return str(version)
            except Exception:
                continue  # this candidate didn't pan out — try the next folder, if any
    except Exception as e:
        logger.error(tr("Ошибка при резервном поиске версии игры (globalgamemanagers): %s"), e)
    return ""
