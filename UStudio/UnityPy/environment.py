import hashlib
import io
import logging
import mmap
import ntpath
import os
import re
import threading
from typing import TYPE_CHECKING, BinaryIO, Callable, Dict, List, NamedTuple, Optional, Tuple, Union, cast
from zipfile import ZipFile

logger = logging.getLogger("UnityPy.environment")

from fsspec import AbstractFileSystem
from fsspec.implementations.local import LocalFileSystem

from .enums import FileType
from .exceptions import CabNameCollisionError
from .files import BundleFile, File, ObjectReader, SerializedFile, WebFile
from .helpers.ContainerHelper import ContainerHelper
from .helpers.ImportHelper import (
    FileSourceType,
    check_file_type,
    find_sensitive_path,
    parse_file,
)
from .streams import EndianBinaryReader

if TYPE_CHECKING:
    from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

reSplit = re.compile(r"(.*?([^\/\\]+?))\.split\d+")


class Environment:
    files: Dict[str, Union[SerializedFile, BundleFile, WebFile, EndianBinaryReader]]
    cabs: Dict[str, Union[SerializedFile, EndianBinaryReader]]
    path: str
    local_files: List[str]
    local_files_simple: List[str]
    typetree_generator: Optional["TypeTreeGenerator"] = None
    _container_index_built: bool = False

    def __init__(self, *args: FileSourceType, fs: Optional[AbstractFileSystem] = None, path: Optional[str] = None):
        self.files = {}
        self.cabs = {}
        self.fs = fs or LocalFileSystem()
        self.local_files = []
        self.local_files_simple = []
        self._container_index_built = False
        # find_file() misses (a dependency genuinely not present anywhere in this
        # environment) are re-paid on every single reference to that same missing name —
        # each miss does an fs.exists() stat plus up to two full O(n) scans of
        # local_files/local_files_simple before giving up. A shared missing dependency
        # referenced from many objects (common at this project's hard-case object counts)
        # would otherwise repeat that full scan every time. Mirrors AssetStudioGUI's
        # noexistFiles: a plain set of names already confirmed absent, short-circuiting
        # find_file() at zero cost on a repeat miss.
        self._missing_files: set = set()
        # Guards the cold-populate of local_files/local_files_simple (below) and
        # _missing_files above — real, confirmed bug (not theoretical): this app
        # calls find_file() from both the GUI thread (bulk MonoBehaviour script-name
        # resolution, e.g. activating a script-restricted Quick Filter) and a
        # background worker thread (SDF-font-atlas generation, which parses a
        # TMP_FontAsset — itself a MonoBehaviour-classed object) concurrently, with
        # no synchronization at all before this fix. Two threads both seeing
        # `len(self.local_files) == 0` and independently re-walking self.fs.walk()
        # to populate BOTH lists desynchronizes their index correspondence (each
        # thread appends its OWN walk's entries to the SAME two shared lists), so
        # `self.local_files[self.local_files_simple.index(simple_name)]` below can
        # return the WRONG file for a given name — reproduced directly: concurrent
        # find_file()-driving calls (via PPtr.deref()/TypeTreeGenerator resolution)
        # against a real fixture produced `EOFError: read_str out of bounds`,
        # garbage PathID KeyErrors, and "Negative length read from TypeTree" within
        # under a minute — the same corruption family that, at real-game object
        # counts and given unlucky timing, escalates into a genuine out-of-bounds
        # memory access (a Windows access violation, not just a Python exception).
        self._find_file_lock = threading.Lock()
        # content_signature() -> name of the top-level file first loaded with that content.
        # Lets load_file() recognize the same physical file arriving under a different path
        # (duplicate copy, sibling extracted/ folder, etc.) and skip re-parsing it.
        self._content_signatures: Dict[Tuple[int, bytes], str] = {}
        # Identical files have identical sizes, so a file is only hashed once ANOTHER file of its size turns up:
        # the first file of each size waits here as (stream_name, path on disk) and is hashed from that path then
        # (a path, not the loaded memoryview: holding the view would keep the file mapped). Lego Party: 1,517
        # files, 3 GB of head+tail reads before, now only the few same-sized ones.
        self._unhashed_by_size: Dict[int, Tuple[str, str]] = {}
        self._hashed_sizes: set = set()
        # (skipped_name, kept_name) pairs for every duplicate load_file() skipped this way —
        # callers can surface this to the user; the library itself stays silent by default.
        self.skipped_duplicates: List[Tuple[str, str]] = []

        # simplify_name(name) -> the full stream_name currently holding that cab slot.
        # Lets register_cab() tell "the same path re-registering itself" (reload after
        # save/import — expected, not a collision) apart from "two DIFFERENT files whose
        # names happen to reduce to the same basename" (a real collision — see CabCollision).
        self._cab_source_names: Dict[str, str] = {}
        # One entry per detected name collision (both files are still fully loaded into
        # self.files/self.assets — this only affects which one wins name-based lookups
        # like find_file()/container). "keep_first" (default) / "keep_last" resolve this
        # automatically; a caller can review/override afterwards via this list. "raise"
        # aborts the load instead (CabNameCollisionError) — the file being registered
        # when the collision is hit never gets added to self.files/self.cabs.
        self.name_collisions: List["CabCollision"] = []
        # simplify_name(name) -> {registered source name: item} for EVERY source ever
        # registered under that key, including the ones a collision policy did not let
        # take the cab slot. get_cab_near() uses it to give an assets file the resource
        # (.resS/.resource) sitting closest to it instead of whichever won the slot.
        self._cab_alternatives: Dict[str, Dict[str, object]] = {}
        # Paths load_file() must open even though their content signature matches an
        # already-loaded file — see _promote_near_duplicates().
        self._dedup_bypass: set = set()
        self._promote_done: set = set()
        self._source_path_cache: Dict[int, Optional[str]] = {}
        self.cab_collision_policy: str = "keep_first"  # "keep_first" | "keep_last" | "raise"

        # Last-resort hook for find_file() (below): a caller-supplied
        # `name -> bundle_path or None` function, tried only after this
        # environment's own loose-file search (self.local_files) has already come up
        # empty. Left unset by default — every environment that never opts in behaves
        # exactly as before. Exists because a reference can legitimately be a CAB
        # entry living INSIDE some other file rather than its own loose file on disk
        # at all (real, reported case: Unity Addressables splits shared assets —
        # MonoScripts especially — into dedicated sibling `.bundle` files, e.g.
        # `<hash>_monoscripts.bundle`, that the asset bundles referencing them never
        # themselves declare as `externals`/dependencies in a way find_file()'s own
        # loose-file search could ever match). This class deliberately doesn't know
        # HOW to build such an index itself (that's app-level policy — see this
        # project's own core/addressables_resolver.py for one implementation) — it
        # only provides the one hook point every reference resolution already funnels
        # through (PPtr.deref()'s own fallback calls find_file() directly).
        self.external_cab_resolver: Optional[Callable[[str], Optional[str]]] = None

        # find_file() populates local_files by walking self.path. Recursive by
        # default (a game's data folder legitimately nests dependencies), but a
        # caller whose self.path is just "the folder some loose file happened to sit
        # in" must turn this off: real reported bug — loading one resources.assets
        # from a folder holding many unrelated games recursively found (and silently
        # used) another game's globalgamemanagers for script names.
        self.local_search_recursive: bool = True

        if path is None:
            # if no path is given, use the current working directory
            if isinstance(self.fs, LocalFileSystem):
                self.path = os.getcwd()
            else:
                self.path = ""
        else:
            self.path = path

        if args:
            for arg in args:
                if isinstance(arg, str):
                    if self.fs.isfile(arg):
                        if ntpath.splitext(arg)[-1] in [".apk", ".zip"]:
                            self.load_zip_file(arg)
                        else:
                            self.path = ntpath.dirname(arg) or ntpath.curdir
                            if reSplit.match(arg):
                                self.load_files([arg])
                            else:
                                self.load_file(arg)
                    elif self.fs.isdir(arg):
                        self.path = arg
                        self.load_folder(arg)
                else:
                    self.load_file(file=arg)

        if len(self.files) == 1:
            self.file = list(self.files.values())[0]

    def close_file(self, name: str) -> None:
        """Unloads a specific file and clears its block cache."""
        if name in self.files:
            del self.files[name]
        key = simplify_name(name)
        self.cabs.pop(key, None)
        if self._cab_source_names.get(key) == name:
            del self._cab_source_names[key]
        self._cab_alternatives.get(key, {}).pop(name, None)
        self._source_path_cache.clear()
        from .files.BundleFile import clear_bundle_cache
        clear_bundle_cache(name)
        self._container_index_built = False

    def load_files(self, files: List[str], type_filters: Optional[Dict[str, set]] = None, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """Loads all files (list) into the Environment and merges .split files for common usage."""
        self.load_assets(files, lambda x: x, type_filters=type_filters, progress_callback=progress_callback)

    def load_folder(self, path: str, type_filters=None, progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """Loads all files in the given path and its subdirs into the Environment."""
        all_files = [self.fs.sep.join([root, f]) for root, dirs, files in self.fs.walk(path) for f in files]
        self.load_files(all_files, type_filters=type_filters, progress_callback=progress_callback)

    def load(self, files: List[str]):
        """Loads all files into the Environment."""
        self.files.update(
            {ntpath.basename(f): self.load_file(self.fs.open(f, "rb"), self, f) for f in files if self.fs.exists(f)}
        )

    def _load_split_file(self, basename: str) -> bytes:
        file: List[bytes] = []
        for i in range(0, 999):
            item = f"{basename}.split{i}"
            if self.fs.exists(item):
                with self.fs.open(item, "rb") as f:
                    file.append(f.read())  # type: ignore
            elif i:
                break
        return b"".join(file)

    def _dedup_signature(self, file, stream_name: str) -> Optional[Tuple[int, bytes]]:
        """content_signature(file) when it can matter, else None ("nothing to compare with"). The first file of
        a size is not hashed: it is remembered by path (when it has one on disk) and hashed only when a second
        file of the same size arrives — the same signatures, so the same duplicates, as hashing every file."""
        size = content_size(file)
        if size is None:
            return content_signature(file)
        pending = self._unhashed_by_size.pop(size, None)
        if pending is not None:
            first_name, first_path = pending
            try:
                with open(first_path, "rb") as source:
                    first_signature = content_signature(source)
            except OSError:
                first_signature = None
            if first_signature is not None:
                self._content_signatures.setdefault(first_signature, first_name)
            self._hashed_sizes.add(size)
        if size in self._hashed_sizes:
            return content_signature(file)
        if isinstance(stream_name, str) and os.path.isfile(stream_name):
            self._unhashed_by_size[size] = (stream_name, stream_name)
            return None
        self._hashed_sizes.add(size)
        return content_signature(file)

    def load_file(
        self,
        file: FileSourceType,
        parent: Optional[Union["Environment", File]] = None,
        name: Optional[str] = None,
        is_dependency: bool = False,
        type_filter=None,
        progress_callback=None
    ):
        if not parent:
            parent = self

        if isinstance(file, str):
            split_match = reSplit.match(file)
            if split_match:
                basepath, _basename = split_match.groups()
                assert isinstance(basepath, str)
                # Real bug fixed here: this unconditionally overwrote an
                # explicitly-passed `name` argument with a name derived from
                # `file` — meaning the `name` parameter this method's own
                # signature documents as an override was silently dead
                # whenever `file` is a plain string (the common case), not
                # just for bytes/buffer inputs where it was actually reached.
                # Confirmed via core.object_preview.import_object_content_raw's
                # own real bug (a live report against a real fixture): its
                # reload call needs to open a resolved absolute PATH while
                # registering under the resource's ALREADY-canonical name
                # (bare or absolute, whichever won the cab slot at initial
                # load) — passing both `file` and `name` only works if this
                # method actually respects `name` when given.
                if name is None:
                    name = basepath
                file = self._load_split_file(basepath)
            else:
                if name is None:
                    name = file
                if not os.path.exists(file):
                    # relative paths are in the asset directory, not the cwd
                    if not os.path.isabs(file):
                        file = os.path.join(self.path, file)
                    # for dependency loading of split files
                    if os.path.exists(f"{file}.split0"):
                        file = self._load_split_file(file)
                    # Unity paths are case insensitive,
                    # so we need to find "Resources/Foo.asset" when the record says "resources/foo.asset"
                    elif not os.path.exists(file):
                        file_path = find_sensitive_path(self.path, file)
                        if file_path:
                            file = file_path
                        else:
                            return None
                            # raise FileNotFoundError(f"File {file} not found in {self.path}")

                if isinstance(file, str):
                    file = self.fs.open(file, "rb")
                    try:
                        fd = file.fileno()
                    except (AttributeError, io.UnsupportedOperation):
                        pass
                    else:
                        try:
                            mm = mmap.mmap(fd, 0, access=mmap.ACCESS_READ)
                        except (ValueError, OSError):
                            pass
                        else:
                            file.close()
                            file = memoryview(mm)

        stream_name = (
            name
            if name
            else getattr(
                file,
                "name",
                str(file.__hash__()) if hasattr(file, "__hash__") else "",  # type: ignore
            )
        )

        if stream_name in self._dedup_bypass:
            pass
        elif stream_name in self.files:
            # a file at this path was already opened before — it may have changed on disk
            # (after save/import or a manual reload) — reset its block cache
            from .files.BundleFile import clear_bundle_cache
            clear_bundle_cache(stream_name)
        else:
            # Not a reload of a path we already know — check whether this is the SAME
            # content arriving under a DIFFERENT path (duplicate copy, a sibling
            # _extracted/ folder re-scanned alongside the bundle it came from, a mod
            # install overlapping the base game, ...). content_signature() only samples
            # ~2MB regardless of file size, so this is cheap even for multi-GB bundles.
            signature = self._dedup_signature(file, stream_name)
            if signature is not None:
                existing_name = self._content_signatures.get(signature)
                if existing_name is not None and existing_name in self.files:
                    self.skipped_duplicates.append((stream_name, existing_name))
                    # DEBUG, not print(): a library shouldn't write to stdout as a
                    # side effect, and callers that care about this (e.g. this
                    # project's own app) already get a cleaner, deduplicated summary
                    # from self.skipped_duplicates after the load finishes rather than
                    # one line per event during it.
                    logger.debug("Skipping %r: identical content already loaded as %r", stream_name, existing_name)
                    return self.files[existing_name]
                self._content_signatures[signature] = stream_name

        typ, reader = check_file_type(file)

        if typ == FileType.ZIP:
            f = self.load_zip_file(file)
        else:
            f = parse_file(reader, self, name=stream_name, typ=typ, is_dependency=is_dependency,
                           type_filter=type_filter, progress_callback=progress_callback)

        if isinstance(f, (SerializedFile, EndianBinaryReader)):
            self.register_cab(stream_name, f)

        self.files[stream_name] = f
        return f

    def load_zip_file(self, value):
        if isinstance(value, str) and self.fs.exists(value):
            buffer = cast(io.BufferedReader, self.fs.open(value, "rb"))
        elif isinstance(value, (bytes, bytearray, memoryview)):
            buffer = io.BytesIO(value)
        elif isinstance(value, (io.BufferedReader, io.BufferedIOBase)):
            buffer = value
        else:
            raise TypeError("Unsupported type for loading zip file")

        z = ZipFile(buffer)

        def load_internal_file(name: str):
            # decode directly first, as the io calls will otherwise be extremely slow
            file_data = z.open(name, "r").read()
            return io.BytesIO(file_data)

        self.load_assets(z.namelist(), load_internal_file)
        z.close()

    def save(self, pack="none", out_path="output"):
        """Saves all changed assets.
        Mark assets as changed using `.mark_changed()`.

        ``pack`` is forwarded as ``packer`` to each file's ``save()``.
        Supported values depend on the file type, for example:
            BundleFile - "none", "lz4", "lz4hc", "lzma", "original"
            WebFile - "none", "gzip", "brotli"
        """
        for fname, fitem in self.files.items():
            if getattr(fitem, "is_changed", False):
                with open(self.fs.sep.join([out_path, ntpath.basename(fname)]), "wb") as out:
                    out.write(fitem.save(packer=pack))

    @property
    def objects(self) -> List[ObjectReader]:
        """Returns a list of all objects in the Environment."""

        def search(item):
            ret = []
            if not isinstance(item, Environment) and getattr(item, "objects", None):
                # serialized file
                if getattr(item, "is_dependency", False):
                    return []
                return [val for val in item.objects.values()]

            elif getattr(item, "files", None):  # WebBundle and BundleFile
                # bundle
                for sub_item in item.files.values():
                    ret.extend(search(sub_item))
                return ret

            return ret

        return search(self)

    def _build_container_index(self) -> None:
        if self._container_index_built:
            return

        self._container_index_built = True
        for f in self.cabs.values():
            if isinstance(f, SerializedFile):
                f.container.parse_preload_table()

    @property
    def container(self) -> ContainerHelper:
        """Returns a dictionary of all objects in the Environment."""
        self._build_container_index()
        container = []
        for f in self.cabs.values():
            if isinstance(f, SerializedFile) and not f.is_dependency:
                container.extend(f.container.container)

        return ContainerHelper(container)

    @property
    def assets(self) -> list:
        """
        Lists all assets / SerializedFiles within this environment.
        """

        def gen_all_asset_files(file, ret: Optional[list] = None):
            if ret is None:
                ret = []

            for f in getattr(file, "files", {}).values():
                if getattr(f, "is_dependency", False):
                    continue
                if isinstance(f, SerializedFile):
                    ret.append(f)
                else:
                    gen_all_asset_files(f, ret)
            return ret

        return gen_all_asset_files(self)

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def apply_collision_winner(self, collision: "CabCollision", keep_rejected: bool) -> None:
        """Overrides an already-resolved CabCollision (from self.name_collisions) after
        the fact — e.g. after the user reviews it in a UI dialog. keep_rejected=True
        swaps the cab slot over to collision.rejected_item/rejected_name; False is a
        no-op (the collision's kept_* side is already what's registered)."""
        if not keep_rejected:
            return
        key = collision.key
        self.cabs[key] = collision.rejected_item
        self._cab_source_names[key] = collision.rejected_name
        self._container_index_built = False

    def register_cab(self, name: str, item: Union[SerializedFile, EndianBinaryReader]) -> None:
        """
        Registers a cab file.

        Parameters
        ----------
        name : str
            The name of the cab file.
        item : File
            The file to register.
        """
        key = simplify_name(name)
        existing_name = self._cab_source_names.get(key)
        self._cab_alternatives.setdefault(key, {})[name] = item

        if existing_name is not None and existing_name != name:
            # Two DIFFERENT source files reduce to the same cab key (e.g. two files both
            # named "level0" — one from the game, one from a backup/mod folder, or two
            # separate bundles that each have their own internal "sharedassets0.assets").
            # Plain dict assignment here would silently pick whichever loaded last —
            # an order that depends on fs.walk()/bundle entry order, not anything
            # meaningful — and every later name-based lookup (find_file(), the
            # `container` property) would only ever see that one. Resolve it via an
            # explicit, visible policy instead.
            if self.cab_collision_policy == "raise":
                raise CabNameCollisionError(key, existing_name, name)

            existing_item = self.cabs.get(key)
            if self.cab_collision_policy == "keep_last":
                self.name_collisions.append(CabCollision(key, name, item, existing_name, existing_item))
                # DEBUG, not print() — same reasoning as the duplicate-skip case
                # above: this project's own app reports these from
                # Environment.name_collisions in its own, nicer summary once loading
                # finishes, rather than needing a line printed per event live.
                logger.debug("Cab name collision on %r: keeping %r over %r (policy=keep_last)", key, name, existing_name)
            else:
                # "keep_first" (default). Also what an unrecognized/"ask" policy falls
                # back to — interactive re-resolution of these is meant to happen after
                # loading finishes (via Environment.name_collisions), not mid-parse.
                self.name_collisions.append(CabCollision(key, existing_name, existing_item, name, item))
                logger.debug(
                    "Cab name collision on %r: keeping %r over %r (policy=%s)",
                    key, existing_name, name, self.cab_collision_policy,
                )
                return

        self._cab_source_names[key] = name
        self.cabs[key] = item
        self._container_index_built = False

    def get_cab(self, name: str) -> Union[SerializedFile, EndianBinaryReader, None]:
        """
        Returns the cab file with the given name.

        Parameters
        ----------
        name : str
            The name of the cab file.

        Returns
        -------
        File
            The cab file.
        """
        return self.cabs.get(simplify_name(name), None)

    def source_path_of(self, file) -> Optional[str]:
        """The physical path a loaded file (or anything nested inside a bundle) came from —
        the env.files key of its top-level container — or None if it can't be told."""
        try:
            current = file
            while getattr(current, "parent", self) is not self and current.parent is not None:
                current = current.parent
            cached = self._source_path_cache.get(id(current), 0)
            if cached != 0:
                return cached
            path = next((p for p, f in self.files.items() if f is current), None)
            self._source_path_cache[id(current)] = path
            return path
        except Exception:
            return None

    def pick_cab_alternative(self, name: str, assets_file=None) -> Optional[Tuple[str, object]]:
        """(registered source name, item) of the cab `name` that lives CLOSEST to
        `assets_file` when several loose files of that name are loaded — e.g. Folder A
        and Folder B each with a resources.assets.resS: the one in the same folder as the
        assets file being read wins, the way Unity itself resolves an external resource
        (relative to the file that declares it), instead of whichever happened to take
        the name slot first. None when there is nothing to choose between (the caller
        then uses the ordinary slot)."""
        key = simplify_name(name)
        alts = self._cab_alternatives.get(key)
        if not alts or assets_file is None:
            return None
        # Hot path (PPtr.deref calls this for every cross-file reference): nothing to
        # choose between and no skipped duplicate that could be promoted -> done at once.
        if len(alts) < 2 and not self.skipped_duplicates:
            return None
        src = self.source_path_of(assets_file)
        if not src:
            return None
        src_dir = os.path.dirname(os.path.abspath(src))
        if self.skipped_duplicates:
            mark = (key, src_dir, len(self.skipped_duplicates))
            if mark not in self._promote_done:
                self._promote_done.add(mark)
                self._promote_near_duplicates(key, src_dir)
                alts = self._cab_alternatives.get(key, alts)
        if len(alts) < 2:
            return None
        slot_name = self._cab_source_names.get(key)
        best = None
        best_score = -1
        real = 0
        for alt_name, item in alts.items():
            path = alt_name if os.path.isabs(alt_name) else os.path.join(self.path, alt_name)
            if not os.path.isfile(path):
                continue  # a bundle-internal entry, not a loose file: nothing to compare
            real += 1
            try:
                common = os.path.commonpath([os.path.dirname(os.path.abspath(path)), src_dir])
            except ValueError:
                common = ""
            score = len([p for p in common.replace("\\", "/").split("/") if p])
            if score > best_score or (score == best_score and alt_name == slot_name):
                best, best_score = (alt_name, item), score
        return best if real >= 2 else None

    def _promote_near_duplicates(self, key: str, src_dir: str) -> None:
        """A same-named file sitting in `src_dir` (next to the assets file being read) that
        load-time de-duplication skipped because its sampled content matched another,
        farther copy: load it for real. Sharing the far copy would be harmless for READING
        identical bytes, but any write (an import appending to the resource) would then
        land in the wrong folder's file — and the content signature only samples the head
        and tail, so "identical" is not a guarantee either."""
        for skipped, _kept in list(self.skipped_duplicates):
            if simplify_name(skipped) != key or skipped in self.files:
                continue
            if os.path.normcase(os.path.dirname(os.path.abspath(skipped))) != os.path.normcase(src_dir):
                continue
            if not os.path.isfile(skipped):
                continue
            self._dedup_bypass.add(skipped)
            try:
                self.load_file(skipped, name=skipped, is_dependency=True)
            finally:
                self._dedup_bypass.discard(skipped)
            self.skipped_duplicates = [p for p in self.skipped_duplicates if p[0] != skipped]

    def get_cab_near(self, name: str, assets_file=None):
        picked = self.pick_cab_alternative(name, assets_file)
        return picked[1] if picked is not None else self.get_cab(name)

    def is_file_loaded(self, path: str) -> bool:
        norm = os.path.normcase(os.path.abspath(path))
        return any(os.path.normcase(os.path.abspath(k)) == norm for k in self.files)

    def reset_missing_files_cache(self) -> None:
        """Clears find_file()'s negative cache (_missing_files — see its own
        docstring in __init__). Needed whenever something that could make a
        previously-failed reference resolvable NOW happens after that failure was
        already recorded — the cache's own early check (`if name in
        self._missing_files: raise ...`) runs BEFORE find_file() ever reaches
        external_cab_resolver, so simply setting/extending that hook after a name
        has already failed once would otherwise never actually get retried for that
        exact name again. Real, confirmed case this exists for: a caller wires
        external_cab_resolver (or extends the CabIndex it reads from) in response
        to an already-failed resolution the user just asked to retry — see
        dialogs/addressables_resolver_dialog.py."""
        with self._find_file_lock:
            self._missing_files.clear()

    def load_assets(self, assets, open_f, type_filters=None, progress_callback=None):
        type_filters = type_filters or {}
        split_files = []
        total = len(assets)
        for i, path in enumerate(assets):
            if progress_callback is not None:
                progress_callback(0, i, total, path)   # level=0, top level
            splitMatch = reSplit.match(path)
            if splitMatch:
                basepath, _basename = splitMatch.groups()
                if basepath in split_files:
                    continue
                split_files.append(basepath)
                data = self._load_split_file(basepath)
                path = basepath
            else:
                data = open_f(path)
            self.load_file(data, name=path, type_filter=type_filters.get(path), progress_callback=progress_callback)
        if progress_callback is not None:
            progress_callback(0, total, total, "Done")

    def find_file(self, name: str, is_dependency: bool = True) -> Union[File, None]:
        """
        Finds a file in the environment.

        Parameters
        ----------
        name : str
            The name of the file.
        is_dependency : bool
            Whether the file is a dependency.

        Returns
        -------
        File | None
            The file if it was found, otherwise None.
        """
        simple_name = simplify_name(name)
        cab = self.get_cab(simple_name)
        if cab:
            return cab

        # Direct-path stat is cheap (one fs.exists() call) — checked before the
        # negative cache below so a name that becomes available at exactly this path
        # after being recorded missing (e.g. extracted/written by some other part of
        # the app between calls) isn't a permanent false negative. The negative cache
        # still protects what actually matters (the expensive O(n) local_files scans
        # further below), it just no longer skips this one cheap stat on a repeat miss.
        fp = self.fs.sep.join([self.path, name])
        if self.fs.exists(fp):
            return self.load_file(fp, name=name, is_dependency=is_dependency)

        # Checked after get_cab()/the direct-path stat (cheap, always current — a name
        # recorded missing here can still be satisfied later by an explicit
        # load_file()/register_cab() for it, e.g. CabBrowserDialog pulling in a
        # declared dependency after the fact) but before the expensive part below (up
        # to two full local_files scans) — see _missing_files' docstring in __init__.
        #
        # Everything touching _missing_files/local_files/local_files_simple is held
        # under self._find_file_lock — see that attribute's own docstring in
        # __init__ for the real, reproduced concurrent-caller corruption this closes.
        # Deliberately released again before load_file() runs below: that call has
        # its own, separate concerns (cab registration, ...) and holding this lock
        # across it would just be a wider lock than the actually-shared state needs,
        # same "smallest scope that's still correct" precedent as
        # ObjectReader.get_raw_data()'s own reader.lock usage.
        resolver_needed = False
        with self._find_file_lock:
            if name in self._missing_files:
                raise FileNotFoundError(f"File {name} not found in {self.path}")

            if len(self.local_files) == 0 and self.path:
                for root, _, files in self.fs.walk(self.path):
                    for f in files:
                        self.local_files.append(self.fs.sep.join([root, f]))
                        self.local_files_simple.append(self.fs.sep.join([root, simplify_name(f)]))
                    if not self.local_search_recursive:
                        break

            if name in self.local_files:
                fp = name
            elif simple_name in self.local_files_simple:
                fp = self.local_files[self.local_files_simple.index(simple_name)]
            else:
                fp = next((f for f in self.local_files if f.endswith(name)), None)
                if not fp:
                    fp = next(
                        (f for f in self.local_files_simple if f.endswith(simple_name)),
                        None,
                    )
                if not fp:
                    resolver_needed = True

        if resolver_needed:
            # Tried OUTSIDE _find_file_lock, deliberately — load_file() below can
            # itself recurse into further dependency resolution (register_cab(),
            # nested load_dependencies() calls, ...), and this lock isn't reentrant;
            # same reasoning the comment above already gives for releasing the lock
            # before the plain loose-file load_file() call at the end of this
            # function. See external_cab_resolver's own docstring in __init__.
            if self.external_cab_resolver is not None:
                resolved = self.external_cab_resolver(name)
                if resolved:
                    self.load_file(resolved, is_dependency=True)
                    cab = self.get_cab(simple_name)
                    if cab:
                        return cab
            with self._find_file_lock:
                self._missing_files.add(name)
            raise FileNotFoundError(f"File {name} not found in {self.path}")

        return self.load_file(fp, name=name, is_dependency=is_dependency)


def simplify_name(name: str) -> str:
    """Simplifies a name by:
    - removing the extension
    - removing the path
    - converting to lowercase
    """
    return ntpath.basename(name).lower()


# Head+tail sample size for content_signature(). Large enough that unrelated files of the
# same size practically never collide, small enough that fingerprinting a 10GB+ bundle (see
# CLAUDE.md's lazy-loading rationale) costs two 1MB reads instead of a full-file hash.
_DEDUP_SAMPLE_BYTES = 1024 * 1024


def content_size(source) -> Optional[int]:
    """The byte size content_signature() would report, without reading anything; None if unknown."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        return len(source)
    if hasattr(source, "seek") and hasattr(source, "tell"):
        try:
            pos = source.tell()
            size = source.seek(0, io.SEEK_END)
            source.seek(pos)
            return size
        except (OSError, ValueError, io.UnsupportedOperation):
            return None
    return None


def content_signature(source) -> Optional[Tuple[int, bytes]]:
    """Cheap (size, partial-hash) fingerprint of a file's actual bytes, independent of its
    path or name. Used to recognize the same physical file loaded twice under different
    paths (a bundle rescanned via a sibling _extracted/ folder, a backup copy, a duplicate
    mod install, ...) without any hardcoded path/name assumptions. Returns None if the
    source can't be cheaply sampled (e.g. a non-seekable stream) — callers should treat
    that as "unknown, don't dedup" rather than an error.
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        size = len(source)
        h = hashlib.blake2b(digest_size=16)
        h.update(bytes(source[:_DEDUP_SAMPLE_BYTES]))
        if size > _DEDUP_SAMPLE_BYTES:
            h.update(bytes(source[-_DEDUP_SAMPLE_BYTES:]))
        return size, h.digest()

    if hasattr(source, "seek") and hasattr(source, "read"):
        try:
            pos = source.tell()
            size = source.seek(0, io.SEEK_END)
            source.seek(0)
            h = hashlib.blake2b(digest_size=16)
            h.update(source.read(_DEDUP_SAMPLE_BYTES))
            if size > _DEDUP_SAMPLE_BYTES:
                source.seek(max(size - _DEDUP_SAMPLE_BYTES, 0))
                h.update(source.read(_DEDUP_SAMPLE_BYTES))
            source.seek(pos)
        except (OSError, ValueError, io.UnsupportedOperation):
            return None
        return size, h.digest()

    return None


class CabCollision(NamedTuple):
    """Two different source files both reduced (via simplify_name — basename, lowercased)
    to the same Environment.cabs key. kept_* is whichever currently holds the slot;
    rejected_* is the one that would otherwise have silently overwritten it."""
    key: str
    kept_name: str
    kept_item: object
    rejected_name: str
    rejected_item: object
