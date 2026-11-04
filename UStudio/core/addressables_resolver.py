"""Resolving a cross-bundle CAB reference across an Addressables-style folder of many
`.bundle` files (Unity's own `StreamingAssets/aa/<Platform>/` layout, or any folder
sharded the same way) — real reported case: `Environment.find_file()`'s own fallback
(see `UnityPy/environment.py`) only ever looks for a LOOSE file on disk whose name
matches the missing cab — the layout loose multi-file games actually use, where a real
dependency genuinely is its own file. Addressables splits shared assets (MonoScripts in
particular — every script referenced by any asset in the build lands in one shared
`*_monoscripts.bundle`, separate from the hundreds/thousands of asset bundles that
reference them) into a CAB entry *inside another bundle* instead — something
`find_file()` was never built to search for, so a MonoBehaviour whose script bundle
wasn't loaded shows "Unknown" in the Script column, and "Jump to object"/"Перейти к
объекту" on its `m_Script` PPtr fails with "File cab-... not found in ...".

Confirmed on the real fixture this was reported against (`Lego party/LEGO Party_Data/
StreamingAssets/aa/StandaloneWindows64/`, 1487 bundles): the missing
`CAB-c86d757d39e57e54aa43c03130827bdd` genuinely lives inside
`95c21c97e76c71a44ac4808c89b16a25_monoscripts.bundle`, a sibling of whatever single
bundle the user had actually loaded.

CabIndex maps a simplified cab name to the bundle file that contains it, built by
opening every bundle in a folder tree with `object_count_only=True` (the same
near-free "read only the header/directory block, never decompress a data block" mode
`bundle_inspector.quick_scan_bundle_contents()` already uses elsewhere in this
project) — confirmed by direct measurement against the real 1487-bundle fixture: 28.5s
total, 19ms/bundle average, zero errors, zero full decompression. Not exposed to the
regular load path automatically (that would silently add up to ~30s, worse for a
bigger Addressables build, to any StreamingAssets-folder load) — see
core/loader.py::_scan_and_confirm() for the *free* path (folding cab names into the
per-file quick scan that folder-mode loads already do) and
dialogs/addressables_resolver_dialog.py for the explicit, user-triggered path (the only
option when just one bundle was loaded, as in the report — a single-file/single-bundle
load has no whole-folder scan to piggyback on)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

from UnityPy import files
from UnityPy.enums import FileType
from UnityPy.environment import Environment, simplify_name
from UnityPy.helpers.ImportHelper import check_file_type

from .progress import ProgressThrottle

logger = logging.getLogger(__name__)

CancelCheck = Optional[Callable[[], bool]]
ProgressCallback = Optional[Callable[[int, int, str], None]]  # (current, total, current_path)


@dataclass
class CabIndex:
    """{simplified cab name: absolute bundle path}, plus enough bookkeeping to show a
    useful summary and to grow incrementally (see add_bundle()) instead of only ever
    being built in one full pass."""

    entries: Dict[str, str] = field(default_factory=dict)
    bundles_scanned: int = 0
    bundles_with_cabs: int = 0
    scan_errors: int = 0
    roots: List[str] = field(default_factory=list)  # every folder this index has scanned, for display

    def add_bundle(self, bundle_path: str, cab_names: Iterable[str]) -> None:
        """Records one candidate file's own internal cab names — bundles_scanned
        counts every call (even with an empty cab_names, e.g. a plain non-bundle
        file that was still successfully looked at and found to have none), while
        bundles_with_cabs only counts a call that actually added something NEW.
        `entries` keeps the FIRST bundle seen for a given cab name — same
        "keep_first" default this project's own cab_collision_policy already uses
        elsewhere, and harmless here regardless: two different bundles genuinely
        sharing one cab name would mean the SAME source asset got included in both
        (a real, if unusual, Addressables build situation), and either bundle
        resolves the reference correctly."""
        self.bundles_scanned += 1
        added = False
        for cab_name in cab_names:
            key = simplify_name(cab_name)
            if key not in self.entries:
                self.entries[key] = bundle_path
                added = True
        if added:
            self.bundles_with_cabs += 1

    def find(self, cab_name: str) -> Optional[str]:
        return self.entries.get(simplify_name(cab_name))

    def __contains__(self, cab_name: str) -> bool:
        return self.find(cab_name) is not None


def list_bundle_cab_names(path: str) -> List[str]:
    """The internal cab entry names a single bundle file declares, read from its
    directory/header block only — `object_count_only=True` skips every SerializedFile's
    own object table too (see UnityPy/files/SerializedFile.py), but that's moot here:
    this function never looks at `bundle.files`' values, only its keys. Returns []
    for a file that isn't a BundleFile at all (a loose `.assets`, a non-Unity file
    that happens to sit in the same folder, ...) rather than raising — callers scanning
    a whole folder need to skip those silently, matching this project's own established
    "a bad/irrelevant file skips itself, it doesn't abort the whole scan" precedent
    (see CLAUDE.md's Fixed Bugs #15)."""
    typ, reader = check_file_type(path)
    if typ != FileType.BundleFile:
        return []
    bundle = files.BundleFile(reader, parent=None, name=path, object_count_only=True)
    return list(bundle.files.keys())


def build_cab_index_for_folder(
    root_dir: str,
    progress_cb: ProgressCallback = None,
    should_cancel: CancelCheck = None,
    index: Optional[CabIndex] = None,
) -> CabIndex:
    """Scans every regular file under root_dir (recursively — Addressables groups can
    nest bundles a level or two deep) and indexes each one's own cab names via
    list_bundle_cab_names(). `index` lets a caller extend an already-built index (e.g.
    the session's free one from a prior folder load) instead of starting over.

    progress_cb(current, total, current_path) is throttled the same way every other
    multi-second scan in this project already is (ProgressThrottle — object indexing,
    text search, bulk export; see gui_workers.py's own module docstring) rather than
    firing once per file, which at Addressables scale (thousands of files) would flood
    the GUI thread's event queue exactly like the compression-chunk progress flood
    documented elsewhere in this project's history."""
    result = index if index is not None else CabIndex()
    result.roots.append(root_dir)

    candidates = []
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for fn in filenames:
            candidates.append(os.path.join(dirpath, fn))
    total = len(candidates)

    throttle = ProgressThrottle()
    for i, path in enumerate(candidates):
        if should_cancel is not None and should_cancel():
            break
        if progress_cb is not None and throttle.should_report(i, total):
            progress_cb(i + 1, total, path)
            throttle.pause()
        try:
            cab_names = list_bundle_cab_names(path)
        except Exception as e:
            result.scan_errors += 1
            logger.debug("Addressables cab scan: skipping %s (%s: %s)", path, type(e).__name__, e)
            continue
        # Unconditional (not "only if cab_names") — bundles_scanned should count every
        # candidate file this scan actually looked at without erroring, matching what
        # a progress/summary UI means by "scanned N files"; add_bundle() itself already
        # keeps bundles_with_cabs as the separate "of those, N were real bundles with
        # CAB entries" count (it only increments that when something was actually
        # added), so nothing here loses that distinction.
        result.add_bundle(path, cab_names)

    return result


def resolve_via_index(environment: Environment, index: CabIndex, cab_name: str) -> Optional[str]:
    """Looks `cab_name` up in `index` and, if found, loads its bundle into `environment`
    (a plain `load_file()` — the exact same call an ordinary loose-dependency
    resolution already ends in, via find_file(); see that function's own docstring in
    UnityPy/environment.py) unless it's already registered. Returns the bundle path
    that was used (whether just-loaded or already present), or None if the cab isn't
    in this index at all.

    Deliberately does not pre-check the winning bundle's own size before loading it —
    the ordinary loose-file dependency path (find_file()'s ultimate self.load_file()
    call) has never had a size gate either; an Addressables shared-asset bundle
    (scripts, shaders, built-in assets) is typically small (confirmed: the real
    monoscripts.bundle from this session's own fixture is 142 KB, loads fully in well
    under half a second), but nothing here assumes that in general — a reference
    into a genuinely large asset bundle would load that whole bundle, exactly as
    loading it directly from the table already would."""
    bundle_path = index.find(cab_name)
    if bundle_path is None:
        return None
    key = simplify_name(cab_name)
    if environment.get_cab(key) is None:
        environment.load_file(bundle_path, is_dependency=True)
    return bundle_path


__all__ = [
    "CabIndex",
    "list_bundle_cab_names",
    "build_cab_index_for_folder",
    "resolve_via_index",
]
