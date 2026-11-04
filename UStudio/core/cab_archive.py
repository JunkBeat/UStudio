"""PyQt-free CAB (bundle) archive browsing/export/import/rebuild logic — previously
embedded directly in cab_browser_dialog.py's work() closures. CabBrowserDialog is now
a thin Qt adapter: it runs these calls on its background QThread and reports progress
via Qt signals; a future console-mode front end would call the same methods directly."""

from core.i18n import tr
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import UnityPy
from UnityPy import files
from UnityPy.enums import FileType
from UnityPy.helpers import ImportHelper
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
from UnityPy.streams import EndianBinaryReader
from UnityPy.files.BundleFile import FlaggedBytesSource, FilePathBytesSource

from .models import RowItem
from .progress import OperationCancelled, CoreOperationError
from .file_utils import detect_game_paths, stream_to_file, safe_join, write_entry_safely
from .object_preview import resolve_object_name, resolve_script_name

logger = logging.getLogger("ustudio.core.cab_archive")

# Above this total decompressed size of archive contents, Import/Import All (which
# rebuild the archive ENTIRELY, including untouched entries — a limitation of the
# format itself) ask which rebuild method to use: in memory (faster, needs ~as much
# RAM) or via disk (slower, barely uses RAM, but temporarily needs ~twice as much
# disk space — see BundleFile.save_to_file()).
IMPORT_INMEMORY_WARNING_THRESHOLD = 1024 * 1024 * 1024  # 1 GB

# Above this decompressed size, "in memory" is not offered at all — it's a handful of
# large monolithic calls with no checkpoint to cancel at, so Esc/"Cancel" can only
# wait for it to finish naturally, never actually stop it early. "Via disk" does the
# work in chunks and checks should_cancel() between them — it genuinely stops within
# seconds.
IMPORT_INMEMORY_HARD_LIMIT = 4 * 1024 * 1024 * 1024  # 4 GB


def check_disk_space(total_bytes: int, target_dir, margin: float = 1.05) -> None:
    """Raises CoreOperationError if target_dir's filesystem doesn't have total_bytes
    (plus a safety margin) free — checked before starting a copy/rebuild instead of
    only failing partway through with a raw OSError."""
    required_bytes = int(total_bytes * margin)
    free_bytes = shutil.disk_usage(target_dir).free
    if free_bytes < required_bytes:
        raise CoreOperationError(
            tr("Недостаточно места на диске: требуется ~{value:.2f} ГБ, доступно {value2:.2f} ГБ.", value=required_bytes / 1024 ** 3, value2=free_bytes / 1024 ** 3)
        )


class CabArchive:
    """Wraps one open bundle (BundleFile) plus the operations available on it: list
    entries, view/export/import a single entry, export/import all, rebuild+save."""

    def __init__(self, bundle, bundle_path: str):
        self.bundle = bundle
        self.bundle_path = bundle_path
        self._env_ready = False

    @classmethod
    def open(cls, path: str) -> "CabArchive":
        typ, reader = ImportHelper.check_file_type(path)
        if typ != FileType.BundleFile:
            raise CoreOperationError(
                tr("Просмотр архива поддерживается только для бандлов Unity.")
            )
        bundle = files.BundleFile(reader, parent=None, name=path, object_count_only=True)
        return cls(bundle, path)

    def entries(self) -> List[Tuple[str, int, Optional[int]]]:
        """(name, size_bytes, object_count_or_None) per internal entry, for display."""
        result = []
        for name, f in self.bundle.files.items():
            stream = getattr(f, "reader", f)
            size = stream.Length if hasattr(stream, "Length") else 0
            result.append((name, size, getattr(f, "object_count", None)))
        return result

    def ensure_environment(self) -> None:
        """Gives the bundle a real Environment (instead of None) and, if possible, a
        typetree_generator — without this, generate_monobehaviour_node() crashes with
        AttributeError on env.typetree_generator whenever a MonoBehaviour has no
        built-in TypeTree (typically IL2CPP builds). The Managed/game-root directory
        is looked up next to the archive itself, scoped to this archive only — never
        touches any global app config."""
        if self._env_ready:
            return
        self._env_ready = True

        env = UnityPy.Environment()
        self.bundle.environment = env

        version = getattr(self.bundle, "version_engine", "") or ""
        if not version:
            return

        paths = detect_game_paths(Path(self.bundle_path))
        generator = TypeTreeGenerator(version)
        try:
            if paths["managed_dir"] and os.path.exists(paths["managed_dir"]):
                generator.load_local_dll_folder(paths["managed_dir"])
                env.typetree_generator = generator
            elif paths["game_root_dir"] and os.path.exists(paths["game_root_dir"]):
                generator.load_local_game(paths["game_root_dir"])
                env.typetree_generator = generator
        except Exception:
            # typetree_generator stays unconfigured — parsing a MonoBehaviour without
            # a built-in TypeTree will correctly fail with a clear ValueError later,
            # rather than silently here with a half-initialized generator
            pass

    def parse_entry_fully(self, name: str):
        """Fully parses the entry `name` (if not already parsed) and replaces its
        object_count_only stub in self.bundle.files with a full SerializedFile. The
        parent is set to self.bundle (not None) — PPtr.deref() resolves cross-file
        references within the bundle specifically via assetsfile.parent.files, so
        without this link back to the bundle no cross-file PPtr would resolve."""
        f = self.bundle.files[name]
        if isinstance(f, files.SerializedFile) and (f.object_count == 0 or f.objects):
            return f  # already fully parsed (or empty — nothing to parse)

        stream = getattr(f, "reader", f)
        stream.Position = 0
        raw = bytes(stream.read(stream.Length))
        reader = EndianBinaryReader(raw)
        parsed = ImportHelper.parse_file(reader, self.bundle, name)
        # File.read_files() sets .flags on every entry right after parsing it (the
        # bundle-node compression/serialization flags — required by save_fs() for
        # EVERY entry, touched or not). Re-parsing here bypasses read_files()
        # entirely, so the replacement object never gets it — real bug, caught via
        # a full Save Game Files round trip after loading one CAB entry: crashed
        # with `AttributeError: 'SerializedFile' object has no attribute 'flags'`
        # the moment save_fs() reached this entry. Carry it over from the stub
        # being replaced, which did get it (from the bundle's initial open).
        parsed.flags = getattr(f, "flags", 0)
        # Marks this entry so core/save_manager.py's _root_file() treats IT as
        # the save root, instead of walking up to self.bundle (the whole
        # original archive) the way it would for any other SerializedFile whose
        # parent is a BundleFile. Real reported request: a CAB-browser session
        # only ever fully parses the entries the user actually asked for (this
        # one, plus its declared dependencies) — "Сохранить файлы игры как..."
        # should save exactly that (this entry's own bytes, as a standalone
        # loose file), not silently expand into rebuilding the ENTIRE original
        # archive the moment ANY edit is made. See save_manager._root_file()'s
        # own comment for the other half of this.
        parsed._cab_browser_standalone_root = True
        self.bundle.files[name] = parsed
        return parsed

    def load_declared_dependencies(self, parsed_entry) -> None:
        """Loads ONLY the internal archive files that the entry actually references
        (parsed_entry.externals) — not the whole archive. Name normalization mirrors
        PPtr.deref(): strip the archive:/ and assets/ prefixes, compare case-insensitively."""
        for external in getattr(parsed_entry, "externals", None) or []:
            clean = external.path
            if clean.startswith("archive:/"):
                clean = clean[len("archive:/"):]
            if clean.startswith("assets/"):
                clean = clean[len("assets/"):]
            clean = clean.rsplit("/", 1)[-1].lower()

            for candidate_name in list(self.bundle.files.keys()):
                if candidate_name.lower() == clean:
                    self.parse_entry_fully(candidate_name)
                    break

    def view_entry(self, name: str) -> Tuple[object, Optional[List[RowItem]]]:
        """Fully parses the selected entry (plus its declared dependencies) and
        collects its MonoBehaviour objects as table rows. Returns (parsed_entry,
        rows) — rows is None when the entry isn't a SerializedFile at all (nothing to
        show as a table)."""
        self.ensure_environment()
        parsed_entry = self.parse_entry_fully(name)
        self.load_declared_dependencies(parsed_entry)

        if not hasattr(parsed_entry, "objects"):
            return parsed_entry, None

        data: List[RowItem] = []
        for obj in parsed_entry.objects.values():
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                container_path = obj.container or ""
            except Exception:
                container_path = ""
            data.append({
                "type": obj.type.name,
                "name": resolve_object_name(obj),
                "container_path": container_path,
                "script_name": resolve_script_name(obj),
                "source": obj.assets_file.name if obj.assets_file else "Unknown",
                "path_id": obj.path_id,
                "size": obj.byte_size,
                "obj_ref": obj,
            })
        return parsed_entry, data

    def export_entry(self, name: str, out_path, progress_callback=None, should_cancel=None) -> int:
        f = self.bundle.files[name]
        stream = getattr(f, "reader", f)
        if not hasattr(stream, "Length"):
            raise CoreOperationError(tr("Для этой записи нет доступных данных."))
        check_disk_space(stream.Length, Path(out_path).parent)
        return stream_to_file(stream, out_path, progress_callback=progress_callback, should_cancel=should_cancel)

    def export_all(self, dir_path, progress_callback=None, should_cancel=None) -> int:
        entries = [
            (name, stream) for name, f in self.bundle.files.items()
            if hasattr(stream := getattr(f, "reader", f), "Length")
        ]
        total_bytes = sum(stream.Length for _, stream in entries)
        check_disk_space(total_bytes, dir_path)

        exported = 0
        cumulative = 0
        for name, stream in entries:
            if should_cancel is not None and should_cancel():
                raise OperationCancelled()
            base = cumulative
            write_entry_safely(
                stream, dir_path, name,
                progress_callback=(
                    (lambda done, _tot, base=base: progress_callback(base + done, total_bytes))
                    if progress_callback else None
                ),
                should_cancel=should_cancel,
            )
            cumulative += stream.Length
            exported += 1
        if progress_callback:
            progress_callback(total_bytes, total_bytes)
        return exported

    def match_files_for_import(self, dir_path) -> Dict[str, str]:
        """Filename-only match of self.bundle.files against files physically present
        in dir_path — used by import_all. safe_join rejects an entry name that would
        resolve outside dir_path (".." segments, an absolute path) instead of
        silently matching whatever happens to live there; one bad name is just
        skipped, not a reason to abort the whole match pass."""
        replacements = {}
        for name in self.bundle.files.keys():
            try:
                candidate = safe_join(dir_path, name)
            except ValueError:
                continue
            if candidate.is_file():
                replacements[name] = str(candidate)
        return replacements

    @staticmethod
    def find_import_all_collisions(replacements: Dict[str, str]) -> List[Tuple[str, str, str]]:
        """Windows filesystems are case-insensitive, so two DIFFERENT archive entry
        names differing only by case can both resolve to the SAME physical file here
        — meaning the same content would silently get packed into two logically
        distinct entries. Returns (first_name, second_name, path) triples, one per
        collision, for the caller to confirm with the user before proceeding."""
        by_resolved_path: Dict[str, str] = {}
        collisions = []
        for name, path in replacements.items():
            key = os.path.normcase(os.path.abspath(path))
            if key in by_resolved_path:
                collisions.append((by_resolved_path[key], name, path))
            else:
                by_resolved_path[key] = name
        return collisions

    def rebuild_and_save(
        self, out_path, replacements: Dict[str, str], mode: str, packer: str,
        progress_callback=None, should_cancel=None,
    ) -> int:
        """Rebuilds the WHOLE archive (an inherited limitation of
        BundleFile.save()/save_to_file(), not this wrapper) substituting
        `replacements` (entry name -> local file path) for those specific entries,
        and writes the result to out_path. mode is "memory" (bundle.save(), fast, but
        effectively uncancellable — no checkpoint inside it) or "disk"
        (bundle.save_to_file(), slower, minimal RAM, genuinely cancellable); the
        caller decides which (the GUI asks the user above
        IMPORT_INMEMORY_WARNING_THRESHOLD, forces "disk" above
        IMPORT_INMEMORY_HARD_LIMIT — a console front end might just always pick "disk").

        Both replaced AND untouched entries are lightweight, lazy wrappers here —
        nothing is read until save()/save_to_file() itself streams through each entry."""
        entries = list(self.bundle.files.items())
        new_files = {}
        for name, f in entries:
            if name in replacements:
                new_files[name] = FilePathBytesSource(replacements[name], getattr(f, "flags", 0))
            else:
                stream = getattr(f, "reader", f)
                new_files[name] = FlaggedBytesSource(stream, getattr(f, "flags", 0))

        # temporarily swap self.bundle.files for the prepared entries just for
        # saving, so that after the operation the original per-entry readers stay
        # working for further View/Export/Import without needing to reopen the archive
        original_files = self.bundle.files
        try:
            self.bundle.files = new_files
            if mode == "disk":
                self.bundle.save_to_file(
                    out_path, packer=packer,
                    should_cancel=should_cancel,
                    progress_callback=progress_callback,
                )
            else:
                out_bytes = self.bundle.save(packer=packer)
                with open(out_path, "wb") as out:
                    out.write(out_bytes)
        finally:
            self.bundle.files = original_files
        return len(replacements)
