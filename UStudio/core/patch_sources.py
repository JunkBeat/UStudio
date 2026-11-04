"""Which physical files a set of patches actually needs loaded.

A patch filename names its target as "... #{path_id} ({source})" — and `source`
is a SERIALIZED FILE's name: a loose file's basename ("level0",
"sharedassets0.assets") or a bundle's internal entry ("CAB-…", "level0" inside
data.unity3d). To import a handful of patches there's no need to load a whole
game folder: this maps each wanted source to the one file that holds it, so a
caller can load just those. Everything else the load might need (a MonoScript
in another file, a .resS resource) is pulled in lazily from the folder by the
Environment, the same as in a full load.

The mapping is conservative on purpose — it answers "exactly one file holds
this source" or it says why it can't (PatchSourceResolution.ok is False) and the
caller is expected to fall back to loading everything, never to guess:
  - a source no file provides,
  - a source that several files provide (a game folder with a backup mirror;
    a full load has its own cab-collision policy for that, this doesn't),
  - a bundle that couldn't be listed (encrypted/unsupported — the source might
    be inside it),
  - a wanted file that is a .splitN part (the loader merges those itself).

Sources are compared in SANITIZED form — a patch filename only carries
sanitize_export_filename()'s output, which isn't invertible, so two real names
that sanitize to the same thing count as one source and (if in different files)
as ambiguous.

PyQt-free, like the rest of core/."""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set

from UnityPy.environment import reSplit as _RE_SPLIT_FILE
from UnityPy.helpers import ImportHelper

from .cab_archive import CabArchive
from .gc_freeze import collect_everything
from .object_preview import sanitize_export_filename

logger = logging.getLogger("ustudio.patch_sources")

# What check_file_type() compares the signature (up to the first NUL) against to
# decide "BundleFile" — equality, not startswith: "UnityWebData1.0" is a WebFile.
_BUNDLE_SIGNATURES = frozenset({b"UnityFS", b"UnityWeb", b"UnityRaw", b"UnityArchive"})


@dataclass
class PatchSourceResolution:
    files: List[str] = field(default_factory=list)          # distinct files to load, in scan order
    unresolved: List[str] = field(default_factory=list)     # wanted sources no file provides
    ambiguous: Dict[str, List[str]] = field(default_factory=dict)  # source -> the several files providing it
    unreadable_bundles: List[str] = field(default_factory=list)    # bundles whose entries couldn't be listed
    unsupported: List[str] = field(default_factory=list)    # sources only provided by a .splitN file
    files_scanned: int = 0

    @property
    def ok(self) -> bool:
        return not (self.unresolved or self.ambiguous or self.unreadable_bundles or self.unsupported)

    def why_not(self) -> str:
        """One line per reason partial loading isn't possible ("" when it is)."""
        parts = []
        if self.unresolved:
            parts.append("no file provides: " + ", ".join(sorted(self.unresolved)))
        for source, paths in sorted(self.ambiguous.items()):
            parts.append(f"'{source}' is provided by several files: " + ", ".join(paths))
        if self.unreadable_bundles:
            parts.append("could not list the entries of: " + ", ".join(self.unreadable_bundles))
        if self.unsupported:
            parts.append("split (.splitN) files are not handled: " + ", ".join(sorted(self.unsupported)))
        return "; ".join(parts)


def _is_bundle_file(path: str) -> bool:
    """Signature sniff by plain read — deliberately NOT ImportHelper.check_file_type():
    that mmaps the file, and a lingering mmap keeps it locked on Windows, which would
    later block an --in-place overwrite of the very file just scanned."""
    try:
        with open(path, "rb") as f:
            head = f.read(20)
    except OSError:
        return False
    return len(head) > 8 and head.split(b"\0", 1)[0] in _BUNDLE_SIGNATURES


def _bundle_entry_names(path: str) -> List[str]:
    return [name for name, _size, _count in CabArchive.open(path).entries()]


def _excluded(path: str, excluded_norm: List[str]) -> bool:
    # Same rule core.loader.EnvironmentLoader._load_folder applies to a folder
    # load's file list — a scan that disagreed about what's excluded would
    # resolve sources to files the real load would never have seen.
    norm = os.path.normcase(os.path.abspath(path))
    return any(norm == ex or norm.startswith(ex + os.sep) for ex in excluded_norm)


def resolve_patch_sources(
    root: str,
    wanted_sources: Iterable[str],
    excluded_folders: Iterable[str] = (),
) -> PatchSourceResolution:
    """Maps every wanted (sanitized) source name to the file under `root` that
    holds it. Loose files are matched by basename; bundles are opened just far
    enough to list their entries (object_count_only — the same cheap read the
    CAB browser uses), and only files whose first bytes are a bundle signature
    are opened at all."""
    wanted: Set[str] = set(wanted_sources)
    result = PatchSourceResolution()

    paths = ImportHelper.list_all_files(root)
    excluded_norm = [os.path.normcase(os.path.abspath(f)) for f in excluded_folders]
    if excluded_norm:
        paths = [p for p in paths if not _excluded(p, excluded_norm)]
    result.files_scanned = len(paths)

    providers: Dict[str, List[str]] = {}   # sanitized source -> distinct files providing it

    def _provide(source: str, path: str) -> None:
        holders = providers.setdefault(source, [])
        if path not in holders:
            holders.append(path)

    split_hits: Set[str] = set()
    for path in paths:
        split = _RE_SPLIT_FILE.match(path)
        if split:
            base = sanitize_export_filename(os.path.basename(split.group(1)), fallback="unknown")
            if base in wanted:
                split_hits.add(base)
            continue

        base = sanitize_export_filename(os.path.basename(path), fallback="unknown")
        if base in wanted:
            _provide(base, path)

        if _is_bundle_file(path):
            try:
                names = _bundle_entry_names(path)
            except Exception as e:  # noqa: BLE001 - any unreadable bundle just disables the fast path
                logger.debug("cannot list bundle %s: %s", path, e)
                result.unreadable_bundles.append(os.path.basename(path))
                continue
            for name in names:
                sanitized = sanitize_export_filename(name, fallback="unknown")
                if sanitized in wanted:
                    _provide(sanitized, path)

    # Bundles were opened with mmap; drop them now (the object graph has cycles)
    # rather than leave the files locked until some later collection.
    collect_everything()

    for source in sorted(wanted):
        holders = providers.get(source, [])
        if source in split_hits and not holders:
            result.unsupported.append(source)
        elif not holders:
            result.unresolved.append(source)
        elif len(holders) > 1:
            result.ambiguous[source] = holders
        elif holders[0] not in result.files:
            result.files.append(holders[0])
    return result
